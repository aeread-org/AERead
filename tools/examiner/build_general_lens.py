"""Full-detail lens for every campaign in the general examiner.

For each published case whose sealed attempt directory is on this machine, walk the event
log and keep, per logical action, the observation exactly as the seat received it, the
instructions the model was given, the raw response text, the parse and legality results,
and, per phase instance, the consequences and the state after the transition; then the
terminal state, the family outcome and the score.  Cases without a local run root get a
"published_only" record carrying whatever the repository's case file says about the world.

Usage: build_general_lens.py <general_examiner dir> <worktree> <receipt_index.json>
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

GE = Path(sys.argv[1])
WT = Path(sys.argv[2])
IDX = json.loads(Path(sys.argv[3]).read_text())
OUT = GE / "data" / "lens"
OUT.mkdir(parents=True, exist_ok=True)
RAW_CAP = 6000
def unpack_json(path: Path):
    """Inflate a gzip+base64 envelope written by a previous run so this run can read and rewrite it."""
    if not path.exists():
        return
    try:
        head = path.read_text()[:64]
        if '"encoding":"gzip+base64"' not in head:
            return
        import base64 as _b64, gzip as _gz
        env = json.loads(path.read_text())
        path.write_bytes(_gz.decompress(_b64.b64decode(env["payload"])))
    except Exception:
        return


def is_narrated(path: Path) -> bool:
    """A family-narrated lens (the housing lemons exporter) carries world_kind; keep it instead of overwriting."""
    try:
        return path.exists() and '"world_kind"' in path.read_text()[:2000]
    except Exception:
        return False


def payload(att: Path, event: dict) -> dict:
    ref = event.get("payload_ref")
    if ref:
        return json.loads((att / ref).read_text())
    return event.get("payload") or {}


def trim_score(score):
    if not isinstance(score, dict):
        return score
    out = {k: v for k, v in score.items() if k not in ("leaf", "evidence_refs")}
    leaf = score.get("leaf") or {}
    est = leaf.get("estimand") or {}
    out["estimand"] = {k: est.get(k) for k in ("estimand_id", "direction", "units", "input_scope") if k in est}
    return out


def trajectory(att: Path):
    events = [json.loads(line) for line in open(att / "events.jsonl")]
    phases, acts, instructions = [], {}, {}
    cur = None
    terminal = outcome = score = None
    for e in events:
        t = e["event_type"]
        if t == "phase_instance_started":
            p = payload(att, e)
            ph = p.get("phase", {})
            cur = {
                "phase_instance_id": e.get("phase_instance_id"), "phase_id": ph.get("phase_id"), "mode": ph.get("mode"),
                "max_logical_actions": ph.get("max_logical_actions"), "actor_selector": ph.get("actor_selector"),
                "next_phases": ph.get("next_phases"), "eligible": list(p.get("eligible_actors") or []),
                "pre_state_sha256": p.get("pre_state_sha256"), "actions": [], "consequences": None, "post_state": None,
                "post_state_sha256": None, "next_phase_id": None, "status": None,
            }
            phases.append(cur)
        elif t == "logical_action_started":
            p = payload(att, e)
            req = p.get("request", {})
            a = {
                "id": e.get("logical_action_id"), "seat": req.get("seat_id"), "role": req.get("role"), "profile": p.get("profile_id"),
                "observation": req.get("observation"), "action_schema": req.get("action_schema"), "raw": None, "parsed": None,
                "legal": None, "valid": None, "failure_code": None, "model": None, "provider_name": None, "instructions_key": None,
                "sampling": None,
                "provider": {"calls": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0,
                             "finish_reasons": [], "attempts": 0, "retry_reasons": [], "failures": []},
            }
            acts[a["id"]] = a
            if cur is None:  # defensive: an action outside a phase instance
                cur = {"phase_instance_id": None, "phase_id": "?", "mode": None, "eligible": [], "actions": [], "consequences": None,
                       "post_state": None, "next_phase_id": None, "status": None}
                phases.append(cur)
            cur["actions"].append(a)
        elif t == "action_attempt_started":
            a = acts.get(e.get("logical_action_id"))
            if a:
                p = payload(att, e)
                a["provider"]["attempts"] += 1
                if p.get("retry_reason"):
                    a["provider"]["retry_reasons"].append(p["retry_reason"])
        elif t == "provider_call_started":
            a = acts.get(e.get("logical_action_id"))
            if a:
                req = payload(att, e).get("request", {})
                ins = req.get("instructions")
                if ins:
                    key = hashlib.sha256(ins.encode()).hexdigest()[:12]
                    instructions[key] = ins
                    a["instructions_key"] = key
                a["model"] = req.get("model")
                a["provider_name"] = req.get("provider")
                a["sampling"] = {k: req.get(k) for k in ("temperature", "top_p", "seed", "reasoning_effort", "max_output_tokens") if req.get(k) is not None}
        elif t == "provider_call_succeeded":
            a = acts.get(e.get("logical_action_id"))
            if a:
                r = payload(att, e).get("provider_result", {})
                pv = a["provider"]
                pv["calls"] += 1
                pv["cost_usd"] += float(r.get("cost_usd") or 0)
                pv["input_tokens"] += int(r.get("input_tokens") or 0)
                pv["output_tokens"] += int(r.get("output_tokens") or 0)
                pv["reasoning_tokens"] += int(r.get("reasoning_tokens") or 0)
                pv["finish_reasons"].append(r.get("finish_reason"))
        elif t == "provider_call_failed":
            a = acts.get(e.get("logical_action_id"))
            if a:
                p = payload(att, e)
                a["provider"]["calls"] += 1
                a["provider"]["failures"].append({"condition": p.get("failure_condition"), "message": (p.get("message") or "")[:300],
                                                  "status_code": p.get("status_code"), "retryable": p.get("retryable")})
        elif t == "action_attempt_succeeded":
            a = acts.get(e.get("logical_action_id"))
            if a:
                cr = payload(att, e).get("canonical_response") or {}
                text = cr.get("text")
                if isinstance(text, str):
                    a["raw"] = text[:RAW_CAP] + ("…[truncated]" if len(text) > RAW_CAP else "")
                elif cr.get("action") is not None:
                    a["raw"] = json.dumps(cr.get("action"))[:RAW_CAP]
        elif t == "action_attempt_failed":
            a = acts.get(e.get("logical_action_id"))
            if a:
                p = payload(att, e)
                if p.get("failure_condition") and not a["provider"]["failures"]:
                    a["provider"]["failures"].append({"condition": p.get("failure_condition")})
        elif t == "action_parsed":
            a = acts.get(e.get("logical_action_id"))
            if a:
                a["parsed"] = payload(att, e).get("parse_result")
        elif t == "action_legality_checked":
            a = acts.get(e.get("logical_action_id"))
            if a:
                a["legal"] = payload(att, e).get("legality_result")
        elif t == "logical_action_succeeded":
            a = acts.get(e.get("logical_action_id"))
            if a:
                p = payload(att, e)
                a["valid"] = p.get("valid")
                a["failure_code"] = p.get("failure_code")
        elif t == "logical_action_failed":
            a = acts.get(e.get("logical_action_id"))
            if a:
                p = payload(att, e)
                a["valid"] = False
                a["failure_code"] = p.get("failure_code") or p.get("failure_condition") or p.get("condition") or "failed"
        elif t == "transition_applied":
            p = payload(att, e)
            tr = p.get("transition", {})
            if cur is not None:
                cur["consequences"] = tr.get("consequences")
                cur["post_state"] = tr.get("state")
                cur["post_state_sha256"] = p.get("post_state_sha256")
                cur["next_phase_id"] = tr.get("next_phase_id")
        elif t == "phase_instance_succeeded":
            if cur is not None:
                cur["status"] = "succeeded"
        elif t == "phase_instance_failed":
            if cur is not None:
                cur["status"] = "failed"
                cur["failure"] = payload(att, e)
        elif t == "episode_terminated":
            terminal = payload(att, e).get("terminal")
        elif t == "family_outcome_recorded":
            outcome = payload(att, e).get("outcome")
        elif t == "score_recorded":
            score = trim_score(payload(att, e).get("score"))
    for a in acts.values():
        a["provider"]["cost_usd"] = round(a["provider"]["cost_usd"], 6)
    return phases, terminal, outcome, score, instructions


def run_plan_case(att: Path):
    """The case definition and seats from the run plan that scheduled this attempt."""
    for up in (3, 4, 5):
        try:
            rp = att.parents[up] / "run_plan.json"
        except IndexError:
            break
        if rp.exists():
            plan = json.loads(rp.read_bytes())
            cell_id = att.parents[1].name
            cell = next((c for c in plan.get("cells", []) if c.get("cell_id") == cell_id), None)
            if not cell:
                return None, None, None
            case = next((c for c in plan.get("cases", []) if c.get("case_id") == cell.get("case_id")), None)
            profiles = {p.get("profile_id"): p for p in plan.get("agent_profiles", []) if isinstance(p, dict)}
            return case, cell, profiles
    return None, None, None


def repo_case_file(case_id: str):
    """cases/<family>/<pack...>/<name>.json for ids like family.pack.name."""
    parts = case_id.split(".")
    if len(parts) < 2:
        return None
    for split in range(1, len(parts)):
        p = WT / "cases" / Path(*parts[:split]) / (".".join(parts[split:]) + ".json")
        if p.exists():
            return p
    return None


def world_from_case(case: dict | None, case_id: str):
    """What the repository says the world is: the case payload (resolving thin references)."""
    src = None
    if case and isinstance(case.get("payload"), dict):
        pl = case["payload"]
        base = pl.get("base_case_id")
        if base and len(pl) <= 6:  # a thin reference to a base case: pull the base world too
            f = repo_case_file(base)
            if f:
                b = json.loads(f.read_text())
                return {"payload": b.get("payload"), "seats": b.get("seats"), "episode": b.get("episode"),
                        "overrides": pl, "source": "run plan case + repository base case " + str(f.relative_to(WT))}
        return {"payload": pl, "seats": case.get("seats"), "episode": case.get("episode"), "source": "run plan case"}
    f = repo_case_file(case_id)
    if f:
        b = json.loads(f.read_text())
        return {"payload": b.get("payload"), "seats": b.get("seats"), "episode": b.get("episode"),
                "source": "repository case file " + str(f.relative_to(WT))}
    return None


def short_source(att: Path) -> str:
    s = str(att)
    for marker in ("/runs/",):
        if marker in s:
            s = s.split(marker, 1)[1]
    parts = s.split("/")
    return "/".join(parts[:3]) + (" … " + parts[-1] if len(parts) > 3 else "")



STRING_CAP = 12000
HEX = re.compile(r"[0-9a-f]{64}")


def cap_strings(v):
    """Bound long string leaves (observations can embed whole documents)."""
    if isinstance(v, str):
        return v if len(v) <= STRING_CAP else v[:STRING_CAP] + f"…[truncated {len(v) - STRING_CAP:,} chars]"
    if isinstance(v, list):
        return [cap_strings(x) for x in v]
    if isinstance(v, dict):
        return {k: cap_strings(x) for k, x in v.items()}
    return v


def _size(v):
    return len(json.dumps(v, separators=(",", ":"), default=str))


def compact_obj(cur, prev, prev_any=None):
    """Lossless references the page expands (expandObj): {"$p":1} same value as this seat's previous
    object; {"$pa":1} same as the previous action's object (any seat); {"$pp":n,"t":[...]} the previous
    array extended by a tail; {"$pe":n,"d":{i:v},"t":[...]} the previous array with some elements
    replaced and a tail appended."""
    if not isinstance(cur, dict):
        return cur
    out = {}
    for k, v in cur.items():
        pv = prev.get(k, KeyError) if isinstance(prev, dict) else KeyError
        pa = prev_any.get(k, KeyError) if isinstance(prev_any, dict) else KeyError
        if pv is not KeyError and pv == v:
            out[k] = {"$p": 1}
        elif pa is not KeyError and pa == v:
            out[k] = {"$pa": 1}
        elif isinstance(v, list) and isinstance(pv, list) and pv and len(v) > len(pv) and v[: len(pv)] == pv:
            out[k] = {"$pp": len(pv), "t": v[len(pv):]}
        elif isinstance(v, list) and isinstance(pv, list) and pv and len(v) >= len(pv) and all(isinstance(x, dict) for x in v[: len(pv)]):
            n = len(pv)
            cand = {"$pe": n, "d": {str(i): v[i] for i in range(n) if v[i] != pv[i]}, "t": v[n:]}
            out[k] = cand if _size(cand) < _size(v) else v
        else:
            out[k] = v
    return out


def compact_case(rec):
    prev_by_seat, prev_state, prev_any = {}, None, None
    for ph in rec.get("phases", []):
        for a in ph["actions"]:
            o = a.get("observation")
            if isinstance(o, dict):
                a["observation"] = compact_obj(o, prev_by_seat.get(a["seat"]), prev_any)
                prev_by_seat[a["seat"]] = o
                prev_any = o
            if a.get("raw") and not a.get("model"):  # scripted seat: the raw text is the parsed action again
                a["raw"] = None
        st = ph.get("post_state")
        if isinstance(st, dict):
            if prev_state is not None:
                ph["post_state"] = compact_obj(st, prev_state)
            prev_state = st
    t, o = rec.get("terminal"), rec.get("outcome")
    if isinstance(t, dict) and isinstance(o, dict):  # terminal keys already carried by the outcome
        rec["terminal"] = {k: ({"$o": 1} if k in o and o[k] == v else v) for k, v in t.items()}


def thin_campaign(cf: Path):
    """For a campaign whose every case has a full lens, drop the per-step rows from its campaign file:
    the page rebuilds steps from the lens.  Keeps everything the tables and the case list need."""
    camp = json.loads(cf.read_text())
    if camp.get("thin"):
        return
    for k in camp["cases"]:
        steps = k.pop("steps", [])
        k["steps_count"] = len(steps)
        k.setdefault("invalid_steps", sum(1 for s in steps if (s.get("outcome") or {}).get("valid") is False))
        k.setdefault("phases", [s.get("phase") for s in steps])
    camp["thin"] = True
    cf.write_text(json.dumps(camp, separators=(",", ":"), default=str))


def published_attempts(bundle: Path):
    """Receipt digests the bundle publishes that resolve to a sealed attempt directory here."""
    shas = set()
    for f in [bundle / "publication_manifest.json", *bundle.glob("reports/*.json"), *bundle.glob("receipts/*"), *bundle.glob("tables/*")]:
        try:
            shas.update(HEX.findall(f.read_text()))
        except Exception:
            continue
    return {s: IDX[s][0] for s in sorted(shas) if s in IDX}


def outcome_row(bundle: Path, sha: str):
    """The bundle's own table row for this receipt, flattened one level (as the grain builder does)."""
    for f in sorted(bundle.glob("tables/*.jsonl")):
        for line in f.read_text().splitlines():
            if sha in line:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                out = {}
                for k, v in row.items():
                    if isinstance(v, dict):
                        for kk, vv in v.items():
                            if not isinstance(vv, (dict, list)):
                                out[f"{k}.{kk}"] = vv
                    elif isinstance(v, list):
                        out[k] = json.dumps(v)[:120]
                    else:
                        out[k] = v
                return out
    for f in sorted(bundle.glob("tables/*.csv")):
        with open(f, newline="") as fh:
            for row in csv.DictReader(fh):
                if sha in row.values():
                    return dict(row)
    return None


