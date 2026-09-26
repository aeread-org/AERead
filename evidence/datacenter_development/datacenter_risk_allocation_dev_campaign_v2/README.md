# datacenter_risk_allocation_dev_campaign_v2

The integrator-client risk-allocation case (`docs/families/datacenter/risk_allocation_case.md`) run through the
shared runner: every episode sealed, verified and replayed. Pack `risk_allocation_eval_v1`, 24 independent worlds (a twin counts with its base world), two replicates per model cell, scripted controls seated in the run. It declares one two-model contrast and does not rank models.

Decision regret ($ thousands) is what each move gave up against the best play on the model's own information,
summed over the episode. Invalid episodes (malformed or illegal moves, replies cut off by the output limit) are
reported as missing, not scored.

| arm / route / seat | valid | mean regret | signed another package than its first | signed the efficient one | cost |
|---|---|---|---|---|---|
| one_price_default/gemini38_flash/client | 64/64 | 44.679 | 3 of 54 | 15 of 54 | $1.78 |
| one_price_default/gemini38_flash/integrator | 64/64 | 59.567 | 6 of 48 | 29 of 48 | $2.57 |
| one_price_default/glm53_flash/client | 50/64 | 99.747 | 21 of 35 | 22 of 35 | $1.66 |
| one_price_default/glm53_flash/integrator | 47/64 | 27.639 | 21 of 36 | 26 of 36 | $2.11 |
| one_price_low/gemini38_flash/client | 64/64 | 95.145 | 1 of 56 | 7 of 56 | $0.18 |
| one_price_low/gemini38_flash/integrator | 64/64 | 173.434 | 0 of 51 | 15 of 51 | $0.30 |
| one_price_low/glm53_flash/client | 64/64 | 199.771 | 13 of 51 | 6 of 51 | $0.18 |
| one_price_low/glm53_flash/integrator | 64/64 | 257.017 | 4 of 49 | 16 of 49 | $0.17 |
| scripted_controls/scripted_defend_the_opening_terms/integrator | 32/32 | 337.445 | 0 of 29 | 4 of 29 | $0.00 |
| scripted_controls/scripted_haggle_price_only/client | 32/32 | 291.983 | 0 of 29 | 4 of 29 | $0.00 |
| scripted_controls/scripted_reference/client | 32/32 | 0.0 | 17 of 25 | 25 of 25 | $0.00 |
| scripted_controls/scripted_reference/integrator | 32/32 | 0.0 | 17 of 25 | 25 of 25 | $0.00 |
| scripted_controls/scripted_sign_the_prior_best_now/client | 32/32 | 283.503 | 0 of 32 | 15 of 32 | $0.00 |
| scripted_controls/scripted_sign_the_prior_best_now/integrator | 32/32 | 357.661 | 0 of 32 | 23 of 32 | $0.00 |

## The declared contrast

Per arm and seat, the mean paired difference in decision regret, GLM 5.3 Flash minus Gemini 3.8 Flash, over cells valid for both models on the same world and replicate (so the same request seed). 95% percentile bootstrap, 2000 draws, seed 20260925, worlds resampled as clusters (a twin with its base world). Reported per model and cause; a cell missing for either model drops out of that world's pair, never imputed. Negative means GLM gave up less.

| arm / seat | pairs (worlds) | GLM minus Gemini [95% CI] | GLM lower / higher / within $1k | missing, Gemini | missing, GLM |
|---|---|---|---|---|---|
| one_price_default/client | 50 (23) | 50.355 [7.645, 110.157] | 15 / 18 / 17 | none | empty_response 1, provider_rejected 2, timeout 10, truncated_reply 1 |
| one_price_default/integrator | 47 (22) | -26.883 [-70.377, 0.089] | 17 / 10 / 20 | none | provider_rejected 3, timeout 8, truncated_reply 6 |
| one_price_low/client | 64 (24) | 104.626 [50.263, 155.042] | 13 / 47 / 4 | none | none |
| one_price_low/integrator | 64 (24) | 83.583 [29.864, 129.449] | 13 / 45 / 6 | none | none |

Claim: descriptive: no winner, no ranking, no causal effect; the four contrasts are reported without a multiplicity correction.

## Run to run

