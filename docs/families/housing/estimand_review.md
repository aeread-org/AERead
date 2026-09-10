# Housing v1: what the primary estimand measures

A review of the estimand the Housing family froze, written after the
confirmatory comparison had been executed and published. It concerns one
question: does the primary outcome respond to the seat the campaign exists to
compare? The answer is that it does not, and the review sets out how that was
established, what the actual mechanism is, and what it costs to detect the
same problem before spending rather than after.

Every number here is either recomputed from committed evidence, or produced by
a provider-free control that regenerates byte for byte. Where a result is
post-hoc or exploratory it is labelled as such. Register rows D-16 and D-24
through D-27 carry the individual findings; this document is the argument that
connects them.

## 1. What the campaign reported

`housing_confirmatory_parasail_v2` executed 720 frozen cells against a sealed
holdout: 30 worlds, three unseen configurations, four subject-opponent
conditions, two replicates, for `$6.90`. 717 completed with verified routes and
exact score replay. The primary estimand is the paired world-level contrast of
GLM 5.3 Flash minus DeepSeek V4 Flash on the subject's normalized welfare
score, equally weighted across configurations and opponents within a world.

| quantity | value |
|---|---|
| paired worlds | 27 |
| mean contrast | `+0.005` |
| 95 percent interval | `-0.016` to `+0.025` |
| declared minimum meaningful effect | `0.05` |

The interval contains zero and lies wholly inside the declared effect in both
directions. Reported as a null with content: the two models are not
distinguishable, and the data are precise enough to say the difference is
smaller than the design was built to detect.

That reading is arithmetically correct. It is also the wrong conclusion to draw
from it.

## 2. The estimand does not respond to the subject

The score is welfare over the assignment oracle's bound, and welfare is

```
sum over tenants of (value - rent) + sum over landlords of (rent - cost)
```

in which every rent cancels exactly. The score therefore moves only through
which tenant is matched to which listing. It is a measure of allocative
efficiency and a good one.

The subject of every Housing condition sits in the tenant seats. A tenant's
levers are which listing it approaches, and what it agrees to pay. The second
is cancelled by construction. So the design placed the model under test in a
seat whose principal lever the metric cannot see.

Decomposing the 717 completed cells makes the consequence explicit.

| source | share of score variance |
|---|---|
| the case, world by configuration | `0.428` |
| the opponent, within a fixed case | `0.564` of the remainder |
| the subject, within a fixed case | `0.067` of the remainder |
| **the subject, of the total** | **`0.000`** |

Two corroborating readings. Across the 90 world-by-configuration cases, what a
one-line scripted heuristic scores predicts the models' score at `r = 0.81`.
And the primary contrast computed per configuration is `+0.024`, `-0.015`,
`+0.011`: it changes sign.

The subject's share of the total is `0.000258`, which the table rounds to
three decimals.

A share must be read against a null, and the null must preserve the design.
Permuting the subject label within each case, which keeps the balance across
opponents and replicates, puts 95 percent of the mass between `0.042` and
`0.448` with a mean of `0.141`. The observed `0.067` sits well inside that, at
`p = 0.746`. So the honest statement is not that the subject share is
extraordinarily low; it is that the subject is **not detectable at all**,
while the opponent is, at `p = 0.003`. The same test on the surplus estimand
returns `p = 0.390` for the subject and `p = 0.001` for the opponent.

The confirmatory null was therefore not a finding that two models are equal. It
was a correct measurement of an estimand that carries almost no agent signal.
No sample size, sealing discipline or replication would have revealed this,
because each of those protections assumes the estimand responds to the
comparison being made.

## 3. The difficulty knob cannot fix it

The natural first response is to re-tune difficulty until the case
discriminates. The panel already spans a wide range and the data reject that
route.

| configuration | tenants / listings | common weight | models | naive baseline | gap | model wins |
|---|---|---|---|---|---|---|
| mild | 8 / 6 | `0.45` | `0.812` | `0.852` | `-0.041` | 40.6% |
| moderate | 8 / 5 | `0.70` | `0.816` | `0.858` | `-0.042` | 41.2% |
| severe | 8 / 4 | `0.95` | `0.854` | `0.896` | `-0.042` | 39.6% |

`common_weight` is the share of a tenant's valuation that is common across
tenants, so `0.45` to `0.95` moves the idiosyncratic component from 55 percent
down to 5 percent. That is nearly the whole range over which sorting skill can
matter. The gap is flat to three decimals and the win rate does not move.

Neither branch of the usual dilemma holds. At the easy end the models do lose
to the baseline, but by the same margin as at the hard end, so the loss is not
a property of easy. At the hard end nothing collapses: the models score highest
of the three. A quantity invariant to the parameter it should depend on is not
the quantity it is named, and a flat difficulty sweep should be read first as
evidence about the instrument.

