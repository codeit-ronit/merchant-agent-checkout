"""Cart tools crossing the REAL SENTINEL boundary under the strict policy.

The Phase 2 boundary proofs:
* cart mutations are REVERSIBLE_WRITE / BindingRole.NONE and flow under strict;
* cart_commit is the ONE binding event: COLLECTION role, amount read from
  expected_amount_minor — and a commit produces exactly ONE boundary audit
  entry (the inner create_order never crosses, so nothing can double-count
  against the run aggregate — ADR-027);
* a price-shaped argument on a mutation is rejected loudly;
* a commit above the collection review tier escalates at the boundary —
  the gate never even runs.
"""

from __future__ import annotations

import pytest

from conduit.cart.gate import CommitGate, GateReason
from conduit.cart.service import CartService
from conduit.cart.store import InMemoryCartRepository
from conduit.catalog.seed import seed_catalog
from conduit.catalog.service import CatalogService
from conduit.catalog.store import InMemoryCatalogRepository
from conduit.mandate.ledger import DrawdownLedger, InMemoryLedgerRepository, Mandate
from conduit.mcp.upstream import ConduitUpstream
from sentinel.audit.ledger import AuditLedger, InMemoryLedgerRepository as AuditRepo
from sentinel.contracts.decision import InjectedEnv
from sentinel.contracts.enums import BindingRole, Disposition, RiskClass
from sentinel.fixtures.upstream import FixtureUpstream
from sentinel.policy_loader import load_policy_set
from sentinel.proxy.classifier import descriptor_index, reconcile
from sentinel.proxy.idempotency import IdempotencyGuard
from sentinel.proxy.interceptor import Interceptor, Signals
from sentinel.redaction.engine import RedactionSession
from sentinel.redaction.quarantine import QuarantineWrapper

pytestmark = pytest.mark.tier1

T0 = 1_000_000
NONCE = "test-nonce-cart"


@pytest.fixture()
def world():
    catalog = CatalogService(InMemoryCatalogRepository())
    seed_catalog(catalog)
    drawdown = DrawdownLedger(InMemoryLedgerRepository())
    drawdown.create_mandate(Mandate("mnd_dinner", 200000, "INR"))
    carts = CartService(InMemoryCartRepository(), catalog, drawdown)
    inner = FixtureUpstream()
    gate = CommitGate(carts, drawdown, inner)
    clock = {"now": T0}
    upstream = ConduitUpstream(inner, catalog, cart=carts, gate=gate,
                               now_ms_fn=lambda: clock["now"])
    audit = AuditLedger(AuditRepo())
    interceptor = Interceptor(
        upstream=upstream, policy_set=load_policy_set("strict"),
        ledger=audit, session=RedactionSession("cart-run", salt=b"z" * 16),
        quarantine=QuarantineWrapper(nonce=NONCE), idempotency=IdempotencyGuard(),
        run_meta=dict(run_id="cart-run", agent_id="reconciliation", agent_version="1",
                      operator_id="op", policy_set_id="strict", git_commit="test"))
    descriptors = descriptor_index(reconcile(upstream.list_tools()))
    return interceptor, descriptors, audit, clock, catalog, drawdown


def _call(world, tool, args):
    interceptor, descriptors, *_ = world
    return interceptor.handle_call(descriptors[tool], args,
                                   InjectedEnv(now_epoch_ms=T0), Signals(), "s", "c")


class TestClassification:
    def test_cart_commit_is_the_one_binding_tool(self, world):
        _, descriptors, *_ = world
        commit = descriptors["cart_commit"]
        assert commit.risk_class is RiskClass.REVERSIBLE_WRITE
        assert commit.binding_role is BindingRole.COLLECTION
        assert commit.amount_arg_path == "expected_amount_minor"
        for name in ("cart_create", "cart_add_item", "cart_update_item",
                     "cart_remove_item", "cart_view", "cart_clear"):
            assert descriptors[name].binding_role is BindingRole.NONE, name


