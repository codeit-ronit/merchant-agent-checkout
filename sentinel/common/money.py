"""Money is integer minor units, always. Never floats. Never a category error.

Razorpay represents amounts as an integer in the smallest currency subunit —
paise for INR: ₹299 is ``29900`` (verified against razorpay.com/docs, ADR-006).
We match that representation exactly so no conversion ever happens inside the
policy engine (currency conversion in a policy engine is a bug source).

Zero-decimal (JPY) and three-decimal (KWD/BHD/OMR) currencies have different
subunit exponents; we record the exponent per currency for *display only* — the
engine compares integers and never divides.
"""

from __future__ import annotations

# Minor-unit exponent per ISO 4217 currency. Display uses this; the engine does
# not. Extend as fixtures require. Unknown currency => treat as 2 for display
# only, and record it (never guess for enforcement — the engine uses raw ints).
MINOR_UNIT_EXPONENT = {
    "INR": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "JPY": 0,   # zero-decimal
    "KWD": 3,   # three-decimal
    "BHD": 3,
    "OMR": 3,
}

CURRENCY_SYMBOL = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}


def format_amount(amount_minor: int, currency: str) -> str:
    """Human-readable amount for explanations and the UI. Display only.

    ``format_amount(2450000, "INR") == "₹24,500.00"``
    """
    if not isinstance(amount_minor, int) or isinstance(amount_minor, bool):
        raise TypeError("amount must be an integer number of minor units")
    exp = MINOR_UNIT_EXPONENT.get(currency, 2)
    symbol = CURRENCY_SYMBOL.get(currency, currency + " ")
    sign = "-" if amount_minor < 0 else ""
    magnitude = abs(amount_minor)
    if exp == 0:
        whole, frac = magnitude, ""
    else:
        divisor = 10**exp
        whole, remainder = divmod(magnitude, divisor)
        frac = "." + str(remainder).rjust(exp, "0")
    # Indian grouping for INR (lakh/crore) is nice-to-have; use plain thousands
    # grouping which is unambiguous and locale-independent.
    return f"{sign}{symbol}{whole:,}{frac}"
