"""Tests for the collusion scripted-policy harness (``harness.py``, spec
section 3 milestone note; pattern: ``tau3_retail.harness.
ScriptedTau3RetailHarness``).

Two kinds of coverage:

* **Policy/harness unit tests** (pure or short-horizon, fast): each of the
  four named scripted policies computes the price spec section 3 says it
  should from a hand-built observation, and ``ScriptedCollusionHarness``
  itself validates ``policy_by_seat`` and records one evidence event per
  served decision.
* **Full-episode, real-shared-runner-path coverage** (spec section 5's
  milestone note: "at least 2 full episodes through the REAL shared-runner
  path, not a hand-wired shortcut"): one 300-round episode here, on the real
  committed ``baseline-symmetric``/alpha=1 pilot cell, driven entirely by
  ``ScriptedCollusionHarness`` through the real ``run_episode`` (not a direct
  call to ``environment.py``'s own hooks) -- the harness's own sealed
  evidence trail is asserted event-by-event. A second full episode, on a
  different real pilot cell with a genuinely reactive policy (tit-for-tat),
  lives in ``tests/test_collusion_replay.py`` (module-scoped and reused for
  the replay coverage there, mirroring ``test_collusion_measurement.py``'s
  own ``shared_nash_result`` convention) -- together the two files exercise
  "at least 2 full episodes" without re-running the expensive 300-round
  scheduler loop a third time.
"""
from __future__ import annotations

import asyncio
from types import MappingProxyType
from typing import Any

import pytest

from aeread.shared_runner.execution import EvidenceStore
from aeread.shared_runner.resolver import PlanCell, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import run_episode
from aeread_families.collusion import cases as collusion_cases
from aeread_families.collusion.environment import CollusionPlugin
from aeread_families.collusion.harness import (
    POLICY_ID_CONSTANT,
    POLICY_ID_MONOPOLY_PLAY,
    POLICY_ID_NASH_PLAY,
    POLICY_ID_TIT_FOR_TAT,
    ScriptedCollusionHarness,
    constant_policy,
    monopoly_play_policy,
    nash_play_policy,
    tit_for_tat_policy,
)

_SEATS = ("firm_a", "firm_b")


def _case() -> CaseManifest:
    """The real, committed baseline-symmetric/alpha=1/seed=0 pilot cell."""
    raw = collusion_cases.build_case("baseline-symmetric", 1.0, 0)
    return CaseManifest.from_dict(raw)


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_collusion_harness_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_collusion_harness",
        suite_version="0.1.0",
        block_id="block_collusion_harness",
        sampling_plan_id="sampling_collusion_harness",
        analysis_plan_id="analysis_collusion_harness",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_collusion_harness_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(
            {"firm_a": "scripted_firm_a", "firm_b": "scripted_firm_b"}
        ),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _evidence(tmp_path: Any, *, suffix: str) -> EvidenceStore:
    return EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_collusion_harness_{suffix}",
        cell_id=f"cell_collusion_harness_{suffix}",
        episode_id=f"episode_collusion_harness_{suffix}",
        episode_attempt_id="attempt_1",
    )


# ---------------------------------------------------------------------------
# Policy unit tests -- pure, no scheduler.
# ---------------------------------------------------------------------------


def test_constant_policy_ignores_the_observation_entirely() -> None:
    policy = constant_policy(1.5)
    assert policy({"round": 0, "price_history": ()}) == 1.5
    assert policy({"round": 299, "price_history": ({"round": 298},) * 5}) == 1.5


def test_nash_play_and_monopoly_play_are_named_constants() -> None:
    nash_policy = nash_play_policy(1.472927)
    monopoly_policy = monopoly_play_policy(1.924981)
    observation = {"round": 10, "price_history": ()}
    assert nash_policy(observation) == 1.472927
    assert monopoly_policy(observation) == 1.924981


def test_tit_for_tat_opens_with_the_given_price_when_history_is_empty() -> None:
    policy = tit_for_tat_policy(seat_id="firm_a", opening_price=1.7)
    assert policy({"round": 0, "price_history": ()}) == 1.7


def test_tit_for_tat_mirrors_the_opponents_most_recent_price() -> None:
    policy_a = tit_for_tat_policy(seat_id="firm_a", opening_price=1.7)
    policy_b = tit_for_tat_policy(seat_id="firm_b", opening_price=1.7)
    history = (
        {"round": 0, "prices": {"firm_a": 1.4, "firm_b": 1.9}, "valid": True},
        {"round": 1, "prices": {"firm_a": 1.5, "firm_b": 2.0}, "valid": True},
    )
    observation = {"round": 2, "price_history": history}
    # Each side mirrors the *other* seat's most recent price, never its own.
    assert policy_a(observation) == 2.0
    assert policy_b(observation) == 1.5


