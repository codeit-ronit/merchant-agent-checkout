# DECISIONS.md — SENTINEL Architecture Decision Log

Append-only during the build. A decision recorded at the time is accurate; a
decision reconstructed at the end is fiction. Every entry names the trade-off
accepted — an ADR without a named cost is marketing, not a decision.

Format per `docs/spec/14-ADR-LOG.md`.

---

## ADR-000 — Build posture: offline-first, credential-free demonstration
Date: 2026-08-21    Phase: 0    Status: Accepted

### Context
The build has no Anthropic API key and only free-tier inference access. The spec
(`02` §4.3, `08` §3.1) already requires that the eval harness run against
cassettes with *no API key at all*, and that Phases 0–3 need no model access.

### Options considered
1. **Require a live provider key to run anything.** Simple, but makes the demo
   fragile (rate limits, model deprecation) and non-reproducible by a stranger.
2. **Offline-first: fixture upstream + committed cassettes + a deterministic
   scripted provider, with real provider adapters that activate only when a key
   is present.** More upfront work (must build record *and* replay paths, must
   author cassettes), but the whole system — demo, tests, evals, red-team —
   runs with zero credentials, and a reviewer reproduces the exact numbers.

### Decision
Option 2. `SENTINEL_MODE=fixture` and `SENTINEL_CASSETTE=replay` are the
defaults everywhere. Real OpenAI-compatible provider adapters exist and record
new cassettes when a key is supplied, but nothing in the default path touches
the network.

### Rationale
It matches the spec's strongest reproducibility claim and turns "no key" from a
limitation into the intended operating mode. Determinism is also what makes the
red-team A/B and the eval regression gates trustworthy.

### Trade-off accepted
Cassettes must be authored and kept fresh; an incomplete cassette key would
produce stale replays that look like passing tests (guarded by ADR-002b). We
carry both a record and a replay path instead of one.

### Revisit if
A funded deployment wants real throughput — then pin a paid provider and record
continuously.

---

## ADR-001 — Enforcement placement: proxy + in-loop, prompt as documentation
Date: 2026-08-21    Phase: 0    Status: Accepted

### Context
A guardrail can live in the system prompt, in the agent loop, or in an MCP proxy
between the agent and the tool server. The project's central claim is that
prompt guardrails are advisory and only boundary enforcement is a property of
the system.

### Options considered
1. **Prompt only.** Zero infrastructure; untestable, erodes under adversarial
   input, produces no artefact.
2. **In-loop only.** Runs in our process, model can't bypass — but scoped to one
   agent implementation and shares a process with attacker-influenced content.
3. **Proxy only.** Protocol-level, framework-independent, survives the agent
   being swapped — but lacks the model's stated reasoning and step context, and
   returns opaque transport errors the model can't adapt to.
4. **Proxy (the guarantee) + in-loop (the experience).**

### Decision
Option 4. The MCP proxy is the boundary that cannot be bypassed and fails
closed; the in-loop guard exists for better denials, richer context, and one
saved round-trip. Both call the *same* pure policy engine with the *same*
context builder. Disagreement is a logged `LAYER_DISAGREEMENT` P0 bug, resolved
to the more restrictive outcome.

### Rationale
Defence in depth with a clean division of responsibility, and the framework-
independence proof (a third-party MCP client subject to identical policy) is
only possible because the proxy is a real MCP server, not a function wrapper.

### Trade-off accepted
Two enforcement paths to keep in sync, and a layer-agreement test that must run
forever. Duplicated evaluation per call (mitigated: the engine is pure and sub-
millisecond).

### Revisit if
The in-loop guard ever diverges from the proxy in a way the agreement test
can't catch — then collapse to proxy-only and accept opaque denials.

---

## ADR-002 — In-house agent loop rather than a framework
Date: 2026-08-21    Phase: 0    Status: Accepted

### Context
The interception point is the entire project. Frameworks package the loop but
bring version churn on a security-critical path and couple to one vendor.

### Options considered
1. **Adopt a framework** (LangChain / a vendor agent SDK). Battle-tested context
   management, retries, session handling — but an opinionated hook API, version
   churn, and vendor coupling that weakens the model-independence claim.
