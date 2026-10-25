"""V7 developmental structure panel. Offline authoring; no paid driver."""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import itertools
import json
from dataclasses import asdict, replace
from functools import lru_cache
from importlib.resources import files as package_files
from pathlib import Path

from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry
from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256, resolve_run_plan
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import LegalityResult, TransitionResult
from . import v2_5_seat_extension_v6_2_1 as baseline

v3, v5 = baseline.v3, baseline.v5
REVISION = "refund_v25_seat_extension/7"
VERSION = "2.5.10"
ROOT = Path(__file__).resolve().parents[3]
RESOURCE_LOOKUP_REVISION = "refund_v25_v7_packaged_resources/1"
PROPOSAL_RESOURCE = "refund_v25_customer_intake_v7_design_proposal.json"
PROPOSAL = ROOT / "configs" / PROPOSAL_RESOURCE
PROPOSAL_SHA = "76ac8d8430a751dd8d2af6298780668280ec043a30d6e322f0deaa93c5c2d7cc"


def proposal():
    """Read pinned bytes from the checkout or the wheel's aeread/configs.

    A present checkout resource is authoritative, including when unreadable or
    invalid. Only absence permits package lookup; a bad checkout must never be
    masked by a valid installed copy. Traversable access also supports zip imports.
    This lookup revision does not change the V7 case or scoring revision.
    """
    try:
        PROPOSAL.lstat()
    except FileNotFoundError:
        resource = package_files("aeread").joinpath("configs").joinpath(PROPOSAL_RESOURCE)
        raw = resource.read_bytes()
    else:
        raw = PROPOSAL.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROPOSAL_SHA:
        raise ValueError("Versioned proposal changed")
    return json.loads(raw)


def public_observation(structure, costs, utilities, budget, rounds, cap):
    ids = [f"f{i}" for i in range(structure["nodes"])]
    return {"collection_v6": {"catalogue": [
        {"fact_id": k, "material": True, "source": "authorized", "requires": [ids[a] for a,b in structure["edges"] if b == i],
         "cost": costs[i], "utility": utilities[i]} for i,k in enumerate(ids)],
        "authorized_sources": ["authorized"], "max_batch_size": cap,
        "max_rounds": rounds, "total_budget": budget, "rule": baseline.INTAKE_RULE},
        "collection_round": 0, "remaining_collection_budget": budget, "disclosed_fact_ids": []}


@lru_cache(None)
def planning_witness(structure_json, axis, seed=301):
    s = json.loads(structure_json); n = s["nodes"]; grid = proposal()["witness_search"]
    costs = sorted({tuple([1]*n), tuple(1+i%2 for i in range(n)), tuple(2-i%2 for i in range(n)), tuple(1+i%3 for i in range(n))})
    utilities = sorted({tuple((1,5,12,24,40)[:n]), tuple(reversed((1,5,12,24,40)[:n]))})
    # A fixed seed-indexed rotation of the authored grid, never model-result selection.
    offset = (seed-301) % len(costs)
    costs = costs[offset:] + costs[:offset]
    offset = (seed-301) % len(utilities)
    utilities = utilities[offset:] + utilities[:offset]
    for cost, utility, budget, rounds, cap in itertools.product(costs, utilities, grid["budgets"], grid["horizons"], grid["batch_caps"]):
        values = grid["budgets"] if axis == "total_budget" else grid["horizons"]
        start = budget if axis == "total_budget" else rounds
        for end in values[values.index(start)+1:]:
            a = public_observation(s,cost,utility,budget,rounds,cap)
            b = public_observation(s,cost,utility,end if axis == "total_budget" else budget,end if axis == "max_rounds" else rounds,cap)
            pa,pb = baseline.intake_plan_reference(a),baseline.intake_plan_reference(b)
            covered = {k for plan in (pa,pb) for batch in plan for k in batch}
            if pa and pb and covered == {f"f{i}" for i in range(n)} and pa[0] != pb[0] and not all((baseline.intake_assessment(a,list(pb[0]))[0],baseline.intake_assessment(b,list(pa[0]))[0])):
                return a,b
    raise ValueError("No objective planning contrast: " + s["id"] + axis)


