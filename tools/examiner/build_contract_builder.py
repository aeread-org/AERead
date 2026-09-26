"""The contract builder for the datacenter full-terms case, for the examiner.

Every world of the full-terms pack priced by the grader's own solver (what the integrator charges for each contract
on its menu in each round, what each contract costs the client, the best contract and the outside options), the
builder page that shows them (contract_builder/), which published runs play the pack, and a check that the numbers
reproduce every such cell's graded realised cost and cost over best attainable. Written to
data/contract_builder.json as the same gzip+base64 envelope as the other data files.

usage: build_contract_builder.py OUT CHECKOUT [--standalone FILE]
  CHECKOUT  a tree whose src/ holds aeread_families.datacenter_development.risk_allocation_contracts
            (branch codex/datacenter-risk-allocation)
  --standalone FILE  also write the builder as one self-contained page (the separate contract-builder artifact)
"""
from __future__ import annotations

import base64
import gzip
import json
import math
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACK = "contracts_eval_v1"
CHECK_TOLERANCE = 0.05  # $k: the grader rounds to 3 decimals, the page's tables to 3


def envelope(obj: object) -> str:
    raw = json.dumps(obj, separators=(",", ":")).encode()
    # mtime 0 keeps the bytes reproducible
    return json.dumps({"encoding": "gzip+base64", "raw_bytes": len(raw), "payload": base64.b64encode(gzip.compress(raw, 9, mtime=0)).decode()},
                      separators=(",", ":"))


def unpack(path: Path) -> dict:
    obj = json.loads(path.read_text())
    if isinstance(obj, dict) and obj.get("encoding") == "gzip+base64":
        return json.loads(gzip.decompress(base64.b64decode(obj["payload"])))
    return obj


def priced_worlds(rc, cp) -> tuple[dict, str]:
    """The builder's data: every world of the pack with the solver's tables, as the page reads them."""
    man, cases = cp.load(PACK)
    r3 = lambda x: round(float(x), 3)
    menus = {p: [[getattr(c, k) for k in rc.TERMS] for c in rc.contracts(p)] for p in rc.PLAYBOOKS}
    order = list(rc.CELLS)
    worlds = []
    for w in sorted(man["worlds"], key=lambda w: (order.index(w["cell"]), rc.PLAYBOOKS.index(w["playbook"]), w["seed"])):
        payload = cases[w["case_id"]]["payload"]
        cw, it = rc.world_from(payload)
        s = rc.solver_for(payload)
        t = s.type_index(it)
        st = s.start(it)
        best, best_cost = s.best_contract(it)
        pre, prep, epaid, eloss, icost = [], [], [], [], []
        for c in s.menu:
            a, b, ic = rc.best_response(c, cw.w, it, cw.x)
            pre.append(int(a)); prep.append(int(b)); icost.append(r3(ic))
            oc = rc.outcomes(c, cw.w, a, b)
            epaid.append(r3(math.fsum(p * pay for p, _, pay, _ in oc))); eloss.append(r3(math.fsum(p * l for p, l, _, _ in oc)))
        ref = s.best(st)
        wr, cl, tm = cw.w.risks, cw.w.client, cw.w.terms
        worlds.append({
            "id": w["case_id"].rsplit(".", 1)[-1], "cell": w["cell"], "lesson": w["lesson"], "playbook": cw.playbook, "seed": w["seed"],
            "risks": {k: getattr(wr, k) for k in ("defect_without_test", "defect_with_test", "defect_fix", "defect_weeks", "unready", "standby",
                                                 "unready_weeks", "incident", "incident_loss")},
            "client": {"charge": cl.risk_charge, "delay": cl.delay_per_week, "capital": cl.capital_rate, "insolvency": cl.insolvency,
                       "turnkey": cl.turnkey_all_in},
            "terms": {"hardware": tm.hardware, "services": tm.services, "deposit_weeks": tm.deposit_weeks, "contingency": tm.uncontrolled_contingency,
                      "icapital": tm.integrator_capital_rate, "margin": tm.floor_margin, "premium": list(tm.ask_premium), "breakoff": tm.breakoff,
                      "round_cost": tm.round_cost},
            "extras": {"team": cw.x.team, "site_prep": cw.x.site_prep},
            "type": {"test_cost": it.test_cost, "risk_charge": it.risk_charge},
            "outside": {"turnkey": r3(cw.outside_cost("turnkey")), "self_manage": r3(cw.outside_cost("self_manage")), "best": cw.best_outside[0]},
            "cc": [r3(x) for x in s.cc[:, t]], "th": [[r3(x) for x in s.th[r][:, t]] for r in range(s.rounds + 1)],
            "icost": icost, "pre": pre, "prep": prep, "epaid": epaid, "eloss": eloss,
            "best": s.index[best], "best_cost": r3(best_cost), "listed": [ci for ci, _ in s.list_prices(it)],
            "shortcuts": {k: s.index[c] for k, c in rc.shortcuts(s, st).items()}, "losers": list(rc.CELLS[w["cell"]]["losers"]),
            "reference": {"first": ref.label(), "value": r3(s.value(st))},
        })
    prefix = man["worlds"][0]["case_id"].rsplit(".", 1)[0] + "."
    text = lambda v: str(v).lower() if isinstance(v, bool) else v
    data = {"terms": list(rc.TERMS), "levels": {k: [text(v) for v in vs] for k, vs in rc.LEVELS.items()},
            "negotiable": {p: list(n) for p, n in rc.NEGOTIABLE.items()}, "bases": {p: rc.contracts(p).index(rc.BASES[p]) for p in rc.PLAYBOOKS},
            "menus": {p: [[text(v) for v in row] for row in rows] for p, rows in menus.items()}, "worlds": worlds,
            "constants": {"site_prep_effect": rc.SITE_PREP_EFFECT, "burn_in_weeks": rc.BURN_IN_WEEKS, "burn_in_crew": rc.BURN_IN_CREW,
                          "burn_in_incident": rc.BURN_IN_INCIDENT_FACTOR, "escrow_fee": rc.ESCROW_FEE, "deposit_share": rc.DEPOSIT_SHARE,
                          "markup_up": rc.MARKUP_UP, "keep_down": rc.KEEP_DOWN, "decay": list(rc.DECAY), "price_step": rc.PRICE_STEP,
                          "walk_margin": rc.WALK_MARGIN, "choice_margin": rc.CHOICE_MARGIN},
            "cells": {k: v["lesson"] for k, v in rc.CELLS.items()}}
    return data, prefix