## 4. The scale itself is sound

It is worth separating two things that look alike. The estimand does not
respond to the subject. The environment and its verifier are fine.

A cell can fall below the oracle in exactly three ways, and the shortfall
divides as 20 percent listings the oracle leases that stay unleased, 68 percent
leased listings going to a lower-value tenant, and 12 percent matches that
destroy value. The lease count explains none of the between-cell variance, so
this is a sorting metric rather than a market-clearing one, and sorting is
where judgment lives.

| same leased listings, sorted by | score |
|---|---|
| random tenants | `0.676` |
| the two models | `0.827` |
| the best possible sorting | `0.944` |

The models sit in the middle of a real ladder, at neither ceiling nor floor.
The oracle bound is a sound verifier and the scale below it discriminates. The
problem is confined to which quantity was made primary.

## 5. Welfare inverts the distribution ranking

Gate 3 of the benchmark QC standard now requires a provider-free control before
an estimand is frozen. Run retrospectively here, it settles the question in a
way the live evidence cannot, because the policies' ordering is known in
advance and no model is involved.

The published control at `evidence/housing/estimand_sensitivity_control/`
scores five tenant policies on the sealed panel: 105 cases, 4200 episodes, no
provider calls, regenerating byte for byte.

| tenant policy | welfare | tenant surplus |
|---|---|---|
| oracle informed | `0.987` | `0.860` |
| truthful | `0.964` | `0.000` |
| naive | `0.870` | `0.746` |
| adaptive | `0.860` | `0.691` |
| random | `0.774` | `0.647` |

The truthful bidder offers its full valuation on its best listing. It therefore
wins allocations as readily as a shrewd bidder and captures, by construction,
exactly none of the surplus. Welfare rates it second best of the five, behind
only the oracle-informed policy, because bidding full value is precisely what
makes an allocation efficient.

The paired contrast between the naive and truthful policies is `-0.094` on
welfare and `+0.746` on surplus, both excluding zero. So welfare does not
merely fail to separate a good tenant from a self-defeating one. It confidently
ranks them the wrong way round. A metric that does this cannot be a sole
primary, and the cheapest possible probe would have exposed it before any
campaign was designed.

## 6. The mechanism is counterparty brokenness, not counterparty leverage

The decomposition in section 2 shows the opponent explaining more within-case
variance than the subject, which invites the conclusion that the landlord seat
simply holds too much leverage. That conclusion is wrong, and the distinction
matters for what to fix.

Leverage cancels. Each subject faces each opponent equally often, so the
opponent's main effect enters both arms of the paired contrast identically and
subtracts out. What does not cancel is a counterparty that violates its own
participation constraint, because the variance it injects is not symmetric
between the arms.

Sweeping a concessive landlord as a controlled variable, against a genuine
skill difference between two scripted policies that differ in no transfer
behaviour:

| opponent violations, share of cells | contrast spread | detected |
|---|---|---|
| 0.0% | `0.019` | yes |
| 1.2% | `0.105` | yes |
| 4.4% | `0.139` | yes |
| 10.7% | `0.322` | no |
| 20.7% | `0.377` | no |
| 35.5% | `0.543` | no |

The real signal has a spread of `0.019`. A counterparty failing in one cell in
ten multiplies it seventeenfold and buries it. Welfare's spread over the same
sweep is `0.034` at every rate without exception, because the rent being given
away cancels out of it: a second demonstration of transfer-blindness from the
opposite direction.

The threshold between 4.4 and 10.7 percent sets the recommended ceiling at 5
percent, and it matches the live campaign exactly. Under the DeepSeek landlord,
which violated in 4.7 percent of cells, the distribution-side contrast is
`+0.186` with an interval of `+0.149` to `+0.222`, decisive at 3.7 times the
declared minimum effect. Under the GLM landlord, which violated in 59.5 percent
of cells after signing 264 leases at zero rent, the same contrast spans zero
with a standard deviation seven times larger.

## 7. What the corrected measurement would look like

Recomputing the frozen estimand structure on tenant surplus over the same
worlds:

| contrast, GLM minus DeepSeek | n | mean | 95 percent interval | excludes zero |
|---|---|---|---|---|
| welfare, the frozen primary | 27 | `+0.005` | `-0.016` to `+0.025` | no |
| tenant surplus | 27 | `+0.465` | `-0.196` to `+1.126` | no |
| tenant surplus, less the degenerate world | 26 | `+0.157` | `-0.042` to `+0.357` | no |
| tenant surplus, versus the sound landlord | 28 | `+0.186` | `+0.149` to `+0.222` | **yes** |
| tenant surplus, versus the broken landlord | 27 | `+0.135` | `-0.236` to `+0.507` | no |

