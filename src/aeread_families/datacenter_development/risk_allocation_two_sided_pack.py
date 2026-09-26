"""Write the two-sided cases: one per world of a one-sided pack, both seats in it.

    python -m aeread_families.datacenter_development.risk_allocation_two_sided_pack two_sided_eval_v1 --write

The worlds, hidden types and seeds are the one-sided pack's, so a two-sided
episode pairs with the one-sided cells of the same world. Break-off draws extend
the one-sided stream to one per move (the first two are the one-sided draws).
Case ids are neutral codes; ``pack.json`` maps them back to cells and twins.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from . import risk_allocation as ra
from . import risk_allocation_pack as rp
from . import risk_allocation_two_sided as ts
from .risk_allocation_two_sided_environment import FAMILY_ID, FAMILY_VERSION, TERMINATIONS, VISIBILITY_POLICY, TwoSidedPlugin

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASES_ROOT = REPOSITORY_ROOT / "cases" / FAMILY_ID
GENERATOR_ID = "datacenter_risk_allocation_two_sided_generator_v1"
GENERATOR_VERSION = "0.1.0"
PACKS: dict[str, dict[str, Any]] = {
    "two_sided_eval_v1": {"split": "eval", "source_pack": "risk_allocation_eval_v1"},
}


def build(pack: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    spec = PACKS[pack]
    source, source_cases = rp.load(spec["source_pack"])
    plugin = TwoSidedPlugin()
    cases, index = [], []
    for world in source["worlds"]:
        one = source_cases[world["seats"]["client"]["case_id"]]
        w = ra.world_from_dict(one["payload"]["world"])
        payload = {"world": one["payload"]["world"], "integrator_type": one["payload"]["integrator_type"],
                   "breakoff_draws": rp.breakoff_draws(one["world_seed"], ts.max_moves(w))}
        plugin.validate_payload(payload)
        code = hashlib.sha256(f"{pack}:{world['slug']}".encode()).hexdigest()[:8]
        raw = {
            "spec_version": CaseManifest.SPEC_VERSION,
            "case_id": f"{FAMILY_ID}.{spec['split']}.{code}",
            "family_id": FAMILY_ID,
            "family_version": FAMILY_VERSION,
            "split": spec["split"],
            "world_seed": one["world_seed"],
            "seats": [{"id": s, "role": s} for s in ts.SEATS],
            "episode": {"max_logical_actions": ts.max_moves(w), "termination": list(TERMINATIONS)},
            "visibility_policy": VISIBILITY_POLICY,
            "payload": payload,
            "provenance": {"generator_id": GENERATOR_ID, "generator_version": GENERATOR_VERSION, "review_status": "generated"},
        }
        raw["content_sha256"] = case_content_sha256(raw)
        cases.append(raw)
        it = ra.IntegratorType(**payload["integrator_type"])
        eff = ra.efficient_package(w, it)
        available = max(0.0, w.client.turnkey_all_in - w.terms.floor_margin - ra.joint_cost(eff, w, it))
        entry = {k: world[k] for k in ("slug", "cell", "seed") if k in world}
        if "twin_of" in world:
            entry["twin_of"] = world["twin_of"]
        entry.update(case_id=raw["case_id"], content_sha256=raw["content_sha256"], one_sided_case_ids=world["seats"],
                     efficient_package=eff.label(), available_surplus=round(available, 3))
        index.append(entry)
    manifest = {
        "pack": pack, "family_id": FAMILY_ID, "family_version": FAMILY_VERSION,
        "generator": {"id": GENERATOR_ID, "version": GENERATOR_VERSION, **spec},
        "claim_status": "generated worlds of the one-sided pack, both seats open; no model result is a claim",
        "worlds": index,
    }
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
    cases = {w["case_id"]: json.loads((root / f"{w['case_id'].rsplit('.', 1)[-1]}.json").read_text()) for w in manifest["worlds"]}
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
