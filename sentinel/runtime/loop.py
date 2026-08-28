"""The in-house agent loop (docs/spec/06 §5).

Outline: build messages (system + operator task + quarantined attachments), then
loop — call the provider, and for each tool call run the in-loop guard, forward
through the proxy or append a structured denial, handle escalations, and enforce
resource ceilings — until the model stops calling tools or a ceiling trips.

The loop contains NO provider-specific branching. Both enforcement layers build
their context with the same ``build_context`` and evaluate the same pure engine;
a mismatch is a logged ``LAYER_DISAGREEMENT`` incident and the more restrictive
outcome is taken.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from sentinel.audit.ledger import AuditLedger, InMemoryLedgerRepository
from sentinel.common.ids import IdFactory
from sentinel.contracts.approvals import ApprovalRequest
from sentinel.contracts.decision import InjectedEnv
from sentinel.contracts.enums import BindingRole, Disposition, RunMode, TerminalState
from sentinel.contracts.runs import RunRecord
from sentinel.metering.meter import MeterAccumulator
from sentinel.policy import evaluate
from sentinel.policy.rules import PolicySet
from sentinel.providers.base import ProviderResponse
from sentinel.providers.factory import build_manager
from sentinel.proxy.classifier import descriptor_index, reconcile
from sentinel.proxy.context import build_context
from sentinel.proxy.idempotency import IdempotencyGuard
from sentinel.proxy.interceptor import Interceptor, Signals
from sentinel.redaction.engine import RedactionSession
from sentinel.redaction.quarantine import QuarantineWrapper
from sentinel.runtime.agent import AgentDefinition
from sentinel.runtime.trace import TraceEmitter


class RunSuspended(Exception):
    """Raised when a run escalates and no synchronous approval handler is set.
    Carries the approval so the caller can persist state and resume later."""

    def __init__(self, approval: ApprovalRequest, state: dict):
        self.approval = approval
        self.state = state
        super().__init__(f"run suspended awaiting approval {approval.id}")


# approval handler: given the request, return True to approve, False to reject.
ApprovalHandler = Callable[[ApprovalRequest], bool]

_INJECTION_MARKERS = ("ignore previous", "ignore all previous", "system:", "as an administrator",
                      "you must", "new instructions", "disregard", "refund to", "send money",
                      "override", "actually, ")


def _injection_score(text: str) -> float:
    low = text.lower()
    hits = sum(1 for m in _INJECTION_MARKERS if m in low)
    return min(1.0, hits / 3.0)      # signal only — never a gate


@dataclass
class RunConfig:
    operator_id: str = "operator"
    known_counterparties: frozenset = frozenset()
    operator_scope_entities: frozenset = frozenset()
    seed: int = 20260821
    mode: RunMode = RunMode.FIXTURE


class AgentRunner:
    def __init__(self, *, cassette_dir: str, cassette_mode: str = "auto",
                 clock_ms: Callable[[], int] | None = None, id_factory: IdFactory | None = None,
                 ledger: AuditLedger | None = None, approvals=None, git_commit: str = "dev",
                 price_table: dict | None = None, fixture_version: str = "0",
                 trace_sink=None):
        self._cassette_dir = cassette_dir
        self._cassette_mode = cassette_mode
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._ids = id_factory or IdFactory()
        self._ledger = ledger or AuditLedger(InMemoryLedgerRepository())
        self._approvals = approvals
        self._git = git_commit
        self._prices = price_table or {}
        self._fixture_version = fixture_version
        self._trace_sink = trace_sink

    @property
    def ledger(self) -> AuditLedger:
        return self._ledger

    def run(self, agent: AgentDefinition, *, upstream, policy_set: PolicySet, task: str,
            attachments: Optional[dict] = None, config: Optional[RunConfig] = None,
            approval_handler: Optional[ApprovalHandler] = None,
            enforcement: str = "on", model_id: Optional[str] = None,
            model_tier: Optional[str] = None,
            redaction: bool = True, quarantine_enabled: bool = True) -> RunRecord:
        cfg = config or RunConfig()
        guardrails_on = enforcement == "on"
        run_id = self._ids.run()
        started = self._clock_ms()
        emitter = TraceEmitter(run_id, self._clock_ms, sink=self._trace_sink)
        meter = MeterAccumulator(self._prices)

        # discovery + scope validation
        report = reconcile(upstream.list_tools())
        descriptors = descriptor_index(report)
        available = {t.name for t in report.callable_manifest}
        agent.validate_scope(available)
        manifest = [_tool_schema(descriptors[n]) for n in agent.tool_scope if n in descriptors]

        # per-run redaction + quarantine, seeded so fixture/replay is deterministic
        session = RedactionSession(run_id, salt=cfg.seed.to_bytes(16, "big"))
        quarantine = QuarantineWrapper(nonce=f"{cfg.seed:032x}")
        run_meta = dict(run_id=run_id, agent_id=agent.id, agent_version=agent.version,
                        operator_id=cfg.operator_id, policy_set_id=policy_set.id,
                        git_commit=self._git)
        if guardrails_on:
            interceptor = Interceptor(
                upstream=upstream, policy_set=policy_set, ledger=self._ledger, session=session,
                quarantine=quarantine, idempotency=IdempotencyGuard(), run_meta=run_meta,
                trace=lambda t, p: emitter.emit(t, p),
                redact=redaction, quarantine_enabled=quarantine_enabled)
        else:
            from sentinel.proxy.interceptor import NullInterceptor
            interceptor = NullInterceptor(upstream=upstream, ledger=self._ledger, run_meta=run_meta,
                                          trace=lambda t, p: emitter.emit(t, p))

        # provider manager. Offline (default): the agent's deterministic brain,
        # cassette-wrapped. Live (SENTINEL_LIVE + a key): real Groq/Gemini in
        # failover order. The factory owns that choice so this loop names no
        # provider (CLAUDE.md rule 5a); it only gets a manager + the model to call.
        manager, call_model = build_manager(
            brain=agent.brain, model_id=model_id or (agent.id + "-brain"),
            model_tier=model_tier, cassette_dir=self._cassette_dir,
            cassette_mode=self._cassette_mode, policy_version=policy_set.version,
            fixture_version=self._fixture_version, system_prompt=agent.system_prompt,
            clock_ms=self._clock_ms)
        manager.probe(call_model)

        # initial messages; the attachment is UNTRUSTED and quarantined by us
        untrusted_present = False
        messages = [{"role": "system", "content": agent.system_prompt},
                    {"role": "user", "content": task}]
        inj_score = 0.0
        if attachments:
            for name, content in attachments.items():
                wrapped, seen = quarantine.wrap(str(content), provenance="UNTRUSTED")
                messages.append({"role": "user", "content": f"[attachment: {name}]\n{wrapped}"})
                untrusted_present = True
                inj_score = max(inj_score, _injection_score(str(content)))
                if seen:
                    emitter.emit("security_event", {"kind": "nonce_in_attachment", "attachment": name})

        emitter.emit("run_started", {"agent": agent.id, "policy_set": policy_set.id,
                                     "prompt_hash": agent.system_prompt_hash})

        # accumulators
        spend_run = 0
        collected_run = 0
        per_tool: dict[str, int] = {}
        per_class: dict[str, int] = {}
        tool_calls = 0
        denials: dict[str, int] = {}
        approvals_requested = approvals_granted = approvals_rejected = 0
        malformed = 0
        schema_violations = 0
        step = 0
        terminal = TerminalState.COMPLETED
        output: dict | None = None

        def env_now() -> InjectedEnv:
            now = self._clock_ms()
            return InjectedEnv(
                now_epoch_ms=now, now_local_hour=(now // 3_600_000) % 24, now_weekday=(now // 86_400_000) % 7,
                spend_run_minor=spend_run, collected_run_minor=collected_run,
                per_tool_count_run=dict(per_tool),
                per_class_count_window=dict(per_class), tool_call_count_run=tool_calls,
                elapsed_run_ms=now - started, known_counterparties=cfg.known_counterparties,
                operator_scope_entities=cfg.operator_scope_entities)

        malformed_retry_used = False
        while True:
            if step >= agent.ceilings.max_steps:
                terminal = TerminalState.ABORTED_CEILING
                emitter.emit("run_aborted", {"reason": "max_steps"})
                break
            if self._clock_ms() - started > agent.ceilings.max_wall_clock_ms:
                terminal = TerminalState.TIMEOUT
                emitter.emit("run_aborted", {"reason": "wall_clock"})
                break

            emitter.emit("step_started", {"step": step})
            resp: ProviderResponse = manager.complete(messages=messages, tools=manifest, model=call_model)
            meter.add_call(resp)

            if resp.malformed_tool_call:
                malformed += 1
                if malformed_retry_used:
                    terminal = TerminalState.ABORTED_MALFORMED_TOOL_CALLS
                    emitter.emit("run_failed", {"reason": "malformed_tool_call_twice"})
                    break
                malformed_retry_used = True
                messages.append({"role": "user", "content":
                                 "Your last tool call was malformed. Re-issue it with valid JSON "
                                 "arguments matching the tool schema. Do not guess money amounts."})
                step += 1
                continue

            if resp.text is not None and not resp.has_tool_calls:
                emitter.emit("model_reasoning", {"text_len": len(resp.text)})
                output = _parse_output(resp.text)
                if not _validate_output(output, agent.output_schema):
                    schema_violations += 1
                    if not malformed_retry_used:
                        malformed_retry_used = True
                        messages.append({"role": "user", "content":
                                         "Your final output did not match the required schema. Re-emit it."})
                        step += 1
                        continue
                    terminal = TerminalState.FAILED
                break

            for tc in resp.tool_calls:
                step_id = self._ids.step()
                call_id = self._ids.call()
                descriptor = descriptors.get(tc.name)
                if descriptor is None:
                    # a tool outside the manifest — should be impossible; treat as unknown
                    from sentinel.contracts.enums import ClassificationStatus, RiskClass
                    from sentinel.contracts.tools import ToolDescriptor
                    descriptor = ToolDescriptor(name=tc.name, upstream_name=tc.name,
                                                risk_class=RiskClass.UNKNOWN,
                                                classification_status=ClassificationStatus.UNCLASSIFIED)
                env = env_now()
                signals = Signals(untrusted_in_context=untrusted_present,
                                  injection_suspicion_score=inj_score,
                                  model_stated_intent=(resp.text or None))
                # context is always built (cheap); the in-loop guard evaluates it
                # only when guardrails are on.
                ctx = build_context(descriptor=descriptor, arguments=tc.arguments, env=env,
                                    run_meta=run_meta, policy_version=policy_set.version,
                                    step_id=step_id, call_id=call_id,
                                    untrusted_in_context=untrusted_present, injection_score=inj_score)
                guard = None
                if guardrails_on:
                    t0 = time.perf_counter()
                    guard = evaluate(policy_set, ctx)
                    meter.add_policy_eval((time.perf_counter() - t0) * 1000)

                outcome = interceptor.handle_call(descriptor, tc.arguments, env, signals, step_id, call_id)
                tool_calls += 1
                per_tool[tc.name] = per_tool.get(tc.name, 0) + 1
                per_class[descriptor.risk_class.value] = per_class.get(descriptor.risk_class.value, 0) + 1

                # layer agreement (docs/spec/06 §5.2)
                if guard is not None and guard.disposition != outcome.decision.disposition:
                    emitter.emit("layer_disagreement", {
                        "tool": tc.name, "in_loop": guard.disposition.value,
                        "proxy": outcome.decision.disposition.value})

                disp = outcome.decision.disposition
                if disp == Disposition.DENY:
                    denials[outcome.decision.reason_code.value] = \
                        denials.get(outcome.decision.reason_code.value, 0) + 1
                    messages.append(_tool_msg(tc, f"DENIED by policy: {outcome.decision.human_reason}"))
                elif disp == Disposition.REQUIRE_APPROVAL:
                    approvals_requested += 1
                    approval = self._make_approval(ctx, outcome.decision, untrusted_present)
                    emitter.emit("approval_requested", {"approval_id": approval.id if approval else None,
                                                        "summary": _summarise(ctx)})
                    if approval_handler is None:
                        # no synchronous handler -> suspend; caller persists + resumes
                        # The run-scoped accumulators MUST travel with the suspend
                        # state, or a resume restarts every counter at zero — a run
                        # that suspended at ₹4L collected would resume with no cap.
                        # (Resume is responsible for restoring these into the env.)
                        raise RunSuspended(approval, {
                            "run_id": run_id, "messages": messages, "session": session.dump(),
                            "accumulators": {
                                "spend_run_minor": spend_run,
                                "collected_run_minor": collected_run,
                                "tool_call_count_run": tool_calls,
                                "per_tool_count_run": dict(per_tool),
                                "per_class_count_window": dict(per_class),
                                "untrusted_present": untrusted_present,
                            }})
                    approved = approval_handler(approval)
                    now = self._clock_ms()
                    if self._approvals and approval:
                        self._approvals.resolve(approval.id, approve=approved,
                                                resolver_id=cfg.operator_id, now_ms=now)
                    if approved:
                        # single-use: consume() FIRST and honor its result. If the
                        # approval was already spent or has expired, it is not valid
                        # now — fail closed rather than executing on a stale grant.
                        consumed = True
                        if self._approvals and approval:
                            consumed = self._approvals.consume(approval.id, ctx.argument_hash, now)
                        if not consumed:
                            approvals_rejected += 1
                            emitter.emit("approval_resolved", {"approved": True, "consumed": False})
                            messages.append(_tool_msg(
                                tc, "Approval could not be consumed (expired or already used); refusing to execute."))
                            continue    # do NOT execute on a stale/spent approval
                        approvals_granted += 1
                        # re-validate on resume: re-run through the proxy WITH the approval
                        approved_env = env.model_copy(update={
                            "valid_approval_present": True, "approval_argument_hash": ctx.argument_hash})
                        re_out = interceptor.handle_call(descriptor, tc.arguments, approved_env,
                                                         signals, step_id, self._ids.call())
                        emitter.emit("approval_resolved", {"approved": True})
                        if re_out.executed and descriptor.moves_money and ctx.money.amount_minor:
                            spend_run += ctx.money.amount_minor
                        if (re_out.executed and descriptor.binding_role == BindingRole.COLLECTION
                                and ctx.money.amount_minor):
                            collected_run += ctx.money.amount_minor
                        messages.append(_tool_msg(tc, _result_text(re_out)))
                    else:
                        approvals_rejected += 1
                        emitter.emit("approval_resolved", {"approved": False})
                        messages.append(_tool_msg(tc, "Action was not approved by the reviewer."))
                else:  # ALLOW
                    if outcome.quarantined_fields:
                        untrusted_present = True   # ingested untrusted content: narrow for the rest
                    if outcome.executed and descriptor.moves_money and ctx.money.amount_minor:
                        spend_run += ctx.money.amount_minor
                    if (outcome.executed and descriptor.binding_role == BindingRole.COLLECTION
                            and ctx.money.amount_minor):
                        collected_run += ctx.money.amount_minor
                    messages.append(_tool_msg(tc, _result_text(outcome)))

                if tool_calls >= agent.ceilings.max_tool_calls:
                    terminal = TerminalState.ABORTED_CEILING
                    emitter.emit("run_aborted", {"reason": "max_tool_calls"})
                    break
            else:
                step += 1
                continue
            break  # ceiling break from inner loop

        wall = self._clock_ms() - started
        if terminal == TerminalState.COMPLETED:
            emitter.emit("run_completed", {"steps": step, "tool_calls": tool_calls})
        record = RunRecord(
            id=run_id, agent_id=agent.id, agent_version=agent.version, operator_id=cfg.operator_id,
            policy_set_id=policy_set.id, policy_set_version=policy_set.version,
            system_prompt_hash=agent.system_prompt_hash, mode=cfg.mode, input_task=task,
            terminal_state=terminal, output=output, step_count=step, tool_call_count=tool_calls,
            denials_by_reason=denials, approvals_requested=approvals_requested,
            approvals_granted=approvals_granted, approvals_rejected=approvals_rejected,
            malformed_tool_calls=malformed, schema_violations=schema_violations,
            provider_failovers=manager.failover_count, meter=meter.finalise(wall),
            git_commit=self._git, started_at_ms=started, ended_at_ms=self._clock_ms())
        return record

    def _make_approval(self, ctx, decision, untrusted: bool) -> ApprovalRequest | None:
        if self._approvals is None:
            # lightweight approval object without a store (CLI/tests may pass a handler)
            from sentinel.approvals.store import ApprovalStore, InMemoryApprovalRepository
            self._approvals = ApprovalStore(InMemoryApprovalRepository(), self._ids)
        return self._approvals.create(context=ctx, decision=decision, summary=_summarise(ctx),
                                      now_ms=self._clock_ms(), processed_untrusted=untrusted)


# --- helpers ---
def _tool_schema(d) -> dict:
    return {"name": d.name, "description": d.description, "inputSchema": d.input_schema}


def _tool_msg(tc, content: str) -> dict:
    return {"role": "tool", "tool_call_id": tc.id, "name": tc.name, "content": content}


def _result_text(outcome) -> str:
    import json
    if outcome.result is None:
        return "(no result returned)"
    return json.dumps(outcome.result, ensure_ascii=False)


def _summarise(ctx) -> str:
    from sentinel.common.money import format_amount
    if ctx.money.amount_minor is not None:
        return (f"{ctx.tool_name} for {format_amount(ctx.money.amount_minor, ctx.money.currency or 'INR')}"
                f"{' to ' + ctx.money.counterparty_ref if ctx.money.counterparty_ref else ''}")
    return f"{ctx.tool_name} on {', '.join(ctx.money.target_entities) or 'the target entity'}"


def _parse_output(text: str) -> dict | None:
    import json
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {"summary": text}
    except Exception:
        return {"summary": text}


def _validate_output(output: dict | None, schema: dict) -> bool:
    if not schema:
        return True
    if output is None:
        return False
    for req in schema.get("required", []):
        if req not in output:
            return False
    return True
