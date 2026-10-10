# Housing reasoning-summary setting experiment

This experiment tests whether requesting exposed summaries changes housing-agent decisions. It varies Claude `--thinking-display summarized` versus `omitted`, and Codex `model_reasoning_summary="detailed"` versus `"none"`. Reasoning effort remains low. Request and raw stdout/stderr retention are enabled in both conditions; sessions are fresh, with identical family prompts and worlds.

The scope is five worlds selected from the earlier non-inspected-signing diagnostic: 300002, 300003, 300005, 300011, 300018. Both pooled and true-cost landlord arms are included for every world, avoiding the previous asymmetric nine-cell selection. Three fresh plays per condition and subject yield 120 planned episodes. This estimates a setting effect in selected worlds, not general benchmark performance.

The driver seals the schedule and source hash before execution. Within each repeat, ON/OFF block order and cell order are randomized with seed 20261009. Both subjects use the same schedule with balanced condition counts. The realized random draw placed OFF before ON in all three repeats; block order is not counterbalanced, so time drift remains an interpretation limit. Each condition/repeat has a distinct campaign identity. Incomplete blocks halt without selective retries. The inference seed is unavailable through these CLIs; repeat indices identify independent draws, not identical sampling randomness.

Primary outcome: focal tenant `net_expected_response_odds`. Secondary outcomes: inspections, signing, inspected signing, chosen listing, rent. The analysis averages repeats and landlord arms within each world, then compares ON minus OFF across five paired world clusters using a Student t interval. Fresh-play spread is reported separately. Conditional rent comparisons are descriptive because signing itself can change. Exact environment scoring is replay-verified by the existing runner.

The first transport gate was interrupted when the driver reused a campaign suffix across conditions. Its output remains under `runs/summary_experiment_20261009` and is excluded. The measured run is under `runs/summary_experiment_20261009_v2` in the `housing-lemons-outside-demand` worktree.

```sh
PYTHONPATH=src:tools/cli_subjects .venv/bin/python tools/cli_subjects/housing_summary_experiment.py --subject claude_opus55 --base /path/to/runs/new_experiment
PYTHONPATH=src:tools/cli_subjects .venv/bin/python tools/cli_subjects/housing_summary_experiment.py --subject codex_sol61 --base /path/to/runs/new_experiment
PYTHONPATH=src:tools/cli_subjects .venv/bin/python tools/cli_subjects/housing_summary_analysis.py /path/to/runs/new_experiment
```

Raw retained output is local and ignored by Git. Summaries are provider-exposed text; they do not establish access to full internal chain of thought. A wide interval cannot establish that requesting summaries has no effect.

## Completed results

All 120 planned episodes completed, with zero failures. Each passed receipt verification and exact score replay. All ten initial-input groups per model match across their six plays.

| Model | ON focal net [95% CI] | OFF focal net [95% CI] | ON minus OFF [95% CI] |
|---|---:|---:|---:|
| Claude Opus 5.5 | $112.07 [$-74.75, $298.89] | $95.11 [$-57.80, $248.02] | $16.97 [$-28.29, $62.22] |
| Codex Sol 6.1 | $181.60 [$-16.70, $379.90] | $178.10 [$-47.11, $403.30] | $3.50 [$-46.01, $53.02] |

Neither payoff difference establishes a summary-setting effect. This is not an equivalence result: the intervals permit material effects, the worlds were selected, and realized block order was OFF then ON in every repeat.

| Model / setting | Focal inspections per episode | Signed | Signed inspected | Readable summary calls / retained calls |
|---|---:|---:|---:|---:|
| Claude ON | 1.53 | 24/30 | 5/30 | 139/156 |
| Claude OFF | 1.63 | 24/30 | 4/30 | 0/165 |
| Codex ON | 1.60 | 24/30 | 4/30 | 92/168 |
| Codex OFF | 1.67 | 24/30 | 7/30 | 0/177 |

Pooled focal payoffs are identical across summary conditions for both models in every sampled world. This is observed agreement, not proof of population equality. The true-cost differences are exploratory: Claude +$33.93 [-$56.58, +$124.44]; Codex +$7.01 [-$92.02, +$106.03].

Mean within-cell payoff SD over fresh plays is $30.36 ON versus $52.13 OFF for Claude, and $48.31 ON versus $36.81 OFF for Codex. This sampling variation helps explain why comparing a single retained rerun with the original play cannot isolate the summary setting.

Full per-episode rents, listings, qualities, receipts, secondary intervals and initial-input checks are in the local `analysis.json`. Exact frozen driver snapshots, contracts, requests and raw streams remain beside it. The rendered report is `/Users/chenyusu/analysis/housing/housing_summary_on_off_experiment.pdf`.
