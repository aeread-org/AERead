"""Tests for the alympics.wac offline replayer (replay.py, spec section 5's
"Replay" test-plan bullet).

Follows the same skip convention as ``tests/test_alympics_wac_environment.py``
and ``tests/test_alympics_wac_harness.py``: pure, structural tests
(``RecordedDecision``/``RecordedEpisode`` round-tripping, ordering
enforcement, comparison reporting) run everywhere; tests that actually
replay a full episode against the pinned upstream checkout run for real
when it is present, and are skipped (never faked) otherwise.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

import pytest

from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.task.execution import CanonicalResponse, CellExecution, EvidenceStore
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
from aeread.shared_runner.task.evaluation import FamilyScoringInput, finalize_family_execution
from aeread.shared_runner.task.scheduler import EpisodeResult, SchedulerContractError, run_episode
from aeread_families.alympics_wac import cases as alympics_cases
from aeread_families.alympics_wac import measurement as alympics_measurement
from aeread_families.alympics_wac.cases import SEAT_ORDER
from aeread_families.alympics_wac.environment import (
    PLUGIN_ID,
    SCORER_ID,
    AlympicsWacPlugin,
    family_manifest,
    register_plugin,
)
from aeread_families.alympics_wac.harness import (
    ScriptedAlympicsWacHarness,
    baseline_policy_assignment,
)
from aeread_families.alympics_wac.replay import (
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


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_ALYMPICS_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-alympics",
    )
    root = Path(candidate)
    marker = root / "src" / "waterAllocation.py"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream Alympics checkout not found at {root}",
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()
CASES_DIR = Path("cases/alympics_wac/base")


def _case(name: str) -> CaseManifest:
    path = CASES_DIR / f"alympics.wac.{name}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_alympics_wac_replay_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_alympics_wac_replay",
        suite_version="0.1.0",
        block_id="block_alympics_wac_replay",
        sampling_plan_id="sampling_alympics_wac_replay",
        analysis_plan_id="analysis_alympics_wac_replay",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_alympics_wac_replay_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(
            {
                seat: f"scripted_{policy}"
                for seat, policy in case.payload["grid_cell"]["policy_assignment"].items()
            }
        ),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _evidence(tmp_path: Path, *, suffix: str) -> EvidenceStore:
    return EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_alympics_wac_replay_{suffix}",
        cell_id=f"cell_alympics_wac_replay_{suffix}",
        episode_id=f"episode_alympics_wac_replay_{suffix}",
        episode_attempt_id="attempt_1",
    )


def _run_live(case: CaseManifest, tmp_path: Path, *, suffix: str):
    cell = _cell(case, suffix=suffix)
    plugin = AlympicsWacPlugin(upstream_root=UPSTREAM_ROOT)
    evidence = _evidence(tmp_path, suffix=suffix)
    policy_assignment = dict(case.payload["grid_cell"]["policy_assignment"])
    harness = ScriptedAlympicsWacHarness(policy_assignment=policy_assignment, evidence=evidence)
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=harness)
    )
    evidence.seal()
    return cell, plugin, result, policy_assignment


# ---------------------------------------------------------------------------
# Evidence-complete episode driving (kernel_scoring_contract_spec.md
# milestone 3): a response source that ALSO writes the full generic evidence
# trail ``task.evaluation.replay_family_scoring_input`` needs to replay, plus
# a real, ``resolve_run_plan``-resolved ``RunPlan`` -- both required to drive
# ``task.evaluation.finalize_family_execution`` for this family for the
# first time, and reused by ``tests/test_shared_runner_scoring_contract.py``
# for its own paired-history fixtures. Mirrors govsim's identically-purposed
# ``EvidenceRecordingGovsimHarness``/``build_govsim_setup``
# (``tests/test_govsim_replay.py``).
# ---------------------------------------------------------------------------


class EvidenceRecordingAlympicsWacHarness:
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
    cost machinery, since every alympics.wac bid is a plain scripted
    integer, never a provider completion.

    ``ScriptedAlympicsWacHarness`` (this family's existing scripted response
    source, ``harness.py``) writes only its own convenience event
    (``alympics_wac_bid_served``) and has never produced evidence
    ``aeread.shared_runner.task.evaluation.replay_family_scoring_input`` can
    replay -- ``finalize_family_execution`` calls that replay internally, so
    this class is what makes driving THAT finalizer for this family possible
    at all. ``answer`` supplies the raw scripted ``{"bid": ...}`` decision
    for one request; this class owns only the evidence-recording seam
    around it, mirroring ``AttemptExecutor``'s own event shapes
    field-for-field.
    """

    def __init__(
        self, *, answer: Callable[[Any], Mapping[str, Any]], evidence: EvidenceStore
    ) -> None:
        self._answer = answer
        self._evidence = evidence

    async def __call__(self, request: Any) -> dict[str, Any]:
        response = dict(self._answer(request))
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
        # ``response`` dict returned above, unchanged -- see
        # ``ScriptedAlympicsWacHarness``'s identical contract), and replay
        # itself reconstructs ``parse``/``legality`` directly from the
        # "action_parsed"/"action_legality_checked" events below, never from
        # this response.
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
    *, rounds: int, world_seed: int = 0, suffix: str = "kernel_contract_fixture"
) -> CaseManifest:
    """A small, fast alympics.wac case for the finalizer receipt test and
    ``tests/test_shared_runner_scoring_contract.py``'s own paired-history
    fixtures.

    Unlike govsim's analogous fixture case, this family's seat roster is
    upstream-fixed (``cases.SEAT_ORDER``/``cases.PERSONAS`` -- no
    constructor parameter varies the 5-persona roster;
    ``docs/alympics_adapter_spec.md`` section 1), so this cannot shrink the
    seat count the way ``test_govsim_replay._two_agent_two_round_case``
    does -- only ``rounds`` varies. ``policy_assignment`` is a required
    field of every alympics.wac case (``cases.build_case``), but the actual
    bids for this fixture always come from
    ``EvidenceRecordingAlympicsWacHarness``'s own ``answer`` callable, never
    from ``harness.POLICY_FUNCTIONS`` -- the declared assignment here
    (all-``proportional``) is therefore an unused placeholder, not a claim
    about how the episode is actually driven. A generous constant supply
    (100, comfortably above every persona's requirement even after several
    same-round winners) means this fixture's bid schedules control winners
    purely through bid magnitude and the balance-exceeding legality gate,
    never through supply exhaustion. Never written to the on-disk corpus.
    """
    cell = {
        "case_id": f"{alympics_cases.CASE_ID_PREFIX}.{suffix}",
        "supply_regime": {"kind": "constant", "value": 100},
        "rounds": rounds,
        "supply_schedule_seed": None,
        "policy_assignment": {seat: "proportional" for seat in SEAT_ORDER},
        "note": "kernel scoring-contract fixture; never written to the checked-in corpus",
    }
    raw = alympics_cases.build_case(cell)
    raw = dict(raw)
    raw["world_seed"] = world_seed
    raw["content_sha256"] = "0" * 64
    raw["content_sha256"] = case_content_sha256(raw)
    return CaseManifest.from_dict(raw)


