"""The tender: three firms bid for one delivery and the client negotiates with any of them in the
same turn. Every bid must reveal its firm's type to a client who knows the policy, no move of any
kind may beat the reference, the environment's state must be the reference's state at every step,
the brief must not state the pricing policy, moves must be read strictly, and the reference must
grade zero through the kernel."""

from __future__ import annotations

import asyncio
import math
import random
from pathlib import Path

import pytest

from aeread.shared_runner.task.scheduler import ActionEnvelope
from aeread_families.datacenter_development import risk_allocation_contracts as rc
from aeread_families.datacenter_development import risk_allocation_tender as rt
from aeread_families.datacenter_development import risk_allocation_tender_campaign as tc
from aeread_families.datacenter_development import risk_allocation_tender_pack as tp
from aeread_families.datacenter_development.risk_allocation_tender_environment import TenderPlugin, parse_tender_move, solver_state


def _payloads() -> list[dict]:
    _, cases = tp.load(tc.PACK)
    return [c["payload"] for c in sorted(cases.values(), key=lambda c: c["case_id"])]


def _random_action(solver: rt.TenderSolver, s: rt.TState, rng: random.Random) -> rt.TAction | None:
    kinds = ["walk"] + (["negotiate"] if s.turn <= solver.rounds and any(solver.open(s, j) for j in range(len(s.bidders))) else [])
    if rng.choice(kinds) == "walk":
        return rt.TAction("walk")
    js = [j for j in range(len(s.bidders)) if solver.open(s, j)]
    rng.shuffle(js)
    moves = []
    for j in js[: rng.randint(1, len(js))]:
        c = rng.choice(solver.menu(j)) if rng.random() < 0.9 else rc.Contract("none", "100", "500", "client", "excluded", "none", False, False)
        ci = solver.index(j, c)
        if ci is None or rng.random() < 0.3:
            price = None
        else:
            price = float(solver.th[j][s.bidders[j].round][ci]) + rng.choice([-300.0, -50.0, -0.05, 0.0, 10.0, 200.0])
        moves.append(rt.Move(j, c, price))
    return rt.TAction("negotiate", moves=tuple(moves))


def test_every_packed_bid_reveals_its_firm_and_the_situations_hold() -> None:
    manifest, cases = tp.load(tc.PACK)
    assert len(manifest["worlds"]) == sum(sum(q.values()) for q in tp.PILOT_QUOTAS.values())
    for w in manifest["worlds"]:
        payload = cases[w["case_id"]]["payload"]
        assert rt.situation(payload) == w["situation"], w["slug"]
        for b in rt.tender_from(payload)[2]:
            s = rt.pricing(payload["world"], payload["extras"], b.playbook)
            assert b.playbook in rt.PLAYBOOKS and rt.identified(s, s.type_index(b.type))


def test_a_coordination_firms_standard_fee_is_the_same_for_every_type() -> None:
    payload = _payloads()[0]
    s = rt.pricing(payload["world"], payload["extras"], "coordination")
    assert len({rt.opening_price(s, k) for k in range(len(s.types))}) == 1  # why coordination firms do not bid here


def test_no_move_of_any_kind_beats_the_reference() -> None:
    rng = random.Random(11)
    checked = 0
    for payload in _payloads()[:8]:
        solver = rt.solver_for(payload)
        for _ in range(120):
            s = solver.start()
            while True:
                v = solver.value(s)
                for j, b in enumerate(s.bidders):  # accepting what a bidder stands at is worth exactly that
                    if b.alive and not math.isinf(b.best):
                        assert b.best >= v - 1e-6
                a = _random_action(solver, s, rng)
                assert solver.q(s, a) >= v - 1e-6, (payload["bidders"], s, a.label())
                checked += 1
                if a.kind != "negotiate":
                    break
                s, _ = rt.step_state(solver, s, a, payload["breakoff_draws"])
    assert checked > 1000


def test_the_environments_state_is_the_references_state_at_every_step() -> None:
    rng = random.Random(5)
    plugin = TenderPlugin()
    for payload in _payloads()[:8]:
        solver = rt.solver_for(payload)
        phase = plugin.phases(payload)[0]
        for trial in range(20):
            state, s = plugin.initial_state(payload, None), solver.start()
            assert solver_state(payload, state) == s
            while not state["finished"] and not state["final"]:
                a = solver.best(s) if trial == 0 else _random_action(solver, s, rng)
                if a.kind != "negotiate":
                    break
                move = tc.reply(solver, state, {"action": "negotiate", "offer": None,
                                                "moves": [{"bidder": m.bidder, "contract": m.contract.as_dict(), "price": m.price} for m in a.moves]}, "")
                parsed = parse_tender_move(move)
                legal = plugin.legal(payload, state, "client", phase, parsed.action)
                assert parsed.ok and legal.legal
                state = plugin.step(payload, state, phase, {"client": ActionEnvelope("client", True, parsed.action, parsed, legal)}).state
                s, _ = rt.step_state(solver, s, rt.action_of(state["decisions"][-1]), payload["breakoff_draws"])
                assert solver_state(payload, state) == s


