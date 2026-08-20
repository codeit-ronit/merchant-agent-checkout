"""Shared test fixtures and synthetic-PII constants.

The PII constants here are format-valid, checksum-INVALID synthetic values (they
cannot collide with a real identifier — see ADR-007). They are used to prove the
PII invariant: none of these strings may appear on any output surface.
"""

from __future__ import annotations

import pytest

from sentinel.common.ids import deterministic_factory
from sentinel.contracts import (
    DecisionContext,
    MoneySemantics,
    RiskClass,
)
from sentinel.contracts.decision import InjectedEnv

# Known synthetic PII values (checksum-invalid; see ADR-007). The PII-invariant
# test greps every output surface for these exact strings.
SYNTHETIC_PII = {
    "PAN_CARD": "4111111111111112",       # Luhn-invalid (real test card ...1111 +1)
    "BANK_ACCOUNT": "0000999900001234",   # reserved all-9s-ish sentinel
    "IFSC": "ZZZZ0000001",                # ZZZZ is not an allocated bank code
    "VPA": "victim@invalid",              # @invalid resolves to nobody
    "PHONE": "9999900000",                # reserved fake body
    "AADHAAR": "299999999990",            # never emitted anywhere, ever
    "EMAIL": "customer@example.invalid",
    "NAME": "Aarav Synthetic-Testperson",
}


@pytest.fixture
def ids():
    return deterministic_factory(seed=1)


@pytest.fixture
def env():
    return InjectedEnv(now_epoch_ms=1_755_000_000_000)


def make_decision_context(ids, env, **overrides) -> DecisionContext:
    base = dict(
        run_id=ids.run(), step_id=ids.step(), call_id=ids.call(),
        agent_id="reconciliation", agent_version="1", operator_id="op1",
        policy_set_id="strict", policy_set_version="1",
        tool_name="create_refund", upstream_tool_name="create_refund",
        risk_class=RiskClass.MONEY_MOVEMENT,
        arguments_redacted={"payment_id": "pay_ABC", "amount": 2450000, "currency": "INR"},
        argument_hash="deadbeef",
        env=env,
        money=MoneySemantics(moves_money=True, amount_minor=2450000, currency="INR",
                             target_entities=("pay_ABC",)),
    )
    base.update(overrides)
    return DecisionContext(**base)
