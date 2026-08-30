# CONDUIT — merchant-agent-checkout

**Making any Razorpay merchant transactable by an AI buyer, end to end.**
A Razorpay Buildathon submission — Track 01: AI Growth & Agentic Commerce.

> **Nine arithmetic failures. Zero wrong charges.** In the committed eval, the
> deliberately-flawed model tier mis-states its own total on 40.9% of commits —
> and the charged amount is wrong 0% of the time, because the server re-prices
> at the moment of binding and rejects every mis-statement. The model chooses
> and explains; code calculates and binds. That sentence is what this
> architecture exists to earn, and it is a measurement, not a claim
> (`make eval-commerce`).

## The problem

An AI buyer cannot shop at a normal merchant. The storefront is built for a
human — pictures, a form, an OTP — and an agent can use none of it. The large
platforms in Razorpay's live agentic pilot built their own integrations; **a
merchant doing ₹5 lakh a month cannot**, and that long tail is what Track
01's second clause exists for. CONDUIT closes it: a structured catalog
derived from what the merchant already has, a cart an agent can reason over,
and a single auditable moment where a cart becomes a real Razorpay order —
inside a spending mandate the user consented to once, upfront.

## The video

*3 minutes: a purchase, a payment failure recovered without a double charge,
and a merchant's own product description trying to manipulate the agent —
in that order.* **[link lands here on recording — script: `docs/demo-script.md`]**

## The numbers — weakest first

14 authored scenarios (expected outcomes written before any run) × 2
deterministic tiers × 3 runs, replayable with zero credentials.

**1. A fooled agent can still bind a budget-compatible substitution.** The
`unnarrowed_cart_mutation` experiment (`make eval-adversarial`) probes exactly
what our injection-containment judgement gave up: when a simulated
quarantine-failure makes the agent obey a merchant's planted "substitute X
with Y" directive, the swapped basket **binds** (₹394 — inside the user's
budget, inside the mandate, but not what they asked for). That is the honest
residual, and it is one precise shape.

The same experiment produced a finding we did not design for: **the user's
stated constraint is itself the first containment layer.** Two of the three
attack shapes — inflate the quantity, add an expensive item — never reached
any control, because they bust the stated budget and the agent's honest
budget logic dismantles the cart. And we did not merely judge the alternative
posture acceptable to skip — **we measured it, and it blocked 100% of benign
traffic** (after any catalog read, every cart mutation escalates to a human).
A control that blocks all legitimate work is not a safer control; it is an
off switch with extra steps. The give-up stands: one attack shape, bounded by
budget and mandate, reversible with one YAML line, contingent on the
real-model fooling rate that quarantine exists to minimise.

**2. The weak tier mis-states totals on 40.9% of its commits — and charged
the wrong amount 0 times.** Stated-total errors: 9 in 22 commits. Amount
accuracy: **still 100%**, because the gate re-prices and rejects every one.
The "model never computes money" constraint, measured as load-bearing — a
zero here would have meant the scenarios never stressed arithmetic.

**The clean sheet** (both tiers unless noted):

| Metric | Value | Gate |
|---|---|---|
| Task success (14 scenarios, 6 categories) | 100% | floor: 100% both tiers |
| Amount accuracy | **100%** | HARD ZERO — one wrong charge fails the suite |
| Mandate violations · double charges | 0 · 0 | HARD ZERO |
| Over-refusal (legitimate purchases blocked) | 0% | ceiling: **10%, defended**¹ |
| Appropriate refusal (unsatisfiable → buy nothing) | 100% | floor: 100% |
| Stated-total error rate | strong 0% · weak 40.9% | measurement, no gate |
| Upsell offered / accepted | 100% / 33.3% | accepted only where the *budget* allowed |
| Merchant time-to-sellable | CSV: 3 steps · URL: 1 step | `artifacts/onboarding-effort.json` |
| Variance across N=3 | none flagged | variance is a finding, not noise |

¹ *A checkout that blocks more than one in ten legitimate purchases is not a
checkout. Each false block costs the merchant the sale and costs agentic
checkout the customer's trust; controls that tax legitimate commerce harder
get turned off in the field — the real failure mode.*

Real-model numbers are pending: both free-tier providers rate-limited the
recording pass at the time of writing — the named "free-tier by design"
limitation in action. The runner is live-ready
(`SENTINEL_LIVE=1 SENTINEL_LIVE_PROVIDER=groq make eval-commerce`); results
land in `evals/commerce/results/live-*.json`, an appendix that never replaces
the committed deterministic floor above.

## The purchase, shown

From the committed record of the loop closing (`artifacts/phase3-live-run.json`):

