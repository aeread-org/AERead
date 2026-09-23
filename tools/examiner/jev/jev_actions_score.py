import json,sys,collections,statistics as st
HERE=__import__("pathlib").Path(__file__).resolve().parent; RES=HERE/"results"
SC=sys.argv[1]; rows=[r for r in json.load(open(f"{RES}/jev_actions_results.json")) if "err" not in r]
def C(rs,f): return dict(collections.Counter(f(r) for r in rs))
def pct(a,b): return f"{a}/{b} ({100*a/b:.0f}%)" if b else "-"
def eff_ok(r):
    t=r["truth"]["effect"]; j=r["jev"]["outcome_effect"][0]
    if t=="informational": return j in("enabling","informational_unused")
    if t=="informational_unused": return j in("informational_unused","none")
    if t=="none": return j in("none","informational_unused")
    return j==t
print("total answered",len(rows),"cost $%.4f"%sum(r["cost"] for r in rows))
# ---------------- procurement ----------------
P=[r for r in rows if r["family"]=="procurement"]; print(f"\n=== PROCUREMENT {len(P)} buyer actions")
print(" outcome_effect agreement with rule:",pct(sum(eff_ok(r) for r in P),len(P)))
for k in("submit_award","defer","counter_offer","check_award","request_quote","request_sample"):
    rs=[r for r in P if r["truth"]["kind"]==k]
    if rs: print(f"  {k:15} n={len(rs):3} rule={C(rs,lambda r:r['truth']['effect'])} jev_effect={C(rs,lambda r:r['jev']['outcome_effect'][0])} agree {pct(sum(eff_ok(r) for r in rs),len(rs))} | agency={C(rs,lambda r:r['jev']['agency'][0])} | cf_yes={sum(r['jev']['counterfactual'][0]=='yes' for r in rs)}")
print(" quote/sample split by whether the supplier was awarded:")
for aw in(True,False):
    rs=[r for r in P if r["truth"]["kind"] in("request_quote","request_sample") and r["truth"]["awarded"]==aw]
    print(f"   awarded={aw!s:5} n={len(rs):3} jev_effect={C(rs,lambda r:r['jev']['outcome_effect'][0])} cf={C(rs,lambda r:r['jev']['counterfactual'][0])}")
print(" agency by arm:")
for arm in("control","treatment"):
    rs=[r for r in P if r["truth"]["arm"]==arm]; n=len(rs)
    ag=collections.Counter(r["jev"]["agency"][0] for r in rs); print(f"   {arm:9} n={n:3} "+"  ".join(f"{k} {v} ({100*v/n:.0f}%)" for k,v in ag.most_common()))
print(" agency × rule effect (all procurement):")
ct=collections.Counter((r["jev"]["agency"][0],r["truth"]["effect"]) for r in P)
for (a,e),v in sorted(ct.items()): print(f"   {a:18} {e:20} {v}")
print(" counters:",[(r["key"],r["truth"]["arm"],"accepted" if r["truth"]["accepted"] else "rejected",r["jev"]["agency"][0],r["jev"]["outcome_effect"][0],r["jev"]["counterfactual"][0]) for r in P if r["truth"]["kind"]=="counter_offer"])
# deliberate share per receipt, by arm
per=collections.defaultdict(list)
for r in P: per[(r["truth"]["arm"],r["key"].split("#")[0])].append(r["jev"]["agency"][0]=="deliberate_choice")
for arm in("control","treatment"):
    xs=[sum(v)/len(v) for (a,k),v in per.items() if a==arm]; print(f" share of deliberate actions per receipt, {arm}: mean {st.mean(xs):.2f} min {min(xs):.2f} max {max(xs):.2f}")
# ---------------- lemons ----------------
L=[r for r in rows if r["family"]=="lemons"]; print(f"\n=== LEMONS {len(L)} tenant actions in 6 worlds")
print(" outcome_effect agreement with rule:",pct(sum(eff_ok(r) for r in L),len(L)))
for ph in("inspect","contact","commit"):
    for dec in("inspect","offer","pass","sign","walk"):
        rs=[r for r in L if r["truth"]["phase"]==ph and r["truth"]["decision"]==dec]
        if rs: print(f"  {ph:8}{dec:8} n={len(rs):3} rule={C(rs,lambda r:r['truth']['effect'])} jev_effect={C(rs,lambda r:r['jev']['outcome_effect'][0])} agree {pct(sum(eff_ok(r) for r in rs),len(rs))} | agency={C(rs,lambda r:r['jev']['agency'][0])} | cf={C(rs,lambda r:r['jev']['counterfactual'][0])}")
