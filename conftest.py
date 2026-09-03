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

_AUCARENA_QC_GATE_REQUIRED_ENV_VAR = "AEREAD_AUCARENA_QC_GATE_REQUIRED"

# tests/test_aucarena_cases.py's own module-level pytest.skip(...,
# allow_module_level=True): a missing pinned upstream auction-arena checkout
# collapses all 19 QC-Gate-1 tests in that module into a single silent
# "1 skipped" line with zero further signal
# (docs/aucarena_codex_triage.md Finding 8) -- the exact same shape of hole
# this gate mechanism already closes for tau2, generalized here instead of
# duplicated.
_AUCARENA_QC_GATE_SKIP_MARKERS = (
    "pinned upstream auction-arena checkout not found",
)

# One (required-env-var, skip-message markers, section title, provisioning
# hint) tuple per upstream-checkout gate this repo has. Add a row here, not a
# second copy of ``pytest_terminal_summary``, for the next family that needs
# one.
_REQUIRED_SKIP_GATES = (
    {
        "env_var": _BRIDGE_REQUIRED_ENV_VAR,
        "markers": _BRIDGE_SKIP_MARKERS,
        "title": "upstream bridge required",
        "hint": (
            "Provide the pinned upstream checkout (AEREAD_TAU2_UPSTREAM_ROOT) and "
            "an interpreter for it (tools/tau2_bridge/provision.sh, then export "
            "$AEREAD_TAU2_BRIDGE_PYTHON), or unset "
            f"${_BRIDGE_REQUIRED_ENV_VAR} to allow skipping."
        ),
    },
    {
        "env_var": _AUCARENA_QC_GATE_REQUIRED_ENV_VAR,
        "markers": _AUCARENA_QC_GATE_SKIP_MARKERS,
        "title": "upstream auction-arena QC gate required",
        "hint": (
            "Provide the pinned upstream auction-arena checkout "
            "(AEREAD_AUCARENA_UPSTREAM_ROOT), or unset "
            f"${_AUCARENA_QC_GATE_REQUIRED_ENV_VAR} to allow skipping."
        ),
    },
)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Turn a missing pinned-upstream-checkout skip into a failed run, and
    -- unconditionally, regardless of that opt-in -- make sure it is never
    silent in the first place.

    Some adapters' whole claim is that they reproduce a pinned upstream
    exactly; the tests that check that claim need a checkout (and sometimes
    an interpreter) this repo does not ship, and when it's absent they skip
    rather than fail -- correct for a contributor working on something else,
    and dangerous everywhere else: a green run then means "the fidelity
    tests didn't run", not "the adapter matches upstream". Worse still when
    the skip is a module-level ``pytest.skip(..., allow_module_level=True)``
    (``tests/test_aucarena_cases.py``): every test in that module collapses
    into one generic skip line, hiding however many distinct claims it made
    (``docs/aucarena_codex_triage.md`` Finding 8).

    Each row in ``_REQUIRED_SKIP_GATES`` gets its own required-env-var: set
    it (CI, and any run meant to certify fidelity) to turn a matching skip
    into a hard failure with the reasons and a provisioning hint printed.
    Off by default so it never surprises a local run.

    That opt-in alone was not enough (independent cross-model verification,
    ``docs/aucarena_fix_verification.md``): nothing in this repo's own
    ``.github/workflows/ci.yml`` sets any of these env vars, so an ordinary
    default run -- exactly what every contributor and every CI job actually
    does -- stayed completely silent about every one of these gates,
    identical to the pre-gate behavior. So a matching skip is now always
    reported, even when the gate is not required: only the *exit status*
    stays untouched by default (a local contributor not working on this
    family must never see a failure), never the *visibility*.
    """
    session = getattr(terminalreporter, "_session", None)
    skipped = terminalreporter.stats.get("skipped", [])
    any_required_gate_missing = False

    for gate in _REQUIRED_SKIP_GATES:
        gate_skips = [
            report
            for report in skipped
            if any(
                marker in str(getattr(report, "longrepr", ""))
                for marker in gate["markers"]
            )
        ]
        if not gate_skips:
            continue

        reasons = sorted({str(getattr(r, "longrepr", "")) for r in gate_skips})
        required = os.environ.get(gate["env_var"], "") in {"1", "true", "yes"}

        if not required:
            terminalreporter.write_sep("-", f"{gate['title']} (not enforced)")
            terminalreporter.write_line(
                f"{len(gate_skips)} test(s)/module(s) skipped because "
                f"${gate['env_var']} is unset. Reported reasons:"
            )
            for reason in reasons:
                terminalreporter.write_line(f"  {reason}")
            terminalreporter.write_line(
                f"Set ${gate['env_var']}=1 to turn this into a failed run instead."
            )
            continue

        any_required_gate_missing = True
        terminalreporter.write_sep("=", gate["title"], red=True)
        terminalreporter.write_line(
            f"{len(gate_skips)} test(s)/module(s) skipped while "
            f"${gate['env_var']} is set. Reported reasons:"
        )
        for reason in reasons:
            terminalreporter.write_line(f"  {reason}")
        terminalreporter.write_line(gate["hint"])

    if not any_required_gate_missing:
        return
    if session is not None:
        session.exitstatus = 1
    config.option.__dict__.setdefault("_aeread_bridge_missing", True)
