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

from typing import Any

from conduit.catalog.service import CatalogError, CatalogService, SearchQuery
from conduit.mcp.tools import CATALOG_TOOL_NAMES, CATALOG_TOOLS, price_shaped_args
from sentinel.fixtures.upstream import Upstream, UpstreamError

DEFAULT_COUNT = 10
MAX_COUNT = 100


class ConduitUpstream:
    """Wraps any inner upstream (fixture or live) and serves catalog tools."""

    def __init__(self, inner: Upstream, catalog: CatalogService):
        self._inner = inner
        self._catalog = catalog

    # ---- Upstream interface ----
    def list_tools(self) -> list[dict[str, Any]]:
        return list(self._inner.list_tools()) + [dict(t) for t in CATALOG_TOOLS]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
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
        tool = next(t for t in CATALOG_TOOLS if t["name"] == name)
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
