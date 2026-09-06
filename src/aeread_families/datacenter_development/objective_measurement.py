"""Bounded verifier leaves for the objective-aware V2 data-center stack."""

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
from aeread.shared_runner.run.resolver import canonical_json_bytes


SCORER_IMPLEMENTATION_ID = "datacenter_objective_score_set_v1"
VALIDITY_IMPLEMENTATION_ID = "datacenter_objective_validity_v1"
REFERENCE_IMPLEMENTATION_ID = "datacenter_objective_references_v1"
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
    objective: bool = False,
) -> MeasurementLeafSpec:
    scorer, validity_impl, reference_impl = implementation_refs()
    domain = ValidityDomainSpec(
        domain_id=f"{leaf_id}_domain",
        domain_version=VERSION,
        schema_ref=f"aeread://datacenter_development_objective/{leaf_id}/v1",
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
    objective_scope = (
        ObjectiveScopeSpec(
            objective_id=leaf_id,
            objective_version=VERSION,
            direction=direction,
            units=units,
            feasible_set=(
                "explicit developer walk or a complete V2 agreement stack accepted "
                "by exact-package controlled counterparty policies"
            ),
            information_set=(
                "developer-visible project facts, public negotiation history, written "
                "offers, declared outside option, and objective rules"
            ),
            horizon="one negotiation followed by the pinned four-month project horizon",
            environment_condition=(
                "frozen bounded V2 project facts and condition-satisfaction schedule"
            ),
            opponent_condition="deterministic exact-package controlled counterparties",
            validity_domain=domain,
        )
        if objective
        else None
    )
    return MeasurementLeafSpec(
        leaf_id=leaf_id,
        leaf_version=VERSION,
        estimand=estimand,
        verifier=VerifierSpec(
            verifier_family=verifier_family,
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id=f"{leaf_id}_reference",
                reference_version=VERSION,
                reference_kind=reference_kind,
                input_scope=input_scope,
                units=units,
                source_sha256=hashlib.sha256(
                    canonical_json_bytes(reference_source)
                ).hexdigest(),
                implementation=reference_impl,
            ),
            objective_scope=objective_scope,
        ),
        scorer=scorer,
    )


def primary_measurement_leaf(
    family_case: Mapping[str, Any],
) -> MeasurementLeafSpec:
    return _leaf(
        leaf_id="safe_developer_objective_attainment",
        input_scope="terminal_state",
        direction="maximize",
        units="ratio",
        verifier_family="objective_reference",
        reference_kind="exact_optimum",
        reference_source={
            "outside_developer_equity_npv_cents": family_case["outside_option"][
                "developer_equity_npv_cents"
            ],
            "reference_developer_equity_npv_cents": family_case["baseline"][
                "developer_equity_npv_cents"
            ],
            "policy_mode": "exact_complete_structured_package",
        },
        objective=True,
    )


