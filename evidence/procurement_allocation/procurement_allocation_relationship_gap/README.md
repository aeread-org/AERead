# procurement_allocation_relationship_gap

Why Gemini 3.8 Flash and GLM 5.3 Flash differ on the procurement repeated-sourcing worlds (four periods, loyalty discounts, retaliation markups, `interaction.periods`). Derived from the published bundles and the committed worlds re-sealed per seed, by `python -m aeread_families.procurement_allocation.relationship_gap`; `--check` regenerates these bytes. Descriptive: no winner, no ranking, and nothing here adds to the pre-registered confirmatory claims.

The endpoint is minus regret to the T-period bound (`contribution_margin_usd - upper_bound_usd`), higher is better. The bound is one number per world, identical on every seed and both sides, so the gap is the margin gap; measuring each part against the bound's own plan for the same period makes a part read as a shortfall against the optimum and puts a lost period in one part instead of spreading it over revenue and cost. Every published trajectory is re-driven through the plugin, each period scored by `evaluate_award` on `relationship.period_case`, and the replay reproduces every published period margin, the bound and the three references. There is no luck part: awards are scored on expected units at true yield and on-time rates, and the delivery draw never enters a margin. The unit is the world; intervals are a world-clustered bootstrap.

## holdout: `procurement_allocation_relationship_holdout_gemini38_flash_confirmatory_v1` against `procurement_allocation_relationship_holdout_glm53_flash_confirmatory_v1`

Of the +33.23 USD/world gap (gemini-3.8-flash minus glm-5.3-flash), periods lost to a rejected award, a malformed action or never played carry +20.76 and loyalty discounts and retaliation markups +13.35. Of 240 periods, glm-5.3-flash lost 6 to rejected awards and 2 to malformed actions, leaving 3 unplayed; gemini-3.8-flash lost 0, 0 and 0.

12 worlds, 60 paired cells per side; claim status `descriptive_post_hoc`: the confirmatory holdout pack (relationship_holdout_v1); the decomposition was not pre-registered, so it explains the published gap and adds no confirmatory claim.

| part (USD per world, against the bound) | gemini-3.8-flash | glm-5.3-flash | gemini-3.8-flash minus glm-5.3-flash (95% world bootstrap) |
|---|---|---|---|
| **minus regret (realized)** | -32.36 | -65.60 | +33.23 (+17.24 to +50.69) |
| kits sold, less the shortfall penalty (outcome) | 0.00 | -0.87 | +0.87 (+0.00 to +2.60) |
| suppliers and quantities at list price (decision) | -5.75 | -6.12 | +0.37 (-4.57 to +6.68) |
| loyalty discounts and retaliation markups (decision) | -7.77 | -21.12 | +13.35 (+6.51 to +20.29) |
| counter-offer concessions (decision) | -18.37 | -16.77 | -1.60 (-2.66 to -0.62) |
| shipping, duty, financing and returns (cost) | -2.87 | -3.32 | +0.45 (+0.18 to +0.70) |
| inquiries, quotes, samples and counters (cost) | 2.40 | 3.36 | -0.96 (-2.80 to +0.36) |
| periods lost to a rejected award, a malformed action or never played (procedure) | 0.00 | -20.76 | +20.76 (+6.30 to +37.09) |

Largest per-cell residual 4e-08; contribution rows (3294, `tables/contributions_holdout.jsonl`) sum to their cell's part within 1.8e-15.

| class | gemini-3.8-flash count | glm-5.3-flash count | gemini-3.8-flash USD/world | glm-5.3-flash USD/world |
|---|---|---|---|---|
| `malformed_action`: an action the environment could not parse ended the episode | 0 | 2 | 0.00 | -8.79 |
| `unplayed_period`: a period never played because the episode had ended | 0 | 3 | 0.00 | -5.38 |
| `below_minimum_service`: an award rejected because its expected kits fell below the period's minimum service | 0 | 6 | 0.00 | -11.97 |
| `late_award`: an award placed on a day when one of its lines could no longer arrive by the deadline | 0 | 3 | 0.00 | -5.91 |
| `unverified_sample`: an award rejected for a supplier with no verified sample | 0 | 3 | 0.00 | -6.06 |
| `over_capacity`: an award rejected for ordering above a supplier's capacity | 0 | 0 | 0.00 | 0.00 |
| `awarded_above_floor`: a feasible award priced above the supplier's floor on at least one line | 240 | 229 | -20.26 | -19.28 |
| `counter_rejected`: a counter-offer the supplier refused | 0 | 15 | 0.00 | -0.04 |
| `loyalty_discount`: a feasible award priced under a loyalty discount (a gain, not a failure) | 125 | 69 | 18.68 | 4.18 |
| `retaliation_markup`: a feasible award priced under a retaliation markup from a supplier quoted and dropped the period before | 0 | 0 | 0.00 | 0.00 |
| `supplier_switch`: a feasible award whose supplier set differs from the previous feasible award's (as the family counts switches) | 7 | 16 | 0.00 | 0.00 |
| `inquiry`: a verbal inquiry: it never authorizes an award | 8 | 84 | -0.01 | -0.07 |

