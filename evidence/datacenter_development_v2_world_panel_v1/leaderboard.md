# datacenter_development_v2_world_panel_v1

Claim status: `twenty_four_world_controlled_developer_paired_panel_exploratory`. Worlds (clusters): 24. Cells: 67 of 96 completed. Reported cost: $1.9000 (lower_bound).

Ranking basis: mean developer equity NPV over admitted stacks and declared walk-aways; no-agreement episodes (walk, reject, rounds exhausted) score the declared outside option; excluded cells (constraint, contract, temporal, or invalid-action failures) are admission failures reported separately, not low scores.

| Rank | Model | Mean dev NPV ($) | Delta vs scripted ($) | Admitted | No deal | Excluded | Failures | Calls | In tok | Out tok | Cost ($) | Mean s |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | gemini38_flash_aistudio | 412,598,290 | -148,494,358 | 71% | 17% | 12% | 0 | 616 | 1655771 | 152286 | 1.7948 | 32.9 |
| 2 | gptoss120b_coreweave | -10,666,667 | -549,587,708 | 0% | 25% | 75% | 0 | 379 | 607349 | 119046 | 0.0381 | 51.6 |

Unranked (incomplete panel or unverified route): glm53_parasail, qwen3_235b_google

## Admission by stratum

| Model | covenant_cliff | delayed_revenue | liability_transfer | restrictive_draws | revenue_without_bankability | verbal_written_divergence |
|---|---:|---:|---:|---:|---:|---:|
| gemini38_flash_aistudio | 4/4 | 3/4 | 3/4 | 4/4 | 3/4 | 0/4 |
| glm53_parasail | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |
| gptoss120b_coreweave | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |
| qwen3_235b_google | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |

## Paired differences (world-clustered bootstrap, 95% interval)

| Treatment | Control | Admission rate diff | Dev NPV diff ($) | Worlds |
|---|---|---:|---:|---:|
| gemini38_flash_aistudio | glm53_parasail | +0.71 [+0.54, +0.88] | +407,301,482 [+124,449,284, +614,462,422] | 4 |
| gemini38_flash_aistudio | gptoss120b_coreweave | +0.71 [+0.54, +0.88] | +398,187,407 [+224,167,589, +544,188,501] | 6 |
| gemini38_flash_aistudio | qwen3_235b_google | +0.71 [+0.54, +0.88] | +430,230,955 [+264,628,206, +564,070,303] | 7 |
| glm53_parasail | gptoss120b_coreweave | +0.00 [+0.00, +0.00] | +0 [+0, +0] | 2 |
| glm53_parasail | qwen3_235b_google | +0.00 [+0.00, +0.00] | +0 [+0, +0] | 3 |
| gptoss120b_coreweave | qwen3_235b_google | +0.00 [+0.00, +0.00] | +0 [+0, +0] | 3 |

No winner claim, inferential model ranking, or causal condition effect is licensed by this artifact.
