"""The analysis declared in docs/families/datacenter/agreement_signalling_plan_2026-10.md, and nothing else.

    PYTHONPATH=src python tools/cli_subjects/agreement_signalling_test.py OUT.json RUNS_ROOT

Reads the three run directories under RUNS_ROOT (``agreement_cli_signal_swap_client_v1``,
``agreement_cli_signal_swap_integrator_v1``, ``agreement_cli_signal_reader_v1``); calls no model. This file was
committed before those runs finished: the measures, exclusions and tests are the plan's.
"""

from __future__ import annotations

import glob
import json
import math
import statistics as st
import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from scipy import stats

from aeread_families.datacenter_development import agreement as ag
from aeread_families.datacenter_development import agreement_negotiator as an
from aeread_families.datacenter_development import agreement_pack as ap
from aeread_families.datacenter_development import agreement_reader as rd
from aeread_families.datacenter_development import risk_allocation_contracts as rc

sys.path.insert(0, str(Path(__file__).parent))
import agreement_notes as nt  # noqa: E402

NAME = {"codex_sol61": "Sol 6.1", "claude_opus55": "Opus 5.5"}
MIN_GAP = 25.0


def cells(run: Path):
    plan = json.loads((run / "campaign_plan.json").read_text())
    _, raw = ap.load(plan["pack"])
    by_id = {c["case_id"]: c for c in raw.values()}
    for f in sorted(glob.glob(f"{run}/cells/*.json")):
        c = json.loads(Path(f).read_text())
        g = c.get("grade") or {}
        case = by_id[c["case_id"]]
        cw, it = rc.world_from({k: case["payload"][k] for k in ("world", "integrator_type", "extras")})
        yield c, g, case, cw, it, c["status"] == "ok" and bool(g.get("valid"))


def replay(run: Path, c, cw):
    """The states before and after each move, with the move."""
    state, out = ag.initial_state(cw), []
    for m in nt.moves(run, c["cell_key"]):
        act = {"action": m["action"], "note": m["note"], "price": m["price"], "clauses": {k: m["changes"].get(k) for k in ag.TERMS} if m["action"] == "redline" else None}
        nxt = ag.apply(state, act, cw)
        out.append((state, act, nxt))
        state = nxt
    return out


def test(values):
    """Mean, 95% interval and two-sided p of a one-sample t test against zero."""
    v = [float(x) for x in values]
    n = len(v)
    if n < 3:
        return {"n": n, "mean": st.fmean(v) if v else float("nan"), "low": float("nan"), "high": float("nan"), "p": float("nan")}
    m, sd = st.fmean(v), st.stdev(v)
    half = stats.t.ppf(0.975, n - 1) * sd / math.sqrt(n)
    return {"n": n, "mean": m, "low": m - half, "high": m + half, "p": float(stats.ttest_1samp(v, 0.0).pvalue)}


def joint(cw, it, terms, charge):
    return an._outside(cw, charge) - cw.w.terms.floor_margin - rc.integrator_cost(terms, cw.w, it, cw.x) - rc.client_cost(terms, cw.w, it, cw.x, charge)


