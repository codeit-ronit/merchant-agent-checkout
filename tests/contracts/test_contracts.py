"""Contract tests (docs/spec/03 §11): round-trip serialisation, schema-version
compatibility, and the redaction-serialisation test."""

from __future__ import annotations

import json

import pytest

from sentinel.contracts import (
    ApprovalRequest,
    AuditEntry,
    DecisionContext,
    Disposition,
    PolicyDecision,
    RunMode,
    RunRecord,
    TerminalState,
    TraceEvent,
    TraceEventType,
)
from sentinel.contracts.audit import GENESIS_HASH
from sentinel.contracts.reasons import ReasonCode, render_reason
from tests.conftest import SYNTHETIC_PII, make_decision_context

pytestmark = pytest.mark.tier1


def test_decision_context_round_trip(ids, env):
    dc = make_decision_context(ids, env)
    restored = DecisionContext.model_validate(json.loads(dc.model_dump_json()))
    assert restored == dc


def test_contract_is_immutable(ids, env):
    dc = make_decision_context(ids, env)
    with pytest.raises(Exception):
        dc.tool_name = "mutated"


def test_extra_field_forbidden(ids, env):
    with pytest.raises(Exception):
        make_decision_context(ids, env, not_a_real_field=1)


def test_schema_version_future_rejected(ids, env):
    dc = make_decision_context(ids, env)
    data = json.loads(dc.model_dump_json())
    data["schema_version"] = 9999
    with pytest.raises(ValueError):
        DecisionContext.ensure_schema(data)


def test_schema_version_current_accepts(ids, env):
    dc = make_decision_context(ids, env)
    data = json.loads(dc.model_dump_json())
    assert DecisionContext.ensure_schema(data) == dc


@pytest.mark.critical
def test_raw_arguments_never_serialised(ids, env):
    """PII placed in the transient arguments_raw field must never appear in any
    serialisation. This is the field-level half of the PII invariant."""
    dc = make_decision_context(
        ids, env,
        arguments_raw={"account_number": SYNTHETIC_PII["BANK_ACCOUNT"],
                       "vpa": SYNTHETIC_PII["VPA"]},
    )
    blob = dc.model_dump_json()
    assert SYNTHETIC_PII["BANK_ACCOUNT"] not in blob
    assert SYNTHETIC_PII["VPA"] not in blob
    assert "arguments_raw" not in blob
    # safe_dict / safe_json must also be clean
    assert SYNTHETIC_PII["BANK_ACCOUNT"] not in dc.safe_json()
    assert dc.arguments_raw is not None  # still usable in-process


@pytest.mark.critical
@pytest.mark.parametrize("pii_value", list(SYNTHETIC_PII.values()))
def test_no_pii_in_contract_surfaces(ids, env, pii_value):
    """Sweep the contract objects that get persisted/streamed: none should carry
    raw PII once built through the intended (redacted) path."""
    dc = make_decision_context(ids, env)
    decision = PolicyDecision(
        disposition=Disposition.REQUIRE_APPROVAL,
        reason_code=ReasonCode.ESCALATE_MONEY_MOVEMENT,
        human_reason=render_reason(ReasonCode.ESCALATE_MONEY_MOVEMENT, tool="create_refund",
                                   amount="₹24,500.00"),
        matched_rules=("money_movement_escalates",),
        deciding_rule="money_movement_escalates",
    )
    trace = TraceEvent(run_id=dc.run_id, sequence=0, type=TraceEventType.POLICY_DECISION,
                       timestamp_ms=1, payload={"reason": decision.human_reason})
    for obj in (dc, decision, trace):
        assert pii_value not in obj.model_dump_json()


def test_audit_entry_chain_payload_excludes_own_hash():
    entry = AuditEntry(entry_id="aud_1", run_id="run_1", timestamp_ms=1,
                       sequence=0, previous_hash=GENESIS_HASH, entry_hash="abc123")
    payload = entry.chain_payload()
    assert "entry_hash" not in payload
    assert payload["previous_hash"] == GENESIS_HASH
    assert payload["sequence"] == 0


def test_run_record_round_trip():
    rr = RunRecord(id="run_1", agent_id="reconciliation", agent_version="1",
                   operator_id="op1", policy_set_id="strict", policy_set_version="1",
                   mode=RunMode.FIXTURE, terminal_state=TerminalState.COMPLETED)
    restored = RunRecord.model_validate(json.loads(rr.model_dump_json()))
    assert restored == rr


def test_approval_binding_semantics(ids, env):
    dc = make_decision_context(ids, env)
    decision = PolicyDecision(disposition=Disposition.REQUIRE_APPROVAL,
                              reason_code=ReasonCode.ESCALATE_MONEY_MOVEMENT,
                              human_reason="needs approval")
    appr = ApprovalRequest(id="appr_1", run_id=dc.run_id, call_id=dc.call_id,
                           context=dc, decision=decision, argument_hash="hash_A",
                           summary="Refund ₹24,500 to payment pay_ABC",
                           created_at_ms=0, expires_at_ms=1000)
    from sentinel.contracts.enums import ApprovalStatus
    approved = appr.model_copy(update={"status": ApprovalStatus.APPROVED})
    # correct hash, in time -> authorises
    assert approved.authorises("hash_A", now_ms=500)
    # one byte different -> does not authorise
    assert not approved.authorises("hash_B", now_ms=500)
    # expired -> does not authorise
    assert not approved.authorises("hash_A", now_ms=1000)
    # pending -> does not authorise
    assert not appr.authorises("hash_A", now_ms=500)
