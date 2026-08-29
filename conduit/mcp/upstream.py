"""``ConduitUpstream`` — a composite upstream: the real (or fixture) Razorpay
surface plus CONDUIT's modelled catalog tools, behind ONE ``Upstream`` face.

Layering rule (CLAUDE.md: do not refactor SENTINEL): SENTINEL is untouched.
This wrapper satisfies the same ``list_tools`` / ``call_tool`` protocol the
proxy already speaks, so the interceptor, classifier, redaction, quarantine,
and audit all apply to catalog calls exactly as they do to Razorpay calls —
same boundary, same trace, same ledger.

Argument discipline: STRICT. An unknown argument is rejected, and a
price-shaped argument is rejected with a message that names the rule —
"the catalog is the only price source." Silent ignoring is forbidden because
the agent would then believe the assertion worked.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from conduit.cart.gate import CommitGate
from conduit.cart.model import CartError
from conduit.cart.service import CartService
from conduit.rail import ModelledSettlementRail
from conduit.catalog.service import CatalogError, CatalogService, SearchQuery
from conduit.mcp.tools import (
    CART_TOOL_NAMES,
    CART_TOOLS,
    CATALOG_TOOL_NAMES,
    CATALOG_TOOLS,
    price_shaped_args,
)
from sentinel.fixtures.upstream import Upstream, UpstreamError

DEFAULT_COUNT = 10
MAX_COUNT = 100

_ALL_TOOLS = CATALOG_TOOLS + CART_TOOLS


class ConduitUpstream:
    """Wraps any inner upstream (fixture or live) and serves the modelled
    catalog + cart surface. ``cart`` and ``gate`` are optional so a
    catalog-only deployment stays possible."""

    def __init__(self, inner: Upstream, catalog: CatalogService,
                 cart: CartService | None = None, gate: CommitGate | None = None,
                 rail: "ModelledSettlementRail | None" = None,
                 now_ms_fn: Callable[[], int] | None = None):
        self._inner = inner
        self._catalog = catalog
        self._cart = cart
        self._gate = gate
        self._rail = rail
        self._now_ms = now_ms_fn or (lambda: int(time.time() * 1000))

    # ---- Upstream interface ----
    def list_tools(self) -> list[dict[str, Any]]:
        tools = list(self._inner.list_tools()) + [dict(t) for t in CATALOG_TOOLS]
        if self._cart is not None:
            tools += [dict(t) for t in CART_TOOLS]
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name in CART_TOOL_NAMES:
            if self._cart is None or self._gate is None:
                raise UpstreamError(f"'{name}' is not served: this deployment has no cart layer")
            self._validate_args(name, arguments)
            try:
                return getattr(self, f"_t_{name}")(arguments)
            except CartError as exc:
                raise UpstreamError(str(exc)) from exc
        # MODELLED settlement rail (ADR-034): the real S2S payment API is not
        # enabled on this account, so these tools are served by a labelled
        # faithful model over real order state. Every minted entity carries
        # "modelled": true. fetch_order_payments answers from the rail only
        # for orders whose payments the rail owns; everything else stays real.
        if self._rail is not None:
            if name in self._rail.RAIL_TOOLS:
                if name == "initiate_payment":
                    return self._rail.initiate_payment(arguments, now_ms=self._now_ms())
                return self._rail.submit_otp(arguments, now_ms=self._now_ms())
            if name == "fetch_order_payments" and self._rail.knows_order(
                    arguments.get("order_id", "")):
                return self._rail.fetch_order_payments(arguments["order_id"])
        if name not in CATALOG_TOOL_NAMES:
            return self._inner.call_tool(name, arguments)
        handler = getattr(self, f"_t_{name}")
        self._validate_args(name, arguments)
        try:
            return handler(arguments)
        except CatalogError as exc:
            raise UpstreamError(str(exc)) from exc

    # ---- strict argument validation: reject, never ignore ----
    def _validate_args(self, name: str, arguments: dict[str, Any]) -> None:
        tool = next(t for t in _ALL_TOOLS if t["name"] == name)
        allowed = set(tool["inputSchema"]["properties"])
        priced = price_shaped_args(arguments, allowed)
        if priced:
            raise UpstreamError(
                f"{name} rejected argument(s) {priced}: the catalog is the only "
                f"price source. Prices are never accepted from the agent — read "
                f"them from the catalog instead.")
        unknown = sorted(set(arguments) - allowed)
        if unknown:
            raise UpstreamError(
                f"{name} rejected unknown argument(s) {unknown}. "
                f"Accepted arguments: {sorted(allowed)}.")
        for req in tool["inputSchema"]["required"]:
            if req not in arguments:
                raise UpstreamError(f"{name} requires '{req}'")

    # ---- pagination (Razorpay collection shape: no has_more; paginate by skip) ----
    @staticmethod
    def _page(rows: list[dict[str, Any]], arguments: dict[str, Any]) -> dict[str, Any]:
        count = min(int(arguments.get("count", DEFAULT_COUNT) or DEFAULT_COUNT), MAX_COUNT)
        skip = int(arguments.get("skip", 0) or 0)
        page = rows[skip: skip + count]
        return {"entity": "collection", "count": len(page), "items": page}

    # ---- handlers ----
    def _t_catalog_search(self, a: dict[str, Any]) -> dict[str, Any]:
        query = SearchQuery(
            category=(a.get("category") or None),
            attributes=frozenset(x.lower() for x in a.get("attributes", [])),
            exclude_attributes=frozenset(x.lower() for x in a.get("exclude_attributes", [])),
            max_price_minor=a.get("max_price_minor"),
            in_stock_only=bool(a.get("in_stock_only", False)),
        )
        rows = [i.to_public() for i in self._catalog.search(query)]
        out = self._page(rows, a)
        out["catalog_version"] = self._catalog.catalog_version()
        return out

    def _t_catalog_get_item(self, a: dict[str, Any]) -> dict[str, Any]:
        item = self._catalog.get_item(a["item_id"]).to_public()
        item["catalog_version"] = self._catalog.catalog_version()
        return item

    def _t_catalog_check_availability(self, a: dict[str, Any]) -> dict[str, Any]:
        quantity = a["quantity"]
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise UpstreamError("quantity must be a positive integer")
        return self._catalog.check_availability(a["item_id"], quantity)

    def _t_catalog_feed(self, a: dict[str, Any]) -> dict[str, Any]:
        feed = self._catalog.bulk_feed()
        out = self._page(feed["items"], a)
        out["entity"] = "catalog_feed"
        out["catalog_version"] = feed["catalog_version"]
        return out

    # ---- cart handlers (modelled; off-rail until the gate) ----
    def _t_cart_create(self, a: dict[str, Any]) -> dict[str, Any]:
        return self._cart.create(a["mandate_id"], now_ms=self._now_ms()).to_public()

    def _t_cart_add_item(self, a: dict[str, Any]) -> dict[str, Any]:
        return self._cart.add_item(a["cart_id"], a["item_id"], a["quantity"],
                                   now_ms=self._now_ms()).to_public()

    def _t_cart_update_item(self, a: dict[str, Any]) -> dict[str, Any]:
        return self._cart.update_item(a["cart_id"], a["item_id"], a["quantity"],
                                      now_ms=self._now_ms()).to_public()

    def _t_cart_remove_item(self, a: dict[str, Any]) -> dict[str, Any]:
        return self._cart.remove_item(a["cart_id"], a["item_id"],
                                      now_ms=self._now_ms()).to_public()

    def _t_cart_view(self, a: dict[str, Any]) -> dict[str, Any]:
        return self._cart.view(a["cart_id"], now_ms=self._now_ms()).to_public()

    def _t_cart_clear(self, a: dict[str, Any]) -> dict[str, Any]:
        return self._cart.clear(a["cart_id"], now_ms=self._now_ms()).to_public()

    def _t_cart_commit(self, a: dict[str, Any]) -> dict[str, Any]:
        # The gate returns STRUCTURED outcomes for both success and rejection —
        # a rejection (re-price diff, shortfall, stock) is a well-formed answer
        # the agent must reason over, not an upstream error.
        return self._gate.commit(a["cart_id"], a["expected_amount_minor"],
                                 a["currency"], now_ms=self._now_ms())
