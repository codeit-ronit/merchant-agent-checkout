"""CSV onboarding — the path every merchant already has.

Two-step by design, because merchant effort is a measured outcome and silent
guessing is how wrong prices enter a catalog:

1. ``infer_mapping(headers)`` proposes column → field assignments with a
   per-column confidence. The merchant confirms or corrects — the one human
   step, and it is counted.
2. ``onboard_csv(text, mapping)`` parses rows into ``CatalogItem``s. A row
   that cannot be parsed unambiguously is SKIPPED WITH A NAMED REASON, never
   silently coerced — the skip list is part of the result, and honesty about
   messy input is part of the metric.

Effort is measured, not asserted: the result carries rows seen/parsed/skipped
and the fraction of columns that were auto-mapped.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from conduit.catalog.model import (
    Availability,
    CatalogItem,
    FreeText,
    Stock,
    TaxTreatment,
)
from conduit.catalog.money_parse import PriceParseError, parse_price_to_minor

# Canonical fields a CSV column can map to.
FIELDS = ("name", "price", "description", "category", "stock", "attributes",
          "tax_rate", "item_id", "merchant_note")

# Header aliases seen in real merchant exports. Matching is case/space/punct-insensitive.
_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "item", "item name", "product", "product name", "title", "dish"),
    "price": ("price", "mrp", "rate", "amount", "cost", "price inr", "price rs", "selling price", "unit price"),
    "description": ("description", "desc", "details", "about"),
    "category": ("category", "cat", "type", "section", "group"),
    "stock": ("stock", "availability", "in stock", "available", "qty", "quantity", "inventory"),
    "attributes": ("attributes", "tags", "diet", "dietary", "veg/nonveg", "veg nonveg", "labels"),
    "tax_rate": ("tax", "tax rate", "gst", "gst %", "tax %", "gst rate"),
    "item_id": ("id", "item id", "sku", "code", "product id"),
    "merchant_note": ("note", "notes", "merchant note", "remarks", "comment"),
}


def _norm(header: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", header.strip().lower()).strip()


@dataclass(frozen=True)
class MappingProposal:
    """Column-to-field proposal for the merchant to confirm."""

    mapping: dict[str, str]          # csv header -> canonical field
    unmapped: tuple[str, ...]        # headers we could not place
    auto_mapped_fraction: float      # display-only metric; never a money value

    def confirmed(self, corrections: dict[str, str] | None = None) -> dict[str, str]:
        """The merchant's one step: accept, optionally correcting columns."""
        final = dict(self.mapping)
        for header, fld in (corrections or {}).items():
            if fld not in FIELDS:
                raise ValueError(f"unknown field '{fld}'; valid: {FIELDS}")
            final[header] = fld
        return final


def infer_mapping(headers: list[str]) -> MappingProposal:
    mapping: dict[str, str] = {}
    unmapped: list[str] = []
    taken: set[str] = set()
    for header in headers:
        n = _norm(header)
        hit = None
        for fld, aliases in _ALIASES.items():
            if fld in taken:
                continue
            if n in (_norm(a) for a in aliases):
                hit = fld
                break
        if hit is None:  # substring fallback, first-alias-wins, still explicit
            for fld, aliases in _ALIASES.items():
                if fld in taken:
                    continue
                if any(_norm(a) in n or n in _norm(a) for a in aliases if len(n) >= 3):
                    hit = fld
                    break
        if hit:
            mapping[header] = hit
            taken.add(hit)
        else:
            unmapped.append(header)
    fraction = len(mapping) / len(headers) if headers else 0.0
    return MappingProposal(mapping=mapping, unmapped=tuple(unmapped),
                           auto_mapped_fraction=fraction)


@dataclass(frozen=True)
class SkippedRow:
    row_number: int   # 1-based, excluding the header row
    reason: str


@dataclass(frozen=True)
class OnboardResult:
    items: tuple[CatalogItem, ...]
    skipped: tuple[SkippedRow, ...]
    rows_seen: int
    auto_mapped_fraction: float
    steps: tuple[str, ...] = field(default=(
        "upload CSV", "confirm column mapping", "review skipped rows"))


