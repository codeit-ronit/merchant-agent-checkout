# Eval suites — two products, two counts

**Read this before quoting any eval number.**

## `evals/scenarios/` — SENTINEL's golden set (31 scenarios)

Inherited from the control plane this repo forked from. The 31 scenarios test
**reconciliation and dispute** workflows (9 happy-path, 7 hard-but-correct,
4 correct-refusal, 6 policy-triggering, 5 adversarial-lite). They validate the
enforcement layer the commerce loop builds on — the proxy, the policy engine,
the audit chain.

**They are not about commerce.** They are kept as regression coverage of the
dependency (ADR-029), not retired — but no CONDUIT-facing document may report
"31 scenarios" as if it described the checkout.

## `evals/commerce/` — CONDUIT's suite (built from Phase 6)

The commerce scenarios: satisfiable purchases, constrained purchases, correctly
unsatisfiable constraints, failure recovery, policy-triggering, adversarial
catalog content. Separate count, separate report, per
`docs/spec/buildathon/08-EVAL.md`. The README reports **this** number.
