import base64, gzip, json, os, sys, time, urllib.request, urllib.error, statistics as st, collections
HERE=__import__("pathlib").Path(__file__).resolve().parent; RES=HERE/"results"
sys.argv=[sys.argv[0], sys.argv[1], "12"]
exec(open(HERE/"jev_probe.py").read().split("results = {}")[0])  # reuse loaders, builders, truth, call
# 1. response metadata / cost fields
data, err, dt, nb = call(state_card(cases[0])); print("response keys:", [k for k in (data or {}) if k!="answers"], "| usage:", json.dumps((data or {}).get("usage"))[:200], "| err:", err)
# 2. harder, verifiable questions on trace and full states
def hard_truth(c):
    A=acts(c); sup=collections.OrderedDict()
    for a in A:
        p=a.get("parsed") or {}; act=p.get("action") if isinstance(p,dict) else None
        if isinstance(act,dict) and act.get("supplier_id"): sup.setdefault(act["supplier_id"],0)
    sampled=set(); awarded=None; nq=0
    for a in A:
        p=a.get("parsed") or {}; act=p.get("action") if isinstance(p,dict) else None
        if not isinstance(act,dict): continue
        if act.get("action")=="request_sample": sampled.add(act.get("supplier_id"))
        if act.get("action")=="request_quote": nq+=1
        if act.get("action")=="submit_award":
            lines=act.get("award_lines") or []; awarded=(lines[0].get("supplier_id") if lines and isinstance(lines[0],dict) else None)
    return {"suppliers":list(sup), "awarded":awarded, "n_sampled":str(min(len(sampled),4)), "n_quotes":str(min(nq,5))}
def hard_questions(c):
    t=hard_truth(c); sups=t["suppliers"] or ["unknown"]
    return {
      "awarded_supplier":{"type":"choice","instructions":"Which supplier received the (first) award line in submit_award? Answer none if there was no award.","criteria":{**{s:f"supplier id {s}" for s in sups},"none":"no award was submitted"}},
      "n_sampled":{"type":"choice","instructions":"How many distinct suppliers did the buyer request a sample from over the whole trajectory?","criteria":{"0":"no samples requested","1":"one supplier sampled","2":"two suppliers sampled","3":"three suppliers sampled","4":"four or more"}},
      "n_quotes":{"type":"choice","instructions":"How many request_quote actions did the buyer take in total?","criteria":{str(i):f"{i} quote request{'s' if i!=1 else ''}" for i in range(5)}|{"5":"five or more"}},
    }
def call_q(state, questions):
    payload=json.dumps({"model":MODEL,"state":state,"questions":questions}).encode()
    req=urllib.request.Request(URL,data=payload,method="POST",headers={"Authorization":"Bearer "+KEY,"Content-Type":"application/json","X-Title":"AERead examiner Jev probe"})
    t0=time.time()
    try:
        with urllib.request.urlopen(req,timeout=120) as r: return json.loads(r.read().decode()), None, time.time()-t0, len(payload)
    except urllib.error.HTTPError as e:
        try: body=e.read().decode()[:200]
        except Exception: body=""
        return None, f"HTTP {e.code} {body}", time.time()-t0, len(payload)
    except Exception as e: return None, f"{type(e).__name__}: {e}", time.time()-t0, len(payload)
for name,builder in (("trace",state_trace),("full",state_full)):
    acc=collections.Counter(); n=0; lat=[]
    for c in cases:
        t=hard_truth(c); q=hard_questions(c); data,err,dt,nb=call_q(builder(c),q)
        if err: print("  ",name,c["case_id"][-24:],"ERR",err[:100]); continue
        n+=1; lat.append(dt)
        for k in q:
            want = t["awarded"] if k=="awarded_supplier" else t[k]; want = want or "none"
            got=data["answers"][k]["choice"]; acc[k]+= (got==want)
            if got!=want: print(f"     miss {name} {c['case_id'][-24:]} {k}: got {got} want {want} p={max(data['answers'][k]['probabilities'].values()):.2f}")
    print(f"=== hard questions, state={name}: n={n}, median latency {st.median(lat):.2f}s, accuracy " + ", ".join(f"{k} {v}/{n}" for k,v in acc.items()))
# 3. size limit: concatenate full trajectories
for k in (2,4,8):
    big={"trajectories":[state_full(c) for c in cases[:k]]}
    data,err,dt,nb=call_q(big,{"n":{"type":"choice","instructions":"How many trajectories are in `trajectories`?","criteria":{str(i):f"{i}" for i in (1,2,4,8,16)}}})
    print(f"=== size probe: {k} trajectories, {nb/1000:.0f}KB (~{nb//4} tokens): " + (f"ERROR {err[:120]}" if err else f"accepted in {dt:.2f}s, answer {data['answers']['n']['choice']} p={max(data['answers']['n']['probabilities'].values()):.2f}"))
