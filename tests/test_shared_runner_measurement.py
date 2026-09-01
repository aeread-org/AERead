from __future__ import annotations

import json

import pytest

from aeread.shared_runner import canonical_json_bytes
from aeread.shared_runner.measurement import (
    EstimandSpec,
    FamilyScoreSet,
    ImplementationRef,
    MeasurementContractError,
    MeasurementLeafSpec,
    MetricValue,
    ObjectiveScopeSpec,
    ReferenceSpec,
    ScoreEnvelope,
    ValidityDomainSpec,
    ValidityReport,
    VerifierSpec,
    normalize_family_score_set,
)


def _implementation(identifier: str, marker: str) -> ImplementationRef:
    return ImplementationRef(identifier, "1.0.0", marker * 64)


def _domain(identifier: str = "retail_base_v1") -> ValidityDomainSpec:
    return ValidityDomainSpec(
        domain_id=identifier,
        domain_version="1.0.0",
        schema_ref=f"{identifier}/1",
        predicate=_implementation(f"{identifier}_predicate", "a"),
    )


def test_refund_terminal_state_is_a_typed_canonical_leaf() -> None:
    domain = _domain()
    estimand = EstimandSpec(
        estimand_id="tau3_retail_db_state",
        estimand_version="1.0.0",
        input_scope="terminal_state",
        direction="none",
        units="pass",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id="tau3_gold_database",
        reference_version="1.0.1",
        reference_kind="terminal_state_equivalence",
        input_scope="terminal_state",
        units="pass",
        source_sha256="b" * 64,
        implementation=_implementation("tau3_state_equivalence", "c"),
    )
    leaf = MeasurementLeafSpec(
        leaf_id="tau3_retail_db_state_leaf",
        leaf_version="1.0.0",
        estimand=estimand,
        verifier=VerifierSpec(
            verifier_family="canonical_reference",
            evaluation_class="deterministic",
            reference=reference,
        ),
        scorer=_implementation("tau3_db_scorer", "d"),
    )
    score = ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(1.0, "pass"),
        metrics={"terminal_state_match": MetricValue(1.0, "pass")},
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=("artifact_001",),
    )

    encoded = json.loads(canonical_json_bytes(score))
    assert encoded["leaf"]["verifier"]["verifier_family"] == "canonical_reference"
    assert encoded["leaf"]["verifier"]["reference"]["reference_kind"] == (
        "terminal_state_equivalence"
    )


def test_supply_chain_can_keep_temporal_and_objective_claims_as_separate_leaves() -> None:
    domain = _domain("supply_chain_orders_v1")
    temporal = MeasurementLeafSpec(
        leaf_id="confirmation_before_purchase_leaf",
        leaf_version="1.0.0",
        estimand=EstimandSpec(
            estimand_id="confirmation_before_purchase",
            estimand_version="1.0.0",
            input_scope="trajectory",
            direction="none",
            units="pass",
            validity_domain=domain,
        ),
        verifier=VerifierSpec(
            verifier_family="rule_constraint",
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id="confirmation_temporal_rule",
                reference_version="1.0.0",
                reference_kind="temporal_property",
                input_scope="trajectory",
                units="pass",
                source_sha256="e" * 64,
                implementation=_implementation("confirmation_temporal_verifier", "f"),
            ),
        ),
        scorer=_implementation("temporal_rule_scorer", "1"),
    )
    objective_scope = ObjectiveScopeSpec(
        objective_id="fulfilled_value_minus_cost",
        objective_version="1.0.0",
        direction="maximize",
        units="usd",
        feasible_set="declared orders and supplier capacities",
        information_set="agent-visible inventory and quotes",
        horizon="one procurement episode",
        environment_condition="pinned demand and lead-time realization",
        opponent_condition="fixed supplier policy v1",
        validity_domain=domain,
    )
    objective = MeasurementLeafSpec(
        leaf_id="procurement_upper_bound_leaf",
        leaf_version="1.0.0",
        estimand=EstimandSpec(
            estimand_id="fulfilled_value_minus_cost",
            estimand_version="1.0.0",
            input_scope="terminal_state",
            direction="maximize",
            units="usd",
            validity_domain=domain,
        ),
        verifier=VerifierSpec(
            verifier_family="objective_reference",
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id="clairvoyant_relaxation",
                reference_version="1.0.0",
                reference_kind="objective_upper_bound",
                input_scope="terminal_state",
                units="usd",
                source_sha256="2" * 64,
                implementation=_implementation("procurement_relaxation", "3"),
            ),
            objective_scope=objective_scope,
        ),
        scorer=_implementation("procurement_objective_scorer", "4"),
    )

    assert temporal.verifier.verifier_family == "rule_constraint"
    assert objective.verifier.verifier_family == "objective_reference"
    assert temporal.leaf_id != objective.leaf_id


