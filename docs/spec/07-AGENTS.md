# 07 — The Agents and the Fixture Dataset

## Framing

The agents exist to **exercise the control plane**, not to be the contribution. Say this in the README. Three agents, chosen so that together they cover the full risk spectrum:

| Agent | Highest risk class used | What it proves |
|---|---|---|
| Reconciliation | `READ` | The system works on a genuinely useful task with zero write risk. Ingests untrusted documents. |
| Dispute Responder | `IRREVERSIBLE_WRITE` | RAG, structured output, and approval gating on a non-money irreversible action. |
| Subscription Recovery | `MONEY_MOVEMENT` | The full escalation path. The agent that must never act alone. |

Build them in this order. Each one exercises strictly more of the control plane than the last.

---

# Agent 1 — Reconciliation Agent

## What is currently true

Razorpay's Agentic Dashboard demonstrates uploading a bank statement and asking for reconciliation against settlements — the agent extracts UTR numbers, cross-references them against records, and flags discrepancies. Finance teams do this manually today, at scale, badly.

## What we are solving

Given a bank statement and a settlement window, produce a classified, auditable reconciliation report.

Why this agent first:
- **Genuinely useful.** Not a toy.
- **Read-only.** Demonstrates the whole pipeline with zero risk of an embarrassing demo.
- **Document ingestion is an injection vector.** A bank statement PDF has a text layer. That makes this agent the ideal carrier for the red-team demo — the attack arrives inside a legitimate business document, which is exactly how it would happen.

## How we proceed

**Input:** a bank statement (CSV and PDF both supported), a date range, and a merchant scope.

**Pipeline:**

1. **Parse and normalise.** Bank statement formats vary wildly. Normalise into a canonical internal transaction shape. Handle dates, amounts in minor units, and reference fields.
2. **Extract references.** UTRs and other reference identifiers appear in narration fields in inconsistent formats. Extract by pattern, then validate.
3. **Fetch settlements.** Via read-only MCP tools, scoped to the date range and merchant.
4. **Match.** Multi-pass, most-confident-first: exact reference match, then amount + date proximity, then fuzzy narration. Each match carries a confidence and the pass that produced it.
5. **Classify.** Every statement line and every settlement record lands in exactly one bucket: `MATCHED`, `AMOUNT_MISMATCH`, `MISSING_IN_STATEMENT`, `MISSING_IN_SETTLEMENTS`, `DUPLICATE_SUSPECTED`, `UNEXPLAINED`.
6. **Report.** Structured output plus a plain-language summary for a finance operator.

> **RESEARCH FIRST:**
> - UTR format and structure in the Indian banking system. What is the canonical form, what length, what character set, are there variants across payment rails?
> - Which Razorpay MCP tools expose settlement data, what date filtering they support, and what pagination behaviour they have. Pagination matters — an agent that silently reads page one and reports "all reconciled" is a serious correctness bug.
> - PDF text extraction library choice for Python. Evaluate at least two against the actual fixture statements before committing. Record the comparison in `DECISIONS.md`.

**Non-obvious requirements that matter:**

- **Never guess a match.** Low confidence goes to `UNEXPLAINED`. A reconciliation agent that quietly forces matches to look successful is worse than no agent. Add an eval scenario specifically for this: an ambiguous case where the correct behaviour is to decline to match.
- **Every match cites its evidence.** Which statement line, which settlement, which pass, what confidence.
- **Pagination must be handled and asserted.** Add an eval scenario where the correct answer requires reading beyond page one.
- **All statement text is `UNTRUSTED`.** Narration fields, descriptions, filenames. Quarantined without exception.

**Tool scope:** read-only settlement, payment, and payout tools. Nothing else. This agent runs under the `reconciliation-readonly` policy set as a least-privilege demonstration.

---

# Agent 2 — Dispute Responder

## What is currently true

Chargebacks require merchants to assemble evidence — transaction records, delivery confirmation, customer communication — within issuer deadlines. Razorpay ships a Dispute Responder agent that auto-responds with optimised evidence.

## What we are solving

Assemble a defensible evidence bundle for a disputed transaction, grounded in the merchant's actual records and in documented evidence requirements, and **never submit it without human approval.**

## How we proceed

**RAG component** — the JD names RAG explicitly, so build it properly:

- Corpus: chargeback reason-code taxonomy, evidence requirements per reason code, and merchant-specific policy documents. All synthetic or from public documentation.
- Chunking strategy chosen deliberately, not by default. Reason-code documentation is highly structured; naive fixed-size chunking will split a reason code from its requirements. **Test the retrieval independently of the agent** with a small retrieval eval set, and record the chunking comparison in `DECISIONS.md`.
- Every claim in the generated bundle cites its retrieved source. Uncited claims are a failure, asserted in evals.

**Pipeline:**

