# 01 — Context and Problem

## 1. What is currently true

### The agentic payments landscape (as of August 2026)

Razorpay — India's largest payment aggregator, processing $180B+ annualised — has shipped three things in rapid succession:

**Agent Studio (March 2026).** A B2B marketplace and builder platform for payment agents, built on Anthropic's Claude Agent SDK. Launch agents include Dispute Responder (auto-responds to chargebacks with optimised evidence), Abandoned Cart Conversion, Subscription Recovery (analyses failed payments, applies retry logic, triggers customer nudges), Cashflow Forecaster, and a COD/RTO risk agent using LLM address validation. It ships with a **no-code agent builder in beta** that lets operations and finance teams create custom agents by describing the task in plain English and selecting which systems the agent may access.

**Agentic Experience Platform (March 2026).** Agentic Onboarding (PAN + website → automated CKYC identity verification, 30–45 min reduced to ~5 min). Agentic Dashboard (natural-language payment operations — upload a bank statement, ask it to reconcile against settlements, it extracts UTRs and flags discrepancies). Agentic Integration (integrate Razorpay in under 10 minutes via Claude Code, Replit, Emergent).

**Vulcan (18 August 2026).** A transformer-based payments foundation model trained on ~3 trillion data points across 4 billion payments, ~3,000 signals per transaction. Handles routing, fraud detection, risk assessment, checkout personalisation. Reported early results: 8–10% higher payment success rate, 8× more international card fraud detected. Razorpay has stated intent to extend it into authentication and lending.

**And, critically for us:** Razorpay publishes an **official open-source MCP server** (`razorpay/razorpay-mcp-server`, Go, ~229 stars, 42 tools, Docker image `razorpay/mcp`, plus a hosted remote option). It exposes payments, payment links, settlements, refunds, payouts, QR codes, and more to any MCP-capable AI client. It supports test-mode keys. Its own README names "agentic applications" as a primary use case.

### The structural fact that creates our problem

Put those together and the picture is this:

- A no-code builder is about to let non-engineers point LLM agents at APIs that **move money**.
- Those agents get access to PAN numbers, bank statements, settlement records, and transaction history.
- The tool layer is a general-purpose MCP server that exposes read and write operations through the same interface, with no semantic distinction between "fetch a payment" and "issue a refund."
- The agents ingest **attacker-controlled text** by design: customer support tickets, chargeback evidence, dispute notes, uploaded bank statements, merchant-entered descriptions.

Public commentary on the Agent Studio launch already raised exactly this: agents with access to PAN, bank statements, and transaction history, and the question of what security measures constrain them.

## 2. The problem

**An LLM agent with access to money-moving tools has no reliable, auditable, testable boundary between what it is allowed to do and what it can be talked into doing.**

Decompose that into four concrete failures:

### Failure 1 — Guardrails live in the prompt, where they are advisory

The dominant pattern is to write "never issue a refund without confirming with the user" into a system prompt. This is a *request*, not a *constraint*. It degrades under long context, adversarial input, multi-turn drift, and model updates. It cannot be unit tested. It produces no artifact when it works and no artifact when it fails.

### Failure 2 — Attacker-controlled text reaches the model with tool access attached

A chargeback evidence bundle contains free text written by a customer. A bank statement PDF contains a text layer. A support ticket is, definitionally, adversary-authored. Any of these can carry an instruction. The agent has no principled way to distinguish "data I was asked to analyse" from "instructions I was given."

### Failure 3 — There is no record that survives scrutiny

When an agent does something wrong with money, the questions are: what did it do, in what order, on whose authority, with what inputs, and could the log have been altered afterwards? Standard application logging answers none of these well.

### Failure 4 — There is no way to know if a change made things worse

Prompt tweaks, model upgrades, and new tools are shipped on vibes. There is no regression gate. "It seemed fine when I tried it" is the current state of the art for agents that touch financial APIs.

## 3. What SENTINEL is

**SENTINEL is a control plane that sits between an agent and its money-moving tools.**

It does four things:

1. **Enforces policy at the tool-call boundary**, not in the prompt. Every tool invocation is intercepted, classified, evaluated against declarative policy, and allowed, denied, or escalated to a human — before it executes.
2. **Redacts PII before it reaches the model**, and quarantines untrusted text so that instructions embedded in data cannot be confused with instructions from the operator.
3. **Writes a tamper-evident audit trail** — hash-chained, append-only, containing every decision with its reason.
4. **Proves the above works** via a deterministic evaluation harness and an adversarial red-team suite, both wired into CI as regression gates.

It ships with three working agents (Reconciliation, Dispute Responder, Subscription Recovery) whose purpose is to *exercise* the control plane and give it a demonstrable surface. The agents are the demo. The control plane is the contribution.

## 4. What SENTINEL is explicitly NOT

State these in the README. Scope discipline is what keeps this finishable.

- **Not an Agent Studio clone.** We are not building a marketplace, a no-code builder, or a competing agent catalogue.
- **Not a payments product.** Test mode only. No real money moves, ever.
- **Not a general-purpose AI firewall.** Scoped to MCP tool calls in a financial-operations context.
- **Not a fraud model.** No ML training. Vulcan's problem space is not ours.
- **Not affiliated with Razorpay.** Independent project built against publicly published open-source software.

## 5. Why this specific project

Three reasons, in order of importance:

1. **It targets an unsolved problem in the exact product surface the team is shipping right now.** Not a generic RAG chatbot with a payments skin.
2. **It demonstrates the rarest engineering skill in the LLM space: evaluation discipline.** Anyone can demo an agent. Very few people build a golden dataset, a cost/latency budget, and a CI regression gate around one.
3. **The red-team A/B is a demo that survives being watched by a skeptic.** Injection succeeds with guardrails off; injection fails with guardrails on; the delta is a number, not an anecdote.

## 6. Success criteria

The project is successful if a Razorpay engineer, reading it cold, concludes:

- This person understands that agents with write access are a security surface, not a feature.
- This person can build an eval harness, which means they can tell whether their own work is getting better.
- This person shipped it, deployed it, and documented what does not work.

## 7. Ethical and legal constraints

Non-negotiable, and stated in the README:

- **Test mode only.** No live keys anywhere in the repo, CI, or deployment. Secret-scanning enabled.
- **Synthetic data only.** All merchants, customers, transactions, PANs, IFSCs, VPAs, and bank statements are generated. Generators must produce values that are *format-valid but not real* — for PAN and card numbers, deliberately fail the real checksum/validation where one exists, so no generated value can collide with a live identifier.
- **No adversarial testing against Razorpay's hosted infrastructure.** The red-team suite runs against our own local fixture server, never against the remote MCP server, never against production endpoints. This is a hard rule.
- **Responsible disclosure.** If the build incidentally surfaces a genuine vulnerability in `razorpay/razorpay-mcp-server`, report it through their published HackerOne programme. Do not publish it, do not put it in the README, do not tweet it.
- **No affiliation implied.** Repo name, description, README, and UI must not suggest endorsement.