def test_the_brief_states_every_term_and_bid_but_not_the_pricing_policy() -> None:
    for payload in _payloads()[:6]:
        text = rt.brief(payload)
        for hidden in ("premium", "markup", "floor", "margin", "step"):
            assert hidden not in text.lower()
        assert all(f"- {k}:" in text for k in rc.TERMS) and all(f"(offer {b}-O1)" in text for b in rt.BIDDER_IDS)
        assert "rival turnkey" not in text  # the walk-away is managing it yourself; turnkey firms are bidders


def test_moves_are_read_strictly() -> None:
    blank = {k: None for k in rc.TERMS}
    ok = lambda m: parse_tender_move({"offer": None, "moves": None, "reason": "", **m}).ok  # noqa: E731
    move = lambda **kw: {"bidder": "B1", "kind": "quote", "terms": blank, "price": None, **kw}  # noqa: E731
    assert ok({"action": "negotiate", "moves": [move(), move(bidder="B2", kind="counter", price=900.0)]})
    assert not ok({"action": "negotiate", "moves": []})
    assert not ok({"action": "negotiate", "moves": [move(), move()]})  # two moves to one bidder
    assert not ok({"action": "negotiate", "moves": [move(price=10.0)]})  # a price on a quote
    assert not ok({"action": "negotiate", "moves": [move(kind="counter")]})  # a counter without a price
    assert not ok({"action": "negotiate", "moves": [move(bidder="B4")]})
    assert not ok({"action": "negotiate", "moves": [move(terms={**blank, "damages": 100})]})
    assert not ok({"action": "accept", "offer": "B1-O1", "moves": [move()]})
    assert ok({"action": "accept", "offer": "B1-O1"}) and ok({"action": "walk"})
    payload = _payloads()[0]
    plugin = TenderPlugin()
    state, phase = plugin.initial_state(payload, None), plugin.phases(payload)[0]
    assert not plugin.legal(payload, state, "client", phase, parse_tender_move({"action": "accept", "offer": "B1-O9", "moves": None, "reason": ""}).action).legal
    final = {**state, "final": True}
    assert not plugin.legal(payload, final, "client", phase, parse_tender_move({"action": "negotiate", "offer": None, "moves": [move()], "reason": ""}).action).legal


def test_the_cost_split_adds_up_to_the_cost_over_best_attainable() -> None:
    rng = random.Random(3)
    for payload in _payloads()[:8]:
        solver = rt.solver_for(payload)
        for _ in range(30):
            j = rng.randrange(len(solver.bidders))
            ci = rng.randrange(len(solver.menu(j)))
            price = float(solver.th[j][solver.rounds][ci]) + rng.choice([0.0, 40.0])
            signed = {"bidder": j, "contract": solver.menu(j)[ci].as_dict(), "price": price}
            for sig, term in ((signed, "signed"), (None, "walked")):
                g = rt.grade(payload, [], sig, term, refused=rng.randrange(3))
                assert math.fsum(g["split"].values()) == pytest.approx(g["cost_over_best_attainable"], abs=2e-3)


def test_the_pilot_seats_gemini_default_on_the_declared_subset_only_and_not_glm_default() -> None:
    assert ("default_reasoning", "glm53_flash") not in tc._entries(list(tc.ARMS), list(tc.oc.ROUTES))
    manifest, _ = tp.load(tc.PACK)
    subset = tc.subset_case_ids()
    assert len(subset) == len({(w["world_type"], w["situation"]) for w in manifest["worlds"]})


@pytest.mark.parametrize("policy", ["reference", *rt.RULES])
def test_scripted_clients_seal_verified_replayable_receipts_and_the_reference_scores_zero(tmp_path: Path, policy: str) -> None:
    setup = tc.build_setup(tc.CONTROLS_ARM, f"{tc.SCRIPTED}{policy}", tc._cases()[:3])
    entry = {"arm": tc.CONTROLS_ARM, "route_id": f"{tc.SCRIPTED}{policy}"}
    for cell in setup.plan.cells:
        record = asyncio.run(tc._run_cell(tmp_path, entry, setup, cell, tc.oc.Spend(1.0), asyncio.Semaphore(1)))
        assert record["status"] == "ok" and record["grade"]["valid"], record
        if policy == "reference":
            assert record["grade"]["decision_regret"] == 0.0
        else:
            assert record["grade"]["decision_regret"] >= 0.0