def synth_campaign(cid: str, fam: str, bundle: Path, recs: list[dict]) -> dict:
    """A campaign file in the published-grain shape, built from the sealed lens records."""
    cases, phase_order, edges = [], [], set()
    for r in recs:
        if r.get("kind") != "sealed":
            continue
        steps, prev_phase = [], None
        for ph in r["phases"]:
            if ph["phase_id"] not in phase_order:
                phase_order.append(ph["phase_id"])
            if prev_phase is not None:
                edges.add((prev_phase, ph["phase_id"]))
            prev_phase = ph["phase_id"]
            for a in ph["actions"]:
                pv = a["provider"]
                steps.append({
                    "i": len(steps), "phase": ph["phase_id"], "seat": a["seat"], "role": a["role"], "profile": a["profile"],
                    "action": (a["parsed"] or {}).get("action") if isinstance(a["parsed"], dict) else None, "parse": a["parsed"], "legal": a["legal"],
                    "outcome": {"valid": a["valid"], "failure_code": a["failure_code"], "status": "ok" if a["valid"] else ("failed" if a["valid"] is False else None)},
                    "provider": {"calls": pv["calls"], "cost": pv["cost_usd"], "cost_unknown": 0, "in": pv["input_tokens"], "out": pv["output_tokens"],
                                 "reasoning": pv["reasoning_tokens"], "finish": [x for x in pv["finish_reasons"] if x], "attempts": pv["attempts"],
                                 "failures": [f.get("condition") for f in pv["failures"] if f.get("condition")]},
                    "tools": None,
                })
        profiles = sorted({a["profile"] for ph in r["phases"] for a in ph["actions"] if a.get("profile")})
        cases.append({
            "case_id": r["case_id"], "cell_id": r["cell_id"], "episode_attempt_id": r["episode_attempt_id"], "receipt_sha256": r["receipt_sha256"],
            "profiles": profiles, "steps": steps, "phases": [ph["phase_id"] for ph in r["phases"]], "outcome_row": outcome_row(bundle, r["receipt_sha256"]),
            "cost": round(sum(s["provider"]["cost"] for s in steps), 6), "invalid_steps": sum(1 for s in steps if s["outcome"]["valid"] is False),
        })
    graph = {"nodes": phase_order, "edges": [{"from": a, "to": b} for a, b in sorted(edges)], "entry": phase_order[0] if phase_order else None,
             "basis": "observed in the sealed event logs on this machine"}
    return {"campaign_id": cid, "family": fam, "source": "sealed_logs", "cases": cases, "graph": graph}


