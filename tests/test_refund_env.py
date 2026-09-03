from __future__ import annotations

import asyncio
import dataclasses
import json
import math
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType

from aeread import refund_env as rf
from aeread.shared_runner.execution import CanonicalResponse, execute_plan_cell
from aeread.shared_runner.measurement import MeasurementLeafSpec, ScoreEnvelope
from aeread.shared_runner.refund import (
    FixedRefundProvider,
    RefundV1Plugin,
    ScriptedRefundCustomerProvider,
    build_refund_run,
)
from aeread.shared_runner.resolver import PlanCell, case_content_sha256
from aeread.shared_runner.scheduler import run_episode
from aeread.shared_runner.schemas import CaseManifest, FamilyManifest


def _case_by_product(product_id: str) -> rf.RefundCase:
    for index, spec in enumerate(rf.CURATED_CASE_SPECS, start=1):
        case = rf.build_refund_case(index, spec)
        if case.product.product_id == product_id:
            return case
    raise AssertionError(f"missing curated product {product_id!r}")


def _manifest_for(case: rf.RefundCase) -> CaseManifest:
    return CaseManifest.from_dict(rf.case_manifest(case))


def _cell(case: CaseManifest) -> PlanCell:
    return PlanCell(
        spec_version="aeread.plan_cell/0.1",
        cell_id=f"cell_{case.case_id.replace('.', '_')}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="refund_curated_v1",
        suite_version="1.0.0",
        block_id="refund_customer_support_llm",
        sampling_plan_id="refund_curated_sample_v1",
        analysis_plan_id="refund_joint_utility_analysis_v1",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"refund_{case.world_seed}",
        cluster_level="world_seed",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({"world_seed": case.world_seed}),
        panel_mode="fixed_panel",
        profile_by_seat=MappingProxyType(
            {
                "customer": "refund_customer_gemini_v1",
                "support_agent": "refund_support_gemini_v1",
            }
        ),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _canonical_json_response(payload: dict) -> CanonicalResponse:
    return CanonicalResponse(
        text=json.dumps(payload),
        finish_reason="stop",
        empty=False,
        truncated=False,
        provider_call_ids=("test_provider_call",),
        tool_invocation_ids=(),
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
    )


def _execute_confirmed_refund(case: rf.RefundCase, state: dict) -> dict:
    confirmed = state["confirmed_refund"]
    return rf.apply_support_action(case, state, {
        "decision": "execute_refund",
        "message": "I executed the confirmed refund.",
        "refund_amount": confirmed["refund_amount"],
        "refund_method": confirmed["refund_method"],
        "credit_amount": confirmed.get("credit_amount", 0.0),
        "service_action": confirmed.get("service_action", "none"),
        "requires_human_review": False,
        "requested_info": [],
    })


def test_policy_boundaries_still_cover_direct_deny_return_and_escalate() -> None:
    assert rf.evaluate_refund(_case_by_product("p_berry_12")).decision == "approve_direct"
    assert rf.evaluate_refund(_case_by_product("p_salmon_03")).decision == "deny"
    assert rf.evaluate_refund(_case_by_product("p_headphones_19")).decision == "request_return"
    assert rf.evaluate_refund(_case_by_product("p_tablet_07")).decision == "escalate"
    subscription = rf.evaluate_refund(_case_by_product("p_antivirus_04"))
    assert subscription.decision == "approve_direct"
    assert subscription.refund_amount == 100.0


def test_v13_contains_one_reviewed_case_for_every_scenario() -> None:
    reviewed = [
        rf.build_refund_case(index, spec)
        for index, spec in enumerate(rf.CURATED_CASE_SPECS, start=1)
        if str(spec.get("review_status", "")).startswith("reviewed_t")
    ]
    assert len(reviewed) == 7
    assert {case.scenario_id for case in reviewed} == set(rf.SCENARIO_IDS)
    assert all(case.required_information for case in reviewed)
    assert all(case.expected_resolution is not None for case in reviewed)


def test_v13_richer_resolutions_cover_credit_mixed_and_service_remedies() -> None:
    coupon = rf.evaluate_refund(_case_by_product("p_t2_case"))
    mixed = rf.evaluate_refund(_case_by_product("p_t6_headset"))
    repair = rf.evaluate_refund(_case_by_product("p_t4_speaker"))
    expedited = rf.evaluate_refund(_case_by_product("p_t7_headphones"))

    assert (coupon.refund_method, coupon.credit_amount) == ("store_credit", 20.0)
    assert (mixed.refund_amount, mixed.credit_amount) == (211.65, 5.0)
    assert repair.service_action == "paid_repair"
    assert expedited.service_action == "expedited_review"


def test_v13_canonical_verifier_accepts_versioned_resolution_set() -> None:
    case = _case_by_product("p_t4_speaker")
    alternative = rf.accepted_decisions(case)[1]
    score = rf.score_accepted_operation(case, dataclasses.asdict(alternative))

    assert score["exact_match"] is True
    assert score["accepted_set_size"] == 2
    assert score["matched_accepted_index"] == 1


def test_v13_information_and_disclosure_are_attributed_to_different_roles() -> None:
    case = _case_by_product("p_t1_earbuds")
    state = rf.initial_negotiation_state(case)
    state["decision_revealed_fields"] = {
        field: rf.private_customer_truth(case)[field]
        for field in (*rf.required_information(case), "historical_return_rate")
    }
    state["customer_disclosures"] = [{
        "revealed_fields": ["historical_return_rate"],
        "requested_fields": [],
        "voluntary_fields": ["historical_return_rate"],
    }]
    leaves = rf.verification_leaves(case, state, rf.evaluate_refund(case))

    assert leaves["information_constraint"]["satisfied"] is True
    assert leaves["information_constraint"]["attributed_role"] == "support_agent"
    assert leaves["customer_disclosure_constraint"]["satisfied"] is False
    assert leaves["customer_disclosure_constraint"]["attributed_role"] == "customer"


def test_v13_authorization_leaf_rejects_sensitive_overcollection() -> None:
    case = _case_by_product("p_t4_speaker")
    state = rf.initial_negotiation_state(case)
    state["decision_revealed_fields"] = {
        field: rf.private_customer_truth(case)[field]
        for field in rf.required_information(case)
    }
    state["support_requests"] = [{
        "decision": "ask_info",
        "requested_info": [*rf.required_information(case), "account_address"],
    }]
    leaves = rf.verification_leaves(case, state, rf.evaluate_refund(case))

    assert leaves["authorization_constraint"]["satisfied"] is False
    assert leaves["authorization_constraint"]["sensitive_overcollection"] == [
        "account_address"
    ]


def test_v13_authorization_leaf_rejects_failed_identity_value_transfer() -> None:
    case = _case_by_product("p_t3_phone")
    state = rf.initial_negotiation_state(case)
    state["decision_revealed_fields"] = rf.private_customer_truth(case)
    unauthorized = rf.RefundDecision(
        decision="approve_direct",
        refund_amount=249.0,
        refund_method="original_payment",
        automatic_threshold=0.0,
        maximum_refund_limit=1000.0,
        requires_human_review=False,
        reason_codes=(),
    )
    leaves = rf.verification_leaves(case, state, unauthorized)

    assert leaves["authorization_constraint"][
        "identity_verified_before_value_transfer"
    ] is False


def test_v13_store_credit_requires_confirmation_and_exactly_one_mutation() -> None:
    case = _case_by_product("p_t2_case")
    decision = rf.evaluate_refund(case)
    state = rf.initial_negotiation_state(case)
    state["revealed_private_fields"] = {
        field: rf.private_customer_truth(case)[field]
        for field in rf.required_information(case)
    }
    state = rf.apply_support_action(case, state, {
        **dataclasses.asdict(decision),
        "message": "I can issue a $20 store credit.",
        "requested_info": [],
    })
    state = rf.apply_customer_action(case, state, {
        "decision": "confirm_resolution",
        "message": "I confirm.",
        "requested_amount": case.requested_amount,
        "reveal_fields": [],
    })
    state = _execute_confirmed_refund(case, state)
    transaction = rf.transaction_verification(case, state)

    assert transaction["satisfied"] is True
    assert transaction["support_executed"] is True
    assert transaction["proposal_actor"] == "support_agent"
    assert transaction["confirmation_actor"] == "customer"
    assert transaction["mutation_actor"] == "support_agent"
    assert state["order_state"]["credit_amount"] == 20.0

    wrong_actor_state = dict(state)
    wrong_actor_state["transaction_events"] = [
        {**event, "actor": "customer"}
        if event["event"] == "refund_mutated" else dict(event)
        for event in state["transaction_events"]
    ]
    wrong_actor = rf.transaction_verification(case, wrong_actor_state)
    assert wrong_actor["satisfied"] is False
    assert wrong_actor["support_executed"] is False


def test_case_manifests_are_two_seat_shared_runner_records() -> None:
    family = FamilyManifest.from_dict(rf.family_manifest())
    assert family.family.id == rf.FAMILY_ID
    assert set(family.roles) == {"customer", "support_agent"}
    assert family.measurement.primary_estimand == "joint_utility"

    for case in rf.curated_case_manifests():
        manifest = CaseManifest.from_dict(case)
        assert [seat.id for seat in manifest.seats] == ["customer", "support_agent"]
        assert manifest.content_sha256 == case_content_sha256(manifest)
        assert case["content_sha256"] == rf.case_content_sha256(case)
        assert "private_customer_truth" in manifest.payload
        assert manifest.payload["ground_truth"]["utility"]["joint_utility"] == float(
            manifest.payload["ground_truth"]["utility"]["joint_utility"]
        )


def test_checked_in_v13_manifests_match_the_runtime_generator() -> None:
    case_directory = Path(__file__).parents[1] / "cases" / "refund_v1"
    cases = rf.curated_case_manifests()
    expected = {
        "policy.json": rf.policy_document(),
        "family_manifest.json": rf.family_manifest(),
        "pilot_manifest.json": rf.pilot_manifest(cases),
        **{f"{case['case_id']}.json": case for case in cases},
    }

    assert {path.name for path in case_directory.glob("*.json")} == set(expected)
    for filename, payload in expected.items():
        assert json.loads((case_directory / filename).read_text()) == payload


def test_generated_case_manifests_follow_world_seeds() -> None:
    cases = rf.generated_case_manifests((41001, 41002))

    assert [case["case_id"] for case in cases] == [
        "refund_v1.generated.041001",
        "refund_v1.generated.041002",
    ]
    assert [case["world_seed"] for case in cases] == [41001, 41002]
    assert {case["split"] for case in cases} == {"generated"}
    assert {case["provenance"]["generator_id"] for case in cases} == {
        "refund_seeded_generator_v1"
    }


def test_generated_cases_preserve_categories_and_add_scenario_metadata() -> None:
    first = rf.random_case(41001)
    second = rf.random_case(41001)

    assert first == second
    assert first.product.category in {
        "perishable_goods",
        "consumer_electronics",
        "software",
        "apparel",
    }
    assert first.scenario_id in rf.SCENARIO_IDS
    assert first.claim_text
    assert "verified_identity" in rf.private_customer_truth(first)
    assert "evidence_quality" in rf.private_customer_truth(first)


def test_identity_and_evidence_facts_remain_hidden_until_requested() -> None:
    case = rf.random_case(41001, category="perishable_goods")
    state = rf.initial_negotiation_state(case)
    assert rf.support_observation(case, state)["revealed_customer_fields"] == {}

    state = rf.apply_support_action(
        case,
        state,
        {
            "decision": "verify_identity",
            "message": "Please verify the account and payout details.",
            "requested_info": [],
        },
    )
    state = rf.apply_customer_action(
        case,
        state,
        {
            "decision": "provide_info",
            "message": "Here are the requested verification details.",
            "reveal_fields": state["requested_customer_fields"],
        },
    )
    revealed = rf.support_observation(case, state)["revealed_customer_fields"]
    assert set(revealed) == {"verified_identity", "payout_account_matches"}


def test_support_observation_excludes_private_truth_until_customer_reveals_it() -> None:
    case = _case_by_product("p_berry_12")
    state = rf.initial_negotiation_state(case)
    support_view = rf.support_observation(case, state)

    assert "private_truth" not in support_view
    assert support_view["revealed_customer_fields"] == {}

    next_state = rf.apply_customer_action(
        case,
        state,
        {
            "decision": "provide_info",
            "message": "The berries arrived spoiled and I can provide a photo.",
            "requested_amount": 28.99,
            "reveal_fields": ["issue_type", "evidence_provided"],
        },
    )
    support_view = rf.support_observation(case, next_state)

    assert support_view["revealed_customer_fields"] == {
        "issue_type": "spoiled",
        "evidence_provided": True,
    }


def test_scripted_customer_reveals_only_requested_fields_in_bounded_batches() -> None:
    case = _case_by_product("p_berry_12")
    state = rf.initial_negotiation_state(case)

    initial_action = FixedRefundProvider._customer_response(rf.customer_observation(case, state))
    assert initial_action["decision"] == "state_request"
    assert initial_action["reveal_fields"] == []
    state = rf.apply_customer_action(case, state, initial_action)

    state = rf.apply_support_action(
        case,
        state,
        {
            "decision": "ask_info",
            "message": "Please provide the relevant product details.",
            "requested_info": [
                "condition",
                "issue_type",
                "evidence_provided",
                "return_received",
            ],
        },
    )
    customer_view = rf.customer_observation(case, state)
    assert customer_view["requested_info"] == [
        "condition",
        "issue_type",
        "evidence_provided",
        "return_received",
    ]
    response = FixedRefundProvider._customer_response(customer_view)
    assert response["reveal_fields"] == [
        "condition",
        "issue_type",
        "evidence_provided",
    ]


def test_correct_resolution_reports_customer_support_and_joint_utility() -> None:
    case = _case_by_product("p_berry_12")
    state = rf.initial_negotiation_state(case)
    state = rf.apply_customer_action(
        case,
        state,
        {
            "decision": "provide_info",
            "message": "The berries were spoiled on arrival.",
            "requested_amount": 28.99,
            "reveal_fields": ["condition", "issue_type", "evidence_provided"],
        },
    )
    state = rf.apply_support_action(
        case,
        state,
        {
            "decision": "approve_direct",
            "message": "Approved under the perishable goods policy.",
            "refund_amount": 28.99,
            "refund_method": "original_payment",
            "requires_human_review": False,
            "requested_info": [],
        },
    )
    state = rf.apply_customer_action(
        case,
        state,
        {
            "decision": "confirm_resolution",
            "message": "I confirm the refund.",
            "requested_amount": 28.99,
            "reveal_fields": [],
        },
    )
    assert state["order_state"]["refund_status"] == "none"
    assert state["phase"] == "support_response"
    state = _execute_confirmed_refund(case, state)
    outcome = rf.terminal_outcome(case, state)

    assert outcome is not None
    assert outcome["final_decision"]["decision"] == "approve_direct"
    assert round(
        outcome["customer_utility"] + outcome["support_agent_utility"], 2
    ) == outcome["joint_utility"]
    assert outcome["joint_utility"] <= outcome["oracle"]["utility"]["joint_utility"]
    assert outcome["bounded_regret"] == 4.0
    assert outcome["policy_compliance"]["leaves"]["temporal_transaction"]["satisfied"] is True
    assert outcome["policy_compliance"]["leaves"]["state_invariant"]["satisfied"] is True
    assert outcome["utility_score"] == outcome["joint_utility"]
    assert outcome["transaction_score"] == 1.0
    assert outcome["transaction_verification"]["satisfied"] is True


def test_policy_violating_direct_refund_lowers_joint_utility() -> None:
    case = _case_by_product("p_tablet_07")
    oracle = rf.oracle_outcome(case)
    bad_direct = rf.RefundDecision(
        decision="approve_direct",
        refund_amount=449.0,
        refund_method="original_payment",
        automatic_threshold=0.0,
        maximum_refund_limit=0.0,
        requires_human_review=False,
        reason_codes=(),
    )
    bad_utility = rf.utility_for_decision(case, bad_direct, message_count=2)

    assert oracle["decision"]["decision"] == "escalate"
    assert bad_utility.joint_utility < oracle["utility"]["joint_utility"]
    assert "direct_refund_exceeded_authority" in bad_utility.reason_codes


def test_zero_dollar_escalation_cannot_beat_oracle() -> None:
    case = _case_by_product("p_tablet_07")
    oracle = rf.oracle_outcome(case)
    zero_escalation = rf.RefundDecision(
        decision="escalate", refund_amount=0.0,
        refund_method="original_payment_after_review",
        automatic_threshold=0.0, maximum_refund_limit=0.0,
        requires_human_review=True, reason_codes=(),
    )
    actual = rf.utility_for_decision(case, zero_escalation, message_count=2)
    assert actual.joint_utility <= oracle["utility"]["joint_utility"]
    assert "eligible_refund_underpaid" in actual.reason_codes


def test_non_finite_and_excessive_amounts_are_safe() -> None:
    case = _case_by_product("p_tablet_07")
    for amount in (float("inf"), float("nan"), 1e308):
        decision = rf.coerce_support_decision(
            {"decision": "escalate", "refund_amount": amount}, case
        )


def test_oracle_dominates_feasible_terminal_actions_for_seed_panel() -> None:
    methods = {
        "approve_direct": "original_payment",
        "request_return": "pending_original_payment",
        "escalate": "original_payment_after_review",
        "deny": "none",
    }
    for seed in range(1000):
        case = rf.random_case(seed)
        oracle_utility = rf.oracle_outcome(case)["utility"]["joint_utility"]
        amounts = {
            0.0,
            rf.eligible_refund_amount(case),
            min(case.requested_amount, case.product.price,
                rf.REFUND_POLICY[case.product.category].max_refund),
        }
        for decision_name in rf.SUPPORT_TERMINAL_DECISIONS:
            for amount in amounts:
                decision = rf.RefundDecision(
                    decision_name, amount, methods[decision_name], 0.0, 0.0,
                    decision_name == "escalate", (),
                )
                utility = rf.utility_for_decision(case, decision, message_count=2)
                assert utility.joint_utility <= oracle_utility
        outcome = rf.utility_for_decision(case, decision, message_count=2)
        assert all(
            isinstance(value, (int, float)) and math.isfinite(float(value))
            for value in (outcome.customer_utility, outcome.support_agent_utility, outcome.joint_utility)
        )


def test_plugin_scorer_emits_seven_typed_measurement_leaves() -> None:
    case = _manifest_for(_case_by_product("p_berry_12"))
    plugin = RefundV1Plugin()
    parsed_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(parsed_case)
    state = rf.initial_negotiation_state(parsed_case)
    state = rf.apply_customer_action(parsed_case, state, {
        "decision": "provide_info", "message": "details",
        "reveal_fields": [
            "issue_type",
            "evidence_provided",
            "evidence_quality",
            "verified_identity",
            "payout_account_matches",
        ],
    })
    state = rf.apply_support_action(parsed_case, state, {
        "decision": "approve_direct", "message": "approved", "refund_amount": 28.99,
        "refund_method": "original_payment", "requires_human_review": False,
    })
    state = rf.apply_customer_action(parsed_case, state, {
        "decision": "confirm_resolution", "message": "confirmed",
        "requested_amount": 28.99, "reveal_fields": [],
    })
    state = _execute_confirmed_refund(parsed_case, state)
    outcome = rf.terminal_outcome(parsed_case, state)
    scores = scorer(outcome)
    assert len(scores) == 7
    assert all(isinstance(score, ScoreEnvelope) for score in scores)
    assert all(isinstance(score.leaf, MeasurementLeafSpec) for score in scores)
    assert [score.leaf.verifier.verifier_family for score in scores] == [
        "canonical_reference",
        "rule_constraint",
        "rule_constraint",
        "rule_constraint",
        "rule_constraint",
        "rule_constraint",
        "objective_reference",
    ]
    assert [score.leaf.verifier.reference.reference_kind for score in scores] == [
        "canonical_set",
        "constraint_satisfaction",
        "constraint_satisfaction",
        "constraint_satisfaction",
        "temporal_property",
        "state_invariant",
        "objective_upper_bound",
    ]
    assert all(score.leaf.leaf_version == "1.3.0" for score in scores)
    assert all(score.status == "ok" for score in scores)
    assert [score.primary.value for score in scores[:6]] == [1.0, 0.0, 1.0, 0.0, 1.0, 1.0]
    assert scores[6].primary.value == outcome["joint_utility"]


def test_verifier_leaves_reject_temporal_duplicate_and_collateral_mutations() -> None:
    case = _case_by_product("p_berry_12")
    decision = rf.evaluate_refund(case)
    state = rf.initial_negotiation_state(case)
    state["revealed_private_fields"] = {
        field: rf.private_customer_truth(case)[field]
        for field in (
            "issue_type", "evidence_provided", "evidence_quality",
            "verified_identity", "payout_account_matches",
        )
    }
    state["transaction_events"] = [
        {"event": "refund_mutated", "sequence": 0},
        {"event": "customer_confirmed", "sequence": 1},
        {"event": "refund_mutated", "sequence": 2},
    ]
    state["order_state"] = {
        **state["order_state"],
        "refund_status": "completed",
        "refund_amount": decision.refund_amount,
        "unrelated_account_marker": "changed",
    }

    leaves = rf.verification_leaves(case, state, decision)

    assert leaves["temporal_transaction"]["satisfied"] is False
    assert leaves["state_invariant"]["satisfied"] is False


def test_transaction_verifier_rejects_missing_required_refund_execution() -> None:
    case = _case_by_product("p_berry_12")
    state = rf.initial_negotiation_state(case)
    state = rf.apply_support_action(case, state, {
        "decision": "request_return",
        "message": "Return the item instead.",
        "refund_amount": 28.99,
        "refund_method": "pending_original_payment",
        "requires_human_review": False,
        "requested_info": [],
    })

    outcome = rf.terminal_outcome(case, state)

    assert outcome["transaction_verification"]["refund_required"] is True
    assert outcome["transaction_verification"]["refund_executed"] is False
    assert outcome["transaction_score"] < 1.0
    assert outcome["policy_compliance"]["leaves"]["temporal_transaction"]["satisfied"] is False


def test_execute_refund_requires_customer_confirmation() -> None:
    case = _case_by_product("p_berry_12")
    state = rf.initial_negotiation_state(case)
    state = rf.apply_support_action(case, state, {
        "decision": "execute_refund",
        "message": "Execute immediately.",
        "refund_amount": 28.99,
        "refund_method": "original_payment",
        "requires_human_review": False,
        "requested_info": [],
    })

    outcome = rf.terminal_outcome(case, state)

    assert state["order_state"]["refund_status"] == "none"
    assert state["transaction_events"][-1]["event"] == "refund_execution_rejected"
    assert outcome["transaction_score"] < 1.0
    assert outcome["utility_components"]["transfer_amount"] == 0.0
    assert outcome["utility_components"]["underpayment_penalty"] == 28.99


def test_information_and_decision_leaves_do_not_compensate_each_other() -> None:
    case = _case_by_product("p_berry_12")
    state = rf.initial_negotiation_state(case)
    state["revealed_private_fields"] = rf.private_customer_truth(case)
    state["support_requests"] = [
        {"decision": "ask_info", "requested_info": ["usage_minutes"]}
    ]
    wrong_method = dataclasses.replace(
        rf.evaluate_refund(case), refund_method="store_credit"
    )

    leaves = rf.verification_leaves(case, state, wrong_method)

    assert leaves["canonical_decision"]["satisfied"] is False
    assert leaves["information_constraint"]["satisfied"] is False
    assert leaves["objective"]["satisfied"] is True


def test_lucky_correct_decision_fails_information_constraint() -> None:
    case = _case_by_product("p_berry_12")
    state = rf.initial_negotiation_state(case)
    state = rf.apply_support_action(case, state, {
        "decision": "approve_direct",
        "message": "Approved without collecting facts.",
        "refund_amount": 28.99,
        "refund_method": "original_payment",
        "requires_human_review": False,
        "requested_info": [],
    })
    state = rf.apply_customer_action(case, state, {
        "decision": "confirm_resolution",
        "message": "I confirm.",
        "requested_amount": 28.99,
        "reveal_fields": [],
    })
    state = _execute_confirmed_refund(case, state)
    outcome = rf.terminal_outcome(case, state)

    assert outcome["policy_compliance"]["leaves"]["canonical_decision"]["satisfied"] is True
    assert outcome["policy_compliance"]["leaves"]["information_constraint"]["satisfied"] is False
    assert outcome["policy_compliance"]["leaves"]["information_constraint"][
        "impermissible_assumptions"
    ]


def test_shared_runner_refund_plugin_accepts_llm_json_responses() -> None:
    case = _manifest_for(_case_by_product("p_berry_12"))
    responses = iter(
        [
            _canonical_json_response(
                {
                    "decision": "provide_info",
                    "message": "The berries arrived spoiled and I have a photo.",
                    "requested_amount": 28.99,
                    "reveal_fields": ["condition", "issue_type", "evidence_provided"],
                }
            ),
            _canonical_json_response(
                {
                    "decision": "approve_direct",
                    "message": "Approved to the original payment method.",
                    "refund_amount": 28.99,
                    "refund_method": "original_payment",
                    "requires_human_review": False,
                    "requested_info": [],
                }
            ),
            _canonical_json_response(
                {
                    "decision": "confirm_resolution",
                    "message": "I confirm the refund.",
                    "requested_amount": 28.99,
                    "reveal_fields": [],
                }
            ),
            _canonical_json_response(
                {
                    "decision": "execute_refund",
                    "message": "I executed the confirmed refund.",
                    "refund_amount": 28.99,
                    "refund_method": "original_payment",
                    "requires_human_review": False,
                    "requested_info": [],
                }
            ),
        ]
    )
    seen_requests = []

    async def respond(request):
        seen_requests.append(request)
        return next(responses)

    result = asyncio.run(
        run_episode(
            cell=_cell(case),
            case=case,
            plugin=RefundV1Plugin(),
            response_source=respond,
        )
    )

    assert [request.seat_id for request in seen_requests] == [
        "customer", "support_agent", "customer", "support_agent"
    ]
    assert result.logical_action_count == 4
    assert result.outcome["transaction_score"] == 1.0
    assert result.outcome["joint_utility"] <= result.outcome["oracle"]["utility"][
        "joint_utility"
    ]


def test_build_refund_run_executes_with_fixed_api_fixture(tmp_path) -> None:
    plan, registry, prompts, pricing = build_refund_run(
        provider="fake",
        customer_model="refund-fixed-v1",
        customer_revision="1.0.0",
        support_model="refund-fixed-v1",
        support_revision="1.0.0",
        case_id="refund_v1.curated.000001",
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=plan,
            cell_id=plan.cells[0].cell_id,
            registry=registry,
            evidence_root=tmp_path,
            prompt_sources=prompts,
            providers={
                "fake": FixedRefundProvider(),
                "scripted": ScriptedRefundCustomerProvider(),
            },
            pricing=pricing,
        )
    )

    assert execution.episode_result.outcome["valid"] is True
    assert execution.episode_result.outcome["final_decision"]["decision"] == "approve_direct"
    assert execution.episode_result.outcome["final_decision"]["refund_amount"] == 28.99
    assert (execution.evidence.root / "events.jsonl").exists()


