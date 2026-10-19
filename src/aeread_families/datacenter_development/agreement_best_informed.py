"""The best informed policy turn by turn, for either seat, against the public scripted counterpart (Gate 3).

    PYTHONPATH=src python -m aeread_families.datacenter_development.agreement_best_informed --out DIR [--processes 8]

The design (``docs/families/datacenter/agreement_case.md``, "What is measured") scores a model's turn by
the best informed policy's value at that turn less the value of the move the model made, given only what
the model's side had seen. This module computes that policy and that loss.

- **What the policy knows**: its own seat's costs exactly, the declared odds of the other side's types, and
  the scripted counterpart's rule and style (``agreement_admitted_pack.public_style``, drawn from the public
  world). It never reads the other side's true type.
- **Beliefs**: the script is deterministic given its type, so the live types at a turn are exactly those
  whose script would have made every script move so far. A client seat's live types are the integrator
  types the draft allows (``cw.types``); an integrator seat's are the client's declared risk charges.
- **Moves**: walk; sign the standing version when allowed; or redline to a candidate clause set at a
  candidate price. The candidate clause sets are, for every non-empty set of live types, the agreement with
  the most expected joint surplus over that set, and the standing terms (price only). The candidate prices
  on a clause set are the seat's break-even moved toward each live type's limit by a share on :data:`GRID`.
  This class contains ``agreement_own_information``'s, so the integrator seat's value can only be higher.
- **Choice**: backward induction over the turns and the live types, maximising expected earnings over the
  live types, ties to the earlier move. Earnings are the seat's surplus over its outside option at both
  sides' true costs, its redline fees deducted, as ``agreement.grade`` reports them ($ thousands).

``loss_by_turn`` replays a sealed negotiation and charges each of the model's turns V(state) − Q(state, move).
The script is driven through :class:`FastNegotiator`, which caches the cost lookups that dominate the original's
running time and leaves every decision rule to the original's code; ``check_script`` compares the two move for move.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from . import agreement as ag
from . import agreement_admitted_pack as aap
from . import agreement_negotiator as an
from . import risk_allocation as ra
from . import risk_allocation_contracts as rc

GRID = (0.2, 0.4, 0.6, 0.8, 1.0)
EPS = 1e-6
SIGN = {"action": "sign", "clauses": None, "price": None, "note": None}
WALK = {"action": "walk", "clauses": None, "price": None, "note": None}


# ---------------------------------------------------------------------------
# The scripted counterpart, with its cost lookups cached.


class FastNegotiator(an.Negotiator):
    """``agreement_negotiator.Negotiator`` with the same rules; only ``surplus`` and ``total`` read from caches.

    The original keys its caches on the whole world, so most of a move goes to hashing it. Here the costs of an
    agreement for one possible type are computed once by the same functions and combined in the same order, so
    every float is the original's."""

    def __init__(self, cw: rc.CWorld, seat: str, own: ra.IntegratorType | None, style: an.Style) -> None:
        super().__init__(cw, seat, own, style)
        self._costs_by: dict[tuple[rc.Contract, Any], tuple[float, float]] = {}
        self._outside_by: dict[float, float] = {}
        self._total_by: dict[tuple[rc.Contract, Any], float] = {}

    def _key(self, o: an.Other) -> Any:
        return o.charge if o.integrator is None else o.integrator

    def surplus(self, c: rc.Contract, price: float, o: an.Other) -> tuple[float, float]:
        k = (c, self._key(o))
        got = self._costs_by.get(k)
        it, charge = self._pair(o)
        if got is None:
            got = self._costs_by[k] = (rc.integrator_cost(c, self.cw.w, it, self.cw.x), rc.client_cost(c, self.cw.w, it, self.cw.x, charge))
        outside = self._outside_by.get(charge)
        if outside is None:
            outside = self._outside_by[charge] = an._outside(self.cw, charge)
        ic, cc = got
        integrator, client = price - ic - self.floor, outside - price - cc
        return (integrator, client) if self.seat == "integrator" else (client, integrator)

    def total(self, c: rc.Contract, o: an.Other) -> float:
        k = (c, self._key(o))
        got = self._total_by.get(k)
        if got is None:
            got = self._total_by[k] = math.fsum(self.surplus(c, 0.0, o))
        return got


