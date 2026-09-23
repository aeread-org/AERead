import json,sys,collections,concurrent.futures as cf
HERE=__import__("pathlib").Path(__file__).resolve().parent; RES=HERE/"results"
SC=sys.argv[1]; sys.path.insert(0,str(HERE))
from jev_lib import load, expand, call
from jev_q import Q
L=load(f"{SC}/data/lens/housing_lemons_refusal_pilot_v1.json")
jobs=[]
for seed in ("100000","100025","100030"):
    for src in ("inspect_then_sign","sign_anything"):
        c=next((x for x in L["cases"] if x["source"]==src and str(x["world_seed"])==seed and x["replicate"]==0),None)
        if not c: continue
        c=expand(c); w=L["worlds"][seed]; o=c["outcome"]; steps=[]
        for ph in c["phases"]:
            rnd=(ph.get("post_state") or {}).get("round_index")
            for a in ph["actions"]:
                steps.append({"step":len(steps)+1,"round":rnd,"phase":ph["phase_id"],"seat":a["seat"],"action":(a.get("parsed") or {}).get("action"),"verdict":next(({"outcome":v["outcome"],"reason":v["reason"]} for v in ph.get("verdicts",[]) if f"tenant_{v['actor_id']}"==a["seat"] or f"landlord_{v['actor_id']}"==a["seat"]),None)})
        world={"lemon_loss":w["lemon_loss"],"inspection_cost":w["inspection_cost"],"rounds":w["rounds"],"listings":[{k:l[k] for k in("id","ask","quality")} for l in w["listings"]]}
        pub={k:o[k] for k in("assignment_pairs","signed_rents","reason","inspection_count") if k in o}
        for s in steps:
            if not s["seat"].startswith("tenant_") or not s["action"] or s["action"].get("decision")=="pass": continue   # only positive actions
            state={"family":"housing lemons (tenants inspect, offer, then sign or walk; hidden listing quality)","case_id":c["id"],"world":world,"trajectory":steps,"focal_step":s["step"],"focal_action":s,"outcome":pub}
            jobs.append((src,seed,s["phase"],s["action"]["decision"],state))
def work(j):
    src,seed,ph,dec,state=j; data,err,nb=call(state,Q)
    return {"src":src,"seed":seed,"phase":ph,"decision":dec,"err":err,"jev":None if err else {q:(data["answers"][q]["choice"],round(max(data["answers"][q]["probabilities"].values()),2)) for q in Q},"cost":0 if err else float((data.get("usage") or {}).get("cost") or 0)}
with cf.ThreadPoolExecutor(8) as ex: rows=list(ex.map(work,jobs))
json.dump(rows,open(f"{RES}/jev_scripted_results.json","w"),indent=1)
rows=[r for r in rows if not r["err"]]; print("scripted actions",len(rows),"cost $%.4f"%sum(r["cost"] for r in rows))
live=[r for r in json.load(open(f"{RES}/jev_actions_results.json")) if r["family"]=="lemons" and "err" not in r and r["truth"]["decision"]!="pass"]
def tab(rs,lab):
    for dec in("inspect","offer","sign","walk"):
        x=[r for r in rs if r["decision"]==dec] if lab!="live" else [r for r in rs if r["truth"]["decision"]==dec]
        if x: print(f"  {lab:18} {dec:8} n={len(x):3} agency={dict(collections.Counter(r['jev']['agency'][0] for r in x))} mean p={sum(r['jev']['agency'][1] for r in x)/len(x):.2f}")
for src in("inspect_then_sign","sign_anything"): tab([r for r in rows if r["src"]==src],src)
tab(live,"live")
