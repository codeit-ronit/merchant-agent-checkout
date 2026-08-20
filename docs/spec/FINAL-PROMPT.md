# FINAL-PROMPT.md

## How to use this

1. Create an empty repo, `sentinel/`.
2. Copy the spec pack into `docs/spec/`.
3. Copy `CLAUDE.md` to the repo root.
4. Start Claude Code in the repo root and paste the kickoff prompt below.

Run **one phase per session.** Phases are long; a fresh session per phase keeps context clean. Start each subsequent session with the continuation prompt at the bottom.

---

## Kickoff prompt — Phase 0

```
You are building SENTINEL, a policy enforcement, audit, and evaluation control
plane for LLM agents that operate on payment infrastructure.

The complete specification is in docs/spec/. Read these before writing anything,
in this order:

  00-START-HERE.md
  01-CONTEXT-AND-PROBLEM.md
  02-ARCHITECTURE.md          <- authoritative; overrides conflicts elsewhere
  03-DATA-CONTRACTS.md
  11-BUILD-ORDER.md
  CLAUDE.md                    <- at repo root; governs how you work here

Then read 04 through 10, 12, 13, and 14 for the components you will reach later.

THE CENTRAL IDEA, so you can evaluate your own choices against it:

Agents are increasingly pointed at APIs that move money. The standard guardrail
is a sentence in a system prompt. That is a request to the model, not a property
of the system: it cannot be unit tested, produces no artefact when it works or
fails, and degrades under adversarial input and model updates. SENTINEL moves
enforcement to the tool-call boundary, in a process the model does not control,
and then proves the enforcement works with a deterministic evaluation harness
and an adversarial red-team suite.

Every design decision serves that claim. If a choice does not, question it.

YOUR TASK THIS SESSION IS PHASE 0 ONLY. Do not start Phase 1.

Phase 0 has two halves, and the first is more important:

--- HALF ONE: RESEARCH AND VERIFY ---

This project integrates with actively developed external systems. Your training
data is likely stale on all of them, and free-tier model catalogues in
particular change monthly. Do not write integration code from memory.

A) Inference providers -- YOU MUST VERIFY THIS EMPIRICALLY

   We are NOT using a vendor agent SDK. The runtime is model-agnostic by design:
   an in-house agent loop (~200 lines) over a thin provider abstraction. Read
   02-ARCHITECTURE.md section 2 for why -- it is a design goal, not a workaround.

   - Identify current free-tier inference providers that support TOOL CALLING /
     FUNCTION CALLING on their free models. Candidates worth checking include
     Groq, Google Gemini, Cerebras, OpenRouter, GitHub Models, and Mistral, but
     verify what is actually available now rather than trusting any list.
   - Select TWO. One primary, one fallback and second model for comparison.
   - VERIFY TOOL CALLING WITH A REAL CALL. Documentation is not sufficient
     evidence. A provider with generous limits and unreliable tool calling is
     worthless for this project, and you will not discover that from a docs page.
   - For each: current RPM / RPD / TPM limits, exact tool-call request and
     response format, how token usage is reported, how rate limits are signalled
     (status codes, headers, retry-after), and free-tier data-handling terms.
   - Note that all our fixture data is synthetic, so training-on-inputs terms
     are not a blocker -- but record the finding, because the README states it.

   These limits change monthly. Everything goes in config with the date checked,
   never hardcoded.

B) Razorpay MCP server (razorpay/razorpay-mcp-server)
   - Read the repository and its published documentation.
   - Run it locally with TEST-MODE keys and call tools/list.
   - Capture the full tool manifest and commit it as a reference artefact.
   - For each tool, determine what it actually does -- do not infer from the
     name. You will classify all of them in Phase 1.
   - Determine how monetary amounts are represented (unit and type).
   - Determine whether the APIs support native idempotency keys.

Record every finding in DECISIONS.md with the date and the source. Where you
verified something empirically, describe the experiment.

If you cannot verify something, say so explicitly in DECISIONS.md rather than
guessing. In a system that gates money-moving actions, a silent wrong assumption
is far worse than a recorded open question.

--- HALF TWO: SCAFFOLD AND CONTRACTS ---

1. Repository structure per 02-ARCHITECTURE.md section 6.
2. Docker Compose, Makefile, CI skeleton, secret scanning, pre-commit hooks.
3. EVERY data contract in 03-DATA-CONTRACTS.md. Typed, validated at
   construction, immutable, schema-versioned, redaction-aware.
4. The full reason-code enum with rendering templates.
5. Contract tests: round-trip serialisation, schema-version compatibility, and
   the redaction-serialisation test asserting no PII pattern appears in output.
6. CI green on push.

EXIT CRITERIA -- check every box in 11-BUILD-ORDER.md Phase 0 before stopping.

HOW TO WORK:

- Types before behaviour. Tests alongside, not after.
- Fail closed everywhere. Never allow on exception, never allow by default.
- Integer minor units for money. Never floats.
- Enumerated reason codes. Never free-text reasons.
- No PII on any output surface, ever.
- Prefer boring: small closed rule sets over expressive DSLs, explicit enums
  over strings, deterministic over clever.
- No model access is needed for Phases 0 through 3. Everything in the
  enforcement core is deterministic and tested with a scripted agent.
- Record decisions in DECISIONS.md as you make them, with the trade-off named.
  A decision without a named cost is not a decision.
- When genuinely uncertain, choose the more restrictive behaviour and flag it.

Start by reading the spec. Then give me a short plan for this session -- what you
will research, what you will build, and anything in the spec you think is wrong
or underspecified. I would rather hear a disagreement now than discover a silent
workaround later.

Do not start writing code until I have seen the plan.
```

