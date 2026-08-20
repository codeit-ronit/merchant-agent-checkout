"""Audit ledger — append-only, SHA-256 hash-chained, gapless sequence.

Tamper-EVIDENT, not tamper-PROOF (LIMITATIONS.md): altering entry N invalidates
every entry after it and the verifier reports the first break, but anyone who can
write to the store can recompute the whole chain. Real resistance needs an
external anchor or write-once storage — neither is implemented.
"""

from sentinel.audit.ledger import (
    AuditLedger,
    InMemoryLedgerRepository,
    LedgerRepository,
    SqliteLedgerRepository,
)
from sentinel.audit.verify import VerificationResult, verify_chain

__all__ = [
    "AuditLedger", "LedgerRepository", "InMemoryLedgerRepository",
    "SqliteLedgerRepository", "verify_chain", "VerificationResult",
]
