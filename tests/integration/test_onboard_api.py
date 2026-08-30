"""Storefront onboarding endpoint + the agent-channel revenue view.

The onboarding endpoint is the "any merchant" claim made pressable, and it
runs on a public demo box — so the SSRF guard is load-bearing, not garnish:
scheme allow-list, private-address refusal re-checked on every redirect hop,
and a hard response-size cap. Every skipped product carries a reason; an
import never overwrites an existing price.
"""

from __future__ import annotations

import json

import pytest

import conduit.api as capi

pytestmark = pytest.mark.tier3


@pytest.fixture()
def api(monkeypatch):
    state = capi.CommerceState()
    monkeypatch.setattr(capi, "state", state)
    return state


def _body(resp):
    if hasattr(resp, "body"):
        return json.loads(resp.body)
    return resp


LD_HTML = """
<html><head><script type="application/ld+json">
{"@graph": [
  {"@type": "Product", "name": "Filter Coffee Powder", "sku": "itm_web-coffee",
   "description": "Peaberry blend",
   "offers": {"price": "349.00", "priceCurrency": "INR", "availability": "InStock"}},
  {"@type": "Product", "name": "Banana Chips", "sku": "itm_web-chips",
   "offers": {"price": "120", "priceCurrency": "INR"}},
  {"@type": "Product", "name": "Imported Cocoa", "sku": "itm_web-cocoa",
   "offers": {"price": "9.99", "priceCurrency": "USD"}}
]}
</script></head><body>no prose is ever parsed</body></html>
"""


class TestGuard:
    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "ftp://example.com/feed",
        "http://localhost/admin",
        "http://127.0.0.1:8080/",
        "http://10.0.0.5/internal",
        "http://169.254.169.254/latest/meta-data/",
    ])
    def test_private_and_non_http_refused(self, api, url):
        resp = capi.onboard_storefront(capi.OnboardReq(url=url))
        assert resp.status_code == 400
        assert _body(resp)["error"]

    def test_redirect_into_private_space_is_blocked(self, api, monkeypatch):
        def fake_fetch(url, **kw):
            raise capi.OnboardBlocked("A redirect was blocked: private network")
        monkeypatch.setattr(capi, "_fetch_storefront", fake_fetch)
        resp = capi.onboard_storefront(capi.OnboardReq(url="http://example.com/shop"))
        assert resp.status_code == 400
        assert "redirect" in _body(resp)["error"].lower()


class TestImport:
    def test_json_ld_imports_inr_items_and_skips_foreign_currency(self, api, monkeypatch):
        monkeypatch.setattr(capi, "_fetch_storefront", lambda url, **kw: LD_HTML)
        before = capi.state.catalog.catalog_version()
        out = capi.onboard_storefront(capi.OnboardReq(url="http://example.com/shop"))
        assert out["imported"] == 2
        assert out["source"] == "json-ld"
        assert any("USD" in s for s in out["skipped"])
        assert out["catalog_version"] > before
        item_ids = {it["item_id"] for it in capi.get_catalog()["items"]}
        assert {"itm_web-coffee", "itm_web-chips"} <= item_ids

    def test_reimport_never_overwrites_existing_prices(self, api, monkeypatch):
        monkeypatch.setattr(capi, "_fetch_storefront", lambda url, **kw: LD_HTML)
        capi.onboard_storefront(capi.OnboardReq(url="http://example.com/shop"))
        again = capi.onboard_storefront(capi.OnboardReq(url="http://example.com/shop"))
        assert again["imported"] == 0
        assert sum("never overwrite" in s for s in again["skipped"]) == 2

    def test_page_without_markup_fails_with_the_way_out(self, api, monkeypatch):
        monkeypatch.setattr(capi, "_fetch_storefront",
                            lambda url, **kw: "<html><body>just prose</body></html>")
        resp = capi.onboard_storefront(capi.OnboardReq(url="http://example.com/shop"))
        assert resp.status_code == 422
        assert "CSV" in _body(resp)["error"]  # the actionable fallback is named


class TestRevenue:
    def test_captured_only_with_upsell_attribution(self, api):
        mandate = capi.create_mandate(capi.MandateReq(amount_minor=500000))
        capi.purchase(capi.PurchaseReq(
            task="Order dinner for four under ₹800, no beef",
            mandate_id=mandate["mandate_id"]))
        rev = capi.revenue()
        assert rev["orders_placed"] == 1
        assert rev["orders_captured"] == 1
        assert rev["payments_declined"] == 0
        assert rev["gross_captured_minor"] == 57260
        # gulab jamun entered via explicit upsell acceptance: ₹80.00 pre-tax
        assert rev["upsell_attributed_minor"] == 8000
        assert rev["aov_minor"] == 57260

    def test_declined_payment_is_counted_but_never_revenue(self, api):
        mandate = capi.create_mandate(capi.MandateReq(amount_minor=500000))
        capi.purchase(capi.PurchaseReq(
            task="Order dinner for four under ₹800, no beef",
            mandate_id=mandate["mandate_id"], decline_demo=True))
        rev = capi.revenue()
        assert rev["orders_placed"] == 1
        assert rev["orders_captured"] == 0
        assert rev["payments_declined"] == 1
        assert rev["gross_captured_minor"] == 0
