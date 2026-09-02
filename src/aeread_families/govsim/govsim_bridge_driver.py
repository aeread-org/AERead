#!/usr/bin/env python
"""Subprocess driver for govsim's ``GovsimBridge`` (see ``govsim_bridge.py``).

This script runs under a SEPARATE, already-provisioned Python interpreter
(``bridges/govsim-venv``, provisioned by ``tools/govsim_bridge/provision.sh``)
that carries the pinned upstream govsim checkout's runtime dependencies
(``numpy``, ``pandas``, ``omegaconf``, ``pettingzoo``) which the project's own
venv deliberately does not. Source is always loaded from the caller-supplied
pinned checkout (commit ``1d11adf047b24fa2ba0d44a1d4931015ea2e5210``), never
from an unrelated govsim distribution installed in that interpreter. Nothing
is installed or fetched by this script (no network calls).

Every function below calls straight into upstream's ``ConcurrentEnv``
subclasses (``reset``/``step``) or reads upstream's own ``POOL_LOCATION``
constant; it never reimplements the regeneration formula, the collapse test,
or `_assign_stochastic`/`_assign_proportional` (see the adapter spec's
"adapter boundary", section 3).

This file must not import anything from the ``aeread`` package: it is
invoked as a standalone script under a *different* Python interpreter that
does not have ``aeread`` on its path.

Protocol -- exactly one JSON object read from stdin, exactly one JSON object
written to stdout:

  {"op": "run_actions", "scenario": "fishing"|"sheep"|"pollution",
   "env_cfg": {"num_agents": int, "initial_resource_in_pool": int,
   "max_num_rounds": int, "harvesting_order": str,
   "assign_resource_strategy": str, "inject_universalization": bool},
   "seed": int, "actions": [<action dict>, ...]}
      -> {"ok": true, "phase": str, "pool_location": str,
          "agent_selection": str, "num_round": int,
          "resource_in_pool": int, "resource_before_harvesting": int,
          "sustainability_threshold": int,
          "wanted_resource": {agent_id: int}, "collected_resource": {...},
          "last_collected_resource": {...}, "rewards": {...},
          "terminations": {...}}
      -- ``actions`` is the complete ordered action history for this episode,
         from the first action taken after ``reset(seed=seed)`` through the
         one just submitted. There is no way to serialize upstream's live
         ``ConcurrentEnv`` (its state holds ``datetime`` values and
         ``PersonaAction`` instances, neither JSON-safe -- see the adapter
         spec's "bridge design" note) across this bridge's per-call subprocess
         boundary, so every call reconstructs the episode from scratch:
         ``reset(seed=seed)``, then ``step()`` once per recorded action in
         order. Upstream's own ``np.random.RandomState`` is seeded once by
         ``reset`` and consumes draws in the exact same call sequence every
         replay, so this is deterministic, not merely "usually the same" --
         verified against upstream's ``_assign_stochastic`` during recon (see
         ``docs/govsim_adapter_spec.md``). Each action dict is
         ``{"kind": "harvesting"|"chat"|"home", "agent_id": str,
         "location": str (defaults to upstream's own POOL_LOCATION for
         "harvesting", "restaurant" for "chat", "home" for "home" -- a caller
         may override this deliberately to reproduce the malformed-operational
         golden), "quantity": int (harvesting only)}``.

  {"op": "runtime_info"}
      -> {"ok": true, "python_version": str, "numpy_version": str,
          "pandas_version": str, "omegaconf_version": str,
          "pettingzoo_version": str}

  {"op": "call_upstream_gini", "array": [float, ...]}
      -> {"ok": true, "gini": float}
      -- Used only by the measurement parity test (spec section 5's P4):
         proves the copy of ``gini()`` vendored verbatim into
         ``measurement.py`` agrees with upstream's real, unmodified function,
         byte-for-byte, on the same sample array. Loads upstream's own
         ``simulation/analysis/plots.py::gini`` by extracting its literal
         source text via ``ast`` and executing that (never
         ``import simulation.analysis.plots`` directly): that module's own
         top-level imports (``plotly``, ``dash``, ``dash_mantine_components``,
         ``statsmodels``) are not installed in this bridge venv and are not
         needed for this one pure-numpy function -- the same style of
         controlled avoidance as this file's own
         ``_make_upstream_importable`` stub-package workaround for
         ``simulation.persona.common``, just via source extraction instead of
         a package-``__init__`` stub, since ``plots.py`` is the module itself,
         not a package with siblings to route around.

  Anything else (bad op, malformed request, an upstream assertion raised by a
  malformed action, ...)
      -> {"ok": false, "error_type": str, "message": str,
          "failed_action_index": int | null}, exit code 1.
      -- "failed_action_index" is the 0-based index into "actions" that
         raised, so the caller (only ever the newest action in practice,
         since every earlier one already replayed cleanly on a prior call)
         can tell a genuine infrastructure failure from upstream's own
         assertion catching a malformed action (spec section 4's
         "malformed-operational" golden).
"""
from __future__ import annotations