2. **Write the loop in-house (~200 lines).** Total control of the interception
   point, no framework on the security path, genuinely model-agnostic.

### Decision
Option 2.

### Rationale
"I wrote the loop, so I know exactly where the boundary is" is a stronger and
more testable claim than "the framework handles it." Model independence is a
design goal, and framework provider-abstractions lag new free-tier providers.

### Trade-off accepted
We give up battle-tested context management, sophisticated retry logic, and
session handling. For a scoped, fixture-backed project this is acceptable; for a
production system at throughput it would not be. Recorded here so it is not
mistaken for an oversight.

### Revisit if
The project grows into a production system, or context-window management becomes
a real source of bugs.

---

## ADR-002a — Provider selection (Groq primary, Gemini fallback)
Date: 2026-08-21    Phase: 0    Status: Accepted

### Context
The runtime is provider-agnostic and needs two free-tier providers with reliable
tool calling. Free-tier catalogues change monthly, so this was verified live on
2026-08-21 (see research report). The hard requirement is tool calling, not
generous limits.

### Options considered
Candidates surveyed live: Groq, Google Gemini (AI Studio), Cerebras, OpenRouter,
Mistral La Plateforme, GitHub Models.
- **Groq** — OpenAI-compatible (`api.groq.com/openai/v1`); tool calling on all
  models; `tool_calls[].function.arguments` as a JSON string; usage as
  `prompt_tokens`/`completion_tokens`; `429` + `retry-after` + `x-ratelimit-*`;
  **does not train on inputs**; no card. GPT-OSS limits: 30 RPM / 1K RPD / 8K TPM.
- **Gemini** — OpenAI-compat endpoint (`…/v1beta/openai/`) so one adapter shape
  covers both; strong tool calling; high TPM; **free tier DOES train on inputs**
  (recorded — synthetic data only, so not a blocker). Enabling billing removes
  the free tier.
- Cerebras (fast but 5 RPM, 2 free models), OpenRouter (per-model inconsistent
  tool calling), Mistral (opaque published limits), GitHub Models (prototyping-
  only limits) — all rejected as primary.

### Decision
Primary **Groq**, fallback/second-comparison **Google Gemini**. Pin
`openai/gpt-oss-120b` (strong) and `openai/gpt-oss-20b` (weak) on Groq — same
provider, so capability-vs-safety is a clean comparison — plus `gemini-2.5-flash`
/ `gemini-2.5-flash-lite` for the cross-provider check. All in
`config/providers.yaml`, never hardcoded, with the verified-on date.

### Rationale
One OpenAI-compatible adapter covers both (satisfies "no provider-specific
branching in the loop"); two independent vendors break correlated failure; both
emit real 429s + usage the governor/meter need; the Groq/Gemini privacy gradient
is documented for an honest audit story.

### Trade-off accepted
Gemini's free tier trains on inputs (mitigated by synthetic-only data, stated in
README). Published limits are third-party for Gemini and must be re-confirmed in
console; the startup probe + pinned config is what makes that survivable. In this
build a live tool-call smoke test was NOT run (no keys), so cassettes are hand-
authored for the deterministic demo; recorded as an open item.

### Revisit if
A pinned model is deprecated (startup probe refuses to start, naming it), or a
funded deployment wants a paid provider.

---

## ADR-003 — Tool risk classification (partial; completed in Phase 1)
Date: 2026-08-21    Phase: 0    Status: Accepted

### Context
The upstream inventory was enumerated live from the razorpay/razorpay-mcp-server
README + Razorpay API docs (not a live `tools/list` — Docker + test keys were
unavailable; recorded as the honest gap). ~45 tools across payments, links,
orders, refunds, QR, settlements, payouts, tokens, and local helpers.

### Decision
Money-movement tools (classified conservatively — if a tool could move funds, it
is MONEY_MOVEMENT): `capture_payment`, `initiate_payment`, `submit_otp` (finalises
a charge), `create_refund`, `create_instant_settlement`. Notably the published
server exposes **no create-payout tool** and **no dispute/subscription CRUD** —
so the highest-classic-risk "send money out" primitive is not reachable, and the
Dispute agent's irreversible write is served by a clearly labelled fixture
extension (`submit_dispute_evidence`) reported as fixture-only by the parity check.

