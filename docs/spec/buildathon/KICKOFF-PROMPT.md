# KICKOFF-PROMPT.md

## Setup

1. In the forked repo, create `docs/spec/buildathon/` and copy documents 00–11 into it.
2. Append `CLAUDE-ADDENDUM.md` to the repo root `CLAUDE.md`.
3. Start Claude Code at the repo root.
4. **One phase per session.** Fresh session each phase.

---

## Phase 0 — Ground truth

```
We are building CONDUIT, a Razorpay Buildathon submission (Track 01: AI Growth
& Agentic Commerce). The spec is in docs/spec/buildathon/. Read these first,
in order:

  00-START-HERE.md
  01-BRIEF-AND-THESIS.md
  02-ARCHITECTURE.md          <- authoritative
  07-FAILURE-MODES.md         <- read early; it shapes everything before it
  10-BUILD-ORDER.md
  CLAUDE.md                   <- repo root, now with the CONDUIT addendum

THE IDEA, so you can evaluate your own choices against it:

An AI buyer cannot shop at a normal merchant. The storefront is built for a
human -- pictures, a form, an OTP -- and an agent can use none of it. Track 01
asks us to make a merchant transactable by an AI buyer end to end.

Two design decisions carry the whole project:

1. The cart lives OFF the payment rail and collapses into exactly one
   create_order at commit. Razorpay has no cart primitive (confirmed against
   our live 41-tool manifest), and that absence is why long-tail merchants are
   unsellable to AI. An agent negotiates -- add, check total, swap, re-check --
   which needs a mutable object. So the agent thinks for free, and there is one
   auditable moment where thinking becomes commitment.

2. The model NEVER computes money. Every total is calculated by deterministic
   code from live catalog truth. Critically, the cart is RE-PRICED server-side
   at commit and diffed against what the agent believed. Price and stock change
   between read and commit; a system that trusts the agent's arithmetic is one
   hallucinated total away from binding the wrong amount.

THE MOST IMPORTANT INSTRUCTION:

The commerce loop is the deliverable. SENTINEL is how it clears the bar.
SENTINEL already answered no brief once by being pure infrastructure. Do not
repeat that. Do not refactor SENTINEL -- extend it only where the commerce
loop needs something it lacks.

YOUR TASK THIS SESSION IS PHASE 0 ONLY. Do not start Phase 1.

Phase 0 is ground truth. This repository has been bitten three times by config
that disagreed with a live server (3 renamed tools, 4 invented tools, 4 wrong
argument paths, and a QR amount field that bypassed every cap). Do not build on
assumed API shape.

Verify, empirically, against a running razorpay/mcp with test-mode keys:

  1. Is the 41-tool manifest still current? Re-run make check-schemas-live.
  2. create_order's live schema: fields accepted, how amount and currency are
     represented, whether notes can carry a cart reference, what it returns.
  3. The initiate_payment -> submit_otp flow in test mode: required arguments,
     what the OTP step actually does with test credentials, and -- most
     importantly -- HOW TO DELIBERATELY TRIGGER A DECLINE. The failure path is
     a deliverable, so you must be able to reproduce it on demand. If declines
     cannot be reliably triggered in test mode, say so and find the timeout
     path instead.
  4. Do Razorpay's APIs accept a native idempotency key header? If yes we
     propagate ours rather than running a parallel mechanism.
  5. How fetch_tokens represents a saved instrument (the mandate binds to one).
  6. What fetch_all_orders actually returns, and whether notes carries anything
     item-shaped -- this determines whether the zero-effort catalog derivation
     path is real or should be dropped.

Then, housekeeping that must happen before any building:

  7. SENTINEL's 31 eval scenarios test reconciliation and disputes -- a
     different product. Either retire them or scope them explicitly as separate,
     so the commerce README never reports a number that doesn't describe it.
  8. Write LINEAGE.md: what SENTINEL is, that it was built first and
     independently, what carries over, what is new.
  9. Write PROTOCOLS.md: which layer each protocol occupies (MCP/A2A for
     discovery, ACP/UCP for checkout, AP2 for authorization, x402 and card
     rails for settlement), what we modelled, what we did not. State plainly
     that Reserve Pay is an NPCI rail-layer product, not a Razorpay API, and
     that UAP is not public.
  10. Pin the repo's test count. The number that means something is what the
      runner collects: pytest --collect-only -q | tail -1. A stale-count
      spread across docs is how a wrong number reaches a README a judge then
      checks. One figure, used everywhere.

Record every finding in DECISIONS.md with the date and how you verified it.
Where you could not verify something, say so explicitly rather than guessing.

EXIT CRITERIA: check every box in 10-BUILD-ORDER.md Phase 0.

Start by reading the spec. Then give me a short plan for this session, plus
anything in the spec you think is wrong or underspecified. I would rather hear
a disagreement now than discover a silent workaround later.

Do not write code until I have seen the plan.
```

