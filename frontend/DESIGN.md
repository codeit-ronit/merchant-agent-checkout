# CONDUIT interface — the design pass (before any component; 09-UI §6)

The subject is **an agent spending someone's money under a limit they set**.
The vernacular is authorisation, drawdown, commitment, receipt — a ledger,
not an app.

## 0. The governing decision: extend, don't invent

The operator surface already carries a deliberate system: ink/slate ground,
muted brass accent, serif display, genuine monospace with tabular figures for
every amount/id/hash, and decision states that read **without colour** (glyph
+ word, never a bare swatch). The buyer surface and merchant console are the
same product seen from two sides — they extend that system. Inventing a
second identity would say the commerce loop is a different thing from its
enforcement, which is the opposite of the thesis. All deltas below are
additions to `styles.css`'s existing tokens.

## 1. Color — commerce state, mapped onto the existing palette

The information colour must carry is STATE. No new hues: commerce states bind
to the proven decision hues, each with its own GLYPH and WORD so every state
survives grayscale (financial software; colour-blind users exist).

| State | Token (maps to) | Glyph + word | Where |
|---|---|---|---|
| SET ASIDE (authorised) | `--await` blue | `● set aside` | mandate created |
| RESERVING (spending) | `--escalate` amber | `◔ reserving` | hold placed, not confirmed |
| COMMITTED | `--allow` green | `✓ committed` | drawdown confirmed / order minted |
| BLOCKED | `--deny` red | `✕ blocked` | policy DENY / gate rejection |
| EXHAUSTED / EXPIRED / REVOKED | `--muted` grey | `○ exhausted` etc. | mandate dead states |
| MODELLED | outline chip, `--muted` | `▢ modelled` | catalog/cart/mandate/rail data |
| REAL · TEST MODE | outline chip, `--accent` brass | `◆ Razorpay · test` | order ids, fetch_order data |

The brass accent stays reserved for what it already means: provenance of the
real rail. The real-vs-modelled chips are PERSISTENT (09 §5) — on the panel
headers, not a footnote.

## 2. Type

Unchanged trio: `--serif` for view titles (the ledger voice), `--sans` for
prose/controls, `--mono` for **every** amount, id, hash, and reason code.
One addition: **money is the hero** — the mandate meter's remaining amount
and the cart total render in large tabular mono (`font-variant-numeric:
tabular-nums`, 28–34px). Misaligned money is a correctness signal.

## 3. The split view (the signature — spend the boldness here)

```
┌─ BUY ─ Fresh Basket ─────────────────────────┬─ THE MACHINERY ── ▢ modelled · ◆ Razorpay test ─┐
│                                              │  MANDATE  mnd_000001            ● set aside      │
│  "Order dinner for four under ₹800,          │  ₹1,427.40 remaining of ₹2,000.00                │
│   no beef."                        [Send]    │  ████████████████████░░░░░░  ← THE one animation │
│                                              ├──────────────────────────────────────────────────┤
│  ┌─ agent ────────────────────────────────┐  │  CART  cart_000001  · server-priced  ▢ modelled  │
│  │ Reading the catalog…                   │  │  Steamed Rice        ×4   ₹360.00  + ₹18.00 tax  │
│  │ Adding steamed rice for four.       ←──┼──┼→ Tandoori Roti       ×4   ₹100.00  +  ₹5.00 tax  │
│  │ Adding rotis.                          │  │  Gulab Jamun (2pc) ↖rule ×1  ₹80.00 + ₹9.60 tax  │
│  │ The merchant offers a dessert — it     │  │  TOTAL                        ₹572.60            │
│  │ fits your budget; adding it.           │  ├──────────────────────────────────────────────────┤
│  │ Committing at ₹572.60…                 │  │  EVENTS (each row: stamp + plain words)          │
│  └────────────────────────────────────────┘  │  ✓ policy   catalog_search — allowed: read-only  │
│                                              │  ✓ policy   cart_commit — inside your mandate    │
│  ┌─ receipt ──────────────────────────────┐  │  ✓ commerce COMMITTED → order_TVW…  ◆ real       │
│  │ ₹572.60 · order_TVWCd7…  ◆ Razorpay    │  │  ✓ policy   initiate_payment — consent upfront  │
│  │ paid · inside your ₹2,000 mandate      │  │  ✓ rail     captured ▢ modelled                  │
│  └────────────────────────────────────────┘  │                                                  │
└──────────────────────────────────────────────┴──────────────────────────────────────────────────┘
```

