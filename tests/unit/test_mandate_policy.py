"""The mandate as policy (05-MANDATE §3.4) — pure engine tests.

The judgements that must hold:
* every mandate failure is a DENY, and exhaustion is UN-APPROVABLE — a valid
  human approval must not rescue it;
* a valid mandate resolves the MONEY_MOVEMENT class floor to ALLOW (consent
  moved upstream) — but never a tier review, never a DENY;
* composition is most-restrictive-wins with the existing controls intact.
"""

from __future__ import annotations

import pytest

from sentinel.contracts import DecisionContext, MoneySemantics, RiskClass
from sentinel.contracts.decision import InjectedEnv, MandateEnv
from sentinel.contracts.enums import BindingRole, Disposition
from sentinel.contracts.reasons import ReasonCode
from sentinel.policy import PolicySet, ToolClassRule, evaluate
from sentinel.policy.rules import AmountCapRule, CollectionTierRule, MandateGateRule

pytestmark = pytest.mark.tier1

NOW = 1_000_000
GOOD = MandateEnv(mandate_id="mnd_1", remaining_minor=200000, currency="INR",
                  scope_merchant_id="mrc_fresh_basket", expires_at_ms=NOW + 60_000)

BASELINE = ToolClassRule(id="base", class_dispositions={
    RiskClass.READ: Disposition.ALLOW,
    RiskClass.REVERSIBLE_WRITE: Disposition.ALLOW,
    RiskClass.IRREVERSIBLE_WRITE: Disposition.REQUIRE_APPROVAL,
    RiskClass.MONEY_MOVEMENT: Disposition.ALLOW,   # floor still escalates it
})
GATE = MandateGateRule(id="mandate_gate",
                       resolves_tools=("initiate_payment", "submit_otp"))
TIERS = CollectionTierRule(id="tiers", review_over_minor=1_000_000,
                           elevated_over_minor=20_000_000, currency="INR")


def ctx(risk=RiskClass.REVERSIBLE_WRITE, tool="cart_commit", amount=74000,
        role=BindingRole.COLLECTION, mandate=GOOD, merchant="mrc_fresh_basket",
        approval=False):
    return DecisionContext(
        run_id="r", step_id="s", call_id="c", agent_id="buyer", agent_version="1",
        operator_id="op", policy_set_id="commerce", policy_set_version="1",
        tool_name=tool, upstream_tool_name=tool, risk_class=risk,
        arguments_redacted={"currency": "INR"}, argument_hash="hash_A",
        env=InjectedEnv(now_epoch_ms=NOW, mandate=mandate, merchant_id=merchant,
                        valid_approval_present=approval,
                        approval_argument_hash="hash_A" if approval else None),
        money=MoneySemantics(moves_money=(risk == RiskClass.MONEY_MOVEMENT),
                             binding_role=role, amount_minor=amount, currency="INR"),
    )


def pset(*rules):
    return PolicySet(id="commerce-test", version="1", rules=tuple(rules))


class TestMandateDenies:
    def test_missing_mandate_denies_binding_calls(self):
        d = evaluate(pset(BASELINE, GATE), ctx(mandate=None))
        assert d.disposition is Disposition.DENY
        assert d.reason_code is ReasonCode.DENY_MANDATE_MISSING

    def test_revoked_is_instant_and_total(self):
        revoked = GOOD.model_copy(update={"status": "REVOKED"})
        d = evaluate(pset(BASELINE, GATE), ctx(mandate=revoked))
        assert d.reason_code is ReasonCode.DENY_MANDATE_REVOKED
        assert "instant and total" in d.human_reason

    def test_expiry_is_absolute(self):
        expired = GOOD.model_copy(update={"expires_at_ms": NOW})  # now >= expiry
        d = evaluate(pset(BASELINE, GATE), ctx(mandate=expired))
        assert d.reason_code is ReasonCode.DENY_MANDATE_EXPIRED

    def test_scope_a_mandate_for_one_merchant_never_draws_for_another(self):
        d = evaluate(pset(BASELINE, GATE), ctx(merchant="mrc_other_shop"))
        assert d.reason_code is ReasonCode.DENY_MANDATE_SCOPE

    def test_exhaustion_names_the_shortfall(self):
        d = evaluate(pset(BASELINE, GATE), ctx(amount=210000))
        assert d.reason_code is ReasonCode.DENY_MANDATE_EXHAUSTED
        assert "₹100.00" in d.human_reason           # 210000 - 200000 short

    @pytest.mark.critical
    def test_exhaustion_is_unapprovable_a_reviewer_cannot_rescue_it(self):
        """THE consent judgement: a valid, argument-bound human approval must
        not override a limit the USER set. DENY is never rescued."""
        d = evaluate(pset(BASELINE, GATE), ctx(amount=210000, approval=True))
        assert d.disposition is Disposition.DENY
        assert d.reason_code is ReasonCode.DENY_MANDATE_EXHAUSTED

    def test_non_binding_tools_are_untouched(self):
        d = evaluate(pset(BASELINE, GATE),
                     ctx(risk=RiskClass.READ, tool="catalog_search",
                         amount=None, role=BindingRole.NONE, mandate=None))
        assert d.disposition is Disposition.ALLOW


