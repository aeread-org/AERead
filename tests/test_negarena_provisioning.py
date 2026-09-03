"""Tests for ``tools/negarena_bridge/provision.sh``'s default upstream path.

docs/negarena_codex_triage.md Finding 5: from ``tools/negarena_bridge``, a
fixed-depth ``../../../..`` resolves correctly from a main checkout
(``AERead/tools/negarena_bridge``) but lands two levels too high from inside
a linked git worktree (``AERead/.worktrees/<name>/tools/negarena_bridge``),
so the default silently became a path that does not exist
(``AERead/upstream-negarena``) instead of the real sibling checkout
(``.../upstream-negarena``, next to ``AERead`` itself). Because a missing
default only prints a note and skips the import probe rather than failing,
an operator running the script from a worktree without setting
``AEREAD_NEGARENA_UPSTREAM_ROOT`` got a script that exited 0 and printed the
export instruction without ever verifying that upstream's game classes
import.

These tests exercise only the path-resolution logic
(``default_upstream_root``), via the script's own
``--print-default-upstream-root`` introspection flag -- never the full
provisioning run (which creates a venv and calls ``pip install``, i.e. the
network access this suite must stay free of).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROVISION_SCRIPT = REPO_ROOT / "tools" / "negarena_bridge" / "provision.sh"

# The convention every negarena test/doc in this repo already hardcodes as
# the real, pinned sibling checkout (e.g. test_negarena_harness.py's own
# ``AEREAD_NEGARENA_UPSTREAM_ROOT`` default).
DOCUMENTED_SIBLING_CHECKOUT = "/Users/sunzeyu/Documents/econ benchmark/upstream-negarena"


def _print_default_upstream_root(script: Path) -> str:
    result = subprocess.run(
        ["bash", str(script), "--print-default-upstream-root"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _copy_script(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(PROVISION_SCRIPT.read_bytes())
    destination.chmod(0o755)
    return destination


def test_default_upstream_root_matches_the_documented_sibling_checkout() -> None:
    """Run from this repo's own real location (a linked git worktree here),
    the default must resolve to the actual sibling checkout every other
    negarena test/doc already assumes -- not a nonexistent path two levels
    too high."""
    assert _print_default_upstream_root(PROVISION_SCRIPT) == DOCUMENTED_SIBLING_CHECKOUT


def test_default_upstream_root_agrees_between_a_main_checkout_and_a_worktree(
    tmp_path: Path,
) -> None:
    """The same script, copied into two synthetic layouts -- a main checkout
    (``AERead/tools/negarena_bridge``, 2 levels below ``AERead``) and a
    linked worktree (``AERead/.worktrees/<name>/tools/negarena_bridge``, 4
    levels below) -- must each resolve to ``upstream-negarena`` sitting next
    to *its own* ``AERead`` directory. A fixed-``..``-count computation
    (the pre-fix script) cannot satisfy both depths from one script; walking
    up to the ancestor literally named "AERead" does, regardless of depth."""
    main_root = tmp_path / "main"
    worktree_root = tmp_path / "worktree"
    main_checkout_script = _copy_script(
        main_root / "AERead" / "tools" / "negarena_bridge" / "provision.sh"
    )
    worktree_script = _copy_script(
        worktree_root
        / "AERead"
        / ".worktrees"
        / "some-family"
        / "tools"
        / "negarena_bridge"
        / "provision.sh"
    )

    main_default = _print_default_upstream_root(main_checkout_script)
    worktree_default = _print_default_upstream_root(worktree_script)

    assert main_default == str(main_root / "upstream-negarena")
    assert worktree_default == str(worktree_root / "upstream-negarena")
