"""Write the playbook-menu cases: one per generated world, the client seat.

    python -m aeread_families.datacenter_development.risk_allocation_menu_pack menu_eval_v1 --write

Six situations (``risk_allocation_menu.CELLS``) times three playbooks, each world
admitted only when its lesson holds for the informed reference. Case ids are neutral
codes; ``pack.json`` maps them back to situation, playbook and the reference's first
move, none of which reaches a prompt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from . import risk_allocation_menu as rm
from . import risk_allocation_pack as rp
from .risk_allocation_menu_environment import FAMILY_ID, FAMILY_VERSION, SEAT, TERMINATIONS, VISIBILITY_POLICY, MenuPlugin

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASES_ROOT = REPOSITORY_ROOT / "cases" / FAMILY_ID
GENERATOR_ID = "datacenter_risk_allocation_menu_generator_v1"
GENERATOR_VERSION = "0.1.0"
PACKS: dict[str, dict[str, Any]] = {"menu_eval_v1": {"split": "eval", "base_seed": 2480000, "seeds_per_cell": 2}}


def build(pack: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    spec = PACKS[pack]
    plugin = MenuPlugin()
    cases, index = [], []
    for row in rm.build_menu_pack(spec["seeds_per_cell"], spec["base_seed"]):
        rounds = len(row["world"]["terms"]["ask_premium"]) - 1
        payload = {"world": row["world"], "integrator_type": row["integrator_type"], "team": row["team"], "breakoff_draws": rp.breakoff_draws(row["seed"], rounds)}
        plugin.validate_payload(payload)
        raw = {
            "spec_version": CaseManifest.SPEC_VERSION,
            "case_id": f"{FAMILY_ID}.{spec['split']}.{hashlib.sha256(f'{pack}:{row['slug']}'.encode()).hexdigest()[:8]}",
            "family_id": FAMILY_ID, "family_version": FAMILY_VERSION, "split": spec["split"], "world_seed": row["seed"],
            "seats": [{"id": SEAT, "role": SEAT}], "episode": {"max_logical_actions": rounds + 1, "termination": list(TERMINATIONS)},
            "visibility_policy": VISIBILITY_POLICY, "payload": payload,
            "provenance": {"generator_id": GENERATOR_ID, "generator_version": GENERATOR_VERSION, "review_status": "generated"},
        }
        raw["content_sha256"] = case_content_sha256(raw)
        cases.append(raw)
        mw, it = rm.menu_world_from(payload)
        s = rm.start_state(mw, it)
        solver = rm.MenuSolver(mw)
        k, best = rm.best_item(mw, it)
        index.append({"slug": row["slug"], "cell": row["cell"], "playbook": row["playbook"], "seed": row["seed"], "lesson": row["lesson"],
                      "case_id": raw["case_id"], "content_sha256": raw["content_sha256"],
                      "reference_first_move": solver.best(s).label(), "reference_expected_cost": round(solver.value(s), 3),
                      "best_item": rm.LABELS[k], "best_item_cost": round(best, 3), "best_outside": mw.best_outside[0]})
    manifest = {"pack": pack, "family_id": FAMILY_ID, "family_version": FAMILY_VERSION, "generator": {"id": GENERATOR_ID, "version": GENERATOR_VERSION, **spec},
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
