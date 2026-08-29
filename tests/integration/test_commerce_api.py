"""The commerce API layer (Phase 7's data source): snapshot isolation between
purchases, unique order ids (the fixture bug ADR-039 found here), and all four
demo paths producing their designed states."""

from __future__ import annotations

import pytest

import conduit.api as capi

pytestmark = pytest.mark.tier3


@pytest.fixture()
def api(monkeypatch):
    state = capi.CommerceState()
    monkeypatch.setattr(capi, "state", state)
    mandate = capi.create_mandate(capi.MandateReq(amount_minor=500000))
    return state, mandate["mandate_id"]


TASK = "Order dinner for four under ₹800, no beef"


def _buy(mandate_id: str, **kw):
    return capi.purchase(capi.PurchaseReq(task=TASK, mandate_id=mandate_id, **kw))


class TestSnapshots:
    def test_second_purchase_starts_with_a_clean_snapshot(self, api):
        state, mid = api
        first = _buy(mid)
        second = capi.purchase(capi.PurchaseReq(
            task="Order a veg lunch for two under ₹400, no extras", mandate_id=mid))
        opening = state.purchases[second["run_ref"]]["trace"][0]["commerce"]
        assert opening["cart"] is None and opening["commit"] is None
        assert first["output"]["order_id"] != second["output"]["order_id"]

    def test_every_event_carries_mandate_and_grows_the_story(self, api):
        state, mid = api
        run = _buy(mid)
        trace = state.purchases[run["run_ref"]]["trace"]
        assert all(evt["commerce"]["mandate"] is not None for evt in trace)
        assert trace[-1]["commerce"]["commit"]["commerce"] == "COMMITTED"
        assert trace[-1]["commerce"]["payment"]["status"] == "captured"
        assert trace[-1]["commerce"]["payment"]["modelled"] is True   # labelled


class TestDemoPaths:
    def test_decline_reverses_visibly(self, api):
        state, mid = api
        run = _buy(mid, decline_demo=True)
        snap = run["final_snapshot"]
        assert run["output"]["decision"] == "payment_declined"
        assert snap["payment"]["status"] == "failed"
        assert snap["mandate"]["remaining_minor"] == 500000            # money back

    def test_reprice_streams_both_verdicts(self, api):
        state, mid = api
        run = _buy(mid, reprice_demo=True)
        verdicts = [e["commerce"]["commit"]["commerce"]
                    for e in state.purchases[run["run_ref"]]["trace"]
                    if e["commerce"]["commit"]]
        assert "REJECT_REPRICE_DIVERGENCE" in verdicts    # policy ALLOW, commerce REFUSED
        assert verdicts[-1] == "COMMITTED"                # re-confirmed at truth

    def test_timeout_reconciles_one_payment_only(self, api):
        state, mid = api
        run = _buy(mid, timeout_demo=True)
        assert run["output"]["decision"] == "purchased"
        payments = state.rail.fetch_order_payments(run["output"]["order_id"])
        assert payments["count"] == 1                     # never a blind retry

    def test_revoke_is_instant_from_the_console(self, api):
        state, mid = api
        assert capi.revoke_mandate(mid)["status"] == "REVOKED"
        run = _buy(mid)
        assert run["output"]["decision"] == "declined"
