"""Pay or test: the properties that make the pack a decision with a known best answer.

Each test pins one thing the pack promises: that the committed worlds are what
the generator makes, that a cell is what its name says, that nothing on a
listing gives a newcomer's type away, that the reference's values are the
environment's own averages, and that every rule the prompt states is true.
"""

from __future__ import annotations

import itertools
import json
from collections import Counter

import pytest

from aeread_families.procurement_allocation import pay_or_test_case_matrix as pack_module
from aeread_families.procurement_allocation import pay_or_test_reference as reference
from aeread_families.procurement_allocation.environment import ProcurementAllocationPlugin, _base_offer, _quantity_values, evaluate_award
from aeread_families.procurement_allocation.pay_or_test_prompt import PAY_OR_TEST_PROMPT

GOOD, LATE, POOR = reference.GOOD, reference.LATE, reference.POOR


@pytest.fixture(scope="module")
def pack() -> dict:
    return pack_module.build_pack()


@pytest.fixture(scope="module")
def worlds(pack) -> list[dict]:
    by_id = {case["case_id"]: case for case in pack["cases"]}
    return [{**world, "case": by_id[world["case_id"]]} for world in pack["manifest"]["worlds"]]


def _observe(payload: dict, actions: list[dict] | None = None) -> dict:
    plugin = ProcurementAllocationPlugin()
    family_case = plugin.validate_payload(payload)
    state = reference.run(payload, actions or [])
    return plugin.observe(family_case, state, "buyer", plugin.phases(family_case)[0])


def _rebuilt(world: dict, types: tuple[str, ...]) -> dict:
    spec = next(s for s in pack_module.world_specs() if s["slug"] == world["slug"])
    structure = pack_module.draw_structure(spec, world["world_seed"])
    return pack_module.build_case(spec, world["world_seed"], structure, types, seal=False)["payload"]


def _quote(sid: str) -> dict:
    return {"action": "request_quote", "supplier_id": sid, "message": "quote"}


def _sample(sid: str) -> dict:
    return {"action": "request_sample", "supplier_id": sid, "message": "sample"}


def _award(sid: str, quantity: int) -> dict:
    return {"action": "submit_award", "award_lines": [{"offer_id": f"offer_{sid}_v1", "quantity": quantity}]}


# --- the committed pack is what the generator makes -----------------------------


def test_committed_pack_is_reproduced_byte_for_byte(pack) -> None:
    for case in pack["cases"]:
        path = pack_module.PACK_ROOT / f"{case['case_id'].rsplit('.', 1)[-1]}.json"
        assert path.read_text(encoding="utf-8") == json.dumps(case, indent=2, sort_keys=True) + "\n"
    committed = (pack_module.PACK_ROOT / "pack.json").read_text(encoding="utf-8")
    assert committed == json.dumps(pack["manifest"], indent=2, sort_keys=True) + "\n"
    assert len(pack_module.case_paths()) == 24


def test_six_cells_of_four_worlds(worlds) -> None:
    assert Counter((w["move"], w["clock"]) for w in worlds) == Counter({cell: 4 for cell in pack_module.CELLS})


# --- a cell is what its name says -------------------------------------------------


def test_in_a_pay_world_paying_is_the_best_policy_and_every_single_test_loses(worlds) -> None:
    for world in (w for w in worlds if w["move"].startswith("pay")):
        assert world["best_policy_value_usd"] - world["pay_value_usd"] <= pack_module.CLOSE_USD, world["slug"]
        assert max(world["test_once_value_usd"].values()) <= world["pay_value_usd"] - pack_module.DECISIVE_USD, world["slug"]


def test_a_pay_time_world_would_say_test_with_one_more_test_of_time(worlds) -> None:
    one_test = pack_module.QUOTE_DAYS + pack_module.NEWCOMER_SAMPLE_DAYS
    for world in (w for w in worlds if w["move"] == "pay_time"):
        payload = json.loads(json.dumps(world["case"]["payload"]))
        payload["objective"]["deadline_days"] += one_test
        assert pack_module.classify(payload)["move"] in ("test_cheapest", "test_other"), world["slug"]


def test_in_a_test_world_one_newcomer_beats_paying_and_the_cell_says_whether_it_is_the_cheapest(worlds) -> None:
    for world in (w for w in worlds if w["move"].startswith("test")):
        once = world["test_once_value_usd"]
        best = world["best_single_test"]
        assert once[best] >= world["pay_value_usd"] + pack_module.DECISIVE_USD, world["slug"]
        assert all(once[best] >= value + pack_module.DECISIVE_USD for sid, value in once.items() if sid != best), world["slug"]
        assert (best == world["cheapest_newcomer"]) == (world["move"] == "test_cheapest"), world["slug"]


