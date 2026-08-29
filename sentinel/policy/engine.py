"""The pure evaluation function.

    evaluate(policy_set, decision_context) -> PolicyDecision

Semantics (docs/spec/04 §3.3), specified and tested:

1. **All rules evaluate** — no short-circuit. Every match is recorded in
   ``matched_rules``, which is what makes explanations and the dry-run simulator
   useful.
2. **Most-restrictive-wins:** DENY > REQUIRE_APPROVAL > ALLOW, unconditionally.
   Precedence is by restrictiveness, never file order.
3. **Default is DENY** (``DENY_FAIL_CLOSED``) — the absence of a permitting rule
   is a denial.
4. **Any exception → DENY** (``DENY_POLICY_EVALUATION_ERROR``) and the caller
   aborts the run. An engine that throws cannot be trusted for the rest of a run.
5. **Class floor (system invariant, above policy):** a ``MONEY_MOVEMENT`` tool is
   never auto-allowed. No policy file — however written — can configure this
   away. Enforced here, after combination, and proven by a test.
6. **Approval resolution:** a REQUIRE_APPROVAL becomes ALLOW iff a valid,
   unexpired, argument-bound approval is present for *this exact* call. A DENY is
   never rescued by an approval.
"""

from __future__ import annotations

from sentinel.contracts.decision import DecisionContext, PolicyDecision
from sentinel.contracts.enums import Disposition, Obligation, RiskClass
from sentinel.contracts.reasons import ReasonCode, render_reason
from sentinel.policy.rules import Outcome, PolicySet


def _restrictiveness(d: Disposition) -> int:
    return d.restrictiveness


def evaluate(policy_set: PolicySet, ctx: DecisionContext) -> PolicyDecision:
    try:
        return _evaluate_inner(policy_set, ctx)
    except Exception:  # fail closed — never allow on exception
        return PolicyDecision(
            disposition=Disposition.DENY,
            reason_code=ReasonCode.DENY_POLICY_EVALUATION_ERROR,
            human_reason=render_reason(ReasonCode.DENY_POLICY_EVALUATION_ERROR, tool=ctx.tool_name),
            matched_rules=(),
            deciding_rule=None,
            obligations=(Obligation.AUDIT_ELEVATED,),
            policy_set_version=policy_set.version,
            # note: intentionally does not surface exc detail (could contain data)
        )


