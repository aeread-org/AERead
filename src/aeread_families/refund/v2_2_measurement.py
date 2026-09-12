"""Typed measurements for Refund V2.2's constrained N:1 panel."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aeread.shared_runner.measurement import (
    EstimandSpec, FamilyScoreSet, ImplementationRef, MeasurementLeafSpec,
    MetricValue, ObjectiveScopeSpec, ReferenceSpec, ScoreEnvelope,
    ValidityDomainSpec, ValidityReport, VerifierSpec,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import FamilyScoringInput

from .v2_2_environment import RefundV22Batch

VERSION = "2.2.0"
DOMAIN_ID = "refund_v22_terminal_domain"
POLICY_LEAF_ID = "refund_v22_policy_compliance_leaf"
ALLOCATION_LEAF_ID = "refund_v22_allocation_leaf"
TRANSACTION_LEAF_ID = "refund_v22_transaction_leaf"
COORDINATION_LEAF_ID = "refund_v22_coordination_leaf"
UTILITY_LEAF_ID = "refund_v22_system_utility_leaf"

V22_ESTIMANDS = (
    "refund_v22_policy_compliance",
    "refund_v22_allocation",
    "refund_v22_transaction",
    "refund_v22_coordination",
    "refund_v22_system_utility",
)


def metric_names() -> tuple[str, ...]:
    """Return metrics in the declared priority order."""
    return V22_ESTIMANDS


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _implementation(identifier: str, filename: str) -> ImplementationRef:
    return ImplementationRef(
        identifier, VERSION,
        hashlib.sha256(Path(__file__).with_name(filename).read_bytes()).hexdigest(),
    )


def _leaf(leaf_id: str, estimand_id: str, units: str, direction: str, *, objective: bool = False) -> MeasurementLeafSpec:
    domain = ValidityDomainSpec(
        DOMAIN_ID, VERSION, "refund_v2_2/terminal_state",
        _implementation("refund_v22_domain_predicate", "v2_2_environment.py"),
    )
    reference_id = f"{estimand_id}_reference"
    reference = ReferenceSpec(
        reference_id, VERSION, "objective_upper_bound" if objective else "constraint_satisfaction",
        "terminal_state", units, _digest({"reference": reference_id, "version": VERSION}),
        _implementation(f"refund_v22_{estimand_id.removeprefix('refund_v22_')}_verifier", "v2_2_environment.py"),
    )
    objective_scope = ObjectiveScopeSpec(
        estimand_id, VERSION, direction, units,
        "verified allocations subject to the sealed shared budget and execution capacity",
        "facts revealed in the sealed batch trajectory",
        "one pinned Refund V2.2 batch", "pinned Refund V2.2 batch and allocation policy",
        "declared active or scripted policy seat configuration", domain,
    ) if objective else None
    return MeasurementLeafSpec(
        leaf_id, VERSION,
        EstimandSpec(estimand_id, VERSION, "terminal_state", direction, units, domain),
        VerifierSpec("objective_reference" if objective else "rule_constraint", "deterministic", reference, objective_scope),
        _implementation("refund_v22_scorer", "v2_2_measurement.py"),
    )


def build_measurement_leaves(batch: RefundV22Batch) -> tuple[MeasurementLeafSpec, ...]:
    del batch
    return (
        _leaf(POLICY_LEAF_ID, "refund_v22_policy_compliance", "pass", "none"),
        _leaf(ALLOCATION_LEAF_ID, "refund_v22_allocation", "pass", "none"),
        _leaf(TRANSACTION_LEAF_ID, "refund_v22_transaction", "pass", "none"),
        _leaf(COORDINATION_LEAF_ID, "refund_v22_coordination", "pass", "none"),
        _leaf(UTILITY_LEAF_ID, "refund_v22_system_utility", "utility_points", "maximize", objective=True),
    )


@dataclass(frozen=True, slots=True)
class RefundV22Scorer:
    batch: RefundV22Batch
    leaves: tuple[MeasurementLeafSpec, ...]

    def __call__(self, scoring_input: FamilyScoringInput, *, evidence_refs: tuple[str, ...] = ()) -> FamilyScoreSet:
        outcome = scoring_input.outcome
        values = (
            1.0 if outcome.get("policy_compliant") else 0.0,
            float(outcome["allocation_score"]), float(outcome["transaction_score"]),
            float(outcome["coordination_score"]), float(outcome["system_utility"]),
        )
        reasons = tuple(str(reason) for reason in outcome.get("verifier_reasons", ()))
        scores = []
        for index, (leaf, value) in enumerate(zip(self.leaves, values, strict=True)):
            refs = {"upper_bound": MetricValue(5.0, "utility_points")} if index == 4 else {"required": MetricValue(1.0, "pass")}
            scores.append(ScoreEnvelope(
                "ok", leaf, MetricValue(value, leaf.estimand.units, metadata={"verifier_reasons": reasons}),
                {}, refs, ValidityReport("valid"), evidence_refs,
            ))
        return FamilyScoreSet(POLICY_LEAF_ID, tuple(scores), (POLICY_LEAF_ID, TRANSACTION_LEAF_ID))


def build_scorer(batch: RefundV22Batch) -> RefundV22Scorer:
    return RefundV22Scorer(batch, build_measurement_leaves(batch))


__all__ = [
    "ALLOCATION_LEAF_ID", "COORDINATION_LEAF_ID", "POLICY_LEAF_ID",
    "RefundV22Scorer", "TRANSACTION_LEAF_ID", "UTILITY_LEAF_ID",
    "V22_ESTIMANDS", "build_measurement_leaves", "build_scorer", "metric_names",
]
