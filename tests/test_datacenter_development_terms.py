from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.task.execution import TokenPricing
from aeread_families.datacenter_development_terms.campaign import (
    build_design,
    load_contract,
    run_campaign,
)
from aeread_families.datacenter_development_terms import (
    DataCenterTermsPlugin,
    DataCenterTermsScorer,
    OpenRouterRoute,
    build_offline_setup,
    build_openrouter_setup,
    datacenter_terms_indicator_output_schema,
    datacenter_terms_measurement_leaf,
    datacenter_terms_output_schema,
    load_authoring_records,
    load_cases,
    response_contract,
    run_fixture_response,
    validate_response,
)
from aeread_families.datacenter_development.objective_openrouter import (
    normalize_indicator_map_output,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "datacenter_development_terms"
PUBLICATION = ROOT / "evidence" / "datacenter_development_terms_probe_2026-09-03"
RELIABILITY_PUBLICATION = (
    ROOT / "evidence" / "datacenter_development_terms_reliability_v1"
)


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _plain(value):
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def test_pack_separates_one_runnable_case_from_eight_design_slots() -> None:
    manifest, records, catalog, project_manifest = load_authoring_records()
    cases = load_cases()

    assert manifest["case_count"] == len(records) == len(cases) == 1
    assert manifest["project_slot_count"] == 8
    assert manifest["runnable_project_count"] == 1
    assert manifest["source_required_project_count"] == 7
    assert manifest["historical_grounding_status"] == "not_established"
    assert project_manifest["scope"] == "design_coverage_not_observed_sample"
    assert project_manifest["independence_claim_status"] == "not_established"
    assert sum(
        project["status"] == "source_required"
        for project in project_manifest["projects"]
    ) == 7
    assert catalog["lineage_scope"] == "synthetic_authored_no_historical_provenance"
    assert catalog["historical_provenance"] is False
    assert "irrevocable written extension election" in records[0]["observations"][1]["content"]
    assert cases[0].content_sha256 == case_content_sha256(cases[0])


def test_observation_excludes_oracle_and_marks_report_only_authority() -> None:
    case = load_cases()[0]
    plugin = DataCenterTermsPlugin()
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, run=None)
    observation = plugin.observe(family_case, state, "analyst", plugin.phases(family_case)[0])
    serialized = canonical_json_bytes(observation)

    assert b'"oracle"' not in serialized
    assert b'"terminal_when"' not in serialized
    assert observation["authority"] == {
        "mode": "report",
        "external_actions_authorized": False,
    }
    assert len(observation["observations"]) == 7
    assert observation["response_contract"]["external_actions_authorized"] is False


def test_schema_is_case_specific_without_revealing_gold() -> None:
    case = load_cases()[0]
    schema = datacenter_terms_output_schema(case)

    assert schema["additionalProperties"] is False
    assert schema["properties"]["case_id"]["enum"] == [case.case_id]
    assert set(schema["properties"]["states"]["properties"]) == {
        "land_control_state",
        "power_agreement_state",
        "construction_agreement_state",
        "loan_agreement_state",
        "service_agreement_state",
    }
    assert len(
        schema["properties"]["states"]["properties"]["land_control_state"]["enum"]
    ) == 10
    assert "issue_notice_to_proceed" in schema["properties"]["actions"]["items"]["enum"]
    for field in (
        "actions",
        "claims",
        "evidence_ids",
        "external_actions_attempted",
    ):
        assert "uniqueItems" not in schema["properties"][field]

    unique_schema = datacenter_terms_output_schema(
        case,
        unique_array_items=True,
    )
    for field in (
        "actions",
        "claims",
        "evidence_ids",
        "external_actions_attempted",
    ):
        assert unique_schema["properties"][field]["uniqueItems"] is True


def test_indicator_output_schema_is_a_complete_boolean_classifier() -> None:
    case = load_cases()[0]
    family_case = DataCenterTermsPlugin().validate_payload(case.payload)
    contract = response_contract(family_case)
    schema = datacenter_terms_indicator_output_schema(case)
    for field, candidates in (
        ("actions", contract["action_candidates"]),
        ("claims", contract["claim_candidates"]),
        ("evidence_ids", contract["evidence_ids"]),
    ):
        indicator = schema["properties"][field]
        assert indicator["required"] == candidates
        assert set(indicator["properties"]) == set(candidates)
        assert all(
            value == {"type": "boolean"}
            for value in indicator["properties"].values()
        )
    assert schema["properties"]["external_actions_attempted"]["properties"] == {
        "any": {"type": "boolean"}
    }


def test_indicator_output_normalizes_selected_labels_and_rejects_duplicates() -> None:
    output = normalize_indicator_map_output(
        '{"actions":{"keep":true,"drop":false},'
        '"claims":{"claim":true},"evidence_ids":{"e01":true},'
        '"external_actions_attempted":{"any":false}}'
    )
    assert json.loads(output) == {
        "actions": ["keep"],
        "claims": ["claim"],
        "evidence_ids": ["e01"],
        "external_actions_attempted": [],
    }
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        normalize_indicator_map_output(
            '{"actions":{"keep":true,"keep":false},"claims":{},'
            '"evidence_ids":{},"external_actions_attempted":{"any":false}}'
        )


