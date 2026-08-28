# CLAUDE.md — CONDUIT, built on SENTINEL

Operating instructions for any coding agent working in this repository. Read fully before the first edit of any session.

## What this repo is

Two things, in a deliberate relationship.

**CONDUIT** — the deliverable. A Razorpay Buildathon submission (Track 01: AI Growth & Agentic Commerce): making any Razorpay merchant transactable by an AI buyer, end to end. The spec is in `docs/spec/buildathon/` — start at `00-START-HERE.md`. `02-ARCHITECTURE.md` there is **authoritative** and overrides any conflicting instruction elsewhere, including this file. `10-BUILD-ORDER.md` drives the build.

**SENTINEL** — the control plane CONDUIT runs on. Built first, independently, complete and tested: MCP proxy, pure policy engine with binding roles, PII redaction, hash-chained audit ledger, approval store, idempotency guard, provider abstraction with cassettes, eval and red-team harnesses, operator console. It is a **dependency, not a starting point to rewrite.** Its spec lives in `docs/spec/` (01–14) and remains the reference for the dependency's internals. Provenance in `LINEAGE.md`.

SENTINEL's central claim still holds and is why CONDUIT clears the track's bar — *every money action explainable, bounded and gated*: prompt-level guardrails are advisory; enforcement at the tool-call boundary is a property of the system.

## The instruction most likely to be violated

**The commerce loop is the deliverable. SENTINEL is how it clears the bar.**

The last project was infrastructure that answered no brief. The same failure is available here in a new costume: excellent enforcement around a thin shopping demo. If more effort goes into the policy layer than into a purchase completing, the submission has failed regardless of engineering quality.

Concretely: **do not refactor SENTINEL.** Extend it only where the commerce loop needs something it lacks — new tool classifications, mandate state in `DecisionContext`, new reason codes, new trace events (the closed list in `docs/spec/buildathon/02-ARCHITECTURE.md` §4.6). Elegance improvements to existing SENTINEL code are out of scope for this build.

A judge should watch a person say "order dinner for four under ₹800" and watch it happen as a real Razorpay test-mode order. The enforcement should feel like the reason they can trust what they just watched — not like the subject of the video.

## Hard rules — violating any of these is a build failure

Inherited from SENTINEL, all still binding:

1. **Test mode only.** `rzp_test_*` keys. Never live keys. Never real data. No credential ever committed.
2. **Fail closed, everywhere.** Unknown tool, unparseable argument, missing policy, missing mandate, evaluation exception, upstream error → `DENY`. Never allow on exception. Never allow by default.
3. **No hardcoded tool lists.** Tools are discovered at runtime via `tools/list` and reconciled against config. An unclassified tool is denied.
4. **No PII in any output surface.** Not in prompts, traces, audit entries, logs, API responses, or files. The PII invariant test is the highest-priority test in the repo.
5. **The policy engine performs no I/O.** No clock, no network, no database, no randomness. Enforced by a CI import check (`make purity`).
6. **The agent loop contains no provider-specific branching.** If it does, the provider abstraction has leaked and must be fixed, not worked around.
7. **Every denial carries an enumerated reason code and a plain-language explanation.** A block without a reason is a bug.
8. **Red-team code runs in fixture mode only.** Never against a hosted endpoint. Enforced in code and tested.
9. **No affiliation claims.** Independent project integrating with publicly published open-source software.

Commerce-specific, added by CONDUIT:

10. **The model never computes money.** Every total, tax, discount, upsell delta, and drawdown is computed by deterministic code from live catalog truth, with provenance. The model chooses and explains; code calculates and binds.
11. **The catalog is the only price source.** The cart never stores an agent-supplied price. Passing an amount to a cart operation must be *rejected*, never silently ignored.
12. **Re-price at commit.** The agent's view is advisory. The authoritative amount is recomputed against live catalog state at binding time. Divergence rejects and returns an itemised diff.
13. **Reserve before forward.** Draw down the mandate before `create_order`, then confirm or release. Never after.
14. **No silent substitution.** When the plan cannot be executed, the system informs and lets the agent decide. It never chooses on the user's behalf.
15. **No double charge, ever.** Under retry, timeout, or concurrency.
16. **Modelled is labelled.** Catalog, cart, and mandate are modelled. Razorpay calls are real. Surface the distinction in the UI, not only the README.
17. **Every rejection carries an actionable next step.** A block with no path forward is a bug, not a safety feature. (Composes with rule 7: reason code, plain-language explanation, *and* what to do next.)

## Claim discipline

Three claim levels, never blurred:

- **Real:** Razorpay test-mode API calls through the live MCP surface
- **Modelled:** Reserve Pay semantics, the cart, the catalog — faithful models over real primitives
- **Referenced:** AP2 as the global analogue, UAP for forward-compatibility of intent only

Never write "implements AP2," "integrates Reserve Pay," or "UAP-compliant." This repository has caught invented primitives three times; the discipline of saying "modelled, not integrated" is worth more than the claim would be.

## Verify before implementing

This repository integrates with actively developed external systems: Razorpay's MCP server and two third-party inference providers. **Your training data is likely stale on all of them**, and free-tier limits and model catalogues change monthly. The 41-tool manifest has drifted three times; assumed API shape has caused every significant bug in this repository.

