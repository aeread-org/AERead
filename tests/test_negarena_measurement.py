"""Tests for the negarena measurement declarations and scorer
(measurement.py, spec section 2) -- the QC Gate-2 goldens from
``docs/negarena_adapter_spec.md`` section 4, now asserting on the actual
scored leaves rather than only on structural termination facts (which
``tests/test_negarena_environment.py`` already covers).

Bridge-dependent tests (everything that drives a scripted transcript
through ``parse_action``/``legal``/``step`` and then scores it) skip
cleanly when no provisioned bridge interpreter is available, mirroring
``tests/test_negarena_environment.py``'s convention. Provision one with
``tools/negarena_bridge/provision.sh``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from aeread.shared_runner.scheduler import ActionEnvelope
from aeread_families.negarena import measurement as m
from aeread_families.negarena.cases import BLUE, RED
from aeread_families.negarena.environment import (
    BLUE_PHASE,
    RED_PHASE,
    NegarenaPlugin,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_ROOT = Path(
    os.environ.get(
        "AEREAD_NEGARENA_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-negarena",
    )
)


def _bridge():
    from aeread_families.negarena.negarena_bridge import (
        NegarenaBridge,
        NegarenaBridgeUnavailableError,
    )

    if not (UPSTREAM_ROOT / "negotiationarena").is_dir():
        pytest.skip(f"pinned upstream NegotiationArena checkout not found at {UPSTREAM_ROOT}")
    try:
        return NegarenaBridge.discover(UPSTREAM_ROOT)
    except NegarenaBridgeUnavailableError as error:
        pytest.skip(f"upstream NegotiationArena Python interpreter unavailable: {error}")


@pytest.fixture(scope="module")
def bridge():
    return _bridge()


@pytest.fixture
def plugin(bridge) -> NegarenaPlugin:
    return NegarenaPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)


def _load_case(case_id: str, split: str) -> dict:
    path = REPO_ROOT / "cases" / "negarena" / split / f"{case_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _buy_sell_response(
    trade_text: str, *, answer: str = "PROPOSAL", resources_text: str = "X: 1"
) -> str:
    return (
        "<message> negotiating </message>\n"
        f"<player answer> {answer} </player answer>\n"
        f"<newly proposed trade> {trade_text} </newly proposed trade>\n"
        f"<my resources> {resources_text} </my resources>\n"
        "<my goals> goal </my goals>\n"
        "<reason> r </reason>\n"
        "<proposal count> 1 </proposal count>"
    )


def _ultimatum_response(*, answer: str, trade_text: str, resources_text: str) -> str:
    return (
        "<move> 1 </move>\n"
        f"<my resources> {resources_text} </my resources>\n"
        f"<player answer> {answer} </player answer>\n"
        "<reason> r </reason>\n"
        "<message> m </message>\n"
        f"<newly proposed trade> {trade_text} </newly proposed trade>"
    )


def _run_transcript(
    plugin: NegarenaPlugin, family_case: dict, turns: list[tuple[str, str]]
) -> tuple[dict, dict]:
    """Drive ``turns`` (ordered ``(seat_id, response_text)``) through the
    real Mode B phase graph; returns ``(final_state, terminal)``.
    """
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    state = plugin.initial_state(family_case, None)
    terminal = None
    for seat_id, response_text in turns:
        phase = phases[RED_PHASE if seat_id == RED else BLUE_PHASE]
        parsed = plugin.parse_action(family_case, state, seat_id, phase, {"response": response_text})
        if not parsed.ok:
            envelope = ActionEnvelope(seat_id=seat_id, valid=False, action=None, parse=parsed, legality=None)
        else:
            legality = plugin.legal(family_case, state, seat_id, phase, parsed.action)
            envelope = ActionEnvelope(
                seat_id=seat_id,
                valid=legality.legal,
                action=parsed.action if legality.legal else None,
                parse=parsed,
                legality=legality,
            )
        transition = plugin.step(family_case, state, phase, {seat_id: envelope})
        state = transition.state
        terminal = plugin.terminal(family_case, state)
        if terminal is not None:
            break
    assert terminal is not None, "transcript did not terminate the episode"
    return state, terminal


def _score_both_seats(
    plugin: NegarenaPlugin, bridge, family_case: dict, state: dict, terminal: dict
) -> dict[str, Any]:
    scorer = plugin.build_scorer(family_case)
    red = scorer.score_seat_outcome(
        bridge=bridge, state=state, terminal=terminal, seat_id=RED, opponent_policy_id="scripted"
    )
    blue = scorer.score_seat_outcome(
        bridge=bridge, state=state, terminal=terminal, seat_id=BLUE, opponent_policy_id="scripted"
    )
    agreement = scorer.score_agreement_reached(terminal=terminal)
    return {"red": red, "blue": blue, "agreement": agreement}


# ---------------------------------------------------------------------------
# Leaf declarations -- pure, no bridge.
# ---------------------------------------------------------------------------


def test_build_leaves_declares_exactly_the_two_spec_leaves() -> None:
    seat_leaf, agreement_leaf = m.build_leaves()

    assert seat_leaf.leaf_id == m.SEAT_OUTCOME_LEAF_ID
    assert seat_leaf.estimand.estimand_id == m.SEAT_OUTCOME_ESTIMAND_ID
    assert seat_leaf.estimand.direction == "maximize"
    assert seat_leaf.estimand.units == "native_valuation"
    assert seat_leaf.estimand.input_scope == "trajectory"
    assert seat_leaf.verifier.verifier_family == "comparative"
    assert seat_leaf.verifier.reference.reference_kind == "head_to_head"
    assert seat_leaf.verifier.evaluation_class == "deterministic"
    assert seat_leaf.composition_kind == "leaf"

    assert agreement_leaf.leaf_id == m.AGREEMENT_LEAF_ID
    assert agreement_leaf.estimand.estimand_id == m.AGREEMENT_ESTIMAND_ID
    assert agreement_leaf.estimand.input_scope == "terminal_state"
    assert agreement_leaf.verifier.verifier_family == "rule_constraint"
    assert agreement_leaf.verifier.reference.reference_kind == "constraint_satisfaction"
    assert agreement_leaf.composition_kind == "leaf"


def test_invalid_termination_reasons_are_exactly_the_two_admission_gate_failures() -> None:
    assert m.INVALID_TERMINATION_REASONS == {"malformed_action", "invalid_measurement"}


def test_score_seat_outcome_never_touches_the_bridge_for_an_invalid_termination() -> None:
    seat_leaf = m.build_seat_outcome_leaf()
    terminal = {"reason": "invalid_measurement", "iteration_count": 1, "last_answer": None}
    score = m.score_seat_outcome(
        seat_leaf,
        bridge=None,  # never called: the short-circuit must happen first
        family_case={"scenario": {}},
        state={"history": []},
        terminal=terminal,
        seat_id=RED,
        opponent_policy_id="scripted",
    )
    assert score.status == "invalid_measurement"
    assert score.primary is None
    assert score.validity.status == "invalid"


def test_score_agreement_reached_never_needs_the_bridge_for_a_malformed_termination() -> None:
    agreement_leaf = m.build_agreement_reached_leaf()
    score = m.score_agreement_reached(agreement_leaf, terminal={"reason": "malformed_action"})
    assert score.status == "invalid_measurement"
    assert score.primary is None


# ---------------------------------------------------------------------------
# Golden 1 -- successful (spec section 4).
# ---------------------------------------------------------------------------


def test_golden_1_buy_sell_settlement_matches_upstreams_shipped_transcript(plugin, bridge) -> None:
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    family_case = plugin.validate_payload(case["payload"])

    offers = [50, 30, 45, 35, 42, 38, 40]
    turns: list[tuple[str, str]] = []
    for index, price in enumerate(offers):
        seat = RED if index % 2 == 0 else BLUE
        resources_text = "X: 1" if seat == RED else "ZUP: 1000"
        turns.append(
            (seat, _buy_sell_response(f"Player RED Gives X: 1 | Player BLUE Gives ZUP: {price}", resources_text=resources_text))
        )
    turns.append((BLUE, _buy_sell_response("NONE", answer="ACCEPT", resources_text="ZUP: 1000")))

    state, terminal = _run_transcript(plugin, family_case, turns)
    assert terminal["reason"] == "accepted"
    scores = _score_both_seats(plugin, bridge, family_case, state, terminal)

    assert scores["red"].status == "ok"
    assert scores["red"].primary.value == 0.0
    assert scores["blue"].primary.value == 20.0
    assert scores["agreement"].primary.value == 1.0
    # opponent identity is score-time metadata, not baked into the leaf.
    assert scores["red"].primary.metadata["opponent_seat_role"] == BLUE
    assert scores["red"].primary.metadata["pairing_rule"] == m.PAIRING_RULE


def test_golden_1_analogue_ultimatum_settlement(plugin, bridge) -> None:
    case = _load_case("negarena.ultimatum.0", "ultimatum")
    family_case = plugin.validate_payload(case["payload"])
    turns = [
        (RED, _ultimatum_response(answer="PROPOSAL", trade_text="Player RED Gives Dollars: 40 | Player BLUE Gives Dollars: 0", resources_text="Dollars: 100")),
        (BLUE, _ultimatum_response(answer="ACCEPT", trade_text="NONE", resources_text="Dollars: 0")),
    ]
    state, terminal = _run_transcript(plugin, family_case, turns)
    assert terminal["reason"] == "accepted"
    scores = _score_both_seats(plugin, bridge, family_case, state, terminal)

    assert scores["red"].primary.value == 60.0
    assert scores["blue"].primary.value == 40.0
    assert scores["agreement"].primary.value == 1.0


# ---------------------------------------------------------------------------
# Golden 2 -- valid-but-poor (spec section 4).
# ---------------------------------------------------------------------------


def test_golden_2_buy_sell_red_accepts_a_lowball(plugin, bridge) -> None:
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    family_case = plugin.validate_payload(case["payload"])
    turns = [
        (RED, _buy_sell_response("Player RED Gives X: 1 | Player BLUE Gives ZUP: 50")),
        (BLUE, _buy_sell_response("Player RED Gives X: 1 | Player BLUE Gives ZUP: 20", resources_text="ZUP: 1000")),
        (RED, _buy_sell_response("NONE", answer="ACCEPT")),
    ]
    state, terminal = _run_transcript(plugin, family_case, turns)
    assert terminal["reason"] == "accepted"
    scores = _score_both_seats(plugin, bridge, family_case, state, terminal)

    # Spec section 4 golden 2: v({X:-1, ZUP:20}) = -20 for RED, 40 for BLUE.
    assert scores["red"].primary.value == -20.0
    assert scores["blue"].primary.value == 40.0
    assert scores["agreement"].primary.value == 1.0


def test_golden_2_analogue_ultimatum_responder_accepts_a_near_zero_split(plugin, bridge) -> None:
    case = _load_case("negarena.ultimatum.0", "ultimatum")
    family_case = plugin.validate_payload(case["payload"])
    turns = [
        (RED, _ultimatum_response(answer="PROPOSAL", trade_text="Player RED Gives Dollars: 1 | Player BLUE Gives Dollars: 0", resources_text="Dollars: 100")),
        (BLUE, _ultimatum_response(answer="ACCEPT", trade_text="NONE", resources_text="Dollars: 0")),
    ]
    state, terminal = _run_transcript(plugin, family_case, turns)
    assert terminal["reason"] == "accepted"
    scores = _score_both_seats(plugin, bridge, family_case, state, terminal)

    assert scores["red"].primary.value == 99.0
    assert scores["blue"].primary.value == 1.0
    assert scores["agreement"].primary.value == 1.0


# ---------------------------------------------------------------------------
# Golden 3 -- invalid-unauthorized (spec section 4): no seat-outcome leaf.
# ---------------------------------------------------------------------------


def test_golden_3_buy_sell_invalid_trade_emits_no_seat_outcome_leaf(plugin, bridge) -> None:
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    family_case = plugin.validate_payload(case["payload"])
    turns = [(RED, _buy_sell_response("Player RED Gives X: 5 | Player BLUE Gives ZUP: 100"))]
    state, terminal = _run_transcript(plugin, family_case, turns)
    assert terminal["reason"] == "invalid_measurement"
    scores = _score_both_seats(plugin, bridge, family_case, state, terminal)

    for score in (scores["red"], scores["blue"], scores["agreement"]):
        assert score.status == "invalid_measurement"
        assert score.primary is None
        assert score.validity.status == "invalid"


def test_golden_3_analogue_ultimatum_invalid_trade_emits_no_seat_outcome_leaf(plugin, bridge) -> None:
    case = _load_case("negarena.ultimatum.0", "ultimatum")
    family_case = plugin.validate_payload(case["payload"])
    turns = [
        (RED, _ultimatum_response(answer="PROPOSAL", trade_text="Player RED Gives Dollars: 150 | Player BLUE Gives Dollars: 0", resources_text="Dollars: 100"))
    ]
    state, terminal = _run_transcript(plugin, family_case, turns)
    assert terminal["reason"] == "invalid_measurement"
    scores = _score_both_seats(plugin, bridge, family_case, state, terminal)

    for score in (scores["red"], scores["blue"], scores["agreement"]):
        assert score.status == "invalid_measurement"
        assert score.primary is None


# ---------------------------------------------------------------------------
# Golden 4 -- malformed-operational (spec section 4): no seat-outcome leaf.
# ---------------------------------------------------------------------------


def test_golden_4_buy_sell_malformed_trade_emits_no_seat_outcome_leaf(plugin, bridge) -> None:
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    family_case = plugin.validate_payload(case["payload"])
    turns = [(RED, _buy_sell_response("this is not a legal trade grammar at all"))]
    state, terminal = _run_transcript(plugin, family_case, turns)
    assert terminal["reason"] == "malformed_action"
    scores = _score_both_seats(plugin, bridge, family_case, state, terminal)

    for score in (scores["red"], scores["blue"], scores["agreement"]):
        assert score.status == "invalid_measurement"
        assert score.primary is None


def test_golden_4_analogue_ultimatum_malformed_trade_emits_no_seat_outcome_leaf(plugin, bridge) -> None:
    case = _load_case("negarena.ultimatum.0", "ultimatum")
    family_case = plugin.validate_payload(case["payload"])
    turns = [
        (RED, _ultimatum_response(answer="PROPOSAL", trade_text="this is not a legal trade grammar at all", resources_text="Dollars: 100"))
    ]
    state, terminal = _run_transcript(plugin, family_case, turns)
    assert terminal["reason"] == "malformed_action"
    scores = _score_both_seats(plugin, bridge, family_case, state, terminal)

    for score in (scores["red"], scores["blue"], scores["agreement"]):
        assert score.status == "invalid_measurement"
        assert score.primary is None


# ---------------------------------------------------------------------------
# Golden 5 -- degenerate-reference (spec section 4).
# ---------------------------------------------------------------------------


def test_golden_5_buy_sell_no_zopa_settles_at_zero_for_both_seats(plugin, bridge) -> None:
    case = _load_case("negarena.buy_sell.2", "buy_sell")
    family_case = plugin.validate_payload(case["payload"])
    turns: list[tuple[str, str]] = []
    for index in range(10):
        seat = RED if index % 2 == 0 else BLUE
        resources_text = "X: 1" if seat == RED else "ZUP: 1000"
        turns.append(
            (seat, _buy_sell_response(f"Player RED Gives X: 1 | Player BLUE Gives ZUP: {50 + index}", resources_text=resources_text))
        )
    state, terminal = _run_transcript(plugin, family_case, turns)
    assert terminal["reason"] == "iteration_cap"
    scores = _score_both_seats(plugin, bridge, family_case, state, terminal)

    assert scores["red"].status == "ok"
    assert scores["red"].primary.value == 0.0
    assert scores["blue"].primary.value == 0.0
    assert scores["agreement"].primary.value == 0.0
    assert scores["agreement"].metrics["terminated_by_iteration_cap"].value == 1.0


def test_golden_5_analogue_ultimatum_zero_endowment_settles_at_zero(plugin, bridge) -> None:
    case = _load_case("negarena.ultimatum.2", "ultimatum")
    family_case = plugin.validate_payload(case["payload"])
    turns: list[tuple[str, str]] = []
    for index in range(6):
        seat = RED if index % 2 == 0 else BLUE
        turns.append(
            (
                seat,
                _ultimatum_response(
                    answer="PROPOSAL",
                    trade_text="Player RED Gives Dollars: 0 | Player BLUE Gives Dollars: 0",
                    resources_text="Dollars: 0",
                ),
            )
        )
    state, terminal = _run_transcript(plugin, family_case, turns)
    assert terminal["reason"] == "iteration_cap"
    scores = _score_both_seats(plugin, bridge, family_case, state, terminal)

    assert scores["red"].primary.value == 0.0
    assert scores["blue"].primary.value == 0.0
    assert scores["agreement"].primary.value == 0.0
