"""Five QC Gate-2 goldens for the ``steer`` adapter (docs/steer_adapter_spec.md
section 4).

Goldens 1-4 each run one scripted trajectory through the REAL kernel
scheduler (``run_episode``), then score the resulting terminal outcome
through the REAL ``environment.py``/``measurement.py`` scorer wiring --
never a hand-rolled shortcut around either. Golden 5 is a corpus-admission
regression test, not a live scoring run (see its own docstring). No
pandas, no bridge subprocess, no network anywhere in this module: only the
cached, flattened JSON at ``bridges/steer-data/<element>/cases.jsonl`` and
the committed case files under ``cases/steer/`` that milestone 1 already
wrote.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from aeread.shared_runner.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import run_episode
from aeread_families.steer import cases as steer_cases
from aeread_families.steer.environment import SteerPlugin


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


def _case_path(element: str, question_id: str) -> Path:
    branch = steer_cases.BRANCH_BY_ELEMENT[element]
    return CASES_DIR / branch / f"steer.{element}.{question_id}.json"


def _case(element: str, question_id: str) -> CaseManifest:
    path = _case_path(element, question_id)
    if not path.is_file():
        pytest.skip(f"case file not built yet at {path}")
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_steer_golden_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_steer_golden",
        suite_version="0.1.0",
        block_id="block_steer_golden",
        sampling_plan_id="sampling_steer_golden",
        analysis_plan_id="analysis_steer_golden",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_steer_golden_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType({"agent": "scripted_agent"}),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _run_golden(case: CaseManifest, *, suffix: str, respond_text: str):
    """Run one scripted episode end to end and score its terminal outcome
    through the real plugin/measurement wiring -- returns (outcome, envelope)."""
    plugin = SteerPlugin(steer_data_root=CACHE_ROOT)
    cell = _cell(case, suffix=suffix)

    async def respond(request):
        del request
        return respond_text

    result = asyncio.run(run_episode(cell=cell, case=case, plugin=plugin, response_source=respond))

    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)
    envelope = scorer.score(result.outcome)
    return result, envelope


# ---------------------------------------------------------------------------
# Golden 1 -- successful.
# ---------------------------------------------------------------------------


def test_golden_1_successful_selects_gold_option_and_scores_1_0() -> None:
    element = "transitivity"
    row = _first_admitted_row(element)
    case = _case(element, row["question_id"])

    result, envelope = _run_golden(
        case,
        suffix="golden1",
        respond_text=json.dumps({"option_id": row["correct_option_id"]}),
    )

    assert result.outcome["termination_reason"] == "answered"
    assert result.outcome["selected_option_id"] == row["correct_option_id"]
    assert result.outcome["failure_code"] is None
    assert envelope.status == "ok"
    assert envelope.validity.status == "valid"
    assert envelope.primary.value == 1.0


# ---------------------------------------------------------------------------
# Golden 2 -- valid-but-poor.
# ---------------------------------------------------------------------------


def test_golden_2_valid_but_poor_selects_a_legal_wrong_option_and_scores_0_0() -> None:
    element = "plurality_voting"
    row = _first_admitted_row(element)
    wrong_option_id = (row["correct_option_id"] + 1) % len(row["options"])
    assert wrong_option_id != row["correct_option_id"]
    case = _case(element, row["question_id"])

    result, envelope = _run_golden(
        case,
        suffix="golden2",
        respond_text=json.dumps({"option_id": wrong_option_id}),
    )

    assert result.outcome["termination_reason"] == "answered"
    assert result.outcome["selected_option_id"] == wrong_option_id
    assert result.outcome["failure_code"] is None
    # A wrong answer, distinguished from an illegal one: still "ok"/"valid",
    # just scored 0.0.
    assert envelope.status == "ok"
    assert envelope.validity.status == "valid"
    assert envelope.primary.value == 0.0


# ---------------------------------------------------------------------------
# Golden 3 -- invalid-unauthorized.
# ---------------------------------------------------------------------------


def test_golden_3_invalid_unauthorized_earns_no_credit_and_changes_no_state() -> None:
    """An option_id absent from this question's own option set (index >=
    options_count). Must be rejected as illegal before scoring, never
    coerced to option 0 or silently recorded as a legitimate wrong answer:
    no protected state (the episode's own selected_option_id) is ever set,
    and the scorer awards no credit at all -- not even the "valid but
    wrong" 0.0 golden 2 earns.

    This also checks the claim against the FULL ``final_state``, not just
    the narrow ``outcome()`` projection (a review suggestion: ``outcome()``
    structurally cannot see whether ``question_text``/``options`` were
    mutated by the illegal-action path, only ``selected_option_id``)."""
    element = "borda_count"
    row = _first_admitted_row(element)
    out_of_range_option_id = len(row["options"])
    case = _case(element, row["question_id"])

    result, envelope = _run_golden(
        case,
        suffix="golden3",
        respond_text=json.dumps({"option_id": out_of_range_option_id}),
    )

    assert result.outcome["termination_reason"] == "error"
    assert result.outcome["failure_code"] == "option_id_out_of_range"
    # No protected state changed: no option was ever recorded as selected.
    assert result.outcome["selected_option_id"] is None
    # The full final_state, not just outcome()'s narrower projection:
    # question_text and options are exactly what was cached, untouched by
    # the illegal-action path.
    assert canonical_json_bytes(result.final_state["question_text"]) == canonical_json_bytes(
        row["question_text"]
    )
    assert canonical_json_bytes(result.final_state["options"]) == canonical_json_bytes(
        row["options"]
    )
    # No credit earned: never scored, not even at 0.0 -- a typed invalidity.
    assert envelope.status == "invalid_measurement"
    assert envelope.primary is None
    assert envelope.validity.status == "invalid"
    assert envelope.validity.reasons == ("option_id_out_of_range",)


# ---------------------------------------------------------------------------
# Golden 4 -- malformed-operational.
# ---------------------------------------------------------------------------


def test_golden_4_malformed_operational_is_typed_invalidity_never_a_task_quality_zero() -> None:
    """Free-text prose instead of a parseable option identifier (mirrors
    provider truncation/non-compliance). Must surface as
    invalid_measurement, never as an economic zero indistinguishable from
    golden 2's legitimate wrong answer."""
    element = "ir_mechanism"
    row = _first_admitted_row(element)
    case = _case(element, row["question_id"])

    result, envelope = _run_golden(
        case,
        suffix="golden4",
        respond_text="I believe the correct answer is the second option.",
    )

    assert result.outcome["termination_reason"] == "error"
    assert result.outcome["failure_code"] == "malformed_answer_json"
    assert result.outcome["selected_option_id"] is None
    assert envelope.status == "invalid_measurement"
    assert envelope.primary is None
    assert envelope.validity.reasons == ("malformed_answer_json",)
    # The critical distinction from golden 2: this must never collapse into
    # the same "ok" shape a legitimate wrong answer produces.
    assert envelope.status != "ok"


# ---------------------------------------------------------------------------
# Golden 5 -- degenerate-reference (a corpus-admission regression test, not
# a live scoring run: the whole point is that this question_id never
# reaches the scorer at all).
# ---------------------------------------------------------------------------


def _dsic_zero_correct_sample_question_id() -> str:
    pins_path = CASES_DIR / "pins.json"
    if not pins_path.is_file():
        pytest.skip(f"pins.json not built yet at {pins_path}")
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    sample = pins["zero_correct_sample_by_element"]["dsic_mechanism"]
    if sample is None:
        pytest.skip("dsic_mechanism has no recorded zero-correct sample in pins.json")
    return sample


def test_golden_5_degenerate_reference_question_id_is_a_real_zero_correct_row() -> None:
    """The fixture itself is real upstream data, not fabricated: one of
    dsic_mechanism's own 1,760/2,417 zero-correct question_ids, recorded in
    pins.json by the same Gate-1 importer run that built the corpus.

    This only checks the sample's SHAPE (a real, non-empty question_id) --
    it trusts the driver's own zero_correct label. For the independent
    check that this specific question really has zero correct options,
    re-derived from the raw upstream answers frame through a genuinely
    different code path than the driver's own classification (a critical
    review finding, docs/steer_codex_triage.md finding 7), see
    tests/test_steer_cases.py's
    ``test_golden_5s_sample_is_independently_verified_to_have_zero_correct_options``.
    """
    sample = _dsic_zero_correct_sample_question_id()
    assert isinstance(sample, str) and sample


def test_golden_5_degenerate_reference_was_excluded_at_gate_1_never_written_as_a_case() -> None:
    """Regression test proving the Gate-1 exclusion path fires: an admitted
    case must never carry a reference with zero correct options, so this
    question_id must have no committed case file at all."""
    sample = _dsic_zero_correct_sample_question_id()
    assert not _case_path("dsic_mechanism", sample).is_file()


def test_golden_5_degenerate_reference_is_absent_from_the_cached_admitted_rows() -> None:
    """Same exclusion, checked one layer lower: the flattened cache the
    runtime environment plugin reads never carries this question_id either
    -- the exclusion happens at flatten time, not just at case-write time."""
    sample = _dsic_zero_correct_sample_question_id()
    path = CACHE_ROOT / "dsic_mechanism" / "cases.jsonl"
    with path.open("r", encoding="utf-8") as handle:
        admitted_ids = {json.loads(line)["question_id"] for line in handle}
    assert sample not in admitted_ids