def js_str(v: object) -> str:
    """String(v) as the page computes it, so contract keys match."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def check_cells(data: dict, prefix: str, cases: list[dict]) -> dict:
    """Recompute each graded cell's realised cost, cost over best attainable and its split from the page's numbers."""
    terms = data["terms"]
    index = {p: {"|".join(js_str(v) for v in row): i for i, row in enumerate(rows)} for p, rows in data["menus"].items()}
    by_id = {w["id"]: w for w in data["worlds"]}
    checked, reproduced, bad = 0, 0, []
    for k in cases:
        o = k.get("outcome_row") or {}
        w = by_id.get(str(k.get("case_id", ""))[len(prefix):])
        if w is None or o.get("cells.realised_cost") is None or o.get("cells.cost_over_best_attainable") is None:
            continue
        rounds = (o.get("cells.refused_counters") or 0) * w["terms"]["round_cost"]
        out_cost = w["outside"][w["outside"]["best"]]
        target = min(w["best_cost"], out_cost)
        if o.get("cells.termination") == "signed":
            c = {t: js_str(o.get(f"cells.signed_contract.{t}")) for t in terms}
            if c["warranty"] != "fix_and_delay":
                c["damages"] = "100"
            if c["deposit"] == "none":
                c["escrow"] = "false"
            ci = index[w["playbook"]].get("|".join(c[t] for t in terms))
            if ci is None:
                bad.append(f"{o.get('cells.cell_key')}: signed contract not on the menu")
                continue
            tot = w["th"][-1][ci] + w["cc"][ci]
            pof = o.get("cells.price_over_floor") or 0.0
            realised = tot + pof + rounds
            parts = {"contract": tot - target, "price": pof, "walk": 0.0, "refused_counters": rounds}
        else:
            o_cost = w["outside"].get(o.get("cells.walked_to") or w["outside"]["best"], out_cost)
            realised = o_cost + rounds
            parts = {"contract": 0.0, "price": 0.0, "walk": o_cost - target, "refused_counters": rounds}
        pairs = [(realised, o["cells.realised_cost"]), (realised - target, o["cells.cost_over_best_attainable"])]
        pairs += [(parts[p], o.get(f"cells.split.{p}")) for p in parts if o.get(f"cells.split.{p}") is not None]
        checked += 1
        if any(abs(a - b) >= CHECK_TOLERANCE for a, b in pairs):
            bad.append(f"{o.get('cells.cell_key')}: recomputed {round(realised, 3)} vs graded {o['cells.realised_cost']}")
        else:
            reproduced += 1
    return {"cells": sum(1 for k in cases if str(k.get("case_id", "")).startswith(prefix)), "checked": checked, "reproduced": reproduced,
            "mismatches": bad}


def main() -> None:
    args = sys.argv[1:]
    standalone = None
    if "--standalone" in args:
        i = args.index("--standalone")
        standalone = Path(args[i + 1])
        del args[i:i + 2]
    out, checkout = Path(args[0]), Path(args[1]).resolve()
    sys.path.insert(0, str(checkout / "src"))
    from aeread_families.datacenter_development import risk_allocation_contracts as rc
    from aeread_families.datacenter_development import risk_allocation_contracts_pack as cp

    data, prefix = priced_worlds(rc, cp)
    head, body, script = ((HERE / "contract_builder" / n).read_text() for n in ("head.html", "body.html", "script.js"))
    template = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                f"{head}</head><body>{body}<script>{script}</script></body></html>")
    runs, parity = [], {}
    for f in sorted((out / "data" / "campaigns").glob("*.json")):
        cases = unpack(f).get("cases") or []
        if any(str(k.get("case_id", "")).startswith(prefix) for k in cases):
            runs.append(f.stem)
            parity[f.stem] = check_cells(data, prefix, cases)
    commit = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    doc = {"pack": PACK, "case_prefix": prefix, "campaigns": runs, "parity": parity, "template": template, "data": data,
           "source": {"module": "aeread_families.datacenter_development.risk_allocation_contracts", "commit": commit}}
    (out / "data" / "contract_builder.json").write_text(envelope(doc))
    if standalone:
        filled = template.replace("__INIT__", "{}").replace("__DATA__", json.dumps(data, separators=(",", ":")).replace("<", "\\u003c"))
        standalone.write_text(filled)
    for run, p in parity.items():
        print(f"  {run}: {p['reproduced']} of {p['checked']} graded cells ({p['cells']} in all) reproduce the grader" + (f"; {len(p['mismatches'])} do not: {p['mismatches'][:3]}" if p["mismatches"] else ""))
    print(f"contract builder: {len(data['worlds'])} worlds of {PACK}, {len(runs)} runs, source {commit[:8]}")


if __name__ == "__main__":
    main()
