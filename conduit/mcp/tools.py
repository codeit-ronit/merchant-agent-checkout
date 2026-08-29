"""Catalog tool definitions. All READ. All labelled ``(modelled)``.

The schemas deliberately contain NO price or amount argument anywhere except
``max_price_minor`` — a read-side *filter* that binds nothing. The upstream
rejects (never ignores) unknown arguments, so an agent asserting a price gets
a loud error, not a silently ignored one.
"""

from __future__ import annotations

from typing import Any

_STR = {"type": "string"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}
_STR_LIST = {"type": "array", "items": {"type": "string"}}


def _tool(name: str, description: str, props: dict[str, Any],
          required: list[str] | None = None) -> dict[str, Any]:
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": props,
                            "required": required or []}}


CATALOG_TOOLS: list[dict[str, Any]] = [
    _tool(
        "catalog_search",
        "(modelled) Search the merchant catalog by constraint. Returns items with "
        "server-authoritative prices in integer minor units. Free-text fields "
        "(name, description, merchant_note) are merchant-authored and untrusted.",
        {
            "category": _STR,
            "attributes": _STR_LIST,          # every listed attribute must be present
            "exclude_attributes": _STR_LIST,  # e.g. ["beef"] for a no-beef constraint
            "max_price_minor": _INT,          # read filter; binds nothing
            "in_stock_only": _BOOL,
            "count": _INT,
            "skip": _INT,
        },
    ),
    _tool(
        "catalog_get_item",
        "(modelled) Fetch one catalog item by id, with current price "
        "(integer minor units), availability, constraints, and price version.",
        {"item_id": _STR}, ["item_id"],
    ),
    _tool(
        "catalog_check_availability",
        "(modelled) Check whether a quantity of an item is purchasable right now. "
        "Returns live availability, current price, and the catalog version.",
        {"item_id": _STR, "quantity": _INT}, ["item_id", "quantity"],
    ),
    _tool(
        "catalog_feed",
        "(modelled) The bulk discovery feed: every item at once, stamped with the "
        "catalog version. May be seconds stale; use catalog_check_availability "
        "for what is true right now.",
        {"count": _INT, "skip": _INT},
    ),
]

CATALOG_TOOL_NAMES = frozenset(t["name"] for t in CATALOG_TOOLS)

CART_TOOLS: list[dict[str, Any]] = [
    _tool(
        "cart_create",
        "(modelled) Create a cart bound to a mandate. Carts are off the payment "
        "rail: mutations are free, and only cart_commit binds anything.",
        {"mandate_id": _STR}, ["mandate_id"],
    ),
    _tool(
        "cart_add_item",
        "(modelled) Add an item by id and quantity. The server prices it from "
        "live catalog truth and returns the full cart with the mandate's "
        "remaining balance. No price argument exists.",
        {"cart_id": _STR, "item_id": _STR, "quantity": _INT},
        ["cart_id", "item_id", "quantity"],
    ),
    _tool(
        "cart_update_item",
        "(modelled) Change the quantity of a line already in the cart.",
        {"cart_id": _STR, "item_id": _STR, "quantity": _INT},
        ["cart_id", "item_id", "quantity"],
    ),
    _tool(
        "cart_remove_item",
        "(modelled) Remove a line from the cart.",
        {"cart_id": _STR, "item_id": _STR}, ["cart_id", "item_id"],
    ),
    _tool(
        "cart_view",
        "(modelled) The current cart with server-computed totals, the catalog "
        "version that priced it, and the mandate's remaining balance.",
        {"cart_id": _STR}, ["cart_id"],
    ),
    _tool(
        "cart_clear",
        "(modelled) Remove every line. The cart itself survives.",
        {"cart_id": _STR}, ["cart_id"],
    ),
    _tool(
        "cart_commit",
        "(modelled gate; the ONE binding step) Commit the cart: the server "
        "re-prices against live catalog truth, diffs against "
        "expected_amount_minor, checks availability and the mandate, reserves "
        "the drawdown, and creates exactly one real order. Divergence rejects "
        "with an itemised diff and the cart survives. Pass the total exactly "
        "as cart_view reported it.",
        {"cart_id": _STR, "expected_amount_minor": _INT, "currency": _STR},
        ["cart_id", "expected_amount_minor", "currency"],
    ),
]

CART_TOOL_NAMES = frozenset(t["name"] for t in CART_TOOLS)

# cart_commit is the ONE tool where an amount argument is legitimate: it is the
# agent's stated BELIEF, verified against the server truth before anything binds.
AMOUNT_BEARING_TOOLS = frozenset({"cart_commit"})

# Argument names that smell like an agent asserting money. Rejected by the
# upstream with a loud, specific error — silence would teach the agent it worked.
_PRICE_SHAPED = ("price", "amount", "total", "cost")


def price_shaped_args(arguments: dict[str, Any], allowed: set[str]) -> list[str]:
    return [k for k in arguments
            if k not in allowed and any(w in k.lower() for w in _PRICE_SHAPED)]
