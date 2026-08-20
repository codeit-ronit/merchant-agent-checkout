"""Synthetic identifier generation (ADR-007): correct values validate, generated
values are guaranteed checksum-invalid, formats match, generation is
deterministic. A Phase-1 exit criterion: no generated identifier passes real
checksum validation."""

from __future__ import annotations

import re

import pytest

from sentinel.fixtures import identifiers as idg

pytestmark = pytest.mark.tier1


def test_luhn_correct_and_break():
    assert idg.luhn_valid("4111111111111111")           # real test card is Luhn-valid
    assert not idg.luhn_valid("4111111111111112")        # +1 breaks it
    for seed in range(20):
        assert not idg.luhn_valid(idg.gen_card(idg.Rng(seed)))


def test_verhoeff_correct_and_break():
    base = "23456789012"
    good = base + str(idg.verhoeff_check_digit(base))
    assert idg.verhoeff_valid(good)
    for seed in range(20):
        assert not idg.verhoeff_valid(idg.gen_aadhaar(idg.Rng(seed)))


def test_gstin_correct_and_break():
    assert idg.gstin_valid("27AAPFU0939F1ZV")            # widely-cited valid example
    for seed in range(20):
        g = idg.gen_gstin(idg.Rng(seed))
        assert len(g) == 15
        assert not idg.gstin_valid(g)


@pytest.mark.critical
def test_no_generated_identifier_passes_real_validation():
    """The safety guarantee: nothing the generator emits can be a real ID."""
    for seed in range(50):
        r = idg.Rng(seed)
        assert not idg.luhn_valid(idg.gen_card(r))
        assert not idg.verhoeff_valid(idg.gen_aadhaar(r))
        assert not idg.gstin_valid(idg.gen_gstin(r))
        assert idg.gen_ifsc(r).startswith("ZZZZ0")       # unallocated bank code
        assert idg.gen_vpa(r).endswith("@invalid")       # non-existent handle
        assert "999" in idg.gen_utr_neft(r)              # impossible Julian day


def test_formats_match_regex():
    r = idg.Rng(3)
    assert re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", idg.gen_pan(r))
    assert re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", idg.gen_ifsc(r))
    assert re.fullmatch(r"[6-9][0-9]{9}", idg.gen_mobile(r))
    assert re.fullmatch(r"[0-9]{16}", idg.gen_card(r))


def test_pan_holder_type_is_reserved_invalid():
    for seed in range(20):
        assert idg.gen_pan(idg.Rng(seed))[3] == "X"      # X is not a valid holder type


def test_generation_is_deterministic():
    a = [idg.gen_card(idg.Rng(9)) for _ in range(5)]
    b = [idg.gen_card(idg.Rng(9)) for _ in range(5)]
    assert a == b
