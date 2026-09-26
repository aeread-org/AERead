"""Typed score leaves for the playbook-menu negotiation.

The primary leaf is decision regret ($ thousands): at each move, what the client's
action gives up against the best play of a client who knows how integrators in this
market choose and price their menus, summed over the episode
(``risk_allocation_menu.grade_menu``). Beside it: whether the client signed the item
best for it, what it paid over the integrator's floor, and its realised cost over
the best it could have attained. The reference implementation's digest covers the
menu module and the economics it grades with.
"""

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

from .risk_allocation_two_sided_measurement import combined_sha256

SCORER_IMPLEMENTATION_ID = "datacenter_risk_allocation_menu_decision_regret_v1"
VALIDITY_IMPLEMENTATION_ID = "datacenter_risk_allocation_menu_validity_v1"
REFERENCE_IMPLEMENTATION_ID = "datacenter_risk_allocation_menu_reference_v1"
VERSION = "0.1.0"
HERE = Path(__file__).parent
REFERENCE_SOURCES = (HERE / "risk_allocation_menu.py", HERE / "risk_allocation.py")


def implementation_refs() -> tuple[ImplementationRef, ImplementationRef, ImplementationRef]:
    here = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return (ImplementationRef(SCORER_IMPLEMENTATION_ID, VERSION, here), ImplementationRef(VALIDITY_IMPLEMENTATION_ID, VERSION, here),
            ImplementationRef(REFERENCE_IMPLEMENTATION_ID, VERSION, combined_sha256(REFERENCE_SOURCES)))


LEAVES: dict[str, tuple[str, str, str, str, str]] = {
    "decision_regret": ("terminal_state", "usd_thousands", "minimize", "objective_reference", "exact_optimum"),
    "episode_valid": ("trajectory", "indicator", "maximize", "rule_constraint", "constraint_satisfaction"),
    "signed_best_item": ("terminal_state", "indicator", "maximize", "canonical_reference", "canonical_point"),
    "cost_over_best_attainable": ("terminal_state", "usd_thousands", "minimize", "objective_reference", "exact_optimum"),
    "contract_signed": ("terminal_state", "indicator", "none", "rule_constraint", "state_invariant"),
    "refused_counters": ("trajectory", "count", "none", "rule_constraint", "temporal_property"),
}
PRIMARY = "decision_regret"
INFORMATION_SET = {
    "decision_regret": "a client who knows how integrators in this market choose their playbook and price each option (not this integrator's costs)",
    "cost_over_best_attainable": "full information: the integrator's true costs and floor prices (a diagnostic)",
}


def _leaf(family_case: Mapping[str, Any], leaf_id: str) -> MeasurementLeafSpec:
    scope, units, direction, verifier_family, kind = LEAVES[leaf_id]
    scorer, validity_impl, reference_impl = implementation_refs()
    rounds = len(family_case["world"]["terms"]["ask_premium"]) - 1
    domain = ValidityDomainSpec(domain_id=f"{leaf_id}_domain", domain_version=VERSION,
                                schema_ref=f"aeread://datacenter_risk_allocation_menu/{leaf_id}/v1", predicate=validity_impl)
    source = {"leaf": leaf_id, "world": family_case["world"], "integrator_type": family_case["integrator_type"], "team": family_case["team"],
              "reference": "risk_allocation_menu.MenuSolver"}
    return MeasurementLeafSpec(
        leaf_id=leaf_id, leaf_version=VERSION,
        estimand=EstimandSpec(estimand_id=leaf_id, estimand_version=VERSION, input_scope=scope, direction=direction, units=units, validity_domain=domain),
        verifier=VerifierSpec(
            verifier_family=verifier_family, evaluation_class="deterministic",
            reference=ReferenceSpec(reference_id=f"{leaf_id}_reference", reference_version=VERSION, reference_kind=kind, input_scope=scope, units=units,
                                    source_sha256=hashlib.sha256(canonical_json_bytes(source)).hexdigest(), implementation=reference_impl),
            objective_scope=ObjectiveScopeSpec(
                objective_id=leaf_id, objective_version=VERSION, direction=direction, units=units,
                feasible_set="the eight items of the posted menu at any price the integrator signs, and the two outside options",
                information_set=INFORMATION_SET[leaf_id], horizon=f"one negotiation of at most {rounds} counters",
                environment_condition="the world's declared risk distributions, break-off probability and round cost",
                opponent_condition="the scripted integrator's declared playbook and pricing policy, its private type drawn from the declared prior",
                validity_domain=domain,
            ) if verifier_family == "objective_reference" else None,
        ),
        scorer=scorer,
    )


def primary_measurement_leaf(family_case: Mapping[str, Any]) -> MeasurementLeafSpec:
    return _leaf(family_case, PRIMARY)


def leaf_values(grade: Mapping[str, Any]) -> dict[str, float]:
    return {
        "decision_regret": float(grade["decision_regret"]),
        "episode_valid": float(bool(grade["valid"])),
        "signed_best_item": float(bool(grade["signed_best_item"])),
        "cost_over_best_attainable": float(grade["cost_over_best_attainable"]),
        "contract_signed": float(grade["signed_item"] is not None),
        "refused_counters": float(grade["refused_counters"]),
    }


class MenuScorer:
    def __init__(self, family_case: Mapping[str, Any]) -> None:
        self._case = family_case

    def __call__(self, scoring_input: Any, *, evidence_refs: tuple[str, ...] = ()) -> FamilyScoreSet:
        return self.score_recorded_outcome(scoring_input.outcome, evidence_refs=evidence_refs or tuple(scoring_input.evidence_refs))

    def score_recorded_outcome(self, outcome: Mapping[str, Any], *, evidence_refs: tuple[str, ...]) -> FamilyScoreSet:
        values = leaf_values(outcome["grade"])
        scores = tuple(ScoreEnvelope(status="ok", leaf=_leaf(self._case, leaf_id), primary=MetricValue(values[leaf_id], units), metrics={},
                                     reference_values={"reference": MetricValue(0.0, units)} if leaf_id in ("decision_regret", "cost_over_best_attainable") else {},
                                     validity=ValidityReport("valid"), evidence_refs=evidence_refs)
                       for leaf_id, (_s, units, *_r) in LEAVES.items())
        return FamilyScoreSet(primary_leaf_id=PRIMARY, scores=scores, admission_leaf_ids=(PRIMARY,))


__all__ = ["LEAVES", "MenuScorer", "REFERENCE_IMPLEMENTATION_ID", "REFERENCE_SOURCES", "SCORER_IMPLEMENTATION_ID", "VALIDITY_IMPLEMENTATION_ID",
           "implementation_refs", "leaf_values", "primary_measurement_leaf"]
