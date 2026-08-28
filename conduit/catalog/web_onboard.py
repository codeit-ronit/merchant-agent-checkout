"""Storefront-URL onboarding — near-zero merchant effort where markup exists.

Many storefronts already emit schema.org/Product (JSON-LD or microdata) or
Open Graph product tags. We parse STRUCTURE ONLY — never prose. A page without
structured product markup fails clearly, naming exactly what was looked for,
because "we couldn't read your page" must be an actionable message, not a
silent empty catalog.

The parser takes an HTML string so tests run offline; fetching is a thin,
separate wrapper (``fetch_storefront``) used only at the operator's request.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser

from conduit.catalog.model import Availability, CatalogItem, FreeText, Stock
from conduit.catalog.money_parse import PriceParseError, parse_price_to_minor


class NoStructuredMarkup(Exception):
    """The page carries no machine-readable product data. Message says what
    was searched for and what the merchant can do about it."""


@dataclass(frozen=True)
class WebOnboardResult:
    items: tuple[CatalogItem, ...]
    source: str            # "json-ld" | "microdata" | "opengraph"
    skipped: tuple[str, ...]  # products present in markup but unparseable, with reasons


# ---------------------------------------------------------------- HTML walk
class _Collector(HTMLParser):
    """One pass: JSON-LD script bodies, OG meta tags, microdata itemprops."""

    def __init__(self) -> None:
        super().__init__()
        self.ld_blocks: list[str] = []
        self.og: dict[str, str] = {}
        self.micro_products: list[dict[str, str]] = []
        self._in_ld = False
        self._micro_stack: list[dict[str, str] | None] = []
        self._pending_itemprop: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_ld = True
            self.ld_blocks.append("")
            return
        if tag == "meta":
            prop = a.get("property") or a.get("name") or ""
            if prop.startswith(("og:", "product:")) and "content" in a:
                self.og[prop] = a["content"]
            # microdata via <meta itemprop=... content=...>
            if "itemprop" in a and "content" in a and self._micro_stack and self._micro_stack[-1] is not None:
                self._micro_stack[-1].setdefault(a["itemprop"], a["content"])
            return
        itemtype = a.get("itemtype", "")
        if "itemscope" in a and "schema.org/product" in itemtype.lower():
            self._micro_stack.append({})
        elif "itemscope" in a:
            self._micro_stack.append(None)  # nested non-product scope
        if "itemprop" in a and self._micro_stack and self._micro_stack[-1] is not None:
            if "content" in a:
                self._micro_stack[-1].setdefault(a["itemprop"], a["content"])
            else:
                self._pending_itemprop = a["itemprop"]

    def handle_data(self, data):
        if self._in_ld:
            self.ld_blocks[-1] += data
        elif self._pending_itemprop and self._micro_stack and self._micro_stack[-1] is not None:
            text = data.strip()
            if text:
                self._micro_stack[-1].setdefault(self._pending_itemprop, text)
                self._pending_itemprop = None

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self._in_ld = False
        # note: we do not pop microdata scopes on endtag (HTML in the wild is
        # unbalanced); products are flushed at close().

    def products_from_microdata(self) -> list[dict[str, str]]:
        return [p for p in self._micro_stack if p]


# ---------------------------------------------------------------- extraction
def _slug(name: str) -> str:
    return "itm_" + re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")[:40]


def _availability_from_schema(value: str | None) -> Availability:
    v = (value or "").lower()
    if "outofstock" in v or "soldout" in v or "discontinued" in v:
        return Availability(stock=Stock.OUT_OF_STOCK)
    if "limitedavailability" in v:
        return Availability(stock=Stock.LIMITED, count=1)
    return Availability(stock=Stock.IN_STOCK)


def _item_from_fields(name: str, price_raw: str, currency: str,
                      description: str, availability_raw: str | None,
                      category: str, sku: str | None) -> CatalogItem:
    price_minor = parse_price_to_minor(price_raw, currency or "INR")
    return CatalogItem(
        item_id=sku or _slug(name),
        price_minor=price_minor,
        currency=currency or "INR",
        availability=_availability_from_schema(availability_raw),
        category=(category or "").lower(),
        text=FreeText(name=name, description=description or ""),
    )


def _walk_ld(node) -> list[dict]:
    """Find every @type: Product node, including inside @graph / ItemList."""
    found: list[dict] = []
    if isinstance(node, list):
        for child in node:
            found.extend(_walk_ld(child))
    elif isinstance(node, dict):
        node_type = node.get("@type", "")
        types = node_type if isinstance(node_type, list) else [node_type]
        if any(str(t).lower() == "product" for t in types):
            found.append(node)
        for key in ("@graph", "itemListElement", "item"):
            if key in node:
                found.extend(_walk_ld(node[key]))
    return found


def _from_json_ld(blocks: list[str]) -> tuple[list[CatalogItem], list[str]]:
    items: list[CatalogItem] = []
    skipped: list[str] = []
    for block in blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            skipped.append("a ld+json block was not valid JSON")
            continue
        for product in _walk_ld(data):
            name = str(product.get("name") or "").strip()
            offers = product.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = offers.get("price", offers.get("lowPrice"))
            if not name or price is None:
                skipped.append(f"product '{name or '?'}': missing name or offers.price")
                continue
            try:
                items.append(_item_from_fields(
                    name=name, price_raw=str(price),
                    currency=str(offers.get("priceCurrency") or "INR"),
                    description=str(product.get("description") or ""),
                    availability_raw=str(offers.get("availability") or ""),
                    category=str(product.get("category") or ""),
                    sku=(str(product["sku"]) if product.get("sku") else None)))
            except (PriceParseError, TypeError, ValueError) as exc:
                skipped.append(f"product '{name}': {exc}")
    return items, skipped


def parse_storefront_html(html: str) -> WebOnboardResult:
    collector = _Collector()
    collector.feed(html)
    collector.close()

    items, skipped = _from_json_ld(collector.ld_blocks)
    if items:
        return WebOnboardResult(tuple(items), "json-ld", tuple(skipped))

    micro_items: list[CatalogItem] = []
    for product in collector.products_from_microdata():
        name = product.get("name", "").strip()
        price = product.get("price")
        if not name or not price:
            skipped.append(f"microdata product '{name or '?'}': missing name or price")
            continue
        try:
            micro_items.append(_item_from_fields(
                name=name, price_raw=price,
                currency=product.get("priceCurrency", "INR"),
                description=product.get("description", ""),
                availability_raw=product.get("availability"),
                category=product.get("category", ""), sku=product.get("sku")))
        except (PriceParseError, TypeError, ValueError) as exc:
            skipped.append(f"microdata product '{name}': {exc}")
    if micro_items:
        return WebOnboardResult(tuple(micro_items), "microdata", tuple(skipped))

    og = collector.og
    og_name = og.get("og:title")
    og_price = og.get("product:price:amount") or og.get("og:price:amount")
    if og_name and og_price:
        try:
            item = _item_from_fields(
                name=og_name, price_raw=og_price,
                currency=og.get("product:price:currency") or og.get("og:price:currency") or "INR",
                description=og.get("og:description", ""),
                availability_raw=og.get("product:availability"),
                category="", sku=None)
            return WebOnboardResult((item,), "opengraph", tuple(skipped))
        except (PriceParseError, TypeError, ValueError) as exc:
            skipped.append(f"opengraph product '{og_name}': {exc}")

    raise NoStructuredMarkup(
        "No machine-readable product data found. Looked for, in order: "
        "schema.org/Product in JSON-LD (<script type=\"application/ld+json\">), "
        "schema.org/Product microdata (itemscope/itemprop), and Open Graph "
        "product tags (og:title + product:price:amount). "
        + (f"Markup was present but unusable: {list(skipped)}. " if skipped else "")
        + "The CSV upload path works for any store regardless of markup.")


def fetch_storefront(url: str, *, timeout_s: int = 10) -> str:
    """Thin fetch wrapper, used only at operator request. Kept apart from the
    parser so everything above is testable offline."""
    from urllib.request import Request, urlopen

    req = Request(url, headers={"User-Agent": "conduit-catalog-onboarding/1.0"})
    with urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 — operator-supplied URL
        return resp.read().decode("utf-8", errors="replace")