def test_tit_for_tat_rejects_an_unknown_seat_id() -> None:
    with pytest.raises(ValueError, match="seat_id"):
        tit_for_tat_policy(seat_id="firm_c", opening_price=1.0)


# ---------------------------------------------------------------------------
# ScriptedCollusionHarness -- structural, short horizon.
# ---------------------------------------------------------------------------


def test_harness_rejects_a_policy_by_seat_missing_a_declared_seat(tmp_path: Any) -> None:
    evidence = _evidence(tmp_path, suffix="missing_seat")
    with pytest.raises(ValueError, match="firm_a.*firm_b|firm_b.*firm_a"):
        ScriptedCollusionHarness(
            policy_by_seat={"firm_a": constant_policy(1.0)}, evidence=evidence
        )


def test_harness_drives_a_short_episode_through_the_real_scheduler(tmp_path: Any) -> None:
    raw = collusion_cases.build_case("baseline-symmetric", 1.0, 0)
    raw = dict(raw)
    raw["payload"] = dict(raw["payload"])
    raw["payload"]["horizon"] = 3
    raw["episode"] = dict(raw["episode"])
    raw["episode"]["max_logical_actions"] = 3 * collusion_cases.LOGICAL_ACTIONS_PER_ROUND
    raw["content_sha256"] = "0" * 64
    raw["content_sha256"] = case_content_sha256(raw)
    case = CaseManifest.from_dict(raw)
    gold = raw["payload"]["gold_reference"]

    evidence = _evidence(tmp_path, suffix="short")
    harness = ScriptedCollusionHarness(
        policy_by_seat={
            "firm_a": constant_policy(gold["p_monopoly"]["firm_a"]),
            "firm_b": constant_policy(gold["p_monopoly"]["firm_b"]),
        },
        evidence=evidence,
    )
    result = asyncio.run(
        run_episode(
            cell=_cell(case, suffix="short"),
            case=case,
            plugin=CollusionPlugin(),
            response_source=harness,
        )
    )
    assert result.terminal["reason"] == "max_periods"
    assert result.outcome["rounds_played"] == 3
    assert len(harness.requests) == 6  # 3 rounds * 2 seats.

    seal = harness.seal()
    assert seal.event_count == 6
    events = evidence.read_events()
    assert len(events) == 6
    assert {event.event_type for event in events} == {"collusion_price_submitted"}
    payload = evidence.read_event_payload(events[0])
    assert payload["seat_id"] == "firm_a"
    assert payload["round"] == 0
    assert payload["price"] == gold["p_monopoly"]["firm_a"]


# ---------------------------------------------------------------------------
# Full-episode, real-shared-runner-path coverage (1 of the >= 2 full
# episodes; see module docstring for the second, in test_collusion_replay.py).
# ---------------------------------------------------------------------------


def test_harness_drives_one_full_300_round_episode_with_sealed_evidence(
    tmp_path: Any,
) -> None:
    case = _case()
    gold = case.payload["gold_reference"]
    p_monopoly = gold["p_monopoly"]

    evidence = _evidence(tmp_path, suffix="full")
    harness = ScriptedCollusionHarness(
        policy_by_seat={
            "firm_a": monopoly_play_policy(p_monopoly["firm_a"]),
            "firm_b": monopoly_play_policy(p_monopoly["firm_b"]),
        },
        evidence=evidence,
    )
    result = asyncio.run(
        run_episode(
            cell=_cell(case, suffix="full"),
            case=case,
            plugin=CollusionPlugin(),
            response_source=harness,
        )
    )

    assert result.terminal["reason"] == "max_periods"
    assert result.outcome["rounds_played"] == case.payload["horizon"] == 300
    assert len(result.outcome["history"]) == 300
    assert all(entry["valid"] for entry in result.outcome["history"])
    for entry in result.outcome["history"]:
        assert entry["prices"] == {
            "firm_a": p_monopoly["firm_a"],
            "firm_b": p_monopoly["firm_b"],
        }

    # 300 rounds * 2 seats -- every logical action recorded and sealed.
    assert len(harness.requests) == 600
    seal = harness.seal()
    assert seal.event_count == 600
    # Sealing twice must be idempotent (EvidenceStore.seal()'s own contract).
    assert harness.seal() == seal


def test_family_manifest_declares_the_four_named_scripted_policies() -> None:
    from aeread_families.collusion.environment import family_manifest

    manifest = family_manifest()
    assert set(manifest.roles["pricing_agent"].scripted_policies) == {
        POLICY_ID_CONSTANT,
        POLICY_ID_TIT_FOR_TAT,
        POLICY_ID_NASH_PLAY,
        POLICY_ID_MONOPOLY_PLAY,
    }