class TestFlowThroughBoundary:
    def test_full_purchase_flow_allowed_under_strict(self, world):
        interceptor, descriptors, audit, *_ = world
        created = _call(world, "cart_create", {"mandate_id": "mnd_dinner"})
        assert created.disposition is Disposition.ALLOW
        cart_id_raw = created.result["cart_id"]
        added = _call(world, "cart_add_item",
                      {"cart_id": cart_id_raw, "item_id": "itm_paneer-tikka", "quantity": 2})
        assert added.disposition is Disposition.ALLOW
        assert added.result["total_minor"] == 42000
        assert added.result["mandate_remaining_minor"] == 200000
        out = _call(world, "cart_commit",
                    {"cart_id": cart_id_raw, "expected_amount_minor": 42000,
                     "currency": "INR"})
        assert out.disposition is Disposition.ALLOW and out.executed
        assert out.result["committed"] is True
        assert out.result["order_id"].startswith("order_")
        assert out.result["mandate_remaining_minor"] == 158000

    @pytest.mark.critical
    def test_one_binding_event_one_audit_entry(self, world):
        """ADR-027: the commit is ONE boundary crossing. The gate's inner
        create_order must not appear as a second audit entry, or the run
        aggregate would double-count."""
        _, _, audit, *_ = world
        created = _call(world, "cart_create", {"mandate_id": "mnd_dinner"})
        cart_id = created.result["cart_id"]
        _call(world, "cart_add_item",
              {"cart_id": cart_id, "item_id": "itm_garlic-naan", "quantity": 2})
        before = len(audit.entries())
        out = _call(world, "cart_commit",
                    {"cart_id": cart_id, "expected_amount_minor": 8400, "currency": "INR"})
        assert out.result["committed"] is True
        entries = audit.entries()[before:]
        assert len(entries) == 1                      # exactly one crossing
        assert entries[0].tool_name == "cart_commit"  # and it is the commit,
        names = [e.tool_name for e in audit.entries()]
        assert "create_order" not in names            # never the inner write

    def test_commit_above_review_tier_is_caught_at_the_boundary(self, world):
        """Collections over ₹10,000 (1,000,000 minor) need review under the
        strict policy. The boundary reads expected_amount_minor and stops the
        call BEFORE the gate runs — nothing reserved, nothing forwarded."""
        _, _, _, _, _, drawdown = world
        drawdown.create_mandate(Mandate("mnd_big", 100_000_000, "INR"))
        created = _call(world, "cart_create", {"mandate_id": "mnd_big"})
        cart_id = created.result["cart_id"]
        out = _call(world, "cart_commit",
                    {"cart_id": cart_id, "expected_amount_minor": 1_500_000,
                     "currency": "INR"})
        assert out.disposition is not Disposition.ALLOW
        assert not out.executed
        assert drawdown.balance("mnd_big").reserved_minor == 0

    def test_price_arg_on_mutation_rejected_loudly(self, world):
        created = _call(world, "cart_create", {"mandate_id": "mnd_dinner"})
        cart_id = created.result["cart_id"]
        out = _call(world, "cart_add_item",
                    {"cart_id": cart_id, "item_id": "itm_garlic-naan",
                     "quantity": 1, "unit_price": 1})
        assert not out.executed
        assert out.upstream_error or out.disposition is not Disposition.ALLOW

    def test_rejection_reaches_the_agent_as_structured_data(self, world):
        """A re-price divergence is a well-formed ALLOW-and-executed response
        carrying the structured diff — not an opaque error."""
        interceptor, descriptors, audit, clock, catalog, _ = world
        created = _call(world, "cart_create", {"mandate_id": "mnd_dinner"})
        cart_id = created.result["cart_id"]
        _call(world, "cart_add_item",
              {"cart_id": cart_id, "item_id": "itm_paneer-tikka", "quantity": 1})
        catalog.set_price("itm_paneer-tikka", 24000, now_ms=T0 + 1)
        out = _call(world, "cart_commit",
                    {"cart_id": cart_id, "expected_amount_minor": 21000,
                     "currency": "INR"})
        assert out.executed
        assert out.result["committed"] is False
        assert out.result["reason_code"] == GateReason.REJECT_REPRICE_DIVERGENCE.value
        assert out.result["diff"]["lines"][0]["actual_unit_minor"] == 24000
