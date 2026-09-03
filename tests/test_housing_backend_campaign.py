from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
from pathlib import Path

import pytest

from aeread_families.housing.backend_campaign import (
    _admission_specs,
    _endpoint_snapshot_sha256,
    catalog_preflight,
    load_contract,
    route_table,
    run_profile_admission,
)
from aeread.shared_runner.task.execution import ProviderResult
from aeread_families.housing.model_sensitivity import (
    build_setups,
    design_artifact,
    provider_free_artifact,
    variance_pilot_analysis,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes


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
V4_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_model_sensitivity_openrouter_alt_v4.json"
)
V5_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_model_sensitivity_openrouter_alt_v5.json"
)
V6_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_model_sensitivity_openrouter_alt_v6.json"
)
V7_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_model_sensitivity_openrouter_alt_v7.json"
)
V8_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_model_sensitivity_openrouter_alt_v8.json"
)
V9_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_model_sensitivity_openrouter_alt_v9.json"
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


def test_v4_contract_stays_on_openrouter_with_phala_and_parasail() -> None:
    contract = load_contract(V4_CONTRACT_PATH)
    routes = route_table(contract)

    assert contract["campaign_id"] == "housing_model_sensitivity_openrouter_alt_v4"
    assert contract["backend"]["gateway"] == "openrouter"
    assert contract["backend"]["allow_fallbacks"] is False
    assert contract["backend"]["require_parameters"] is True
    assert routes["glm_53_flash"].provider == "Phala"
    assert routes["deepseek_v4_flash"].provider == "Parasail"
    assert contract["profile_admission"]["cost_ceiling_usd"] == 0.06

    design = design_artifact(contract, routes=routes)
    assert design["status"] == "passed"
    assert design["planned_trajectories"] == 12


def test_v5_contract_stays_on_openrouter_with_nextbit_and_parasail() -> None:
    contract = load_contract(V5_CONTRACT_PATH)
    routes = route_table(contract)

    assert contract["campaign_id"] == "housing_model_sensitivity_openrouter_alt_v5"
    assert contract["backend"]["gateway"] == "openrouter"
    assert contract["backend"]["allow_fallbacks"] is False
    assert contract["backend"]["require_parameters"] is True
    assert routes["glm_53_flash"].provider == "NextBit"
    assert routes["deepseek_v4_flash"].provider == "Parasail"
    assert contract["profile_admission"]["cost_ceiling_usd"] == 0.06

    design = design_artifact(contract, routes=routes)
    assert design["status"] == "passed"
    assert design["planned_trajectories"] == 12


def test_v6_contract_adds_visible_empty_response_retries() -> None:
    contract = load_contract(V6_CONTRACT_PATH)
    routes = route_table(contract)

    assert contract["campaign_id"] == "housing_model_sensitivity_openrouter_alt_v6"
    assert routes["glm_53_flash"].provider == "NextBit"
    assert routes["deepseek_v4_flash"].provider == "Parasail"
    assert contract["controls"]["retryable_conditions"] == [
        "length",
        "rate_limit",
        "provider_5xx",
        "empty_response",
    ]
    assert contract["controls"]["max_action_attempts"] == 4
    assert contract["controls"]["sdk_retries"] == 0


def test_v7_profiles_bind_conditional_schemas_and_declared_retries() -> None:
    contract = load_contract(V7_CONTRACT_PATH)
    setups = build_setups(contract, routes=route_table(contract))

    assert contract["controls"]["action_schema_version"] == "housing_actions/2.0"
    assert contract["controls"]["wire_live_profile_controls"] is True
    for setup in setups.values():
        for profile in setup.plan.agent_profiles:
            assert profile.retry_policy.retryable_conditions == (
                "length",
                "rate_limit",
                "provider_5xx",
                "empty_response",
            )
            schemas = profile.harness.config["output_schema_by_action_schema"]
            assert all("oneOf" in schema for schema in schemas.values())


