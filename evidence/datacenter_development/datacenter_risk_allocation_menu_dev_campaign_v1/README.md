# datacenter_risk_allocation_menu_dev_campaign_v1

The playbook-menu variant of the integrator-client risk-allocation case (`docs/families/datacenter/risk_allocation_case.md`): a scripted integrator posts one of three playbooks (coordination, managed, turnkey) with a menu pricing every combination of three negotiable options, by a policy the client is not told; the model, as client, accepts an item, counters one, or walks to a rival turnkey offer or to managing the deployment itself. Sealed, verified and replayed through the shared runner. It does not rank models.

Decision regret ($ thousands) is what each move gave up against a client who knows how integrators in this market choose and price their menus, summed over the episode.

| arm / client | valid | decision regret [95% CI] | zero regret | signed the best item | walked to the best outside option | cost over best attainable |
|---|---|---|---|---|---|---|
| default_reasoning/gemini38_flash | 72/72 | 182.468 [135.976, 231.824] | 15 | 9 of 48 | 22 of 24 | 238.32 |
| default_reasoning/glm53_flash | 35/72 | 46.466 [28.286, 67.13] | 5 | 1 of 17 | 15 of 18 | 84.866 |
| low_effort/gemini38_flash | 70/72 | 453.197 [350.213, 560.864] | 1 | 5 of 47 | 3 of 23 | 498.825 |
| low_effort/glm53_flash | 64/72 | 269.544 [192.84, 352.745] | 6 | 5 of 41 | 12 of 23 | 321.135 |
| scripted_controls/scripted_accept_the_first_item | 36/36 | 705.835 [603.686, 803.195] | 0 | 2 of 24 | 0 of 12 | 764.152 |
| scripted_controls/scripted_cheapest_all_in_price | 36/36 | 727.622 [623.153, 820.604] | 0 | 2 of 24 | 0 of 12 | 785.939 |
| scripted_controls/scripted_haggle_the_base_item | 36/36 | 364.058 [283.045, 448.824] | 0 | 0 of 24 | 0 of 12 | 385.286 |
| scripted_controls/scripted_reference | 36/36 | 0.0 [0.0, 0.0] | 36 | 22 of 24 | 12 of 12 | 53.124 |
| scripted_controls/scripted_walk_to_turnkey | 36/36 | 564.147 [439.604, 688.473] | 6 | 0 of 24 | 6 of 12 | 622.464 |

## The declared contrast

per arm, the mean paired difference in decision regret, GLM 5.3 Flash minus Gemini 3.8 Flash, over cells valid for both on the same world and replicate. 95% percentile bootstrap, 2000 draws, seed 20260927, worlds resampled as clusters. Positive means GLM gave up more.

| arm | pairs (worlds) | GLM minus Gemini |
|---|---|---|
| low_effort | 62 (35) | -189.814 [-306.849, -95.69] |
| default_reasoning | 35 (23) | -90.507 [-147.618, -40.998] |

Default reasoning minus low effort, same worlds:

| client | pairs | difference |
|---|---|---|
| gemini38_flash | 70 | -269.36 [-402.988, -137.05] |
| glm53_flash | 32 | -226.386 [-335.432, -118.483] |

## Checked after the run

Not declared: computed after the run, on 2026-09-26, to check the design; not declared in the frozen plan. The split divides each valid episode's cost over the best attainable (at the integrator's true type) into the item it signed, the price it paid over that item's last-round price, walking or breaking off when a deal was better, and refused counters; it does not divide decision regret, which is scored on the client's information.

| arm / client | item | price over last-round price | walking or break-off | refused counters |
|---|---|---|---|---|
| default_reasoning/gemini38_flash | 32.368 | 178.932 | 18.339 | 8.681 |
| default_reasoning/glm53_flash | 0.0 | 0.287 | 63.15 | 21.429 |
| low_effort/gemini38_flash | 175.643 | 225.93 | 81.894 | 15.357 |
| low_effort/glm53_flash | 97.996 | 182.398 | 29.022 | 11.719 |
| scripted_controls/scripted_accept_the_first_item | 364.152 | 400.0 | 0.0 | 0.0 |
| scripted_controls/scripted_cheapest_all_in_price | 352.339 | 433.6 | 0.0 | 0.0 |
| scripted_controls/scripted_haggle_the_base_item | 278.893 | 0.0 | 59.17 | 47.222 |
| scripted_controls/scripted_reference | 1.033 | 39.59 | 0.0 | 12.5 |
| scripted_controls/scripted_walk_to_turnkey | 0.0 | 0.0 | 622.464 | 0.0 |

DC-D-26 (prices shown rounded, signed unrounded): 0 of 197 model counters in valid episodes were refused within $50 below the price.

Claim: descriptive: no winner, no ranking, no causal effect; the contrasts are reported without a multiplicity correction.

The reference graded zero regret on every cell: True.

## Accounting

454 of 468 planned cells executed, 14 sealed as typed exclusions, 0 not attempted; 421 valid episodes. Replay verified: True. Cost $5.11 (lower_bound): every answered provider call of every cell, read from the sealed event logs at the declared per-token prices; 15 call(s) ended with the outcome unknown (a dropped connection) and may have been billed, so the total is a floor.

Plan `43f89f8ecb46`.