hp=[r for r in L if r["truth"]["phase"]=="commit" and r["truth"]["decision"]=="pass" and r["truth"]["had_hold"]]
print(" commit-pass WITH a held offer (refusal by inaction):",len(hp),[(r["key"],r["jev"]["agency"],r["jev"]["outcome_effect"],r["jev"]["counterfactual"]) for r in hp])
wk=[r for r in L if r["truth"]["decision"]=="walk"]; print(" walks:",[(r["key"],r["jev"]["agency"],r["jev"]["outcome_effect"],r["jev"]["counterfactual"]) for r in wk])
sg=[r for r in L if r["truth"]["decision"]=="sign"]; print(" signs: agency",C(sg,lambda r:r["jev"]["agency"][0]),"effect",C(sg,lambda r:r["jev"]["outcome_effect"][0]),"cf",C(sg,lambda r:r["jev"]["counterfactual"][0]))
npass=[r for r in L if r["truth"]["decision"]=="pass" and not r["truth"]["had_hold"]]; print(" passes without a hold: agency",C(npass,lambda r:r["jev"]["agency"][0]),"effect",C(npass,lambda r:r["jev"]["outcome_effect"][0]))
# enabling inspections: did Jev link inspection -> later sign?
ins=[r for r in L if r["truth"]["decision"]=="inspect"]; print(" inspections: rule enabling",sum(r["truth"]["effect"]=="enabling" for r in ins),"jev enabling",sum(r["jev"]["outcome_effect"][0]=="enabling" for r in ins),"| confusion",C(ins,lambda r:(r["truth"]["effect"],r["jev"]["outcome_effect"][0])))
# ---------------- datacenter ----------------
for fam in("adoption_v3","affordance_v1"):
    D=[r for r in rows if r["family"]==fam]; print(f"\n=== DATACENTER {fam} {len(D)} developer actions")
    print(" outcome_effect agreement:",pct(sum(eff_ok(r) for r in D),len(D)))
    for sub in("starter","instructed_copy","self_copy","sign","walk",None):
        rs=[r for r in D if r["truth"]["sub"]==sub]
        if rs: print(f"  {str(sub):16} n={len(rs):3} rule_agency={C(rs,lambda r:r['truth']['agency'])} jev_agency={C(rs,lambda r:r['jev']['agency'][0])} jev_effect={C(rs,lambda r:r['jev']['outcome_effect'][0])} cf={C(rs,lambda r:r['jev']['counterfactual'][0])}")
    ic=[r for r in D if r["truth"]["sub"]=="instructed_copy"]; sc=[r for r in D if r["truth"]["sub"]=="self_copy"]
    print(f"  instructed copy vs self copy: jev copy_repeat rate {pct(sum(r['jev']['agency'][0]=='copy_repeat' for r in ic),len(ic))} vs {pct(sum(r['jev']['agency'][0]=='copy_repeat' for r in sc),len(sc))}; cf yes {pct(sum(r['jev']['counterfactual'][0]=='yes' for r in ic),len(ic))} vs {pct(sum(r['jev']['counterfactual'][0]=='yes' for r in sc),len(sc))}")
    for m in("mistral32","qwen3_235b"):
        rs=[r for r in D if r["truth"]["model"]==m]; print(f"   {m:10} sub={C(rs,lambda r:r['truth']['sub'])} jev_agency={C(rs,lambda r:r['jev']['agency'][0])}")
# ---------------- overall: agency x effect ----------------
print("\n=== ALL: Jev agency × Jev outcome_effect")
ct=collections.Counter((r["jev"]["agency"][0],r["jev"]["outcome_effect"][0]) for r in rows)
for (a,e),v in sorted(ct.items(),key=lambda x:-x[1]): print(f"   {a:18} {e:20} {v}")
print(" deliberate AND (decisive|enabling):",sum(1 for r in rows if r["jev"]["agency"][0]=="deliberate_choice" and r["jev"]["outcome_effect"][0] in("decisive","enabling")),"of",len(rows))
print(" counterfactual yes by rule effect:",{e:pct(sum(r["jev"]["counterfactual"][0]=="yes" for r in rows if r["truth"]["effect"]==e),sum(1 for r in rows if r["truth"]["effect"]==e)) for e in("decisive","enabling","informational","informational_unused","none")})
