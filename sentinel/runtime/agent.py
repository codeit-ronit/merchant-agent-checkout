"""An agent is a declarative bundle, not a script.

The system prompt is documentation of intent — NEVER the security boundary. Its
hash is recorded in the RunRecord because prompt changes are the most common
cause of behaviour changes, and without version tracking a regression cannot be
attributed to its cause.

The declared tool scope is a *narrowing* of what policy permits, never a
widening: an agent that declares a tool absent from the manifest fails at
startup, not at call time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Callable

from sentinel.providers.base import ProviderResponse

# A deterministic model stand-in: (messages, tools) -> ProviderResponse.
Brain = Callable[[list[dict], list[dict]], ProviderResponse]


@dataclass(frozen=True)
class ResourceCeilings:
    """Runtime invariants that hold even under a misconfigured policy."""
    max_steps: int = 12
    max_tool_calls: int = 30
    max_wall_clock_ms: int = 120_000     # excludes time suspended awaiting approval
    max_cost_micros: int | None = None
    max_provider_retries: int = 3


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    version: str
    system_prompt: str
    tool_scope: tuple[str, ...]           # tools this agent may request at all
    output_schema: dict[str, Any]
    default_policy_set: str
    brain: Brain                          # deterministic offline stand-in for the model
    ceilings: ResourceCeilings = field(default_factory=ResourceCeilings)

    @property
    def system_prompt_hash(self) -> str:
        return sha256(self.system_prompt.encode("utf-8")).hexdigest()[:16]

    def validate_scope(self, available_tool_names: set[str]) -> None:
        """Fail at startup if the agent declares a tool the manifest does not
        offer (a scope that widens beyond what exists)."""
        missing = [t for t in self.tool_scope if t not in available_tool_names]
        if missing:
            raise ValueError(
                f"agent '{self.id}' declares tools not in the manifest: {missing}. "
                f"Tool scope must narrow what policy permits, never widen it.")
