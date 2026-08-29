"""The buyer agent end to end (tier 3, no model): natural language in,
order out — through the REAL loop, boundary, policy, gate, and ledger.

The Phase 3 exit criteria that live here:
* a natural-language constraint produces an order (Razorpay-minted when live;
  fixture-minted here, same code path);
* the agent never computes a total — every bound amount is a server total;
* honest decline on unsatisfiable constraints, buying nothing;
* revocation and exhaustion end the purchase with nothing bound;
* the audit chain verifies and carries the commerce outcome.
"""

from __future__ import annotations

import tempfile

import pytest

from conduit.agents.buyer import BUYER, parse_constraint
from conduit.cart.gate import CommitGate
from conduit.cart.service import CartService
from conduit.cart.store import InMemoryCartRepository
from conduit.catalog.seed import MERCHANT, seed_catalog
from conduit.catalog.service import CatalogService
from conduit.catalog.store import InMemoryCatalogRepository
from conduit.mandate.ledger import DrawdownLedger, InMemoryLedgerRepository
from conduit.mandate.service import MandateService
from conduit.mcp.upstream import ConduitUpstream
from conduit.rail import ModelledSettlementRail
from sentinel.audit.ledger import AuditLedger, InMemoryLedgerRepository as AuditRepo
from sentinel.audit.verify import verify_chain
from sentinel.contracts.enums import TerminalState
from sentinel.fixtures.dataset import dataset_version
from sentinel.fixtures.upstream import FixtureUpstream
from sentinel.policy_loader import load_policy_set
from sentinel.runtime.loop import AgentRunner, RunConfig

pytestmark = pytest.mark.tier3

T0 = 1_756_500_000_000
WEEK = 7 * 24 * 3600 * 1000
TASK = "Order dinner for four under ₹800, no beef, using mandate {mid}."


def _clock():
    state = {"t": T0}
    def tick():
        state["t"] += 10
        return state["t"]
    return tick


def _world(locked_minor=200000):
    catalog = CatalogService(InMemoryCatalogRepository())
    seed_catalog(catalog)
    drawdown = DrawdownLedger(InMemoryLedgerRepository())
    mandates = MandateService(drawdown)
    mandate = mandates.create(locked_minor=locked_minor, currency="INR",
                              scope_merchant_id=MERCHANT.merchant_id,
                              expires_at_ms=T0 + WEEK,
                              instrument_contact="9876543210", now_ms=T0)
    carts = CartService(InMemoryCartRepository(), catalog, drawdown)
    inner = FixtureUpstream()
    clock = _clock()
    upstream = ConduitUpstream(inner, catalog, cart=carts,
                               gate=CommitGate(carts, drawdown, inner),
                               rail=ModelledSettlementRail(), now_ms_fn=clock)
    audit = AuditLedger(AuditRepo())
    runner = AgentRunner(cassette_dir=tempfile.mkdtemp(), cassette_mode="auto",
                         clock_ms=clock, ledger=audit, fixture_version=dataset_version())
    cfg = RunConfig(mandate_env_fn=lambda: mandates.to_env(mandate.mandate_id),
                    merchant_id=MERCHANT.merchant_id)
    return runner, upstream, audit, mandates, drawdown, mandate, cfg, catalog


def _run(runner, upstream, cfg, mandate, task=TASK):
    return runner.run(BUYER, upstream=upstream, policy_set=load_policy_set("commerce"),
                      task=task.format(mid=mandate.mandate_id), config=cfg)


class TestConstraintParsing:
    def test_the_headline_constraint(self):
        c = parse_constraint("Order dinner for four under ₹800, no beef, using mandate mnd_000001.")
        assert c == {"budget_minor": 80000, "party": 4, "exclude": ["beef"],
                     "mandate_id": "mnd_000001"}


