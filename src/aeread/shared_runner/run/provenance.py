"""Which commit a bundle's pinned sources came from.

A campaign plan pins its family source files by digest. The first later edit
to that family changes those digests, and from then on the earlier bundle
cannot be rebuilt or replayed from current source: it still replays from the
commit whose source the plan pinned, but nothing in the bundle says which
commit that is, and an operator has to match digests against ``git log`` by
hand (TB-D-04: three occurrences in two days, #161).

``source_commit_for_pins`` answers it from the pins alone. A publisher calls
it at publish time and records the answer as the manifest's
``source_commit``; a reader holding an older bundle calls it (or
``aeread source-commit``) with the bundle's recorded digests.

The commit returned is the one that *produced* the pinned state: the newest
commit at which every pinned file has its pinned bytes and which touched at
least one of them. Every later commit that leaves those files alone replays
equally well, but this one does not move as history grows, so publishing the
same bundle again from a later checkout writes the same bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")


class ProvenanceError(ValueError):
    """The pinned sources cannot be tied to one committed state."""


def is_source_commit(value: object) -> bool:
    """Whether ``value`` is a full lowercase commit id."""

    return isinstance(value, str) and _COMMIT.fullmatch(value) is not None


def _git(root: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ("git", "-C", str(root), *arguments),
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise ProvenanceError(f"cannot run git in {root}: {error}") from error
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", "replace").strip()
        raise ProvenanceError(f"git {' '.join(arguments[:2])} failed in {root}: {message}")
    return completed.stdout


def _validated_pins(pins: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(pins, Mapping) or not pins:
        raise ProvenanceError("pins must be a non-empty mapping of path to sha256")
    validated: dict[str, str] = {}
    for path, digest in pins.items():
        posix = PurePosixPath(path) if isinstance(path, str) else None
        if (
            posix is None
            or not path
            or posix.is_absolute()
            or ".." in posix.parts
            or "\\" in path
        ):
            raise ProvenanceError(f"pinned path must be repository-relative: {path!r}")
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise ProvenanceError(f"pin for {path} must be a lowercase sha256")
        validated[posix.as_posix()] = digest
    return dict(sorted(validated.items()))


def _blob_sha256(root: Path, commit: str, path: str) -> str | None:
    completed = subprocess.run(
        ("git", "-C", str(root), "cat-file", "blob", f"{commit}:{path}"),
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        return None
    return hashlib.sha256(completed.stdout).hexdigest()


def _matches(root: Path, commit: str, pins: Mapping[str, str]) -> bool:
    return all(_blob_sha256(root, commit, path) == digest for path, digest in pins.items())


def source_commit_for_pins(
    repository_root: Path | str, pins: Mapping[str, str], *, revision: str = "HEAD"
) -> str:
    """The commit that produced the pinned sources, searched back from ``revision``.

    ``pins`` maps repository-relative paths to the sha256 of each file's
    bytes. Only committed content is considered, so a pinned file with
    uncommitted edits is never mistaken for a replayable state. Raises
    :class:`ProvenanceError` when no commit reachable from ``revision`` holds
    every pin.
    """

    root = Path(repository_root)
    validated = _validated_pins(pins)
    history = _git(root, "rev-list", revision, "--", *validated).decode("ascii").split()
    for commit in history:
        if _matches(root, commit, validated):
            return commit
    raise ProvenanceError(
        f"no commit reachable from {revision} holds every pinned source "
        f"({len(validated)} paths, {len(history)} commits touching them searched); "
        "the history may be shallow, or a pinned file was never committed with those bytes"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aeread source-commit",
        description="find the commit a bundle's pinned source digests came from",
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--revision", default="HEAD", help="search back from this revision")
    parser.add_argument(
        "--pin",
        action="append",
        default=[],
        metavar="PATH=SHA256",
        help="one pinned source file; repeatable",
    )
    parser.add_argument(
        "--pins-json",
        type=Path,
        help="a JSON object mapping repository-relative paths to sha256 digests",
    )
    args = parser.parse_args(argv)
    pins: dict[str, str] = {}
    try:
        if args.pins_json is not None:
            loaded = json.loads(args.pins_json.read_text(encoding="utf-8"))
            if not isinstance(loaded, Mapping):
                raise ProvenanceError("--pins-json must hold a JSON object")
            pins.update(loaded)
        for entry in args.pin:
            path, separator, digest = entry.rpartition("=")
            if not separator or not path:
                raise ProvenanceError(f"--pin must be PATH=SHA256: {entry!r}")
            pins[path] = digest
        commit = source_commit_for_pins(args.repository_root, pins, revision=args.revision)
    except (ProvenanceError, OSError, json.JSONDecodeError) as error:
        parser.exit(1, f"aeread source-commit: {error}\n")
    print(commit)
    return 0


__all__ = ["ProvenanceError", "is_source_commit", "main", "source_commit_for_pins"]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
