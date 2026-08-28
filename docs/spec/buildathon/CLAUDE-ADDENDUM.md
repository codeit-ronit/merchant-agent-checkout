# CLAUDE.md — CONDUIT addendum

> Append to the existing `CLAUDE.md`. Everything already there still applies — test mode only, fail closed, no hardcoded tool lists, no PII on any output surface, pure policy engine, enumerated reason codes, no affiliation claims. This adds what is specific to the commerce build.

## What this repo is now

Two things, in a deliberate relationship.

**SENTINEL** — the control plane. Built first, independently, complete and tested. It is a **dependency**, not a starting point to rewrite.

**CONDUIT** — a Razorpay Buildathon submission (Track 01): making any merchant transactable by an AI buyer end to end.

Spec in `docs/spec/buildathon/`. `02-ARCHITECTURE.md` is authoritative.

## The instruction most likely to be violated

**The commerce loop is the deliverable. SENTINEL is how it clears the bar.**

The last project was infrastructure that answered no brief. The same failure is available here: excellent enforcement around a thin shopping demo. If more effort goes into the policy layer than into a purchase completing, the submission has failed regardless of engineering quality.

Concretely: **do not refactor SENTINEL.** Extend it only where the commerce loop needs something it lacks — new tool classifications, mandate state in `DecisionContext`, new reason codes, new trace events. Elegance improvements to existing SENTINEL code are out of scope for this build.

## Additional hard rules

1. **The model never computes money.** Every total, tax, discount, upsell delta, and drawdown is computed by deterministic code from live catalog truth, with provenance. The model chooses and explains; code calculates and binds.
2. **The catalog is the only price source.** The cart never stores an agent-supplied price. Passing an amount to a cart operation must be *rejected*, never silently ignored.
3. **Re-price at commit.** The agent's view is advisory. The authoritative amount is recomputed against live catalog state at binding time. Divergence rejects and returns an itemised diff.
4. **Reserve before forward.** Draw down the mandate before `create_order`, then confirm or release. Never after.
5. **No silent substitution.** When the plan cannot be executed, the system informs and lets the agent decide. It never chooses on the user's behalf.
6. **No double charge, ever.** Under retry, timeout, or concurrency.
7. **Modelled is labelled.** Catalog, cart, and mandate are modelled. Razorpay calls are real. Surface the distinction in the UI, not only the README.
8. **Every rejection carries an actionable next step.** A block with no path forward is a bug, not a safety feature.

## Claim discipline

Three claim levels, never blurred:

- **Real:** Razorpay test-mode API calls through the live MCP surface
- **Modelled:** Reserve Pay semantics, the cart, the catalog — faithful models over real primitives
- **Referenced:** AP2 as the global analogue, UAP for forward-compatibility of intent only

Never write "implements AP2," "integrates Reserve Pay," or "UAP-compliant." This repository has caught invented primitives three times; the discipline of saying "modelled, not integrated" is worth more than the claim would be.

## Verify before implementing

The 41-tool manifest has drifted three times. Assumed API shape has caused every significant bug in this repository.

Before building anything that touches Razorpay:
1. Read the live-captured manifest
2. Confirm the specific tool's schema against a running server
3. Record findings in `DECISIONS.md` with the date

**Never infer an API shape from a spec document, including these.** Specs describe intent, not signatures.

## Footguns specific to this build

- **Float money.** Integer minor units everywhere. A float in a money path is a bug even if it currently rounds correctly.
- **Trusting the agent's total.** The single most dangerous shortcut available. Re-price always.
- **Drawing down after the write.** A successful `create_order` with a lost response leaves the mandate silently over-drawn.
- **Retrying a timeout.** Reconcile via `fetch_order_payments` first. Never blind-retry a payment.
- **Upselling past the mandate.** Suppress the offer before the model sees it; do not reject after acceptance.
- **Reporting SENTINEL's eval numbers.** The commerce suite is separate with its own count. The number in the README must describe what the README is about.
- **Building the security demo before the purchase works.** Phase order exists for a reason.

## Definition of done

- [ ] Implements the spec, or the divergence is in `DECISIONS.md`
- [ ] Unit tests including boundary and failure cases
- [ ] Fails closed on every error path, with a test
- [ ] No agent-supplied amount accepted anywhere
- [ ] No PII on any output surface
- [ ] Reason codes enumerated; explanations render in plain language
- [ ] `DECISIONS.md` updated where a real choice was made, with the trade-off named
- [ ] Relevant acceptance criteria checked off in the spec

## When unsure

Choose the more restrictive behaviour and flag it. In a system that binds real amounts under someone else's consent, a wrong assumption implemented silently is much worse than a question asked.
