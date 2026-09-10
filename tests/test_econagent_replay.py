"""Tests for the econagent_v1 offline replayer (replay.py, spec section 5,
milestone 3).

See ``replay.py``'s own module docstring for why this family's replay seam
is the *bridge* (``EconAgentBridge``), not the scheduler's ``ResponseSource``
the way ``tau3_retail/replay.py`` replays tool calls -- every ``agent_i``
seat submits the same acknowledgment every month regardless of observation
(spec milestone-1 correction 4), so there is no per-seat decision content to
record or replay at the response-source layer at all.

Follows the same ``_require_bridge()``/skip convention as every other
econagent test file: pure, bridge-free structural tests run everywhere;
tests that actually record and replay a real bridge-driven episode run for
real when a provisioned bridge interpreter is available, and are skipped
(never faked) otherwise.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import pytest

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner import episode_id_for_cell, run_episode
from aeread.shared_runner.measurement import normalize_family_score_set
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import (
    ImplementationPin,
    PlanCell,
    RunPlan,
    canonical_json_bytes,
    case_content_sha256,
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
from aeread.shared_runner.task.evaluation import (
    SeatContext,
    finalize_family_execution,
    replay_family_scoring_input,
)
from aeread.shared_runner.task.execution import CanonicalResponse, CellExecution, EvidenceStore
from aeread.shared_runner.task.scheduler import EpisodeResult, SchedulerContractError
from aeread_families.econagent_v1 import cases as econagent_cases
from aeread_families.econagent_v1 import econagent_bridge as econagent_bridge_module
from aeread_families.econagent_v1 import environment as econagent_environment
from aeread_families.econagent_v1 import measurement as m
from aeread_families.econagent_v1.econagent_bridge import (
    EconAgentBridgeUnavailableError,
    discover_bridge_python,
)
from aeread_families.econagent_v1.environment import (
    PLUGIN_ID,
    SCORER_ID,
    EconAgentV1Plugin,
    family_manifest,
    register_plugin,
)
from aeread_families.econagent_v1.harness import ACK_RESPONSE
from aeread_families.econagent_v1.replay import (
    RecordedBridgeCall,
    RecordedEconAgentBridge,
    RecordedEconAgentEpisode,
    ReplayError,
    assert_replay_matches,
    compare_episode_results,
    replay_and_verify,
    replay_episode,
    run_and_record_episode,
    score_replayed_episode,
    score_tax_bracket_arithmetic_and_record,
)


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_ECONAGENT_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-econagent",
    )
    root = Path(candidate)
    if not (root / "config.yaml").is_file():
        pytest.skip(
            f"pinned upstream EconAgent checkout not found at {root}",
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()

try:
    BRIDGE_PYTHON = discover_bridge_python(upstream_root=UPSTREAM_ROOT)
except EconAgentBridgeUnavailableError as error:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = str(error)
else:
    _BRIDGE_SKIP_REASON = ""


def _require_bridge() -> None:
    if BRIDGE_PYTHON is None:
        pytest.skip(_BRIDGE_SKIP_REASON or "bridge python unavailable")


def _case(case_id: str = "econagent.pilot.tiny4x6.seed0") -> CaseManifest:
    path = Path("cases/econagent_v1") / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    n_agents = case.payload["scenario"]["n_agents"]
    profile_by_seat = {
        f"agent_{index}": "econagent_v1_scripted_complex" for index in range(n_agents)
    }
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_econagent_replay_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_econagent_replay",
        suite_version="0.1.0",
        block_id="block_econagent_replay",
        sampling_plan_id="sampling_econagent_replay",
        analysis_plan_id="analysis_econagent_replay",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_econagent_replay_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(profile_by_seat),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _run_live(*, suffix: str):
    _require_bridge()
    case = _case("econagent.pilot.tiny4x6.seed0")
    cell = _cell(case, suffix=suffix)
    result, recorded = asyncio.run(
        run_and_record_episode(cell=cell, case=case, upstream_root=UPSTREAM_ROOT)
    )
    return case, cell, result, recorded


def _scorer_for(case: CaseManifest):
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    family_case = plugin.validate_payload(case.payload)
    return plugin.build_scorer(family_case)


# ---------------------------------------------------------------------------
# Evidence-complete episode driving (kernel_scoring_contract_spec.md
# milestone 3): a response source that ALSO writes the full generic evidence
# trail ``task.evaluation.replay_family_scoring_input`` needs to replay, plus
# a real, ``resolve_run_plan``-resolved ``RunPlan`` -- both required to drive
# ``task.evaluation.finalize_family_execution`` for this family for the
# first time, and reused by ``tests/test_shared_runner_scoring_contract.py``
# for its own paired-history fixtures.
# ---------------------------------------------------------------------------


class EvidenceRecordingEconAgentHarness:
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
    cost machinery (mirrors ``tests/test_govsim_replay.py``'s identically-
    purposed ``EvidenceRecordingGovsimHarness``).

    ``ScriptedEconAgentHarness`` (this family's existing scripted response
    source, ``harness.py``) writes NO evidence at all and has never produced
    evidence ``aeread.shared_runner.task.evaluation.replay_family_scoring_input``
    can replay -- this class is what makes driving THAT finalizer for this
    family possible at all. Unlike govsim's harness, there is no per-phase
    decision to branch on (spec milestone-1 correction 4): every request gets
    the exact same acknowledgment (``harness.ACK_RESPONSE``), verbatim.
    """

    def __init__(self, *, evidence: EvidenceStore) -> None:
        self._evidence = evidence

    async def __call__(self, request: Any) -> dict[str, Any]:
        response = dict(ACK_RESPONSE)
        self._evidence.append_event(
            "logical_action_started",
            {"request": request},
            phase_instance_id=request.phase_instance_id,
            logical_action_id=request.logical_action_id,
            visibility=f"seat:{request.seat_id}",
        )
        # A CanonicalResponse-shaped placeholder purely for replay provenance
        # (``LogicalActionRecord.response``): this family's own
        # ``parse_action`` never reads it (the scheduler hands it the raw
        # ``response`` dict returned above, unchanged), and replay itself
        # reconstructs ``parse``/``legality`` directly from the
        # "action_parsed"/"action_legality_checked" events below, never
        # from this response.
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


