# Data-center family failure register

766 incidents across 768 cells in 9 runs of `datacenter_development_v2_world_panel_v1`.

Attribution answers the question worth asking later: whose fault was it? Anything a model can trigger is the model's, never the provider's.

| Attribution | As recorded | After reclassification |
|---|---:|---:|
| budget | 5 | 7 |
| environment | 11 | 9 |
| model | 356 | 371 |
| negotiation | 213 | 213 |
| provider | 181 | 166 |

17 incidents were recorded under one attribution and belong to another. The original condition is kept beside the correction.

## Runs

| Run | Cells | Incidents | Superseded |
|---|---:|---:|---|
| `datacenter_development_v2_world_panel_v1` | 192 | 183 | no |
| `datacenter_development_v2_world_panel_v1__superseded1__superseded1` | 192 | 234 | yes |
| `datacenter_development_v2_world_panel_v1_run3_partial_predegeneracy_fix_20260904` | 4 | 4 | yes |
| `datacenter_development_v2_world_panel_v1_run4_phasegraph_bug_20260904` | 25 | 25 | yes |
| `datacenter_development_v2_world_panel_v1_run5_precalibration_20260905` | 96 | 83 | yes |
| `datacenter_development_v2_world_panel_v1_run6_preplanning_20260906` | 96 | 79 | yes |
| `datacenter_development_v2_world_panel_v1_run7_action_budget_bug_20260906` | 33 | 32 | yes |
| `datacenter_development_v2_world_panel_v1_run8_cost_cap_too_tight_20260906` | 34 | 34 | yes |
| `datacenter_development_v2_world_panel_v1_run9_planning_only_20260907` | 96 | 92 | yes |

## Defects

The judgment-bearing half: what the design got wrong, what caught it, and where it stands. `detection` is the honest answer, including "nothing, it was found later".

| Defect | Severity | Detection | Disposition | Regression test |
|---|---|---|---|---|
| degenerate-counter-adoption | invalidates_measurement | offline probe over the generated pack | fixed | `test_adopting_every_counter_is_admissible_but_never_optimal` |
| unbounded-self-written-damages | invalidates_measurement | offline probe over the generated pack | fixed | `test_no_within_policy_stack_earns_unbounded_self_written_damages` |
| forced-amendment-no-decline | truncates_trajectories | live panel | fixed | `test_optional_amendment_can_be_declined_without_ending_the_episode` |
| undeclared-decline-transition | kills_cells | live panel | fixed | `test_every_transition_lands_on_a_declared_next_phase` |
| counter-terms-unrecorded | silent_wrong_metric | reading sealed evidence after a panel | fixed | `test_verbal_written_diagnostic_counts_adopted_undisclosed_terms` |
| coverage-counted-the-balloon | invalidates_measurement | recalibration to market magnitudes | fixed | `test_a_bullet_repayment_at_maturity_is_not_a_coverage_breach` |
| model-error-booked-as-provider | mis-attributes_failure | live panel | fixed | `test_an_absurd_integer_is_a_model_error_not_an_infrastructure_failure` |
| covenant-cliff-unbuildable-from-leverage | specification_not_realisable | recalibration to market magnitudes | worked_around | `test_every_world_has_feasible_trap_and_walk_away_paths` |
| traps-unreachable-by-counter-adopters | strata_do_not_test_what_they_claim | offline probe plus the calibrated live panel | fixed | `test_the_task_cannot_be_solved_without_cross_agreement_lookahead` |
| planning-decoupled-from-negotiation | under-tests_declared_capability | offline probe over the generated pack | fixed | `test_the_lookahead_has_a_reachable_solution_and_a_closed_alternative` |
| mechanisms-shipped-without-checking-they-bind | mechanism_does_not_bind | running naive strategies against the pack | fixed | `test_no_world_survives_a_naive_strategy_or_an_inert_lever` |
| primary-metric-is-survivorship-biased | headline_number_not_comparable | reading the completed panel | fixed | `test_every_completed_episode_is_scored` |
| bankability-threshold-never-binds | mechanism_does_not_bind | the sequencing diagnostic on the first full panel | fixed | `test_the_lender_requirement_sometimes_exceeds_market_convention` |
| sequencing-anchored-by-presentation-order | confounds_a_reported_metric | first panel carrying the sequencing diagnostic | fixed | `test_the_presented_order_does_not_favour_one_answer` |
| suite-needs-gitignored-artifacts | blocks_clean_checkout | running the suite in a fresh worktree | fixed | `test_the_suite_does_not_require_gitignored_artifacts` |
| costless-integrative-concession | mechanism_does_not_bind | manual trace of a single cell from observation to score | fixed | `test_the_concession_the_counterparty_asks_for_is_not_free` |
| evidence-bundles-break-the-publication-layout | blocks_clean_checkout | running the whole suite rather than the family subset | fixed | `test_evidence_bundles_use_the_standard_publication_categories` |
| panel-run-cannot-be-republished | headline_not_comparable | republishing the bundle after moving it to the standard layout | worked_around | `test_publish_refuses_a_run_whose_summary_and_design_disagree` |
| panel-pinned-to-a-superseded-pack | headline_not_comparable | manual trace of a single cell from observation to score | open | `test_world_panel_rejects_budget_overflow_and_drifted_pack` |

Open: panel-pinned-to-a-superseded-pack.
