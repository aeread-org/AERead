from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from pathlib import Path

import pytest

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner import canonical_json_bytes
from aeread.shared_runner.task.execution import TokenPricing
from aeread.shared_runner.run.resolver import case_content_sha256
import aeread_families.procurement_allocation.environment as environment_module
from aeread_families.procurement_allocation import (
    ProcurementAllocationPlugin,
    build_offline_setup,
    build_openrouter_setup,
    evaluate_award,
    finalize_procurement_allocation_execution,
    load_case,
    procurement_action_output_schema,
    replay_procurement_allocation_receipt,
    run_fixture_script,
    solve_full_information_upper_bound,
)
from aeread_families.procurement_grounding import OpenRouterRoute


def _plain(value):
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _response(action: dict) -> str:
    return json.dumps(action, sort_keys=True)


def _optimal_script() -> list[str]:
    negotiated_terms = {
        "switch_reliable": (0.082, 30),
        "oled_reliable": (1.72, 45),
        "charger_reliable": (0.55, 45),
    }
    actions: list[dict] = []
    for supplier_id, (unit_price, refund_window) in negotiated_terms.items():
        actions.extend(
            [
                {
                    "action": "request_quote",
                    "supplier_id": supplier_id,
                    "message": "Please issue a formal quote with full commercial terms.",
                },
                {
                    "action": "counter_offer",
                    "supplier_id": supplier_id,
                    "offer_id": f"offer_{supplier_id}_v1",
                    "proposal": {
                        "unit_price_usd": unit_price,
                        "moq": 10,
                        "payment_terms_days": 60,
                        "refund_window_days": refund_window,
                        "return_freight_payer": "supplier",
                    },
                    "message": "Please formalize these price, payment, and return terms.",
                },
                {
                    "action": "request_sample",
                    "supplier_id": supplier_id,
                    "message": "Please provide the exact-variant qualification sample.",
                },
            ]
        )
    actions.append(
        {
            "action": "submit_award",
            "award_lines": [
                {"offer_id": f"offer_{supplier_id}_v2", "quantity": 20}
                for supplier_id in negotiated_terms
            ],
        }
    )
    return [_response(action) for action in actions]


def test_case_hash_and_objective_upper_bound_validate() -> None:
    case = load_case()
    upper = solve_full_information_upper_bound(case.payload)

    assert case.case_id == "procurement_allocation_v1.dev.quality_speed_margin"
    assert case.content_sha256 == case_content_sha256(case)
    assert upper.contribution_margin_usd == pytest.approx(16.00174036)
    assert upper.completed_kits == 19
    assert upper.actions_required == 10
    assert [row["supplier_id"] for row in upper.award_plan] == [
        "switch_reliable",
        "oled_reliable",
        "charger_reliable",
    ]


def test_observation_hides_private_terms_and_marks_listings_unverified() -> None:
    case = load_case()
    plugin = ProcurementAllocationPlugin()
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, run=None)
    phase = plugin.phases(family_case)[0]

    observation = plugin.observe(family_case, state, "buyer", phase)
    serialized = canonical_json_bytes(observation)

    assert b"private_terms" not in serialized
    assert b"floor_unit_price_usd" not in serialized
    assert not observation["formal_offers"]
    assert not observation["verified_samples"]
    assert {
        row["listing"]["evidence_status"] for row in observation["supplier_listings"]
    } == {"marketplace_listing_unverified"}


def test_verbal_confirmation_is_visible_but_not_award_eligible(tmp_path) -> None:
    script = [
        _response(
            {
                "action": "inquire",
                "supplier_id": "switch_reliable",
                "fields": ["exact_variant", "lead_time", "return_refund_policy"],
                "message": "Please verbally confirm the variant and service terms.",
            }
        ),
        _response(
            {
                "action": "submit_award",
                "award_lines": [
                    {"offer_id": "verbal_switch_reliable", "quantity": 20}
                ],
            }
        ),
    ]

    _, execution, provider = asyncio.run(
        run_fixture_script(script, evidence_root=tmp_path / "verbal")
    )
    outcome = _plain(execution.episode_result.outcome)
    final_state = _plain(execution.episode_result.final_state)

    assert provider.exhausted
    assert final_state["claims"]["switch_reliable"]["exact_variant"][
        "evidence_status"
    ] == "verbal_claim"
    assert not final_state["offers"]
    assert outcome["decision"] == "award"
    assert outcome["feasible"] is False
    assert outcome["contribution_margin_usd"] == pytest.approx(-0.05)
    assert "award_lines[0].unknown_offer" in outcome["violations"]


