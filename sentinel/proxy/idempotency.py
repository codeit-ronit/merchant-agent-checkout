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
    def __init__(self) -> None:
        self._seen: dict[str, Any] = {}
        self._lock = threading.Lock()

    def seen(self, key: str) -> bool:
        with self._lock:
            return key in self._seen

    def get(self, key: str) -> Any | None:
        with self._lock:
            return self._seen.get(key)

    def record(self, key: str, result: Any) -> None:
        with self._lock:
            self._seen[key] = result


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
