"""Allow running pytest from a repo checkout without installing the package."""
import os
import sys
from dataclasses import dataclass
from pathlib import Path

_src = Path(__file__).resolve().parent / "src"
if _src.is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))


@dataclass(frozen=True)
class _BridgeRequirement:
    """One family's "no faked fidelity" enforcement declaration.

    ``env_var``, when set to a truthy value, turns that family's own
    missing-upstream-bridge skips into a failed run (see
    ``pytest_terminal_summary``'s own docstring below). ``skip_markers`` are
    substrings of that family's own skip messages -- both ways its fidelity
    tests can go unrun: no interpreter that can import upstream, and no
    upstream checkout to import.
    """

    family: str
    env_var: str
    skip_markers: tuple[str, ...]
    provision_hint: str


# Each family that declares upstream-fidelity tests registers its own
# requirement here -- adding a new family's enforcement is a new tuple
# entry, never a change to the matching/failing logic below (docs/
# econagent_codex_triage.md finding 5: this used to recognize only tau2's
# own env var and skip markers, so setting econagent's requirement flag
# with no usable interpreter still produced a silent, zero-exit skip).
_BRIDGE_REQUIREMENTS = (
    _BridgeRequirement(
        family="tau2-bench (tau3_retail adapter)",
        env_var="AEREAD_TAU2_BRIDGE_REQUIRED",
        skip_markers=(
            "upstream tau2-bench Python interpreter",
            "upstream tau2-bench checkout not found",
        ),
        provision_hint=(
            "Provide the pinned upstream checkout (AEREAD_TAU2_UPSTREAM_ROOT) and "
            "an interpreter for it (tools/tau2_bridge/provision.sh, then export "
            "$AEREAD_TAU2_BRIDGE_PYTHON)."
        ),
    ),
    _BridgeRequirement(
        family="EconAgent (econagent_v1 adapter)",
        env_var="AEREAD_ECONAGENT_BRIDGE_REQUIRED",
        skip_markers=(
            "pinned upstream EconAgent Python interpreter",
            "pinned upstream EconAgent checkout not found",
        ),
        provision_hint=(
            "Provide the pinned upstream checkout (AEREAD_ECONAGENT_UPSTREAM_ROOT) "
            "and an interpreter for it (tools/econagent_bridge/provision.sh, then "
            "export $AEREAD_ECONAGENT_BRIDGE_PYTHON)."
        ),
    ),
)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Turn a missing upstream bridge from a silent skip into a failed run.

    Each adapter's whole claim is that it reproduces its own pinned upstream
    engine exactly. The tests that check that claim need an interpreter
    which can import the pinned upstream checkout, and when there isn't one
    they skip rather than fail -- which is correct for a contributor who is
    working on something else, and dangerous everywhere else: a green run
    then means "the fidelity tests didn't run", not "the adapter matches
    upstream".

    Setting a family's own ``*_BRIDGE_REQUIRED=1`` (see ``_BRIDGE_REQUIREMENTS``
    above; CI, and any run that is meant to certify fidelity) makes that
    family's own missing-bridge skips an error instead. Off by default so it
    never surprises a local run. Every declared family is checked
    independently -- setting one family's flag never masks, nor is masked
    by, another family's own skips.
    """
    skipped = terminalreporter.stats.get("skipped", [])
    any_required_missing = False
    for requirement in _BRIDGE_REQUIREMENTS:
        if os.environ.get(requirement.env_var, "") not in {"1", "true", "yes"}:
            continue
        bridge_skips = [
            report
            for report in skipped
            if any(
                marker in str(getattr(report, "longrepr", ""))
                for marker in requirement.skip_markers
            )
        ]
        if not bridge_skips:
            continue
        any_required_missing = True
        terminalreporter.write_sep("=", "upstream bridge required", red=True)
        terminalreporter.write_line(
            f"{len(bridge_skips)} {requirement.family} upstream-fidelity test(s) "
            f"skipped while ${requirement.env_var} is set. Reported reasons:"
        )
        for reason in sorted({str(getattr(r, "longrepr", "")) for r in bridge_skips}):
            terminalreporter.write_line(f"  {reason}")
        terminalreporter.write_line(requirement.provision_hint)
        terminalreporter.write_line(
            f"...or unset ${requirement.env_var} to allow skipping."
        )

    if not any_required_missing:
        return
    session = getattr(terminalreporter, "_session", None)
    if session is not None:
        session.exitstatus = 1
    config.option.__dict__.setdefault("_aeread_bridge_missing", True)
