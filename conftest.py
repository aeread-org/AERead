"""Allow running pytest from a repo checkout without installing the package."""
import os
import sys
from pathlib import Path

import pytest

_src = Path(__file__).resolve().parent / "src"
if _src.is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))


# One entry per family whose fidelity claim depends on an out-of-repo upstream
# fixture (a pinned checkout, a bridge interpreter, a built cache):
# (required-env-var, provisioning hint, skip-message markers). Both ways a
# gated test can go unrun belong in one family's markers tuple: no interpreter
# that can import upstream, and (where applicable) no upstream checkout at all.
_BRIDGE_FAMILIES = (
    (
        "AEREAD_TAU2_BRIDGE_REQUIRED",
        (
            "Provide the pinned upstream checkout (AEREAD_TAU2_UPSTREAM_ROOT) and "
            "an interpreter for it (tools/tau2_bridge/provision.sh, then export "
            "$AEREAD_TAU2_BRIDGE_PYTHON), or unset $AEREAD_TAU2_BRIDGE_REQUIRED to "
            "allow skipping."
        ),
        (
            "upstream tau2-bench Python interpreter",
            "upstream tau2-bench checkout not found",
        ),
    ),
    (
        "AEREAD_ECONEVALS_BRIDGE_REQUIRED",
        (
            "Provision the bridge interpreter (tools/econevals_bridge/provision.sh, "
            "then export $AEREAD_ECONEVALS_BRIDGE_PYTHON) and the pinned upstream "
            "checkout (set $AEREAD_ECONEVALS_UPSTREAM_ROOT if it is not at the "
            "default path), or unset $AEREAD_ECONEVALS_BRIDGE_REQUIRED to allow "
            "skipping."
        ),
        (
            "pinned upstream econ-evals Python interpreter",
            "pinned upstream econ-evals checkout not found",
        ),
    ),
    (
        "AEREAD_STEER_FIXTURES_REQUIRED",
        (
            "Build the flattened cache (src/aeread_families/steer/cases.py, "
            "AEREAD_STEER_DATA_ROOT), and for test_steer_cases.py specifically "
            "provide the pinned upstream checkout (AEREAD_STEER_UPSTREAM_ROOT) "
            "and a pandas-capable interpreter (tools/steer_bridge/provision.sh, "
            "then export $AEREAD_STEER_BRIDGE_PYTHON), or unset "
            "$AEREAD_STEER_FIXTURES_REQUIRED to allow skipping."
        ),
        (
            "flattened cache not built yet at",
            "pinned upstream STEER checkout not found at",
            "cached STEER corpus bytes not found at",
            "no pandas-capable Python interpreter found for the steer bridge",
        ),
    ),
    (
        "AEREAD_AUCARENA_QC_GATE_REQUIRED",
        (
            "Provide the pinned upstream auction-arena checkout "
            "(AEREAD_AUCARENA_UPSTREAM_ROOT), or unset "
            "$AEREAD_AUCARENA_QC_GATE_REQUIRED to allow skipping."
        ),
        ("pinned upstream auction-arena checkout not found",),
    ),
    (
        "AEREAD_AGENTICPAY_BRIDGE_REQUIRED",
        (
            "Provision the bridge interpreter (tools/agenticpay_bridge/provision.sh, "
            "then export $AEREAD_AGENTICPAY_BRIDGE_PYTHON) and the pinned upstream "
            "checkout, or unset $AEREAD_AGENTICPAY_BRIDGE_REQUIRED to allow skipping."
        ),
        (
            "upstream AgenticPay Python interpreter",
            "upstream AgenticPay checkout not found",
        ),
    ),
    (
        "AEREAD_ALYMPICS_UPSTREAM_REQUIRED",
        (
            "Provide the pinned upstream Alympics checkout at the path named in "
            "the skip reason, or export AEREAD_ALYMPICS_UPSTREAM_ROOT to point at "
            "one, or unset $AEREAD_ALYMPICS_UPSTREAM_REQUIRED to allow skipping."
        ),
        ("pinned upstream Alympics checkout not found",),
    ),
    (
        "AEREAD_ECONAGENT_BRIDGE_REQUIRED",
        (
            "Provide the pinned upstream checkout (AEREAD_ECONAGENT_UPSTREAM_ROOT) "
            "and an interpreter for it (tools/econagent_bridge/provision.sh, then "
            "export $AEREAD_ECONAGENT_BRIDGE_PYTHON), or unset "
            "$AEREAD_ECONAGENT_BRIDGE_REQUIRED to allow skipping."
        ),
        (
            "pinned upstream EconAgent Python interpreter",
            "pinned upstream EconAgent checkout not found",
        ),
    ),
    (
        "AEREAD_NEGARENA_BRIDGE_REQUIRED",
        (
            "Provide the pinned upstream checkout (AEREAD_NEGARENA_UPSTREAM_ROOT) "
            "and an interpreter for it (tools/negarena_bridge/provision.sh, then "
            "export $AEREAD_NEGARENA_BRIDGE_PYTHON), or unset "
            "$AEREAD_NEGARENA_BRIDGE_REQUIRED to allow skipping."
        ),
        (
            "upstream NegotiationArena Python interpreter unavailable",
            "pinned upstream NegotiationArena checkout not found",
        ),
    ),
)


