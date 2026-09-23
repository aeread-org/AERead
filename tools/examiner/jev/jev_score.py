import json,gzip,base64,collections,statistics as st,sys
HERE=__import__("pathlib").Path(__file__).resolve().parent; RES=HERE/"results"
SC=sys.argv[1]
def load(p):
    d=json.load(open(p)); return json.loads(gzip.decompress(base64.b64decode(d["payload"]))) if d.get("encoding") else d
def mean(xs): xs=[x for x in xs if x is not None]; return round(st.mean(xs),2) if xs else None
def C(rows,f): return dict(collections.Counter(f(r) for r in rows))
d=json.load(open(f"{RES}/jev_pass_results.json")); R=d["results"]
# ---------- procurement: arm from instructions key, join to results rows ----------
l=load(f"{SC}/data/lens/procurement_allocation_unified_regret_recovery_v2.json")
TREAT="3c8810960987"
res=load(f"{SC}/data/results/procurement_allocation_unified_regret_recovery_v2.json")
tab=[t for t in res["tables"] if (t.get("rows") or [{}])[0].get("arm")][0]["rows"]
P=R["procurement"]; used=set(); mism=0
for row in P:
    c=next(c for c in l["cases"] if c["receipt_sha256"].startswith(row["key"]))
    k=[a for ph in c["phases"] for a in ph["actions"]][0].get("instructions_key"); arm="treatment" if k==TREAT else "control"
    seed=c["world"]["payload"]["interaction"]["sample_noise"]["seed"]
    cand=[i for i,t in enumerate(tab) if i not in used and t["environment_seed"]==seed and t["arm"]==arm and t["action_count"]==row["truth"]["n_actions"] and t["termination_reason"]==row["truth"]["reason"]]
    row["truth"].update(arm=arm,seed=seed)
    if cand: used.add(cand[0]); t=tab[cand[0]]; row["truth"].update(regret=t["regret_to_upper_bound_usd"],margin=t["contribution_margin_usd"],decision=t["decision"],kits=t["completed_kits"])
    else: mism+=1
print(f"=== PROCUREMENT unified_regret_recovery_v2: {len(P)} receipts, join to results rows: {len(P)-mism}/{len(P)}")
print(" rule flags: invalid actions",sum(r["truth"]["invalid"] for r in P),"| duplicate actions",sum(r["truth"]["dup_actions"] for r in P),"| termination",C(P,lambda r:r["truth"]["reason"]))
for a in("control","treatment"):
    rs=[r for r in P if r["truth"]["arm"]==a]
    print(f" {a:9} n={len(rs)} actions {mean(r['truth']['n_actions'] for r in rs)} regret {mean(r['truth'].get('regret') for r in rs)} | attention {C(rs,lambda r:r['jev']['attention'][0])} | primary_issue {C(rs,lambda r:r['jev']['primary_issue'][0])} | contradiction {C(rs,lambda r:r['jev']['claims_contradicted'][0])}")
