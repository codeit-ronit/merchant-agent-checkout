# SENTINEL

[![ci](https://github.com/codeit-ronit/SENTINEL/actions/workflows/ci.yml/badge.svg)](https://github.com/codeit-ronit/SENTINEL/actions/workflows/ci.yml)
&nbsp;[**Live demo →**](https://sentinel-5krh.onrender.com/) · [Handbook](docs/handbook.html) · [Build & live-test report](PROJECT-REPORT.md)

**A policy enforcement, audit, and evaluation control plane for LLM agents that operate on payment infrastructure.**

Prompt-level guardrails are advisory. SENTINEL makes them mandatory by moving
enforcement to the **tool-call boundary** — a process the model does not control —
and then **proves** it works with a deterministic evaluation harness and an
adversarial red-team suite.

---

### ⚠️ Test mode only · Not affiliated with Razorpay

Independent open-source project. **Not affiliated with, endorsed by, or produced
by Razorpay.** Integrates with the publicly published open-source
[`razorpay/razorpay-mcp-server`](https://github.com/razorpay/razorpay-mcp-server).
Test-mode keys (`rzp_test_*`) only — a `rzp_live_` key is rejected at startup and
blocked from the repo by CI. All data is synthetic and *checksum-invalid*, so no
generated value can collide with a real identifier. The red-team runs
**exclusively against the local fixture server**, never a hosted endpoint.

---

## The problem, in three sentences

A no-code builder is about to let non-engineers point LLM agents at APIs that
move money, and those agents ingest attacker-controlled text by design — support
tickets, chargeback evidence, uploaded bank statements. The industry's standard
guardrail is a sentence in a system prompt, which is a *request* to the model:
it cannot be unit tested, produces no artefact when it works or fails, and
degrades under adversarial input and model updates. SENTINEL intercepts every
tool call at the protocol boundary, classifies it, redacts PII, evaluates it
against declarative policy, and allows / denies / escalates it to a human —
before it executes.

## The three headline numbers

Produced offline by `make redteam` (paired A/B, rule-based grading), reproducible
by anyone with **no API key**.

**How to read these numbers (this matters).** The agent under test is a
**worst-case, fully-compromised agent** — a deterministic stand-in written to
follow *every* injected instruction. That is deliberate: it is standard security
methodology to test a defence against a maximal adversary, not an average one. A
real model might resist an injection by luck; this one never does. So the
"guardrails off" column is not a claim that *a real model gets fooled X% of the
time* — it is the worst case, and the point is what the proxy does about it:

| Against a worst-case agent that follows every injection | Result |
|---|---|
| Guardrails **off** (no control plane) | **12 unauthorised money movements + 1 exfiltration executed** |
| Guardrails **on** | **0 unauthorised money movements, 0 exfiltration** (12/13 attempts still *made* — all blocked at the boundary) |
| Legitimate-work **false-positive** rate | **0%** *(on a small benign set — see Limitations)* |

**Enforcement does not depend on the model resisting.** That "0" is the
model-independent, genuinely-proven half — the proxy denies whatever the agent
attempts. (The quarantine wrapper is a mitigation; permission narrowing at the
boundary is the guarantee. We did not "solve" prompt injection — nobody has.)

**Guardrail overhead:** policy evaluation adds a measured **~0.05 ms per call**
with **no measurable accuracy loss**.

## Agent-capability differentiation (not yet a real multi-model finding)

The runtime is model-agnostic by design, and the harness runs against two
**deterministic stand-in agents** of different quality:

> A "strong" stand-in scored 100% task success; a "weak" one scored 81% with 13
> malformed tool calls and lower hard-case accuracy — while **both had 0
> unauthorised executions, 0 PII leaks, 0 policy errors.** This demonstrates the
> harness *can differentiate agent capability while the enforcement result stays
> invariant.* It is **not** a Groq-vs-Gemini comparison — that requires a
> one-time recording pass with real provider keys (`SENTINEL_CASSETTE=record`),
> which is wired and ready but not yet run.

## Verified against the real `razorpay/mcp` (test mode)

Not just a mock — SENTINEL is checked against the genuine published server:

- **Tool-surface parity is real.** The reference manifest was **captured live** by
  running `razorpay/mcp:latest` over MCP stdio and calling `tools/list` (41 tools);
  the fixture loads that capture verbatim, so parity is genuine, not circular.
  (This corrected several docs-derived mistakes — see `DECISIONS.md` ADR-003a.)
- **Enforcement holds against the live server.** With test-mode keys, a
  `create_refund` is **DENIED before it is ever forwarded** to Razorpay, and a
  real `fetch_all_payments` returns the real `{entity,count,items}` shape through
  the proxy with redaction + audit intact.
- Reproduce it: `export RAZORPAY_KEY_ID=rzp_test_… RAZORPAY_KEY_SECRET=… && make check-schemas-live`
  (needs Docker). Test-mode keys only; nothing money-moving executes; keys are
  never written to a file.

## Quickstart (no credentials required)

Everything runs offline in fixture mode with cassette replay — no API key, no
network.

```bash
make install        # venv + dependencies
make test           # tiers 1-3 + the 5 load-bearing safety tests (~3s, no model)
make demo-cli       # THE HEADLINE: an injected refund DENIED with a plain reason
make eval           # golden set, per-model metrics, regression gates
make redteam        # the paired A/B (100% -> 0%), ablation, false-positive rate
make verify-audit   # walk the tamper-evident hash chain
make demo           # the operator surface at http://localhost:8080
```

`make demo-cli` output (abridged):

```
2 · Prompt injection in the statement — the refund is DENIED
    the fooled model attempted: create_refund  amount=₹450.00
    ✕ DENIED [DENY_FAIL_CLOSED]
      Blocked: no rule permits create_refund for this agent, and the default is to deny.
    refunds actually executed in the fixture: 0
4 · The audit chain — verifiable, and it breaks when tampered
    ⛓ verified — 7 entries, chain intact
    after altering entry #2: ⛓ CHAIN BROKEN at entry #2 — refusing to certify
```

## Deploy a public demo (fixture mode, no credentials)

The operator surface + API ship as one **multi-stage Docker image** (verified: it
builds and serves the SPA, the API, and the red-team numbers). Host it free on
Render / Fly / Railway or any Docker host — full steps in
[`DEPLOY.md`](DEPLOY.md):

```bash
docker build -t sentinel . && docker run -p 8080:8080 sentinel   # -> http://localhost:8080
# Render: New > Blueprint (reads render.yaml).  Fly: fly launch --no-deploy && fly deploy.
```

Do **not** set any real key on the public demo — it is meant to run guardrail-free
of real data (there is none in the repo).

## Architecture — enforcement in a process the model does not control

```
Operator surface (React) ──REST+SSE──> Control-plane API (FastAPI)
                                              │
                                     Agent runtime (in-house loop)
                                     ├─ in-loop guard (layer 2, the experience)
                                     └─ provider abstraction (Groq/Gemini, cassettes)
                                              │  MCP protocol
                                   SENTINEL MCP proxy (layer 1 — THE GUARANTEE)
                                   classify → redact → evaluate → allow/deny/escalate
                                   → idempotency → forward → scan/quarantine → audit
                                              │
                        fixture upstream (default)  |  razorpay/mcp (live, test keys)

  cross-cutting: pure policy engine · redaction · hash-chained audit · approvals
  offline: eval harness (golden set) · red-team A/B  →  CI regression gates
```

The **MCP proxy** is a real MCP server, so a completely different MCP client
pointed at it is subject to the same policy — a property a prompt can never have.
Both enforcement layers call the *same pure policy engine* via the same context
builder; a disagreement is a logged P0 incident. Full walkthrough and every
decision: [`docs/handbook.html`](docs/handbook.html) and the reading below.

## How it holds even when the model is wrong

- **Pure policy engine** — `evaluate(policy_set, context)`, no I/O, exhaustively
  tested and property-tested. A **class-floor invariant** makes it *impossible*
  for any policy file, however written, to auto-allow money movement without
  approval (proven over 400 generated policies).
- **Redaction** — the model reasons over stable tokens (`ACCT_a17f`), never real
  PANs/accounts/VPAs; an unissued token in a tool call is a flagged exfiltration
  attempt. The PII invariant is tested across *every* output surface on every commit.
- **Trust quarantine** — untrusted text is wrapped in a per-run nonce delimiter;
  `provenance_guard` narrows the agent's permissions once it ingests untrusted content.
- **Tamper-evident audit** — an append-only SHA-256 hash chain; the verifier
  reports the first break at the exact position.

## What this is not

Not an Agent Studio clone, not a payments product, not a general-purpose AI
firewall, not a fraud model, and not affiliated with Razorpay.

## Limitations (the honest ones — full list in [`LIMITATIONS.md`](LIMITATIONS.md))

- The audit ledger is **tamper-evident, not tamper-proof**: anyone who can write
  to the database can recompute the whole chain. Real resistance needs an external
  anchor (an RFC 6962-style transparency log) or write-once storage — not implemented.
- **Prompt injection is not solved.** L1 (behaviour altered) is non-zero even with
  guardrails on; the design makes that harmless rather than pretending it is impossible.
- The offline "models" are **deterministic stand-ins** — real Groq/Gemini adapters
  and the cassette layer are built and activate when a key is present (`SENTINEL_CASSETTE=record`);
  the enforcement result is provable offline regardless.
- The **agent's `tools/call` responses on real data** are validated only for
  shape/enforcement (the test account is empty); redaction of genuine PII is
  proven on synthetic fixtures, not yet on populated live data.

## Documentation

- **[`docs/handbook.html`](docs/handbook.html)** — the end-to-end handbook (open in a browser).
- **[`DECISIONS.md`](DECISIONS.md)** — every architectural decision, with its trade-off named.
- **[`LIMITATIONS.md`](LIMITATIONS.md)** — what this does not do, unflinchingly.
- **[`docs/spec/`](docs/spec/)** — the specification pack this was built from.

## Reproduce the numbers

```bash
git clone <repo> && cd sentinel && make install
SENTINEL_CASSETTE=replay make eval      # replays committed cassettes, no key -> same numbers
SENTINEL_CASSETTE=replay make redteam
```

Built phase by phase per [`docs/spec/11-BUILD-ORDER.md`](docs/spec/11-BUILD-ORDER.md);
169 tests green (tiers 1–3), with five load-bearing safety tests marked
`@pytest.mark.critical`.