def test_the_clock_fits_the_number_of_tests_its_name_says(worlds) -> None:
    one_test = pack_module.QUOTE_DAYS + pack_module.NEWCOMER_SAMPLE_DAYS
    fall_back = pack_module.QUOTE_DAYS + pack_module.ESTABLISHED_SAMPLE[1] + pack_module.ESTABLISHED_LEAD_DAYS
    for world in worlds:
        fits = (world["deadline_days"] - fall_back) // one_test
        assert fits == pack_module.CLOCK_TESTS[world["clock"]], world["slug"]


# --- worlds are admitted on structure, and types are a fair draw ---------------


def test_the_cell_does_not_depend_on_how_the_newcomers_turned_out(worlds) -> None:
    for world in worlds[::4]:
        seen = pack_module.classify(world["case"]["payload"])
        for types in ((GOOD, GOOD, GOOD), (LATE, POOR, LATE), (POOR, LATE, GOOD)):
            assert pack_module.classify(_rebuilt(world, types)) == seen, world["slug"]


def test_a_listing_is_the_same_whatever_type_its_seller_is(worlds) -> None:
    world = worlds[0]
    listings = []
    for types in ((GOOD, GOOD, GOOD), (LATE, LATE, LATE), (POOR, POOR, POOR)):
        observation = _observe(_rebuilt(world, types))
        listings.append(json.dumps(observation["supplier_listings"], sort_keys=True))
    assert len(set(listings)) == 1


def test_types_follow_the_stated_shares() -> None:
    spec = pack_module.world_specs()[8]
    drawn: Counter = Counter()
    expected = {GOOD: 0.0, LATE: 0.0, POOR: 0.0}
    for seed in range(8_000_000, 8_002_000):
        structure = pack_module.draw_structure(spec, seed)
        for newcomer, kind in zip(structure["newcomers"], pack_module.draw_types(structure, seed)):
            drawn[kind] += 1
            expected[LATE] += newcomer["late"] / pack_module.COHORT_TRACKED
            expected[POOR] += newcomer["failed"] / pack_module.COHORT_TRACKED
            expected[GOOD] += 1.0 - (newcomer["late"] + newcomer["failed"]) / pack_module.COHORT_TRACKED
    for kind in (GOOD, LATE, POOR):
        assert abs(drawn[kind] - expected[kind]) < 4 * (expected[kind] ** 0.5), (kind, drawn[kind], expected[kind])


def test_the_pack_records_types_that_match_its_cases(worlds) -> None:
    for world in worlds:
        terms = {s["supplier_id"]: s["private_terms"] for s in world["case"]["payload"]["suppliers"]}
        for newcomer in world["newcomers"]:
            mine = terms[newcomer["supplier_id"]]
            kind = (LATE if mine["on_time_probability"] < reference.BAD_BELOW
                    else POOR if mine["quality"]["verified_yield_rate"] < reference.BAD_BELOW else GOOD)
            assert kind == newcomer["type"], world["slug"]


# --- the reference's numbers are the environment's ------------------------------


@pytest.mark.parametrize("index", [0, 5, 9, 14, 17, 22])
def test_expected_values_equal_the_average_over_every_way_the_newcomers_could_turn_out(worlds, index) -> None:
    world = worlds[index]
    ref = reference.Reference(world["case"]["payload"])
    order = [n["supplier_id"] for n in world["newcomers"]]
    share = {n["supplier_id"]: {GOOD: n["stated_good_share"], LATE: n["stated_late_share"], POOR: n["stated_poor_share"]}
             for n in world["newcomers"]}
    totals = {name: 0.0 for name in ("best_policy", *reference.RULES)}
    for types in itertools.product((GOOD, LATE, POOR), repeat=len(order)):
        weight = 1.0
        for sid, kind in zip(order, types):
            weight *= share[sid][kind]
        payload = _rebuilt(world, types)
        probe = reference.Reference(payload)
        for name in totals:
            actions = reference.play(payload, None if name == "best_policy" else reference.RULES[name])
            totals[name] += weight * reference.final_margin(probe, reference.run(payload, actions))
    start = ref.start()
    assert totals["best_policy"] == pytest.approx(ref.value(*start), abs=1e-6)
    for name, rule in reference.RULES.items():
        assert totals[name] == pytest.approx(ref.rule_value(name, rule, *start), abs=1e-6), name
        assert totals[name] <= totals["best_policy"] + 1e-6, name


def test_the_best_policy_gives_nothing_up_and_no_rule_beats_it(worlds) -> None:
    for world in worlds:
        assert world["realized"]["best_policy"]["decision_loss_usd"] == 0.0, world["slug"]
        for name, value in world["rule_value_usd"].items():
            assert value <= world["best_policy_value_usd"] + 0.01, (world["slug"], name)


