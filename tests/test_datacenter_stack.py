from __future__ import annotations

import asyncio
import dataclasses

import pytest

from aeread.shared_runner.execution import TokenPricing
from aeread.shared_runner.resolver import canonical_json_bytes
from aeread.shared_runner.scheduler import (
    ActionEnvelope,
    LegalityResult,
    ParseResult,
)
from aeread_families.datacenter_development.contracts import (
    ContractSignature,
    ContractValidationError,
    LandAgreement,
    apply_executed_amendment,
    execute_offer,
    make_offer,
)
from aeread_families.datacenter_development.stack_environment import (
    DataCenterStackPlugin,
)
from aeread_families.datacenter_development.stack_runner import (
    build_stack_openrouter_setup,
    finalize_stack_execution,
    load_stack_case,
    replay_stack_receipt,
    run_stack_offline,
    stack_developer_output_schemas,
)
from aeread_families.procurement_grounding import OpenRouterRoute


GLM_ROUTE = OpenRouterRoute(
    profile_id="datacenter_glm53_flash_v1",
    model="z-ai/glm-5.3-flash",
    revision="z-ai/glm-5.3-flash-20260826",
    route_provider="DeepInfra",
    quantization="fp8",
    pricing=TokenPricing(
        input_per_million=0.075,
        cached_input_per_million=0.015,
        output_per_million=0.25,
        pricing_id="datacenter_test_glm53_flash_deepinfra",
    ),
    max_prompt_price_per_million="0.075",
    max_completion_price_per_million="0.25",
    reasoning_effort="low",
)


def _land(*, expiry: int) -> LandAgreement:
    return LandAgreement(
        site_control_start_month=1,
        closing_month=1,
        site_control_expiry_month=expiry,
        purchase_price_cents=20_000,
        extension_option_months=2,
        extension_price_cents=5_000,
        permitted_use_capacity_kw=1_000,
        conditions_precedent=("zoning_approval",),
    )


def _execute_land(offer):
    return execute_offer(
        offer,
        (
            ContractSignature(offer.offer_id, "developer"),
            ContractSignature(offer.offer_id, "landowner"),
        ),
        required_signers=("developer", "landowner"),
    )


def test_land_amendment_requires_exact_superseded_offer_and_changed_fields() -> None:
    prior_offer = make_offer(
        case_id="datacenter_v2_case_001",
        agreement_type="land",
        proposer_seat_id="developer",
        round_index=0,
        message="Initial site-control agreement.",
        terms=_land(expiry=3),
    )
    prior = _execute_land(prior_offer)
    amendment_offer = make_offer(
        case_id="datacenter_v2_case_001",
        agreement_type="land",
        proposer_seat_id="developer",
        round_index=0,
        message="Extend site control through COD.",
        terms=_land(expiry=4),
        supersedes_offer_id=prior.offer_id,
        amended_fields=("site_control_expiry_month",),
        precedence_index=1,
    )
    amendment = _execute_land(amendment_offer)

    assert apply_executed_amendment(prior, amendment) == amendment

    wrong_fields = dataclasses.replace(
        amendment,
        amended_fields=("extension_option_months",),
        offer_id=make_offer(
            case_id="datacenter_v2_case_001",
            agreement_type="land",
            proposer_seat_id="developer",
            round_index=0,
            message="Incorrect field declaration.",
            terms=_land(expiry=4),
            supersedes_offer_id=prior.offer_id,
            amended_fields=("extension_option_months",),
            precedence_index=1,
        ).offer_id,
    )
    with pytest.raises(ContractValidationError, match="exactly match"):
        apply_executed_amendment(prior, wrong_fields)


