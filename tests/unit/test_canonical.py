"""Canonical serialisation + hashing (ADR-010)."""

from __future__ import annotations

import pytest

from sentinel.common.canonical import (
    CanonicalizationError,
    canonical_json,
    sha256_hex,
)

pytestmark = pytest.mark.tier1


def test_key_ordering_is_stable_regardless_of_insertion_order():
    a = canonical_json({"b": 1, "a": 2, "c": {"z": 1, "y": 2}})
    b = canonical_json({"c": {"y": 2, "z": 1}, "a": 2, "b": 1})
    assert a == b == '{"a":2,"b":1,"c":{"y":2,"z":1}}'


def test_floats_forbidden():
    with pytest.raises(CanonicalizationError):
        canonical_json({"amount": 1.5})
    with pytest.raises(CanonicalizationError):
        canonical_json([1, 2, 3.0])


def test_large_int_forbidden_as_number():
    with pytest.raises(CanonicalizationError):
        canonical_json({"id": 2**53})
    # boundary is allowed
    assert canonical_json({"id": 2**53 - 1})


def test_bool_distinct_from_int():
    assert canonical_json({"x": True}) == '{"x":true}'
    assert canonical_json({"x": 1}) == '{"x":1}'


def test_non_ascii_emitted_literally():
    assert canonical_json({"sym": "₹"}) == '{"sym":"₹"}'


def test_duplicate_keys_impossible_by_construction():
    # Python dicts cannot hold duplicate keys; assert nested dict handling anyway.
    assert canonical_json({"a": {"a": 1}}) == '{"a":{"a":1}}'


def test_sha256_deterministic_and_order_independent():
    h1 = sha256_hex({"b": 1, "a": 2})
    h2 = sha256_hex({"a": 2, "b": 1})
    assert h1 == h2
    assert len(h1) == 64


def test_sha256_changes_on_any_edit():
    base = sha256_hex({"amount": 2450000, "payment_id": "pay_ABC"})
    changed = sha256_hex({"amount": 2450001, "payment_id": "pay_ABC"})
    assert base != changed
