"""Independent deterministic verifier leaves for data-center negotiations."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.measurement import (
    EstimandSpec,
    FamilyScoreSet,
    ImplementationRef,
    MeasurementLeafSpec,
    MetricValue,
    ObjectiveScopeSpec,
    ReferenceSpec,
    ScoreEnvelope,
    ValidityDomainSpec,
    ValidityReport,
    VerifierSpec,
)
from aeread.shared_runner.resolver import canonical_json_bytes


SCORER_IMPLEMENTATION_ID = "datacenter_development_score_set_v1"
VALIDITY_IMPLEMENTATION_ID = "datacenter_measurement_validity_v1"
REFERENCE_IMPLEMENTATION_ID = "datacenter_measurement_references_v1"
VERSION = "1.0.0"


def _source_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def implementation_refs() -> tuple[ImplementationRef, ...]:
    digest = _source_hash()
    return tuple(
        ImplementationRef(item, VERSION, digest)
        for item in (
            SCORER_IMPLEMENTATION_ID,
            VALIDITY_IMPLEMENTATION_ID,
            REFERENCE_IMPLEMENTATION_ID,
        )
    )


def _leaf(
    *,
    leaf_id: str,
    input_scope: str,
    direction: str,
    units: str,
    verifier_family: str,
    reference_kind: str,
    reference_source: Any,
) -> MeasurementLeafSpec:
    scorer, validity_impl, reference_impl = implementation_refs()
    domain = ValidityDomainSpec(
        domain_id=f"{leaf_id}_domain",
        domain_version=VERSION,
        schema_ref=f"aeread://datacenter_development/{leaf_id}/v1",
        predicate=validity_impl,
    )
    estimand = EstimandSpec(
        estimand_id=leaf_id,
        estimand_version=VERSION,
        input_scope=input_scope,
        direction=direction,
        units=units,
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=f"{leaf_id}_reference",
        reference_version=VERSION,
        reference_kind=reference_kind,
        input_scope=input_scope,
        units=units,
        source_sha256=hashlib.sha256(canonical_json_bytes(reference_source)).hexdigest(),
        implementation=reference_impl,
    )
    objective = None
    if verifier_family == "objective_reference":
        objective = ObjectiveScopeSpec(
            objective_id=leaf_id,
            objective_version=VERSION,
            direction=direction,
            units=units,
            feasible_set="typed service and loan terms accepted by controlled counterparties",
            information_set="developer observation at each negotiation phase",
            horizon="one negotiation followed by the pinned monthly project horizon",
            environment_condition="frozen project facts and condition-satisfaction schedule",
            opponent_condition="deterministic customer and lender policies",
            validity_domain=domain,
        )
    return MeasurementLeafSpec(
        leaf_id=leaf_id,
        leaf_version=VERSION,
        estimand=estimand,
        verifier=VerifierSpec(
            verifier_family=verifier_family,
            evaluation_class="deterministic",
            reference=reference,
            objective_scope=objective,
        ),
        scorer=scorer,
    )


def primary_measurement_leaf(
    family_case: Mapping[str, Any],
) -> MeasurementLeafSpec:
    """Build the primary leaf for typed operational-failure receipts."""

    baseline = family_case["baseline"]
    outside = family_case["outside_option"]
    return _leaf(
        leaf_id="developer_equity_npv",
        input_scope="terminal_state",
        direction="maximize",
        units="cents",
        verifier_family="objective_reference",
        reference_kind="comparison_baseline",
        reference_source={
            "baseline": baseline["developer_equity_npv_cents"],
            "outside": outside["developer_equity_npv_cents"],
        },
    )


class DataCenterDevelopmentScorer:
    """Score economics, contract validity, constraints, and ordering separately."""

    def __init__(self, family_case: Mapping[str, Any]) -> None:
        self._case = family_case

    def __call__(
        self, outcome: Mapping[str, Any], *, evidence_refs: tuple[str, ...]
    ) -> FamilyScoreSet:
        baseline = self._case["baseline"]
        outside = self._case["outside_option"]
        primary_leaf = primary_measurement_leaf(self._case)
        contract_leaf = _leaf(
            leaf_id="binding_contract_integrity",
            input_scope="terminal_state",
            direction="maximize",
            units="indicator",
            verifier_family="canonical_reference",
            reference_kind="terminal_state_equivalence",
            reference_source={"required_signatures": {"service": ["customer", "developer"], "loan": ["developer", "lender"]}},
        )
        constraint_leaf = _leaf(
            leaf_id="project_constraint_satisfaction",
            input_scope="terminal_state",
            direction="maximize",
            units="indicator",
            verifier_family="rule_constraint",
            reference_kind="constraint_satisfaction",
            reference_source={"requires": ["financing_succeeded", "not_defaulted"]},
        )
        temporal_leaf = _leaf(
            leaf_id="negotiation_temporal_compliance",
            input_scope="trajectory",
            direction="maximize",
            units="indicator",
            verifier_family="rule_constraint",
            reference_kind="temporal_property",
            reference_source={"order": ["offer", "accept", "sign"], "agreements": ["service", "loan"]},
        )
        total_leaf = _leaf(
            leaf_id="total_project_npv",
            input_scope="terminal_state",
            direction="maximize",
            units="cents",
            verifier_family="objective_reference",
            reference_kind="comparison_baseline",
            reference_source={"baseline": baseline["total_project_npv_cents"], "outside": outside["total_project_npv_cents"]},
        )

        def score(
            leaf: MeasurementLeafSpec,
            value: int | float,
            *,
            reference_name: str,
            reference_value: int | float,
            metrics: Mapping[str, MetricValue] | None = None,
        ) -> ScoreEnvelope:
            return ScoreEnvelope(
                status="ok",
                leaf=leaf,
                primary=MetricValue(float(value), leaf.estimand.units),
                metrics=metrics or {},
                reference_values={
                    reference_name: MetricValue(float(reference_value), leaf.estimand.units)
                },
                validity=ValidityReport("valid"),
                evidence_refs=evidence_refs,
            )

        contract_ok = bool(outcome["binding_contract_integrity"])
        constraints_ok = bool(outcome["project_constraints_satisfied"])
        temporal_ok = not outcome["temporal_violations"]
        scores = (
            score(
                primary_leaf,
                outcome["developer_equity_npv_cents"],
                reference_name="scripted_baseline",
                reference_value=baseline["developer_equity_npv_cents"],
                metrics={
                    "delta_from_baseline": MetricValue(
                        float(outcome["developer_equity_npv_cents"] - baseline["developer_equity_npv_cents"]), "cents"
                    )
                },
            ),
            score(contract_leaf, int(contract_ok), reference_name="required", reference_value=1),
            score(constraint_leaf, int(constraints_ok), reference_name="required", reference_value=1),
            score(temporal_leaf, int(temporal_ok), reference_name="required", reference_value=1),
            score(
                total_leaf,
                outcome["total_project_npv_cents"],
                reference_name="scripted_baseline",
                reference_value=baseline["total_project_npv_cents"],
            ),
        )
        return FamilyScoreSet(
            primary_leaf_id=primary_leaf.leaf_id,
            scores=scores,
            admission_leaf_ids=tuple(item.leaf.leaf_id for item in scores),
        )


__all__ = [
    "DataCenterDevelopmentScorer",
    "REFERENCE_IMPLEMENTATION_ID",
    "SCORER_IMPLEMENTATION_ID",
    "VALIDITY_IMPLEMENTATION_ID",
    "implementation_refs",
    "primary_measurement_leaf",
]
