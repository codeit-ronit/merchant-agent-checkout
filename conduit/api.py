"""The commerce API — the split view's data source (09-UI §9's data contract).

A purchase runs deterministically server-side (fixture upstream, the shipping
buyer brain — a real model when SENTINEL_LIVE is set); every trace event is
enriched AT CAPTURE with a commerce snapshot {mandate, cart, verdicts} and the
stream endpoint replays the enriched trace paced — so the left pane's words
and the right pane's machinery are driven by the SAME events, and the
signature synchrony is structural rather than choreographed.

Mounted into the operator server with one include (the allowed extension
shape: SENTINEL untouched beyond the mount line).
"""

from __future__ import annotations

import ipaddress
import socket
import threading
import time
import uuid
from urllib.parse import urlparse

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from conduit.cart.gate import CommitGate
from conduit.cart.service import CartService
from conduit.cart.store import InMemoryCartRepository
from conduit.catalog.seed import MERCHANT, seed_catalog
from conduit.catalog.service import CatalogService
from conduit.catalog.web_onboard import NoStructuredMarkup, parse_storefront_html
from conduit.catalog.store import InMemoryCatalogRepository
from conduit.mandate.ledger import DrawdownLedger, InMemoryLedgerRepository
from conduit.mandate.service import MandateService
from conduit.mcp.upstream import ConduitUpstream
from conduit.rail import ModelledSettlementRail
from conduit.settlement import SettlementCoordinator
from sentinel.audit.ledger import AuditLedger, InMemoryLedgerRepository as AuditRepo
from sentinel.fixtures.dataset import dataset_version
from sentinel.fixtures.upstream import FixtureUpstream
from sentinel.policy_loader import load_policy_set
from sentinel.runtime.loop import AgentRunner, RunConfig

router = APIRouter(prefix="/api/commerce", tags=["commerce"])

WEEK_MS = 7 * 24 * 3600 * 1000


