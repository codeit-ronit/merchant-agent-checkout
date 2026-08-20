"""Reason codes and their plain-language templates.

Every allow, deny, and escalation carries a machine-readable ``ReasonCode`` and a
human-readable sentence written for an operations person, not an engineer:

    Bad:  "DENY: rule_47 predicate false"
    Good: "Blocked: refunds over ₹10,000 need finance approval. This one was ₹24,500."

Rendering never raises and never leaks PII: templates reference amounts, caps,
tool names, counts, and windows — never raw identifiers. Missing parameters fall
back to a safe generic phrase. A test asserts full template coverage and no leak.
"""

from __future__ import annotations

from enum import Enum

from sentinel.contracts.enums import Disposition


class ReasonCode(str, Enum):
    # --- ALLOW ---
    ALLOW_EXPLICIT_RULE = "ALLOW_EXPLICIT_RULE"
    ALLOW_READ_ONLY = "ALLOW_READ_ONLY"
    ALLOW_PRIOR_APPROVAL = "ALLOW_PRIOR_APPROVAL"
    ALLOW_WITHIN_SCOPE = "ALLOW_WITHIN_SCOPE"
    # --- DENY ---
    DENY_UNKNOWN_TOOL = "DENY_UNKNOWN_TOOL"
    DENY_FORBIDDEN_TOOL = "DENY_FORBIDDEN_TOOL"
    DENY_SCHEMA_INVALID = "DENY_SCHEMA_INVALID"
    DENY_OUT_OF_SCOPE = "DENY_OUT_OF_SCOPE"
    DENY_AMOUNT_EXCEEDS_CAP = "DENY_AMOUNT_EXCEEDS_CAP"
    DENY_RATE_LIMIT = "DENY_RATE_LIMIT"
    DENY_OUTSIDE_TIME_WINDOW = "DENY_OUTSIDE_TIME_WINDOW"
    DENY_SUSPECTED_EXFILTRATION = "DENY_SUSPECTED_EXFILTRATION"
    DENY_POLICY_EVALUATION_ERROR = "DENY_POLICY_EVALUATION_ERROR"
    DENY_FAIL_CLOSED = "DENY_FAIL_CLOSED"
    DENY_TOOL_DENIED = "DENY_TOOL_DENIED"
    DENY_ARGUMENT_CONSTRAINT = "DENY_ARGUMENT_CONSTRAINT"
    # --- ESCALATE (REQUIRE_APPROVAL) ---
    ESCALATE_MONEY_MOVEMENT = "ESCALATE_MONEY_MOVEMENT"
    ESCALATE_IRREVERSIBLE = "ESCALATE_IRREVERSIBLE"
    ESCALATE_AMOUNT_THRESHOLD = "ESCALATE_AMOUNT_THRESHOLD"
    ESCALATE_INJECTION_SUSPECTED = "ESCALATE_INJECTION_SUSPECTED"
    ESCALATE_NOVEL_COUNTERPARTY = "ESCALATE_NOVEL_COUNTERPARTY"
    ESCALATE_APPROVAL_REQUIRED_RULE = "ESCALATE_APPROVAL_REQUIRED_RULE"


# Default disposition each code expresses (used for cross-checks and rendering tests).
CODE_DISPOSITION: dict[ReasonCode, Disposition] = {
    ReasonCode.ALLOW_EXPLICIT_RULE: Disposition.ALLOW,
    ReasonCode.ALLOW_READ_ONLY: Disposition.ALLOW,
    ReasonCode.ALLOW_PRIOR_APPROVAL: Disposition.ALLOW,
    ReasonCode.ALLOW_WITHIN_SCOPE: Disposition.ALLOW,
    ReasonCode.DENY_UNKNOWN_TOOL: Disposition.DENY,
    ReasonCode.DENY_FORBIDDEN_TOOL: Disposition.DENY,
    ReasonCode.DENY_SCHEMA_INVALID: Disposition.DENY,
    ReasonCode.DENY_OUT_OF_SCOPE: Disposition.DENY,
    ReasonCode.DENY_AMOUNT_EXCEEDS_CAP: Disposition.DENY,
    ReasonCode.DENY_RATE_LIMIT: Disposition.DENY,
    ReasonCode.DENY_OUTSIDE_TIME_WINDOW: Disposition.DENY,
    ReasonCode.DENY_SUSPECTED_EXFILTRATION: Disposition.DENY,
    ReasonCode.DENY_POLICY_EVALUATION_ERROR: Disposition.DENY,
    ReasonCode.DENY_FAIL_CLOSED: Disposition.DENY,
    ReasonCode.DENY_TOOL_DENIED: Disposition.DENY,
    ReasonCode.DENY_ARGUMENT_CONSTRAINT: Disposition.DENY,
    ReasonCode.ESCALATE_MONEY_MOVEMENT: Disposition.REQUIRE_APPROVAL,
    ReasonCode.ESCALATE_IRREVERSIBLE: Disposition.REQUIRE_APPROVAL,
    ReasonCode.ESCALATE_AMOUNT_THRESHOLD: Disposition.REQUIRE_APPROVAL,
    ReasonCode.ESCALATE_INJECTION_SUSPECTED: Disposition.REQUIRE_APPROVAL,
    ReasonCode.ESCALATE_NOVEL_COUNTERPARTY: Disposition.REQUIRE_APPROVAL,
    ReasonCode.ESCALATE_APPROVAL_REQUIRED_RULE: Disposition.REQUIRE_APPROVAL,
}

