#!/usr/bin/env python3
"""Memory-on vs memory-off A/B for the EverOS integration.

Runs the same case + seed list twice through the submission harness:

- ``mem``   — :class:`MemoryCandidate` backed by a live EverOS server;
  episodes run **sequentially in seed order** so memory accumulates.
- ``nomem`` — identical candidate wired to :class:`NullMemory` (control).

Per-arm output: ``results.jsonl`` (one row per episode) and
``summary.json`` (pooled AER = sigma w_real / sigma denominator over ok
episodes, seeded episode-bootstrap CI, LLM usage). Replay verification is
off in both arms (cross-episode memory is not byte-replayable).

Example::

    python integrations/everos/everos_memory_ab.py \
        --case cases/exchange_v1/v0/case03_hidden_discovery.json \
        --seeds 1200:1212 --model deepseek/deepseek-v4-flash \
        --everos-url http://127.0.0.1:8377 --out output/everos_ab
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

from aeread.integrations.everos_memory import (
    EverOSMemory,
    MemoryCandidate,
    NullMemory,
    arm_health,
    build_openrouter_llm_fn,
    run_memory_episode,
    should_abort_memory_arm,
)


def parse_seeds(spec: str) -> list[int]:
    if ":" in spec:
        lo, hi = spec.split(":")
        return list(range(int(lo), int(hi)))
    return [int(s) for s in spec.split(",") if s.strip()]


def boot_ci(rows: list[dict], n: int = 2000, seed: int = 7) -> tuple | None:
    ok = [(r["w_real"], r["denominator"]) for r in rows
          if r.get("w_real") is not None and r.get("denominator")]
    if len(ok) < 2:
        return None
    rng = random.Random(seed)
    stats = []
    for _ in range(n):
        pick = [rng.choice(ok) for _ in ok]
        d = sum(x[1] for x in pick)
        if d > 1e-9:
            stats.append(sum(x[0] for x in pick) / d)
    stats.sort()
    return stats[int(0.025 * len(stats))], stats[int(0.975 * len(stats))]


def pooled(rows: list[dict]) -> float | None:
    d = sum(r["denominator"] for r in rows
            if r.get("w_real") is not None and r.get("denominator"))
    if d <= 1e-9:
        return None
    return sum(r["w_real"] for r in rows
               if r.get("w_real") is not None and r.get("denominator")) / d


def run_arm(arm: str, args: argparse.Namespace, out_dir: Path) -> dict:
    case_path = Path(args.case)
    if arm.startswith("mem"):
        memory = EverOSMemory(args.everos_url, app_id="aeread-ab",
                              project_id=args.memory_project or case_path.stem)
    else:
        memory = NullMemory()
    llm_fn = build_openrouter_llm_fn(
        args.model, temperature=args.temperature, max_tokens=args.max_tokens)
    candidate = MemoryCandidate(llm_fn, memory,
                                agent_id=f"aeread-{arm}",
                                memory_top_k=args.top_k,
                                min_score=args.min_score,
                                distill=args.distill,
                                overfetch=args.overfetch)

    arm_dir = out_dir / arm
    arm_dir.mkdir(parents=True, exist_ok=True)
    results_path = arm_dir / "results.jsonl"
    memory_arm = arm.startswith("mem")
    rows: list[dict] = []
    for seed in parse_seeds(args.seeds):
        t0 = time.time()
        try:
            r = run_memory_episode(case_path, seed, candidate,
                                   agent_label=f"everos-{arm}",
                                   max_tokens=args.max_tokens)
            row = {"arm": arm, "case": case_path.stem, "seed": seed,
                   "status": r["status"], "aer": r["aer"],
                   "w_real": r["w_real"], "denominator": r["denominator"],
                   "turns": len(r["turns"]),
                   "blank_turns": r["blank_turns"],
                   "memory_snippets": sum(t.get("memory_snippets", 0)
                                          for t in r["turns"]),
                   "memory_errors": r["memory_errors"],
                   "error": r.get("error"),
                   "secs": round(time.time() - t0, 1)}
        except Exception as err:  # noqa: BLE001 - keep the sweep alive
            row = {"arm": arm, "case": case_path.stem, "seed": seed,
                   "status": "error", "error": f"{type(err).__name__}: {err}",
                   "secs": round(time.time() - t0, 1)}
        rows.append(row)
        with open(results_path, "a") as fh:
            fh.write(json.dumps(row) + "\n")
        if row.get("status") != "error":
            turns_dir = arm_dir / "turns"
            turns_dir.mkdir(exist_ok=True)
            (turns_dir / f"s{seed}.json").write_text(
                json.dumps(r["turns"], indent=1))
        print(f"[{arm}] seed {seed}: status={row.get('status')} "
              f"aer={row.get('aer')} snippets={row.get('memory_snippets')} "
              f"blank_turns={row.get('blank_turns')} "
              f"({row['secs']}s)", flush=True)

        # a memory server that is up but returning nothing makes this arm a
        # second control; stop at 3 episodes rather than paying for 12
        if memory_arm:
            reason = should_abort_memory_arm(rows)
            if reason:
                print(f"[{arm}] ABORT: {reason}", flush=True)
                break

    health = arm_health(rows, memory_arm=memory_arm,
                        max_blank_rate=args.max_blank_rate)
    summary = {"arm": arm, "case": case_path.stem, "model": args.model,
               "n": len(rows),
               "n_ok": sum(1 for r in rows if r.get("status") == "ok"),
               "pooled_aer": pooled(rows), "ci95": boot_ci(rows),
               "memory_errors": sum(r.get("memory_errors", 0) for r in rows),
               "health": health,
               "llm_usage": getattr(llm_fn, "usage", None)}
    (arm_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    rate = health["blank_turn_rate"]
    print(f"[{arm}] pooled AER={summary['pooled_aer']} "
          f"ci95={summary['ci95']} "
          f"blank_turns={health['blank_turns']}/{health['turns']}"
          f"{'' if rate is None else f' ({rate:.1%})'} "
          f"snippets={health['memory_snippets']} "
          f"usage={summary['llm_usage']}", flush=True)
    for problem in health["problems"]:
        print(f"[{arm}] UNHEALTHY: {problem}", flush=True)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", required=True)
    ap.add_argument("--seeds", default="1200:1212",
                    help="lo:hi range or comma list (dev seeds)")
    ap.add_argument("--model", default="deepseek/deepseek-v4-flash")
    ap.add_argument("--everos-url", default="http://127.0.0.1:8377")
    ap.add_argument("--arms", default="nomem,mem",
                    help="comma list drawn from {nomem,mem}")
    ap.add_argument("--out", default="output/everos_ab")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-tokens", type=int, default=1200)
    ap.add_argument("--top-k", type=int, default=4)
    ap.add_argument("--min-score", type=float, default=None)
    ap.add_argument("--overfetch", type=int, default=1,
                    help="search top_k*overfetch, outcome-filter, cap at top_k")
    ap.add_argument("--distill", action="store_true",
                    help="LLM-written transferable-lessons reflection")
    ap.add_argument("--memory-project", default=None,
                    help="EverOS project_id override (fresh memory scope)")
    ap.add_argument("--max-blank-rate", type=float, default=0.10,
                    help="fraction of muted turns above which an arm is "
                         "reported UNHEALTHY and the run exits non-zero")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries = [run_arm(arm.strip(), args, out_dir)
                 for arm in args.arms.split(",") if arm.strip()]
    (out_dir / "ab_summary.json").write_text(json.dumps(summaries, indent=1))
    print("A/B complete ->", out_dir / "ab_summary.json")

    # an arm whose validity counters failed must not be quietly poolable:
    # exit non-zero so a queue script stops instead of banking the number
    unhealthy = [s["arm"] for s in summaries if s["health"]["problems"]]
    if unhealthy:
        print("UNHEALTHY ARMS (do not pool):", ", ".join(unhealthy))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