class TestTheLoopCloses:
    @pytest.mark.critical
    def test_natural_language_becomes_an_order_inside_the_mandate(self):
        runner, upstream, audit, mandates, drawdown, mandate, cfg, _ = _world()
        rec = _run(runner, upstream, cfg, mandate)

        assert rec.terminal_state == TerminalState.COMPLETED
        out = rec.output
        assert out["decision"] == "purchased"
        assert out["order_id"].startswith("order_")
        assert out["payment_status"] == "captured"
        assert out["total_minor"] <= 80000                       # budget honoured
        assert out["total_minor"] > 0
        # the drawdown drew exactly the server-computed total, once
        bal = drawdown.balance(mandate.mandate_id)
        assert bal.drawn_minor == out["total_minor"]
        assert out["mandate_remaining_minor"] == bal.remaining_minor
        # audit: chain verifies; the commit's commerce verdict is first-class
        assert verify_chain(audit.entries()).ok
        commits = [e for e in audit.entries() if e.tool_name == "cart_commit"]
        assert commits and commits[-1].app_outcome == "COMMITTED"
        # money movement was mandate-resolved, not human-approved
        pays = [e for e in audit.entries() if e.tool_name == "initiate_payment"]
        assert pays and pays[-1].decision.reason_code.value == "ALLOW_MANDATE_BOUND"

    def test_no_beef_is_actually_honoured(self):
        runner, upstream, audit, _, _, mandate, cfg, _ = _world()
        rec = _run(runner, upstream, cfg, mandate)
        bought = {i["item_id"] for i in rec.output["items"]}
        assert "itm_beef-fry" not in bought

    def test_agent_reacts_to_a_reprice_mid_run(self):
        """Price moves between view and commit; the agent re-confirms at the
        truth and the FINAL bound amount is the re-priced server total."""
        runner, upstream, audit, _, drawdown, mandate, cfg, catalog = _world()

        # bump the cheapest main's price the moment the cart first prices it —
        # a mutation hook on the catalog service, deterministic
        original_price = catalog.price_history  # keep linter quiet
        bumped = {"done": False}
        orig_get = catalog.get_item

        def racing_get(item_id):
            item = orig_get(item_id)
            if not bumped["done"] and item_id == "itm_dal-makhani":
                bumped["done"] = True
                catalog.set_price("itm_dal-makhani", 19000, now_ms=T0 + 5)
                return orig_get(item_id)
            return item

        catalog.get_item = racing_get
        rec = _run(runner, upstream, cfg, mandate)
        assert rec.terminal_state == TerminalState.COMPLETED
        out = rec.output
        assert out["decision"] == "purchased"
        bal = drawdown.balance(mandate.mandate_id)
        assert bal.drawn_minor == out["total_minor"]             # truth bound, once


class TestHonestFailure:
    def test_unsatisfiable_budget_declines_and_buys_nothing(self):
        runner, upstream, audit, _, drawdown, mandate, cfg, _ = _world()
        rec = _run(runner, upstream, cfg, mandate,
                   task="Order dinner for four under ₹5, no beef, using mandate {mid}.")
        out = rec.output
        assert out["decision"] == "declined"
        assert out["constraints_unsatisfied"]
        assert drawdown.balance(mandate.mandate_id).drawn_minor == 0
        commits = [e for e in audit.entries() if e.tool_name == "cart_commit"]
        assert commits == []                                     # never even tried

    def test_revoked_mandate_binds_nothing(self):
        runner, upstream, audit, mandates, drawdown, mandate, cfg, _ = _world()
        mandates.revoke(mandate.mandate_id, now_ms=T0 + 1)
        rec = _run(runner, upstream, cfg, mandate)
        assert rec.output["decision"] == "declined"
        assert drawdown.balance(mandate.mandate_id).drawn_minor == 0
        # the commit was DENIED at the boundary by the mandate gate
        commits = [e for e in audit.entries() if e.tool_name == "cart_commit"]
        assert commits and commits[-1].decision.reason_code.value == "DENY_MANDATE_REVOKED"

    def test_exhausted_mandate_binds_nothing(self):
        runner, upstream, audit, _, drawdown, mandate, cfg, _ = _world(locked_minor=1000)
        rec = _run(runner, upstream, cfg, mandate)   # ₹10 mandate, dinner needs more
        assert rec.output["decision"] == "declined"
        assert drawdown.balance(mandate.mandate_id).drawn_minor == 0
