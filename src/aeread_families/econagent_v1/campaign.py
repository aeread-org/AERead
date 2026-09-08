"""Six-position GLM 5.2/Arena campaign for EconAgent."""
from __future__ import annotations
import argparse,asyncio,hashlib,json
from pathlib import Path
from typing import Any
from aeread.shared_runner.run.adapter_campaign import MODEL,PROVIDER,REVISION,ROUTE_PROVIDER,_digest,_write_once
from aeread.shared_runner.analysis.research import deserialize_evaluation_receipt
from aeread.shared_runner.run.publication import SANITIZATION_DECLARATION,assert_public_payload,atomic_publish,jsonl,receipt_projection
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import finalize_family_execution,replay_family_receipt
from aeread.shared_runner.task.execution import ArenaChatClient,execute_plan_cell
from aeread.shared_runner.task.receipts import read_evaluation_receipt
from .live import MAX_OUTPUT_TOKENS,RULE_PROVIDER,SUBJECT_SEAT,build_live_setup,load_case
CAMPAIGN_ID="econagent_glm5p2_arena_first_light_v2"
CELLS=(("econagent.pilot.tiny4x6.seed0",300),("econagent.pilot.small10x12.seed0",300),("econagent.pilot.small10x12.seed1",300),("econagent.pilot.tiny4x6.seed0",301),("econagent.pilot.small10x12.seed0",301),("econagent.pilot.small10x12.seed1",301))
MAX_CASE_COST_USD=.03; HARD_TOTAL_COST_USD=.20
def _failure(e):
 c=e;s=set()
 while c is not None and id(c) not in s:
  s.add(id(c));x=getattr(c,"condition",None)
  if isinstance(x,str) and x:return x
  c=c.__cause__ or c.__context__
 return "execution_failure"
def _name(i,c,s):return f"{i:02d}_{c}_s{s}.json"
def _cost(root):
 total=0.
 if not root.exists():return total
 for p in root.rglob("*"):
  if not p.is_file() or "artifacts/sha256" not in str(p):continue
  try:x=json.loads(p.read_text())
  except (OSError,UnicodeDecodeError,json.JSONDecodeError):continue
  if x.get("pricing_id")=="arena_2026-09-06_glm5p2_reported_cost":total+=float(x.get("cost_usd",0))
 return total
def campaign_plan()->dict[str,Any]:
 panel=[]
 for c,s in CELLS:
  x=load_case(c);panel.append({"case_id":c,"case_sha256":x.content_sha256,"seed":s})
 v={"schema_version":"aeread.adapter_live_campaign/0.1","campaign_id":CAMPAIGN_ID,"family_id":"econagent_v1","route":{"provider":PROVIDER,"model":MODEL,"revision":REVISION,"route_provider":ROUTE_PROVIDER,"substitution_for_issue_93":"glm-5.3-flash/Parasail unavailable to owner"},"panel":panel,"execution":{"sequential":True,"abort_on_operational_failure":False,"replay_every_receipt":True,"max_output_tokens":MAX_OUTPUT_TOKENS,"reasoning_effort":"none","subject_seat":SUBJECT_SEAT,"controlled_counterparts":"fixed acknowledgments","six_positions":"three authored cases at seeds 300 and 301"},"budget":{"max_case_cost_usd":MAX_CASE_COST_USD,"hard_total_cost_usd":HARD_TOTAL_COST_USD}}
 v["plan_sha256"]=_digest(v);return v
async def execute(*,run_root:Path,upstream_root:Path):
 plan=campaign_plan();_write_once(run_root/"campaign_plan.json",plan);canary=json.loads((run_root/"checkpoints"/"canary.json").read_text())
 if canary.get("status")!="admitted" or canary.get("family_id")!="econagent_v1":raise RuntimeError("EconAgent canary not admitted")
 total=float(canary.get("cost_usd",0));provider=ArenaChatClient()
 for i,(case_id,seed) in enumerate(CELLS):
  cp=run_root/"checkpoints"/_name(i,case_id,seed)
  if cp.exists():total+=float(json.loads(cp.read_text()).get("cost_usd",0));continue
  if total+MAX_CASE_COST_USD>HARD_TOTAL_COST_USD:raise RuntimeError("insufficient reserve")
  try:
   setup=build_live_setup(case_id=case_id,upstream_root=upstream_root,sampling_seed=seed,max_cost_usd=MAX_CASE_COST_USD);root=run_root/"executions"/f"{i:02d}_{case_id}_s{seed}"
   result=await execute_plan_cell(plan=setup.plan,cell_id=setup.plan.cells[0].cell_id,registry=setup.registry,evidence_root=root,prompt_sources=setup.prompt_sources,providers={PROVIDER:provider,RULE_PROVIDER:setup.rule_client},pricing=setup.pricing,harnesses=setup.harnesses)
   receipt=finalize_family_execution(setup=setup,execution=result);replayed=replay_family_receipt(setup=setup,receipt=receipt,evidence_root=root)
   if replayed.receipt_sha256!=receipt.receipt_sha256:raise RuntimeError("receipt replay mismatch")
   cost=float(result.total_cost_usd);total+=cost
   record={"schema_version":"aeread.adapter_checkpoint/0.1","campaign_id":CAMPAIGN_ID,"plan_sha256":plan["plan_sha256"],"ordinal":i,"case_id":case_id,"seed":seed,"status":"complete","receipt_path":str((result.evidence.root/"evaluation_receipt.json").relative_to(run_root)),"receipt_sha256":receipt.receipt_sha256,"receipt_replayed":True,"receipt_status":receipt.status,"inclusion_status":receipt.inclusion_status,"cost_usd":cost}
  except Exception as e:record={"schema_version":"aeread.adapter_checkpoint/0.1","campaign_id":CAMPAIGN_ID,"plan_sha256":plan["plan_sha256"],"ordinal":i,"case_id":case_id,"seed":seed,"status":"operational_failure","failure_type":type(e).__name__,"failure_condition":_failure(e)}
  record["record_sha256"]=_digest(record);_write_once(cp,record)
