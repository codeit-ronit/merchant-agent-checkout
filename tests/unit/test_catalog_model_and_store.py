"""Catalog model + store: money-position integrity, versioning, reproducibility."""

from __future__ import annotations

import pytest

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
from conduit.catalog.service import CatalogError, CatalogService, SearchQuery
from conduit.catalog.store import InMemoryCatalogRepository, SqliteCatalogRepository


def _item(item_id="itm_paneer", price=20000, **kw):
    defaults = dict(
        item_id=item_id, price_minor=price, currency="INR",
        availability=Availability(stock=Stock.IN_STOCK),
        text=FreeText(name="Paneer Tikka", description="Chargrilled cottage cheese"),
        category="mains", attributes=frozenset({"veg"}),
    )
    defaults.update(kw)
    return CatalogItem(**defaults)


# ---------------------------------------------------------------- model guards
class TestMoneyPositions:
    def test_float_price_raises(self):
        with pytest.raises(TypeError):
            _item(price=200.0)

    def test_bool_price_raises(self):
        with pytest.raises(TypeError):
            _item(price=True)

    def test_zero_and_negative_prices_rejected(self):
        for bad in (0, -100):
            with pytest.raises(ValueError):
                _item(price=bad)

    def test_float_tax_rate_raises(self):
        with pytest.raises(TypeError):
            TaxTreatment(rate_bps=5.0)

    def test_tax_rate_bounds(self):
        with pytest.raises(ValueError):
            TaxTreatment(rate_bps=10_001)

    def test_unknown_currency_rejected(self):
        with pytest.raises(ValueError):
            _item(currency="XXX")


class TestAvailability:
    def test_limited_requires_count(self):
        with pytest.raises(ValueError):
            Availability(stock=Stock.LIMITED)

    def test_count_only_for_limited(self):
        with pytest.raises(ValueError):
            Availability(stock=Stock.IN_STOCK, count=5)

    def test_purchasable_logic(self):
        assert Availability(stock=Stock.IN_STOCK).purchasable(99)
        assert not Availability(stock=Stock.OUT_OF_STOCK).purchasable(1)
        limited = Availability(stock=Stock.LIMITED, count=3)
        assert limited.purchasable(3) and not limited.purchasable(4)


class TestRules:
    def test_item_cannot_upsell_itself(self):
        with pytest.raises(ValueError):
            UpsellRule(rule_id="r1", trigger_item_id="a", offer_item_id="a")

    def test_constraints_sanity(self):
        with pytest.raises(ValueError):
            Constraints(min_quantity=0)
        with pytest.raises(ValueError):
            Constraints(min_quantity=2, max_per_order=1)


# ------------------------------------------------------------- service + store
@pytest.fixture(params=["memory", "sqlite"])
def repo(request, tmp_path):
    if request.param == "memory":
        return InMemoryCatalogRepository()
    return SqliteCatalogRepository(tmp_path / "catalog.db")


class TestVersioning:
    def test_price_change_bumps_version_and_logs(self, repo):
        svc = CatalogService(repo)
        svc.upsert_items([_item()], now_ms=1000)
        v0 = svc.catalog_version()
        updated = svc.set_price("itm_paneer", 24000, now_ms=2000)
        assert updated.price_version == 2
        assert svc.catalog_version() == v0 + 1
        (change,) = svc.price_history("itm_paneer")
        assert (change.from_minor, change.to_minor) == (20000, 24000)
        assert (change.from_version, change.to_version) == (1, 2)
        assert change.changed_at_ms == 2000

    def test_same_price_is_not_a_change(self, repo):
        svc = CatalogService(repo)
        svc.upsert_items([_item()], now_ms=1000)
        svc.set_price("itm_paneer", 20000, now_ms=2000)
        assert svc.price_history("itm_paneer") == []
        assert svc.get_item("itm_paneer").price_version == 1

    def test_upsert_of_existing_item_with_new_price_logs_change(self, repo):
        svc = CatalogService(repo)
        svc.upsert_items([_item()], now_ms=1000)
        svc.upsert_items([_item(price=25000)], now_ms=2000)
        assert svc.get_item("itm_paneer").price_version == 2
        assert len(svc.price_history("itm_paneer")) == 1

    def test_float_price_via_service_rejected(self, repo):
        svc = CatalogService(repo)
        svc.upsert_items([_item()], now_ms=1000)
        with pytest.raises(CatalogError):
            svc.set_price("itm_paneer", 240.0, now_ms=2000)


class TestReads:
    def test_phantom_item_rejected_with_actionable_message(self, repo):
        svc = CatalogService(repo)
        with pytest.raises(CatalogError, match="Search the catalog"):
            svc.get_item("itm_ghost")

    def test_search_filters(self, repo):
        svc = CatalogService(repo)
        svc.upsert_items([
            _item("itm_paneer", 20000),
            _item("itm_chicken", 30000, attributes=frozenset({"non-veg"})),
            _item("itm_naan", 4000, category="breads", attributes=frozenset(),
                  availability=Availability(stock=Stock.OUT_OF_STOCK)),
        ], now_ms=1000)
        veg = svc.search(SearchQuery(attributes=frozenset({"veg"})))
        assert [i.item_id for i in veg] == ["itm_paneer"]
        no_meat = svc.search(SearchQuery(exclude_attributes=frozenset({"non-veg"})))
        assert {i.item_id for i in no_meat} == {"itm_paneer", "itm_naan"}
        cheap = svc.search(SearchQuery(max_price_minor=5000))
        assert [i.item_id for i in cheap] == ["itm_naan"]
        in_stock = svc.search(SearchQuery(in_stock_only=True))
        assert {i.item_id for i in in_stock} == {"itm_paneer", "itm_chicken"}

    def test_feed_carries_version_and_untrusted_fields(self, repo):
        svc = CatalogService(repo)
        svc.upsert_items([_item()], now_ms=1000)
        feed = svc.bulk_feed()
        assert feed["catalog_version"] == svc.catalog_version()
        (row,) = feed["items"]
        assert row["price_minor"] == 20000 and row["name"] == "Paneer Tikka"

    def test_upsell_rule_requires_real_items(self, repo):
        svc = CatalogService(repo)
        svc.upsert_items([_item()], now_ms=1000)
        with pytest.raises(CatalogError):
            svc.put_upsell_rule(UpsellRule("r1", "itm_paneer", "itm_ghost"))

    def test_merchant_config_roundtrip(self, repo):
        svc = CatalogService(repo)
        svc.put_merchant(MerchantConfig("mrc_fresh", "Fresh Basket", 1))
        assert svc.merchant().max_upsell_offers_per_cart == 1


class TestSqlitePersistence:
    def test_survives_reopen(self, tmp_path):
        path = tmp_path / "cat.db"
        svc = CatalogService(SqliteCatalogRepository(path))
        svc.upsert_items([_item()], now_ms=1000)
        svc.set_price("itm_paneer", 24000, now_ms=2000)
        svc2 = CatalogService(SqliteCatalogRepository(path))
        assert svc2.get_item("itm_paneer").price_minor == 24000
        assert svc2.catalog_version() == svc.catalog_version()
        assert len(svc2.price_history("itm_paneer")) == 1
