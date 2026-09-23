"""Small Jev pass with rule-derived ground truth: procurement (36), lemons live worlds (49), datacenter counteroffer adoption (18) + affordance (20)."""
import json, os, sys, re, collections
HERE=__import__("pathlib").Path(__file__).resolve().parent; RES=HERE/"results"
SC=sys.argv[1]; sys.path.insert(0,str(HERE))
from jev_lib import load, expand, acts, compact, trace_state, call, Q_PROC
def choice(instr,**crit): return {"type":"choice","instructions":instr,"criteria":crit}
ATT=choice("How much does this trajectory deserve an analyst's attention?",high="something went clearly wrong or clearly unusual",medium="worth a look",low="routine")
def ans(data,q): a=data["answers"][q]; return a["choice"], round(max(a["probabilities"].values()),2)
res={}; cost=0.0; ncalls=0
def run(label,items,Q):
    global cost,ncalls; rows=[]
    for key,state,truth in items:
        data,err,nb=call(state,Q); ncalls+=1
        if err: rows.append({"key":key,"err":err}); print(label,key,"ERR",err[:100]); continue
        cost+=float((data.get("usage") or {}).get("cost") or 0)
        rows.append({"key":key,"bytes":nb,"truth":truth,"jev":{q:ans(data,q) for q in Q}})
    res[label]=rows; print(label,len(rows),"done"); return rows
# ---------- 1. procurement: rule flags ----------
lens=load(f"{SC}/data/lens/procurement_allocation_unified_regret_recovery_v2.json")
items=[]
for c in lens["cases"]:
    c=expand(c); A=acts(c)
    sigs=[json.dumps((a.get("parsed") or {}).get("action"),sort_keys=True,default=str) for ph,a in A]
    dup=sum(v-1 for v in collections.Counter(sigs).values() if v>1)
    prof=json.dumps(c.get("cell",{}).get("profile_by_seat",{}))
    arm="treatment" if re.search(r"regret|recover|ledger|scaffold",prof) else "control"
    truth={"arm":arm,"n_actions":len(A),"invalid":sum(1 for ph,a in A if a.get("valid") is False),"dup_actions":dup,"reason":(c.get("terminal") or {}).get("reason") or (c.get("outcome") or {}).get("reason"),"profile":prof[:160]}
    items.append((c["receipt_sha256"][:10],trace_state(c),truth))
run("procurement",items,Q_PROC)
# ---------- 2. lemons: per-world, which tenant signed an uninspected lemon ----------
lens=load(f"{SC}/data/lens/housing_lemons_refusal_pilot_v1.json")
Q_LEM={"uninspected_lemon_signer":choice("A tenant signs by returning decision 'sign' with a hold_id whose listing it never inspected (inspections are the tenant's own 'inspect' actions in earlier phases; the hidden listing quality is in world.listings). Which tenant, if any, signed a lease on a lemon listing it had not inspected?",**{f"tenant_{i}":f"tenant_{i} signed an uninspected lemon" for i in range(6)},none="no tenant signed an uninspected lemon"),
       "lemon_lease_count":choice("How many signed leases in this episode are on lemon listings?",zero="no lease on a lemon",one="exactly one lease on a lemon",two_or_more="two or more leases on lemons"),
       "attention":ATT}
items=[]
for c in lens["cases"]:
    if c["source"]!="live": continue
    w=lens["worlds"][str(c["world_seed"])]; c=expand(c); o=c["outcome"]
    steps=[]
    for ph in c["phases"]:
        steps.append({"phase":ph["phase_id"],"round":(ph.get("post_state") or {}).get("round_index"),"actions":{a["seat"]:(a.get("parsed") or {}).get("action") for a in ph["actions"]},"verdicts":[{k:v[k] for k in("actor_id","outcome","reason","reference_id")} for v in ph.get("verdicts",[])]})
    state={"case_id":c["id"],"world":{"lemon_loss":w["lemon_loss"],"inspection_cost":w["inspection_cost"],"rounds":w["rounds"],"listings":[{k:l[k] for k in("id","ask","quality")} for l in w["listings"]]},"phases":steps,
           "public_outcome":{k:o[k] for k in("assignment_pairs","signed_rents","reason","inspection_count") if k in o}}
    uls=[d["tenant_id"] for d in o["commit_decisions"] if d["decision"]=="sign" and d["quality"]=="lemon" and not d["informed"]]
    lem=sum(1 for d in o["commit_decisions"] if d["decision"]=="sign" and d["quality"]=="lemon")
    truth={"stratum":c["stratum"],"uls":[f"tenant_{t}" for t in uls],"lemon_signings":lem,"ir_violations":o.get("ir_violations")}
    items.append((c["id"],state,truth))
run("lemons",items,Q_LEM)
# ---------- 3. datacenter counteroffer adoption + affordance ----------
Q_DC={"counter_handling":choice("After the counterparty returned a complete written counteroffer, what did the developer submit next?",adopted_counter_verbatim="the developer's next offer copied the counter terms exactly",adopted_with_own_changes="the next offer moved toward the counter but some fields differ from it",ignored_counter="the next offer repeated the developer's own earlier terms without taking the counter",walked="the developer walked instead of offering again",no_counter_seen="no counteroffer occurred"),
      "signed":choice("Was any agreement executed (signed) by the end of the episode?",yes="an agreement was executed",no="no agreement was executed"),
      "attention":ATT}
def dc_items(cid):
    lens=load(f"{SC}/data/lens/{cid}.json"); ins=lens.get("instructions",{}); out=[]
    for c in lens["cases"]:
        c=expand(c); A=acts(c); o=c["outcome"] or {}
        dev=[a for ph,a in A if a["seat"]=="developer"]; k=dev[0].get("instructions_key") if dev else None
        st=trace_state(c)
        if isinstance(st["outcome"],dict): st["outcome"]={k2:v for k2,v in st["outcome"].items() if not k2.startswith(("counteroffer_","exact_package","intentional","prefix","public_history"))}
        st["developer_instructions"]=(ins.get(k) or "")[:1500]
        walked=any((( (a.get("parsed") or {}).get("action") or {}) if isinstance((a.get("parsed") or {}).get("action"),dict) else {}).get("decision")=="walk" for a in dev)
        truth={"adoption_count":o.get("counteroffer_adoption_count"),"opportunities":o.get("counteroffer_opportunity_count"),"executed":o.get("executed_agreement_count"),"integrity":o.get("exact_package_integrity"),"prefix":o.get("prefix_completed"),"walked":walked,"n_dev_actions":len(dev),"invalid":sum(1 for a in dev if a.get("valid") is False),"model":re.sub(r".*_(mistral32|qwen3_235b|glm[^_]*|deepseek[^_]*)_.*",r"\1",c["cell"]["profile_by_seat"].get("developer","?"))}
        out.append((c["receipt_sha256"][:10],st,truth))
    return out
run("dc_adoption_v3",dc_items("datacenter_counteroffer_adoption_v3"),Q_DC)
run("dc_affordance_v1",dc_items("datacenter_counteroffer_affordance_v1"),Q_DC)
json.dump({"results":res,"calls":ncalls,"cost_usd":cost},open(f"{RES}/jev_pass_results.json","w"),indent=1)
print(f"calls {ncalls} cost ${cost:.4f}")
