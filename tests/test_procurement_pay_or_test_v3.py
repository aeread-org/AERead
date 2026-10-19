"""Pay or test, version 3: what the environment, the reference, the generator and the brief each promise.

The environment: an unanswered quote costs its fee and day and shows nothing; replies are a pure function of the case;
the recorded supplier always answers; a lookup names the registered factory; inquiry and counters are gone; the buyer
does not see the reply seed or terms that never bind; the leaf binds this module's bytes. The reference: its values
are the environment's own averages under the stated law; with every quote answered and no shared source it is
version 2's; a lookup settles a kind's sharing. The generator: prices come from the 56 record pairs; sharing, types
and factories agree. The pilot pack: each world is the first admitted seed of its block, reproduced byte for byte,
and passes every admission rule. The brief: every rule it states is the environment's.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter

import pytest

from aeread.shared_runner.task.scheduler import ActionEnvelope
from aeread_families.procurement_allocation import environment as v1_environment
from aeread_families.procurement_allocation import pay_or_test_v2_reference as v2_reference
from aeread_families.procurement_allocation import pay_or_test_v3_case_matrix as pack_module
from aeread_families.procurement_allocation import pay_or_test_v3_environment as environment
from aeread_families.procurement_allocation import pay_or_test_v3_reference as reference
from aeread_families.procurement_allocation.pay_or_test_reference import GOOD, LATE, POOR, QUALIFIED, final_margin
from aeread_families.procurement_allocation.pay_or_test_v3_prompt import PAY_OR_TEST_V3_PROMPT

SPEC = {"slug": "test", "kind": "myopic_tests", "pack_id": pack_module.PILOT_PACK_ID}
#: A world with all three newcomers of one kind, the source shared with probability 0.65.
THREE_OF_A_KIND = 9_300_001


def _world(seed: int = THREE_OF_A_KIND, **changes) -> tuple[dict, dict]:
    structure = {**pack_module.draw_structure(SPEC, seed), **changes}
    drawn = pack_module.draw_types(structure, seed)
    return structure, pack_module.build_case(SPEC, seed, structure, drawn)["payload"]


def _step(plugin, family_case, state, action):
    parsed = plugin.parse_action(family_case, state, "buyer", None, action)
    if not parsed.ok:
        envelope = ActionEnvelope(seat_id="buyer", valid=False, action=None, parse=parsed, legality=None)
    else:
        legality = plugin.legal(family_case, state, "buyer", None, parsed.action)
        envelope = ActionEnvelope(seat_id="buyer", valid=legality.legal, action=parsed.action, parse=parsed,
                                  legality=legality)
    return plugin.step(family_case, state, None, {"buyer": envelope}).state


def _ids(family_case: dict) -> tuple[str, list[str]]:
    recorded = [s["supplier_id"] for s in family_case["suppliers"] if s["listing"]["marketplace_record"]["orders_reported"]]
    newcomers = [s["supplier_id"] for s in family_case["suppliers"] if not s["listing"]["marketplace_record"]["orders_reported"]]
    return recorded[0], newcomers


# --- the environment -----------------------------------------------------------------------


def test_an_unanswered_quote_costs_its_fee_and_day_and_shows_nothing() -> None:
    _, payload = _world()
    plugin = environment.PayOrTestV3Plugin()
    case = plugin.validate_payload(payload)
    _, newcomers = _ids(case)
    seed, p = case["interaction"]["reply_seed"], case["policy"]["newcomer_quote_answer_probability"]
    target = next(n for n in newcomers if not environment.quote_answered(seed, n, 0, p))
    state = _step(plugin, case, plugin.initial_state(case, None),
                  {"action": "request_quote", "supplier_id": target, "message": "Please quote."})
    assert state["offers"] == {} and target not in state["latest_offer_by_supplier"]
    assert state["elapsed_days"] == case["interaction"]["quote_days"]
    assert state["information_cost_usd"] == case["interaction"]["quote_cost_usd"]
    assert state["actions_used"] == 1 and not state["done"]
    assert state["unanswered_quotes"] == {target: 1}
    assert plugin.observe(case, state, "buyer", None)["unanswered_quote_requests"] == {target: 1}


def test_replies_are_a_pure_function_of_the_case_and_answer_at_the_stated_rate() -> None:
    _, payload = _world()
    plugin = environment.PayOrTestV3Plugin()
    case = plugin.validate_payload(payload)
    _, newcomers = _ids(case)
    actions = [{"action": "request_quote", "supplier_id": newcomers[k % 3], "message": "Quote?"} for k in range(9)]

    def play():
        state = plugin.initial_state(case, None)
        for action in actions:
            state = _step(plugin, case, state, action)
        return state

    assert play() == play()
    answered = sum(environment.quote_answered(11, f"s{i}", k, 1 / 3) for i in range(400) for k in range(10))
    assert abs(answered / 4000 - 1 / 3) < 0.03


def test_the_recorded_supplier_always_answers() -> None:
    _, payload = _world()
    plugin = environment.PayOrTestV3Plugin()
    case = plugin.validate_payload(payload)
    recorded, _ = _ids(case)
    state = plugin.initial_state(case, None)
    for _ in range(3):
        state = _step(plugin, case, state, {"action": "request_quote", "supplier_id": recorded, "message": "Quote?"})
        assert recorded in state["latest_offer_by_supplier"]
    assert state["unanswered_quotes"] == {}


def test_a_lookup_names_the_registered_factory_and_shared_newcomers_name_the_same_one() -> None:
    seed = THREE_OF_A_KIND
    structure = pack_module.draw_structure(SPEC, seed)
    for k in range(40):
        drawn = pack_module.draw_types(structure, seed + 1000 * k)
        payload = pack_module.build_case(SPEC, seed, structure, drawn)["payload"]
        plugin = environment.PayOrTestV3Plugin()
        case = plugin.validate_payload(payload)
        _, newcomers = _ids(case)
        state = plugin.initial_state(case, None)
        for n in newcomers:
            state = _step(plugin, case, state, {"action": "look_up_source", "supplier_id": n})
        named = {state["source_records"][n]["source_factory"] for n in newcomers}
        assert (len(named) == 1) == drawn["shared_by_group"][0]
        assert state["information_cost_usd"] == pytest.approx(3 * case["interaction"]["source_lookup_cost_usd"])
        assert state["elapsed_days"] == 3 * case["interaction"]["source_lookup_days"]


def test_an_award_check_costs_nothing_and_takes_no_days_but_uses_an_action() -> None:
    _, payload = _world()
    plugin = environment.PayOrTestV3Plugin()
    case = plugin.validate_payload(payload)
    recorded, _ = _ids(case)
    state = _step(plugin, case, plugin.initial_state(case, None),
                  {"action": "request_quote", "supplier_id": recorded, "message": "Quote?"})
    offer = state["latest_offer_by_supplier"][recorded]
    before = (state["elapsed_days"], state["information_cost_usd"], state["actions_used"])
    state = _step(plugin, case, state, {"action": "check_award", "award_lines": [{"offer_id": offer, "quantity": 55}]})
    assert (state["elapsed_days"], state["information_cost_usd"], state["actions_used"]) == (before[0], before[1], before[2] + 1)
    assert state["award_checks"] and not state["done"]


@pytest.mark.parametrize("action", [
    {"action": "inquire", "supplier_id": "x", "fields": ["quality"], "message": "Yield?"},
    {"action": "counter_offer", "supplier_id": "x", "offer_id": "o", "proposal": {"unit_price_usd": 1.0}, "message": "?"},
])
def test_inquiry_and_counter_offers_are_not_actions(action) -> None:
    _, payload = _world()
    plugin = environment.PayOrTestV3Plugin()
    case = plugin.validate_payload(payload)
    parsed = plugin.parse_action(case, plugin.initial_state(case, None), "buyer", None, action)
    assert not parsed.ok and parsed.error_code == "unknown_procurement_action"
    state = _step(plugin, case, plugin.initial_state(case, None), action)
    assert state["done"] and state["termination_reason"] == "invalid_action"


def test_the_buyer_does_not_see_the_reply_seed_or_terms_that_never_bind() -> None:
    _, payload = _world()
    plugin = environment.PayOrTestV3Plugin()
    case = plugin.validate_payload(payload)
    observed = plugin.observe(case, plugin.initial_state(case, None), "buyer", None)
    text = json.dumps(observed)
    assert "reply_seed" not in text and str(case["interaction"]["reply_seed"]) not in text
    assert not {"cash_budget_usd", "annual_financing_rate", "working_capital_horizon_days"} & set(observed["objective"])
    assert "inquiry_fields" not in observed["policy"] and "counter_fee_usd" not in observed["policy"]["process"]
    assert "source_factory" not in text and "verbal_claims" not in observed
    assert observed["policy"]["newcomer_quote_answer_probability"] == pytest.approx(1 / 3, abs=1e-6)


def test_validation_refuses_the_terms_of_actions_version_three_does_not_offer() -> None:
    _, payload = _world()
    for field, where in (("inquiry_days", "interaction"), ("counter_cost_usd", "interaction"), ("inquiry_fields", "policy")):
        broken = json.loads(json.dumps(payload))
        broken[where][field] = 1
        with pytest.raises(ValueError):
            environment.validate_v3_payload(broken)


def test_the_leaf_binds_this_module_and_version_one_and_the_schema_matches_the_actions() -> None:
    _, payload = _world()
    case = environment.validate_v3_payload(payload)
    leaf = environment.measurement_leaf(case)
    assert leaf.scorer.implementation_id == environment.SCORER_ID and leaf.scorer.content_sha256 == environment.source_digest()
    assert leaf.scorer.content_sha256 != v1_environment.procurement_allocation_measurement_leaf(case).scorer.content_sha256
    schema = environment.action_output_schema()
    assert set(schema["properties"]["action"]["enum"]) == environment.ACTION_TYPES
    assert environment.family_manifest().family.version == environment.FAMILY_VERSION != v1_environment.FAMILY_VERSION


# --- the reference ---------------------------------------------------------------------------


def test_values_are_the_environments_own_averages_under_the_stated_law() -> None:
    """The best policy's and the one-step rule's values against their play through the environment, 600 draws."""
    seed = THREE_OF_A_KIND
    structure = pack_module.draw_structure(SPEC, seed)
    ref = reference.Reference(pack_module._blind(SPEC, seed, structure))
    start = ref.start()
    for rule_name in (None, "one_step_value"):
        target = ref.value(*start) if rule_name is None else ref.rule_value(rule_name, reference.RULES[rule_name], *start)
        margins = []
        for k in range(600):
            drawn = pack_module.draw_types(structure, seed * 1000 + k)
            sample = {**structure, "reply_seed": 1 + (seed * 7919 + k * 104729) % (2**31 - 2)}
            ref.case = environment.validate_v3_payload(pack_module.build_case(SPEC, seed, sample, drawn, seal=False)["payload"])
            state = ref.plugin.initial_state(ref.case, None)
            while not state["done"]:
                seen = ref.status_of(state)
                left, day = ref.max_actions - state["actions_used"], state["elapsed_days"]
                rule = reference.RULES[rule_name] if rule_name else None
                choice = ref.best_action(seen, left, day) if rule is None else rule(ref, seen, left, day)
                if choice[0] == "submit_award" and seen[choice[1]] != QUALIFIED:
                    choice = ("defer",)
                state = _step(ref.plugin, ref.case, state, ref.wire(choice, state))
            margins.append(final_margin(ref, state))
        se = statistics.stdev(margins) / len(margins) ** 0.5
        assert abs(statistics.fmean(margins) - target) < 4 * se + 1e-6


def test_with_every_quote_answered_and_no_shared_source_version_three_is_version_two() -> None:
    for seed in (THREE_OF_A_KIND, 9_300_003, 9_300_005):
        structure = pack_module.draw_structure(SPEC, seed)
        payload = pack_module._blind(SPEC, seed, structure, rho=0.0)
        payload["policy"]["newcomer_quote_answer_probability"] = 1.0
        v3 = reference.Reference(payload)
        v2 = v2_reference.Reference(environment.version1_view(payload))
        assert v3.value(*v3.start()) == pytest.approx(v2.value(*v2.start()), abs=1e-9)
        assert not any(kind == reference.LOOKUP for kind, _ in v3.requests(v3.start()[0]))


def test_a_lookup_settles_whether_a_kind_shares_a_source_and_moves_the_posterior() -> None:
    structure = pack_module.draw_structure(SPEC, THREE_OF_A_KIND)
    ref = reference.Reference(pack_module._blind(SPEC, THREE_OF_A_KIND, structure))
    seen = ref.start()[0]
    a, b, c = ref.groups[0]
    assert ref.shared_odds(seen, 0) == pytest.approx(ref.rho)
    (p, once), = ref.outcomes(seen, reference.LOOKUP, a)
    assert p == 1.0 and once.looked == {a} and once.sharing[0] == reference.UNKNOWN
    outcomes = dict((s.sharing[0], (q, s)) for q, s in ref.outcomes(once, reference.LOOKUP, b))
    assert outcomes[reference.SHARED][0] == pytest.approx(ref.rho)
    shown_poor = outcomes[reference.SHARED][1].with_state(a, v2_reference.SHOWN_POOR)
    assert ref.type_odds(shown_poor, c) == pytest.approx((0.0, 0.0, 1.0))
    separate = outcomes[reference.SEPARATE][1].with_state(a, v2_reference.SHOWN_POOR)
    assert ref.type_odds(separate, c) == pytest.approx(ref.prior[c])
    assert not ref.lookup_informs(outcomes[reference.SHARED][1], c)


def test_the_one_step_rule_plans_one_newcomer_and_never_looks_up() -> None:
    for seed in (THREE_OF_A_KIND, 9_300_003, 9_300_045):
        structure = pack_module.draw_structure(SPEC, seed)
        ref = reference.Reference(pack_module._blind(SPEC, seed, structure))
        start = ref.start()
        best = ref.value(*start)
        for i in ref.newcomers:
            assert ref.restricted_value(*start, frozenset({i})) <= best + 1e-9
        assert ref.rule_value("one_step_value", reference.RULES["one_step_value"], *start) <= best + 1e-9
        for actions in (reference.play(pack_module._blind(SPEC, seed, structure), reference.RULES["one_step_value"]),):
            assert all(a["action"] != reference.LOOKUP for a in actions)


# --- the generator --------------------------------------------------------------------------


def test_prices_come_from_the_record_pairs() -> None:
    pairs = pack_module.RECORD_DISCOUNTS
    assert len(pairs) == 56 and list(pairs) == sorted(pairs)
    assert statistics.median(pairs) == pytest.approx(-0.0077, abs=1e-4)
    assert sum(d > 0 for d in pairs) == 27 and min(pairs) > -2.0 and max(pairs) < 0.7
    seen = Counter()
    for seed in range(9_300_000, 9_300_300):
        for n in pack_module.draw_structure(SPEC, seed)["newcomers"]:
            seen[n["discount"]] += 1
    assert set(seen) <= set(pairs) and len(seen) > 30


def test_sharing_types_and_factories_follow_the_stated_law() -> None:
    structure = {**pack_module.draw_structure(SPEC, THREE_OF_A_KIND)}
    rho = structure["same_source_probability"]
    shared = 0
    all_alike_when_separate = 0
    n = 4000
    for k in range(n):
        drawn = pack_module.draw_types(structure, 77 + k)
        if drawn["shared_by_group"][0]:
            shared += 1
            assert len(set(drawn["types"])) == 1 and len(set(drawn["factories"])) == 1
        else:
            assert len(set(drawn["factories"])) == 3
            all_alike_when_separate += len(set(drawn["types"])) == 1
        assert drawn["established_factory"] not in drawn["factories"]
    assert abs(shared / n - rho) < 0.03
    good = 1 - (structure["newcomers"][0]["late"] + structure["newcomers"][0]["failed"]) / pack_module.COHORT_TRACKED
    alike = good**3 + (structure["newcomers"][0]["late"] / 40) ** 3 + (structure["newcomers"][0]["failed"] / 40) ** 3
    assert abs(all_alike_when_separate / max(1, n - shared) - alike) < 0.05


# --- the pilot pack ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((pack_module.pack_root() / "pack.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def worlds(manifest) -> list[dict]:
    cases = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in pack_module.case_paths()}
    return [{**world, "case": cases[world["slug"]]} for world in manifest["worlds"]]


@pytest.mark.parametrize("index", range(12))
def test_each_pilot_world_is_rebuilt_from_its_seed_byte_for_byte(manifest, index) -> None:
    world = manifest["worlds"][index]
    spec = next(s for s in pack_module.world_specs() if s["slug"] == world["slug"])
    assert world["world_seed"] == spec["seed_block"] + world["seeds_scanned"] - 1
    case, entry = pack_module.world_at(spec, world["world_seed"], world["seeds_scanned"])
    committed = json.loads((pack_module.pack_root() / f"{world['slug']}.json").read_text(encoding="utf-8"))
    assert case == committed and entry == world


def test_no_earlier_seed_of_any_block_is_admitted(manifest) -> None:
    """Each world is the first admitted seed of its block: every seed before it, in every block, is screened again."""
    from concurrent.futures import ProcessPoolExecutor

    jobs = []
    for world in manifest["worlds"]:
        spec = next(s for s in pack_module.world_specs() if s["slug"] == world["slug"])
        jobs += [(spec, seed) for seed in range(spec["seed_block"], world["world_seed"])]
    with ProcessPoolExecutor(8) as pool:
        admitted = [job[1] for job, ok in zip(jobs, pool.map(pack_module._admits, jobs, chunksize=4)) if ok]
    assert admitted == []


def test_the_manifest_is_rebuilt_from_its_worlds_byte_for_byte(manifest) -> None:
    entries = []
    for world in manifest["worlds"]:
        spec = next(s for s in pack_module.world_specs() if s["slug"] == world["slug"])
        case = json.loads((pack_module.pack_root() / f"{world['slug']}.json").read_text(encoding="utf-8"))
        entries.append((case, world))
    assert pack_module.build_pack(entries)["manifest"] == manifest


def test_every_pilot_world_passes_admission_and_the_pack_its_mean(manifest, worlds) -> None:
    assert Counter(w["kind"] for w in worlds) == {kind: 6 for kind in pack_module.KINDS}
    for w in worlds:
        for name in pack_module.ADMISSION_RULES:
            assert w["rule_loss_usd"][name] >= pack_module.MARGIN_USD
        assert w["expected_full_information_value_usd"] - w["best_policy_value_usd"] >= pack_module.INFORMATION_HEADROOM_USD
        assert w["one_step_loss_without_shared_source_usd"] < pack_module.ATTRIBUTION_USD
        if w["kind"] == "myopic_pays":
            assert w["best_over_pay_share"] >= pack_module.STAKE_SHARE
            assert w["one_step_first_action"].startswith("request_quote") and w["established"]["supplier_id"] in w["one_step_first_action"]
    assert statistics.fmean(w["rule_loss_usd"]["one_step_value"] for w in worlds) >= pack_module.MEAN_MARGIN_USD
    assert manifest["expected_loss_usd_by_rule"]["one_step_value"] >= pack_module.MEAN_MARGIN_USD


#: v2's pilot pack: always paying the premium lost $69.24 a world, and the best first action went to a newcomer in 12 of 12.
V2_PILOT_PAY_PREMIUM_LOSS_USD = 69.24


def test_testing_is_made_more_attractive_than_in_version_two(manifest, worlds) -> None:
    """Spec check 3: paying the premium loses more than on v2's pilot, and the best first move still goes to a newcomer."""
    assert manifest["expected_loss_usd_by_rule"]["pay_premium"] > V2_PILOT_PAY_PREMIUM_LOSS_USD
    assert all(w["best_first_to_newcomer"] for w in worlds)


