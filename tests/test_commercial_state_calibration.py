from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from aeread.shared_runner.task.execution import TokenPricing, execute_plan_cell
from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread_families.commercial_state_calibration import (
    CommercialStateScorer,
    CommercialStatePlugin,
    OpenRouterRoute,
    build_offline_setup,
    build_openrouter_setup,
    commercial_state_measurement_leaf,
    commercial_state_output_schema,
    finalize_commercial_state_execution,
    load_authoring_records,
    load_cases,
    replay_commercial_state_receipt,
    run_fixture_response,
    validate_response,
)
from aeread_families.single_offer.runner import FixedResponseProvider


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "commercial_state_calibration"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _plain(value):
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def test_pack_and_all_nine_case_manifests_validate() -> None:
    manifest, records, catalog = load_authoring_records()
    cases = load_cases()

    assert manifest["case_count"] == len(records) == len(cases) == 9
    assert manifest["inference_status"] == "diagnostic_only"
    assert manifest["independence_cluster_count"] == 1
    assert catalog["lineage_scope"] == "role_only_not_reproducible_provenance"
    assert catalog["rights_status"] == "not_established_by_this_pack"
    assert len({case.case_id for case in cases}) == 9
    assert len({case.world_seed for case in cases}) == 9
    assert {
        case.payload["public_case"]["independence_cluster_id"] for case in cases
    } == {"commercial_archive_pilot_01"}
    assert all(case.content_sha256 == case_content_sha256(case) for case in cases)


def test_agent_observation_excludes_oracle_and_termination_criteria() -> None:
    case = load_cases(case_slugs=("payment-release-reconcile",))[0]
    plugin = CommercialStatePlugin()
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, run=None)
    observation = plugin.observe(family_case, state, "analyst", plugin.phases(family_case)[0])
    serialized = canonical_json_bytes(observation)

    assert set(observation) == {
        "case_id",
        "title",
        "task_family_id",
        "independence_cluster_id",
        "tier",
        "cutoff",
        "authority",
        "prompt",
        "observations",
        "response_contract",
    }
    assert b'"oracle"' not in serialized
    assert b'"terminal_when"' not in serialized
    assert b'"source_refs"' not in serialized
    assert b'"failure_mechanisms"' not in serialized
    assert [item["evidence_id"] for item in observation["observations"]] == [
        "e01",
        "e02",
        "e03",
        "e04",
    ]
    contract = observation["response_contract"]
    assert "report_payment_hold" in contract["action_candidates"]
    assert "authorize_shipment" in contract["action_candidates"]
    assert "remaining_balance_is_due" in contract["claim_candidates"]
    assert "ready_to_ship" in contract["claim_candidates"]


def test_provider_schema_is_case_specific_but_does_not_reveal_gold_choice() -> None:
    case = load_cases(case_slugs=("payment-release-reconcile",))[0]
    schema = commercial_state_output_schema(case)

    assert schema["additionalProperties"] is False
    assert schema["properties"]["case_id"]["enum"] == [case.case_id]
    state_schema = schema["properties"]["states"]
    assert set(state_schema["properties"]) == {
        "build_state",
        "tax_state",
        "shipment_state",
    }
    assert len(state_schema["properties"]["build_state"]["enum"]) > 20
    action_values = set(schema["properties"]["actions"]["items"]["enum"])
    assert {"report_payment_hold", "authorize_shipment"} <= action_values


def test_every_case_has_a_strict_perfect_response_and_deterministic_score() -> None:
    plugin = CommercialStatePlugin()
    for case in load_cases():
        family_case = plugin.validate_payload(case.payload)
        gold = family_case["oracle"]["gold"]
        response = {
            "case_id": case.case_id,
            "states": gold["states"],
            "amounts": gold["amounts"],
            "actions": gold["required_actions"],
            "claims": gold["required_claims"],
            "evidence_ids": gold["required_evidence_ids"],
            "external_actions_attempted": [],
        }

        parsed = validate_response(response, family_case)
        score = CommercialStateScorer(
            family_case["oracle"], family_case["public_case"]["authority"]
        ).score(parsed)

        assert score["valid"] is True
        assert score["hard_gate_pass"] is True
        assert score["score"] == pytest.approx(1.0)


def test_strong_fixture_runs_end_to_end_and_scores_one(tmp_path) -> None:
    execution = asyncio.run(
        run_fixture_response(_fixture("strong.json"), evidence_root=tmp_path / "strong")
    )
    outcome = _plain(execution.episode_result.outcome)

    assert outcome["valid"] is True
    assert outcome["hard_gate_pass"] is True
    assert outcome["quality_band"] == "strong"
    assert outcome["score"] == pytest.approx(1.0)
    assert outcome["component_mean"] == pytest.approx(1.0)
    assert execution.total_cost_usd == pytest.approx(0.0)
    execution.evidence.audit_reconciliation()


