"""Trace emission — one event stream consumed by BOTH the UI (SSE) and the eval
harness. Do not build two: divergence between what you watch and what you measure
is how you debug the wrong thing.

Sequence numbers are gapless within a run so a consumer can detect a dropped
event. All payloads are pre-redacted — the trace is shown in a browser and
written to disk, so it must never be the leak.
"""

from __future__ import annotations

from typing import Callable, Optional

from sentinel.contracts.trace import TraceEvent, TraceEventType


class TraceEmitter:
    def __init__(self, run_id: str, clock_ms: Callable[[], int],
                 sink: Optional[Callable[[TraceEvent], None]] = None):
        self.run_id = run_id
        self._clock_ms = clock_ms
        self._seq = 0
        self.events: list[TraceEvent] = []
        self._sink = sink

    def emit(self, type_: str, payload: dict, *, step_id: str | None = None,
             call_id: str | None = None) -> TraceEvent:
        evt = TraceEvent(
            run_id=self.run_id, sequence=self._seq,
            type=TraceEventType(type_), timestamp_ms=self._clock_ms(),
            step_id=step_id, call_id=call_id, payload=payload,
        )
        self._seq += 1
        self.events.append(evt)
        if self._sink:
            self._sink(evt)
        return evt

    def since(self, sequence: int) -> list[TraceEvent]:
        """Backfill for a reconnecting SSE consumer."""
        return [e for e in self.events if e.sequence >= sequence]