@dataclass(frozen=True, slots=True)
class AlympicsWacSetup:
    """A resolved, provider-free ``RunPlan`` for one alympics.wac case.

    Like govsim's own analogous setup, this family's real runtime never
    goes through ``execute_plan_cell``'s harness/provider stack at all --
    every seat is answered directly through ``run_episode``'s
    ``response_source`` (``ScriptedAlympicsWacHarness``/
    ``EvidenceRecordingAlympicsWacHarness`` above), matching this module's
    own ``_run_live``. The declared ``minimal_chat`` harness and fixture
    provider below exist purely to satisfy ``resolve_run_plan``'s
    structural pin/capability checks and are never actually invoked.
    """

    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, Any]


_ALYMPICS_FIXTURE_PROFILE_ID = "alympics_wac_unused_fixture_profile_v1"
_ALYMPICS_FIXTURE_PROVIDER_ID = "alympics_wac_unused_fixture_provider"
_ALYMPICS_FIXTURE_RUNTIME_ID = "aeread.shared_runner.task.execution"


def _pin(
    component_id: str, kind: str, source_path: Path, *, version: str = "0.1.0"
) -> ImplementationPin:
    return ImplementationPin.from_dict(
        {
            "component_id": component_id,
            "kind": kind,
            "version": version,
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        }
    )