def swap_client(run: Path):
    per = defaultdict(lambda: defaultdict(lambda: {"s": [], "prot": [], "terms": []}))  # (model, world) -> type -> lists
    counts = defaultdict(lambda: defaultdict(int))
    facts = {}
    for c, g, case, cw, it, ok in cells(run):
        model = NAME[c["client"]]
        if not ok:
            counts[model]["failed"] += 1
            continue
        moves = replay(run, c, cw)
        if not moves or moves[0][1]["action"] != "redline":
            counts[model]["script did not open"] += 1
            continue
        if len(moves) < 2:
            counts[model]["no reply read"] += 1
            continue
        _, act, after = moves[1]
        charges = sorted(ch for ch, _ in cw.w.client_prior)
        low, high = charges[0], charges[-1]
        mine = "high" if cw.w.client.risk_charge == high else "low"
        counts[model][f"replies: {act['action']}"] += 1
        counts[model][f"replies under the {mine} charge: {act['action']}"] += 1
        if act["action"] == "walk":
            continue
        opened = moves[0][2]
        terms = rc.Contract(**(after["terms"] if act["action"] == "redline" else opened["terms"]))
        price = act["price"] if act["action"] == "redline" else opened["standing"]["price"]
        l_low, l_high = rd.client_limit(cw, it, terms, low), rd.client_limit(cw, it, terms, high)
        slot = per[(model, case["world_seed"])][mine]
        slot["prot"].append(rd.protection(terms))
        slot["terms"].append(terms)
        if abs(l_high - l_low) >= MIN_GAP:
            slot["s"].append((price - l_low) / (l_high - l_low))
        else:
            counts[model]["replies left out of the price position (limits under 25 apart)"] += 1
        facts[case["world_seed"]] = (cw, it, low, high)
    out = {"counts": {m: dict(v) for m, v in counts.items()}, "worlds": {}}
    for (model, world), types in per.items():
        row = {}
        if types["low"]["s"] and types["high"]["s"]:
            row["pass_through"] = st.fmean(types["high"]["s"]) - st.fmean(types["low"]["s"])
            row["s_low"], row["s_high"] = st.fmean(types["low"]["s"]), st.fmean(types["high"]["s"])  # for the figure; the tests use the difference
        if types["low"]["prot"] and types["high"]["prot"]:
            row["clause_shift"] = st.fmean(types["high"]["prot"]) - st.fmean(types["low"]["prot"])
            row["clauses_low"], row["clauses_high"] = st.fmean(types["low"]["prot"]), st.fmean(types["high"]["prot"])
            cw, it, low, high = facts[world]
            j = lambda ts, ch: st.fmean(joint(cw, it, t, ch) for t in ts)
            row["tailoring_value"] = 0.5 * ((j(types["high"]["terms"], high) - j(types["low"]["terms"], high)) + (j(types["low"]["terms"], low) - j(types["high"]["terms"], low)))
        out["worlds"].setdefault(model, {})[str(world)] = row
    return out


def swap_integrator(run: Path):
    per = defaultdict(lambda: defaultdict(list))
    counts = defaultdict(lambda: defaultdict(int))
    for c, g, case, cw, it, ok in cells(run):
        model = NAME[c["integrator"]]
        if not ok:
            counts[model]["failed"] += 1
            continue
        moves = replay(run, c, cw)
        if not moves:
            counts[model]["no opening read"] += 1
            continue
        _, act, after = moves[0]
        counts[model][f"openings: {act['action']}"] += 1
        if act["action"] != "redline":
            continue
        costs = sorted({t.test_cost for t in cw.types})
        terms = rc.Contract(**after["terms"])
        lim = lambda cost: rc.integrator_cost(terms, cw.w, replace(it, test_cost=cost), cw.x) + cw.w.terms.floor_margin
        l_low, l_high = lim(costs[0]), lim(costs[-1])
        if abs(l_high - l_low) < MIN_GAP:
            counts[model]["openings left out of the price position (limits under 25 apart)"] += 1
            continue
        per[(model, case["world_seed"])]["high" if it.test_cost == costs[-1] else "low"].append((act["price"] - l_low) / (l_high - l_low))
    out = {"counts": {m: dict(v) for m, v in counts.items()}, "worlds": {}}
    for (model, world), types in per.items():
        if types["low"] and types["high"]:
            out["worlds"].setdefault(model, {})[str(world)] = {"pass_through": st.fmean(types["high"]) - st.fmean(types["low"])}
    return out


def readers(run: Path):
    earned = defaultdict(dict)  # (model, world) -> arm -> earnings
    extra = defaultdict(lambda: defaultdict(int))
    for c, g, case, cw, it, ok in cells(run):
        model = NAME[c["client"]]
        arm = "silent" if "negotiator_drawn" in c["pairing"] else "reads price" if "reader_price" in c["pairing"] else "reads clauses"
        if not ok:
            extra[(model, arm)]["failed"] += 1
            continue
        if g["available_surplus"] <= 1e-6:
            extra[(model, arm)]["no-deal worlds"] += 1
            extra[(model, arm)]["no-deal worlds walked"] += g["termination"] == "walked"
            continue
        earned[(model, case["world_seed"])][arm] = g["client_surplus"]
        extra[(model, arm)]["deal worlds"] += 1
        extra[(model, arm)]["signed"] += g["termination"] == "signed"
        extra[(model, arm)]["signed below its walk-away point"] += bool(g["client_ir_violation"])
        if arm != "silent":
            channel = "price" if arm == "reads price" else "clauses"
            for before, act, after in replay(run, c, cw):
                if before["to_move"] == "client" and act["action"] == "redline":
                    belief = rd.Reader(cw, it, channel, "codex" if model == "Sol 6.1" else "claude").belief(after)
                    guess = max(belief, key=lambda o: o.p).charge
                    extra[(model, arm)]["first offers read"] += 1
                    extra[(model, arm)]["most likely type was the true one"] += guess == cw.w.client.risk_charge
                    break
    return {"earned": {f"{m}|{w}": v for (m, w), v in earned.items()}, "extra": {f"{m}|{a}": dict(v) for (m, a), v in extra.items()}}


