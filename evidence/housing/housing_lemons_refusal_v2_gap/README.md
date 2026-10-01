# housing_lemons_refusal_v2_gap

Why `housing_lemons_refusal_v2_gemini38_flash` (gemini-3.8-flash) and `housing_lemons_refusal_v2_glm53_flash` (glm-5.3-flash) differ on the same 24 lemons worlds. Derived from the two published bundles and the worlds regenerated from their seeds by `python -m aeread_families.housing.lemons_gap`; `--check` regenerates these bytes. Descriptive: no winner, no ranking.

Tenant net payoff per market splits exactly into the parts below (largest per-cell residual 4.5e-13).

| part | gemini-3.8-flash | glm-5.3-flash | gemini-3.8-flash minus glm-5.3-flash (95% world bootstrap) |
|---|---|---|---|
| tenant net payoff (realized) | 327.8 | 134.0 | 193.9 (65.2 to 322.3) |
| inspected, then signed | 475.3 | 492.4 | -17.1 (-145.8 to 102.4) |
| signed blind, worth it in expectation | 53.0 | 43.1 | 9.9 (-28.9 to 51.0) |
| signed blind, not worth it in expectation | 0.0 | -17.5 | 17.5 (0.0 to 46.0) |
| which blind leases turned out lemons (luck) | 62.5 | -90.3 | 152.8 (62.5 to 243.1) |
| inspection fees | -263.0 | -293.8 | 30.7 (13.0 to 48.4) |

Decision classes, judged at what the tenant knew (counts over all cells; amounts are expected dollars per market, diagnostic and overlapping, not parts of the sum):

| class | gemini-3.8-flash count | glm-5.3-flash count | gemini-3.8-flash per market | glm-5.3-flash per market |
|---|---|---|---|---|
| `L1_blind_sign_below_expected_value`: signed an uninspected hold worth less than its rent in expectation | 0 | 4 | 0.0 | 17.5 |
| `L2_skipped_worthwhile_inspection`: signed blind after passing on that round's inspection, when inspecting the listing first was worth the fee | 0 | 6 | 0.0 | 32.0 |
| `L3_declined_hold_worth_more`: walked from or let expire a hold worth more than its rent in expectation | 0 | 16 | 0.0 | 33.3 |
| `L4_signed_above_ask`: signed at a rent above the posted ask | 0 | 31 | 0.0 | 61.6 |
| `L5_good_blind_bet_turned_lemon`: a blind signing worth it in expectation that turned out a lemon (luck, not a failure) | 2 | 8 | 27.8 | 107.6 |
| `A1_tenant_signed_above_own_value`: a signed lease left the tenant below zero surplus (as in the Housing taxonomy) | 2 | 11 | 23.5 | 124.1 |

Against the scripted inspect-then-sign reference (replay reproduces 24 of 24 published payoffs), per market:

| part | gemini-3.8-flash minus reference | glm-5.3-flash minus reference |
|---|---|---|
| tenant net payoff (realized) | -26.3 (-94.5 to 22.2) | -220.2 (-339.6 to -103.5) |
| inspected, then signed | -139.2 (-237.3 to -53.1) | -122.2 (-186.7 to -54.6) |
| signed blind, worth it in expectation | 53.0 (25.1 to 85.4) | 43.1 (21.9 to 67.5) |
| signed blind, not worth it in expectation | 0.0 (0.0 to 0.0) | -17.5 (-46.0 to 0.0) |
| which blind leases turned out lemons (luck) | 62.5 (-27.8 to 152.8) | -90.3 (-173.6 to -13.9) |
| inspection fees | -2.6 (-10.9 to 6.8) | -33.3 (-52.1 to -14.6) |

| leases, per market | gemini-3.8-flash | glm-5.3-flash | reference |
|---|---|---|---|
| signed after inspecting | 1.44 | 1.77 | 1.83 |
| signed blind | 0.48 | 0.45 | 0.00 |
| surplus per inspected lease | 330.67 | 283.72 | 335.22 |
| rent minus ask | 0.00 | -45.65 | 1.00 |

Every instance, with the step that decided it, is in `reports/gap_decomposition.json`. `tables/contributions.jsonl` (1281 rows) carries every part down to the decision and step that made it; per cell, a part's rows sum to that cell's part (largest difference 0).
