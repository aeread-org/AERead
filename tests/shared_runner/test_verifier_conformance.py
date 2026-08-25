"""Provider-free conformance tests for reusable measurement-leaf records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import get_args, get_type_hints

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


def _estimand() -> EstimandSpec:
    return EstimandSpec(
        estimand_id="allocation-quality",
        estimand_version="1.0.0",
        input_scope="terminal_state",
        direction="maximize",
        units="utility_points",
        quantity_schema_ref="allocation-quality/1",
        validity_domain=_domain(),
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


def _leaf(verifier: object, classes: tuple[str, ...]) -> MeasurementLeafSpec:
    return MeasurementLeafSpec(
        leaf_id="allocation-quality-leaf",
        leaf_version="1.0.0",
        composition_kind="leaf",
        estimand=_estimand(),
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
            match_kind="exact",
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
        "input_scope": "trajectory",
        "checkpoint_scope": "whole_trajectory",
        "result_schema_ref": "rule-result/1",
        "result_semantics": "pass_vector_and_residual",
        "residual_schema_ref": "constraint-residual/1",
        "source": _case_source(),
    }
    return (
        ConstraintSatisfactionReference(
            reference_kind="constraint_satisfaction",
            predicate=_implementation("constraint_predicate", "a"),
            **common,
        ),
        StateInvariantReference(
            reference_kind="state_invariant",
            predicate=_implementation("state_invariant", "b"),
            **common,
        ),
        TemporalPropertyReference(
            reference_kind="temporal_property",
            predicate=_implementation("temporal_property", "c"),
            **common,
        ),
        AxiomRelationReference(
            reference_kind="axiom_relation",
            relation=_implementation("axiom_relation", "d"),
            **common,
        ),
        MetamorphicRelationReference(
            reference_kind="metamorphic_relation",
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
        "direction": {
            "direction": "minimize",
            "source_to_canonical_rule": "negate",
        },
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
    export_names = set(sdk.__all__)
    assert not export_names & forbidden_exact
    assert not any(
        fragment in name.lower()
        for name in export_names
        for fragment in forbidden_fragments
    )

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
        "ValidityDomainSpec",
    }
    assert new_record_names <= export_names
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
        assert not forbidden_exact & set(get_args(hints))
        assert not any(token in hints for token in forbidden_exact)
        assert "JSONObject" not in hints


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
