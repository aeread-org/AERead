from __future__ import annotations

import asyncio
import hashlib
import io
import json
from pathlib import Path

import pytest

from aeread.shared_runner.housing_backend_campaign import (
    _admission_specs,
    catalog_preflight,
    load_contract,
    route_table,
    run_profile_admission,
)
from aeread.shared_runner.execution import ProviderResult
from aeread.shared_runner.housing_model_sensitivity import (
    build_setups,
    design_artifact,
    provider_free_artifact,
)
from aeread.shared_runner.resolver import canonical_json_bytes


CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_model_sensitivity_openrouter_alt_v2.json"
)
V3_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_model_sensitivity_openrouter_alt_v3.json"
)


def test_contract_pins_new_routes_and_requires_admission_before_live() -> None:
    contract = load_contract(CONTRACT_PATH)
    routes = route_table(contract)

    assert contract["campaign_id"] == ("housing_model_sensitivity_openrouter_alt_v2")
    assert routes["glm_53_flash"].provider == "Novita"
    assert routes["deepseek_v4_flash"].provider == "OpenInference"
    assert all(route.quantization == "fp8" for route in routes.values())
    assert contract["backend"]["allow_fallbacks"] is False
    assert contract["profile_admission"]["attempt_limit_per_probe"] == 1
    assert contract["execution"]["winner_claim_allowed"] is False
    assert contract["analysis"]["ranking_allowed"] is False


def test_v3_contract_stays_on_openrouter_with_reka_and_parasail() -> None:
    contract = load_contract(V3_CONTRACT_PATH)
    routes = route_table(contract)

    assert contract["campaign_id"] == "housing_model_sensitivity_openrouter_alt_v3"
    assert contract["backend"]["gateway"] == "openrouter"
    assert routes["glm_53_flash"].provider == "Reka"
    assert routes["deepseek_v4_flash"].provider == "Parasail"
    assert contract["profile_admission"]["cost_ceiling_usd"] == 0.06

    design = design_artifact(contract, routes=routes)
    assert design["status"] == "passed"
    assert design["planned_trajectories"] == 12


def test_design_reuses_cases_but_assigns_new_profile_identities() -> None:
    contract = load_contract(CONTRACT_PATH)
    setups = build_setups(contract, routes=route_table(contract))
    expected_profiles = contract["profile_admission"]["profile_sha256s"]

    assert len(setups) == 12
    for setup in setups.values():
        actual = {
            profile.profile_id: hashlib.sha256(
                canonical_json_bytes(profile)
            ).hexdigest()
            for profile in setup.plan.agent_profiles
        }
        assert actual == {
            profile_id: expected_profiles[profile_id] for profile_id in actual
        }
    design = design_artifact(contract, routes=route_table(contract))
    assert design["planned_trajectories"] == 12
    assert design["complete_model_matrix"] is True
    assert design["ranking_allowed"] is False


def test_provider_free_gate_preserves_the_selected_worlds_and_holdout() -> None:
    result = provider_free_artifact(load_contract(CONTRACT_PATH))

    assert result["status"] == "passed"
    assert result["provider_calls"] == 0
    assert result["provider_cost_usd"] == 0.0
    assert result["confirmatory_holdout_status"] == "sealed_not_executed"
    assert len(result["worlds"]) == 3


def test_admission_matrix_has_three_probes_for_every_role_schema() -> None:
    specs = _admission_specs(load_contract(CONTRACT_PATH))

    assert len(specs) == 18
    assert {spec["model_id"] for spec in specs} == {
        "glm_53_flash",
        "deepseek_v4_flash",
    }
    assert {(spec["role"], spec["action_schema"]) for spec in specs} == {
        ("tenant", "housing_contact_v1"),
        ("tenant", "housing_commit_v1"),
        ("landlord", "housing_respond_v1"),
    }
    assert all(
        sum(
            candidate["model_id"] == spec["model_id"]
            and candidate["role"] == spec["role"]
            and candidate["action_schema"] == spec["action_schema"]
            for candidate in specs
        )
        == 3
        for spec in specs[:6]
    )


class _CatalogResponse(io.StringIO):
    def __enter__(self) -> "_CatalogResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def test_catalog_preflight_requires_exact_active_seed_capable_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = load_contract(CONTRACT_PATH)

    def fake_open(url: str, *, timeout: int) -> _CatalogResponse:
        assert timeout == 30
        model_id = (
            "glm_53_flash" if "z-ai/glm-5.3-flash" in url else "deepseek_v4_flash"
        )
        model = contract["models"][model_id]
        endpoint = {
            "name": f"{model['provider']} | {model['canonical_model']}",
            "provider_name": model["provider"],
            "quantization": model["quantization"],
            "pricing": {
                "prompt": str(model["input_per_million"] / 1_000_000),
                "input_cache_read": str(model["cached_input_per_million"] / 1_000_000),
                "completion": str(model["output_per_million"] / 1_000_000),
            },
            "supported_parameters": sorted(
                {
                    "max_tokens",
                    "reasoning_effort",
                    "response_format",
                    "seed",
                    "temperature",
                    "top_p",
                }
            ),
            "status": 0,
            "max_completion_tokens": 4096,
            "uptime_last_5m": 100.0,
            "uptime_last_30m": 100.0,
            "uptime_last_1d": 100.0,
        }
        return _CatalogResponse(json.dumps({"data": {"endpoints": [endpoint]}}))

    monkeypatch.setattr(
        "aeread.shared_runner.housing_backend_campaign.urllib.request.urlopen",
        fake_open,
    )

    result = catalog_preflight(contract)

    assert result["status"] == "passed"
    assert result["provider_inference_calls"] == 0
    assert {row["provider"] for row in result["routes"]} == {
        "Novita",
        "OpenInference",
    }


