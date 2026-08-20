# 10 — Operator Surface (Frontend)

## 1. What is currently true

Agent tooling UIs are overwhelmingly chat transcripts. A chat transcript is the wrong shape for an operator who needs to answer: what is this agent doing right now, what is it asking permission for, what was it stopped from doing, and can I trust the record?

## 2. What we are solving

**A control surface, not a chat window.** The person using this is an operations or finance reviewer, not a prompt engineer. They need to make an approval decision in under thirty seconds with enough context to be accountable for it.

## 3. Views

Six views. Each has one job.

### 3.1 Run console

Live trace as it streams. Each step shows: the model's reasoning, the tool requested, the policy decision with its reason, and the result.

Requirements:
- Policy decisions are the visual focus, not an afterthought. Denials and escalations are the most important events on the screen.
- Every decision expands to show matched rules and the deciding rule.
- Quarantined content is **visually distinct and unmistakable** — the operator must be able to see at a glance which parts of the context were untrusted.
- Running cost and elapsed time update live.
- Reconnects cleanly and backfills missed events using sequence numbers.

### 3.2 Approval queue

The highest-stakes screen in the product.

For each pending approval:
- **A single plain sentence stating what will happen.** Not JSON. The JSON is available behind a disclosure, but the sentence is the interface.
- Which policy rule triggered the escalation, in plain language.
- The context: the agent, the task, the entity involved.
- **A prominent flag if this run processed untrusted content.** This is the single most decision-relevant fact and it must not be buried.
- Time remaining before expiry, counting down.
- Approve / Reject, with an optional note.

Design constraints, drawn from real approval-fatigue failure modes:
- **No bulk approve-all.** Batch approval is permitted for a reviewed plan, but each item remains individually bound and individually visible. Convenience must not become a rubber stamp.
- Expired approvals are shown as expired, greyed, and not actionable. Never silently disappear — the operator needs to see that something timed out.
- Rejection requires no justification, approval on a run flagged for untrusted content does.

### 3.3 Policy editor and dry-run simulator

- Read and edit policy sets with schema validation and inline errors.
- **The dry-run panel is the centrepiece.** Select historical runs, apply the candidate policy, see every decision that would change.
- Changes are grouped into newly denied, newly escalated, and **newly allowed** — the last rendered as a warning, prominently, because loosening policy is the change most likely to be made carelessly.

### 3.4 Eval dashboard

Trends across commits: accuracy by category, p50/p95 latency, cost per run, over-refusal rate.

Requirements:
- Every point links to the commit and the full result artefact.
- Hard-gate metrics are displayed as pass/fail status, not as trend lines. A hard zero is not a trend.
- Variance shown as a band, not hidden by the mean.

### 3.5 Red-team results

The A/B comparison, given the prominence it deserves.

- Aggregate table: attack success rate off versus on, by severity level.
- The ablation table.
- **False-positive rate displayed with equal weight** to the success rate. Same size, same position, no visual de-emphasis.
- Per-payload drill-down with the full trace, so any claimed block can be inspected.

### 3.6 Audit viewer

- Chronological ledger with filters by run, tool, disposition, and reason code.
- **A verify button that walks the chain and displays the result.** Verified with entry count, or the exact sequence number of the first break.
- The verification result is the visual anchor of this screen. An audit log nobody verifies is theatre.

## 4. Design direction

The frontend should not look like a default admin template. It will be looked at by people who see a great many dashboards.

**Ground it in the subject.** This is a control room for financial operations. The vernacular is ledgers, reconciliation, authorisation, and chain of custody. Not "AI." The interface should feel like something a finance operator would trust with an audit trail — closer to a settlement system than to a chatbot.

**Deliberate choices required:**

- **Palette:** 4–6 named values, chosen for this brief. Decision state is the primary information carried by colour — allowed, denied, escalated, and awaiting review must be distinguishable instantly and also distinguishable without colour, since financial software has accessibility obligations and colour-blind operators exist.
- **Typography:** a display face and a body face, plus a genuine monospace face for identifiers, amounts, and hashes. **Amounts and identifiers must be tabular-figure aligned.** Misaligned money in a financial interface is a correctness signal, not an aesthetic one.
- **Structure:** the hash chain is real sequential structure — one of the few places a numbered or linked visual device encodes something true rather than decorating. Use it there and nowhere it does not belong.
- **Signature element:** pick one and make it the memorable thing. The strongest candidate is the audit chain visualisation — a verifiable, linked sequence that visibly breaks when tampered with. It embodies the entire project in one visual.

**Calibrate away from defaults.** Current AI-generated design clusters around three looks: warm cream background with high-contrast serif and terracotta accent; near-black with a single acid-green or vermilion accent; broadsheet layout with hairline rules and zero border radius. All are legitimate for some brief. None should be chosen here by default. Spend the freedom on something specific to a financial control room.

**Restraint.** One bold element, everything else quiet and disciplined. Responsive to mobile, visible keyboard focus, reduced motion respected. Build the quality floor without announcing it.

**Copy.** Write from the operator's side of the screen. "Blocked: refunds over ₹10,000 need finance approval" — not "Policy rule violation: threshold_exceeded." Active voice. An action keeps the same name through the whole flow: the button that says "Approve" produces a state that says "Approved." Errors explain what happened and what to do next; they do not apologise and they are never vague. Empty states are invitations to act.

## 5. Technical constraints

- React + TypeScript + Vite.
- Server-sent events for the live trace, with sequence-number-based reconnection and backfill.
- All data arrives pre-redacted from the API. **The frontend never redacts** — redaction in the client means the real value already crossed the wire.
- Every view has a working empty state and a working error state. Both are specified before either is built.

## 6. Acceptance criteria

- [ ] All six views implemented and reachable.
- [ ] Live trace streams, reconnects, and backfills without gaps.
- [ ] Approval decisions are readable as one plain sentence without expanding JSON.
- [ ] Untrusted-content flag is prominent on affected approvals.
- [ ] No bulk approve-all path exists.
- [ ] Dry-run simulator renders newly-allowed changes as warnings.
- [ ] Audit verification runs from the UI and displays a definite result.
- [ ] False-positive rate displayed with equal prominence to attack success rate.
- [ ] Decision states distinguishable without colour.
- [ ] Amounts and identifiers tabular-aligned.
- [ ] Responsive to mobile, keyboard navigable, reduced motion respected.
