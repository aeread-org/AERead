"""Tests for the repo-root ``conftest.py``'s upstream-required skip-to-
failure gate, scoped to alympics.wac's own policy entry.

Codex triage finding 9 (docs/alympics_codex_triage.md): every one of this
family's environment/measurement/harness/parity/replay test modules skips,
module-level, whenever the pinned upstream Alympics checkout is absent
(``tests/test_alympics_wac_*.py``'s own ``_upstream_root()`` helper), and
this project's CI workflow (``.github/workflows/ci.yml``) provisions
neither the checkout nor an env var to require it -- so a green CI run for
this family currently proves only that ``test_alympics_wac_cases.py``'s
upstream-free tests ran. This mirrors the project's own already-established
fix for the identical shape of problem in tau2/tau3 (see ``conftest.py``'s
``pytest_terminal_summary``, predating this family): setting a dedicated,
opt-in env var turns a matching skip into a failed run instead of a silent
one, off by default so it never surprises a local contributor.

These tests call the real ``conftest.pytest_terminal_summary`` function --
loaded directly from the repo-root file, never reimplemented -- against
hand-built stand-ins for pytest's own ``terminalreporter``/``config``
objects (the same style this family's own scorer tests already use for
hand-built ``round_log`` evidence): the *production* hook function, driven
by realistic fake inputs, not a shortcut re-implementation of its logic.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

_CONFTEST_PATH = Path(__file__).resolve().parents[1] / "conftest.py"

ALYMPICS_ENV_VAR = "AEREAD_ALYMPICS_UPSTREAM_REQUIRED"
ALYMPICS_SKIP_TEXT = "pinned upstream Alympics checkout not found at /some/path"


def _load_conftest():
    spec = importlib.util.spec_from_file_location("_alympics_test_root_conftest", _CONFTEST_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeReport:
    def __init__(self, longrepr: str) -> None:
        self.longrepr = longrepr


class _FakeTerminalReporter:
    def __init__(self, skipped):
        self.stats = {"skipped": list(skipped)}
        self.lines: list[str] = []
        self.seps: list[str] = []
        self._session = SimpleNamespace(exitstatus=0)

    def write_sep(self, char, title=None, **kwargs) -> None:
        if title:
            self.seps.append(title)

    def write_line(self, line: str) -> None:
        self.lines.append(line)


class _FakeConfig:
    def __init__(self) -> None:
        self.option = SimpleNamespace()


def test_alympics_upstream_skip_stays_silent_without_the_required_env_var(monkeypatch) -> None:
    monkeypatch.delenv(ALYMPICS_ENV_VAR, raising=False)
    conftest = _load_conftest()
    reporter = _FakeTerminalReporter([_FakeReport(ALYMPICS_SKIP_TEXT)])
    config = _FakeConfig()

    conftest.pytest_terminal_summary(reporter, 0, config)

    assert reporter._session.exitstatus == 0
    assert reporter.lines == []
    assert reporter.seps == []


def test_alympics_upstream_skip_fails_the_run_when_required(monkeypatch) -> None:
    monkeypatch.setenv(ALYMPICS_ENV_VAR, "1")
    conftest = _load_conftest()
    reporter = _FakeTerminalReporter([_FakeReport(ALYMPICS_SKIP_TEXT)])
    config = _FakeConfig()

    conftest.pytest_terminal_summary(reporter, 0, config)

    assert reporter._session.exitstatus == 1
    assert any("alympics" in title.lower() for title in reporter.seps)
    assert any(ALYMPICS_SKIP_TEXT in line for line in reporter.lines)


def test_unrelated_skips_never_trip_the_alympics_gate(monkeypatch) -> None:
    monkeypatch.setenv(ALYMPICS_ENV_VAR, "1")
    conftest = _load_conftest()
    reporter = _FakeTerminalReporter([_FakeReport("some unrelated skip reason")])
    config = _FakeConfig()

    conftest.pytest_terminal_summary(reporter, 0, config)

    assert reporter._session.exitstatus == 0
    assert reporter.lines == []


def test_alympics_gate_never_disturbs_the_preexisting_tau2_gate(monkeypatch) -> None:
    """The alympics-specific extension must be additive: an unrelated,
    already-required tau2 skip must still fail the run exactly as before,
    with no interference between the two families' policies."""
    monkeypatch.setenv("AEREAD_TAU2_BRIDGE_REQUIRED", "1")
    monkeypatch.delenv(ALYMPICS_ENV_VAR, raising=False)
    conftest = _load_conftest()
    reporter = _FakeTerminalReporter(
        [_FakeReport("upstream tau2-bench checkout not found at /some/path")]
    )
    config = _FakeConfig()

    conftest.pytest_terminal_summary(reporter, 0, config)

    assert reporter._session.exitstatus == 1
