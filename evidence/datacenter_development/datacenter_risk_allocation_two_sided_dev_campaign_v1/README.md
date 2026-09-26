# datacenter_risk_allocation_two_sided_dev_campaign_v1

The two-sided integrator-client risk-allocation case (`docs/families/datacenter/risk_allocation_case.md`, section two-sided): both seats played, on the 32 worlds of the one-sided eval pack, sealed, verified and replayed through the shared runner. Arm `low_effort`; two replicates per model pairing; two scripted pairings as controls in the same run. It does not rank models.

Joint value lost ($ thousands) is the surplus the best outcome for both parties' true private costs makes available, less the surplus the pair realised, round costs included; zero is the best any pair could do. It needs no model of either player.

| pairing (client / integrator) | valid | joint value lost [95% CI] | allocation / no deal / delay | signed (efficient) | IR violations client / integrator | median client share |
|---|---|---|---|---|---|---|
| gemini_client_gemini_integrator | 64/64 | 441.342 [251.654, 697.651] | 59.974 / 305.196 / 76.172 | 45 (3) | 7 / 14 | 0.909 |
| gemini_client_glm_integrator | 63/64 | 538.307 [368.895, 720.68] | 13.852 / 435.963 / 88.492 | 23 (1) | 6 / 1 | 0.504 |
| glm_client_gemini_integrator | 61/64 | 341.815 [191.263, 536.779] | 36.832 / 234.901 / 70.082 | 38 (3) | 8 / 2 | 0.55 |
| glm_client_glm_integrator | 56/64 | 440.578 [278.586, 650.465] | 41.563 / 326.247 / 72.768 | 30 (6) | 11 / 4 | 0.407 |
| oracle_client_oracle_integrator | 32/32 | 0.0 [0.0, 0.0] | 0.0 / 0.0 / 0.0 | 26 (26) | 0 / 0 | 0.5 |
| rule_client_rule_integrator | 32/32 | 306.748 [214.206, 409.275] | 174.033 / 80.371 / 52.344 | 18 (5) | 0 / 0 | 0.496 |

## Declared seat contrasts

swapping one seat's model with the other seat's model held fixed, paired on world and replicate (GLM minus Gemini): client seat against a Gemini integrator and against a GLM integrator; integrator seat against a Gemini client and against a GLM client; each on joint value lost and on the swapped seat's own surplus. 95% percentile bootstrap, 2000 draws, seed 20260926, worlds resampled as clusters (a twin with its base world). Negative joint value lost favours GLM in the swapped seat.

| contrast | pairs (worlds) | joint value lost | swapped seat's own surplus |
|---|---|---|---|
| client seat GLM minus Gemini, integrator gemini | 61 (24) | -88.007 [-193.93, -7.355] | -35.387 [-108.215, 37.084] |
| client seat GLM minus Gemini, integrator glm | 55 (23) | -89.509 [-173.685, -15.425] | 13.984 [-27.341, 53.301] |
| integrator seat GLM minus Gemini, client gemini | 63 (24) | 93.955 [-71.762, 249.439] | 48.799 [-2.718, 106.104] |
| integrator seat GLM minus Gemini, client glm | 55 (23) | 103.968 [-26.545, 234.367] | -13.673 [-82.199, 67.11] |

Claim: descriptive: no winner, no ranking, no causal effect; the eight contrasts are reported without a multiplicity correction.

The oracle pair lost zero on every world: True.

## Accounting

318 of 320 planned cells executed, 2 sealed as typed exclusions, 0 not attempted; 308 valid episodes. Replay verified: True. Cost $1.40 (lower_bound): every answered provider call of every cell, read from the sealed event logs at the declared per-token prices; 3 call(s) ended with the outcome unknown (a dropped connection) and may have been billed, so the total is a floor.

Plan `f50daf8a9fd5`.
