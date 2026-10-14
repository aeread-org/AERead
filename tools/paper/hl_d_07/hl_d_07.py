"""HL-D-07: recompute the Housing v14 primary measure at the posterior given everything seat 0 observed.

Offline. Reads the published v14 bundle and its declared Gemini fill (for the reproduction check), the sealed
run roots (for seat 0's per-round inspections, offers and landlord replies), and the worktree code. Writes only
to this script's folder.

Run (from anywhere):
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<worktree>/src <worktree-or-shared>/.venv/bin/python hl_d_07.py
"""
from __future__ import annotations

import os
import glob
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any, Mapping

WT = Path(os.environ["AEREAD_HOUSING_ROOT"])  # a checkout of codex/housing-lemons-outside-demand with its runs/
OUT = Path(__file__).resolve().parent
V14 = WT / "evidence/housing/housing_lemons_price_confirmatory_v14"
FILL = WT / "evidence/housing/housing_lemons_price_confirmatory_v14_gemini_fill"
RUNS = WT / "runs"

from aeread_families.housing import lemons, price_bargaining, price_endpoint as pe, price_publication as pp  # noqa: E402

TOL = 1e-6
LEMON_COUNT, LISTINGS, LOSS = 2, 4, 1000.0
SHORT = {"housing_lemons_price_confirmatory_v14_glm53_flash_nextbit": "GLM",
         "housing_lemons_price_confirmatory_v14_gpt6_luna": "Luna",
         "housing_lemons_price_confirmatory_v14_gemini38_flash": "Gemini"}
GEMINI = "housing_lemons_price_confirmatory_v14_gemini38_flash"


# ---------------------------------------------------------------------------------------------
# The corrected measure
# ---------------------------------------------------------------------------------------------

def reply_quality(arm: str, offer: float, hold_rent: float, floor: float) -> str | None:
    """What one landlord reply proves about its listing, given the true landlord arm.

    Pooled arm: the landlord reserves on the sound-equivalent cost whatever the quality, so no reply says
    anything. Leaky arm (``true_cost``): an offer at or above the sound floor is accepted by both qualities
    (uninformative); an offer below it is answered below the floor by a lemon (accept or counter at the lemon
    target) and countered exactly at the floor by a sound listing.
    """
    if arm != "true_cost" or offer >= floor - TOL:
        return None
    if hold_rent < floor - TOL:
        return "lemon"
    if abs(hold_rent - floor) <= TOL:
        return "sound"
    raise ValueError(f"reply {hold_rent} to an offer {offer} below the floor {floor} is neither below nor at it")


def lemon_posterior(listing: int, known: Mapping[int, str], lemon_count: int = LEMON_COUNT,
                    num_listings: int = LISTINGS) -> float:
    """P(listing is a lemon | known qualities), exchangeable prior with exactly ``lemon_count`` lemons."""
    if listing in known:
        return 1.0 if known[listing] == "lemon" else 0.0
    unknown = num_listings - len(known)
    lemons_known = sum(q == "lemon" for q in known.values())
    return min(1.0, max(0.0, (lemon_count - lemons_known) / unknown))


def knowledge(arm: str, round_index: int, inspections: Mapping[int, tuple[int, str]],
              replies: Mapping[int, Mapping[str, Any]], floors: Mapping[int, float]) -> tuple[dict, dict]:
    """(inspected, reply-revealed) qualities seat 0 holds at the commit phase of ``round_index``.

    ``inspections``: listing -> (round inspected, quality). ``replies``: round -> {listing, offer, hold}.
    Within a round the order is inspect, contact, respond, commit, so a commit decision sees its own round's
    inspection and reply.
    """
    inspected = {l: q for l, (r, q) in inspections.items() if r <= round_index}
    revealed: dict[int, str] = {}
    for r, reply in replies.items():
        if r > round_index:
            continue
        q = reply_quality(arm, reply["offer"], reply["hold"], floors[reply["listing"]])
        if q is not None:
            revealed[reply["listing"]] = q
    return inspected, revealed


