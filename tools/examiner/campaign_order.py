"""Chronological order of every bundle within its family, with the basis stated.

Signals, strongest first: modification time of the sealed receipts this bundle publishes
(when the run root is on this machine), the first commit whose diff mentions the identity,
a date embedded in the identity, a created_date inside its reports.  Also: which other
bundle identities the README names (reads as "refers to"), so the page can show lineage."""
from __future__ import annotations

import datetime
import glob
import json
import os
import re
import subprocess
from pathlib import Path

HEX = re.compile(r"[0-9a-f]{64}")


def _receipt_window(bundle: Path, idx: dict):
    shas = set()
    for f in [bundle / "publication_manifest.json", *bundle.glob("reports/*.json"), *bundle.glob("receipts/*"), *bundle.glob("tables/*")]:
        try:
            shas.update(HEX.findall(f.read_text()))
        except Exception:
            continue
    ts = []
    for s in shas:
        for d in idx.get(s, []):
            f = os.path.join(d, "evaluation_receipt.json")
            if os.path.exists(f):
                ts.append(os.path.getmtime(f))
    if not ts:
        return None
    iso = lambda t: datetime.datetime.fromtimestamp(t).isoformat(timespec="minutes")
    return {"start": iso(min(ts)), "end": iso(max(ts)), "receipts": len(ts)}


def _created_dates(bundle: Path):
    out = set()
    for f in [*bundle.glob("reports/*.json"), *bundle.glob("qc/*.json")]:
        try:
            out.update(re.findall(r'"(?:created_date|generated_at|published_at|run_date|started_at)"\s*:\s*"(\d{4}-\d{2}-\d{2}[^"]*)"', f.read_text()))
        except Exception:
            continue
    return sorted(out)


def _git_first(wt: Path, cid: str):
    r = subprocess.run(["git", "log", "--reverse", "--format=%cI %h %s", "-S" + cid, "--", "."], cwd=wt, capture_output=True, text=True).stdout.split("\n")
    if not r or not r[0]:
        return None
    date, sha, *subject = r[0].split(" ", 2)
    return {"date": date, "commit": sha, "subject": (subject[0] if subject else "")[:90]}


def annotate(catalog: list[dict], wt: Path, idx: dict, roots: dict | None = None) -> None:
    """``roots`` maps a checkout label (a bundle's ``checkout``) to its path; a bundle
    without one lives in ``wt``. Git history is read in the bundle's own checkout."""
    roots = roots or {}
    ids = [c["id"] for c in catalog]
    for c in catalog:
        root = Path(roots.get(c.get("checkout")) or wt)
        bundle = root / c["path"]
        readme = (bundle / "README.md").read_text() if (bundle / "README.md").exists() else ""
        first = re.split(r"(?<=[.!?])\s", re.sub(r"\s+", " ", readme.split("\n\n")[1] if "\n\n" in readme else readme).strip(), 1)[0] if readme else ""
        first = re.sub(r"^#.*?\n", "", first).strip()
        win = _receipt_window(bundle, idx)
        git = _git_first(root, c["id"])
        m = re.search(r"(\d{4}-\d{2}-\d{2})", c["id"])
        created = _created_dates(bundle)
        if win:
            at, basis = win["start"], "sealed receipts on this machine"
        elif git:
            at, basis = git["date"][:16].replace("T", " "), "first commit naming it"
        elif m:
            at, basis = m.group(1), "date in the identity"
        elif created:
            at, basis = created[0], "created_date in its reports"
        else:
            at, basis = None, "unknown"
        c["order"] = {"at": at, "basis": basis, "window": win, "git": git, "id_date": m.group(1) if m else None, "created": created,
                      "refs": [i for i in ids if i != c["id"] and i in readme], "summary": first[:220],
                      "claim": next((f["value"] for f in c.get("facts", []) if f["key"] == "claim_status" and isinstance(f["value"], str)), None)}
    fams = {}
    for c in catalog:
        fams.setdefault(c["family"], []).append(c)
    for fam, members in fams.items():
        members.sort(key=lambda c: ((c["order"]["at"] or "9999"), c.get("version_number") or 0, c["id"]))
        for i, c in enumerate(members):
            c["order"].update({"rank": i + 1, "of": len(members), "prev": members[i - 1]["id"] if i else None, "next": members[i + 1]["id"] if i + 1 < len(members) else None})
    # a bundle whose README names another bundle "refers to" it; mark the reverse ("referred by")
    by_id = {c["id"]: c for c in catalog}
    for c in catalog:
        for r in c["order"]["refs"]:
            by_id[r]["order"].setdefault("referred_by", []).append(c["id"])


if __name__ == "__main__":
    import sys
    ge, wt, idx_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    cat_path = ge / "data" / "catalog.json"
    cat = json.loads(cat_path.read_text())
    roots_file = Path(__file__).with_name("roots.json")
    annotate(cat["campaigns"], wt, json.loads(idx_path.read_text()), roots=json.loads(roots_file.read_text()) if roots_file.exists() else None)
    cat_path.write_text(json.dumps(cat, separators=(",", ":"), default=str))
    from collections import Counter
    print("basis:", Counter(c["order"]["basis"] for c in cat["campaigns"]))
    for c in sorted(cat["campaigns"], key=lambda c: (c["family"], c["order"]["rank"])):
        if c["family"] == "datacenter_development_terms":
            print(f"  #{c['order']['rank']:2} {c['order']['at'] or '—':17} {c['id'][:55]:55} refs={c['order']['refs']} | {c['order']['summary'][:70]}")
