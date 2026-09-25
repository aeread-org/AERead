# datacenter_risk_allocation_dev_campaign_v1

The integrator-client risk-allocation case (`docs/families/datacenter/risk_allocation_case.md`) run through the
shared runner: every episode sealed, verified and replayed. A diagnostic dev campaign on a 16-world pack, one run per
cell, both seats of every world. It does not rank models.

Decision regret ($ thousands) is what each move gave up against the best play on the model's own information,
summed over the episode. Invalid episodes (malformed or illegal moves, replies cut off by the output limit) are
reported as missing, not scored.

| arm / route / seat | valid | mean regret | signed another package than its first | signed the efficient one | cost |
|---|---|---|---|---|---|
| one_price_default/gemini38_flash/client | 16/16 | 70.816 | 1 of 15 | 6 of 15 | $0.47 |
| one_price_default/gemini38_flash/integrator | 16/16 | 53.427 | 1 of 12 | 4 of 12 | $0.58 |
| one_price_default/glm53_flash/client | 13/16 | 71.971 | 5 of 9 | 6 of 9 | $0.45 |
| one_price_default/glm53_flash/integrator | 5/16 | 14.757 | 2 of 5 | 4 of 5 | $0.19 |
| one_price_low/gemini38_flash/client | 16/16 | 122.335 | 0 of 14 | 1 of 14 | $0.05 |
| one_price_low/gemini38_flash/integrator | 16/16 | 158.19 | 0 of 15 | 3 of 15 | $0.10 |
| one_price_low/glm53_flash/client | 16/16 | 164.213 | 4 of 12 | 1 of 12 | $0.04 |
| one_price_low/glm53_flash/integrator | 16/16 | 204.719 | 0 of 11 | 2 of 11 | $0.03 |
| two_prices_low/gemini38_flash/client | 16/16 | 125.686 | 6 of 13 | 4 of 13 | $0.05 |
| two_prices_low/gemini38_flash/integrator | 14/16 | 134.656 | 7 of 11 | 2 of 11 | $0.06 |
| two_prices_low/glm53_flash/client | 10/16 | 237.344 | 1 of 7 | 0 of 7 | $0.05 |
| two_prices_low/glm53_flash/integrator | 15/16 | 242.364 | 2 of 12 | 3 of 12 | $0.03 |

Analysis (`reports/summary.json`, key `analysis`):

- Run-to-run variance: unmeasured: one run per cell. The break-off draws are fixed per world, so a later replicate campaign would measure the model's own spread.
- Judges: none: decision regret is an exact computation, and every receipt was replayed to the same digest
- Intervals: 95% percentile bootstrap, 2000 draws, worlds resampled as clusters (a twin with its base world).

| arm / route / seat | valid | mean regret [95% CI] | median | strict pass (zero regret) |
|---|---|---|---|---|
| one_price_default/gemini38_flash/client | 16/16 | 70.816 [26.366, 138.289] | 34.8 | 4 |
| one_price_default/gemini38_flash/integrator | 16/16 | 53.427 [25.743, 92.811] | 24.05 | 5 |
| one_price_default/glm53_flash/client | 13/16 | 71.971 [11.018, 168.761] | 0.52 | 7 |
| one_price_default/glm53_flash/integrator | 5/16 | 14.757 [0.089, 43.968] | 0.1 | 4 |
| one_price_low/gemini38_flash/client | 16/16 | 122.335 [57.073, 221.341] | 64.35 | 1 |
| one_price_low/gemini38_flash/integrator | 16/16 | 158.19 [72.43, 286.96] | 93.75 | 2 |
| one_price_low/glm53_flash/client | 16/16 | 164.213 [98.806, 238.084] | 136.157067 | 1 |
| one_price_low/glm53_flash/integrator | 16/16 | 204.719 [156.393, 257.716] | 200.0 | 0 |
| two_prices_low/gemini38_flash/client | 16/16 | 125.686 [42.737, 235.528] | 30.7928 | 3 |
| two_prices_low/gemini38_flash/integrator | 14/16 | 134.656 [61.578, 246.754] | 101.14875 | 2 |
| two_prices_low/glm53_flash/client | 10/16 | 237.344 [124.441, 342.726] | 282.41 | 0 |
| two_prices_low/glm53_flash/integrator | 15/16 | 242.364 [197.616, 292.151] | 224.0 | 0 |

Paired against `one_price_low` on the same worlds (difference in decision regret, $ thousands; negative is better):

| arm / route / seat | worlds | mean difference [95% CI] |
|---|---|---|
| one_price_default/gemini38_flash/client | 16 | -51.52 [-140.845, -0.082] |
| one_price_default/gemini38_flash/integrator | 16 | -104.764 [-208.478, -33.088] |
| one_price_default/glm53_flash/client | 13 | -111.854 [-164.435, -51.81] |
| one_price_default/glm53_flash/integrator | 5 | -185.819 [-233.125, -136.472] |
| two_prices_low/gemini38_flash/client | 16 | 3.35 [-27.983, 39.742] |
| two_prices_low/gemini38_flash/integrator | 14 | -32.703 [-114.298, 31.508] |
| two_prices_low/glm53_flash/client | 10 | 55.551 [-18.238, 116.716] |
| two_prices_low/glm53_flash/integrator | 15 | 27.33 [-38.239, 89.031] |

Total cost $2.10. Plan `5381365db245`.
