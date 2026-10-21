"""Pay or test, version 2: the properties that make the pack a decision a one-step rule cannot solve.

Each test pins one thing the pack promises: that the committed worlds are what
the generator makes; that every admitted world defeats the one-step rule and
every fixed rule by the declared margin, and the pack's mean by the declared
mean; that admission reads nothing a buyer cannot see; that types follow the
law the brief states; that the reference's values are the environment's own
averages over every way the newcomers could turn out; and that every rule the
brief states is true.
"""

from __future__ import annotations

import itertools
import json
import random
import statistics
from collections import Counter

import pytest

from tests import full_regeneration

from aeread_families.procurement_allocation import pay_or_test_reference as v1_reference
from aeread_families.procurement_allocation import pay_or_test_v2_case_matrix as pack_module
from aeread_families.procurement_allocation import pay_or_test_v2_reference as reference
from aeread_families.procurement_allocation.environment import ProcurementAllocationPlugin
from aeread_families.procurement_allocation.pay_or_test_prompt import PAY_OR_TEST_PROMPT_V2
from aeread_families.procurement_allocation.pay_or_test_v2_prompt import PAY_OR_TEST_V2_PROMPT

GOOD, LATE, POOR = v1_reference.GOOD, v1_reference.LATE, v1_reference.POOR
WORLD_COUNT = len(pack_module.CELLS) * pack_module.WORLDS_PER_CELL


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((pack_module.PACK_ROOT / "pack.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def worlds(manifest) -> list[dict]:
    cases = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in pack_module.case_paths()}
    return [{**world, "case": cases[world["slug"]]} for world in manifest["worlds"]]


def _spec(world: dict) -> dict:
    return next(s for s in pack_module.world_specs() if s["slug"] == world["slug"])


def _structure(world: dict) -> dict:
    return pack_module.draw_structure(_spec(world), world["world_seed"])


def _rebuilt(world: dict, types: tuple[str, ...], **changes) -> dict:
    structure = {**_structure(world), **changes}
    return pack_module.build_case(_spec(world), world["world_seed"], structure, types, seal=False)["payload"]


def _observe(payload: dict, actions: list[dict] | None = None) -> dict:
    plugin = ProcurementAllocationPlugin()
    family_case = plugin.validate_payload(payload)
    state = reference.run(payload, actions or [])
    return plugin.observe(family_case, state, "buyer", plugin.phases(family_case)[0])


def _quote(sid: str) -> dict:
    return {"action": "request_quote", "supplier_id": sid, "message": "quote"}


def _sample(sid: str) -> dict:
    return {"action": "request_sample", "supplier_id": sid, "message": "sample"}


def _award(sid: str, quantity: int) -> dict:
    return {"action": "submit_award", "award_lines": [{"offer_id": f"offer_{sid}_v1", "quantity": quantity}]}


# --- the committed pack is what the generator makes -----------------------------


# Regenerating the pack takes minutes, so the check is split by world and spread across workers:
# each world is the first admitted seed of its block and is rebuilt byte for byte, and the
# manifest is rebuilt from those worlds.
@pytest.mark.parametrize("index", full_regeneration.indices(WORLD_COUNT))
def test_each_world_is_the_first_admitted_seed_of_its_block_reproduced_byte_for_byte(manifest, index) -> None:
    spec = pack_module.world_specs()[index]
    entry = manifest["worlds"][index]
    assert entry["slug"] == spec["slug"]
    assert entry["seeds_scanned"] == entry["world_seed"] - spec["seed_block"] + 1
    for seed in full_regeneration.seeds(spec["seed_block"], entry["world_seed"]):
        admitted, _ = pack_module.admit(spec, seed, pack_module.draw_structure(spec, seed))
        assert not admitted, (spec["slug"], seed)
    case, rebuilt = pack_module.world_at(spec, entry["world_seed"], entry["seeds_scanned"])
    assert rebuilt == entry
    path = pack_module.PACK_ROOT / f"{spec['slug']}.json"
    assert path.read_text(encoding="utf-8") == json.dumps(case, indent=2, sort_keys=True) + "\n"


def test_the_manifest_is_rebuilt_from_its_worlds_byte_for_byte(manifest, worlds) -> None:
    pack = pack_module.build_pack([(w["case"], {k: v for k, v in w.items() if k != "case"}) for w in worlds])
    committed = (pack_module.PACK_ROOT / "pack.json").read_text(encoding="utf-8")
    assert committed == json.dumps(pack["manifest"], indent=2, sort_keys=True) + "\n"
    assert [p.stem for p in pack_module.case_paths()] == sorted(w["slug"] for w in worlds)
    assert len(worlds) == WORLD_COUNT


PILOT = pack_module.PILOT_PACK_ID


@pytest.mark.parametrize("index", full_regeneration.indices(len(pack_module.CELLS) * pack_module.SPLITS[PILOT]["worlds_per_cell"]))
def test_each_pilot_world_is_the_first_admitted_seed_of_its_block_reproduced_byte_for_byte(index) -> None:
    """The pilot split is the same generator and admission on its own seed range, under its own pack id."""
    manifest = json.loads((pack_module.pack_root(PILOT) / "pack.json").read_text(encoding="utf-8"))
    spec = pack_module.world_specs(PILOT)[index]
    entry = manifest["worlds"][index]
    assert entry["slug"] == spec["slug"] and entry["case_id"] == f"procurement_allocation_v1.{PILOT}.{spec['slug']}"
    for seed in full_regeneration.seeds(spec["seed_block"], entry["world_seed"]):
        admitted, _ = pack_module.admit(spec, seed, pack_module.draw_structure(spec, seed))
        assert not admitted, (spec["slug"], seed)
    case, rebuilt = pack_module.world_at(spec, entry["world_seed"], entry["seeds_scanned"])
    assert rebuilt == entry and case["split"] == PILOT
    path = pack_module.pack_root(PILOT) / f"{spec['slug']}.json"
    assert path.read_text(encoding="utf-8") == json.dumps(case, indent=2, sort_keys=True) + "\n"


def test_the_pilot_manifest_is_rebuilt_from_its_worlds_byte_for_byte() -> None:
    root = pack_module.pack_root(PILOT)
    manifest = json.loads((root / "pack.json").read_text(encoding="utf-8"))
    cases = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in pack_module.case_paths(split=PILOT)}
    pack = pack_module.build_pack([(cases[w["slug"]], w) for w in manifest["worlds"]], split=PILOT)
    assert (root / "pack.json").read_text(encoding="utf-8") == json.dumps(pack["manifest"], indent=2, sort_keys=True) + "\n"
    assert manifest["pack_id"] == PILOT and manifest["world_count"] == 12
    assert manifest["controls"]["seed_start"] == 9_100_000 and manifest["controls"]["worlds_per_cell"] == 3


