"""Cart service: server pricing, constraints, mandate visibility, expiry."""

from __future__ import annotations

import pytest

from conduit.cart.model import CartError, CartStatus
from conduit.cart.service import DEFAULT_TTL_MS, CartService
from conduit.cart.store import InMemoryCartRepository, SqliteCartRepository
from conduit.catalog.seed import seed_catalog
from conduit.catalog.service import CatalogService
from conduit.catalog.store import InMemoryCatalogRepository
from conduit.mandate.ledger import DrawdownLedger, InMemoryLedgerRepository, Mandate

pytestmark = pytest.mark.tier1

T0 = 1_000_000  # deterministic epoch for the tests


@pytest.fixture(params=["memory", "sqlite"])
def carts(request, tmp_path):
    catalog = CatalogService(InMemoryCatalogRepository())
    seed_catalog(catalog)
    ledger = DrawdownLedger(InMemoryLedgerRepository())
    ledger.create_mandate(Mandate("mnd_dinner", 200000, "INR"))  # ₹2,000
    repo = (InMemoryCartRepository() if request.param == "memory"
            else SqliteCartRepository(tmp_path / "carts.db"))
    return CartService(repo, catalog, ledger), catalog, ledger


class TestServerPricing:
    def test_every_mutation_returns_server_totals_and_mandate_remaining(self, carts):
        svc, _, _ = carts
        cart = svc.create("mnd_dinner", now_ms=T0)
        assert cart.total_minor == 0 and cart.mandate_remaining_minor == 200000
        cart = svc.add_item(cart.cart_id, "itm_paneer-tikka", 2, now_ms=T0)
        # 2 × ₹200 = ₹400 + 5% tax ₹20
        assert cart.subtotal_minor == 40000
        assert cart.tax_total_minor == 2000
        assert cart.total_minor == 42000
        assert cart.mandate_remaining_minor == 200000  # nothing reserved yet: off-rail
        (line,) = cart.lines
        assert line.unit_price_minor == 20000 and line.price_version == 1

    def test_tax_is_integer_floor_per_declared_treatment(self, carts):
        svc, _, _ = carts
        cart = svc.create("mnd_dinner", now_ms=T0)
        # gulab jamun ₹80 @ 12% → 8000 * 1200 // 10000 = 960
        cart = svc.add_item(cart.cart_id, "itm_gulab-jamun", 1, now_ms=T0)
        assert cart.lines[0].tax_minor == 960

    def test_phantom_item_rejected_at_the_cart_boundary(self, carts):
        svc, _, _ = carts
        cart = svc.create("mnd_dinner", now_ms=T0)
        with pytest.raises(CartError, match="phantom items are rejected"):
            svc.add_item(cart.cart_id, "itm_unicorn", 1, now_ms=T0)

    def test_quantity_constraints_enforced(self, carts):
        svc, _, _ = carts
        cart = svc.create("mnd_dinner", now_ms=T0)
        with pytest.raises(CartError, match="at most 12"):
            svc.add_item(cart.cart_id, "itm_garlic-naan", 13, now_ms=T0)
        with pytest.raises(CartError, match="positive integer"):
            svc.add_item(cart.cart_id, "itm_garlic-naan", 0, now_ms=T0)

    def test_update_remove_clear(self, carts):
        svc, _, _ = carts
        cart = svc.create("mnd_dinner", now_ms=T0)
        svc.add_item(cart.cart_id, "itm_garlic-naan", 4, now_ms=T0)
        cart = svc.update_item(cart.cart_id, "itm_garlic-naan", 2, now_ms=T0)
        assert cart.lines[0].quantity == 2
        cart = svc.remove_item(cart.cart_id, "itm_garlic-naan", now_ms=T0)
        assert cart.lines == ()
        with pytest.raises(CartError, match="not in the cart"):
            svc.remove_item(cart.cart_id, "itm_garlic-naan", now_ms=T0)

    def test_reprice_reflects_catalog_change_on_next_view(self, carts):
        svc, catalog, _ = carts
        cart = svc.create("mnd_dinner", now_ms=T0)
        svc.add_item(cart.cart_id, "itm_paneer-tikka", 1, now_ms=T0)
        catalog.set_price("itm_paneer-tikka", 24000, now_ms=T0 + 1)
        cart = svc.view(cart.cart_id, now_ms=T0 + 2)
        assert cart.lines[0].unit_price_minor == 24000
        assert cart.lines[0].price_version == 2


class TestExpiry:
    def test_expired_cart_rejects_mutations_with_next_step(self, carts):
        svc, _, _ = carts
        cart = svc.create("mnd_dinner", now_ms=T0)
        later = T0 + DEFAULT_TTL_MS + 1
        with pytest.raises(CartError, match="expired"):
            svc.add_item(cart.cart_id, "itm_garlic-naan", 1, now_ms=later)
        assert svc.record(cart.cart_id).status is CartStatus.EXPIRED

    def test_expiry_releases_a_held_reservation(self, carts):
        svc, _, ledger = carts
        cart = svc.create("mnd_dinner", now_ms=T0)
        svc.add_item(cart.cart_id, "itm_paneer-tikka", 1, now_ms=T0)
        # simulate a hold left by an interrupted commit
        ledger.reserve("mnd_dinner", 21000, ref=cart.cart_id, now_ms=T0)
        assert ledger.balance("mnd_dinner").reserved_minor == 21000
        svc.view(cart.cart_id, now_ms=T0 + DEFAULT_TTL_MS + 1)  # touch → expire
        bal = ledger.balance("mnd_dinner")
        assert bal.reserved_minor == 0 and bal.remaining_minor == 200000

    def test_unknown_mandate_fails_closed_at_create(self, carts):
        svc, _, _ = carts
        with pytest.raises(Exception, match="no mandate"):
            svc.create("mnd_ghost", now_ms=T0)
