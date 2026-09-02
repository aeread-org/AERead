"""Provider-free scheduler coverage for the termsbench environment plugin.

Covers docs/termsbench_adapter_spec.md section 5's environment test plan:
phase graph under both opener orders, all 5 App. B.3 termination cases plus
the adapter-defined AgreementViolation case, and constraint checks mapping to
the right critical/secondary violation component. The scorer (leaves 1-4) is
a separate milestone; nothing here depends on it.
"""
from __future__ import annotations

import asyncio
from types import MappingProxyType

import pytest

from aeread.shared_runner.registry import REQUIRED_FAMILY_PLUGIN_HOOKS, PluginRegistry
from aeread.shared_runner.resolver import PlanCell
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import SchedulerContractError, run_episode
from aeread_families.termsbench import cases as tb_cases
from aeread_families.termsbench.environment import (
    AGENT_PHASE,
    COUNTERPART_PHASE,
    TermsBenchPlugin,
    family_manifest,
    register_plugin,
)
from aeread_families.termsbench.harness import ScriptedTermsBenchHarness


def _case(family: str, regime: str, world_seed: int) -> CaseManifest:
    return CaseManifest.from_dict(tb_cases.build_case(family, regime, world_seed))


def _cell(case: CaseManifest) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id="cell_termsbench_environment",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_termsbench_environment",
        suite_version="0.1.0",
        block_id="block_termsbench_environment",
        sampling_plan_id="sampling_termsbench_environment",
        analysis_plan_id="analysis_termsbench_environment",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id="cluster_termsbench_environment",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(
            {"agent": "scripted_agent", "counterpart": "termsbench_counterpart_kernel_v1"}
        ),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _seed_with_chi(family: str, regime: str, chi: str, start: int = 1000000) -> int:
    seed = start
    while tb_cases.generate_payload(family, regime, seed)["chi"] != chi:
        seed += 1
    return seed


def _run(case: CaseManifest, harness: ScriptedTermsBenchHarness):
    registry = PluginRegistry()
    plugin = register_plugin(registry)
    return asyncio.run(run_episode(cell=_cell(case), case=case, plugin=plugin, response_source=harness))


# ---------------------------------------------------------------------------
# Registration and phase graph.
# ---------------------------------------------------------------------------


def test_plugin_registers_every_required_hook_through_normal_registry() -> None:
    registry = PluginRegistry()
    plugin = register_plugin(registry)
    resolved = registry.resolve_manifest(family_manifest())
    assert resolved is plugin
    for hook in REQUIRED_FAMILY_PLUGIN_HOOKS:
        assert callable(getattr(plugin, hook))


def test_phase_graph_starts_with_agent_turn_when_agent_opens() -> None:
    seed = _seed_with_chi("candid", "overlap", "agent_opens")
    case = _case("candid", "overlap", seed)
    plugin = TermsBenchPlugin()
    family_case = plugin.validate_payload(case.payload)
    phases = plugin.phases(family_case)
    assert phases[0].phase_id == AGENT_PHASE
    assert phases[1].phase_id == COUNTERPART_PHASE
    assert phases[0].next_phases == (COUNTERPART_PHASE,)
    assert phases[1].next_phases == (AGENT_PHASE,)


def test_phase_graph_starts_with_counterpart_turn_when_counterpart_opens() -> None:
    seed = _seed_with_chi("candid", "overlap", "counterpart_opens")
    case = _case("candid", "overlap", seed)
    plugin = TermsBenchPlugin()
    family_case = plugin.validate_payload(case.payload)
    phases = plugin.phases(family_case)
    assert phases[0].phase_id == COUNTERPART_PHASE
    assert phases[1].phase_id == AGENT_PHASE


# ---------------------------------------------------------------------------
# App. B.3 termination cases (5) plus the adapter-defined AgreementViolation.
# ---------------------------------------------------------------------------


