"""Allow running pytest from a repo checkout without installing the package."""
import os
import sys
from pathlib import Path

import pytest

_src = Path(__file__).resolve().parent / "src"
if _src.is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))


# ---------------------------------------------------------------------------
# Codex-review finding 6 (amazonbarg): a missing upstream checkout must skip
# only the tests that actually need it, not every test in a
# `test_amazonbarg_*.py` module wholesale.
#
# Every one of the six `test_amazonbarg_*.py` files computed its own
# `UPSTREAM_ROOT` at *module import time* and called
# `pytest.skip(..., allow_module_level=True)` when the pinned checkout was
# missing -- which skips the whole module, including pure declaration/logic
# tests that never touch `upstream_root` at all (e.g.
# `test_amazonbarg_measurement.py`'s five `build_*_leaf` tests). A green run's
# "106/106 passed" headline figure then gave no signal that those numbers
# depended on one personal, absolute checkout path existing on the machine
# that ran them -- on any other machine the true count was "0 ran, N
# skipped," silently, with no failure.
#
# The fix: each of those six files' `_upstream_root()` no longer skips at
# import time (see each file for the updated helper); this hook skips
# individual, already-collected test items instead, at the *item* level, so
# only the tests that actually reference the upstream checkout are skipped --
# a test opts out of this by carrying the `no_upstream_checkout_required`
# marker, applied only to tests independently verified to need no real
# upstream bytes.
# ---------------------------------------------------------------------------

_AMAZONBARG_UPSTREAM_ENV_VAR = "AEREAD_AMAZONBARG_UPSTREAM_ROOT"
_AMAZONBARG_UPSTREAM_DEFAULT = "/Users/sunzeyu/Documents/econ benchmark/upstream-amazonbarg"
_AMAZONBARG_UPSTREAM_MARKER = ("data", "AmazonHistoryPrice", "home-kitchen.json")
_AMAZONBARG_NO_UPSTREAM_MARKER = "no_upstream_checkout_required"


def _amazonbarg_upstream_root() -> Path:
    return Path(os.environ.get(_AMAZONBARG_UPSTREAM_ENV_VAR, _AMAZONBARG_UPSTREAM_DEFAULT))


def _amazonbarg_upstream_available() -> bool:
    marker = _amazonbarg_upstream_root()
    for part in _AMAZONBARG_UPSTREAM_MARKER:
        marker = marker / part
    return marker.is_file()


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        f"{_AMAZONBARG_NO_UPSTREAM_MARKER}: "
        "this amazonbarg test needs no real upstream checkout bytes, so it "
        "must still run even when AEREAD_AMAZONBARG_UPSTREAM_ROOT is missing.",
    )


def pytest_collection_modifyitems(config, items):
    if _amazonbarg_upstream_available():
        return
    reason = (
        "pinned upstream AmazonPriceHistory checkout not found at "
        f"{_amazonbarg_upstream_root()} (set {_AMAZONBARG_UPSTREAM_ENV_VAR})"
    )
    skip_marker = pytest.mark.skip(reason=reason)
    for item in items:
        if "test_amazonbarg_" not in item.fspath.basename:
            continue
        if item.get_closest_marker(_AMAZONBARG_NO_UPSTREAM_MARKER) is not None:
            continue
        item.add_marker(skip_marker)


_BRIDGE_REQUIRED_ENV_VAR = "AEREAD_TAU2_BRIDGE_REQUIRED"

# Both ways the upstream-fidelity tests can go unrun: no interpreter that can
# import upstream, and no upstream checkout to import. Matching only the first
# left the second silent, which is the same hole one level up.
_BRIDGE_SKIP_MARKERS = (
    "upstream tau2-bench Python interpreter",
    "upstream tau2-bench checkout not found",
)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Turn a missing upstream bridge from a silent skip into a failed run.

    The tau3 adapter's whole claim is that it reproduces upstream tau2-bench
    exactly. The tests that check that claim need an interpreter which can
    import the pinned upstream checkout, and when there isn't one they skip
    rather than fail -- which is correct for a contributor who is working on
    something else, and dangerous everywhere else: a green run then means
    "the fidelity tests didn't run", not "the adapter matches upstream".

    Setting ``AEREAD_TAU2_BRIDGE_REQUIRED=1`` (CI, and any run that is meant
    to certify fidelity) makes that skip an error instead. Off by default so
    it never surprises a local run.

    Provision the interpreter with ``tools/tau2_bridge/provision.sh``.
    """
    if os.environ.get(_BRIDGE_REQUIRED_ENV_VAR, "") not in {"1", "true", "yes"}:
        return

    skipped = terminalreporter.stats.get("skipped", [])
    bridge_skips = [
        report
        for report in skipped
        if any(
            marker in str(getattr(report, "longrepr", ""))
            for marker in _BRIDGE_SKIP_MARKERS
        )
    ]
    if not bridge_skips:
        return

    terminalreporter.write_sep("=", "upstream bridge required", red=True)
    terminalreporter.write_line(
        f"{len(bridge_skips)} upstream-fidelity test(s) skipped while "
        f"${_BRIDGE_REQUIRED_ENV_VAR} is set. Reported reasons:"
    )
    for reason in sorted({str(getattr(r, "longrepr", "")) for r in bridge_skips}):
        terminalreporter.write_line(f"  {reason}")
    terminalreporter.write_line(
        "Provide the pinned upstream checkout (AEREAD_TAU2_UPSTREAM_ROOT) and "
        "an interpreter for it (tools/tau2_bridge/provision.sh, then export "
        "$AEREAD_TAU2_BRIDGE_PYTHON), or unset "
        f"${_BRIDGE_REQUIRED_ENV_VAR} to allow skipping."
    )
    session = getattr(terminalreporter, "_session", None)
    if session is not None:
        session.exitstatus = 1
    config.option.__dict__.setdefault("_aeread_bridge_missing", True)
