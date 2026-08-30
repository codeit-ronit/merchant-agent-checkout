# 10 — Build Order

## Governing principle

**Get a purchase completing end to end as early as possible, then make it good.**

The opposite instinct — build the catalog perfectly, then the cart perfectly, then finally connect them — produces a project where the loop closes at the last minute and every integration problem arrives at once.

Phase 3 ends with a real Razorpay order id from a natural-language instruction. Everything after that makes it correct, safe, measured, and beautiful. **If time runs out after Phase 3, there is still a submission.**

Every phase ends with something demonstrable and an appended `DECISIONS.md` entry.

---

## Phase 0 — Ground truth

**Goal:** know what is actually there before building on it.

1. Complete every **VERIFY FIRST** block in `02-ARCHITECTURE.md` §7.
2. Confirm the 41-tool manifest is still current — it has drifted three times.
3. Confirm `create_order`'s live schema: fields, amount representation, whether `notes` can carry a cart reference, what it returns.
4. Confirm `initiate_payment` → `submit_otp` in test mode, including **how to deliberately trigger a decline.** The failure path is a deliverable.
5. Confirm native idempotency key support.
6. Confirm `fetch_tokens` shape.
7. Retire or quarantine SENTINEL eval scenarios that no longer describe this product.
8. Write `LINEAGE.md` and `PROTOCOLS.md`.
9. Pin the repo's test count: the figure that means something is what the runner collects (`pytest --collect-only -q`). Correct any doc quoting a stale count; use that one number everywhere.

**Exit:**
- [x] Every finding in `DECISIONS.md` with the date (ADR-028, ADR-029)
- [~] Decline reproducible on demand, method recorded — method recorded (`failure@razorpay` VPA; never cancellation); REPRODUCTION deferred to Phase 3 item 0 by operator decision (ADR-028), so the deferral cannot slide
- [x] `LINEAGE.md` verified and `PROTOCOLS.md` written
- [x] SENTINEL suite scoped as separate (ADR-029, `evals/README.md`)
- [x] Test count pinned from collection (203 at pin time); stale counts corrected

**Do not skip this.** Three prior bugs came from building on assumed API shape.

---

## Phase 1 — Catalog

**Goal:** a merchant becomes legible to software.

1. Catalog data model — integer minor units, availability, constraints, tax declaration
2. CSV upload path with realistic messy input
3. Storefront URL path for structured markup
4. Bulk feed + MCP tools (`READ`)
5. Free text classified `UNTRUSTED`, quarantined at the proxy
6. Price versioning to support commit-time diffs
7. Merchant upsell rules
8. Seeded synthetic merchant fixtures

**Exit:**
- [x] Both onboarding paths work; effort measured (`artifacts/onboarding-effort.json`; path 3 dropped per ADR-030)
- [x] Catalog is the sole price source; test proves agent price rejected (`test_catalog_mcp_boundary.py::TestPriceRejection`)
- [x] Free text quarantined; verified in the trace (`TestQuarantine` — nonce-wrapped at the real boundary, audit entry present)
- [x] Prices integer minor units throughout; no float in any money path (model guards + float-free parser, tested)
- [x] Fixtures seeded and reproducible (`TestSeed::test_seed_is_reproducible`)

---

## Phase 2 — Cart and commit gate

**Goal:** the core. An agent can iterate for free and commit once.

1. Cart service — mutable, off-rail, server-priced
2. MCP tools (`REVERSIBLE_WRITE`, `BindingRole.NONE`)
3. Recompute on every mutation; return total + mandate remaining
4. Commit gate: re-price → diff → availability → mandate → policy → idempotency → one `create_order`.
   **Parser note (ADR-030 finding):** Razorpay serialises `notes` as an empty
   *list* when absent and an *object* when populated. Anything reading a cart
   reference back from `notes` must handle both shapes explicitly — do not
   discover this at commit time.
5. Reserve-before-forward
6. Concurrency at the drawdown ledger
7. Cart expiry with reservation release

**Exit:**
- [x] No cart operation accepts an amount; rejection tested, not silent ignore (`test_cart_mcp_boundary.py`; strict arg layer)
- [x] Re-price produces an itemised structured diff — with WHY per line, from the stored last-priced snapshot (`test_commit_gate.py::TestRepriceDiff`)
- [x] Divergence rejects and preserves the cart; hallucinated totals get their own honest reason (`REJECT_STATED_TOTAL_WRONG`)
- [x] Idempotent commit: same request twice → one order (`TestIdempotency`)
- [x] Failed `create_order` releases the reservation; cart recoverable (`TestFailClosed`)
- [x] Concurrent commits cannot over-draw; tested with REAL concurrency — barrier-released threads (`test_drawdown_ledger.py::TestRealConcurrency`)
- [x] Catalog unreachable → fail closed, nothing reserved (`TestFailClosed`)

---

## Phase 3 — Mandate + buyer agent → **the loop closes**

**Goal:** natural language in, real Razorpay order out. **The milestone that matters most.**

