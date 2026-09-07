"""Shared-runner setup for live EconAgent acknowledgment episodes."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from aeread.shared_runner.adapter_campaign import BASE_URL,MODEL,PROVIDER,REVISION
from aeread.shared_runner.model_call.harness import CanonicalMessage,FailureCondition,HarnessOutput,default_harnesses
from aeread.shared_runner.registry import HarnessRegistry,HarnessRequirements,PluginRegistry,ProviderCapabilities
from aeread.shared_runner.run.resolver import ImplementationPin,canonical_json_bytes,resolve_run_plan
from aeread.shared_runner.schemas import AgentProfile,AnalysisPlan,CaseManifest,EvaluationBlock,RunSpec,SamplingPlan,SuiteManifest
from aeread.shared_runner.task.execution import ProviderFailure,ProviderResult,TokenPricing
from .environment import EconAgentV1Plugin,family_manifest,register_plugin

ROOT=Path(__file__).resolve().parents[3]; SUBJECT_SEAT="agent_0"
PROMPT_ID="econagent_glm5p2_arena_prompt_v1"
PROMPT='Return only the JSON object {"acknowledge":true} to advance this EconAgent month.'
RULE_PROVIDER="econagent_ack_rule"; RULE_MODEL="ack_rule"; RULE_PROFILE_ID="econagent_ack_rule_v1"; RULE_PROMPT_ID="econagent_ack_rule_prompt_v1"; RULE_PROMPT=PROMPT
PRICING=TokenPricing(0,0,0,"arena_2026-09-06_glm5p2_reported_cost"); RULE_PRICING=TokenPricing(0,0,0,"econagent_ack_rule_zero_cost_v1"); MAX_OUTPUT_TOKENS=512

class AckRuleClient:
 async def complete(self,request:Any)->ProviderResult:
  return ProviderResult(response_id=f"local_{request.provider_call_id}",requested_model=RULE_MODEL,resolved_model=RULE_MODEL,output_text='{"acknowledge":true}',finish_reason="stop",input_tokens=0,cached_input_tokens=0,output_tokens=0,cost_usd=0,raw_response={"local_ack_rule":True})

class EconAckHarness:
 id="econagent_ack";version="1.0"
 requires=HarnessRequirements(provider=frozenset(),tools="none",memory=frozenset({"disabled"}),owns_retries=False,owns_tools=False,replayable=True,blocking=False,spawns_subagents=False)
 async def open_episode(self,episode):return None
 async def close_episode(self,episode):return None
 def state_reader(self):return None
 def classify_failure(self,e):return FailureCondition(e.condition,e.retryable) if isinstance(e,ProviderFailure) else FailureCondition("harness_error",False)
 async def act(self,request,ctx):
  turn=await ctx.model.complete(messages=(CanonicalMessage(role="user",content=canonical_json_bytes(request.observation).decode()),),response_mode="text")
  payload=json.loads(turn.text)
  if payload!={"acknowledge":True}:raise ValueError("EconAgent acknowledgment must be true")
  return HarnessOutput(action=payload,claimed_tool_calls=(),rounds_used=1,notes={})

def schema(): return {"type":"object","properties":{"acknowledge":{"type":"boolean","const":True}},"required":["acknowledge"],"additionalProperties":False}
def load_case(case_id:str)->CaseManifest: return CaseManifest.from_dict(json.loads((ROOT/"cases"/"econagent_v1"/f"{case_id}.json").read_text()))
def _pin(i,k,v,d): return ImplementationPin.from_dict({"component_id":i,"kind":k,"version":v,"sha256":d})
def _profile(*,pid,provider,model,revision,prompt_id,pricing,cost,actions):
 local=provider==RULE_PROVIDER
 return AgentProfile.from_dict({"spec_version":AgentProfile.SPEC_VERSION,"profile_id":pid,"model":{"provider":provider,"model":model,"revision":revision,"base_url":None if local else BASE_URL},"harness":{"id":EconAckHarness.id,"version":EconAckHarness.version,"config":{"pricing_id":pricing.pricing_id,"pricing_sha256":pricing.content_sha256(),"output_schema":schema(),"provider_metadata":{"provider_cost_status":"local_zero_cost" if local else "response_reported"}}},"prompt":{"prompt_id":prompt_id,"sha256":hashlib.sha256(PROMPT.encode()).hexdigest()},"runtime":{"kind":"python","implementation":"aeread.shared_runner.task.execution","version":"0.1.0"},"tools":[],"memory":{"mode":"disabled"},"reasoning":{"condition_id":"reasoning_unavailable_v1" if local else "reasoning_disabled_v1","effort":None if local else "none","token_budget":None,"rationale_visibility":"unavailable" if local else "hidden"},"sampling":{"temperature":0,"max_output_tokens":16 if local else MAX_OUTPUT_TOKENS,"seed":None,"top_p":None},"budgets":{"max_logical_actions":actions,"timeout_seconds":180,"max_cost_usd":cost},"retry_policy":{"max_action_attempts":1,"retryable_conditions":[],"session_mode":"restart","sdk_retries":0}})

def build_live_setup(*,case_id:str,upstream_root:Path,sampling_seed:int=300,max_cost_usd:float=.03)->SimpleNamespace:
 case=load_case(case_id); family=family_manifest(); plugin=EconAgentV1Plugin(upstream_root=upstream_root); fc=plugin.validate_payload(case.payload); registry=PluginRegistry(); register_plugin(registry,plugin=plugin); suffix=hashlib.sha256(f"{case_id}:{sampling_seed}".encode()).hexdigest()[:10]
 sampling=SamplingPlan.from_dict({"spec_version":SamplingPlan.SPEC_VERSION,"sampling_plan_id":f"econagent_live_sampling_{suffix}","estimand":family.measurement.primary_estimand,"target":case_id,"selection":"fixed_curated","seeds":[sampling_seed],"replicates":1,"cluster_level":"case","cluster_id_fields":["case_id"],"paired_fields":[],"replicate_level":"episode_attempt","panel_mode":"fixed_panel"})
 seats=[x.id for x in case.seats]; controls={x:RULE_PROFILE_ID for x in seats if x!=SUBJECT_SEAT}
 block=EvaluationBlock.from_dict({"spec_version":EvaluationBlock.SPEC_VERSION,"block_id":f"econagent_live_block_{suffix}","kind":"controlled","subject_seats":[SUBJECT_SEAT],"controlled_profiles":controls,"repetitions":1,"seed_policy":"fixed"})
 analysis=AnalysisPlan.from_dict({"spec_version":AnalysisPlan.SPEC_VERSION,"analysis_plan_id":f"econagent_live_analysis_{suffix}","estimands":[family.measurement.primary_estimand],"group_by":["case_id"],"missingness":"report_separately","resampling_unit":"case","uncertainty":"none","multiplicity":"none","sensitivity":[],"cross_family_scalar":"disabled"})
 suite=SuiteManifest.from_dict({"spec_version":SuiteManifest.SPEC_VERSION,"suite_id":f"econagent_live_suite_{suffix}","version":"1.0.0","family_ids":[family.family.id],"case_ids":[case_id],"sampling_plan_id":sampling.sampling_plan_id,"evaluation_block_ids":[block.block_id],"analysis_plan_id":analysis.analysis_plan_id})
 subject=_profile(pid="econagent_glm5p2_arena_v1",provider=PROVIDER,model=MODEL,revision=REVISION,prompt_id=PROMPT_ID,pricing=PRICING,cost=max_cost_usd,actions=case.episode.max_logical_actions); rule=_profile(pid=RULE_PROFILE_ID,provider=RULE_PROVIDER,model=RULE_MODEL,revision="ack-rule-v1",prompt_id=RULE_PROMPT_ID,pricing=RULE_PRICING,cost=0,actions=case.episode.max_logical_actions)
 assignments={x:subject.profile_id if x==SUBJECT_SEAT else rule.profile_id for x in seats}
 run=RunSpec.from_dict({"spec_version":RunSpec.SPEC_VERSION,"run_spec_id":f"econagent_live_run_{suffix}","suite_id":suite.suite_id,"evaluation_block_ids":[block.block_id],"agent_profile_ids":[subject.profile_id,rule.profile_id],"seat_assignments":assignments,"execution_mode":"evaluate","replicate_override":None,"budget_overrides":None})
 scorer=plugin.build_scorer(fc); refs=set()
 for leaf in scorer.leaves: refs.update((leaf.estimand.validity_domain.predicate,leaf.verifier.reference.implementation,leaf.scorer))
 src=ROOT/"src"/"aeread_families"/"econagent_v1"; env=src/"environment.py"; meas=src/"measurement.py"; exe=ROOT/"src"/"aeread"/"shared_runner"/"task"/"execution.py"
 pins=(_pin(family.family.plugin_id,"family_plugin",family.family.version,hashlib.sha256(env.read_bytes()).hexdigest()),_pin(family.scoring.scorer_id,"scorer",family.family.version,hashlib.sha256(env.read_bytes()+meas.read_bytes()).hexdigest()),*tuple(_pin(r.implementation_id,"reference",r.version,r.content_sha256) for r in sorted(refs,key=lambda x:x.implementation_id)),_pin(EconAckHarness.id,"harness",EconAckHarness.version,hashlib.sha256((src/"live.py").read_bytes()).hexdigest()),_pin("aeread.shared_runner.task.execution","runtime","0.1.0",hashlib.sha256(exe.read_bytes()).hexdigest()))
 harness=EconAckHarness();harnesses={**default_harnesses(),f"{harness.id}/{harness.version}":harness};hr=HarnessRegistry();[hr.register(x) for x in harnesses.values()]
 plan=resolve_run_plan(families=(family,),cases=(case,),suite=suite,sampling=sampling,evaluation_blocks=(block,),analysis=analysis,agent_profiles=(subject,rule),run_spec=run,registry=registry,implementation_pins=pins,harness_registry=hr,provider_capabilities={PROVIDER:ProviderCapabilities(native_tools=False,structured_output=True,seed=False,system_prompt=True,reasoning_budget=True,reasoning_token_report=False,max_context_tokens=None),RULE_PROVIDER:ProviderCapabilities(native_tools=False,structured_output=True,seed=False,system_prompt=True,reasoning_budget=False,reasoning_token_report=False,max_context_tokens=None)})
 return SimpleNamespace(plan=plan,registry=registry,prompt_sources={PROMPT_ID:PROMPT,RULE_PROMPT_ID:RULE_PROMPT},pricing={MODEL:PRICING,RULE_MODEL:RULE_PRICING},rule_client=AckRuleClient(),harnesses=harnesses,case=case)
