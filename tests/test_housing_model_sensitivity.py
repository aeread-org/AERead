from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from aeread_families.housing.runner import build_housing_smoke
from aeread_families.housing.model_sensitivity import (
    _critical_failure,
    build_setups,
    design_artifact,
    execute_campaign,
    load_contract,
    provider_free_artifact,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import ProviderFailure
from aeread.shared_runner.task.scheduler import SchedulerContractError


CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_model_sensitivity_v1.json"
)


def test_contract_freezes_models_cases_harness_and_single_world_claim_scope() -> None:
    contract = load_contract(CONTRACT_PATH)

    assert contract["claim_status"] == "development_integration_only"
    assert contract["controls"]["harness"] == "minimal_chat/1.0"
    assert contract["controls"]["tools"] == "disabled"
    assert contract["controls"]["memory"] == "disabled"
    assert contract["execution"]["world_seeds"] == [1971418798]
    assert contract["execution"]["winner_claim_allowed"] is False
    assert contract["analysis"]["ranking_allowed"] is False
    assert len(contract["conditions"]) == 4


def test_setups_cross_all_models_and_cases_with_admitted_profile_hashes() -> None:
    contract = load_contract(CONTRACT_PATH)
    setups = build_setups(contract)
    expected_profiles = contract["profile_admission_reference"]["profile_sha256s"]

    assert len(setups) == 12
    assert {config_id for config_id, _ in setups} == {
        "mild_cw085_r2",
        "moderate_cw085_r2",
        "severe_cw030_r2",
    }
    for setup in setups.values():
        profiles = {
            profile.profile_id: profile for profile in setup.plan.agent_profiles
        }
        assert {
            profile_id: hashlib.sha256(canonical_json_bytes(profile)).hexdigest()
            for profile_id, profile in profiles.items()
        } == {profile_id: expected_profiles[profile_id] for profile_id in profiles}
        assert all(
            profile.budgets.max_logical_actions
            == (48 if "tenant" in profile_id else 16)
            for profile_id, profile in profiles.items()
        )
        assert all(
            (profile.harness.id, profile.harness.version) == ("minimal_chat", "1.0")
            for profile in profiles.values()
        )


def test_design_and_provider_free_gates_are_complete_and_reproducible() -> None:
    contract = load_contract(CONTRACT_PATH)

    design = design_artifact(contract)
    provider_free = provider_free_artifact(contract)

    assert design["status"] == "passed"
    assert design["planned_trajectories"] == 12
    assert design["complete_model_matrix"] is True
    assert design["ranking_allowed"] is False
    assert provider_free["status"] == "passed"
    assert provider_free["provider_calls"] == 0
    assert provider_free["provider_cost_usd"] == 0.0
    assert provider_free["confirmatory_holdout_status"] == "sealed_not_executed"
    assert len(provider_free["worlds"]) == 3
    assert all(
        row["oracle_crosscheck_passed"] and row["oracle_active_ceiling_passed"]
        for row in provider_free["worlds"]
    )


def test_campaign_writes_sealed_provider_free_artifacts_without_a_key(
    tmp_path: Path,
) -> None:
    result = asyncio.run(
        execute_campaign(
            contract_path=CONTRACT_PATH,
            output_root=tmp_path / "campaign",
            through="provider_free",
        )
    )

    assert result["design"]["planned_trajectories"] == 12
    assert result["provider_free"]["provider_calls"] == 0
    assert (tmp_path / "campaign" / "design" / "summary.json").is_file()
    assert (tmp_path / "campaign" / "provider_free" / "summary.json").is_file()


def test_contract_rejects_ranking_or_case_selection_drift(tmp_path: Path) -> None:
    contract = json.loads(CONTRACT_PATH.read_bytes())
    contract["analysis"]["ranking_allowed"] = True
    ranking_path = tmp_path / "ranking.json"
    ranking_path.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(ValueError, match="analysis contract drifted"):
        load_contract(ranking_path)

    contract = json.loads(CONTRACT_PATH.read_bytes())
    contract["source_case_selection"]["file_sha256"] = "0" * 64
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(ValueError, match="selected-case file digest drifted"):
        load_contract(selection_path)


def test_housing_builder_preserves_defaults_and_accepts_frozen_profile_caps() -> None:
    default = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    explicit = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
        common_weight=0.85,
        tenant_max_logical_actions_override=48,
        landlord_max_logical_actions_override=16,
    )

    assert default.plan.cases[0].payload["common_weight"] == 0.6
    assert explicit.plan.cases[0].payload["common_weight"] == 0.85
    profiles = {
        profile.model.provider: profile for profile in explicit.plan.agent_profiles
    }
    assert profiles["housing_scripted_tenant"].budgets.max_logical_actions == 48
    assert profiles["housing_scripted_landlord"].budgets.max_logical_actions == 16

    with pytest.raises(ValueError, match="must be a positive integer"):
        build_housing_smoke(
            tenant_provider="housing_scripted_tenant",
            tenant_model="housing_scripted_tenant_v1",
            tenant_revision="1.0.0",
            tenant_max_logical_actions_override=True,
        )


def test_critical_failure_classification_uses_typed_causes_not_provider_prose() -> None:
    rate_limit = ProviderFailure(
        "rate_limit",
        "retry shortly or route to another provider",
        retryable=True,
        status_code=429,
    )
    try:
        raise SchedulerContractError("response source failed") from rate_limit
    except SchedulerContractError as wrapped_rate_limit:
        assert _critical_failure(wrapped_rate_limit) is False

    provider_contract = ProviderFailure(
        "provider_contract", "route identity drifted", retryable=False
    )
    try:
        raise SchedulerContractError("response source failed") from provider_contract
    except SchedulerContractError as wrapped_provider_contract:
        assert _critical_failure(wrapped_provider_contract) is True

    assert _critical_failure(SchedulerContractError("phase graph drifted")) is True


def test_published_qualification_record_is_digest_bound() -> None:
    path = (
        CONTRACT_PATH.parents[1]
        / "evidence"
        / "housing_model_sensitivity_v1"
        / "reports"
        / "qualification.json"
    )
    value = json.loads(path.read_bytes())
    core = {key: item for key, item in value.items() if key != "artifact_sha256"}

    assert (
        value["artifact_sha256"]
        == hashlib.sha256(canonical_json_bytes(core)).hexdigest()
    )
    assert value["gate_status"][-1]["completed_trajectories"] == 0
    assert value["gate_status"][-1]["not_started_trajectories"] == 9
    assert value["source_case_selection"]["confirmatory_holdout_status"] == (
        "sealed_not_executed"
    )
    assert value["ranking_allowed"] is False
