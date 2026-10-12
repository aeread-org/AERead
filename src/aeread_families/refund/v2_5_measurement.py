"""Seat-scoped measurement declarations for Refund V2.5."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from aeread.shared_runner.measurement import EstimandSpec, FamilyScoreSet, ImplementationRef, MeasurementLeafSpec, MetricValue, ReferenceSpec, ScoreEnvelope, ValidityDomainSpec, ValidityReport, VerifierSpec
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import FamilyScoringInput

from .v2_5_policy import UnifiedRefundCase

VERSION = "2.5.1"
_DIMENSIONS = (
    "policy_semantic", "workflow", "payment", "evidence", "contract",
    "end_to_end", "operational",
)
DIMENSIONS = _DIMENSIONS
COLLABORATION_DIMENSIONS = (
    "customer_disclosure_integrity", "intake_fact_request_quality",
    "customer_confirmation_integrity", "payment_proposal_binding",
)
SCORING_DIMENSIONS = DIMENSIONS + COLLABORATION_DIMENSIONS
ESTIMANDS = tuple(f"refund_v25_{name}" for name in _DIMENSIONS)
LEAF_IDS = tuple(f"refund_v25_{name}_leaf" for name in _DIMENSIONS)
(POLICY_LEAF_ID, WORKFLOW_LEAF_ID, PAYMENT_LEAF_ID, EVIDENCE_LEAF_ID, CONTRACT_LEAF_ID, END_TO_END_LEAF_ID, OPERATIONAL_LEAF_ID) = LEAF_IDS


def _impl(identifier: str, filename: str) -> ImplementationRef:
    return ImplementationRef(identifier, VERSION, hashlib.sha256(Path(__file__).with_name(filename).read_bytes()).hexdigest())


def build_measurement_leaves(case: UnifiedRefundCase) -> tuple[MeasurementLeafSpec, ...]:
    del case
    domain = ValidityDomainSpec("refund_v25_terminal", VERSION, "refund_v2_5/terminal", _impl("refund_v25_domain", "v2_5_runner.py"))
    leaves = []
    for leaf_id, estimand in zip(LEAF_IDS, ESTIMANDS, strict=True):
        reference = ReferenceSpec(f"{estimand}_reference", VERSION, "constraint_satisfaction", "terminal_state", "pass", hashlib.sha256(canonical_json_bytes({"estimand": estimand, "version": VERSION})).hexdigest(), _impl(f"{estimand}_verifier", "v2_5_runner.py"))
        leaves.append(MeasurementLeafSpec(leaf_id, VERSION, EstimandSpec(estimand, VERSION, "terminal_state", "none", "pass", domain), VerifierSpec("rule_constraint", "deterministic", reference, None), _impl("refund_v25_scorer", "v2_5_measurement.py")))
    return tuple(leaves)


@dataclass(frozen=True, slots=True)
class RefundV25Scorer:
    case: UnifiedRefundCase
    leaves: tuple[MeasurementLeafSpec, ...]

    def __call__(self, scoring_input: FamilyScoringInput, *, evidence_refs: tuple[str, ...] = ()) -> FamilyScoreSet:
        outcome = scoring_input.outcome
        taxonomy = tuple(str(tag) for tag in outcome.get("taxonomy", ()))
        by_dimension = outcome.get("taxonomy_by_dimension", {})
        coverage = outcome.get("coverage_by_dimension", {})
        opportunities = outcome.get("opportunities_by_collaboration_dimension", {})
        scores = tuple(
            ScoreEnvelope(
                "ok", leaf,
                MetricValue(float(outcome[name]), "pass", metadata={
                    "failure_taxonomy": tuple(str(tag) for tag in by_dimension.get(name, taxonomy)),
                    "coverage": float(coverage.get(name, 1.0)),
                    **({
                        "collaboration_metrics": {
                            metric: {
                                "value": float(outcome.get(metric, 0.0)),
                                "coverage": float(coverage.get(metric, 0.0)),
                                "opportunities": int(opportunities.get(metric, 0)),
                                "failure_taxonomy": tuple(str(tag) for tag in by_dimension.get(metric, ())),
                            }
                            for metric in COLLABORATION_DIMENSIONS
                        }
                    } if name == "end_to_end" else {}),
                }),
                {}, {"required": MetricValue(1.0, "pass")}, ValidityReport("valid"), evidence_refs,
            )
            for leaf, name in zip(self.leaves, _DIMENSIONS, strict=True)
        )
        return FamilyScoreSet(END_TO_END_LEAF_ID, scores, (END_TO_END_LEAF_ID, POLICY_LEAF_ID, PAYMENT_LEAF_ID, OPERATIONAL_LEAF_ID))


def build_scorer(case: UnifiedRefundCase) -> RefundV25Scorer:
    return RefundV25Scorer(case, build_measurement_leaves(case))
