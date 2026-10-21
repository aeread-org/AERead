"""Read the inference v2 cells: did a subject read the record, and did it carry it over?

    PYTHONPATH=src python tools/cli_subjects/procurement_v2_report.py <runs/procurement_allocation>

The pack's own manifest says which suppliers are good, which component carries
the record and what the reference policies earn. Two things are read off each
cell's action trace before any score: whether the supplier it verified on the
recorded component is one the record calls good, and whether the supplier it
verified first on the unrecorded component is good. The second is the
inference; a buyer that does not carry the record over gets it right in half
the worlds. Then the v1 worlds under the two prompts, for the same subject.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from math import comb
from pathlib import Path

from aeread_families.procurement_allocation import inference_v2_case_matrix as v2

SOLVED = 50.0
V2_RUNS = {
    "claude code opus 5.5": "inference_v2_neutral_claude_code_opus55_v1",
    "codex sol 6.1": "inference_v2_neutral_codex_cli_sol61_v1",
}
V1_ARMS = {
    "codex sol 6.1": {"scaffold prompt": "inference_v1_codex_cli_sol61_v1", "neutral prompt": "inference_v1_neutral_codex_cli_sol61_v1"},
    "claude code opus 5.5": {"scaffold prompt": "inference_v1_claude_code_opus55_v1", "neutral prompt": "inference_v1_neutral_claude_code_opus55_v1"},
}


def load(root: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(root.glob("results/*/seed_*.json"))]


def world_of(row: dict) -> str:
    return row["case_id"].rsplit(".", 1)[-1]


def supplier_of(offer_id: str) -> str:
    return offer_id.removeprefix("offer_").rsplit("_v", 1)[0]


def at_least(k: int, n: int) -> float:
    """P(X >= k) for X ~ Binomial(n, 1/2): how often a coin does this well."""
    return sum(comb(n, i) for i in range(k, n + 1)) / 2 ** n


def interval(values: list[float]) -> str:
    n = len(values)
    if n < 2:
        return "n/a"
    mean, se = statistics.fmean(values), statistics.stdev(values) / n ** 0.5
    t = {17: 2.110, 16: 2.120, 15: 2.131, 14: 2.145, 13: 2.160, 12: 2.179, 11: 2.201, 10: 2.228, 9: 2.262, 8: 2.306}.get(n - 1, 2.0)
    return f"{mean:+.1f} [{mean - t * se:+.1f}, {mean + t * se:+.1f}] (n={n})"


def read_cell(row: dict, world: dict) -> dict:
    """What one cell did, in the pack's terms."""
    good = set(world["good_supplier_ids"])
    trace = row.get("action_trace") or []
    quoted = [a["supplier_id"] for a in trace if a["action"] == "request_quote"]
    first = {}
    for supplier_id in quoted:
        component = world["recorded_component"] if supplier_id.startswith(world["recorded_component"]) else world["unrecorded_component"]
        first.setdefault(component, supplier_id)
    last = trace[-1] if trace else {}
    awarded = {supplier_of(line["offer_id"]) for line in last.get("award_lines", [])} if last.get("action") == "submit_award" else set()
    if row["status"] != "completed":
        ending = "did not complete"
    elif row["termination_reason"] == "interaction_budget_exhausted":
        ending = "ran out of actions"
    elif row["decision"] == "defer":
        ending = "deferred"
    elif row["decision"] != "award":
        ending = "invalid action"
    elif awarded <= good and len(awarded) == 2:
        ending = "awarded two good suppliers"
    elif row.get("violations"):
        ending = "award refused: " + ", ".join(row["violations"])[:40]
    else:
        ending = "awarded a bad supplier"
    unrecorded = first.get(world["unrecorded_component"])
    return {
        "recorded_pick_good": first.get(world["recorded_component"]) in good if world["recorded_component"] in first else None,
        "unrecorded_pick_good": unrecorded in good if unrecorded else None,
        "unrecorded_pick": unrecorded,
        "suppliers_quoted": len(set(quoted)), "ending": ending,
        "regret": row.get("regret_to_upper_bound_usd"),
        "bound": row.get("upper_bound_usd"),
    }


