# Data-center negotiation family: design findings

Findings from building the 24-world V2 pack (R3) and running the first paired
live panels (R4/R5). Everything below was verified by probing the engine or by
reading sealed receipts, not inferred from model output.

Two classes are separated deliberately: **defects that made the measurement
invalid**, which are fixed on this branch, and **modelling limits that are
still open**, which need a design decision before the family can carry the
claims the implementation plan makes for it.

---

## Part 1: defects found and fixed

### 1.1 The negotiation was degenerate

Each counterparty answers an unacceptable offer with a fixed `counter_terms`
package. In the first generated pack those counter terms **were the
developer-optimal answer**: adopting every counter verbatim matched or beat
the scripted baseline in **20 of 24 worlds**.

The panel was therefore measuring whether a model copies a counter back, not
whether it negotiates. This matches what the live runs showed: the one route
that kept proposing its own terms instead of adopting counters (GLM-5.3-flash)
exhausted its rounds in 34 of 48 cells, while routes that adopted got further.

**Fix.** Every negotiated price now carries a two-sided band with 30 percent
width. The counter sits at the counterparty-favourable ceiling and remains
admissible; the scripted developer negotiates to the floor.

| | before | after |
|---|---:|---:|
| Worlds where blind counter-adoption reaches the baseline | 20 / 24 | 0 / 24 |
| Median headroom between adopting and negotiating | 0 | 104,000 cents |

Regression test: `test_adopting_every_counter_is_admissible_but_never_optimal`.

### 1.2 A developer could write itself unbounded damages

Counterparty policies bounded only one side of each term. Fields where the
developer pays were capped above but had no floor, and liability fields were
unconstrained entirely. Two consequences, both accepted by every counterparty
and both passing all constraint checks:

- The utility accepted a **zero** interconnection charge and a zero demand
  charge, because its policy only capped them from above.
- Setting the EPC and power delay-damages fields to arbitrary values earned
  **19,970,000 cents against a 530,000 cent baseline**, a 38x return, because
  the engine credits liquidated damages as terminal value with no counterparty
  refusal and no cap relative to contract price.

A metric that rewards self-awarded damages by 38x measures exploitation, not
negotiation.

**Fix.** Policies are two-sided bands with reservation floors, and liability
terms are capped at the counterparty's quoted level. Regression test:
`test_no_within_policy_stack_earns_unbounded_self_written_damages`.

Residual headroom after the fix is a bounded 30,000 cents from negotiating a
tighter completion guarantee and collecting capped delay damages. That is
realistic contracting behaviour and is left in deliberately.

### 1.3 The V2 sequence forced an amendment with no way to decline

V2 always runs a land-amendment phase. A developer that judged the executed
lease adequate had no lawful action: re-proposing the same terms was rejected,
and there was no decline. This truncated **16 of 48 Gemini cells and 2 gpt-oss
cells** after they had already negotiated land, power, EPC and service.

**Fix.** Optional agreements accept an explicit `decline` action that advances
to the next agreement without executing one. Completion no longer requires an
optional agreement. Regression test:
`test_optional_amendment_can_be_declined_without_ending_the_episode`.

### 1.4 Three smaller correctness defects

- **Amendment fields crashed the environment.** A live developer whose
  amendment changed fields other than the scripted ones raised
  `family_execution_failure` at commit instead of being measured. Amended
  fields are now derived from the structured diff.
- **Oversized integers escaped as operational failures.** A model emitting a
  5,811-digit integer raised inside the JSON decoder and was recorded as
  infrastructure missingness rather than as a malformed action.
- **Month 0 was proposed repeatedly.** Two routes lost cells proposing month 0
  for 1-based month fields. The developer prompt now states the convention.

---

## Part 2: modelling limits that are still open

These do not corrupt the current measurement, but each one caps what the
family can claim. They need a decision, not a patch.

### 2.1 The economics are four orders of magnitude too small

A world's EPC contract is 224,000 cents (**$2,240**) for a 1 MW data centre,
and a successful developer clears about **$7,080**. Real 1 MW capacity is
roughly $10M of construction.

This is not merely cosmetic. Models bring real-world priors: several proposed
land at 1,000,000 cents ($10,000), which is economically sane for a site and
was rejected as outside the band. The benchmark currently penalises correct
domain intuition. Either scale the worlds to realistic magnitudes or state
explicitly in the observation that amounts are scenario-scaled.

### 2.2 There is no time value of money

Every discount rate is zero and the base-rate curve is all zeros, so
`developer_equity_npv` is an undiscounted sum. Deferring a payment is free,
and the EPC payment schedule, which is otherwise unconstrained, has no effect
on value. A financing benchmark in which financing timing does not matter is
missing its central mechanism.

### 2.3 Nothing is stochastic, so nothing is risk-adjusted

The implementation plan describes the primary outcome as *risk-adjusted*
developer equity NPV. Worlds are fully deterministic: capacity, demand and
schedules are fixed vectors known in advance. There is no risk to adjust for,
and no reason to value a guarantee or a cap except through the delay-damages
path. Either introduce scenario uncertainty or drop "risk-adjusted" from the
claim.

### 2.4 The counterparty has no utility function

Acceptance is field-wise: a package is accepted when every field sits inside
its band. The counterparty cannot trade a concession on one term for a gain on
another, so **integrative bargaining is unmeasurable**. Logrolling, the single
most studied negotiation skill, cannot appear in a score. The counter is also
static: the same package regardless of what was offered, so extra rounds add
no information and there is no adaptive opponent.

### 2.5 Whole subsystems are never exercised

Energy throughput is zero, customer usage is constant, and the rate curve is
flat, so energy pass-through, variable-demand SLA credits and floating-rate
interest never execute. The horizon is 6 months for a land-to-operations
sequence that takes 24 to 48 months in practice, so the delayed-revenue
stratum compresses into a one-month distinction.

### 2.6 Coverage and process gaps

- **Only V2 has worlds.** V0 and V1 still have a single curated case each.
- **Mechanism annotations are machine-derived** (`review_status: generated`).
  Section 8 of the plan requires a hand-reviewed explanation per world; nobody
  has confirmed the traps are economically sensible rather than merely
  engine-failing.
- **`verbal_written_mismatch` is descriptive only.** It is now computed and
  sealed, but it is not a scored leaf, per the plan's own staging.
- **The harness axis is untested.** R5 as written is a harness bake-off
  (minimal chat against LangGraph or smolagents on one model). What has run is
  a model panel on one harness.
- **The suite does not pass from a clean checkout.** Fifteen
  `datacenter_development_terms` tests on the campaign branch read artifacts
  under the gitignored `runs/` directory and fail with `FileNotFoundError`
  anywhere those local runs are absent. This contradicts the R3 exit gate,
  which requires reproducibility from a clean checkout. None of these failures
  involves the negotiation-stack modules.

---

## What the panels can and cannot support today

They can support: route qualification with verified endpoints and complete
cost telemetry; typed separation of admission failures, no-agreement outcomes
and infrastructure missingness; and world-clustered paired comparison across
24 independent clusters.

They cannot yet support: any claim about negotiation skill in the integrative
sense, any risk-adjusted interpretation of the primary metric, or any
cross-model ranking, which the artifacts explicitly disallow.