0. **FIRST, before the buyer agent — close the five ADR-028 UNVERIFIED
   payment-leg items against real test keys:** what `create_order` returns;
   reproduce the decline (`initiate_payment` + `vpa=failure@razorpay` — never
   cancellation, which succeeds in test mode); `submit_otp` behaviour;
   `fetch_tokens` response shape; whether the `single_block_multiple_debit`
   mandate-order flow works in test mode. The decline reproduction is a
   deliverable — the bar's "one failure handled gracefully" — not a
   nice-to-have. This item exists so the deferral from Phase 0 cannot slide.
1. Mandate service — lock, scope, expiry, revoke, ledger-derived balance.
   **Design note (ADR-028 finding 7):** `fetch_tokens` is keyed by *contact
   number*, not customer id — the mandate's instrument binding must map
   contact → token, and the identity model must own that dependency
   explicitly rather than discover it mid-build.
2. Mandate in `DecisionContext`; enforcement as policy, composition order per `05-MANDATE.md` §3.4
3. Buyer agent — definition, prompt, tool scope, structured output
4. Payment: `initiate_payment` → `submit_otp`
5. Receipt

**Exit — the ones that matter:**
- [x] **A natural-language constraint produces a real Razorpay test-mode order with a Razorpay-minted id** — `order_TVWCd7DHE9KzQh`, recorded in `artifacts/phase3-live-run.json`; settlement on the labelled modelled rail per ADR-034
- [x] Mandate scope, expiry, and revocation all enforced, with tests (`test_mandate_policy.py`, `test_mandate_lifecycle.py` — incl. mid-flight revocation)
- [x] Exhaustion is un-approvable DENY — a valid human approval cannot rescue it (critical test)
- [x] Concurrent draws serialise; over-draw impossible (Phase 2 barrier-thread tests; ledger defence-in-depth)
- [x] Agent never computes a total; tested — every bound amount is a server total; the stated-total-wrong path has its own reason code and metric
- [x] Agent declines honestly on unsatisfiable constraints, buying nothing (`test_buyer_agent.py::TestHonestFailure`)
- [x] Balance survives suspend/resume because it is ledger-derived (snapshot is a callable; sqlite reopen test)

*Receipt note: the structured output carries items, prices charged, total,
order id, payment status, and mandate remaining; the rendered receipt with
the permitting rule and audit reference is Phase 7 surface work.*

**The project is now demonstrable.** Everything after strengthens it.

---

## Phase 4 — Failure paths

**Goal:** the bar's "one failure handled gracefully," done properly.

1. Decline: order held, payment failed, cart recoverable, idempotent retry
2. Drawdown behaviour on decline — decided, documented, recorded
3. Ambiguous timeout: reconcile via `fetch_order_payments`, never blind-retry
4. Out-of-stock, partial availability, phantom product
5. Mandate expiry/revocation mid-purchase
6. Every row of `07-FAILURE-MODES.md` §4

**Exit:**
- [x] Decline demonstrated end to end with idempotent retry — one order, two attempts, one capture; drawdown RESERVE→CONFIRM→REVERSE→RESERVE→CONFIRM visible in the ledger (`test_failure_matrix.py::TestDecline`)
- [x] Timeout reconciles before retrying, with tests in BOTH directions (hidden success → never pays again; hidden failure → honest decline) plus the boundary refusing the identical blind retry (`TestAmbiguousTimeout`)
- [x] Every failure row has a passing test — the mapping is the docstring of `test_failure_matrix.py`
- [x] Every failure response carries an actionable next step (`TestActionableNextSteps`)
- [x] Double-charge impossible under retry, timeout, and concurrency — three critical tests (`TestNoDoubleCharge`)
- [x] Drawdown behaviour on decline: decided (ADR-026), implemented (SettlementCoordinator), recorded (ADR-036)
- [x] Bonus hole closed while writing the matrix: `resolves_tools` — a valid dinner mandate can no longer authorise a refund (critical test)

---

## Phase 5 — Upsell

**Goal:** connect to the revenue headline; prove controls work on a positive money action.

1. Merchant rules drive offers; agent-invented offers rejected
2. Offer suppressed pre-model when it would exceed the mandate
3. Acceptance explicit; silent addition structurally impossible
4. Receipt marks upsell, rule, and acceptance
5. Per-cart cap

