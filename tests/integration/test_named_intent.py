"""Named intent: when the user's own words name a catalog item, the agent buys
exactly that — the case every onboarded storefront produces. Two properties
are load-bearing: (1) the loop closes end-to-end on an item that entered via
storefront-URL onboarding, and (2) a merchant can NEVER hijack a task by
naming a product out of generic constraint words — names match as labels
only, and a name with no specific token matches nothing.
"""

from __future__ import annotations

import pytest

import conduit.api as capi

pytestmark = pytest.mark.tier3

COFFEE_HTML = """
<html><head><script type="application/ld+json">
{"@type": "Product", "name": "Attikan Estate", "sku": "itm_attikan-estate",
 "description": "Single-origin arabica",
 "offers": {"price": "700.00", "priceCurrency": "INR", "availability": "InStock"}}
</script></head></html>
"""

# The trap: every token is constraint grammar or a number. If name-matching
# were naive, this ₹1 item would capture every "dinner under ₹800" task.
TRAP_HTML = """
<html><head><script type="application/ld+json">
{"@type": "Product", "name": "Dinner Under 800", "sku": "itm_web-trap",
 "offers": {"price": "1.00", "priceCurrency": "INR", "availability": "InStock"}}
</script></head></html>
"""


@pytest.fixture()
def api(monkeypatch):
    state = capi.CommerceState()
    monkeypatch.setattr(capi, "state", state)
    mandate = capi.create_mandate(capi.MandateReq(amount_minor=500000))
    return state, mandate["mandate_id"]


def _onboard(monkeypatch, html: str):
    monkeypatch.setattr(capi, "_fetch_storefront", lambda url, **kw: html)
    return capi.onboard_storefront(capi.OnboardReq(url="http://example.com/shop"))


class TestNamedIntent:
    def test_onboarded_item_is_bought_by_name_end_to_end(self, api, monkeypatch):
        _state, mid = api
        assert _onboard(monkeypatch, COFFEE_HTML)["imported"] == 1
        result = capi.purchase(capi.PurchaseReq(
            task="Buy one Attikan Estate coffee under ₹900", mandate_id=mid))
        report = result["output"]
        assert report["decision"] == "purchased"
        assert [i["item_id"] for i in report["items"]] == ["itm_attikan-estate"]
        assert report["order_id"]
        # named intent buys exactly what was named — no extras, ever
        assert report["upsell_accepted"] is False

    def test_named_item_over_budget_declines_honestly(self, api, monkeypatch):
        _state, mid = api
        _onboard(monkeypatch, COFFEE_HTML)
        result = capi.purchase(capi.PurchaseReq(
            task="Buy one Attikan Estate coffee under ₹500", mandate_id=mid))
        report = result["output"]
        assert report["decision"] == "declined"
        assert report["order_id"] is None
        assert "budget" in report["constraints_unsatisfied"][0]

    def test_generic_name_cannot_hijack_a_dinner_task(self, api, monkeypatch):
        _state, mid = api
        assert _onboard(monkeypatch, TRAP_HTML)["imported"] == 1
        result = capi.purchase(capi.PurchaseReq(
            task="Order dinner for four under ₹800, no beef", mandate_id=mid))
        report = result["output"]
        assert report["decision"] == "purchased"
        bought = {i["item_id"] for i in report["items"]}
        assert "itm_web-trap" not in bought
        assert "itm_steamed-rice" in bought  # the dinner path still runs

    def test_dinner_task_unchanged_by_named_intent_machinery(self, api):
        _state, mid = api
        result = capi.purchase(capi.PurchaseReq(
            task="Order dinner for four under ₹800, no beef", mandate_id=mid))
        report = result["output"]
        assert report["decision"] == "purchased"
        assert report["total_minor"] == 57260  # the pinned demo dinner, untouched
