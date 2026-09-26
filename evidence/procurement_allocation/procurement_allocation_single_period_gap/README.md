# procurement_allocation_single_period_gap

Why a prompt treatment changes regret on the single-period procurement worlds. One model, GLM 5.3 Flash on Parasail, under two prompts, paired cell by cell on the same world and inference seed; treatment against control, not model against model. Derived from published bundles and the committed cases by `python -m aeread_families.procurement_allocation.single_period_gap`, which replays every published action trace (all 144 + 36 rows reproduce their published margin, regret, bound, feasibility, kits, termination and violations); `--check` regenerates these bytes. Descriptive: no winner, no ranking.

The endpoint is minus `regret_to_upper_bound_usd` (higher is better), in USD per world. A submitted award that breaks a gate is scored at the defer value less the information already bought, so it loses nearly the whole bound; that cell's endpoint is one part, and a cell that ends with no award is another. A feasible award's regret is the ten additive term gaps against the full-information plan (`regret_decomposition.decompose_feasible_award`), grouped into four parts. When a treatment turns a rejected award into a feasible one, the gain shows up in the gate part and whatever the new award still loses shows up in the feasible-award parts, so read the parts together with the pair transitions, which net the two.

## Why the strategy scaffold changes regret

`procurement_allocation_glm53_flash_parasail_strategy_confirmatory_v2`: strategy scaffold (`procurement_allocation_strategy_scaffold_v3`) against the unscaffolded prompt (`procurement_allocation_prompt_v1`), 12 worlds x labeled and opaque surfaces x 3 seeds, 72 cells a side.

The scaffold's +26.0 per world comes from fewer awards rejected at a gate. In 20 pairs the unscaffolded award broke a gate and the scaffolded one was feasible (+29.4 per world, net of what the new awards still lose); in 16 of those the unscaffolded award left a bill-of-materials component with no supplier at all. That failure is 29 unscaffolded cells and 0 scaffolded ones. 3 pairs went the other way (-5.5), and where both awards were feasible (18 pairs) the scaffold moved the economics by only +0.9. The scaffold's own rejected awards fail differently: 9 carry an unverified sample (against 2), 6 a line that could no longer arrive in time (against 1), and 10 too few units with every component in place (against 8).

| unscaffolded ended | strategy scaffold ended | pairs | contribution to the gap, USD/world | unscaffolded classes in these pairs |
|---|---|---:|---:|---|
| award rejected at a gate | feasible award | 20 | 29.38 | cash_budget_exceeded 3, component_not_awarded 16, invalid_order_step 1, minimum_service_not_met 18, quantity_short 2 |
| feasible award | award rejected at a gate | 3 | -5.55 | none |
| no award | feasible award | 1 | 1.38 | interaction_budget_exhausted 1 |
| feasible award | feasible award | 18 | 0.92 | none |
| award rejected at a gate | award rejected at a gate | 25 | -0.09 | arrives_after_deadline 1, below_moq 1, cash_budget_exceeded 3, component_not_awarded 12, invalid_order_step 1, minimum_service_not_met 20, quantity_short 5, sample_not_verified 2 |
| award rejected at a gate | no award | 2 | 0.00 | cash_budget_exceeded 1, component_not_awarded 1, minimum_service_not_met 2, quantity_short 1 |
| no award | award rejected at a gate | 3 | -0.00 | deferred 1, interaction_budget_exhausted 1, unparseable_action 1 |

| part | strategy scaffold | unscaffolded | strategy scaffold minus unscaffolded |
|---|---:|---:|---:|
| **minus regret (realized)** | **-67.9** | **-93.9** | **26.0** |
| award rejected at a gate (procedure) | -57.7 | -81.1 | 23.4 |
| no award: deferred, out of actions, or unparseable (procedure) | -4.1 | -8.3 | 4.2 |
| kits short of the full-information plan (outcome) | -0.2 | -0.5 | 0.3 |
| landed price above the plan (cost) | -1.4 | -1.1 | -0.3 |
| payment terms and returns (cost) | -4.5 | -2.9 | -1.6 |
| information bought beyond the plan's (cost) | 0.0 | 0.0 | 0.0 |

The environment never reads the inference seed: the three seeds of a world and surface replay one case digest and only the model's sampling differs, so the world is the unit and no interval is given. The confirmatory's own frozen analysis published a 12-world bootstrap for the headline, 7.2 to 46.1. The realized gap equals that published treatment-minus-control margin effect (26.0384) and its per-surface values (16.8383 labeled, 35.2385 opaque); the replayed terms of all 60 feasible awards equal `procurement_allocation_glm_regret_decomposition_v1`'s. Largest per-cell residual 1e-08.

| surface | realized | infeasible_award | no_award | kits_short | landed_cost | terms_and_returns | information_spend |
|---|---:|---:|---:|---:|---:|---:|---:|
| labeled | 16.8 | 16.5 | 3.3 | -0.4 | -0.9 | -1.7 | 0.0 |
| opaque | 35.2 | 30.3 | 5.0 | 0.9 | 0.3 | -1.4 | 0.1 |

Failure classes (diagnostic, overlapping, not parts of the sum). Counts are cells; amounts are the regret of the cells carrying the class, per world. The last three split `minimum_service_not_met` by what the replay shows:

| class | strategy scaffold cells | unscaffolded cells | strategy scaffold regret/world | unscaffolded regret/world |
|---|---:|---:|---:|---:|
| `cash_budget_exceeded`: the award's cash spend (goods, freight, duty, information) exceeds the budget | 6 | 7 | 8.7 | 11.7 |
| `minimum_service_not_met`: the award completes fewer expected kits than the minimum service level | 25 | 40 | 49.0 | 69.2 |
| `sample_not_verified`: an awarded supplier's sample was never verified, so its units count for nothing | 9 | 2 | 17.3 | 4.0 |
| `invalid_order_step`: an awarded quantity is off the supplier's order step | 0 | 2 | 0.0 | 2.9 |
| `below_moq`: an awarded quantity is below the supplier's minimum order | 0 | 1 | 0.0 | 2.5 |
| `interaction_budget_exhausted`: the action budget ran out with no award or defer | 0 | 2 | 0.0 | 4.1 |
| `unparseable_action`: an action could not be parsed, which ends the episode | 1 | 1 | 2.1 | 2.1 |
| `deferred`: deferred instead of awarding, forgoing the bound (a choice, not a violation) | 1 | 1 | 2.1 | 2.2 |
| `component_not_awarded`: the award leaves a bill-of-materials component with no supplier | 0 | 29 | 0.0 | 49.8 |
| `arrives_after_deadline`: an awarded line can no longer arrive by the deadline (located at the step that used up the slack) | 6 | 1 | 13.1 | 2.2 |
| `quantity_short`: every component awarded, verified and on time, but too few expected good units | 10 | 8 | 18.6 | 13.3 |

Steps are located in the trajectory grain published for this bundle in `procurement_allocation_trajectory_grains_v1`: one logical action per step, step index = action ordinal - 1, each step its own instance of the only phase, so the round index equals the step index. Every contribution row and instance names the action and supplier at its step, and a test checks both against the grain. A late line is located at the step whose days used up its slack; every other class at the award, defer, or ending step. 5 published `action_trace` entries for an award or defer carry a `supplier_id` that the parser discards (the grain's parsed action has none), so rows name a supplier only for actions addressed to one.

## Why the pre-award check changes regret on noisy-sample worlds

`procurement_allocation_unified_regret_recovery_v2`: the pre-award check worksheet against the strategy scaffold, both with the binomial sample notice, 6 worlds x 3 seeds, 18 cells a side. Each seed binds that episode's sample-noise draw, so seeds are distinct cases of a world, and intervals are a world-clustered bootstrap (seed 20260925, 10000 draws) over only 6 worlds.

The worksheet's +5.0 per world involves no award rejected at a gate on either side. 2.4 of it is the 1 pair where the scaffold deferred and the worksheet awarded: the defer forgoes the whole bound (+4.9 in the no-award part), and the worksheet's award there gives back -2.5 in the feasible-award parts. The other 2.6 comes from the 17 pairs where both sides awarded: kits short of the full-information plan +2.36, landed price above the plan +0.61, payment terms and returns -0.33, information bought beyond the plan's -0.03. The realized gap equals minus the published mean regret delta (-5.0226); largest per-cell residual 1e-08.

| strategy scaffold ended | pre-award check ended | pairs | contribution to the gap, USD/world | strategy scaffold classes in these pairs |
|---|---|---:|---:|---|
| feasible award | feasible award | 17 | 2.60 | none |
| no award | feasible award | 1 | 2.42 | deferred 1 |

| part | pre-award check | strategy scaffold | pre-award check minus strategy scaffold (95% world bootstrap) |
|---|---:|---:|---:|
| **minus regret (realized)** | **-29.9** | **-35.0** | **5.0** (0.8 to 9.7) |
| award rejected at a gate (procedure) | 0.0 | 0.0 | 0.0 (0.0 to 0.0) |
| no award: deferred, out of actions, or unparseable (procedure) | 0.0 | -4.9 | 4.9 (0.0 to 14.8) |
| kits short of the full-information plan (outcome) | -41.0 | -40.2 | -0.8 (-9.5 to 7.1) |
| landed price above the plan (cost) | 14.2 | 12.6 | 1.6 (0.5 to 3.4) |
| payment terms and returns (cost) | -4.3 | -3.5 | -0.8 (-2.4 to 0.6) |
| information bought beyond the plan's (cost) | 1.1 | 1.0 | 0.1 (-0.4 to 0.5) |

| class | pre-award check cells | strategy scaffold cells | pre-award check regret/world | strategy scaffold regret/world |
|---|---:|---:|---:|---:|
| `deferred`: deferred instead of awarding, forgoing the bound (a choice, not a violation) | 0 | 1 | 0.0 | 4.9 |

No step-level log is published for this bundle, so its contribution rows and instances carry null step fields and name the action by `action_ordinal`, its place in the published `action_trace`.

Reports: `reports/gap_decomposition.json` and `reports/gap_decomposition_pre_award_check.json`, each with every cell's parts, the pair transitions, and every class instance at its step. Tables: `tables/contributions.jsonl` (527 rows) and `tables/contributions_pre_award_check.jsonl` (315 rows), one row per decision per part; per cell a part's rows sum to that cell's part (largest difference 4.4e-16).