def test_v8_repeats_the_full_matrix_with_calibrated_cost_guards() -> None:
    contract = load_contract(V8_CONTRACT_PATH)
    setups = build_setups(contract, routes=route_table(contract))

    assert contract["campaign_id"] == "housing_model_sensitivity_openrouter_alt_v8"
    assert contract["execution"]["cost_ceiling_usd"] == 0.10
    assert contract["execution"]["per_trajectory_cost_reserve_usd"] == 0.01
    assert contract["execution"]["world_seeds"] == [1971418798]
    assert len(setups) == 12
    expected_profiles = contract["profile_admission"]["profile_sha256s"]
    for setup in setups.values():
        for profile in setup.plan.agent_profiles:
            assert hashlib.sha256(canonical_json_bytes(profile)).hexdigest() == (
                expected_profiles[profile.profile_id]
            )


def test_v9_freezes_four_unused_development_worlds_and_48_paired_cells() -> None:
    contract = load_contract(V9_CONTRACT_PATH)
    routes = route_table(contract)
    design = design_artifact(contract, routes=routes)
    provider_free = provider_free_artifact(contract)
    case_contract = json.loads(
        (V9_CONTRACT_PATH.parent / "housing_case_config_sweep_v1.json").read_bytes()
    )
    holdout_seeds = set(case_contract["confirmatory_holdout"]["world_seeds"])

    assert contract["claim_status"] == "exploratory_variance_pilot_only"
    assert contract["execution"]["world_seeds"] == [
        1460378342,
        981417412,
        123194022,
        145537168,
    ]
    assert 1971418798 not in contract["execution"]["world_seeds"]
    assert not holdout_seeds.intersection(contract["execution"]["world_seeds"])
    assert contract["execution"]["cost_ceiling_usd"] == 0.35
    assert contract["execution"]["per_trajectory_cost_reserve_usd"] == 0.01
    assert design["planned_trajectories"] == 48
    assert len(design["plans"]) == 48
    assert len({row["cell_id"] for row in design["plans"]}) == 48
    assert {row["world_seed"] for row in design["plans"]} == set(
        contract["execution"]["world_seeds"]
    )
    assert provider_free["status"] == "passed"
    assert provider_free["confirmatory_holdout_status"] == "sealed_not_executed"
    assert len(provider_free["worlds"]) == 12
    assert all(
        row["oracle_crosscheck_passed"] and row["oracle_active_ceiling_passed"]
        for row in provider_free["worlds"]
    )

    expected_profiles = contract["profile_admission"]["profile_sha256s"]
    for setup in build_setups(contract, routes=routes).values():
        for profile in setup.plan.agent_profiles:
            assert hashlib.sha256(canonical_json_bytes(profile)).hexdigest() == (
                expected_profiles[profile.profile_id]
            )


def test_v9_variance_analysis_uses_complete_world_pairs_and_not_cells() -> None:
    contract = load_contract(V9_CONTRACT_PATH)
    rows: list[dict[str, object]] = []
    world_offsets = [0.00, 0.02, -0.01, 0.03]
    for world_seed, offset in zip(
        contract["execution"]["world_seeds"], world_offsets, strict=True
    ):
        for config_index, config_id in enumerate(
            ("mild_cw085_r2", "moderate_cw085_r2", "severe_cw030_r2")
        ):
            for condition in contract["conditions"]:
                subject_bonus = 0.10 if condition["subject"] == "glm_53_flash" else 0
                opponent_bonus = (
                    0.01 if condition["opponent"] == "glm_53_flash" else 0
                )
                rows.append(
                    {
                        "config_id": config_id,
                        "condition_id": condition["condition_id"],
                        "subject": condition["subject"],
                        "opponent": condition["opponent"],
                        "world_seed": world_seed,
                        "status": "completed",
                        "within_case_score": (
                            0.50
                            + offset
                            + 0.02 * config_index
                            + subject_bonus
                            + opponent_bonus
                        ),
                    }
                )

    result = variance_pilot_analysis(rows, contract)

    assert result["status"] == "estimable"
    assert result["paired_world_count"] == 4
    assert result["expected_cells_per_subject_per_world"] == 6
    assert result["mean_paired_contrast"] == pytest.approx(0.10)
    assert result["sample_variance"] == pytest.approx(0.0)
    assert result["recommended_confirmatory_worlds"] == 30
    assert result["ranking_allowed"] is False

    rows[0]["status"] = "operational_failure"
    rows[0].pop("within_case_score")
    incomplete = variance_pilot_analysis(rows, contract)
    assert incomplete["paired_world_count"] == 3
    assert incomplete["incomplete_world_count"] == 1
    assert incomplete["worlds"][0]["complete_pair"] is False


