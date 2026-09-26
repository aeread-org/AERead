"""The full-terms menu: every contract term the risk-allocation case can model exactly, with
its levels. The economics must reduce to the one-sided case's, a cap must bound every
outcome, the reference's closed form must equal brute force, every price shown must be a
price the integrator signs at, the brief must not state the pricing policy, and the
reference must grade zero through the kernel."""

from __future__ import annotations

import asyncio
import random
from dataclasses import replace
from pathlib import Path

import pytest

from aeread_families.datacenter_development import risk_allocation as ra
from aeread_families.datacenter_development import risk_allocation_contracts as rc
from aeread_families.datacenter_development import risk_allocation_contracts_campaign as cc
from aeread_families.datacenter_development import risk_allocation_contracts_pack as cp
from aeread_families.datacenter_development.risk_allocation_contracts_environment import ContractsPlugin, listing, parse_contract_move


def _payloads():
    _, cases = cp.load(cc.PACK)
    return [c["payload"] for c in sorted(cases.values(), key=lambda c: c["case_id"])]


def test_uncapped_contracts_without_the_new_terms_cost_what_the_one_sided_case_says() -> None:
    no_prep = rc.Extras(800.0, 1e9)  # site preparation never pays, as in the one-sided case
    for k in range(24):
        w = ra.draw_world(random.Random(k), list(ra.CELLS)[k % len(ra.CELLS)])
        for it, _ in w.prior:
            for pkg in ra.PACKAGES:
                c = rc.Contract(pkg.warranty, "100", "uncapped", pkg.readiness, pkg.consequential,
                                "50%" if pkg.deposit == "at_signing" else "none", False, False)
                assert rc.integrator_cost(c, w, it, no_prep) == pytest.approx(ra.integrator_cost(pkg, w, it), abs=1e-9)
                assert rc.client_cost(c, w, it, no_prep) == pytest.approx(ra.client_cost(pkg, w, it), abs=1e-9)


def test_a_cap_bounds_every_outcome_and_the_new_terms_move_the_right_probabilities() -> None:
    w = ra.draw_world(random.Random(7), "shift_the_tail")
    full = rc.Contract("fix_and_delay", "200", "uncapped", "integrator", "included", "50%", False, False)
    for cap in ("1500", "500"):
        assert max(pay for _, _, pay, _ in rc.outcomes(replace(full, liability_cap=cap), w, False, False)) <= rc.CAP[cap]
    paid = [sum(p * pay for p, _, pay, _ in rc.outcomes(replace(full, liability_cap=cap), w, False, False)) for cap in ("uncapped", "1500", "500")]
    assert paid[0] > paid[1] > paid[2]
    probs = lambda c, prep=False: rc._probabilities(c, w, False, prep)  # noqa: E731
    assert probs(replace(full, burn_in=True))[2] == pytest.approx(0.5 * probs(full)[2])
    assert probs(full, prep=True)[1] == pytest.approx(rc.SITE_PREP_EFFECT * probs(full)[1])
    assert probs(replace(full, escrow=True))[3] == 0.0 and probs(replace(full, deposit="none"))[3] == 0.0
    it = w.prior[0][0]
    assert not rc.best_response(replace(full, readiness="client"), w, it, rc.Extras(800.0, 0.0))[1]  # no standby, no reason to prepare


def test_each_playbook_puts_every_combination_of_its_terms_on_the_menu() -> None:
    assert {p: len(rc.contracts(p)) for p in rc.PLAYBOOKS} == {"coordination": 64, "managed": 240, "turnkey": 360}
    for p in rc.PLAYBOOKS:
        menu = rc.contracts(p)
        assert menu[0] == rc.BASES[p] and all(c == c.normal() for c in menu) and set(rc.listed(p)) <= set(menu)
        fixed = [k for k in rc.TERMS if k not in rc.NEGOTIABLE[p]]
        assert all(getattr(c, k) == getattr(rc.BASES[p], k) for c in menu for k in fixed if k != "damages")


class _Brute(rc.ContractSolver):
    """The same programme with no closed form: every state searched."""

    def value(self, s):
        if s in self._memo:
            return self._memo[s]
        now = min(self.out, self._accept_value(s.types, s.standing))
        v = now if s.final else min(now, min(self.q(s, a) for a in self.candidates(s) if a.kind == "propose"))
        self._memo[s] = v
        return v


def test_the_closed_form_for_a_known_type_equals_searching_every_state() -> None:
    checked_pooled = False
    for seed in range(40):
        cw, it = rc.draw_world(random.Random(seed), "buy_the_cover", "coordination")
        fast, brute = rc.ContractSolver(cw), _Brute(cw)
        s = fast.start(it)
        if seed >= 4 and (len(s.types) == 1 or checked_pooled):
            continue
        checked_pooled |= len(s.types) > 1
        assert fast.value(s) == pytest.approx(brute.value(s), abs=1e-6)
        after = fast.after_refusal(s, fast.menu[5], fast.type_index(it))
        assert fast.value(after) == pytest.approx(brute.value(after), abs=1e-6)
    assert checked_pooled, "no world where the list leaves two types; widen the search"


def test_every_price_shown_is_a_price_the_integrator_signs_at() -> None:
    for payload in _payloads()[:8]:
        solver = rc.solver_for(payload)
        for th in solver.th:
            assert abs(th / rc.PRICE_STEP - (th / rc.PRICE_STEP).round()).max() < 1e-6
        cw, it = rc.world_from(payload)
        plugin = ContractsPlugin()
        state = plugin.initial_state(payload, None)
        offer = state["offers"][1]
        shown = rc.show(cw, offer["price"])
        # countering at the shown list price in round 1 is signed, since the round-1 price is lower than the list
        move = parse_contract_move({"action": "counter", "offer": None, "terms": offer["contract"], "price": shown, "outside": None, "reason": ""})
        assert move.ok and rc.all_in(cw, move.action["price"]) >= float(solver.th[1][solver.index[rc.Contract(**offer["contract"])], solver.type_index(it)]) - 1e-6


