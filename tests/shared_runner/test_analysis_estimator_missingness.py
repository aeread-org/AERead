from __future__ import annotations

import ast
import hashlib
import inspect
import json
import textwrap

import pytest
from pydantic import TypeAdapter, ValidationError

import aeread.sdk.v1 as sdk_v1
from aeread.sdk.v1 import (
    BooleanSuccessPredicateSpec,
    BoundsOrSensitivityMissingnessSpec,
    CanonicalRational,
    CompleteCaseConditionalMissingnessSpec,
    DifferenceEstimatorSpec,
    EpisodeMissingnessSpec,
    EstimatorSpec,
    IdentityTransformationSpec,
    MeanEstimatorSpec,
    PassAllKEstimatorSpec,
    PlannedPopulationInvalidateMissingnessSpec,
    ProbabilityEstimatorSpec,
    QuantileEstimatorSpec,
    RaterCoverageSummarySpec,
    RaterDisagreementSummarySpec,
    RaterSummarySpec,
)
from aeread.sdk.v1.records import ArtifactRef, ImplementationRef
import aeread.sdk.v1.records as records_module


ANALYSIS_ESTIMATOR_MISSINGNESS_EXPORTS = {
    "BooleanSuccessPredicateSpec",
    "BoundsOrSensitivityMissingnessSpec",
    "CanonicalRational",
    "CompleteCaseConditionalMissingnessSpec",
    "DifferenceEstimatorSpec",
    "EpisodeMissingnessSpec",
    "EstimatorSpec",
    "IdentityTransformationSpec",
    "MeanEstimatorSpec",
    "PassAllKEstimatorSpec",
    "PlannedPopulationInvalidateMissingnessSpec",
    "ProbabilityEstimatorSpec",
    "QuantileEstimatorSpec",
    "RaterCoverageSummarySpec",
    "RaterDisagreementSummarySpec",
    "RaterSummarySpec",
}


