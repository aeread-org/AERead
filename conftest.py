"""Allow running pytest from a repo checkout without installing the package."""
import os
import sys
from pathlib import Path

_src = Path(__file__).resolve().parent / "src"
if _src.is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))


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
