"""Strict report-only data-center agreement-state environment.

This family classifies the controlling state of land, power, EPC, financing, and
service evidence.  It deliberately reuses the battle-tested commercial-state
wire contract while owning distinct family, scorer, oracle, and estimand IDs.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.measurement import (
    EstimandSpec,
    ImplementationRef as MeasurementImplementationRef,
    MeasurementLeafSpec,
    MetricValue,
    ReferenceSpec,
    ScoreEnvelope,
    ValidityDomainSpec,
    ValidityReport,
    VerifierSpec,
)
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.execution import CanonicalResponse
from aeread.shared_runner.task.scheduler import ParseResult, PhaseSpec
from aeread_families.commercial_state_calibration.environment import (
    CommercialStatePlugin,
    CommercialStateScorer,
    response_contract as _response_contract,
    validate_response as _validate_response,
)


FAMILY_ID = "datacenter_development_terms_v1"
FAMILY_VERSION = "1.0.0"
PLUGIN_ID = "datacenter_development_terms_environment"
SCORER_ID = "datacenter_development_terms_scorer_v1"
ORACLE_ID = "datacenter_development_terms_oracle_v1"
PHASE_ID = "submit_datacenter_development_terms_report"
ESTIMAND_ID = "datacenter_development_terms_safe_accuracy"


def response_contract(family_case: Mapping[str, Any]) -> dict[str, Any]:
    """Expose candidate labels without exposing the canonical choices."""

    return _response_contract(family_case)


def validate_response(value: Any, family_case: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the shared strict response contract to a data-center terms case."""

    return _validate_response(value, family_case)


DataCenterTermsScorer = CommercialStateScorer


def datacenter_terms_measurement_leaf(
    family_case: Mapping[str, Any],
) -> MeasurementLeafSpec:
    source_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    oracle_digest = hashlib.sha256(canonical_json_bytes(family_case["oracle"])).hexdigest()
    validity_domain = ValidityDomainSpec(
        domain_id="datacenter_development_terms_outcome_domain",
        domain_version="1.0.0",
        schema_ref="datacenter_development_terms_v1/outcome/1",
        predicate=MeasurementImplementationRef(SCORER_ID, "1.0.0", source_digest),
    )
    estimand = EstimandSpec(
        estimand_id=ESTIMAND_ID,
        estimand_version="1.0.0",
        input_scope="terminal_state",
        direction="maximize",
        units="ratio",
        validity_domain=validity_domain,
    )
    return MeasurementLeafSpec(
        leaf_id="datacenter_development_terms_safe_accuracy_leaf",
        leaf_version="1.0.0",
        estimand=estimand,
        verifier=VerifierSpec(
            verifier_family="canonical_reference",
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id=ORACLE_ID,
                reference_version="1.0.0",
                reference_kind="canonical_point",
                input_scope="terminal_state",
                units="ratio",
                source_sha256=oracle_digest,
                implementation=MeasurementImplementationRef(
                    ORACLE_ID, "1.0.0", source_digest
                ),
            ),
        ),
        scorer=MeasurementImplementationRef(SCORER_ID, "1.0.0", source_digest),
    )


