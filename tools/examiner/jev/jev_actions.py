"""Action-level Jev pass: agency (deliberate / procedural / copy / inaction) and outcome effect per focal action, with rule-derived truth."""
import json, sys, re, collections, concurrent.futures as cf
HERE=__import__("pathlib").Path(__file__).resolve().parent; RES=HERE/"results"
SC=sys.argv[1]; sys.path.insert(0,str(HERE))
from jev_lib import load, expand, acts, compact, call
def choice(instr,**crit): return {"type":"choice","instructions":instr,"criteria":crit}
Q={"agency":choice("Look only at the focal action (focal_step). How much genuine decision did the agent exercise in it?",
      deliberate_choice="the agent chose among genuinely different options using information in the trajectory (which counterparty to engage, whether to counter, whether to walk, what quantity to award)",
      procedural_default="the step follows the prescribed procedure or the safest default and needed no real decision",
      copy_repeat="the action copies terms it was handed, repeats an earlier action, or restates the agent's own previous action",
      null_inaction="a pass, no-op, or an action with nothing to decide"),
   "outcome_effect":choice("Given the whole trajectory and its outcome, what part did the focal action play in the final outcome?",
      decisive="it directly set or ended the outcome: a signing, an award, a defer, a walk, an accepted counter, or a pass that let a held offer lapse",
      enabling="a prerequisite the final outcome relied on: a quote or sample from a supplier that was later awarded, an offer that produced the hold later signed, an inspection of a listing the agent later signed or walked from",
      informational_unused="it gathered information or made an offer that the final outcome did not use",
      none="no effect on the outcome"),
   "counterfactual":choice("If the focal action were replaced by the safest default for that step (pass, skip, or copying what was handed), would the final outcome change?",yes="the outcome would change materially",marginally="only a small change",no="the outcome would be the same")}
jobs=[]   # (family,key,state,truth)
# ---------------- procurement ----------------
P=load(f"{SC}/data/lens/procurement_allocation_unified_regret_recovery_v2.json"); TREAT="3c8810960987"
for c in P["cases"]:
    c=expand(c); A=acts(c); arm="treatment" if A[0][1].get("instructions_key")==TREAT else "control"
    award=(c.get("outcome") or {}).get("award_lines") or (c.get("terminal") or {}).get("award_lines") or []
    last=[ph for ph,a in A][-1]; sub=[(a.get("parsed") or {}).get("action") for ph,a in A if ((a.get("parsed") or {}).get("action") or {}).get("action")=="submit_award"]
    if sub: award=sub[-1].get("award_lines") or award
    awarded_sup={re.sub(r"^offer_(supplier_[0-9a-f]+)_v\d+$",r"\1",l.get("offer_id","")) for l in award}
    steps=[]
    for i,(ph,a) in enumerate(A):
        act=(a.get("parsed") or {}).get("action") or {}; steps.append({"step":i+1,"action":compact(act,700),"verdict":compact(ph.get("consequences"),300)})
    out=c.get("outcome") or {}; pub={k:out.get(k) for k in("decision","completed_kits","contribution_margin_usd","termination_reason","feasible_award","violations")}
    obj=c["world"]["payload"]["objective"]; policy=c["world"]["payload"]["policy"]
    for i,(ph,a) in enumerate(A):
        act=(a.get("parsed") or {}).get("action") or {}; k=act.get("action"); cons=ph.get("consequences") or {}
        sup=act.get("supplier_id") or re.sub(r"^offer_(supplier_[0-9a-f]+)_v\d+$",r"\1",act.get("offer_id","") or "") or re.sub(r"^offer_(supplier_[0-9a-f]+)_v\d+$",r"\1",cons.get("offer_id","") or "")
        if k in("submit_award","defer"): eff="decisive"
        elif k=="counter_offer": eff="decisive" if cons.get("accepted") else "informational_unused"
        elif k=="check_award": eff="informational"   # accept enabling or informational_unused
        elif k in("request_quote","request_sample","send_inquiry"): eff="enabling" if sup in awarded_sup else "informational_unused"
        else: eff="?"
        state={"family":"procurement (buyer sourcing episode)","case_id":c["case_id"],"arm_note":"the buyer prompt may prescribe a fixed worksheet","objective":compact(obj,600),"policy":compact(policy,400),"trajectory":steps,"focal_step":i+1,"focal_action":steps[i],"outcome":pub}
        jobs.append(("procurement",f"{c['receipt_sha256'][:10]}#{i+1}",state,{"arm":arm,"kind":k,"supplier":sup,"awarded":sup in awarded_sup,"effect":eff,"accepted":cons.get("accepted")}))