class TestMandateResolvesTheFloor:
    @pytest.mark.critical
    def test_valid_mandate_allows_money_movement_without_a_human(self):
        """Consent moved upstream: the class floor escalates, the mandate
        resolves — end to end with no human mid-flow."""
        d = evaluate(pset(BASELINE, GATE),
                     ctx(risk=RiskClass.MONEY_MOVEMENT, tool="initiate_payment"))
        assert d.disposition is Disposition.ALLOW
        assert d.reason_code is ReasonCode.ALLOW_MANDATE_BOUND
        assert d.deciding_rule == "__mandate_bound__"
        assert "consent was given upfront" in d.human_reason

    def test_without_a_mandate_gate_rule_the_floor_stands(self):
        """A policy set that never opted into mandates keeps the human floor —
        the resolution requires the rule's presence, not just env data."""
        d = evaluate(pset(BASELINE),
                     ctx(risk=RiskClass.MONEY_MOVEMENT, tool="initiate_payment"))
        assert d.disposition is Disposition.REQUIRE_APPROVAL
        assert d.reason_code is ReasonCode.ESCALATE_MONEY_MOVEMENT

    def test_invalid_mandate_keeps_money_movement_denied(self):
        d = evaluate(pset(BASELINE, GATE),
                     ctx(risk=RiskClass.MONEY_MOVEMENT, tool="initiate_payment",
                         mandate=GOOD.model_copy(update={"status": "REVOKED"})))
        assert d.disposition is Disposition.DENY
        assert d.reason_code is ReasonCode.DENY_MANDATE_REVOKED

    @pytest.mark.critical
    def test_a_dinner_mandate_never_authorises_a_refund(self):
        """Consent to a purchase is not consent to arbitrary money movement:
        the mandate resolves the floor ONLY for the tools the rule names. A
        refund under a perfectly valid mandate still needs a human."""
        d = evaluate(pset(BASELINE, GATE),
                     ctx(risk=RiskClass.MONEY_MOVEMENT, tool="create_refund",
                         role=BindingRole.DISBURSEMENT, amount=5000))
        assert d.disposition is Disposition.REQUIRE_APPROVAL
        assert d.reason_code is ReasonCode.ESCALATE_MONEY_MOVEMENT

    def test_empty_resolves_list_fails_closed(self):
        bare_gate = MandateGateRule(id="gate_no_resolve")
        d = evaluate(pset(BASELINE, bare_gate),
                     ctx(risk=RiskClass.MONEY_MOVEMENT, tool="initiate_payment"))
        assert d.disposition is Disposition.REQUIRE_APPROVAL

    def test_mandate_never_resolves_a_tier_review(self):
        """A ₹15,000 commit inside a ₹100,000 mandate still needs the human
        tier review — the mandate resolves only the class floor."""
        big = MandateEnv(mandate_id="mnd_big", remaining_minor=10_000_000,
                         currency="INR", scope_merchant_id="mrc_fresh_basket",
                         expires_at_ms=NOW + 60_000)
        d = evaluate(pset(BASELINE, GATE, TIERS), ctx(amount=1_500_000, mandate=big))
        assert d.disposition is Disposition.REQUIRE_APPROVAL

    def test_hard_caps_still_beat_the_mandate(self):
        cap = AmountCapRule(id="cap", scope="per_call", max_minor=50_000,
                            currency="INR", applies_to_roles=(BindingRole.COLLECTION,))
        d = evaluate(pset(BASELINE, GATE, cap), ctx(amount=74000))
        assert d.disposition is Disposition.DENY
        assert d.reason_code is ReasonCode.DENY_AMOUNT_EXCEEDS_CAP


class TestCommercePolicySet:
    def test_commerce_yaml_loads_and_composes(self):
        from sentinel.policy_loader import load_policy_set
        p = load_policy_set("commerce")
        d = evaluate(p, ctx(risk=RiskClass.MONEY_MOVEMENT, tool="initiate_payment",
                            amount=74000))
        assert d.reason_code is ReasonCode.ALLOW_MANDATE_BOUND
        d = evaluate(p, ctx(risk=RiskClass.MONEY_MOVEMENT, tool="initiate_payment",
                            amount=74000, mandate=None))
        assert d.disposition is Disposition.DENY
        assert d.reason_code is ReasonCode.DENY_MANDATE_MISSING
