# housing_lemons_refusal_v2_comparison

Paired comparison of `housing_lemons_refusal_v2_gemini38_flash` (left) and `housing_lemons_refusal_v2_glm53_flash` (right) on the same 24 lemons worlds, both with the pooled lemon landlord (HL-D-01) at temperature 1.0 (HL-D-02). Derived from the two published bundles by `python -m aeread_families.housing.lemons_comparison`; `--check` regenerates these bytes. Descriptive: no winner, no ranking.

`housing_lemons_refusal_v2_glm53_flash` is an incomplete pack published by the owner's decision; missing as typed missingness: `world_100021__rep_1`. That world's mean on that side uses the seeds it completed.

| endpoint | left | right | left minus right (95% world bootstrap) | worlds left higher / right higher |
|---|---|---|---|---|
| tenant net payoff (market total) | 327.83 | 133.95 | 193.88 (66.85 to 321.68) | 19 / 5 |
| the same, blind signings at expected value (luck removed) | 265.34 | 224.23 | 41.11 (-69.33 to 143.30) | 14 / 10 |
| within-case score | 0.223 | 0.079 | 0.143 (0.063 to 0.230) | 19 / 5 |
| abstention correctness | 1.000 | 0.927 | 0.073 (0.037 to 0.112) | 11 / 0 |
| cells signing an uninspected lemon | 0.042 | 0.229 | -0.188 (-0.333 to -0.062) | 1 / 8 |
| inspections per cell | 10.5 | 11.8 | -1.2 (-1.9 to -0.5) | 4 / 17 |

The second row takes the luck of the lemon draws out (HL-J-01): each lease a tenant signed without inspecting is counted at its expected value at that tenant's own lemon probability, as the environment recorded it, instead of the value it turned out to have. Most of the realized gap is those draws.

Scripted benchmarks on the same worlds (left / right): reference 354.16 / 354.16; sign anything -864.62 / -864.62; oracle 1493.92 / 1493.92.

Per-stratum slices and every world's means are in `reports/comparison.json`.
