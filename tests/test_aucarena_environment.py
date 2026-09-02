"""Provider-free scheduler coverage for the ``aucarena`` environment plugin.

Drives all five QC Gate-2 goldens (spec section 5) through the real kernel
phase scheduler (``aeread.shared_runner.scheduler.run_episode``) with the
shipped ``ScriptedAucArenaHarness`` (``harness.py``, milestone 3 -- promoted
from an in-test class milestone 1 defined here, back when no shipped module
existed yet; see that spec section's milestone-1 note): the whole per-round
decision is "one seat's raw bid text", so a thin per-test policy function
plus that harness is enough.

These tests assert mechanical correctness of the environment (legality,
hammer determination, budget/profit bookkeeping, termination) -- leaf-result
assertions for the four declared ``MeasurementLeafSpec`` leaves live in
``tests/test_aucarena_measurement.py`` instead, against
``AucArenaPlugin.build_scorer``'s real scorer (``measurement.py``). Sealed,
tamper-evident evidence for a real, multi-episode run through this harness
is covered at the bottom of this module; replaying such a run offline lives
in ``tests/test_aucarena_replay.py``.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any

import pytest

from aeread.shared_runner.execution import EvidenceSealedError, EvidenceStore
from aeread.shared_runner.registry import REQUIRED_FAMILY_PLUGIN_HOOKS, PluginRegistry
from aeread.shared_runner.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import EpisodeResult, run_episode
from aeread_families.aucarena.environment import (
    AucArenaPlugin,
    BID_ROUND_PHASE,
    family_manifest,
    register_plugin,
)
from aeread_families.aucarena.harness import Policy, ScriptedAucArenaHarness

CASES_DIR = Path("cases/aucarena/pilot")


def _case(golden_name: str) -> CaseManifest:
    path = CASES_DIR / f"aucarena.pilot.{golden_name}_01.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest) -> PlanCell:
    profile_by_seat = {seat.id: f"scripted_{seat.id}" for seat in case.seats}
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_{case.case_id}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_aucarena_environment",
        suite_version="0.1.0",
        block_id="block_aucarena_environment",
        sampling_plan_id="sampling_aucarena_environment",
        analysis_plan_id="analysis_aucarena_environment",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id="cluster_aucarena_environment",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(profile_by_seat),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _min_markup_policy(seat_id: str, observation: Any) -> str:
    """"Bids the legal minimum markup on every round it stays in" (golden 1)."""
    if seat_id != "agent":
        return ""
    minimum = observation["minimum_next_bid"]
    if observation["own_budget"] >= minimum:
        return str(minimum)
    return "-1"


def _always_withdraw_policy(seat_id: str, observation: Any) -> str:
    del observation
    return "-1" if seat_id == "agent" else ""


def _illegal_150_policy(seat_id: str, observation: Any) -> str:
    del observation
    return "150" if seat_id == "agent" else ""


def _malformed_text_policy(seat_id: str, observation: Any) -> str:
    del observation
    return "uh, I'll think about it" if seat_id == "agent" else ""


def _run(case: CaseManifest, policy: Policy) -> EpisodeResult:
    plugin = AucArenaPlugin()
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved = registry.resolve_manifest(family_manifest())
    cell = _cell(case)
    harness = ScriptedAucArenaHarness(policy)
    return asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved, response_source=harness)
    )


def _all_actions(result: EpisodeResult):
    for phase_instance in result.phase_instances:
        yield from phase_instance.actions


def _plain(value: Any) -> Any:
    """Detach a frozen (tuple/MappingProxyType) evidence value back into
    ordinary JSON-shaped containers for easy comparison against literals."""
    return json.loads(canonical_json_bytes(value))


# ---------------------------------------------------------------------------
# Plugin registration and phase graph shape.
# ---------------------------------------------------------------------------


def test_plugin_registers_every_required_hook_through_normal_registry() -> None:
    plugin = AucArenaPlugin()
    registry = PluginRegistry()
    manifest = family_manifest()
    registered = register_plugin(registry, plugin=plugin)

    assert registered is plugin
    assert registry.resolve_manifest(manifest) is plugin
    assert set(REQUIRED_FAMILY_PLUGIN_HOOKS) == {
        name
        for name in REQUIRED_FAMILY_PLUGIN_HOOKS
        if callable(getattr(plugin, name, None))
    }


def test_phase_graph_is_one_self_looping_phase() -> None:
    plugin = AucArenaPlugin()
    case = _case("successful")
    phases = plugin.phases(plugin.validate_payload(case.payload))
    assert [(phase.phase_id, phase.mode, phase.next_phases) for phase in phases] == [
        (BID_ROUND_PHASE, "simultaneous", (BID_ROUND_PHASE,))
    ]


def test_build_scorer_returns_the_four_declared_leaves() -> None:
    plugin = AucArenaPlugin()
    case = _case("successful")
    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)
    assert len(scorer.leaves) == 4


# ---------------------------------------------------------------------------
# Golden 1: successful_01.
# ---------------------------------------------------------------------------


def test_golden_1_agent_wins_items_1_and_2_loses_3_and_4() -> None:
    result = _run(_case("successful"), _min_markup_policy)

    assert result.terminal["reason"] == "auction_complete"
    items_by_id = {entry["item_id"]: entry for entry in result.outcome["items"]}
    assert items_by_id[1]["winner"] == "agent"
    assert items_by_id[2]["winner"] == "agent"
    assert items_by_id[3]["winner"] == "field_high"
    assert items_by_id[4]["winner"] == "field_high"
    assert all(entry["sold"] for entry in result.outcome["items"])

    seats = result.outcome["seats"]
    assert seats["agent"]["profit"] == 800  # (2000-1600) x 2
    assert seats["agent"]["budget"] == 0
    assert seats["field_low"]["profit"] == 0  # withdraws immediately every time
    assert seats["field_high"]["profit"] == 2000  # (2000-1000) x 2

    # aucarena_bid_legality / aucarena_hammer_rule invariants: every recorded
    # action this episode is legal and well-formed.
    assert all(record.envelope.valid for record in _all_actions(result))


def test_golden_1_field_low_never_records_a_positive_bid() -> None:
    result = _run(_case("successful"), _min_markup_policy)
    field_low_bids = [
        record.envelope.action["bid_price"]
        for record in _all_actions(result)
        if record.seat_id == "field_low"
    ]
    assert field_low_bids  # it was asked every item
    assert all(bid_price < 0 for bid_price in field_low_bids)


# ---------------------------------------------------------------------------
# Golden 2: valid_but_poor_01.
# ---------------------------------------------------------------------------


def test_golden_2_agent_always_withdraws_and_ends_with_zero_profit() -> None:
    result = _run(_case("valid_but_poor"), _always_withdraw_policy)

    assert result.terminal["reason"] == "auction_complete"
    seats = result.outcome["seats"]
    assert seats["agent"]["profit"] == 0
    assert seats["agent"]["budget"] == 3200  # untouched
    assert _plain(seats["agent"]["items_won"]) == []
    # A valid, scoreable, strategically poor outcome -- never invalid.
    assert all(record.envelope.valid for record in _all_actions(result))
    # field_high (the only real bidder left) wins every item uncontested.
    assert all(entry["winner"] == "field_high" for entry in result.outcome["items"])


# ---------------------------------------------------------------------------
# Golden 3: invalid_unauthorized_01.
# ---------------------------------------------------------------------------


def test_golden_3_agents_150_bid_is_rejected_by_legal_with_zero_mutation() -> None:
    result = _run(_case("invalid_unauthorized"), _illegal_150_policy)

    agent_records = [r for r in _all_actions(result) if r.seat_id == "agent"]
    assert len(agent_records) == 1
    record = agent_records[0]
    assert record.parse.ok is True  # 150 is well-formed
    assert record.legality is not None
    assert record.legality.legal is False
    assert "lower than the starting bid" in record.legality.reason
    assert record.envelope.valid is False

    # Zero mutation: agent's budget is untouched, and the item resolves
    # exactly as if agent had never acted this round.
    assert result.outcome["seats"]["agent"]["budget"] == 3200
    assert result.outcome["seats"]["agent"]["profit"] == 0
    assert result.outcome["items"][0]["winner"] == "field_high"
    assert result.outcome["items"][0]["hammer_price"] == 1000


# ---------------------------------------------------------------------------
# Golden 4: malformed_operational_01.
# ---------------------------------------------------------------------------


def test_golden_4_agents_gibberish_is_malformed_not_illegal() -> None:
    result = _run(_case("malformed_operational"), _malformed_text_policy)

    agent_records = [r for r in _all_actions(result) if r.seat_id == "agent"]
    assert len(agent_records) == 1
    record = agent_records[0]
    assert record.parse.ok is False
    assert record.parse.error_code == "malformed_operational"
    assert record.legality is None  # legal() is never reached
    assert record.envelope.valid is False

    assert result.outcome["seats"]["agent"]["budget"] == 3200
    assert result.outcome["seats"]["agent"]["profit"] == 0
    assert result.outcome["items"][0]["winner"] == "field_high"


def test_golden_3_and_4_fail_through_distinct_code_paths() -> None:
    illegal = _run(_case("invalid_unauthorized"), _illegal_150_policy)
    malformed = _run(_case("malformed_operational"), _malformed_text_policy)

    illegal_record = next(r for r in _all_actions(illegal) if r.seat_id == "agent")
    malformed_record = next(r for r in _all_actions(malformed) if r.seat_id == "agent")

    assert illegal_record.parse.ok is True and illegal_record.legality.legal is False
    assert malformed_record.parse.ok is False and malformed_record.legality is None


# ---------------------------------------------------------------------------
# Golden 5: degenerate_reference_01.
# ---------------------------------------------------------------------------


def test_golden_5_single_seat_withdraws_and_item_fails_to_sell() -> None:
    result = _run(_case("degenerate_reference"), _always_withdraw_policy)

    assert result.terminal["reason"] == "auction_complete"
    assert _plain(result.outcome["items"]) == [
        {"item_id": 5, "sold": False, "winner": None, "hammer_price": None}
    ]
    seats = result.outcome["seats"]
    assert seats["agent"]["profit"] == 0
    assert seats["agent"]["budget"] == 6000  # untouched
    assert all(record.envelope.valid for record in _all_actions(result))


# ---------------------------------------------------------------------------
# Determinism / replay-readiness: same case, same policy, same seed -> the
# same terminal outcome every time (no upstream import, no network; this is
# what lets replay.py be exact by construction -- see replay.py and
# tests/test_aucarena_replay.py, milestone 3).
# ---------------------------------------------------------------------------


def test_golden_1_is_deterministic_across_repeated_runs() -> None:
    case = _case("successful")
    first = _run(case, _min_markup_policy)
    second = _run(case, _min_markup_policy)
    assert first.outcome == second.outcome
    assert first.final_state == second.final_state


# ---------------------------------------------------------------------------
# Milestone 3: the shipped ``ScriptedAucArenaHarness`` seals every bid
# decision it serves into a real ``EvidenceStore`` -- a tamper-evident,
# hash-chained log of the one externally-supplied input this family's
# environment ever consumes. Two full episodes (goldens 1 and 3, chosen for
# distinct shapes: a full 4-item multi-round auction vs. a single illegal-bid
# episode) each drive their own sealed evidence generation through the real
# kernel scheduler -- not a hand-wired shortcut around ``run_episode``.
# ---------------------------------------------------------------------------


def _run_sealed(
    case: CaseManifest, policy: Policy, evidence: EvidenceStore
) -> tuple[EpisodeResult, ScriptedAucArenaHarness]:
    plugin = AucArenaPlugin()
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved = registry.resolve_manifest(family_manifest())
    cell = _cell(case)
    harness = ScriptedAucArenaHarness(policy, evidence=evidence)
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved, response_source=harness)
    )
    return result, harness


def test_two_full_episodes_each_produce_independently_sealed_evidence(
    tmp_path: Path,
) -> None:
    golden_1_evidence = EvidenceStore(
        tmp_path / "golden_1_evidence",
        run_plan_id="runplan_aucarena_sealed",
        cell_id="cell_aucarena_sealed_golden_1",
        episode_id="episode_aucarena_sealed_golden_1",
        episode_attempt_id="attempt_1",
    )
    golden_1_result, golden_1_harness = _run_sealed(
        _case("successful"), _min_markup_policy, golden_1_evidence
    )

    golden_3_evidence = EvidenceStore(
        tmp_path / "golden_3_evidence",
        run_plan_id="runplan_aucarena_sealed",
        cell_id="cell_aucarena_sealed_golden_3",
        episode_id="episode_aucarena_sealed_golden_3",
        episode_attempt_id="attempt_1",
    )
    golden_3_result, golden_3_harness = _run_sealed(
        _case("invalid_unauthorized"), _illegal_150_policy, golden_3_evidence
    )

    # Both episodes actually ran, end to end, through the real scheduler.
    assert golden_1_result.terminal["reason"] == "auction_complete"
    assert golden_3_result.terminal["reason"] == "auction_complete"
    assert len(golden_1_harness.requests) == golden_1_result.logical_action_count
    assert len(golden_3_harness.requests) == golden_3_result.logical_action_count

    for evidence, result in (
        (golden_1_evidence, golden_1_result),
        (golden_3_evidence, golden_3_result),
    ):
        evidence.verify_chain()
        events = evidence.read_events()
        assert [event.event_type for event in events] == (
            ["bid_decision_served"] * result.logical_action_count
        )
        # Sealing is durable and independently re-verifiable: a second call
        # returns the identical seal, and a fresh audit-only handle on the
        # same directory verifies it too -- this is the tamper-evident
        # guarantee, not just an in-memory claim.
        seal = evidence.seal()
        assert evidence.seal() == seal
        audited = EvidenceStore.audit_existing(evidence.root)
        assert audited.verify_seal() == seal

    # Every recorded event actually carries the response the harness served,
    # keyed to the same phase_instance_id/logical_action_id the scheduler
    # itself assigned -- not an empty or placeholder payload.
    first_event = golden_3_evidence.read_events()[0]
    payload = golden_3_evidence.read_event_payload(first_event)
    assert payload["seat_id"] == "agent"
    assert payload["response"] == "150"
    assert first_event.phase_instance_id == golden_3_result.phase_instances[0].phase_instance_id


def test_sealed_evidence_rejects_further_writes(tmp_path: Path) -> None:
    evidence = EvidenceStore(
        tmp_path / "sealed_rejects_writes",
        run_plan_id="runplan_aucarena_sealed_reject",
        cell_id="cell_aucarena_sealed_reject",
        episode_id="episode_aucarena_sealed_reject",
        episode_attempt_id="attempt_1",
    )
    _run_sealed(_case("valid_but_poor"), _always_withdraw_policy, evidence)
    evidence.seal()

    harness = ScriptedAucArenaHarness(_always_withdraw_policy, evidence=evidence)
    fake_request = SimpleNamespace(
        phase_id=BID_ROUND_PHASE,
        seat_id="agent",
        observation={},
        phase_instance_id="phase_instance_fake",
        logical_action_id="logical_action_fake",
    )

    with pytest.raises(EvidenceSealedError):
        asyncio.run(harness(fake_request))