def kernel_contract_fixture_case(
    *,
    world_seed: int,
    suffix: str,
    n_agents: int = 2,
    episode_length: int = 1,
    beta: float = 0.1,
    gamma: float = 0.1,
    h: float = 1.0,
) -> CaseManifest:
    """A small, fast, fully-controlled econagent_v1 case for the kernel
    scoring-contract protocol test's own paired-history fixtures.

    Distinct from the checked-in three-scenario corpus (``cases.py``'s own
    ``SCENARIOS``, always ``beta=gamma=0.1, h=1.0``): this fixture case lets
    ``beta``/``gamma``/``h`` vary so a genuine, real-bridge-verified
    paired-history pair can be constructed (see this module's own
    ``test_kernel_contract_scoring_fixtures_are_a_genuine_paired_history_pair``).
    Never written to the on-disk corpus. Real pins (``cases.build_pins``),
    never fabricated -- ``EconAgentV1Plugin.validate_payload`` cross-checks
    every pin field against the actual pinned upstream checkout.
    """
    pins = econagent_cases.build_pins(UPSTREAM_ROOT)
    case_id = f"econagent.kernel_contract_fixture.{suffix}"
    seats = [{"id": f"agent_{index}", "role": "agent"} for index in range(n_agents)]
    raw: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": case_id,
        "family_id": econagent_cases.FAMILY_ID,
        "family_version": econagent_cases.FAMILY_VERSION,
        "split": econagent_cases.SPLIT,
        "world_seed": world_seed,
        "seats": seats,
        "episode": {
            "max_logical_actions": n_agents * episode_length,
            "termination": list(econagent_cases.TERMINATION_REASONS),
        },
        "visibility_policy": econagent_cases.VISIBILITY_POLICY,
        "payload": {
            "scenario": {
                "case_id": case_id,
                "n_agents": n_agents,
                "episode_length": episode_length,
                "world_seed": world_seed,
                "beta": beta,
                "gamma": gamma,
                "h": h,
                "purpose": (
                    "kernel_scoring_contract_spec.md milestone-3 paired-history "
                    "fixture, never run as part of the declared, gated corpus"
                ),
            },
            "pins": dict(pins),
        },
        "provenance": {
            "generator_id": "econagent_v1_kernel_contract_fixture_generator_v1",
            "generator_version": "1.0.0",
            "review_status": "curated",
        },
        "content_sha256": "0" * 64,
    }
    raw["content_sha256"] = case_content_sha256(raw)
    return CaseManifest.from_dict(raw)


@dataclass(frozen=True, slots=True)
class EconAgentSetup:
    """A resolved, provider-free ``RunPlan`` for one econagent_v1 case.

    This family's real runtime never goes through ``execute_plan_cell``'s
    harness/provider stack at all -- every seat is answered directly through
    ``run_episode``'s ``response_source``
    (``ScriptedEconAgentHarness``/``EvidenceRecordingEconAgentHarness``
    above). The declared ``minimal_chat`` harness and fixture provider below
    exist purely to satisfy ``resolve_run_plan``'s structural pin/capability
    checks and are never actually invoked (mirrors
    ``tests/test_govsim_replay.py``'s identically-purposed ``GovsimSetup``).
    """

    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, Any]


_ECONAGENT_FIXTURE_PROFILE_ID = "econagent_v1_unused_fixture_profile_v1"
_ECONAGENT_FIXTURE_PROVIDER_ID = "econagent_v1_unused_fixture_provider"
_ECONAGENT_FIXTURE_RUNTIME_ID = "aeread.shared_runner.task.execution"


def _pin(component_id: str, kind: str, *, version: str, sha256: str) -> ImplementationPin:
    return ImplementationPin.from_dict(
        {"component_id": component_id, "kind": kind, "version": version, "sha256": sha256}
    )


def _file_pin(component_id: str, kind: str, source_path: Path, *, version: str) -> ImplementationPin:
    return _pin(
        component_id, kind, version=version, sha256=hashlib.sha256(source_path.read_bytes()).hexdigest()
    )


def _measurement_pins(pins: Mapping[str, Any]) -> tuple[ImplementationPin, ...]:
    """One pin per distinct implementation referenced by this family's own
    declared leaves (``measurement.py``'s three ``build_*_leaf`` functions):
    each leaf's validity-domain predicate, verifier-reference implementation,
    and scorer. Built straight from the same ``ImplementationRef`` values the
    leaves themselves carry -- never a hand-typed id or a re-hashed file --
    so this can never drift from what ``EvaluationReceipt._validate_and_
    freeze_plan_pins`` will actually require. Every one of these is a
    ``family.scoring.reference_provider_ids`` entry (``environment.py``'s
    ``family_manifest()``), so ``resolve_run_plan``'s own
    ``_required_pin_kinds`` requires kind ``"reference"`` for ALL of them --
    including the leaf-level scorer refs -- never ``"scorer"`` (that kind is
    reserved for ``family.scoring.scorer_id`` itself, pinned separately
    below).
    """
    leaves = m.build_leaves(pins)
    refs: dict[str, Any] = {}
    for leaf in leaves:
        refs[leaf.estimand.validity_domain.predicate.implementation_id] = (
            leaf.estimand.validity_domain.predicate
        )
        refs[leaf.verifier.reference.implementation.implementation_id] = (
            leaf.verifier.reference.implementation
        )
        refs[leaf.scorer.implementation_id] = leaf.scorer
    return tuple(
        _pin(ref.implementation_id, "reference", version=ref.version, sha256=ref.content_sha256)
        for ref in refs.values()
    )


