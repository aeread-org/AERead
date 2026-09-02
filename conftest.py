"""Allow running pytest from a repo checkout without installing the package."""
import os
import sys
from pathlib import Path

_src = Path(__file__).resolve().parent / "src"
if _src.is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))


# One entry per family whose fidelity claim depends on an upstream bridge
# interpreter: (required-env-var, provisioning hint, skip-message markers).
# Both ways a bridge-gated test can go unrun belong in one family's markers
# tuple: no interpreter that can import upstream, and (where applicable) no
# upstream checkout to import at all. Matching only the first left the
# second silent, which is the same hole one level up.
_BRIDGE_FAMILIES = (
    (
        "AEREAD_TAU2_BRIDGE_REQUIRED",
        "Provide the pinned upstream checkout (AEREAD_TAU2_UPSTREAM_ROOT) and "
        "an interpreter for it (tools/tau2_bridge/provision.sh, then export "
        "$AEREAD_TAU2_BRIDGE_PYTHON), or unset $AEREAD_TAU2_BRIDGE_REQUIRED to "
        "allow skipping.",
        (
            "upstream tau2-bench Python interpreter",
            "upstream tau2-bench checkout not found",
        ),
    ),
    (
        "AEREAD_ECONEVALS_BRIDGE_REQUIRED",
        "Provision the bridge interpreter (tools/econevals_bridge/provision.sh, "
        "then export $AEREAD_ECONEVALS_BRIDGE_PYTHON), or unset "
        "$AEREAD_ECONEVALS_BRIDGE_REQUIRED to allow skipping.",
        ("pinned upstream econ-evals Python interpreter",),
    ),
)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Turn a missing upstream bridge from a silent skip into a failed run.

    Some adapters' whole claim is that they reproduce a pinned upstream
    exactly. The tests that check that claim need an interpreter which can
    import the pinned upstream checkout, and when there isn't one they skip
    rather than fail -- which is correct for a contributor who is working on
    something else, and dangerous everywhere else: a green run then means
    "the fidelity tests didn't run", not "the adapter matches upstream".

    Setting the family's own ``..._BRIDGE_REQUIRED=1`` (CI, and any run that
    is meant to certify fidelity) makes that family's bridge-gated skips an
    error instead. Off by default so it never surprises a local run.
    """
    del exitstatus
    skipped = terminalreporter.stats.get("skipped", [])
    for env_var, hint, markers in _BRIDGE_FAMILIES:
        if os.environ.get(env_var, "") not in {"1", "true", "yes"}:
            continue
        bridge_skips = [
            report
            for report in skipped
            if any(marker in str(getattr(report, "longrepr", "")) for marker in markers)
        ]
        if not bridge_skips:
            continue

        terminalreporter.write_sep("=", "upstream bridge required", red=True)
        terminalreporter.write_line(
            f"{len(bridge_skips)} upstream-fidelity test(s) skipped while "
            f"${env_var} is set. Reported reasons:"
        )
        for reason in sorted({str(getattr(r, "longrepr", "")) for r in bridge_skips}):
            terminalreporter.write_line(f"  {reason}")
        terminalreporter.write_line(hint)
        session = getattr(terminalreporter, "_session", None)
        if session is not None:
            session.exitstatus = 1
        config.option.__dict__.setdefault("_aeread_bridge_missing", True)
