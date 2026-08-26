"""Task 1.1b4b declaration-only analysis-inference authoring contract."""

from __future__ import annotations

import hashlib
import json

from pydantic import TypeAdapter, ValidationError
import pytest

import aeread.sdk.v1 as sdk_v1
from aeread.sdk.v1 import (
    AnalysisSourceRef,
    ClusterBootstrapStabilityIntervalSpec,
    EffectiveResamplingBlockSpec,
    HolmMultiplicityAdjustmentSpec,
    HypothesisTestSpec,
    InferenceCompatibilitySpec,
    IntervalSpec,
    MultiplicityAdjustmentSpec,
    NoHypothesisTestSpec,
    NoIntervalSpec,
    NoMultiplicityAdjustmentSpec,
    PairProjectionSpec,
    PairedRandomizationTestSpec,
    PopulationClusterProjectionSpec,
)


B4B_EXPORTS = {
    "AnalysisSourceRef",
    "EffectiveResamplingBlockSpec",
    "PopulationClusterProjectionSpec",
    "PairProjectionSpec",
    "NoIntervalSpec",
    "ClusterBootstrapStabilityIntervalSpec",
    "IntervalSpec",
    "NoHypothesisTestSpec",
    "PairedRandomizationTestSpec",
    "HypothesisTestSpec",
    "NoMultiplicityAdjustmentSpec",
    "HolmMultiplicityAdjustmentSpec",
    "MultiplicityAdjustmentSpec",
    "InferenceCompatibilitySpec",
}


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _source(kind: str) -> dict[str, object]:
    return {
        "spec_version": "aeread.analysis_source_ref/0.1",
        "record_type": "analysis_source_ref",
        "source_kind": kind,
        "record_id": f"source.{kind}",
        "record_version": "1.0.0",
        "content_sha256": _sha(kind),
    }


def _cluster_projection(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "spec_version": "aeread.cluster_projection/0.1",
        "record_type": "cluster_projection",
        "projection_id": "cluster.population",
        "projection_version": "1.0.0",
        "cluster_design_ref": _source("cluster_design"),
        "population_key_field": "population_unit_id",
        "replicate_nesting_rule": "all_plan_cells_for_unit_share_population_cluster",
        "coverage_rule": "exactly_one_population_cluster_per_planned_cell",
        "effective_block_kind": "strict_coarsening",
        "effective_blocks": [
            {
                "effective_block_id": "block.a",
                "population_cluster_ids": ["cluster.a", "cluster.b"],
            }
        ],
        "group_integrity_rule": "pair_and_pass_all_k_groups_wholly_nested",
        "ordering_rule": "effective_block_id_then_canonical_row_identity",
    }
    value.update(overrides)
    return value


def _pair_projection(kind: str = "paired", **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "spec_version": "aeread.pair_projection/0.1",
        "record_type": "pair_projection",
        "projection_id": "pair.policy",
        "projection_version": "1.0.0",
        "pairing_ref": _source("pairing_design"),
        "pairing_kind": kind,
        "coordinate_source": "resolved_plan_cell_coordinates",
        "direction": "subject_minus_comparator",
        "formation_rule": (
            "one_to_one_equal_pair_keys"
            if kind == "paired"
            else "independent_subject_and_comparator_arms"
        ),
        "duplicate_rule": "reject",
        "missing_pair_rule": "typed_missing_not_drop",
        "ordering_rule": (
            "pair_key_then_subject_then_comparator"
            if kind == "paired"
            else "subject_then_comparator_canonical_row_identity"
        ),
        "projection_scope": "analysis_relation_only",
    }
    value.update(overrides)
    return value


def _no_interval(reason: str = "not_requested") -> dict[str, object]:
    return {
        "spec_version": "aeread.interval/0.1",
        "record_type": "interval",
        "interval_kind": "none",
        "reason": reason,
        "method": "none",
    }


def _stability_interval(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "spec_version": "aeread.interval/0.1",
        "record_type": "interval",
        "interval_kind": "cluster_bootstrap_stability",
        "interval_id": "interval.stability",
        "interval_version": "1.0.0",
        "method": "percentile_cluster_bootstrap_stability",
        "coverage_claim": "none_descriptive_only",
        "target": "conditional_on_observed_effective_blocks",
        "central_mass": {"numerator": 9, "denominator": 10},
        "endpoint_definition": "equal_tailed_percentile_endpoints",
        "resample_count": 100,
        "resampling_seed": 0,
        "resampling_unit": "whole_effective_row_block",
        "effective_block_source": "population_cluster_projection",
        "group_integrity_rule": "pair_and_pass_all_k_groups_wholly_nested",
        "estimator_recompute_rule": (
            "complete_declared_estimator_over_all_rows_with_block_multiplicity"
        ),
        "sampler_policy": "aeread.sha256_rejection_uint256_mod_c/0.1",
        "endpoint_quantile_policy": "r7_linear_exact_rational",
        "minimum_effective_blocks": 2,
        "claim_boundary": "no_finite_population_or_superpopulation_coverage_claim",
    }
    value.update(overrides)
    return value


