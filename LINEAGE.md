# Lineage

This repository was **forked from [`codeit-ronit/SENTINEL`](https://github.com/codeit-ronit/SENTINEL)** —
a policy-enforcement, audit, and evaluation control plane for LLM agents on
payment infrastructure. SENTINEL was **built first and independently**, before
this buildathon: 24 architectural decisions (`DECISIONS.md` ADR-001–024), 203
offline-reproducible tests, a 29-payload prompt-injection red-team, and live
verification against the real `razorpay/mcp` server (41 tools, test mode).

This is a **git-history fork** (GitHub does not allow forking a repo into the
account that already owns it). The complete SENTINEL history is preserved in this
repo's `git log`, and the original is wired as a remote:

```
git remote -v
# origin    → codeit-ronit/merchant-agent-checkout   (this repo)
# sentinel  → codeit-ronit/SENTINEL                   (the frozen original)
```

The commit **"Fork point: buildathon Track 01 begins here"** is the clean line in
`git log` between the two bodies of work.

**What carried over** (the enforcement foundation, already built and tested):
the pure policy engine, the MCP proxy boundary, PII redaction + tamper-evident
audit chain, the binding-role / mandate-ready amount caps, and the offline eval +
red-team harness.

**What is new here** (the buildathon work, built on top): the **agentic commerce
loop** — how a merchant becomes sellable to AI buyers — and the **mandate** object
(a consented spending envelope) that gates money movement without a human tapping
at each purchase.

SENTINEL remains a **separate, frozen** repository; this repo builds on it and
does not modify it.
