"""``RunRecord`` and ``Meter`` — the record of one agent execution.

``git_commit`` is recorded on day one: it is what makes the eval dashboard's
"across commits" view possible, and retrofitting it is painful. The prompt hash
is recorded because prompt changes are the most common cause of behaviour
changes, and without it a regression cannot be attributed to its cause.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import Field

from sentinel.contracts.base import Contract
from sentinel.contracts.enums import RunMode, TerminalState


class Meter(Contract):
    """Cost/latency/attribution. Where a provider reports no usage, the gap is
    recorded (cost_micros=None) rather than estimated — an invented number is
    worse than a missing one."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_reads: int = 0
    total_cost_micros: Optional[int] = None   # integer micro-currency; None = provider reported nothing
    cost_gap: bool = False                     # True if any call lacked usage data
    wall_clock_ms: float = 0.0
    policy_eval_ms: float = 0.0                # honest cost of the guardrail
    time_to_first_tool_call_ms: Optional[float] = None
    provider_calls: dict[str, int] = Field(default_factory=dict)  # provider -> count
    model_calls: dict[str, int] = Field(default_factory=dict)     # model -> count


class RunRecord(Contract):
    id: str
    agent_id: str
    agent_version: str
    operator_id: str
    policy_set_id: str
    policy_set_version: str
    system_prompt_hash: str = ""              # version the prompt; attribute regressions

    mode: RunMode
    input_task: str = ""
    artifact_refs: tuple[str, ...] = ()       # references, NOT contents

    terminal_state: TerminalState
    output: Optional[dict[str, Any]] = None   # conforms to the agent's declared schema

    # aggregates
    step_count: int = 0
    tool_call_count: int = 0
    denials_by_reason: dict[str, int] = Field(default_factory=dict)
    approvals_requested: int = 0
    approvals_granted: int = 0
    approvals_rejected: int = 0
    malformed_tool_calls: int = 0             # a real quality signal, reported per model
    schema_violations: int = 0
    provider_failovers: int = 0

    meter: Meter = Field(default_factory=Meter)

    git_commit: str = ""                      # sha of the code that produced this run
    started_at_ms: int = 0
    ended_at_ms: int = 0
