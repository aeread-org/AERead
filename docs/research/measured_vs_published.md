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
| TERMS-Bench | four panels of 30 cases, 30/30 replayed each (PR #153), **two of them the paper's own agents** | **yes, and checked** | nothing structural: 30 cases against the paper's 1,800 per agent, and 3 of its 6 counterpart families |
| GovSim | four panels published or on PR #169, incl. **two validation models** | **yes, and checked** | none of the paper's own agents is reachable at all; the check runs on the nearest models and says so |
| EconEvals | `panel_v10`, 6 cases, published | **partly, and more than first thought** | two of three tracks need no normalizer we lack; what differs is *which* attempt is scored — see below |
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

## TERMS-Bench — checked against the paper's own agents

Two of the paper's thirteen agents are reachable on our route and sit at
opposite ends of its table, so the same 30 cases were run through both. The
predictions were written into the family's scoping note *before* the runs.
This is the only family where we can check the adapter rather than only use
it.

| | GPT-4o-mini | GLM-5.1 | GLM 5.3 Flash | paper: GPT-4o-mini | paper: GLM-5.1 |
|---|---:|---:|---:|---|---|
| `SE+` | **0.035** | **0.458** | 0.533 | 0.189 (its lowest) | — (table's best is 0.694) |
| `CSE+` | **0.044** | **0.458** | 0.533 | ~0.296 (its lowest) | **0.721 (its best)** |
| `AGR+` | **0.80** | **1.00** | 1.00 | **0.522 (its lowest)** | frontier 0.934 – 0.999 |
| `FAGR-` | 0.00 | 0.00 | 0.133 | ~0 | ~0 |
| `CritViol%` | 0.233 | 0.133 | 0.067 | band 0 – 0.0206 | 0.0133 |
| cost / wall | $0.003 / 0.7 min | $0.182 / 30.8 min | $0.134 / 43.5 min | | |

**The ordering reproduces.** GPT-4o-mini is the only agent in the set that
fails to close a feasible deal (`AGR+` 0.80 against 1.00), which is the
paper's own structural claim — every frontier agent between 0.934 and 0.999,
GPT-4o-mini alone at 0.522. On surplus the same two ends separate by 13×
here against the paper's 3.7×. The paper's third claim about GLM-5.1,
breaching its reservation in No-deal, did not reproduce: one breach in 30
cases, in an Overlap case.

**Every absolute level is displaced the same way** — lower surplus, higher
violations, for all three models. That is what a thinner agent scaffold
looks like: ours is one JSON call per turn with no memory, reflection or
planning stage, against the paper's own scaffold. A scoring defect would not
be expected to displace three different models uniformly while preserving
their order.

**One number needed decomposing, and the cause was ours** (TB-D-05).
GLM-5.1's `CritViol` of 0.133 is four cases: one reservation breach and
three accepts that echoed the counterpart's price. The strict schema that
`gpt-4o-mini` requires declares `price` **required** while the prompt says
not to include one for a non-offer; `price: null` satisfies both, and
GPT-4o-mini used it on all twenty of its non-offer turns. GLM-5.1 resolved
the contradiction toward the schema. Its negotiation-conduct violation rate
is 1/30, against the paper's 1.33% — close. The lesson generalises: when the
schema and the prompt disagree, the panel measures how the model resolves
your contradiction.

**Two limits on what can ever be checked here.** Claude Opus 4.6 and 4.7 —
the paper's best `SE+` — are unreachable: no OpenRouter endpoint for either
supports a declared seed, and this kernel refuses a diagnostic run without
one. GLM-5.1 is reachable only through DeepInfra, the sole endpoint offering
both a seed and structured output, at fp4.

## TERMS-Bench — the reasoning condition explains most of the compliance gap

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

## GovSim — the adapter reproduces both ends of the paper's range

Every govsim panel we had run survived 12 of 12 months, which cannot
distinguish a capable agent from a saturated task. Two more panels settle it.

| | our harness (3 cases, baseline arm) | the paper |
|---|---|---|
| `gpt-4o-mini` (not a paper agent) | **1.0 months, collapse in all three**, whole pool taken in round 1 | its eight collapsing agents: 1.0–1.1 months |
| `gpt-4o-2024-08-06` | 2 of 3 survive, **mean 8.7 months** | GPT-4o: 53.3% survival, **9.3 ± 2.2 months** |
| GLM 5.3 Flash | 3 of 3 survive, 12 months each | above its best |

The environment produces collapse, at the same figure the paper reports for
the agents that fail, and GPT-4o's mean survival here falls inside the
paper's interval for the same model family. GLM 5.3 Flash's 12/12 is
therefore a fact about a 2026 model rather than an artefact.

Unlike TERMS-Bench, the absolute numbers agree rather than merely the
ordering — which is what one would expect, because survival months is a
property of upstream's own environment dynamics, run here through the pinned
bridge, rather than of a scoring layer we reimplemented.

**None of the paper's agents is reachable**, and the second reason is worth
recording. Its Anthropic and open-weight rows have no endpoint accepting a
declared seed (#172). Its OpenAI rows — `gpt-3.5-turbo` and
`gpt-4o-2024-05-13` — refuse `response_format: json_schema` outright, because
OpenAI's Structured Outputs arrived with `2024-08-06`: **every agent the 2024
paper evaluated predates a feature this harness requires**. The models above
are the nearest reachable stand-ins, not the paper's rows, and the GPT-3.5
canary caught the difference for $0.00.

## EconEvals — comparable on two tracks; the difference is which attempt is scored

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

**Correction (2026-09-10).** An earlier version of this page said all three
tracks normalize against a uniform-random baseline, which we do not compute.
That is true only of scheduling. Upstream's own scoring notebooks are
explicit: procurement reports `max_ratio = max_utility / opt_utility`, and
pricing reports `total_profits / opt_profits` over rounds 50–100, each
multiplied by 100. Both are plain ratios to the optimum — exactly the
quantity our leaf already carries as `agent / v_star`. The random baseline
appears only in scheduling, where the metric is blocking pairs and zero is
optimal, and upstream computes it in
`calculate_scheduling_baseline.num_blocking_pairs_in_expectation`, which the
bridge can call.

What does separate us from the paper on those two tracks is **which attempt
is scored**. The paper takes the agent's best *feasible* attempt for
procurement and a 50–100 round window for pricing; our objective leaf is
declared `input_scope="terminal_state"` and scores the final submission. So
our procurement figures are a lower bound on the paper's statistic, not a
different scale, and our pricing figures are a different window rather than
a different normalization.

That cannot be recovered from `panel_v10`: the bundle records the terminal
value and `v_star`, not the per-attempt series. Closing it needs the leaf to
carry the maximum over feasible attempts (procurement) and the windowed sum
(pricing) as declared metrics, which is provider-free family work and a new
measurement identity, and then one panel to exercise it.

Scheduling is directly comparable at the extreme already, and the result is
a good one: the agent submitted a stable matching — zero blocking pairs, the
optimum — on both cases, which is what the paper's best model scored on that
tier.

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
| EconEvals: score the statistic the paper scores | procurement's max over feasible attempts and pricing's 50–100 window as declared metrics; scheduling's random baseline from upstream's own `num_blocking_pairs_in_expectation` | provider-free, then one panel |
| GovSim deliberating arm | ditto; today's `reasoning_low_v1` is a suppressed condition | ~$0.05 |
| TERMS-Bench interval width | the corpus generator can produce more than 30 cases; 300 would cost ~$1.3 at v3 rates | ~$1.3 |
| TERMS-Bench, GLM 5.3 Flash under the strict dialect | a like-for-like fourth panel, so all four sit under one schema | ~$0.13 |
| TERMS-Bench, a strict-dialect prompt that says "set price to null" | removes the schema/prompt contradiction (TB-D-05) | next identity |
| TERMS-Bench stress families | Strategic, Stochastic and Adversarial presets are not implemented | family work |
| tau3 | PR #97's split, then a panel that completes | see #97 |
