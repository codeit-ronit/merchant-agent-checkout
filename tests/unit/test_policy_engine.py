"""Policy engine — per-rule-type units, evaluation semantics, explanation quality
(docs/spec/04). Tier 1: pure, no I/O."""

from __future__ import annotations

import pytest

from sentinel.contracts import DecisionContext, MoneySemantics, RiskClass
from sentinel.contracts.decision import InjectedEnv
from sentinel.contracts.enums import BindingRole, Disposition, Obligation
from sentinel.contracts.reasons import ReasonCode
from sentinel.policy import (
    AmountCapRule,
    ApprovalRequiredRule,
    ArgumentConstraintRule,
    CounterpartyNoveltyRule,
    EntityScopeRule,
    PolicySet,
    ProvenanceGuardRule,
    RateLimitRule,
    TimeWindowRule,
    ToolAllowRule,
    ToolClassRule,
    ToolDenyRule,
    evaluate,
)

pytestmark = pytest.mark.tier1


def ctx(risk=RiskClass.READ, tool="fetch_payment", amount=None, currency="INR",
        args=None, provenance_untrusted=False, counterparty=None, targets=(),
        role=BindingRole.NONE, **env_kw):
    money = MoneySemantics(
        moves_money=(risk == RiskClass.MONEY_MOVEMENT),
        binding_role=role,
        amount_minor=amount, currency=(currency if amount is not None else None),
        counterparty_ref=counterparty, target_entities=tuple(targets),
    )
    return DecisionContext(
        run_id="run_1", step_id="s1", call_id="c1", agent_id="agent", agent_version="1",
        operator_id="op", policy_set_id="test", policy_set_version="1",
        tool_name=tool, upstream_tool_name=tool, risk_class=risk,
        arguments_redacted=args or {}, argument_hash="hash_A",
        quarantined_content_in_context=provenance_untrusted,
        env=InjectedEnv(now_epoch_ms=1, **env_kw), money=money,
    )


def pset(*rules) -> PolicySet:
    return PolicySet(id="test", version="1", rules=tuple(rules))


BASELINE = ToolClassRule(id="base", class_dispositions={
    RiskClass.READ: Disposition.ALLOW,
    RiskClass.REVERSIBLE_WRITE: Disposition.ALLOW,
    RiskClass.IRREVERSIBLE_WRITE: Disposition.REQUIRE_APPROVAL,
    RiskClass.MONEY_MOVEMENT: Disposition.REQUIRE_APPROVAL,
})


# ---------------- per rule type ----------------

def test_tool_class_dispositions():
    p = pset(BASELINE)
    assert evaluate(p, ctx(RiskClass.READ)).disposition == Disposition.ALLOW
    assert evaluate(p, ctx(RiskClass.IRREVERSIBLE_WRITE, tool="close_qr_code")).disposition == Disposition.REQUIRE_APPROVAL


def test_tool_deny_beats_allow_most_restrictive_wins():
    p = pset(BASELINE, ToolDenyRule(id="deny_x", tools=("fetch_payment",)))
    d = evaluate(p, ctx(RiskClass.READ, tool="fetch_payment"))
    assert d.disposition == Disposition.DENY
    assert d.reason_code == ReasonCode.DENY_TOOL_DENIED


def test_tool_allow_permits_named_tool_under_fail_closed_default():
    # No tool_class rule -> default deny; tool_allow provides the permit.
    p = pset(ToolAllowRule(id="allow", tools=("fetch_all_settlements",)))
    assert evaluate(p, ctx(RiskClass.READ, tool="fetch_all_settlements")).disposition == Disposition.ALLOW
    d = evaluate(p, ctx(RiskClass.READ, tool="other"))
    assert d.disposition == Disposition.DENY
    assert d.reason_code == ReasonCode.DENY_FAIL_CLOSED


def test_amount_cap_per_call_boundary():
    p = pset(BASELINE, AmountCapRule(id="cap", scope="per_call", max_minor=1000000,
                                     applies_to_classes=(RiskClass.MONEY_MOVEMENT,)))
    # exactly at cap -> not exceeded (boundary)
    assert evaluate(p, ctx(RiskClass.MONEY_MOVEMENT, "create_refund", amount=1000000)).disposition == Disposition.REQUIRE_APPROVAL
    # one over -> DENY
    d = evaluate(p, ctx(RiskClass.MONEY_MOVEMENT, "create_refund", amount=1000001))
    assert d.disposition == Disposition.DENY and d.reason_code == ReasonCode.DENY_AMOUNT_EXCEEDS_CAP