def _no_test(reason: str = "not_requested") -> dict[str, object]:
    return {
        "spec_version": "aeread.hypothesis_test/0.1",
        "record_type": "hypothesis_test",
        "test_kind": "none",
        "reason": reason,
        "method": "none",
    }


def _paired_test(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "spec_version": "aeread.hypothesis_test/0.1",
        "record_type": "hypothesis_test",
        "test_kind": "paired_randomization",
        "test_id": "test.paired",
        "test_version": "1.0.0",
        "method": "paired_sign_flip_randomization",
        "execution_assignment_design_ref": _source("execution_assignment_design"),
        "subject_role": "subject",
        "comparator_role": "comparator",
        "role_binding_rule": (
            "match_referenced_design_subject_and_comparator_execution_blocks"
        ),
        "statistic": "absolute_mean_subject_minus_comparator",
        "alternative": "two_sided",
        "extreme_tie_rule": "greater_than_or_equal",
        "pair_eligibility_rule": "every_preregistered_pair_has_exactly_two_valid_arm_outcomes",
        "missing_pair_rule": (
            "typed_ineligible_no_p_value_no_deletion_replacement_or_reassignment"
        ),
        "exhaustive_assignment_vector_threshold": 2,
        "monte_carlo_resample_count": 1,
        "monte_carlo_seed": 0,
        "exhaustive_order": "mask_ascending_pair_key_order_bit0_negative",
        "monte_carlo_policy": "aeread.paired_randomization_sha256_bit/0.1",
        "monte_carlo_correction": "plus_one_numerator_and_denominator",
        "numeric_policy": "aeread.exact_rational_binary64/0.1",
        "interval_requirement": "none",
    }
    value.update(overrides)
    return value


def _no_multiplicity(reason: str = "not_requested") -> dict[str, object]:
    return {
        "spec_version": "aeread.multiplicity/0.1",
        "record_type": "multiplicity",
        "multiplicity_kind": "none",
        "reason": reason,
        "method": "none",
    }


def _holm(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "spec_version": "aeread.multiplicity/0.1",
        "record_type": "multiplicity",
        "multiplicity_kind": "holm_familywise",
        "family_id": "family.confirmatory",
        "family_version": "1.0.0",
        "alpha": {"numerator": 1, "denominator": 20},
        "family_membership_source": "task_1_1b5_immutable_preregistered_test_nodes",
        "minimum_family_size": 2,
        "family_cardinality_rule": "at_least_two_distinct_preregistered_test_nodes",
        "family_ordering_rule": "eligible_raw_p_value_then_test_id_followed_by_ineligible_test_id",
        "method": "holm_step_down_familywise",
        "threshold_rule": "alpha_over_original_preregistered_family_size_minus_eligible_rank_plus_one",
        "stop_rule": "stop_rejecting_after_first_nonrejection",
        "adjusted_p_rule": "running_max_rank_scaled_clipped_one",
        "ineligible_test_rule": "retain_in_preregistered_family_cardinality_no_adjusted_p_no_rejection",
        "numeric_policy": "exact_rational",
    }
    value.update(overrides)
    return value


def _compatibility(target: str, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "spec_version": "aeread.inference_compatibility/0.1",
        "record_type": "inference_compatibility",
        "compatibility_id": "compatibility.example",
        "compatibility_version": "1.0.0",
        "inference_target": target,
        "panel_basis": "fixed_panel",
        "estimator_analysis_unit": "planned_cell",
        "missingness_kind": "planned_population_invalidate",
        "cluster_projection": None,
        "pair_projection": None,
        "interval": _no_interval(),
        "hypothesis_test": _no_test(),
        "multiplicity": _no_multiplicity(),
        "compatibility_matrix_version": "aeread.inference_compatibility_matrix/0.2",
    }
    value.update(overrides)
    return value


