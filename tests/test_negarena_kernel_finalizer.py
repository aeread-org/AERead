"""Negarena driven through the shared kernel's own finalizer, for real.

Every existing negarena integration test (``tests/test_negarena_harness.py``)
drives an episode through the real scheduler (``run_episode``) but then
scores it by calling ``NegarenaScorer.score_seat_outcome``/
``score_agreement_reached`` directly, and seals evidence containing only
``negarena_decision_served`` events -- a hand-wired shortcut around the
generic kernel path every other production family (Housing) actually uses
(``aeread.shared_runner.family_evaluation.finalize_family_execution``,
reached via ``execute_plan_cell``). ``docs/negarena_codex_triage.md``
Findings 1 and 3 are both about that shortcut: the production scorer
(``plugin.build_scorer(family_case)``, called as ``scorer(outcome,
evidence_refs=...)``) was not callable at all, and the harness-produced
evidence has no phase/transition/terminal/outcome/score boundaries for the
shared replay path to read back.

This module builds a genuine, fully-resolved negarena ``RunPlan`` (the same
``resolve_run_plan`` R1/R2 machinery ``aeread.shared_runner.smoke``/
``aeread.shared_runner.housing`` use), drives one episode through
``run_episode`` with ``ScriptedNegarenaHarness`` exactly as
``test_negarena_harness.py`` already does, then -- unlike that module --
seals the *complete* generic evidence lifecycle
(``harness.record_full_evidence_lifecycle``) and calls
``finalize_family_execution`` itself: the actual production call site named
by both findings, not a stand-in for it.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import pytest

from aeread.shared_runner.execution import CellExecution, EvidenceStore
from aeread.shared_runner.family_evaluation import finalize_family_execution
from aeread.shared_runner.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.resolver import (
    ImplementationPin,
    RunPlan,
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
from aeread_families.negarena import measurement, parity
from aeread_families.negarena.cases import BLUE, RED
from aeread_families.negarena.environment import (
    BLUE_PHASE,
    RED_PHASE,
    PLUGIN_ID,
    SCORER_ID,
    NegarenaPlugin,
    family_manifest,
    register_plugin,
)
from aeread_families.negarena.harness import run_scripted_negarena_episode
from aeread_families.negarena.negarena_bridge import NegarenaBridge

REPO_ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_ROOT = Path(
    os.environ.get(
        "AEREAD_NEGARENA_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-negarena",
    )
)

if not (UPSTREAM_ROOT / "negotiationarena").is_dir():
    pytest.skip(
        f"pinned upstream NegotiationArena checkout not found at {UPSTREAM_ROOT}",
        allow_module_level=True,
    )


def _bridge():
    from aeread_families.negarena.negarena_bridge import NegarenaBridgeUnavailableError

    try:
        return NegarenaBridge.discover(UPSTREAM_ROOT)
    except NegarenaBridgeUnavailableError as error:
        pytest.skip(f"upstream NegotiationArena Python interpreter unavailable: {error}")


@pytest.fixture(scope="module")
def bridge():
    return _bridge()


def _load_case(case_id: str, split: str) -> CaseManifest:
    path = REPO_ROOT / "cases" / "negarena" / split / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _script_from_transcript(
    transcript: parity.GoldenOneTranscript,
) -> list[tuple[str, str, dict[str, str]]]:
    return [
        (RED_PHASE if seat_id == RED else BLUE_PHASE, seat_id, {"response": text})
        for seat_id, text in transcript.turns
    ]


@dataclass(frozen=True, slots=True)
class _EvaluationSetup:
    """Minimal ``EvaluationSetup`` (family_evaluation.py) implementation.

    ``prompt_sources``/``pricing`` are never read by
    ``finalize_family_execution`` itself (only by ``execute_plan_cell``'s
    provider-calling path, which this module deliberately bypasses -- the
    episode is driven by ``ScriptedNegarenaHarness`` exactly like
    ``test_negarena_harness.py``), so both are left empty here.
    """

    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, Any]


def _build_negarena_run_plan(*, plugin: NegarenaPlugin, case: CaseManifest) -> tuple[RunPlan, PluginRegistry]:
    """One fully-resolved, sealed negarena ``RunPlan`` for a single case.

    Both seats share one scripted profile (self-play): nothing in this
    module ever calls a ``ProviderClient`` (the episode is driven directly
    through ``run_episode`` + ``ScriptedNegarenaHarness``), so the profile
    only needs to be schema-valid and admitted, never actually invoked.
    """
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)

    profile = AgentProfile.from_dict(
        {
            "spec_version": "aeread.agent_profile/0.1",
            "profile_id": "negarena_scripted_v1",
            "model": {
                "provider": "negarena_scripted",
                "model": "negarena-scripted-v1",
                "revision": "1.0.0",
                "base_url": None,
            },
            "harness": {"id": "minimal_chat", "version": "1.0", "config": {}},
            "prompt": {
                "prompt_id": "negarena_scripted_prompt_v1",
                "sha256": hashlib.sha256(b"negarena scripted seat").hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": "aeread.shared_runner.execution",
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "reasoning_none_v1",
                "effort": None,
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": 512,
                "seed": None,
                "top_p": None,
            },
            "budgets": {
                "max_logical_actions": 20,
                "timeout_seconds": 30.0,
                "max_cost_usd": None,
            },
            "retry_policy": {
                "max_action_attempts": 1,
                "retryable_conditions": [],
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )

    sampling = SamplingPlan.from_dict(
        {
            "spec_version": "aeread.sampling/0.1",
            "sampling_plan_id": "negarena_kernel_finalizer_sample_v1",
            "estimand": "fixed_smoke_case",
            "target": "negarena_kernel_finalizer_fixture",
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
            "spec_version": "aeread.evaluation_block/0.1",
            "block_id": "negarena_kernel_finalizer_block",
            "kind": "self_play",
            "subject_seats": [RED, BLUE],
            "controlled_profiles": {},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": "aeread.analysis/0.1",
            "analysis_plan_id": "negarena_kernel_finalizer_analysis_v1",
            "estimands": [measurement.SEAT_OUTCOME_ESTIMAND_ID],
            "group_by": ["family_id"],
            "missingness": "report_separately",
            "resampling_unit": "cluster_id",
            "uncertainty": "none",
            "multiplicity": "none",
            "sensitivity": [],
            "cross_family_scalar": "disabled",
        }
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": "aeread.suite/0.1",
            "suite_id": "negarena_kernel_finalizer_suite_v1",
            "version": "1.0.0",
            "family_ids": [case.family_id],
            "case_ids": [case.case_id],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    run_spec = RunSpec.from_dict(
        {
            "spec_version": "aeread.run_spec/0.1",
            "run_spec_id": "negarena_kernel_finalizer_run_v1",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id],
            "seat_assignments": {RED: profile.profile_id, BLUE: profile.profile_id},
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )

    harness_registry = HarnessRegistry()
    for harness in default_harnesses().values():
        harness_registry.register(harness)

    environment_sha256 = hashlib.sha256(
        Path(__file__).parents[1].joinpath(
            "src", "aeread_families", "negarena", "environment.py"
        ).read_bytes()
    ).hexdigest()
    execution_sha256 = hashlib.sha256(
        Path(__file__).parents[1].joinpath(
            "src", "aeread", "shared_runner", "execution.py"
        ).read_bytes()
    ).hexdigest()
    # Every implementation id either declared measurement leaf actually
    # references (validity-domain predicate, reference implementation,
    # scorer -- for both leaves), read straight off the leaves themselves so
    # this can never drift from ``family_manifest``'s own
    # ``_measurement_reference_provider_ids()``. Required for
    # ``EvaluationReceipt``'s own pin/implementation cross-check to pass at
    # all (docs/negarena_codex_triage.md Finding 1).
    seat_leaf = measurement.build_seat_outcome_leaf()
    agreement_leaf = measurement.build_agreement_reached_leaf()
    reference_refs = {
        seat_leaf.estimand.validity_domain.predicate,
        seat_leaf.verifier.reference.implementation,
        seat_leaf.scorer,
        agreement_leaf.verifier.reference.implementation,
        agreement_leaf.scorer,
    }
    reference_pins = tuple(
        ImplementationPin.from_dict(
            {
                "component_id": ref.implementation_id,
                "kind": "reference",
                "version": ref.version,
                "sha256": ref.content_sha256,
            }
        )
        for ref in reference_refs
    )
    pins = (
        ImplementationPin.from_dict(
            {
                "component_id": PLUGIN_ID,
                "kind": "family_plugin",
                "version": "0.1.0",
                "sha256": environment_sha256,
            }
        ),
        ImplementationPin.from_dict(
            {
                "component_id": SCORER_ID,
                "kind": "scorer",
                "version": "0.1.0",
                "sha256": environment_sha256,
            }
        ),
        *reference_pins,
        ImplementationPin.from_dict(
            {
                "component_id": "minimal_chat",
                "kind": "harness",
                "version": "1.0",
                "sha256": execution_sha256,
            }
        ),
        ImplementationPin.from_dict(
            {
                "component_id": "aeread.shared_runner.execution",
                "kind": "runtime",
                "version": "0.1.0",
                "sha256": execution_sha256,
            }
        ),
    )

    plan = resolve_run_plan(
        families=(family_manifest(),),
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
            "negarena_scripted": ProviderCapabilities(
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
    return plan, registry


def _run_negarena_episode_through_finalizer(bridge, tmp_path: Path):
    """Drive one buy_sell golden-1 episode all the way to a sealed receipt.

    Uses ``run_scripted_negarena_episode`` -- this adapter's one production
    entry point for a scripted episode -- rather than hand-wiring
    ``run_episode``/``record_full_evidence_lifecycle`` here: that function
    seals the complete evidence lifecycle internally, so this helper (the
    only place in the repository that reaches ``finalize_family_execution``)
    can no longer forget the step (docs/negarena_codex_triage.md Finding 3).

    Returns ``(receipt, evidence, family_case)``.
    """
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    plugin = NegarenaPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    family_case = plugin.validate_payload(case.payload)
    transcript = parity.build_buy_sell_golden_one(family_case)

    plan, registry = _build_negarena_run_plan(plugin=plugin, case=case)
    cell = plan.cells[0]
    resolved_plugin = registry.resolve_manifest(family_manifest())

    evidence = EvidenceStore(
        tmp_path / "evidence",
        run_plan_id=plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_id=f"episode_{cell.cell_id}",
        episode_attempt_id="attempt_1",
    )
    result = asyncio.run(
        run_scripted_negarena_episode(
            cell=cell,
            case=case,
            plugin=resolved_plugin,
            evidence=evidence,
            script=_script_from_transcript(transcript),
        )
    )
    evidence.audit_reconciliation()

    execution = CellExecution(
        run_plan_id=plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_attempt_id="attempt_1",
        episode_result=result,
        evidence=evidence,
        action_executions=(),
        total_cost_usd=0.0,
    )
    setup = _EvaluationSetup(
        plan=plan, registry=registry, prompt_sources={}, pricing={}
    )
    receipt = finalize_family_execution(setup=setup, execution=execution)
    return receipt, evidence, family_case


def test_finalize_family_execution_does_not_crash_and_seals_a_typed_receipt(
    tmp_path: Path, bridge
) -> None:
    """Finding 1: the production scorer must be callable.

    Before ``NegarenaScorer.__call__`` existed, this call raised
    ``TypeError: 'NegarenaScorer' object is not callable`` at
    ``family_evaluation.py``'s ``finalize_family_execution`` before any
    score was recorded, before evidence was sealed, and before a receipt
    was written. It must now reach a well-formed, sealed, typed receipt
    instead.
    """
    receipt, evidence, _family_case = _run_negarena_episode_through_finalizer(
        bridge, tmp_path
    )

    assert receipt.status == "invalid_measurement"
    assert receipt.inclusion_status == "excluded"
    assert receipt.replay_level == "state_and_score"
    assert receipt.primary_leaf_id == measurement.SEAT_OUTCOME_LEAF_ID
    assert len(receipt.scores) == 1
    assert receipt.scores[0].status == "invalid_measurement"
    assert receipt.scores[0].leaf.leaf_id == measurement.SEAT_OUTCOME_LEAF_ID
    assert receipt.scores[0].primary is None
    assert receipt.failure is not None
    assert receipt.failure.condition == "invalid_family_measurement"
    assert "seat_pairing_context" in receipt.failure.message

    # Evidence really was sealed with a durable receipt on disk -- the
    # concrete failure this finding named ("before score_recorded, evidence
    # sealing, or receipt creation") did not happen.
    assert evidence.verify_seal() == receipt.evidence
    receipt_path = evidence.root / "evaluation_receipt.json"
    assert receipt_path.is_file()
    assert receipt_path.read_bytes() == canonical_json_bytes(receipt) + b"\n"


def test_finalize_family_execution_seals_the_complete_evidence_lifecycle(
    tmp_path: Path, bridge
) -> None:
    """Finding 3: the sealed log must contain more than served responses.

    Before ``record_full_evidence_lifecycle`` existed, the only durable
    events a negarena episode ever produced were ``negarena_decision_served``
    -- no phase boundary, no transition, no terminal record, no outcome, and
    (because of Finding 1) no score. An auditor reading only event types must
    now see a genuine, replayable lifecycle, ending in ``score_recorded``.
    """
    receipt, evidence, _family_case = _run_negarena_episode_through_finalizer(
        bridge, tmp_path
    )
    del receipt

    event_types = {event.event_type for event in evidence.read_events()}
    for required in (
        "negarena_decision_served",
        "phase_instance_started",
        "logical_action_started",
        "action_parsed",
        "action_legality_checked",
        "logical_action_succeeded",
        "transition_applied",
        "episode_terminated",
        "family_outcome_recorded",
        "score_recorded",
    ):
        assert required in event_types, f"missing evidence event type: {required}"

    # Every logical action reconciles (started <-> succeeded), exactly what
    # audit_reconciliation already re-verifies inside finalize_family_execution
    # itself -- asserted again here directly against the raw log.
    evidence.audit_reconciliation()


def test_run_scripted_negarena_episode_seals_the_complete_lifecycle_automatically(
    tmp_path: Path, bridge
) -> None:
    """Finding 3, closed for real (docs/negarena_fix_verification.md):
    ``record_full_evidence_lifecycle`` used to be invoked only by hand, by
    this very test module's own helper -- nothing in production code called
    it, so a real caller could forget the extra step and reach
    ``finalize_family_execution`` with an incomplete evidence log.
    ``run_scripted_negarena_episode`` is now the one production entry point
    this adapter ships for driving a scripted episode; this test makes no
    manual ``record_full_evidence_lifecycle`` call at all, and the complete
    lifecycle must still be sealed, because the function seals it internally
    rather than leaving it to the caller.
    """
    case = _load_case("negarena.buy_sell.0", "buy_sell")
    plugin = NegarenaPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    family_case = plugin.validate_payload(case.payload)
    transcript = parity.build_buy_sell_golden_one(family_case)

    plan, registry = _build_negarena_run_plan(plugin=plugin, case=case)
    cell = plan.cells[0]
    resolved_plugin = registry.resolve_manifest(family_manifest())

    evidence = EvidenceStore(
        tmp_path / "evidence",
        run_plan_id=plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_id=f"episode_{cell.cell_id}",
        episode_attempt_id="attempt_1",
    )

    result = asyncio.run(
        run_scripted_negarena_episode(
            cell=cell,
            case=case,
            plugin=resolved_plugin,
            evidence=evidence,
            script=_script_from_transcript(transcript),
        )
    )
    assert result.terminal["reason"] == "accepted"

    event_types = {event.event_type for event in evidence.read_events()}
    for required in (
        "negarena_decision_served",
        "phase_instance_started",
        "logical_action_started",
        "action_parsed",
        "action_legality_checked",
        "logical_action_succeeded",
        "transition_applied",
        "episode_terminated",
        "family_outcome_recorded",
    ):
        assert required in event_types, f"missing evidence event type: {required}"
    evidence.audit_reconciliation()