def build_alympics_setup(case: CaseManifest, *, suffix: str) -> AlympicsWacSetup:
    """Resolve a real, one-cell ``RunPlan`` for ``case`` (spec section 5.3).

    Every seat shares one placeholder agent profile: this family's real
    runtime never invokes it (see ``AlympicsWacSetup``'s own docstring), so
    the harness/provider it names exist only to satisfy
    ``resolve_run_plan``'s structural checks.
    """
    family = family_manifest()
    seat_ids = [seat.id for seat in case.seats]
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": f"alympics_wac_{suffix}_sample_v1",
            "estimand": "fixed_alympics_wac_case",
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
            "block_id": f"alympics_wac_{suffix}_block",
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
            "analysis_plan_id": f"alympics_wac_{suffix}_analysis_v1",
            "estimands": [alympics_measurement.TERMINAL_WEALTH_ESTIMAND_ID],
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
            "suite_id": f"alympics_wac_{suffix}_suite_v1",
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
            "profile_id": _ALYMPICS_FIXTURE_PROFILE_ID,
            "model": {
                "provider": _ALYMPICS_FIXTURE_PROVIDER_ID,
                "model": "alympics_wac_unused_fixture_model_v1",
                "revision": "1.0.0",
                "base_url": None,
            },
            "harness": {
                "id": "minimal_chat",
                "version": "1.0",
                "config": {},
            },
            "prompt": {
                "prompt_id": f"alympics_wac_{suffix}_prompt_v1",
                "sha256": hashlib.sha256(
                    b"alympics.wac scripted seat: no prompt is ever sent"
                ).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": _ALYMPICS_FIXTURE_RUNTIME_ID,
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "alympics_wac_scripted_no_reasoning_v1",
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
            "run_spec_id": f"alympics_wac_{suffix}_run_spec_v1",
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

    import aeread_families.alympics_wac.environment as alympics_environment_module
    import aeread.shared_runner.task.execution as execution_module

    environment_path = Path(alympics_environment_module.__file__)
    execution_path = Path(execution_module.__file__)
    measurement_path = Path(alympics_measurement.__file__)
    pins = (
        _pin(PLUGIN_ID, "family_plugin", environment_path),
        _pin(SCORER_ID, "scorer", environment_path),
        _pin("minimal_chat", "harness", execution_path, version="1.0"),
        _pin(_ALYMPICS_FIXTURE_RUNTIME_ID, "runtime", execution_path, version="0.1.0"),
        # measurement.py declares each leaf's validity-domain predicate and
        # scorer implementation under its own distinct component id (see
        # environment.py's family_manifest() docstring on
        # scoring.reference_provider_ids); every one of those nine must
        # also be pinned here, or
        # EvaluationReceipt._validate_and_freeze_plan_pins rejects the
        # sealed receipt as missing implementations.
        _pin("alympics_wac_base_domain_predicate", "reference", environment_path),
        _pin("alympics_wac_bid_legality_gate", "reference", environment_path),
        _pin("alympics_wac_settlement_shadow_recompute", "reference", environment_path),
        _pin("alympics_wac_terminal_wealth_baseline_run", "reference", measurement_path),
        _pin("alympics_wac_survival_baseline_run", "reference", measurement_path),
        _pin("alympics_wac_terminal_wealth_scorer", "reference", measurement_path),
        _pin("alympics_wac_survival_scorer", "reference", measurement_path),
        _pin("alympics_wac_bid_legality_scorer", "reference", measurement_path),
        _pin("alympics_wac_settlement_exactness_scorer", "reference", measurement_path),
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
            _ALYMPICS_FIXTURE_PROVIDER_ID: ProviderCapabilities(
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
    return AlympicsWacSetup(plan=plan, registry=registry, prompt_sources={}, pricing={})


def _clean_episode_answer(request: Any) -> Mapping[str, Any]:
    """A legal, boring bid every round for every seat -- 1 unit, always
    affordable -- for the finalizer receipt test's "clean episode" (no
    eliminations, no illegal bids, ``status="ok"``,
    ``inclusion_status="included"``)."""
    return {"bid": 1}


# ---------------------------------------------------------------------------
# Pure, no upstream: RecordedDecision/RecordedEpisode structural round-tripping.
# ---------------------------------------------------------------------------


def test_recorded_episode_round_trips_through_plain_json() -> None:
    decision = RecordedDecision(phase_id="bid", seat_id="alex", response={"bid": 24})
    episode = RecordedEpisode(case_id="alympics.wac.reference_baseline", decisions=(decision,))

    text = episode.to_json()
    restored = RecordedEpisode.from_json(text)

    assert restored.case_id == episode.case_id
    assert len(restored.decisions) == 1
    assert restored.decisions[0].phase_id == "bid"
    assert restored.decisions[0].seat_id == "alex"
    assert restored.decisions[0].response == {"bid": 24}


def test_recorded_response_source_enforces_ordering_and_reports_exhaustion() -> None:
    decisions = (RecordedDecision(phase_id="bid", seat_id="alex", response={"bid": 24}),)
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "bid"
        seat_id = "alex"

    response = asyncio.run(source(_Request()))
    assert response == {"bid": 24}
    assert source.exhausted is True

    with pytest.raises(ReplayError, match="exhausted"):
        asyncio.run(source(_Request()))


def test_recorded_response_source_rejects_phase_seat_mismatch() -> None:
    decisions = (RecordedDecision(phase_id="bid", seat_id="bob", response={"bid": 27}),)
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "bid"
        seat_id = "alex"

    with pytest.raises(ReplayError, match="does not match"):
        asyncio.run(source(_Request()))


def test_compare_episode_results_reports_specific_mismatches_not_one_boolean() -> None:
    """A synthetic mismatch (mutated terminal) must be visible per-component."""

    class _Fake:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    original = _Fake(
        phase_instances=(),
        terminal={"reason": "rounds_exhausted", "round_id": 20},
        outcome={"termination_reason": "rounds_exhausted"},
        final_state={"players": {}, "round_log": ()},
    )
    replayed = _Fake(
        phase_instances=(),
        terminal={"reason": "all_seats_eliminated", "round_id": 4},
        outcome={"termination_reason": "rounds_exhausted"},
        final_state={"players": {}, "round_log": ()},
    )

    comparison = compare_episode_results(original, replayed)

    assert comparison.terminal_matches is False
    assert comparison.outcome_matches is True
    assert comparison.final_state_matches is True
    assert comparison.matches is False
    with pytest.raises(ReplayError, match="terminal record differs"):
        assert_replay_matches(comparison)


def test_replay_case_mismatch_raises_a_typed_replay_error_without_running_anything() -> None:
    decisions = (RecordedDecision(phase_id="bid", seat_id="alex", response={"bid": 24}),)
    wrong_case = RecordedEpisode(case_id="alympics.wac.does_not_exist", decisions=decisions)
    case = _case("reference_baseline")
    cell = _cell(case, suffix="mismatch_pure")
    plugin = AlympicsWacPlugin(upstream_root=UPSTREAM_ROOT)

    with pytest.raises(ReplayError, match="not"):
        asyncio.run(
            replay_episode(cell=cell, case=case, plugin=plugin, recorded=wrong_case)
        )


# ---------------------------------------------------------------------------
# Upstream-gated: genuine offline replay of a live, fully-scripted episode.
# ---------------------------------------------------------------------------


def test_replay_from_a_json_round_tripped_record_reproduces_the_live_run_byte_identically(
    tmp_path: Path,
) -> None:
    case = _case("reference_baseline")
    cell, original_plugin, original, _ = _run_live(case, tmp_path, suffix="live")

    recorded = record_episode(original)
    # Force a genuine round trip through plain JSON text -- proves replay
    # never depends on reusing the original run's in-memory Python objects.
    recorded = RecordedEpisode.from_json(recorded.to_json())
    assert recorded.case_id == case.case_id
    assert len(recorded.decisions) == original.logical_action_count

    # A second, independent plugin -- not the one that produced the
    # original run -- drives the replay.
    replay_plugin = AlympicsWacPlugin(upstream_root=UPSTREAM_ROOT)

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=recorded)
    )

    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is True
    # Unlike tau3_retail (whose per-message wall-clock timestamp never
    # survives two independent runs identically), this family's state
    # carries no such field: the replayed state is expected to be exactly
    # byte-identical to the original, not merely content-equivalent.
    assert comparison.final_state_matches is True
    assert comparison.state_hashes_match is True
    assert canonical_json_bytes(replayed.final_state) == canonical_json_bytes(
        original.final_state
    )
    assert replayed.terminal["reason"] == "rounds_exhausted"
    assert_replay_matches(comparison)  # never raises


def test_replay_reproduces_a_mid_game_elimination_episode_byte_identically(
    tmp_path: Path,
) -> None:
    case = _case("mixed_policies_a")
    cell, original_plugin, original, _ = _run_live(case, tmp_path, suffix="mixed_live")
    recorded = RecordedEpisode.from_json(record_episode(original).to_json())

    replay_plugin = AlympicsWacPlugin(upstream_root=UPSTREAM_ROOT)
    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=recorded)
    )

    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is True
    assert comparison.final_state_matches is True
    assert replayed.final_state["eliminated_order"] == original.final_state["eliminated_order"]