def test_case1_counterpart_accepts_the_agents_offer() -> None:
    seed = _seed_with_chi("candid", "overlap", "agent_opens")
    case = _case("candid", "overlap", seed)
    r_a = case.payload["agent"]["r_a"]
    script = [{"decision": "offer", "price": r_a - 40.0, "message": "opening"}]
    harness = ScriptedTermsBenchHarness(
        world_seed=case.world_seed, script=script, counterpart_draws_by_round={1: {"u_accept": 0.0}}
    )
    result = _run(case, harness)
    assert result.terminal["reason"] == "counterpart_accept"
    assert result.terminal["final_price"] == pytest.approx(r_a - 40.0)


def test_case2_agent_accepts_the_counterparts_opening_offer() -> None:
    seed = _seed_with_chi("candid", "overlap", "counterpart_opens")
    case = _case("candid", "overlap", seed)
    harness = ScriptedTermsBenchHarness(
        world_seed=case.world_seed, script=[{"decision": "accept", "price": None, "message": "deal"}]
    )
    result = _run(case, harness)
    assert result.terminal["reason"] == "agent_accept"
    assert result.terminal["final_price"] is not None


def test_case2_agent_reject_terminates_with_disagreement() -> None:
    seed = _seed_with_chi("candid", "overlap", "counterpart_opens")
    case = _case("candid", "overlap", seed)
    harness = ScriptedTermsBenchHarness(
        world_seed=case.world_seed, script=[{"decision": "reject", "price": None, "message": "no deal"}]
    )
    result = _run(case, harness)
    assert result.terminal["reason"] == "agent_reject"
    assert result.terminal["final_price"] is None


def test_case4_counterpart_walk_away_terminates_with_disagreement() -> None:
    seed = _seed_with_chi("candid", "overlap", "agent_opens")
    case = _case("candid", "overlap", seed)
    r_b = case.payload["t_b"]["r_b"]
    # Buyer offering far below the seller counterpart's reservation is not
    # individually rational for the counterpart (delta_bar < 0); combined
    # with a forced walk-away draw at/after k_walk=5, this reaches case 4.
    lowball = max(0.0, r_b - 90.0)
    script = [{"decision": "offer", "price": lowball, "message": "lowball"}] * 6
    draws = {rk: {"u_accept": 0.999, "u_walkaway": 0.0} for rk in range(1, 7)}
    harness = ScriptedTermsBenchHarness(world_seed=case.world_seed, script=script, counterpart_draws_by_round=draws)
    result = _run(case, harness)
    assert result.terminal["reason"] == "counterpart_walk_away"
    assert result.terminal["final_price"] is None


def test_case5_round_limit_reached_without_agreement_is_timeout() -> None:
    seed = _seed_with_chi("candid", "overlap", "counterpart_opens")
    case = _case("candid", "overlap", seed)
    r_a = case.payload["agent"]["r_a"]
    horizon = case.payload["horizon"]
    script = [{"decision": "offer", "price": r_a * 0.5, "message": "x"}] * (horizon + 2)
    draws = {rk: {"u_accept": 0.999, "u_walkaway": 0.999} for rk in range(1, horizon + 2)}
    harness = ScriptedTermsBenchHarness(world_seed=case.world_seed, script=script, counterpart_draws_by_round=draws)
    result = _run(case, harness)
    assert result.terminal["reason"] == "timeout"
    assert result.terminal["final_price"] is None
    assert result.terminal["rounds_used"] == horizon + 1


def test_golden3_accept_without_counterpart_offer_is_agreement_violation() -> None:
    seed = _seed_with_chi("candid", "overlap", "agent_opens")
    case = _case("candid", "overlap", seed)
    harness = ScriptedTermsBenchHarness(
        world_seed=case.world_seed, script=[{"decision": "accept", "price": None, "message": "premature"}]
    )
    result = _run(case, harness)
    assert result.terminal["reason"] == "agreement_violation"
    assert result.terminal["final_price"] is None
    assert result.terminal["critical_violations"]["invalid_action"] is True
    assert result.terminal["malformed_action_schema"] is False
    # Golden 3's own invariant (spec section 4): no protected state (price,
    # DB) is touched on the illegal-Accept path.
    assert result.final_state["round"] == 1
    assert result.final_state["agent_offers"] == ()
    assert result.final_state["counterpart_offers"] == ()
    assert result.final_state["transcript"] == ()


