#!/usr/bin/env python
"""Subprocess driver for econagent_v1's ``EconAgentBridge`` (see ``econagent_bridge.py``).

This script runs under a SEPARATE, already-provisioned Python interpreter with
the pinned upstream EconAgent checkout's runtime dependencies installed
(``tools/econagent_bridge/provision.sh``). Source is always loaded from the
caller-supplied pinned checkout (commit ``bfada09``), and the process is
always spawned with ``cwd=<upstream_root>`` by the caller -- required because
both ``simulate.py``'s top-level ``open('config.yaml')`` and
``ai_economist/foundation/scenarios/one_step_economy/one_step_economy.py``'s
``open('data/profiles.json')`` are bare, cwd-relative reads (see
``docs/econagent_adapter_spec.md``'s milestone-1 corrections 1-2). Nothing is
installed or fetched by this script; no network call is ever made.

It exists so the project venv -- which deliberately does not carry
``ai_economist``/``simulate.py``'s runtime dependencies -- can delegate every
scenario construction, scripted-policy decision, and engine step to the real
upstream implementation instead of reimplementing any of it. Every op below
either reads static upstream data (``resolve_env_config``) or calls straight
into upstream code (``foundation.make_env_instance``, ``simulate.
complex_actions``, ``env.step``); none of it reimplements upstream's tax,
consumption, or budget arithmetic.

This file must not import anything from the ``aeread`` package: it is
invoked as a standalone script under a *different* Python interpreter that
does not have ``aeread`` on its path.

Protocol -- unlike ``tau3_retail``'s ``tau2_bridge_driver.py`` (one JSON
object per fresh subprocess, all state in the payload), this driver is a
PERSISTENT subprocess for the lifetime of one episode: it reads one JSON
request per line from stdin and writes one JSON response per line to stdout,
in a loop, keeping the live upstream ``env`` object as process state between
requests. See ``docs/econagent_adapter_spec.md``'s milestone-1 correction 3
for why (``complex_actions`` needs the live env object's mutable per-agent
state and shared RNG stream, not a JSON-serializable snapshot).

  {"op": "resolve_env_config"}
      -> {"ok": true, "env_config": {...}}
      -- the verbatim ``env`` sub-mapping parsed from the pinned
         ``config.yaml``, byte-exact source, no field renamed or dropped.
         Stateless; does not require a prior "reset" and does not start an
         episode. Used by ``cases.py`` at import time for Gate-1's resolved-
         env digest, and may be sent to a driver process that is then closed
         without ever calling "reset".

  {"op": "reset", "n_agents": int, "episode_length": int, "world_seed": int,
   "beta": float (default 0.1), "gamma": float (default 0.1), "h": float
   (default 1.0)}
      -> {"ok": true, "n_agents": int, "episode_length": int, "timestep": 0}
      -- parses config.yaml itself, overrides "n_agents"/"episode_length" the
         same way ``simulate.main()`` does, sets ``env_config["seed"] =
         world_seed`` (upstream's own ``BaseEnvironment.__init__`` calls
         ``self.seed(seed)`` when given), then calls
         ``foundation.make_env_instance(**env_config)`` and ``env.reset()``.
         Must be the first request of an episode; a second "reset" without an
         intervening "shutdown" is an error (one driver process serves
         exactly one episode).

  {"op": "step_month"}
      -> {"ok": true, "timestep": int, "done": bool,
          "actions": {agent_idx: [labor:int, consumption:number], "p": [0]}}
      -- calls ``simulate.complex_actions(env, obs, beta=..., gamma=...,
         h=...)`` (the real upstream scripted policy, never reimplemented)
         then ``env.step(actions)``, exactly mirroring ``simulate.main()``'s
         per-month loop. "actions" is upstream's own return value, reported
         back for kernel-side bookkeeping/replay (see the adapter's
         milestone-1 correction 4 for why this pass's seats acknowledge
         rather than decide).

  {"op": "agent_snapshot"}
      -> {"ok": true, "agents": {agent_idx: {"inventory": {...},
          "income": {...}, "consumption": {...}, "saving": {...},
          "endogenous": {...}, "skill": float, "expected_skill": float,
          "production": float}}, "world": {"price": float,
          "interest_rate": float, "timestep": int, "period": int}}
      -- a JSON-safe read of the live agent/world state after the most
         recent "reset" or "step_month", for the environment plugin's
         per-seat ``observe()``/``terminal()``/``outcome()``. No upstream
         computation happens here; this only reads already-computed
         attributes. "period" is ``env.world.period`` (the world-level
         yearly cycle length SimpleSaving/PeriodicBracketTax's
         GDP/unemployment bookkeeping key off -- distinct from
         PeriodicBracketTax's *own* "period" kwarg, which is 1 in the
         pinned config), added in milestone 2 so measurement.py can
         identify saving-interest months without hardcoding the pinned
         config's value.

  {"op": "dense_log"}
      -> {"ok": true, "dense_log": {...}}
      -- the full, JSON-safe ``env.dense_log`` accumulated so far
         (``config.yaml``'s ``dense_log_frequency: 1`` means every step is
         recorded). Verbatim upstream data; no field is recomputed here.
         Per-component logs (e.g. "PeriodicTax", the per-agent-per-month
         income/tax_paid/lump_sum/marginal_rate/effective_rate dicts) are
         only backfilled by upstream's own ``_finalize_logs()`` when the
         episode's LAST "step_month" completes (``done`` is true) --
         calling this op before that point omits them; the environment
         plugin therefore calls this exactly once, right after the
         terminal "step_month" and before "shutdown".

  {"op": "recompute_tax", "incomes": {agent_idx: float, ...}}
      -> {"ok": true, "results": {agent_idx: {"tax_due": float,
          "marginal_rate": float}, ...}}
      -- milestone 2 addition for ``econagent_tax_bracket_arithmetic``
         (spec section 2): re-invokes upstream's own
         ``PeriodicBracketTax.taxes_due``/``marginal_rate`` methods on
         caller-supplied incomes -- never a reimplemented piecewise
         formula. Stateless (does not require a prior "reset"): the
         "us-federal-single-filer-2018-scaled" bracket schedule is a pure
         function of the pinned config (no RNG, no dependency on
         n_agents/world_seed), so a throwaway env constructed just for
         this call reproduces the real episode's own component exactly.
         May be sent to a driver process that is then closed without ever
         calling "reset", exactly like "resolve_env_config".

  {"op": "shutdown"}
      -> {"ok": true}
      -- acknowledges, then the driver exits after writing the response.

  Anything else (bad op, malformed request, import failure, an upstream
  exception, ...)
      -> {"ok": false, "error_type": str, "message": str}, and the driver
         exits (a request-level error ends the whole session -- never
         silently recovered with unrelated state).

  {"op": "step_month", "_test_crash_before_responding": true}
      -- NOT part of the real protocol above and never sent by
         ``EconAgentBridge``'s public API: a test-only fault-injection
         marker on an otherwise-real ``step_month`` request (performs the
         real mutation, then exits without responding) that exists solely
         to reproduce docs/econagent_codex_triage.md's finding 3 ("mutation
         can precede every durable outcome") deterministically for
         ``tests/test_econagent_goldens.py``, through the real upstream
         engine, never a mock.

  {"op": "step_month", "_test_hang_before_responding": true}
      -- NOT part of the real protocol above and never sent by
         ``EconAgentBridge``'s public API: a test-only fault-injection
         marker on an otherwise-real ``step_month`` request (performs the
         real mutation, then blocks forever without exiting or responding)
         that exists solely to reproduce docs/econagent_codex_triage.md's
         finding 7 ("persistent requests do not enforce their timeout")
         deterministically for ``tests/test_econagent_goldens.py``, through
         the real upstream engine, never a mock -- unlike the crash marker
         above, the subprocess and its stdout pipe stay alive, so only a
         genuine read timeout on the caller's side can ever detect this.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_SESSION: dict[str, Any] = {}


def _to_jsonable(value: Any) -> Any:
    """Recursively convert numpy scalars/arrays to plain JSON-safe values.

    ``env``/``agent`` state and ``env.dense_log`` are full of numpy float64/
    int64 scalars and, inside dense-logged world snapshots, numpy arrays.
    ``json.dumps`` cannot serialize an ``ndarray`` and should not be trusted
    to silently do the right thing for numpy scalar subclasses either -- this
    makes the conversion explicit rather than relying on numpy's incidental
    float/int subclassing.
    """
    import numpy as np

    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return _to_jsonable(value.tolist())
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def _resolve_env_config(upstream_root: Path) -> dict[str, Any]:
    import yaml

    config_path = upstream_root / "config.yaml"
    with config_path.open("r", encoding="utf-8") as handle:
        run_configuration = yaml.safe_load(handle)
    env_config = run_configuration.get("env")
    if not isinstance(env_config, dict):
        raise ValueError("config.yaml has no 'env' mapping")
    return _to_jsonable(env_config)


def _op_resolve_env_config(request: dict[str, Any], upstream_root: Path) -> dict[str, Any]:
    del request
    return {"ok": True, "env_config": _resolve_env_config(upstream_root)}


def _op_reset(request: dict[str, Any], upstream_root: Path) -> dict[str, Any]:
    if "env" in _SESSION:
        raise RuntimeError(
            "this driver process already served a 'reset'; one process is "
            "exactly one episode"
        )
    import ai_economist.foundation as foundation
    from simulate import complex_actions  # noqa: F401 -- see module docstring

    n_agents = int(request["n_agents"])
    episode_length = int(request["episode_length"])
    world_seed = int(request["world_seed"])

    env_config = _resolve_env_config(upstream_root)
    env_config["n_agents"] = n_agents
    env_config["episode_length"] = episode_length
    # BaseEnvironment.seed() asserts seed > 0 (ai_economist/foundation/base/
    # base_env.py); AERead's own world_seed is zero-based (CaseManifest.
    # world_seed's grammar allows 0, and the pinned scenario table uses
    # world_seed=0). +1 is a fixed, documented, adapter-side offset applied
    # only here, never touching the case's own declared world_seed -- two
    # distinct world_seed values still map to two distinct upstream seeds.
    env_config["seed"] = world_seed + 1

    env = foundation.make_env_instance(**env_config)
    obs = env.reset()

    _SESSION["env"] = env
    _SESSION["obs"] = obs
    _SESSION["complex_actions"] = complex_actions
    _SESSION["beta"] = float(request.get("beta", 0.1))
    _SESSION["gamma"] = float(request.get("gamma", 0.1))
    _SESSION["h"] = float(request.get("h", 1.0))

    return {
        "ok": True,
        "n_agents": n_agents,
        "episode_length": episode_length,
        "timestep": int(env.world.timestep),
    }


def _require_session() -> dict[str, Any]:
    if "env" not in _SESSION:
        raise RuntimeError("no active episode on this driver process; send 'reset' first")
    return _SESSION


def _op_step_month(request: dict[str, Any]) -> dict[str, Any]:
    del request
    session = _require_session()
    env = session["env"]
    complex_actions = session["complex_actions"]

    actions = complex_actions(
        env,
        session["obs"],
        beta=session["beta"],
        gamma=session["gamma"],
        h=session["h"],
    )
    obs, _rew, done, _info = env.step(actions)
    session["obs"] = obs

    return {
        "ok": True,
        "timestep": int(env.world.timestep),
        "done": bool(done["__all__"]),
        "actions": _to_jsonable(actions),
    }


_TEST_CRASH_BEFORE_RESPONDING_KEY = "_test_crash_before_responding"


def _op_step_month_and_crash_before_responding(request: dict[str, Any]) -> None:
    """Test-only fault injection -- deterministically reproduces
    docs/econagent_codex_triage.md finding 3 through the real upstream
    engine, never a mock: performs the exact same mutation
    ``_op_step_month`` performs (the real, mutating ``env.step(actions)``),
    then exits immediately, without ever writing or flushing a response.

    Not part of this driver's real protocol and not reachable through
    ``EconAgentBridge``'s public API at all -- only reachable via a
    hand-crafted raw ``{"op": "step_month", "_test_crash_before_responding":
    true}`` request past the public API, exactly like this module's
    existing ``_op_step_month`` bypass golden (the "invalid or
    unauthorized" golden's bridge-protocol-layer case), so that the request
    ``EconAgentBridge`` actually sees still has ``op="step_month"`` --
    ``tests/test_econagent_goldens.py``'s regression test for finding 3
    exercises the exact same client-side branch a real lost ``step_month``
    response would hit, not a fake op name the client has no reason to know
    about.
    """
    _op_step_month(request)  # the real mutation; its result is discarded on purpose
    os._exit(1)  # no response is ever written -- the crash IS the point


_TEST_HANG_BEFORE_RESPONDING_KEY = "_test_hang_before_responding"


def _op_step_month_and_hang_before_responding(request: dict[str, Any]) -> None:
    """Test-only fault injection -- deterministically reproduces
    docs/econagent_codex_triage.md finding 7 through the real upstream
    engine, never a mock: performs the exact same mutation
    ``_op_step_month`` performs, then blocks forever without ever writing
    or flushing a response -- simulating a hung ``complex_actions``/
    ``env.step`` call that leaves the subprocess (and its stdout pipe)
    alive but silent, unlike ``_op_step_month_and_crash_before_responding``
    above (finding 3), whose exit immediately closes the pipe. A genuine
    hang like this is exactly what ``EconAgentBridge``'s missing read
    timeout (finding 7) could not detect: the caller's
    ``process.stdout.readline()`` blocked forever regardless of
    ``timeout_seconds``.

    Not part of this driver's real protocol and not reachable through
    ``EconAgentBridge``'s public API at all -- only reachable via a
    hand-crafted raw ``{"op": "step_month", "_test_hang_before_responding":
    true}`` request past the public API, exactly like
    ``_op_step_month_and_crash_before_responding``.
    """
    _op_step_month(request)  # the real mutation; its result is discarded on purpose
    while True:
        time.sleep(3600)  # the caller's own read timeout must fire long before this


def _op_agent_snapshot(request: dict[str, Any]) -> dict[str, Any]:
    del request
    session = _require_session()
    env = session["env"]

    agents: dict[str, Any] = {}
    for agent in env.all_agents:
        idx = str(agent.idx)
        if idx == "p":
            continue
        agents[idx] = {
            "inventory": _to_jsonable(agent.inventory),
            "income": _to_jsonable(agent.income),
            "consumption": _to_jsonable(agent.consumption),
            "saving": _to_jsonable(agent.saving),
            "endogenous": _to_jsonable(agent.endogenous),
            "skill": _to_jsonable(agent.state["skill"]),
            "expected_skill": _to_jsonable(agent.state["expected skill"]),
            "production": _to_jsonable(agent.state["production"]),
        }
    world = {
        "price": _to_jsonable(env.world.price[-1]) if len(env.world.price) else None,
        "interest_rate": (
            _to_jsonable(env.world.interest_rate[-1])
            if len(env.world.interest_rate)
            else None
        ),
        "timestep": int(env.world.timestep),
        # Verbatim upstream config constant (SimpleSaving/PeriodicBracketTax's
        # own world-level cycle length -- distinct from PeriodicBracketTax's
        # *own* "period" kwarg, which is 1 in the pinned config). Exposed so
        # measurement.py can identify which months SimpleSaving actually
        # fires on (``timestep % period == 0``) without guessing or
        # hardcoding the pinned config's value.
        "period": int(env.world.period),
    }
    return {"ok": True, "agents": agents, "world": world}


def _op_dense_log() -> dict[str, Any]:
    session = _require_session()
    return {"ok": True, "dense_log": _to_jsonable(session["env"].dense_log)}


def _op_recompute_tax(request: dict[str, Any], upstream_root: Path) -> dict[str, Any]:
    """Re-invoke upstream's OWN ``PeriodicBracketTax`` bracket method (never a
    reimplemented piecewise formula) on caller-supplied incomes.

    Stateless, like ``resolve_env_config``: does not require a prior
    "reset" and does not touch ``_SESSION``. The bracket schedule for the
    pinned ``us-federal-single-filer-2018-scaled`` tax model is a pure
    function of the config (``bracket_cutoffs`` from ``usd_scaling``,
    ``curr_marginal_rates`` from the fixed schedule clipped by
    ``rate_max`` -- no RNG, no dependency on ``n_agents``/``world_seed``),
    so a freshly-constructed throwaway env yields byte-identical
    ``taxes_due``/``marginal_rate`` results to the real episode's own
    component -- confirmed empirically against a live episode run while
    building this op (see the econagent measurement module and spec
    milestone-2 corrections).
    """
    import ai_economist.foundation as foundation

    env_config = _resolve_env_config(upstream_root)
    # n_agents/episode_length/seed are irrelevant to the bracket schedule
    # (see docstring); fixed, valid placeholders satisfy upstream's own
    # constructor assertions (n_agents >= 2, seed > 0) without claiming any
    # particular episode identity for this stateless op.
    env_config["n_agents"] = 2
    env_config["episode_length"] = 1
    env_config["seed"] = 1
    env = foundation.make_env_instance(**env_config)
    component = env.get_component("PeriodicBracketTax")

    incomes = request["incomes"]
    if not isinstance(incomes, dict):
        raise ValueError("recompute_tax requires a mapping of agent_idx -> income")
    results = {
        agent_idx: {
            "tax_due": _to_jsonable(component.taxes_due(float(income))),
            "marginal_rate": _to_jsonable(component.marginal_rate(float(income))),
        }
        for agent_idx, income in incomes.items()
    }
    return {"ok": True, "results": results}


def _op_shutdown() -> dict[str, Any]:
    return {"ok": True}


def _dispatch(request: dict[str, Any], upstream_root: Path) -> tuple[dict[str, Any], bool]:
    """Return ``(response, keep_serving)``."""
    op = request.get("op")
    if op == "resolve_env_config":
        return _op_resolve_env_config(request, upstream_root), True
    if op == "reset":
        return _op_reset(request, upstream_root), True
    if op == "step_month":
        if request.get(_TEST_CRASH_BEFORE_RESPONDING_KEY):
            _op_step_month_and_crash_before_responding(request)  # never returns
            raise AssertionError("unreachable: the process above always exits first")
        if request.get(_TEST_HANG_BEFORE_RESPONDING_KEY):
            _op_step_month_and_hang_before_responding(request)  # never returns
            raise AssertionError("unreachable: the process above always hangs first")
        return _op_step_month(request), True
    if op == "agent_snapshot":
        return _op_agent_snapshot(request), True
    if op == "dense_log":
        return _op_dense_log(), True
    if op == "recompute_tax":
        return _op_recompute_tax(request, upstream_root), True
    if op == "shutdown":
        return _op_shutdown(), False
    return (
        {"ok": False, "error_type": "bad_request", "message": f"unknown op: {op!r}"},
        False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream-root",
        required=True,
        help="path to the pinned EconAgent checkout (commit bfada09); the "
        "caller must also spawn this process with cwd set to this same path",
    )
    args = parser.parse_args(argv)
    upstream_root = Path(args.upstream_root).resolve()
    src_dir = str(upstream_root)
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    exit_code = 0
    while True:
        line = sys.stdin.readline()
        if not line:
            break  # EOF: caller closed stdin, e.g. after one-shot use.
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
            response, keep_serving = _dispatch(request, upstream_root)
        except Exception as error:  # noqa: BLE001 - reported as a structured infra failure
            response = {
                "ok": False,
                "error_type": type(error).__name__,
                "message": str(error),
            }
            keep_serving = False
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
        if not response.get("ok"):
            exit_code = 1
        if not keep_serving:
            break
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
