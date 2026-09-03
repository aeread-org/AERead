from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.housing import DEEPINFRA_GLM_53_FLASH_ROUTE
from aeread.shared_runner.housing_population_campaign import (
    _complete_admission_request,
    _live_stage_root,
    _profile_request,
    audit_world_panel,
    build_condition_setups,
    design_contract_artifact,
    execute_campaign,
    load_contract,
)
from aeread.shared_runner.execution import ProviderFailure, ProviderResult
from aeread.shared_runner.resolver import canonical_json_bytes


CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_population_crossplay_v0.json"
)


def test_contract_resolves_the_complete_frozen_crossplay_matrix() -> None:
    contract = load_contract(CONTRACT_PATH)
    setups = build_condition_setups(
        contract,
        world_seeds=contract["full_trajectory"]["world_seeds"],
        replicates=1,
    )

    assert len(setups) == 6
    for condition in contract["conditions"]:
        setup = setups[condition["condition_id"]]
        for profile in setup.plan.agent_profiles:
            if profile.model.provider != "openrouter":
                continue
            assert profile.retry_policy.max_action_attempts == 4
            assert profile.retry_policy.retryable_conditions == (
                "length",
                "rate_limit",
                "provider_5xx",
                "empty_response",
            )
        block = setup.plan.evaluation_blocks[0]
        assert block.kind == condition["evaluation_kind"]
        assert len(setup.plan.cells[0].profile_by_seat) == 10
        if block.kind == "controlled":
            assert len(block.subject_seats) == 6
            assert len(block.controlled_profiles) == 4
        elif block.kind == "self_play":
            assert len(block.subject_seats) == 10
            assert dict(block.controlled_profiles) == {}
        else:
            assert len(block.subject_seats) == 6
            assert dict(block.controlled_profiles) == {}


def test_design_and_provider_free_qc_are_evidence_backed() -> None:
    contract = load_contract(CONTRACT_PATH)

    design = design_contract_artifact(contract)
    qc = audit_world_panel(contract)

    assert design["status"] == "passed"
    assert design["complete_matrix"] is True
    assert design["scripted_anchor_ranked"] is False
    assert qc["status"] == "passed"
    assert qc["world_count"] == 17
    assert qc["duplicate_world_count"] == 0
    assert qc["beatability_passed"] is True
    assert all(
        row["oracle_total"] == row["oracle_informed_total"]
        and row["oracle_total"] > row["naive_total"]
        for row in qc["worlds"]
    )


def test_glm_route_uses_distinct_cached_input_price() -> None:
    pricing = DEEPINFRA_GLM_53_FLASH_ROUTE.token_pricing()

    assert pricing.input_per_million == 0.075
    assert pricing.cached_input_per_million == 0.015
    assert pricing.output_per_million == 0.25


def test_admission_retries_declared_failures_and_records_every_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = load_contract(CONTRACT_PATH)
    request = _profile_request(
        controls=contract["controls"],
        model_id="glm_53_flash",
        role="tenant",
        action_schema="housing_contact_v1",
        observation={"board": []},
        probe_index=0,
    )
    responses: list[ProviderFailure | ProviderResult] = [
        ProviderFailure("rate_limit", "busy", retryable=True, status_code=429),
        ProviderResult(
            response_id="response_empty",
            requested_model=request.model,
            resolved_model=request.revision,
            output_text="",
            finish_reason="stop",
            input_tokens=1,
            cached_input_tokens=0,
            output_tokens=0,
            cost_usd=0.0002,
            raw_response={},
        ),
        ProviderResult(
            response_id="response_ok",
            requested_model=request.model,
            resolved_model=request.revision,
            output_text='{"decision":"pass","listing_id":null,"rent":null}',
            finish_reason="stop",
            input_tokens=1,
            cached_input_tokens=0,
            output_tokens=1,
            cost_usd=0.0001,
            raw_response={},
        ),
    ]

    class SequencedClient:
        async def complete(self, unused_request: object) -> ProviderResult:
            response = responses.pop(0)
            if isinstance(response, ProviderFailure):
                raise response
            return response

    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(
        "aeread.shared_runner.housing_population_campaign.asyncio.sleep",
        record_sleep,
    )
    result, attempts = asyncio.run(
        _complete_admission_request(
            client=SequencedClient(),  # type: ignore[arg-type]
            request=request,
            controls=contract["controls"],
        )
    )

    assert result.response_id == "response_ok"
    assert [row["status"] for row in attempts] == ["failed", "failed", "passed"]
    assert [row["failure_condition"] for row in attempts] == [
        "rate_limit",
        "empty_response",
        None,
    ]
    assert sum(row["cost_usd"] for row in attempts) == pytest.approx(0.0003)
    assert len(delays) == 2


def test_live_gate_retries_use_whole_matrix_attempt_directories(
    tmp_path: Path,
) -> None:
    assert _live_stage_root(tmp_path, "full_trajectory", 1) == (
        tmp_path / "full_trajectory"
    )
    assert _live_stage_root(tmp_path, "full_trajectory", 2) == (
        tmp_path / "full_trajectory" / "attempt_2"
    )


def test_contract_rejects_route_drift(tmp_path: Path) -> None:
    value = json.loads(CONTRACT_PATH.read_bytes())
    value["models"]["glm_53_flash"]["canonical_model"] = "drifted"
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="model route drifted"):
        load_contract(path)