# ---------------- lemons: tenant actions in 6 worlds ----------------
L=load(f"{SC}/data/lens/housing_lemons_refusal_pilot_v1.json")
WORLDS=["live__w100000__r0","live__w100025__r0","live__w100025__r1","live__w100001__r0","live__w100012__r1","live__w100030__r0"]
for cid in WORLDS:
    c=expand(next(x for x in L["cases"] if x["id"]==cid)); w=L["worlds"][str(c["world_seed"])]; o=c["outcome"]
    # A hold lives from the respond phase that grants it to the next commit phase. Do not key holds by
    # post_state.round_index: a commit phase's post_state already carries the NEXT round (fixed 2026-09-22).
    steps=[]; step_holds=[]; cur_holds={}
    for ph in c["phases"]:
        rnd=(ph.get("post_state") or {}).get("round_index")
        if ph["phase_id"]=="respond": cur_holds={f"tenant_{h['tenant_id']}":h for h in (ph.get("holds") or [])}
        for a in ph["actions"]:
            steps.append({"step":len(steps)+1,"round":rnd,"phase":ph["phase_id"],"seat":a["seat"],"action":(a.get("parsed") or {}).get("action"),"verdict":next(({"outcome":v["outcome"],"reason":v["reason"]} for v in ph.get("verdicts",[]) if f"tenant_{v['actor_id']}"==a["seat"] or f"landlord_{v['actor_id']}"==a["seat"]),None)})
            step_holds.append(dict(cur_holds))
        if ph["phase_id"]=="commit": cur_holds={}
    # per-tenant later transactions for enabling labels
    signed={(d["tenant_id"],d["listing_id"]):d["decision"] for d in o["commit_decisions"]}
    pub={k:o[k] for k in("assignment_pairs","signed_rents","reason","inspection_count")}
    world={"lemon_loss":w["lemon_loss"],"inspection_cost":w["inspection_cost"],"rounds":w["rounds"],"listings":[{k:l[k] for k in("id","ask","quality")} for l in w["listings"]]}
    for s in steps:
        if not s["seat"].startswith("tenant_"): continue
        t=int(s["seat"].split("_")[1]); act=s["action"] or {}; dec=act.get("decision"); ph=s["phase"]
        hold=step_holds[s["step"]-1].get(s["seat"]) if ph=="commit" else None
        if ph=="commit":
            eff="decisive" if dec in("sign","walk") or (dec=="pass" and hold) else "none"
            ag="null_inaction" if dec=="pass" else ("deliberate_choice" if dec=="walk" else None)
        elif ph=="contact":
            eff=("enabling" if dec=="offer" and (t,act.get("listing_id")) in signed else ("informational_unused" if dec=="offer" else "none")); ag="null_inaction" if dec=="pass" else None
        else:
            eff=("enabling" if dec=="inspect" and (t,act.get("listing_id")) in signed else ("informational_unused" if dec=="inspect" else "none")); ag="null_inaction" if dec=="pass" else None
        state={"family":"housing lemons (tenants inspect, offer, then sign or walk; hidden listing quality)","case_id":cid,"world":world,"trajectory":steps,"focal_step":s["step"],"focal_action":s,"held_offer_for_focal_tenant":hold,"outcome":pub}
        jobs.append(("lemons",f"{cid}#{s['step']}",state,{"phase":ph,"decision":dec,"had_hold":bool(hold),"effect":eff,"agency":ag,"tenant":s["seat"]}))
