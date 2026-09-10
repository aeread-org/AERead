# What we have measured, and whether it can sit beside the paper

**Status:** measurement inventory, 2026-09-10
**Scope:** every family that has produced a live, replayed evidence bundle.
**Question it answers:** for each benchmark we have re-implemented, can our
number be set next to the number its paper reports — and if not, what exactly
is in the way.

The short answer is that being *finished* and being *comparable* are
different properties, and until this week we had conflated them. Four
families have complete, replayed, digest-bound live evidence. Of those, one
is comparable today, one is comparable only after a re-run that is already
under way, one needs a missing normalizer, and one is not published at all.

| family | live evidence | comparable to its paper? | what is in the way |
|---|---|---|---|
| TERMS-Bench | pilot v2 + v3, 30 cases each, 30/30 replayed (PR #153) | **yes**, with a stated `n` caveat | nothing structural: 30 cases against the paper's 1,800 per agent, and 3 of its 6 counterpart families |
| GovSim | `first_light_v1`, `dialogue_v3` published; `baseline_v4` on PR #159 | **yes, as of `baseline_v4`** | the two published panels ran the paper's *universalization intervention* while their cases declared the baseline (G-D-03); the corrected arm is the comparable one |
| EconEvals | `panel_v10`, 6 cases, published | **partly** | our objective leaf is raw units plus the exact optimum; the paper normalizes against a uniform-random baseline, which we do not compute |
| tau3 retail | v9 and v18 on PR #97, unmerged | **no** | not published, and v18 completed 1 of 5 cases |
| housing, procurement allocation, data-center, commercial-state | published, many campaigns | n/a | our own designs; there is no external paper to compare against |

## A qualifier that applies to every number below

Every live panel this repository has published ran on one route — OpenRouter
GLM 5.3 Flash on Parasail — and, until 2026-09-10, every one of them declared
a reasoning condition that turns reasoning off. Measured on that route with
one call per condition on an identical prompt:

| declared condition | reasoning tokens returned |
|---|---:|
| `reasoning.max_tokens: 1500` (`reasoning_capped_1500_v1`) | 13 |
| `reasoning.max_tokens: 8000` | 13 |
| `reasoning.effort: "low"` (`reasoning_low_v1`) | 13 |
| **no reasoning block declared** (`reasoning_unconstrained_v1`) | **259** |

The cap is a switch, not a budget. `econevals_glm53_flash_parasail_panel_v10`
and both govsim panels therefore measure a **non-deliberating** GLM 5.3
Flash, and no published number of ours was a like-for-like against a paper
table whose agents reason freely. This is R-D-01 in the incident log; the
declaration standard in [reasoning condition and diagnostics](reasoning_condition_and_diagnostics.md)
required the condition to be named and versioned, which it was — what it
could not require is that the name describe what the route does with it.

## TERMS-Bench — comparable, and the reasoning condition explains the gap

Paper: *TERMS-Bench: Diagnosing LLM Negotiation Agents Beyond Deal Rate*
(arXiv 2605.13909v2), 13 agents, 1,800 seeded episodes each, 3 regimes × 6
counterpart families. Ours: 30 pilot cases (15 Overlap, 15 No-deal; Candid,
Taciturn, Expressive), the counterpart run as a kernel scripted seat so it is
the paper's specified opponent rather than a second model.

| | v2 suppressed | v3 deliberating | paper, 13 agents |
|---|---:|---:|---|
| `SE+` surplus efficiency | 0.402 | **0.533** | 0.189 – 0.694 (best Claude Opus 4.6) |
| `CSE+` conditional surplus | 0.402 | **0.533** | 0.296 – 0.721 (best GLM-5.1) |
| `AGR+` agreement, Overlap | 1.00 | 1.00 | 0.522 – 0.999; frontier 0.934 – 0.999 |
| `FAGR-` false agreement, No-deal | 0.067 (1/15) | 0.133 (2/15) | ~0; worst 0.0017 |
| `CritViol%` | 0.433 (13/30) | **0.067 (2/30)** | 0 – 0.0206 |
| cost / wall clock | $0.029 / 5.6 min | $0.134 / 43.5 min | — |

Read across: on surplus and agreement GLM 5.3 Flash lands squarely inside the
paper's band, and deliberation moves it from mid-pack to upper-middle.
Compliance is the interesting column. v2's 43% critical-violation rate was
twenty times the paper's worst agent; almost all of it was the agent offering
above its own reservation value to chase a seller it could not reach, and
allowing the model to think removed 11 of those 13 breaches. What remains,
6.7%, is still three times the paper's worst — a real gap, an order of
magnitude smaller than the one the harness manufactured.

False agreement moved the wrong way, 1 case to 2. Both v3 cases closed by the
counterpart accepting an offer the agent should not have made in a world with
no zone of agreement. On 15 No-deal cases that is one event of difference and
carries no claim, but it is the axis the paper singles out as independent of
surplus, and it is the one where we look worst.

What a reader must not do with these numbers: rank GLM 5.3 Flash against the
paper's table. 30 cases against 1,800 gives our means intervals that overlap
most of the paper's column, and half its counterpart families — including
both stress families — are not in our corpus.

## GovSim — the published panels measured the intervention, not the baseline

Paper: *Cooperate or Collapse: Emergence of Sustainable Cooperation in a
Society of LLM Agents* (arXiv 2404.16698). Headline: all but the strongest
2024 models fail to sustain the resource, **highest survival rate below
54%**, and communication between agents is critical.

Ours, both panels: 12 of 12 months survived, in all three scenarios, with and
without communication. That does not contradict the paper — it answers a
different question. Upstream hands the agent the sustainability threshold
only under `inject_universalization`, its moral-reasoning intervention, which
the paper reports as significantly more sustainable; the baseline agent must
infer that number from the pool's dynamics. Our `observe()` served the
threshold on every observation while every case in the corpus declared
`inject_universalization: false`, so both published panels ran the
intervention arm under a contract that said baseline (G-D-03).

| campaign | arm | communication | survival | total harvest vs sustainable 600 |
|---|---|---|---:|---|
| `first_light_v1` | universalization | removed | 12/12 all scenarios | 560 / 600 / 592 |
| `dialogue_v3` | universalization | present | 12/12 all scenarios | 199 / 521 / 594 |
| **`baseline_v4`** | **baseline** | present | **12/12 all scenarios** | **237 / 401 / 182** |

The corrected arm does not rescue the paper's finding — it sharpens ours.
GLM 5.3 Flash never collapses the pool, in any arm, in any scenario: the
2024 failure mode the paper diagnoses does not reproduce on this model two
years later, and survival, the paper's headline metric, is saturated for it.
Three cases cannot distinguish 100% from 95%, but they distinguish it from
below 54%.

What the baseline arm costs the agent is yield. Told the threshold, the
agents harvest at or near it; not told it, they take 30–67% of what the
commons could sustain and their Gini rises from 0.007–0.011 to 0.040–0.142.
They buy survival with caution rather than with an estimate of the
regeneration rate — which is a different competence from the one the paper
was unable to find in 2024, and worth its own metric.

The v1 → v3 pair remains a result on its own terms: with the threshold
given, adding dialogue did not change survival and pushed the agents into
*under*-harvesting, most sharply in fishing (600 → 199).

## EconEvals — complete, and one reference value short of comparable

Paper: *EconEvals: Benchmarks and Litmus Tests for LLM Agents in Unknown
Environments* (arXiv 2503.18825), 100 periods per run, scores normalized so
that 100 is optimal and **0 is a uniform-random baseline**.

`econevals_glm53_flash_parasail_panel_v10`: 6 of 6 cases included, every
feasibility gate valid, every case running the full 100 periods.

| case | agent | pinned optimum `v_star` | agent / optimum | paper, Basic tier |
|---|---:|---:|---:|---|
| procurement.basic.0 | 17.99 | 81.31 | 0.221 | best 72.8 (Claude 3.5 Sonnet) |
| procurement.basic.1 | 4.22 | 20.29 | 0.208 | " |
| scheduling.basic.0 | 0 blocking pairs | 0 | **optimal** | best 100 (Claude 3.5 Sonnet) |
| scheduling.basic.1 | 0 blocking pairs | 0 | **optimal** | " |
| pricing.basic.0 | 35.09 | 41.66 | 0.842 | best 83.2 (Claude 3.5 Sonnet) |
| pricing.basic.1 | 13.01 | 26.42 | 0.492 | " |

Scheduling is directly comparable at the extreme and the result is a good
one: the agent submitted a stable matching — zero blocking pairs, the
optimum — on both cases, which is what the paper's best model scored on that
tier. The other two tracks are not comparable as written, because our
`agent / v_star` ratio and the paper's 0–100 score have different zeros:
ours is a fraction of the optimum, theirs is the position between a
uniform-random baseline and the optimum. Our objective leaf deliberately
stores raw units plus `v_star` and leaves ratios to the consumer, so closing
this needs one new reference value per case — the random-baseline score —
not a change to what we measure.

## tau3 retail — not published

The τ³ retail pipeline proof is on PR #97 and unmerged. Its first panel
(v9, 5/5) was costed before the per-round accounting fix, and the current
panel (v18) completed 1 of 5 cases, excluding 3 on the per-case cost cap and
1 on a malformed response. Nothing here is comparable to τ²-bench's reported
pass rates yet.

## What closing each gap costs

| gap | work | cost |
|---|---|---|
| GovSim baseline arm | done: `baseline_v4`, PR #159 | $0.04 |
| EconEvals deliberating arm | one campaign identity with `reasoning_unconstrained_v1` | ~$1 |
| EconEvals random-baseline normalizer | one reference provider per track, then re-score existing receipts | provider-free |
| GovSim deliberating arm | ditto; today's `reasoning_low_v1` is a suppressed condition | ~$0.05 |
| TERMS-Bench interval width | the corpus generator can produce more than 30 cases; 300 would cost ~$1.3 at v3 rates | ~$1.3 |
| TERMS-Bench stress families | Strategic, Stochastic and Adversarial presets are not implemented | family work |
| tau3 | PR #97's split, then a panel that completes | see #97 |