_STOCK_WORDS_IN = ("y", "yes", "true", "in stock", "instock", "available", "1")
_STOCK_WORDS_OUT = ("n", "no", "false", "out of stock", "outofstock", "unavailable", "0", "")


def _parse_stock(value: str) -> Availability:
    v = value.strip().lower()
    if v in _STOCK_WORDS_IN:
        return Availability(stock=Stock.IN_STOCK)
    if v in _STOCK_WORDS_OUT:
        return Availability(stock=Stock.OUT_OF_STOCK)
    if v.isdigit():
        n = int(v)
        return (Availability(stock=Stock.LIMITED, count=n) if n
                else Availability(stock=Stock.OUT_OF_STOCK))
    raise ValueError(f"cannot read stock value '{value}'")


def _parse_tax_bps(value: str) -> int:
    v = value.strip().rstrip("%").strip()
    if not v:
        return 0
    whole, _, frac = v.partition(".")
    if not whole.isdigit() or (frac and not frac.isdigit()) or len(frac) > 2:
        raise ValueError(f"cannot read tax rate '{value}'")
    return int(whole) * 100 + (int(frac.ljust(2, "0")) if frac else 0)


def _slug(name: str) -> str:
    return "itm_" + re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")[:40]


def onboard_csv(text: str, mapping: dict[str, str], *, currency: str = "INR") -> OnboardResult:
    """Parse a merchant CSV with a CONFIRMED mapping into catalog items.

    Never coerces ambiguity: a bad price, unreadable stock, or missing name
    skips the row with a reason. Duplicate ids within the file are a skip,
    not an overwrite.
    """
    if "name" not in mapping.values() or "price" not in mapping.values():
        raise ValueError("mapping must cover at least 'name' and 'price'")

    reader = csv.DictReader(io.StringIO(text))
    items: list[CatalogItem] = []
    skipped: list[SkippedRow] = []
    seen_ids: set[str] = set()
    rows_seen = 0

    for row_number, row in enumerate(reader, start=1):
        rows_seen += 1
        get = lambda fld: next(
            (str(row.get(h) or "").strip() for h, f in mapping.items() if f == fld), "")
        name = get("name")
        if not name:
            skipped.append(SkippedRow(row_number, "no item name"))
            continue
        try:
            price_minor = parse_price_to_minor(get("price"), currency)
        except PriceParseError as exc:
            skipped.append(SkippedRow(row_number, f"price: {exc}"))
            continue
        try:
            availability = _parse_stock(get("stock")) if get("stock") else Availability(stock=Stock.IN_STOCK)
            tax = TaxTreatment(rate_bps=_parse_tax_bps(get("tax_rate"))) if get("tax_rate") else TaxTreatment()
        except ValueError as exc:
            skipped.append(SkippedRow(row_number, str(exc)))
            continue
        item_id = get("item_id") or _slug(name)
        if item_id in seen_ids:
            skipped.append(SkippedRow(row_number, f"duplicate item id '{item_id}'"))
            continue
        seen_ids.add(item_id)
        attributes = frozenset(
            a.strip().lower() for a in re.split(r"[|;,/]", get("attributes")) if a.strip())
        try:
            items.append(CatalogItem(
                item_id=item_id, price_minor=price_minor, currency=currency,
                availability=availability, tax=tax,
                category=get("category").lower(), attributes=attributes,
                text=FreeText(name=name, description=get("description"),
                              merchant_note=get("merchant_note") or None),
            ))
        except (TypeError, ValueError) as exc:
            skipped.append(SkippedRow(row_number, str(exc)))

    mapped_headers = len(mapping)
    total_headers = len(reader.fieldnames or []) or mapped_headers
    return OnboardResult(
        items=tuple(items), skipped=tuple(skipped), rows_seen=rows_seen,
        auto_mapped_fraction=mapped_headers / total_headers if total_headers else 0.0)
