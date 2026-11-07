"""Free checks of the scripted negotiator, before a model meets it. No model is called.

    PYTHONPATH=src python -m aeread_families.datacenter_development.agreement_negotiator_check [--pack agreement_dev_v1] [--out FILE]

A stand-in for the model sits opposite the script and knows both true types, so what it can earn is a
ceiling, not a prediction. On a deal world it always proposes the best agreement and varies only the
share of the surplus it asks for. Four fixed plans show whether its moves matter, and a search over
every plan on a grid of asks (sign, walk, or ask one of ``GRID``) gives the best plan against this
script: an exact best reply within that grid. The script against itself checks its own conduct.
"""

from __future__ import annotations

import argparse
import json
import random
from collections.abc import Callable, Mapping
from multiprocessing import Pool
from typing import Any

from . import agreement as ag
from . import agreement_negotiator as an
from . import agreement_pack as ap
from . import risk_allocation as ra
from . import risk_allocation_contracts as rc

GRID = tuple(round(0.1 * k, 1) for k in range(1, 11))
EPS = 1e-6


class Informed:
    """What the stand-in works with: the best agreement for the two true types and what there is to share."""

    def __init__(self, cw: rc.CWorld, it: ra.IntegratorType, seat: str) -> None:
        self.cw, self.it, self.seat = cw, it, seat
        self.best = ag.best_agreement(cw, it)
        self.floor, self.outside = cw.w.terms.floor_margin, cw.best_outside[1]
        ic, cc = ag.costs(cw, it, self.best)
        self.ic, self.cc = ic, cc
        self.available = self.outside - self.floor - ic - cc

    def worth(self, state: Mapping[str, Any]) -> float | None:
        """What signing the version on the table is worth to the stand-in, over walking."""
        st = state["standing"]
        if st is None or st["by"] == self.seat:
            return None
        ic, cc = ag.costs(self.cw, self.it, rc.Contract(**state["terms"]))
        return st["price"] - ic - self.floor if self.seat == "integrator" else self.outside - st["price"] - cc

    def ask(self, state: Mapping[str, Any], share: float) -> dict[str, Any]:
        price = self.ic + self.floor + share * self.available if self.seat == "integrator" else self.outside - self.cc - share * self.available
        now = rc.Contract(**state["terms"])
        return {"action": "redline", "clauses": {k: (getattr(self.best, k) if getattr(self.best, k) != getattr(now, k) else None) for k in ag.TERMS},
                "price": round(price, 6), "note": None}


SIGN = {"action": "sign", "clauses": None, "price": None, "note": None}
WALK = {"action": "walk", "clauses": None, "price": None, "note": None}


def fixed_plan(ask: Callable[[random.Random], float], sign_at: Callable[[random.Random], float], first_offer: bool = False):
    """A plan: ask this share whenever it may redline; sign what is on the table once it is worth this share."""
    def move(state: Mapping[str, Any], me: Informed, rng: random.Random) -> dict[str, Any]:
        worth = me.worth(state)
        can = "redline" in ag.allowed(state) and me.available > EPS
        if worth is not None and worth >= -EPS and (first_offer or not can or worth >= sign_at(rng) * me.available - EPS):
            return SIGN
        return me.ask(state, ask(rng)) if can and not (first_offer and worth is not None) else WALK
    return move


PLANS = {
    "takes the first offer": fixed_plan(lambda r: 0.5, lambda r: 0.0, first_offer=True),
    "splits evenly": fixed_plan(lambda r: 0.5, lambda r: 0.5),
    "never comes down": fixed_plan(lambda r: 0.9, lambda r: 0.9),
    "random": fixed_plan(lambda r: r.uniform(0.2, 1.0), lambda r: r.uniform(0.0, 1.0)),
}


def surplus(cw: rc.CWorld, it: ra.IntegratorType, state: Mapping[str, Any], seat: str) -> float:
    return ag.grade(cw, it, state)[f"{seat}_surplus"]


def play(cw: rc.CWorld, it: ra.IntegratorType, seat: str, style: str, plan: str, seed: int = 0) -> dict[str, Any]:
    """The stand-in in ``seat`` on a fixed plan, the script in the other."""
    me, rng, state = Informed(cw, it, seat), random.Random(seed), ag.initial_state(cw)
    while not state["finished"]:
        act = PLANS[plan](state, me, rng) if state["to_move"] == seat else an.negotiator_move(state, cw, it, style)
        state = ag.apply(state, act, cw)
    return state


