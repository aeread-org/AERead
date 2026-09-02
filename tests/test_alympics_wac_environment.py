"""Provider-free scheduler coverage for the alympics.wac environment plugin.

Every test here runs the pinned, real upstream ``waterAllocation`` /
``Alympics`` checkout in-process (no bridge, no network, no LLM call --
``docs/alympics_adapter_spec.md`` section 1's "No bridge" decision). The five
goldens in the spec's section 4 are exercised as environment/trajectory
behavior (state transitions, exceptions caught, termination reasons), never
as a scoring claim -- ``build_scorer`` is deliberately not built yet
(milestone 2).
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from aeread.shared_runner.registry import (
    REQUIRED_FAMILY_PLUGIN_HOOKS,
    PluginRegistry,
)
from aeread.shared_runner.resolver import PlanCell
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import SchedulerContractError, run_episode
from aeread_families.alympics_wac.cases import PERSONAS, SEAT_ORDER
from aeread_families.alympics_wac.environment import (
    AlympicsWacPlugin,
    RoundOutcome,
    _delegate_round,
    family_manifest,
    register_plugin,
)
from aeread_families.alympics_wac import environment as environment_module


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_ALYMPICS_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-alympics",
    )
    root = Path(candidate)
    marker = root / "src" / "waterAllocation.py"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream Alympics checkout not found at {root}",
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()
CASES_DIR = Path("cases/alympics_wac/base")


def _case(name: str) -> CaseManifest:
    path = CASES_DIR / f"alympics.wac.{name}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id="cell_alympics_wac_environment",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_alympics_wac_environment",
        suite_version="0.1.0",
        block_id="block_alympics_wac_environment",
        sampling_plan_id="sampling_alympics_wac_environment",
        analysis_plan_id="analysis_alympics_wac_environment",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id="cluster_alympics_wac_environment",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(
            {seat: f"scripted_{seat}" for seat in SEAT_ORDER}
        ),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _plugin() -> AlympicsWacPlugin:
    return AlympicsWacPlugin(upstream_root=UPSTREAM_ROOT)


async def _proportional_response_source(request):
    requirement = request.observation["requirement"]
    return {"bid": 3 * requirement}


def _multiplier_response_source(multiplier_by_seat):
    async def _respond(request):
        seat_id = request.seat_id
        requirement = request.observation["requirement"]
        return {"bid": multiplier_by_seat[seat_id] * requirement}

    return _respond


# ---------------------------------------------------------------------------
# Registration and family manifest shape.
# ---------------------------------------------------------------------------


def test_plugin_registers_every_required_hook_through_normal_registry() -> None:
    plugin = _plugin()
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


def test_build_scorer_hook_wires_to_measurement_pys_alympics_wac_scorer() -> None:
    # Milestone 2 scope: build_scorer now returns the real measurement
    # leaves instead of raising (see tests/test_alympics_wac_measurement.py
    # for full leaf/golden coverage; this only pins the hook wiring).
    from aeread_families.alympics_wac.measurement import AlympicsWacScorer

    plugin = _plugin()
    case = _case("reference_baseline")
    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)
    assert isinstance(scorer, AlympicsWacScorer)
    assert scorer.family_case == family_case
    leaves = scorer.leaves_for_focal_seat("alex")
    assert len(leaves) == 4
    assert scorer.panel_policy_ids("alex") == {
        seat: "proportional" for seat in SEAT_ORDER if seat != "alex"
    }


def test_phases_is_one_self_looping_simultaneous_bid_phase() -> None:
    plugin = _plugin()
    case = _case("reference_baseline")
    family_case = plugin.validate_payload(case.payload)
    phases = plugin.phases(family_case)
    assert len(phases) == 1
    phase = phases[0]
    assert phase.phase_id == "bid"
    assert phase.mode == "simultaneous"
    assert phase.next_phases == ("bid",)
    assert phase.max_logical_actions == 5 * 20


# ---------------------------------------------------------------------------
# validate_payload.
# ---------------------------------------------------------------------------


def test_validate_payload_accepts_every_grid_cell_case() -> None:
    plugin = _plugin()
    for path in sorted(CASES_DIR.glob("alympics.wac.*.json")):
        case = CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
        family_case = plugin.validate_payload(case.payload)
        assert family_case["grid_cell"]["rounds"] == len(family_case["supply_schedule"])


def test_validate_payload_rejects_wrong_upstream_commit() -> None:
    plugin = _plugin()
    case = _case("reference_baseline")
    payload = environment_module._plain(case.payload)
    payload["upstream_pin"]["commit"] = "0" * 40
    with pytest.raises(ValueError, match="upstream_pin"):
        plugin.validate_payload(payload)


def test_validate_payload_rejects_tampered_personas() -> None:
    plugin = _plugin()
    case = _case("reference_baseline")
    payload = environment_module._plain(case.payload)
    payload["personas"]["alex"]["requirement"] = 999
    with pytest.raises(ValueError, match="personas"):
        plugin.validate_payload(payload)


# ---------------------------------------------------------------------------
# Golden 1 -- successful: verified round-1 bid vector (spec section 4).
# ---------------------------------------------------------------------------


def test_round_1_proportional_bids_and_winner_match_the_hand_verified_golden() -> None:
    plugin = _plugin()
    case = _case("reference_baseline")
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, None)
    phases = plugin.phases(family_case)
    phase = phases[0]

    actors = plugin.eligible_actors(family_case, state, phase)
    assert actors == ("alex", "bob", "cindy", "david", "eric")

    actions = {}
    for seat in actors:
        observation = plugin.observe(family_case, state, seat, phase)
        raw = {"bid": 3 * observation["requirement"]}
        parsed = plugin.parse_action(family_case, state, seat, phase, raw)
        assert parsed.ok
        legality = plugin.legal(family_case, state, seat, phase, parsed.action)
        assert legality.legal
        actions[seat] = SimpleNamespace(action=parsed.action)

    transition = plugin.step(family_case, state, phase, actions)
    round_log = transition.state["round_log"][0]

    assert round_log["bids"] == {"alex": 24, "bob": 27, "cindy": 30, "david": 33, "eric": 36}
    assert round_log["winners"] == ["eric"]
    assert round_log["bid_legal"] == {seat: True for seat in actors}
    assert transition.state["players"]["eric"] == {
        "balance": 84,
        "hp": 10,
        "no_drink": 1,
        "alive": True,
    }
    for seat in ("alex", "bob", "cindy", "david"):
        assert transition.state["players"][seat]["hp"] == 7
        assert transition.state["players"][seat]["no_drink"] == 2
        assert transition.state["players"][seat]["alive"] is True
    assert transition.next_phase_id == "bid"
    assert transition.state["termination"] is None


def test_reference_baseline_runs_full_20_rounds_end_to_end_through_run_episode() -> None:
    plugin = _plugin()
    case = _case("reference_baseline")
    cell = _cell(case)

    result = asyncio.run(
        run_episode(
            cell=cell,
            case=case,
            plugin=plugin,
            response_source=_proportional_response_source,
        )
    )

    assert result.terminal["reason"] == "rounds_exhausted"
    assert result.terminal["round_id"] == 20
    assert result.outcome["termination_reason"] == "rounds_exhausted"
    # All-proportional (identical multiplier for every seat) does not mean
    # identical outcomes: `_check_winner` admits the *highest absolute bid*
    # first, and 3x each seat's own (different) requirement/salary is not a
    # need-normalized bid -- the highest-salary seat (Eric) wins most rounds
    # and the rest are gradually eliminated. This is a real, delegated
    # emergent property of the scenario, not a scoring claim (leaf 1/2 are
    # built in milestone 2, and per the audit this is `baseline_only` --
    # never read as evidence of a solved policy optimum).
    final_players = result.final_state["players"]
    survivors = [seat for seat in SEAT_ORDER if final_players[seat]["alive"]]
    eliminated = [seat for seat in SEAT_ORDER if not final_players[seat]["alive"]]
    assert survivors, "at least one seat must survive a rounds_exhausted ending"
    assert set(survivors) | set(eliminated) == set(SEAT_ORDER)
    assert set(result.final_state["eliminated_order"]) == set(eliminated)
    for seat in survivors:
        assert final_players[seat]["balance"] > 0


# ---------------------------------------------------------------------------
# Golden 2 -- valid but poor: a systematically under-bidding focal seat.
# ---------------------------------------------------------------------------


def test_conservative_focal_seat_ends_with_lower_wealth_than_proportional_rivals() -> None:
    plugin = _plugin()
    case = _case("reference_baseline")
    cell = _cell(case)

    # alex bids 1x requirement ("conservative"); every rival bids 3x
    # ("proportional") -- every bid stays legal and well-formed (Leaf 3/4
    # would pass), alex is simply outbid most rounds.
    multipliers = {"alex": 1, "bob": 3, "cindy": 3, "david": 3, "eric": 3}
    response_source = _multiplier_response_source(multipliers)

    result = asyncio.run(
        run_episode(
            cell=cell,
            case=case,
            plugin=plugin,
            response_source=response_source,
        )
    )

    final_players = result.final_state["players"]
    assert final_players["alex"]["balance"] < final_players["bob"]["balance"]
    assert final_players["alex"]["no_drink"] >= 2


# ---------------------------------------------------------------------------
# Golden 3 -- invalid/unauthorized: bid exceeds balance, silently excluded.
# ---------------------------------------------------------------------------


def test_delegate_round_flags_an_over_balance_bid_as_illegal_but_still_settles() -> None:
    plugin = _plugin()
    upstream = plugin._require_upstream()
    alive = SEAT_ORDER
    players_state = {seat: {"balance": 0, "hp": 8, "no_drink": 1} for seat in alive}
    bids = {"alex": 10_000, "bob": 27, "cindy": 30, "david": 33, "eric": 36}

    outcome = _delegate_round(
        upstream,
        round_id=1,
        supply=15,
        alive_seats=alive,
        players_state=players_state,
        bids=bids,
    )

    assert outcome.status == "settled"
    assert outcome.bid_legal["alex"] is False
    assert all(outcome.bid_legal[seat] for seat in ("bob", "cindy", "david", "eric"))
    assert outcome.winners == ("eric",)
    # A silent exclusion is not a settlement error: alex still gets a
    # perfectly ordinary "lost this round" penalty, same as a legal loss.
    assert outcome.players["alex"] == {"balance": 70, "hp": 7, "no_drink": 2}


def test_legal_hook_never_rejects_an_over_balance_bid_action() -> None:
    # invalid_action_policy="reject" on the bid phase means a `legal()`
    # rejection would abort the whole episode -- confirming this hook never
    # does that for a merely-over-balance (but well-typed) bid.
    plugin = _plugin()
    case = _case("reference_baseline")
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, None)
    phase = plugin.phases(family_case)[0]

    legality = plugin.legal(family_case, state, "alex", phase, {"bid": 999_999})
    assert legality.legal is True


def test_over_balance_bid_is_flagged_illegal_through_a_real_run_episode_step() -> None:
    # Unlike the two tests above (which call `_delegate_round`/`legal`
    # directly), this drives golden 3 through the actual Mode C phase graph
    # -- `observe` -> `parse_action` -> `legal` -> `step` -- via `run_episode`,
    # so the `bids`-from-`actions` assembly, the `players_before` snapshot,
    # and the round-log entry `step` itself writes (spec section 5's e2e
    # requirement) are the ones actually exercised, not a hand-constructed
    # stand-in for them.
    plugin = _plugin()
    case = _case("reference_baseline")
    cell = _cell(case)

    async def _response_source(request):
        if request.seat_id == "alex":
            # 999,999 exceeds any balance alex could ever accrue this
            # episode (daily_salary tops out at 120/round for 20 rounds),
            # so the over-balance bid stays illegal for every round.
            return {"bid": 999_999}
        return {"bid": 3 * request.observation["requirement"]}

    result = asyncio.run(
        run_episode(
            cell=cell,
            case=case,
            plugin=plugin,
            response_source=_response_source,
        )
    )

    round_log = result.final_state["round_log"]
    assert round_log, "expected at least one round to be recorded"
    rounds_with_alex = [entry for entry in round_log if "alex" in entry["bid_legal"]]
    assert rounds_with_alex, "alex must be alive and bidding in at least one round"
    for entry in rounds_with_alex:
        assert entry["bid_legal"]["alex"] is False
        assert "alex" not in entry["winners"]
        # A silent exclusion is not a settlement error: every other
        # (still-alive) seat's legality is untouched by alex's violation --
        # only alex's own bid was ever illegal.
        for seat, legal in entry["bid_legal"].items():
            if seat != "alex":
                assert legal is True
    final_players = result.final_state["players"]
    assert not final_players["alex"]["alive"]
    assert "alex" in result.final_state["eliminated_order"]
    assert result.terminal["reason"] in ("rounds_exhausted", "all_seats_eliminated")


# ---------------------------------------------------------------------------
# Golden 4 -- malformed/operational failure.
# ---------------------------------------------------------------------------


def test_delegate_round_missing_key_raises_keyerror_caught_as_malformed() -> None:
    plugin = _plugin()
    upstream = plugin._require_upstream()
    alive = SEAT_ORDER
    players_state = {seat: {"balance": 0, "hp": 8, "no_drink": 1} for seat in alive}
    bids = {"alex": 24, "bob": 27, "cindy": 30, "david": 33, "eric": 36}

    outcome = _delegate_round(
        upstream,
        round_id=1,
        supply=15,
        alive_seats=alive,
        players_state=players_state,
        bids=bids,
        force_malformed="missing_key",
    )
    assert outcome.status == "malformed_action"
    assert outcome.players is None
    assert outcome.error.startswith("KeyError")


def test_delegate_round_unparseable_raises_typeerror_caught_as_malformed() -> None:
    plugin = _plugin()
    upstream = plugin._require_upstream()
    alive = SEAT_ORDER
    players_state = {seat: {"balance": 0, "hp": 8, "no_drink": 1} for seat in alive}
    bids = {"alex": 24, "bob": 27, "cindy": 30, "david": 33, "eric": 36}

    outcome = _delegate_round(
        upstream,
        round_id=1,
        supply=15,
        alive_seats=alive,
        players_state=players_state,
        bids=bids,
        force_malformed="unparseable",
    )
    assert outcome.status == "malformed_action"
    assert outcome.error.startswith("TypeError")


def test_step_records_malformed_action_termination_without_crashing(monkeypatch) -> None:
    plugin = _plugin()
    case = _case("reference_baseline")
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, None)
    phase = plugin.phases(family_case)[0]

    def _broken_delegate_round(*args, **kwargs):
        return RoundOutcome(
            status="malformed_action",
            players=None,
            eliminated_this_round=tuple(SEAT_ORDER),
            winners=(),
            bid_legal={},
            error="KeyError: 'Alex'",
        )

    monkeypatch.setattr(environment_module, "_delegate_round", _broken_delegate_round)

    actions = {
        seat: SimpleNamespace(action={"bid": 3 * PERSONAS[seat]["requirement"]})
        for seat in SEAT_ORDER
    }
    transition = plugin.step(family_case, state, phase, actions)

    assert transition.state["termination"] == "malformed_action"
    assert transition.next_phase_id is None
    assert transition.state["round_log"][-1]["status"] == "malformed_action"
    assert transition.state["round_log"][-1]["error"] == "KeyError: 'Alex'"


# ---------------------------------------------------------------------------
# Golden 5 -- degenerate reference: zero supply every round.
# ---------------------------------------------------------------------------


def test_zero_supply_degenerate_eliminates_every_seat_identically_at_round_4() -> None:
    plugin = _plugin()
    case = _case("zero_supply_degenerate")
    cell = _cell(case)

    async def _zero_bid_response_source(request):
        return {"bid": 0}

    result = asyncio.run(
        run_episode(
            cell=cell,
            case=case,
            plugin=plugin,
            response_source=_zero_bid_response_source,
        )
    )

    assert result.terminal["reason"] == "all_seats_eliminated"
    assert result.terminal["round_id"] == 4
    hp_by_seat = {seat: result.final_state["players"][seat]["hp"] for seat in SEAT_ORDER}
    assert hp_by_seat == {seat: -2 for seat in SEAT_ORDER}
    assert set(result.final_state["eliminated_order"]) == set(SEAT_ORDER)
    for seat in SEAT_ORDER:
        assert result.final_state["players"][seat]["alive"] is False


def test_zero_supply_degenerate_hp_trajectory_matches_the_spec_exactly() -> None:
    plugin = _plugin()
    case = _case("zero_supply_degenerate")
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, None)
    phase = plugin.phases(family_case)[0]

    expected_hp_after_round = {1: 7, 2: 5, 3: 2}
    for round_id in (1, 2, 3):
        actors = plugin.eligible_actors(family_case, state, phase)
        actions = {
            seat: SimpleNamespace(action={"bid": 0}) for seat in actors
        }
        transition = plugin.step(family_case, state, phase, actions)
        state = transition.state
        for seat in SEAT_ORDER:
            assert state["players"][seat]["hp"] == expected_hp_after_round[round_id]
        assert state["termination"] is None


# ---------------------------------------------------------------------------
# Leakage audit (spec section 2 leaf 4 prerequisite).
# ---------------------------------------------------------------------------


def test_observation_never_contains_another_seats_status_or_bid() -> None:
    plugin = _plugin()
    case = _case("reference_baseline")
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, None)
    # Force each seat to a visibly distinct balance/HP so a leak is
    # unmistakable if it ever appears in another seat's observation.
    distinguishing_values = {
        "alex": 111,
        "bob": 222,
        "cindy": 333,
        "david": 444,
        "eric": 555,
    }
    for seat, value in distinguishing_values.items():
        state["players"][seat]["balance"] = value

    phase = plugin.phases(family_case)[0]
    observations = {
        seat: plugin.observe(family_case, state, seat, phase) for seat in SEAT_ORDER
    }
    for seat in SEAT_ORDER:
        own_observation_text = json.dumps(observations[seat], sort_keys=True)
        assert str(distinguishing_values[seat]) in own_observation_text
        for other_seat, other_value in distinguishing_values.items():
            if other_seat == seat:
                continue
            assert str(other_value) not in own_observation_text


# ---------------------------------------------------------------------------
# eligible_actors shrinks as seats are eliminated (mid-game, not total wipeout).
# ---------------------------------------------------------------------------


def test_eligible_actors_excludes_eliminated_seats() -> None:
    plugin = _plugin()
    case = _case("reference_baseline")
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, None)
    state["players"]["alex"]["alive"] = False
    phase = plugin.phases(family_case)[0]

    actors = plugin.eligible_actors(family_case, state, phase)
    assert "alex" not in actors
    assert set(actors) == {"bob", "cindy", "david", "eric"}


def test_observe_rejects_an_already_eliminated_seat() -> None:
    plugin = _plugin()
    case = _case("reference_baseline")
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, None)
    state["players"]["alex"]["alive"] = False
    phase = plugin.phases(family_case)[0]

    with pytest.raises(ValueError, match="eliminated"):
        plugin.observe(family_case, state, "alex", phase)


# ---------------------------------------------------------------------------
# Malformed schema-level actions are still hard-rejected by the scheduler.
# ---------------------------------------------------------------------------


def test_parse_action_rejects_a_negative_bid() -> None:
    plugin = _plugin()
    case = _case("reference_baseline")
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, None)
    phase = plugin.phases(family_case)[0]

    parsed = plugin.parse_action(family_case, state, "alex", phase, {"bid": -1})
    assert not parsed.ok
    assert parsed.error_code == "bid_must_be_a_nonnegative_integer"


def test_scheduler_aborts_the_episode_on_a_malformed_bid_schema() -> None:
    plugin = _plugin()
    case = _case("reference_baseline")
    cell = _cell(case)

    async def _malformed_response_source(request):
        if request.seat_id == "alex":
            return {"bid": "not-a-number"}
        return {"bid": 3 * request.observation["requirement"]}

    with pytest.raises(SchedulerContractError):
        asyncio.run(
            run_episode(
                cell=cell,
                case=case,
                plugin=plugin,
                response_source=_malformed_response_source,
            )
        )
