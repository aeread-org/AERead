"""End-to-end coverage for the ``steer`` adapter (docs/steer_adapter_spec.md
section 5, "e2e"): one scripted trajectory per declared element (8 total)
through the REAL kernel scheduler (``run_episode``) and the REAL
``ScriptedSteerHarness`` -- never a hand-wired shortcut around either --
asserting exactly one logical action per episode and that the sealed
``ScoreEnvelope``'s leaf/units/direction match spec section 2.

Unlike ``tests/test_steer_environment.py``/``tests/test_steer_goldens.py``
(which drive ``run_episode`` with a bare ``async def respond`` function),
every episode here is driven through ``ScriptedSteerHarness``, so each one
also records a sealed ``EvidenceStore`` event for its one submitted answer
and verifies that seal -- the milestone-3 "sealed evidence" requirement.
Eight full episodes (the parametrized element sweep below) comfortably
clears the ">= 2 full episodes through the real shared-runner path" bar.

No pandas, no bridge subprocess, no network anywhere in this module: only
the cached, flattened JSON at ``bridges/steer-data/<element>/cases.jsonl``
and the committed case files under ``cases/steer/`` milestone 1 already
wrote.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from aeread.shared_runner.execution import EvidenceStore, TokenPricing, execute_plan_cell
from aeread.shared_runner.family_evaluation import finalize_family_execution
from aeread.shared_runner.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.resolver import (
    ImplementationPin,
    PlanCell,
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
from aeread.shared_runner.scheduler import SchedulerContractError, run_episode
from aeread.shared_runner.smoke import FixedResponseProvider
from aeread_families.steer import cases as steer_cases
from aeread_families.steer.environment import SteerPlugin, family_manifest, register_plugin
from aeread_families.steer.harness import ScriptedSteerHarness


def _cache_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_STEER_DATA_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/bridges/steer-data",
    )
    root = Path(candidate)
    marker = root / "transitivity" / "cases.jsonl"
    if not marker.is_file():
        pytest.skip(
            f"flattened cache not built yet at {root}; run "
            "src/aeread_families/steer/cases.py first",
            allow_module_level=True,
        )
    return root


CACHE_ROOT = _cache_root()
CASES_DIR = Path(__file__).resolve().parents[1] / "cases" / "steer"


def _first_admitted_row(element: str) -> dict:
    path = CACHE_ROOT / element / "cases.jsonl"
    with path.open("r", encoding="utf-8") as handle:
        return json.loads(handle.readline())


def _case(element: str, question_id: str) -> CaseManifest:
    branch = steer_cases.BRANCH_BY_ELEMENT[element]
    path = CASES_DIR / branch / f"steer.{element}.{question_id}.json"
    if not path.is_file():
        pytest.skip(f"case file not built yet at {path}")
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_steer_e2e_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_steer_e2e",
        suite_version="0.1.0",
        block_id="block_steer_e2e",
        sampling_plan_id="sampling_steer_e2e",
        analysis_plan_id="analysis_steer_e2e",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_steer_e2e_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType({"agent": "scripted_agent"}),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


# ---------------------------------------------------------------------------
# One scripted trajectory per declared element, through the harness.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("element", steer_cases.DECLARED_ELEMENTS)
def test_scripted_harness_runs_one_full_episode_per_declared_element(
    element: str, tmp_path: Path
) -> None:
    row = _first_admitted_row(element)
    case = _case(element, row["question_id"])
    cell = _cell(case, suffix=element)
    plugin = SteerPlugin(steer_data_root=CACHE_ROOT)
    evidence = EvidenceStore(
        tmp_path / "evidence",
        run_plan_id=f"runplan_steer_e2e_{element}",
        cell_id=cell.cell_id,
        episode_id=f"episode_steer_e2e_{element}",
        episode_attempt_id="attempt_1",
    )
    respond_text = json.dumps({"option_id": row["correct_option_id"]})
    harness = ScriptedSteerHarness(
        evidence=evidence, script=[("answer_question", respond_text)]
    )

    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=harness)
    )

    # observe -> one action -> terminal (spec section 5's "e2e").
    assert result.logical_action_count == 1
    assert len(result.phase_instances) == 1
    assert harness.exhausted
    assert result.outcome["termination_reason"] == "answered"
    assert result.outcome["selected_option_id"] == row["correct_option_id"]

    # The sealed ScoreEnvelope's leaf/units/direction match spec section 2.
    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)
    envelope = scorer.score(result.outcome)
    assert envelope.leaf.leaf_id == "steer_answer_key"
    assert envelope.leaf.estimand.direction == "maximize"
    assert envelope.leaf.estimand.units == "pass"
    assert envelope.leaf.verifier.verifier_family == "canonical_reference"
    assert envelope.leaf.verifier.evaluation_class == "deterministic"
    assert envelope.leaf.verifier.reference.reference_kind == "canonical_point"
    assert envelope.status == "ok"
    assert envelope.primary.value == 1.0
    assert envelope.primary.unit == "pass"

    # Sealed evidence: the harness recorded one event for the submitted
    # answer plus one for the score (finding 8, docs/steer_codex_triage.md --
    # the seal is durable, self-verifying, and genuinely score-inclusive,
    # not merely "this raw text was served").
    harness.record_score(envelope)
    seal = evidence.seal()
    assert seal.event_count == 2
    assert evidence.verify_seal() == seal
    events = evidence.read_events()
    assert len(events) == 2
    payload = evidence.read_event_payload(events[0])
    assert payload["element"] == element
    assert payload["response_text"] == respond_text
    score_payload = evidence.read_event_payload(events[1])
    assert events[1].event_type == "score_recorded"
    assert score_payload["primary_leaf_id"] == envelope.leaf.leaf_id
    assert canonical_json_bytes(score_payload["score"]) == canonical_json_bytes(envelope)
    evidence.close()


# ---------------------------------------------------------------------------
# Finding 8 (docs/steer_codex_triage.md): ``ScriptedSteerHarness`` only ever
# sealed one evidence event -- "this raw text was served" -- and never a
# score, so a harness-driven run's seal never certified "this outcome was
# scored as X." ``record_score`` closes that gap, mirroring
# ``aeread.shared_runner.family_evaluation.finalize_family_execution``'s own
# score_recorded-before-seal convention exactly.
# ---------------------------------------------------------------------------


def test_scripted_harness_seals_a_score_recorded_event_before_the_evidence_seal(
    tmp_path: Path,
) -> None:
    element = "transitivity"
    row = _first_admitted_row(element)
    case = _case(element, row["question_id"])
    cell = _cell(case, suffix="score_recorded")
    plugin = SteerPlugin(steer_data_root=CACHE_ROOT)
    evidence = EvidenceStore(
        tmp_path / "evidence",
        run_plan_id="runplan_steer_e2e_score_recorded",
        cell_id=cell.cell_id,
        episode_id="episode_steer_e2e_score_recorded",
        episode_attempt_id="attempt_1",
    )
    respond_text = json.dumps({"option_id": row["correct_option_id"]})
    harness = ScriptedSteerHarness(
        evidence=evidence, script=[("answer_question", respond_text)]
    )

    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=harness)
    )

    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)
    envelope = scorer.score(result.outcome)
    assert envelope.status == "ok"

    submission_event = harness.submission_events[-1]
    score_event = harness.record_score(envelope)

    # Before the fix, ``record_score`` did not exist at all -- the harness
    # had no way to put the score into the durable evidence log. Now the
    # seal covers two events, not one, and the second is the score.
    seal = evidence.seal()
    assert seal.event_count == 2
    assert evidence.verify_seal() == seal
    events = evidence.read_events()
    assert len(events) == 2
    assert events[0].event_id == submission_event.event_id
    assert events[1].event_id == score_event.event_id
    assert events[1].event_type == "score_recorded"
    score_payload = evidence.read_event_payload(events[1])
    assert score_payload["primary_leaf_id"] == envelope.leaf.leaf_id
    assert score_payload["outcome_event_id"] == submission_event.event_id
    assert canonical_json_bytes(score_payload["score"]) == canonical_json_bytes(envelope)
    evidence.close()


# ---------------------------------------------------------------------------
# The harness also records evidence for illegal/malformed submissions --
# never silently, and never coerced into a passing shape.
# ---------------------------------------------------------------------------


def test_scripted_harness_seals_evidence_for_an_illegal_submission(tmp_path: Path) -> None:
    element = "borda_count"
    row = _first_admitted_row(element)
    case = _case(element, row["question_id"])
    cell = _cell(case, suffix="illegal")
    plugin = SteerPlugin(steer_data_root=CACHE_ROOT)
    evidence = EvidenceStore(
        tmp_path / "evidence",
        run_plan_id="runplan_steer_e2e_illegal",
        cell_id=cell.cell_id,
        episode_id="episode_steer_e2e_illegal",
        episode_attempt_id="attempt_1",
    )
    out_of_range = len(row["options"])
    respond_text = json.dumps({"option_id": out_of_range})
    harness = ScriptedSteerHarness(
        evidence=evidence, script=[("answer_question", respond_text)]
    )

    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=harness)
    )

    assert result.outcome["termination_reason"] == "error"
    assert result.outcome["failure_code"] == "option_id_out_of_range"
    assert result.outcome["selected_option_id"] is None

    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)
    envelope = scorer.score(result.outcome)
    assert envelope.status == "invalid_measurement"
    assert envelope.primary is None

    # Even an invalid_measurement score is sealed alongside the submission --
    # never silently dropped from the evidence bundle (finding 8).
    harness.record_score(envelope)
    seal = evidence.seal()
    assert seal.event_count == 2
    events = evidence.read_events()
    payload = evidence.read_event_payload(events[0])
    assert payload["response_text"] == respond_text
    score_payload = evidence.read_event_payload(events[1])
    assert events[1].event_type == "score_recorded"
    assert canonical_json_bytes(score_payload["score"]) == canonical_json_bytes(envelope)
    evidence.close()


def test_scripted_harness_seals_evidence_for_a_malformed_submission(tmp_path: Path) -> None:
    element = "ir_mechanism"
    row = _first_admitted_row(element)
    case = _case(element, row["question_id"])
    cell = _cell(case, suffix="malformed")
    plugin = SteerPlugin(steer_data_root=CACHE_ROOT)
    evidence = EvidenceStore(
        tmp_path / "evidence",
        run_plan_id="runplan_steer_e2e_malformed",
        cell_id=cell.cell_id,
        episode_id="episode_steer_e2e_malformed",
        episode_attempt_id="attempt_1",
    )
    respond_text = "I believe the answer is the second option."
    harness = ScriptedSteerHarness(
        evidence=evidence, script=[("answer_question", respond_text)]
    )

    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=harness)
    )

    assert result.outcome["termination_reason"] == "error"
    assert result.outcome["failure_code"] == "malformed_answer_json"

    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)
    envelope = scorer.score(result.outcome)
    assert envelope.status == "invalid_measurement"

    harness.record_score(envelope)
    seal = evidence.seal()
    assert seal.event_count == 2
    evidence.close()


# ---------------------------------------------------------------------------
# Harness-level contract checks (script/order enforcement).
# ---------------------------------------------------------------------------


def test_scripted_harness_rejects_a_phase_id_the_script_does_not_expect(
    tmp_path: Path,
) -> None:
    element = "transitivity"
    row = _first_admitted_row(element)
    case = _case(element, row["question_id"])
    cell = _cell(case, suffix="phase_mismatch")
    plugin = SteerPlugin(steer_data_root=CACHE_ROOT)
    evidence = EvidenceStore(
        tmp_path / "evidence",
        run_plan_id="runplan_steer_e2e_phase_mismatch",
        cell_id=cell.cell_id,
        episode_id="episode_steer_e2e_phase_mismatch",
        episode_attempt_id="attempt_1",
    )
    harness = ScriptedSteerHarness(
        evidence=evidence,
        script=[("some_other_phase", json.dumps({"option_id": 0}))],
    )

    with pytest.raises(SchedulerContractError, match="script expected phase"):
        asyncio.run(
            run_episode(cell=cell, case=case, plugin=plugin, response_source=harness)
        )
    evidence.close()


def test_scripted_harness_raises_once_the_script_is_exhausted(tmp_path: Path) -> None:
    element = "transitivity"
    row = _first_admitted_row(element)
    case = _case(element, row["question_id"])
    cell = _cell(case, suffix="exhausted")
    evidence = EvidenceStore(
        tmp_path / "evidence",
        run_plan_id="runplan_steer_e2e_exhausted",
        cell_id=cell.cell_id,
        episode_id="episode_steer_e2e_exhausted",
        episode_attempt_id="attempt_1",
    )
    harness = ScriptedSteerHarness(evidence=evidence, script=[])

    with pytest.raises(RuntimeError, match="script exhausted"):
        asyncio.run(harness(type("Request", (), {"phase_id": "answer_question"})()))
    evidence.close()


# ---------------------------------------------------------------------------
# Finding 1 (docs/steer_codex_triage.md): the one real production
# finalization path, `finalize_family_execution`, calls whatever
# `plugin.build_scorer(family_case)` returns AS A CALLABLE -- e.g.
# `family_evaluation.py:245-248`'s
# `plugin.build_scorer(family_case)(recorded_outcome, evidence_refs=...)` --
# never `.score(...)`. Every other test in this suite only ever calls
# `.score(...)` directly, so none of them exercise the shape production
# finalization actually needs. This test drives the real path end to end --
# `resolve_run_plan` -> `execute_plan_cell` -> `finalize_family_execution`,
# never a hand-wired shortcut around any of the three.
# ---------------------------------------------------------------------------

STEER_FINALIZE_PROMPT = (
    "Return only one JSON object with one integer field named option_id."
)


def _steer_finalize_setup(case: CaseManifest) -> SimpleNamespace:
    """Build one real, sealed ``RunPlan`` for a single steer case.

    Mirrors ``aeread.shared_runner.smoke.build_single_offer_smoke``'s R1-R2
    construction, but for the real ``steer`` family/plugin rather than the
    smoke fixture -- so the plan this returns can drive the exact same
    ``execute_plan_cell`` / ``finalize_family_execution`` production entry
    points any other family does.
    """
    family = family_manifest()
    registry = PluginRegistry()
    register_plugin(registry, plugin=SteerPlugin(steer_data_root=CACHE_ROOT))

    sampling = SamplingPlan.from_dict(
        {
            "spec_version": "aeread.sampling/0.1",
            "sampling_plan_id": "sampling_steer_finalize_v1",
            "estimand": "steer_answer_key",
            "target": "steer_finalize_fixture",
            "selection": "fixed_curated",
            "seeds": [1],
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
            "block_id": "block_steer_finalize",
            "kind": "self_play",
            "subject_seats": ["agent"],
            "controlled_profiles": {},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": "aeread.analysis/0.1",
            "analysis_plan_id": "analysis_steer_finalize_v1",
            "estimands": ["steer_answer_key"],
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
            "suite_id": "suite_steer_finalize_v1",
            "version": "0.1.0",
            "family_ids": [steer_cases.FAMILY_ID],
            "case_ids": [case.case_id],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    pricing = TokenPricing(0.0, 0.0, 0.0, "steer_finalize_fixed_response_zero_cost_v1")
    profile = AgentProfile.from_dict(
        {
            "spec_version": "aeread.agent_profile/0.1",
            "profile_id": "steer_finalize_agent_v1",
            "model": {
                "provider": "fake",
                "model": "fake-model",
                "revision": "fixed-v1",
                "base_url": None,
            },
            "harness": {
                "id": "minimal_chat",
                "version": "1.0",
                "config": {
                    "pricing_id": pricing.pricing_id,
                    "pricing_sha256": pricing.content_sha256(),
                },
            },
            "prompt": {
                "prompt_id": "steer_finalize_prompt_v1",
                "sha256": hashlib.sha256(STEER_FINALIZE_PROMPT.encode()).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": "aeread.shared_runner.execution",
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "reasoning_low_v1",
                "effort": "low",
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": 80,
                "seed": None,
                "top_p": None,
            },
            "budgets": {
                "max_logical_actions": 1,
                "timeout_seconds": 30.0,
                "max_cost_usd": 0.001,
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
            "spec_version": "aeread.run_spec/0.1",
            "run_spec_id": "run_spec_steer_finalize_v1",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id],
            "seat_assignments": {"agent": profile.profile_id},
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    repo_root = Path(__file__).resolve().parents[1]
    steer_src = repo_root / "src" / "aeread_families" / "steer"
    environment_bytes = (steer_src / "environment.py").read_bytes()
    measurement_bytes = (steer_src / "measurement.py").read_bytes()
    environment_sha256 = hashlib.sha256(environment_bytes).hexdigest()
    # Mirrors `measurement._predicate_and_scorer_sha256` exactly: the
    # predicate and the scorer share one pinned id/digest (both named by
    # `family.scoring.scorer_id`), so this single "scorer" pin also satisfies
    # the leaf's `estimand.validity_domain.predicate` ImplementationRef --
    # never an unreferenced pin `resolve_run_plan` would reject.
    predicate_and_scorer_sha256 = hashlib.sha256(
        environment_bytes + measurement_bytes
    ).hexdigest()
    oracle_sha256 = hashlib.sha256(
        (steer_src / "steer_bridge_driver.py").read_bytes()
    ).hexdigest()
    execution_sha256 = hashlib.sha256(
        (repo_root / "src" / "aeread" / "shared_runner" / "execution.py").read_bytes()
    ).hexdigest()
    pins = (
        ImplementationPin.from_dict(
            {
                "component_id": family.family.plugin_id,
                "kind": "family_plugin",
                "version": family.family.version,
                "sha256": environment_sha256,
            }
        ),
        ImplementationPin.from_dict(
            {
                "component_id": family.scoring.scorer_id,
                "kind": "scorer",
                "version": family.family.version,
                "sha256": predicate_and_scorer_sha256,
            }
        ),
        ImplementationPin.from_dict(
            {
                "component_id": family.scoring.oracle_id,
                "kind": "reference",
                "version": family.family.version,
                "sha256": oracle_sha256,
            }
        ),
        ImplementationPin.from_dict(
            {
                "component_id": profile.harness.id,
                "kind": "harness",
                "version": profile.harness.version,
                "sha256": execution_sha256,
            }
        ),
        ImplementationPin.from_dict(
            {
                "component_id": profile.runtime.implementation,
                "kind": "runtime",
                "version": profile.runtime.version,
                "sha256": execution_sha256,
            }
        ),
    )
    harness_registry = HarnessRegistry()
    for harness in default_harnesses().values():
        harness_registry.register(harness)
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
            "fake": ProviderCapabilities(
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
    return SimpleNamespace(
        plan=plan,
        registry=registry,
        prompt_sources={"steer_finalize_prompt_v1": STEER_FINALIZE_PROMPT},
        pricing={"fake-model": pricing},
    )


def test_finalize_family_execution_scores_a_real_steer_episode_through_the_production_path(
    tmp_path: Path,
) -> None:
    """Drive the REAL production path -- ``resolve_run_plan`` ->
    ``execute_plan_cell`` -> ``finalize_family_execution`` -- for one steer
    case with a correct submitted answer.

    Before ``SteerScorer`` gained ``__call__``, this failed with
    ``TypeError: 'SteerScorer' object is not callable`` inside
    ``finalize_family_execution``'s own
    ``plugin.build_scorer(family_case)(recorded_outcome,
    evidence_refs=(outcome_event.event_id,))`` -- exactly the call every
    other steer test's `.score(...)`-only coverage never exercised.
    """
    element = "transitivity"
    row = _first_admitted_row(element)
    case = _case(element, row["question_id"])
    setup = _steer_finalize_setup(case)
    provider = FixedResponseProvider(json.dumps({"option_id": row["correct_option_id"]}))

    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path / "runs",
            prompt_sources=setup.prompt_sources,
            providers={"fake": provider},
            pricing=setup.pricing,
        )
    )

    receipt = finalize_family_execution(setup=setup, execution=execution)

    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"
    assert len(receipt.scores) == 1
    score = receipt.scores[0]
    assert score.leaf.leaf_id == "steer_answer_key"
    assert score.primary is not None
    assert score.primary.value == 1.0
    assert score.primary.unit == "pass"
