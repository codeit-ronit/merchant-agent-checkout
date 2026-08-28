# CONDUIT — Specification Pack

> Making any Razorpay merchant transactable by an AI buyer, end to end.
> Razorpay Buildathon, Track 01: AI Growth & Agentic Commerce.

## What this pack is

A specification, not a codebase. It is written to be executed by an autonomous coding agent working in the forked repository that already contains SENTINEL.

Every document answers three questions in order: what is currently true, what problem we are solving, and how we proceed. It deliberately contains no implementation code — library versions move and APIs drift, and this project has already been bitten three times by config that disagreed with a live server. Each document instead carries **VERIFY FIRST** blocks naming exactly what must be checked against reality before that component is built.

## The single most important instruction

**The commerce loop is the deliverable. SENTINEL is how it clears the bar.**

The previous project was a control plane that answered no brief. The same mistake is available again in a new costume: building beautiful enforcement around a thin shopping demo. If the demo spends more time on policy engines than on a purchase completing, the submission has failed regardless of engineering quality.

A judge should watch a person say "order dinner for four under ₹800" and watch it happen. The enforcement should feel like the reason they can trust what they just watched — not like the subject of the video.

## Reading order

| # | Document | Read when |
|---|---|---|
| 01 | `01-BRIEF-AND-THESIS.md` | First. What the track asks and how we answer each clause. |
| 02 | `02-ARCHITECTURE.md` | Before any code. Authoritative. |
| 03 | `03-CATALOG.md` | Phase 1 |
| 04 | `04-CART-AND-COMMIT.md` | Phase 2 — the core of the build |
| 05 | `05-MANDATE.md` | Phase 3 |
| 06 | `06-BUYER-AGENT-AND-UPSELL.md` | Phase 4 |
| 07 | `07-FAILURE-MODES.md` | Phase 5. Read early anyway — it shapes everything. |
| 08 | `08-EVAL.md` | Phase 6 |
| 09 | `09-UI.md` | Phase 7 |
| 10 | `10-BUILD-ORDER.md` | **Read after 02. Drives the whole build.** |
| 11 | `11-DEMO-AND-SUBMISSION.md` | Phase 8, and before recording anything |
| — | `CLAUDE-ADDENDUM.md` | Append to the repo's existing `CLAUDE.md` |
| — | `KICKOFF-PROMPT.md` | The prompt to start with |

## What already exists in the repo

SENTINEL, complete and tested: MCP proxy, pure policy engine with binding roles, PII redaction, hash-chained audit ledger, approval store, idempotency guard, provider abstraction with cassettes, eval and red-team harnesses, operator console, 203 tests.

**Treat it as a dependency, not a starting point to rewrite.** Extend it where the commerce loop needs something it does not have. Do not refactor it for elegance. Every hour spent improving SENTINEL is an hour not spent on the thing being judged.

## Non-negotiable rules

1. **Test mode only.** `rzp_test_*`. Never live keys, never real data.
2. **Fail closed.** Unknown tool, unparseable argument, missing mandate, evaluation error → deny.
3. **The model never does arithmetic on money.** Every total, tax, discount, and drawdown is computed by deterministic code with provenance. The model chooses and explains; code calculates.
4. **No invented primitives.** The live 41-tool manifest is the truth. There is no cart object upstream, no mandate API, no Reserve Pay endpoint. Anything modelled is labelled as modelled.
5. **Honest claim levels.** We model Reserve Pay semantics; we do not integrate with it. AP2 is the global analogue; we do not implement it. UAP is not public; we are forward-compatible with its stated purpose only.
6. **Every money action explainable, bounded and gated.** The track's bar, and the reason the enforcement layer exists.

## What "done" looks like

A judge, in ten minutes:

- Reads a README that opens with a purchase, not an architecture diagram.
- Watches a 3-minute video where a natural-language instruction becomes a real Razorpay test-mode order with a Razorpay-minted ID.
- Sees a payment fail mid-flow and the system recover without double-charging.
- Sees a merchant's own product description try to manipulate the agent, and fail.
- Opens a live demo and completes a purchase themselves.
- Reads measured numbers: task success, mandate violations, over-refusal rate, cost and latency per purchase.
- Finds a `LIMITATIONS.md` that is honest about what is modelled and what is real.