def build_econagent_setup(case: CaseManifest, *, suffix: str) -> EconAgentSetup:
    """Resolve a real, one-cell ``RunPlan`` for ``case`` (spec section 5.3).

    Every agent seat shares one placeholder agent profile: this family's real
    runtime never invokes it (see ``EconAgentSetup``'s own docstring), so the
    harness/provider it names exist only to satisfy ``resolve_run_plan``'s
    structural checks.
    """
    family = family_manifest()
    seat_ids = [seat.id for seat in case.seats]
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": f"econagent_{suffix}_sample_v1",
            "estimand": "fixed_econagent_case",
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
            "block_id": f"econagent_{suffix}_block",
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
            "analysis_plan_id": f"econagent_{suffix}_analysis_v1",
            "estimands": [m.BUDGET_IDENTITY_ESTIMAND_ID],
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
            "suite_id": f"econagent_{suffix}_suite_v1",
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
            "profile_id": _ECONAGENT_FIXTURE_PROFILE_ID,
            "model": {
                "provider": _ECONAGENT_FIXTURE_PROVIDER_ID,
                "model": "econagent_v1_unused_fixture_model_v1",
                "revision": "1.0.0",
                "base_url": None,
            },
            "harness": {
                "id": "minimal_chat",
                "version": "1.0",
                "config": {},
            },
            "prompt": {
                "prompt_id": f"econagent_{suffix}_prompt_v1",
                "sha256": hashlib.sha256(
                    b"econagent scripted acknowledgment: no prompt is ever sent"
                ).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": _ECONAGENT_FIXTURE_RUNTIME_ID,
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "econagent_scripted_no_reasoning_v1",
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
            "run_spec_id": f"econagent_{suffix}_run_spec_v1",
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
    register_plugin(registry, upstream_root=UPSTREAM_ROOT)
    harness_registry = HarnessRegistry()
    for harness in default_harnesses().values():
        harness_registry.register(harness)

    environment_path = Path(econagent_environment.__file__)
    execution_path = Path(execution_module.__file__)
    pins = (
        _file_pin(PLUGIN_ID, "family_plugin", environment_path, version="0.1.0"),
        _file_pin(SCORER_ID, "scorer", environment_path, version="0.1.0"),
        _file_pin("minimal_chat", "harness", execution_path, version="1.0"),
        _file_pin(_ECONAGENT_FIXTURE_RUNTIME_ID, "runtime", execution_path, version="0.1.0"),
        *_measurement_pins(case.payload["pins"]),
    )
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
            _ECONAGENT_FIXTURE_PROVIDER_ID: ProviderCapabilities(
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
    return EconAgentSetup(plan=plan, registry=registry, prompt_sources={}, pricing={})


def test_finalize_wires_econagent_to_the_shared_family_finalizer(tmp_path: Path) -> None:
    """This family has never produced an ``EvaluationReceipt``.

    Every other family already migrated to the ``FamilyScoringInput``
    contract has at least one test driving a real episode through
    ``task.evaluation.finalize_family_execution`` (see
    ``tests/test_govsim_replay.py``'s identically-purposed
    ``test_finalize_wires_govsim_to_the_shared_family_finalizer``); econagent
    had none, because its existing scripted response source
    (``ScriptedEconAgentHarness``) writes no evidence at all --
    ``EvidenceRecordingEconAgentHarness`` (this module, above) is what makes
    this reachable. Drives one small, real, bridge-backed episode (the
    checked-in ``econagent.pilot.tiny4x6.seed0`` case) end to end through the
    real finalizer and asserts a clean receipt comes back carrying every one
    of this family's three declared finalize-time leaves.
    """
    _require_bridge()
    case = _case("econagent.pilot.tiny4x6.seed0")
    setup = build_econagent_setup(case, suffix="finalize_receipt")
    cell = setup.plan.cells[0]
    family = setup.plan.families[0]
    plugin = setup.registry.resolve_manifest(family)

    evidence = EvidenceStore(
        tmp_path / "evidence_finalize_receipt",
        run_plan_id=setup.plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_id=f"episode_{cell.cell_id}",
        episode_attempt_id="attempt_1",
    )
    harness = EvidenceRecordingEconAgentHarness(evidence=evidence)
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=harness)
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

    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"
    assert {score.leaf.leaf_id for score in receipt.scores} == {
        m.BUDGET_IDENTITY_LEAF_ID,
        m.TAX_BRACKET_LEAF_ID,
        m.MACRO_TRAJECTORY_LEAF_ID,
    }
    assert receipt.primary_leaf_id == m.BUDGET_IDENTITY_LEAF_ID
    evidence_refs = {score.evidence_refs for score in receipt.scores}
    assert len(evidence_refs) == 1
    budget_identity = next(
        score for score in receipt.scores if score.leaf.leaf_id == m.BUDGET_IDENTITY_LEAF_ID
    )
    assert budget_identity.status == "ok"


# ---------------------------------------------------------------------------
# The whole-outcome paired-history pair (kernel_scoring_contract_spec.md
# ruling R7/R9(a)'s precondition): docs/econagent_migration_plan.md found it
# "constructible... to be verified against the real bridge in a later
# milestone, not merely asserted". Verified below, against two real,
# bridge-backed episodes.
# ---------------------------------------------------------------------------


def run_kernel_contract_fixture(
    tmp_path: Path,
    *,
    world_seed: int,
    suffix: str,
    n_agents: int = 2,
    episode_length: int = 1,
    beta: float = 0.1,
    gamma: float = 0.1,
    h: float = 1.0,
) -> tuple[EconAgentSetup, EconAgentV1Plugin, Mapping[str, Any], EvidenceStore]:
    """Run one small, real, bridge-backed kernel-contract fixture episode end
    to end through the real scheduler and return everything a caller needs
    to either build a ``FamilyScoringFixture``
    (tests/test_shared_runner_scoring_contract.py) or replay it directly
    (this module's own paired-history test, below): the resolved ``setup``,
    the registered ``plugin`` (needed for replay: this family's
    ``bridge_session_id`` is minted per plugin instance, see
    ``EconAgentV1Plugin._mint_session_id``), the validated ``family_case``,
    and the sealed ``evidence``.
    """
    _require_bridge()
    case = kernel_contract_fixture_case(
        world_seed=world_seed,
        suffix=suffix,
        n_agents=n_agents,
        episode_length=episode_length,
        beta=beta,
        gamma=gamma,
        h=h,
    )
    setup = build_econagent_setup(case, suffix=suffix)
    cell = setup.plan.cells[0]
    family = setup.plan.families[0]
    plugin = setup.registry.resolve_manifest(family)
    family_case = plugin.validate_payload(case.payload)

    evidence = EvidenceStore(
        tmp_path / f"evidence_kernel_contract_{suffix}",
        run_plan_id=setup.plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_id=episode_id_for_cell(cell),
        episode_attempt_id="attempt_1",
    )
    harness = EvidenceRecordingEconAgentHarness(evidence=evidence)
    asyncio.run(run_episode(cell=cell, case=case, plugin=plugin, response_source=harness))
    return setup, plugin, family_case, evidence


def test_paired_history_pair_has_a_byte_identical_outcome_and_a_differing_trajectory(
    tmp_path: Path,
) -> None:
    """kernel_scoring_contract_spec.md milestone 3: docs/econagent_migration_
    plan.md found a whole-outcome paired-history pair "constructible... to
    be verified against the real bridge in a later milestone, not merely
    asserted" -- verified here, against two real, bridge-backed episodes,
    not merely asserted in a comment.

    Every one of this family's three leaves is declared
    ``input_scope="trajectory"`` (no ``terminal_state`` leaf exists), so
    ruling R7's mislabelling-contrapositive has nothing to check for this
    family; this pair exists only to satisfy R7/R9(a)'s own PRECONDITION (a
    byte-identical PROJECTED outcome -- this family declares no
    ``trajectory_outcome_paths``, so the projection is the whole outcome --
    produced by a genuinely differing trajectory). Verified directly here
    rather than through ``_assert_family_obeys_the_scoring_contract`` --
    see ``tests/test_shared_runner_scoring_contract.py``'s
    ``_SINGLE_FIXTURE_EXEMPT_FAMILIES`` entry for this family for why
    ruling R9(b)'s SEPARATE same-case sensitivity-witness requirement
    cannot be satisfied by any fixture this family could honestly supply,
    independent of whether this pair exists.

    **Construction, by domain reasoning, not luck.** Upstream's own
    ``complex_actions`` decides labor via
    ``int(np.random.uniform() < (income / (wealth * (1+interest_rate) +
    1e-8)) ** gamma)``. At month 1, every agent's ``wealth`` (``Coin``
    inventory) is exactly the pinned config's own starting balance of
    ``0`` -- seed-independent -- so with ``gamma < 0`` the base
    ``income / (0 + 1e-8)`` (a huge positive number since ``income`` is
    always positive) raised to a NEGATIVE power underflows to (as verified
    empirically against the real bridge while building this fixture,
    exactly) ``0.0``, making every agent's labor draw ``False`` with
    certainty regardless of ``world_seed``: zero income, zero tax, zero
    lump-sum redistribution (nothing was collected to redistribute), and
    upstream's own consumption components clip nominal spend to available
    wealth (``0``), so actual ``consumption_spend`` is also ``0`` --
    leaving every agent's Coin balance unchanged at ``0`` for the whole
    (one-month) episode. Two different ``world_seed``s therefore produce a
    byte-identical outcome from genuinely different skill draws, prices,
    and nominal per-agent actions (asserted below, not merely claimed).
    """
    left_setup, left_plugin, left_case, left_evidence = run_kernel_contract_fixture(
        tmp_path, world_seed=0, suffix="paired_left", gamma=-1.0
    )
    right_setup, right_plugin, right_case, right_evidence = run_kernel_contract_fixture(
        tmp_path, world_seed=1, suffix="paired_right", gamma=-1.0
    )
    del left_setup, right_setup

    # A genuinely different case (world_seed), never a duplicate of the same
    # run relabelled.
    assert left_case != right_case

    left_input = replay_family_scoring_input(
        plugin=left_plugin,
        family_case=left_case,
        evidence=left_evidence,
        seat_context=SeatContext((), {}),
    )
    right_input = replay_family_scoring_input(
        plugin=right_plugin,
        family_case=right_case,
        evidence=right_evidence,
        seat_context=SeatContext((), {}),
    )

    # The byte-identity claim, verified here -- not asserted in a comment.
    assert canonical_json_bytes(left_input.outcome) == canonical_json_bytes(
        right_input.outcome
    )
    assert left_input.outcome == {
        "termination_reason": "episode_length_reached",
        "timestep": 1,
        "n_agents": 2,
        "final_inventory_coin": {"0": 0.0, "1": 0.0},
    }
    # A genuinely differing trajectory, not a coincidence of identical
    # replayed state.
    assert left_input.phase_instances != right_input.phase_instances

    # Both trajectories are honestly scoreable end to end (never merely
    # replayable): the same seam finalize_family_execution calls.
    left_scores = normalize_family_score_set(
        left_plugin.build_scorer(left_case)(
            left_input, evidence_refs=left_input.evidence_refs
        )
    )
    right_scores = normalize_family_score_set(
        right_plugin.build_scorer(right_case)(
            right_input, evidence_refs=right_input.evidence_refs
        )
    )
    for leaf_id in (
        m.BUDGET_IDENTITY_LEAF_ID,
        m.TAX_BRACKET_LEAF_ID,
        m.MACRO_TRAJECTORY_LEAF_ID,
    ):
        left_score = next(
            score for score in left_scores.scores if score.leaf.leaf_id == leaf_id
        )
        right_score = next(
            score for score in right_scores.scores if score.leaf.leaf_id == leaf_id
        )
        assert left_score.status == "ok"
        assert right_score.status == "ok"


def test_call_output_is_sensitive_to_phase_instances_for_every_declared_leaf(
    tmp_path: Path,
) -> None:
    """docs/econagent_migration_review.md finding 3: neither existing check
    would catch ``EconAgentV1Scorer.__call__`` regressing to a constant,
    always-``"ok"`` output that never actually reads its OWN call's
    ``scoring_input.phase_instances``. ``tests/test_shared_runner_scoring_
    contract.py``'s ``_SINGLE_FIXTURE_EXEMPT_FAMILIES`` entry for this
    family means the shared protocol's ``_assert_trajectory_leaves_are_
    witnessed`` (ruling R9(b)) never runs for ``econagent_v1`` at all --
    and the paired-history test immediately above checks only
    ``status == "ok"`` for both fixtures, never any measurement content,
    so a scorer collapsed to a constant would pass it too.

    A true R9(b) SAME-CASE witness is structurally impossible for this
    family (see that test module's own comment on
    ``_SINGLE_FIXTURE_EXEMPT_FAMILIES``'s ``econagent_v1`` entry:
    ``world_seed``/``beta``/``gamma``/``h`` fully and deterministically
    determine the whole trajectory, so two fixtures sharing one
    ``family_case`` always share one trajectory too, and R9(b) needs a
    byte-identical ``family_case`` with a DIFFERING trajectory). This test
    therefore witnesses non-constancy a different, weaker way that needs
    no economic coincidence and no same-case pair: two fixtures differing
    ONLY in ``episode_length`` (one month vs. two, same ``world_seed``)
    produce, by construction, a different NUMBER of agent-months in their
    dense logs -- so ``econagent_budget_identity``'s and
    ``econagent_tax_bracket_arithmetic``'s own ``checked_agent_months``
    metric, and ``econagent_macro_trajectory``'s own per-month metric
    count, MUST differ between the two if ``__call__`` genuinely reads its
    OWN call's ``phase_instances``, and CANNOT differ if it reads a
    cached, hardcoded, or otherwise constant trajectory instead. This
    proves non-constancy, not genuine economic trajectory-dependence
    (ruling R9(b)'s own stated limit) -- the paired-history test above
    already establishes the byte-identical-outcome precondition
    separately, and is not repeated here.
    """
    left_setup, left_plugin, left_case, left_evidence = run_kernel_contract_fixture(
        tmp_path, world_seed=0, suffix="sensitivity_left", episode_length=1
    )
    right_setup, right_plugin, right_case, right_evidence = run_kernel_contract_fixture(
        tmp_path, world_seed=0, suffix="sensitivity_right", episode_length=2
    )
    del left_setup, right_setup

    left_input = replay_family_scoring_input(
        plugin=left_plugin,
        family_case=left_case,
        evidence=left_evidence,
        seat_context=SeatContext((), {}),
    )
    right_input = replay_family_scoring_input(
        plugin=right_plugin,
        family_case=right_case,
        evidence=right_evidence,
        seat_context=SeatContext((), {}),
    )
    # A genuinely different trajectory, not a coincidence of identical
    # replayed state.
    assert left_input.phase_instances != right_input.phase_instances

    left_scores = normalize_family_score_set(
        left_plugin.build_scorer(left_case)(
            left_input, evidence_refs=left_input.evidence_refs
        )
    )
    right_scores = normalize_family_score_set(
        right_plugin.build_scorer(right_case)(
            right_input, evidence_refs=right_input.evidence_refs
        )
    )

    for leaf_id in (m.BUDGET_IDENTITY_LEAF_ID, m.TAX_BRACKET_LEAF_ID):
        left_score = next(
            score for score in left_scores.scores if score.leaf.leaf_id == leaf_id
        )
        right_score = next(
            score for score in right_scores.scores if score.leaf.leaf_id == leaf_id
        )
        assert left_score.status == "ok"
        assert right_score.status == "ok"
        assert (
            left_score.metrics["checked_agent_months"].value
            != right_score.metrics["checked_agent_months"].value
        ), (
            f"{leaf_id}: checked_agent_months is identical across two fixtures "
            "with a different episode_length -- __call__ is not reading this "
            "call's own phase_instances"
        )

    left_macro = next(
        score
        for score in left_scores.scores
        if score.leaf.leaf_id == m.MACRO_TRAJECTORY_LEAF_ID
    )
    right_macro = next(
        score
        for score in right_scores.scores
        if score.leaf.leaf_id == m.MACRO_TRAJECTORY_LEAF_ID
    )
    assert left_macro.status == "ok"
    assert right_macro.status == "ok"
    assert len(left_macro.metrics) != len(right_macro.metrics), (
        "econagent_macro_trajectory: metric count is identical across two "
        "fixtures with a different episode_length -- __call__ is not reading "
        "this call's own phase_instances"
    )


# ---------------------------------------------------------------------------
# Pure, no bridge: RecordedBridgeCall/RecordedEconAgentEpisode round-tripping
# and RecordedEconAgentBridge's ordering/exhaustion contract.
# ---------------------------------------------------------------------------


def test_recorded_bridge_call_round_trips_through_plain_dict() -> None:
    call = RecordedBridgeCall(
        method="recompute_tax",
        args={"incomes": {"0": 1000.0, "1": (2000.0,)}},
        response={"results": {"0": {"tax_due": 1.0}}},
    )
    restored = RecordedBridgeCall.from_dict(call.to_dict())
    assert restored.method == "recompute_tax"
    # Tuple/list distinctions collapse to JSON arrays through the round trip.
    assert restored.args == {"incomes": {"0": 1000.0, "1": [2000.0]}}
    assert restored.response == {"results": {"0": {"tax_due": 1.0}}}


def test_recorded_econagent_episode_round_trips_through_plain_json() -> None:
    calls = (
        RecordedBridgeCall(method="start_episode", args={"n_agents": 4}, response={"ok": True}),
        RecordedBridgeCall(method="step_month", args={}, response={"timestep": 1}),
    )
    episode = RecordedEconAgentEpisode(
        case_id="econagent.pilot.tiny4x6.seed0", session_calls=calls
    )
    text = episode.to_json()
    restored = RecordedEconAgentEpisode.from_json(text)

    assert restored.case_id == episode.case_id
    assert len(restored.session_calls) == 2
    assert restored.session_calls[0].method == "start_episode"
    assert restored.session_calls[1].response == {"timestep": 1}


def test_recorded_bridge_enforces_call_order_and_reports_exhaustion() -> None:
    calls = (
        RecordedBridgeCall(
            method="start_episode",
            args={"n_agents": 4, "episode_length": 1, "world_seed": 0},
            response={"ok": True},
        ),
        RecordedBridgeCall(method="step_month", args={}, response={"timestep": 1, "done": False}),
    )
    bridge = RecordedEconAgentBridge(calls)

    assert bridge.start_episode(n_agents=4, episode_length=1, world_seed=0) == {"ok": True}
    assert bridge.exhausted is False
    assert bridge.step_month() == {"timestep": 1, "done": False}
    assert bridge.exhausted is True

    with pytest.raises(ReplayError, match="exhausted"):
        bridge.agent_snapshot()


def test_recorded_bridge_rejects_a_method_order_mismatch() -> None:
    calls = (RecordedBridgeCall(method="step_month", args={}, response={"timestep": 1}),)
    bridge = RecordedEconAgentBridge(calls)

    with pytest.raises(ReplayError, match="does not match"):
        bridge.agent_snapshot()


def test_recorded_bridge_rejects_a_start_episode_argument_mismatch() -> None:
    """Regression guard for the "replay ignores episode-start arguments"
    finding (docs/econagent_codex_triage.md finding 2): ``start_episode``
    used to discard its own ``kwargs`` entirely (``del kwargs``) and serve
    the recorded response purely by call order, so a replayed episode's
    genuinely different scenario parameters (``n_agents``/``episode_length``/
    ``world_seed``/``beta``/``gamma``/``h``) went unchecked -- a record made
    for a 4-agent, seed-0 episode could be replayed as a 99-agent, seed-999
    episode and still succeed."""
    calls = (
        RecordedBridgeCall(
            method="start_episode",
            args={"n_agents": 4, "world_seed": 0},
            response={"ok": True},
        ),
    )
    bridge = RecordedEconAgentBridge(calls)

    with pytest.raises(ReplayError, match="arguments do not match"):
        bridge.start_episode(n_agents=99, world_seed=999)


def test_recorded_bridge_serves_start_episode_when_arguments_match() -> None:
    calls = (
        RecordedBridgeCall(
            method="start_episode",
            args={"n_agents": 4, "world_seed": 0},
            response={"ok": True},
        ),
    )
    bridge = RecordedEconAgentBridge(calls)

    assert bridge.start_episode(n_agents=4, world_seed=0) == {"ok": True}
    assert bridge.exhausted is True


def test_recorded_bridge_rejects_a_recompute_tax_income_mismatch() -> None:
    """Regression guard: unlike every other replayed method, `recompute_tax`
    must not serve its recorded response purely by call order -- the
    replayed `incomes` argument (re-derived from the replayed episode's own
    dense_log) has to equal what the original live scoring call actually
    recorded, or a dense_log/income divergence introduced elsewhere could
    silently reuse a stale recorded `tax_due` against different incomes."""
    calls = (
        RecordedBridgeCall(
            method="recompute_tax",
            args={"incomes": {"0": 1000.0}},
            response={"0": {"tax_due": 1.0}},
        ),
    )
    bridge = RecordedEconAgentBridge(calls)

    with pytest.raises(ReplayError, match="arguments do not match"):
        bridge.recompute_tax({"0": 2000.0})


def test_recorded_bridge_serves_recompute_tax_when_incomes_match() -> None:
    calls = (
        RecordedBridgeCall(
            method="recompute_tax",
            args={"incomes": {"0": 1000.0}},
            response={"0": {"tax_due": 1.0}},
        ),
    )
    bridge = RecordedEconAgentBridge(calls)

    assert bridge.recompute_tax({"0": 1000.0}) == {"0": {"tax_due": 1.0}}
    assert bridge.exhausted is True


def test_compare_episode_results_reports_specific_mismatches_not_one_boolean() -> None:
    """A synthetic mismatch (mutated terminal) must be visible per-component."""

    class _Fake:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    original = _Fake(
        phase_instances=(),
        terminal={"reason": "episode_length_reached", "timestep": 6},
        outcome={"termination_reason": "episode_length_reached"},
        final_state={"timestep": 6},
    )
    replayed = _Fake(
        phase_instances=(),
        terminal={"reason": "episode_length_reached", "timestep": 5},
        outcome={"termination_reason": "episode_length_reached"},
        final_state={"timestep": 6},
    )

    comparison = compare_episode_results(original, replayed)

    assert comparison.terminal_matches is False
    assert comparison.outcome_matches is True
    assert comparison.final_state_matches is True
    assert comparison.matches is False
    with pytest.raises(ReplayError, match="terminal record differs"):
        assert_replay_matches(comparison)


# ---------------------------------------------------------------------------
# Bridge-gated: record a real live episode, replay it with the bridge
# subprocess disabled entirely, and cross-check.
# ---------------------------------------------------------------------------


def test_recorded_episode_captures_the_expected_bridge_call_sequence() -> None:
    """4 agents x 6 months: start_episode, agent_snapshot, then
    (step_month, agent_snapshot) x 6, then dense_log, close."""
    _require_bridge()
    _case_obj, _cell_obj, _result, recorded = _run_live(suffix="sequence")

    methods = [call.method for call in recorded.session_calls]
    assert methods == (
        ["start_episode", "agent_snapshot"]
        + ["step_month", "agent_snapshot"] * 6
        + ["dense_log", "close"]
    )


def test_replay_from_a_json_round_tripped_record_reproduces_the_live_run() -> None:
    case, cell, original, recorded = _run_live(suffix="live")

    # Force a genuine round trip through plain JSON text -- proves replay
    # never depends on reusing the original run's in-memory Python objects.
    recorded = RecordedEconAgentEpisode.from_json(recorded.to_json())
    assert recorded.case_id == case.case_id

    # Patch EconAgentBridge._spawn out from under the bridge module for the
    # duration of the replay -- if replay_episode ever tried to spawn the
    # real upstream bridge subprocess (rather than serving from the
    # recorded call log), this would raise immediately. Narrower than
    # patching `subprocess.Popen` globally, which would also break
    # `EconAgentV1Plugin.validate_payload`'s own unrelated `git`
    # subprocess.run calls (git itself is spawned through Popen
    # internally). This is the literal proof behind spec section 5's "the
    # bridge process disabled entirely".
    def _must_not_spawn(_self: Any) -> Any:
        raise AssertionError("replay must never spawn the real bridge subprocess")

    original_spawn = econagent_bridge_module.EconAgentBridge._spawn
    econagent_bridge_module.EconAgentBridge._spawn = _must_not_spawn  # type: ignore[assignment]
    try:
        replayed = asyncio.run(
            replay_episode(
                cell=cell, case=case, upstream_root=UPSTREAM_ROOT, recorded=recorded
            )
        )
    finally:
        econagent_bridge_module.EconAgentBridge._spawn = original_spawn

    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is True
    assert comparison.final_state_content_matches is True
    assert comparison.terminal_matches is True
    assert comparison.outcome_matches is True
    assert replayed.terminal["reason"] == "episode_length_reached"

    # `EconAgentV1Plugin.initial_state` derives `bridge_session_id`
    # deterministically from the real scheduler's own `cell.cell_id` (fix
    # for docs/econagent_codex_triage.md finding 6), so the RAW, byte-exact
    # state matches too here -- both this live run and its replay were
    # driven through the same `cell`. See
    # `test_replay_reproduces_the_byte_exact_canonical_final_state_for_the_identical_cell`
    # for the dedicated regression test and `replay._strip_bridge_session_id`
    # for the one case (`cell=None`, bypassing the real scheduler) where raw
    # agreement still cannot be assumed.
    assert comparison.final_state_matches is True
    assert canonical_json_bytes(replayed.final_state) == canonical_json_bytes(
        original.final_state
    )


def test_replay_reproduces_the_byte_exact_canonical_final_state_for_the_identical_cell() -> None:
    """Finding 6 (docs/econagent_codex_triage.md): ``initial_state()`` used
    to mint a fresh ``uuid.uuid4().hex`` ``bridge_session_id`` on every call,
    so two executions of the identical case/plan/seed -- a live run and its
    own offline replay, both driven through the real production path
    (``run_and_record_episode``/``replay_episode``) with the exact same
    ``cell`` -- produced different canonical states and hashes even though
    nothing about the episode itself differed; only the semantic comparison
    (content with ``bridge_session_id`` stripped) could report agreement.
    Now that ``bridge_session_id`` is derived deterministically from the
    real scheduler's own ``cell.cell_id``, the raw final state -- not just
    its stripped content -- matches byte-for-byte, with no stripping needed.
    """
    _require_bridge()
    case, cell, original, recorded = _run_live(suffix="determinism")
    recorded = RecordedEconAgentEpisode.from_json(recorded.to_json())

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, upstream_root=UPSTREAM_ROOT, recorded=recorded)
    )

    comparison = compare_episode_results(original, replayed)
    assert comparison.final_state_matches is True
    assert canonical_json_bytes(replayed.final_state) == canonical_json_bytes(
        original.final_state
    )
    assert (
        original.final_state["bridge_session_id"]
        == replayed.final_state["bridge_session_id"]
    )


