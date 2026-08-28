"""The pure policy engine — layer of the system that decides ALLOW / DENY /
REQUIRE_APPROVAL for a tool call.

PURITY IS A HARD CONSTRAINT (enforced by tests/unit/test_policy_purity.py):
this package imports no I/O — no clock, no network, no database, no randomness,
no filesystem. Everything the engine needs arrives in ``DecisionContext``. The
YAML loader that reads policy files lives OUTSIDE this package
(``sentinel.policy_loader``) precisely so this package stays pure.
"""

from sentinel.policy.engine import evaluate
from sentinel.policy.rules import (
    RULE_TYPES,
    AmountCapRule,
    ApprovalRequiredRule,
    ArgumentConstraintRule,
    CollectionTierRule,
    CounterpartyNoveltyRule,
    EntityScopeRule,
    PolicySet,
    ProvenanceGuardRule,
    RateLimitRule,
    Rule,
    TimeWindowRule,
    ToolAllowRule,
    ToolClassRule,
    ToolDenyRule,
)

__all__ = [
    "evaluate", "PolicySet", "Rule", "RULE_TYPES",
    "ToolClassRule", "ToolAllowRule", "ToolDenyRule", "AmountCapRule",
    "RateLimitRule", "EntityScopeRule", "ArgumentConstraintRule",
    "TimeWindowRule", "ApprovalRequiredRule", "ProvenanceGuardRule",
    "CounterpartyNoveltyRule", "CollectionTierRule",
]
