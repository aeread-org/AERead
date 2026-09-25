"""StarCraft (OpenBW prototype) matches for the examiner.

Reads the local match runs of the starcraft_master prototype (mode-<name>.<id>/ with a manifest.json) and adds
them to an examiner build as one bundle: each match is a case, and each step is one strategist decision (a goal
chosen, a goal reviewed, an engagement posture, a tactical mission, a concession review) with what the seat was
shown, the option it took and its stated reason. The state beyond a seat's view is the opponent's economy and army
at that moment, read from the opponent's own snapshots.

These runs are not AERead evidence: every manifest says "not an AERead EvaluationReceipt" and every iteration
report "sealed_partial_diagnostic_only". The bundle is marked external so the page says so and applies no AERead
checklist. Nothing machine-local is published: absolute paths are cut to run-relative ones, and replays, raw event
logs and controller logs are never copied.

    python3 build_starcraft.py <examiner build dir> <starcraft runs dir>
"""
from __future__ import annotations

import base64
import bisect
import gzip
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(sys.argv[1])
RUNS = Path(sys.argv[2]).expanduser().resolve()
BID = "starcraft_codex_claude_local"
FAMILY = "starcraft"
LABEL = "StarCraft (OpenBW prototype)"
LOCAL = re.compile(r"(/Users|/private|/home|/var/folders)/[^\s\"']*")
JEV_PHASES = {"tactical_mission"}  # chosen by the tactical chooser (Jev); every other step by the seat's strategist model
STRATEGIST_NAME = {"codex_cli": "Codex", "claude_cli": "Claude"}
# The controller's loop per seat (starcraft_master tools/action_combined_runner.py, CombinedRunner.run): on each new
# strategic snapshot, a concession review when due, then an engagement posture when due, then one macro lane's agenda
# step (select a goal if the lane has none, else pursue it and review it when due; primary and support lanes take
# turns). Jev's tactical missions and worker orders run in the same loop on the finer tactical snapshots.
LOOP = {"plugin": "CombinedRunner (starcraft_master)", "variant": "per seat",
        "nodes": ["match_start", "concession", "engagement", "goal", "goal_review", "tactical_mission"],
        "edges": [{"from": a, "to": b} for a, b in (("match_start", "concession"), ("concession", "engagement"), ("engagement", "goal"),
                  ("engagement", "goal_review"), ("goal", "concession"),
                  ("goal_review", "concession"), ("tactical_mission", "tactical_mission"))],
        "modes": {n: "single" for n in ("match_start", "concession", "engagement", "goal", "goal_review", "tactical_mission")},
        "actors": {"match_start": "launcher", "concession": "strategist model", "engagement": "strategist model", "goal": "strategist model",
                   "goal_review": "strategist model", "tactical_mission": "Jev"},
        "note": ("Each seat runs this loop on its own. On every new strategic snapshot (about every 120 frames) the strategist model "
                 "reviews concession when due, then the engagement posture when due, then one macro lane takes a step: it picks a goal "
                 "if it has none, otherwise the goal runner pursues it and the model reviews it when due (primary and support lanes "
                 "alternate). Jev chooses tactical missions and worker orders in the same loop on finer snapshots. Steps below are "
                 "these decisions from both seats in frame order.")}


def load(path: Path):
    d = json.loads(path.read_text())
    if isinstance(d, dict) and d.get("encoding") == "gzip+base64":
        d = json.loads(gzip.decompress(base64.b64decode(d["payload"])))
    return d


def pack(path: Path, obj) -> int:
    raw = json.dumps(obj, separators=(",", ":"), default=str).encode()
    path.write_text(json.dumps({"encoding": "gzip+base64", "raw_bytes": len(raw), "payload": base64.b64encode(gzip.compress(raw, 9)).decode()}, separators=(",", ":")))
    return path.stat().st_size


def scrub(obj, run: Path):
    """Machine-local paths become run-relative (or just a file name); nothing else changes."""
    if isinstance(obj, dict):
        return {k: scrub(v, run) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v, run) for v in obj]
    if isinstance(obj, str) and LOCAL.search(obj):
        return LOCAL.sub(lambda m: m.group(0).split(str(run) + "/", 1)[1] if str(run) + "/" in m.group(0) else "…/" + m.group(0).rstrip("/").split("/")[-1], obj)
    return obj