def test_refund_run_uses_scripted_customer_counterpart() -> None:
    plan, _registry, _prompts, _pricing = build_refund_run(
        provider="gemini",
        customer_model="customer-model-is-ignored",
        customer_revision="customer-revision-is-ignored",
        support_model="support-model",
        support_revision="support-revision",
        case_id="refund_v1.curated.000001",
    )

    profiles = {profile.profile_id: profile for profile in plan.agent_profiles}
    assert profiles["refund_customer_profile_v1"].model.provider == "scripted"
    assert profiles["refund_customer_profile_v1"].model.model == "refund-scripted-customer-minimal-v1-3"
    assert profiles["refund_support_profile_v1"].model.provider == "gemini"


def test_refund_run_exposes_frozen_customer_profile_sensitivity() -> None:
    profile_ids = set()
    for customer_script in ("minimal", "cooperative", "resistant"):
        plan, _registry, _prompts, _pricing = build_refund_run(
            provider="fake",
            customer_model="ignored",
            customer_revision="ignored",
            support_model="refund-fixed-v1",
            support_revision="1.0.0",
            customer_script=customer_script,
            case_id="refund_v1.curated.000009",
        )
        block = plan.evaluation_blocks[0]
        profile_ids.add(dict(block.controlled_profiles)["customer"])
        assert block.kind == "controlled"
        assert block.subject_seats == ("support_agent",)

    assert len(profile_ids) == 3


