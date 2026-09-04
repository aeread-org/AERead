"""Objective-visible, bounded-policy wrapper for the V2 agreement stack."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import FamilyManifest

from .objective_measurement import ObjectiveAwareDataCenterScorer
from .stack_environment import COUNTERPART_BY_KEY, DataCenterStackPlugin, phase_ids


FAMILY_ID = "datacenter_development_v1"
FAMILY_VERSION = "2.1.0"
PLUGIN_ID = "datacenter_development_objective_environment_v1"
SCORER_ID = "datacenter_objective_score_set_v1"


def objective_stack_family_manifest() -> FamilyManifest:
    roles = {"developer": {"testable": True, "scripted_policies": ["scripted"]}}
    for counterpart in sorted(set(COUNTERPART_BY_KEY.values())):
        roles[counterpart] = {
            "testable": False,
            "scripted_policies": ["controlled"],
        }
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {
                "id": FAMILY_ID,
                "version": FAMILY_VERSION,
                "plugin_id": PLUGIN_ID,
            },
            "environment": {
                "topology": "sequential_datacenter_agreement_stack_v2_objective_visible",
                "phase_specs": list(phase_ids("v2")),
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": roles,
            "measurement": {
                "primary_estimand": "safe_developer_objective_attainment",
                "measurement_kind": "optimizable_outcome",
                "direction": "maximize",
                "comparison_baseline": "certified_singleton_control_package",
                "outcome_support": "closed_unit_interval",
            },
            "scoring": {
                "scorer_id": SCORER_ID,
                "reference_provider_ids": [
                    "datacenter_objective_validity_v1",
                    "datacenter_objective_references_v1",
                ],
            },
        }
    )


def _numeric_terms(value: Mapping[str, Any]) -> dict[str, int]:
    return {
        str(field): item
        for field, item in value.items()
        if isinstance(item, int) and not isinstance(item, bool)
    }


class ObjectiveAwareStackPlugin(DataCenterStackPlugin):
    """Reuse V2 transitions while strengthening visibility and calibration."""

    def __init__(self) -> None:
        super().__init__("v2")

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = super().validate_payload(payload)
        for agreement_key, policy in data["policies"].items():
            counter_terms = policy["counter_terms"]
            numeric = _numeric_terms(counter_terms)
            if policy["minimums"] != numeric or policy["maximums"] != numeric:
                raise ValueError(
                    f"{agreement_key} policy must bind every numeric counter term exactly"
                )
            if set(policy["required_conditions"]) != set(
                counter_terms["conditions_precedent"]
            ):
                raise ValueError(
                    f"{agreement_key} required conditions must equal the counter package"
                )
        outside = data["outside_option"]
        baseline = data["baseline"]
        if (
            baseline["developer_equity_npv_cents"]
            <= outside["developer_equity_npv_cents"]
        ):
            raise ValueError("completed developer reference must beat the outside option")
        if baseline["customer_npv_cents"] < outside["customer_npv_cents"]:
            raise ValueError("completed customer reference must satisfy participation")
        if baseline["total_project_npv_cents"] <= outside["total_project_npv_cents"]:
            raise ValueError("completed reference must create total project surplus")
        return data

    def observe(self, family_case, state, seat, phase) -> dict[str, Any]:
        observation = super().observe(family_case, state, seat, phase)
        if seat == "developer":
            observation["developer_objective"] = {
                "objective_id": "safe_developer_objective_attainment",
                "decision_rule": (
                    "maximize developer_equity_npv_cents subject to completed binding "
                    "contracts, project constraints, and temporal compliance"
                ),
                "outside_option_developer_equity_npv_cents": family_case[
                    "outside_option"
                ]["developer_equity_npv_cents"],
                "explicit_walk_allowed": True,
                "involuntary_failure_is_not_a_walk": True,
                "currency_unit": "cents",
                "project_month_indexing": "one_based",
            }
        return observation

    def build_scorer(self, family_case) -> ObjectiveAwareDataCenterScorer:
        return ObjectiveAwareDataCenterScorer(family_case)


def register_objective_stack_plugin(
    registry: PluginRegistry,
    *,
    plugin: ObjectiveAwareStackPlugin | None = None,
) -> ObjectiveAwareStackPlugin:
    resolved = plugin or ObjectiveAwareStackPlugin()
    registry.register_trusted(objective_stack_family_manifest(), resolved)
    return resolved


__all__ = [
    "FAMILY_ID",
    "FAMILY_VERSION",
    "ObjectiveAwareStackPlugin",
    "PLUGIN_ID",
    "SCORER_ID",
    "objective_stack_family_manifest",
    "register_objective_stack_plugin",
]
