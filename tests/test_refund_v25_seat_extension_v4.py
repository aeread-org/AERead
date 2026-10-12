import asyncio
import copy
import itertools
import json
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from aeread_families.refund import v2_5_seat_extension_v4 as v4


def proposal(case):
    return {**asdict(v4.v3.resolve_policy(case)), "proposal_id": "proposal_1"}


def test_development_and_holdout_are_disjoint_minimal_pairs():
    development = v4.build_panels()
    full = v4.build_panels(include_holdout=True)
    assert {k:len(v) for k,v in development.items()} == {"payments":8,"customer":4}
    assert {k:len(v) for k,v in full.items()} == {"payments":10,"customer":6}
    assert not any(c.seat_context["held_out"] for cases in development.values() for c in cases)
    assert sum(c.seat_context["held_out"] for cases in full.values() for c in cases) == 4
    for seed in (301,302,303):
        v4.admit_panels(v4.build_panels(seed,include_holdout=True))


def test_ledger_order_invariance_and_independent_observation_only_counterpart():
    for case in v4.build_panels(include_holdout=True)["payments"]:
        p = proposal(case)
        ledger = case.seat_context["payment_ledger"]
        expected = v4.payment_reference(p,ledger)
        for permutation in itertools.permutations(ledger["records"]):
            shuffled = {**ledger,"records":list(permutation)}
            assert v4.payment_reference(p,shuffled) == expected
            action = v4.scripted_payment({"confirmed_proposal":p,"payment_ledger":shuffled})
            action["action"] = action["decision"]
            assert v4.v3.payment_errors(action,expected) == []


def test_pending_scope_and_latest_revision_have_real_execution_reversals():
    by_mechanism={}
    for c in v4.build_panels()["payments"]:
        by_mechanism.setdefault(c.seat_context["mechanism"],[]).append(c)
    for mechanism,pair in by_mechanism.items():
        a,b=(v4.payment_reference(proposal(c),c.seat_context["payment_ledger"]) for c in pair)
        assert (a["kind"],a["amount"]) != (b["kind"],b["amount"]),mechanism
    pair=by_mechanism["line_item_residual"]
    assert v4.payment_reference(proposal(pair[1]),pair[1].seat_context["payment_ledger"])["amount"] == .01


def test_ambiguous_revisions_and_undeclared_pair_changes_fail_admission():
    panels=v4.build_panels()
    case=panels["payments"][0]
    ledger=copy.deepcopy(case.seat_context["payment_ledger"])
    ledger["records"].append(dict(ledger["records"][0]))
    bad=replace(case,seat_context={**case.seat_context,"payment_ledger":ledger})
    with pytest.raises(ValueError,match="Nonunique"):
        v4.admit_panels({**panels,"payments":(bad,panels["payments"][1])})
    changed=replace(case,interaction=replace(case.interaction,public_claim="Different claim"))
    with pytest.raises(ValueError,match="declared"):
        v4.admit_panels({**panels,"payments":(changed,panels["payments"][1])})


def test_customer_source_revision_disclosure_and_confirmation_negative_controls():
    case=v4.build_panels()["customer"][0]
    plugin=v4.ExtensionPlugin()
    phases={p.phase_id:p for p in plugin.phases(case)}
    state=plugin.initial_state(case,None)
    ids=list(case.facts)[:2]
    state["pending_requested"]=ids
    obs=plugin.observe(case,state,"customer",phases["customer_disclosure"])
    assert "private_facts" not in obs
    request=SimpleNamespace(input_text=json.dumps({"role":"customer","phase_id":"customer_disclosure","observation":obs}),provider_call_id="offline",model="scripted",revision="4")
    action=json.loads(asyncio.run(v4.ScriptedProvider().complete(request)).output_text)
    action["action"]=action["decision"]
    assert plugin.legal(case,state,"customer",phases["customer_disclosure"],action).legal
    wrong={**action,"fact_values":dict(action["fact_values"])}
    old=next(r for r in obs["private_fact_records"] if r["fact_id"]==ids[0] and r["revision"]==1)
    wrong["fact_values"][ids[0]]=old["value"]
    assert not plugin.legal(case,state,"customer",phases["customer_disclosure"],wrong).legal
    p=proposal(case);state["proposal"]=p
    confirm={"action":"confirm_resolution","proposal_id":p["proposal_id"],"revealed_fact_ids":[],"confirmed_terms":{k:p[k] for k in v4.TERMS}}
    assert plugin.legal(case,state,"customer",phases["customer_confirmation"],confirm).legal
    changed={**confirm,"confirmed_terms":{**confirm["confirmed_terms"],"amount":float(p["amount"])+.01}}
    assert plugin.legal(case,state,"customer",phases["customer_confirmation"],changed).reason=="customer_confirmation_terms_mismatch"


def test_new_settlement_on_redelivery_blocks_a_second_mutation():
    case=v4.build_panels()["payments"][0]
    plugin=v4.ExtensionPlugin();phases={p.phase_id:p for p in plugin.phases(case)}
    state=plugin.initial_state(case,None);p=proposal(case)
    ledger=case.seat_context["payment_ledger"]
    ticket={**v4.payment_reference(p,ledger),"public_ledger":ledger}
    assert ticket["kind"]=="execute"
    state.update(proposal=p,confirmed_proposal_id=p["proposal_id"],execution_ticket=ticket,original_execution_ticket=ticket)
    action=v4.scripted_payment({"confirmed_proposal":p,"payment_ledger":ledger});action["action"]=action["decision"]
    result=plugin.step(case,state,phases["payments_execute"],{"payments":SimpleNamespace(valid=True,action=action)})
    new=result.state
    assert len(new["transactions"])==1 and new["execution_ticket"]["kind"]=="no_op"
    wrong={**action,"ledger_snapshot_id":new["execution_ticket"]["ledger_snapshot_id"]}
    assert not plugin.legal(case,new,"payments",phases["payments_execute"],wrong).legal
    assert len(new["transactions"])==1


def test_customer_terms_are_advertised_in_schema_and_money_is_not_type_fragile():
    panels=v4.build_panels()
    setup=v4.build_run(panels["customer"],active_agents=("customer",))
    profile=next(p for p in setup.plan.agent_profiles if p.prompt.prompt_id==v4.v3.legacy.PROMPT_IDS["customer"])
    assert set(profile.harness.config["output_schema"]["properties"]["confirmed_terms"]["required"])==set(v4.TERMS)
    case=panels["customer"][0];plugin=v4.ExtensionPlugin()
    phase=next(p for p in plugin.phases(case) if p.phase_id=="customer_confirmation")
    state=plugin.initial_state(case,None);p={**proposal(case),"amount":0.0};state["proposal"]=p
    action={"action":"confirm_resolution","proposal_id":p["proposal_id"],"revealed_fact_ids":[],"confirmed_terms":{k:p[k] for k in v4.TERMS}}
    action["confirmed_terms"]["amount"]=0
    assert plugin.legal(case,state,"customer",phase,action).legal
    action["confirmed_terms"]["amount"]=False
    assert not plugin.legal(case,state,"customer",phase,action).legal
