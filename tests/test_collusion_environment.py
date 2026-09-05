"""Provider-free scheduler coverage for the collusion environment plugin.

This milestone builds the environment (spec section 3), not the scorer
(spec section 2): these tests exercise plugin registration, the phase
graph, price parsing/legality, the demand/profit transition, and the three
declared termination reasons a trajectory can reach -- never a
``MeasurementLeafSpec`` or a score.
"""
from __future__ import annotations

import asyncio
import copy
from types import MappingProxyType

import pytest

from aeread.shared_runner.registry import REQUIRED_FAMILY_PLUGIN_HOOKS, PluginRegistry
from aeread.shared_runner.run.resolver import PlanCell, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import SchedulerContractError, run_episode
from aeread_families.collusion import cases as collusion_cases
from aeread_families.collusion import economics
from aeread_families.collusion.environment import (
    PRICE_ROUND_PHASE,
    CollusionPlugin,
    family_manifest,
    register_plugin,
)

BASELINE_ALPHA1 = "collusion.duopoly.baseline-symmetric.alpha1.seed0"


def _case(*, horizon: int = 3) -> CaseManifest:
    """One real built case, optionally with a short horizon for fast tests."""
    raw = collusion_cases.build_case("baseline-symmetric", 1.0, 0)
    if horizon != raw["payload"]["horizon"]:
        raw = copy.deepcopy(raw)
        raw["payload"]["horizon"] = horizon
        raw["episode"]["max_logical_actions"] = horizon * collusion_cases.LOGICAL_ACTIONS_PER_ROUND
        raw["content_sha256"] = "0" * 64
        raw["content_sha256"] = case_content_sha256(raw)
    return CaseManifest.from_dict(raw)


def _cell(case: CaseManifest) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id="cell_collusion_environment",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_collusion_environment",
        suite_version="0.1.0",
        block_id="block_collusion_environment",
        sampling_plan_id="sampling_collusion_environment",
        analysis_plan_id="analysis_collusion_environment",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id="cluster_collusion_environment",
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


# ---------------------------------------------------------------------------
# Import-level / registration.
# ---------------------------------------------------------------------------


def test_plugin_registers_every_required_hook_through_normal_registry() -> None:
    registry = PluginRegistry()
    plugin = register_plugin(registry)
    for hook in REQUIRED_FAMILY_PLUGIN_HOOKS:
        assert callable(getattr(plugin, hook))
    resolved = registry.resolve("collusion", "0.1.0", "collusion_environment")
    assert resolved is plugin


def test_family_manifest_is_strict_and_internally_consistent() -> None:
    manifest = family_manifest()
    assert manifest.family.id == "collusion"
    assert manifest.family.version == "0.1.0"
    assert manifest.environment.phase_specs == (PRICE_ROUND_PHASE,)
    assert manifest.environment.needs_tools is False
    assert manifest.environment.needs_sandbox is False
    assert set(manifest.roles) == {"pricing_agent"}
    assert manifest.roles["pricing_agent"].testable is True


def test_registering_the_same_family_version_twice_is_refused() -> None:
    registry = PluginRegistry()
    register_plugin(registry)
    with pytest.raises(Exception):
        register_plugin(registry)


def test_build_scorer_returns_the_four_declared_leaves() -> None:
    # Milestone 2 (docs/collusion_adapter_spec.md section 2): build_scorer no
    # longer raises NotImplementedError -- see tests/test_collusion_measurement.py
    # for the scorer's own coverage; this only confirms the environment's hook
    # wires through to it.
    plugin = CollusionPlugin()
    case = _case()
    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)
    assert [leaf.leaf_id for leaf in scorer.leaves] == [
        "collusion_price_legality",
        "collusion_distance_to_nash_price",
        "collusion_distance_to_monopoly_price",
        "collusion_long_run_profit",
    ]


# ---------------------------------------------------------------------------
# validate_payload.
# ---------------------------------------------------------------------------


def test_validate_payload_accepts_every_built_case() -> None:
    plugin = CollusionPlugin()
    for case in collusion_cases.build_all_cases().values():
        family_case = plugin.validate_payload(case["payload"])
        assert family_case["cost_scale"] == case["payload"]["cost_scale"]


def test_validate_payload_rejects_unknown_fields() -> None:
    plugin = CollusionPlugin()
    case = _case()
    payload = dict(case.payload)
    payload["extra_field"] = 1
    with pytest.raises(ValueError, match="unexpected"):
        plugin.validate_payload(payload)


def test_validate_payload_accepts_ceiling_exactly_at_monopoly() -> None:
    # Closed interval, spec section 4's "degenerate reference" golden: k=1
    # makes ceiling == p_monopoly exactly, which is admissible (the same
    # "at-ceiling-is-legal" convention legal() enforces per round), not
    # rejected. See tests/test_collusion_measurement.py's degenerate-ceiling
    # golden for the full end-to-end exercise of this boundary.
    plugin = CollusionPlugin()
    case = _case()
    payload = dict(case.payload)
    payload["ceiling_k"] = 1.0
    family_case = plugin.validate_payload(payload)
    assert family_case["ceiling_k"] == 1.0


