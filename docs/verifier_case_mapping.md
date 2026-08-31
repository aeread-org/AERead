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
| **canonical/reference** | A **retail refund** agent must leave the order, item, amount, payment method, and refund status in the approved terminal state. | **tau3-bench** `retail/base` | `terminal_state_equivalence` against the versioned gold database. Alternative legal tool paths may pass; natural-language assertions remain separate. |
| **rule/constraint/temporal** | A **regulated refund process** must check eligibility and obtain confirmation before mutating the customer account. | **STATE-Bench** | Deterministic final-state predicates plus replayed temporal requirements such as read-before-write, confirmation-before-mutation, and forbidden changes. Residual UX judgments remain judge-dependent. |
| **objective/optimum/bound** | A firm solves **procurement and scheduling** subject to costs, capacity, and feasibility constraints. | **EconEvals** | Exact instance objective and solution where supplied, with executable greedy policies retained as comparison baselines rather than confused with the optimum. |
| **comparative** | A buyer agent conducts **supplier price negotiation** against a controlled seller under hidden information. | **TERMS-Bench** | Paired utility, agreement, and failure differences against a version-pinned counterpart on identical cases and seeds. Its extra-information dynamic program is a separate upper-bound leaf. |
| **rater/judge** | An agent produces a **professional analyst deliverable** whose usefulness and quality cannot be fully reduced to database fields. | **GDPval** | Blinded expert rubric or pairwise preference with rater provenance, ties, disagreement, and uncertainty; the result is judge- and reference-dependent. |
| **simulation/statistical** | An operator manages **inventory and pricing** under uncertain customer demand across repeated business periods. | **Vending-Bench** | Expected net worth, failure risk, and outcome quantiles across declared task clusters and simulator seeds. Repetition estimates a distribution; it does not create a missing policy optimum. |
| **integrity/admissibility** | An **audited agent episode** may enter analysis only if observations, provider attempts, tool calls, state transitions, hashes, retries, and replay are complete. | **AERead EvaluationReceipt** and replay contract | `measurement_validity` admission before capability scoring. This is runner infrastructure, **not a standalone capability benchmark**. |

## Important boundaries

- `simulation/statistical` modifies a semantic verifier. For example, Vending-Bench uses
  an objective verifier per run and a stochastic estimator across demand realizations.
- `integrity/admissibility` gates evidence. It must not turn a missing trace into an
  economic failure or success.
- SAGE is a nearby candidate for `rule/constraint/temporal` when service-flow graph
  transitions are machine-observable; residual semantic dialogue quality belongs under
  `rater/judge`. It still requires a pinned release and scoring-schema audit before use.
- Native `housing_v1` is the paper counterpart to EconEvals: welfare uses
  `objective/optimum/bound`, while phase order, real offers, immutable holds, capacity,
  terminal payoffs, and IR use separate `rule/constraint/temporal` leaves.
- These mappings support typed within-case results. They do not create a universal
  cross-benchmark score.
