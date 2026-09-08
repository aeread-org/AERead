"""Paired re-emission versus by-reference counteroffer acceptance."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from typing import Any

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.execution import CanonicalResponse
from aeread.shared_runner.task.scheduler import (
    LegalityResult,
    ParseResult,
    TransitionResult,
)

from .adoption_environment import CounterofferAdoptionPlugin
from .adoption_environment_v3 import NullableProseCounterofferAdoptionPlugin
from .adoption_measurement import CounterofferAdoptionScorer
from .contracts import LandAgreement, make_offer
from .stack_environment import _phase_id, _plain, phase_ids


FAMILY_ID = "datacenter_counteroffer_affordance_v1"
FAMILY_VERSION = "1.0.0"
PLUGIN_ID = "datacenter_counteroffer_affordance_environment_v1"
SCORER_ID = "datacenter_counteroffer_adoption_score_set_v1"
CONDITIONS = ("reemit_package", "accept_by_reference")


def affordance_family_manifest() -> FamilyManifest:
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {
                "id": FAMILY_ID,
                "version": FAMILY_VERSION,
                "plugin_id": PLUGIN_ID,
            },
            "environment": {
                "topology": "paired_land_counteroffer_acceptance_affordance_v1",
                "phase_specs": list(phase_ids("v2")[:3]),
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
                "comparison_baseline": "paired_full_package_reemission",
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


class CounterofferAffordancePlugin(NullableProseCounterofferAdoptionPlugin):
    """Expose one formal counteroffer, with a condition-specific resolution rule."""

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        expected = {
            "base_case_id",
            "base_case_sha256",
            "stage_id",
            "required_sequence",
            "affordance_condition",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("affordance payload fields differ")
        condition = payload["affordance_condition"]
        if condition not in CONDITIONS:
            raise ValueError("unknown affordance condition")
        base_payload = {
            key: value for key, value in payload.items() if key != "affordance_condition"
        }
        expanded = CounterofferAdoptionPlugin().validate_payload(base_payload)
        if expanded["adoption_stage"]["required_sequence"] != ["land"]:
            raise ValueError("affordance diagnostic must remain land-only")
        expanded["affordance_condition"] = condition
        return expanded

    def initial_state(self, family_case, run) -> dict[str, Any]:
        state = super().initial_state(family_case, run)
        state["pending_counteroffer_id"] = {"land": None}
        state["reference_acceptance_count"] = 0
        return state

    def phases(self, family_case):
        phases = super().phases(family_case)
        return tuple(
            dataclasses.replace(
                phase,
                next_phases=(
                    _phase_id("land", "response"),
                    _phase_id("land", "commit"),
                ),
            )
            if phase.phase_id == _phase_id("land", "offer")
            else phase
            for phase in phases
        )

    def observe(self, family_case, state, seat, phase) -> dict[str, Any]:
        observation = super().observe(family_case, state, seat, phase)
        if seat != "developer":
            return observation
        observation["counteroffer_adoption_task"]["required_behavior"] = (
            "Submit starter_offer_terms first. When a formal counteroffer is "
            "pending, follow counteroffer_resolution exactly, then sign the "
            "accepted_offer_id."
        )
        if phase.phase_id.endswith("_offer"):
            counteroffer_id = state["pending_counteroffer_id"]["land"]
            if counteroffer_id is not None:
                condition = family_case["affordance_condition"]
                observation["pending_counteroffer_offer_id"] = counteroffer_id
                observation["counteroffer_resolution"] = {
                    "mode": condition,
                    "required_action": (
                        {
                            "decision": "offer",
                            "offer_id": None,
                            "message": "Nonbinding prose may be null.",
                            "terms": "Copy pending_counter_terms exactly.",
                        }
                        if condition == "reemit_package"
                        else {
                            "decision": "accept_counteroffer",
                            "offer_id": "Copy pending_counteroffer_offer_id exactly.",
                            "message": None,
                            "terms": None,
                        }
                    ),
                }
        return observation

    def parse_action(self, family_case, state, seat, phase, response):
        if isinstance(response, CanonicalResponse) and phase.phase_id.endswith(
            "_offer"
        ):
            try:
                value = json.loads(response.text)
            except (TypeError, json.JSONDecodeError):
                value = None
            if isinstance(value, dict) and set(value) == {
                "decision",
                "offer_id",
                "message",
                "terms",
            }:
                if (
                    value["decision"] == "accept_counteroffer"
                    and isinstance(value["offer_id"], str)
                    and value["message"] is None
                    and value["terms"] is None
                ):
                    return ParseResult.success(
                        {
                            "decision": "accept_counteroffer",
                            "offer_id": value["offer_id"],
                        }
                    )
                if value["decision"] in {"offer", "walk"} and value[
                    "offer_id"
                ] is None:
                    normalized = {
                        key: value[key] for key in ("decision", "message", "terms")
                    }
                    response = dataclasses.replace(
                        response,
                        text=canonical_json_bytes(normalized).decode("utf-8"),
                    )
        return super().parse_action(family_case, state, seat, phase, response)

    def legal(self, family_case, state, seat, phase, action):
        if action["decision"] != "accept_counteroffer":
            return super().legal(family_case, state, seat, phase, action)
        if family_case["affordance_condition"] != "accept_by_reference":
            return LegalityResult.illegal("reference_acceptance_not_available")
        expected = state["pending_counteroffer_id"]["land"]
        if not phase.phase_id.endswith("_offer") or action["offer_id"] != expected:
            return LegalityResult.illegal("stale_or_unknown_counteroffer")
        offer = next(
            (item for item in state["offers"] if item["offer_id"] == expected), None
        )
        if offer is None or offer["proposer_seat_id"] != "landowner":
            return LegalityResult.illegal("counteroffer_provenance_invalid")
        if canonical_json_bytes(offer["terms"]) != canonical_json_bytes(
            state["pending_counter_terms"]["land"]
        ):
            return LegalityResult.illegal("counteroffer_terms_drift")
        return LegalityResult.legal_action()

    def step(self, family_case, state, phase, actions):
        seat = self.eligible_actors(family_case, state, phase)[0]
        envelope = actions[seat]
        if (
            envelope.valid
            and phase.phase_id.endswith("_offer")
            and envelope.action["decision"] == "accept_counteroffer"
        ):
            next_state = _plain(state)
            offer_id = envelope.action["offer_id"]
            next_state["accepted_offer_id"]["land"] = offer_id
            next_state["pending_counteroffer_id"]["land"] = None
            next_state["pending_counter_terms"]["land"] = None
            next_state["reference_acceptance_count"] += 1
            next_state["public_history"].append(
                {
                    "phase_id": phase.phase_id,
                    "seat_id": seat,
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
            envelope.valid
            and phase.phase_id.endswith("_response")
            and envelope.action["decision"] == "counter"
            and transition.next_phase_id == _phase_id("land", "offer")
        ):
            next_state = _plain(transition.state)
            counteroffer = make_offer(
                case_id=family_case["scenario_id"],
                agreement_type="land",
                proposer_seat_id="landowner",
                round_index=next_state["rounds"]["land"],
                message=envelope.action["message"],
                terms=LandAgreement.from_dict(envelope.action["terms"]),
            )
            next_state["offers"].append(_plain(counteroffer))
            next_state["latest_offer_id"]["land"] = counteroffer.offer_id
            next_state["pending_counteroffer_id"]["land"] = counteroffer.offer_id
            next_state["public_history"][-1][
                "counteroffer_id"
            ] = counteroffer.offer_id
            return TransitionResult(
                next_state,
                transition.next_phase_id,
                {
                    **dict(transition.consequences),
                    "formal_counteroffer_id": counteroffer.offer_id,
                },
            )
        return transition

    def outcome(self, family_case, terminal) -> dict[str, Any]:
        outcome = super().outcome(family_case, terminal)
        outcome["affordance_condition"] = family_case["affordance_condition"]
        outcome["reference_acceptance_count"] = terminal[
            "reference_acceptance_count"
        ]
        outcome["reference_acceptance_used"] = (
            terminal["reference_acceptance_count"] == 1
        )
        return outcome

    def build_scorer(self, family_case) -> CounterofferAdoptionScorer:
        return CounterofferAdoptionScorer(family_case)


def register_affordance_plugin(registry: PluginRegistry, *, plugin=None):
    resolved = plugin or CounterofferAffordancePlugin()
    registry.register_trusted(affordance_family_manifest(), resolved)
    return resolved


__all__ = [
    "CONDITIONS",
    "FAMILY_ID",
    "FAMILY_VERSION",
    "PLUGIN_ID",
    "CounterofferAffordancePlugin",
    "affordance_family_manifest",
    "register_affordance_plugin",
]
