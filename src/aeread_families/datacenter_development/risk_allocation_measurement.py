"""Typed score leaves for the integrator-client risk-allocation case.

The primary leaf is decision regret: at every move, what the action gives up
against the best action on the model's own information, in expected cost to
the model ($ thousands), summed over the episode (``risk_allocation_environment.grade``).
The reference is the exact programme in ``risk_allocation.py``; its source is
pinned under the reference implementation id, so a change to the reference
changes the identity it is scored under.

Every leaf is ``ok`` on every episode. An invalid move (a malformed or illegal
reply, or a reply cut off by the output limit) is not an invalid measurement:
``episode_valid`` records it, the outcome carries its typed reason, and the
analysis treats such episodes as missingness. Scoring them ``invalid_measurement``
would exclude the receipt as a scorer failure, which it is not.
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

SCORER_IMPLEMENTATION_ID = "datacenter_risk_allocation_decision_regret_v1"
VALIDITY_IMPLEMENTATION_ID = "datacenter_risk_allocation_validity_v1"
REFERENCE_IMPLEMENTATION_ID = "datacenter_risk_allocation_reference_v1"
VERSION = "0.1.0"
REFERENCE_SOURCE = Path(__file__).with_name("risk_allocation.py")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def implementation_refs() -> tuple[ImplementationRef, ImplementationRef, ImplementationRef]:
    """Scorer and validity are this file; the reference is the solver's source."""
    here = _sha256(Path(__file__))
    return (
        ImplementationRef(SCORER_IMPLEMENTATION_ID, VERSION, here),
        ImplementationRef(VALIDITY_IMPLEMENTATION_ID, VERSION, here),
        ImplementationRef(REFERENCE_IMPLEMENTATION_ID, VERSION, _sha256(REFERENCE_SOURCE)),
    )


def _reference_source(family_case: Mapping[str, Any], leaf_id: str) -> dict[str, Any]:
    return {
        "leaf": leaf_id,
        "seat": family_case["seat"],
        "world": family_case["world"],
        "packages_per_request": family_case.get("packages_per_request", 1),
        "reference": "best play on the model's own information: risk_allocation.Solver",
    }


def _leaf(family_case: Mapping[str, Any], *, leaf_id: str, input_scope: str, units: str, direction: str,
          verifier_family: str, reference_kind: str) -> MeasurementLeafSpec:
    scorer, validity_impl, reference_impl = implementation_refs()
    rounds = len(family_case["world"]["terms"]["ask_premium"]) - 1
    domain = ValidityDomainSpec(
        domain_id=f"{leaf_id}_domain",
        domain_version=VERSION,
        schema_ref=f"aeread://datacenter_risk_allocation/{leaf_id}/v1",
        predicate=validity_impl,
    )
    return MeasurementLeafSpec(
        leaf_id=leaf_id,
        leaf_version=VERSION,
        estimand=EstimandSpec(
            estimand_id=leaf_id,
            estimand_version=VERSION,
            input_scope=input_scope,
            direction=direction,
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
                source_sha256=hashlib.sha256(canonical_json_bytes(_reference_source(family_case, leaf_id))).hexdigest(),
                implementation=reference_impl,
            ),
            objective_scope=ObjectiveScopeSpec(
                objective_id=leaf_id,
                objective_version=VERSION,
                direction=direction,
                units=units,
                feasible_set="the 24 contract packages at any price the counterpart signs, and walking away to the outside option",
                information_set=INFORMATION_SET[leaf_id],
                horizon=f"one negotiation of at most {rounds} rounds",
                environment_condition="the world's declared risk distributions, break-off probability and round cost",
                opponent_condition="the scripted counterpart's declared pricing rule, its private type drawn from the declared prior",
                validity_domain=domain,
            ) if verifier_family == "objective_reference" else None,
        ),
        scorer=scorer,
    )


