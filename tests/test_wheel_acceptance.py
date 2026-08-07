"""Wheel-acceptance test: prove the artifact adopters install, not the
checkout.

Every other test in this suite runs against ``src/`` on ``sys.path`` (see
``conftest.py``), which is exactly the gap Workstream 7 of
``integrations/rllm/READINESS_PROPOSAL.md`` calls out: a working-directory
change can still discover the checkout root. This module instead builds the
real wheel with the running interpreter, installs it into a throwaway venv,
and runs AERead's dataset preflight from a directory that contains no
AERead source tree at all.

This is the only module in the suite that touches the network -- to fetch
the wheel's own build backend and runtime dependencies (openai, scipy,
numpy) from PyPI, per the readiness proposal's "no network beyond pip
installing the local wheel and its cached deps" bound. It never installs
``rllm`` and never calls a model provider. It is marked ``wheel`` and
excluded from the default run (see the ``addopts`` in ``pyproject.toml``);
select it explicitly::

    pytest tests/test_wheel_acceptance.py -m wheel -q
"""
from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

import pytest


pytestmark = pytest.mark.wheel

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CASE_IDS = [
    "case01_visible_bilateral_ir",
    "case02_multiparty_clearing",
    "case03_hidden_discovery",
    "case04_consent_under_hidden_info",
]


def _subprocess_env() -> dict[str, str]:
    """A copy of the environment with no path back into this checkout."""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return env


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, check=True, capture_output=True, text=True,
        env=_subprocess_env(), **kwargs,
    )


@pytest.fixture(scope="module")
def installed_wheel(tmp_path_factory) -> tuple[Path, Path]:
    """Build the wheel once and install it into a fresh, isolated venv."""
    dist_dir = tmp_path_factory.mktemp("dist")
    _run([
        sys.executable, "-m", "pip", "wheel", str(REPO_ROOT),
        "--no-deps", "-w", str(dist_dir),
    ])
    wheels = sorted(dist_dir.glob("aeread-*.whl"))
    assert len(wheels) == 1, f"expected exactly one built wheel, found {wheels}"

    venv_dir = tmp_path_factory.mktemp("venv") / "env"
    venv.EnvBuilder(with_pip=True, clear=True).create(str(venv_dir))
    venv_python = venv_dir / (
        "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    )
    _run([str(venv_python), "-m", "pip", "install", str(wheels[0])])

    outside_checkout = tmp_path_factory.mktemp("outside-checkout")
    return venv_python, outside_checkout


def test_installed_package_does_not_resolve_back_into_the_checkout(
    installed_wheel,
):
    venv_python, outside_checkout = installed_wheel
    located = _run(
        [str(venv_python), "-c",
         "import aeread, os; print(os.path.dirname(aeread.__file__))"],
        cwd=str(outside_checkout),
    ).stdout.strip()
    assert located
    assert not Path(located).is_relative_to(REPO_ROOT)


def test_wheel_ships_the_rllm_entry_points_without_installing_rllm(
    installed_wheel,
):
    venv_python, outside_checkout = installed_wheel
    script = (
        "from importlib.metadata import entry_points\n"
        "eps = entry_points()\n"
        "agents = {e.name: e.value for e in eps.select(group='rllm.agents')}\n"
        "evaluators = {e.name: e.value "
        "for e in eps.select(group='rllm.evaluators')}\n"
        "print(agents)\n"
        "print(evaluators)\n"
    )
    output = _run(
        [str(venv_python), "-c", script], cwd=str(outside_checkout),
    ).stdout.splitlines()
    assert output[0] == (
        "{'aeread': 'aeread.integrations.rllm_flow:aeread_flow'}"
    )
    assert output[1] == (
        "{'aeread': 'aeread.integrations.rllm_eval:aeread_evaluator'}"
    )


def test_preflight_resolves_every_manifest_resource_outside_the_checkout(
    installed_wheel,
):
    venv_python, outside_checkout = installed_wheel
    result = _run(
        [str(venv_python), "-m", "aeread.integrations.rllm_dataset",
         "--preflight"],
        cwd=str(outside_checkout),
    )

    assert "caseset_version: integration-v1" in result.stdout
    assert "protocol_version: exchange-v1" in result.stdout
    assert str(REPO_ROOT) not in result.stdout

    verified_lines = [
        line for line in result.stdout.splitlines() if "verified=" in line
    ]
    assert len(verified_lines) == len(EXPECTED_CASE_IDS)
    for case_id, line in zip(EXPECTED_CASE_IDS, verified_lines):
        assert line.strip().startswith(f"{case_id}:")
        verified_path = line.rsplit("verified=", 1)[1].strip()
        assert Path(verified_path).is_file()
        assert not Path(verified_path).is_relative_to(REPO_ROOT)

    assert "train: 16 rows" in result.stdout
    assert "dev: 8 rows" in result.stdout
    assert "test: 8 rows (public-development alias of dev)" in result.stdout
