# SENTINEL — Specification Pack

> A policy enforcement, audit, and evaluation control plane for LLM agents that operate on payment infrastructure.

## What this pack is

This is a **specification pack**, not a codebase and not a tutorial. It is written to be handed to an autonomous coding agent (Claude Code, Opus 5) which will do the implementation.

Every document here answers three questions in order:

1. **What is currently true** — the state of the world this component exists in.
2. **What problem we are solving** — stated precisely enough to know when it is solved.
3. **How we proceed** — the decisions, constraints, and acceptance criteria. Not the code.

The pack deliberately does **not** contain implementation code. Library versions move, APIs change, and a spec that hardcodes a function signature rots the day it is written. Instead, each document contains **RESEARCH FIRST** blocks listing exactly what must be verified against live documentation before that component is built.

## Reading order

| # | Document | Read when |
|---|---|---|
| 01 | `01-CONTEXT-AND-PROBLEM.md` | Before anything. Explains why SENTINEL exists. |
| 02 | `02-ARCHITECTURE.md` | Before any code. The single most important file. |
| 03 | `03-DATA-CONTRACTS.md` | Before Phase 1. Defines every object that crosses a boundary. |
| 04 | `04-POLICY-ENGINE.md` | Phase 3 |
| 05 | `05-AUDIT-AND-REDACTION.md` | Phase 3–4 |
| 06 | `06-AGENT-RUNTIME.md` | Phase 1 |
| 07 | `07-AGENTS.md` | Phase 2, 6 |
| 08 | `08-EVAL-HARNESS.md` | Phase 5 |
| 09 | `09-REDTEAM.md` | Phase 6 |
| 10 | `10-FRONTEND.md` | Phase 7 |
| 11 | `11-BUILD-ORDER.md` | **Read after 02. This drives the whole build.** |
| 12 | `12-TESTING-AND-CI.md` | Continuously |
| 13 | `13-DEMO-AND-INTERVIEW.md` | Phase 8, and before any interview |
| 14 | `14-ADR-LOG.md` | Continuously — append as decisions are made |
| — | `CLAUDE.md` | Copy into the repo root. Governs agent behaviour during the build. |
| — | `FINAL-PROMPT.md` | The kickoff prompt. |

## The one-sentence version

> Prompt-level guardrails are advisory. SENTINEL makes them mandatory by moving enforcement to the tool-call boundary, then proves the enforcement works with a reproducible evaluation and red-team harness.

## Non-negotiable rules for the whole project

These are repeated in `CLAUDE.md` because they are the rules most likely to be violated under time pressure.

1. **Test mode only.** Razorpay test-mode API keys (`rzp_test_*`). Never live keys. Never real merchant data. This is stated in the README, the UI, and the repo description.
2. **Fail closed.** Any unknown tool, unparseable argument, missing policy, or evaluation error results in `DENY`. Never `ALLOW` by default, never `ALLOW` on exception.
3. **No hardcoded tool lists.** Tool inventories are discovered by introspecting the MCP server at runtime and classified against a config file. A tool that appears in the server but not in the config is treated as maximally dangerous until a human classifies it.
4. **Everything is a decision with a reason.** Every allow, deny, and approval request carries a machine-readable reason code and a human-readable explanation. "Blocked" without a reason is a bug.
5. **Determinism where it matters.** Evaluations must run against fixtures, not the network. A benchmark that produces different numbers on every run is not a benchmark.
6. **No affiliation claims.** This is an independent open-source project that integrates with a publicly published open-source MCP server. It is not affiliated with, endorsed by, or produced by Razorpay. Say so in the README.
7. **Document the limitations.** The README must contain a section that honestly lists what does not work, what was cut, and what would need to change for production use. This is a feature of the project, not an admission.

## What "done" looks like

A reviewer can, in under ten minutes:

- Clone the repo, run one command, and see the system running against fixtures.
- Watch an agent attempt a money-moving action and be stopped by a policy it can read.
- Watch a prompt-injection payload succeed with guardrails off and fail with guardrails on, with the difference quantified.
- Open a dashboard showing accuracy, p50/p95 latency, and cost per run across the last N commits.
- Read a `DECISIONS.md` explaining why each major choice was made.
