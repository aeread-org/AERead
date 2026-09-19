# Unified regret campaign: offline admission

Status: six worlds admitted offline. Live pilot and confirmation are pending. This is not a model result.

All 96 candidates were screened at 12 environment seeds using two public-observation policies (2,304 outcomes; zero provider calls). Sixteen passed; the first six in the declared order were selected.

| World | Mean policy gap (USD) | Required gap (USD) | Reference award rate | Greedy award rate |
|---|---:|---:|---:|---:|
| market_002 | 45.88 | 7.95 | 1.000 | 0.000 |
| market_009 | 23.78 | 13.99 | 1.000 | 0.333 |
| market_011 | 14.73 | 12.94 | 1.000 | 0.750 |
| market_023 | 25.99 | 12.95 | 1.000 | 0.250 |
| market_025 | 19.22 | 12.59 | 1.000 | 0.417 |
| market_031 | 54.15 | 9.54 | 1.000 | 0.000 |

Rates above describe deterministic offline policies under stochastic observations, not the live model control. Both the per-seed economic scores and rejection reasons for all candidates are in [admission.json](reports/admission.json).

The source-pinned [design](reports/design.json) is pending provider and pilot admission, not a frozen confirmatory plan. Historical campaign evidence is unchanged.
