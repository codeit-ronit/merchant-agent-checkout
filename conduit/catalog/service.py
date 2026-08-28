"""CatalogService — the single source of price and availability truth.

Two sides with different authority:

* **Merchant side** (``upsert_items``, ``set_price``, ``set_availability``,
  ``put_upsell_rule``): the only code paths that can put a price into the
  catalog. Every mutation bumps the catalog version; every price change is
  logged with from/to and versions.
* **Agent side** (``search``, ``get_item``, ``check_availability``,
  ``bulk_feed``): read-only views. No agent-facing method accepts a price,
  and the MCP layer rejects (never ignores) any attempt to pass one.

Deterministic: mutations take ``now_ms`` from the caller. No clock here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from conduit.catalog.model import (
    Availability,
    CatalogItem,
    MerchantConfig,
    PriceChange,
    UpsellRule,
)
from conduit.catalog.store import CatalogRepository


class CatalogError(Exception):
    """Catalog-side rejection. Carries a plain-language, actionable message."""


@dataclass(frozen=True)
class SearchQuery:
    category: str | None = None
    attributes: frozenset[str] = frozenset()   # every listed attribute must be present
    exclude_attributes: frozenset[str] = frozenset()
    max_price_minor: int | None = None         # a read filter; binds nothing
    in_stock_only: bool = False


class CatalogService:
    def __init__(self, repo: CatalogRepository):
        self._repo = repo

    # ------------------------------------------------------------------
    # merchant side — the ONLY price-writing paths
    # ------------------------------------------------------------------
    def upsert_items(self, items: list[CatalogItem], *, now_ms: int) -> int:
        """Insert or replace items. Price changes on existing items are
        version-bumped and logged. Returns the new catalog version."""
        for item in items:
            existing = self._repo.get_item(item.item_id)
            if existing is not None and existing.price_minor != item.price_minor:
                item = replace(item, price_version=existing.price_version + 1)
                self._repo.record_price_change(PriceChange(
                    item_id=item.item_id,
                    from_minor=existing.price_minor, to_minor=item.price_minor,
                    from_version=existing.price_version, to_version=item.price_version,
                    changed_at_ms=now_ms))
            elif existing is not None:
                item = replace(item, price_version=existing.price_version)
            self._repo.put_item(item)
        return self._repo.bump_version()

    def set_price(self, item_id: str, new_price_minor: int, *, now_ms: int) -> CatalogItem:
        if isinstance(new_price_minor, bool) or not isinstance(new_price_minor, int):
            raise CatalogError("price must be an integer number of minor units")
        item = self._require(item_id)
        if new_price_minor == item.price_minor:
            return item
        updated = replace(item, price_minor=new_price_minor, price_version=item.price_version + 1)
        self._repo.record_price_change(PriceChange(
            item_id=item_id, from_minor=item.price_minor, to_minor=new_price_minor,
            from_version=item.price_version, to_version=updated.price_version,
            changed_at_ms=now_ms))
        self._repo.put_item(updated)
        self._repo.bump_version()
        return updated

    def set_availability(self, item_id: str, availability: Availability, *, now_ms: int) -> CatalogItem:
        item = self._require(item_id)
        updated = replace(item, availability=availability)
        self._repo.put_item(updated)
        self._repo.bump_version()
        return updated

    def put_upsell_rule(self, rule: UpsellRule) -> None:
        self._require(rule.trigger_item_id)
        self._require(rule.offer_item_id)  # offer price comes from the catalog like any item
        self._repo.put_upsell_rule(rule)
        self._repo.bump_version()

    def put_merchant(self, merchant: MerchantConfig) -> None:
        self._repo.put_merchant(merchant)

    # ------------------------------------------------------------------
    # agent side — read-only truth
    # ------------------------------------------------------------------
    def get_item(self, item_id: str) -> CatalogItem:
        return self._require(item_id)

    def search(self, query: SearchQuery) -> list[CatalogItem]:
        out = []
        for item in self._repo.list_items():
            if query.category and item.category != query.category:
                continue
            if query.attributes and not query.attributes <= item.attributes:
                continue
            if query.exclude_attributes and query.exclude_attributes & item.attributes:
                continue
            if query.max_price_minor is not None and item.price_minor > query.max_price_minor:
                continue
            if query.in_stock_only and not item.availability.purchasable(1):
                continue
            out.append(item)
        return out

    def check_availability(self, item_id: str, quantity: int) -> dict:
        item = self._require(item_id)
        return {
            "item_id": item_id,
            "requested_quantity": quantity,
            "purchasable": item.availability.purchasable(quantity),
            "stock": item.availability.stock.value,
            "stock_count": item.availability.count,
            "price_minor": item.price_minor,
            "currency": item.currency,
            "price_version": item.price_version,
            "catalog_version": self._repo.catalog_version(),
        }

    def bulk_feed(self) -> dict:
        """The discovery document: everything at once, versioned, cacheable.
        Answers "what exists"; the tools answer "what is true right now"."""
        return {
            "entity": "catalog_feed",
            "catalog_version": self._repo.catalog_version(),
            "items": [i.to_public() for i in self._repo.list_items()],
        }

    def upsell_rules(self) -> list[UpsellRule]:
        return self._repo.list_upsell_rules()

    def merchant(self) -> MerchantConfig | None:
        return self._repo.get_merchant()

    def catalog_version(self) -> int:
        return self._repo.catalog_version()

    def price_history(self, item_id: str) -> list[PriceChange]:
        return self._repo.price_history(item_id)

    # ------------------------------------------------------------------
    def _require(self, item_id: str) -> CatalogItem:
        item = self._repo.get_item(item_id)
        if item is None:
            raise CatalogError(
                f"no catalog item '{item_id}'. Search the catalog for valid item ids — "
                f"phantom items are rejected, never created.")
        return item
