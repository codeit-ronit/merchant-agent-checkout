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

from typing import Any

from sentinel.fixtures.upstream import UpstreamError


class ModelledSettlementRail:
    RAIL_TOOLS = frozenset({"initiate_payment", "submit_otp"})

    def __init__(self) -> None:
        self._payments: dict[str, dict] = {}
        self._by_order: dict[str, list[str]] = {}
        self._counter = 0

    # ------------------------------------------------------------- handlers
    def initiate_payment(self, a: dict[str, Any], *, now_ms: int) -> dict:
        amount = a.get("amount")
        order_id = a.get("order_id")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise UpstreamError("initiate_payment requires a positive integer amount (minor units)")
        if not order_id:
            raise UpstreamError("initiate_payment requires an order_id")
        self._counter += 1
        pay_id = f"pay_MDL{self._counter:09d}"
        vpa = a.get("vpa")
        if vpa == "failure@razorpay":
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
            "error": error, "created_at_ms": now_ms,
            "modelled": True,
        }
        self._payments[pay_id] = record
        self._by_order.setdefault(order_id, []).append(pay_id)
        return dict(record)

    def submit_otp(self, a: dict[str, Any], *, now_ms: int) -> dict:
        pay_id = a.get("payment_id")
        otp = str(a.get("otp_string") or "")
        record = self._payments.get(pay_id)
        if record is None:
            raise UpstreamError(f"no payment '{pay_id}' on the modelled rail")
        if record["status"] != "created":
            raise UpstreamError(
                f"payment '{pay_id}' is {record['status']}; OTP applies only to a "
                f"payment awaiting authentication")
        if not otp.strip():
            raise UpstreamError("otp_string is required")
        record["status"] = "captured"
        record["otp_required"] = False
        record["authorized_at_ms"] = now_ms
        return dict(record)

    def fetch_order_payments(self, order_id: str) -> dict:
        items = [dict(self._payments[p]) for p in self._by_order.get(order_id, [])]
        return {"entity": "collection", "count": len(items), "items": items}

    def knows_order(self, order_id: str) -> bool:
        return order_id in self._by_order
