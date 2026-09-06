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

### 1.4 The decline jump was not declared in the phase graph

The fix in 1.3 introduced its own defect. Declining an optional agreement
skips that agreement's response and commit phases, but the amendment offer
phase still declared only its response phase as a successor, so the scheduler
rejected the transition as an undeclared next phase and the cell died as
`family_execution_failure`. A live panel caught it in 6 of the first 7 cells.

Two tests now cover it: a phase-graph consistency check on the decline
transition, and a full scripted episode that declines the amendment and still
completes, seals and replays. The lesson is that testing `legal()` in
isolation was not enough; the phase graph is a separate declaration that has
to agree with every transition the environment can take.

### 1.5 Counter terms were never recorded, so the diagnostic read empty

The environment recorded structured terms for offers but not for counters, so
a counter in the trajectory was unauditable and the verbal/written diagnostic
compared against an empty package and always reported zero adoptions. The
first panel run reported `undisclosed_counters_adopted: 0` for cells that had
demonstrably adopted the hidden term.

Counters now record their structured terms, which discloses nothing new since
the developer already receives them through `pending_counter_terms`, and the
diagnostic falls back to the world's declared counter package. Recomputed from
the sealed receipts of the final panel, the true figure is **4 adoptions of 4
presentations** for Gemini and 0 of 3 for Qwen, published alongside the run as
`verbal_written_diagnostic_corrected.json`.

### 1.6 Three smaller correctness defects

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

## Part 1b: recalibration to published market figures

Section 2.1 below recorded that the economics were four orders of magnitude
too small. They now are not. The worlds are a 50 MW project over 36 months,
with every magnitude anchored to a published 2026 benchmark rather than
invented, and `tests/test_datacenter_qc.py` fails if any of them drifts out of
range.

| Quantity | Calibrated world | Published range |
|---|---:|---|
| Construction | $10.3M per MW | $8M to $13M per MW |
| Lease rate | $185 per kW-month | $130 to $400 wholesale |
| Loan spread | SOFR + 255bps | 250 to 450bps |
| Loan-to-cost | 65% | 50% to 70% |
| EPC delay cap | 9% of contract | 5% to 10% |
| Lease term | 15 years, take-or-pay | 15 to 20 years |

Energy throughput and pass-through, a floating base-rate curve, and per-seat
discount rates of 12, 7 and 8 percent are now live, which closes 2.2 and most
of 2.5. A successful developer clears about $404M against an $8M walk-away,
and negotiating rather than adopting counters is worth a median $39.5M.

Two engine defects surfaced only once the world was realistic:

- **Coverage counted the balloon.** Debt-service coverage included the bullet
  principal repayment at maturity, so every realistic term loan breached its
  covenant in its final month purely because principal came due. Coverage is
  now measured on scheduled service, and repayment ability is still tested
  separately as `maturity_nonpayment`.
- **The covenant-cliff stratum was unbuildable from leverage.** Section 8 of
  the plan specifies that stratum as "small changes in price, ramp, or
  leverage" causing a breach. Once loan-to-cost is capped at a realistic 65 to
  70 percent, stabilised coverage runs 2 to 4x and *no admissible leverage
  breaches it*: the commitment binds before the advance rate does, so raising
  leverage changes nothing at all. The stratum now uses the tenant ramp. Price
  and ramp are the real levers; leverage is not one.

A third point is recorded but not fixed: the coverage covenant is gated on the
contractual service commencement date rather than on first revenue, so a
package that commences before its conditions precedent are met reports zero
coverage for those months. That is arguably correct, but it means the
commencement date, not commercial operation, decides when the covenant starts
biting.

### A model error booked as an infrastructure failure

Qwen emitted integers of 5,700 to 5,800 digits. CPython refuses to decode an
integer past 4,300 digits, and that refusal is raised inside the provider call,
before the family parser runs, so the scheduler recorded 14 cells as
`child_provider_outcome_unknown` provider missingness. They are model errors.
Mis-typing them inflates the provider's fault and understates the model's.

The decode limit is now lifted in the plugin and any term beyond a quadrillion
cents is rejected as a malformed action, so the cell is booked against the
model. The affected cells in the calibrated run are listed in
`mistyped_model_errors_corrected.json` alongside the published evidence.

The general lesson is that a family must own the classification of anything a
model can cause. If a model can trigger it, it is not infrastructure.

## How this family is quality controlled

Golden-value tests pin what the engine returned last time. They do not say it
is right. Three layers do:

