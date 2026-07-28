"""Task rows for the aeread rLLM dataset (experimental).

Rows are pure parameters (FrozenLake pattern): the arena is rebuilt
deterministically from ``(case_path, seed)`` inside the flow. Register the
public dev split locally with::

    python -m aeread.integrations.rllm_dataset --register

Official evaluation uses an additional private held-out seed set that never
ships in this repository.
"""
from __future__ import annotations

import argparse
import glob
from pathlib import Path
from typing import Any

DEFAULT_CASES = "configs/exchange_economy/cases_v0/case0*.json"
DEFAULT_SEEDS = tuple(range(1200, 1210))


def build_rows(cases_glob: str = DEFAULT_CASES,
               seeds: tuple[int, ...] = DEFAULT_SEEDS) -> list[dict[str, Any]]:
    case_paths = sorted(glob.glob(cases_glob))
    if not case_paths:
        raise FileNotFoundError(f"no case configs match {cases_glob!r} "
                                "(run from a repo checkout, or pass an absolute glob)")
    rows = []
    for cp in case_paths:
        stem = Path(cp).stem
        for seed in seeds:
            rows.append({
                "uid": f"{stem}:s{seed}",
                "case_path": str(Path(cp).resolve()),
                "seed": int(seed),
                "question": f"AERead exchange-economy case {stem}, seed {seed}",
            })
    return rows


def register(name: str = "aeread", split: str = "test",
             cases_glob: str = DEFAULT_CASES,
             seeds: tuple[int, ...] = DEFAULT_SEEDS) -> int:
    from rllm.data import DatasetRegistry  # type: ignore[import-not-found]
    rows = build_rows(cases_glob, seeds)
    DatasetRegistry.register_dataset(name, rows, split)
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--register", action="store_true")
    ap.add_argument("--name", default="aeread")
    ap.add_argument("--split", default="test")
    ap.add_argument("--cases", default=DEFAULT_CASES)
    ap.add_argument("--seeds", type=int, nargs="*", default=list(DEFAULT_SEEDS))
    args = ap.parse_args()
    if args.register:
        n = register(args.name, args.split, args.cases, tuple(args.seeds))
        print(f"registered {n} rows as dataset {args.name!r} split {args.split!r}")
    else:
        rows = build_rows(args.cases, tuple(args.seeds))
        print(f"{len(rows)} rows; first: {rows[0]}")


if __name__ == "__main__":
    main()