def test_counter_outside_supplier_limits_is_rejected_without_new_offer(
    tmp_path,
) -> None:
    script = [
        _response(
            {
                "action": "request_quote",
                "supplier_id": "switch_reliable",
                "message": "Please issue a formal quote.",
            }
        ),
        _response(
            {
                "action": "counter_offer",
                "supplier_id": "switch_reliable",
                "offer_id": "offer_switch_reliable_v1",
                "proposal": {
                    "unit_price_usd": 0.001,
                    "moq": None,
                    "payment_terms_days": None,
                    "refund_window_days": None,
                    "return_freight_payer": None,
                },
                "message": "Can you accept this price?",
            }
        ),
        _response({"action": "defer", "reason": "Counter was not accepted."}),
    ]

    _, execution, provider = asyncio.run(
        run_fixture_script(script, evidence_root=tmp_path / "rejected-counter")
    )
    final_state = _plain(execution.episode_result.final_state)
    outcome = _plain(execution.episode_result.outcome)

    assert provider.exhausted
    assert set(final_state["offers"]) == {"offer_switch_reliable_v1"}
    assert final_state["latest_offer_by_supplier"]["switch_reliable"] == (
        "offer_switch_reliable_v1"
    )
    assert any(
        "Counter rejected" in message["content"]
        for message in final_state["conversation"]
        if message["role"] == "supplier"
    )
    assert outcome["decision"] == "defer"
    assert outcome["contribution_margin_usd"] == pytest.approx(-0.25)


def test_optimal_interactive_script_matches_reference_and_replays(tmp_path) -> None:
    setup, execution, provider = asyncio.run(
        run_fixture_script(_optimal_script(), evidence_root=tmp_path / "optimal")
    )
    outcome = _plain(execution.episode_result.outcome)

    assert provider.exhausted
    assert len(execution.action_executions) == 10
    assert outcome["decision"] == "award"
    assert outcome["feasible"] is True
    assert outcome["contribution_margin_usd"] == pytest.approx(
        outcome["upper_bound_usd"]
    )
    assert outcome["regret_to_upper_bound_usd"] == pytest.approx(0.0)
    assert outcome["completed_kits"] == 19
    assert outcome["elapsed_days"] == 12

    receipt = finalize_procurement_allocation_execution(
        setup=setup, execution=execution
    )
    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"
    assert receipt.scores[0].primary.value == pytest.approx(16.00174036)
    assert receipt.scores[0].leaf.verifier.verifier_family == "objective_reference"

    replayed = replay_procurement_allocation_receipt(
        setup=setup,
        receipt=receipt,
        evidence_root=tmp_path / "optimal",
    )
    assert canonical_json_bytes(replayed) == canonical_json_bytes(receipt)


def test_return_window_changes_expected_recovery_and_margin() -> None:
    case = load_case()
    suppliers = {
        supplier["supplier_id"]: supplier for supplier in case.payload["suppliers"]
    }
    selected = ("switch_reliable", "oled_reliable", "charger_reliable")
    offers = {
        f"offer_{supplier_id}_v1": environment_module._base_offer(
            suppliers[supplier_id], version=1, issued_day=0
        )
        for supplier_id in selected
    }
    quality = {
        supplier_id: {
            **_plain(suppliers[supplier_id]["private_terms"]["quality"]),
            "supplier_id": supplier_id,
            "variant_id": suppliers[supplier_id]["private_terms"]["variant_id"],
            "evidence_status": "verified_sample",
        }
        for supplier_id in selected
    }
    lines = [
        {"offer_id": f"offer_{supplier_id}_v1", "quantity": 20}
        for supplier_id in selected
    ]
    protected = evaluate_award(
        case.payload,
        award_lines=lines,
        offers=offers,
        quality_evidence=quality,
        elapsed_days=0,
        information_cost_usd=0.0,
    )
    expired_claim_offers = copy.deepcopy(offers)
    expired_claim_offers["offer_oled_reliable_v1"]["return_policy"][
        "refund_window_days"
    ] = 5
    unprotected = evaluate_award(
        case.payload,
        award_lines=lines,
        offers=expired_claim_offers,
        quality_evidence=quality,
        elapsed_days=0,
        information_cost_usd=0.0,
    )

    assert protected["feasible"] and unprotected["feasible"]
    assert protected["expected_recovery_usd"] > unprotected["expected_recovery_usd"]
    assert protected["contribution_margin_usd"] > unprotected[
        "contribution_margin_usd"
    ]


