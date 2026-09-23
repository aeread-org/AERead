"""Case examiner data: every sealed lemons-pilot trajectory, action by action, with the
world's ground truth regenerated from the seed. Output is a compact JSON the page narrates."""
from __future__ import annotations

import json
import sys
from pathlib import Path

WT = Path(sys.argv[1]); OUT = Path(sys.argv[2])
sys.path.insert(0, str(WT / "src"))
from aeread_families.housing import environment as hz  # noqa: E402
from aeread_families.housing import lemons  # noqa: E402
from aeread_families.housing.runner import HousingV1Plugin  # noqa: E402

RUN = WT / "runs" / "housing_lemons_refusal_pilot_v1"
BUNDLE = WT / "evidence" / "housing" / "housing_lemons_refusal_pilot_v1"
plugin = HousingV1Plugin()


def attempts_with_receipts(root: Path):
    for receipt in sorted(root.rglob("evaluation_receipt.json")):
        d = json.loads(receipt.read_bytes())
        if d.get("status") == "ok":
            yield d["receipt_sha256"], receipt.parent


def payload(att: Path, event):
    ref = event.get("payload_ref")
    return json.loads((att / ref).read_text()) if ref else {}


def world_record(payload_):
    case = plugin.validate_payload(payload_)
    world = case["world"]
    oracle = hz.assignment_oracle(world.surplus)
    return {
        "lemon_share": world.lemon_share, "lemon_loss": world.lemon_loss, "inspection_cost": world.inspection_cost,
        "lemon_count": world.lemon_count, "rounds": case["rounds"],
        "listings": [
            {"id": l.listing_id, "ask": world.ask[l.listing_id], "quality": hz.QUALITY_LABEL[world.quality[l.listing_id]],
             "cost": world.costs[l.listing_id], "beds": l.beds, "baths": l.baths, "campus": l.minutes_to_campus,
             "crime": l.crime_index, "groceries": l.minutes_to_groceries, "orientation": l.orientation}
            for l in world.listings
        ],
        "tenants": [{"id": t, "values_if_sound": world.values_if_sound[t], "values_true": world.values[t]} for t in range(world.num_tenants)],
        "oracle_pairs": [list(p) for p in oracle.pairs], "oracle_total": oracle.total,
    }


def trajectory(att: Path):
    events = [json.loads(line) for line in open(att / "events.jsonl")]
    phases = []
    current = None
    actions_by_id = {}
    case_payload = None
    for e in events:
        t = e["event_type"]
        if t == "phase_instance_started":
            p = payload(att, e)
            current = {"phase_instance_id": e["phase_instance_id"], "phase_id": p["phase"]["phase_id"], "mode": p["phase"]["mode"],
                       "eligible": list(p["eligible_actors"]), "actions": [], "verdicts": [], "inbox": [], "holds": [], "post_state": None}
            phases.append(current)
        elif t == "logical_action_started":
            p = payload(att, e)
            req = p["request"]
            case_payload = case_payload or None
            a = {"id": e["logical_action_id"], "seat": req["seat_id"], "role": req["role"], "profile": p.get("profile_id"),
                 "observation_round": req["observation"].get("round_index"), "parsed": None, "legal": None, "valid": None,
                 "failure_code": None, "provider": {"calls": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
                                                    "reasoning_tokens": 0, "finish_reasons": [], "attempts": 0, "retry_reasons": []}}
            # landlord observations carry the inbox, which is not in the pre-state; keep it
            if req["role"] == "landlord":
                a["inbox"] = [{"tenant_id": o["tenant_id"], "rent": o["rent"], "offer_id": o["offer_id"]} for o in req["observation"].get("inbox", [])]
            actions_by_id[a["id"]] = a
            current["actions"].append(a)
        elif t == "action_attempt_started":
            a = actions_by_id[e["logical_action_id"]]; p = payload(att, e)
            a["provider"]["attempts"] += 1
            if p.get("retry_reason"):
                a["provider"]["retry_reasons"].append(p["retry_reason"])
        elif t == "provider_call_succeeded":
            a = actions_by_id[e["logical_action_id"]]; r = payload(att, e)["provider_result"]
            pv = a["provider"]; pv["calls"] += 1; pv["cost_usd"] += float(r.get("cost_usd") or 0)
            pv["input_tokens"] += int(r.get("input_tokens") or 0); pv["output_tokens"] += int(r.get("output_tokens") or 0)
            pv["reasoning_tokens"] += int(r.get("reasoning_tokens") or 0); pv["finish_reasons"].append(r.get("finish_reason"))
        elif t == "action_parsed":
            a = actions_by_id[e["logical_action_id"]]; a["parsed"] = payload(att, e)["parse_result"]
        elif t == "action_legality_checked":
            a = actions_by_id[e["logical_action_id"]]; a["legal"] = payload(att, e)["legality_result"]
        elif t == "logical_action_succeeded":
            a = actions_by_id[e["logical_action_id"]]; p = payload(att, e); a["valid"] = p["valid"]; a["failure_code"] = p["failure_code"]
        elif t == "logical_action_failed":
            a = actions_by_id[e["logical_action_id"]]; p = payload(att, e); a["valid"] = False; a["failure_code"] = p.get("failure_code") or p.get("condition")
        elif t == "transition_applied":
            tr = payload(att, e)["transition"]
            c = tr["consequences"]
            current["verdicts"] = c["verdicts"]; current["inbox"] = c["inbox"]; current["holds"] = c["holds"]
            s = tr["state"]
            current["post_state"] = {
                "round_index": s["round_index"], "phase": s["phase"], "pairs": s["pairs"], "signed_rents": s["signed_rents"],
                "holds": s["holds"], "rejected": s["rejected"], "wasted_contacts": s["wasted_contacts"],
                "inspected": s.get("inspected", []), "inspection_spend": s.get("inspection_spend", []),
                "commit_decisions": s.get("commit_decisions", []), "offers": s["offers"],
            }
        elif t == "episode_terminated":
            terminal = payload(att, e)["terminal"]
    for a in actions_by_id.values():
        a["provider"]["cost_usd"] = round(a["provider"]["cost_usd"], 6)
    return phases, terminal


