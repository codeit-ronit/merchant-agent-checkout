"""Catalog types. Types before behaviour.

Two structural rules enforced here, not by convention:

* **Money is integer minor units.** A float in a money position raises at
  construction, even if it would round cleanly. Tax rates are integer basis
  points for the same reason.
* **Trusted and untrusted fields are separated by type.** Machine fields
  (id, price, stock, currency) live on ``CatalogItem``; merchant-authored
  free text lives only inside ``FreeText``, so no code path can read a
  description without going through the field the proxy quarantines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from sentinel.common.money import MINOR_UNIT_EXPONENT


class Stock(str, Enum):
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    LIMITED = "LIMITED"  # requires a count


def _require_int(value: object, name: str) -> int:
    """A money-position guard: ints only, and bool is not an int here."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer (minor units); got {type(value).__name__}")
    return value


@dataclass(frozen=True)
class TaxTreatment:
    """Declared by the merchant. We declare tax; we never compute tax policy.

    ``rate_bps`` is the declared rate in integer basis points (5% == 500) —
    basis points because a float rate is a float in a money path.
    """

    rate_bps: int = 0
    category: str | None = None  # e.g. a GST category label, opaque to us

    def __post_init__(self) -> None:
        _require_int(self.rate_bps, "tax rate_bps")
        if not (0 <= self.rate_bps <= 10_000):
            raise ValueError("tax rate_bps must be within [0, 10000]")


@dataclass(frozen=True)
class Availability:
    stock: Stock
    count: int | None = None  # required iff LIMITED

    def __post_init__(self) -> None:
        if self.stock is Stock.LIMITED:
            if self.count is None or isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 0:
                raise ValueError("LIMITED availability requires a non-negative integer count")
        elif self.count is not None:
            raise ValueError(f"count is only meaningful for LIMITED stock, not {self.stock.value}")

    def purchasable(self, quantity: int) -> bool:
        if self.stock is Stock.IN_STOCK:
            return True
        if self.stock is Stock.LIMITED:
            return quantity <= (self.count or 0)
        return False


@dataclass(frozen=True)
class Constraints:
    min_quantity: int = 1
    max_per_order: int | None = None
    requires_item_id: str | None = None  # requires-another-item

    def __post_init__(self) -> None:
        if self.min_quantity < 1:
            raise ValueError("min_quantity must be >= 1")
        if self.max_per_order is not None and self.max_per_order < self.min_quantity:
            raise ValueError("max_per_order cannot be below min_quantity")


@dataclass(frozen=True)
class FreeText:
    """Merchant-authored text. UNTRUSTED by classification; the proxy
    quarantines these fields on every tool response that carries them."""

    name: str
    description: str = ""
    merchant_note: str | None = None


@dataclass(frozen=True)
class CatalogItem:
    item_id: str
    price_minor: int
    currency: str
    availability: Availability
    text: FreeText
    tax: TaxTreatment = field(default_factory=TaxTreatment)
    category: str = ""
    attributes: frozenset[str] = frozenset()  # constraint matching: "veg", "spicy", ...
    constraints: Constraints = field(default_factory=Constraints)
    variant_of: str | None = None
    price_version: int = 1  # bumped by the store on every price change

    def __post_init__(self) -> None:
        if not self.item_id:
            raise ValueError("item_id is required")
        _require_int(self.price_minor, "price_minor")
        if self.price_minor <= 0:
            raise ValueError("price_minor must be positive")
        if self.currency not in MINOR_UNIT_EXPONENT:
            raise ValueError(f"unknown currency '{self.currency}'")
        _require_int(self.price_version, "price_version")
        if not isinstance(self.attributes, frozenset):
            object.__setattr__(self, "attributes", frozenset(self.attributes))

    # --- serialisation for tool responses / the bulk feed ---
    def structured_fields(self) -> dict:
        """Machine-authoritative fields only (TOOL_STRUCTURED)."""
        return {
            "item_id": self.item_id,
            "price_minor": self.price_minor,
            "currency": self.currency,
            "stock": self.availability.stock.value,
            "stock_count": self.availability.count,
            "tax_rate_bps": self.tax.rate_bps,
            "tax_category": self.tax.category,
            "category": self.category,
            "attributes": sorted(self.attributes),
            "min_quantity": self.constraints.min_quantity,
            "max_per_order": self.constraints.max_per_order,
            "requires_item_id": self.constraints.requires_item_id,
            "variant_of": self.variant_of,
            "price_version": self.price_version,
        }

    def to_public(self) -> dict:
        """Full tool-response shape: structured fields + the untrusted free
        text under the exact field names tool_classes.yaml marks UNTRUSTED."""
        out = self.structured_fields()
        out["name"] = self.text.name
        out["description"] = self.text.description
        out["merchant_note"] = self.text.merchant_note
        return out


@dataclass(frozen=True)
class UpsellRule:
    """Merchant-authored. The ONLY source an offer may come from — an offer
    with no rule behind it is a policy violation, not a creative flourish."""

    rule_id: str
    trigger_item_id: str
    offer_item_id: str

    def __post_init__(self) -> None:
        if not (self.rule_id and self.trigger_item_id and self.offer_item_id):
            raise ValueError("rule_id, trigger_item_id and offer_item_id are all required")
        if self.trigger_item_id == self.offer_item_id:
            raise ValueError("an item cannot upsell itself")


@dataclass(frozen=True)
class MerchantConfig:
    merchant_id: str
    display_name: str  # merchant-authored → untrusted on any output surface
    max_upsell_offers_per_cart: int = 1

    def __post_init__(self) -> None:
        if self.max_upsell_offers_per_cart < 0:
            raise ValueError("max_upsell_offers_per_cart must be >= 0")


@dataclass(frozen=True)
class PriceChange:
    """One entry in the price-version log — what makes the commit-time diff
    able to say not just *that* the total changed but *why*."""

    item_id: str
    from_minor: int
    to_minor: int
    from_version: int
    to_version: int
    changed_at_ms: int

    def __post_init__(self) -> None:
        for f in ("from_minor", "to_minor", "from_version", "to_version", "changed_at_ms"):
            _require_int(getattr(self, f), f)
