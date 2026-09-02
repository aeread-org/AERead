"""Component-level parity harness for negarena's golden-1 transcripts (spec
section 5, "the tau3 parity.py pattern").

For golden 1 in each family (``negarena.buy_sell.0``, ``negarena.ultimatum.0``)
this module runs the identical, ordered scripted transcript two independent
ways:

* **adapter**: driven through the real Mode B phase graph
  (``NegarenaPlugin.parse_action``/``legal``/``step``, exactly the pattern
  ``tests/test_negarena_environment.py``'s golden-1 tests already use), then
  scored through ``measurement.build_scorer(...).score_seat_outcome(...)``
  -- the real kernel-facing path, which itself delegates settlement to
  ``NegarenaBridge.settle``'s two-synthetic-entry shortcut (spec section 3:
  "settlement computation ... executed via the bridge, never
  reimplemented").
* **upstream_direct**: the identical ordered raw response text, replayed
  through upstream's OWN turn loop via
  ``NegarenaBridge.replay_transcript`` (``write_game_state``/``game_over``/
  ``after_game_ends``, upstream's real code, called independently) --
  never touching ``environment.py``/``measurement.py`` at all.

Both sides ultimately call upstream's real ``after_game_ends()``, but via
two independently constructed ``game_state`` histories, so a byte-identical
``player_outcome`` between them is genuine parity evidence, not a
tautology (spec section 5: "require byte-identical player_outcome").
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aeread.shared_runner.scheduler import ActionEnvelope

from . import measurement as measurement_module
from .cases import BLUE, RED
from .environment import BLUE_PHASE, RED_PHASE, NegarenaPlugin
from .negarena_bridge import NegarenaBridge


def _scripted_buy_sell_response(
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


def _scripted_ultimatum_response(
    *, answer: str, trade_text: str, resources_text: str
) -> str:
    return (
        "<move> 1 </move>\n"
        f"<my resources> {resources_text} </my resources>\n"
        f"<player answer> {answer} </player answer>\n"
        "<reason> r </reason>\n"
        "<message> m </message>\n"
        f"<newly proposed trade> {trade_text} </newly proposed trade>"
    )


@dataclass(frozen=True, slots=True)
class GoldenOneTranscript:
    """One golden-1 scripted transcript: ordered ``(seat_id, response_text)``."""

    family_case: Mapping[str, Any]
    turns: tuple[tuple[str, str], ...]


def build_buy_sell_golden_one(family_case: Mapping[str, Any]) -> GoldenOneTranscript:
    """Reproduces upstream's own shipped
    ``example_logs/buysell/1707347676639/`` transcript verbatim (spec
    section 4 golden 1): proposals ``50->30->45->35->42->38->40``, then
    BLUE ``ACCEPT``s.
    """
    offers = (50, 30, 45, 35, 42, 38, 40)
    turns: list[tuple[str, str]] = []
    for index, price in enumerate(offers):
        seat = RED if index % 2 == 0 else BLUE
        resources_text = "X: 1" if seat == RED else "ZUP: 1000"
        turns.append(
            (
                seat,
                _scripted_buy_sell_response(
                    f"Player RED Gives X: 1 | Player BLUE Gives ZUP: {price}",
                    resources_text=resources_text,
                ),
            )
        )
    turns.append((BLUE, _scripted_buy_sell_response("NONE", answer="ACCEPT", resources_text="ZUP: 1000")))
    return GoldenOneTranscript(family_case=family_case, turns=tuple(turns))


def build_ultimatum_golden_one(family_case: Mapping[str, Any]) -> GoldenOneTranscript:
    """The ultimatum analogue of golden 1 (spec section 4): the reference
    scenario reaching ``ACCEPT`` -- RED proposes a split, BLUE accepts.
    """
    turns = (
        (
            RED,
            _scripted_ultimatum_response(
                answer="PROPOSAL",
                trade_text="Player RED Gives Dollars: 40 | Player BLUE Gives Dollars: 0",
                resources_text="Dollars: 100",
            ),
        ),
        (
            BLUE,
            _scripted_ultimatum_response(
                answer="ACCEPT", trade_text="NONE", resources_text="Dollars: 0"
            ),
        ),
    )
    return GoldenOneTranscript(family_case=family_case, turns=turns)


@dataclass(frozen=True, slots=True)
class ParityResult:
    """Component-level comparison result for one golden-1 transcript."""

    game_kind: str
    adapter_player_outcome: tuple[float, ...]
    upstream_direct_player_outcome: tuple[float, ...]
    adapter_final_response: str
    upstream_direct_final_response: str

    @property
    def matched(self) -> bool:
        return (
            self.adapter_player_outcome == self.upstream_direct_player_outcome
            and self.adapter_final_response == self.upstream_direct_final_response
        )


def _run_adapter(
    plugin: NegarenaPlugin, transcript: GoldenOneTranscript, *, bridge: NegarenaBridge
) -> tuple[tuple[float, ...], str]:
    """The real kernel-facing path: phase graph + measurement.py scorer."""
    family_case = transcript.family_case
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    state = plugin.initial_state(family_case, None)
    terminal: Mapping[str, Any] | None = None
    for seat_id, response_text in transcript.turns:
        phase = phases[RED_PHASE if seat_id == RED else BLUE_PHASE]
        parsed = plugin.parse_action(
            family_case, state, seat_id, phase, {"response": response_text}
        )
        if not parsed.ok:
            envelope = ActionEnvelope(
                seat_id=seat_id, valid=False, action=None, parse=parsed, legality=None
            )
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
    if terminal is None:
        raise ValueError("golden-1 transcript did not terminate the episode")

    scorer = plugin.build_scorer(family_case)
    red_score = scorer.score_seat_outcome(
        bridge=bridge, state=state, terminal=terminal, seat_id=RED, opponent_policy_id="scripted"
    )
    blue_score = scorer.score_seat_outcome(
        bridge=bridge, state=state, terminal=terminal, seat_id=BLUE, opponent_policy_id="scripted"
    )
    assert red_score.primary is not None and blue_score.primary is not None
    return (red_score.primary.value, blue_score.primary.value), terminal["last_answer"]


def _run_upstream_direct(
    transcript: GoldenOneTranscript, *, bridge: NegarenaBridge
) -> tuple[tuple[float, ...], str]:
    """The independent path: upstream's own turn loop, never touching the
    adapter's ``environment.py``/``measurement.py`` code."""
    scenario = transcript.family_case["scenario"]
    raw_turns = [text for _seat, text in transcript.turns]
    result = bridge.replay_transcript(
        game_kind=scenario["game_kind"], scenario=scenario, turns=raw_turns
    )
    if not result["settled"]:
        raise ValueError(f"upstream-direct replay produced no settlement: {result['reason']}")
    outcome = tuple(
        measurement_module.native_outcome_value(entry) for entry in result["player_outcome"]
    )
    return outcome, result["final_response"]


def run_golden_one_parity(
    plugin: NegarenaPlugin, transcript: GoldenOneTranscript, *, bridge: NegarenaBridge
) -> ParityResult:
    """Run and compare golden 1 for one family; never raises for a mismatch
    (the caller asserts on ``ParityResult.matched``)."""
    adapter_outcome, adapter_final = _run_adapter(plugin, transcript, bridge=bridge)
    upstream_outcome, upstream_final = _run_upstream_direct(transcript, bridge=bridge)
    scenario = transcript.family_case["scenario"]
    return ParityResult(
        game_kind=scenario["game_kind"],
        adapter_player_outcome=adapter_outcome,
        upstream_direct_player_outcome=upstream_outcome,
        adapter_final_response=adapter_final,
        upstream_direct_final_response=upstream_final,
    )


__all__ = [
    "GoldenOneTranscript",
    "ParityResult",
    "build_buy_sell_golden_one",
    "build_ultimatum_golden_one",
    "run_golden_one_parity",
]
