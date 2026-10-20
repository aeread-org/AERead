"""Does the agreement case's counterpart need its beliefs? The scripted negotiator with and without its belief update.

    PYTHONPATH=src python tools/datacenter/agreement_belief_ablation.py [--processes 8] > OUT.json

The scripted negotiator (``agreement_negotiator``) starts from the declared odds over the other side's type and drops
every type that would have lost money on an offer that side made. This compares it with the same negotiator whose
belief is frozen at the declared odds, everything else equal, as the counterpart of the v2 confirmatory arms (the style
``agreement_admitted_pack.public_style`` draws from the public world) on every deal world of the admitted v2 pack, in
both seats. Opposite it sits, in turn:

- each fixed style of the scripted negotiator, which keeps its own belief update in both runs;
- v1's stand-ins that know both true types: four fixed plans and ``best_plan``, the exact best reply on a grid of asks
  (the told-both-types ceiling);
- when the counterpart is the client, the integrator's own-information best reply (Gate 3's reference).

For each pairing it reports how often the counterpart's own moves differ between the two runs, how often a move on the
updating run would have been different with the frozen belief, and what the change does to each seat's earnings, in
$k and in percent of the world's available surplus. No model is called.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import replace
from multiprocessing import Pool
from typing import Any, Mapping

from aeread_families.datacenter_development import agreement as ag
from aeread_families.datacenter_development import agreement_admitted_pack as aap
from aeread_families.datacenter_development import agreement_admitted_pack_v2 as v2
from aeread_families.datacenter_development import agreement_negotiator as an
from aeread_families.datacenter_development import agreement_negotiator_check as chk
from aeread_families.datacenter_development import agreement_own_information as oi
from aeread_families.datacenter_development import risk_allocation_contracts as rc

STYLES = ("even", "firm", "hard", "soft", "overreach", "price_only", "collapse")
EPS = 1e-6
_UPDATING = an.negotiator_move


class Frozen(an.Negotiator):
    """The same negotiator, its belief held at the declared odds whatever the other side offers."""

    def belief(self, state: Mapping[str, Any]) -> list[an.Other]:
        mass = math.fsum(o.p for o in self.prior)
        return [replace(o, p=o.p / mass) for o in self.prior]


def _frozen_move(state: Mapping[str, Any], cw: rc.CWorld, it: Any, style: Any = "even") -> dict[str, Any]:
    seat = state["to_move"]
    return Frozen(cw, seat, it if seat == "integrator" else None, style).move(state)


def _counterpart(frozen: bool):
    return _frozen_move if frozen else _UPDATING


def _moves_of(state: Mapping[str, Any], seat: str) -> list[Any]:
    return [(h["action"], json.dumps(h.get("changes"), sort_keys=True), h.get("price")) for h in state["history"] if h["by"] == seat]


def _bites(cw: rc.CWorld, it: Any, end: Mapping[str, Any], seat: str, style: Any) -> tuple[int, int, int]:
    """Along a finished updating run: (the counterpart's moves, how many the frozen belief would have changed, how many
    were made with a belief narrower than the declared odds)."""
    state = ag.initial_state(cw)
    moves = changed = narrowed = 0
    for h in end["history"]:
        if state["to_move"] == seat:
            live = an.Negotiator(cw, seat, it if seat == "integrator" else None, style)
            moves += 1
            changed += live.move(state) != _frozen_move(state, cw, it, style)
            narrowed += len(live.belief(state)) < len(live.prior)
        redline = h["action"] == "redline"
        act = {"action": h["action"],
               "clauses": ({k: v["now"] for k, v in (h.get("changes") or {}).items()} if redline else None),
               "price": h.get("price") if redline else None, "note": None}
        state = ag.apply(state, act, cw)
    return moves, changed, narrowed


def _grade(cw: rc.CWorld, it: Any, end: Mapping[str, Any]) -> dict[str, float]:
    g = ag.grade(cw, it, end)
    return {"integrator": g["integrator_surplus"], "client": g["client_surplus"], "lost": g["joint_value_lost"],
            "termination": g["termination"]}


def _style_pairing(cw: rc.CWorld, it: Any, seat: str, style: Any, opponent: str, frozen: bool) -> dict[str, Any]:
    move = _counterpart(frozen)
    state = ag.initial_state(cw)
    while not state["finished"]:
        act = move(state, cw, it, style) if state["to_move"] == seat else _UPDATING(state, cw, it, opponent)
        state = ag.apply(state, act, cw)
    return state


def _with_counterpart(frozen: bool, fn, *args):
    """Run a v1 stand-in or the own-information search with the counterpart's belief frozen or not."""
    an.negotiator_move = _counterpart(frozen)
    try:
        return fn(*args)
    finally:
        an.negotiator_move = _UPDATING


