"""Tests for the alympics.wac measurement leaves (measurement.py).

Covers the five QC Gate-2 goldens from ``docs/alympics_adapter_spec.md``
section 4 as executable, typed-result assertions -- never as environment-
only trajectory checks (those already live in
``tests/test_alympics_wac_environment.py``, milestone 1's scope). Every
test here runs the pinned, real upstream ``waterAllocation``/``Alympics``
checkout in-process (no bridge, no network, no LLM call, no judge call --
this family declares no rater/judge leaf at all).
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from aeread.shared_runner.measurement import MeasurementContractError
from aeread.shared_runner.resolver import PlanCell
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import run_episode
from aeread_families.alympics_wac import measurement as m
from aeread_families.alympics_wac.cases import PERSONAS, SEAT_ORDER
from aeread_families.alympics_wac.environment import AlympicsWacPlugin, _delegate_round


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
        cell_id="cell_alympics_wac_measurement",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_alympics_wac_measurement",
        suite_version="0.1.0",
        block_id="block_alympics_wac_measurement",
        sampling_plan_id="sampling_alympics_wac_measurement",
        analysis_plan_id="analysis_alympics_wac_measurement",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id="cluster_alympics_wac_measurement",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType({seat: f"scripted_{seat}" for seat in SEAT_ORDER}),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _plugin() -> AlympicsWacPlugin:
    return AlympicsWacPlugin(upstream_root=UPSTREAM_ROOT)


def _multiplier_response_source(multiplier_by_seat):
    async def _respond(request):
        seat_id = request.seat_id
        requirement = request.observation["requirement"]
        return {"bid": multiplier_by_seat[seat_id] * requirement}

    return _respond


def _run(case: CaseManifest, response_source) -> tuple[dict, list, dict]:
    """Run one full episode; return (final_players, round_log, terminal)."""
    plugin = _plugin()
    cell = _cell(case)
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=response_source)
    )
    return result.final_state["players"], result.final_state["round_log"], result.terminal


ALL_PROPORTIONAL = {seat: 3 for seat in SEAT_ORDER}


# ---------------------------------------------------------------------------
# Leaf declaration shape (spec section 2).
# ---------------------------------------------------------------------------


def test_build_leaves_returns_exactly_4_leaves_always() -> None:
    leaves = m.build_leaves(
        focal_seat="alex",
        panel_policy_ids={"bob": "proportional", "cindy": "proportional", "david": "proportional", "eric": "proportional"},
    )
    assert len(leaves) == 4
    assert [leaf.leaf_id for leaf in leaves] == [
        m.TERMINAL_WEALTH_LEAF_ID,
        m.SURVIVAL_LEAF_ID,
        m.BID_LEGALITY_LEAF_ID,
        m.SETTLEMENT_EXACTNESS_LEAF_ID,
    ]
    for leaf in leaves:
        assert leaf.composition_kind == "leaf"


def test_leaf_1_and_2_are_comparative_baseline_delta() -> None:
    wealth = m.build_terminal_wealth_leaf(focal_seat="alex", panel_policy_ids={"bob": "proportional"})
    survival = m.build_survival_leaf(focal_seat="alex", panel_policy_ids={"bob": "proportional"})
    for leaf in (wealth, survival):
        assert leaf.verifier.verifier_family == "comparative"
        assert leaf.verifier.reference.reference_kind == "baseline_delta"
        assert leaf.verifier.evaluation_class == "deterministic"
        assert leaf.estimand.direction == "maximize"


def test_leaf_3_and_4_are_rule_constraint_never_judge_dependent() -> None:
    legality = m.build_bid_legality_leaf()
    settlement = m.build_settlement_exactness_leaf()
    for leaf in (legality, settlement):
        assert leaf.verifier.verifier_family == "rule_constraint"
        assert leaf.verifier.evaluation_class == "deterministic"
        assert leaf.estimand.direction == "none"
    assert legality.verifier.reference.reference_kind == "constraint_satisfaction"
    assert settlement.verifier.reference.reference_kind == "state_invariant"


def test_opponent_panel_is_part_of_the_leaf_1_2_reference_identity() -> None:
    """Two leaves that differ only in the opponent panel must not collide
    on `source_sha256` -- the panel is part of the estimand (spec section 2)."""
    all_proportional = m.build_terminal_wealth_leaf(
        focal_seat="alex", panel_policy_ids={"bob": "proportional", "cindy": "proportional"}
    )
    one_aggressive = m.build_terminal_wealth_leaf(
        focal_seat="alex", panel_policy_ids={"bob": "aggressive", "cindy": "proportional"}
    )
    assert (
        all_proportional.verifier.reference.source_sha256
        != one_aggressive.verifier.reference.source_sha256
    )


def test_the_specs_literal_higher_is_better_is_not_a_legal_kernel_direction() -> None:
    """Spec section 2's leaf 1 YAML literally writes
    `direction: higher_is_better`; the kernel's real EstimandSpec only
    accepts {"maximize", "minimize", "none"}. Documented as a deviation in
    measurement.py's module docstring (mirrors
    tau3_retail.measurement's identical "transcript" deviation test); this
    pins the kernel behavior driving that deviation so it cannot silently
    drift back to an invalid value."""
    from aeread.shared_runner.measurement import EstimandSpec, ImplementationRef, ValidityDomainSpec

    domain = ValidityDomainSpec("d", "1.0.0", "ref", ImplementationRef("p", "1.0.0", "a" * 64))
    with pytest.raises(MeasurementContractError, match="direction"):
        EstimandSpec("e", "1.0.0", "trajectory", "higher_is_better", "native_currency", domain)


# ---------------------------------------------------------------------------
# Evidence helpers.
# ---------------------------------------------------------------------------


def test_is_supply_degenerate_true_only_when_no_requirement_can_ever_be_met() -> None:
    assert m.is_supply_degenerate([0, 0, 0, 0], PERSONAS) is True
    assert m.is_supply_degenerate([7, 7, 7], PERSONAS) is True  # below min requirement (8)
    assert m.is_supply_degenerate([8, 7, 7], PERSONAS) is False  # 8 meets alex's requirement


def test_rounds_survived_counts_only_rounds_the_seat_actually_bid_in() -> None:
    round_log = [
        {"round_id": 1, "bids": {"alex": 1, "bob": 2}},
        {"round_id": 2, "bids": {"bob": 2}},
    ]
    assert m.rounds_survived(round_log, "alex") == 1
    assert m.rounds_survived(round_log, "bob") == 2


def test_alive_at_terminal_reads_the_final_players_alive_flag() -> None:
    final_players = {"alex": {"alive": False}, "bob": {"alive": True}}
    assert m.alive_at_terminal(final_players, "alex") is False
    assert m.alive_at_terminal(final_players, "bob") is True


# ---------------------------------------------------------------------------
# Golden 1 -- successful.
# ---------------------------------------------------------------------------


def test_golden_1_successful_reports_positive_wealth_and_full_survival() -> None:
    case = _case("reference_baseline")
    final_players, round_log, terminal = _run(case, _multiplier_response_source(ALL_PROPORTIONAL))
    upstream = _plugin()._require_upstream()

    for focal_seat in SEAT_ORDER:
        wealth_leaf = m.build_terminal_wealth_leaf(
            focal_seat=focal_seat,
            panel_policy_ids={s: "proportional" for s in SEAT_ORDER if s != focal_seat},
        )
        wealth = m.score_terminal_wealth(
            wealth_leaf,
            focal_seat=focal_seat,
            actual_final_players=final_players,
            actual_round_log=round_log,
            actual_termination_reason=terminal["reason"],
            baseline_final_players=final_players,  # identical policy -> its own baseline
        )
        assert wealth.status == "ok"
        assert wealth.reference_values["actual_terminal_wealth"].value > 0
        assert wealth.primary.value == 0.0  # actual == baseline here

        survival_leaf = m.build_survival_leaf(
            focal_seat=focal_seat,
            panel_policy_ids={s: "proportional" for s in SEAT_ORDER if s != focal_seat},
        )
        survival = m.score_survival(
            survival_leaf,
            focal_seat=focal_seat,
            actual_round_log=round_log,
            actual_final_players=final_players,
            actual_termination_reason=terminal["reason"],
            baseline_round_log=round_log,
            baseline_final_players=final_players,
        )
        assert survival.status == "ok"

        legality_leaf = m.build_bid_legality_leaf()
        legality = m.score_bid_legality(
            legality_leaf,
            focal_seat=focal_seat,
            round_log=round_log,
            termination_reason=terminal["reason"],
        )
        assert legality.status == "ok"
        assert legality.primary.value == 1.0

    settlement_leaf = m.build_settlement_exactness_leaf()
    settlement = m.score_settlement_exactness(
        settlement_leaf,
        upstream_module=upstream,
        round_log=round_log,
        termination_reason=terminal["reason"],
    )
    assert settlement.status == "ok"
    assert settlement.primary.value == 1.0
    assert settlement.metrics["rounds_checked"].value == len(round_log)


# ---------------------------------------------------------------------------
# Golden 2 -- valid but poor.
# ---------------------------------------------------------------------------


def test_golden_2_conservative_focal_seat_scores_a_negative_wealth_delta() -> None:
    # Focal seat is Cindy, not Alex: under "all seats bid 3x their own
    # requirement," Alex's persona already has the *smallest* requirement of
    # the 5, so Alex's own bid is bid-rank-last regardless of whether Alex
    # bids 1x or 3x -- a verified structural fact about this panel that
    # makes Alex's own policy causally inert to Alex's own wealth here (both
    # scripts produce byte-identical outcomes for Alex). Cindy sits in the
    # *middle* of the requirement ranking, so dropping Cindy alone to 1x
    # demonstrably changes Cindy's own admission outcomes over the 20
    # rounds -- verified concretely: baseline (all 3x) ends Cindy at balance
    # 570; scripting only Cindy to 1x ends Cindy at balance 400.
    baseline_case = _case("reference_baseline")
    baseline_final_players, baseline_round_log, baseline_terminal = _run(
        baseline_case, _multiplier_response_source(ALL_PROPORTIONAL)
    )

    poor_case = _case("reference_baseline")
    multipliers = {"alex": 3, "bob": 3, "cindy": 1, "david": 3, "eric": 3}
    actual_final_players, actual_round_log, actual_terminal = _run(
        poor_case, _multiplier_response_source(multipliers)
    )

    leaf = m.build_terminal_wealth_leaf(
        focal_seat="cindy",
        panel_policy_ids={"alex": "proportional", "bob": "proportional", "david": "proportional", "eric": "proportional"},
    )
    envelope = m.score_terminal_wealth(
        leaf,
        focal_seat="cindy",
        actual_final_players=actual_final_players,
        actual_round_log=actual_round_log,
        actual_termination_reason=actual_terminal["reason"],
        baseline_final_players=baseline_final_players,
    )

    assert envelope.status == "ok"
    assert envelope.primary.value < 0
    assert envelope.reference_values["actual_terminal_wealth"].value == 400.0
    assert envelope.reference_values["baseline_terminal_wealth"].value == 570.0
    # Every bid stayed legal and well-formed -- "legal action, bad outcome,"
    # never touching the admission gates (spec section 4).
    legality_leaf = m.build_bid_legality_leaf()
    legality = m.score_bid_legality(
        legality_leaf,
        focal_seat="cindy",
        round_log=actual_round_log,
        termination_reason=actual_terminal["reason"],
    )
    assert legality.status == "ok"


# ---------------------------------------------------------------------------
# Golden 3 -- invalid/unauthorized: bid exceeds balance.
# ---------------------------------------------------------------------------


def _one_round_over_balance_evidence() -> tuple[list, dict]:
    """One round, built directly via `_delegate_round` (never through
    `observe()`), mirroring the spec's own hand-verified worked example:
    a bid of 10,000 against a balance of 70 never wins, no error, no
    distinguishing flag from an ordinary legal loss."""
    plugin = _plugin()
    upstream = plugin._require_upstream()
    players_before = {seat: {"balance": 0, "hp": 8, "no_drink": 1} for seat in SEAT_ORDER}
    bids = {"alex": 10_000, "bob": 27, "cindy": 30, "david": 33, "eric": 36}
    outcome = _delegate_round(
        upstream,
        round_id=1,
        supply=15,
        alive_seats=SEAT_ORDER,
        players_state=players_before,
        bids=bids,
    )
    round_log = [
        {
            "round_id": 1,
            "supply": 15,
            "bids": bids,
            "bid_legal": dict(outcome.bid_legal),
            "winners": list(outcome.winners),
            "eliminated_this_round": list(outcome.eliminated_this_round),
            "status": outcome.status,
            "players_before": players_before,
            "players_after": dict(outcome.players),
        }
    ]
    final_players = {
        seat: {**outcome.players[seat], "alive": seat not in outcome.eliminated_this_round}
        for seat in SEAT_ORDER
    }
    return round_log, final_players


def test_golden_3_over_balance_bid_becomes_invalid_measurement_never_a_legal_loss() -> None:
    round_log, final_players = _one_round_over_balance_evidence()

    legality_leaf = m.build_bid_legality_leaf()
    legality = m.score_bid_legality(
        legality_leaf, focal_seat="alex", round_log=round_log, termination_reason="rounds_exhausted"
    )
    assert legality.status == "invalid_measurement"
    assert legality.primary is None
    assert "bid_exceeds_balance" in legality.validity.reasons[0]

    wealth_leaf = m.build_terminal_wealth_leaf(
        focal_seat="alex", panel_policy_ids={s: "proportional" for s in SEAT_ORDER if s != "alex"}
    )
    wealth = m.score_terminal_wealth(
        wealth_leaf,
        focal_seat="alex",
        actual_final_players=final_players,
        actual_round_log=round_log,
        actual_termination_reason="rounds_exhausted",
        baseline_final_players=final_players,
    )
    assert wealth.status == "invalid_measurement"
    assert wealth.primary is None
    assert "bid_exceeds_balance" in wealth.validity.reasons[0]

    survival_leaf = m.build_survival_leaf(
        focal_seat="alex", panel_policy_ids={s: "proportional" for s in SEAT_ORDER if s != "alex"}
    )
    survival = m.score_survival(
        survival_leaf,
        focal_seat="alex",
        actual_round_log=round_log,
        actual_final_players=final_players,
        actual_termination_reason="rounds_exhausted",
        baseline_round_log=round_log,
        baseline_final_players=final_players,
    )
    assert survival.status == "invalid_measurement"
    assert survival.primary is None

    # A seat whose bid stayed legal is unaffected by another seat's violation.
    bob_legality = m.score_bid_legality(
        legality_leaf, focal_seat="bob", round_log=round_log, termination_reason="rounds_exhausted"
    )
    assert bob_legality.status == "ok"
    assert bob_legality.primary.value == 1.0


# ---------------------------------------------------------------------------
# Golden 4 -- malformed/operational failure.
# ---------------------------------------------------------------------------


def _one_round_malformed_evidence() -> list:
    plugin = _plugin()
    upstream = plugin._require_upstream()
    players_before = {seat: {"balance": 0, "hp": 8, "no_drink": 1} for seat in SEAT_ORDER}
    bids = {"alex": 24, "bob": 27, "cindy": 30, "david": 33, "eric": 36}
    outcome = _delegate_round(
        upstream,
        round_id=1,
        supply=15,
        alive_seats=SEAT_ORDER,
        players_state=players_before,
        bids=bids,
        force_malformed="missing_key",
    )
    assert outcome.status == "malformed_action"
    return [
        {
            "round_id": 1,
            "supply": 15,
            "bids": bids,
            "status": "malformed_action",
            "error": outcome.error,
            "players_before": players_before,
            "players_after": None,
        }
    ]


def test_golden_4_malformed_action_becomes_typed_invalidity_never_a_zero() -> None:
    round_log = _one_round_malformed_evidence()
    plugin = _plugin()
    upstream = plugin._require_upstream()
    dummy_final_players = {seat: {"balance": 0, "hp": 8, "no_drink": 1, "alive": True} for seat in SEAT_ORDER}

    wealth_leaf = m.build_terminal_wealth_leaf(
        focal_seat="alex", panel_policy_ids={s: "proportional" for s in SEAT_ORDER if s != "alex"}
    )
    wealth = m.score_terminal_wealth(
        wealth_leaf,
        focal_seat="alex",
        actual_final_players=dummy_final_players,
        actual_round_log=round_log,
        actual_termination_reason="malformed_action",
        baseline_final_players=dummy_final_players,
    )
    assert wealth.status == "invalid_measurement"
    assert wealth.primary is None
    assert wealth.validity.reasons[0].startswith("malformed_action:round_1:KeyError")
    # Never a task-quality zero (taxonomy section 9 / spec section 4 golden 4):
    # `primary is None` (asserted above) is itself the typed-invalidity
    # result -- an `ok` envelope with `primary.value == 0.0` would instead
    # silently look like a real, scored, zero-wealth outcome.

    survival_leaf = m.build_survival_leaf(
        focal_seat="alex", panel_policy_ids={s: "proportional" for s in SEAT_ORDER if s != "alex"}
    )
    survival = m.score_survival(
        survival_leaf,
        focal_seat="alex",
        actual_round_log=round_log,
        actual_final_players=dummy_final_players,
        actual_termination_reason="malformed_action",
        baseline_round_log=round_log,
        baseline_final_players=dummy_final_players,
    )
    assert survival.status == "invalid_measurement"

    legality_leaf = m.build_bid_legality_leaf()
    legality = m.score_bid_legality(
        legality_leaf, focal_seat="alex", round_log=round_log, termination_reason="malformed_action"
    )
    assert legality.status == "invalid_measurement"
    assert legality.validity.reasons[0].startswith("malformed_action:round_1:KeyError")

    settlement_leaf = m.build_settlement_exactness_leaf()
    settlement = m.score_settlement_exactness(
        settlement_leaf,
        upstream_module=upstream,
        round_log=round_log,
        termination_reason="malformed_action",
    )
    assert settlement.status == "invalid_measurement"
    assert settlement.validity.reasons[0].startswith("malformed_action:round_1:KeyError")


# ---------------------------------------------------------------------------
# Golden 5 -- degenerate reference.
# ---------------------------------------------------------------------------


def test_golden_5_zero_supply_is_information_free_regardless_of_policy() -> None:
    degenerate_case = _case("zero_supply_degenerate")
    supply_schedule = degenerate_case.payload["supply_schedule"]
    assert m.is_supply_degenerate(supply_schedule, PERSONAS) is True

    proportional_players, proportional_round_log, proportional_terminal = _run(
        degenerate_case, _multiplier_response_source(ALL_PROPORTIONAL)
    )
    # A wildly different (but still legal -- bid <= balance) bid pattern
    # still can never win: every persona's requirement exceeds a supply of
    # 0 every round, so bid magnitude is irrelevant to `_check_winner`'s
    # eligibility gate.
    aggressive_multipliers = {seat: 5 for seat in SEAT_ORDER}
    aggressive_players, aggressive_round_log, aggressive_terminal = _run(
        degenerate_case, _multiplier_response_source(aggressive_multipliers)
    )

    assert proportional_terminal["reason"] == aggressive_terminal["reason"] == "all_seats_eliminated"
    assert proportional_players == aggressive_players

    wealth_leaf = m.build_terminal_wealth_leaf(
        focal_seat="alex", panel_policy_ids={s: "proportional" for s in SEAT_ORDER if s != "alex"}
    )
    wealth = m.score_terminal_wealth(
        wealth_leaf,
        focal_seat="alex",
        actual_final_players=aggressive_players,
        actual_round_log=aggressive_round_log,
        actual_termination_reason=aggressive_terminal["reason"],
        baseline_final_players=proportional_players,
        not_informative=True,
    )
    assert wealth.status == "ok"
    assert wealth.primary.value == 0.0
    assert wealth.primary.metadata["not_informative"] is True

    survival_leaf = m.build_survival_leaf(
        focal_seat="alex", panel_policy_ids={s: "proportional" for s in SEAT_ORDER if s != "alex"}
    )
    survival = m.score_survival(
        survival_leaf,
        focal_seat="alex",
        actual_round_log=aggressive_round_log,
        actual_final_players=aggressive_players,
        actual_termination_reason=aggressive_terminal["reason"],
        baseline_round_log=proportional_round_log,
        baseline_final_players=proportional_players,
        not_informative=True,
    )
    assert survival.status == "ok"
    assert survival.primary.value == 0.0
    assert survival.primary.metadata["not_informative"] is True


# ---------------------------------------------------------------------------
# Leaf 4 settlement-exactness: a real recompute, not a tautology.
# ---------------------------------------------------------------------------


def test_settlement_exactness_detects_a_corrupted_sealed_post_state() -> None:
    """Mutation test: corrupt one round_log entry's sealed post-state and
    confirm the leaf 4 recompute actually catches it -- proving this check
    is not a no-op that would always pass regardless of what is sealed
    (see the project's own "skips hide unrun claims" lesson)."""
    case = _case("short_horizon")
    final_players, round_log, terminal = _run(case, _multiplier_response_source(ALL_PROPORTIONAL))
    upstream = _plugin()._require_upstream()
    settlement_leaf = m.build_settlement_exactness_leaf()

    clean = m.score_settlement_exactness(
        settlement_leaf, upstream_module=upstream, round_log=round_log, termination_reason=terminal["reason"]
    )
    assert clean.status == "ok"

    corrupted_round_log = [dict(entry) for entry in round_log]
    corrupted_entry = dict(corrupted_round_log[0])
    corrupted_players_after = {
        seat: dict(snapshot) for seat, snapshot in corrupted_entry["players_after"].items()
    }
    a_seat = next(iter(corrupted_players_after))
    corrupted_players_after[a_seat]["balance"] += 1
    corrupted_entry["players_after"] = corrupted_players_after
    corrupted_round_log[0] = corrupted_entry

    corrupted = m.score_settlement_exactness(
        settlement_leaf,
        upstream_module=upstream,
        round_log=corrupted_round_log,
        termination_reason=terminal["reason"],
    )
    assert corrupted.status == "invalid_measurement"
    assert "settlement_recompute_diverged:round_1" in corrupted.validity.reasons[0]


# ---------------------------------------------------------------------------
# build_scorer wiring (environment.py hook).
# ---------------------------------------------------------------------------


def test_plugin_build_scorer_hook_returns_the_same_leaf_ids_as_measurement_py() -> None:
    plugin = _plugin()
    case = _case("mixed_policies_a")
    family_case = plugin.validate_payload(case.payload)

    scorer = plugin.build_scorer(family_case)

    expected_panel = m.build_leaves(
        focal_seat="alex",
        panel_policy_ids={"bob": "conservative", "cindy": "proportional", "david": "myopic_need", "eric": "proportional"},
    )
    actual = scorer.leaves_for_focal_seat("alex")
    assert tuple(leaf.leaf_id for leaf in actual) == tuple(leaf.leaf_id for leaf in expected_panel)
    assert scorer.panel_policy_ids("alex") == {
        "bob": "conservative",
        "cindy": "proportional",
        "david": "myopic_need",
        "eric": "proportional",
    }
    assert scorer.is_not_informative() is False
