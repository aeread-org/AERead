"""Write the agreement cases: the worlds of the full-terms eval pack, both seats open.

    python -m aeread_families.datacenter_development.agreement_pack agreement_dev_v1 --write

The worlds, hidden types and seeds are the full-terms pack's, so the economics are
the ones already tested. That pack was admitted for a different question (a client
choosing on a list), so this is a development pack, not the admitted pack the
design calls for. Case ids are neutral codes; ``pack.json`` maps them back.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from . import agreement as ag
from . import risk_allocation_contracts as rc
from .agreement_environment import FAMILY_ID, FAMILY_VERSION, TERMINATIONS, VISIBILITY_POLICY, AgreementPlugin

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASES_ROOT = REPOSITORY_ROOT / "cases" / FAMILY_ID
SOURCE_ROOT = REPOSITORY_ROOT / "cases" / "datacenter_risk_allocation_contracts_v1"
GENERATOR_ID = "datacenter_agreement_generator_v1"
GENERATOR_VERSION = "0.1.0"
PACKS: dict[str, dict[str, Any]] = {
    "agreement_dev_v1": {"split": "dev", "source_pack": "contracts_eval_v1"},
    # the same worlds, the client's brief stating what walking away costs it
    "agreement_dev_walkaway_v1": {"split": "dev", "source_pack": "contracts_eval_v1", "brief_version": "walkaway_stated_v1"},
}


def build(pack: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    spec = PACKS[pack]
    plugin = AgreementPlugin()
    cases, index = [], []
    for path in sorted(p for p in (SOURCE_ROOT / spec["source_pack"]).glob("*.json") if p.name != "pack.json"):
        one = json.loads(path.read_text())
        payload = {k: one["payload"][k] for k in ("world", "integrator_type", "extras")}
        if spec.get("brief_version"):
            payload["brief_version"] = spec["brief_version"]
        plugin.validate_payload(payload)
        cw, it = rc.world_from({k: payload[k] for k in ("world", "integrator_type", "extras")})
        code = hashlib.sha256(f"{pack}:{one['case_id']}".encode()).hexdigest()[:8]
        raw = {
            "spec_version": CaseManifest.SPEC_VERSION, "case_id": f"{FAMILY_ID}.{spec['split']}.{code}", "family_id": FAMILY_ID,
            "family_version": FAMILY_VERSION, "split": spec["split"], "world_seed": one["world_seed"],
            "seats": [{"id": s, "role": s} for s in ag.SEATS],
            "episode": {"max_logical_actions": ag.MOVES, "termination": list(TERMINATIONS)},
            "visibility_policy": VISIBILITY_POLICY, "payload": payload,
            "provenance": {"generator_id": GENERATOR_ID, "generator_version": GENERATOR_VERSION, "review_status": "generated"},
        }
        raw["content_sha256"] = case_content_sha256(raw)
        cases.append(raw)
        best = ag.best_agreement(cw, it)
        d = ag.draft(cw)
        available = max(0.0, cw.best_outside[1] - cw.w.terms.floor_margin - ag.joint_cost(cw, it, best))
        index.append({
            "case_id": raw["case_id"], "content_sha256": raw["content_sha256"], "source_case_id": one["case_id"], "world_seed": one["world_seed"],
            "playbook": cw.playbook, **({"outside_option": cw.best_outside[0]} if spec.get("brief_version") else {}), "draft": d.label(), "best_agreement": best.label(),
            "clauses_to_change": sorted(k for k in ag.TERMS if getattr(best, k) != getattr(d, k)),
            "available_surplus": round(available, 3),
            "left_on_the_table_by_the_draft": round(ag.joint_cost(cw, it, d) - ag.joint_cost(cw, it, best), 3),
            "draft_beats_no_deal": bool(cw.best_outside[1] - cw.w.terms.floor_margin - ag.joint_cost(cw, it, d) > 0),
        })
    manifest = {
        "pack": pack, "family_id": FAMILY_ID, "family_version": FAMILY_VERSION,
        "generator": {"id": GENERATOR_ID, "version": GENERATOR_VERSION, **spec},
        "claim_status": "development worlds borrowed from the full-terms pack, both seats open; no model result is a claim",
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
