"""Starter-grounded V2 counteroffer-adoption environment."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.execution import CanonicalResponse
from aeread.shared_runner.task.scheduler import ParseResult

from .adoption_environment import (
    FAMILY_ID,
    SCORER_ID,
    CounterofferAdoptionPlugin,
    STAGE_SEQUENCES,
)
from .adoption_runner import FIRST_OFFER_PERTURB_FIELD
from .stack_environment import phase_ids


FAMILY_VERSION = "1.1.0"
PLUGIN_ID = "datacenter_counteroffer_adoption_environment_v2"


def adoption_family_manifest_v2() -> FamilyManifest:
    roles = {"developer": {"testable": True, "scripted_policies": ["scripted"]}}
    for counterpart in ("contractor", "landowner", "utility"):
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
                "topology": "starter_grounded_nested_counteroffer_adoption_v2",
                "phase_specs": list(phase_ids("v2")[:9]),
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": roles,
            "measurement": {
                "primary_estimand": "counteroffer_adoption_rate",
                "measurement_kind": "property_or_answer",
                "direction": "maximize",
                "comparison_baseline": "exact_scripted_counteroffer_adoption",
                "outcome_support": "closed_unit_interval",
            },
            "scoring": {
                "scorer_id": SCORER_ID,
                "reference_provider_ids": [
                    "datacenter_counteroffer_adoption_validity_v1",
                    "datacenter_counteroffer_adoption_references_v1",
                ],
            },
        }
    )


def starter_terms(family_case: Mapping[str, Any], key: str) -> dict[str, Any]:
    terms = json.loads(
        canonical_json_bytes(family_case["policies"][key]["counter_terms"])
    )
    field = FIRST_OFFER_PERTURB_FIELD[key]
    terms[field] = int(terms[field]) - 1
    return terms


class StarterGroundedCounterofferAdoptionPlugin(CounterofferAdoptionPlugin):
    def observe(self, family_case, state, seat, phase) -> dict[str, Any]:
        observation = super().observe(family_case, state, seat, phase)
        if seat == "developer" and phase.phase_id.endswith("_offer"):
            key = observation["agreement_key"]
            if state["rounds"][key] == 0:
                observation["starter_offer_terms"] = starter_terms(family_case, key)
                observation["starter_offer_instruction"] = (
                    "Copy starter_offer_terms exactly as your first structured offer."
                )
        return observation

    def parse_action(self, family_case, state, seat, phase, response):
        if isinstance(response, CanonicalResponse) and phase.phase_id.endswith("_offer"):
            try:
                value = json.loads(response.text)
            except (TypeError, json.JSONDecodeError):
                value = None
            if (
                isinstance(value, dict)
                and set(value) == {"decision", "message", "terms"}
                and value["decision"] == "walk"
                and (value["message"] is None or isinstance(value["message"], str))
                and value["terms"] is None
            ):
                return ParseResult.success({"decision": "walk"})
        return super().parse_action(family_case, state, seat, phase, response)


def register_adoption_plugin_v2(
    registry: PluginRegistry,
    *,
    plugin: StarterGroundedCounterofferAdoptionPlugin | None = None,
) -> StarterGroundedCounterofferAdoptionPlugin:
    resolved = plugin or StarterGroundedCounterofferAdoptionPlugin()
    registry.register_trusted(adoption_family_manifest_v2(), resolved)
    return resolved


__all__ = [
    "FAMILY_VERSION",
    "PLUGIN_ID",
    "StarterGroundedCounterofferAdoptionPlugin",
    "adoption_family_manifest_v2",
    "register_adoption_plugin_v2",
    "starter_terms",
]
