"""Write the risk-allocation pack as shared-runner cases, one per world and seat.

    python -m aeread_families.datacenter_development.risk_allocation_pack risk_allocation_dev_v1 --write

Each world of :func:`risk_allocation.build_pack` becomes two cases, the client
seat and the integrator seat, on the same facts. Case ids are neutral codes so
no cell name reaches anything a model sees; ``pack.json`` maps them back to
cells, twins and the reference for grading. Both seats of a world and its twin
share one set of break-off draws.
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

from . import risk_allocation as ra
from .risk_allocation_environment import FAMILY_ID, FAMILY_VERSION, TERMINATIONS, VISIBILITY_POLICY, RiskAllocationPlugin

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASES_ROOT = REPOSITORY_ROOT / "cases" / FAMILY_ID
GENERATOR_ID = "datacenter_risk_allocation_generator_v1"
GENERATOR_VERSION = "0.1.0"
PACKS: dict[str, dict[str, Any]] = {
    "risk_allocation_dev_v1": {"split": "dev", "base_seed": 2460000, "seeds_per_cell": 2},
    # The same worlds and break-off draws under the two-prices protocol: a price
    # request may name an alternate package. Its own case ids and digests.
    "risk_allocation_two_prices_dev_v1": {"split": "dev", "base_seed": 2460000, "seeds_per_cell": 2, "packages_per_request": 2},
}


def neutral_code(pack: str, slug: str, seat: str) -> str:
    return hashlib.sha256(f"{pack}:{slug}:{seat}".encode()).hexdigest()[:8]


def breakoff_draws(seed: int, rounds: int) -> list[float]:
    rng = random.Random(f"risk_allocation_breakoff:{seed}")
    return [round(rng.random(), 6) for _ in range(rounds)]


def case_for(pack: str, split: str, row: dict[str, Any], seat: str, packages_per_request: int = 1) -> dict[str, Any]:
    world = row["world"]
    rounds = len(world["terms"]["ask_premium"]) - 1
    payload = {
        "seat": seat,
        "world": world,
        "integrator_type": row["hidden_type"],
        "breakoff_draws": breakoff_draws(row["seed"], rounds),
    }
    if packages_per_request != 1:
        payload["packages_per_request"] = packages_per_request
    RiskAllocationPlugin().validate_payload(payload)
    raw = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": f"{FAMILY_ID}.{split}.{neutral_code(pack, row['slug'], seat)}",
        "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "split": split,
        "world_seed": row["seed"],
        "seats": [{"id": seat, "role": seat}],
        "episode": {"max_logical_actions": rounds + 1, "termination": list(TERMINATIONS)},
        "visibility_policy": VISIBILITY_POLICY,
        "payload": payload,
        "provenance": {"generator_id": GENERATOR_ID, "generator_version": GENERATOR_VERSION, "review_status": "generated"},
    }
    raw["content_sha256"] = case_content_sha256(raw)
    return raw


def build(pack: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    spec = PACKS[pack]
    rows = ra.build_pack(spec["seeds_per_cell"], spec["base_seed"])
    per_request = spec.get("packages_per_request", 1)
    cases: list[dict[str, Any]] = []
    index: list[dict[str, Any]] = []
    for row in rows:
        entry = {k: row[k] for k in ("slug", "cell", "seed", "lesson", "hidden_type", "efficient_package", "joint_saving_vs_opening")}
        if "twin_of" in row:
            entry["twin_of"] = row["twin_of"]
        entry["client_risk_charge"] = row["world"]["client"]["risk_charge"]
        entry["seats"] = {}
        for seat in ra.SEATS:
            raw = case_for(pack, spec["split"], row, seat, per_request)
            cases.append(raw)
            view = row if seat == "client" else row["integrator_seat"]
            if per_request != 1:  # admission stays on the one-price protocol; the views are the variant's
                full = ra.seat_view(ra.world_from_dict(row["world"]), seat, ra.IntegratorType(**row["hidden_type"]), alternates=True)
                view = {
                    "reference_first_move": {"kind": ra.first_move_kind(full["reference"]["first_action"]), "action": full["reference"]["first_action"].label()},
                    "reference_expected_cost": full["reference"]["expected_cost"],
                    "rule_regret_prior": {k: round(v, 3) for k, v in full["rule_regret"].items()},
                }
            entry["seats"][seat] = {
                "case_id": raw["case_id"],
                "content_sha256": raw["content_sha256"],
                "reference_first_move": view["reference_first_move"],
                "reference_expected_cost": round(view["reference_expected_cost"], 6),
                "rule_regret_prior": view["rule_regret_prior"],
            }
        index.append(entry)
    manifest = {
        "pack": pack,
        "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "generator": {"id": GENERATOR_ID, "version": GENERATOR_VERSION, **spec},
        "claim_status": "dev pack for diagnostics; no model result is a claim",
        "worlds": index,
    }
    return cases, manifest


def write(pack: str) -> Path:
    cases, manifest = build(pack)
    root = CASES_ROOT / pack
    root.mkdir(parents=True, exist_ok=True)
    for raw in cases:
        code = raw["case_id"].rsplit(".", 1)[-1]
        (root / f"{code}.json").write_text(json.dumps(raw, indent=1, sort_keys=True) + "\n")
    (root / "pack.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return root


def load(pack: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    root = CASES_ROOT / pack
    manifest = json.loads((root / "pack.json").read_text())
    cases = {}
    for world in manifest["worlds"]:
        for seat in world["seats"].values():
            code = seat["case_id"].rsplit(".", 1)[-1]
            cases[seat["case_id"]] = json.loads((root / f"{code}.json").read_text())
    return manifest, cases


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pack", choices=sorted(PACKS))
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    if args.write:
        print(write(args.pack))
    else:
        cases, manifest = build(args.pack)
        print(f"{len(manifest['worlds'])} worlds, {len(cases)} cases")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
