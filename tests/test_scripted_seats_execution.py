"""Scripted seats (docs/kernel_scripted_seats_design.md, #92), slice 2.

Execution, sealing, receipts and replay of a seat the family resolves itself.
Built on the kernel-owned reference family: a ``counterpart`` role that is
not testable and is filled by a deterministic policy, taking one turn between
the participant's two rounds.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import pytest

from aeread.shared_runner.run.resolver import ImplementationPin, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest, RoleSpec
from aeread.shared_runner.task.evaluation import finalize_family_execution, replay_family_receipt
from aeread.shared_runner.task.execution import execute_plan_cell
from aeread.shared_runner.task.scheduler import ParseResult, PhaseSpec, SchedulerContractError, TransitionResult
from tests.test_shared_runner_scoring_contract import (
    _REFERENCE_BALANCE_LEAF_ID,
    _REFERENCE_FAMILY_ID,
    _REFERENCE_FAMILY_VERSION,
    _REFERENCE_MODULE_DIGEST,
    _REFERENCE_TRAJECTORY_LEAF_ID,
    _ReferencePlugin,
    _reference_family_manifest,
    _run_reference_episode,
)

POLICY = "fixed_counterpart_v1"
SCRIPTED = {"counterpart_0": POLICY}


class _ScriptedCounterpartPlugin(_ReferencePlugin):
    """The reference family with a counterpart turn between the two rounds."""

    def phases(self, family_case):
        del family_case
        obs = {"participant": "kernel_contract_observation_v1", "counterpart": "kernel_contract_observation_v1"}
        act = {"participant": "kernel_contract_choice_v1", "counterpart": "kernel_contract_choice_v1"}
        return (
            PhaseSpec("round_one", "participant", "single", obs, act, 1, "reject", ("counterpart_turn",)),
            PhaseSpec("counterpart_turn", "counterpart", "single", obs, act, 1, "reject", ("round_two",)),
            PhaseSpec("round_two", "participant", "single", obs, act, 1, "reject", ()),
        )

    def eligible_actors(self, family_case, state, phase):
        del family_case, state
        return ("counterpart_0",) if phase.phase_id == "counterpart_turn" else ("participant_0",)

    def parse_action(self, family_case, state, seat, phase, response):
        # A scripted seat hands the scheduler the structured response, as a
        # harness-driven model seat would; the reference family's model seat
        # still speaks in canonical responses.
        if isinstance(response, Mapping):
            if response.get("label") in {"x", "y"}:
                return ParseResult.success({"label": response["label"]})
            return ParseResult.failure("malformed_choice")
        return super().parse_action(family_case, state, seat, phase, response)

    def step(self, family_case, state, phase, actions):
        del family_case
        (seat_id,) = actions
        label = actions[seat_id].action["label"]
        next_state = {"labels": tuple(state["labels"]) + (label,)}
        next_phase = {"round_one": "counterpart_turn", "counterpart_turn": "round_two"}.get(phase.phase_id)
        return TransitionResult(state=next_state, next_phase_id=next_phase)

    def terminal(self, family_case, state):
        del family_case
        labels = tuple(state["labels"])
        return {"labels": labels} if len(labels) == 3 else None

    def scripted_response(self, policy_id, request, *, world_seed):
        assert policy_id == POLICY
        return {"label": "x" if (world_seed + request.observation["round"]) % 2 == 0 else "y"}


class _DriftedCounterpartPlugin(_ScriptedCounterpartPlugin):
    """The same family after someone changed the policy: replay must notice."""

    def scripted_response(self, policy_id, request, *, world_seed):
        original = super().scripted_response(policy_id, request, world_seed=world_seed)
        return {"label": "y" if original["label"] == "x" else "x"}


# The receipt's plan-pin-completeness check is only reachable through
# finalize_family_execution; it needs the reference leaves' validity and
# reference implementations pinned, the way the seat-scoped fixture pins them.
_LEAF_PINS = tuple(
    ImplementationPin.from_dict(
        {
            "component_id": f"{leaf_id}_{suffix}_v1",
            "kind": "reference",
            "version": "1.0.0",
            "sha256": _REFERENCE_MODULE_DIGEST,
        }
    )
    for leaf_id in (_REFERENCE_BALANCE_LEAF_ID, _REFERENCE_TRAJECTORY_LEAF_ID)
    for suffix in ("validity", "reference")
)


def _manifest():
    base = _reference_family_manifest()
    return dataclasses.replace(
        base,
        roles=MappingProxyType(
            {
                "participant": base.roles["participant"],
                "counterpart": RoleSpec(testable=False, scripted_policies=(POLICY,)),
            }
        ),
        environment=dataclasses.replace(
            base.environment, phase_specs=("round_one", "counterpart_turn", "round_two")
        ),
        # The receipt's plan-pin-completeness check (only reachable through
        # finalize) needs the leaves' implementations pinned, and the
        # resolver admits a pin only when the manifest cites it.
        scoring=dataclasses.replace(
            base.scoring,
            reference_provider_ids=tuple(base.scoring.reference_provider_ids)
            + tuple(pin.component_id for pin in _LEAF_PINS),
        ),
    )


def _case() -> CaseManifest:
    raw = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": "kernel_contract_scripted_counterpart_case_v1",
        "family_id": _REFERENCE_FAMILY_ID,
        "family_version": _REFERENCE_FAMILY_VERSION,
        "split": "dev",
        "world_seed": 1,
        "seats": [
            {"id": "participant_0", "role": "participant"},
            {"id": "counterpart_0", "role": "counterpart"},
        ],
        "episode": {"max_logical_actions": 3, "termination": ["both_rounds_recorded"]},
        "visibility_policy": "kernel_contract_reference_full_visibility_v1",
        "payload": {"scenario_id": "kernel_contract_scripted_counterpart_case_v1"},
        "provenance": {
            "generator_id": "kernel_contract_reference_generator_v1",
            "generator_version": "1.0.0",
            "review_status": "curated",
        },
        "content_sha256": "0" * 64,
    }
    raw["content_sha256"] = case_content_sha256(raw)
    return CaseManifest.from_dict(raw)


def _run(tmp_path: Path, plugin_factory=_ScriptedCounterpartPlugin):
    return asyncio.run(
        _run_reference_episode(
            ["x", "y"],
            evidence_root=tmp_path / "run",
            plugin_factory=plugin_factory,
            case=_case(),
            family_manifest=_manifest(),
            subject_seats=["participant_0"],
            extra_pins=_LEAF_PINS,
            scripted_seats=SCRIPTED,
        )
    )


def _payloads(execution, event_type):
    out = []
    for event in execution.evidence.read_events():
        if event.event_type == event_type:
            out.append((event, json.loads((execution.evidence.root / event.payload_ref).read_text())))
    return out


def test_a_scripted_seat_runs_without_a_provider_and_is_sealed_as_such(tmp_path: Path) -> None:
    setup, execution = _run(tmp_path)
    # observe() reports round = labels so far + 1, so the counterpart acts in
    # round 2; seed 1 + round 2 is odd -> "y". Participant scripted x then y.
    assert execution.episode_result.final_state["labels"] == ("x", "y", "y")
    # Exactly the model seat's two calls reached a provider; the counterpart never did.
    assert len(_payloads(execution, "provider_call_started")) == 2
    scripted = _payloads(execution, "scripted_action")
    assert len(scripted) == 1
    assert scripted[0][1]["policy_id"] == POLICY and scripted[0][1]["response"] == {"label": "y"}
    starts = {p["request"]["seat_id"]: p for _, p in _payloads(execution, "logical_action_started")}
    assert starts["counterpart_0"]["source"] == "scripted_policy"
    assert starts["counterpart_0"]["profile_id"] == f"scripted:{POLICY}"
    assert "source" not in starts["participant_0"]
    execution.evidence.audit_reconciliation()


def test_the_receipt_names_the_scripted_seat_apart_from_model_seats(tmp_path: Path) -> None:
    setup, execution = _run(tmp_path)
    receipt = finalize_family_execution(setup=setup, execution=execution)
    assert dict(receipt.scripted_seats) == SCRIPTED
    assert set(receipt.agent_profile_sha256_by_seat) == {"participant_0"}
    assert receipt.inclusion_status == "included"


def test_replay_recomputes_the_scripted_response_and_notices_drift(tmp_path: Path) -> None:
    setup, execution = _run(tmp_path)
    receipt = finalize_family_execution(setup=setup, execution=execution)
    replayed = replay_family_receipt(setup=setup, receipt=receipt, evidence_root=tmp_path / "run")
    assert replayed.receipt_sha256 == receipt.receipt_sha256

    drifted_setup, _ = _run(tmp_path / "drifted", plugin_factory=_DriftedCounterpartPlugin)
    with pytest.raises(ValueError, match="scripted response mismatch"):
        replay_family_receipt(setup=drifted_setup, receipt=receipt, evidence_root=tmp_path / "run")


def test_a_plugin_without_the_hook_fails_before_the_episode_starts(tmp_path: Path) -> None:
    class _NoHook(_ScriptedCounterpartPlugin):
        scripted_response = None

    with pytest.raises(SchedulerContractError, match="no scripted_response hook"):
        _run(tmp_path, plugin_factory=_NoHook)
