"""The commit gate — every Phase 2 exit criterion that lives at the gate.

Uses the real FixtureUpstream for create_order (an order id gets minted) and
failure-injecting stubs for the upstream-failed and catalog-unreachable paths.
"""

from __future__ import annotations

import pytest

from conduit.cart.gate import CommitGate, GateReason, notes_as_dict
from conduit.cart.model import CartStatus
from conduit.cart.service import CartService
from conduit.cart.store import InMemoryCartRepository
from conduit.catalog.model import Availability, Stock
from conduit.catalog.seed import seed_catalog
from conduit.catalog.service import CatalogService
from conduit.catalog.store import InMemoryCatalogRepository
from conduit.mandate.ledger import DrawdownLedger, InMemoryLedgerRepository, Mandate
from sentinel.fixtures.upstream import FixtureUpstream

pytestmark = pytest.mark.tier1

T0 = 1_000_000


class CountingUpstream:
    """FixtureUpstream + a real count of create_order forwards. The fixture's
    own `.executed` records only MONEY_MOVEMENT tools, so asserting on it for
    create_order would pass trivially and prove nothing."""

    def __init__(self):
        self._inner = FixtureUpstream()
        self.create_order_calls = 0

    def call_tool(self, name, args):
        if name == "create_order":
            self.create_order_calls += 1
        return self._inner.call_tool(name, args)

    def list_tools(self):
        return self._inner.list_tools()


@pytest.fixture()
def world():
    catalog = CatalogService(InMemoryCatalogRepository())
    seed_catalog(catalog)
    ledger = DrawdownLedger(InMemoryLedgerRepository())
    ledger.create_mandate(Mandate("mnd_dinner", 200000, "INR"))
    carts = CartService(InMemoryCartRepository(), catalog, ledger)
    upstream = CountingUpstream()
    gate = CommitGate(carts, ledger, upstream)
    return carts, catalog, ledger, gate, upstream


def _dinner_cart(carts) -> tuple[str, int]:
    """Paneer ×2 + naan ×4: 40000+16000 subtotal, 5% tax → total 58800."""
    cart = carts.create("mnd_dinner", now_ms=T0)
    carts.add_item(cart.cart_id, "itm_paneer-tikka", 2, now_ms=T0)
    view = carts.add_item(cart.cart_id, "itm_garlic-naan", 4, now_ms=T0)
    return cart.cart_id, view.total_minor


class TestHappyPath:
    def test_commit_mints_an_order_and_confirms_the_drawdown(self, world):
        carts, _, ledger, gate, _ = world
        cart_id, total = _dinner_cart(carts)
        out = gate.commit(cart_id, total, "INR", now_ms=T0 + 1)
        assert out["committed"] and out["reason_code"] == GateReason.COMMITTED.value
        assert out["order_id"].startswith("order_")
        assert out["amount_minor"] == total
        assert out["mandate_remaining_minor"] == 200000 - total
        assert len(out["breakdown"]) == 2
        bal = ledger.balance("mnd_dinner")
        assert (bal.drawn_minor, bal.reserved_minor) == (total, 0)
        assert carts.record(cart_id).status is CartStatus.COMMITTED

    def test_result_carries_catalog_version_and_notes_echo(self, world):
        carts, catalog, _, gate, _ = world
        cart_id, total = _dinner_cart(carts)
        out = gate.commit(cart_id, total, "INR", now_ms=T0 + 1)
        assert out["catalog_version"] == catalog.catalog_version()
        assert out["notes_echo"]["conduit_cart_id"] == cart_id