Full per-tool table and rationale land in `config/tool_classes.yaml` in Phase 1.

### Trade-off accepted
Classifying from docs rather than a live introspection risks a schema mismatch
the parity check can only catch against a real capture. Recorded; the reference
manifest carries a provenance note.

### Revisit if
A live `tools/list` capture becomes possible, or upstream adds money-moving tools.

---

## ADR-006 — Monetary representation: integer minor units, enforced at serialisation
Date: 2026-08-21    Phase: 0    Status: Accepted

### Context
Floats for money are a category error. Razorpay represents amounts as an integer
in the smallest currency subunit — ₹299 = `29900` (verified: razorpay.com/docs
orders/create and fetch-all-payments). Zero-decimal (JPY) and three-decimal
(KWD/BHD/OMR) currencies differ by subunit exponent.

### Decision
Integer minor units everywhere, matching upstream exactly so no conversion ever
happens in the engine. The canonical serialiser (`common/canonical.py`) **raises
on any float**, enforcing the rule at the boundary rather than by discipline.
`common/money.py` records subunit exponents for *display only*.

### Trade-off accepted
Callers must convert display amounts to minor units at the edge; the engine never
divides. This is the intended cost.

### Revisit if
A currency with a non-power-of-ten subunit appears (none in ISO 4217 today).

---

## ADR-007 — PII detection + synthetic-safe generation (Indian identifiers)
Date: 2026-08-21    Phase: 0    Status: Accepted

### Context
Verified formats live on 2026-08-21 (sources in the research report). Which
identifiers carry a checksum determines how the generator produces values that
are format-valid but cannot collide with a real one.

### Decision
- **Detection**: structural (schema-annotated fields in `ToolDescriptor`) as the
  primary mechanism; regex + format validation as the safety net for free text.
- **Formats**: PAN `[A-Z]{5}[0-9]{4}[A-Z]`; Aadhaar `[2-9][0-9]{11}` (Verhoeff);
  IFSC `[A-Z]{4}0[A-Z0-9]{6}` (no checksum); UPI VPA `local@handle`; GSTIN 15-char
  (Luhn mod 36); Indian mobile `[6-9][0-9]{9}`; card PAN 13–19 (Luhn mod 10);
  UTR NEFT 16 / RTGS 22 / IMPS-UPI 12 (no checksum).
- **Synthetic-safe generation** (so no synthetic value is a real identifier):
  for checksummed types (Aadhaar/Verhoeff, GSTIN/Luhn-36, card/Luhn-10) compute
  the correct check char then emit `(correct+1)` — guaranteed-invalid. For
  checksum-free types use **structural reservation**: IFSC bank code `ZZZZ`, VPA
  handle `@invalid`, UTR Julian day `999`, reserved mobile bodies, all-9s bank
  accounts. **Aadhaar is never stored/emitted at all** (Aadhaar Act sensitivity).

### Trade-off accepted
PAN's 10th-char algorithm is not public, so PAN synthetic-safety relies on a
structurally-reserved holder-type char (`X`), not a failed checksum. Redaction
detectors key on the *format regex*, not the checksum, because attacker-supplied
real values will not be conveniently checksum-broken.

### Revisit if
A checksum spec is published (PAN), or new identifier types enter the fixtures.

---

## ADR-010 — Canonical serialisation + hash (RFC 8785-inspired, SHA-256)
Date: 2026-08-21    Phase: 0    Status: Accepted

### Context
The audit chain, idempotency keys, and cassette keys all need a byte-stable
serialisation. RFC 8785 (JCS) is the standard, but its number handling forces
every value through an IEEE-754 double — which silently mangles 64-bit integers
and decimals, catastrophic for a money ledger.

### Decision
A JCS-inspired subset, **stricter** than the RFC: floats forbidden outright;
integers beyond ±(2^53−1) forbidden as numbers (carry as strings, per the RFC's
own recommendation) — our IDs are already strings; keys ordered by UTF-16 code
units (JCS order); compact UTF-8, non-ASCII literal. Hash: **SHA-256** (RFC 6962
/ CT family; collision-resistant; ubiquitous). Tamper-evidence reduces to SHA-256
collision resistance.

