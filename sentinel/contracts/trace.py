"""``TraceEvent`` — the streaming unit. One event per meaningful thing in a run.

Both the UI (via SSE) and the eval harness consume the *same* stream — there is
no second path. Sequence numbers are gapless within a run so a consumer can
detect a dropped event. All payloads are pre-redacted: the trace is shown in a
browser and written to disk, so it must never be the leak.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from sentinel.contracts.base import Contract
from sentinel.contracts.enums import TraceEventType


class TraceEvent(Contract):
    run_id: str
    sequence: int                      # gapless within the run, starts at 0
    type: TraceEventType
    timestamp_ms: int
    step_id: str | None = None
    call_id: str | None = None
    # Pre-redacted, type-specific payload. Never contains raw PII.
    payload: dict[str, Any] = Field(default_factory=dict)