def publish(*,run_root:Path,publication_root:Path):
 plan=json.loads((run_root/"campaign_plan.json").read_text());rows=[];receipts=[]
 for i,(case_id,seed) in enumerate(CELLS):
  x=json.loads((run_root/"checkpoints"/_name(i,case_id,seed)).read_text());root=run_root/"executions"/f"{i:02d}_{case_id}_s{seed}"
  if x["status"]=="complete":
   sr=read_evaluation_receipt(run_root/x["receipt_path"]);r=deserialize_evaluation_receipt(sr);receipts.append(receipt_projection(sr,campaign_cell_key=f"{i:02d}:{case_id}:s{seed}"));p=next(q for q in r.scores if q.leaf.leaf_id==r.primary_leaf_id);rows.append({"case_id":case_id,"seed":seed,"status":r.status,"inclusion_status":r.inclusion_status,"primary":p.primary.value if p.primary else None,"cost_usd":x["cost_usd"],"receipt_sha256":r.receipt_sha256,"receipt_replayed":True})
  else:rows.append({"case_id":case_id,"seed":seed,"status":x["status"],"failure_type":x.get("failure_type"),"failure_condition":x.get("failure_condition"),"observed_successful_turn_cost_usd":_cost(root)})
 completed=[x for x in rows if "receipt_sha256" in x];summary={"campaign_id":CAMPAIGN_ID,"status":"complete" if len(completed)==6 else "complete_with_exclusions","plan_sha256":plan["plan_sha256"],"planned_cases":6,"completed_cases":len(completed),"failed_cases":6-len(completed),"included_cases":sum(x.get("inclusion_status")=="included" for x in rows),"completed_receipt_cost_usd":sum(float(x.get("cost_usd",0)) for x in rows),"observed_panel_cost_usd_lower_bound":sum(float(x.get("cost_usd",x.get("observed_successful_turn_cost_usd",0))) for x in rows),"cost_accounting_status":"lower_bound when terminal failed-turn costs unavailable","route":plan["route"],"sanitization":dict(SANITIZATION_DECLARATION)}
 files={"README.md":b"# EconAgent GLM 5.2 Arena first-light panel\n\nSix positions; completed receipts replayed and sanitized.\n","reports/summary.json":canonical_json_bytes(summary)+b"\n","trajectories/archive.jsonl":jsonl(rows)}
 for i,x in enumerate(receipts):files[f"receipts/{i:02d}_{x['case_id']}.json"]=canonical_json_bytes(x)+b"\n"
 arts=[{"path":n,"sha256":hashlib.sha256(p).hexdigest(),"size_bytes":len(p)} for n,p in sorted(files.items())];m={"schema_version":"aeread.publication_manifest/0.1","publication_id":CAMPAIGN_ID,"campaign_id":CAMPAIGN_ID,"plan_sha256":plan["plan_sha256"],"artifacts":arts,"sanitization":dict(SANITIZATION_DECLARATION)};m["publication_sha256"]=_digest(m);files["publication_manifest.json"]=canonical_json_bytes(m)+b"\n"
 for n,p in files.items():assert_public_payload(n,p);atomic_publish(publication_root/n,p)
def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument("--run-root",required=True,type=Path);p.add_argument("--upstream-root",type=Path);p.add_argument("--publication-root",type=Path);p.add_argument("--execute",action="store_true");p.add_argument("--publish-only",action="store_true");a=p.parse_args(argv)
 if a.execute:
  if a.upstream_root is None:p.error("--execute requires --upstream-root")
  asyncio.run(execute(run_root=a.run_root,upstream_root=a.upstream_root))
 elif a.publish_only:publish(run_root=a.run_root,publication_root=a.publication_root)
 else:print(json.dumps(campaign_plan(),indent=2,sort_keys=True))
 return 0
if __name__=="__main__":raise SystemExit(main())
