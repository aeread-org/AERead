"""Schema-aligned V3 campaign for counteroffer-adoption depth."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.receipts import verify_evaluation_receipt

from .adoption_campaign import _group_summary
from .adoption_campaign_v2 import _cells
from .adoption_environment import STAGE_SEQUENCES
from .adoption_runner_v3 import build_adoption_setup_v3, finalize_adoption_execution_v3, finalize_adoption_failure_v3, load_adoption_case_v3, replay_adoption_receipt_v3, run_adoption_offline_v3, run_adoption_openrouter_v3
from .objective_campaign import _atomic_write, _call_usage, _plain, _read_sealed, _route, _score_projection, _sealed, _sha256
from .objective_openrouter import CLIENT_IMPLEMENTATION_ID, ParameterCompatibleOpenRouterClient
from .objective_runner import OBJECTIVE_CASE_PATH
from .stack_runner import load_stack_case


CAMPAIGN_ID = "datacenter_counteroffer_adoption_v3"
CONDITION = "schema_aligned_starter_grounded_forced_counteroffer_adoption"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT_PATH = REPOSITORY_ROOT / "configs" / f"{CAMPAIGN_ID}.json"
DEFAULT_RUN_ROOT = REPOSITORY_ROOT / "runs" / CAMPAIGN_ID


def load_contract(path: Path | str = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(contract, dict): raise ValueError("V3 contract must be an object")
    frozen = {"schema_version": "aeread.datacenter_counteroffer_adoption_campaign_contract/0.3", "campaign_id": CAMPAIGN_ID, "family_id": "datacenter_counteroffer_adoption_v1", "family_version": "1.2.0", "condition": CONDITION, "claim_status": "single_curated_project_schema_aligned_nested_depth_diagnostic_only"}
    if any(contract.get(key) != value for key, value in frozen.items()): raise ValueError("V3 identity or claim boundary differs")
    if set(contract["stages"]) != set(STAGE_SEQUENCES): raise ValueError("V3 stages differ")
    for stage_id, sequence in STAGE_SEQUENCES.items():
        stage = contract["stages"][stage_id]
        if set(stage) != {"case_id", "expected_case_sha256", "required_sequence"} or tuple(stage["required_sequence"]) != sequence: raise ValueError(f"{stage_id}: V3 stage differs")
    seeds = contract["inference_seeds"]
    if not isinstance(seeds, list) or len(seeds) != 3 or len(set(seeds)) != 3 or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seeds): raise ValueError("V3 seeds differ")
    expected = {"mistral32_deepinfra": ("mistralai/mistral-small-3.2-24b-instruct", "mistralai/mistral-small-3.2-24b-instruct-2506", "DeepInfra"), "qwen3_235b_novita": ("qwen/qwen3-235b-a22b-2507", "qwen/qwen3-235b-a22b-07-25", "Novita")}
    if set(contract["models"]) != set(expected): raise ValueError("V3 model panel differs")
    for model_id, route in expected.items():
        model = contract["models"][model_id]
        if (model["requested_model"], model["canonical_model"], model["provider"]) != route or model["access_class"] != "open_source" or model["license_id"] != "Apache-2.0" or model["reasoning_effort"] is not None: raise ValueError(f"{model_id}: V3 route differs")
    controls = contract["execution"]
    required_controls = {"harness": "minimal_chat/1.0", "adapter": CLIENT_IMPLEMENTATION_ID, "max_concurrent_cells_per_route_provider": 1, "max_action_attempts": 1, "sdk_retries": 0, "response_cache": False, "provider_fallbacks": False}
    if any(controls.get(key) != value for key, value in required_controls.items()): raise ValueError("V3 execution controls differ")
    if 3 * len(seeds) * len(expected) * float(controls["max_cost_usd_per_live_profile"]) > float(controls["campaign_max_cost_usd"]): raise ValueError("V3 cost ceiling exceeded")
    analysis = contract["analysis"]
    if analysis.get("independent_cluster_count") != 1 or analysis.get("stage_variants_independent") is not False or analysis.get("nested_stage_order") != list(STAGE_SEQUENCES) or analysis.get("missingness") != "report_separately" or analysis.get("primary_estimand") != "counteroffer_adoption_rate": raise ValueError("V3 analysis differs")
    for field in ("winner_claim_allowed", "inferential_model_ranking_allowed", "causal_depth_effect_allowed"):
        if analysis.get(field) is not False: raise ValueError(f"analysis.{field} must be false")
    return contract


def _setup(contract, cell):
    controls = contract["execution"]
    return build_adoption_setup_v3(str(cell["stage_id"]), route=_route(contract["models"][cell["model_id"]]), seed=int(cell["inference_seed"]), max_output_tokens=int(controls["max_output_tokens_per_action"]), timeout_seconds=float(controls["timeout_seconds_per_action"]), max_cost_usd=float(controls["max_cost_usd_per_live_profile"]))


def _implementation_hashes():
    names = ("contracts.py", "stack_environment.py", "stack_runner.py", "objective_environment.py", "objective_openrouter.py", "adoption_environment.py", "adoption_measurement.py", "adoption_runner.py", "adoption_campaign.py", "adoption_environment_v2.py", "adoption_runner_v2.py", "adoption_environment_v3.py", "adoption_runner_v3.py", "adoption_campaign_v3.py")
    root = Path(__file__).parent
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}


def build_design(contract):
    base = load_stack_case("v2", OBJECTIVE_CASE_PATH)
    if base.case_id != contract["base_case"]["case_id"] or base.content_sha256 != contract["base_case"]["expected_case_sha256"]: raise ValueError("V3 base case differs")
    for stage_id, spec in contract["stages"].items():
        case = load_adoption_case_v3(stage_id)
        if case.case_id != spec["case_id"] or case.content_sha256 != spec["expected_case_sha256"]: raise ValueError(f"{stage_id}: V3 case differs")
    cells = []
    per_cell = float(contract["execution"]["max_cost_usd_per_live_profile"])
    for cell in _cells(contract):
        setup = _setup(contract, cell); plan_cell = setup.plan.cells[0]
        if sum(profile.model.provider == "openrouter" for profile in setup.plan.agent_profiles) != 1: raise ValueError("V3 live profile count differs")
        cells.append({**cell, "run_plan_id": setup.plan.run_plan_id, "run_plan_sha256": setup.plan.plan_sha256, "cell_id": plan_cell.cell_id, "case_id": plan_cell.case_id, "case_sha256": plan_cell.case_sha256, "evaluation_block_kind": "controlled", "live_profile_count": 1, "declared_cell_max_cost_usd": per_cell})
    maximum = sum(cell["declared_cell_max_cost_usd"] for cell in cells)
    hashes = _implementation_hashes()
    return _sealed({"schema_version": "aeread.datacenter_counteroffer_adoption_design/0.3", "campaign_id": CAMPAIGN_ID, "contract_sha256": _sha256(contract), "campaign_driver_sha256": hashes["adoption_campaign_v3.py"], "adapter_implementation_id": CLIENT_IMPLEMENTATION_ID, "implementation_source_sha256s": hashes, "base_case_id": base.case_id, "base_case_sha256": base.content_sha256, "independent_cluster_count": 1, "nested_stage_count": 3, "nested_stage_variants_independent": False, "planned_cells": len(cells), "paired_seed_count": 3, "worst_case_declared_cost_usd": maximum, "campaign_max_cost_usd": contract["execution"]["campaign_max_cost_usd"], "predecessor_campaign_id": "datacenter_counteroffer_adoption_v2", "instrument_change": "nullable_nonbinding_offer_prose_normalized", "cells": cells})


async def run_provider_free_gate(contract, *, run_root):
    path = run_root / "provider_free_validation" / "summary.json"
    if path.exists(): return _read_sealed(path)
    rows=[]
    for stage_id in contract["analysis"]["nested_stage_order"]:
        evidence=run_root/"provider_free_validation"/stage_id/"evidence"; setup,execution=await run_adoption_offline_v3(stage_id,evidence_root=evidence); receipt=finalize_adoption_execution_v3(setup=setup,execution=execution); verify_evaluation_receipt(receipt); replayed=replay_adoption_receipt_v3(setup=setup,receipt=receipt,evidence_root=evidence); score=next(item for item in receipt.scores if item.leaf.leaf_id=="counteroffer_adoption_rate"); outcome=execution.episode_result.outcome; passed=score.primary.value==1 and outcome["exact_package_integrity"] and replayed==receipt; rows.append({"stage_id":stage_id,"status":"passed" if passed else "failed","case_sha256":setup.case.content_sha256,"logical_action_count":execution.episode_result.logical_action_count,"primary_score":score.primary.value,"receipt_sha256":receipt.receipt_sha256,"replay_verified":replayed==receipt})
    result=_sealed({"schema_version":"aeread.datacenter_counteroffer_adoption_provider_free_gate/0.3","campaign_id":CAMPAIGN_ID,"contract_sha256":_sha256(contract),"status":"passed" if all(row["status"]=="passed" for row in rows) else "failed","stages":rows}); _atomic_write(path,result); return result


def run_profile_admission_gate(contract, *, design, run_root):
    path=run_root/"profile_admission"/"summary.json"
    if path.exists(): return _read_sealed(path)
    expected={cell["cell_key"]:cell for cell in design["cells"]}; admitted=[]
    for cell in _cells(contract):
        setup=_setup(contract,cell); target=expected[cell["cell_key"]]
        if setup.plan.plan_sha256!=target["run_plan_sha256"] or setup.plan.cells[0].cell_id!=target["cell_id"] or not all(item.admitted for item in setup.plan.profile_admissions): raise ValueError("V3 profile admission drift")
        admitted.append(cell["cell_key"])
    result=_sealed({"schema_version":"aeread.datacenter_counteroffer_adoption_profile_gate/0.3","campaign_id":CAMPAIGN_ID,"contract_sha256":_sha256(contract),"status":"passed","admitted_cells":admitted}); _atomic_write(path,result); return result


async def _run_live_cell(contract,cell,*,run_root,provider):
    root=run_root/"live"/str(cell["cell_key"]); path=root/"result.json"
    if path.exists(): return _read_sealed(path)
    if root.exists(): raise ValueError(f"refusing to replace incomplete V3 cell {cell['cell_key']}")
    setup=_setup(contract,cell); controls=contract["execution"]; started=time.perf_counter()
    try:
        _,execution=await run_adoption_openrouter_v3(str(cell["stage_id"]),_route(contract["models"][cell["model_id"]]),evidence_root=root/"evidence",seed=int(cell["inference_seed"]),max_output_tokens=int(controls["max_output_tokens_per_action"]),timeout_seconds=float(controls["timeout_seconds_per_action"]),max_cost_usd=float(controls["max_cost_usd_per_live_profile"]),provider=provider); receipt=finalize_adoption_execution_v3(setup=setup,execution=execution); verify_evaluation_receipt(receipt); replayed=replay_adoption_receipt_v3(setup=setup,receipt=receipt,evidence_root=root/"evidence"); result=_sealed({"schema_version":"aeread.datacenter_counteroffer_adoption_live_cell/0.3","campaign_id":CAMPAIGN_ID,**dict(cell),"status":"completed","receipt_status":receipt.status,"inclusion_status":receipt.inclusion_status,"receipt_sha256":receipt.receipt_sha256,"replay_verified":replayed==receipt,"elapsed_seconds":time.perf_counter()-started,"usage":_call_usage(execution),"outcome":_plain(execution.episode_result.outcome),"scores":_score_projection(receipt),"failure":None})
    except Exception as error:
        receipt=finalize_adoption_failure_v3(setup=setup,cell_id=setup.plan.cells[0].cell_id,evidence_root=root/"evidence",error=error); result=_sealed({"schema_version":"aeread.datacenter_counteroffer_adoption_live_cell/0.3","campaign_id":CAMPAIGN_ID,**dict(cell),"status":"operational_failure","receipt_status":receipt.status,"inclusion_status":receipt.inclusion_status,"receipt_sha256":receipt.receipt_sha256,"replay_verified":False,"elapsed_seconds":time.perf_counter()-started,"usage":None,"outcome":None,"scores":None,"failure":{"failure_class":receipt.failure.failure_class,"failure_condition":receipt.failure.condition,"error_type":type(error).__name__}})
    _atomic_write(path,result); return result


def summarize(contract,design,rows):
    completed=[row for row in rows if row["status"]=="completed"]; operational=[row for row in rows if row["status"]!="completed"]; cost=sum(float(row["usage"]["reported_cost_usd"]) for row in completed if row["usage"] is not None)
    return _sealed({"schema_version":"aeread.datacenter_counteroffer_adoption_summary/0.3","campaign_id":CAMPAIGN_ID,"contract_sha256":_sha256(contract),"design_sha256":design["artifact_sha256"],"campaign_driver_sha256":design["campaign_driver_sha256"],"implementation_source_sha256s":design["implementation_source_sha256s"],"claim_status":contract["claim_status"],"predecessor_campaign_id":design["predecessor_campaign_id"],"instrument_change":design["instrument_change"],"independent_cluster_count":1,"nested_stage_variants_independent":False,"planned_cells":len(rows),"completed_cells":len(completed),"included_cells":sum(row["inclusion_status"]=="included" for row in completed),"operational_failure_cells":len(operational),"failure_fraction":len(operational)/len(rows),"failure_conditions":[row["failure"]["failure_condition"] for row in operational],"reported_cost_usd":cost,"provider_cost_complete":not operational,"cost_qualifier":"exact" if not operational else "lower_bound","campaign_max_cost_usd":contract["execution"]["campaign_max_cost_usd"],"within_declared_campaign_cost_ceiling":cost<=float(contract["execution"]["campaign_max_cost_usd"]),"model_summaries":[_group_summary(key="model_id",value=model_id,rows=rows) for model_id in sorted(contract["models"])],"stage_summaries":[_group_summary(key="stage_id",value=stage_id,rows=rows) for stage_id in contract["analysis"]["nested_stage_order"]],"winner_claim_allowed":False,"inferential_model_ranking_allowed":False,"causal_depth_effect_allowed":False})


async def run_campaign(*,contract_path=DEFAULT_CONTRACT_PATH,run_root=DEFAULT_RUN_ROOT,stop_after="live",provider_factory:Callable[[],Any]=ParameterCompatibleOpenRouterClient):
    contract=load_contract(contract_path); root=Path(run_root); design=build_design(contract); _atomic_write(root/"design.json",design)
    if stop_after=="design": return design
    gate=await run_provider_free_gate(contract,run_root=root)
    if gate["status"]!="passed": raise ValueError("V3 provider-free gate failed")
    if stop_after=="provider_free": return gate
    admission=run_profile_admission_gate(contract,design=design,run_root=root)
    if stop_after=="profile_admission": return admission
    semaphore=asyncio.Semaphore(int(contract["execution"]["concurrency"])); locks={str(model["provider"]):asyncio.Semaphore(1) for model in contract["models"].values()}
    async def execute(cell):
        provider_name=str(contract["models"][cell["model_id"]]["provider"])
        async with semaphore,locks[provider_name]: return await _run_live_cell(contract,cell,run_root=root,provider=provider_factory())
    rows=await asyncio.gather(*(execute(cell) for cell in design["cells"])); summary=summarize(contract,design,rows); _atomic_write(root/"live"/"summary.json",summary); return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--contract",type=Path,default=DEFAULT_CONTRACT_PATH); parser.add_argument("--run-root",type=Path,default=DEFAULT_RUN_ROOT); parser.add_argument("--stop-after",choices=("design","provider_free","profile_admission","live"),default="live"); args=parser.parse_args(argv); print(canonical_json_bytes(asyncio.run(run_campaign(contract_path=args.contract,run_root=args.run_root,stop_after=args.stop_after))).decode("utf-8")); return 0


if __name__=="__main__": raise SystemExit(main())


__all__=["CAMPAIGN_ID","DEFAULT_CONTRACT_PATH","DEFAULT_RUN_ROOT","build_design","load_contract","run_campaign","summarize"]
