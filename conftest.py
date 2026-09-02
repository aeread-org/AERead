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

# One (require-env-var, skip-reason markers) pair per family adapter that
# bridges to a pinned upstream checkout across a subprocess. Each entry
# follows tau3_retail's original convention exactly -- see that family's
# entry above and tools/<family>_bridge/provision.sh for the interpreter
# each one names.
_BRIDGE_CONFIGS = (
    (_BRIDGE_REQUIRED_ENV_VAR, _BRIDGE_SKIP_MARKERS),
    (
        "AEREAD_AGENTICPAY_BRIDGE_REQUIRED",
        (
            "upstream AgenticPay Python interpreter",
            "upstream AgenticPay checkout not found",
        ),
    ),
)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Turn a missing upstream bridge from a silent skip into a failed run.

    Each bridged family adapter's whole claim is that it reproduces its
    pinned upstream exactly. The tests that check that claim need an
    interpreter which can import the pinned upstream checkout, and when
    there isn't one they skip rather than fail -- which is correct for a
    contributor who is working on something else, and dangerous everywhere
    else: a green run then means "the fidelity tests didn't run", not "the
    adapter matches upstream".

    Setting the matching ``AEREAD_<FAMILY>_BRIDGE_REQUIRED=1`` (CI, and any
    run that is meant to certify fidelity) makes that family's skip an error
    instead. Off by default so it never surprises a local run.

    Provision each interpreter with its own ``tools/<family>_bridge/
    provision.sh``.
    """
    any_required = any(
        os.environ.get(env_var, "") in {"1", "true", "yes"}
        for env_var, _markers in _BRIDGE_CONFIGS
    )
    if not any_required:
        return

    skipped = terminalreporter.stats.get("skipped", [])
    any_missing = False
    for env_var, markers in _BRIDGE_CONFIGS:
        if os.environ.get(env_var, "") not in {"1", "true", "yes"}:
            continue
        bridge_skips = [
            report
            for report in skipped
            if any(marker in str(getattr(report, "longrepr", "")) for marker in markers)
        ]
        if not bridge_skips:
            continue
        any_missing = True
        terminalreporter.write_sep("=", f"{env_var} required", red=True)
        terminalreporter.write_line(
            f"{len(bridge_skips)} upstream-fidelity test(s) skipped while "
            f"${env_var} is set. Reported reasons:"
        )
        for reason in sorted({str(getattr(r, "longrepr", "")) for r in bridge_skips}):
            terminalreporter.write_line(f"  {reason}")
        terminalreporter.write_line(f"Unset ${env_var} to allow skipping, or provision that bridge.")

    if not any_missing:
        return
    session = getattr(terminalreporter, "_session", None)
    if session is not None:
        session.exitstatus = 1
    config.option.__dict__.setdefault("_aeread_bridge_missing", True)
