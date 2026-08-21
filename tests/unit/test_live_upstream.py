"""LiveUpstream key guard (tier 1, no Docker): test mode only, ever.

The full live integration is exercised by `make check-schemas-live` against the
real razorpay/mcp image (Docker + rzp_test_ keys); it is not run in unit CI.
These tests prove the load-bearing guard: a live key is refused before any
connection is attempted."""

from __future__ import annotations

import pytest

from sentinel.proxy.live_upstream import LiveKeyError, require_test_mode

pytestmark = pytest.mark.tier1


def test_accepts_test_mode_key():
    assert require_test_mode("rzp_test_abc123") == "rzp_test_abc123"


@pytest.mark.critical
def test_refuses_live_key():
    with pytest.raises(LiveKeyError):
        require_test_mode("rzp_live_abc123")


def test_refuses_non_razorpay_key():
    with pytest.raises(LiveKeyError):
        require_test_mode("sk-something-else")


def test_refuses_missing_key(monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    with pytest.raises(LiveKeyError):
        require_test_mode(None)


def test_constructing_live_upstream_with_live_key_raises():
    from sentinel.proxy.live_upstream import LiveUpstream
    with pytest.raises(LiveKeyError):
        LiveUpstream(command="docker", args=[], env={"RAZORPAY_KEY_ID": "rzp_live_x"})