def _evaluate_inner(policy_set: PolicySet, ctx: DecisionContext) -> PolicyDecision:
    # 1. Unknown/forbidden tools never reach policy in production (the proxy
    #    denies them first), but the engine also fails closed on them so it is
    #    correct in isolation.
    if ctx.risk_class == RiskClass.UNKNOWN:
        return _decision(Disposition.DENY, ReasonCode.DENY_UNKNOWN_TOOL, None, (), ctx, policy_set,
                        {"tool": ctx.tool_name})
    if ctx.risk_class == RiskClass.FORBIDDEN:
        return _decision(Disposition.DENY, ReasonCode.DENY_FORBIDDEN_TOOL, None, (), ctx, policy_set,
                        {"tool": ctx.tool_name})

    # 2. Run every rule; collect all outcomes (no short-circuit).
    outcomes: list[Outcome] = []
    for rule in policy_set.rules:
        out = rule.evaluate(ctx)
        if out is not None:
            outcomes.append(out)

    matched_rules = tuple(o.rule_id for o in outcomes)

    # 3. Combine most-restrictive-wins. Baseline is DENY_FAIL_CLOSED.
    winner = _most_restrictive(outcomes)

    if winner is None:
        # No rule fired at all -> fail closed.
        return _decision(Disposition.DENY, ReasonCode.DENY_FAIL_CLOSED, None, matched_rules, ctx,
                        policy_set, {"tool": ctx.tool_name})

    disposition = winner.disposition
    reason_code = winner.reason_code
    deciding_rule = winner.rule_id
    render_params = dict(winner.render_params)

    # 4. Provenance narrowing (post-combination TIGHTENING only). When untrusted
    #    content is in context and the policy set has a provenance_guard rule, an
    #    otherwise-ALLOW write is downgraded to REQUIRE_APPROVAL. This only ever
    #    tightens an ALLOW — it never rescues a DENY into an approval, so
    #    monotonicity holds.
    guard_rule = next((r for r in policy_set.rules
                       if getattr(r, "kind", "") == "provenance_guard"), None)
    narrowed_classes: tuple[RiskClass, ...] = ()
    if guard_rule is not None:
        # Respect the rule's own declared scope (it always existed in config;
        # the engine previously hardcoded both write classes). Strict keeps
        # both true; commerce narrows only irreversible writes — the off-rail
        # cart binds nothing and the mandate bounds what commit can do
        # (ADR-035: injection containment for commerce is structural).
        if getattr(guard_rule, "escalate_reversible", True):
            narrowed_classes += (RiskClass.REVERSIBLE_WRITE,)
        if getattr(guard_rule, "escalate_irreversible", True):
            narrowed_classes += (RiskClass.IRREVERSIBLE_WRITE,)
    if (ctx.untrusted_in_context and disposition == Disposition.ALLOW
            and ctx.risk_class in narrowed_classes):
        disposition = Disposition.REQUIRE_APPROVAL
        reason_code = ReasonCode.ESCALATE_INJECTION_SUSPECTED
        deciding_rule = "__provenance_guard__"
        render_params = {"tool": ctx.tool_name}

    # 5. Class floor — MONEY_MOVEMENT is never auto-allowed. This overrides ANY
    #    rule (including a maliciously-written tool_class -> ALLOW), unless the
    #    disposition is already a DENY (which is more restrictive and wins).
    if ctx.risk_class == RiskClass.MONEY_MOVEMENT and disposition == Disposition.ALLOW:
        disposition = Disposition.REQUIRE_APPROVAL
        reason_code = ReasonCode.ESCALATE_MONEY_MOVEMENT
        deciding_rule = "__class_floor__"
        render_params = {"tool": ctx.tool_name, "amount": _fmt_amt(ctx)}

    # 5b. Mandate resolution (CONDUIT): consent moved upstream. IFF this policy
    #     set carries a mandate_gate rule AND the injected mandate authorises
    #     this exact call (scope, expiry, status, balance — re-checked here,
    #     not assumed), the CLASS-FLOOR escalation resolves to ALLOW: the
    #     user's upfront consent is the approval. Deliberately narrow: only
    #     the class floor is resolvable — a tier review, a provenance
    #     escalation, or any DENY still stands. Monotonicity holds: like
    #     human approval, this rescues only an escalation, never a denial.
    if (disposition == Disposition.REQUIRE_APPROVAL
            and reason_code == ReasonCode.ESCALATE_MONEY_MOVEMENT
            and any(getattr(r, "kind", "") == "mandate_gate" for r in policy_set.rules)):
        from sentinel.policy.rules import mandate_failure
        if mandate_failure(ctx) is None:
            disposition = Disposition.ALLOW
            reason_code = ReasonCode.ALLOW_MANDATE_BOUND
            deciding_rule = "__mandate_bound__"
            render_params = {"tool": ctx.tool_name, "amount": _fmt_amt(ctx)}

    # 5c. Approval resolution — a valid, argument-bound, unexpired approval turns
    #    an escalation into an allow. A DENY is never rescued.
    obligations: list[Obligation] = []
    if disposition == Disposition.REQUIRE_APPROVAL:
        if ctx.env.valid_approval_present and ctx.env.approval_argument_hash == ctx.argument_hash:
            disposition = Disposition.ALLOW
            reason_code = ReasonCode.ALLOW_PRIOR_APPROVAL
            deciding_rule = "__prior_approval__"
            render_params = {"tool": ctx.tool_name, "amount": _fmt_amt(ctx)}
        else:
            obligations.append(Obligation.BIND_APPROVAL_TO_ARGS)

    # 6. Obligations from context.
    if ctx.untrusted_in_context:
        obligations.append(Obligation.FLAG_UNTRUSTED_CONTENT)
    if ctx.risk_class in (RiskClass.MONEY_MOVEMENT, RiskClass.IRREVERSIBLE_WRITE):
        obligations.append(Obligation.AUDIT_ELEVATED)
    # An elevated collection escalation carries a stricter review contract: the
    # reviewer must confirm the amount, and it is audited at the elevated level.
    if reason_code == ReasonCode.ESCALATE_ELEVATED_COLLECTION:
        obligations.append(Obligation.CONFIRM_AMOUNT)
        if Obligation.AUDIT_ELEVATED not in obligations:
            obligations.append(Obligation.AUDIT_ELEVATED)

    return _decision(disposition, reason_code, deciding_rule, matched_rules, ctx, policy_set,
                    render_params, obligations)


def _most_restrictive(outcomes: list[Outcome]) -> Outcome | None:
    """The winning outcome: highest restrictiveness; ties broken by first
    occurrence (stable), so the explanation is deterministic."""
    winner: Outcome | None = None
    for o in outcomes:
        if winner is None or _restrictiveness(o.disposition) > _restrictiveness(winner.disposition):
            winner = o
    return winner


def _fmt_amt(ctx: DecisionContext) -> str:
    from sentinel.common.money import format_amount
    if ctx.money.amount_minor is None:
        return "the amount"
    return format_amount(ctx.money.amount_minor, ctx.money.currency or "INR")


def _decision(disposition, reason_code, deciding_rule, matched_rules, ctx, policy_set,
              render_params, obligations=None) -> PolicyDecision:
    return PolicyDecision(
        disposition=disposition,
        reason_code=reason_code,
        human_reason=render_reason(reason_code, **render_params),
        matched_rules=matched_rules,
        deciding_rule=deciding_rule,
        obligations=tuple(obligations or ()),
        policy_set_version=policy_set.version,
    )