def test_cells_are_balanced_by_kind_and_clock(worlds) -> None:
    assert Counter((w["kind"], w["clock"]) for w in worlds) == Counter({cell: pack_module.WORLDS_PER_CELL for cell in pack_module.CELLS})
    for world in worlds:
        assert world["kind"] == pack_module.classify(world["case"]["payload"], full_information=False)["kind"], world["slug"]


def test_the_clock_fits_the_number_of_tests_its_name_says(worlds) -> None:
    one_test = pack_module.QUOTE_DAYS + pack_module.NEWCOMER_SAMPLE_DAYS
    fall_back = pack_module.QUOTE_DAYS + pack_module.ESTABLISHED_SAMPLE[1] + pack_module.ESTABLISHED_LEAD_DAYS
    for world in worlds:
        assert (world["deadline_days"] - fall_back) // one_test == pack_module.CLOCK_TESTS[world["clock"]], world["slug"]


def test_the_pack_does_not_overlap_version_one_seeds(worlds) -> None:
    from aeread_families.procurement_allocation import pay_or_test_case_matrix as v1

    v1_low = v1.SEED_START - v1.NATURAL_MIX_SEEDS
    v1_high = v1.SEED_START + len(v1.world_specs()) * v1.SEEDS_PER_WORLD
    for world in worlds:
        assert not v1_low <= world["world_seed"] < v1_high, world["slug"]


# --- admission: every world defeats every rule it is screened against -----------


def test_every_world_defeats_the_one_step_rules_and_every_fixed_rule_by_the_margin(worlds) -> None:
    for world in worlds:
        for name in pack_module.ADMISSION_RULES:
            assert world["rule_loss_usd"][name] >= pack_module.MARGIN_USD, (world["slug"], name)


def test_the_one_step_rule_loses_the_declared_mean_and_the_manifest_says_so(manifest, worlds) -> None:
    mean = statistics.fmean(w["rule_loss_usd"]["one_step_value"] for w in worlds)
    assert mean >= pack_module.MEAN_MARGIN_USD
    assert manifest["expected_loss_usd_by_rule"]["one_step_value"] == round(mean, 2)


