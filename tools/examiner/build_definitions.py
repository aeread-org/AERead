"""Strata and baselines, defined: what each stratum value and each reference on the examiner's pages means.

    python3 build_definitions.py <out dir> <AERead checkout>

A stratum is a condition the design fixes before a model acts (a world type, a scenario, the model in the other
seat); a baseline is what a model is measured against (a scripted policy, an oracle, an answer key, a bound). The
pages showed both as bare labels. `definitions.json` beside this script holds one entry per label: a short
definition in the world's own terms and the committed file it comes from, as a branch, a repository path and a
verbatim quote. The build reads that file at the branch's commit (`git show`, so uncommitted edits never count),
finds the quote, and stops if it is missing: a definition cannot outlive the text it paraphrases. Baselines that a
published gap report describes itself (`baselines[].description`) are added from the report, quoting it, unless an
entry already covers them. Writes `data/definitions.json` with each source's commit and line.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from build_case_cards import extra_checkouts

HERE = Path(__file__).resolve().parent


def norm(value: str) -> str:
    return re.sub(r"[\s-]+", "_", str(value).strip().lower())


def git(checkout: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(checkout), *args], check=True, capture_output=True, text=True).stdout


def resolve(checkout: Path, branch: str) -> str:
    """The commit a branch name points at: the pushed branch first (what others can check), then a local one."""
    for ref in (f"origin/{branch}", branch):
        try:
            return git(checkout, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").strip()
        except subprocess.CalledProcessError:
            continue
    raise SystemExit(f"definitions: branch {branch!r} is not known to the repository at {checkout}")


def locate(checkout: Path, commit: str, path: str, quote: str, *spellings: str) -> int:
    """The line the quote starts on; `spellings` are other forms of it the file may hold (JSON escapes)."""
    try:
        text = git(checkout, "show", f"{commit}:{path}")
    except subprocess.CalledProcessError:
        raise SystemExit(f"definitions: {path} does not exist at {commit[:10]}")
    at = next((i for i in (text.find(q) for q in (quote, *spellings)) if i >= 0), -1)
    if at < 0:
        raise SystemExit(f"definitions: the quote is no longer in {path} at {commit[:10]}: {quote[:90]!r}")
    return text.count("\n", 0, at) + 1


def report_baselines(roots: list[Path]) -> list[dict]:
    """Baselines a gap report defines itself, quoted from the report file at its checkout's commit."""
    out, seen = [], set()
    for root in roots:
        try:
            commit = git(root, "rev-parse", "HEAD").strip()
            branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
        except subprocess.CalledProcessError:
            continue
        for report in sorted((root / "evidence").glob("*/*/reports/gap_decomposition*.json")):
            rel = report.relative_to(root).as_posix()
            try:
                committed = json.loads(git(root, "show", f"{commit}:{rel}"))
            except (subprocess.CalledProcessError, json.JSONDecodeError):
                continue  # not committed on this checkout: nothing to cite
            for b in committed.get("baselines") or []:
                if not b.get("description") or (committed.get("family"), norm(b["label"])) in seen:
                    continue
                seen.add((committed.get("family"), norm(b["label"])))
                quote = b["description"][:160]
                out.append({"kind": "baseline", "family": committed.get("family"), "value": b.get("key") or norm(b["label"]),
                            "keys": [b["label"]], "label": b["label"], "definition": b["description"],
                            "applies_to": sorted({committed.get("left"), committed.get("right"), report.parent.parent.name} - {None}),
                            "source": {"branch": branch if branch != "HEAD" else commit[:10], "path": rel, "quote": quote,
                                       "commit": commit, "line": locate(root, commit, rel, json.dumps(quote)[1:-1], json.dumps(quote, ensure_ascii=False)[1:-1])},
                            "derived_from": "gap report"})
    return out


def main(out: Path, checkout: Path) -> None:
    entries = json.loads((HERE / "definitions.json").read_text(encoding="utf-8"))["entries"]
    commits: dict[str, str] = {}
    for e in entries:
        src = e["source"]
        commit = commits.setdefault(src["branch"], resolve(checkout, src["branch"]))
        src["commit"], src["line"] = commit, locate(checkout, commit, src["path"], src["quote"])
    have = {(e["family"], norm(k)) for e in entries for k in [e["value"], *e.get("keys", [])]}
    for b in report_baselines([checkout, *extra_checkouts()]):
        if not any((b["family"], norm(k)) in have for k in [b["value"], *b["keys"]]):
            entries.append(b)
    ids = set()
    for e in entries:
        e["id"] = f"{e['kind']}:{e['family']}:{e.get('dimension') or '-'}:{norm(e['value'])}" + (f":{e['scope']}" if e.get("scope") else "")
        if e["id"] in ids:
            raise SystemExit(f"definitions: two entries share the id {e['id']}; give one a dimension or a scope")
        ids.add(e["id"])
    (out / "data").mkdir(parents=True, exist_ok=True)
    body = {"schema": "aeread.examiner.definitions/0.1", "entries": entries}
    (out / "data" / "definitions.json").write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    kinds = {k: sum(e["kind"] == k for e in entries) for k in ("stratum", "baseline")}
    print(f"definitions: {kinds['stratum']} strata and {kinds['baseline']} baselines, every quote found at its commit")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