### Trade-off accepted
Not byte-identical to a generic RFC 8785 library for float-bearing inputs — but
we forbid those, so it is strictly safer for this domain. This is **tamper-
evident, not tamper-proof**: anyone who can rewrite the DB can recompute the whole
chain. Real resistance needs an external anchor (RFC 6962-style transparency log)
or WORM storage — neither implemented (LIMITATIONS.md).

### Revisit if
Cross-system interop with a generic JCS consumer is needed, or an external anchor
is added.

---

## ADR-011 — Idempotency: our own guard (no usable native key upstream)
Date: 2026-08-21    Phase: 0    Status: Accepted

### Context
Native Razorpay idempotency (`X-Payout-Idempotency`) exists **only for RazorpayX
payout APIs** and, since 2025-03-15, is mandatory there. But the MCP server
exposes **no payout-creation tool**, so none of the reachable money-movement
tools (`capture_payment`, `initiate_payment`, `create_refund`,
`create_instant_settlement`) are covered by any native idempotency mechanism.

### Decision
SENTINEL supplies its own guard: a deterministic key from `(run_id,
semantic_operation, canonicalised_arguments)`, checked before forwarding; a seen
key returns the stored result and records `IDEMPOTENT_REPLAY` rather than
re-executing. Where a native key IS available (a future payout tool), propagate
ours as its value rather than inventing a parallel mechanism.

### Trade-off accepted
Our guard is per-process/per-run state, not an upstream guarantee; a genuinely
duplicated call from two separate runs relies on entity-level locking, not the
key. Recorded.

### Revisit if
A payout-creation tool appears upstream (then propagate the native header).

---

## ADR-018 — Red-team grading + corpus, informed by public literature
Date: 2026-08-21    Phase: 0    Status: Accepted (design; built in Phase 6)

### Context
Surveyed live: OWASP LLM01:2025 (prompt injection = #1 risk; direct/indirect/
multimodal), Microsoft Spotlighting (datamarking dropped ASR ~50%→<3% but not to
0 under adaptive attack), OpenAI Instruction Hierarchy, the CaMeL paper
("defeat prompt injection by design" — separate control from data, least
privilege), and the "Critical Evaluation of Defenses" result that adaptive
attackers reach >90% ASR against published defenses. Benchmarks: AgentDojo (has a
Banking domain) and InjecAgent.

### Decision
- **Grading is rule-based and deterministic**, derived from the trace + audit
  log, never a model judging outputs (a model-graded safety suite cannot be
  trusted). Severity L0–L4 per `RedTeamSeverity`.
- **Corpus** covers the 11 payload classes across ≥4 vectors, plus a required
  benign-but-suspicious class to measure false positives (the "C" number).
- **Framing**: quarantine (per-run nonce) is a *mitigation*; permission narrowing
  is the *guarantee*. We expect L1 (behaviour altered) non-zero even guardrails-on
  and report it honestly; L3/L4 must be 0. The goal is to make being fooled
  harmless, not impossible — directly the CaMeL / OWASP least-privilege framing.

### Trade-off accepted
Rule-based grading can miss subtle behaviour changes a human would catch; we
accept coarser but trustworthy grades over a model judge. The injection detector
is a signal, never a gate (fails open on novel payloads by design → never decides).

### Revisit if
We adopt a vetted external grader, or add a benchmark like AgentDojo directly.


---

## ADR-004 — Policy language scope: a closed rule set, not a DSL
Date: 2026-08-21    Phase: 2    Status: Accepted

### Context
Policy must be readable by non-engineers, testable, and safe. An expressive
policy DSL (arbitrary predicates/expressions) is tempting for flexibility.

### Options considered
1. **An expression DSL** (e.g. a mini-language / eval of conditions). Maximally
   flexible — and a new attack surface, an untestable space, and a maintenance
   burden. Arbitrary evaluation over attacker-influenceable context is exactly
   what we are trying to prevent elsewhere.
2. **A closed set of typed rule types**, each with a narrow evaluation.

### Decision
Option 2: 11 rule types, each a pure pydantic model with a bounded ``evaluate``.
Adding a rule type is a reviewable code change with a test, not a config edit.

### Trade-off accepted
There are real policies this cannot express (arbitrary cross-field arithmetic,
conditional chains). That is a chosen cost, stated in LIMITATIONS.md. We would
rather deny an inexpressible policy than add an eval() surface.

