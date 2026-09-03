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

docs/negarena_fix_verification.md points out that the tests above never
actually exercise the real provisioning use-site: the ``UPSTREAM_ROOT=...``
assignment the normal (non-flag) run performs, which is what really gates
the upstream import check. ``--print-default-upstream-root`` calls
``default_upstream_root`` directly and always ignores any
``AEREAD_NEGARENA_UPSTREAM_ROOT`` override, so reverting *only* the real
assignment (while leaving the helper function and that flag untouched)
left both tests above green while normal provisioning was broken again.
``--print-resolved-upstream-root`` (below) is not a second, separately
maintained copy of that logic -- ``provision.sh`` now computes
``UPSTREAM_ROOT`` exactly once, and this flag and the real provisioning run
both read that same variable, so a regression in the real assignment cannot
avoid being caught by a test that drives this flag.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROVISION_SCRIPT = REPO_ROOT / "tools" / "negarena_bridge" / "provision.sh"


def _ancestor_named(path: Path, name: str) -> Path:
    """Walk up from ``path`` to the ancestor literally named ``name``.

    Mirrors ``provision.sh``'s own ``default_upstream_root()`` walk exactly
    -- so the expected sibling-checkout path below is derived the same way
    production code derives it (from the repo root up to the ancestor
    literally named "AERead"), rather than one developer's own absolute
    path hardcoded as the expected value. That hardcoded version could only
    ever pass on the one machine it was written on; CI (a checkout rooted at
    e.g. ``/home/runner/...``) failed both jobs on it.
    """
    for candidate in (path, *path.parents):
        if candidate.name == name:
            return candidate
    raise AssertionError(f"no ancestor named {name!r} found above {path}")


# The relationship docs/negarena_adapter_spec.md and every negarena test/doc
# actually promise: "upstream-negarena" sits next to the top-level "AERead"
# directory itself, regardless of which machine or checkout depth this runs
# from. Computed from REPO_ROOT (this test file's own location), exactly
# like ``default_upstream_root()`` computes it from ``provision.sh``'s own
# location -- both walk up to the ancestor named "AERead", then descend into
# "upstream-negarena" next to it.
DOCUMENTED_SIBLING_CHECKOUT = str(
    _ancestor_named(REPO_ROOT, "AERead").parent / "upstream-negarena"
)


def _print_default_upstream_root(script: Path) -> str:
    result = subprocess.run(
        ["bash", str(script), "--print-default-upstream-root"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _print_resolved_upstream_root(
    script: Path, *, upstream_root_override: str | None = None
) -> str:
    """Drive ``--print-resolved-upstream-root`` -- the exact ``UPSTREAM_ROOT``
    value the real (non-flag) provisioning run below it resolves and uses --
    with a controlled environment so this never depends on whatever the
    ambient shell happens to have exported."""
    env = dict(os.environ)
    if upstream_root_override is None:
        env.pop("AEREAD_NEGARENA_UPSTREAM_ROOT", None)
    else:
        env["AEREAD_NEGARENA_UPSTREAM_ROOT"] = upstream_root_override
    result = subprocess.run(
        ["bash", str(script), "--print-resolved-upstream-root"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
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


def test_resolved_upstream_root_matches_the_default_when_no_override_is_set() -> None:
    """docs/negarena_fix_verification.md Finding 5: this drives the real
    provisioning use-site's own ``UPSTREAM_ROOT=...`` assignment (via
    ``--print-resolved-upstream-root``), not just the ``default_upstream_root``
    helper function in isolation. With no ``AEREAD_NEGARENA_UPSTREAM_ROOT``
    override, it must resolve to the same documented sibling checkout."""
    assert (
        _print_resolved_upstream_root(PROVISION_SCRIPT) == DOCUMENTED_SIBLING_CHECKOUT
    )


def test_resolved_upstream_root_honors_an_explicit_env_override() -> None:
    """The real assignment is
    ``${AEREAD_NEGARENA_UPSTREAM_ROOT:-$(default_upstream_root ...)}`` -- an
    explicit override must take precedence over the computed default. This
    is a code path ``--print-default-upstream-root`` never exercises at all:
    that flag calls the helper function directly and always ignores the
    environment."""
    override = "/tmp/some-other-upstream-negarena-checkout"
    assert (
        _print_resolved_upstream_root(PROVISION_SCRIPT, upstream_root_override=override)
        == override
    )


def test_resolved_upstream_root_agrees_between_a_main_checkout_and_a_worktree(
    tmp_path: Path,
) -> None:
    """Same synthetic-layout proof as
    ``test_default_upstream_root_agrees_between_a_main_checkout_and_a_worktree``
    above, but through the real production assignment (no env override set)
    at both checkout depths, rather than the bare helper function."""
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

    main_resolved = _print_resolved_upstream_root(main_checkout_script)
    worktree_resolved = _print_resolved_upstream_root(worktree_script)

    assert main_resolved == str(main_root / "upstream-negarena")
    assert worktree_resolved == str(worktree_root / "upstream-negarena")
