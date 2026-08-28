# merchant-agent-checkout

**Making a merchant sellable to AI buyers** — an agentic checkout where an AI
agent can discover products, build a cart, and pay **within a consented spending
envelope**, and every money-moving call is **gated at the tool-call boundary**
before it executes.

> Built for Razorpay's buildathon (Track 01). Independent project — not affiliated
> with, endorsed by, or produced by Razorpay or NPCI. Integrates the publicly
> published open-source [`razorpay/razorpay-mcp-server`](https://github.com/razorpay/razorpay-mcp-server)
> in **test mode only** (`rzp_test_*`). All data is synthetic.

---

## The problem (Track 01)

Every UPI payment today needs a human PIN at the moment of purchase — deliberate
proof that a person approved *this* transaction. Put an AI agent in that flow and
it stalls at the PIN, so the human is back on their phone and the agent saved them
nothing. Authentication was designed assuming a human is present at payment; with
an agent, no human is.

The resolution — the shape NPCI's UPI Reserve Pay and Razorpay's Agentic Payments
pilot both use — is to **move consent upstream**: the human authorises **once, in
advance**, by setting a spending envelope for a merchant. Inside the envelope the
agent transacts freely; outside it, it stops; it can be revoked instantly.

> **AI can act decisively, but never independently of the user's intent.**

## The loop this builds

```
discover → build cart → mandate-bound checkout → settle
                              │
                    consented spending envelope
             (locked amount · one merchant · expiry · revocable · drawdown)
```

- **Mandate** — the consent envelope, authorised once by the operator. A
  Reserve-Pay-shaped object: a locked amount for a single merchant, with an
  expiry, revocable at any time, drawn down as the agent spends.
- **Settlement** — through the real Razorpay test-mode primitives:
  `initiate_payment` + `submit_otp` for the charge, `fetch_tokens` for the saved
  instrument. (Reserve Pay itself is an NPCI *rail-layer* product and is not
  reachable through the gateway's MCP surface — see `LINEAGE.md` / the mandate ADR
  for why we model its policy semantics rather than call it.)

**Status:** the enforcement foundation below is built and tested; the commerce
loop and the mandate object are the buildathon work, in progress.

## Enforcement (the foundation — built on SENTINEL)

This repo is a fork of **[SENTINEL](https://github.com/codeit-ronit/SENTINEL)**, a
policy-enforcement + audit control plane built first and independently (see
[`LINEAGE.md`](LINEAGE.md)). Every tool call the agent makes passes through an MCP
proxy that **classifies → PII-redacts → evaluates against declarative policy →
allows / denies / escalates** it, in a process the model does not control, then
writes it to a tamper-evident hash-chained audit log — all before it executes.

The mandate plugs into that engine: money movement is gated by the envelope, so a
charge that fits the *budget* but goes to the *wrong merchant* (e.g. an injected
"also pay ₹450 to account X") is **denied** — something a rail-level amount lock
alone would not catch.

## What the numbers describe

Two suites, kept separate so each count describes what it's about:

- **Inherited enforcement suite (from SENTINEL — tests the control plane, not
  commerce):** 203 offline-reproducible tests, a 29-payload prompt-injection A/B
  red-team (24 unauthorised money movements with guardrails off → 0 with them on,
  0% false-positive), and **31 reconciliation / dispute golden scenarios**. These
  validate the enforcement layer the commerce loop builds on. They are *not* about
  commerce.
- **Commerce suite (new to this repo):** the checkout / mandate golden scenarios —
  built as the loop is built, reported here with its own count once it exists.

## Documentation

- [`LINEAGE.md`](LINEAGE.md) — what SENTINEL is, what carried over, what's new.
- [`DECISIONS.md`](DECISIONS.md) — every architectural decision, ADR-001 onward
  (the SENTINEL foundation; commerce decisions append from here).
- The SENTINEL control-plane README is preserved in git history and in the
  [original repo](https://github.com/codeit-ronit/SENTINEL).