def measures(arm: str, decision: Mapping[str, Any], inspections, replies, floors, sound_value: float) -> dict[str, Any]:
    """Lemon probability of one blind decision under the published rule, gap (1) only, and the full posterior."""
    r, listing = int(decision["round_index"]), int(decision["listing_id"])
    inspected, revealed = knowledge(arm, r, inspections, replies, floors)
    stated_p = lemon_posterior(listing, inspected) if listing not in inspected else None
    # the environment's recorded value is the stated-odds value; check we reproduce it
    stated_value = round(sound_value - stated_p * LOSS, 2)
    if abs(stated_value - float(decision["expected_value"])) > 0.011:
        raise AssertionError(f"stated value {stated_value} != recorded {decision['expected_value']} for {decision}")
    published_p = 1.0 if (arm == "true_cost" and float(decision["rent"]) < floors[listing] - TOL) else stated_p
    gap1_p = lemon_posterior(listing, {listing: revealed[listing]}) if listing in revealed else stated_p
    full_p = lemon_posterior(listing, {**inspected, **revealed})
    current = replies.get(r)
    current_q = reply_quality(arm, current["offer"], current["hold"], floors[listing]) if current else None
    earlier_same = [rr for rr, rep in replies.items() if rr < r and rep["listing"] == listing
                    and reply_quality(arm, rep["offer"], rep["hold"], floors[listing]) is not None]
    others = {l: q for l, q in revealed.items() if l != listing and l not in inspected}

    def value(p: float) -> float:
        return float(decision["expected_value"]) if abs(p - stated_p) < 1e-12 else round(sound_value - p * LOSS, 2)

    return {"p_stated": stated_p, "p_published": published_p, "p_gap1": gap1_p, "p_full": full_p,
            "v_published": round(sound_value - LOSS, 2) if published_p != stated_p else float(decision["expected_value"]),
            "v_gap1": value(gap1_p), "v_full": value(full_p),
            "current_reply": current_q, "earlier_same_listing_reveal": bool(earlier_same),
            "other_listings_revealed": others}


# ---------------------------------------------------------------------------------------------
# Hand-built tests
# ---------------------------------------------------------------------------------------------

