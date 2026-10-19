"""Which commit a bundle's pinned sources came from (#161), and the join key
that stays unique when every inference seed has its own run plan (DC-T-04)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from aeread.shared_runner import (
    EPISODE_KEY_FIELDS,
    ProvenanceError,
    assert_unique_episode_keys,
    episode_key,
    source_commit_for_pins,
)
from aeread.shared_runner.run import provenance, seal_manifest
from aeread.shared_runner.run.publication import (
    rebuild_publication_manifest,
    seal_publication_manifest,
)

BOUNDARY = {"included": "tables", "excluded": "raw run evidence"}


def _git(root: Path, *arguments: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    return subprocess.run(
        ("git", "-C", str(root), *arguments), check=True, capture_output=True, env=env
    ).stdout.decode().strip()


def _commit(root: Path, files: dict[str, str], message: str) -> str:
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def repository(tmp_path: Path):
    """A family that ran a campaign at ``ran``, then moved on twice."""

    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    commits = {
        "first": _commit(root, {"family/environment.py": "v1\n", "family/runner.py": "r1\n"}, "family"),
    }
    commits["ran"] = _commit(root, {"family/environment.py": "v2\n"}, "the state the campaign ran on")
    commits["unrelated"] = _commit(root, {"docs/notes.md": "notes\n"}, "docs only")
    commits["moved"] = _commit(root, {"family/environment.py": "v3\n"}, "a later reasoning condition")
    commits["again"] = _commit(root, {"family/runner.py": "r2\n"}, "a route registry")
    pins = {"family/environment.py": _sha("v2\n"), "family/runner.py": _sha("r1\n")}
    return root, commits, pins


def test_the_commit_that_produced_the_pinned_sources_is_found_after_the_family_moved(repository) -> None:
    root, commits, pins = repository
    assert _sha((root / "family/environment.py").read_text()) != pins["family/environment.py"]
    assert source_commit_for_pins(root, pins) == commits["ran"]


def test_the_answer_does_not_move_as_history_grows(repository) -> None:
    """Publishing the same bundle again from a later checkout must write the
    same bytes, so the commit is the one that produced the state, not HEAD."""

    root, commits, pins = repository
    for revision in (commits["ran"], commits["unrelated"], commits["moved"], "HEAD"):
        assert source_commit_for_pins(root, pins, revision=revision) == commits["ran"]
    current = {"family/environment.py": _sha("v3\n"), "family/runner.py": _sha("r2\n")}
    assert source_commit_for_pins(root, current) == commits["again"]
    _commit(root, {"docs/more.md": "more\n"}, "docs only, later")
    assert source_commit_for_pins(root, current) == commits["again"]


def test_uncommitted_edits_are_never_a_replayable_state(repository) -> None:
    root, _commits, _pins = repository
    (root / "family/environment.py").write_text("v4, not committed\n", encoding="utf-8")
    dirty = {"family/environment.py": _sha("v4, not committed\n"), "family/runner.py": _sha("r2\n")}
    with pytest.raises(ProvenanceError, match="no commit reachable"):
        source_commit_for_pins(root, dirty)


def test_a_state_before_the_searched_revision_is_not_found_after_it(repository) -> None:
    root, commits, pins = repository
    with pytest.raises(ProvenanceError, match="no commit reachable"):
        source_commit_for_pins(root, pins, revision=commits["first"])


@pytest.mark.parametrize(
    "pins",
    [
        {},
        {"/abs/environment.py": "0" * 64},
        {"../outside.py": "0" * 64},
        {"family/environment.py": "not-a-digest"},
        {"family/environment.py": "A" * 64},
    ],
)
def test_malformed_pins_are_refused(repository, pins) -> None:
    root, _commits, _pins = repository
    with pytest.raises(ProvenanceError):
        source_commit_for_pins(root, pins)


def test_the_cli_prints_the_commit_or_exits_non_zero(repository, tmp_path, capsys) -> None:
    root, commits, pins = repository
    pins_file = tmp_path / "pins.json"
    pins_file.write_text(json.dumps({"family/runner.py": pins["family/runner.py"]}), encoding="utf-8")
    code = provenance.main(
        [
            "--repository-root", str(root),
            "--pins-json", str(pins_file),
            "--pin", f"family/environment.py={pins['family/environment.py']}",
        ]
    )
    assert code == 0 and capsys.readouterr().out.strip() == commits["ran"]
    with pytest.raises(SystemExit) as raised:
        provenance.main(["--repository-root", str(root), "--pin", f"family/runner.py={'0' * 64}"])
    assert raised.value.code == 1


def _bundle(tmp_path: Path, name: str = "bundle") -> Path:
    root = tmp_path / name
    (root / "tables").mkdir(parents=True)
    (root / "tables" / "rows.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    return root


def test_a_manifest_records_the_source_commit_and_a_rebuild_keeps_it(repository, tmp_path) -> None:
    root, commits, pins = repository
    bundle = _bundle(tmp_path)
    commit = source_commit_for_pins(root, pins)
    manifest = seal_publication_manifest(
        bundle, publication_id="fixture_v1", privacy_boundary=BOUNDARY, source_commit=commit
    )
    assert manifest["source_commit"] == commits["ran"]
    assert rebuild_publication_manifest(bundle) == manifest


def test_a_manifest_without_a_source_commit_is_what_it_always_was(tmp_path) -> None:
    plain = seal_publication_manifest(_bundle(tmp_path, "a"), publication_id="fixture_v1", privacy_boundary=BOUNDARY)
    assert "source_commit" not in plain


@pytest.mark.parametrize("value", ["abc123", "HEAD", "A" * 40, ""])
def test_a_malformed_source_commit_is_refused(tmp_path, value) -> None:
    with pytest.raises(ValueError, match="source_commit"):
        seal_publication_manifest(
            _bundle(tmp_path), publication_id="fixture_v1", privacy_boundary=BOUNDARY, source_commit=value
        )


def test_seal_manifest_cli_accepts_the_source_commit(tmp_path) -> None:
    bundle = _bundle(tmp_path)
    commit = "0123456789abcdef0123456789abcdef01234567"
    assert seal_manifest.main(
        [str(bundle), "--new", "--included", "tables", "--excluded", "raw", "--source-commit", commit]
    ) == 0
    assert json.loads((bundle / "publication_manifest.json").read_text())["source_commit"] == commit


def _row(run_plan_id: str, **overrides: str) -> dict[str, str]:
    return {
        "run_plan_id": run_plan_id,
        "cell_id": "cell_world_07",
        "episode_id": "episode_world_07",
        "episode_attempt_id": "episode_attempt_world_07_0",
        **overrides,
    }


def test_two_seeds_of_one_world_share_every_cell_identity_but_not_the_episode_key() -> None:
    """DC-T-04: the inference seed lives in the run plan, so the two seed
    cells of a world share cell_id, episode_id and episode_attempt_id."""

    seed_a, seed_b = _row("runplan_seed_41211"), _row("runplan_seed_41212")
    for field in ("cell_id", "episode_id", "episode_attempt_id"):
        assert seed_a[field] == seed_b[field]
    assert episode_key(seed_a) != episode_key(seed_b)
    assert episode_key(seed_a) == episode_key(dict(reversed(list(seed_a.items()))))
    assert EPISODE_KEY_FIELDS == ("run_plan_id", "cell_id", "episode_attempt_id")
    assert_unique_episode_keys([seed_a, seed_b], label="trajectory rows")


def test_a_repeated_episode_key_is_refused_and_a_record_without_one_is_not_keyed() -> None:
    row = _row("runplan_seed_41211")
    with pytest.raises(ValueError, match="repeat 1 episode key"):
        assert_unique_episode_keys([row, dict(row)], label="receipt rows")
    with pytest.raises(ValueError, match="lacks an episode key field"):
        episode_key({"run_plan_id": "runplan_x", "cell_id": "cell_x"})