def source_pair(seed, scenario):
    cases = v3.build_unified_panel(seed, include_policy_stress_extension=True)
    pair = [c for c in cases if c.interaction.scenario == scenario]
    if len(pair) != 2 or v3.resolve_policy(pair[0]) == v3.resolve_policy(pair[1]):
        raise ValueError("No unique semantic source pair: " + scenario)
    return pair


def context(structure, pair_index, kind, heldout):
    return {"panel": kind + "_v7", "pair_kind": kind + "_v5", "structure_id": structure["id"],
            "mechanism": structure["id"] + "." + str(pair_index), "held_out": heldout,
            "stratum": structure.get("difficulty", "reserved"), "proposal_supersession": False,
            "confirmation_terms": True, "overlapping_disclosure": False}


def make_case(base, seed, ctx, variant, facts):
    stem = f"seat_v7.{ctx['panel']}.{ctx['mechanism']}".lower()
    return v3.SeatCase(replace(base.interaction, case_id=f"{stem}.{variant}.{seed:06d}", pair_id=stem,
                              variant=variant, facts=copy.deepcopy(facts), changed_fact_ids=()), base.product_category, ctx)


def customer_pair(s, index, seed, heldout):
    left,right = source_pair(seed,s["scenario"])
    scope = "order_A"; cutoff = 10 + index * 10
    contract = {"request_scope": scope, "as_of": cutoff,
                "authorities": [{"document_id":"primary","priority":0},{"document_id":"backup","priority":1}], "rule":baseline.CUSTOMER_RULE}
    records = []
    def add(fact,doc,revision,time,status,value,record_scope=scope):
        records.append({"fact_id":fact,"document_id":doc,"scope":record_scope,"revision":revision,"recorded_at":time,"status":status,"value":copy.deepcopy(value)})
    name = s["id"]
    for fact,x in left.facts.items():
        y = right.facts[fact]
        add(fact,"primary",1,1,"live",x)
        add(fact,"backup",1,1,"live",y)
        if name in ("C01","C05"):
            add(fact,"primary",2,cutoff+1,"live",y)
            if name == "C05" and fact not in left.interaction.changed_fact_ids:
                add(fact,"primary",3,2,"revoked",None)
        elif name in ("C03","CH01") and fact in left.interaction.changed_fact_ids:
            add(fact,"primary",2,cutoff+1,"revoked",None)
        elif name == "C04":
            add(fact,"primary",2,2,"revoked",None)
            add(fact,"primary",3,cutoff+1,"live",x)
        elif name == "C06":
            add(fact,"primary",100,1,"live",y,"order_B")
            add(fact,"primary",101,1,"revoked",None,"foreign")
            add(fact,"backup",100,1,"live",y,"order_B")
        elif name == "C07":
            # No primary record exists yet at the first snapshot.
            records[-2]["recorded_at"] = cutoff+1
            add(fact,"primary",200,cutoff+100,"live",x,"foreign")
        if name == "CH01":
            add(fact,"third",1,1,"live",x)
            add(fact,"third",2,cutoff+100,"revoked",None,"foreign")
    if name == "CH01":
        contract["authorities"].append({"document_id":"third","priority":2})
    contracts = [copy.deepcopy(contract),copy.deepcopy(contract)]
    record_sets = [copy.deepcopy(records),copy.deepcopy(records)]
    effect = s.get("pair_effects",["disclosure_value_change"]*2)[index]
    binding = None
    if name in ("C08","CH02"):
        effect = "confirmation_binding_change"
        binding = [{"current_id":f"proposal_{seed}_{index}_current_A","next_id":f"proposal_{seed}_{index}_final_A"},
                   {"current_id":f"proposal_{seed}_{index}_current_B","next_id":f"proposal_{seed}_{index}_final_A"}]
        path = "proposal_binding_v7.current_id"
    elif effect == "source_invariance":
        target = next(i for i,r in enumerate(records) if r["scope"] == "foreign")
        field = "status" if name == "C06" else "revision"
        record_sets[1][target][field] = "live" if field == "status" else 201
        path = f"private_records_v6.{target}.{field}"
    elif name == "C06":
        contracts[1]["request_scope"] = "order_B"; path = "customer_contract_v6.request_scope"
    elif name == "C02" or (name == "C05" and index == 1):
        contracts[1]["authorities"][0]["priority"] = 2; path = "customer_contract_v6.authorities.0.priority"
    else:
        contracts[1]["as_of"] = cutoff+1; path = "customer_contract_v6.as_of"
    output = []
    for j,variant in enumerate(("a","b")):
        ctx = context(s,index,"customer",heldout)
        ctx.update(customer_contract_v6=contracts[j],private_records_v6=record_sets[j],
                   pair_effect=effect,intervention_path=path,customer_record_provenance=True)
        if binding:
            ctx.update(proposal_binding_v7=binding[j],sequential_proposals=name == "CH02")
        obs = {"requested_fact_ids":list(left.facts),"customer_contract_v6":contracts[j],"private_fact_records":record_sets[j]}
        output.append(make_case(left,seed,ctx,variant,baseline.disclosure_reference(obs)))
    return finalize_changes(output)