The metric change alone is necessary and not sufficient: the overall surplus
contrast still spans zero. Both corrections are required together, which is why
the rent floor and the individual-rationality gate are preconditions for the
surplus estimand rather than accounting hygiene beside it.

Under both, the subject's share of within-case variance rises from `0.067` to
`0.267`, and the contrast by configuration becomes `+0.141`, `+0.296`, `+0.867`
as `common_weight` rises: monotone, sixfold, the dose-response a capability
measure should show and which welfare never showed at any difficulty.

That rise must be reported with its uncertainty, and an earlier draft of this
review did not. Against the permutation null the surplus subject share of
`0.267` returns `p = 0.390`. It is not distinguishable from chance on this
panel. The point estimate is four times welfare's and the direction is
consistent with everything else here, but the decomposition alone does not
establish that surplus detects these two models. The evidence that carries the
recommendation is the control in section 5, where the ordering is known before
the run, together with the clean-counterparty contrast above, which does
exclude zero. Section 8 is the reason to expect no more than that: subject
detectability has not been stable across panels for either metric.

## 8. The pilot measured a different environment

Turning the decomposition from an ad-hoc script into a reproducible tool, and
running it over every published Housing campaign rather than the confirmatory
one alone, surfaced a second failure that the single-campaign view had hidden.

A subject share must be read against chance, not against zero. Splitting a
case's cells by any label captures variance even when the label is
meaningless: for two subjects and eight cells per case the expected share is
`(k-1)/(n-1)`, or `0.144`. Measured that way:

| campaign | cells | welfare, subject `p` | surplus, subject `p` |
|---|---|---|---|
| pilot line, v23 | 186 | **`0.004`** | `0.858` |
| pilot line, v26 | 189 | **`0.001`** | `0.977` |
| confirmatory holdout | 717 | `0.746` | `0.390` |

Bold marks a subject effect distinguishable from a design-preserving
permutation null at the five percent level.

The two lines ran on different environments:

| | tenants / listings | common weights | rounds | worlds |
|---|---|---|---|---|
| pilot panel | 6 / 5, 4, 3 | `0.85`, `0.85`, `0.30` | 2 | 8 |
| holdout panel | 8 / 6, 5, 4 | `0.45`, `0.70`, `0.95` | 3 | 30 |

On the pilot panel, welfare's subject effect is significant at `p = 0.004` and
`p = 0.001`. Nothing in the pilot suggested the estimand was blind, because on
that panel it was not. On the holdout the same metric returns `p = 0.746`. The
surplus estimand reverses the pattern and is significant on neither panel,
which is the more sobering half: subject detectability did not survive the
panel change for either metric, so the recommendation in section 7 cannot be
treated as settled and must be re-established on whatever panel is frozen.

This compounds with, rather than restates, section 2. The confirmatory world
count was derived from between-world variance measured on the pilot panel. It
was then spent on a panel where the metric behaves differently. Even an
estimand that responded to the subject would have been sized on the wrong
environment.

The instrument that found this is published at
`evidence/housing/estimand_diagnostics/`, reads only committed rows, and
regenerates byte for byte. Two earlier versions of it were wrong in ways worth
recording. The first used a fixed floor of `0.15` on the subject's share,
which would have passed the very campaign it exists to catch. The second
compared the observed share with the analytic expectation `(k-1)/(n-1)`; that
expectation is accurate on average here, `0.144` against a permuted mean of
`0.141`, but comparing a point estimate with a mean ignores the null's spread,
and the spread is what matters: it reaches `0.448`. Only the permutation
version supports the significance claims above (D-28).

## 9. What landed, and what is still owed

Landed, all opt-in per contract so no sealed campaign changes behaviour:

- `controls.minimum_rent` with action schema `housing_actions/2.1` or `2.2`,
  enforced identically by the schema, the market and profile admission, so a
  landlord cannot concede a unit at zero (D-23);
- `controls.prompt_version: housing_prompts/2.0`, prompts that state each
  seat's payoff and its participation constraint (D-21);
- `analysis.subject_ir_violation_policy: typed_failure` with
  `maximum_subject_ir_failure_fraction`, so a subject violating its own payoff
  is a typed failure rather than a number averaged into the score (D-24);
- `analysis.co_primary_estimand: subject_surplus_share`, carrying the claim
  jointly with welfare and requiring
  `maximum_opponent_ir_violation_fraction`, recommended at `0.05` on the
  sweep above (D-27);
- `confirmatory_panel.minimum_upper_bound`, excluding worlds whose normalizer
  is near zero rather than exactly zero (D-18).

Still owed before another confirmatory comparison:

