"""Data contracts — every object that crosses a boundary in SENTINEL.

Rules (docs/spec/03-DATA-CONTRACTS.md), all enforced here:
1. Typed and validated at construction (Pydantic; a malformed object is impossible).
2. Immutable once created (``frozen=True``): decisions, audit entries, traces are facts.
3. Versioned (every persisted structure carries ``schema_version``).
4. Redaction-aware (PII-bearing fields are excluded from serialisation).
5. Reason codes are an enum, never a free string.
"""

from sentinel.contracts.approvals import ApprovalRequest
from sentinel.contracts.audit import AuditEntry
from sentinel.contracts.decision import DecisionContext, MoneySemantics, PolicyDecision
from sentinel.contracts.enums import (
    ApprovalStatus,
    AssertionType,
    ClassificationStatus,
    Disposition,
    Obligation,
    Provenance,
    ReconClass,
    RedTeamSeverity,
    RiskClass,
    RunMode,
    TerminalState,
    TraceEventType,
)
from sentinel.contracts.reasons import ReasonCode, reason_templates, render_reason
from sentinel.contracts.runs import Meter, RunRecord
from sentinel.contracts.scenarios import (
    Assertion,
    EvalResult,
    PairedRedTeamResult,
    RedTeamResult,
    Scenario,
)
from sentinel.contracts.tools import FieldProvenance, PiiField, ToolDescriptor
from sentinel.contracts.trace import TraceEvent

__all__ = [
    "ApprovalStatus", "AssertionType", "ClassificationStatus", "Disposition",
    "Obligation", "Provenance", "ReconClass", "RedTeamSeverity", "RiskClass",
    "RunMode", "TerminalState", "TraceEventType",
    "ReasonCode", "render_reason", "reason_templates",
    "DecisionContext", "MoneySemantics", "PolicyDecision",
    "FieldProvenance", "PiiField", "ToolDescriptor",
    "TraceEvent", "AuditEntry", "ApprovalRequest",
    "Meter", "RunRecord",
    "Assertion", "EvalResult", "PairedRedTeamResult", "RedTeamResult", "Scenario",
]
