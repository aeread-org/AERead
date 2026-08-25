# Real-world verifier examples and benchmark mapping

**Status:** compact example crosswalk for the shared-runner measurement contract

**Sources checked:** [`verifier_taxonomy.md`](verifier_taxonomy.md), the PDF-checked
[`problem_bound_case_audit.md`](problem_bound_case_audit.md), and the pinned
[`refund_external_benchmark_integration.md`](refund_external_benchmark_integration.md)

The operational framework contains **five semantic verifier families** and **two cross-cutting layers**. The table gives one recognizable real-world workflow and one
best-fit benchmark for each. A benchmark may still emit secondary verifier leaves; the
mapping identifies the clearest primary use, not an exclusive label.

| Operational verifier class | One real-world case | Best-fit benchmark | What the verifier establishes |
|---|---|---|---|
| **canonical/reference** | A **retail refund** agent must leave the order, item, amount, payment method, and refund status in the approved terminal state. | **tau3-bench** `retail/base` | `terminal_state_equivalence` is a primary deterministic database leaf, not the full upstream scalar. Alternative legal tool paths may pass; natural-language assertions remain separate. |
| **rule/constraint/temporal** | A **regulated refund process** must check eligibility and obtain confirmation before mutating the customer account. | **STATE-Bench** | Official final-state requirements are deterministic; task requirements remain a separate locked-judge leaf. A temporal leaf is deterministic only after compilation to a versioned trace predicate. |
| **objective/optimum/bound** | A firm solves **procurement and scheduling** subject to costs, capacity, and feasibility constraints. | **EconEvals** | Scheduling uses an empirical random-matching comparison baseline. Procurement supports an exact reference only with its solver and certificate pinned to the same instance and objective. |
| **comparative** | A buyer agent conducts **supplier price negotiation** against a controlled seller under hidden information. | **TERMS-Bench** | The public materials support an AERead-owned TERMS-style conformance fixture; official parity waits for the simulator, defaults, and license. |
| **rater/judge** | An agent produces a **professional analyst deliverable** whose usefulness and quality cannot be fully reduced to database fields. | **GDPval** | The headline protocol is blinded occupational-expert comparison. An LLM or canned judge is a separately identified protocol, and source admission still depends on dataset licensing. |
| **simulation/statistical** | An operator manages **inventory and pricing** under uncertain customer demand across repeated business periods. | **Vending-Bench** | Expected net worth, failure risk, and outcome quantiles are a later cross-cutting pressure test. Repetition estimates a distribution; it does not create a missing policy optimum or official-adapter evidence. |
| **integrity/admissibility** | An **audited agent episode** may enter analysis only if observations, provider attempts, tool calls, state transitions, hashes, retries, and replay are complete. | **AERead EvaluationReceipt** and replay contract | `measurement_validity` admission before capability scoring. This is runner infrastructure, **not a standalone capability benchmark**. |

## Important boundaries

- In pinned tau3 `retail/base`, 112 of 114 task records declare `DB + NL_ASSERTION`.
  The database comparison is therefore a primary deterministic database leaf, not the full upstream scalar.
- In STATE, final-state requirements are the official deterministic layer, while task requirements are evaluated by a locked LLM judge. A task requirement becomes a deterministic temporal leaf only when it can be compiled into a versioned predicate over recorded trace evidence.
- EconEvals Scheduling uses an empirical random-matching baseline, not an exact optimum.
  Procurement may publish an exact reference only with a pinned solver and certificate in the declared validity domain.
- Until the official simulator, defaults, and license are available, only AERead-owned TERMS-style conformance is admitted and official parity is blocked.
- GDPval's headline protocol uses occupational experts in blinded pairwise comparison.
  LLM/canned judging is a different protocol, and the dataset license must pass admission before artifacts are vendored or redistributed.
- Vending remains a later cross-cutting pressure test. Until official V2 code, license, and state contract are public and pinned, official adapter parity is blocked.
- `simulation/statistical` modifies a semantic verifier. For example, Vending-Bench uses
  an objective verifier per run and a stochastic estimator across demand realizations.
- `integrity/admissibility` gates evidence. It must not turn a missing trace into an
  economic failure or success.
- SAGE is a nearby candidate for `rule/constraint/temporal` when service-flow graph
  transitions are machine-observable; residual semantic dialogue quality belongs under
  `rater/judge`. It still requires a pinned release and scoring-schema audit before use.
- Native `housing_v1` is the paper counterpart to EconEvals: welfare uses
  `objective/optimum/bound`, while phase order, real offers, immutable holds, capacity,
  terminal payoffs, and IR use separate `rule/constraint/temporal` leaves. `B` is the naive executable comparison baseline; `L = 0` is a separate feasible lower-bound witness; and `U` is a full-information maximum-weight relaxation. These are three typed references, not one oracle score.
- These mappings support typed within-case results. They do not create a universal
  cross-benchmark score.
