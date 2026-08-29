"""Cart types. The structural rule: a cart line holds an item id and a
quantity — THERE IS NO PRICE FIELD TO SET. Prices exist only in the priced
view, which the server computes from catalog truth and stamps with the
catalog version that priced it (the provenance the commit-time diff needs).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CartStatus(str, Enum):
    OPEN = "OPEN"
    COMMITTED = "COMMITTED"
    EXPIRED = "EXPIRED"


class CartError(Exception):
    """Cart-side rejection with an actionable message."""


@dataclass(frozen=True)
class CartLine:
    """What the agent controls: which item, how many. Nothing else."""

    item_id: str
    quantity: int

    def __post_init__(self) -> None:
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int) or self.quantity < 1:
            raise CartError("quantity must be a positive integer")


@dataclass(frozen=True)
class PricedLine:
    """Server-computed view of one line, with provenance."""

    item_id: str
    name: str                # merchant-authored → untrusted on output surfaces
    quantity: int
    unit_price_minor: int
    line_total_minor: int    # unit × qty
    tax_minor: int           # floor(line_total × rate_bps / 10000)
    price_version: int
    upsell_rule_id: str | None = None   # set iff the line entered via explicit acceptance


@dataclass(frozen=True)
class PricedCart:
    """The full server-computed view: what cart_view returns, and the snapshot
    the commit-time diff compares against live truth."""

    cart_id: str
    mandate_id: str
    currency: str
    lines: tuple[PricedLine, ...]
    subtotal_minor: int
    tax_total_minor: int
    total_minor: int
    catalog_version: int     # which truth priced this view
    mandate_remaining_minor: int
    expires_at_ms: int
    status: CartStatus
    # Offers the server surfaced WITH this view. Suppression is pre-model by
    # construction: an offer that would exceed the mandate is never in here,
    # so the model never sees it (06 §B3).
    upsell_offers: tuple[dict, ...] = ()

    def to_public(self) -> dict:
        return {
            "cart_id": self.cart_id,
            "mandate_id": self.mandate_id,
            "currency": self.currency,
            "lines": [
                {
                    "item_id": ln.item_id,
                    "name": ln.name,
                    "quantity": ln.quantity,
                    "unit_price_minor": ln.unit_price_minor,
                    "line_total_minor": ln.line_total_minor,
                    "tax_minor": ln.tax_minor,
                    "price_version": ln.price_version,
                    "upsell_rule_id": ln.upsell_rule_id,
                }
                for ln in self.lines
            ],
            "upsell_offers": [dict(o) for o in self.upsell_offers],
            "subtotal_minor": self.subtotal_minor,
            "tax_total_minor": self.tax_total_minor,
            "total_minor": self.total_minor,
            "catalog_version": self.catalog_version,
            "mandate_remaining_minor": self.mandate_remaining_minor,
            "expires_at_ms": self.expires_at_ms,
            "status": self.status.value,
        }


@dataclass
class CartRecord:
    """Stored cart state. Mutable by the service only; lines carry no money."""

    cart_id: str
    mandate_id: str
    currency: str
    created_at_ms: int
    expires_at_ms: int
    status: CartStatus = CartStatus.OPEN
    lines: dict[str, int] = field(default_factory=dict)   # item_id -> quantity
    committed_order_id: str | None = None
    committed_amount_minor: int | None = None
    # The last server-priced view the agent was shown: item_id -> [unit_minor,
    # price_version]. This is what makes the commit-time diff able to say what
    # the agent BELIEVED, per line — not merely that the totals differ.
    last_priced: dict[str, list[int]] = field(default_factory=dict)
    last_priced_catalog_version: int = 0
    # Upsell state (06 §B). Offers the server has SURFACED for this cart,
    # keyed by offer_id, each bound to the cart/catalog state that cleared it
    # — acceptance re-validates against the LIVE state (the re-price lesson,
    # reused). Surfacing is cumulative: the per-cart cap counts every offer
    # ever shown, not just currently visible ones.
    offers: dict[str, dict] = field(default_factory=dict)
    offers_surfaced: int = 0
    # item_id -> {rule_id, offer_id, accepted_at_ms}: the lines that entered
    # via explicit acceptance — what the receipt marks as upsells.
    accepted_upsells: dict[str, dict] = field(default_factory=dict)
