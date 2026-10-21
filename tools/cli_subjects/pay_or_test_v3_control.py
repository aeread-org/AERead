"""Pay or test version 3: a frozen control model that tests, for Gate 1's measured-headroom ground.

Declared in ``docs/families/procurement-allocation/pay_or_test_v3_control_plan.md``. Everything is
``pay_or_test_v3_openrouter``'s, imported unchanged (its bytes and the plans of the flash runs stay as they are), except
what the plan names: two candidates (GPT-6 Luna and Gemini 3.8 Flash at reasoning effort ``high`` on the flash run's
pinned routes), the pack and request seeds of each phase, the ceilings, the identities and the plan's scope.

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/pay_or_test_v3_control.py --phase probe --subject gpt6_luna_high
    ... --phase probe --subject gpt6_luna_high --route-check --env-file <AERead>/.env     # one strict call
    ... --phase probe --subject gpt6_luna_high --execute --env-file <AERead>/.env
    ... --phase control --subject <the selected candidate> --execute --env-file <AERead>/.env
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

import pay_or_test_openrouter as v1
import pay_or_test_v3_openrouter as flash
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.procurement_allocation import pay_or_test_v3_case_matrix as v3

PLAN = "docs/families/procurement-allocation/pay_or_test_v3_control_plan.md"
WRAPPER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
#: The candidates in the plan's order, each a flash route with only its profile id and reasoning effort changed.
CANDIDATES = {"gpt6_luna_high": "gpt6_luna", "gemini38_flash_high": "gemini38_flash"}
PHASES = {
    "probe": {"pack": v3.PILOT_PACK_ID, "seeds": [87101], "ceiling_usd": 1.50, "claim_status": "development_diagnostic",
              "scope": "Phase A of the control plan: choosing a frozen control that tests, on the 12 development worlds"},
    "control": {"pack": v3.CONFIRM_PACK_ID, "seeds": [87201, 87202, 87203], "ceiling_usd": 4.00,
                "claim_status": "declared_diagnostic",
                "scope": "Phase B of the control plan: the frozen control at three seeds on the 20 declared worlds, read "
                         "for degenerate and trivial worlds (Gate 1, measured headroom); no claim about any model"},
}

for name, base in CANDIDATES.items():
    spec = {**v1.SUBJECTS[base], "route": dataclasses.replace(
        v1.SUBJECTS[base]["route"], profile_id=f"procurement_pay_or_test_v3_control_{name}_v1", reasoning_effort="high")}
    v1.SUBJECTS[name] = spec  # ``v1._route_block`` and the catalog check read the subject here
    flash.SUBJECTS[name] = spec

_flash_model_plan = flash.model_plan
_phase: dict[str, Any] = {}


def configure(phase: str) -> None:
    """Point the imported driver at one phase's pack, seeds and ceilings."""
    settings = PHASES[phase]
    _phase.clear()
    _phase.update(settings, name=phase)
    flash.PACK = settings["pack"]
    flash.CONTROLS["inference_seeds"] = list(settings["seeds"])
    for name in CANDIDATES:
        flash.CONTROLS["total_cost_ceiling_usd"][name] = settings["ceiling_usd"]


def campaign_id(subject: str) -> str:
    return f"procurement_allocation_{flash.PACK}_v3_control_{subject}_v1"


def model_plan(subject: str) -> dict[str, Any]:
    """The flash driver's plan for this phase, with this plan's identity, status and scope."""
    if subject not in CANDIDATES:
        raise KeyError(f"{subject!r} is not a candidate of the control plan")
    plan = dict(_flash_model_plan(subject))
    plan.pop("plan_sha256")
    plan.update(campaign_plan=PLAN, claim_status=_phase["claim_status"], claim_scope=_phase["scope"], phase=_phase["name"],
                driver={**plan["driver"], "wrapper": {"path": "tools/cli_subjects/pay_or_test_v3_control.py",
                                                      "sha256": WRAPPER_SHA256}})
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return plan


flash.campaign_id = campaign_id
flash.model_plan = model_plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--phase", choices=sorted(PHASES), required=True)
    parser.add_argument("--subject", choices=sorted(CANDIDATES), required=True)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--route-check", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    configure(args.phase)
    if not (args.route_check or args.execute):
        plan = model_plan(args.subject)
        print(json.dumps({k: plan[k] for k in ("campaign_id", "planned_trajectory_count", "claim_status", "plan_sha256")}))
        return 0
    v1.load_api_key(args.env_file)
    if args.route_check:
        print(json.dumps(asyncio.run(flash.probe(args.subject)), indent=1))
        return 0
    run_root = args.run_root or flash.RUNS_ROOT / campaign_id(args.subject).removeprefix("procurement_allocation_")
    artifact = asyncio.run(flash.run(args.subject, run_root, resume=args.resume))
    print(json.dumps({"halted": artifact["halted"], "completed": sum(r["status"] == "completed" for r in artifact["rows"]),
                      "planned": artifact["plan"]["planned_trajectory_count"],
                      "cost_usd": round(sum(flash._spent(r) for r in artifact["rows"]), 4)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
