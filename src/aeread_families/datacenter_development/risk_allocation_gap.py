"""Why Gemini 3.8 Flash and GLM 5.3 Flash differ on the risk-allocation dev campaign.

A derived analysis in the Tier 1 sense: it reads only the published bundle
``evidence/datacenter_development/datacenter_risk_allocation_dev_campaign_v1``
(``tables/cells.jsonl``, ``trajectories/sanitized.jsonl``,
``receipts/projections.jsonl``) and the committed cases that campaign ran
(``cases/datacenter_risk_allocation_v1/``, checked against the bundle's pack
digests and every receipt's case digest), and regenerates byte-identical output
(``--check``).

**Endpoint.** Minus ``decision_regret``, the campaign's primary leaf, so higher
is better. Decision regret is the sum over an episode's moves of what each move
gave up against the best move on the model's own information, in $ thousands.
The bundle publishes only the sum. Every move is re-graded here with the
family's own code (``risk_allocation.Solver`` over ``risk_allocation_environment.seen_of``),
and every episode is replayed through the plugin: the replayed grade must
reproduce every published grade field of its cell, and the re-graded moves must
sum to the published decision regret.

**Parts.** Each move's regret is split by what the move was:

- a proposal gives up ``package + price``. The package part is what the best way
  of proposing that package (any price, a price request, or in the two-prices arm
  a request naming any alternate) gives up against the best move available; the
  price part is what the model's own price or request gives up against that best
  way. Both are at least zero.
- an accept or a walk is one part.

The first move's proposal parts are ``opening_package`` and ``opening_price``;
every later proposal's are ``later_package`` and ``later_price``; every accept or
walk, in any round, is ``accept_or_walk``. Parts are minus these regrets, so per
cell they sum to minus the published decision regret (the largest residual is
published). There is no luck part: the break-off draw is the only chance event,
and decision regret prices it in expectation, so the draw never enters the score.
The grade's ``allocation_gap`` and ``price_gap`` are not parts either: they are
measured against the true types, not the model's information, and they do not add
up to the score; they appear only as outcome classes.

**Classes** are diagnostic. The move classes say what went wrong at a move that
gave up at least $1k (the published "strict pass" line), with the amount of the
part they explain; the outcome classes read the grade's diagnostics against the
true types, and the luck class counts break-offs. One of the move classes,
``refused_at_the_stated_price``, is an environment defect (DC-D-25): a proposal at
the price the counterpart had just stated, refused because the stated figure was
rounded to the refusing side.

**Unit.** A world is one case per seat. A twin shares its base world's seed,
every public fact and the break-off draws, and differs only in the counterpart's
hidden type, so a world and its twin are one cluster (16 worlds, 12 clusters;
checked). Amounts are means per world over the worlds where both models' episodes
are valid; intervals are a world-cluster percentile bootstrap, reported only with
at least ``MIN_CLUSTERS_FOR_INTERVAL`` clusters.

**Comparisons.** Gemini (left) against GLM (right), one report per seat. The
primary arm is the one with the most valid pairs; the other arm and seat pairs
are reported where at least ``MIN_PAIRS`` worlds are paired. A cell that is not
valid on both sides is typed missingness, never a zero: ``published_reasons``
counts the cells left out, by cause.

    python -m aeread_families.datacenter_development.risk_allocation_gap --write
    python -m aeread_families.datacenter_development.risk_allocation_gap --check
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import random
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256

from . import risk_allocation as ra
from . import risk_allocation_environment as env
from . import risk_allocation_pack as rp

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence" / "datacenter_development"
SOURCE = "datacenter_risk_allocation_dev_campaign_v1"
OUT = EVIDENCE / "datacenter_risk_allocation_gap"
ROUTES = (("left", "gemini38_flash"), ("right", "glm53_flash"))
ARMS = ("one_price_low", "one_price_default", "two_prices_low")
MIN_PAIRS = 10
MIN_CLUSTERS_FOR_INTERVAL = 10
FLOOR = 1.0  # $k: a move that gives up less is not a failure (the published "zero regret" line)
STATED_PRECISION = 0.05  # $k: the counterpart's answer states its price to one decimal
BOOTSTRAP_SEED = 20260927
BOOTSTRAP_DRAWS = 10000
TOLERANCE = 1e-6

COMPONENTS: tuple[tuple[str, str, str, str], ...] = (
    ("opening_package", "opening package", "decision",
     "First move, a proposal: what proposing that package in its best way (best price, or asking) gives up against the best first move."),
    ("opening_price", "opening price or request", "decision",
     "First move, a proposal: what the model's price, or its price request, gives up against the best way of proposing the same package."),
    ("later_package", "later package", "decision",
     "Every proposal after the first answer: what proposing that package in its best way gives up against the best move then."),
    ("later_price", "later price or request", "decision",
     "Every proposal after the first answer: what the model's price, or its request, gives up against the best way of proposing that package."),
    ("accept_or_walk", "accepting or walking", "decision",
     "Every accept of a standing offer and every walk away, in any round: what it gives up against the best move then."),
)
KEYS = tuple(key for key, *_ in COMPONENTS)

CLASSES: dict[str, dict[str, str]] = {
    "proposed_when_walking_or_accepting_was_best": {
        "group": "decision", "label": "proposed while walking away (or accepting the standing offer) was the best move",
        "amount": "the move's package part, $k"},
    "opened_with_another_package": {
        "group": "decision", "label": "the first proposal named a package the best first move did not",
        "amount": "the move's package part, $k"},
    "kept_its_first_package": {
        "group": "decision", "label": "after an answer, proposed its first package again when another package was the best move",
        "amount": "the move's package part, $k"},
    "switched_to_the_wrong_package": {
        "group": "decision", "label": "after an answer, changed package, but not to the one the best move names",
        "amount": "the move's package part, $k"},
    "asked_when_it_should_have_offered": {
        "group": "decision", "label": "asked the price (or offered one no consistent counterpart signs) when offering the signing price was worth more",
        "amount": "the move's price part, $k"},
    "asked_the_less_useful_question": {
        "group": "decision", "label": "asked a price in a less useful way (one package where naming an alternate too was worth more, or the other way round)",
        "amount": "the move's price part, $k"},
    "offered_when_it_should_have_asked": {
        "group": "decision", "label": "offered a price some consistent counterpart signs when asking first was worth more",
        "amount": "the move's price part, $k"},
    "offered_a_worse_signing_price": {
        "group": "decision", "label": "offered a signing price, but not the best one for that package (paid or conceded too much, or priced out a type it should have signed)",
        "amount": "the move's price part, $k"},
    "refused_at_the_stated_price": {
        "group": "format", "label": "proposed at the price the counterpart had stated, which was rounded to the side it refuses (DC-D-25)",
        "amount": "the move's price part, $k"},
    "took_a_counter_when_proposing_was_better": {
        "group": "decision", "label": "accepted the standing counter when proposing again was the best move",
        "amount": "the move's regret, $k"},
    "accepted_when_walking_was_better": {
        "group": "decision", "label": "accepted a standing offer worse than walking away",
        "amount": "the move's regret, $k"},
    "walked_when_a_deal_was_better": {
        "group": "decision", "label": "walked away when accepting or proposing was the best move",
        "amount": "the move's regret, $k"},
    "signed_an_inefficient_contract": {
        "group": "outcome", "label": "signed a contract with less joint value than the efficient one for the true types (published allocation gap)",
        "amount": "the published allocation_gap, $k of joint value"},
    "price_left_to_the_counterpart": {
        "group": "outcome", "label": "signed at a price the counterpart would have bettered (published price gap: above the integrator's floor, or below the client's final bid)",
        "amount": "the published price_gap, $k"},
    "broke_off_after_a_refusal": {
        "group": "luck", "label": "the counterpart broke off after a refused proposal (the break-off draw; its risk is already in the move's regret)",
        "amount": "the published allocation_gap of the episode, $k of joint value lost against the best outcome for the true types"},
}
MOVE_CLASSES = tuple(k for k, v in CLASSES.items() if v["group"] in ("decision", "format"))


# ---------------------------------------------------------------------------
# Reading the published bundle and the committed cases.


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _bundle() -> Path:
    return EVIDENCE / SOURCE


def load() -> dict[str, Any]:
    """The bundle's cells, its trajectory steps by receipt, and the cases it ran, each checked against the bundle."""
    bundle = _bundle()
    manifest = json.loads((bundle / "publication_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((bundle / "reports" / "summary.json").read_text(encoding="utf-8"))
    cells = _jsonl(bundle / "tables" / "cells.jsonl")
    projections = {p["campaign_cell_key"]: p for p in _jsonl(bundle / "receipts" / "projections.jsonl")}
    steps: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in _jsonl(bundle / "trajectories" / "sanitized.jsonl"):
        steps[row["source_receipt_sha256"]].append(row)
    for rows in steps.values():
        rows.sort(key=lambda r: r["step_index"])
        if [r["step_index"] for r in rows] != list(range(len(rows))):
            raise ValueError(f"{rows[0]['source_receipt_sha256']}: the trajectory's steps are not 0..n-1")
    cases: dict[str, dict[str, Any]] = {}
    packs = {arm["pack"] for arm in summary["arms"].values()}
    for pack in sorted(packs):
        pack_manifest, pack_cases = rp.load(pack)
        declared = manifest["source_bindings"]["pack_manifest_sha256"][pack]
        if hashlib.sha256(canonical_json_bytes(pack_manifest)).hexdigest() != declared:
            raise ValueError(f"the committed pack {pack} is not the one the campaign bound")
        cases.update(pack_cases)
    for row in cells:
        case = cases[row["case_id"]]
        if case_content_sha256(case) != case["content_sha256"] or projections[row["cell_key"]]["case_sha256"] != case["content_sha256"]:
            raise ValueError(f"{row['cell_key']}: the committed case is not the one the receipt sealed")
        projection = projections[row["cell_key"]]
        if projection["source_receipt_sha256"] != row["receipt_sha256"]:
            raise ValueError(f"{row['cell_key']}: the cell row and its receipt projection disagree")
        scored = {s["leaf"]["leaf_id"]: s["primary"]["value"] for s in projection["scores"] if s.get("status") == "ok"}
        if row.get("valid") is True and scored.get("decision_regret") != row["decision_regret"]:
            raise ValueError(f"{row['cell_key']}: the receipt's decision_regret leaf is not the cell table's")
    models = {}
    route_of = {row["receipt_sha256"]: row["route_id"] for row in cells}
    for receipt, rows in steps.items():
        for row in rows:
            for attempt in row.get("attempts") or []:
                for call in attempt.get("provider_calls") or []:
                    models.setdefault(route_of[receipt], set()).add(call["requested_model"])
    if any(len(v) != 1 for v in models.values()):
        raise ValueError(f"a route requested more than one model: {models}")
    return {"cells": cells, "steps": steps, "cases": cases, "summary": summary, "manifest": manifest,
            "models": {route: next(iter(v)) for route, v in models.items()}}


def _round_indices(steps: Sequence[Mapping[str, Any]]) -> dict[int, int]:
    """Per step, how many times the episode's first phase had started, from 0 (the examiner counts rounds this way)."""
    out, count, last, first = {}, -1, None, steps[0]["phase_id"] if steps else None
    for row in steps:
        if row["phase_instance_id"] != last:
            last = row["phase_instance_id"]
            if row["phase_id"] == first:
                count += 1
        out[int(row["step_index"])] = count
    return out


def replay(payload: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The episode's terminal state, re-driven through the plugin from its published moves; None for an exclusion."""
    plugin = env.RiskAllocationPlugin()
    state = plugin.initial_state(payload, None)
    for row in steps:
        outcome = row.get("outcome") or {}
        if outcome.get("valid") is True:
            envelope = SimpleNamespace(valid=True, action=row["action"])
        elif outcome.get("valid") is False:
            parse = row.get("parse") or {}
            envelope = SimpleNamespace(valid=False, parse=SimpleNamespace(ok=bool(parse.get("ok")), error_code=parse.get("error_code")),
                                       legality=SimpleNamespace(reason=(row.get("legality") or {}).get("reason")))
        else:
            return None  # a provider fault ended the cell before a move: no terminal state
        state = plugin.step(payload, state, None, {payload["seat"]: envelope}).state
    return state if state["finished"] else None


# ---------------------------------------------------------------------------
# Re-grading each move.


def _money(x: float, digits: int = 3) -> str:
    return f"{x:,.{digits}f}".rstrip("0").rstrip(".")


def _pkg(p: ra.Package) -> str:
    return p.label()


def describe(action: ra.Action, standing: tuple[ra.Package, float] | None = None, also: Sequence[tuple[ra.Package, float]] = (),
             past: bool = False) -> str:
    """One plain clause for an action, with exact prices: "propose ..." or, with ``past``, "proposed ..."."""
    verb = (lambda present, done: done if past else present)
    if action.kind == "walk":
        return verb("walk away", "walked away")
    if action.kind == "accept":
        offers = ([standing] if standing else []) + list(also)
        chosen = next((o for o in offers if action.package is None or o[0] == action.package), None)
        return verb("accept", "accepted") + " the standing offer" + (f", {_pkg(chosen[0])} at {_money(chosen[1])}" if chosen else "")
    if action.price == ra.PRICE_IT:
        return (verb("ask", "asked") + f" the price of {_pkg(action.package)}"
                + (f" and of {_pkg(action.alternate)}" if action.alternate is not None else ""))
    return verb("propose", "proposed") + f" {_pkg(action.package)} at {_money(action.price)}"


def move_label(action: ra.Action) -> str:
    """The move as the trajectory records it, with its exact price: what a contribution row names."""
    if action.kind != "propose":
        return action.kind + (f" {_pkg(action.package)}" if action.package is not None else "")
    if action.price == ra.PRICE_IT:
        return f"propose {_pkg(action.package)}, price requested" + (f", alternate {_pkg(action.alternate)}" if action.alternate is not None else "")
    return f"propose {_pkg(action.package)} at {_money(action.price, 6)}"


def _when(seen: ra.Seen) -> str:
    return "After the last answer" if seen.final else f"Round {seen.round}"


def grade_moves(payload: Mapping[str, Any], actions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every move's regret, split into its part(s), with the move classes it falls in.

    ``actions`` are the moves the environment accepted, in order, as the trajectory publishes them."""
    game, other = env.game_of(payload)
    solver = ra.Solver(game)
    decisions = [{"action": dict(a)} for a in actions]
    moves: list[dict[str, Any]] = []
    first_package: ra.Package | None = None
    for i, d in enumerate(decisions):
        seen = env.seen_of(payload, {"decisions": decisions}, upto=i)
        raw = env._action(d["action"])  # as the trajectory records it; the reference keys a lone accept without its package
        action = ra.normalise(seen, raw)
        types = ra.consistent_types(solver, seen)
        q = solver.q_values(seen.round, types, seen.standing, seen.final, seen.also)
        if action not in q:  # an off-grid price: valued the way decision_regret values it
            if action.kind != "propose" or seen.final or (action.alternate is not None and not game.alternates):
                raise ValueError(f"{action.label()} is not available here")
            q[action] = solver.proposal_value(seen.round, types, action.package, action.price, action.alternate)
        low = min(q.values())
        best = ra._best_of(q)
        regret = round(q[action] - low, 6)
        move: dict[str, Any] = {"index": i, "round": seen.round, "final": seen.final, "action": action, "raw": raw, "best": best,
                                "regret": regret, "classes": [], "when": _when(seen)}
        said = describe(raw, seen.standing, seen.also, past=True)
        best_said = describe(best, seen.standing, seen.also)
        if action.kind == "propose":
            same = {b: v for b, v in q.items() if b.kind == "propose" and b.package == action.package}
            if game.alternates:  # a request naming any alternate is also a way of proposing this package
                for alt in ra.PACKAGES:
                    b = ra.Action("propose", action.package, ra.PRICE_IT, alt)
                    if alt != action.package and b not in same:
                        same[b] = solver.proposal_value(seen.round, types, action.package, ra.PRICE_IT, alt)
            best_same = min(same, key=lambda b: (ra._key(same[b]), b.price != ra.PRICE_IT, b.alternate is not None))
            package = min(max(round(same[best_same] - low, 6), 0.0), regret)
            price = regret - package
            opening = i == 0
            if first_package is None:
                first_package = action.package
            signers = [] if action.price == ra.PRICE_IT else [t for t in types if game.signs(action.price, game.threshold(action.package, t, seen.round))]
            true_threshold = game.threshold(action.package, other, seen.round)
            near_miss = (action.price != ra.PRICE_IT and not game.signs(action.price, true_threshold)
                         and abs(action.price - true_threshold) <= STATED_PRECISION)
            move.update(kind="propose", best_same=best_same, parts={("opening_" if opening else "later_") + "package": package,
                                                                   ("opening_" if opening else "later_") + "price": price})
            move["notes"] = {
                ("opening_" if opening else "later_") + "package": (
                    f"{move['when']}: {said}. " + (f"The best move on its information was to {best_said}; this package, proposed in its best way, gives up ${package:,.1f}k against it."
                                                   if package > 0 else "This package, proposed in its best way, was the best move.")),
                ("opening_" if opening else "later_") + "price": (
                    f"{move['when']}: {said}. " + (f"The best way to propose this package was to {describe(best_same)}, so the price gave up ${price:,.1f}k."
                                                   if price > 0 else "No better way to propose this package.")),
            }
            if package >= FLOOR:
                if best.kind != "propose":
                    cls = "proposed_when_walking_or_accepting_was_best"
                elif opening:
                    cls = "opened_with_another_package"
                elif action.package == first_package:
                    cls = "kept_its_first_package"
                else:
                    cls = "switched_to_the_wrong_package"
                move["classes"].append((cls, package, f"{move['when']}: {said}; the best move was to {best_said}, so the package gave up ${package:,.1f}k."))
            if price >= FLOOR:
                if near_miss:
                    cls = "refused_at_the_stated_price"
                    note = (f"{move['when']}: {said}, {abs(action.price - true_threshold) * 1000:,.2f} dollars past the counterpart's limit of "
                            f"{_money(true_threshold, 6)} but within the rounding of the price it had stated; refused, the price part gave up ${price:,.1f}k (DC-D-25).")
                else:
                    asked = not signers
                    best_asks = best_same.price == ra.PRICE_IT
                    cls = {(True, False): "asked_when_it_should_have_offered", (True, True): "asked_the_less_useful_question",
                           (False, True): "offered_when_it_should_have_asked", (False, False): "offered_a_worse_signing_price"}[(asked, best_asks)]
                    note = f"{move['when']}: {said}; the best way to propose this package was to {describe(best_same)}, so the price gave up ${price:,.1f}k."
                move["classes"].append((cls, price, note))
        else:
            move.update(kind=action.kind, parts={"accept_or_walk": regret})
            move["notes"] = {"accept_or_walk": f"{move['when']}: {said}. " + (f"The best move was to {best_said}, so it gave up ${regret:,.1f}k."
                                                                              if regret > 0 else "That was the best move.")}
            if regret >= FLOOR:
                if action.kind == "walk":
                    cls = "walked_when_a_deal_was_better"
                elif best.kind == "propose":
                    cls = "took_a_counter_when_proposing_was_better"
                elif best.kind == "walk":
                    cls = "accepted_when_walking_was_better"
                else:
                    raise ValueError(f"an accept that gave up {regret} against another accept is not classified")
                move["classes"].append((cls, regret, f"{move['when']}: {said}; the best move was to {best_said}, so it gave up ${regret:,.1f}k."))
        moves.append(move)
    return moves


# ---------------------------------------------------------------------------
# One cell: parts, the rows behind them, and the classes.


GRADE_FIELDS = ("valid", "termination", "invalid", "decision_regret", "allocation_gap", "price_gap", "signed_package",
                "efficient_package", "first_proposed_package", "switched_package", "refused_rounds")


def replay_check(data: Mapping[str, Any]) -> dict[str, Any]:
    """Every cell whose episode ended on a move (valid, or an invalid move), replayed through the plugin and graded,
    against every published grade field; a cell a provider fault ended has no terminal state to replay."""
    replayed, mismatches = 0, []
    for row in data["cells"]:
        payload = data["cases"][row["case_id"]]["payload"]
        state = replay(payload, data["steps"].get(row["receipt_sha256"], []))
        if state is None:
            if row.get("valid") is not None:
                raise ValueError(f"{row['cell_key']}: a graded cell whose trajectory does not reach a terminal state")
            continue
        replayed += 1
        graded = env.grade(payload, state)
        if any(graded[k] != row[k] for k in GRADE_FIELDS) or (graded["decisions"] or [{}])[0].get("regret") != row["first_move_regret"]:
            mismatches.append(row["cell_key"])
    if mismatches:
        raise ValueError(f"replayed grades differ from the published ones: {mismatches}")
    return {"cells": replayed, "mismatches": 0,
            "statement": "every cell whose episode ended on a move was replayed through the plugin from its published trajectory and "
                         "graded; every published grade field and the first move's regret were reproduced. Cells a provider fault "
                         "ended have no terminal state and no grade."}


def analyse_cell(payload: Mapping[str, Any], steps: Sequence[Mapping[str, Any]], published: Mapping[str, Any]) -> dict[str, Any]:
    """The cell's parts (minus regret), one contribution row per move per part, and its class instances.

    Refuses a cell whose replay or re-grading does not reproduce what the bundle published."""
    state = replay(payload, steps)
    if state is None:
        raise ValueError(f"{published['cell_key']}: not a finished episode")
    graded = env.grade(payload, state)
    for key in GRADE_FIELDS:
        if graded[key] != published[key]:
            raise ValueError(f"{published['cell_key']}: replayed {key} {graded[key]!r} is not the published {published[key]!r}")
    accepted = [row for row in steps if (row.get("outcome") or {}).get("valid") is True]
    moves = grade_moves(payload, [row["action"] for row in accepted])
    if [m["regret"] for m in moves] != [d["regret"] for d in graded["decisions"]]:
        raise ValueError(f"{published['cell_key']}: re-graded moves differ from the plugin's grade")
    if moves and moves[0]["regret"] != published["first_move_regret"]:
        raise ValueError(f"{published['cell_key']}: re-graded first move differs from the published first_move_regret")
    rounds = _round_indices(steps)
    rows: list[dict[str, Any]] = []
    instances: list[dict[str, Any]] = []
    for move, step in zip(moves, accepted):
        at = {"step_index": int(step["step_index"]), "round_index": rounds[int(step["step_index"])],
              "phase_id": step["phase_id"], "seat_id": step["seat_id"]}
        for key in KEYS:
            if key in move["parts"]:
                amount = -move["parts"][key]
                rows.append({**at, "component": key, "amount": amount, "move": move_label(move["raw"]), "note": move["notes"][key]})
        for cls, amount, note in move["classes"]:
            instances.append({**at, "class": cls, "amount": amount, "note": note})
    parts = {key: math.fsum(r["amount"] for r in rows if r["component"] == key) for key in KEYS}
    endpoint = -float(published["decision_regret"])
    last = {"step_index": int(accepted[-1]["step_index"]), "round_index": rounds[int(accepted[-1]["step_index"])],
            "phase_id": accepted[-1]["phase_id"], "seat_id": accepted[-1]["seat_id"]}
    seat = payload["seat"]
    if published["signed_package"] is not None:
        if published["allocation_gap"] >= FLOOR:
            instances.append({**last, "class": "signed_an_inefficient_contract", "amount": float(published["allocation_gap"]),
                              "note": f"Signed {published['signed_package']}; the efficient contract for the true types was "
                                      f"{published['efficient_package']}, so joint value fell ${published['allocation_gap']:,.1f}k short."})
        if published["price_gap"] >= FLOOR:
            where = "above the integrator's floor" if seat == "client" else "below the client's final bid"
            instances.append({**last, "class": "price_left_to_the_counterpart", "amount": float(published["price_gap"]),
                              "note": f"Signed {published['signed_package']} ${published['price_gap']:,.1f}k {where} for that package."})
    if published["termination"] == "broke_off":
        instances.append({**last, "class": "broke_off_after_a_refusal", "amount": float(published["allocation_gap"]),
                          "note": f"The counterpart broke off after the refused proposal ({moves[-1]['when'].lower()}); with no deal, joint value "
                                  f"fell ${published['allocation_gap']:,.1f}k short of the best outcome for the true types."})
    return {"parts": parts, "endpoint": endpoint, "residual": math.fsum(parts.values()) - endpoint, "rows": rows,
            "instances": instances, "moves": len(moves)}


# ---------------------------------------------------------------------------
# Comparisons.


def _cluster(row: Mapping[str, Any], cases: Mapping[str, Any]) -> int:
    return int(cases[row["case_id"]]["world_seed"])


def check_clusters(data: Mapping[str, Any]) -> dict[str, Any]:
    """A twin shares its base world's seed, public facts and draws; distinct seeds are distinct worlds."""
    worlds: dict[tuple[str, str, str], tuple[Any, ...]] = {}
    roots: dict[str, str] = {}
    for row in data["cells"]:
        case = data["cases"][row["case_id"]]
        payload = case["payload"]
        facts = (case["world_seed"], canonical_json_bytes(payload["world"]), tuple(payload["breakoff_draws"]), row["seat"], row["arm"])
        worlds.setdefault((row["world"], row["seat"], row["arm"]), facts)
        roots[row["world"]] = row.get("twin_of") or row["world"]
    base: dict[int, set[str]] = {}
    for (world, seat, arm), facts in worlds.items():
        root = roots[world]
        if root != world:
            ref = worlds[(root, seat, arm)]
            if ref != facts:
                raise ValueError(f"{world} does not share its base world's seed, public facts and draws")
        base.setdefault(facts[0], set()).add(root)
    if any(len(v) != 1 for v in base.values()):
        raise ValueError("two base worlds share a seed")
    publics = {canonical_json_bytes(data["cases"][r["case_id"]]["payload"]["world"]) for r in data["cells"]}
    seeds = {_cluster(r, data["cases"]) for r in data["cells"]}
    if len(publics) != len(seeds):
        raise ValueError("world seeds do not map one to one onto distinct public worlds")
    names = {r["world"] for r in data["cells"]}
    return {"worlds": len(names), "clusters": len(seeds)}


def _pairs(data: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    by: dict[tuple[str, str], dict[str, dict[str, dict[str, Any]]]] = collections.defaultdict(lambda: collections.defaultdict(dict))
    for row in data["cells"]:
        by[(row["arm"], row["seat"])][row["world"]][row["route_id"]] = row
    out = {}
    for key, worlds in sorted(by.items()):
        paired = sorted(w for w, d in worlds.items() if all((d.get(route) or {}).get("valid") is True for _, route in ROUTES))
        out[key] = {"worlds": worlds, "paired": paired,
                    "clusters": len({_cluster(worlds[w][ROUTES[0][1]], data["cases"]) for w in paired}),
                    "valid": {side: sum(1 for d in worlds.values() if (d.get(route) or {}).get("valid") is True) for side, route in ROUTES},
                    "cells": {side: sum(1 for d in worlds.values() if route in d) for side, route in ROUTES}}
    return out


def primary_arm(pairs: Mapping[tuple[str, str], Mapping[str, Any]]) -> str:
    total = collections.Counter()
    for (arm, _seat), p in pairs.items():
        total[arm] += len(p["paired"])
    return min(total, key=lambda arm: (-total[arm], arm))


def _failure_cause(steps: Sequence[Mapping[str, Any]]) -> str:
    for row in steps:
        outcome = row.get("outcome") or {}
        if outcome.get("valid") is not True:
            return str(outcome.get("failure_code") or (row.get("parse") or {}).get("error_code") or "unknown")
    return "unfinished"


def _boot(by_cluster: Mapping[int, Sequence[float]], rng: random.Random) -> list[float]:
    keys = sorted(by_cluster)
    means = []
    for _ in range(BOOTSTRAP_DRAWS):
        flat = [x for _ in keys for x in by_cluster[keys[rng.randrange(len(keys))]]]
        means.append(math.fsum(flat) / len(flat))
    means.sort()
    return [round(means[int(0.025 * BOOTSTRAP_DRAWS)], 6), round(means[min(BOOTSTRAP_DRAWS - 1, int(0.975 * BOOTSTRAP_DRAWS))], 6)]


def _r(x: float) -> float:
    return round(x, 6) + 0.0  # no negative zero in the published bytes


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


def comparison(data: Mapping[str, Any], arm: str, seat: str, pair: Mapping[str, Any], panel: list[dict[str, Any]],
               primary: str, worlds: Mapping[str, int], replayed: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """One report, left (Gemini) against right (GLM) on the worlds both played validly, and its contribution rows."""
    cells: dict[str, list[dict[str, Any]]] = {"left": [], "right": []}
    table: list[dict[str, Any]] = []
    instances: list[dict[str, Any]] = []
    residuals, contribution_residuals, moves = [], [], {"left": 0, "right": 0}
    for world in pair["paired"]:
        for side, route in ROUTES:
            row = pair["worlds"][world][route]
            case = data["cases"][row["case_id"]]
            result = analyse_cell(case["payload"], data["steps"][row["receipt_sha256"]], row)
            where = {"side": side, "campaign_id": SOURCE, "receipt_sha256": row["receipt_sha256"], "world_seed": int(case["world_seed"]),
                     "replicate_index": int(row.get("replicate_index") or 0), "unit": world}
            residuals.append(result["residual"])
            moves[side] += result["moves"]
            sums = collections.Counter()
            for item in result["rows"]:
                sums[item["component"]] += item["amount"]
                table.append({**where, **{k: item[k] for k in ("step_index", "round_index", "phase_id", "seat_id", "component", "move", "note")},
                              "amount": _r(item["amount"])})
            contribution_residuals.extend(result["parts"][k] - sums[k] for k in KEYS)
            instances.extend({**where, **{k: v for k, v in item.items() if k != "amount"}, "amount": _r(item["amount"])} for item in result["instances"])
            amounts = collections.Counter()
            counts = collections.Counter()
            for item in result["instances"]:
                amounts[item["class"]] += item["amount"]
                counts[item["class"]] += 1
            cells[side].append({**where, "stratum": row["world_cell"], "parts": result["parts"], "endpoint": result["endpoint"],
                                "class_amounts": amounts, "class_counts": counts, "cluster": int(case["world_seed"])})
    clusters = sorted({c["cluster"] for c in cells["left"]})
    interval = len(clusters) >= MIN_CLUSTERS_FOR_INTERVAL
    rng = random.Random(BOOTSTRAP_SEED)

    def block(pick: Callable[[Mapping[str, Any]], float]) -> dict[str, Any]:
        left = [pick(c) for c in cells["left"]]
        right = [pick(c) for c in cells["right"]]
        diffs: dict[int, list[float]] = collections.defaultdict(list)
        for c, a, b in zip(cells["left"], left, right):
            diffs[c["cluster"]].append(a - b)
        return {"left": _r(_mean(left)), "right": _r(_mean(right)), "difference": _r(_mean([a - b for a, b in zip(left, right)])),
                "difference_ci": _boot(diffs, rng) if interval else None}

    for a, b in zip(cells["left"], cells["right"]):
        if a["unit"] != b["unit"]:
            raise ValueError("left and right cells are not paired by world")
    realized = block(lambda c: c["endpoint"])
    components = [{"key": k, "label": lab, "group": grp, "description": desc, **block(lambda c, k=k: c["parts"][k])} for k, lab, grp, desc in COMPONENTS]
    classes = []
    for key, meta in CLASSES.items():
        amounts = block(lambda c, key=key: c["class_amounts"][key])
        classes.append({"key": key, "group": meta["group"], "label": meta["label"], "amount_basis": meta["amount"],
                        "left_count": sum(c["class_counts"][key] for c in cells["left"]),
                        "right_count": sum(c["class_counts"][key] for c in cells["right"]),
                        "left_amount_per_market": amounts["left"], "right_amount_per_market": amounts["right"],
                        "amount_difference": amounts["difference"], "amount_difference_ci": amounts["difference_ci"]})
    if max(abs(r) for r in residuals) > 1e-5:
        raise ValueError(f"{arm}/{seat}: a cell's parts do not sum to its published decision regret")
    if max(abs(r) for r in contribution_residuals) > 1e-9:
        raise ValueError(f"{arm}/{seat}: a cell's contribution rows do not sum to its parts")
    reasons: dict[str, collections.Counter] = {"left": collections.Counter(), "right": collections.Counter()}
    for world, routes in pair["worlds"].items():
        for side, route in ROUTES:
            row = routes.get(route)
            if row is None:
                reasons[side]["no_cell"] += 1
            elif row.get("valid") is not True:
                reasons[side][_failure_cause(data["steps"].get(row["receipt_sha256"], []))] += 1
            elif world not in pair["paired"]:
                reasons[side]["valid_but_unpaired"] += 1
    reason_keys = sorted({k for side in reasons.values() for k in side}, key=lambda k: (k == "valid_but_unpaired", k))
    pack = data["summary"]["arms"][arm]["pack"]
    suffix = f"{arm}_{seat}"
    report = {
        "schema_version": "aeread.gap_decomposition/0.1",
        "family": "datacenter_development", "world_kind": f"risk_allocation_{seat}_seat",
        "title": "Why they differ",
        "comparison": {"arm": arm, "seat": seat, "pack": pack, "primary": arm == primary, **worlds},
        "left": SOURCE, "right": SOURCE,
        "left_model": data["models"][ROUTES[0][1]], "right_model": data["models"][ROUTES[1][1]], "right_label": "glm-5.3-flash",
        "endpoint": "minus decision_regret ($ thousands): minus the published primary leaf, the sum over the episode's moves of what each "
                    "gave up against the best move on the model's own information",
        "unit": "$ thousands per world, the mean over the worlds where both models' episodes are valid; a world is one case of this seat, "
                "and a twin is clustered with its base world",
        "unit_label": "world", "per_label": "world", "amount_label": "$k/world",
        "class_heading": "what went wrong (moves judged on the model's own information; outcomes against the true types)",
        "direction": "higher", "claim_status": "diagnostic_dev_campaign",
        "winner_claim_allowed": False, "inferential_model_ranking_allowed": False,
        "paired_worlds": len(pair["paired"]), "cells": {"left": len(cells["left"]), "right": len(cells["right"])},
        "clusters": len(clusters), "moves": moves,
        "bootstrap": ({"seed": BOOTSTRAP_SEED, "draws": BOOTSTRAP_DRAWS, "interval": "percentile_95",
                       "unit": "world cluster (world_seed: a twin with its base world)",
                       "stream": "one random.Random(seed) per report: realized, then components in declared order, then class amounts in "
                                 "declared order; each draw resamples the clusters with replacement and takes the mean over their worlds"}
                      if interval else None),
        "realized": realized,
        "components": components,
        "accounting_check": {
            "max_abs_residual_per_cell": max(abs(r) for r in residuals),
            "statement": "each cell's parts sum to minus its published decision_regret; the residual is the rounding of the published "
                         "sum to 6 decimals",
            "max_abs_contribution_residual": max(abs(r) for r in contribution_residuals),
            "contribution_statement": "per cell, the contribution rows of each part sum to that cell's part"},
        "classes": classes,
        "instances": sorted(instances, key=lambda i: (i["class"], i["side"], i["unit"], i["step_index"])),
        "cell_parts": [{**{k: c[k] for k in ("side", "campaign_id", "receipt_sha256", "world_seed", "replicate_index", "unit", "stratum")},
                        "parts": {k: _r(v) for k, v in c["parts"].items()}}
                       for c in sorted(cells["left"] + cells["right"], key=lambda c: (c["side"], c["unit"]))],
        "contributions": {"table": f"tables/contributions_{suffix}.jsonl", "rows": len(table),
                          "fields": ["side", "campaign_id", "receipt_sha256", "world_seed", "replicate_index", "unit", "step_index",
                                     "round_index", "phase_id", "seat_id", "component", "amount", "move", "note"]},
        **({"published_reasons": {
            "reasons": reason_keys,
            "left": {k: reasons["left"][k] for k in reason_keys}, "right": {k: reasons["right"][k] for k in reason_keys},
            "statement": "cells of this arm and seat left out of the comparison, by cause: the failure code of the step that ended an "
                         "excluded or invalid cell (read from the published trajectory), or a valid cell whose other side is missing. "
                         "None is scored as zero."}} if reason_keys else {}),
        "panel": panel,
        "replay_check": replayed,
        "source_manifest_sha256": {SOURCE: hashlib.sha256((_bundle() / "publication_manifest.json").read_bytes()).hexdigest()},
    }
    if not interval:
        report["intervals"] = f"none: {len(clusters)} world clusters, fewer than the {MIN_CLUSTERS_FOR_INTERVAL} an interval needs here"
    rank = {k: i for i, k in enumerate(KEYS)}
    table.sort(key=lambda r: (r["side"], r["unit"], r["step_index"], rank[r["component"]]))
    return report, table


def analyse() -> dict[str, tuple[dict[str, Any], list[dict[str, Any]]]]:
    data = load()
    worlds = check_clusters(data)
    replayed = replay_check(data)
    pairs = _pairs(data)
    primary = primary_arm(pairs)
    order = sorted(pairs, key=lambda k: (k[0] != primary, ARMS.index(k[0]), k[1]))
    panel = []
    for arm, seat in order:
        p = pairs[(arm, seat)]
        reported = len(p["paired"]) >= MIN_PAIRS
        panel.append({"arm": arm, "seat": seat, "primary": arm == primary, "paired_worlds": len(p["paired"]), "clusters": p["clusters"],
                      "left_valid": p["valid"]["left"], "right_valid": p["valid"]["right"], "cells_per_side": p["cells"]["left"],
                      "report": f"reports/gap_decomposition_{arm}_{seat}.json" if reported else None,
                      "reason": None if reported else f"{len(p['paired'])} paired worlds, fewer than the {MIN_PAIRS} a report needs"})
    out = {}
    for arm, seat in order:
        if len(pairs[(arm, seat)]["paired"]) >= MIN_PAIRS:
            out[f"{arm}_{seat}"] = comparison(data, arm, seat, pairs[(arm, seat)], panel, primary, worlds, replayed)
    return out


# ---------------------------------------------------------------------------
# Output.


def _table_bytes(rows: Sequence[Mapping[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def _report_bytes(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def _ci(block: Mapping[str, Any]) -> str:
    ci = block.get("difference_ci")
    return f"{block['difference']:.1f} ({ci[0]:.1f} to {ci[1]:.1f})" if ci else f"{block['difference']:.1f}"


def _reasons(report: Mapping[str, Any], side: str) -> str:
    given = report.get("published_reasons")
    if not given:
        return "none"
    return ", ".join(f"{k} {given[side][k]}" for k in given["reasons"] if given[side][k]) or "none"


def _readme(reports: Mapping[str, tuple[dict[str, Any], list]]) -> str:
    first = next(iter(reports.values()))[0]
    L, R = first["left_model"].split("/")[-1], first["right_model"].split("/")[-1]
    panel = first["panel"]
    primary = [r for r, _ in reports.values() if r["comparison"]["primary"]]
    extras = [r for r, _ in reports.values() if not r["comparison"]["primary"]]
    lines = [
        f"# {OUT.name}",
        "",
        f"Why {L} (left) and {R} (right) differ on `{SOURCE}`, seat by seat. Derived from that published bundle and the committed "
        "cases it ran by `python -m aeread_families.datacenter_development.risk_allocation_gap`; `--check` regenerates these bytes. "
        "Diagnostic: one run per cell on a 16-world dev pack, no winner, no ranking.",
        "",
        "The endpoint is minus decision regret ($ thousands; higher is better). The bundle publishes only each episode's sum. Every "
        f"episode that ended on a move ({first['replay_check']['cells']} cells) is replayed through the plugin from its published "
        "trajectory and reproduces every published grade field, and every move is re-graded with the family's own solver, reproducing "
        "the plugin's regret move by move. Each move's regret is split by what the move was: a proposal into the package (proposing that package "
        "in its best way, against the best move) and the price (the model's price or request, against that best way); an accept or a "
        "walk is one part. The first move's parts are the opening ones. Per cell the parts sum to minus the published decision regret "
        f"(largest residual {max(r['accounting_check']['max_abs_residual_per_cell'] for r, _ in reports.values()):.2g}). The published "
        "`allocation_gap` and `price_gap` are not parts: they are judged against the true types, not the model's information, and do "
        "not add up to the score, so they appear as outcome classes. The break-off draw never enters the score, so there is no luck part.",
        "",
        f"The unit is the world. A twin shares its base world's seed, public facts and break-off draws, so the "
        f"{first['comparison']['worlds']} worlds form {first['comparison']['clusters']} clusters (checked); amounts are means over paired worlds, and intervals resample clusters "
        f"({BOOTSTRAP_DRAWS} draws, seed {BOOTSTRAP_SEED}), only where at least {MIN_CLUSTERS_FOR_INTERVAL} clusters are paired. "
        "A world enters a comparison only when both models' episodes are valid; the others are typed missingness, never zeros.",
        "",
        "| arm | seat | paired worlds (clusters) | valid, left / right | report |",
        "|---|---|---|---|---|",
        *(f"| {p['arm']}{' (primary)' if p['primary'] else ''} | {p['seat']} | {p['paired_worlds']} ({p['clusters']}) | "
          f"{p['left_valid']} / {p['right_valid']} of {p['cells_per_side']} | "
          + (f"`{p['report'].split('/')[-1]}`" if p["report"] else f"none: {p['reason']}") + " |" for p in panel),
        "",
    ]
    for r in primary:
        seat = r["comparison"]["seat"]
        lines += [f"## {r['comparison']['arm']}, {seat} seat", "",
                  f"{r['paired_worlds']} paired worlds in {r['clusters']} clusters; {r['moves']['left']} and {r['moves']['right']} moves re-graded. "
                  "Largest parts of the difference: " + ", ".join(f"{c['label']} {c['difference']:+.1f}" for c in sorted(
                      r["components"], key=lambda c: -abs(c["difference"]))[:2]) + ".", "",
                  f"| part | {L} | {R} | {L} minus {R} (95% cluster bootstrap) |", "|---|---|---|---|",
                  f"| **minus decision regret** | **{r['realized']['left']:.1f}** | **{r['realized']['right']:.1f}** | **{_ci(r['realized'])}** |",
                  *(f"| {c['label']} | {c['left']:.1f} | {c['right']:.1f} | {_ci(c)} |" for c in r["components"]),
                  "",
                  f"| class | {L} count | {R} count | {L} $k/world | {R} $k/world |", "|---|---|---|---|---|",
                  *(f"| `{c['key']}` ({c['group']}) | {c['left_count']} | {c['right_count']} | {c['left_amount_per_market']:.1f} | "
                    f"{c['right_amount_per_market']:.1f} |" for c in r["classes"] if c["left_count"] or c["right_count"]),
                  ""]
    if extras:
        head = "| part | " + " | ".join(f"{r['comparison']['arm']}, {r['comparison']['seat']} ({r['paired_worlds']} worlds)" for r in extras) + " |"
        lines += ["## Other arms, extra reports", "",
                  f"{L} minus {R}, $k per paired world (95% cluster bootstrap where there are enough clusters):", "",
                  head, "|---" * (len(extras) + 1) + "|",
                  "| **minus decision regret** | " + " | ".join(f"**{_ci(r['realized'])}**" for r in extras) + " |",
                  *(f"| {label} | " + " | ".join(_ci(next(c for c in r["components"] if c["key"] == key)) for r in extras) + " |"
                    for key, label, *_ in COMPONENTS),
                  ""]
    lines += ["## Left out, by cause", "",
              "| report | " + L + " | " + R + " |", "|---|---|---|",
              *(f"| {r['comparison']['arm']}, {r['comparison']['seat']} | "
                + " | ".join(_reasons(r, side) for side in ("left", "right")) + " |" for r, _ in reports.values()),
              "",
              "Classes are diagnostic, counted over paired cells, and are not parts of the sum. A move class needs the move to give up at "
              f"least ${FLOOR:.0f}k, the published strict-pass line; its amount is the part it explains, so the move classes split the "
              "regret of those moves further. `refused_at_the_stated_price` is an environment defect, not a pricing error: the counterpart "
              "states its price rounded, and a proposal at the stated figure is refused when the rounding went to the refusing side "
              "(DC-D-25 in `docs/operations/incident_log.md`).",
              "",
              "Each report is `reports/gap_decomposition_<arm>_<seat>.json`, with every cell's parts and every class instance at the step "
              "that made it; `tables/contributions_<arm>_<seat>.jsonl` has one row per move per part, with the move and its step, and per "
              "cell a part's rows sum to that cell's part.",
              ""]
    return "\n".join(lines)


def write() -> None:
    reports = analyse()
    (OUT / "reports").mkdir(parents=True, exist_ok=True)
    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    for suffix, (report, table) in reports.items():
        (OUT / "reports" / f"gap_decomposition_{suffix}.json").write_text(_report_bytes(report))
        (OUT / "tables" / f"contributions_{suffix}.jsonl").write_text(_table_bytes(table))
    (OUT / "README.md").write_text(_readme(reports))
    print(f"wrote {OUT.relative_to(ROOT)}: {len(reports)} reports")


def check() -> bool:
    reports = analyse()
    expected = {OUT / "README.md": _readme(reports)}
    for suffix, (report, table) in reports.items():
        expected[OUT / "reports" / f"gap_decomposition_{suffix}.json"] = _report_bytes(report)
        expected[OUT / "tables" / f"contributions_{suffix}.jsonl"] = _table_bytes(table)
    present = {p for p in OUT.rglob("*") if p.is_file()} if OUT.exists() else set()
    ok = present == set(expected) and all(p.read_text(encoding="utf-8") == text for p, text in expected.items())
    print("risk-allocation gap analysis regenerates to the committed bytes" if ok else "risk-allocation gap analysis differs from its generator")
    return ok


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        write()
        return 0
    if args.check:
        return 0 if check() else 1
    for suffix, (report, _) in analyse().items():
        print(suffix, report["realized"], {c["key"]: c["difference"] for c in report["components"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