# ---------------------------------------------------------------------------
# One world from one seat: the types the seat cannot tell apart, and what each makes of an agreement.


@dataclass(frozen=True)
class Hypothesis:
    """One type the other side may have, as the seat sees it."""
    label: str
    p: float
    cw: rc.CWorld  # the world with this type's client charge (the integrator seat's hypotheses differ only there)
    it: ra.IntegratorType  # the integrator's type in this hypothesis


class Seat:
    """Everything the search needs for one seat of one world."""

    def __init__(self, cw: rc.CWorld, it: ra.IntegratorType, seat: str) -> None:
        if seat not in ag.SEATS:
            raise ValueError(seat)
        self.seat, self.true_cw, self.true_it = seat, cw, it
        script_seat = ag.other(seat)
        self.style = aap.public_style(cw, script_seat)
        if seat == "integrator":
            hyps = [Hypothesis(f"charge={c:g}", p, aap.with_charge(cw, c), it) for c, p in cw.w.client_prior]
            if any(aap.public_style(h.cw, script_seat) != self.style for h in hyps):
                raise AssertionError("the public style must not depend on the hidden charge")
            self.true_label = f"charge={cw.w.client.risk_charge:g}"
        else:
            weight = {t: p for t, p in cw.w.prior}
            total = math.fsum(weight[t] for t in cw.types)
            hyps = [Hypothesis(f"test={t.test_cost:g},charge={t.risk_charge:g}", weight[t] / total, cw, t) for t in cw.types]
            self.true_label = f"test={it.test_cost:g},charge={it.risk_charge:g}"
        self.hyps = {h.label: h for h in hyps}
        if self.true_label not in self.hyps:
            raise AssertionError("the true type must be one the seat's prior allows")
        self.scripts = {h.label: FastNegotiator(h.cw, script_seat, h.it if script_seat == "integrator" else None, self.style) for h in hyps}
        self.floor = cw.w.terms.floor_margin
        self._costs: dict[tuple[str, rc.Contract], tuple[float, float]] = {}
        self._script_moves: dict[tuple[str, str], dict[str, Any]] = {}
        self.visited: dict[tuple[str, str], Mapping[str, Any]] = {}  # every state the script was asked to move in, for check_script

    # ---- money ----
    def costs(self, label: str, c: rc.Contract) -> tuple[float, float]:
        k = (label, c)
        got = self._costs.get(k)
        if got is None:
            h = self.hyps[label]
            got = self._costs[k] = ag.costs(h.cw, h.it, c)
        return got

    def outside(self, label: str) -> float:
        return self.hyps[label].cw.best_outside[1]

    def earnings(self, label: str, state: Mapping[str, Any]) -> float:
        """The seat's surplus at a finished state, as ``agreement.grade`` computes it, for this hypothesis."""
        fee = state["round_costs"][self.seat]
        signed = state["signed"]
        if signed is None:
            return 0.0 - fee
        ic, cc = self.costs(label, rc.Contract(**signed["terms"]))
        deal = signed["price"] - ic - self.floor if self.seat == "integrator" else self.outside(label) - signed["price"] - cc
        return deal - fee

    def joint(self, label: str, c: rc.Contract) -> float:
        ic, cc = self.costs(label, c)
        return self.outside(label) - self.floor - ic - cc

    def limits(self, label: str, c: rc.Contract) -> tuple[float, float]:
        """(the seat's break-even price, the other side's) on this clause set, for this hypothesis."""
        ic, cc = self.costs(label, c)
        mine, theirs = ic + self.floor, self.outside(label) - cc
        return (mine, theirs) if self.seat == "integrator" else (theirs, mine)

    # ---- the script ----
    def script_move(self, label: str, state: Mapping[str, Any]) -> dict[str, Any]:
        k = (label, _key(state))
        got = self._script_moves.get(k)
        if got is None:
            got = self._script_moves[k] = self.scripts[label].move(state)
            self.visited[k] = state
        return got

    def step(self, label: str, state: Mapping[str, Any], act: Mapping[str, Any]) -> dict[str, Any]:
        """The seat's move, then the script's reply if the negotiation goes on."""
        cw = self.hyps[label].cw
        s = ag.apply(state, act, cw)
        if not s["finished"]:
            s = ag.apply(s, self.script_move(label, s), cw)
        return s

    # ---- the seat's moves ----
    def candidates(self, labels: Sequence[str], state: Mapping[str, Any]) -> list[rc.Contract]:
        d = ag.draft(self.true_cw)
        out = {rc.Contract(**state["terms"])}
        for n in range(1, len(labels) + 1):
            for subset in itertools.combinations(labels, n):
                out.add(max(ag.ALL_AGREEMENTS, key=lambda k: (round(math.fsum(self.hyps[x].p * self.joint(x, k) for x in subset), 6), k == d, k)))
        return sorted(out)

    def moves(self, labels: Sequence[str], state: Mapping[str, Any], grid: Sequence[float] = GRID) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [WALK]
        allowed = ag.allowed(state)
        if "sign" in allowed:
            out.append(SIGN)
        if "redline" not in allowed:
            return out
        now = rc.Contract(**state["terms"])
        for k in self.candidates(labels, state):
            prices = set()
            for x in labels:
                mine, theirs = self.limits(x, k)
                room = (theirs - mine) if self.seat == "integrator" else (mine - theirs)
                if room <= EPS:
                    continue
                for share in grid:
                    prices.add(round(mine + share * room, 3) if self.seat == "integrator" else round(mine - share * room, 3))
            for price in sorted(prices):
                out.append({"action": "redline", "clauses": {t: (getattr(k, t) if getattr(k, t) != getattr(now, t) else None) for t in ag.TERMS},
                            "price": price, "note": None})
        return out


