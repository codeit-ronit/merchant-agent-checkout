# CLAUDE.md — SENTINEL

Operating instructions for any coding agent working in this repository. Read fully before the first edit of any session.

## What this project is

SENTINEL is a policy enforcement, audit, and evaluation control plane for LLM agents that operate on payment infrastructure. Full context in `docs/spec/01-CONTEXT-AND-PROBLEM.md`. Architecture in `docs/spec/02-ARCHITECTURE.md` — that document is authoritative and overrides any conflicting instruction elsewhere.

The central claim: **prompt-level guardrails are advisory; enforcement at the tool-call boundary is a property of the system.** Every design decision serves that claim.

## Hard rules — violating any of these is a build failure

1. **Test mode only.** `rzp_test_*` keys. Never live keys. Never real data. No credential ever committed.
2. **Fail closed, everywhere.** Unknown tool, unparseable argument, missing policy, evaluation exception, upstream error → `DENY`. Never allow on exception. Never allow by default.
3. **No hardcoded tool lists.** Tools are discovered at runtime via `tools/list` and reconciled against config. An unclassified tool is denied.
4. **No PII in any output surface.** Not in prompts, traces, audit entries, logs, API responses, or files. The PII invariant test is the highest-priority test in the repo.
5. **The policy engine performs no I/O.** No clock, no network, no database, no randomness. Enforced by a CI import check.
5a. **The agent loop contains no provider-specific branching.** If it does, the provider abstraction has leaked and must be fixed, not worked around.
6. **Every denial carries an enumerated reason code and a plain-language explanation.** A block without a reason is a bug.
7. **Red-team code runs in fixture mode only.** Never against a hosted endpoint. Enforced in code and tested.
8. **No affiliation claims.** Independent project integrating with publicly published open-source software.

## Research before implementing

This repository integrates with actively developed external systems: Razorpay's MCP server and two third-party inference providers. **Your training data is likely stale on all of them.** Free-tier limits and model catalogues in particular change monthly.

Before implementing any component that touches either:

1. Read the current official documentation.
2. Verify empirically where behaviour matters — especially whether tool calling actually works on a given free-tier model, provider tool-call formats, and the upstream tool inventory.
3. Record what you found in `DECISIONS.md`, including the date and the source.

**Never infer an API surface from a spec document, including the spec documents in this repository.** They describe intent, not signatures. If a spec conflicts with live documentation, live documentation wins and the conflict goes in `DECISIONS.md`.

If you cannot verify something, say so in the code as a comment and in `DECISIONS.md`. Do not guess and proceed silently.

## Working style

**Types before behaviour.** Define the contract, then implement against it.

**Tests alongside, not after.** Every safety-critical behaviour must be provable in a pure unit test. If a safety property can only be tested by calling a model, push the property down into a pure component instead.

**One phase at a time.** Follow `docs/spec/11-BUILD-ORDER.md`. Do not begin a phase until the previous phase's exit criteria are met and checked off. The build order front-loads the control plane deliberately.

**Record decisions as you make them.** Append to `DECISIONS.md` at the time, with the trade-off named. Reconstructed decision logs read like fiction because they are.

**Prefer boring.** Small closed rule sets over expressive DSLs. Explicit enums over free strings. Deterministic over clever. Every piece of flexibility is an attack surface and an untested path.

## Things that are easy to get wrong

- **Moving a check from the proxy into the agent loop.** The loop shares a process with attacker-influenced content. The proxy is the boundary. Never relocate enforcement into the loop for performance.
- **An incomplete cassette key.** If the key omits the policy version or fixture version, replays go stale and tests pass against answers to questions you are no longer asking. This is the worst failure mode in the whole harness.
- **Repairing a malformed tool call.** Free-tier models emit them regularly. Reject, retry once with a correction, then fail. Never guess the intended arguments of a money-moving call.
- **A fixed quarantine delimiter.** Trivially defeated by anyone who reads the source. Per-run nonce, always.
- **Floats for money.** Integer minor units throughout. No exceptions.
- **Audit chain writes under concurrency.** Sequence numbers must be gapless. Test this specifically.
- **Approval reuse.** Single-use, argument-bound, expiring, and re-validated on resume.
- **Pagination.** An agent that silently reads page one and reports success is a correctness bug that looks like a working feature.
- **Averaging away eval variance.** Variance is a finding, not noise.

## Definition of done for any unit of work

- [ ] Implements the spec, or the divergence is recorded in `DECISIONS.md`
- [ ] Unit tests including boundary and failure cases
- [ ] Fails closed on every error path, with a test proving it
- [ ] Produces no PII on any output surface
- [ ] Reason codes enumerated, explanations render
- [ ] `DECISIONS.md` updated if a real choice was made
- [ ] The relevant acceptance criteria in the spec are checked off

## Commands

Defined in the Makefile as they are built:

- `make demo` — start everything in fixture mode
- `make test` — tiers 1–3, fast, no model
- `make eval` — golden set with regression gates
- `make redteam` — paired A/B suite
- `make verify-audit` — walk and verify the hash chain
- `make check-schemas` — fixture versus live upstream parity

## When you are unsure

Ask, or record the uncertainty explicitly. In a system that enforces boundaries on money-moving actions, a wrong assumption implemented silently is much worse than a question asked. **When genuinely uncertain, choose the more restrictive behaviour and flag it.**
