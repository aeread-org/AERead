from pathlib import Path

import pytest

from aeread.shared_runner.layout import LayoutError, PublicationLayout, RunLayout


def test_run_layout_names_the_run_task_and_attempt_levels(tmp_path: Path) -> None:
    layout = RunLayout(tmp_path, "run_001")

    assert layout.plan_path == tmp_path / "run_001" / "run_plan.json"
    assert layout.attempt_dir("task_001", "attempt_001") == (
        tmp_path
        / "run_001"
        / "tasks"
        / "task_001"
        / "attempts"
        / "attempt_001"
    )


def test_run_layout_reads_one_legacy_attempt_but_rejects_ambiguity(
    tmp_path: Path,
) -> None:
    layout = RunLayout(tmp_path, "run_001")
    legacy = layout.legacy_task_dir("task_001") / "attempt_001"
    legacy.mkdir(parents=True)
    assert layout.resolve_attempt_dir("task_001", "attempt_001") == legacy

    canonical = layout.attempt_dir("task_001", "attempt_001")
    canonical.mkdir(parents=True)
    with pytest.raises(LayoutError, match="canonical and legacy"):
        layout.resolve_attempt_dir("task_001", "attempt_001")


def test_layout_rejects_identifiers_that_escape_their_level(tmp_path: Path) -> None:
    with pytest.raises(LayoutError, match="one filesystem segment"):
        RunLayout(tmp_path, "../run")


def test_publication_layout_separates_tables_from_trajectories(tmp_path: Path) -> None:
    layout = PublicationLayout(tmp_path / "evidence" / "campaign_001")
    assert layout.tables_dir.name == "tables"
    assert layout.trajectories_dir.name == "trajectories"
