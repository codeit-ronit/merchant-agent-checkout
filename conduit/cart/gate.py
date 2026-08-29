"""The commit gate — the single moment where thinking becomes commitment.

Sequence (04 §4.1): load/verify → RE-PRICE → DIFF against the agent's stated
amount → availability → mandate → (policy: at the proxy boundary, where
cart_commit is classified COLLECTION — step 6 happens BEFORE this code runs)
→ idempotency → RESERVE → ONE create_order → confirm | release.

Two shapes of outcome, both structured (04 §4.4):
* success — order id (upstream-minted), final amount, itemised breakdown,
  mandate remaining after drawdown, catalog version;
* rejection — an enumerated reason, the true amount where relevant, an
  ITEMISED diff that says per line what the agent believed, what is true,
  and WHY it changed, and an actionable next step. The cart survives.

A rejection is a well-formed answer the agent must reason over, not an
upstream failure — so the gate RETURNS rejections; it raises only on
malformed input (which the strict argument layer above already prevents).

Fail closed: any failure to read catalog truth rejects the commit before
anything is reserved. Never commit against a cached price.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from conduit.cart.model import CartError, CartStatus
from conduit.cart.service import CartService
from conduit.mandate.ledger import DrawdownLedger, LedgerError


class GateReason(str, Enum):
    COMMITTED = "COMMITTED"
    COMMITTED_IDEMPOTENT_REPLAY = "COMMITTED_IDEMPOTENT_REPLAY"
    REJECT_REPRICE_DIVERGENCE = "REJECT_REPRICE_DIVERGENCE"
    REJECT_STATED_TOTAL_WRONG = "REJECT_STATED_TOTAL_WRONG"   # no price moved; the agent's arithmetic did
    REJECT_UNAVAILABLE = "REJECT_UNAVAILABLE"
    REJECT_REQUIRES_ITEM_MISSING = "REJECT_REQUIRES_ITEM_MISSING"
    REJECT_MANDATE_INSUFFICIENT = "REJECT_MANDATE_INSUFFICIENT"
    REJECT_CART_EXPIRED = "REJECT_CART_EXPIRED"
    REJECT_NO_SUCH_CART = "REJECT_NO_SUCH_CART"
    REJECT_ALREADY_COMMITTED = "REJECT_ALREADY_COMMITTED"
    REJECT_CURRENCY_MISMATCH = "REJECT_CURRENCY_MISMATCH"
    REJECT_EMPTY_CART = "REJECT_EMPTY_CART"
    REJECT_CATALOG_UNREACHABLE = "REJECT_CATALOG_UNREACHABLE"
    REJECT_UPSTREAM_FAILED = "REJECT_UPSTREAM_FAILED"


def notes_as_dict(value: Any) -> dict:
    """Razorpay serialises ``notes`` as an empty LIST when absent and an
    object when populated (ADR-030). Read both shapes; never assume one."""
    return dict(value) if isinstance(value, dict) else {}


def _reject(reason: GateReason, message: str, next_step: str, **extra: Any) -> dict:
    return {"committed": False, "reason_code": reason.value,
            "message": message, "next_step": next_step, **extra}


class CommitGate:
    def __init__(self, cart: CartService, ledger: DrawdownLedger, upstream: Any):
        self._cart = cart
        self._ledger = ledger
        self._upstream = upstream  # the INNER upstream: the gate's one write goes here
        # idempotency: (cart_id, final_amount_minor, mandate_id) -> prior success
        self._committed: dict[tuple[str, int, str], dict] = {}

    # ------------------------------------------------------------------
    def commit(self, cart_id: str, expected_amount_minor: int, currency: str,
               *, now_ms: int) -> dict:
        # ---- 1. load + verify state ----
        try:
            record = self._cart.record(cart_id)
        except CartError as exc:
            return _reject(GateReason.REJECT_NO_SUCH_CART, str(exc),
                           "Create a cart with cart_create first.")
        record = self._cart.expire_if_due(record, now_ms=now_ms)

        if isinstance(expected_amount_minor, bool) or not isinstance(expected_amount_minor, int):
            return _reject(GateReason.REJECT_STATED_TOTAL_WRONG,
                           "expected_amount_minor must be an integer number of minor units.",
                           "Read the total from cart_view and pass it unchanged.")
        if record.status is CartStatus.EXPIRED:
            return _reject(GateReason.REJECT_CART_EXPIRED,
                           f"cart '{cart_id}' expired; any reservation was released.",
                           "Create a new cart and rebuild it — the catalog is still available.")
        if record.status is CartStatus.COMMITTED:
            key = (cart_id, expected_amount_minor, record.mandate_id)
            prior = self._committed.get(key)
            if prior is not None:
                return {**prior, "reason_code": GateReason.COMMITTED_IDEMPOTENT_REPLAY.value,
                        "idempotent_replay": True}
            return _reject(GateReason.REJECT_ALREADY_COMMITTED,
                           f"cart '{cart_id}' is already committed as order "
                           f"{record.committed_order_id} for {record.committed_amount_minor} "
                           f"minor units — a different amount cannot recommit it.",
                           "Create a new cart for a new purchase.")
        if currency != record.currency:
            return _reject(GateReason.REJECT_CURRENCY_MISMATCH,
                           f"cart is priced in {record.currency}, not {currency}.",
                           f"Commit with currency='{record.currency}'.")
        if not record.lines:
            return _reject(GateReason.REJECT_EMPTY_CART, "the cart is empty.",
                           "Add items before committing.")

        believed = dict(record.last_priced)  # what the agent was last shown

        # ---- 2. RE-PRICE against live catalog truth (fail closed) ----
        try:
            priced = self._cart.price(record, now_ms=now_ms)
        except Exception as exc:  # catalog unreachable / any read failure → closed
            return _reject(GateReason.REJECT_CATALOG_UNREACHABLE,
                           f"could not re-price against live catalog truth ({exc}). "
                           f"Committing against a cached price is forbidden.",
                           "Retry when the catalog is reachable; the cart is unchanged.")

        # ---- 3. DIFF against the agent's stated amount ----
        if expected_amount_minor != priced.total_minor:
            line_diffs, any_price_moved = self._line_diffs(believed, priced)
            reason = (GateReason.REJECT_REPRICE_DIVERGENCE if any_price_moved
                      else GateReason.REJECT_STATED_TOTAL_WRONG)
            message = (
                "the cart re-priced differently at commit: "
                f"stated {expected_amount_minor}, true total {priced.total_minor}."
                if any_price_moved else
                "no price changed, but the stated amount does not match the "
                f"server total: stated {expected_amount_minor}, true total "
                f"{priced.total_minor}. The catalog computes money; agents do not.")
            return _reject(
                reason, message,
                f"Re-read the diff, then re-commit with expected_amount_minor="
                f"{priced.total_minor}, adjust the cart, or abandon. The cart is intact.",
                diff={
                    "expected_total_minor": expected_amount_minor,
                    "actual_total_minor": priced.total_minor,
                    "delta_minor": priced.total_minor - expected_amount_minor,
                    "believed_catalog_version": record.last_priced_catalog_version,
                    "actual_catalog_version": priced.catalog_version,
                    "lines": line_diffs,
                })

        # ---- 4. availability, per line, naming the failure ----
        for line in priced.lines:
            item = self._cart.live_item(line.item_id)  # live item
            if not item.availability.purchasable(line.quantity):
                return _reject(
                    GateReason.REJECT_UNAVAILABLE,
                    f"'{line.item_id}' is not purchasable at quantity {line.quantity} "
                    f"(stock: {item.availability.stock.value}"
                    f"{f', {item.availability.count} left' if item.availability.count is not None else ''}).",
                    "Remove or reduce that line — the system never substitutes on your behalf.",
                    unavailable_item_id=line.item_id)
            if item.constraints.requires_item_id and item.constraints.requires_item_id not in record.lines:
                return _reject(
                    GateReason.REJECT_REQUIRES_ITEM_MISSING,
                    f"'{line.item_id}' requires '{item.constraints.requires_item_id}' in the same order.",
                    f"Add '{item.constraints.requires_item_id}' or remove '{line.item_id}'.",
                    unavailable_item_id=line.item_id)

        # ---- 7. idempotency (before reserving: a replay must not re-hold) ----
        key = (cart_id, priced.total_minor, record.mandate_id)
        prior = self._committed.get(key)
        if prior is not None:
            return {**prior, "reason_code": GateReason.COMMITTED_IDEMPOTENT_REPLAY.value,
                    "idempotent_replay": True}

        # ---- 5+8. mandate check IS the atomic reserve (shortfall named) ----
        try:
            self._ledger.reserve(record.mandate_id, priced.total_minor,
                                 ref=cart_id, now_ms=now_ms)
        except LedgerError as exc:
            return _reject(GateReason.REJECT_MANDATE_INSUFFICIENT, str(exc),
                           "Reduce the cart below the remaining balance, or ask the "
                           "user to raise the mandate. The cart is intact.")

        # ---- 9. ONE create_order (reserve-before-forward) ----
        try:
            order = self._upstream.call_tool("create_order", {
                "amount": priced.total_minor,
                "currency": record.currency,
                "receipt": cart_id[:40],
                "notes": {
                    "conduit_cart_id": cart_id,
                    "conduit_mandate_id": record.mandate_id,
                    "conduit_catalog_version": str(priced.catalog_version),
                },
            })
            order_id = order.get("id") if isinstance(order, dict) else None
            if not order_id:
                raise RuntimeError(f"upstream returned no order id: {order!r}")
        except Exception as exc:
            self._ledger.release(record.mandate_id, ref=cart_id, now_ms=now_ms)
            return _reject(GateReason.REJECT_UPSTREAM_FAILED,
                           f"create_order failed ({exc}); the reservation was released.",
                           "The cart is intact — retry the commit; it is idempotent.")

        # ---- 10. confirm the drawdown; the cart becomes COMMITTED ----
        balance = self._ledger.confirm(record.mandate_id, ref=cart_id, now_ms=now_ms)
        record.status = CartStatus.COMMITTED
        record.committed_order_id = order_id
        record.committed_amount_minor = priced.total_minor
        self._cart.save(record)

        result = {
            "committed": True,
            "reason_code": GateReason.COMMITTED.value,
            "order_id": order_id,
            "amount_minor": priced.total_minor,
            "currency": record.currency,
            "breakdown": priced.to_public()["lines"],
            "subtotal_minor": priced.subtotal_minor,
            "tax_total_minor": priced.tax_total_minor,
            "mandate_id": record.mandate_id,
            "mandate_remaining_minor": balance.remaining_minor,
            "catalog_version": priced.catalog_version,
            "notes_echo": notes_as_dict(order.get("notes")),
            "idempotent_replay": False,
        }
        self._committed[key] = result
        return result

    # ------------------------------------------------------------------
    @staticmethod
    def _line_diffs(believed: dict[str, list[int]], priced) -> tuple[list[dict], bool]:
        """Per-line: what the agent believed, what is true, and why."""
        diffs: list[dict] = []
        any_moved = False
        for line in priced.lines:
            prior = believed.get(line.item_id)
            if prior is None:
                why = "line added since last view"
                any_moved = True
                believed_unit, believed_version = None, None
            else:
                believed_unit, believed_version = prior[0], prior[1]
                if believed_unit != line.unit_price_minor:
                    why = (f"price changed v{believed_version}→v{line.price_version}: "
                           f"{believed_unit} → {line.unit_price_minor} minor units")
                    any_moved = True
                else:
                    why = "unchanged"
            diffs.append({
                "item_id": line.item_id,
                "quantity": line.quantity,
                "believed_unit_minor": believed_unit,
                "actual_unit_minor": line.unit_price_minor,
                "believed_price_version": believed_version,
                "actual_price_version": line.price_version,
                "line_delta_minor": (line.unit_price_minor - believed_unit) * line.quantity
                                    if believed_unit is not None else None,
                "why": why,
            })
        return diffs, any_moved