1. **Accounting identities**, checked for all 24 worlds rather than one
   fixture: monthly sources equal uses, principal rolls forward, and the three
   seat NPVs sum to the reported total. `simulate_project` raises on any
   violation, so every world that generates has already proved them.
2. **Metamorphic properties**: a directional input change must move the
   outcome the way finance requires. Raising the capacity charge must not
   lower developer value; raising the EPC price must not raise it; a delay
   that moves commercial operation must destroy value; a positive discount
   rate must reduce a future-weighted NPV. These catch sign errors and
   mis-wired terms that no golden value can.
3. **Calibration and structural bounds**: every magnitude sits in a published
   range, every world exercises energy, floating rates and discounting, and
   equity is priced above debt. Blind counter-adoption must stay admissible
   but never optimal, and inflated liability terms must be rejected at any
   scale.

The value of the layer is not theoretical. Writing it caught that the pack on
disk was still toy-scale, that the bargaining band pushed the negotiated EPC
price below market, and that one property I asserted about energisation was
simply false.

## Part 2: modelling limits that are still open

These do not corrupt the current measurement, but each one caps what the
family can claim. They need a decision, not a patch.

### 2.1 The economics were four orders of magnitude too small (now fixed, see Part 1b)

A world's EPC contract is 224,000 cents (**$2,240**) for a 1 MW data centre,
and a successful developer clears about **$7,080**. Real 1 MW capacity is
roughly $10M of construction.

This is not merely cosmetic. Models bring real-world priors: several proposed
land at 1,000,000 cents ($10,000), which is economically sane for a site and
was rejected as outside the band. The benchmark currently penalises correct
domain intuition. Either scale the worlds to realistic magnitudes or state
explicitly in the observation that amounts are scenario-scaled.

### 2.2 There was no time value of money (now fixed, see Part 1b)

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

## What the calibrated panel showed

The 96-cell panel on the recalibrated 50 MW worlds, for $1.90:

| Route | Admitted | Mean developer NPV | vs baseline | Typed failures |
|---|---:|---:|---:|---:|
| Gemini 3.8 Flash | 71% | $412.6M | -$148.5M | 0 |
| gpt-oss-120b | 0% | -$10.7M | -$549.6M | 0 |
| GLM-5.3-flash | 0% | n/a | n/a | 15 rate-limited |
| Qwen3-235B | 0% | n/a | n/a | 14 oversized integers |

Gemini transacts on most worlds and still leaves roughly $39M per world on the
table, the counter-adoption gap the width fix created. gpt-oss now completes
the panel without a single operational failure but is excluded on 18 of 24
worlds for schema-invalid actions. Only Gemini and gpt-oss have complete,
route-verified panels, so only they are ranked.

## What the earlier toy-scale panel showed

The final 96-cell panel on the corrected worlds is the first run in which the
family measured what it was built to measure.

| Route | Admitted | Mean developer NPV | vs scripted baseline |
|---|---:|---:|---:|
| Gemini 3.8 Flash | 54% | $6,426 | -$1,028 |
| Qwen3-235B | 0% | -$338 | -$7,895 |
| GLM-5.3-flash | 0% | n/a | n/a |
| gpt-oss-120b | 0% | n/a | n/a |

Gemini is the only route that transacts, and its admitted NPV equals **pure
counter-adoption to the cent** in every completed stack: it accepts whatever
each counterparty counters with and leaves about 12 percent on the table. On
the pre-fix worlds that same behaviour would have scored exactly at baseline
and looked like flawless play, which is precisely why 1.1 mattered.

The strata now discriminate. Gemini clears revenue-without-bankability and
liability-transfer 4 of 4, but the covenant-cliff and restrictive-draws traps
catch it 3 of 4 each, and the verbal/written trap catches it 4 of 4: it signs
a loan whose prose claimed only the fee moved while the terms also cut the
advance rate, and the project then fails on a funding shortfall.

Paired world-clustered intervals separate Gemini from every open-weight route
by +0.54 admission rate [+0.33, +0.75]. The three routes at zero admission are
not separable from each other.

## What the panels can and cannot support today

They can support: route qualification with verified endpoints and complete
cost telemetry; typed separation of admission failures, no-agreement outcomes
and infrastructure missingness; and world-clustered paired comparison across
24 independent clusters.

They cannot yet support: any claim about negotiation skill in the integrative
sense, any risk-adjusted interpretation of the primary metric, or any
cross-model ranking, which the artifacts explicitly disallow.
