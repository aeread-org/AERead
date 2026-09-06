"""Tests for the econevals offline replayer (replay.py, milestone 3).

Follows the same ``_bridge()``/skip convention as
``tests/test_econevals_environment.py``: pure structural tests run
everywhere; tests that actually replay tool calls run for real when a
pinned upstream bridge interpreter is provisioned, and are skipped (never
faked) otherwise.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import pytest

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import (
    ImplementationPin,
    PlanCell,
    RunPlan,
    case_content_sha256,
    canonical_json_bytes,
    resolve_run_plan,
)
from aeread.shared_runner.schemas import (
    AgentProfile,
    AnalysisPlan,
    CaseManifest,
    EvaluationBlock,
    RunSpec,
    SamplingPlan,
    SuiteManifest,
)
from aeread.shared_runner.task.execution import CanonicalResponse, CellExecution, EvidenceStore
from aeread.shared_runner.task.evaluation import finalize_family_execution
from aeread.shared_runner.task.scheduler import EpisodeResult, run_episode
from aeread_families.econevals import cases as econevals_cases
from aeread_families.econevals import environment as econevals_environment
from aeread_families.econevals.econevals_bridge import (
    EconevalsBridge,
    EconevalsBridgeUnavailableError,
    discover_bridge_python,
)
from aeread_families.econevals.environment import (
    ROLE_ID,
    SEAT_ID,
    TRACK_TOOLS,
    EconevalsPlugin,
    family_manifest,
    register_plugin,
)
from aeread_families.econevals.harness import ScriptedEconevalsHarness
from aeread_families.econevals.measurement import GATE_LEAF_ID, OBJECTIVE_LEAF_ID
from aeread_families.econevals.replay import (
    RecordedDecision,
    RecordedEpisode,
    RecordedResponseSource,
    ReplayError,
    assert_replay_matches,
    compare_episode_results,
    record_episode,
    replay_and_verify,
    replay_episode,
    score_replayed_episode,
)
from aeread_families.econevals.tools import EconevalsToolSession

CASES_DIR = Path("cases/econevals")

try:
    BRIDGE_PYTHON = discover_bridge_python()
except EconevalsBridgeUnavailableError as error:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = str(error)
else:
    _BRIDGE_SKIP_REASON = ""


def _bridge() -> EconevalsBridge:
    if BRIDGE_PYTHON is None:
        pytest.skip(_BRIDGE_SKIP_REASON or "bridge python unavailable")
    return EconevalsBridge(python_executable=BRIDGE_PYTHON)


def _shrunk_case(split: str, case_id: str, *, max_steps: int) -> CaseManifest:
    """See ``tests/test_econevals_environment.py``'s identical helper: a
    test-scoped copy of a real pilot case with a much smaller
    ``pins.max_steps``/``episode.max_logical_actions`` so a replay test can
    reach a genuine termination in a handful of periods."""
    path = CASES_DIR / split / f"{case_id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["payload"] = dict(raw["payload"])
    raw["payload"]["pins"] = dict(raw["payload"]["pins"])
    raw["payload"]["pins"]["max_steps"] = max_steps
    raw["episode"] = dict(raw["episode"])
    raw["episode"]["max_logical_actions"] = max_steps
    raw["content_sha256"] = case_content_sha256(raw)
    return CaseManifest.from_dict(raw)


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_econevals_replay_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_econevals_replay",
        suite_version="0.1.0",
        block_id="block_econevals_replay",
        sampling_plan_id="sampling_econevals_replay",
        analysis_plan_id="analysis_econevals_replay",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_econevals_replay_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType({SEAT_ID: "scripted_agent"}),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _pricing_script(product_ids: list[str], *, periods: int) -> list[list[dict]]:
    prices = {product_id: 1.0 for product_id in product_ids}
    return [
        [
            {"id": "1", "name": "get_product_ids", "arguments": {}},
            {"id": "2", "name": "set_prices", "arguments": {"prices_dict_str": prices}},
        ]
        for _ in range(periods)
    ]


def _run_live(bridge: EconevalsBridge, tmp_path: Path, *, suffix: str):
    case = _shrunk_case("pricing_basic", "econevals.pricing.basic.0", max_steps=3)
    cell = _cell(case, suffix=suffix)
    plugin = EconevalsPlugin(bridge=bridge)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())
    family_case = plugin.validate_payload(case.payload)
    product_ids = family_case["generated_instance"]["product_ids"]

    evidence = EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_econevals_replay_{suffix}",
        cell_id=cell.cell_id,
        episode_id=f"episode_econevals_replay_{suffix}",
        episode_attempt_id="attempt_1",
    )
    harness = ScriptedEconevalsHarness(
        plugin=resolved_plugin,
        family_case=family_case,
        evidence=evidence,
        script=_pricing_script(product_ids, periods=3),
    )
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=harness)
    )
    evidence.seal()
    return case, cell, resolved_plugin, family_case, result


# ---------------------------------------------------------------------------
# Evidence-complete episode driving (kernel_scoring_contract_spec.md
# milestone 3): a response source that ALSO writes the full generic evidence
# trail ``task.evaluation.replay_family_scoring_input`` needs to replay, plus
# a real, ``resolve_run_plan``-resolved ``RunPlan`` -- both required to drive
# ``task.evaluation.finalize_family_execution`` for this family for the
# first time, and reused by ``tests/test_shared_runner_scoring_contract.py``
# for its own paired-history fixtures.
# ---------------------------------------------------------------------------


class EvidenceRecordingEconevalsHarness:
    """A ``run_episode`` response source that writes the full generic
    replay-required evidence trail (``logical_action_started``,
    ``action_attempt_succeeded``, ``action_parsed``,
    ``action_legality_checked``, ``logical_action_succeeded``,
    ``phase_instance_started``, ``transition_applied``,
    ``phase_instance_succeeded``, ``episode_terminated``,
    ``family_outcome_recorded``) -- exactly the event vocabulary
    ``aeread.shared_runner.task.execution.MinimalChatExecutor``/
    ``AttemptExecutor`` write for every LLM-harness-backed family's own
    evidence, reproduced here without any of that class's provider/retry/
    cost machinery (mirroring govsim's own identically-purposed
    ``EvidenceRecordingGovsimHarness``, ``tests/test_govsim_replay.py``).

    ``ScriptedEconevalsHarness`` (this family's existing scripted response
    source, ``harness.py``) drives every tool call through the kernel
    ``ToolRuntime``, which writes only ``tool_invocation_started``/
    ``tool_invocation_succeeded`` pairs -- a THIRD evidence layer, never the
    generic one ``replay_family_scoring_input`` reads -- so it has never
    produced evidence ``finalize_family_execution`` can replay. This class
    calls ``EconevalsPlugin.dispatch_submit`` directly (the SAME tool-body
    implementation ``step``'s own cross-check independently re-derives, per
    ``environment.py``'s module docstring), against a private
    ``EconevalsToolSession`` mirror, skipping ``ToolRuntime`` entirely --
    that third layer is not required for replay and this family's own
    ``audit_reconciliation`` call tolerates its absence (every one of its
    four tracked entity types is keyed by an id field this harness simply
    never sets).

    ``script`` is one ``{"name", "arguments"}`` submit-tool call per period
    -- always exactly one call, always the track's own declared submit tool
    (spec's "the terminating submit call always ends the period"), so no
    read-only tool burst is scripted here; nothing this family's leaves read
    depends on one.
    """

    def __init__(
        self,
        *,
        plugin: EconevalsPlugin,
        family_case: Mapping[str, Any],
        evidence: EvidenceStore,
        script: Sequence[Mapping[str, Any]],
    ) -> None:
        self._plugin = plugin
        self._family_case = family_case
        self._evidence = evidence
        self._script = tuple(dict(call) for call in script)
        self._cursor = 0
        self._session = EconevalsToolSession(plugin.initial_state(family_case, None))

    async def __call__(self, request: Any) -> dict[str, Any]:
        if self._cursor >= len(self._script):
            raise RuntimeError("script exhausted before episode termination")
        call = self._script[self._cursor]
        self._cursor += 1
        track = self._family_case["track"]
        submit_tool = TRACK_TOOLS[track]["submit_tool"]
        name = call["name"]
        arguments = dict(call["arguments"])
        if name != submit_tool:
            raise RuntimeError(
                f"EvidenceRecordingEconevalsHarness only scripts the track's "
                f"own submit tool ({submit_tool!r}), got {name!r}"
            )
        result = self._plugin.dispatch_submit(
            track, self._family_case, self._session.get_state(), name, arguments
        )
        tool_call = {"id": "1", "name": name, "arguments": arguments}
        tool_execution = {
            "tool_call_id": "1",
            "name": name,
            "arguments": arguments,
            "result": result,
        }
        response = {"tool_calls": [tool_call], "tool_executions": [tool_execution]}

        self._evidence.append_event(
            "logical_action_started",
            {"request": request},
            phase_instance_id=request.phase_instance_id,
            logical_action_id=request.logical_action_id,
            visibility=f"seat:{request.seat_id}",
        )
        # A CanonicalResponse-shaped placeholder purely for replay provenance
        # (``LogicalActionRecord.response``): econevals's own ``parse_action``
        # never reads it (the scheduler hands it the raw ``response`` dict
        # returned below, unchanged), and replay itself reconstructs
        # ``parse``/``legality`` directly from the "action_parsed"/
        # "action_legality_checked" events below, never from this response.
        canonical = CanonicalResponse(
            text=json.dumps(response, sort_keys=True),
            finish_reason="stop",
            empty=False,
            truncated=False,
            provider_call_ids=(),
            tool_invocation_ids=(),
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            action=response,
        )
        self._evidence.append_event(
            "action_attempt_succeeded",
            {"canonical_response": canonical},
            phase_instance_id=request.phase_instance_id,
            logical_action_id=request.logical_action_id,
            visibility=f"seat:{request.seat_id}",
        )
        self._session.advance_period(self._family_case)
        return response

    def finalize_action(self, record: Any) -> None:
        envelope = record.envelope
        failure_code = None
        if not envelope.valid:
            failure_code = (
                envelope.parse.error_code
                if not envelope.parse.ok
                else envelope.legality.reason
            )
        self._evidence.append_event(
            "action_parsed",
            {"parse_result": envelope.parse},
            phase_instance_id=record.request.phase_instance_id,
            logical_action_id=record.logical_action_id,
            visibility=f"seat:{record.seat_id}",
        )
        if envelope.legality is not None:
            self._evidence.append_event(
                "action_legality_checked",
                {"legality_result": envelope.legality},
                phase_instance_id=record.request.phase_instance_id,
                logical_action_id=record.logical_action_id,
            )
        event_type = (
            "logical_action_succeeded"
            if envelope.valid
            else "logical_action_agent_action_failure"
        )
        self._evidence.append_event(
            event_type,
            {"valid": envelope.valid, "failure_code": failure_code},
            logical_action_id=record.logical_action_id,
        )

    def fail_logical_action(self, logical_action_id: str, *, failure_code: str) -> None:
        self._evidence.append_event(
            "logical_action_failed",
            {"failure_condition": failure_code},
            logical_action_id=logical_action_id,
        )

    def phase_started(
        self,
        *,
        phase_instance_id: str,
        phase: Any,
        eligible_actors: tuple[str, ...],
        pre_state_sha256: str,
    ) -> None:
        self._evidence.append_event(
            "phase_instance_started",
            {
                "phase": phase,
                "eligible_actors": eligible_actors,
                "pre_state_sha256": pre_state_sha256,
            },
            phase_instance_id=phase_instance_id,
        )

    def transition_applied(
        self,
        *,
        phase_instance_id: str,
        phase: Any,
        transition: Any,
        post_state_sha256: str,
    ) -> None:
        self._evidence.append_event(
            "transition_applied",
            {
                "phase_id": phase.phase_id,
                "transition": transition,
                "post_state_sha256": post_state_sha256,
            },
            phase_instance_id=phase_instance_id,
        )

    def phase_completed(self, *, phase_instance: Any) -> None:
        self._evidence.append_event(
            "phase_instance_succeeded",
            {
                "phase_id": phase_instance.phase_id,
                "post_state_sha256": phase_instance.post_state_sha256,
                "logical_action_ids": tuple(
                    action.logical_action_id for action in phase_instance.actions
                ),
            },
            phase_instance_id=phase_instance.phase_instance_id,
        )

    def episode_completed(self, *, episode_result: EpisodeResult) -> None:
        self._evidence.append_event(
            "episode_terminated",
            {
                "terminal": episode_result.terminal,
                "logical_action_count": episode_result.logical_action_count,
            },
        )
        self._evidence.append_event(
            "family_outcome_recorded",
            {"outcome": episode_result.outcome},
        )


def econevals_illegal_procurement_script(offer_id: str) -> dict[str, Any]:
    """One period's worth of a deliberately illegal procurement submission:
    an offer id ``environment._submit_procurement`` pre-validates against
    ``instance["menu"]`` and rejects before ever calling the bridge (see
    ``EconevalsPlugin._submit_procurement``'s own ``unknown_ids`` check) --
    this is why this family's fixtures below need no bridge interpreter at
    all, unlike a legal submission for any of the three tracks."""
    return {
        "name": TRACK_TOOLS["procurement"]["submit_tool"],
        "arguments": {
            TRACK_TOOLS["procurement"]["submit_arg"]: {offer_id: 1},
        },
    }


def _econevals_fixture_case(*, world_seed: int, max_steps: int, case_id: str) -> CaseManifest:
    """A small, hand-authored, fully-controlled procurement case.

    Unlike the checked-in pilot corpus (a real, bridge-generated
    ``generated_instance``/``gold_optimum`` per ``cases.py``), this fixture's
    instance is a bare-minimum stand-in: every case below only ever drives
    ``econevals_illegal_procurement_script``'s pre-bridge illegal-offer-id
    path (``EconevalsPlugin._submit_procurement``'s own ``unknown_ids``
    check, which returns before ever calling ``self._require_bridge()``), so
    neither ``gold_optimum`` (never read on that path) nor a real menu
    (only ``instance["menu"]``'s own KEY SET is read, to decide what counts
    as an "unknown" offer id) needs to be bridge-produced. Exists only for
    this module's own finalizer test and
    ``tests/test_shared_runner_scoring_contract.py``'s paired-history
    fixtures; never written to the checked-in pilot corpus.
    """
    raw: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": case_id,
        "family_id": econevals_cases.FAMILY_ID,
        "family_version": econevals_cases.FAMILY_VERSION,
        "split": "dev",
        "world_seed": world_seed,
        "seats": [{"id": SEAT_ID, "role": ROLE_ID}],
        "episode": {
            "max_logical_actions": max_steps,
            "termination": list(econevals_cases.TERMINATION_REASONS),
        },
        "visibility_policy": econevals_cases.VISIBILITY_POLICY,
        "payload": {
            "track": "procurement",
            "difficulty": "Basic",
            "seed": world_seed,
            "generated_instance": {"menu": {"known_item": {"price": 10}}},
            "gold_optimum": {},
            "pins": {"max_steps": max_steps},
        },
        "provenance": {
            "generator_id": "econevals_kernel_contract_fixture_generator_v1",
            "generator_version": "1.0.0",
            "review_status": "curated",
        },
        "upstream_task_id": None,
        "content_sha256": "0" * 64,
    }
    raw["content_sha256"] = case_content_sha256(raw)
    return CaseManifest.from_dict(raw)


@dataclass(frozen=True, slots=True)
class EconevalsSetup:
    """A resolved, provider-free ``RunPlan`` for one econevals case.

    This family's real runtime never goes through ``execute_plan_cell``'s
    harness/provider stack -- every period is answered directly through
    ``run_episode``'s ``response_source``
    (``ScriptedEconevalsHarness``/``EvidenceRecordingEconevalsHarness``
    above). The declared ``minimal_chat`` harness and fixture provider below
    exist purely to satisfy ``resolve_run_plan``'s structural pin/capability
    checks and are never actually invoked (mirrors govsim's identically-
    purposed ``GovsimSetup``).
    """

    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, Any]


_ECONEVALS_FIXTURE_PROFILE_ID = "econevals_unused_fixture_profile_v1"
_ECONEVALS_FIXTURE_PROVIDER_ID = "econevals_unused_fixture_provider"
_ECONEVALS_FIXTURE_RUNTIME_ID = "aeread.shared_runner.task.execution"


def build_econevals_setup(
    plugin: EconevalsPlugin, case: CaseManifest, *, suffix: str
) -> EconevalsSetup:
    """Resolve a real, one-cell ``RunPlan`` for ``case`` (spec section 5.3).

    Every seat shares one placeholder agent profile: this family's real
    runtime never invokes it (see ``EconevalsSetup``'s own docstring), so
    the harness/provider it names exist only to satisfy
    ``resolve_run_plan``'s structural checks.
    """
    family = family_manifest()
    seat_ids = [seat.id for seat in case.seats]
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": f"econevals_{suffix}_sample_v1",
            "estimand": "fixed_econevals_case",
            "target": case.case_id,
            "selection": "fixed_curated",
            "seeds": [case.world_seed],
            "replicates": 1,
            "cluster_level": "world_seed",
            "cluster_id_fields": ["generator_version", "world_seed"],
            "paired_fields": [],
            "replicate_level": "episode_attempt",
            "panel_mode": "fixed_panel",
        }
    )
    block = EvaluationBlock.from_dict(
        {
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": f"econevals_{suffix}_block",
            "kind": "self_play",
            "subject_seats": list(seat_ids),
            "controlled_profiles": {},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": AnalysisPlan.SPEC_VERSION,
            "analysis_plan_id": f"econevals_{suffix}_analysis_v1",
            "estimands": [family.measurement.primary_estimand],
            "group_by": ["family_id"],
            "missingness": "report_separately",
            "resampling_unit": "world_seed",
            "uncertainty": "none",
            "multiplicity": "none",
            "sensitivity": [],
            "cross_family_scalar": "disabled",
        }
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": SuiteManifest.SPEC_VERSION,
            "suite_id": f"econevals_{suffix}_suite_v1",
            "version": "1.0.0",
            "family_ids": [family.family.id],
            "case_ids": [case.case_id],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    profile = AgentProfile.from_dict(
        {
            "spec_version": AgentProfile.SPEC_VERSION,
            "profile_id": _ECONEVALS_FIXTURE_PROFILE_ID,
            "model": {
                "provider": _ECONEVALS_FIXTURE_PROVIDER_ID,
                "model": "econevals_unused_fixture_model_v1",
                "revision": "1.0.0",
                "base_url": None,
            },
            "harness": {
                "id": "minimal_chat",
                "version": "1.0",
                "config": {},
            },
            "prompt": {
                "prompt_id": f"econevals_{suffix}_prompt_v1",
                "sha256": hashlib.sha256(
                    b"econevals scripted agent: no prompt is ever sent"
                ).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": _ECONEVALS_FIXTURE_RUNTIME_ID,
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "econevals_scripted_no_reasoning_v1",
                "effort": None,
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": 64,
                "seed": None,
                "top_p": None,
            },
            "budgets": {
                "max_logical_actions": case.episode.max_logical_actions,
                "timeout_seconds": 30.0,
                "max_cost_usd": 0.0,
            },
            "retry_policy": {
                "max_action_attempts": 1,
                "retryable_conditions": [],
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )
    run_spec = RunSpec.from_dict(
        {
            "spec_version": RunSpec.SPEC_VERSION,
            "run_spec_id": f"econevals_{suffix}_run_spec_v1",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id],
            "seat_assignments": {seat_id: profile.profile_id for seat_id in seat_ids},
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )

    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    harness_registry = HarnessRegistry()
    for harness in default_harnesses().values():
        harness_registry.register(harness)

    environment_path = Path(econevals_environment.__file__)
    execution_path = Path(execution_module.__file__)
    pins = (
        ImplementationPin.from_dict(
            {
                "component_id": econevals_environment.PLUGIN_ID,
                "kind": "family_plugin",
                "version": "0.1.0",
                "sha256": hashlib.sha256(environment_path.read_bytes()).hexdigest(),
            }
        ),
        ImplementationPin.from_dict(
            {
                "component_id": econevals_environment.SCORER_ID,
                "kind": "scorer",
                "version": "0.1.0",
                "sha256": hashlib.sha256(environment_path.read_bytes()).hexdigest(),
            }
        ),
        ImplementationPin.from_dict(
            {
                "component_id": "minimal_chat",
                "kind": "harness",
                "version": "1.0",
                "sha256": hashlib.sha256(execution_path.read_bytes()).hexdigest(),
            }
        ),
        ImplementationPin.from_dict(
            {
                "component_id": _ECONEVALS_FIXTURE_RUNTIME_ID,
                "kind": "runtime",
                "version": "0.1.0",
                "sha256": hashlib.sha256(execution_path.read_bytes()).hexdigest(),
            }
        ),
    ) + tuple(_reference_pin(ref) for ref in _reference_implementations())
    plan = resolve_run_plan(
        families=(family,),
        cases=(case,),
        suite=suite,
        sampling=sampling,
        evaluation_blocks=(block,),
        analysis=analysis,
        agent_profiles=(profile,),
        run_spec=run_spec,
        registry=registry,
        implementation_pins=pins,
        harness_registry=harness_registry,
        provider_capabilities={
            _ECONEVALS_FIXTURE_PROVIDER_ID: ProviderCapabilities(
                native_tools=False,
                structured_output=False,
                seed=False,
                system_prompt=True,
                reasoning_budget=False,
                reasoning_token_report=False,
                max_context_tokens=None,
            )
        },
    )
    return EconevalsSetup(plan=plan, registry=registry, prompt_sources={}, pricing={})


def _reference_implementations() -> tuple[Any, ...]:
    """Every ``ImplementationRef`` any of this family's leaves declare, for
    any track -- the exact content ``family_manifest()``'s own
    ``scoring.reference_provider_ids`` (``measurement.reference_provider_ids``)
    names, pinned here from the SAME builders rather than re-hashed by hand,
    so a pin can never silently drift from what a leaf actually declares."""
    from aeread_families.econevals import measurement as m

    domain_predicate = m.build_gate_leaf("procurement").estimand.validity_domain.predicate
    refs = {domain_predicate}
    for track in econevals_cases.TRACKS:
        refs.add(m.build_gate_leaf(track).scorer)
        refs.add(m.build_objective_leaf(track, {}).scorer)
    return tuple(refs)


def _reference_pin(ref: Any) -> ImplementationPin:
    return ImplementationPin.from_dict(
        {
            "component_id": ref.implementation_id,
            "kind": "reference",
            "version": ref.version,
            "sha256": ref.content_sha256,
        }
    )


def test_finalize_wires_econevals_to_the_shared_family_finalizer(tmp_path: Path) -> None:
    """This family has never produced an ``EvaluationReceipt``.

    Drives one small, real, bridge-free episode (this module's own
    ``_econevals_fixture_case``, deliberately illegal -- see
    ``econevals_illegal_procurement_script``'s own docstring for why this
    needs no bridge at all) end to end through the real
    ``task.evaluation.finalize_family_execution`` and asserts a receipt
    comes back carrying EXACTLY this family's two declared finalize-time
    leaves and its declared primary leaf id.

    Because the gate never passes (spec's hybrid-gate composition: the
    objective is never computed when the gate does not pass, for ANY
    reason -- ``measurement._objective_not_computed``'s own docstring), the
    sole admission leaf (``econevals_objective_leaf``) is
    ``invalid_measurement``, so the receipt is genuinely
    ``inclusion_status == "excluded"`` -- asserted here as the actual,
    observed result, not "included": this family's admission leaf is
    invalid whenever the final submission is not a legal one, which this
    fixture deliberately is not.
    """
    plugin = EconevalsPlugin(bridge=None)
    case = _econevals_fixture_case(
        world_seed=0,
        max_steps=1,
        case_id="econevals.kernel_contract_fixture.finalize_receipt.0",
    )
    setup = build_econevals_setup(plugin, case, suffix="finalize_receipt")
    cell = setup.plan.cells[0]
    family = setup.plan.families[0]
    resolved_plugin = setup.registry.resolve_manifest(family)
    family_case = resolved_plugin.validate_payload(case.payload)

    evidence = EvidenceStore(
        tmp_path / "evidence_finalize_receipt",
        run_plan_id=setup.plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_id=f"episode_{cell.cell_id}",
        episode_attempt_id="attempt_1",
    )
    harness = EvidenceRecordingEconevalsHarness(
        plugin=resolved_plugin,
        family_case=family_case,
        evidence=evidence,
        script=[econevals_illegal_procurement_script("unknown_offer")],
    )
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=harness)
    )
    execution = CellExecution(
        run_plan_id=setup.plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_attempt_id="attempt_1",
        episode_result=result,
        evidence=evidence,
        action_executions=(),
        total_cost_usd=0.0,
    )

    receipt = finalize_family_execution(setup=setup, execution=execution)

    assert {score.leaf.leaf_id for score in receipt.scores} == {GATE_LEAF_ID, OBJECTIVE_LEAF_ID}
    assert receipt.primary_leaf_id == OBJECTIVE_LEAF_ID
    assert receipt.status == "invalid_measurement"
    assert receipt.inclusion_status == "excluded"
    objective_score = next(
        score for score in receipt.scores if score.leaf.leaf_id == OBJECTIVE_LEAF_ID
    )
    assert objective_score.status == "invalid_measurement"
    assert any(
        "unknown_offer" in reason or "gate_failed" in reason
        for reason in objective_score.validity.reasons
    )
    gate_score = next(score for score in receipt.scores if score.leaf.leaf_id == GATE_LEAF_ID)
    assert gate_score.status == "ok"
    assert gate_score.primary.value == 0.0


# ---------------------------------------------------------------------------
# Pure, no bridge: RecordedDecision/RecordedEpisode structural round-tripping.
# ---------------------------------------------------------------------------


def test_recorded_episode_round_trips_through_plain_json() -> None:
    decision = RecordedDecision(
        phase_id="period",
        seat_id="agent",
        response={"tool_calls": [{"id": "1"}], "n": (1, 2)},
    )
    episode = RecordedEpisode(case_id="econevals.pricing.basic.0", decisions=(decision,))

    text = episode.to_json()
    restored = RecordedEpisode.from_json(text)

    assert restored.case_id == episode.case_id
    assert len(restored.decisions) == 1
    assert restored.decisions[0].phase_id == "period"
    assert restored.decisions[0].seat_id == "agent"
    # Tuple/list distinctions collapse to JSON arrays through the round trip.
    assert restored.decisions[0].response == {
        "tool_calls": [{"id": "1"}],
        "n": [1, 2],
    }


def test_recorded_response_source_enforces_ordering_and_reports_exhaustion() -> None:
    decisions = (
        RecordedDecision(phase_id="period", seat_id="agent", response={"tool_calls": []}),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "period"
        seat_id = "agent"

    response = asyncio.run(source(_Request()))
    assert response == {"tool_calls": []}
    assert source.exhausted is True

    with pytest.raises(ReplayError, match="exhausted"):
        asyncio.run(source(_Request()))


def test_recorded_response_source_rejects_phase_seat_mismatch() -> None:
    decisions = (
        RecordedDecision(phase_id="period", seat_id="agent", response={"tool_calls": []}),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "period"
        seat_id = "someone_else"

    with pytest.raises(ReplayError, match="does not match"):
        asyncio.run(source(_Request()))


def test_compare_episode_results_reports_specific_mismatches_not_one_boolean() -> None:
    """A synthetic mismatch (mutated terminal) must be visible per-component."""

    class _Fake:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    original = _Fake(
        phase_instances=(),
        terminal={"reason": "max_periods"},
        outcome={"period_count": 3},
        final_state={"period": 3, "attempts": []},
    )
    replayed = _Fake(
        phase_instances=(),
        terminal={"reason": "error"},
        outcome={"period_count": 3},
        final_state={"period": 3, "attempts": []},
    )

    comparison = compare_episode_results(original, replayed)

    assert comparison.terminal_matches is False
    assert comparison.outcome_matches is True
    assert comparison.matches is False
    with pytest.raises(ReplayError, match="terminal record differs"):
        assert_replay_matches(comparison)


# ---------------------------------------------------------------------------
# Bridge-gated: genuine offline replay of a live, tool-executing episode.
# ---------------------------------------------------------------------------


def test_replay_from_a_json_round_tripped_record_reproduces_the_live_run_byte_identically(
    tmp_path: Path,
) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, family_case, original = _run_live(
        bridge, tmp_path, suffix="live"
    )

    recorded = record_episode(original)
    # Force a genuine round trip through plain JSON text -- proves replay
    # never depends on reusing the original run's in-memory Python objects.
    recorded = RecordedEpisode.from_json(recorded.to_json())
    assert recorded.case_id == case.case_id

    # A second, independent EconevalsBridge/plugin -- not the one that
    # produced the original run -- drives the replay, through the SAME
    # PlanCell (so phase_instance_id/episode_id agree; see replay.py's own
    # docstring on why this family's raw state is expected to byte-match,
    # unlike tau3.retail's timestamped messages).
    replay_bridge = EconevalsBridge(python_executable=BRIDGE_PYTHON)
    replay_plugin = EconevalsPlugin(bridge=replay_bridge)
    registry = PluginRegistry()
    register_plugin(registry, plugin=replay_plugin)
    resolved_replay_plugin = registry.resolve_manifest(family_manifest())

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=resolved_replay_plugin, recorded=recorded)
    )

    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is True
    assert comparison.state_hashes_match is True
    assert comparison.final_state_matches is True
    assert comparison.original_final_state_sha256 == comparison.replayed_final_state_sha256
    assert replayed.terminal["reason"] == "max_periods"

    # Genuinely byte-identical, not merely content-equivalent (see
    # replay.py's module docstring for why econevals's state affords this
    # where tau3.retail's cannot).
    assert canonical_json_bytes(replayed.final_state) == canonical_json_bytes(
        original.final_state
    )


def test_replayed_episode_recomputes_both_leaves_from_the_final_attempts_list(
    tmp_path: Path,
) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, family_case, original = _run_live(
        bridge, tmp_path, suffix="score"
    )
    recorded = record_episode(original)

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=resolved_plugin, recorded=recorded)
    )
    scorer = resolved_plugin.build_scorer(family_case)

    scores = score_replayed_episode(scorer=scorer, replayed=replayed)
    original_gate, original_objective = scorer.score_terminal_state(original.final_state)

    assert scores.gate == original_gate
    assert scores.objective == original_objective
    assert scores.gate.primary.value == 1.0
    assert scores.objective is not None
    assert scores.objective.leaf.estimand.units == "profit_usd"


def test_replay_and_verify_end_to_end_returns_a_matching_report(tmp_path: Path) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, family_case, original = _run_live(
        bridge, tmp_path, suffix="e2e"
    )
    recorded = record_episode(original)
    scorer = resolved_plugin.build_scorer(family_case)

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            plugin=resolved_plugin,
            scorer=scorer,
            recorded=recorded,
            original=original,
        )
    )

    assert report.status == "match"
    assert report.scores.gate.primary.value == 1.0
    assert report.final_state_sha256 == original.phase_instances[-1].post_state_sha256


def test_replay_raises_when_a_recorded_tool_result_is_tampered_with(tmp_path: Path) -> None:
    """The tool-level replay guarantee: step() itself catches this, and
    replay_episode must not swallow it."""
    bridge = _bridge()
    case, cell, resolved_plugin, family_case, original = _run_live(
        bridge, tmp_path, suffix="tamper"
    )
    recorded = record_episode(original)

    tampered_decisions = list(recorded.decisions)
    first = tampered_decisions[0]
    response = dict(first.response)
    executions = [dict(item) for item in response["tool_executions"]]
    executions[0] = dict(executions[0])
    executions[0]["result"] = dict(executions[0]["result"])
    executions[0]["result"]["content"] = {"product_ids": ["tampered"]}
    response["tool_executions"] = executions
    tampered_decisions[0] = RecordedDecision(
        phase_id=first.phase_id, seat_id=first.seat_id, response=response
    )
    tampered = RecordedEpisode(case_id=recorded.case_id, decisions=tuple(tampered_decisions))

    with pytest.raises(RuntimeError, match="tool replay result differs"):
        asyncio.run(
            replay_episode(cell=cell, case=case, plugin=resolved_plugin, recorded=tampered)
        )


def test_replay_requires_a_live_bridge_it_is_not_bridge_free(tmp_path: Path) -> None:
    """Pins down the corrected spec section 5 claim: "offline replay" means
    zero further MODEL calls, not zero bridge subprocess calls -- step()'s
    own tool-replay cross-check (exercised above by the tamper test) always
    re-derives every recorded tool result from a live bridge call, replay
    included, exactly like tau3_retail's replay re-executing tool calls
    through its own bridge. A plugin built with no bridge at all must fail
    loudly on replay, the same way a live run would -- never silently
    "succeed" by trusting the recorded evidence alone."""
    bridge = _bridge()
    case, cell, _resolved_plugin, family_case, original = _run_live(
        bridge, tmp_path, suffix="no_bridge"
    )
    recorded = record_episode(original)

    bridge_free_plugin = EconevalsPlugin(bridge=None)
    registry = PluginRegistry()
    register_plugin(registry, plugin=bridge_free_plugin)
    resolved_bridge_free_plugin = registry.resolve_manifest(family_manifest())

    with pytest.raises(RuntimeError, match="requires a provisioned EconevalsBridge"):
        asyncio.run(
            replay_episode(
                cell=cell, case=case, plugin=resolved_bridge_free_plugin, recorded=recorded
            )
        )


def test_replay_case_mismatch_raises_a_typed_replay_error(tmp_path: Path) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, family_case, original = _run_live(
        bridge, tmp_path, suffix="mismatch"
    )
    recorded = record_episode(original)
    wrong_case = RecordedEpisode(
        case_id="econevals.pricing.basic.999", decisions=recorded.decisions
    )

    with pytest.raises(ReplayError, match="not"):
        asyncio.run(
            replay_episode(cell=cell, case=case, plugin=resolved_plugin, recorded=wrong_case)
        )