def test_no_split_award_beats_the_best_single_supplier(worlds) -> None:
    for world in worlds[::3]:
        payload = _rebuilt(world, (GOOD, GOOD, GOOD))
        ref = reference.Reference(payload)
        offers = {sid: _base_offer(s, version=1, issued_day=0) for sid, s in ref._good.items()}
        evidence = {sid: {**s["private_terms"]["quality"], "supplier_id": sid, "variant_id": s["private_terms"]["variant_id"],
                          "evidence_status": "verified_sample"} for sid, s in ref._good.items()}
        best_single = max(ref.award(i, 0)[0] for i in range(len(ref.ids)))
        for a, b in itertools.combinations(ref.ids, 2):
            for qa in _quantity_values(offers[a]):
                for qb in _quantity_values(offers[b]):
                    result = evaluate_award(
                        ref.case, award_lines=[{"offer_id": offers[a]["offer_id"], "quantity": qa},
                                               {"offer_id": offers[b]["offer_id"], "quantity": qb}],
                        offers={o["offer_id"]: o for o in offers.values()}, quality_evidence=evidence,
                        elapsed_days=0, information_cost_usd=0.0)
                    assert not result["feasible"] or result["contribution_margin_usd"] <= best_single + 1e-9


def test_a_trajectory_is_priced_action_by_action(worlds) -> None:
    world = next(w for w in worlds if w["slug"] == "test_other__tight__1")
    payload = world["case"]["payload"]
    established = world["established"]["supplier_id"]
    # Pay the premium in a world where a test was worth more, after one stray inquiry.
    actions = [{"action": "inquire", "supplier_id": established, "fields": ["quality"], "message": "?"},
               _quote(established), _sample(established), _award(established, 55)]
    scored = reference.score_actions(payload, actions)
    gap = world["best_policy_value_usd"] - world["pay_value_usd"]
    assert scored["decision_loss_usd"] == pytest.approx(gap + pack_module.INQUIRY_FEE_USD, abs=0.02)
    assert scored["loss_by_part_usd"]["award_terms"] == 0.0
    # The same plan with five units too many loses on the award's own terms.
    wasteful = reference.score_actions(payload, actions[1:3] + [_award(established, 60)])
    assert wasteful["loss_by_part_usd"]["award_terms"] > 50.0
    # An action the environment rejects ends the order with nothing supplied.
    broken = reference.score_actions(payload, [{"action": "request_quote", "supplier_id": "nobody", "message": "x"}])
    assert broken["steps"][0]["valid"] is False
    assert broken["outcome"]["contribution_margin_usd"] == pack_module.NO_SUPPLY_VALUE_USD


# --- what the buyer is shown is true, and what the prompt states is true -----------


def test_a_listing_states_the_price_lead_time_and_sample_terms_the_supplier_holds(worlds) -> None:
    for world in worlds:
        payload = world["case"]["payload"]
        assert "sample_noise" not in payload["interaction"], "noisy samples make the pre-award check an oracle (P-D-17)"
        process, interaction = payload["policy"]["process"], payload["interaction"]
        assert (process["quote_fee_usd"], process["quote_days"]) == (interaction["quote_cost_usd"], interaction["quote_days"])
        assert (process["inquiry_fee_usd"], process["counter_fee_usd"]) == (interaction["inquiry_cost_usd"], interaction["counter_cost_usd"])
        for supplier in payload["suppliers"]:
            listing, terms = supplier["listing"], supplier["private_terms"]
            assert listing["displayed_unit_price_usd"] == terms["base_unit_price_usd"]
            assert listing["claimed_lead_time_days"] == terms["lead_time_days"]
            assert (listing["sample_fee_usd"], listing["sample_days"]) == (
                terms["quality"]["sample_cost_usd"], terms["quality"]["sample_lead_time_days"])
            assert ("cohort_record" in listing) == (listing["marketplace_record"]["orders_reported"] == 0)


def test_only_a_quote_shows_lateness_and_only_a_sample_shows_yield(worlds) -> None:
    world = worlds[0]
    payload = _rebuilt(world, (LATE, POOR, GOOD))
    late, poor, good = (n["supplier_id"] for n in world["newcomers"])
    ask = [{"action": "inquire", "supplier_id": sid, "fields": ["lead_time", "quality"], "message": "?"} for sid in (late, poor)]
    claims = _observe(payload, ask)["verbal_claims"]
    assert claims[late]["lead_time"]["value"]["on_time_probability"] == reference.GOOD_ON_TIME
    assert claims[poor]["quality"]["value"]["claimed_yield_rate"] == reference.GOOD_YIELD
    seen = _observe(payload, [_quote(late), _quote(poor), _sample(poor), _sample(good)])
    offers = {o["supplier_id"]: o for o in seen["formal_offers"].values()}
    assert offers[late]["on_time_probability"] == reference.LATE_ON_TIME
    assert offers[poor]["on_time_probability"] == reference.GOOD_ON_TIME
    assert seen["verified_samples"][poor]["verified_yield_rate"] == reference.POOR_YIELD
    assert seen["verified_samples"][good]["verified_yield_rate"] == reference.GOOD_YIELD
    assert seen["elapsed_days"] == 2 * pack_module.QUOTE_DAYS + 2 * pack_module.NEWCOMER_SAMPLE_DAYS
    fees = {n["supplier_id"]: n["sample_fee_usd"] for n in world["newcomers"]}
    assert seen["information_cost_usd"] == 2 * pack_module.QUOTE_FEE_USD + fees[poor] + fees[good]