def test_initial_state_mints_distinct_session_ids_for_two_different_cells_of_the_same_case() -> None:
    """Guards the finding-6 determinism fix against a narrower, unsafe
    implementation that derived ``bridge_session_id`` from scenario fields
    alone (n_agents/episode_length/world_seed/...) rather than
    ``cell.cell_id``: that would collide for two concurrently-running
    replicates of the identical case, silently corrupting both sessions'
    bridge lookups (``EconAgentV1Plugin._sessions`` is keyed by
    ``bridge_session_id`` alone). Two distinct cells of the same case must
    never share a session id.
    """
    _require_bridge()
    case = _case("econagent.pilot.tiny4x6.seed0")
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    family_case = plugin.validate_payload(case.payload)
    cell_a = _cell(case, suffix="concurrent-a")
    cell_b = _cell(case, suffix="concurrent-b")

    state_a = plugin.initial_state(family_case, cell_a)
    try:
        state_b = plugin.initial_state(family_case, cell_b)
        try:
            assert state_a["bridge_session_id"] != state_b["bridge_session_id"]
            assert len(plugin._sessions) == 2
        finally:
            plugin._sessions.pop(state_b["bridge_session_id"]).close()
    finally:
        plugin._sessions.pop(state_a["bridge_session_id"]).close()


