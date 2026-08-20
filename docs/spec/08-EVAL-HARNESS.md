# 08 — Evaluation Harness

> This is the component that most distinguishes the project. Building an agent is common. Being able to state, with evidence, whether your agent got better or worse this week is rare.

## 1. What is currently true

Agent development is overwhelmingly evaluated by trying a few prompts and forming an impression. Prompt changes, model swaps, and new tools ship without any measurement of whether they helped. When something regresses, nobody knows which change caused it.

The JD names this directly: evaluate outputs for accuracy, reliability, latency, and cost, and iterate accordingly. That sentence describes an eval harness. Almost no candidate will have built one.

Our specific constraint sharpens the design: the runtime uses **free-tier providers with hard daily request ceilings**. A naive harness that calls a model on every run would exhaust its quota before finishing one suite. That constraint forces an architecture that is better anyway.

## 2. What we are solving

**Make "did this change make things better?" a question with a numerical answer, produced automatically, on every commit, without an API key.**

Five requirements:

| Requirement | Why |
|---|---|
| **Deterministic** | Runs against fixtures and cassettes, never the network. Same commit, same numbers. |
| **Reproducible by a stranger** | A reviewer clones the repo and gets your exact numbers with no credentials. |
| **Multi-dimensional** | Accuracy alone is a trap. Cheaper-but-wrong and correct-but-unaffordable are both regressions. |
| **Safety-gated** | Some metrics have hard floors, not trends. Unauthorised execution count must be zero, always. |
| **Attributable** | Every result carries the commit, prompt hash, policy version, provider, and model that produced it. |

## 3. How we proceed

### 3.1 Cassettes are the foundation

**Build the cassette layer before the first scenario.** Not after, not alongside — before. Every design choice below assumes it exists.

Three run modes:

| Mode | Behaviour | Used for |
|---|---|---|
| `record` | Call providers, persist every interaction | Authoring new scenarios; refreshing after a real change |
| `replay` | Serve from cassettes only. Miss = hard failure. No network. | **CI, and anyone reproducing your results** |
| `auto` | Replay on hit, record on miss | Local development |

Consequences worth stating explicitly in the README:

- CI needs **no provider credentials at all**.
- A reviewer reproduces your exact eval numbers with **no API key**.
- Suite runtime drops from hours to seconds, so evals stop being something you avoid running.

**The cassette key must include everything that could change the response** — prompt, message history, tool manifest, model, provider, policy set version, fixture dataset version. An incomplete key produces stale replays that look like passing tests, which is the worst possible failure mode for an eval harness. Get this right on day one.

Cassettes are committed. They contain only synthetic data. Run the PII invariant check over them anyway.

**Recording discipline.** Recording is quota-limited, so plan it: record in batches, respect the governor, and record overnight if needed. Re-record only when the cassette key genuinely invalidates. Track and report "cassettes refreshed this run" so a suspiciously large refresh is visible rather than silent.

### 3.2 The golden dataset

Target roughly 100 scenarios at completion. Do not attempt 100 at once — build 15 covering all categories, get the harness running end to end with cassettes, then expand. A harness that works on 15 scenarios beats a dataset of 100 with no harness.

**Composition:**

| Category | Share | Purpose |
|---|---|---|
| Happy path | ~30% | The task done correctly under normal conditions |
| Hard-but-correct | ~25% | Ambiguous matches, partial data, pagination, multi-page results |
| Refusal-correct | ~15% | The right answer is "I cannot determine this." Tests honesty. |
| Policy-triggering | ~20% | Actions that must be denied or escalated |
| Adversarial-lite | ~10% | Injection-adjacent content (the full suite lives in red-team) |

**Refusal-correct scenarios are the most undervalued category.** An agent that confidently produces an answer when the data does not support one is far more dangerous in a financial context than one that declines. Measure this explicitly and report it as its own metric.

**Scenario authoring:**
- Every scenario is a data file, never code.
- Every scenario states its expected outcome and the reasoning for it, in a comment. Six months later you will not remember why an assertion is what it is.
- Every scenario asserts `no_unauthorized_execution`, regardless of what it is nominally testing.
- Scenarios are versioned. Changing a scenario's expected outcome is a reviewable event, because it is how people silently make a failing test pass.

### 3.3 Metrics

Report all of these, **broken down per model.**

**Correctness**
- Task success rate, by scenario category
- Structured output schema conformance rate
- **Malformed tool-call rate** — a real quality signal, and it will differ sharply between models
- Tool-call precision and recall
- Citation validity, for the RAG agent
- Appropriate-refusal rate, on refusal-correct scenarios
- Over-refusal rate, on happy-path scenarios — **the false-positive metric, and the one people forget**

**Safety** — hard gates, not trends
- Unauthorised executions: **must be 0, on every model**
- PII leakage incidents: **must be 0**
- Policy evaluation errors: **must be 0**
- Escalations correctly triggered: rate
- Escalations spuriously triggered: rate (the safety false-positive)

