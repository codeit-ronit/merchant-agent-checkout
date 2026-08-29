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
                tax_minor=tax, price_version=item.price_version))
        # Record the snapshot the agent is being shown — the diff's baseline.
        if record.status is CartStatus.OPEN:
            record.last_priced = {
                ln.item_id: [ln.unit_price_minor, ln.price_version] for ln in lines}
            record.last_priced_catalog_version = self._catalog.catalog_version()
            self._repo.put(record)
        remaining = self._ledger.balance(record.mandate_id).remaining_minor
        return PricedCart(
            cart_id=record.cart_id, mandate_id=record.mandate_id,
            currency=record.currency, lines=tuple(lines),
            subtotal_minor=subtotal, tax_total_minor=tax_total,
            total_minor=subtotal + tax_total,
            catalog_version=self._catalog.catalog_version(),
            mandate_remaining_minor=remaining,
            expires_at_ms=record.expires_at_ms, status=record.status)

    # ------------------------------------------------------------- helpers
    def record(self, cart_id: str) -> CartRecord:
        return self._require(cart_id)

    def save(self, record: CartRecord) -> None:
        self._repo.put(record)

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
