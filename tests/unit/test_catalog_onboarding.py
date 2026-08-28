"""Onboarding paths: float-free money parsing, messy CSV, storefront markup,
seed reproducibility. These tests run on the committed fixtures — the same
files the demo uses — so 'works on messy input' is proven, not curated."""

from __future__ import annotations

from pathlib import Path

import pytest

from conduit.catalog.csv_onboard import infer_mapping, onboard_csv
from conduit.catalog.model import Stock
from conduit.catalog.money_parse import PriceParseError, parse_price_to_minor
from conduit.catalog.seed import ITEMS, seed_catalog
from conduit.catalog.service import CatalogService
from conduit.catalog.store import InMemoryCatalogRepository
from conduit.catalog.web_onboard import (
    NoStructuredMarkup,
    parse_storefront_html,
)

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures" / "merchant"


# ---------------------------------------------------------------- money parse
class TestPriceParsing:
    @pytest.mark.parametrize("raw,expected", [
        ("299", 29900),
        ("₹200.00", 20000),
        ("Rs. 1,299.50", 129950),
        ("INR 40", 4000),
        ("40/-", 4000),
        ("  180 ", 18000),
        ("1,29,900", 12990000),   # Indian grouping
        ("0.50", 50),
        (240, 24000),             # int = whole units
    ])
    def test_parses_to_minor_units(self, raw, expected):
        assert parse_price_to_minor(raw) == expected

    @pytest.mark.parametrize("bad", [
        "", "  ", "12.345", "1e3", "-40", -40, "about 200", "200 or 250", True,
    ])
    def test_rejects_ambiguity(self, bad):
        with pytest.raises(PriceParseError):
            parse_price_to_minor(bad)

    def test_rejects_float_outright(self):
        with pytest.raises(PriceParseError, match="float"):
            parse_price_to_minor(200.0)

    def test_zero_decimal_currency(self):
        assert parse_price_to_minor("500", "JPY") == 500
        with pytest.raises(PriceParseError):
            parse_price_to_minor("500.5", "JPY")


# ------------------------------------------------------------------ CSV path
class TestCsvOnboarding:
    def test_mapping_inference_on_real_headers(self):
        text = (FIXTURES / "fresh-basket.csv").read_text()
        headers = text.splitlines()[0].split(",")
        proposal = infer_mapping(headers)
        assert proposal.mapping["Item Name"] == "name"
        assert proposal.mapping["MRP (Rs.)"] == "price"
        assert proposal.mapping["Veg/NonVeg"] == "attributes"
        assert proposal.mapping["GST %"] == "tax_rate"
        assert proposal.mapping["Qty"] == "stock"
        assert proposal.auto_mapped_fraction >= 0.8  # effort metric: measured

    def test_messy_fixture_parses_with_named_skips(self):
        text = (FIXTURES / "fresh-basket.csv").read_text()
        mapping = infer_mapping(text.splitlines()[0].split(",")).confirmed()
        result = onboard_csv(text, mapping)

        assert result.rows_seen == 13
        parsed = {i.item_id for i in result.items}
        assert "itm_paneer-tikka" in parsed and "itm_garlic-naan" in parsed
        # every skip carries a reason a merchant can act on
        reasons = {s.row_number: s.reason for s in result.skipped}
        assert 3 in reasons and "price" in reasons[3]          # prose price
        assert 11 in reasons and "duplicate" in reasons[11]    # re-export dupe
        assert 12 in reasons and "name" in reasons[12]         # nameless row
        assert 13 in reasons and "price" in reasons[13]        # priceless row
        assert len(result.items) + len(result.skipped) == result.rows_seen

    def test_prices_are_integer_minor_units(self):
        text = (FIXTURES / "fresh-basket.csv").read_text()
        mapping = infer_mapping(text.splitlines()[0].split(",")).confirmed()
        for item in onboard_csv(text, mapping).items:
            assert isinstance(item.price_minor, int)
        by_id = {i.item_id: i for i in onboard_csv(text, mapping).items}
        assert by_id["itm_paneer-tikka"].price_minor == 20000
        assert by_id["itm_veg-biryani"].price_minor == 19000   # "₹1,90"
        assert by_id["itm_garlic-naan"].price_minor == 4000    # "40/-"

    def test_stock_words_and_counts(self):
        text = (FIXTURES / "fresh-basket.csv").read_text()
        mapping = infer_mapping(text.splitlines()[0].split(",")).confirmed()
        by_id = {i.item_id: i for i in onboard_csv(text, mapping).items}
        assert by_id["itm_paneer-tikka"].availability.stock is Stock.LIMITED
        assert by_id["itm_paneer-tikka"].availability.count == 25
        assert by_id["itm_dal-makhani"].availability.stock is Stock.IN_STOCK
        assert by_id["itm_masala-chaas"].availability.stock is Stock.OUT_OF_STOCK

    def test_mapping_corrections_are_validated(self):
        proposal = infer_mapping(["Item Name", "MRP (Rs.)"])
        with pytest.raises(ValueError, match="unknown field"):
            proposal.confirmed({"Item Name": "not_a_field"})

    def test_mapping_must_cover_name_and_price(self):
        with pytest.raises(ValueError, match="name.*price|price.*name"):
            onboard_csv("a,b\n1,2\n", {"a": "description"})


