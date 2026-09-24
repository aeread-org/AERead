# Hidden-information case: judging a supplier from its record

Draft design, 2026-09-24. Replaces the qualification and unreliable-incumbent
strata, whose answer leaked through supplier names and whose cheaper supplier
was never bad (P-D-09, P-D-10). Generator and reference:
`src/aeread_families/procurement_allocation/supplier_profiles.py`
(`python -m aeread_families.procurement_allocation.supplier_profiles --out pack.json`).
Not yet wired into the environment.

## What is tested

Judging a supplier under hidden information: reading a public record for what
it does and does not show, deciding whether a test is worth its price, and
acting on the result. Not tested here: negotiation, deadlines, budgets.

## Three layers

| Layer | Buyer gets | Here |
|---|---|---|
| Prior | declared base rates | the market below, stated in the prompt (`market_facts_text`) |
| Signals | a public record, a paid sample, each delivered lot | profile page; 10-unit sample (noisy); a lot shows the supplier's kind |
| Truth | hidden, drawn from the prior | good or bad, per supplier per world |

Nothing else carries the truth: ids are neutral codes (`supplier_pmev`), listing
order is shuffled, both suppliers make the same claims, and price is set by
the cell, not by the type.

## The market (declared)

Shaped after what Alibaba shows and how guides say to read it: inflated
ratings, brushed reviews, Gold as a paid membership, Verified as a check on
the company rather than the product, on-time over protected orders only.

| | good | bad |
|---|---|---|
| prior share, 5+ years on platform / newer | 95% / 70% | 5% / 30% |
| units defective | 1% | 30% |
| on time | 97% | 85% |
| orders with a problem | 5% | 45% |
| holds Gold / Verified | 60% / 50% | 60% / 35% |

About 35% of orders get a review. Stars are inflated: a problem order still
gets five stars 30% of the time. A quarter of bad suppliers buy about six fake
orders with five-star reviews; fake orders are never protected. Reply time is
unrelated to type.

## The profile and its posterior

Simulated order by order from the hidden type, e.g.:

> supplier_fewy: 2 years on the platform, 15 orders; 5.0 stars from 7 reviews
> (5★ 7 · 4★ 0 · 3★ 0 · 2★ 0 · 1★ 0); 4/7 protected orders on time; Gold; replies within 4h

It reads as perfect, and P(bad) = 0.96: 4 of 7 protected orders on time is
what a bad supplier (85%) produces far more often than a good one (97%).

`posterior_bad` is exact under the declared model (it sums over the unseen
number of fake orders). Calibration on 6,000 simulated new suppliers: mean
posterior 0.110 / 0.270 / 0.495 / 0.691 / 0.952 against an actual bad share of
0.107 / 0.281 / 0.526 / 0.691 / 0.946 in the five bins.

## The case

One component, an established incumbent and a cheaper challenger, 4 periods
of 20 units. Each period the buyer may sample one supplier, then buys the lot
from one. A defective unit loses a kit ($10). The reference is the best policy
on the buyer's information, a dynamic programme over beliefs; the oracle knows
the types. Grading is ex ante: regret to the reference's expected value at the
buyer's beliefs, so a good bet that loses is not penalised.

## The pack: four cells, each rewarding a different first move

| Cell | Challenger record | Saving | Best first move | Example (seed) |
|---|---|---|---|---|
| switch_on_record | long and clean, P(bad) ≤ 0.03 | 25-34% | buy the challenger, no test | 12 yrs, 4.8★/100, 114/117 on time |
| test_thin_record | thin, P(bad) 0.15-0.5 | 25-34% | sample it | 1 yr, 5.0★/1, 3/4 on time |
| not_worth_testing | thin, P(bad) 0.15-0.5 | 6-10% | stay with the incumbent | 2 yrs, 4.5★/4, 4/4 on time |
| stars_mislead | outrates the incumbent, P(bad) ≥ 0.6 | 25-34% | stay with the incumbent | 5.0★/7 but 4/7 on time |

