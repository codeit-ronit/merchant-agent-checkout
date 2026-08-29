"""The MODELLED settlement rail (ADR-034).

The S2S payment API family (`initiate_payment` → `submit_otp`) is not enabled
on this test account — verified empirically, 404 from the wrapped endpoint.
So settlement is a labelled MODEL over real order state, faithful to the
documented shapes: the same tool names, the same collection envelopes, the
documented test-VPA semantics (`failure@razorpay` fails, `success@razorpay`
succeeds), and an OTP step for saved-instrument payments.

Every entity this rail mints carries ``"modelled": true`` — the line between
real and modelled is surfaced in the data itself, not only in the README.

If S2S is ever enabled, this class's seam is the same Upstream interface:
delete the interception and the real tools drop in (ADR-034 revisit-if).

Deterministic: callers pass ``now_ms``; ids are counters, not randomness.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from sentinel.fixtures.upstream import UpstreamError

# The one deliberately-wrong OTP for the modelled rail's failure path.
WRONG_OTP = "000000"


class ModelledSettlementRail:
    RAIL_TOOLS = frozenset({"initiate_payment", "submit_otp"})

    def __init__(self) -> None:
        self._payments: dict[str, dict] = {}
        self._by_order: dict[str, list[str]] = {}
        self._counter = 0
        self._lock = threading.Lock()   # per-rail serialisation: one capture per order
        self._timeout_armed: str | None = None  # None | "captured" | "failed"
        # observers: called with the payment record on every terminal status —
        # the settlement coordinator subscribes (reversal on decline, ADR-026)
        self._observers: list[Callable[[dict], None]] = []

    # --------------------------------------------------------- test/demo API
    def arm_timeout(self, hidden_outcome: str = "captured") -> None:
        """Arm ONE ambiguous timeout: the next initiate_payment WRITES the
        payment with ``hidden_outcome``, then the call raises — so the caller
        genuinely cannot know. Ground truth is discoverable only the correct
        way: fetch_order_payments. Modelled-rail injection, labelled as such."""
        if hidden_outcome not in ("captured", "failed"):
            raise ValueError("hidden_outcome must be 'captured' or 'failed'")
        self._timeout_armed = hidden_outcome

    def subscribe(self, observer: Callable[[dict], None]) -> None:
        self._observers.append(observer)

    def _notify(self, record: dict) -> None:
        if record["status"] in ("captured", "failed"):
            for observer in self._observers:
                observer(dict(record))

    def _captured_for(self, order_id: str) -> dict | None:
        for pid in self._by_order.get(order_id, []):
            if self._payments[pid]["status"] == "captured":
                return self._payments[pid]
        return None

    # ------------------------------------------------------------- handlers
    def initiate_payment(self, a: dict[str, Any], *, now_ms: int) -> dict:
        amount = a.get("amount")
        order_id = a.get("order_id")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise UpstreamError("initiate_payment requires a positive integer amount (minor units)")
        if not order_id:
            raise UpstreamError("initiate_payment requires an order_id")
        with self._lock:
            # Razorpay reality: an order with a captured payment takes no
            # further payments. The paid-order guard is the rail-side half of
            # "no double charge, ever".
            already = self._captured_for(order_id)
            if already is not None:
                raise UpstreamError(
                    f"order '{order_id}' is already paid by {already['id']}; a paid "
                    f"order accepts no further payments. Reconcile with "
                    f"fetch_order_payments instead of retrying.")
            self._counter += 1
            pay_id = f"pay_MDL{self._counter:09d}"
            vpa = a.get("vpa")
            timeout = self._timeout_armed
            self._timeout_armed = None
            if timeout is not None:
                status, error = timeout, (None if timeout == "captured" else {
                    "code": "BAD_REQUEST_ERROR",
                    "description": "Payment failed (hidden behind a timeout)",
                    "source": "customer", "step": "payment_authorization"})
            elif vpa == "failure@razorpay":
                # the documented deliberate-failure VPA, modelled faithfully
                status, error = "failed", {
                    "code": "BAD_REQUEST_ERROR",
                    "description": "Payment failed (test VPA failure@razorpay)",
                    "source": "customer", "step": "payment_authorization",
                }
            elif vpa:
                status, error = "captured", None      # UPI collect success
            else:
                status, error = "created", None       # saved instrument -> OTP step
            record = {
                "id": pay_id, "entity": "payment", "order_id": order_id,
                "amount": amount, "currency": a.get("currency", "INR"),
                "status": status, "method": "upi" if vpa else "card",
                "otp_required": status == "created",
                "otp_attempts": 0,
                "error": error, "created_at_ms": now_ms,
                "modelled": True,
            }
            self._payments[pay_id] = record
            self._by_order.setdefault(order_id, []).append(pay_id)
        self._notify(record)
        if timeout is not None:
            # The state above IS written — the ambiguity is real for the caller.
            raise UpstreamError(
                "the payment rail timed out; the outcome is UNKNOWN. Do not "
                "retry blindly — reconcile with fetch_order_payments first.")
        return dict(record)

    def submit_otp(self, a: dict[str, Any], *, now_ms: int) -> dict:
        pay_id = a.get("payment_id")
        otp = str(a.get("otp_string") or "")
        with self._lock:
            record = self._payments.get(pay_id)
            if record is None:
                raise UpstreamError(f"no payment '{pay_id}' on the modelled rail")
            if record["status"] != "created":
                raise UpstreamError(
                    f"payment '{pay_id}' is {record['status']}; OTP applies only to a "
                    f"payment awaiting authentication")
            if not otp.strip():
                raise UpstreamError("otp_string is required")
            if otp == WRONG_OTP:
                record["otp_attempts"] += 1
                if record["otp_attempts"] >= 3:
                    record["status"] = "failed"
                    record["otp_required"] = False
                    record["error"] = {"code": "BAD_REQUEST_ERROR",
                                       "description": "OTP attempts exhausted",
                                       "source": "customer", "step": "payment_authentication"}
                    result = dict(record)
                    self._notify(record)
                    return result
                raise UpstreamError(
                    f"incorrect OTP for '{pay_id}' "
                    f"(attempt {record['otp_attempts']} of 3). The payment is still "
                    f"awaiting authentication; the order is held — resubmit or abandon.")
            record["status"] = "captured"
            record["otp_required"] = False
            record["authorized_at_ms"] = now_ms
            result = dict(record)
        self._notify(record)
        return result

    def fetch_order_payments(self, order_id: str) -> dict:
        items = [dict(self._payments[p]) for p in self._by_order.get(order_id, [])]
        return {"entity": "collection", "count": len(items), "items": items}

    def knows_order(self, order_id: str) -> bool:
        return order_id in self._by_order