def run_tests() -> list[str]:
    passed = []
    floors = {0: 2000.0, 1: 2100.0, 2: 1900.0, 3: 2500.0}

    def check(name, got, want):
        assert abs(got - want) < 1e-12, (name, got, want)
        passed.append(name)

    check("no information: 2 of 4", lemon_posterior(0, {}), 0.5)
    check("one lemon inspected: 1 of 3", lemon_posterior(1, {0: "lemon"}), 1 / 3)
    check("one sound inspected: 2 of 3", lemon_posterior(1, {0: "sound"}), 2 / 3)
    check("both lemons known: 0", lemon_posterior(3, {0: "lemon", 1: "lemon"}), 0.0)
    check("two sound known: 1", lemon_posterior(3, {0: "sound", 1: "sound"}), 1.0)
    assert reply_quality("true_cost", 1500.0, 1020.0, 2000.0) == "lemon"; passed.append("leaky: counter below floor -> lemon")
    assert reply_quality("true_cost", 1500.0, 1500.0, 2000.0) == "lemon"; passed.append("leaky: acceptance below floor -> lemon")
    assert reply_quality("true_cost", 1500.0, 2000.0, 2000.0) == "sound"; passed.append("leaky: counter at floor -> sound")
    assert reply_quality("true_cost", 2000.0, 2000.0, 2000.0) is None; passed.append("leaky: acceptance at floor -> none")
    assert reply_quality("true_cost", 2300.0, 2300.0, 2000.0) is None; passed.append("leaky: acceptance above floor -> none")
    assert reply_quality("pooled", 1500.0, 2000.0, 2000.0) is None; passed.append("pooled: counter at floor -> none")
    assert reply_quality("pooled", 0.0, 2025.0, 2000.0) is None; passed.append("pooled: any reply -> none")
    try:
        reply_quality("true_cost", 1500.0, 2050.0, 2000.0)
        raise AssertionError("inconsistent reply accepted")
    except ValueError:
        passed.append("leaky: reply above floor to an offer below it -> error")
    # decision-level cases: (arm, decision, inspections, replies) -> (p_published, p_gap1, p_full)
    sv = 3000.0

    def dec(r, l, rent, p):
        return {"round_index": r, "listing_id": l, "rent": rent, "expected_value": round(sv - p * LOSS, 2)}

    # gap 1: counter at the sound floor on the signed listing, round 0, nothing inspected
    m = measures("true_cost", dec(0, 0, 2000.0, 0.5), {}, {0: {"listing": 0, "offer": 1500.0, "hold": 2000.0}}, floors, sv)
    check("gap1: published stated 0.5", m["p_published"], 0.5); check("gap1: corrected 0", m["p_full"], 0.0)
    check("gap1: gap1-only 0", m["p_gap1"], 0.0)
    # same in pooled: nothing changes
    m = measures("pooled", dec(0, 0, 2000.0, 0.5), {}, {0: {"listing": 0, "offer": 1500.0, "hold": 2000.0}}, floors, sv)
    check("pooled: unchanged", m["p_full"], 0.5)
    # published case: hold below floor on the signed listing -> 1 under all three
    m = measures("true_cost", dec(0, 0, 1020.0, 0.5), {}, {0: {"listing": 0, "offer": 900.0, "hold": 1020.0}}, floors, sv)
    check("published lemon: 1", m["p_published"], 1.0); check("published lemon: full 1", m["p_full"], 1.0)
    # gap 2: round 0 reply proves listing 1 a lemon, round 1 signs listing 0 at an uninformative acceptance
    reps = {0: {"listing": 1, "offer": 1000.0, "hold": 1100.0}, 1: {"listing": 0, "offer": 2200.0, "hold": 2200.0}}
    m = measures("true_cost", dec(1, 0, 2200.0, 0.5), {}, reps, floors, sv)
    check("gap2 lemon elsewhere: published 0.5", m["p_published"], 0.5)
    check("gap2 lemon elsewhere: gap1-only 0.5", m["p_gap1"], 0.5)
    check("gap2 lemon elsewhere: full 1/3", m["p_full"], 1 / 3)
    # gap 2, sound elsewhere plus a lemon inspected: listing 2 inspected lemon r0, listing 1 counter at floor r0
    reps = {0: {"listing": 1, "offer": 1500.0, "hold": 2100.0}, 1: {"listing": 0, "offer": 2200.0, "hold": 2200.0}}
    m = measures("true_cost", dec(1, 0, 2200.0, 1 / 3), {2: (0, "lemon")}, reps, floors, sv)
    check("gap2 sound elsewhere: stated 1/3", m["p_published"], 1 / 3)
    check("gap2 sound elsewhere: full 1/2", m["p_full"], 0.5)
    # both lemons known (one inspected, one by reply) -> the remaining unknown is sound
    reps = {0: {"listing": 1, "offer": 1000.0, "hold": 1100.0}, 1: {"listing": 0, "offer": 2200.0, "hold": 2200.0}}
    m = measures("true_cost", dec(1, 0, 2200.0, 1 / 3), {2: (0, "lemon")}, reps, floors, sv)
    check("two lemons known: full 0", m["p_full"], 0.0)
    # a listing both inspected and reply-revealed counts once
    reps = {0: {"listing": 2, "offer": 1000.0, "hold": 1100.0}, 1: {"listing": 0, "offer": 2200.0, "hold": 2200.0}}
    m = measures("true_cost", dec(1, 0, 2200.0, 1 / 3), {2: (0, "lemon")}, reps, floors, sv)
    check("inspected and revealed counted once: 1/3", m["p_full"], 1 / 3)
    # a reply in a later round is not used for an earlier decision
    reps = {0: {"listing": 0, "offer": 2200.0, "hold": 2200.0}, 1: {"listing": 1, "offer": 1000.0, "hold": 1100.0}}
    m = measures("true_cost", dec(0, 0, 2200.0, 0.5), {}, reps, floors, sv)
    check("later reply ignored: 0.5", m["p_full"], 0.5)
    # earlier-round reveal on the same listing, later uninformative acceptance (not in the published rule)
    reps = {0: {"listing": 0, "offer": 1500.0, "hold": 2000.0}, 1: {"listing": 0, "offer": 2000.0, "hold": 2000.0}}
    m = measures("true_cost", dec(1, 0, 2000.0, 0.5), {}, reps, floors, sv)
    check("earlier same-listing sound: published 0.5", m["p_published"], 0.5)
    check("earlier same-listing sound: gap1 0", m["p_gap1"], 0.0)
    # property test against the real landlord rule: on pack worlds, every offer level, the reply never lies
    from aeread_families.housing import price_campaign
    seeds = [s for part in ("main", "holdout") for v in price_campaign.PACK[part]["by_stratum"].values() for s in v]
    bad = 0
    informative = 0
    ask_below_cost = 0
    for seed in seeds:
        world = lemons.make_lemons_world(6, 4, seed, 0.6, lemon_share=0.5, lemon_loss=1000.0, inspection_cost=25.0,
                                         landlord_reservation="true_cost")
        for l in range(4):
            floor = pe.sound_floor(world, l)
            if float(world.ask[l]) < float(world.sound_costs[l]):
                ask_below_cost += 1
            truth = "lemon" if world.quality[l] == lemons.LEMON else "sound"
            for offer in (0.0, floor - 1100, floor - 600, floor - 30, floor - 1, floor - 0.01, floor, floor + 5,
                          float(world.ask[l])):
                offer = max(0.0, round(offer, 2))
                obs = {"inbox": [{"offer_id": "o", "tenant_id": 0, "rent": offer, "listing_id": l}],
                       "private_cost": world.costs[l], "listing": {"rent_asked": world.ask[l]}}
                action = price_bargaining.landlord_action(obs)
                hold = offer if action["decision"] == "accept" else action["counter_rent"]
                q = reply_quality("true_cost", offer, hold, floor)
                informative += q is not None
                bad += q is not None and q != truth
    assert bad == 0, bad
    passed.append(f"real landlord rule on {len(seeds)} pack worlds x 4 listings x 9 offers: {informative} informative "
                  f"replies, 0 wrong; listings with ask below sound cost: {ask_below_cost}")
    return passed