def test_information_has_headroom_in_every_world(worlds) -> None:
    for world in worlds:
        headroom = world["expected_full_information_value_usd"] - world["best_policy_value_usd"]
        assert headroom >= pack_module.INFORMATION_HEADROOM_USD, world["slug"]


def test_without_a_shared_source_the_one_step_rule_is_close_to_the_best_policy(worlds) -> None:
    """The counterfactual that attributes the shortfall: the same listings, a source never shared."""
    for world in worlds:
        ref = reference.Reference(_rebuilt(world, (GOOD,) * 3, same_source_probability=0.0))
        start = ref.start()
        gap = ref.value(*start) - ref.rule_value("one_step_value", reference.one_step_value, *start)
        assert gap < pack_module.ATTRIBUTION_USD, world["slug"]
        assert round(gap, 2) == world["one_step_loss_without_shared_source_usd"], world["slug"]


def test_admission_does_not_depend_on_how_the_newcomers_turned_out(worlds) -> None:
    profiles = list(itertools.product((GOOD, LATE, POOR), repeat=3))
    for world in worlds:
        seen = pack_module.classify(world["case"]["payload"], full_information=False)
        for types in random.Random(world["world_seed"]).sample(profiles, 4):
            assert pack_module.classify(_rebuilt(world, types), full_information=False) == seen, world["slug"]


def test_a_listing_is_the_same_whatever_type_its_seller_is(worlds) -> None:
    for world in worlds[:: pack_module.WORLDS_PER_CELL]:
        listings = set()
        for types in ((GOOD, GOOD, GOOD), (LATE, LATE, LATE), (POOR, POOR, POOR), (LATE, POOR, GOOD)):
            observation = _observe(_rebuilt(world, types))
            listings.add(json.dumps([observation["supplier_listings"], observation["policy"]], sort_keys=True))
        assert len(listings) == 1, world["slug"]


def test_the_pack_records_types_that_match_its_cases(worlds) -> None:
    for world in worlds:
        terms = {s["supplier_id"]: s["private_terms"] for s in world["case"]["payload"]["suppliers"]}
        for newcomer in world["newcomers"]:
            mine = terms[newcomer["supplier_id"]]
            kind = (LATE if mine["on_time_probability"] < v1_reference.BAD_BELOW
                    else POOR if mine["quality"]["verified_yield_rate"] < v1_reference.BAD_BELOW else GOOD)
            assert kind == newcomer["type"], world["slug"]


# --- types follow the law the brief states ---------------------------------------


def _shares(newcomer: dict) -> dict[str, float]:
    late, poor = newcomer["late"] / pack_module.COHORT_TRACKED, newcomer["failed"] / pack_module.COHORT_TRACKED
    return {GOOD: 1.0 - late - poor, LATE: late, POOR: poor}


def test_types_follow_the_stated_shares_and_the_stated_chance_of_a_shared_source() -> None:
    spec = pack_module.world_specs()[0]
    drawn, expected = Counter(), Counter()
    same_kind = same_kind_expected = other_kind = other_kind_expected = 0.0
    same_kind_pairs = other_kind_pairs = 0
    for seed in range(7_000_000, 7_004_000):
        structure = pack_module.draw_structure(spec, seed)
        types = pack_module.draw_types(structure, seed)
        rho = structure["same_source_probability"]
        for newcomer, kind_of in zip(structure["newcomers"], types):
            drawn[kind_of] += 1
            for t, share in _shares(newcomer).items():
                expected[t] += share
        for (a, ta), (b, tb) in itertools.combinations(zip(structure["newcomers"], types), 2):
            shares_a, shares_b = _shares(a), _shares(b)
            independent = sum(shares_a[t] * shares_b[t] for t in shares_a)
            if a["kind"] == b["kind"]:
                same_kind_pairs += 1
                same_kind += ta == tb
                same_kind_expected += rho + (1.0 - rho) * independent
            else:
                other_kind_pairs += 1
                other_kind += ta == tb
                other_kind_expected += independent
    for t in (GOOD, LATE, POOR):
        assert abs(drawn[t] - expected[t]) < 4 * expected[t] ** 0.5, (t, drawn[t], expected[t])
    assert abs(same_kind - same_kind_expected) < 4 * same_kind_expected ** 0.5, (same_kind, same_kind_expected)
    assert abs(other_kind - other_kind_expected) < 4 * other_kind_expected ** 0.5, (other_kind, other_kind_expected)
    assert same_kind_pairs > 1000 and other_kind_pairs > 1000


