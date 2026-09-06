"""Tests for the ``steer`` measurement declarations (measurement.py, spec
section 2).

Every test here is pure, provider-free, and bridge-free: it reads only the
cached, flattened JSON at ``bridges/steer-data/<element>/cases.jsonl`` that
milestone 1's importer already wrote (never pandas, never a bridge
subprocess, never the network).

No bridge-gated upstream-scoring parity test exists in this module, unlike
``tests/test_tau3_retail_measurement.py``'s: STEER's pinned commit deleted
its own evaluation submodule (docs/steer_adapter_spec.md's Governing facts
-- "Remove STEER evaluation submodule"), so there is no upstream scorer to
call through a bridge and cross-check against (spec section 5, "Parity --
none against upstream scoring exists"). The corpus's own parity claims --
fetch-hash parity against the git-lfs ``oid`` and flatten-determinism
parity -- are already covered by ``tests/test_steer_cases.py``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from aeread.shared_runner.measurement import FamilyScoreSet, MeasurementLeafSpec
from aeread.shared_runner.task.evaluation import FamilyScoringInput
from aeread_families.steer import cases as steer_cases
from aeread_families.steer import measurement as m
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


def _rows(element: str) -> list[dict]:
    path = CACHE_ROOT / element / "cases.jsonl"
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def _first_row(element: str) -> dict:
    return _rows(element)[0]


def _row_with_options_count(element: str, options_count: int) -> dict:
    for row in _rows(element):
        if len(row["options"]) == options_count:
            return row
    raise AssertionError(f"no admitted {element} row has options_count={options_count}")


def _plugin() -> SteerPlugin:
    return SteerPlugin(steer_data_root=CACHE_ROOT)


# ---------------------------------------------------------------------------
# Leaf declaration (build_answer_key_leaf) -- spec section 2's exact shape.
# ---------------------------------------------------------------------------


def test_build_answer_key_leaf_declares_the_spec_section_2_shape() -> None:
    row = _first_row("transitivity")
    leaf = m.build_answer_key_leaf(row)

    assert isinstance(leaf, MeasurementLeafSpec)
    assert leaf.leaf_id == "steer_answer_key"
    assert leaf.composition_kind == "leaf"

    estimand = leaf.estimand
    assert estimand.estimand_id == "steer_answer_key"
    assert estimand.input_scope == "answer"
    assert estimand.direction == "maximize"
    assert estimand.units == "pass"

    verifier = leaf.verifier
    assert verifier.verifier_family == "canonical_reference"
    assert verifier.evaluation_class == "deterministic"
    assert verifier.reference.reference_kind == "canonical_point"
    assert verifier.reference.input_scope == "answer"
    assert verifier.reference.units == "pass"
    assert verifier.reference.source_sha256 == row["source_sha256"]


def test_build_answer_key_leaf_source_sha256_is_specific_to_the_questions_own_content() -> None:
    """Two different questions never share one reference identity."""
    row_a = _first_row("transitivity")
    row_b = _rows("transitivity")[1]
    assert row_a["source_sha256"] != row_b["source_sha256"]

    leaf_a = m.build_answer_key_leaf(row_a)
    leaf_b = m.build_answer_key_leaf(row_b)
    assert leaf_a.verifier.reference.source_sha256 != leaf_b.verifier.reference.source_sha256


def test_build_answer_key_leaf_is_identical_shape_across_declared_elements() -> None:
    """"identical shape for all 8 elements" (spec section 2) -- only the
    per-question reference.source_sha256 varies."""
    leaves = [m.build_answer_key_leaf(_first_row(element)) for element in steer_cases.DECLARED_ELEMENTS]
    for leaf in leaves:
        assert leaf.leaf_id == "steer_answer_key"
        assert leaf.verifier.verifier_family == "canonical_reference"
        assert leaf.verifier.evaluation_class == "deterministic"
        assert leaf.verifier.reference.reference_kind == "canonical_point"
        assert leaf.estimand.direction == "maximize"


# ---------------------------------------------------------------------------
# score_answer_key -- table-driven pass/fail/illegal/malformed, plus the
# "option_id present in Options globally but not within this question's own
# subset" edge case (spec section 5's "Unit -- scorer").
# ---------------------------------------------------------------------------


def test_score_answer_key_golden_1_successful_scores_1_0() -> None:
    row = _first_row("transitivity")
    leaf = m.build_answer_key_leaf(row)
    envelope = m.score_answer_key(
        leaf,
        correct_option_id=row["correct_option_id"],
        selected_option_id=row["correct_option_id"],
        valid=True,
        failure_code=None,
    )
    assert envelope.status == "ok"
    assert envelope.validity.status == "valid"
    assert envelope.primary.value == 1.0
    assert envelope.primary.unit == "pass"
    assert envelope.reference_values["gold_option_id"].value == float(row["correct_option_id"])


def test_score_answer_key_golden_2_valid_but_poor_scores_0_0() -> None:
    """A legal, in-range, schema-valid option_id that is not gold."""
    row = _first_row("plurality_voting")
    wrong_option_id = (row["correct_option_id"] + 1) % len(row["options"])
    assert wrong_option_id != row["correct_option_id"]
    leaf = m.build_answer_key_leaf(row)

    envelope = m.score_answer_key(
        leaf,
        correct_option_id=row["correct_option_id"],
        selected_option_id=wrong_option_id,
        valid=True,
        failure_code=None,
    )
    assert envelope.status == "ok"
    assert envelope.primary.value == 0.0


def test_score_answer_key_golden_3_invalid_unauthorized_is_invalid_measurement() -> None:
    """An option_id absent from this question's own option set: never
    coerced to option 0, never scored as a legitimate wrong answer."""
    row = _first_row("borda_count")
    leaf = m.build_answer_key_leaf(row)

    envelope = m.score_answer_key(
        leaf,
        correct_option_id=row["correct_option_id"],
        selected_option_id=None,
        valid=False,
        failure_code="option_id_out_of_range",
    )
    assert envelope.status == "invalid_measurement"
    assert envelope.primary is None
    assert envelope.validity.status == "invalid"
    assert envelope.validity.reasons == ("option_id_out_of_range",)


def test_score_answer_key_golden_4_malformed_operational_is_invalid_measurement() -> None:
    """Free-text prose instead of a parseable option identifier: surfaced
    as invalid_measurement, never as an economic zero."""
    row = _first_row("ir_mechanism")
    leaf = m.build_answer_key_leaf(row)

    envelope = m.score_answer_key(
        leaf,
        correct_option_id=row["correct_option_id"],
        selected_option_id=None,
        valid=False,
        failure_code="malformed_answer_json",
    )
    assert envelope.status == "invalid_measurement"
    assert envelope.primary is None
    assert envelope.validity.reasons == ("malformed_answer_json",)
    # Distinguished from golden 2: never the value 0.0 wearing an
    # "ok"/valid label.
    assert envelope.status != "ok"


def test_score_answer_key_edge_case_option_id_valid_elsewhere_but_not_here() -> None:
    """An option_id present in Options globally but not within this
    question's own subset (spec section 5's stated edge case): plurality_voting
    has both 4-option and 5-option questions in the pilot corpus; option_id 4
    is a real, in-range index for a 5-option question but out of range for a
    4-option one. environment.py's legal() -- exercised directly here --
    rejects it per-question, and the scorer must report that rejection as
    invalid_measurement, never as a legitimate wrong answer."""
    row_4_option = _row_with_options_count("plurality_voting", 4)
    row_5_option = _row_with_options_count("plurality_voting", 5)
    globally_valid_option_id = 4
    assert globally_valid_option_id < len(row_5_option["options"])
    assert globally_valid_option_id >= len(row_4_option["options"])

    plugin = _plugin()
    family_case = {
        "element": "plurality_voting",
        "question_id": row_4_option["question_id"],
        "options_count": len(row_4_option["options"]),
    }
    legality = plugin.legal(family_case, {}, "agent", None, {"option_id": globally_valid_option_id})
    assert not legality.legal
    assert legality.reason == "option_id_out_of_range"

    leaf = m.build_answer_key_leaf(row_4_option)
    envelope = m.score_answer_key(
        leaf,
        correct_option_id=row_4_option["correct_option_id"],
        selected_option_id=None,
        valid=False,
        failure_code=legality.reason,
    )
    assert envelope.status == "invalid_measurement"
    assert envelope.primary is None


# ---------------------------------------------------------------------------
# SteerScorer / build_scorer wiring.
# ---------------------------------------------------------------------------


def test_build_scorer_returns_the_leaf_measurement_declares_for_the_same_row() -> None:
    row = _first_row("dsic_mechanism")
    scorer = m.build_scorer(row)
    assert scorer.question_id == row["question_id"]
    assert scorer.correct_option_id == row["correct_option_id"]
    assert scorer.leaves == (m.build_answer_key_leaf(row),)


def test_steer_scorer_score_delegates_to_score_answer_key_for_a_valid_outcome() -> None:
    row = _first_row("certainty_effect")
    scorer = m.build_scorer(row)
    outcome = {
        "termination_reason": "answered",
        "selected_option_id": row["correct_option_id"],
        "failure_code": None,
    }
    envelope = scorer.score(outcome)
    assert envelope.status == "ok"
    assert envelope.primary.value == 1.0


def test_steer_scorer_score_delegates_to_score_answer_key_for_an_invalid_outcome() -> None:
    row = _first_row("backward_induction")
    scorer = m.build_scorer(row)
    outcome = {
        "termination_reason": "error",
        "selected_option_id": None,
        "failure_code": "malformed_answer_json",
    }
    envelope = scorer.score(outcome)
    assert envelope.status == "invalid_measurement"
    assert envelope.validity.reasons == ("malformed_answer_json",)


# ---------------------------------------------------------------------------
# SteerScorer.__call__ -- the production finalizer seam under the
# kernel_scoring_contract_spec.md contract (migration milestone 2 of 3).
# ``task.evaluation.finalize_family_execution`` executes
# ``plugin.build_scorer(family_case)(scoring_input,
# evidence_refs=scoring_input.evidence_refs)`` directly on whatever
# ``build_scorer`` returns -- never through ``.score(...)`` the way every
# golden above does. Before this milestone, ``__call__`` took a
# ``FamilyScoringInput`` but returned a bare ``ScoreEnvelope``, leaving the
# caller to know it had to be unwrapped from a ``FamilyScoreSet`` itself;
# the tests below prove the declared leaf set now comes back wrapped.
# ---------------------------------------------------------------------------


def test_steer_scorer_call_returns_a_family_score_set_with_the_one_declared_leaf() -> None:
    row = _first_row("certainty_effect")
    scorer = m.build_scorer(row)
    scoring_input = FamilyScoringInput(
        outcome={
            "termination_reason": "answered",
            "selected_option_id": row["correct_option_id"],
            "failure_code": None,
        },
        phase_instances=(),
        evidence_refs=("evt_outcome_0",),
    )

    score_set = scorer(scoring_input, evidence_refs=scoring_input.evidence_refs)

    assert isinstance(score_set, FamilyScoreSet)
    assert {score.leaf.leaf_id for score in score_set.scores} == {m.ANSWER_KEY_LEAF_ID}
    assert score_set.primary_leaf_id == m.ANSWER_KEY_LEAF_ID
    assert score_set.admission_leaf_ids == (m.ANSWER_KEY_LEAF_ID,)

    answer_key = score_set.scores[0]
    assert answer_key.status == "ok"
    assert answer_key.primary.value == 1.0
    assert answer_key.evidence_refs == ("evt_outcome_0",)


def test_steer_scorer_call_reports_invalid_measurement_for_an_invalid_submission() -> None:
    row = _first_row("backward_induction")
    scorer = m.build_scorer(row)
    scoring_input = FamilyScoringInput(
        outcome={
            "termination_reason": "error",
            "selected_option_id": None,
            "failure_code": "malformed_answer_json",
        },
        phase_instances=(),
        evidence_refs=("evt_outcome_0",),
    )

    score_set = scorer(scoring_input, evidence_refs=scoring_input.evidence_refs)

    assert isinstance(score_set, FamilyScoreSet)
    answer_key = score_set.scores[0]
    assert answer_key.leaf.leaf_id == m.ANSWER_KEY_LEAF_ID
    assert answer_key.status == "invalid_measurement"
    assert answer_key.validity.reasons == ("malformed_answer_json",)


# ---------------------------------------------------------------------------
# Plugin wiring (environment.py's build_scorer hook).
# ---------------------------------------------------------------------------


def test_plugin_build_scorer_returns_the_same_leaf_measurement_py_declares() -> None:
    element = "pure_nash"
    row = _first_row(element)
    plugin = _plugin()
    family_case = {
        "element": element,
        "question_id": row["question_id"],
        "options_count": len(row["options"]),
        "source_sha256": row["source_sha256"],
    }

    scorer = plugin.build_scorer(family_case)

    assert scorer.leaves == (m.build_answer_key_leaf(row),)
    assert scorer.correct_option_id == row["correct_option_id"]