def main() -> int:
    base = Path(sys.argv[1])
    manifest = json.loads((v2.PACK_ROOT / "pack.json").read_text())
    worlds = {w["slug"]: w for w in manifest["worlds"]}
    cases = {p.stem: json.loads(p.read_text())["payload"] for p in v2.case_paths()}
    cheapest = {}
    for slug, payload in cases.items():
        rows = [s for s in payload["suppliers"] if s["component"] == worlds[slug]["unrecorded_component"]]
        cheapest[slug] = min(rows, key=lambda s: s["listing"]["displayed_unit_price_usd"])["supplier_id"]
    reference = manifest["reference_worlds_solved"]
    print(f"inference v2, {len(worlds)} worlds, five actions. Reference policies, worlds solved: reads the record and carries it over "
          f"{reference['informed']}; reads the record then cheapest {reference['records_then_rule:cheapest_first']}, then dearest "
          f"{reference['records_then_rule:dearest_first']}; cheapest for both {reference['rule_only:cheapest_first']}")
    cells = {name: {world_of(r): read_cell(r, worlds[world_of(r)]) for r in load(base / run)}
             for name, run in V2_RUNS.items() if (base / run).exists()}
    print(f"\n{'subject':22s} cells  solved  regret/world  share of bound  read the record  carried it over (coin does this well)  unrecorded pick is the cheapest  suppliers quoted")
    for name, by in cells.items():
        done = [c for c in by.values() if c["regret"] is not None]
        rec = [c["recorded_pick_good"] for c in by.values() if c["recorded_pick_good"] is not None]
        unrec = [c["unrecorded_pick_good"] for c in by.values() if c["unrecorded_pick_good"] is not None]
        is_cheapest = sum(c["unrecorded_pick"] == cheapest[w] for w, c in by.items() if c["unrecorded_pick"])
        print(f"{name:22s} {len(by):5d} {sum(c['regret'] < SOLVED for c in done):6d}/{len(by)} {statistics.fmean(c['regret'] for c in done):11.1f} "
              f"{statistics.fmean(1 - c['regret'] / c['bound'] for c in done):14.0%} {sum(rec):12d}/{len(rec)} "
              f"{sum(unrec):12d}/{len(unrec)} (p {at_least(sum(unrec), len(unrec)):.4f}) {is_cheapest:22d}/{len(unrec)} "
              f"{statistics.fmean(c['suppliers_quoted'] for c in by.values()):17.1f}")
    for name, by in cells.items():
        print(f"\n{name}: how the cells ended:", dict(Counter(c["ending"] for c in by.values()).most_common()))

    def split(label: str, key) -> None:
        groups = sorted({key(w) for w in worlds.values()}, key=str)
        print(f"\nworlds solved by {label}: " + " | ".join(str(g) for g in groups))
        for name, by in cells.items():
            parts = []
            for g in groups:
                ws = [s for s, w in worlds.items() if key(w) == g and s in by and by[s]["regret"] is not None]
                parts.append(f"{sum(by[s]['regret'] < SOLVED for s in ws)}/{len(ws)}")
            print(f"  {name:22s} " + " | ".join(parts))
        for policy in ("records_then_rule:cheapest_first", "records_then_rule:dearest_first"):
            parts = [f"{sum(w['reference_regret_usd'][policy] < SOLVED for w in worlds.values() if key(w) == g)}/{sum(key(w) == g for w in worlds.values())}" for g in groups]
            print(f"  {'rule: ' + policy.split(':')[1]:22s} " + " | ".join(parts))

    split("whether the cheapest unrecorded listing is good", lambda w: "cheapest good" if w["cheapest_unrecorded_is_good"] else "cheapest bad")
    split("signal direction", lambda w: "high-is-good" if v2.high_is_good(w["signal"]) else "low-is-good")
    split("signal attribute", lambda w: v2.attribute_of(w["signal"]))
    split("binding risk", lambda w: w["risk"])

    names = list(cells)
    if len(names) == 2:
        both = [s for s in worlds if all(s in cells[n] and cells[n][s]["regret"] is not None for n in names)]
        diffs = [cells[names[0]][s]["regret"] - cells[names[1]][s]["regret"] for s in both]
        print(f"\npaired by world, regret of {names[0]} minus {names[1]}: {interval(diffs)}; "
              f"$50+ lower on {sum(d < -SOLVED for d in diffs)} worlds, $50+ higher on {sum(d > SOLVED for d in diffs)}")
    print("\nregret per world, USD (* solved); the unrecorded pick: + good, - bad, ? none")
    print(f"{'world':34s} {'cheapest':>9s} " + " ".join(f"{n[:20]:>22s}" for n in names))
    for slug, w in worlds.items():
        row = []
        for n in names:
            c = cells[n].get(slug)
            mark = "?" if not c or c["unrecorded_pick_good"] is None else "+" if c["unrecorded_pick_good"] else "-"
            row.append(("" if not c or c["regret"] is None else f"{c['regret']:.0f}{'*' if c['regret'] < SOLVED else ' '} {mark}").rjust(22))
        print(f"{slug:34s} {'good' if w['cheapest_unrecorded_is_good'] else 'bad':>9s} " + " ".join(row))

    # --- the v1 worlds under the two prompts -----------------------------------
    v1_root = v2.REPOSITORY_ROOT / "cases/procurement_allocation_v1/inference_v1/labeled"
    v1 = {p.stem: json.loads(p.read_text())["payload"] for p in v1_root.glob("*.json")}
    low = ("price_low", "lead_time_short", "moq_low")
    printed = False
    for subject, arms in V1_ARMS.items():
        for arm, run in arms.items():
            if not (base / run).exists():
                continue
            if not printed:
                print("\nthe v1 worlds under the two prompts: worlds solved low-is-good / high-is-good, and cells whose first quote for every component is the cheapest listing")
                printed = True
            solved, starts, n = Counter(), 0, 0
            for r in load(base / run):
                if r["status"] != "completed":
                    continue
                w = world_of(r)
                half = "low" if w.startswith(low) else "high"
                solved[half] += r["regret_to_upper_bound_usd"] < SOLVED
                price = {s["supplier_id"]: (s["component"], s["listing"]["displayed_unit_price_usd"]) for s in v1[w]["suppliers"]}
                cheap = {}
                for sid, (comp, p) in price.items():
                    if comp not in cheap or p < price[cheap[comp]][1]:
                        cheap[comp] = sid
                first = {}
                for a in r["action_trace"]:
                    if a["action"] == "request_quote":
                        first.setdefault(price[a["supplier_id"]][0], a["supplier_id"])
                if len(first) == len(cheap):
                    n += 1
                    starts += all(first[c] == cheap[c] for c in cheap)
            print(f"  {subject:22s} {arm:16s} {solved['low']}/9  {solved['high']}/9   starts at the cheapest {starts}/{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