def test_the_reference_prior_is_the_stated_law_exactly(worlds) -> None:
    for world in worlds:
        ref = reference.Reference(world["case"]["payload"])
        structure = _structure(world)
        order = [ref.ids[i] for i in ref.newcomers]
        position = {f"{pack_module.COMPONENT}_l{code}": k for k, code in enumerate(structure["codes"][1:])}
        rho = structure["same_source_probability"]
        prior = dict(ref.joint_prior())
        assert sum(prior.values()) == pytest.approx(1.0, abs=1e-12)
        for types in itertools.product((GOOD, LATE, POOR), repeat=3):
            by_position = {position[sid]: t for sid, t in zip(order, types)}
            stated = 1.0
            for members in pack_module.groups_of(structure):
                shares = _shares(structure["newcomers"][members[0]])
                independent = 1.0
                for i in members:
                    independent *= shares[by_position[i]]
                if len(members) == 1:
                    stated *= independent
                else:
                    shared = shares[by_position[members[0]]] if len({by_position[i] for i in members}) == 1 else 0.0
                    stated *= rho * shared + (1.0 - rho) * independent
            assert prior.get(types, 0.0) == pytest.approx(stated, abs=1e-12), (world["slug"], types)


# --- the reference's numbers are the environment's ------------------------------


@pytest.mark.parametrize("index", range(WORLD_COUNT))
def test_expected_values_equal_the_environments_average_over_every_way_the_newcomers_could_turn_out(worlds, index) -> None:
    world = worlds[index]
    ref = reference.Reference(world["case"]["payload"])
    order = [ref.ids[i] for i in ref.newcomers]
    position = {n["supplier_id"]: k for k, n in enumerate(world["newcomers"])}
    totals = {name: 0.0 for name in ("best_policy", *reference.RULES)}
    for types, weight in ref.joint_prior():
        drawn = [None] * 3
        for sid, t in zip(order, types):
            drawn[position[sid]] = t
        payload = _rebuilt(world, tuple(drawn))
        probe = reference.Reference(payload)
        for name in totals:
            actions = reference.play(payload, None if name == "best_policy" else reference.RULES[name])
            totals[name] += weight * reference.final_margin(probe, reference.run(payload, actions))
    start = ref.start()
    assert totals["best_policy"] == pytest.approx(ref.value(*start), abs=1e-6)
    assert totals["best_policy"] == pytest.approx(world["best_policy_value_usd"], abs=0.006)
    for name, rule in reference.RULES.items():
        assert totals[name] == pytest.approx(ref.rule_value(name, rule, *start), abs=1e-6), name
        assert totals[name] <= totals["best_policy"] + 1e-6, name
        assert totals["best_policy"] - totals[name] == pytest.approx(world["rule_loss_usd"][name], abs=0.011), name


def test_the_best_policy_gives_nothing_up_on_the_world_as_drawn(worlds) -> None:
    for world in worlds:
        assert world["realized"]["best_policy"]["decision_loss_usd"] == 0.0, world["slug"]


def test_a_trajectory_is_priced_action_by_action(worlds) -> None:
    world = next(w for w in worlds if w["kind"] == "myopic_pays")
    payload = world["case"]["payload"]
    established = world["established"]["supplier_id"]
    actions = [{"action": "inquire", "supplier_id": established, "fields": ["quality"], "message": "?"},
               *reference.play(payload, reference.pay_premium)]
    scored = reference.score_actions(payload, actions)
    assert scored["decision_loss_usd"] == pytest.approx(world["rule_loss_usd"]["pay_premium"] + pack_module.INQUIRY_FEE_USD, abs=0.02)
    # The inquiry costs its fee and a day; the day can cost a probe the time it needed, so the stray is priced
    # at what it took from the best policy, never less than the fee.
    ref = reference.Reference(payload)
    after = ref.value(ref.start()[0], pack_module.BUDGET_ACTIONS - 1, 1) - pack_module.INQUIRY_FEE_USD
    assert scored["loss_by_part_usd"]["strays"] == pytest.approx(world["best_policy_value_usd"] - after, abs=0.01)
    assert scored["loss_by_part_usd"]["strays"] >= pack_module.INQUIRY_FEE_USD - 1e-9
    broken = reference.score_actions(payload, [{"action": "request_quote", "supplier_id": "nobody", "message": "x"}])
    assert broken["steps"][0]["valid"] is False
    assert broken["outcome"]["contribution_margin_usd"] == pack_module.NO_SUPPLY_VALUE_USD


