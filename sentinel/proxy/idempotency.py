"""Idempotency guard — a retried refund must not be a second refund.

Agents retry, loops repeat, networks time out ambiguously, and provider failover
adds a new retry path (if provider A times out after emitting a tool call and
provider B re-emits it). Every mutating call gets a deterministic key from
``(run_id, semantic_operation, canonicalised_arguments)``. Canonicalisation is
stable (sorted keys, integer numbers, no whitespace) via the canonical serialiser.
A seen key returns the stored prior result and records ``IDEMPOTENT_REPLAY``
instead of executing again.

Entity-level locking guards the concurrent-runs case (two runs mutating the same
entity): the second acquirer blocks, never interleaves.
"""

from __future__ import annotations

import threading
from typing import Any

from sentinel.common.canonical import sha256_hex


def idempotency_key(run_id: str, operation: str, arguments: dict[str, Any]) -> str:
    """Deterministic key. Canonicalisation (sorted keys, integer numbers, compact)
    is provided by the canonical serialiser, so equal calls hash equal."""
    return sha256_hex({"run": run_id, "op": operation, "args": arguments})


class IdempotencyGuard:
    """States per key: absent -> reserved (in-flight / ambiguous) -> done (result
    stored). ``begin`` is the single atomic check-and-reserve that makes both a
    sequential retry AND a concurrent race safe: exactly one caller gets
    ``proceed`` for a given key; everyone else gets ``replay`` (a completed call)
    or ``refuse`` (a call that is in-flight or failed ambiguously — re-executing a
    money movement is worse than denying it)."""

    _RESERVED = object()

    def __init__(self) -> None:
        self._seen: dict[str, Any] = {}      # key -> result, or _RESERVED sentinel
        self._lock = threading.Lock()

    def begin(self, key: str) -> tuple[str, Any]:
        """Atomically reserve ``key`` for execution. Returns one of:
        ('proceed', None)  -> caller may forward; must call complete()/abandon()
        ('replay', result) -> already completed; return the stored result, do NOT execute
        ('refuse', None)   -> reserved by someone else / a prior ambiguous failure; DENY.
        """
        with self._lock:
            if key not in self._seen:
                self._seen[key] = self._RESERVED
                return ("proceed", None)
            stored = self._seen[key]
            if stored is self._RESERVED:
                return ("refuse", None)
            return ("replay", stored)

    def complete(self, key: str, result: Any) -> None:
        with self._lock:
            self._seen[key] = result

    def abandon(self, key: str) -> None:
        """Release a reservation on a CLEAN, retryable failure (upstream provably
        did nothing). NOT used for money movement, where an ambiguous failure must
        stay reserved and fail closed."""
        with self._lock:
            if self._seen.get(key) is self._RESERVED:
                del self._seen[key]

    # --- legacy read helpers (kept for callers/tests that only inspect) ---
    def seen(self, key: str) -> bool:
        with self._lock:
            return key in self._seen

    def get(self, key: str) -> Any | None:
        with self._lock:
            v = self._seen.get(key)
            return None if v is self._RESERVED else v

    def record(self, key: str, result: Any) -> None:
        self.complete(key, result)


class EntityLocks:
    """Per-entity locks so concurrent runs cannot interleave a mutation of the
    same entity. Acquire around forwarding a write; release after."""

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def lock_for(self, entity_id: str) -> threading.Lock:
        with self._guard:
            if entity_id not in self._locks:
                self._locks[entity_id] = threading.Lock()
            return self._locks[entity_id]