def test_reference_kind_cannot_be_attached_to_the_wrong_verifier_family() -> None:
    with pytest.raises(MeasurementContractError, match="does not belong"):
        VerifierSpec(
            verifier_family="canonical_reference",
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id="wrong_reference",
                reference_version="1.0.0",
                reference_kind="temporal_property",
                input_scope="trajectory",
                units="pass",
                source_sha256="5" * 64,
                implementation=_implementation("wrong_verifier", "6"),
            ),
        )


def test_objective_verifier_requires_a_fully_scoped_objective() -> None:
    with pytest.raises(MeasurementContractError, match="objective_scope"):
        VerifierSpec(
            verifier_family="objective_reference",
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id="housing_oracle",
                reference_version="1.0.0",
                reference_kind="exact_optimum",
                input_scope="terminal_state",
                units="utility_points",
                source_sha256="7" * 64,
                implementation=_implementation("housing_exact_assignment", "8"),
            ),
        )


def test_score_envelope_cannot_turn_invalid_evidence_into_a_score() -> None:
    domain = _domain()
    leaf = MeasurementLeafSpec(
        leaf_id="refund_leaf",
        leaf_version="1.0.0",
        estimand=EstimandSpec(
            estimand_id="refund_state",
            estimand_version="1.0.0",
            input_scope="terminal_state",
            direction="none",
            units="pass",
            validity_domain=domain,
        ),
        verifier=VerifierSpec(
            verifier_family="canonical_reference",
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id="refund_gold_state",
                reference_version="1.0.0",
                reference_kind="terminal_state_equivalence",
                input_scope="terminal_state",
                units="pass",
                source_sha256="9" * 64,
                implementation=_implementation("refund_state_equivalence", "a"),
            ),
        ),
        scorer=_implementation("refund_scorer", "b"),
    )

    with pytest.raises(MeasurementContractError, match="invalid_measurement"):
        ScoreEnvelope(
            status="invalid_measurement",
            leaf=leaf,
            primary=MetricValue(1.0, "pass"),
            metrics={},
            reference_values={},
            validity=ValidityReport("invalid", ("state artifact missing",)),
            evidence_refs=(),
        )


def test_family_score_set_requires_explicit_valid_admission_leaf_ids() -> None:
    domain = _domain("family_score_set_v1")
    leaf = MeasurementLeafSpec(
        leaf_id="primary_leaf",
        leaf_version="1.0.0",
        estimand=EstimandSpec(
            estimand_id="primary_metric",
            estimand_version="1.0.0",
            input_scope="terminal_state",
            direction="none",
            units="pass",
            validity_domain=domain,
        ),
        verifier=VerifierSpec(
            verifier_family="canonical_reference",
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id="primary_reference",
                reference_version="1.0.0",
                reference_kind="terminal_state_equivalence",
                input_scope="terminal_state",
                units="pass",
                source_sha256="c" * 64,
                implementation=_implementation("primary_verifier", "d"),
            ),
        ),
        scorer=_implementation("primary_scorer", "e"),
    )
    score = ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(1.0, "pass"),
        metrics={},
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=("outcome",),
    )

    normalized = normalize_family_score_set(score)
    assert normalized.primary_leaf_id == leaf.leaf_id
    assert normalized.admission_leaf_ids == (leaf.leaf_id,)
    assert normalized.invalid_admission_leaf_ids == ()

    with pytest.raises(MeasurementContractError, match="absent"):
        FamilyScoreSet(
            primary_leaf_id=leaf.leaf_id,
            scores=(score,),
            admission_leaf_ids=(leaf.leaf_id, "missing_leaf"),
        )
