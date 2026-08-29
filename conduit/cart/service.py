"""CartService — mutable, off-rail, server-priced, expiring.

Every mutation re-prices the whole cart from live catalog truth and returns
the priced view PLUS the mandate's remaining balance — the feedback loop that
lets the agent reason about affordability against real numbers instead of its
own arithmetic (06 §A3).

No operation accepts an amount. Quantity constraints are enforced at
mutation; availability and requires-another-item are commit-gate checks
(stock changes between add and commit anyway).

Deterministic: every method takes ``now_ms``. Expiry is checked on touch, and
an expired cart releases any reservation it holds (04 §3.1).
"""

from __future__ import annotations

from conduit.cart.model import CartError, CartLine, CartRecord, CartStatus, PricedCart, PricedLine
from conduit.cart.store import CartRepository
from conduit.catalog.service import CatalogError, CatalogService
from conduit.mandate.ledger import DrawdownLedger, LedgerError

DEFAULT_TTL_MS = 30 * 60 * 1000  # 30 minutes


def _tax_minor(line_total_minor: int, rate_bps: int) -> int:
    """Integer floor, per line. Declared treatment, deterministic arithmetic."""
    return (line_total_minor * rate_bps) // 10_000


class CartService:
    def __init__(self, repo: CartRepository, catalog: CatalogService,
                 ledger: DrawdownLedger, *, ttl_ms: int = DEFAULT_TTL_MS):
        self._repo = repo
        self._catalog = catalog
        self._ledger = ledger
        self._ttl_ms = ttl_ms
        self._counter = 0

    # ------------------------------------------------------------- lifecycle
    def create(self, mandate_id: str, *, now_ms: int) -> PricedCart:
        mandate = self._ledger.get_mandate(mandate_id)  # fails closed on unknown mandate
        self._counter += 1
        record = CartRecord(
            cart_id=f"cart_{self._counter:06d}",
            mandate_id=mandate_id,
            currency=mandate.currency,
            created_at_ms=now_ms,
            expires_at_ms=now_ms + self._ttl_ms,
        )
        self._repo.put(record)
        return self.price(record, now_ms=now_ms)

    def expire_if_due(self, record: CartRecord, *, now_ms: int) -> CartRecord:
        """Expiry on touch: mark EXPIRED and release any reservation the cart
        still holds — an abandoned hold is a leak AND a correctness bug."""
        if record.status is CartStatus.OPEN and now_ms >= record.expires_at_ms:
            record.status = CartStatus.EXPIRED
            self._repo.put(record)
            try:
                self._ledger.release(record.mandate_id, ref=record.cart_id, now_ms=now_ms)
            except LedgerError:
                pass  # no active hold — nothing to return
        return record

    # ------------------------------------------------------------- mutations
    def add_item(self, cart_id: str, item_id: str, quantity: int, *, now_ms: int) -> PricedCart:
        record = self._open_cart(cart_id, now_ms)
        line = CartLine(item_id=item_id, quantity=quantity)  # validates quantity
        item = self._item_or_reject(item_id)
        new_qty = record.lines.get(item_id, 0) + line.quantity
        self._check_quantity_constraints(item, new_qty)
        record.lines[item_id] = new_qty
        self._repo.put(record)
        return self.price(record, now_ms=now_ms)

    def update_item(self, cart_id: str, item_id: str, quantity: int, *, now_ms: int) -> PricedCart:
        record = self._open_cart(cart_id, now_ms)
        if item_id not in record.lines:
            raise CartError(f"'{item_id}' is not in the cart. Add it first, or check cart_view.")
        line = CartLine(item_id=item_id, quantity=quantity)
        item = self._item_or_reject(item_id)
        self._check_quantity_constraints(item, line.quantity)
        record.lines[item_id] = line.quantity
        self._repo.put(record)
        return self.price(record, now_ms=now_ms)

    def remove_item(self, cart_id: str, item_id: str, *, now_ms: int) -> PricedCart:
        record = self._open_cart(cart_id, now_ms)
        if item_id not in record.lines:
            raise CartError(f"'{item_id}' is not in the cart; nothing to remove.")
        del record.lines[item_id]
        self._repo.put(record)
        return self.price(record, now_ms=now_ms)

    def clear(self, cart_id: str, *, now_ms: int) -> PricedCart:
        record = self._open_cart(cart_id, now_ms)
        record.lines.clear()
        self._repo.put(record)
        return self.price(record, now_ms=now_ms)

    def view(self, cart_id: str, *, now_ms: int) -> PricedCart:
        record = self._require(cart_id)
        record = self.expire_if_due(record, now_ms=now_ms)
        return self.price(record, now_ms=now_ms)

    # ------------------------------------------------------------- upsell
    def accept_upsell(self, cart_id: str, offer_id: str, *, now_ms: int) -> PricedCart:
        """The ONLY path an upsell enters the cart (06 §B2: the agent may
        offer — the system may never silently add). Acceptance RE-VALIDATES
        everything against the LIVE world, because the offer was cleared
        against an earlier cart state and the world moves — the re-price
        lesson, reused rather than rediscovered."""
        record = self._open_cart(cart_id, now_ms)
        offer = record.offers.get(offer_id)
        if offer is None:
            raise CartError(
                f"no offer '{offer_id}' on this cart. Offers are server-issued — "
                f"read them from cart_view. An invented offer is a policy "
                f"violation, not a creative flourish.")
        item_id = offer["item_id"]
        if item_id in record.lines:
            raise CartError(f"'{item_id}' is already in the cart; the offer no longer applies.")
        item = self._item_or_reject(item_id)
        if not item.availability.purchasable(offer["quantity"]):
            raise CartError(
                f"offer '{offer_id}' withdrawn: '{item_id}' is no longer available. "
                f"The cart is unchanged.")
        if item.price_minor != offer["unit_price_minor"]:
            # the world moved: never bind the stale offer price. Refresh the
            # stored offer so the next view shows the new truth (the cap is
            # not double-counted — same offer, new price).
            offer["unit_price_minor"] = item.price_minor
            offer["tax_minor"] = _tax_minor(item.price_minor * offer["quantity"],
                                            item.tax.rate_bps)
            offer["offer_total_minor"] = (item.price_minor * offer["quantity"]
                                          + offer["tax_minor"])
            self._repo.put(record)
            raise CartError(
                f"offer '{offer_id}' re-priced since it was shown "
                f"(now {item.price_minor} minor units/unit). Re-read cart_view — "
                f"the refreshed offer appears there if it is still affordable.")
        current = self.price(record, now_ms=now_ms)
        if current.total_minor + offer["offer_total_minor"] > current.mandate_remaining_minor:
            raise CartError(
                f"offer '{offer_id}' no longer fits the mandate: the cart changed "
                f"since the offer was cleared. Remove something or decline the "
                f"offer; the cart is unchanged.")
        record.lines[item_id] = offer["quantity"]
        record.accepted_upsells[item_id] = {
            "rule_id": offer["rule_id"], "offer_id": offer_id,
            "accepted_at_ms": now_ms}
        self._repo.put(record)
        return self.price(record, now_ms=now_ms)

    # ------------------------------------------------------------- pricing
    def price(self, record: CartRecord, *, now_ms: int) -> PricedCart:
        """The server computes every figure from live catalog truth. The
        returned view IS the agent's knowledge of money — and the snapshot
        the commit gate diffs against a fresh re-price."""
        lines: list[PricedLine] = []
        subtotal = tax_total = 0
        for item_id, qty in record.lines.items():
            item = self._item_or_reject(item_id)
            line_total = item.price_minor * qty
            tax = _tax_minor(line_total, item.tax.rate_bps)
            subtotal += line_total
            tax_total += tax
            lines.append(PricedLine(
                item_id=item_id, name=item.text.name, quantity=qty,
                unit_price_minor=item.price_minor, line_total_minor=line_total,
                tax_minor=tax, price_version=item.price_version,
                upsell_rule_id=(record.accepted_upsells.get(item_id) or {}).get("rule_id")))
        remaining = self._ledger.balance(record.mandate_id).remaining_minor
        total = subtotal + tax_total
        offers = self._surface_offers(record, total, remaining)
        # Record the snapshot the agent is being shown — the diff's baseline.
        if record.status is CartStatus.OPEN:
            record.last_priced = {
                ln.item_id: [ln.unit_price_minor, ln.price_version] for ln in lines}
            record.last_priced_catalog_version = self._catalog.catalog_version()
            self._repo.put(record)
        return PricedCart(
            cart_id=record.cart_id, mandate_id=record.mandate_id,
            currency=record.currency, lines=tuple(lines),
            subtotal_minor=subtotal, tax_total_minor=tax_total,
            total_minor=total,
            catalog_version=self._catalog.catalog_version(),
            mandate_remaining_minor=remaining,
            expires_at_ms=record.expires_at_ms, status=record.status,
            upsell_offers=tuple(offers))

    def _surface_offers(self, record: CartRecord, total_minor: int,
                        remaining_minor: int) -> list[dict]:
        """Which offers this view carries. SUPPRESSION IS PRE-MODEL BY
        CONSTRUCTION (06 §B3): an offer whose acceptance would exceed the
        mandate is simply not in the response — the model never sees an
        offer it cannot afford, so there is nothing to reject after
        acceptance. Surfacing is capped cumulatively per cart, and every
        offer is stored with the cart state that cleared it; acceptance
        re-validates against the live state regardless."""
        if record.status is not CartStatus.OPEN:
            return []
        merchant = self._catalog.merchant()
        cap = merchant.max_upsell_offers_per_cart if merchant else 0
        surfaced_rules = {o["rule_id"] for o in record.offers.values()}
        changed = False
        for rule in self._catalog.upsell_rules():         # sorted: deterministic
            if (rule.trigger_item_id not in record.lines
                    or rule.offer_item_id in record.lines
                    or rule.rule_id in surfaced_rules
                    or record.offers_surfaced >= cap):
                continue
            item = self._item_or_reject(rule.offer_item_id)
            quantity = item.constraints.min_quantity
            if not item.availability.purchasable(quantity):
                continue
            line_total = item.price_minor * quantity
            offer_total = line_total + _tax_minor(line_total, item.tax.rate_bps)
            if total_minor + offer_total > remaining_minor:
                continue                                   # suppressed pre-model
            offer_id = f"off_{record.cart_id}_{record.offers_surfaced + 1}"
            record.offers[offer_id] = {
                "offer_id": offer_id, "rule_id": rule.rule_id,
                "item_id": rule.offer_item_id, "quantity": quantity,
                "unit_price_minor": item.price_minor,
                "tax_minor": offer_total - line_total,
                "offer_total_minor": offer_total,
                "cleared_at": {
                    "cart_total_minor": total_minor,
                    "mandate_remaining_minor": remaining_minor,
                    "catalog_version": self._catalog.catalog_version(),
                    "price_version": item.price_version,
                },
            }
            record.offers_surfaced += 1
            surfaced_rules.add(rule.rule_id)
            changed = True
        if changed:
            self._repo.put(record)
        # visibility: surfaced, not yet in the cart, and STILL affordable at
        # the stored (re-validated-on-acceptance) price
        visible = []
        for offer in record.offers.values():
            if offer["item_id"] in record.lines:
                continue
            if total_minor + offer["offer_total_minor"] > remaining_minor:
                continue
            out = dict(offer)
            out["name"] = self._item_or_reject(offer["item_id"]).text.name
            visible.append(out)
        return visible

    # ------------------------------------------------------------- helpers
    def record(self, cart_id: str) -> CartRecord:
        return self._require(cart_id)

    def save(self, record: CartRecord) -> None:
        self._repo.put(record)

    def find_by_committed_order(self, order_id: str) -> CartRecord | None:
        return self._repo.find_by_committed_order(order_id)

    def live_item(self, item_id: str):
        """Live catalog truth for one item (rejects phantoms). Used by the gate."""
        return self._item_or_reject(item_id)

    def _require(self, cart_id: str) -> CartRecord:
        record = self._repo.get(cart_id)
        if record is None:
            raise CartError(f"no cart '{cart_id}'. Create one with cart_create.")
        return record

    def _open_cart(self, cart_id: str, now_ms: int) -> CartRecord:
        record = self.expire_if_due(self._require(cart_id), now_ms=now_ms)
        if record.status is CartStatus.EXPIRED:
            raise CartError(
                f"cart '{cart_id}' expired. Create a new cart; any reservation was released.")
        if record.status is CartStatus.COMMITTED:
            raise CartError(
                f"cart '{cart_id}' is already committed (order "
                f"{record.committed_order_id}). Create a new cart for a new purchase.")
        return record

    def _item_or_reject(self, item_id: str):
        try:
            return self._catalog.get_item(item_id)
        except CatalogError as exc:
            raise CartError(str(exc)) from exc

    @staticmethod
    def _check_quantity_constraints(item, quantity: int) -> None:
        c = item.constraints
        if quantity < c.min_quantity:
            raise CartError(
                f"'{item.item_id}' has a minimum quantity of {c.min_quantity}.")
        if c.max_per_order is not None and quantity > c.max_per_order:
            raise CartError(
                f"'{item.item_id}' allows at most {c.max_per_order} per order; "
                f"requested {quantity}.")
