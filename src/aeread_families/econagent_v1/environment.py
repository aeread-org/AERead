"""Kernel family plugin for the pinned upstream EconAgent ``complex`` policy.

The kernel schedules one month at a time. All ``n_agents`` seats act
simultaneously every month (Mode C: ``mode="simultaneous"``, mirroring
``housing_v1``'s ``contact``/``respond``/``commit`` phases) in a single
self-looping ``agent_month`` phase. Per
``docs/econagent_adapter_spec.md``'s milestone-1 correction 4, each seat's
declared action this pass is a trivial acknowledgment, not a decomposed
``[labor, consumption]`` decision: the real ``complex_actions`` computation
happens once per month inside the persistent bridge subprocess, which also
applies ``env.step``. Only ``step`` calls the bridge or changes the canonical
family state.
"""
from __future__ import annotations

import copy
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.scheduler import (
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
)

from .cases import (
    EXPECTED_BRACKET_SCHEDULE,
    FAMILY_ID,
    FAMILY_VERSION,
    POLICY_MODEL,
    TERMINATION_REASONS,
    UPSTREAM_COMMIT,
    UPSTREAM_REPO,
)
from . import measurement
from .econagent_bridge import EconAgentBridge

PLUGIN_ID = "econagent_v1_environment"
SCORER_ID = "econagent_v1_scorer"
AGENT_MONTH_PHASE = "agent_month"

_SCENARIO_FIELDS = {
    "case_id",
    "n_agents",
    "episode_length",
    "world_seed",
    "beta",
    "gamma",
    "h",
    "purpose",
}
_PINS_REQUIRED_FIELDS = {
    "upstream_repo",
    "upstream_commit",
    "config_yaml_sha256",
    "config_yaml_bytes",
    "profiles_json_sha256",
    "profiles_json_bytes",
    "bracket_schedule",
    "policy_model",
    "env_config_sha256",
}


def _set_termination(state: dict[str, Any], reason: str) -> None:
    """Record a termination reason, refusing one the case never declared.

    The case manifest publishes ``TERMINATION_REASONS`` as this family's
    termination vocabulary. Nothing in the kernel cross-checks a terminal
    reason against that declaration at runtime, so without this the two
    could drift silently -- see ``tau3_retail/environment.py``'s identical
    helper and docstring for the incident that motivated it there.
    """
    if reason not in TERMINATION_REASONS:
        raise ValueError(
            f"termination reason {reason!r} is not declared by this family; "
            f"declared reasons are {list(TERMINATION_REASONS)}"
        )
    state["termination"] = reason


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


def _sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def family_manifest() -> FamilyManifest:
    """Return the strict family declaration used by the trusted registry."""
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {
                "id": FAMILY_ID,
                "version": FAMILY_VERSION,
                "plugin_id": PLUGIN_ID,
            },
            "environment": {
                "topology": "simultaneous_multiagent_economy",
                "phase_specs": [AGENT_MONTH_PHASE],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {
                "agent": {"testable": True, "scripted_policies": [POLICY_MODEL]},
            },
            "measurement": {
                # No weighted scalar and no declared optimum this pass (spec
                # section 2/6): the two rule_constraint accounting leaves and
                # the baseline-only macro diagnostics are a vector, not
                # collapsed into a single maximize/minimize estimand.
                "primary_estimand": "econagent_budget_identity",
                "measurement_kind": "property_or_answer",
                "direction": "none",
                "outcome_support": "pass_fail",
            },
            "scoring": {"scorer_id": SCORER_ID},
        }
    )


def register_plugin(
    registry: PluginRegistry,
    *,
    plugin: "EconAgentV1Plugin | None" = None,
    upstream_root: Path | str | None = None,
    bridge_factory: Callable[[], EconAgentBridge] | None = None,
) -> "EconAgentV1Plugin":
    """Register one exact family/version binding in the kernel registry."""
    if plugin is None:
        if upstream_root is None:
            raise ValueError("upstream_root is required when plugin is not supplied")
        plugin = EconAgentV1Plugin(upstream_root=upstream_root, bridge_factory=bridge_factory)
    registry.register_trusted(family_manifest(), plugin)
    return plugin


