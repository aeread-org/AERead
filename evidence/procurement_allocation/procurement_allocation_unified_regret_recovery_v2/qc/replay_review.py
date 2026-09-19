import hashlib,json,math,re
from pathlib import Path
from aeread_families.procurement_allocation.continuous_campaign import _digest,_seal,economic_world_id
from aeread_families.procurement_allocation.continuous_recovery import episode_case,CONFIRMATORY_SEEDS,implementation_pins
from aeread_families.procurement_allocation.regret_decomposition import replay_action_trace
from aeread_families.procurement_allocation.runner import continuous_promotion_rule
from aeread_families.procurement_allocation.model_campaign import _write_once_json
root=Path('evidence/procurement_allocation/procurement_allocation_unified_regret_recovery_v2')
manifest=json.loads((root/'publication_manifest.json').read_text())
assert manifest['manifest_sha256']==_digest({k:v for k,v in manifest.items() if k!='manifest_sha256'})
for name,digest in manifest['artifacts'].items():
 assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
assert manifest['source_bindings']['implementation_pins']==implementation_pins()
report=json.loads((root/'reports/confirmatory.json').read_text())
rows=report['rows']
cases=[json.loads(p.read_text()) for p in Path('cases/procurement_allocation_v1/continuous_candidates_v2/opaque').glob('*.json')]
worlds={economic_world_id(c):c for c in cases}
checked=0
for row in rows:
 if row['status']!='completed':continue
 outcome=replay_action_trace(episode_case(worlds[row['world_id']],row['environment_seed'])['payload'], row['action_trace'])['outcome']
 for field in ('contribution_margin_usd','upper_bound_usd','regret_to_upper_bound_usd','completed_kits','feasible_award'):
  assert outcome[field]==row[field],field
 checked+=1
contract=json.loads((root/'tables/execution_contract.json').read_text())
assert continuous_promotion_rule(rows,world_ids=contract['world_ids'],seeds=CONFIRMATORY_SEEDS)==report['summary']
patterns=[r'sk-or-v1-[A-Za-z0-9_-]{20,}',r'sk-ant-[A-Za-z0-9_-]{20,}',r'sk-proj-[A-Za-z0-9_-]{20,}',r'"(?:user_id|authorization|raw_output|input_text|output_text|messages|prompts)"\s*:']
for path in root.rglob('*'):
 if path.is_file():
  text=path.read_text()
  assert not any(re.search(p,text,re.I) for p in patterns),path
status=json.loads((root/'reports/execution_status.json').read_text())
assert status['combined_accounted_cost_usd']<=.35
record=_seal({'campaign_id':report['campaign_id'],'artifacts_verified':len(manifest['artifacts']),'public_action_trace_outcomes_replayed':checked,'planned_rows':36,'comparison_recomputed':True,'source_pins_match':True,'credential_account_raw_payload_scan':'clean','combined_cap_respected':True,'publication_manifest_sha256':manifest['manifest_sha256'],'audit_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
_write_once_json(root/'qc/execution_audit.json',record)
print(json.dumps(record,indent=2))
