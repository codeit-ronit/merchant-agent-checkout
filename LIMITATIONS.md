# LIMITATIONS.md — what this project does not do

Naming your own scope cuts is a seniority signal, not an admission. This file is
deliberately unflinching. Where a limitation has a known fix, the fix is named.
First the commerce loop (CONDUIT), then the enforcement layer (SENTINEL).

## Discounts are deferred, not half-built
The catalog has no merchant discount rules, so "discounts from merchant rules
only" is vacuously satisfied (ADR-032). The reason it is deferred rather than
sketched: a discount is a *negative* money action authored by the merchant and
applied by code, and it needs the same attribution and bounding model the
upsell got — a merchant-authored rule as the only source, a cap, receipt
visibility, and suppression logic — or it becomes an unbounded price-mutation
channel. Half of that model is worse than none of it.

## Catalog-from-order-history is dropped (ADR-030)
Verified live: order entities carry no line items and a fresh test account's
`notes` are empty. Demonstrating "zero-effort catalog derivation" would require
seeding our own history — a circular demo. The path is real only for merchants
whose integrations already write item-shaped `notes`; this account cannot
represent them.

## Agents can be price-discriminated against
A merchant could quote AI buyers higher than humans. We do not prevent this —
there is no human-facing price to compare against. It is a real property of
agent-readable catalogs; detection would require cross-referencing the
merchant's human storefront.

## Modelled versus real — the line, stated plainly
Catalog, cart, and mandate are MODELLED services over real primitives. Every
Razorpay call is REAL (test mode). Reserve Pay is an NPCI rail-layer product
with no Razorpay API: we model its semantics; we do not integrate it. See
`PROTOCOLS.md` for every protocol's claim level.

## Commerce state is in-process
The drawdown ledger's atomicity is a process-level lock over a repository
seam (ADR-032). Single-operator local deployment, as inherited. Multi-process
deployment would move the lock into a database transaction — the seam exists,
the work is not done.

---

# SENTINEL — the enforcement layer's own limitations

## The audit ledger is tamper-EVIDENT, not tamper-PROOF
The hash chain makes retroactive alteration *detectable*: change entry N and
every entry after it fails verification. But anyone who can write to the
database can recompute the entire chain from any point forward, and it will
verify cleanly. **Real tamper-resistance requires an external anchor** (periodic
publication of the head hash to an append-only external service such as an
RFC 6962-style transparency log), or genuine write-once storage. Neither is
implemented. Overclaiming here is worse than the limitation.

## Prompt injection is not "solved" — nobody has solved it
The quarantine wrapper is a **mitigation** that reduces attack success; it does
not eliminate it. The real defence is **permission narrowing**: when untrusted
content enters a run, the agent's permissions shrink, so it does not matter
whether the model was fooled. Expect the red-team L1 metric (behaviour altered,
no unauthorised action) to be non-zero even with guardrails on. L3 (exfiltration)
and L4 (unauthorised money movement / irreversible write) must be zero. The goal
is to make being fooled *harmless*, not impossible.

## The injection detector is a heuristic with unmeasured coverage on novel payloads
It is a *signal* that raises scrutiny, never a *gate* that grants passage. A
classifier that fails open on a novel payload would create false confidence, so
it never decides on its own.

## The policy language is deliberately limited
A closed set of rule types, not an expression DSL. An expressive DSL is a new
attack surface and an untestable space. There are real policies this cannot
express (e.g. arbitrary cross-field arithmetic); that is a chosen cost. Adding a
rule type is a reviewable event with a test.

## The fixture server is a faithful double only to the extent the parity check catches drift
Evals pass against fixtures. If upstream schemas change and the schema-parity
check misses it, evals could pass against a world that no longer exists. The
parity check is the mitigation; it is not a proof. **Update:** the fixture is now
reconciled to a *live capture* of `razorpay/mcp` and verified against the real
server (`make check-schemas-live`, ADR-003a) — so parity is genuine today; the
residual risk is future upstream drift between live re-captures, which the
reconciliation surfaces as UNCLASSIFIED (denied) / STALE (warned).

## Deliberately not built (single operator, local deployment)
- **Multi-tenancy and real authentication.** Single trusted operator.
- **Encryption at rest for the token→value map.** The map is local and
  synthetic-only; a production deployment would encrypt it.
- **Protection against a malicious operator.** SENTINEL constrains the *agent*,
  not the human running it.
- **Streaming / partial tool results.**
- **Formal verification of policy completeness.** We test; we do not prove.
- **Production-grade inference.** Free-tier providers are rate-limited by design
  and unsuitable for real throughput. The architecture supports any provider;
  this deployment uses free ones.

## What would break first at Razorpay scale
Candidates, to be confirmed by profiling: the audit ledger's single-writer
serialisation under concurrency; the token store becoming a hot path; approval-
queue latency dominating end-to-end time in practice. The single-writer ledger
is the most likely first bottleneck; the fix is a per-shard chain with a
periodic cross-shard anchor.
