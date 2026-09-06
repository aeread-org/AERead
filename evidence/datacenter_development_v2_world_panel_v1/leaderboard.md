# datacenter_development_v2_world_panel_v1

Claim status: `twenty_four_world_controlled_developer_paired_panel_exploratory`. Worlds (clusters): 24. Cells: 89 of 96 completed. Reported cost: $1.8892 (lower_bound).

Ranking basis: mean developer equity NPV over admitted stacks and declared walk-aways; no-agreement episodes (walk, reject, rounds exhausted) score the declared outside option; excluded cells (constraint, contract, temporal, or invalid-action failures) are admission failures reported separately, not low scores.

| Rank | Model | Mean dev NPV ($) | Delta vs scripted ($) | Admitted | No deal | Excluded | Failures | Calls | In tok | Out tok | Cost ($) | Mean s |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | gemini38_flash_aistudio | 210,333,796 | -366,156,419 | 17% | 25% | 58% | 0 | 555 | 1474488 | 152058 | 1.6593 | 32.2 |
| 2 | qwen3_235b_google | -10,166,667 | -559,551,898 | 0% | 25% | 75% | 0 | 146 | 179785 | 118969 | 0.1428 | 71.4 |

Unranked (incomplete panel or unverified route): glm53_parasail, gptoss120b_coreweave

## Admission by stratum

| Model | covenant_cliff | delayed_revenue | liability_transfer | restrictive_draws | revenue_without_bankability | verbal_written_divergence |
|---|---:|---:|---:|---:|---:|---:|
| gemini38_flash_aistudio | 1/4 | 0/4 | 1/4 | 1/4 | 1/4 | 0/4 |
| glm53_parasail | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |
| gptoss120b_coreweave | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |
| qwen3_235b_google | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |

## Paired differences (world-clustered bootstrap, 95% interval)

| Treatment | Control | Admission rate diff | Dev NPV diff ($) | Worlds |
|---|---|---:|---:|---:|
| gemini38_flash_aistudio | glm53_parasail | +0.17 [+0.04, +0.33] | +294,909,278 [+88,407,438, +513,385,654] | 6 |
| gemini38_flash_aistudio | gptoss120b_coreweave | +0.17 [+0.04, +0.33] | +315,191,137 [+90,959,884, +510,904,459] | 7 |
| gemini38_flash_aistudio | qwen3_235b_google | +0.17 [+0.04, +0.33] | +265,222,315 [+0, +530,444,631] | 2 |
| glm53_parasail | gptoss120b_coreweave | +0.00 [+0.00, +0.00] | +0 [+0, +0] | 10 |
| glm53_parasail | qwen3_235b_google | +0.00 [+0.00, +0.00] | +0 [+0, +0] | 4 |
| gptoss120b_coreweave | qwen3_235b_google | +0.00 [+0.00, +0.00] | +0 [+0, +0] | 3 |

No winner claim, inferential model ranking, or causal condition effect is licensed by this artifact.
