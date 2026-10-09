"""Read the CLI subjects' procurement cells beside the four development pilots, world by world.

    python tools/cli_subjects/procurement_report.py <runs/procurement_allocation>

A cell is solved when its regret is under $50 (``trajectory_analysis.SOLVED_REGRET_USD``); a
world is solved for a subject when more than half of that subject's completed cells on it are.
Every number is per world: a subject's cells on one world are replicates, not cases.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

SOLVED_REGRET_USD = 50.0
RUNS = {
    "claude code opus 5.5": "inference_v1_claude_code_opus55_v1",
    "codex sol 6.1": "inference_v1_codex_cli_sol61_v1",
    "claude code opus 5.5 (gate)": "inference_v1_claude_code_opus55_gate_v1",
    "claude code fable 5.1 (gate)": "inference_v1_claude_code_fable51_gate_v1",
    "gemini 3.8 flash": "inference_v1_gemini",
    "glm 5.3 flash": "inference_v1_screen",
    "qwen3 next instruct": "inference_v1_qwen_instruct",
    "qwen3 next thinking": "inference_v1_qwen_thinking",
}
LOW = ("price_low", "lead_time_short", "moq_low")
#: The subjects played through a CLI, one cell a world.
CLI_PANELS = ("claude code opus 5.5", "codex sol 6.1")
REPOSITORY = Path(__file__).resolve().parents[2]


def t_interval(values: list[float]) -> str:
    """Mean and 95% Student-t interval over worlds."""
    n = len(values)
    if n < 2:
        return "n/a"
    mean, se = statistics.fmean(values), statistics.stdev(values) / n ** 0.5
    # two-sided 97.5% t quantiles for the sample sizes this panel can produce
    t = {17: 2.110, 16: 2.120, 15: 2.131, 14: 2.145, 13: 2.160, 12: 2.179, 11: 2.201, 10: 2.228, 9: 2.262, 8: 2.306,
         7: 2.365, 6: 2.447, 5: 2.571, 4: 2.776, 3: 3.182, 2: 4.303, 1: 12.706}.get(n - 1, 2.0)
    return f"{mean:+.1f} [{mean - t * se:+.1f}, {mean + t * se:+.1f}] (n={n})"


def load(root: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(root.glob("results/*/seed_*.json"))]


def world_of(row: dict) -> str:
    return row["case_id"].rsplit(".", 1)[-1]


def main() -> int:
    base = Path(sys.argv[1])
    cells = {name: load(base / run) for name, run in RUNS.items() if (base / run).exists()}
    worlds = sorted({world_of(r) for rows in cells.values() for r in rows})
    per = {name: defaultdict(list) for name in cells}
    for name, rows in cells.items():
        for r in rows:
            per[name][world_of(r)].append(r)

    def regret(rows: list[dict]) -> float | None:
        done = [r["regret_to_upper_bound_usd"] for r in rows if r["status"] == "completed"]
        return statistics.fmean(done) if done else None

    def solved(rows: list[dict]) -> bool | None:
        done = [r for r in rows if r["status"] == "completed"]
        return (sum(r["regret_to_upper_bound_usd"] < SOLVED_REGRET_USD for r in done) * 2 > len(done)) if done else None

    print("subject                        cells  done  award defer failed  worlds  solved  mean regret/world  list cost  s/cell")
    for name, rows in cells.items():
        done = [r for r in rows if r["status"] == "completed"]
        decisions = Counter(r["decision"] for r in done)
        covered = [w for w in worlds if per[name][w] and solved(per[name][w]) is not None]
        mean = statistics.fmean(regret(per[name][w]) for w in covered) if covered else float("nan")
        seconds = statistics.median(r["elapsed_seconds"] for r in rows) if rows else float("nan")
        print(f"{name:30s} {len(rows):5d} {len(done):5d} {decisions['award']:6d} {decisions['defer']:5d} {decisions['failed']:6d}"
              f" {len(covered):7d} {sum(bool(solved(per[name][w])) for w in covered):7d} {mean:18.1f}"
              f" {sum(float(r.get('cost_usd') or 0) for r in rows):10.2f} {seconds:7.0f}")

    def strata(label: str, key) -> None:
        print(f"\nworlds solved by {label} (solved / worlds with a completed cell)")
        groups = sorted({key(w) for w in worlds})
        print(f"{'subject':30s} " + " ".join(f"{g:>14s}" for g in groups))
        for name in cells:
            parts = []
            for g in groups:
                ws = [w for w in worlds if key(w) == g and solved(per[name][w]) is not None]
                parts.append(f"{sum(bool(solved(per[name][w])) for w in ws)}/{len(ws)}".rjust(14))
            print(f"{name:30s} " + " ".join(parts))

    strata("signal direction", lambda w: "low-is-good" if w.startswith(LOW) else "high-is-good")
    strata("binding risk", lambda w: w.rsplit("__", 1)[-1])
    strata("listing attribute", lambda w: w.split("_")[0])

    names = [n for n in cells if "gate" not in n]
    print("\nmean regret per world, USD (blank: no completed cell; * solved)")
    print(f"{'world':36s} " + " ".join(f"{n[:15]:>16s}" for n in names))
    for w in worlds:
        row = []
        for n in names:
            value = regret(per[n][w])
            row.append(("" if value is None else f"{value:.0f}{'*' if solved(per[n][w]) else ' '}").rjust(16))
        print(f"{w:36s} " + " ".join(row))

    present = [n for n in CLI_PANELS if n in cells]
    print("\npaired by world, regret of the first minus the second, USD (negative: the first lost less)")
    for i, a in enumerate(present):
        for b in [n for n in names if n != a and (n not in present or present.index(n) > i)]:
            both = [w for w in worlds if regret(per[a][w]) is not None and regret(per[b][w]) is not None]
            diffs = [regret(per[a][w]) - regret(per[b][w]) for w in both]
            lower, higher = sum(d < -SOLVED_REGRET_USD for d in diffs), sum(d > SOLVED_REGRET_USD for d in diffs)
            print(f"  {a} minus {b:22s} {t_interval(diffs)}; lost $50+ less on {lower} worlds, $50+ more on {higher}")

    truth = {}
    for path in (REPOSITORY / "cases/procurement_allocation_v1/inference_v1/labeled").glob("*.json"):
        truth[path.stem] = {s["supplier_id"]: s["private_terms"] for s in json.loads(path.read_text())["payload"]["suppliers"]}
    print("\nsearch depth: suppliers quoted and sampled per completed cell, by binding risk")
    print(f"{'subject':24s} {'risk':9s} cells  quoted  sampled  actions  awards  solved")
    for name in names:
        for risk in ("timing", "capacity", "yield"):
            rows = [r for r in cells[name] if r["status"] == "completed" and world_of(r).endswith("__" + risk)]
            if not rows:
                continue
            quoted = statistics.fmean(len({a["supplier_id"] for a in r["action_trace"] if a["action"] == "request_quote"}) for r in rows)
            sampled = statistics.fmean(len({a["supplier_id"] for a in r["action_trace"] if a["action"] == "request_sample"}) for r in rows)
            print(f"{name:24s} {risk:9s} {len(rows):5d} {quoted:7.1f} {sampled:8.1f} {statistics.fmean(r['action_count'] for r in rows):8.1f}"
                  f" {sum(r['decision'] == 'award' for r in rows):7d} {sum(r['regret_to_upper_bound_usd'] < SOLVED_REGRET_USD for r in rows):7d}")
    for name in present:
        rows = cells[name]
        print(f"\n{name}, how each cell ended")
        print(Counter((r.get("decision"), r.get("termination_reason"), tuple(r.get("violations") or ())) for r in rows if r["status"] == "completed").most_common())
        print("actions per cell:", sorted(r["action_count"] for r in rows if r["status"] == "completed"))
        print("cells that did not complete:", [(world_of(r), r.get("failure_condition"), str(r.get("failure_message"))[:160]) for r in rows if r["status"] != "completed"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