def test_the_one_step_rule_follows_the_posterior_after_a_result(worlds) -> None:
    """A newcomer's result moves the odds of the others of its kind, as the stated law says it should."""
    for world in worlds:
        ref = reference.Reference(world["case"]["payload"])
        rho = world["same_source_probability"]
        for members in ref.groups:
            if len(members) < 2:
                continue
            a, b = members[:2]
            good, late, poor = ref.prior[b]
            status = list(ref.start()[0])
            status[a] = v1_reference.QUALIFIED
            assert ref.type_odds(tuple(status), b)[0] > good
            status[a] = reference.SHOWN_POOR
            after_poor = ref.type_odds(tuple(status), b)
            assert after_poor[2] > poor and after_poor[0] < good
            if len(members) == 2:
                assert after_poor[2] == pytest.approx(rho + (1.0 - rho) * poor)
                status[a] = v1_reference.QUALIFIED
                assert ref.type_odds(tuple(status), b)[0] == pytest.approx(rho + (1.0 - rho) * good)


# --- what the buyer is shown is true, and what the prompt states is true -----------


def test_a_listing_states_the_price_lead_time_and_sample_terms_the_supplier_holds(worlds) -> None:
    for world in worlds:
        payload = world["case"]["payload"]
        assert "sample_noise" not in payload["interaction"], "noisy samples make the pre-award check an oracle (P-D-17)"
        process, interaction = payload["policy"]["process"], payload["interaction"]
        assert (process["quote_fee_usd"], process["quote_days"]) == (interaction["quote_cost_usd"], interaction["quote_days"])
        assert (process["inquiry_fee_usd"], process["counter_fee_usd"]) == (interaction["inquiry_cost_usd"], interaction["counter_cost_usd"])
        assert payload["policy"][reference.SOURCING_FIELD]["same_source_probability"] == world["same_source_probability"]
        for supplier in payload["suppliers"]:
            listing, terms = supplier["listing"], supplier["private_terms"]
            assert listing["displayed_unit_price_usd"] == terms["base_unit_price_usd"]
            assert listing["claimed_lead_time_days"] == terms["lead_time_days"]
            assert (listing["sample_fee_usd"], listing["sample_days"]) == (
                terms["quality"]["sample_cost_usd"], terms["quality"]["sample_lead_time_days"])
            assert ("cohort_record" in listing) == (listing["marketplace_record"]["orders_reported"] == 0)
        kinds = Counter(s["listing"]["seller_kind"] for s in payload["suppliers"] if "cohort_record" in s["listing"])
        assert max(kinds.values()) >= 2, "a world without two newcomers of one kind has no shared source to learn from"


def test_only_a_quote_shows_lateness_and_only_a_sample_shows_yield(worlds) -> None:
    world = worlds[0]
    payload = _rebuilt(world, (LATE, POOR, GOOD))
    late, poor, good = (n["supplier_id"] for n in world["newcomers"])
    ask = [{"action": "inquire", "supplier_id": sid, "fields": ["lead_time", "quality"], "message": "?"} for sid in (late, poor)]
    claims = _observe(payload, ask)["verbal_claims"]
    assert claims[late]["lead_time"]["value"]["on_time_probability"] == v1_reference.GOOD_ON_TIME
    assert claims[poor]["quality"]["value"]["claimed_yield_rate"] == v1_reference.GOOD_YIELD
    seen = _observe(payload, [_quote(late), _quote(poor), _sample(poor), _sample(good)])
    offers = {o["supplier_id"]: o for o in seen["formal_offers"].values()}
    assert offers[late]["on_time_probability"] == v1_reference.LATE_ON_TIME
    assert offers[poor]["on_time_probability"] == v1_reference.GOOD_ON_TIME
    assert seen["verified_samples"][poor]["verified_yield_rate"] == v1_reference.POOR_YIELD
    assert seen["verified_samples"][good]["verified_yield_rate"] == v1_reference.GOOD_YIELD
    assert seen["elapsed_days"] == 2 * pack_module.QUOTE_DAYS + 2 * pack_module.NEWCOMER_SAMPLE_DAYS
    fees = {n["supplier_id"]: n["sample_fee_usd"] for n in world["newcomers"]}
    assert seen["information_cost_usd"] == 2 * pack_module.QUOTE_FEE_USD + fees[poor] + fees[good]