Against the published references (each reconstructed period by period and split into the same parts), model minus reference, USD per world:

| part | gemini-3.8-flash minus myopic | glm-5.3-flash minus myopic | gemini-3.8-flash minus loyal | glm-5.3-flash minus loyal | gemini-3.8-flash minus shopping | glm-5.3-flash minus shopping |
|---|---|---|---|---|---|---|
| minus regret (realized) | -7.34 | -40.57 | +43.64 | +10.40 | -4.64 | -37.88 |
| kits sold, less the shortfall penalty | +0.00 | -0.87 | +0.00 | -0.87 | +0.00 | -0.87 |
| suppliers and quantities at list price | +1.58 | +1.21 | +2.29 | +1.92 | +1.79 | +1.42 |
| loyalty discounts and retaliation markups | +14.57 | +1.22 | +9.47 | -3.88 | +14.57 | +1.22 |
| counter-offer concessions | -21.23 | -19.63 | -20.96 | -19.36 | -19.55 | -17.95 |
| shipping, duty, financing and returns | -1.87 | -2.32 | -2.04 | -2.49 | -1.66 | -2.11 |
| inquiries, quotes, samples and counters | -0.39 | +0.57 | -0.69 | +0.27 | +0.21 | +1.17 |
| periods lost to a rejected award, a malformed action or never played | +0.00 | -20.76 | +55.57 | +34.81 | +0.00 | -20.76 |

Seeds: each re-seals the world's delivery draws and sample noise, so the buyer reads different samples, but gemini-3.8-flash's decisions mostly repeat across them (26 distinct decision sequences in 60 cells) where glm-5.3-flash's rarely do (57 in 60); the world is the unit either way.

Delivery draws differed from the scored kits in 159 of 240 awarded gemini-3.8-flash periods and 155 of 229 glm-5.3-flash periods, and moved no margin.

## dev2: `procurement_allocation_relationship_dev2_gemini38_flash_variance_v2` against `procurement_allocation_relationship_dev2_glm53_flash_variance_v2`

Of the +52.39 USD/world gap (gemini-3.8-flash minus glm-5.3-flash), periods lost to a rejected award, a malformed action or never played carry +41.80 and loyalty discounts and retaliation markups +14.95. Of 236 periods, glm-5.3-flash lost 14 to rejected awards and 4 to malformed actions, leaving 6 unplayed; gemini-3.8-flash lost 1, 0 and 0.

12 worlds, 59 paired cells per side; claim status `development_qualification`: the development pack (relationship_dev_v2), read to see whether the parts hold on another set of worlds. Excluded: 2 cell(s), listed in the report.

| part (USD per world, against the bound) | gemini-3.8-flash | glm-5.3-flash | gemini-3.8-flash minus glm-5.3-flash (95% world bootstrap) |
|---|---|---|---|
| **minus regret (realized)** | -33.72 | -86.11 | +52.39 (+34.07 to +72.32) |
| kits sold, less the shortfall penalty (outcome) | 0.00 | -1.30 | +1.30 (+0.00 to +3.90) |
| suppliers and quantities at list price (decision) | -8.72 | -4.66 | -4.06 (-7.70 to -0.00) |
| loyalty discounts and retaliation markups (decision) | -5.30 | -20.25 | +14.95 (+7.88 to +21.95) |
| counter-offer concessions (decision) | -18.65 | -16.61 | -2.04 (-3.11 to -1.05) |
| shipping, duty, financing and returns (cost) | -2.93 | -3.16 | +0.23 (-0.23 to +0.63) |
| inquiries, quotes, samples and counters (cost) | 3.58 | 3.38 | +0.20 (-0.71 to +0.92) |
| periods lost to a rejected award, a malformed action or never played (procedure) | -1.70 | -43.51 | +41.80 (+21.01 to +64.74) |

