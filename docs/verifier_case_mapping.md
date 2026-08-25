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
| **canonical/reference** | A **retail refund** agent must leave the order, item, amount, payment method, and refund status in the approved terminal state. | **tau3-bench** `retail/base` | `terminal_state_equivalence` is a primary deterministic database leaf, not the full upstream scalar. In the pinned split, 112 of 114 tasks declare `DB + NL_ASSERTION`, so natural-language assertions remain a separate leaf. |
| **rule/constraint/temporal** | A **regulated refund process** must check eligibility and obtain confirmation before mutating the customer account. | **STATE-Bench** | The final-state requirements are the official deterministic layer; non-empty task requirements use the locked task-requirements judge. An empty task-requirement set uses the official deterministic identity shortcut and does not call a judge (task 142: 5 state, 0 task). A deterministic temporal leaf requires a requirement compiled into a versioned predicate over recorded trace evidence. |
| **objective/optimum/bound** | A firm solves **procurement and scheduling** subject to costs, capacity, and feasibility constraints. | **EconEvals** | Scheduling uses an empirical random-matching comparison baseline, not an exact optimum. Procurement supports an exact reference only with a pinned solver and certificate in the declared validity domain. |
| **comparative** | A buyer agent conducts **supplier price negotiation** against a controlled seller under hidden information. | **TERMS-Bench** | Only AERead-owned TERMS-style conformance is currently admitted; official parity is blocked until the official simulator, defaults, and license are available. |
| **rater/judge** | An agent produces a **professional analyst deliverable** whose usefulness and quality cannot be fully reduced to database fields. | **GDPval** | The headline protocol uses occupational experts in blinded pairwise comparison. LLM/canned judging is separate, and the dataset license must pass admission before artifacts are vendored or redistributed. |
| **simulation/statistical** | An operator manages **inventory and pricing** under uncertain customer demand across repeated business periods. | **Vending-Bench** | Expected net worth, failure risk, and outcome quantiles are a later pressure test. Until official V2 code, license, and state contract are public and pinned, official adapter parity is blocked. |
| **integrity/admissibility** | An **audited agent episode** may enter analysis only if observations, provider attempts, tool calls, state transitions, hashes, retries, and replay are complete. | **AERead EvaluationReceipt** and replay contract | `measurement_validity` admission before capability scoring. This is runner infrastructure, **not a standalone capability benchmark**. |

## Important boundaries

- In pinned tau3 `retail/base`, 112 of 114 task records declare `DB + NL_ASSERTION`.
  The database comparison is therefore a primary deterministic database leaf, not the full upstream scalar.
- In STATE, final-state requirements are the official deterministic layer. Non-empty task requirements use the locked task-requirements judge. An empty task-requirement set uses the official deterministic identity shortcut without a judge call; task 142 has 5 state and 0 task requirements. A task requirement becomes a deterministic temporal leaf only when it can be compiled into a versioned predicate over recorded trace evidence.
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