---

## Continuation prompt — Phases 1 through 8

```
Continuing SENTINEL. Read CLAUDE.md and docs/spec/02-ARCHITECTURE.md first, then
DECISIONS.md to pick up where the last session left off.

This session is PHASE <N> only. Read docs/spec/11-BUILD-ORDER.md for its scope
and exit criteria, and the component spec it references.

Before you start:
1. Confirm every exit criterion from Phase <N-1> is actually met. If any is not,
   fix it before starting new work.
2. Complete any RESEARCH FIRST block in this phase's component spec. Verify
   against live documentation, not memory, not the spec.
3. Give me a short plan, including anything you think the spec has wrong.

Then build. Keep DECISIONS.md current as you go. Stop when the exit criteria are
met -- do not roll into the next phase.
```

---

## Session-end prompt

```
Wrap up this session:

1. Check off every exit criterion met in docs/spec/11-BUILD-ORDER.md.
2. Ensure DECISIONS.md records every real choice made, each with its trade-off
   named. Include anything that surprised you or contradicted an assumption --
   those entries are the most valuable ones in the file.
3. List what is not yet done in this phase and why.
4. List anything you had to assume because you could not verify it.
5. Confirm: CI green, no credentials in the repo or its history, no PII on any
   output surface.
6. Flag anything in the spec that turned out to be wrong or underspecified, so
   it can be corrected before the next phase.
```

---

## Sanity checks between sessions

Run these yourself. Do not delegate them.

- `git log -p | grep -i "rzp_live"` — must return nothing. Ever.
- Read the newest `DECISIONS.md` entries. If none of them names a trade-off, the log is not being kept properly.
- Confirm the phase's exit criteria are genuinely met, not optimistically checked.
- After Phase 4, verify the central demonstration by hand: a denied money-movement call, from the command line, with a plain-language reason. That is the project. Everything after it makes it measurable and presentable.
- After Phase 5, clone the repo into a fresh directory with no credentials set and run the eval suite in replay mode. If it does not reproduce your committed numbers, the cassette layer is not doing its job.