def test_catalog_preflight_rejects_an_endpoint_below_the_frozen_output_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = load_contract(V3_CONTRACT_PATH)
    model = contract["models"]["glm_53_flash"]

    def fake_open(_url: str, *, timeout: int) -> _CatalogResponse:
        assert timeout == 30
        endpoint = {
            "name": f"{model['provider']} | {model['canonical_model']}",
            "provider_name": model["provider"],
            "quantization": model["quantization"],
            "pricing": {
                "prompt": str(model["input_per_million"] / 1_000_000),
                "input_cache_read": str(model["cached_input_per_million"] / 1_000_000),
                "completion": str(model["output_per_million"] / 1_000_000),
            },
            "supported_parameters": sorted(
                {
                    "max_tokens",
                    "reasoning_effort",
                    "response_format",
                    "seed",
                    "temperature",
                    "top_p",
                }
            ),
            "status": 0,
            "max_completion_tokens": 2048,
        }
        return _CatalogResponse(json.dumps({"data": {"endpoints": [endpoint]}}))

    monkeypatch.setattr(
        "aeread.shared_runner.housing_backend_campaign.urllib.request.urlopen",
        fake_open,
    )

    with pytest.raises(ValueError, match="completion limit is too small"):
        catalog_preflight(contract)


def test_contract_rejects_in_campaign_fallback_or_route_changes(
    tmp_path: Path,
) -> None:
    value = json.loads(CONTRACT_PATH.read_bytes())
    value["backend"]["allow_fallbacks"] = True
    path = tmp_path / "fallback.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="backend contract drifted"):
        load_contract(path)

    value = json.loads(CONTRACT_PATH.read_bytes())
    value["models"]["glm_53_flash"]["provider"] = "DeepInfra"
    path = tmp_path / "route.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="alternate route drifted"):
        load_contract(path)


def test_semantically_invalid_admission_retains_raw_response_and_billing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    contract = load_contract(CONTRACT_PATH)

    class InvalidActionClient:
        async def complete(self, request: object) -> ProviderResult:
            return ProviderResult(
                response_id="invalid-action-fixture",
                requested_model=request.model,
                resolved_model=request.revision,
                output_text='{"invalid":true}',
                finish_reason="stop",
                input_tokens=100,
                cached_input_tokens=0,
                output_tokens=10,
                cost_usd=0.0001,
                raw_response={
                    "id": "invalid-action-fixture",
                    "model": request.revision,
                    "choices": [{"message": {"content": '{"invalid":true}'}}],
                },
            )

    monkeypatch.setattr(
        "aeread.shared_runner.housing_backend_campaign.OpenRouterChatClient",
        InvalidActionClient,
    )

    result = asyncio.run(
        run_profile_admission(contract, output_root=tmp_path / "admission")
    )

    assert result["status"] == "failed_with_typed_missingness"
    assert result["attempted_probe_count"] == 18
    assert result["provider_cost_complete"] is True
    assert result["observed_cost_usd"] == pytest.approx(0.0018)
    assert {row["failure_condition"] for row in result["rows"]} == {
        "invalid_admission_action"
    }
    assert all(row["raw_response_sha256"] for row in result["rows"])
    assert all(row["route_verified"] is True for row in result["rows"])
    assert len(list((tmp_path / "admission").rglob("probe_*_raw.json"))) == 18


def test_published_backend_qualification_is_digest_bound() -> None:
    path = (
        CONTRACT_PATH.parents[1]
        / "docs"
        / "evidence"
        / "housing_model_sensitivity_openrouter_alt_v2_qualification_2026-09-02.json"
    )
    value = json.loads(path.read_bytes())
    core = {key: item for key, item in value.items() if key != "artifact_sha256"}

    assert (
        value["artifact_sha256"]
        == hashlib.sha256(canonical_json_bytes(core)).hexdigest()
    )
    assert value["gate_status"][-1]["status"] == "blocked_by_profile_admission"
    assert value["gate_status"][-1]["provider_calls"] == 0
    assert value["source_case_selection"]["confirmatory_holdout_status"] == (
        "sealed_not_executed"
    )
    assert value["ranking_allowed"] is False


def test_published_v3_qualification_is_digest_bound_and_has_no_scores() -> None:
    path = (
        V3_CONTRACT_PATH.parents[1]
        / "docs"
        / "evidence"
        / "housing_model_sensitivity_openrouter_alt_v3_qualification_2026-09-02.json"
    )
    value = json.loads(path.read_bytes())
    core = {key: item for key, item in value.items() if key != "artifact_sha256"}

    assert (
        value["artifact_sha256"]
        == hashlib.sha256(canonical_json_bytes(core)).hexdigest()
    )
    assert value["gate_status"][-1]["status"] == "blocked_by_profile_admission"
    assert value["gate_status"][-1]["provider_calls"] == 0
    assert "score" not in value
    assert value["ranking_allowed"] is False
