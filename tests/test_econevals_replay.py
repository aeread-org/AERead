"""Tests for the econevals offline replayer (replay.py, milestone 3).

Follows the same ``_bridge()``/skip convention as
``tests/test_econevals_environment.py``: pure structural tests run
everywhere; tests that actually replay tool calls run for real when a
pinned upstream bridge interpreter is provisioned, and are skipped (never
faked) otherwise.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from aeread.shared_runner.execution import EvidenceStore
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.resolver import PlanCell, case_content_sha256, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import run_episode
from aeread_families.econevals.econevals_bridge import (
    EconevalsBridge,
    EconevalsBridgeUnavailableError,
    discover_bridge_python,
)
from aeread_families.econevals.environment import (
    SEAT_ID,
    EconevalsPlugin,
    family_manifest,
    register_plugin,
)
from aeread_families.econevals.harness import ScriptedEconevalsHarness
from aeread_families.econevals.replay import (
    RecordedDecision,
    RecordedEpisode,
    RecordedResponseSource,
    ReplayError,
    assert_replay_matches,
    compare_episode_results,
    record_episode,
    replay_and_verify,
    replay_episode,
    score_replayed_episode,
)

CASES_DIR = Path("cases/econevals")

try:
    BRIDGE_PYTHON = discover_bridge_python()
except EconevalsBridgeUnavailableError as error:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = str(error)
else:
    _BRIDGE_SKIP_REASON = ""


def _bridge() -> EconevalsBridge:
    if BRIDGE_PYTHON is None:
        pytest.skip(_BRIDGE_SKIP_REASON or "bridge python unavailable")
    return EconevalsBridge(python_executable=BRIDGE_PYTHON)


def _shrunk_case(split: str, case_id: str, *, max_steps: int) -> CaseManifest:
    """See ``tests/test_econevals_environment.py``'s identical helper: a
    test-scoped copy of a real pilot case with a much smaller
    ``pins.max_steps``/``episode.max_logical_actions`` so a replay test can
    reach a genuine termination in a handful of periods."""
    path = CASES_DIR / split / f"{case_id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["payload"] = dict(raw["payload"])
    raw["payload"]["pins"] = dict(raw["payload"]["pins"])
    raw["payload"]["pins"]["max_steps"] = max_steps
    raw["episode"] = dict(raw["episode"])
    raw["episode"]["max_logical_actions"] = max_steps
    raw["content_sha256"] = case_content_sha256(raw)
    return CaseManifest.from_dict(raw)


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_econevals_replay_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_econevals_replay",
        suite_version="0.1.0",
        block_id="block_econevals_replay",
        sampling_plan_id="sampling_econevals_replay",
        analysis_plan_id="analysis_econevals_replay",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_econevals_replay_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType({SEAT_ID: "scripted_agent"}),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _pricing_script(product_ids: list[str], *, periods: int) -> list[list[dict]]:
    prices = {product_id: 1.0 for product_id in product_ids}
    return [
        [
            {"id": "1", "name": "get_product_ids", "arguments": {}},
            {"id": "2", "name": "set_prices", "arguments": {"prices_dict_str": prices}},
        ]
        for _ in range(periods)
    ]


def _run_live(bridge: EconevalsBridge, tmp_path: Path, *, suffix: str):
    case = _shrunk_case("pricing_basic", "econevals.pricing.basic.0", max_steps=3)
    cell = _cell(case, suffix=suffix)
    plugin = EconevalsPlugin(bridge=bridge)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())
    family_case = plugin.validate_payload(case.payload)
    product_ids = family_case["generated_instance"]["product_ids"]

    evidence = EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_econevals_replay_{suffix}",
        cell_id=cell.cell_id,
        episode_id=f"episode_econevals_replay_{suffix}",
        episode_attempt_id="attempt_1",
    )
    harness = ScriptedEconevalsHarness(
        plugin=resolved_plugin,
        family_case=family_case,
        evidence=evidence,
        script=_pricing_script(product_ids, periods=3),
    )
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=harness)
    )
    evidence.seal()
    return case, cell, resolved_plugin, family_case, result


# ---------------------------------------------------------------------------
# Pure, no bridge: RecordedDecision/RecordedEpisode structural round-tripping.
# ---------------------------------------------------------------------------


def test_recorded_episode_round_trips_through_plain_json() -> None:
    decision = RecordedDecision(
        phase_id="period",
        seat_id="agent",
        response={"tool_calls": [{"id": "1"}], "n": (1, 2)},
    )
    episode = RecordedEpisode(case_id="econevals.pricing.basic.0", decisions=(decision,))

    text = episode.to_json()
    restored = RecordedEpisode.from_json(text)

    assert restored.case_id == episode.case_id
    assert len(restored.decisions) == 1
    assert restored.decisions[0].phase_id == "period"
    assert restored.decisions[0].seat_id == "agent"
    # Tuple/list distinctions collapse to JSON arrays through the round trip.
    assert restored.decisions[0].response == {
        "tool_calls": [{"id": "1"}],
        "n": [1, 2],
    }


def test_recorded_response_source_enforces_ordering_and_reports_exhaustion() -> None:
    decisions = (
        RecordedDecision(phase_id="period", seat_id="agent", response={"tool_calls": []}),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "period"
        seat_id = "agent"

    response = asyncio.run(source(_Request()))
    assert response == {"tool_calls": []}
    assert source.exhausted is True

    with pytest.raises(ReplayError, match="exhausted"):
        asyncio.run(source(_Request()))


def test_recorded_response_source_rejects_phase_seat_mismatch() -> None:
    decisions = (
        RecordedDecision(phase_id="period", seat_id="agent", response={"tool_calls": []}),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "period"
        seat_id = "someone_else"

    with pytest.raises(ReplayError, match="does not match"):
        asyncio.run(source(_Request()))


def test_compare_episode_results_reports_specific_mismatches_not_one_boolean() -> None:
    """A synthetic mismatch (mutated terminal) must be visible per-component."""

    class _Fake:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    original = _Fake(
        phase_instances=(),
        terminal={"reason": "max_periods"},
        outcome={"period_count": 3},
        final_state={"period": 3, "attempts": []},
    )
    replayed = _Fake(
        phase_instances=(),
        terminal={"reason": "error"},
        outcome={"period_count": 3},
        final_state={"period": 3, "attempts": []},
    )

    comparison = compare_episode_results(original, replayed)

    assert comparison.terminal_matches is False
    assert comparison.outcome_matches is True
    assert comparison.matches is False
    with pytest.raises(ReplayError, match="terminal record differs"):
        assert_replay_matches(comparison)


# ---------------------------------------------------------------------------
# Bridge-gated: genuine offline replay of a live, tool-executing episode.
# ---------------------------------------------------------------------------


def test_replay_from_a_json_round_tripped_record_reproduces_the_live_run_byte_identically(
    tmp_path: Path,
) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, family_case, original = _run_live(
        bridge, tmp_path, suffix="live"
    )

    recorded = record_episode(original)
    # Force a genuine round trip through plain JSON text -- proves replay
    # never depends on reusing the original run's in-memory Python objects.
    recorded = RecordedEpisode.from_json(recorded.to_json())
    assert recorded.case_id == case.case_id

    # A second, independent EconevalsBridge/plugin -- not the one that
    # produced the original run -- drives the replay, through the SAME
    # PlanCell (so phase_instance_id/episode_id agree; see replay.py's own
    # docstring on why this family's raw state is expected to byte-match,
    # unlike tau3.retail's timestamped messages).
    replay_bridge = EconevalsBridge(python_executable=BRIDGE_PYTHON)
    replay_plugin = EconevalsPlugin(bridge=replay_bridge)
    registry = PluginRegistry()
    register_plugin(registry, plugin=replay_plugin)
    resolved_replay_plugin = registry.resolve_manifest(family_manifest())

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=resolved_replay_plugin, recorded=recorded)
    )

    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is True
    assert comparison.state_hashes_match is True
    assert comparison.final_state_matches is True
    assert comparison.original_final_state_sha256 == comparison.replayed_final_state_sha256
    assert replayed.terminal["reason"] == "max_periods"

    # Genuinely byte-identical, not merely content-equivalent (see
    # replay.py's module docstring for why econevals's state affords this
    # where tau3.retail's cannot).
    assert canonical_json_bytes(replayed.final_state) == canonical_json_bytes(
        original.final_state
    )


def test_replayed_episode_recomputes_both_leaves_from_the_final_attempts_list(
    tmp_path: Path,
) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, family_case, original = _run_live(
        bridge, tmp_path, suffix="score"
    )
    recorded = record_episode(original)

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=resolved_plugin, recorded=recorded)
    )
    scorer = resolved_plugin.build_scorer(family_case)

    scores = score_replayed_episode(scorer=scorer, replayed=replayed)
    original_gate, original_objective = scorer.score_terminal_state(original.final_state)

    assert scores.gate == original_gate
    assert scores.objective == original_objective
    assert scores.gate.primary.value == 1.0
    assert scores.objective is not None
    assert scores.objective.leaf.estimand.units == "profit_usd"


def test_replay_and_verify_end_to_end_returns_a_matching_report(tmp_path: Path) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, family_case, original = _run_live(
        bridge, tmp_path, suffix="e2e"
    )
    recorded = record_episode(original)
    scorer = resolved_plugin.build_scorer(family_case)

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            plugin=resolved_plugin,
            scorer=scorer,
            recorded=recorded,
            original=original,
        )
    )

    assert report.status == "match"
    assert report.scores.gate.primary.value == 1.0
    assert report.final_state_sha256 == original.phase_instances[-1].post_state_sha256


def test_replay_raises_when_a_recorded_tool_result_is_tampered_with(tmp_path: Path) -> None:
    """The tool-level replay guarantee: step() itself catches this, and
    replay_episode must not swallow it."""
    bridge = _bridge()
    case, cell, resolved_plugin, family_case, original = _run_live(
        bridge, tmp_path, suffix="tamper"
    )
    recorded = record_episode(original)

    tampered_decisions = list(recorded.decisions)
    first = tampered_decisions[0]
    response = dict(first.response)
    executions = [dict(item) for item in response["tool_executions"]]
    executions[0] = dict(executions[0])
    executions[0]["result"] = dict(executions[0]["result"])
    executions[0]["result"]["content"] = {"product_ids": ["tampered"]}
    response["tool_executions"] = executions
    tampered_decisions[0] = RecordedDecision(
        phase_id=first.phase_id, seat_id=first.seat_id, response=response
    )
    tampered = RecordedEpisode(case_id=recorded.case_id, decisions=tuple(tampered_decisions))

    with pytest.raises(RuntimeError, match="tool replay result differs"):
        asyncio.run(
            replay_episode(cell=cell, case=case, plugin=resolved_plugin, recorded=tampered)
        )


def test_replay_case_mismatch_raises_a_typed_replay_error(tmp_path: Path) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, family_case, original = _run_live(
        bridge, tmp_path, suffix="mismatch"
    )
    recorded = record_episode(original)
    wrong_case = RecordedEpisode(
        case_id="econevals.pricing.basic.999", decisions=recorded.decisions
    )

    with pytest.raises(ReplayError, match="not"):
        asyncio.run(
            replay_episode(cell=cell, case=case, plugin=resolved_plugin, recorded=wrong_case)
        )
