"""Kernel family plugin for the pinned govsim common-pool-resource scenarios.

Mode C (simultaneous), mirroring ``housing_v1``'s ``contact/respond/commit``
phase-count style (docs/govsim_adapter_spec.md section 3.1):

  harvest   mode=simultaneous, seats=persona_0..persona_{N-1}
            -> one bridge call replaying 2N upstream env.step() calls
               (lake, then pool_after_harvesting, in agent_selector order --
               upstream's own fixed persona_0..N-1 cycle under
               harvesting_order="concurrent")
  discuss   mode=single, seat=persona_0 (fixed "spokesperson", matching
            upstream's own post-harvest cursor -- see the module docstring
            of ``govsim_bridge_driver.py``)
            -> one bridge call replaying 1 upstream env.step() call
               (an empty-conversation PersonaActionChat; no cheap talk in
               v1, spec section 6)
  reflect   mode=simultaneous, seats=persona_0..persona_{N-1}, housekeeping
            only
            -> one bridge call replaying N upstream env.step() calls; the
               last one triggers upstream's own regeneration + collapse
               check + threshold recompute
  -> loop to harvest, or terminal when upstream's own termination flag fires

Only ``step`` ever calls the bridge and changes the canonical family state;
``observe``/``terminal``/``eligible_actors``/``legal`` all read the last
state a ``step`` call returned.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.scheduler import (
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
)

from . import measurement, policies
from .cases import (
    ENV_CFG_FIELDS,
    FAMILY_ID,
    FAMILY_VERSION,
    SCENARIOS,
    TERMINATION_REASONS,
    UPSTREAM_COMMIT,
    UPSTREAM_REPO,
    _concurrent_env_path,
    _persona_common_path,
    _scenario_env_path,
    _sha256_file,
)
from .govsim_bridge import GovsimActionError, GovsimBridge

# cases.py's own convention: src/aeread_families/govsim/environment.py -> repo
# root is parents[3] (identical offset to cases.py's `_default_output_dir`,
# a sibling module in this same directory).
_PINS_PATH = Path(__file__).resolve().parents[3] / "cases" / "govsim" / "v1" / "pins.json"


def _verify_source_and_dependency_pins(
    upstream_root: Path, bridge: GovsimBridge | None
) -> None:
    """Confirm the pinned upstream source bytes -- and, when a bridge is
    available, its resolved runtime dependency versions -- match
    ``cases/govsim/v1/pins.json`` exactly (triage Finding 4).

    A clean git checkout at the pinned commit (``validate_payload``'s own
    ``git rev-parse``/``git status`` checks, immediately above this call)
    is not itself proof that the SPECIFIC files this adapter executes, or
    the interpreter running them, still match what the corpus was
    generated against: a checkout can be clean-and-at-the-right-commit
    while the individual pinned files have been altered outside git's view
    (e.g. an untracked overlay), and a bridge interpreter can resolve a
    different NumPy/pandas/OmegaConf/PettingZoo version than the one the
    corpus was pinned against without git ever noticing either. Raises
    ``ValueError`` naming every mismatch found, never just the first.
    """
    pins = json.loads(_PINS_PATH.read_text(encoding="utf-8"))
    mismatches: list[str] = []

    actual_concurrent = _sha256_file(_concurrent_env_path(upstream_root))
    if actual_concurrent != pins["concurrent_env_sha256"]:
        mismatches.append(
            "concurrent_env.py sha256 mismatch: pinned="
            f"{pins['concurrent_env_sha256']}, actual={actual_concurrent}"
        )

    actual_persona_common = _sha256_file(_persona_common_path(upstream_root))
    if actual_persona_common != pins["persona_common_sha256"]:
        mismatches.append(
            "simulation/persona/common.py sha256 mismatch: pinned="
            f"{pins['persona_common_sha256']}, actual={actual_persona_common}"
        )

    for scenario, pinned_sha256 in pins["scenario_env_sha256"].items():
        actual_sha256 = _sha256_file(_scenario_env_path(upstream_root, scenario))
        if actual_sha256 != pinned_sha256:
            mismatches.append(
                f"{scenario} env.py sha256 mismatch: pinned={pinned_sha256}, "
                f"actual={actual_sha256}"
            )

    pinned_versions = pins.get("bridge_versions")
    # Nothing to compare against when the corpus was generated without a
    # bridge interpreter (pins.json's own "bridge_versions_unavailable_reason"
    # convention, cases.py's build_pins), and nothing to run the comparison
    # against when this plugin instance has no bridge configured at all
    # (e.g. a schema-only validate_payload call) -- neither case fabricates
    # a pass or a failure it cannot actually support.
    if pinned_versions is not None and bridge is not None:
        actual_versions = bridge.runtime_info()
        for key, pinned_value in pinned_versions.items():
            actual_value = actual_versions.get(key)
            if actual_value != pinned_value:
                mismatches.append(
                    f"{key} mismatch: pinned={pinned_value}, actual={actual_value}"
                )

    if mismatches:
        raise ValueError(
            f"pinned source/dependency verification failed against {_PINS_PATH}: "
            + "; ".join(mismatches)
        )

PLUGIN_ID = "govsim_environment"
SCORER_ID = "govsim_scorer"

HARVEST_PHASE = "harvest"
DISCUSS_PHASE = "discuss"
REFLECT_PHASE = "reflect"

PERSONA_ROLE = "persona"

_PAYLOAD_KEYS = frozenset(
    {
        "upstream_repo",
        "upstream_commit",
        "scenario",
        "env_cfg",
        "personas",
        "policy_assignment",
        "world_seed",
    }
)


def _set_termination(state: dict[str, Any], reason: str) -> None:
    """Record a termination reason, refusing one the case never declared.

    Mirrors ``tau3_retail``'s identical guard: the case manifest publishes
    ``TERMINATION_REASONS`` as this family's termination vocabulary, and
    nothing in the kernel cross-checks a terminal reason against that
    declaration at runtime, so without this the two could silently drift.
    """
    if reason not in TERMINATION_REASONS:
        raise ValueError(
            f"termination reason {reason!r} is not declared by this family; "
            f"declared reasons are {list(TERMINATION_REASONS)}"
        )
    state["termination"] = reason


def _persona_ids(family_case: Mapping[str, Any]) -> tuple[str, ...]:
    num_agents = int(family_case["env_cfg"]["num_agents"])
    return tuple(f"persona_{i}" for i in range(num_agents))


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


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
                "topology": "common_pool_resource_rounds",
                "phase_specs": [HARVEST_PHASE, DISCUSS_PHASE, REFLECT_PHASE],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {
                PERSONA_ROLE: {
                    "testable": True,
                    "scripted_policies": list(policies.SCRIPTED_POLICIES),
                }
            },
            "measurement": {
                # Per docs/problem_bound_case_audit.md row P06: no certified
                # policy upper bound exists for any of this family's
                # comparative leaves (spec section 2/6); this declaration is
                # comparative-only against an AERead-authored baseline
                # policy, never framed as an approach to a bound. The five
                # per-leaf declarations (govsim_no_collapse,
                # govsim_threshold_adherence, govsim_survival_months,
                # govsim_total_harvest, govsim_equality_gini) are
                # measurement.py's job, deferred to a later milestone (see
                # `build_scorer` below).
                "primary_estimand": "govsim_survival_months",
                # "comparative_or_human_judged" is the closest legal value in
                # schemas.py's MeasurementDeclaration enum
                # ({"property_or_answer", "optimizable_outcome",
                # "comparative_or_human_judged"} -- no bare "comparative"
                # bucket exists there); every leaf in measurement.py declares
                # evaluation_class="deterministic" with no rater/judge/rubric
                # field anywhere, so this family is NOT human-judged despite
                # the enum label. A consumer must branch on each leaf's own
                # verifier_family/evaluation_class, never on this
                # family-level field, to decide whether rater-provenance is
                # required (ledger_entries/govsim.md #6: this is a kernel
                # schema imprecision, not something fixable here).
                "measurement_kind": "comparative_or_human_judged",
                "direction": "maximize",
                "comparison_baseline": "govsim_sustainable_v1",
                "bound_status": "baseline_only",
                "outcome_support": "bounded_by_max_num_rounds",
            },
            "scoring": {"scorer_id": SCORER_ID},
        }
    )


def register_plugin(
    registry: PluginRegistry,
    *,
    plugin: "GovsimPlugin | None" = None,
    upstream_root: Path | str | None = None,
    bridge: GovsimBridge | None = None,
) -> "GovsimPlugin":
    """Register one exact family/version binding in the kernel registry."""
    if plugin is None:
        if upstream_root is None:
            raise ValueError("upstream_root is required when plugin is not supplied")
        plugin = GovsimPlugin(upstream_root=upstream_root, bridge=bridge)
    registry.register(family_manifest(), plugin)
    return plugin


class GovsimPlugin:
    """The complete family-owned hook boundary required by ``PluginRegistry``."""

    def __init__(
        self,
        *,
        upstream_root: Path | str,
        bridge: GovsimBridge | None,
    ) -> None:
        self.upstream_root = Path(upstream_root)
        self.bridge = bridge

    # ------------------------------------------------------------------
    # validate_payload
    # ------------------------------------------------------------------

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = _plain(payload)
        if set(data) != set(_PAYLOAD_KEYS):
            raise ValueError(
                f"payload must contain exactly {sorted(_PAYLOAD_KEYS)}, got "
                f"{sorted(data)}"
            )
        if data["upstream_repo"] != UPSTREAM_REPO:
            raise ValueError("payload pins the wrong upstream repository")
        if data["upstream_commit"] != UPSTREAM_COMMIT:
            raise ValueError("payload pins the wrong upstream commit")
        if data["scenario"] not in SCENARIOS:
            raise ValueError(f"unknown scenario: {data['scenario']!r}")

        env_cfg = data["env_cfg"]
        if not isinstance(env_cfg, dict) or set(env_cfg) != set(ENV_CFG_FIELDS):
            raise ValueError(
                f"payload.env_cfg must contain exactly {sorted(ENV_CFG_FIELDS)}"
            )
        num_agents = env_cfg["num_agents"]
        if (
            not isinstance(num_agents, int)
            or isinstance(num_agents, bool)
            or not (1 <= num_agents <= 5)
        ):
            raise ValueError("payload.env_cfg.num_agents must be an integer in [1, 5]")
        if env_cfg["harvesting_order"] != "concurrent":
            raise ValueError(
                "this family only wraps harvesting_order='concurrent' "
                "(spec section 0); 'random-sequential' is out of scope"
            )

        personas = data["personas"]
        if (
            not isinstance(personas, list)
            or len(personas) != num_agents
            or not all(isinstance(name, str) and name for name in personas)
        ):
            raise ValueError(
                "payload.personas must list exactly num_agents non-empty names"
            )

        expected_seats = set(_persona_ids(data))
        policy_assignment = data["policy_assignment"]
        if not isinstance(policy_assignment, dict) or set(policy_assignment) != expected_seats:
            raise ValueError(
                "payload.policy_assignment must cover exactly "
                f"{sorted(expected_seats)}"
            )
        unknown_policies = set(policy_assignment.values()) - set(policies.SCRIPTED_POLICIES)
        if unknown_policies:
            raise ValueError(
                f"payload.policy_assignment references undeclared policies: "
                f"{sorted(unknown_policies)}"
            )

        world_seed = data["world_seed"]
        if not isinstance(world_seed, int) or isinstance(world_seed, bool) or world_seed < 0:
            raise ValueError("payload.world_seed must be a nonnegative integer")

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
        if revision.stdout.strip() != UPSTREAM_COMMIT:
            raise ValueError(
                "upstream checkout revision mismatch: "
                f"expected {UPSTREAM_COMMIT}, got {revision.stdout.strip()}"
            )
        status = subprocess.run(
            ["git", "-C", str(self.upstream_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        if status.returncode != 0 or status.stdout:
            raise ValueError("upstream checkout must be clean at the pinned revision")
        _verify_source_and_dependency_pins(self.upstream_root, self.bridge)
        return data

    # ------------------------------------------------------------------
    # initial_state / phases / eligible_actors
    # ------------------------------------------------------------------

    def initial_state(self, family_case: Mapping[str, Any], cell: Any) -> dict[str, Any]:
        del cell
        bridge = self._require_bridge()
        projection = bridge.run_actions(
            scenario=family_case["scenario"],
            env_cfg=family_case["env_cfg"],
            seed=int(family_case["world_seed"]),
            actions=[],
        )
        projection.pop("ok", None)
        return {
            "action_history": [],
            "projection": projection,
            "termination": None,
            "operational_failure": None,
            # Per-round record consumed only by measurement.py's trajectory-
            # scoped leaves (govsim_no_collapse, govsim_threshold_adherence);
            # see step()'s HARVEST/REFLECT branches for how each entry is
            # assembled.
            "round_trace": [],
        }

    def phases(self, family_case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        num_agents = int(family_case["env_cfg"]["num_agents"])
        max_num_rounds = int(family_case["env_cfg"]["max_num_rounds"])
        # `phase_action_counts` in the scheduler accumulates across every
        # instance of a phase over the whole episode (every round it runs
        # again), never just one instance -- so each PhaseSpec's own
        # `max_logical_actions` must be the phase's total over all
        # `max_num_rounds` rounds, not a per-round or shared episode value.
        harvest_and_reflect_budget = num_agents * max_num_rounds
        discuss_budget = max_num_rounds
        return (
            PhaseSpec(
                phase_id=HARVEST_PHASE,
                actor_selector=PERSONA_ROLE,
                mode="simultaneous",
                observation_schema_by_role={PERSONA_ROLE: "govsim_harvest_observation_v1"},
                action_schema_by_role={PERSONA_ROLE: "govsim_harvest_action_v1"},
                max_logical_actions=harvest_and_reflect_budget,
                invalid_action_policy="reject",
                next_phases=(DISCUSS_PHASE,),
            ),
            PhaseSpec(
                phase_id=DISCUSS_PHASE,
                actor_selector=PERSONA_ROLE,
                mode="single",
                observation_schema_by_role={PERSONA_ROLE: "govsim_discuss_observation_v1"},
                action_schema_by_role={PERSONA_ROLE: "govsim_discuss_action_v1"},
                max_logical_actions=discuss_budget,
                invalid_action_policy="reject",
                next_phases=(REFLECT_PHASE,),
            ),
            PhaseSpec(
                phase_id=REFLECT_PHASE,
                actor_selector=PERSONA_ROLE,
                mode="simultaneous",
                observation_schema_by_role={PERSONA_ROLE: "govsim_reflect_observation_v1"},
                action_schema_by_role={PERSONA_ROLE: "govsim_reflect_action_v1"},
                max_logical_actions=harvest_and_reflect_budget,
                invalid_action_policy="reject",
                next_phases=(HARVEST_PHASE,),
            ),
        )

    def eligible_actors(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
    ) -> tuple[str, ...]:
        del state
        personas = _persona_ids(family_case)
        if phase.phase_id in (HARVEST_PHASE, REFLECT_PHASE):
            return personas
        if phase.phase_id == DISCUSS_PHASE:
            # Fixed spokesperson: matches upstream's own post-harvest cursor
            # (see govsim_bridge_driver.py's module docstring / spec 3.1).
            return (personas[0],)
        raise ValueError(f"unknown phase: {phase.phase_id}")

    # ------------------------------------------------------------------
    # observe / parse_action / legal
    # ------------------------------------------------------------------

    def observe(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
    ) -> dict[str, Any]:
        if seat_id not in self.eligible_actors(family_case, state, phase):
            raise ValueError(f"seat {seat_id!r} is not active in phase {phase.phase_id!r}")
        projection = state["projection"]
        # Deliberately symmetric across seats: scripted v1 policies act on
        # aggregate pool state only, never a peer's individual
        # `wanted_resource` (which upstream itself hides mid-round anyway --
        # spec section 0's noninterference note). A richer, seat-private
        # observation is a follow-up for an LLM-driven persona, not this
        # milestone.
        return {
            "scenario": family_case["scenario"],
            "phase": phase.phase_id,
            "agent_id": seat_id,
            "num_agents": int(family_case["env_cfg"]["num_agents"]),
            "num_round": projection["num_round"],
            "resource_in_pool": projection["resource_in_pool"],
            "sustainability_threshold": projection["sustainability_threshold"],
        }

    def parse_action(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        response: Any,
    ) -> ParseResult:
        del family_case, state, seat_id
        if not isinstance(response, Mapping):
            return ParseResult.failure("response_not_object")
        raw = _plain(response)
        if phase.phase_id == HARVEST_PHASE:
            quantity = raw.get("quantity")
            if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
                return ParseResult.failure("invalid_harvest_quantity")
            return ParseResult.success({"quantity": quantity})
        if phase.phase_id == DISCUSS_PHASE:
            return ParseResult.success({})
        if phase.phase_id == REFLECT_PHASE:
            return ParseResult.success({})
        return ParseResult.failure("unknown_phase")

    def legal(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        action: Mapping[str, Any],
    ) -> LegalityResult:
        del action
        eligible = self.eligible_actors(family_case, state, phase)
        if seat_id not in eligible:
            return LegalityResult.illegal("seat_phase_mismatch")
        return LegalityResult.legal_action()

    # ------------------------------------------------------------------
    # step / terminal / outcome
    # ------------------------------------------------------------------

    def step(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
        actions: Mapping[str, Any],
    ) -> TransitionResult:
        new_state = _plain(state)
        if new_state["termination"] is not None:
            raise ValueError("step called after the episode already terminated")

        personas = _persona_ids(family_case)
        new_actions: list[dict[str, Any]] = []
        if phase.phase_id == HARVEST_PHASE:
            for persona_id in personas:
                quantity = actions[persona_id].action["quantity"]
                new_actions.append(
                    {"kind": "harvesting", "agent_id": persona_id, "quantity": int(quantity)}
                )
            for persona_id in personas:
                # "pool_after_harvesting": a dummy re-observe step upstream
                # requires from every agent before phase advances; carries
                # no quantity of its own (spec section 3.1).
                new_actions.append(
                    {"kind": "harvesting", "agent_id": persona_id, "quantity": 0}
                )
            next_phase = DISCUSS_PHASE
        elif phase.phase_id == DISCUSS_PHASE:
            (spokesperson,) = self.eligible_actors(family_case, state, phase)
            new_actions.append({"kind": "chat", "agent_id": spokesperson})
            next_phase = REFLECT_PHASE
        elif phase.phase_id == REFLECT_PHASE:
            for persona_id in personas:
                new_actions.append({"kind": "home", "agent_id": persona_id})
            next_phase = HARVEST_PHASE
        else:
            raise ValueError(f"unknown phase: {phase.phase_id}")

        bridge = self._require_bridge()
        history = list(new_state["action_history"]) + new_actions
        try:
            projection = bridge.run_actions(
                scenario=family_case["scenario"],
                env_cfg=family_case["env_cfg"],
                seed=int(family_case["world_seed"]),
                actions=history,
            )
        except GovsimActionError as error:
            # A caught upstream assertion on a malformed action (QC Gate 2's
            # "malformed-operational" golden): a typed, never-silent
            # operational failure, never promoted to a scored zero and
            # never left to crash the harness (shared_runner_portability_
            # contract.md section 4).
            _set_termination(new_state, "operational_failure")
            new_state["operational_failure"] = {
                "error_type": error.error_type,
                "message": str(error),
                "failed_action_index": error.failed_action_index,
            }
            return TransitionResult(
                state=new_state,
                next_phase_id=None,
                consequences={"upstream_calls": len(new_actions), "failed": True},
            )

        projection.pop("ok", None)
        new_state["action_history"] = history
        new_state["projection"] = projection
        if phase.phase_id == HARVEST_PHASE:
            # Stash this round's harvest-phase snapshot (wanted_resource --
            # upstream's own `_assign_resource()` output, already finalized
            # by the time the 2N-action batch above returns -- and the
            # sustainability_threshold that was in effect for it, i.e. the
            # value regeneration computed at the END of the PREVIOUS round,
            # or upstream's own reset() default for round 0) so it can be
            # merged into one round_trace entry once REFLECT closes this
            # round out. Read straight off upstream's own recorded state,
            # never re-derived (spec section 2's "never re-derived
            # independently of upstream's own state").
            new_state["_pending_round_snapshot"] = {
                "wanted_resource": dict(projection["wanted_resource"]),
                "sustainability_threshold": int(projection["sustainability_threshold"]),
            }
        elif phase.phase_id == REFLECT_PHASE:
            # Merge the pending harvest-phase snapshot with this round's
            # close-out (upstream's own post-regeneration resource_in_pool
            # and its own `terminations` flag, computed by upstream BEFORE
            # regeneration -- see concurrent_env.py's step()) into exactly
            # one round_trace entry. `collapsed_or_horizon` is upstream's own
            # flag, not re-derived: this environment already halts the
            # episode the first round it is True (see below), so it can
            # only ever be True on the LAST entry appended.
            pending = new_state.pop("_pending_round_snapshot", {}) or {}
            round_trace = list(new_state.get("round_trace", []))
            round_trace.append(
                {
                    "round_index": len(round_trace),
                    "wanted_resource": dict(pending.get("wanted_resource", {})),
                    "sustainability_threshold": pending.get("sustainability_threshold"),
                    "resource_in_pool_after_regen": projection["resource_in_pool"],
                    "collapsed_or_horizon": bool(all(projection["terminations"].values())),
                }
            )
            new_state["round_trace"] = round_trace
        if all(projection["terminations"].values()):
            _set_termination(new_state, "collapse_or_horizon")
            next_phase = None
        return TransitionResult(
            state=new_state,
            next_phase_id=next_phase,
            consequences={"upstream_calls": len(new_actions), "failed": False},
        )

    def terminal(
        self, family_case: Mapping[str, Any], state: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        del family_case
        reason = state["termination"]
        if reason is None:
            return None
        projection = state["projection"]
        result: dict[str, Any] = {
            "reason": reason,
            "num_round": projection["num_round"],
            "resource_in_pool": projection["resource_in_pool"],
            "collected_resource": dict(projection["collected_resource"]),
            # measurement.py's trajectory-scoped leaves (govsim_no_collapse,
            # govsim_threshold_adherence) read this; see step()'s HARVEST/
            # REFLECT branches for how each entry is assembled. Possibly
            # short one entry for the in-progress round on an
            # "operational_failure" termination (the round never reached
            # REFLECT) -- measurement.py never scores that termination
            # reason regardless (see its module docstring).
            "round_trace": [dict(entry) for entry in state.get("round_trace", [])],
        }
        if reason == "operational_failure":
            result["operational_failure"] = dict(state["operational_failure"])
        return result

    def outcome(
        self, family_case: Mapping[str, Any], terminal: Mapping[str, Any]
    ) -> dict[str, Any]:
        del family_case
        reason = terminal["reason"]
        # Mirrors shared_runner_portability_contract.md section 4: an
        # interruption with uncertain external outcome remains
        # "outcome_unknown", never silently promoted to a known result.
        outcome_status = "outcome_unknown" if reason == "operational_failure" else "known"
        result: dict[str, Any] = {
            "termination_reason": reason,
            "outcome_status": outcome_status,
            "num_round": terminal["num_round"],
            "resource_in_pool": terminal["resource_in_pool"],
            "collected_resource": dict(terminal["collected_resource"]),
        }
        if reason == "operational_failure":
            result["operational_failure"] = dict(terminal["operational_failure"])
        return result

    def build_scorer(self, family_case: Mapping[str, Any]) -> measurement.GovsimScorer:
        """Return the five declared measurement leaves for this case.

        Delegates entirely to ``measurement.py`` (spec section 2), mirroring
        ``tau3_retail``'s identical convention of keeping every estimand/
        reference/scorer declaration in that one module and having this hook
        just wire it in. ``family_evaluation.py``'s ``finalize_family_execution``
        calls the returned ``GovsimScorer`` directly
        (``plugin.build_scorer(family_case)(recorded_outcome,
        evidence_refs=(...))``); ``measurement.py``'s ``GovsimScorer.__call__``
        is the seam that satisfies that call. The other four (non-primary)
        leaves' named methods are still exercised directly by
        ``tests/test_govsim_measurement.py`` today.
        """
        return measurement.build_scorer(family_case)

    def build_reference_providers(self, family_case: Mapping[str, Any]) -> tuple[Any, ...]:
        del family_case
        # No certified policy upper bound exists for any comparative leaf
        # (docs/problem_bound_case_audit.md row P06); nothing to provide.
        return ()

    def generator(self, family_case: Mapping[str, Any]) -> None:
        del family_case
        # Corpus generation is an offline script (cases.py's CLI), not a
        # runtime hook -- mirrors tau3_retail's identical convention.
        return None

    def _require_bridge(self) -> GovsimBridge:
        if self.bridge is None:
            raise RuntimeError("govsim execution requires a provisioned GovsimBridge")
        return self.bridge


__all__ = [
    "DISCUSS_PHASE",
    "GovsimPlugin",
    "HARVEST_PHASE",
    "PERSONA_ROLE",
    "PLUGIN_ID",
    "REFLECT_PHASE",
    "SCORER_ID",
    "family_manifest",
    "register_plugin",
]