catalog = json.loads((GE / "data" / "catalog.json").read_text())
index = {}
for camp_entry in catalog["campaigns"]:
    cid = camp_entry["id"]
    bundle = WT / camp_entry["path"]
    cf = GE / "data" / "campaigns" / f"{cid}.json"
    unpack_json(cf)
    published_grain = cf.exists() and not (json.loads(cf.read_text()).get("source") == "sealed_logs")
    unpack_json(OUT / f"{cid}.json")
    if is_narrated(OUT / f"{cid}.json"):
        nf = OUT / f"{cid}.json"; nd = json.loads(nf.read_text())
        if not nd.get("compact"):
            for rec in nd["cases"]:
                prev_state = None
                for ph in rec.get("phases", []):
                    st = ph.get("post_state")
                    if isinstance(st, dict):
                        if prev_state is not None:
                            ph["post_state"] = compact_obj(st, prev_state)
                        prev_state = st
            nd["compact"] = True
            nf.write_text(json.dumps(nd, separators=(",", ":"), default=str))
        if cf.exists():
            thin_campaign(cf)
        index[cid] = {"file": f"data/lens/{cid}.json", "kind": "narrated", "cases": len(nd["cases"]),
                      "note": "family-narrated lens exported by the family's own exporter (kept as is)"}
        continue
    if published_grain:
        camp = json.loads(cf.read_text())
        targets = [(k["receipt_sha256"], k["cell_id"], k["episode_attempt_id"], k["case_id"]) for k in camp["cases"]]
    else:
        targets = []
        for sha, d in published_attempts(bundle).items():
            rc = json.loads((Path(d) / "evaluation_receipt.json").read_bytes())
            targets.append((sha, rc.get("cell_id"), rc.get("episode_attempt_id"), rc.get("case_id")))
        targets.sort(key=lambda t: (t[3] or "", t[1] or "", t[2] or ""))
    if not targets:
        layout = sorted({p.relative_to(bundle).parts[0] for p in bundle.rglob("*") if p.is_file()})
        manifest = json.loads((bundle / "publication_manifest.json").read_text()) if (bundle / "publication_manifest.json").exists() else {}
        receipt_lists = [v for k, v in (manifest.get("source_bindings") or {}).items() if "receipt" in k and isinstance(v, list) and v]
        has_receipts = bool(receipt_lists) or any(bundle.glob("receipts/*")) or any("receipt_sha256" in f.read_text() for f in bundle.glob("tables/*") if f.is_file())
        why = ("it publishes per-attempt receipt digests, but none resolves to a sealed attempt directory on this machine (the run root is elsewhere)" if has_receipts
               else "it publishes no per-attempt receipts at all (a derived, aggregate or register bundle: " + ", ".join(layout) + ")")
        index[cid] = {"file": None, "kind": "none", "cases": 0, "sealed": 0, "layout": layout, "publishes_receipts": has_receipts,
                      "note": "no step grain in the bundle and nothing to reconstruct it from: " + why}
        continue
    cases_out, instructions_all, sealed = [], {}, 0
    for sha, cell_id, attempt_id, case_id in targets:
        dirs = IDX.get(sha)
        rec = {"receipt_sha256": sha, "cell_id": cell_id, "episode_attempt_id": attempt_id, "case_id": case_id}
        if dirs:
            att = Path(dirs[0])
            receipt = json.loads((att / "evaluation_receipt.json").read_bytes())
            phases, terminal, outcome, score, ins = trajectory(att)
            for ph in phases:
                for a in ph["actions"]:
                    a["observation"] = cap_strings(a["observation"])
                ph["post_state"] = cap_strings(ph["post_state"]); ph["consequences"] = cap_strings(ph["consequences"])
            instructions_all.update(ins)
            case, cell, profiles = run_plan_case(att)
            rec.update({
                "kind": "sealed", "source": short_source(att), "receipt_status": receipt.get("status"), "failure": receipt.get("failure"),
                "replicate_index": receipt.get("replicate_index"), "phases": phases, "terminal": cap_strings(terminal), "outcome": outcome, "score": score,
                "world": cap_strings(world_from_case(case, case_id or "")), "cell": {kk: cell.get(kk) for kk in ("case_id", "replicate_index", "seat_profiles", "profile_by_seat", "condition", "variant", "world_seed") if cell and kk in cell},
                "profiles": {pid: {kk: p.get(kk) for kk in ("model", "provider", "policy_id", "kind", "temperature", "reasoning_effort") if kk in p} for pid, p in (profiles or {}).items()},
            })
            sealed += 1
        else:
            rec.update({"kind": "published_only", "world": world_from_case(None, case_id or "")})
        cases_out.append(rec)
    kind = "sealed" if sealed == len(cases_out) else ("mixed" if sealed else "published_only")
    if kind == "published_only" and not any(c.get("world") for c in cases_out):
        index[cid] = {"file": None, "kind": "none", "cases": len(cases_out), "sealed": 0,
                      "note": "no sealed attempt directory on this machine and no repository case file for these case ids"}
        continue
    if not published_grain and sealed:
        synth = synth_campaign(cid, camp_entry.get("family"), bundle, cases_out)
        cf.write_text(json.dumps(synth, separators=(",", ":"), default=str))
        rows = sum(len(k["steps"]) for k in synth["cases"])
        prof_ids = sorted({p for k in synth["cases"] for p in k["profiles"]})
        scripted = sum(1 for pid in prof_ids if any(a.get("provider_name") == "scripted" or not a.get("model") for c in cases_out if c.get("kind") == "sealed" for ph in c["phases"] for a in ph["actions"] if a.get("profile") == pid))
        camp_entry["trajectory_file"] = f"data/campaigns/{cid}.json"
        g = camp_entry.get("grain") or {}
        g.update({"source": "sealed_logs", "cases": len(synth["cases"]), "rows": rows, "steps_per_case": round(rows / max(1, len(synth["cases"])), 1),
                  "phases": synth["graph"]["nodes"], "profiles": len(prof_ids), "scripted_profiles": scripted, "profile_ids": prof_ids,
                  "invalid_steps": sum(k["invalid_steps"] for k in synth["cases"]), "cost_usd": round(sum(k["cost"] for k in synth["cases"]), 6)})
        camp_entry["grain"] = g
    for rec in cases_out:
        compact_case(rec)
    data = {"campaign_id": cid, "family": camp_entry.get("family"), "kind": kind, "sealed_cases": sealed, "compact": True, "cases": cases_out, "instructions": instructions_all}
    out = OUT / f"{cid}.json"
    out.write_text(json.dumps(data, separators=(",", ":"), default=str))
    if kind == "sealed":
        thin_campaign(cf)
    index[cid] = {"file": f"data/lens/{cid}.json", "kind": kind, "cases": len(cases_out), "sealed": sealed, "bytes": out.stat().st_size,
                  "published_grain": published_grain,
                  "note": ("observations, states and consequences from the sealed event logs on this machine" + ("" if published_grain else "; the bundle publishes no step grain, so the steps themselves come from those logs")) if kind == "sealed"
                  else "no sealed attempt directory on this machine; world facts from the repository case files only"}
    acts = sum(len(p["actions"]) for c in cases_out for p in c.get("phases", []))
    print(f"{cid}: kind={kind} sealed={sealed}/{len(cases_out)} actions={acts} bytes={out.stat().st_size:,}{'' if published_grain else ' [campaign file synthesized]'}")

