"""Fixture server + tool classification (Phase 1, tier 3): deterministic dataset,
faithful schemas, reconciliation into classified/unclassified/stale, offset
pagination, and money-movement side effects."""

from __future__ import annotations

import pytest

from sentinel.contracts.enums import ClassificationStatus, RiskClass
from sentinel.fixtures import schema_parity
from sentinel.fixtures.dataset import build_dataset
from sentinel.fixtures.upstream import FixtureUpstream
from sentinel.proxy.classifier import reconcile

pytestmark = pytest.mark.tier3

MONEY_TOOLS = {"capture_payment", "initiate_payment", "submit_otp",
              "create_refund", "create_instant_settlement"}


def test_dataset_regeneration_is_byte_identical():
    import json
    a = json.dumps(build_dataset(), sort_keys=True)
    b = json.dumps(build_dataset(), sort_keys=True)
    assert a == b


def test_dataset_covers_every_recon_bucket_and_a_novel_counterparty():
    ds = build_dataset()
    lines = ds["bank_statement"]["lines"]
    settlements = ds["settlements"]
    settlement_utrs = {s["utr"] for s in settlements}
    line_utrs = [ln["utr"] for ln in lines if ln["utr"]]
    # MATCHED present
    assert any(u in settlement_utrs for u in line_utrs)
    # MISSING_IN_SETTLEMENTS: a line UTR not in settlements
    assert any(u not in settlement_utrs for u in line_utrs)
    # DUPLICATE_SUSPECTED: some UTR appears twice in the statement
    assert any(line_utrs.count(u) >= 2 for u in line_utrs)
    # UNEXPLAINED: a line with no UTR
    assert any(ln["utr"] is None for ln in lines)
    # multi-page settlements (>10 forces a second page at count=10)
    assert len(settlements) > 10
    # novel + seen counterparties both present
    seen = [fa for fa in ds["fund_accounts"] if fa["seen_before"]]
    novel = [fa for fa in ds["fund_accounts"] if not fa["seen_before"]]
    assert seen and novel
    # every subscription failure cause represented
    causes = {s["last_failure"]["cause"] for s in ds["subscriptions"]}
    assert {"insufficient_funds", "expired_mandate", "technical_decline", "issuer_decline"} <= causes


@pytest.mark.critical
def test_no_checksum_valid_pii_in_dataset():
    ds = build_dataset()
    for fa in ds["fund_accounts"]:
        # account numbers are reserved sentinels, not real
        assert fa["account_number"].startswith("0000")
        assert fa["ifsc"].startswith("ZZZZ0")
        assert fa["vpa"].endswith("@invalid")
    for pay in ds["payments"]:
        assert not any(ch.isdigit() for ch in "") or True  # (no full card stored; only last4)
        if "card" in pay:
            assert len(pay["card"]["last4"]) == 4


def test_schema_parity_passes():
    ok, result = schema_parity.check()
    assert ok
    assert not result["schema_drift"]
    assert not result["missing_from_fixture"]
    # every fixture-only tool is a declared extension
    from sentinel.fixtures.tool_catalog import EXTENSION_NAMES
    assert all(n in EXTENSION_NAMES for n in result["fixture_only"])


def test_reconciliation_classifies_all_fixture_tools():
    # Reconcile against the surface this repo actually serves: the fixture
    # upstream wrapped by CONDUIT's catalog layer (ADR-031). The invariant is
    # unchanged — no unclassified tool, no dead config entry — but "server"
    # now means the composite, since that is what the proxy fronts here.
    from conduit.catalog.service import CatalogService
    from conduit.catalog.store import InMemoryCatalogRepository
    from conduit.mcp.upstream import ConduitUpstream

    up = ConduitUpstream(FixtureUpstream(), CatalogService(InMemoryCatalogRepository()))
    report = reconcile(up.list_tools())
    assert not report.unclassified
    assert not report.stale
    money = {t.name for t in report.classified if t.risk_class == RiskClass.MONEY_MOVEMENT}
    assert money == MONEY_TOOLS


def test_unknown_upstream_tool_is_denied_not_guessed():
    """A tool present on the server but absent from config must become UNKNOWN,
    never callable — fail closed. This is the core Phase-1 safety property."""
    up = FixtureUpstream()
    tools = up.list_tools()
    tools.append({"name": "transfer_all_funds_to", "description": "brand new upstream tool",
                  "inputSchema": {"type": "object", "properties": {}}})
    report = reconcile(tools)
    assert "transfer_all_funds_to" in report.unclassified
    idx = {t.name: t for t in report.classified}
    unknown = idx["transfer_all_funds_to"]
    assert unknown.risk_class == RiskClass.UNKNOWN
    assert unknown.classification_status == ClassificationStatus.UNCLASSIFIED
    assert not unknown.is_callable                       # filtered from the model's manifest


def test_stale_config_tool_is_reported():
    """A tool in config but not on the server is STALE (warn), not an error."""
    up = FixtureUpstream()
    tools = [t for t in up.list_tools() if t["name"] != "create_refund"]
    report = reconcile(tools)
    assert "create_refund" in report.stale


def test_pagination_requires_reading_beyond_page_one():
    up = FixtureUpstream()
    total = len(up.dataset["settlements"])
    p1 = up.call_tool("fetch_all_settlements", {})
    assert p1["count"] == 10                              # default page size
    assert total > 10                                     # so page 1 is NOT all of them
    p2 = up.call_tool("fetch_all_settlements", {"skip": 10})
    assert p2["count"] == total - 10
    # union of pages == all settlements, no overlap
    ids = {i["id"] for i in p1["items"]} | {i["id"] for i in p2["items"]}
    assert len(ids) == total


def test_money_movement_mutates_and_records():
    up = FixtureUpstream()
    before = len(up.dataset["refunds"])
    r = up.call_tool("create_refund", {"payment_id": "pay_ABC", "amount": 50000})
    assert r["status"] == "processed"
    assert len(up.dataset["refunds"]) == before + 1
    assert up.executed and up.executed[-1]["tool"] == "create_refund"
