"""The incident-log to issue projection.

The log is the source of truth and an issue is a projection of a row, so
these tests fix the two things that make that safe: which rows count as
unresolved, and that a row is identified the same way twice running.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# `tools/` is not a package, so the script is loaded by path.
_MODULE = Path(__file__).resolve().parents[1] / "tools" / "incident_sync.py"
_spec = importlib.util.spec_from_file_location("incident_sync", str(_MODULE))
assert _spec is not None and _spec.loader is not None
incident_sync = importlib.util.module_from_spec(_spec)
sys.modules["incident_sync"] = incident_sync
_spec.loader.exec_module(incident_sync)


def _ledger(tmp_path: Path, body: str) -> Path:
    root = tmp_path / "docs" / "operations"
    root.mkdir(parents=True)
    (root / "incident_log.md").write_text(body, encoding="utf-8")
    return tmp_path


LEDGER = """# log

## 2026-09-01 housing

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| D-1 | a thing broke | a person read it | one run | fixed in #12 |
| D-14 | another thing | CI | none | open |

## 2026-09-02 procurement

| id | what happened | disposition |
|---|---|---|
| D-14 | a different thing, same number | open, and deliberately numbered per section |
| J-2 | a judgment | it stands |
"""


def test_rows_are_identified_by_section_because_the_log_reuses_numbers(tmp_path: Path) -> None:
    """`D-14` appears in two sections on purpose -- each numbers its own
    findings -- so a bare id cannot key an issue."""
    rows = incident_sync.collect(_ledger(tmp_path, LEDGER))
    keys = [row.key for row in rows]
    assert len(keys) == len(set(keys))
    assert [k for k in keys if k.endswith("D-14")] == [
        "2026-09-01-housing/D-14",
        "2026-09-02-procurement/D-14",
    ]
    assert not incident_sync.lint(rows)


def test_unresolved_is_exactly_a_disposition_beginning_with_open(tmp_path: Path) -> None:
    rows = {row.id + "@" + row.section: row for row in incident_sync.collect(_ledger(tmp_path, LEDGER))}
    assert rows["D-1@2026-09-01-housing"].unresolved is False
    assert rows["D-14@2026-09-01-housing"].unresolved is True
    assert rows["D-14@2026-09-02-procurement"].unresolved is True
    assert rows["J-2@2026-09-02-procurement"].unresolved is False


def test_lint_catches_a_row_that_reads_unresolved_without_saying_open(tmp_path: Path) -> None:
    """The whole convention exists so a reader never has to interpret prose
    to learn whether something is outstanding. A row that hides it is the
    failure this check is for."""
    body = LEDGER + "\n| O-1 | a thing | nobody | none | this remains open, we think |\n"
    problems = incident_sync.lint(incident_sync.collect(_ledger(tmp_path, body)))
    assert any("reads as unresolved" in p and "O-1" in p for p in problems)


def test_lint_catches_a_duplicated_key_within_one_section(tmp_path: Path) -> None:
    body = LEDGER + "\n| D-14 | a third thing in the procurement section | x | y | open |\n"
    problems = incident_sync.lint(incident_sync.collect(_ledger(tmp_path, body)))
    assert any("duplicate incident key" in p for p in problems)


def test_the_plan_opens_only_what_is_missing_and_closes_only_what_resolved(tmp_path: Path) -> None:
    rows = incident_sync.collect(_ledger(tmp_path, LEDGER))
    by_key = {row.key: row for row in rows}
    issues = {
        # already projected and still open: leave it alone
        "2026-09-01-housing/D-14": {"number": 1, "state": "OPEN", "body": "", "title": ""},
        # a resolved row that still has an open issue: close it
        "2026-09-01-housing/D-1": {"number": 2, "state": "OPEN", "body": "", "title": ""},
    }
    to_open, to_close = incident_sync.plan(rows, issues)
    assert [row.key for row in to_open] == ["2026-09-02-procurement/D-14"]
    assert [(row.key, issue["number"]) for row, issue in to_close] == [
        ("2026-09-01-housing/D-1", 2)
    ]


def test_apply_writes_the_marker_and_never_edits_the_log(tmp_path: Path) -> None:
    root = _ledger(tmp_path, LEDGER)
    before = (root / "docs" / "operations" / "incident_log.md").read_text()
    rows = incident_sync.collect(root)
    to_open, to_close = incident_sync.plan(rows, {})
    calls: list[list[str]] = []
    incident_sync.apply(to_open, to_close, runner=lambda args: calls.append(list(args)) or "")
    assert len(calls) == 2 and all(c[:2] == ["issue", "create"] for c in calls)
    bodies = [c[c.index("--body") + 1] for c in calls]
    assert all(f"<!-- {incident_sync.MARKER}: " in b for b in bodies)
    assert all("source of truth" in b for b in bodies)
    # the projection is one-way
    assert (root / "docs" / "operations" / "incident_log.md").read_text() == before


def test_the_repositorys_own_log_lints() -> None:
    """The convention is only worth having if the real log obeys it."""
    problems = incident_sync.lint(incident_sync.collect(incident_sync.REPOSITORY_ROOT))
    assert problems == [], "\n".join(problems)


def test_a_branch_announces_only_the_rows_it_adds(tmp_path: Path) -> None:
    """A row already open on the base is not this branch's news; a row the
    branch adds, or flips back to open, is."""
    root = _ledger(tmp_path, LEDGER + "\n| O-9 | a fresh failure | CI | one run | open |\n")
    base_text = LEDGER.replace("| D-1 | a thing broke | a person read it | one run | fixed in #12 |",
                               "| D-1 | a thing broke | a person read it | one run | open |")
    base = incident_sync.collect_at("BASE", root, reader=lambda ref, rel: base_text)
    added = incident_sync.new_unresolved(incident_sync.collect(root), base)
    keys = [row.key for row in added]
    # appended after the procurement table, so that is its section
    assert "2026-09-02-procurement/O-9" in keys    # added by the branch
    assert "2026-09-01-housing/D-1" not in keys    # the branch RESOLVED this one
    assert "2026-09-01-housing/D-14" not in keys   # already open on the base


def test_a_ledger_absent_from_the_base_contributes_nothing(tmp_path: Path) -> None:
    """A family whose ledger is new on this branch has no base rows, and that
    must read as 'all new' rather than crash."""
    root = _ledger(tmp_path, LEDGER)
    base = incident_sync.collect_at("BASE", root, reader=lambda ref, rel: None)
    assert base == []
    added = incident_sync.new_unresolved(incident_sync.collect(root), base)
    assert len(added) == 2


def test_announce_rewrites_its_own_comment_rather_than_stacking(tmp_path: Path) -> None:
    """Every push re-announces, so the comment must be replaced in place or a
    long-lived branch grows a wall of them."""
    rows = [r for r in incident_sync.collect(_ledger(tmp_path, LEDGER)) if r.unresolved]
    calls: list[list[str]] = []

    def runner(args):
        calls.append(list(args))
        if args[:2] == ["pr", "view"]:
            return json.dumps({"comments": [{"id": "IC_kwDO-99", "body": incident_sync.ANNOUNCE_MARKER + "\nold"}]})
        return ""

    result = incident_sync.announce(rows, "153", runner=runner)
    assert result == "updated the incident comment"
    assert not any(c[:2] == ["pr", "comment"] for c in calls)
    patched = next(c for c in calls if c[0] == "api")
    assert any("issues/comments/99" in arg for arg in patched)
    assert incident_sync.ANNOUNCE_MARKER in patched[-1]


def test_announce_says_so_plainly_when_a_branch_adds_none(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    incident_sync.announce([], "1", runner=lambda a: calls.append(list(a)) or (json.dumps({"comments": []}) if a[:2] == ["pr", "view"] else ""))
    body = next(c for c in calls if c[:2] == ["pr", "comment"])[-1]
    assert "adds no unresolved incident rows" in body