def test_output_schema_has_one_strict_root_with_all_actions() -> None:
    schema = procurement_action_output_schema()

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["action"]["enum"] == [
        "inquire",
        "request_quote",
        "request_sample",
        "counter_offer",
        "submit_award",
        "check_award",
        "defer",
    ]
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["supplier_id"]["type"] == ["string", "null"]


def test_parser_projects_superset_schema_onto_selected_action() -> None:
    case = load_case()
    plugin = ProcurementAllocationPlugin()
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, run=None)
    phase = plugin.phases(family_case)[0]
    payload = {
        "action": "inquire",
        "supplier_id": "switch_value",
        "message": "Please confirm the commercial and quality terms.",
        "fields": ["exact_variant", "quality"],
        "offer_id": None,
        "proposal": None,
        "award_lines": [],
        "reason": None,
    }

    parsed = plugin.parse_action(family_case, state, "buyer", phase, payload)

    assert parsed.ok
    assert _plain(parsed.action) == {
        "action": "inquire",
        "supplier_id": "switch_value",
        "message": "Please confirm the commercial and quality terms.",
        "fields": ["exact_variant", "quality"],
    }

    payload["award_lines"] = [
        {"offer_id": "offer_switch_value_v1", "quantity": 20}
    ]
    still_parsed = plugin.parse_action(family_case, state, "buyer", phase, payload)
    assert still_parsed.ok
    assert "award_lines" not in still_parsed.action

    payload["unexpected_field"] = "must not be silently discarded"
    rejected = plugin.parse_action(family_case, state, "buyer", phase, payload)
    assert not rejected.ok
    assert rejected.error_code == "malformed_procurement_action"


def test_run_plan_pins_sources_and_openrouter_route() -> None:
    setup = build_offline_setup()
    pins = {pin.component_id: pin.sha256 for pin in setup.plan.implementation_pins}
    environment_sha = hashlib.sha256(
        Path(environment_module.__file__).read_bytes()
    ).hexdigest()
    execution_sha = hashlib.sha256(Path(execution_module.__file__).read_bytes()).hexdigest()

    assert pins["procurement_allocation_environment"] == environment_sha
    assert pins["procurement_allocation_contribution_margin_scorer_v1"] == environment_sha
    assert pins["procurement_full_information_upper_bound_v1"] == environment_sha
    assert pins["minimal_chat"] == execution_sha
    assert pins["aeread.shared_runner.task.execution"] == execution_sha

    route = OpenRouterRoute(
        profile_id="procurement_glm_test_v1",
        model="z-ai/glm-test",
        revision="z-ai/glm-test",
        route_provider="test-provider",
        quantization="unknown",
        pricing=TokenPricing(0.1, 0.05, 0.2, "test_pricing_v1"),
        max_prompt_price_per_million="0.1",
        max_completion_price_per_million="0.2",
        reasoning_effort="low",
    )
    routed = build_openrouter_setup(route, seed=231)
    profile = routed.plan.agent_profiles[0]

    assert profile.model.provider == "openrouter"
    assert profile.model.model == "z-ai/glm-test"
    assert profile.sampling.seed == 231
    assert _plain(profile.harness.config["output_schema"]) == procurement_action_output_schema()
    assert profile.retry_policy.max_action_attempts == 1
    assert profile.retry_policy.retryable_conditions == ()

    retrying = build_openrouter_setup(
        route,
        seed=231,
        max_action_attempts=3,
        retryable_conditions=("rate_limit", "provider_5xx"),
        retry_backoff="exponential_jitter_v1",
    )
    retrying_profile = retrying.plan.agent_profiles[0]
    assert retrying_profile.retry_policy.max_action_attempts == 3
    assert retrying_profile.retry_policy.retryable_conditions == (
        "rate_limit",
        "provider_5xx",
    )
    assert retrying_profile.retry_policy.sdk_retries == 0
    assert (
        retrying_profile.harness.config["retry_backoff"]
        == "exponential_jitter_v1"
    )
    assert retrying_profile.harness.config["retry_base_seconds"] == 2.0
    assert retrying_profile.harness.config["retry_after_max_seconds"] == 60.0

    with pytest.raises(ValueError, match="known-zero-cost"):
        build_openrouter_setup(
            route,
            seed=231,
            max_action_attempts=2,
            retryable_conditions=("timeout",),
            retry_backoff="exponential_jitter_v1",
        )