def test_multiworld_generalization_preserves_v8_gate_digests() -> None:
    contract = load_contract(V8_CONTRACT_PATH)
    qualification = json.loads(
        (
            V8_CONTRACT_PATH.parents[1]
            / "evidence"
            / contract["campaign_id"]
            / "reports"
            / "qualification.json"
        ).read_bytes()
    )
    gates = {row["gate_id"]: row for row in qualification["gate_status"]}

    assert design_artifact(contract, routes=route_table(contract))[
        "artifact_sha256"
    ] == gates["design"]["artifact_sha256"]
    assert provider_free_artifact(contract)["artifact_sha256"] == gates[
        "provider_free"
    ]["artifact_sha256"]


def test_v8_catalog_preflight_binds_stable_endpoint_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = load_contract(V8_CONTRACT_PATH)
    endpoints: dict[str, dict[str, object]] = {}
    for model_id, model in contract["models"].items():
        endpoint = {
            "name": f"{model['provider']} | {model['canonical_model']}",
            "provider_name": model["provider"],
            "quantization": model["quantization"],
            "pricing": {
                "prompt": str(model["input_per_million"] / 1_000_000),
                "input_cache_read": str(
                    model["cached_input_per_million"] / 1_000_000
                ),
                "completion": str(model["output_per_million"] / 1_000_000),
            },
            "supported_parameters": sorted(
                {
                    "max_tokens",
                    "reasoning_effort",
                    "response_format",
                    "seed",
                    "structured_outputs",
                    "temperature",
                    "top_p",
                }
            ),
            "status": 0,
            "max_completion_tokens": 4096,
            "uptime_last_5m": 100.0,
            "uptime_last_30m": 100.0,
        }
        model["endpoint_snapshot_sha256"] = _endpoint_snapshot_sha256(endpoint)
        endpoints[model_id] = endpoint

    def fake_open(url: str, *, timeout: int) -> _CatalogResponse:
        assert timeout == 30
        model_id = (
            "glm_53_flash" if "z-ai/glm-5.3-flash" in url else "deepseek_v4_flash"
        )
        return _CatalogResponse(
            json.dumps({"data": {"endpoints": [endpoints[model_id]]}})
        )

    monkeypatch.setattr(
        "aeread_families.housing.backend_campaign.urllib.request.urlopen",
        fake_open,
    )
    result = catalog_preflight(contract)
    assert result["status"] == "passed"
    assert all(row["endpoint_snapshot_sha256"] for row in result["routes"])

    contract["models"]["glm_53_flash"]["endpoint_snapshot_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="endpoint snapshot drifted"):
        catalog_preflight(contract)


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
                    "structured_outputs",
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
        "aeread_families.housing.backend_campaign.urllib.request.urlopen",
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
                    "structured_outputs",
                    "temperature",
                    "top_p",
                }
            ),
            "status": 0,
            "max_completion_tokens": 2048,
        }
        return _CatalogResponse(json.dumps({"data": {"endpoints": [endpoint]}}))

    monkeypatch.setattr(
        "aeread_families.housing.backend_campaign.urllib.request.urlopen",
        fake_open,
    )

    with pytest.raises(ValueError, match="completion limit is too small"):
        catalog_preflight(contract)