# ---------------------------------------------------------------------------------------------
# Sealed trajectories
# ---------------------------------------------------------------------------------------------

INSPECTION_REF = re.compile(r"inspection:r(\d+):t0:l(\d+)")


def trajectory(cell_json: Path) -> dict[str, Any]:
    """Seat 0's inspections, offers and replies from a cell's sealed event log."""
    ev_root = cell_json.with_name(cell_json.stem + "_evidence")
    attempts = sorted(glob.glob(str(ev_root / "runplan_*/tasks/*/attempts/*/events.jsonl")))
    if len(attempts) != 1:
        raise ValueError(f"{len(attempts)} attempts under {ev_root}")
    base = Path(attempts[0]).parent
    inspections: dict[int, int] = {}
    last_state = None
    outcome = None
    for line in Path(attempts[0]).read_text().splitlines():
        event = json.loads(line)
        if event["event_type"] == "transition_applied":
            payload = json.loads((base / event["payload_ref"]).read_text())
            if payload["phase_id"] == "inspect":
                for verdict in payload["transition"]["consequences"]["verdicts"]:
                    if verdict["actor_id"] == 0 and verdict["outcome"] == "applied":
                        r, l = map(int, INSPECTION_REF.fullmatch(verdict["reference_id"]).groups())
                        assert l not in inspections
                        inspections[l] = r
            last_state = payload["transition"]["state"]
        elif event["event_type"] == "family_outcome_recorded":
            outcome = json.loads((base / event["payload_ref"]).read_text())["outcome"]
    offers, holds = {}, {}
    for h in last_state["history"]:
        if h.get("tenant_id") != 0:
            continue
        if h["event"] == "offer":
            assert h["round_index"] not in offers
            offers[h["round_index"]] = (int(h["listing_id"]), float(h["rent"]))
        elif h["event"] == "hold":
            assert h["round_index"] not in holds
            holds[h["round_index"]] = (int(h["listing_id"]), float(h["binding_rent"]), h["landlord"])
    replies = {}
    for r, (l, rent, text) in holds.items():
        ol, orent = offers[r]
        assert ol == l, (cell_json, r)
        replies[r] = {"listing": l, "offer": orent, "hold": rent, "text": text}
    # the sealed state's own inspection record agrees
    seat0 = next(x for x in last_state["inspected"] if x["tenant_id"] == 0)
    assert {int(i["listing_id"]) for i in seat0["items"]} == set(inspections), cell_json
    return {"inspections": inspections, "replies": replies, "outcome": outcome}