### Revisit if
A recurring real policy need cannot be met — then add a *specific* typed rule,
never a general expression.

---

## ADR-005 — Policy engine purity, enforced structurally
Date: 2026-08-21    Phase: 2    Status: Accepted

### Context
A pure decision function can be exhaustively unit-tested, property-tested, and
replayed against historical traces. The moment it reads a clock or a DB it
becomes untestable and non-deterministic.

### Decision
``sentinel.policy`` imports no I/O. Time, spend, counts, and approval status are
injected via ``DecisionContext.env``. The YAML loader (I/O) lives outside the
package in ``sentinel.policy_loader``. A CI test (``test_policy_purity.py``) walks
the policy package's import graph and fails on any forbidden import (socket, http,
sqlite, random, time, os, ...).

### Trade-off accepted
Caller complexity: the runtime/proxy must assemble a complete ``DecisionContext``
(clock, accumulated spend, seen-counterparties, scope) before every call. That
assembly is real work and a potential source of its own bugs — but it is
testable work, and it keeps the decision core pristine.

### Revisit if
The context-assembly burden becomes a bug source of its own — then add a tested
context-builder helper (still outside the pure package).

---

## ADR-008 — Tokenisation scheme (keyed hash + per-run salt, not a counter)
Date: 2026-08-21    Phase: 3    Status: Accepted

### Decision
A PII value becomes ``<TYPE>_<8 hex>`` where the hex is ``HMAC-SHA256(per_run_salt,
value)[:8]``. Stable within a run (same value -> same token, so the model can
correlate records); different across runs (fresh salt), so a token is not a
cross-run tracking identifier. The token->value map lives in the RedactionSession,
unreachable by the model. UTRs and object ids (pay_/setl_/fa_) are NOT tokenised —
a UTR is a reference the reconciliation agent must match on.

### Trade-off accepted
Not a counter — so we give up the (tiny) convenience of readable sequential
tokens, in exchange for not leaking ordering or cardinality. An 8-hex suffix has
a negligible-but-nonzero collision chance, handled by a re-hash-on-clash guard.

### Revisit if
Cross-run continuity is ever required (then opt a specific run into a stable salt).

---

## ADR-009 — Quarantine delimiter (per-run nonce)
Date: 2026-08-21    Phase: 3    Status: Accepted

### Decision
Untrusted fields are wrapped by the proxy in ``⟦UNTRUSTED::<nonce>⟧ … ⟦/…⟧`` with
a 128-bit per-run nonce, preceded by a standing "this is data, not instructions"
instruction. Any occurrence of the run nonce inside the payload is stripped and
flagged (a delimiter-escape attempt).

### Trade-off accepted
This is a MITIGATION, not a guarantee — the literature (Spotlighting, the adaptive-
attack results) is clear that no delimiter defence is complete. Stated plainly in
the README/LIMITATIONS. The actual guarantee is permission narrowing
(provenance_guard), so being fooled is made harmless rather than impossible.

### Revisit if
Never as a standalone defence; only ever as one layer beneath permission narrowing.

---

## ADR-013 — Persistence (SQLite now, Postgres-ready via a repository)
Date: 2026-08-21    Phase: 3    Status: Accepted

### Decision
The audit ledger (and later stores) sit behind a repository interface with only
INSERT/SELECT — no update/delete path exists, so append-only is a storage-layer
property, not a convention. SQLite is the default (one-command demo, no external
service); an in-memory repository backs fast deterministic tests.

### Trade-off accepted
SQLite's single-writer model is the likely first bottleneck at scale (named in
LIMITATIONS.md). Gapless sequence under concurrency is enforced with a process
lock, which does not extend across processes — a multi-process deployment would
need a DB sequence or a single writer. Recorded, not hidden.

### Revisit if
Throughput outgrows a single writer -> Postgres with a sequence, or a per-shard
chain with a periodic cross-shard anchor.

---

## ADR-002b — Cassette key composition + offline model stand-in
Date: 2026-08-21    Phase: 4    Status: Accepted

