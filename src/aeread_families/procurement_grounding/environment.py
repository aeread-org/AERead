"""One-shot procurement-grounding environment for the 231-project source bundle.

The task is deliberately not a min-cost award problem. The source snapshot contains
project-frequency proxies, marketplace search cards, outreach traces, and sparse quote
rows, but it does not contain a complete set of exact-variant, landed-cost offers. The
measured capability is therefore evidence-grounded procurement judgment: preserve each
source denominator, identify the highest supplier-readiness gaps, and defer a bulk order
until the declared qualification gates are satisfied.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.execution import CanonicalResponse
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
from aeread.shared_runner.resolver import canonical_json_bytes
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.scheduler import (
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
)


FAMILY_ID = "procurement_grounding_v1"
FAMILY_VERSION = "1.0.0"
PLUGIN_ID = "procurement_grounding_environment"
SCORER_ID = "procurement_grounding_scorer_v1"
PHASE_ID = "submit_procurement_assessment"

REPORT_FIELDS = {
    "readiness_decision",
    "scope",
    "source_counts",
    "priority_families",
    "supplier_distribution",
    "evidence_interpretations",
    "procurement_controls",
    "next_steps",
}
PRIORITY_FIELDS = {
    "family_id",
    "project_count",
    "accepted_suppliers",
    "priority_score",
    "priority_band",
}
DISTRIBUTION_FIELDS = {
    "top_search_card_supplier",
    "top_search_card_unique_skus",
    "top_search_card_candidate_slots",
    "largest_outreach_assignment_supplier",
    "largest_outreach_assigned_skus",
}
CONTROL_FIELDS = {
    "accepted_suppliers_target",
    "shortlist_structure",
    "variant_gates",
}


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


def _require_exact_fields(value: Any, expected: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{path} fields differ: missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )
    return value


def _require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _require_integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{path} must be a non-negative integer")
    return value


def _validate_string_list(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{path} must be a non-empty array")
    result = [_require_string(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise ValueError(f"{path} must not contain duplicates")
    return result


def _validate_report_structure(report: Any, oracle: Mapping[str, Any]) -> dict[str, Any]:
    data = _require_exact_fields(report, REPORT_FIELDS, "report")
    _require_string(data["readiness_decision"], "report.readiness_decision")
    _require_string(data["scope"], "report.scope")

    expected_count_keys = set(oracle["source_counts"])
    counts = _require_exact_fields(data["source_counts"], expected_count_keys, "report.source_counts")
    for key, value in counts.items():
        _require_integer(value, f"report.source_counts.{key}")

    priorities = data["priority_families"]
    if not isinstance(priorities, list) or len(priorities) != 3:
        raise ValueError("report.priority_families must contain exactly three rows")
    for index, priority in enumerate(priorities):
        row = _require_exact_fields(priority, PRIORITY_FIELDS, f"report.priority_families[{index}]")
        _require_string(row["family_id"], f"report.priority_families[{index}].family_id")
        _require_integer(row["project_count"], f"report.priority_families[{index}].project_count")
        _require_integer(row["accepted_suppliers"], f"report.priority_families[{index}].accepted_suppliers")
        _require_integer(row["priority_score"], f"report.priority_families[{index}].priority_score")
        _require_string(row["priority_band"], f"report.priority_families[{index}].priority_band")

    distribution = _require_exact_fields(
        data["supplier_distribution"], DISTRIBUTION_FIELDS, "report.supplier_distribution"
    )
    for key in ("top_search_card_supplier", "largest_outreach_assignment_supplier"):
        _require_string(distribution[key], f"report.supplier_distribution.{key}")
    for key in DISTRIBUTION_FIELDS - {
        "top_search_card_supplier",
        "largest_outreach_assignment_supplier",
    }:
        _require_integer(distribution[key], f"report.supplier_distribution.{key}")

    interpretation_keys = set(oracle["evidence_interpretations"])
    interpretations = _require_exact_fields(
        data["evidence_interpretations"],
        interpretation_keys,
        "report.evidence_interpretations",
    )
    for key, value in interpretations.items():
        if type(value) is not bool:
            raise ValueError(f"report.evidence_interpretations.{key} must be a boolean")

    controls = _require_exact_fields(
        data["procurement_controls"], CONTROL_FIELDS, "report.procurement_controls"
    )
    _require_integer(
        controls["accepted_suppliers_target"],
        "report.procurement_controls.accepted_suppliers_target",
    )
    _require_string(controls["shortlist_structure"], "report.procurement_controls.shortlist_structure")
    gate_keys = set(oracle["variant_gates"])
    gates = _require_exact_fields(
        controls["variant_gates"], gate_keys, "report.procurement_controls.variant_gates"
    )
    for key, value in gates.items():
        _validate_string_list(value, f"report.procurement_controls.variant_gates.{key}")

    _validate_string_list(data["next_steps"], "report.next_steps")
    return data


@dataclass(frozen=True, slots=True)
class ProcurementGroundingScorer:
    """Deterministic 100-point scorer over the structured procurement report."""

    oracle: Mapping[str, Any]

    def __call__(self, report: Mapping[str, Any]) -> dict[str, Any]:
        return self.score(report)

    def score(self, report: Mapping[str, Any]) -> dict[str, Any]:
        oracle = self.oracle
        breakdown: dict[str, int] = {}
        mismatches: list[str] = []

        count_points = 0
        for key, expected in oracle["source_counts"].items():
            if report["source_counts"][key] == expected:
                count_points += 1
            else:
                mismatches.append(f"source_counts.{key}")
        breakdown["source_counts"] = count_points  # 26 points

        priority_points = 0
        for index, expected in enumerate(oracle["priority_families"]):
            actual = report["priority_families"][index]
            if actual["family_id"] == expected["family_id"]:
                priority_points += 4
            else:
                mismatches.append(f"priority_families[{index}].family_id")
            for field in ("project_count", "accepted_suppliers", "priority_score", "priority_band"):
                if actual[field] == expected[field]:
                    priority_points += 1
                else:
                    mismatches.append(f"priority_families[{index}].{field}")
        breakdown["priority_families"] = priority_points  # 24 points

        distribution_points = 0
        for key, expected in oracle["supplier_distribution"].items():
            if report["supplier_distribution"][key] == expected:
                distribution_points += 2
            else:
                mismatches.append(f"supplier_distribution.{key}")
        breakdown["supplier_distribution"] = distribution_points  # 10 points

        interpretation_points = 0
        for key, expected in oracle["evidence_interpretations"].items():
            if report["evidence_interpretations"][key] is expected:
                interpretation_points += 3
            else:
                mismatches.append(f"evidence_interpretations.{key}")
        breakdown["evidence_interpretations"] = interpretation_points  # 15 points

        control_points = 0
        controls = report["procurement_controls"]
        if controls["accepted_suppliers_target"] == oracle["accepted_suppliers_target"]:
            control_points += 3
        else:
            mismatches.append("procurement_controls.accepted_suppliers_target")
        if controls["shortlist_structure"] == oracle["shortlist_structure"]:
            control_points += 3
        else:
            mismatches.append("procurement_controls.shortlist_structure")
        if report["scope"] == oracle["scope"]:
            control_points += 3
        else:
            mismatches.append("scope")
        for family_id, expected in oracle["variant_gates"].items():
            actual = controls["variant_gates"][family_id]
            if set(actual) == set(expected) and len(actual) == len(expected):
                control_points += 2
            else:
                mismatches.append(f"procurement_controls.variant_gates.{family_id}")
        breakdown["procurement_controls"] = control_points  # 15 points

        decision_points = 0
        if report["readiness_decision"] == oracle["readiness_decision"]:
            decision_points += 4
        else:
            mismatches.append("readiness_decision")
        actual_steps = set(report["next_steps"])
        for step in oracle["next_steps"]:
            if step in actual_steps:
                decision_points += 1
            else:
                mismatches.append(f"next_steps.{step}")
        breakdown["decision_and_next_steps"] = decision_points  # 10 points

        total_points = sum(breakdown.values())
        quality_band = "strong" if total_points >= 85 else ("adequate" if total_points >= 60 else "valid_but_poor")
        return {
            "valid": True,
            "quality_band": quality_band,
            "total_points": total_points,
            "max_points": 100,
            "score": total_points / 100.0,
            "breakdown": breakdown,
            "mismatched_fields": mismatches,
        }


def procurement_measurement_leaf(
    family_case: Mapping[str, Any],
) -> MeasurementLeafSpec:
    """Declare the deterministic accuracy measurement used by receipts."""

    source_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    oracle_digest = hashlib.sha256(
        canonical_json_bytes(family_case["oracle"])
    ).hexdigest()
    validity_domain = ValidityDomainSpec(
        domain_id="procurement_grounding_outcome_domain",
        domain_version="1.0.0",
        schema_ref="procurement_grounding_v1/outcome/1",
        predicate=MeasurementImplementationRef(
            SCORER_ID, "1.0.0", source_digest
        ),
    )
    estimand = EstimandSpec(
        estimand_id="procurement_grounding_accuracy",
        estimand_version="1.0.0",
        input_scope="terminal_state",
        direction="maximize",
        units="ratio",
        validity_domain=validity_domain,
    )
    return MeasurementLeafSpec(
        leaf_id="procurement_grounding_accuracy_leaf",
        leaf_version="1.0.0",
        estimand=estimand,
        verifier=VerifierSpec(
            verifier_family="canonical_reference",
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id="procurement_grounding_oracle_v1",
                reference_version="1.0.0",
                reference_kind="canonical_point",
                input_scope="terminal_state",
                units="ratio",
                source_sha256=oracle_digest,
                implementation=MeasurementImplementationRef(
                    "procurement_grounding_oracle_v1", "1.0.0", source_digest
                ),
            ),
        ),
        scorer=MeasurementImplementationRef(SCORER_ID, "1.0.0", source_digest),
    )


@dataclass(frozen=True, slots=True)
class ProcurementGroundingMeasurementScorer:
    """Wrap the family outcome in AERead's portable measurement envelope."""

    family_case: Mapping[str, Any]

    def __call__(
        self,
        outcome: Mapping[str, Any],
        *,
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        leaf = procurement_measurement_leaf(self.family_case)
        reasons: list[str] = []
        if not isinstance(outcome, Mapping):
            reasons.append("procurement outcome must be an object")
            outcome = {}
        score = outcome.get("score")
        total_points = outcome.get("total_points")
        max_points = outcome.get("max_points")
        valid_action = outcome.get("valid")
        mismatches = outcome.get("mismatched_fields")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not 0.0 <= float(score) <= 1.0
        ):
            reasons.append("score must be a ratio in [0, 1]")
        if (
            isinstance(total_points, bool)
            or not isinstance(total_points, int)
            or not 0 <= total_points <= 100
        ):
            reasons.append("total_points must be an integer in [0, 100]")
        if max_points != 100:
            reasons.append("max_points must equal 100")
        if not isinstance(valid_action, bool):
            reasons.append("valid must be boolean")
        if not isinstance(mismatches, (list, tuple)) or any(
            not isinstance(item, str) for item in mismatches
        ):
            reasons.append("mismatched_fields must be an array of strings")
        if not reasons and total_points != round(float(score) * 100):
            reasons.append("score and total_points disagree")

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
            primary=MetricValue(float(score), "ratio"),
            metrics={
                "total_points": MetricValue(float(total_points), "points"),
                "valid_action": MetricValue(1.0 if valid_action else 0.0, "indicator"),
                "mismatched_field_count": MetricValue(
                    float(len(mismatches)), "count"
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
                "primary_estimand": "procurement_grounding_accuracy",
                "measurement_kind": "property_or_answer",
                "direction": "maximize",
                "outcome_support": "unit_interval",
            },
            "scoring": {
                "scorer_id": SCORER_ID,
                "oracle_id": "procurement_grounding_oracle_v1",
            },
        }
    )


