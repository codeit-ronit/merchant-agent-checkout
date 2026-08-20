# 04 — Policy Engine

## 1. What is currently true

The prevailing way to constrain an agent is a sentence in a system prompt. That sentence is unversioned, untested, invisible in logs, and negotiable by anything that gets into the model's context. When someone asks "what is this agent allowed to do?", the honest answer today is "read the prompt and hope."

## 2. What we are solving

**Make the answer to "what is this agent allowed to do?" a file that a non-engineer can read, a test can assert on, and the runtime cannot ignore.**

Four properties, all required:

| Property | Meaning |
|---|---|
| **Externalised** | Policy lives in versioned config, not in code and not in prompts. |
| **Deterministic** | Same context + same policy = same decision, always. |
| **Explainable** | Every decision names the rule that caused it, in plain language. |
| **Fail-closed** | Absence of a permitting rule is a denial. Errors are denials. |

## 3. How we proceed

### 3.1 The purity constraint

```
evaluate(policy_set, decision_context) -> PolicyDecision
```

No I/O. No clock. No network. No database. No randomness. No global state.

Time, accumulated spend, call counts, and approval status are all **injected** via `DecisionContext` by the caller.

The payoff is large and immediate:
- Exhaustive unit testing with hand-built contexts.
- Property-based testing (see 3.6).
- **Replay**: take any historical run's trace, apply a proposed new policy, and see exactly which decisions would change. This powers the policy editor's dry-run mode and is a genuinely impressive demo.
- Reasoning about the engine without reasoning about the world.

Enforce purity structurally: the policy package must not import any I/O module. Add a lint rule or an import-graph test that fails CI if it does. Do not rely on discipline.

### 3.2 Rule types — deliberately constrained

**Do not build a general expression language.** A DSL with arbitrary evaluation is a new attack surface, an untestable space, and a maintenance burden. Instead, provide a closed set of rule types, each with a narrow, well-understood evaluation.

Start with these. Add a type only when a real scenario demands it, and record why in `DECISIONS.md`.

| Rule type | Constrains | Example intent |
|---|---|---|
| `tool_class` | Disposition by risk class | Money movement always escalates |
| `tool_allow` / `tool_deny` | Named tools | This agent may only touch settlement reads |
| `amount_cap` | Per-call, per-run, per-window monetary ceilings | No single refund over ₹X; no more than ₹Y per run |
| `rate_limit` | Call counts per tool or class per window | At most N refunds per hour |
| `entity_scope` | Which entities may be targeted | Only payments belonging to the merchant in scope |
| `argument_constraint` | Declarative predicates on argument values | Currency must be INR; date range under 90 days |
| `time_window` | When actions are permitted | No payouts outside business hours |
| `approval_required` | Which conditions force escalation | Any new counterparty; any amount over threshold |
| `provenance_guard` | Behaviour when quarantined content is in context | If injection suspected, downgrade all writes to escalation |
| `counterparty_novelty` | First-time destinations | Never auto-approve a payout to an unseen fund account |

The last two are where the interesting work is.

**`provenance_guard`** is the structural answer to prompt injection: *if the model's context contains untrusted text, then its permissions narrow.* Not "the model should be careful" — the permission set actually shrinks. This is the rule that makes the red-team A/B produce a clean result.

**`counterparty_novelty`** encodes a real payments-fraud pattern: the dangerous action is usually not a large amount, it is a *new destination*. Including it shows domain understanding rather than generic security thinking.

### 3.3 Evaluation semantics

Specify these explicitly and test them. Ambiguity here is how policy engines produce surprises.

