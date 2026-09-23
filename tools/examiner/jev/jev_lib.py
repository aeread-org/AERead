"""Small Jev pass: typed triage questions over sealed trajectories of three campaigns."""
import base64, gzip, json, os, sys, time, urllib.request, urllib.error, statistics as st, collections
SC=sys.argv[1] if len(sys.argv)>1 else "."; KEY=os.environ.get("OPENROUTER_API_KEY",""); URL="https://openrouter.ai/api/alpha/decisions"; MODEL="typesafe/jev-1.13"
def load(p):
    d=json.load(open(p)); return json.loads(gzip.decompress(base64.b64decode(d["payload"]))) if d.get("encoding") else d
def expand_obj(cur,prev,prev_any):
    out={}
    for k,v in cur.items():
        if isinstance(v,dict) and v.get("$p")==1 and len(v)==1: out[k]=(prev or {}).get(k)
        elif isinstance(v,dict) and v.get("$pa")==1 and len(v)==1: out[k]=(prev_any or {}).get(k)
        elif isinstance(v,dict) and isinstance(v.get("$pp"),int) and "t" in v and len(v)==2: out[k]=((prev or {}).get(k) or [])[:v["$pp"]]+v["t"]
        elif isinstance(v,dict) and isinstance(v.get("$pe"),int) and "d" in v and "t" in v:
            base=list(((prev or {}).get(k) or [])[:v["$pe"]]); [base.__setitem__(int(i),x) for i,x in v["d"].items()]; out[k]=base+v["t"]
        else: out[k]=v
    return out
def expand(case):
    prev_by_seat,prev_any,prev_state={},None,None
    for ph in case.get("phases",[]):
        for a in ph["actions"]:
            o=a.get("observation")
            if isinstance(o,dict): a["observation"]=expand_obj(o,prev_by_seat.get(a["seat"]),prev_any); prev_by_seat[a["seat"]]=a["observation"]; prev_any=a["observation"]
        s=ph.get("post_state")
        if isinstance(s,dict): ph["post_state"]=expand_obj(s,prev_state,None); prev_state=ph["post_state"]
    t=case.get("terminal"); o=case.get("outcome")
    if isinstance(t,dict) and isinstance(o,dict):
        for k,v in list(t.items()):
            if isinstance(v,dict) and v.get("$o")==1: t[k]=o.get(k)
    return case
def acts(c): return [(ph,a) for ph in c.get("phases",[]) for a in ph["actions"]]
def compact(v,n=220):
    s=json.dumps(v,default=str); return json.loads(s) if len(s)<=n else s[:n]+"…"
def trace_state(c, extra=None):
    steps=[]
    for i,(ph,a) in enumerate(acts(c)[:60]):
        p=a.get("parsed") or {}; act=p.get("action") if isinstance(p,dict) else None
        steps.append({"step":i+1,"phase":ph["phase_id"],"seat":a["seat"],"action":compact(act,600) if act is not None else None,"valid":a.get("valid"),"failure_code":a.get("failure_code"),"model_text":(a.get("raw") or "")[:200],"environment_verdict":compact(ph.get("consequences"),300)})
    s={"case_id":c["case_id"],"steps":steps,"outcome":compact(c.get("outcome"),1200),"terminal":compact({k:v for k,v in (c.get("terminal") or {}).items() if k in ("reason","termination_reason","decision")},200)}
    if extra: s.update(extra)
    return s
def call(state,questions):
    payload=json.dumps({"model":MODEL,"state":state,"questions":questions}).encode()
    req=urllib.request.Request(URL,data=payload,method="POST",headers={"Authorization":"Bearer "+KEY,"Content-Type":"application/json","X-Title":"AERead examiner Jev pass"})
    try:
        with urllib.request.urlopen(req,timeout=120) as r: return json.loads(r.read().decode()),None,len(payload)
    except urllib.error.HTTPError as e:
        try: body=e.read().decode()[:160]
        except Exception: body=""
        return None,f"HTTP {e.code} {body}",len(payload)
    except Exception as e: return None,f"{type(e).__name__}: {e}",len(payload)
Q_PROC={
 "primary_issue":{"type":"choice","instructions":"Which single label best describes the most important problem in this buyer's trajectory, if any? Use the action trace, the environment verdicts and the outcome.","criteria":{
   "awarded_without_sample":"an award line names a supplier whose sample was never requested or verified",
   "awarded_without_formal_quote":"an award line relies on a verbal claim or listing rather than a formal quote",
   "ignored_capacity_or_moq":"the award quantity conflicts with a supplier's stated MOQ or capacity",
   "budget_exhausted":"the action budget ran out before an award",
   "deferred_with_feasible_path":"the buyer deferred although a feasible award looked available from the offers gathered",
   "unparseable_or_invalid_action":"at least one action was rejected by the environment",
   "wasted_actions":"the buyer repeated inquiries or requests that added no information",
   "none":"a competent trajectory with no notable problem"}},
 "claims_contradicted":{"type":"choice","instructions":"Did a formal quote or a verified sample contradict what a supplier claimed verbally or in its listing?","criteria":{"yes_and_buyer_adjusted":"a contradiction appeared and the buyer changed course","yes_but_buyer_ignored":"a contradiction appeared and the buyer proceeded as if it had not","no_contradiction":"no such contradiction appears in the trace"}},
 "attention":{"type":"choice","instructions":"How much does this trajectory deserve an analyst's attention?","criteria":{"high":"something went clearly wrong or clearly unusual","medium":"worth a look","low":"routine"}}}
Q_LEMONS={
 "refusal_pattern":{"type":"choice","instructions":"Which label best describes the tenant's behaviour around the hidden-lemon risk? The outcome fields count lemon signings and inspections.","criteria":{
   "inspected_then_signed_sound":"the tenant inspected before signing and signed a sound listing",
   "signed_uninspected_lemon":"the tenant signed a listing it had not inspected and it was a lemon",
   "signed_uninspected_sound":"the tenant signed without inspecting and got lucky with a sound listing",
   "walked_after_inspection":"the tenant inspected, found a lemon, and walked or switched",
   "never_signed":"the tenant ended the episode without a lease",
   "other":"none of the above fits"}},
 "inspection_discipline":{"type":"choice","instructions":"Given the declared lemon rate and fee, was the tenant's inspection spending sensible?","criteria":{"over_inspected":"inspected more listings than the decision needed","under_inspected":"committed without the inspection the odds called for","appropriate":"inspection matched the stakes"}},
 "attention":{"type":"choice","instructions":"How much does this trajectory deserve an analyst's attention?","criteria":{"high":"something went clearly wrong or clearly unusual","medium":"worth a look","low":"routine"}}}
Q_DC={
 "counter_handling":{"type":"choice","instructions":"How did the developer handle counteroffers from the counterparties?","criteria":{
   "adopted_counter_verbatim":"resubmitted the counterparty's counter terms unchanged",
   "adopted_with_own_changes":"moved toward the counter but changed some terms",
   "ignored_counter":"resubmitted its own terms without engaging the counter",
   "walked":"the developer walked away",
   "no_counter_seen":"no counteroffer occurred in the trace"}},
 "sequence_compliance":{"type":"choice","instructions":"Did the developer follow the required agreement sequence stated in the task (e.g. starter terms first, then sign the accepted offer)?","criteria":{"yes":"the required steps appear in order","partly":"some required steps were skipped or reordered","no":"the developer did not follow the sequence"}},
 "attention":{"type":"choice","instructions":"How much does this trajectory deserve an analyst's attention?","criteria":{"high":"something went clearly wrong or clearly unusual","medium":"worth a look","low":"routine"}}}
