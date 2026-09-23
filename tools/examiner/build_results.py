"""Quantitative results per bundle, in a shape the page can chart without knowing the family.

For every bundle: record tables (arrays of dicts, dicts of dicts, JSONL and CSV tables, long-format
metric tables pivoted wide), interval estimates (a point with a [lo, hi] bootstrap interval), headline
scalars, and the per-case outcome rows already joined to the campaign file.  Output: data/results/<id>.json
(gzip+base64 envelope) and data/results/index.json.

Usage: build_results.py <general_examiner dir> <worktree>
"""
from __future__ import annotations

import base64
import csv
import gzip
import json
import re
import sys
from pathlib import Path

GE = Path(sys.argv[1]); WT = Path(sys.argv[2])
OUT = GE / "data" / "results"; OUT.mkdir(parents=True, exist_ok=True)
LABELS = ["model_id", "model", "route", "candidate_id", "arm", "condition", "surface", "world", "world_id", "case_id", "case", "scenario",
          "supplier_id", "name", "id", "label", "track", "policy", "profile_id", "stratum", "archetype", "treatment", "seat_id", "leaf_id", "metric_name"]
ID_LIKE = re.compile(r"sha256|_sha$|^id$|_id$|ordinal|_index$|^index$|^seed$|world_seed|fact_id|run_id|task_id|block_id|receipt", re.I)
HEADLINE = re.compile(r"rate|mean|delta|score|margin|npv|regret|admission|effect|fraction|share|median|total_cost|cost_usd|count", re.I)
ROW_CAP, NUM_CAP, CAT_CAP = 400, 16, 6


def unpack(path: Path):
    d = json.loads(path.read_text())
    if isinstance(d, dict) and d.get("encoding") == "gzip+base64":
        d = json.loads(gzip.decompress(base64.b64decode(d["payload"])))
    return d


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def coerce(v):
    """CSV cell -> number/bool/None/string."""
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    try:
        f = float(s)
        return int(f) if re.fullmatch(r"-?\d+", s) else f
    except ValueError:
        return s