def test_the_order_is_counted_as_the_prompt_says(worlds) -> None:
    world = worlds[0]
    payload = _rebuilt(world, (GOOD, POOR, GOOD))
    good, poor, _ = (n["supplier_id"] for n in world["newcomers"])
    ref = reference.Reference(payload)
    # Kits: quantity times yield times on-time rate, rounded down, capped at the target.
    done = reference.run(payload, [_quote(good), _sample(good), _award(good, 50)])
    outcome = ref.plugin.outcome(ref.case, ref.plugin.terminal(ref.case, done))
    assert outcome["completed_kits"] == int(50 * reference.GOOD_YIELD * reference.GOOD_ON_TIME) == 47
    full = reference.run(payload, [_quote(good), _sample(good), _award(good, 60)])
    assert ref.plugin.outcome(ref.case, ref.plugin.terminal(ref.case, full))["completed_kits"] == pack_module.TARGET_KITS
    # Three kits short costs three penalties and three kits of revenue against the same order completed.
    info = pack_module.QUOTE_FEE_USD + next(n["sample_fee_usd"] for n in world["newcomers"] if n["supplier_id"] == good)
    # Under the minimum the award is void: nothing supplied, information still paid for.
    void = reference.run(payload, [_quote(poor), _sample(poor), _award(poor, 60)])
    spent = pack_module.QUOTE_FEE_USD + next(n["sample_fee_usd"] for n in world["newcomers"] if n["supplier_id"] == poor)
    assert reference.final_margin(ref, void) == pytest.approx(pack_module.NO_SUPPLY_VALUE_USD - spent)
    # Walking away and running out of actions are the same nothing.
    assert reference.final_margin(ref, reference.run(payload, [{"action": "defer", "reason": "no"}])) == pack_module.NO_SUPPLY_VALUE_USD
    stalled = reference.run(payload, [_quote(good)] * pack_module.BUDGET_ACTIONS)
    assert stalled["termination_reason"] == "interaction_budget_exhausted"
    assert reference.final_margin(ref, stalled) == pytest.approx(pack_module.NO_SUPPLY_VALUE_USD - pack_module.BUDGET_ACTIONS * pack_module.QUOTE_FEE_USD)
    # A delivery that would land after the deadline delivers nothing.
    lead = next(s["private_terms"]["lead_time_days"] for s in payload["suppliers"] if s["supplier_id"] == good)
    waits = payload["objective"]["deadline_days"] - lead - pack_module.QUOTE_DAYS - pack_module.NEWCOMER_SAMPLE_DAYS
    on_the_day = [_quote(good), _sample(good)] + [_quote(good)] * waits + [_award(good, 55)]
    assert reference.final_margin(ref, reference.run(payload, on_the_day)) > 0
    one_day_late = [_quote(good), _sample(good)] + [_quote(good)] * (waits + 1) + [_award(good, 55)]
    assert reference.final_margin(ref, reference.run(payload, one_day_late)) < pack_module.NO_SUPPLY_VALUE_USD
    assert info > 0


def test_the_prompt_names_only_things_the_buyer_can_see_and_prescribes_nothing(worlds) -> None:
    observation = _observe(worlds[0]["case"]["payload"])
    for path in ("objective.target_kits", "objective.shortfall_penalty_per_kit_usd", "objective.minimum_service_kits",
                 "objective.defer_value_usd", "objective.deadline_days", "policy.process.quote_fee_usd", "policy.process.quote_days"):
        assert path in PAY_OR_TEST_PROMPT
        node = observation
        for key in path.split("."):
            node = node[key]
    listing = next(row["listing"] for row in observation["supplier_listings"] if "cohort_record" in row["listing"])
    for field in ("sample_fee_usd", "sample_days", "marketplace_record", "cohort_record"):
        assert field in PAY_OR_TEST_PROMPT and field in listing
    assert {"elapsed_days", "actions_left"} <= set(observation)
    lowered = PAY_OR_TEST_PROMPT.lower()
    for word in ("cheapest", "rank", "first test", "start with", "smallest", "always", "never test", "should"):
        assert word not in lowered, word
