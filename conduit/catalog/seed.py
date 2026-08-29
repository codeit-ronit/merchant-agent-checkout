"""Seeded synthetic merchant — deterministic, reproducible, demo-shaped.

"Fresh Basket" is the merchant in every demo and eval: a home kitchen whose
menu makes "dinner for four under ₹800, no beef" a genuinely solvable — but
not trivial — constraint. Same seed, same catalog, byte for byte.

All data is synthetic. No real merchant, no real prices, no PII.
"""

from __future__ import annotations

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
from conduit.catalog.service import CatalogService

SEED_TIME_MS = 1_756_400_000_000  # fixed epoch ms; determinism over realism

MERCHANT = MerchantConfig(
    merchant_id="mrc_fresh_basket",
    display_name="Fresh Basket",
    max_upsell_offers_per_cart=1,
)


def _i(item_id: str, name: str, price_minor: int, category: str, attrs: set[str],
       description: str = "", stock: Stock = Stock.IN_STOCK, count: int | None = None,
       tax_bps: int = 500, note: str | None = None,
       constraints: Constraints | None = None) -> CatalogItem:
    return CatalogItem(
        item_id=item_id, price_minor=price_minor, currency="INR",
        availability=Availability(stock=stock, count=count),
        text=FreeText(name=name, description=description, merchant_note=note),
        tax=TaxTreatment(rate_bps=tax_bps), category=category,
        attributes=frozenset(attrs), constraints=constraints or Constraints(),
    )


ITEMS: tuple[CatalogItem, ...] = (
    _i("itm_paneer-tikka", "Paneer Tikka", 20000, "mains", {"veg"},
       "Chargrilled cottage cheese with mint chutney", note="bestseller"),
    _i("itm_dal-makhani", "Dal Makhani", 18000, "mains", {"veg"},
       "Slow-cooked black lentils, butter finish"),
    _i("itm_butter-chicken", "Butter Chicken", 32000, "mains", {"non-veg", "chicken"},
       "Tomato-butter gravy"),
    _i("itm_beef-fry", "Beef Fry", 28000, "mains", {"non-veg", "beef"},
       "Kerala-style dry fry"),
    _i("itm_veg-biryani", "Veg Biryani", 19000, "rice", {"veg"},
       "Fragrant rice with seasonal vegetables", stock=Stock.LIMITED, count=4),
    _i("itm_steamed-rice", "Steamed Rice", 9000, "rice", {"veg"}),
    _i("itm_garlic-naan", "Garlic Naan", 4000, "breads", {"veg"},
       "Tandoor flatbread with garlic butter",
       constraints=Constraints(min_quantity=1, max_per_order=12)),
    _i("itm_tandoori-roti", "Tandoori Roti", 2500, "breads", {"veg"},
       "Whole wheat tandoor bread"),
    _i("itm_gulab-jamun", "Gulab Jamun (2 pc)", 8000, "desserts", {"veg"},
       "Warm milk dumplings in syrup", tax_bps=1200, note="pairs with mains"),
    _i("itm_masala-chaas", "Masala Chaas", 5000, "beverages", {"veg"},
       "Spiced buttermilk", stock=Stock.OUT_OF_STOCK, tax_bps=1200),
    _i("itm_family-thali", "Family Thali (serves 2)", 45000, "mains", {"veg"},
       "Two mains, bread, rice, dessert",
       constraints=Constraints(min_quantity=1, max_per_order=3)),
)

UPSELL_RULES: tuple[UpsellRule, ...] = (
    # Merchant-authored: a main invites a dessert. The ONLY offers that exist.
    UpsellRule("rule_dessert_with_mains", "itm_paneer-tikka", "itm_gulab-jamun"),
    UpsellRule("rule_bread_with_dal", "itm_dal-makhani", "itm_garlic-naan"),
    UpsellRule("rule_dessert_with_rice", "itm_steamed-rice", "itm_gulab-jamun"),
)


def seed_catalog(service: CatalogService) -> int:
    """Load Fresh Basket into a catalog service. Returns the catalog version.
    Deterministic: same inputs, same order, fixed timestamp."""
    service.put_merchant(MERCHANT)
    version = service.upsert_items(list(ITEMS), now_ms=SEED_TIME_MS)
    for rule in UPSELL_RULES:
        service.put_upsell_rule(rule)
    return service.catalog_version()