def test_replay_raises_when_recorded_decisions_run_out_early(tmp_path: Path) -> None:
    case = _case("reference_baseline")
    cell, _plugin, original, _ = _run_live(case, tmp_path, suffix="truncated")
    recorded = record_episode(original)
    truncated = RecordedEpisode(
        case_id=recorded.case_id, decisions=recorded.decisions[:-1]
    )

    replay_plugin = AlympicsWacPlugin(upstream_root=UPSTREAM_ROOT)
    # The missing decision is discovered *inside* the response_source
    # callback, mid-episode -- the scheduler itself wraps any response-
    # source exception as SchedulerContractError (scheduler.py's
    # `_request_action`), so the ReplayError this module raises surfaces
    # here as that exception's cause, not directly.
    with pytest.raises(SchedulerContractError, match="exhausted"):
        asyncio.run(
            replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=truncated)
        )


def test_replay_detects_a_tampered_bid_only_via_comparison_against_the_original(
    tmp_path: Path,
) -> None:
    """Known, honest limit (see docs/alympics_adapter_status.md): unlike
    tau3_retail's tool-level re-execution, replay_episode itself has no
    independent oracle to catch a tampered recorded bid -- it faithfully
    replays whatever the record says and settles it exactly like a live
    run would. The only place a tamper becomes visible is
    ``compare_episode_results`` against the original run."""
    case = _case("reference_baseline")
    cell, _plugin, original, _ = _run_live(case, tmp_path, suffix="tamper")
    recorded = record_episode(original)

    tampered_decisions = list(recorded.decisions)
    first = tampered_decisions[0]
    assert first.response["bid"] != 999
    tampered_decisions[0] = RecordedDecision(
        phase_id=first.phase_id, seat_id=first.seat_id, response={"bid": 999}
    )
    tampered = RecordedEpisode(case_id=recorded.case_id, decisions=tuple(tampered_decisions))

    replay_plugin = AlympicsWacPlugin(upstream_root=UPSTREAM_ROOT)
    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=replay_plugin, recorded=tampered)
    )

    # replay_episode itself never raised -- the tamper only surfaces here.
    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is False
    assert comparison.final_state_matches is False
    with pytest.raises(ReplayError, match="final state differs"):
        assert_replay_matches(comparison)


