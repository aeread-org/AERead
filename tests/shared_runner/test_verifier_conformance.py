"""Provider-free conformance tests for reusable measurement-leaf records."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import re
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

import aeread.sdk.v1 as sdk
from aeread.sdk.v1 import (
    AbsoluteToleranceSpec,
    ArtifactRef,
    ArtifactReferenceSource,
    AxiomRelationReference,
    BaselineDeltaReference,
    BlindOrderSpec,
    CanonicalPointReference,
    CanonicalReferenceVerifier,
    CanonicalSetReference,
    CasePayloadReferenceSource,
    ComparativeReferenceVerifier,
    ConstraintSatisfactionReference,
    DistanceToCanonicalSetReference,
    EstimandSpec,
    ExactPointMatchSpec,
    EvaluatorAgentRaterSource,
    FieldRatingReference,
    HeadToHeadReference,
    HumanReferenceComparison,
    ImplementationRef,
    ImportedHumanRaterSource,
    MeasurementLeafSpec,
    MetamorphicRelationReference,
    ObjectiveBaselineClaim,
    ObjectiveBaselineReference,
    ObjectiveBoundClaim,
    ObjectiveExactClaim,
    ObjectiveExactReference,
    ObjectiveLowerBoundReference,
    ObjectiveReferenceVerifier,
    ObjectiveScopeSpec,
    ObjectiveSupportClaim,
    ObjectiveSupportMaxReference,
    ObjectiveSupportMinReference,
    ObjectiveUpperBoundReference,
    ObjectiveValueOnlyClaim,
    ObjectiveValueReference,
    PairedComparisonReference,
    PreOutcomeComputationSource,
    RaterInputSpec,
    RaterJudgeVerifier,
    RaterScoreResult,
    RaterTieResult,
    RelativeToleranceSpec,
    RuleConstraintVerifier,
    StateInvariantReference,
    TemporalPropertyReference,
    TerminalStateEquivalenceReference,
    TolerancePointMatchSpec,
    ValidityDomainSpec,
    content_sha256,
)


def _implementation(name: str, marker: str = "1") -> ImplementationRef:
    return ImplementationRef(
        implementation_id=name,
        version="1.0.0",
        content_sha256=marker * 64,
    )


def _artifact(marker: str, media_type: str = "application/json") -> ArtifactRef:
    return ArtifactRef(sha256=marker * 64, media_type=media_type, size_bytes=10)


def _case_source() -> CasePayloadReferenceSource:
    return CasePayloadReferenceSource(
        source_kind="case_payload",
        path="references/target.json",
        schema_ref="canonical-target/1",
    )


def _domain() -> ValidityDomainSpec:
    return ValidityDomainSpec(
        domain_id="dev-cases",
        domain_version="1.0.0",
        schema_ref="validity-domain/1",
        predicate=_implementation("validity_predicate", "2"),
        parameters=(_artifact("3"),),
    )


def _estimand(
    *,
    estimand_id: str = "allocation-quality",
    input_scope: str = "terminal_state",
    direction: str = "maximize",
    units: str = "utility_points",
    validity_domain: ValidityDomainSpec | None = None,
) -> EstimandSpec:
    return EstimandSpec(
        estimand_id=estimand_id,
        estimand_version="1.0.0",
        input_scope=input_scope,
        direction=direction,
        units=units,
        quantity_schema_ref=f"{estimand_id}/1",
        validity_domain=validity_domain or _domain(),
    )


def _scope() -> ObjectiveScopeSpec:
    return ObjectiveScopeSpec(
        objective_id="allocation-value",
        objective_version="1.0.0",
        direction="maximize",
        source_direction="maximize",
        source_to_canonical_rule="identity",
        units="utility_points",
        feasible_set="declared allocations",
        information_set="candidate-visible observations",
        horizon="one episode",
        environment_condition="housing-v1 fixed cases",
        opponent_condition="scripted landlord v1",
        stochastic_expectation="expectation over declared world randomness",
        validity_domain=_domain(),
    )


def _compatible_estimand(verifier: object) -> EstimandSpec:
    if isinstance(verifier, CanonicalReferenceVerifier):
        return _estimand(
            estimand_id="canonical-correctness",
            input_scope=verifier.reference.input_scope,
            units=verifier.reference.units,
        )
    if isinstance(verifier, RuleConstraintVerifier):
        return _estimand(
            estimand_id="rule-satisfaction",
            input_scope=verifier.reference.input_scope,
            units="rule_pass",
        )
    if isinstance(verifier, ObjectiveReferenceVerifier):
        return _estimand(
            estimand_id=verifier.scope.objective_id,
            input_scope="terminal_state",
            direction=verifier.scope.direction,
            units=verifier.scope.units,
            validity_domain=verifier.scope.validity_domain,
        )
    if isinstance(verifier, ComparativeReferenceVerifier):
        return _estimand(
            estimand_id="comparative-effect",
            input_scope=verifier.reference.input_scope,
            direction=verifier.reference.direction,
            units=verifier.reference.units,
            validity_domain=verifier.reference.validity_domain,
        )
    if isinstance(verifier, RaterJudgeVerifier):
        scope = (
            "terminal_state"
            if verifier.input.input_scope == "outcome"
            else verifier.input.input_scope
        )
        return _estimand(
            estimand_id="rater-assessment",
            input_scope=scope,
            units="rubric_points",
        )
    raise AssertionError(f"unsupported verifier fixture: {type(verifier).__name__}")


def _leaf(
    verifier: object,
    classes: tuple[str, ...],
    *,
    estimand: EstimandSpec | None = None,
) -> MeasurementLeafSpec:
    return MeasurementLeafSpec(
        leaf_id="allocation-quality-leaf",
        leaf_version="1.0.0",
        composition_kind="leaf",
        estimand=estimand or _compatible_estimand(verifier),
        verifier=verifier,
        allowed_evaluation_classes=classes,
        scorer=_implementation("allocation_scorer", "4"),
    )


def _canonical_references() -> tuple[object, ...]:
    common = {
        "reference_id": "canonical-answer",
        "reference_version": "1.0.0",
        "input_schema_ref": "answer/1",
        "units": "label",
        "source": _case_source(),
    }
    return (
        CanonicalPointReference(
            reference_kind="canonical_point",
            input_scope="answer",
            canonicalizer=_implementation("canonicalize_answer", "5"),
            match=ExactPointMatchSpec(match_kind="exact"),
            **common,
        ),
        CanonicalSetReference(
            reference_kind="canonical_set",
            input_scope="answer",
            canonicalizer=_implementation("canonicalize_answer", "5"),
            membership=_implementation("set_membership", "6"),
            match_kind="exact",
            **common,
        ),
        TerminalStateEquivalenceReference(
            reference_kind="terminal_state_equivalence",
            input_scope="terminal_state",
            equivalence=_implementation("state_equivalence", "7"),
            **common,
        ),
        DistanceToCanonicalSetReference(
            reference_kind="distance_to_canonical_set",
            input_scope="terminal_state",
            canonicalizer=_implementation("canonicalize_state", "8"),
            distance=_implementation("state_distance", "9"),
            tolerance=AbsoluteToleranceSpec(
                tolerance_kind="absolute", value=0.01, units="label"
            ),
            **common,
        ),
    )


def _rule_references() -> tuple[object, ...]:
    common = {
        "reference_id": "economic-rule",
        "reference_version": "1.0.0",
        "result_schema_ref": "rule-result/1",
        "result_semantics": "pass_vector_and_residual",
        "residual_schema_ref": "constraint-residual/1",
        "source": _case_source(),
    }
    return (
        ConstraintSatisfactionReference(
            reference_kind="constraint_satisfaction",
            input_scope="answer",
            checkpoint_scope="answer",
            predicate=_implementation("constraint_predicate", "a"),
            **common,
        ),
        StateInvariantReference(
            reference_kind="state_invariant",
            input_scope="trajectory",
            checkpoint_scope="every_state",
            predicate=_implementation("state_invariant", "b"),
            **common,
        ),
        TemporalPropertyReference(
            reference_kind="temporal_property",
            input_scope="trajectory",
            checkpoint_scope="whole_trajectory",
            ordering="event_sequence",
            predicate=_implementation("temporal_property", "c"),
            **common,
        ),
        AxiomRelationReference(
            reference_kind="axiom_relation",
            input_scope="terminal_state",
            checkpoint_scope="final_state",
            relation=_implementation("axiom_relation", "d"),
            **common,
        ),
        MetamorphicRelationReference(
            reference_kind="metamorphic_relation",
            input_scope="distribution",
            checkpoint_scope="related_cases",
            relation_scope="related_cases_or_reruns",
            relation=_implementation("metamorphic_relation", "e"),
            **common,
        ),
    )


def _objective_reference(cls: type, reference_kind: str, **extra: object) -> object:
    return cls(
        reference_kind=reference_kind,
        reference_id=f"allocation-{reference_kind}",
        reference_version="1.0.0",
        scope=_scope(),
        proof_type="pinned exact implementation",
        source=_case_source(),
        **extra,
    )


def _comparative_references() -> tuple[object, ...]:
    common = {
        "reference_id": "comparison-reference",
        "reference_version": "1.0.0",
        "input_scope": "distribution",
        "comparator": _implementation("comparison", "f"),
        "population_schema_ref": "population/1",
        "role_precondition": "candidate role only",
        "matching_precondition": "same case and declared counterpart",
        "units": "win_probability",
        "direction": "maximize",
        "validity_domain": _domain(),
        "provenance_schema_ref": "comparison-provenance/1",
        "source": _case_source(),
    }
    return tuple(
        cls(reference_kind=kind, **common)
        for cls, kind in (
            (BaselineDeltaReference, "baseline_delta"),
            (PairedComparisonReference, "paired_comparison"),
            (HeadToHeadReference, "head_to_head"),
            (HumanReferenceComparison, "human_reference"),
            (FieldRatingReference, "field_rating"),
        )
    )


def _rater() -> RaterJudgeVerifier:
    return RaterJudgeVerifier(
        verifier_family="rater_judge",
        verifier_id="blind-rater",
        verifier_version="1.0.0",
        protocol_id="blind-pairwise",
        protocol_version="1.0.0",
        rubric_ref=_artifact("4", "text/markdown"),
        prompt_ref=_artifact("5", "text/plain"),
        input=RaterInputSpec(
            input_scope="trajectory",
            visibility="evaluator_authorized",
            projection=_implementation("rater_projection", "6"),
            renderer=_implementation("rater_renderer", "7"),
            rendered_schema_ref="rendered-rater-input/1",
        ),
        rater_source=EvaluatorAgentRaterSource(
            source_kind="evaluator_agent",
            evaluator_protocol_id="judge-agent-contract",
            evaluator_protocol_version="1.0.0",
            adapter_contract=_implementation("judge_adapter_contract", "8"),
        ),
        blind_order=BlindOrderSpec(
            algorithm=_implementation("blind_order", "9"),
            seed_input="evaluation_seed",
            counterbalance_input="counterbalance_label",
            position_schema_ref="blind-position/1",
        ),
        calibration_refs=(_artifact("a"),),
        provenance_refs=(_artifact("b"),),
        result_schema_ref="rater-score/1",
        valid_tie_schema_ref="rater-tie/1",
        disagreement_schema_ref="rater-disagreement/1",
    )


@pytest.mark.parametrize("reference", _canonical_references())
def test_every_canonical_reference_kind_validates(reference: object) -> None:
    leaf = _leaf(
        CanonicalReferenceVerifier(
            verifier_family="canonical_reference",
            verifier_id="canonical-verifier",
            verifier_version="1.0.0",
            reference=reference,
        ),
        ("deterministic",),
    )
    assert MeasurementLeafSpec.model_validate(leaf.model_dump(mode="json")) == leaf


@pytest.mark.parametrize("reference", _rule_references())
def test_every_rule_reference_kind_validates(reference: object) -> None:
    leaf = _leaf(
        RuleConstraintVerifier(
            verifier_family="rule_constraint",
            verifier_id="rule-verifier",
            verifier_version="1.0.0",
            reference=reference,
        ),
        ("deterministic",),
    )
    assert MeasurementLeafSpec.model_validate(leaf.model_dump(mode="json")) == leaf


@pytest.mark.parametrize("reference", _comparative_references())
def test_every_comparative_reference_kind_validates(reference: object) -> None:
    leaf = _leaf(
        ComparativeReferenceVerifier(
            verifier_family="comparative",
            verifier_id="comparative-verifier",
            verifier_version="1.0.0",
            reference=reference,
        ),
        ("stochastic_estimator",),
    )
    assert MeasurementLeafSpec.model_validate(leaf.model_dump(mode="json")) == leaf


def test_every_objective_claim_kind_validates() -> None:
    exact = ObjectiveExactClaim(
        claim_kind="exact",
        certification_rule="exact_reference_match",
        exact=_objective_reference(ObjectiveExactReference, "exact_value"),
    )
    bound = ObjectiveBoundClaim(
        claim_kind="bound",
        bound_status="bracketed",
        certification_rule="certified_lower_le_optimum_le_upper",
        lower_bound=_objective_reference(ObjectiveLowerBoundReference, "lower_bound"),
        upper_bound=_objective_reference(ObjectiveUpperBoundReference, "upper_bound"),
    )
    baseline = ObjectiveBaselineClaim(
        claim_kind="baseline",
        certification_rule="comparison_against_pinned_baseline",
        baseline=_objective_reference(
            ObjectiveBaselineReference,
            "comparison_baseline",
            comparison_id="naive-policy",
            comparison_version="1.0.0",
        ),
    )
    support = ObjectiveSupportClaim(
        claim_kind="support",
        certification_rule="support_min_lte_outcome_lte_support_max",
        support_min=_objective_reference(ObjectiveSupportMinReference, "support_min"),
        support_max=_objective_reference(ObjectiveSupportMaxReference, "support_max"),
    )
    value_only = ObjectiveValueOnlyClaim(
        claim_kind="value_only",
        certification_rule="no_optimality_or_comparison_claim",
        value=_objective_reference(ObjectiveValueReference, "value_only"),
    )
    for claim in (exact, bound, baseline, support, value_only):
        leaf = _leaf(
            ObjectiveReferenceVerifier(
                verifier_family="objective_reference",
                verifier_id="objective-verifier",
                verifier_version="1.0.0",
                scope=_scope(),
                claim=claim,
            ),
            ("deterministic", "stochastic_estimator"),
        )
        assert MeasurementLeafSpec.model_validate(leaf.model_dump(mode="json")) == leaf


def test_minimal_rater_leaf_and_typed_valid_tie_validate() -> None:
    leaf = _leaf(_rater(), ("judge_dependent",))
    tie = RaterTieResult(
        result_kind="valid_tie", schema_ref=leaf.verifier.valid_tie_schema_ref
    )
    score = RaterScoreResult(
        result_kind="score", value=0.75, schema_ref=leaf.verifier.result_schema_ref
    )
    assert tie.result_kind == "valid_tie"
    assert score.value == 0.75


def test_non_rater_dual_mode_round_trip_and_hash_are_stable() -> None:
    verifier = CanonicalReferenceVerifier(
        verifier_family="canonical_reference",
        verifier_id="canonical-verifier",
        verifier_version="1.0.0",
        reference=_canonical_references()[0],
    )
    leaf = _leaf(verifier, ("deterministic", "stochastic_estimator"))
    digest = content_sha256(leaf)
    round_tripped = MeasurementLeafSpec.model_validate(leaf.model_dump(mode="json"))
    assert round_tripped.allowed_evaluation_classes == (
        "deterministic",
        "stochastic_estimator",
    )
    assert content_sha256(round_tripped) == digest


@pytest.mark.parametrize(
    "classes",
    [
        (),
        ("deterministic", "deterministic"),
        ("stochastic_estimator", "deterministic"),
        ("judge_dependent",),
        ("deterministic", "judge_dependent"),
    ],
)
def test_non_rater_rejects_empty_duplicate_noncanonical_or_judge_modes(
    classes: tuple[str, ...],
) -> None:
    verifier = CanonicalReferenceVerifier(
        verifier_family="canonical_reference",
        verifier_id="canonical-verifier",
        verifier_version="1.0.0",
        reference=_canonical_references()[0],
    )
    with pytest.raises(ValidationError):
        _leaf(verifier, classes)


@pytest.mark.parametrize(
    "classes",
    [
        ("deterministic",),
        ("stochastic_estimator",),
        ("judge_dependent", "judge_dependent"),
    ],
)
def test_rater_allows_exactly_judge_dependent(classes: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        _leaf(_rater(), classes)


def test_objective_reference_scope_must_match_every_field_exactly() -> None:
    outer_scope = _scope()
    reference = _objective_reference(ObjectiveExactReference, "exact_value")
    base = reference.scope.model_dump(mode="python")
    mutations: Mapping[str, Mapping[str, object]] = {
        "objective_id": {"objective_id": "other-objective"},
        "objective_version": {"objective_version": "1.0.1"},
        "source_direction": {
            "source_direction": "minimize",
            "source_to_canonical_rule": "negate",
        },
        "source_to_canonical_rule": {
            "source_direction": "minimize",
            "source_to_canonical_rule": "negate",
        },
        "units": {"units": "usd"},
        "feasible_set": {"feasible_set": "other policies"},
        "information_set": {"information_set": "full information"},
        "horizon": {"horizon": "two episodes"},
        "environment_condition": {"environment_condition": "other env"},
        "opponent_condition": {"opponent_condition": "other opponent"},
        "stochastic_expectation": {"stochastic_expectation": "none"},
        "validity_domain": {
            "validity_domain": ValidityDomainSpec(
                **{
                    **_domain().model_dump(mode="python"),
                    "domain_id": "other-domain",
                }
            )
        },
    }
    for field_name, updates in mutations.items():
        mutated_scope = ObjectiveScopeSpec.model_validate({**base, **updates})
        mutated_reference = reference.model_copy(update={"scope": mutated_scope})
        with pytest.raises(ValidationError, match="scope"):
            ObjectiveReferenceVerifier.model_validate(
                {
                    "verifier_family": "objective_reference",
                    "verifier_id": "objective-verifier",
                    "verifier_version": "1.0.0",
                    "scope": outer_scope.model_dump(mode="python"),
                    "claim": {
                        "claim_kind": "exact",
                        "certification_rule": "exact_reference_match",
                        "exact": mutated_reference.model_dump(mode="python"),
                    },
                }
            )


def test_objective_bound_and_claim_invariants_fail_closed() -> None:
    lower = _objective_reference(ObjectiveLowerBoundReference, "lower_bound")
    upper = _objective_reference(ObjectiveUpperBoundReference, "upper_bound")
    invalid_claims = (
        {
            "claim_kind": "bound",
            "bound_status": "bracketed",
            "certification_rule": "certified_lower_le_optimum_le_upper",
            "lower_bound": lower,
        },
        {
            "claim_kind": "bound",
            "bound_status": "lower_bound_only",
            "certification_rule": "feasible_witness_lower_bounds_optimum",
            "lower_bound": lower,
            "upper_bound": upper,
        },
        {
            "claim_kind": "bound",
            "bound_status": "epsilon_solved",
            "certification_rule": "computed_bound_gap_lte_epsilon",
            "lower_bound": lower,
            "upper_bound": upper,
        },
        {
            "claim_kind": "bound",
            "bound_status": "bracketed",
            "certification_rule": "certified_lower_le_optimum_le_upper",
            "lower_bound": lower,
            "upper_bound": upper,
            "epsilon": 0.1,
            "epsilon_units": "utility_points",
        },
        {
            "claim_kind": "bound",
            "bound_status": "bracketed",
            "certification_rule": "computed_bound_gap_eq_zero",
            "lower_bound": lower,
            "upper_bound": upper,
        },
    )
    for claim in invalid_claims:
        with pytest.raises(ValidationError):
            ObjectiveBoundClaim.model_validate(claim)

    with pytest.raises(ValidationError):
        ObjectiveSupportClaim.model_validate(
            {
                "claim_kind": "support",
                "certification_rule": "support_min_lte_outcome_lte_support_max",
                "support_min": _objective_reference(
                    ObjectiveSupportMinReference, "support_min"
                ),
            }
        )
    with pytest.raises(ValidationError):
        ObjectiveBaselineClaim.model_validate(
            {
                "claim_kind": "baseline",
                "certification_rule": "comparison_against_pinned_baseline",
                "lower_bound": lower,
            }
        )

    duplicate_identity_upper = ObjectiveUpperBoundReference(
        **{
            **upper.model_dump(mode="python"),
            "reference_id": lower.reference_id,
            "reference_version": lower.reference_version,
        }
    )
    with pytest.raises(ValidationError, match="identities"):
        ObjectiveReferenceVerifier(
            verifier_family="objective_reference",
            verifier_id="objective-verifier",
            verifier_version="1.0.0",
            scope=_scope(),
            claim=ObjectiveBoundClaim(
                claim_kind="bound",
                bound_status="bracketed",
                certification_rule="certified_lower_le_optimum_le_upper",
                lower_bound=lower,
                upper_bound=duplicate_identity_upper,
            ),
        )


def test_rater_rejects_ambiguous_source_and_unpinned_required_inputs() -> None:
    valid = _rater().model_dump(mode="python")
    invalid_payloads = []
    for field_name in (
        "rubric_ref",
        "prompt_ref",
        "input",
        "blind_order",
        "calibration_refs",
        "provenance_refs",
        "result_schema_ref",
        "valid_tie_schema_ref",
        "disagreement_schema_ref",
    ):
        invalid_payloads.append(
            {key: value for key, value in valid.items() if key != field_name}
        )
    invalid_payloads.extend(
        (
            {
                **valid,
                "rater_source": {
                    "source_kind": "ambiguous",
                    "evaluator_protocol_id": "x",
                },
            },
            {
                **valid,
                "input": {
                    **valid["input"],
                    "visibility": {"roles": ["judge"]},
                },
            },
        )
    )
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            RaterJudgeVerifier.model_validate(payload)

    imported = ImportedHumanRaterSource(
        source_kind="imported_human",
        evidence_source=ArtifactReferenceSource(
            source_kind="artifacts", artifacts=(_artifact("c"),)
        ),
        import_validator=_implementation("human_evidence_import", "d"),
        evidence_schema_ref="human-judgments/1",
    )
    assert imported.source_kind == "imported_human"


@pytest.mark.parametrize(
    "path",
    ["", ".", "..", "/absolute", "a//b", "a/./b", "a/../b", "a/", "a\\b"],
)
def test_case_payload_source_rejects_empty_traversal_or_empty_segments(
    path: str,
) -> None:
    with pytest.raises(ValidationError):
        CasePayloadReferenceSource(
            source_kind="case_payload", path=path, schema_ref="target/1"
        )


def test_reference_sources_are_strict_pinned_and_canonical() -> None:
    first, second = _artifact("1"), _artifact("2")
    source = ArtifactReferenceSource(source_kind="artifacts", artifacts=(first, second))
    assert source.artifacts == (first, second)
    for artifacts in ((), (first, first), (second, first)):
        with pytest.raises(ValidationError):
            ArtifactReferenceSource(source_kind="artifacts", artifacts=artifacts)

    computation = PreOutcomeComputationSource(
        source_kind="pre_outcome_computation",
        determinism="pure_deterministic",
        implementation=_implementation("precompute", "3"),
        allowed_inputs=("case_payload", "reference_artifacts"),
        output_schema_ref="computed-reference/1",
        input_artifacts=(first,),
    )
    assert computation.allowed_inputs == ("case_payload", "reference_artifacts")
    with pytest.raises(ValidationError):
        PreOutcomeComputationSource(
            **{
                **computation.model_dump(mode="python"),
                "allowed_inputs": ("reference_artifacts", "case_payload"),
            }
        )

    relative = RelativeToleranceSpec(tolerance_kind="relative", value=0.05)
    assert (
        TypeAdapter(sdk.ToleranceSpec).validate_python(
            relative.model_dump(mode="python")
        )
        == relative
    )
    with pytest.raises(ValidationError):
        PreOutcomeComputationSource(
            **{
                **computation.model_dump(mode="python"),
                "allowed_inputs": ("case_payload",),
            }
        )


@pytest.mark.parametrize("alias", ["latest", "current", "default", "stable"])
def test_new_semantic_versions_reject_symbolic_aliases(alias: str) -> None:
    objects = (
        (_domain(), "domain_version"),
        (_estimand(), "estimand_version"),
        (_canonical_references()[0], "reference_version"),
        (_rater(), "protocol_version"),
        (
            _leaf(
                CanonicalReferenceVerifier(
                    verifier_family="canonical_reference",
                    verifier_id="canonical-verifier",
                    verifier_version="1.0.0",
                    reference=_canonical_references()[0],
                ),
                ("deterministic",),
            ),
            "leaf_version",
        ),
    )
    for record, field_name in objects:
        payload = record.model_dump(mode="python")
        payload[field_name] = alias
        with pytest.raises(ValidationError):
            type(record).model_validate(payload)


def test_records_reject_neighbors_unknown_discriminators_missing_and_extras() -> None:
    canonical = CanonicalReferenceVerifier(
        verifier_family="canonical_reference",
        verifier_id="canonical-verifier",
        verifier_version="1.0.0",
        reference=_canonical_references()[0],
    )
    payload = canonical.model_dump(mode="python")
    payload["claim"] = {"claim_kind": "value_only"}
    with pytest.raises(ValidationError):
        CanonicalReferenceVerifier.model_validate(payload)

    leaf = _leaf(canonical, ("deterministic",))
    for field_name in (
        "leaf_id",
        "leaf_version",
        "estimand",
        "verifier",
        "allowed_evaluation_classes",
        "scorer",
    ):
        missing = leaf.model_dump(mode="python")
        missing.pop(field_name)
        with pytest.raises(ValidationError):
            MeasurementLeafSpec.model_validate(missing)
    bad = leaf.model_dump(mode="python")
    bad["verifier"]["verifier_family"] = "unknown_family"
    with pytest.raises(ValidationError):
        MeasurementLeafSpec.model_validate(bad)

    bad = canonical.model_dump(mode="python")
    bad["reference"]["reference_kind"] = "unknown_reference"
    with pytest.raises(ValidationError):
        CanonicalReferenceVerifier.model_validate(bad)
    with pytest.raises(ValidationError):
        TypeAdapter(sdk.ReferenceSource).validate_python(
            {"source_kind": "unknown_source"}
        )
    bad = leaf.model_dump(mode="python")
    bad["suite_pairing"] = "forbidden"
    with pytest.raises(ValidationError):
        MeasurementLeafSpec.model_validate(bad)


@pytest.mark.parametrize(
    ("record", "field_name"),
    [
        (_domain(), "domain_id"),
        (_estimand(), "estimand_id"),
        (_canonical_references()[0], "reference_id"),
        (_rater(), "protocol_id"),
    ],
)
def test_new_record_identifiers_reject_empty_values(
    record: object, field_name: str
) -> None:
    payload = record.model_dump(mode="python")
    payload[field_name] = ""
    with pytest.raises(ValidationError):
        type(record).model_validate(payload)


def test_rater_implementation_and_artifact_pins_fail_closed() -> None:
    for container, field_name in (
        ("input", "projection"),
        ("input", "renderer"),
        ("blind_order", "algorithm"),
    ):
        invalid = _rater().model_dump(mode="python")
        invalid[container][field_name]["version"] = "latest"
        with pytest.raises(ValidationError):
            RaterJudgeVerifier.model_validate(invalid)
    for field_name in ("calibration_refs", "provenance_refs"):
        invalid = _rater().model_dump(mode="python")
        invalid[field_name][0]["sha256"] = "not-a-digest"
        with pytest.raises(ValidationError):
            RaterJudgeVerifier.model_validate(invalid)


def test_round_trip_immutability_schema_discriminators_and_unsafe_revalidation() -> None:
    leaf = _leaf(
        CanonicalReferenceVerifier(
            verifier_family="canonical_reference",
            verifier_id="canonical-verifier",
            verifier_version="1.0.0",
            reference=_canonical_references()[0],
        ),
        ("deterministic",),
    )
    with pytest.raises(ValidationError):
        leaf.leaf_id = "changed"

    schema = MeasurementLeafSpec.model_json_schema()
    assert schema["properties"]["leaf_version"]
    assert "leaf_version" in schema["required"]
    verifier_schema = TypeAdapter(sdk.VerifierSpec).json_schema()
    assert verifier_schema["discriminator"]["propertyName"] == "verifier_family"
    source_schema = TypeAdapter(sdk.ReferenceSource).json_schema()
    assert source_schema["discriminator"]["propertyName"] == "source_kind"
    for alias, discriminator in (
        (sdk.CanonicalReference, "reference_kind"),
        (sdk.RuleReference, "reference_kind"),
        (sdk.ComparativeReference, "reference_kind"),
        (sdk.ObjectiveClaim, "claim_kind"),
        (sdk.PointMatchSpec, "match_kind"),
        (sdk.RaterSource, "source_kind"),
        (sdk.RaterResult, "result_kind"),
        (sdk.ToleranceSpec, "tolerance_kind"),
    ):
        assert (
            TypeAdapter(alias).json_schema()["discriminator"]["propertyName"]
            == discriminator
        )
    definitions = schema["$defs"]
    for record_name, version_field in (
        ("EstimandSpec", "estimand_version"),
        ("ValidityDomainSpec", "domain_version"),
        ("CanonicalPointReference", "reference_version"),
        ("RaterJudgeVerifier", "protocol_version"),
    ):
        assert version_field in definitions[record_name]["required"]

    copied = leaf.model_copy(update={"allowed_evaluation_classes": ()})
    copied_raw = copied.model_dump(mode="python")
    assert copied_raw["allowed_evaluation_classes"] == ()
    with pytest.raises(ValidationError):
        MeasurementLeafSpec.model_validate(copied_raw)

    constructed = MeasurementLeafSpec.model_construct(
        leaf_id=leaf.leaf_id,
        leaf_version=leaf.leaf_version,
        composition_kind=leaf.composition_kind,
        estimand=leaf.estimand,
        verifier=leaf.verifier,
        allowed_evaluation_classes=("judge_dependent",),
        scorer=leaf.scorer,
    )
    constructed_raw = constructed.model_dump(mode="python")
    assert constructed_raw["allowed_evaluation_classes"] == ("judge_dependent",)
    with pytest.raises(ValidationError):
        MeasurementLeafSpec.model_validate(constructed_raw)

    missing = MeasurementLeafSpec.model_construct(
        leaf_id=leaf.leaf_id,
        leaf_version=leaf.leaf_version,
        composition_kind=leaf.composition_kind,
        estimand=leaf.estimand,
        verifier=leaf.verifier,
        allowed_evaluation_classes=leaf.allowed_evaluation_classes,
    )
    missing_raw = missing.model_dump(mode="python")
    assert "scorer" not in missing_raw
    with pytest.raises(ValidationError):
        MeasurementLeafSpec.model_validate(missing_raw)


def test_leaf_records_and_exports_do_not_leak_suite_or_later_runtime_ownership() -> None:
    forbidden_exact = {
        "ResolvedEvaluationBinding",
        "RaterAggregateInput",
        "ResolvedMeasurementContract",
        "BoundVerifier",
    }
    forbidden_fragments = (
        "selected_evaluation_class",
        "judgment_slot",
        "agent_profile",
        "human_evidence_assignment",
        "suite_pairing",
    )

    def normalize_identifier(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())

    normalized_forbidden = {
        normalize_identifier(value)
        for value in (*forbidden_exact, *forbidden_fragments)
    }
    export_names = set(sdk.__all__)
    assert not export_names & forbidden_exact

    new_record_names = {
        "AbsoluteToleranceSpec",
        "ArtifactReferenceSource",
        "AxiomRelationReference",
        "BaselineDeltaReference",
        "BlindOrderSpec",
        "CanonicalPointReference",
        "CanonicalReferenceVerifier",
        "CanonicalSetReference",
        "CasePayloadReferenceSource",
        "ComparativeReferenceVerifier",
        "ConstraintSatisfactionReference",
        "DistanceToCanonicalSetReference",
        "EstimandSpec",
        "EvaluatorAgentRaterSource",
        "ExactPointMatchSpec",
        "FieldRatingReference",
        "HeadToHeadReference",
        "HumanReferenceComparison",
        "ImportedHumanRaterSource",
        "MeasurementLeafSpec",
        "MetamorphicRelationReference",
        "ObjectiveBaselineClaim",
        "ObjectiveBaselineReference",
        "ObjectiveBoundClaim",
        "ObjectiveExactClaim",
        "ObjectiveExactReference",
        "ObjectiveLowerBoundReference",
        "ObjectiveReferenceVerifier",
        "ObjectiveScopeSpec",
        "ObjectiveSupportClaim",
        "ObjectiveSupportMaxReference",
        "ObjectiveSupportMinReference",
        "ObjectiveUpperBoundReference",
        "ObjectiveValueOnlyClaim",
        "ObjectiveValueReference",
        "PairedComparisonReference",
        "PreOutcomeComputationSource",
        "RaterInputSpec",
        "RaterJudgeVerifier",
        "RaterScoreResult",
        "RaterTieResult",
        "RelativeToleranceSpec",
        "RuleConstraintVerifier",
        "StateInvariantReference",
        "TemporalPropertyReference",
        "TerminalStateEquivalenceReference",
        "TolerancePointMatchSpec",
        "ValidityDomainSpec",
    }
    assert new_record_names <= export_names
    assert not any(
        normalize_identifier(fragment) in normalize_identifier(name)
        for name in new_record_names
        for fragment in forbidden_fragments
    )
    new_records = tuple(getattr(sdk, name) for name in sorted(new_record_names))
    forbidden_science_fields = {
        "cluster",
        "panel",
        "pairing",
        "replicate",
        "estimator",
        "interval",
        "missingness",
        "assignment",
    }

    def schema_property_names(value: object) -> set[str]:
        if isinstance(value, dict):
            names = set(value.get("properties", {}))
            for child in value.values():
                names.update(schema_property_names(child))
            return names
        if isinstance(value, list):
            names: set[str] = set()
            for child in value:
                names.update(schema_property_names(child))
            return names
        return set()

    for record_type in new_records:
        fields = set(record_type.model_fields)
        assert not fields & forbidden_science_fields, record_type.__name__
        schema_fields = schema_property_names(record_type.model_json_schema())
        assert not schema_fields & forbidden_science_fields, record_type.__name__
        hints = str(get_type_hints(record_type, include_extras=True))
        normalized_hints = normalize_identifier(hints)
        assert not any(token in normalized_hints for token in normalized_forbidden)
        assert "JSONObject" not in hints

    aliases = (
        sdk.CanonicalReference,
        sdk.ComparativeReference,
        sdk.EvaluationClass,
        sdk.ObjectiveClaim,
        sdk.PointMatchSpec,
        sdk.RaterResult,
        sdk.RaterSource,
        sdk.ReferenceSource,
        sdk.RuleReference,
        sdk.ToleranceSpec,
        sdk.VerifierSpec,
    )
    for alias in aliases:
        alias_contract = str(alias) + json.dumps(
            TypeAdapter(alias).json_schema(), sort_keys=True
        )
        normalized_alias = normalize_identifier(alias_contract)
        assert not any(token in normalized_alias for token in normalized_forbidden)


def test_task_1_1a1_has_one_exact_public_export_delta() -> None:
    expected_added = {
        "AbsoluteToleranceSpec",
        "ArtifactReferenceSource",
        "AxiomRelationReference",
        "BaselineDeltaReference",
        "BlindOrderSpec",
        "CanonicalPointReference",
        "CanonicalReference",
        "CanonicalReferenceVerifier",
        "CanonicalSetReference",
        "CasePayloadReferenceSource",
        "ComparativeReference",
        "ComparativeReferenceVerifier",
        "ConstraintSatisfactionReference",
        "DistanceToCanonicalSetReference",
        "EstimandSpec",
        "EvaluationClass",
        "EvaluatorAgentRaterSource",
        "ExactPointMatchSpec",
        "FieldRatingReference",
        "HeadToHeadReference",
        "HumanReferenceComparison",
        "ImportedHumanRaterSource",
        "MeasurementLeafSpec",
        "MetamorphicRelationReference",
        "ObjectiveBaselineClaim",
        "ObjectiveBaselineReference",
        "ObjectiveBoundClaim",
        "ObjectiveClaim",
        "ObjectiveExactClaim",
        "ObjectiveExactReference",
        "ObjectiveLowerBoundReference",
        "ObjectiveReferenceVerifier",
        "ObjectiveScopeSpec",
        "ObjectiveSupportClaim",
        "ObjectiveSupportMaxReference",
        "ObjectiveSupportMinReference",
        "ObjectiveUpperBoundReference",
        "ObjectiveValueOnlyClaim",
        "ObjectiveValueReference",
        "PairedComparisonReference",
        "PointMatchSpec",
        "PreOutcomeComputationSource",
        "RaterInputSpec",
        "RaterJudgeVerifier",
        "RaterResult",
        "RaterScoreResult",
        "RaterSource",
        "RaterTieResult",
        "ReferenceSource",
        "RelativeToleranceSpec",
        "RuleConstraintVerifier",
        "RuleReference",
        "StateInvariantReference",
        "TemporalPropertyReference",
        "TerminalStateEquivalenceReference",
        "TolerancePointMatchSpec",
        "ToleranceSpec",
        "ValidityDomainSpec",
        "VerifierSpec",
    }
    exports = set(sdk.__all__)
    assert len(sdk.__all__) == len(exports)
    assert expected_added <= exports
    legacy_exports = exports - expected_added
    legacy_hash = hashlib.sha256(
        json.dumps(sorted(legacy_exports), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert (
        legacy_hash
        == "4bfb5f02d49da0419f6b9d6865d0e0963650f08104b9cdfa3983f08ff8dd1379"
    )


def test_typed_reference_items_have_one_source_and_no_generic_artifact_field() -> None:
    reference_types = tuple(
        type(reference)
        for reference in (
            *_canonical_references(),
            *_rule_references(),
            *_comparative_references(),
            _objective_reference(ObjectiveExactReference, "exact_value"),
            _objective_reference(ObjectiveLowerBoundReference, "lower_bound"),
            _objective_reference(ObjectiveUpperBoundReference, "upper_bound"),
            _objective_reference(
                ObjectiveBaselineReference,
                "comparison_baseline",
                comparison_id="baseline",
                comparison_version="1.0.0",
            ),
            _objective_reference(ObjectiveSupportMinReference, "support_min"),
            _objective_reference(ObjectiveSupportMaxReference, "support_max"),
            _objective_reference(ObjectiveValueReference, "value_only"),
        )
    )
    for reference_type in reference_types:
        assert "source" in reference_type.model_fields
        assert "artifacts" not in reference_type.model_fields
    assert set(ArtifactReferenceSource.model_fields) == {
        "spec_version",
        "source_kind",
        "artifacts",
    }


def test_leaf_rejects_comparative_estimand_semantic_mismatch() -> None:
    reference = _comparative_references()[0]
    mismatched = EstimandSpec(
        estimand_id="unrelated-estimand",
        estimand_version="1.0.0",
        input_scope="terminal_state",
        direction="maximize",
        units="usd",
        quantity_schema_ref="unrelated/1",
        validity_domain=ValidityDomainSpec(
            **{
                **_domain().model_dump(mode="python"),
                "domain_id": "unrelated-domain",
            }
        ),
    )
    with pytest.raises(ValidationError, match="comparative"):
        MeasurementLeafSpec(
            leaf_id="mismatched-comparative",
            leaf_version="1.0.0",
            composition_kind="leaf",
            estimand=mismatched,
            verifier=ComparativeReferenceVerifier(
                verifier_family="comparative",
                verifier_id="comparative-verifier",
                verifier_version="1.0.0",
                reference=reference,
            ),
            allowed_evaluation_classes=("stochastic_estimator",),
            scorer=_implementation("scorer"),
        )


@pytest.mark.parametrize("family", ["canonical", "rule", "rater"])
def test_leaf_rejects_incompatible_family_input_scope(family: str) -> None:
    if family == "canonical":
        verifier = CanonicalReferenceVerifier(
            verifier_family="canonical_reference",
            verifier_id="canonical-verifier",
            verifier_version="1.0.0",
            reference=_canonical_references()[0],
        )
        classes = ("deterministic",)
    elif family == "rule":
        verifier = RuleConstraintVerifier(
            verifier_family="rule_constraint",
            verifier_id="rule-verifier",
            verifier_version="1.0.0",
            reference=_rule_references()[0],
        )
        classes = ("deterministic",)
    else:
        verifier = _rater()
        classes = ("judge_dependent",)
    with pytest.raises(ValidationError, match="scope"):
        _leaf(verifier, classes, estimand=_estimand())


def test_leaf_rejects_objective_estimand_direction_units_or_domain_mismatch() -> None:
    scope = _scope()
    verifier = ObjectiveReferenceVerifier(
        verifier_family="objective_reference",
        verifier_id="objective-verifier",
        verifier_version="1.0.0",
        scope=scope,
        claim=ObjectiveValueOnlyClaim(
            claim_kind="value_only",
            certification_rule="no_optimality_or_comparison_claim",
            value=_objective_reference(ObjectiveValueReference, "value_only"),
        ),
    )
    mismatched = EstimandSpec(
        estimand_id="wrong-objective",
        estimand_version="1.0.0",
        input_scope="terminal_state",
        direction="minimize",
        units="usd",
        quantity_schema_ref="wrong-objective/1",
        validity_domain=ValidityDomainSpec(
            **{
                **_domain().model_dump(mode="python"),
                "domain_id": "wrong-domain",
            }
        ),
    )
    with pytest.raises(ValidationError, match="objective"):
        MeasurementLeafSpec(
            leaf_id="mismatched-objective",
            leaf_version="1.0.0",
            composition_kind="leaf",
            estimand=mismatched,
            verifier=verifier,
            allowed_evaluation_classes=("deterministic",),
            scorer=_implementation("scorer"),
        )


def test_objective_scope_rejects_native_minimize_without_canonical_negation() -> None:
    with pytest.raises(ValidationError):
        ObjectiveScopeSpec(
            **{
                **_scope().model_dump(mode="python"),
                "direction": "minimize",
                "source_direction": "minimize",
                "source_to_canonical_rule": "identity",
            }
        )


def test_distance_absolute_tolerance_units_must_match_distance_units() -> None:
    payload = _canonical_references()[-1].model_dump(mode="python")
    payload["tolerance"]["units"] = "seconds"
    with pytest.raises(ValidationError, match="tolerance units"):
        DistanceToCanonicalSetReference.model_validate(payload)


def test_temporal_rule_requires_ordered_trajectory_scope() -> None:
    payload = _rule_references()[2].model_dump(mode="python")
    payload["input_scope"] = "answer"
    payload["checkpoint_scope"] = "every_state"
    with pytest.raises(ValidationError):
        TemporalPropertyReference.model_validate(payload)


def test_artifact_tuple_rejects_same_digest_with_conflicting_metadata() -> None:
    first = _artifact("1", "application/json")
    conflicting = ArtifactRef(
        sha256=first.sha256,
        media_type="text/plain",
        size_bytes=first.size_bytes + 1,
    )
    with pytest.raises(ValidationError, match="sha256"):
        ArtifactReferenceSource(
            source_kind="artifacts",
            artifacts=(first, conflicting),
        )


@pytest.mark.parametrize(
    ("source_direction", "rule", "valid"),
    [
        ("maximize", "identity", True),
        ("maximize", "negate", False),
        ("minimize", "identity", False),
        ("minimize", "negate", True),
    ],
)
def test_objective_source_direction_is_exhaustively_canonicalized(
    source_direction: str, rule: str, valid: bool
) -> None:
    payload = _scope().model_dump(mode="python")
    payload["source_direction"] = source_direction
    payload["source_to_canonical_rule"] = rule
    if valid:
        scope = ObjectiveScopeSpec.model_validate(payload)
        assert scope.direction == "maximize"
    else:
        with pytest.raises(ValidationError, match="source_to_canonical_rule"):
            ObjectiveScopeSpec.model_validate(payload)


@pytest.mark.parametrize(
    ("bound_status", "certification_rule", "with_upper", "epsilon"),
    [
        (
            "exact_solved",
            "computed_bound_gap_eq_zero",
            True,
            None,
        ),
        (
            "epsilon_solved",
            "computed_bound_gap_lte_epsilon",
            True,
            0.1,
        ),
        (
            "bracketed",
            "certified_lower_le_optimum_le_upper",
            True,
            None,
        ),
        (
            "lower_bound_only",
            "feasible_witness_lower_bounds_optimum",
            False,
            None,
        ),
    ],
)
def test_every_objective_bound_mode_has_one_valid_canonical_shape(
    bound_status: str,
    certification_rule: str,
    with_upper: bool,
    epsilon: float | None,
) -> None:
    payload = {
        "claim_kind": "bound",
        "bound_status": bound_status,
        "certification_rule": certification_rule,
        "lower_bound": _objective_reference(
            ObjectiveLowerBoundReference, "lower_bound"
        ),
    }
    if with_upper:
        payload["upper_bound"] = _objective_reference(
            ObjectiveUpperBoundReference, "upper_bound"
        )
    if epsilon is not None:
        payload["epsilon"] = epsilon
        payload["epsilon_units"] = _scope().units
    claim = ObjectiveBoundClaim.model_validate(payload)
    assert claim.bound_status == bound_status


def test_epsilon_bound_units_must_match_canonical_objective_units() -> None:
    with pytest.raises(ValidationError, match="epsilon_units"):
        ObjectiveBoundClaim(
            claim_kind="bound",
            bound_status="epsilon_solved",
            certification_rule="computed_bound_gap_lte_epsilon",
            lower_bound=_objective_reference(
                ObjectiveLowerBoundReference, "lower_bound"
            ),
            upper_bound=_objective_reference(
                ObjectiveUpperBoundReference, "upper_bound"
            ),
            epsilon=0.1,
            epsilon_units="seconds",
        )


def test_canonical_point_has_typed_exact_and_tolerance_matching() -> None:
    common = {
        **_canonical_references()[0].model_dump(mode="python"),
        "match": {
            "match_kind": "tolerance",
            "tolerance": {
                "tolerance_kind": "absolute",
                "value": 0.01,
                "units": "label",
            },
        },
    }
    tolerant = CanonicalPointReference.model_validate(common)
    assert isinstance(tolerant.match, TolerancePointMatchSpec)
    assert isinstance(_canonical_references()[0].match, ExactPointMatchSpec)

    wrong_units = tolerant.model_dump(mode="python")
    wrong_units["match"]["tolerance"]["units"] = "seconds"
    with pytest.raises(ValidationError, match="tolerance units"):
        CanonicalPointReference.model_validate(wrong_units)


@pytest.mark.parametrize(
    ("reference_index", "input_scope", "checkpoint_scope"),
    [
        (0, "answer", "final_state"),
        (0, "terminal_state", "answer"),
        (0, "trajectory", "whole_trajectory"),
        (1, "terminal_state", "every_state"),
        (1, "trajectory", "final_state"),
        (1, "answer", "answer"),
        (2, "trajectory", "every_transition"),
        (3, "answer", "final_state"),
        (3, "terminal_state", "answer"),
        (3, "trajectory", "whole_trajectory"),
        (4, "distribution", "whole_trajectory"),
        (4, "trajectory", "related_cases"),
    ],
)
def test_rule_kind_scope_checkpoint_matrix_rejects_incompatible_pairs(
    reference_index: int, input_scope: str, checkpoint_scope: str
) -> None:
    reference = _rule_references()[reference_index]
    payload = reference.model_dump(mode="python")
    payload["input_scope"] = input_scope
    payload["checkpoint_scope"] = checkpoint_scope
    with pytest.raises(ValidationError):
        type(reference).model_validate(payload)


def test_metamorphic_relation_freezes_related_case_boundary() -> None:
    reference = _rule_references()[4]
    assert reference.input_scope == "distribution"
    assert reference.checkpoint_scope == "related_cases"
    assert reference.relation_scope == "related_cases_or_reruns"


def test_family_fixtures_bind_estimand_to_verifier_semantics() -> None:
    verifiers = (
        CanonicalReferenceVerifier(
            verifier_family="canonical_reference",
            verifier_id="canonical-verifier",
            verifier_version="1.0.0",
            reference=_canonical_references()[0],
        ),
        RuleConstraintVerifier(
            verifier_family="rule_constraint",
            verifier_id="rule-verifier",
            verifier_version="1.0.0",
            reference=_rule_references()[0],
        ),
        ObjectiveReferenceVerifier(
            verifier_family="objective_reference",
            verifier_id="objective-verifier",
            verifier_version="1.0.0",
            scope=_scope(),
            claim=ObjectiveValueOnlyClaim(
                claim_kind="value_only",
                certification_rule="no_optimality_or_comparison_claim",
                value=_objective_reference(ObjectiveValueReference, "value_only"),
            ),
        ),
        ComparativeReferenceVerifier(
            verifier_family="comparative",
            verifier_id="comparative-verifier",
            verifier_version="1.0.0",
            reference=_comparative_references()[0],
        ),
        _rater(),
    )
    for verifier in verifiers:
        classes = (
            ("judge_dependent",)
            if isinstance(verifier, RaterJudgeVerifier)
            else ("deterministic",)
        )
        assert _leaf(verifier, classes).estimand == _compatible_estimand(verifier)


def test_comparative_leaf_exact_matches_every_estimand_binding_field() -> None:
    verifier = ComparativeReferenceVerifier(
        verifier_family="comparative",
        verifier_id="comparative-verifier",
        verifier_version="1.0.0",
        reference=_comparative_references()[0],
    )
    leaf = _leaf(verifier, ("stochastic_estimator",))
    mutations = {
        "input_scope": "terminal_state",
        "direction": "minimize",
        "units": "usd",
        "validity_domain": ValidityDomainSpec(
            **{
                **leaf.estimand.validity_domain.model_dump(mode="python"),
                "domain_id": "other-domain",
            }
        ),
    }
    for field_name, value in mutations.items():
        payload = leaf.model_dump(mode="python")
        payload["estimand"][field_name] = value
        with pytest.raises(ValidationError, match="comparative"):
            MeasurementLeafSpec.model_validate(payload)


def test_objective_leaf_exact_matches_every_estimand_binding_field() -> None:
    verifier = ObjectiveReferenceVerifier(
        verifier_family="objective_reference",
        verifier_id="objective-verifier",
        verifier_version="1.0.0",
        scope=_scope(),
        claim=ObjectiveValueOnlyClaim(
            claim_kind="value_only",
            certification_rule="no_optimality_or_comparison_claim",
            value=_objective_reference(ObjectiveValueReference, "value_only"),
        ),
    )
    leaf = _leaf(verifier, ("deterministic",))
    mutations = {
        "direction": "minimize",
        "units": "usd",
        "validity_domain": ValidityDomainSpec(
            **{
                **leaf.estimand.validity_domain.model_dump(mode="python"),
                "domain_id": "other-domain",
            }
        ),
    }
    for field_name, value in mutations.items():
        payload = leaf.model_dump(mode="python")
        payload["estimand"][field_name] = value
        with pytest.raises(ValidationError, match="objective"):
            MeasurementLeafSpec.model_validate(payload)


def test_canonical_rule_and_rater_scope_bindings_fail_independently() -> None:
    canonical = CanonicalReferenceVerifier(
        verifier_family="canonical_reference",
        verifier_id="canonical-verifier",
        verifier_version="1.0.0",
        reference=_canonical_references()[0],
    )
    canonical_leaf = _leaf(canonical, ("deterministic",))
    for field_name, value in (
        ("input_scope", "terminal_state"),
        ("units", "usd"),
    ):
        payload = canonical_leaf.model_dump(mode="python")
        payload["estimand"][field_name] = value
        with pytest.raises(ValidationError, match="canonical"):
            MeasurementLeafSpec.model_validate(payload)

    rule = RuleConstraintVerifier(
        verifier_family="rule_constraint",
        verifier_id="rule-verifier",
        verifier_version="1.0.0",
        reference=_rule_references()[0],
    )
    rule_payload = _leaf(rule, ("deterministic",)).model_dump(mode="python")
    rule_payload["estimand"]["input_scope"] = "terminal_state"
    with pytest.raises(ValidationError, match="rule"):
        MeasurementLeafSpec.model_validate(rule_payload)

    rater_payload = _leaf(_rater(), ("judge_dependent",)).model_dump(mode="python")
    rater_payload["estimand"]["input_scope"] = "terminal_state"
    with pytest.raises(ValidationError, match="rater"):
        MeasurementLeafSpec.model_validate(rater_payload)


def _record_instances_for_required_field_checks() -> tuple[object, ...]:
    exact_claim = ObjectiveExactClaim(
        claim_kind="exact",
        certification_rule="exact_reference_match",
        exact=_objective_reference(ObjectiveExactReference, "exact_value"),
    )
    bound_claim = ObjectiveBoundClaim(
        claim_kind="bound",
        bound_status="bracketed",
        certification_rule="certified_lower_le_optimum_le_upper",
        lower_bound=_objective_reference(ObjectiveLowerBoundReference, "lower_bound"),
        upper_bound=_objective_reference(ObjectiveUpperBoundReference, "upper_bound"),
    )
    baseline_claim = ObjectiveBaselineClaim(
        claim_kind="baseline",
        certification_rule="comparison_against_pinned_baseline",
        baseline=_objective_reference(
            ObjectiveBaselineReference,
            "comparison_baseline",
            comparison_id="baseline",
            comparison_version="1.0.0",
        ),
    )
    support_claim = ObjectiveSupportClaim(
        claim_kind="support",
        certification_rule="support_min_lte_outcome_lte_support_max",
        support_min=_objective_reference(ObjectiveSupportMinReference, "support_min"),
        support_max=_objective_reference(ObjectiveSupportMaxReference, "support_max"),
    )
    value_claim = ObjectiveValueOnlyClaim(
        claim_kind="value_only",
        certification_rule="no_optimality_or_comparison_claim",
        value=_objective_reference(ObjectiveValueReference, "value_only"),
    )
    objective_verifier = ObjectiveReferenceVerifier(
        verifier_family="objective_reference",
        verifier_id="objective-verifier",
        verifier_version="1.0.0",
        scope=_scope(),
        claim=value_claim,
    )
    imported_source = ImportedHumanRaterSource(
        source_kind="imported_human",
        evidence_source=ArtifactReferenceSource(
            source_kind="artifacts", artifacts=(_artifact("c"),)
        ),
        import_validator=_implementation("human_evidence_import", "d"),
        evidence_schema_ref="human-judgments/1",
    )
    computation = PreOutcomeComputationSource(
        source_kind="pre_outcome_computation",
        determinism="pure_deterministic",
        implementation=_implementation("precompute", "e"),
        allowed_inputs=("case_payload",),
        output_schema_ref="computed-reference/1",
    )
    return (
        _domain(),
        _estimand(),
        _case_source(),
        ArtifactReferenceSource(source_kind="artifacts", artifacts=(_artifact("1"),)),
        computation,
        AbsoluteToleranceSpec(tolerance_kind="absolute", value=0.1, units="label"),
        RelativeToleranceSpec(tolerance_kind="relative", value=0.1),
        ExactPointMatchSpec(match_kind="exact"),
        TolerancePointMatchSpec(
            match_kind="tolerance",
            tolerance=RelativeToleranceSpec(tolerance_kind="relative", value=0.1),
        ),
        *_canonical_references(),
        CanonicalReferenceVerifier(
            verifier_family="canonical_reference",
            verifier_id="canonical-verifier",
            verifier_version="1.0.0",
            reference=_canonical_references()[0],
        ),
        *_rule_references(),
        RuleConstraintVerifier(
            verifier_family="rule_constraint",
            verifier_id="rule-verifier",
            verifier_version="1.0.0",
            reference=_rule_references()[0],
        ),
        _scope(),
        _objective_reference(ObjectiveExactReference, "exact_value"),
        _objective_reference(ObjectiveLowerBoundReference, "lower_bound"),
        _objective_reference(ObjectiveUpperBoundReference, "upper_bound"),
        baseline_claim.baseline,
        support_claim.support_min,
        support_claim.support_max,
        value_claim.value,
        exact_claim,
        bound_claim,
        baseline_claim,
        support_claim,
        value_claim,
        objective_verifier,
        *_comparative_references(),
        ComparativeReferenceVerifier(
            verifier_family="comparative",
            verifier_id="comparative-verifier",
            verifier_version="1.0.0",
            reference=_comparative_references()[0],
        ),
        _rater().input,
        _rater().rater_source,
        imported_source,
        _rater().blind_order,
        _rater(),
        RaterScoreResult(result_kind="score", value=1.0, schema_ref="score/1"),
        RaterTieResult(result_kind="valid_tie", schema_ref="tie/1"),
        _leaf(
            CanonicalReferenceVerifier(
                verifier_family="canonical_reference",
                verifier_id="canonical-verifier",
                verifier_version="1.0.0",
                reference=_canonical_references()[0],
            ),
            ("deterministic",),
        ),
    )


def test_every_new_record_rejects_each_missing_required_field() -> None:
    for record in _record_instances_for_required_field_checks():
        required = type(record).model_json_schema().get("required", ())
        for field_name in required:
            payload = record.model_dump(mode="python")
            payload.pop(field_name)
            with pytest.raises(ValidationError):
                type(record).model_validate(payload)


def test_every_new_union_rejects_an_unknown_discriminator() -> None:
    cases = (
        (sdk.ReferenceSource, _case_source(), "source_kind"),
        (
            sdk.ToleranceSpec,
            AbsoluteToleranceSpec(tolerance_kind="absolute", value=0.1, units="label"),
            "tolerance_kind",
        ),
        (sdk.PointMatchSpec, ExactPointMatchSpec(match_kind="exact"), "match_kind"),
        (sdk.CanonicalReference, _canonical_references()[0], "reference_kind"),
        (sdk.RuleReference, _rule_references()[0], "reference_kind"),
        (
            sdk.ObjectiveClaim,
            ObjectiveValueOnlyClaim(
                claim_kind="value_only",
                certification_rule="no_optimality_or_comparison_claim",
                value=_objective_reference(ObjectiveValueReference, "value_only"),
            ),
            "claim_kind",
        ),
        (
            sdk.ComparativeReference,
            _comparative_references()[0],
            "reference_kind",
        ),
        (sdk.RaterSource, _rater().rater_source, "source_kind"),
        (
            sdk.RaterResult,
            RaterTieResult(result_kind="valid_tie", schema_ref="tie/1"),
            "result_kind",
        ),
        (
            sdk.VerifierSpec,
            CanonicalReferenceVerifier(
                verifier_family="canonical_reference",
                verifier_id="canonical-verifier",
                verifier_version="1.0.0",
                reference=_canonical_references()[0],
            ),
            "verifier_family",
        ),
    )
    for alias, valid, discriminator in cases:
        payload = valid.model_dump(mode="python")
        payload[discriminator] = "unknown"
        with pytest.raises(ValidationError):
            TypeAdapter(alias).validate_python(payload)


def _canonical_tuple_records() -> tuple[tuple[type, dict[str, object], str, bool], ...]:
    first, second = _artifact("1"), _artifact("2")
    domain = ValidityDomainSpec(
        **{**_domain().model_dump(mode="python"), "parameters": (first, second)}
    )
    computation = PreOutcomeComputationSource(
        source_kind="pre_outcome_computation",
        determinism="pure_deterministic",
        implementation=_implementation("precompute", "3"),
        allowed_inputs=("case_payload", "reference_artifacts"),
        output_schema_ref="computed-reference/1",
        input_artifacts=(first, second),
    )
    rater = RaterJudgeVerifier(
        **{
            **_rater().model_dump(mode="python"),
            "calibration_refs": (first, second),
            "provenance_refs": (first, second),
        }
    )
    return (
        (ValidityDomainSpec, domain.model_dump(mode="python"), "parameters", False),
        (
            ArtifactReferenceSource,
            ArtifactReferenceSource(
                source_kind="artifacts", artifacts=(first, second)
            ).model_dump(mode="python"),
            "artifacts",
            True,
        ),
        (
            PreOutcomeComputationSource,
            computation.model_dump(mode="python"),
            "input_artifacts",
            False,
        ),
        (
            RaterJudgeVerifier,
            rater.model_dump(mode="python"),
            "calibration_refs",
            True,
        ),
        (
            RaterJudgeVerifier,
            rater.model_dump(mode="python"),
            "provenance_refs",
            True,
        ),
    )


def test_every_artifact_tuple_enforces_order_digest_uniqueness_and_cardinality() -> None:
    for model, base, field_name, required in _canonical_tuple_records():
        first, second = base[field_name]
        conflicting = {
            **first,
            "media_type": "text/plain",
            "size_bytes": first["size_bytes"] + 1,
        }
        whitespace_media_type = {**first, "media_type": " \t "}
        invalid_values = (
            (second, first),
            (first, first),
            (first, conflicting),
            (whitespace_media_type, second),
        )
        for values in invalid_values:
            with pytest.raises(ValidationError):
                model.model_validate({**base, field_name: values})
        empty = {**base, field_name: ()}
        if required:
            with pytest.raises(ValidationError):
                model.model_validate(empty)
        else:
            assert model.model_validate(empty)


@pytest.mark.parametrize("field_name", ["rubric_ref", "prompt_ref"])
def test_rater_direct_artifact_refs_reject_whitespace_media_type(
    field_name: str,
) -> None:
    payload = _rater().model_dump(mode="python")
    payload[field_name]["media_type"] = " \t "
    with pytest.raises(ValidationError, match="media_type"):
        RaterJudgeVerifier.model_validate(payload)


def test_new_measurement_schema_and_five_family_content_hashes_are_pinned() -> None:
    def schema_digest(value: object) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()

    assert {
        "MeasurementLeafSpec": schema_digest(MeasurementLeafSpec.model_json_schema()),
        "ReferenceSource": schema_digest(
            TypeAdapter(sdk.ReferenceSource).json_schema()
        ),
        "VerifierSpec": schema_digest(TypeAdapter(sdk.VerifierSpec).json_schema()),
    } == {
        "MeasurementLeafSpec": "50fc81260e41b76598327e6357081b606b8b9ebf94be89b9eac6c72ab2e9bc76",
        "ReferenceSource": "231b4cca7b9a598c93e4167c12b93705f0ad17233f1cda7df0fe801835998748",
        "VerifierSpec": "635076e0d74d1e0db578f30bca1792ffefe6950b8bfb526cbc0bb70ad539c73c",
    }

    verifiers = {
        "canonical": (
            CanonicalReferenceVerifier(
                verifier_family="canonical_reference",
                verifier_id="canonical-verifier",
                verifier_version="1.0.0",
                reference=_canonical_references()[0],
            ),
            ("deterministic",),
        ),
        "rule": (
            RuleConstraintVerifier(
                verifier_family="rule_constraint",
                verifier_id="rule-verifier",
                verifier_version="1.0.0",
                reference=_rule_references()[0],
            ),
            ("deterministic",),
        ),
        "objective": (
            ObjectiveReferenceVerifier(
                verifier_family="objective_reference",
                verifier_id="objective-verifier",
                verifier_version="1.0.0",
                scope=_scope(),
                claim=ObjectiveValueOnlyClaim(
                    claim_kind="value_only",
                    certification_rule="no_optimality_or_comparison_claim",
                    value=_objective_reference(ObjectiveValueReference, "value_only"),
                ),
            ),
            ("deterministic", "stochastic_estimator"),
        ),
        "comparative": (
            ComparativeReferenceVerifier(
                verifier_family="comparative",
                verifier_id="comparative-verifier",
                verifier_version="1.0.0",
                reference=_comparative_references()[0],
            ),
            ("stochastic_estimator",),
        ),
        "rater": (_rater(), ("judge_dependent",)),
    }
    assert {
        name: content_sha256(_leaf(verifier, classes))
        for name, (verifier, classes) in verifiers.items()
    } == {
        "canonical": "8b86215371982aa247098555e99402530d8da9275de7b56551f403ba11da562e",
        "rule": "6af8ddd829b6c158eb68dcd02cf0c443dc3820a7ad294a6366e59a1c578ee40d",
        "objective": "d72c23652aab9f8ceb4c9983877bfc8ffca848ed8feb373b04ed2b1cd9e0a253",
        "comparative": "d09cdfdb57fa16f98ed908908366b949dfa3fc5049c0e57b2600b3fb142d673f",
        "rater": "c86549ccf7761266294c6b43d2bd596769dc21b491ffb2f1ecb95e32c4c62ac6",
    }
