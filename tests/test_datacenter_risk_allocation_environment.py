"""The risk-allocation case played through its environment plugin.

Pinned here: what a model sees carries no hidden type and no cell name (twins
with different hidden types see byte-identical first observations), the
reference played through the plugin grades zero regret in every committed case,
a rule that does not negotiate the allocation is charged where the pack says it
loses, and a malformed or illegal move ends the episode as typed missingness.
"""

from __future__ import annotations

import json
from dataclasses import replace
from functools import lru_cache

import pytest

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.task.execution import CanonicalResponse
from aeread.shared_runner.task.scheduler import ActionEnvelope
from aeread_families.datacenter_development import risk_allocation as ra
from aeread_families.datacenter_development import risk_allocation_pack as rp
from aeread_families.datacenter_development.risk_allocation_environment import RiskAllocationPlugin, game_of, grade, seen_of

PACK = "risk_allocation_dev_v1"


@lru_cache(maxsize=1)
def _pack() -> tuple[dict, dict]:
    return rp.load(PACK)


def _world(cell: str, twin: bool = False) -> dict:
    manifest, _ = _pack()
    return next(w for w in manifest["worlds"] if w["cell"] == cell and ("twin_of" in w) == twin)


def _case(world: dict, seat: str) -> dict:
    return _pack()[1][world["seats"][seat]["case_id"]]


class Episode:
    def __init__(self, raw: dict) -> None:
        self.plugin = RiskAllocationPlugin()
        self.payload = self.plugin.validate_payload(raw["payload"])
        self.seat = self.payload["seat"]
        self.phase = self.plugin.phases(self.payload)[0]
        self.state = self.plugin.initial_state(self.payload, None)

    def observe(self) -> dict:
        return self.plugin.observe(self.payload, self.state, self.seat, self.phase)

    def play(self, response) -> None:
        parsed = self.plugin.parse_action(self.payload, self.state, self.seat, self.phase, response)
        legality = self.plugin.legal(self.payload, self.state, self.seat, self.phase, parsed.action) if parsed.ok else None
        envelope = ActionEnvelope(self.seat, bool(parsed.ok and legality.legal), parsed.action if parsed.ok else None, parsed, legality)
        self.state = self.plugin.step(self.payload, self.state, self.phase, {self.seat: envelope}).state


def _as_json(a: ra.Action) -> dict:
    if a.kind != "propose":
        return {"action": a.kind, "package": None, "price": None, "reason": "reference"}
    return {"action": "propose", "package": a.package.as_dict(), "price": None if a.price == ra.PRICE_IT else a.price, "reason": "reference"}


def _play_policy(raw: dict, policy_of) -> Episode:
    ep = Episode(raw)
    game, _ = game_of(ep.payload)
    policy = policy_of(game)
    while not ep.state["finished"]:
        ep.play(_as_json(policy(seen_of(ep.payload, ep.state))))
    return ep


def test_committed_cases_verify_and_regenerate_byte_for_byte() -> None:
    manifest, cases = _pack()
    assert len(cases) == 2 * len(manifest["worlds"])
    for raw in cases.values():
        assert case_content_sha256(raw) == raw["content_sha256"]
    built, rebuilt_manifest = rp.build(PACK)
    assert {c["case_id"]: c["content_sha256"] for c in built} == {k: v["content_sha256"] for k, v in cases.items()}
    assert json.loads(json.dumps(rebuilt_manifest, sort_keys=True)) == manifest


def test_nothing_a_model_sees_names_the_cell_or_the_hidden_answer() -> None:
    manifest, cases = _pack()
    words = set(ra.CELLS) | {"lesson", "hidden", "efficient", "reference", "twin"}
    for raw in cases.values():
        assert not any(cell in raw["case_id"] for cell in ra.CELLS)
        text = json.dumps(Episode(raw).observe()).lower()
        for word in words:
            assert word not in text, (raw["case_id"], word)


def test_twins_with_different_hidden_types_see_the_same_first_observation() -> None:
    manifest, _ = _pack()
    twins = [w for w in manifest["worlds"] if "twin_of" in w]
    assert twins
    for twin in twins:
        base = next(w for w in manifest["worlds"] if w["slug"] == twin["twin_of"])
        a, b = Episode(_case(base, "client")), Episode(_case(twin, "client"))
        assert a.payload["integrator_type"] != b.payload["integrator_type"]
        assert json.dumps(a.observe(), sort_keys=True) == json.dumps(b.observe(), sort_keys=True)


def test_the_integrator_seat_does_not_see_the_clients_charge() -> None:
    raw = _case(_world("price_the_alternatives"), "integrator")
    first = json.dumps(Episode(raw).observe(), sort_keys=True)
    for charge, _ in ra.CLIENT_PRIOR:
        other = json.loads(json.dumps(raw))
        other["payload"]["world"]["client"]["risk_charge"] = charge
        assert json.dumps(Episode(other).observe(), sort_keys=True) == first


