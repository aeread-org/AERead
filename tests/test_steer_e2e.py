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
import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from aeread.shared_runner.execution import EvidenceStore
from aeread.shared_runner.resolver import PlanCell
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import SchedulerContractError, run_episode
from aeread_families.steer import cases as steer_cases
from aeread_families.steer.environment import SteerPlugin
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

    # Sealed evidence: the harness recorded exactly one event for the one
    # submitted answer, and the seal is durable and self-verifying.
    seal = evidence.seal()
    assert seal.event_count == 1
    assert evidence.verify_seal() == seal
    events = evidence.read_events()
    assert len(events) == 1
    payload = evidence.read_event_payload(events[0])
    assert payload["element"] == element
    assert payload["response_text"] == respond_text
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

    seal = evidence.seal()
    assert seal.event_count == 1
    events = evidence.read_events()
    payload = evidence.read_event_payload(events[0])
    assert payload["response_text"] == respond_text
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

    seal = evidence.seal()
    assert seal.event_count == 1
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