**Exit:** per `06-BUYER-AGENT-AND-UPSELL.md` §B6 — all met (ADR-037, `tests/unit/test_upsell.py`):
- [x] Every offer traces to a merchant rule; an invented offer_id is refused and named a policy violation
- [x] Offer suppressed pre-model when it would exceed the mandate — absent from the response by construction
- [x] Silent addition structurally impossible: `cart_accept_upsell` with a server-issued id is the only path in
- [x] Upsell price sourced from catalog; acceptance re-validates price/stock/mandate against the LIVE cart (the review's TOCTOU condition — critical test: cleared-then-cart-grew is withdrawn)
- [x] Receipt marks the upsell, its rule, its offer id, and the acceptance time; breakdown lines carry `upsell_rule_id`
- [x] Per-cart offer cap enforced cumulatively (counts what was shown)
- [~] Upsell acceptance rate as a revenue metric → Phase 6 eval reporting

---

## Phase 6 — Evaluation

**Goal:** numbers.

1. Commerce suite, separate from SENTINEL's
2. 12 scenarios across all six categories first.
   **Overfitting guard:** the Fresh Basket seed was deliberately shaped so the
   headline constraint works — which makes it exactly the fixture you can
   overfit to. The suite MUST include at least one merchant fixture that was
   NOT authored around a known-good scenario — generated, with the constraint
   scenarios written *after* the catalog exists. Otherwise task-success
   measures fixture design, not how well the agent shops.
3. All metrics per `08-EVAL.md` §4 — including the stated-total error rate
   (`REJECT_STATED_TOTAL_WRONG` frequency), the direct per-model measurement
   of arithmetic failure that proves the no-model-money constraint is
   load-bearing
4. Gates including amount-accuracy hard zero and over-refusal ceiling
5. Adversarial suite with benign controls — MUST include the named
   `unnarrowed_cart_mutation` group (08-EVAL §7): the specific probes of what
   `escalate_reversible: false` gave up, reported by name, with the
   one-YAML-line reversal criterion stated
6. Expand toward ~40

**Exit:**
- [x] Replay reproduces committed numbers with no credentials (`make eval-commerce`; deterministic brains + committed fixtures; Spice Route anchored by a byte-identity regeneration test)
- [x] Amount accuracy 100%; hard-zero gate active in code — proven load-bearing: weak tier mis-states 40.9% of commits and charges wrong 0 times
- [x] Over-refusal 0% against the 10% ceiling, defended as a product decision in `thresholds.yaml` and the README
- [x] Adversarial A/B (`make eval-adversarial`): the named `unnarrowed_cart_mutation` group across four conditions, benign twins reported at equal prominence (narrowed control: 100% false blocks; commerce: zero)
- [x] Merchant time-to-sellable measured (`artifacts/onboarding-effort.json`)
- [~] Real-model recorded numbers: infrastructure ready, blocked at time of writing by free-tier rate limits on both providers (ADR-038; rerun: `SENTINEL_LIVE=1 SENTINEL_LIVE_PROVIDER=groq make eval-commerce`)

---

## Phase 7 — Interface

**Goal:** make the invisible visible.

Design pass before implementation, per `09-UI.md` §6. Split view first — it is the signature and everything else is support.

**Exit:** per `09-UI.md` §9 — all verified in the running app (ADR-039):
- [x] Split view: conversation and machinery synchronised live (one enriched event stream drives both panes — synchrony by construction)
- [x] Cart, totals, and mandate drawdown update in real time as the agent works
- [x] Every policy decision visible with its plain-language reason (+ reason code in mono)
- [x] Re-price diff surfaced; the two-verdict row shows "policy allowed / commerce refused" side by side
- [x] Mandate creation reads as setting money aside; instant revoke works from the merchant console
- [x] Real vs modelled surfaced persistently (▢ modelled / ◆ Razorpay · test chips on panel headers and entities)
- [x] Receipt names the total, order id (real chip), payment status (modelled chip), mandate remaining, and marks the accepted offer
- [x] Failure states explain what happened and the next step (decline / timeout / declined-honestly cards)
- [x] Amounts tabular-aligned; states glyph+word (colour-independent); responsive stack < 900px; reduced motion honoured; designed empty states

---

## Phase 8 — Ship

1. **README** — opens with a purchase, not an architecture diagram
2. `LIMITATIONS.md` — modelled vs real, scope cuts, known gaps
3. `PROTOCOLS.md` — which layer each protocol occupies, what we modelled
4. Live demo, fixture-capable, no credentials to try
5. **3-minute video** per `11-DEMO-AND-SUBMISSION.md`
6. Final security pass: no keys in history, secret scan clean, test-mode notice prominent, non-affiliation stated

**Exit:**
- [x] Clone to running in one command, verified clean (fresh clone, zero credentials: 401 tests, both eval suites through gates in replay, server boots — ADR-040)
- [x] Local demo runs without credentials (`make demo`); hosted deploy configs exist (render/fly/Procfile) — deploying is an operator action
- [~] Video: script complete with the fixed order + the two-verdict beat + the verbatim claim guard (`docs/demo-script.md`) — RECORDING is the operator's action
- [x] README reports commerce numbers, not SENTINEL's — and weakest-first, with the earned sentence above everything
- [x] Git history contains no credentials — secret scan clean over tree AND history; the only `rzp_live` strings are the refusal guard's own test dummies

---

## If time compresses

Cut from the bottom. Never from the top.

1. Reduce commerce scenarios from 40 to 20, keeping all six categories
2. Cut the storefront-URL onboarding path; keep CSV
3. Cut merchant console views except catalog and mandates
4. Cut the upsell — but say in the README that the revenue mechanism was scoped out and why

**Never cut:** the cart, the commit gate with its re-price diff, the mandate, the decline path, the audit trail, or the honest limitations. Those are the submission.
