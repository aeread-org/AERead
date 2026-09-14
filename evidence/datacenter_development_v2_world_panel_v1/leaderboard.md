# datacenter_development_v2_world_panel_v1

Claim status: `twenty_four_world_controlled_developer_paired_panel_exploratory`. Worlds (clusters): 24. Cells: 157 of 192 completed. Reported cost: $4.5797 (lower_bound).

Ranking basis: mean developer equity NPV over admitted stacks and declared walk-aways; no-agreement episodes (walk, reject, rounds exhausted) score the declared outside option; excluded cells (constraint, contract, temporal, or invalid-action failures) are admission failures reported separately, not low scores.

Every completed episode is scored, so the mean is not an average over whichever cells a route happened to finish well.

| Rank | Model | Mean dev NPV ($) | Delta vs scripted ($) | Admitted | No deal | Excluded | Failures | Calls | In tok | Out tok | Cost ($) | Mean s |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|

Unranked (incomplete panel or unverified route): gemini38_flash_aistudio, glm53_parasail, gptoss120b_coreweave, qwen3_235b_google

## Admission by stratum

| Model | covenant_cliff | delayed_revenue | liability_transfer | restrictive_draws | revenue_without_bankability | verbal_written_divergence |
|---|---:|---:|---:|---:|---:|---:|
| gemini38_flash_aistudio | 3/8 | 2/8 | 1/8 | 1/8 | 2/8 | 0/8 |
| glm53_parasail | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 |
| gptoss120b_coreweave | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 |
| qwen3_235b_google | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 |

## Paired differences (world-clustered bootstrap, 95% interval)

| Treatment | Control | Admission rate diff | Dev NPV diff ($) | Worlds |
|---|---|---:|---:|---:|
| gemini38_flash_aistudio | glm53_parasail | +0.19 [+0.10, +0.29] | n/a | 0 |
| gemini38_flash_aistudio | gptoss120b_coreweave | +0.19 [+0.10, +0.29] | n/a | 0 |
| gemini38_flash_aistudio | qwen3_235b_google | +0.19 [+0.10, +0.29] | n/a | 0 |
| glm53_parasail | gptoss120b_coreweave | +0.00 [+0.00, +0.00] | n/a | 0 |
| glm53_parasail | qwen3_235b_google | +0.00 [+0.00, +0.00] | n/a | 0 |
| gptoss120b_coreweave | qwen3_235b_google | +0.00 [+0.00, +0.00] | n/a | 0 |

No winner claim, inferential model ranking, or causal condition effect is licensed by this artifact.