def score_cell(cell_json: Path) -> dict[str, Any]:
    row = json.loads(cell_json.read_text())
    seed, arm = int(row["world_seed"]), row["arm"]
    traj = trajectory(cell_json)
    facts = row["outcome_facts"]
    assert traj["outcome"]["commit_decisions"] == facts["commit_decisions"], cell_json
    world = lemons.make_lemons_world(6, 4, seed, 0.6, lemon_share=0.5, lemon_loss=1000.0, inspection_cost=25.0,
                                     landlord_reservation=arm)
    floors = {l: pe.sound_floor(world, l) for l in range(4)}
    quality = {l: ("lemon" if world.quality[l] == lemons.LEMON else "sound") for l in range(4)}
    inspections = {l: (r, quality[l]) for l, r in traj["inspections"].items()}
    # reply text agrees with the numbers, and every informative reply tells the truth
    for r, rep in traj["replies"].items():
        accepted = rep["text"] == "accepted your offer"
        assert accepted == (abs(rep["hold"] - rep["offer"]) < 0.005), (cell_json, rep)
        q = reply_quality(arm, rep["offer"], rep["hold"], floors[rep["listing"]])
        assert q is None or q == quality[rep["listing"]], (cell_json, rep, q)
    published = pe.score_cell(facts, world_seed=seed, arm=arm)
    seat = published["by_seat"][0]
    decisions = []
    for d in facts["commit_decisions"]:
        if int(d["tenant_id"]) != 0:
            continue
        r = int(d["round_index"])
        rep = traj["replies"][r]
        assert rep["listing"] == int(d["listing_id"]) and abs(rep["hold"] - float(d["rent"])) < 0.005, (cell_json, d)
        informed = int(d["listing_id"]) in {l for l, (ri, _) in inspections.items() if ri <= r}
        assert informed == bool(d["informed"]), (cell_json, d)
        if d["informed"] or d["decision"] != "sign":
            continue
        sound_value = float(world.values_if_sound[0][int(d["listing_id"])])
        m = measures(arm, d, inspections, traj["replies"], floors, sound_value)
        decisions.append({**m, "round_index": r, "listing_id": int(d["listing_id"]), "rent": float(d["rent"]),
                          "quality": d["quality"], "arm": arm})
    # reproduce the published seat-0 primary from the decision values
    pub_rows = {(x["round_index"], x["listing_id"]): x for x in published["decisions"]
                if x["tenant_id"] == 0 and x["decision"] == "sign" and not x["informed"]}
    for x in decisions:
        assert abs(pub_rows[(x["round_index"], x["listing_id"])]["expected_value_response"] - x["v_published"]) < 0.006
    base = seat["net_expected_response_odds"]
    d_gap1 = sum(x["v_gap1"] - x["v_published"] for x in decisions)
    d_full = sum(x["v_full"] - x["v_published"] for x in decisions)
    return {"world_seed": seed, "arm": arm, "primary_published": base,
            "primary_gap1": round(base + d_gap1, 2), "primary_corrected": round(base + d_full, 2),
            "delta_gap1": round(d_gap1, 2), "delta_full": round(d_full, 2), "blind_signings": decisions,
            "informative_replies": sum(reply_quality(arm, rep["offer"], rep["hold"], floors[rep["listing"]]) is not None
                                       for rep in traj["replies"].values())}


# ---------------------------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------------------------

def jround(x):
    return json.loads(json.dumps(x))


def with_primary(rows, scored, key):
    out = []
    for r in rows:
        r = dict(r)
        if r["status"] == "completed":
            r[pp.PRIMARY] = scored[(r["world_seed"], r["arm"])][key]
        out.append(r)
    return out


def summary(report) -> dict[str, Any]:
    """The step-1 numbers, oriented as the task states them (Gemini first)."""
    def fmt(iv):
        return {"mean": iv["mean"], "lo": iv["lo"], "hi": iv["hi"], "n": iv["n"]}
    out = {"models": {}, "pairs": {}}
    for m, e in report["models"].items():
        s = e["by_scope"]
        out["models"][SHORT[m]] = {sc: {"primary": fmt(s[sc]["primary"]), "minus_reference": fmt(s[sc]["minus_reference"])}
                                   for sc in s}
    for k, v in report["pairs"].items():
        a, b = (SHORT[x] for x in k.split(" - "))
        flip = b == "Gemini"  # report Gemini - X as the task does
        name = f"{b}-{a}" if flip else f"{a}-{b}"
        sign = -1 if flip else 1

        def o(iv):
            if iv["mean"] is None:
                return None
            lo, hi = sign * iv["lo"], sign * iv["hi"]
            return {"mean": round(sign * iv["mean"], 2), "lo": min(lo, hi), "hi": max(lo, hi), "n": iv["n"], "p": iv["p"]}
        out["pairs"][name] = {"main": {**o(v["main"]), "p_holm": v["main"]["p_holm"],
                                       "separated_after_holm": v["main"]["separated_after_holm"],
                                       "at_least_50": v["main"]["at_least_minimum_meaningful"]},
                              "holdout": o(v["holdout"])}
    return out


def strata_pairs(rows_by_model, key="main") -> dict[str, Any]:
    """Not declared: the pairwise contrasts within each favourite stratum (for the strata verdict only)."""
    out = {}
    models = list(rows_by_model)
    for stratum in ("favourite_is_lemon", "favourite_is_sound"):
        for i in range(len(models)):
            for j in range(i + 1, len(models)):
                a, b = models[i], models[j]
                la = pp.per_world(rows_by_model[a], pp.PRIMARY, population="main", stratum=stratum)
                lb = pp.per_world(rows_by_model[b], pp.PRIMARY, population="main", stratum=stratum)
                both = sorted(set(la) & set(lb))
                iv = pp._interval([la[s] - lb[s] for s in both])
                out[f"{stratum}: {SHORT[a]}-{SHORT[b]}"] = {k: iv[k] for k in ("n", "mean", "lo", "hi", "p")}
    return out


