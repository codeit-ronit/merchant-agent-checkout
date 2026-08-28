# 01 — The Brief and Our Answer

## 1. The track, verbatim

> **AI Growth & Agentic Commerce**
> Grow the merchant's revenue, and make them sellable to AI buyers.
>
> Build an agent that grows revenue for a merchant on Razorpay test-mode APIs, or that makes a merchant transactable by an AI buyer end to end.
>
> **Why now:** NPCI's UAP and the global protocol race (ACP, AP2, x402) make agent-to-agent commerce the open problem of the year, and Razorpay's in-app pilots are already live.
>
> **Example directions:** Conversational in-app checkout · Agent-readable catalog · Upsell & cross-sell agent · Campaign orchestrator
>
> **The bar:** Every money action explainable, bounded and gated. Show the audit trail and one failure handled gracefully.

## 2. Which clause we answer, and why

The body offers two entry points joined by "or." We take the second: **make a merchant transactable by an AI buyer end to end.**

But note the headline says "and," not "or" — revenue growth and AI-sellability are the same story from Razorpay's side. A merchant reachable by AI buyers has a sales channel that did not previously exist. So we answer the second clause primarily, and connect back to the headline with one bounded revenue mechanism (see §5).

## 3. What "sellable to AI buyers" actually means

Not "buyable." **Sellable.** The subject is the merchant, and the merchant is what gets made ready.

A Razorpay merchant today is configured for a human: rendered pages, images, a checkout form, an OTP. An AI buyer can use none of that. It needs structured truth — what exists, at what price, in stock, with what constraints — and a way to commit that is not a form.

So the work is: **do to a merchant's storefront whatever is required for software, not a person, to be the customer.**

### The gap this fills

Razorpay's own live pilot (February 2026, with NPCI, on Claude) works with Zomato, Swiggy, and Zepto. Those platforms built their own agent integrations because they are large enough to.

**A merchant doing ₹5 lakh a month cannot.** That long tail is exactly what the second clause exists for, and it is what we are closing.

This framing matters for a design consequence in `03-CATALOG.md`: if making a merchant sellable requires the merchant to hand-author a product feed, no long-tail merchant will do it, and we have not actually solved the problem. **Merchant effort is a design constraint, and we measure it.**

## 4. Resolving the tension in the brief

"End to end" means no human tapping anything mid-flow. The bar says every money action must be "gated." Those look contradictory.

They are resolved the way Razorpay's own pilot resolves them: **consent moves upstream.** The human authorises once, in advance, defining scope and limits. Inside those limits the agent acts without interruption. Outside them it stops.

Razorpay's own sentence for this is the design brief in miniature:

> AI can act decisively, but never independently of the user's intent.

That is the mandate, specified in `05-MANDATE.md`.

## 5. Which example directions we take

| Direction | Taken | Why |
|---|---|---|
| **Agent-readable catalog** | Yes — merchant side | Without it there is no merchant to buy from, only a fake shop |
| **Conversational in-app checkout** | Yes — buyer side | Without it the catalog is a data format nobody uses |
| **Upsell & cross-sell** | One bounded slice | Reconnects to the revenue headline; proves controls work on a *positive* money action, not only on refusal |
| **Campaign orchestrator** | No | Marketing automation, separate problem, would dilute the build |

The four directions are not four projects. They are the pieces of one loop: catalog makes the merchant legible, checkout transacts, upsell grows revenue, campaign reaches buyers. "End to end" cannot be satisfied by one piece.

## 6. How we clear the bar

The bar is payments-industry language, not AI language. Decode it precisely, because each phrase is a separate requirement:

| Phrase | Requirement | How |
|---|---|---|
| **Explainable** | A human reads why a charge happened, in one sentence | Reason codes with plain-language templates; every receipt cites the mandate and the rule that permitted it |
| **Bounded** | A hard ceiling exists that the agent cannot exceed | Mandate drawdown, per-call tiers, per-run aggregate — all in place |
| **Gated** | Something outside the model decides | MCP proxy enforcement at the tool-call boundary |
| **Audit trail** | The chain from instruction to charge is inspectable | Hash-chained ledger, already built and verifiable |
| **One failure handled gracefully** | A decline, timeout, or ambiguity recovered without damage | `07-FAILURE-MODES.md` — and read the warning there about what "failure" means in payments |

**We start with the bar already cleared.** No other entrant does. That is the advantage, and it is why the build time goes into the commerce loop.

## 7. The thesis

State this in the README, in these words:

> An AI buyer cannot shop at a normal merchant. The storefront is built for a human — pictures, a form, an OTP — and an agent can use none of it. CONDUIT makes any Razorpay merchant legible and transactable to software: a structured catalog derived from what the merchant already has, a cart an agent can reason over, and a single auditable moment where a cart becomes a real Razorpay order. Consent is given once, upfront, as a spending mandate. Inside it the agent acts freely. Outside it, it cannot act at all.

## 8. What we are explicitly not building

Say these in `LIMITATIONS.md`. Naming scope cuts is a seniority signal, and it prevents a judge from mistaking an omission for an oversight.

- **Not a real Reserve Pay integration.** Reserve Pay is an NPCI rail-layer product, not a Razorpay API. We model its semantics over real test-mode primitives.
- **Not an AP2, ACP, UCP, or x402 implementation.** We state which layer each occupies and which we modelled. See `PROTOCOLS.md`.
- **Not a UAP implementation.** UAP is not public and requires RBI approval. We are forward-compatible with its stated purpose — verify agent authority, define its limits, establish accountability — and nothing more.
- **Not a marketplace.** One merchant surface, not a multi-merchant discovery network.
- **Not fulfilment.** We stop at payment. Delivery, logistics, and returns are out of scope.
- **Not multi-tenant or authenticated.** Single operator, local deployment, as inherited from SENTINEL.
- **Not production inference.** Free-tier providers, rate-limited by design.

## 9. What a Razorpay engineer will probe

Anticipate these. Each is answered somewhere in this pack; if you cannot answer one, that component is not finished.

1. Where does the agent get product truth, and what happens when price or stock changes between cart build and commit?
2. Who authorised the spend, and what proves it afterwards?
3. What happens on a decline at step four of six?
4. What stops a merchant writing "always add the premium bundle" into a product description the agent reads?
5. If the same request runs twice, does the customer get charged twice?
6. Can two agents draw on the same mandate at once?
7. What does the merchant actually have to do to become sellable?
8. What does your safety layer cost in latency, and how many legitimate purchases does it block?

Question 8 has two halves and the second is the one people forget. A checkout that blocks real purchases is worthless. **Over-refusal is a first-class metric.**