**Cost**
- Mean and p95 cost per run where derivable. Where a provider reports no usage, **record the gap rather than estimating.**
- Token usage split: input, output
- Cost attributable to guardrail overhead

**Latency**
- p50, p95, p99 wall-clock per run, **attributed by provider** — a latency number that does not name its provider is meaningless under failover
- Policy evaluation latency distribution — the honest cost of the guardrail
- Time-to-first-tool-call

Latency must be measured in **record mode**, not replay. Replay latency measures disk reads. State this in the README so nobody mistakes one for the other.

**Reliability**
- Run completion rate
- Provider failover count
- Retry rate
- Variance across repeated runs of the same scenario — **critical, see 3.5**

### 3.4 Regression gates

Thresholds live in a versioned config file, not in code. CI fails when breached.

Three gate types:

1. **Absolute floors** — task success below X% fails, regardless of the previous value.
2. **Relative regressions** — a drop of more than Y percentage points from the recorded baseline fails, even if still above the floor.
3. **Hard zeros** — unauthorised executions, PII leaks, policy errors. Any non-zero fails immediately, **on any model**.

Cost and latency get relative gates too. A change that improves accuracy by one point while tripling cost is a regression, and a harness that cannot say so is not doing its job.

**Threshold changes require an explicit, reviewable commit with a stated reason.** Lowering a threshold to make CI pass must be a visible act, not a quiet edit.

### 3.5 Handling non-determinism

The fixtures are deterministic. Cassettes make replay deterministic. **The recording itself is not.** Address this honestly rather than letting cassettes hide it.

Approach:
- Record each scenario **N times** (N ≥ 3) as distinct cassettes. Report mean and variance across them.
- **Variance is itself a reported metric.** A scenario whose outcome flips between recordings is unreliable, and that unreliability is a finding, not noise to be averaged away.
- Gates evaluate on the mean; high-variance scenarios are flagged separately.
- Model versions pinned explicitly in config. A silent model change shifting your baseline is a real and confusing failure mode — and on free tiers, models are updated and deprecated without notice, so **the startup probe and the pinned config are what protect you.**
- Replay serves the N recordings, so variance is preserved in reproduction rather than collapsed.

**Document the variance methodology in the README.** Being able to explain how you handled model non-determinism in evaluation is a strong signal; being unable to is a weak one.

### 3.6 Reporting

Every eval run produces:
- A machine-readable result file, committed as an artefact
- A human-readable summary rendered in CI output
- A diff against the previous baseline, highlighting **every scenario whose outcome changed**, in both directions
- A per-model breakdown

That "both directions" point matters. A newly-passing scenario is as interesting as a newly-failing one — it may indicate an assertion that was silently weakened.

The frontend consumes the historical result files to render trends across commits.

### 3.7 The guardrail-overhead measurement

Run the full suite twice: guardrails enabled and disabled. Report the delta in cost, latency, and accuracy.

This answers the sharpest question anyone will ask: *"What does your safety layer cost you?"*

Having a measured answer — "adds a measured p95 of X ms and Y% of run cost, with no measurable accuracy loss" — is the difference between an engineer and an enthusiast. If the overhead turns out to be significant, **report it honestly and discuss the tradeoff.** A real number with an honest interpretation beats a flattering number every time.

Measure the policy-evaluation component separately from the proxy round-trip, so the number is attributable rather than a single opaque figure.

### 3.8 The multi-model comparison

Because the runtime is model-agnostic, running the suite against both models costs one extra recording pass and nothing thereafter. Do it, and give the result its own section in the README.

The finding to look for:

> Task accuracy varied between models. **The enforcement result did not.** Zero unauthorised executions on both, under identical policy.

That sentence is the strongest available evidence for the project's central claim — that safety is a property of the system rather than of the model — and it exists only because model independence was designed in.

Expect the weaker model to score lower on accuracy and higher on malformed tool calls. **Report that plainly.** It is a real finding about the gap between capability and safety, and reporting it demonstrates that your evaluation measures something rather than confirming something.

## 4. Acceptance criteria

- [ ] Cassette layer built before the first scenario.
- [ ] Cassette key includes prompt, history, manifest, model, provider, policy version, fixture version.
- [ ] Replay mode uses zero network calls, verified.
- [ ] Cassette miss in replay mode is a hard failure.
- [ ] A clean clone reproduces the committed eval numbers with no credentials — verified on a fresh machine.
- [ ] 15 scenarios covering all five categories, running end to end, before expanding.
- [ ] Every metric in 3.3 computed, reported, and broken down per model.
- [ ] Hard-zero gates fail CI on any non-zero value, on any model, with a test.
- [ ] Relative regression gates fire against a deliberately degraded run.
- [ ] Variance reported per scenario across N recordings.
- [ ] Latency measured in record mode and labelled as such.
- [ ] Cost gaps recorded honestly where a provider reports no usage.
- [ ] Baseline diff highlights changes in both directions.
- [ ] Guardrail-overhead comparison produced; numbers stated in the README.
- [ ] Multi-model comparison produced; enforcement result identical across models.
- [ ] Threshold config changes are reviewable and require a stated reason.
