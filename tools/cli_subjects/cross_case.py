"""Do the subjects that do well on the procurement panel also do well on the Housing price case?

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/cross_case.py \
        <runs/procurement_allocation> <housing runs dir> <inference_v1 labeled cases dir>

Four subjects played both cases: the two CLI subjects (one cell a world) and the two models that
have a development run on the inference panel and confirmatory cells on the same Housing worlds.
Two questions, kept apart:

1. Scores. Each case's score per subject, the rank agreement between the two cases, and how often
   that agreement survives resampling the worlds of each case.
2. Behaviours. The same two habits measured in both cases from the action records: how much
   information a subject buys before it commits, and whether it refuses a deal its own evidence
   says is bad.

Four subjects cannot establish a correlation: the smallest two-sided p a perfect rank agreement
can reach with four is 2/24. The numbers describe; they do not test.
"""

from __future__ import annotations

import itertools
import json
import random
import statistics
import sys
from pathlib import Path

from aeread_families.housing import price_endpoint
from aeread_families.housing import price_publication as pub

import housing_cli

SOLVED_REGRET_USD = 50.0
SUBJECTS = {
    "claude code opus 5.5": ("inference_v1_claude_code_opus55_v1", housing_cli.campaign_id("claude_opus55", "panel")),
    "codex sol 6.1": ("inference_v1_codex_cli_sol61_v1", housing_cli.campaign_id("codex_sol61", "panel")),
    "gemini 3.8 flash": ("inference_v1_gemini", "housing_lemons_price_confirmatory_v14_gemini38_flash"),
    "glm 5.3 flash": ("inference_v1_screen", "housing_lemons_price_confirmatory_v14_glm53_flash_nextbit"),
}
BAD_ON_TIME = 0.9


def spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return out
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 0.0


