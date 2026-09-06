"""Independent-review regression (amazonbarg migration review, finding 4):
CI must require the amazonbarg bridge, or the family's scoring-contract
protocol test can silently skip while the run stays green.

``conftest.py``'s ``pytest_terminal_summary`` hook already converts a
bridge-gated skip into a hard failure -- but only when the matching
``AEREAD_AMAZONBARG_BRIDGE_REQUIRED`` environment variable is set ("Off by
default so it never surprises a local run", per that module's own
docstring). Before this test, nothing enforced that *some* run in this
project's CI actually opts in for amazonbarg specifically: as checked in,
``.github/workflows/ci.yml`` ran only ``pytest tests/ -q`` (no bridge-required
variable set for this family at all) plus a dedicated ``agenticpay-fidelity``
job for a different family -- so a plain CI run reported success (green)
while every amazonbarg upstream-fidelity assertion, INCLUDING this family's
own registry-driven scoring-contract check
(``test_amazonbarg_obeys_the_scoring_contract``,
``tests/test_shared_runner_scoring_contract.py``), silently skipped for want
of the pinned upstream AmazonPriceHistory checkout. That test is the one
thing standing between ``amazonbarg.bilateral`` being enrolled in
``TRUSTED_BUILTIN_PLUGIN_KEYS`` (a trust claim) and that trust actually being
behaviourally checked (ruling R6: "a family must be added to that set to be
trusted at all, and that same act enrolls it in the conformance test. You
cannot obtain one without the other.") -- without a CI job that actually
requires the bridge, enrollment and conformance-checking silently decouple
by default.

This test never actually runs GitHub Actions (this suite is
provider-free/offline, and there is no local runner for it) -- it inspects
the checked-in workflow text directly, so it cannot prove the job it finds
actually succeeds end to end. What it can and does prove is that the opt-in
switch is wired on for this family and that the family's fidelity/protocol
test files are actually invoked under it, so this protection cannot silently
regress (e.g. someone deleting the job, or the job drifting to run a
different, non-fidelity test selection) without this test failing first.
Mirrors ``tests/test_agenticpay_bilateral_ci_bridge_requirement.py`` exactly,
except amazonbarg needs no separate bridge-interpreter provisioning step
(``upstream_shim.py``'s own module docstring: the delegated import runs
in-process, under this project's own venv) -- only the pinned upstream
checkout itself.

Gate follow-up: this file's own basename contains ``test_amazonbarg_``, so
``conftest.py``'s ``pytest_collection_modifyitems`` swept its three tests into
a skip under the plain ``test`` job whenever the upstream checkout was
missing (true for every real CI runner, since that job never provisions any
family's checkout) -- and this file was never added to
``_FIDELITY_TEST_FILES`` above either, so the ``amazonbarg-fidelity`` job
never ran it. The three tests here read only the checked-in workflow YAML
text; they touch no upstream bytes at all, so they are marked
``@pytest.mark.no_upstream_checkout_required`` below to run unconditionally
under the plain job instead of being added to the fidelity job (which would
gate them on a checkout they do not need).
``test_every_amazonbarg_test_file_is_covered_by_some_ci_job`` guards against
this exact shape of gap recurring for any amazonbarg test file.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_CI_WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"
_TESTS_DIR = Path(__file__).resolve().parent

_FIDELITY_TEST_FILES = (
    "tests/test_amazonbarg_cases.py",
    "tests/test_amazonbarg_environment.py",
    "tests/test_amazonbarg_harness.py",
    "tests/test_amazonbarg_measurement.py",
    "tests/test_amazonbarg_replay.py",
    "tests/test_amazonbarg_shim.py",
    "tests/test_amazonbarg_upstream_skip_scope.py",
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


@pytest.mark.no_upstream_checkout_required
def test_ci_sets_the_amazonbarg_bridge_required_switch() -> None:
    text = _workflow_code()
    assert re.search(
        r"^\s*AEREAD_AMAZONBARG_BRIDGE_REQUIRED\s*:\s*[\"']?1[\"']?\s*$",
        text,
        re.MULTILINE,
    ), (
        "no CI step sets AEREAD_AMAZONBARG_BRIDGE_REQUIRED: without it, "
        "conftest.py's skip-to-failure hook stays off by default, and CI can go "
        "green while amazonbarg's scoring-contract protocol test "
        "(test_amazonbarg_obeys_the_scoring_contract) and every other amazonbarg "
        "upstream-fidelity assertion silently skip (migration review finding 4)"
    )


@pytest.mark.no_upstream_checkout_required
def test_ci_provisions_the_pinned_upstream_amazonbarg_checkout() -> None:
    text = _workflow_code()
    assert "AEREAD_AMAZONBARG_UPSTREAM_ROOT" in text, (
        "no CI step sets AEREAD_AMAZONBARG_UPSTREAM_ROOT; requiring the bridge "
        "is meaningless if the gated job cannot even locate the pinned upstream "
        "checkout"
    )
    assert "TianXiaSJTU/AmazonPriceHistory" in text, (
        "no CI step checks out the pinned upstream AmazonPriceHistory repository"
    )


@pytest.mark.no_upstream_checkout_required
def test_ci_actually_runs_every_amazonbarg_fidelity_test_file_under_the_bridge_gate() -> None:
    text = _workflow_code()
    for test_file in _FIDELITY_TEST_FILES:
        assert test_file in text, (
            f"no CI job invokes {test_file}; requiring the bridge is meaningless if "
            "the gated job never actually runs this family's fidelity/protocol tests"
        )


def _module_level_test_functions(path: Path) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]


def _is_marked_no_upstream_checkout_required(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    return any(
        isinstance(decorator, ast.Attribute)
        and decorator.attr == "no_upstream_checkout_required"
        and isinstance(decorator.value, ast.Attribute)
        and decorator.value.attr == "mark"
        for decorator in node.decorator_list
    )


def _exempt_from_the_plain_jobs_amazonbarg_skip(path: Path) -> bool:
    """True if every test in ``path`` is marked so the plain ``test`` job's
    blanket amazonbarg skip (``conftest.py``'s ``pytest_collection_modifyitems``,
    keyed off ``test_amazonbarg_`` in the basename) never touches it."""
    test_functions = _module_level_test_functions(path)
    return bool(test_functions) and all(
        _is_marked_no_upstream_checkout_required(node) for node in test_functions
    )


@pytest.mark.no_upstream_checkout_required
def test_every_amazonbarg_test_file_is_covered_by_some_ci_job() -> None:
    """Guard for the gate-follow-up defect above: a
    ``tests/test_amazonbarg_*.py`` file that is neither listed in the fidelity
    job's own invocation nor exempted -- every one of its tests marked
    ``no_upstream_checkout_required`` -- from the plain job's blanket
    amazonbarg skip runs in *no* CI job at all. That is exactly what happened
    to this very file before this test existed: it was absent from
    ``_FIDELITY_TEST_FILES`` and carried no marker, so the plain job skipped
    it (no upstream checkout on a real runner) and the fidelity job never
    invoked it either.
    """
    text = _workflow_code()
    uncovered = [
        f"tests/{path.name}"
        for path in sorted(_TESTS_DIR.glob("test_amazonbarg_*.py"))
        if f"tests/{path.name}" not in text
        and not _exempt_from_the_plain_jobs_amazonbarg_skip(path)
    ]
    assert not uncovered, (
        "these amazonbarg test files run under no CI job at all -- neither "
        "listed in the amazonbarg-fidelity job's pytest invocation nor "
        "exempted (every test marked no_upstream_checkout_required) from the "
        f"plain job's blanket amazonbarg skip: {uncovered}"
    )
