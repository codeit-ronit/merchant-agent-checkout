"""The append-only, hash-chained audit ledger.

Append-only is enforced at the storage layer, not by convention: the repository
interface has no update or delete method. Sequence numbers are gapless and
ledger-wide, enforced under a lock so concurrent writers cannot interleave or
create a gap.

Persistence: SQLite by default (one-command demo, no external service), behind a
repository so the swap to Postgres is contained (ADR-013). An in-memory
repository backs fast, deterministic tests.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Protocol

from sentinel.common.canonical import sha256_hex
from sentinel.common.ids import IdFactory
from sentinel.contracts.audit import GENESIS_HASH, AuditEntry


class LedgerRepository(Protocol):
    """No update/delete method exists — append-only by construction."""

    def append(self, entry: AuditEntry) -> None: ...
    def head(self) -> AuditEntry | None: ...
    def all(self) -> list[AuditEntry]: ...
    def count(self) -> int: ...


class InMemoryLedgerRepository:
    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def append(self, entry: AuditEntry) -> None:
        self._entries.append(entry)

    def head(self) -> AuditEntry | None:
        return self._entries[-1] if self._entries else None

    def all(self) -> list[AuditEntry]:
        return list(self._entries)

    def count(self) -> int:
        return len(self._entries)


class SqliteLedgerRepository:
    """SQLite-backed. Only INSERT and SELECT — no UPDATE/DELETE path exists."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS audit_log ("
            " sequence INTEGER PRIMARY KEY, entry_id TEXT UNIQUE NOT NULL,"
            " entry_hash TEXT NOT NULL, previous_hash TEXT NOT NULL,"
            " body TEXT NOT NULL)"
        )
        self._conn.commit()

    def append(self, entry: AuditEntry) -> None:
        self._conn.execute(
            "INSERT INTO audit_log (sequence, entry_id, entry_hash, previous_hash, body)"
            " VALUES (?,?,?,?,?)",
            (entry.sequence, entry.entry_id, entry.entry_hash, entry.previous_hash,
             entry.model_dump_json()),
        )
        self._conn.commit()

    def head(self) -> AuditEntry | None:
        row = self._conn.execute(
            "SELECT body FROM audit_log ORDER BY sequence DESC LIMIT 1").fetchone()
        return AuditEntry.model_validate(json.loads(row[0])) if row else None

    def all(self) -> list[AuditEntry]:
        rows = self._conn.execute("SELECT body FROM audit_log ORDER BY sequence ASC").fetchall()
        return [AuditEntry.model_validate(json.loads(r[0])) for r in rows]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]


class AuditLedger:
    """Constructs hash-chained entries and appends them under a single-writer
    lock so the sequence is gapless even under concurrent writers."""

    def __init__(self, repo: LedgerRepository | None = None, id_factory: IdFactory | None = None):
        self._repo = repo if repo is not None else InMemoryLedgerRepository()
        self._ids = id_factory or IdFactory()
        self._lock = threading.Lock()

    def record(self, **fields: Any) -> AuditEntry:
        """Append one entry. ``fields`` are AuditEntry fields EXCEPT the chain
        fields (entry_id, sequence, previous_hash, entry_hash), which are set
        here."""
        with self._lock:
            head = self._repo.head()
            previous_hash = head.entry_hash if head else GENESIS_HASH
            sequence = (head.sequence + 1) if head else 0
            draft = AuditEntry(
                entry_id=self._ids.entry(),
                sequence=sequence,
                previous_hash=previous_hash,
                entry_hash="",  # set below; excluded from chain_payload
                **fields,
            )
            entry_hash = sha256_hex(draft.chain_payload())
            entry = draft.model_copy(update={"entry_hash": entry_hash})
            self._repo.append(entry)
            return entry

    def entries(self) -> list[AuditEntry]:
        return self._repo.all()

    def count(self) -> int:
        return self._repo.count()
