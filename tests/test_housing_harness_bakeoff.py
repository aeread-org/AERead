from __future__ import annotations

import pytest

from aeread.shared_runner.housing import build_housing_smoke
from aeread.shared_runner.housing_harness_bakeoff import (
    GLM_DEEPINFRA_ROUTE,
    GLM_MODEL,
    GLM_REVISION,
    LangChainProviderStrategyHarness,
    SmolagentsToolCallingHarness,
    _atomic_write_json,
    _condition_summary,
    _public_failure_summary,
    _read_sealed_row,
    _sealed_row,
    _summed_usage,
    derive_world_seeds,
)


def test_harness_panel_seeds_are_deterministic_and_unique() -> None:
    first = derive_world_seeds(master_seed=20260831, count=10)
    second = derive_world_seeds(master_seed=20260831, count=10)

    assert first == second
    assert len(set(first)) == 10
    assert derive_world_seeds(master_seed=20260830, count=10) != first


@pytest.mark.parametrize(
    ("harness", "required_capability"),
    [
        (LangChainProviderStrategyHarness(), "structured_output"),
        (SmolagentsToolCallingHarness(), "native_tools"),
    ],
)
def test_external_harness_identity_is_sealed_in_housing_plan(
    harness, required_capability: str
) -> None:
    setup = build_housing_smoke(
        tenant_provider="openrouter",
        tenant_model=GLM_MODEL,
        tenant_revision=GLM_REVISION,
        world_seeds=(41001,),
        replicates=1,
        reasoning_condition_id=f"test_{harness.id}_v1",
        reasoning_effort="low",
        inference_seed_base=87001,
        num_tenants=2,
        num_listings=1,
        rounds=1,
        openrouter_route=GLM_DEEPINFRA_ROUTE,
        tenant_harness=harness,
        tenant_profile_id_override=f"housing_test_{harness.id}",
        tenant_runtime="aeread.shared_runner.housing_harness_bakeoff",
        tenant_implementation_sha256="1" * 64,
    )

    tenant = next(
        profile
        for profile in setup.plan.agent_profiles
        if profile.model.provider == "openrouter"
    )
    assert (tenant.harness.id, tenant.harness.version) == (
        harness.id,
        harness.version,
    )
    assert required_capability in harness.requires.provider
    assert f"{harness.id}/{harness.version}" in setup.harnesses
    assert tenant.harness.config["request_seed_source"] == "paired_cell_v1"
    assert tenant.harness.config["retry_backoff"] == "exponential_jitter_v1"


def test_framework_usage_is_exact_only_when_every_response_reports_cost() -> None:
    complete = _summed_usage(
        [
            {
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 4,
                    "cost": 0.001,
                    "prompt_tokens_details": {"cached_tokens": 3},
                    "completion_tokens_details": {"reasoning_tokens": 2},
                }
            },
            {
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 5,
                    "cost": 0.002,
                }
            },
        ]
    )

    assert complete == {
        "input_tokens": 30,
        "cached_input_tokens": 3,
        "output_tokens": 9,
        "reasoning_tokens": 2,
        "cost_usd": pytest.approx(0.003),
        "provider_cost_complete": True,
    }

    incomplete = _summed_usage(
        [
            {"usage": {"prompt_tokens": 10, "completion_tokens": 4}},
        ]
    )
    assert incomplete["cost_usd"] is None
    assert incomplete["provider_cost_complete"] is False


def test_bakeoff_result_resume_requires_a_valid_digest(tmp_path) -> None:
    path = tmp_path / "result.json"
    row = _sealed_row({"condition_id": "arm_v1", "status": "completed"})
    _atomic_write_json(path, row)

    assert _read_sealed_row(path) == row

    path.write_text(path.read_text().replace("completed", "failed"))
    with pytest.raises(ValueError, match="result digest mismatch"):
        _read_sealed_row(path)


def test_public_failure_summary_omits_raw_provider_payload() -> None:
    error = RuntimeError(
        "Error code: 429 - {'user_id': 'private-user', 'api_key': 'secret'}"
    )

    summary = _public_failure_summary(error)

    assert summary == {
        "failure_type": "RuntimeError",
        "failure_condition": "provider_rate_limit",
        "failure_status_code": 429,
    }
    assert "private-user" not in repr(summary)
    assert "secret" not in repr(summary)


def test_condition_summary_keeps_operational_missingness_out_of_quality() -> None:
    rows = [
        {
            "condition_id": "arm_v1",
            "status": "completed",
            "within_case_score": 0.75,
            "elapsed_seconds": 2.0,
            "input_tokens": 10,
            "output_tokens": 2,
            "cost_usd": 0.001,
            "framework_model_request_count": 1,
            "effective_retry_count": 0,
            "framework_route_verified": True,
            "framework_provider_cost_complete": True,
        },
        {
            "condition_id": "arm_v1",
            "status": "operational_failure",
            "elapsed_seconds": 4.0,
        },
    ]

    summary = _condition_summary(rows, condition_id="arm_v1", planned=2)

    assert summary["mean_within_case_score"] == pytest.approx(0.75)
    assert summary["completed_worlds"] == 1
    assert summary["operational_failures"] == 1
    assert summary["provider_cost_complete"] is False
    assert summary["cost_qualifier"] == "unknown"
