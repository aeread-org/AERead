"""Is each stratum split more than noise? The page's test, run offline over a whole build.

    python3 strata_noise.py <build dir> [--json out.json]

For every model-comparison case (data/model_comparisons.json) and every declared stratum dimension, and for every
gap report split by stratum (data/case_cards.json), the same permutation test the page draws under each split:
the spread of the stratum means of the per-unit paired difference (units times squared distance from the grand
mean) against 2000 shuffles of the stratum labels, across independent clusters when each unit sits in one stratum,
within each unit when every unit was run in several. A stratum holding one independent unit, or a split over fewer
than 5 clusters, is not testable. Pairing follows the page (matched seeds within a unit, the strata not tested
averaged equally within the unit, equal weight per unit; the two models with most cells; the first reasoning arm
both models ran, unless the arm is what is tested).

Two tests per split: `gap`, whether the difference between the two models changes across strata (the question a
reported split answers), and `level`, whether the two models' mean score changes across strata (whether the
stratum makes worlds easier or harder, which matters for coverage even when it does not separate models). The
shuffles use Python's generator, so p values match the page's within Monte Carlo error (about 0.005 at p = 0.05),
not digit for digit. Families the owner has marked not ready are skipped, as on the page.
"""

from __future__ import annotations

import base64
import collections
import gzip
import json
import random
import statistics
import sys
from pathlib import Path

HIDDEN = {"datacenter_development_terms", "commercial_state_calibration", "procurement_grounding"}
N_SHUFFLES, MIN_CLUSTERS = 2000, 5


def load(path: Path):
    j = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(j, dict) and j.get("encoding") == "gzip+base64":
        return json.loads(gzip.decompress(base64.b64decode(j["payload"])))
    return j


def split_test(items: list[dict], seed: str) -> dict | None:
    """items: {u: unit, c: cluster, st: stratum, d: value}, one per unit and stratum."""
    strata = sorted({x["st"] for x in items}, key=str)
    if len(strata) < 2:
        return None
    units = collections.defaultdict(list)
    for i, x in enumerate(items):
        units[x["u"]].append(i)
    between = all(len(v) == 1 for v in units.values())
    clusters = sorted({x["c"] for x in items}, key=str)
    min_c = min(len({x["c"] for x in items if x["st"] == v}) for v in strata)
    base = {"k": len(strata), "clusters": len(clusters), "between": between, "min_clusters": min_c}
    if between and min_c < 2:
        return {**base, "kind": "one"}
    if len(clusters) < MIN_CLUSTERS:
        return {**base, "kind": "few"}

    def spread(labels):
        tot = collections.defaultdict(float); n = collections.Counter()
        for x, lab in zip(items, labels):
            tot[lab] += x["d"]; n[lab] += 1
        g = sum(x["d"] for x in items) / len(items)
        return sum(n[v] * (tot[v] / n[v] - g) ** 2 for v in n)

    rng = random.Random(seed)
    observed = spread([x["st"] for x in items]); ge = 0
    if between:
        lab_of = {}
        for x in items:
            lab_of.setdefault(x["c"], x["st"])
        whole = all(lab_of[x["c"]] == x["st"] for x in items)
        for _ in range(N_SHUFFLES):
            if whole:
                ls = [lab_of[c] for c in clusters]; rng.shuffle(ls); m = dict(zip(clusters, ls))
                labels = [m[x["c"]] for x in items]
            else:
                labels = [x["st"] for x in items]; rng.shuffle(labels)
            ge += spread(labels) >= observed - 1e-9
    else:
        groups = [g for g in units.values() if len(g) > 1]
        for _ in range(N_SHUFFLES):
            labels = [x["st"] for x in items]
            for g in groups:
                ls = [items[i]["st"] for i in g]; rng.shuffle(ls)
                for i, lab in zip(g, ls):
                    labels[i] = lab
            ge += spread(labels) >= observed - 1e-9
    return {**base, "kind": "test", "p": (1 + ge) / (1 + N_SHUFFLES)}


def per_unit(s: dict, mkey: str, a: str, b: str, dim: str, fix: dict | None) -> tuple[list[dict], list[dict]]:
    """Per (unit, stratum of `dim`): the paired difference a - b, and the two models' mean, as the page pairs them."""
    ci = {c: i for i, c in enumerate(s["cols"])}
    meas = next(m for m in s["measures"] if m["key"] == mkey)
    matched = s.get("matched", True) is not False and not meas.get("own_cells")
    rest = [d["key"] for d in s["dims"] if d["key"] != dim]
    clusters = s.get("clusters") or {}
    tree = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(list))))
    for r in s["rows"]:
        m, v = r[ci["model"]], r[ci[mkey]]
        if m not in (a, b) or v is None or (fix and any(r[ci[k]] != val for k, val in fix.items())):
            continue
        tree[(r[ci[dim]], r[ci["unit"]])][tuple(r[ci[k]] for k in rest)][m][r[ci["rep"]]].append(v)
    diffs, levels = [], []
    for (st, u), combos in tree.items():
        xs, ys = [], []
        for models in combos.values():
            ma, mb = models.get(a), models.get(b)
            if not ma or not mb:
                continue
            if matched:
                common = [k for k in ma if k in mb]
                if not common:
                    continue
                xs.append(statistics.mean(statistics.mean(ma[k]) for k in common)); ys.append(statistics.mean(statistics.mean(mb[k]) for k in common))
            else:
                xs.append(statistics.mean(v for vs in ma.values() for v in vs)); ys.append(statistics.mean(v for vs in mb.values() for v in vs))
        if xs:
            c = clusters.get(u, u)
            diffs.append({"u": u, "c": c, "st": st, "d": statistics.mean(x - y for x, y in zip(xs, ys))})
            levels.append({"u": u, "c": c, "st": st, "d": statistics.mean((x + y) / 2 for x, y in zip(xs, ys))})
    return diffs, levels


