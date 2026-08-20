# 14 — Decision Log (ADR)

This file becomes `DECISIONS.md` in the repository root. **Append to it during the build, not afterwards.** A decision recorded at the time is accurate; a decision reconstructed at the end is fiction, and reads like it.

The JD asks explicitly for documentation of architecture, technical decisions, trade-offs, and limitations. This file is that deliverable.

## Entry format

```
## ADR-NNN — <Short title>
Date: YYYY-MM-DD    Phase: N    Status: Proposed | Accepted | Superseded by ADR-MMM

### Context
What was true that forced a decision. What constraints applied.

### Options considered
At least two, with the genuine case for each. An ADR listing one option is not a decision, it is a description.

### Decision
What was chosen.

### Rationale
Why this one. What it optimises for.

### Trade-off accepted
What is now worse because of this choice. Every real decision has one. If you cannot name it, you have not made a decision.

### Revisit if
The condition under which this should be reconsidered.
```

That "trade-off accepted" field is the one that matters. An ADR without a named cost is marketing.

## Seeded entries — record these as they are resolved

These are the decisions the build will force. Fill each one in when you reach it. Do not pre-fill them from this spec — the point is to record what you actually found.

**ADR-001 — Enforcement placement.** Prompt versus SDK callback versus MCP proxy. Why both layers rather than one. What the duplication costs.

**ADR-002 — In-house agent loop rather than a framework.** Why we own the loop. What we give up: battle-tested context management, retry logic, session handling.

**ADR-002a — Provider selection.** The two providers chosen, their verified free-tier limits and the date checked, whether tool calling was confirmed by a real call, usage reporting, and data-handling terms.

**ADR-002b — Cassette key composition.** Exactly what the key hashes and why each element is necessary. What a stale replay would look like and how it is prevented.

**ADR-003 — Tool risk classification.** How each upstream tool was classified. Rationale for every money-movement classification. How unknowns are handled.

**ADR-004 — Policy language scope.** Why a closed set of rule types rather than an expression language. What this cannot express.

**ADR-005 — Policy engine purity.** Why no I/O, and what the injected-context design costs in caller complexity.

**ADR-006 — Monetary representation.** Integer minor units. How this maps to the upstream representation. Why never floats.

**ADR-007 — PII detection strategy.** Structural versus pattern. The Indian identifier format research, with sources. The checksum-invalid generation decision.

**ADR-008 — Tokenisation scheme.** Stability within run, instability across runs, derivation method, and why not a counter.

**ADR-009 — Quarantine delimiter.** Per-run nonce and why a fixed delimiter is inadequate. Honest statement of what this does and does not achieve.

**ADR-010 — Hash function and canonical serialisation.** The choice, the alternatives, and why this is tamper-evident rather than tamper-proof.

**ADR-011 — Idempotency.** Key derivation and canonicalisation. Whether upstream native idempotency exists and whether it was used.

**ADR-012 — Approval binding.** Single-use, argument-bound, expiring. Why re-evaluation on resume is necessary.

**ADR-013 — Persistence.** SQLite now, Postgres-ready. Where the repository boundary sits. What breaks at scale.

**ADR-014 — Fixture fidelity.** How parity is maintained and what the schema-drift check catches and misses.

**ADR-015 — Structured output.** Native SDK mechanism versus boundary enforcement. Which, and why.

**ADR-016 — Eval non-determinism.** N-runs, variance reporting, model pinning. Why variance is reported rather than averaged away.

**ADR-017 — Regression gate thresholds.** Initial values and their justification. The rule that lowering a threshold requires a reasoned commit.

**ADR-018 — Red-team grading.** Rule-based rather than model-graded, and why a model-graded safety suite cannot be trusted.

**ADR-019 — PDF extraction library.** The comparison performed, against real fixture statements, and the result.

**ADR-020 — RAG chunking strategy.** The comparison, the retrieval eval used to decide, and the result.

**ADR-020a — Multi-model comparison findings.** Accuracy delta between models, malformed tool-call rates, and confirmation that the enforcement result was identical. Record it even if one model performed noticeably worse.

**ADR-021 — Ablation findings.** Which control contributed most. **Record this even if — especially if — it contradicts the design intuition.**

**ADR-022 — Scope cuts.** Everything deliberately not built, with a one-line reason each. Mirrors `LIMITATIONS.md`.

## A note on honesty

Some of these entries will record that something did not work as expected, or that a measurement contradicted the design assumption behind it. **Record those especially.**

The single most credible document a junior engineer can produce is a decision log containing an entry that says "I expected X, measured Y, and changed the design." It demonstrates that the measurements are real, that the author reads their own results, and that the conclusions were not written before the work.

An ADR log with no surprises in it is a log nobody actually kept.