| arm / route / seat | worlds with both replicates | mean gap between replicates | within-world SD | share of variance within worlds | same contract both times |
|---|---|---|---|---|---|
| one_price_default/gemini38_flash/client | 32 | 29.581 | 58.683 | 0.399 | 25 of 32 |
| one_price_default/gemini38_flash/integrator | 32 | 55.621 | 87.695 | 0.411 | 23 of 32 |
| one_price_default/glm53_flash/client | 22 | 83.477 | 144.666 | 0.34 | 15 of 22 |
| one_price_default/glm53_flash/integrator | 19 | 29.369 | 37.31 | 0.358 | 12 of 19 |
| one_price_low/gemini38_flash/client | 32 | 48.492 | 89.5 | 0.372 | 28 of 32 |
| one_price_low/gemini38_flash/integrator | 32 | 79.15 | 93.088 | 0.151 | 24 of 32 |
| one_price_low/glm53_flash/client | 32 | 128.686 | 135.429 | 0.541 | 11 of 32 |
| one_price_low/glm53_flash/integrator | 32 | 131.454 | 120.864 | 0.23 | 10 of 32 |

## Controls in the run

| policy / seat | valid | mean regret | max regret |
|---|---|---|---|
| defend_the_opening_terms/integrator | 32/32 | 337.445 | 1271.277783 |
| haggle_price_only/client | 32/32 | 291.983 | 935.78565 |
| reference/client | 32/32 | 0.0 | 0.0 |
| reference/integrator | 32/32 | 0.0 | 0.0 |
| sign_the_prior_best_now/client | 32/32 | 283.503 | 732.02 |
| sign_the_prior_best_now/integrator | 32/32 | 357.661 | 886.46 |

The reference graded zero regret on every cell: True.

## Distributions

- Run-to-run variance: per model group below (`run_to_run`): two replicates per world under different request seeds
- Judges: none: decision regret is an exact computation, and every receipt was replayed to the same digest
- Intervals: 95% percentile bootstrap, 2000 draws, worlds resampled as clusters (a twin with its base world).

| arm / route / seat | valid | mean regret [95% CI] | median | strict pass (zero regret) |
|---|---|---|---|---|
| one_price_default/gemini38_flash/client | 64/64 | 44.679 [24.637, 73.65] | 14.16 | 20 |
| one_price_default/gemini38_flash/integrator | 64/64 | 59.567 [27.272, 103.704] | 0.75 | 34 |
| one_price_default/glm53_flash/client | 50/64 | 99.747 [34.712, 186.229] | 2.36 | 22 |
| one_price_default/glm53_flash/integrator | 47/64 | 27.639 [11.305, 49.318] | 0.06 | 30 |
| one_price_low/gemini38_flash/client | 64/64 | 95.145 [58.673, 141.992] | 52.2 | 7 |
| one_price_low/gemini38_flash/integrator | 64/64 | 173.434 [101.872, 262.19] | 66.85 | 15 |
| one_price_low/glm53_flash/client | 64/64 | 199.771 [156.196, 246.963] | 203.48 | 8 |
| one_price_low/glm53_flash/integrator | 64/64 | 257.017 [183.559, 348.121] | 208.28 | 6 |
| scripted_controls/scripted_defend_the_opening_terms/integrator | 32/32 | 337.445 [241.572, 462.091] | 270.9 | 5 |
| scripted_controls/scripted_haggle_price_only/client | 32/32 | 291.983 [216.003, 386.988] | 223.080806 | 4 |
| scripted_controls/scripted_reference/client | 32/32 | 0.0 [0.0, 0.0] | 0.0 | 32 |
| scripted_controls/scripted_reference/integrator | 32/32 | 0.0 [0.0, 0.0] | 0.0 | 32 |
| scripted_controls/scripted_sign_the_prior_best_now/client | 32/32 | 283.503 [219.923, 351.704] | 289.0771 | 3 |
| scripted_controls/scripted_sign_the_prior_best_now/integrator | 32/32 | 357.661 [282.002, 430.229] | 338.7198 | 3 |

Paired against `one_price_low` on the same worlds (difference in decision regret, $ thousands; negative is better):

| arm / route / seat | pairs | mean difference [95% CI] |
|---|---|---|
| one_price_default/gemini38_flash/client | 64 | -50.467 [-87.453, -23.395] |
| one_price_default/gemini38_flash/integrator | 64 | -113.867 [-179.976, -59.391] |
| one_price_default/glm53_flash/client | 50 | -87.302 [-148.056, -11.181] |
| one_price_default/glm53_flash/integrator | 47 | -220.88 [-293.173, -160.22] |

## Accounting

680 of 704 planned cells executed, 24 sealed as typed exclusions, 0 not attempted; 673 valid episodes. Replay verified: True. Cost $8.94 (lower_bound): every answered provider call of every cell, read from the sealed event logs at the declared per-token prices; 94 call(s) ended with the outcome unknown (a dropped connection) and may have been billed, so the total is a floor.

Plan `8e94fdf7893b`.
