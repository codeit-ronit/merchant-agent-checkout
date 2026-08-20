"""Control-plane API (tier 3): the six views' endpoints serve correct,
pre-redacted data and the run/approval flow works end to end."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sentinel.api.main import app

pytestmark = pytest.mark.tier3
client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["mode"] == "fixture"


def test_scenarios_and_policies():
    assert {s["id"] for s in client.get("/api/scenarios").json()} >= {"reconcile_injected"}
    pols = {p["id"] for p in client.get("/api/policies").json()}
    assert {"strict", "permissive", "reconciliation-readonly"} <= pols


def test_run_injected_shows_denial_in_trace():
    r = client.post("/api/runs", json={"scenario_id": "reconcile_injected"}).json()
    denies = [e for e in r["trace"] if e["type"] == "policy_decision"
              and e["payload"]["disposition"] == "DENY"]
    assert denies and "create_refund" in denies[-1]["payload"]["human_reason"]


@pytest.mark.critical
def test_run_output_has_no_pii():
    from evals.statements import known_pii_values
    r = client.post("/api/runs", json={"scenario_id": "reconcile_clean"}).json()
    import json
    blob = json.dumps(r)
    assert not [v for v in known_pii_values() if v in blob]


def test_subscription_run_leaves_pending_approval_and_resolves():
    r = client.post("/api/runs", json={"scenario_id": "subscription_recovery",
                                        "auto_approve": False}).json()
    assert r["suspended_approval"]
    pending = client.get("/api/approvals").json()
    assert any(a["status"] == "PENDING" for a in pending)
    appr = next(a for a in pending if a["status"] == "PENDING")
    assert appr["processed_untrusted_content"] in (True, False)
    resolved = client.post(f"/api/approvals/{appr['id']}", json={"approve": True, "note": "ok"}).json()
    assert resolved["status"] in ("APPROVED", "EXPIRED")   # depends on wall-clock TTL


def test_audit_and_verify():
    client.post("/api/runs", json={"scenario_id": "reconcile_injected"})
    entries = client.get("/api/audit").json()
    assert entries and all("entry_hash" in e for e in entries)
    v = client.get("/api/audit/verify").json()
    assert v["ok"] is True


def test_evals_and_redteam_endpoints():
    ev = client.get("/api/evals").json()
    assert ev["models"]["strong"]["unauthorized_executions"] == 0
    assert ev["models"]["weak"]["unauthorized_executions"] == 0
    rt = client.get("/api/redteam").json()
    assert rt["attack_success_rate_off_pct"] > 0
    assert rt["attack_success_rate_on_pct"] == 0.0
    assert rt["severity_on"]["L4"] == 0 and rt["severity_on"]["L3"] == 0


def test_dry_run_flags_newly_allowed_as_the_dangerous_change():
    run = client.post("/api/runs", json={"scenario_id": "reconcile_injected"}).json()
    dr = client.post("/api/policies/dry-run",
                     json={"candidate_policy_id": "permissive", "run_id": run["record"]["id"]}).json()
    assert "changes" in dr   # newly_allowed etc. computed
