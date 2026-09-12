"""Run the Refund V2.1 1:N panel through the shared-runner adapter."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .v2_environment import build_1n_panel
from .v2_runner import run as run_shared


def run(seeds: tuple[int, ...], output: Path) -> dict:
    report = asyncio.run(
        run_shared(
            output=output,
            provider="scripted",
            model="refund-v21-scripted",
            revision="2.1.0",
            world_seeds=seeds,
            active_agents=("policy",),
        )
    )
    report.update(
        {
            "topology": "1:N",
            "seeds": list(seeds),
            "scenarios": sorted(
                {case.scenario for seed in seeds for case in build_1n_panel(seed)}
            ),
            "planned_cases": report["planned_cells"],
            "completed_cases": report["completed_cells"],
        }
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "refund_v2_1n_summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world-seeds", default="1,2,3,4,5")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    seeds = tuple(int(item.strip()) for item in args.world_seeds.split(",") if item.strip())
    print(json.dumps(run(seeds, args.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
