"""Canonical tool catalog — the single source of truth for the upstream MCP
tool surface.

PROVENANCE (important, and stated honestly): these tool names, descriptions, and
argument shapes were derived on 2026-08-21 from the razorpay/razorpay-mcp-server
README, the published Razorpay API docs, and Docker Hub — NOT from a live
``tools/list`` call, because Docker + rzp_test_* keys were unavailable in the
build environment. This is recorded in DECISIONS.md (ADR-003). In a real
deployment ``make reference-manifest`` re-captures this from the live server in
LIVE mode; the schema-parity check then catches any drift.

The 42 API tools + 2 local helpers mirror what the research found. Notably the
published server exposes **no create-payout tool** and **no dispute tools** — so
the money-movement surface reachable here is capture/initiate/refund/instant-
settlement, and the Dispute agent's irreversible write is served by a clearly
labelled FIXTURE EXTENSION (see ``FIXTURE_EXTENSIONS``), which the parity check
reports as fixture-only rather than silently pretending it is upstream.
"""

from __future__ import annotations

from typing import Any

_STR = {"type": "string"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


# Common argument fragments
_PAGINATION = {"count": _INT, "skip": _INT, "from": _INT, "to": _INT}


def _tool(name: str, description: str, props: dict[str, Any],
          required: list[str] | None = None) -> dict[str, Any]:
    return {"name": name, "description": description,
            "inputSchema": _schema(props, required)}


# --- Payments (8) ---
_PAYMENTS = [
    _tool("capture_payment", "Change payment status from authorized to captured (finalises the charge).",
          {"payment_id": _STR, "amount": _INT, "currency": _STR}, ["payment_id", "amount", "currency"]),
    _tool("fetch_payment", "Fetch payment details by ID.", {"payment_id": _STR}, ["payment_id"]),
    _tool("fetch_payment_card_details", "Fetch card details used for a payment.", {"payment_id": _STR}, ["payment_id"]),
    _tool("fetch_all_payments", "Fetch all payments with filtering and pagination.", dict(_PAGINATION)),
    _tool("update_payment", "Update the notes field of a payment.", {"payment_id": _STR, "notes": {"type": "object"}}, ["payment_id"]),
    _tool("initiate_payment", "Initiate a payment using a saved payment method (charges the customer).",
          {"amount": _INT, "currency": _STR, "customer_id": _STR, "token": _STR, "order_id": _STR}, ["amount", "currency", "customer_id"]),
    _tool("resend_otp", "Resend OTP if the previous one was not received or expired.", {"payment_id": _STR}, ["payment_id"]),
    _tool("submit_otp", "Verify and submit OTP to complete payment authentication (finalises the charge).",
          {"payment_id": _STR, "otp": _STR}, ["payment_id", "otp"]),
]

# --- Payment Links (6) ---
_PAYMENT_LINKS = [
    _tool("create_payment_link", "Create a standard payment link.", {"amount": _INT, "currency": _STR, "description": _STR}, ["amount", "currency"]),
    _tool("create_payment_link_upi", "Create a UPI payment link.", {"amount": _INT, "currency": _STR, "description": _STR}, ["amount", "currency"]),
    _tool("fetch_all_payment_links", "Fetch all payment links.", dict(_PAGINATION)),
    _tool("fetch_payment_link", "Fetch details of a payment link.", {"payment_link_id": _STR}, ["payment_link_id"]),
    _tool("send_payment_link", "Send a payment link via SMS or email.", {"payment_link_id": _STR, "medium": _STR}, ["payment_link_id", "medium"]),
    _tool("update_payment_link", "Update a standard payment link.", {"payment_link_id": _STR, "notes": {"type": "object"}}, ["payment_link_id"]),
]

# --- Orders (5) ---
_ORDERS = [
    _tool("create_order", "Create an order (a container/intent; no money moves).", {"amount": _INT, "currency": _STR, "receipt": _STR}, ["amount", "currency"]),
    _tool("fetch_order", "Fetch order by ID.", {"order_id": _STR}, ["order_id"]),
    _tool("fetch_all_orders", "Fetch all orders.", dict(_PAGINATION)),
    _tool("update_order", "Update an order's notes.", {"order_id": _STR, "notes": {"type": "object"}}, ["order_id"]),
    _tool("fetch_order_payments", "Fetch all payments for an order.", {"order_id": _STR}, ["order_id"]),
]

# --- Refunds (6) ---
_REFUNDS = [
    _tool("create_refund", "Create a refund (returns funds to the payer).",
          {"payment_id": _STR, "amount": _INT, "speed": _STR, "notes": {"type": "object"}}, ["payment_id", "amount"]),
    _tool("fetch_refund", "Fetch refund by ID.", {"refund_id": _STR}, ["refund_id"]),
    _tool("fetch_all_refunds", "Fetch all refunds.", dict(_PAGINATION)),
    _tool("update_refund", "Update refund notes.", {"refund_id": _STR, "notes": {"type": "object"}}, ["refund_id"]),
    _tool("fetch_multiple_refunds_for_payment", "Fetch multiple refunds for a payment.", {"payment_id": _STR, **_PAGINATION}, ["payment_id"]),
    _tool("fetch_specific_refund_for_payment", "Fetch a specific refund for a payment.", {"payment_id": _STR, "refund_id": _STR}, ["payment_id", "refund_id"]),
]

# --- QR Codes (7) ---
_QR = [
    _tool("create_qr_code", "Create a QR code (a collection instrument).", {"type": _STR, "usage": _STR, "fixed_amount": _BOOL, "payment_amount": _INT}, ["type"]),
    _tool("fetch_qr_code", "Fetch QR code by ID.", {"qr_id": _STR}, ["qr_id"]),
    _tool("fetch_all_qr_codes", "Fetch all QR codes.", dict(_PAGINATION)),
    _tool("fetch_qr_codes_by_customer_id", "Fetch QR codes by customer ID.", {"customer_id": _STR}, ["customer_id"]),
    _tool("fetch_qr_codes_by_payment_id", "Fetch QR codes by payment ID.", {"payment_id": _STR}, ["payment_id"]),
    _tool("fetch_payments_for_qr_code", "Fetch payments for a QR code.", {"qr_id": _STR, **_PAGINATION}, ["qr_id"]),
    _tool("close_qr_code", "Close a QR code (cannot be reopened).", {"qr_id": _STR}, ["qr_id"]),
]

# --- Settlements (6) ---
_SETTLEMENTS = [
    _tool("fetch_all_settlements", "Fetch all settlements.", dict(_PAGINATION)),
    _tool("fetch_settlement_with_id", "Fetch settlement details by ID.", {"settlement_id": _STR}, ["settlement_id"]),
    _tool("fetch_settlement_recon_details", "Fetch the settlement reconciliation report for a period.", {"year": _INT, "month": _INT, "day": _INT, **_PAGINATION}, ["year", "month"]),
    _tool("create_instant_settlement", "Create an instant settlement (moves merchant balance to bank ahead of schedule).", {"amount": _INT, "settle_full_balance": _BOOL, "description": _STR}, ["amount"]),
    _tool("fetch_all_instant_settlements", "Fetch all instant settlements.", dict(_PAGINATION)),
    _tool("fetch_instant_settlement_with_id", "Fetch instant settlement by ID.", {"settlement_id": _STR}, ["settlement_id"]),
]

# --- Payouts (2) — read-only; no create-payout tool exists upstream ---
_PAYOUTS = [
    _tool("fetch_all_payouts", "Fetch all payouts by account number.", {"account_number": _STR, **_PAGINATION}, ["account_number"]),
    _tool("fetch_payout_by_id", "Fetch payout by payout ID.", {"payout_id": _STR}, ["payout_id"]),
]

# --- Tokens (2) ---
_TOKENS = [
    _tool("fetch_tokens", "Get saved payment methods by customer ID or contact.", {"customer_id": _STR}, ["customer_id"]),
    _tool("revoke_token", "Revoke a saved payment method / token (cannot be undone).", {"customer_id": _STR, "token": _STR}, ["customer_id", "token"]),
]

# --- Registration / integration helpers (3) ---
_HELPERS = [
    _tool("create_registration_link", "Create a registration/authorisation link for recurring debits (mandate).", {"amount": _INT, "currency": _STR, "customer": {"type": "object"}}, ["amount", "currency"]),
    _tool("detect_stack", "(Local) Detect the project's language/framework for checkout integration.", {"path": _STR}),
    _tool("integrate_razorpay_checkout", "(Local) Generate Razorpay Standard Checkout integration code.", {"path": _STR, "language": _STR}),
]

UPSTREAM_TOOLS: list[dict[str, Any]] = (
    _PAYMENTS + _PAYMENT_LINKS + _ORDERS + _REFUNDS + _QR + _SETTLEMENTS + _PAYOUTS + _TOKENS + _HELPERS
)

# FIXTURE EXTENSIONS — NOT present in the current published upstream. They model
# a plausible near-future tool (Razorpay has disputes in its API/dashboard, just
# not in the MCP server yet) so the Dispute Responder agent has a real
# IRREVERSIBLE_WRITE to gate. The schema-parity check reports these as
# fixture-only rather than pretending they are upstream (ADR-003).
FIXTURE_EXTENSIONS: list[dict[str, Any]] = [
    _tool("fetch_dispute", "(fixture extension) Fetch a dispute and its underlying transaction.", {"dispute_id": _STR}, ["dispute_id"]),
    _tool("fetch_all_disputes", "(fixture extension) Fetch all disputes.", dict(_PAGINATION)),
    _tool("submit_dispute_evidence", "(fixture extension) Submit an evidence bundle to contest a dispute (irreversible once submitted).",
          {"dispute_id": _STR, "evidence": {"type": "object"}, "action": _STR}, ["dispute_id", "evidence", "action"]),
]

EXTENSION_NAMES = frozenset(t["name"] for t in FIXTURE_EXTENSIONS)


def upstream_manifest() -> dict[str, Any]:
    """The reference ``tools/list`` view of the real upstream (no extensions)."""
    return {
        "provenance": {
            "captured_on": "2026-08-21",
            "method": "derived from README + Razorpay API docs (Docker+test-keys "
                      "unavailable in build env); see DECISIONS.md ADR-003",
            "source_repo": "razorpay/razorpay-mcp-server",
            "tool_count": len(UPSTREAM_TOOLS),
        },
        "tools": UPSTREAM_TOOLS,
    }


def fixture_manifest() -> dict[str, Any]:
    """What the fixture server advertises: upstream mirror + labelled extensions."""
    return {"tools": UPSTREAM_TOOLS + FIXTURE_EXTENSIONS}
