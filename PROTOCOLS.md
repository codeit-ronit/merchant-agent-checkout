# Protocols — which layer each occupies, and what this project claims

The agentic-commerce protocol landscape is crowded and the names get blurred.
This file states, precisely, where each protocol sits and what CONDUIT's
relationship to it is. The claim levels are the ones used everywhere in this
repo: **Real** (we call it), **Modelled** (we implement its semantics over real
primitives, without the protocol), **Referenced** (we cite it for orientation
and claim nothing).

| Protocol | Who / where | Layer | CONDUIT's relationship |
|---|---|---|---|
| **MCP** | Anthropic, open | Tool discovery & transport | **Real.** The buyer agent reaches every tool over MCP through the SENTINEL proxy; the upstream is the published `razorpay/mcp` image (41 tools, live-verified 2026-08-29). |
| **A2A** | Google-led, open | Agent-to-agent discovery/messaging | **Referenced.** Single-agent build; no agent-to-agent hop exists here. |
| **ACP** | OpenAI + Stripe | Checkout: agent ↔ merchant commerce flow | **Referenced.** The catalog + cart fill the same gap for Razorpay merchants that ACP's structured feeds fill in the Stripe world. We implement no ACP endpoint. |
| **UCP** | Stripe-world unified checkout | Checkout: structured product feeds | **Referenced.** Same as ACP: the gap analogue, not the protocol. |
| **AP2** | Google-led agent payments protocol | Authorization: Intent / Cart / Payment mandates | **Modelled shape, not the protocol.** CONDUIT's constraint → committed cart → order+payment maps structurally onto AP2's three mandates. No AP2 message, signature, or endpoint is implemented. Never write "implements AP2". |
| **UPI Reserve Pay** | NPCI, launched GFF 2025 | Rail: block funds once, debit within the block without repeated PINs | **Modelled.** Reserve Pay is an NPCI *rail-layer* product. It is not a Razorpay API and does not appear in the MCP tool surface as a tool. CONDUIT's mandate implements its policy semantics (lock, scope, expiry, drawdown, instant revoke) over real test-mode primitives. |
| **UAP** | NPCI Unified Agentic Payments | Agent authority: verify authority, define limits, establish accountability | **Referenced, intent only.** Not public; requires RBI approval. CONDUIT is forward-compatible with its stated purpose — nothing more. Never write "UAP-compliant". |
| **x402** | Coinbase-led HTTP 402 payments | Settlement (machine-native) | **Referenced.** Out of scope; settlement here is UPI/card test rails. |
| **Card rails / UPI** | Razorpay gateway, test mode | Settlement | **Split (ADR-034).** `create_order` and every read-back are **Real** against `rzp_test_*` keys — order ids are Razorpay-minted. The settlement leg (`initiate_payment` → `submit_otp`) is **Modelled**: the S2S payment API is feature-gated and not enabled on this account (verified empirically — 404 from the wrapped endpoint for both documented test VPAs). The modelled rail is faithful to the documented shapes, marks every entity `"modelled": true`, and drops out for the real tools if S2S is ever enabled. Money never moves; data is synthetic. |

## One empirical nuance (found 2026-08-29, Phase 0)

The live `create_order` tool schema natively accepts **mandate-order
parameters**: `customer_id`, `method: "upi"`, and a `token` object carrying
`max_amount`, `frequency`, and `type: "single_block_multiple_debit"` — the UPI
block-and-debit primitive that Reserve Pay builds on. So while no *tool* in the
41-tool surface is named for mandates, the *arguments* of `create_order` do
expose a mandate-shaped rail feature.

CONDUIT's mandate remains **Modelled** — the claim upgrades only if the
single-block-multiple-debit flow is verified to work end-to-end in test mode
with real test keys (candidate experiment for Phase 3, recorded in
`DECISIONS.md`). Until then the distinction stands: **our mandate object,
drawdown ledger, and revocation are ours; the rail's block-and-debit argument
surface exists but is unexercised.**

## The sentence that keeps this honest

> Mandate semantics are modelled on UPI Reserve Pay — an NPCI rail-layer
> product that Razorpay's own agentic pilot is built on. Reserve Pay is not
> exposed in Razorpay's API or MCP surface, so this is a faithful model over
> real test-mode primitives, not an integration. AP2's three-mandate structure
> is the global analogue; UAP is not yet public and is referenced only for
> forward-compatibility of intent.
