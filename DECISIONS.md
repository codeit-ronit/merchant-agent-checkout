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

