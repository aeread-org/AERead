import asyncio
import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.scheduler import run_episode
from aeread_families.refund import v2_5_seat_extension_v7 as v7


def select(panel, structure, index=0, seed=301):
    return tuple(c for c in v7.build_panels(seed,True)[panel]
                 if c.seat_context["structure_id"] == structure and c.seat_context["mechanism"] == structure+"."+str(index))


async def trajectory(pair, corrupt=None):
    setup=v7.build_run(pair); plugin=v7.ExtensionPlugin(); manifest=setup.plan.cases[0]
    case=plugin.validate_payload(manifest.payload)
    cell=next(c for c in setup.plan.cells if c.case_id == manifest.case_id)
    provider=v7.ScriptedProvider(); seen=[]
    async def source(request):
        inp={"role":request.seat_id,"phase_id":request.phase_id,"observation":json.loads(canonical_json_bytes(request.observation))}
        result=await provider.complete(SimpleNamespace(input_text=json.dumps(inp),model="scripted",revision="7",provider_call_id="offline"))
        action=json.loads(result.output_text)
        seen.append((inp,copy.deepcopy(action)))
        if corrupt: action=corrupt(inp,action)
        return json.dumps(action)
    result=await run_episode(cell=cell,case=manifest,plugin=plugin,response_source=source)
    return case,result.final_state,plugin.outcome(case,result.final_state),seen


def test_counts_and_effects_all_seeds():
    for seed in (301,302,303):
        panels=v7.build_panels(seed)
        assert {k:len(v) for k,v in panels.items()} == {"intake":32,"customer":32}
        assert sum(len(v) for v in v7.build_panels(seed,True).values()) == 80
        counts={effect:sum(c.seat_context["pair_effect"] == effect for c in panels["customer"])/2
                for effect in ("disclosure_value_change","source_invariance","confirmation_binding_change")}
        assert counts == {"disclosure_value_change":12,"source_invariance":2,"confirmation_binding_change":2}
        assert not any(c.seat_context["held_out"] for group in panels.values() for c in group)


@pytest.mark.parametrize("panel,structure",[("intake",s["id"]) for s in v7.proposal()["intake_structures"]+v7.proposal()["reserved_intake_structures"]]
                         +[("customer",s["id"]) for s in v7.proposal()["customer_structures"]+v7.proposal()["reserved_customer_structures"]])
def test_full_trajectory_branches_and_visibility(panel,structure):
    for index in (0,1):
        pair=select(panel,structure,index)
        for order in (pair,pair[::-1]):
            case,state,outcome,seen=asyncio.run(trajectory(order))
            assert not state["failures"] and outcome["end_to_end"] == 1
            assert v7.baseline.seat_strict(outcome,state,"intake") == v7.baseline.seat_strict(outcome,state,"customer") == 1
            for inp,action in seen:
                obs=inp["observation"]; seat=inp["role"]
                if seat == "intake":
                    assert not {"private_facts","private_fact_records","reference_resolution","policy_contract","proposal_binding_v7"} & obs.keys()
                if seat == "policy":
                    assert not {"private_facts","private_fact_records","reference_resolution"} & obs.keys()
                    if action["decision"] == "submit_resolution" and "assigned_proposal_id" in obs:
                        assert action["proposal_id"] == obs["assigned_proposal_id"]
                if seat == "customer":
                    assert not {"reference_resolution","policy_contract","assigned_proposal_id"} & obs.keys()
                if seat == "payments":
                    assert not {"private_facts","private_fact_records","pending_proposal","policy_contract","reference_resolution"} & obs.keys()
            confirmations=[a for i,a in seen if i["phase_id"] == "customer_confirmation"]
            if structure == "CH02":
                assert len(confirmations) == 2 and confirmations[0]["proposal_id"] != confirmations[1]["proposal_id"]
            else: assert len(confirmations) == 1
            assert len(state["transactions"]) <= 1
            if state["transactions"]: assert state["transactions"][0]["proposal_id"] == state["confirmed_proposal_id"]


def test_independent_intake_planners_all_reachable_states(monkeypatch):
    for case in v7.build_panels(301,True)["intake"]:
        c=case.seat_context["collection_v6"]; visited=set()
        def visit(known,budget,round_number):
            key=(tuple(sorted(known)),budget,round_number)
            if key in visited: return
            visited.add(key)
            obs=v7.baseline.intake_observation(case,{"revealed_facts":{k:case.facts[k] for k in known},"collection_budget":budget,"collection_round":round_number})
            plan=v7.baseline.intake_plan_reference(obs)
            assert v7.baseline.scripted_intake(obs) == (list(plan[0]) if plan else [])
            if round_number < c["max_rounds"]:
                for batch,spent,_ in v7.baseline._batches(c,known,budget): visit(set(known)|set(batch),budget-spent,round_number+1)
        visit(set(),c["total_budget"],0)
    monkeypatch.setattr(v7.baseline,"intake_plan_reference",lambda *_:pytest.fail("script consulted oracle"))
    assert v7.baseline.scripted_intake(v7.baseline.intake_observation(case,{}))


@pytest.mark.parametrize("kind,reason",[("stale","customer_confirmation_stale_proposal"),("terms","customer_confirmation_terms_mismatch"),
                                      ("policy_id","policy_assigned_proposal_binding_mismatch"),("extra_fact","customer_unrequested_fact_disclosure")])
