"""Approval store — holds escalated actions awaiting a human.

Approvals are single-use, argument-bound, and expiring, and are re-validated on
resume: approving "refund ₹500 to payment X" must never authorise
"refund ₹5000 to payment X", and an expired approval is dead, not renewable.
"""

from sentinel.approvals.store import (
    ApprovalStore,
    InMemoryApprovalRepository,
    SqliteApprovalRepository,
)

__all__ = ["ApprovalStore", "InMemoryApprovalRepository", "SqliteApprovalRepository"]