@pytest.mark.parametrize("index", range(12))
def test_each_pilot_worlds_values_are_its_own_average_through_the_environment(worlds, index) -> None:
    """Spec check 1 on every pilot world: the best policy's and the one-step rule's exact values against 400 plays
    through the environment under the stated law (types, sharing, factories and replies redrawn)."""
    world = worlds[index]
    spec = next(s for s in pack_module.world_specs() if s["slug"] == world["slug"])
    seed = world["world_seed"]
    structure = pack_module.draw_structure(spec, seed)
    ref = reference.Reference(pack_module._blind(spec, seed, structure))
    start = ref.start()
    assert ref.value(*start) == pytest.approx(world["best_policy_value_usd"], abs=0.006)
    for rule_name in (None, "one_step_value"):
        target = ref.value(*start) if rule_name is None else ref.rule_value(rule_name, reference.RULES[rule_name], *start)
        margins = []
        for k in range(400):
            drawn = pack_module.draw_types(structure, seed * 1000 + k)
            sample = {**structure, "reply_seed": 1 + (seed * 7919 + k * 104729) % (2**31 - 2)}
            ref.case = environment.validate_v3_payload(pack_module.build_case(spec, seed, sample, drawn, seal=False)["payload"])
            state = ref.plugin.initial_state(ref.case, None)
            while not state["done"]:
                seen = ref.status_of(state)
                left, day = ref.max_actions - state["actions_used"], state["elapsed_days"]
                choice = (ref.best_action(seen, left, day) if rule_name is None
                          else reference.RULES[rule_name](ref, seen, left, day))
                if choice[0] == "submit_award" and seen[choice[1]] != QUALIFIED:
                    choice = ("defer",)
                state = _step(ref.plugin, ref.case, state, ref.wire(choice, state))
            margins.append(final_margin(ref, state))
        se = statistics.stdev(margins) / len(margins) ** 0.5
        assert abs(statistics.fmean(margins) - target) < 4 * se + 1e-6