1. **Evaluation order.** All rules evaluate; no short-circuit. Collecting every match is what makes explanations useful.
2. **Combination.** Most-restrictive-wins. `DENY` beats `REQUIRE_APPROVAL` beats `ALLOW`, unconditionally. A permissive rule can never override a restrictive one.
3. **Default.** No matching permitting rule → `DENY` with `DENY_FAIL_CLOSED`.
4. **Errors.** Any exception during evaluation → `DENY` with `DENY_POLICY_EVALUATION_ERROR`, plus abort the run. An engine that throws is an engine you cannot trust for the rest of that run.
5. **Precedence is by restrictiveness, not by file order.** Order-dependent policy is a bug factory. Two people editing the same file should not be able to change behaviour by reordering.

### 3.4 Policy file format

Human-readable, versioned, commentable. Requirements:

- A header with policy set id, version, description, and author.
- Every rule has a stable `id`, a `description` written for an operations person, and its type-specific parameters.
- Rules can be tagged and grouped for readability, but grouping must not affect evaluation.
- The file validates against a schema at load time. Invalid file → refuse to start.
- Monetary amounts are expressed unambiguously, with currency and minor-unit handling stated. **Never floats.** Integer minor units throughout the system.

> **RESEARCH FIRST:** Confirm how Razorpay's APIs represent monetary amounts in the tool schemas (unit and type). Match that representation exactly in `DecisionContext` so no conversion happens inside the engine. Currency conversion inside a policy engine is a category error and a bug source.

Ship at least three policy sets:

| Set | Purpose |
|---|---|
| `strict` | Default. Money movement always escalates. Read-only auto-allowed within scope. |
| `permissive` | **The red-team baseline.** Guardrails effectively off. Used only to produce the "before" half of the A/B. Loading it must print a loud warning and be blocked in live mode. |
| `reconciliation-readonly` | Minimal scope for the read-only agent. Demonstrates least privilege. |

### 3.5 Explanation quality

Every decision produces one sentence an operations person can act on.

Bad: `DENY: rule_47 predicate false`
Good: `Blocked: refunds over ₹10,000 need approval from a finance reviewer. This one was ₹24,500.`

Treat explanation quality as a tested requirement, not a nicety. Add a test asserting every reason code has a non-empty template, that every template renders without error against a representative context, and that no rendered explanation leaks unredacted PII.

### 3.6 Property-based testing

Purity makes this cheap and it will find real bugs. Properties to assert over generated contexts and policy sets:

- **Monotonicity.** Adding a restrictive rule never makes a previously-denied call allowed.
- **Determinism.** Same inputs, N runs, identical output including matched-rule ordering.
- **Fail-closed under mutation.** Randomly corrupt a policy set; the decision distribution shifts toward denial, never toward allow.
- **Approval binding.** A decision that was `REQUIRE_APPROVAL` never becomes `ALLOW` under an approval whose argument hash differs by even one byte.
- **Class floor.** No policy set can be written that auto-allows a `MONEY_MOVEMENT` tool without approval. This is a system invariant enforced above the policy layer — it must be impossible to configure away, and there must be a test proving a maliciously-written policy file cannot do it.

That last property is important. It is the difference between "our default config is safe" and "the system is safe."

### 3.7 The dry-run simulator

Exposed via API and UI. Input: a candidate policy set plus a set of historical run ids. Output: for each recorded decision, what the new policy would decide, and a summary of what changed — newly denied, newly allowed, newly escalated.

**Newly allowed is the row that matters.** It should be rendered as a warning, prominently, because loosening policy is the change most likely to be made carelessly.

## 4. Acceptance criteria

- [ ] Engine package has zero I/O imports, enforced by a CI check.
- [ ] Every rule type has unit tests covering match, non-match, and boundary conditions.
- [ ] Property tests for all five properties in 3.6 pass.
- [ ] A malformed policy file causes startup failure, with a test proving it.
- [ ] An exception inside a rule produces `DENY` and aborts the run, with a test proving it.
- [ ] No policy file can be written that auto-allows money movement — test proves this.
- [ ] Every reason code has a rendered explanation template; a test asserts full coverage and no PII leakage.
- [ ] Dry-run replay produces a correct diff against at least one recorded historical run.
- [ ] Median policy evaluation latency is measured and recorded in the README.
