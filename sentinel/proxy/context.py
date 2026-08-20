"""Shared ``DecisionContext`` builder.

Both enforcement layers — the in-loop guard (runtime) and the authoritative proxy
— build their context here and evaluate the SAME pure engine. Using one builder
is what makes "the layers cannot silently diverge" structurally true; the
layer-agreement test guards against a regression that breaks that.
"""

from __future__ import annotations

from typing import Any

from sentinel.common.canonical import sha256_hex
from sentinel.contracts.decision import DecisionContext, InjectedEnv, MoneySemantics
from sentinel.contracts.tools import ToolDescriptor
from sentinel.proxy.idempotency import idempotency_key


def _get_path(obj: dict, path: str) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def money_semantics(d: ToolDescriptor, args: dict) -> MoneySemantics:
    amount = _get_path(args, d.amount_arg_path) if d.amount_arg_path else None
    currency = _get_path(args, d.currency_arg_path) if d.currency_arg_path else None
    targets = tuple(str(_get_path(args, p)) for p in d.entity_arg_paths if _get_path(args, p) is not None)
    cp = _get_path(args, d.counterparty_arg_path) if d.counterparty_arg_path else None
    return MoneySemantics(
        moves_money=d.moves_money,
        amount_minor=amount if isinstance(amount, int) and not isinstance(amount, bool) else None,
        currency=currency if isinstance(currency, str) else ("INR" if d.moves_money else None),
        target_entities=targets,
        counterparty_ref=str(cp) if cp is not None else None,
    )


def build_context(*, descriptor: ToolDescriptor, arguments: dict, env: InjectedEnv,
                  run_meta: dict, policy_version: str, step_id: str, call_id: str,
                  untrusted_in_context: bool = False, injection_score: float = 0.0,
                  provenance_present: tuple = (), model_stated_intent: str | None = None,
                  ) -> DecisionContext:
    arg_hash = sha256_hex(arguments)
    return DecisionContext(
        run_id=run_meta["run_id"], step_id=step_id, call_id=call_id,
        agent_id=run_meta["agent_id"], agent_version=run_meta["agent_version"],
        operator_id=run_meta["operator_id"], policy_set_id=run_meta["policy_set_id"],
        policy_set_version=policy_version,
        tool_name=descriptor.name, upstream_tool_name=descriptor.upstream_name,
        risk_class=descriptor.risk_class, arguments_redacted=arguments,
        argument_hash=arg_hash,
        idempotency_key=idempotency_key(run_meta["run_id"], descriptor.upstream_name, arguments),
        env=env, provenance_present=provenance_present,
        quarantined_content_in_context=untrusted_in_context,
        model_stated_intent=model_stated_intent, injection_suspicion_score=injection_score,
        money=money_semantics(descriptor, arguments),
    )
