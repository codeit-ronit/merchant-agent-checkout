"""The drawdown ledger — an append-only log, never a running integer.

Balance is DERIVED from the entries at read time (05-MANDATE §3.2): that gives
an audit trail, makes reserve/confirm/release explicit states, means the
balance is reconstructible rather than trusted, and makes suspend/resume
incapable of losing it — the run holds no authoritative copy.

Concurrency: ``reserve`` is the serialisation point (04 §5). The
check-and-append is atomic under one lock, so two commits against the same
mandate cannot both pass a balance check the other has already consumed.

Confirm-at-order-creation, reverse-on-decline semantics are ADR-026; the
REVERSE entry kind exists now so Phase 4 reverses as a *ledger entry*, never
a deletion.

Deterministic: no clock — every mutating call takes ``now_ms``.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from sentinel.common.money import MINOR_UNIT_EXPONENT, format_amount


class LedgerError(Exception):
    """A drawdown operation that cannot proceed. Message names the shortfall
    or the state conflict — a block with no next step is a bug."""


class EntryKind(str, Enum):
    RESERVE = "RESERVE"    # held ahead of the upstream write (reserve-before-forward)
    CONFIRM = "CONFIRM"    # the write succeeded; reservation became a drawdown
    RELEASE = "RELEASE"    # the write failed / cart expired; hold returned
    REVERSE = "REVERSE"    # a confirmed drawdown undone (Phase 4: decline) — an entry, not a deletion


@dataclass(frozen=True)
class LedgerEntry:
    seq: int
    mandate_id: str
    kind: EntryKind
    amount_minor: int
    ref: str              # what this movement belongs to (cart id / order id)
    at_ms: int


@dataclass(frozen=True)
class Mandate:
    """The consent envelope: a locked amount, for ONE merchant, until an
    absolute non-extendable expiry, revocable instantly. The instrument is
    bound by CONTACT (ADR-028 finding 7: `fetch_tokens` is keyed by contact,
    not customer id — the identity model owns that mapping explicitly).

    Phase 2 callers that predate scope/expiry get permissive defaults ONLY in
    the sense that a blank scope never matches any merchant — absent scope
    fails closed at the policy gate, not open."""

    mandate_id: str
    locked_minor: int
    currency: str
    scope_merchant_id: str = ""          # "" matches no merchant: fail closed
    expires_at_ms: int = 0               # 0 = already expired: fail closed
    status: str = "ACTIVE"               # ACTIVE | REVOKED
    instrument_contact: str | None = None  # synthetic contact -> fetch_tokens key
    customer_id: str | None = None         # rail customer (minted by fetch_tokens)

    def __post_init__(self) -> None:
        if isinstance(self.locked_minor, bool) or not isinstance(self.locked_minor, int):
            raise TypeError("locked_minor must be an integer number of minor units")
        if self.locked_minor <= 0:
            raise ValueError("locked_minor must be positive")
        if self.currency not in MINOR_UNIT_EXPONENT:
            raise ValueError(f"unknown currency '{self.currency}'")
        if isinstance(self.expires_at_ms, bool) or not isinstance(self.expires_at_ms, int):
            raise TypeError("expires_at_ms must be an integer epoch ms")
        if self.status not in ("ACTIVE", "REVOKED"):
            raise ValueError(f"unknown mandate status '{self.status}'")


@dataclass(frozen=True)
class Balance:
    """Derived, never stored."""

    locked_minor: int
    reserved_minor: int    # active holds (RESERVE not yet CONFIRMed/RELEASEd)
    drawn_minor: int       # CONFIRMed minus REVERSEd
    remaining_minor: int   # locked - reserved - drawn


class LedgerRepository(Protocol):
    def append(self, entry: LedgerEntry) -> None: ...
    def entries(self, mandate_id: str) -> list[LedgerEntry]: ...
    def next_seq(self) -> int: ...
    def put_mandate(self, mandate: Mandate) -> None: ...
    def get_mandate(self, mandate_id: str) -> Mandate | None: ...


class InMemoryLedgerRepository:
    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []
        self._mandates: dict[str, Mandate] = {}

    def append(self, entry: LedgerEntry) -> None:
        self._entries.append(entry)

    def entries(self, mandate_id: str) -> list[LedgerEntry]:
        return [e for e in self._entries if e.mandate_id == mandate_id]

    def next_seq(self) -> int:
        return len(self._entries) + 1

    def put_mandate(self, mandate: Mandate) -> None:
        self._mandates[mandate.mandate_id] = mandate

    def get_mandate(self, mandate_id: str) -> Mandate | None:
        return self._mandates.get(mandate_id)


class SqliteLedgerRepository:
    def __init__(self, db_path: str | Path):
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS mandates (
              mandate_id TEXT PRIMARY KEY, locked_minor INTEGER NOT NULL,
              currency TEXT NOT NULL,
              scope_merchant_id TEXT NOT NULL DEFAULT '',
              expires_at_ms INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL DEFAULT 'ACTIVE',
              instrument_contact TEXT, customer_id TEXT
            );
            CREATE TABLE IF NOT EXISTS drawdown_entries (
              seq INTEGER PRIMARY KEY,
              mandate_id TEXT NOT NULL, kind TEXT NOT NULL,
              amount_minor INTEGER NOT NULL, ref TEXT NOT NULL, at_ms INTEGER NOT NULL
            );
            """
        )
        self._conn.commit()

    def append(self, entry: LedgerEntry) -> None:
        self._conn.execute(
            "INSERT INTO drawdown_entries VALUES (?,?,?,?,?,?)",
            (entry.seq, entry.mandate_id, entry.kind.value,
             entry.amount_minor, entry.ref, entry.at_ms))
        self._conn.commit()

    def entries(self, mandate_id: str) -> list[LedgerEntry]:
        rows = self._conn.execute(
            "SELECT seq, mandate_id, kind, amount_minor, ref, at_ms FROM drawdown_entries"
            " WHERE mandate_id = ? ORDER BY seq", (mandate_id,)).fetchall()
        return [LedgerEntry(r[0], r[1], EntryKind(r[2]), r[3], r[4], r[5]) for r in rows]

    def next_seq(self) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM drawdown_entries").fetchone()
        return row[0]

    def put_mandate(self, mandate: Mandate) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO mandates VALUES (?,?,?,?,?,?,?,?)",
            (mandate.mandate_id, mandate.locked_minor, mandate.currency,
             mandate.scope_merchant_id, mandate.expires_at_ms, mandate.status,
             mandate.instrument_contact, mandate.customer_id))
        self._conn.commit()

    def get_mandate(self, mandate_id: str) -> Mandate | None:
        row = self._conn.execute(
            "SELECT mandate_id, locked_minor, currency, scope_merchant_id,"
            " expires_at_ms, status, instrument_contact, customer_id"
            " FROM mandates WHERE mandate_id = ?",
            (mandate_id,)).fetchone()
        return Mandate(*row) if row else None