def finalize_changes(pair):
    changed = tuple(sorted(k for k in pair[0].facts if canonical_json_bytes(pair[0].facts[k]) != canonical_json_bytes(pair[1].facts[k])))
    return [replace(c,interaction=replace(c.interaction,changed_fact_ids=changed)) for c in pair]


def build_panels(seed=301, include_holdout=False):
    p = proposal(); panels = {"intake":[],"customer":[]}
    structures = [(s,False) for s in p["intake_structures"]]
    if include_holdout: structures += [(s,True) for s in p["reserved_intake_structures"]]
    for s,heldout in structures:
        base = source_pair(seed,s["scenario"])[0]
        ids = sorted(v3.spec_for(s["scenario"]).fact_ids())
        for index,axis in enumerate(("total_budget","max_rounds")):
            witnesses = planning_witness(json.dumps(s,sort_keys=True),axis,seed)
            for variant,w in zip(("a","b"),witnesses):
                c = copy.deepcopy(w["collection_v6"])
                mapping = {f"f{i}":k for i,k in enumerate(ids)}
                for row in c["catalogue"]:
                    row["fact_id"] = mapping[row["fact_id"]]; row["requires"] = [mapping[k] for k in row["requires"]]
                ctx = context(s,index,"intake",heldout)
                ctx.update(collection_v6=c,collection_v5=copy.deepcopy(c),pair_effect="observable_action_change",intervention_path="collection_v6."+axis)
                panels["intake"].append(make_case(base,seed,ctx,variant,base.facts))
    structures = [(s,False) for s in p["customer_structures"]]
    if include_holdout: structures += [(s,True) for s in p["reserved_customer_structures"]]
    for s,heldout in structures:
        for index in (0,1): panels["customer"] += customer_pair(s,index,seed,heldout)
    result = {k:tuple(v) for k,v in panels.items()}
    admit_panels(result)
    return result


