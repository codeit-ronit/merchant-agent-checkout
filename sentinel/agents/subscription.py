"""Agent 3 — Subscription Recovery (MONEY_MOVEMENT).

Diagnoses failed recurring payments, proposes a recovery plan, and executes ONLY
what a human has explicitly approved — with every money-moving retry individually
escalated. This is the agent that must never act alone; it exists to exercise the
full escalation path.

Non-obvious properties honoured:
* Plan approval != action approval — the plan is structured output; each retry is
  a separate, argument-bound escalation.
* Retry viability differs by failure cause (retrying a hard decline is futile and
  costly), classified before proposing.
* Novel counterparty is the sharp edge — a retry against a never-seen mandate
  escalates via ``counterparty_novelty``. Provably incapable of unattended money
  movement: the class floor + strict policy escalate every retry.
"""

from __future__ import annotations

import json

from sentinel.providers.base import NormalisedToolCall, ProviderResponse
from sentinel.runtime.agent import AgentDefinition, ResourceCeilings

SYSTEM_PROMPT = (
    "You recover failed subscription payments. Fetch failed subscriptions, "
    "classify each failure cause, and propose a recovery plan. Only retry causes "
    "that are plausibly recoverable (insufficient funds, technical declines) — "
    "never retry a hard issuer decline or an expired mandate. Every retry moves "
    "money and must be individually authorised by a human; never act on your own."
)

OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["summary", "plan", "retried", "escalated"],
    "properties": {"summary": {"type": "string"}, "plan": {"type": "array"},
                   "retried": {"type": "integer"}, "escalated": {"type": "integer"}},
}

# Real tools only (verified against the live tools/list): the published server
# exposes no create_registration_link, so recovery retries go through
# initiate_payment (which really requires amount + order_id).
TOOL_SCOPE = ("fetch_all_subscriptions", "fetch_subscription", "fetch_all_payments",
              "initiate_payment")

RETRY_VIABLE = {"insufficient_funds", "technical_decline"}


def _subscriptions_from(messages: list[dict]) -> list[dict]:
    subs = []
    for m in messages:
        if m.get("role") == "tool" and m.get("name") == "fetch_all_subscriptions":
            try:
                subs.extend(json.loads(m["content"]).get("items", []))
            except Exception:
                pass
    return subs


def make_brain(*, force_unauthorised: bool = False):
    """``force_unauthorised`` models a red-team attempt to move money without
    approval; the control plane escalates/denies it regardless."""

    def brain(messages: list[dict], tools: list[dict]) -> ProviderResponse:
        subs = _subscriptions_from(messages)
        retried_ids = {m.get("tool_call_id") for m in messages
                       if m.get("role") == "tool" and m.get("name") == "initiate_payment"}

        if not subs:
            return ProviderResponse(tool_calls=(NormalisedToolCall(
                "tc_fetch", "fetch_all_subscriptions", {"count": 100}),))

        # propose one retry per viable failed subscription; each is a money move.
        for i, s in enumerate(subs):
            cause = s.get("last_failure", {}).get("cause")
            if cause in RETRY_VIABLE:
                tc_id = f"tc_retry_{i}"
                if tc_id in retried_ids:
                    continue
                return ProviderResponse(
                    text=f"Retrying subscription {s['id']} (cause: {cause}).",
                    tool_calls=(NormalisedToolCall(tc_id, "initiate_payment", {
                        "amount": s["amount"], "currency": "INR",
                        "order_id": f"order_retry_{s['id']}",   # real initiate_payment requires order_id
                        "customer_id": s["mandate_fund_account"]}),))

        # final plan
        plan = [{"subscription_id": s["id"], "cause": s.get("last_failure", {}).get("cause"),
                 "action": "retry" if s.get("last_failure", {}).get("cause") in RETRY_VIABLE else "no_retry",
                 "reason": ("recoverable — retry after human approval"
                            if s.get("last_failure", {}).get("cause") in RETRY_VIABLE
                            else "hard failure — retrying is futile and costly")}
                for s in subs]
        retried = sum(1 for m in messages if m.get("role") == "tool" and m.get("name") == "initiate_payment"
                      and "processed" in str(m.get("content", "")) or "created" in str(m.get("content", "")))
        report = {"summary": f"Diagnosed {len(subs)} subscriptions; "
                             f"{sum(1 for p in plan if p['action'] == 'retry')} recoverable.",
                  "plan": plan, "retried": retried,
                  "escalated": sum(1 for p in plan if p["action"] == "retry")}
        return ProviderResponse(text=json.dumps(report, ensure_ascii=False), finish_reason="stop")

    return brain


def build_agent(*, force_unauthorised: bool = False) -> AgentDefinition:
    return AgentDefinition(
        id="subscription-recovery", version="1", system_prompt=SYSTEM_PROMPT,
        tool_scope=TOOL_SCOPE, output_schema=OUTPUT_SCHEMA, default_policy_set="strict",
        brain=make_brain(force_unauthorised=force_unauthorised),
        ceilings=ResourceCeilings(max_steps=12, max_tool_calls=15))
