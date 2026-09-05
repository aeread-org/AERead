from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from aeread_families.housing.harness_leaderboard import (
    build_leaderboard,
    leaderboard_csv,
    leaderboard_markdown,
    write_leaderboard,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes


EVIDENCE = Path(__file__).parents[1] / "evidence"
PUBLICATION = EVIDENCE / "housing_open_harness_2026-08-31"
BAKEOFF = PUBLICATION / "reports" / "bakeoff.json"
ADMISSION = PUBLICATION / "qc" / "admission.json"


def _inputs() -> tuple[dict, dict]:
    return json.loads(BAKEOFF.read_bytes()), json.loads(ADMISSION.read_bytes())


def test_full_trajectory_leaderboard_ranks_only_comparable_completed_arms() -> None:
    bakeoff, admission = _inputs()

    leaderboard = build_leaderboard(bakeoff, admission=admission)
    rows = leaderboard["full_trajectory_leaderboard"]

    assert [(row["rank"], row["harness_id"], row["status"]) for row in rows] == [
        (1, "aeread_minimal_chat_v1", "ranked"),
        (2, "langchain_provider_strategy_v1", "ranked"),
        (None, "smolagents_tool_calling_agent_v1", "disqualified_operational_failure"),
    ]
    assert rows[0]["mean_within_case_score"] == pytest.approx(0.8629114671)
    assert rows[2]["cost_qualifier"] == "lower_bound"
    assert rows[2]["provider_cost_complete"] is False


def test_single_action_results_are_a_separate_qualification_order() -> None:
    bakeoff, admission = _inputs()
    leaderboard = build_leaderboard(bakeoff, admission=admission)

    assert [row["harness_id"] for row in leaderboard["qualification_gate"]] == [
        "aeread_minimal_chat",
        "langchain_provider_strategy",
        "pydantic_ai_native_output",
        "smolagents_tool_calling_agent",
    ]
    assert all(
        row["status"] == "passed_single_action_gate"
        for row in leaderboard["qualification_gate"]
    )


def test_leaderboard_refuses_a_tampered_bakeoff_artifact() -> None:
    bakeoff, admission = _inputs()
    tampered = copy.deepcopy(bakeoff)
    tampered["condition_summaries"]["aeread_minimal_chat_v1"][
        "mean_within_case_score"
    ] = 1.0

    with pytest.raises(ValueError, match="digest mismatch"):
        build_leaderboard(tampered, admission=admission)


def test_leaderboard_exports_human_and_machine_readable_views(tmp_path) -> None:
    prefix = tmp_path / "housing.leaderboard.2026-08-31"
    json_path, csv_path, markdown_path = write_leaderboard(
        bakeoff_path=BAKEOFF,
        admission_path=ADMISSION,
        output_prefix=prefix,
    )

    assert json_path.name == "housing.leaderboard.2026-08-31.json"
    assert "AERead Minimal Chat" in csv_path.read_text()
    markdown = markdown_path.read_text()
    assert "# Housing V1 Open Harness Leaderboard" in markdown
    assert "PydanticAI Native Output" in markdown

    payload = json.loads(json_path.read_bytes())
    claimed = payload.pop("leaderboard_sha256")
    assert claimed == hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def test_renderers_preserve_unranked_operational_failure() -> None:
    bakeoff, admission = _inputs()
    leaderboard = build_leaderboard(bakeoff, admission=admission)

    assert "disqualified_operational_failure" in leaderboard_csv(leaderboard)
    markdown = leaderboard_markdown(leaderboard)
    assert "0/1" in markdown
    assert "known lower bounds" in markdown
    assert "≥$0.004463" in markdown
    assert "$≥" not in markdown


def test_langgraph_condition_has_a_stable_display_name() -> None:
    from aeread_families.housing.harness_leaderboard import DISPLAY_NAMES

    assert (
        DISPLAY_NAMES["langgraph_structured_output_v1"]
        == "LangGraph Structured Output"
    )
