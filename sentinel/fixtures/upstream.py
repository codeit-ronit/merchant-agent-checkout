"""``FixtureUpstream`` — a deterministic, in-process double of the Razorpay MCP
server.

Implements the same ``list_tools`` / ``call_tool`` surface the proxy's upstream
client speaks, backed by the synthetic dataset. It is a *faithful* double: the
schemas it advertises come from the same catalog the reference manifest is built
from, and its list endpoints use real offset pagination (``count`` default 10,
max 100, ``skip`` default 0) so an agent that reads only page one and reports
"all reconciled" is a bug the evals can catch.

Money-movement tools mutate an in-memory copy of the dataset and return a
created-entity result, so the proxy's idempotency guard and the red-team's
"did the fixture state change?" grading have something real to observe. State is
reset per run by constructing a fresh ``FixtureUpstream``.
"""

from __future__ import annotations

import copy
from typing import Any, Protocol

from sentinel.fixtures import identifiers as idg
from sentinel.fixtures.dataset import build_dataset
from sentinel.fixtures.tool_catalog import fixture_manifest

DEFAULT_COUNT = 10
MAX_COUNT = 100


class Upstream(Protocol):
    """The interface the proxy's upstream client depends on. ``FixtureUpstream``
    and (in live mode) an MCP-client-backed ``LiveUpstream`` both satisfy it."""

    def list_tools(self) -> list[dict[str, Any]]: ...
    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class UpstreamError(Exception):
    """An upstream-side error (unknown tool, bad id). The proxy fails closed on it."""


