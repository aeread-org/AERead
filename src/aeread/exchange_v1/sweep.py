"""Exchange V1 sweep harness (D7) — configs x models x seeds, one CSV out.

Runs the cartesian grid through `runner` (one self-contained run dir
per cell) and aggregates stable columns into <out>/sweep_results.csv +
sweep_meta.json. Two invariants:

- harness failures are NEVER economic results: a crashed cell gets
  status=harness_error and empty metric columns, so an infra bug can't
  masquerade as "the model failed to trade";
- no model claim from a single seed: the sweep exists precisely to make
  multi-seed runs the default shape of any result.

Usage:
    python -m aeread.exchange_v1.sweep \
        --configs configs/exchange_economy/a.json configs/exchange_economy/b.json \
        --models google/gemini-3.5-flash --seeds 1 2 3 \
        --mode live_frozen --out sweeps/2026-07-03_smoke/ \
        [--cost-ceiling-usd 5.0] [--dry-run]

`--mode offline` (or --dry-run, which forces it) exercises the exact same grid
with the scripted policy at $0 — run that first to validate a sweep's shape.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Optional

from aeread.exchange_v1.runner import (  # noqa: E402
    InferenceOptions,
    RunnerError,
    run_v1,
)

SWEEP_SCHEMA_VERSION = "1.0"

# Stable column order — append-only by convention (downstream readers rely on it).
CSV_COLUMNS = [
    "config",
    "model",
    "seed",
    "mode",
    "status",
    "run_id",
    "run_dir",
    "rounds",
    "applied_mechanisms",
    "ir_violations",
    "initial_welfare",
    "final_welfare",
    "optimum_welfare",
    "welfare_ratio",
    "coordination_cost_total",
    "llm_calls",
    "fresh_calls",
    "cached_calls",
    "total_tokens",
    "estimated_cost_usd",
    "error",
]


def _cell_row_base(config_path: Path, model: str, seed: int, mode: str) -> dict[str, Any]:
    return {column: "" for column in CSV_COLUMNS} | {
        "config": config_path.stem,
        "model": model,
        "seed": seed,
        "mode": mode,
    }


def run_sweep(
    configs: list[str | Path],
    models: list[str],
    seeds: list[int],
    *,
    mode: str = "offline",
    out_root: str | Path = "sweeps/sweep",
    options_base: Optional[InferenceOptions] = None,
    rounds_override: Optional[int] = None,
    cost_ceiling_usd: Optional[float] = None,
    quiet: bool = False,
    strict: bool = True,
) -> Path:
    """Run the grid; returns the sweep directory containing sweep_results.csv.

    strict defaults to True here (unlike single runs): a sweep feeds model
    claims, so a cell whose manifest is incomplete must fail as harness_error
    rather than contribute numbers.
    """
    out_root = Path(out_root)
    runs_dir = out_root / "runs"
    out_root.mkdir(parents=True, exist_ok=True)
    options_base = options_base or InferenceOptions()

    rows: list[dict[str, Any]] = []
    total_cost = 0.0
    aborted_reason: Optional[str] = None
    csv_path = out_root / "sweep_results.csv"

    def _flush_csv() -> None:
        # rewritten after every cell so a mid-sweep crash loses nothing
        with csv_path.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    cells = [
        (Path(config), model, seed)
        for config in configs
        for model in models
        for seed in seeds
    ]
    for index, (config_path, model, seed) in enumerate(cells):
        row = _cell_row_base(config_path, model, seed, mode)
        if aborted_reason is not None:
            row["status"] = "skipped"
            row["error"] = aborted_reason
            rows.append(row)
            _flush_csv()
            continue
        run_id = f"{config_path.stem}__{model.replace('/', '-')}__s{seed}__cell{index:04d}"
        try:
            outcome = run_v1(
                config_path,
                mode=mode,
                seed=seed,
                out_root=runs_dir,
                options=InferenceOptions(
                    model=model,
                    compiler_model=options_base.compiler_model,
                    verifier_model=options_base.verifier_model,
                    max_tokens=options_base.max_tokens,
                    temperature=options_base.temperature,
                    sample=options_base.sample,
                    batch=options_base.batch,
                ),
                rounds_override=rounds_override,
                run_id=run_id,
                quiet=True,
                strict=strict,
            )
        except BaseException as err:  # noqa: BLE001 — a cell must never sink the sweep
            if isinstance(err, KeyboardInterrupt):
                raise
            row["status"] = "harness_error"
            row["run_id"] = run_id
            row["error"] = f"{type(err).__name__}: {err}"
            rows.append(row)
            _flush_csv()
            if not quiet:
                print(f"[{index + 1}/{len(cells)}] HARNESS ERROR {run_id}: {row['error']}")
                traceback.print_exc()
            continue

        summary = outcome.summary
        usage = summary.get("usage") or {}
        cell_cost = float(usage.get("estimated_cost_usd") or 0.0)
        total_cost += cell_cost
        row.update(
            {
                "status": "ok",
                "run_id": run_id,
                "run_dir": str(outcome.run_dir),
                "rounds": summary["rounds"],
                "applied_mechanisms": summary["applied_mechanisms"],
                "ir_violations": summary["ir_violations"],
                "initial_welfare": summary["initial_welfare"],
                "final_welfare": summary["final_welfare"],
                "optimum_welfare": summary["optimum_welfare"],
                "welfare_ratio": summary["welfare_ratio"],
                "coordination_cost_total": summary["coordination_cost_total"],
                "llm_calls": usage.get("calls", 0),
                "fresh_calls": usage.get("fresh_calls", 0),
                "cached_calls": usage.get("cached_calls", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "estimated_cost_usd": cell_cost,
            }
        )
        rows.append(row)
        _flush_csv()
        if not quiet:
            print(
                f"[{index + 1}/{len(cells)}] ok {run_id} "
                f"welfare_ratio={summary['welfare_ratio']:.3f} cost=${cell_cost:.4f}"
            )
        if cost_ceiling_usd is not None and total_cost >= cost_ceiling_usd:
            aborted_reason = (
                f"cost ceiling reached: ${total_cost:.4f} >= ${cost_ceiling_usd:.4f}"
            )
            if not quiet:
                print(f"ABORTING remaining cells: {aborted_reason}")

    _flush_csv()
    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    meta = {
        "sweep_schema_version": SWEEP_SCHEMA_VERSION,
        "mode": mode,
        "configs": [str(c) for c in configs],
        "models": models,
        "seeds": seeds,
        "cells": len(cells),
        "status_counts": status_counts,
        "total_estimated_cost_usd": round(total_cost, 6),
        "cost_ceiling_usd": cost_ceiling_usd,
        "aborted_reason": aborted_reason,
    }
    (out_root / "sweep_meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    if not quiet:
        print(
            f"sweep done: {status_counts} | total cost ${total_cost:.4f} | "
            f"results: {csv_path}"
        )
    return out_root


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--configs", nargs="+", required=True)
    ap.add_argument("--models", nargs="+", default=["google/gemini-3.5-flash"])
    ap.add_argument("--seeds", nargs="+", type=int, required=True)
    ap.add_argument("--mode", choices=("offline", "live_frozen"), default="offline")
    ap.add_argument("--out", default="sweeps/sweep")
    ap.add_argument("--rounds-override", type=int, default=None)
    ap.add_argument("--max-tokens", type=int, default=1200)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--batch", action="store_true")
    ap.add_argument("--compiler-model", default=None)
    ap.add_argument("--verifier-model", default=None)
    ap.add_argument(
        "--cost-ceiling-usd",
        type=float,
        default=None,
        help="abort remaining cells once total estimated cost reaches this",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="force offline mode: validate the sweep shape at $0 before going live",
    )
    ap.add_argument(
        "--no-strict",
        action="store_true",
        help="tolerate funnel-check mismatches (cells complete as manifest_incomplete "
        "instead of harness_error); strict is the default in sweeps",
    )
    args = ap.parse_args(argv)

    mode = "offline" if args.dry_run else args.mode
    for config in args.configs:
        if not Path(config).is_file():
            raise RunnerError(f"config not found: {config}")
    run_sweep(
        args.configs,
        args.models,
        args.seeds,
        mode=mode,
        out_root=args.out,
        options_base=InferenceOptions(
            compiler_model=args.compiler_model,
            verifier_model=args.verifier_model,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            sample=args.sample,
            batch=args.batch,
        ),
        rounds_override=args.rounds_override,
        cost_ceiling_usd=args.cost_ceiling_usd,
        strict=not args.no_strict,
    )


if __name__ == "__main__":
    main()