def register_plugin(
    registry: PluginRegistry, *, plugin: "ProcurementGroundingPlugin | None" = None
) -> "ProcurementGroundingPlugin":
    resolved = plugin or ProcurementGroundingPlugin()
    registry.register_trusted(family_manifest(), resolved)
    return resolved


class ProcurementGroundingPlugin:
    """Family-owned AERead hooks for one analyst report submission."""

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = _plain(payload)
        if set(data) != {"snapshot", "visible_evidence", "oracle"}:
            raise ValueError("payload must contain exactly snapshot, visible_evidence, and oracle")
        if not isinstance(data["snapshot"], dict) or not isinstance(data["visible_evidence"], dict):
            raise ValueError("payload.snapshot and payload.visible_evidence must be objects")
        if not isinstance(data["oracle"], dict):
            raise ValueError("payload.oracle must be an object")
        oracle = data["oracle"]
        required_oracle = {
            "source_counts",
            "priority_families",
            "supplier_distribution",
            "evidence_interpretations",
            "accepted_suppliers_target",
            "shortlist_structure",
            "variant_gates",
            "scope",
            "readiness_decision",
            "next_steps",
        }
        if set(oracle) != required_oracle:
            raise ValueError("payload.oracle fields do not match the scorer contract")
        if len(oracle["source_counts"]) != 26:
            raise ValueError("payload.oracle.source_counts must contain 26 denominated facts")
        if len(oracle["priority_families"]) != 3:
            raise ValueError("payload.oracle.priority_families must contain three rows")
        return data

    def initial_state(self, family_case: Mapping[str, Any], run: Any) -> dict[str, Any]:
        del family_case, run
        return {"done": False, "valid": None, "report": None, "failure_code": None}

    def phases(self, family_case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        del family_case
        return (
            PhaseSpec(
                phase_id=PHASE_ID,
                actor_selector="analyst_only",
                mode="single",
                observation_schema_by_role={"analyst": "procurement_grounding_observation_v1"},
                action_schema_by_role={"analyst": "procurement_grounding_report_v1"},
                max_logical_actions=1,
                invalid_action_policy="family_defined",
                next_phases=(),
            ),
        )

    def eligible_actors(
        self, family_case: Mapping[str, Any], state: Mapping[str, Any], phase: PhaseSpec
    ) -> tuple[str, ...]:
        del family_case, state, phase
        return ("analyst",)

    def observe(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat: str,
        phase: PhaseSpec,
    ) -> dict[str, Any]:
        del state, seat, phase
        return {
            "snapshot": _plain(family_case["snapshot"]),
            "evidence": _plain(family_case["visible_evidence"]),
        }

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
            report = _validate_report_structure(value, family_case["oracle"])
        except ValueError:
            return ParseResult.failure("malformed_procurement_report")
        return ParseResult.success(report)

    def legal(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat: str,
        phase: PhaseSpec,
        action: Mapping[str, Any],
    ) -> LegalityResult:
        del family_case, state, seat, phase
        if action["readiness_decision"] != "defer_bulk_order":
            return LegalityResult.illegal("premature_bulk_order_readiness")
        return LegalityResult.legal_action()

    def step(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
        actions: Mapping[str, Any],
    ) -> TransitionResult:
        del family_case, state, phase
        envelope = actions["analyst"]
        failure_code = None
        if not envelope.valid:
            failure_code = (
                envelope.parse.error_code
                if not envelope.parse.ok
                else envelope.legality.reason
            )
        next_state = {
            "done": True,
            "valid": envelope.valid,
            "report": _plain(envelope.action) if envelope.valid else None,
            "failure_code": failure_code,
        }
        return TransitionResult(
            state=next_state,
            next_phase_id=None,
            consequences={"submission_valid": envelope.valid, "failure_code": failure_code},
        )

    def terminal(
        self, family_case: Mapping[str, Any], state: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        del family_case
        if not state["done"]:
            return None
        return {
            "reason": "submitted" if state["valid"] else "invalid_submission",
            "valid": state["valid"],
            "report": _plain(state["report"]),
            "failure_code": state["failure_code"],
        }

    def outcome(
        self, family_case: Mapping[str, Any], terminal: Mapping[str, Any]
    ) -> dict[str, Any]:
        if not terminal["valid"]:
            return {
                "valid": False,
                "quality_band": "invalid",
                "total_points": 0,
                "max_points": 100,
                "score": 0.0,
                "breakdown": {},
                "mismatched_fields": [],
                "failure_code": terminal["failure_code"],
            }
        result = ProcurementGroundingScorer(family_case["oracle"]).score(terminal["report"])
        result["failure_code"] = None
        return result

    def build_scorer(
        self, family_case: Mapping[str, Any]
    ) -> ProcurementGroundingMeasurementScorer:
        return ProcurementGroundingMeasurementScorer(family_case)

    def build_reference_providers(self, family_case: Mapping[str, Any]) -> tuple[Any, ...]:
        del family_case
        return ()

    def generator(self, family_case: Mapping[str, Any] | None = None) -> None:
        del family_case
        return None


__all__ = [
    "FAMILY_ID",
    "FAMILY_VERSION",
    "PHASE_ID",
    "PLUGIN_ID",
    "REPORT_FIELDS",
    "SCORER_ID",
    "ProcurementGroundingMeasurementScorer",
    "ProcurementGroundingPlugin",
    "ProcurementGroundingScorer",
    "family_manifest",
    "procurement_measurement_leaf",
    "register_plugin",
]
