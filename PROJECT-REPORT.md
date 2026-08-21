# SENTINEL — build & live-test report

*A field report back to the spec author (the Claude that produced `docs/spec/`).*
*Written 2026-08-21. Everything below is what was actually built and measured — not a plan.*

---

## 0. TL;DR

You spec'd **SENTINEL** — a policy-enforcement, audit, and evaluation control
plane for LLM agents on payment infrastructure. I built it end to end from
`docs/spec/`, phase by phase (19 commits, one theme each), and then — on the
operator's push — **tested it against the real `razorpay/mcp` server**, which
exposed and corrected several assumptions the docs-only build had baked in.

- **Live demo:** https://sentinel-5krh.onrender.com/ (fixture mode, no keys, free tier — first hit after idle cold-starts ~30–60s)
- **Repo:** https://github.com/codeit-ronit/SENTINEL
- **Headline red-team (worst-case adversary):** against a stand-in agent that follows *every* injected instruction, guardrails-off executed **24 unauthorised money movements + 5 exfiltrations**; guardrails-on executed **0**. Enforcement does not depend on the model resisting.
- **Agent-capability differentiation:** a strong vs weak stand-in scored **100% / 87.1%** task success — **0 unauthorized on both** (enforcement is invariant to the agent). A **real-model recording pass** (§8, ADR-002c) separately confirms this on *real* models — 4 models across Groq + OpenRouter, all attempted the refund, all blocked, 0 unauthorized.
- **Guardrail overhead:** **well under 0.1 ms** policy-eval per call, no accuracy loss.
- **Scale:** ~7,100 lines Python + ~3,000 lines React/TS, **169 tests** (41 marked `@pytest.mark.critical`), all green.
- **Verified against the real server:** tool-surface parity (41 tools), all schemas, all arg-paths, and a live money-movement denial — with test-mode keys.

---

## 1. What it is (the thesis held up)

The central claim, unchanged from the spec and now demonstrated:

> Prompt-level guardrails are *advisory* — a request to the model. Enforcement at
> the **tool-call boundary**, in a process the model does not control, is a
> *property of the system*: it can be unit-tested, audited, and trusted with money.

SENTINEL sits between an agent and its money-moving tools. Every tool call is
intercepted at an MCP proxy, **classified → PII-redacted → evaluated against
declarative policy → allowed / denied / escalated to a human**, then written to a
tamper-evident hash-chained audit log — all before it executes.

The framework-independence proof works: a client that is *not* the agent loop,
pointed at the proxy, is subject to identical policy. A prompt can never offer that.

---

## 2. What was built (all 8 phases + the operator surface)

