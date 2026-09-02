#!/usr/bin/env python
"""Subprocess driver for agenticpay_bilateral's ``AgenticpayBridge`` (see
``agenticpay_bridge.py``).

This script runs under a SEPARATE, already-provisioned Python interpreter
with the pinned upstream checkout's runtime dependencies installed
(``loguru``, ``numpy`` -- see ``tools/agenticpay_bridge/requirements.txt``).
Source is always loaded from the caller-supplied pinned checkout (commit
``1ff4e1a2686eac6a07ff559df6d50329c6fd9f69``), never from an unrelated
``agenticpay`` distribution installed in that interpreter. Nothing is
installed or fetched by this script (no network calls).

It exists so ``environment.py`` -- which runs inside AERead's own Python
interpreter that deliberately does not carry ``agenticpay``'s runtime
dependencies -- can delegate every negotiation round to the real upstream
``BaseEnv.reset``/``step`` instead of reimplementing any of the price/
contract extraction, legality checks, or scoring formulas (forbidden
outright by docs/agenticpay_adapter_spec.md section 3).

Upstream's own environment object is *not* JSON-serializable (it holds a
``ConversationMemory``, a ``NegotiationState`` dataclass, and an
``Enum``-valued status internally as live Python attributes, not a plain
dict the way tau2-bench's ``RetailDB`` is) and cannot be handed back to the
caller between subprocess calls the way tau3_retail's bridge round-trips a
``db`` dict. Rather than pickle a live object across process boundaries (or
keep one subprocess alive per case, a much larger change), each call
reconstructs the environment from scratch and replays every completed round
in ``history`` before applying the newly requested round. This is the same
"no state cached across calls" discipline tau3_retail's bridge already
follows for its own ``db``; here the full ordered ``(buyer_action,
seller_action)`` history plays the equivalent role. It costs O(rounds) work
per call instead of O(1), which is a fine trade against
``max_rounds=20`` for provider-free, scripted-trajectory tests.

Because upstream's constructor requires ``buyer_agent``/``seller_agent``
objects satisfying ``BaseAgent``, and ``reset()`` calls their
``.initialize(context)`` (a concrete, non-abstract method that only stores
``context``) but nothing under ``envs/`` ever calls their abstract
``.respond()``, this driver supplies a minimal ``ScriptedAgent`` shim
(``model=None``, ``.respond()`` raises) rather than importing
``agents.buyer_agent``/``agents.seller_agent`` (which unconditionally
import ``loguru`` themselves -- redundant, since importing the ``agenticpay``
package at all already requires it, but never a reason to construct a real
LLM-backed agent for a scripted replay).

Protocol -- exactly one JSON object read from stdin, exactly one JSON object
written to stdout:

  {"op": "reset", "env_module": str, "env_class": str,
   "constructor_kwargs": dict, "reset_kwargs": dict}
      -> {"ok": true, "observation": <json>, "info": <json>}

  {"op": "replay_round", "env_module": str, "env_class": str,
   "constructor_kwargs": dict, "reset_kwargs": dict,
   "history": [{"buyer_action": str|null, "seller_action": str|null}, ...],
   "buyer_action": str|null, "seller_action": str|null}
      -> {"ok": true, "observation": <json>, "reward": float,
          "terminated": bool, "truncated": bool, "info": <json>}
      -- constructs a fresh environment, calls ``reset(**reset_kwargs)``,
         replays every entry of ``history`` in order via ``step(...)``
         (raising if any of those rounds unexpectedly terminates the
         episode early), then applies the newly requested round and
         returns upstream's own ``step()`` result verbatim (after
         recursively converting dataclasses/Enums to plain JSON). In
         contract mode, ``info`` is additionally overlaid with
         ``buyer_contract_valid``/``seller_contract_valid`` -- upstream's
         own ``_validate_contract`` verdict for *this round's* attempted
         submission, called again (never reimplemented) because upstream
         itself never records that verdict in ``state`` (see
         ``_overlay_contract_validity``).

  {"op": "runtime_info"}
      -> {"ok": true, "python_version": str, "agenticpay_package_file": str}

  Anything else (bad op, malformed request, import failure, ...)
      -> {"ok": false, "error_type": str, "message": str}, exit code 1.
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import enum
import importlib
import io
import json
import sys
from pathlib import Path
from typing import Any


def _make_upstream_importable(upstream_root: str | None) -> None:
    """Ensure ``import agenticpay`` resolves to the pinned checkout."""
    if upstream_root:
        root_dir = str(Path(upstream_root).resolve())
        sys.path[:] = [entry for entry in sys.path if entry != root_dir]
        sys.path.insert(0, root_dir)
    import agenticpay

    if upstream_root:
        expected_package = (Path(upstream_root) / "agenticpay").resolve()
        loaded_file = Path(agenticpay.__file__).resolve()
        if not loaded_file.is_relative_to(expected_package):
            raise RuntimeError(
                "agenticpay import did not resolve under the requested pinned "
                f"checkout: loaded {loaded_file}, expected under {expected_package}"
            )


def _scripted_agent_class():
    from agenticpay.agents.base_agent import BaseAgent

    class ScriptedAgent(BaseAgent):
        """A no-op stand-in satisfying ``BaseAgent``'s duck-typed contract.

        ``reset()`` calls ``.initialize(context)`` (inherited, concrete: it
        only stores ``context``); nothing under ``envs/`` ever calls
        ``.respond()``. Actions are injected directly by this driver's
        caller, never generated here.
        """

        def respond(self, conversation_history, current_state):  # noqa: D401
            raise NotImplementedError(
                "ScriptedAgent never generates its own responses; the bridge "
                "driver injects buyer/seller actions directly"
            )

    return ScriptedAgent


def _resolve_env_class(env_module: str, env_class: str):
    module = importlib.import_module(env_module)
    return getattr(module, env_class)


def _json_safe(value: Any) -> Any:
    """Recursively convert upstream's dataclass/Enum-bearing return values."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_safe(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _restore_bool_discrete_keys(contract_config: Any) -> Any:
    """Undo ``cases._json_dict_key``'s bool -> ``"true"``/``"false"`` coercion.

    Two of the 25 realistic scenarios declare a boolean-valued discrete
    contract term (``extra_condiments``, ``include_utilities``): upstream's
    own ``discrete_weights[term]`` dict uses Python ``True``/``False`` as
    keys in source, but a case manifest can only store string dict keys
    (JSON has no other kind). Restoring the exact key type upstream's own
    ``_calculate_contract_utilities``/``_validate_contract`` compare
    against (a live contract submission's ``discrete_terms[term]`` is a
    JSON-parsed Python bool after ``json.loads`` on a ``<contract>...
    </contract>`` block) matters here, not just for JSON-storage tidiness:
    left as the string ``"true"``, ``dw.get(value, 0.0)`` with a real bool
    ``value`` would silently miss and fall back to a ``0.0`` default
    weight, corrupting the utility calculation for exactly these terms.

    Scoped narrowly: only ``discrete_weights[term]`` where the paired
    ``discrete_options[term]`` list itself contains a Python bool after the
    same JSON round trip -- never a blanket "string that looks like true/
    false" guess.
    """
    if not isinstance(contract_config, dict):
        return contract_config
    discrete_options = contract_config.get("discrete_options") or {}
    for preference_key in ("buyer_preferences", "seller_preferences"):
        preferences = contract_config.get(preference_key)
        if not isinstance(preferences, dict):
            continue
        discrete_weights = preferences.get("discrete_weights")
        if not isinstance(discrete_weights, dict):
            continue
        for term, weight_map in discrete_weights.items():
            options = discrete_options.get(term)
            if not isinstance(options, list) or not isinstance(weight_map, dict):
                continue
            if not any(isinstance(option, bool) for option in options):
                continue
            restored: dict[Any, Any] = {}
            for key, value in weight_map.items():
                if key == "true":
                    restored[True] = value
                elif key == "false":
                    restored[False] = value
                else:
                    restored[key] = value
            discrete_weights[term] = restored
    return contract_config