```
task     "Order dinner for four under ₹800, no beef, using mandate mnd_000001."
order    order_TVWCd7DHE9KzQh — Razorpay-minted, test mode; live fetch_order confirms:
         status: created · amount: 48300 · notes echoed:
           { conduit_cart_id: cart_000001,
             conduit_mandate_id: mnd_000001,
             conduit_catalog_version: "3" }
amount   ₹483.00 — server-computed at the commit gate; the agent never computed it
payment  captured on the MODELLED settlement rail (ADR-034)
policy   initiate_payment decided by ALLOW_MANDATE_BOUND — consent given upfront,
         no per-payment human approval
audit    hash chain verified end to end
```

The whole chain is traceable from a natural-language sentence to a real
Razorpay entity — a local mock cannot mint that order id, and the `notes`
echo ties the rail's object back to the cart, mandate, and catalog version
that produced it. (`make demo` runs this loop interactively: a split view —
conversation on the left, the machinery live on the right.)

## Architecture — the one decision that carries it

```
 user ──▶ mandate (consent, once) ─────────────┐
 "dinner for four under ₹800, no beef"         ▼
 BUYER AGENT ──MCP──▶ SENTINEL PROXY ──▶ catalog · cart (OFF-RAIL, free to iterate)
   chooses, narrates    classify·quarantine        │
   never computes money policy·audit               ▼  COMMIT GATE: re-price → diff →
                                                   │  mandate → idempotency
                                                   ▼
                                        ONE create_order  ◆ Razorpay, test mode
                                                   ▼
                                        settlement (modelled rail, ADR-034)
```

**The cart lives off the payment rail and collapses into exactly one
`create_order` at commit.** Razorpay's live 41-tool surface has no cart
primitive — that absence is why long-tail merchants are unsellable to AI. An
agent negotiates (add, check the total against its mandate, swap, re-check),
which needs a mutable object; off-rail, thinking is free and there is one
auditable moment where thinking becomes commitment. At that moment the cart
is **re-priced server-side and diffed against what the agent believed** —
divergence rejects with an itemised, per-line *why*, and the stale amount can
never bind. Every mandate failure is un-approvable (a reviewer must not
override a limit the user set), and a valid mandate resolves the
money-movement floor for the purchase's payment leg only — **a dinner mandate
can never authorise a refund** (critical test).

## Try it — hosted or local, no credentials either way

**Live demo:** https://conduit-checkout.onrender.com — open "Buy — live demo"
and press **▶ Run the whole demo**; one click sets ₹2,000 aside and buys
dinner. *(Free-tier hosting sleeps when idle: the first hit after a quiet
spell takes 30–60 seconds to wake. Everything after is instant.)*

```sh
make install && make demo     # the same app locally: buyer + merchant + operator surface
make test                     # 401 tests, deterministic, no model, no network
make eval-commerce            # the numbers above, replayed byte-for-byte
make eval-adversarial         # the unnarrowed_cart_mutation experiment
```

## The track, item by item

Track 01's brief, mapped to what is actually built (nothing here is aspirational):

| The brief asks | Where it lives |
| --- | --- |
| *"Makes a merchant transactable by an AI buyer end to end"* | The core loop: natural language → catalog → cart → commit gate → **real Razorpay test-mode order** → settlement → auditable receipt |
| *"Grow the merchant's revenue"* | The bounded upsell engine (offered 100% when affordable, accepted 33.3% in eval, never past budget) + the merchant's **agent-channel revenue view** with upsell attribution |
| *"Agent-readable catalog"* | Machine truth split from untrusted merchant prose, plus onboarding for any merchant: CSV upload or **paste a storefront URL** — schema.org/Product JSON-LD, microdata, or Open Graph parse in seconds (verified against a live Shopify store), and the agent can buy the imported item by name immediately |
| *"Conversational in-app checkout"* | The Order page: plain language in, a real order out, every step streamed |
| *"Upsell & cross-sell agent"* | Server-computed offers, suppressed before the model ever sees the unaffordable, re-validated at acceptance (TOCTOU-safe), marked on the receipt |
| *"Campaign orchestrator"* | **Not built** — the one example direction we skipped, named in LIMITATIONS rather than half-shipped |
| *"Every money action explainable, bounded and gated"* | The thesis: reason code + plain-language explanation + next step on every decision; mandate bounds; ten-step commit gate; class floors no one can approve past |
| *"Show the audit trail"* | Hash-chained ledger (`make verify-audit`), the Decisions drawer on every run, both commit verdicts side by side |
| *"One failure handled gracefully"* | Three, one-click: decline (money visibly returns), re-price (refused with an itemised diff), timeout (reconcile, never blind-retry) |

