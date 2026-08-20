# SENTINEL

**A policy enforcement, audit, and evaluation control plane for LLM agents that operate on payment infrastructure.**

> Prompt-level guardrails are advisory. SENTINEL makes them mandatory by moving
> enforcement to the tool-call boundary — in a process the model does not
> control — then proves the enforcement works with a reproducible evaluation and
> red-team harness.

---

### ⚠️ Test mode only · Not affiliated with Razorpay

This is an **independent open-source project**. It is **not affiliated with,
endorsed by, or produced by Razorpay**. It integrates with the publicly
published open-source [`razorpay/razorpay-mcp-server`](https://github.com/razorpay/razorpay-mcp-server).

- **Test-mode keys only** (`rzp_test_*`). Never live keys. A key beginning
  `rzp_live_` is rejected at startup and blocked from the repo by CI.
- **Synthetic data only.** Every merchant, customer, PAN, IFSC, VPA, and bank
  statement is generated to be *format-valid but checksum-invalid*, so no
  generated value can collide with a real identifier.
- The red-team suite runs **exclusively against the local fixture server** —
  never against Razorpay's hosted infrastructure.

---

## Quickstart (no credentials required)

The demo, tests, evals, and red-team all run **offline** in fixture mode with
cassette replay — no API key, no network.

```bash
make install        # create venv, install deps
make test           # tiers 1-3: fast, deterministic, no model
make demo-cli       # the headline: a money-movement call denied with a plain reason
make verify-audit   # walk and verify the tamper-evident hash chain
make eval           # golden eval set with regression gates (offline)
make redteam        # paired A/B red-team suite (offline)
```

## The central idea

Enforcement lives in three places; only two of them are real:

| Placement | Strength |
|---|---|
| System prompt | Advisory — a *request* to the model. Untestable. |
| In the agent loop | Strong — runs in our process, but shares it with attacker-influenced content. |
| **MCP proxy between agent and tools** | **Strongest — protocol-level, framework-independent, fails closed.** |

SENTINEL implements the proxy (the guarantee) and the in-loop guard (the
experience), and treats the prompt as documentation. Both call the *same pure
policy engine*. A third-party MCP client pointed at the proxy is subject to
identical policy — which is not true of any prompt.

## Headline numbers

_Filled in at Phase 8 from the committed eval and red-team artefacts:_

- Attack success rate — guardrails **off**: `A%`
- Attack success rate — guardrails **on**: `B%`
- Legitimate-work **false-positive** rate: `C%`
- Guardrail overhead: added p95 latency `X ms`, `Y%` of run cost.

## Documentation

- [`DECISIONS.md`](DECISIONS.md) — every architectural decision, with its trade-off named.
- [`LIMITATIONS.md`](LIMITATIONS.md) — what this does not do, unflinchingly.
- [`docs/spec/`](docs/spec/) — the full specification pack this was built from.

## What this is not

Not an Agent Studio clone, not a payments product, not a general-purpose AI
firewall, not a fraud model, and not affiliated with Razorpay.

## Build status

Built phase by phase per [`docs/spec/11-BUILD-ORDER.md`](docs/spec/11-BUILD-ORDER.md).
See `DECISIONS.md` for the current state.
