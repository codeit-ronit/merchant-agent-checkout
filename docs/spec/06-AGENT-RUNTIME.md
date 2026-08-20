# 06 — Agent Runtime, Provider Layer, and the In-Loop Guard

## 1. What is currently true

The agent loop is a small, well-understood pattern: send messages and a tool manifest to a model, receive either text or tool calls, execute the tools, append results, repeat until the model stops calling tools or a ceiling is hit.

Frameworks package this with session management, retries, and context handling. They also bring version churn, opinionated interception points, and — critically for us — a coupling to one vendor.

Most inference providers now expose an OpenAI-compatible chat-completions interface with tool calling, which means one adapter shape covers several providers with only small per-provider differences.

## 2. What we are solving

**Run an agent such that every tool call passes through two independent enforcement layers, the model behind it can be swapped without touching enforcement, and the whole thing survives free-tier rate limits.**

Three sub-problems:

| Sub-problem | Solution |
|---|---|
| Precise, owned interception point | Write the loop ourselves |
| Model and provider independence | Thin abstraction with normalised tool calling |
| Rate limits and provider churn | Governor, failover, cassettes, startup model probe |

## 3. Why write the loop rather than adopt a framework

Stated plainly, because it will be asked:

- **We need total control over the interception point.** That is the entire project. A framework's hook API is a constraint we would be working around.
- **No version churn on a security-critical path.** A framework upgrade that changes permission semantics is a silent security regression.
- **Model independence is a design goal**, and framework abstractions over providers vary in quality and lag new providers.
- **It is genuinely small.** Roughly 200 lines. The complexity in this project lives in the proxy, the policy engine, and the evals — not the loop.
- **"I wrote the loop, so I know exactly where the boundary is"** is a stronger interview answer than "the framework handles it."

The honest trade-off, and record it in `DECISIONS.md`: we give up battle-tested context management, sophisticated retry logic, and session handling that a mature framework provides for free. For a scoped project with resource ceilings and fixture-backed evaluation, that is an acceptable loss. For a production system at throughput, it would not be.

## 4. The provider abstraction

### 4.1 The interface

One method. Given messages and a tool manifest, return a normalised response containing either assistant text or tool calls, plus usage and provider attribution.

Everything provider-specific lives behind this line. **If the agent loop ever branches on which provider is active, the abstraction has leaked and must be fixed rather than worked around.**

### 4.2 Normalisation

Providers differ in ways that will bite:

- Tool-call representation and how arguments are encoded
- Whether arguments arrive as a parsed object or a string requiring parsing
- Message role vocabulary, and how tool results are represented in history
- Finish-reason values
- Usage field names, and whether usage is reported at all
- Error shapes and rate-limit signalling — status codes, headers, retry-after

Normalise all of it at the adapter. Write a conformance test suite that every adapter must pass: same input, structurally equivalent normalised output. Run it against each provider once during development and record the results.

### 4.3 Rate-limit governor

Free tiers are governed by requests-per-minute, requests-per-day, and tokens-per-minute ceilings that differ per provider and per model, and change without notice.

Requirements:
- Limits are **read from config**, never hardcoded, with the date they were verified recorded alongside.
- The governor tracks usage in a **persistent store**, so a restart does not reset the daily counter and cause a burst of rejections.
- **Block locally before the provider rejects.** Sliding-window tracking against each ceiling. A long eval run should slow down gracefully, not fail in a burst.
- Expose remaining quota so the eval runner can plan, and the UI can show it.

### 4.4 Failover

On rate limit or transient error: back off with jitter, retry a bounded number of times, then fail over to the secondary provider.

Requirements:
- The provider that actually served each call is recorded in the trace and in `RunRecord`.
- A provider switch mid-run is a visible trace event, not a silent substitution. A run that produced different behaviour after switching models is important information.
- Failover is bounded. If all providers are exhausted, the run fails cleanly with a distinct terminal state — never hangs, never silently produces a degraded result.
- **Failover interacts with idempotency.** If provider A times out after emitting a tool call and provider B re-emits it, the idempotency guard prevents duplicate execution. Test this sequence explicitly.

### 4.5 Startup model probe

