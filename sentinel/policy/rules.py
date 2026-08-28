"""The closed set of rule types.

Deliberately NOT a general expression language — a DSL with arbitrary evaluation
is a new attack surface and an untestable space. Each rule type has a narrow,
well-understood ``evaluate`` that returns at most one ``Outcome`` (or ``None`` if
it did not fire). The engine combines outcomes most-restrictive-wins.

Every rule and every model here is pure and immutable. Money is integer minor
units throughout — no floats, ever.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, ConfigDict

from sentinel.common.money import format_amount
from sentinel.contracts.decision import DecisionContext
from sentinel.contracts.enums import BindingRole, Disposition, RiskClass
from sentinel.contracts.reasons import ReasonCode


@dataclass(frozen=True)
class Outcome:
    """One rule's contribution to a decision."""

    disposition: Disposition
    reason_code: ReasonCode
    rule_id: str
    render_params: dict


class Rule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    description: str = ""
    tags: tuple[str, ...] = ()

    # Subclasses set this; it is the value used in the policy file's ``type``.
    kind: str = "base"

    def evaluate(self, ctx: DecisionContext) -> Optional[Outcome]:  # pragma: no cover
        raise NotImplementedError


def _amt(ctx: DecisionContext) -> str:
    if ctx.money.amount_minor is None:
        return "the amount"
    return format_amount(ctx.money.amount_minor, ctx.money.currency or "INR")


# ---------------------------------------------------------------------------
# tool_class — disposition by risk class
# ---------------------------------------------------------------------------
class ToolClassRule(Rule):
    kind: str = "tool_class"
    # e.g. {"READ": "ALLOW", "MONEY_MOVEMENT": "REQUIRE_APPROVAL", ...}
    class_dispositions: dict[RiskClass, Disposition]

    def evaluate(self, ctx: DecisionContext) -> Optional[Outcome]:
        disp = self.class_dispositions.get(ctx.risk_class)
        if disp is None:
            return None
        if disp == Disposition.ALLOW:
            code = ReasonCode.ALLOW_READ_ONLY if ctx.risk_class == RiskClass.READ else ReasonCode.ALLOW_EXPLICIT_RULE
        elif disp == Disposition.REQUIRE_APPROVAL:
            code = (ReasonCode.ESCALATE_MONEY_MOVEMENT if ctx.risk_class == RiskClass.MONEY_MOVEMENT
                    else ReasonCode.ESCALATE_IRREVERSIBLE if ctx.risk_class == RiskClass.IRREVERSIBLE_WRITE
                    else ReasonCode.ESCALATE_APPROVAL_REQUIRED_RULE)
        else:  # a class explicitly mapped to DENY
            code = ReasonCode.DENY_TOOL_DENIED
        return Outcome(disp, code, self.id, {"tool": ctx.tool_name, "amount": _amt(ctx), "rule": self.id})


# ---------------------------------------------------------------------------
# tool_allow / tool_deny — named tools
# ---------------------------------------------------------------------------
class ToolAllowRule(Rule):
    kind: str = "tool_allow"
    tools: tuple[str, ...] = ()

    def evaluate(self, ctx: DecisionContext) -> Optional[Outcome]:
        if ctx.tool_name in self.tools:
            return Outcome(Disposition.ALLOW, ReasonCode.ALLOW_EXPLICIT_RULE, self.id,
                          {"tool": ctx.tool_name, "rule": self.id})
        return None


class ToolDenyRule(Rule):
    kind: str = "tool_deny"
    tools: tuple[str, ...] = ()

    def evaluate(self, ctx: DecisionContext) -> Optional[Outcome]:
        if ctx.tool_name in self.tools:
            return Outcome(Disposition.DENY, ReasonCode.DENY_TOOL_DENIED, self.id,
                          {"tool": ctx.tool_name, "rule": self.id})
        return None


