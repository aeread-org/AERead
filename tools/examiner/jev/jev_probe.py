"""Can Jev take a trajectory?  Send real sealed trajectories (three state sizes) to the decisions
endpoint with questions whose answers the sealed data already knows, and measure acceptance,
latency, cost, and accuracy.  Key from the environment; never printed."""
import base64, gzip, json, os, sys, time, urllib.request, urllib.error, statistics as st
HERE=__import__("pathlib").Path(__file__).resolve().parent; RES=HERE/"results"
SC = sys.argv[1]; CID = "procurement_allocation_unified_regret_recovery_v2"; N = int(sys.argv[2]) if len(sys.argv) > 2 else 8
KEY = os.environ["OPENROUTER_API_KEY"]; URL = "https://openrouter.ai/api/alpha/decisions"; MODEL = "typesafe/jev-1.13"

def load(p):
    d = json.load(open(p)); return json.loads(gzip.decompress(base64.b64decode(d["payload"]))) if d.get("encoding") else d
def expand_obj(cur, prev, prev_any):
    out = {}
    for k, v in cur.items():
        if isinstance(v, dict) and v.get("$p") == 1 and len(v) == 1: out[k] = (prev or {}).get(k)
        elif isinstance(v, dict) and v.get("$pa") == 1 and len(v) == 1: out[k] = (prev_any or {}).get(k)
        elif isinstance(v, dict) and isinstance(v.get("$pp"), int) and "t" in v and len(v) == 2: out[k] = ((prev or {}).get(k) or [])[: v["$pp"]] + v["t"]
        elif isinstance(v, dict) and isinstance(v.get("$pe"), int) and "d" in v and "t" in v:
            base = list(((prev or {}).get(k) or [])[: v["$pe"]]); [base.__setitem__(int(i), x) for i, x in v["d"].items()]; out[k] = base + v["t"]
        else: out[k] = v
    return out
def expand(case):
    prev_by_seat, prev_any = {}, None
    for ph in case["phases"]:
        for a in ph["actions"]:
            o = a.get("observation")
            if isinstance(o, dict):
                a["observation"] = expand_obj(o, prev_by_seat.get(a["seat"]), prev_any); prev_by_seat[a["seat"]] = a["observation"]; prev_any = a["observation"]
    return case

lens = load(f"{SC}/data/lens/{CID}.json")
cases = [expand(c) for c in lens["cases"] if c.get("kind") == "sealed"][:N]

def acts(c): return [a for ph in c["phases"] for a in ph["actions"]]
def decision(a): p = a.get("parsed") or {}; act = p.get("action") if isinstance(p, dict) else None; return (act or {}).get("action") if isinstance(act, dict) else None
def truth(c):
    o = c.get("outcome") or {}; A = acts(c); decs = [decision(a) for a in A]
    award_idx = next((i for i, d in enumerate(decs) if d == "submit_award"), None)
    sampled_before = any(d == "request_sample" for d in decs[: award_idx]) if award_idx is not None else any(d == "request_sample" for d in decs)
    end = o.get("termination_reason") or o.get("decision") or "?"
    invalid = sum(1 for a in A if a.get("valid") is False)
    signal = ("signal_invalid_action" if invalid else "signal_deferred" if end == "deferred" else "signal_budget_exhausted" if end == "interaction_budget_exhausted"
              else "signal_skipped_verification" if (award_idx is not None and not sampled_before) else "signal_reference_beaten" if (o.get("regret_to_upper_bound_usd") is not None and o["regret_to_upper_bound_usd"] <= 1.0) else "none")
    return {"end": end if end in ("submitted", "deferred", "interaction_budget_exhausted", "invalid_action") else "submitted", "sampled_before_award": "yes" if sampled_before else "no", "feasible": "yes" if o.get("feasible") else "no", "signal": signal}

def state_card(c):
    o = c.get("outcome") or {}
    return {"campaign": CID, "case_id": c["case_id"], "profile": (c.get("cell") or {}).get("profile_by_seat"), "actions": [decision(a) for a in acts(c)],
            "invalid_actions": sum(1 for a in acts(c) for _ in [0] if a.get("valid") is False), "outcome": {k: o.get(k) for k in ("decision", "termination_reason", "feasible", "completed_kits", "contribution_margin_usd", "regret_to_upper_bound_usd", "upper_bound_usd", "cash_spend_usd", "elapsed_days")}}
