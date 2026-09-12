"""Issue #179 regression, mirroring agenticpay's own: CI must require the
govsim bridge, or upstream-fidelity assertions can silently skip while the
run stays green.

``conftest.py``'s ``pytest_terminal_summary`` hook already converts a bridge-gated
skip into a hard failure -- but only when the matching
``AEREAD_<FAMILY>_BRIDGE_REQUIRED`` environment variable is set ("Off by default so
it never surprises a local run", per that module's own docstring). The govsim gate
itself landed in #176; nothing in that change required any CI run to actually opt
in. Without a job that sets ``AEREAD_GOVSIM_BRIDGE_REQUIRED``, a plain
``pytest tests/ -q`` run can go green while every govsim upstream-fidelity test
(``test_govsim_bridge_driver.py``, ``test_govsim_cases.py``,
``test_govsim_environment.py``, ``test_govsim_measurement.py``,
``test_govsim_parity.py``, ``test_govsim_replay.py``) silently skipped for want of
a provisioned bridge.

``tests/test_shared_runner_scoring_contract.py`` is included here too, for the
same reason it is included in agenticpay's job: its
``test_govsim_obeys_the_scoring_contract`` is govsim's own scoring-contract
fidelity test, per-test-skipped when the bridge is unavailable, and the
always-on ``test_every_registered_family_obeys_the_scoring_contract`` in that same
file only marks govsim "enrolled" for closure purposes without ever invoking its
scorer -- so this is the only place that test actually gets certified as run, not
merely skipped.

This test never actually runs GitHub Actions (this suite is provider-free/offline,
and there is no local runner for it) -- it inspects the checked-in workflow text
directly, so it cannot prove the job it finds actually succeeds end to end. What it
can and does prove is that the opt-in switch is wired on for this family and that
the fidelity test files are actually invoked under it, so this protection cannot
silently regress (e.g. someone deleting the job, or the job drifting to run a
different, non-fidelity test selection) without this test failing first.
"""
from __future__ import annotations

import re
from pathlib import Path

_CI_WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"

_FIDELITY_TEST_FILES = (
    "tests/test_govsim_bridge_driver.py",
    "tests/test_govsim_cases.py",
    "tests/test_govsim_environment.py",
    "tests/test_govsim_measurement.py",
    "tests/test_govsim_parity.py",
    "tests/test_govsim_replay.py",
    "tests/test_shared_runner_scoring_contract.py",
)


def _workflow_text() -> str:
    assert _CI_WORKFLOW.is_file(), f"CI workflow not found at {_CI_WORKFLOW}"
    return _CI_WORKFLOW.read_text(encoding="utf-8")


def _workflow_code() -> str:
    """The workflow with comments stripped.

    The variable's name also appears in a comment explaining why the switch
    exists, so a substring search over the raw file passes even when the
    operative assignment is deleted -- the comment alone keeps it green.
    Everything asserted below reads this instead.
    """

    lines = []
    for line in _workflow_text().splitlines():
        code = line.split("#", 1)[0]
        if code.strip():
            lines.append(code)
    return "\n".join(lines)


def _govsim_job_code() -> str:
    """Only the ``govsim-fidelity`` job's lines, comments stripped.

    The agenticpay and amazonbarg wiring tests search the whole workflow. That
    was sufficient while one job listed ``tests/test_shared_runner_scoring_
    contract.py``; it is not now that three do. Dropping that file from this
    job alone left a whole-file search green, because agenticpay's job still
    names it -- observed while writing this test. So every assertion below is
    scoped to this job's block: from the ``govsim-fidelity:`` key to the next
    top-level job key, or the end of the file.
    """

    text = _workflow_code()
    match = re.search(
        r"^  govsim-fidelity:\n(?P<body>(?:(?!^  [A-Za-z0-9_-]+:\n).*\n?)*)",
        text,
        re.MULTILINE,
    )
    assert match, "ci.yml defines no `govsim-fidelity` job (#179)"
    return match.group("body")


def test_ci_sets_the_govsim_bridge_required_switch() -> None:
    text = _govsim_job_code()
    assert re.search(
        r"^\s*AEREAD_GOVSIM_BRIDGE_REQUIRED\s*:\s*[\"']?1[\"']?\s*$",
        text,
        re.MULTILINE,
    ), (
        "the govsim-fidelity job does not set AEREAD_GOVSIM_BRIDGE_REQUIRED: without it, "
        "conftest.py's skip-to-failure hook stays off by default, and CI can go "
        "green while every govsim upstream-fidelity assertion silently skipped "
        "(#179)"
    )


def test_ci_actually_runs_every_govsim_fidelity_test_file_under_the_bridge_gate() -> None:
    text = _govsim_job_code()
    for test_file in _FIDELITY_TEST_FILES:
        assert test_file in text, (
            f"the govsim-fidelity job does not invoke {test_file}; requiring the bridge is meaningless if "
            "the gated job never actually runs this family's fidelity tests"
        )
