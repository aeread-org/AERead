"""Paired public-delta salience treatment for land counteroffer adoption."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.schemas import FamilyManifest

from .adoption_environment import CounterofferAdoptionPlugin
from .adoption_environment_v3 import NullableProseCounterofferAdoptionPlugin
from .adoption_measurement import CounterofferAdoptionScorer
from .stack_environment import phase_ids


FAMILY_ID = "datacenter_counteroffer_salience_v1"
FAMILY_VERSION = "1.0.0"
PLUGIN_ID = "datacenter_counteroffer_salience_environment_v1"
SCORER_ID = "datacenter_counteroffer_adoption_score_set_v1"
CONDITIONS = ("full_package", "explicit_delta")


def salience_family_manifest() -> FamilyManifest:
    return FamilyManifest.from_dict({
        "spec_version": FamilyManifest.SPEC_VERSION,
        "family": {"id": FAMILY_ID, "version": FAMILY_VERSION, "plugin_id": PLUGIN_ID},
        "environment": {
            "topology": "paired_land_counteroffer_public_delta_salience_v1",
            "phase_specs": list(phase_ids("v2")[:3]),
            "needs_tools": False,
            "needs_sandbox": False,
        },
        "roles": {
            "developer": {"testable": True, "scripted_policies": ["scripted"]},
            "landowner": {"testable": False, "scripted_policies": ["controlled"]},
        },
        "measurement": {
            "primary_estimand": "counteroffer_adoption_rate",
            "measurement_kind": "property_or_answer",
            "direction": "maximize",
            "comparison_baseline": "paired_full_package_presentation",
            "outcome_support": "closed_unit_interval",
        },
        "scoring": {
            "scorer_id": SCORER_ID,
            "reference_provider_ids": [
                "datacenter_counteroffer_adoption_validity_v1",
                "datacenter_counteroffer_adoption_references_v1",
            ],
        },
    })


class CounterofferSaliencePlugin(NullableProseCounterofferAdoptionPlugin):
    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping) or set(payload) != {
            "base_case_id", "base_case_sha256", "stage_id",
            "required_sequence", "salience_condition",
        }:
            raise ValueError("salience payload fields differ")
        condition = payload["salience_condition"]
        if condition not in CONDITIONS:
            raise ValueError("unknown salience condition")
        base_payload = {key: value for key, value in payload.items() if key != "salience_condition"}
        expanded = CounterofferAdoptionPlugin().validate_payload(base_payload)
        if expanded["adoption_stage"]["required_sequence"] != ["land"]:
            raise ValueError("salience diagnostic must remain land-only")
        expanded["salience_condition"] = condition
        return expanded

    def observe(self, family_case, state, seat, phase) -> dict[str, Any]:
        observation = super().observe(family_case, state, seat, phase)
        if (
            seat == "developer"
            and phase.phase_id.endswith("_offer")
            and observation.get("pending_counter_terms") is not None
            and family_case["salience_condition"] == "explicit_delta"
        ):
            latest = observation["latest_offer"]["terms"]
            counter = observation["pending_counter_terms"]
            changed = [
                {
                    "field": field,
                    "prior_value": latest.get(field),
                    "counter_value": counter.get(field),
                }
                for field in sorted(set(latest) | set(counter))
                if canonical_json_bytes(latest.get(field))
                != canonical_json_bytes(counter.get(field))
            ]
            observation["counteroffer_delta"] = changed
            observation["counteroffer_delta_instruction"] = (
                "Apply counter_value for every listed field, and copy every "
                "remaining field from pending_counter_terms exactly."
            )
        return observation

    def outcome(self, family_case, terminal) -> dict[str, Any]:
        outcome = super().outcome(family_case, terminal)
        outcome["salience_condition"] = family_case["salience_condition"]
        return outcome

    def build_scorer(self, family_case) -> CounterofferAdoptionScorer:
        return CounterofferAdoptionScorer(family_case)


def register_salience_plugin(registry: PluginRegistry, *, plugin=None):
    resolved = plugin or CounterofferSaliencePlugin()
    registry.register_trusted(salience_family_manifest(), resolved)
    return resolved


__all__ = ["CONDITIONS", "FAMILY_ID", "FAMILY_VERSION", "PLUGIN_ID", "CounterofferSaliencePlugin", "register_salience_plugin", "salience_family_manifest"]
