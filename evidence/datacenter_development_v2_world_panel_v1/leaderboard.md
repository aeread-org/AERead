# datacenter_development_v2_world_panel_v1

Claim status: `twenty_four_world_controlled_developer_paired_panel_exploratory`. Worlds (clusters): 24. Cells: 86 of 96 completed. Reported cost: $1.4655 (lower_bound).

Ranking basis: mean developer equity NPV over admitted stacks and declared walk-aways; no-agreement episodes (walk, reject, rounds exhausted) score the declared outside option; excluded cells (constraint, contract, temporal, or invalid-action failures) are admission failures reported separately, not low scores.

| Rank | Model | Mean dev NPV ($) | Delta vs scripted ($) | Admitted | No deal | Excluded | Failures | Calls | In tok | Out tok | Cost ($) | Mean s |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | gemini38_flash_aistudio | 6,426 | -1,028 | 54% | 0% | 46% | 0 | 626 | 1156925 | 113673 | 1.2810 | 30.2 |
| 2 | qwen3_235b_google | -338 | -7,895 | 0% | 67% | 33% | 0 | 339 | 357576 | 43785 | 0.1160 | 29.3 |

Unranked (incomplete panel or unverified route): glm53_parasail, gptoss120b_coreweave

## Admission by stratum

| Model | covenant_cliff | delayed_revenue | liability_transfer | restrictive_draws | revenue_without_bankability | verbal_written_divergence |
|---|---:|---:|---:|---:|---:|---:|
| gemini38_flash_aistudio | 1/4 | 3/4 | 4/4 | 1/4 | 4/4 | 0/4 |
| glm53_parasail | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |
| gptoss120b_coreweave | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |
| qwen3_235b_google | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |

## Paired differences (world-clustered bootstrap, 95% interval)

| Treatment | Control | Admission rate diff | Dev NPV diff ($) | Worlds |
|---|---|---:|---:|---:|
| gemini38_flash_aistudio | glm53_parasail | +0.54 [+0.33, +0.75] | +6,493 [+5,946, +7,044] | 7 |
| gemini38_flash_aistudio | gptoss120b_coreweave | +0.54 [+0.33, +0.75] | +6,384 [+5,490, +7,340] | 3 |
| gemini38_flash_aistudio | qwen3_235b_google | +0.54 [+0.33, +0.75] | +6,606 [+5,952, +7,195] | 9 |
| glm53_parasail | gptoss120b_coreweave | +0.00 [+0.00, +0.00] | +0 [+0, +0] | 2 |
| glm53_parasail | qwen3_235b_google | +0.00 [+0.00, +0.00] | +0 [+0, +0] | 12 |
| gptoss120b_coreweave | qwen3_235b_google | +0.00 [+0.00, +0.00] | +0 [+0, +0] | 2 |

No winner claim, inferential model ranking, or causal condition effect is licensed by this artifact.
