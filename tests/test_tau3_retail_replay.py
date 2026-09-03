"""Tests for the tau3.retail offline replayer (replay.py, spec section 9).

Follows the same ``_bridge()``/skip convention as
``tests/test_tau3_retail_environment.py``: pure structural tests run
everywhere; tests that actually replay tool calls run for real when a
pinned upstream Python interpreter is provisioned, and are skipped (never
faked) otherwise.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from aeread.shared_runner.task.execution import EvidenceStore
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import SchedulerContractError, run_episode
from aeread_families.tau3_retail.environment import (
    Tau3RetailPlugin,
    family_manifest,
    register_plugin,
)
from aeread_families.tau3_retail.harness import ScriptedTau3RetailHarness
from aeread_families.tau3_retail.replay import (
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
from aeread_families.tau3_retail.tau2_bridge import (
    Tau2Bridge,
    Tau2BridgeUnavailableError,
    discover_bridge_python,
)


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_TAU2_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-tau2",
    )
    root = Path(candidate)
    marker = root / "data" / "tau2" / "domains" / "retail" / "tasks.json"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream tau2-bench checkout not found at {root}",
            # Every test in this module needs the checkout, so skipping the
            # module is the intent. Without this flag pytest treats a
            # module-level skip as an error and the whole file fails to
            # collect -- which is what CI hit, since CI has no checkout.
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()

try:
    BRIDGE_PYTHON = discover_bridge_python(upstream_root=UPSTREAM_ROOT)
except Tau2BridgeUnavailableError as error:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = str(error)
else:
    _BRIDGE_SKIP_REASON = ""


def _bridge() -> Tau2Bridge:
    if BRIDGE_PYTHON is None:
        pytest.skip(_BRIDGE_SKIP_REASON or "bridge python unavailable")
    return Tau2Bridge(python_executable=BRIDGE_PYTHON, upstream_root=UPSTREAM_ROOT)


def _case(task_id: str = "73") -> CaseManifest:
    path = Path("cases/tau3_retail/base") / f"tau3.retail.base.{task_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_tau3_retail_replay_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_tau3_retail_replay",
        suite_version="0.1.0",
        block_id="block_tau3_retail_replay",
        sampling_plan_id="sampling_tau3_retail_replay",
        analysis_plan_id="analysis_tau3_retail_replay",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_tau3_retail_replay_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(
            {"assistant": "scripted_assistant", "user": "scripted_user"}
        ),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


RETURN_ARGUMENTS = {
    "item_ids": ["7228247242", "2698416822", "8098621301", "3320557165"],
    "order_id": "#W5272531",
    "payment_method_id": "credit_card_6824399",
}

_SCRIPT = [
    (
        "user_turn",
        {"content": "Please return the four non-coffee items from order #W5272531."},
    ),
    (
        "assistant_turn",
        {
            "messages": [
                {
                    "tool_calls": [
                        {
                            "id": "call_get_order",
                            "name": "get_order_details",
                            "arguments": {"order_id": "#W5272531"},
                        }
                    ]
                },
                {
                    "tool_calls": [
                        {
                            "id": "call_return_items",
                            "name": "return_delivered_order_items",
                            "arguments": RETURN_ARGUMENTS,
                        }
                    ]
                },
                {"content": "The four non-coffee items have been returned."},
            ]
        },
    ),
    ("user_turn", {"content": "###STOP###"}),
]


def _run_live(bridge: Tau2Bridge, tmp_path: Path, *, suffix: str):
    case = _case("73")
    cell = _cell(case, suffix=suffix)
    plugin = Tau3RetailPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())

    raw_db = json.loads(
        (UPSTREAM_ROOT / "data" / "tau2" / "domains" / "retail" / "db.json").read_text(
            encoding="utf-8"
        )
    )
    initial_db = bridge.normalize_db(raw_db)
    evidence = EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_tau3_retail_replay_{suffix}",
        cell_id=cell.cell_id,
        episode_id=f"episode_tau3_retail_replay_{suffix}",
        episode_attempt_id="attempt_1",
    )
    scripted = ScriptedTau3RetailHarness(
        bridge=bridge, initial_db=initial_db, evidence=evidence, script=_SCRIPT
    )
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=scripted)
    )
    return case, cell, resolved_plugin, result


# ---------------------------------------------------------------------------
# Pure, no bridge: RecordedDecision/RecordedEpisode structural round-tripping.
# ---------------------------------------------------------------------------


def test_recorded_episode_round_trips_through_plain_json() -> None:
    decision = RecordedDecision(
        phase_id="user_turn", seat_id="user", response={"content": "hello", "n": (1, 2)}
    )
    episode = RecordedEpisode(case_id="tau3.retail.base.73", decisions=(decision,))

    text = episode.to_json()
    restored = RecordedEpisode.from_json(text)

    assert restored.case_id == episode.case_id
    assert len(restored.decisions) == 1
    assert restored.decisions[0].phase_id == "user_turn"
    assert restored.decisions[0].seat_id == "user"
    # Tuple/list distinctions collapse to JSON arrays through the round trip.
    assert restored.decisions[0].response == {"content": "hello", "n": [1, 2]}


def test_recorded_response_source_enforces_ordering_and_reports_exhaustion() -> None:
    decisions = (
        RecordedDecision(phase_id="user_turn", seat_id="user", response={"content": "hi"}),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "user_turn"
        seat_id = "user"

    response = asyncio.run(source(_Request()))
    assert response == {"content": "hi"}
    assert source.exhausted is True

    with pytest.raises(ReplayError, match="exhausted"):
        asyncio.run(source(_Request()))


def test_recorded_response_source_rejects_phase_seat_mismatch() -> None:
    decisions = (
        RecordedDecision(
            phase_id="assistant_turn", seat_id="assistant", response={"messages": []}
        ),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "user_turn"
        seat_id = "user"

    with pytest.raises(ReplayError, match="does not match"):
        asyncio.run(source(_Request()))


def test_compare_episode_results_reports_specific_mismatches_not_one_boolean() -> None:
    """A synthetic mismatch (mutated terminal) must be visible per-component."""

    class _Fake:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    original = _Fake(
        phase_instances=(),
        terminal={"reason": "user_stop"},
        outcome={"final_db_sha256": "a" * 64},
        final_state={"db_hash": "a" * 64, "messages": ()},
    )
    replayed = _Fake(
        phase_instances=(),
        terminal={"reason": "max_steps"},
        outcome={"final_db_sha256": "a" * 64},
        final_state={"db_hash": "a" * 64, "messages": ()},
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


def test_replay_from_a_json_round_tripped_record_reproduces_the_live_run(
    tmp_path: Path,
) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, original = _run_live(bridge, tmp_path, suffix="live")

    recorded = record_episode(original)
    # Force a genuine round trip through plain JSON text -- proves replay
    # never depends on reusing the original run's in-memory Python objects.
    recorded = RecordedEpisode.from_json(recorded.to_json())
    assert recorded.case_id == case.case_id

    # A second, independent Tau2Bridge/plugin -- not the one that produced
    # the original run -- drives the replay.
    replay_bridge = Tau2Bridge(python_executable=BRIDGE_PYTHON, upstream_root=UPSTREAM_ROOT)
    replay_plugin = Tau3RetailPlugin(upstream_root=UPSTREAM_ROOT, bridge=replay_bridge)
    registry = PluginRegistry()
    register_plugin(registry, plugin=replay_plugin)
    resolved_replay_plugin = registry.resolve_manifest(family_manifest())

    replayed = asyncio.run(
        replay_episode(
            cell=cell, case=case, plugin=resolved_replay_plugin, recorded=recorded
        )
    )

    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is True
    assert comparison.final_state_content_matches is True
    assert comparison.original_final_db_sha256 == comparison.replayed_final_db_sha256
    assert replayed.terminal["reason"] == "user_stop"

    # Known, general (not task-specific) property of Tau3RetailPlugin.step():
    # every message it appends is re-timestamped through a fresh upstream
    # model_validate call, so the RAW, byte-exact state never matches itself
    # across two independent runs of one trajectory -- only its *content*
    # does. Documented on replay._strip_message_timestamps; pinned here so
    # this doesn't silently regress into a false "everything matches" claim.
    assert comparison.final_state_matches is False
    assert canonical_json_bytes(replayed.final_state) != canonical_json_bytes(
        original.final_state
    )


def test_replayed_episode_recomputes_leaf_1_by_delegating_to_upstream(
    tmp_path: Path,
) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, original = _run_live(bridge, tmp_path, suffix="score")
    recorded = record_episode(original)

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=resolved_plugin, recorded=recorded)
    )
    task_path = Path("cases/tau3_retail/base") / "tau3.retail.base.73.json"
    payload = json.loads(task_path.read_text(encoding="utf-8"))["payload"]
    scorer = resolved_plugin.build_scorer(payload)

    scores = score_replayed_episode(bridge=bridge, scorer=scorer, replayed=replayed)

    assert scores.db_state.primary.value == 1.0
    assert scores.nl_assertions is None  # task 73 declares no judge leaf


def test_replay_and_verify_end_to_end_returns_a_matching_report(tmp_path: Path) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, original = _run_live(bridge, tmp_path, suffix="e2e")
    recorded = record_episode(original)
    task_path = Path("cases/tau3_retail/base") / "tau3.retail.base.73.json"
    payload = json.loads(task_path.read_text(encoding="utf-8"))["payload"]
    scorer = resolved_plugin.build_scorer(payload)

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            plugin=resolved_plugin,
            bridge=bridge,
            scorer=scorer,
            recorded=recorded,
            original=original,
        )
    )

    assert report.status == "match"
    assert report.scores.db_state.primary.value == 1.0
    assert report.final_db_sha256 == original.terminal["db_hash"]


def test_replay_raises_when_a_recorded_tool_result_is_tampered_with(tmp_path: Path) -> None:
    """The tool-level replay guarantee: step() itself catches this, and
    replay_episode must not swallow it."""
    bridge = _bridge()
    case, cell, resolved_plugin, original = _run_live(bridge, tmp_path, suffix="tamper")
    recorded = record_episode(original)

    tampered_decisions = list(recorded.decisions)
    for index, decision in enumerate(tampered_decisions):
        if decision.phase_id == "assistant_turn":
            response = dict(decision.response)
            executions = [dict(item) for item in response["tool_executions"]]
            executions[0] = dict(executions[0])
            executions[0]["result"] = dict(executions[0]["result"])
            executions[0]["result"]["content"] = "tampered content"
            response["tool_executions"] = executions
            tampered_decisions[index] = RecordedDecision(
                phase_id=decision.phase_id, seat_id=decision.seat_id, response=response
            )
            break
    tampered = RecordedEpisode(case_id=recorded.case_id, decisions=tuple(tampered_decisions))

    with pytest.raises(SchedulerContractError, match="tool replay result differs"):
        asyncio.run(
            replay_episode(cell=cell, case=case, plugin=resolved_plugin, recorded=tampered)
        )


def test_replay_case_mismatch_raises_a_typed_replay_error(tmp_path: Path) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, original = _run_live(bridge, tmp_path, suffix="mismatch")
    recorded = record_episode(original)
    wrong_case = RecordedEpisode(case_id="tau3.retail.base.999", decisions=recorded.decisions)

    with pytest.raises(ReplayError, match="not"):
        asyncio.run(
            replay_episode(cell=cell, case=case, plugin=resolved_plugin, recorded=wrong_case)
        )