def test_catalog_preflight_requires_strict_structured_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = load_contract(V4_CONTRACT_PATH)

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
                "input_cache_read": str(
                    model["cached_input_per_million"] / 1_000_000
                ),
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
        }
        return _CatalogResponse(json.dumps({"data": {"endpoints": [endpoint]}}))

    monkeypatch.setattr(
        "aeread_families.housing.backend_campaign.urllib.request.urlopen",
        fake_open,
    )

    with pytest.raises(ValueError, match="parameter support drifted"):
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
        "aeread_families.housing.backend_campaign.OpenRouterChatClient",
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
        / "evidence"
        / "housing_model_sensitivity_openrouter_alt_v2"
        / "reports"
        / "qualification.json"
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
        / "evidence"
        / "housing_model_sensitivity_openrouter_alt_v3"
        / "reports"
        / "qualification.json"
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


def test_published_v4_qualification_is_digest_bound_and_blocks_live() -> None:
    path = (
        V4_CONTRACT_PATH.parents[1]
        / "evidence"
        / "housing_model_sensitivity_openrouter_alt_v4"
        / "reports"
        / "qualification.json"
    )
    value = json.loads(path.read_bytes())
    core = {key: item for key, item in value.items() if key != "artifact_sha256"}

    assert (
        value["artifact_sha256"]
        == hashlib.sha256(canonical_json_bytes(core)).hexdigest()
    )
    assert value["gate_status"][-1]["status"] == "blocked_by_profile_admission"
    assert value["gate_status"][-1]["provider_calls"] == 0
    assert value["profile_results"][0]["passed_probes"] == 1
    assert value["profile_results"][1]["passed_probes"] == 9
    assert "score" not in value
    assert value["ranking_allowed"] is False


@pytest.mark.parametrize(
    ("contract_path", "campaign_id", "expected_status"),
    [
        (
            V5_CONTRACT_PATH,
            "housing_model_sensitivity_openrouter_alt_v5",
            "stopped_with_typed_missingness",
        ),
        (
            V6_CONTRACT_PATH,
            "housing_model_sensitivity_openrouter_alt_v6",
            "blocked_by_profile_admission",
        ),
        (
            V7_CONTRACT_PATH,
            "housing_model_sensitivity_openrouter_alt_v7",
            "stopped_with_typed_missingness",
        ),
    ],
)
def test_published_recent_qualifications_are_digest_bound(
    contract_path: Path, campaign_id: str, expected_status: str
) -> None:
    path = (
        contract_path.parents[1]
        / "evidence"
        / campaign_id
        / "reports"
        / "qualification.json"
    )
    value = json.loads(path.read_bytes())
    core = {key: item for key, item in value.items() if key != "artifact_sha256"}

    assert value["artifact_sha256"] == hashlib.sha256(
        canonical_json_bytes(core)
    ).hexdigest()
    assert value["campaign_id"] == campaign_id
    assert value["status"] == expected_status
    assert value["ranking_allowed"] is False
    assert value["winner_claim_allowed"] is False
    assert value["contract_location_amendment"]["executed_contract_sha256"]
    assert value["contract_location_amendment"]["current_contract_sha256"]
    assert value["publication_policy"]["raw_provider_responses_included"] is False


def test_published_v7_trajectories_are_digest_bound_and_non_rankable() -> None:
    path = (
        V7_CONTRACT_PATH.parents[1]
        / "evidence"
        / "housing_model_sensitivity_openrouter_alt_v7"
        / "trajectories"
        / "selected.json"
    )
    value = json.loads(path.read_bytes())
    core = {key: item for key, item in value.items() if key != "artifact_sha256"}

    assert value["artifact_sha256"] == hashlib.sha256(
        canonical_json_bytes(core)
    ).hexdigest()
    assert len(value["trajectories"]) == 7
    assert value["ranking_allowed"] is False
    assert value["raw_provider_responses_included"] is False
    assert value["model_reasoning_included"] is False
    assert all(row["route_verified"] for row in value["trajectories"])
    assert all(row["replay_verified"] for row in value["trajectories"])
    assert all(row["provider_cost_complete"] for row in value["trajectories"])

    qualification_path = path.parents[1] / "reports" / "qualification.json"
    qualification = json.loads(qualification_path.read_bytes())
    assert qualification["trajectory_export"]["artifact_sha256"] == value[
        "artifact_sha256"
    ]


