from __future__ import annotations

import asyncio
import importlib.metadata
import json
import sys
import types

import pytest

from aeread_families.housing.runner import build_housing_smoke
from aeread_families.housing.harness_bakeoff import (
    GLM_DEEPINFRA_ROUTE,
    GLM_MODEL,
    GLM_REVISION,
    MODEL_LANDLORD_PROFILE_ID,
    HousingRoleRoutingProviderClient,
    LangChainProviderStrategyHarness,
    LangGraphStructuredOutputHarness,
    SmolagentsToolCallingHarness,
    _atomic_write_json,
    _capture_http_client,
    _condition_summary,
    _event_framework_metrics,
    _public_failure_summary,
    _read_sealed_row,
    _sealed_row,
    _summed_usage,
    derive_world_seeds,
)
from aeread.shared_runner.model_call.open_harnesses import _run_langgraph_structured_decision
from aeread.shared_runner.task.execution import ProviderRequest, ProviderResult


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
        (LangGraphStructuredOutputHarness(), "structured_output"),
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
        tenant_runtime="aeread_families.housing.harness_bakeoff",
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


def test_model_landlord_profile_is_fixed_and_paired_in_housing_plan() -> None:
    setup = build_housing_smoke(
        tenant_provider="openrouter",
        tenant_model=GLM_MODEL,
        tenant_revision=GLM_REVISION,
        landlord_provider="openrouter",
        landlord_model=GLM_MODEL,
        landlord_revision=GLM_REVISION,
        landlord_profile_id_override=MODEL_LANDLORD_PROFILE_ID,
        landlord_inference_seed_base=97001,
        landlord_openrouter_route=GLM_DEEPINFRA_ROUTE,
        world_seeds=(41001,),
        replicates=1,
        inference_seed_base=87001,
        num_tenants=2,
        num_listings=1,
        rounds=2,
        openrouter_route=GLM_DEEPINFRA_ROUTE,
    )

    profiles = {profile.profile_id: profile for profile in setup.plan.agent_profiles}
    landlord = profiles[MODEL_LANDLORD_PROFILE_ID]
    assert landlord.model.provider == "openrouter"
    assert landlord.model.revision == GLM_REVISION
    assert (landlord.harness.id, landlord.harness.version) == ("minimal_chat", "1.0")
    assert landlord.harness.config["request_seed_source"] == "paired_cell_v1"
    assert landlord.harness.config["request_seed_base"] == 97001
    assert setup.plan.cells[0].profile_by_seat["landlord_0"] == MODEL_LANDLORD_PROFILE_ID
    assert setup.plan.evaluation_blocks[0].controlled_profiles == {
        "landlord_0": MODEL_LANDLORD_PROFILE_ID
    }


def test_housing_role_router_keeps_landlord_out_of_tenant_harness() -> None:
    class FakeProvider:
        def __init__(self, label: str) -> None:
            self.label = label
            self.requests = []

        async def complete(self, request: ProviderRequest) -> ProviderResult:
            self.requests.append(request)
            return ProviderResult(
                response_id=self.label,
                requested_model=request.model,
                resolved_model=request.revision,
                output_text='{"decision":"pass","listing_id":null,"rent":null}',
                finish_reason="stop",
                input_tokens=1,
                cached_input_tokens=0,
                output_tokens=1,
                cost_usd=0.0,
                raw_response={"fixture": True},
            )

    def request(role: str) -> ProviderRequest:
        return ProviderRequest(
            provider_call_id=f"provider_call_{role}",
            provider="openrouter",
            base_url="https://openrouter.ai/api/v1",
            model=GLM_MODEL,
            revision=GLM_REVISION,
            instructions="Return one action.",
            input_text=json.dumps({"role": role}),
            temperature=0.0,
            top_p=1.0,
            max_output_tokens=128,
            reasoning_effort="low",
            timeout_seconds=30.0,
            request_sha256="",
            output_schema={"type": "object"},
            provider_metadata={},
            seed=1,
        ).with_computed_hash()

    tenant = FakeProvider("tenant")
    landlord = FakeProvider("landlord")
    router = HousingRoleRoutingProviderClient(tenant=tenant, landlord=landlord)

    assert asyncio.run(router.complete(request("tenant"))).response_id == "tenant"
    assert asyncio.run(router.complete(request("landlord"))).response_id == "landlord"
    assert len(tenant.requests) == 1
    assert len(landlord.requests) == 1


