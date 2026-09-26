"""The playbook-menu case: the integrator posts a playbook and a menu of negotiable options;
the client negotiates the item best for itself. The reference must grade zero, the brief must not
state the pricing policy, and the kernel path must seal and replay."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from aeread_families.datacenter_development import risk_allocation as ra
from aeread_families.datacenter_development import risk_allocation_menu as rm
from aeread_families.datacenter_development import risk_allocation_menu_campaign as mc
from aeread_families.datacenter_development import risk_allocation_menu_pack as mp
from aeread_families.datacenter_development.risk_allocation_menu_environment import MenuPlugin, parse_menu_move, world_of


def test_each_playbook_offers_three_negotiable_options_and_prices_all_eight_combinations() -> None:
    for playbook, items in rm.PLAYBOOKS.items():
        assert len(rm.OPTIONS[playbook]) == 3 and len(items) == 8 and len(set(items)) == 8
        assert items[0] == rm.BASES[playbook]


def test_the_policy_chooses_playbooks_by_the_integrators_costs() -> None:
    assert rm.playbook_of(ra.IntegratorType(40.0, 1.2)) == "coordination"
    assert rm.playbook_of(ra.IntegratorType(40.0, 0.3)) == "turnkey"
    assert rm.playbook_of(ra.IntegratorType(200.0, 0.3)) == "managed"


def _cases():
    _, cases = mp.load(mc.PACK)
    return [c["payload"] for c in sorted(cases.values(), key=lambda c: c["case_id"])]


def test_the_brief_shows_the_menu_but_not_the_pricing_policy() -> None:
    for payload in _cases()[:6]:
        mw, it = world_of(payload)
        text = rm.menu_brief(mw, rm.list_prices(mw.playbook, mw.w, it))
        for hidden in ("premium", "markup", "floor", "margin"):
            assert hidden not in text.lower()
        assert all(f"- {label}:" in text for label in rm.LABELS)


def test_a_counter_is_read_in_the_menus_own_terms() -> None:
    fee_payload = next(p for p in _cases() if rm.fee_based(world_of(p)[0].playbook))
    mw, _ = world_of(fee_payload)
    assert rm.all_in_price(mw, 1000.0) == 1000.0 + mw.w.terms.hardware
    assert not parse_menu_move({"action": "walk", "item": None, "price": None, "outside": None, "reason": ""}).ok
    assert not parse_menu_move({"action": "accept", "item": "Z", "price": None, "outside": None, "reason": ""}).ok
    assert parse_menu_move({"action": "counter", "item": "C", "price": 900, "outside": None, "reason": ""}).action["price"] == 900.0


@pytest.mark.parametrize("policy", ["reference", "haggle_the_base_item"])
def test_scripted_clients_seal_verified_replayable_receipts_and_the_reference_scores_zero(tmp_path: Path, policy: str) -> None:
    setup = mc.build_setup(mc.CONTROLS_ARM, f"{mc.SCRIPTED}{policy}", mc._cases()[:3])
    assert "scripted" in setup.plan.agent_profiles[0].profile_id
    entry = {"arm": mc.CONTROLS_ARM, "route_id": f"{mc.SCRIPTED}{policy}"}
    for cell in setup.plan.cells:
        record = asyncio.run(mc._run_cell(tmp_path, entry, setup, cell, mc.oc.Spend(1.0), asyncio.Semaphore(1)))
        assert record["status"] == "ok" and record["grade"]["valid"], record
        if policy == "reference":
            assert record["grade"]["decision_regret"] == pytest.approx(0.0, abs=1e-6)


def test_every_situation_is_admitted_on_every_playbook() -> None:
    manifest, _ = mp.load(mc.PACK)
    pairs = {(w["cell"], w["playbook"]) for w in manifest["worlds"]}
    assert pairs == {(c, p) for c in rm.CELLS for p in rm.PLAYBOOKS}
