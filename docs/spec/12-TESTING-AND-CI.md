# 12 — Testing and CI

## What is currently true

Test suites for agent systems typically consist of a handful of integration tests that call a model and assert something vague about the output. They are slow, flaky, expensive, and prove very little.

## What we are solving

**A test suite where the safety-critical parts are fast, deterministic, and exhaustive, and where the model-dependent parts are quarantined into a separate tier that does not gate every commit.**

## The test tiers

### Tier 1 — Pure unit tests (no model, no network, no I/O)

The majority of the suite. Must run in seconds.

Covers:
- Policy engine: every rule type, every boundary condition
- Redaction detectors and tokenisation
- Canonical serialisation and hash chaining
- Idempotency key derivation
- Argument canonicalisation
- Tool classification and reconciliation
- Contract round-tripping

**Every safety-critical behaviour must be provable at this tier.** If a safety property can only be tested by calling a model, the design is wrong and the property should be pushed down into a pure component.

### Tier 2 — Property-based tests

Per `04` §3.6. Generated contexts and policy sets. These will find bugs the example-based tests miss, particularly around rule interaction.

Run on every commit. Record and commit any failing seed as a permanent regression case.

### Tier 3 — Integration tests (fixture server, no model)

Full pipeline with a scripted agent that emits predetermined tool calls rather than a real model. This tests the proxy, policy, redaction, audit, and idempotency working together, deterministically and for free.

**This tier is underused in the industry and it is where most real integration bugs live.** A scripted agent lets you test the exact call sequences that are hard to elicit from a real model — the retry loop, the unissued-token emission, the concurrent mutation.

### Tier 4 — Agent tests (fixture server, real model)

Slow, costly, non-deterministic. The eval harness lives here.

- Not run on every commit. Run on merge to main, on a schedule, and on demand.
- Results cached by content hash so re-running a report does not re-run the model.
- Model version pinned explicitly.

### Tier 5 — Live smoke tests (real upstream, test keys)

A minimal set confirming the real MCP server still behaves as expected: schema parity, a read call, a policy denial.

Run on a schedule, not on commit. Failure here means the world changed underneath us, which is information, not a broken build.

## The tests that matter most

Five tests carry disproportionate weight. If everything else were deleted, these would still make the project credible.

| Test | What it prevents |
|---|---|
| **PII invariant across all output surfaces** | The most embarrassing possible failure. Runs on every commit. |
| **No policy file can auto-allow money movement** | Proves safety is a system property, not a config default. |
| **Fail-closed on exception** | Proves errors deny rather than allow. |
| **Layer agreement** | Proves the two enforcement layers cannot silently diverge. |
| **Audit chain break detection at exact position** | Proves the ledger claim is real. |

Mark them explicitly in the codebase. Anyone reading the test suite should be able to find them immediately.

## CI pipeline

**On every push:**
1. Lint, type check, format check
2. Policy package purity check — zero I/O imports
3. Secret scan
4. Tiers 1, 2, 3
5. Frontend build and type check

**On merge to main, additionally:**
6. Tier 4 eval suite with regression gates
7. Red-team suite with the L3/L4 hard gate
8. Fixture-versus-upstream schema parity check
9. Publish eval and red-team artefacts

**Scheduled:**
10. Tier 5 live smoke tests
11. Schema parity against upstream — catches upstream changes early

## Gate policy

- Any Tier 1–3 failure blocks.
- Any hard-zero metric non-zero blocks.
- Any L3 or L4 red-team success under guardrails-on blocks.
- Relative regressions block, and require either a fix or an explicit, reasoned threshold change in a reviewable commit.
- **Lowering a threshold is a visible act.** Never a quiet edit.

## Secret handling

- Test-mode keys only, ever. Injected via environment, never committed.
- Secret scanning in CI and as a pre-commit hook.
- If a key is ever committed, rotate it and rewrite history. Both.
- CI itself uses test keys only, and only in the scheduled live smoke job.

## Coverage

Coverage as a diagnostic, not a target. A gate on total coverage percentage produces tests written to satisfy the gate.

Instead, require: every reason code is produced by at least one test, every rule type has boundary tests, every failure mode in `02` §7 has a test, and every acceptance criterion across the spec pack maps to a test.

That last requirement is the real coverage metric. Maintain the mapping explicitly.
