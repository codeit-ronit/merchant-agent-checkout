"""Canonical serialisation and hashing for the audit chain, idempotency keys,
and cassette keys.

Design (see DECISIONS.md ADR-010). This is an **RFC 8785 (JCS)-inspired** subset,
deliberately made *stricter* than the RFC for a money domain:

* **Floats are forbidden.** RFC 8785 pushes every number through an IEEE-754
  double, which silently mangles 64-bit integers and any decimal — catastrophic
  for money. We forbid ``float`` outright (enforcing the project's no-floats
  rule at the serialisation boundary) and carry money as integer minor units.
* **Large integers are forbidden as numbers.** Anything beyond ±(2**53 - 1)
  must be carried by the caller as a string, exactly as RFC 8785 recommends.
  Our identifiers are already strings (ULIDs), so this never bites in practice.
* **Object keys are ordered by UTF-16 code units**, matching JCS (not code-point
  or UTF-8 byte order — they diverge outside the BMP).
* **Compact, UTF-8, non-ASCII emitted literally**, no inter-token whitespace.

Hash: **SHA-256** (RFC 6962 / Certificate Transparency family; collision- and
preimage-resistant; ubiquitous). The tamper-evidence argument reduces to its
collision resistance. This is tamper-*evident*, not tamper-*proof* — see
LIMITATIONS.md.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

MAX_SAFE_INT = 2**53 - 1  # 9_007_199_254_740_991


class CanonicalizationError(ValueError):
    """Raised when a value cannot be canonicalised safely (e.g. a float)."""


def _utf16_key(k: str) -> bytes:
    # UTF-16 big-endian code-unit sequence == the JCS sort order.
    return k.encode("utf-16-be")


def _normalise(value: Any) -> Any:
    """Recursively produce a structure whose dicts have JCS-ordered keys and
    which contains no disallowed types. bool must be checked before int."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        # JSON true/false — fine, and distinct from int.
        return value
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INT:
            raise CanonicalizationError(
                f"integer {value} exceeds 2**53-1; carry it as a string instead"
            )
        return value
    if isinstance(value, float):
        raise CanonicalizationError(
            "floats are forbidden in canonical form (money is integer minor units)"
        )
    if isinstance(value, dict):
        keys = list(value.keys())
        if any(not isinstance(k, str) for k in keys):
            raise CanonicalizationError("object keys must be strings")
        if len(set(keys)) != len(keys):
            raise CanonicalizationError("duplicate object keys are not allowed (I-JSON)")
        ordered = {}
        for k in sorted(keys, key=_utf16_key):
            ordered[k] = _normalise(value[k])
        return ordered
    if isinstance(value, (list, tuple)):
        return [_normalise(v) for v in value]
    raise CanonicalizationError(f"type {type(value).__name__} is not canonicalisable")


def canonical_json(value: Any) -> str:
    """Return the canonical JSON string for ``value``."""
    normalised = _normalise(value)
    return json.dumps(
        normalised,
        ensure_ascii=False,        # emit non-ASCII literally, per JCS
        separators=(",", ":"),     # no inter-token whitespace
        sort_keys=False,           # ordering already applied in _normalise
        allow_nan=False,           # NaN / Infinity terminate, per JCS
    )


def canonical_bytes(value: Any) -> bytes:
    """Canonical UTF-8 byte string for hashing/signing."""
    return canonical_json(value).encode("utf-8")


def sha256_hex(value: Any) -> str:
    """SHA-256 hex digest over the canonical byte form of ``value``."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_hex_bytes(data: bytes) -> str:
    """SHA-256 hex digest over raw bytes (for cassette keys built from a string)."""
    return hashlib.sha256(data).hexdigest()


def stringify_floats(value: Any) -> Any:
    """Recursively convert floats to a fixed-precision string, so a structure
    containing timing floats (audit latencies) can be canonicalised. This is the
    RFC 8785 recommendation for non-integer numbers: carry them as strings rather
    than risk IEEE-754 round-trips changing the hash. Fixed 6-decimal precision
    makes the representation stable across runs."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return f"{value:.6f}"
    if isinstance(value, dict):
        return {k: stringify_floats(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [stringify_floats(v) for v in value]
    return value
