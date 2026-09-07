# datacenter_development_v2_world_panel_v1

Claim status: `twenty_four_world_controlled_developer_paired_panel_exploratory`. Worlds (clusters): 24. Cells: 71 of 96 completed. Reported cost: $1.9820 (lower_bound).

Ranking basis: mean developer equity NPV over admitted stacks and declared walk-aways; no-agreement episodes (walk, reject, rounds exhausted) score the declared outside option; excluded cells (constraint, contract, temporal, or invalid-action failures) are admission failures reported separately, not low scores.

| Rank | Model | Mean dev NPV ($) | Delta vs scripted ($) | Admitted | No deal | Excluded | Failures | Calls | In tok | Out tok | Cost ($) | Mean s |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|

Unranked (incomplete panel or unverified route): gemini38_flash_aistudio, glm53_parasail, gptoss120b_coreweave, qwen3_235b_google

## Admission by stratum

| Model | covenant_cliff | delayed_revenue | liability_transfer | restrictive_draws | revenue_without_bankability | verbal_written_divergence |
|---|---:|---:|---:|---:|---:|---:|
| gemini38_flash_aistudio | 0/4 | 0/4 | 0/4 | 0/4 | 2/4 | 0/4 |
| glm53_parasail | 0/4 | 0/4 | 0/4 | 0/4 | 1/4 | 0/4 |
| gptoss120b_coreweave | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |
| qwen3_235b_google | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |

## Paired differences (world-clustered bootstrap, 95% interval)

| Treatment | Control | Admission rate diff | Dev NPV diff ($) | Worlds |
|---|---|---:|---:|---:|
| gemini38_flash_aistudio | glm53_parasail | +0.04 [+0.00, +0.12] | -163,082 [-489,247, +0] | 3 |
| gemini38_flash_aistudio | gptoss120b_coreweave | +0.08 [+0.00, +0.21] | +183,885,526 [+0, +551,656,577] | 3 |
| gemini38_flash_aistudio | qwen3_235b_google | +0.08 [+0.00, +0.21] | +551,656,577 [+551,656,577, +551,656,577] | 1 |
| glm53_parasail | gptoss120b_coreweave | +0.04 [+0.00, +0.12] | +0 [+0, +0] | 6 |
| glm53_parasail | qwen3_235b_google | +0.04 [+0.00, +0.12] | +0 [+0, +0] | 1 |
| gptoss120b_coreweave | qwen3_235b_google | +0.00 [+0.00, +0.00] | +0 [+0, +0] | 2 |

No winner claim, inferential model ranking, or causal condition effect is licensed by this artifact.
