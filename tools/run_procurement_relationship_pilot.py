#!/usr/bin/env python
"""Live passes over the repeated-sourcing worlds on a frozen route.

    prepare  --run-root runs/<id> --campaign-id <id> --route <route> --seeds 73201 73202 73203
    execute  --run-root runs/<id>                       one episode per world x seed, sequential
    replay   --run-root runs/<id>                       re-audit every receipt from disk, no provider
    compare  --run-root runs/<id> --against runs/<other> paired by world and seed
    publish  --run-root runs/<id>                       seal the evidence bundle under evidence/

Everything lives in ``aeread_families.procurement_allocation.relationship_campaign``;
this file parses arguments and prints. The key is read from ``OPENROUTER_API_KEY``
and never written; the run directory is gitignored.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from aeread_families.procurement_allocation import relationship_campaign as campaign  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=("prepare", "execute", "replay", "compare", "confirmatory", "publish"))
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--campaign-id", default=None, help="prepare: the frozen campaign identity")
    parser.add_argument(
        "--route", default=campaign.DEFAULT_ROUTE, choices=sorted(campaign.ROUTES), help="prepare: the route to freeze"
    )
    parser.add_argument(
        "--seeds", type=int, nargs="+", default=list(campaign.DEFAULT_SEEDS), help="prepare: one cell per world per seed"
    )
    parser.add_argument(
        "--pack",
        default="relationship_v1",
        help="prepare: which committed pack to run (relationship_v1, relationship_dev_v2, relationship_holdout_v1)",
    )
    parser.add_argument("--against", type=Path, default=None, help="compare / confirmatory: the other run root")
    parser.add_argument(
        "--confirmatory",
        action="store_true",
        help="prepare: freeze the pre-registration of relationship_confirmatory into the plan",
    )
    parser.add_argument("--publication-root", type=Path, default=None, help="publish: override the evidence path")
    arguments = parser.parse_args(argv)
    run_root = arguments.run_root.resolve()

    if arguments.step == "prepare":
        if not arguments.campaign_id:
            raise SystemExit("prepare requires --campaign-id")
        preregistration = None
        if arguments.confirmatory:
            from aeread_families.procurement_allocation.relationship_confirmatory import PREREGISTRATION

            if arguments.pack != PREREGISTRATION["pack"] or list(arguments.seeds) != PREREGISTRATION["seeds"]:
                raise SystemExit(
                    f"a confirmatory plan runs pack {PREREGISTRATION['pack']} on seeds {PREREGISTRATION['seeds']}"
                )
            preregistration = PREREGISTRATION
        plan = campaign.prepare(
            run_root,
            campaign_id=arguments.campaign_id,
            seeds=arguments.seeds,
            route_id=arguments.route,
            case_paths=campaign.pack_paths(arguments.pack),
            preregistration=preregistration,
        )
        print(
            json.dumps(
                {k: plan[k] for k in ("campaign_id", "route_id", "plan_sha256", "git_head", "seeds")}
                | {"cells": len(plan["cells"])},
                indent=2,
            )
        )
        return 0

    if arguments.step == "execute":
        summary = campaign.execute(run_root)
        keys = (
            "completed",
            "failed",
            "not_attempted",
            "cost_usd",
            "mean_regret_usd",
            "mean_regret_usd_95_world_bootstrap",
            "mean_advantage_over_myopic_usd",
            "mean_advantage_over_myopic_usd_95_world_bootstrap",
            "counters",
            "inquiries",
            "switches",
            "halted",
        )
        print(json.dumps({k: summary.get(k) for k in keys}, indent=2))
        return 2 if summary.get("halted") else 0

    if arguments.step == "replay":
        report = campaign.replay(run_root)
        print(
            json.dumps(
                {
                    label: (cell if isinstance(cell, str) else cell["receipt_sha256_matches_result"])
                    for label, cell in report["cells"].items()
                },
                indent=2,
            )
        )
        return 0

    if arguments.step == "compare":
        if arguments.against is None:
            raise SystemExit("compare requires --against")
        report = campaign.compare(run_root, arguments.against.resolve())
        print(json.dumps({k: v for k, v in report.items() if k != "per_world"}, indent=2))
        for slug, row in sorted(report["per_world"].items()):
            print(
                f"{slug:26s} regret delta {row['regret']:8.2f}  counters {row['counters']:+.2f}  quoted {row['quoted']:+.2f}"
            )
        return 0

    if arguments.step == "confirmatory":
        if arguments.against is None:
            raise SystemExit("confirmatory requires --against")
        from aeread_families.procurement_allocation.relationship_confirmatory import write

        report = write(run_root, arguments.against.resolve())
        print(json.dumps({k: v for k, v in report.items() if k != "O3_vs_deadline_aware"}, indent=2, default=str))
        for side, row in report["O3_vs_deadline_aware"].items():
            print(side, "vs deadline_aware:", row["mean"], row["interval_95"], row["worlds_model_better"], "worlds better,", row["verdict"])
        return 0

    manifest = campaign.publish(run_root, publication_root=arguments.publication_root)
    print(json.dumps({"publication_id": manifest["publication_id"], "artifacts": len(manifest["artifacts"]), "manifest_sha256": manifest["manifest_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
