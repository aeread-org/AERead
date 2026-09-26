# refund_v2_1_gap

Why each Refund V2.1 policy model falls short of the answer key (the scripted canonical policy, which resolves all 120 cells as the case definitions authorize). Derived from the published bundles and the cases rebuilt from their definitions by `python -m aeread_families.refund.v2_gap`; `--check` regenerates these bytes. Descriptive only: no winner, no ranking, no interval.

The unit is the case. The 20 seeds of a scenario repeat one case (RF-D-01), so each number is a mean over the six cases of the share of cells, in percentage points. Every unresolved cell is exactly one part, chosen by the first thing that went wrong in its trajectory, so the parts sum to the shortfall.

| part | deepseek-v4-flash-0731 | gemini-2.5-flash-lite | gpt-5.6-luna | grok-4.3 |
|---|---|---|---|---|
| **resolved, minus the answer key** | **-50.0** | **-98.3** | **-20.8** | **-47.5** |
| decided before a required fact (procedure) | -44.2 | 0.0 | -15.0 | -29.2 |
| asked again for a known fact (procedure) | 0.0 | -80.8 | 0.0 | 0.0 |
| asked for a fact the case lacks (procedure) | 0.0 | -0.8 | -5.8 | 0.0 |
| correct denial, method null (format) | -5.8 | -16.7 | 0.0 | -17.5 |
| wrong decision (outcome) | 0.0 | 0.0 | 0.0 | -0.8 |
| wrong amount or method (outcome) | 0.0 | 0.0 | 0.0 | 0.0 |
| transaction not as proposed (outcome) | 0.0 | 0.0 | 0.0 | 0.0 |

What the shortfall is made of, per model (share of its 120 cells):

| cells | deepseek-v4-flash-0731 | gemini-2.5-flash-lite | gpt-5.6-luna | grok-4.3 |
|---|---|---|---|---|
| resolved as scored | 50.0% | 1.7% | 79.2% | 52.5% |
| reached the answer key's outcome | 100.0% | 18.3% | 94.2% | 99.2% |
| ended before any decision | 0.0% | 81.7% | 5.8% | 0.0% |
| reached a wrong outcome | 0.0% | 0.0% | 0.0% | 0.8% |

Procedure parts end the case at a rejected step; a correct denial written with `method: null` fails on the string "none" alone (RF-D-03). Each model's report is `reports/gap_decomposition_<model>.json`, with every unresolved cell and the step that decided it; `tables/contributions_<model>.jsonl` gives one row per unresolved cell.