print(" actions by attention:",{k:mean(r['truth']['n_actions'] for r in P if r['jev']['attention'][0]==k) for k in("low","medium","high")})
print(" regret by attention:",{k:mean(r['truth'].get('regret') for r in P if r['jev']['attention'][0]==k) for k in("low","medium","high")})
print(" regret by primary_issue:",{k:mean(r['truth'].get('regret') for r in P if r['jev']['primary_issue'][0]==k) for k in("none","wasted_actions")})
print(" actions by primary_issue:",{k:mean(r['truth']['n_actions'] for r in P if r['jev']['primary_issue'][0]==k) for k in("none","wasted_actions")})
print(" deferred receipt:",[(r["key"],r["truth"]["arm"],r["jev"]) for r in P if r["truth"]["reason"]=="deferred"])
print(" flagged (high, then medium by confidence):")
for r in sorted(P,key=lambda r:(r['jev']['attention'][0]!='high',-r['jev']['attention'][1]))[:6]: print("   ",r["key"],r["truth"]["arm"],"seed",r["truth"]["seed"],"n",r["truth"]["n_actions"],"regret",r["truth"].get("regret"),"margin",r["truth"].get("margin"),r["jev"])
# ---------- lemons ----------
L=R["lemons"]; print(f"\n=== LEMONS housing_lemons_refusal_pilot_v1: {len(L)} live worlds")
print(" truth: worlds with an uninspected-lemon signer",sum(1 for r in L if r["truth"]["uls"]),"| lemon signings per world",C(L,lambda r:r["truth"]["lemon_signings"]),"| strata",C(L,lambda r:r["truth"]["stratum"]))
hit=[((r["jev"]["uninspected_lemon_signer"][0]=="none" and not r["truth"]["uls"]) or (r["jev"]["uninspected_lemon_signer"][0] in r["truth"]["uls"])) for r in L]
print(f" uninspected_lemon_signer correct: {sum(hit)}/{len(L)}; jev choices {C(L,lambda r:r['jev']['uninspected_lemon_signer'][0])}")
print("  true signer worlds:"); [print("    ",r["key"],r["truth"]["stratum"],"truth",r["truth"]["uls"],"jev",r["jev"]["uninspected_lemon_signer"],"count",r["jev"]["lemon_lease_count"],"att",r["jev"]["attention"]) for r in L if r["truth"]["uls"]]
fa=[(r["key"],r["jev"]["uninspected_lemon_signer"]) for r in L if r["jev"]["uninspected_lemon_signer"][0]!="none" and not r["truth"]["uls"]]; print("  false alarms:",len(fa),fa[:8])
m={0:"zero",1:"one"}; ok2=[(m.get(r["truth"]["lemon_signings"],"two_or_more")==r["jev"]["lemon_lease_count"][0]) for r in L]
print(f" lemon_lease_count correct: {sum(ok2)}/{len(L)}; jev {C(L,lambda r:r['jev']['lemon_lease_count'][0])}; confusion:",C(L,lambda r:(m.get(r['truth']['lemon_signings'],'two_or_more'),r['jev']['lemon_lease_count'][0])))
print(" attention",C(L,lambda r:r["jev"]["attention"][0]),"| non-low worlds:",[(r["key"][-9:],r["jev"]["attention"][0],"uls",len(r["truth"]["uls"]),"lem",r["truth"]["lemon_signings"],"ir",len(r["truth"]["ir_violations"] or [])) for r in L if r["jev"]["attention"][0]!="low"])
print(" confidence when right / wrong (signer q):",mean(r["jev"]["uninspected_lemon_signer"][1] for r,h in zip(L,hit) if h),mean(r["jev"]["uninspected_lemon_signer"][1] for r,h in zip(L,hit) if not h))
print(" ir_violations worlds:",sum(1 for r in L if r["truth"]["ir_violations"]),"| attention among them",C([r for r in L if r["truth"]["ir_violations"]],lambda r:r["jev"]["attention"][0]))
# ---------- datacenter ----------
for lab in ("dc_adoption_v3","dc_affordance_v1"):
    D=R[lab]; print(f"\n=== {lab}: {len(D)} receipts")
    print(" truth: adoption_count",C(D,lambda r:r["truth"]["adoption_count"]),"executed",C(D,lambda r:r["truth"]["executed"]),"walked",C(D,lambda r:r["truth"]["walked"]),"prefix_completed",C(D,lambda r:r["truth"]["prefix"]),"invalid dev actions",sum(r["truth"]["invalid"] for r in D))
    print(" jev: counter_handling",C(D,lambda r:r["jev"]["counter_handling"][0]),"| signed",C(D,lambda r:r["jev"]["signed"][0]),"| attention",C(D,lambda r:r["jev"]["attention"][0]))
    def exp(t):   # a receipt that ended on an invalid first action never received a counter (opportunities is None)
        if t["opportunities"] is None: return "no_counter_seen"
        return "walked" if t["walked"] else ("adopted_counter_verbatim" if (t["adoption_count"] or 0)>0 else "ignored_counter")
    okc=[exp(r["truth"])==r["jev"]["counter_handling"][0] for r in D]; oks=[("yes" if (r["truth"]["executed"] or 0)>0 else "no")==r["jev"]["signed"][0] for r in D]
    print(f" agreement with rule: counter_handling {sum(okc)}/{len(D)}, signed {sum(oks)}/{len(D)}; confusion",C(D,lambda r:(exp(r['truth']),r['jev']['counter_handling'][0])))
    for mdl in sorted(set(r["truth"]["model"] for r in D)):
        rs=[r for r in D if r["truth"]["model"]==mdl]; print(f"   {mdl:12} n={len(rs)} rule adoption>0 {sum((r['truth']['adoption_count'] or 0)>0 for r in rs)} executed>0 {sum((r['truth']['executed'] or 0)>0 for r in rs)} walked {sum(r['truth']['walked'] for r in rs)} | jev {C(rs,lambda r:r['jev']['counter_handling'][0])} att {C(rs,lambda r:r['jev']['attention'][0])}")
    print("  disagreements / high attention:")
    for r,o in zip(D,okc):
        if not o or r["jev"]["attention"][0]=="high": print("    ",r["key"],r["truth"]["model"],{k:r["truth"][k] for k in("adoption_count","opportunities","executed","walked","n_dev_actions","invalid")},r["jev"])
print(f"\ncalls {d['calls']}  cost ${d['cost_usd']:.4f}")
json.dump(d,open(f"{RES}/jev_pass_results.json","w"),indent=1)