def admit_panels(panels):
    cases = [c for group in panels.values() for c in group]; pairs = {}
    if not cases or len({c.case_id for c in cases}) != len(cases): raise ValueError("Unique cases required")
    for case in cases:
        v3.legacy.validate_case_domains(case)
        v3.legacy.validate_resolution_invariants(case,v3.resolve_policy(case))
        spec = v3.spec_for(case.interaction.scenario)
        compiled = spec.resolve(case.facts,v3.public_inputs(case.interaction.item_net_price,case.interaction.allocated_tax))
        ref = asdict(v3.resolve_policy(case)); expected = {k:ref[k] for k in v3.legacy._RESOLUTION_FIELDS if k != "reason_code"}; expected["reason_code"] = ref["policy_basis"]
        if compiled != expected: raise ValueError("Policy/reference disagreement")
        ctx = case.seat_context; path = ctx["intervention_path"]
        p = proposal()
        authored = p["intake_structures"]+p["reserved_intake_structures"] if "collection_v6" in ctx else p["customer_structures"]+p["reserved_customer_structures"]
        structure = next((s for s in authored if s["id"] == ctx["structure_id"]),None)
        if structure is None or structure["scenario"] != case.interaction.scenario or ctx["held_out"] != (structure["id"] in {s["id"] for s in p["reserved_intake_structures"]+p["reserved_customer_structures"]}): raise ValueError("Structure/proposal mismatch")
        if "collection_v6" in ctx:
            c = ctx["collection_v6"]; rows = c["catalogue"]; ids = {r["fact_id"] for r in rows}
            if c != ctx["collection_v5"] or c["rule"] != baseline.INTAKE_RULE or ids != set(spec.fact_ids()) or len(ids) != len(rows): raise ValueError("Invalid material catalogue")
            if type(c["max_rounds"]) is not int or not 1 <= c["max_rounds"] <= 4 or type(c["max_batch_size"]) is not int or not 1 <= c["max_batch_size"] <= 3 or type(c["total_budget"]) is not int or not 1 <= c["total_budget"] <= 12: raise ValueError("Invalid bounded planning contract")
            reached = set()
            ordered_ids = sorted(ids)
            edges = {(ordered_ids[a],ordered_ids[b]) for a,b in structure["edges"]}
            if {(k,r["fact_id"]) for r in rows for k in r["requires"]} != edges: raise ValueError("Authored graph mismatch")
            for r in rows:
                if r["material"] is not True or type(r["cost"]) is not int or r["cost"] < 1 or type(r["utility"]) is not int or r["utility"] < 1 or not set(r["requires"]) <= ids or r["source"] not in c["authorized_sources"]: raise ValueError("Invalid planning node")
            for _ in rows: reached |= {r["fact_id"] for r in rows if set(r["requires"]) <= reached}
            if reached != ids or not baseline.intake_plan_reference(baseline.intake_observation(case,{})): raise ValueError("Uncollectible graph")
            if path not in ("collection_v6.total_budget","collection_v6.max_rounds"): raise ValueError("Undeclared planning intervention")
        else:
            c = ctx["customer_contract_v6"]; records = ctx["private_records_v6"]; auth = c["authorities"]
            if c["rule"] != baseline.CUSTOMER_RULE or type(c["as_of"]) is not int or not isinstance(c["request_scope"],str) or any(type(a["priority"]) is not int or a["priority"] < 0 for a in auth) or len({a["priority"] for a in auth}) != len(auth) or len({a["document_id"] for a in auth}) != len(auth): raise ValueError("Ambiguous authority contract")
            keys = [(r["fact_id"],r["document_id"],r["scope"],r["revision"]) for r in records]
            if len(set(keys)) != len(keys): raise ValueError("Duplicate record revision")
            if any(r["fact_id"] not in case.facts or r["status"] not in ("live","revoked") or type(r["revision"]) is not int or r["revision"] < 1 or type(r["recorded_at"]) is not int for r in records): raise ValueError("Invalid record")
            obs = {"requested_fact_ids":list(case.facts),"customer_contract_v6":c,"private_fact_records":records}
            if canonical_json_bytes(baseline.disclosure_reference(obs)) != canonical_json_bytes(case.facts) or canonical_json_bytes(baseline.scripted_disclosure(obs)) != canonical_json_bytes(case.facts): raise ValueError("Authoritative facts disagree")
            allowed = {"customer_contract_v6.as_of","customer_contract_v6.request_scope","customer_contract_v6.authorities.0.priority","proposal_binding_v7.current_id"}
            allowed |= {f"private_records_v6.{i}.{field}" for i,r in enumerate(records) if r["scope"] == "foreign" for field in ("revision","status")}
            if path not in allowed: raise ValueError("Intervention not allowed")
            binding = ctx.get("proposal_binding_v7")
            if binding and (not all(isinstance(binding.get(k),str) and binding[k] for k in ("current_id","next_id")) or binding["current_id"] == binding["next_id"] or binding["current_id"].startswith("proposal_archived_")): raise ValueError("Ambiguous proposal binding")
        pairs.setdefault(case.interaction.pair_id,[]).append(case)
    for pair in pairs.values():
        if len(pair) != 2 or {c.interaction.variant for c in pair} != {"a","b"}: raise ValueError("Two variants required")
        a,b = sorted(pair,key=lambda c:c.interaction.variant); path = a.seat_context["intervention_path"]
        if path != b.seat_context["intervention_path"] or canonical_json_bytes(baseline._value_at(a.seat_context,path)) == canonical_json_bytes(baseline._value_at(b.seat_context,path)): raise ValueError("Actual single intervention required")
        changed = {k for k in a.facts if canonical_json_bytes(a.facts[k]) != canonical_json_bytes(b.facts[k])}
        if changed != set(a.interaction.changed_fact_ids) or changed != set(b.interaction.changed_fact_ids): raise ValueError("Fact differences undeclared")
        raw = [asdict(a),asdict(b)]
        for r in raw:
            r["interaction"].pop("case_id"); r["interaction"].pop("variant")
            for k in changed: r["interaction"]["facts"][k] = None
            v5._set_path(r["seat_context"],path,None)
            if path.startswith("collection_v6."): v5._set_path(r["seat_context"],path.replace("collection_v6.","collection_v5."),None)
        if raw[0] != raw[1]: raise ValueError("Unexpected pair difference")
        effect = a.seat_context["pair_effect"]
        if effect == "observable_action_change":
            oa,ob = (baseline.intake_observation(c,{}) for c in (a,b)); pa,pb = (baseline.intake_plan_reference(o) for o in (oa,ob))
            covered = {k for plan in (pa,pb) for batch in plan for k in batch}
            if covered != set(v3.spec_for(a.interaction.scenario).fact_ids()) or pa[0] == pb[0] or all((baseline.intake_assessment(oa,list(pb[0]))[0],baseline.intake_assessment(ob,list(pa[0]))[0])) or v3.resolve_policy(a) != v3.resolve_policy(b): raise ValueError("No objective graph-covering action contrast")
        elif effect == "disclosure_value_change":
            if not changed or v3.resolve_policy(a) == v3.resolve_policy(b): raise ValueError("No policy contrast")
        elif effect in ("source_invariance","confirmation_binding_change"):
            if changed or v3.resolve_policy(a) != v3.resolve_policy(b): raise ValueError("Broken semantic invariance")
        else: raise ValueError("Unknown pair effect")