A world is admitted only if its intended move beats every other by at least
$1 in expectation. Where the record leaves real doubt (0.1 < P(bad) < 0.9) a
twin with the same record and the other hidden type is added: before any
evidence a good judge acts the same in both.

Expected regret of rules that do not judge (a draft pack of 3 seeds per cell):

| Rule | loses in |
|---|---|
| stay with the incumbent | switch_on_record ($28-31), test_thin_record ($6-13) |
| buy the cheapest, switch after a bad lot | test_thin_record, not_worth_testing, stars_mislead (to $46) |
| sample the cheapest, buy it if ≤1 defect | switch_on_record ($9-11), not_worth_testing, stars_mislead |
| buy the higher-rated | test_thin_record, stars_mislead (to $46) |

## Stated simplifications

A delivered lot reveals the supplier's kind (a 20-unit lot at 30% versus 1%
defects is misread under 1% of the time); the buyer is told this. Samples fit
inside a period; no deadline, budget or capacity binds. One component varies.

## Before a live run (new pack and campaign identity)

1. Environment: listings carry the profile and neutral ids; awards no longer
   require a sample; the prompt states `market_facts_text()`.
2. Checks rewritten on the buyer's view: tested when the test was worth it;
   skipped it when not; dropped a supplier after a failed sample or a bad lot;
   did not act on stars that the on-time record contradicts.
3. Leak audits: renaming invariance, label-free baselines no better than the
   prior allows, realised bad share in the pack against the declared prior.
4. A manual trace of one cell, then a small crossed pilot.

## Probe v2 (2026-09-24): diagnostic, not a claim

`tools/run_supplier_judgment_probe.py`, plan `runs/supplier_judgment_probe_v2/`
(ignored). 19 worlds of the draft pack (3 seeds per cell plus twins), Gemini
3.8 Flash (Google AI Studio) and GLM 5.3 Flash (Parasail), temperature 1.0,
reasoning effort low, one run, common random sample and lot outcomes across
models. 37 of 38 episodes completed; one GLM episode is typed missingness (a
429 from the upstream after 3 attempts, not rerun). Cost $0.13. A dry run with
the reference as the model scores 0 regret and 19/19 correct first moves.
Probe v1 was stopped by P-T-10 with 6 episodes written; they are not graded.

Decision regret: at every decision, the reference's value of its best action
minus the value of the action taken, at the buyer's exact beliefs, summed
over the episode. Rules are scored by their expected regret on the same worlds.

| Mean regret, $ | switch_on_record | test_thin_record | not_worth_testing | stars_mislead | all |
|---|---|---|---|---|---|
| Gemini 3.8 Flash | 0.00 | 3.99 | 0.00 | 2.05 | 1.69 |
| GLM 5.3 Flash | 9.22 | 0.00 | 6.02 | 5.21 | 4.19 |
| stay with the incumbent | 29.46 | 10.35 | 0.00 | 0.00 | 7.92 |
| buy the cheapest | 0.00 | 6.33 | 5.18 | 31.94 | 10.36 |
| sample the cheapest | 9.44 | 0.40 | 3.86 | 9.32 | 4.80 |
| buy the higher-rated | 10.35 | 8.32 | 0.00 | 31.94 | 10.98 |

First moves: GLM sampled in 16 of 19 worlds whatever the cell, and its regret
profile is the "sample the cheapest" rule's. Gemini stayed with the incumbent
unless the challenger's record was long and clean, and missed the worthwhile
test on a thin record in 3 of 6 worlds; it beat every rule overall.

Stated beliefs track the exact posterior (mean absolute gap 0.02-0.07) except
in stars_mislead (0.15-0.17), where the evidence is an on-time shortfall or
padded review counts; GLM named the padding in its reasons and sampled anyway.
So on this probe the models read the record about right and differ in what
they do with it: whether a test is worth its price.

What this supports: the four cells separate two decision styles the old
strata could not, and no fixed rule matches the reference. What it does not:
any model ranking (19 worlds, one run, twins not independent), or anything
about the environment's deadlines, budgets and negotiation, which the draft
leaves out.
