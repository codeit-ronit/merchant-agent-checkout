"""Money formatting (ADR-006) and time-ordered IDs."""

from __future__ import annotations

import pytest

from sentinel.common.ids import PREFIXES, IdFactory, deterministic_factory
from sentinel.common.money import format_amount

pytestmark = pytest.mark.tier1


def test_inr_formatting():
    assert format_amount(2450000, "INR") == "₹24,500.00"
    assert format_amount(29900, "INR") == "₹299.00"
    assert format_amount(0, "INR") == "₹0.00"


def test_zero_and_three_decimal_currencies():
    assert format_amount(295, "JPY") == "¥295"        # zero-decimal
    assert format_amount(295990, "KWD") == "KWD 295.990"  # three-decimal


def test_negative_amounts():
    assert format_amount(-10000, "INR") == "-₹100.00"


def test_float_amount_rejected():
    with pytest.raises(TypeError):
        format_amount(1.5, "INR")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        format_amount(True, "INR")  # bool is not an amount


def test_ids_are_prefixed_and_typed():
    f = IdFactory()
    assert f.run().startswith("run_")
    assert f.step().startswith("step_")
    assert f.call().startswith("call_")
    assert f.approval().startswith("appr_")


def test_ids_are_time_sortable():
    f = IdFactory()
    ids = [f.run() for _ in range(50)]
    # ULID prefix makes lexicographic order == chronological order
    assert ids == sorted(ids)


def test_deterministic_factory_is_reproducible():
    a = deterministic_factory(seed=7)
    b = deterministic_factory(seed=7)
    assert [a.run() for _ in range(5)] == [b.run() for _ in range(5)]


def test_all_prefixes_registered():
    for kind in PREFIXES:
        assert IdFactory().new(kind)
