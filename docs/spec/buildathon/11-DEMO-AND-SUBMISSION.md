# 11 — Demo and Submission

## 1. What the judges said they read

From the buildathon site:

> **What we read instead of your resume:** a repo that actually runs · a 5-minute video of it working · what broke at 2 AM, and how you got out.
>
> **Four steps:** pick a track · build something real · show your work: repo, 5-min video, architecture · if it has signal, we call you in.

Three deliverables: **repo, video, architecture.** Optimise each for a stranger reading against a brief.

And note the third bullet under what they read — *"what broke at 2 AM, and how you got out."* They are explicitly asking for the failure story. You have unusually good ones.

## 2. The video

Five minutes is the stated limit. **Use three.** A tight three beats a padded five, and judges watch many.

```
0:00–0:20  The problem, concretely. A normal merchant's storefront is built for
           a human — pictures, a form, an OTP. An AI can use none of it.

0:20–0:45  Merchant onboarding. Upload a CSV or paste a storefront URL. Show
           the clock. "This merchant is now sellable to AI buyers."

0:45–1:05  Mandate. A person sets aside ₹2,000 for this merchant. One consent,
           upfront. This is the only human step in the entire flow.

1:05–2:00  THE PURCHASE. Split view. "Order dinner for four under ₹800, no
           beef." Left: the conversation. Right: cart building, totals
           recomputing, mandate draining, policy decisions firing.
           End on the Razorpay order id.

2:00–2:35  THE FAILURE. Payment declines. Order held, cart recoverable,
           retry — and the same order comes back, not a second one.
           Say it plainly: no double charge.

2:35–2:55  THE SIGNATURE. A product description contains a hidden instruction
           to add an expensive item. Show it in the catalog. Run the same
           purchase. The instruction is quarantined, the cart is unchanged,
           the attempt is in the audit log.

2:55–3:00  The numbers. Task success, mandate violations (0), over-refusal,
           attack success on/off, cost per purchase.
```

**Order is deliberate and should not be changed.** Purchase first — it is what the track asked for. Operational failure second — it proves you understand payments. Security last — it differentiates. Leading with security would signal you read a commerce brief as a safety brief.

**Narration discipline:** no talking-head intro, no logo animation, no "in today's world." Start on the problem. Every claim on screen must be visible on screen.

**The claim guard (ADR-034), verbatim, every time settlement appears:** *"The
order is real — Razorpay minted this id. The settlement is modelled — the S2S
payment API is gated on this account."* Both halves in the same breath. The
README is corrected; a video is where an overclaim slips out casually, so the
sentence is scripted here rather than trusted to improvisation.

**Record the demo with a REAL model**, not the deterministic stand-in. The
stand-in optimises the stated constraint exactly (it will buy rice and rotis
for four); a real model brings priors about what dinner is. The demo shows
judgement, not just logic — and the eval reports both.

## 3. The README

Structure, in order:

1. **One sentence.** What this is.
2. **The problem**, in three sentences. An AI buyer cannot shop at a normal merchant; the storefront is built for a human; here is what it takes to change that.
3. **The video**, linked at the top.
4. **The headline numbers.** Task success, mandate violations, over-refusal, merchant time-to-sellable, cost per purchase.
5. **The purchase**, shown — a real trace ending in a real order id.
6. **Architecture**, one diagram and one paragraph on the central decision: the cart lives off-rail and collapses into one `create_order` at commit.
7. **Quickstart.** One command, no credentials.
8. **Real vs modelled.** The table. Catalog, cart, mandate modelled; Razorpay real.
9. **What broke and how we got out.** See §5.
10. **Limitations.** Link and summarise the three most important.
11. **Lineage.** SENTINEL, what it is, what carried over.
12. **Test mode and non-affiliation.** Prominent.

**Do not:** open with a feature list, describe the stack before the problem, or claim to implement any protocol you modelled.

## 4. The architecture deliverable

One diagram plus one page. The page should answer, in order:

- Why the cart is off-rail and what that buys
- Why the model never computes money
- Why re-pricing at commit is non-negotiable
- Where enforcement lives and why it is not in the prompt
- What is modelled and what is real

Five decisions, each with the trade-off named. That is a stronger architecture document than a component inventory.

## 5. "What broke at 2 AM" — write this properly

They asked for it explicitly. You have four genuinely good ones. Pick two or three:

**The tool surface was wrong.** Built from documentation, tested against the live server, found 41 tools not 45 — three renamed, four that did not exist, and four wrong argument paths. Fix: the committed reference manifest is now a live capture, so schema parity is real rather than circular.

**The QR bypass.** Amount caps were keyed on risk class, so a QR code — which binds an amount but is not money movement — was invisible to every check. A ₹5,00,000 QR passed unexamined. Fix: separated *what a tool can hurt* from *what it commits you to*, as orthogonal axes. Third instance of the same bug class, so the fix was a CI check for the class, not a patch for the instance.

**The suspend/resume hole.** Adding a collection cap revealed that the existing disbursement cap had the same flaw — a run that suspended for approval resumed with no cap in either direction. Found by building the new control, not by testing the old one.

