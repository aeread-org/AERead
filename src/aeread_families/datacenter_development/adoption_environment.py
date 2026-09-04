"""Nested data-center prefixes for written-counteroffer adoption diagnosis."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.schemas import FamilyManifest

from .adoption_measurement import CounterofferAdoptionScorer
from .objective_environment import ObjectiveAwareStackPlugin
from .stack_environment import COUNTERPART_BY_KEY, DataCenterStackPlugin, phase_ids
from .stack_runner import load_stack_case


FAMILY_ID = "datacenter_counteroffer_adoption_v1"
FAMILY_VERSION = "1.0.0"
PLUGIN_ID = "datacenter_counteroffer_adoption_environment_v1"
SCORER_ID = "datacenter_counteroffer_adoption_score_set_v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BASE_CASE_PATH = (
    REPOSITORY_ROOT
    / "cases"
    / "datacenter_development_v1"
    / "v2"
    / "objective_bounded_001.json"
)
STAGE_SEQUENCES = {
    "land": ("land",),
    "land_power": ("land", "power"),
    "land_power_epc": ("land", "power", "epc"),
}


def adoption_family_manifest() -> FamilyManifest:
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
                "topology": "nested_sequential_datacenter_counteroffer_adoption_v1",
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


def _exact_fields(value: Mapping[str, Any], fields: set[str], path: str) -> None:
    if set(value) != fields:
        raise ValueError(
            f"{path} fields differ: missing={sorted(fields - set(value))}, "
            f"unexpected={sorted(set(value) - fields)}"
        )


class CounterofferAdoptionPlugin:
    """Expand a hash-pinned base case, then run only the requested prefix."""

    @staticmethod
    def _delegate(family_case: Mapping[str, Any]) -> DataCenterStackPlugin:
        delegate = DataCenterStackPlugin("v2")
        delegate.sequence = tuple(family_case["adoption_stage"]["required_sequence"])
        return delegate

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValueError("payload must be an object")
        _exact_fields(
            payload,
            {"base_case_id", "base_case_sha256", "stage_id", "required_sequence"},
            "payload",
        )
        stage_id = payload["stage_id"]
        if stage_id not in STAGE_SEQUENCES:
            raise ValueError("unknown adoption stage")
        sequence = tuple(payload["required_sequence"])
        if sequence != STAGE_SEQUENCES[stage_id]:
            raise ValueError("required_sequence differs from the named nested stage")
        base = load_stack_case("v2", BASE_CASE_PATH)
        if payload["base_case_id"] != base.case_id:
            raise ValueError("base case ID differs")
        if payload["base_case_sha256"] != base.content_sha256:
            raise ValueError("base case hash differs")
        expanded = ObjectiveAwareStackPlugin().validate_payload(base.payload)
        expanded["adoption_stage"] = {
            "stage_id": stage_id,
            "required_sequence": list(sequence),
            "base_case_id": base.case_id,
            "base_case_sha256": base.content_sha256,
        }
        return expanded

    def initial_state(self, family_case, run) -> dict[str, Any]:
        return self._delegate(family_case).initial_state(family_case, run)

    def phases(self, family_case):
        return self._delegate(family_case).phases(family_case)

    def eligible_actors(self, family_case, state, phase):
        return self._delegate(family_case).eligible_actors(
            family_case, state, phase
        )

    def observe(self, family_case, state, seat, phase) -> dict[str, Any]:
        observation = self._delegate(family_case).observe(
            family_case, state, seat, phase
        )
        if seat == "developer":
            sequence = family_case["adoption_stage"]["required_sequence"]
            observation["counteroffer_adoption_task"] = {
                "stage_id": family_case["adoption_stage"]["stage_id"],
                "required_sequence": list(sequence),
                "required_behavior": (
                    "For every controlled counterparty written counteroffer, copy "
                    "all structured terms exactly into the next offer, then sign "
                    "the accepted offer_id exactly. A walk is allowed but receives "
                    "no adoption credit."
                ),
                "economic_optimization_scored": False,
            }
        return observation

    def parse_action(self, family_case, state, seat, phase, response):
        return self._delegate(family_case).parse_action(
            family_case, state, seat, phase, response
        )

    def legal(self, family_case, state, seat, phase, action):
        return self._delegate(family_case).legal(
            family_case, state, seat, phase, action
        )

    def step(self, family_case, state, phase, actions):
        return self._delegate(family_case).step(
            family_case, state, phase, actions
        )

    def terminal(self, family_case, state):
        return self._delegate(family_case).terminal(family_case, state)

    def outcome(self, family_case, terminal) -> dict[str, Any]:
        sequence = tuple(family_case["adoption_stage"]["required_sequence"])
        executed = terminal["executed"]
        countered = {
            item["agreement_key"]
            for item in terminal["public_history"]
            if item.get("decision") == "counter"
            and item.get("agreement_key") in sequence
        }
        exact_keys = {
            key
            for key in sequence
            if key in executed
            and canonical_json_bytes(executed[key]["terms"])
            == canonical_json_bytes(family_case["policies"][key]["counter_terms"])
        }
        adopted = exact_keys & countered
        prefix_completed = all(key in executed for key in sequence)
        exact_integrity = prefix_completed and len(exact_keys) == len(sequence)
        return {
            "stage_id": family_case["adoption_stage"]["stage_id"],
            "required_sequence": list(sequence),
            "termination_reason": terminal["termination_reason"],
            "public_history": json.loads(
                canonical_json_bytes(terminal["public_history"])
            ),
            "temporal_violations": list(terminal["temporal_violations"]),
            "prefix_completed": prefix_completed,
            "executed_agreement_count": sum(key in executed for key in sequence),
            "exact_package_integrity": exact_integrity,
            "counteroffer_opportunity_count": len(countered),
            "counteroffer_adoption_count": len(adopted),
            "counteroffer_adoption_rate": len(adopted) / len(sequence),
            "intentional_resolution": (
                prefix_completed
                or terminal["termination_reason"] == "developer_walk"
            ),
        }

    def build_scorer(self, family_case) -> CounterofferAdoptionScorer:
        return CounterofferAdoptionScorer(family_case)

    def build_reference_providers(self, family_case) -> tuple[Any, ...]:
        del family_case
        return ()

    def generator(self, family_case=None) -> None:
        del family_case
        return None


def register_adoption_plugin(
    registry: PluginRegistry,
    *,
    plugin: CounterofferAdoptionPlugin | None = None,
) -> CounterofferAdoptionPlugin:
    resolved = plugin or CounterofferAdoptionPlugin()
    registry.register_trusted(adoption_family_manifest(), resolved)
    return resolved


__all__ = [
    "BASE_CASE_PATH",
    "FAMILY_ID",
    "FAMILY_VERSION",
    "PLUGIN_ID",
    "SCORER_ID",
    "STAGE_SEQUENCES",
    "CounterofferAdoptionPlugin",
    "adoption_family_manifest",
    "register_adoption_plugin",
]