Free-tier catalogues churn, and models are deleted without announcement. A project that dies silently six months from now because a model vanished is not one anyone can evaluate.

At startup, probe each configured model with a trivial call. Any configured model that is unavailable causes a **refusal to start**, with a message naming the model and the provider. Loud failure, immediately, with an actionable message.

### 4.6 Cassettes

Per `02-ARCHITECTURE.md` §4.3. Implemented inside the provider abstraction so the loop is unaware of them.

Key requirement: **the cassette key must include everything that could change the response.** An incomplete key produces stale replays that look like passing tests, which is the worst possible failure in an eval harness. Include the fixture dataset version and the policy set version, not just the prompt — a policy change alters the denial messages appended to the message history, which changes subsequent turns.

> **RESEARCH FIRST — before writing any provider code:**
> 1. For each candidate provider: current free-tier RPM / RPD / TPM, whether a credit card is required, and whether signup is instant.
> 2. **Whether tool calling works on the free-tier models**, verified with a real call — not from documentation alone. This is the hard requirement. A provider with generous limits and unreliable tool calling is worthless here.
> 3. The exact tool-call request and response format for each.
> 4. Usage reporting: field names, and whether cost is derivable.
> 5. Rate-limit signalling: status codes, headers, whether a retry-after is provided.
> 6. Data-handling terms for free-tier usage.
> 7. Whether an existing abstraction library is worth the dependency versus direct adapters.
>
> Record all findings with the date checked in `DECISIONS.md`. These values will be stale within months; the config file and the ADR are what make that survivable.

## 5. The agent loop

### 5.1 Structure

Deliberately simple. In outline:

- Build initial messages: system prompt, operator task, any quarantined attachments
- Loop until a terminal condition:
  - Call the provider with messages and the tool manifest
  - If the response is text with no tool calls → run complete
  - For each tool call: build `DecisionContext`, run the **in-loop guard**, then either execute via the proxy or append a structured denial
  - Append results to the message history
  - Check resource ceilings
- Validate structured output against the agent's declared schema
- Emit terminal trace event and persist `RunRecord`

### 5.2 The in-loop guard (layer 2)

Before any tool call reaches the proxy, the loop builds a `DecisionContext` and evaluates it against the same Policy Engine with the same policy set.

Why duplicate what the proxy will do anyway:
- **Better denials.** A structured, reasoned denial appended to the message history, which the model can read and adapt to — rather than an opaque transport error.
- **Richer context.** The model's stated reasoning text, the step number, and accumulated run state are available here and not at the protocol layer. The model's stated intent is a useful policy input.
- **Cheaper.** Saves a round trip to the proxy and upstream.

**The layers must never disagree.** Same engine, same context builder, same policy set. If they produce different dispositions for the same call, log a `LAYER_DISAGREEMENT` incident, take the more restrictive outcome, and treat it as a P0 bug. Add a test that runs a corpus of calls through both paths and asserts identical decisions.

**The in-loop guard is not the guarantee.** It is a convenience and an optimisation. The proxy is the boundary. Never move a check from the proxy into the loop for performance reasons — that would move enforcement into the layer an attacker's payload shares a process with.

### 5.3 Handling malformed tool calls

Free-tier open-weights models produce malformed tool calls more often than frontier models. This is a real operational issue, not an edge case.

Behaviour:
- Validate the tool call against the declared schema at the abstraction boundary, before the guard and before the proxy.
- Malformed → append a corrective message describing what was wrong, retry once.
- Still malformed → fail the run cleanly with a distinct terminal state.
- **Never guess the intended arguments.** Repairing a malformed money-moving call is exactly the kind of helpfulness that causes incidents.
- Count malformed tool calls as a **reported eval metric**, per model. It is a legitimate quality signal and a fair basis for comparing models.

### 5.4 Agent definition

Each agent is a declarative bundle, not a script:

- identifier and version
- system prompt (documentation of intent — **never the security boundary**)
- declared tool scope: which tools it may request at all
- structured output schema
- default policy set
- resource ceilings: max steps, max wall-clock, max cost, max tool calls

**Version the system prompt and record its hash in `RunRecord`.** Prompt changes are the most common cause of behaviour changes, and without version tracking your eval dashboard cannot attribute a regression to its cause.

