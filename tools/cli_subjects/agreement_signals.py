"""What a model's first offer reveals about its private type, with no words involved.

    PYTHONPATH=src python tools/cli_subjects/agreement_signals.py OUT.json

Reads the run directories listed in ``RUNS``; calls no model. For each model seat it reports how far the first
offer's price moves with the seat's own private limit, how often one offer rules out or pins a declared type, and
how the number of clauses protecting the client varies with the seat's own risk charge. The comparison is across
worlds, so it is evidence of a signal and not a clean measurement of one: the private type is a property of the
world. The integrator's risk charge is public through its standard draft; only its pre-staging cost is private.
"""
import json, glob, sys, collections, math
sys.path.insert(0, "tools/cli_subjects")
import numpy as np
from pathlib import Path
from multiprocessing import Pool
from aeread_families.datacenter_development import agreement as ag, agreement_pack as ap, agreement_negotiator as an, risk_allocation_contracts as rc
import agreement_notes as nt
R = "/Users/chenyusu/AERead/runs/datacenter_development"; B = "/Users/chenyusu/aeread-run-backups/agreement_2026-10-09"
RUNS = [f"{R}/agreement_cli_{x}_v1" for x in ("pair_spread_dev", "pair_rest_dev", "pair_repeat_dev", "pair_repeat_walkaway_dev", "selfplay_probe", "scripted_canary", "scripted_rest", "scripted_soft",
        "scripted_tactics", "scripted_fill1", "scripted_fill2", "scripted_fill3", "elicitation_probe")] + [f"{B}/agreement_claude_integrator_codex_client_one_v1", f"{B}/agreement_codex_integrator_claude_client_one_v1"]
NAME = {"codex_sol61": "Codex", "claude_opus55": "Opus"}

def one(job):
    run, pack, f = job
    c = json.load(open(f)); g = c.get("grade") or {}
    if c["status"] != "ok" or not g.get("valid"): return []
    _, raw = ap.load(pack); case = next(x for x in raw.values() if x["case_id"] == c["case_id"])
    cw, it = rc.world_from({k: case["payload"][k] for k in ("world", "integrator_type", "extras")})
    w, x = cw.w, cw.x; floor = w.terms.floor_margin
    types = list(cw.types); wt = {t: p for t, p in w.prior}; z = sum(wt[t] for t in types); pt = {t: wt[t] / z for t in types}
    charges = dict(w.client_prior); own_c = w.client.risk_charge
    ms = nt.moves(Path(run), c["cell_key"]); state = ag.initial_state(cw); out = []; first = {"integrator": True, "client": True}
    for n, m in enumerate(ms, start=1):
        seat = state["to_move"]; subject = c[seat]
        act = {"action": m["action"], "note": m["note"], "price": m["price"], "clauses": {k: m["changes"].get(k) for k in ag.TERMS} if m["action"] == "redline" else None}
        nxt = ag.apply(state, act, cw)
        if subject in NAME and m["action"] == "redline" and first[seat]:
            first[seat] = False; terms = rc.Contract(**nxt["terms"]); price = m["price"]
            if seat == "integrator":
                lim = {t: rc.integrator_cost(terms, w, t, x) + floor for t in types}; own = lim[it]; pm = sum(pt[t] * lim[t] for t in types); n_types = len(types)
                fits = [t for t in types if price >= lim[t] - 1e-6]          # types that would not lose on this offer
                rank = sorted(types, key=lambda t: lim[t]).index(it)
            else:
                out_c = {ch: an._outside(cw, ch) for ch in charges}
                lim = {ch: out_c[ch] - rc.client_cost(terms, w, it, x, ch) for ch in charges}; own = lim[own_c]; pm = sum(charges[ch] * lim[ch] for ch in charges); n_types = len(charges)
                fits = [ch for ch in charges if price <= lim[ch] + 1e-6]
                rank = sorted(charges, key=lambda ch: lim[ch]).index(own_c)
            true_key = it if seat == "integrator" else own_c
            prot = sum([terms.warranty == "fix_and_delay", str(terms.damages) == "200", str(terms.liability_cap) == "uncapped", terms.readiness == "integrator", terms.consequential == "included", bool(terms.burn_in)])
            out.append({"model": NAME[subject], "seat": seat, "world": str(case["world_seed"]), "protection": prot, "charge": own_c if seat == "client" else it.risk_charge, "test_cost": it.test_cost, "move": n, "price": price, "own": own, "pm": pm, "dev": own - pm, "n_types": n_types,
                        "spread": max(lim.values()) - min(lim.values()), "kept": len(fits), "true_kept": true_key in fits, "rank": rank,
                        "lims": sorted(lim.values()), "own_i": sorted(lim.values()).index(own) if own in lim.values() else -1, "first_move": n <= 2})
        state = nxt
    return out