def main() -> int:
    procurement_root, housing_root, cases_dir = (Path(a) for a in sys.argv[1:4])
    names = list(SUBJECTS)

    # --- procurement: per world, the share of the full-information bound a subject earned
    truth = {p.stem: {s["supplier_id"]: s["private_terms"] for s in json.loads(p.read_text())["payload"]["suppliers"]}
             for p in cases_dir.glob("*.json")}
    proc_cells = {n: [json.loads(p.read_text()) for p in sorted((procurement_root / SUBJECTS[n][0]).glob("results/*/seed_*.json"))]
                  for n in names}
    world = lambda row: row["case_id"].rsplit(".", 1)[-1]  # noqa: E731
    proc_worlds = sorted(truth)
    proc = {n: {} for n in names}
    for n in names:
        for w in proc_worlds:
            done = [r for r in proc_cells[n] if world(r) == w and r["status"] == "completed"]
            if done:
                proc[n][w] = {
                    "share": statistics.fmean(1 - r["regret_to_upper_bound_usd"] / r["upper_bound_usd"] for r in done),
                    "regret": statistics.fmean(r["regret_to_upper_bound_usd"] for r in done),
                    "solved": sum(r["regret_to_upper_bound_usd"] < SOLVED_REGRET_USD for r in done) * 2 > len(done),
                }
    proc_common = [w for w in proc_worlds if all(w in proc[n] for n in names)]

    # --- housing: per world, the deciding tenant's net as a share of the full-information ceiling
    worlds = housing_cli.PANELS["panel"]
    rows = {n: pub.cell_rows({"campaign_id": SUBJECTS[n][1], "world_seeds": worlds, "arms": list(pub.ARMS)},
                             housing_root / SUBJECTS[n][1]) for n in names}
    level = {n: pub.per_world(rows[n], pub.PRIMARY) for n in names}
    ceiling = {s: statistics.fmean(r["ceiling"] for r in rows[names[0]] if r["world_seed"] == s) for s in worlds}
    rule = {s: statistics.fmean(r["reference_net"] for r in rows[names[0]] if r["world_seed"] == s) for s in worlds}
    house_common = [s for s in worlds if all(s in level[n] for n in names)]

    def proc_score(n: str, ws: list[str]) -> float:
        return statistics.fmean(proc[n][w]["share"] for w in ws)

    def house_score(n: str, ws: list[int]) -> float:
        return sum(level[n][s] for s in ws) / sum(ceiling[s] for s in ws)

    print(f"scores on the worlds all four played: {len(proc_common)} procurement worlds, {len(house_common)} Housing worlds")
    print(f"{'subject':24s} procurement: solved  regret/world  share of bound   housing: net/world  minus the rule  share of ceiling")
    for n in names:
        print(f"{n:24s} {sum(proc[n][w]['solved'] for w in proc_common):14d}/{len(proc_common)} "
              f"{statistics.fmean(proc[n][w]['regret'] for w in proc_common):12.0f} {proc_score(n, proc_common):14.0%} "
              f"{statistics.fmean(level[n][s] for s in house_common):20.0f} "
              f"{statistics.fmean(level[n][s] - rule[s] for s in house_common):15.0f} {house_score(n, house_common):16.0%}")
    p_scores = [proc_score(n, proc_common) for n in names]
    h_scores = [house_score(n, house_common) for n in names]
    rho = spearman(p_scores, h_scores)
    pairs = list(itertools.combinations(range(len(names)), 2))
    same = sum((p_scores[a] - p_scores[b]) * (h_scores[a] - h_scores[b]) > 0 for a, b in pairs)
    perms = [spearman(p_scores, [h_scores[i] for i in perm]) for perm in itertools.permutations(range(len(names)))]
    exact = sum(abs(r) >= abs(rho) - 1e-12 for r in perms) / len(perms)
    print(f"\nrank agreement between the two cases: Spearman {rho:+.2f}; {same} of {len(pairs)} pairs of subjects ordered the same way; "
          f"exact two-sided permutation p {exact:.3f} (the smallest possible with {len(names)} subjects is {2 / len(perms):.3f})")
    order = lambda scores: " > ".join(names[i] for i in sorted(range(len(names)), key=lambda i: -scores[i]))  # noqa: E731
    print("  procurement order:", order(p_scores))
    print("  housing order:    ", order(h_scores))

    rng = random.Random(20261008)
    draws = []
    for _ in range(5000):
        pw = [rng.choice(proc_common) for _ in proc_common]
        hw = [rng.choice(house_common) for _ in house_common]
        draws.append(spearman([proc_score(n, pw) for n in names], [house_score(n, hw) for n in names]))
    draws.sort()
    print(f"resampling the worlds of each case 5000 times (the same worlds for every subject): Spearman median {statistics.median(draws):+.2f}, "
          f"middle 90% {draws[250]:+.2f} to {draws[4749]:+.2f}; positive in {sum(d > 0 for d in draws) / 50:.0f}% of draws, "
          f"+0.8 or more in {sum(d >= 0.8 - 1e-9 for d in draws) / 50:.0f}%")
    print("which pairs the two cases order the same way:")
    for a, b in pairs:
        dp, dh = p_scores[a] - p_scores[b], h_scores[a] - h_scores[b]
        print(f"  {names[a]:22s} vs {names[b]:22s} procurement {dp:+.1%}  housing {dh:+.1%}  {'same' if dp * dh > 0 else 'opposite'}")

    # --- behaviours, measured the same way in both cases
    def supplier(offer_id: str) -> str:
        return offer_id.removeprefix("offer_").rsplit("_v", 1)[0]

    print(f"\n{'':24s} information bought before committing        refusing a deal its own evidence says is bad")
    print(f"{'subject':24s} procurement: suppliers  housing: listings      procurement: decided cells that saw a   housing: holds not worth signing")
    print(f"{'':24s} sampled per cell       inspected per cell     late offer and did not award one       that it walked from")
    info_p, info_h, refuse_p, refuse_h = [], [], [], []
    for n in names:
        done = [r for r in proc_cells[n] if r["status"] == "completed"]
        sampled = statistics.fmean(len({a["supplier_id"] for a in r["action_trace"] if a["action"] == "request_sample"}) for r in done)
        saw = took = 0
        # Only cells that ended in a decision count: a cell that died on a malformed action after
        # seeing a late offer refused nothing.
        for r in [r for r in done if r["decision"] in {"award", "defer"}]:
            w = world(r)
            quoted = {a["supplier_id"] for a in r["action_trace"] if a["action"] == "request_quote"}
            if not any(truth[w][s]["on_time_probability"] < BAD_ON_TIME for s in quoted):
                continue
            saw += 1
            last = r["action_trace"][-1]
            awarded = {supplier(line["offer_id"]) for line in last.get("award_lines", [])} if last["action"] == "submit_award" else set()
            took += any(truth[w][s]["on_time_probability"] < BAD_ON_TIME for s in awarded)
        cells = [r for r in rows[n] if r["status"] == "completed"]
        inspections, bad_holds, walked = [], 0, 0
        for r in cells:
            raw = json.loads((housing_root / SUBJECTS[n][1] / "live" / f"world_{r['world_seed']}__{r['arm']}.json").read_text())
            scored = price_endpoint.score_cell(raw["outcome_facts"], world_seed=r["world_seed"], arm=r["arm"])
            inspections.append(scored["by_seat"][0]["inspection_spend"] / 25.0)
            for d in scored["decisions"]:
                if d["tenant_id"] == 0 and not d["worth_it_response"]:
                    bad_holds += 1
                    walked += d["decision"] == "walk"
        info_p.append(sampled); info_h.append(statistics.fmean(inspections))
        refuse_p.append(1 - took / saw if saw else float("nan")); refuse_h.append(walked / bad_holds if bad_holds else float("nan"))
        print(f"{n:24s} {sampled:12.1f} {statistics.fmean(inspections):22.2f} {f'{saw - took} of {saw}':>30s} {f'{walked} of {bad_holds}':>38s}")
    print(f"\nrank agreement across the four subjects: information bought {spearman(info_p, info_h):+.2f}; refusing a bad deal {spearman(refuse_p, refuse_h):+.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
