"""Typed verifier leaves for staged written-counteroffer adoption."""

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
    ReferenceSpec,
    ScoreEnvelope,
    ValidityDomainSpec,
    ValidityReport,
    VerifierSpec,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes


SCORER_IMPLEMENTATION_ID = "datacenter_counteroffer_adoption_score_set_v1"
VALIDITY_IMPLEMENTATION_ID = "datacenter_counteroffer_adoption_validity_v1"
REFERENCE_IMPLEMENTATION_ID = "datacenter_counteroffer_adoption_references_v1"
VERSION = "1.0.0"


def _source_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def implementation_refs() -> tuple[ImplementationRef, ...]:
    digest = _source_hash()
    return tuple(
        ImplementationRef(component, VERSION, digest)
        for component in (
            SCORER_IMPLEMENTATION_ID,
            VALIDITY_IMPLEMENTATION_ID,
            REFERENCE_IMPLEMENTATION_ID,
        )
    )


def _leaf(
    *,
    leaf_id: str,
    input_scope: str,
    units: str,
    verifier_family: str,
    reference_kind: str,
    reference_source: Any,
) -> MeasurementLeafSpec:
    scorer, validity_impl, reference_impl = implementation_refs()
    domain = ValidityDomainSpec(
        domain_id=f"{leaf_id}_domain",
        domain_version=VERSION,
        schema_ref=f"aeread://datacenter_counteroffer_adoption/{leaf_id}/v1",
        predicate=validity_impl,
    )
    return MeasurementLeafSpec(
        leaf_id=leaf_id,
        leaf_version=VERSION,
        estimand=EstimandSpec(
            estimand_id=leaf_id,
            estimand_version=VERSION,
            input_scope=input_scope,
            direction="maximize",
            units=units,
            validity_domain=domain,
        ),
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
            objective_scope=None,
        ),
        scorer=scorer,
    )


def primary_measurement_leaf(
    family_case: Mapping[str, Any],
) -> MeasurementLeafSpec:
    return _leaf(
        leaf_id="counteroffer_adoption_rate",
        input_scope="terminal_state",
        units="ratio",
        verifier_family="canonical_reference",
        reference_kind="terminal_state_equivalence",
        reference_source={
            "required_sequence": family_case["adoption_stage"]["required_sequence"],
            "required_behavior": (
                "copy each complete written counter package exactly and sign its "
                "accepted offer id"
            ),
        },
    )


class CounterofferAdoptionScorer:
    """Score adoption while keeping completion, integrity, and order visible."""

    def __init__(self, family_case: Mapping[str, Any]) -> None:
        self._case = family_case

    @staticmethod
    def _score(
        leaf: MeasurementLeafSpec,
        value: int | float,
        reference_value: int | float,
        evidence_refs: tuple[str, ...],
    ) -> ScoreEnvelope:
        return ScoreEnvelope(
            status="ok",
            leaf=leaf,
            primary=MetricValue(float(value), leaf.estimand.units),
            metrics={},
            reference_values={
                "required": MetricValue(float(reference_value), leaf.estimand.units)
            },
            validity=ValidityReport("valid"),
            evidence_refs=evidence_refs,
        )

    def __call__(
        self, outcome: Mapping[str, Any], *, evidence_refs: tuple[str, ...]
    ) -> FamilyScoreSet:
        required = len(self._case["adoption_stage"]["required_sequence"])
        primary = primary_measurement_leaf(self._case)
        specs = (
            (primary, float(outcome["counteroffer_adoption_rate"]), 1),
            (
                _leaf(
                    leaf_id="prefix_completion",
                    input_scope="terminal_state",
                    units="indicator",
                    verifier_family="rule_constraint",
                    reference_kind="state_invariant",
                    reference_source={"required": True},
                ),
                int(bool(outcome["prefix_completed"])),
                1,
            ),
            (
                _leaf(
                    leaf_id="exact_package_integrity",
                    input_scope="terminal_state",
                    units="indicator",
                    verifier_family="canonical_reference",
                    reference_kind="terminal_state_equivalence",
                    reference_source={"required": True},
                ),
                int(bool(outcome["exact_package_integrity"])),
                1,
            ),
            (
                _leaf(
                    leaf_id="executed_agreement_count",
                    input_scope="terminal_state",
                    units="count",
                    verifier_family="rule_constraint",
                    reference_kind="state_invariant",
                    reference_source={"required_count": required},
                ),
                int(outcome["executed_agreement_count"]),
                required,
            ),
            (
                _leaf(
                    leaf_id="counteroffer_opportunity_count",
                    input_scope="trajectory",
                    units="count",
                    verifier_family="rule_constraint",
                    reference_kind="temporal_property",
                    reference_source={"expected_count": required},
                ),
                int(outcome["counteroffer_opportunity_count"]),
                required,
            ),
            (
                _leaf(
                    leaf_id="negotiation_temporal_compliance",
                    input_scope="trajectory",
                    units="indicator",
                    verifier_family="rule_constraint",
                    reference_kind="temporal_property",
                    reference_source={"required": True},
                ),
                int(not outcome["temporal_violations"]),
                1,
            ),
            (
                _leaf(
                    leaf_id="intentional_resolution",
                    input_scope="terminal_state",
                    units="indicator",
                    verifier_family="rule_constraint",
                    reference_kind="state_invariant",
                    reference_source={
                        "allowed": ["agreement_stack_executed", "developer_walk"]
                    },
                ),
                int(bool(outcome["intentional_resolution"])),
                1,
            ),
        )
        scores = tuple(
            self._score(leaf, value, reference, evidence_refs)
            for leaf, value, reference in specs
        )
        return FamilyScoreSet(
            primary_leaf_id=primary.leaf_id,
            scores=scores,
            admission_leaf_ids=tuple(score.leaf.leaf_id for score in scores),
        )


__all__ = [
    "CounterofferAdoptionScorer",
    "REFERENCE_IMPLEMENTATION_ID",
    "SCORER_IMPLEMENTATION_ID",
    "VALIDITY_IMPLEMENTATION_ID",
    "implementation_refs",
    "primary_measurement_leaf",
]