# leaf id: (input scope, units, direction, verifier family, reference kind). Decision regret is
# scored against the exact optimum from the terminal state, which records every decision the
# model took (the kernel admits exact_optimum only over a terminal state or a distribution).
LEAVES: dict[str, tuple[str, str, str, str, str]] = {
    "decision_regret": ("terminal_state", "usd_thousands", "minimize", "objective_reference", "exact_optimum"),
    "episode_valid": ("trajectory", "indicator", "maximize", "rule_constraint", "constraint_satisfaction"),
    "allocation_gap": ("terminal_state", "usd_thousands", "minimize", "objective_reference", "exact_optimum"),
    "price_gap": ("terminal_state", "usd_thousands", "minimize", "objective_reference", "comparison_baseline"),
    "contract_signed": ("terminal_state", "indicator", "none", "rule_constraint", "state_invariant"),
    "efficient_contract_signed": ("terminal_state", "indicator", "maximize", "canonical_reference", "canonical_point"),
    "switched_package": ("trajectory", "indicator", "none", "rule_constraint", "temporal_property"),
    "refused_rounds": ("trajectory", "count", "none", "rule_constraint", "temporal_property"),
}
PRIMARY = "decision_regret"
INFORMATION_SET = {
    "decision_regret": "the model's own: the declared prior over the counterpart's private costs, narrowed by every price it has seen",
    "allocation_gap": "full information: both parties' true types (a diagnostic, not the score)",
    "price_gap": "full information: the counterpart's true floor or final bid for the signed package (a diagnostic)",
}


def primary_measurement_leaf(family_case: Mapping[str, Any]) -> MeasurementLeafSpec:
    scope, units, direction, verifier, kind = LEAVES[PRIMARY]
    return _leaf(family_case, leaf_id=PRIMARY, input_scope=scope, units=units, direction=direction,
                 verifier_family=verifier, reference_kind=kind)


def leaf_values(grade: Mapping[str, Any]) -> dict[str, float]:
    signed = grade["signed_package"] is not None
    return {
        "decision_regret": float(grade["decision_regret"]),
        "episode_valid": float(bool(grade["valid"])),
        "allocation_gap": float(grade["allocation_gap"]),
        "price_gap": float(grade["price_gap"]) if signed else 0.0,
        "contract_signed": float(signed),
        "efficient_contract_signed": float(signed and grade["signed_package"] == grade["efficient_package"]),
        "switched_package": float(bool(grade["switched_package"])),
        "refused_rounds": float(grade["refused_rounds"]),
    }


class RiskAllocationScorer:
    def __init__(self, family_case: Mapping[str, Any]) -> None:
        self._case = family_case

    def __call__(self, scoring_input: Any, *, evidence_refs: tuple[str, ...] = ()) -> FamilyScoreSet:
        """The kernel's once-per-episode hook: ``scoring_input.outcome`` is the plugin's
        ``outcome`` over the verified re-execution, which carries ``grade``."""
        return self.score_recorded_outcome(scoring_input.outcome, evidence_refs=evidence_refs or tuple(scoring_input.evidence_refs))

    def score_recorded_outcome(self, outcome: Mapping[str, Any], *, evidence_refs: tuple[str, ...]) -> FamilyScoreSet:
        values = leaf_values(outcome["grade"])
        scores = []
        for leaf_id, (scope, units, direction, verifier, kind) in LEAVES.items():
            leaf = _leaf(self._case, leaf_id=leaf_id, input_scope=scope, units=units, direction=direction,
                         verifier_family=verifier, reference_kind=kind)
            scores.append(ScoreEnvelope(
                status="ok",
                leaf=leaf,
                primary=MetricValue(values[leaf_id], units),
                metrics={},
                reference_values={"reference": MetricValue(0.0, units)} if leaf_id in ("decision_regret", "allocation_gap") else {},
                validity=ValidityReport("valid"),
                evidence_refs=evidence_refs,
            ))
        return FamilyScoreSet(primary_leaf_id=PRIMARY, scores=tuple(scores), admission_leaf_ids=(PRIMARY,))


__all__ = [
    "LEAVES",
    "REFERENCE_IMPLEMENTATION_ID",
    "RiskAllocationScorer",
    "SCORER_IMPLEMENTATION_ID",
    "VALIDITY_IMPLEMENTATION_ID",
    "implementation_refs",
    "leaf_values",
    "primary_measurement_leaf",
]
