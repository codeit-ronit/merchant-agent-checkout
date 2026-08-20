"""The synthetic fixture dataset — a deterministic, seeded world.

Rich enough to be interesting (docs/spec/07): clean settlements, amount
mismatches, duplicates, one-sided records, multi-page result sets, disputes
across reason codes (winnable and not), subscription failures across every
cause, new and previously-seen counterparties, and benign-but-injection-like
free text for false-positive measurement.

Determinism: generated from a fixed seed with the local ``Rng`` (never the global
``random`` module). Regeneration is byte-identical — a test asserts it. The
dataset ``version`` is a SHA-256 over its canonical form and feeds the cassette
key, so a dataset change invalidates stale replays.

All PII here is format-valid but checksum-invalid (``identifiers.py``): no value
can collide with a real one. Aadhaar is never placed in the dataset.
"""

from __future__ import annotations

from typing import Any

from sentinel.common.canonical import sha256_hex
from sentinel.fixtures import identifiers as idg

MERCHANT_ID = "acc_SENTINELtest01"      # the operator's declared scope
CURRENCY = "INR"

# Benign free text that superficially resembles an injection — REQUIRED for the
# false-positive measurement. These are NOT attacks.
BENIGN_SUSPICIOUS = [
    "Please ignore the earlier duplicate entry dated 03/07; it was reversed.",
    "SYSTEM UPGRADE NOTICE: settlement cycles shift to T+1 from next week.",
    "Refund processed as per customer request ticket #4471.",
]

# Ordinary, clean narrations.
CLEAN_NARRATION = [
    "RAZORPAY SETTLEMENT", "NEFT CR RAZORPAY", "UPI SETTLEMENT CREDIT",
    "IMPS RAZORPAY PVT LTD", "RTGS CREDIT RAZORPAY SOFTWARE",
]

FAILURE_CAUSES = ["insufficient_funds", "expired_mandate", "technical_decline", "issuer_decline"]
DISPUTE_REASONS = ["fraud", "product_not_received", "duplicate_processing",
                  "credit_not_processed", "unrecognized"]


def _person(rng: idg.Rng) -> dict[str, Any]:
    first = rng.choice(["Aarav", "Diya", "Vivaan", "Ananya", "Kabir", "Isha", "Reyansh", "Myra"])
    last = rng.choice(["Sharma", "Patel", "Reddy", "Nair", "Iyer", "Bose", "Khan", "Mehta"])
    name = f"{first} {last}"
    return {
        "name": name,
        "email": f"{first.lower()}.{last.lower()}@example.invalid",
        "contact": idg.gen_mobile(rng),
    }