def test_golden4_malformed_action_is_agreement_violation_and_flagged_malformed() -> None:
    seed = _seed_with_chi("candid", "overlap", "agent_opens")
    case = _case("candid", "overlap", seed)
    harness = ScriptedTermsBenchHarness(world_seed=case.world_seed, script=[{"nonsense": True}])
    result = _run(case, harness)
    assert result.terminal["reason"] == "agreement_violation"
    assert result.terminal["malformed_action_schema"] is True
    assert result.terminal["critical_violations"]["invalid_action"] is True


# ---------------------------------------------------------------------------
# Constraint checks map to the right critical/secondary violation component.
# ---------------------------------------------------------------------------


def test_price_bound_violation_is_flagged_but_does_not_terminate() -> None:
    seed = _seed_with_chi("candid", "overlap", "agent_opens")
    case = _case("candid", "overlap", seed)
    p_max = case.payload["price_bounds"]["p_max"]
    script = [{"decision": "offer", "price": p_max + 50.0, "message": "too high"}]
    harness = ScriptedTermsBenchHarness(
        world_seed=case.world_seed, script=script, counterpart_draws_by_round={1: {"u_accept": 0.999, "u_walkaway": 0.999}}
    )
    plugin = TermsBenchPlugin()
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, None)
    phase = plugin.phases(family_case)[0]

    class _Envelope:
        def __init__(self, action):
            self.action, self.valid, self.parse, self.legality = action, True, None, None

    action = plugin.parse_action(family_case, state, "agent", phase, script[0]).action
    transition = plugin.step(family_case, state, phase, {"agent": _Envelope(action)})
    assert transition.state["critical_violations"]["price_bound"] is True
    assert transition.state["termination"] is None  # logged, not terminal (B.3)


def test_monotonicity_violation_is_secondary_and_does_not_terminate() -> None:
    seed = _seed_with_chi("candid", "overlap", "agent_opens")
    case = _case("candid", "overlap", seed)
    r_a = case.payload["agent"]["r_a"]
    plugin = TermsBenchPlugin()
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, None)
    phase = plugin.phases(family_case)[0]

    class _Envelope:
        def __init__(self, action):
            self.action, self.valid, self.parse, self.legality = action, True, None, None

    first = plugin.parse_action(family_case, state, "agent", phase, {"decision": "offer", "price": r_a - 40.0, "message": "a"}).action
    t1 = plugin.step(family_case, state, phase, {"agent": _Envelope(first)})
    state2 = dict(t1.state)
    state2["termination"] = None  # re-enter agent_turn as if this were a fresh round

    second = plugin.parse_action(family_case, state2, "agent", phase, {"decision": "offer", "price": r_a - 45.0, "message": "b"}).action
    t2 = plugin.step(family_case, state2, phase, {"agent": _Envelope(second)})
    assert t2.state["secondary_violations"]["monotonicity"] is True
    assert t2.state["critical_violations"]["price_bound"] is False


# ---------------------------------------------------------------------------
# Replay-and-verify: step() must reject a counterpart response that does not
# match what kernel.resolve_counterpart_turn recomputes from the same draws.
# ---------------------------------------------------------------------------


def test_step_rejects_a_counterpart_response_that_lies_about_its_resolution() -> None:
    seed = _seed_with_chi("candid", "overlap", "agent_opens")
    case = _case("candid", "overlap", seed)

    class LyingHarness:
        async def __call__(self, request):
            if request.phase_id == "agent_turn":
                return {"decision": "offer", "price": case.payload["agent"]["r_a"] - 40.0, "message": "x"}
            # Claim an "accept" no matter what the sealed draws actually imply.
            return {
                "resolved": "accept",
                "price": case.payload["agent"]["r_a"] - 40.0,
                "sentiment_cue": "neutral",
                "strategic_cue": "Concede",
                "message": "lying",
                "round": request.observation["round"],
                "draws": {
                    "u_accept": 0.999999,
                    "u_walkaway": 0.999999,
                    "opening_noise": 0.0,
                    "sentiment_noise": 0.0,
                    "posture_u": 0.5,
                },
            }

    with pytest.raises(SchedulerContractError, match="replay mismatch"):
        _run(case, LyingHarness())