# ---------------------------------------------------------------------------
# amount_cap — hard monetary ceilings (a DENY: cannot be approved by anyone)
# ---------------------------------------------------------------------------
class AmountCapRule(Rule):
    kind: str = "amount_cap"
    scope: str = "per_call"                 # per_call | per_run | per_window
    max_minor: int
    currency: str = "INR"
    applies_to_classes: tuple[RiskClass, ...] = ()   # scope by risk class
    applies_to_roles: tuple[BindingRole, ...] = ()   # or by binding role (ADR-024)

    def _applies(self, ctx: DecisionContext) -> bool:
        if (not ctx.money.moves_money and ctx.money.amount_minor is None
                and ctx.money.binding_role == BindingRole.NONE):
            return False
        if self.applies_to_classes or self.applies_to_roles:
            return (ctx.risk_class in self.applies_to_classes
                    or ctx.money.binding_role in self.applies_to_roles)
        return True                                   # empty scope => all money-moving

    def _prior(self, ctx: DecisionContext) -> int:
        # per_run accumulates against the right pool: collections against the
        # collection total, everything else against disbursement spend.
        if ctx.money.binding_role == BindingRole.COLLECTION:
            return ctx.env.collected_run_minor
        return ctx.env.spend_run_minor

    def evaluate(self, ctx: DecisionContext) -> Optional[Outcome]:
        if not self._applies(ctx):
            return None
        # A money-moving call whose amount could not be parsed cannot be proven to
        # sit under the hard ceiling, so it fails closed here rather than falling
        # through to an approvable escalation — the ceiling is un-approvable.
        if ctx.money.amount_minor is None:
            return Outcome(Disposition.DENY, ReasonCode.DENY_AMOUNT_EXCEEDS_CAP, self.id, {
                "tool": ctx.tool_name,
                "amount": "an unreadable amount",
                "cap": format_amount(self.max_minor, self.currency),
            })
        amount = ctx.money.amount_minor
        if self.scope == "per_run":
            total = self._prior(ctx) + amount
        elif self.scope == "per_window":
            total = ctx.env.spend_window_minor + amount
        else:
            total = amount
        if total > self.max_minor:
            return Outcome(Disposition.DENY, ReasonCode.DENY_AMOUNT_EXCEEDS_CAP, self.id, {
                "tool": ctx.tool_name,
                "amount": format_amount(total, self.currency),
                "cap": format_amount(self.max_minor, self.currency),
            })
        return None


# ---------------------------------------------------------------------------
# rate_limit — call counts per tool or class per window
# ---------------------------------------------------------------------------
class RateLimitRule(Rule):
    kind: str = "rate_limit"
    scope: str = "tool"                     # tool | class
    key: str = ""                           # tool name or risk-class value; empty => the call's own
    max_count: int
    window: str = "run"

    def evaluate(self, ctx: DecisionContext) -> Optional[Outcome]:
        if self.scope == "tool":
            key = self.key or ctx.tool_name
            if self.key and self.key != ctx.tool_name:
                return None
            count = ctx.env.per_tool_count_run.get(key, 0)
        else:  # class
            key = self.key or ctx.risk_class.value
            if self.key and self.key != ctx.risk_class.value:
                return None
            count = ctx.env.per_class_count_window.get(key, 0)
        if count >= self.max_count:
            return Outcome(Disposition.DENY, ReasonCode.DENY_RATE_LIMIT, self.id, {
                "tool": ctx.tool_name, "count": count, "limit": self.max_count, "window": self.window})
        return None


# ---------------------------------------------------------------------------
# entity_scope — which entities may be targeted
# ---------------------------------------------------------------------------
class EntityScopeRule(Rule):
    kind: str = "entity_scope"
    require_scope: bool = True              # if False, an empty scope is not enforced

    def evaluate(self, ctx: DecisionContext) -> Optional[Outcome]:
        scope = ctx.env.operator_scope_entities
        if not scope:
            return None                       # no declared scope -> nothing to enforce against
        targets = ctx.money.target_entities
        if not targets:
            return None
        out_of_scope = [e for e in targets if e not in scope]
        if out_of_scope:
            return Outcome(Disposition.DENY, ReasonCode.DENY_OUT_OF_SCOPE, self.id,
                          {"tool": ctx.tool_name})
        return None


# ---------------------------------------------------------------------------
# argument_constraint — declarative predicates on argument values
# ---------------------------------------------------------------------------
class ArgumentConstraintRule(Rule):
    kind: str = "argument_constraint"
    arg_path: str
    op: str                                 # equals | in | max | currency_in
    value: object = None

    def _get(self, ctx: DecisionContext):
        cur = ctx.arguments_redacted
        for part in self.arg_path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        return cur

    _KNOWN_OPS = ("equals", "in", "max", "currency_in")

    def evaluate(self, ctx: DecisionContext) -> Optional[Outcome]:
        # An unrecognised op is a misconfigured policy — fail closed FIRST, before
        # any short-circuit, so an absent argument can never mask a bad op.
        if self.op not in self._KNOWN_OPS:
            return Outcome(Disposition.DENY, ReasonCode.DENY_ARGUMENT_CONSTRAINT, self.id, {
                "tool": ctx.tool_name, "detail": f"unknown constraint op '{self.op}'"})
        actual = self._get(ctx)
        violated = False
        if self.op == "currency_in":
            # Applies only to calls that actually carry a currency (money calls).
            cur = ctx.money.currency if ctx.money.currency is not None else actual
            if cur is None:
                return None
            violated = cur not in (self.value or [])
        elif actual is None:
            # "constrain the value IF present" — an absent field is not this
            # rule's concern (missing required args are caught by schema checks).
            return None
        elif self.op == "equals":
            violated = actual != self.value
        elif self.op == "in":
            violated = actual not in (self.value or [])
        elif self.op == "max":
            violated = isinstance(actual, int) and actual > int(self.value)
        else:
            violated = True  # unknown op -> fail closed
        if violated:
            return Outcome(Disposition.DENY, ReasonCode.DENY_ARGUMENT_CONSTRAINT, self.id, {
                "tool": ctx.tool_name, "detail": f"{self.arg_path} {self.op} {self.value}"})
        return None


