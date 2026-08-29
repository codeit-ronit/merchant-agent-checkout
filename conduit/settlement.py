"""SettlementCoordinator — the drawdown's reaction to payment outcomes.

ADR-026 decided the semantics; Phase 4 implements them:

* **Decline → REVERSE, visibly.** No money moved, so holding the user's
  locked balance against a failed payment is hostile. The reversal is a new
  ledger entry, never a deletion — history shows confirm-then-reverse, and
  the balance stays reconstructible.
* **Retry-success after a reversal → re-draw.** A captured payment for an
  order whose purchase currently holds none of the mandate re-establishes the
  drawdown (reserve + confirm under the ledger's lock). The retry's amount
  was policy-gated at the boundary BEFORE the rail ran (mandate_gate checks
  amount against the ledger-derived remaining), so an insufficient re-draw
  here is an invariant breach, not a user flow — it raises, loudly.

Subscribed to the modelled rail's terminal payment statuses. Orders that no
CONDUIT cart committed (foreign orders) are ignored.
"""

from __future__ import annotations

from typing import Callable

from conduit.cart.service import CartService
from conduit.mandate.ledger import DrawdownLedger, LedgerError


class SettlementCoordinator:
    def __init__(self, carts: CartService, ledger: DrawdownLedger,
                 now_ms_fn: Callable[[], int]):
        self._carts = carts
        self._ledger = ledger
        self._now_ms = now_ms_fn

    def on_payment(self, payment: dict) -> None:
        record = self._carts.find_by_committed_order(payment.get("order_id", ""))
        if record is None:
            return  # not a conduit-committed order
        mandate_id, ref = record.mandate_id, record.cart_id
        net = self._ledger.net_drawn(mandate_id, ref)
        status = payment.get("status")

        if status == "failed" and net > 0:
            # ADR-026: reverse as a visible entry; the user's money comes back
            # and the ledger shows exactly what happened.
            self._ledger.reverse(mandate_id, ref=ref, now_ms=self._now_ms())
        elif status == "captured" and net == 0:
            # a successful retry after a decline's reversal: re-establish the
            # drawdown. The boundary already re-gated the amount against the
            # live remaining balance, so failure here is an invariant breach.
            try:
                self._ledger.reserve(mandate_id, payment["amount"], ref=ref,
                                     now_ms=self._now_ms())
                self._ledger.confirm(mandate_id, ref=ref, now_ms=self._now_ms())
            except LedgerError as exc:
                raise LedgerError(
                    f"INVARIANT BREACH: payment {payment.get('id')} captured but the "
                    f"mandate could not be re-drawn ({exc}). The boundary must gate "
                    f"payment amounts against the live remaining balance.") from exc
