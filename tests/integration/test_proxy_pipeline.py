"""The proxy decision pipeline end to end with a scripted driver (tier 3, no
model): classify -> validate -> rehydrate -> policy -> idempotency -> forward ->
redact -> quarantine -> audit."""

from __future__ import annotations

import pytest

from sentinel.audit.ledger import AuditLedger, InMemoryLedgerRepository
from sentinel.audit.verify import verify_chain
from sentinel.common.canonical import sha256_hex
from sentinel.contracts.decision import InjectedEnv
from sentinel.contracts.enums import Disposition
from sentinel.contracts.reasons import ReasonCode
from sentinel.fixtures.upstream import FixtureUpstream
from sentinel.policy_loader import load_policy_set
from sentinel.proxy.classifier import descriptor_index, reconcile
from sentinel.proxy.idempotency import IdempotencyGuard
from sentinel.proxy.interceptor import Interceptor, Signals
from sentinel.redaction.engine import RedactionSession
from sentinel.redaction.quarantine import QuarantineWrapper

pytestmark = pytest.mark.tier3


def build(policy="strict"):
    up = FixtureUpstream()
    idx = descriptor_index(reconcile(up.list_tools()))
    interc = Interceptor(
        upstream=up, policy_set=load_policy_set(policy),
        ledger=AuditLedger(InMemoryLedgerRepository()),
        session=RedactionSession("run_1", salt=b"fixed-16-byte-sl!"),
        quarantine=QuarantineWrapper(nonce="RUNNONCE"),
        idempotency=IdempotencyGuard(),
        run_meta=dict(run_id="run_1", agent_id="a", agent_version="1", operator_id="op",
                      policy_set_id=policy, git_commit="test"),
    )
    return up, idx, interc


ENV = InjectedEnv(now_epoch_ms=1000)


def test_read_allows_and_redacts():
    _, idx, interc = build()
    out = interc.handle_call(idx["fetch_all_payments"], {"count": 3}, ENV, Signals(), "s", "c")
    assert out.disposition == Disposition.ALLOW
    assert out.redaction_count > 0
    assert "@example.invalid" not in str(out.result)   # emails tokenized


def test_money_movement_escalates_not_executes():
    _, idx, interc = build()
    out = interc.handle_call(idx["create_refund"], {"payment_id": "pay_X", "amount": 50000},
                             ENV, Signals(), "s", "c")
    assert out.disposition == Disposition.REQUIRE_APPROVAL
    assert out.decision.reason_code == ReasonCode.ESCALATE_MONEY_MOVEMENT
    assert not out.executed


def test_approval_allows_and_executes():
    up, idx, interc = build()
    args = {"payment_id": "pay_X", "amount": 50000}
    ah = sha256_hex(args)
    env = InjectedEnv(now_epoch_ms=1000, valid_approval_present=True, approval_argument_hash=ah)
    out = interc.handle_call(idx["create_refund"], args, env, Signals(), "s", "c")
    assert out.disposition == Disposition.ALLOW and out.executed
    assert out.result["status"] == "processed"


def test_idempotent_replay_does_not_re_execute():
    up, idx, interc = build()
    args = {"payment_id": "pay_X", "amount": 50000}
    env = InjectedEnv(now_epoch_ms=1000, valid_approval_present=True, approval_argument_hash=sha256_hex(args))
    before = len(up.dataset["refunds"])
    interc.handle_call(idx["create_refund"], args, env, Signals(), "s1", "c1")
    after_first = len(up.dataset["refunds"])
    out2 = interc.handle_call(idx["create_refund"], args, env, Signals(), "s2", "c2")
    assert after_first == before + 1
    assert len(up.dataset["refunds"]) == after_first     # NOT executed again
    assert out2.idempotent_replay and not out2.executed


@pytest.mark.critical
def test_raw_pii_in_a_tool_argument_is_not_persisted_to_audit():
    """Defense in depth: a raw PII value that reaches a tool-call argument (e.g.
    the model copied it out of an un-tokenized field, or fabricated it) must be
    scrubbed before it lands in the hash-chained audit ledger."""
    _, idx, interc = build()
    # create_payment_link is a reversible write allowed on a clean run
    interc.handle_call(idx["create_payment_link"],
                       {"amount": 1000, "currency": "INR",
                        "description": "contact raj.real@leak.invalid / 9876512345"},
                       ENV, Signals(), "s", "c")
    dumped = str([e.model_dump() if hasattr(e, "model_dump") else e for e in interc.ledger.entries()])
    assert "raj.real@leak.invalid" not in dumped     # email scrubbed from the audit
    assert "9876512345" not in dumped                # phone scrubbed from the audit


@pytest.mark.critical
def test_unissued_token_is_denied_and_flagged():
    _, idx, interc = build()
    out = interc.handle_call(idx["initiate_payment"],
                             {"amount": 1000, "order_id": "order_1", "currency": "INR",
                              "customer_id": "cust_A", "token": "CARD_deadbeef"},
                             ENV, Signals(), "s", "c")
    assert out.disposition == Disposition.DENY
    assert out.decision.reason_code == ReasonCode.DENY_SUSPECTED_EXFILTRATION
    assert out.security_event