def test_task_1_1b4b_publishes_exact_fourteen_name_additive_surface() -> None:
    surface = tuple(sorted(sdk_v1.__all__))
    assert len(surface) == len(set(surface)) == 220
    assert B4B_EXPORTS <= set(surface)
    prior = tuple(name for name in surface if name not in B4B_EXPORTS)
    assert len(prior) == 206
    assert (
        hashlib.sha256(
            json.dumps(prior, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        == "13b0b9a9403d345979e8eb34213a94ad2fc9c91a395af42c326a83d3b40f917f"
    )


def test_all_concrete_records_admit_one_valid_constructor_shape() -> None:
    assert AnalysisSourceRef.model_validate(_source("cluster_design"))
    assert EffectiveResamplingBlockSpec.model_validate(
        {"effective_block_id": "block.a", "population_cluster_ids": ["a"]}
    )
    assert PopulationClusterProjectionSpec.model_validate(_cluster_projection())
    assert PairProjectionSpec.model_validate(_pair_projection())
    assert NoIntervalSpec.model_validate(_no_interval())
    assert ClusterBootstrapStabilityIntervalSpec.model_validate(_stability_interval())
    assert NoHypothesisTestSpec.model_validate(_no_test())
    assert PairedRandomizationTestSpec.model_validate(_paired_test())
    assert NoMultiplicityAdjustmentSpec.model_validate(_no_multiplicity())
    assert HolmMultiplicityAdjustmentSpec.model_validate(_holm())
    assert InferenceCompatibilitySpec.model_validate(
        _compatibility(
            "planned_panel_descriptive", missingness_kind="complete_case_conditional"
        )
    )


@pytest.mark.parametrize(
    ("factory", "record_type", "overrides"),
    [
        (
            _cluster_projection,
            PopulationClusterProjectionSpec,
            {"cluster_design_ref": _source("pairing_design")},
        ),
        (
            _cluster_projection,
            PopulationClusterProjectionSpec,
            {
                "effective_blocks": [
                    {
                        "effective_block_id": "block.a",
                        "population_cluster_ids": ["b", "a"],
                    }
                ]
            },
        ),
        (
            _pair_projection,
            PairProjectionSpec,
            {"formation_rule": "independent_subject_and_comparator_arms"},
        ),
        (
            _paired_test,
            PairedRandomizationTestSpec,
            {"execution_assignment_design_ref": _source("pairing_design")},
        ),
        (
            _stability_interval,
            ClusterBootstrapStabilityIntervalSpec,
            {"central_mass": {"numerator": 1, "denominator": 1}},
        ),
        (
            _holm,
            HolmMultiplicityAdjustmentSpec,
            {"alpha": {"numerator": 1, "denominator": 1}},
        ),
    ],
)
def test_local_declarations_reject_invalid_intrinsic_contracts(
    factory: object, record_type: object, overrides: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        record_type.model_validate(factory(**overrides))  # type: ignore[union-attr,operator]


@pytest.mark.parametrize(
    "overrides", [{"record_id": " "}, {"record_version": "latest"}]
)
def test_analysis_source_ref_requires_pinned_nonblank_identity(
    overrides: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        AnalysisSourceRef.model_validate({**_source("cluster_design"), **overrides})


@pytest.mark.parametrize(
    "target,overrides",
    [
        (
            "planned_panel_descriptive",
            {"cluster_projection": _cluster_projection()},
        ),
        (
            "finite_population_probability_sample",
            {"panel_basis": "sampled_srswor", "interval": _stability_interval()},
        ),
        (
            "cluster_bootstrap_descriptive_stability",
            {"interval": _no_interval()},
        ),
        (
            "paired_observational_effect",
            {
                "estimator_analysis_unit": "pair",
                "pair_projection": _pair_projection(),
                "hypothesis_test": _paired_test(),
            },
        ),
        (
            "unpaired_observational_difference",
            {
                "pair_projection": _pair_projection("unpaired"),
                "hypothesis_test": _paired_test(),
            },
        ),
        (
            "paired_randomized_effect",
            {
                "estimator_analysis_unit": "pair",
                "pair_projection": _pair_projection(),
                "hypothesis_test": _paired_test(),
                "interval": _no_interval("paired_randomization_test_has_no_interval"),
                "missingness_kind": "complete_case_conditional",
            },
        ),
    ],
)
def test_inference_compatibility_rejects_closed_matrix_mismatches(
    target: str, overrides: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        InferenceCompatibilitySpec.model_validate(_compatibility(target, **overrides))


def test_discriminated_unions_normalize_raw_dicts_and_reject_mixed_arms() -> None:
    assert isinstance(
        TypeAdapter(IntervalSpec).validate_python(_no_interval()), NoIntervalSpec
    )
    with pytest.raises(ValidationError):
        TypeAdapter(IntervalSpec).validate_python(
            {**_no_interval(), "interval_id": "unauthorized"}
        )