def test_initial_state_refuses_to_start_the_same_cell_twice_concurrently() -> None:
    """A session's bridge is looked up by ``bridge_session_id`` alone
    (``_require_session``); silently overwriting an already-active entry
    for the same cell would orphan the first session's own bridge with no
    way to reach it (or close it) again. ``_mint_session_id`` raises
    instead of allowing that."""
    _require_bridge()
    case = _case("econagent.pilot.tiny4x6.seed0")
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    family_case = plugin.validate_payload(case.payload)
    cell = _cell(case, suffix="reused")

    state = plugin.initial_state(family_case, cell)
    try:
        with pytest.raises(RuntimeError, match="already active"):
            plugin.initial_state(family_case, cell)
    finally:
        plugin._sessions.pop(state["bridge_session_id"]).close()


def test_replay_recomputes_all_three_leaves_with_zero_live_calls() -> None:
    _require_bridge()
    case, cell, original, recorded = _run_live(suffix="score")
    scorer = _scorer_for(case)

    original_dense_log = original.terminal["dense_log"]
    original_n_agents = original.terminal["n_agents"]
    original_month_actions = original.terminal["month_actions"]
    original_world_period = original.terminal["final_world"]["period"]
    original_world_interest_rate_by_month = original.terminal["world_interest_rate_by_month"]
    original_budget = scorer.score_budget_identity(
        dense_log=original_dense_log,
        n_agents=original_n_agents,
        world_period=original_world_period,
        month_actions=original_month_actions,
        world_interest_rate_by_month=original_world_interest_rate_by_month,
    )
    original_macro = scorer.score_macro_trajectory(
        dense_log=original_dense_log,
        n_agents=original_n_agents,
        month_actions=original_month_actions,
    )
    original_tax, tax_calls = score_tax_bracket_arithmetic_and_record(
        scorer,
        dense_log=original_dense_log,
        n_agents=original_n_agents,
        upstream_root=UPSTREAM_ROOT,
    )
    assert original_budget.primary.value == 1.0
    assert original_tax.primary.value == 1.0

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, upstream_root=UPSTREAM_ROOT, recorded=recorded)
    )
    scores = score_replayed_episode(
        scorer=scorer, replayed=replayed, tax_recompute_calls=tax_calls
    )

    assert scores.budget_identity == original_budget
    assert scores.tax_bracket_arithmetic == original_tax
    assert scores.macro_trajectory == original_macro