class ExtensionPlugin(baseline.ExtensionPlugin):
    def validate_payload(self,payload):
        case = super().validate_payload(payload)
        if payload.get("design_revision") != REVISION: raise ValueError("Wrong V7 revision")
        return case

    def phases(self,case):
        n = len(v3.spec_for(case.interaction.scenario).fact_ids())
        return tuple(replace(p,max_logical_actions=max(p.max_logical_actions,4)) if p.phase_id == "intake_request" else
                     replace(p,max_logical_actions=n+5) if p.phase_id == "customer_disclosure" else
                     replace(p,max_logical_actions=n+3) if p.phase_id == "policy_turn" else
                     replace(p,max_logical_actions=2,next_phases=("payments_execute","policy_turn")) if p.phase_id == "customer_confirmation" else p
                     for p in super().phases(case))

    def initial_state(self,case,run):
        return {**super().initial_state(case,run),"proposal_delivery_v7":0}

    def observe(self,case,state,seat,phase):
        obs = dict(super().observe(case,state,seat,phase))
        binding = case.seat_context.get("proposal_binding_v7")
        if binding and seat == "policy":
            obs["assigned_proposal_id"] = binding["next_id"] if state["proposal_delivery_v7"] else binding["current_id"]
        return obs

    def legal(self,case,state,seat,phase,action):
        if seat == "policy" and action.get("action") == "submit_resolution" and case.seat_context.get("proposal_binding_v7"):
            expected = self.observe(case,state,seat,phase)["assigned_proposal_id"]
            if action.get("proposal_id") != expected: return LegalityResult.illegal("policy_assigned_proposal_binding_mismatch")
        return super().legal(case,state,seat,phase,action)

    def step(self,case,state,phase,actions):
        result = super().step(case,state,phase,actions); new = dict(result.state)
        if new["failures"]: return result
        if phase.phase_id == "policy_turn" and result.next_phase_id == "customer_confirmation" and case.seat_context.get("proposal_binding_v7"):
            # Preserve the exact ID submitted by policy; never overwrite the live proposal.
            p = new["proposal"]
            archived = list(state.get("expired_proposals",()))
            archived += [{**p,"proposal_id":"proposal_archived_999","draft_status":"abandoned","amount":round(p["amount"]+1,2)},
                         {**p,"proposal_id":"proposal_archived_998","draft_status":"abandoned"}]
            new["expired_proposals"] = archived
        if phase.phase_id == "customer_confirmation" and case.seat_context.get("sequential_proposals") and not state["proposal_delivery_v7"]:
            new["expired_proposals"] = list(new["expired_proposals"]) + [{**new["proposal"],"draft_status":"superseded"}]
            new.update(proposal_delivery_v7=1,proposal=None,confirmed_proposal_id=None,execution_ticket=None)
            return TransitionResult(new,"policy_turn")
        return TransitionResult(new,result.next_phase_id)

    def build_scorer(self,case):
        scorer = super().build_scorer(case); digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest(); leaves=[]
        for leaf in scorer.leaves:
            domain = leaf.estimand.validity_domain; ref = leaf.verifier.reference
            leaves.append(replace(leaf,leaf_version=VERSION,estimand=replace(leaf.estimand,estimand_version=VERSION,
                validity_domain=replace(domain,domain_version=VERSION,predicate=replace(domain.predicate,version=VERSION,content_sha256=digest))),
                verifier=replace(leaf.verifier,reference=replace(ref,reference_version=VERSION,implementation=replace(ref.implementation,version=VERSION,content_sha256=digest)))))
        return replace(scorer,leaves=tuple(leaves))


