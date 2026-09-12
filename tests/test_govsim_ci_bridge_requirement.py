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

Unlike the agenticpay and amazonbarg wiring tests, this one parses the workflow
as YAML and asserts on the ``pytest`` step itself. A substring search over the
job text cannot tell which step an ``env`` block belongs to, and GitHub scopes a
step's ``env`` to that step: a job that set ``AEREAD_GOVSIM_BRIDGE_REQUIRED`` on
the provisioning step and ran ``echo <the seven paths>`` in the next step passed
the substring version of this test (cross-model review of #179). It also asserts
the job's ``python-version`` equals the patch version sealed in
``cases/govsim/v1/pins.json``: ``environment.py`` compares the bridge's reported
``python_version`` to that pin exactly, so a floating ``"3.11"`` that resolved to
3.11.16 on the runner would fail every gated test with ``python_version mismatch``.
"""
from __future__ import annotations

import json
import shlex
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_CI_WORKFLOW = _ROOT / ".github" / "workflows" / "ci.yml"
_GOVSIM_PINS = _ROOT / "cases" / "govsim" / "v1" / "pins.json"
_JOB = "govsim-fidelity"

_FIDELITY_TEST_FILES = (
    "tests/test_govsim_bridge_driver.py",
    "tests/test_govsim_cases.py",
    "tests/test_govsim_environment.py",
    "tests/test_govsim_measurement.py",
    "tests/test_govsim_parity.py",
    "tests/test_govsim_replay.py",
    "tests/test_shared_runner_scoring_contract.py",
)


def _job() -> dict:
    assert _CI_WORKFLOW.is_file(), f"CI workflow not found at {_CI_WORKFLOW}"
    workflow = yaml.safe_load(_CI_WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow.get("jobs") or {}
    assert _JOB in jobs, f"ci.yml defines no `{_JOB}` job (#179); jobs: {sorted(jobs)}"
    return jobs[_JOB]


def _steps_running(executable: str) -> list[dict]:
    found = []
    for step in _job().get("steps") or []:
        run = step.get("run")
        if not isinstance(run, str):
            continue
        argv = shlex.split(run)
        if argv and Path(argv[0]).name == executable:
            found.append(step)
    return found


def _pytest_step() -> dict:
    steps = _steps_running("pytest")
    assert len(steps) == 1, (
        f"expected exactly one `pytest` step in the `{_JOB}` job, found {len(steps)}; "
        "requiring the bridge is meaningless if the gated job never runs pytest"
    )
    return steps[0]


def test_the_pytest_step_itself_sets_the_bridge_required_switch() -> None:
    env = _pytest_step().get("env") or {}
    assert str(env.get("AEREAD_GOVSIM_BRIDGE_REQUIRED", "")).strip() == "1", (
        f"the `{_JOB}` job's pytest step does not set AEREAD_GOVSIM_BRIDGE_REQUIRED=1 "
        "in its own env. GitHub scopes a step's env to that step, so setting it on the "
        "provisioning step leaves conftest.py's skip-to-failure hook off while pytest "
        f"runs (#179). Step env: {sorted(env)}"
    )
    for var in ("AEREAD_GOVSIM_UPSTREAM_ROOT", "AEREAD_GOVSIM_BRIDGE_PYTHON"):
        assert str(env.get(var, "")).strip(), (
            f"the pytest step does not set {var}; without it the bridge-gated tests "
            "skip (and, with the switch set, fail) instead of running"
        )


def test_the_pytest_step_runs_every_govsim_fidelity_test_file() -> None:
    step = _pytest_step()
    argv = shlex.split(step["run"])
    for test_file in _FIDELITY_TEST_FILES:
        assert test_file in argv, (
            f"the `{_JOB}` job's pytest step does not invoke {test_file}; requiring the "
            "bridge is meaningless if the gated job never runs this family's fidelity tests"
        )
    assert "if" not in step and not step.get("continue-on-error"), (
        "the pytest step must run unconditionally and its failure must fail the job"
    )


def test_the_job_pins_the_python_patch_the_corpus_sealed() -> None:
    pinned = json.loads(_GOVSIM_PINS.read_text(encoding="utf-8"))["bridge_versions"]["python_version"]
    setup_steps = [
        step for step in _job().get("steps") or []
        if str(step.get("uses", "")).startswith("actions/setup-python@")
    ]
    assert len(setup_steps) == 1, f"expected one setup-python step, found {len(setup_steps)}"
    requested = str((setup_steps[0].get("with") or {}).get("python-version", "")).strip()
    assert requested == pinned, (
        f"the `{_JOB}` job requests python-version {requested!r} but "
        f"cases/govsim/v1/pins.json seals python_version {pinned!r}; environment.py compares "
        "the bridge's reported version to the pin exactly, so anything but the sealed patch "
        "fails every gated test with `python_version mismatch`"
    )
