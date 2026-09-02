"""Independent oracle-vs-adapter parity harness for econagent_v1 (spec section 5).

For each pilot scenario, this module runs upstream's own
``foundation.make_env_instance`` + ``simulate.complex_actions`` loop TWO
independent ways and compares them field by field, using the shared
kernel's own ``aeread.shared_runner.parity`` primitives (mirroring
``tau3_retail/parity.py``'s pattern):

* **oracle** -- :func:`run_oracle` spawns a short-lived subprocess running a
  small, self-contained script (never importing anything from
  ``econagent_bridge_driver.py``) that constructs the env, drives
  ``complex_actions``/``env.step`` directly, and reads the terminal state off
  the live ``env`` object itself. This is independent on purpose: reusing
  ``econagent_bridge_driver.py`` for "the oracle" would only prove the
  driver agrees with itself, which proves nothing about whether the
  adapter's own orchestration (``environment.py``'s ``step()``/``terminal()``)
  introduces any divergence.
* **adapter** -- runs the identical scenario through the real
  ``EconAgentV1Plugin`` (``initial_state``/``step``/``terminal``), the
  actual kernel-facing code path, via ``econagent_bridge_driver.py``.

Per spec section 5: "require the adapter's per-agent terminal
``inventory['Coin']``, cumulative ``tax_paid``, and dense_log length match
the oracle's exactly." This is the delegate-not-reimplement proof: the
adapter must not silently diverge from a bare call into the same upstream
code.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.parity import ParityField, ParityReport, ParitySpec, compare_projections
from aeread.shared_runner.registry import PluginRegistry

from .econagent_bridge import discover_bridge_python
from .environment import EconAgentV1Plugin, register_plugin

# A standalone script, deliberately NOT importing econagent_bridge_driver.py
# (see module docstring): constructs the env and drives complex_actions/
# env.step directly, reading the request off stdin and writing one JSON
# response line to stdout. Run with cwd=<upstream_root> for the same
# cwd-relative-read reasons econagent_bridge_driver.py documents.
_ORACLE_SCRIPT = """
import json
import sys

sys.path.insert(0, ".")
import yaml
import ai_economist.foundation as foundation
from simulate import complex_actions

request = json.loads(sys.stdin.readline())
with open("config.yaml", "r", encoding="utf-8") as handle:
    run_configuration = yaml.safe_load(handle)
env_config = run_configuration["env"]
env_config["n_agents"] = int(request["n_agents"])
env_config["episode_length"] = int(request["episode_length"])
env_config["seed"] = int(request["world_seed"]) + 1

env = foundation.make_env_instance(**env_config)
obs = env.reset()
for _ in range(int(request["episode_length"])):
    actions = complex_actions(
        env,
        obs,
        beta=float(request["beta"]),
        gamma=float(request["gamma"]),
        h=float(request["h"]),
    )
    obs, _rew, _done, _info = env.step(actions)

final_inventory_coin = {}
for agent in env.all_agents:
    idx = str(agent.idx)
    if idx == "p":
        continue
    final_inventory_coin[idx] = float(agent.inventory["Coin"])

cumulative_tax_paid = {idx: 0.0 for idx in final_inventory_coin}
tax_component = env.get_component("PeriodicBracketTax")
for month_tax in tax_component.taxes:
    for idx in final_inventory_coin:
        entry = month_tax.get(idx) if isinstance(month_tax, dict) else None
        if entry:
            cumulative_tax_paid[idx] += float(entry["tax_paid"])