def test_amount_cap_per_run_accumulates():
    p = pset(BASELINE, AmountCapRule(id="cap", scope="per_run", max_minor=1000000,
                                     applies_to_classes=(RiskClass.MONEY_MOVEMENT,)))
    d = evaluate(p, ctx(RiskClass.MONEY_MOVEMENT, "create_refund", amount=600000, spend_run_minor=500000))
    assert d.disposition == Disposition.DENY   # 500k already + 600k = 1.1M > 1M


def test_amount_cap_denies_unreadable_amount():
    """A money-moving call whose amount could not be parsed must NOT slip under the
    hard ceiling into an approvable escalation — it fails closed to DENY."""
    p = pset(BASELINE, AmountCapRule(id="cap", scope="per_call", max_minor=1000000,
                                     applies_to_classes=(RiskClass.MONEY_MOVEMENT,)))
    d = evaluate(p, ctx(RiskClass.MONEY_MOVEMENT, "create_refund", amount=None))
    assert d.disposition == Disposition.DENY and d.reason_code == ReasonCode.DENY_AMOUNT_EXCEEDS_CAP


def test_argument_constraint_unknown_op_fails_closed_even_when_arg_absent():
    """A misconfigured constraint op must DENY, even if the target argument is
    absent (an absent arg must never mask a bad op)."""
    p = pset(BASELINE, ArgumentConstraintRule(id="bad", arg_path="nope", op="lt", value=5))
    d = evaluate(p, ctx(RiskClass.READ, "fetch_payment", args={}))
    assert d.disposition == Disposition.DENY and d.reason_code == ReasonCode.DENY_ARGUMENT_CONSTRAINT


def test_forbidden_tool_denied():
    d = evaluate(pset(BASELINE), ctx(RiskClass.FORBIDDEN, "banned_tool"))
    assert d.disposition == Disposition.DENY and d.reason_code == ReasonCode.DENY_FORBIDDEN_TOOL


def test_approval_threshold_boundary_is_exclusive():
    p = pset(ToolClassRule(id="b", class_dispositions={RiskClass.REVERSIBLE_WRITE: Disposition.ALLOW}),
             ApprovalRequiredRule(id="thr", amount_over_minor=1000000))
    at = evaluate(p, ctx(RiskClass.REVERSIBLE_WRITE, "create_payment_link", amount=1000000))
    assert at.disposition == Disposition.ALLOW                       # exactly at threshold: not over
    over = evaluate(p, ctx(RiskClass.REVERSIBLE_WRITE, "create_payment_link", amount=1000001))
    assert over.disposition == Disposition.REQUIRE_APPROVAL          # one over: escalates


def test_hard_deny_is_never_rescued_by_a_valid_approval():
    """A DENY from a hard cap stays DENY even with a valid, argument-matching
    approval present — approvals only rescue escalations, never denials."""
    p = pset(BASELINE, AmountCapRule(id="cap", scope="per_call", max_minor=1000000,
                                     applies_to_classes=(RiskClass.MONEY_MOVEMENT,)))
    d = evaluate(p, ctx(RiskClass.MONEY_MOVEMENT, "create_refund", amount=2000000,
                        valid_approval_present=True, approval_argument_hash="hash_A"))
    assert d.disposition == Disposition.DENY and d.reason_code == ReasonCode.DENY_AMOUNT_EXCEEDS_CAP


def _collection_pset():
    from sentinel.policy import CollectionTierRule
    return pset(BASELINE, CollectionTierRule(id="tiers", review_over_minor=1000000,
                                             elevated_over_minor=20000000))


def test_collection_tier_below_review_is_allowed():
    d = evaluate(_collection_pset(), ctx(RiskClass.REVERSIBLE_WRITE, "create_order",
                                         amount=500000, role=BindingRole.COLLECTION))
    assert d.disposition == Disposition.ALLOW


def test_collection_tier_standard_review():
    d = evaluate(_collection_pset(), ctx(RiskClass.REVERSIBLE_WRITE, "create_order",
                                         amount=1500000, role=BindingRole.COLLECTION))
    assert d.disposition == Disposition.REQUIRE_APPROVAL
    assert d.reason_code == ReasonCode.ESCALATE_AMOUNT_THRESHOLD
    assert Obligation.CONFIRM_AMOUNT not in d.obligations   # standard tier: no amount-confirm


def test_collection_tier_elevated_review_carries_obligations():
    d = evaluate(_collection_pset(), ctx(RiskClass.REVERSIBLE_WRITE, "create_payment_link",
                                         amount=25000000, role=BindingRole.COLLECTION))
    assert d.disposition == Disposition.REQUIRE_APPROVAL
    assert d.reason_code == ReasonCode.ESCALATE_ELEVATED_COLLECTION
    assert Obligation.CONFIRM_AMOUNT in d.obligations       # reviewer must confirm the amount
    assert Obligation.AUDIT_ELEVATED in d.obligations


