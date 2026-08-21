"""THE HIGHEST-VALUE TEST IN THE REPOSITORY (docs/spec/05 A3, spec 12).

Seed the full pipeline with fixtures that carry known synthetic PII, run reads
that return that PII, then grep EVERY output surface — the redacted results, all
trace-event payloads, and all audit entries — for those exact values. None may
appear anywhere outside the token store.

If this test ever fails, PII has leaked to a surface a human or an attacker can
read. It runs on every commit.
"""

from __future__ import annotations

import json

import pytest

from sentinel.audit.ledger import AuditLedger, InMemoryLedgerRepository
from sentinel.contracts.decision import InjectedEnv
from sentinel.fixtures.dataset import build_dataset
from sentinel.fixtures.upstream import FixtureUpstream
from sentinel.policy_loader import load_policy_set
from sentinel.proxy.classifier import descriptor_index, reconcile
from sentinel.proxy.idempotency import IdempotencyGuard
from sentinel.proxy.interceptor import Interceptor, Signals
from sentinel.redaction.engine import RedactionSession
from sentinel.redaction.quarantine import QuarantineWrapper

pytestmark = [pytest.mark.tier3, pytest.mark.critical]


def _known_pii_values() -> list[str]:
    ds = build_dataset()
    values: list[str] = []
    for pay in ds["payments"]:
        values += [pay["email"], pay["contact"], pay["name"]]
        if "vpa" in pay:
            values.append(pay["vpa"])
    for fa in ds["fund_accounts"]:
        values += [fa["account_number"], fa["ifsc"], fa["vpa"], fa["account_holder"]]
    for pay in ds["payments"]:
        if "card" in pay:
            values.append(pay["card"]["last4"])
    # keep only distinctive, non-trivial strings (avoid 4-digit false positives
    # that could legitimately appear as amounts)
    return [v for v in set(values) if v and len(v) >= 5]


def test_no_pii_on_any_output_surface():
    up = FixtureUpstream()
    idx = descriptor_index(reconcile(up.list_tools()))
    ledger = AuditLedger(InMemoryLedgerRepository())
    trace_events: list[tuple[str, dict]] = []
    interc = Interceptor(
        upstream=up, policy_set=load_policy_set("strict"), ledger=ledger,
        session=RedactionSession("run_pii", salt=b"pii-invariant16!"),
        quarantine=QuarantineWrapper(nonce="PIINONCE"),
        idempotency=IdempotencyGuard(),
        run_meta=dict(run_id="run_pii", agent_id="a", agent_version="1", operator_id="op",
                      policy_set_id="strict", git_commit="test"),
        trace=lambda t, p: trace_events.append((t, p)),
    )
    env = InjectedEnv(now_epoch_ms=1)

    # reads that return PII across pages
    results = []
    for skip in (0, 10):
        results.append(interc.handle_call(idx["fetch_all_payments"], {"count": 10, "skip": skip},
                                          env, Signals(), f"s{skip}", f"c{skip}"))
    # a dispute carries an untrusted customer message + payment PII
    disp_id = build_dataset()["disputes"][0]["id"]
    results.append(interc.handle_call(idx["fetch_dispute"], {"dispute_id": disp_id}, env, Signals(), "sd", "cd"))
    # saved tokens by contact (real arg name is `contact`) — returns VPAs
    results.append(interc.handle_call(idx["fetch_tokens"], {"contact": "9999900000"}, env, Signals(), "st", "ct"))

    # --- collect EVERY output surface ---
    surfaces: list[str] = []
    for out in results:
        if out.result is not None:
            surfaces.append(json.dumps(out.result, ensure_ascii=False))
        surfaces.append(out.decision.model_dump_json())
    for t, payload in trace_events:
        surfaces.append(json.dumps(payload, ensure_ascii=False))
    for entry in ledger.entries():
        surfaces.append(entry.model_dump_json())        # audit entries are pre-redacted
    blob = "\n".join(surfaces)

    leaked = [v for v in _known_pii_values() if v in blob]
    assert not leaked, f"PII leaked to an output surface: {leaked[:5]}"


@pytest.mark.critical
def test_committed_cassettes_are_pii_clean():
    """Belt-and-braces (docs/spec/02 §4.3): the COMMITTED cassettes must contain
    no known PII value. Only guardrails-ON eval cassettes are committed; the
    guardrails-off red-team recordings (which capture the exfiltration
    counterfactual) are intentionally not committed."""
    import glob

    from evals.statements import known_pii_values
    committed = glob.glob("cassettes/evals/*.json")
    assert committed, "expected committed eval cassettes"
    pii = known_pii_values()
    leaks = [(f, v) for f in committed for v in pii if v in open(f, encoding="utf-8").read()]
    assert not leaks, f"PII in a committed cassette: {leaks[:3]}"


def test_reconciliation_over_all_pages_never_leaks_utr_is_visible():
    """UTRs are transaction references, NOT PII — reconciliation must be able to
    match on them, so they are deliberately left visible."""
    up = FixtureUpstream()
    idx = descriptor_index(reconcile(up.list_tools()))
    interc = Interceptor(
        upstream=up, policy_set=load_policy_set("reconciliation-readonly"),
        ledger=AuditLedger(InMemoryLedgerRepository()),
        session=RedactionSession("run_r", salt=b"recon-16-bytes!!"),
        quarantine=QuarantineWrapper(nonce="RN"),
        idempotency=IdempotencyGuard(),
        run_meta=dict(run_id="run_r", agent_id="reconciliation", agent_version="1", operator_id="op",
                      policy_set_id="reconciliation-readonly", git_commit="t"),
    )
    env = InjectedEnv(now_epoch_ms=1)
    out = interc.handle_call(idx["fetch_all_settlements"], {"count": 100}, env, Signals(), "s", "c")
    utr = build_dataset()["settlements"][0]["utr"]
    assert utr in json.dumps(out.result)      # UTR visible for matching
