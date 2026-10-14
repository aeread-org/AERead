# housing_lemons_price_confirmatory_v14

Confirmatory panel of the Housing lemons price case with one deciding tenant and outside demand: three models on the same 260-world pack and 40-world holdout, both landlord arms, one replicate. The rules are in the sealed tenant prompt and the reply history in the sealed observation (notice v4). The analysis below is the one declared in the contracts before any v14 cell ran.

Primary measure: seat 0's net at the reply-conditioned odds, mean of the two arms, per world; 95% Student-t over worlds; Holm over the three model pairs.

| Model | Completed cells | Primary, main pack | Minus reachable reference | Realized share of reference | Holdout primary | Cost |
|---|---|---|---|---|---|---|
| `housing_lemons_price_confirmatory_v14_glm53_flash_nextbit` | 600 of 600 | +137 [+111, +162] | -155 [-177, -134] | 45% | +73 [+5, +140] | $0.41 |
| `housing_lemons_price_confirmatory_v14_gpt6_luna` | 600 of 600 | +130 [+104, +156] | -162 [-181, -142] | 47% | +113 [+46, +180] | $0.63 |
| `housing_lemons_price_confirmatory_v14_gemini38_flash` | 564 of 600 | +211 [+188, +233] | -81 [-97, -65] | 72% | +188 [+120, +255] | $6.40 |

| Pair | Main pack | Holm p | Holdout |
|---|---|---|---|
| `housing_lemons_price_confirmatory_v14_glm53_flash_nextbit - housing_lemons_price_confirmatory_v14_gpt6_luna` | +7 [-16, +29] | 0.562 | -40 [-106, +26] |
| `housing_lemons_price_confirmatory_v14_glm53_flash_nextbit - housing_lemons_price_confirmatory_v14_gemini38_flash` | -70 [-92, -48] | 2.24e-09 | -106 [-168, -44] |
| `housing_lemons_price_confirmatory_v14_gpt6_luna - housing_lemons_price_confirmatory_v14_gemini38_flash` | -80 [-99, -62] | 1.57e-15 | -55 [-98, -12] |

Files: `tables/cells.jsonl` (every planned cell, with typed missingness), `reports/analysis.json`, `reports/contracts.json`, `reports/pack.json`. `publication_manifest.json` digests every file and binds the bundle to its source receipts.

No kernel trajectory grain: for 1,800 cells it is 145 MB, 22 times the largest grain in `evidence/`, because every outside-demand seat and landlord action is a row (85% of rows; seat 0 is 12%). The sealed attempt directories it would be built from stay in the run roots, bound here by receipt digest; `aeread publish-trajectories` adds it to a copy of this bundle when they are at hand.