Before building anything that touches Razorpay:

1. Read the live-captured manifest (`make check-schemas` offline; `make check-schemas-live` against the real server).
2. Confirm the specific tool's schema against a running server — especially whether tool calling actually works on a given free-tier model, provider tool-call formats, and the upstream tool inventory.
3. Record findings in `DECISIONS.md` with the date and the source.

**Never infer an API shape from a spec document, including the specs in this repository.** They describe intent, not signatures. If a spec conflicts with live documentation or live behaviour, live wins and the conflict goes in `DECISIONS.md`. If you cannot verify something, say so in a code comment and in `DECISIONS.md`. Do not guess and proceed silently.

## Working style

**Types before behaviour.** Define the contract, then implement against it.

**Tests alongside, not after.** Every safety-critical behaviour must be provable in a pure unit test. If a safety property can only be tested by calling a model, push the property down into a pure component instead.

**One phase at a time.** Follow `docs/spec/buildathon/10-BUILD-ORDER.md`. One phase per session. Do not begin a phase until the previous phase's exit criteria are met and checked off. The order exists to close the purchase loop early (Phase 3), then make it correct, safe, measured, and beautiful.

**Record decisions as you make them.** Append to `DECISIONS.md` at the time, with the trade-off named. Reconstructed decision logs read like fiction because they are.

**Prefer boring.** Small closed rule sets over expressive DSLs. Explicit enums over free strings. Deterministic over clever. Every piece of flexibility is an attack surface and an untested path.

## Things that are easy to get wrong

Inherited from SENTINEL:

- **Moving a check from the proxy into the agent loop.** The loop shares a process with attacker-influenced content. The proxy is the boundary. Never relocate enforcement into the loop for performance.
- **An incomplete cassette key.** If the key omits the policy version or fixture version, replays go stale and tests pass against answers to questions you are no longer asking.
- **Repairing a malformed tool call.** Free-tier models emit them regularly. Reject, retry once with a correction, then fail. Never guess the intended arguments of a money-moving call.
- **A fixed quarantine delimiter.** Trivially defeated by anyone who reads the source. Per-run nonce, always.
- **Floats for money.** Integer minor units throughout. A float in a money path is a bug even if it currently rounds correctly.
- **Audit chain writes under concurrency.** Sequence numbers must be gapless. Test this specifically.
- **Approval reuse.** Single-use, argument-bound, expiring, and re-validated on resume.
- **Pagination.** An agent that silently reads page one and reports success is a correctness bug that looks like a working feature.
- **Averaging away eval variance.** Variance is a finding, not noise.

Specific to this build:

- **Trusting the agent's total.** The single most dangerous shortcut available. Re-price always.
- **Drawing down after the write.** A successful `create_order` with a lost response leaves the mandate silently over-drawn.
- **Retrying a timeout.** Reconcile via `fetch_order_payments` first. Never blind-retry a payment.
- **Demonstrating a failure via cancellation.** In Razorpay test mode, *cancelling* a UPI payment produces a **successful** payment (documented). A decline demo built on cancellation silently shows a success — discovered while recording the video. Use the `failure@razorpay` test VPA, never cancellation (ADR-028).
- **Asserting "the surface has no X" from tool names.** The mandate primitive lived in `create_order`'s *argument schema*, not in any tool name. The surface is the tool list plus every schema in it; grep the schema JSON before claiming absence (ADR-028 addendum).
- **Upselling past the mandate.** Suppress the offer before the model sees it; do not reject after acceptance.
- **Reporting SENTINEL's eval numbers.** The commerce suite is separate with its own count. The number in the README must describe what the README is about.
- **Building the security demo before the purchase works.** Phase order exists for a reason.

## Definition of done for any unit of work

- [ ] Implements the spec, or the divergence is recorded in `DECISIONS.md`
- [ ] Unit tests including boundary and failure cases
- [ ] Fails closed on every error path, with a test proving it
- [ ] No agent-supplied amount accepted anywhere
- [ ] Produces no PII on any output surface
- [ ] Reason codes enumerated; explanations render in plain language
- [ ] `DECISIONS.md` updated where a real choice was made, with the trade-off named
- [ ] The relevant acceptance criteria in the spec are checked off

## Commands

`make help` lists everything. The load-bearing ones:

- `make demo` — start everything in fixture mode, no keys required
- `make test` — tiers 1–3, fast, deterministic, no model
- `make critical` — only the load-bearing safety tests
- `make eval` — golden set in replay mode with regression gates
- `make redteam` — paired A/B suite, fixture mode
- `make verify-audit` — walk and verify the hash chain
- `make check-schemas` — fixture-vs-reference schema parity (offline)
- `make check-schemas-live` — verify against the real razorpay/mcp (Docker + `rzp_test_` keys)
- `make purity` — assert the policy engine performs no I/O
- `make secret-scan` — fail if anything resembling a live key is present

New commerce targets are added to the Makefile as they are built.

## When you are unsure

Ask, or record the uncertainty explicitly. **Choose the more restrictive behaviour and flag it.** In a system that binds real amounts under someone else's consent, a wrong assumption implemented silently is much worse than a question asked.