def _build_env(request: dict[str, Any]):
    env_cls = _resolve_env_class(request["env_module"], request["env_class"])
    ScriptedAgent = _scripted_agent_class()
    buyer = ScriptedAgent(model=None, role_description="buyer", name="buyer")
    seller = ScriptedAgent(model=None, role_description="seller", name="seller")
    constructor_kwargs = dict(request["constructor_kwargs"])
    environment_info = constructor_kwargs.get("environment_info")
    if isinstance(environment_info, dict) and "contract_config" in environment_info:
        environment_info = dict(environment_info)
        environment_info["contract_config"] = _restore_bool_discrete_keys(
            environment_info["contract_config"]
        )
        constructor_kwargs["environment_info"] = environment_info
    env = env_cls(buyer_agent=buyer, seller_agent=seller, **constructor_kwargs)
    observation, info = env.reset(**request["reset_kwargs"])
    return env, observation, info


def _op_reset(request: dict[str, Any]) -> dict[str, Any]:
    _env, observation, info = _build_env(request)
    return {"ok": True, "observation": _json_safe(observation), "info": _json_safe(info)}


def _overlay_contract_utilities(env: Any, info: dict[str, Any]) -> dict[str, Any]:
    """Work around upstream's own stale ``info["buyer_utility"]``/``["seller_utility"]``.

    ``Task1BasicPriceNegotiation.step()`` builds ``info`` (via
    ``_get_info()``, which reads ``self.state.metadata.get("buyer_utility")``)
    *before* it calls ``_calculate_global_score``/``_calculate_buyer_score``/
    ``_calculate_seller_score`` on a terminal round -- and those three score
    methods are the *only* place that ever writes
    ``self.state.metadata["buyer_utility"]``/``["seller_utility"]``. The
    returned ``info`` dict therefore always reports ``null`` for both
    fields on the very round that computes them, even when a real,
    non-degenerate MAUT contract utility was just calculated (reproduced
    directly against the pinned checkout: a `s01_beauty_product` contract
    with `z_max=1.2`, `GlobalScore=100.0` still reports `buyer_utility:
    null`, `seller_utility: null`). This is an upstream evaluation-order
    quirk, not a scoring formula this adapter re-derives: the correct,
    already-computed values live on ``env.state.metadata`` by the time
    ``step()`` returns, so this reads them from there -- never
    recalculates ``u_b``/``u_s`` itself.
    """
    metadata = getattr(getattr(env, "state", None), "metadata", None)
    if isinstance(metadata, dict):
        info["buyer_utility"] = metadata.get("buyer_utility")
        info["seller_utility"] = metadata.get("seller_utility")
    return info