class CommerceState:
    """One merchant, one world, rebuilt per process — demo state, not a DB."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.catalog = CatalogService(InMemoryCatalogRepository())
        seed_catalog(self.catalog)
        self.drawdown = DrawdownLedger(InMemoryLedgerRepository())
        self.mandates = MandateService(self.drawdown)
        self.cart_repo = InMemoryCartRepository()
        self.carts = CartService(self.cart_repo, self.catalog, self.drawdown)
        self.inner = FixtureUpstream()
        self.rail = ModelledSettlementRail()
        self.rail.subscribe(SettlementCoordinator(self.carts, self.drawdown,
                                                  self._now_ms).on_payment)
        self.upstream = ConduitUpstream(self.inner, self.catalog, cart=self.carts,
                                        gate=CommitGate(self.carts, self.drawdown, self.inner),
                                        rail=self.rail, now_ms_fn=self._now_ms)
        self.audit = AuditLedger(AuditRepo())
        self.purchases: dict[str, dict] = {}
        self.mandate_ids: list[str] = []

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    # ------------------------------------------------------------- snapshots
    def _latest_cart(self, after_cart_id: str):
        """This RUN's cart only: the newest cart created after the run began.
        Without the baseline, a second purchase's early events would carry the
        previous purchase's cart — found by the HTTP smoke test."""
        carts = getattr(self.cart_repo, "_carts", {})
        fresh = [c for c in carts.values() if c.cart_id > after_cart_id]
        return max(fresh, key=lambda c: c.cart_id) if fresh else None

    def snapshot(self, mandate_id: str, *, after_cart_id: str = "",
                 after_audit_seq: int = -1) -> dict:
        snap: dict = {"mandate": None, "cart": None, "commit": None, "payment": None}
        try:
            snap["mandate"] = self.mandates.public_view(mandate_id, now_ms=self._now_ms())
        except Exception:
            pass
        record = self._latest_cart(after_cart_id)
        if record is not None:
            try:
                snap["cart"] = self.carts.price(record, now_ms=self._now_ms()).to_public()
            except Exception:
                snap["cart"] = {"cart_id": record.cart_id, "status": record.status.value}
            # THIS run's latest commit verdicts, straight from the audit
            # ledger (app_outcome, ADR-033) next to the policy verdict
            commits = [e for e in self.audit.entries()
                       if e.tool_name == "cart_commit" and e.sequence > after_audit_seq]
            if commits:
                last = commits[-1]
                snap["commit"] = {
                    "policy": {"disposition": last.decision.disposition.value if last.decision else None,
                               "reason_code": last.decision.reason_code.value if last.decision else None,
                               "human_reason": last.decision.human_reason if last.decision else None},
                    "commerce": last.app_outcome,
                    "order_id": record.committed_order_id,
                }
            if record.committed_order_id:
                payments = self.rail.fetch_order_payments(record.committed_order_id)
                if payments["count"]:
                    snap["payment"] = payments["items"][-1]
        return snap

    # ------------------------------------------------------------- purchase
    def run_purchase(self, task: str, mandate_id: str, *, decline_demo: bool = False,
                     timeout_demo: bool = False, reprice_demo: bool = False) -> dict:
        with self._lock:
            run_ref = f"buy_{uuid.uuid4().hex[:10]}"
            full_task = f"{task.rstrip('. ')} — using mandate {mandate_id}."
            if decline_demo:
                full_task += " Pay with failure@razorpay."
            if timeout_demo:
                self.rail.arm_timeout("captured")
            upstream = self.upstream
            if reprice_demo:
                state = {"done": False}
                base, catalog, now = self.upstream, self.catalog, self._now_ms

                class Bump:
                    def list_tools(self):
                        return base.list_tools()

                    def call_tool(self, name, args):
                        if name == "cart_commit" and not state["done"]:
                            state["done"] = True
                            item = catalog.get_item("itm_steamed-rice")
                            catalog.set_price("itm_steamed-rice",
                                              item.price_minor + 3000, now_ms=now())
                        return base.call_tool(name, args)

                upstream = Bump()

            trace: list[dict] = []
            carts_before = getattr(self.cart_repo, "_carts", {})
            cart_baseline = max(carts_before.keys(), default="")
            entries_before = self.audit.entries()
            audit_baseline = entries_before[-1].sequence if entries_before else -1

            def sink(evt: dict) -> None:
                enriched = dict(evt)
                enriched["commerce"] = self.snapshot(
                    mandate_id, after_cart_id=cart_baseline,
                    after_audit_seq=audit_baseline)
                trace.append(enriched)

            import tempfile

            from conduit.agents.buyer import BUYER
            # A PRIVATE cassette dir per purchase: the demo state resets its
            # deterministic counters (mnd_000001, cart_000001) while a shared
            # dir would persist — message-identical keys could then replay a
            # stale response against a different world. The offline brain is
            # deterministic, so replay buys nothing here anyway.
            runner = AgentRunner(cassette_dir=tempfile.mkdtemp(),
                                 cassette_mode="auto", ledger=self.audit,
                                 fixture_version=dataset_version(), trace_sink=sink)
            record = runner.run(
                BUYER, upstream=upstream, policy_set=load_policy_set("commerce"),
                task=full_task,
                config=RunConfig(mandate_env_fn=lambda: self.mandates.to_env(mandate_id),
                                 merchant_id=MERCHANT.merchant_id))
            result = {
                "run_ref": run_ref,
                "task": full_task,
                "terminal": record.terminal_state.value,
                "output": record.output,
                "final_snapshot": self.snapshot(mandate_id, after_cart_id=cart_baseline,
                                                after_audit_seq=audit_baseline),
            }
            self.purchases[run_ref] = {"trace": trace, "result": result}
            return result


state = CommerceState()


# ---------------------------------------------------------------- routes
@router.get("/catalog")
def get_catalog():
    feed = state.catalog.bulk_feed()
    merchant = state.catalog.merchant()
    return {
        "merchant": {"merchant_id": merchant.merchant_id,
                     "display_name": merchant.display_name,
                     "max_upsell_offers_per_cart": merchant.max_upsell_offers_per_cart},
        "claim": {"catalog": "modelled", "orders": "razorpay-test-mode"},
        **feed,
        "rules": [{"rule_id": r.rule_id, "trigger_item_id": r.trigger_item_id,
                   "offer_item_id": r.offer_item_id}
                  for r in state.catalog.upsell_rules()],
    }