def test_task_1_1b4a_publishes_one_exact_additive_surface() -> None:
    surface = tuple(sorted(sdk_v1.__all__))
    b3b_exports = {
        "AssignmentAuthoringRecordRef",
        "ExchangeabilityDomainSpec",
        "ExecuteUniformWithinPairAssignmentSourceSpec",
        "ExecutionAssignmentSourceSpec",
        "ImportedUniformWithinPairAssignmentSourceSpec",
        "IndependentUniformWithinPairExecutionAssignmentSpec",
    }

    assert ANALYSIS_ESTIMATOR_MISSINGNESS_EXPORTS <= set(surface)
    assert len(surface) == len(set(surface)) == 206
    without_b3b = tuple(name for name in surface if name not in b3b_exports)
    assert len(without_b3b) == 200
    prior = tuple(
        name
        for name in without_b3b
        if name not in ANALYSIS_ESTIMATOR_MISSINGNESS_EXPORTS
    )
    assert len(prior) == 184
    assert (
        hashlib.sha256(
            json.dumps(prior, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        == "2b2334f96db668a41a42ee876f654a70740fb90d22b12a234162a1d3c153b723"
    )


def test_task_1_1b4a_symbols_are_constructible_strict_models() -> None:
    assert CanonicalRational(numerator=0, denominator=1).model_dump() == {
        "numerator": 0,
        "denominator": 1,
    }
    assert EstimatorSpec is not None
    assert EpisodeMissingnessSpec is not None
    assert RaterSummarySpec is not None
    assert all(
        isinstance(symbol, type)
        for symbol in (
            BooleanSuccessPredicateSpec,
            BoundsOrSensitivityMissingnessSpec,
            CompleteCaseConditionalMissingnessSpec,
            DifferenceEstimatorSpec,
            IdentityTransformationSpec,
            MeanEstimatorSpec,
            PassAllKEstimatorSpec,
            PlannedPopulationInvalidateMissingnessSpec,
            ProbabilityEstimatorSpec,
            QuantileEstimatorSpec,
            RaterCoverageSummarySpec,
            RaterDisagreementSummarySpec,
        )
    )


@pytest.mark.parametrize("value", [True, 1.0, "1", None])
def test_canonical_rational_rejects_coercive_numerators(value: object) -> None:
    with pytest.raises(ValidationError):
        CanonicalRational(numerator=value, denominator=1)


def _implementation(suffix: str = "1") -> ImplementationRef:
    return ImplementationRef(
        implementation_id=f"analysis.impl.{suffix}",
        version="1.0.0",
        content_sha256=suffix * 64,
    )


def _artifact(suffix: str = "a") -> ArtifactRef:
    return ArtifactRef(sha256=suffix * 64, media_type="application/json", size_bytes=7)


def _predicate(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "spec_version": "aeread.boolean_success_predicate/0.1",
        "record_type": "boolean_success_predicate",
        "predicate_id": "success",
        "predicate_version": "1.0.0",
        "input_metric_id": "utility",
        "input_schema_ref": "schema://metric/utility/1",
        "implementation": _implementation(),
        "output_kind": "boolean",
        "semantic_scope": "measurement_success_not_operational_availability",
    }
    values.update(overrides)
    return values


def _estimator_common(kind: str, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "spec_version": "aeread.estimator/0.1",
        "record_type": "estimator",
        "estimator_kind": kind,
        "estimator_id": f"{kind}-estimator",
        "estimator_version": "1.0.0",
        "output_metric_id": f"{kind}-output",
        "input_numeric_policy": "aeread.exact_rational_binary64/0.1",
        "output_rounding_policy": "aeread.binary64_rne/0.1",
        "rounding_stage": "typed_output_only_never_internal",
    }
    values.update(overrides)
    return values


def _missingness_common(kind: str, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "spec_version": "aeread.episode_missingness/0.1",
        "record_type": "episode_missingness",
        "missingness_kind": kind,
        "policy_id": f"{kind}-policy",
        "policy_version": "1.0.0",
        "coverage_unit": "planned_cell",
        "count_reporting_rule": "planned_valid_missing_invalid_counts_separate",
        "silent_drop_rule": "forbidden",
        "zero_attempt_rule": "run_coverage_not_observation",
        "valid_tie_rule": "valid_measurement_not_missing",
    }
    values.update(overrides)
    return values


def _mean(**overrides: object) -> MeanEstimatorSpec:
    values = _estimator_common(
        "mean",
        input_metric_id="utility",
        analysis_unit="planned_cell",
        weighting="row_uniform",
        within_cluster_reduction=None,
    )
    values.update(overrides)
    return MeanEstimatorSpec(**values)


def _difference(**overrides: object) -> DifferenceEstimatorSpec:
    values = _estimator_common(
        "difference",
        input_metric_id="utility",
        input_arity=2,
        operand_order="subject_minus_comparator",
        analysis_unit="planned_cell",
        weighting="row_uniform",
        within_cluster_reduction=None,
    )
    values.update(overrides)
    return DifferenceEstimatorSpec(**values)


def _probability(**overrides: object) -> ProbabilityEstimatorSpec:
    values = _estimator_common(
        "probability",
        predicate=_predicate(),
        analysis_unit="planned_cell",
        weighting="row_uniform",
        denominator_source="episode_missingness_policy",
    )
    values.update(overrides)
    return ProbabilityEstimatorSpec(**values)


def _quantile(**overrides: object) -> QuantileEstimatorSpec:
    values = _estimator_common(
        "quantile",
        input_metric_id="utility",
        analysis_unit="planned_cell",
        weighting="row_uniform",
        q={"numerator": 1, "denominator": 2},
        interpolation="r7_linear",
    )
    values.update(overrides)
    return QuantileEstimatorSpec(**values)


def _pass_all_k(**overrides: object) -> PassAllKEstimatorSpec:
    values = _estimator_common(
        "pass_all_k",
        predicate=_predicate(),
        k=3,
        analysis_unit="planned_cell_group",
        weighting="group_uniform",
        group_key_fields=("population_unit_id", "case_id"),
        group_semantics="exactly_k_unique_plan_cells",
        incomplete_group_rule="typed_missing_not_false",
    )
    values.update(overrides)
    return PassAllKEstimatorSpec(**values)


@pytest.mark.parametrize(
    ("numerator", "denominator"),
    [(0, 2), (2, 4), (1, 0), (1, -2), (3, 3)],
)
def test_canonical_rational_rejects_noncanonical_values(
    numerator: int, denominator: int
) -> None:
    with pytest.raises(ValidationError):
        CanonicalRational(numerator=numerator, denominator=denominator)


def test_canonical_rational_accepts_reduced_sign_and_has_only_two_fields() -> None:
    assert CanonicalRational(numerator=-3, denominator=7).model_dump() == {
        "numerator": -3,
        "denominator": 7,
    }
    assert tuple(CanonicalRational.model_fields) == ("numerator", "denominator")


def test_canonical_rational_rejects_normal_subclass_admission() -> None:
    class Extended(CanonicalRational):
        note: str

    extended = Extended(numerator=1, denominator=2, note="unauthorized")
    with pytest.raises(ValidationError):
        CanonicalRational.model_validate(extended)


@pytest.mark.parametrize(
    "overrides",
    [
        {"predicate_id": " "},
        {"predicate_version": "latest"},
        {"input_metric_id": ""},
        {"input_schema_ref": "\t"},
        {
            "implementation": {
                "implementation_id": "x",
                "version": "latest",
                "content_sha256": "1" * 64,
            }
        },
        {"output_kind": "score"},
        {"semantic_scope": "operational_availability"},
        {"options": {}},
    ],
)
def test_boolean_success_predicate_rejects_invalid_contracts(
    overrides: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        BooleanSuccessPredicateSpec(**_predicate(**overrides))


@pytest.mark.parametrize(
    ("unit", "weighting", "reduction", "accepted"),
    [
        ("planned_cell", "row_uniform", None, True),
        ("population_cluster", "cluster_uniform", "mean", True),
        ("planned_cell", "cluster_uniform", None, False),
        ("planned_cell", "row_uniform", "mean", False),
        ("population_cluster", "row_uniform", "mean", False),
        ("population_cluster", "cluster_uniform", None, False),
    ],
)
def test_mean_estimator_freezes_analysis_unit_weighting_and_reduction(
    unit: str, weighting: str, reduction: str | None, accepted: bool
) -> None:
    constructor = lambda: _mean(
        analysis_unit=unit,
        weighting=weighting,
        within_cluster_reduction=reduction,
    )
    if accepted:
        assert constructor().analysis_unit == unit
    else:
        with pytest.raises(ValidationError):
            constructor()


@pytest.mark.parametrize(
    ("unit", "weighting", "reduction", "accepted"),
    [
        ("planned_cell", "row_uniform", None, True),
        ("population_cluster", "cluster_uniform", "mean", True),
        ("pair", "pair_uniform", None, True),
        ("pair", "row_uniform", None, False),
        ("pair", "pair_uniform", "mean", False),
        ("population_cluster", "cluster_uniform", None, False),
    ],
)
def test_difference_estimator_freezes_analysis_unit_weighting_and_reduction(
    unit: str, weighting: str, reduction: str | None, accepted: bool
) -> None:
    constructor = lambda: _difference(
        analysis_unit=unit,
        weighting=weighting,
        within_cluster_reduction=reduction,
    )
    if accepted:
        assert constructor().operand_order == "subject_minus_comparator"
    else:
        with pytest.raises(ValidationError):
            constructor()


@pytest.mark.parametrize("value", [0, 1, 3, True, 2.0, "2", None])
def test_difference_input_arity_is_exact_strict_two(value: object) -> None:
    constructor = lambda: _difference(input_arity=value)
    if type(value) is int and value == 2:
        assert constructor().input_arity == 2
    else:
        with pytest.raises(ValidationError):
            constructor()


def test_probability_denominator_is_owned_by_missingness_policy() -> None:
    assert _probability().denominator_source == "episode_missingness_policy"
    with pytest.raises(ValidationError):
        _probability(denominator_source="valid")


@pytest.mark.parametrize(
    "q",
    [
        {"numerator": 0, "denominator": 1},
        {"numerator": 1, "denominator": 1},
        {"numerator": -1, "denominator": 2},
        {"numerator": 3, "denominator": 2},
        {"numerator": 2, "denominator": 4},
        0.5,
    ],
)
def test_quantile_requires_reduced_rational_strictly_between_zero_and_one(
    q: object,
) -> None:
    with pytest.raises(ValidationError):
        _quantile(q=q)


@pytest.mark.parametrize(
    "overrides",
    [
        {"k": 0},
        {"k": -1},
        {"k": True},
        {"k": 3.0},
        {"group_key_fields": ()},
        {"group_key_fields": ("case_id", "population_unit_id")},
        {"group_key_fields": ("case_id", "case_id")},
        {"group_key_fields": ("case_id", "attempt_id")},
        {"group_semantics": "at_least_k_cells"},
        {"incomplete_group_rule": "false"},
    ],
)
def test_pass_all_k_rejects_invalid_group_contracts(
    overrides: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        _pass_all_k(**overrides)


def test_estimator_union_normalizes_raw_dicts_and_rejects_wrong_arm_payload() -> None:
    adapter = TypeAdapter(EstimatorSpec)
    for model in (_mean(), _difference(), _probability(), _quantile(), _pass_all_k()):
        parsed = adapter.validate_python(model.model_dump(mode="python"))
        assert type(parsed) is type(model)
    mixed = _mean().model_dump(mode="python") | {"predicate": _predicate()}
    with pytest.raises(ValidationError):
        adapter.validate_python(mixed)


@pytest.mark.parametrize(
    ("input_units", "output_units"),
    [("USD", "seconds"), (" ", " "), ("USD", "")],
)
def test_identity_transformation_requires_one_nonblank_unit(
    input_units: str, output_units: str
) -> None:
    with pytest.raises(ValidationError):
        IdentityTransformationSpec(
            spec_version="aeread.transformation/0.1",
            record_type="transformation",
            transformation_kind="identity",
            input_units=input_units,
            output_units=output_units,
            unit_rule="input_and_output_units_must_match",
        )


def _planned_missingness(
    **overrides: object,
) -> PlannedPopulationInvalidateMissingnessSpec:
    values = _missingness_common(
        "planned_population_invalidate",
        scientific_target="planned_population_primary",
        denominator_treatment="planned",
        ignorability_assumption="none",
        missing_or_invalid_rule="typed_invalid_primary_analysis",
        conditional_secondary_rule="separate_preregistered_block_only",
    )
    values.update(overrides)
    return PlannedPopulationInvalidateMissingnessSpec(**values)


def _conditional_missingness(
    **overrides: object,
) -> CompleteCaseConditionalMissingnessSpec:
    values = _missingness_common(
        "complete_case_conditional",
        scientific_target="complete_case_conditional",
        denominator_treatment="valid_only",
        minimum_valid_planned_cells=2,
        ignorability_assumption="none_claimed",
        missing_or_invalid_rule="exclude_with_typed_disposition_and_report",
        population_primary_claim="forbidden",
    )
    values.update(overrides)
    return CompleteCaseConditionalMissingnessSpec(**values)


def _bounds_missingness(**overrides: object) -> BoundsOrSensitivityMissingnessSpec:
    values = _missingness_common(
        "bounds_or_sensitivity",
        scientific_target="bounds_or_sensitivity",
        denominator_treatment="planned_with_typed_unobserved_units",
        method=_implementation("2"),
        method_input_schema_ref="schema://missingness/bounds/1",
        assumption_artifact_ref=_artifact("b"),
        point_estimate_rule="no_unbounded_complete_case_primary",
    )
    values.update(overrides)
    return BoundsOrSensitivityMissingnessSpec(**values)


@pytest.mark.parametrize(
    "constructor",
    [_planned_missingness, _conditional_missingness, _bounds_missingness],
)
def test_missingness_is_planned_cell_only_and_has_no_realized_fields(
    constructor,
) -> None:
    assert constructor().coverage_unit == "planned_cell"
    with pytest.raises(ValidationError):
        constructor(coverage_unit="cluster")
    with pytest.raises(ValidationError):
        constructor(planned_count=10)


@pytest.mark.parametrize("value", [0, -1, True, 2.0, "2", None])
def test_complete_case_minimum_is_strict_positive_planned_cells(value: object) -> None:
    with pytest.raises(ValidationError):
        _conditional_missingness(minimum_valid_planned_cells=value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"policy_id": ""},
        {"policy_version": "latest"},
        {"method_input_schema_ref": " "},
        {
            "method": {
                "implementation_id": "x",
                "version": "latest",
                "content_sha256": "2" * 64,
            }
        },
        {
            "assumption_artifact_ref": {
                "sha256": "b" * 64,
                "media_type": " ",
                "size_bytes": 7,
            }
        },
    ],
)
def test_bounds_missingness_requires_complete_exact_pins(
    overrides: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        _bounds_missingness(**overrides)


def test_missingness_union_normalizes_arms_and_rejects_mixed_payload() -> None:
    adapter = TypeAdapter(EpisodeMissingnessSpec)
    for model in (
        _planned_missingness(),
        _conditional_missingness(),
        _bounds_missingness(),
    ):
        parsed = adapter.validate_python(model.model_dump(mode="python"))
        assert type(parsed) is type(model)
    mixed = _planned_missingness().model_dump(mode="python") | {
        "minimum_valid_planned_cells": 2
    }
    with pytest.raises(ValidationError):
        adapter.validate_python(mixed)


def _coverage(**overrides: object) -> RaterCoverageSummarySpec:
    values: dict[str, object] = {
        "spec_version": "aeread.rater_summary/0.1",
        "record_type": "rater_summary",
        "summary_kind": "coverage",
        "summary_id": "judge-coverage",
        "summary_version": "1.0.0",
        "denominator": "planned_judgment_slots",
        "reported_counts": (
            "planned_slots",
            "valid_slots",
            "missing_slots",
            "invalid_slots",
        ),
        "missing_judgment_score_rule": "never_coerce_to_score_zero",
        "score_effect": "none_descriptive_only",
    }
    values.update(overrides)
    return RaterCoverageSummarySpec(**values)


def _disagreement(**overrides: object) -> RaterDisagreementSummarySpec:
    values: dict[str, object] = {
        "spec_version": "aeread.rater_summary/0.1",
        "record_type": "rater_summary",
        "summary_kind": "categorical_pairwise_disagreement",
        "summary_id": "judge-disagreement",
        "summary_version": "1.0.0",
        "input_rule": "accepted_terminal_categorical_judgments_only",
        "denominator": "unordered_valid_rater_pairs",
        "metric": "pairwise_disagreement_probability",
        "fewer_than_two_rule": "typed_unavailable_not_zero",
        "tie_rule": "preserve_valid_categorical_tie",
        "score_effect": "none_descriptive_only",
    }
    values.update(overrides)
    return RaterDisagreementSummarySpec(**values)


@pytest.mark.parametrize(
    "reported_counts",
    [
        ("planned_slots", "valid_slots", "invalid_slots", "missing_slots"),
        ("planned_slots", "valid_slots", "missing_slots"),
        ("planned_slots", "valid_slots", "missing_slots", "invalid_slots", "score"),
    ],
)
def test_rater_coverage_freezes_exact_count_order(
    reported_counts: tuple[str, ...]
) -> None:
    with pytest.raises(ValidationError):
        _coverage(reported_counts=reported_counts)


def test_rater_summaries_are_descriptive_and_union_is_closed() -> None:
    adapter = TypeAdapter(RaterSummarySpec)
    for model in (_coverage(), _disagreement()):
        parsed = adapter.validate_python(model.model_dump(mode="python"))
        assert type(parsed) is type(model)
        assert parsed.score_effect == "none_descriptive_only"
    with pytest.raises(ValidationError):
        _disagreement(fewer_than_two_rule="zero")
    with pytest.raises(ValidationError):
        _coverage(aggregation="majority_vote")


@pytest.mark.parametrize(
    ("constructor", "overrides"),
    [
        (_mean, {"estimator_id": ""}),
        (_difference, {"estimator_version": "latest"}),
        (_probability, {"output_metric_id": " "}),
        (_quantile, {"input_metric_id": ""}),
        (_pass_all_k, {"estimator_version": "1"}),
        (_planned_missingness, {"policy_version": "stable"}),
        (_coverage, {"summary_id": ""}),
        (_disagreement, {"summary_version": "current"}),
    ],
)
def test_analysis_declarations_reject_blank_or_unpinned_identities(
    constructor, overrides: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        constructor(**overrides)


def _all_concrete_records() -> tuple[object, ...]:
    return (
        CanonicalRational(numerator=1, denominator=2),
        BooleanSuccessPredicateSpec(**_predicate()),
        _mean(),
        _difference(),
        _probability(),
        _quantile(),
        _pass_all_k(),
        IdentityTransformationSpec(
            spec_version="aeread.transformation/0.1",
            record_type="transformation",
            transformation_kind="identity",
            input_units="USD",
            output_units="USD",
            unit_rule="input_and_output_units_must_match",
        ),
        _planned_missingness(),
        _conditional_missingness(),
        _bounds_missingness(),
        _coverage(),
        _disagreement(),
    )


def test_all_public_record_fields_use_the_exact_canonical_order() -> None:
    expected = {
        CanonicalRational: ("numerator", "denominator"),
        BooleanSuccessPredicateSpec: (
            "spec_version",
            "record_type",
            "predicate_id",
            "predicate_version",
            "input_metric_id",
            "input_schema_ref",
            "implementation",
            "output_kind",
            "semantic_scope",
        ),
        MeanEstimatorSpec: (
            "spec_version",
            "record_type",
            "estimator_kind",
            "estimator_id",
            "estimator_version",
            "output_metric_id",
            "input_numeric_policy",
            "output_rounding_policy",
            "rounding_stage",
            "input_metric_id",
            "analysis_unit",
            "weighting",
            "within_cluster_reduction",
        ),
        DifferenceEstimatorSpec: (
            "spec_version",
            "record_type",
            "estimator_kind",
            "estimator_id",
            "estimator_version",
            "output_metric_id",
            "input_numeric_policy",
            "output_rounding_policy",
            "rounding_stage",
            "input_metric_id",
            "input_arity",
            "operand_order",
            "analysis_unit",
            "weighting",
            "within_cluster_reduction",
        ),
        ProbabilityEstimatorSpec: (
            "spec_version",
            "record_type",
            "estimator_kind",
            "estimator_id",
            "estimator_version",
            "output_metric_id",
            "input_numeric_policy",
            "output_rounding_policy",
            "rounding_stage",
            "predicate",
            "analysis_unit",
            "weighting",
            "denominator_source",
        ),
        QuantileEstimatorSpec: (
            "spec_version",
            "record_type",
            "estimator_kind",
            "estimator_id",
            "estimator_version",
            "output_metric_id",
            "input_numeric_policy",
            "output_rounding_policy",
            "rounding_stage",
            "input_metric_id",
            "analysis_unit",
            "weighting",
            "q",
            "interpolation",
        ),
        PassAllKEstimatorSpec: (
            "spec_version",
            "record_type",
            "estimator_kind",
            "estimator_id",
            "estimator_version",
            "output_metric_id",
            "input_numeric_policy",
            "output_rounding_policy",
            "rounding_stage",
            "predicate",
            "k",
            "analysis_unit",
            "weighting",
            "group_key_fields",
            "group_semantics",
            "incomplete_group_rule",
        ),
        IdentityTransformationSpec: (
            "spec_version",
            "record_type",
            "transformation_kind",
            "input_units",
            "output_units",
            "unit_rule",
        ),
        PlannedPopulationInvalidateMissingnessSpec: (
            "spec_version",
            "record_type",
            "missingness_kind",
            "policy_id",
            "policy_version",
            "coverage_unit",
            "count_reporting_rule",
            "silent_drop_rule",
            "zero_attempt_rule",
            "valid_tie_rule",
            "scientific_target",
            "denominator_treatment",
            "ignorability_assumption",
            "missing_or_invalid_rule",
            "conditional_secondary_rule",
        ),
        CompleteCaseConditionalMissingnessSpec: (
            "spec_version",
            "record_type",
            "missingness_kind",
            "policy_id",
            "policy_version",
            "coverage_unit",
            "count_reporting_rule",
            "silent_drop_rule",
            "zero_attempt_rule",
            "valid_tie_rule",
            "scientific_target",
            "denominator_treatment",
            "minimum_valid_planned_cells",
            "ignorability_assumption",
            "missing_or_invalid_rule",
            "population_primary_claim",
        ),
        BoundsOrSensitivityMissingnessSpec: (
            "spec_version",
            "record_type",
            "missingness_kind",
            "policy_id",
            "policy_version",
            "coverage_unit",
            "count_reporting_rule",
            "silent_drop_rule",
            "zero_attempt_rule",
            "valid_tie_rule",
            "scientific_target",
            "denominator_treatment",
            "method",
            "method_input_schema_ref",
            "assumption_artifact_ref",
            "point_estimate_rule",
        ),
        RaterCoverageSummarySpec: (
            "spec_version",
            "record_type",
            "summary_kind",
            "summary_id",
            "summary_version",
            "denominator",
            "reported_counts",
            "missing_judgment_score_rule",
            "score_effect",
        ),
        RaterDisagreementSummarySpec: (
            "spec_version",
            "record_type",
            "summary_kind",
            "summary_id",
            "summary_version",
            "input_rule",
            "denominator",
            "metric",
            "fewer_than_two_rule",
            "tie_rule",
            "score_effect",
        ),
    }
    by_type = {type(record): record for record in _all_concrete_records()}
    for record_type, fields in expected.items():
        assert tuple(record_type.model_fields) == fields
        assert tuple(by_type[record_type].model_dump(mode="python")) == fields


@pytest.mark.parametrize("record", _all_concrete_records())
def test_every_concrete_record_rejects_normally_constructed_subclasses(record) -> None:
    record_type = type(record)
    extended_type = type(
        f"Extended{record_type.__name__}",
        (record_type,),
        {"__annotations__": {"unauthorized": str}, "__module__": __name__},
    )
    extended = extended_type(
        **record.model_dump(mode="python"), unauthorized="not-authorized"
    )
    with pytest.raises(ValidationError):
        record_type.model_validate(extended)


@pytest.mark.parametrize(
    ("adapter", "record"),
    [
        (TypeAdapter(EstimatorSpec), _mean()),
        (TypeAdapter(EstimatorSpec), _difference()),
        (TypeAdapter(EstimatorSpec), _probability()),
        (TypeAdapter(EstimatorSpec), _quantile()),
        (TypeAdapter(EstimatorSpec), _pass_all_k()),
        (TypeAdapter(EpisodeMissingnessSpec), _planned_missingness()),
        (TypeAdapter(EpisodeMissingnessSpec), _conditional_missingness()),
        (TypeAdapter(EpisodeMissingnessSpec), _bounds_missingness()),
        (TypeAdapter(RaterSummarySpec), _coverage()),
        (TypeAdapter(RaterSummarySpec), _disagreement()),
    ],
)
def test_union_aliases_reject_extended_arm_instances(
    adapter: TypeAdapter, record
) -> None:
    record_type = type(record)
    extended_type = type(
        f"UnionExtended{record_type.__name__}",
        (record_type,),
        {"__annotations__": {"unauthorized": str}, "__module__": __name__},
    )
    extended = extended_type(
        **record.model_dump(mode="python"), unauthorized="not-authorized"
    )
    with pytest.raises(ValidationError):
        adapter.validate_python(extended)


def test_nested_value_and_pin_subclasses_fail_closed() -> None:
    class ExtendedRational(CanonicalRational):
        unauthorized: str

    with pytest.raises(ValidationError):
        _quantile(q=ExtendedRational(numerator=1, denominator=2, unauthorized="x"))

    class LooseImplementation(ImplementationRef):
        content_sha256: str

    loose_implementation = LooseImplementation(
        implementation_id="loose", version="1.0.0", content_sha256="bad"
    )
    with pytest.raises(ValidationError):
        BooleanSuccessPredicateSpec(**_predicate(implementation=loose_implementation))

    class LooseArtifact(ArtifactRef):
        media_type: str

    loose_artifact = LooseArtifact(sha256="a" * 64, media_type=" ", size_bytes=1)
    with pytest.raises(ValidationError):
        _bounds_missingness(assumption_artifact_ref=loose_artifact)


def _assert_analysis_source_is_declaration_only(source: str) -> None:
    tree = ast.parse(textwrap.dedent(source))
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree)
    )
    expected_inventory = (
        ("class", "_StrictValueModel"),
        ("class", "CanonicalRational"),
        ("class", "BooleanSuccessPredicateSpec"),
        ("function", "_validate_estimator_identity"),
        ("function", "_validate_analysis_unit_weighting"),
        ("class", "MeanEstimatorSpec"),
        ("class", "DifferenceEstimatorSpec"),
        ("class", "ProbabilityEstimatorSpec"),
        ("class", "QuantileEstimatorSpec"),
        ("class", "PassAllKEstimatorSpec"),
        ("alias", "EstimatorSpec"),
        ("class", "IdentityTransformationSpec"),
        ("function", "_validate_missingness_identity"),
        ("class", "PlannedPopulationInvalidateMissingnessSpec"),
        ("class", "CompleteCaseConditionalMissingnessSpec"),
        ("class", "BoundsOrSensitivityMissingnessSpec"),
        ("alias", "EpisodeMissingnessSpec"),
        ("class", "RaterCoverageSummarySpec"),
        ("class", "RaterDisagreementSummarySpec"),
        ("alias", "RaterSummarySpec"),
    )
    inventory: list[tuple[str, str]] = []
    alias_nodes: dict[str, ast.Assign] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            assert not node.decorator_list
            inventory.append(("class", node.name))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert not node.decorator_list
            inventory.append(("function", node.name))
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            alias_name = node.targets[0].id
            inventory.append(("alias", alias_name))
            alias_nodes[alias_name] = node
        else:
            raise AssertionError(ast.dump(node, include_attributes=False))
    assert tuple(inventory) == expected_inventory

    def union_arm_names(node: ast.expr) -> tuple[str, ...]:
        if isinstance(node, ast.Name):
            return (node.id,)
        assert isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr)
        return (*union_arm_names(node.left), *union_arm_names(node.right))

    expected_aliases = {
        "EstimatorSpec": (
            (
                "MeanEstimatorSpec",
                "DifferenceEstimatorSpec",
                "ProbabilityEstimatorSpec",
                "QuantileEstimatorSpec",
                "PassAllKEstimatorSpec",
            ),
            "estimator_kind",
        ),
        "EpisodeMissingnessSpec": (
            (
                "PlannedPopulationInvalidateMissingnessSpec",
                "CompleteCaseConditionalMissingnessSpec",
                "BoundsOrSensitivityMissingnessSpec",
            ),
            "missingness_kind",
        ),
        "RaterSummarySpec": (
            ("RaterCoverageSummarySpec", "RaterDisagreementSummarySpec"),
            "summary_kind",
        ),
    }
    assert set(alias_nodes) == set(expected_aliases)
    for alias_name, (expected_arms, expected_discriminator) in expected_aliases.items():
        value = alias_nodes[alias_name].value
        assert (
            isinstance(value, ast.Subscript)
            and isinstance(value.value, ast.Name)
            and value.value.id == "Annotated"
            and isinstance(value.slice, ast.Tuple)
            and len(value.slice.elts) == 2
        )
        union_node, field_node = value.slice.elts
        assert union_arm_names(union_node) == expected_arms
        assert (
            isinstance(field_node, ast.Call)
            and isinstance(field_node.func, ast.Name)
            and field_node.func.id == "Field"
            and not field_node.args
            and len(field_node.keywords) == 1
            and field_node.keywords[0].arg == "discriminator"
            and isinstance(field_node.keywords[0].value, ast.Constant)
            and field_node.keywords[0].value.value == expected_discriminator
        )

    allowed_calls = {
        "ConfigDict",
        "Field",
        "ValueError",
        "abs",
        "enumerate",
        "gcd",
        "handler",
        "isinstance",
        "len",
        "model_validator",
        "set",
        "sorted",
        "tuple",
        "type",
        "_require_non_empty",
        "_require_semver",
        "_validate_analysis_unit_weighting",
        "_validate_estimator_identity",
        "_validate_missingness_identity",
        "_validate_planned_artifact",
        "_validate_planned_implementation",
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute):
            assert (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "allowed"
                and node.func.attr == "get"
            ), ast.unparse(node.func)
            continue
        assert isinstance(node.func, ast.Name), ast.unparse(node.func)
        assert node.func.id in allowed_calls, node.func.id

    expected_attributes = {
        "allowed.get",
        "coordinate_order.__getitem__",
        "self.analysis_unit",
        "self.assumption_artifact_ref",
        "self.denominator",
        "self.estimator_id",
        "self.estimator_version",
        "self.group_key_fields",
        "self.implementation",
        "self.input_arity",
        "self.input_metric_id",
        "self.input_schema_ref",
        "self.input_units",
        "self.method",
        "self.method_input_schema_ref",
        "self.numerator",
        "self.output_metric_id",
        "self.output_units",
        "self.policy_id",
        "self.policy_version",
        "self.predicate_id",
        "self.predicate_version",
        "self.q",
        "self.q.denominator",
        "self.q.numerator",
        "self.summary_id",
        "self.summary_version",
        "self.weighting",
        "self.within_cluster_reduction",
    }
    actual_attributes = {
        ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert actual_attributes == expected_attributes
    forbidden_names = {
        "__builtins__",
        "__import__",
        "builtins",
        "compile",
        "delattr",
        "eval",
        "exec",
        "filesystem",
        "getattr",
        "globals",
        "importlib",
        "locals",
        "open",
        "os",
        "pathlib",
        "provider",
        "requests",
        "runtime",
        "setattr",
        "socket",
        "subprocess",
        "sys",
        "vars",
    }
    loaded_names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    assert loaded_names.isdisjoint(forbidden_names)


def _analysis_declaration_source() -> str:
    source = inspect.getsource(records_module)
    tree = ast.parse(source)
    start = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "_StrictValueModel"
    )
    end = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ValidityDomainSpec"
    )
    lines = source.splitlines(keepends=True)
    return "".join(lines[start.lineno - 1 : end.lineno - 1])