def test_the_reference_played_through_the_plugin_grades_clean_in_every_case() -> None:
    _, cases = _pack()
    for raw in cases.values():
        ep = _play_policy(raw, ra.reference_policy)
        graded = grade(ep.payload, ep.state)
        assert graded["valid"], raw["case_id"]
        assert graded["decision_regret"] == pytest.approx(0.0, abs=1e-6), (raw["case_id"], graded["decisions"])


def test_price_only_haggling_is_charged_where_the_allocation_matters_and_not_where_it_does_not() -> None:
    haggle = lambda game: ra.rules(game)["haggle_price_only"]  # noqa: E731
    loses = grade(*(lambda ep: (ep.payload, ep.state))(_play_policy(_case(_world("price_the_alternatives"), "client"), haggle)))
    assert loses["decision_regret"] > ra.LOSER_MARGIN and loses["allocation_gap"] > 0
    right = grade(*(lambda ep: (ep.payload, ep.state))(_play_policy(_case(_world("keep_their_terms"), "client"), haggle)))
    assert right["decision_regret"] == pytest.approx(0.0, abs=1e-6)


def test_walking_is_free_only_where_no_deal_beats_turnkey() -> None:
    walk = lambda game: (lambda seen: ra.Action("walk"))  # noqa: E731
    away = _play_policy(_case(_world("walk_away"), "client"), walk)
    g = grade(away.payload, away.state)
    assert g["decision_regret"] == pytest.approx(0.0, abs=1e-6) and g["allocation_gap"] == 0 and g["deal_surplus"] < 0
    stay = _play_policy(_case(_world("shift_the_tail"), "client"), walk)
    g = grade(stay.payload, stay.state)
    assert g["decision_regret"] > 100 and g["allocation_gap"] == pytest.approx(g["deal_surplus"])


def test_a_counter_teaches_the_integrators_cost_and_is_shown_as_a_price() -> None:
    raw = _case(_world("price_the_alternatives"), "client")
    ep = Episode(raw)
    probe = ra.Package("fix_and_delay", "client", "included", "at_signing")
    ep.play({"action": "propose", "package": probe.as_dict(), "price": None, "reason": "price it"})
    if ep.state["termination"] == "broke_off":
        pytest.skip("this world's first draw breaks off")
    obs = ep.observe()
    game, truth = game_of(ep.payload)
    assert obs["standing_offer"]["price"] == pytest.approx(ra.ask_price(probe, game.w, truth, 1), abs=1e-3)
    assert obs["round"] == 2 and "would sign this package at" in obs["history"][0]["answer"]


def test_malformed_and_illegal_moves_end_the_episode_as_typed_missingness() -> None:
    world = _world("price_the_alternatives")
    ep = Episode(_case(world, "integrator"))
    ep.play({"action": "accept", "package": None, "price": None, "reason": "x"})  # nothing to accept yet
    assert ep.state["termination"] == "invalid_action" and ep.state["invalid"] == "nothing_to_accept"
    assert not grade(ep.payload, ep.state)["valid"]
    ep = Episode(_case(world, "client"))
    ep.play(CanonicalResponse("not json", "stop", False, False, (), (), 0, 0, 0, 0.0))
    assert ep.state["invalid"] == "malformed_json"
    ep = Episode(_case(world, "client"))
    ep.play({"action": "propose", "package": {"warranty": "gold"}, "price": 1.0, "reason": "x"})
    assert ep.state["invalid"] == "bad_package"
    ep = Episode(_case(world, "client"))
    ep.play({"action": "walk", "package": ra.OPENING.as_dict(), "price": None, "reason": "x"})
    assert ep.state["invalid"] == "terms_on_a_non_proposal"


def test_a_model_response_is_read_from_the_text_the_provider_returned() -> None:
    ep = Episode(_case(_world("keep_their_terms"), "client"))
    text = 'Here is my move: {"action": "walk", "package": null, "price": null, "reason": "turnkey"}'
    ep.play(CanonicalResponse(text, "stop", False, False, (), (), 0, 0, 0, 0.0))
    assert ep.state["termination"] == "walked"


def test_both_seats_and_twins_share_the_break_off_draws() -> None:
    manifest, cases = _pack()
    for world in manifest["worlds"]:
        draws = {json.dumps(cases[s["case_id"]]["payload"]["breakoff_draws"]) for s in world["seats"].values()}
        assert len(draws) == 1
        if "twin_of" in world:
            base = next(w for w in manifest["worlds"] if w["slug"] == world["twin_of"])
            assert cases[base["seats"]["client"]["case_id"]]["payload"]["breakoff_draws"] == cases[world["seats"]["client"]["case_id"]]["payload"]["breakoff_draws"]


def test_validate_refuses_a_type_outside_the_declared_prior() -> None:
    raw = json.loads(json.dumps(_case(_world("close_now"), "client")))
    raw["payload"]["integrator_type"]["test_cost"] = 55.0
    with pytest.raises(ValueError):
        RiskAllocationPlugin().validate_payload(raw["payload"])
    w = ra.world_from_dict(raw["payload"]["world"])
    assert replace(w.client, risk_charge=0.4).risk_charge not in {c for c, _ in w.client_prior}
