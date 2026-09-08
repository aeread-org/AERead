"""Shared test gating.

``@pytest.mark.local_run("<campaign_id>", ...)`` declares that a test reads
the git-ignored ``runs/<campaign_id>`` directories produced by paid or local
campaigns. Such tests skip where any declared run is absent (CI, fresh clones)
and fail instead when ``AEREAD_LOCAL_RUNS_REQUIRED=1``, so a machine that is
supposed to hold the runs cannot pass by skipping quietly.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = REPOSITORY_ROOT / "runs"
LOCAL_RUNS_REQUIRED = "AEREAD_LOCAL_RUNS_REQUIRED"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "local_run(*campaign_ids): test reads the git-ignored runs/<campaign_id> "
        f"directories; skipped when any is absent unless {LOCAL_RUNS_REQUIRED}=1",
    )


@pytest.fixture(autouse=True)
def _require_declared_local_runs(request: pytest.FixtureRequest) -> None:
    marker = request.node.get_closest_marker("local_run")
    if marker is None:
        return
    campaign_ids = marker.args
    if not campaign_ids or any(
        not isinstance(item, str) or not item for item in campaign_ids
    ):
        raise pytest.UsageError(
            "local_run marker requires one or more non-empty campaign_id strings"
        )
    missing = [item for item in campaign_ids if not (RUNS_ROOT / item).is_dir()]
    if not missing:
        return
    message = "local campaign run is absent: " + ", ".join(
        f"runs/{item}" for item in missing
    )
    if os.environ.get(LOCAL_RUNS_REQUIRED) == "1":
        pytest.fail(message, pytrace=False)
    pytest.skip(message)