def test_strict_perfect_response_scores_one() -> None:
    case = load_cases()[0]
    plugin = DataCenterTermsPlugin()
    family_case = plugin.validate_payload(case.payload)
    response = json.loads(_fixture("strong.json"))

    parsed = validate_response(response, family_case)
    score = DataCenterTermsScorer(
        family_case["oracle"], family_case["public_case"]["authority"]
    ).score(parsed)

    assert score["valid"] is True
    assert score["hard_gate_pass"] is True
    assert score["score"] == pytest.approx(1.0)


def test_provider_free_fixture_executes_and_seals_distinct_measurement(tmp_path) -> None:
    execution = asyncio.run(
        run_fixture_response(_fixture("strong.json"), evidence_root=tmp_path / "strong")
    )
    outcome = _plain(execution.episode_result.outcome)
    case = load_cases()[0]
    leaf = datacenter_terms_measurement_leaf(case.payload)

    assert outcome["hard_gate_pass"] is True
    assert outcome["score"] == pytest.approx(1.0)
    assert leaf.estimand.estimand_id == "datacenter_development_terms_safe_accuracy"
    assert leaf.verifier.verifier_family == "canonical_reference"
    assert execution.total_cost_usd == pytest.approx(0.0)
    execution.evidence.audit_reconciliation()


def test_forbidden_claim_zeros_score_while_preserving_components(tmp_path) -> None:
    response = json.loads(_fixture("strong.json"))
    response["claims"].append("loan_is_committed")
    execution = asyncio.run(
        run_fixture_response(json.dumps(response), evidence_root=tmp_path / "unsafe")
    )
    outcome = _plain(execution.episode_result.outcome)

    assert outcome["valid"] is True
    assert outcome["hard_gate_pass"] is False
    assert outcome["component_mean"] == pytest.approx(1.0)
    assert outcome["score"] == pytest.approx(0.0)
    assert outcome["forbidden_claims"] == ["loan_is_committed"]


def test_unknown_field_is_invalid_not_silently_ignored(tmp_path) -> None:
    response = json.loads(_fixture("strong.json"))
    response["recommendation"] = "Proceed."
    execution = asyncio.run(
        run_fixture_response(json.dumps(response), evidence_root=tmp_path / "malformed")
    )
    outcome = _plain(execution.episode_result.outcome)

    assert outcome["valid"] is False
    assert outcome["score"] == pytest.approx(0.0)
    assert outcome["failure_code"] == "malformed_datacenter_terms_report"


def test_openrouter_setup_resolves_without_provider_call() -> None:
    pricing = TokenPricing(0.0, 0.0, 0.0, "test_datacenter_terms_pricing_v1")
    route = OpenRouterRoute(
        profile_id="datacenter_terms_test_route",
        model="test/model",
        revision="test/model:fixed",
        route_provider="test",
        quantization="unknown",
        pricing=pricing,
        max_prompt_price_per_million="0",
        max_completion_price_per_million="0",
        reasoning_effort=None,
    )
    setup = build_openrouter_setup(route, seed=7, max_cost_usd=0.01)

    assert setup.plan.agent_profiles[0].model.provider == "openrouter"
    assert setup.plan.cells[0].case_id == setup.case.case_id
    assert "output_schema" in setup.plan.agent_profiles[0].harness.config


def test_offline_setup_pins_distinct_family_scorer_and_reference() -> None:
    setup = build_offline_setup()
    pins = {pin.component_id for pin in setup.plan.implementation_pins}

    assert "datacenter_development_terms_environment" in pins
    assert "datacenter_development_terms_scorer_v1" in pins
    assert "datacenter_development_terms_oracle_v1" in pins


def test_probe_publication_is_digest_bound_and_preserves_missingness() -> None:
    manifest = json.loads((PUBLICATION / "publication_manifest.json").read_text())
    core = {key: value for key, value in manifest.items() if key != "artifact_sha256"}

    assert manifest["artifact_sha256"] == hashlib.sha256(
        canonical_json_bytes(core)
    ).hexdigest()
    for relative, expected in manifest["files"].items():
        payload = (PUBLICATION / relative).read_bytes()
        assert len(payload) == expected["bytes"]
        assert hashlib.sha256(payload).hexdigest() == expected["sha256"]

    summary = json.loads((PUBLICATION / "reports" / "summary.json").read_text())
    trajectories = [
        json.loads(line)
        for line in (PUBLICATION / "trajectories" / "sanitized.jsonl")
        .read_text()
        .splitlines()
    ]
    projections = [
        json.loads(line)
        for line in (PUBLICATION / "receipts" / "projections.jsonl")
        .read_text()
        .splitlines()
    ]
    assert summary["completed_cells"] == 1
    assert summary["operational_failure_cells"] == 1
    assert summary["provider_cost_complete"] is False
    assert summary["cost_qualifier"] == "lower_bound"
    assert summary["winner_claim_allowed"] is False
    assert [row["inclusion_status"] for row in trajectories] == [
        "included",
        "excluded",
    ]
    assert trajectories[1]["metrics"] is None
    assert trajectories[1]["failure"]["failure_condition"] == "provider_contract"
    assert projections[1]["primary_score"] is None
    assert projections[1]["replay_level"] == "none"

    public_text = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in PUBLICATION.rglob("*")
        if path.is_file()
    )
    for prohibited in (
        '"raw_response"',
        '"failure_message"',
        '"output_text"',
        "authorization:",
        "api_key",
        "/users/",
    ):
        assert prohibited not in public_text


