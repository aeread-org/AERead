"""Typed score leaves for the two-sided risk-allocation negotiation.

The primary leaf is joint value lost ($ thousands): the surplus the best outcome
for both parties' true private costs makes available, less the surplus the pair
realised, round costs included (``risk_allocation_two_sided.grade_two_sided``).
It is exact and needs no model of either player. Each side's surplus and whether
a signed deal left a side below its outside option are leaves beside it.

Every leaf is ``ok`` on every episode; an invalid move is recorded by
``episode_valid`` and the outcome's typed reason, and the analysis treats it as
missingness, as in the one-sided case. The reference implementation's digest
covers both the two-sided rules and the economics they grade with.
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

SCORER_IMPLEMENTATION_ID = "datacenter_risk_allocation_two_sided_joint_value_v1"
VALIDITY_IMPLEMENTATION_ID = "datacenter_risk_allocation_two_sided_validity_v1"
REFERENCE_IMPLEMENTATION_ID = "datacenter_risk_allocation_two_sided_reference_v1"
VERSION = "0.1.0"
HERE = Path(__file__).parent
REFERENCE_SOURCES = (HERE / "risk_allocation_two_sided.py", HERE / "risk_allocation.py")


def combined_sha256(paths: tuple[Path, ...]) -> str:
    """One digest over several sources, each framed by its name and length."""
    h = hashlib.sha256()
    for p in paths:
        data = p.read_bytes()
        h.update(f"{p.name}:{len(data)}\n".encode())
        h.update(data)
    return h.hexdigest()


def implementation_refs() -> tuple[ImplementationRef, ImplementationRef, ImplementationRef]:
    here = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return (
        ImplementationRef(SCORER_IMPLEMENTATION_ID, VERSION, here),
        ImplementationRef(VALIDITY_IMPLEMENTATION_ID, VERSION, here),
        ImplementationRef(REFERENCE_IMPLEMENTATION_ID, VERSION, combined_sha256(REFERENCE_SOURCES)),
    )


# leaf id: (input scope, units, direction, verifier family, reference kind)
LEAVES: dict[str, tuple[str, str, str, str, str]] = {
    "joint_value_lost": ("terminal_state", "usd_thousands", "minimize", "objective_reference", "exact_optimum"),
    "episode_valid": ("trajectory", "indicator", "maximize", "rule_constraint", "constraint_satisfaction"),
    "allocation_loss": ("terminal_state", "usd_thousands", "minimize", "objective_reference", "exact_optimum"),
    "no_deal_loss": ("terminal_state", "usd_thousands", "minimize", "objective_reference", "exact_optimum"),
    "delay_loss": ("trajectory", "usd_thousands", "minimize", "rule_constraint", "temporal_property"),
    "client_surplus": ("terminal_state", "usd_thousands", "none", "rule_constraint", "state_invariant"),
    "integrator_surplus": ("terminal_state", "usd_thousands", "none", "rule_constraint", "state_invariant"),
    "client_ir_violation": ("terminal_state", "indicator", "minimize", "rule_constraint", "state_invariant"),
    "integrator_ir_violation": ("terminal_state", "indicator", "minimize", "rule_constraint", "state_invariant"),
    "contract_signed": ("terminal_state", "indicator", "none", "rule_constraint", "state_invariant"),
    "efficient_contract_signed": ("terminal_state", "indicator", "maximize", "canonical_reference", "canonical_point"),
}
PRIMARY = "joint_value_lost"
INFORMATION_SET = "full information: both parties' true private costs (a benchmark neither player has)"


def _reference_source(family_case: Mapping[str, Any], leaf_id: str) -> dict[str, Any]:
    return {"leaf": leaf_id, "world": family_case["world"], "integrator_type": family_case["integrator_type"],
            "reference": "the efficient package for both true types, or no deal: risk_allocation_two_sided.grade_two_sided"}


def _leaf(family_case: Mapping[str, Any], leaf_id: str) -> MeasurementLeafSpec:
    scope, units, direction, verifier_family, reference_kind = LEAVES[leaf_id]
    scorer, validity_impl, reference_impl = implementation_refs()
    moves = 2 * len(family_case["world"]["terms"]["ask_premium"])
    domain = ValidityDomainSpec(domain_id=f"{leaf_id}_domain", domain_version=VERSION,
                                schema_ref=f"aeread://datacenter_risk_allocation_two_sided/{leaf_id}/v1", predicate=validity_impl)
    return MeasurementLeafSpec(
        leaf_id=leaf_id,
        leaf_version=VERSION,
        estimand=EstimandSpec(estimand_id=leaf_id, estimand_version=VERSION, input_scope=scope, direction=direction, units=units,
                              validity_domain=domain),
        verifier=VerifierSpec(
            verifier_family=verifier_family,
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id=f"{leaf_id}_reference", reference_version=VERSION, reference_kind=reference_kind, input_scope=scope, units=units,
                source_sha256=hashlib.sha256(canonical_json_bytes(_reference_source(family_case, leaf_id))).hexdigest(),
                implementation=reference_impl,
            ),
            objective_scope=ObjectiveScopeSpec(
                objective_id=leaf_id, objective_version=VERSION, direction=direction, units=units,
                feasible_set="the 24 contract packages at any price both parties sign, and no deal (both outside options)",
                information_set=INFORMATION_SET,
                horizon=f"one negotiation of at most {moves} alternating moves",
                environment_condition="the world's declared risk distributions, break-off probability and round cost, with break-off draws stored per world",
                opponent_condition="both seats are players under test; the benchmark is the pair's best joint outcome, not a best response",
                validity_domain=domain,
            ) if verifier_family == "objective_reference" else None,
        ),
        scorer=scorer,
    )


def primary_measurement_leaf(family_case: Mapping[str, Any]) -> MeasurementLeafSpec:
    return _leaf(family_case, PRIMARY)


def leaf_values(grade: Mapping[str, Any]) -> dict[str, float]:
    signed = grade["signed_package"] is not None
    return {
        "joint_value_lost": float(grade["joint_value_lost"]),
        "episode_valid": float(bool(grade["valid"])),
        "allocation_loss": float(grade["allocation_loss"]),
        "no_deal_loss": float(grade["no_deal_loss"]),
        "delay_loss": float(grade["delay_loss"]),
        "client_surplus": float(grade["client_surplus"]),
        "integrator_surplus": float(grade["integrator_surplus"]),
        "client_ir_violation": float(bool(grade["client_ir_violation"])),
        "integrator_ir_violation": float(bool(grade["integrator_ir_violation"])),
        "contract_signed": float(signed),
        "efficient_contract_signed": float(bool(grade["efficient_contract_signed"])),
    }


class TwoSidedScorer:
    def __init__(self, family_case: Mapping[str, Any]) -> None:
        self._case = family_case

    def __call__(self, scoring_input: Any, *, evidence_refs: tuple[str, ...] = ()) -> FamilyScoreSet:
        return self.score_recorded_outcome(scoring_input.outcome, evidence_refs=evidence_refs or tuple(scoring_input.evidence_refs))

    def score_recorded_outcome(self, outcome: Mapping[str, Any], *, evidence_refs: tuple[str, ...]) -> FamilyScoreSet:
        values = leaf_values(outcome["grade"])
        scores = []
        for leaf_id, (_scope, units, *_rest) in LEAVES.items():
            scores.append(ScoreEnvelope(
                status="ok",
                leaf=_leaf(self._case, leaf_id),
                primary=MetricValue(values[leaf_id], units),
                metrics={},
                reference_values={"reference": MetricValue(0.0, units)} if leaf_id in ("joint_value_lost", "allocation_loss", "no_deal_loss") else {},
                validity=ValidityReport("valid"),
                evidence_refs=evidence_refs,
            ))
        return FamilyScoreSet(primary_leaf_id=PRIMARY, scores=tuple(scores), admission_leaf_ids=(PRIMARY,))


__all__ = [
    "LEAVES",
    "REFERENCE_IMPLEMENTATION_ID",
    "REFERENCE_SOURCES",
    "SCORER_IMPLEMENTATION_ID",
    "TwoSidedScorer",
    "VALIDITY_IMPLEMENTATION_ID",
    "combined_sha256",
    "implementation_refs",
    "leaf_values",
    "primary_measurement_leaf",
]
