"""The decision pipeline — lifecycle steps 4–12 (docs/spec/02 §5).

This is the enforcement boundary in code. Given a resolved tool, the arguments
the model emitted, and the injected run environment, it:

  ④ resolves the risk class (UNKNOWN/FORBIDDEN -> deny)
  ⑤ validates arguments against the declared schema (malformed -> deny, never guessed)
  ⑥ rehydrates placeholder tokens (an unissued token -> deny + exfiltration flag)
  ⑦ evaluates policy (authoritative) -> ALLOW / DENY / REQUIRE_APPROVAL
  ⑧ checks idempotency (seen -> stored result, no execution)
  ⑨ forwards to upstream
  ⑩⑪ redacts the result and quarantines untrusted fields
  ⑫ writes the audit entry

Every step can fail closed independently. The in-loop guard (Phase 4) calls the
same policy engine first; the proxy is the authoritative repeat.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from sentinel.contracts.audit import AuditEntry
from sentinel.contracts.decision import DecisionContext, InjectedEnv, PolicyDecision
from sentinel.contracts.enums import Disposition, Provenance, RiskClass
from sentinel.contracts.reasons import ReasonCode, render_reason
from sentinel.contracts.tools import ToolDescriptor
from sentinel.policy import evaluate
from sentinel.policy.rules import PolicySet
from sentinel.proxy.context import build_context
from sentinel.proxy.idempotency import IdempotencyGuard
from sentinel.redaction.engine import (
    RedactionSession,
    _redact_string,
    redact_result,
    rehydrate_arguments,
)
from sentinel.redaction.quarantine import QuarantineWrapper, UnissuedTokenError


@dataclass
class Signals:
    """Run-level provenance/injection signals the runtime tracks and passes in."""
    untrusted_in_context: bool = False
    injection_suspicion_score: float = 0.0
    provenance_present: tuple[Provenance, ...] = ()
    model_stated_intent: Optional[str] = None


@dataclass
class InterceptOutcome:
    disposition: Disposition
    decision: PolicyDecision
    audit_entry: AuditEntry
    result: Optional[dict] = None       # redacted + quarantined, if forwarded/replayed
    executed: bool = False
    idempotent_replay: bool = False
    security_event: bool = False
    upstream_error: bool = False
    quarantined_fields: tuple[str, ...] = ()
    redaction_count: int = 0


def _get_path(obj: dict, path: str) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _redact_arg_strings(arguments: dict, session: RedactionSession) -> dict:
    """Pattern-scrub PII out of argument STRING values (deep copy). Tokens and
    non-PII strings pass through unchanged, so a call with no raw PII (the normal
    case) is untouched and its argument hash is unchanged."""
    def w(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: w(v) for k, v in node.items()}
        if isinstance(node, list):
            return [w(v) for v in node]
        if isinstance(node, str):
            return _redact_string(node, {}, session)
        return node
    return w(arguments)


def _validate_schema(arguments: dict, schema: dict) -> Optional[str]:
    """Minimal JSON-schema check: required fields present + loose type match.
    Returns an error string, or None if valid. Malformed -> the caller denies;
    a money-moving call's arguments are never guessed or repaired."""
    if not schema:
        return None
    for req in schema.get("required", []):
        if req not in arguments or arguments[req] is None:
            return f"missing required argument '{req}'"
    props = schema.get("properties", {})
    type_ok = {"string": str, "integer": int, "boolean": bool, "object": dict, "number": (int, float)}
    for key, value in arguments.items():
        spec = props.get(key)
        if not spec:
            continue
        expected = spec.get("type")
        py = type_ok.get(expected)
        if py and value is not None and not isinstance(value, py):
            # bool is a subclass of int; reject bool where integer expected
            if expected == "integer" and isinstance(value, bool):
                return f"argument '{key}' must be an integer, not a boolean"
            if not isinstance(value, py):
                return f"argument '{key}' has wrong type (expected {expected})"
    return None


