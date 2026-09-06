# Data-center family failure register

541 incidents across 573 cells in 10 runs of `datacenter_development_v2_world_panel_v1`.

Attribution answers the question worth asking later: whose fault was it? Anything a model can trigger is the model's, never the provider's.

| Attribution | As recorded | After reclassification |
|---|---:|---:|
| budget | 16 | 16 |
| environment | 10 | 10 |
| model | 281 | 298 |
| negotiation | 170 | 170 |
| provider | 64 | 47 |

17 incidents were recorded under one attribution and belong to another. The original condition is kept beside the correction.

## Runs

| Run | Cells | Incidents | Superseded |
|---|---:|---:|---|
| `datacenter_development_v2_world_panel_v1` | 96 | 79 | no |
| `datacenter_development_v2_world_panel_v1_aborted_deepinfra_venice_20260903` | 3 | 3 | yes |
| `datacenter_development_v2_world_panel_v1_aborted_mistral_20260903` | 3 | 3 | yes |
| `datacenter_development_v2_world_panel_v1_aborted_reka_mistral_20260903` | 7 | 7 | yes |
| `datacenter_development_v2_world_panel_v1_aborted_zai_20260903` | 3 | 3 | yes |
| `datacenter_development_v2_world_panel_v1_run1_amendment_bug_20260903` | 144 | 144 | yes |
| `datacenter_development_v2_world_panel_v1_run2_pre_amendment_fix_20260904` | 192 | 190 | yes |
| `datacenter_development_v2_world_panel_v1_run3_partial_predegeneracy_fix_20260904` | 4 | 4 | yes |
| `datacenter_development_v2_world_panel_v1_run4_phasegraph_bug_20260904` | 25 | 25 | yes |
| `datacenter_development_v2_world_panel_v1_run5_precalibration_20260905` | 96 | 83 | yes |

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
| traps-unreachable-by-counter-adopters | strata_do_not_test_what_they_claim | open | `none` |
| planning-decoupled-from-negotiation | under-tests_declared_capability | open | `none` |
| suite-needs-gitignored-artifacts | blocks_clean_checkout | open | `none` |

Open: traps-unreachable-by-counter-adopters, planning-decoupled-from-negotiation, suite-needs-gitignored-artifacts.