class ScriptedProvider(baseline.ScriptedProvider):
    async def complete(self,request):
        result = await super().complete(request); inp = json.loads(request.input_text)
        action = json.loads(result.output_text)
        if inp["role"] == "policy" and action.get("decision") == "submit_resolution" and "assigned_proposal_id" in inp["observation"]:
            action["proposal_id"] = inp["observation"]["assigned_proposal_id"]
        return replace(result,output_text=json.dumps(action))


def build_run(cases,active_agents=("policy",),provider="scripted",model="refund-v25-scripted",provider_revision=REVISION):
    if len(active_agents) != 1 or active_agents[0] not in v3.legacy.ROLES: raise ValueError("Exactly one active seat required")
    admit_panels({"selected":cases})
    template = baseline.build_run(baseline.build_panels(cases[0].interaction.world_seed)["customer"],active_agents,provider,model,provider_revision)
    family = template.plan.families[0]; plugin = ExtensionPlugin()
    digest = hashlib.sha256(Path(baseline.__file__).read_bytes()).hexdigest()
    pins = tuple(v3.legacy._pin(p.component_id,p.kind,Path(__file__),VERSION) if p.sha256 == digest else p for p in template.plan.implementation_pins)
    dep = v3.legacy._pin("refund_v25_v621_dependency","reference",Path(baseline.__file__),baseline.VERSION)
    config_pin = v3.legacy._pin("refund_v25_v7_proposal","reference",PROPOSAL,REVISION)
    pins += (dep,config_pin)
    family = replace(family,scoring=replace(family.scoring,reference_provider_ids=family.scoring.reference_provider_ids+(dep.component_id,config_pin.component_id)))
    registry=PluginRegistry(); registry.register(family,plugin,contribution=v3.legacy._contribution(),evidence_root=v3.legacy.ROOT / "cases/refund_v2")
    manifests=[]
    for case in cases:
        raw=json.loads(canonical_json_bytes(v3.legacy._case_manifest(case)))
        raw["episode"]["max_logical_actions"]=max(40,2*len(v3.spec_for(case.interaction.scenario).fact_ids())+20)
        raw["payload"].update(collection_contract=v3.collection_contract(case),design_revision=REVISION)
        raw["payload"]["semantic_case_sha256"]=hashlib.sha256(canonical_json_bytes({"case":asdict(case),"revision":REVISION})).hexdigest()
        raw["provenance"].update(generator_version=VERSION,review_status="generated")
        raw["content_sha256"]=case_content_sha256(raw); manifests.append(CaseManifest.from_dict(raw))
    prompts=dict(template.prompt_sources)
    prompts[v3.legacy.PROMPT_IDS["policy"]] += " If assigned_proposal_id is present, submit exactly that ID; it is the public binding for this delivery."
    profiles=tuple(replace(p,prompt=replace(p.prompt,sha256=hashlib.sha256(prompts[p.prompt.prompt_id].encode()).hexdigest())) for p in template.plan.agent_profiles)
    harnesses=HarnessRegistry()
    for h in template.harnesses.values(): harnesses.register(h)
    suite="refund_v25_seat_extension_v7"
    plan=resolve_run_plan(families=(family,),cases=tuple(manifests),suite=replace(template.plan.suite,suite_id=suite,case_ids=tuple(c.case_id for c in manifests)),
        sampling=template.plan.sampling,evaluation_blocks=template.plan.evaluation_blocks,analysis=template.plan.analysis,agent_profiles=profiles,
        run_spec=replace(template.plan.run_spec,suite_id=suite),registry=registry,implementation_pins=pins,harness_registry=harnesses,
        provider_capabilities={provider:v5.ProviderCapabilities(False,False,False,True,True,False,None),"scripted":v5.ProviderCapabilities(False,False,False,True,False,False,None)})
    return replace(template,registry=registry,plan=plan,prompt_sources=prompts)


