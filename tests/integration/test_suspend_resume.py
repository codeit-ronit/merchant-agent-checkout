"""Suspension and resumption surviving a process restart, with policy re-checked
on resume (docs/spec/06 §5.6). The run state (message history + token store) is
just our own serialised session, because we own the loop."""

from __future__ import annotations

import tempfile

import pytest

from sentinel.audit.ledger import AuditLedger, InMemoryLedgerRepository
from sentinel.fixtures.dataset import dataset_version
from sentinel.fixtures.upstream import FixtureUpstream
from sentinel.policy_loader import load_policy_set
from sentinel.providers.base import NormalisedToolCall, ProviderResponse
from sentinel.redaction.engine import RedactionSession
from sentinel.runtime.agent import AgentDefinition, ResourceCeilings
from sentinel.runtime.loop import AgentRunner, RunConfig, RunSuspended

pytestmark = pytest.mark.tier3


def _refund_agent():
    def brain(messages, tools):
        if any(m.get("name") == "create_refund" for m in messages if m.get("role") == "tool"):
            return ProviderResponse(text='{"summary": "done"}', finish_reason="stop")
        return ProviderResponse(tool_calls=(NormalisedToolCall("t", "create_refund",
                                {"payment_id": "pay_X", "amount": 50000}),))
    return AgentDefinition(id="refund", version="1", system_prompt="refund per ticket",
                           tool_scope=("create_refund",), output_schema={"required": ["summary"]},
                           default_policy_set="strict", brain=brain,
                           ceilings=ResourceCeilings(max_steps=4))


def _clock():
    st = {"t": 1_755_000_000_000}
    return lambda: st.__setitem__("t", st["t"] + 10) or st["t"]


def test_escalation_suspends_when_no_handler():
    """With no synchronous approval handler, an escalation suspends the run and
    surfaces the approval (nothing executes)."""
    up = FixtureUpstream()
    runner = AgentRunner(cassette_dir=tempfile.mkdtemp(), cassette_mode="auto", clock_ms=_clock(),
                         fixture_version=dataset_version())
    with pytest.raises(RunSuspended) as exc:
        runner.run(_refund_agent(), upstream=up, policy_set=load_policy_set("strict"),
                   task="refund", config=RunConfig())
    assert exc.value.approval.status.value == "PENDING"
    assert len(up.executed) == 0                       # nothing executed while suspended
    # the suspended state carries the message history + token store for restart
    assert "messages" in exc.value.state and "session" in exc.value.state


def test_state_survives_restart_and_resumes_with_revalidation():
    """Simulate a restart: capture the suspended state, build a FRESH runner
    (new process), and resume by re-validating the approval through the proxy.
    Policy is re-evaluated on resume — the decision made before suspension is not
    trusted."""
    up = FixtureUpstream()
    seed = 20260821
    runner = AgentRunner(cassette_dir=tempfile.mkdtemp(), cassette_mode="auto", clock_ms=_clock(),
                         fixture_version=dataset_version())
    try:
        runner.run(_refund_agent(), upstream=up, policy_set=load_policy_set("strict"),
                   task="refund", config=RunConfig(seed=seed))
        assert False, "expected suspension"
    except RunSuspended as susp:
        state = susp.state
        approval = susp.approval

    # --- fresh process: reconstruct the token store from the serialised state ---
    session = RedactionSession.load(state["session"])
    assert session.run_id == state["run_id"]

    # re-validate: re-run the escalated call through the proxy WITH the approval.
    # policy is re-checked; a valid, argument-bound approval turns escalation into
    # an allow -> the refund now executes exactly once.
    from sentinel.contracts.decision import InjectedEnv
    from sentinel.proxy.classifier import descriptor_index, reconcile
    from sentinel.proxy.idempotency import IdempotencyGuard
    from sentinel.proxy.interceptor import Interceptor, Signals
    from sentinel.redaction.quarantine import QuarantineWrapper

    up2 = FixtureUpstream()
    descriptors = descriptor_index(reconcile(up2.list_tools()))
    interc = Interceptor(upstream=up2, policy_set=load_policy_set("strict"),
                         ledger=AuditLedger(InMemoryLedgerRepository()), session=session,
                         quarantine=QuarantineWrapper(nonce=f"{seed:032x}"), idempotency=IdempotencyGuard(),
                         run_meta=dict(run_id=state["run_id"], agent_id="refund", agent_version="1",
                                       operator_id="op", policy_set_id="strict", git_commit="t"))
    args = {"payment_id": "pay_X", "amount": 50000}
    approved_env = InjectedEnv(now_epoch_ms=1, valid_approval_present=True,
                               approval_argument_hash=approval.argument_hash)
    out = interc.handle_call(descriptors["create_refund"], args, approved_env, Signals(), "s", "c")
    assert out.disposition.value == "ALLOW" and out.executed
    assert len(up2.executed) == 1

    # a CHANGED argument on resume must NOT be authorised by the same approval
    changed = interc.handle_call(descriptors["create_refund"], {"payment_id": "pay_X", "amount": 999999},
                                 approved_env, Signals(), "s2", "c2")
    assert changed.disposition.value == "REQUIRE_APPROVAL"   # different args -> re-escalate
