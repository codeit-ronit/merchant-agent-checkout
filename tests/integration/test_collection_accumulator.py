"""The collection aggregate counter is only trustworthy if (1) it tallies executed
collections, never rejected/denied attempts, and (2) it travels with the suspend
state so a resume does not restart the cap at zero. Both are exactly where a
counter-based control quietly fails."""

from __future__ import annotations

import tempfile

import pytest

from sentinel.fixtures.dataset import dataset_version
from sentinel.fixtures.upstream import FixtureUpstream
from sentinel.policy_loader import load_policy_set
from sentinel.providers.base import NormalisedToolCall, ProviderResponse
from sentinel.runtime.agent import AgentDefinition, ResourceCeilings
from sentinel.runtime.loop import AgentRunner, RunConfig, RunSuspended

pytestmark = pytest.mark.tier3


def _clock():
    st = {"t": 1_755_000_000_000}
    return lambda: st.__setitem__("t", st["t"] + 10) or st["t"]


def _order_agent(brain):
    return AgentDefinition(id="collector", version="1", system_prompt="raise orders",
                           tool_scope=("create_order",), output_schema={"required": ["summary"]},
                           default_policy_set="strict", brain=brain,
                           ceilings=ResourceCeilings(max_steps=16, max_tool_calls=16))


def _count_orders(messages):
    return sum(1 for m in messages if m.get("role") == "tool" and m.get("name") == "create_order")


def test_rejected_collection_does_not_count_toward_the_aggregate():
    """Four ₹1.5L orders (₹6L total, over the ₹5L aggregate) that are all REJECTED
    must never trip the aggregate cap — rejected attempts bind nothing."""
    def brain(messages, tools):
        if _count_orders(messages) < 4:
            return ProviderResponse(tool_calls=(NormalisedToolCall("t", "create_order",
                                    {"amount": 15000000, "currency": "INR"}),))
        return ProviderResponse(text='{"summary": "done"}', finish_reason="stop")

    up = FixtureUpstream()
    runner = AgentRunner(cassette_dir=tempfile.mkdtemp(), cassette_mode="auto", clock_ms=_clock(),
                         fixture_version=dataset_version())
    rec = runner.run(_order_agent(brain), upstream=up, policy_set=load_policy_set("strict"),
                     task="orders", config=RunConfig(), approval_handler=lambda a: False)  # reject all
    # 4 rejected escalations, ₹6L attempted — yet the aggregate cap (₹5L) was
    # NEVER tripped, proving rejected attempts do not accumulate.
    assert "DENY_AMOUNT_EXCEEDS_CAP" not in rec.denials_by_reason
    assert rec.approvals_rejected == 4


def test_collection_accumulator_travels_with_suspend_state():
    """A run that executes a ₹5k order (counts) then escalates a ₹15k order with no
    handler (suspends) must carry the ₹5k in the suspend state — else a resume
    restarts the cap at zero."""
    def brain(messages, tools):
        n = _count_orders(messages)
        if n == 0:
            return ProviderResponse(tool_calls=(NormalisedToolCall("t1", "create_order",
                                    {"amount": 500000, "currency": "INR"}),))     # ₹5k -> allow+execute
        if n == 1:
            return ProviderResponse(tool_calls=(NormalisedToolCall("t2", "create_order",
                                    {"amount": 1500000, "currency": "INR"}),))    # ₹15k -> escalate
        return ProviderResponse(text='{"summary": "done"}', finish_reason="stop")

    up = FixtureUpstream()
    runner = AgentRunner(cassette_dir=tempfile.mkdtemp(), cassette_mode="auto", clock_ms=_clock(),
                         fixture_version=dataset_version())
    with pytest.raises(RunSuspended) as exc:
        runner.run(_order_agent(brain), upstream=up, policy_set=load_policy_set("strict"),
                   task="orders", config=RunConfig())    # no handler -> escalation suspends
    acc = exc.value.state.get("accumulators", {})
    assert acc.get("collected_run_minor") == 500000      # the executed ₹5k survives the suspend
    assert acc.get("spend_run_minor") == 0               # no disbursement happened
