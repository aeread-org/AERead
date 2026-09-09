# datacenter_development_v2_world_panel_v1

Claim status: `twenty_four_world_controlled_developer_paired_panel_exploratory`. Worlds (clusters): 24. Cells: 155 of 192 completed. Reported cost: $4.4397 (lower_bound).

Ranking basis: mean developer equity NPV over admitted stacks and declared walk-aways; no-agreement episodes (walk, reject, rounds exhausted) score the declared outside option; excluded cells (constraint, contract, temporal, or invalid-action failures) are admission failures reported separately, not low scores.

| Rank | Model | Mean dev NPV ($) | Delta vs scripted ($) | Admitted | No deal | Excluded | Failures | Calls | In tok | Out tok | Cost ($) | Mean s |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | gemini38_flash_aistudio | 437,939,449 | -112,952,576 | 12% | 2% | 85% | 0 | 1314 | 3585433 | 358646 | 3.9937 | 42.0 |
| 2 | glm53_parasail | -108,727 | -563,348,170 | 2% | 69% | 29% | 0 | 678 | 1095781 | 106184 | 0.2153 | 37.0 |

Unranked (incomplete panel or unverified route): gptoss120b_coreweave, qwen3_235b_google

## Admission by stratum

| Model | covenant_cliff | delayed_revenue | liability_transfer | restrictive_draws | revenue_without_bankability | verbal_written_divergence |
|---|---:|---:|---:|---:|---:|---:|
| gemini38_flash_aistudio | 0/8 | 0/8 | 1/8 | 2/8 | 3/8 | 0/8 |
| glm53_parasail | 1/8 | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 |
| gptoss120b_coreweave | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 |
| qwen3_235b_google | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 |

## Paired differences (world-clustered bootstrap, 95% interval)

| Treatment | Control | Admission rate diff | Dev NPV diff ($) | Worlds |
|---|---|---:|---:|---:|
| gemini38_flash_aistudio | glm53_parasail | +0.10 [+0.00, +0.21] | n/a | 0 |
| gemini38_flash_aistudio | gptoss120b_coreweave | +0.12 [+0.04, +0.21] | n/a | 0 |
| gemini38_flash_aistudio | qwen3_235b_google | +0.12 [+0.04, +0.21] | n/a | 0 |
| glm53_parasail | gptoss120b_coreweave | +0.02 [+0.00, +0.06] | +0 [+0, +0] | 1 |
| glm53_parasail | qwen3_235b_google | +0.02 [+0.00, +0.06] | +91,825,824 [+0, +183,651,649] | 2 |
| gptoss120b_coreweave | qwen3_235b_google | +0.00 [+0.00, +0.00] | +0 [+0, +0] | 2 |

No winner claim, inferential model ranking, or causal condition effect is licensed by this artifact.
