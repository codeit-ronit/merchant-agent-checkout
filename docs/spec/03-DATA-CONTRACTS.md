# 03 — Data Contracts

## Why this document exists first

Every component in SENTINEL is separated from every other by a typed boundary. Defining those boundaries before writing behaviour is what makes the components independently testable and independently replaceable. Build these types in Phase 0, before anything that uses them.

**Rules for all contracts:**

1. **Typed and validated at construction.** Use Pydantic models. A malformed object should be impossible to create, not caught later.
2. **Immutable once created.** Decisions, audit entries, and traces are facts. Facts do not get edited.
3. **Versioned.** Every persisted structure carries a `schema_version`. When it changes, old records still parse or explicitly fail — never silently misparse.
4. **Redaction-aware.** Any type that can hold PII declares which fields may, and has a serialiser that produces a safe representation. Logging an object must never leak.
5. **Reason codes are an enum, never a free string.** Free-text reasons cannot be aggregated, tested, or counted. Every deny in the system maps to one enumerated code.

## 1. Core identifiers

Define a small set of ID types rather than passing bare strings. A `RunId` and a `StepId` should not be interchangeable at the type level.

- `RunId` — one agent execution, start to terminal state
- `StepId` — one iteration of the agent loop within a run
- `CallId` — one tool invocation
- `ApprovalId` — one escalation
- `PolicySetId` + version — which policy governed this decision
- `ScenarioId` — one eval or red-team case

All IDs sortable by creation time. Prefer a time-ordered identifier scheme so that sorting a log sorts it chronologically without a separate timestamp index.

## 2. `DecisionContext`

The complete input to a policy evaluation. **This is the most important type in the system.**

Because the Policy Engine is pure, everything it could possibly need must be here. If you find yourself wanting to read a clock or query a database inside the engine, the missing value belongs in this type instead.

Contents:

**Identity and provenance**
- run id, step id, call id
- agent identifier and version
- operator identifier
- policy set id and version being applied

**The call itself**
- tool name as presented to the model
- upstream tool name (may differ after namespacing)
- resolved risk class
- raw arguments, redacted arguments, canonical argument hash
- idempotency key

**Injected environment** — supplied by the caller, never read by the engine
- current timestamp
- accumulated spend this run / today / this policy window
- tool call count this run, and per-tool counts
- elapsed run duration
- whether a valid, unexpired, argument-bound approval exists for this exact call

**Signals**
- provenance levels present in the context that produced this call
- whether any quarantined content was in the model's context at the time
- whether the model's stated intent (captured from its reasoning text) is available
- injection-suspicion score, if the detector ran

**Money semantics**
- extracted amount and currency, when the tool has money semantics
- target entity identifiers (payment, refund, settlement, contact, fund account)
- whether the target entity is within the operator's declared scope

That last field deserves emphasis. A large class of real agent failures is not "did something forbidden" but "did the right thing to the wrong entity." Scope must be a first-class policy input.

## 3. `PolicyDecision`

The engine's output. Immutable.

- `disposition` — one of `ALLOW`, `DENY`, `REQUIRE_APPROVAL`
- `reason_code` — enum, required, always
- `human_reason` — one plain sentence, written for an operations person, not an engineer
- `matched_rules` — every rule that fired, in evaluation order, not just the deciding one
- `deciding_rule` — the one that determined the disposition
- `obligations` — things the caller must do if allowed (e.g. `AUDIT_ELEVATED`, `NOTIFY_OPERATOR`, `REDACT_RESULT_FULLY`)
- `evaluation_duration_ms`
- `policy_set_version`

**Design note on `matched_rules`.** Recording every rule that fired, not just the decisive one, is what makes the policy editor's dry-run simulator useful and what lets you debug "why didn't my rule fire?" — which is the question people actually have.

### Reason code taxonomy

Group by prefix so they aggregate cleanly in the dashboard:

- `ALLOW_*` — allowed by explicit rule, allowed as read-only, allowed with prior approval
- `DENY_UNKNOWN_TOOL`, `DENY_FORBIDDEN_TOOL`, `DENY_SCHEMA_INVALID`, `DENY_OUT_OF_SCOPE`, `DENY_AMOUNT_EXCEEDS_CAP`, `DENY_RATE_LIMIT`, `DENY_OUTSIDE_TIME_WINDOW`, `DENY_SUSPECTED_EXFILTRATION`, `DENY_POLICY_EVALUATION_ERROR`, `DENY_FAIL_CLOSED`
- `ESCALATE_MONEY_MOVEMENT`, `ESCALATE_IRREVERSIBLE`, `ESCALATE_AMOUNT_THRESHOLD`, `ESCALATE_INJECTION_SUSPECTED`, `ESCALATE_NOVEL_COUNTERPARTY`

Do not treat this list as final — it is a starting taxonomy. Add codes as real cases appear, but never add a code without also adding a test that produces it.

## 4. `ToolDescriptor`

The reconciled view of one tool.

- name, upstream name, description
- input schema as declared by upstream
- risk class and the config source that assigned it
- classification status: `CLASSIFIED` / `UNCLASSIFIED` / `STALE`
- money semantics: does it move money, where in the arguments is the amount, where is the currency, which arguments are entity references
- provenance map: for each output field, its trust level
- PII map: which output fields may contain which PII types

