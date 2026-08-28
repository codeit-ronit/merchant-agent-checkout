"""Catalog tools crossing the REAL SENTINEL boundary.

These tests construct the actual Interceptor — classifier, policy, redaction,
quarantine, audit — over a ConduitUpstream, proving the Phase 1 exit criteria
at the enforcement boundary rather than in the service:

* catalog READ tools are classified and allowed;
* merchant free text comes back quarantined (per-run nonce), and the
  quarantine is visible in the interception result;
* an agent-supplied price is REJECTED, never silently ignored;
* an unclassified conduit tool would be denied (fail closed) — proven by
  reconciling against a config with the entry removed.
"""

from __future__ import annotations

import pytest

from conduit.catalog.seed import seed_catalog
from conduit.catalog.service import CatalogService
from conduit.catalog.store import InMemoryCatalogRepository
from conduit.mcp.tools import CATALOG_TOOL_NAMES
from conduit.mcp.upstream import ConduitUpstream
from sentinel.audit.ledger import AuditLedger, InMemoryLedgerRepository
from sentinel.contracts.decision import InjectedEnv
from sentinel.contracts.enums import Disposition, RiskClass
from sentinel.fixtures.upstream import FixtureUpstream
from sentinel.policy_loader import load_policy_set
from sentinel.proxy.classifier import descriptor_index, reconcile
from sentinel.proxy.idempotency import IdempotencyGuard
from sentinel.proxy.interceptor import Interceptor, Signals
from sentinel.redaction.engine import RedactionSession
from sentinel.redaction.quarantine import QuarantineWrapper

pytestmark = pytest.mark.tier1

NONCE = "test-nonce-cat"


@pytest.fixture()
def catalog_upstream():
    svc = CatalogService(InMemoryCatalogRepository())
    seed_catalog(svc)
    return ConduitUpstream(FixtureUpstream(), svc)


@pytest.fixture()
def boundary(catalog_upstream):
    ledger = AuditLedger(InMemoryLedgerRepository())
    interceptor = Interceptor(
        upstream=catalog_upstream,
        policy_set=load_policy_set("reconciliation-readonly"),
        ledger=ledger,
        session=RedactionSession("cat-run", salt=b"y" * 16),
        quarantine=QuarantineWrapper(nonce=NONCE),
        idempotency=IdempotencyGuard(),
        run_meta=dict(run_id="cat-run", agent_id="reconciliation", agent_version="1",
                      operator_id="op", policy_set_id="reconciliation-readonly",
                      git_commit="test"),
    )
    descriptors = descriptor_index(reconcile(catalog_upstream.list_tools()))
    return interceptor, descriptors, ledger


def _call(boundary, tool, args):
    interceptor, descriptors, _ = boundary
    return interceptor.handle_call(descriptors[tool], args,
                                   InjectedEnv(now_epoch_ms=1), Signals(), "s", "c")


class TestClassification:
    def test_all_catalog_tools_reconcile_as_read(self, catalog_upstream):
        report = reconcile(catalog_upstream.list_tools())
        by_name = {d.name: d for d in report.classified}
        for name in CATALOG_TOOL_NAMES:
            assert by_name[name].risk_class is RiskClass.READ
            assert name not in report.unclassified

    def test_unclassified_catalog_tool_is_denied_fail_closed(self, catalog_upstream, tmp_path, monkeypatch):
        """Remove catalog_feed from config → UNKNOWN → filtered from the
        manifest and denied. The no-hardcoded-tool-lists rule, held."""
        import shutil

        import yaml
        cfg_dir = tmp_path / "config"
        shutil.copytree("config", cfg_dir)
        data = yaml.safe_load((cfg_dir / "tool_classes.yaml").read_text())
        del data["tools"]["catalog_feed"]
        (cfg_dir / "tool_classes.yaml").write_text(yaml.safe_dump(data))
        monkeypatch.setenv("SENTINEL_CONFIG_DIR", str(cfg_dir))
        from sentinel.common.config import load_yaml_cached
        load_yaml_cached.cache_clear()
        try:
            report = reconcile(catalog_upstream.list_tools())
            assert "catalog_feed" in report.unclassified
            assert "catalog_feed" not in {d.name for d in report.callable_manifest}
        finally:
            load_yaml_cached.cache_clear()