def _replace_top_level_alias(source: str, alias: str, replacement: str) -> str:
    tree = ast.parse(source)
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.Assign)
        and len(item.targets) == 1
        and isinstance(item.targets[0], ast.Name)
        and item.targets[0].id == alias
    )
    lines = source.splitlines(keepends=True)
    return "".join(
        (
            *lines[: node.lineno - 1],
            f"{alias} = {replacement}\n",
            *lines[node.end_lineno :],
        )
    )


def test_task_1_1b4a_added_source_is_provider_and_runtime_free() -> None:
    added = _analysis_declaration_source()
    _assert_analysis_source_is_declaration_only(added)

    mutation = added.replace(
        "        return self",
        "        filesystem.runtime_call()\n        return self",
        1,
    )
    with pytest.raises(AssertionError):
        _assert_analysis_source_is_declaration_only(mutation)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda source: "x = runtime.filesystem\n" + source,
        lambda source: source.replace(
            "class CanonicalRational", "@runtime.hook\nclass CanonicalRational", 1
        ),
        lambda source: source.replace(
            "class CanonicalRational",
            '@model_validator(mode="after")\nclass CanonicalRational',
            1,
        ),
        lambda source: "x = __builtins__.open\n" + source,
        lambda source: source.replace(
            "class MeanEstimatorSpec", "class RenamedMeanEstimatorSpec", 1
        ),
    ],
)
def test_source_guard_rejects_capability_and_inventory_mutations(mutation) -> None:
    added = _analysis_declaration_source()
    with pytest.raises(AssertionError):
        _assert_analysis_source_is_declaration_only(mutation(added))


