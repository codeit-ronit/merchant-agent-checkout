"""MandateService — the lifecycle over the drawdown ledger (05-MANDATE §3.3).

CREATE is the one human step in the whole flow. REVOKE is instant and total:
active reservations are released in the same call, and everything downstream
(policy gate, ledger defence, gate reserve) refuses from that moment. EXPIRE
is absolute and non-extendable — there is deliberately no method to extend.

``to_env`` builds the MandateEnv snapshot the runtime injects into
DecisionContext — the balance is ledger-derived at snapshot time, never a
stored number, so suspend/resume cannot lose it.
"""

from __future__ import annotations

from dataclasses import replace

from conduit.mandate.ledger import DrawdownLedger, EntryKind, LedgerError, Mandate
from sentinel.contracts.decision import MandateEnv


class MandateService:
    def __init__(self, ledger: DrawdownLedger):
        self._ledger = ledger
        self._counter = 0

    # ------------------------------------------------------------- lifecycle
    def create(self, *, locked_minor: int, currency: str, scope_merchant_id: str,
               expires_at_ms: int, instrument_contact: str | None = None,
               customer_id: str | None = None, now_ms: int) -> Mandate:
        """The one human step: amount, merchant, expiry — consent, upfront."""
        if now_ms >= expires_at_ms:
            raise LedgerError("a mandate must expire in the future")
        if not scope_merchant_id:
            raise LedgerError("a mandate must be scoped to a merchant")
        self._counter += 1
        mandate = Mandate(
            mandate_id=f"mnd_{self._counter:06d}",
            locked_minor=locked_minor, currency=currency,
            scope_merchant_id=scope_merchant_id, expires_at_ms=expires_at_ms,
            status="ACTIVE", instrument_contact=instrument_contact,
            customer_id=customer_id)
        self._ledger.create_mandate(mandate)
        return mandate

    def revoke(self, mandate_id: str, *, now_ms: int) -> Mandate:
        """Instant and total: status flips, and every active reservation is
        released NOW — an agent mid-purchase is stopped at the gate, never
        allowed to finish 'because it already started'."""
        mandate = self._ledger.get_mandate(mandate_id)
        revoked = replace(mandate, status="REVOKED")
        self._ledger.create_mandate(revoked)  # upsert
        # release every open hold on this mandate
        open_refs: dict[str, bool] = {}
        for entry in self._ledger.entries(mandate_id):
            if entry.kind is EntryKind.RESERVE:
                open_refs[entry.ref] = True
            elif entry.kind in (EntryKind.CONFIRM, EntryKind.RELEASE):
                open_refs.pop(entry.ref, None)
        for ref in open_refs:
            self._ledger.release(mandate_id, ref=ref, now_ms=now_ms)
        return revoked

    def get(self, mandate_id: str) -> Mandate:
        return self._ledger.get_mandate(mandate_id)

    # ------------------------------------------------------------- snapshot
    def to_env(self, mandate_id: str) -> MandateEnv:
        """The policy input: state + LEDGER-DERIVED remaining balance."""
        mandate = self._ledger.get_mandate(mandate_id)
        balance = self._ledger.balance(mandate_id)
        return MandateEnv(
            mandate_id=mandate.mandate_id,
            remaining_minor=balance.remaining_minor,
            currency=mandate.currency,
            scope_merchant_id=mandate.scope_merchant_id,
            expires_at_ms=mandate.expires_at_ms,
            status=mandate.status,
        )

    def public_view(self, mandate_id: str, *, now_ms: int) -> dict:
        """What the UI and the receipt show. Derived, explainable."""
        mandate = self._ledger.get_mandate(mandate_id)
        balance = self._ledger.balance(mandate_id)
        effective = ("REVOKED" if mandate.status == "REVOKED"
                     else "EXPIRED" if now_ms >= mandate.expires_at_ms
                     else "EXHAUSTED" if balance.remaining_minor <= 0
                     else "ACTIVE")
        return {
            "mandate_id": mandate.mandate_id,
            "locked_minor": mandate.locked_minor,
            "currency": mandate.currency,
            "scope_merchant_id": mandate.scope_merchant_id,
            "expires_at_ms": mandate.expires_at_ms,
            "status": effective,
            "reserved_minor": balance.reserved_minor,
            "drawn_minor": balance.drawn_minor,
            "remaining_minor": balance.remaining_minor,
        }