async def conformance(output,seeds=(301,302,303)):
    if output.exists(): raise FileExistsError("Fresh offline output required")
    rows=[]
    for seed in seeds:
        for panel,cases in build_panels(seed,include_holdout=True).items():
            for seat in v3.legacy.ROLES:
                setup=build_run(cases,active_agents=(seat,))
                for cell in setup.plan.cells:
                    root=output/str(seed)/panel/seat
                    execution=await v3.legacy.execute_plan_cell(plan=setup.plan,cell_id=cell.cell_id,registry=setup.registry,evidence_root=root,
                        prompt_sources=setup.prompt_sources,providers={"scripted":ScriptedProvider()},pricing=setup.pricing,episode_attempt_ordinal=0,harnesses=setup.harnesses)
                    receipt=v3.legacy.finalize_family_execution(setup=setup,execution=execution)
                    v3.legacy.replay_family_receipt(setup=setup,receipt=receipt,evidence_root=root)
                    if not all(s.primary.value == 1 for s in receipt.scores): raise AssertionError((cell.case_id,seat,[(s.leaf.leaf_id,s.primary.value) for s in receipt.scores]))
                    metrics=next(s.primary.metadata["collaboration_metrics"] for s in receipt.scores if s.leaf.leaf_id == v3.measurement.END_TO_END_LEAF_ID)
                    if not all(m["value"] == 1 and m["coverage"] == 1 for m in metrics.values()): raise AssertionError((cell.case_id,metrics))
                    rows.append({"case_id":cell.case_id,"seat":seat,"full_scores":True,"replayed":True})
        print(json.dumps({"seed":seed,"completed":len(rows)}),flush=True)
    result={"revision":REVISION,"seeds":list(seeds),"completed":len(rows),"paid_calls":0,"rows":rows,
            "source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"human_normative_qc_approved":False,"paid_execution_authorized":False}
    (output/"summary.json").write_bytes(canonical_json_bytes(result)+b"\n")
    return result


if __name__ == "__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--output",type=Path,required=True)
    asyncio.run(conformance(parser.parse_args().output))
