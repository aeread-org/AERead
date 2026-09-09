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
import hashlib
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

from aeread.shared_runner import canonical_json_bytes
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
                # kernel_scoring_contract_spec.md section 3: every leaf this
                # family publishes at finalize time, exactly one primary, and
                # precisely the leaves that gate admission -- declared here,
                # the one source of truth, never inferred from
                # ``build_scorer`` or a test fixture. All three are
                # ``scope="finalize_time"``: every leaf in measurement.py is
                # ``evaluation_class="deterministic"`` with no judge, rater,
                # or other not-yet-existing artifact dependency (spec
                # section 4), so none is ``deferred``. See
                # docs/econagent_adapter_status.md's "Leaf policy" section
                # for why ``econagent_budget_identity`` is primary and why it
                # and ``econagent_tax_bracket_arithmetic`` alone gate
                # admission.
                "leaves": [
                    {"leaf_id": measurement.BUDGET_IDENTITY_LEAF_ID, "scope": "finalize_time"},
                    {"leaf_id": measurement.TAX_BRACKET_LEAF_ID, "scope": "finalize_time"},
                    {"leaf_id": measurement.MACRO_TRAJECTORY_LEAF_ID, "scope": "finalize_time"},
                ],
                "primary_leaf_id": measurement.BUDGET_IDENTITY_LEAF_ID,
                "admission_leaf_ids": [
                    measurement.BUDGET_IDENTITY_LEAF_ID,
                    measurement.TAX_BRACKET_LEAF_ID,
                ],
            },
            # `measurement.py` gives each leaf's validity-domain predicate
            # and verifier-reference implementation a component id distinct
            # from that leaf's own scorer id (unlike, e.g.,
            # procurement_grounding's single leaf, which reuses `scorer_id`
            # itself for both) -- `resolve_run_plan`'s own pin bookkeeping
            # only requires and admits a pin for a component named here or
            # as `scorer_id` (`_required_pin_kinds`), and
            # `EvaluationReceipt._validate_and_freeze_plan_pins` requires
            # every leaf-declared implementation ref to match one, so every
            # one of these seven must be declared as a reference provider
            # (mirrors govsim's identically-motivated `reference_provider_ids`).
            "scoring": {
                "scorer_id": SCORER_ID,
                "reference_provider_ids": [
                    measurement.DOMAIN_PREDICATE_ID,
                    measurement.BUDGET_IDENTITY_REFERENCE_IMPLEMENTATION_ID,
                    measurement.TAX_BRACKET_REFERENCE_IMPLEMENTATION_ID,
                    measurement.MACRO_TRAJECTORY_REFERENCE_IMPLEMENTATION_ID,
                    measurement.BUDGET_IDENTITY_SCORER_ID,
                    measurement.TAX_BRACKET_SCORER_ID,
                    measurement.MACRO_TRAJECTORY_SCORER_ID,
                ],
            },
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

    #135 A1/A2: the KERNEL's own generic replay
    (``task.evaluation._replay_family_trajectory``, driving
    ``replay_family_scoring_input``/``finalize_family_execution``/
    ``replay_family_receipt``/``audit_family_receipt``) now receives the
    actual executed ``PlanCell`` and checks its identity against the sealed
    evidence before ``initial_state`` is ever called -- certified replay is
    cell-bound, the same as a live run, so its minted
    ``bridge_session_id`` always matches the live run's own. The no-``cell``
    fallback in ``_mint_session_id`` below therefore no longer serves
    certified kernel replay at all; it remains deterministic (derived only
    from ``family_case``'s own canonical digest, never from order or from
    any other cell's mint) for the narrower case of a direct,
    unsealed parity call that bypasses the real scheduler entirely (e.g. a
    handful of this family's own tests that call ``initial_state`` directly
    with no real ``PlanCell``). See ``_mint_session_id``'s own docstring.
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

    def initial_state(self, family_case: Mapping[str, Any], run: Any) -> dict[str, Any]:
        """Build the initial family state for one episode.

        The second parameter is named ``run`` (not ``cell``) to match every
        other family's own ``initial_state`` hook. #135 A1:
        ``task.evaluation._replay_family_trajectory`` now calls
        ``plugin.initial_state(family_case, cell)`` by keyword with the real,
        sealed-evidence-checked ``PlanCell`` (kernel_scoring_contract_spec.md's
        ``replay_family_scoring_input`` contract); the live scheduler
        (``task.scheduler.run_episode``) still passes the same value
        positionally, so this rename does not change what value actually
        arrives here (see ``_mint_session_id``'s own docstring, which still
        calls this parameter ``cell`` -- it is the same value, renamed only
        at this call boundary). Only a direct, unsealed parity call that
        bypasses the real scheduler entirely still calls this with
        ``run=None``.
        """
        scenario = family_case["scenario"]
        # Mint (and, per review finding 1/3, evict any stale entry for) the
        # session id BEFORE starting the new bridge subprocess: a malformed
        # cell (review finding 2) then raises before anything is spawned,
        # rather than leaking a started-but-never-registered bridge.
        session_id = self._mint_session_id(run, family_case)
        bridge = self._bridge_factory()
        bridge.start_episode(
            n_agents=scenario["n_agents"],
            episode_length=scenario["episode_length"],
            world_seed=scenario["world_seed"],
            beta=scenario["beta"],
            gamma=scenario["gamma"],
            h=scenario["h"],
        )
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
        session_id = new_state["bridge_session_id"]
        bridge = self._require_session(session_id)
        # Captured BEFORE bridge.step_month() mutates anything: this is the
        # rate upstream's own SimpleSaving is about to apply for THIS month
        # (whether or not this month is actually a saving-interest boundary
        # month), i.e. `state["world"]["interest_rate"]` as of the end of
        # the previous month -- see measurement.py's
        # `compute_budget_identity_residuals` docstring for why reading it
        # back out of the finished dense_log instead would be wrong for any
        # boundary month past the first.
        pre_step_interest_rate = new_state["world"]["interest_rate"]
        try:
            result = bridge.step_month()
            snapshot = bridge.agent_snapshot()

            new_state["timestep"] = result["timestep"]
            new_state["agents"] = snapshot["agents"]
            new_state["world"] = snapshot["world"]
            new_state["month_actions"] = list(new_state["month_actions"]) + [
                result["actions"]
            ]
            new_state["world_interest_rate_by_month"] = list(
                new_state["world_interest_rate_by_month"]
            ) + [pre_step_interest_rate]

            if result["done"] or new_state["timestep"] >= new_state["episode_length"]:
                # Upstream's own per-component dense log (e.g. "PeriodicTax")
                # is only backfilled by env's _finalize_logs() once this LAST
                # step_month() has completed -- must be read now, before the
                # session closes (see econagent_bridge.py's dense_log()
                # docstring). Read before close(): a bridge failure fetching
                # it must surface as the same typed EconAgentBridgeError a
                # mid-episode failure would, never a silently-terminal
                # episode with missing evidence.
                new_state["dense_log"] = bridge.dense_log()
                _set_termination(new_state, "episode_length_reached")
                self._close_session(session_id)
        except Exception:
            # Review finding 1 ("exception poisoning"): a mid-episode
            # bridge failure (step_month/agent_snapshot/dense_log) must not
            # leave this session sitting in self._sessions forever with no
            # close hook ever having run for it. The kernel retries a
            # crashed attempt within the SAME process, and because identity
            # is cell-bound (_mint_session_id), the retry re-derives this
            # IDENTICAL session_id -- evict it here, before the exception
            # propagates, so the retry's own initial_state starts fresh
            # instead of being bricked by a stale, broken entry.
            # ``_evict_session``, not ``_close_session``: the bridge that
            # just failed is often ALREADY broken in a way that makes its
            # own ``close()`` raise too (e.g. a killed subprocess's stdin
            # pipe -- see tests/test_econagent_goldens.py's
            # ``test_golden_bridge_killed_mid_episode_...`` golden, which
            # deliberately never calls ``close()`` on such a bridge itself);
            # that secondary failure must never mask the original one.
            self._evict_session(session_id)
            raise

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

        The two ``rule_constraint`` accounting leaves and the
        ``baseline_only`` macro diagnostic (spec section 2) are declared in
        ``measurement.py``. ``task.evaluation.finalize_family_execution``
        calls the returned ``EconAgentV1Scorer`` directly
        (``plugin.build_scorer(family_case)(scoring_input,
        evidence_refs=scoring_input.evidence_refs)``, per
        kernel_scoring_contract_spec.md section 1);
        ``EconAgentV1Scorer.__call__`` is the seam that satisfies that call
        and returns every one of this family's three declared finalize-time
        leaves (section 5), not just the primary. Each leaf's own named
        ``score_*`` method is still exercised directly by
        ``tests/test_econagent_measurement.py``'s goldens today.
        ``bridge_factory=self._bridge_factory`` gives ``__call__`` the same
        live, stateless bridge handle a real episode's own scoring already
        uses for ``econagent_tax_bracket_arithmetic``'s
        ``recompute_tax`` re-invocation.
        """
        scenario = family_case["scenario"]
        pins = family_case["pins"]
        return measurement.build_scorer(scenario, pins, bridge_factory=self._bridge_factory)

    def build_reference_providers(self, family_case: Mapping[str, Any]) -> tuple[Any, ...]:
        del family_case
        return ()

    def generator(self, family_case: Mapping[str, Any]) -> None:
        del family_case
        return None

    def _mint_session_id(self, cell: Any, family_case: Mapping[str, Any]) -> str:
        """Choose this episode's ``bridge_session_id`` (docs/econagent_codex_triage.md
        finding 6, extended by #135 A1/A2 -- see this class's own docstring).

        Deterministic whenever the real scheduler (or certified kernel
        replay -- #135 A1 threads the real ``cell`` all the way through
        ``replay_family_scoring_input``/``finalize_family_execution``/
        ``replay_family_receipt``/``audit_family_receipt``) supplies a
        ``cell``: its own ``cell_id`` already uniquely identifies one case x
        block x seed x repetition execution unit (see ``PlanCell``), so
        every independent run/replay/audit of the identical logical episode
        -- all driven through the same ``cell`` -- mints the identical
        ``bridge_session_id`` and therefore byte-identical canonical state
        (``pre_state_sha256``/``post_state_sha256``/``final_state``), not
        merely semantically equivalent content. If that same cell already
        has an active session, EVICTS it (best-effort closes its bridge via
        ``_evict_session``) and proceeds rather than raising (review
        finding 1): the kernel retries a crashed attempt within the SAME
        process, and a step()/initial_state() failure partway through that
        attempt (see ``step``'s own ``except`` clause) must not brick the
        cell for every later attempt just because no earlier code path ever
        closed the dead entry. Evicting by id is safe precisely because
        identity is cell-bound -- the id a retry derives for this cell is
        always the SAME id the crashed attempt derived, so eviction can
        never select, or disturb, any OTHER cell's session. Two distinct
        cells of the identical case (e.g. two seeds of one
        ``family_case``, or a live run finalized/replayed/audited in any
        order relative to a sibling cell sharing one plugin instance) never
        collide and never interact: each cell's id depends only on its own
        ``cell_id``, never on mint order or on what any other cell minted
        before it (#135 A2 -- this previously went through a case-keyed
        FIFO queue that made the no-``cell`` fallback below depend on the
        order REAL cells happened to mint in, which broke the moment a
        second cell of the same case was finalized/replayed/audited in
        the "wrong" order).

        Falls back to an id derived purely from ``family_case``'s own
        canonical digest only when ``cell`` is ``None`` -- now reached only
        by a direct, unsealed parity call that bypasses the real scheduler
        entirely (a handful of this family's own tests call
        ``initial_state`` directly with no real ``PlanCell``); #135 A1
        means certified kernel replay always supplies the real cell, so this
        fallback no longer needs to reproduce any specific live run's id.
        Deterministic and stable across repeated calls for the identical
        ``family_case`` -- never derived from, or perturbed by, any cell any
        caller minted before it. Two overlapping, unsealed calls for the
        identical ``family_case`` therefore mint the identical fallback id
        too; the same eviction above applies there (review finding 3) so
        the second call's own ``initial_state`` never silently overwrites
        ``self._sessions`` out from under the first call's still-unclosed
        bridge.

        A non-``None`` cell with no truthy ``cell_id`` is refused outright
        (``ValueError``, review finding 2) rather than silently routed onto
        the unsealed fallback above: a real ``PlanCell`` with a missing or
        empty ``cell_id`` is malformed, not "no cell was supplied," and must
        never be served the fallback's case-digest-only identity.
        """
        if cell is not None:
            cell_id = getattr(cell, "cell_id", None)
            if not cell_id:
                raise ValueError(
                    "EconAgent requires a PlanCell with cell_id for live "
                    "execution and certified replay"
                )
            session_id = f"econagent_v1:{cell_id}"
            self._evict_session(session_id)
            return session_id

        case_digest = hashlib.sha256(canonical_json_bytes(family_case)).hexdigest()
        session_id = f"econagent_v1:case:{case_digest}"
        self._evict_session(session_id)
        return session_id

    def _require_session(self, session_id: str) -> EconAgentBridge:
        bridge = self._sessions.get(session_id)
        if bridge is None:
            raise RuntimeError(
                f"no active bridge session {session_id!r}; initial_state must run first "
                "and the episode must not already be terminal"
            )
        return bridge

    def _close_session(self, session_id: str) -> None:
        """Close and forget one bridge session, tolerating there being none.

        Reused only by ``step``'s own NATURAL termination (the episode
        reached its last month cleanly): a ``bridge.close()`` failure there
        is a genuine, worth-surfacing problem (the bridge was healthy right
        up to this point), so unlike ``_evict_session`` below this
        propagates whatever ``bridge.close()`` itself raises -- exactly the
        behavior this call site had before ``_close_session`` existed as a
        named helper. A no-op when ``session_id`` has no active session,
        and tolerant of a bridge that was already closed
        (``EconAgentBridge.close()`` documents itself as idempotent).
        """
        bridge = self._sessions.pop(session_id, None)
        if bridge is not None:
            bridge.close()

    def _evict_session(self, session_id: str) -> None:
        """Evict one session, tolerating a bridge that cannot be cleanly closed.

        Reused by every "must make forward progress no matter what"
        cleanup path: stale-session eviction in ``_mint_session_id``
        (review findings 1 and 3) and ``step``'s own mid-episode-failure
        ``except`` clause (review finding 1). The bridge being evicted here
        is already known-broken -- that is WHY it is being evicted -- so a
        secondary ``bridge.close()`` failure on top of that (e.g. a
        SIGKILLed or already-crashed subprocess whose stdin pipe is itself
        already broken -- see ``tests/test_econagent_goldens.py``'s
        ``test_golden_bridge_killed_mid_episode_...`` golden, which
        deliberately never calls ``close()`` on such a bridge itself) must
        never block progress or mask a more important exception (the
        original bridge failure ``step``'s ``except`` clause is about to
        re-raise). Always pops ``session_id`` out of ``self._sessions``
        first -- so the id is free for a fresh session either way -- then
        best-effort closes, swallowing whatever ``bridge.close()`` raises.
        """
        bridge = self._sessions.pop(session_id, None)
        if bridge is None:
            return
        try:
            bridge.close()
        except Exception:
            pass


__all__ = [
    "AGENT_MONTH_PHASE",
    "PLUGIN_ID",
    "SCORER_ID",
    "EconAgentV1Plugin",
    "family_manifest",
    "register_plugin",
]