The provenance and PII maps are what let the proxy do field-level quarantine and redaction automatically instead of blanket-treating whole responses. Deriving them requires actually reading each tool's response shape — this is manual, unglamorous work and it is where the quality of the system comes from.

## 5. `TraceEvent`

The streaming unit. One event per meaningful thing that happens in a run. Both the UI and the eval harness consume the same stream — do not build two.

Event types at minimum: run started, step started, model reasoning emitted, tool call requested, policy decision made, approval requested, approval resolved, tool call forwarded, tool result received, result redacted, quarantine applied, idempotent replay, run completed, run failed, run aborted.

Every event carries: type, ids, timestamp, sequence number within the run, and a type-specific payload. Sequence numbers must be gapless so a consumer can detect dropped events.

**All trace payloads are pre-redacted.** The trace is displayed in a browser and written to disk. It must never be the leak.

## 6. `AuditEntry`

One immutable ledger record. Superset of the trace event, plus:

- `previous_hash` — hash of the preceding entry
- `entry_hash` — hash over this entry's canonical serialisation including `previous_hash`
- `sequence` — monotonic, gapless, ledger-wide

Canonical serialisation must be exactly specified and stable: field ordering, number formatting, string encoding, null handling. If serialisation is ambiguous, verification is meaningless.

> **RESEARCH FIRST:** Choose the hash function and canonical serialisation format deliberately. Consider an existing canonical-JSON specification rather than inventing one. Record the choice and its rationale in `DECISIONS.md`, including why this is tamper-*evident* and not tamper-*proof*.

## 7. `ApprovalRequest`

- id, run id, call id
- the `DecisionContext` snapshot at escalation time
- the `PolicyDecision` that escalated it
- `argument_hash` — the binding. Approval authorises exactly these arguments.
- plain-language summary — one sentence an operations person can act on without reading JSON. This is a product requirement, not a nicety.
- created at, expires at
- status: `PENDING` / `APPROVED` / `REJECTED` / `EXPIRED`
- resolver identity, resolution timestamp, optional note

**Invariants to enforce in code and test:**
- Single use. A consumed approval cannot authorise a second call.
- Argument-bound. Any change to arguments invalidates it.
- Expiry is absolute and not extendable.
- Rejection is terminal for that call.

## 8. `RunRecord`

- id, agent, agent version, operator, policy set version
- mode: `FIXTURE` or `LIVE`
- input task and any uploaded artefacts (references, not contents)
- terminal state: `COMPLETED` / `FAILED` / `ABORTED_BY_POLICY` / `ABORTED_APPROVAL_EXPIRED` / `TIMEOUT`
- structured output, conforming to the agent's declared output schema
- aggregates: step count, tool call count, denials by reason code, approvals requested/granted/rejected
- meter: input tokens, output tokens, cache reads, total cost, wall-clock ms, policy-evaluation ms
- git commit sha of the code that produced it

That last field is what makes the eval dashboard's "across commits" view possible. Add it on day one; retrofitting it is painful.

## 9. `Scenario` (eval and red-team)

A scenario is a fully specified, reproducible case.

- id, suite, tags
- fixture dataset reference — the exact upstream state
- agent under test and its configuration
- policy set to apply
- operator task prompt
- injected content, if any, and where it is injected (which field of which record)
- assertions

**Assertion types** — keep this list small and composable:

- `output_matches` — structured output satisfies a predicate
- `tool_called` / `tool_not_called` — a specific tool was or was not invoked
- `no_unauthorized_execution` — **the critical one.** No `MONEY_MOVEMENT` or `IRREVERSIBLE_WRITE` tool executed without a valid approval. Non-negotiable, asserted on every scenario in every suite.
- `denial_reason_includes` — a specific reason code appeared
- `approval_requested` — an escalation happened
- `within_budget` — cost and latency under scenario-specific ceilings

Every scenario asserts `no_unauthorized_execution`, including scenarios that are nominally about accuracy. Safety assertions are not opt-in.

## 10. `EvalResult` and `RedTeamResult`

Per scenario: pass/fail per assertion, the full trace, the run record, and a diff against the previous recorded result for the same scenario.

Per suite: pass rate, per-assertion-type breakdown, aggregate cost, p50/p95/p99 latency, **attempted policy violations**, and **successful unauthorised executions (must be 0)**.

Red-team adds:
- `attack_success_rate` split by outcome severity — unauthorised action taken, information disclosed, agent behaviour altered without action, no effect
- paired results: same payload with guardrails disabled versus enabled

The paired result is the demo. Build the data structure to hold the pair from the start rather than reconstructing it at report time.

## 11. Contract testing

For every contract above:
- Round-trip serialisation test.
- Schema-version compatibility test: a record written under version N still reads under version N+1, or fails loudly.
- Redaction test: serialise an instance populated with synthetic PII, assert no PII pattern appears in the output.

That third test should run against every type that can carry PII, as a parametrised test. It is the cheapest possible insurance against the most embarrassing possible bug.
