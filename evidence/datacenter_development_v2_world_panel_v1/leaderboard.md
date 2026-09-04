# datacenter_development_v2_world_panel_v1

Claim status: `twenty_four_world_controlled_developer_paired_panel_exploratory`. Worlds (clusters): 24. Cells: 142 of 144 completed. Reported cost: $0.3098 (lower_bound).

Ranking basis: mean developer equity NPV over admitted stacks and declared walk-aways; no-agreement episodes (walk, reject, rounds exhausted) score the declared outside option; excluded cells (constraint, contract, temporal, or invalid-action failures) are admission failures reported separately, not low scores.

| Rank | Model | Mean dev NPV ($) | Delta vs scripted ($) | Admitted | No deal | Excluded | Failures | Calls | In tok | Out tok | Cost ($) | Mean s |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | gptoss120b_coreweave | -325 | -7,129 | 0% | 25% | 75% | 0 | 743 | 810135 | 134251 | 0.0467 | 34.9 |

Unranked (incomplete panel or unverified route): glm53_parasail, qwen3_235b_google

## Admission by stratum

| Model | covenant_cliff | delayed_revenue | liability_transfer | restrictive_draws | revenue_without_bankability | verbal_written_divergence |
|---|---:|---:|---:|---:|---:|---:|
| glm53_parasail | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 |
| gptoss120b_coreweave | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 |
| qwen3_235b_google | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 |

## Paired differences (world-clustered bootstrap, 95% interval)

| Treatment | Control | Admission rate diff | Dev NPV diff ($) | Worlds |
|---|---|---:|---:|---:|
| glm53_parasail | gptoss120b_coreweave | +0.00 [+0.00, +0.00] | +0 [+0, +0] | 1 |
| glm53_parasail | qwen3_235b_google | +0.00 [+0.00, +0.00] | n/a | 0 |
| gptoss120b_coreweave | qwen3_235b_google | +0.00 [+0.00, +0.00] | n/a | 0 |

No winner claim, inferential model ranking, or causal condition effect is licensed by this artifact.
