"""Tests for the amazonbarg.bilateral scripted harness (harness.py, milestone 3).

Drives at least two full episodes through the REAL shared-runner path
(``run_episode`` with the genuine ``AmazonbargPlugin``/registry, never a
hand-wired shortcut) using ``ScriptedAmazonbargHarness``, and proves the
sealed ``EvidenceStore`` this harness produces is a genuine, verifiable,
hash-chained record -- not merely an in-memory transcript. See
``tests/test_amazonbarg_replay.py`` for what these same two sealed episodes
are then used to replay.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from aeread.shared_runner.execution import EvidenceStore
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.resolver import PlanCell
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import run_episode
from aeread_families.amazonbarg import cases as amazonbarg_cases
from aeread_families.amazonbarg.environment import (
    BUYER_PHASE,
    SELLER_PHASE,
    AmazonbargPlugin,
    family_manifest,
    register_plugin,
)
from aeread_families.amazonbarg.harness import (
    EVENT_TYPE_DECISION_SERVED,
    ScriptedAmazonbargHarness,
)


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_AMAZONBARG_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-amazonbarg",
    )
    root = Path(candidate)
    marker = root / "data" / "AmazonHistoryPrice" / "home-kitchen.json"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream AmazonPriceHistory checkout not found at {root}",
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()
CASES_DIR = Path("cases/amazonbarg/pilot")


def _case(codename: str) -> CaseManifest:
    case_id = amazonbarg_cases.case_id_for_codename(codename)
    path = CASES_DIR / f"{case_id}.json"
    if not path.is_file():
        pytest.skip(f"checked-in case file not found at {path}")
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_amazonbarg_harness_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_amazonbarg_harness",
        suite_version="0.1.0",
        block_id="block_amazonbarg_harness",
        sampling_plan_id="sampling_amazonbarg_harness",
        analysis_plan_id="analysis_amazonbarg_harness",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_amazonbarg_harness_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType({"buyer": "scripted_buyer", "seller": "scripted_seller"}),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _evidence(tmp_path: Path, *, suffix: str) -> EvidenceStore:
    return EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_amazonbarg_harness_{suffix}",
        cell_id=f"cell_amazonbarg_harness_{suffix}",
        episode_id=f"episode_amazonbarg_harness_{suffix}",
        episode_attempt_id="attempt_1",
    )


def _registry_plugin() -> tuple[PluginRegistry, AmazonbargPlugin]:
    plugin = AmazonbargPlugin(upstream_root=UPSTREAM_ROOT)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    return registry, registry.resolve_manifest(family_manifest())


# Two full episodes, run end to end through the real scheduler, one closing
# a deal (golden 1) and one quitting with no ZOPA at all (golden 5) -- see
# docs/amazonbarg_adapter_spec.md section 4.
GOLDEN_1_SCRIPT = [
    (BUYER_PHASE, "buyer", {"content": "Thought: t\nTalk: hi\nAction: [BUY] $120 (1x home-kitchen_2)"}),
    (SELLER_PHASE, "seller", {"content": "Thought: t\nTalk: ok\nAction: [SELL] $150 (1x home-kitchen_2)"}),
    (BUYER_PHASE, "buyer", {"content": "Thought: t\nTalk: deal?\nAction: [BUY] $135 (1x home-kitchen_2)"}),
    (SELLER_PHASE, "seller", {"content": "Thought: t\nTalk: yes\nAction: [DEAL] $135 (1x home-kitchen_2)"}),
]
GOLDEN_5_SCRIPT = [
    (BUYER_PHASE, "buyer", {"content": "Thought: t\nTalk: hi\nAction: [BUY] $850 (1x toys-games_22)"}),
    (SELLER_PHASE, "seller", {"content": "Thought: t\nTalk: no\nAction: [REJECT]"}),
    (BUYER_PHASE, "buyer", {"content": "Thought: t\nTalk: bye\nAction: [QUIT]"}),
]


def _run_sealed_episode(codename: str, script, tmp_path: Path, *, suffix: str):
    case = _case(codename)
    cell = _cell(case, suffix=suffix)
    _registry, resolved_plugin = _registry_plugin()
    evidence = _evidence(tmp_path, suffix=suffix)
    harness = ScriptedAmazonbargHarness(evidence=evidence, script=script)
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=harness)
    )
    return case, cell, resolved_plugin, evidence, harness, result


# ---------------------------------------------------------------------------
# Episode 1: golden 1, a successful deal.
# ---------------------------------------------------------------------------


def test_golden_1_runs_end_to_end_through_the_real_scheduler_and_seals_evidence(
    tmp_path: Path,
) -> None:
    case, cell, _plugin, evidence, harness, result = _run_sealed_episode(
        "home-kitchen_2", GOLDEN_1_SCRIPT, tmp_path, suffix="golden1"
    )

    assert harness.exhausted
    assert harness.sealed
    assert result.terminal["reason"] == "deal"
    assert result.terminal["terminating_actor"] == "seller"
    assert result.logical_action_count == 4

    # The evidence store is a genuinely durable, hash-chained record -- not
    # merely an in-memory transcript.
    evidence.verify_chain()
    seal = evidence.verify_seal()
    events = evidence.read_events()
    assert len(events) == 4
    assert seal.event_count == 4
    assert all(event.event_type == EVENT_TYPE_DECISION_SERVED for event in events)

    # Every served decision round-trips exactly through the sealed evidence.
    for (expected_phase, expected_seat, expected_response), event in zip(
        GOLDEN_1_SCRIPT, events
    ):
        payload = evidence.read_event_payload(event)
        assert payload["phase_id"] == expected_phase
        assert payload["seat_id"] == expected_seat
        assert payload["response"] == expected_response


# ---------------------------------------------------------------------------
# Episode 2: golden 5, the degenerate-reference (no-ZOPA) quit.
# ---------------------------------------------------------------------------


def test_golden_5_runs_end_to_end_through_the_real_scheduler_and_seals_evidence(
    tmp_path: Path,
) -> None:
    case, cell, _plugin, evidence, harness, result = _run_sealed_episode(
        "toys-games_22", GOLDEN_5_SCRIPT, tmp_path, suffix="golden5"
    )

    assert harness.exhausted
    assert harness.sealed
    assert result.terminal["reason"] == "quit"
    assert result.terminal["terminating_actor"] == "buyer"
    assert result.logical_action_count == 3

    evidence.verify_chain()
    seal = evidence.verify_seal()
    events = evidence.read_events()
    assert len(events) == 3
    assert seal.event_count == 3

    for (expected_phase, expected_seat, expected_response), event in zip(
        GOLDEN_5_SCRIPT, events
    ):
        payload = evidence.read_event_payload(event)
        assert payload["phase_id"] == expected_phase
        assert payload["seat_id"] == expected_seat
        assert payload["response"] == expected_response


# ---------------------------------------------------------------------------
# Harness contract: phase/seat ordering, exhaustion, sealed-once.
# ---------------------------------------------------------------------------


def test_harness_rejects_a_response_served_for_the_wrong_seat(tmp_path: Path) -> None:
    case = _case("home-kitchen_2")
    cell = _cell(case, suffix="wrong_seat")
    _registry, resolved_plugin = _registry_plugin()
    evidence = _evidence(tmp_path, suffix="wrong_seat")
    wrong_script = [
        (BUYER_PHASE, "seller", {"content": "Thought: t\nTalk: hi\nAction: [BUY] $1 (1x home-kitchen_2)"}),
    ]
    harness = ScriptedAmazonbargHarness(evidence=evidence, script=wrong_script)

    with pytest.raises(RuntimeError, match="script expected phase"):
        asyncio.run(
            run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=harness)
        )


def test_harness_raises_when_the_script_is_exhausted_before_termination(
    tmp_path: Path,
) -> None:
    case = _case("home-kitchen_2")
    cell = _cell(case, suffix="exhausted")
    _registry, resolved_plugin = _registry_plugin()
    evidence = _evidence(tmp_path, suffix="exhausted")
    short_script = [
        (BUYER_PHASE, "buyer", {"content": "Thought: t\nTalk: hi\nAction: [BUY] $120 (1x home-kitchen_2)"}),
    ]
    harness = ScriptedAmazonbargHarness(evidence=evidence, script=short_script)

    with pytest.raises(RuntimeError, match="script exhausted"):
        asyncio.run(
            run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=harness)
        )


def test_seal_is_idempotent_across_repeated_episode_completed_calls(tmp_path: Path) -> None:
    """``episode_completed`` fires exactly once from a real ``run_episode``
    run, but the harness's own guard against re-sealing is tested directly
    here so a future scheduler change that called it twice would not
    silently raise ``EvidenceSealedError`` instead of being a no-op."""
    evidence = _evidence(tmp_path, suffix="idempotent_seal")
    harness = ScriptedAmazonbargHarness(evidence=evidence, script=[])

    asyncio.run(harness.episode_completed(episode_result=None))
    asyncio.run(harness.episode_completed(episode_result=None))

    assert harness.sealed
    evidence.verify_seal()
