"""Mandate lifecycle (05-MANDATE §3.3): create, revoke-instant-and-total,
absolute expiry, ledger defence-in-depth, and the mid-flight revocation path
through the commit gate."""

from __future__ import annotations

import pytest

from conduit.cart.gate import CommitGate, GateReason
from conduit.cart.service import CartService
from conduit.cart.store import InMemoryCartRepository
from conduit.catalog.seed import MERCHANT, seed_catalog
from conduit.catalog.service import CatalogService
from conduit.catalog.store import InMemoryCatalogRepository
from conduit.mandate.ledger import DrawdownLedger, InMemoryLedgerRepository, LedgerError
from conduit.mandate.service import MandateService
from sentinel.fixtures.upstream import FixtureUpstream

pytestmark = pytest.mark.tier1

T0 = 1_000_000
WEEK = 7 * 24 * 3600 * 1000


@pytest.fixture()
def world():
    catalog = CatalogService(InMemoryCatalogRepository())
    seed_catalog(catalog)
    ledger = DrawdownLedger(InMemoryLedgerRepository())
    mandates = MandateService(ledger)
    mandate = mandates.create(locked_minor=200000, currency="INR",
                              scope_merchant_id=MERCHANT.merchant_id,
                              expires_at_ms=T0 + WEEK,
                              instrument_contact="9876543210", now_ms=T0)
    carts = CartService(InMemoryCartRepository(), catalog, ledger)
    gate = CommitGate(carts, ledger, FixtureUpstream())
    return mandates, ledger, carts, gate, mandate


class TestLifecycle:
    def test_create_validates_scope_and_future_expiry(self, world):
        mandates, *_ = world
        with pytest.raises(LedgerError, match="future"):
            mandates.create(locked_minor=1000, currency="INR",
                            scope_merchant_id="m", expires_at_ms=T0, now_ms=T0)
        with pytest.raises(LedgerError, match="scoped"):
            mandates.create(locked_minor=1000, currency="INR",
                            scope_merchant_id="", expires_at_ms=T0 + 1, now_ms=T0)

    def test_env_snapshot_is_ledger_derived(self, world):
        mandates, ledger, _, _, mandate = world
        ledger.reserve(mandate.mandate_id, 50000, ref="cart_x", now_ms=T0)
        env = mandates.to_env(mandate.mandate_id)
        assert env.remaining_minor == 150000        # derived, not stored
        assert env.scope_merchant_id == MERCHANT.merchant_id

    def test_revoke_is_instant_and_releases_open_holds(self, world):
        mandates, ledger, _, _, mandate = world
        ledger.reserve(mandate.mandate_id, 50000, ref="cart_x", now_ms=T0)
        mandates.revoke(mandate.mandate_id, now_ms=T0 + 1)
        bal = ledger.balance(mandate.mandate_id)
        assert bal.reserved_minor == 0              # holds released NOW
        with pytest.raises(LedgerError, match="REVOKED"):
            ledger.reserve(mandate.mandate_id, 1000, ref="cart_y", now_ms=T0 + 2)

    def test_expiry_refuses_new_reservations(self, world):
        mandates, ledger, _, _, mandate = world
        with pytest.raises(LedgerError, match="expired"):
            ledger.reserve(mandate.mandate_id, 1000, ref="c", now_ms=T0 + WEEK)

    def test_public_view_derives_effective_status(self, world):
        mandates, ledger, _, _, mandate = world
        view = mandates.public_view(mandate.mandate_id, now_ms=T0)
        assert view["status"] == "ACTIVE" and view["remaining_minor"] == 200000
        assert mandates.public_view(mandate.mandate_id, now_ms=T0 + WEEK)["status"] == "EXPIRED"


class TestMidFlightRevocation:
    @pytest.mark.critical
    def test_revocation_between_reserve_and_confirm_denies_the_drawdown(self, world):
        """An agent mid-purchase against a revoked mandate is stopped — never
        allowed to finish 'because it already started'. The order may exist
        upstream; NOTHING is drawn, and the gate says so truthfully."""
        mandates, ledger, carts, _, mandate = world

        class RevokingUpstream:
            """Simulates the user revoking WHILE create_order is in flight."""
            def __init__(self):
                self.order_count = 0
            def call_tool(self, name, args):
                assert name == "create_order"
                self.order_count += 1
                mandates.revoke(mandate.mandate_id, now_ms=T0 + 5)
                return {"id": "order_midflight", "status": "created", **args}

        gate = CommitGate(carts, ledger, RevokingUpstream())
        cart = carts.create(mandate.mandate_id, now_ms=T0)
        view = carts.add_item(cart.cart_id, "itm_paneer-tikka", 1, now_ms=T0)
        out = gate.commit(cart.cart_id, view.total_minor, "INR", now_ms=T0 + 1)

        assert out["committed"] is False
        assert out["reason_code"] == GateReason.REJECT_MANDATE_REVOKED_MIDFLIGHT.value
        assert out["order_id"] == "order_midflight"    # honest: the order exists
        assert "Nothing was charged" in out["next_step"]
        bal = ledger.balance(mandate.mandate_id)
        assert (bal.drawn_minor, bal.reserved_minor) == (0, 0)