def test_validate_payload_rejects_ceiling_strictly_below_monopoly() -> None:
    plugin = CollusionPlugin()
    case = _case()
    payload = dict(case.payload)
    payload["ceiling_k"] = 0.999  # ceiling < p_monopoly: monopoly-play would be illegal.
    with pytest.raises(ValueError, match="ceiling"):
        plugin.validate_payload(payload)


# ---------------------------------------------------------------------------
# End-to-end trajectories through the real scheduler (no scorer involved).
# ---------------------------------------------------------------------------


def _constant_price_response(price: float):
    async def respond(request):
        return {"price": price}

    return respond


def test_legal_trajectory_computes_correct_quantities_and_profits_and_hits_max_periods() -> None:
    case = _case(horizon=3)
    p_monopoly = case.payload["gold_reference"]["p_monopoly"]["firm_a"]

    async def respond(request):
        return {"price": p_monopoly}

    result = asyncio.run(
        run_episode(
            cell=_cell(case), case=case, plugin=CollusionPlugin(), response_source=respond
        )
    )

    assert result.terminal["reason"] == "max_periods"
    assert result.outcome["termination_reason"] == "max_periods"
    assert result.outcome["rounds_played"] == 3
    history = result.outcome["history"]
    assert len(history) == 3
    demand_params = case.payload["demand_params"]
    expected_q, _ = economics.quantities(
        (p_monopoly, p_monopoly),
        tuple(demand_params["a"]),
        demand_params["a0"],
        demand_params["mu"],
        demand_params["beta"],
        case.payload["cost_scale"],
    )
    for round_index, entry in enumerate(history):
        assert entry["round"] == round_index
        assert entry["valid"] is True
        assert entry["prices"] == {"firm_a": p_monopoly, "firm_b": p_monopoly}
        assert entry["quantities"]["firm_a"] == pytest.approx(expected_q)
        assert entry["quantities"]["firm_a"] == entry["quantities"]["firm_b"]
        assert entry["profits"]["firm_a"] == entry["profits"]["firm_b"]


def test_simultaneous_phase_hides_peer_price_until_the_round_closes() -> None:
    case = _case(horizon=2)
    requests: list = []

    async def respond(request):
        requests.append(request)
        # Different prices per seat, so leaking one into the other's
        # observation before the round closes would be detectable.
        return {"price": 1.4 if request.seat_id == "firm_a" else 1.9}

    asyncio.run(
        run_episode(cell=_cell(case), case=case, plugin=CollusionPlugin(), response_source=respond)
    )
    assert [request.seat_id for request in requests] == ["firm_a", "firm_b", "firm_a", "firm_b"]

    round_0_firm_a, round_0_firm_b, round_1_firm_a, round_1_firm_b = requests
    # Both round-0 requests are frozen from the same empty pre-round state --
    # neither seat's about-to-be-submitted price is visible to the other.
    # (The scheduler freezes observations into tuples/mapping-proxies, hence
    # the tuple/dict comparison below rather than list literals.)
    assert round_0_firm_a.observation["price_history"] == ()
    assert round_0_firm_b.observation["price_history"] == ()
    # Only after the round closes does round 0's *public* price bundle
    # (both firms' prices) become visible to both seats -- own realized
    # quantity/profit stays private to each seat (spec "Governing facts").
    for request in (round_1_firm_a, round_1_firm_b):
        assert request.observation["price_history"] == (
            {"round": 0, "prices": {"firm_a": 1.4, "firm_b": 1.9}, "valid": True},
        )
        assert len(request.observation["own_history"]) == 1
    assert round_1_firm_a.observation["own_history"][0]["quantity"] != round_1_firm_b.observation[
        "own_history"
    ][0]["quantity"]


def test_legality_violation_terminates_gracefully_and_excludes_the_round() -> None:
    case = _case(horizon=5)
    p_monopoly = case.payload["gold_reference"]["p_monopoly"]["firm_a"]
    ceiling = case.payload["ceiling_k"] * p_monopoly
    over_ceiling = ceiling * 3  # exceeds the ceiling for every drawable k (spec golden 3).

    async def respond(request):
        if request.seat_id == "firm_a":
            return {"price": over_ceiling}
        return {"price": p_monopoly}

    result = asyncio.run(
        run_episode(cell=_cell(case), case=case, plugin=CollusionPlugin(), response_source=respond)
    )

    assert result.terminal["reason"] == "legality_violation"
    history = result.outcome["history"]
    assert len(history) == 1
    assert history[0]["valid"] is False
    assert history[0]["quantities"] is None
    assert history[0]["profits"] is None
    assert history[0]["invalid_reasons"] == {"firm_a": "price_out_of_bounds"}


