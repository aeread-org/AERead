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

  {"op": "check_trade", "direction": "offer"|"accept",
   "give": {agent_label: resource_dict, agent_label: resource_dict},
   "resources": resource_dict}
      -> {"ok": true, "legal": bool}
      -- delegates to ``Trade(give).can_offer(Resources(resources))`` (when
         ``direction == "offer"``) or ``Trade(give).can_accept(...)`` (when
         ``direction == "accept"``), which upstream itself never calls
         before ``execute_trade`` (the adapter-owned admission gate, spec
         section 3).

  Anything else (bad op, malformed request, import failure, ...)
      -> {"ok": false, "error_type": str, "message": str}, exit code 1.
"""
from __future__ import annotations

import argparse
import json
import sys
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


def _op_parse_response(request: dict[str, Any]) -> dict[str, Any]:
    from negotiationarena.constants import PROPOSED_TRADE_TAG, RESOURCES_TAG

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
