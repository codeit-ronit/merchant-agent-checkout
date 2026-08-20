"""Chain verification — walk from genesis and report the first break.

A verifiable audit log that nobody verifies is theatre, so this is exposed both
as ``make verify-audit`` and as a button in the operator UI. It re-computes each
entry's hash and checks (a) the recomputed hash matches the stored one, (b) the
stored previous_hash matches the prior entry's hash, and (c) the sequence is
gapless from 0.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from sentinel.common.canonical import sha256_hex
from sentinel.contracts.audit import GENESIS_HASH, AuditEntry


@dataclass
class VerificationResult:
    ok: bool
    entry_count: int
    first_break_sequence: int | None = None
    detail: str = ""

    def render(self) -> str:
        if self.ok:
            return f"verified — {self.entry_count} entries, chain intact"
        return (f"CHAIN BROKEN at entry #{self.first_break_sequence} "
                f"— refusing to certify ({self.detail})")


def verify_chain(entries: list[AuditEntry]) -> VerificationResult:
    prev_hash = GENESIS_HASH
    for i, entry in enumerate(entries):
        if entry.sequence != i:
            return VerificationResult(False, len(entries), i,
                                      f"sequence gap: expected {i}, got {entry.sequence}")
        if entry.previous_hash != prev_hash:
            return VerificationResult(False, len(entries), entry.sequence,
                                      "previous_hash does not match the prior entry")
        recomputed = sha256_hex(entry.chain_payload())
        if recomputed != entry.entry_hash:
            return VerificationResult(False, len(entries), entry.sequence,
                                      "entry content was altered (hash mismatch)")
        prev_hash = entry.entry_hash
    return VerificationResult(True, len(entries))


def _load_ledger():
    from sentinel.audit.ledger import SqliteLedgerRepository
    db = os.environ.get("SENTINEL_AUDIT_DB", "sentinel_state/audit.db")
    if not os.path.exists(db):
        return None
    return SqliteLedgerRepository(db).all()


def main() -> int:
    entries = _load_ledger()
    if entries is None:
        print("no audit ledger found (run the demo first: make demo-cli)")
        return 0
    result = verify_chain(entries)
    print(result.render())
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