def state_trace(c):
    s = state_card(c); s["steps"] = []
    for i, a in enumerate(acts(c)):
        p = a.get("parsed") or {}; act = p.get("action") if isinstance(p, dict) else None
        s["steps"].append({"step": i + 1, "seat": a["seat"], "action": act if isinstance(act, dict) else None, "valid": a.get("valid"), "failure_code": a.get("failure_code"), "raw_excerpt": (a.get("raw") or "")[:240]})
    return s
def state_full(c):
    s = state_trace(c)
    for i, a in enumerate(acts(c)): s["steps"][i]["observation"] = a.get("observation")
    return s

QUESTIONS = {
    "end": {"type": "choice", "instructions": "How did this procurement episode end? Read `outcome` and the action trace.",
            "criteria": {"submitted": "the buyer submitted an award", "deferred": "the buyer deferred without awarding", "interaction_budget_exhausted": "the action budget ran out before an award", "invalid_action": "the episode ended on an invalid action"}},
    "sampled_before_award": {"type": "choice", "instructions": "Did the buyer request a sample from at least one supplier before submitting the award?", "criteria": {"yes": "a request_sample action precedes the submit_award action", "no": "no request_sample action before the award, or no award"}},
    "feasible": {"type": "choice", "instructions": "Was the final award feasible according to the outcome?", "criteria": {"yes": "outcome.feasible is true", "no": "outcome.feasible is false or there was no award"}},
    "signal": {"type": "choice", "instructions": "Which single label best describes why an analyst should look at this trajectory, if at all? Prefer the most specific label that applies.",
               "criteria": {"signal_invalid_action": "at least one action was rejected by the environment", "signal_deferred": "the buyer deferred instead of awarding", "signal_budget_exhausted": "the buyer ran out of actions",
                            "signal_skipped_verification": "the buyer awarded without sampling any supplier first", "signal_reference_beaten": "regret to the upper bound is at most 1 USD, i.e. essentially optimal", "none": "an ordinary completed trajectory with nothing notable"}},
}
def call(state):
    payload = json.dumps({"model": MODEL, "state": state, "questions": QUESTIONS}).encode()
    req = urllib.request.Request(URL, data=payload, method="POST", headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json", "X-Title": "AERead examiner Jev probe"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90) as r: data = json.loads(r.read().decode()); err = None
    except urllib.error.HTTPError as e:
        try: body = e.read().decode()[:300]
        except Exception: body = ""
        data, err = None, f"HTTP {e.code} {body}"
    except Exception as e: data, err = None, f"{type(e).__name__}: {e}"
    return data, err, time.time() - t0, len(payload)

results = {}
for name, builder in (("card", state_card), ("trace", state_trace), ("full", state_full)):
    rows = []
    for c in cases:
        data, err, dt, nbytes = call(builder(c)); tr = truth(c)
        if err or not data or "answers" not in data: rows.append({"case": c["case_id"][-30:], "bytes": nbytes, "err": err or str(data)[:200], "s": round(dt, 2)}); continue
        ans = data["answers"]; usage = data.get("usage") or {}
        row = {"case": c["case_id"][-30:], "bytes": nbytes, "s": round(dt, 2), "tokens": usage.get("total_tokens") or usage.get("prompt_tokens"), "cost": usage.get("cost") or usage.get("total_cost")}
        for q in QUESTIONS: a = ans.get(q, {}); row[q] = (a.get("choice"), round(max(a.get("probabilities", {}).values() or [0]), 2), tr[q])
        rows.append(row)
    results[name] = rows
    ok = [r for r in rows if "err" not in r]
    print(f"\n=== state={name}: {len(ok)}/{len(rows)} accepted; median bytes {int(st.median([r['bytes'] for r in rows]))}; median latency {st.median([r['s'] for r in rows]):.2f}s" + (f"; tokens/call ~{st.median([r['tokens'] for r in ok if r.get('tokens')]) if any(r.get('tokens') for r in ok) else 'n/a'}" if ok else ""))
    for r in rows:
        if "err" in r: print(f"   {r['case']:30} {r['bytes']:7d}B  ERROR {r['err'][:120]}"); continue
        print(f"   {r['case']:30} {r['bytes']:7d}B {r['s']:5.2f}s  " + "  ".join(f"{q}={r[q][0]}({r[q][1]}){'✓' if r[q][0]==r[q][2] else '✗ want '+str(r[q][2])}" for q in QUESTIONS))
    if ok:
        for q in QUESTIONS: print(f"   accuracy {q:22} {sum(1 for r in ok if r[q][0]==r[q][2])}/{len(ok)}")
json.dump(results, open(f"{RES}/jev_probe_results.json", "w"), indent=1)