def one_world(job: tuple[str, Mapping[str, Any]]) -> dict[str, Any]:
    code, payload = job
    cw, it = rc.world_from({k: payload[k] for k in ("world", "integrator_type", "extras")})
    available = ag.grade(cw, it, ag.initial_state(cw))["available_surplus"]
    row: dict[str, Any] = {"world": code, "available": available, "seats": {}}
    for seat in ag.SEATS:
        opposite = ag.other(seat)
        style = aap.public_style(cw, seat)
        out: dict[str, Any] = {}
        pairings: dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
        for opponent in STYLES:
            pairings[f"style:{opponent}"] = tuple(_style_pairing(cw, it, seat, style, opponent, f) for f in (False, True))
        for plan in chk.PLANS:
            pairings[f"plan:{plan}"] = tuple(_with_counterpart(f, chk.play, cw, it, opposite, style, plan) for f in (False, True))
        pairings["ceiling"] = tuple(_with_counterpart(f, chk.best_plan, cw, it, opposite, style)[2] for f in (False, True))
        for name, (live, still) in pairings.items():
            a, b = _grade(cw, it, live), _grade(cw, it, still)
            moves, changed, narrowed = _bites(cw, it, live, seat, style)
            out[name] = {"moves_differ": _moves_of(live, seat) != _moves_of(still, seat),
                         "counterpart_moves": moves, "moves_changed_by_belief": changed, "moves_with_narrowed_belief": narrowed,
                         "opponent_updating": a[opposite], "opponent_frozen": b[opposite],
                         "counterpart_updating": a[seat], "counterpart_frozen": b[seat],
                         "terminations": [a["termination"], b["termination"]]}
        if seat == "client":
            live, still = (_with_counterpart(f, oi.own_information, cw, it) for f in (False, True))
            out["own_information"] = {"updating": live, "frozen": still}
        row["seats"][seat] = out
    return row


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    deal = [r for r in rows if r["available"] > EPS]
    out: dict[str, Any] = {"deal_worlds": len(deal)}
    for seat in ag.SEATS:
        names = [n for n in deal[0]["seats"][seat] if n != "own_information"]
        table = {}
        for name in names:
            cells = [(r["available"], r["seats"][seat][name]) for r in deal]
            gap = [100 * (c["opponent_updating"] - c["opponent_frozen"]) / av for av, c in cells]
            mine = [100 * (c["counterpart_updating"] - c["counterpart_frozen"]) / av for av, c in cells]
            table[name] = {
                "worlds_where_counterpart_moves_differ": sum(c["moves_differ"] for _, c in cells),
                "counterpart_moves": sum(c["counterpart_moves"] for _, c in cells),
                "moves_changed_by_belief": sum(c["moves_changed_by_belief"] for _, c in cells),
                "moves_with_narrowed_belief": sum(c["moves_with_narrowed_belief"] for _, c in cells),
                "opponent_earnings_change_pct_mean": round(statistics.fmean(gap), 3),
                "opponent_earnings_change_pct_max_abs": round(max(abs(x) for x in gap), 3),
                "counterpart_earnings_change_pct_mean": round(statistics.fmean(mine), 3),
            }
        out[f"counterpart_{seat}"] = table
    oi_rows = [(r["available"], r["seats"]["client"]["own_information"]) for r in deal]
    keys = [k for k, v in oi_rows[0][1]["updating"].items() if isinstance(v, (int, float))]
    out["own_information_vs_client"] = {
        k: round(statistics.fmean(100 * (o["updating"][k] - o["frozen"][k]) / av for av, o in oi_rows), 3) for k in keys}
    return out