import argparse
import json
import sys
import types
from pathlib import Path
from typing import Any


_SCENARIO_ENV_CLASSES: dict[str, tuple[str, str]] = {
    "fishing": ("simulation.scenarios.fishing.environment.env", "FishingConcurrentEnv"),
    "sheep": ("simulation.scenarios.sheep.environment.env", "SheepConcurrentEnv"),
    "pollution": (
        "simulation.scenarios.pollution.environment.env",
        "PollutionConcurrentEnv",
    ),
}

_ENV_CFG_FIELDS = (
    "num_agents",
    "initial_resource_in_pool",
    "max_num_rounds",
    "harvesting_order",
    "assign_resource_strategy",
    "inject_universalization",
)


def _make_upstream_importable(upstream_root: str) -> str:
    """Import only ``ConcurrentEnv``/``env.py``/``persona.common`` (spec §3.2).

    ``simulation.persona.common`` (plain dataclass-style action/observation
    types, zero third-party imports) is a submodule of the ``simulation.persona``
    *package*, whose real ``__init__.py`` unconditionally imports the full
    pathfinder cognition stack (``sentence_transformers``, ``wandb``, ...),
    none of which this bridge venv installs and none of which this adapter
    ever wraps. Installing stub package objects for ``simulation`` and
    ``simulation.persona`` -- empty ``types.ModuleType``s whose ``__path__``
    points at the real upstream directories -- lets
    ``import simulation.persona.common`` resolve that one submodule directly
    without ever executing ``simulation/persona/__init__.py``.

    Returns the resolved, absolute upstream root -- ``_op_call_upstream_gini``
    needs it too (to locate ``simulation/analysis/plots.py`` without importing
    it), and this is the one place that already resolves and normalizes it.
    """
    root = str(Path(upstream_root).resolve())
    sys.path[:] = [entry for entry in sys.path if entry != root]
    sys.path.insert(0, root)

    if "simulation" not in sys.modules:
        simulation_pkg = types.ModuleType("simulation")
        simulation_pkg.__path__ = [str(Path(root) / "simulation")]
        sys.modules["simulation"] = simulation_pkg
    if "simulation.persona" not in sys.modules:
        persona_pkg = types.ModuleType("simulation.persona")
        persona_pkg.__path__ = [str(Path(root) / "simulation" / "persona")]
        sys.modules["simulation.persona"] = persona_pkg
    return root


def _import_env_class(scenario: str):
    if scenario not in _SCENARIO_ENV_CLASSES:
        raise ValueError(
            f"unknown scenario {scenario!r}; expected one of "
            f"{sorted(_SCENARIO_ENV_CLASSES)}"
        )
    module_name, class_name = _SCENARIO_ENV_CLASSES[scenario]
    import importlib

    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def _build_env(scenario: str, env_cfg: dict[str, Any]):
    from omegaconf import OmegaConf

    env_class = _import_env_class(scenario)
    cfg = OmegaConf.create({field: env_cfg[field] for field in _ENV_CFG_FIELDS})
    num_agents = int(env_cfg["num_agents"])
    persona_ids = [f"persona_{i}" for i in range(num_agents)]
    # Display names never affect arithmetic (prompt text only); a fixed
    # placeholder avoids threading persona name choice through this op.
    map_id_to_name = {agent_id: agent_id for agent_id in persona_ids}
    env = env_class(cfg, "/dev/null/unused-govsim-bridge-storage", map_id_to_name)
    # This bridge only ever inspects `internal_global_state`/rewards/
    # terminations, never upstream's own wandb/pandas log; discard the
    # per-round `save_log()` disk write entirely rather than fabricate a
    # writable experiment_storage directory for a value nothing here reads.
    env.save_log = lambda: None  # type: ignore[method-assign]
    return env


def _build_action(env: Any, action: dict[str, Any]):
    from simulation.persona.common import (
        PersonaAction,
        PersonaActionChat,
        PersonaActionHarvesting,
    )

    kind = action["kind"]
    agent_id = action["agent_id"]
    if kind == "harvesting":
        location = action.get("location", env.POOL_LOCATION)
        return PersonaActionHarvesting(
            agent_id,
            location,
            int(action["quantity"]),
            stats={},
            html_interactions=["govsim_bridge"],
        )
    if kind == "chat":
        location = action.get("location", "restaurant")
        # log_step_conversation unconditionally indexes
        # html_interactions[-2]/[-1] even for an empty conversation (no
        # cheap talk in v1, spec section 6); two placeholder entries avoid
        # an IndexError on upstream's own logging path.
        return PersonaActionChat(
            agent_id,
            location,
            [],
            conversation_resource_limit=0,
            stats={},
            html_interactions=["govsim_bridge", "govsim_bridge"],
        )
    if kind == "home":
        location = action.get("location", "home")
        return PersonaAction(
            agent_id, location, stats={}, html_interactions=["govsim_bridge"]
        )
    raise ValueError(f"unknown action kind: {kind!r}")


