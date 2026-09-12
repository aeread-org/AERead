"""Typed measurements for the Refund V2.1 shared-runner adapter."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
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
from aeread.shared_runner.task.evaluation import FamilyScoringInput

from .v2_environment import RefundV2Case


VERSION = "2.1.0"
DOMAIN_ID = "refund_v21_terminal_domain"
DOMAIN_VERSION = VERSION
UTILITY_LEAF_ID = "refund_v21_system_utility_leaf"
TRANSACTION_LEAF_ID = "refund_v21_transaction_leaf"
COORDINATION_LEAF_ID = "refund_v21_coordination_leaf"
POLICY_LEAF_ID = "refund_v21_policy_compliance_leaf"


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _file_digest(filename: str) -> str:
    return hashlib.sha256(Path(__file__).with_name(filename).read_bytes()).hexdigest()


def implementation(identifier: str, filename: str = "v2_measurement.py") -> ImplementationRef:
    return ImplementationRef(identifier, VERSION, _file_digest(filename))


def _domain() -> ValidityDomainSpec:
    return ValidityDomainSpec(
        domain_id=DOMAIN_ID,
        domain_version=DOMAIN_VERSION,
        schema_ref="refund_v2_1/terminal_state",
        predicate=implementation("refund_v21_domain_predicate", "v2_environment.py"),
    )


def _leaf(
    *,
    leaf_id: str,
    estimand_id: str,
    units: str,
    direction: str,
    reference_kind: str,
    reference_id: str,
    reference_impl: str,
    objective: bool = False,
) -> MeasurementLeafSpec:
    domain = _domain()
    reference = ReferenceSpec(
        reference_id=reference_id,
        reference_version=VERSION,
        reference_kind=reference_kind,
        input_scope="terminal_state" if objective else "trajectory",
        units=units,
        source_sha256=_digest({"reference": reference_id, "version": VERSION}),
        implementation=implementation(reference_impl, "v2_environment.py"),
    )
    objective_scope = None
    if objective:
        objective_scope = ObjectiveScopeSpec(
            objective_id=estimand_id,
            objective_version=VERSION,
            direction=direction,
            units=units,
            feasible_set="verified Refund V2.1 terminal outcomes",
            information_set="facts revealed in the sealed trajectory",
            horizon="one pinned Refund V2.1 episode",
            environment_condition="pinned Refund V2.1 case and policy",
            opponent_condition="declared active or scripted seat configuration",
            validity_domain=domain,
        )
    return MeasurementLeafSpec(
        leaf_id=leaf_id,
        leaf_version=VERSION,
        estimand=EstimandSpec(
            estimand_id=estimand_id,
            estimand_version=VERSION,
            input_scope=reference.input_scope,
            direction=direction,
            units=units,
            validity_domain=domain,
        ),
        verifier=VerifierSpec(
            verifier_family="objective_reference" if objective else "rule_constraint",
            evaluation_class="deterministic",
            reference=reference,
            objective_scope=objective_scope,
        ),
        scorer=implementation("refund_v21_scorer"),
    )


def build_measurement_leaves(case: RefundV2Case) -> tuple[MeasurementLeafSpec, ...]:
    del case
    return (
        _leaf(
            leaf_id=POLICY_LEAF_ID,
            estimand_id="refund_v21_policy_compliance",
            units="pass",
            direction="none",
            reference_kind="constraint_satisfaction",
            reference_id="refund_v21_policy_reference",
            reference_impl="refund_v21_policy_verifier",
        ),
        _leaf(
            leaf_id=TRANSACTION_LEAF_ID,
            estimand_id="refund_v21_transaction",
            units="pass",
            direction="none",
            reference_kind="state_invariant",
            reference_id="refund_v21_transaction_reference",
            reference_impl="refund_v21_transaction_verifier",
        ),
        _leaf(
            leaf_id=COORDINATION_LEAF_ID,
            estimand_id="refund_v21_coordination",
            units="pass",
            direction="none",
            reference_kind="temporal_property",
            reference_id="refund_v21_coordination_reference",
            reference_impl="refund_v21_coordination_verifier",
        ),
        _leaf(
            leaf_id=UTILITY_LEAF_ID,
            estimand_id="refund_v21_system_utility",
            units="utility_points",
            direction="maximize",
            reference_kind="objective_upper_bound",
            reference_id="refund_v21_utility_reference",
            reference_impl="refund_v21_utility_verifier",
            objective=True,
        ),
    )


def _pass(leaf: MeasurementLeafSpec, value: float, *, refs: tuple[str, ...], reasons: tuple[str, ...]) -> ScoreEnvelope:
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(value, leaf.estimand.units, metadata={"verifier_reasons": reasons}),
        metrics={},
        reference_values={"required": MetricValue(1.0, leaf.estimand.units)},
        validity=ValidityReport("valid"),
        evidence_refs=refs,
    )


@dataclass(frozen=True, slots=True)
class RefundV21Scorer:
    case: RefundV2Case
    leaves: tuple[MeasurementLeafSpec, ...]

    def __call__(self, scoring_input: FamilyScoringInput, *, evidence_refs: tuple[str, ...] = ()) -> FamilyScoreSet:
        outcome = scoring_input.outcome
        reasons = tuple(str(item) for item in outcome.get("verifier_reasons", ()))
        utility = float(outcome["utility_score"])
        transaction = float(outcome["transaction_score"])
        coordination = float(outcome["coordination_score"])
        policy = 1.0 if bool(outcome.get("policy_compliant")) else 0.0
        scores = (
            _pass(self.leaves[0], policy, refs=evidence_refs, reasons=reasons),
            _pass(self.leaves[1], transaction, refs=evidence_refs, reasons=reasons),
            _pass(self.leaves[2], coordination, refs=evidence_refs, reasons=reasons),
            ScoreEnvelope(
                status="ok",
                leaf=self.leaves[3],
                primary=MetricValue(
                    utility,
                    "utility_points",
                    metadata={
                        "aggregation": "system_outcome",
                        "cross_family_comparable": False,
                    },
                ),
                metrics={},
                reference_values={"upper_bound": MetricValue(2.0, "utility_points")},
                validity=ValidityReport("valid"),
                evidence_refs=evidence_refs,
            ),
        )
        return FamilyScoreSet(
            primary_leaf_id=POLICY_LEAF_ID,
            scores=scores,
            admission_leaf_ids=(POLICY_LEAF_ID, TRANSACTION_LEAF_ID),
        )


def build_scorer(case: RefundV2Case) -> RefundV21Scorer:
    return RefundV21Scorer(case, build_measurement_leaves(case))


__all__ = [
    "COORDINATION_LEAF_ID",
    "POLICY_LEAF_ID",
    "RefundV21Scorer",
    "TRANSACTION_LEAF_ID",
    "UTILITY_LEAF_ID",
    "build_measurement_leaves",
    "build_scorer",
    "implementation",
]