@pytest.mark.parametrize(
    "replacement",
    [
        "None",
        'type("X", (), {})',
        (
            "Annotated[DifferenceEstimatorSpec | MeanEstimatorSpec | "
            "ProbabilityEstimatorSpec | QuantileEstimatorSpec | "
            "PassAllKEstimatorSpec, Field(discriminator='estimator_kind')]"
        ),
        (
            "Annotated[MeanEstimatorSpec | DifferenceEstimatorSpec | "
            "ProbabilityEstimatorSpec | QuantileEstimatorSpec | "
            "PassAllKEstimatorSpec, Field(discriminator='wrong_kind')]"
        ),
    ],
)
def test_source_guard_rejects_union_alias_rhs_replacement(replacement: str) -> None:
    added = _analysis_declaration_source()
    mutation = _replace_top_level_alias(added, "EstimatorSpec", replacement)
    with pytest.raises(AssertionError):
        _assert_analysis_source_is_declaration_only(mutation)


def _schema_property_names(schema: object) -> set[str]:
    if isinstance(schema, dict):
        names = set(schema.get("properties", {}))
        for value in schema.values():
            names.update(_schema_property_names(value))
        return names
    if isinstance(schema, list):
        names: set[str] = set()
        for value in schema:
            names.update(_schema_property_names(value))
        return names
    return set()


