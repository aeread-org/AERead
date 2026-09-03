"""Typed measurement contract for Refund V1.2."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.measurement import (
    EstimandSpec,
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

from . import environment as rf


MEASUREMENT_VERSION = "1.2.0"
DOMAIN_ID = "refund_v1_2_terminal_domain"
DOMAIN_VERSION = "1.2.0"

CANONICAL_DECISION_LEAF_ID = "refund_canonical_decision_leaf"
INFORMATION_CONSTRAINT_LEAF_ID = "refund_information_constraint_leaf"
TEMPORAL_TRANSACTION_LEAF_ID = "refund_temporal_transaction_leaf"
STATE_INVARIANT_LEAF_ID = "refund_state_invariant_leaf"
OBJECTIVE_LEAF_ID = "refund_joint_utility_leaf"


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _source_digest(filename: str) -> str:
    return hashlib.sha256(Path(__file__).with_name(filename).read_bytes()).hexdigest()


def _implementation(identifier: str, filename: str) -> ImplementationRef:
    return ImplementationRef(
        implementation_id=identifier,
        version=MEASUREMENT_VERSION,
        content_sha256=_source_digest(filename),
    )


def _validity_domain() -> ValidityDomainSpec:
    return ValidityDomainSpec(
        domain_id=DOMAIN_ID,
        domain_version=DOMAIN_VERSION,
        schema_ref="refund_v1_2/outcome/1",
        predicate=_implementation("refund_policy_oracle_v1", "environment.py"),
    )


def _pass_leaf(
    *,
    leaf_id: str,
    estimand_id: str,
    input_scope: str,
    verifier_family: str,
    reference_id: str,
    reference_kind: str,
    reference_source: Any,
) -> MeasurementLeafSpec:
    domain = _validity_domain()
    return MeasurementLeafSpec(
        leaf_id=leaf_id,
        leaf_version=MEASUREMENT_VERSION,
        estimand=EstimandSpec(
            estimand_id=estimand_id,
            estimand_version=MEASUREMENT_VERSION,
            input_scope=input_scope,
            direction="none",
            units="pass",
            validity_domain=domain,
        ),
        verifier=VerifierSpec(
            verifier_family=verifier_family,
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id=reference_id,
                reference_version=MEASUREMENT_VERSION,
                reference_kind=reference_kind,
                input_scope=input_scope,
                units="pass",
                source_sha256=_digest(reference_source),
                implementation=_implementation("refund_oracle_policy_v1", "environment.py"),
            ),
        ),
        scorer=_implementation("refund_typed_measurements_v1_2", "measurement.py"),
    )


def build_measurement_leaves(case: rf.RefundCase) -> tuple[MeasurementLeafSpec, ...]:
    """Declare each Refund claim independently; no composite operation score."""
    expected = rf.oracle_outcome(case)
    policy_reference = {
        "policy": rf.policy_document(),
        "expected_decision": expected["decision"],
    }
    transaction_reference = {
        "expected_decision": expected["decision"],
        "rule": (
            "exactly one matching proposal must precede exactly one explicit customer "
            "confirmation, which must precede exactly one matching mutation; otherwise "
            "no refund transaction event or mutation is permitted"
        ),
    }
    canonical = _pass_leaf(
        leaf_id=CANONICAL_DECISION_LEAF_ID,
        estimand_id="refund_canonical_decision",
        input_scope="terminal_state",
        verifier_family="canonical_reference",
        reference_id="refund_policy_accepted_resolution",
        reference_kind="canonical_set",
        reference_source=policy_reference,
    )
    information = _pass_leaf(
        leaf_id=INFORMATION_CONSTRAINT_LEAF_ID,
        estimand_id="refund_information_constraint",
        input_scope="trajectory",
        verifier_family="rule_constraint",
        reference_id="refund_required_information_rule",
        reference_kind="constraint_satisfaction",
        reference_source=policy_reference,
    )
    temporal = _pass_leaf(
        leaf_id=TEMPORAL_TRANSACTION_LEAF_ID,
        estimand_id="refund_temporal_transaction",
        input_scope="trajectory",
        verifier_family="rule_constraint",
        reference_id="refund_confirmation_before_mutation_rule",
        reference_kind="temporal_property",
        reference_source=transaction_reference,
    )
    invariant = _pass_leaf(
        leaf_id=STATE_INVARIANT_LEAF_ID,
        estimand_id="refund_state_invariant",
        input_scope="terminal_state",
        verifier_family="rule_constraint",
        reference_id="refund_authorized_state_change_rule",
        reference_kind="state_invariant",
        reference_source={
            "modeled_state_scope": "order_state",
            "allowed_refund_fields": [
                "refund_amount",
                "refund_method",
                "refund_status",
            ],
            "transaction": transaction_reference,
        },
    )
    domain = _validity_domain()
    objective = MeasurementLeafSpec(
        leaf_id=OBJECTIVE_LEAF_ID,
        leaf_version=MEASUREMENT_VERSION,
        estimand=EstimandSpec(
            estimand_id="refund_joint_utility",
            estimand_version=MEASUREMENT_VERSION,
            input_scope="terminal_state",
            direction="maximize",
            units="usd_equivalent",
            validity_domain=domain,
        ),
        verifier=VerifierSpec(
            verifier_family="objective_reference",
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id="refund_full_information_utility_upper_bound",
                reference_version=MEASUREMENT_VERSION,
                reference_kind="objective_upper_bound",
                input_scope="terminal_state",
                units="usd_equivalent",
                source_sha256=_digest(expected),
                implementation=_implementation("refund_oracle_policy_v1", "environment.py"),
            ),
            objective_scope=ObjectiveScopeSpec(
                objective_id="refund_joint_utility",
                objective_version=MEASUREMENT_VERSION,
                direction="maximize",
                units="usd_equivalent",
                feasible_set="policy-valid terminal refund resolutions and authorized state changes",
                information_set="customer facts revealed in the recorded trajectory",
                horizon="one pinned Refund V1.2 episode",
                environment_condition="pinned refund case and policy",
                opponent_condition="customer profile declared in the RunPlan",
                validity_domain=domain,
            ),
        ),
        scorer=_implementation("refund_typed_measurements_v1_2", "measurement.py"),
    )
    return canonical, information, temporal, invariant, objective


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    return float(value)


def _pass_score(
    leaf: MeasurementLeafSpec,
    result: Mapping[str, Any],
    *,
    evidence_refs: tuple[str, ...],
) -> ScoreEnvelope:
    satisfied = bool(result.get("satisfied"))
    metrics: dict[str, MetricValue] = {}
    for key, value in result.items():
        if key == "satisfied" or isinstance(value, bool):
            if key != "satisfied":
                metrics[key] = MetricValue(1.0 if value else 0.0, "pass")
        elif isinstance(value, (int, float)):
            metrics[key] = MetricValue(float(value), "count")
    metadata = {
        key: value
        for key, value in result.items()
        if key != "satisfied" and not isinstance(value, (bool, int, float))
    }
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(1.0 if satisfied else 0.0, "pass", metadata=metadata),
        metrics=metrics,
        reference_values={"required": MetricValue(1.0, "pass")},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


@dataclass(frozen=True, slots=True)
class RefundV12Scorer:
    case: rf.RefundCase
    leaves: tuple[MeasurementLeafSpec, ...]

    def __call__(
        self,
        outcome: Mapping[str, Any],
        *,
        evidence_refs: Sequence[str] = (),
    ) -> tuple[ScoreEnvelope, ...]:
        compliance = outcome.get("policy_compliance")
        if not isinstance(compliance, Mapping) or not isinstance(
            compliance.get("leaves"), Mapping
        ):
            raise ValueError("Refund outcome has no policy-compliance leaves")
        results = compliance["leaves"]
        references = tuple(evidence_refs)
        scores = [
            _pass_score(self.leaves[index], results[name], evidence_refs=references)
            for index, name in enumerate(
                (
                    "canonical_decision",
                    "information_constraint",
                    "temporal_transaction",
                    "state_invariant",
                )
            )
        ]
        joint_utility = _number(outcome.get("joint_utility"), "joint_utility")
        oracle_utility = _number(
            outcome.get("oracle", {}).get("utility", {}).get("joint_utility"),
            "oracle joint utility",
        )
        objective = ScoreEnvelope(
            status="ok",
            leaf=self.leaves[4],
            primary=MetricValue(joint_utility, "usd_equivalent"),
            metrics={
                "bounded_regret": MetricValue(
                    _number(outcome.get("bounded_regret"), "bounded_regret"),
                    "usd_equivalent",
                ),
                "customer_utility": MetricValue(
                    _number(outcome.get("customer_utility"), "customer_utility"),
                    "usd_equivalent",
                ),
                "support_agent_utility": MetricValue(
                    _number(outcome.get("support_agent_utility"), "support_agent_utility"),
                    "usd_equivalent",
                ),
                "policy_compliance": MetricValue(
                    1.0 if compliance.get("satisfied") else 0.0, "pass"
                ),
            },
            reference_values={
                "full_information_upper_bound": MetricValue(
                    oracle_utility, "usd_equivalent"
                )
            },
            validity=ValidityReport("valid"),
            evidence_refs=references,
            utility_by_seat={
                "customer": MetricValue(
                    _number(outcome.get("customer_utility"), "customer_utility"),
                    "usd_equivalent",
                ),
                "support_agent": MetricValue(
                    _number(outcome.get("support_agent_utility"), "support_agent_utility"),
                    "usd_equivalent",
                ),
            },
        )
        scores.append(objective)
        return tuple(scores)


def build_scorer(case: rf.RefundCase) -> RefundV12Scorer:
    return RefundV12Scorer(case=case, leaves=build_measurement_leaves(case))


__all__ = [
    "CANONICAL_DECISION_LEAF_ID",
    "INFORMATION_CONSTRAINT_LEAF_ID",
    "MEASUREMENT_VERSION",
    "OBJECTIVE_LEAF_ID",
    "RefundV12Scorer",
    "STATE_INVARIANT_LEAF_ID",
    "TEMPORAL_TRANSACTION_LEAF_ID",
    "build_measurement_leaves",
    "build_scorer",
]