def test_admission_does_not_depend_on_how_the_newcomers_turned_out(worlds) -> None:
    for w in worlds[::3]:
        spec = next(s for s in pack_module.world_specs() if s["slug"] == w["slug"])
        structure = pack_module.draw_structure(spec, w["world_seed"])
        assert pack_module._blind(spec, w["world_seed"], structure) == pack_module._blind(spec, w["world_seed"], structure)
        payload = w["case"]["payload"]
        observed = environment.PayOrTestV3Plugin().observe(environment.validate_v3_payload(payload), {
            **environment.PayOrTestV3Plugin().initial_state(None, None)}, "buyer", None)
        blind = pack_module._blind(spec, w["world_seed"], structure)
        blind_observed = environment.PayOrTestV3Plugin().observe(environment.validate_v3_payload(blind), {
            **environment.PayOrTestV3Plugin().initial_state(None, None)}, "buyer", None)
        assert observed == blind_observed


# --- the brief ----------------------------------------------------------------------------------


def test_the_brief_states_the_actions_the_environment_takes_and_no_other() -> None:
    listed = set(re.findall(r"^- ([a-z_]+): ", PAY_OR_TEST_V3_PROMPT.split("Allowed actions:")[1].split("\n\n")[0], re.M))
    assert listed == environment.ACTION_TYPES
    for gone in ("inquire", "counter_offer", "financing", "cash_budget", "verbal"):
        assert gone not in PAY_OR_TEST_V3_PROMPT