def test_binding_and_disclosure_negative_controls(kind,reason):
    def corrupt(inp,action):
        phase=inp["phase_id"]
        if kind == "stale" and phase == "customer_confirmation":
            action["proposal_id"]=inp["observation"]["expired_proposals"][0]["proposal_id"]
        elif kind == "terms" and phase == "customer_confirmation": action["confirmed_terms"]["amount"] += .01
        elif kind == "policy_id" and phase == "policy_turn" and action["decision"] == "submit_resolution": action["proposal_id"]="unassigned"
        elif kind == "extra_fact" and phase == "customer_disclosure":
            action["revealed_fact_ids"].append("not_requested"); action["fact_values"]["not_requested"]=True
        return action
    _,state,outcome,_=asyncio.run(trajectory(select("customer","C08"),corrupt))
    assert state["failures"]
    if kind != "extra_fact": assert reason in state["failures"]
    assert outcome["end_to_end"] == 0 and not state["transactions"]


def test_sequential_stale_confirmation_and_no_interim_payment():
    def corrupt(inp,action):
        if inp["phase_id"] == "customer_confirmation":
            old=[p for p in inp["observation"]["expired_proposals"] if p.get("draft_status") == "superseded"]
            if old: action["proposal_id"]=old[-1]["proposal_id"]
        return action
    _,state,_,seen=asyncio.run(trajectory(select("customer","CH02"),corrupt))
    assert state["failures"] == ("customer_confirmation_stale_proposal",) or list(state["failures"]) == ["customer_confirmation_stale_proposal"]
    assert not state["transactions"] and not any(i["role"] == "payments" for i,a in seen)
    assert state["confirmed_proposal_id"] is None


@pytest.mark.parametrize("mutation",["fact","record","budget","cycle","duplicate","undeclared"])
def test_admission_rejects_malformed_or_unlisted_changes(mutation):
    pair=list(select("intake","I04")) if mutation in ("budget","cycle") else list(select("customer","C01"))
    c=pair[1]; ctx=copy.deepcopy(c.seat_context); facts=dict(c.facts)
    if mutation == "fact": facts[next(iter(facts))]=False
    elif mutation == "record": ctx["private_records_v6"][0]["value"]="invented"
    elif mutation == "budget": ctx["collection_v6"]["max_rounds"]=5; ctx["collection_v5"]=copy.deepcopy(ctx["collection_v6"])
    elif mutation == "cycle":
        for row in ctx["collection_v6"]["catalogue"]: row["requires"]=[row["fact_id"]]
        ctx["collection_v5"]=copy.deepcopy(ctx["collection_v6"])
    elif mutation == "duplicate": ctx["private_records_v6"].append(copy.deepcopy(ctx["private_records_v6"][0]))
    else: ctx["customer_contract_v6"]["as_of"] += 100; ctx["intervention_path"]="customer_contract_v6"
    pair[1]=replace(c,seat_context=ctx,interaction=replace(c.interaction,facts=facts))
    with pytest.raises(ValueError): v7.admit_panels({"test":tuple(pair)})


def test_active_seat_control_and_phase_bounds():
    pair=select("intake","I04")
    with pytest.raises(ValueError): v7.build_run(pair,active_agents=("customer","intake"))
    plugin=v7.ExtensionPlugin()
    assert next(p for p in plugin.phases(pair[0]) if p.phase_id == "intake_request").max_logical_actions >= 4
    assert v7.proposal()["paid_execution_authorized"] is False


def test_graph_edges_exercised_and_four_round_trace():
    pair=select("intake","I07",1)
    covered=set()
    for c in pair:
        plan=v7.baseline.intake_plan_reference(v7.baseline.intake_observation(c,{}))
        covered |= {k for batch in plan for k in batch}
    assert covered == set(v7.v3.spec_for(pair[0].interaction.scenario).fact_ids())
    _,state,_,_=asyncio.run(trajectory(pair[::-1]))
    assert len([e for e in state["events"] if e["phase"] == "intake_request"]) == 4
    assert not state["failures"]


def test_customer_script_is_oracle_independent_and_record_order_invariant(monkeypatch):
    observations=[]
    for case in v7.build_panels(301,True)["customer"]:
        obs={"requested_fact_ids":list(case.facts),"customer_contract_v6":case.seat_context["customer_contract_v6"],
             "private_fact_records":case.seat_context["private_records_v6"]}
        assert v7.baseline.scripted_disclosure(obs) == v7.baseline.disclosure_reference(obs)
        observations.append((obs,dict(case.facts)))
    monkeypatch.setattr(v7.baseline,"disclosure_reference",lambda *_:pytest.fail("script consulted oracle"))
    for obs,expected in observations:
        reverse={**obs,"private_fact_records":list(reversed(obs["private_fact_records"]))}
        assert canonical_json_bytes(v7.baseline.scripted_disclosure(reverse)) == canonical_json_bytes(expected)


def test_schema_error_is_contract_only_and_seat_scoped():
    def corrupt(inp,action):
        if inp["role"] == "customer": action["extra"]=True
        return action
    _,state,outcome,_=asyncio.run(trajectory(select("customer","C08"),corrupt))
    assert not state["failures"]
    assert outcome["policy_semantic"] == outcome["customer_disclosure_integrity"] == outcome["customer_confirmation_integrity"] == 1
    assert outcome["contract"] == 0
    assert v7.baseline.seat_strict(outcome,state,"customer") == 0
    assert v7.baseline.seat_strict(outcome,state,"intake") == 1
