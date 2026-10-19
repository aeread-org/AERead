# datacenter_development_v2_world_panel_confirmatory_v1

Claim status: `single_route_gemini_confirmatory_admission_and_reference_delta_on_held_out_worlds`. Worlds (clusters): 24. Cells: 72 of 72 completed. Reported cost: $5.3371 (exact).

Ranking basis: mean developer equity NPV over every completed episode. An admitted stack scores what it earns; a no-agreement episode and an executed stack that cannot stand up both score the declared outside option, because neither delivers a project and the developer could have walked. Operational failures are typed missingness and are reported separately. Scoring only the cells a route succeeded on would make the headline an average over a self-selected subset.

Every completed episode is scored, so the mean is not an average over whichever cells a route happened to finish well.

| Rank | Model | Mean dev NPV ($) | Delta vs scripted ($) | Admitted | No deal | Excluded | Failures | Calls | In tok | Out tok | Cost ($) | Mean s |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | gemini38_flash_aistudio | 127,169,308 | -426,892,038 | 25% | 0% | 75% | 0 | 1933 | 4809280 | 475760 | 5.3371 | 36.0 |

## Admission by stratum

| Model | covenant_cliff | delayed_revenue | liability_transfer | restrictive_draws | revenue_without_bankability | verbal_written_divergence |
|---|---:|---:|---:|---:|---:|---:|
| gemini38_flash_aistudio | 3/12 | 6/12 | 3/12 | 5/12 | 1/12 | 0/12 |

## Paired differences (world-clustered bootstrap, 95% interval)

| Treatment | Control | Admission rate diff | Dev NPV diff ($) | Worlds |
|---|---|---:|---:|---:|

No winner claim, inferential model ranking, or causal condition effect is licensed by this artifact.
