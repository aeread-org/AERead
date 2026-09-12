"""Six-cell GLM 5.2/Arena campaign for algorithmic collusion."""
from __future__ import annotations
import argparse, asyncio, hashlib, json
from pathlib import Path
from typing import Any
from aeread.shared_runner.run.adapter_campaign import _digest, _write_once
from aeread.shared_runner.analysis.research import deserialize_evaluation_receipt
from aeread.shared_runner.run.publication import SANITIZATION_DECLARATION, assert_public_payload, atomic_publish, jsonl, receipt_projection
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import finalize_family_execution, replay_family_receipt
from aeread.shared_runner.task.execution import ArenaChatClient, execute_plan_cell
from aeread.shared_runner.task.receipts import read_evaluation_receipt
from .live import CANARY_SPEC, MAX_OUTPUT_TOKENS, MODEL, PROVIDER, REVISION, ROUTE_PROVIDER, RULE_PROVIDER, SUBJECT_SEAT, build_live_setup, load_case

CAMPAIGN_ID = "collusion_glm5p2_arena_first_light_v1"
CASE_IDS = (
 "collusion.duopoly.baseline-symmetric.alpha1.seed0",
 "collusion.duopoly.baseline-symmetric.alpha3p2.seed0",
 "collusion.duopoly.baseline-symmetric.alpha10.seed0",
 "collusion.duopoly.asymmetric-quality.alpha1.seed0",
 "collusion.duopoly.asymmetric-quality.alpha3p2.seed0",
 "collusion.duopoly.asymmetric-quality.alpha10.seed0",
)
SEED=300; MAX_CASE_COST_USD=0.03; HARD_TOTAL_COST_USD=0.20

def _observed_provider_cost(root:Path)->float:
    total=0.0
    if not root.exists(): return total
    for path in root.rglob("*"):
        if not path.is_file() or "artifacts/sha256" not in str(path): continue
        try: payload=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,UnicodeDecodeError,json.JSONDecodeError): continue
        if payload.get("pricing_id")=="arena_2026-09-06_glm5p2_reported_cost": total+=float(payload.get("cost_usd",0))
    return total

def _failure_condition(error: BaseException) -> str:
    current: BaseException|None=error; seen=set()
    while current is not None and id(current) not in seen:
        seen.add(id(current)); condition=getattr(current,"condition",None)
        if isinstance(condition,str) and condition: return condition
        current=current.__cause__ or current.__context__
    return "execution_failure"

def campaign_plan() -> dict[str,Any]:
    cases=[load_case(x) for x in CASE_IDS]
    value={"schema_version":"aeread.adapter_live_campaign/0.1","campaign_id":CAMPAIGN_ID,
      "family_id":"collusion","route":{"provider":PROVIDER,"model":MODEL,"revision":REVISION,
      "route_provider":ROUTE_PROVIDER,"canary_spec_sha256":CANARY_SPEC.spec_sha256,"substitution_for_issue_93":"glm-5.3-flash/Parasail unavailable to owner"},
      "panel":[{"case_id":x.case_id,"case_sha256":x.content_sha256,"seed":SEED} for x in cases],
      "execution":{"sequential":True,"abort_on_operational_failure":False,"replay_every_receipt":True,
      "max_output_tokens":MAX_OUTPUT_TOKENS,"reasoning_effort":"none","subject_seat":SUBJECT_SEAT,
      "controlled_counterpart":"firm_b fixed at case Nash price"},
      "budget":{"max_case_cost_usd":MAX_CASE_COST_USD,"hard_total_cost_usd":HARD_TOTAL_COST_USD}}
    value["plan_sha256"]=_digest(value); return value

async def execute(*,run_root:Path)->None:
    plan=campaign_plan(); _write_once(run_root/"campaign_plan.json",plan)
    canary=json.loads((run_root/"checkpoints"/"canary.json").read_text())
    if (canary.get("status")!="admitted" or canary.get("family_id")!="collusion"
        or canary.get("plan_sha256") != plan["plan_sha256"]
        or canary.get("spec_sha256") != CANARY_SPEC.spec_sha256): raise RuntimeError("collusion canary not admitted")
    total=float(canary.get("cost_usd",0)); provider=ArenaChatClient()
    for ordinal,case_id in enumerate(CASE_IDS):
        checkpoint=run_root/"checkpoints"/f"{ordinal:02d}_{case_id}.json"
        if checkpoint.exists(): total+=float(json.loads(checkpoint.read_text()).get("cost_usd",0)); continue
        if total+MAX_CASE_COST_USD>HARD_TOTAL_COST_USD: raise RuntimeError("insufficient campaign reserve")
        try:
            setup=build_live_setup(case_id=case_id,sampling_seed=SEED,max_cost_usd=MAX_CASE_COST_USD)
            root=run_root/"executions"/case_id
            result=await execute_plan_cell(plan=setup.plan,cell_id=setup.plan.cells[0].cell_id,
              registry=setup.registry,evidence_root=root,prompt_sources=setup.prompt_sources,
              providers={PROVIDER:provider,RULE_PROVIDER:setup.rule_client},pricing=setup.pricing)
            receipt=finalize_family_execution(setup=setup,execution=result)
            replayed=replay_family_receipt(setup=setup,receipt=receipt,evidence_root=root)
            if replayed.receipt_sha256!=receipt.receipt_sha256: raise RuntimeError("receipt replay mismatch")
            cost=float(result.total_cost_usd); total+=cost
            if total>HARD_TOTAL_COST_USD: raise RuntimeError("campaign exceeded cost ceiling")
            record={"schema_version":"aeread.adapter_checkpoint/0.1","campaign_id":CAMPAIGN_ID,
             "plan_sha256":plan["plan_sha256"],"ordinal":ordinal,"case_id":case_id,"status":"complete",
             "receipt_path":str((result.evidence.root/"evaluation_receipt.json").relative_to(run_root)),
             "receipt_sha256":receipt.receipt_sha256,"receipt_replayed":True,"receipt_status":receipt.status,
             "inclusion_status":receipt.inclusion_status,"cost_usd":cost}
        except Exception as error:
            record={"schema_version":"aeread.adapter_checkpoint/0.1","campaign_id":CAMPAIGN_ID,
             "plan_sha256":plan["plan_sha256"],"ordinal":ordinal,"case_id":case_id,
             "status":"operational_failure","failure_type":type(error).__name__,
             "failure_condition":_failure_condition(error)}
        record["record_sha256"]=_digest(record); _write_once(checkpoint,record)