# Templates. ``{placeholders}`` are filled from render params; a placeholder
# whose value is absent uses a safe fallback (see ``_SafeDict``). None of these
# reference PII — only tool names, amounts (already display-formatted), caps,
# counts, windows, and generic nouns.
_TEMPLATES: dict[ReasonCode, str] = {
    ReasonCode.ALLOW_EXPLICIT_RULE:
        "Allowed: {tool} is permitted for this agent by rule '{rule}'.",
    ReasonCode.ALLOW_READ_ONLY:
        "Allowed: {tool} only reads data and stays within the operator's scope.",
    ReasonCode.ALLOW_PRIOR_APPROVAL:
        "Allowed: a reviewer approved this exact action ({tool}, {amount}) and the approval is still valid.",
    ReasonCode.ALLOW_WITHIN_SCOPE:
        "Allowed: {tool} targets an entity inside the operator's declared scope.",
    ReasonCode.DENY_UNKNOWN_TOOL:
        "Blocked: {tool} is not classified in policy, so it is treated as maximally dangerous until a human classifies it.",
    ReasonCode.DENY_FORBIDDEN_TOOL:
        "Blocked: {tool} is forbidden in this deployment and is not available to the agent.",
    ReasonCode.DENY_SCHEMA_INVALID:
        "Blocked: the arguments to {tool} did not match the tool's declared schema, so the call was rejected rather than guessed.",
    ReasonCode.DENY_OUT_OF_SCOPE:
        "Blocked: {tool} targets an entity outside the operator's declared scope.",
    ReasonCode.DENY_AMOUNT_EXCEEDS_CAP:
        "Blocked: {tool} for {amount} exceeds the hard ceiling of {cap} and cannot be approved by anyone.",
    ReasonCode.DENY_RATE_LIMIT:
        "Blocked: {tool} has already run {count} times this {window}; the limit is {limit}.",
    ReasonCode.DENY_OUTSIDE_TIME_WINDOW:
        "Blocked: {tool} is only permitted during {window}; the current time is outside it.",
    ReasonCode.DENY_SUSPECTED_EXFILTRATION:
        "Blocked and flagged as a security event: {tool} referenced a placeholder token that was never issued in this run — a possible data-exfiltration attempt.",
    ReasonCode.DENY_POLICY_EVALUATION_ERROR:
        "Blocked: the policy engine could not evaluate this call safely, so the call was denied and the run aborted (fail closed).",
    ReasonCode.DENY_FAIL_CLOSED:
        "Blocked: no rule permits {tool} for this agent, and the default is to deny.",
    ReasonCode.DENY_TOOL_DENIED:
        "Blocked: {tool} is explicitly denied to this agent by rule '{rule}'.",
    ReasonCode.DENY_ARGUMENT_CONSTRAINT:
        "Blocked: an argument to {tool} violated a policy constraint ({detail}).",
    ReasonCode.ESCALATE_MONEY_MOVEMENT:
        "Needs approval: {tool} moves money ({amount}) and always requires a human reviewer.",
    ReasonCode.ESCALATE_IRREVERSIBLE:
        "Needs approval: {tool} makes a change that cannot be undone and requires a human reviewer.",
    ReasonCode.ESCALATE_AMOUNT_THRESHOLD:
        "Needs approval: {tool} for {amount} is over the {threshold} review threshold.",
    ReasonCode.ESCALATE_INJECTION_SUSPECTED:
        "Needs approval: this run processed untrusted content, so {tool} was escalated to a human even though it would normally be allowed.",
    ReasonCode.ESCALATE_NOVEL_COUNTERPARTY:
        "Needs approval: {tool} pays out to a destination never seen before in this deployment — a new counterparty always needs a human reviewer.",
    ReasonCode.ESCALATE_APPROVAL_REQUIRED_RULE:
        "Needs approval: rule '{rule}' requires a human reviewer for {tool}.",
}


class _SafeDict(dict):
    """format_map helper: unknown/absent placeholders render as a neutral word,
    so a template never raises on a missing parameter."""

    _FALLBACKS = {
        "tool": "this action",
        "rule": "policy",
        "amount": "the amount",
        "cap": "the limit",
        "count": "several",
        "limit": "the limit",
        "window": "this window",
        "threshold": "the",
        "detail": "a value was not permitted",
    }

    def __missing__(self, key: str) -> str:
        return self._FALLBACKS.get(key, "")


def reason_templates() -> dict[ReasonCode, str]:
    """Every code -> its template. Used by the coverage test."""
    return dict(_TEMPLATES)


def render_reason(code: ReasonCode, **params) -> str:
    """Render the plain-language sentence for ``code``. Never raises."""
    template = _TEMPLATES[code]
    # Stringify params defensively; drop None so the fallback fires.
    safe = {k: ("" if v is None else str(v)) for k, v in params.items()}
    return template.format_map(_SafeDict(safe))