class Interceptor:
    def __init__(self, *, upstream, policy_set: PolicySet, ledger, session: RedactionSession,
                 quarantine: QuarantineWrapper, idempotency: IdempotencyGuard,
                 run_meta: dict[str, str],
                 trace: Optional[Callable[[str, dict], None]] = None,
                 redact: bool = True, quarantine_enabled: bool = True):
        self.upstream = upstream
        self.policy_set = policy_set
        self.ledger = ledger
        self.session = session
        self.quarantine = quarantine
        self.idempotency = idempotency
        self.run_meta = run_meta          # run_id, agent_id, agent_version, operator_id, policy_set_id, git_commit
        self.trace = trace or (lambda t, p: None)
        # ablation toggles: policy is always on in the interceptor; redaction and
        # quarantine can be disabled to measure each control's marginal effect.
        self.redact = redact
        self.quarantine_enabled = quarantine_enabled

    def handle_call(self, descriptor: ToolDescriptor, arguments: dict, env: InjectedEnv,
                    signals: Signals, step_id: str, call_id: str) -> InterceptOutcome:
        rm = self.run_meta
        # Normally the model only ever saw tokens, so arguments carry no raw PII.
        # But defense in depth: pattern-scrub argument STRINGS before they reach the
        # decision context or the audit ledger, so a raw value that slipped through
        # (fabricated, or copied from an un-tokenized field) is never persisted.
        # Rehydration/schema/forwarding below still use the original `arguments`.
        redacted_args = _redact_arg_strings(arguments, self.session) if self.redact else arguments
        ctx = build_context(
            descriptor=descriptor, arguments=redacted_args, env=env, run_meta=rm,
            policy_version=self.policy_set.version, step_id=step_id, call_id=call_id,
            untrusted_in_context=signals.untrusted_in_context,
            injection_score=signals.injection_suspicion_score,
            provenance_present=signals.provenance_present,
            model_stated_intent=signals.model_stated_intent)
        idem_key = ctx.idempotency_key
        self.trace("tool_call_requested", {"tool": descriptor.name, "risk_class": descriptor.risk_class.value})

        # ⑤ schema validation (before policy; a malformed call is denied, not guessed)
        err = _validate_schema(arguments, descriptor.input_schema)
        if err is not None:
            return self._deny(ctx, ReasonCode.DENY_SCHEMA_INVALID, {"tool": descriptor.name},
                              outcome="blocked", detail=err)

        # ⑥ rehydrate tokens; an unissued token is a suspected exfiltration attempt
        try:
            rehydrated = rehydrate_arguments(arguments, descriptor.rehydratable_arg_paths, self.session)
        except UnissuedTokenError as exc:
            self.trace("security_event", {"kind": "unissued_token", "tool": descriptor.name})
            return self._deny(ctx, ReasonCode.DENY_SUSPECTED_EXFILTRATION, {"tool": descriptor.name},
                              outcome="security_event", security_event=True, detail=str(exc.token))

        # ⑦ authoritative policy evaluation
        decision = evaluate(self.policy_set, ctx)
        self.trace("policy_decision", {"disposition": decision.disposition.value,
                                       "reason_code": decision.reason_code.value,
                                       "human_reason": decision.human_reason,
                                       "matched_rules": list(decision.matched_rules)})

        if decision.disposition == Disposition.DENY:
            entry = self._audit(ctx, decision, outcome="blocked")
            return InterceptOutcome(Disposition.DENY, decision, entry)

        if decision.disposition == Disposition.REQUIRE_APPROVAL:
            self.trace("approval_requested", {"tool": descriptor.name, "amount": ctx.money.amount_minor})
            entry = self._audit(ctx, decision, outcome="escalated")
            return InterceptOutcome(Disposition.REQUIRE_APPROVAL, decision, entry)

        # ⑧ idempotency: for mutating calls, atomically reserve the key BEFORE
        # forwarding. A completed call replays its stored result; a call already
        # reserved (in-flight, or a prior ambiguous failure) or racing a duplicate
        # is REFUSED — re-executing a money movement is worse than denying it.
        is_write = descriptor.risk_class in (RiskClass.REVERSIBLE_WRITE,
                                             RiskClass.IRREVERSIBLE_WRITE, RiskClass.MONEY_MOVEMENT)
        if is_write:
            state, stored = self.idempotency.begin(idem_key)
            if state == "replay":
                self.trace("idempotent_replay", {"tool": descriptor.name})
                entry = self._audit(ctx, decision, outcome="idempotent_replay")
                return InterceptOutcome(Disposition.ALLOW, decision, entry, result=stored,
                                        executed=False, idempotent_replay=True)
            if state == "refuse":
                self.trace("idempotency_refused", {"tool": descriptor.name})
                return self._deny(ctx, ReasonCode.DENY_UPSTREAM_ERROR, {"tool": descriptor.name},
                                  outcome="idempotency_refused",
                                  detail="a prior identical call is in flight or failed ambiguously")

        # ⑨ forward to upstream with rehydrated arguments — fail CLOSED on error
        # (CLAUDE.md rule 2: an upstream error is a DENY, never an ALLOW).
        self.trace("tool_call_forwarded", {"tool": descriptor.upstream_name})
        try:
            raw_result = self.upstream.call_tool(descriptor.upstream_name, rehydrated)
        except Exception:
            # The outcome is UNCERTAIN — the upstream may have executed before it
            # raised. For a write we KEEP the reservation (a retry is refused above)
            # so we can never double-execute; for a read we release it (safe to retry).
            if is_write:
                self.trace("run_failed", {"tool": descriptor.upstream_name, "error": "upstream_error",
                                          "reserved": True})
            else:
                self.idempotency.abandon(idem_key)
                self.trace("run_failed", {"tool": descriptor.upstream_name, "error": "upstream_error"})
            return self._deny(ctx, ReasonCode.DENY_UPSTREAM_ERROR, {"tool": descriptor.name},
                              outcome="upstream_error", upstream_error=True)

        # ⑩ redact PII in the result (ablation: may be disabled)
        if self.redact:
            redacted, detections = redact_result(raw_result, descriptor.pii_map, self.session)
        else:
            redacted, detections = raw_result, []

        # ⑪ quarantine untrusted free-text fields (per-run nonce; ablation: may be disabled)
        quarantined_fields: list[str] = []
        if self.quarantine_enabled:
            for fp in descriptor.provenance_map:
                if fp.provenance == Provenance.UNTRUSTED:
                    _wrap_field(redacted, fp.field_path, self.quarantine, quarantined_fields)
        if quarantined_fields:
            self.trace("quarantine_applied", {"fields": quarantined_fields})

        if descriptor.risk_class in (RiskClass.REVERSIBLE_WRITE, RiskClass.IRREVERSIBLE_WRITE,
                                     RiskClass.MONEY_MOVEMENT):
            self.idempotency.record(idem_key, redacted)

        self.trace("tool_result_received", {"tool": descriptor.name, "redactions": len(detections)})
        entry = self._audit(ctx, decision, outcome="forwarded")
        return InterceptOutcome(
            Disposition.ALLOW, decision, entry, result=redacted, executed=True,
            quarantined_fields=tuple(quarantined_fields), redaction_count=len(detections))

    # -- helpers --
    def _deny(self, ctx, reason_code, params, *, outcome, security_event=False,
              upstream_error=False, detail="") -> InterceptOutcome:
        decision = PolicyDecision(
            disposition=Disposition.DENY, reason_code=reason_code,
            human_reason=render_reason(reason_code, **params),
            deciding_rule="__proxy__", policy_set_version=self.policy_set.version)
        self.trace("policy_decision", {"disposition": "DENY", "reason_code": reason_code.value,
                                       "human_reason": decision.human_reason})
        entry = self._audit(ctx, decision, outcome=outcome)
        return InterceptOutcome(Disposition.DENY, decision, entry,
                                security_event=security_event, upstream_error=upstream_error)

    def _audit(self, ctx: DecisionContext, decision: PolicyDecision, *, outcome: str) -> AuditEntry:
        return self.ledger.record(
            run_id=ctx.run_id, step_id=ctx.step_id, call_id=ctx.call_id,
            timestamp_ms=ctx.env.now_epoch_ms, tool_name=ctx.tool_name,
            risk_class=ctx.risk_class, arguments_redacted=ctx.arguments_redacted,
            argument_hash=ctx.argument_hash, decision=decision, outcome=outcome,
            policy_set_version=self.policy_set.version,
            agent_version=self.run_meta.get("agent_version"),
            git_commit=self.run_meta.get("git_commit"),
        )


