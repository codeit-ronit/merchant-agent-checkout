"""Tokenisation, result redaction, and rehydration (docs/spec/05 A3, ADR-008).

* **Stable within a run** — the same underlying value produces the same token
  every time, so the model can still correlate records (reconciliation depends on
  this).
* **Not stable across runs** — the token is a keyed hash of the value plus a
  per-run salt, so a token is not a cross-run tracking identifier.
* **Not a counter** — counters leak ordering and cardinality.
* The token→value map lives here, in a store the agent runtime cannot address —
  never in a trace, an audit entry, or any object the model reaches.
"""

from __future__ import annotations

import copy
import hmac
import os
import re
from hashlib import sha256
from typing import Any

from sentinel.redaction.detectors import (
    PII_PREFIX,
    Detection,
    pattern_detect,
    structural_detect,
)

# A token is <PREFIX>_<8 hex>. Used to spot model-emitted tokens in arguments.
_TOKEN_RE = re.compile(r"\b(" + "|".join(sorted(set(PII_PREFIX.values()))) + r")_[0-9a-f]{8}\b")


class RedactionSession:
    """Per-run token store. Constructed once per run with a fresh salt."""

    def __init__(self, run_id: str, salt: bytes | None = None):
        self.run_id = run_id
        # per-run salt: random by default, injectable for deterministic replay.
        self.salt = salt if salt is not None else os.urandom(16)
        self._token_to_value: dict[str, str] = {}
        self._value_to_token: dict[str, str] = {}
        self.pattern_on_clean_field = 0   # schema-annotation debt metric

    def tokenize(self, value: str, pii_type: str) -> str:
        if value in self._value_to_token:
            return self._value_to_token[value]
        digest = hmac.new(self.salt, value.encode("utf-8"), sha256).hexdigest()[:8]
        prefix = PII_PREFIX.get(pii_type, "PII")
        token = f"{prefix}_{digest}"
        # (astronomically unlikely) collision guard: extend on clash
        while token in self._token_to_value and self._token_to_value[token] != value:
            digest = hmac.new(self.salt, (value + token).encode(), sha256).hexdigest()[:8]
            token = f"{prefix}_{digest}"
        self._token_to_value[token] = value
        self._value_to_token[value] = token
        return token

    def is_issued(self, token: str) -> bool:
        return token in self._token_to_value

    def detokenize(self, token: str) -> str | None:
        return self._token_to_value.get(token)

    @property
    def issued_count(self) -> int:
        return len(self._token_to_value)


def _redact_string(s: str, structural_values: dict[str, str], session: RedactionSession) -> str:
    out = s
    # structural values first (exact known values may appear inside free text too)
    for val, pii_type in structural_values.items():
        if val and val in out:
            out = out.replace(val, session.tokenize(val, pii_type))
    # pattern safety net over whatever remains
    for det in pattern_detect(out):
        if det.value in structural_values:
            continue
        # a real pattern hit on text the structural map didn't cover -> debt
        session.pattern_on_clean_field += 1
        out = out.replace(det.value, session.tokenize(det.value, det.pii_type))
    return out


def redact_result(result: dict, pii_map, session: RedactionSession) -> tuple[dict, list[Detection]]:
    """Return a redacted deep copy of ``result`` and the detections applied.

    Structural detections (from the tool's pii_map) are authoritative; a pattern
    pass then sweeps every string for anything the schema missed."""
    redacted = copy.deepcopy(result)
    structural = structural_detect(redacted, pii_map)
    structural_values = {d.value: d.pii_type for d in structural}

    def walk(node: Any):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str):
                    node[k] = _redact_string(v, structural_values, session)
                else:
                    walk(v)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                if isinstance(v, str):
                    node[i] = _redact_string(v, structural_values, session)
                else:
                    walk(v)

    walk(redacted)
    return redacted, structural


def rehydrate_arguments(arguments: dict, rehydratable_paths, session: RedactionSession) -> dict:
    """Substitute issued tokens back to real values, but ONLY in argument paths a
    tool legitimately needs. Any token that was never issued this run — anywhere
    in the arguments — is a hallucination or an exfiltration attempt and raises
    ``UnissuedTokenError`` (the caller denies + flags a security event).
    """
    from sentinel.redaction.quarantine import UnissuedTokenError

    # 1. Scan ALL argument strings for model-emitted tokens; any unissued token
    #    is a suspected exfiltration attempt regardless of where it appears.
    def scan(node: Any):
        if isinstance(node, str):
            for m in _TOKEN_RE.finditer(node):
                if not session.is_issued(m.group()):
                    raise UnissuedTokenError(m.group())
        elif isinstance(node, dict):
            for v in node.values():
                scan(v)
        elif isinstance(node, list):
            for v in node:
                scan(v)

    scan(arguments)

    # 2. Rehydrate issued tokens in the declared rehydratable paths only.
    out = copy.deepcopy(arguments)
    rehydratable = set(rehydratable_paths or ())
    for path in rehydratable:
        parts = path.split(".")
        node = out
        for p in parts[:-1]:
            node = node.get(p) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, dict) and parts[-1] in node:
            val = node[parts[-1]]
            if isinstance(val, str) and session.is_issued(val):
                node[parts[-1]] = session.detokenize(val)
    return out