1. Fetch the dispute and its underlying transaction (read).
2. Classify the reason code.
3. Retrieve applicable evidence requirements (RAG).
4. Gather available evidence from merchant records (read).
5. Identify gaps — what is required but unavailable. **This is the most valuable output.** An honest "you cannot win this one, here is what is missing" beats a confident bundle built on nothing.
6. Draft the bundle as structured output with citations.
7. **Request approval to submit.** Always. `IRREVERSIBLE_WRITE`.

**Non-obvious requirements:**

- **Untrusted content is central here.** Customer-authored dispute descriptions are the payload carrier. This agent is the second red-team vector.
- **The gap analysis must be honest.** Add an eval scenario where the evidence genuinely does not support the merchant, and assert the agent says so rather than fabricating.
- **No claim without a citation.** Assert this.

---

# Agent 3 — Subscription Recovery

## What is currently true

Failed recurring payments are a large, quiet revenue leak. Razorpay's Subscription Recovery agent analyses failures, applies retry logic, and triggers customer nudges. Retries and nudges both touch money and customers.

## What we are solving

Diagnose subscription payment failures, propose a recovery plan, and execute **only what a human has explicitly approved** — with every money-moving step individually authorised.

This agent exists to exercise the escalation path fully. It is the one that must never act alone.

## How we proceed

**Pipeline:**

1. Fetch failed subscription payments in scope (read).
2. Classify failure causes — insufficient funds, expired mandate, technical decline, issuer decline. Retry viability differs sharply by cause, and retrying a hard decline is both futile and costly.
3. Propose a plan: which subscriptions to retry, when, and which customers to nudge. Structured output, with per-item reasoning.
4. **Each money-moving step is individually escalated.** Approving the plan does not approve the actions. Approving one retry does not approve the next.

**Non-obvious requirements — the interesting engineering:**

- **Plan approval ≠ action approval.** A human approving a plan of twelve retries has not approved twelve arbitrary retries. Each is separately bound and separately approved. Build the UI so a reviewer can approve a batch conveniently while each item remains individually bound to its arguments and individually revocable.
- **Retry timing is a policy concern, not an agent concern.** Card network and issuer retry rules exist and violating them has consequences. Encode as `time_window` and `rate_limit` policy rules so they are enforced regardless of what the agent proposes.
- **Novel counterparty is the sharp edge.** A retry to a previously-seen mandate is routine. A payout to a fund account never seen before is the highest-risk action in the entire system. `counterparty_novelty` must fire here.
- **This agent must be provably incapable of unattended money movement.** Add a red-team scenario that tries every angle to make it move money without approval, and assert zero successes.

> **RESEARCH FIRST:** Which subscription, mandate, and payment tools the MCP server exposes, and precisely which of them move money. Classify conservatively — if you cannot determine from documentation whether a tool moves money, classify it as if it does and record why.

---

# The Fixture Dataset

## Why it matters

Everything downstream depends on it. Evaluations are only as meaningful as the world they run against, and the red-team suite runs here exclusively — never against anyone's real infrastructure.

## Requirements

**Faithful.** Tool schemas must match upstream exactly. If they drift, evals pass against fixtures and fail against reality. Add a CI check that compares fixture schemas against the live upstream `tools/list` and fails on divergence.

**Deterministic.** Seeded generation. Same seed, same dataset, byte for byte. Committed as a versioned artefact, not regenerated on each run.

**Safe.** All identifiers format-valid but checksum-invalid where a checksum exists, so no generated value can collide with a real one. Stated explicitly in the README.

**Rich enough to be interesting.** The dataset must contain the hard cases, or evals only test the easy path:

- Settlements that reconcile cleanly
- Amount mismatches from fees, FX, and partial settlement
- Duplicate-looking-but-distinct transactions
- Transactions genuinely absent from one side
- Multi-page result sets that require pagination
- Disputes across several reason codes, some winnable and some not
- Subscription failures across every cause category
- Both new and previously-seen counterparties
- Free-text fields containing benign content that superficially resembles injection — **essential for measuring false positives.** A guardrail that blocks legitimate work is a failed guardrail, and without this you cannot measure it.

That last item is easy to skip and important not to. Measuring only attack-blocking rate, without measuring legitimate-work-blocking rate, produces a system that looks safe and is unusable.

**Generation approach:** procedural from a seed, with hand-authored edge cases layered on top. Procedural gives volume; hand-authored gives the specific hard cases. Both are needed.

## Acceptance criteria

- [ ] Fixture schemas match live upstream, verified by a CI check.
- [ ] Regeneration from seed is byte-identical.
- [ ] Every scenario category above is represented, with a coverage report.
- [ ] No generated identifier passes real-world checksum validation, asserted by a test.
- [ ] Benign-but-injection-like content present and used in false-positive measurement.