class MandateReq(BaseModel):
    amount_minor: int
    expires_in_days: int = 7


@router.post("/mandates")
def create_mandate(req: MandateReq):
    try:
        now = state._now_ms()
        mandate = state.mandates.create(
            locked_minor=req.amount_minor, currency="INR",
            scope_merchant_id=MERCHANT.merchant_id,
            expires_at_ms=now + req.expires_in_days * 24 * 3600 * 1000,
            instrument_contact="9876543210", now_ms=now)
        state.mandate_ids.append(mandate.mandate_id)
        return state.mandates.public_view(mandate.mandate_id, now_ms=now)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.get("/mandates")
def list_mandates():
    now = state._now_ms()
    return [state.mandates.public_view(mid, now_ms=now) for mid in state.mandate_ids]


@router.post("/mandates/{mandate_id}/revoke")
def revoke_mandate(mandate_id: str):
    try:
        state.mandates.revoke(mandate_id, now_ms=state._now_ms())
        return state.mandates.public_view(mandate_id, now_ms=state._now_ms())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)


class PurchaseReq(BaseModel):
    task: str
    mandate_id: str
    decline_demo: bool = False
    timeout_demo: bool = False
    reprice_demo: bool = False


@router.post("/purchase")
def purchase(req: PurchaseReq):
    if req.mandate_id not in state.mandate_ids:
        return JSONResponse({"error": f"no mandate {req.mandate_id} — set one aside first"},
                            status_code=400)
    try:
        return state.run_purchase(req.task, req.mandate_id,
                                  decline_demo=req.decline_demo,
                                  timeout_demo=req.timeout_demo,
                                  reprice_demo=req.reprice_demo)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/purchase/{run_ref}/stream")
async def purchase_stream(run_ref: str):
    """SSE: replays the enriched trace paced, so the split view reads as live
    and both panes stay locked to the same events."""
    import asyncio
    import json as _json

    from sse_starlette.sse import EventSourceResponse
    run = state.purchases.get(run_ref)

    async def gen():
        if not run:
            yield {"event": "error", "data": _json.dumps({"error": "unknown purchase"})}
            return
        for evt in run["trace"]:
            yield {"event": "trace", "data": _json.dumps(evt, default=str)}
            await asyncio.sleep(0.22)
        yield {"event": "done", "data": _json.dumps(run["result"], default=str)}

    return EventSourceResponse(gen())


# ---------------------------------------------------------------- onboarding
# The "any merchant" claim, made pressable: paste a storefront URL, and if the
# page carries standard product markup (schema.org JSON-LD / microdata / Open
# Graph — what mainstream store platforms emit), its items become agent-
# sellable in this world. Structure only, never prose; every skip has a reason.

class OnboardBlocked(Exception):
    """The fetch was refused before any network read (or mid-redirect)."""


_MAX_STOREFRONT_BYTES = 2_000_000


