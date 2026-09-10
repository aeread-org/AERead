# Data-center family failure register

583 incidents across 576 cells in 8 runs of `datacenter_development_v2_world_panel_v1`.

Attribution answers the question worth asking later: whose fault was it? Anything a model can trigger is the model's, never the provider's.

| Attribution | As recorded | After reclassification |
|---|---:|---:|
| budget | 5 | 7 |
| environment | 10 | 8 |
| model | 215 | 230 |
| negotiation | 206 | 206 |
| provider | 147 | 132 |

17 incidents were recorded under one attribution and belong to another. The original condition is kept beside the correction.

## Runs

| Run | Cells | Incidents | Superseded |
|---|---:|---:|---|
| `datacenter_development_v2_world_panel_v1` | 192 | 234 | no |
| `datacenter_development_v2_world_panel_v1_run3_partial_predegeneracy_fix_20260904` | 4 | 4 | yes |
| `datacenter_development_v2_world_panel_v1_run4_phasegraph_bug_20260904` | 25 | 25 | yes |
| `datacenter_development_v2_world_panel_v1_run5_precalibration_20260905` | 96 | 83 | yes |
| `datacenter_development_v2_world_panel_v1_run6_preplanning_20260906` | 96 | 79 | yes |
| `datacenter_development_v2_world_panel_v1_run7_action_budget_bug_20260906` | 33 | 32 | yes |
| `datacenter_development_v2_world_panel_v1_run8_cost_cap_too_tight_20260906` | 34 | 34 | yes |
| `datacenter_development_v2_world_panel_v1_run9_planning_only_20260907` | 96 | 92 | yes |

## Defects

| Defect | Severity | Status | Regression test |
|---|---|---|---|
| degenerate-counter-adoption | invalidates_measurement | fixed | `test_adopting_every_counter_is_admissible_but_never_optimal` |
| unbounded-self-written-damages | invalidates_measurement | fixed | `test_no_within_policy_stack_earns_unbounded_self_written_damages` |
| forced-amendment-no-decline | truncates_trajectories | fixed | `test_optional_amendment_can_be_declined_without_ending_the_episode` |
| undeclared-decline-transition | kills_cells | fixed | `test_every_transition_lands_on_a_declared_next_phase` |
| counter-terms-unrecorded | silent_wrong_metric | fixed | `test_verbal_written_diagnostic_counts_adopted_undisclosed_terms` |
| coverage-counted-the-balloon | invalidates_measurement | fixed | `test_a_bullet_repayment_at_maturity_is_not_a_coverage_breach` |
| model-error-booked-as-provider | mis-attributes_failure | fixed | `test_an_absurd_integer_is_a_model_error_not_an_infrastructure_failure` |
| covenant-cliff-unbuildable-from-leverage | specification_not_realisable | worked_around | `test_every_world_has_feasible_trap_and_walk_away_paths` |
| traps-unreachable-by-counter-adopters | strata_do_not_test_what_they_claim | fixed | `test_the_task_cannot_be_solved_without_cross_agreement_lookahead` |
| planning-decoupled-from-negotiation | under-tests_declared_capability | fixed | `test_the_lookahead_has_a_reachable_solution_and_a_closed_alternative` |
| mechanisms-shipped-without-checking-they-bind | mechanism_does_not_bind | fixed | `test_no_world_survives_a_naive_strategy_or_an_inert_lever` |
| primary-metric-is-survivorship-biased | headline_number_not_comparable | open | `none` |
| bankability-threshold-never-binds | mechanism_does_not_bind | open | `none` |
| sequencing-anchored-by-presentation-order | confounds_a_reported_metric | open | `none` |
| suite-needs-gitignored-artifacts | blocks_clean_checkout | open | `none` |

Open: primary-metric-is-survivorship-biased, bankability-threshold-never-binds, sequencing-anchored-by-presentation-order, suite-needs-gitignored-artifacts.