def test_schema_invalid_is_denied_not_guessed():
    _, idx, interc = build()
    out = interc.handle_call(idx["create_refund"], {"payment_id": "pay_X"}, ENV, Signals(), "s", "c")
    assert out.disposition == Disposition.DENY
    assert out.decision.reason_code == ReasonCode.DENY_SCHEMA_INVALID


def test_provenance_guard_narrows_after_untrusted():
    """A reversible write allowed on a clean run escalates once untrusted content
    is in context (permission narrowing)."""
    _, idx, interc = build()
    clean = interc.handle_call(idx["create_payment_link"], {"amount": 1000, "currency": "INR"},
                               ENV, Signals(), "s1", "c1")
    assert clean.disposition == Disposition.ALLOW
    dirty = interc.handle_call(idx["create_payment_link"], {"amount": 1000, "currency": "INR"},
                               ENV, Signals(untrusted_in_context=True), "s2", "c2")
    assert dirty.disposition == Disposition.REQUIRE_APPROVAL


def test_untrusted_field_is_quarantined_with_nonce():
    from sentinel.fixtures.dataset import build_dataset
    _, idx, interc = build()
    disp_id = build_dataset()["disputes"][0]["id"]
    out = interc.handle_call(idx["fetch_dispute"], {"dispute_id": disp_id}, ENV, Signals(), "s2", "c2")
    assert out.disposition == Disposition.ALLOW
    assert "RUNNONCE" in str(out.result)               # customer_message quarantined
    assert out.quarantined_fields


def test_audit_chain_of_a_run_verifies():
    _, idx, interc = build()
    interc.handle_call(idx["fetch_all_payments"], {"count": 2}, ENV, Signals(), "s1", "c1")
    interc.handle_call(idx["create_refund"], {"payment_id": "pay_X", "amount": 50000}, ENV, Signals(), "s2", "c2")
    res = verify_chain(interc.ledger.entries())
    assert res.ok and res.entry_count == 2


# --- fail-closed on upstream failure (CLAUDE.md rule 2) ---

class _Raiser:
    """An upstream whose every call fails — stands in for unreachable / erroring MCP."""
    def call_tool(self, name, args):
        raise RuntimeError("upstream unreachable")


class _SlowUpstream:
    """Delegates to a real fixture upstream but sleeps first, so two concurrent
    callers are both in `begin()` before either completes."""
    def __init__(self, real):
        self.real = real
    def call_tool(self, name, args):
        import time
        time.sleep(0.05)
        return self.real.call_tool(name, args)


def test_upstream_error_on_read_fails_closed():
    _, idx, interc = build()
    interc.upstream = _Raiser()
    out = interc.handle_call(idx["fetch_all_payments"], {"count": 3}, ENV, Signals(), "s", "c")
    assert out.disposition == Disposition.DENY               # NOT allow
    assert out.decision.reason_code == ReasonCode.DENY_UPSTREAM_ERROR
    assert out.upstream_error and not out.executed


@pytest.mark.critical
def test_upstream_error_on_write_denies_and_refuses_retry():
    """An ambiguous upstream failure on a money movement must DENY and must NOT be
    silently retried into a possible double execution."""
    up, idx, interc = build()
    args = {"payment_id": "pay_X", "amount": 50000}
    env = InjectedEnv(now_epoch_ms=1000, valid_approval_present=True,
                      approval_argument_hash=sha256_hex(args))
    interc.upstream = _Raiser()
    out1 = interc.handle_call(idx["create_refund"], args, env, Signals(), "s1", "c1")
    assert out1.disposition == Disposition.DENY and out1.upstream_error and not out1.executed
    # the identical call retried is REFUSED (reservation held) — never re-executed
    out2 = interc.handle_call(idx["create_refund"], args, env, Signals(), "s2", "c2")
    assert out2.disposition == Disposition.DENY
    assert out2.decision.reason_code == ReasonCode.DENY_UPSTREAM_ERROR
    assert not out2.executed


@pytest.mark.critical
def test_concurrent_duplicate_write_executes_exactly_once():
    """Two identical money movements racing through the proxy: exactly one executes."""
    import threading
    up, idx, interc = build()
    interc.upstream = _SlowUpstream(up)
    args = {"payment_id": "pay_X", "amount": 50000}
    env = InjectedEnv(now_epoch_ms=1000, valid_approval_present=True,
                      approval_argument_hash=sha256_hex(args))
    before = len(up.dataset["refunds"])
    results: list = []
    barrier = threading.Barrier(2)

    def call(cid):
        barrier.wait()
        results.append(interc.handle_call(idx["create_refund"], args, env, Signals(), cid, cid))

    ts = [threading.Thread(target=call, args=(f"c{i}",)) for i in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sum(1 for r in results if r.executed) == 1        # exactly one real execution
    assert len(up.dataset["refunds"]) == before + 1          # exactly one refund landed
