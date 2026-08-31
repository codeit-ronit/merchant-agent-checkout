"""The idempotency REFUSAL path must emit a valid trace event. Found by the
first real model that retried a payment: the branch emitted a type outside
the closed TraceEventType list and crashed the whole run with ValueError —
no deterministic test had ever reached this emit (ADR-042)."""

from __future__ import annotations

import pytest

import conduit.api as capi

pytestmark = pytest.mark.tier3


def test_inflight_duplicate_money_call_is_refused_not_crashed(monkeypatch):
    state = capi.CommerceState()
    monkeypatch.setattr(capi, "state", state)
    m = capi.create_mandate(capi.MandateReq(amount_minor=500000))

    # Every write finds its slot "in flight" → the FIRST write takes the
    # refusal branch, which used to crash the run with ValueError.
    from sentinel.proxy.idempotency import IdempotencyGuard
    monkeypatch.setattr(IdempotencyGuard, "begin",
                        lambda self, key: ("refuse", None))
    res = capi.state.run_purchase(
        "Order dinner for four under ₹800, no beef", m["mandate_id"])
    # the run must SURVIVE the refusal (no ValueError), and nothing may charge
    assert res.get("terminal") is not None
    trace_types = {str(e.get("type")) for e in
                   (state.purchases.get(res["run_ref"]) or {}).get("trace", [])}
    assert not any("idempotency_refused" in t for t in trace_types)
    # and the refusal really fired, surfaced as the closed-list security_event
    events = (state.purchases.get(res["run_ref"]) or {}).get("trace", [])
    kinds = {(e.get("payload") or {}).get("kind") for e in events
             if "SECURITY_EVENT" in str(e.get("type", "")).upper()}
    assert "idempotency_refused" in kinds