def test_published_v8_qualification_and_attempts_are_digest_bound() -> None:
    root = (
        V8_CONTRACT_PATH.parents[1]
        / "evidence"
        / "housing_model_sensitivity_openrouter_alt_v8"
    )
    qualification = json.loads(
        (root / "reports" / "qualification.json").read_bytes()
    )
    trajectories = json.loads(
        (root / "trajectories" / "attempted.json").read_bytes()
    )
    for value in (qualification, trajectories):
        core = {key: item for key, item in value.items() if key != "artifact_sha256"}
        assert value["artifact_sha256"] == hashlib.sha256(
            canonical_json_bytes(core)
        ).hexdigest()

    assert qualification["status"] == "completed_with_typed_missingness"
    assert qualification["acceptance"] == {
        "publishable_integration_evidence": True,
        "all_frozen_cells_attempted": True,
        "prerequisite_gates_passed": True,
        "typed_missingness_preserved": True,
        "leaderboard_eligible": False,
    }
    assert qualification["trajectory_export"]["artifact_sha256"] == trajectories[
        "artifact_sha256"
    ]
    assert trajectories["planned_trajectories"] == 12
    assert trajectories["attempted_trajectories"] == 12
    assert trajectories["completed_trajectories"] == 11
    assert trajectories["operational_failures"] == 1
    assert (
        sum(row["status"] == "completed" for row in trajectories["trajectories"])
        == 11
    )
    failure = next(
        row for row in trajectories["trajectories"] if row["status"] != "completed"
    )
    assert failure["failure_condition"] == "timeout"
    assert failure["inclusion_status"] == "excluded"
    assert failure["score"] is None
    serialized = json.dumps(
        {"qualification": qualification, "trajectories": trajectories}
    )
    assert "raw_response" not in serialized
    assert "output_text" not in serialized
    assert "/Users/" not in serialized


def test_published_v9_block_and_fact_tables_are_digest_bound() -> None:
    root = (
        V9_CONTRACT_PATH.parents[1]
        / "evidence"
        / "housing_model_sensitivity_openrouter_alt_v9"
    )
    qualification = json.loads(
        (root / "reports" / "qualification.json").read_bytes()
    )
    trajectories = json.loads(
        (root / "trajectories" / "attempted.json").read_bytes()
    )
    manifest = json.loads((root / "tables" / "fact_manifest.json").read_bytes())
    for value in (qualification, trajectories, manifest):
        core = {key: item for key, item in value.items() if key != "artifact_sha256"}
        assert value["artifact_sha256"] == hashlib.sha256(
            canonical_json_bytes(core)
        ).hexdigest()

    assert qualification["status"] == "blocked_by_profile_admission"
    assert qualification["acceptance"]["publishable_gate_evidence"] is True
    assert qualification["acceptance"]["publishable_integration_evidence"] is False
    assert qualification["gate_status"][-1]["attempted_trajectories"] == 0
    assert qualification["gate_status"][-1]["not_started_trajectories"] == 48
    assert qualification["failed_admission_probes"] == [
        {
            "action_schema": "housing_respond_v1",
            "artifact_sha256": "4806f294cfc09407da938964a53a5ee30ee8ca2bb61b2d5e754a596b1785703a",
            "billing_status": "unavailable_on_failed_call",
            "failure_condition": "rate_limit",
            "failure_status_code": 429,
            "failure_type": "ProviderFailure",
            "model_id": "glm_53_flash",
            "probe_index": 1,
            "role": "landlord",
        }
    ]
    assert trajectories["planned_trajectories"] == 48
    assert trajectories["attempted_trajectories"] == 0
    assert trajectories["trajectories"] == []

    for table in manifest["artifacts"].values():
        path = V9_CONTRACT_PATH.parents[1] / table["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == table["sha256"]
        with path.open(newline="", encoding="utf-8") as handle:
            assert len(list(csv.DictReader(handle))) == table["row_count"]
    serialized = json.dumps(
        {"qualification": qualification, "trajectories": trajectories}
    )
    assert "raw_response" not in serialized
    assert "output_text" not in serialized
    assert "/Users/" not in serialized
