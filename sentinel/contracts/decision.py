"""``DecisionContext`` and ``PolicyDecision`` — the input to and output from the
pure policy engine.

``DecisionContext`` is the most important type in the system. Because the engine
is pure, *everything it could need is here*: the call, the resolved risk class,
the redacted arguments, and an ``InjectedEnv`` carrying the clock, spend,
counts, approval status, and seen-counterparties — all supplied by the caller,
never read by the engine.

Redaction note: the engine reasons over **redacted** arguments (PII replaced by
stable tokens) plus non-PII money semantics (integer amount, currency, entity
*reference* ids such as ``pay_...`` / ``fa_...`` — which are Razorpay object ids,
not PII). Raw PII never enters this object. ``arguments_raw`` exists for the
proxy's transient rehydration use only and is excluded from all serialisation.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import Field

from sentinel.contracts.base import Contract
from sentinel.contracts.enums import BindingRole, Disposition, Obligation, Provenance, RiskClass
from sentinel.contracts.reasons import ReasonCode


class MoneySemantics(Contract):
    """Extracted money meaning of a call, when the tool has any. Amounts are
    integer minor units (paise for INR) — never floats."""

    moves_money: bool = False
    amount_minor: Optional[int] = None
    currency: Optional[str] = None
    # Financial-commitment role — orthogonal to risk_class (ADR-024). Amount
    # governance keys off this, so a reversible write that binds a large amount is
    # still governed.
    binding_role: BindingRole = BindingRole.NONE
    # Entity *reference* ids (pay_/rfnd_/setl_/fa_/cust_...). These are Razorpay
    # object identifiers, NOT PII (the account number behind fa_... is PII and is
    # tokenised elsewhere). Novelty and scope checks operate on these.
    target_entities: tuple[str, ...] = ()
    # The payout/transfer destination reference, when the tool has one. Used by
    # counterparty_novelty. A stable, non-PII object id.
    counterparty_ref: Optional[str] = None


class MandateEnv(Contract):
    """The consent envelope's state at decision time (CONDUIT, 05-MANDATE
    §3.4): a policy INPUT, not a parallel gate. Injected by the caller like
    every other env fact — the engine never reads the ledger itself. The
    balance is ledger-derived by the injector; the engine only compares."""

    mandate_id: str
    remaining_minor: int
    currency: str
    scope_merchant_id: str
    expires_at_ms: int
    status: str = "ACTIVE"           # ACTIVE | REVOKED


class InjectedEnv(Contract):
    """Everything the engine would otherwise have to read from the world.
    Supplied by the caller. The engine NEVER reads a clock, db, or network."""

    now_epoch_ms: int
    now_local_hour: int = 0            # operator-timezone hour, for time_window rules
    now_weekday: int = 0               # 0=Mon .. 6=Sun
    spend_run_minor: int = 0           # accumulated DISBURSEMENT spend this run
    collected_run_minor: int = 0       # accumulated COLLECTION amount bound this run
    spend_day_minor: int = 0           # accumulated spend today
    spend_window_minor: int = 0        # accumulated spend this policy window
    tool_call_count_run: int = 0
    per_tool_count_run: dict[str, int] = Field(default_factory=dict)
    per_class_count_window: dict[str, int] = Field(default_factory=dict)
    elapsed_run_ms: int = 0
    # Approval status for THIS exact call (argument-bound, unexpired, unconsumed).
    valid_approval_present: bool = False
    approval_argument_hash: Optional[str] = None
    # Counterparties seen before in this deployment (object refs, non-PII).
    known_counterparties: frozenset[str] = frozenset()
    # Entities inside the operator's declared scope (object refs, non-PII).
    operator_scope_entities: frozenset[str] = frozenset()
    # CONDUIT mandate state (None when the run is not mandate-bound) and the
    # deployment's merchant identity, for the mandate scope check.
    mandate: Optional[MandateEnv] = None
    merchant_id: Optional[str] = None


class DecisionContext(Contract):
    # Identity & provenance
    run_id: str
    step_id: str
    call_id: str
    agent_id: str
    agent_version: str
    operator_id: str
    policy_set_id: str
    policy_set_version: str

    # The call itself
    tool_name: str                         # as presented to the model
    upstream_tool_name: str                # may differ after namespacing
    risk_class: RiskClass
    arguments_redacted: dict[str, Any] = Field(default_factory=dict)
    argument_hash: str = ""                # canonical hash of the redacted args
    idempotency_key: str = ""
    # Transient, proxy-only, NEVER serialised (redaction rule 4).
    arguments_raw: Optional[dict[str, Any]] = Field(default=None, exclude=True, repr=False)

    # Injected environment
    env: InjectedEnv

    # Signals
    provenance_present: tuple[Provenance, ...] = ()
    quarantined_content_in_context: bool = False
    model_stated_intent: Optional[str] = None
    injection_suspicion_score: float = 0.0     # signal only; never a gate

    # Money semantics
    money: MoneySemantics = Field(default_factory=MoneySemantics)

    @property
    def untrusted_in_context(self) -> bool:
        return self.quarantined_content_in_context or Provenance.UNTRUSTED in self.provenance_present


class PolicyDecision(Contract):
    """The engine's output. Immutable. Names the deciding rule and every rule
    that fired (not just the decisive one — that is what makes explanations and
    the dry-run simulator useful)."""

    disposition: Disposition
    reason_code: ReasonCode
    human_reason: str                       # one plain sentence for an ops person
    matched_rules: tuple[str, ...] = ()     # every rule that fired, in order
    deciding_rule: Optional[str] = None     # the one that set the disposition
    obligations: tuple[Obligation, ...] = ()
    evaluation_duration_ms: float = 0.0
    policy_set_version: str = ""

    @property
    def allowed(self) -> bool:
        return self.disposition == Disposition.ALLOW

    @property
    def denied(self) -> bool:
        return self.disposition == Disposition.DENY

    @property
    def escalated(self) -> bool:
        return self.disposition == Disposition.REQUIRE_APPROVAL