class TestRepriceDiff:
    def test_divergence_rejects_with_itemised_why_and_preserves_cart(self, world):
        carts, catalog, ledger, gate, _ = world
        cart_id, total = _dinner_cart(carts)
        catalog.set_price("itm_paneer-tikka", 24000, now_ms=T0 + 1)  # ₹200 → ₹240
        out = gate.commit(cart_id, total, "INR", now_ms=T0 + 2)

        assert not out["committed"]
        assert out["reason_code"] == GateReason.REJECT_REPRICE_DIVERGENCE.value
        diff = out["diff"]
        # new true total: subtotal 48000+16000, tax 5% → 67200
        assert diff["actual_total_minor"] == 67200
        assert diff["delta_minor"] == 67200 - total
        changed = next(d for d in diff["lines"] if d["item_id"] == "itm_paneer-tikka")
        assert changed["believed_unit_minor"] == 20000
        assert changed["actual_unit_minor"] == 24000
        assert "v1→v2" in changed["why"]                       # WHY, not just that
        assert changed["line_delta_minor"] == 8000             # ×2 quantity
        unchanged = next(d for d in diff["lines"] if d["item_id"] == "itm_garlic-naan")
        assert unchanged["why"] == "unchanged"
        # cart preserved, nothing reserved, nothing committed
        assert carts.record(cart_id).status is CartStatus.OPEN
        assert ledger.balance("mnd_dinner").reserved_minor == 0
        assert "re-commit with expected_amount_minor=67200" in out["next_step"]

    def test_reconfirm_after_divergence_commits_at_the_new_truth(self, world):
        carts, catalog, _, gate, _ = world
        cart_id, total = _dinner_cart(carts)
        catalog.set_price("itm_paneer-tikka", 24000, now_ms=T0 + 1)
        rejected = gate.commit(cart_id, total, "INR", now_ms=T0 + 2)
        new_total = rejected["diff"]["actual_total_minor"]
        out = gate.commit(cart_id, new_total, "INR", now_ms=T0 + 3)
        assert out["committed"] and out["amount_minor"] == 67200

    def test_hallucinated_total_gets_the_honest_message(self, world):
        """No price changed — the agent's arithmetic is simply wrong. The
        rejection must say so rather than blaming a re-price."""
        carts, _, _, gate, _ = world
        cart_id, total = _dinner_cart(carts)
        out = gate.commit(cart_id, total + 1000, "INR", now_ms=T0 + 1)
        assert out["reason_code"] == GateReason.REJECT_STATED_TOTAL_WRONG.value
        assert all(d["why"] == "unchanged" for d in out["diff"]["lines"])
        assert "agents do not" in out["message"]

    def test_stale_amount_never_binds(self, world):
        """The core property: after a price change, the OLD amount cannot
        produce an order under any sequence of retries."""
        carts, catalog, ledger, gate, upstream = world
        cart_id, total = _dinner_cart(carts)
        catalog.set_price("itm_paneer-tikka", 24000, now_ms=T0 + 1)
        for _ in range(3):
            out = gate.commit(cart_id, total, "INR", now_ms=T0 + 2)
            assert not out["committed"]
        assert ledger.balance("mnd_dinner").drawn_minor == 0
        assert upstream.create_order_calls == 0  # no create_order ever forwarded


class TestAvailabilityAndConstraints:
    def test_out_of_stock_names_the_item_never_substitutes(self, world):
        carts, catalog, _, gate, _ = world
        cart_id, total = _dinner_cart(carts)
        catalog.set_availability("itm_garlic-naan",
                                 Availability(stock=Stock.OUT_OF_STOCK), now_ms=T0 + 1)
        out = gate.commit(cart_id, total, "INR", now_ms=T0 + 2)
        assert out["reason_code"] == GateReason.REJECT_UNAVAILABLE.value
        assert out["unavailable_item_id"] == "itm_garlic-naan"
        assert "never substitutes" in out["next_step"]

    def test_limited_stock_shortfall_is_specific(self, world):
        carts, catalog, _, gate, _ = world
        cart = carts.create("mnd_dinner", now_ms=T0)
        view = carts.add_item(cart.cart_id, "itm_veg-biryani", 4, now_ms=T0)  # 4 left: fits
        catalog.set_availability("itm_veg-biryani",
                                 Availability(stock=Stock.LIMITED, count=2), now_ms=T0 + 1)
        out = gate.commit(cart.cart_id, view.total_minor, "INR", now_ms=T0 + 2)
        assert out["reason_code"] == GateReason.REJECT_UNAVAILABLE.value
        assert "2 left" in out["message"]


class TestMandate:
    def test_insufficient_balance_denies_before_any_order_with_shortfall(self, world):
        carts, _, ledger, gate, upstream = world
        cart = carts.create("mnd_dinner", now_ms=T0)
        view = carts.add_item(cart.cart_id, "itm_family-thali", 3, now_ms=T0)
        # 3 × ₹450 = ₹1350 + 5% = 141750 — fits ₹2000? yes. Draw it down first:
        ledger.reserve("mnd_dinner", 150000, ref="other_cart", now_ms=T0)
        out = gate.commit(cart.cart_id, view.total_minor, "INR", now_ms=T0 + 1)
        assert out["reason_code"] == GateReason.REJECT_MANDATE_INSUFFICIENT.value
        assert "short by" in out["message"]
        assert upstream.create_order_calls == 0  # denied BEFORE create_order
        assert carts.record(cart.cart_id).status is CartStatus.OPEN