def _storefront_url_error(url: str) -> str | None:
    """SSRF guard: this endpoint runs on a public demo box, so it must never
    be usable to read private address space. Fail closed on anything odd."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "Only http(s) storefront URLs are supported."
    host = parsed.hostname
    if not host:
        return "That URL has no host."
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return f"Could not resolve '{host}'."
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return "That address points inside a private network — public storefronts only."
    return None


def _fetch_storefront_guarded(url: str, *, timeout_s: int = 10) -> str:
    """Fetch with the guard re-applied on every redirect hop and a hard size
    cap — urlopen follows redirects, and a public URL redirecting into
    private address space is the classic SSRF second act."""
    from urllib.request import HTTPRedirectHandler, Request, build_opener

    class _GuardedRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N803
            err = _storefront_url_error(newurl)
            if err:
                raise OnboardBlocked(f"A redirect was blocked: {err}")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = build_opener(_GuardedRedirect())
    req = Request(url, headers={"User-Agent": "conduit-catalog-onboarding/1.0"})
    with opener.open(req, timeout=timeout_s) as resp:  # noqa: S310 — guarded above
        raw = resp.read(_MAX_STOREFRONT_BYTES + 1)
    if len(raw) > _MAX_STOREFRONT_BYTES:
        raise OnboardBlocked("That page is larger than 2 MB — point at a product or collection page.")
    return raw.decode("utf-8", errors="replace")


# module-level indirection so tests can swap the fetch without any network
_fetch_storefront = _fetch_storefront_guarded


class OnboardReq(BaseModel):
    url: str


@router.post("/onboard")
def onboard_storefront(req: OnboardReq):
    url = req.url.strip()
    err = _storefront_url_error(url)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    try:
        html = _fetch_storefront(url)
        result = parse_storefront_html(html)
    except OnboardBlocked as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except NoStructuredMarkup as exc:
        # the parser's message already names what was looked for and the way out
        return JSONResponse({"error": str(exc)}, status_code=422)
    except OSError as exc:
        return JSONResponse({"error": f"Could not fetch the page: {exc}"}, status_code=502)

    existing = {it["item_id"] for it in state.catalog.bulk_feed()["items"]}
    kept, skipped = [], list(result.skipped)
    for item in result.items:
        if item.currency != "INR":
            skipped.append(f"'{item.text.name}': priced in {item.currency} — this demo binds INR only")
            continue
        if item.item_id in existing:
            skipped.append(f"'{item.text.name}': id '{item.item_id}' already in the catalog — "
                           "skipped; imports never overwrite existing prices")
            continue
        kept.append(item)
    if kept:
        state.catalog.upsert_items(kept, now_ms=state._now_ms())
    return {
        "imported": len(kept),
        "source": result.source,
        "skipped": skipped,
        "catalog_version": state.catalog.catalog_version(),
        "items": [{"item_id": i.item_id, "name": i.text.name, "price_minor": i.price_minor}
                  for i in kept],
        "claim": {"catalog": "modelled", "orders": "razorpay-test-mode"},
    }


# ---------------------------------------------------------------- revenue
@router.get("/revenue")
def revenue():
    """The agent channel, in the merchant's terms. Honest accounting: revenue
    counts captured payments only; upsell attribution uses the commit-time
    price snapshot (pre-tax) — the exact figures the gate verified."""
    placed = captured = declined = 0
    gross_minor = upsell_minor = 0
    for record in getattr(state.cart_repo, "_carts", {}).values():
        if not record.committed_order_id:
            continue
        placed += 1
        payments = state.rail.fetch_order_payments(record.committed_order_id)
        last = payments["items"][-1] if payments["count"] else None
        status = (last or {}).get("status")
        if status == "captured":
            captured += 1
            gross_minor += record.committed_amount_minor or 0
            for item_id in (record.accepted_upsells or {}):
                priced = record.last_priced.get(item_id)
                qty = record.lines.get(item_id, 0)
                if priced and qty:
                    upsell_minor += priced[0] * qty
        elif status == "failed":
            declined += 1
    return {
        "orders_placed": placed,
        "orders_captured": captured,
        "payments_declined": declined,
        "gross_captured_minor": gross_minor,
        "upsell_attributed_minor": upsell_minor,
        "aov_minor": gross_minor // captured if captured else 0,
        "note": "captured payments only; upsell attribution is pre-tax at commit-time prices",
        "claim": {"orders": "razorpay-test-mode", "settlement": "modelled"},
    }


@router.get("/orders")
def orders():
    out = []
    for record in getattr(state.cart_repo, "_carts", {}).values():
        if not record.committed_order_id:
            continue
        payments = state.rail.fetch_order_payments(record.committed_order_id)
        out.append({
            "order_id": record.committed_order_id,
            "cart_id": record.cart_id,
            "mandate_id": record.mandate_id,
            "amount_minor": record.committed_amount_minor,
            "currency": record.currency,
            "upsells": record.accepted_upsells,
            "payments": payments["items"],
            "claim": {"order": "razorpay-test-mode", "settlement": "modelled"},
        })
    return sorted(out, key=lambda o: o["cart_id"], reverse=True)
