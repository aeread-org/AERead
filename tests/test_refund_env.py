from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from types import MappingProxyType

from aeread import refund_env as rf
from aeread.shared_runner.execution import CanonicalResponse, execute_plan_cell
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


def test_policy_boundaries_still_cover_direct_deny_return_and_escalate() -> None:
    assert rf.evaluate_refund(_case_by_product("p_berry_12")).decision == "approve_direct"
    assert rf.evaluate_refund(_case_by_product("p_salmon_03")).decision == "deny"
    assert rf.evaluate_refund(_case_by_product("p_headphones_19")).decision == "request_return"
    assert rf.evaluate_refund(_case_by_product("p_tablet_07")).decision == "escalate"
    subscription = rf.evaluate_refund(_case_by_product("p_antivirus_04"))
    assert subscription.decision == "approve_direct"
    assert subscription.refund_amount == 100.0


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
    outcome = rf.terminal_outcome(case, state)

    assert outcome is not None
    assert outcome["final_decision"]["decision"] == "approve_direct"
    assert round(
        outcome["customer_utility"] + outcome["support_agent_utility"], 2
    ) == outcome["joint_utility"]
    assert outcome["joint_utility"] == outcome["oracle"]["utility"]["joint_utility"]


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

    assert [request.seat_id for request in seen_requests] == ["customer", "support_agent"]
    assert result.logical_action_count == 2
    assert result.outcome["joint_utility"] == result.outcome["oracle"]["utility"][
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
    assert profiles["refund_customer_profile_v1"].model.model == "refund-scripted-customer-v1"
    assert profiles["refund_support_profile_v1"].model.provider == "gemini"


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
    assert plan.suite.suite_id == "refund_seeded_experiment_v1"


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