def test_replay_leaf2_detects_a_recorded_recompute_tax_income_mismatch() -> None:
    """Mutation check for the "recompute_tax replays by call order alone"
    gap: a `RecordedEconAgentBridge` double served purely by call order
    would silently reuse a stale recorded `tax_due` against incomes that no
    longer match what generated it. Tampering one recorded
    `recompute_tax` call's own `args["incomes"]` (never its response, and
    never call order/count) must be caught -- proving leaf 2's replay path
    actually checks its own recorded inputs, not just their sequence."""
    _require_bridge()
    case, cell, original, recorded = _run_live(suffix="tax-income-mismatch")
    scorer = _scorer_for(case)
    dense_log = original.terminal["dense_log"]
    n_agents = original.terminal["n_agents"]
    _tax_score, tax_calls = score_tax_bracket_arithmetic_and_record(
        scorer, dense_log=dense_log, n_agents=n_agents, upstream_root=UPSTREAM_ROOT
    )

    tampered_tax_calls = list(tax_calls)
    first_call = tampered_tax_calls[0]
    tampered_incomes = dict(first_call.args["incomes"])
    some_agent = next(iter(tampered_incomes))
    tampered_incomes[some_agent] = tampered_incomes[some_agent] + 1234.0
    tampered_tax_calls[0] = RecordedBridgeCall(
        method=first_call.method,
        args={"incomes": tampered_incomes},
        response=first_call.response,
    )

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, upstream_root=UPSTREAM_ROOT, recorded=recorded)
    )
    with pytest.raises(ReplayError, match="arguments do not match"):
        score_replayed_episode(
            scorer=scorer, replayed=replayed, tax_recompute_calls=tuple(tampered_tax_calls)
        )


