"""Sanity checks on a built examiner directory; exit 1 on any hard failure."""
import gzip, json, sys
from pathlib import Path

def load(path: Path):
    d = json.loads(gzip.open(path, "rb").read() if path.suffix == ".gz" else path.read_bytes())
    if isinstance(d, dict) and d.get("encoding") == "gzip+base64":
        import base64
        d = json.loads(gzip.decompress(base64.b64decode(d["payload"])))
    return d

GE = Path(sys.argv[1]); data = GE / "data"
problems, notes = [], []
cat = json.loads((data / "catalog.json").read_text())
idx = json.loads((data / "lens" / "index.json").read_text()) if (data / "lens" / "index.json").exists() else {}
ids = {c["id"] for c in cat["campaigns"]}
for c in cat["campaigns"]:
    for k in ("id", "path", "family", "stem", "chain", "status", "checklist", "order"):
        if k not in c: problems.append(f"{c['id']}: catalog entry lacks {k}")
    if c.get("trajectory_file"):
        f = GE / c["trajectory_file"]
        if not f.exists(): problems.append(f"{c['id']}: trajectory_file missing {c['trajectory_file']}"); continue
        camp = load(f)
        if not camp.get("cases"): problems.append(f"{c['id']}: campaign file has no cases")
        for case in camp.get("cases", [])[:3]:
            for k in ("case_id", "cell_id", "episode_attempt_id", "receipt_sha256"):
                if k not in case: problems.append(f"{c['id']}: case lacks {k}")
            if "steps" not in case and "steps_count" not in case: problems.append(f"{c['id']}: case has neither steps nor steps_count")
        if camp.get("thin") and (idx.get(c["id"]) or {}).get("kind") not in ("sealed", "narrated"): problems.append(f"{c['id']}: thin campaign file without a full lens")
        g = camp.get("graph") or {}
        if not g.get("nodes"): notes.append(f"{c['id']}: empty observed graph")
    m = idx.get(c["id"])
    if m is None: notes.append(f"{c['id']}: no lens index entry")
    elif m.get("file") and not (GE / m["file"]).exists(): problems.append(f"{c['id']}: lens file missing {m['file']}")
for cid in idx:
    if cid not in ids: problems.append(f"lens index names unknown campaign {cid}")
for f in sorted(list(data.rglob("*.json")) + list(data.rglob("*.gz"))):
    sz = f.stat().st_size
    if sz > (15_000_000 if f.suffix == ".gz" else 16_000_000): problems.append(f"{f.relative_to(GE)} is {sz/1e6:.1f}MB (over the artifact file limit)")
total = sum(f.stat().st_size for f in data.rglob("*") if f.is_file())
if total > 60_000_000: notes.append(f"data totals {total/1e6:.1f}MB; the artifact allows 64MB per version")
kinds = {}
for m in idx.values(): kinds[m.get("kind")] = kinds.get(m.get("kind"), 0) + 1
print(f"bundles {len(cat['campaigns'])} | with trajectories {sum(1 for c in cat['campaigns'] if c.get('trajectory_file'))} | lens kinds {kinds} | data {total/1e6:.1f}MB | branch {cat.get('generated_from',{}).get('branch')}")
for n in notes: print("note:", n)
for p in problems: print("PROBLEM:", p)
sys.exit(1 if problems else 0)