# Per-family display: summary title, human family name, and whether a matching
# skip is reported even when the family's env var is unset (exit status untouched).
_BRIDGE_FAMILY_DISPLAY = {
    "AEREAD_TAU2_BRIDGE_REQUIRED": {"family": "tau2-bench (tau3_retail adapter)", "title": "upstream bridge required: tau2-bench (tau3_retail adapter)", "note_when_unenforced": False},
    "AEREAD_ECONEVALS_BRIDGE_REQUIRED": {"family": "econ-evals (econevals adapter)", "title": "upstream bridge required: econ-evals (econevals adapter)", "note_when_unenforced": False},
    "AEREAD_STEER_FIXTURES_REQUIRED": {"family": "STEER (steer adapter)", "title": "steer fixtures required", "note_when_unenforced": False},
    "AEREAD_AUCARENA_QC_GATE_REQUIRED": {"family": "auction-arena (aucarena adapter)", "title": "upstream auction-arena QC gate required", "note_when_unenforced": True},
    "AEREAD_AGENTICPAY_BRIDGE_REQUIRED": {"family": "AgenticPay (agenticpay_bilateral adapter)", "title": "upstream bridge required: AgenticPay (agenticpay_bilateral adapter)", "note_when_unenforced": False},
    "AEREAD_ALYMPICS_UPSTREAM_REQUIRED": {"family": "Alympics (alympics.wac adapter)", "title": "upstream required: alympics.wac", "note_when_unenforced": False},
    "AEREAD_ECONAGENT_BRIDGE_REQUIRED": {"family": "EconAgent (econagent_v1 adapter)", "title": "upstream bridge required: EconAgent (econagent_v1 adapter)", "note_when_unenforced": False},
    "AEREAD_NEGARENA_BRIDGE_REQUIRED": {"family": "NegotiationArena (negarena adapter)", "title": "upstream bridge required: NegotiationArena (negarena adapter)", "note_when_unenforced": False},
}


def _truthy(env_var: str) -> bool:
    return os.environ.get(env_var, "") in {"1", "true", "yes"}


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Turn a missing upstream fixture from a silent skip into a failed run.

    Each adapter's whole claim is that it reproduces its own pinned upstream
    exactly. The tests that check that claim need out-of-repo fixtures, and
    when one is missing they skip rather than fail -- correct for a contributor
    working on something else, dangerous everywhere else: a green run then
    means "the fidelity tests didn't run", not "the adapter matches upstream".

    Setting a family's own required env var (see ``_BRIDGE_FAMILIES``; CI, and
    any run meant to certify fidelity) makes that family's own gated skips an
    error instead, with the reasons and a provisioning hint printed. Off by
    default so it never surprises a local run. Every family is checked
    independently: one family's flag never masks, nor is masked by, another's.
    Families that opt into ``note_when_unenforced`` print a visible note even
    when their flag is unset; the exit status is never changed by a note.
    """
    del exitstatus
    skipped = terminalreporter.stats.get("skipped", [])
    any_required_missing = False
    for env_var, hint, markers in _BRIDGE_FAMILIES:
        family = {
            "env_var": env_var,
            "hint": hint,
            "title": "upstream bridge required",
            "family": env_var,
            "note_when_unenforced": False,
            **_BRIDGE_FAMILY_DISPLAY.get(env_var, {}),
        }
        matches = [
            report
            for report in skipped
            if any(marker in str(getattr(report, "longrepr", "")) for marker in markers)
        ]
        if not matches:
            continue
        reasons = sorted({str(getattr(r, "longrepr", "")) for r in matches})
        if not _truthy(family["env_var"]):
            if family["note_when_unenforced"]:
                terminalreporter.write_sep("-", f"{family['title']} (not enforced)")
                terminalreporter.write_line(
                    f"{len(matches)} test(s)/module(s) skipped because "
                    f"${family['env_var']} is unset. Reported reasons:"
                )
                for reason in reasons:
                    terminalreporter.write_line(f"  {reason}")
                terminalreporter.write_line(
                    f"Set ${family['env_var']}=1 to turn this into a failed run instead."
                )
            continue
        any_required_missing = True
        terminalreporter.write_sep("=", family["title"], red=True)
        terminalreporter.write_line(
            f"{len(matches)} {family['family']} upstream-fidelity test(s) skipped "
            f"while ${family['env_var']} is set. Reported reasons:"
        )
        for reason in reasons:
            terminalreporter.write_line(f"  {reason}")
        terminalreporter.write_line(family["hint"])
    if not any_required_missing:
        return
    session = getattr(terminalreporter, "_session", None)
    if session is not None:
        session.exitstatus = 1
    option = getattr(config, "option", None)
    if option is not None:
        option.__dict__.setdefault("_aeread_bridge_missing", True)


# amazonbarg: its fidelity tests need real upstream AmazonHistoryPrice bytes.
# Tests marked ``no_upstream_checkout_required`` run regardless; the rest skip
# with a reason naming the missing path when the checkout is absent.
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