## Real versus modelled — never blurred

| Layer | Claim level |
|---|---|
| Razorpay test-mode API calls (`create_order`, `fetch_order`, `fetch_order_payments`, `fetch_tokens`, …) via the live MCP surface — every order id is Razorpay-minted | **Real** |
| Catalog, cart, mandate (Reserve Pay semantics), **and the settlement leg** (`initiate_payment` → `submit_otp`): the S2S payment API is feature-gated and not enabled on this account (verified empirically — 404 for both documented test VPAs, ADR-034), so settlement is a faithful labelled model over real order state | **Modelled** |
| AP2 (global analogue), UAP (forward-compatibility of intent only) | **Referenced** |

The distinction is surfaced **in the product** — `▢ modelled` / `◆ Razorpay ·
test` chips on every panel and entity — not only here. Full protocol map with
claim levels: [`PROTOCOLS.md`](PROTOCOLS.md). One rail nuance found
empirically: `create_order` *accepted* a `single_block_multiple_debit`
mandate order in test mode (a real order was minted with block-and-debit
arguments); the debit leg is unverifiable on this account, so the claim stays
exactly that precise.

## What broke at 2 AM

Three of the stories ([the full set](docs/spec/buildathon/11-DEMO-AND-SUBMISSION.md)):

**The accidental chaos test.** Our fixture minted the SAME order id for every
`create_order` (constant-seeded RNG). Three demo purchases collided onto one
order — and every control behaved correctly against the lie: the paid-order
guard refused the extra payment; the buyer reconciled and honestly reported
the capture it found. Why it took until Phase 7: five phases of test worlds
were single-purchase by construction, and a single-purchase world
*structurally cannot* produce an id collision. The lesson is test-world
**shape**, not coverage — a suite can be green forever on worlds too small to
contain the bug class.

**Seven instances of one disease: a control measuring something adjacent to
what you assumed.** Risk class vs binding role (a ₹5,00,000 QR passed every
amount cap). Boundary verdict vs commerce outcome (ALLOW for a refused
commit). Authorisation *existence* vs authorisation *scope* (a valid dinner
mandate resolving the money floor for a refund — the user said "you may spend
₹2,000 at Fresh Basket"; the system heard "you may move money"). The hunt
discipline now: write the one-sentence property the control should guarantee,
then check the sentence against the code.

**Trust nothing you didn't capture from a running system.** The upstream's
README claims 46 tools; the live image serves 41 — the fourth documented
docs-vs-live drift, each caught by capturing the manifest from the image. The
fifth instance was ours: "no mandate in the surface" was true of tool *names*
but not of `create_order`'s *argument schema*. The surface is the tool list
plus every schema in it.

## Limitations — the three that matter most

- **Settlement is modelled** (S2S is account-gated; ADR-034) — the order and
  every read-back are real; the decline/timeout demos run on a faithful
  labelled model and upgrade to real behind the same seam if S2S is enabled.
- **A fooled agent can bind a budget-compatible substitution** — the measured
  residual above, with a named reversal trigger.
- **Single-operator, in-process state** — the drawdown ledger's atomicity is
  a process-level lock over a repository seam; multi-process needs a database
  transaction (seam exists, work not done).

- **No campaign orchestrator** — the one example direction not attempted;
  the seams it would need (catalog, offers, audit) exist.

The unflinching list: [`LIMITATIONS.md`](LIMITATIONS.md).

## Lineage

Forked from [SENTINEL](https://github.com/codeit-ronit/SENTINEL) — a policy
enforcement, audit, and evaluation control plane built first and
independently. In CONDUIT it is a **dependency**: every tool call the buyer
makes crosses its proxy (classify → redact → quarantine → policy → audit)
before executing, which is how the track's bar — *every money action
explainable, bounded and gated* — is a property of the system rather than a
prompt. Its numbers (203 tests at fork, a 29-payload red-team A/B, 31
reconciliation scenarios) describe the control plane and are never quoted as
commerce numbers. Full provenance: [`LINEAGE.md`](LINEAGE.md) ·
[`DECISIONS.md`](DECISIONS.md) (ADR-000–040).

## Test mode and non-affiliation

Test mode only, everywhere, always: `rzp_test_*` keys, synthetic data, no
real customer, no real money, no credential in the tree or history (enforced:
`make secret-scan`). Independent project integrating the publicly published
open-source [`razorpay/razorpay-mcp-server`](https://github.com/razorpay/razorpay-mcp-server);
not affiliated with, endorsed by, or produced by Razorpay or NPCI.