def test_replayed_episode_recomputes_all_four_leaves_using_a_replayed_baseline(
    tmp_path: Path,
) -> None:
    case = _case("mixed_policies_a")
    cell, plugin, original, policy_assignment = _run_live(
        case, tmp_path, suffix="score_actual"
    )
    recorded = record_episode(original)
    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=plugin, recorded=recorded)
    )

    focal_seat = "alex"
    baseline_assignment = baseline_policy_assignment(policy_assignment, focal_seat=focal_seat)
    baseline_evidence = _evidence(tmp_path, suffix="score_baseline")
    baseline_harness = ScriptedAlympicsWacHarness(
        policy_assignment=baseline_assignment, evidence=baseline_evidence
    )
    baseline_cell = _cell(case, suffix="score_baseline")
    baseline_original = asyncio.run(
        run_episode(
            cell=baseline_cell, case=case, plugin=plugin, response_source=baseline_harness
        )
    )
    baseline_recorded = record_episode(baseline_original)
    baseline_replayed = asyncio.run(
        replay_episode(
            cell=baseline_cell, case=case, plugin=plugin, recorded=baseline_recorded
        )
    )

    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)
    upstream_module = plugin._require_upstream()

    scores = score_replayed_episode(
        scorer=scorer,
        upstream_module=upstream_module,
        focal_seat=focal_seat,
        replayed=replayed,
        baseline_final_players=baseline_replayed.final_state["players"],
        baseline_round_log=baseline_replayed.final_state["round_log"],
    )

    assert scores.bid_legality.status == "ok"
    assert scores.settlement_exactness.status == "ok"
    assert scores.terminal_wealth.status == "ok"
    assert scores.survival.status == "ok"
    # alex ("aggressive") is the sole round-15 survivor in the actual run;
    # under baseline "proportional" (holding the rest of the panel fixed)
    # its own outcome is expected to differ -- never asserted as "better",
    # per P01's baseline_only verdict (spec section 6).
    actual_wealth = replayed.final_state["players"][focal_seat]["balance"]
    baseline_wealth = baseline_replayed.final_state["players"][focal_seat]["balance"]
    assert scores.terminal_wealth.primary.value == actual_wealth - baseline_wealth


