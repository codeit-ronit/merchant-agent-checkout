"""PII detection — two stages, both required (docs/spec/05 A3).

* **Structural** (primary): the tool's ``pii_map`` in ``ToolDescriptor`` names
  which output fields carry which PII type. Precise and cheap.
* **Pattern** (safety net): regex + format for free-text fields where PII appears
  unpredictably. We track how often the pattern layer fires on a field the
  structural layer thought clean — that count is the schema-annotation debt.

Detectors key on the *format regex*, not the checksum: an attacker-supplied real
value will not be conveniently checksum-broken, so we must catch it by shape.
Object identifiers (pay_, setl_, fa_) and UTRs are NOT PII — a UTR is a
transaction reference the reconciliation agent must match on, so it is left
visible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Ordered most-specific first so overlapping matches resolve sensibly.
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("VPA", re.compile(r"\b[A-Za-z0-9.\-]{2,}@(?:invalid|ok\w+|ybl|paytm|upi|axl|ibl|apl)\b")),
    ("IFSC", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ("GSTIN", re.compile(r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    ("AADHAAR", re.compile(r"\b[2-9][0-9]{11}\b")),
    ("PAN_CARD", re.compile(r"\b[0-9]{13,19}\b")),
    ("PHONE", re.compile(r"\b[6-9][0-9]{9}\b")),
]

# PII types the structural map may declare (kept aligned with PATTERNS labels).
PII_PREFIX = {
    "PAN_CARD": "CARD", "BANK_ACCOUNT": "ACCT", "IFSC": "IFSC", "VPA": "VPA",
    "PHONE": "PHONE", "EMAIL": "EMAIL", "NAME": "NAME", "AADHAAR": "AADHAAR",
    "PAN": "PAN", "GSTIN": "GSTIN",
}


@dataclass
class Detection:
    field_path: str          # where it was found ("" for a pattern hit in unknown text)
    value: str
    pii_type: str
    via: str                 # "structural" | "pattern"


def _resolve_paths(obj: Any, path: str) -> list[tuple[list, Any]]:
    """Resolve a dotted/`items[]` path to a list of (container_trail, value).
    Returns the *parent container + key* so the caller can rewrite in place."""
    results: list[tuple[list, Any]] = []

    def walk(node: Any, parts: list[str], trail: list):
        if not parts:
            results.append((trail, node))
            return
        head, rest = parts[0], parts[1:]
        if head.endswith("[]"):
            key = head[:-2]
            seq = node.get(key) if isinstance(node, dict) else None
            if isinstance(seq, list):
                for i, elem in enumerate(seq):
                    walk(elem, rest, trail + [(seq, i)])
        else:
            if isinstance(node, dict) and head in node:
                walk(node[head], rest, trail + [(node, head)])

    walk(obj, path.split("."), [])
    return results


def structural_detect(result: dict, pii_map) -> list[Detection]:
    found: list[Detection] = []
    for pf in pii_map:
        for _trail, value in _resolve_paths(result, pf.field_path):
            if isinstance(value, str) and value:
                found.append(Detection(pf.field_path, value, pf.pii_type, "structural"))
    return found


def pattern_detect(text: str) -> list[Detection]:
    found: list[Detection] = []
    for pii_type, pat in PATTERNS:
        for m in pat.finditer(text):
            found.append(Detection("", m.group(), pii_type, "pattern"))
    return found
