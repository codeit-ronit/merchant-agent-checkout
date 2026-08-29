"""Bounded upsell (06 §B): offer-never-add, suppression pre-model,
state-bound clearance with live re-validation at acceptance — the re-price
lesson applied to offers (the value checked at one moment and acted on at
another is re-checked at the acting moment)."""

from __future__ import annotations

import pytest

from conduit.cart.gate import CommitGate
from conduit.cart.model import CartError
from conduit.cart.service import CartService
from conduit.cart.store import InMemoryCartRepository
from conduit.catalog.model import Availability, MerchantConfig, Stock, UpsellRule
from conduit.catalog.seed import MERCHANT, seed_catalog
from conduit.catalog.service import CatalogService
from conduit.catalog.store import InMemoryCatalogRepository
from conduit.mandate.ledger import DrawdownLedger, InMemoryLedgerRepository, Mandate
from sentinel.fixtures.upstream import FixtureUpstream

pytestmark = pytest.mark.tier1

T0 = 1_000_000


def _world(locked_minor=200000, cap=1):
    catalog = CatalogService(InMemoryCatalogRepository())
    seed_catalog(catalog)
    if cap != MERCHANT.max_upsell_offers_per_cart:
        catalog.put_merchant(MerchantConfig(MERCHANT.merchant_id,
                                            MERCHANT.display_name, cap))
    ledger = DrawdownLedger(InMemoryLedgerRepository())
    ledger.create_mandate(Mandate("mnd_u", locked_minor, "INR"))
    carts = CartService(InMemoryCartRepository(), catalog, ledger)
    return catalog, ledger, carts


class TestSuppressionIsPreModel:
    def test_affordable_offer_surfaces_with_the_view(self):
        _, _, carts = _world()
        cart = carts.create("mnd_u", now_ms=T0)
        view = carts.add_item(cart.cart_id, "itm_paneer-tikka", 1, now_ms=T0)
        (offer,) = view.upsell_offers
        assert offer["rule_id"] == "rule_dessert_with_mains"
        assert offer["item_id"] == "itm_gulab-jamun"
        assert offer["offer_total_minor"] == 8960          # 8000 + 12% tax
        assert offer["cleared_at"]["cart_total_minor"] == view.total_minor

    @pytest.mark.critical
    def test_unaffordable_offer_never_reaches_the_model(self):
        """A mandate that covers the cart but not cart+offer: the offer is
        simply ABSENT from the response — nothing to reject after acceptance,
        because the model never saw it (06 §B3)."""
        _, _, carts = _world(locked_minor=22000)            # paneer 21000 fits; +8960 doesn't
        cart = carts.create("mnd_u", now_ms=T0)
        view = carts.add_item(cart.cart_id, "itm_paneer-tikka", 1, now_ms=T0)
        assert view.upsell_offers == ()

    def test_out_of_stock_offer_item_never_surfaces(self):
        catalog, _, carts = _world()
        catalog.set_availability("itm_gulab-jamun",
                                 Availability(stock=Stock.OUT_OF_STOCK), now_ms=T0)
        cart = carts.create("mnd_u", now_ms=T0)
        view = carts.add_item(cart.cart_id, "itm_paneer-tikka", 1, now_ms=T0)
        assert view.upsell_offers == ()

    def test_per_cart_cap_counts_cumulatively(self):
        """Cap 1: after ONE offer has ever been surfaced, no second rule may
        surface on this cart — even after the first becomes irrelevant."""
        _, _, carts = _world(cap=1)
        cart = carts.create("mnd_u", now_ms=T0)
        view = carts.add_item(cart.cart_id, "itm_paneer-tikka", 1, now_ms=T0)
        assert len(view.upsell_offers) == 1                 # dessert offer surfaced
        # jamun enters the cart NORMALLY -> the offer is moot; dal's bread rule
        # would now be eligible, but the cumulative cap is already spent
        carts.add_item(cart.cart_id, "itm_gulab-jamun", 1, now_ms=T0)
        view = carts.add_item(cart.cart_id, "itm_dal-makhani", 1, now_ms=T0)
        assert view.upsell_offers == ()

    def test_cap_two_surfaces_the_second_rule(self):
        _, _, carts = _world(cap=2)
        cart = carts.create("mnd_u", now_ms=T0)
        carts.add_item(cart.cart_id, "itm_paneer-tikka", 1, now_ms=T0)
        view = carts.add_item(cart.cart_id, "itm_dal-makhani", 1, now_ms=T0)
        assert {o["rule_id"] for o in view.upsell_offers} == {
            "rule_dessert_with_mains", "rule_bread_with_dal"}