**The provider integration that never ran.** Wiring real models exposed that the agent loop always constructed the deterministic stand-in and never built a real provider from config. The abstraction was untested in the only way that mattered.

Write each in three sentences: what you assumed, what was actually true, what you changed. **The second and third are the strongest** — both are cases where new work exposed an existing control that was silently broken, which is the hardest class of bug to find deliberately.

And one sentence for the methodology, which is rarer and better than a bug story: the upstream's own README claims 46 tools while the live image serves 41 — the **fourth** documented docs-vs-live drift, each caught the same way, by capturing the manifest from the running image instead of trusting any document. (The fifth instance was subtler and our own: "no mandate in the surface" was true of tool names but not of `create_order`'s argument schema — the surface is the tool list *plus every schema in it*. ADR-028.)

And one observation that is more interesting than its joke: asked for "dinner
for four under ₹800," the deterministic stand-in bought **rice and rotis for
four** — constraint-perfect, gastronomically tragic. A stand-in optimises the
stated constraint *exactly*; a real model brings priors about what dinner
*is*. That is the genuine difference between testing agent **logic** (the
stand-in's job, deterministic and offline) and testing agent **judgement**
(the model's job, measured in the eval) — and it is why the demo records with
a real model while the test suite never needs one.

**The accidental chaos test.** The fixture's `create_order` minted the SAME
id for every order (a constant-seeded RNG) — Razorpay's most basic property,
violated by our own test double. Three demo purchases collided onto one
order, and every control behaved correctly against the lie: the paid-order
guard refused the extra payment, the buyer reconciled via
`fetch_order_payments` and honestly reported the capture it found. We ran a
chaos test by accident and passed it. The interesting part is WHY it took
until Phase 7: five phases of test worlds were all single-purchase by
construction, and a single-purchase world structurally cannot produce an id
collision. The lesson is about test-world SHAPE, not test coverage — a suite
can be green forever on worlds too small to contain the bug class. The first
multi-purchase world (the demo API) surfaced it in minutes.

The strongest pattern of all, seven instances deep: **a control measuring
something adjacent to what you assumed.** Risk class vs binding role (the QR
bypass). Boundary verdict vs commerce outcome (ALLOW for a refused commit).
Authorisation *existence* vs authorisation *scope* (a valid dinner mandate
resolving the money floor for a refund — the user said "you may spend ₹2,000
at Fresh Basket"; the system heard "you may move money"). Same shape every
time: the check is green, and it is honestly reporting a property one step
away from the one you needed. How we hunt it now: for every control, write
the one-sentence property it should guarantee ("a refund under a valid
mandate still needs a human") and check the sentence against the code —
sentences that read as obviously correct once written were invisible before.

There is a second named pattern worth a sentence: **validating against something you authored.** Three catches of the same disease in three different shapes — the schema-parity check that compared the fixture against a manifest transcribed from the same docs (ADR-003a, fixed by capturing live); the order-history catalog path whose only demo would have run against history we seeded ourselves (ADR-030, dropped); and a Phase 2 test asserting "the stale amount never binds" on the fixture's `.executed` list, **which does not record `create_order`** — a green check on the single most important property in the build that never actually observed a bind (caught in review, replaced with a real forward count). That third shape is the subtlest: the reference wasn't authored, the *observation surface* was assumed. The test is one question: *who wrote — or chose — the thing this check passes against?* If the answer is "we did," the check is theatre until the observation comes from outside.

## 6. Numbers to have ready

Every one traceable to a committed artefact:

- Task success rate, by scenario category, per model
- Amount accuracy — should be 100% by construction
- Mandate violations, double charges, silent substitutions — all 0
- Over-refusal rate — the usability number
- Appropriate-refusal rate on unsatisfiable scenarios
- Attack success with controls off vs on, plus false-positive rate
- Cost and p95 latency per purchase, labelled with the mode measured
- Merchant time-to-sellable, per path
- Enforcement overhead

## 7. Questions to have answers for

1. **What happens if the price changes between the agent reading and committing?** The strongest question anyone can ask. Answer: re-price at commit, itemised diff, agent re-confirms, stale amount never binds.
2. **Can it double-charge?** No, under retry, timeout, or concurrency — three separate tests.
3. **What does a merchant actually have to do?** The onboarding paths, with measured time.
4. **What stops the merchant manipulating the agent?** Quarantine plus permission narrowing. Note the unusual threat model: the attacker is the counterparty.
5. **How many legitimate purchases does your safety layer block?** The over-refusal number. Have it.
6. **What's modelled?** Catalog, cart, mandate. Razorpay calls are real. Reserve Pay is NPCI rail-layer and not reachable.
7. **What would break at scale?** Pick one your own profiling supports — the drawdown ledger's serialisation point is the honest candidate — and say what you would do about it.
8. **What did you cut?** Have the list, unapologetically.

## 8. Things that lose the round

- Claiming to implement AP2, UAP, ACP, or Reserve Pay
- Implying Razorpay affiliation or endorsement
- Any live key anywhere in the repository or its history
- A demo where the purchase is shorter than the safety explanation
- Reporting SENTINEL's scenario count for a commerce project
- Presenting over-refusal as an afterthought, or omitting it
- Being unable to explain the commit gate sequence without notes