def test_collection_tier_never_hard_denies_on_size():
    # a huge collection escalates (elevated), it is NEVER an un-approvable DENY
    d = evaluate(_collection_pset(), ctx(RiskClass.REVERSIBLE_WRITE, "create_order",
                                         amount=10**12, role=BindingRole.COLLECTION))
    assert d.disposition == Disposition.REQUIRE_APPROVAL


def test_collection_tier_unreadable_amount_is_treated_as_elevated():
    d = evaluate(_collection_pset(), ctx(RiskClass.REVERSIBLE_WRITE, "create_qr_code",
                                         amount=None, role=BindingRole.COLLECTION))
    assert d.disposition == Disposition.REQUIRE_APPROVAL
    assert d.reason_code == ReasonCode.ESCALATE_ELEVATED_COLLECTION


def test_amount_cap_is_disbursement_only_collection_uses_tiers():
    """The orthogonality proof: the same ₹2.5L amount is an un-approvable DENY as a
    DISBURSEMENT (refund) but an approvable elevated escalation as a COLLECTION."""
    p = pset(BASELINE,
             AmountCapRule(id="cap", scope="per_call", max_minor=20000000,
                           applies_to_classes=(RiskClass.MONEY_MOVEMENT,)))
    from sentinel.policy import CollectionTierRule
    p2 = pset(BASELINE, CollectionTierRule(id="t", review_over_minor=1000000, elevated_over_minor=20000000))
    disb = evaluate(p, ctx(RiskClass.MONEY_MOVEMENT, "create_refund", amount=25000000,
                           role=BindingRole.DISBURSEMENT))
    coll = evaluate(p2, ctx(RiskClass.REVERSIBLE_WRITE, "create_order", amount=25000000,
                            role=BindingRole.COLLECTION))
    assert disb.disposition == Disposition.DENY               # send-out over ceiling: un-approvable
    assert coll.disposition == Disposition.REQUIRE_APPROVAL   # collect over ceiling: approvable


def test_rate_limit_by_class():
    p = pset(BASELINE, RateLimitRule(id="rl", scope="class", key="MONEY_MOVEMENT", max_count=2))
    ok = evaluate(p, ctx(RiskClass.MONEY_MOVEMENT, "create_refund", amount=1000,
                         per_class_count_window={"MONEY_MOVEMENT": 1}))
    assert ok.disposition == Disposition.REQUIRE_APPROVAL
    over = evaluate(p, ctx(RiskClass.MONEY_MOVEMENT, "create_refund", amount=1000,
                           per_class_count_window={"MONEY_MOVEMENT": 2}))
    assert over.disposition == Disposition.DENY and over.reason_code == ReasonCode.DENY_RATE_LIMIT


def test_entity_scope_denies_out_of_scope():
    p = pset(BASELINE, EntityScopeRule(id="scope"))
    d = evaluate(p, ctx(RiskClass.READ, "fetch_payment", targets=("pay_OTHER",),
                        operator_scope_entities=frozenset({"pay_MINE"})))
    assert d.disposition == Disposition.DENY and d.reason_code == ReasonCode.DENY_OUT_OF_SCOPE
    ok = evaluate(p, ctx(RiskClass.READ, "fetch_payment", targets=("pay_MINE",),
                         operator_scope_entities=frozenset({"pay_MINE"})))
    assert ok.disposition == Disposition.ALLOW


def test_argument_constraint_currency_only_applies_to_money_calls():
    p = pset(BASELINE, ArgumentConstraintRule(id="inr", arg_path="currency", op="currency_in", value=["INR"]))
    # read call has no currency -> constraint does not fire
    assert evaluate(p, ctx(RiskClass.READ, "fetch_payment")).disposition == Disposition.ALLOW
    # money call in USD -> denied
    d = evaluate(p, ctx(RiskClass.MONEY_MOVEMENT, "create_refund", amount=1000, currency="USD",
                        args={"currency": "USD"}))
    assert d.disposition == Disposition.DENY and d.reason_code == ReasonCode.DENY_ARGUMENT_CONSTRAINT


def test_time_window_blocks_outside_hours():
    p = pset(BASELINE, TimeWindowRule(id="tw", applies_to_classes=(RiskClass.MONEY_MOVEMENT,),
                                      allowed_hours=(9, 18), window_label="business hours"))
    d = evaluate(p, ctx(RiskClass.MONEY_MOVEMENT, "create_refund", amount=1000, now_local_hour=22))
    assert d.disposition == Disposition.DENY and d.reason_code == ReasonCode.DENY_OUTSIDE_TIME_WINDOW
    inside = evaluate(p, ctx(RiskClass.MONEY_MOVEMENT, "create_refund", amount=1000, now_local_hour=11))
    assert inside.disposition == Disposition.REQUIRE_APPROVAL


