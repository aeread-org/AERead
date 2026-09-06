"""Tests for the negarena environment: registration, phase graph, and the
scripted-golden mechanics from docs/negarena_adapter_spec.md section 4.

Bridge-dependent tests (parse_action/legal, which delegate to upstream's own
parser and admission-gate methods) skip cleanly when no provisioned bridge
interpreter is available -- mirroring tests/test_tau3_retail_cases.py's
``allow_module_level`` skip convention. Provision one with
``tools/negarena_bridge/provision.sh``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from aeread.shared_runner.registry import IncompletePluginError, PluginRegistry
from aeread.shared_runner.task.scheduler import ActionEnvelope, LegalityResult, ParseResult
from aeread_families.negarena import cases as negarena_cases
from aeread_families.negarena.environment import (
    BLUE_PHASE,
    RED_PHASE,
    NegarenaPlugin,
    family_manifest,
    register_plugin,
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
        pytest.skip(
            f"pinned upstream NegotiationArena checkout not found at {UPSTREAM_ROOT}",
            allow_module_level=False,
        )
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


def _scripted_response(
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


def _act(plugin: NegarenaPlugin, family_case, state, seat: str, phase, text: str):
    """Run one full parse -> legal -> step cycle; returns the transition."""
    parsed = plugin.parse_action(family_case, state, seat, phase, {"response": text})
    if not parsed.ok:
        envelope = ActionEnvelope(seat_id=seat, valid=False, action=None, parse=parsed, legality=None)
        return parsed, None, plugin.step(family_case, state, phase, {seat: envelope})
    legality = plugin.legal(family_case, state, seat, phase, parsed.action)
    envelope = ActionEnvelope(
        seat_id=seat,
        valid=legality.legal,
        action=parsed.action if legality.legal else None,
        parse=parsed,
        legality=legality,
    )
    transition = plugin.step(family_case, state, phase, {seat: envelope})
    return parsed, legality, transition


# ---------------------------------------------------------------------------
# Registration / family manifest / phase graph (no bridge required).
# ---------------------------------------------------------------------------


def test_family_manifest_declares_mode_b_two_seat_alternation() -> None:
    manifest = family_manifest()
    assert manifest.family.id == "negarena"
    assert manifest.environment.phase_specs == (RED_PHASE, BLUE_PHASE)
    assert manifest.environment.needs_tools is False
    assert set(manifest.roles) == {"red", "blue"}
    assert manifest.measurement.measurement_kind == "comparative_or_human_judged"
    assert manifest.measurement.direction == "maximize"


def test_family_manifest_declares_both_leaves_with_seat_outcome_primary() -> None:
    """kernel_scoring_contract_spec.md section 3: the manifest, not the
    scorer or a test fixture, is the one source of the leaf set, the
    primary, and admission membership. See docs/negarena_adapter_status.md's
    "Leaf policy" section for why `negarena_seat_outcome` is primary and why
    it alone gates admission.

    Mutation-verified: removing either leaf's dict from `family_manifest`'s
    `measurement.leaves` (or changing `primary_leaf_id`/`admission_leaf_ids`)
    fails this test's `set(declared.leaf_ids)`/`primary_leaf_id`/
    `admission_leaf_ids` assertions directly.
    """
    from aeread_families.negarena import measurement

    manifest = family_manifest()
    declared = manifest.measurement.finalize_time_leaf_policy()

    assert set(declared.leaf_ids) == {
        measurement.SEAT_OUTCOME_LEAF_ID,
        measurement.AGREEMENT_LEAF_ID,
    }
    assert declared.primary_leaf_id == measurement.SEAT_OUTCOME_LEAF_ID
    assert declared.admission_leaf_ids == (measurement.SEAT_OUTCOME_LEAF_ID,)
    # Neither leaf waits on a judge verdict or any other not-yet-existing
    # artifact -- every scorer in measurement.py is deterministic (spec
    # section 4); neither is `deferred`.
    assert all(leaf.scope == "finalize_time" for leaf in manifest.measurement.leaves)

    # Ruling R12: leaf 1's estimand is inherently per seat ("what did THIS
    # seat realize"), so it is declared seat_scope="subject_seat"; leaf 2 (a
    # single fact about the whole episode, not a function of which seat is
    # the tested subject) stays the default seat_scope="cell".
    leaves_by_id = {leaf.leaf_id: leaf for leaf in manifest.measurement.leaves}
    assert leaves_by_id[measurement.SEAT_OUTCOME_LEAF_ID].seat_scope == "subject_seat"
    assert leaves_by_id[measurement.AGREEMENT_LEAF_ID].seat_scope == "cell"


def test_register_plugin_succeeds_against_the_real_registry() -> None:
    registry = PluginRegistry()
    plugin = NegarenaPlugin(upstream_root=UPSTREAM_ROOT, bridge=None)
    register_plugin(registry, plugin=plugin)
    registered = registry.registrations()
    assert len(registered) == 1
    assert registered[0].family_id == "negarena"
    assert registered[0].plugin_id == "negarena_environment"


def test_register_plugin_requires_every_hook_present() -> None:
    class Incomplete:
        def validate_payload(self, payload):
            return payload

    registry = PluginRegistry()
    with pytest.raises(IncompletePluginError):
        registry.register_trusted(family_manifest(), Incomplete())


def test_phases_are_mode_single_and_alternate_red_then_blue(plugin) -> None:
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    family_case = plugin.validate_payload(case["payload"])
    phases = plugin.phases(family_case)
    assert [phase.phase_id for phase in phases] == [RED_PHASE, BLUE_PHASE]
    for phase in phases:
        assert phase.mode == "single"
        assert phase.invalid_action_policy == "family_defined"
    assert phases[0].next_phases == (BLUE_PHASE,)
    assert phases[1].next_phases == (RED_PHASE,)


def test_build_scorer_returns_the_two_declared_leaves(plugin) -> None:
    # Milestone 2: build_scorer is wired to measurement.py (see
    # tests/test_negarena_measurement.py for the full scoring behaviour;
    # this only checks the hand-off itself).
    from aeread_families.negarena import measurement

    case = _load_case("negarena.buy_sell.0", "buy_sell")
    family_case = plugin.validate_payload(case["payload"])
    scorer = plugin.build_scorer(family_case)
    assert scorer.seat_outcome_leaf.leaf_id == measurement.SEAT_OUTCOME_LEAF_ID
    assert scorer.agreement_leaf.leaf_id == measurement.AGREEMENT_LEAF_ID


# ---------------------------------------------------------------------------
# validate_payload.
# ---------------------------------------------------------------------------


def test_validate_payload_accepts_every_authored_case(plugin) -> None:
    _pins, authored = negarena_cases.author_all_cases()
    for case in authored.values():
        family_case = plugin.validate_payload(case["payload"])
        assert family_case["scenario"]["game_kind"] in {"buy_sell", "ultimatum"}


def test_validate_payload_rejects_wrong_upstream_commit(plugin) -> None:
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    payload = json.loads(json.dumps(case["payload"]))
    payload["pins"]["upstream_commit"] = "0" * 40
    with pytest.raises(ValueError, match="wrong upstream commit"):
        plugin.validate_payload(payload)


def test_validate_payload_rejects_seats_missing_a_color(plugin) -> None:
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    payload = json.loads(json.dumps(case["payload"]))
    del payload["scenario"]["seats"]["blue"]
    with pytest.raises(ValueError, match="red and blue"):
        plugin.validate_payload(payload)


def test_validate_payload_rejects_a_nonzero_blue_ultimatum_endowment(plugin) -> None:
    """Regression for docs/negarena_review_claude.md WARNING-2.

    Upstream's after_game_ends() reports RED's outcome as its absolute
    final holdings but BLUE's as a *delta* from BLUE's own starting
    holdings; the two are only comparable under the same head_to_head
    estimand when BLUE starts at 0. Every authored case does, but nothing
    used to stop a future one from silently reintroducing the asymmetry.
    """
    case = _load_case("negarena.ultimatum.0", "ultimatum")
    payload = json.loads(json.dumps(case["payload"]))
    payload["scenario"]["seats"]["blue"]["starting_resources"]["Dollars"] = 10
    with pytest.raises(ValueError, match="starting_resources.Dollars must be 0"):
        plugin.validate_payload(payload)


# ---------------------------------------------------------------------------
# Golden 1 -- successful (spec section 4): reproduces upstream's own shipped
# example_logs/buysell/1707347676639/ transcript turn-for-turn.
# ---------------------------------------------------------------------------


def test_golden_1_successful_buy_sell_reference_transcript(plugin) -> None:
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    family_case = plugin.validate_payload(case["payload"])
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    state = plugin.initial_state(family_case, None)

    offers = [50, 30, 45, 35, 42, 38, 40]
    for index, price in enumerate(offers):
        seat = "red" if index % 2 == 0 else "blue"
        phase = phases[RED_PHASE if seat == "red" else BLUE_PHASE]
        resources_text = "X: 1" if seat == "red" else "ZUP: 1000"
        text = _scripted_response(
            f"Player RED Gives X: 1 | Player BLUE Gives ZUP: {price}",
            resources_text=resources_text,
        )
        parsed, legality, transition = _act(plugin, family_case, state, seat, phase, text)
        assert parsed.ok
        assert legality.legal
        state = transition.state
        assert transition.next_phase_id is not None

    # Turn 8: BLUE accepts.
    phase = phases[BLUE_PHASE]
    text = _scripted_response("NONE", answer="ACCEPT", resources_text="ZUP: 1000")
    parsed, legality, transition = _act(plugin, family_case, state, "blue", phase, text)
    assert parsed.ok
    assert legality.legal
    assert transition.next_phase_id is None
    state = transition.state

    terminal = plugin.terminal(family_case, state)
    assert terminal["reason"] == "accepted"
    assert terminal["iteration_count"] == 8
    # Upstream's own after_game_ends() reads the ACCEPTED trade from the turn
    # *before* the accept turn (game_state[-2]); this is the same lookup.
    accepted_trade = state["history"][-2]["public"]["newly proposed trade"]
    assert accepted_trade["as_text"] == "Player RED Gives X: 1 | Player BLUE Gives ZUP: 40"

    outcome = plugin.outcome(family_case, terminal)
    assert outcome["termination_reason"] == "accepted"


# ---------------------------------------------------------------------------
# Golden 2 -- valid-but-poor: fully legal, completes normally, bad outcome.
# ---------------------------------------------------------------------------


def test_golden_2_valid_but_poor_red_accepts_a_lowball(plugin) -> None:
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    family_case = plugin.validate_payload(case["payload"])
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    state = plugin.initial_state(family_case, None)

    text = _scripted_response("Player RED Gives X: 1 | Player BLUE Gives ZUP: 50")
    parsed, legality, transition = _act(plugin, family_case, state, "red", phases[RED_PHASE], text)
    assert parsed.ok and legality.legal
    state = transition.state

    text = _scripted_response(
        "Player RED Gives X: 1 | Player BLUE Gives ZUP: 20",
        resources_text="ZUP: 1000",
    )
    parsed, legality, transition = _act(plugin, family_case, state, "blue", phases[BLUE_PHASE], text)
    assert parsed.ok and legality.legal
    state = transition.state

    text = _scripted_response("NONE", answer="ACCEPT")
    parsed, legality, transition = _act(plugin, family_case, state, "red", phases[RED_PHASE], text)
    assert parsed.ok and legality.legal
    assert transition.next_phase_id is None
    terminal = plugin.terminal(family_case, transition.state)
    assert terminal["reason"] == "accepted"
    accepted_trade = transition.state["history"][-2]["public"]["newly proposed trade"]
    assert accepted_trade["as_text"] == "Player RED Gives X: 1 | Player BLUE Gives ZUP: 20"


# ---------------------------------------------------------------------------
# Golden 3 -- invalid-unauthorized (spec section 4).
# ---------------------------------------------------------------------------


def test_golden_3_invalid_unauthorized_trade_is_caught_by_the_admission_gate(
    plugin,
) -> None:
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    family_case = plugin.validate_payload(case["payload"])
    phase = plugin.phases(family_case)[0]
    state = plugin.initial_state(family_case, None)

    # RED holds only {X: 1} but proposes giving X: 5.
    text = _scripted_response("Player RED Gives X: 5 | Player BLUE Gives ZUP: 100")
    parsed = plugin.parse_action(family_case, state, "red", phase, {"response": text})
    assert parsed.ok
    legality = plugin.legal(family_case, state, "red", phase, parsed.action)
    assert not legality.legal
    assert legality.reason == "invalid_measurement"

    envelope = ActionEnvelope(seat_id="red", valid=False, action=None, parse=parsed, legality=legality)
    transition = plugin.step(family_case, state, phase, {"red": envelope})
    assert transition.next_phase_id is None
    terminal = plugin.terminal(family_case, transition.state)
    assert terminal["reason"] == "invalid_measurement"


def test_golden_3_analogue_ultimatum_proposer_offers_more_than_held(plugin) -> None:
    case = _load_case("negarena.ultimatum.0", "ultimatum")
    family_case = plugin.validate_payload(case["payload"])
    phase = plugin.phases(family_case)[0]
    state = plugin.initial_state(family_case, None)

    # RED holds Dollars: 100 but proposes giving Dollars: 150.
    text = (
        "<move> 1 </move>\n"
        "<my resources> Dollars: 100 </my resources>\n"
        "<player answer> PROPOSAL </player answer>\n"
        "<reason> r </reason>\n"
        "<message> m </message>\n"
        "<newly proposed trade> Player RED Gives Dollars: 150 | Player BLUE Gives Dollars: 0 "
        "</newly proposed trade>"
    )
    parsed = plugin.parse_action(family_case, state, "red", phase, {"response": text})
    assert parsed.ok
    legality = plugin.legal(family_case, state, "red", phase, parsed.action)
    assert not legality.legal
    assert legality.reason == "invalid_measurement"


# ---------------------------------------------------------------------------
# Golden 4 -- malformed-operational (spec section 4).
# ---------------------------------------------------------------------------


def test_golden_4_malformed_trade_text_is_caught_not_a_crash(plugin) -> None:
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    family_case = plugin.validate_payload(case["payload"])
    phase = plugin.phases(family_case)[0]
    state = plugin.initial_state(family_case, None)

    text = _scripted_response("this is not a legal trade grammar at all")
    parsed = plugin.parse_action(family_case, state, "red", phase, {"response": text})
    assert not parsed.ok
    assert parsed.error_code == "malformed_action"

    envelope = ActionEnvelope(seat_id="red", valid=False, action=None, parse=parsed, legality=None)
    transition = plugin.step(family_case, state, phase, {"red": envelope})
    assert transition.next_phase_id is None
    terminal = plugin.terminal(family_case, transition.state)
    assert terminal["reason"] == "malformed_action"


def test_golden_4_missing_trade_tag_is_caught_not_a_crash(plugin) -> None:
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    family_case = plugin.validate_payload(case["payload"])
    phase = plugin.phases(family_case)[0]
    state = plugin.initial_state(family_case, None)

    # No <newly proposed trade> tag at all.
    text = (
        "<message> negotiating </message>\n"
        "<player answer> PROPOSAL </player answer>\n"
        "<my resources> X: 1 </my resources>\n"
        "<my goals> goal </my goals>\n"
        "<reason> r </reason>\n"
        "<proposal count> 1 </proposal count>"
    )
    parsed = plugin.parse_action(family_case, state, "red", phase, {"response": text})
    assert not parsed.ok
    assert parsed.error_code == "malformed_action"


def test_golden_4_missing_player_answer_tag_is_caught_not_a_crash(plugin) -> None:
    """Regression for docs/negarena_review_claude.md CRITICAL-1.

    Upstream's own ``get_tag_indices`` (``negotiationarena/utils.py``) never
    raises on an absent tag -- it returns ``-1``/``-1`` and the resulting
    slice is a garbage substring of the surrounding response, silently
    populated into ``public["player answer"]`` -- so a response missing
    *any* required tag other than the trade tag used to parse through as a
    clean, legal, non-terminal turn instead of being flagged
    ``malformed_action``.
    """
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    family_case = plugin.validate_payload(case["payload"])
    phase = plugin.phases(family_case)[0]
    state = plugin.initial_state(family_case, None)

    # Well-formed <message>/<newly proposed trade>/<my resources>, but no
    # <player answer> tag at all.
    text = (
        "<message> hi </message>\n"
        "<newly proposed trade> Player RED Gives X: 1 | Player BLUE Gives ZUP: 40 "
        "</newly proposed trade>\n"
        "<my resources> X: 1 </my resources>\n"
        "<my goals> goal </my goals>\n"
        "<reason> r </reason>\n"
        "<proposal count> 1 </proposal count>"
    )
    parsed = plugin.parse_action(family_case, state, "red", phase, {"response": text})
    assert not parsed.ok
    assert parsed.error_code == "malformed_action"

    envelope = ActionEnvelope(seat_id="red", valid=False, action=None, parse=parsed, legality=None)
    transition = plugin.step(family_case, state, phase, {"red": envelope})
    assert transition.next_phase_id is None
    terminal = plugin.terminal(family_case, transition.state)
    assert terminal["reason"] == "malformed_action"


def test_golden_4_missing_player_answer_tag_is_caught_for_ultimatum_too(plugin) -> None:
    """Same regression as above, for the other family split (ultimatum)."""
    case = _load_case("negarena.ultimatum.0", "ultimatum")
    family_case = plugin.validate_payload(case["payload"])
    phase = plugin.phases(family_case)[0]
    state = plugin.initial_state(family_case, None)

    # No <player answer> tag at all.
    text = (
        "<move> 1 </move>\n"
        "<my resources> Dollars: 100 </my resources>\n"
        "<reason> r </reason>\n"
        "<message> m </message>\n"
        "<newly proposed trade> Player RED Gives Dollars: 40 | Player BLUE Gives Dollars: 0 "
        "</newly proposed trade>"
    )
    parsed = plugin.parse_action(family_case, state, "red", phase, {"response": text})
    assert not parsed.ok
    assert parsed.error_code == "malformed_action"


# ---------------------------------------------------------------------------
# Golden 5 -- degenerate-reference (spec section 4).
# ---------------------------------------------------------------------------


def test_golden_5_no_zopa_never_accepts_through_the_iteration_cap(plugin) -> None:
    case = _load_case("negarena.buy_sell.2", "buy_sell")
    family_case = plugin.validate_payload(case["payload"])
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    state = plugin.initial_state(family_case, None)

    seat_cycle = ["red", "blue"]
    transition = None
    for index in range(10):
        seat = seat_cycle[index % 2]
        phase = phases[RED_PHASE if seat == "red" else BLUE_PHASE]
        resources_text = "X: 1" if seat == "red" else "ZUP: 1000"
        text = _scripted_response(
            f"Player RED Gives X: 1 | Player BLUE Gives ZUP: {50 + index}",
            resources_text=resources_text,
        )
        parsed, legality, transition = _act(plugin, family_case, state, seat, phase, text)
        assert parsed.ok and legality.legal
        state = transition.state
        if transition.next_phase_id is None:
            break

    terminal = plugin.terminal(family_case, state)
    assert terminal["reason"] == "iteration_cap"
    assert terminal["iteration_count"] == 10


def test_golden_5_analogue_ultimatum_degenerate_zero_endowment_still_admits(
    plugin,
) -> None:
    case = _load_case("negarena.ultimatum.2", "ultimatum")
    family_case = plugin.validate_payload(case["payload"])
    phase = plugin.phases(family_case)[0]
    state = plugin.initial_state(family_case, None)

    # Both seats hold Dollars: 0; the only legal proposal is the empty split.
    text = (
        "<move> 1 </move>\n"
        "<my resources> Dollars: 0 </my resources>\n"
        "<player answer> PROPOSAL </player answer>\n"
        "<reason> r </reason>\n"
        "<message> m </message>\n"
        "<newly proposed trade> Player RED Gives Dollars: 0 | Player BLUE Gives Dollars: 0 "
        "</newly proposed trade>"
    )
    parsed = plugin.parse_action(family_case, state, "red", phase, {"response": text})
    assert parsed.ok
    legality = plugin.legal(family_case, state, "red", phase, parsed.action)
    assert legality.legal


# ---------------------------------------------------------------------------
# Ultimatum reference scenario: early accept, early reject, and REJECT is a
# split-only-in-ultimatum termination reason (unlike buy_sell).
# ---------------------------------------------------------------------------


def _ultimatum_turn(plugin, family_case, state, phase, seat, *, answer, trade_text):
    text = (
        "<move> 1 </move>\n"
        f"<my resources> Dollars: {100 if seat == 'red' else 0} </my resources>\n"
        f"<player answer> {answer} </player answer>\n"
        "<reason> r </reason>\n"
        "<message> m </message>\n"
        f"<newly proposed trade> {trade_text} </newly proposed trade>"
    )
    return _act(plugin, family_case, state, seat, phase, text)


def test_ultimatum_reference_scenario_reaches_accepted(plugin) -> None:
    case = _load_case("negarena.ultimatum.0", "ultimatum")
    family_case = plugin.validate_payload(case["payload"])
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    state = plugin.initial_state(family_case, None)

    _parsed, _legality, transition = _ultimatum_turn(
        plugin, family_case, state, phases[RED_PHASE], "red",
        answer="PROPOSAL",
        trade_text="Player RED Gives Dollars: 40 | Player BLUE Gives Dollars: 0",
    )
    state = transition.state
    assert transition.next_phase_id == BLUE_PHASE

    _parsed, _legality, transition = _ultimatum_turn(
        plugin, family_case, state, phases[BLUE_PHASE], "blue",
        answer="ACCEPT", trade_text="NONE",
    )
    assert transition.next_phase_id is None
    terminal = plugin.terminal(family_case, transition.state)
    assert terminal["reason"] == "accepted"


def test_ultimatum_reject_ends_the_episode_but_buy_sell_reject_does_not(plugin) -> None:
    ultimatum_case = _load_case("negarena.ultimatum.0", "ultimatum")
    ultimatum_family_case = plugin.validate_payload(ultimatum_case["payload"])
    phase = plugin.phases(ultimatum_family_case)[0]
    state = plugin.initial_state(ultimatum_family_case, None)
    _parsed, _legality, transition = _ultimatum_turn(
        plugin, ultimatum_family_case, state, phase, "red",
        answer="REJECT", trade_text="NONE",
    )
    assert transition.next_phase_id is None
    terminal = plugin.terminal(ultimatum_family_case, transition.state)
    assert terminal["reason"] == "rejected"

    buy_sell_case = _load_case("negarena.buy_sell.0", "buy_sell")
    buy_sell_family_case = plugin.validate_payload(buy_sell_case["payload"])
    bs_phase = plugin.phases(buy_sell_family_case)[0]
    bs_state = plugin.initial_state(buy_sell_family_case, None)
    text = _scripted_response(
        "Player RED Gives X: 1 | Player BLUE Gives ZUP: 50", answer="REJECT"
    )
    _parsed, _legality, bs_transition = _act(
        plugin, buy_sell_family_case, bs_state, "red", bs_phase, text
    )
    # buy_sell's own game_over never checks for REJECT (upstream's own
    # "TODO: this is pretty buggy") -- the episode simply continues.
    assert bs_transition.next_phase_id == BLUE_PHASE