if __name__ == "__main__":
    jobs = []
    for run in RUNS:
        pack = json.load(open(f"{run}/campaign_plan.json"))["pack"]
        jobs += [(run, pack, f) for f in sorted(glob.glob(f"{run}/cells/*.json"))]
    with Pool(8) as pool: rows = [r for part in pool.map(one, jobs, chunksize=4) for r in part]
    json.dump(rows, open(sys.argv[1], "w"))
    rng = np.random.default_rng(5)
    def slope(sub):
        xs = np.array([r["dev"] for r in sub]); ys = np.array([r["price"] - r["pm"] for r in sub]); b = np.polyfit(xs, ys, 1); return b[0], b[1]
    for model in ("Codex", "Opus"):
        for seat in ("integrator", "client"):
            A = [r for r in rows if r["model"] == model and r["seat"] == seat and (seat == "client" or r["move"] == 1)]
            multi = [r for r in A if r["n_types"] >= 2 and r["spread"] > 1]
            worlds = sorted({r["world"] for r in multi})
            b, a = slope(multi)
            boots = []
            for _ in range(600):
                pick = rng.choice(worlds, len(worlds)); byw = collections.defaultdict(list)
                for r in multi: byw[r["world"]].append(r)
                samp = [r for w_ in pick for r in byw[w_]]
                boots.append(slope(samp)[0])
            lo, hi = np.percentile(boots, [2.5, 97.5])
            # decoder: leave one world out, guess the declared type whose predicted offer is nearest
            hit = chance = 0; n = 0
            for w_ in worlds:
                train = [r for r in multi if r["world"] != w_]; bb, aa = slope(train)
                for r in (r for r in multi if r["world"] == w_):
                    preds = [r["pm"] + aa + bb * (l - r["pm"]) for l in r["lims"]]
                    guess = int(np.argmin([abs(r["price"] - p) for p in preds])); hit += guess == r["own_i"]; chance += 1 / r["n_types"]; n += 1
            sign = 1 if seat == "integrator" else -1
            margin = np.array([sign * (r["price"] - r["own"]) for r in A])
            print(f"{model:5} {seat:10} first offers {len(A):4d} in {len({r['world'] for r in A})} worlds | with 2+ types to tell apart {len(multi):4d} in {len(worlds)} worlds, their limits {np.mean([r['spread'] for r in multi]):.0f} apart"
                  f" | price moves {b:.2f} per $1 of its own private limit [{lo:.2f}, {hi:.2f}] | type named from one offer {hit/n:.0%} (chance {chance/n:.0%})"
                  f" | offer rules out a type {np.mean([r['kept'] < r['n_types'] for r in multi]):.0%}, pins the true type {np.mean([r['kept'] == 1 and r['true_kept'] for r in multi]):.0%}, rules out the TRUE type {np.mean([not r['true_kept'] for r in multi]):.0%}"
                  f" | asks {np.median(margin):.0f} beyond its true limit (median), below its own limit in {np.mean(margin < -0.5):.0%}")
            key = "charge"
            by = collections.defaultdict(list)
            for r in A: by[r[key]].append(r["protection"])
            print("        clauses protecting the client in its first offer (of 6), by its own risk charge:", {k: (round(float(np.mean(v)), 2), len(v)) for k, v in sorted(by.items())})
            if seat == "integrator":
                by2 = collections.defaultdict(list)
                for r in A: by2[r["test_cost"]].append(r["protection"])
                print("        ... and by its own pre-staging cost:", {k: (round(float(np.mean(v)), 2), len(v)) for k, v in sorted(by2.items())})