def test_every_field_the_brief_names_is_in_what_the_buyer_sees() -> None:
    _, payload = _world()
    plugin = environment.PayOrTestV3Plugin()
    case = plugin.validate_payload(payload)
    observed = plugin.observe(case, plugin.initial_state(case, None), "buyer", None)
    for path in set(re.findall(r"\b((?:policy|objective)\.[a-z_]+(?:\.[a-z_]+)*)", PAY_OR_TEST_V3_PROMPT)):
        node = observed
        for part in path.split("."):
            assert part in node, path
            node = node[part]
    listing = observed["supplier_listings"][0]["listing"]
    for field in ("sample_fee_usd", "sample_days", "marketplace_record", "seller_kind"):
        assert field in listing


def test_the_brief_states_the_answer_rate_lookup_terms_and_shared_source_as_the_generator_draws_them() -> None:
    _, payload = _world()
    case = environment.validate_v3_payload(payload)
    assert case["policy"]["newcomer_quote_answer_probability"] == pytest.approx(pack_module.ANSWER_PROBABILITY, abs=1e-6)
    assert case["interaction"]["source_lookup_cost_usd"] == pack_module.LOOKUP_FEE_USD
    flat = " ".join(PAY_OR_TEST_V3_PROMPT.split())
    assert "name the same factory when looked up" in flat and "It always arrives" in flat
    assert "A listing with a marketplace_record always answers" in flat
    assert "check_award reports whether an award would be eligible and what it would earn. It costs nothing and takes no days" in flat
    assert v2_reference.Reference.__init__ and "policy.newcomer_sourcing.same_source_probability" in flat