def build_dataset(seed: int = 20260821) -> dict[str, Any]:
    rng = idg.Rng(seed)
    ds: dict[str, Any] = {"merchant_id": MERCHANT_ID, "currency": CURRENCY}

    # --- Fund accounts / counterparties (some known, one deliberately novel) ---
    fund_accounts = []
    for i in range(4):
        p = _person(rng)
        fund_accounts.append({
            "id": f"fa_{idg.Rng(seed + 100 + i).digits(14)}",
            "account_holder": p["name"],
            "account_number": idg.gen_bank_account(rng),   # PII
            "ifsc": idg.gen_ifsc(rng),                      # PII-ish
            "vpa": idg.gen_vpa(rng, p["name"]),             # PII
            "seen_before": i < 3,                            # first 3 are known; index 3 is NOVEL
        })
    ds["fund_accounts"] = fund_accounts

    # --- Payments (spanning statuses/methods; some carry PII + free text) ---
    payments = []
    for i in range(16):
        p = _person(rng)
        status = rng.choice(["captured", "captured", "captured", "authorized", "failed"])
        method = rng.choice(["card", "upi", "netbanking"])
        amount = rng.randint(10, 5000) * 100  # paise, ₹10–₹5000
        rec: dict[str, Any] = {
            "id": f"pay_{idg.Rng(seed + 200 + i).letters(14)}",
            "amount": amount, "currency": CURRENCY, "status": status,
            "method": method,
            "customer_id": f"cust_{idg.Rng(seed + 300 + i).letters(12)}",
            "email": p["email"], "contact": p["contact"], "name": p["name"],
            "created_at": 1_752_000_000 + i * 3600,
            "description": rng.choice(CLEAN_NARRATION + BENIGN_SUSPICIOUS),
            "notes": {"merchant_note": rng.choice(CLEAN_NARRATION)},
        }
        if method == "card":
            rec["card"] = {"last4": idg.gen_card(rng)[-4:], "network": rng.choice(["Visa", "MasterCard", "RuPay"])}
        if method == "upi":
            rec["vpa"] = idg.gen_vpa(rng, p["name"])
        payments.append(rec)
    ds["payments"] = payments

    # --- Settlements (14 -> forces pagination at count=10) + UTRs ---
    settlements = []
    for i in range(14):
        gross = rng.randint(5000, 50000) * 100
        fees = int(gross * 0.02)
        tax = int(fees * 0.18)
        settlements.append({
            "id": f"setl_{idg.Rng(seed + 400 + i).letters(12)}",
            "amount": gross - fees - tax,   # net settled (paise)
            "gross": gross, "fees": fees, "tax": tax, "currency": CURRENCY,
            "status": "processed",
            "utr": idg.gen_utr_neft(idg.Rng(seed + 500 + i)),
            "created_at": 1_752_100_000 + i * 86400,
        })
    ds["settlements"] = settlements

    # --- Bank statement lines, HAND-AUTHORED to hit every recon bucket ---
    # MATCHED: exact UTR + amount for settlements 0..8
    lines = []
    for i in range(9):
        s = settlements[i]
        lines.append({
            "line_no": len(lines) + 1, "date": "2026-07-%02d" % (i + 1),
            "narration": f"{rng.choice(CLEAN_NARRATION)} {s['utr']}",
            "utr": s["utr"], "credit": s["amount"], "debit": 0,
        })
    # AMOUNT_MISMATCH: settlement 9 present but credited short by an extra fee
    s9 = settlements[9]
    lines.append({"line_no": len(lines) + 1, "date": "2026-07-10",
                  "narration": f"NEFT CR RAZORPAY {s9['utr']}", "utr": s9["utr"],
                  "credit": s9["amount"] - 1500, "debit": 0})
    # settlement 10 -> MISSING_IN_STATEMENT (no line at all)
    # MISSING_IN_SETTLEMENTS: a bank credit whose UTR is not any settlement
    orphan_utr = idg.gen_utr_neft(idg.Rng(seed + 9999))
    lines.append({"line_no": len(lines) + 1, "date": "2026-07-11",
                  "narration": f"NEFT CR UNKNOWN SOURCE {orphan_utr}", "utr": orphan_utr,
                  "credit": 4500000, "debit": 0})
    # DUPLICATE_SUSPECTED: settlement 11 appears twice
    s11 = settlements[11]
    for d in range(2):
        lines.append({"line_no": len(lines) + 1, "date": "2026-07-12",
                      "narration": f"RTGS CREDIT RAZORPAY {s11['utr']}", "utr": s11["utr"],
                      "credit": s11["amount"], "debit": 0})
    # UNEXPLAINED: garbled narration, no parseable UTR, odd amount
    lines.append({"line_no": len(lines) + 1, "date": "2026-07-13",
                  "narration": "MISC ADJ ENTRY REF ****", "utr": None, "credit": 128700, "debit": 0})
    ds["bank_statement"] = {
        "account_number": idg.gen_bank_account(rng),
        "period": {"from": "2026-07-01", "to": "2026-07-31"},
        "lines": lines,
    }

    # --- Refunds ---
    refunds = []
    for i in range(3):
        pay = payments[i]
        refunds.append({
            "id": f"rfnd_{idg.Rng(seed + 600 + i).letters(12)}",
            "payment_id": pay["id"], "amount": pay["amount"], "currency": CURRENCY,
            "status": "processed", "speed_processed": "normal",
        })
    ds["refunds"] = refunds

    # --- Payouts (read-only) referencing fund accounts, with one to the novel FA ---
    payouts = []
    for i, fa in enumerate(fund_accounts):
        payouts.append({
            "id": f"pout_{idg.Rng(seed + 700 + i).letters(12)}",
            "fund_account_id": fa["id"], "amount": rng.randint(1000, 20000) * 100,
            "currency": CURRENCY, "status": "processed",
            "utr": idg.gen_utr_upi(idg.Rng(seed + 800 + i)),
        })
    ds["payouts"] = payouts

    # --- Disputes (fixture extension), across reason codes; some winnable ---
    disputes = []
    for i in range(4):
        pay = payments[i + 3]
        winnable = i % 2 == 0
        cust_msg = BENIGN_SUSPICIOUS[i % len(BENIGN_SUSPICIOUS)] if winnable else \
            "I never received the product and demand an immediate full refund."
        disputes.append({
            "id": f"disp_{idg.Rng(seed + 900 + i).letters(12)}",
            "payment_id": pay["id"], "amount": pay["amount"], "currency": CURRENCY,
            "reason_code": DISPUTE_REASONS[i % len(DISPUTE_REASONS)],
            "status": "open", "respond_by": 1_753_000_000,
            "customer_message": cust_msg,           # UNTRUSTED
            "evidence_available": {
                "shipping_proof": winnable, "delivery_confirmation": winnable,
                "customer_communication": True, "refund_policy": True,
            },
        })
    ds["disputes"] = disputes

    # --- Subscriptions with failed payments across every cause ---
    subs = []
    for i in range(4):
        fa = fund_accounts[i]
        subs.append({
            "id": f"sub_{idg.Rng(seed + 1000 + i).letters(12)}",
            "customer_id": f"cust_{idg.Rng(seed + 1100 + i).letters(12)}",
            "mandate_fund_account": fa["id"],
            "amount": rng.randint(200, 2000) * 100, "currency": CURRENCY,
            "status": "active",
            "last_failure": {
                "cause": FAILURE_CAUSES[i], "attempts": rng.randint(1, 3),
                "retry_viable": FAILURE_CAUSES[i] in ("insufficient_funds", "technical_decline"),
            },
            "counterparty_seen_before": fa["seen_before"],
        })
    ds["subscriptions"] = subs

    ds["version"] = sha256_hex({k: v for k, v in ds.items() if k != "version"})[:16]
    return ds


# Module-level cached default dataset (deterministic, so caching is safe).
_DEFAULT: dict[str, Any] | None = None


def default_dataset() -> dict[str, Any]:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = build_dataset()
    return _DEFAULT


def dataset_version() -> str:
    return default_dataset()["version"]