class ObjectiveAwareDataCenterScorer:
    """Keep economic value, validity, and intentional resolution separate."""

    def __init__(self, family_case: Mapping[str, Any]) -> None:
        self._case = family_case

    @staticmethod
    def _score(
        leaf: MeasurementLeafSpec,
        value: int | float,
        *,
        reference_name: str,
        reference_value: int | float,
        evidence_refs: tuple[str, ...],
        metrics: Mapping[str, MetricValue] | None = None,
    ) -> ScoreEnvelope:
        return ScoreEnvelope(
            status="ok",
            leaf=leaf,
            primary=MetricValue(float(value), leaf.estimand.units),
            metrics=metrics or {},
            reference_values={
                reference_name: MetricValue(
                    float(reference_value), leaf.estimand.units
                )
            },
            validity=ValidityReport("valid"),
            evidence_refs=evidence_refs,
        )

    def __call__(
        self, outcome: Mapping[str, Any], *, evidence_refs: tuple[str, ...]
    ) -> FamilyScoreSet:
        outside = int(
            self._case["outside_option"]["developer_equity_npv_cents"]
        )
        reference = int(self._case["baseline"]["developer_equity_npv_cents"])
        if reference <= outside:
            raise ValueError("objective reference must strictly dominate the outside option")

        completed = bool(outcome["project_completed"])
        contract_ok = bool(outcome["binding_contract_integrity"])
        constraints_ok = bool(outcome["project_constraints_satisfied"])
        temporal_ok = not outcome["temporal_violations"]
        npv = int(outcome["developer_equity_npv_cents"])
        reference_dominates = not completed or npv <= reference
        eligible = (
            completed
            and contract_ok
            and constraints_ok
            and temporal_ok
            and reference_dominates
        )
        raw_attainment = (npv - outside) / (reference - outside)
        attainment = min(1.0, max(0.0, raw_attainment)) if eligible else 0.0
        intentional_resolution = completed or outcome["termination_reason"] == "developer_walk"

        primary = primary_measurement_leaf(self._case)
        raw_npv = _leaf(
            leaf_id="developer_equity_npv",
            input_scope="terminal_state",
            direction="maximize",
            units="cents",
            verifier_family="objective_reference",
            reference_kind="exact_optimum",
            reference_source={"reference": reference, "outside": outside},
            objective=True,
        )
        contract_leaf = _leaf(
            leaf_id="binding_contract_integrity",
            input_scope="terminal_state",
            direction="maximize",
            units="indicator",
            verifier_family="canonical_reference",
            reference_kind="terminal_state_equivalence",
            reference_source={"required": True},
        )
        constraint_leaf = _leaf(
            leaf_id="project_constraint_satisfaction",
            input_scope="terminal_state",
            direction="maximize",
            units="indicator",
            verifier_family="rule_constraint",
            reference_kind="constraint_satisfaction",
            reference_source={"required": True},
        )
        temporal_leaf = _leaf(
            leaf_id="negotiation_temporal_compliance",
            input_scope="trajectory",
            direction="maximize",
            units="indicator",
            verifier_family="rule_constraint",
            reference_kind="temporal_property",
            reference_source={"required": True},
        )
        resolution_leaf = _leaf(
            leaf_id="intentional_resolution",
            input_scope="terminal_state",
            direction="maximize",
            units="indicator",
            verifier_family="rule_constraint",
            reference_kind="state_invariant",
            reference_source={"allowed": ["agreement_stack_executed", "developer_walk"]},
        )
        dominance_leaf = _leaf(
            leaf_id="controlled_reference_dominance",
            input_scope="terminal_state",
            direction="maximize",
            units="indicator",
            verifier_family="rule_constraint",
            reference_kind="state_invariant",
            reference_source={"maximum_completed_developer_npv_cents": reference},
        )
        scores = (
            self._score(
                primary,
                attainment,
                reference_name="perfect_attainment",
                reference_value=1,
                evidence_refs=evidence_refs,
                metrics={
                    "eligible_completion": MetricValue(int(eligible), "indicator"),
                    "raw_attainment": MetricValue(raw_attainment, "ratio"),
                },
            ),
            self._score(
                raw_npv,
                npv,
                reference_name="certified_control_reference",
                reference_value=reference,
                evidence_refs=evidence_refs,
                metrics={
                    "outside_option": MetricValue(outside, "cents"),
                    "delta_from_outside": MetricValue(npv - outside, "cents"),
                },
            ),
            self._score(
                contract_leaf,
                int(contract_ok),
                reference_name="required",
                reference_value=1,
                evidence_refs=evidence_refs,
            ),
            self._score(
                constraint_leaf,
                int(constraints_ok),
                reference_name="required",
                reference_value=1,
                evidence_refs=evidence_refs,
            ),
            self._score(
                temporal_leaf,
                int(temporal_ok),
                reference_name="required",
                reference_value=1,
                evidence_refs=evidence_refs,
            ),
            self._score(
                resolution_leaf,
                int(intentional_resolution),
                reference_name="required",
                reference_value=1,
                evidence_refs=evidence_refs,
            ),
            self._score(
                dominance_leaf,
                int(reference_dominates),
                reference_name="required",
                reference_value=1,
                evidence_refs=evidence_refs,
            ),
        )
        return FamilyScoreSet(
            primary_leaf_id=primary.leaf_id,
            scores=scores,
            admission_leaf_ids=tuple(item.leaf.leaf_id for item in scores),
        )


__all__ = [
    "ObjectiveAwareDataCenterScorer",
    "REFERENCE_IMPLEMENTATION_ID",
    "SCORER_IMPLEMENTATION_ID",
    "VALIDITY_IMPLEMENTATION_ID",
    "implementation_refs",
    "primary_measurement_leaf",
]
