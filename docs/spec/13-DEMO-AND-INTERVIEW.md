# 13 — Demo, README, and Interview Preparation

## Part A — The README

The README is the artefact most people will actually read. It should be readable in four minutes and should make someone want to open the repo.

**Required structure, in this order:**

1. **One sentence.** What this is. No preamble.
2. **The problem**, in three sentences. Agents are being pointed at money-moving APIs; the standard guardrail is a sentence in a prompt; that is not a boundary you can test or trust.
3. **The three headline numbers.** Attack success rate off, on, and the false-positive rate. Above the fold.
4. **The guardrail overhead number.** What safety costs in latency and money.
5. **Architecture diagram**, with one paragraph explaining the central decision: enforcement at the tool-call boundary, not in the prompt.
6. **Quickstart.** One command. Fixture mode. No credentials required.
7. **Demo video**, 90 seconds, embedded or linked at the top.
8. **What this is not.** The scope boundaries from `01` §4.
9. **Limitations.** Link to `LIMITATIONS.md` and summarise the three most important honestly.
10. **Test mode and non-affiliation notice.** Prominent, not buried in a footer.

**Do not:** open with a feature list, describe the tech stack before the problem, use the word "revolutionary," or claim to have solved prompt injection.

## Part B — The demo video

90 seconds. No talking-head intro. No logo animation.

```
0:00–0:10  The bank statement on screen. Looks entirely normal.
0:10–0:20  Reveal the text layer. An instruction is embedded.
0:20–0:40  Guardrails off. The agent reads it, follows it, calls the refund
           tool. It executes. Show the fixture state change.
0:40–1:05  Guardrails on. Same statement, same task. The agent reports the
           embedded instruction instead of acting on it. If it does attempt
           the call, policy denies it with a plain-language reason and the
           attempt lands in the audit log as a security event.
1:05–1:20  The aggregate table: A%, B%, C%.
1:20–1:30  The audit chain verifying. Then tamper with an entry. It breaks,
           at the exact position.
```

**Narration discipline:** say "and if it does attempt the call." Do not claim the model was never fooled. The claim is that it does not matter whether the model was fooled — that is a stronger claim and a true one.

## Part C — Interview preparation

The selection process is Buildathon → Builder Challenge → Technical Deep Dive → Hiring Manager. Rounds 3 and 4 are where this project earns its value, and where an unrehearsed answer costs it.

### The questions that will be asked

**"Why not just put it in the system prompt?"**
The core question. Answer: a prompt is a request to the model; a proxy is a property of the system. Prompts cannot be unit tested, do not produce artefacts when they succeed or fail, and degrade under adversarial input and model updates. Then offer the demonstration: a completely different MCP client pointed at the proxy is subject to the same policy. That is not true of any prompt.

**"What does your safety layer cost?"**
Have the measured number ready — added p95 latency, percentage of run cost, and accuracy delta. If the overhead is meaningful, say so and discuss the tradeoff. A real number honestly interpreted beats a flattering one.

**"Did you solve prompt injection?"**
No. Nobody has. Explain the two-mechanism design: quarantine is a mitigation that reduces success rate; permission narrowing is the guarantee that makes success harmless. Point at the L1 number being non-zero while L3 and L4 are zero. **This answer is the single strongest thing you can say in the interview,** because most candidates will claim to have solved it.

**"What would break first at Razorpay's scale?"**
Have a real answer. Candidates: the audit ledger's single-writer serialisation under concurrency; the policy engine's per-call latency at high throughput; the token store becoming a hot path; approval queue latency dominating end-to-end time in practice. Pick the one your own profiling actually supports and say what you would do about it.

**"Your audit log — could I fake it?"**
Yes, if you can write to the database. It is tamper-evident, not tamper-proof. Then say what real tamper-resistance requires: an external anchor or write-once storage, neither of which is implemented. **Volunteering this before being pushed is the answer that builds trust.**

**"Which of your controls actually did the work?"**
The ablation table. If it shows permission narrowing doing most of the work and quarantine doing less than you expected, say so. Reporting a result that contradicts your own design intuition is the most credible thing you can do.

**"How did you handle model non-determinism in your evals?"**
N runs per scenario, variance reported as a metric rather than averaged away, model version pinned, high-variance scenarios flagged separately. Most candidates have not thought about this at all.

**"What did you cut?"**
Have the list ready and unapologetic: multi-tenancy, encryption at rest, a general policy DSL, formal verification. Each with a one-sentence reason. Naming your own scope cuts confidently reads as seniority; being caught not having thought about them reads as the opposite.

**"Walk me through what happens when the agent calls a tool."**
The fourteen-step lifecycle from `02` §4. Know it cold, in order. This is the question that separates people who built it from people who prompted it into existence.

### Framing for Round 4

The hiring manager question is not "is this impressive." It is "will this person be useful in six months."

The framing:

> Agent Studio is in beta and the no-code builder is about to let non-engineers point agents at money-moving APIs. The interesting problem there is not building more agents — it is knowing what an agent is allowed to do, proving it, and being able to tell whether a change made things worse. I built the smallest honest version of that, measured it, and documented what does not work.

### Things that will lose the round

- Claiming affiliation, endorsement, or that you tested against Razorpay's production systems.
- Overstating the audit guarantee.
- Being unable to explain the tool call lifecycle without notes.
- Presenting the false-positive rate as an afterthought, or omitting it.
- Any live key anywhere in the repository or its history.
- Claiming prompt injection is solved.

### The honest self-assessment to have ready

Know the weakest part of your own project before someone finds it. Strong candidates: the injection detector is a heuristic with unmeasured coverage on novel payloads; the fixture server is a faithful double only to the extent the schema parity check catches drift; the policy language is deliberately limited and there are real policies it cannot express.

Being first to name the weakest part of your own work is the most reliable seniority signal available in a technical interview.