def test_replay_rejects_a_recorded_start_episode_argument_mismatch() -> None:
    """Mutation check for the "replay ignores episode-start arguments"
    finding (docs/econagent_codex_triage.md finding 2), exercised through the
    REAL production path (``replay_episode`` -> ``run_episode`` ->
    ``EconAgentV1Plugin.initial_state`` -> the replay bridge's own
    ``start_episode``), never a hand-constructed ``RecordedEconAgentBridge``
    in isolation: tampering one recorded ``start_episode`` call's own
    ``args["world_seed"]`` (never its response, never call order/count) must
    be caught when the *same* case/cell -- whose own scenario still supplies
    the real, untampered ``world_seed`` -- is replayed against it."""
    _require_bridge()
    case, cell, _original, recorded = _run_live(suffix="start-episode-mismatch")

    tampered_calls = list(recorded.session_calls)
    first_call = tampered_calls[0]
    assert first_call.method == "start_episode"
    tampered_args = dict(first_call.args)
    tampered_args["world_seed"] = tampered_args["world_seed"] + 1
    tampered_calls[0] = RecordedBridgeCall(
        method=first_call.method, args=tampered_args, response=first_call.response
    )
    tampered = RecordedEconAgentEpisode(
        case_id=recorded.case_id, session_calls=tuple(tampered_calls)
    )

    # start_episode runs inside EconAgentV1Plugin.initial_state, which the
    # real scheduler's own run_episode() calls during preflight -- any
    # exception raised there (including this ReplayError) is therefore
    # surfaced wrapped as a SchedulerContractError ("family preflight
    # failed: ..."), unlike the leaf-2 recompute_tax mismatch (raised
    # directly by measurement.py, outside the scheduler's own call), which
    # is why this asserts a different exception type than the recompute_tax
    # mutation test above despite both being "arguments do not match".
    with pytest.raises(SchedulerContractError, match="arguments do not match"):
        asyncio.run(
            replay_episode(cell=cell, case=case, upstream_root=UPSTREAM_ROOT, recorded=tampered)
        )


