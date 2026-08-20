# 02 — Architecture

> This is the most important document in the pack. Every other spec derives from it. If a later document contradicts this one, this one wins and the contradiction is a bug to be raised, not silently resolved.

## 1. The central architectural decision

**Enforcement happens at the tool-call boundary, in a process the model does not control.**

There are three places you could put a guardrail:

| Placement | Strength | Why |
|---|---|---|
| System prompt | Advisory | The model may comply. Adversarial input, context pressure, and model updates all erode it. Untestable. |
| In the agent loop, before execution | Strong | Runs in our process. The model cannot bypass it. But scoped to one agent implementation. |
| MCP proxy between agent and tool server | Strongest | Protocol-level. Enforces regardless of which agent, which framework, or which model. Survives the agent being replaced entirely. |

**SENTINEL implements the second and the third, and treats the first as documentation.**

This is the defensible engineering claim of the project, and it should be stated in exactly these terms:

> Prompt-level guardrails are requests to the model. Proxy-level guardrails are properties of the system. Only the second kind can be tested, audited, or trusted with money.

### Why both layers, not just one

The MCP proxy is the real boundary — it holds even if the agent is swapped for a different framework tomorrow. The in-loop check is the *ergonomic* boundary — it gives us structured pre-execution context (the model's stated reasoning, the step number, accumulated run state) that the raw protocol does not, and it lets us return a denial the model can read and adapt to rather than an opaque transport error.

Defence in depth, with a clear division:
- **Proxy layer** = the guarantee. Cannot be bypassed. Fails closed.
- **In-loop layer** = the experience. Better messages, cleaner escalation, richer telemetry.

If they ever disagree, the proxy wins and the disagreement is logged as a `LAYER_DISAGREEMENT` incident — because it means one of them has a bug.

## 2. Model independence is a design goal, not a workaround

**The agent runtime is model-agnostic and provider-agnostic by design.**

This is the strongest version of the project's thesis. If the claim is *"enforcement at the protocol boundary holds regardless of which agent, framework, or model"*, then demonstrating it with a single vendor's SDK is weaker evidence than demonstrating it across two providers.

Consequences that flow from this:

- The agent loop is **written in-house**, not adopted from a framework. Roughly 200 lines: send messages, receive tool calls, intercept, execute, append results, repeat. We need precise control over the interception point regardless — that is the entire project — and owning the loop removes a version-churn dependency from a security-critical path.
- A thin **provider abstraction** sits underneath, so the same agent runs against multiple inference providers.
- The eval harness reports results **per model**, and the README states that the enforcement result held across all of them.

**State this in the README** as a deliberate choice, because it is one:

> Model-agnostic by design — the enforcement boundary is the MCP protocol, not the agent framework. Demonstrated across two providers.

## 3. System diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  OPERATOR SURFACE                                                    │
│  React SPA — Run console · Approval queue · Policy editor ·          │
│  Eval dashboard · Red-team results · Audit viewer                    │
└───────────────────────────────┬──────────────────────────────────────┘
                                │  REST + SSE
┌───────────────────────────────▼──────────────────────────────────────┐
│  CONTROL PLANE API  (FastAPI)                                        │
│  /runs  /approvals  /policies  /audit  /evals  /redteam              │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│  AGENT RUNTIME  (in-house loop)                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  IN-LOOP GUARD (layer 2)                                       │  │
│  │  pre-execution check → delegates decision to Policy Engine     │  │
│  └────────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  PROVIDER ABSTRACTION                                          │  │
│  │  normalised chat + tool-calling interface · failover ·         │  │
│  │  rate-limit governor · CASSETTE record/replay                  │  │
│  │      ├── Provider A (primary)                                  │  │
│  │      └── Provider B (fallback / second model for comparison)   │  │
│  └────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────┬──────────────────────────────────────┘
                                │  MCP protocol
┌───────────────────────────────▼──────────────────────────────────────┐
│  SENTINEL MCP PROXY  (layer 1 — THE GUARANTEE)                       │
│                                                                      │
│   inbound: tools/list   → filter + annotate tool manifest            │
│   inbound: tools/call   → ① classify  ② redact  ③ evaluate policy    │
│                           ④ ALLOW / DENY / ESCALATE                  │
│                           ⑤ idempotency  ⑥ forward or block          │
│   outbound: tool result → ⑦ scan  ⑧ quarantine untrusted text        │
│                           ⑨ redact  ⑩ audit                          │
└───────┬────────────────────────────────────────────┬─────────────────┘
        │                                            │
┌───────▼─────────────────┐              ┌───────────▼──────────────────┐
│  UPSTREAM (live mode)   │              │  UPSTREAM (fixture mode)     │
│  razorpay/mcp           │              │  SENTINEL fixture server     │
│  Docker, TEST KEYS ONLY │              │  Deterministic. In-process.  │
└─────────────────────────┘              └──────────────────────────────┘

        ┌──────────────── CROSS-CUTTING ────────────────┐
        │  Policy Engine · Redaction Service ·          │
        │  Audit Ledger (hash-chained) ·                │
        │  Approval Store · Cost & Latency Meter        │
        └───────────────────────────────────────────────┘

        ┌──────────────── OFFLINE ──────────────────────┐
        │  Eval Harness (golden set) · Red-Team Harness │
        │  → CI regression gates (cassette replay)      │
        └───────────────────────────────────────────────┘
```

## 4. Component responsibilities

Each component has exactly one job. If a component grows a second job, split it.

### 4.1 SENTINEL MCP Proxy

A standards-compliant MCP server that presents itself to the agent as the tool provider, and acts as an MCP client to the real upstream.

Responsibilities:
- Speak MCP on both sides. The agent must not need to know the proxy exists.
- Discover the upstream tool manifest at startup via `tools/list`.
- Filter the manifest: tools classified `FORBIDDEN` are removed entirely so they never enter the model's context.
- Annotate remaining tool descriptions with their risk class, so the model has honest information about what it is holding.
- Intercept every `tools/call`, run the decision pipeline, forward or block.
- Post-process every tool result before it returns to the model.

Explicitly NOT its job: deciding policy (that is the Policy Engine), storing audit records (that is the Ledger), or knowing anything about specific agents, models, or providers.

**Design note.** Building the proxy as a real MCP server rather than a function wrapper is what makes the framework-independence claim true. It must be demonstrable by pointing a completely different MCP client at it and watching policy still hold. That demonstration is a required deliverable, not a nice-to-have.

### 4.2 Provider Abstraction

One normalised interface over multiple inference providers.

Responsibilities:
- Expose a single method: given messages and a tool manifest, return either assistant text or tool calls, plus usage.
- **Normalise provider differences**: tool-call request and response formats, message roles, finish reasons, usage field names, error shapes.
- **Failover.** On rate limit or provider error: retry with backoff, then fail over to the secondary provider. Record which provider actually served each call — this appears in `RunRecord` and matters for eval attribution.
- **Rate-limit governor.** Track requests and tokens per provider against configured per-minute and per-day ceilings, read from config. Block locally *before* the provider rejects, so a long eval run degrades gracefully instead of erroring in a burst.
- **Cassette record/replay.** See §4.3.

Design constraint: **the agent loop must not know which provider served a call.** If any behaviour differs by provider outside this module, the abstraction has leaked.

> **RESEARCH FIRST — before writing any provider code:**
> 1. Current free-tier limits (RPM, RPD, TPM) for the two providers you select. These change monthly. Record the values and the date checked in `DECISIONS.md`, and read them from config — never hardcoded.
> 2. Whether each provider supports **tool calling / function calling** on its free-tier models, and the exact request and response format. This is the hard requirement — a provider without reliable tool calling is unusable here regardless of how generous its limits are. Verify with a real call before committing to it.
> 3. How each reports token usage, and whether cost can be derived. If a provider reports no usage, record the gap rather than inventing an estimate.
> 4. Data-handling terms — whether free-tier inputs may be used for training. **All fixture data is synthetic, so this is not a blocker**, but state it explicitly in the README. A reader will wonder, and answering unprompted shows you thought about it.
> 5. Whether an existing abstraction library covers your chosen providers well enough to justify the dependency, versus writing adapters directly. Two providers is a small surface; direct adapters may be cleaner. Decide with reasons and record it.
> 6. Model deprecation policy. Free catalogues churn. Note how each provider announces removals, if at all.

### 4.3 Cassette layer (record / replay)

**Required, not an optimisation.** Rate limits, not cost, are the binding constraint on evaluation.

Every model interaction is recorded once and replayed thereafter, keyed by a content hash of everything that could change the response:

```
hash(system prompt + message history + tool manifest + model id
     + provider + policy set version + fixture dataset version)
```

Modes:
- **Record** — call the provider, persist the full request/response pair.
- **Replay** — serve from disk. No network. Deterministic.
- **Auto** — replay on hit, record on miss. Default for development.

A cassette miss during a replay-mode CI run is a **hard failure**, never a silent fallthrough to the network. CI must not depend on a provider being up.

Two payoffs beyond rate limits:
- Tier 4 tests become deterministic and reproducible.
- **A reviewer can clone the repo and reproduce your exact eval numbers with no API key at all.** That is a far stronger property than screenshots, and it belongs in the README.

Cassettes are committed to the repository. They contain only synthetic data — but run the PII invariant check over cassette files too, as belt and braces.

### 4.4 Tool Classifier

Maps a tool name + argument shape to a risk class. Classification drives everything downstream.

**Risk classes** (ordered by severity):

| Class | Meaning | Default disposition |
|---|---|---|
| `READ` | Retrieves data. No state change. | Allow, subject to scope and rate policy |
| `REVERSIBLE_WRITE` | Changes state, undoable without financial consequence. | Allow, subject to policy; always audited |
| `IRREVERSIBLE_WRITE` | Changes state in a way that cannot be undone but does not move money. | Require approval by default |
| `MONEY_MOVEMENT` | Causes funds to move or commits to moving them. | Require approval always. Never auto-allowed. |
| `UNKNOWN` | Not present in the classification config. | **DENY.** Fail closed. |
| `FORBIDDEN` | Explicitly banned for this deployment. | Removed from the manifest entirely. |

**How classification is derived — do not hardcode this.**

At startup the proxy introspects the upstream `tools/list`, then reconciles it against `config/tool_classes.yaml`. Reconciliation produces three sets:

- **Classified** — present in both. Use the configured class.
- **Unclassified** — on the server, absent from config. Class = `UNKNOWN` → denied, surfaced loudly in the UI and startup logs as "N tools require classification."
- **Stale** — in config, absent from the server. Warn; the upstream may have removed or renamed a tool.

This matters because the upstream MCP server is actively developed. A tool added upstream next month must not silently become callable. The reconciliation report is itself a deliverable — it demonstrates the system degrades safely when the world changes underneath it.

> **RESEARCH FIRST:** Enumerate the actual current tool inventory of `razorpay/razorpay-mcp-server` by reading its repository and published documentation, and by calling `tools/list` against a locally-run instance with test keys. Classify each tool by reading what it does, not by guessing from its name. Record the classification rationale for every money-movement tool in `DECISIONS.md`. Do not copy a tool list from any spec document including this one — enumerate it live.

### 4.5 Policy Engine

A **pure function**. This is a hard architectural constraint.

```
evaluate(policy_set, decision_context) -> PolicyDecision
```

No I/O, no clock reads, no network, no randomness, no database. Everything it needs arrives in `decision_context`, including the current time and accumulated spend, injected by the caller.

Why: a pure policy engine can be exhaustively unit tested, property tested, replayed against historical traces, and reasoned about. The moment it reads a clock it becomes untestable.

Full specification in `04-POLICY-ENGINE.md`.

### 4.6 Redaction Service

Bidirectional PII handling.

- **Inbound** (result → model): detect PII in upstream responses, replace with stable placeholder tokens, retain the mapping in a store the model cannot reach.
- **Outbound** (model → tool): rehydrate placeholders back to real values only for arguments of tools that legitimately need them, and only when policy allows.

The critical property: **the model never sees a real PAN, bank account number, card number, or VPA, and does not need to.** It reasons over stable tokens. `ACCT_a17f` is as useful to a reconciliation agent as the real account number, and infinitely less dangerous in a log, a trace, a cassette, or an exfiltration attempt.

This property matters more under the multi-provider design than it would have under a single first-party provider: prompts are being sent to third-party inference services whose free tiers may train on inputs. Redaction is part of what makes that acceptable, alongside the fixture data being synthetic. Say both things in the README.

Full specification in `05-AUDIT-AND-REDACTION.md`.

### 4.7 Trust Boundary / Quarantine

The countermeasure to prompt injection.

Every piece of text entering the model is tagged with a provenance level:

| Level | Source | Treatment |
|---|---|---|
| `SYSTEM` | Our own prompts and policies | Trusted. Instructions honoured. |
| `OPERATOR` | The human running the agent | Trusted. Instructions honoured. |
| `TOOL_STRUCTURED` | Machine-generated fields from upstream (IDs, amounts, timestamps, enums) | Trusted as *data*. Never as instructions. |
| `UNTRUSTED` | Any free-text field, any uploaded document, any customer/merchant-authored string | Quarantined. |

Quarantined content is wrapped in an unambiguous, non-forgeable delimiter and preceded by a standing instruction that content inside is data to be analysed and never instructions to be followed. The delimiter includes a per-run random nonce so it cannot be closed early by an attacker who has read our source code — this is essential and is the difference between a real defence and a cosmetic one.

The quarantine wrapper is applied by the proxy, in result post-processing, based on field provenance derived from the tool's output schema. Do not rely on the agent to quarantine its own inputs.

### 4.8 Idempotency Guard

Agents retry. Loops repeat. Networks time out ambiguously. **Provider failover introduces a new retry path.** Without a guard, a retried refund is a second refund.

Every mutating call gets a deterministic idempotency key derived from `(run_id, semantic_operation, canonicalised_arguments)`. Canonicalisation must be stable: sorted keys, normalised numeric representation, normalised whitespace. Before forwarding, the guard checks whether this key has been seen in this run. If it has, return the stored prior result and record an `IDEMPOTENT_REPLAY` event rather than executing again.

**Failover makes this more important, not less.** If provider A times out after emitting a tool call and provider B re-emits it, the idempotency guard is what prevents duplicate execution. Add a test for exactly that sequence.

> **RESEARCH FIRST:** Determine whether the upstream Razorpay APIs accept a native idempotency key header and, if so, propagate ours rather than inventing a parallel mechanism. Native support is strictly better. Document the finding either way.

### 4.9 Approval Store

Holds escalated actions awaiting a human.

An approval request captures: the full decision context, the policy rule that triggered escalation, a plain-language rendering of what will happen, the redacted arguments, and an expiry. A human approves or rejects with an optional note. Approvals are **single-use and bound to the exact argument hash** — approving "refund ₹500 to payment X" must not authorise "refund ₹5000 to payment X". Expired approvals are dead, not renewable.

The run blocks while awaiting approval and resumes on decision. Design for the approval to arrive minutes later, or never.

### 4.10 Audit Ledger

Append-only, hash-chained. Each entry contains the hash of the previous entry, making retroactive alteration detectable. Ships with a verification command that walks the chain and reports the first break.

This is deliberately modest — tamper-*evident*, not tamper-*proof*. Say so in the README. Overclaiming here is worse than the limitation.

Full specification in `05-AUDIT-AND-REDACTION.md`.

### 4.11 Cost & Latency Meter

Wraps every run. Records per-step and per-run: input tokens, output tokens, cost where derivable, wall-clock latency, time attributable to policy evaluation, and **which provider and model served each call**.

That last field is necessary under failover: a latency number that does not name its provider is meaningless.

The policy-evaluation metric matters because the honest question about any guardrail is "what does it cost you?" Being able to answer "policy evaluation adds a measured p95 of X ms" is the difference between an engineer and an enthusiast.

Where a provider reports no usage, record the gap explicitly rather than estimating. An invented number is worse than a missing one.

### 4.12 Fixture Server

A second MCP server implementing the same tool surface as the upstream, backed by a static synthetic dataset.

This exists so evaluations are deterministic and the red-team suite never touches anyone's infrastructure. It is not a toy — its tool schemas must match upstream exactly, or evals will pass against fixtures and fail against reality.

**Mode switching** is a single environment variable. Everything else is identical between modes. If any component behaves differently in fixture mode versus live mode, that is a bug — it means the fixture is not a faithful double.

## 5. The request lifecycle

Follow one tool call end to end. This is the sequence to implement and the sequence to explain in an interview.

```
 1. Agent loop sends messages + tool manifest via the provider abstraction.
      → cassette hit: replay. miss: call provider, record.
      → rate limit or error: back off, then fail over to secondary provider.
 2. Provider returns a tool call. Loop builds DecisionContext, calls Policy Engine.
      → DENY here short-circuits: a structured denial is appended to the message
        history so the model can read it and adapt.
 3. Call reaches the SENTINEL MCP Proxy over the MCP protocol.
 4. Classifier resolves risk class. UNKNOWN → deny, fail closed.
 5. Argument validation against the tool's declared schema. Malformed → deny.
 6. Redaction Service rehydrates any placeholder tokens in the arguments.
      → A placeholder the model was never legitimately given → deny + flag as
        possible exfiltration attempt.
 7. Policy Engine evaluates (second, authoritative evaluation).
      ALLOW      → continue
      DENY       → block, audit, return structured denial
      ESCALATE   → create approval request, suspend run, await human
 8. Idempotency Guard checks the key. Seen → return stored result, no execution.
 9. Forward to upstream (live or fixture).
10. Result returns. Scan for PII → redact → replace with placeholder tokens.
11. Classify field provenance. Wrap UNTRUSTED text in nonce-delimited quarantine.
12. Write audit entry: decision, reason code, matched rule, redacted args,
    latency, tokens, provider, model, cost, chain hash.
13. Return to model. Loop appends the result and iterates.
14. Trace event streamed to the UI and persisted for eval replay.
```

Every one of steps 4–12 must be able to fail closed independently.

## 6. Technology choices

Stated with reasoning so they can be overridden intelligently rather than followed blindly.

| Layer | Choice | Reasoning |
|---|---|---|
| Agent loop | Written in-house, ~200 lines | We need precise control of the interception point regardless. Removes framework version churn from a security path. "I wrote the loop, so I know exactly where the boundary is" is a stronger claim than "the framework handles it." |
| Inference | Two free-tier providers with tool calling, behind an abstraction | Model independence is a design goal. Two providers also mitigates rate limits and silent model deprecation. |
| Control plane API | FastAPI | Named in the JD. Async-native, which matters for streaming traces and long-blocked runs. Pydantic gives schema validation for free. |
| Proxy | Python MCP server implementation | Same process family as the runtime, simpler operationally. Language-independent by protocol regardless. |
| Persistence | SQLite → Postgres-ready | SQLite makes the demo one command with no external service. Every query goes through a repository layer so the swap is contained. |
| Frontend | React + TypeScript + Vite | TypeScript is in the JD. Vite for build speed. |
| Policy format | Declarative, versioned, human-readable | Non-engineers must be able to read a policy. That is the point of externalising it from the prompt. |
| Container | Docker + Compose | Upstream MCP server ships as a Docker image; Compose makes the whole stack one command. |
| CI | GitHub Actions | Runs in cassette-replay mode, so CI needs no provider credentials at all. |

## 7. Repository layout

Structure follows the architecture. A reader should be able to infer the design from `ls`.

```
sentinel/
├── CLAUDE.md
├── README.md
├── DECISIONS.md
├── LIMITATIONS.md
├── docker-compose.yml
├── Makefile                      # make demo, make eval, make redteam, make verify-audit
├── config/
│   ├── tool_classes.yaml         # risk classification, reconciled at startup
│   ├── policies/                 # versioned policy sets
│   ├── providers.yaml            # models, rate limits, failover order
│   └── redaction_rules.yaml
├── sentinel/
│   ├── proxy/                    # MCP proxy: server, client, interceptor
│   ├── policy/                   # pure engine, rules, decision types
│   ├── redaction/                # detectors, tokenizer, quarantine
│   ├── audit/                    # ledger, hash chain, verifier
│   ├── approvals/                # store, lifecycle
│   ├── runtime/                  # agent loop, in-loop guard, trace emitter
│   ├── providers/                # abstraction, adapters, governor, cassettes
│   ├── agents/                   # the three agents: prompts, tool scopes, output schemas
│   ├── metering/                 # cost, latency, provider attribution
│   ├── api/                      # FastAPI routers
│   └── fixtures/                 # fixture MCP server + synthetic data generators
├── cassettes/                    # committed, synthetic-only, replayable
├── evals/
│   ├── scenarios/                # golden dataset
│   ├── runner.py
│   └── thresholds.yaml           # regression gates
├── redteam/
│   ├── payloads/                 # injection corpus, by vector and class
│   ├── runner.py
│   └── thresholds.yaml
├── frontend/
└── tests/
```

## 8. Failure modes to design against explicitly

Write a test for each. These are the things that will actually go wrong.

| # | Failure | Required behaviour |
|---|---|---|
| 1 | Upstream MCP server unreachable at startup | Refuse to start. An empty manifest means every tool is `UNKNOWN`, which is safe, but silently starting broken is worse than failing loudly. |
| 2 | Upstream adds a tool we have not classified | Deny it. Surface prominently. Never guess a class from the name. |
| 3 | Policy file malformed | Refuse to start. Never fall back to a permissive default. |
| 4 | Policy engine raises mid-run | Deny the call, record `POLICY_EVALUATION_ERROR`, abort the run. Never treat an exception as allow. |
| 5 | Approval expires while run suspended | Terminate cleanly. Do not resume on a stale approval. |
| 6 | Model emits an unissued placeholder token | Deny, flag as suspected exfiltration, escalate to the UI. |
| 7 | Model attempts a tool removed from the manifest | Should be impossible; if observed, treat and log as a serious incident. |
| 8 | Injection payload appears inside a quarantine block | Expected. Record whether subsequent tool calls changed as a result — that is the red-team metric. |
| 9 | Audit chain hash mismatch | Verifier reports the first broken link and refuses to certify the run. |
| 10 | Concurrent runs mutate the same entity | Entity-level locking in the idempotency layer; second run blocks or fails, never interleaves. |
| 11 | **Primary provider rate-limits mid-run** | Governor blocks locally before the provider rejects; back off, then fail over. Record the switch in the trace. The run must not fail. |
| 12 | **Provider emits a malformed tool call** | Reject at the abstraction boundary; do not forward to the proxy. Retry once with a corrective message, then fail the run cleanly. **Never guess the intended arguments.** |
| 13 | **Provider deletes a model we depend on** | Startup probe confirms configured models are live. Missing model → refuse to start, naming the model. |
| 14 | **Cassette miss in a replay-mode CI run** | Hard failure. CI must never silently fall through to the network. |

Failures 11–14 are specific to the multi-provider design and easy to overlook. Free-tier catalogues change without notice; a project that dies silently when a model is deprecated is not one anyone can run six months from now.

## 9. What we are deliberately not building

Say these out loud in `LIMITATIONS.md`. Naming your own scope cuts is a seniority signal.

- Multi-tenancy and real authentication. Single operator, local deployment.
- Encryption at rest for the placeholder mapping store.
- A policy DSL with arbitrary expressions. Deliberately constrained rule types — an expressive DSL is a new attack surface.
- Streaming/partial tool results.
- Any protection against a malicious *operator*. SENTINEL constrains the agent, not the human running it.
- Formal verification of policy completeness. We test; we do not prove.
- **Production-grade inference.** Free-tier providers are rate-limited by design and unsuitable for real throughput. The architecture supports any provider; this deployment uses free ones. Say so plainly rather than letting a reviewer discover it.