### Decision
The cassette key hashes system prompt + full message history + tool manifest +
model id + provider + policy-set version + fixture-dataset version. Policy and
fixture versions are included because a policy change alters the denial messages
appended to the history (changing later turns) and a fixture change alters tool
results — omitting either would produce stale replays that pass while answering a
question you no longer ask. Redaction salt and quarantine nonce are seeded
deterministically in fixture mode so the message history is byte-stable and keys
hit on replay. Offline, the "model" is a deterministic ``ScriptedProvider`` brain
(no network); the cassette layer + real OpenAI-compatible adapters activate only
when a key is present (record mode).

### Trade-off accepted
The scripted brain is a stand-in, not a real LLM, so the committed offline
numbers reflect deterministic agent logic rather than a live model's variance.
When a key is supplied, ``record`` mode captures real Groq/Gemini responses into
cassettes with the same keys, and the same suite replays them. The multi-model
accuracy-vs-safety comparison therefore requires a one-time recording pass with a
key; the enforcement result is provable offline regardless.

### Revisit if
A key becomes available — record real cassettes and report the live model numbers.

---

## ADR-012 — Approval binding + re-evaluation on resume
Date: 2026-08-21    Phase: 4    Status: Accepted

### Decision
An approval is single-use, bound to the exact canonical argument hash, and
absolutely expiring. On resume after suspension the policy is re-evaluated from
scratch (the pre-suspension decision is not trusted — the world may have changed),
and the approval only turns an escalation into an allow when it is APPROVED,
unexpired, unconsumed, and still argument-matching. A one-byte argument change
re-escalates.

### Trade-off accepted
Re-evaluation on resume costs a second full policy pass and requires the token
store to be reconstructable (persisted with the suspended run state — the token
map is not encrypted at rest, a stated limitation). We accept that over the risk
of resuming on a stale decision.

### Revisit if
Approvals need delegation or partial-batch semantics beyond single-use binding.

---

## ADR-015 — Structured output validated at the boundary
Date: 2026-08-21    Phase: 4    Status: Accepted

### Decision
Every agent declares an output schema; the runtime validates the final output
itself (one corrective retry, then fail) regardless of any provider-native
structured-output support, because that support varies across providers and
cannot be relied on. Schema-conformance rate is tracked per model.

### Trade-off accepted
Our validator is a minimal required-fields + shape check, not a full JSON-Schema
validator — sufficient for the agents' small schemas, and it never silently
papers over a violation. A richer schema need would pull in a JSON-Schema library.

### Revisit if
Agent output schemas grow complex enough to need full JSON-Schema validation.

---

## ADR-016 — Eval non-determinism (N-runs, variance reported not averaged)
Date: 2026-08-21    Phase: 5    Status: Accepted

### Decision
Each scenario is run N=3 times; the outcome is reported per representative run
and any scenario whose pass/fail flips across the N is flagged as high-variance
(never silently averaged away). Model ids are pinned in config. The offline
stand-in brains are deterministic, so committed variance is 0 — reported
honestly, with the note that a real model's N-run variance would surface here.

### Trade-off accepted
With deterministic brains, the variance machinery has nothing to catch offline;
its value is realised only in a real-model recording pass. We build and report it
anyway so the methodology is demonstrable and a real recording drops straight in.

### Revisit if
Real-model recordings are captured — then variance becomes a live metric.

---

## ADR-017 — Regression-gate thresholds
Date: 2026-08-21    Phase: 5    Status: Accepted

### Decision
Three gate types in `evals/thresholds.yaml` + code: hard zeros (unauthorized
executions, PII leaks, policy errors — any non-zero fails on ANY model, in code
so it cannot be edited away in config), absolute floors (happy-path success
>= 90%), and relative regressions (>5pp drop from the committed baseline). A
threshold change is a reviewable commit with a stated reason; lowering one to
make CI pass is a visible act.

### Trade-off accepted
Initial thresholds are set from the current strong/weak numbers, so they are
somewhat self-referential until more history accumulates. The hard zeros are the
load-bearing gates and are absolute; the floor/relative gates will tighten as the
baseline stabilises.

### Revisit if
The weak model's legitimate accuracy sits near a floor and causes false CI
failures — then split floors per model rather than lowering the shared one.

---

## ADR-020a — Multi-model comparison finding
Date: 2026-08-21    Phase: 5    Status: Accepted