def make_table(rows: list, file: str, path: str, note: str = ""):
    rows = [r for r in rows if isinstance(r, dict)]
    if len(rows) < 2:
        return None
    nums, cats = {}, {}
    for r in rows:
        for k, v in r.items():
            if ID_LIKE.search(k) and k not in ("inference_seed",):
                continue
            if is_num(v):
                nums[k] = nums.get(k, 0) + 1
            elif isinstance(v, (str, bool)) or k == "inference_seed":
                cats.setdefault(k, set()).add(str(v))
    num_fields = [k for k, n in sorted(nums.items(), key=lambda kv: -kv[1]) if n >= max(2, len(rows) // 3) and k != "inference_seed"][:NUM_CAP]
    if not num_fields:
        return None
    cat_fields = [k for k, vals in cats.items() if 2 <= len(vals) <= 24 and k not in num_fields and not re.search(r"refs|metadata|reasons|sha|path|file|message|content", k, re.I)][:CAT_CAP]
    label = next((l for l in LABELS if l in rows[0] and l not in num_fields), None)
    total = len(rows)
    if total > ROW_CAP:
        step = total / ROW_CAP
        rows = [rows[int(i * step)] for i in range(ROW_CAP)]
        note = (note + " · " if note else "") + f"{ROW_CAP} of {total} rows sampled evenly"
    keep = set(num_fields) | set(cat_fields) | ({label} if label else set())
    out_rows = [{k: (v if (is_num(v) or isinstance(v, bool) or v is None) else str(v)[:80]) for k, v in r.items() if k in keep} for r in rows]
    return {"file": file, "path": path, "rows": out_rows, "row_count": total, "numeric": num_fields, "categorical": cat_fields, "label": label, "note": note}


def pivot_long(rows: list, file: str):
    """A long metric table (metric_name, value, ...) -> one wide row per (case, seat, leaf)."""
    keys = ["case_id", "task_id", "seat_id", "leaf_id", "block_id", "inclusion_status", "metric_role"]
    wide: dict = {}
    for r in rows:
        v = coerce(r.get("value"))
        if not is_num(v):
            continue
        ident = tuple(str(r.get(k, "")) for k in ("case_id", "task_id", "seat_id"))
        w = wide.setdefault(ident, {k: r.get(k) for k in keys if r.get(k) not in (None, "")})
        w[str(r.get("metric_name"))] = v
    return make_table(list(wide.values()), file, "pivot(metric_name → value)", "long metric table pivoted wide")


def walk(node, file: str, path: str, tables: list, intervals: list, headline: list, depth: int = 0):
    if depth > 5:
        return
    if isinstance(node, list):
        if len(node) >= 2 and all(isinstance(x, dict) for x in node[:5]):
            t = make_table(node, file, path)
            if t:
                tables.append(t)
            return
        for i, x in enumerate(node[:3]):
            walk(x, file, f"{path}[{i}]", tables, intervals, headline, depth + 1)
        return
    if not isinstance(node, dict):
        return
    # a point estimate with a bootstrap / confidence interval next to it
    iv_key = next((k for k in node if re.search(r"interval|confidence|_ci$|^ci", k, re.I) and isinstance(node[k], list) and len(node[k]) == 2 and all(is_num(x) for x in node[k])), None)
    if iv_key:
        point_key = next((k for k in node if re.search(r"mean|point|estimate|effect|value|median", k, re.I) and is_num(node[k])), None)
        n_key = next((k for k in node if re.search(r"count|^n$|resamples", k, re.I) and is_num(node[k])), None)
        intervals.append({"file": file, "path": path, "point": node[point_key] if point_key else None, "lo": node[iv_key][0], "hi": node[iv_key][1],
                          "n": node[n_key] if n_key else None, "interval_key": iv_key})
    # dict of dicts with numeric fields -> keyed table
    vals = [v for v in node.values() if isinstance(v, dict)]
    if len(vals) >= 2 and len(vals) >= 0.6 * len(node) and all(any(is_num(x) for x in v.values()) for v in vals) and not any(is_num(v) for v in node.values()):
        rows = [{"key": k, **v} for k, v in node.items() if isinstance(v, dict)]
        if not any(re.search(r"interval|confidence", kk, re.I) for r in rows for kk in r):
            t = make_table(rows, file, path + " (keyed)", "one row per key")
            if t:
                t["label"] = "key"; tables.append(t)
    if depth <= 1:
        for k, v in node.items():
            if is_num(v) and HEADLINE.search(k) and not ID_LIKE.search(k):
                headline.append({"file": file, "path": f"{path}.{k}" if path else k, "value": v})
    for k, v in node.items():
        if isinstance(v, (dict, list)):
            walk(v, file, f"{path}.{k}" if path else k, tables, intervals, headline, depth + 1)


catalog = json.loads((GE / "data" / "catalog.json").read_text())
index = {}
for c in catalog["campaigns"]:
    bundle = WT / c["path"]
    tables, intervals, headline = [], [], []
    hints: list = []  # what the bundle itself names as the guarded / primary metric
    def collect_hints(node, depth=0):
        if depth > 4 or not isinstance(node, dict):
            return
        for k, v in node.items():
            if re.search(r"guarded_metric|primary_metric|primary_estimand|primary_outcome|primary_leaf", k, re.I):
                strong = bool(re.search(r"guarded_metric|primary_estimand|primary_metric", k, re.I))
                for x in (v if isinstance(v, list) else [v]):
                    if isinstance(x, str) and x not in hints:
                        hints.insert(0, x) if strong else hints.append(x)
            if isinstance(v, dict):
                collect_hints(v, depth + 1)
    for f in sorted(bundle.glob("reports/*.json")) + sorted(bundle.glob("tables/*.json")):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        collect_hints(d)
        ctx = {k: d[k] for k in ("arm", "condition", "model_id", "surface", "candidate_id", "stratum", "route", "treatment") if isinstance(d.get(k), str)} if isinstance(d, dict) else {}
        if ctx and isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, list) and len(v) >= 2 and all(isinstance(x, dict) for x in v[:5]):
                    d[k] = [{**ctx, **x} for x in v]
        walk(d, str(f.relative_to(bundle)), "", tables, intervals, headline)
    for f in sorted(bundle.glob("tables/*.jsonl")):
        rows = []
        for line in f.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
        flat_rows = []
        for r in rows:  # flatten one level, as the campaign builder does for outcome rows
            fr = {}
            for k, v in r.items():
                if isinstance(v, dict):
                    for kk, vv in v.items():
                        if not isinstance(vv, (dict, list)):
                            fr[f"{k}.{kk}"] = vv
                elif not isinstance(v, list):
                    fr[k] = v
            flat_rows.append(fr)
        t = make_table(flat_rows, str(f.relative_to(bundle)), "rows")
        if t:
            tables.append(t)
    for f in sorted(bundle.glob("tables/*.csv")):
        try:
            with open(f, newline="") as fh:
                rows = [{k: coerce(v) for k, v in r.items()} for r in csv.DictReader(fh)]
        except Exception:
            continue
        if rows and "metric_name" in rows[0] and "value" in rows[0]:
            t = pivot_long(rows, str(f.relative_to(bundle)))
        else:
            t = make_table(rows, str(f.relative_to(bundle)), "rows")
        if t:
            tables.append(t)
    # per-case outcome rows from the campaign file (bundle tables joined by receipt)
    tf = c.get("trajectory_file")
    if tf and (GE / tf).exists():
        camp = unpack(GE / tf)
        rows = []
        for k in camp.get("cases", []):
            r = {kk: (coerce(vv) if isinstance(vv, str) else vv) for kk, vv in (k.get("outcome_row") or {}).items()}
            r["case_id"] = k.get("case_id"); r["steps"] = k.get("steps_count") if "steps_count" in k else len(k.get("steps") or [])
            r["invalid_steps"] = k.get("invalid_steps"); r["provider_cost_usd"] = k.get("cost")
            m = re.match(r"^(.*?)[._](\d+)$", str(k.get("case_id", "")))
            r["archetype"] = (m.group(1).split(".")[-1] if m else str(k.get("case_id", "")).split(".")[-1])
            rows.append(r)
        t = make_table(rows, tf.split("/")[-1], "cases", "one row per sealed case: bundle tables joined by receipt, plus steps and provider cost")
        if t:
            t["label"] = "case_id"; tables.insert(0, t)
    # dedupe identical tables; merge same-schema row tables published per arm/condition into one table
    seen = set(); uniq = []
    for t in tables:
        key = (t["file"], t["path"])
        if key in seen:
            continue
        seen.add(key); uniq.append(t)
    merged = []; by_schema: dict = {}
    for t in uniq:
        sig = (t["path"], tuple(t["numeric"]), t["label"])
        if t["path"] == "rows" and t["file"].startswith("reports/") and t["row_count"] >= 4:
            by_schema.setdefault(sig, []).append(t)
        else:
            merged.append(t)
    for sig, group in by_schema.items():
        if len(group) == 1:
            merged.append(group[0]); continue
        rows = []
        for t in group:
            src = t["file"].split("/")[-1].rsplit(".", 1)[0]
            rows.extend([{"source": src, **r} for r in t["rows"]])
        m = make_table(rows, " + ".join(t["file"].split("/")[-1] for t in group), "rows (merged across files)", f"{len(group)} same-schema row tables merged; 'source' names the file")
        if m:
            m["label"] = group[0]["label"]; merged.append(m)
        else:
            merged.extend(group)
    uniq = merged
    uniq.sort(key=lambda t: (t["path"] != "cases", -t["row_count"]))
    hl = []; seen_h = set()
    for h in headline:
        if h["path"] not in seen_h:
            seen_h.add(h["path"]); hl.append(h)
    data = {"campaign_id": c["id"], "family": c["family"], "primary_hints": hints[:8], "tables": uniq[:24], "intervals": intervals[:60], "headline": hl[:40]}
    raw = json.dumps(data, separators=(",", ":"), default=str).encode()
    (OUT / f"{c['id']}.json").write_text(json.dumps({"encoding": "gzip+base64", "raw_bytes": len(raw), "payload": base64.b64encode(gzip.compress(raw, 9)).decode()}, separators=(",", ":")))
    index[c["id"]] = {"file": f"data/results/{c['id']}.json", "tables": len(uniq[:24]), "intervals": len(intervals[:60]), "headline": len(hl[:40]), "raw_bytes": len(raw)}
(OUT / "index.json").write_text(json.dumps(index, indent=1))
tot = sum((OUT / f).stat().st_size for f in [p.name for p in OUT.glob("*.json")])
print(f"results: {len(index)} bundles, {sum(v['tables'] for v in index.values())} tables, {sum(v['intervals'] for v in index.values())} intervals, {sum(v['headline'] for v in index.values())} headline numbers, {tot/1e6:.1f}MB packed")
