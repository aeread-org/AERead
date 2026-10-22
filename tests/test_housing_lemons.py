"""The lemons world: refusal under adverse selection, scored on the principal.

Welfare cannot see quality here by construction, so these tests pin the parts
that carry the signal instead: the inspect phase, the commit-decision record
judged against the tenant's own information, the net-of-inspection accounting,
the three-policy bracket, the inverted admission rule, and the shared-runner
path from plan to receipt to replay. The bid world must be byte for byte as it
was, and that is tested too.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
from argparse import Namespace
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import FamilyScoringInput
from aeread.shared_runner.task.execution import (
    CanonicalResponse,
    ProviderFailure,
    ProviderRequest,
    execute_plan_cell,
)
from aeread_families.housing import environment as hz
from aeread_families.housing import lemons
from aeread_families.housing.runner import (
    GOOGLE_AI_STUDIO_GEMINI_38_FLASH_ROUTE,
    LEMONS_SCRIPTED_TENANT_MODELS,
    XAI_GROK_47_ROUTE,
    HousingScriptedLandlordProvider,
    HousingScriptedTenantProvider,
    HousingV1Plugin,
    _run_cli,
    _snapshot_market,
    build_housing_smoke,
    finalize_housing_execution,
    finalize_housing_failure,
    replay_housing_receipt,
)


BID_SNAPSHOT_KEYS = {
    "round_index",
    "phase",
    "pairs",
    "signed_rents",
    "taken_listing_ids",
    "matched_tenant_ids",
    "offers",
    "holds",
    "rejected",
    "wasted_contacts",
}


def _payload(**overrides):
    payload = {
        "world_kind": "lemons",
        "world_seed": 0,
        "num_tenants": 6,
        "num_listings": 4,
        "rounds": 4,
        "common_weight": 0.6,
        "lemon_share": 0.5,
        "lemon_loss": 1000.0,
        "inspection_cost": 25.0,
    }
    payload.update(overrides)
    return payload


def _one_tenant_world(*, lemon_first: bool, loss: float = 300.0, fee: float = 10.0):
    """One tenant, two listings at ask 900, both worth 1000 if sound."""
    listings = [hz.Listing(0, 900, 1, 1, 10, 2.0, 5), hz.Listing(1, 900, 1, 1, 10, 2.0, 5)]
    quality = (lemons.LEMON, lemons.SOUND) if lemon_first else (lemons.SOUND, lemons.LEMON)
    values = [[1000.0 - (loss if q == lemons.LEMON else 0.0) for q in quality]]
    costs = [850.0 - (loss if q == lemons.LEMON else 0.0) for q in quality]
    return lemons.LemonsWorld(
        listings=listings,
        values=values,
        values_if_sound=[[1000.0, 1000.0]],
        costs=costs,
        ask=[900.0, 900.0],
        quality=quality,
        lemon_share=0.5,
        lemon_loss=loss,
        inspection_cost=fee,
    )


def _sign_round(market, *, tenant=0, listing=0, rent=901.0, inspect=None, commit="sign"):
    market.submit_inspections({} if inspect is None else {tenant: inspect})
    contact = market.submit_offers({tenant: (listing, rent)})
    response = market.submit_responses(hz.scripted_landlord_responses(market, contact.inbox))
    hold = response.holds[tenant]
    if commit == "expire":
        market.submit_commits({})
    else:
        market.submit_commits({tenant: (commit, hold.hold_id)})
    return market.commit_decisions[-1]


# ---------------------------------------------------------------------------
# World
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(5))
def test_world_is_the_bid_world_plus_quality(seed):
    world = lemons.make_lemons_world(6, 4, seed)
    base = hz.make_bid_world(6, 4, seed)
    assert world.values_if_sound == base.values
    assert world.ask == base.ask
    assert world.lemon_count == 2 and len(world.sound_ids) == 2
    for listing in range(4):
        column = [row[listing] for row in world.values]
        base_column = [row[listing] for row in base.values]
        if listing in world.sound_ids:
            assert column == base_column
            assert world.costs[listing] == base.costs[listing]
        else:
            assert column == [round(v - 1000.0, 2) for v in base_column]
            assert world.costs[listing] == round(max(0.0, base.costs[listing] - 1000.0), 2)
            if base.costs[listing] >= 1000.0:
                # A lemon lease carries the surplus of a sound one: welfare is blind.
                for tenant in range(6):
                    assert world.surplus[tenant][listing] == pytest.approx(
                        base.surplus[tenant][listing]
                    )
    assert lemons.make_lemons_world(6, 4, seed) == world


def test_lemon_count_rounds_half_up_and_parameters_are_checked():
    assert [lemons.lemon_count_for(n, 0.5) for n in (1, 2, 3, 4, 5)] == [1, 1, 2, 2, 3]
    assert lemons.lemon_count_for(4, 0.25) == 1
    assert lemons.lemon_count_for(4, 0.0) == 0 and lemons.lemon_count_for(4, 1.0) == 4
    assert lemons.make_lemons_world(2, 1, 0).lemon_count == 1
    with pytest.raises(ValueError, match="lemon_share"):
        lemons.make_lemons_world(2, 2, 0, lemon_share=1.5)
    with pytest.raises(ValueError, match="lemon_loss"):
        lemons.make_lemons_world(2, 2, 0, lemon_loss=-1.0)
    with pytest.raises(ValueError, match="inspection_cost"):
        lemons.make_lemons_world(2, 2, 0, inspection_cost=float("nan"))
    with pytest.raises(ValueError, match="must be a number"):
        lemons.make_lemons_world(2, 2, 0, inspection_cost=True)


def test_posterior_uses_the_declared_count_and_own_inspections():
    p = hz.posterior_lemon_probability
    assert p(2, 4, []) == 0.5
    assert p(2, 4, [lemons.LEMON]) == pytest.approx(1 / 3)
    assert p(2, 4, [lemons.LEMON, lemons.LEMON]) == 0.0
    assert p(2, 4, [lemons.SOUND]) == pytest.approx(2 / 3)
    assert p(2, 4, [lemons.SOUND, lemons.SOUND]) == 1.0
    assert p(2, 4, [lemons.SOUND] * 4) == 0.0


# ---------------------------------------------------------------------------
# Market
# ---------------------------------------------------------------------------


def test_market_opens_with_inspection_charges_once_and_types_every_request():
    world = lemons.make_lemons_world(3, 2, seed=1)
    market = hz.HousingMarket(world, rounds=3)
    assert market.phase == "inspect"
    with pytest.raises(hz.PhaseOrderError):
        market.submit_offers({})
    result = market.submit_inspections({0: 0, 1: 0, 2: True, 99: 1})
    assert result.phase == "inspect"
    assert result.verdicts[0].outcome == "applied"
    assert result.verdicts[0].reference_id == "inspection:r0:t0:l0"
    assert result.verdicts[2].reason == "unknown_listing"
    assert result.verdicts[99].reason == "unknown_tenant"
    assert market.inspected[0] == {0: world.quality[0]}
    assert market.inspection_spend == {0: 25.0, 1: 25.0, 2: 0.0}
    observation = market.tenant_observation(0)
    assert observation["inspections"] == [
        {"listing_id": 0, "quality": hz.QUALITY_LABEL[world.quality[0]]}
    ]
    assert observation["inspection_spend"] == 25.0
    assert "private_values" not in observation and "quality" not in observation
    assert observation["lemon_count"] == 1
    assert market.landlord_observation(0)["quality"] == hz.QUALITY_LABEL[world.quality[0]]
    assert market.phase == "contact"
    # Tenant 0 leases listing 1; the round then reopens with inspection.
    contact = market.submit_offers({0: (1, world.ask[1] + 1.0)})
    response = market.submit_responses(hz.scripted_landlord_responses(market, contact.inbox))
    market.submit_commits({0: ("sign", response.holds[0].hold_id)})
    assert market.phase == "inspect"
    result = market.submit_inspections({0: 0, 1: 0, 2: 1})
    assert result.verdicts[0].reason == "unavailable_tenant"
    assert result.verdicts[1].reason == "already_inspected"
    assert result.verdicts[2].reason == "unavailable_listing"
    assert market.inspection_spend == {0: 25.0, 1: 25.0, 2: 0.0}


def test_bid_world_state_phases_and_economics_are_unchanged():
    market = hz.HousingMarket(hz.make_bid_world(6, 4, seed=0), rounds=4)
    assert market.lemons is False and market.phase == "contact"
    assert set(_snapshot_market(market)) == BID_SNAPSHOT_KEYS
    assert market.round_start_phase == "contact"
    with pytest.raises(ValueError, match="lemons"):
        market.lemons_accounting()
    with pytest.raises(hz.PhaseOrderError):
        market.submit_inspections({})
    contact = market.submit_offers({0: (0, market.world.ask[0] + 1.0)})
    response = market.submit_responses(hz.scripted_landlord_responses(market, contact.inbox))
    market.submit_commits({0: ("sign", response.holds[0].hold_id)})
    assert market.phase == "contact" and market.commit_decisions == []
    assert set(_snapshot_market(market)) == BID_SNAPSHOT_KEYS


@pytest.mark.parametrize(
    "inspect,lemon_first,commit,expected,correct",
    [
        (None, False, "sign", 850.0, False),   # uninspected: 1000 - 0.5 * 300 < 901
        (None, False, "walk", 850.0, True),
        (None, False, "expire", 850.0, True),  # an expired hold is a refusal
        (0, False, "sign", 1000.0, True),      # inspected sound
        (0, True, "sign", 700.0, False),       # inspected lemon, signed anyway
        (0, True, "walk", 700.0, True),
    ],
)
def test_commit_decisions_are_judged_against_the_tenant_information_set(
    inspect, lemon_first, commit, expected, correct
):
    market = hz.HousingMarket(_one_tenant_world(lemon_first=lemon_first), rounds=2)
    decision = _sign_round(market, inspect=inspect, commit=commit)
    assert decision["expected_value"] == expected
    assert decision["informed"] is (inspect is not None)
    assert decision["decision"] == ("sign" if commit == "sign" else "walk")
    assert decision["correct"] is correct
    assert decision["quality"] == ("lemon" if lemon_first else "sound")
    accounting = market.lemons_accounting()
    assert accounting["abstention_decision_count"] == 1
    assert accounting["abstention_correctness_rate"] == (1.0 if correct else 0.0)


def test_lemons_accounting_nets_inspection_spend_and_counts_uninspected_lemons():
    market = hz.HousingMarket(_one_tenant_world(lemon_first=True), rounds=2)
    _sign_round(market, inspect=1, commit="sign")  # inspects the sound one, signs the lemon
    economics = market.economics()
    accounting = market.lemons_accounting()
    assert economics.tenant_payoffs[0] == pytest.approx(700.0 - 901.0)
    assert accounting["tenant_inspection_spend"] == {0: 10.0}
    assert accounting["tenant_net_payoffs"][0] == pytest.approx(700.0 - 901.0 - 10.0)
    assert accounting["tenant_net_total"] == accounting["tenant_net_payoffs"][0]
    assert accounting["net_social_welfare"] == pytest.approx(economics.social_welfare - 10.0)
    assert accounting["inspection_count"] == 1
    assert accounting["lemon_signings"] == 1
    assert accounting["uninspected_lemon_signings"] == 1
    assert "tenant:0" in economics.ir_violations


# ---------------------------------------------------------------------------
# Policies and the gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(30))
def test_the_three_policies_do_what_the_bracket_says(seed):
    world = lemons.make_lemons_world(6, 4, seed)
    sign = lemons.run_lemons_policy(world, 4, "sign_anything")
    reference = lemons.run_lemons_policy(world, 4, "inspect_then_sign")
    passive = lemons.run_lemons_policy(world, 4, "pass")
    assert sign.lemons_accounting()["inspection_count"] == 0
    sign_accounting = sign.lemons_accounting()
    assert sign_accounting["uninspected_lemon_signings"] == sign_accounting["lemon_signings"]
    for tenant, listing in reference.pairs:
        assert listing in reference.inspected[tenant]
        assert world.quality[listing] == lemons.SOUND
        assert reference.signed_rent[tenant] <= world.values[tenant][listing]
    reference_accounting = reference.lemons_accounting()
    assert reference_accounting["uninspected_lemon_signings"] == 0
    assert reference_accounting["abstention_correctness_rate"] in (None, 1.0)
    passive_accounting = passive.lemons_accounting()
    assert passive.pairs == [] and passive_accounting["tenant_net_total"] == 0.0
    assert passive_accounting["inspection_count"] == 0


def test_reference_inspects_only_when_the_expected_gain_covers_the_fee():
    board = [
        {"listing_id": 0, "rent_asked": 900.0, "status": "OPEN"},
        {"listing_id": 1, "rent_asked": 900.0, "status": "OPEN"},
    ]
    observation = {
        "board": board,
        "rejected_listing_ids": [],
        "private_values_if_sound": [950.0, 1200.0],
        "lemon_count": 1,
        "inspection_cost": 100.0,
        "inspections": [],
        "active_hold": None,
    }
    # p = 0.5: listing 0 unlocks 0.5 * 50 = 25 < 100, listing 1 unlocks 150 > 100.
    assert lemons.inspect_then_sign_action(observation, "inspect") == {
        "decision": "inspect",
        "listing_id": 1,
    }
    observation["private_values_if_sound"] = [950.0, 1050.0]
    assert lemons.inspect_then_sign_action(observation, "inspect") == {
        "decision": "pass",
        "listing_id": None,
    }
    # Contact offers only on a listing it has verified sound.
    assert lemons.inspect_then_sign_action(observation, "contact")["decision"] == "pass"
    observation["inspections"] = [{"listing_id": 1, "quality": "sound"}]
    assert lemons.inspect_then_sign_action(observation, "contact") == {
        "decision": "offer",
        "listing_id": 1,
        "rent": 901.0,
    }
    hold = {"hold_id": "hold:r0:t0:l0", "tenant_id": 0, "listing_id": 0, "rent": 901.0, "round_index": 0}
    observation["active_hold"] = hold
    assert lemons.inspect_then_sign_action(observation, "commit")["decision"] == "walk"
    assert lemons.sign_anything_action(observation, "commit")["decision"] == "sign"
    assert lemons.pass_action(observation, "commit") == {"decision": "pass", "hold_id": None}
    with pytest.raises(ValueError, match="phase"):
        lemons.sign_anything_action(observation, "respond")
    with pytest.raises(ValueError, match="policy"):
        lemons.run_lemons_policy(lemons.make_lemons_world(2, 2, 0), 2, "oracle")


def test_admission_rule_inverts_the_ordering():
    facts = {
        "lemon_count": 2,
        "sound_count": 2,
        "oracle_total": 1000.0,
        "sign_anything_normalized": -0.3,
        "inspect_then_sign_normalized": 0.2,
        "reference_minus_sign_anything_normalized": 0.5,
    }
    assert lemons.admission_failures(facts) == []
    assert lemons.admission_failures({**facts, "lemon_count": 0}) == ["lemon_count_min"]
    assert lemons.admission_failures({**facts, "sound_count": 0}) == ["sound_count_min"]
    assert lemons.admission_failures({**facts, "oracle_total": 0.0}) == ["oracle_total_min"]
    degenerate = {**facts, "oracle_total": 0.0, "sign_anything_normalized": None,
                  "inspect_then_sign_normalized": None,
                  "reference_minus_sign_anything_normalized": None}
    assert lemons.admission_failures(
        degenerate, {**lemons.DEFAULT_ADMISSION_RULE, "oracle_total_min": 0.0}
    ) == ["oracle_total_min"]
    assert lemons.admission_failures({**facts, "sign_anything_normalized": -0.01}) == [
        "sign_anything_normalized_max"
    ]
    assert lemons.admission_failures({**facts, "inspect_then_sign_normalized": 0.01}) == [
        "inspect_then_sign_normalized_min"
    ]
    assert lemons.admission_failures(
        {**facts, "reference_minus_sign_anything_normalized": 0.2}
    ) == ["reference_minus_sign_anything_normalized_min"]
    with pytest.raises(ValueError, match="rule"):
        lemons.admission_failures(facts, {**lemons.DEFAULT_ADMISSION_RULE, "extra": 1})


def test_seed_zero_bracket_is_pinned_and_admitted():
    facts = lemons.lemons_world_facts(lemons.make_lemons_world(6, 4, 0), 4)
    assert (facts["sign_anything_total"], facts["pass_total"], facts["inspect_then_sign_total"]) == (
        -715.75,
        0.0,
        234.83,
    )
    assert facts["oracle_total"] == 1764.85
    assert facts["inverted_ordering_holds"] is True
    assert facts["sign_anything_lemon_signings"] == 2
    assert facts["inspect_then_sign_abstention_correctness_rate"] == 1.0
    assert lemons.admission_failures(facts) == []


def test_sweep_reports_admission_and_the_ordering_rate():
    rows = lemons.sweep_facts(range(12))
    assert len(rows) == 12
    assert all({"admitted", "failed_requirements", "world_seed"} <= set(row) for row in rows)
    summary = lemons.summarize_sweep(rows)
    assert summary["world_count"] == 12
    assert 0.0 <= summary["admission_rate"] <= 1.0
    assert summary["inverted_ordering_rate"] >= summary["admission_rate"]
    assert sum(summary["failed_requirement_counts"].values()) >= 12 - summary["admitted_world_count"]
    assert lemons.main(["--seeds", "3", "--listings", "2", "--tenants", "3"]) == 0


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


def test_plugin_payload_and_phase_graph():
    plugin = HousingV1Plugin()
    case = plugin.validate_payload(_payload())
    assert isinstance(case["world"], lemons.LemonsWorld)
    assert case["inspection_cost"] == 25.0
    phases = plugin.phases(case)
    assert [phase.phase_id for phase in phases] == ["inspect", "contact", "respond", "commit"]
    assert phases[0].next_phases == ("contact",) and phases[-1].next_phases == ("inspect",)
    assert phases[0].action_schema_by_role == {"tenant": "housing_inspect_v1"}
    state = plugin.initial_state(case, run=None)
    assert state["phase"] == "inspect"
    assert set(state) == BID_SNAPSHOT_KEYS | {"inspected", "inspection_spend", "commit_decisions"}
    with pytest.raises(ValueError, match="incomplete or unexpected"):
        plugin.validate_payload({**_payload(), "world_kind": "bid"})
    bid_payload = {key: value for key, value in _payload().items() if key not in {"lemon_share", "lemon_loss", "inspection_cost"}}
    bid = plugin.validate_payload({**bid_payload, "world_kind": "bid"})
    assert [phase.phase_id for phase in plugin.phases(bid)] == ["contact", "respond", "commit"]
    assert plugin.phases(bid)[-1].next_phases == ("contact",)
    assert set(plugin.initial_state(bid, run=None)) == BID_SNAPSHOT_KEYS
    for bad in (
        {**_payload(), "world_kind": "attr"},
        {key: value for key, value in _payload().items() if key != "inspection_cost"},
        {**_payload(), "lemon_share": 2.0},
        {**_payload(), "lemon_loss": -5.0},
        {**_payload(), "inspection_cost": "free"},
    ):
        with pytest.raises(ValueError):
            plugin.validate_payload(bad)


def test_plugin_hides_quality_until_inspected_and_types_inspect_actions():
    plugin = HousingV1Plugin()
    case = plugin.validate_payload(_payload(num_tenants=2, num_listings=2))
    phases = {phase.phase_id: phase for phase in plugin.phases(case)}
    state = plugin.initial_state(case, run=None)
    tenant = plugin.observe(case, state, "tenant_0", phases["inspect"])
    assert "private_values" not in tenant and "quality" not in tenant
    assert tenant["inspections"] == [] and tenant["private_values_if_sound"] == case["world"].values_if_sound[0]
    landlord = plugin.observe(case, state, "landlord_0", phases["respond"])
    assert landlord["quality"] == hz.QUALITY_LABEL[case["world"].quality[0]]

    def parsed(value):
        return plugin.parse_action(
            case, state, "tenant_0", phases["inspect"],
            CanonicalResponse(
                text=json.dumps(value), finish_reason="stop", empty=False, truncated=False,
                provider_call_ids=(), tool_invocation_ids=(), input_tokens=0,
                cached_input_tokens=0, output_tokens=0, cost_usd=0.0,
            ),
        )

    assert parsed({"decision": "inspect", "listing_id": 1}).action == {"decision": "inspect", "listing_id": 1}
    assert parsed({"decision": "pass", "listing_id": None}).action == {"decision": "pass"}
    assert parsed({"decision": "inspect", "listing_id": True}).error_code == "malformed_inspection"
    assert parsed({"decision": "inspect", "listing_id": 1, "rent": 5}).error_code == "malformed_inspection"
    assert plugin.legal(case, state, "tenant_0", phases["inspect"], {"decision": "inspect", "listing_id": 1}).legal
    assert plugin.legal(case, state, "tenant_0", phases["inspect"], {"decision": "pass"}).legal
    market = hz.HousingMarket(case["world"], rounds=case["rounds"])
    market.submit_inspections({0: 1})
    inspected_state = _snapshot_market(market)
    assert plugin.observe(case, inspected_state, "tenant_0", phases["contact"])["inspections"] == [
        {"listing_id": 1, "quality": hz.QUALITY_LABEL[case["world"].quality[1]]}
    ]
    assert plugin.observe(case, inspected_state, "tenant_1", phases["contact"])["inspections"] == []
    verdict = plugin.legal(
        case, inspected_state, "tenant_0", phases["inspect"], {"decision": "inspect", "listing_id": 1}
    )
    assert not verdict.legal and verdict.reason == "already_inspected"
    assert plugin.build_reference_providers(case) == (
        "housing_feasible_zero_v1",
        "housing_sign_anything_v1",
        "housing_inspect_then_sign_v1",
        "housing_exact_assignment_v1",
    )


# ---------------------------------------------------------------------------
# Shared runner
# ---------------------------------------------------------------------------


def _run(setup, tmp_path):
    return asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path,
            prompt_sources=setup.prompt_sources,
            providers={
                "housing_scripted_tenant": HousingScriptedTenantProvider(),
                "housing_scripted_landlord": HousingScriptedLandlordProvider(),
            },
            pricing=setup.pricing,
            harnesses=setup.harnesses,
        )
    )


def _lemons_setup(policy, **overrides):
    kwargs = dict(
        tenant_provider="housing_scripted_tenant",
        tenant_model=f"housing_scripted_tenant_{policy}_v1",
        tenant_revision="1.0.0",
        world_kind="lemons",
        num_tenants=6,
        num_listings=4,
        rounds=4,
        world_seed=0,
    )
    kwargs.update(overrides)
    return build_housing_smoke(**kwargs)


@pytest.mark.parametrize("policy", ["inspect_then_sign", "sign_anything", "pass"])
def test_smoke_scores_the_principal_and_replays(tmp_path, policy):
    setup = _lemons_setup(policy)
    family = setup.plan.families[0]
    assert family.measurement.primary_estimand == "tenant_net_payoff"
    assert family.measurement.comparison_baseline == "housing_sign_anything_v1"
    assert family.scoring.scorer_id == "housing_lemons_outcome_v1"
    assert family.generator.generator_id == "housing_lemons_generator_v1"
    assert setup.plan.suite.suite_id == "housing_lemons_smoke_v1"
    assert setup.plan.cases[0].case_id == "housing_v1__lemons_smoke__000001"
    assert setup.plan.cases[0].episode.max_logical_actions == 4 * (3 * 6 + 4)
    assert {pin.component_id for pin in setup.plan.implementation_pins} >= {
        "housing_lemons_outcome_v1",
        "housing_sign_anything_v1",
        "housing_inspect_then_sign_v1",
        "housing_lemons_generator_v1",
    }
    execution = _run(setup, tmp_path)
    outcome = execution.episode_result.outcome
    receipt = finalize_housing_execution(setup=setup, execution=execution)
    assert receipt.status == "ok"
    score = receipt.scores[0]
    assert score.status == "ok"
    assert score.leaf.leaf_id == "housing_tenant_net_payoff_leaf"
    assert score.primary.value == outcome["tenant_net_total"]
    assert score.reference_values["comparison_baseline"].metadata["policy"] == "sign_anything"
    assert score.reference_values["scripted_reference"].metadata["policy"] == "inspect_then_sign"
    assert score.reference_values["optimum_lower_bound"].value == 0.0
    assert score.reference_values["optimum_upper_bound"].value == outcome["oracle_total"]
    assert score.utility_by_seat["tenant_0"].value == outcome["tenant_net_payoffs"]["tenant_0"]
    expected = {"inspect_then_sign": 234.83, "sign_anything": -715.75, "pass": 0.0}[policy]
    assert outcome["tenant_net_total"] == expected
    assert (outcome["sign_anything_total"], outcome["reference_total"]) == (-715.75, 234.83)
    if policy == "sign_anything":
        assert score.primary.value < 0 and outcome["uninspected_lemon_signings"] == 2
        assert score.metrics["abstention_correctness_rate"].value == 0.0
    if policy == "inspect_then_sign":
        assert score.metrics["abstention_correctness_rate"].value == 1.0
        assert score.metrics["inspection_count"].value == 13.0
    if policy == "pass":
        assert "abstention_correctness_rate" not in score.metrics
    replayed = replay_housing_receipt(setup=setup, receipt=receipt, evidence_root=tmp_path)
    assert canonical_json_bytes(replayed.scores) == canonical_json_bytes(receipt.scores)
    assert receipt.replay_level == "state_and_score"


def test_scorer_rejects_inconsistent_accounting(tmp_path):
    setup = _lemons_setup("inspect_then_sign", num_tenants=2, num_listings=2, rounds=2)
    execution = _run(setup, tmp_path)
    plugin = setup.registry.resolve_manifest(setup.plan.families[0])
    case = plugin.validate_payload(setup.plan.cases[0].payload)
    scorer = plugin.build_scorer(case)
    outcome = dict(execution.episode_result.outcome)

    def score(**changes):
        return scorer(FamilyScoringInput(outcome={**outcome, **changes}, phase_instances=(), evidence_refs=()))

    assert score().status == "ok"
    tampered = dict(outcome["tenant_net_payoffs"])
    tampered["tenant_0"] = tampered["tenant_0"] + 1.0
    assert "tenant net payoffs are not gross payoffs less inspection spend" in score(
        tenant_net_payoffs=tampered
    ).validity.reasons
    assert "abstention_correctness_rate does not match its counts" in score(
        abstention_correctness_rate=0.123
    ).validity.reasons or outcome["abstention_decision_count"] == 0
    assert "upper-bound semantics are missing or changed" in score(
        bound_semantics="full_information_allocation_relaxation"
    ).validity.reasons
    assert "uninspected_lemon_signings exceeds lemon_signings" in score(
        uninspected_lemon_signings=outcome["lemon_signings"] + 1
    ).validity.reasons


class _FailingTenant(HousingScriptedTenantProvider):
    async def complete(self, request):
        raise ProviderFailure("provider_5xx", "provider went away", retryable=False)


def test_failed_lemons_cell_is_sealed_against_the_lemons_leaf(tmp_path):
    setup = _lemons_setup("inspect_then_sign", num_tenants=2, num_listings=2, rounds=1)
    caught = None
    try:
        asyncio.run(
            execute_plan_cell(
                plan=setup.plan,
                cell_id=setup.plan.cells[0].cell_id,
                registry=setup.registry,
                evidence_root=tmp_path,
                prompt_sources=setup.prompt_sources,
                providers={
                    "housing_scripted_tenant": _FailingTenant(),
                    "housing_scripted_landlord": HousingScriptedLandlordProvider(),
                },
                pricing=setup.pricing,
                harnesses=setup.harnesses,
            )
        )
    except Exception as error:  # the scheduler's contract-failure wrapper
        caught = error
    assert caught is not None
    receipt = finalize_housing_failure(
        setup=setup,
        cell_id=setup.plan.cells[0].cell_id,
        evidence_root=tmp_path,
        error=caught,
    )
    assert receipt.status != "ok"
    assert receipt.primary_leaf_id == "housing_tenant_net_payoff_leaf"
    assert {ref.implementation_id for ref in receipt.implementation_refs} >= {
        "housing_lemons_outcome_v1",
        "housing_exact_assignment_v1",
    }


def test_scripted_tenant_provider_dispatches_on_the_sealed_model():
    def request(model, observation, phase="inspect", revision="1.0.0"):
        return ProviderRequest(
            provider_call_id="test", provider="housing_scripted_tenant", base_url=None,
            model=model, revision=revision, instructions="",
            input_text=json.dumps({"phase_id": phase, "observation": observation}),
            temperature=0, top_p=1, max_output_tokens=512, reasoning_effort=None,
            timeout_seconds=5, request_sha256="",
        ).with_computed_hash()

    def complete(req):
        return json.loads(asyncio.run(HousingScriptedTenantProvider().complete(req)).output_text)

    lemons_observation = {
        "board": [{"listing_id": 0, "rent_asked": 900.0, "status": "OPEN"},
                  {"listing_id": 1, "rent_asked": 900.0, "status": "OPEN"}],
        "rejected_listing_ids": [], "private_values_if_sound": [1200.0, 950.0],
        "lemon_count": 1, "inspection_cost": 25.0, "inspections": [], "active_hold": None,
    }
    bid_observation = {"board": [{"listing_id": 0, "rent_asked": 900.0, "status": "OPEN"}],
                       "private_values": [1200.0], "active_hold": None}
    assert complete(request("housing_scripted_tenant_sign_anything_v1", lemons_observation)) == {
        "decision": "pass", "listing_id": None,
    }
    assert complete(request("housing_scripted_tenant_inspect_then_sign_v1", lemons_observation)) == {
        "decision": "inspect", "listing_id": 0,
    }
    assert complete(request("housing_scripted_tenant_v1", bid_observation, phase="contact")) == {
        "decision": "offer", "listing_id": 0, "rent": 901.0,
    }
    with pytest.raises(ProviderFailure, match="model/revision"):
        complete(request("housing_scripted_tenant_v9", lemons_observation))
    with pytest.raises(ProviderFailure, match="model/revision"):
        complete(request("housing_scripted_tenant_v1", bid_observation, revision="2.0.0"))
    with pytest.raises(ProviderFailure, match="lemons world"):
        complete(request("housing_scripted_tenant_v1", lemons_observation, phase="contact"))
    with pytest.raises(ProviderFailure, match="lemons observation"):
        complete(request("housing_scripted_tenant_pass_v1", bid_observation, phase="contact"))
    assert set(LEMONS_SCRIPTED_TENANT_MODELS) == {
        "housing_scripted_tenant_sign_anything_v1",
        "housing_scripted_tenant_inspect_then_sign_v1",
        "housing_scripted_tenant_pass_v1",
    }


def test_smoke_builder_pairs_world_kind_with_the_tenant_policy_and_keeps_bid_ids():
    with pytest.raises(ValueError, match="lemons scripted tenant"):
        build_housing_smoke(tenant_provider="housing_scripted_tenant",
                            tenant_model="housing_scripted_tenant_v1", tenant_revision="1.0.0",
                            world_kind="lemons")
    with pytest.raises(ValueError, match="lemons scripted tenant"):
        build_housing_smoke(tenant_provider="housing_scripted_tenant",
                            tenant_model="housing_scripted_tenant_pass_v1", tenant_revision="1.0.0")
    with pytest.raises(ValueError, match="world_kind"):
        build_housing_smoke(tenant_provider="housing_scripted_tenant",
                            tenant_model="housing_scripted_tenant_v1", tenant_revision="1.0.0",
                            world_kind="attr")
    with pytest.raises(ValueError, match="tenant_max_cost_usd_override"):
        _lemons_setup("pass", tenant_max_cost_usd_override=0.0)
    bid = build_housing_smoke(tenant_provider="housing_scripted_tenant",
                              tenant_model="housing_scripted_tenant_v1", tenant_revision="1.0.0")
    assert bid.plan.suite.suite_id == "housing_smoke_v1"
    assert bid.plan.cases[0].case_id == "housing_v1__smoke__000001"
    assert bid.plan.cases[0].payload["world_kind"] == "bid"
    assert "lemon_share" not in bid.plan.cases[0].payload
    assert bid.plan.families[0].scoring.scorer_id == "housing_outcome_v1"
    assert {pin.component_id for pin in bid.plan.implementation_pins} == {
        "aeread.housing_v1", "housing_outcome_v1", "housing_exact_assignment_v1",
        "housing_feasible_zero_v1", "housing_naive_v1", "housing_generator_v1",
        "minimal_chat", "aeread.shared_runner.housing",
    }


def test_live_route_pins_and_declared_sampling():
    assert GOOGLE_AI_STUDIO_GEMINI_38_FLASH_ROUTE.canonical_model == "google/gemini-3.8-flash-20260902"
    assert XAI_GROK_47_ROUTE.canonical_model == "x-ai/grok-4.7-20260916"
    assert XAI_GROK_47_ROUTE.provider == "xAI" and XAI_GROK_47_ROUTE.quantization == "unknown"
    setup = build_housing_smoke(
        tenant_provider="openrouter", tenant_model="x-ai/grok-4.7",
        tenant_revision=XAI_GROK_47_ROUTE.canonical_model, world_kind="lemons",
        openrouter_route=XAI_GROK_47_ROUTE, tenant_top_p=None, tenant_max_cost_usd_override=0.5,
        world_seeds=(0,), inference_seed_base=87001,
    )
    tenant = next(p for p in setup.plan.agent_profiles if p.model.provider == "openrouter")
    assert tenant.sampling.top_p is None
    assert tenant.budgets.max_cost_usd == 0.5
    assert tenant.prompt.prompt_id == "housing_tenant_lemons_v1"
    assert set(tenant.harness.config["output_schema_by_action_schema"]) == {
        "housing_inspect_v1", "housing_contact_v1", "housing_commit_v1",
    }
    default = build_housing_smoke(tenant_provider="openrouter", tenant_model="deepseek/deepseek-v4-flash-0731",
                                  tenant_revision="deepseek/deepseek-v4-flash-20260731")
    tenant = next(p for p in default.plan.agent_profiles if p.model.provider == "openrouter")
    assert tenant.sampling.top_p == 1.0 and tenant.budgets.max_cost_usd == 0.01


@pytest.mark.parametrize("policy", ["inspect_then_sign", "sign_anything"])
def test_cli_runs_a_lemons_world(tmp_path, policy):
    args = Namespace(provider="scripted", model=None, revision=None, world_seed=0, tenants=3,
                     listings=2, rounds=2, attempt=0, run_root=tmp_path, world_kind="lemons",
                     tenant_policy=policy, route="deepinfra_deepseek")
    result = asyncio.run(_run_cli(args))
    assert result["measurement_status"] == "ok"
    assert result["world_kind"] == "lemons"
    assert result["tenant_model"] == f"housing_scripted_tenant_{policy}_v1"
    assert result["outcome"]["bound_semantics"] == "full_information_tenant_capture_relaxation"


# --------------------------------------------------------------------------
# HL-D-01: under v1 a lemon's landlord accepts a lowball a sound one counters,
# so the reply reveals quality for free; a pooled world closes that channel.
# --------------------------------------------------------------------------


def _lowball_replies(reservation: str) -> set[tuple[str, str]]:
    from aeread_families.housing import environment as hz_env
    from aeread_families.housing import lemons as lemons_mod

    seen = set()
    for seed in range(100000, 100012):
        world = lemons_mod.make_lemons_world(
            6, 4, seed, 0.6, lemon_share=0.5, lemon_loss=1000.0, inspection_cost=25.0,
            landlord_reservation=reservation,
        )
        for listing in range(4):
            market = hz_env.HousingMarket(world, rounds=4)
            offer = hz_env.Offer(
                offer_id=f"o{listing}", tenant_id=0, listing_id=listing,
                rent=round(world.ask[listing] - 300.0, 2), round_index=0,
            )
            reply = hz_env.scripted_landlord_responses(market, {listing: [offer]})[listing][0][0]
            quality = "lemon" if world.quality[listing] == lemons_mod.LEMON else "sound"
            seen.add((quality, reply))
    return seen


def test_true_cost_landlord_reply_reveals_quality() -> None:
    assert _lowball_replies("true_cost") == {("lemon", "accept"), ("sound", "counter")}


def test_pooled_landlord_reply_does_not_reveal_quality() -> None:
    assert _lowball_replies("pooled") == {("lemon", "counter"), ("sound", "counter")}


def test_pooled_world_keeps_true_costs_in_the_accounting() -> None:
    from aeread_families.housing import lemons as lemons_mod

    pooled = lemons_mod.make_lemons_world(6, 4, 100001, 0.6, landlord_reservation="pooled")
    plain = lemons_mod.make_lemons_world(6, 4, 100001, 0.6)
    assert pooled.costs == plain.costs and pooled.values == plain.values
    for listing in pooled.lemon_ids:
        assert pooled.reservation_cost(listing) > pooled.costs[listing]
    for listing in pooled.sound_ids:
        assert pooled.reservation_cost(listing) == pooled.costs[listing]


def test_pooled_landlord_observation_is_opt_in() -> None:
    from aeread_families.housing import environment as hz_env
    from aeread_families.housing import lemons as lemons_mod

    plain = hz_env.HousingMarket(lemons_mod.make_lemons_world(6, 4, 100001, 0.6), rounds=4)
    pooled = hz_env.HousingMarket(
        lemons_mod.make_lemons_world(6, 4, 100001, 0.6, landlord_reservation="pooled"), rounds=4
    )
    assert "reservation_cost" not in plain.landlord_observation(0)
    assert "reservation_cost" in pooled.landlord_observation(0)


def test_v2_identities_pin_route_temperature_and_landlord(tmp_path) -> None:
    import json as _json

    import pytest as _pytest

    from aeread.shared_runner.run.contract import ContractError
    from aeread_families.housing import lemons_campaign as campaign

    for cid in ("housing_lemons_refusal_v2_gemini38_flash", "housing_lemons_refusal_v2_glm53_flash"):
        contract = campaign.load_contract(f"configs/{cid}.json")
        assert contract["environment"]["lemon_landlord"] == "pooled"
        assert contract["controls"]["temperature"] == 1.0
    base = _json.loads(open("configs/housing_lemons_refusal_v2_glm53_flash.json").read())
    for mutate in (
        lambda c: c["controls"].__setitem__("temperature", 0.0),
        lambda c: c["environment"].pop("lemon_landlord"),
        lambda c: c.__setitem__("route", _json.loads(open("configs/housing_lemons_refusal_v2_gemini38_flash.json").read())["route"]),
    ):
        bad = _json.loads(_json.dumps(base))
        mutate(bad)
        path = tmp_path / "bad.json"
        path.write_text(_json.dumps(bad))
        with _pytest.raises(ContractError):
            campaign.load_contract(path)


def test_v2_setup_sends_the_declared_temperature() -> None:
    from aeread_families.housing import lemons_campaign as campaign

    for cid in ("housing_lemons_refusal_v2_gemini38_flash", "housing_lemons_refusal_v2_glm53_flash"):
        contract = campaign.load_contract(f"configs/{cid}.json")
        setup = campaign.build_setup(contract, tenant="live", world_seeds=(100000,), replicates=1)
        tenants = [p for p in setup.plan.agent_profiles if "tenant" in p.profile_id]
        assert tenants and all(p.sampling.temperature == 1.0 for p in tenants)
