# 07 — Failure Modes

> Read this early, not at Phase 5. It shapes the design of everything before it.

## 1. The requirement, read carefully

The bar says: *"Show the audit trail and one failure handled gracefully."*

**In payments, "a failure" means a decline, a timeout, an ambiguous settlement, an out-of-stock — an operational failure in the normal course of business.** It does not primarily mean a security event.

This is the most likely misreading of the entire brief, and it is a costly one. Answering "one failure handled gracefully" with only a prompt-injection block tells a payments engineer that you read the sentence as an AI-safety prompt rather than a commerce prompt.

**Do both, in this order:**

1. **The literal answer** — a payment declines mid-flow, recovered without damage. This proves you understand payments.
2. **The signature** — an injected instruction in a product description, blocked. This proves you understand agents.

First establishes credibility. Second differentiates. Reversing them reads as a security project wearing a commerce costume.

## 2. The primary demonstrated failure: payment decline

### What happens

Cart committed. `create_order` succeeded — the order exists, the mandate is drawn down. Then `initiate_payment` declines.

### Required behaviour

- **The order stands.** It is a legitimate intent to collect. Do not delete it.
- **Payment marked failed**, with the decline reason surfaced as given by the rail.
- **The mandate reservation is handled correctly.** The order was created, so the drawdown confirmed at step 10 of the gate sequence (`04` §4.1). It confirms there and does not wait for payment success — the mandate authorises *binding an amount*, not money moving; waiting would let orders bind past the balance, with the over-draw discovered only as payments land (ADR-026). On payment failure the drawdown **reverses** — a user-fairness judgement, not a correctness one: no money moved, and holding the user's locked balance against a failed payment is hostile. A stricter system could defensibly hold the reservation for a retry window; the ADR names this as a product choice. Confirm and reversal are **separate ledger entries, not a deletion** — history shows what happened, and the balance stays reconstructible.
- **A reversed drawdown must not silently free budget for a different purchase.** If ₹800 reverses on a decline and the agent immediately spends it elsewhere, the user's original intent quietly evaporated. Default (ADR-026): the reversal is **visible to the user**, rather than scoped to a retry window of the same cart — simpler, and honest. Phase 4 confirms this deliberately rather than falling into whichever the code does first.
- **The cart remains recoverable.** The user retries; the agent does not rebuild from scratch.
- **Retry is idempotent.** Same cart, same amount → the existing order is reused. **No second order, no double charge.** This is the property to demonstrate on screen.
- **The agent reports honestly.** "Payment declined, here is why, the order is held, you can retry." Not a silent retry loop, and not a cheerful message that hides the failure.

> **VERIFY FIRST:** Determine how to deliberately trigger a decline in Razorpay test mode — test card numbers, a specific amount, or a simulated failure mode. You must be able to reproduce it on demand for the demo and the eval suite. Record the method in `DECISIONS.md`. If declines cannot be triggered reliably in test mode, say so and demonstrate the timeout path instead — but find out rather than assuming.

## 3. The ambiguous timeout — the harder case

`initiate_payment` times out. **You do not know whether it succeeded.**

This is the genuinely hard failure in payments, and handling it correctly is a strong signal.

**Never retry blindly.** Reconcile first: call `fetch_order_payments` against the order to discover ground truth. Then act on what actually happened, not on what you assume.

Three outcomes:
- A payment exists and succeeded → report success, do not retry
- A payment exists and failed → treat as a decline, per §2
- No payment exists → safe to retry, under the idempotency key

This is worth a distinct eval scenario and a line in the demo narration. "We don't retry on timeout, we reconcile" is a sentence that lands with anyone who has run payments.

## 4. The full failure matrix

Each needs a test. Grouped by where they arise.

### Catalog and cart

| Failure | Behaviour |
|---|---|
| Price changed between read and commit | Re-price wins; itemised diff returned; agent re-confirms; cart survives |
| Item out of stock at commit | Reject, name the specific item, never substitute silently |
| Partial availability (3 of 4) | Inform with specifics; the agent decides; system never chooses for the user |
| Agent names a nonexistent product | Reject at the cart boundary; no phantom line item |
| Agent asserts a price | Ignored entirely; catalog is the only source |
| Catalog unreachable at commit | Fail closed; never commit against a cached price |
| Cart expired | Reject; release any held reservation |

### Mandate

| Failure | Behaviour |
|---|---|
| Expired mid-purchase | Deny at the gate; not resumable on a stale mandate |
| Insufficient balance | Deny before `create_order`, with the shortfall named |
| Revoked mid-purchase | In-flight commit denied immediately; reservations released |
| Wrong merchant scope | Deny; a mandate for A is never drawable by B |
| Two agents, one mandate, concurrent | Serialised at the ledger; over-draw impossible |

### Payment

| Failure | Behaviour |
|---|---|
| Decline | §2 |
| Ambiguous timeout | §3 — reconcile, never blind-retry |
| Duplicate submission | Idempotent; one order, one charge |
| OTP step fails | Order held, payment failed, cart recoverable |

### Agent and security

| Failure | Behaviour |
|---|---|
| Injection in product description | Quarantined; `provenance_guard` narrows writes; logged as a security event |
| Agent attempts an out-of-scope tool | Denied; logged as an incident, not a routine denial |
| Agent loops without progress | Resource ceiling terminates the run cleanly |
| Malformed tool call | Reject, one corrective retry, then fail. **Never guess intended arguments on a money call.** |
| Upsell would exceed mandate | Suppressed pre-offer, not rejected post-acceptance |

## 5. The principle underneath all of it

**Every failure leaves the system in a state a human can understand and act on.**

Not "the run failed." Instead: what was attempted, how far it got, what state things are in now, and what the next step is. A failure with no actionable next step is a bug.

Three properties to hold everywhere:

- **No silent substitution.** The system never decides on the user's behalf when the plan cannot be executed.
- **No double-charge, ever.** Under any retry, any timeout, any concurrent submission.
- **No hidden failure.** The agent never reports success it did not achieve, and never quietly retries in a way that obscures what happened.

## 6. Acceptance criteria

- [ ] Deliberate decline reproducible on demand; method recorded
- [ ] Decline: order held, payment failed, cart recoverable, retry idempotent — demonstrated on screen
- [ ] Drawdown behaviour on decline decided, documented, and recorded in the ledger
- [ ] Timeout path reconciles via `fetch_order_payments` before any retry, with a test
- [ ] Every row in §4 has a passing test
- [ ] Every failure response carries an actionable next step; asserted in evals
- [ ] Double-charge impossible under retry, timeout, and concurrency — three separate tests
- [ ] The demo shows the operational failure *before* the security failure
