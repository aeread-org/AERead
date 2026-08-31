from __future__ import annotations

import pytest

from aeread_families.procurement_grounding.bakeoff import (
    DEFAULT_CANDIDATES,
    OpenRouterBatchClient,
    conservative_cost_ceiling,
    planned_matrix,
    preflight_candidate,
    selected_candidates,
    summarize_rows,
)
from aeread.shared_runner.execution import ProviderRequest
from aeread_families.procurement_grounding.runner import (
    build_openrouter_setup,
    load_case,
    procurement_report_output_schema,
)


def test_wire_schema_is_strict_without_serializing_oracle_values() -> None:
    case = load_case()
    schema = procurement_report_output_schema(case)

    assert schema["additionalProperties"] is False
    assert schema["properties"]["priority_families"]["items"]["type"] == "object"
    assert "minItems" not in schema["properties"]["priority_families"]
    assert set(schema["properties"]["source_counts"]["properties"]) == set(
        case.payload["oracle"]["source_counts"]
    )
    serialized = repr(schema)
    assert "ready_for_bulk_order" not in serialized
    assert "Dongguan Jinyuan" not in serialized


def test_openrouter_setup_seals_route_schema_seed_and_cost() -> None:
    candidate = DEFAULT_CANDIDATES[0]
    setup = build_openrouter_setup(
        candidate.route,
        seed=71003,
        max_output_tokens=2500,
        max_cost_usd=0.01,
    )

    profile = setup.plan.agent_profiles[0]
    assert profile.model.provider == "openrouter"
    assert profile.model.model == candidate.route.model
    assert profile.model.revision == candidate.route.revision
    assert profile.sampling.seed == 71003
    assert profile.sampling.max_output_tokens == 2500
    assert profile.budgets.max_cost_usd == pytest.approx(0.01)
    assert profile.harness.config["provider_metadata"] == {
        "route_provider": "DeepInfra",
        "quantization": "fp8",
        "canonical_model": "deepseek/deepseek-v4-flash-20260731",
        "max_prompt_price_per_million": "0.08",
        "max_completion_price_per_million": "0.18",
    }
    assert profile.harness.config["output_schema"]["additionalProperties"] is False


def test_default_matrix_fits_the_fifteen_cent_hard_cap() -> None:
    ceiling = conservative_cost_ceiling(
        DEFAULT_CANDIDATES, replicates=3, warmups=1
    )
    matrix = planned_matrix(
        DEFAULT_CANDIDATES, replicates=3, warmups=1, concurrency=4
    )

    assert ceiling < 0.15
    assert matrix["conservative_cost_ceiling_usd"] == pytest.approx(ceiling)
    assert matrix["response_cache"] == "disabled"
    assert {row["lane"] for row in matrix["candidates"]} == {
        "standard",
        "batch_variant",
    }


def test_no_batch_selection_removes_only_batch_variant() -> None:
    selected = selected_candidates(include_batch=False)

    assert selected
    assert all(candidate.lane == "standard" for candidate in selected)
    assert len(selected) == len(DEFAULT_CANDIDATES) - 1


def test_preflight_rejects_a_price_increase(monkeypatch) -> None:
    candidate = DEFAULT_CANDIDATES[0]
    endpoint = {
        "name": f"{candidate.route.route_provider} | {candidate.route.revision}",
        "provider_name": candidate.route.route_provider,
        "quantization": candidate.route.quantization,
        "pricing": {"prompt": "0.000001", "completion": "0.00000016"},
        "supported_parameters": [
            "max_tokens",
            "reasoning_effort",
            "response_format",
            "seed",
            "structured_outputs",
        ],
    }
    monkeypatch.setattr(
        "aeread_families.procurement_grounding.bakeoff._load_endpoint_catalog",
        lambda _model: {"endpoints": [endpoint]},
    )

    with pytest.raises(RuntimeError, match="prices rose above"):
        preflight_candidate(candidate)


def test_summary_recommends_only_quality_qualified_candidate() -> None:
    cheap = DEFAULT_CANDIDATES[0]
    expensive = DEFAULT_CANDIDATES[1]
    rows = [
        {
            "candidate_id": cheap.candidate_id,
            "warmup": False,
            "status": "completed",
            "elapsed_seconds": 1.0,
            "valid": True,
            "score": 0.89,
            "input_tokens": 100,
            "cached_input_tokens": 50,
            "cost_usd": 0.0001,
        },
        {
            "candidate_id": expensive.candidate_id,
            "warmup": False,
            "status": "completed",
            "elapsed_seconds": 2.0,
            "valid": True,
            "score": 1.0,
            "input_tokens": 100,
            "cached_input_tokens": 80,
            "cost_usd": 0.0002,
        },
    ]

    summary = summarize_rows(rows)

    assert summary["recommendation"]["candidate_id"] == expensive.candidate_id
    cheap_summary = next(
        item
        for item in summary["candidates"]
        if item["candidate_id"] == cheap.candidate_id
    )
    assert cheap_summary["quality_qualified"] is False


def test_batch_result_allows_missing_reported_cost_for_pinned_price_fallback() -> None:
    candidate = DEFAULT_CANDIDATES[-1]
    request = ProviderRequest(
        provider_call_id="provider_call_batch_fixture",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        model=candidate.route.model,
        revision=candidate.route.revision,
        instructions="return json",
        input_text="{}",
        temperature=None,
        top_p=None,
        max_output_tokens=100,
        reasoning_effort="low",
        timeout_seconds=30.0,
        request_sha256="",
        output_schema={"type": "object", "properties": {}, "additionalProperties": False},
        provider_metadata={
            "route_provider": "Google",
            "quantization": "unknown",
            "canonical_model": candidate.route.revision,
            "max_prompt_price_per_million": "0.1875",
            "max_completion_price_per_million": "0.9375",
        },
        seed=1,
    ).with_computed_hash()
    item = {
        "custom_id": "provider_call_batch_fixture-0",
        "response": {
            "status_code": 200,
            "body": {
                "id": "gen_batch_fixture",
                "model": "google/gemini-3.7-flash",
                "provider": "Google",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "{}"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "prompt_tokens_details": {"cached_tokens": 0},
                },
            },
        },
    }

    result = OpenRouterBatchClient._provider_result(
        request, item, batch_id="batch_fixture"
    )

    assert result.cost_usd is None
    assert result.input_tokens == 100
    assert result.output_tokens == 20