def counts(scored_by_model, rows_by_model) -> dict[str, Any]:
    out = {}
    for model, scored in scored_by_model.items():
        meta = {(r["world_seed"], r["arm"]): r for r in rows_by_model[model]}
        groups: dict[str, dict[str, Any]] = {}

        def add(group, x, cell):
            g = groups.setdefault(group, {"blind_signings": 0, "changed_full": 0, "changed_gap1": 0,
                                          "changed_gap2": 0, "current_round_sound_counter": 0,
                                          "earlier_round_same_listing": 0, "gap2_lemon_elsewhere": 0,
                                          "gap2_sound_elsewhere": 0, "sum_delta_full": 0.0, "sum_delta_gap1": 0.0,
                                          "sum_delta_gap2": 0.0})
            g["blind_signings"] += 1
            g["changed_full"] += abs(x["v_full"] - x["v_published"]) > 0.005
            g["changed_gap1"] += abs(x["v_gap1"] - x["v_published"]) > 0.005
            g["changed_gap2"] += abs(x["v_full"] - x["v_gap1"]) > 0.005
            g["current_round_sound_counter"] += x["current_reply"] == "sound"
            g["earlier_round_same_listing"] += (x["earlier_same_listing_reveal"] and x["current_reply"] is None
                                                and abs(x["v_gap1"] - x["v_published"]) > 0.005)
            if abs(x["v_full"] - x["v_gap1"]) > 0.005:
                qs = set(x["other_listings_revealed"].values())
                g["gap2_lemon_elsewhere"] += "lemon" in qs
                g["gap2_sound_elsewhere"] += "sound" in qs
            g["sum_delta_full"] += x["v_full"] - x["v_published"]
            g["sum_delta_gap1"] += x["v_gap1"] - x["v_published"]
            g["sum_delta_gap2"] += x["v_full"] - x["v_gap1"]
        for key, cell in scored.items():
            r = meta[key]
            for x in cell["blind_signings"]:
                for group in ("all", f"{r['population']}", f"{r['population']}/{cell['arm']}",
                              f"{r['population']}/{r['stratum']}", f"{r['population']}/{r['stratum']}/{cell['arm']}"):
                    add(group, x, cell)
        for g in groups.values():
            for k in ("sum_delta_full", "sum_delta_gap1", "sum_delta_gap2"):
                g[k] = round(g[k], 2)
        # mean change per world, over the worlds the primary uses (main pack, both arms)
        per_world = {}
        for scope, sel in (("main", {"population": "main"}), ("holdout", {"population": "holdout"}),
                           ("main/favourite_is_lemon", {"population": "main", "stratum": "favourite_is_lemon"}),
                           ("main/favourite_is_sound", {"population": "main", "stratum": "favourite_is_sound"})):
            res = {}
            for label, key in (("gap1", "delta_gap1"), ("full", "delta_full")):
                rows = [dict(r, _d=scored[(r["world_seed"], r["arm"])][key]) for r in rows_by_model[model]
                        if r["status"] == "completed"]
                w = pp.per_world(rows, "_d", **sel)
                res[label] = round(statistics.fmean(w.values()), 3) if w else None
                for arm in ("true_cost", "pooled"):
                    cells = [x["_d"] for x in rows if x["arm"] == arm and x["world_seed"] in w]
                    res[f"{label}_per_{arm}_cell"] = round(statistics.fmean(cells), 3) if cells else None
            res["gap2"] = round(res["full"] - res["gap1"], 3) if res["full"] is not None else None
            res["worlds"] = len(w)
            per_world[scope] = res
        out[SHORT[model]] = {"by_group": dict(sorted(groups.items())), "mean_change_per_world": per_world}
    return out