print(json.dumps({
    "final_inventory_coin": final_inventory_coin,
    "cumulative_tax_paid": cumulative_tax_paid,
    "dense_log_length": len(env.dense_log["states"]),
}))
"""

PARITY_SPEC = ParitySpec(
    parity_id="econagent_v1_pilot_parity",
    parity_version="1.0.0",
    fields=(
        ParityField("final_inventory_coin", ("final_inventory_coin",), ("final_inventory_coin",)),
        ParityField("cumulative_tax_paid", ("cumulative_tax_paid",), ("cumulative_tax_paid",)),
        ParityField("dense_log_length", ("dense_log_length",), ("dense_log_length",)),
    ),
)


class ParityRunError(RuntimeError):
    """A scenario could not be run at all by one side (distinct from a diverged field)."""


@dataclass(frozen=True, slots=True)
class OracleResult:
    final_inventory_coin: Mapping[str, float]
    cumulative_tax_paid: Mapping[str, float]
    dense_log_length: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_inventory_coin": dict(self.final_inventory_coin),
            "cumulative_tax_paid": dict(self.cumulative_tax_paid),
            "dense_log_length": self.dense_log_length,
        }


def _subprocess_env() -> dict[str, str]:
    import os

    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def run_oracle(
    *,
    upstream_root: Path,
    python_executable: Path,
    n_agents: int,
    episode_length: int,
    world_seed: int,
    beta: float = 0.1,
    gamma: float = 0.1,
    h: float = 1.0,
    timeout_seconds: float = 120.0,
) -> OracleResult:
    """Run upstream's own ``complex_actions`` loop, independent of the adapter.

    Never imports or reuses ``econagent_bridge_driver.py`` (see module
    docstring) -- this is a genuinely separate implementation of "construct
    env, drive complex_actions/env.step episode_length times", so agreement
    with the adapter's own run is real evidence, not a driver agreeing with
    itself.
    """
    request = {
        "n_agents": n_agents,
        "episode_length": episode_length,
        "world_seed": world_seed,
        "beta": beta,
        "gamma": gamma,
        "h": h,
    }
    try:
        process = subprocess.run(
            [str(python_executable), "-c", _ORACLE_SCRIPT],
            cwd=str(upstream_root),
            input=json.dumps(request) + "\n",
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=_subprocess_env(),
        )
    except subprocess.TimeoutExpired as error:
        raise ParityRunError(f"oracle subprocess timed out after {timeout_seconds}s") from error
    except OSError as error:
        raise ParityRunError(f"could not spawn oracle subprocess: {error}") from error
    if process.returncode != 0:
        raise ParityRunError(
            f"oracle subprocess failed (exit={process.returncode}):\n{process.stderr}"
        )
    lines = [line for line in process.stdout.strip().splitlines() if line.strip()]
    if not lines:
        raise ParityRunError(f"oracle subprocess produced no output; stderr:\n{process.stderr}")
    response = json.loads(lines[-1])
    return OracleResult(
        final_inventory_coin=response["final_inventory_coin"],
        cumulative_tax_paid=response["cumulative_tax_paid"],
        dense_log_length=response["dense_log_length"],
    )


def run_adapter(
    *,
    upstream_root: Path,
    n_agents: int,
    episode_length: int,
    world_seed: int,
    pins: Mapping[str, Any],
    beta: float = 0.1,
    gamma: float = 0.1,
    h: float = 1.0,
) -> OracleResult:
    """Run the identical scenario through the real kernel-facing adapter path.

    Uses ``EconAgentV1Plugin`` directly (``initial_state``/``step``/
    ``terminal``) -- the actual code path a scheduled episode runs, not a
    reimplementation of it.
    """
    plugin = EconAgentV1Plugin(upstream_root=upstream_root)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)

    payload = {
        "scenario": {
            "case_id": "econagent.parity.adhoc",
            "n_agents": n_agents,
            "episode_length": episode_length,
            "world_seed": world_seed,
            "beta": beta,
            "gamma": gamma,
            "h": h,
            "purpose": "parity harness",
        },
        "pins": dict(pins),
    }
    family_case = plugin.validate_payload(payload)
    phase = plugin.phases(family_case)[0]
    state = plugin.initial_state(family_case, cell=None)
    while state["termination"] is None:
        actors = plugin.eligible_actors(family_case, state, phase)
        actions = {
            seat: plugin.parse_action(family_case, state, seat, phase, {"acknowledge": True})
            for seat in actors
        }
        transition = plugin.step(family_case, state, phase, actions)
        state = transition.state
    terminal = plugin.terminal(family_case, state)

    final_inventory_coin = {
        agent_id: float(agent_state["inventory"]["Coin"])
        for agent_id, agent_state in terminal["final_agents"].items()
    }
    cumulative_tax_paid = {agent_id: 0.0 for agent_id in final_inventory_coin}
    for month_tax in terminal["dense_log"]["PeriodicTax"]:
        for agent_id in final_inventory_coin:
            entry = month_tax.get(agent_id)
            if entry:
                cumulative_tax_paid[agent_id] += float(entry["tax_paid"])

    return OracleResult(
        final_inventory_coin=final_inventory_coin,
        cumulative_tax_paid=cumulative_tax_paid,
        dense_log_length=len(terminal["dense_log"]["states"]),
    )


@dataclass(frozen=True, slots=True)
class ScenarioParityResult:
    scenario_id: str
    status: str  # "ran" | "error"
    reason: str | None
    report: ParityReport | None

    @property
    def matched(self) -> bool:
        return self.report is not None and self.report.status == "match"


def run_scenario_parity(
    *,
    upstream_root: Path,
    python_executable: Path,
    scenario_id: str,
    n_agents: int,
    episode_length: int,
    world_seed: int,
    pins: Mapping[str, Any],
    beta: float = 0.1,
    gamma: float = 0.1,
    h: float = 1.0,
) -> ScenarioParityResult:
    """Run and compare one scenario; never raises for an ordinary failure."""
    try:
        oracle = run_oracle(
            upstream_root=upstream_root,
            python_executable=python_executable,
            n_agents=n_agents,
            episode_length=episode_length,
            world_seed=world_seed,
            beta=beta,
            gamma=gamma,
            h=h,
        )
        adapted = run_adapter(
            upstream_root=upstream_root,
            n_agents=n_agents,
            episode_length=episode_length,
            world_seed=world_seed,
            pins=pins,
            beta=beta,
            gamma=gamma,
            h=h,
        )
    except Exception as error:  # noqa: BLE001 - reported as a typed per-scenario result
        return ScenarioParityResult(
            scenario_id=scenario_id,
            status="error",
            reason=f"{type(error).__name__}: {error}",
            report=None,
        )
    report = compare_projections(oracle.to_dict(), adapted.to_dict(), PARITY_SPEC)
    return ScenarioParityResult(scenario_id=scenario_id, status="ran", reason=None, report=report)


__all__ = [
    "OracleResult",
    "PARITY_SPEC",
    "ParityRunError",
    "ScenarioParityResult",
    "discover_bridge_python",
    "run_adapter",
    "run_oracle",
    "run_scenario_parity",
]
