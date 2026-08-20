"""Property-based tests for the policy engine (docs/spec/04 §3.6).

Purity makes these cheap and they find bugs example tests miss. Five properties:
monotonicity, determinism, fail-closed under mutation, approval binding, and the
class floor (no policy can auto-allow money movement)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sentinel.contracts import DecisionContext, MoneySemantics, RiskClass
from sentinel.contracts.decision import InjectedEnv
from sentinel.contracts.enums import Disposition
from sentinel.policy import PolicySet, ToolClassRule, ToolDenyRule, evaluate

pytestmark = [pytest.mark.tier2]

RISK = st.sampled_from([RiskClass.READ, RiskClass.REVERSIBLE_WRITE,
                        RiskClass.IRREVERSIBLE_WRITE, RiskClass.MONEY_MOVEMENT])
DISP = st.sampled_from([Disposition.ALLOW, Disposition.REQUIRE_APPROVAL, Disposition.DENY])


@st.composite
def contexts(draw):
    risk = draw(RISK)
    amount = draw(st.integers(min_value=0, max_value=50_000_00)) if risk == RiskClass.MONEY_MOVEMENT else None
    approval = draw(st.booleans())
    return DecisionContext(
        run_id="run", step_id="s", call_id="c", agent_id="a", agent_version="1",
        operator_id="op", policy_set_id="p", policy_set_version="1",
        tool_name=draw(st.sampled_from(["fetch_payment", "create_refund", "close_qr_code", "initiate_payment"])),
        upstream_tool_name="x", risk_class=risk,
        arguments_redacted={}, argument_hash="hash_A",
        env=InjectedEnv(now_epoch_ms=1, valid_approval_present=approval,
                        approval_argument_hash=("hash_A" if approval else None)),
        money=MoneySemantics(moves_money=(risk == RiskClass.MONEY_MOVEMENT),
                             amount_minor=amount, currency=("INR" if amount is not None else None)),
    )


@st.composite
def class_dispositions(draw):
    return {
        RiskClass.READ: draw(DISP), RiskClass.REVERSIBLE_WRITE: draw(DISP),
        RiskClass.IRREVERSIBLE_WRITE: draw(DISP), RiskClass.MONEY_MOVEMENT: draw(DISP),
    }


@st.composite
def policy_sets(draw):
    return PolicySet(id="gen", version="1",
                     rules=(ToolClassRule(id="c", class_dispositions=draw(class_dispositions())),))


@settings(max_examples=300)
@given(policy_sets(), contexts())
def test_determinism(ps, c):
    """Same inputs, repeated runs, identical output including matched-rule order."""
    a = evaluate(ps, c)
    b = evaluate(ps, c)
    assert a == b


@settings(max_examples=400)
@given(policy_sets(), contexts())
@pytest.mark.critical
def test_class_floor_money_movement_never_auto_allowed(ps, c):
    """No policy set — however its class_dispositions are written — can auto-allow
    a MONEY_MOVEMENT tool without a valid approval. THE system invariant."""
    d = evaluate(ps, c)
    if c.risk_class == RiskClass.MONEY_MOVEMENT and not c.env.valid_approval_present:
        assert d.disposition != Disposition.ALLOW


@settings(max_examples=300)
@given(policy_sets(), contexts())
def test_monotonicity_adding_a_deny_never_loosens(ps, c):
    """Adding a restrictive rule (a matching tool_deny) never makes a decision
    less restrictive."""
    before = evaluate(ps, c)
    stricter = ps.model_copy(update={"rules": ps.rules + (ToolDenyRule(id="d", tools=(c.tool_name,)),)})
    after = evaluate(stricter, c)
    assert after.disposition.restrictiveness >= before.disposition.restrictiveness
    assert after.disposition == Disposition.DENY   # the deny matches this tool


@settings(max_examples=300)
@given(policy_sets(), contexts())
def test_approval_binding_wrong_hash_never_allows(ps, c):
    """An escalation is never turned into ALLOW by an approval whose argument
    hash differs by even one byte."""
    # force an approval that is present but bound to a DIFFERENT hash
    c2 = c.model_copy(update={"env": c.env.model_copy(update={
        "valid_approval_present": True, "approval_argument_hash": "different_hash"})})
    d = evaluate(ps, c2)
    if c2.risk_class == RiskClass.MONEY_MOVEMENT:
        # money movement must not be ALLOWed by a mismatched approval
        assert d.disposition != Disposition.ALLOW


@settings(max_examples=200)
@given(contexts())
def test_fail_closed_under_empty_policy(c):
    """An empty policy set denies everything (fail closed)."""
    d = evaluate(PolicySet(id="empty", version="1", rules=()), c)
    assert d.disposition == Disposition.DENY