def test_replay_and_verify_end_to_end_returns_a_matching_report(tmp_path: Path) -> None:
    case = _case("reference_baseline")
    cell, plugin, original, policy_assignment = _run_live(case, tmp_path, suffix="e2e")
    recorded = record_episode(original)

    focal_seat = "alex"
    # reference_baseline is already all-"proportional", so the baseline run
    # for its own focal seat is the identical policy assignment -- the
    # comparative delta is expected to be exactly zero.
    baseline_assignment = baseline_policy_assignment(policy_assignment, focal_seat=focal_seat)
    assert baseline_assignment == policy_assignment
    baseline_evidence = _evidence(tmp_path, suffix="e2e_baseline")
    baseline_harness = ScriptedAlympicsWacHarness(
        policy_assignment=baseline_assignment, evidence=baseline_evidence
    )
    baseline_cell = _cell(case, suffix="e2e_baseline")
    baseline_original = asyncio.run(
        run_episode(
            cell=baseline_cell, case=case, plugin=plugin, response_source=baseline_harness
        )
    )

    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)
    upstream_module = plugin._require_upstream()

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            plugin=plugin,
            scorer=scorer,
            upstream_module=upstream_module,
            focal_seat=focal_seat,
            recorded=recorded,
            baseline_final_players=baseline_original.final_state["players"],
            baseline_round_log=baseline_original.final_state["round_log"],
            original=original,
        )
    )

    assert report.status == "match"
    assert report.scores.terminal_wealth.status == "ok"
    assert report.scores.terminal_wealth.primary.value == 0.0
    assert report.scores.survival.status == "ok"
    assert report.scores.survival.primary.value == 0.0


