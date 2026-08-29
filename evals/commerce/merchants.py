"""Merchant fixtures for the commerce suite.

Two merchants, two provenances, on purpose (08-EVAL overfitting guard):

* **Fresh Basket** — the demo-shaped seed (`conduit.catalog.seed`), designed
  so the headline constraint works. Good demo design, dangerous eval design.
* **Spice Route** — GENERATED from a seed, not authored around any scenario.
  The generator ran first; the scenarios were authored afterwards FROM the
  generated truth (expected outcomes reasoned before any agent run). The
  generated catalog is committed to ``spice-route.json`` and a test asserts
  regeneration matches it byte-for-byte, so scenario reasoning can cite it.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from conduit.catalog.model import (
    Availability,
    CatalogItem,
    Constraints,
    FreeText,
    MerchantConfig,
    Stock,
    TaxTreatment,
    UpsellRule,
)
from conduit.catalog.seed import seed_catalog
from conduit.catalog.service import CatalogService
from conduit.catalog.store import InMemoryCatalogRepository

SPICE_SEED = 20260829
SEED_TIME_MS = 1_756_600_000_000
SPICE_JSON = Path(__file__).resolve().parent / "spice-route.json"

_NAMES = {
    "mains": ["Chettinad Chicken", "Malabar Fish Curry", "Kadai Paneer",
              "Mutton Rogan Josh", "Aloo Gobi", "Prawn Moilee"],
    "rice": ["Ghee Rice", "Lemon Rice", "Hyderabadi Veg Biryani"],
    "breads": ["Malabar Parotta", "Appam (2 pc)"],
    "desserts": ["Payasam", "Elaneer Pudding"],
    "beverages": ["Filter Coffee", "Sulaimani Tea"],
}
_ATTRS = {
    "Chettinad Chicken": {"non-veg", "chicken", "spicy"},
    "Malabar Fish Curry": {"non-veg", "seafood"},
    "Kadai Paneer": {"veg"},
    "Mutton Rogan Josh": {"non-veg", "mutton"},
    "Aloo Gobi": {"veg"},
    "Prawn Moilee": {"non-veg", "seafood"},
    "Ghee Rice": {"veg"},
    "Lemon Rice": {"veg"},
    "Hyderabadi Veg Biryani": {"veg"},
    "Malabar Parotta": {"veg"},
    "Appam (2 pc)": {"veg"},
    "Payasam": {"veg", "contains-nuts"},
    "Elaneer Pudding": {"veg"},
    "Filter Coffee": {"veg"},
    "Sulaimani Tea": {"veg"},
}
_PRICE_RANGES = {"mains": (160, 420), "rice": (90, 260), "breads": (25, 60),
                 "desserts": (60, 140), "beverages": (30, 80)}

SPICE_MERCHANT = MerchantConfig(
    merchant_id="mrc_spice_route", display_name="Spice Route",
    max_upsell_offers_per_cart=1)


def _slug(name: str) -> str:
    import re
    return "itm_" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]


def generate_spice_route() -> tuple[list[CatalogItem], list[UpsellRule]]:
    """Deterministic from SPICE_SEED. NOT shaped around any scenario: prices,
    stock states, and rules fall out of the RNG, and the scenarios were
    written afterwards against this truth."""
    rng = random.Random(SPICE_SEED)
    items: list[CatalogItem] = []
    for category, names in _NAMES.items():
        lo, hi = _PRICE_RANGES[category]
        for name in names:
            rupees = rng.randrange(lo, hi + 1)
            roll = rng.random()
            if roll < 0.12:
                availability = Availability(stock=Stock.OUT_OF_STOCK)
            elif roll < 0.30:
                availability = Availability(stock=Stock.LIMITED,
                                            count=rng.randrange(2, 6))
            else:
                availability = Availability(stock=Stock.IN_STOCK)
            items.append(CatalogItem(
                item_id=_slug(name),
                price_minor=rupees * 100,
                currency="INR",
                availability=availability,
                text=FreeText(name=name, description=f"{name} — house recipe"),
                tax=TaxTreatment(rate_bps=500 if category != "beverages" else 1200),
                category=category,
                attributes=frozenset(_ATTRS[name]),
                constraints=Constraints(),
            ))
    rules = [
        UpsellRule("rule_sr_dessert", items[0].item_id, _slug("Payasam")),
        UpsellRule("rule_sr_coffee", _slug("Ghee Rice"), _slug("Filter Coffee")),
    ]
    return items, rules


def build_catalog(merchant: str) -> CatalogService:
    service = CatalogService(InMemoryCatalogRepository())
    if merchant == "fresh_basket":
        seed_catalog(service)
        return service
    if merchant == "spice_route":
        items, rules = generate_spice_route()
        service.put_merchant(SPICE_MERCHANT)
        service.upsert_items(items, now_ms=SEED_TIME_MS)
        for rule in rules:
            service.put_upsell_rule(rule)
        return service
    raise ValueError(f"unknown merchant fixture '{merchant}'")


def merchant_id(merchant: str) -> str:
    from conduit.catalog.seed import MERCHANT
    return MERCHANT.merchant_id if merchant == "fresh_basket" else SPICE_MERCHANT.merchant_id


def dump_spice_route() -> dict:
    items, rules = generate_spice_route()
    return {
        "seed": SPICE_SEED,
        "items": [i.to_public() for i in items],
        "rules": [{"rule_id": r.rule_id, "trigger": r.trigger_item_id,
                   "offer": r.offer_item_id} for r in rules],
    }


if __name__ == "__main__":
    payload = dump_spice_route()
    SPICE_JSON.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    for item in payload["items"]:
        print(f"{item['item_id']:34s} {item['category']:10s} ₹{item['price_minor']/100:>8.2f} "
              f"{item['stock']:12s} {','.join(item['attributes'])}")
    print("rules:", payload["rules"])
