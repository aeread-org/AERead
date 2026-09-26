# datacenter_risk_allocation_contracts_dev_campaign_v1

The full-terms menu of the integrator-client risk-allocation case (`docs/families/datacenter/risk_allocation_case.md`): a scripted integrator posts one of three playbooks with every combination of its negotiable terms on the menu (warranty, delay-damages rate, liability cap, readiness, consequential loss, deposit size, escrow, burn-in; 64 to 360 contracts), prices them by a policy the client is not told, and lists the base and each single change; the model, as client, accepts a standing offer, counters or asks the price of any contract, or walks. Sealed, verified and replayed through the shared runner. It does not rank models.

Decision regret ($ thousands) is what each move gave up against a client who knows how integrators in this market choose and price their playbooks, summed over the episode. A client that signs the right contract after two refusals without knowing the policy keeps a client that signs the right contract after two refusals without knowing the pricing policy carries 40 to 65 thousand of regret per deal world on this pack (simulated before the freeze); regret below that needs the policy.

| arm / client | valid | decision regret [95% CI] | zero regret | signed a best contract | walked to the best outside option | cost over best attainable |
|---|---|---|---|---|---|---|
| default_reasoning/gemini38_flash | 0/116 | None | 0 | 0 of 0 | 0 of 0 | None |
| low_effort/gemini38_flash | 116/116 | 415.935 [360.706, 467.748] | 11 | 14 of 104 | 8 of 12 | 484.27 |
| low_effort/glm53_flash | 18/116 | 412.353 [332.078, 506.95] | 1 | 1 of 18 | 0 of 0 | 483.807 |
| scripted_controls/scripted_accept_the_base | 58/58 | 795.116 [734.444, 859.843] | 0 | 0 of 52 | 0 of 6 | 862.699 |
| scripted_controls/scripted_cheapest_listed_price | 58/58 | 827.164 [764.888, 885.848] | 0 | 0 of 52 | 0 of 6 | 894.747 |
| scripted_controls/scripted_every_protection | 58/58 | 383.718 [332.529, 434.658] | 4 | 1 of 52 | 0 of 6 | 465.094 |
| scripted_controls/scripted_haggle_the_base | 58/58 | 389.428 [321.41, 459.427] | 4 | 0 of 52 | 0 of 6 | 469.435 |
| scripted_controls/scripted_reference | 58/58 | 0.0 [0.0, 0.0] | 58 | 45 of 52 | 6 of 6 | 68.784 |
| scripted_controls/scripted_walk_to_turnkey | 58/58 | 398.717 [336.428, 463.367] | 6 | 0 of 52 | 6 of 6 | 466.3 |

## The declared contrast

at low effort, the mean paired difference in decision regret, GLM 5.3 Flash minus Gemini 3.8 Flash, over cells valid for both on the same world and replicate. 95% percentile bootstrap, 2000 draws, seed 20260928, worlds resampled as clusters. Positive means GLM gave up more.

| arm | pairs (worlds) | GLM minus Gemini |
|---|---|---|
| low_effort | 18 (15) | -15.053 [-207.576, 161.975] |

Default reasoning minus low effort, same worlds:

| client | pairs | difference |
|---|---|---|
| gemini38_flash | 0 | not seated |
| glm53_flash | 0 | not seated |

## Where the cost comes from

The declared split: each valid episode's contract signed (its cost to the client at the integrator's last-round price over the best contract's, or over the better outside option when walking is best), the price paid over that last-round price, walking or breaking off when a deal was better, and refused counters (declined requests included). As the plan defines them the four parts sum to the episode's cost over the best attainable at the integrator's true type, not to its decision regret, which is scored on the client's information; the plan's word 'regret' for the split is loose (DC-J-04).

| arm / client | contract signed | price over last-round price | walking or break-off | refused counters | declined requests |
|---|---|---|---|---|---|
| default_reasoning/gemini38_flash | None | None | None | None | None |
| low_effort/gemini38_flash | 133.16 | 291.047 | 50.365 | 9.698 | 0.0 |
| low_effort/glm53_flash | 107.376 | 315.561 | 56.703 | 4.167 | 0.0 |
| scripted_controls/scripted_accept_the_base | 462.699 | 400.0 | 0.0 | 0.0 | 0.0 |
| scripted_controls/scripted_cheapest_listed_price | 462.885 | 431.862 | 0.0 | 0.0 | 0.0 |
| scripted_controls/scripted_every_protection | 129.038 | 248.455 | 62.601 | 25.0 | 0.0 |
| scripted_controls/scripted_haggle_the_base | 326.94 | 0.0 | 96.374 | 46.121 | 0.0 |
| scripted_controls/scripted_reference | 0.958 | 25.657 | 22.342 | 19.828 | 0.0 |
| scripted_controls/scripted_walk_to_turnkey | 0.0 | 0.0 | 466.3 | 0.0 | 0.0 |

Terms that differ from the nearest best contract, over signed deals in worlds where a contract is best:

| arm / client | signed deals | warranty | damages | liability_cap | readiness | consequential | deposit | escrow | burn_in |
|---|---|---|---|---|---|---|---|---|---|
| default_reasoning/gemini38_flash | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| low_effort/gemini38_flash | 89 | 19 | 37 | 23 | 22 | 19 | 11 | 3 | 20 |
| low_effort/glm53_flash | 15 | 2 | 7 | 5 | 6 | 5 | 3 | 2 | 1 |
| scripted_controls/scripted_accept_the_base | 52 | 32 | 30 | 20 | 33 | 38 | 18 | 2 | 13 |
| scripted_controls/scripted_cheapest_listed_price | 52 | 32 | 30 | 28 | 33 | 38 | 10 | 2 | 13 |
| scripted_controls/scripted_every_protection | 44 | 0 | 10 | 0 | 1 | 14 | 25 | 11 | 31 |
| scripted_controls/scripted_haggle_the_base | 39 | 24 | 21 | 16 | 24 | 27 | 14 | 1 | 11 |
| scripted_controls/scripted_reference | 48 | 0 | 0 | 0 | 0 | 2 | 1 | 0 | 1 |
| scripted_controls/scripted_walk_to_turnkey | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Missing cells by cause: default_reasoning/gemini38_flash: 116 provider_rejected:http_402_insufficient_credits; low_effort/glm53_flash: 98 provider_rejected:http_402_insufficient_credits.

Not seated: default_reasoning/glm53_flash (DC-O-14).

Claim: descriptive: no winner, no ranking, no causal effect; the contrasts are reported without a multiplicity correction.

The reference graded zero regret on every cell: True.

## Accounting

482 of 696 planned cells executed, 214 sealed as typed exclusions, 0 not attempted; 482 valid episodes. Replay verified: True. Cost $0.42 (exact): every answered provider call of every cell, read from the sealed event logs at the declared per-token prices.

Plan `b93fcd7df256`.
