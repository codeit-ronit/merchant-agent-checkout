"""Parse merchant-supplied price strings to integer minor units — WITHOUT floats.

The parser works on the string's digits directly. ``float()`` never appears:
a float in a money path is a bug even when it currently rounds correctly
(CLAUDE.md hard rule 10; ADR-006).

Accepts what real merchant files contain: currency symbols/codes, thousands
separators (both 1,299 and Indian 1,29,900 grouping), surrounding whitespace,
a trailing ``/-``. Rejects what cannot be trusted silently: more decimals than
the currency has, scientific notation, negatives, empty strings.
"""

from __future__ import annotations

import re

from sentinel.common.money import MINOR_UNIT_EXPONENT


class PriceParseError(ValueError):
    """The string is not an unambiguous price. Message says why."""


_PREFIXES = ("₹", "rs.", "rs", "inr", "$", "usd", "€", "eur", "£", "gbp")
_CLEAN_RE = re.compile(r"^\d+(\.\d+)?$")


def parse_price_to_minor(raw: str | int, currency: str = "INR") -> int:
    """``"₹1,299.50" -> 129950``  ·  ``"299" -> 29900``  ·  ``240 -> 24000``.

    An ``int`` is accepted as whole currency units. A ``float`` is rejected
    outright — if a caller has a float, the value has already been through a
    lossy representation and must be re-sourced as a string or int.
    """
    exponent = MINOR_UNIT_EXPONENT.get(currency)
    if exponent is None:
        raise PriceParseError(f"unknown currency '{currency}'")

    if isinstance(raw, bool):
        raise PriceParseError("a boolean is not a price")
    if isinstance(raw, float):
        raise PriceParseError(
            "refusing a float price: floats are lossy in money paths. "
            "Supply the price as a string or an integer of whole units.")
    if isinstance(raw, int):
        if raw < 0:
            raise PriceParseError("price cannot be negative")
        return raw * (10 ** exponent)

    text = str(raw).strip().lower()
    if not text:
        raise PriceParseError("empty price")
    for prefix in _PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    text = text.removesuffix("/-").strip()
    text = text.replace(",", "").replace(" ", "")
    if "e" in text:
        raise PriceParseError(f"scientific notation is not a price: '{raw}'")
    if text.startswith("-"):
        raise PriceParseError("price cannot be negative")
    if not _CLEAN_RE.match(text):
        raise PriceParseError(f"cannot parse '{raw}' as a price")

    whole, _, frac = text.partition(".")
    if len(frac) > exponent:
        raise PriceParseError(
            f"'{raw}' has more decimal places than {currency} supports ({exponent})")
    frac_minor = int(frac.ljust(exponent, "0")) if exponent else 0
    if exponent == 0 and frac:
        raise PriceParseError(f"{currency} has no decimal subunit; got '{raw}'")
    return int(whole) * (10 ** exponent) + frac_minor