def test_campaign_executes_through_provider_free_gate_without_paid_calls(
    tmp_path: Path,
) -> None:
    result = asyncio.run(
        execute_campaign(
            contract_path=CONTRACT_PATH,
            output_root=tmp_path / "campaign",
            through="provider_free_validation",
        )
    )

    assert result["gate_summaries"]["design_contract"]["status"] == "passed"
    assert result["gate_summaries"]["provider_free_validation"]["status"] == "passed"
    history = json.loads((tmp_path / "campaign" / "gate_history.json").read_bytes())
    assert [record["gate_id"] for record in history["records"]] == [
        "design_contract",
        "provider_free_validation",
    ]
    summary = json.loads(
        (
            tmp_path / "campaign" / "provider_free_validation" / "summary.json"
        ).read_bytes()
    )
    assert summary["provider_cost_usd"] == 0.0
    assert summary["replay_verified"] is True


def test_campaign_explicitly_migrates_legacy_history_without_losing_source(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "campaign"
    asyncio.run(
        execute_campaign(
            contract_path=CONTRACT_PATH,
            output_root=output_root,
            through="provider_free_validation",
        )
    )
    history_path = output_root / "gate_history.json"
    modern = json.loads(history_path.read_bytes())
    provider_summary_path = output_root / "provider_free_validation" / "summary.json"
    provider_summary = json.loads(provider_summary_path.read_bytes())
    provider_summary_core = {
        key: value
        for key, value in provider_summary.items()
        if key not in {"artifact_sha256", "covered_world_ids"}
    }
    provider_summary_path.write_bytes(
        canonical_json_bytes(
            {
                **provider_summary_core,
                "artifact_sha256": hashlib.sha256(
                    canonical_json_bytes(provider_summary_core)
                ).hexdigest(),
            }
        )
        + b"\n"
    )
    legacy_core = {
        "schema_version": "aeread.campaign_gate_history/0.1",
        "records": [
            {
                "attempt_index": row["attempt_index"],
                "campaign_id": row["campaign_id"],
                "evidence_refs": [item["path"] for item in row["evidence_refs"]],
                "failure_reasons": row["failure_reasons"],
                "gate_id": row["gate_id"],
                "status": row["status"],
            }
            for row in modern["records"]
        ],
    }
    legacy = {
        **legacy_core,
        "artifact_sha256": hashlib.sha256(
            canonical_json_bytes(legacy_core)
        ).hexdigest(),
    }
    legacy_bytes = canonical_json_bytes(legacy) + b"\n"
    history_path.write_bytes(legacy_bytes)

    with pytest.raises(ValueError, match="legacy campaign history"):
        asyncio.run(
            execute_campaign(
                contract_path=CONTRACT_PATH,
                output_root=output_root,
                through="provider_free_validation",
            )
        )

    result = asyncio.run(
        execute_campaign(
            contract_path=CONTRACT_PATH,
            output_root=output_root,
            through="provider_free_validation",
            migrate_legacy_history=True,
        )
    )

    assert result["legacy_history_migrated"] is True
    assert (output_root / "gate_history.v0.1.json").read_bytes() == legacy_bytes
    migrated = json.loads(history_path.read_bytes())
    assert migrated["schema_version"] == "aeread.campaign_gate_history/0.2"
    assert [row["record_type"] for row in migrated["records"]] == ["gate", "gate"]
    assert all(
        row["evidence_refs"][0]["sha256"]
        for row in migrated["records"]
    )


def test_published_trajectory_examples_are_digest_bound_and_unranked() -> None:
    path = (
        CONTRACT_PATH.parents[1]
        / "evidence"
        / "housing_population_crossplay_v0"
        / "trajectories"
        / "selected_2026-09-02.json"
    )
    value = json.loads(path.read_bytes())
    core = {key: item for key, item in value.items() if key != "artifact_sha256"}

    assert (
        value["artifact_sha256"]
        == hashlib.sha256(canonical_json_bytes(core)).hexdigest()
    )
    assert value["ranking_allowed"] is False
    assert value["raw_provider_responses_included"] is False
    assert value["model_reasoning_included"] is False
    assert {example["example_class"] for example in value["examples"]} == {
        "completed_upper_observed_crossplay",
        "completed_lower_observed_crossplay",
        "shortest_operational_failure",
    }


def test_published_population_qualification_is_digest_bound() -> None:
    path = (
        CONTRACT_PATH.parents[1]
        / "evidence"
        / "housing_population_crossplay_v0"
        / "reports"
        / "qualification_2026-09-01.json"
    )
    value = json.loads(path.read_bytes())
    core = {key: item for key, item in value.items() if key != "artifact_sha256"}

    assert (
        value["artifact_sha256"]
        == hashlib.sha256(canonical_json_bytes(core)).hexdigest()
    )
    assert value["winner_claim_allowed"] is False
    assert value["local_evidence"]["committed"] is False


def test_published_population_requalification_is_digest_bound_and_blocked() -> None:
    path = (
        CONTRACT_PATH.parents[1]
        / "evidence"
        / "housing_population_crossplay_v0"
        / "reports"
        / "requalification_2026-09-02.json"
    )
    value = json.loads(path.read_bytes())
    core = {key: item for key, item in value.items() if key != "artifact_sha256"}

    assert (
        value["artifact_sha256"]
        == hashlib.sha256(canonical_json_bytes(core)).hexdigest()
    )
    assert value["status"] == "blocked_by_profile_admission"
    assert value["winner_claim_allowed"] is False
    assert value["observed_totals"]["visible_provider_attempts"] == 6
    assert value["observed_totals"]["trajectories_started"] == 0
    assert value["source_bindings"]["raw_provider_metadata_committed"] is False
