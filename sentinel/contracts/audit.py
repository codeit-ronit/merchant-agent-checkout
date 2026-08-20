"""``AuditEntry`` — one immutable ledger record.

A superset of a trace event, plus the hash chain. Each entry's ``entry_hash``
covers its canonical serialisation *including* ``previous_hash``, so altering
entry N invalidates every entry after it. Sequences are gapless ledger-wide.

Pre-redacted: redaction happens before the entry is constructed, never after.
The canonical serialisation for hashing is exactly specified in
``sentinel.common.canonical`` (RFC-8785-inspired, floats forbidden).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import Field

from sentinel.contracts.base import Contract
from sentinel.contracts.decision import PolicyDecision
from sentinel.contracts.enums import RiskClass

GENESIS_HASH = "0" * 64  # previous_hash of the first entry


class AuditEntry(Contract):
    # --- identity & timestamps ---
    entry_id: str
    run_id: str
    step_id: Optional[str] = None
    call_id: Optional[str] = None
    timestamp_ms: int

    # --- the call ---
    tool_name: Optional[str] = None
    risk_class: Optional[RiskClass] = None
    arguments_redacted: dict[str, Any] = Field(default_factory=dict)
    argument_hash: Optional[str] = None

    # --- the decision ---
    decision: Optional[PolicyDecision] = None

    # --- approval linkage ---
    approval_id: Optional[str] = None
    approval_resolver: Optional[str] = None

    # --- execution outcome ---
    outcome: str = ""   # forwarded | blocked | idempotent_replay | upstream_error | security_event

    # --- meter ---
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micros: Optional[int] = None       # integer micro-currency; None if provider reports no usage
    policy_eval_ms: float = 0.0
    provider: Optional[str] = None
    model: Optional[str] = None

    # --- attribution ---
    policy_set_version: Optional[str] = None
    agent_version: Optional[str] = None
    git_commit: Optional[str] = None

    # --- chain ---
    sequence: int                            # monotonic, gapless, ledger-wide
    previous_hash: str
    entry_hash: str

    def chain_payload(self) -> dict[str, Any]:
        """The canonical view that ``entry_hash`` is computed over: everything
        EXCEPT ``entry_hash`` itself. Includes ``previous_hash`` and ``sequence``.

        Timing floats are stringified (ADR-010) so the structure canonicalises
        deterministically without risking IEEE-754 round-trips changing a hash."""
        from sentinel.common.canonical import stringify_floats
        data = self.model_dump(mode="json", exclude={"entry_hash"})
        return stringify_floats(data)
