# datacenter_risk_allocation_gap

Why gemini-3.8-flash (left) and glm-5.3-flash (right) differ on `datacenter_risk_allocation_dev_campaign_v1`, seat by seat. Derived from that published bundle and the committed cases it ran by `python -m aeread_families.datacenter_development.risk_allocation_gap`; `--check` regenerates these bytes. Diagnostic: one run per cell on a 16-world dev pack, no winner, no ranking.

The endpoint is minus decision regret ($ thousands; higher is better). The bundle publishes only each episode's sum. Every episode that ended on a move (171 cells) is replayed through the plugin from its published trajectory and reproduces every published grade field, and every move is re-graded with the family's own solver, reproducing the plugin's regret move by move. Each move's regret is split by what the move was: a proposal into the package (proposing that package in its best way, against the best move) and the price (the model's price or request, against that best way); an accept or a walk is one part. The first move's parts are the opening ones. Per cell the parts sum to minus the published decision regret (largest residual 5.7e-14). The published `allocation_gap` and `price_gap` are not parts: they are judged against the true types, not the model's information, and do not add up to the score, so they appear as outcome classes. The break-off draw never enters the score, so there is no luck part.

The unit is the world. A twin shares its base world's seed, public facts and break-off draws, so the 16 worlds form 12 clusters (checked); amounts are means over paired worlds, and intervals resample clusters (10000 draws, seed 20260927), only where at least 10 clusters are paired. A world enters a comparison only when both models' episodes are valid; the others are typed missingness, never zeros.

| arm | seat | paired worlds (clusters) | valid, left / right | report |
|---|---|---|---|---|
| one_price_low (primary) | client | 16 (12) | 16 / 16 of 16 | `gap_decomposition_one_price_low_client.json` |
| one_price_low (primary) | integrator | 16 (12) | 16 / 16 of 16 | `gap_decomposition_one_price_low_integrator.json` |
| one_price_default | client | 13 (11) | 16 / 13 of 16 | `gap_decomposition_one_price_default_client.json` |
| one_price_default | integrator | 5 (5) | 16 / 5 of 16 | none: 5 paired worlds, fewer than the 10 a report needs |
| two_prices_low | client | 10 (9) | 16 / 10 of 16 | `gap_decomposition_two_prices_low_client.json` |
| two_prices_low | integrator | 13 (10) | 14 / 15 of 16 | `gap_decomposition_two_prices_low_integrator.json` |

## one_price_low, client seat

16 paired worlds in 12 clusters; 30 and 37 moves re-graded. Largest parts of the difference: accepting or walking +52.8, later price or request +9.2.

| part | gemini-3.8-flash | glm-5.3-flash | gemini-3.8-flash minus glm-5.3-flash (95% cluster bootstrap) |
|---|---|---|---|
| **minus decision regret** | **-122.3** | **-164.2** | **41.9 (-53.5 to 113.5)** |
| opening package | -12.1 | -7.3 | -4.8 (-13.3 to 0.3) |
| opening price or request | -46.4 | -38.5 | -7.9 (-35.7 to 8.7) |
| later package | -38.5 | -31.1 | -7.4 (-32.8 to 14.6) |
| later price or request | -25.3 | -34.6 | 9.2 (-49.0 to 48.4) |
| accepting or walking | 0.0 | -52.8 | 52.8 (0.0 to 93.8) |

| class | gemini-3.8-flash count | glm-5.3-flash count | gemini-3.8-flash $k/world | glm-5.3-flash $k/world |
|---|---|---|---|---|
| `proposed_when_walking_or_accepting_was_best` (decision) | 4 | 1 | 6.2 | 1.6 |
| `opened_with_another_package` (decision) | 2 | 3 | 9.0 | 5.7 |
| `kept_its_first_package` (decision) | 11 | 3 | 35.4 | 10.4 |
| `switched_to_the_wrong_package` (decision) | 0 | 5 | 0.0 | 20.7 |
| `asked_when_it_should_have_offered` (decision) | 1 | 10 | 30.1 | 67.9 |
| `offered_when_it_should_have_asked` (decision) | 2 | 0 | 25.3 | 0.0 |
| `offered_a_worse_signing_price` (decision) | 1 | 1 | 16.3 | 5.1 |
| `took_a_counter_when_proposing_was_better` (decision) | 0 | 3 | 0.0 | 52.8 |
| `signed_an_inefficient_contract` (outcome) | 13 | 11 | 63.8 | 47.6 |
| `price_left_to_the_counterpart` (outcome) | 0 | 4 | 0.0 | 54.8 |
| `broke_off_after_a_refusal` (luck) | 2 | 2 | 214.1 | 178.8 |

## one_price_low, integrator seat

16 paired worlds in 12 clusters; 30 and 36 moves re-graded. Largest parts of the difference: accepting or walking +117.1, opening price or request -45.3.

| part | gemini-3.8-flash | glm-5.3-flash | gemini-3.8-flash minus glm-5.3-flash (95% cluster bootstrap) |
|---|---|---|---|
| **minus decision regret** | **-158.2** | **-204.7** | **46.5 (-77.8 to 130.8)** |
| opening package | -10.4 | -10.4 | 0.0 (0.0 to 0.0) |
| opening price or request | -69.4 | -24.1 | -45.3 (-122.8 to -1.1) |
| later package | -49.4 | -41.3 | -8.1 (-41.8 to 26.6) |
| later price or request | -29.0 | -11.9 | -17.2 (-71.7 to 17.8) |
| accepting or walking | 0.0 | -117.1 | 117.1 (51.5 to 187.6) |

| class | gemini-3.8-flash count | glm-5.3-flash count | gemini-3.8-flash $k/world | glm-5.3-flash $k/world |
|---|---|---|---|---|
| `proposed_when_walking_or_accepting_was_best` (decision) | 3 | 3 | 4.7 | 4.7 |
| `opened_with_another_package` (decision) | 2 | 2 | 8.8 | 8.8 |
| `kept_its_first_package` (decision) | 9 | 4 | 46.2 | 27.6 |
| `switched_to_the_wrong_package` (decision) | 0 | 1 | 0.0 | 10.6 |
| `asked_when_it_should_have_offered` (decision) | 0 | 2 | 0.0 | 7.0 |
| `offered_when_it_should_have_asked` (decision) | 4 | 1 | 35.1 | 2.4 |
| `offered_a_worse_signing_price` (decision) | 2 | 2 | 59.7 | 21.7 |
| `refused_at_the_stated_price` (format) | 1 | 1 | 3.7 | 4.9 |
| `took_a_counter_when_proposing_was_better` (decision) | 0 | 7 | 0.0 | 115.2 |
| `accepted_when_walking_was_better` (decision) | 0 | 1 | 0.0 | 1.9 |
| `signed_an_inefficient_contract` (outcome) | 12 | 9 | 80.0 | 57.4 |
| `price_left_to_the_counterpart` (outcome) | 2 | 8 | 82.2 | 103.5 |
| `broke_off_after_a_refusal` (luck) | 1 | 2 | 104.1 | 183.7 |

## Other arms, extra reports

gemini-3.8-flash minus glm-5.3-flash, $k per paired world (95% cluster bootstrap where there are enough clusters):

| part | one_price_default, client (13 worlds) | two_prices_low, client (10 worlds) | two_prices_low, integrator (13 worlds) |
|---|---|---|---|
| **minus decision regret** | **-3.0 (-101.8 to 119.8)** | **50.4** | **95.1 (-23.8 to 174.8)** |
| opening package | -18.7 (-60.1 to 3.9) | 0.3 | -0.5 (-1.9 to 0.0) |
| opening price or request | 39.1 (-17.5 to 137.6) | 44.2 | -26.7 (-107.7 to 19.3) |
| later package | -10.9 (-20.5 to -1.5) | -4.6 | -25.4 (-46.7 to -6.7) |
| later price or request | -12.5 (-76.2 to 25.2) | -8.0 | -7.4 (-33.3 to 18.2) |
| accepting or walking | 0.0 (0.0 to 0.0) | 18.6 | 155.2 (78.9 to 221.8) |

## Left out, by cause

| report | gemini-3.8-flash | glm-5.3-flash |
|---|---|---|
| one_price_low, client | none | none |
| one_price_low, integrator | none | none |
| one_price_default, client | valid_but_unpaired 3 | provider_rejected 1, transport 1, truncated_reply 1 |
| two_prices_low, client | valid_but_unpaired 6 | rate_limit 5, truncated_reply 1 |
| two_prices_low, integrator | rate_limit 2, valid_but_unpaired 1 | rate_limit 1, valid_but_unpaired 2 |

Classes are diagnostic, counted over paired cells, and are not parts of the sum. A move class needs the move to give up at least $1k, the published strict-pass line; its amount is the part it explains, so the move classes split the regret of those moves further. `refused_at_the_stated_price` is an environment defect, not a pricing error: the counterpart states its price rounded, and a proposal at the stated figure is refused when the rounding went to the refusing side (DC-D-25 in `docs/operations/incident_log.md`).

Each report is `reports/gap_decomposition_<arm>_<seat>.json`, with every cell's parts and every class instance at the step that made it; `tables/contributions_<arm>_<seat>.jsonl` has one row per move per part, with the move and its step, and per cell a part's rows sum to that cell's part.