def test_the_order_is_counted_as_the_prompt_says(worlds) -> None:
    world = worlds[0]
    payload = _rebuilt(world, (GOOD, POOR, GOOD))
    good, poor, _ = (n["supplier_id"] for n in world["newcomers"])
    ref = reference.Reference(payload)
    done = reference.run(payload, [_quote(good), _sample(good), _award(good, 50)])
    outcome = ref.plugin.outcome(ref.case, ref.plugin.terminal(ref.case, done))
    assert outcome["completed_kits"] == int(50 * v1_reference.GOOD_YIELD * v1_reference.GOOD_ON_TIME) == 47
    full = reference.run(payload, [_quote(good), _sample(good), _award(good, 60)])
    assert ref.plugin.outcome(ref.case, ref.plugin.terminal(ref.case, full))["completed_kits"] == pack_module.TARGET_KITS
    void = reference.run(payload, [_quote(poor), _sample(poor), _award(poor, 60)])
    spent = pack_module.QUOTE_FEE_USD + next(n["sample_fee_usd"] for n in world["newcomers"] if n["supplier_id"] == poor)
    assert reference.final_margin(ref, void) == pytest.approx(pack_module.NO_SUPPLY_VALUE_USD - spent)
    assert reference.final_margin(ref, reference.run(payload, [{"action": "defer", "reason": "no"}])) == pack_module.NO_SUPPLY_VALUE_USD
    stalled = reference.run(payload, [_quote(good)] * pack_module.BUDGET_ACTIONS)
    assert stalled["termination_reason"] == "interaction_budget_exhausted"
    assert reference.final_margin(ref, stalled) == pytest.approx(pack_module.NO_SUPPLY_VALUE_USD - pack_module.BUDGET_ACTIONS * pack_module.QUOTE_FEE_USD)
    lead = next(s["private_terms"]["lead_time_days"] for s in payload["suppliers"] if s["supplier_id"] == good)
    waits = payload["objective"]["deadline_days"] - lead - pack_module.QUOTE_DAYS - pack_module.NEWCOMER_SAMPLE_DAYS
    on_the_day = [_quote(good), _sample(good)] + [_quote(good)] * waits + [_award(good, 55)]
    assert reference.final_margin(ref, reference.run(payload, on_the_day)) > 0
    one_day_late = [_quote(good), _sample(good)] + [_quote(good)] * (waits + 1) + [_award(good, 55)]
    assert reference.final_margin(ref, reference.run(payload, one_day_late)) < pack_module.NO_SUPPLY_VALUE_USD


def test_a_quote_is_final_as_the_prompt_says(worlds) -> None:
    world = worlds[0]
    payload = world["case"]["payload"]
    sid = world["established"]["supplier_id"]
    offer = next(iter(_observe(payload, [_quote(sid)])["formal_offers"].values()))
    for proposal in ({"unit_price_usd": round(offer["unit_price_usd"] - 0.01, 2)}, {"moq": offer["moq"] - 5},
                     {"payment_terms_days": offer["payment_terms_days"] + 15}):
        counter = {"action": "counter_offer", "supplier_id": sid, "offer_id": offer["offer_id"], "proposal": proposal, "message": "?"}
        after = _observe(payload, [_quote(sid), counter])
        assert list(after["formal_offers"]) == [offer["offer_id"]], proposal
        assert after["elapsed_days"] == pack_module.QUOTE_DAYS + 1
        assert after["information_cost_usd"] == pack_module.QUOTE_FEE_USD + pack_module.COUNTER_FEE_USD


def test_the_prompt_is_brief_two_plus_the_shared_source_and_prescribes_nothing(worlds) -> None:
    added = [line for line in PAY_OR_TEST_V2_PROMPT.splitlines() if line not in PAY_OR_TEST_PROMPT_V2.splitlines()]
    assert all(line in PAY_OR_TEST_V2_PROMPT.splitlines() for line in PAY_OR_TEST_PROMPT_V2.splitlines())
    assert len(added) == 7 and added[0].startswith("- New listings of the same seller_kind")
    observation = _observe(worlds[0]["case"]["payload"])
    assert "policy.newcomer_sourcing.same_source_probability" in PAY_OR_TEST_V2_PROMPT
    assert observation["policy"]["newcomer_sourcing"]["same_source_probability"] == worlds[0]["same_source_probability"]
    assert all("seller_kind" in row["listing"] for row in observation["supplier_listings"])
    lowered = "\n".join(added).lower()
    for word in ("cheapest", "rank", "first", "start with", "probe", "always", "never test", "should", "worth"):
        assert word not in lowered, word