---

## Phases 1–8 continuation

```
Continuing CONDUIT. Read CLAUDE.md and docs/spec/buildathon/02-ARCHITECTURE.md,
then DECISIONS.md to pick up where the last session ended.

This session is PHASE <N> ONLY. Read 10-BUILD-ORDER.md for its scope and exit
criteria, plus the component spec it references.

Before starting:
1. Confirm every Phase <N-1> exit criterion is actually met. Fix any that
   aren't before new work.
2. Complete any VERIFY FIRST block in this phase's spec, against a running
   server -- not from documentation, not from these specs.
3. Give me a short plan, including anything you think the spec has wrong.

Then build. Keep DECISIONS.md current with trade-offs named. Stop when the exit
criteria are met -- do not roll into the next phase.

Remember: the commerce loop is the deliverable. If you find yourself improving
SENTINEL rather than building the purchase, stop and tell me.
```

---

## Phase 7 (UI) — use this instead

```
Continuing CONDUIT. This session is PHASE 7, the interface. Read
docs/spec/buildathon/09-UI.md fully before anything else.

The signature element is the SPLIT VIEW: conversation on the left, machinery on
the right -- cart assembling, totals recomputing, mandate draining, policy
decisions firing, all live and synchronised. The moment to design for is the
agent saying "adding paneer tikka" while simultaneously a line item appears, the
total recomputes, and the mandate bar shrinks. That synchrony is the demo.

DESIGN PASS BEFORE CODE. Produce a compact token system first:
  - Palette: 4-6 named hex values, chosen for THIS brief. The information colour
    carries is STATE: authorised, spending, committed, blocked, exhausted. All
    must be distinguishable WITHOUT colour -- this is financial software.
  - Type: a display face, a body face, and a genuine monospace for amounts, ids
    and hashes. Amounts MUST be tabular-figure aligned.
  - Layout: ASCII wireframes for the split view and the merchant console.
  - Signature: the split view. Spend boldness there; keep everything else quiet.

The subject is an agent spending someone's money under a limit they set. The
vernacular is authorisation, drawdown, commitment, receipt -- a ledger, not an
app. Do not default to the three looks AI design clusters around (cream + serif
+ terracotta; near-black + acid accent; broadsheet hairlines). Spend the freedom
on something specific to money moving under a limit.

Motion: used once, precisely, on the mandate drawdown. It is the only place a
value moves continuously and where motion carries meaning. Restraint everywhere
else.

Copy: write from the user's side. "₹2,000 set aside for Fresh Basket", not
"mandate created". "Blocked: this would take you ₹340 over your limit", not
"DENY_MANDATE_EXHAUSTED".

Show me the design plan and wireframes before writing any component.
```

---

## Session end

```
Wrap up:

1. Check off every exit criterion met in 10-BUILD-ORDER.md.
2. Ensure DECISIONS.md records every real choice with its trade-off named.
   Include anything that surprised you or contradicted an assumption -- those
   entries are the most valuable in the file, and two of them will go in the
   README's "what broke at 2 AM" section.
3. List what is not done in this phase and why.
4. List anything you assumed because you could not verify it.
5. Confirm: CI green, no credentials in the repo or history, no PII on any
   output surface, no float in any money path.
6. Flag anything in the spec that turned out wrong or underspecified.
```

---

## Checks to run yourself between sessions

Do not delegate these.

- `git log -p | grep -i "rzp_live"` — must return nothing, ever
- Read the newest `DECISIONS.md` entries. No named trade-offs means the log is not being kept properly.
- **After Phase 3, do the purchase by hand.** A natural-language constraint producing a real Razorpay order id is the project. If that does not work end to end, nothing after it matters.
- After Phase 6, clone into a fresh directory with no credentials and run the commerce evals in replay mode. If they do not reproduce, the cassette layer is not doing its job.