**The moment to design for:** the agent says "Adding steamed rice" on the
left while, on the right, the line item appears, the total recomputes, and
the mandate bar shrinks — one SSE event drives both sides, so the synchrony
is structural, not choreographed.

**The two-verdict row** (the ADR-032/033 nuance — the thing a payments
engineer will stop on). One event, two verdicts, both true, side by side:

```
│  ┌ cart_commit ──────────────────────────────────────────────────────┐   │
│  │  ✓ POLICY allowed — inside your mandate    ✕ COMMERCE refused —   │   │
│  │    (the call was permitted to run)           the price changed:   │   │
│  │                                              Steamed Rice ₹90→₹120│   │
│  │  next step: re-confirm at ₹698.60, adjust, or abandon             │   │
│  └───────────────────────────────────────────────────────────────────┘   │
```

Never render these as a contradiction and never hide one: policy permitted
the call; commerce refused the outcome. That pairing IS the architecture.

## 4. Motion — once, precisely

The mandate meter's width transition (300ms ease-out) is the only continuous
animation; it is the only place a value moves continuously and the motion
carries meaning (money being consumed / returning on reversal).
`prefers-reduced-motion: reduce` ⇒ no transition, values still update.
Everything else appears without animation.

## 5. Copy — from the user's side of the screen

| System term | The screen says |
|---|---|
| mandate created | **₹2,000 set aside for Fresh Basket** |
| DENY_MANDATE_EXHAUSTED | **Blocked: this would take you ₹340 over your limit** |
| reprice divergence | **The price changed while we were shopping. Steamed Rice is now ₹120, up from ₹90. New total ₹698.60.** |
| REVERSE ledger entry | **Payment failed — your ₹572.60 is back in the mandate. The order is held; retrying is safe.** |
| revoke | button: **Revoke now** → state: **Revoked — nothing further can be spent** |

Reason codes stay visible in small mono under the plain words (explainable
means both audiences). Errors state what happened and the next step; they
never apologise and are never vague. Buttons keep their names through the
flow ("Set aside" → "Set aside ✓").

## 6. Buyer surface beyond the split view

* **Mandate creation** — feels like setting money aside, not a form: one
  amount field (large mono), merchant name fixed, expiry picker, button
  "Set aside". Result state: `● ₹2,000 set aside for Fresh Basket`.
* **Failure states** are designed, not residual: decline (order held card +
  safe-retry note), re-price (itemised diff table, old→new per line),
  blocked (reason + next step). Each names what happened, the state now, and
  what to do.
* **Empty states** invite action ("No mandate yet — set one aside to let the
  agent shop.").

## 7. Merchant console (catalog + mandates; other views are Phase-8 cuts)

```
┌ CATALOG — Fresh Basket ▢ modelled ──────────────────────────────────┐
│ TRUSTED (machine truth)                    │ UNTRUSTED (your text)  │
│ id · price (mono) · stock · tax · attrs    │ name · description     │
│ itm_steamed-rice  ₹90.00  IN_STOCK  5%     │ "Steamed Rice" …       │
│  — header note: "Your descriptions are treated as untrusted data —  │
│     an agent will never obey instructions written in them."         │
└─────────────────────────────────────────────────────────────────────┘
┌ MANDATES ────────────────────────────────────────────────────────────┐
│ mnd_000001  ● set aside  ₹1,427.40 / ₹2,000.00   [Revoke now]        │
│  revoke is INSTANT: meter empties, in-flight commits are refused     │
└──────────────────────────────────────────────────────────────────────┘
```

## 8. Quality floor

Responsive: the split view stacks (conversation, then machinery) below
900px. Visible keyboard focus (existing tokens). Reduced motion respected.
Every view has designed empty and error states. Amounts tabular-aligned
everywhere.

## 9. Data contract

One SSE stream drives both panes: the purchase runs deterministically
server-side; each trace event is enriched at capture with a commerce
snapshot `{mandate_view, cart_view}` and replayed paced (the existing
run-stream pattern). Left pane renders narration events; right pane renders
the snapshots and stamped decision rows from the SAME events — synchrony by
construction.