class EconAgentV1Plugin:
    """The complete family-owned hook boundary required by ``PluginRegistry``.

    Unlike ``tau3_retail``'s plugin (one shared, stateless ``Tau2Bridge``),
    this plugin holds a *registry of live episode sessions* keyed by a
    ``bridge_session_id`` stored in each episode's own ``state`` dict -- one
    persistent bridge subprocess per in-flight episode, since
    ``complex_actions`` needs the live upstream ``env`` object for the whole
    episode (spec milestone-1 correction 3). Sessions are removed as soon as
    ``step`` observes the episode's terminal month.

    ``bridge_session_id`` is derived deterministically from the real
    scheduler's own ``cell.cell_id`` (see ``initial_state``/
    ``_mint_session_id``) rather than minted at random, so that two
    independent runs of the identical case/plan/seed -- notably a live run
    and its own offline replay (``replay.py``), both driven through the same
    ``cell`` -- produce byte-identical canonical state, not merely
    semantically equivalent content.
    """

    def __init__(
        self,
        *,
        upstream_root: Path | str,
        bridge_factory: Callable[[], EconAgentBridge] | None = None,
    ) -> None:
        self.upstream_root = Path(upstream_root)
        self._bridge_factory = bridge_factory or (
            lambda: EconAgentBridge.discover(self.upstream_root)
        )
        self._sessions: dict[str, EconAgentBridge] = {}

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = _plain(payload)
        if set(data) != {"scenario", "pins"}:
            raise ValueError("payload must contain exactly scenario and pins")
        scenario = data["scenario"]
        pins = data["pins"]
        if not isinstance(scenario, dict) or not isinstance(pins, dict):
            raise ValueError("payload.scenario and payload.pins must be objects")
        if set(scenario) != _SCENARIO_FIELDS:
            raise ValueError(f"payload.scenario fields must be exactly {_SCENARIO_FIELDS}")
        if not isinstance(scenario.get("case_id"), str) or not scenario["case_id"]:
            raise ValueError("payload.scenario.case_id must be a non-empty string")
        n_agents = scenario.get("n_agents")
        if not isinstance(n_agents, int) or isinstance(n_agents, bool) or n_agents < 2:
            # Matches upstream's own BaseEnvironment `assert n_agents >= 2`.
            raise ValueError("payload.scenario.n_agents must be an integer >= 2")
        episode_length = scenario.get("episode_length")
        if (
            not isinstance(episode_length, int)
            or isinstance(episode_length, bool)
            or episode_length < 1
        ):
            raise ValueError("payload.scenario.episode_length must be a positive integer")
        world_seed = scenario.get("world_seed")
        if not isinstance(world_seed, int) or isinstance(world_seed, bool) or world_seed < 0:
            raise ValueError("payload.scenario.world_seed must be a non-negative integer")
        for hyperparameter in ("beta", "gamma", "h"):
            value = scenario.get(hyperparameter)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"payload.scenario.{hyperparameter} must be numeric")
        if not isinstance(scenario.get("purpose"), str) or not scenario["purpose"]:
            raise ValueError("payload.scenario.purpose must be a non-empty string")

        if _PINS_REQUIRED_FIELDS - set(pins):
            raise ValueError(
                f"payload.pins is missing fields: {_PINS_REQUIRED_FIELDS - set(pins)}"
            )
        if set(pins) - _PINS_REQUIRED_FIELDS - {"env_config_sha256_unavailable_reason"}:
            raise ValueError("payload.pins has unexpected fields")
        if pins.get("upstream_repo") != UPSTREAM_REPO:
            raise ValueError("payload pins the wrong upstream repository")
        if pins.get("upstream_commit") != UPSTREAM_COMMIT:
            raise ValueError("payload pins the wrong upstream commit")
        if pins.get("policy_model") != POLICY_MODEL:
            raise ValueError("payload pins a policy model other than 'complex'")
        if pins.get("bracket_schedule") != EXPECTED_BRACKET_SCHEDULE:
            raise ValueError("payload pins an unexpected tax-bracket schedule")
        env_config_sha256 = pins.get("env_config_sha256")
        if env_config_sha256 is None:
            if not isinstance(pins.get("env_config_sha256_unavailable_reason"), str):
                raise ValueError(
                    "a null env_config_sha256 requires an explicit derivation gap"
                )
        elif (
            not isinstance(env_config_sha256, str)
            or len(env_config_sha256) != 64
            or any(character not in "0123456789abcdef" for character in env_config_sha256)
        ):
            raise ValueError("payload.pins.env_config_sha256 is malformed")

        revision = subprocess.run(
            ["git", "-C", str(self.upstream_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if revision.returncode != 0:
            raise ValueError(
                "upstream_root is not a readable git checkout: "
                f"{revision.stderr.strip()}"
            )
        if not revision.stdout.strip().startswith(UPSTREAM_COMMIT):
            raise ValueError(
                "upstream checkout revision mismatch: "
                f"expected a prefix of {UPSTREAM_COMMIT!r}, got {revision.stdout.strip()!r}"
            )
        status = subprocess.run(
            ["git", "-C", str(self.upstream_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        if status.returncode != 0 or status.stdout:
            raise ValueError("upstream checkout must be clean at the pinned revision")

        config_path = self.upstream_root / "config.yaml"
        profiles_path = self.upstream_root / "data" / "profiles.json"
        for pin_name, path in (
            ("config_yaml_sha256", config_path),
            ("profiles_json_sha256", profiles_path),
        ):
            if not path.is_file():
                raise ValueError(f"pinned upstream file is missing: {path}")
            actual = _sha256_file(path)
            if pins.get(pin_name) != actual:
                raise ValueError(
                    f"payload {pin_name} mismatch: authored {pins.get(pin_name)!r}, "
                    f"actual {actual!r}"
                )
        if pins.get("config_yaml_bytes") != config_path.stat().st_size:
            raise ValueError("payload config_yaml_bytes does not match pinned config.yaml")
        if pins.get("profiles_json_bytes") != profiles_path.stat().st_size:
            raise ValueError(
                "payload profiles_json_bytes does not match pinned data/profiles.json"
            )
        return data

    def initial_state(self, family_case: Mapping[str, Any], cell: Any) -> dict[str, Any]:
        scenario = family_case["scenario"]
        bridge = self._bridge_factory()
        bridge.start_episode(
            n_agents=scenario["n_agents"],
            episode_length=scenario["episode_length"],
            world_seed=scenario["world_seed"],
            beta=scenario["beta"],
            gamma=scenario["gamma"],
            h=scenario["h"],
        )
        session_id = self._mint_session_id(cell)
        self._sessions[session_id] = bridge
        snapshot = bridge.agent_snapshot()
        return {
            "bridge_session_id": session_id,
            "n_agents": scenario["n_agents"],
            "episode_length": scenario["episode_length"],
            "timestep": 0,
            "termination": None,
            "agents": snapshot["agents"],
            "world": snapshot["world"],
            "month_actions": [],
            # One entry appended per step() call, before that month's
            # mutation (see step()'s own comment) -- the world_interest_rate
            # that will actually be applied to compute *this* month's
            # saving-interest payoff, per measurement.py's
            # econagent_budget_identity leaf. Reading it back out of a
            # finished dense_log instead would be wrong for any boundary
            # month past the first: upstream's own SimpleSaving may already
            # have advanced world.interest_rate to the *next* boundary
            # month's rate by the time dense_log is read.
            "world_interest_rate_by_month": [],
            # Populated only at termination (see step()) -- the full,
            # per-component upstream dense log (spec section 2's
            # rule_constraint leaves read every term from this, never
            # recomputing accounting independently). None until then, never
            # a fabricated placeholder.
            "dense_log": None,
        }

    def phases(self, family_case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        episode_length = int(family_case["scenario"]["episode_length"])
        n_agents = int(family_case["scenario"]["n_agents"])
        return (
            PhaseSpec(
                phase_id=AGENT_MONTH_PHASE,
                actor_selector="all_agents",
                mode="simultaneous",
                observation_schema_by_role={"agent": "econagent_v1_month_observation_v1"},
                action_schema_by_role={"agent": "econagent_v1_month_ack_v1"},
                # One logical action per agent seat per month (this
                # self-looping phase covers all `episode_length` months) --
                # matches `cases.py`'s identical `n_agents * episode_length`
                # budget and `housing_v1`'s `num_tenants * rounds` convention
                # for its own simultaneous, self-looping phases. See
                # cases.py's `build_case` docstring comment (milestone-3
                # correction) for the SchedulerContractError this fixes.
                max_logical_actions=n_agents * episode_length,
                invalid_action_policy="reject",
                next_phases=(AGENT_MONTH_PHASE,),
            ),
        )

    def eligible_actors(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
    ) -> tuple[str, ...]:
        del state
        if phase.phase_id != AGENT_MONTH_PHASE:
            raise ValueError(f"unknown phase: {phase.phase_id}")
        n_agents = int(family_case["scenario"]["n_agents"])
        return tuple(f"agent_{index}" for index in range(n_agents))

    def observe(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
    ) -> dict[str, Any]:
        if phase.phase_id != AGENT_MONTH_PHASE or not seat_id.startswith("agent_"):
            raise ValueError(f"seat {seat_id!r} is not active in phase {phase.phase_id!r}")
        agent_index = seat_id[len("agent_") :]
        agent_state = state["agents"].get(agent_index)
        if agent_state is None:
            raise ValueError(f"no live agent state for seat {seat_id!r}")
        del family_case
        return {
            "agent_index": agent_index,
            "month": state["timestep"],
            "episode_length": state["episode_length"],
            "inventory": agent_state["inventory"],
            "income": agent_state["income"],
            "consumption": agent_state["consumption"],
            "saving": agent_state["saving"],
            "endogenous": agent_state["endogenous"],
            "skill": agent_state["skill"],
            "expected_skill": agent_state["expected_skill"],
            "world_price": state["world"]["price"],
            "world_interest_rate": state["world"]["interest_rate"],
        }

    def parse_action(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        response: Any,
    ) -> ParseResult:
        del family_case, state
        if phase.phase_id != AGENT_MONTH_PHASE or not seat_id.startswith("agent_"):
            return ParseResult.failure("seat_phase_mismatch")
        if not isinstance(response, Mapping):
            return ParseResult.failure("response_not_object")
        raw = _plain(response)
        if set(raw) != {"acknowledge"} or raw["acknowledge"] is not True:
            return ParseResult.failure("invalid_month_ack")
        return ParseResult.success({"acknowledge": True})

    def legal(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        action: Mapping[str, Any],
    ) -> LegalityResult:
        del family_case, state, action
        if phase.phase_id != AGENT_MONTH_PHASE or not seat_id.startswith("agent_"):
            return LegalityResult.illegal("seat_phase_mismatch")
        return LegalityResult.legal_action()

    def step(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
        actions: Mapping[str, Any],
    ) -> TransitionResult:
        if phase.phase_id != AGENT_MONTH_PHASE:
            raise ValueError(f"unknown phase: {phase.phase_id}")
        n_agents = int(family_case["scenario"]["n_agents"])
        if len(actions) != n_agents:
            raise RuntimeError(
                f"expected acknowledgments from all {n_agents} agent seats, got "
                f"{len(actions)}"
            )

        new_state = _plain(state)
        bridge = self._require_session(new_state["bridge_session_id"])
        # Captured BEFORE bridge.step_month() mutates anything: this is the
        # rate upstream's own SimpleSaving is about to apply for THIS month
        # (whether or not this month is actually a saving-interest boundary
        # month), i.e. `state["world"]["interest_rate"]` as of the end of
        # the previous month -- see measurement.py's
        # `compute_budget_identity_residuals` docstring for why reading it
        # back out of the finished dense_log instead would be wrong for any
        # boundary month past the first.
        pre_step_interest_rate = new_state["world"]["interest_rate"]
        result = bridge.step_month()
        snapshot = bridge.agent_snapshot()

        new_state["timestep"] = result["timestep"]
        new_state["agents"] = snapshot["agents"]
        new_state["world"] = snapshot["world"]
        new_state["month_actions"] = list(new_state["month_actions"]) + [result["actions"]]
        new_state["world_interest_rate_by_month"] = list(
            new_state["world_interest_rate_by_month"]
        ) + [pre_step_interest_rate]

        if result["done"] or new_state["timestep"] >= new_state["episode_length"]:
            # Upstream's own per-component dense log (e.g. "PeriodicTax") is
            # only backfilled by env's _finalize_logs() once this LAST
            # step_month() has completed -- must be read now, before the
            # session closes (see econagent_bridge.py's dense_log()
            # docstring). Read before close(): a bridge failure fetching it
            # must surface as the same typed EconAgentBridgeError a mid-
            # episode failure would, never a silently-terminal episode with
            # missing evidence.
            new_state["dense_log"] = bridge.dense_log()
            _set_termination(new_state, "episode_length_reached")
            bridge.close()
            self._sessions.pop(new_state["bridge_session_id"], None)

        return TransitionResult(
            state=new_state,
            next_phase_id=(None if new_state["termination"] else AGENT_MONTH_PHASE),
            consequences={"months_elapsed": 1, "tool_calls": 0},
        )

    def terminal(
        self, family_case: Mapping[str, Any], state: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        del family_case
        reason = state["termination"]
        if reason is None:
            return None
        return {
            "reason": reason,
            "timestep": state["timestep"],
            "episode_length": state["episode_length"],
            "n_agents": state["n_agents"],
            "final_agents": state["agents"],
            "final_world": state["world"],
            "month_actions": state["month_actions"],
            "world_interest_rate_by_month": state["world_interest_rate_by_month"],
            "dense_log": state["dense_log"],
        }

    def outcome(
        self, family_case: Mapping[str, Any], terminal: Mapping[str, Any]
    ) -> dict[str, Any]:
        del family_case
        return {
            "termination_reason": terminal["reason"],
            "timestep": terminal["timestep"],
            "n_agents": terminal["n_agents"],
            "final_inventory_coin": {
                agent_index: agent_state["inventory"]["Coin"]
                for agent_index, agent_state in terminal["final_agents"].items()
            },
        }

    def build_scorer(self, family_case: Mapping[str, Any]) -> Any:
        """Return the one ``EconAgentV1Scorer`` declaring this case's leaves.

        Built in milestone 2 (measurement.py) -- the two ``rule_constraint``
        accounting leaves and the ``baseline_only`` macro diagnostics (spec
        section 2). Only the leaves are declared here; scoring itself
        happens against a terminated episode's ``terminal()`` output (see
        ``measurement.score_budget_identity``/``score_tax_bracket_arithmetic``/
        ``score_macro_trajectory``, mirroring ``tau3_retail``'s identical
        split between "declare the leaves" and "score a specific episode").
        """
        scenario = family_case["scenario"]
        pins = family_case["pins"]
        return measurement.build_scorer(scenario, pins)

    def build_reference_providers(self, family_case: Mapping[str, Any]) -> tuple[Any, ...]:
        del family_case
        return ()

    def generator(self, family_case: Mapping[str, Any]) -> None:
        del family_case
        return None

    def _mint_session_id(self, cell: Any) -> str:
        """Choose this episode's ``bridge_session_id`` (docs/econagent_codex_triage.md
        finding 6).

        Deterministic whenever the real scheduler supplies a ``cell``: its
        own ``cell_id`` already uniquely identifies one case x block x seed
        x repetition execution unit (see ``PlanCell``), so two independent
        runs of the identical logical episode -- a live run and its own
        offline replay, both driven through ``run_episode``/
        ``replay_episode`` with the same ``cell`` -- mint the identical
        ``bridge_session_id`` and therefore byte-identical canonical state
        (``pre_state_sha256``/``post_state_sha256``/``final_state``), not
        merely semantically equivalent content. Raises if that same cell
        already has an active session -- the same plan cell must never be
        started twice concurrently in one plugin instance, since sessions
        are looked up by this id alone (``_require_session``).

        Falls back to a fresh random id only when ``cell`` is ``None`` --
        a handful of tests call ``initial_state`` directly, bypassing the
        real scheduler entirely, and never feed the result into a cross-run
        canonical-state comparison.
        """
        cell_id = getattr(cell, "cell_id", None)
        if cell_id is None:
            return uuid.uuid4().hex
        session_id = f"econagent_v1:{cell_id}"
        if session_id in self._sessions:
            raise RuntimeError(
                f"a bridge session for cell {cell_id!r} is already active; "
                "the same plan cell must never be started twice concurrently"
            )
        return session_id

    def _require_session(self, session_id: str) -> EconAgentBridge:
        bridge = self._sessions.get(session_id)
        if bridge is None:
            raise RuntimeError(
                f"no active bridge session {session_id!r}; initial_state must run first "
                "and the episode must not already be terminal"
            )
        return bridge


__all__ = [
    "AGENT_MONTH_PHASE",
    "PLUGIN_ID",
    "SCORER_ID",
    "EconAgentV1Plugin",
    "family_manifest",
    "register_plugin",
]
