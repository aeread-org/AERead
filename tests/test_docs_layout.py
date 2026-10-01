"""Layout guards for ``docs/``: placement, indexing, links and cited paths.

The placement rule lives in ``docs/README.md``. These tests are what keep it
true: seventy-nine documents once accumulated at the root of ``docs/``,
unindexed, with ninety-two stale cross-references, and nothing failed.
"""

from __future__ import annotations

import io
import re
import subprocess
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
MOVED = DOCS / "operations" / "moved_documents.md"

_LINK = re.compile(r"\]\((<[^>]+>|[^)\s]+)\)")
_EXTERNAL = re.compile(r"^(https?:|mailto:|#)")
_CITATION = re.compile(r"(?<![\w/.\-])(docs/[A-Za-z0-9_./\-]+?\.md)\b")
_TABLE_ROW = re.compile(r"^\| `(docs/[^`]+\.md)` \| (.*) \|$")
_DESTINATION = re.compile(r"^\[`(docs/[^`]+\.md)`\]")


def _link_targets(markdown: Path) -> list[str]:
    targets = []
    for match in _LINK.finditer(markdown.read_text(encoding="utf-8")):
        target = match.group(1).strip("<>")
        if not _EXTERNAL.match(target):
            targets.append(target)
    return targets


def _redirects() -> tuple[dict[str, str], set[str]]:
    """The moved table and the cited-but-absent table, as written."""
    moved: dict[str, str] = {}
    absent: set[str] = set()
    for line in MOVED.read_text(encoding="utf-8").splitlines():
        row = _TABLE_ROW.match(line)
        if row is None:
            continue
        cited, rest = row.group(1), row.group(2)
        destination = _DESTINATION.match(rest)
        if destination is not None:
            moved[cited] = destination.group(1)
        else:
            absent.add(cited)
    return moved, absent


def _tracked_text_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode("utf-8")
    paths = []
    for name in listed.split("\0"):
        # Published evidence is immutable and cites paths as they were when
        # it was sealed; it is outside what a documentation move may touch.
        if not name or name.startswith("evidence/"):
            continue
        path = ROOT / name
        if path.suffix in {".png", ".svg", ".lock", ".gz", ".pdf"}:
            continue
        if not path.is_file():  # a tracked symlink to a directory
            continue
        paths.append(path)
    return paths


def _prose(path: Path, text: str) -> str:
    """The part of a file that cites documents rather than naming test data.

    A test's string literals are fixtures (a placeholder path written into a
    temporary repository); its comments and docstrings are citations.
    Everything else is read whole.
    """
    if path.suffix != ".py" or ROOT / "tests" not in path.parents:
        return text
    prose = []
    previous = None
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    for index, token in enumerate(tokens):
        if token.type == tokenize.COMMENT:
            prose.append(token.string)
        elif token.type == tokenize.STRING:
            following = next(
                (t for t in tokens[index + 1 :] if t.type not in (tokenize.COMMENT, tokenize.NL)),
                None,
            )
            starts_statement = previous in (None, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT)
            if starts_statement and following is not None and following.type == tokenize.NEWLINE:
                prose.append(token.string)
        if token.type not in (tokenize.COMMENT, tokenize.NL):
            previous = token.type
    return "\n".join(prose)


def test_docs_root_holds_only_the_index() -> None:
    assert {path.name for path in DOCS.iterdir() if path.is_file()} == {"README.md"}


def test_every_document_is_linked_from_the_index_or_its_section_readme() -> None:
    indexes = [DOCS / "README.md", *sorted(DOCS.glob("*/README.md"))]
    linked = set()
    for index in indexes:
        for target in _link_targets(index):
            linked.add((index.parent / target.split("#")[0]).resolve())
    unlinked = sorted(
        str(path.relative_to(ROOT))
        for path in DOCS.rglob("*.md")
        if path.resolve() not in linked and path not in indexes
    )
    assert not unlinked, unlinked


def test_relative_links_in_documents_resolve_inside_the_repository() -> None:
    broken = []
    for markdown in sorted(DOCS.rglob("*.md")):
        for target in _link_targets(markdown):
            path = target.split("#")[0]
            if not path:
                continue
            # An absolute path is somebody's machine, not this repository.
            if path.startswith("/") or not (markdown.parent / path).exists():
                broken.append(f"{markdown.relative_to(ROOT)} -> {target}")
    assert not broken, broken


def test_moved_documents_table_points_at_documents_that_exist() -> None:
    moved, absent = _redirects()
    assert moved, "docs/operations/moved_documents.md has no rows"
    assert not moved.keys() & absent
    for cited, destination in moved.items():
        assert not (ROOT / cited).exists(), f"{cited} exists; drop its row"
        assert (ROOT / destination).is_file(), f"{cited} -> {destination} is missing"
    for cited in absent:
        assert not (ROOT / cited).exists(), f"{cited} exists; drop its row"


def test_every_cited_document_path_exists_or_is_redirected() -> None:
    """A documentation path cited anywhere must lead somewhere.

    Source files are hashed into sealed identities, so their citations are
    not rewritten when a document moves; the moved-documents table is what
    keeps those citations resolvable.
    """
    moved, absent = _redirects()
    dangling: dict[str, set[str]] = {}
    for path in _tracked_text_files():
        if path == MOVED:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for match in _CITATION.finditer(_prose(path, text)):
            cited = match.group(1)
            if any(marker in cited for marker in "<*{"):
                continue
            if (ROOT / cited).exists() or cited in moved or cited in absent:
                continue
            dangling.setdefault(cited, set()).add(str(path.relative_to(ROOT)))
    assert not dangling, {cited: sorted(files) for cited, files in dangling.items()}
