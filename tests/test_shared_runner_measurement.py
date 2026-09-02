from __future__ import annotations

import json

import pytest

from aeread.shared_runner import canonical_json_bytes
from aeread.shared_runner.measurement import (
    EstimandSpec,
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


def test_verifier_taxonomy_reference_kind_tables_name_only_real_kinds() -> None:
    """docs/verifier_taxonomy.md drift guard: any markdown table whose first
    column is headed "Reference kind" may only name kinds the measurement
    contract actually accepts — a spec author following the doc must never
    hit MeasurementContractError. Conceptual claim-pattern names live in
    columns with other headings."""

    import re
    from pathlib import Path

    from aeread.shared_runner.measurement import _REFERENCE_KINDS

    real_kinds = set().union(*_REFERENCE_KINDS.values())
    doc = (
        Path(__file__).resolve().parent.parent / "docs" / "verifier_taxonomy.md"
    ).read_text()

    documented: list[str] = []
    in_reference_kind_table = False
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped.startswith("| Reference kind"):
            in_reference_kind_table = True
            continue
        if in_reference_kind_table:
            if not stripped.startswith("|"):
                in_reference_kind_table = False
                continue
            if stripped.startswith("| `"):
                # Every backticked token in the row's first cell, not just the
                # first: a cell naming two kinds must have both checked.
                first_cell = stripped.split("|")[1]
                documented.extend(re.findall(r"`([^`]+)`", first_cell))

    assert documented, "the taxonomy doc must document reference kinds"
    fake = [kind for kind in documented if kind not in real_kinds]
    assert fake == [], (
        f"verifier_taxonomy.md names reference kinds the contract rejects: {fake}"
    )
    for kind in _REFERENCE_KINDS["objective_reference"]:
        assert f"`{kind}`" in doc, (
            f"objective_reference kind {kind!r} is undocumented in the taxonomy"
        )


def test_field_rating_verifier_cannot_claim_deterministic_evaluation() -> None:
    reference = ReferenceSpec(
        reference_id="marketplace_field_rating",
        reference_version="1.0.0",
        reference_kind="field_rating",
        input_scope="answer",
        units="rating",
        source_sha256="b" * 64,
        implementation=_implementation("field_rating_reference", "c"),
    )

    with pytest.raises(MeasurementContractError, match="field_rating"):
        VerifierSpec(
            verifier_family="comparative",
            evaluation_class="deterministic",
            reference=reference,
        )

    judged = VerifierSpec(
        verifier_family="comparative",
        evaluation_class="judge_dependent",
        reference=reference,
    )
    assert judged.evaluation_class == "judge_dependent"


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