# --- the kernel ----------------------------------------------------------------------------------


def _sealed_case_path(tmp_path, seed: int = THREE_OF_A_KIND):
    structure = pack_module.draw_structure(SPEC, seed)
    case = pack_module.build_case(SPEC, seed, structure, pack_module.draw_types(structure, seed))
    path = tmp_path / "case.json"
    path.write_text(json.dumps(case, indent=2, sort_keys=True), encoding="utf-8")
    return path, case


def test_the_kernel_refuses_the_version_three_plugin_until_it_is_trusted(tmp_path) -> None:
    from aeread.shared_runner.registry import ContributionAdmissionError
    from aeread_families.procurement_allocation import pay_or_test_v3_runner as runner
    from aeread_families.procurement_allocation.pay_or_test_v3_prompt import PROMPT_ID

    path, _ = _sealed_case_path(tmp_path)
    with pytest.raises(ContributionAdmissionError, match="not an exact in-tree trusted plugin"):
        runner.build_offline_setup(case_path=path, prompt=PAY_OR_TEST_V3_PROMPT, prompt_id=PROMPT_ID)


@pytest.mark.parametrize("rule", ["look_up_first", None])
def test_once_trusted_an_episode_runs_through_the_kernel_scores_as_the_reference_and_replays(tmp_path, monkeypatch, rule) -> None:
    import asyncio

    from aeread.shared_runner import registry
    from aeread.shared_runner.run.resolver import canonical_json_bytes
    from aeread.shared_runner.task.evaluation import finalize_family_execution, replay_family_receipt
    from aeread.shared_runner.task.execution import execute_plan_cell
    from aeread_families.procurement_allocation import pay_or_test_v3_runner as runner
    from aeread_families.procurement_allocation.runner import SequenceResponseProvider
    from aeread_families.procurement_allocation.pay_or_test_v3_prompt import PROMPT_ID

    key = (environment.FAMILY_ID, environment.FAMILY_VERSION, environment.PLUGIN_ID)
    monkeypatch.setattr(registry, "TRUSTED_BUILTIN_PLUGIN_KEYS", registry.TRUSTED_BUILTIN_PLUGIN_KEYS | {key})
    path, case = _sealed_case_path(tmp_path)
    actions = reference.play(case["payload"], reference.RULES[rule] if rule else None)
    if rule == "look_up_first":
        assert sum(a["action"] == reference.LOOKUP for a in actions) >= 2
    setup = runner.build_offline_setup(case_path=path, prompt=PAY_OR_TEST_V3_PROMPT, prompt_id=PROMPT_ID)
    provider = SequenceResponseProvider([canonical_json_bytes(a).decode("utf-8") for a in actions])
    execution = asyncio.run(execute_plan_cell(
        plan=setup.plan, cell_id=setup.plan.cells[0].cell_id, registry=setup.registry, evidence_root=tmp_path / "ev",
        prompt_sources=setup.prompt_sources, providers={"fake": provider}, pricing=setup.pricing,
        episode_attempt_ordinal=0, harnesses=setup.harnesses))
    assert provider.exhausted
    ref = reference.Reference(case["payload"])
    expected = final_margin(ref, reference.run(case["payload"], actions))
    assert execution.episode_result.outcome["contribution_margin_usd"] == pytest.approx(expected)
    receipt = finalize_family_execution(setup=setup, execution=execution)
    assert receipt.status == "ok" and receipt.scores[0].leaf.scorer.implementation_id == environment.SCORER_ID
    replayed = replay_family_receipt(setup=setup, receipt=receipt, evidence_root=tmp_path / "ev")
    assert canonical_json_bytes(replayed) == canonical_json_bytes(receipt)