1. A new sealed panel. The holdout is spent and must not be reused.
2. The control arm rerun under the rent floor, to confirm the floor alone
   brings the opponent-violation rate under the declared ceiling. Free.
3. A variance pilot on the confirmatory panel's own generator parameters, or
   a declared reason a different one is admissible. The pilot in use ran 6
   tenants at common weights 0.85 and 0.30 over 2 rounds; the holdout runs 8
   tenants at 0.45 to 0.95 over 3 rounds, and the estimand does not behave the
   same on both (D-28).
4. A variance pilot sized on whichever estimand is made primary. The world
   count in use was derived from welfare's between-world variance, which is a
   different quantity's noise.
5. A like-for-like baseline: the naive tenant policy against the same model
   landlord, reported beside the primary. The published baseline pairs the
   naive tenant with a scripted landlord and is not comparable as it stands
   (D-25).

## 10. How this was found, and how it should have been

The sequence matters more than the conclusion, because the conclusion is
specific to Housing and the sequence is not.

Nothing in the pipeline objected. Every campaign gate passed: design,
provider-free, catalog preflight, profile admission, confirmatory execution.
Every test passed. The freeze was honoured, the holdout was sealed before any
outcome existed, the receipts replayed exactly, the digests recompute today.
The defect was never in whether the checks ran. It was in what they checked.

What actually found it was seven steps, each asking a question the previous
answer did not settle:

1. **Distrust a clean null.** The reported interval was precise and inside the
   declared effect. A precise null and a broken instrument produce identical
   artifacts, so the result was treated as a claim to be attacked rather than
   a finding to be published.
2. **Decompose the headline into parts that can disagree.** Splitting the
   shortfall below the oracle into unleased listings, mis-sorted listings and
   value-destroying matches showed one world-configuration supplying every
   negative score in the campaign (D-18).
3. **Read individual episodes, not aggregates.** Tracing that world's
   trajectories showed a landlord accepting below its own cost and conceding
   units at zero rent, which no summary statistic had surfaced (D-21 to D-23).
4. **Ask whether the anecdote is the pattern.** Sweeping all 720 cells turned
   one world's oddity into 264 zero-rent leases campaign-wide, and showed the
   primary outcome could not see any of them because rent cancels (D-16, D-22).
5. **Test the obvious hypothesis and let it fail.** The natural explanation was
   difficulty calibration. Sweeping it showed the gap flat to three decimals
   across nearly the whole idiosyncratic-value range, which eliminated
   difficulty and pointed at the instrument (D-26).
6. **Decompose the variance by factor.** This is the step that named the root
   cause: the case explains 42.8 percent of score variance and the subject
   0.000. Every earlier step had described symptoms of this one fact (D-27).
7. **Build a control whose answer is known in advance.** A truthful bidder must
   capture zero surplus by construction. Scoring it proved welfare inverts the
   distribution ranking, and sweeping a concessive counterparty separated
   metric blindness from counterparty brokenness.

Steps 6 and 7 are the only two that identified causes rather than symptoms.
Both are provider-free. Both could have run before a single model call, on the
panel as designed, in minutes and for nothing. Instead they ran after ten
campaigns, a variance pilot, a sealed freeze and 720 executed cells.

That is the reusable lesson, and it is now Gate 3 of the benchmark QC standard:
decompose the metric's variance across case, opponent and subject, and prove
sensitivity against known-ordered control policies, before the estimand is
frozen. If the subject's share is near zero, stop; no sample size, sealing
discipline or replication recovers a result, because every one of those
protections assumes the estimand responds to the comparison.

Three intermediate diagnoses written during this investigation were wrong and
are kept in the register rather than edited away: a hashing drift attributed to
an un-incremented version field when the repository already had a ruling for it
(D-20); a claim that both models sort worse than a one-line heuristic, which
compared them against a baseline facing a different counterparty (D-25); and a
prescription of measurement hygiene, which would have produced a cleaner
measurement of nothing. Each was corrected by evidence or by review, which is
the reason the register keeps wrong hypotheses at the moment they are made.

## 11. What this review does not establish

The confirmatory result stands as what it is: a precise null on allocative
efficiency, for these two models, these routes and this panel. Nothing here
overturns it.

The surplus numbers in sections 6 and 7 are post-hoc. They use an estimand that
was not predeclared, on a holdout that is spent, and the favourable
counterparty slice was chosen after seeing it. They are a hypothesis for the
next campaign identity, not a result.

Mean tenant surplus exceeds `1.0` in the live cells, because landlords signing
below their own cost subsidise tenants. On its own the surplus metric therefore
scores exploitation of a broken counterparty as skill. Its validity depends
entirely on the guards listed above being active, which in the published
evidence they were not.