# pack every lens and campaign file: gzip + base64 inside a small JSON envelope, same file name
# (the artifact host serves only known text/media types; the page inflates with DecompressionStream)
import base64, gzip
def pack_json(path: Path):
    raw = path.read_bytes()
    try:
        if json.loads(raw).get("encoding") == "gzip+base64":
            return
    except Exception:
        pass
    packed = base64.b64encode(gzip.compress(raw, compresslevel=9)).decode("ascii")
    path.write_text(json.dumps({"encoding": "gzip+base64", "raw_bytes": len(raw), "payload": packed}, separators=(",", ":")))
for cf in sorted((GE / "data" / "campaigns").glob("*.json")):
    pack_json(cf)
for lf in sorted(OUT.glob("*.json")):
    if lf.name != "index.json":
        pack_json(lf)
for stale in list((GE / "data" / "campaigns").glob("*.json.gz")) + list(OUT.glob("*.json.gz")):
    stale.unlink()
for meta in index.values():
    f = meta.get("file")
    if f and (GE / f).exists():
        meta["bytes"] = (GE / f).stat().st_size
(GE / "data" / "catalog.json").write_text(json.dumps(catalog, separators=(",", ":"), default=str))
(OUT / "index.json").write_text(json.dumps(index, indent=1))
print("packed (gzip+base64 json):", len(list((GE / "data" / "campaigns").glob("*.json"))), "campaign files,", len([x for x in OUT.glob("*.json") if x.name != "index.json"]), "lens files")
print("index:", Counter(v["kind"] for v in index.values()), "| synthesized:", sum(1 for c in catalog["campaigns"] if (c.get("grain") or {}).get("source") == "sealed_logs"))