def _key(state: Mapping[str, Any]) -> str:
    return json.dumps(state["history"], sort_keys=True, default=str)


def _reply_key(state: Mapping[str, Any]) -> str:
    return json.dumps([state["finished"], state["termination"], state["history"][-1] if state["history"] else None], sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# Backward induction over turns and live types.


class Solver:
    """``moves(labels, state)`` may replace the seat's class of moves, to reproduce another reference's."""

    def __init__(self, seat: Seat, grid: Sequence[float] = GRID, moves: Any = None) -> None:
        self.s, self.grid = seat, tuple(grid)
        self._moves = moves or (lambda labels, state: seat.moves(labels, state, self.grid))
        self._memo: dict[tuple[str, tuple[str, ...]], tuple[dict[str, float], dict[str, Any] | None]] = {}

    def _expected(self, labels: Sequence[str], values: Mapping[str, float]) -> float:
        z = math.fsum(self.s.hyps[x].p for x in labels)
        return math.fsum(self.s.hyps[x].p / z * values[x] for x in labels)

    def after(self, state: Mapping[str, Any], labels: Sequence[str], act: Mapping[str, Any]) -> dict[str, float]:
        """Per live type: what the seat earns if it makes ``act`` now and plays the best informed policy after."""
        nxt = {x: self.s.step(x, state, act) for x in labels}
        groups: dict[str, list[str]] = {}
        for x, st in nxt.items():
            groups.setdefault(_reply_key(st), []).append(x)
        values: dict[str, float] = {}
        for members in groups.values():
            st = nxt[members[0]]
            if st["finished"]:
                values.update({x: self.s.earnings(x, nxt[x]) for x in members})
            else:
                values.update(self.solve(st, members)[0])
        return values

    def solve(self, state: Mapping[str, Any], labels: Sequence[str]) -> tuple[dict[str, float], dict[str, Any] | None]:
        """(per live type, the seat's earnings under the best informed policy from here; its move), at the seat's turn."""
        labels = tuple(sorted(labels))
        if state["finished"]:
            return {x: self.s.earnings(x, state) for x in labels}, None
        if state["to_move"] != self.s.seat:
            raise ValueError("solve is called at the seat's own turn")
        k = (_key(state), labels)
        got = self._memo.get(k)
        if got is not None:
            return got
        best: tuple[float, dict[str, float], dict[str, Any]] | None = None
        for act in self._moves(labels, state):
            values = self.after(state, labels, act)
            v = self._expected(labels, values)
            if best is None or v > best[0] + EPS:
                best = (v, values, act)
        assert best is not None
        self._memo[k] = (best[1], best[2])
        return self._memo[k]

    def value(self, state: Mapping[str, Any], labels: Sequence[str]) -> float:
        return self._expected(labels, self.solve(state, labels)[0])

    def q(self, state: Mapping[str, Any], labels: Sequence[str], act: Mapping[str, Any]) -> float:
        return self._expected(labels, self.after(state, labels, act))


def opening(seat: Seat) -> tuple[dict[str, Mapping[str, Any]], dict[str, list[str]]]:
    """The seat's first turn for each hypothesis: the initial state for an integrator, or after the script's opening
    for a client, with the hypotheses grouped by what the seat has then seen."""
    states, groups = {}, {}
    for x, h in seat.hyps.items():
        st = ag.initial_state(h.cw)
        if seat.seat == "client":
            st = ag.apply(st, seat.script_move(x, st), h.cw)
        states[x] = st
        groups.setdefault(_reply_key(st), []).append(x)
    return states, groups


def plan_values(seat: Seat, grid: Sequence[float] = GRID, moves: Any = None) -> dict[str, Any]:
    """Per hypothesis, the best informed plan's earnings from the start; the prior-weighted expectation; and the same
    search told the true type (what not knowing it costs on this class of moves)."""
    solver = Solver(seat, grid, moves)
    states, groups = opening(seat)
    values: dict[str, float] = {}
    for members in groups.values():
        st = states[members[0]]
        values.update({x: seat.earnings(x, states[x]) for x in members} if st["finished"] else solver.solve(st, members)[0])
    expected = math.fsum(seat.hyps[x].p * values[x] for x in values)
    told = Solver(seat, grid, moves)
    st = states[seat.true_label]
    full = seat.earnings(seat.true_label, st) if st["finished"] else told.solve(st, [seat.true_label])[0][seat.true_label]
    return {"by_type": {x: round(v, 6) for x, v in sorted(values.items())}, "at_true": round(values[seat.true_label], 6),
            "expected": round(expected, 6), "told_the_type": round(full, 6), "true_type": seat.true_label}


# ---------------------------------------------------------------------------
# Replaying the plan against the original script, and checking the cached script against the original.


def replay(seat: Seat, label: str, grid: Sequence[float] = GRID) -> tuple[float, list[dict[str, Any]]]:
    """Play the best informed policy against the *original* script with type ``label``; what the seat earns."""
    h = seat.hyps[label]
    solver = Solver(seat, grid)
    state = ag.initial_state(h.cw)
    live = sorted(seat.hyps)
    trace = []
    while not state["finished"]:
        if state["to_move"] == seat.seat:
            act = solver.solve(state, live)[1]
            trace.append({"move": state["move"], "act": act, "live": list(live)})
        else:
            act = an.Negotiator(h.cw, ag.other(seat.seat), h.it if seat.seat == "client" else None, seat.style).move(state)
            live = [x for x in live if seat.script_move(x, state) == act]
        state = ag.apply(state, act, h.cw)
    return seat.earnings(label, state), trace


def check_script(seat: Seat, every: int = 1) -> int:
    """The cached script's move equals the original's on every ``every``-th state it was asked to move in; the count."""
    n = 0
    origs = {x: an.Negotiator(h.cw, ag.other(seat.seat), h.it if seat.seat == "client" else None, seat.style) for x, h in seat.hyps.items()}
    for i, ((x, _), st) in enumerate(sorted(seat.visited.items(), key=lambda kv: kv[0])):
        if i % every:
            continue
        a, b = seat._script_moves[(x, _key(st))], origs[x].move(st)
        if a != b:
            raise AssertionError(f"cached script differs from the original for {x} at move {st['move']}: {a} vs {b}")
        n += 1
    return n


# ---------------------------------------------------------------------------
# Loss by turn on a sealed negotiation.


def loss_by_turn(seat: Seat, moves: Sequence[Mapping[str, Any]], grid: Sequence[float] = GRID, solver: Solver | None = None) -> dict[str, Any]:
    """Replay a sealed negotiation (every move in order, both seats) in the true world and charge each of the seat's turns.

    A turn's loss is V(state) − Q(state, move): the best informed policy's expected earnings from that turn less the
    expected earnings of the move made followed by the best informed policy, both over the types still live given every
    script move so far. The script's recorded moves must be the ones the script makes with the true type."""
    solver = solver or Solver(seat, grid)
    h = seat.hyps[seat.true_label]
    state = ag.initial_state(h.cw)
    live = sorted(seat.hyps)
    turns = []
    for m in moves:
        if state["finished"]:
            raise AssertionError("a move recorded after the negotiation ended")
        act = {"action": m["action"], "clauses": m.get("clauses"), "price": m.get("price"), "note": None}
        if state["to_move"] == seat.seat:
            v, q = solver.value(state, live), solver.q(state, live, act)
            best = solver.solve(state, live)[1]
            turns.append({"move": state["move"], "live": len(live), "action": act["action"], "price": act["price"],
                          "best_action": best["action"] if best else None, "best_price": best["price"] if best else None,
                          "value": round(v, 6), "q": round(q, 6), "loss": round(v - q, 6)})
        else:
            mine = seat.script_move(seat.true_label, state)
            if (mine["action"], mine["price"], {k: v for k, v in (mine["clauses"] or {}).items() if v is not None}) != \
                    (act["action"], act["price"], {k: v for k, v in (act["clauses"] or {}).items() if v is not None}):
                raise AssertionError(f"the recorded script move at move {state['move']} is not the script's: {act} vs {mine}")
            live = [x for x in live if seat.script_move(x, state) == mine]
            act = mine
        state = ag.apply(state, act, h.cw)
    if not state["finished"]:
        raise AssertionError("the recorded negotiation does not finish")
    return {"turns": turns, "loss": round(math.fsum(t["loss"] for t in turns), 6), "earned": round(seat.earnings(seat.true_label, state), 6),
            "termination": state["termination"]}


# ---------------------------------------------------------------------------
# The one-step check: is the best agreement reached by judging each clause on its own against the draft?


def one_step(seat: Seat, labels: Sequence[str]) -> dict[str, Any]:
    """Over the live types, the agreement that sets every clause to its best position judged alone against the draft,
    against the agreement with the most expected joint surplus. Equal means the case is arithmetic for this seat."""
    d = ag.draft(seat.true_cw)
    z = math.fsum(seat.hyps[x].p for x in labels)
    ev = lambda k: math.fsum(seat.hyps[x].p / z * seat.joint(x, k) for x in labels)
    best = max(ag.ALL_AGREEMENTS, key=lambda k: (round(ev(k), 6), k == d, k))
    picks = {}
    for term in ag.TERMS:
        alone = [rc.contract_from({term: level}, d).normal() for level in rc.LEVELS[term]]
        picks[term] = getattr(max(alone, key=lambda k: (round(ev(k), 6), k == d, k)), term)
    step = rc.Contract(**{t: picks[t] for t in ag.TERMS}).normal()
    return {"best": best.label(), "one_step": step.label(), "draft": d.label(), "best_value": round(ev(best), 6),
            "one_step_value": round(ev(step), 6), "draft_value": round(ev(d), 6), "matches": abs(ev(best) - ev(step)) <= EPS}


# ---------------------------------------------------------------------------
# The analysis: every admitted world, both seats, and the sealed firm-population negotiations.


CONFIRMATORY = "evidence/datacenter_development/datacenter_agreement_confirm_firm_population_v1"


def sealed_negotiations(root: Path) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """(world, model seat) -> each model's negotiation: subject, moves in order, the recorded outcome."""
    rows = [json.loads(line) for line in (root / CONFIRMATORY / "trajectories/sanitized.jsonl").read_text().splitlines() if line.strip()]
    cells = {c["receipt_sha256"]: c for c in (json.loads(line) for line in (root / CONFIRMATORY / "tables/cells.jsonl").read_text().splitlines() if line.strip())}
    by_cell: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_cell.setdefault(r["source_receipt_sha256"], []).append(r)
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for sha, rs in sorted(by_cell.items()):
        c = cells[sha]
        seat = "integrator" if not c["integrator"].startswith("scripted") else "client"
        rs.sort(key=lambda r: r["step_index"])
        out.setdefault((c["world"], seat), []).append({
            "subject": c[seat], "cell_key": c["cell_key"], "receipt_sha256": sha, "recorded_surplus": c[f"{seat}_surplus"],
            "moves": [r["action"] for r in rs]})
    for v in out.values():
        v.sort(key=lambda n: n["subject"])
    return out


def world_job(job: tuple[str, Mapping[str, Any], str, list[dict[str, Any]]]) -> dict[str, Any]:
    world, payload, seat_name, negotiations = job
    cw, it = rc.world_from({k: payload[k] for k in ("world", "integrator_type", "extras")})
    seat = Seat(cw, it, seat_name)
    solver = Solver(seat)
    plan = plan_values(seat)
    replays = {x: round(replay(seat, x)[0], 6) for x in seat.hyps}
    if any(abs(replays[x] - plan["by_type"][x]) > 1e-5 for x in replays):
        raise AssertionError(f"{world} {seat_name}: the plan replayed against the original script earns {replays}, not {plan['by_type']}")
    row: dict[str, Any] = {"world": world, "seat": seat_name, "types": len(seat.hyps), "plan": plan, "replayed_against_original_script": True,
                           "one_step_own_information": one_step(seat, sorted(seat.hyps)),
                           "one_step_full_information": one_step(seat, [seat.true_label]), "negotiations": []}
    for n in negotiations:
        got = loss_by_turn(seat, n["moves"], solver=solver)
        if abs(got["earned"] - n["recorded_surplus"]) > 1e-5:
            raise AssertionError(f"{n['cell_key']}: replay earns {got['earned']}, the record says {n['recorded_surplus']}")
        row["negotiations"].append({"subject": n["subject"], "cell_key": n["cell_key"], "receipt_sha256": n["receipt_sha256"], **got,
                                    "shortfall_at_true": round(plan["at_true"] - got["earned"], 6)})
    row["script_states_checked"] = check_script(seat, every=10)
    return row


def run(root: Path, processes: int = 8) -> dict[str, Any]:
    _, cases, _ = aap.load()
    payloads = {c["case_id"].rsplit(".", 1)[-1]: c["payload"] for c in cases.values()}
    sealed = sealed_negotiations(root)
    jobs = [(w, payloads[w], s, sealed.get((w, s), [])) for w in sorted(payloads) for s in ag.SEATS]
    with Pool(processes) as pool:
        rows = pool.map(world_job, jobs, chunksize=1)
    return {"analysis": "agreement_best_informed_v1", "pack": aap.PACK, "grid": list(GRID), "sealed_campaign": CONFIRMATORY,
            "counterpart": "scripted negotiator, public drawn style (agreement_admitted_pack.public_style)", "rows": rows}


def _mean(xs: Sequence[float]) -> float | None:
    return round(math.fsum(xs) / len(xs), 3) if xs else None


def summary(result: Mapping[str, Any]) -> dict[str, Any]:
    """The tables the write-up reads, from ``rows.json`` alone (deal worlds: the pack's available surplus is positive)."""
    manifest, _, _ = aap.load()
    deal = {w["case_id"].rsplit(".", 1)[-1]: w["available_surplus"] > 0 for w in manifest["worlds"]}
    out: dict[str, Any] = {"analysis": result["analysis"], "pack": result["pack"], "seats": {}}
    for seat in ag.SEATS:
        rows = [r for r in result["rows"] if r["seat"] == seat]
        block: dict[str, Any] = {"worlds": len(rows), "deal_worlds": sum(deal[r["world"]] for r in rows)}
        for scope, keep in (("all", lambda r: True), ("deal", lambda r: deal[r["world"]])):
            rs = [r for r in rows if keep(r)]
            block[f"plan_{scope}"] = {
                "expected": _mean([r["plan"]["expected"] for r in rs]), "at_true": _mean([r["plan"]["at_true"] for r in rs]),
                "told_the_type": _mean([r["plan"]["told_the_type"] for r in rs]),
                "types_live_at_start": {str(n): sum(r["types"] == n for r in rs) for n in sorted({r["types"] for r in rs})}}
        block["one_step"] = {k: {"matches": sum(r[f"one_step_{k}"]["matches"] for r in rows),
                                 "mean_value_short": _mean([r[f"one_step_{k}"]["best_value"] - r[f"one_step_{k}"]["one_step_value"] for r in rows])}
                             for k in ("own_information", "full_information")}
        subjects: dict[str, Any] = {}
        for name in sorted({n["subject"] for r in rows for n in r["negotiations"]}):
            for scope, keep in (("all", lambda r: True), ("deal", lambda r: deal[r["world"]])):
                ns = [(r, n) for r in rows if keep(r) for n in r["negotiations"] if n["subject"] == name]
                turns = [(i, t) for _, n in ns for i, t in enumerate(n["turns"])]
                subjects.setdefault(name, {})[scope] = {
                    "negotiations": len(ns), "earned": _mean([n["earned"] for _, n in ns]),
                    "plan_at_true": _mean([r["plan"]["at_true"] for r, _ in ns]),
                    "shortfall_at_true": _mean([n["shortfall_at_true"] for _, n in ns]),
                    "loss_by_turn_total": _mean([n["loss"] for _, n in ns]),
                    "loss_by_turn_index": {str(i + 1): {"turns": sum(1 for j, _ in turns if j == i), "mean_loss": _mean([t["loss"] for j, t in turns if j == i])}
                                           for i in range(3)},
                    "turns": len(turns), "turns_losing_over_1k": sum(t["loss"] > 1.0 for _, t in turns),
                    "turns_beating_the_policy": sum(t["loss"] < -1e-6 for _, t in turns),
                    "beaten_by": round(-math.fsum(t["loss"] for _, t in turns if t["loss"] < -1e-6), 3),
                    "same_kind_of_move_as_the_policy": sum(t["action"] == t["best_action"] for _, t in turns)}
        block["subjects"] = subjects
        out["seats"][seat] = block
    return out


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--processes", type=int, default=8)
    parser.add_argument("--summary-only", action="store_true", help="recompute summary.json from the rows.json already in --out")
    args = parser.parse_args(argv)
    out = Path(args.out) / "reports"  # an evidence bundle keeps its files in the standard categories
    if args.summary_only:
        result = json.loads((out / "rows.json").read_text())
    else:
        result = run(Path(args.root), args.processes)
        out.mkdir(parents=True, exist_ok=True)
        (out / "rows.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    (out / "summary.json").write_text(json.dumps(summary(result), indent=1, sort_keys=True) + "\n")
    print(f"{len(result['rows'])} world-seats; rows.json and summary.json in {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["CONFIRMATORY", "FastNegotiator", "GRID", "Hypothesis", "Seat", "Solver", "check_script", "loss_by_turn", "one_step", "opening",
           "plan_values", "replay", "run", "sealed_negotiations", "summary", "world_job"]