# ---------------------------------------------------------------------------
# time_window — when actions are permitted
# ---------------------------------------------------------------------------
class TimeWindowRule(Rule):
    kind: str = "time_window"
    applies_to_classes: tuple[RiskClass, ...] = ()
    allowed_hours: tuple[int, int] = (0, 24)     # [start, end) in operator-local hours
    allowed_weekdays: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)
    window_label: str = "the permitted window"

    def evaluate(self, ctx: DecisionContext) -> Optional[Outcome]:
        if self.applies_to_classes and ctx.risk_class not in self.applies_to_classes:
            return None
        hour = ctx.env.now_local_hour
        wd = ctx.env.now_weekday
        start, end = self.allowed_hours
        ok = (start <= hour < end) and (wd in self.allowed_weekdays)
        if not ok:
            return Outcome(Disposition.DENY, ReasonCode.DENY_OUTSIDE_TIME_WINDOW, self.id,
                          {"tool": ctx.tool_name, "window": self.window_label})
        return None


# ---------------------------------------------------------------------------
# approval_required — conditions that force escalation
# ---------------------------------------------------------------------------
class ApprovalRequiredRule(Rule):
    kind: str = "approval_required"
    risk_classes: tuple[RiskClass, ...] = ()
    amount_over_minor: Optional[int] = None
    tools: tuple[str, ...] = ()
    currency: str = "INR"

    def evaluate(self, ctx: DecisionContext) -> Optional[Outcome]:
        if self.tools and ctx.tool_name in self.tools:
            return Outcome(Disposition.REQUIRE_APPROVAL, ReasonCode.ESCALATE_APPROVAL_REQUIRED_RULE,
                          self.id, {"tool": ctx.tool_name, "rule": self.id})
        if self.risk_classes and ctx.risk_class in self.risk_classes:
            code = (ReasonCode.ESCALATE_MONEY_MOVEMENT if ctx.risk_class == RiskClass.MONEY_MOVEMENT
                    else ReasonCode.ESCALATE_IRREVERSIBLE if ctx.risk_class == RiskClass.IRREVERSIBLE_WRITE
                    else ReasonCode.ESCALATE_APPROVAL_REQUIRED_RULE)
            return Outcome(Disposition.REQUIRE_APPROVAL, code, self.id,
                          {"tool": ctx.tool_name, "amount": _amt(ctx), "rule": self.id})
        if (self.amount_over_minor is not None and ctx.money.amount_minor is not None
                and ctx.money.amount_minor > self.amount_over_minor):
            return Outcome(Disposition.REQUIRE_APPROVAL, ReasonCode.ESCALATE_AMOUNT_THRESHOLD, self.id, {
                "tool": ctx.tool_name, "amount": _amt(ctx),
                "threshold": format_amount(self.amount_over_minor, self.currency)})
        return None


# ---------------------------------------------------------------------------
# provenance_guard — permissions NARROW when untrusted content is in context.
# This is the structural answer to prompt injection.
# ---------------------------------------------------------------------------
class ProvenanceGuardRule(Rule):
    """Permission NARROWING when untrusted content is in context.

    Critically, narrowing must only ever TIGHTEN — it must never rescue a
    fail-closed denial into an approval (that would be a loosening and would
    break monotonicity). So this rule itself emits only the pure-tightening case
    (an out-of-scope read under untrusted -> DENY); the ALLOW->REQUIRE_APPROVAL
    downgrade for writes is applied by the engine as a post-combination step,
    which can see the already-combined disposition and only ever downgrades an
    ALLOW. The engine activates that step when a provenance_guard rule is present.
    """

    kind: str = "provenance_guard"
    escalate_irreversible: bool = True
    escalate_reversible: bool = True
    restrict_reads_to_scope: bool = True

    def evaluate(self, ctx: DecisionContext) -> Optional[Outcome]:
        if not ctx.untrusted_in_context:
            return None
        if ctx.risk_class == RiskClass.READ and self.restrict_reads_to_scope:
            scope = ctx.env.operator_scope_entities
            targets = ctx.money.target_entities
            # after ingesting untrusted text the agent cannot go exploring: a read
            # to an entity outside the operator's original scope is denied (a pure
            # tightening — DENY is the most restrictive disposition).
            if scope and targets and any(e not in scope for e in targets):
                return Outcome(Disposition.DENY, ReasonCode.DENY_OUT_OF_SCOPE, self.id,
                              {"tool": ctx.tool_name})
        return None


