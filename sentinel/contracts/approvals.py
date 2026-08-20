"""``ApprovalRequest`` — one escalated action awaiting a human.

Invariants (enforced in the store and proven in tests):
* **Single use** — a consumed approval cannot authorise a second call.
* **Argument-bound** — any change to arguments (one byte) invalidates it.
* **Expiry is absolute and not extendable.**
* **Rejection is terminal** for that call.

The ``summary`` is a product requirement, not a nicety: one sentence an
operations person can act on in under 30 seconds without reading JSON.
"""

from __future__ import annotations

from typing import Optional

from sentinel.contracts.base import Contract
from sentinel.contracts.decision import DecisionContext, PolicyDecision
from sentinel.contracts.enums import ApprovalStatus


class ApprovalRequest(Contract):
    id: str
    run_id: str
    call_id: str

    context: DecisionContext          # snapshot at escalation time (already redacted)
    decision: PolicyDecision          # the decision that escalated it

    argument_hash: str                # THE binding — authorises exactly these args
    summary: str                      # one plain sentence for the reviewer

    created_at_ms: int
    expires_at_ms: int

    # Whether this run processed untrusted content — the single most decision-
    # relevant fact for the reviewer, surfaced prominently in the UI.
    processed_untrusted_content: bool = False

    status: ApprovalStatus = ApprovalStatus.PENDING
    resolver_id: Optional[str] = None
    resolved_at_ms: Optional[int] = None
    note: Optional[str] = None

    def is_expired(self, now_ms: int) -> bool:
        return now_ms >= self.expires_at_ms

    def authorises(self, argument_hash: str, now_ms: int) -> bool:
        """True only if APPROVED, unexpired, unconsumed, and bound to exactly
        these arguments. Re-checked on resume — never trust a pre-suspension
        decision."""
        return (
            self.status == ApprovalStatus.APPROVED
            and not self.is_expired(now_ms)
            and self.argument_hash == argument_hash
        )