class TestExplicitAcceptance:
    def test_acceptance_adds_the_line_and_marks_it(self):
        _, _, carts = _world()
        cart = carts.create("mnd_u", now_ms=T0)
        view = carts.add_item(cart.cart_id, "itm_paneer-tikka", 1, now_ms=T0)
        (offer,) = view.upsell_offers
        after = carts.accept_upsell(cart.cart_id, offer["offer_id"], now_ms=T0 + 1)
        jamun = next(ln for ln in after.lines if ln.item_id == "itm_gulab-jamun")
        assert jamun.upsell_rule_id == "rule_dessert_with_mains"
        assert after.total_minor == view.total_minor + offer["offer_total_minor"]

    @pytest.mark.critical
    def test_invented_offer_is_rejected_loudly(self):
        """The agent cannot fabricate an offer: only server-issued ids exist,
        and a made-up one is named a policy violation, not ignored."""
        _, _, carts = _world()
        cart = carts.create("mnd_u", now_ms=T0)
        carts.add_item(cart.cart_id, "itm_paneer-tikka", 1, now_ms=T0)
        with pytest.raises(CartError, match="policy violation"):
            carts.accept_upsell(cart.cart_id, "off_invented_1", now_ms=T0 + 1)

    def test_silent_addition_is_structurally_impossible(self):
        """No cart mutation ever adds an upsell line: only accept_upsell can,
        and it takes an explicit server-issued offer_id. The structural
        proof: after surfacing WITHOUT acceptance, the cart is unchanged."""
        _, _, carts = _world()
        cart = carts.create("mnd_u", now_ms=T0)
        view = carts.add_item(cart.cart_id, "itm_paneer-tikka", 1, now_ms=T0)
        assert view.upsell_offers                            # offered...
        again = carts.view(cart.cart_id, now_ms=T0 + 1)
        assert [ln.item_id for ln in again.lines] == ["itm_paneer-tikka"]  # ...never added


class TestAcceptanceRevalidates:
    """The review's flag: a value cleared at one moment and acted on at
    another. Acceptance re-checks EVERYTHING live."""

    @pytest.mark.critical
    def test_offer_cleared_earlier_is_withdrawn_when_the_cart_grew(self):
        """Cleared when affordable; the agent then adds items; acceptance
        would now exceed the mandate → withdrawn with a next step, cart
        unchanged. Same class as the re-price problem, same cure."""
        _, _, carts = _world(locked_minor=55000)             # ₹550
        cart = carts.create("mnd_u", now_ms=T0)
        view = carts.add_item(cart.cart_id, "itm_paneer-tikka", 1, now_ms=T0)  # 21000
        (offer,) = view.upsell_offers                        # cleared: 21000+8960 ≤ 55000
        carts.add_item(cart.cart_id, "itm_dal-makhani", 1, now_ms=T0)          # +18900
        carts.add_item(cart.cart_id, "itm_tandoori-roti", 4, now_ms=T0)        # +10500 → 50400; +8960 > 55000
        with pytest.raises(CartError, match="no longer fits the mandate"):
            carts.accept_upsell(cart.cart_id, offer["offer_id"], now_ms=T0 + 1)
        view = carts.view(cart.cart_id, now_ms=T0 + 2)
        assert "itm_gulab-jamun" not in {ln.item_id for ln in view.lines}

    def test_offer_repriced_since_clearance_is_not_bound_stale(self):
        catalog, _, carts = _world()
        cart = carts.create("mnd_u", now_ms=T0)
        view = carts.add_item(cart.cart_id, "itm_paneer-tikka", 1, now_ms=T0)
        (offer,) = view.upsell_offers
        catalog.set_price("itm_gulab-jamun", 12000, now_ms=T0 + 1)   # ₹80 → ₹120
        with pytest.raises(CartError, match="re-priced"):
            carts.accept_upsell(cart.cart_id, offer["offer_id"], now_ms=T0 + 2)
        # the refreshed offer shows the NEW truth on the next view
        view = carts.view(cart.cart_id, now_ms=T0 + 3)
        (fresh,) = view.upsell_offers
        assert fresh["unit_price_minor"] == 12000
        assert fresh["offer_id"] == offer["offer_id"]        # same offer, not a cap hit

    def test_offer_gone_out_of_stock_is_withdrawn(self):
        catalog, _, carts = _world()
        cart = carts.create("mnd_u", now_ms=T0)
        view = carts.add_item(cart.cart_id, "itm_paneer-tikka", 1, now_ms=T0)
        (offer,) = view.upsell_offers
        catalog.set_availability("itm_gulab-jamun",
                                 Availability(stock=Stock.OUT_OF_STOCK), now_ms=T0 + 1)
        with pytest.raises(CartError, match="no longer available"):
            carts.accept_upsell(cart.cart_id, offer["offer_id"], now_ms=T0 + 2)


class TestReceiptMarksIt:
    def test_committed_breakdown_and_result_name_the_rule_and_offer(self):
        _, ledger, carts = _world()
        gate = CommitGate(carts, ledger, FixtureUpstream())
        cart = carts.create("mnd_u", now_ms=T0)
        view = carts.add_item(cart.cart_id, "itm_paneer-tikka", 1, now_ms=T0)
        (offer,) = view.upsell_offers
        after = carts.accept_upsell(cart.cart_id, offer["offer_id"], now_ms=T0 + 1)
        out = gate.commit(cart.cart_id, after.total_minor, "INR", now_ms=T0 + 2)
        assert out["committed"]
        (upsell,) = out["upsells"]
        assert upsell["item_id"] == "itm_gulab-jamun"
        assert upsell["rule_id"] == "rule_dessert_with_mains"
        assert upsell["offer_id"] == offer["offer_id"]
        assert upsell["accepted_at_ms"] == T0 + 1
        jamun_line = next(l for l in out["breakdown"] if l["item_id"] == "itm_gulab-jamun")
        assert jamun_line["upsell_rule_id"] == "rule_dessert_with_mains"
