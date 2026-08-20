"""Time-ordered identifiers.

Every ID is a ULID (48-bit millisecond timestamp + 80 bits of entropy, Crockford
base32) with a short type prefix, e.g. ``run_01J9Z...``. Two properties matter:

* **Sortable by creation time.** Lexicographic sort == chronological sort, so a
  log sorts chronologically with no separate timestamp index.
* **Type-tagged.** A ``RunId`` and a ``StepId`` are not interchangeable strings.

IDs are minted by *callers* (runtime, proxy, stores) — never by the pure policy
engine, which reads no clock and no randomness. For deterministic tests, an
``IdFactory`` accepts an injectable clock and entropy source.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable

# Crockford base32 (no I, L, O, U).
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


# Prefix registry — one per ID type in the data-contract spec.
PREFIXES = {
    "RunId": "run",
    "StepId": "step",
    "CallId": "call",
    "ApprovalId": "appr",
    "ScenarioId": "scn",
    "PolicySetId": "pol",
    "EntryId": "aud",
    "TraceId": "trc",
}


@dataclass
class IdFactory:
    """Mints prefixed ULIDs. Inject ``clock``/``entropy`` for deterministic tests.

    Monotonic within a millisecond: if two IDs are minted in the same ms, the
    random component is incremented rather than redrawn, so lexicographic order
    stays equal to chronological order even under a burst. This is the standard
    ULID monotonic factory behaviour and is what "sortable by creation time"
    actually requires."""

    clock: Callable[[], float] = time.time
    entropy: Callable[[int], bytes] = os.urandom
    _last_ms: int = -1
    _last_rand: int = 0

    def new(self, kind: str) -> str:
        prefix = PREFIXES[kind]
        ms = int(self.clock() * 1000)
        if ms == self._last_ms:
            self._last_rand += 1
            rand_int = self._last_rand
        else:
            self._last_ms = ms
            rand_int = int.from_bytes(self.entropy(10)[:10].ljust(10, b"\x00"), "big") & ((1 << 50) - 1)
            self._last_rand = rand_int
        time_part = _encode(ms & ((1 << 48) - 1), 10)
        rand_part = _encode(rand_int & ((1 << 50) - 1), 10)
        return f"{prefix}_{time_part}{rand_part}"

    def run(self) -> str: return self.new("RunId")
    def step(self) -> str: return self.new("StepId")
    def call(self) -> str: return self.new("CallId")
    def approval(self) -> str: return self.new("ApprovalId")
    def scenario(self) -> str: return self.new("ScenarioId")
    def entry(self) -> str: return self.new("EntryId")
    def trace(self) -> str: return self.new("TraceId")


# Default process-wide factory for production paths.
DEFAULT = IdFactory()


def new_run_id() -> str: return DEFAULT.run()
def new_step_id() -> str: return DEFAULT.step()
def new_call_id() -> str: return DEFAULT.call()
def new_approval_id() -> str: return DEFAULT.approval()
def new_entry_id() -> str: return DEFAULT.entry()


def deterministic_factory(seed: int = 0) -> IdFactory:
    """A fully deterministic factory for tests and fixture/replay runs: a fixed
    clock and a counter-based entropy stream. Not used on any production path."""
    counter = {"n": seed}
    base_ms = 1_755_000_000_000  # a fixed instant in 2025-08, arbitrary but stable

    def clock() -> float:
        counter["n"] += 1
        return (base_ms + counter["n"]) / 1000.0

    def entropy(n: int) -> bytes:
        counter["n"] += 1
        return counter["n"].to_bytes(16, "big")[:n]

    return IdFactory(clock=clock, entropy=entropy)