# --- the confirmatory pack and its odds twins --------------------------------------------------


def _confirm_manifest() -> dict:
    return json.loads((pack_module.pack_root(pack_module.CONFIRM_PACK_ID) / "pack.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("index", range(20))
def test_each_confirmatory_world_is_rebuilt_from_its_seed_byte_for_byte(index) -> None:
    world = _confirm_manifest()["worlds"][index]
    spec = next(s for s in pack_module.world_specs(pack_module.CONFIRM_PACK_ID) if s["slug"] == world["slug"])
    assert world["world_seed"] == spec["seed_block"] + world["seeds_scanned"] - 1
    case, entry = pack_module.world_at(spec, world["world_seed"], world["seeds_scanned"])
    root = pack_module.pack_root(pack_module.CONFIRM_PACK_ID)
    assert case == json.loads((root / f"{world['slug']}.json").read_text(encoding="utf-8")) and entry == world


def test_no_earlier_seed_of_any_confirmatory_block_is_admitted() -> None:
    from concurrent.futures import ProcessPoolExecutor

    jobs = []
    for world in _confirm_manifest()["worlds"]:
        spec = next(s for s in pack_module.world_specs(pack_module.CONFIRM_PACK_ID) if s["slug"] == world["slug"])
        jobs += [(spec, seed) for seed in range(spec["seed_block"], world["world_seed"])]
    with ProcessPoolExecutor(8) as pool:
        admitted = [job[1] for job, ok in zip(jobs, pool.map(pack_module._admits, jobs, chunksize=4)) if ok]
    assert admitted == []


def test_the_confirmatory_pack_is_twenty_fresh_option_value_worlds_that_pass_admission() -> None:
    manifest = _confirm_manifest()
    worlds = manifest["worlds"]
    assert len(worlds) == 20 and {w["kind"] for w in worlds} == {"myopic_pays"}
    pilot = json.loads((pack_module.pack_root() / "pack.json").read_text(encoding="utf-8"))
    assert min(w["world_seed"] for w in worlds) > max(w["world_seed"] for w in pilot["worlds"])
    for w in worlds:
        for name in pack_module.ADMISSION_RULES:
            assert w["rule_loss_usd"][name] >= pack_module.MARGIN_USD
        assert w["best_over_pay_share"] >= pack_module.STAKE_SHARE
        assert w["one_step_loss_without_shared_source_usd"] < pack_module.ATTRIBUTION_USD
    entries = [(json.loads((pack_module.pack_root(pack_module.CONFIRM_PACK_ID) / f"{w['slug']}.json").read_text()), w)
               for w in worlds]
    assert pack_module.build_pack(entries, split=pack_module.CONFIRM_PACK_ID)["manifest"] == manifest


def test_each_odds_twin_is_its_confirmatory_world_with_only_the_cohort_records_redrawn() -> None:
    root = pack_module.pack_root(pack_module.DIAGNOSTIC_PACK_ID)
    committed = json.loads((root / "pack.json").read_text(encoding="utf-8"))
    rebuilt = pack_module.build_diagnostic_pack()
    assert rebuilt["manifest"] == committed
    for case in rebuilt["cases"]:
        assert case == json.loads((root / f"{case['case_id'].rsplit('.', 1)[-1]}.json").read_text(encoding="utf-8"))
    for twin in committed["worlds"]:
        spec = {"slug": twin["slug"], "kind": "myopic_pays", "pack_id": pack_module.CONFIRM_PACK_ID}
        original = pack_module.draw_structure(spec, twin["world_seed"])
        variant = pack_module.with_version_one_odds(original, twin["world_seed"])
        strip = lambda st: {**st, "newcomers": [{k: v for k, v in n.items() if k not in ("late", "failed")}  # noqa: E731
                                                for n in st["newcomers"]]}
        assert strip(original) == strip(variant)
        for n in variant["newcomers"]:
            assert n["late"] in pack_module.V1_COHORT_LATE and n["failed"] in pack_module.V1_COHORT_FAILED
