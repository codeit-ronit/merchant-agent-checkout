"""Cart storage — repository protocol, in-memory and SQLite, house pattern."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Protocol

from conduit.cart.model import CartRecord, CartStatus


class CartRepository(Protocol):
    def get(self, cart_id: str) -> CartRecord | None: ...
    def put(self, record: CartRecord) -> None: ...
    def open_carts(self) -> list[CartRecord]: ...
    def find_by_committed_order(self, order_id: str) -> CartRecord | None: ...


class InMemoryCartRepository:
    def __init__(self) -> None:
        self._carts: dict[str, CartRecord] = {}

    def get(self, cart_id: str) -> CartRecord | None:
        return self._carts.get(cart_id)

    def put(self, record: CartRecord) -> None:
        self._carts[record.cart_id] = record

    def open_carts(self) -> list[CartRecord]:
        return [c for c in self._carts.values() if c.status is CartStatus.OPEN]

    def find_by_committed_order(self, order_id: str) -> CartRecord | None:
        return next((c for c in self._carts.values()
                     if c.committed_order_id == order_id), None)


class SqliteCartRepository:
    def __init__(self, db_path: str | Path):
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS carts (
              cart_id TEXT PRIMARY KEY, mandate_id TEXT NOT NULL,
              currency TEXT NOT NULL, created_at_ms INTEGER NOT NULL,
              expires_at_ms INTEGER NOT NULL, status TEXT NOT NULL,
              lines TEXT NOT NULL,
              committed_order_id TEXT, committed_amount_minor INTEGER,
              last_priced TEXT NOT NULL DEFAULT '{}',
              last_priced_catalog_version INTEGER NOT NULL DEFAULT 0,
              offers TEXT NOT NULL DEFAULT '{}',
              offers_surfaced INTEGER NOT NULL DEFAULT 0,
              accepted_upsells TEXT NOT NULL DEFAULT '{}'
            );
            """
        )
        self._conn.commit()

    def get(self, cart_id: str) -> CartRecord | None:
        row = self._conn.execute("SELECT * FROM carts WHERE cart_id = ?", (cart_id,)).fetchone()
        if row is None:
            return None
        return CartRecord(
            cart_id=row[0], mandate_id=row[1], currency=row[2], created_at_ms=row[3],
            expires_at_ms=row[4], status=CartStatus(row[5]), lines=json.loads(row[6]),
            committed_order_id=row[7], committed_amount_minor=row[8],
            last_priced=json.loads(row[9]), last_priced_catalog_version=row[10],
            offers=json.loads(row[11]), offers_surfaced=row[12],
            accepted_upsells=json.loads(row[13]))

    def put(self, record: CartRecord) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO carts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (record.cart_id, record.mandate_id, record.currency, record.created_at_ms,
             record.expires_at_ms, record.status.value, json.dumps(record.lines),
             record.committed_order_id, record.committed_amount_minor,
             json.dumps(record.last_priced), record.last_priced_catalog_version,
             json.dumps(record.offers), record.offers_surfaced,
             json.dumps(record.accepted_upsells)))
        self._conn.commit()

    def open_carts(self) -> list[CartRecord]:
        rows = self._conn.execute("SELECT cart_id FROM carts WHERE status = 'OPEN'").fetchall()
        return [self.get(r[0]) for r in rows]

    def find_by_committed_order(self, order_id: str) -> CartRecord | None:
        row = self._conn.execute("SELECT cart_id FROM carts WHERE committed_order_id = ?",
                                 (order_id,)).fetchone()
        return self.get(row[0]) if row else None
