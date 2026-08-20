# 11 — Build Order

## The governing principle

**Build the thing that can prove itself, early.**

The temptation is to build all three agents first because they are visible, then bolt on guardrails. That order produces a project where the interesting part is rushed and untested.

The order below front-loads the control plane and adds agents as they become needed to exercise it. At the end of Phase 4 — well before the frontend exists — the project already has its central claim demonstrable from the command line.

**Every phase ends with a demonstrable artefact.** If a phase cannot be demonstrated, it is not finished, regardless of how much code exists.

**Every phase ends with a `DECISIONS.md` entry.** Decisions recorded at the time are accurate; decisions reconstructed later are fiction.

---

## Phase 0 — Foundation

**Goal:** the skeleton, the contracts, and a verified understanding of both external systems.

> **No model access is needed for Phases 0 through 3.** The proxy, policy engine, redaction, audit ledger, idempotency, approvals, and fixture server are all deterministic and are tested with a scripted agent. A provider is first required in Phase 4.

Work:
1. Repo, `CLAUDE.md`, Docker Compose, Makefile, CI skeleton, secret scanning.
2. **All data contracts from `03-DATA-CONTRACTS.md`.** Types before behaviour.
3. Reason-code enum with rendering templates.
4. **Complete every RESEARCH FIRST block in `02` and `06`.** Run the Razorpay MCP server locally with test keys and call `tools/list`. Select two inference providers and **verify tool calling works on their free-tier models with a real call** — documentation is not sufficient evidence here. Record limits, formats, usage reporting, and the date checked in `DECISIONS.md`.
5. Contract round-trip and redaction-serialisation tests.

**Exit criteria:**
- [ ] `tools/list` output from the real upstream captured and committed as a reference artefact.
- [ ] Two providers selected, with tool calling verified by a real call, and their limits recorded with the date checked.
- [ ] All contracts defined, tested, round-tripping.
- [ ] CI runs on push.
- [ ] Secret scanning active; a test key committed by accident would be caught.

**Do not proceed until the research is genuinely done.** Every later phase compounds an error made here.

---

## Phase 1 — Fixture server and tool classification

**Goal:** a deterministic world, and a classification of everything in it.

Work:
1. Synthetic data generators. Seeded, reproducible, checksum-invalid identifiers.
2. Fixture MCP server matching upstream schemas exactly.
3. Schema-parity CI check: fixture versus live `tools/list`.
4. `config/tool_classes.yaml` — classify **every** upstream tool, by reading what it does.
5. Reconciliation logic: classified / unclassified / stale.

**Exit criteria:**
- [ ] Fixture server serves the full tool surface; parity check passes.
- [ ] Every upstream tool classified, with rationale for every money-movement classification in `DECISIONS.md`.
- [ ] Regeneration from seed is byte-identical.
- [ ] No generated identifier passes real checksum validation.

---

## Phase 2 — Policy engine

**Goal:** the pure decision core.

Work:
1. Rule types from `04` §3.2.
2. Evaluation semantics: most-restrictive-wins, fail-closed, no short-circuit.
3. Policy file schema and loader; malformed file → refuse to start.
4. The three policy sets: `strict`, `permissive`, `reconciliation-readonly`.
5. Explanation rendering for every reason code.
6. Unit tests per rule type. Property tests per `04` §3.6.
7. **CI check enforcing zero I/O imports in the policy package.**

**Exit criteria:**
- [ ] All property tests pass, including the invariant that no policy file can auto-allow money movement.
- [ ] Malformed policy causes startup failure, with a test.
- [ ] Rule exception produces `DENY` and aborts, with a test.
- [ ] Every reason code renders; no rendered explanation leaks PII.
- [ ] Purity check passes in CI.

---

## Phase 3 — The proxy, redaction, and the audit ledger

**Goal:** the enforcement boundary exists and is provable.

Work:
1. MCP proxy: server side, client side, startup reconciliation, manifest filtering and annotation.
2. Redaction: structural and pattern detection, tokenisation, rehydration with unissued-token detection.
3. Quarantine with per-run nonce.
4. Audit ledger with hash chain and verifier.
5. Idempotency guard.
6. **The PII invariant test across every output surface.**

**Exit criteria:**
- [ ] Proxy refuses to start when upstream is unreachable.
- [ ] Unclassified tool is denied and surfaced.
- [ ] PII invariant test passes across all surfaces, in CI.
- [ ] Tokens stable within a run, distinct across runs.
- [ ] Unissued-token rehydration denied and flagged.
- [ ] Nonce delimiter cannot be escaped by a payload containing a guessed delimiter.
- [ ] Audit chain verifies clean, and reports the exact break position when mutated.
- [ ] Idempotent replay returns the stored result without re-executing.

---

## Phase 4 — Runtime, first agent, and the first real demonstration

**Goal:** end to end, command line, no UI. **This is the milestone that matters most.**