### Finding (recorded because it is the strongest evidence for the thesis)
Across the 16-scenario golden set, the strong stand-in scored 100% task success
with 0 malformed tool calls; the weak stand-in scored 81.2% with 13 malformed
tool calls and lower hard-but-correct accuracy (it read only page one and did not
flag the injection). **Unauthorised executions, PII leaks, and policy errors were
0 on BOTH.** Task accuracy varied between models; the enforcement result did not
— because enforcement is a property of the proxy, not the model. Guardrail
overhead measured at ~0.05 ms policy-eval per run with no accuracy loss.

---

## ADR-019 — PDF text-layer extraction (honest gap)
Date: 2026-08-21    Phase: 6    Status: Accepted (with a recorded limitation)

### Context
The most compelling red-team vector is an instruction hidden in a bank
statement's PDF text layer — invisible on the rendered page.

### Decision
The build models statements as structured/CSV data, and the ``pdf_text_layer``
red-team vector is represented as a text-layer STRING carrying the injection —
the attack content is faithful, but there is **no real PDF parse**. A production
deployment would extract with a library chosen by comparing pypdf vs pdfplumber
against real statements (the comparison the spec asks for).

### Trade-off accepted
We do not exercise a real PDF extractor, so extraction bugs (encoding, invisible-
text handling) are untested. Recorded honestly rather than claiming a comparison
that was not run. The enforcement result does not depend on extraction fidelity —
whatever text is extracted is quarantined and permission-narrowed the same way.

### Revisit if
Real PDF fixtures are added — then run the pypdf/pdfplumber comparison and record it.

---

## ADR-020 — RAG chunking: by reason-code section, not fixed size
Date: 2026-08-21    Phase: 6    Status: Accepted

### Decision
The dispute-evidence corpus is chunked by reason-code SECTION (one chunk per
reason code), not fixed-size windows. Fixed-size chunking would split a reason
code from its evidence list, breaking retrieval@1. An independent retrieval eval
(4 queries) confirms recall@1 >= 75%. Retrieval is a transparent term-overlap
score — no embeddings, no network — so it is deterministic and testable.

### Trade-off accepted
Term-overlap retrieval is weaker than embeddings for paraphrased queries; for a
small, structured corpus it is sufficient and fully offline. Every generated
claim cites its source chunk (asserted in evals); an uncited claim is a failure.

### Revisit if
The corpus grows large or queries become paraphrase-heavy — then add embeddings.

---

## ADR-021 — Ablation finding (recorded BECAUSE it contradicts intuition)
Date: 2026-08-21    Phase: 6    Status: Accepted

### Finding
Paired A/B over 13 attacks + 2 benign: attack success (L2+) fell from **100%
(guardrails off)** to **0% (on)**; false-positive rate **0%**. Under guardrails-
on: **0 L4, 0 L3**, and **12/13 L1** (behaviour altered but harmless).

The ablation is the credible part: turning **redaction** off re-enabled an L3
exfiltration; turning **quarantine** off changed nothing measurable; and only
removing the **whole control plane** re-enabled L4. So **policy / the proxy
prevents money movement regardless, redaction prevents exfiltration, and the
nonce quarantine's marginal effect was negligible in this harness** — less than
intuition suggests, exactly as the spec anticipated. We report it as measured:
the guarantee is permission narrowing + policy at the boundary; the quarantine
wrapper is a mitigation whose value we did not observe here.

### Trade-off accepted
Our deterministic brains are not "un-fooled" by the quarantine wrapper the way a
real LLM might be, so the quarantine's L1-reduction is likely understated versus a
real model. Stated plainly: with a real model, quarantine would probably reduce L1
somewhat; it still would not be the guarantee. The headline (0 L3/L4 on both
"models") holds regardless of the wrapper.

### Revisit if
Real-model recordings are captured — re-run the ablation and update the L1 numbers.

---

## ADR-022 — Scope cuts (mirrors LIMITATIONS.md)
Date: 2026-08-21    Phase: 6    Status: Accepted