def test_the_brief_states_every_term_but_not_the_pricing_policy() -> None:
    for payload in _payloads()[:6]:
        cw, _ = rc.world_from(payload)
        offers = [{"id": o["id"], "terms": o["contract"], "price": rc.show(cw, o["price"])} for o in listing(payload)]
        text = rc.brief(cw, offers)
        for hidden in ("premium", "markup", "floor", "margin", "step"):
            assert hidden not in text.lower()
        assert all(f"- {k}:" in text for k in rc.TERMS) and all(f"- {o['id']}:" in text for o in offers)


def test_moves_are_read_strictly_and_an_off_menu_contract_is_declined_not_invalid() -> None:
    blank = {k: None for k in rc.TERMS}
    ok = lambda m: parse_contract_move({"offer": None, "terms": None, "price": None, "outside": None, "reason": "", **m}).ok  # noqa: E731
    assert ok({"action": "quote", "terms": {**blank, "burn_in": True}})
    assert not ok({"action": "quote", "terms": {**blank, "burn_in": True}, "price": 10.0})
    assert not ok({"action": "counter", "terms": {**blank, "damages": 100}, "price": 900.0})
    assert not ok({"action": "accept", "terms": blank, "offer": "O1"})
    assert not ok({"action": "walk", "outside": "rival"})
    assert ok({"action": "counter", "terms": {**blank, "damages": "200", "escrow": True}, "price": 900.0})
    payload = next(p for p in _payloads() if rc.world_from(p)[0].playbook == "coordination")
    plugin = ContractsPlugin()
    state = plugin.initial_state(payload, None)
    phase = plugin.phases(payload)[0]
    move = parse_contract_move({"action": "quote", "offer": None, "terms": {**blank, "deposit": "none"}, "price": None, "outside": None, "reason": ""})
    assert plugin.legal(payload, state, "client", phase, move.action).legal  # deposit is fixed on this playbook: declined, not illegal
    accept_unknown = parse_contract_move({"action": "accept", "offer": "O99", "terms": None, "price": None, "outside": None, "reason": ""})
    assert not plugin.legal(payload, state, "client", phase, accept_unknown.action).legal


def test_the_packed_worlds_still_teach_their_lessons_and_the_shortcuts_lose() -> None:
    manifest, cases = cp.load(cc.PACK)
    assert len(manifest["worlds"]) == 58 and len({w["seed"] for w in manifest["worlds"]}) == 58
    for w in manifest["worlds"]:
        cw, it = rc.world_from(cases[w["case_id"]]["payload"])
        assert rc.lesson_holds(w["cell"], cw, it), w["slug"]
        solver = rc.solver_for(cases[w["case_id"]]["payload"])
        t, (best, best_cost) = solver.type_index(it), solver.best_contract(it)
        assert abs(cw.best_outside[1] - best_cost) >= rc.WALK_MARGIN
        cut = rc.shortcuts(solver, solver.start(it))
        for name in rc.CELLS[w["cell"]]["losers"]:
            assert solver.total[solver.rounds][solver.index[cut[name]], t] - best_cost >= rc.CHOICE_MARGIN, (w["slug"], name)


def test_the_full_terms_campaign_does_not_seat_glm_at_default_reasoning() -> None:
    assert ("default_reasoning", "glm53_flash") not in cc._entries(list(cc.ARMS), list(cc.oc.ROUTES))


@pytest.mark.parametrize("policy", ["reference", "every_protection"])
def test_scripted_clients_seal_verified_replayable_receipts_and_the_reference_scores_zero(tmp_path: Path, policy: str) -> None:
    setup = cc.build_setup(cc.CONTROLS_ARM, f"{cc.SCRIPTED}{policy}", cc._cases()[:3])
    assert "scripted" in setup.plan.agent_profiles[0].profile_id
    entry = {"arm": cc.CONTROLS_ARM, "route_id": f"{cc.SCRIPTED}{policy}"}
    for cell in setup.plan.cells:
        record = asyncio.run(cc._run_cell(tmp_path, entry, setup, cell, cc.oc.Spend(1.0), asyncio.Semaphore(1)))
        assert record["status"] == "ok" and record["grade"]["valid"]
        if policy == "reference":
            assert record["grade"]["decision_regret"] == 0.0
        else:
            assert record["grade"]["decision_regret"] >= 0.0


def test_the_campaign_checks_the_account_before_any_model_cell_and_stops_at_the_first_402() -> None:
    plan = {"min_account_balance_usd": 8.0, "plans": [{"route_id": "gemini38_flash"}, {"route_id": f"{cc.SCRIPTED}reference"}]}
    with pytest.raises(SystemExit, match="below the plan's floor"):
        cc.preflight(plan, balance=lambda: 0.5)
    cc.preflight(plan, balance=lambda: 9.0)
    cc.preflight({**plan, "plans": [{"route_id": f"{cc.SCRIPTED}reference"}]}, balance=lambda: 0.0)  # controls cost nothing
    assert cc.is_out_of_credit(RuntimeError("Error code: 402 - {'error': {'message': 'Insufficient credits'}}"))
    assert not cc.is_out_of_credit(RuntimeError("Error code: 429 - rate limited"))
