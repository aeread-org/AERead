"""Inference v2: the properties that make whom-to-verify a question the buyer can answer.

Each test pins one thing the first panel got wrong (incident row P-D-15) or one
thing this pack promises, so an edit that quietly brings the old shape back
fails here and not in a run.
"""

from __future__ import annotations

import json
from collections import Counter

import pytest

from aeread_families.procurement_allocation import inference_v2_case_matrix as v2
from aeread_families.procurement_allocation.environment import ProcurementAllocationPlugin
from aeread_families.procurement_allocation.inference_v2_prompt import NEUTRAL_PROMPT
from aeread_families.procurement_allocation.strategy_scaffold import STRATEGY_PROMPT
from aeread_families.procurement_allocation.trajectory_analysis import SOLVED_REGRET_USD


@pytest.fixture(scope="module")
def pack() -> dict:
    return v2.build_pack()


@pytest.fixture(scope="module")
def worlds(pack) -> list[dict]:
    by_id = {case["case_id"]: case for case in pack["cases"]}
    return [{**world, "case": by_id[world["case_id"]]} for world in pack["manifest"]["worlds"]]


def _first_observation(case: dict) -> dict:
    plugin = ProcurementAllocationPlugin()
    family_case = plugin.validate_payload(case["payload"])
    return plugin.observe(family_case, plugin.initial_state(family_case, None), "buyer", plugin.phases(family_case)[0])


# --- the committed pack is what the generator makes -----------------------------


def test_committed_pack_is_reproduced_byte_for_byte(pack) -> None:
    for case in pack["cases"]:
        path = v2.PACK_ROOT / f"{case['case_id'].rsplit('.', 1)[-1]}.json"
        assert path.read_text(encoding="utf-8") == json.dumps(case, indent=2, sort_keys=True) + "\n"
    committed = (v2.PACK_ROOT / "pack.json").read_text(encoding="utf-8")
    assert committed == json.dumps(pack["manifest"], indent=2, sort_keys=True) + "\n"
    assert len(v2.case_paths()) == 18


def test_every_signal_meets_every_binding_risk_once(worlds) -> None:
    assert Counter((w["signal"], w["risk"]) for w in worlds) == Counter(
        (signal, risk) for signal in v2.SIGNALS for risk in v2.RISKS
    )


# --- there is something to read, and only one thing ----------------------------


def test_one_component_has_a_record_on_every_listing_and_the_other_has_none(worlds) -> None:
    for world in worlds:
        records = Counter()
        for row in _first_observation(world["case"])["supplier_listings"]:
            records[(row["component"], row["listing"]["marketplace_record"]["orders_reported"] > 0)] += 1
        assert records == Counter({(world["recorded_component"], True): 4, (world["unrecorded_component"], False): 4})


def test_the_record_names_the_good_suppliers_and_one_attribute_separates_them(worlds) -> None:
    for world in worlds:
        observation = _first_observation(world["case"])
        rows = v2._listings(observation)[world["recorded_component"]]
        assert v2.separating_attributes(rows) == [(v2.attribute_of(world["signal"]), v2.high_is_good(world["signal"]))]
        largest = max(r["marketplace_record"]["largest_order_filled_units"] for r in rows)
        named = {r["supplier_id"] for r in rows if v2.record_says_good(r, largest=largest)}
        assert named == {s for s in world["good_supplier_ids"] if s.startswith(world["recorded_component"])}


def test_the_other_attributes_carry_no_information_on_either_component(worlds) -> None:
    for world in worlds:
        good = set(world["good_supplier_ids"])
        signal_attribute = v2.attribute_of(world["signal"])
        for rows in v2._listings(_first_observation(world["case"])).values():
            for name in v2.ATTRIBUTES:
                if name == signal_attribute:
                    continue
                field = v2.LISTING_FIELD[name]
                ranked = sorted(rows, key=lambda r: r[field])
                assert ranked[1][field] < ranked[2][field], "two levels, two listings each"
                assert sorted(r["supplier_id"] in good for r in ranked[:2]) == [False, True]
                assert sorted(r["supplier_id"] in good for r in ranked[2:]) == [False, True]


