import json, sys, time
HERE=__import__("pathlib").Path(__file__).resolve().parent; RES=HERE/"results"
sys.argv=[sys.argv[0], sys.argv[1], "3"]
exec(open(HERE/"jev_probe.py").read().split("results = {}")[0])
# what does an award line look like? (was my truth extractor wrong?)
for c in cases[:1]:
    for a in acts(c):
        p=a.get("parsed") or {}; act=p.get("action") if isinstance(p,dict) else None
        if isinstance(act,dict) and act.get("action")=="submit_award": print("award_lines example:", json.dumps(act.get("award_lines"))[:300])
data, err, dt, nb = call(state_card(cases[0])); print("response keys:", [k for k in (data or {}) if k!="answers"]); print("usage:", json.dumps((data or {}).get("usage"))[:300]); print("other:", json.dumps({k:v for k,v in (data or {}).items() if k not in ("answers","usage")})[:300])
# bisect the state size limit with a padded full trajectory
base=state_full(cases[0]); q={"end":QUESTIONS["end"]}
def try_size(kb):
    s=dict(base); s["padding"]=("lorem ipsum dolor sit amet, consectetur adipiscing elit " * 4000)[: max(0, kb*1000 - len(json.dumps(base)))]
    payload=json.dumps({"model":MODEL,"state":s,"questions":q}).encode()
    req=urllib.request.Request(URL,data=payload,method="POST",headers={"Authorization":"Bearer "+KEY,"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=120) as r: json.loads(r.read().decode()); return True, len(payload)
    except urllib.error.HTTPError as e: return False, len(payload)
lo, hi = 55, 100
while hi-lo > 4:
    mid=(lo+hi)//2; ok,n=try_size(mid); print(f"  {mid}KB ({n//4} tok est): {'accepted' if ok else 'rejected'}"); lo, hi = (mid, hi) if ok else (lo, mid)
print(f"state limit between {lo}KB and {hi}KB of JSON (roughly {lo*250}-{hi*250} tokens)")