def _overlay_contract_validity(env: Any, request: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    """Report whether *this round's* attempted contract submission was valid.

    Upstream's own ``step()`` decides "accepted" internally (``_validate_contract``)
    but never records that decision anywhere in ``self.state`` -- only its effect
    (whether ``state.metadata["buyer_contract"]``/``["seller_contract"]`` gets
    overwritten). That effect is indistinguishable from "nothing happened" when a
    seat *repeats* an already-accepted contract verbatim: the stored value does not
    visibly change either way, so a before/after state comparison alone cannot tell
    "repeated a legal contract" from "rejected an illegal one" (second-review Codex
    finding 4 -- reproduced directly against the pinned checkout). Rather than
    reimplement upstream's bounds-checking ourselves, this calls upstream's own
    ``_extract_contract``/``_validate_contract`` methods again, on the exact same
    raw text ``step()`` itself just used to reach its own accept/reject decision for
    this round -- both are pure (no side effects on ``env``), so this reproduces
    upstream's own verdict exactly, never a re-derivation of it. Skipped entirely
    outside contract mode, and left unset (not overlaid) when extraction itself
    found nothing to validate (no ``<contract>`` tag, or unparsable JSON) -- exactly
    mirroring upstream's own "nothing written" outcome for those cases.
    """
    if not getattr(env, "use_contract_mode", False):
        return info
    for seat, action_key in (("buyer", "buyer_action"), ("seller", "seller_action")):
        action_text = request.get(action_key)
        if action_text is None:
            continue
        contract = env._extract_contract(action_text)
        if contract is None:
            continue
        info[f"{seat}_contract_valid"] = bool(env._validate_contract(contract))
    return info


def _op_replay_round(request: dict[str, Any]) -> dict[str, Any]:
    env, observation, info = _build_env(request)
    for index, prior in enumerate(request.get("history", [])):
        observation, _reward, terminated, truncated, info = env.step(
            buyer_action=prior.get("buyer_action"),
            seller_action=prior.get("seller_action"),
        )
        if terminated or truncated:
            raise RuntimeError(
                f"history replay round {index} unexpectedly ended the episode "
                f"(terminated={terminated}, truncated={truncated}); the "
                "requested round was never reached"
            )
    observation, reward, terminated, truncated, info = env.step(
        buyer_action=request.get("buyer_action"),
        seller_action=request.get("seller_action"),
    )
    info = _overlay_contract_utilities(env, info)
    info = _overlay_contract_validity(env, request, info)
    return {
        "ok": True,
        "observation": _json_safe(observation),
        "reward": reward,
        "terminated": terminated,
        "truncated": truncated,
        "info": _json_safe(info),
    }


def _op_runtime_info() -> dict[str, Any]:
    import agenticpay

    return {
        "ok": True,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "agenticpay_package_file": str(Path(agenticpay.__file__).resolve()),
    }


def _dispatch(request: dict[str, Any]) -> dict[str, Any]:
    op = request.get("op")
    if op == "reset":
        return _op_reset(request)
    if op == "replay_round":
        return _op_replay_round(request)
    if op == "runtime_info":
        return _op_runtime_info()
    return {"ok": False, "error_type": "bad_request", "message": f"unknown op: {op!r}"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream-root",
        default=None,
        help="path to the pinned AgenticPay checkout that must supply the imported agenticpay package",
    )
    args = parser.parse_args(argv)
    # Task1BasicPriceNegotiation._calculate_reward/_calculate_seller_reward/
    # _calculate_buyer_reward call print(...) unconditionally on every
    # terminal round (not gated by any print_details flag, unlike the
    # GlobalScore/BuyerScore/SellerScore helpers step() itself calls with
    # print_details=False). Left alone this corrupts the one-JSON-object-on-
    # stdout protocol below. Every upstream call happens with the real
    # stdout swapped out for a throwaway buffer; only this driver's own
    # response is ever written to the real stdout.
    real_stdout = sys.stdout
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            _make_upstream_importable(args.upstream_root)
            request = json.loads(sys.stdin.read())
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
            response = _dispatch(request)
    except Exception as error:  # noqa: BLE001 - reported as a structured infra failure
        response = {"ok": False, "error_type": type(error).__name__, "message": str(error)}
    real_stdout.write(json.dumps(response))
    real_stdout.flush()
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