# ----------------------------------------------------------- storefront path
class TestWebOnboarding:
    def test_json_ld_fixture_parses(self):
        html = (FIXTURES / "fresh-basket.html").read_text()
        result = parse_storefront_html(html)
        assert result.source == "json-ld"
        by_id = {i.item_id: i for i in result.items}
        assert by_id["itm_paneer-tikka"].price_minor == 20000
        assert by_id["itm_gulab-jamun"].availability.stock is Stock.LIMITED
        (skip,) = result.skipped
        assert "Mystery Special" in skip and "price" in skip

    def test_microdata_fallback(self):
        html = """
        <div itemscope itemtype="https://schema.org/Product">
          <span itemprop="name">Masala Chaas</span>
          <meta itemprop="price" content="50">
          <meta itemprop="priceCurrency" content="INR">
        </div>"""
        result = parse_storefront_html(html)
        assert result.source == "microdata"
        assert result.items[0].price_minor == 5000

    def test_opengraph_fallback(self):
        html = """
        <meta property="og:title" content="Family Thali">
        <meta property="product:price:amount" content="450.00">
        <meta property="product:price:currency" content="INR">"""
        result = parse_storefront_html(html)
        assert result.source == "opengraph"
        assert result.items[0].price_minor == 45000

    def test_absence_fails_clearly_and_names_the_alternatives(self):
        with pytest.raises(NoStructuredMarkup, match="JSON-LD.*microdata.*Open Graph|schema.org"):
            parse_storefront_html("<html><body><h1>Menu</h1><p>Paneer ₹200</p></body></html>")


# -------------------------------------------------------------------- seeding
class TestSeed:
    def test_seed_is_reproducible(self):
        a, b = CatalogService(InMemoryCatalogRepository()), CatalogService(InMemoryCatalogRepository())
        assert seed_catalog(a) == seed_catalog(b)
        assert a.bulk_feed() == b.bulk_feed()

    def test_seed_supports_the_demo_constraint(self):
        """'Dinner for four under ₹800, no beef' must be solvable but not trivial."""
        svc = CatalogService(InMemoryCatalogRepository())
        seed_catalog(svc)
        from conduit.catalog.service import SearchQuery
        no_beef = svc.search(SearchQuery(exclude_attributes=frozenset({"beef"}), in_stock_only=True))
        assert any(i.attributes >= {"beef"} for i in ITEMS)          # something to exclude
        cheapest_dinner = sorted(i.price_minor for i in no_beef)[:4]
        assert sum(cheapest_dinner) < 80000                          # solvable under ₹800
