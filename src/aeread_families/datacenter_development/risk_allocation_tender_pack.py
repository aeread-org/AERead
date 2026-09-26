"""Write the tender cases: one per generated world, the client seat.

    python -m aeread_families.datacenter_development.risk_allocation_tender_pack tender_pilot_v1 --write

Four world types (``risk_allocation_tender.WORLD_TYPES``) label coverage; within each, a
world is admitted under a situation (``SITUATIONS``) only when every bid reveals its
firm's type and the situation's margins hold for the reference. The quotas follow what
each world type supplies: a client that tolerates risk almost never finds the lowest
bidder best and never does better managing the deployment itself, so it carries neither
quota. Case ids are neutral codes; ``pack.json`` maps them back to world type, situation
and the reference's first move, none of which reaches a prompt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from . import risk_allocation_tender as rt
from .risk_allocation_tender_environment import FAMILY_ID, FAMILY_VERSION, SEAT, TERMINATIONS, VISIBILITY_POLICY, TenderPlugin

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASES_ROOT = REPOSITORY_ROOT / "cases" / FAMILY_ID
GENERATOR_ID = "datacenter_risk_allocation_tender_generator_v1"
GENERATOR_VERSION = "0.1.0"
PILOT_QUOTAS = {
    "risk_tolerant": {"another_bidder_is_best": 5, "lowest_bidder_is_best": 1},
    "moderate": {"self_manage": 2, "another_bidder_is_best": 2, "lowest_bidder_is_best": 2},
    "risk_averse": {"another_bidder_is_best": 4, "lowest_bidder_is_best": 2},
    "fragile_bidders": {"self_manage": 2, "another_bidder_is_best": 2, "lowest_bidder_is_best": 2},
}
PACKS: dict[str, dict[str, Any]] = {"tender_pilot_v1": {"split": "eval", "base_seed": 2600000, "quotas": PILOT_QUOTAS}}


def breakoff_draws(seed: int, bidders: int, rounds: int) -> list[list[float]]:
    """One uniform draw per bidder per round, each bidder its own stream."""
    out = []
    for j in range(bidders):
        rng = random.Random(f"risk_allocation_tender_breakoff:{seed}:{rt.BIDDER_IDS[j]}")
        out.append([round(rng.random(), 6) for _ in range(rounds)])
    return out


def build(pack: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    spec = PACKS[pack]
    plugin = TenderPlugin()
    cases, index = [], []
    for row in rt.build_pack(spec["quotas"], spec["base_seed"]):
        rounds = len(row["world"]["terms"]["ask_premium"]) - 1
        payload = {"world": row["world"], "extras": row["extras"], "bidders": row["bidders"],
                   "breakoff_draws": breakoff_draws(row["seed"], len(row["bidders"]), rounds)}
        plugin.validate_payload(payload)
        raw = {
            "spec_version": CaseManifest.SPEC_VERSION,
            "case_id": f"{FAMILY_ID}.{spec['split']}.{hashlib.sha256((pack + ':' + row['slug']).encode()).hexdigest()[:8]}",
            "family_id": FAMILY_ID, "family_version": FAMILY_VERSION, "split": spec["split"], "world_seed": row["seed"],
            "seats": [{"id": SEAT, "role": SEAT}], "episode": {"max_logical_actions": rounds + 1, "termination": list(TERMINATIONS)},
            "visibility_policy": VISIBILITY_POLICY, "payload": payload,
            "provenance": {"generator_id": GENERATOR_ID, "generator_version": GENERATOR_VERSION, "review_status": "generated"},
        }
        raw["content_sha256"] = case_content_sha256(raw)
        cases.append(raw)
        solver = rt.solver_for(payload)
        s = solver.start()
        floors = [solver.floor_best(j) for j in range(len(solver.bidders))]
        index.append({"slug": row["slug"], "world_type": row["world_type"], "situation": row["situation"], "seed": row["seed"], "lesson": row["lesson"],
                      "case_id": raw["case_id"], "content_sha256": raw["content_sha256"],
                      "bidders": [{"id": b.id, "playbook": b.playbook, "bid_all_in": solver.bid(j), "best_contract": floors[j][0].as_dict(),
                                   "best_contract_cost": round(floors[j][1], 3)} for j, b in enumerate(solver.bidders)],
                      "lowest_bidder": rt.BIDDER_IDS[rt.lowest_bid(solver)], "best_attainable": solver.best_attainable()[0],
                      "reference_first_move": solver.best(s).label(),
                      "reference_expected_cost": round(solver.value(s), 3), "self_manage_cost": round(solver.out, 3)})
    manifest = {"pack": pack, "family_id": FAMILY_ID, "family_version": FAMILY_VERSION,
                "generator": {"id": GENERATOR_ID, "version": GENERATOR_VERSION, **spec},
                "claim_status": "generated worlds; no model result is a claim", "worlds": index}
    return cases, manifest


def write(pack: str) -> Path:
    cases, manifest = build(pack)
    root = CASES_ROOT / pack
    root.mkdir(parents=True, exist_ok=True)
    for raw in cases:
        (root / f"{raw['case_id'].rsplit('.', 1)[-1]}.json").write_text(json.dumps(raw, indent=1, sort_keys=True) + "\n")
    (root / "pack.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return root


def load(pack: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    root = CASES_ROOT / pack
    manifest = json.loads((root / "pack.json").read_text())
    return manifest, {w["case_id"]: json.loads((root / f"{w['case_id'].rsplit('.', 1)[-1]}.json").read_text()) for w in manifest["worlds"]}


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pack", choices=sorted(PACKS))
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    print(write(args.pack) if args.write else f"{len(build(args.pack)[0])} cases")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
