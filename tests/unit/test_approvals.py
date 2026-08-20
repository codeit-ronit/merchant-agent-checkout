"""Approval lifecycle invariants (docs/spec/03 §7): single-use, argument-bound,
absolute expiry, terminal rejection."""

from __future__ import annotations

import pytest

from sentinel.approvals.store import ApprovalStore, InMemoryApprovalRepository
from sentinel.contracts.decision import DecisionContext, InjectedEnv, MoneySemantics, PolicyDecision
from sentinel.contracts.enums import ApprovalStatus, Disposition, RiskClass
from sentinel.contracts.reasons import ReasonCode

pytestmark = pytest.mark.tier1


def _ctx(arg_hash="hash_A"):
    return DecisionContext(
        run_id="run", step_id="s", call_id="c", agent_id="a", agent_version="1", operator_id="op",
        policy_set_id="strict", policy_set_version="1", tool_name="create_refund",
        upstream_tool_name="create_refund", risk_class=RiskClass.MONEY_MOVEMENT,
        argument_hash=arg_hash, env=InjectedEnv(now_epoch_ms=0),
        money=MoneySemantics(moves_money=True, amount_minor=50000, currency="INR"))


def _decision():
    return PolicyDecision(disposition=Disposition.REQUIRE_APPROVAL,
                          reason_code=ReasonCode.ESCALATE_MONEY_MOVEMENT, human_reason="needs approval")


def _store():
    return ApprovalStore(InMemoryApprovalRepository(), default_ttl_ms=1000)


def test_approve_then_consume_once():
    s = _store()
    appr = s.create(context=_ctx(), decision=_decision(), summary="refund ₹500", now_ms=0)
    s.resolve(appr.id, approve=True, resolver_id="op", now_ms=10)
    assert s.consume(appr.id, "hash_A", now_ms=20) is True         # first use authorises
    assert s.consume(appr.id, "hash_A", now_ms=30) is False        # single-use: second use denied
    assert s.get(appr.id).status == ApprovalStatus.CONSUMED


def test_argument_binding_one_byte_difference():
    s = _store()
    appr = s.create(context=_ctx("hash_A"), decision=_decision(), summary="x", now_ms=0)
    s.resolve(appr.id, approve=True, resolver_id="op", now_ms=10)
    assert s.consume(appr.id, "hash_B", now_ms=20) is False        # different args -> not authorised


def test_expiry_is_absolute():
    s = _store()
    appr = s.create(context=_ctx(), decision=_decision(), summary="x", now_ms=0, ttl_ms=100)
    s.resolve(appr.id, approve=True, resolver_id="op", now_ms=10)
    assert s.consume(appr.id, "hash_A", now_ms=1000) is False      # expired -> dead


def test_rejection_is_terminal():
    s = _store()
    appr = s.create(context=_ctx(), decision=_decision(), summary="x", now_ms=0)
    s.resolve(appr.id, approve=False, resolver_id="op", now_ms=10)
    # a later approve does not revive a rejected approval
    again = s.resolve(appr.id, approve=True, resolver_id="op", now_ms=20)
    assert again.status == ApprovalStatus.REJECTED