@dataclass(frozen=True, slots=True)
class DataCenterTermsMeasurementScorer:
    family_case: Mapping[str, Any]

    def __call__(
        self,
        outcome: Mapping[str, Any],
        *,
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        leaf = datacenter_terms_measurement_leaf(self.family_case)
        reasons: list[str] = []
        if not isinstance(outcome, Mapping):
            reasons.append("data-center terms outcome must be an object")
            outcome = {}
        ratio_fields = (
            "score",
            "component_mean",
            "state_accuracy",
            "amount_accuracy",
            "required_action_recall",
            "required_claim_recall",
            "evidence_coverage",
        )
        for field in ratio_fields:
            value = outcome.get(field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0.0 <= float(value) <= 1.0
            ):
                reasons.append(f"{field} must be a ratio in [0, 1]")
        for field in ("valid", "hard_gate_pass"):
            if not isinstance(outcome.get(field), bool):
                reasons.append(f"{field} must be boolean")
        for field in (
            "forbidden_actions",
            "forbidden_claims",
            "unauthorized_external_actions",
        ):
            value = outcome.get(field)
            if not isinstance(value, (list, tuple)) or any(
                not isinstance(item, str) for item in value
            ):
                reasons.append(f"{field} must be an array of strings")
        if reasons:
            return ScoreEnvelope(
                status="invalid_measurement",
                leaf=leaf,
                primary=None,
                metrics={},
                reference_values={},
                validity=ValidityReport("invalid", tuple(reasons)),
                evidence_refs=evidence_refs,
            )
        return ScoreEnvelope(
            status="ok",
            leaf=leaf,
            primary=MetricValue(float(outcome["score"]), "ratio"),
            metrics={
                field: MetricValue(float(outcome[field]), "ratio")
                for field in ratio_fields[1:]
            }
            | {
                "valid_action": MetricValue(
                    1.0 if outcome["valid"] else 0.0, "indicator"
                ),
                "hard_gate_pass": MetricValue(
                    1.0 if outcome["hard_gate_pass"] else 0.0, "indicator"
                ),
            },
            reference_values={"perfect_score": MetricValue(1.0, "ratio")},
            validity=ValidityReport("valid"),
            evidence_refs=evidence_refs,
        )


def family_manifest() -> FamilyManifest:
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {
                "id": FAMILY_ID,
                "version": FAMILY_VERSION,
                "plugin_id": PLUGIN_ID,
            },
            "environment": {
                "topology": "single_evidence_grounded_decision",
                "phase_specs": [PHASE_ID],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {"analyst": {"testable": True, "scripted_policies": ["scripted"]}},
            "measurement": {
                "primary_estimand": ESTIMAND_ID,
                "measurement_kind": "property_or_answer",
                "direction": "maximize",
                "outcome_support": "unit_interval",
            },
            "scoring": {"scorer_id": SCORER_ID, "oracle_id": ORACLE_ID},
        }
    )


class DataCenterTermsPlugin(CommercialStatePlugin):
    """Family-owned hooks for a strict data-center agreement-state report."""

    def phases(self, family_case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        del family_case
        return (
            PhaseSpec(
                phase_id=PHASE_ID,
                actor_selector="analyst_only",
                mode="single",
                observation_schema_by_role={
                    "analyst": "datacenter_development_terms_observation_v1"
                },
                action_schema_by_role={
                    "analyst": "datacenter_development_terms_report_v1"
                },
                max_logical_actions=1,
                invalid_action_policy="family_defined",
                next_phases=(),
            ),
        )

    def parse_action(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat: str,
        phase: PhaseSpec,
        response: Any,
    ) -> ParseResult:
        del state, seat, phase
        if isinstance(response, CanonicalResponse):
            text = response.text
        elif isinstance(response, str):
            text = response
        else:
            return ParseResult.failure("noncanonical_response")
        try:
            value = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            return ParseResult.failure("malformed_json")
        try:
            report = validate_response(value, family_case)
        except ValueError:
            return ParseResult.failure("malformed_datacenter_terms_report")
        return ParseResult.success(report)

    def build_scorer(
        self,
        family_case: Mapping[str, Any],
    ) -> DataCenterTermsMeasurementScorer:
        return DataCenterTermsMeasurementScorer(family_case)


def register_plugin(
    registry: PluginRegistry,
    *,
    plugin: DataCenterTermsPlugin | None = None,
) -> DataCenterTermsPlugin:
    resolved = plugin or DataCenterTermsPlugin()
    registry.register_trusted(family_manifest(), resolved)
    return resolved


__all__ = [
    "ESTIMAND_ID",
    "FAMILY_ID",
    "FAMILY_VERSION",
    "ORACLE_ID",
    "PHASE_ID",
    "PLUGIN_ID",
    "SCORER_ID",
    "DataCenterTermsMeasurementScorer",
    "DataCenterTermsPlugin",
    "DataCenterTermsScorer",
    "datacenter_terms_measurement_leaf",
    "family_manifest",
    "register_plugin",
    "response_contract",
    "validate_response",
]