def test_check_award_reports_violations_without_terminating(tmp_path) -> None:
    """A pre-award check evaluates the proposed lines against the current formal
    offers and samples, reports what submit_award would report, consumes one
    action and nothing else, and leaves the episode open."""
    quote = {
        "action": "request_quote",
        "supplier_id": "switch_reliable",
        "message": "Please issue a formal quote.",
    }
    sample = {
        "action": "request_sample",
        "supplier_id": "switch_reliable",
        "message": "Please send the exact-variant sample.",
    }
    over_capacity = {
        "action": "check_award",
        "award_lines": [{"offer_id": "offer_switch_reliable_v1", "quantity": 30}],
    }
    unknown_offer = {
        "action": "check_award",
        "award_lines": [{"offer_id": "offer_oled_reliable_v1", "quantity": 20}],
    }
    script = [_response(a) for a in (quote, sample, over_capacity, unknown_offer)] + [
        _response({"action": "defer", "reason": "checks only"})
    ]

    _, execution, provider = asyncio.run(
        run_fixture_script(script, evidence_root=tmp_path / "check")
    )
    outcome = _plain(execution.episode_result.outcome)
    final_state = _plain(execution.episode_result.final_state)

    assert provider.exhausted
    assert outcome["decision"] == "defer"
    assert outcome["action_count"] == 5
    checks = final_state["award_checks"]
    assert [c["ordinal"] for c in checks] == [3, 4]
    assert checks[0]["feasible"] is False
    assert "switch_reliable.over_capacity" in checks[0]["violations"]
    assert checks[1]["feasible"] is False
    assert "award_lines[0].unknown_offer" in checks[1]["violations"]
    # a check costs an action only: no money, no calendar time
    assert final_state["information_cost_usd"] == pytest.approx(
        0.1 + final_state["quality_evidence"]["switch_reliable"]["sample_cost_usd"]
    )
    assert final_state["elapsed_days"] == checks[0]["elapsed_days"] == checks[1]["elapsed_days"]
    assert final_state["award_lines"] == []


def test_check_award_projection_matches_the_award_it_precedes(tmp_path) -> None:
    script = _optimal_script()
    award = json.loads(script[-1])["action"] if False else None
    actions = [json.loads(item)["action"] if False else None for item in script]
    del award, actions
    raw = [json.loads(s) for s in script]
    submit = raw[-1]
    check = {"action": "check_award", "award_lines": submit["award_lines"]}
    script_with_check = [_response(a) for a in raw[:-1]] + [_response(check), _response(submit)]

    _, execution, _ = asyncio.run(
        run_fixture_script(script_with_check, evidence_root=tmp_path / "match")
    )
    outcome = _plain(execution.episode_result.outcome)
    final_state = _plain(execution.episode_result.final_state)
    check_record = final_state["award_checks"][-1]

    assert outcome["feasible"] is True
    assert check_record["feasible"] is True
    assert check_record["violations"] == []
    assert check_record["completed_kits"] == outcome["completed_kits"]
    assert check_record["contribution_margin_usd"] == pytest.approx(
        outcome["contribution_margin_usd"]
    )


def test_check_award_is_visible_in_the_observation_and_parses_strictly() -> None:
    case = load_case()
    plugin = ProcurementAllocationPlugin()
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, run=None)
    phase = plugin.phases(family_case)[0]

    assert plugin.observe(family_case, state, "buyer", phase)["award_checks"] == []
    parsed = plugin.parse_action(
        family_case, state, "buyer", phase,
        {"action": "check_award", "award_lines": [{"offer_id": "x", "quantity": 1}]},
    )
    assert parsed.ok
    rejected = plugin.parse_action(
        family_case, state, "buyer", phase,
        {"action": "check_award", "award_lines": []},
    )
    assert not rejected.ok and rejected.error_code == "malformed_procurement_action"