#: The v2 confirmatory arms played against the scripted counterpart, and the seat the script held in each.
RECORDED_ARMS = {"datacenter_agreement_v2_integrator_firm": "client", "datacenter_agreement_v2_client_firm": "integrator"}


def _key(act: Mapping[str, Any]) -> tuple[Any, ...]:
    clauses = act.get("clauses") or {}
    return (act["action"], json.dumps({k: v for k, v in clauses.items() if v is not None}, sort_keys=True), act.get("price"))


def recorded(evidence_root: str) -> dict[str, Any]:
    """On every recorded v2 negotiation against the script: each scripted move rebuilt from the history (it must equal
    the recorded move), and the move the same script would have made with its belief frozen at the declared odds."""
    from pathlib import Path

    _, raw, _ = v2.load(v2.ADMITTED)
    worlds = {c["case_id"]: c["payload"] for c in raw.values()}
    out: dict[str, Any] = {}
    for arm, script_seat in RECORDED_ARMS.items():
        rows = [json.loads(line) for line in open(Path(evidence_root) / arm / "trajectories" / "sanitized.jsonl")]
        episodes: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            episodes.setdefault(row["episode_id"], []).append(row)
        moves = changed = narrowed = mismatched = 0
        by_model: dict[str, list[int]] = {}
        for steps in episodes.values():
            steps.sort(key=lambda r: r["step_index"])
            payload = worlds[steps[0]["case_id"]]
            cw, it = rc.world_from({k: payload[k] for k in ("world", "integrator_type", "extras")})
            style = aap.public_style(cw, script_seat)
            model = "codex" if "codex" in steps[0]["profile_id"] else "claude"
            state = ag.initial_state(cw)
            for step in steps:
                if state["finished"]:
                    break
                act = step["action"]
                if state["to_move"] == script_seat:
                    live = an.Negotiator(cw, script_seat, it if script_seat == "integrator" else None, style)
                    now = live.move(state)
                    mismatched += _key(now) != _key(act)
                    moves += 1
                    differs = _key(_frozen_move(state, cw, it, style)) != _key(now)
                    changed += differs
                    narrowed += len(live.belief(state)) < len(live.prior)
                    by_model.setdefault(model, [0, 0])
                    by_model[model][0] += 1
                    by_model[model][1] += differs
                state = ag.apply(state, act, cw)
        out[arm] = {"script_seat": script_seat, "episodes": len(episodes), "script_moves": moves,
                    "rebuilt_moves_not_matching_the_record": mismatched, "moves_changed_by_a_frozen_belief": changed,
                    "moves_with_narrowed_belief": narrowed,
                    "by_opponent_model": {m: {"script_moves": v[0], "changed": v[1]} for m, v in by_model.items()}}
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--processes", type=int, default=8)
    parser.add_argument("--recorded", metavar="EVIDENCE_ROOT",
                        help="instead: check every recorded v2 negotiation against the script (evidence/datacenter_development)")
    args = parser.parse_args(argv)
    if args.recorded:
        print(json.dumps(recorded(args.recorded), indent=1))
        return 0
    _, raw, _ = v2.load(v2.ADMITTED)
    jobs = [(c["case_id"].rsplit(".", 1)[-1], c["payload"]) for c in sorted(raw.values(), key=lambda c: c["case_id"])]
    with Pool(args.processes) as pool:
        rows = pool.map(one_world, jobs, chunksize=1)
    print(json.dumps({"pack": v2.ADMITTED.pack, "counterpart": "agreement_admitted_pack.public_style",
                      "summary": summarize(rows), "worlds": rows}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