@pytest.mark.parametrize(
    ("scope", "family_version", "expected_actions", "developer_npv", "total_npv"),
    (
        ("v1", "1.1.0", 12, -50_000, 150_000),
        ("v2", "2.0.0", 18, -155_000, -55_000),
    ),
)
def test_versioned_cases_validate_execute_seal_and_replay(
    tmp_path, scope, family_version, expected_actions, developer_npv, total_npv
) -> None:
    case = load_stack_case(scope)
    assert case.family_version == family_version
    DataCenterStackPlugin(scope).validate_payload(case.payload)

    evidence_root = tmp_path / scope
    setup, execution = asyncio.run(
        run_stack_offline(scope, evidence_root=evidence_root)
    )
    outcome = execution.episode_result.outcome

    assert execution.episode_result.logical_action_count == expected_actions
    assert execution.total_cost_usd == 0.0
    assert outcome["project_completed"] is True
    assert outcome["binding_contract_integrity"] is True
    assert outcome["project_constraints_satisfied"] is True
    assert outcome["developer_equity_npv_cents"] == developer_npv
    assert outcome["total_project_npv_cents"] == total_npv

    receipt = finalize_stack_execution(setup=setup, execution=execution)
    score_by_id = {score.leaf.leaf_id: score for score in receipt.scores}
    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"
    assert len(receipt.scores) == 5
    assert score_by_id["binding_contract_integrity"].primary.value == 1.0
    assert score_by_id["project_constraint_satisfaction"].primary.value == 1.0
    assert score_by_id["negotiation_temporal_compliance"].primary.value == 1.0
    assert replay_stack_receipt(
        setup=setup, receipt=receipt, evidence_root=evidence_root
    ) == receipt

    if scope == "v2":
        assert outcome["amendment_precedence_valid"] is True
        adjustments = outcome["project_outcome"]["adjustments"]
        assert adjustments["site_control_valid_through_cod"] is True
        assert adjustments["land_extension_exercised"] is False
        amendment_offer = next(
            row
            for row in outcome["public_history"]
            if row.get("agreement_key") == "land_amendment"
            and row["decision"] == "offer"
        )
        assert amendment_offer["supersedes_offer_id"].startswith("offer_")
        assert tuple(amendment_offer["amended_fields"]) == (
            "site_control_expiry_month",
        )


def test_v2_developer_observation_excludes_every_private_policy() -> None:
    case = load_stack_case("v2")
    plugin = DataCenterStackPlugin("v2")
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, run=None)
    phase = plugin.phases(family_case)[0]

    observation = plugin.observe(family_case, state, "developer", phase)
    serialized = repr(observation)

    assert "private_policy" not in serialized
    assert "policies" not in serialized
    assert "scripted_developer" not in serialized
    assert "baseline" not in serialized
    assert "outside_option" not in serialized
    assert "customer_usage_kw_by_month" not in serialized
    assert "customer_value_cents_per_kw_month" not in serialized


def test_final_round_counter_terminates_as_valid_outside_option() -> None:
    case = load_stack_case("v1")
    plugin = DataCenterStackPlugin("v1")
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, run=None)
    state["rounds"]["power"] = family_case["negotiation"]["max_rounds"][
        "power"
    ]
    phase = next(
        item
        for item in plugin.phases(family_case)
        if item.phase_id == "power_utility_response"
    )
    action = {
        "decision": "counter",
        "offer_id": "offer_final_round",
        "message": "Final controlled counteroffer.",
        "terms": family_case["policies"]["power"]["counter_terms"],
    }
    transition = plugin.step(
        family_case,
        state,
        phase,
        {
            "utility": ActionEnvelope(
                seat_id="utility",
                valid=True,
                action=action,
                parse=ParseResult.success(action),
                legality=LegalityResult.legal_action(),
            )
        },
    )
    outcome = plugin.outcome(family_case, plugin.terminal(family_case, transition.state))

    assert transition.next_phase_id is None
    assert transition.state["finished"] is True
    assert transition.state["termination_reason"] == (
        "power_negotiation_rounds_exhausted"
    )
    assert outcome["project_completed"] is False
    assert outcome["temporal_violations"] == []
    assert outcome["developer_equity_npv_cents"] == family_case[
        "outside_option"
    ]["developer_equity_npv_cents"]


@pytest.mark.parametrize(("scope", "schema_count"), (("v1", 8), ("v2", 12)))
def test_live_stack_plan_admits_glm_with_every_phase_schema(
    scope: str, schema_count: int
) -> None:
    setup = build_stack_openrouter_setup(
        scope, GLM_ROUTE, seed=20260831
    )
    schemas = stack_developer_output_schemas(setup.case)
    developer_profile_id = setup.plan.cells[0].profile_by_seat["developer"]
    developer_profile = next(
        profile
        for profile in setup.plan.agent_profiles
        if profile.profile_id == developer_profile_id
    )

    assert developer_profile.model.provider == "openrouter"
    assert len(schemas) == schema_count
    assert canonical_json_bytes(
        developer_profile.harness.config["output_schema_by_action_schema"]
    ) == canonical_json_bytes(schemas)
    assert all(admission.admitted for admission in setup.plan.profile_admissions)
    assert {
        profile.model.provider
        for profile in setup.plan.agent_profiles
        if profile.profile_id != developer_profile_id
    } == {
        f"datacenter_stack_scripted_{seat}"
        for seat in setup.plan.cells[0].profile_by_seat
        if seat != "developer"
    }
