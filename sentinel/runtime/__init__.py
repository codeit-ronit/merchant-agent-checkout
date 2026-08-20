"""The in-house agent runtime — a small, owned loop over the provider
abstraction, with the in-loop guard (layer 2) before every tool call.

We wrote the loop rather than adopting a framework so the interception point is
ours and free of version churn on a security-critical path (ADR-002). The loop
contains no provider-specific branching; if it did, the abstraction would have
leaked.
"""

from sentinel.runtime.agent import AgentDefinition, ResourceCeilings
from sentinel.runtime.loop import AgentRunner, RunSuspended
from sentinel.runtime.trace import TraceEmitter

__all__ = ["AgentDefinition", "ResourceCeilings", "AgentRunner", "RunSuspended", "TraceEmitter"]
