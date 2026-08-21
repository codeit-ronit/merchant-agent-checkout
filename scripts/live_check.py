"""Verify SENTINEL against the REAL razorpay/mcp server (test mode only).

Two checks, both against the genuine published image over MCP stdio:
1. SCHEMA PARITY — the real `tools/list` matches the committed reference
   manifest + the fixture (the check that was circular until we captured live).
2. LIVE ENFORCEMENT — a money-movement call (`create_refund`) is DENIED by the
   proxy's policy BEFORE it is ever forwarded to the real server. This needs no
   valid Razorpay credentials: the denial short-circuits before any upstream
   call, so it demonstrates enforcement against the real tool surface safely.

Requires Docker + the `razorpay/mcp:latest` image. A dummy `rzp_test_` key is
enough because `tools/list` needs no real auth and the money call never forwards.

    make check-schemas-live      (or: python -m scripts.live_check)
"""

from __future__ import annotations

import os
import sys

DOCKER_ARGS = ["run", "-i", "--rm", "-e", "RAZORPAY_KEY_ID", "-e", "RAZORPAY_KEY_SECRET",
               "razorpay/mcp:latest"]


def _connect():
    from sentinel.proxy.live_upstream import LiveUpstream
    os.environ.setdefault("RAZORPAY_KEY_ID", "rzp_test_LIVECHECKDUMMY")
    os.environ.setdefault("RAZORPAY_KEY_SECRET", "dummy_not_real")
    return LiveUpstream(command="docker", args=DOCKER_ARGS,
                        env={"RAZORPAY_KEY_ID": os.environ["RAZORPAY_KEY_ID"],
                             "RAZORPAY_KEY_SECRET": os.environ["RAZORPAY_KEY_SECRET"]})


def check_parity(real_tools: list[dict]) -> int:
    from sentinel.fixtures.tool_catalog import EXTENSION_NAMES, UPSTREAM_TOOLS
    real = {t["name"] for t in real_tools}
    fixture_upstream = {t["name"] for t in UPSTREAM_TOOLS}
    missing = sorted(real - fixture_upstream)          # real has, fixture lacks
    extra = sorted(fixture_upstream - real)            # fixture has, real lacks
    print(f"\n1) SCHEMA PARITY vs the real razorpay/mcp ({len(real)} tools)")
    print(f"   fixture upstream models {len(fixture_upstream)} tools")
    if not missing and not extra:
        print("   ✓ MATCH — the fixture mirrors the real tool surface exactly.")
    else:
        print(f"   ✕ DRIFT — missing_from_fixture={missing}  extra_in_fixture={extra}")
    print(f"   (fixture also adds labelled extensions, reported fixture-only: {sorted(EXTENSION_NAMES)})")
    return 0 if not missing and not extra else 1


def check_enforcement(live) -> int:
    """Attempt a refund through the proxy against the REAL server; expect a DENY
    that never forwards upstream."""
    from sentinel.audit.ledger import AuditLedger, InMemoryLedgerRepository
    from sentinel.contracts.decision import InjectedEnv
    from sentinel.contracts.enums import Disposition
    from sentinel.policy_loader import load_policy_set
    from sentinel.proxy.classifier import descriptor_index, reconcile
    from sentinel.proxy.idempotency import IdempotencyGuard
    from sentinel.proxy.interceptor import Interceptor, Signals
    from sentinel.redaction.engine import RedactionSession
    from sentinel.redaction.quarantine import QuarantineWrapper

    descriptors = descriptor_index(reconcile(live.list_tools()))
    interc = Interceptor(
        upstream=live, policy_set=load_policy_set("reconciliation-readonly"),
        ledger=AuditLedger(InMemoryLedgerRepository()),
        session=RedactionSession("live", salt=b"x" * 16),
        quarantine=QuarantineWrapper(nonce="live"), idempotency=IdempotencyGuard(),
        run_meta=dict(run_id="live", agent_id="reconciliation", agent_version="1",
                      operator_id="op", policy_set_id="reconciliation-readonly", git_commit="live"))
    out = interc.handle_call(descriptors["create_refund"],
                             {"payment_id": "pay_X", "amount": 4500000},
                             InjectedEnv(now_epoch_ms=1), Signals(), "s", "c")
    print("\n2) LIVE ENFORCEMENT against the real razorpay/mcp")
    print(f"   attempted create_refund (MONEY_MOVEMENT) -> {out.disposition.value} "
          f"[{out.decision.reason_code.value}]")
    print(f"   reason: {out.decision.human_reason}")
    print(f"   executed against the real server: {out.executed}  (denied before forwarding)")
    return 0 if out.disposition == Disposition.DENY and not out.executed else 1


def main() -> int:
    try:
        live = _connect()
    except Exception as exc:
        print(f"could not start razorpay/mcp: {exc}\n"
              f"need Docker + `docker pull razorpay/mcp:latest`.")
        return 2
    try:
        real_tools = live.list_tools()
        rc = check_parity(real_tools) | check_enforcement(live)
    finally:
        live.close()
    print("\n" + ("LIVE CHECK PASSED — verified against the real razorpay/mcp." if rc == 0
                  else "LIVE CHECK FAILED."))
    return rc


if __name__ == "__main__":
    sys.exit(main())
