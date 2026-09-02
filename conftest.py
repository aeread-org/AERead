"""Allow running pytest from a repo checkout without installing the package."""
import os
import sys
from dataclasses import dataclass
from pathlib import Path

_src = Path(__file__).resolve().parent / "src"
if _src.is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))


@dataclass(frozen=True)
class _UpstreamRequiredPolicy:
    """One family's own "skip must not silently hide unrun fidelity tests" gate.

    Setting ``env_var`` (CI, and any run meant to certify fidelity) turns a
    matching skip into a failed run instead of a silent one. Off by default
    so it never surprises a local contributor working on something else.
    """

    name: str
    env_var: str
    skip_markers: tuple[str, ...]
    provision_hint: str


_UPSTREAM_REQUIRED_POLICIES = (
    _UpstreamRequiredPolicy(
        name="tau2/tau3",
        env_var="AEREAD_TAU2_BRIDGE_REQUIRED",
        # Both ways the upstream-fidelity tests can go unrun: no interpreter
        # that can import upstream, and no upstream checkout to import.
        # Matching only the first left the second silent, which is the same
        # hole one level up.
        skip_markers=(
            "upstream tau2-bench Python interpreter",
            "upstream tau2-bench checkout not found",
        ),
        provision_hint=(
            "Provide the pinned upstream checkout (AEREAD_TAU2_UPSTREAM_ROOT) and "
            "an interpreter for it (tools/tau2_bridge/provision.sh, then export "
            "$AEREAD_TAU2_BRIDGE_PYTHON), or unset $AEREAD_TAU2_BRIDGE_REQUIRED to "
            "allow skipping."
        ),
    ),
    _UpstreamRequiredPolicy(
        name="alympics.wac",
        env_var="AEREAD_ALYMPICS_UPSTREAM_REQUIRED",
        # Codex triage finding 9 (docs/alympics_codex_triage.md): every one
        # of this family's environment/measurement/harness/parity/replay
        # test modules skips, module-level, whenever the pinned upstream
        # Alympics checkout is absent (each test file's own
        # ``_upstream_root()`` helper), and this project's CI workflow
        # provisions neither the checkout nor an env var to require it -- so
        # a green CI run for this family previously proved only that
        # ``test_alympics_wac_cases.py``'s upstream-free tests ran.
        skip_markers=("pinned upstream Alympics checkout not found",),
        provision_hint=(
            "Provide the pinned upstream Alympics checkout at the path named in "
            "the skip reason, or export AEREAD_ALYMPICS_UPSTREAM_ROOT to point at "
            "one, or unset $AEREAD_ALYMPICS_UPSTREAM_REQUIRED to allow skipping."
        ),
    ),
)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Turn a missing pinned upstream from a silent skip into a failed run.

    Several families' whole claim is that they reproduce a pinned upstream
    exactly. The tests that check that claim need the pinned upstream
    checkout (and, for tau2/tau3, an interpreter that can import it), and
    when it is missing they skip rather than fail -- correct for a
    contributor working on something else, dangerous everywhere else: a
    green run then means "the fidelity tests didn't run", not "the adapter
    matches upstream". See ``_UPSTREAM_REQUIRED_POLICIES`` for each family's
    own opt-in env var and provisioning hint.
    """
    skipped = terminalreporter.stats.get("skipped", [])
    any_required = False
    for policy in _UPSTREAM_REQUIRED_POLICIES:
        if os.environ.get(policy.env_var, "") not in {"1", "true", "yes"}:
            continue
        matches = [
            report
            for report in skipped
            if any(
                marker in str(getattr(report, "longrepr", ""))
                for marker in policy.skip_markers
            )
        ]
        if not matches:
            continue
        any_required = True

        terminalreporter.write_sep("=", f"upstream required: {policy.name}", red=True)
        terminalreporter.write_line(
            f"{len(matches)} upstream-fidelity test(s) skipped while "
            f"${policy.env_var} is set. Reported reasons:"
        )
        for reason in sorted({str(getattr(r, "longrepr", "")) for r in matches}):
            terminalreporter.write_line(f"  {reason}")
        terminalreporter.write_line(policy.provision_hint)

    if not any_required:
        return
    session = getattr(terminalreporter, "_session", None)
    if session is not None:
        session.exitstatus = 1
    config.option.__dict__.setdefault("_aeread_bridge_missing", True)