# ---------------- datacenter developer actions ----------------
for cid in("datacenter_counteroffer_adoption_v3","datacenter_counteroffer_affordance_v1"):
    D=load(f"{SC}/data/lens/{cid}.json"); ins=D.get("instructions",{})
    for c in D["cases"]:
        c=expand(c); A=acts(c); o=c.get("outcome") or {}
        steps=[{"step":i+1,"phase":ph["phase_id"],"seat":a["seat"],"action":compact((a.get("parsed") or {}).get("action"),900),"valid":a.get("valid"),"failure_code":a.get("failure_code"),"verdict":compact(ph.get("consequences"),200)} for i,(ph,a) in enumerate(A)]
        dev=[(i,ph,a) for i,(ph,a) in enumerate(A) if a["seat"]=="developer"]; key=dev[0][2].get("instructions_key") if dev else None
        pub={"executed_agreement_count":o.get("executed_agreement_count"),"finished":(c.get("terminal") or {}).get("finished")}
        prev_dev_terms=None; last_counter=None
        for i,(ph,a) in enumerate(A):
            act=(a.get("parsed") or {}).get("action") or {}
            if a["seat"]!="developer":
                if isinstance(act,dict) and act.get("decision")=="counter": last_counter=act.get("terms")
                continue
            terms=act.get("terms") if isinstance(act,dict) else None; dec=act.get("decision") if isinstance(act,dict) else None
            if a.get("valid") is False: ag,eff="null_inaction","decisive"
            elif dec=="offer" and last_counter is not None and terms==last_counter: ag,eff="copy_repeat","decisive"          # instructed adoption
            elif dec=="offer" and prev_dev_terms is not None and terms==prev_dev_terms: ag,eff="copy_repeat","decisive"      # self-copy, ignores counter
            elif dec=="offer" and last_counter is None: ag,eff="copy_repeat","enabling"                                      # starter terms
            elif dec=="offer": ag,eff="deliberate_choice","decisive"
            elif dec in("sign","walk"): ag,eff="procedural_default" if dec=="sign" else "deliberate_choice","decisive"
            else: ag,eff="?","?"
            sub="instructed_copy" if (dec=="offer" and last_counter is not None and terms==last_counter) else ("self_copy" if (dec=="offer" and prev_dev_terms is not None and terms==prev_dev_terms) else ("starter" if dec=="offer" and last_counter is None else dec))
            state={"family":"datacenter counteroffer adoption (developer vs scripted counterparty)","case_id":c["case_id"],"developer_instructions":(ins.get(key) or "")[:1500],"trajectory":steps,"focal_step":i+1,"focal_action":steps[i],"outcome":pub}
            jobs.append((cid.replace("datacenter_counteroffer_",""),f"{c['receipt_sha256'][:10]}#{i+1}",state,{"decision":dec,"valid":a.get("valid"),"sub":sub,"agency":ag,"effect":eff,"model":re.sub(r".*_(mistral32|qwen3_235b)_.*",r"\1",c["cell"]["profile_by_seat"].get("developer","?"))}))
            if terms is not None: prev_dev_terms=terms
print("jobs:",collections.Counter(j[0] for j in jobs),"total",len(jobs))
if "--truth-only" in sys.argv:   # rebuild the rule labels without calling Jev and compare with the saved run
    saved={r["key"]:r["truth"] for r in json.load(open(RES/"jev_actions_results.json"))}
    diff=[(k,saved.get(k),t) for f,k,st_,t in jobs if saved.get(k)!=t]
    print(f"rule labels rebuilt: {len(jobs)}; differ from saved: {len(diff)}"); [print("  ",d) for d in diff[:10]]
    sys.exit(1 if diff else 0)
def work(j):
    fam,key,state,truth=j; data,err,nb=call(state,Q)
    if err: return {"family":fam,"key":key,"err":err,"truth":truth}
    return {"family":fam,"key":key,"bytes":nb,"truth":truth,"cost":float((data.get("usage") or {}).get("cost") or 0),"jev":{q:(data["answers"][q]["choice"],round(max(data["answers"][q]["probabilities"].values()),2)) for q in Q}}
with cf.ThreadPoolExecutor(8) as ex: rows=list(ex.map(work,jobs))
errs=[r for r in rows if "err" in r]; print("errors",len(errs),[e["err"][:80] for e in errs[:3]]); print("cost $%.4f"%sum(r.get("cost",0) for r in rows))
json.dump(rows,open(f"{RES}/jev_actions_results.json","w"),indent=1)