def test_replay_and_verify_end_to_end_returns_a_matching_report() -> None:
    _require_bridge()
    case, cell, original, recorded = _run_live(suffix="e2e")
    scorer = _scorer_for(case)
    dense_log = original.terminal["dense_log"]
    n_agents = original.terminal["n_agents"]
    _tax_score, tax_calls = score_tax_bracket_arithmetic_and_record(
        scorer, dense_log=dense_log, n_agents=n_agents, upstream_root=UPSTREAM_ROOT
    )

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            upstream_root=UPSTREAM_ROOT,
            scorer=scorer,
            recorded=recorded,
            tax_recompute_calls=tax_calls,
            original=original,
        )
    )

    assert report.status == "match"
    assert report.scores.budget_identity.primary.value == 1.0
    assert report.scores.tax_bracket_arithmetic.primary.value == 1.0


def test_replay_and_verify_without_an_original_reports_not_comparable_not_match() -> None:
    """Finding 4 (docs/econagent_codex_triage.md): ``replay_and_verify``'s own
    documented, supported "genuinely offline" mode (``original=None``, no live
    run held in memory to compare against) leaves ``comparison`` as ``None`` --
    there is nothing to have agreed. ``ReplayReport.status`` must not report
    that as "match"; a passing label requires an actual, performed comparison.
    """
    _require_bridge()
    case, cell, original, recorded = _run_live(suffix="no-original")
    scorer = _scorer_for(case)
    dense_log = original.terminal["dense_log"]
    n_agents = original.terminal["n_agents"]
    _tax_score, tax_calls = score_tax_bracket_arithmetic_and_record(
        scorer, dense_log=dense_log, n_agents=n_agents, upstream_root=UPSTREAM_ROOT
    )

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            upstream_root=UPSTREAM_ROOT,
            scorer=scorer,
            recorded=recorded,
            tax_recompute_calls=tax_calls,
            original=None,
        )
    )

    assert report.comparison is None
    assert report.status != "match"
    assert report.status == "not_comparable"


def test_replay_diverges_when_a_recorded_bridge_response_is_tampered_with() -> None:
    """Mutation check: `compare_episode_results` must genuinely detect
    divergence, not just agreement -- guards against it being vacuously true."""
    _require_bridge()
    case, cell, original, recorded = _run_live(suffix="tamper")

    tampered_calls = list(recorded.session_calls)
    for index, call in enumerate(tampered_calls):
        if call.method == "step_month":
            response = copy.deepcopy(call.response)
            response["actions"]["0"] = [999.0, 999.0]  # out-of-range, invented
            tampered_calls[index] = RecordedBridgeCall(
                method=call.method, args=call.args, response=response
            )
            break
    tampered = RecordedEconAgentEpisode(
        case_id=recorded.case_id, session_calls=tuple(tampered_calls)
    )

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, upstream_root=UPSTREAM_ROOT, recorded=tampered)
    )
    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is False
    with pytest.raises(ReplayError, match="differs"):
        assert_replay_matches(comparison)


def test_replay_case_mismatch_raises_a_typed_replay_error() -> None:
    _require_bridge()
    case, cell, _original, recorded = _run_live(suffix="mismatch")
    wrong_case = RecordedEconAgentEpisode(
        case_id="econagent.pilot.small10x12.seed0", session_calls=recorded.session_calls
    )

    with pytest.raises(ReplayError, match="not"):
        asyncio.run(
            replay_episode(
                cell=cell, case=case, upstream_root=UPSTREAM_ROOT, recorded=wrong_case
            )
        )


def test_replay_raises_when_the_recorded_session_has_an_unconsumed_tail() -> None:
    """A recorded call the replayed run never actually asks for must trip
    the post-episode exhaustion check -- guards against that check being
    vacuously satisfied. (Dropping the final ``close`` entry instead would
    NOT reproduce this: ``RecordedEconAgentBridge.close()`` deliberately
    tolerates a missing recorded ``close``, mirroring
    ``EconAgentBridge.close()``'s own "safe to call more than once, and
    safe to call when no episode was ever started" contract.)"""
    _require_bridge()
    case, cell, _original, recorded = _run_live(suffix="padded")
    extra_call = recorded.session_calls[1]  # a genuine "agent_snapshot" entry
    padded = RecordedEconAgentEpisode(
        case_id=recorded.case_id, session_calls=recorded.session_calls + (extra_call,)
    )

    with pytest.raises(ReplayError, match="before every recorded bridge call was consumed"):
        asyncio.run(
            replay_episode(
                cell=cell, case=case, upstream_root=UPSTREAM_ROOT, recorded=padded
            )
        )
