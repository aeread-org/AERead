"""Typed Refund V3 measurements for the shared runner.

Seat performance is conditional on the work assigned to that seat. Reference
payment execution and system success remain separate diagnostics. Missing
opportunities never become component scores. A parsed, measurable action can
establish a strict seat failure before later opportunities arise; parse/schema
failures remain typed invalidity, never economic zeros. Only the subject leaf
gates admission.
This module declares a manifest but does not register or approve the family.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from aeread.shared_runner.measurement import (
    EstimandSpec, FamilyScoreSet, ImplementationRef, MeasurementLeafSpec,
    MetricValue, ReferenceSpec, ScoreEnvelope, ValidityDomainSpec, ValidityReport,
    VerifierSpec,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.evaluation import FamilyScoringInput

from . import v3_cases as cases

VERSION = "3.0.0"
FAMILY_ID = "refund_v3"
PLUGIN_ID = "aeread.refund_v3"
SCORER_ID = "refund_v3_measurement"
REFERENCE_IMPLEMENTATION_ID = "refund_v3_environment"
DIMENSIONS = (
    "policy_semantic", "workflow", "contract", "evidence",
    "customer_disclosure", "customer_confirmation", "intake_planning",
    "payment_binding", "payment_execution",
)
SEAT_DIMENSIONS = {
    "policy": ("policy_semantic", "workflow", "contract", "evidence"),
    "customer": ("customer_disclosure", "customer_confirmation"),
    "intake": ("intake_planning",),
    "payments": ("payment_binding", "payment_execution"),
}
PHASE_DIMENSIONS = {
    "customer_claim": ("customer_disclosure",),
    "customer_disclosure": ("customer_disclosure",),
    "customer_confirmation": ("customer_confirmation",),
    "intake_request": ("intake_planning",),
    "policy_turn": SEAT_DIMENSIONS["policy"],
    "payments_execute": SEAT_DIMENSIONS["payments"],
}
SEAT_STRICT_LEAF_ID = "refund_v3_seat_strict_leaf"
PRIMARY_LEAF_ID = SEAT_STRICT_LEAF_ID
SYSTEM_STRICT_LEAF_ID = "refund_v3_system_strict_leaf"
MEASUREMENTS = ("seat_strict", "system_strict") + DIMENSIONS
LEAF_IDS = tuple(f"refund_v3_{name}_leaf" for name in MEASUREMENTS)


def _implementation(identifier: str, filename: str) -> ImplementationRef:
    return ImplementationRef(
        identifier, VERSION,
        hashlib.sha256(Path(__file__).with_name(filename).read_bytes()).hexdigest(),
    )


def build_measurement_leaves(case: cases.Case) -> tuple[MeasurementLeafSpec, ...]:
    scorer = _implementation(SCORER_ID, "v3_measurement.py")
    reference = _implementation(REFERENCE_IMPLEMENTATION_ID, "v3_environment.py")
    domain = ValidityDomainSpec(
        "refund_v3_terminal", VERSION, "refund_v3/terminal", scorer,
    )
    source = hashlib.sha256(canonical_json_bytes(cases.payload(case))).hexdigest()
    # Verified action envelopes determine whether an outcome's numeric values
    # are measurable at all, including component and system diagnostics.
    return tuple(
        MeasurementLeafSpec(
            leaf_id, VERSION,
            EstimandSpec(f"refund_v3_{name}", VERSION, "trajectory",
                         "maximize", "pass", domain),
            VerifierSpec("rule_constraint", "deterministic", ReferenceSpec(
                f"refund_v3_{name}_reference", VERSION, "constraint_satisfaction",
                "trajectory", "pass", source, reference,
            )),
            scorer,
        )
        for name, leaf_id in zip(MEASUREMENTS, LEAF_IDS, strict=True)
    )


def family_manifest() -> FamilyManifest:
    """Declare finalize-time policy without entering the trusted registry."""
    return FamilyManifest.from_dict({
        "spec_version": FamilyManifest.SPEC_VERSION,
        "family": {"id": FAMILY_ID, "version": VERSION, "plugin_id": PLUGIN_ID},
        "environment": {
            "topology": "sequential", "needs_tools": False, "needs_sandbox": False,
            "phase_specs": ["customer_claim", "intake_request", "customer_disclosure",
                            "policy_turn", "customer_confirmation", "payments_execute"],
        },
        "roles": {seat: {"testable": True, "scripted_policies": ["scripted"]}
                  for seat in cases.SEATS},
        "measurement": {
            "primary_estimand": "refund_v3_seat_strict",
            "measurement_kind": "property_or_answer", "direction": "maximize",
            "outcome_support": "unit_interval",
            "leaves": [{"leaf_id": leaf_id, "scope": "finalize_time",
                        "seat_scope": "subject_seat" if leaf_id == PRIMARY_LEAF_ID else "cell"}
                       for leaf_id in LEAF_IDS],
            "primary_leaf_id": PRIMARY_LEAF_ID,
            "admission_leaf_ids": [PRIMARY_LEAF_ID],
        },
        "scoring": {"scorer_id": SCORER_ID, "oracle_id": REFERENCE_IMPLEMENTATION_ID},
    })


def _fraction(value: object, *, binary: bool = False) -> bool:
    return (type(value) in (int, float) and math.isfinite(value)
            and (value in (0, 1) if binary else 0 <= value <= 1))


def _mapping(value: object) -> Mapping:
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True, slots=True)
class RefundV3Scorer:
    case: cases.Case
    leaves: tuple[MeasurementLeafSpec, ...]

    def __call__(
        self, scoring_input: FamilyScoringInput, *, evidence_refs: tuple[str, ...] = (),
    ) -> FamilyScoreSet:
        if not isinstance(scoring_input, FamilyScoringInput):
            raise TypeError("Refund V3 requires FamilyScoringInput")
        outcome = scoring_input.outcome
        metrics = _mapping(outcome.get("metrics"))
        coverage = _mapping(outcome.get("coverage"))
        strict = _mapping(outcome.get("seat_strict"))
        refs = evidence_refs or scoring_input.evidence_refs
        metadata = {
            "operational_status": outcome.get("operational_status"),
            "failure_taxonomy": tuple(outcome.get("taxonomy", ())),
            "total_collection_cost": outcome.get("total_collection_cost"),
        }
        contract_failures: dict[str, tuple[str, ...]] = {}
        action_invalidity: dict[str, str] = {}
        component_invalidity: dict[str, str] = {}
        for phase in scoring_input.phase_instances:
            for action in phase.actions:
                reason = None
                if not action.parse.ok:
                    reason = f"invalid_action_parse:{action.parse.error_code}"
                elif action.parse.action is None:
                    reason = "missing_parsed_action"
                elif action.legality is None:
                    reason = "missing_legality_result"
                elif not action.envelope.valid and action.legality.legal:
                    reason = "invalid_action_envelope"
                if reason:
                    action_invalidity.setdefault(action.seat_id, reason)
                    for dimension in PHASE_DIMENSIONS.get(phase.phase_id, ()):
                        component_invalidity.setdefault(dimension, reason)
                elif not action.legality.legal:
                    # Only a parsed action with an actual legality verdict can
                    # establish a measured contract failure before completion.
                    contract_failures[action.seat_id] = (
                        *contract_failures.get(action.seat_id, ()), action.legality.reason,
                    )

        def component_reason(name: str) -> str | None:
            if name in component_invalidity:
                return component_invalidity[name]
            covered = coverage.get(name)
            if not _fraction(covered, binary=True):
                return f"invalid_coverage:{name}"
            if covered == 0 or metrics.get(name) is None:
                return f"uncovered_component:{name}"
            if not _fraction(metrics[name]):
                return f"invalid_component:{name}"
            return None

        def seat_reason(seat: str) -> str | None:
            if seat in action_invalidity:
                return action_invalidity[seat]
            if seat in contract_failures:
                return None
            for name in SEAT_DIMENSIONS[seat]:
                reason = component_reason(name)
                if reason:
                    return reason
            if seat == "payments" and not _fraction(
                outcome.get("payment_conditional_execution"), binary=True,
            ):
                return "invalid_payment_conditional_execution"
            if not _fraction(strict.get(seat), binary=True):
                return f"invalid_seat_strict:{seat}"
            return None

        # A measurable failed action establishes zero without imputing any of
        # its unobserved components. Malformed/unknown seats have no utility.
        utilities = {
            seat: MetricValue(0.0 if seat in contract_failures else strict[seat], "pass", {
                **metadata,
                **({"measurement_basis": "observed_contract_failure",
                    "contract_failure_reasons": contract_failures[seat]}
                   if seat in contract_failures else {}),
                **({"payment_conditional_execution": outcome.get("payment_conditional_execution")}
                   if seat == "payments" else {}),
            })
            for seat in cases.SEATS if seat_reason(seat) is None
        }
        scores = []
        for name, leaf in zip(MEASUREMENTS, self.leaves, strict=True):
            reason = None
            value = None
            details = dict(metadata)
            if name == "seat_strict":
                subjects = scoring_input.seat_context.subject_seats
                if not subjects:
                    reason = "no_subject_seat"
                elif len(subjects) != 1:
                    reason = "ambiguous_subject_seat"
                elif subjects[0] not in SEAT_DIMENSIONS:
                    reason = "unknown_subject_seat"
                elif subjects[0] != self.case.seat:
                    reason = "unscored_crossseat_probe"
                else:
                    reason = seat_reason(subjects[0])
                    if reason is None:
                        value = utilities[subjects[0]].value
                        details.update(utilities[subjects[0]].metadata)
                        details["subject_seat"] = subjects[0]
            elif name == "system_strict":
                reason = next(iter(action_invalidity.values()), None)
                if reason is None:
                    reason = next((component_reason(k) for k in DIMENSIONS
                                   if component_reason(k)), None)
                if reason is None:
                    reason = next((f"invalid_seat_strict:{s}" for s in cases.SEATS
                                   if not _fraction(strict.get(s), binary=True)), None)
                value = outcome.get(name)
                if reason is None and not _fraction(value, binary=True):
                    reason = "invalid_system_strict"
            else:
                reason = component_reason(name)
                value = metrics.get(name)
                details["coverage"] = coverage.get(name)
            scores.append(ScoreEnvelope(
                status="invalid_measurement" if reason else "ok", leaf=leaf,
                primary=None if reason else MetricValue(value, "pass", details),
                metrics={}, reference_values={"required": MetricValue(1, "pass")},
                validity=ValidityReport("invalid", (reason,)) if reason else ValidityReport("valid"),
                evidence_refs=refs,
                utility_by_seat=utilities if name == "seat_strict" else {},
            ))
        return FamilyScoreSet(PRIMARY_LEAF_ID, tuple(scores), (PRIMARY_LEAF_ID,))


def build_scorer(case: cases.Case) -> RefundV3Scorer:
    return RefundV3Scorer(case, build_measurement_leaves(case))