def jsonl(path: Path) -> list:
    out = []
    if path.exists():
        for line in path.read_text(errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass  # a line cut short when the seat was stopped
    return out


def num(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def condense(snap: dict) -> dict:
    """A seat's own view at one macro snapshot, as counts rather than unit lists."""
    own = snap.get("own_units") or []
    return {"minerals": num(snap.get("minerals")), "gas": num(snap.get("gas")),
            "free_supply": num(snap.get("free_supply_half_units")) / 2,
            "units": dict(sorted(Counter(u.get("type") for u in own if u.get("completed")).items())),
            "in_production": dict(sorted(Counter(u.get("type") for u in own if not u.get("completed")).items())),
            "visible_enemies": dict(sorted(Counter(u.get("type") for u in (snap.get("visible_enemies") or [])).items())),
            "researched": sorted(snap.get("researched") or [])}


def snapshots(seat_dir: Path) -> list:
    snaps = []
    for p in seat_dir.glob("action-snapshot-macro-*.json"):
        try:
            s = json.loads(p.read_text())
        except ValueError:
            continue
        snaps.append((num(s.get("frame")), condense(s)))
    return sorted(snaps, key=lambda x: x[0])


def at(snaps: list, frame: int):
    frames = [f for f, _ in snaps]
    i = bisect.bisect_right(frames, frame) - 1
    return snaps[i][1] if i >= 0 else (snaps[0][1] if snaps else None)


def request_frame(seat_dir: Path, request_id) -> int | None:
    for kind in ("micro", "macro"):
        p = seat_dir / f"{kind}-request-{request_id}.json"
        if p.exists():
            try:
                return num(json.loads(p.read_text()).get("frame"), None)
            except ValueError:
                pass
    return None


def menu_labels(e: dict) -> list:
    return [f"{o.get('id')}: {o.get('label')}" for o in ((e.get("menu") or {}).get("options") or [])]


def decisions(run: Path, seat: str) -> list:
    """Every strategist decision of one seat, as (frame, phase, action, extra observation, model calls)."""
    d = run / seat
    out = []
    for lane_file, lane in (("action-agenda.events.jsonl", "primary"), ("action-agenda-support.events.jsonl", "support")):
        for e in jsonl(d / lane_file):
            ev = e.get("event")
            if ev == "goal_selected":
                out.append((num(e.get("frame")), "goal", {"decision": "select_goal", "lane": lane, "goal": e.get("goal"), "target_count": e.get("target_count"),
                            "rationale": e.get("plan_summary"), "strategic_plan": e.get("strategic_plan")},
                            {"selected_path": e.get("selected_path")}, num(e.get("selection_model_calls"), 1)))
            elif ev in ("goal_review", "goal_review_deferred"):
                pc = e.get("menu", {}).get("public_context") or e.get("public_context") or {}
                out.append((num(e.get("frame")), "goal_review", {"decision": e.get("choice_id"), "lane": lane, "deferred": ev.endswith("deferred"),
                            "reviewed_goal": pc.get("active_goal")}, {"menu": menu_labels(e), "public_context": pc}, 1))
    for e in jsonl(d / "action-engagement.events.jsonl"):
        if e.get("event") == "engagement_directive_selected":
            dr = e.get("directive") or {}
            out.append((num(dr.get("frame"), num(e.get("frame"))), "engagement", {"decision": e.get("choice_id"), "posture": dr.get("posture"),
                        "rationale": dr.get("public_reason"), "visible_home_threat": dr.get("visible_home_threat")},
                        {"menu": menu_labels(e), "public_context": (e.get("menu") or {}).get("public_context") or e.get("public_context")}, 1))
    for e in jsonl(d / "action-tactical.events.jsonl"):
        if e.get("event") == "tactical_mission_selected":
            f = num(e.get("frame"), None)
            f = f if f is not None else request_frame(d, e.get("request_id"))
            out.append((f or 0, "tactical_mission", {"decision": "select_mission", "script_id": e.get("script_id"), "actor_unit_ids": e.get("actor_unit_ids")}, {}, 1))
    for e in jsonl(d / "action-concession.events.jsonl"):
        if e.get("event") == "concession_review":
            out.append((num(e.get("frame")), "concession", {"decision": e.get("choice_id")},
                        {"menu": menu_labels(e), "visible_state": e.get("visible_state"), "public_context": (e.get("menu") or {}).get("public_context")}, 1))
    return sorted(out, key=lambda x: x[0])


def command_frames(run: Path, seat: str) -> list:
    """Frames of the native commands the seat's engine observed (cheap: only command lines are parsed)."""
    frames = []
    p = run / f"{seat}.events.jsonl"
    if p.exists():
        with p.open(errors="replace") as fh:
            for line in fh:
                if '"command_observed"' in line:
                    try:
                        frames.append(num(json.loads(line).get("frame")))
                    except ValueError:
                        pass
    return sorted(frames)


def build_case(run: Path, reports: Path):
    m = json.loads((run / "manifest.json").read_text())
    launch = json.loads((run / "launch.json").read_text()) if (run / "launch.json").exists() else {}
    seats = [s["seat_id"] for s in (m.get("mode") or {}).get("seats") or []]
    races = {s["seat_id"]: s.get("race", "").lower() for s in (m.get("mode") or {}).get("seats") or []}
    rid = run.name.split(".", 1)[1]
    report = next((json.loads(p.read_text()) for p in sorted(reports.glob(f"{rid}.*.json"), key=lambda p: (".sealed." not in p.name, p.name))), {})
    snaps = {s: snapshots(run / s) for s in seats}
    backends = {}
    for s in seats:
        for e in jsonl(run / s / "action-concession.events.jsonl")[:1]:
            backends[s] = (e.get("metadata") or {}).get("backend")
    state = lambda f: {"frame": f, **{s: at(snaps[s], f) for s in seats}}
    decs = sorted(((f, s, ph, act, extra, calls) for s in seats for (f, ph, act, extra, calls) in decisions(run, s)), key=lambda x: (x[0], x[1]))
    cmds = {s: command_frames(run, s) for s in seats}
    launched = datetime.fromtimestamp((run / "launch.json").stat().st_mtime if (run / "launch.json").exists() else run.stat().st_mtime, tz=timezone.utc).astimezone()
    traj = m.get("trajectories") or {}
    last_frame = max([num(t.get("last_frame")) for t in traj.values()] or [0])
    phases = [{"phase_id": "match_start", "actions": [], "eligible": seats, "mode": "simultaneous", "status": "succeeded",
               "consequences": {"map": launch.get("map_path"), "seats": {s: races[s] for s in seats}, "timeout_seconds": launch.get("timeout_seconds")},
               "post_state": state(decs[0][0] if decs else 0)}]
    for i, (f, s, ph, act, extra, calls) in enumerate(decs):
        nxt = decs[i + 1][0] if i + 1 < len(decs) else last_frame
        later = [g for g in decs[i + 1:] if g[1] == s]
        until = later[0][0] if later else last_frame
        own = at(snaps[s], f) or {}
        obs = {"frame": f, "view": own, **{k: v for k, v in extra.items() if v}}
        n_cmd = sum(1 for c in cmds[s] if f <= c < until)
        jev = ph in JEV_PHASES
        who = "Jev" if jev else STRATEGIST_NAME.get(backends.get(s), s)
        phases.append({"phase_id": ph, "eligible": [s], "mode": "single", "status": "succeeded",
                       "actions": [{"seat": s, "actor": who, "role": f"Jev tactician for {races[s]}" if jev else f"{races[s]} strategist", "profile": s,
                                    "model": "Jev (tactical chooser)" if jev else f"{backends.get(s) or s} strategist",
                                    "observation": obs, "parsed": {"ok": True, "action": act}, "legal": {"legal": True}, "valid": True,
                                    "provider": {"calls": calls}}],  # cost and tokens are not recorded by these runs
                       "consequences": {"native_commands_before_this_seat_decides_again": n_cmd, "frames_until_this_seat_decides_again": until - f},
                       "post_state": state(nxt)})
    outcome = m.get("outcome") or {}
    results = {s: (traj.get(s) or {}).get("terminal_result") for s in seats}
    out = {"decision": m.get("status_note") or m.get("capture_status"), "winner": outcome.get("winner"), "result_status": outcome.get("status"),
           "capture_status": m.get("capture_status"), "admission": report.get("admission") or "no iteration report",
           "frames": last_frame, **{f"{s}_result": results[s] for s in seats},
           "trajectory_status": {s: (traj.get(s) or {}).get("status") for s in seats},
           "observability_limits": m.get("observability_limits")}
    seat_rep = {x.get("seat_id") or x.get("seat"): x for x in (report.get("seats") or []) if isinstance(x, dict)}
    lens_case = scrub({"receipt_sha256": m.get("manifest_sha256"), "case_id": run.name, "cell_id": m.get("cell_id"), "kind": "sealed", "phases": phases,
                       "profiles": {s: {"model": {"model": f"{backends.get(s) or s} strategist, Jev tactician", "provider": races[s]}} for s in seats},
                       "outcome": out, "terminal": {"reason": out["decision"]},
                       "world": {"source": launch.get("map_path"), "payload": {"map": launch.get("map_path"), "map_sha256": launch.get("map_sha256"),
                                 "seats": launch.get("seats"), "timeout_seconds": launch.get("timeout_seconds"), "frame_delay_ms": launch.get("frame_delay_ms"),
                                 "macro_lanes_per_model_seat": launch.get("macro_lanes_per_model_seat"), "game_data_sha256": launch.get("game_data_sha256")}},
                       "source": f"starcraft_master/runs/{run.name}", "receipt_status": m.get("capture_status")}, run)
    goals = {s: sum(1 for d in decs if d[1] == s and d[2] == "goal") for s in seats}
    row = {"launched": launched.strftime("%Y-%m-%d %H:%M"), "end": out["decision"], "winner": outcome.get("winner") or "—",
           "verified": outcome.get("status"), "frames": last_frame, **{f"{s}_result": results[s] or "—" for s in seats},
           **{f"{s}_goals": goals[s] for s in seats}, **{f"{s}_replans": num((seat_rep.get(s) or {}).get("goal_replans"), None) for s in seats}}
    case = {"case_id": run.name, "cell_id": m.get("cell_id"), "episode_attempt_id": m.get("episode_attempt_id") or run.name,
            "receipt_sha256": m.get("manifest_sha256"), "profiles": [f"{s} ({races[s]})" for s in seats],
            "steps_count": sum(len(p["actions"]) for p in phases), "invalid_steps": 0, "cost": None, "outcome_row": row}
    return case, lens_case, launched, [p["phase_id"] for p in phases], backends, races


def main():
    runs = sorted(p for p in RUNS.glob("mode-*.*") if (p / "manifest.json").exists())
    if not runs:
        print("starcraft: no sealed match under", RUNS); return
    reports = RUNS / "iteration-reports"
    built = []
    for run in runs:
        try:
            built.append(build_case(run, reports))
        except Exception as error:  # one unreadable match does not stop the rest
            print(f"starcraft: skipped {run.name}: {error}")
    built.sort(key=lambda b: b[2], reverse=True)  # newest match first
    cases = [b[0] for b in built]; lens_cases = [b[1] for b in built]
    seq = [b[3] for b in built]
    nodes = []
    for s in seq:
        for n in s:
            if n not in nodes:
                nodes.append(n)
    edges = sorted({(a, b) for s in seq for a, b in zip(s, s[1:])})
    (OUT / "data" / "campaigns").mkdir(parents=True, exist_ok=True); (OUT / "data" / "lens").mkdir(parents=True, exist_ok=True)
    cfile = f"data/campaigns/{BID}.json"; lfile = f"data/lens/{BID}.json"
    pack(OUT / cfile, {"campaign_id": BID, "family": FAMILY, "source": "sealed_logs", "thin": True, "cases": cases,
                       "graph": {"nodes": nodes, "edges": [{"from": a, "to": b} for a, b in edges]}})
    lbytes = pack(OUT / lfile, {"campaign_id": BID, "cases": lens_cases})
    idx_path = OUT / "data" / "lens" / "index.json"
    idx = json.loads(idx_path.read_text()) if idx_path.exists() else {}
    idx[BID] = {"kind": "sealed", "file": lfile, "cases": len(lens_cases), "sealed": len(lens_cases),
                "note": "local OpenBW prototype matches; steps are strategist decisions"}
    idx_path.write_text(json.dumps(idx, separators=(",", ":")))
    ends = Counter(c["outcome_row"]["end"] for c in cases)
    verified = [c for c in cases if c["outcome_row"]["verified"] == "verified_by_both_seats"]
    wins = Counter(c["outcome_row"]["winner"] for c in verified)
    backends = {k: v for b in built for k, v in b[4].items() if v}
    races = {k: v for b in built for k, v in b[5].items()}
    newest = built[0][2]; oldest = built[-1][2]
    headline = (f"{len(cases)} matches · {len(verified)} with a result both seats verified ("
                + ", ".join(f"{n} won by {w}" for w, n in wins.most_common()) + ") · " + ", ".join(f"{n} {e}" for e, n in ends.most_common()))
    entry = {
        "id": BID, "path": "starcraft_master/runs (local, not in the AERead repository)", "family": FAMILY, "family_label": LABEL, "checkout": None,
        "external": True, "external_note": "Local runs of the starcraft_master OpenBW prototype. Every manifest says “AERead-inspired local evidence; not an AERead EvaluationReceipt” and every iteration report “sealed_partial_diagnostic_only”: these are diagnostics, not an AERead family, campaign or model comparison, and no score should be read from them. The AERead validity checklist and QC profile do not apply.",
        "stem": BID, "version": None, "version_number": 0.0, "variant": "", "date": newest.strftime("%Y-%m-%d"),
        "manifest": {k: None for k in ("schema_version", "campaign_id", "publication_id", "claim_status", "cost_qualifier", "total_cost_usd",
                                       "winner_claim_allowed", "inferential_model_ranking_allowed", "causal_condition_effect_allowed", "prior_pilot_attempts")},
        "artifact_count": None, "source_receipts": len(cases),
        "readme": {"excerpt": "StarCraft: Brood War matches on the OpenBW engine: a Codex strategist (Protoss) against a Claude strategist (Zerg), each with Jev as the tactician, on (2)Challenger. Each step here is one decision: the strategist model's goals, goal reviews, engagement postures and concession reviews, and Jev's tactical missions. The state beyond a seat's view is the opponent's economy and army at that moment. Research backlog: docs/research/starcraft_rts_case_candidates.md.",
                   "summary": f"Codex (Protoss) vs Claude (Zerg) strategists with Jev tactics on OpenBW; {len(cases)} local matches, {oldest:%Y-%m-%d %H:%M} to {newest:%H:%M}."},
        "models": [f"{backends.get(s, s)} · {races.get(s, '')}" for s in ("codex", "claude") if s in races],
        "headline": headline, "facts": [], "issues": [], "qc": {"sections": []},
        "status": {"label": "local prototype · not AERead evidence", "claim_status": None,
                   "readme_sentence": "These are not an AERead family, registered cases, a generated failure register, a qualified campaign, or model-comparison results.",
                   "fact_evidence": ["manifest: format_relation = AERead-inspired local evidence; not an AERead EvaluationReceipt",
                                     "iteration reports: admission = sealed_partial_diagnostic_only"],
                   "open_issues": 0, "direct_issues": 0},
        "grain": {"family": FAMILY, "source": "sealed_logs", "cases": len(cases), "rows": sum(c["steps_count"] for c in cases),
                  "steps_per_case": round(sum(c["steps_count"] for c in cases) / max(1, len(cases)), 1), "phases": nodes,
                  "profiles": 2, "scripted_profiles": 0, "profile_ids": [f"{s} strategist ({races.get(s, '')})" for s in ("codex", "claude") if s in races],
                  "invalid_steps": 0, "cost_usd": None},
        "trajectory_file": cfile, "checklist": [],
        "chain": {"stem": BID, "position": 1, "length": 1, "latest": True, "members": [BID]},
        "order": {"rank": 1, "of": 1, "at": newest.strftime("%Y-%m-%dT%H:%M:%S"), "basis": "match launch times on this machine",
                  "summary": f"{len(cases)} local OpenBW matches, Codex vs Claude strategists with Jev tactics"},
    }
    cat_path = OUT / "data" / "catalog.json"
    cat = json.loads(cat_path.read_text())
    cat["campaigns"] = [c for c in cat["campaigns"] if c.get("family") != FAMILY] + [entry]
    cat["families"] = sorted(set(cat["families"]) | {FAMILY})
    cat["family_label"][FAMILY] = LABEL
    cat.setdefault("declared_graphs", {})[FAMILY] = [LOOP]
    cat_path.write_text(json.dumps(cat, separators=(",", ":"), default=str))
    det_path = OUT / "data" / "check_details.json"
    if det_path.exists():
        det = load(det_path)
        det.setdefault("campaigns", {})[BID] = {"path": "starcraft_master/runs", "checkout": "local", "files": [], "items": {}}
        pack(det_path, det)
    blob = (OUT / lfile).read_bytes() + (OUT / cfile).read_bytes()
    leaked = LOCAL.search(gzip.decompress(base64.b64decode(json.loads((OUT / lfile).read_text())["payload"])).decode())
    print(f"starcraft: {len(cases)} matches, {sum(c['steps_count'] for c in cases)} decisions, lens {lbytes / 1e6:.1f} MB packed"
          + (f" | LOCAL PATH LEFT: {leaked.group(0)[:60]}" if leaked else " | no local paths"))


main()