def test_price_is_not_the_signal_in_disguise(worlds) -> None:
    """v1's decoy left the cheapest listing good in every low-is-good world and bad in every other."""
    other = [w for w in worlds if v2.attribute_of(w["signal"]) != "price"]
    assert Counter(w["cheapest_unrecorded_is_good"] for w in other) == Counter({True: 6, False: 6})
    assert all(w["dearest_unrecorded_is_good"] != w["cheapest_unrecorded_is_good"] for w in other)
    assert Counter(w["cheapest_unrecorded_is_good"] for w in worlds) == Counter({True: 9, False: 9})
    assert Counter(w["recorded_component"] for w in worlds) == Counter({"sht30_i2c": 9, "bh1750_gy302": 9})
    for direction in (True, False):
        split = Counter(w["cheapest_unrecorded_is_good"] for w in other if v2.high_is_good(w["signal"]) == direction)
        assert split == Counter({True: 3, False: 3}), "the signal's direction does not predict the cheapest listing"


def test_nothing_the_buyer_sees_names_the_cell_or_links_listings_across_components(worlds) -> None:
    for world in worlds:
        observation = _first_observation(world["case"])
        shown = json.dumps(observation)
        assert "is_good" not in shown and world["slug"] not in shown and world["signal"] not in shown
        listings = v2._listings(observation)
        prices = [{r["displayed_unit_price_usd"] for r in rows} for rows in listings.values()]
        assert not prices[0] & prices[1]
        codes = [row["supplier_id"].rsplit("_l", 1)[-1] for row in observation["supplier_listings"]]
        assert len(set(codes)) == 8 and all(code.isdigit() for code in codes)
        # every listing claims the same yield, so a claim separates nobody
        assert {row["listing"]["claimed_yield_rate"] for row in observation["supplier_listings"]} == {0.99}


# --- verification is scarce, a wrong choice costs and does not end the episode ---


def test_the_budget_buys_one_verified_supplier_per_component(worlds) -> None:
    for world in worlds:
        payload = world["case"]["payload"]
        assert payload["interaction"]["max_actions"] == world["case"]["episode"]["max_logical_actions"] == 5
        assert payload["objective"]["target_kits"] == 19 and payload["objective"]["minimum_service_kits"] == 8


def test_reading_the_record_and_carrying_it_over_solves_every_world(worlds) -> None:
    for world in worlds:
        outcome = v2.replay(world["case"]["payload"], lambda o: v2.choose_targets(o, mode="informed"))
        assert outcome["decision"] == "award" and not outcome["violations"]
        assert outcome["regret_to_upper_bound_usd"] < 10.0
        assert set(outcome["targets"].values()) <= set(world["good_supplier_ids"])


def test_no_fixed_listing_rule_does_better_than_about_half(pack) -> None:
    solved = pack["manifest"]["reference_worlds_solved"]
    assert solved["informed"] == 18
    assert solved["records_then_rule:cheapest_first"] == solved["records_then_rule:dearest_first"] == 9
    for rule in v2.RULES:
        assert 6 <= solved[f"records_then_rule:{rule}"] <= 12
        assert solved[f"rule_only:{rule}"] <= 9


def test_a_wrong_supplier_costs_most_of_the_margin_and_not_all_of_it(worlds) -> None:
    """v1's score was a cliff: regret was under $50 or over $250 and nothing between."""
    wrong = [
        (regret, world["upper_bound_usd"])
        for world in worlds
        for policy, regret in world["reference_regret_usd"].items()
        if policy.startswith("records_then_rule") and regret >= SOLVED_REGRET_USD
    ]
    assert len(wrong) >= 40
    for regret, bound in wrong:
        assert 0.45 * bound < regret < 0.75 * bound


# --- the prompt says what the marketplace is and prescribes no procedure -------


def test_the_prompt_prescribes_no_ranking_and_states_the_three_facts() -> None:
    text = " ".join(NEUTRAL_PROMPT.lower().split())
    for phrase in ("rank", "smallest plausible", "decision procedure", "before considering price"):
        assert phrase not in text
    assert "rank the remaining candidates" in " ".join(STRATEGY_PROMPT.lower().split()), "what v1 was played under"
    for fact in ("actions_left counts every action", "marketplace_record", "tends to hold for the other"):
        assert fact in text