class DrawdownLedger:
    """Reserve → confirm | release, atomically, against a derived balance."""

    def __init__(self, repo: LedgerRepository):
        self._repo = repo
        self._lock = threading.Lock()  # THE serialisation point

    # ---- setup ----
    def create_mandate(self, mandate: Mandate) -> None:
        self._repo.put_mandate(mandate)

    def get_mandate(self, mandate_id: str) -> Mandate:
        mandate = self._repo.get_mandate(mandate_id)
        if mandate is None:
            raise LedgerError(f"no mandate '{mandate_id}'. Create one before opening a cart against it.")
        return mandate

    # ---- derived state ----
    def balance(self, mandate_id: str) -> Balance:
        mandate = self.get_mandate(mandate_id)
        reserved = drawn = 0
        open_holds: dict[str, int] = {}
        for e in self._repo.entries(mandate_id):
            if e.kind is EntryKind.RESERVE:
                open_holds[e.ref] = open_holds.get(e.ref, 0) + e.amount_minor
            elif e.kind is EntryKind.CONFIRM:
                open_holds.pop(e.ref, None)
                drawn += e.amount_minor
            elif e.kind is EntryKind.RELEASE:
                open_holds.pop(e.ref, None)
            elif e.kind is EntryKind.REVERSE:
                drawn -= e.amount_minor
        reserved = sum(open_holds.values())
        return Balance(locked_minor=mandate.locked_minor, reserved_minor=reserved,
                       drawn_minor=drawn,
                       remaining_minor=mandate.locked_minor - reserved - drawn)

    def active_reservation(self, mandate_id: str, ref: str) -> int | None:
        """The open hold for a ref, if any (RESERVE without CONFIRM/RELEASE)."""
        amount = None
        for e in self._repo.entries(mandate_id):
            if e.ref != ref:
                continue
            if e.kind is EntryKind.RESERVE:
                amount = e.amount_minor
            elif e.kind in (EntryKind.CONFIRM, EntryKind.RELEASE):
                amount = None
        return amount

    def entries(self, mandate_id: str) -> list[LedgerEntry]:
        return self._repo.entries(mandate_id)

    # ---- the atomic step ----
    def reserve(self, mandate_id: str, amount_minor: int, *, ref: str, now_ms: int) -> Balance:
        if isinstance(amount_minor, bool) or not isinstance(amount_minor, int) or amount_minor <= 0:
            raise LedgerError("reservation amount must be a positive integer of minor units")
        with self._lock:
            mandate = self.get_mandate(mandate_id)
            # Defence in depth: policy is the gate, but the ledger refuses to
            # hold money against a dead envelope even if a caller skips policy.
            if mandate.status != "ACTIVE":
                raise LedgerError(
                    f"mandate '{mandate_id}' is {mandate.status}: revocation is instant "
                    f"and total; nothing further can be reserved against it.")
            if mandate.expires_at_ms and now_ms >= mandate.expires_at_ms:
                raise LedgerError(
                    f"mandate '{mandate_id}' expired; it cannot be extended. "
                    f"The user must set aside a new one.")
            bal = self.balance(mandate_id)
            if self.active_reservation(mandate_id, ref) is not None:
                raise LedgerError(f"ref '{ref}' already holds an active reservation")
            if amount_minor > bal.remaining_minor:
                shortfall = amount_minor - bal.remaining_minor
                raise LedgerError(
                    f"insufficient mandate balance: needs "
                    f"{format_amount(amount_minor, mandate.currency)}, remaining "
                    f"{format_amount(bal.remaining_minor, mandate.currency)} — short by "
                    f"{format_amount(shortfall, mandate.currency)}. Reduce the cart "
                    f"or ask the user to raise the mandate.")
            self._repo.append(LedgerEntry(self._repo.next_seq(), mandate_id,
                                          EntryKind.RESERVE, amount_minor, ref, now_ms))
            return self.balance(mandate_id)

    def confirm(self, mandate_id: str, *, ref: str, now_ms: int) -> Balance:
        with self._lock:
            mandate = self.get_mandate(mandate_id)
            if mandate.status != "ACTIVE":
                # In-flight commits are denied immediately on revocation
                # (05-MANDATE §3.3) — never allowed to finish "because it
                # already started".
                raise LedgerError(
                    f"mandate '{mandate_id}' is {mandate.status}; the in-flight "
                    f"drawdown cannot be confirmed.")
            held = self.active_reservation(mandate_id, ref)
            if held is None:
                raise LedgerError(f"no active reservation for ref '{ref}' to confirm")
            self._repo.append(LedgerEntry(self._repo.next_seq(), mandate_id,
                                          EntryKind.CONFIRM, held, ref, now_ms))
            return self.balance(mandate_id)

    def release(self, mandate_id: str, *, ref: str, now_ms: int) -> Balance:
        with self._lock:
            held = self.active_reservation(mandate_id, ref)
            if held is None:
                raise LedgerError(f"no active reservation for ref '{ref}' to release")
            self._repo.append(LedgerEntry(self._repo.next_seq(), mandate_id,
                                          EntryKind.RELEASE, held, ref, now_ms))
            return self.balance(mandate_id)

    def reverse(self, mandate_id: str, *, ref: str, now_ms: int) -> Balance:
        """Undo a CONFIRMed drawdown as a new entry (ADR-026: visible, never a
        deletion). Phase 4 uses this on payment decline."""
        with self._lock:
            confirmed = 0
            for e in self._repo.entries(mandate_id):
                if e.ref == ref:
                    if e.kind is EntryKind.CONFIRM:
                        confirmed += e.amount_minor
                    elif e.kind is EntryKind.REVERSE:
                        confirmed -= e.amount_minor
            if confirmed <= 0:
                raise LedgerError(f"no confirmed drawdown for ref '{ref}' to reverse")
            self._repo.append(LedgerEntry(self._repo.next_seq(), mandate_id,
                                          EntryKind.REVERSE, confirmed, ref, now_ms))
            return self.balance(mandate_id)