def _project_state(env: Any) -> dict[str, Any]:
    state = env.internal_global_state
    return {
        "phase": env.phase,
        "pool_location": env.POOL_LOCATION,
        "agent_selection": env.agent_selection,
        "num_round": env.num_round,
        "resource_in_pool": state["resource_in_pool"],
        "resource_before_harvesting": state["resource_before_harvesting"],
        "sustainability_threshold": state["sustainability_threshold"],
        "wanted_resource": dict(state["wanted_resource"]),
        "collected_resource": dict(state["collected_resource"]),
        "last_collected_resource": dict(state["last_collected_resource"]),
        "rewards": dict(env.rewards),
        "terminations": dict(env.terminations),
    }


def _op_run_actions(request: dict[str, Any]) -> dict[str, Any]:
    env = _build_env(request["scenario"], request["env_cfg"])
    env.reset(seed=int(request["seed"]))
    actions = request["actions"]
    for index, action in enumerate(actions):
        persona_action = _build_action(env, action)
        try:
            result = env.step(persona_action)
        except AssertionError as error:
            # The one intended path (spec section 4's "malformed-operational"
            # golden): upstream validates every action with a bare `assert`
            # (see `simulation/scenarios/common/environment/concurrent_env.py`'s
            # `step()`), never a typed exception -- this is the only
            # exception type this function ever downgrades to a typed,
            # index-carrying action failure. Any OTHER exception (KeyError,
            # AttributeError, ...) is a genuine adapter/upstream
            # incompatibility, not a malformed action, and must propagate
            # uncaught here so `main()`'s outer handler reports it as an
            # infrastructure failure (`failed_action_index: null`) instead
            # of being indistinguishable from this branch.
            return {
                "ok": False,
                "error_type": type(error).__name__,
                "message": str(error),
                "failed_action_index": index,
            }
        if result is None:
            return {
                "ok": False,
                "error_type": "EpisodeAlreadyTerminated",
                "message": (
                    "upstream step() returned None: the acting agent was "
                    "already terminated before this action"
                ),
                "failed_action_index": index,
            }
    response = _project_state(env)
    response["ok"] = True
    return response


def _op_runtime_info() -> dict[str, Any]:
    import numpy
    import omegaconf
    import pandas
    import pettingzoo

    return {
        "ok": True,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "numpy_version": numpy.__version__,
        "pandas_version": pandas.__version__,
        "omegaconf_version": omegaconf.__version__,
        "pettingzoo_version": pettingzoo.__version__,
    }


def _load_upstream_gini(upstream_root: str):
    """Load upstream's real ``gini()`` function object without importing
    ``simulation.analysis.plots`` (see this file's module docstring's
    ``call_upstream_gini`` op entry for why)."""
    import ast

    plots_path = Path(upstream_root) / "simulation" / "analysis" / "plots.py"
    source = plots_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(plots_path))
    segment = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "gini":
            segment = ast.get_source_segment(source, node)
            break
    if segment is None:
        raise ValueError(
            f"gini() function not found in upstream {plots_path} -- has the "
            "pinned checkout drifted from the commit this bridge expects?"
        )
    namespace: dict[str, Any] = {"np": __import__("numpy")}
    exec(  # noqa: S102 - executing upstream's own pinned source, not user input
        compile(segment, filename=str(plots_path), mode="exec"), namespace
    )
    return namespace["gini"]


def _op_call_upstream_gini(request: dict[str, Any], upstream_root: str) -> dict[str, Any]:
    import numpy as np

    gini_fn = _load_upstream_gini(upstream_root)
    array = np.array(request["array"], dtype=float)
    return {"ok": True, "gini": float(gini_fn(array))}


def _dispatch(request: dict[str, Any], upstream_root: str) -> dict[str, Any]:
    op = request.get("op")
    if op == "run_actions":
        return _op_run_actions(request)
    if op == "runtime_info":
        return _op_runtime_info()
    if op == "call_upstream_gini":
        return _op_call_upstream_gini(request, upstream_root)
    return {
        "ok": False,
        "error_type": "bad_request",
        "message": f"unknown op: {op!r}",
        "failed_action_index": None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream-root",
        required=True,
        help="path to the pinned govsim checkout (commit "
        "1d11adf047b24fa2ba0d44a1d4931015ea2e5210)",
    )
    args = parser.parse_args(argv)
    try:
        resolved_upstream_root = _make_upstream_importable(args.upstream_root)
        request = json.loads(sys.stdin.read())
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
        response = _dispatch(request, resolved_upstream_root)
    except Exception as error:  # noqa: BLE001 - reported as a structured infra failure
        response = {
            "ok": False,
            "error_type": type(error).__name__,
            "message": str(error),
            "failed_action_index": None,
        }
    sys.stdout.write(json.dumps(response))
    sys.stdout.flush()
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