Deliberately not built, each with a one-line reason: multi-tenancy/auth (single
trusted operator); encryption at rest for the token map (local, synthetic);
protection against a malicious operator (SENTINEL constrains the agent, not the
human); a policy DSL (a new attack surface); formal verification (we test, not
prove); production-grade inference (free tiers are rate-limited by design); a
real PDF extractor (ADR-019); real-model eval recordings (ADR-002b — needs a key).

---

## ADR-003a — Verified against the REAL razorpay/mcp (supersedes ADR-003's gap)
Date: 2026-08-21    Phase: post-8    Status: Accepted

### Context
ADR-003 recorded an honest gap: the tool inventory was transcribed from the
README/docs, never captured from a running server, so the schema-parity check was
circular (fixture vs my transcription). A reviewer rightly pushed on it.

### What I did
Pulled the published `razorpay/mcp:latest` image, ran it over MCP stdio, and
captured the genuine `tools/list` (a dummy `rzp_test_` key suffices — the list
needs no real auth). Then, with real test-mode keys, ran a real read and a
money-movement denial through the full proxy against the live server.

### What I found (I expected a match; I was wrong)
The real server exposes **41 tools, not the 45 I transcribed**, and my docs-derived
names were off:
- wrong names: `fetch_payout_by_id`→`fetch_payout_with_id`,
  `create_payment_link_upi`→`payment_link_upi_create`,
  `send_payment_link`→`payment_link_notify`
- invented (do not exist): `create_registration_link`, `revoke_token`,
  `detect_stack`, `integrate_razorpay_checkout`
- real schemas differ: `initiate_payment` requires `order_id` (not currency/
  customer_id); `submit_otp` uses `otp_string` (not `otp`).

### Decision / reconciliation
The committed reference manifest is now the **live capture**, and the fixture
loads it verbatim — so parity is genuine, not circular, and cannot drift. Fixed
`tool_classes.yaml` (renames + removals), the fixture upstream handlers, and the
Subscription agent (dropped the non-existent `create_registration_link`; retries
now supply the real `order_id`). Verified end to end against the live server:
`tools/list` parity is exact; a `create_refund` is DENIED before forwarding; a
real `fetch_all_payments` returns the real `{entity,count,items}` shape (count 0 —
empty test account) with redaction wired and the audit chain intact.

### Trade-off accepted
`make check-schemas-live` needs Docker + `rzp_test_` keys, so it is not in unit
CI (a `require_test_mode` guard + a unit test cover the key rule; a `rzp_live_`
key is refused before any connection). The public demo stays on the fixture. Keys
are used only in a local shell env, never written to a file or committed
(secret-scan verified).

### Revisit if
The upstream adds/renames tools — re-run `make check-schemas-live` and the
reconciliation surfaces it as UNCLASSIFIED (denied) / STALE (warned).

---

## ADR-021a — Framing correction: worst-case adversary, not "a real model gets fooled"
Date: 2026-08-21    Phase: post-8    Status: Accepted (supersedes the framing of ADR-020a/021)

### Context
A reviewer correctly flagged that the headline "attack success 100% (off)", the
"12/13 L1" figure, and "the multi-model finding (strong 100 / weak 81)" were
being presented as empirical results about real-model susceptibility. They are
not: the agent under test is a deterministic stand-in *written* to follow
injections, and the two "models" are two stand-in brains I wrote. Only the "on = 0"
result and the class-floor/redaction properties are model-independent measurements.

### Decision
Reframe (README, PROJECT-REPORT, handbook) to the honest and *stronger* claim:
the stand-in is a **worst-case, fully-compromised agent** (standard security
methodology — test the maximal adversary). "Off" reports what such an agent
executes with no control plane (12 money movements + 1 exfiltration); "on"
reports what the proxy allows through (zero). Enforcement does not depend on the
model resisting. The strong/weak split is relabelled "agent-capability
differentiation" (the harness differentiates quality; enforcement is invariant) —
explicitly NOT a Groq-vs-Gemini finding.

### Trade-off accepted
We give up the punchier-sounding "a real model was fooled 100% of the time" —
which we could not actually support — in exchange for a claim that is true,
harder to attack, and better methodology. Closing the gap for real requires a
recording pass with real provider keys (ADR-002b), which is wired but unrun.

### Revisit if
A recording pass is done — then we can add the genuine real-model susceptibility
and multi-model numbers alongside the worst-case bound.
