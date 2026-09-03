"""Paired broad versus dedicated counteroffer-acceptance schemas."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from typing import Any

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.execution import CanonicalResponse
from aeread.shared_runner.task.scheduler import (
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
)

from .adoption_measurement import CounterofferAdoptionScorer
from .affordance_environment import CounterofferAffordancePlugin
from .stack_environment import _phase_id, _plain


FAMILY_ID = "datacenter_counteroffer_action_schema_v1"
FAMILY_VERSION = "1.0.0"
PLUGIN_ID = "datacenter_counteroffer_action_schema_environment_v1"
SCORER_ID = "datacenter_counteroffer_adoption_score_set_v1"
CONDITIONS = ("shared_offer_schema", "dedicated_accept_schema")
DEDICATED_PHASE_ID = "land_developer_accept_counteroffer"
DEDICATED_ACTION_SCHEMA_ID = "datacenter_land_accept_counteroffer_v1"


def action_schema_family_manifest() -> FamilyManifest:
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {
                "id": FAMILY_ID,
                "version": FAMILY_VERSION,
                "plugin_id": PLUGIN_ID,
            },
            "environment": {
                "topology": "paired_land_counteroffer_action_schema_v1",
                "phase_specs": [
                    _phase_id("land", "offer"),
                    _phase_id("land", "response"),
                    DEDICATED_PHASE_ID,
                    _phase_id("land", "commit"),
                ],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {
                "developer": {
                    "testable": True,
                    "scripted_policies": ["scripted"],
                },
                "landowner": {
                    "testable": False,
                    "scripted_policies": ["controlled"],
                },
            },
            "measurement": {
                "primary_estimand": "counteroffer_adoption_rate",
                "measurement_kind": "property_or_answer",
                "direction": "maximize",
                "comparison_baseline": "paired_shared_offer_action_schema",
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


class CounterofferActionSchemaPlugin(CounterofferAffordancePlugin):
    """Route the treatment arm through a narrow acceptance-only phase."""

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        expected = {
            "base_case_id",
            "base_case_sha256",
            "stage_id",
            "required_sequence",
            "schema_condition",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("action-schema payload fields differ")
        condition = payload["schema_condition"]
        if condition not in CONDITIONS:
            raise ValueError("unknown action-schema condition")
        affordance_payload = {
            key: value for key, value in payload.items() if key != "schema_condition"
        }
        affordance_payload["affordance_condition"] = "accept_by_reference"
        expanded = super().validate_payload(affordance_payload)
        expanded["schema_condition"] = condition
        return expanded

    def phases(self, family_case) -> tuple[PhaseSpec, ...]:
        base = super().phases(family_case)
        phases: list[PhaseSpec] = []
        for phase in base:
            if phase.phase_id == _phase_id("land", "response"):
                phase = dataclasses.replace(
                    phase,
                    next_phases=(
                        _phase_id("land", "offer"),
                        DEDICATED_PHASE_ID,
                        _phase_id("land", "commit"),
                    ),
                )
            phases.append(phase)
            if phase.phase_id == _phase_id("land", "response"):
                phases.append(
                    PhaseSpec(
                        phase_id=DEDICATED_PHASE_ID,
                        actor_selector="developer",
                        mode="single",
                        observation_schema_by_role={
                            "developer": "datacenter_stack_developer_v1"
                        },
                        action_schema_by_role={
                            "developer": DEDICATED_ACTION_SCHEMA_ID
                        },
                        max_logical_actions=1,
                        invalid_action_policy="family_defined",
                        next_phases=(_phase_id("land", "commit"),),
                    )
                )
        return tuple(phases)

    def observe(self, family_case, state, seat, phase) -> dict[str, Any]:
        observation = super().observe(family_case, state, seat, phase)
        if seat == "developer" and phase.phase_id == DEDICATED_PHASE_ID:
            counteroffer_id = state["pending_counteroffer_id"]["land"]
            observation["pending_counteroffer_offer_id"] = counteroffer_id
            observation["counteroffer_resolution"] = {
                "mode": "accept_by_reference",
                "required_action": {
                    "decision": "accept_counteroffer",
                    "offer_id": "Copy pending_counteroffer_offer_id exactly.",
                },
            }
        return observation

    def parse_action(self, family_case, state, seat, phase, response):
        if phase.phase_id != DEDICATED_PHASE_ID:
            return super().parse_action(family_case, state, seat, phase, response)
        if not isinstance(response, CanonicalResponse):
            return ParseResult.failure("noncanonical_response")
        try:
            value = json.loads(response.text)
        except (TypeError, json.JSONDecodeError):
            return ParseResult.failure("malformed_json")
        if (
            not isinstance(value, dict)
            or set(value) != {"decision", "offer_id"}
            or value["decision"] != "accept_counteroffer"
            or not isinstance(value["offer_id"], str)
        ):
            return ParseResult.failure("malformed_counteroffer_acceptance")
        return ParseResult.success(value)

    def legal(self, family_case, state, seat, phase, action):
        if phase.phase_id != DEDICATED_PHASE_ID:
            return super().legal(family_case, state, seat, phase, action)
        expected = state["pending_counteroffer_id"]["land"]
        if action["offer_id"] != expected:
            return LegalityResult.illegal("stale_or_unknown_counteroffer")
        offer = next(
            (item for item in state["offers"] if item["offer_id"] == expected), None
        )
        if offer is None or offer["proposer_seat_id"] != "landowner":
            return LegalityResult.illegal("counteroffer_provenance_invalid")
        return LegalityResult.legal_action()

    def step(self, family_case, state, phase, actions):
        if phase.phase_id == DEDICATED_PHASE_ID:
            envelope = actions["developer"]
            if not envelope.valid:
                return super().step(family_case, state, phase, actions)
            next_state = _plain(state)
            offer_id = envelope.action["offer_id"]
            next_state["accepted_offer_id"]["land"] = offer_id
            next_state["pending_counteroffer_id"]["land"] = None
            next_state["pending_counter_terms"]["land"] = None
            next_state["reference_acceptance_count"] += 1
            next_state["public_history"].append(
                {
                    "phase_id": phase.phase_id,
                    "seat_id": "developer",
                    "agreement_key": "land",
                    "decision": "accept_counteroffer",
                    "offer_id": offer_id,
                }
            )
            return TransitionResult(
                next_state,
                _phase_id("land", "commit"),
                {"valid": True, "accepted_counteroffer_id": offer_id},
            )
        transition = super().step(family_case, state, phase, actions)
        if (
            phase.phase_id == _phase_id("land", "response")
            and transition.next_phase_id == _phase_id("land", "offer")
            and family_case["schema_condition"] == "dedicated_accept_schema"
        ):
            return TransitionResult(
                transition.state,
                DEDICATED_PHASE_ID,
                transition.consequences,
            )
        return transition

    def outcome(self, family_case, terminal) -> dict[str, Any]:
        outcome = super().outcome(family_case, terminal)
        outcome["schema_condition"] = family_case["schema_condition"]
        return outcome

    def build_scorer(self, family_case) -> CounterofferAdoptionScorer:
        return CounterofferAdoptionScorer(family_case)


def register_action_schema_plugin(registry: PluginRegistry, *, plugin=None):
    resolved = plugin or CounterofferActionSchemaPlugin()
    registry.register_trusted(action_schema_family_manifest(), resolved)
    return resolved


__all__ = [
    "CONDITIONS",
    "DEDICATED_ACTION_SCHEMA_ID",
    "DEDICATED_PHASE_ID",
    "FAMILY_ID",
    "FAMILY_VERSION",
    "PLUGIN_ID",
    "CounterofferActionSchemaPlugin",
    "action_schema_family_manifest",
    "register_action_schema_plugin",
]
