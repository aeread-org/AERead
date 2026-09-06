"""Tests for the repo-root ``conftest.py``'s upstream-required skip-to-
failure gate, scoped to negarena's own policy entry.

kernel_scoring_contract_spec.md migration milestone 3 (mirrors govsim's
identical fix, ``docs/govsim_migration_review.md`` finding 1): negarena's
scoring-contract behavioral test, ``test_negarena_obeys_the_scoring_
contract`` (``tests/test_shared_runner_scoring_contract.py``), and every
other bridge-gated negarena test (``tests/test_negarena_environment.py``,
``test_negarena_measurement.py``, ``test_negarena_kernel_finalizer.py``,
...) skip -- per-test, never module-level -- whenever the pinned upstream
NegotiationArena checkout or bridge interpreter is unavailable
(``tests/test_shared_runner_scoring_contract.py``'s own ``_negarena_bridge()``).
Meanwhile ``test_every_registered_family_obeys_the_scoring_contract``'s
closed-world catalog closure counts ``("negarena", "0.1.0")`` as enrolled
unconditionally via ``_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS``, regardless
of whether the bridge-gated behavioral test actually ran. A plain CI run
can therefore go green while negarena's returned leaf set, provenance,
determinism, and terminal-state scope were never checked at all.

This mirrors the project's own already-established fix for the identical
shape of problem in tau2/econevals/agenticpay/alympics/econagent/govsim
(see ``conftest.py``'s ``pytest_terminal_summary``, predating this family):
setting a dedicated, opt-in env var turns a matching skip into a failed
run instead of a silent one, off by default so it never surprises a local
contributor.

These tests call the real ``conftest.pytest_terminal_summary`` function --
loaded directly from the repo-root file, never reimplemented -- against
hand-built stand-ins for pytest's own ``terminalreporter``/``config``
objects, mirroring ``tests/test_govsim_bridge_required_gate.py``'s own
style (the migration reference): the *production* hook function, driven by
realistic fake inputs, not a shortcut re-implementation of its logic.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

_CONFTEST_PATH = Path(__file__).resolve().parents[1] / "conftest.py"

NEGARENA_ENV_VAR = "AEREAD_NEGARENA_BRIDGE_REQUIRED"
NEGARENA_CHECKOUT_SKIP_TEXT = "pinned upstream NegotiationArena checkout not found"
NEGARENA_INTERPRETER_SKIP_TEXT = "upstream NegotiationArena Python interpreter unavailable"


def _load_conftest():
    spec = importlib.util.spec_from_file_location("_negarena_test_root_conftest", _CONFTEST_PATH)
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


def test_negarena_checkout_skip_stays_silent_without_the_required_env_var(monkeypatch) -> None:
    monkeypatch.delenv(NEGARENA_ENV_VAR, raising=False)
    conftest = _load_conftest()
    reporter = _FakeTerminalReporter([_FakeReport(NEGARENA_CHECKOUT_SKIP_TEXT)])
    config = _FakeConfig()

    conftest.pytest_terminal_summary(reporter, 0, config)

    assert reporter._session.exitstatus == 0
    assert reporter.lines == []
    assert reporter.seps == []


def test_negarena_checkout_skip_fails_the_run_when_required(monkeypatch) -> None:
    monkeypatch.setenv(NEGARENA_ENV_VAR, "1")
    conftest = _load_conftest()
    reporter = _FakeTerminalReporter([_FakeReport(NEGARENA_CHECKOUT_SKIP_TEXT)])
    config = _FakeConfig()

    conftest.pytest_terminal_summary(reporter, 0, config)

    assert reporter._session.exitstatus == 1
    assert any("negarena" in title.lower() for title in reporter.seps)
    assert any(NEGARENA_CHECKOUT_SKIP_TEXT in line for line in reporter.lines)


def test_negarena_missing_interpreter_skip_fails_the_run_when_required(monkeypatch) -> None:
    """The bridge interpreter marker is a distinct failure mode from the
    missing-checkout marker (``NegarenaBridge.discover``/
    ``discover_bridge_python`` vs. the plain checkout-directory check) --
    both must be caught."""
    monkeypatch.setenv(NEGARENA_ENV_VAR, "1")
    conftest = _load_conftest()
    reporter = _FakeTerminalReporter([_FakeReport(NEGARENA_INTERPRETER_SKIP_TEXT)])
    config = _FakeConfig()

    conftest.pytest_terminal_summary(reporter, 0, config)

    assert reporter._session.exitstatus == 1
    assert any("negarena" in title.lower() for title in reporter.seps)
    assert any(NEGARENA_INTERPRETER_SKIP_TEXT in line for line in reporter.lines)


def test_unrelated_skips_never_trip_the_negarena_gate(monkeypatch) -> None:
    monkeypatch.setenv(NEGARENA_ENV_VAR, "1")
    conftest = _load_conftest()
    reporter = _FakeTerminalReporter([_FakeReport("some unrelated skip reason")])
    config = _FakeConfig()

    conftest.pytest_terminal_summary(reporter, 0, config)

    assert reporter._session.exitstatus == 0
    assert reporter.lines == []


def test_negarena_gate_never_disturbs_the_preexisting_tau2_gate(monkeypatch) -> None:
    """The negarena-specific extension must be additive: an unrelated,
    already-required tau2 skip must still fail the run exactly as before,
    with no interference between the two families' policies."""
    monkeypatch.setenv("AEREAD_TAU2_BRIDGE_REQUIRED", "1")
    monkeypatch.delenv(NEGARENA_ENV_VAR, raising=False)
    conftest = _load_conftest()
    reporter = _FakeTerminalReporter(
        [_FakeReport("upstream tau2-bench checkout not found at /some/path")]
    )
    config = _FakeConfig()

    conftest.pytest_terminal_summary(reporter, 0, config)

    assert reporter._session.exitstatus == 1


def test_tau2_gate_never_disturbs_the_negarena_gate(monkeypatch) -> None:
    """And the converse: an unrelated, already-required negarena skip must
    not be masked by tau2's own (unset) policy."""
    monkeypatch.setenv(NEGARENA_ENV_VAR, "1")
    monkeypatch.delenv("AEREAD_TAU2_BRIDGE_REQUIRED", raising=False)
    conftest = _load_conftest()
    reporter = _FakeTerminalReporter([_FakeReport(NEGARENA_CHECKOUT_SKIP_TEXT)])
    config = _FakeConfig()

    conftest.pytest_terminal_summary(reporter, 0, config)

    assert reporter._session.exitstatus == 1