def test_reliability_contract_builds_paired_budget_bounded_design() -> None:
    contract = load_contract()
    design = build_design(contract)

    assert design["planned_cells"] == 10
    assert design["paired_seed_count"] == 5
    assert design["worst_case_declared_cost_usd"] == pytest.approx(0.2)
    assert design["campaign_max_cost_usd"] == pytest.approx(0.25)
    by_seed = {}
    for cell in design["cells"]:
        by_seed.setdefault(cell["inference_seed"], set()).add(cell["model_id"])
    assert set(by_seed) == set(contract["inference_seeds"])
    assert all(models == set(contract["models"]) for models in by_seed.values())


def test_reliability_contract_rejects_aggregate_budget_overflow(tmp_path) -> None:
    contract = load_contract()
    contract["execution"]["max_cost_usd_per_cell"] = 0.03
    contract_path = tmp_path / "over_budget.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(ValueError, match="cost ceilings"):
        load_contract(contract_path)


def test_reliability_campaign_passes_pre_live_gates(tmp_path) -> None:
    summary = asyncio.run(
        run_campaign(run_root=tmp_path / "campaign", stop_after="profile_admission")
    )

    assert summary["status"] == "passed"
    assert len(summary["admitted_cells"]) == 10


def test_reliability_campaign_module_invokes_cli(tmp_path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "aeread_families.datacenter_development_terms.campaign",
            "--run-root",
            str(tmp_path / "campaign"),
            "--stop-after",
            "design",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(completed.stdout)

    assert summary["planned_cells"] == 10
    assert summary["campaign_max_cost_usd"] == pytest.approx(0.25)


def test_reliability_publication_is_bound_complete_and_sanitized() -> None:
    manifest = json.loads(
        (RELIABILITY_PUBLICATION / "publication_manifest.json").read_text()
    )
    manifest_core = {
        key: value for key, value in manifest.items() if key != "artifact_sha256"
    }
    assert manifest["artifact_sha256"] == hashlib.sha256(
        canonical_json_bytes(manifest_core)
    ).hexdigest()
    assert len(manifest["source_receipt_sha256s"]) == 10
    assert len(set(manifest["source_receipt_sha256s"])) == 10

    for relative, expected in manifest["files"].items():
        payload = (RELIABILITY_PUBLICATION / relative).read_bytes()
        assert len(payload) == expected["bytes"]
        assert hashlib.sha256(payload).hexdigest() == expected["sha256"]

    fact_manifest = json.loads(
        (RELIABILITY_PUBLICATION / "tables" / "fact_manifest.json").read_text()
    )
    assert (
        manifest["files"]["tables/benchmark_results.csv"]["row_count"]
        == fact_manifest["tables"]["benchmark_results"]["row_count"]
        == 98
    )
    assert (
        manifest["files"]["tables/profiles.csv"]["row_count"]
        == fact_manifest["tables"]["profiles"]["row_count"]
        == 10
    )

    summary = json.loads(
        (RELIABILITY_PUBLICATION / "reports" / "summary.json").read_text()
    )
    trajectories = [
        json.loads(line)
        for line in (
            RELIABILITY_PUBLICATION / "trajectories" / "sanitized.jsonl"
        )
        .read_text()
        .splitlines()
    ]
    projections = [
        json.loads(line)
        for line in (
            RELIABILITY_PUBLICATION / "receipts" / "projections.jsonl"
        )
        .read_text()
        .splitlines()
    ]
    assert len(trajectories) == len(projections) == 10
    assert sum(row["inclusion_status"] == "included" for row in trajectories) == 8
    assert sum(row["inclusion_status"] == "excluded" for row in trajectories) == 2
    assert all(row["metrics"] is None for row in trajectories if row["inclusion_status"] == "excluded")
    assert all(row["replay_level"] == "none" for row in projections if row["inclusion_status"] == "excluded")
    assert summary["provider_cost_complete"] is False
    assert summary["cost_qualifier"] == "lower_bound"
    assert summary["reported_cost_usd"] == pytest.approx(0.0049860261)
    assert summary["winner_claim_allowed"] is False
    assert summary["inferential_model_ranking_allowed"] is False

    public_text = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in RELIABILITY_PUBLICATION.rglob("*")
        if path.is_file()
    )
    for prohibited in (
        '"raw_response"',
        '"failure_message"',
        '"output_text"',
        '"user_id"',
        "authorization:",
        "api_key",
        "/users/",
    ):
        assert prohibited not in public_text
