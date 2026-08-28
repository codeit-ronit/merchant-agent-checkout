"""Catalog storage — repository protocol with in-memory and SQLite backends,
mirroring SENTINEL's store pattern (approvals/audit).

Two properties the commit gate depends on:

* **A monotonic catalog version**, bumped on every mutation, stamped onto the
  bulk feed and every priced view — the provenance field that makes a
  commit-time re-price diff attributable.
* **An append-only price-change log** so a diff can name what changed, from
  what, to what, and when.

No clock in here: every mutating call takes ``now_ms`` from the caller, the
same discipline the policy engine enforces for itself.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Protocol

from conduit.catalog.model import (
    Availability,
    CatalogItem,
    Constraints,
    FreeText,
    MerchantConfig,
    PriceChange,
    Stock,
    TaxTreatment,
    UpsellRule,
)


class CatalogRepository(Protocol):
    def get_item(self, item_id: str) -> CatalogItem | None: ...
    def put_item(self, item: CatalogItem) -> None: ...
    def list_items(self) -> list[CatalogItem]: ...
    def record_price_change(self, change: PriceChange) -> None: ...
    def price_history(self, item_id: str) -> list[PriceChange]: ...
    def catalog_version(self) -> int: ...
    def bump_version(self) -> int: ...
    def put_upsell_rule(self, rule: UpsellRule) -> None: ...
    def list_upsell_rules(self) -> list[UpsellRule]: ...
    def get_merchant(self) -> MerchantConfig | None: ...
    def put_merchant(self, merchant: MerchantConfig) -> None: ...


class InMemoryCatalogRepository:
    def __init__(self) -> None:
        self._items: dict[str, CatalogItem] = {}
        self._changes: list[PriceChange] = []
        self._rules: dict[str, UpsellRule] = {}
        self._merchant: MerchantConfig | None = None
        self._version = 0

    def get_item(self, item_id: str) -> CatalogItem | None:
        return self._items.get(item_id)

    def put_item(self, item: CatalogItem) -> None:
        self._items[item.item_id] = item

    def list_items(self) -> list[CatalogItem]:
        return sorted(self._items.values(), key=lambda i: i.item_id)

    def record_price_change(self, change: PriceChange) -> None:
        self._changes.append(change)

    def price_history(self, item_id: str) -> list[PriceChange]:
        return [c for c in self._changes if c.item_id == item_id]

    def catalog_version(self) -> int:
        return self._version

    def bump_version(self) -> int:
        self._version += 1
        return self._version

    def put_upsell_rule(self, rule: UpsellRule) -> None:
        self._rules[rule.rule_id] = rule

    def list_upsell_rules(self) -> list[UpsellRule]:
        return sorted(self._rules.values(), key=lambda r: r.rule_id)

    def get_merchant(self) -> MerchantConfig | None:
        return self._merchant

    def put_merchant(self, merchant: MerchantConfig) -> None:
        self._merchant = merchant


def _item_to_row(item: CatalogItem) -> tuple:
    return (
        item.item_id,
        item.price_minor,
        item.currency,
        item.availability.stock.value,
        item.availability.count,
        item.text.name,
        item.text.description,
        item.text.merchant_note,
        item.tax.rate_bps,
        item.tax.category,
        item.category,
        json.dumps(sorted(item.attributes)),
        item.constraints.min_quantity,
        item.constraints.max_per_order,
        item.constraints.requires_item_id,
        item.variant_of,
        item.price_version,
    )


def _row_to_item(row: tuple) -> CatalogItem:
    (item_id, price_minor, currency, stock, count, name, description, merchant_note,
     rate_bps, tax_category, category, attributes, min_q, max_q, requires, variant_of,
     price_version) = row
    return CatalogItem(
        item_id=item_id,
        price_minor=price_minor,
        currency=currency,
        availability=Availability(stock=Stock(stock), count=count),
        text=FreeText(name=name, description=description, merchant_note=merchant_note),
        tax=TaxTreatment(rate_bps=rate_bps, category=tax_category),
        category=category,
        attributes=frozenset(json.loads(attributes)),
        constraints=Constraints(min_quantity=min_q, max_per_order=max_q, requires_item_id=requires),
        variant_of=variant_of,
        price_version=price_version,
    )


class SqliteCatalogRepository:
    def __init__(self, db_path: str | Path):
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS items (
              item_id TEXT PRIMARY KEY, price_minor INTEGER NOT NULL,
              currency TEXT NOT NULL, stock TEXT NOT NULL, stock_count INTEGER,
              name TEXT NOT NULL, description TEXT NOT NULL, merchant_note TEXT,
              tax_rate_bps INTEGER NOT NULL, tax_category TEXT, category TEXT NOT NULL,
              attributes TEXT NOT NULL, min_quantity INTEGER NOT NULL,
              max_per_order INTEGER, requires_item_id TEXT, variant_of TEXT,
              price_version INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS price_changes (
              seq INTEGER PRIMARY KEY AUTOINCREMENT,
              item_id TEXT NOT NULL, from_minor INTEGER NOT NULL, to_minor INTEGER NOT NULL,
              from_version INTEGER NOT NULL, to_version INTEGER NOT NULL,
              changed_at_ms INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS upsell_rules (
              rule_id TEXT PRIMARY KEY, trigger_item_id TEXT NOT NULL,
              offer_item_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS merchant (
              merchant_id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
              max_upsell_offers_per_cart INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
            INSERT OR IGNORE INTO meta (key, value) VALUES ('catalog_version', 0);
            """
        )
        self._conn.commit()

    def get_item(self, item_id: str) -> CatalogItem | None:
        row = self._conn.execute("SELECT * FROM items WHERE item_id = ?", (item_id,)).fetchone()
        return _row_to_item(row) if row else None

    def put_item(self, item: CatalogItem) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            _item_to_row(item))
        self._conn.commit()

    def list_items(self) -> list[CatalogItem]:
        rows = self._conn.execute("SELECT * FROM items ORDER BY item_id").fetchall()
        return [_row_to_item(r) for r in rows]

    def record_price_change(self, change: PriceChange) -> None:
        self._conn.execute(
            "INSERT INTO price_changes (item_id, from_minor, to_minor, from_version, to_version, changed_at_ms)"
            " VALUES (?,?,?,?,?,?)",
            (change.item_id, change.from_minor, change.to_minor,
             change.from_version, change.to_version, change.changed_at_ms))
        self._conn.commit()

    def price_history(self, item_id: str) -> list[PriceChange]:
        rows = self._conn.execute(
            "SELECT item_id, from_minor, to_minor, from_version, to_version, changed_at_ms"
            " FROM price_changes WHERE item_id = ? ORDER BY seq", (item_id,)).fetchall()
        return [PriceChange(*r) for r in rows]

    def catalog_version(self) -> int:
        return self._conn.execute("SELECT value FROM meta WHERE key='catalog_version'").fetchone()[0]

    def bump_version(self) -> int:
        self._conn.execute("UPDATE meta SET value = value + 1 WHERE key='catalog_version'")
        self._conn.commit()
        return self.catalog_version()

    def put_upsell_rule(self, rule: UpsellRule) -> None:
        self._conn.execute("INSERT OR REPLACE INTO upsell_rules VALUES (?,?,?)",
                           (rule.rule_id, rule.trigger_item_id, rule.offer_item_id))
        self._conn.commit()

    def list_upsell_rules(self) -> list[UpsellRule]:
        rows = self._conn.execute("SELECT rule_id, trigger_item_id, offer_item_id"
                                  " FROM upsell_rules ORDER BY rule_id").fetchall()
        return [UpsellRule(*r) for r in rows]

    def get_merchant(self) -> MerchantConfig | None:
        row = self._conn.execute("SELECT merchant_id, display_name, max_upsell_offers_per_cart"
                                 " FROM merchant").fetchone()
        return MerchantConfig(*row) if row else None

    def put_merchant(self, merchant: MerchantConfig) -> None:
        self._conn.execute("INSERT OR REPLACE INTO merchant VALUES (?,?,?)",
                           (merchant.merchant_id, merchant.display_name,
                            merchant.max_upsell_offers_per_cart))
        self._conn.commit()


__all__ = ["CatalogRepository", "InMemoryCatalogRepository", "SqliteCatalogRepository"]