Largest per-cell residual 5e-08; contribution rows (3205, `tables/contributions_dev2.jsonl`) sum to their cell's part within 1.9e-15.

| class | gemini-3.8-flash count | glm-5.3-flash count | gemini-3.8-flash USD/world | glm-5.3-flash USD/world |
|---|---|---|---|---|
| `malformed_action`: an action the environment could not parse ended the episode | 0 | 4 | 0.00 | -19.88 |
| `unplayed_period`: a period never played because the episode had ended | 0 | 6 | 0.00 | -14.91 |
| `below_minimum_service`: an award rejected because its expected kits fell below the period's minimum service | 1 | 12 | -1.70 | -20.07 |
| `late_award`: an award placed on a day when one of its lines could no longer arrive by the deadline | 1 | 7 | -1.70 | -11.56 |
| `unverified_sample`: an award rejected for a supplier with no verified sample | 0 | 4 | 0.00 | -6.69 |
| `over_capacity`: an award rejected for ordering above a supplier's capacity | 0 | 2 | 0.00 | -3.56 |
| `awarded_above_floor`: a feasible award priced above the supplier's floor on at least one line | 235 | 212 | -20.32 | -18.69 |
| `counter_rejected`: a counter-offer the supplier refused | 0 | 17 | 0.00 | -0.04 |
| `loyalty_discount`: a feasible award priced under a loyalty discount (a gain, not a failure) | 125 | 66 | 21.25 | 4.66 |
| `retaliation_markup`: a feasible award priced under a retaliation markup from a supplier quoted and dropped the period before | 0 | 1 | 0.00 | -0.25 |
| `supplier_switch`: a feasible award whose supplier set differs from the previous feasible award's (as the family counts switches) | 6 | 17 | 0.00 | 0.00 |
| `inquiry`: a verbal inquiry: it never authorizes an award | 4 | 89 | -0.00 | -0.08 |

Against the published references (each reconstructed period by period and split into the same parts), model minus reference, USD per world:

| part | gemini-3.8-flash minus myopic | glm-5.3-flash minus myopic | gemini-3.8-flash minus loyal | glm-5.3-flash minus loyal | gemini-3.8-flash minus shopping | glm-5.3-flash minus shopping |
|---|---|---|---|---|---|---|
| minus regret (realized) | -7.74 | -60.13 | +43.62 | -8.77 | -5.14 | -57.54 |
| kits sold, less the shortfall penalty | +0.00 | -1.30 | +0.00 | -1.30 | +0.00 | -1.30 |
| suppliers and quantities at list price | +0.07 | +4.13 | +0.45 | +4.51 | +0.30 | +4.36 |
| loyalty discounts and retaliation markups | +16.67 | +1.72 | +10.73 | -4.22 | +16.67 | +1.72 |
| counter-offer concessions | -21.35 | -19.31 | -21.01 | -18.97 | -19.79 | -17.75 |
| shipping, duty, financing and returns | -1.86 | -2.09 | -2.07 | -2.30 | -1.66 | -1.89 |
| inquiries, quotes, samples and counters | +0.43 | +0.23 | +0.15 | -0.05 | +1.04 | +0.84 |
| periods lost to a rejected award, a malformed action or never played | -1.70 | -43.51 | +55.37 | +13.57 | -1.70 | -43.51 |

Seeds: each re-seals the world's delivery draws and sample noise, so the buyer reads different samples, but gemini-3.8-flash's decisions mostly repeat across them (25 distinct decision sequences in 59 cells) where glm-5.3-flash's rarely do (58 in 59); the world is the unit either way.

Delivery draws differed from the scored kits in 153 of 235 awarded gemini-3.8-flash periods and 137 of 212 glm-5.3-flash periods, and moved no margin.

The published `action_counts`, `counters` and `inquiries` of the source bundles also count a malformed action as the type it attempted (P-T-11); the classes here count executed actions from the trajectory. Two sentences of the source READMEs do not hold for these packs (P-T-12): the seeds reach the buyer from period one through the sample noise, and both packs are 12 rule-selected worlds.

Every class instance and every cell's parts are in `reports/gap_decomposition_<pack>.json`; each contribution row names the step (`step_index`, `round_index`, `phase_id`, `seat_id`, and the `action` published there) that made it. Rows at a period's closing step also carry the bound's plan for that period, so the part is the buyer's decision against the optimum's.