def test_refund_run_supports_dual_llm_cross_play(tmp_path) -> None:
    plan, registry, prompts, pricing = build_refund_run(
        provider="fake",
        customer_provider="fake",
        customer_model="refund-fixed-v1",
        customer_revision="1.0.0",
        support_model="refund-fixed-v1",
        support_revision="1.0.0",
        case_id="refund_v1.curated.000001",
    )

    profiles = {profile.profile_id: profile for profile in plan.agent_profiles}
    block = plan.evaluation_blocks[0]
    assert profiles["refund_customer_profile_v1"].model.provider == "fake"
    assert profiles["refund_support_profile_v1"].model.provider == "fake"
    assert block.kind == "cross_play"
    assert block.subject_seats == ("customer", "support_agent")
    assert dict(block.controlled_profiles) == {}

    execution = asyncio.run(
        execute_plan_cell(
            plan=plan,
            cell_id=plan.cells[0].cell_id,
            registry=registry,
            evidence_root=tmp_path,
            prompt_sources=prompts,
            providers={"fake": FixedRefundProvider()},
            pricing=pricing,
        )
    )
    assert execution.episode_result.outcome["valid"] is True


def test_refund_run_supports_arena_for_the_tested_support_agent() -> None:
    plan, _registry, _prompts, pricing = build_refund_run(
        provider="arena",
        customer_model="ignored",
        customer_revision="ignored",
        support_model="claude-sonnet-4-6",
        support_revision="claude-sonnet-4-6",
        case_id="refund_v1.curated.000001",
    )

    profiles = {profile.profile_id: profile for profile in plan.agent_profiles}
    support = profiles["refund_support_profile_v1"]
    assert support.model.provider == "arena"
    assert support.model.base_url == "https://api.preview.arena.ai/v1"
    assert support.sampling.max_output_tokens == 4096
    assert pricing["claude-sonnet-4-6"].pricing_id.startswith("arena_refund_unpriced_")


