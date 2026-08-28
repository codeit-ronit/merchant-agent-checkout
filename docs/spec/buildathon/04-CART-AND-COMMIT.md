# 04 — Cart and Commit Gate

> The heart of the project. If only one component is excellent, make it this one.

## 1. What is currently true

Confirmed against the live 41-tool manifest: **Razorpay has no cart primitive.** The nearest object is the Order, created whole by `create_order` with a final amount. Payment links and QR codes are similar — collection instruments created with an amount already decided.

Every one of these assumes the amount is *already known*. That assumption comes from human checkout, where a person decides in a UI and the server is told the result.

## 2. What we are solving

**An AI buyer arrives at the amount by iterating, and there is nothing upstream to iterate on.**

A human decides, then pays. An agent negotiates: add an item, check the total against its mandate, swap something, remove one, re-check, commit. That is four or five state changes before anything should touch a payment rail.

Without a mutable object, the agent has exactly one move — `create_order` with an amount it had no structured way to reach. It would be doing the arithmetic itself, in the model, on money. That is the failure this component exists to prevent.

## 3. The cart

### 3.1 Properties

**Off-rail.** Touches no Razorpay primitive until commit. Mutations are free: no upstream write, no policy escalation, no audit weight. The agent may iterate as much as it likes.

**Server-priced.** Every mutation triggers a recompute from live catalog truth. The cart holds item ids and quantities; **it never holds a price the agent supplied.** The agent names *what*; code produces *how much*.

**Provenanced.** Each cart records which agent, which mandate, which run, and which catalog version priced it. That last field is what makes the commit-time diff possible.

**Expiring.** Carts have a TTL. An abandoned cart holding a mandate reservation is a resource leak and a correctness problem.

### 3.2 Operations

Exposed as MCP tools, classified `REVERSIBLE_WRITE` but **`BindingRole.NONE`** — they change state without binding an amount, so amount governance correctly does not apply. This is exactly the distinction the binding-role model was built for, and it is worth an ADR note that the model earned its keep here.

- `cart_create` — new cart, bound to a mandate
- `cart_add_item` — item id + quantity; server prices it
- `cart_update_item` — change quantity
- `cart_remove_item`
- `cart_view` — current state with server-computed totals
- `cart_clear`

**No operation accepts an amount.** A test must prove that passing one is rejected rather than ignored — silent ignoring is worse, because the agent then believes it worked.

### 3.3 Computation

All deterministic, all in code, all with provenance:

- Line total = catalog price × quantity
- Tax per the merchant's declared treatment
- Discounts from merchant rules only, never agent-proposed
- Cart total = sum, in integer minor units, no floats anywhere

Every computed figure records which catalog version and which rule produced it. When the commit-time diff says "the total changed by ₹40," it must be able to say *why*.

### 3.4 Live mandate visibility

On every mutation, return the mandate's remaining balance alongside the cart total.

This matters more than it looks. It lets the agent reason about affordability *before* commit, rather than discovering at the gate that it has overshot. Cheaper, and it produces better agent behaviour — the agent adjusts the cart instead of failing the purchase.

It is also the most compelling thing in the demo UI: the drawdown visibly decreasing as the cart grows.

## 4. The commit gate

**The single moment where thinking becomes commitment.** Everything expensive happens here and nowhere else.

**Classification: `RiskClass.REVERSIBLE_WRITE`, `BindingRole.COLLECTION`** (ADR-027). Reversible because an unpaid order can be abandoned with no financial consequence — it is an intent to collect, exactly what `create_order` is, and exactly what it becomes. Collection-binding because it commits an amount, which is precisely the distinction the binding-role model exists to capture. It therefore inherits the full collection governance: per-call tiers, run aggregate, currency constraint, and mandate composition. A call can be reversible and still bind ₹5 lakh.

**One binding event, one accumulation.** `cart_commit` and the `create_order` it issues must not double-count against the run aggregate. The natural implementation counts both; test that it does not.

### 4.1 Sequence