def test_replay_and_verify_with_no_original_in_memory_never_fabricates_a_match(
    tmp_path: Path,
) -> None:
    """Codex triage finding 5: this module's own docstring names
    ``original=None`` as a real, intended mode -- "a genuinely offline
    replay from a previously-written record, with no original run in
    memory" -- but ``ReplayReport.status`` used to collapse that ``None``
    comparison (nothing was ever compared) into the exact same string,
    ``"match"``, a genuinely verified state-hash-level agreement would
    produce. This exercises exactly that documented, intended usage (never
    passing ``original``, the way a real offline-replay operator would)
    through the real production ``replay_and_verify`` function."""
    case = _case("reference_baseline")
    cell, plugin, original, policy_assignment = _run_live(case, tmp_path, suffix="no_original")
    recorded = record_episode(original)
    # Force a genuine round trip through plain JSON text, mirroring a real
    # "loaded from disk, no original run in memory" operator flow.
    recorded = RecordedEpisode.from_json(recorded.to_json())

    focal_seat = "alex"
    baseline_assignment = baseline_policy_assignment(policy_assignment, focal_seat=focal_seat)
    baseline_evidence = _evidence(tmp_path, suffix="no_original_baseline")
    baseline_harness = ScriptedAlympicsWacHarness(
        policy_assignment=baseline_assignment, evidence=baseline_evidence
    )
    baseline_cell = _cell(case, suffix="no_original_baseline")
    baseline_original = asyncio.run(
        run_episode(
            cell=baseline_cell, case=case, plugin=plugin, response_source=baseline_harness
        )
    )

    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)
    upstream_module = plugin._require_upstream()

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            plugin=plugin,
            scorer=scorer,
            upstream_module=upstream_module,
            focal_seat=focal_seat,
            recorded=recorded,
            baseline_final_players=baseline_original.final_state["players"],
            baseline_round_log=baseline_original.final_state["round_log"],
            # `original` deliberately omitted -- the documented "no original
            # run in memory" offline-replay mode.
        )
    )

    assert report.comparison is None
    assert report.status != "match"
    assert report.status == "not_compared"
    # Re-scoring the replayed episode from its own state still works --
    # only the *comparison* is unavailable, never the scoring.
    assert report.scores.terminal_wealth.status == "ok"


def test_finalize_wires_alympics_wac_to_the_shared_family_finalizer(tmp_path: Path) -> None:
    """This family has never produced an ``EvaluationReceipt``.

    Every other family already migrated to the ``FamilyScoringInput``
    contract has at least one test driving a real episode through
    ``task.evaluation.finalize_family_execution`` (see
    ``tests/test_govsim_replay.py``'s identically-purposed
    ``test_finalize_wires_govsim_to_the_shared_family_finalizer``);
    alympics.wac had none, because its existing scripted response source
    (``ScriptedAlympicsWacHarness``) writes only its own convenience event
    and has never produced evidence ``finalize_family_execution``'s
    internal ``replay_family_scoring_input`` call can replay --
    ``EvidenceRecordingAlympicsWacHarness`` (this module, above) is what
    makes this reachable.

    Drives one small, real, upstream-backed CLEAN episode (every seat bids
    a fixed, always-legal ``1`` every round; nobody is ever eliminated) end
    to end through the real finalizer and asserts a receipt comes back
    carrying EXACTLY this family's four declared finalize-time leaf ids and
    the declared primary -- not merely that a receipt came back.
    """
    case = kernel_contract_fixture_case(rounds=2, suffix="finalize_receipt")
    setup = build_alympics_setup(case, suffix="finalize_receipt")
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
    harness = EvidenceRecordingAlympicsWacHarness(
        answer=_clean_episode_answer, evidence=evidence
    )
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
        alympics_measurement.TERMINAL_WEALTH_LEAF_ID,
        alympics_measurement.SURVIVAL_LEAF_ID,
        alympics_measurement.BID_LEGALITY_LEAF_ID,
        alympics_measurement.SETTLEMENT_EXACTNESS_LEAF_ID,
    }
    assert receipt.primary_leaf_id == alympics_measurement.TERMINAL_WEALTH_LEAF_ID
    evidence_refs = {score.evidence_refs for score in receipt.scores}
    assert len(evidence_refs) == 1
    for score in receipt.scores:
        assert score.status == "ok"