def test_approval_required_amount_threshold():
    # money movement already escalates; use a reversible write to isolate the threshold reason
    d = evaluate(pset(ToolClassRule(id="b", class_dispositions={RiskClass.REVERSIBLE_WRITE: Disposition.ALLOW}),
                      ApprovalRequiredRule(id="thr", amount_over_minor=1000000)),
                 ctx(RiskClass.REVERSIBLE_WRITE, "create_payment_link", amount=2000000))
    assert d.disposition == Disposition.REQUIRE_APPROVAL and d.reason_code == ReasonCode.ESCALATE_AMOUNT_THRESHOLD


def test_provenance_guard_narrows_irreversible_to_escalation():
    p = pset(ToolClassRule(id="b", class_dispositions={RiskClass.IRREVERSIBLE_WRITE: Disposition.ALLOW}),
             ProvenanceGuardRule(id="pg"))
    clean = evaluate(p, ctx(RiskClass.IRREVERSIBLE_WRITE, "submit_dispute_evidence"))
    assert clean.disposition == Disposition.ALLOW
    dirty = evaluate(p, ctx(RiskClass.IRREVERSIBLE_WRITE, "submit_dispute_evidence", provenance_untrusted=True))
    assert dirty.disposition == Disposition.REQUIRE_APPROVAL
    assert dirty.reason_code == ReasonCode.ESCALATE_INJECTION_SUSPECTED


def test_counterparty_novelty_escalates_unseen_destination():
    p = pset(BASELINE, CounterpartyNoveltyRule(id="cp"))
    novel = evaluate(p, ctx(RiskClass.MONEY_MOVEMENT, "initiate_payment", amount=1000,
                            counterparty="fa_NEW", known_counterparties=frozenset({"fa_OLD"})))
    assert novel.disposition == Disposition.REQUIRE_APPROVAL
    seen = evaluate(p, ctx(RiskClass.MONEY_MOVEMENT, "initiate_payment", amount=1000,
                           counterparty="fa_OLD", known_counterparties=frozenset({"fa_OLD"})))
    # still escalates (money movement) but not for novelty
    assert seen.disposition == Disposition.REQUIRE_APPROVAL


# ---------------- semantics ----------------

def test_no_matching_rule_is_fail_closed():
    d = evaluate(pset(), ctx(RiskClass.READ, "anything"))
    assert d.disposition == Disposition.DENY and d.reason_code == ReasonCode.DENY_FAIL_CLOSED


def test_unknown_risk_class_denied():
    d = evaluate(pset(BASELINE), ctx(RiskClass.UNKNOWN, "mystery_tool"))
    assert d.disposition == Disposition.DENY and d.reason_code == ReasonCode.DENY_UNKNOWN_TOOL


def test_matched_rules_records_all_that_fired_not_just_decider():
    p = pset(BASELINE, CounterpartyNoveltyRule(id="cp"),
             ApprovalRequiredRule(id="thr", amount_over_minor=100))
    d = evaluate(p, ctx(RiskClass.MONEY_MOVEMENT, "initiate_payment", amount=50000,
                        counterparty="fa_NEW", known_counterparties=frozenset()))
    # baseline (escalate) + novelty (escalate) + threshold (escalate) all fired
    assert "cp" in d.matched_rules and "thr" in d.matched_rules and "base" in d.matched_rules


@pytest.mark.critical
def test_fail_closed_on_exception(monkeypatch):
    """A rule that raises must produce DENY_POLICY_EVALUATION_ERROR, never allow."""
    class Exploding(ToolClassRule):
        def evaluate(self, ctx):
            raise RuntimeError("boom")
    p = pset(Exploding(id="boom", class_dispositions={RiskClass.READ: Disposition.ALLOW}))
    d = evaluate(p, ctx(RiskClass.READ, "fetch_payment"))
    assert d.disposition == Disposition.DENY
    assert d.reason_code == ReasonCode.DENY_POLICY_EVALUATION_ERROR


def test_every_decision_has_a_rendered_explanation():
    for risk in (RiskClass.READ, RiskClass.MONEY_MOVEMENT, RiskClass.IRREVERSIBLE_WRITE):
        d = evaluate(pset(BASELINE), ctx(risk, "some_tool", amount=(5000 if risk == RiskClass.MONEY_MOVEMENT else None)))
        assert d.human_reason and not d.human_reason.endswith(":")
