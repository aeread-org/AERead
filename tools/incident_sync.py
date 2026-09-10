#!/usr/bin/env python3
"""Keep the incident log's unresolved rows and this repository's issues in step.

The two-tier register (`docs/operations/incident_log.md` and the per-family
ledgers) is the source of truth for what has gone wrong here, and its rows
are never deleted -- only their disposition changes. That works well for the
record and badly for the work: a row whose disposition is `open` is a task
nobody is assigned, nobody is notified of, and nobody sees unless they reread
a 900-line document. Three issues were filed by hand this week for rows that
were already in the log.

This script closes that gap in one direction only. **The log is the source of
truth**; an issue is a projection of a row, carrying a marker that ties it
back. It never edits the log, because a disposition is a judgment and the
person who resolved something writes it in the row.

Three modes:

* ``--lint`` parses every table and checks the convention below. It needs no
  network and runs on pull requests.
* ``--check`` compares unresolved rows against the repository's issues and
  reports drift without changing anything. Exits non-zero if there is drift,
  so it can gate.
* ``--apply`` opens an issue for each unresolved row that has none, and
  closes the issue of a row that is no longer unresolved.
* ``--announce --pr N`` posts one comment on a pull request naming the
  unresolved rows it adds, which will become issues when it merges.

The last mode exists because a row is written on a branch and merged days
later, and an incident is most useful to other people on the day it happens.
Announcing is deliberately not opening: a branch may be rebased, rewritten or
abandoned, and an issue tracker should not fill up with rows that never
landed. The comment is rewritten in place on every push, so it always
describes the branch as it now stands.

**The convention it enforces.** A row is unresolved if and only if its
disposition begins with the word ``open`` once markdown emphasis is stripped.
"Open" is not a failure state -- the standard says so -- but it does have to
be written the same way every time, or a reader has to interpret prose to
learn whether something is still outstanding, and so does this script.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LEDGERS = ("docs/operations/incident_log.md",)
LEDGER_GLOBS = ("docs/families/*/incidents.md",)

MARKER = "aeread-incident"
LABEL = "incident"
# `| D-14 |` or `| TB-D-03 |`: a family or section prefix and a number.
ROW_ID = re.compile(r"^[A-Z][A-Za-z0-9]*(?:-[A-Z]+)*-\d+$")
EMPHASIS = re.compile(r"[*`_]+")


@dataclass(frozen=True)
class IncidentRow:
    """One row of one incident table.

    `id` is only unique within its section -- the log reuses `D-14` in both
    the housing and the procurement sections, deliberately, because each
    section numbers its own findings. `key` is what identifies a row across
    the repository, and it is what an issue's marker carries.
    """

    id: str
    summary: str
    disposition: str
    path: str
    line: int
    cells: tuple[str, ...]
    section: str

    @property
    def key(self) -> str:
        return f"{self.section}/{self.id}" if self.section else self.id

    @property
    def unresolved(self) -> bool:
        return EMPHASIS.sub("", self.disposition).strip().lower().startswith("open")

    @property
    def title(self) -> str:
        # A title is a handle, not the row: one clause, no markdown, bounded.
        text = EMPHASIS.sub("", self.summary).strip()
        clause = re.split(r"(?<=[a-z0-9])[.;] ", text)[0]
        if len(clause) > 96:
            clause = clause[:93].rsplit(" ", 1)[0] + "..."
        return f"Incident {self.key}: {clause}"

    def body(self) -> str:
        cells = "\n".join(
            f"- **{name}:** {value}"
            for name, value in zip(("what happened", "detection", "cost"), self.cells[1:-1])
            if value
        )
        return (
            f"<!-- {MARKER}: {self.key} -->\n"
            f"Projected from the incident log, which is the source of truth for this row.\n"
            f"Editing the issue does not change the record; resolving the row does.\n\n"
            f"{cells}\n\n"
            f"- **disposition:** {self.disposition}\n\n"
            f"Source: [`{self.path}` line {self.line}]"
            f"(../blob/main/{self.path}#L{self.line})\n\n"
            f"This issue is closed automatically when that row's disposition stops "
            f"beginning with `open`. Write the resolution in the row, not here."
        )


def _slug(text: str) -> str:
    """A short, stable handle for a section heading.

    Stable matters more than pretty: it goes into an issue marker, so a
    heading that gains a word must not orphan the issue. Only the leading
    date-or-word run is kept for that reason.
    """
    cleaned = EMPHASIS.sub("", text).strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")
    return "-".join(cleaned.split("-")[:4])


def ledger_paths(root: Path) -> list[Path]:
    paths = [root / name for name in LEDGERS]
    for pattern in LEDGER_GLOBS:
        paths.extend(sorted(root.glob(pattern)))
    return [path for path in paths if path.is_file()]


def parse_rows(path: Path, root: Path) -> list[IncidentRow]:
    """Every id-bearing row of every table in one ledger.

    The ledgers carry two table shapes (three columns and five), and the
    parser cares only that the first cell is an id and the last a
    disposition, so a new shape does not need a code change.
    """
    return _parse_text(path.read_text(encoding="utf-8"), str(path.relative_to(root)), path)


def _parse_text(text: str, relative: str, path: Path) -> list[IncidentRow]:
    rows: list[IncidentRow] = []
    # A family ledger numbers its own findings, so the family is the scope and
    # the marker reads `govsim/G-D-03`. The shared log reuses numbers across
    # its dated sections, so there the section is the scope.
    family = path.parent.name if path.parent.parent.name == "families" else ""
    section = family
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("## ") and not family:
            section = _slug(stripped[3:])
            continue
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = tuple(cell.strip() for cell in stripped.strip("|").split("|"))
        if len(cells) < 3 or not ROW_ID.match(cells[0]):
            continue
        rows.append(
            IncidentRow(
                id=cells[0],
                summary=cells[1],
                disposition=cells[-1],
                path=relative,
                line=number,
                cells=cells,
                section=section or _slug(path.stem),
            )
        )
    return rows


def collect(root: Path = REPOSITORY_ROOT) -> list[IncidentRow]:
    rows: list[IncidentRow] = []
    for path in ledger_paths(root):
        rows.extend(parse_rows(path, root))
    return rows


def collect_at(ref: str, root: Path = REPOSITORY_ROOT,
               reader: Callable[[str, str], str | None] | None = None) -> list[IncidentRow]:
    """The same rows as they stand at a git ref.

    Used to tell which rows a branch *adds*, so a pull request can be told
    what it will open without opening it. A ledger that does not exist at the
    ref simply contributes nothing, which is the right answer for a family
    whose ledger is new on this branch.
    """
    read = reader or _read_at_ref
    rows: list[IncidentRow] = []
    for path in ledger_paths(root):
        relative = str(path.relative_to(root))
        text = read(ref, relative)
        if text is None:
            continue
        rows.extend(_parse_text(text, relative, path))
    return rows


def _read_at_ref(ref: str, relative: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:{relative}"], capture_output=True, text=True, cwd=REPOSITORY_ROOT
    )
    return result.stdout if result.returncode == 0 else None


def new_unresolved(current: Sequence[IncidentRow], base: Sequence[IncidentRow]) -> list[IncidentRow]:
    """Unresolved rows this branch adds, and rows it reopens.

    A row that was already unresolved on the base is not this branch's news;
    a row the branch flips back to open is.
    """
    was_unresolved = {row.key for row in base if row.unresolved}
    return [row for row in current if row.unresolved and row.key not in was_unresolved]


def lint(rows: Sequence[IncidentRow]) -> list[str]:
    """Complaints that need no network: duplicate ids, empty dispositions,
    and a disposition that reads as unresolved without saying `open`."""
    problems: list[str] = []
    seen: dict[str, IncidentRow] = {}
    for row in rows:
        previous = seen.get(row.key)
        if previous is not None:
            problems.append(
                f"{row.path}:{row.line}: duplicate incident key {row.key} "
                f"(also {previous.path}:{previous.line})"
            )
        seen[row.key] = row
        if not row.disposition:
            problems.append(f"{row.path}:{row.line}: {row.key} has an empty disposition")
        text = EMPHASIS.sub("", row.disposition).strip().lower()
        if not row.unresolved and re.search(r"\b(still |remains |is )?(open|outstanding|unresolved|owed|pending)\b", text):
            problems.append(
                f"{row.path}:{row.line}: {row.key} reads as unresolved but its disposition "
                f"does not begin with 'open', so no issue will be opened for it: "
                f"{row.disposition[:70]!r}"
            )
    return problems


# --- the repository side ----------------------------------------------------


def _gh(args: Sequence[str]) -> str:
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, cwd=REPOSITORY_ROOT
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {result.stderr.strip()[:300]}")
    return result.stdout


def list_incident_issues() -> dict[str, dict]:
    """Existing projections, keyed by the incident id in their marker.

    Keyed by marker rather than by title so that retitling an issue -- which
    a person may reasonably do -- does not orphan it.
    """
    raw = _gh(
        ["issue", "list", "--label", LABEL, "--state", "all", "--limit", "500",
         "--json", "number,title,body,state"]
    )
    issues: dict[str, dict] = {}
    for issue in json.loads(raw or "[]"):
        found = re.search(rf"<!-- {MARKER}: ([A-Za-z0-9/-]+) -->", issue.get("body") or "")
        if found:
            issues[found.group(1)] = issue
    return issues


def plan(rows: Sequence[IncidentRow], issues: dict[str, dict]) -> tuple[list[IncidentRow], list[tuple[IncidentRow, dict]]]:
    """What --apply would do: issues to open, issues to close."""
    to_open = [
        row for row in rows
        if row.unresolved and (row.key not in issues or issues[row.key]["state"] == "CLOSED")
    ]
    to_close = [
        (row, issues[row.key]) for row in rows
        if not row.unresolved and row.key in issues and issues[row.key]["state"] == "OPEN"
    ]
    return to_open, to_close


def apply(to_open: Iterable[IncidentRow], to_close: Iterable[tuple[IncidentRow, dict]],
          runner: Callable[[Sequence[str]], str] = _gh) -> list[str]:
    done: list[str] = []
    for row in to_open:
        runner(["issue", "create", "--title", row.title, "--body", row.body(), "--label", LABEL])
        done.append(f"opened an issue for {row.key}")
    for row, issue in to_close:
        runner([
            "issue", "comment", str(issue["number"]),
            "--body",
            f"Closing: the incident log's row for `{row.key}` is no longer open.\n\n"
            f"> {row.disposition}\n\n"
            f"Source: `{row.path}` line {row.line}.",
        ])
        runner(["issue", "close", str(issue["number"])])
        done.append(f"closed #{issue['number']} for {row.key}")
    return done


ANNOUNCE_MARKER = "<!-- aeread-incident-announce -->"


def announce(rows: Sequence[IncidentRow], pr: str,
             runner: Callable[[Sequence[str]], str] = _gh) -> str:
    """Post or rewrite this branch's incident comment on a pull request."""
    if rows:
        listed = "\n".join(
            f"- **{row.key}** — {EMPHASIS.sub('', row.summary)[:150]}  \n"
            f"  `{row.path}` line {row.line}"
            for row in rows
        )
        body = (
            f"{ANNOUNCE_MARKER}\n"
            f"This branch logs **{len(rows)} unresolved incident "
            f"{'row' if len(rows) == 1 else 'rows'}**. Merging it opens an issue for each, "
            f"and resolving a row later closes its issue.\n\n{listed}\n\n"
            f"Nothing is opened before the merge: a branch can be rebased or abandoned, "
            f"and the issue tracker should carry rows that landed."
        )
    else:
        body = (
            f"{ANNOUNCE_MARKER}\n"
            f"This branch adds no unresolved incident rows."
        )
    existing = json.loads(runner(["pr", "view", pr, "--json", "comments"]) or "{}")
    for comment in existing.get("comments", []):
        if ANNOUNCE_MARKER in (comment.get("body") or ""):
            # `gh` cannot edit a comment by id, so the stale one is replaced by
            # rewriting it through the API.
            runner([
                "api", "-X", "PATCH",
                f"repos/{{owner}}/{{repo}}/issues/comments/{comment['id'].split('-')[-1]}",
                "-f", f"body={body}",
            ])
            return "updated the incident comment"
    runner(["pr", "comment", pr, "--body", body])
    return "posted the incident comment"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--lint", action="store_true", help="parse and check the convention; no network")
    mode.add_argument("--check", action="store_true", help="report drift against the issues; no writes")
    mode.add_argument("--apply", action="store_true", help="open and close issues to match the log")
    mode.add_argument("--announce", action="store_true",
                      help="comment on a pull request naming the unresolved rows it adds")
    parser.add_argument("--pr", help="pull request number, for --announce")
    parser.add_argument("--base-ref", default="origin/main",
                        help="what --announce compares against (default: origin/main)")
    parser.add_argument("--root", type=Path, default=REPOSITORY_ROOT)
    args = parser.parse_args(argv)

    rows = collect(args.root)
    problems = lint(rows)
    unresolved = [row for row in rows if row.unresolved]
    print(f"{len(rows)} incident rows, {len(unresolved)} unresolved, across {len(ledger_paths(args.root))} ledgers")

    if args.announce:
        if not args.pr:
            parser.error("--announce needs --pr")
        if problems:
            for problem in problems:
                print(f"  {problem}")
            return 1
        added = new_unresolved(rows, collect_at(args.base_ref, args.root))
        for row in added:
            print(f"  new unresolved: {row.key}")
        print(f"  {announce(added, args.pr)}")
        return 0

    if args.lint or not (args.check or args.apply):
        for problem in problems:
            print(f"  {problem}")
        return 1 if problems else 0

    if problems:
        for problem in problems:
            print(f"  {problem}")
        print("refusing to sync while the log does not lint")
        return 1

    issues = list_incident_issues()
    to_open, to_close = plan(rows, issues)
    for row in to_open:
        print(f"  would open : {row.key:34} {row.title[:60]}")
    for row, issue in to_close:
        print(f"  would close: {row.key:34} #{issue['number']} (row resolved)")
    if args.check:
        return 1 if (to_open or to_close) else 0
    for line in apply(to_open, to_close):
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
