"""``Scenario`` (eval + red-team) and the result types.

A scenario is a fully specified, reproducible case — a data file, never code.
Every scenario asserts ``no_unauthorized_execution`` regardless of what it is
nominally testing: safety assertions are not opt-in.

The paired red-team result holds the guardrails-off / guardrails-on pair from
the start — it is the demo, and reconstructing the pair at report time is how
you end up comparing the wrong things.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import Field

from sentinel.contracts.base import Contract
from sentinel.contracts.enums import AssertionType, RedTeamSeverity


class Assertion(Contract):
    type: AssertionType
    # Free-form parameters interpreted per assertion type. Kept small and
    # composable (docs/spec/03 §9). Examples:
    #   tool_called: {"tool": "create_refund"}
    #   denial_reason_includes: {"reason_code": "ESCALATE_MONEY_MOVEMENT"}
    #   within_budget: {"max_cost_micros": 5000, "max_latency_ms": 8000}
    #   output_matches: {"path": "summary.matched_count", "equals": 3}
    params: dict[str, Any] = Field(default_factory=dict)
    # Why this assertion is what it is — you will not remember in six months.
    rationale: str = ""


class Scenario(Contract):
    id: str
    suite: str                          # "golden" | "redteam"
    tags: tuple[str, ...] = ()
    category: str = ""                  # happy_path | hard_but_correct | refusal_correct | policy_triggering | adversarial_lite

    fixture_dataset_version: str        # the exact upstream state
    agent_id: str
    agent_config: dict[str, Any] = Field(default_factory=dict)
    policy_set_id: str

    operator_task: str

    # Injection, if any: what, and where (which field of which record).
    injected_content: Optional[str] = None
    injection_field: Optional[str] = None    # dotted path into the fixture record
    injection_record_id: Optional[str] = None
    injection_vector: Optional[str] = None   # e.g. "statement_narration", "pdf_text_layer"
    injection_class: Optional[str] = None    # e.g. "direct_override", "delimiter_escape"

    assertions: tuple[Assertion, ...] = ()

    # Expected outcome + reasoning, for the human reader (docs/spec/08 §3.2).
    expected_outcome: str = ""


class AssertionResult(Contract):
    type: AssertionType
    passed: bool
    detail: str = ""


class EvalResult(Contract):
    scenario_id: str
    model: str
    provider: str
    passed: bool
    assertion_results: tuple[AssertionResult, ...] = ()
    run_record_id: str = ""
    git_commit: str = ""
    # diff against the previous recorded result for the same scenario+model
    changed_from_baseline: Optional[str] = None   # "newly_passing" | "newly_failing" | None
    cassettes_refreshed: int = 0


class RedTeamResult(Contract):
    scenario_id: str
    model: str
    guardrails_on: bool
    severity: RedTeamSeverity          # rule-based grade from trace + audit
    unauthorized_execution: bool = False
    pii_or_token_exfiltrated: bool = False
    out_of_scope_read: bool = False
    behaviour_altered: bool = False
    detail: str = ""
    run_record_id: str = ""


class PairedRedTeamResult(Contract):
    """Same payload, guardrails off vs on, identical in every other respect.
    This pairing is the headline result."""

    scenario_id: str
    model: str
    payload_class: str
    vector: str
    off: RedTeamResult                 # condition A — guardrails off
    on: RedTeamResult                  # condition B — guardrails on
    is_benign: bool = False            # benign-but-suspicious: measures false positives
