"""Format-valid, checksum-INVALID synthetic Indian financial identifiers.

Every generator here produces a value that matches the real format regex but is
guaranteed *not* to be a real identifier, so no synthetic value can collide with
a live one (ADR-007). Two techniques, per the research:

* **Checksummed types** (Aadhaar/Verhoeff, GSTIN/Luhn-mod-36, card/Luhn-mod-10):
  compute the correct check character, then emit ``(correct + 1)`` — guaranteed
  to fail validation.
* **Checksum-free types** (IFSC, VPA, UTR, mobile, bank account): structural
  reservation — an unallocated bank code ``ZZZZ``, a non-existent VPA handle
  ``@invalid``, an impossible Julian day ``999``, reserved sentinel bodies.

The check-digit algorithms are pure functions with both a validator and a
generator, so a test can assert (a) the correct value passes and (b) the emitted
synthetic value fails.

Note on Aadhaar: it is generated only to exercise the *detector*; SENTINEL never
stores or emits an Aadhaar value on any surface (Aadhaar Act sensitivity).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Luhn (mod 10) — card PANs
# ---------------------------------------------------------------------------

def luhn_check_digit(number_without_check: str) -> int:
    """The check digit that makes ``number_without_check + d`` Luhn-valid."""
    total = 0
    # Rightmost digit of the full number will be the check digit (position 0),
    # so the last digit of number_without_check is doubled.
    for i, ch in enumerate(reversed(number_without_check)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - (total % 10)) % 10


def luhn_valid(number: str) -> bool:
    if not number.isdigit() or len(number) < 2:
        return False
    return luhn_check_digit(number[:-1]) == int(number[-1])


# ---------------------------------------------------------------------------
# Luhn mod 36 — GSTIN
# ---------------------------------------------------------------------------
_MOD36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_MOD36_INDEX = {c: i for i, c in enumerate(_MOD36)}


def gstin_check_char(first14: str) -> str:
    """GSTIN check character: Luhn mod 36 over the first 14 characters."""
    factor, total = 1, 0
    for ch in first14:
        code = _MOD36_INDEX[ch]
        addend = factor * code
        factor = 1 if factor == 2 else 2
        addend = (addend // 36) + (addend % 36)
        total += addend
    remainder = total % 36
    check_code = (36 - remainder) % 36
    return _MOD36[check_code]


def gstin_valid(gstin: str) -> bool:
    if len(gstin) != 15:
        return False
    return gstin_check_char(gstin[:14]) == gstin[14]


# ---------------------------------------------------------------------------
# Verhoeff — Aadhaar
# ---------------------------------------------------------------------------
_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]
_VERHOEFF_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff_check_digit(number_without_check: str) -> int:
    c = 0
    digits = [int(d) for d in reversed(number_without_check)]
    for i, d in enumerate(digits):
        c = _VERHOEFF_D[c][_VERHOEFF_P[(i + 1) % 8][d]]
    return _VERHOEFF_INV[c]


def verhoeff_valid(number: str) -> bool:
    if not number.isdigit():
        return False
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


# ---------------------------------------------------------------------------
# Seeded synthetic generators (deterministic; no global randomness)
# ---------------------------------------------------------------------------
class Rng:
    """A tiny deterministic PRNG (xorshift64) so fixture generation is byte-
    identical from a seed and never touches the global ``random`` module."""

    def __init__(self, seed: int):
        self.state = (seed ^ 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF or 1

    def _next(self) -> int:
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFFFFFFFFFF
        x ^= x >> 7
        x ^= (x << 17) & 0xFFFFFFFFFFFFFFFF
        self.state = x
        return x

    def randint(self, lo: int, hi: int) -> int:
        return lo + self._next() % (hi - lo + 1)

    def choice(self, seq):
        return seq[self._next() % len(seq)]

    def digits(self, n: int) -> str:
        return "".join(str(self.randint(0, 9)) for _ in range(n))

    def letters(self, n: int) -> str:
        return "".join(chr(ord("A") + self.randint(0, 25)) for _ in range(n))


_ALPHANUM = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gen_pan(rng: Rng) -> str:
    """PAN with the 4th char = 'X' (not a valid holder-type), so structurally
    impossible while matching [A-Z]{5}[0-9]{4}[A-Z]."""
    return rng.letters(3) + "X" + rng.letters(1) + rng.digits(4) + rng.letters(1)


def gen_card(rng: Rng, bin6: str = "411111") -> str:
    """16-digit card with a deliberately wrong Luhn check digit."""
    body = bin6 + rng.digits(9)
    correct = luhn_check_digit(body)
    wrong = (correct + 1) % 10
    return body + str(wrong)


def gen_gstin(rng: Rng) -> str:
    """15-char GSTIN embedding a reserved PAN, with a wrong Luhn-mod-36 check."""
    state = f"{rng.randint(1, 38):02d}"
    pan = gen_pan(rng)                     # already structurally reserved
    entity = str(rng.randint(1, 9))
    first14 = state + pan + entity + "Z"
    correct = gstin_check_char(first14)
    idx = (_MOD36_INDEX[correct] + 1) % 36
    return first14 + _MOD36[idx]


def gen_aadhaar(rng: Rng) -> str:
    """12-digit Aadhaar (leading 2-9) with a deliberately wrong Verhoeff digit.
    Generated ONLY to test the detector; never emitted on any surface."""
    first11 = str(rng.randint(2, 9)) + rng.digits(10)
    correct = verhoeff_check_digit(first11)
    wrong = (correct + 1) % 10
    return first11 + str(wrong)


def gen_ifsc(rng: Rng) -> str:
    """IFSC with reserved bank code ZZZZ (unallocated); char 5 stays '0'."""
    return "ZZZZ0" + "".join(rng.choice(_ALPHANUM) for _ in range(6))


def gen_bank_account(rng: Rng) -> str:
    """Reserved sentinel account: leading 0000 block no issuer uses."""
    return "0000" + rng.digits(rng.randint(8, 12))


def gen_vpa(rng: Rng, name: str | None = None) -> str:
    """VPA on the non-existent handle @invalid (resolves to nobody)."""
    local = (name or ("user" + rng.digits(4))).lower().replace(" ", ".")
    return f"{local}@invalid"


def gen_mobile(rng: Rng) -> str:
    """Indian mobile [6-9]xxxxxxxxx with a reserved fake body."""
    lead = rng.choice("6789")
    return lead + "9999" + rng.digits(5)


def gen_utr_neft(rng: Rng) -> str:
    """16-char NEFT UTR with reserved bank code ZZZZ and impossible Julian 999."""
    year = f"{rng.randint(20, 26):02d}"
    serial = rng.digits(6)
    return "ZZZZN" + year + "999" + serial


def gen_utr_upi(rng: Rng) -> str:
    """12-digit UPI RRN with a reserved 000000 lead switch-assigned RRNs avoid."""
    return "000000" + rng.digits(6)