```
Agent calls cart_commit(cart_id, expected_amount_minor)

 1. Load cart. Verify not expired, not already committed.
 2. RE-PRICE: recompute every line against live catalog state.
 3. DIFF against expected_amount_minor.
      match      → continue
      divergence → REJECT. Return the true amount and an itemised
                   explanation of what changed. Agent must re-confirm.
                   Cart is NOT destroyed.
 4. Availability check: every item still purchasable at the requested quantity.
      → name the specific item that failed. Never substitute silently.
 5. Mandate check: scope matches merchant, not expired, not revoked,
    remaining balance ≥ total.
      → deny with the shortfall named.
 6. Policy evaluation (SENTINEL): collection tier, run aggregate, currency.
 7. Idempotency: key over (cart_id, final_amount, mandate_id).
      → seen: return the prior order, do not create a second.
 8. Reserve the drawdown against the mandate.
 9. ONE create_order.
10. On success: confirm the drawdown, record the order, emit the trace.
    On failure: release the reservation, leave the cart recoverable.
```

### 4.2 Why the re-price diff is the important part

**This is the answer to the sharpest question a payments engineer can ask**, and almost no submission will have one.

Between catalog read and commit, price and stock change. Human checkout solves this by re-pricing server-side and showing the user the difference. An agent system that trusts the agent's arithmetic is one hallucinated total away from binding the wrong amount to a real customer.

Requirements:

- The diff is **itemised**: which line changed, from what, to what, and why
- The agent receives it as **structured data**, not prose, so it can decide rather than guess
- The cart survives — the agent may accept the new total, adjust, or abandon
- The event is logged, because a merchant repeatedly re-pricing between read and commit is a signal worth surfacing

Demo this explicitly. A price changing mid-purchase, the commit being rejected with the reason, the agent re-confirming, and the correct amount binding — that sequence is more convincing than any amount of description.

### 4.3 Reserve-before-forward

Draw down the mandate **before** `create_order`, then confirm or release based on the outcome. Never after.

If you draw down after, a `create_order` that succeeds while the response is lost leaves an order that exists with no drawdown recorded — the mandate is silently over-drawn. Reserving first makes the failure mode "a reservation to release," which is recoverable, instead of "money bound with no record," which is not.

This is the same reserve-before-forward pattern already used in SENTINEL's idempotency guard. Reuse it rather than inventing a second mechanism.

### 4.4 What the gate returns

On success: order id (Razorpay-minted — this is the proof the loop is real), final amount, itemised breakdown, mandate remaining after drawdown, the policy reason code that permitted it, and the audit chain reference.

On rejection: a specific reason code, the true amount where relevant, and what the agent could do about it. **A rejection with no actionable next step is a bug**, not a safety feature.

## 5. Concurrency

Two agents may hold carts against the same mandate. Handle it or you have an over-draw bug.

- The drawdown ledger is the serialisation point. Reservations are atomic.
- Second concurrent commit against insufficient remaining balance fails cleanly, with the shortfall named.
- Never interleave. Never allow both to succeed on the same balance.

Test this with genuinely concurrent commits, not sequential ones. Almost nobody handles this and it is a legitimate "what would break at scale" answer in an interview.

## 6. Acceptance criteria

- [ ] No cart operation accepts an amount; a test proves rejection, not silent ignoring
- [ ] Every total is server-computed with recorded provenance
- [ ] Re-price at commit produces an itemised, structured diff
- [ ] Divergence rejects the commit and preserves the cart, with a test
- [ ] Out-of-stock at commit names the specific item; no silent substitution
- [ ] Mandate insufficiency denies before `create_order`, with the shortfall named
- [ ] Reserve-before-forward; a failed `create_order` releases the reservation, with a test
- [ ] Idempotent commit: same request twice → one order, one charge
- [ ] `cart_commit` and its `create_order` accumulate ONCE against the run aggregate — one binding event, one accumulation — with a test (ADR-027)
- [ ] Concurrent commits on one mandate cannot over-draw; tested with real concurrency
- [ ] Catalog unreachable at commit → fail closed
- [ ] Cart expiry releases any held reservation
- [ ] Every rejection carries an actionable next step