# ---------------------------------------------------------------------------
# counterparty_novelty — a payout/charge to an unseen destination always escalates
# ---------------------------------------------------------------------------
class CounterpartyNoveltyRule(Rule):
    kind: str = "counterparty_novelty"

    def evaluate(self, ctx: DecisionContext) -> Optional[Outcome]:
        cp = ctx.money.counterparty_ref
        if cp and cp not in ctx.env.known_counterparties:
            return Outcome(Disposition.REQUIRE_APPROVAL, ReasonCode.ESCALATE_NOVEL_COUNTERPARTY,
                          self.id, {"tool": ctx.tool_name})
        return None


class CollectionTierRule(Rule):
    """Amount governance for COLLECTION_BINDING tools (order / payment link / QR),
    keyed off the binding ROLE, not the risk class (ADR-024). Three tiers:

    * <= review_over_minor            -> no escalation (baseline allow)
    * review_over_minor..elevated     -> standard review (ESCALATE_AMOUNT_THRESHOLD)
    * > elevated_over_minor           -> ELEVATED review — the reviewer must confirm
                                         the amount; the engine attaches
                                         CONFIRM_AMOUNT + AUDIT_ELEVATED obligations.

    A collection with an unreadable amount is treated as elevated (fail toward the
    stricter tier). Collections never hard-DENY on size — collecting is the
    low-risk, refundable direction; the ceiling forces deliberate attention."""

    kind: str = "collection_tier"
    review_over_minor: int
    elevated_over_minor: int
    currency: str = "INR"

    def evaluate(self, ctx: DecisionContext) -> Optional[Outcome]:
        if ctx.money.binding_role != BindingRole.COLLECTION:
            return None
        amt = ctx.money.amount_minor
        if amt is None or amt > self.elevated_over_minor:
            shown = format_amount(amt, self.currency) if amt is not None else "an unreadable amount"
            return Outcome(Disposition.REQUIRE_APPROVAL, ReasonCode.ESCALATE_ELEVATED_COLLECTION,
                           self.id, {"tool": ctx.tool_name, "amount": shown,
                                     "threshold": format_amount(self.elevated_over_minor, self.currency)})
        if amt > self.review_over_minor:
            return Outcome(Disposition.REQUIRE_APPROVAL, ReasonCode.ESCALATE_AMOUNT_THRESHOLD,
                           self.id, {"tool": ctx.tool_name, "amount": format_amount(amt, self.currency),
                                     "threshold": format_amount(self.review_over_minor, self.currency)})
        return None


class CollectionBoundAmountRule(Rule):
    """A COLLECTION must bind a concrete amount, or it cannot be governed. Refuses
    (DENY) a variable-amount collection — an explicit ``fixed_amount: false`` (e.g.
    a variable QR code, where the payer chooses any amount and no tier can bind it)
    or a collection that carries no readable amount at all. Un-approvable: an
    ungovernable collection is not made safe by a reviewer clicking approve."""

    kind: str = "collection_bound_amount"

    def evaluate(self, ctx: DecisionContext) -> Optional[Outcome]:
        if ctx.money.binding_role != BindingRole.COLLECTION:
            return None
        args = ctx.arguments_redacted or {}
        if args.get("fixed_amount") is False:
            return Outcome(Disposition.DENY, ReasonCode.DENY_UNBOUNDED_COLLECTION, self.id,
                           {"tool": ctx.tool_name})
        if ctx.money.amount_minor is None:
            return Outcome(Disposition.DENY, ReasonCode.DENY_UNBOUNDED_COLLECTION, self.id,
                           {"tool": ctx.tool_name})
        return None


RULE_TYPES: dict[str, type[Rule]] = {
    "tool_class": ToolClassRule,
    "collection_tier": CollectionTierRule,
    "collection_bound_amount": CollectionBoundAmountRule,
    "tool_allow": ToolAllowRule,
    "tool_deny": ToolDenyRule,
    "amount_cap": AmountCapRule,
    "rate_limit": RateLimitRule,
    "entity_scope": EntityScopeRule,
    "argument_constraint": ArgumentConstraintRule,
    "time_window": TimeWindowRule,
    "approval_required": ApprovalRequiredRule,
    "provenance_guard": ProvenanceGuardRule,
    "counterparty_novelty": CounterpartyNoveltyRule,
}


class PolicySet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    version: str
    description: str = ""
    author: str = ""
    # permissive set is the red-team baseline: blocked in live mode, loud warning.
    is_permissive_baseline: bool = False
    rules: tuple[Rule, ...] = ()

    def rule_ids(self) -> list[str]:
        return [r.id for r in self.rules]