class TestIdempotency:
    def test_same_request_twice_one_order(self, world):
        carts, _, ledger, gate, _ = world
        cart_id, total = _dinner_cart(carts)
        first = gate.commit(cart_id, total, "INR", now_ms=T0 + 1)
        second = gate.commit(cart_id, total, "INR", now_ms=T0 + 2)
        assert second["idempotent_replay"] is True
        assert second["order_id"] == first["order_id"]
        assert ledger.balance("mnd_dinner").drawn_minor == total  # once

    def test_recommit_with_different_amount_is_rejected_not_reordered(self, world):
        carts, _, _, gate, _ = world
        cart_id, total = _dinner_cart(carts)
        gate.commit(cart_id, total, "INR", now_ms=T0 + 1)
        out = gate.commit(cart_id, total + 100, "INR", now_ms=T0 + 2)
        assert out["reason_code"] == GateReason.REJECT_ALREADY_COMMITTED.value


class TestFailClosed:
    def test_failed_create_order_releases_the_reservation(self, world):
        carts, _, ledger, _, _ = world

        class ExplodingUpstream:
            def call_tool(self, name, args):
                raise RuntimeError("upstream down")

        gate = CommitGate(carts, ledger, ExplodingUpstream())
        cart_id, total = _dinner_cart(carts)
        out = gate.commit(cart_id, total, "INR", now_ms=T0 + 1)
        assert out["reason_code"] == GateReason.REJECT_UPSTREAM_FAILED.value
        bal = ledger.balance("mnd_dinner")
        assert (bal.reserved_minor, bal.drawn_minor) == (0, 0)   # released
        assert carts.record(cart_id).status is CartStatus.OPEN   # recoverable
        assert "retry" in out["next_step"]

    def test_upstream_without_order_id_is_a_failure_not_a_commit(self, world):
        carts, _, ledger, _, _ = world

        class NoIdUpstream:
            def call_tool(self, name, args):
                return {"status": "created"}  # no id — treat as failure

        gate = CommitGate(carts, ledger, NoIdUpstream())
        cart_id, total = _dinner_cart(carts)
        out = gate.commit(cart_id, total, "INR", now_ms=T0 + 1)
        assert out["reason_code"] == GateReason.REJECT_UPSTREAM_FAILED.value
        assert ledger.balance("mnd_dinner").reserved_minor == 0

    def test_catalog_unreachable_fails_closed_before_reserving(self, world):
        carts, catalog, ledger, gate, upstream = world
        cart_id, total = _dinner_cart(carts)

        def explode(*a, **k):
            raise ConnectionError("catalog down")

        catalog.get_item = explode  # every re-price read now fails
        out = gate.commit(cart_id, total, "INR", now_ms=T0 + 1)
        assert out["reason_code"] == GateReason.REJECT_CATALOG_UNREACHABLE.value
        assert "cached price" in out["message"]
        assert ledger.balance("mnd_dinner").reserved_minor == 0
        assert upstream.create_order_calls == 0

    def test_expired_cart_rejects_commit(self, world):
        carts, _, _, gate, _ = world
        cart_id, total = _dinner_cart(carts)
        from conduit.cart.service import DEFAULT_TTL_MS
        out = gate.commit(cart_id, total, "INR", now_ms=T0 + DEFAULT_TTL_MS + 1)
        assert out["reason_code"] == GateReason.REJECT_CART_EXPIRED.value

    def test_currency_mismatch_and_empty_cart(self, world):
        carts, _, _, gate, _ = world
        cart = carts.create("mnd_dinner", now_ms=T0)
        out = gate.commit(cart.cart_id, 0, "USD", now_ms=T0 + 1)
        assert out["reason_code"] == GateReason.REJECT_CURRENCY_MISMATCH.value
        out = gate.commit(cart.cart_id, 0, "INR", now_ms=T0 + 1)
        assert out["reason_code"] == GateReason.REJECT_EMPTY_CART.value


class TestNotesShapes:
    def test_notes_read_back_handles_both_serialisations(self):
        """ADR-030: empty list when absent, object when populated."""
        assert notes_as_dict([]) == {}
        assert notes_as_dict(None) == {}
        assert notes_as_dict({"k": "v"}) == {"k": "v"}
        assert notes_as_dict("stray") == {}
