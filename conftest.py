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

_STEER_FIXTURES_REQUIRED_ENV_VAR = "AEREAD_STEER_FIXTURES_REQUIRED"

# Every way the whole steer test suite can go unrun without ever failing
# (docs/steer_codex_triage.md finding 5): the flattened cache 6 of the 7
# steer test modules module-level-skip on
# (test_steer_measurement.py/test_steer_goldens.py/test_steer_cases.py/
# test_steer_environment.py/test_steer_replay.py/test_steer_e2e.py), plus
# test_steer_cases.py's own two additional prerequisites -- the pinned
# upstream checkout and a pandas-capable bridge interpreter -- that only
# that one module needs. Reproduced empirically: pointing
# AEREAD_STEER_DATA_ROOT at a nonexistent directory and running the steer
# suite alongside any other passing test file gives "N passed, 6 skipped"
# at exit code 0 -- nothing in the pytest exit code reveals that steer's
# tests never ran at all.
_STEER_SKIP_MARKERS = (
    "flattened cache not built yet at",
    "pinned upstream STEER checkout not found at",
    "cached STEER corpus bytes not found at",
    "no pandas-capable Python interpreter found for the steer bridge",
)

# (env var, skip markers, what a green run without ${env var} actually means,
# how to provision what is missing)
_FIXTURE_REQUIRED_FAMILIES = (
    (
        _BRIDGE_REQUIRED_ENV_VAR,
        _BRIDGE_SKIP_MARKERS,
        "upstream-fidelity",
        "the tau3 adapter's whole claim is that it reproduces upstream "
        "tau2-bench exactly",
        "Provide the pinned upstream checkout (AEREAD_TAU2_UPSTREAM_ROOT) and "
        "an interpreter for it (tools/tau2_bridge/provision.sh, then export "
        "$AEREAD_TAU2_BRIDGE_PYTHON)",
    ),
    (
        _STEER_FIXTURES_REQUIRED_ENV_VAR,
        _STEER_SKIP_MARKERS,
        "steer",
        "the steer adapter's whole claim is that it reproduces upstream "
        "narunraman/STEER's pinned corpus and answer key",
        "Build the flattened cache (src/aeread_families/steer/cases.py, "
        "AEREAD_STEER_DATA_ROOT), and for test_steer_cases.py specifically "
        "provide the pinned upstream checkout (AEREAD_STEER_UPSTREAM_ROOT) "
        "and a pandas-capable interpreter (tools/steer_bridge/provision.sh, "
        "then export $AEREAD_STEER_BRIDGE_PYTHON)",
    ),
)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Turn a missing upstream fixture from a silent skip into a failed run.

    Each family's whole claim is that it reproduces a pinned upstream corpus.
    The tests that check that claim need real, out-of-repo fixtures (an
    upstream checkout, a matching interpreter, a built cache), and when one
    is missing they skip rather than fail -- correct for a contributor
    working on something else, and dangerous everywhere else: a green run
    then means "these tests didn't run", not "the adapter matches upstream".
    Reported skip reasons are matched by substring because skip messages
    embed the specific missing path.

    Setting the family's own required env var (CI, and any run meant to
    certify fidelity) makes that skip an error instead. Off by default so it
    never surprises a local run.
    """
    skipped = terminalreporter.stats.get("skipped", [])
    session = getattr(terminalreporter, "_session", None)
    for env_var, markers, label, stakes, provision_hint in _FIXTURE_REQUIRED_FAMILIES:
        if os.environ.get(env_var, "") not in {"1", "true", "yes"}:
            continue
        fixture_skips = [
            report
            for report in skipped
            if any(
                marker in str(getattr(report, "longrepr", "")) for marker in markers
            )
        ]
        if not fixture_skips:
            continue

        terminalreporter.write_sep("=", f"{label} fixtures required", red=True)
        terminalreporter.write_line(
            f"{len(fixture_skips)} {label} test(s) skipped while ${env_var} is "
            f"set ({stakes}). Reported reasons:"
        )
        for reason in sorted({str(getattr(r, "longrepr", "")) for r in fixture_skips}):
            terminalreporter.write_line(f"  {reason}")
        terminalreporter.write_line(
            f"{provision_hint}, or unset ${env_var} to allow skipping."
        )
        if session is not None:
            session.exitstatus = 1
        config.option.__dict__.setdefault(f"_aeread_{label}_fixtures_missing", True)