Declared tool scope is a *narrowing* of what policy permits, never a widening. An agent declaring a tool that policy forbids is a configuration error and must fail at startup, not at call time.

### 5.5 Structured output

Every agent produces output conforming to a declared schema, so the eval harness can assert without brittle string matching.

Enforce at the boundary: validate, and treat a schema violation as a run failure rather than papering over it. Provider-native structured-output support varies and cannot be relied on across providers, so **validate ourselves regardless** of whether a given provider offers it. One retry with a corrective message is acceptable; a second failure fails the run.

Track schema-conformance rate per model as an eval metric.

### 5.6 Suspension and resumption

When policy escalates, the run must block — potentially for a long time.

Requirements:
- Persist enough state to resume after a process restart. A run suspended at 5pm should be resumable at 9am. Since we own the loop, this is straightforward: the message history plus run state is the entire session.
- Approval expiry terminates the run cleanly with `ABORTED_APPROVAL_EXPIRED`.
- Resumption re-validates: the approval must still be valid, unexpired, unconsumed, and bound to an argument hash that still matches. **Re-run the policy check on resume.** Do not trust the decision made before suspension — the world may have changed.
- The UI shows suspended runs prominently. A run silently waiting forever is a bad product.

Owning the loop is a real advantage here. Framework session-suspension semantics vary and are often the hardest thing to work around; for us, persistence is just serialising our own state.

### 5.7 Trace emission

One event stream, consumed by both the UI (via SSE) and the eval harness. Do not build two paths — divergence between what you watch and what you measure is how you end up debugging the wrong thing.

Requirements: gapless sequence numbers, pre-redacted payloads, persisted for replay, streamable live, and **provider and model attribution on every model-call event**.

### 5.8 Resource ceilings

Enforced by the runtime, independent of policy:

- Max steps per run — prevents infinite loops
- Max wall-clock — excluding time suspended awaiting approval
- Max cost per run — hard stop where cost is derivable
- Max tool calls per run
- Max provider retries and failovers per run

Breaching a ceiling terminates the run with a distinct terminal state. These are not policy rules; they are runtime invariants that hold even under a misconfigured policy.

## 6. Multi-model comparison as a deliverable

Because the runtime is model-agnostic, running the full suite against both configured models is nearly free once cassettes exist. Do it, and report it.

The headline finding to look for and state plainly:

> Task accuracy varied between models. **The enforcement result did not.** Zero unauthorised executions on both, under identical policy.

That single sentence is the strongest available evidence for the project's central claim, and it is only available because model independence was designed in rather than bolted on. Put it in the README.

Expect the weaker model to score lower on accuracy and higher on malformed tool calls. **Report that honestly** — it is a real, interesting finding about the difference between capability and safety, and it demonstrates that your evaluation is measuring something rather than confirming something.

## 7. Acceptance criteria

- [ ] Provider abstraction exposes one interface; the loop contains no provider-specific branching.
- [ ] Adapter conformance suite passes for both providers.
- [ ] Rate-limit governor blocks locally before provider rejection; counters survive restart.
- [ ] Failover on rate limit and on error, with provider attribution recorded in the trace.
- [ ] Failover-plus-retry does not cause duplicate execution — tested explicitly.
- [ ] Startup model probe refuses to start on an unavailable model, naming it.
- [ ] Cassette key includes prompt, history, manifest, model, provider, policy version, and fixture version.
- [ ] Cassette miss in replay mode is a hard failure.
- [ ] Agent loop completes a real task end to end against fixtures.
- [ ] In-loop guard denies with a structured, model-readable reason.
- [ ] Layer-agreement test: a corpus of calls yields identical decisions from both layers.
- [ ] Malformed tool calls are rejected, retried once, then fail cleanly — never repaired by guessing.
- [ ] Structured output validated at the boundary; violations fail the run.
- [ ] A run suspends on escalation, survives process restart, and resumes correctly.
- [ ] Policy re-evaluated on resume; a changed world blocks resumption, with a test.
- [ ] Every resource ceiling has a test that trips it.
- [ ] Trace sequence numbers gapless under load.
- [ ] Full suite runs against both models; enforcement results identical.
