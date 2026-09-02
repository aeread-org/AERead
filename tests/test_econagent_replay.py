"""Tests for the econagent_v1 offline replayer (replay.py, spec section 5,
milestone 3).

See ``replay.py``'s own module docstring for why this family's replay seam
is the *bridge* (``EconAgentBridge``), not the scheduler's ``ResponseSource``
the way ``tau3_retail/replay.py`` replays tool calls -- every ``agent_i``
seat submits the same acknowledgment every month regardless of observation
(spec milestone-1 correction 4), so there is no per-seat decision content to
record or replay at the response-source layer at all.

Follows the same ``_require_bridge()``/skip convention as every other
econagent test file: pure, bridge-free structural tests run everywhere;
tests that actually record and replay a real bridge-driven episode run for
real when a provisioned bridge interpreter is available, and are skipped
(never faked) otherwise.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread_families.econagent_v1 import econagent_bridge as econagent_bridge_module
from aeread_families.econagent_v1.econagent_bridge import (
    EconAgentBridgeUnavailableError,
    discover_bridge_python,
)
from aeread_families.econagent_v1.environment import EconAgentV1Plugin, register_plugin
from aeread_families.econagent_v1.replay import (
    RecordedBridgeCall,
    RecordedEconAgentBridge,
    RecordedEconAgentEpisode,
    ReplayError,
    assert_replay_matches,
    compare_episode_results,
    replay_and_verify,
    replay_episode,
    run_and_record_episode,
    score_replayed_episode,
    score_tax_bracket_arithmetic_and_record,
)


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_ECONAGENT_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-econagent",
    )
    root = Path(candidate)
    if not (root / "config.yaml").is_file():
        pytest.skip(
            f"pinned upstream EconAgent checkout not found at {root}",
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()

try:
    BRIDGE_PYTHON = discover_bridge_python(upstream_root=UPSTREAM_ROOT)
except EconAgentBridgeUnavailableError as error:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = str(error)
else:
    _BRIDGE_SKIP_REASON = ""


def _require_bridge() -> None:
    if BRIDGE_PYTHON is None:
        pytest.skip(_BRIDGE_SKIP_REASON or "bridge python unavailable")


def _case(case_id: str = "econagent.pilot.tiny4x6.seed0") -> CaseManifest:
    path = Path("cases/econagent_v1") / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    n_agents = case.payload["scenario"]["n_agents"]
    profile_by_seat = {
        f"agent_{index}": "econagent_v1_scripted_complex" for index in range(n_agents)
    }
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_econagent_replay_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_econagent_replay",
        suite_version="0.1.0",
        block_id="block_econagent_replay",
        sampling_plan_id="sampling_econagent_replay",
        analysis_plan_id="analysis_econagent_replay",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_econagent_replay_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(profile_by_seat),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _run_live(*, suffix: str):
    _require_bridge()
    case = _case("econagent.pilot.tiny4x6.seed0")
    cell = _cell(case, suffix=suffix)
    result, recorded = asyncio.run(
        run_and_record_episode(cell=cell, case=case, upstream_root=UPSTREAM_ROOT)
    )
    return case, cell, result, recorded


def _scorer_for(case: CaseManifest):
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    family_case = plugin.validate_payload(case.payload)
    return plugin.build_scorer(family_case)


# ---------------------------------------------------------------------------
# Pure, no bridge: RecordedBridgeCall/RecordedEconAgentEpisode round-tripping
# and RecordedEconAgentBridge's ordering/exhaustion contract.
# ---------------------------------------------------------------------------


def test_recorded_bridge_call_round_trips_through_plain_dict() -> None:
    call = RecordedBridgeCall(
        method="recompute_tax",
        args={"incomes": {"0": 1000.0, "1": (2000.0,)}},
        response={"results": {"0": {"tax_due": 1.0}}},
    )
    restored = RecordedBridgeCall.from_dict(call.to_dict())
    assert restored.method == "recompute_tax"
    # Tuple/list distinctions collapse to JSON arrays through the round trip.
    assert restored.args == {"incomes": {"0": 1000.0, "1": [2000.0]}}
    assert restored.response == {"results": {"0": {"tax_due": 1.0}}}


def test_recorded_econagent_episode_round_trips_through_plain_json() -> None:
    calls = (
        RecordedBridgeCall(method="start_episode", args={"n_agents": 4}, response={"ok": True}),
        RecordedBridgeCall(method="step_month", args={}, response={"timestep": 1}),
    )
    episode = RecordedEconAgentEpisode(
        case_id="econagent.pilot.tiny4x6.seed0", session_calls=calls
    )
    text = episode.to_json()
    restored = RecordedEconAgentEpisode.from_json(text)

    assert restored.case_id == episode.case_id
    assert len(restored.session_calls) == 2
    assert restored.session_calls[0].method == "start_episode"
    assert restored.session_calls[1].response == {"timestep": 1}


def test_recorded_bridge_enforces_call_order_and_reports_exhaustion() -> None:
    calls = (
        RecordedBridgeCall(method="start_episode", args={}, response={"ok": True}),
        RecordedBridgeCall(method="step_month", args={}, response={"timestep": 1, "done": False}),
    )
    bridge = RecordedEconAgentBridge(calls)

    assert bridge.start_episode(n_agents=4, episode_length=1, world_seed=0) == {"ok": True}
    assert bridge.exhausted is False
    assert bridge.step_month() == {"timestep": 1, "done": False}
    assert bridge.exhausted is True

    with pytest.raises(ReplayError, match="exhausted"):
        bridge.agent_snapshot()


def test_recorded_bridge_rejects_a_method_order_mismatch() -> None:
    calls = (RecordedBridgeCall(method="step_month", args={}, response={"timestep": 1}),)
    bridge = RecordedEconAgentBridge(calls)

    with pytest.raises(ReplayError, match="does not match"):
        bridge.agent_snapshot()


def test_recorded_bridge_rejects_a_recompute_tax_income_mismatch() -> None:
    """Regression guard: unlike every other replayed method, `recompute_tax`
    must not serve its recorded response purely by call order -- the
    replayed `incomes` argument (re-derived from the replayed episode's own
    dense_log) has to equal what the original live scoring call actually
    recorded, or a dense_log/income divergence introduced elsewhere could
    silently reuse a stale recorded `tax_due` against different incomes."""
    calls = (
        RecordedBridgeCall(
            method="recompute_tax",
            args={"incomes": {"0": 1000.0}},
            response={"0": {"tax_due": 1.0}},
        ),
    )
    bridge = RecordedEconAgentBridge(calls)

    with pytest.raises(ReplayError, match="arguments do not match"):
        bridge.recompute_tax({"0": 2000.0})


def test_recorded_bridge_serves_recompute_tax_when_incomes_match() -> None:
    calls = (
        RecordedBridgeCall(
            method="recompute_tax",
            args={"incomes": {"0": 1000.0}},
            response={"0": {"tax_due": 1.0}},
        ),
    )
    bridge = RecordedEconAgentBridge(calls)

    assert bridge.recompute_tax({"0": 1000.0}) == {"0": {"tax_due": 1.0}}
    assert bridge.exhausted is True


def test_compare_episode_results_reports_specific_mismatches_not_one_boolean() -> None:
    """A synthetic mismatch (mutated terminal) must be visible per-component."""

    class _Fake:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    original = _Fake(
        phase_instances=(),
        terminal={"reason": "episode_length_reached", "timestep": 6},
        outcome={"termination_reason": "episode_length_reached"},
        final_state={"timestep": 6},
    )
    replayed = _Fake(
        phase_instances=(),
        terminal={"reason": "episode_length_reached", "timestep": 5},
        outcome={"termination_reason": "episode_length_reached"},
        final_state={"timestep": 6},
    )

    comparison = compare_episode_results(original, replayed)

    assert comparison.terminal_matches is False
    assert comparison.outcome_matches is True
    assert comparison.final_state_matches is True
    assert comparison.matches is False
    with pytest.raises(ReplayError, match="terminal record differs"):
        assert_replay_matches(comparison)


# ---------------------------------------------------------------------------
# Bridge-gated: record a real live episode, replay it with the bridge
# subprocess disabled entirely, and cross-check.
# ---------------------------------------------------------------------------


def test_recorded_episode_captures_the_expected_bridge_call_sequence() -> None:
    """4 agents x 6 months: start_episode, agent_snapshot, then
    (step_month, agent_snapshot) x 6, then dense_log, close."""
    _require_bridge()
    _case_obj, _cell_obj, _result, recorded = _run_live(suffix="sequence")

    methods = [call.method for call in recorded.session_calls]
    assert methods == (
        ["start_episode", "agent_snapshot"]
        + ["step_month", "agent_snapshot"] * 6
        + ["dense_log", "close"]
    )


def test_replay_from_a_json_round_tripped_record_reproduces_the_live_run() -> None:
    case, cell, original, recorded = _run_live(suffix="live")

    # Force a genuine round trip through plain JSON text -- proves replay
    # never depends on reusing the original run's in-memory Python objects.
    recorded = RecordedEconAgentEpisode.from_json(recorded.to_json())
    assert recorded.case_id == case.case_id

    # Patch EconAgentBridge._spawn out from under the bridge module for the
    # duration of the replay -- if replay_episode ever tried to spawn the
    # real upstream bridge subprocess (rather than serving from the
    # recorded call log), this would raise immediately. Narrower than
    # patching `subprocess.Popen` globally, which would also break
    # `EconAgentV1Plugin.validate_payload`'s own unrelated `git`
    # subprocess.run calls (git itself is spawned through Popen
    # internally). This is the literal proof behind spec section 5's "the
    # bridge process disabled entirely".
    def _must_not_spawn(_self: Any) -> Any:
        raise AssertionError("replay must never spawn the real bridge subprocess")

    original_spawn = econagent_bridge_module.EconAgentBridge._spawn
    econagent_bridge_module.EconAgentBridge._spawn = _must_not_spawn  # type: ignore[assignment]
    try:
        replayed = asyncio.run(
            replay_episode(
                cell=cell, case=case, upstream_root=UPSTREAM_ROOT, recorded=recorded
            )
        )
    finally:
        econagent_bridge_module.EconAgentBridge._spawn = original_spawn

    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is True
    assert comparison.final_state_content_matches is True
    assert comparison.terminal_matches is True
    assert comparison.outcome_matches is True
    assert replayed.terminal["reason"] == "episode_length_reached"

    # Known, general (not task-specific) property of
    # `EconAgentV1Plugin.initial_state`: it mints a fresh `uuid.uuid4().hex`
    # bookkeeping key (`bridge_session_id`) on every call, so the RAW,
    # byte-exact state never matches itself across two independent runs of
    # one trajectory -- only its *content* does. Documented on
    # `replay._strip_bridge_session_id`; pinned here so this doesn't
    # silently regress into a false "everything matches" claim.
    assert comparison.final_state_matches is False
    assert canonical_json_bytes(replayed.final_state) != canonical_json_bytes(
        original.final_state
    )


def test_replay_recomputes_all_three_leaves_with_zero_live_calls() -> None:
    _require_bridge()
    case, cell, original, recorded = _run_live(suffix="score")
    scorer = _scorer_for(case)

    original_dense_log = original.terminal["dense_log"]
    original_n_agents = original.terminal["n_agents"]
    original_month_actions = original.terminal["month_actions"]
    original_world_period = original.terminal["final_world"]["period"]
    original_budget = scorer.score_budget_identity(
        dense_log=original_dense_log,
        n_agents=original_n_agents,
        world_period=original_world_period,
        month_actions=original_month_actions,
    )
    original_macro = scorer.score_macro_trajectory(
        dense_log=original_dense_log,
        n_agents=original_n_agents,
        month_actions=original_month_actions,
    )
    original_tax, tax_calls = score_tax_bracket_arithmetic_and_record(
        scorer,
        dense_log=original_dense_log,
        n_agents=original_n_agents,
        upstream_root=UPSTREAM_ROOT,
    )
    assert original_budget.primary.value == 1.0
    assert original_tax.primary.value == 1.0

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, upstream_root=UPSTREAM_ROOT, recorded=recorded)
    )
    scores = score_replayed_episode(
        scorer=scorer, replayed=replayed, tax_recompute_calls=tax_calls
    )

    assert scores.budget_identity == original_budget
    assert scores.tax_bracket_arithmetic == original_tax
    assert scores.macro_trajectory == original_macro


def test_replay_leaf2_detects_a_recorded_recompute_tax_income_mismatch() -> None:
    """Mutation check for the "recompute_tax replays by call order alone"
    gap: a `RecordedEconAgentBridge` double served purely by call order
    would silently reuse a stale recorded `tax_due` against incomes that no
    longer match what generated it. Tampering one recorded
    `recompute_tax` call's own `args["incomes"]` (never its response, and
    never call order/count) must be caught -- proving leaf 2's replay path
    actually checks its own recorded inputs, not just their sequence."""
    _require_bridge()
    case, cell, original, recorded = _run_live(suffix="tax-income-mismatch")
    scorer = _scorer_for(case)
    dense_log = original.terminal["dense_log"]
    n_agents = original.terminal["n_agents"]
    _tax_score, tax_calls = score_tax_bracket_arithmetic_and_record(
        scorer, dense_log=dense_log, n_agents=n_agents, upstream_root=UPSTREAM_ROOT
    )

    tampered_tax_calls = list(tax_calls)
    first_call = tampered_tax_calls[0]
    tampered_incomes = dict(first_call.args["incomes"])
    some_agent = next(iter(tampered_incomes))
    tampered_incomes[some_agent] = tampered_incomes[some_agent] + 1234.0
    tampered_tax_calls[0] = RecordedBridgeCall(
        method=first_call.method,
        args={"incomes": tampered_incomes},
        response=first_call.response,
    )

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, upstream_root=UPSTREAM_ROOT, recorded=recorded)
    )
    with pytest.raises(ReplayError, match="arguments do not match"):
        score_replayed_episode(
            scorer=scorer, replayed=replayed, tax_recompute_calls=tuple(tampered_tax_calls)
        )


def test_replay_and_verify_end_to_end_returns_a_matching_report() -> None:
    _require_bridge()
    case, cell, original, recorded = _run_live(suffix="e2e")
    scorer = _scorer_for(case)
    dense_log = original.terminal["dense_log"]
    n_agents = original.terminal["n_agents"]
    _tax_score, tax_calls = score_tax_bracket_arithmetic_and_record(
        scorer, dense_log=dense_log, n_agents=n_agents, upstream_root=UPSTREAM_ROOT
    )

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            upstream_root=UPSTREAM_ROOT,
            scorer=scorer,
            recorded=recorded,
            tax_recompute_calls=tax_calls,
            original=original,
        )
    )

    assert report.status == "match"
    assert report.scores.budget_identity.primary.value == 1.0
    assert report.scores.tax_bracket_arithmetic.primary.value == 1.0


def test_replay_diverges_when_a_recorded_bridge_response_is_tampered_with() -> None:
    """Mutation check: `compare_episode_results` must genuinely detect
    divergence, not just agreement -- guards against it being vacuously true."""
    _require_bridge()
    case, cell, original, recorded = _run_live(suffix="tamper")

    tampered_calls = list(recorded.session_calls)
    for index, call in enumerate(tampered_calls):
        if call.method == "step_month":
            response = copy.deepcopy(call.response)
            response["actions"]["0"] = [999.0, 999.0]  # out-of-range, invented
            tampered_calls[index] = RecordedBridgeCall(
                method=call.method, args=call.args, response=response
            )
            break
    tampered = RecordedEconAgentEpisode(
        case_id=recorded.case_id, session_calls=tuple(tampered_calls)
    )

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, upstream_root=UPSTREAM_ROOT, recorded=tampered)
    )
    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is False
    with pytest.raises(ReplayError, match="differs"):
        assert_replay_matches(comparison)


def test_replay_case_mismatch_raises_a_typed_replay_error() -> None:
    _require_bridge()
    case, cell, _original, recorded = _run_live(suffix="mismatch")
    wrong_case = RecordedEconAgentEpisode(
        case_id="econagent.pilot.small10x12.seed0", session_calls=recorded.session_calls
    )

    with pytest.raises(ReplayError, match="not"):
        asyncio.run(
            replay_episode(
                cell=cell, case=case, upstream_root=UPSTREAM_ROOT, recorded=wrong_case
            )
        )


def test_replay_raises_when_the_recorded_session_has_an_unconsumed_tail() -> None:
    """A recorded call the replayed run never actually asks for must trip
    the post-episode exhaustion check -- guards against that check being
    vacuously satisfied. (Dropping the final ``close`` entry instead would
    NOT reproduce this: ``RecordedEconAgentBridge.close()`` deliberately
    tolerates a missing recorded ``close``, mirroring
    ``EconAgentBridge.close()``'s own "safe to call more than once, and
    safe to call when no episode was ever started" contract.)"""
    _require_bridge()
    case, cell, _original, recorded = _run_live(suffix="padded")
    extra_call = recorded.session_calls[1]  # a genuine "agent_snapshot" entry
    padded = RecordedEconAgentEpisode(
        case_id=recorded.case_id, session_calls=recorded.session_calls + (extra_call,)
    )

    with pytest.raises(ReplayError, match="before every recorded bridge call was consumed"):
        asyncio.run(
            replay_episode(
                cell=cell, case=case, upstream_root=UPSTREAM_ROOT, recorded=padded
            )
        )
