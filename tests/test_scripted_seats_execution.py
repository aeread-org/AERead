"""Scripted seats (docs/architecture/kernel_scripted_seats_design.md, #92), slice 2.

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


def test_a_scripted_receipt_and_its_plan_survive_the_research_layer_round_trip(tmp_path: Path) -> None:
    """The research layer rebuilds receipts and plans from disk and verifies
    their digests; a field it did not know about would deserialize as its
    default and fail verification -- which is how the TERMS-Bench publisher
    found this gap on its first real receipt."""
    from aeread.shared_runner.analysis import research
    from aeread.shared_runner.run.publication import receipt_projection
    from aeread.shared_runner.run.resolver import write_run_plan
    from aeread.shared_runner.task.receipts import read_evaluation_receipt

    setup, execution = _run(tmp_path)
    receipt = finalize_family_execution(setup=setup, execution=execution)
    serialized = read_evaluation_receipt(execution.evidence.root / "evaluation_receipt.json")
    assert dict(serialized["scripted_seats"]) == SCRIPTED
    rebuilt = research.deserialize_evaluation_receipt(serialized)
    assert rebuilt.receipt_sha256 == receipt.receipt_sha256
    assert dict(rebuilt.scripted_seats) == SCRIPTED
    # The public projection carries which seats were not models.
    assert receipt_projection(serialized, campaign_cell_key="k")["scripted_seats"] == SCRIPTED

    plan_path = write_run_plan(setup.plan, tmp_path / "run_plan.json")
    loaded = research._load_run_plan(plan_path)
    assert loaded.plan_sha256 == setup.plan.plan_sha256
    assert dict(loaded.cells[0].scripted_seats) == SCRIPTED


# Review of #150 (2026-09-09), findings 1-4, 6 and 7.


def test_the_projection_omits_scripted_seats_when_there_are_none(tmp_path: Path) -> None:
    """Finding 1: a receipt without a scripted seat projects the bytes it did
    before the field existed, so an earlier campaign can be republished into
    its own bundle (atomic_publish refuses different bytes)."""
    from aeread.shared_runner.run.publication import atomic_publish, jsonl, receipt_projection
    from aeread.shared_runner.task.receipts import read_evaluation_receipt

    setup, execution = _run(tmp_path)
    finalize_family_execution(setup=setup, execution=execution)
    serialized = dict(read_evaluation_receipt(execution.evidence.root / "evaluation_receipt.json"))
    serialized.pop("scripted_seats")
    before = {key: value for key, value in receipt_projection(serialized, campaign_cell_key="k").items()}
    assert "scripted_seats" not in before
    assert "scripted_seats" not in receipt_projection(
        {**serialized, "scripted_seats": {}}, campaign_cell_key="k"
    )
    path = tmp_path / "bundle" / "receipts.jsonl"
    atomic_publish(path, jsonl([before]))
    atomic_publish(path, jsonl([receipt_projection(serialized, campaign_cell_key="k")]))


def _attempt_dirs(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_dir() and path.parent.name == "attempts")


def test_an_async_hook_is_refused_at_execution_with_reconcilable_evidence(tmp_path: Path) -> None:
    """Finding 2: replay calls the hook synchronously, so an awaitable is
    refused where it is produced instead of breaking finalization later."""
    from aeread.shared_runner.task.execution import EvidenceStore

    class _AsyncHook(_ScriptedCounterpartPlugin):
        async def scripted_response(self, policy_id, request, *, world_seed):
            return {"label": "x"}

    with pytest.raises(SchedulerContractError, match="awaitable"):
        _run(tmp_path, plugin_factory=_AsyncHook)
    attempts = _attempt_dirs(tmp_path / "run")
    assert attempts
    for attempt in attempts:
        EvidenceStore.audit_existing(attempt).audit_reconciliation()


def test_a_raising_hook_leaves_reconcilable_evidence(tmp_path: Path) -> None:
    """Finding 3: the started attempt and logical action get terminal events,
    as the executor seals them for a model seat, before the error propagates."""
    from aeread.shared_runner.task.execution import EvidenceStore

    class _Raising(_ScriptedCounterpartPlugin):
        def scripted_response(self, policy_id, request, *, world_seed):
            raise RuntimeError("scripted policy bug")

    with pytest.raises(SchedulerContractError, match="scripted policy bug"):
        _run(tmp_path, plugin_factory=_Raising)
    attempts = _attempt_dirs(tmp_path / "run")
    assert attempts
    for attempt in attempts:
        store = EvidenceStore.audit_existing(attempt)
        store.audit_reconciliation()
        failed = [event for event in store.read_events() if event.event_type == "action_attempt_failed"]
        assert len(failed) == 1


def test_replay_and_audit_refuse_scripted_seats_that_disagree_with_the_plan(tmp_path: Path) -> None:
    """Finding 4: a self-consistent receipt that names another policy for the
    scripted seat no longer passes replay or audit."""
    from aeread.shared_runner.task.evaluation import audit_family_receipt
    from aeread.shared_runner.task.receipts import seal_evaluation_receipt, write_evaluation_receipt

    setup, execution = _run(tmp_path)
    receipt = finalize_family_execution(setup=setup, execution=execution)
    tampered = seal_evaluation_receipt(
        dataclasses.replace(
            receipt,
            receipt_sha256=None,
            scripted_seats=MappingProxyType({"counterpart_0": "some_other_policy_v9"}),
        )
    )
    with pytest.raises(ValueError, match="scripted seats do not match"):
        replay_family_receipt(setup=setup, receipt=tampered, evidence_root=tmp_path / "run")
    path = execution.evidence.root / "evaluation_receipt.json"
    audit_family_receipt(setup=setup, receipt_path=path)
    path.unlink()
    write_evaluation_receipt(tampered, path)
    with pytest.raises(ValueError, match="scripted_seats does not match"):
        audit_family_receipt(setup=setup, receipt_path=path)


def test_a_cell_with_a_seat_both_scripted_and_profiled_is_refused(tmp_path: Path) -> None:
    """Finding 6: the scheduler's cell check rejects the overlap that RunSpec
    forbids, for a cell built outside the resolver."""
    from aeread.shared_runner.task.scheduler import _validate_cell_case

    setup, _ = _run(tmp_path)
    cell = setup.plan.cells[0]
    profile = next(iter(cell.profile_by_seat))
    both = dataclasses.replace(
        cell, scripted_seats=MappingProxyType({**cell.scripted_seats, profile: POLICY})
    )
    with pytest.raises(SchedulerContractError, match="both a model profile and a scripted policy"):
        _validate_cell_case(both, _case())


def test_the_research_layer_refuses_a_provider_call_from_a_scripted_seat(tmp_path: Path, monkeypatch) -> None:
    """Finding 7: a scripted seat is permitted to act, never to call a model."""
    from types import SimpleNamespace

    from aeread.shared_runner.analysis import research

    setup, execution = _run(tmp_path)
    receipt = finalize_family_execution(setup=setup, execution=execution)
    stores = {setup.plan.cells[0].cell_id: execution.evidence}
    research.project_loss_analysis_tables(setup.plan, [receipt], stores)

    real = research._extract_model_calls

    def with_a_scripted_call(evidence, *, task_id):
        return (*real(evidence, task_id=task_id), SimpleNamespace(seat_id="counterpart_0"))

    monkeypatch.setattr(research, "_extract_model_calls", with_a_scripted_call)
    with pytest.raises(research.ResearchContractError, match="scripted seats made provider calls"):
        research.project_loss_analysis_tables(setup.plan, [receipt], stores)