def publish(*,run_root:Path,publication_root:Path)->None:
    plan=json.loads((run_root/"campaign_plan.json").read_text()); rows=[]; receipts=[]
    for ordinal,case_id in enumerate(CASE_IDS):
        checkpoint=json.loads((run_root/"checkpoints"/f"{ordinal:02d}_{case_id}.json").read_text())
        if checkpoint["status"]=="complete":
            serialized=read_evaluation_receipt(run_root/checkpoint["receipt_path"]); receipt=deserialize_evaluation_receipt(serialized)
            receipts.append(receipt_projection(serialized,campaign_cell_key=f"{ordinal:02d}:{case_id}"))
            primary=next(x for x in receipt.scores if x.leaf.leaf_id==receipt.primary_leaf_id)
            rows.append({"case_id":case_id,"status":receipt.status,"inclusion_status":receipt.inclusion_status,
             "primary":primary.primary.value if primary.primary else None,"cost_usd":checkpoint["cost_usd"],
             "receipt_sha256":receipt.receipt_sha256,"receipt_replayed":True})
        else: rows.append({"case_id":case_id,"status":checkpoint["status"],"failure_type":checkpoint.get("failure_type"),"failure_condition":checkpoint.get("failure_condition"),"observed_successful_turn_cost_usd":_observed_provider_cost(run_root/"executions"/case_id)})
    completed=[x for x in rows if "receipt_sha256" in x]
    summary={"campaign_id":CAMPAIGN_ID,"status":"complete" if len(completed)==6 else "complete_with_exclusions",
     "plan_sha256":plan["plan_sha256"],"planned_cases":6,"completed_cases":len(completed),
     "failed_cases":6-len(completed),"included_cases":sum(x.get("inclusion_status")=="included" for x in rows),
     "completed_receipt_cost_usd":sum(float(x.get("cost_usd",0)) for x in rows),
     "observed_panel_cost_usd_lower_bound":sum(float(x.get("cost_usd",x.get("observed_successful_turn_cost_usd",0))) for x in rows),
     "cost_accounting_status":"lower_bound; terminal failed-turn costs unavailable","route":plan["route"],
     "sanitization":dict(SANITIZATION_DECLARATION)}
    files={"README.md":b"# Collusion GLM 5.2 Arena first-light panel\n\nSix duopoly cells with a frozen Nash counterpart; completed receipts replayed and sanitized.\n",
     "reports/summary.json":canonical_json_bytes(summary)+b"\n","trajectories/archive.jsonl":jsonl(rows)}
    for i,row in enumerate(receipts): files[f"receipts/{i:02d}_{row['case_id']}.json"]=canonical_json_bytes(row)+b"\n"
    artifacts=[{"path":n,"sha256":hashlib.sha256(p).hexdigest(),"size_bytes":len(p)} for n,p in sorted(files.items())]
    manifest={"schema_version":"aeread.publication_manifest/0.1","publication_id":CAMPAIGN_ID,
     "campaign_id":CAMPAIGN_ID,"plan_sha256":plan["plan_sha256"],"artifacts":artifacts,"sanitization":dict(SANITIZATION_DECLARATION)}
    manifest["publication_sha256"]=_digest(manifest); files["publication_manifest.json"]=canonical_json_bytes(manifest)+b"\n"
    for name,payload in files.items(): assert_public_payload(name,payload); atomic_publish(publication_root/name,payload)

def main(argv=None)->int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--run-root",required=True,type=Path); p.add_argument("--publication-root",type=Path); p.add_argument("--execute",action="store_true"); p.add_argument("--publish-only",action="store_true"); a=p.parse_args(argv)
    if a.execute: asyncio.run(execute(run_root=a.run_root))
    elif a.publish_only:
        if a.publication_root is None: p.error("--publish-only requires --publication-root")
        publish(run_root=a.run_root,publication_root=a.publication_root)
    else: print(json.dumps(campaign_plan(),indent=2,sort_keys=True))
    return 0
if __name__=="__main__": raise SystemExit(main())