def test_openai_v2_capture_client_never_uses_httpx2(monkeypatch) -> None:
    selected = []

    class ExpectedClient:
        def __init__(self, *args, **kwargs) -> None:
            selected.append("httpx")

        def close(self) -> None:
            return None

    class ForbiddenClient:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("OpenAI SDK 2.x must use httpx.Client")

    monkeypatch.setattr(
        importlib.metadata,
        "version",
        lambda package: "2.45.0" if package == "openai" else "0.0.0",
    )
    monkeypatch.setitem(
        sys.modules,
        "httpx",
        types.SimpleNamespace(Client=ExpectedClient),
    )
    monkeypatch.setitem(
        sys.modules,
        "httpx2",
        types.SimpleNamespace(Client=ForbiddenClient),
    )

    client = _capture_http_client([])
    try:
        assert selected == ["httpx"]
    finally:
        client.close()


def test_openai_v3_capture_client_uses_httpx2(monkeypatch) -> None:
    selected = []

    class ExpectedClient:
        def __init__(self, *args, **kwargs) -> None:
            selected.append("httpx2")

        def close(self) -> None:
            return None

    class ForbiddenClient:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("OpenAI SDK 3.x must use httpx2.Client")

    monkeypatch.setattr(
        importlib.metadata,
        "version",
        lambda package: "3.6.0" if package == "openai" else "0.0.0",
    )
    monkeypatch.setitem(
        sys.modules,
        "httpx",
        types.SimpleNamespace(Client=ForbiddenClient),
    )
    monkeypatch.setitem(
        sys.modules,
        "httpx2",
        types.SimpleNamespace(Client=ExpectedClient),
    )

    client = _capture_http_client([])
    try:
        assert selected == ["httpx2"]
    finally:
        client.close()


def test_langgraph_gate_is_one_explicit_structured_decision_node() -> None:
    pytest.importorskip("langchain_core")
    pytest.importorskip("langgraph")

    class FakeStructuredModel:
        def __init__(self) -> None:
            self.messages = None

        def invoke(self, messages):
            self.messages = messages
            return {"parsed": {"decision": "pass", "listing_id": None, "rent": None}}

    request = ProviderRequest(
        provider_call_id="provider_call_langgraph_fixture",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        model=GLM_MODEL,
        revision=GLM_REVISION,
        instructions="Return one valid Housing action.",
        input_text='{"observation": {}}',
        temperature=0.0,
        top_p=1.0,
        max_output_tokens=250,
        reasoning_effort="low",
        timeout_seconds=30.0,
        request_sha256="",
        output_schema={
            "type": "object",
            "properties": {
                "decision": {"type": "string"},
                "listing_id": {"type": ["integer", "null"]},
                "rent": {"type": ["number", "null"]},
            },
            "required": ["decision", "listing_id", "rent"],
            "additionalProperties": False,
        },
        provider_metadata={},
        seed=1,
    ).with_computed_hash()
    model = FakeStructuredModel()

    action, trace = _run_langgraph_structured_decision(model, request)

    assert action == {"decision": "pass", "listing_id": None, "rent": None}
    assert trace == {"graph_node_count": 1, "structured_model_calls": 1}
    assert model.messages is not None
    assert [message.type for message in model.messages] == ["system", "human"]


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


def test_framework_event_metrics_count_captured_model_requests() -> None:
    class Event:
        event_type = "provider_call_succeeded"

    class Evidence:
        def read_events(self):
            return [Event()]

        def read_event_payload(self, _event):
            return {
                "provider_result": {
                    "raw_response": {
                        "framework": "langgraph_structured_output",
                        "framework_version": "1.2.11",
                        "framework_model_request_count": 1,
                        "provider_cost_complete": True,
                        "provider_responses": [
                            {
                                "openrouter_metadata": {
                                    "endpoints": {
                                        "available": [
                                            {"provider": "DeepInfra", "selected": True}
                                        ]
                                    }
                                }
                            }
                        ],
                    }
                }
            }

    assert _event_framework_metrics(Evidence()) == {
        "framework_model_request_count": 1,
        "framework_versions": ["1.2.11"],
        "framework_route_verified": True,
        "framework_provider_cost_complete": True,
    }


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
