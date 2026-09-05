"""Canonical filesystem layout for runs and publications.

The object hierarchy is campaign -> run -> task -> attempt -> event. Provider
calls are canonical events within an attempt and are projected into the
``model_calls`` research table; they are not duplicated as mutable source
files.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


RUNS_ROOT = Path("runs")
PUBLICATION_ROOT = Path("evidence")
WORK_ROOT = Path("work")
TASKS_DIRECTORY = "tasks"
ATTEMPTS_DIRECTORY = "attempts"
TABLES_DIRECTORY = "tables"
TRAJECTORIES_DIRECTORY = "trajectories"


class LayoutError(ValueError):
    """A run-layout identity or path is ambiguous or unsafe."""


def _segment(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise LayoutError(f"{field} must be a non-empty string")
    if value in {".", ".."} or Path(value).name != value:
        raise LayoutError(f"{field} must be one filesystem segment")
    return value


@dataclass(frozen=True, slots=True)
class RunLayout:
    """Paths for one sealed run below a caller-selected local run root."""

    root: Path
    run_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))
        _segment(self.run_id, field="run_id")

    @property
    def run_dir(self) -> Path:
        return self.root / self.run_id

    @property
    def plan_path(self) -> Path:
        return self.run_dir / "run_plan.json"

    def task_dir(self, task_id: str) -> Path:
        return self.run_dir / TASKS_DIRECTORY / _segment(task_id, field="task_id")

    def attempts_dir(self, task_id: str) -> Path:
        return self.task_dir(task_id) / ATTEMPTS_DIRECTORY

    def attempt_dir(self, task_id: str, attempt_id: str) -> Path:
        return self.attempts_dir(task_id) / _segment(
            attempt_id, field="episode_attempt_id"
        )

    def legacy_task_dir(self, task_id: str) -> Path:
        """Pre-layout task path, retained only for read compatibility."""

        return self.run_dir / _segment(task_id, field="task_id")

    def resolve_task_dir(self, task_id: str) -> Path:
        canonical = self.task_dir(task_id)
        legacy = self.legacy_task_dir(task_id)
        if canonical.exists() and legacy.exists():
            raise LayoutError(
                f"both canonical and legacy task directories exist for {task_id!r}"
            )
        return canonical if canonical.exists() or not legacy.exists() else legacy

    def resolve_attempts_dir(self, task_id: str) -> Path:
        task_dir = self.resolve_task_dir(task_id)
        return (
            task_dir / ATTEMPTS_DIRECTORY
            if task_dir == self.task_dir(task_id)
            else task_dir
        )

    def resolve_attempt_dir(self, task_id: str, attempt_id: str) -> Path:
        canonical = self.attempt_dir(task_id, attempt_id)
        legacy = self.legacy_task_dir(task_id) / _segment(
            attempt_id, field="episode_attempt_id"
        )
        if canonical.exists() and legacy.exists():
            raise LayoutError(
                f"both canonical and legacy attempt directories exist for {attempt_id!r}"
            )
        return canonical if canonical.exists() or not legacy.exists() else legacy


@dataclass(frozen=True, slots=True)
class PublicationLayout:
    """Stable locations in one curated, tracked publication bundle."""

    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))

    @property
    def tables_dir(self) -> Path:
        return self.root / TABLES_DIRECTORY

    @property
    def trajectories_dir(self) -> Path:
        return self.root / TRAJECTORIES_DIRECTORY


__all__ = [
    "ATTEMPTS_DIRECTORY",
    "LayoutError",
    "PUBLICATION_ROOT",
    "PublicationLayout",
    "RUNS_ROOT",
    "RunLayout",
    "TABLES_DIRECTORY",
    "TASKS_DIRECTORY",
    "TRAJECTORIES_DIRECTORY",
    "WORK_ROOT",
]