def default_pair(s: dict) -> tuple[str, str]:
    cells = collections.Counter(r[1] for r in s["rows"])
    label = {m["key"]: m.get("label") or m["key"] for m in s["models"]}
    top = sorted((m["key"] for m in s["models"]), key=lambda k: -cells[k])[:2]
    return tuple(sorted(top, key=lambda k: label[k]))


def pick(s: dict, a: str, b: str) -> tuple[dict | None, list[str]]:
    """The reasoning-arm menu's default: the first arm both models ran, in the order the design declares."""
    d = next((d for d in s["dims"] if d.get("pick") is True or d["key"] == "arm"), None)
    if not d:
        return None, []
    ci = {c: i for i, c in enumerate(s["cols"])}
    ran = collections.defaultdict(set)
    for r in s["rows"]:
        if r[ci["model"]] in (a, b):
            ran[r[ci[d["key"]]]].add(r[ci["model"]])
    both = [v["v"] for v in d["values"] if len(ran.get(v["v"], ())) == 2]
    return ({d["key"]: both[0]} if both else None), both


def comparison_tests(mc: dict, fam_of: dict) -> list[dict]:
    out = []
    for s in mc["sets"]:
        if all(fam_of.get(c) in HIDDEN or fam_of.get(c) is None for c in s["campaigns"]):
            continue
        meas = next((m for m in s["measures"] if m.get("primary")), s["measures"][0])
        a, b = default_pair(s)
        fix, both = pick(s, a, b)
        arm = next(iter(fix)) if fix else None
        for d in s["dims"]:
            is_arm = d["key"] == arm or (d.get("pick") is True)
            if is_arm and len(both) < 2:
                continue
            f = None if is_arm else fix
            diffs, levels = per_unit(s, meas["key"], a, b, d["key"], f)
            seed = "|".join([s["id"], meas["key"], d["key"], a, b, json.dumps(f)])
            gap, lev = split_test(diffs, seed + "|gap"), split_test(levels, seed + "|level")
            if gap is None and lev is None:
                continue
            strata = collections.defaultdict(list)
            for x in diffs:
                strata[x["st"]].append(x["d"])
            out.append({"source": "comparison", "family": s["family"], "case": s["title"], "id": s["id"], "dimension": d["label"],
                        "dim_key": d["key"], "measure": meas["label"], "pair": f"{a} - {b}", "arm_fixed": f,
                        "units": len({x["u"] for x in diffs}), "gap": gap, "level": lev,
                        "strata": {str(k): round(statistics.mean(v), 3) for k, v in strata.items()}})
    return out


def gap_tests(cards: dict) -> list[dict]:
    out = []
    for key, g in (cards.get("gaps") or {}).items():
        if "refs" in g or "ref" in g:
            continue
        cp = g.get("cell_parts") or {}
        if not isinstance(cp, dict) or not cp.get("compact"):
            continue
        by_world = collections.defaultdict(lambda: {"left": [], "right": [], "st": None})
        for r in cp["rows"]:
            w = r[5] if r[5] is not None else r[3]
            by_world[w][r[0]].append(sum(r[7])); by_world[w]["st"] = by_world[w]["st"] or r[6]
        items = [{"u": w, "c": w, "st": v["st"], "d": statistics.mean(v["left"]) - statistics.mean(v["right"])}
                 for w, v in by_world.items() if v["left"] and v["right"] and v["st"] not in (None, "")]
        t = split_test(items, key + "|pair")
        if t:
            strata = collections.defaultdict(list)
            for x in items:
                strata[x["st"]].append(x["d"])
            out.append({"source": "gap", "family": g.get("family"), "case": g.get("title") or "Why they differ", "id": key,
                        "dimension": "gap stratum", "measure": g.get("endpoint"), "units": len(items), "gap": t, "level": None,
                        "strata": {str(k): round(statistics.mean(v), 3) for k, v in strata.items()}})
    return out


def fmt(t: dict | None) -> str:
    if not t:
        return "-"
    if t["kind"] == "one":
        return f"one {'world' if t['min_clusters'] == 1 else 'cluster'} per stratum"
    if t["kind"] == "few":
        return f"{t['clusters']} clusters"
    return f"p {t['p']:.3f}{' *' if t['p'] < 0.05 else ''}"


def main(build: Path, json_out: Path | None) -> None:
    data = build / "data"
    cat = load(data / "catalog.json")
    fam_of = {c["id"]: c["family"] for c in cat["campaigns"]}
    rows = comparison_tests(load(data / "model_comparisons.json"), fam_of) + gap_tests(load(data / "case_cards.json"))
    testable = [r for r in rows if r["gap"] and r["gap"]["kind"] == "test"]
    for r in rows:
        print(f"{r['family'][:14]:14} | {r['case'][:52]:52} | {r['dimension'][:24]:24} | units {r['units']:3} | gap {fmt(r['gap']):22} | level {fmt(r['level'])}")
    print(f"\n{len(rows)} splits; {len(testable)} testable for the gap; {sum(r['gap']['p'] < 0.05 for r in testable)} at p < 0.05 "
          f"({0.05 * len(testable):.1f} expected by chance)")
    if json_out:
        json_out.write_text(json.dumps(rows, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    args = sys.argv[1:]
    out = Path(args[args.index("--json") + 1]) if "--json" in args else None
    main(Path(args[0]), out)