def best_plan(cw: rc.CWorld, it: ra.IntegratorType, seat: str, style: str) -> tuple[float, list[Any], dict[str, Any]]:
    """The most the stand-in can earn against this script with sign, walk and asks on ``GRID``; ties go to the shorter plan."""
    me = Informed(cw, it, seat)

    def go(state: Mapping[str, Any]) -> tuple[float, list[Any], Mapping[str, Any]]:
        if state["finished"]:
            return surplus(cw, it, state, seat), [], state
        if state["to_move"] != seat:
            return go(ag.apply(state, an.negotiator_move(state, cw, it, style), cw))
        options: list[tuple[Any, dict[str, Any]]] = [("walk", WALK)]
        if "sign" in ag.allowed(state):
            options.append(("sign", SIGN))
        if "redline" in ag.allowed(state) and me.available > EPS:
            options += [(a, me.ask(state, a)) for a in GRID]
        found = None
        for label, act in options:
            value, path, end = go(ag.apply(state, act, cw))
            if found is None or value > found[0] + EPS or (abs(value - found[0]) <= EPS and len(path) + 1 < len(found[1])):
                found = (value, [label, *path], end)
        return found

    value, path, end = go(ag.initial_state(cw))
    return value, path, dict(end)


def one_world(job: tuple[str, Mapping[str, Any], str]) -> dict[str, Any]:
    code, payload, style = job
    cw, it = rc.world_from({k: payload[k] for k in ("world", "integrator_type", "extras")})
    state = ag.initial_state(cw)
    while not state["finished"]:
        state = ag.apply(state, an.negotiator_move(state, cw, it, style), cw)
    g = ag.grade(cw, it, state)
    row: dict[str, Any] = {"world": code, "available": g["available_surplus"], "self_play": {
        k: g[k] for k in ("termination", "joint_value_lost", "client_surplus", "integrator_surplus", "best_agreement_signed", "client_ir_violation",
                          "integrator_ir_violation", "moves", "walked_by")}, "seats": {}}
    for seat in ag.SEATS:
        script_seat = ag.other(seat)
        st = an.Negotiator(cw, script_seat, it if script_seat == "integrator" else None, style).style
        out: dict[str, Any] = {"script": {"opening": st.opening, "final": st.final, "least": st.least, "reciprocity": st.reciprocity}, "plans": {}}
        for plan in PLANS:
            end = play(cw, it, seat, style, plan)
            gg = ag.grade(cw, it, end)
            out["plans"][plan] = {"mine": gg[f"{seat}_surplus"], "script": gg[f"{script_seat}_surplus"], "termination": gg["termination"],
                                  "script_below_outside": gg[f"{script_seat}_ir_violation"], "lost": gg["joint_value_lost"]}
        value, path, end = best_plan(cw, it, seat, style)
        gg = ag.grade(cw, it, end)
        out["best"] = {"mine": value, "script": gg[f"{script_seat}_surplus"], "plan": path, "termination": gg["termination"], "moves": gg["moves"],
                       "lost": gg["joint_value_lost"], "script_below_outside": gg[f"{script_seat}_ir_violation"]}
        row["seats"][seat] = out
    return row


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", default="agreement_dev_v1")
    parser.add_argument("--style", default=an.DRAWN)
    parser.add_argument("--out")
    parser.add_argument("--processes", type=int, default=8)
    args = parser.parse_args(argv)
    _, raw = ap.load(args.pack)
    jobs = [(c["case_id"].rsplit(".", 1)[-1], c["payload"], args.style) for c in sorted(raw.values(), key=lambda c: c["case_id"])]
    with Pool(args.processes) as pool:
        rows = pool.map(one_world, jobs, chunksize=1)
    text = json.dumps({"pack": args.pack, "style": args.style, "grid": GRID, "population": an.POPULATION, "worlds": rows}, indent=1, default=str)
    if args.out:
        open(args.out, "w").write(text)
    print(f"{len(rows)} worlds checked")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["GRID", "Informed", "PLANS", "best_plan", "one_world", "play"]