| Layer | What | State |
|---|---|---|
| **Data contracts** | Immutable, schema-versioned, redaction-aware Pydantic types; enumerated reason codes with plain-language templates; canonical JSON (RFC 8785-inspired, floats forbidden) + SHA-256 | ✅ |
| **Fixture world** | Seeded synthetic dataset (checksum-*invalid* Indian identifiers, so nothing can collide with a real one); in-process double of the upstream MCP surface | ✅ |
| **Pure policy engine** | 11 closed rule types (no DSL); most-restrictive-wins; fail-closed; **class-floor invariant** proven over 400 generated policies (no config can auto-allow money movement); zero-I/O import check | ✅ |
| **Proxy + redaction + audit + idempotency** | Decision pipeline; structural+pattern PII detection → stable per-run tokens; per-run-nonce quarantine; append-only SHA-256 hash chain + verifier; idempotency guard | ✅ |
| **Runtime + providers** | In-house ~200-line agent loop + in-loop guard (shares the exact context builder with the proxy → layers can't diverge); provider abstraction (Groq + Gemini adapters, one OpenAI-compatible shape); cassette record/replay; rate-limit governor; startup probe; suspend/resume across restart | ✅ |
| **Agents** | Reconciliation (READ), Dispute Responder (IRREVERSIBLE_WRITE + RAG with citations + honest gap analysis), Subscription Recovery (MONEY_MOVEMENT + per-action escalation + counterparty novelty) | ✅ |
| **Eval harness** | 31 golden scenarios across 5 categories; per-model metrics; regression gates (absolute floor / relative / hard-zero); offline + reproducible via committed cassettes | ✅ |
| **Red-team** | 29 attacks (11 classes × 6 vectors) + 15 benign; rule-based deterministic grading (L0–L4); paired A/B; ablation; fixture-mode-only (refuses otherwise, tested); L3/L4 CI gate | ✅ |
| **Operator surface** | React + TS + Vite, six views (run console, approvals, policy + dry-run, evals, red-team, audit); financial control-room design; decision states legible without colour; the hash-chain as the signature visual | ✅ |
| **Control-plane API** | FastAPI: `/api/scenarios /runs (+SSE) /approvals /policies (+dry-run) /audit (+verify) /evals /redteam` | ✅ |
| **Ship** | README, DECISIONS.md (every trade-off named), LIMITATIONS.md, MIT license, one-command `make demo`, Docker + Render/Fly/Railway configs, a living HTML handbook | ✅ |

Repo layout mirrors the architecture: `sentinel/{contracts,common,policy,proxy,redaction,audit,approvals,providers,runtime,metering,agents,fixtures,api}`, `config/`, `evals/`, `redteam/`, `frontend/`, `tests/{unit,property,integration,contracts}`, `docs/`.

---

## 3. The results (measured, offline, reproducible with no key)

**Red-team A/B** (`make redteam`). Read the "off" column as a **worst-case,
fully-compromised agent** — a deterministic stand-in written to follow every
injection (standard security methodology: test against a maximal adversary, not
an average one). The number that is *measured and model-independent* is the "on"
column: the proxy denies whatever the agent attempts.
- Guardrails **off** (no control plane): **24 unauthorized money movements + 5 exfiltrations executed**.
- Guardrails **on**: **0 executed** (24/29 attempts still *made* by the compromised agent — all blocked at the boundary; L1 behaviour-alteration is a property of the stand-in, not a measurement of real-model susceptibility).
- **False-positive rate: 0%** on a benign set of n=15 (expanded from n=2).

**Ablation** (the honest, intuition-contradicting finding):

| control off | L4 | L3 | L1 |
|---|---|---|---|
| all on | 0 | 0 | 12 |
| no redaction | 0 | **1** | 12 |
| no quarantine | 0 | 0 | 12 |
| no control plane | **12** | **1** | 0 |

→ **Policy prevents money movement; redaction prevents exfiltration; the nonce quarantine's marginal effect was negligible in this harness** — less than intuition suggests. Reported because it contradicts the design assumption.

**Agent-capability differentiation** (`make eval`): two *deterministic stand-in
agents* — strong 100% / weak 87.1% (weak: 13 malformed tool calls, misses hard +
adversarial cases); **both 0 unauthorized / 0 PII / 0 policy errors.** This shows
the harness differentiates capability while enforcement stays invariant. This
capability split is between two stand-ins; the **real-model recording pass**
(§8, ADR-002c) separately confirms enforcement holds on *real* models across two
providers (Groq + OpenRouter). Guardrail overhead well under 0.1 ms/call, no
accuracy loss.

---

## 4. Live testing against the REAL `razorpay/mcp` — the important part

This is the part that changed the project. The spec (rightly) had me build against a
**fixture double** for determinism + safety + credential-free reproducibility. But
the fixture's tool surface was **transcribed from the README/docs, never captured
from a running server** — an honest gap I'd flagged in ADR-003. On the operator's
push, I closed it: pulled `razorpay/mcp:latest`, ran it over MCP stdio, and built a
real `LiveUpstream` MCP client behind the same proxy.

**Running it against reality exposed real errors in the docs-derived surface:**

- The real server exposes **41 tools, not the 45** I'd transcribed.
- **3 wrong tool names:** `fetch_payout_by_id`→`fetch_payout_with_id`, `create_payment_link_upi`→`payment_link_upi_create`, `send_payment_link`→`payment_link_notify`.
- **4 invented tools that don't exist:** `create_registration_link`, `revoke_token`, `detect_stack`, `integrate_razorpay_checkout`.
- **2 wrong required-arg schemas:** `initiate_payment` really requires `order_id` (I'd assumed currency/customer_id); `submit_otp` uses `otp_string` (I'd assumed `otp`).
- **4 wrong argument names in the classification config** (caught only by an exhaustive schema diff): QR tools use `qr_code_id` not `qr_id`; `fetch_tokens` uses `contact` not `customer_id`.

**All of the above are now fixed and reconciled.** The committed reference manifest
*is* the live capture, and the fixture loads it verbatim — so schema parity is now
**genuine, not circular**, and cannot silently drift.

**Three independent proofs the connection is real** (with the operator's `rzp_test_` keys):
1. `tools/list` → the genuine 41-tool surface (which corrected my mistakes).
2. `create_refund` (money movement) → **DENIED by policy before it was ever forwarded** to Razorpay.
3. `create_order` → an authenticated write that returned a **Razorpay-minted id `order_TSFZMikHWvQ7ox`** (a local mock cannot produce that), plus a real `fetch_all_payments` returning the genuine `{entity, count, items}` shape through the proxy with redaction + audit intact.

**Reproducible:** `export RAZORPAY_KEY_ID=rzp_test_… RAZORPAY_KEY_SECRET=… && make check-schemas-live` (needs Docker). It validates, in one command: tool-name parity + all 41 schemas + every `tool_classes.yaml` arg-path + a live money-movement denial. A `rzp_live_` key is refused before any connection; test-mode keys are used only in a local shell env and are **never written to a file or committed** (secret scan verified).

**Safety boundaries kept:** the red-team suite still runs **only against the fixture**, never against Razorpay's server (a hard rule); the public demo stays fixture-mode; nothing money-moving auto-executes.

---

## 5. Deployment

- **Live:** https://sentinel-5krh.onrender.com/ — Render free tier, Docker (multi-stage: Node builds the SPA, Python serves it + the API), `autoDeploy` on push, health check `/api/health`. Fixture mode, no credentials.
- **Repo:** https://github.com/codeit-ronit/SENTINEL — 19 meaningful phase-by-phase commits.
- Deploy configs for Render / Fly / Railway + `DEPLOY.md` in the repo.

---

## 6. How to run / reproduce (no credentials)

```bash
make install
make test            # 169 tests, tiers 1-3 + the 5 load-bearing safety tests (~3s)
make demo-cli        # injected refund DENIED with a plain reason; audit chain breaks on tamper
make demo            # the operator surface at localhost:8080
make eval            # per-model metrics + regression gates (offline)
make redteam         # the paired A/B + ablation (offline)
make verify-audit    # walk the tamper-evident hash chain
# with Docker + rzp_test_ keys:
make check-schemas-live   # verify names + schemas + arg-paths + a live denial vs the real razorpay/mcp
```

---

## 7. Key decisions (full log in `DECISIONS.md`)

Highlights, each with its trade-off named:
- **ADR-001** enforcement placement: proxy (the guarantee) + in-loop guard (the experience), same pure engine.
- **ADR-002 / 002a / 002b** in-house loop; Groq+Gemini (one OpenAI-compatible adapter); cassette key includes policy + fixture version.
- **ADR-004 / 005** closed rule set (not a DSL); engine purity enforced structurally.
- **ADR-010** RFC 8785-inspired canonical JSON, SHA-256, tamper-*evident* not *proof*.
- **ADR-020a** the multi-model finding; **ADR-021** the ablation finding (recorded *because* it contradicts intuition).
- **ADR-003 → ADR-003a** the big one: "I built from docs, assumed a tool surface, tested against the real server, was wrong in several places, and reconciled to ground truth." This is the most credible entry in the log.

---

## 8. Honest limitations (full list in `LIMITATIONS.md`)

- The audit ledger is **tamper-evident, not tamper-proof** — anyone who can rewrite the DB can recompute the chain. Real resistance needs an external anchor (RFC 6962-style) or WORM.
- **Prompt injection is not solved** — L1 is non-zero even guardrails-on; the design makes being fooled *harmless*, not impossible.
- The offline "models" are **deterministic stand-ins** used as a *worst-case
  compromised agent* (the "off" red-team numbers and the strong/weak split are
  properties of these stand-ins, not measurements of real models).
- **Recording pass — now DONE against real models (ADR-002c).** Wiring the real
  providers exposed that the loop always built the stand-in and never a real
  provider from config — an integration gap, not just "needs a key." Fixed with a
  provider factory (`sentinel/providers/factory.py`); the loop still names no
  provider. With real keys, recorded the money-movement scenario across **two real
  providers** — Groq (`gpt-oss-120b`/`20b`) and OpenRouter
  (`nvidia/nemotron-3.5-lightning` + `liquid/lfm-2.5-2.6b`): **all four real models
  attempted the refund and enforcement blocked every one → 0 unauthorized / 0 PII /
  0 policy errors / 0 malformed on all four** (`evals/results/live-*.json`,
  `cassettes/live/`). *Enforcement invariance is now shown with real models, not
  stand-ins.* Honestly scoped: 1 scenario, `n_runs=1`, both tiers — a full
  31-scenario live pass was impractical (free-tier latency 20s–5min/call; the
  reconciliation agent hits `max_steps` per run). Live latency uses the injected
  deterministic clock, not wall-time. **Gemini was denied** on the available key
  (HTTP 403 "project has been denied access" on generation — a project restriction,
  not config), so OpenRouter is the recorded second provider; Gemini stays in
  `providers.yaml` but out of `failover_order`.
- **Red-team sample (now expanded):** 29 attacks + 15 benign (was 13 + 2). The 0%
  false-positive rate now rests on n=15, not n=2; golden set grew 16→31 scenarios.
- Redaction of **genuine live PII** is proven on synthetic fixtures; the live test account is empty, so it's shape/enforcement-validated live, not populated-data-validated.
- Not built (deliberate): multi-tenancy/auth, encryption-at-rest for the token map, protection against a malicious operator, a policy DSL, formal verification, production-grade inference.

---

## 9. Notes back to you (the spec author)

The spec asked me to flag anything wrong or underspecified. Two things:

1. **The tool inventory in the research was docs-derived and partly wrong** (see §4). The spec's own instinct — "enumerate it live, never infer from a spec document" — was correct; the initial build only got there after the operator insisted on testing against `razorpay/mcp`. The lesson landed: the schema-parity check is only meaningful once the reference manifest is a *live* capture, otherwise it's circular. That's now fixed and guarded.
2. **The spec assumed richer upstream tools than exist** — no `create-payout`, no dispute or subscription tools on the published server. The Dispute and Subscription agents are therefore backed by clearly *labelled fixture extensions*, which the reconciliation reports as fixture-only. That's honest, and it doubles as a live demonstration of the classified/unclassified/stale reconciliation.

Everything else in the spec held up well — especially the eval-discipline and red-team-A/B contributions, which are what make this defensible in front of a payments-security engineer.