def main() -> int:
    tests = run_tests()
    print(f"{len(tests)} hand-built checks passed")

    # --- step 1: reproduce the published bundle and the fill sensitivity from the run roots ---
    contracts = json.loads((V14 / "reports/contracts.json").read_text())
    rows_by_model = {cid: pp.cell_rows(contracts[cid], RUNS / cid) for cid in pp.V14_PANEL}
    published_rows = {(r["campaign_id"], r["world_seed"], r["arm"]): r
                      for r in map(json.loads, (V14 / "tables/cells.jsonl").read_text().splitlines())}
    mine = {(r["campaign_id"], r["world_seed"], r["arm"]): jround(r) for rows in rows_by_model.values() for r in rows}
    assert mine == published_rows, "rebuilt cell rows differ from the published table"
    report = pp.analysis(rows_by_model)
    assert jround(report) == json.loads((V14 / "reports/analysis.json").read_text()), "analysis differs"
    fill_contract = json.loads((FILL / "reports/contract.json").read_text())
    fill_rows = pp.cell_rows(fill_contract, RUNS / pp.FILL_ID)
    refused = {tuple(c) for c in fill_contract["analysis"]["filled_cells"]}
    for r in fill_rows:
        r["role"] = "filled" if (r["world_seed"], r["arm"]) in refused else "repeat"
    pub_fill = {(r["world_seed"], r["arm"]): r for r in map(json.loads, (FILL / "tables/cells.jsonl").read_text().splitlines())}
    assert {(r["world_seed"], r["arm"]): jround(r) for r in fill_rows} == pub_fill, "fill rows differ"
    fill_by_cell = {(r["world_seed"], r["arm"]): r for r in fill_rows}

    def merged_models(rbm):
        merged = [dict(fill_by_cell[(r["world_seed"], r["arm"])], campaign_id=GEMINI, role="filled")
                  if (r["world_seed"], r["arm"]) in refused else r for r in rbm[GEMINI]]
        out = {cid: rbm[cid] for cid in sorted(rbm) if cid != GEMINI}
        out[GEMINI] = merged
        return out
    fill_report = pp.analysis(merged_models(rows_by_model))
    pub_sens = json.loads((FILL / "reports/sensitivity.json").read_text())["v14_analysis_with_fill"]
    assert jround(fill_report) == pub_sens, "fill sensitivity differs"
    print("reproduced: 1800 v14 rows, analysis.json, 48 fill rows, sensitivity.json (exact)")

    # --- step 2: per-decision posterior from the sealed trajectories ---
    scored_by_model = {}
    for cid in pp.V14_PANEL:
        scored_by_model[cid] = {}
        for r in rows_by_model[cid]:
            if r["status"] == "completed":
                cell = score_cell(RUNS / cid / "live" / f"world_{r['world_seed']}__{r['arm']}.json")
                assert abs(cell["primary_published"] - r[pp.PRIMARY]) < 0.006
                scored_by_model[cid][(r["world_seed"], r["arm"])] = cell
    fill_scored = {}
    for r in fill_rows:
        if r["status"] == "completed":
            cell = score_cell(RUNS / pp.FILL_ID / "live" / f"world_{r['world_seed']}__{r['arm']}.json")
            assert abs(cell["primary_published"] - r[pp.PRIMARY]) < 0.006
            fill_scored[(r["world_seed"], r["arm"])] = cell
    repeats_identical = sum(
        fill_scored[k]["primary_corrected"] == scored_by_model[GEMINI][k]["primary_corrected"]
        for k, r in fill_by_cell.items() if r["role"] == "repeat" and k in scored_by_model[GEMINI])
    print("scored", {SHORT[c]: len(v) for c, v in scored_by_model.items()}, "fill", len(fill_scored),
          "repeats identical under the corrected measure:", repeats_identical)

    # --- step 3: the declared analysis under each measure ---
    results: dict[str, Any] = {"tests": tests, "reproduction": "exact: cells.jsonl (1800), analysis.json, fill cells (48), sensitivity.json"}
    for label, key in (("published", "primary_published"), ("gap1_only", "primary_gap1"), ("corrected", "primary_corrected")):
        rbm = {cid: with_primary(rows_by_model[cid], scored_by_model[cid], key) for cid in pp.V14_PANEL}
        rep = pp.analysis(rbm)
        if label == "published":
            assert jround(rep) == jround(report)
        fill_gem = with_primary(fill_rows, fill_scored, key)
        fb = {(r["world_seed"], r["arm"]): r for r in fill_gem}
        merged = [dict(fb[(r["world_seed"], r["arm"])], campaign_id=GEMINI, role="filled")
                  if (r["world_seed"], r["arm"]) in refused else r for r in rbm[GEMINI]]
        rbm_fill = {cid: rbm[cid] for cid in sorted(rbm) if cid != GEMINI}
        rbm_fill[GEMINI] = merged
        rep_fill = pp.analysis(rbm_fill)
        if label == "published":
            assert jround(rep_fill) == jround(fill_report)
        results[label] = {"v14": summary(rep), "with_fill": summary(rep_fill),
                          "strata_pairs_v14_undeclared": strata_pairs(rbm),
                          "strata_pairs_with_fill_undeclared": strata_pairs(rbm_fill)}
    results["counts_v14"] = counts(scored_by_model, rows_by_model)
    gem_fill_scored = dict(scored_by_model[GEMINI])
    gem_fill_scored.update({k: v for k, v in fill_scored.items() if k in refused})
    gem_fill_rows = [dict(fill_by_cell[(r["world_seed"], r["arm"])], campaign_id=GEMINI)
                     if (r["world_seed"], r["arm"]) in refused else r for r in rows_by_model[GEMINI]]
    results["counts_gemini_with_fill"] = counts({GEMINI: gem_fill_scored}, {GEMINI: gem_fill_rows})["Gemini"]
    # the HL-D-07 count: blind signings whose own current reply was a counter at the sound target
    claim = {}
    for cid, scored in scored_by_model.items():
        meta = {(r["world_seed"], r["arm"]): r for r in rows_by_model[cid]}
        xs = [(meta[k], x) for k, c in scored.items() for x in c["blind_signings"] if x["current_reply"] == "sound"]
        p_counts: dict[str, int] = {}
        for _, x in xs:
            key_p = f"{x['p_stated']:.4f}"
            p_counts[key_p] = p_counts.get(key_p, 0) + 1
        claim[SHORT[cid]] = {"all_populations": len(xs), "main": sum(m["population"] == "main" for m, _ in xs),
                             "stated_p_of_these": p_counts,
                             "value_changes": sum(abs(x["v_gap1"] - x["v_published"]) > 0.005 for _, x in xs),
                             "all_sound": all(x["quality"] == "sound" for _, x in xs),
                             "sum_value_understated_usd": round(sum(x["v_gap1"] - x["v_published"] for _, x in xs), 2)}
        # dollars per world under several denominators
        main_worlds = len(pp.per_world(rows_by_model[cid], pp.PRIMARY))
        main_tc = sum(1 for k in scored if meta[k]["population"] == "main" and k[1] == "true_cost")
        all_tc = sum(1 for k in scored if k[1] == "true_cost")
        s_main = sum(x["v_gap1"] - x["v_published"] for m, x in xs if m["population"] == "main")
        s_all = claim[SHORT[cid]]["sum_value_understated_usd"]
        claim[SHORT[cid]].update({
            "per_main_world_primary(mean of arms)": round(s_main / 2 / main_worlds, 2),
            "per_main_leaky_cell": round(s_main / main_tc, 2),
            "per_leaky_cell_all_populations": round(s_all / all_tc, 2),
            "per_cell_all": round(s_all / len(scored), 2)})
    results["hl_d_07_claim_check"] = claim
    # why gap (2) is empty: every blind signing preceded by an informative reply on another listing
    diag = {}
    for cid, scored in list(scored_by_model.items()) + [("fill", fill_scored)]:
        tab: dict[str, int] = {}
        for (seed, arm), cell in scored.items():
            if arm != "true_cost":
                continue
            t = trajectory(RUNS / (pp.FILL_ID if cid == "fill" else cid) / "live" / f"world_{seed}__{arm}.json")
            world = lemons.make_lemons_world(6, 4, seed, 0.6, lemon_share=0.5, lemon_loss=1000.0, inspection_cost=25.0,
                                             landlord_reservation=arm)
            floors = {l: pe.sound_floor(world, l) for l in range(4)}
            for x in cell["blind_signings"]:
                for rr, rep in t["replies"].items():
                    if rr >= x["round_index"] or rep["listing"] == x["listing_id"]:
                        continue
                    q = reply_quality(arm, rep["offer"], rep["hold"], floors[rep["listing"]])
                    if q is None:
                        continue
                    ir = t["inspections"].get(rep["listing"])
                    k = (f"{q} revealed; that listing {'inspected' if ir is not None and ir <= x['round_index'] else 'not inspected'}"
                         f" by the signing; stated p={x['p_stated']:.4f}")
                    tab[k] = tab.get(k, 0) + 1
        diag[SHORT.get(cid, "Gemini fill")] = tab
    results["gap2_diagnosis_blind_signings_after_an_informative_reply_elsewhere"] = diag
    (OUT / "hl_d_07_results.json").write_text(json.dumps(results, indent=1, sort_keys=True, default=str) + "\n")
    print(json.dumps({k: results[k] for k in ("hl_d_07_claim_check", "gap2_diagnosis_blind_signings_after_an_informative_reply_elsewhere")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