def test_malformed_price_terminates_as_retry_exhausted_never_an_economic_zero() -> None:
    case = _case(horizon=5)
    p_monopoly = case.payload["gold_reference"]["p_monopoly"]["firm_a"]

    async def respond(request):
        if request.seat_id == "firm_b":
            return {"price": "not a number"}
        return {"price": p_monopoly}

    result = asyncio.run(
        run_episode(cell=_cell(case), case=case, plugin=CollusionPlugin(), response_source=respond)
    )

    assert result.terminal["reason"] == "retry_exhausted"
    history = result.outcome["history"]
    assert len(history) == 1
    assert history[0]["valid"] is False
    assert history[0]["profits"] is None
    assert history[0]["invalid_reasons"] == {"firm_b": "malformed_price"}


def test_price_parsed_from_free_form_prose_takes_the_last_number() -> None:
    case = _case(horizon=1)
    p_monopoly = case.payload["gold_reference"]["p_monopoly"]["firm_a"]

    async def respond(request):
        return f"I will reason about this for a while. My final price is {p_monopoly}."

    result = asyncio.run(
        run_episode(cell=_cell(case), case=case, plugin=CollusionPlugin(), response_source=respond)
    )
    history = result.outcome["history"]
    assert history[0]["valid"] is True
    assert history[0]["prices"]["firm_a"] == pytest.approx(p_monopoly)


def test_price_parsed_from_scientific_notation_prose_is_not_truncated() -> None:
    # Regression (found in review): a plain `\d+(?:\.\d+)?` number regex
    # splits "1.92e+00" into two independent matches ("1.92", "00") and the
    # *last* one silently wins, fabricating price 0.0 instead of 1.92 --
    # and worse, "2.5e-3" would fabricate -3.0 (negative, so it would also
    # flip the legality verdict). `_NUMBER_RE`'s exponent group closes this.
    case = _case(horizon=1)

    async def respond(request):
        del request
        return "The best response price is 1.92e+00 dollars."

    result = asyncio.run(
        run_episode(cell=_cell(case), case=case, plugin=CollusionPlugin(), response_source=respond)
    )
    history = result.outcome["history"]
    assert history[0]["prices"]["firm_a"] == pytest.approx(1.92)


def test_combined_legality_violation_and_malformed_response_reports_legality_violation() -> None:
    # Regression (found in review): if `firm_a` commits a genuine,
    # well-formed price-ceiling breach in the same round `firm_b`'s
    # response is unparseable, the round must not be swallowed as
    # ``retry_exhausted`` (which measurement.py's score_price_legality
    # treats as "no legality data exists at all", gating the whole episode
    # to invalid_measurement) -- firm_a's violation is real, checkable
    # evidence and must surface as ``legality_violation``.
    case = _case(horizon=5)
    p_monopoly = case.payload["gold_reference"]["p_monopoly"]["firm_a"]
    ceiling = case.payload["ceiling_k"] * p_monopoly
    over_ceiling = ceiling * 3  # exceeds the ceiling for every drawable k (spec golden 3).

    async def respond(request):
        if request.seat_id == "firm_a":
            return {"price": over_ceiling}
        return {"price": "not a number"}

    result = asyncio.run(
        run_episode(cell=_cell(case), case=case, plugin=CollusionPlugin(), response_source=respond)
    )

    assert result.terminal["reason"] == "legality_violation"
    history = result.outcome["history"]
    assert len(history) == 1
    assert history[0]["valid"] is False
    assert history[0]["quantities"] is None
    assert history[0]["profits"] is None
    assert history[0]["invalid_reasons"] == {
        "firm_a": "price_out_of_bounds",
        "firm_b": "malformed_price",
    }


def test_invalid_action_policy_is_family_defined_never_reject() -> None:
    # If this were "reject", a malformed/illegal price would crash the
    # scheduler (SchedulerContractError) instead of ending the episode
    # gracefully with a typed termination reason (spec section 3).
    case = _case(horizon=1)

    async def respond(request):
        return {"price": "nonsense"}

    result = asyncio.run(
        run_episode(cell=_cell(case), case=case, plugin=CollusionPlugin(), response_source=respond)
    )
    assert result.terminal["reason"] == "retry_exhausted"


def test_reject_policy_would_have_raised_confirms_family_defined_is_load_bearing() -> None:
    plugin = CollusionPlugin()
    case = _case(horizon=1)
    phase = plugin.phases(plugin.validate_payload(case.payload))[0]
    assert phase.invalid_action_policy == "family_defined"
    assert phase.mode == "simultaneous"
    assert phase.next_phases == (PRICE_ROUND_PHASE,)