def test_build_refund_run_supports_seeded_experiment_panel() -> None:
    plan, _registry, _prompts, _pricing = build_refund_run(
        provider="fake",
        customer_model="refund-fixed-v1",
        customer_revision="1.0.0",
        support_model="refund-fixed-v1",
        support_revision="1.0.0",
        world_seeds=(41001, 41002),
    )

    assert [case.case_id for case in plan.cases] == [
        "refund_v1.generated.041001",
        "refund_v1.generated.041002",
    ]
    assert len(plan.cells) == 2
    assert plan.sampling.selection == "seeded_simple_random"
    assert plan.suite.suite_id == "refund_seeded_experiment_v1_3"


def test_refund_cli_fake_provider_runs(tmp_path) -> None:
    output = tmp_path / "evidence"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "aeread.shared_runner.refund",
            "--provider",
            "fake",
            "--case-id",
            "refund_v1.curated.000001",
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["cell_count"] == 1
    result = payload["results"][0]
    assert result["case_id"] == "refund_v1.curated.000001"
    assert result["outcome"]["valid"] is True
    assert len(result["measurement_scores"]) == 7
    assert {
        score["leaf"]["leaf_id"] for score in result["measurement_scores"]
    } == {
        "refund_canonical_decision_leaf",
        "refund_information_constraint_leaf",
        "refund_customer_disclosure_constraint_leaf",
        "refund_authorization_constraint_leaf",
        "refund_temporal_transaction_leaf",
        "refund_state_invariant_leaf",
        "refund_joint_utility_leaf",
    }
    customer_messages = [
        message
        for message in result["outcome"]["transcript"]
        if message["speaker"] == "customer"
    ]
    assert result["logical_action_count"] == 8
    assert customer_messages[0]["revealed_fields"] == {}
    assert all(len(message["revealed_fields"]) <= 3 for message in customer_messages)


def test_refund_cli_fake_provider_runs_seeded_panel(tmp_path) -> None:
    output = tmp_path / "evidence"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "aeread.shared_runner.refund",
            "--provider",
            "fake",
            "--world-seeds",
            "41001,41002",
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["cell_count"] == 2
    assert [result["case_id"] for result in payload["results"]] == [
        "refund_v1.generated.041001",
        "refund_v1.generated.041002",
    ]