class TestQuarantine:
    def test_search_result_quarantines_merchant_text(self, boundary):
        out = _call(boundary, "catalog_search", {"attributes": ["veg"]})
        assert out.disposition is Disposition.ALLOW and out.executed
        assert out.quarantined_fields  # untrusted fields were wrapped
        first = out.result["items"][0]
        assert NONCE in first["name"]            # merchant text is inside the wrapper
        assert "UNTRUSTED" in first["name"]
        assert isinstance(first["price_minor"], int)   # structured stays machine-readable
        assert NONCE not in str(first["price_minor"])

    def test_get_item_quarantines_description(self, boundary):
        out = _call(boundary, "catalog_get_item", {"item_id": "itm_paneer-tikka"})
        assert out.disposition is Disposition.ALLOW
        assert NONCE in out.result["description"]
        assert out.result["price_minor"] == 20000

    def test_quarantine_is_in_the_audit_trail(self, boundary):
        _call(boundary, "catalog_search", {})
        _, _, ledger = boundary
        entries = ledger.entries()
        assert entries and entries[-1].tool_name == "catalog_search"


class TestPriceRejection:
    def test_agent_supplied_price_is_rejected_not_ignored(self, boundary):
        out = _call(boundary, "catalog_search", {"price": 1})
        assert not out.executed
        assert out.disposition is not Disposition.ALLOW or out.error is not None

    def test_rejection_message_names_the_rule(self, catalog_upstream):
        from sentinel.fixtures.upstream import UpstreamError
        with pytest.raises(UpstreamError, match="only price source"):
            catalog_upstream.call_tool("catalog_search", {"unit_price_minor": 999})
        with pytest.raises(UpstreamError, match="only price source"):
            catalog_upstream.call_tool("catalog_get_item",
                                       {"item_id": "itm_paneer-tikka", "amount": 100})

    def test_unknown_argument_rejected_with_accepted_list(self, catalog_upstream):
        from sentinel.fixtures.upstream import UpstreamError
        with pytest.raises(UpstreamError, match="unknown argument"):
            catalog_upstream.call_tool("catalog_feed", {"verbose": True})


class TestUpstreamBehaviour:
    def test_delegates_non_catalog_tools_to_inner(self, catalog_upstream):
        result = catalog_upstream.call_tool("fetch_all_settlements", {})
        assert result["entity"] == "collection"

    def test_feed_paginates_like_razorpay_collections(self, catalog_upstream):
        page1 = catalog_upstream.call_tool("catalog_feed", {"count": 4})
        page2 = catalog_upstream.call_tool("catalog_feed", {"count": 4, "skip": 4})
        assert page1["count"] == 4 and page2["count"] == 4
        assert "has_more" not in page1  # faithful: paginate by skip until short page
        ids1 = {i["item_id"] for i in page1["items"]}
        ids2 = {i["item_id"] for i in page2["items"]}
        assert not ids1 & ids2

    def test_phantom_item_fails_closed_through_boundary(self, boundary):
        out = _call(boundary, "catalog_get_item", {"item_id": "itm_ghost"})
        assert not out.executed or out.error is not None

    def test_availability_check_carries_versions(self, catalog_upstream):
        out = catalog_upstream.call_tool("catalog_check_availability",
                                         {"item_id": "itm_veg-biryani", "quantity": 5})
        assert out["purchasable"] is False and out["stock"] == "LIMITED"
        assert out["price_version"] == 1 and out["catalog_version"] > 0
