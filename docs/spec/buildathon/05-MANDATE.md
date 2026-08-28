# 05 — Mandate: Consent, Moved Upstream

## 1. What is currently true

Every UPI payment needs a PIN. That is deliberate: the PIN proves a human approved *this specific* payment. It is the reason agentic payments were blocked — an agent reaching checkout hits an authentication step that assumes a human is present, and there isn't one.

**NPCI's answer is Reserve Pay**, launched at Global Fintech Fest 2025: lock a portion of a credit limit or line in advance, once, and spending inside the lock needs no further PIN.

**Razorpay's February 2026 pilot with NPCI on Claude is built on it.** Their own description: the user gives a one-time, consent-based authorization by setting a spending limit for a merchant; within that limit the agent transacts with no repeated PIN prompts; the user keeps visibility and can revoke instantly. Their summary — *AI can act decisively, but never independently of the user's intent* — is this component's design brief in one sentence.

**Reserve Pay is an NPCI rail-layer product, not a Razorpay API.** It sits underneath Razorpay and does not appear in the 41-tool MCP surface. Confirmed empirically: no match for reserve, mandate, emandate, recurring, autopay, nach, or plan.

## 2. What we are solving

**The brief demands "end to end" — no human tapping anything mid-flow. The bar demands every money action be "gated." Those are only compatible if consent moves upstream.**

The human authorises once, defining scope and limits. Inside them the agent runs uninterrupted. Outside them it cannot act at all.

## 3. How we proceed

**We model Reserve Pay's semantics over real test-mode primitives.** Not an integration, and the README says so precisely.

### 3.1 Why this is less novel than it sounds — and that is good

You already built a drawdown counter. `collected_run_minor` tracks committed amount against a per-run ceiling and refuses past it.

**A mandate is the same primitive with a different scope**: instead of "this run," it is "this merchant, until this date, up to this amount." You are generalising something tested, not inventing something new.

Say this in `DECISIONS.md`. Reusing a proven mechanism at a new scope is a better engineering story than a parallel implementation, and it means the mandate inherits behaviour you already trust.

### 3.2 What a mandate holds

- Locked amount, integer minor units
- **Merchant scope** — which merchant may draw. A mandate for one merchant must never be drawable by another; test it explicitly.
- Expiry, absolute and not extendable
- Instrument reference (via `fetch_tokens` — which is keyed by **contact
  number**, not customer id, per ADR-028 finding 7; the identity model must
  own the contact → token mapping explicitly)
- Status: active / exhausted / expired / revoked
- **Drawdown ledger** — an append-only record of every reservation, confirmation, and release

The ledger is not a running integer. It is a log, and the balance is derived from it. That gives you an audit trail, makes reserve/confirm/release states explicit, and means a balance can be reconstructed and verified rather than trusted.

### 3.3 Lifecycle

```
CREATE   human authorises: amount, merchant, expiry, instrument
         → one-time consent. The only human step in the whole flow.

RESERVE  commit gate holds an amount before create_order
         → atomic; the serialisation point for concurrency

CONFIRM  create_order succeeded → reservation becomes a drawdown

RELEASE  create_order failed, or cart expired → reservation returns

REVOKE   human ends it instantly
         → active reservations released; in-flight commits denied

EXPIRE   past expiry, no further draws, no extension
```

**Revocation must be instant and total.** Razorpay's blog specifically promises users can revoke consent instantly. An agent mid-purchase against a revoked mandate must be stopped at the gate, not allowed to finish "because it already started."

### 3.4 Enforcement placement

The mandate is a **policy input**, not a parallel check.

Add mandate state to `DecisionContext`: id, remaining balance, scope, expiry, status. Then express mandate governance as policy rules alongside the existing ones. This keeps one decision engine, one audit path, one explanation format — rather than a second gate with its own semantics.

**How it composes with existing controls.** You have four amount controls now. Order matters and must be explicit:

| Order | Control | Disposition | Why first |
|---|---|---|---|
| 1 | Mandate scope / expiry / revoked | DENY | No authority at all — nothing else is relevant |
| 2 | Mandate remaining balance | DENY | Un-approvable: a human already set this limit; overriding it defeats the consent model |
| 3 | Per-run collection aggregate | DENY | Runtime invariant, un-approvable |
| 4 | Per-call collection tier | ESCALATE | Approvable, tiered |
| 5 | Currency (INR-only) | DENY | Constraint |

**Most restrictive wins**, consistent with the existing engine. The critical judgement: **mandate exhaustion is un-approvable.** A reviewer must not be able to approve past a limit the user set — that is exactly the authority the mandate was created to bound. Allowing an operator to override it would make the whole consent model theatre.

Record this reasoning in an ADR. It is the kind of decision that looks arbitrary unless the rationale is written down.

### 3.5 Charging

Money movement goes through the real primitives: `initiate_payment` → `submit_otp`, with `fetch_tokens` for the saved instrument. `counterparty_arg_path: customer_id` already carries the novelty note — a never-seen customer on a mandate charge is a legitimate signal.

**The mandate authorises; the rail settles.** Do not conflate them in the code or in the README.

### 3.6 Suspend/resume — the known gap

The accumulator restore path is deferred under ADR-023. Mandate drawdown has the same exposure, with one difference: the ledger is persisted, so the balance is reconstructible from it rather than held only in run state.

**Make the mandate balance derived from the ledger at read time**, not carried in run state. Then suspend/resume cannot lose it — the ledger is the truth and the run holds no authoritative copy.

That is a genuinely better design than the run accumulator, and it is worth noting in the ADR as the pattern the accumulator should eventually adopt.

## 4. Honesty requirements

Verbatim in the README:

> Mandate semantics are modelled on UPI Reserve Pay — an NPCI rail-layer product that Razorpay's own agentic pilot is built on. Reserve Pay is not exposed in Razorpay's API or MCP surface, so this is a faithful model over real test-mode primitives, not an integration. AP2's three-mandate structure is the global analogue; UAP is not yet public and is referenced only for forward-compatibility of intent.

Three claims, three accuracy levels, none overstated.

**Label it as modelled in the UI too**, alongside catalog and cart. The reconciliation view saying out loud *"these tools are real, these are modelled, here is the line"* is more impressive than a system that blurs it — and this repository has already established that habit.

## 5. Acceptance criteria

- [ ] Mandate scope enforced: a mandate for merchant A cannot be drawn by merchant B, with a test
- [ ] Expiry absolute and non-extendable, with a test
- [ ] Revocation instant: in-flight commit denied, active reservations released, with a test
- [ ] Drawdown ledger append-only; balance derived, not stored
- [ ] Reserve → confirm and reserve → release both correct, with tests
- [ ] Exhaustion is un-approvable DENY, not escalation, with a test
- [ ] Composition order enforced and tested against all four other controls
- [ ] Concurrent reservations serialise; over-draw impossible, tested with real concurrency
- [ ] Balance survives suspend/resume because it is ledger-derived
- [ ] Mandate state present in `DecisionContext`; enforcement is policy, not a parallel gate
- [ ] Modelled status visible in the UI, not only in the README