def case_payload_for(att: Path):
    plan = json.loads((att.parents[3] / "run_plan.json").read_bytes())
    cell_id = att.parents[1].name
    cell = next(c for c in plan["cells"] if c["cell_id"] == cell_id)
    case = next(c for c in plan["cases"] if c["case_id"] == cell["case_id"])
    return case["payload"], cell.get("replicate_index", 0), plan.get("run_plan_id")


cells = [json.loads(l) for l in (BUNDLE / "tables/cells.jsonl").read_text().splitlines()]
by_receipt = {c["receipt_sha256"]: c for c in cells if c.get("receipt_sha256")}
controls = [json.loads(l) for l in (BUNDLE / "tables/scripted_controls.jsonl").read_text().splitlines()]
control_by_receipt = {c["receipt_sha256"]: c for c in controls}
contract = json.load(open(WT / "configs/housing_lemons_refusal_pilot_v1.json"))
strata = {seed: s for s, seeds in contract["variance_pilot"]["strata"].items() for seed in seeds}

out_cases = []
roots = [RUN / "full_trajectory/live_tenant/evidence", RUN / "variance_pilot/live_tenant/evidence", RUN / "variance_pilot/attempt_2/live_tenant/evidence"]
roots += [RUN / "provider_free_validation" / p / "evidence" for p in contract["scripted_controls"]]
worlds = {}
for root in roots:
    for sha, att in attempts_with_receipts(root):
        row = by_receipt.get(sha) or control_by_receipt.get(sha)
        if row is None:
            continue
        source = row.get("policy", "live")
        payload_, replicate, run_plan_id = case_payload_for(att)
        seed = payload_["world_seed"]
        worlds.setdefault(seed, world_record(payload_))
        phases, terminal = trajectory(att)
        out_cases.append({
            "id": f"{source}__w{seed}__r{replicate}", "source": source, "world_seed": seed, "replicate": replicate,
            "stratum": strata.get(seed, "full_trajectory"), "stage": row.get("stage"), "receipt_sha256": sha,
            "model": "google/gemini-3.8-flash-20260902" if source == "live" else f"housing_scripted_tenant_{source}_v1",
            "cost_usd": row.get("cost_usd", 0.0), "reused_from_attempt": row.get("reused_from_attempt"),
            "outcome": {k: terminal.get(k) for k in ("tenant_net_total", "tenant_net_payoffs", "tenant_payoffs", "tenant_inspection_spend",
                                                       "landlord_payoffs", "reference_total", "sign_anything_total", "oracle_total",
                                                       "within_case_score", "abstention_correctness_rate", "abstention_decision_count",
                                                       "abstention_correct_count", "lemon_signings", "uninspected_lemon_signings",
                                                       "ir_violations", "assignment_pairs", "signed_rents", "reason", "inspection_count",
                                                       "social_welfare", "commit_decisions")},
            "phases": phases,
        })
out_cases.sort(key=lambda c: (c["world_seed"], {"live": 0, "inspect_then_sign": 1, "sign_anything": 2, "pass": 3}[c["source"]], c["replicate"]))
data = {"campaign_id": "housing_lemons_refusal_pilot_v1", "family": "housing_v1", "world_kind": "lemons",
        "phase_graph": [["inspect", "contact"], ["contact", "respond"], ["respond", "commit"], ["commit", "inspect"]],
        "phase_actors": {"inspect": "unmatched tenants", "contact": "unmatched tenants", "respond": "landlords with an open listing", "commit": "unmatched tenants"},
        "worlds": worlds, "cases": out_cases}
OUT.write_text(json.dumps(data, separators=(",", ":")))
print("cases", len(out_cases), "| worlds", len(worlds), "| bytes", OUT.stat().st_size, "| actions", sum(len(p["actions"]) for c in out_cases for p in c["phases"]))
from collections import Counter
print(Counter(c["source"] for c in out_cases))