def test_task_1_1b4a_schemas_exclude_later_owned_runtime_and_inference_fields() -> None:
    schemas = [type(record).model_json_schema() for record in _all_concrete_records()]
    schemas.extend(
        TypeAdapter(alias).json_schema()
        for alias in (EstimatorSpec, EpisodeMissingnessSpec, RaterSummarySpec)
    )
    properties = set().union(*(_schema_property_names(schema) for schema in schemas))
    assert properties.isdisjoint(
        {
            "analysis_result",
            "assignment_artifact_ref",
            "attempt_id",
            "cluster_design_id",
            "interval",
            "multiplicity",
            "p_value",
            "pairing_id",
            "provider_call_id",
            "receipt_id",
            "score_aggregation",
        }
    )


@pytest.mark.parametrize(
    ("source_name", "estimator", "missingness", "rater_summary"),
    [
        ("tau3-state", _probability(), _planned_missingness(), None),
        ("econ-scheduling", _mean(), _conditional_missingness(), None),
        ("terms", _probability(), _planned_missingness(), _coverage()),
        ("gdpval", _probability(), _planned_missingness(), _disagreement()),
        ("housing", _difference(), _planned_missingness(), None),
    ],
)
def test_representative_benchmarks_only_pressure_constructor_shapes(
    source_name: str,
    estimator,
    missingness,
    rater_summary,
) -> None:
    assert source_name
    assert isinstance(
        estimator,
        (MeanEstimatorSpec, DifferenceEstimatorSpec, ProbabilityEstimatorSpec),
    )
    assert missingness.coverage_unit == "planned_cell"
    if rater_summary is not None:
        assert rater_summary.score_effect == "none_descriptive_only"
