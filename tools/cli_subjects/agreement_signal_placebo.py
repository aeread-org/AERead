"""Why the look-back price signal failed its declared test: the same regression on a price that cannot carry the type.

    PYTHONPATH=src python tools/cli_subjects/agreement_signal_placebo.py OUT.json

Reads the runs ``agreement_signals.py`` read, and the type-swap run; calls no model. The look-back analysis regressed
(price - mean client limit) on (true client limit - mean client limit) over the client's counter-offers, across
worlds. Here the same regression is run on the integrator's opening price. The opener is never told the client's
risk charge, so its price cannot reveal it: any slope is the world, not a signal. The type-swap run plays each
world under both charges with one opening, so there the slope has to be near zero.
"""
import json, glob, sys, collections
sys.path.insert(0, "tools/cli_subjects")
import numpy as np
from pathlib import Path
from multiprocessing import Pool
from aeread_families.datacenter_development import agreement as ag, agreement_pack as ap, agreement_negotiator as an, risk_allocation_contracts as rc
import agreement_notes as nt
import agreement_signals as sg
NAME = {"codex_sol61": "Codex", "claude_opus55": "Opus"}
SWAP = f"{sg.R}/agreement_cli_signal_swap_client_v1"

def limits(cw, it, terms):
    charges = dict(cw.w.client_prior); lim = {ch: an._outside(cw, ch) - rc.client_cost(terms, cw.w, it, cw.x, ch) for ch in charges}
    return lim, sum(charges[ch] * lim[ch] for ch in charges)

def one(job):
    """The client's first decision in one negotiation, with the offer it was answering."""
    run, pack, f = job
    c = json.load(open(f)); g = c.get("grade") or {}
    if c["status"] != "ok" or not g.get("valid") or c["client"] not in NAME: return []
    _, raw = ap.load(pack); case = next(x for x in raw.values() if x["case_id"] == c["case_id"])
    cw, it = rc.world_from({k: case["payload"][k] for k in ("world", "integrator_type", "extras")}); own = cw.w.client.risk_charge
    state = ag.initial_state(cw)
    for m in nt.moves(Path(run), c["cell_key"]):
        act = {"action": m["action"], "note": m["note"], "price": m["price"], "clauses": {k: m["changes"].get(k) for k in ag.TERMS} if m["action"] == "redline" else None}
        nxt = ag.apply(state, act, cw)
        if state["to_move"] == "client":
            if not state.get("standing"): return []
            l0, pm0 = limits(cw, it, rc.Contract(**state["terms"]))
            row = {"model": NAME[c["client"]], "opener": NAME.get(c["integrator"], "a script"), "world": str(case["world_seed"]), "action": m["action"],
                   "open_y": state["standing"]["price"] - pm0, "open_x": l0[own] - pm0, "open_gap": max(l0.values()) - min(l0.values())}
            if m["action"] == "redline":
                l1, pm1 = limits(cw, it, rc.Contract(**nxt["terms"])); row.update(y=m["price"] - pm1, x=l1[own] - pm1, gap=max(l1.values()) - min(l1.values()))
            elif m["action"] == "sign": row.update(y=row["open_y"], x=row["open_x"], gap=row["open_gap"])
            return [row]
        state = nxt
    return []

def read(runs):
    jobs = []
    for run in runs:
        pack = json.load(open(f"{run}/campaign_plan.json"))["pack"]; jobs += [(run, pack, f) for f in sorted(glob.glob(f"{run}/cells/*.json"))]
    with Pool(8) as pool: return [r for part in pool.map(one, jobs, chunksize=4) for r in part]

def slope(rows, x, y, gap, rng):
    rows = [r for r in rows if x in r and r[gap] > 1]; byw = collections.defaultdict(list)
    for r in rows: byw[r["world"]].append(r)
    fit = lambda s: float(np.polyfit(np.array([r[x] for r in s]), np.array([r[y] for r in s]), 1)[0])
    if len(byw) < 6: return None
    ws = sorted(byw); bs = [fit([r for w in rng.choice(ws, len(ws)) for r in byw[w]]) for _ in range(2000)]
    return {"slope": fit(rows), "low": float(np.percentile(bs, 2.5)), "high": float(np.percentile(bs, 97.5)), "n": len(rows), "worlds": len(ws)}

def pack_by_type(pack):
    """Per true charge: worlds, and the gap between the three types' limits at the standard draft (public: it does not use the true charge)."""
    _, raw = ap.load(pack); by = collections.defaultdict(list)
    for case in raw.values():
        cw, it = rc.world_from({k: case["payload"][k] for k in ("world", "integrator_type", "extras")}); l, _ = limits(cw, it, rc.Contract(**ag.initial_state(cw)["terms"]))
        by[cw.w.client.risk_charge].append(max(l.values()) - min(l.values()))
    return {str(k): {"worlds": len(v), "mean_gap_at_standard_draft": float(np.mean(v))} for k, v in sorted(by.items())}

if __name__ == "__main__":
    rng = np.random.default_rng(13); out = {}
    for name, rows in (("earlier runs", read(sg.RUNS)), ("type-swap run", read([SWAP]))):
        opus = [r for r in rows if r["model"] == "Opus"]
        cells = {"Opus's counter-offer price (the look-back analysis)": slope([r for r in opus if r["action"] == "redline"], "x", "y", "gap", rng),
                 "Opus's reply, a signature taking the offer's price": slope(opus, "x", "y", "gap", rng),
                 "opening price, every opener": slope(rows, "open_x", "open_y", "open_gap", rng)}
        for who in ("a script", "Codex", "Opus"): cells[f"opening price, opened by {who}"] = slope([r for r in rows if r["opener"] == who], "open_x", "open_y", "open_gap", rng)
        out[name] = cells
        print(name)
        for k, v in cells.items(): print(f"  {k:52s} " + (f"{v['slope']:5.2f} [{v['low']:5.2f}, {v['high']:5.2f}]  offers {v['n']:4d}  worlds {v['worlds']}" if v else "too few worlds"))
    out["packs"] = {p: pack_by_type(p) for p in ("agreement_dev_v1", "agreement_confirm_v1")}
    for p, v in out["packs"].items(): print(p, {k: (x["worlds"], round(x["mean_gap_at_standard_draft"])) for k, x in v.items()})
    json.dump(out, open(sys.argv[1], "w"), indent=1)