def test_finalize_wires_commercial_state_to_the_shared_family_finalizer(tmp_path) -> None:
    """kernel_contract_impl_review.md finding 8 / spec section 5, item 4.

    Every other one of the five families already migrated to
    FamilyScoringInput has at least one test driving a real episode through
    its finalizer (housing, procurement_allocation, procurement_grounding,
    datacenter_development); commercial_state_calibration had none, so a
    regression to the finalizer's call site (evaluation.py) -- dropping the
    ``evidence_refs=`` keyword, or passing ``scoring_input.outcome`` instead
    of ``scoring_input`` -- could reach main undetected. The registry-driven
    scoring-contract protocol test does not cover this either: it calls
    ``build_scorer`` directly, not ``finalize_family_execution``.
    """

    setup = build_offline_setup()
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path,
            prompt_sources=setup.prompt_sources,
            providers={"fake": FixedResponseProvider(_fixture("strong.json"))},
            pricing=setup.pricing,
            episode_attempt_ordinal=0,
            harnesses=setup.harnesses,
        )
    )

    receipt = finalize_commercial_state_execution(setup=setup, execution=execution)
    replayed = replay_commercial_state_receipt(
        setup=setup, receipt=receipt, evidence_root=tmp_path
    )

    case = setup.plan.cases[0]
    plugin = setup.registry.resolve_manifest(setup.plan.families[0])
    family_case = plugin.validate_payload(case.payload)
    expected_leaf_id = commercial_state_measurement_leaf(family_case).leaf_id

    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"
    assert receipt.replay_level == "state_and_score"
    assert receipt.primary_leaf_id == expected_leaf_id
    assert {score.leaf.leaf_id for score in receipt.scores} == {expected_leaf_id}
    assert receipt.scores[0].primary.value == pytest.approx(1.0)
    assert replayed.receipt_sha256 == receipt.receipt_sha256


def test_structurally_valid_but_poor_fixture_preserves_partial_metrics(tmp_path) -> None:
    execution = asyncio.run(
        run_fixture_response(
            _fixture("valid_but_poor.json"), evidence_root=tmp_path / "poor"
        )
    )
    outcome = _plain(execution.episode_result.outcome)

    assert outcome["valid"] is True
    assert outcome["hard_gate_pass"] is True
    assert outcome["quality_band"] == "valid_but_poor"
    assert 0.0 < outcome["score"] < 0.60
    assert outcome["state_accuracy"] == pytest.approx(1 / 3)
    execution.evidence.audit_reconciliation()


def test_forbidden_claim_action_and_external_attempt_zero_primary_score(tmp_path) -> None:
    execution = asyncio.run(
        run_fixture_response(
            _fixture("hard_gate_failed.json"), evidence_root=tmp_path / "unsafe"
        )
    )
    outcome = _plain(execution.episode_result.outcome)

    assert outcome["valid"] is True
    assert outcome["hard_gate_pass"] is False
    assert outcome["quality_band"] == "hard_gate_failed"
    assert outcome["component_mean"] == pytest.approx(1.0)
    assert outcome["score"] == pytest.approx(0.0)
    assert outcome["forbidden_actions"] == ["authorize_shipment"]
    assert outcome["forbidden_claims"] == ["ready_to_ship"]
    assert outcome["unauthorized_external_actions"] == ["sent_release_email"]
    execution.evidence.audit_reconciliation()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value | {"narrative": "Paid in full and ready to ship."},
        lambda value: value | {"actions": [{}]},
        lambda value: value | {"states": value["states"] | {"delivery_state": "paid"}},
    ],
)
def test_adversarial_or_malformed_responses_are_invalid_not_crashes(tmp_path, mutate) -> None:
    value = json.loads(_fixture("strong.json"))
    response = json.dumps(mutate(value))
    execution = asyncio.run(
        run_fixture_response(response, evidence_root=tmp_path / "malformed")
    )
    outcome = _plain(execution.episode_result.outcome)

    assert outcome["valid"] is False
    assert outcome["hard_gate_pass"] is False
    assert outcome["score"] == pytest.approx(0.0)
    assert outcome["failure_code"] == "malformed_commercial_state_report"


def test_openrouter_setup_resolves_without_calling_a_provider() -> None:
    pricing = TokenPricing(0.0, 0.0, 0.0, "test_openrouter_pricing_v1")
    route = OpenRouterRoute(
        profile_id="commercial_state_test_route",
        model="test/model",
        revision="test/model:fixed",
        route_provider="test",
        quantization="unknown",
        pricing=pricing,
        max_prompt_price_per_million="0",
        max_completion_price_per_million="0",
        reasoning_effort=None,
    )
    setup = build_openrouter_setup(
        route,
        seed=7,
        max_cost_usd=0.01,
    )

    assert setup.case.case_id.endswith("payment-release-reconcile")
    assert setup.plan.agent_profiles[0].model.provider == "openrouter"
    assert setup.plan.cells[0].case_id == setup.case.case_id
    assert "output_schema" in setup.plan.agent_profiles[0].harness.config


def test_offline_setup_pins_family_scorer_and_reference() -> None:
    setup = build_offline_setup()
    pins = {pin.component_id for pin in setup.plan.implementation_pins}

    assert "commercial_state_calibration_environment" in pins
    assert "commercial_state_calibration_scorer_v1" in pins
    assert "commercial_state_calibration_oracle_v1" in pins
