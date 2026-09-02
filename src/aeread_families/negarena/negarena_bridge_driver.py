#!/usr/bin/env python
"""Subprocess driver for negarena's ``NegarenaBridge`` (see ``negarena_bridge.py``).

This script runs under a SEPARATE, already-provisioned Python interpreter
with upstream NegotiationArena's runtime dependencies (``openai``,
``anthropic``) installed. Source is always loaded from the caller-supplied
pinned checkout (commit ``c447fafd439a20b84cdedeb2f8a85c4fad764745``), never
from an unrelated negotiationarena distribution installed in that
interpreter. Nothing is installed or fetched by this script (no network
calls -- see the adapter spec's rule 2).

It exists so ``environment.py`` -- which runs inside AERead's own project
venv, which deliberately does not carry ``openai``/``anthropic`` -- can
delegate every scripted-response parse and every trade-legality check to the
real upstream implementation instead of reimplementing it (spec section 3:
"upstream owns ... the scripted-response tag grammar the parsers expect ...
and the parser classes themselves"; "AEREAD owns ... the trade-legality
admission gate ... delegated, not reimplemented"). Nothing about tag-parsing
or trade-legality logic is ever hand-derived here; every op below calls
straight into upstream's own parser classes (``BuySellGameDefaultParser``,
``UltimatumGameDefaultParser``) or game-object methods (``Trade.can_offer``,
``Trade.can_accept``, ``Resources.check_transaction_legal``).

This file must not import anything from the ``aeread`` package: it is
invoked as a standalone script under a *different* Python interpreter that
does not have ``aeread`` on its path.

A second, independent upstream defect (see docs/negarena_adapter_spec.md's
"Correction" note and ledger_entries/negarena.md): ``games/ultimatum/
interface.py`` references ``negotiationarena.agent_message.
AgentMessageInterface``, which does not exist at this pin -- only
``AgentMessage`` does. ``_make_ultimatum_importable`` works around it with a
documented compatibility alias set on the already-imported module object,
never touching the read-only upstream checkout.

Protocol -- exactly one JSON object read from stdin, exactly one JSON object
written to stdout:

  {"op": "runtime_info"}
      -> {"ok": true, "python_version": str, "negotiationarena_package_file": str}

  {"op": "parse_response", "game_kind": "buy_sell"|"ultimatum", "response": str}
      -> {"ok": true, "parsed": true, "public": {...}, "secret": {...}}
      -- delegates to ``BuySellGameDefaultParser().parse(response)`` /
         ``UltimatumGameDefaultParser().parse(response)``
         (``negotiationarena.agent_message.AgentMessage``'s ``.public``/
         ``.secret`` dicts). A parsed ``<newly proposed trade>`` value is
         rendered as ``{"kind": "proposal", "give": {agent_label:
         resource_dict, ...}, "as_text": str(trade)}`` (json-safe; "give"'s
         shape is exactly ``Trade``'s own constructor input, so it can be
         round-tripped straight back into ``op=check_trade`` below without
         this driver inventing any new representation); a refused/no-trade
         tag value (upstream's ``"NONE"`` sentinel) is
         ``{"kind": "none"}``. A parsed ``<my resources>`` value is
         flattened from a ``Resources`` object to its own ``resource_dict``.
      -> {"ok": true, "parsed": false, "parse_error_type": str,
          "parse_error_message": str}
      -- upstream's own parser raised (``write_game_state``'s real
         behavior at this pin is to re-raise on an unparseable response --
         see the adapter spec's governing facts); this is a normal, in-band,
         ``ok=true`` response, never an exception, exactly mirroring
         tau2_bridge_driver.py's "a tool-level error is not an infra
         failure" convention. The caller (``environment.py``) turns this
         into ``malformed_action``, never lets the process crash.
      -- also returned (``parse_error_type": "missing_required_tag"``) when
         upstream's own ``get_tag_indices`` (``negotiationarena/utils.py``)
         reports a required tag absent from the raw response. Upstream's
         parsers never raise in this case -- ``get_tag_indices`` returns
         ``-1``/``-1`` and the subsequent slice silently yields a garbage
         substring instead (docs/negarena_review_claude.md CRITICAL-1;
         reproduced live: a response missing ``<player answer>`` parsed
         clean with a garbage ``"player answer"`` value). Checked here,
         before ``parser.parse()`` runs, by calling upstream's own
         ``get_tag_indices`` directly on every tag its parser unconditionally
         extracts for this ``game_kind`` -- never a hand-rolled tag grammar.

  {"op": "check_trade", "direction": "offer"|"accept",
   "give": {agent_label: resource_dict, agent_label: resource_dict},
   "resources": resource_dict}
      -> {"ok": true, "legal": bool}
      -- delegates to ``Trade(give).can_offer(Resources(resources))`` (when
         ``direction == "offer"``) or ``Trade(give).can_accept(...)`` (when
         ``direction == "accept"``), which upstream itself never calls
         before ``execute_trade`` (the adapter-owned admission gate, spec
         section 3).

  {"op": "settle", "game_kind": "buy_sell"|"ultimatum", "scenario": {...
   same shape as a case's payload.scenario...}, "iteration_count": int,
   "final_answer": str, "proposed_trade": {agent_label: resource_dict,
   agent_label: resource_dict} | null}
      -> {"ok": true, "settled": true, "player_outcome": [entry, entry],
          "final_resources": [resource_json, resource_json],
          "final_response": str}
      -> {"ok": true, "settled": false, "reason": str}
      -- measurement.py's production settlement path (spec section 2:
         "settlement computation (after_game_ends()), executed via the
         bridge, never reimplemented"). Constructs upstream's own
         ``BuySellGame``/``MultiTurnUltimatumGame`` from ``scenario`` (the
         real constructor -- goals, resources, iterations -- exactly as
         ``runner/buysell_main.py``/``runner/ultimatum_main.py`` do), then
         appends exactly the two ``game_state`` entries
         ``after_game_ends()`` itself reads (``game_state[-2]``'s
         ``newly proposed trade``, ``game_state[-1]``'s ``player answer``)
         and calls upstream's own ``after_game_ends()`` -- never
         recomputing ``Trade.execute_trade``/``Valuation.value`` locally.
         ``settled=false`` mirrors ``BuySellGame.after_game_ends()``'s own
         single-iteration short-circuit (``int(end_state[...]) <= 1``),
         which appends no ``"summary"`` key at all.
         Each ``player_outcome``/``final_resources`` entry is a typed
         ``{"kind": "scalar", "value": float}`` (buy_sell -- ``Valuation``
         already reduces to one number) or ``{"kind": "resources", "value":
         resource_dict}`` (ultimatum -- ``UltimatumGoal`` has no
         ``Valuation``, so ``after_game_ends()``'s own ``outcome`` list
         holds raw ``Resources`` objects; see this module's
         ``_outcome_json``).

  {"op": "replay_transcript", "game_kind": "buy_sell"|"ultimatum",
   "scenario": {...}, "turns": [raw_response_text, ...]}
      -> {"ok": true, "settled": true, "player_outcome": [...],
          "final_resources": [...], "final_response": str}
      -> {"ok": true, "settled": false, "reason": str}
      -> {"ok": false, "error_type": "replay_incomplete", "message": str}
      -- parity-only path (spec section 5): replays the identical ordered
         raw scripted response text through upstream's OWN turn loop --
         ``AlternatingGame.write_game_state`` (upstream's real parser,
         called again, independently of ``environment.py``'s
         ``parse_response`` bridge calls) then ``game_over()``, mirroring
         ``AlternatingGame.run()``'s loop body verbatim minus the
         ``players[turn].step()`` call (the raw text is already given) --
         then ``after_game_ends()``. Never touches ``op=settle``'s
         two-entry shortcut, so a match between the two ops' outputs on the
         same transcript is real parity evidence, not a tautology.

  Anything else (bad op, malformed request, import failure, ...)
      -> {"ok": false, "error_type": str, "message": str}, exit code 1.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


def _make_upstream_importable(upstream_root: str | None) -> None:
    """Ensure ``import negotiationarena`` / ``import games`` resolve to the
    pinned checkout.

    Unlike tau2's bridge driver, upstream negarena has no ``src/`` layout --
    ``negotiationarena`` and ``games`` are top-level packages directly under
    the checkout root.
    """
    if upstream_root:
        root_dir = str(Path(upstream_root).resolve())
        sys.path[:] = [entry for entry in sys.path if entry != root_dir]
        sys.path.insert(0, root_dir)
    import negotiationarena

    if upstream_root:
        expected_package = (Path(upstream_root) / "negotiationarena").resolve()
        loaded_file = Path(negotiationarena.__file__).resolve()
        if not loaded_file.is_relative_to(expected_package):
            raise RuntimeError(
                "negotiationarena import did not resolve under the requested "
                f"pinned checkout: loaded {loaded_file}, expected under "
                f"{expected_package}"
            )


def _apply_agent_message_interface_alias() -> None:
    """Work around upstream's own ``AgentMessageInterface``/``AgentMessage``
    naming defect (see this module's docstring and
    ``docs/negarena_adapter_spec.md``'s "Correction" note).

    ``games/ultimatum/interface.py`` does
    ``from negotiationarena.agent_message import AgentMessageInterface`` at
    module scope; ``negotiationarena/agent_message.py`` at this exact pinned
    commit defines only ``AgentMessage``. This sets the missing name on the
    already-imported module object -- never edits the read-only upstream
    checkout, never redefines ``AgentMessage`` itself.
    """
    import negotiationarena.agent_message as agent_message_module

    if not hasattr(agent_message_module, "AgentMessageInterface"):
        agent_message_module.AgentMessageInterface = agent_message_module.AgentMessage


def _null_agent(agent_name: str) -> Any:
    """A minimal, scriptless ``Agent`` subclass -- never ``ChatGPTAgent``/
    ``ClaudeAgent`` (no key touched, spec section 5). Upstream's own
    ``BuySellGame``/``MultiTurnUltimatumGame`` constructors call
    ``init_players()`` -> ``Agent.init_agent()`` on every player
    unconditionally; this satisfies that unavoidable call without ever
    invoking ``.chat()``/``.think()`` -- settlement ops never call
    ``players[turn].step()``, since the scripted response text is always
    supplied directly (by the caller for ``op=settle``, from ``turns`` for
    ``op=replay_transcript``).
    """
    from negotiationarena.agents.agents import Agent

    class _NullAgent(Agent):
        def chat(self) -> str:
            raise NotImplementedError(
                "settlement replay never calls Agent.chat(); the scripted "
                "response text is supplied directly, never generated here"
            )

        def update_conversation_tracking(self, entity: str, message: str) -> None:
            pass

    return _NullAgent(agent_name)


def _buy_sell_seat_objects(seat: dict[str, Any]) -> tuple[Any, Any]:
    """One seat's ``(Goal, Resources)`` pair, mirroring
    ``runner/buysell_main.py``'s construction exactly."""
    from negotiationarena.game_objects.goal import BuyerGoal, SellerGoal
    from negotiationarena.game_objects.resource import Resources
    from negotiationarena.game_objects.valuation import Valuation

    resources = Resources(dict(seat["starting_resources"]))
    valuation = Valuation(dict(seat["valuation"]))
    if seat["goal_kind"] == "seller":
        goal: Any = SellerGoal(cost_of_production=valuation)
    elif seat["goal_kind"] == "buyer":
        goal = BuyerGoal(willingness_to_pay=valuation)
    else:
        raise ValueError(f"unknown buy_sell goal_kind: {seat['goal_kind']!r}")
    return goal, resources


def _build_buy_sell_game(scenario: dict[str, Any], log_dir: str) -> Any:
    from negotiationarena.constants import AGENT_ONE, AGENT_TWO
    from games.buy_sell_game.game import BuySellGame

    seats = scenario["seats"]
    red_goal, red_resources = _buy_sell_seat_objects(seats["red"])
    blue_goal, blue_resources = _buy_sell_seat_objects(seats["blue"])
    return BuySellGame(
        players=[_null_agent(AGENT_ONE), _null_agent(AGENT_TWO)],
        iterations=int(scenario["iterations"]),
        player_goals=[red_goal, blue_goal],
        player_starting_resources=[red_resources, blue_resources],
        player_conversation_roles=[f"You are {AGENT_ONE}.", f"You are {AGENT_TWO}."],
        player_social_behaviour=["", ""],
        log_dir=log_dir,
    )


def _build_ultimatum_game(scenario: dict[str, Any], log_dir: str) -> Any:
    # games/ultimatum/game.py imports games/ultimatum/interface.py, which
    # needs the AgentMessageInterface alias applied first (this module's
    # docstring / docs/negarena_adapter_spec.md's "Correction" note).
    _apply_agent_message_interface_alias()
    from negotiationarena.constants import AGENT_ONE, AGENT_TWO
    from negotiationarena.game_objects.goal import UltimatumGoal
    from negotiationarena.game_objects.resource import Resources
    from games.ultimatum.game import MultiTurnUltimatumGame

    seats = scenario["seats"]
    red_resources = Resources(dict(seats["red"]["starting_resources"]))
    blue_resources = Resources(dict(seats["blue"]["starting_resources"]))
    # Mirrors runner/ultimatum_main.py's own reference construction exactly.
    resources_support_set = Resources({scenario["money_token"]: 0})
    return MultiTurnUltimatumGame(
        players=[_null_agent(AGENT_ONE), _null_agent(AGENT_TWO)],
        iterations=int(scenario["iterations"]),
        resources_support_set=resources_support_set,
        player_goals=[UltimatumGoal(), UltimatumGoal()],
        player_initial_resources=[red_resources, blue_resources],
        player_social_behaviour=["", ""],
        player_roles=[f"You are {AGENT_ONE}.", f"You are {AGENT_TWO}."],
        log_dir=log_dir,
    )


def _build_game(game_kind: str, scenario: dict[str, Any], log_dir: str) -> Any:
    if game_kind == "buy_sell":
        return _build_buy_sell_game(scenario, log_dir)
    if game_kind == "ultimatum":
        return _build_ultimatum_game(scenario, log_dir)
    raise ValueError(f"unknown game_kind: {game_kind!r}")


def _parser_for(game_kind: str) -> Any:
    if game_kind == "buy_sell":
        from games.buy_sell_game.game import BuySellGameDefaultParser

        return BuySellGameDefaultParser()
    if game_kind == "ultimatum":
        _apply_agent_message_interface_alias()
        from games.ultimatum.interface import UltimatumGameDefaultParser

        return UltimatumGameDefaultParser()
    raise ValueError(f"unknown game_kind: {game_kind!r}")


def _trade_json(value: Any) -> dict[str, Any]:
    from negotiationarena.game_objects.trade import Trade

    if isinstance(value, Trade):
        return {
            "kind": "proposal",
            "give": {
                value.keys[0]: dict(value.resources_from_first_agent.resource_dict),
                value.keys[1]: dict(value.resources_from_second_agent.resource_dict),
            },
            "as_text": str(value),
        }
    # Upstream's REFUSING_OR_WAIT_TAG sentinel ("NONE"): no trade proposed
    # this turn.
    return {"kind": "none"}


def _resources_json(value: Any) -> Any:
    from negotiationarena.game_objects.resource import Resources

    if isinstance(value, Resources):
        return dict(value.resource_dict)
    return value


def _required_tags_for(game_kind: str) -> tuple[str, ...]:
    """The exact tag set upstream's own parser unconditionally extracts.

    Mirrors ``BuySellGameDefaultParser.parse``/``UltimatumGameDefaultParser.
    parse`` (``games/buy_sell_game/game.py``, ``games/ultimatum/
    interface.py``) call-for-call -- read directly from upstream source at
    the pinned commit, never guessed. Every one of these tags is extracted
    via ``get_tag_contents``/``get_tag_indices`` regardless of whether the
    tag is actually present in the raw response (docs/negarena_review_claude
    .md CRITICAL-1), which is exactly why presence has to be checked here
    first.
    """
    from negotiationarena.constants import (
        GOALS_TAG,
        MESSAGE_TAG,
        PLAYER_ANSWER_TAG,
        PROPOSAL_COUNT_TAG,
        PROPOSED_TRADE_TAG,
        REASONING_TAG,
        RESOURCES_TAG,
        TURN_OR_MOVE_TAG,
    )

    if game_kind == "buy_sell":
        return (
            RESOURCES_TAG,
            GOALS_TAG,
            REASONING_TAG,
            PLAYER_ANSWER_TAG,
            MESSAGE_TAG,
            PROPOSAL_COUNT_TAG,
            PROPOSED_TRADE_TAG,
        )
    if game_kind == "ultimatum":
        return (
            TURN_OR_MOVE_TAG,
            RESOURCES_TAG,
            PLAYER_ANSWER_TAG,
            REASONING_TAG,
            MESSAGE_TAG,
            PROPOSED_TRADE_TAG,
        )
    raise ValueError(f"unknown game_kind: {game_kind!r}")


def _op_parse_response(request: dict[str, Any]) -> dict[str, Any]:
    from negotiationarena.constants import PROPOSED_TRADE_TAG, RESOURCES_TAG
    from negotiationarena.utils import get_tag_indices

    game_kind = request.get("game_kind")
    response = request.get("response")
    if game_kind not in {"buy_sell", "ultimatum"}:
        return {
            "ok": False,
            "error_type": "bad_request",
            "message": f"unknown game_kind: {game_kind!r}",
        }
    if not isinstance(response, str):
        return {
            "ok": False,
            "error_type": "bad_request",
            "message": "response must be a string",
        }

    # Upstream's own tag-boundary lookup (``get_tag_indices``) returns
    # ``-1``/``-1`` -- never raises -- for an absent tag, and every required
    # tag is unconditionally extracted anyway, so a missing tag would
    # otherwise parse "clean" with a garbage value instead of surfacing as
    # malformed (docs/negarena_review_claude.md CRITICAL-1). Delegates to
    # upstream's own function, never a hand-rolled tag-presence check.
    for tag in _required_tags_for(game_kind):
        start_index, end_index, _ = get_tag_indices(response, tag)
        if start_index == -1 or end_index == -1:
            return {
                "ok": True,
                "parsed": False,
                "parse_error_type": "missing_required_tag",
                "parse_error_message": f"required tag <{tag}> not found in raw response",
            }

    parser = _parser_for(game_kind)
    try:
        message = parser.parse(response)
    except Exception as error:  # noqa: BLE001 - upstream's own parse failure, in-band
        return {
            "ok": True,
            "parsed": False,
            "parse_error_type": type(error).__name__,
            "parse_error_message": str(error),
        }

    public = dict(message.public)
    secret = dict(message.secret)
    if PROPOSED_TRADE_TAG in public:
        public[PROPOSED_TRADE_TAG] = _trade_json(public[PROPOSED_TRADE_TAG])
    if RESOURCES_TAG in secret:
        secret[RESOURCES_TAG] = _resources_json(secret[RESOURCES_TAG])
    return {"ok": True, "parsed": True, "public": public, "secret": secret}


def _op_check_trade(request: dict[str, Any]) -> dict[str, Any]:
    from negotiationarena.game_objects.resource import Resources
    from negotiationarena.game_objects.trade import Trade

    direction = request.get("direction")
    give = request.get("give")
    resources = request.get("resources")
    if direction not in {"offer", "accept"}:
        return {
            "ok": False,
            "error_type": "bad_request",
            "message": f"unknown direction: {direction!r}",
        }
    if not isinstance(give, dict) or len(give) != 2:
        return {
            "ok": False,
            "error_type": "bad_request",
            "message": "give must be a two-agent trade mapping",
        }
    if not isinstance(resources, dict):
        return {
            "ok": False,
            "error_type": "bad_request",
            "message": "resources must be a mapping",
        }

    trade = Trade(give)
    holder = Resources(resources)
    legal = trade.can_offer(holder) if direction == "offer" else trade.can_accept(holder)
    return {"ok": True, "legal": bool(legal)}


def _outcome_json(value: Any) -> dict[str, Any]:
    """Typed wrapper for one ``after_game_ends()`` summary entry.

    ``BuySellGame``'s ``player_outcome`` entries are plain numbers
    (``Valuation.value`` already reduces to one ``ZUP``-denominated
    scalar); ``MultiTurnUltimatumGame``'s are raw ``Resources`` objects
    (``UltimatumGoal`` carries no ``Valuation`` -- ``games/ultimatum/
    game.py``'s ``after_game_ends``: ``outcome[0] = final_resources[0]``
    is literally a ``Resources`` object, not a number, and ``final_resources``
    itself is always a list of ``Resources`` for both games). Both shapes
    are recorded verbatim, never coerced to a common representation here;
    see ``measurement.py`` for how the adapter reduces each to one
    native-unit scalar per seat.
    """
    from negotiationarena.game_objects.resource import Resources

    if isinstance(value, Resources):
        return {"kind": "resources", "value": dict(value.resource_dict)}
    return {"kind": "scalar", "value": value}


def _read_settlement(game: Any) -> dict[str, Any]:
    """Read back whatever upstream's own ``after_game_ends()`` just appended.

    Shared tail for ``op=settle``/``op=replay_transcript`` -- both call
    ``game.after_game_ends()`` themselves (via a different, independently
    constructed ``game_state``) and then delegate solely to this function
    to report the result, so neither op can silently diverge in how it
    reads the summary back.
    """
    end_state = game.game_state[-1]
    summary = end_state.get("summary")
    if summary is None:
        # BuySellGame.after_game_ends()'s own single-iteration short-circuit
        # (int(end_state["current_iteration"]) <= 1) appends no "summary"
        # key at all; MultiTurnUltimatumGame has no equivalent short-circuit.
        return {
            "ok": True,
            "settled": False,
            "reason": (
                "upstream's own after_game_ends() computed no summary for "
                f"this transcript (current_iteration={end_state.get('current_iteration')!r})"
            ),
        }
    return {
        "ok": True,
        "settled": True,
        "player_outcome": [_outcome_json(v) for v in summary["player_outcome"]],
        "final_resources": [_outcome_json(v) for v in summary["final_resources"]],
        "final_response": summary["final_response"],
    }


def _op_settle(request: dict[str, Any]) -> dict[str, Any]:
    from negotiationarena.constants import PLAYER_ANSWER_TAG, PROPOSED_TRADE_TAG
    from negotiationarena.game_objects.trade import Trade

    game_kind = request.get("game_kind")
    scenario = request.get("scenario")
    iteration_count = request.get("iteration_count")
    final_answer = request.get("final_answer")
    proposed_trade = request.get("proposed_trade")
    if game_kind not in {"buy_sell", "ultimatum"}:
        return {"ok": False, "error_type": "bad_request", "message": f"unknown game_kind: {game_kind!r}"}
    if not isinstance(scenario, dict):
        return {"ok": False, "error_type": "bad_request", "message": "scenario must be an object"}
    if not isinstance(iteration_count, int) or isinstance(iteration_count, bool) or iteration_count < 1:
        return {
            "ok": False,
            "error_type": "bad_request",
            "message": "iteration_count must be a positive integer",
        }
    if not isinstance(final_answer, str) or not final_answer:
        return {"ok": False, "error_type": "bad_request", "message": "final_answer must be a non-empty string"}
    if proposed_trade is not None and not (isinstance(proposed_trade, dict) and len(proposed_trade) == 2):
        return {
            "ok": False,
            "error_type": "bad_request",
            "message": "proposed_trade must be a two-agent trade mapping or null",
        }

    with tempfile.TemporaryDirectory(prefix="negarena_bridge_settle_") as tmp_dir:
        game = _build_game(game_kind, scenario, tmp_dir)
        # after_game_ends() always reads game_state[-2]'s proposed trade
        # (even when the episode was never accepted -- it just goes unused
        # in that branch) and game_state[-1]'s player answer; these two
        # synthetic entries are exactly what write_game_state would have
        # produced for those two turns, never anything after_game_ends()
        # itself does not read.
        trade_value: Any = Trade(proposed_trade) if proposed_trade is not None else "NONE"
        game.game_state.append(
            {
                "current_iteration": max(iteration_count - 1, 1),
                "turn": 0,
                "player_public_info_dict": {PROPOSED_TRADE_TAG: trade_value},
            }
        )
        game.game_state.append(
            {
                "current_iteration": iteration_count,
                "turn": 1,
                "player_public_info_dict": {PLAYER_ANSWER_TAG: final_answer},
            }
        )
        game.after_game_ends()
        return _read_settlement(game)


def _op_replay_transcript(request: dict[str, Any]) -> dict[str, Any]:
    game_kind = request.get("game_kind")
    scenario = request.get("scenario")
    turns = request.get("turns")
    if game_kind not in {"buy_sell", "ultimatum"}:
        return {"ok": False, "error_type": "bad_request", "message": f"unknown game_kind: {game_kind!r}"}
    if not isinstance(scenario, dict):
        return {"ok": False, "error_type": "bad_request", "message": "scenario must be an object"}
    if not isinstance(turns, list) or not turns or not all(isinstance(item, str) for item in turns):
        return {
            "ok": False,
            "error_type": "bad_request",
            "message": "turns must be a non-empty list of raw response strings",
        }

    with tempfile.TemporaryDirectory(prefix="negarena_bridge_replay_") as tmp_dir:
        game = _build_game(game_kind, scenario, tmp_dir)
        # Mirrors AlternatingGame.run()'s loop body verbatim minus the
        # players[turn].step() call -- the raw scripted text is already
        # given, so nothing here generates or parses a NEW response;
        # write_game_state/game_over/after_game_ends are all upstream's own,
        # called independently of environment.py's parse_response op.
        game.current_iteration = 1
        game.turn = 0
        ended = False
        for response in turns:
            game.write_game_state(game.players, response)
            if game.game_over():
                ended = True
                break
            game.get_next_player()
            game.current_iteration += 1
        if not ended:
            return {
                "ok": False,
                "error_type": "replay_incomplete",
                "message": (
                    f"scripted transcript of {len(turns)} turn(s) did not reach "
                    "upstream's own game_over() -- the parity harness must supply "
                    "a terminating transcript"
                ),
            }
        game.after_game_ends()
        return _read_settlement(game)


def _op_runtime_info() -> dict[str, Any]:
    import negotiationarena

    return {
        "ok": True,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "negotiationarena_package_file": str(Path(negotiationarena.__file__).resolve()),
    }


def _dispatch(request: dict[str, Any]) -> dict[str, Any]:
    op = request.get("op")
    if op == "parse_response":
        return _op_parse_response(request)
    if op == "check_trade":
        return _op_check_trade(request)
    if op == "settle":
        return _op_settle(request)
    if op == "replay_transcript":
        return _op_replay_transcript(request)
    if op == "runtime_info":
        return _op_runtime_info()
    return {
        "ok": False,
        "error_type": "bad_request",
        "message": f"unknown op: {op!r}",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream-root",
        default=None,
        help="path to the pinned NegotiationArena checkout whose top-level "
        "negotiationarena/games packages must supply the imported source",
    )
    args = parser.parse_args(argv)
    try:
        _make_upstream_importable(args.upstream_root)
        request = json.loads(sys.stdin.read())
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
        response = _dispatch(request)
    except Exception as error:  # noqa: BLE001 - reported as a structured infra failure
        response = {
            "ok": False,
            "error_type": type(error).__name__,
            "message": str(error),
        }
    sys.stdout.write(json.dumps(response))
    sys.stdout.flush()
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