class NullInterceptor:
    """The counterfactual: NO control plane. Forwards every call straight to
    upstream — no policy, no redaction, no quarantine, no audit decision. This is
    the "guardrails off" world used for the red-team A/B condition A and the
    guardrail-overhead measurement. It is the honest representation of an agent
    with a naive MCP connection: money moves, PII flows, injection is obeyed.
    """

    def __init__(self, *, upstream, ledger, run_meta: dict, trace=None, **_ignored):
        self.upstream = upstream
        self.ledger = ledger
        self.run_meta = run_meta
        self.trace = trace or (lambda t, p: None)

    def handle_call(self, descriptor: ToolDescriptor, arguments: dict, env, signals,
                    step_id: str, call_id: str) -> InterceptOutcome:
        from sentinel.contracts.audit import GENESIS_HASH
        decision = PolicyDecision(disposition=Disposition.ALLOW,
                                  reason_code=ReasonCode.ALLOW_EXPLICIT_RULE,
                                  human_reason="(no control plane — allowed unconditionally)")
        self.trace("tool_call_forwarded", {"tool": descriptor.upstream_name, "guardrails": "off"})
        try:
            result = self.upstream.call_tool(descriptor.upstream_name, arguments)
        except Exception:
            entry = AuditEntry(entry_id="none", run_id=self.run_meta["run_id"], timestamp_ms=0,
                               sequence=0, previous_hash=GENESIS_HASH, entry_hash="none")
            return InterceptOutcome(Disposition.ALLOW, decision, entry, result=None, upstream_error=True)
        entry = AuditEntry(entry_id="none", run_id=self.run_meta["run_id"], timestamp_ms=0,
                           sequence=0, previous_hash=GENESIS_HASH, entry_hash="none")
        return InterceptOutcome(Disposition.ALLOW, decision, entry, result=result, executed=True)


def _wrap_field(obj: Any, path: str, quarantine: QuarantineWrapper, wrapped: list[str]) -> None:
    """Wrap a single (possibly ``items[]``) field's string value(s) in the nonce
    quarantine, in place."""
    parts = path.split(".")

    def walk(node: Any, ps: list[str], trail: str):
        if not ps:
            return
        head, rest = ps[0], ps[1:]
        if head.endswith("[]"):
            key = head[:-2]
            seq = node.get(key) if isinstance(node, dict) else None
            if isinstance(seq, list):
                for i, elem in enumerate(seq):
                    if not rest and isinstance(elem, str):
                        seq[i], _ = quarantine.wrap(elem)
                        wrapped.append(f"{trail}{key}[{i}]")
                    else:
                        walk(elem, rest, f"{trail}{key}[{i}].")
        else:
            if isinstance(node, dict) and head in node:
                if not rest and isinstance(node[head], str):
                    node[head], _ = quarantine.wrap(node[head])
                    wrapped.append(f"{trail}{head}")
                else:
                    walk(node[head], rest, f"{trail}{head}.")

    walk(obj, parts, "")