def holm(ps):
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adj, running = [0.0] * len(ps), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(ps) - rank) * ps[i]))
        adj[i] = running
    return adj


def main(argv):
    out_path, root = Path(argv[0]), Path(argv[1])
    sc = swap_client(root / "agreement_cli_signal_swap_client_v1")
    si = swap_integrator(root / "agreement_cli_signal_swap_integrator_v1")
    reader_run = root / "agreement_cli_signal_reader_v1"
    rr = readers(reader_run) if (reader_run / "cells").exists() else {"earned": {}, "extra": {}}
    col = lambda model, key: {w: r[key] for w, r in sc["worlds"].get(model, {}).items() if key in r}
    paired = lambda a, b: [a[w] - b[w] for w in sorted(set(a) & set(b))]
    cost = lambda model, arm: [v[arm] - v["silent"] for k, v in rr["earned"].items() if k.startswith(model + "|") and arm in v and "silent" in v]
    primary = {
        "P1a Opus price pass-through > 0": (test(col("Opus 5.5", "pass_through").values()), +1),
        "P1b Opus pass-through > Sol's": (test(paired(col("Opus 5.5", "pass_through"), col("Sol 6.1", "pass_through"))), +1),
        "P2a Sol clause shift > 0": (test(col("Sol 6.1", "clause_shift").values()), +1),
        "P2b Sol clause shift > Opus's": (test(paired(col("Sol 6.1", "clause_shift"), col("Opus 5.5", "clause_shift"))), +1),
        "P3a Opus earns less against the price reader": (test(cost("Opus 5.5", "reads price")), -1),
        "P3b Sol earns less against the clause reader": (test(cost("Sol 6.1", "reads clauses")), -1),
    }
    ps = [t["p"] if not math.isnan(t["p"]) else 1.0 for t, _ in primary.values()]
    for (name, (t, sign)), adj in zip(primary.items(), holm(ps)):
        t["holm_p"] = adj
        t["verdict"] = "no data" if t["n"] < 3 else "supported" if adj < 0.05 and t["mean"] * sign > 0 else "contradicted" if adj < 0.05 else "not supported"
    secondary = {
        "Sol price pass-through": test(col("Sol 6.1", "pass_through").values()), "Opus clause shift": test(col("Opus 5.5", "clause_shift").values()),
        "Sol: value of tailoring its clauses": test(col("Sol 6.1", "tailoring_value").values()), "Opus: value of tailoring its clauses": test(col("Opus 5.5", "tailoring_value").values()),
        "Sol against the price reader": test(cost("Sol 6.1", "reads price")), "Opus against the clause reader": test(cost("Opus 5.5", "reads clauses")),
        **{f"{m}: integrator's pass-through of its pre-staging cost": test([r["pass_through"] for r in si["worlds"].get(m, {}).values()]) for m in NAME.values()},
    }
    result = {"primary": {k: v[0] for k, v in primary.items()}, "secondary": secondary, "swap_client_counts": sc["counts"], "swap_integrator_counts": si["counts"], "reader_extra": rr["extra"],
              "swap_client_worlds": sc["worlds"], "reader_earned": rr["earned"]}
    out_path.write_text(json.dumps(result, indent=1))
    fmt = lambda t: f"{t['mean']:8.2f} [{t['low']:7.2f}, {t['high']:7.2f}] n={t['n']:2d} p={t['p']:.4f}" if t["n"] >= 3 else f"n={t['n']}"
    print("PRIMARY")
    for k, v in result["primary"].items():
        print(f"  {k:48} {fmt(v)}  holm={v['holm_p']:.4f}  {v['verdict']}")
    print("SECONDARY")
    for k, v in secondary.items():
        print(f"  {k:58} {fmt(v)}")
    for label in ("swap_client_counts", "swap_integrator_counts", "reader_extra"):
        print(label, json.dumps(result[label]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