Work:
1. Provider abstraction: adapters, conformance suite, rate-limit governor, failover, startup model probe, **cassette layer**.
2. In-house agent loop with the in-loop guard.
3. Layer-agreement test across both enforcement layers.
4. Trace emission.
5. Approval store and a minimal CLI approval flow.
6. Suspension and resumption, surviving a process restart.
7. Resource ceilings.
8. **Reconciliation Agent.**
9. Cost and latency meter, with provider attribution.

**Exit criteria — the important ones:**
- [ ] Reconciliation Agent completes a real task against fixtures and produces valid structured output.
- [ ] A money-movement call is denied by policy, with a plain-language reason, from the command line.
- [ ] An escalated call suspends the run; approving from the CLI resumes it; expiry terminates it.
- [ ] **A third-party MCP client pointed at the proxy is subject to identical policy.** Record this — it is the framework-independence proof.
- [ ] Failover works on rate limit and error, without causing duplicate execution.
- [ ] Startup model probe refuses to start on an unavailable model.
- [ ] Cassettes record and replay; replay uses zero network calls.
- [ ] Both enforcement layers agree across a test corpus.
- [ ] Audit log for a complete run verifies clean.

**At this point the project's core claim is demonstrable.** Everything after this makes it measurable and presentable. If time runs short later, the project is already defensible from here.

---

## Phase 5 — Eval harness

**Goal:** numbers.

Work:
1. Scenario format and runner, built on the cassette layer from Phase 4.
2. **15 scenarios covering all five categories.** Get the harness working before expanding.
3. All metrics from `08` §3.2.
4. Regression gates: absolute, relative, hard-zero.
5. N-run variance handling.
6. Baseline diff.
7. CI integration.
8. Expand toward ~100 scenarios.

**Exit criteria:**
- [ ] Suite runs offline with zero network calls, verified.
- [ ] Hard-zero gates fail CI on any non-zero value, with a test.
- [ ] Relative gates fire against a deliberately degraded run.
- [ ] Variance reported per scenario.
- [ ] Guardrail-overhead comparison produced; numbers recorded in the README.
- [ ] A clean clone reproduces the committed numbers in replay mode with no credentials.
- [ ] Multi-model comparison produced; enforcement result identical across both models.

---

## Phase 6 — Remaining agents and the red-team suite

**Goal:** full risk coverage and the headline result.

Work:
1. Dispute Responder, with the RAG component and independently evaluated retrieval.
2. Subscription Recovery, with per-action escalation and `counterparty_novelty`.
3. Payload corpus: eleven classes, four-plus vectors, plus benign-but-suspicious.
4. Rule-based deterministic grading.
5. Paired A/B runner. **Fixture-mode-only enforcement, tested.**
6. Ablation across individual controls.
7. CI gate on L3/L4.

**Exit criteria:**
- [ ] All three agents operational.
- [ ] Retrieval evaluated independently; chunking comparison in `DECISIONS.md`.
- [ ] Red-team runner refuses non-fixture mode, with a test.
- [ ] Paired A/B produced for every payload.
- [ ] Ablation table produced.
- [ ] Zero L3 and L4 under guardrails-on.
- [ ] False-positive rate measured and reported.

---

## Phase 7 — Operator surface

**Goal:** a reviewer can see it without reading code.

Work: all six views from `10`. Design pass before implementation, per the design direction in that document.

**Exit criteria:** as listed in `10` §6.

---

## Phase 8 — Ship

**Goal:** a stranger can evaluate it in ten minutes.

Work:
1. **README.** Problem, architecture, the three headline numbers, guardrail overhead, quickstart, and an honest limitations section.
2. `LIMITATIONS.md`, complete and unflinching.
3. `DECISIONS.md`, tidied and complete.
4. Deployment with a live demo URL, fixture mode, no keys required to try it.
5. One-command local start.
6. **The 90-second demo video** per `09` §4.6.
7. Architecture diagram.
8. Final security pass: no keys anywhere in history, secret scan clean, test-mode notice prominent, non-affiliation stated.

**Exit criteria:**
- [ ] Clone to running in one command, verified on a clean machine.
- [ ] Live demo reachable, fixture mode, no credentials required.
- [ ] Demo video recorded and linked from the README.
- [ ] README states all three red-team numbers and the guardrail overhead.
- [ ] `LIMITATIONS.md` is honest about tamper-evidence, quarantine efficacy, and everything cut.
- [ ] Git history contains no credentials.

---

## Descoping order, if time compresses

Cut from the bottom. Never cut from the top.

1. Reduce the golden set from 100 scenarios to 40. Keep all five categories.
2. Cut the Subscription Recovery agent. Move `counterparty_novelty` demonstration into a policy test.
3. Cut the eval dashboard view; keep the CI report and link the artefacts.
4. Cut the policy editor UI; keep the dry-run simulator as a CLI command.

5. Drop to a single provider. Keep the abstraction and say in the README that a second provider is configured but unrecorded — the abstraction is the claim, the second model is the evidence.

**Never cut:** the proxy, the policy engine, redaction, the audit chain, the cassette layer, the red-team paired A/B, or the honest limitations section. Those are the project.