class FixtureUpstream:
    def __init__(self, seed: int = 20260821):
        self._ds = build_dataset(seed)
        # money-movement side effects accumulate here (reset per instance)
        self.executed: list[dict[str, Any]] = []

    # --- discovery ---
    def list_tools(self) -> list[dict[str, Any]]:
        return copy.deepcopy(fixture_manifest()["tools"])

    @property
    def dataset(self) -> dict[str, Any]:
        return self._ds

    # --- pagination helper ---
    def _page(self, items: list[dict[str, Any]], arguments: dict[str, Any]) -> dict[str, Any]:
        count = min(int(arguments.get("count", DEFAULT_COUNT) or DEFAULT_COUNT), MAX_COUNT)
        skip = int(arguments.get("skip", 0) or 0)
        page = items[skip: skip + count]
        # Faithful to Razorpay's collection shape: NO has_more / next token — the
        # caller must paginate by increasing skip until a short page.
        return {"entity": "collection", "count": len(page), "items": copy.deepcopy(page)}

    def _find(self, items: list[dict[str, Any]], id_field: str, id_value: str) -> dict[str, Any]:
        for it in items:
            if it.get(id_field) == id_value:
                return copy.deepcopy(it)
        raise UpstreamError(f"no record with {id_field}={id_value}")

    # --- dispatch ---
    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_t_{name}", None)
        if handler is None:
            # Unknown to the fixture. In real life the proxy would already have
            # denied an unclassified tool; reaching here is an upstream error.
            raise UpstreamError(f"fixture upstream has no tool '{name}'")
        return handler(arguments)

    # ---- READ: settlements ----
    def _t_fetch_all_settlements(self, a): return self._page(self._ds["settlements"], a)
    def _t_fetch_settlement_with_id(self, a): return self._find(self._ds["settlements"], "id", a["settlement_id"])
    def _t_fetch_all_instant_settlements(self, a): return self._page([], a)
    def _t_fetch_instant_settlement_with_id(self, a): return self._find(self._ds["settlements"], "id", a["settlement_id"])

    def _t_fetch_settlement_recon_details(self, a):
        # Recon report links settlements to their gross/fees/tax breakdown.
        recon = [{"settlement_id": s["id"], "utr": s["utr"], "amount": s["amount"],
                  "fees": s["fees"], "tax": s["tax"], "gross": s["gross"],
                  "created_at": s["created_at"]} for s in self._ds["settlements"]]
        return self._page(recon, a)

    # ---- READ: payments ----
    def _t_fetch_all_payments(self, a): return self._page(self._ds["payments"], a)
    def _t_fetch_payment(self, a): return self._find(self._ds["payments"], "id", a["payment_id"])
    def _t_fetch_order_payments(self, a): return self._page(self._ds["payments"], a)

    def _t_fetch_payment_card_details(self, a):
        pay = self._find(self._ds["payments"], "id", a["payment_id"])
        return {"id": pay["id"], "card": pay.get("card", {"last4": "0000", "network": "Unknown"})}

    # ---- READ: refunds ----
    def _t_fetch_all_refunds(self, a): return self._page(self._ds["refunds"], a)
    def _t_fetch_refund(self, a): return self._find(self._ds["refunds"], "id", a["refund_id"])
    def _t_fetch_multiple_refunds_for_payment(self, a):
        items = [r for r in self._ds["refunds"] if r["payment_id"] == a["payment_id"]]
        return self._page(items, a)

    # ---- READ: payouts ----
    def _t_fetch_all_payouts(self, a): return self._page(self._ds["payouts"], a)
    def _t_fetch_payout_by_id(self, a): return self._find(self._ds["payouts"], "id", a["payout_id"])

    # ---- READ: fixture-extension disputes / subscriptions ----
    def _t_fetch_all_disputes(self, a): return self._page(self._ds["disputes"], a)
    def _t_fetch_dispute(self, a):
        disp = self._find(self._ds["disputes"], "id", a["dispute_id"])
        disp["payment"] = self._find(self._ds["payments"], "id", disp["payment_id"])
        return disp
    def _t_fetch_all_subscriptions(self, a): return self._page(self._ds["subscriptions"], a)
    def _t_fetch_subscription(self, a): return self._find(self._ds["subscriptions"], "id", a["subscription_id"])

    # ---- MONEY MOVEMENT / WRITES (mutate + record) ----
    def _t_create_refund(self, a):
        refund = {"id": f"rfnd_{idg.Rng(len(self.executed) + 1).letters(12)}",
                  "payment_id": a["payment_id"], "amount": a["amount"],
                  "currency": "INR", "status": "processed", "entity": "refund"}
        self._ds["refunds"].append(refund)
        self.executed.append({"tool": "create_refund", **a})
        return refund

    def _t_capture_payment(self, a):
        self.executed.append({"tool": "capture_payment", **a})
        return {"id": a["payment_id"], "status": "captured", "amount": a["amount"], "entity": "payment"}

    def _t_initiate_payment(self, a):
        pay_id = f"pay_{idg.Rng(len(self.executed) + 7).letters(14)}"
        self.executed.append({"tool": "initiate_payment", **a})
        return {"id": pay_id, "status": "created", "amount": a["amount"], "entity": "payment"}

    def _t_submit_otp(self, a):
        self.executed.append({"tool": "submit_otp", **a})
        return {"id": a["payment_id"], "status": "captured", "entity": "payment"}

    def _t_create_instant_settlement(self, a):
        self.executed.append({"tool": "create_instant_settlement", **a})
        return {"id": f"setl_{idg.Rng(len(self.executed) + 3).letters(12)}",
                "amount": a["amount"], "status": "created", "entity": "settlement"}

    def _t_submit_dispute_evidence(self, a):
        self.executed.append({"tool": "submit_dispute_evidence", **a})
        return {"id": a["dispute_id"], "status": "under_review", "entity": "dispute"}

    # ---- lightweight writes used less often ----
    def _t_update_payment(self, a): return {"id": a["payment_id"], "status": "updated"}
    def _t_update_refund(self, a): return {"id": a["refund_id"], "status": "updated"}
    def _t_create_order(self, a): return {"id": f"order_{idg.Rng(1).letters(12)}", **a, "status": "created"}
    def _t_create_payment_link(self, a): return {"id": f"plink_{idg.Rng(2).letters(12)}", **a, "status": "created"}
