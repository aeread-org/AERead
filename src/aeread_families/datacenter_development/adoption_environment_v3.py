"""V3 adoption environment aligning nullable nonbinding offer prose."""

from __future__ import annotations

import dataclasses
import json

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.execution import CanonicalResponse

from .adoption_environment import FAMILY_ID, SCORER_ID
from .adoption_environment_v2 import StarterGroundedCounterofferAdoptionPlugin
from .stack_environment import phase_ids


FAMILY_VERSION = "1.2.0"
PLUGIN_ID = "datacenter_counteroffer_adoption_environment_v3"


def adoption_family_manifest_v3() -> FamilyManifest:
    roles = {"developer": {"testable": True, "scripted_policies": ["scripted"]}}
    for counterpart in ("contractor", "landowner", "utility"):
        roles[counterpart] = {"testable": False, "scripted_policies": ["controlled"]}
    return FamilyManifest.from_dict({
        "spec_version": FamilyManifest.SPEC_VERSION,
        "family": {"id": FAMILY_ID, "version": FAMILY_VERSION, "plugin_id": PLUGIN_ID},
        "environment": {"topology": "starter_grounded_nullable_prose_counteroffer_adoption_v3", "phase_specs": list(phase_ids("v2")[:9]), "needs_tools": False, "needs_sandbox": False},
        "roles": roles,
        "measurement": {"primary_estimand": "counteroffer_adoption_rate", "measurement_kind": "property_or_answer", "direction": "maximize", "comparison_baseline": "exact_scripted_counteroffer_adoption", "outcome_support": "closed_unit_interval"},
        "scoring": {"scorer_id": SCORER_ID, "reference_provider_ids": ["datacenter_counteroffer_adoption_validity_v1", "datacenter_counteroffer_adoption_references_v1"]},
    })


class NullableProseCounterofferAdoptionPlugin(StarterGroundedCounterofferAdoptionPlugin):
    """Treat null offer prose as neutral because only terms bind."""

    def parse_action(self, family_case, state, seat, phase, response):
        if isinstance(response, CanonicalResponse) and phase.phase_id.endswith("_offer"):
            try:
                value = json.loads(response.text)
            except (TypeError, json.JSONDecodeError):
                value = None
            if (
                isinstance(value, dict)
                and set(value) == {"decision", "message", "terms"}
                and value["decision"] == "offer"
                and value["message"] is None
                and isinstance(value["terms"], dict)
            ):
                normalized = {
                    **value,
                    "message": "Structured written offer; terms control.",
                }
                response = dataclasses.replace(
                    response,
                    text=canonical_json_bytes(normalized).decode("utf-8"),
                )
        return super().parse_action(family_case, state, seat, phase, response)


def register_adoption_plugin_v3(registry: PluginRegistry, *, plugin=None):
    resolved = plugin or NullableProseCounterofferAdoptionPlugin()
    registry.register_trusted(adoption_family_manifest_v3(), resolved)
    return resolved


__all__ = ["FAMILY_VERSION", "PLUGIN_ID", "NullableProseCounterofferAdoptionPlugin", "adoption_family_manifest_v3", "register_adoption_plugin_v3"]
