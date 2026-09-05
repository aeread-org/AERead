from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aeread_families.housing.backend_campaign import (
    _admission_complete,
    _admission_specs,
    _endpoint_snapshot_sha256,
    catalog_preflight,
    execute_campaign,
    load_contract,
    route_table,
    run_profile_admission,
)
from aeread.shared_runner.task.execution import (
    EvidenceIntegrityError,
    ProviderFailure,
    ProviderResult,
)
from aeread_families.housing.provider_cooldown import CooldownProviderClient
from aeread_families.housing.model_sensitivity import (
    PacedProviderClient,
    build_setups,
    design_artifact,
    provider_free_artifact,
    run_live,
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
V10_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_model_sensitivity_openrouter_morph_v10.json"
)
V11_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_model_sensitivity_openrouter_deepinfra_v11.json"
)
V12_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_model_sensitivity_openrouter_deepinfra_v12.json"
)
V13_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_model_sensitivity_openrouter_friendli_v13.json"
)
V14_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_model_sensitivity_openrouter_friendli_v14.json"
)
V15_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_model_sensitivity_openrouter_friendli_v15.json"
)
V16_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_model_sensitivity_openrouter_parasail_v16.json"
)
V17_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_model_sensitivity_openrouter_parasail_v17.json"
)
V18_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_model_sensitivity_openrouter_parasail_v18.json"
)
V19_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_model_sensitivity_openrouter_parasail_v19.json"
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


def test_v10_changes_only_glm_route_identity_and_stays_under_user_budget() -> None:
    v9 = load_contract(V9_CONTRACT_PATH)
    v10 = load_contract(V10_CONTRACT_PATH)
    routes = route_table(v10)

    assert routes["glm_53_flash"].provider == "Morph"
    assert routes["deepseek_v4_flash"].provider == "Parasail"
    assert v10["models"]["glm_53_flash"]["input_per_million"] == 0.13
    assert v10["models"]["glm_53_flash"]["output_per_million"] == 0.45
    assert v10["execution"] == v9["execution"]
    assert v10["analysis"] == v9["analysis"]
    assert v10["conditions"] == v9["conditions"]
    assert (
        v10["profile_admission"]["cost_ceiling_usd"]
        + v10["execution"]["cost_ceiling_usd"]
        < 5.0
    )
    assert design_artifact(v10, routes=routes)["planned_trajectories"] == 48
    assert len(provider_free_artifact(v10)["worlds"]) == 12

    expected_profiles = v10["profile_admission"]["profile_sha256s"]
    for setup in build_setups(v10, routes=routes).values():
        for profile in setup.plan.agent_profiles:
            assert hashlib.sha256(canonical_json_bytes(profile)).hexdigest() == (
                expected_profiles[profile.profile_id]
            )


def test_v11_freezes_a_four_condition_full_trajectory_gate() -> None:
    contract = load_contract(V11_CONTRACT_PATH)
    routes = route_table(contract)
    case_contract = json.loads(
        (V11_CONTRACT_PATH.parent / "housing_case_config_sweep_v1.json").read_bytes()
    )

    assert contract["claim_status"] == "development_full_trajectory_gate_only"
    assert contract["execution"]["stage"] == "full_trajectory"
    assert contract["execution"]["config_ids"] == ["moderate_cw085_r2"]
    assert contract["execution"]["world_seeds"] == [227922569]
    assert 227922569 not in case_contract["confirmatory_holdout"]["world_seeds"]
    assert routes["glm_53_flash"].provider == "DeepInfra"
    assert routes["deepseek_v4_flash"].provider == "Parasail"
    assert contract["profile_admission"]["cost_ceiling_usd"] + contract[
        "execution"
    ]["cost_ceiling_usd"] == pytest.approx(0.14)

    design = design_artifact(contract, routes=routes)
    provider_free = provider_free_artifact(contract)
    assert design["artifact_sha256"] == (
        "5ead3480740ef7105a8c94d486c2f0e896c0682d15974a8eae1780ebdde04ea8"
    )
    assert design["planned_trajectories"] == 4
    assert design["configuration_count"] == 1
    assert design["condition_count"] == 4
    assert len({row["condition_id"] for row in design["plans"]}) == 4
    assert provider_free["status"] == "passed"
    assert len(provider_free["worlds"]) == 1
    assert provider_free["confirmatory_holdout_status"] == "sealed_not_executed"

    expected_profiles = contract["profile_admission"]["profile_sha256s"]
    for setup in build_setups(contract, routes=routes).values():
        for profile in setup.plan.agent_profiles:
            assert hashlib.sha256(canonical_json_bytes(profile)).hexdigest() == (
                expected_profiles[profile.profile_id]
            )


def test_v12_changes_only_campaign_identity_profiles_and_call_pacing() -> None:
    v11 = load_contract(V11_CONTRACT_PATH)
    v12 = load_contract(V12_CONTRACT_PATH)
    routes = route_table(v12)

    assert v12["execution"] == v11["execution"]
    assert v12["analysis"] == v11["analysis"]
    assert v12["conditions"] == v11["conditions"]
    assert v12["controls"]["call_pacing"] == {
        "clock": "monotonic_start_to_start",
        "minimum_interval_seconds_by_provider": {
            "DeepInfra": 15.0,
            "Parasail": 15.0,
        },
        "first_call_delay_seconds": 15.0,
        "scope": "shared_across_profile_admission_and_full_trajectory",
        "implementation_sha256": (
            "6e51c13330a2aa73e4b9f8e7610c0cc232873b1aecaf1b85960a3db2ab8790cd"
        ),
    }
    assert routes["glm_53_flash"].provider == "DeepInfra"
    assert routes["deepseek_v4_flash"].provider == "Parasail"
    assert (
        v12["profile_admission"]["cost_ceiling_usd"]
        + v12["execution"]["cost_ceiling_usd"]
        == pytest.approx(0.14)
    )
    assert design_artifact(v12, routes=routes)["artifact_sha256"] == (
        "e26b9f1e43ce5976f5e17c53749880f1f4512e5f3442f386edcffc176d8c08c5"
    )
    assert provider_free_artifact(v12)["artifact_sha256"] == (
        "a0e032b4f6a8131845879addbc9a837e47b77d64eac15a9742a41d8eca246203"
    )

    expected_profiles = v12["profile_admission"]["profile_sha256s"]
    for setup in build_setups(v12, routes=routes).values():
        for profile in setup.plan.agent_profiles:
            assert hashlib.sha256(canonical_json_bytes(profile)).hexdigest() == (
                expected_profiles[profile.profile_id]
            )


def test_paced_provider_client_enforces_route_specific_start_intervals() -> None:
    class Clock:
        def __init__(self) -> None:
            self.now = 0.0
            self.waits: list[float] = []

        def __call__(self) -> float:
            return self.now

        async def sleep(self, seconds: float) -> None:
            self.waits.append(seconds)
            self.now += seconds

    class Delegate:
        def __init__(self) -> None:
            self.providers: list[str] = []

        async def complete(self, request: object) -> object:
            self.providers.append(request.provider_metadata["route_provider"])
            return object()

    async def exercise() -> tuple[Clock, Delegate, PacedProviderClient]:
        clock = Clock()
        delegate = Delegate()
        client = PacedProviderClient(
            delegate,
            minimum_interval_seconds_by_provider={
                "DeepInfra": 15.0,
                "Parasail": 10.0,
            },
            first_call_delay_seconds=5.0,
            clock=clock,
            sleeper=clock.sleep,
        )
        for provider in ("DeepInfra", "DeepInfra", "Parasail", "Parasail"):
            await client.complete(
                SimpleNamespace(provider_metadata={"route_provider": provider})
            )
        return clock, delegate, client

    clock, delegate, client = asyncio.run(exercise())

    assert clock.waits == [5.0, 15.0, 5.0, 10.0]
    assert delegate.providers == ["DeepInfra", "DeepInfra", "Parasail", "Parasail"]
    assert client.pacing_summary_since(0) == {
        "provider_calls": 4,
        "paced_call_count": 4,
        "pacing_wait_seconds": 35.0,
        "by_provider": {
            "DeepInfra": {"provider_calls": 2, "pacing_wait_seconds": 20.0},
            "Parasail": {"provider_calls": 2, "pacing_wait_seconds": 15.0},
        },
    }


def test_v13_changes_only_identity_glm_route_cooldown_and_admission_timeout() -> None:
    v12 = load_contract(V12_CONTRACT_PATH)
    v13 = load_contract(V13_CONTRACT_PATH)
    routes = route_table(v13)

    assert v13["execution"] == v12["execution"]
    assert v13["analysis"] == v12["analysis"]
    assert v13["conditions"] == v12["conditions"]
    assert v13["source_case_selection"] == v12["source_case_selection"]
    unchanged = {
        key: value
        for key, value in v13["controls"].items()
        if key
        not in {"reasoning_condition_id", "call_pacing", "admission_timeout_enforcement"}
    }
    assert unchanged == {
        key: value
        for key, value in v12["controls"].items()
        if key not in {"reasoning_condition_id", "call_pacing"}
    }
    assert v13["controls"]["call_pacing"] == {
        "clock": "monotonic_completion_to_start",
        "cooldown_seconds_by_provider": {"Friendli": 10.0, "Parasail": 10.0},
        "first_call_delay_seconds": 0.0,
        "scope": "shared_across_profile_admission_and_full_trajectory",
        "implementation_sha256": (
            "4dc67f4ae81395166264049bbf917d8d42e69c5d6069c97fea981c4b419415d3"
        ),
    }
    assert v13["controls"]["call_pacing"]["implementation_sha256"] == (
        hashlib.sha256(
            (
                V13_CONTRACT_PATH.parents[1]
                / "src"
                / "aeread_families"
                / "housing"
                / "provider_cooldown.py"
            ).read_bytes()
        ).hexdigest()
    )
    assert v13["controls"]["admission_timeout_enforcement"] == (
        "asyncio_wait_for_controls_timeout_seconds"
    )
    assert routes["glm_53_flash"].provider == "Friendli"
    assert routes["glm_53_flash"].quantization == "unknown"
    assert routes["deepseek_v4_flash"].provider == "Parasail"
    assert v13["models"]["deepseek_v4_flash"]["endpoint_snapshot_sha256"] == (
        v12["models"]["deepseek_v4_flash"]["endpoint_snapshot_sha256"]
    )
    assert (
        v13["profile_admission"]["cost_ceiling_usd"]
        + v13["execution"]["cost_ceiling_usd"]
        == pytest.approx(0.14)
    )
    assert design_artifact(v13, routes=routes)["artifact_sha256"] == (
        "4627be3c85e2a85f27d5d38e0fa3c04fe141f2b448de402abbf658ad63e96db5"
    )
    assert provider_free_artifact(v13)["artifact_sha256"] == (
        "f1906b194b7df6ad039cb821315d1e21d0038f7c14a9f498186721837cb2c430"
    )

    expected_profiles = v13["profile_admission"]["profile_sha256s"]
    for setup in build_setups(v13, routes=routes).values():
        for profile in setup.plan.agent_profiles:
            assert hashlib.sha256(canonical_json_bytes(profile)).hexdigest() == (
                expected_profiles[profile.profile_id]
            )


def test_cooldown_provider_client_measures_from_completion_and_serialises() -> None:
    class Clock:
        def __init__(self) -> None:
            self.now = 0.0
            self.waits: list[float] = []

        def __call__(self) -> float:
            return self.now

        async def sleep(self, seconds: float) -> None:
            self.waits.append(seconds)
            self.now += seconds

    class Delegate:
        def __init__(self, clock: Clock) -> None:
            self.clock = clock
            self.providers: list[str] = []

        async def complete(self, request: object) -> object:
            self.providers.append(request.provider_metadata["route_provider"])
            # A slow call: the next call must wait the full cooldown after this
            # completion, not from this start (the V12 defect).
            self.clock.now += request.provider_metadata.get("duration", 0.0)
            if request.provider_metadata.get("fail"):
                raise ProviderFailure("rate_limit", "429", retryable=True)
            return object()

    async def exercise() -> tuple[Clock, Delegate, CooldownProviderClient]:
        clock = Clock()
        delegate = Delegate(clock)
        client = CooldownProviderClient(
            delegate,
            cooldown_seconds_by_provider={"Friendli": 10.0, "Parasail": 10.0},
            first_call_delay_seconds=0.0,
            clock=clock,
            sleeper=clock.sleep,
        )
        calls = (
            {"route_provider": "Friendli", "duration": 140.0},
            {"route_provider": "Friendli", "duration": 1.0, "fail": True},
            {"route_provider": "Friendli", "duration": 1.0},
            {"route_provider": "Parasail", "duration": 1.0},
            {"route_provider": "Parasail", "duration": 1.0},
        )
        for metadata in calls:
            try:
                await client.complete(SimpleNamespace(provider_metadata=metadata))
            except ProviderFailure:
                pass
        return clock, delegate, client

    clock, delegate, client = asyncio.run(exercise())

    assert clock.waits == [10.0, 10.0, 10.0]
    assert delegate.providers == [
        "Friendli",
        "Friendli",
        "Friendli",
        "Parasail",
        "Parasail",
    ]
    assert client.pacing_summary_since(0) == {
        "provider_calls": 5,
        "paced_call_count": 3,
        "pacing_wait_seconds": 30.0,
        "by_provider": {
            "Friendli": {"provider_calls": 3, "pacing_wait_seconds": 20.0},
            "Parasail": {"provider_calls": 2, "pacing_wait_seconds": 10.0},
        },
    }
    with pytest.raises(EvidenceIntegrityError):
        asyncio.run(
            client.complete(
                SimpleNamespace(provider_metadata={"route_provider": "DeepInfra"})
            )
        )


def test_v13_admission_call_is_bound_by_the_frozen_timeout() -> None:
    class SlowClient:
        async def complete(self, request: object) -> object:
            await asyncio.sleep(0.2)
            return "late"

    request = SimpleNamespace(timeout_seconds=0.01)
    enforced = {"controls": {"admission_timeout_enforcement": "asyncio_wait_for"}}
    legacy = {"controls": {}}

    with pytest.raises(ProviderFailure) as excinfo:
        asyncio.run(_admission_complete(enforced, SlowClient(), request))
    assert excinfo.value.condition == "timeout"
    assert asyncio.run(_admission_complete(legacy, SlowClient(), request)) == "late"


def test_published_v13_full_trajectory_gate_is_digest_bound_and_complete() -> None:
    evidence_root = (
        V13_CONTRACT_PATH.parents[1]
        / "evidence"
        / "housing_model_sensitivity_openrouter_friendli_v13"
    )
    qualification = json.loads(
        (evidence_root / "reports" / "qualification.json").read_bytes()
    )
    trajectories = json.loads(
        (evidence_root / "trajectories" / "attempted.json").read_bytes()
    )
    fact_index = json.loads(
        (evidence_root / "tables" / "canonical_fact_index.json").read_bytes()
    )

    assert qualification["artifact_sha256"] == (
        "4a976375fbed6fb1dd1e0f2c14dceaaafa825a2209c17b3906841b05281c5605"
    )
    assert trajectories["artifact_sha256"] == (
        "832f2b1663cde9c2c02f187ebe62d6d4ae5705d9fddc1d4cefe112af5a83d992"
    )
    assert fact_index["artifact_sha256"] == (
        "7ec39dfaa4379d9ba736e53b05a4b3290e2b93eec762b9deadf69117c5e4c965"
    )
    assert qualification["status"] == "completed_with_full_matrix"
    assert qualification["winner_claim_allowed"] is False
    assert qualification["ranking_allowed"] is False
    assert qualification["protocol_gate_assessment"]["full_trajectory_gate_passed"]
    admission = qualification["gate_status"][-2]
    assert admission["gate_id"] == "profile_admission"
    assert admission["passed_probe_count"] == 18
    assert admission["operational_failures"] == 0
    gate = qualification["gate_status"][-1]
    assert gate["gate_id"] == "full_trajectory"
    assert gate["completed_trajectories"] == 4
    assert gate["operational_failures"] == 0
    assert gate["complete_matrix"] is True
    assert trajectories["source_gate"] == "full_trajectory"
    assert trajectories["local_source"].endswith("/full_trajectory")
    assert len(trajectories["trajectories"]) == 4
    assert {row["condition_id"] for row in trajectories["trajectories"]} == {
        "deepseek_v4_flash__vs__deepseek_v4_flash",
        "glm_53_flash__vs__deepseek_v4_flash",
        "deepseek_v4_flash__vs__glm_53_flash",
        "glm_53_flash__vs__glm_53_flash",
    }
    assert all(row["replay_verified"] for row in trajectories["trajectories"])
    assert all(row["route_verified"] for row in trajectories["trajectories"])
    assert {
        route["provider"] for route in qualification["backend"]["routes"]
    } == {"Friendli", "Parasail"}
    published = b"".join(path.read_bytes() for path in evidence_root.rglob("*.*"))
    assert b'"raw_response":' not in published
    assert b"output_text" not in published
    assert b"/Users/" not in published


def test_v14_carries_v13_routes_and_controls_into_a_fresh_four_world_pilot() -> None:
    v10 = load_contract(V10_CONTRACT_PATH)
    v13 = load_contract(V13_CONTRACT_PATH)
    v14 = load_contract(V14_CONTRACT_PATH)
    routes = route_table(v14)

    # Same routes, cooldown, and admission-timeout controls as the passed V13 gate.
    assert routes["glm_53_flash"].provider == "Friendli"
    assert routes["deepseek_v4_flash"].provider == "Parasail"
    for model_id in ("glm_53_flash", "deepseek_v4_flash"):
        assert v14["models"][model_id]["endpoint_snapshot_sha256"] == (
            v13["models"][model_id]["endpoint_snapshot_sha256"]
        )
    assert v14["controls"]["call_pacing"] == v13["controls"]["call_pacing"]
    assert v14["controls"]["admission_timeout_enforcement"] == (
        v13["controls"]["admission_timeout_enforcement"]
    )
    changed = {
        key
        for key in v14["controls"]
        if v14["controls"][key] != v13["controls"].get(key)
    }
    assert changed == {"reasoning_condition_id", "condition_order"}
    # Same multi-world pilot design as V9/V10, on fresh development worlds.
    assert v14["controls"]["condition_order"] == v10["controls"]["condition_order"]
    assert v14["analysis"] == v10["analysis"]
    assert v14["conditions"] == v13["conditions"]
    assert "stage" not in v14["execution"]
    assert v14["execution"]["world_seeds"] == [
        264284765,
        722524881,
        1535604354,
        366965770,
    ]
    previously_used = {
        seed
        for path in (V10_CONTRACT_PATH, V13_CONTRACT_PATH, CONTRACT_PATH)
        for seed in load_contract(path)["execution"]["world_seeds"]
    }
    assert not previously_used & set(v14["execution"]["world_seeds"])
    assert v14["execution"]["cost_ceiling_usd"] == pytest.approx(0.45)
    assert (
        v14["profile_admission"]["cost_ceiling_usd"]
        + v14["execution"]["cost_ceiling_usd"]
        == pytest.approx(0.51)
    )
    design = design_artifact(v14, routes=routes)
    assert design["planned_trajectories"] == 48
    assert design["artifact_sha256"] == (
        "ae0bd0aad2e02465643b32c4c2d7f8ef4345891fd2b2d9993e8d152671879b34"
    )
    assert provider_free_artifact(v14)["artifact_sha256"] == (
        "880d05c8d2a68be48100ea655908d8d482f1e3b78c801eb41ffa9976cbdc2c04"
    )
    expected_profiles = v14["profile_admission"]["profile_sha256s"]
    for setup in build_setups(v14, routes=routes).values():
        for profile in setup.plan.agent_profiles:
            assert hashlib.sha256(canonical_json_bytes(profile)).hexdigest() == (
                expected_profiles[profile.profile_id]
            )


def test_published_v14_records_cooldown_rate_limit_block_and_zero_trajectories() -> None:
    evidence_root = (
        V14_CONTRACT_PATH.parents[1]
        / "evidence"
        / "housing_model_sensitivity_openrouter_friendli_v14"
    )
    qualification = json.loads(
        (evidence_root / "reports" / "qualification.json").read_bytes()
    )
    fact_manifest = json.loads(
        (evidence_root / "tables" / "fact_manifest.json").read_bytes()
    )
    trajectories = json.loads(
        (evidence_root / "trajectories" / "attempted.json").read_bytes()
    )
    with (evidence_root / "tables" / "profile_admission.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        admission_rows = list(csv.DictReader(handle))

    assert qualification["artifact_sha256"] == (
        "5affebdf1efc95caeebda78b1e9576ea817e0d8c91baa5e9ac06e16e5bea0d73"
    )
    assert fact_manifest["artifact_sha256"] == (
        "a7fb349f864671b1fcfa611842a439dffd50374cf83a9d8476e5e3358651c847"
    )
    assert trajectories["artifact_sha256"] == (
        "4e09947cd171add239fc3b14e064f1af27397f9f79a1e6ab740167571f041090"
    )
    assert qualification["status"] == "blocked_by_profile_admission"
    assert qualification["gate_status"][-1]["attempted_trajectories"] == 0
    assert qualification["gate_status"][-1]["not_started_trajectories"] == 48
    assert qualification["gate_status"][-1]["provider_calls"] == 0
    assert len(admission_rows) == 18
    failures = [row for row in admission_rows if row["status"] != "passed"]
    assert len(failures) == 3
    assert {row["model_id"] for row in failures} == {"glm_53_flash"}
    assert {row["failure_condition"] for row in failures} == {"rate_limit"}
    assert {row["failure_status_code"] for row in failures} == {"429"}
    # Every failed call had already received the full 10-second cooldown.
    assert all(float(row["pacing_wait_seconds"]) > 9.9 for row in failures)
    assert all(row["pacing_provider_calls"] == "1" for row in failures)
    assert all(float(row["elapsed_seconds"]) < 120.0 for row in admission_rows)
    published = b"".join(path.read_bytes() for path in evidence_root.rglob("*.*"))
    assert b'"raw_response":' not in published
    assert b"output_text" not in published
    assert b"/Users/" not in published


def test_v15_changes_only_identity_and_visible_admission_attempts() -> None:
    v14 = load_contract(V14_CONTRACT_PATH)
    v15 = load_contract(V15_CONTRACT_PATH)
    routes = route_table(v15)

    assert v15["execution"] == v14["execution"]
    assert v15["analysis"] == v14["analysis"]
    assert v15["conditions"] == v14["conditions"]
    changed = {
        key for key in v15["controls"] if v15["controls"][key] != v14["controls"][key]
    }
    assert changed == {"reasoning_condition_id"}
    for model_id in ("glm_53_flash", "deepseek_v4_flash"):
        assert v15["models"][model_id]["endpoint_snapshot_sha256"] == (
            v14["models"][model_id]["endpoint_snapshot_sha256"]
        )
    assert v15["profile_admission"]["attempt_limit_per_probe"] == 4
    assert v14["profile_admission"]["attempt_limit_per_probe"] == 1
    assert v15["profile_admission"]["sdk_retries"] == 0
    assert v15["profile_admission"]["hidden_repair_allowed"] is False
    assert v15["profile_admission"]["cost_ceiling_usd"] == (
        v14["profile_admission"]["cost_ceiling_usd"]
    )
    assert design_artifact(v15, routes=routes)["artifact_sha256"] == (
        "2464978213bff4b92b3423f6b55a789016e74da5f3bd0c33ee2779ec39cf1c52"
    )
    assert provider_free_artifact(v15)["artifact_sha256"] == (
        "1434cc85aaec8f5373c9327de3a3b083d41b34931921bed9feec0835aa317e1e"
    )
    expected_profiles = v15["profile_admission"]["profile_sha256s"]
    for setup in build_setups(v15, routes=routes).values():
        for profile in setup.plan.agent_profiles:
            assert hashlib.sha256(canonical_json_bytes(profile)).hexdigest() == (
                expected_profiles[profile.profile_id]
            )


def test_v15_admission_retries_rate_limits_visibly_and_stops_on_invalid_action(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    contract = load_contract(V15_CONTRACT_PATH)
    calls: list[str] = []

    class FlakyClient:
        async def complete(self, request: object) -> ProviderResult:
            calls.append(request.provider_call_id)
            seen = sum(1 for call in calls if call == request.provider_call_id)
            # First GLM probe: 429 twice, then pass. Second GLM probe: invalid
            # action on the first call (must not be retried). Others pass.
            if request.provider_call_id.endswith("glm_53_flash_tenant_contact_0"):
                if seen <= 2:
                    raise ProviderFailure(
                        "rate_limit", "429 upstream", retryable=True, status_code=429
                    )
            content = '{"invalid":true}' if (
                request.provider_call_id.endswith("glm_53_flash_tenant_commit_0")
            ) else None
            observation_text = request.input_text
            if content is None:
                # Produce a schema-valid action for the probe's schema.
                import json as _json

                payload = _json.loads(observation_text)
                schema = payload["action_schema"]
                obs = payload["observation"]
                del obs
                if schema == "housing_contact_v1":
                    content = _json.dumps(
                        {"decision": "pass", "listing_id": None, "rent": None}
                    )
                elif schema == "housing_commit_v1":
                    content = _json.dumps({"decision": "pass", "hold_id": None})
                else:
                    content = _json.dumps(
                        {"decision": "reject_all", "offer_id": None, "counter_rent": None}
                    )
            return ProviderResult(
                response_id="flaky-fixture",
                requested_model=request.model,
                resolved_model=request.revision,
                output_text=content,
                finish_reason="stop",
                input_tokens=100,
                cached_input_tokens=0,
                output_tokens=10,
                cost_usd=0.0001,
                raw_response={"id": "flaky-fixture", "model": request.revision},
            )

    monkeypatch.setattr("aeread_families.housing.backend_campaign.asyncio.sleep", _no_sleep)
    result = asyncio.run(
        run_profile_admission(
            contract, output_root=tmp_path / "admission", provider_client=FlakyClient()
        )
    )
    by_key = {
        (row["model_id"], row["action_schema"], row["probe_index"]): row
        for row in result["rows"]
    }
    retried = by_key[("glm_53_flash", "housing_contact_v1", 0)]
    assert retried["status"] == "passed"
    assert retried["visible_attempt_count"] == 3
    assert retried["effective_retry_count"] == 2
    assert [a["status"] for a in retried["attempts"]] == [
        "operational_failure",
        "operational_failure",
        "passed",
    ]
    assert [a.get("retry_delay_seconds") for a in retried["attempts"]] == [
        2.0,
        4.0,
        None,
    ]
    assert retried["billing_status"] == (
        "provider_reported_with_unbilled_failed_attempts"
    )
    assert retried["cost_usd"] == pytest.approx(0.0001)
    assert result["hidden_retry_count"] == 0
    assert result["provider_cost_complete"] is False
    assert calls.count("admission_glm_53_flash_tenant_contact_0") == 3
    assert calls.count("admission_glm_53_flash_tenant_commit_0") == 1


async def _no_sleep(_seconds: float) -> None:
    return None


def test_published_v15_pilot_is_digest_bound_conformant_and_non_estimable() -> None:
    evidence_root = (
        V15_CONTRACT_PATH.parents[1]
        / "evidence"
        / "housing_model_sensitivity_openrouter_friendli_v15"
    )
    qualification = json.loads(
        (evidence_root / "reports" / "qualification.json").read_bytes()
    )
    trajectories = json.loads(
        (evidence_root / "trajectories" / "attempted.json").read_bytes()
    )
    fact_index = json.loads(
        (evidence_root / "tables" / "canonical_fact_index.json").read_bytes()
    )

    assert qualification["artifact_sha256"] == (
        "a8957f39ab4aa47877f0f9cb6f46fee143c59b7548784f687147ca260405a8b6"
    )
    assert trajectories["artifact_sha256"] == (
        "3665f9c97d991c689ec1afe8a3b167ca2b073ad423850a979af2e42b8113c8a9"
    )
    assert fact_index["artifact_sha256"] == (
        "5a14841e969f59e0ec16827c371a72f820ffae0d8124b0661fb3e7e9c91b1a38"
    )
    assert qualification["status"] == "completed_with_typed_missingness"
    assert qualification["winner_claim_allowed"] is False
    assert qualification["ranking_allowed"] is False
    admission = qualification["gate_status"][-2]
    assert admission["passed_probe_count"] == 18
    assert admission["hidden_retry_count"] == 0
    live = qualification["gate_status"][-1]
    assert live["attempted_trajectories"] == 48
    assert live["completed_trajectories"] == 43
    assert live["operational_failures"] == 5
    gate = qualification["protocol_gate_assessment"]
    assert gate["protocol_conformant"] is True
    assert gate["prerequisite_gate"]["campaign_id"] == (
        "housing_model_sensitivity_openrouter_friendli_v13"
    )
    assert gate["prerequisite_gate"]["qualification_artifact_sha256"] == (
        "4a976375fbed6fb1dd1e0f2c14dceaaafa825a2209c17b3906841b05281c5605"
    )
    assert qualification["acceptance"]["prerequisite_gates_passed"] is True
    assert qualification["acceptance"]["paired_worlds_complete"] is False
    variance = qualification["variance_pilot_analysis"]
    assert variance["status"] == "insufficient_paired_worlds"
    assert variance["paired_world_count"] == 0
    assert variance["incomplete_world_count"] == 4
    failures = [
        row for row in trajectories["trajectories"] if row["status"] != "completed"
    ]
    assert len(failures) == 5
    assert {row["failure_condition"] for row in failures} == {"rate_limit", "timeout"}
    assert all("glm_53_flash" in row["condition_id"] for row in failures)
    assert len({row["world_seed"] for row in failures}) == 4
    published = b"".join(path.read_bytes() for path in evidence_root.rglob("*.*"))
    assert b'"raw_response":' not in published
    assert b"output_text" not in published
    assert b"/Users/" not in published


def test_v16_repins_both_models_to_parasail_from_a_digest_bound_route_probe() -> None:
    from aeread_families.housing.backend_campaign import CAMPAIGN_SPECS

    v13 = load_contract(V13_CONTRACT_PATH)
    v16 = load_contract(V16_CONTRACT_PATH)
    routes = route_table(v16)
    spec = CAMPAIGN_SPECS["housing_model_sensitivity_openrouter_parasail_v16"]

    probe_root = V16_CONTRACT_PATH.parents[1] / "evidence" / "housing_glm_route_probe_2026-09-05"
    summary = json.loads((probe_root / "reports" / "summary.json").read_bytes())
    assert summary["artifact_sha256"] == (
        spec["route_selection_probe"]["summary_artifact_sha256"]
    )
    assert summary["artifact_sha256"] == (
        "54406a94d4dacc0d1c0b6533ff67cdcfbbc4a20b56fdb91d98a7a551ac8cb63c"
    )
    core = {key: value for key, value in summary.items() if key != "artifact_sha256"}
    assert hashlib.sha256(canonical_json_bytes(core)).hexdigest() == (
        summary["artifact_sha256"]
    )
    assert summary["probe_calls_sha256"] == hashlib.sha256(
        (probe_root / "tables" / "probe_calls.jsonl").read_bytes()
    ).hexdigest()
    by_provider = {row["provider"]: row for row in summary["routes"]}
    assert by_provider["Parasail"]["valid"] == 100
    assert by_provider["Parasail"]["calls"] == 100
    assert by_provider["Parasail"]["rate_limit"] == 0
    assert summary["selection"]["selected_provider"] == "Parasail"
    assert len(by_provider) == 12

    assert routes["glm_53_flash"].provider == "Parasail"
    assert routes["glm_53_flash"].quantization == "fp8"
    assert routes["deepseek_v4_flash"].provider == "Parasail"
    assert v16["models"]["deepseek_v4_flash"]["endpoint_snapshot_sha256"] == (
        v13["models"]["deepseek_v4_flash"]["endpoint_snapshot_sha256"]
    )
    assert v16["execution"] == v13["execution"]
    assert v16["analysis"] == v13["analysis"]
    assert v16["conditions"] == v13["conditions"]
    assert v16["controls"]["call_pacing"]["cooldown_seconds_by_provider"] == {
        "Parasail": 10.0
    }
    assert v16["controls"]["call_pacing"]["implementation_sha256"] == (
        v13["controls"]["call_pacing"]["implementation_sha256"]
    )
    assert v16["controls"]["admission_timeout_enforcement"] == (
        v13["controls"]["admission_timeout_enforcement"]
    )
    assert v16["profile_admission"]["attempt_limit_per_probe"] == 4
    assert (
        v16["profile_admission"]["cost_ceiling_usd"]
        + v16["execution"]["cost_ceiling_usd"]
        == pytest.approx(0.14)
    )
    assert design_artifact(v16, routes=routes)["artifact_sha256"] == (
        "c3aaa9e985e925a3701db7a245351a75f4c398f9bf2754c1ec0c0b8eb82d2be6"
    )
    assert provider_free_artifact(v16)["artifact_sha256"] == (
        "ff96dfd951c6ff1fbbbae92872065a2ed04fe3fc621fe8828b6bbe73da4cfdb7"
    )
    expected_profiles = v16["profile_admission"]["profile_sha256s"]
    for setup in build_setups(v16, routes=routes).values():
        for profile in setup.plan.agent_profiles:
            assert hashlib.sha256(canonical_json_bytes(profile)).hexdigest() == (
                expected_profiles[profile.profile_id]
            )
    published = b"".join(path.read_bytes() for path in probe_root.rglob("*.*"))
    assert b"sk-or-" not in published
    assert b"/Users/" not in published


def test_published_v16_parasail_gate_is_digest_bound_and_complete() -> None:
    evidence_root = (
        V16_CONTRACT_PATH.parents[1]
        / "evidence"
        / "housing_model_sensitivity_openrouter_parasail_v16"
    )
    qualification = json.loads(
        (evidence_root / "reports" / "qualification.json").read_bytes()
    )
    trajectories = json.loads(
        (evidence_root / "trajectories" / "attempted.json").read_bytes()
    )
    fact_index = json.loads(
        (evidence_root / "tables" / "canonical_fact_index.json").read_bytes()
    )
    assert qualification["artifact_sha256"] == (
        "221ebfa55ba6aecd89546f74b7851deac869a8f68277ed51b366ef13088a2abb"
    )
    assert trajectories["artifact_sha256"] == (
        "d59d2504e418af0451304c3e364be692e79790eb717e4314c3755d56521f6e91"
    )
    assert fact_index["artifact_sha256"] == (
        "4347d56b75aadf2a11ee66cf6a7f29cef0e9089384ef64bac481f6f477b8a45f"
    )
    assert qualification["status"] == "completed_with_full_matrix"
    assert qualification["ranking_allowed"] is False
    gate = qualification["gate_status"][-1]
    assert gate["gate_id"] == "full_trajectory"
    assert gate["completed_trajectories"] == 4
    assert gate["operational_failures"] == 0
    assert qualification["gate_status"][-2]["passed_probe_count"] == 18
    assert qualification["gate_status"][-2]["hidden_retry_count"] == 0
    assert {route["provider"] for route in qualification["backend"]["routes"]} == {
        "Parasail"
    }
    assert all(row["replay_verified"] for row in trajectories["trajectories"])
    published = b"".join(path.read_bytes() for path in evidence_root.rglob("*.*"))
    assert b'"raw_response":' not in published
    assert b"output_text" not in published
    assert b"/Users/" not in published


def test_v17_pilot_carries_v16_routes_and_names_v16_as_its_verified_gate() -> None:
    from aeread_families.housing.backend_campaign import CAMPAIGN_SPECS

    v15 = load_contract(V15_CONTRACT_PATH)
    v16 = load_contract(V16_CONTRACT_PATH)
    v17 = load_contract(V17_CONTRACT_PATH)
    routes = route_table(v17)
    spec = CAMPAIGN_SPECS["housing_model_sensitivity_openrouter_parasail_v17"]

    for model_id in ("glm_53_flash", "deepseek_v4_flash"):
        assert routes[model_id].provider == "Parasail"
        assert v17["models"][model_id]["endpoint_snapshot_sha256"] == (
            v16["models"][model_id]["endpoint_snapshot_sha256"]
        )
    assert v17["controls"]["call_pacing"] == v16["controls"]["call_pacing"]
    assert v17["controls"]["admission_timeout_enforcement"] == (
        v16["controls"]["admission_timeout_enforcement"]
    )
    assert v17["profile_admission"]["attempt_limit_per_probe"] == 4
    assert v17["analysis"] == v15["analysis"]
    assert v17["conditions"] == v15["conditions"]
    assert "stage" not in v17["execution"]
    assert v17["execution"]["cost_ceiling_usd"] == pytest.approx(0.45)
    assert v17["execution"]["world_seeds"] == [
        1063943031,
        647986875,
        1758927083,
        237549679,
    ]
    previously_used = {
        seed
        for path in (
            CONTRACT_PATH,
            V10_CONTRACT_PATH,
            V13_CONTRACT_PATH,
            V15_CONTRACT_PATH,
            V16_CONTRACT_PATH,
        )
        for seed in load_contract(path)["execution"]["world_seeds"]
    }
    assert not previously_used & set(v17["execution"]["world_seeds"])

    gate = spec["prerequisite_full_trajectory_gate"]
    assert gate["campaign_id"] == "housing_model_sensitivity_openrouter_parasail_v16"
    qualification = json.loads(
        (V17_CONTRACT_PATH.parents[1] / gate["qualification_path"]).read_bytes()
    )
    assert qualification["artifact_sha256"] == gate["qualification_artifact_sha256"]
    assert qualification["gate_status"][-1]["status"] == "completed_with_full_matrix"
    assert spec["route_selection_probe"]["summary_artifact_sha256"] == (
        CAMPAIGN_SPECS["housing_model_sensitivity_openrouter_parasail_v16"][
            "route_selection_probe"
        ]["summary_artifact_sha256"]
    )

    design = design_artifact(v17, routes=routes)
    assert design["planned_trajectories"] == 48
    assert design["artifact_sha256"] == (
        "de4e1df272a42e879e864b5dd5c60a1dc246a2f771b7b51f23b7efdbc615dae4"
    )
    assert provider_free_artifact(v17)["artifact_sha256"] == (
        "17700073ca73b3384e949ec19d0b53aa43e9d5206ac57e2148359dc09fdaa785"
    )
    expected_profiles = v17["profile_admission"]["profile_sha256s"]
    for setup in build_setups(v17, routes=routes).values():
        for profile in setup.plan.agent_profiles:
            assert hashlib.sha256(canonical_json_bytes(profile)).hexdigest() == (
                expected_profiles[profile.profile_id]
            )


def test_published_v17_records_the_driver_stop_after_three_cells() -> None:
    evidence_root = (
        V17_CONTRACT_PATH.parents[1]
        / "evidence"
        / "housing_model_sensitivity_openrouter_parasail_v17"
    )
    qualification = json.loads(
        (evidence_root / "reports" / "qualification.json").read_bytes()
    )
    trajectories = json.loads(
        (evidence_root / "trajectories" / "attempted.json").read_bytes()
    )
    assert qualification["artifact_sha256"] == (
        "213d2e947e505fed17867946041cee43577e8561d4b0aed66728fd346b30e244"
    )
    assert trajectories["artifact_sha256"] == (
        "1bbe15410e685680d14d21127bd9171c94ebce1b8c75f1f634cbb4d0e7b579f2"
    )
    assert qualification["status"] == "stopped_with_typed_missingness"
    gate = qualification["gate_status"][-1]
    assert gate["attempted_trajectories"] == 3
    assert gate["completed_trajectories"] == 0
    assert gate["not_started_trajectories"] == 45
    assert gate["critical_stop"] is True
    assert qualification["acceptance"]["all_frozen_cells_attempted"] is False
    assert qualification["acceptance"]["protocol_conformant"] is True
    assert qualification["observed_score_range"]["minimum"] is None
    assert [row["failure_condition"] for row in trajectories["trajectories"]] == [
        "timeout",
        "timeout",
        "execution_error",
    ]
    assert any("never attempted" in item for item in trajectories["limitations"])
    published = b"".join(path.read_bytes() for path in evidence_root.rglob("*.*"))
    assert b'"raw_response":' not in published
    assert b"output_text" not in published
    assert b"/Users/" not in published


def test_v18_freezes_wall_time_and_seat_budget_in_the_contract() -> None:
    v16 = load_contract(V16_CONTRACT_PATH)
    v18 = load_contract(V18_CONTRACT_PATH)
    routes = route_table(v18)

    changed = {
        key for key in v18["controls"] if v18["controls"][key] != v16["controls"].get(key)
    }
    assert changed == {"reasoning_condition_id", "timeout_seconds", "seat_max_cost_usd"}
    assert v18["controls"]["timeout_seconds"] == 300.0
    assert v18["controls"]["seat_max_cost_usd"] == 0.03
    assert v16["controls"].get("seat_max_cost_usd") is None
    for model_id in ("glm_53_flash", "deepseek_v4_flash"):
        assert routes[model_id].provider == "Parasail"
        assert v18["models"][model_id]["endpoint_snapshot_sha256"] == (
            v16["models"][model_id]["endpoint_snapshot_sha256"]
        )
    assert v18["execution"]["world_seeds"] == v16["execution"]["world_seeds"]
    assert v18["execution"]["stage"] == "full_trajectory"
    assert v18["execution"]["per_trajectory_cost_reserve_usd"] == pytest.approx(0.06)
    assert (
        v18["profile_admission"]["cost_ceiling_usd"]
        + v18["execution"]["cost_ceiling_usd"]
        == pytest.approx(0.36)
    )
    for setup in build_setups(v18, routes=routes).values():
        for profile in setup.plan.agent_profiles:
            assert profile.budgets.timeout_seconds == 300.0
            assert profile.budgets.max_cost_usd == 0.03
    for setup in build_setups(v16, routes=route_table(v16)).values():
        for profile in setup.plan.agent_profiles:
            assert profile.budgets.timeout_seconds == 120.0
            assert profile.budgets.max_cost_usd == 0.01
    assert design_artifact(v18, routes=routes)["artifact_sha256"] == (
        "b05a7626e7efb8cd07e0d62be1c9823e09ab46f66874e1b0aefb131619538b51"
    )
    assert provider_free_artifact(v18)["artifact_sha256"] == (
        "dc1af3b3dfa055e3370b508e3008623a6746fd494038c9bdb29b905ce28838a7"
    )
    expected_profiles = v18["profile_admission"]["profile_sha256s"]
    for setup in build_setups(v18, routes=routes).values():
        for profile in setup.plan.agent_profiles:
            assert hashlib.sha256(canonical_json_bytes(profile)).hexdigest() == (
                expected_profiles[profile.profile_id]
            )


def test_seat_cost_budget_exhaustion_is_typed_cell_missingness_not_critical() -> None:
    from aeread_families.housing.model_sensitivity import _critical_failure

    seat_budget = EvidenceIntegrityError(
        "cost budget exceeded for profile 'housing_x_tenant_v18': 0.0105 > 0.01"
    )
    assert _critical_failure(seat_budget) is False
    assert _critical_failure(EvidenceIntegrityError("offline replay mismatch")) is True
    assert _critical_failure(
        ProviderFailure("provider_contract", "fallback or repeated route", retryable=False)
    ) is True
    assert _critical_failure(
        ProviderFailure("rate_limit", "429", retryable=True, status_code=429)
    ) is False


def test_published_v18_gate_is_digest_bound_and_complete() -> None:
    evidence_root = (
        V18_CONTRACT_PATH.parents[1]
        / "evidence"
        / "housing_model_sensitivity_openrouter_parasail_v18"
    )
    qualification = json.loads(
        (evidence_root / "reports" / "qualification.json").read_bytes()
    )
    trajectories = json.loads(
        (evidence_root / "trajectories" / "attempted.json").read_bytes()
    )
    assert qualification["artifact_sha256"] == (
        "061aab759f4a632e336546b8b0b1ea38caeead15c528b936534835d7dbfae43b"
    )
    assert trajectories["artifact_sha256"] == (
        "c0ef79322ddf60035ffb4d2a8dbd7cb207f836be99431a6c8a4a86a2a03af9da"
    )
    assert qualification["status"] == "completed_with_full_matrix"
    gate = qualification["gate_status"][-1]
    assert gate["gate_id"] == "full_trajectory"
    assert gate["completed_trajectories"] == 4
    assert gate["operational_failures"] == 0
    assert qualification["controls"]["timeout_seconds"] == 300.0
    assert all(row["replay_verified"] for row in trajectories["trajectories"])
    assert max(row["cost_usd"] for row in trajectories["trajectories"]) > 0.01
    published = b"".join(path.read_bytes() for path in evidence_root.rglob("*.*"))
    assert b'"raw_response":' not in published
    assert b"output_text" not in published
    assert b"/Users/" not in published


def test_v19_pilot_carries_v18_controls_and_names_v18_as_its_verified_gate() -> None:
    from aeread_families.housing.backend_campaign import CAMPAIGN_SPECS

    v17 = load_contract(V17_CONTRACT_PATH)
    v18 = load_contract(V18_CONTRACT_PATH)
    v19 = load_contract(V19_CONTRACT_PATH)
    routes = route_table(v19)
    spec = CAMPAIGN_SPECS["housing_model_sensitivity_openrouter_parasail_v19"]

    changed = {
        key for key in v19["controls"] if v19["controls"][key] != v18["controls"].get(key)
    }
    assert changed == {"reasoning_condition_id", "condition_order"}
    assert v19["controls"]["timeout_seconds"] == 300.0
    assert v19["controls"]["seat_max_cost_usd"] == 0.03
    for model_id in ("glm_53_flash", "deepseek_v4_flash"):
        assert routes[model_id].provider == "Parasail"
        assert v19["models"][model_id]["endpoint_snapshot_sha256"] == (
            v18["models"][model_id]["endpoint_snapshot_sha256"]
        )
    assert v19["analysis"] == v17["analysis"]
    assert v19["conditions"] == v17["conditions"]
    assert "stage" not in v19["execution"]
    assert v19["execution"]["cost_ceiling_usd"] == pytest.approx(1.0)
    assert v19["execution"]["per_trajectory_cost_reserve_usd"] == pytest.approx(0.06)
    assert v19["execution"]["world_seeds"] == [
        647986875,
        1758927083,
        237549679,
        1515521562,
    ]
    # V17 executed cells only on its first world; the other three carry no
    # executed cell, so reusing them is not a rerun.
    v17_root = (
        V17_CONTRACT_PATH.parents[1]
        / "evidence"
        / "housing_model_sensitivity_openrouter_parasail_v17"
        / "trajectories"
        / "attempted.json"
    )
    executed_worlds = {
        row["world_seed"]
        for row in json.loads(v17_root.read_bytes())["trajectories"]
    }
    assert not executed_worlds & set(v19["execution"]["world_seeds"])
    previously_used = {
        seed
        for path in (
            CONTRACT_PATH,
            V10_CONTRACT_PATH,
            V13_CONTRACT_PATH,
            V15_CONTRACT_PATH,
            V16_CONTRACT_PATH,
            V18_CONTRACT_PATH,
        )
        for seed in load_contract(path)["execution"]["world_seeds"]
    }
    assert not previously_used & set(v19["execution"]["world_seeds"])

    gate = spec["prerequisite_full_trajectory_gate"]
    assert gate["campaign_id"] == "housing_model_sensitivity_openrouter_parasail_v18"
    qualification = json.loads(
        (V19_CONTRACT_PATH.parents[1] / gate["qualification_path"]).read_bytes()
    )
    assert qualification["artifact_sha256"] == gate["qualification_artifact_sha256"]
    assert qualification["controls"]["timeout_seconds"] == 300.0
    for setup in build_setups(v19, routes=routes).values():
        for profile in setup.plan.agent_profiles:
            assert profile.budgets.timeout_seconds == 300.0
            assert profile.budgets.max_cost_usd == 0.03
    design = design_artifact(v19, routes=routes)
    assert design["planned_trajectories"] == 48
    assert design["artifact_sha256"] == (
        "2fcc9d8d3744f3779de26624e451205be430bf3fa6ecd7127aadcde4974645fa"
    )
    assert provider_free_artifact(v19)["artifact_sha256"] == (
        "72027855275419a11d0c621820affbb5ef7e2aa4762265017181f0602e08c91d"
    )
    expected_profiles = v19["profile_admission"]["profile_sha256s"]
    for setup in build_setups(v19, routes=routes).values():
        for profile in setup.plan.agent_profiles:
            assert hashlib.sha256(canonical_json_bytes(profile)).hexdigest() == (
                expected_profiles[profile.profile_id]
            )


def test_published_v19_pilot_has_two_paired_worlds_and_only_rate_limit_losses() -> None:
    evidence_root = (
        V19_CONTRACT_PATH.parents[1]
        / "evidence"
        / "housing_model_sensitivity_openrouter_parasail_v19"
    )
    qualification = json.loads(
        (evidence_root / "reports" / "qualification.json").read_bytes()
    )
    trajectories = json.loads(
        (evidence_root / "trajectories" / "attempted.json").read_bytes()
    )
    assert qualification["artifact_sha256"] == (
        "7b72914c34f0461e190215906a735a64ddccd3e4943c79e1e1b87b11c64df3e1"
    )
    assert trajectories["artifact_sha256"] == (
        "3960007ed5366162299986559d10b7ae532631af5d2659bfe83e06267b35159d"
    )
    assert qualification["status"] == "completed_with_typed_missingness"
    assert qualification["winner_claim_allowed"] is False
    assert qualification["ranking_allowed"] is False
    live = qualification["gate_status"][-1]
    assert live["attempted_trajectories"] == 48
    assert live["completed_trajectories"] == 32
    assert live["operational_failures"] == 16
    assert live["critical_stop"] is False
    variance = qualification["variance_pilot_analysis"]
    assert variance["status"] == "estimable"
    assert variance["paired_world_count"] == 2
    assert variance["recommended_confirmatory_worlds"] == 32
    assert qualification["acceptance"]["paired_worlds_complete"] is False
    assert qualification["acceptance"]["confirmatory_freeze_ready"] is False
    assert qualification["acceptance"]["protocol_conformant"] is True
    assert qualification["protocol_gate_assessment"]["prerequisite_gate"]["campaign_id"] == (
        "housing_model_sensitivity_openrouter_parasail_v18"
    )
    failures = [row for row in trajectories["trajectories"] if row["status"] != "completed"]
    assert len(failures) == 16
    assert {row["failure_condition"] for row in failures} == {"rate_limit"}
    assert all("glm_53_flash" in row["condition_id"] for row in failures)
    assert {row["world_seed"] for row in failures} == {237549679, 1515521562}
    assert "exploratory" in qualification["next_gate"]
    published = b"".join(path.read_bytes() for path in evidence_root.rglob("*.*"))
    assert b'"raw_response":' not in published
    assert b"output_text" not in published
    assert b"/Users/" not in published


def test_published_v12_records_pacing_failure_and_zero_trajectories() -> None:
    evidence_root = (
        V12_CONTRACT_PATH.parents[1]
        / "evidence"
        / "housing_model_sensitivity_openrouter_deepinfra_v12"
    )
    qualification = json.loads(
        (evidence_root / "reports" / "qualification.json").read_bytes()
    )
    fact_manifest = json.loads(
        (evidence_root / "tables" / "fact_manifest.json").read_bytes()
    )
    trajectories = json.loads(
        (evidence_root / "trajectories" / "attempted.json").read_bytes()
    )
    with (evidence_root / "tables" / "profile_admission.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        admission_rows = list(csv.DictReader(handle))

    assert qualification["artifact_sha256"] == (
        "7c8e2d24135d21ebd279fb3bea4a31ed693e1575d5ea81296051e4d842ddc5f1"
    )
    assert fact_manifest["artifact_sha256"] == (
        "b8e3b77011d932d1f23cb9fa8389d2df0512a5f246adaac26ba00033a37a2558"
    )
    assert trajectories["artifact_sha256"] == (
        "06eddf1bcf66de662a2b2413e2d838a3db6f3aed2e43b866f012411e3385bec8"
    )
    assert qualification["status"] == "blocked_by_profile_admission"
    assert qualification["gate_status"][-1]["attempted_trajectories"] == 0
    assert qualification["gate_status"][-1]["not_started_trajectories"] == 4
    assert qualification["gate_status"][-1]["provider_calls"] == 0
    assert len(admission_rows) == 18
    failures = [row for row in admission_rows if row["status"] != "passed"]
    assert len(failures) == 1
    assert failures[0]["model_id"] == "glm_53_flash"
    assert failures[0]["failure_condition"] == "rate_limit"
    assert failures[0]["failure_status_code"] == "429"
    assert failures[0]["pacing_provider_calls"] == "1"
    assert failures[0]["paced_call_count"] == "0"
    assert failures[0]["pacing_wait_seconds"] == "0.0"
    assert float(admission_rows[0]["elapsed_seconds"]) > 120.0
    published = b"".join(path.read_bytes() for path in evidence_root.rglob("*.*"))
    assert b'"raw_response":' not in published
    assert b"output_text" not in published
    assert b"/Users/" not in published


def test_v11_failed_admission_blocks_the_full_trajectory_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    contract = load_contract(V11_CONTRACT_PATH)
    failed_admission = {
        "status": "failed_with_typed_missingness",
        "artifact_sha256": "a" * 64,
    }

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")
    monkeypatch.setattr(
        "aeread_families.housing.backend_campaign.catalog_preflight",
        lambda _contract: {
            "campaign_id": contract["campaign_id"],
            "status": "passed",
            "artifact_sha256": "b" * 64,
        },
    )

    async def fake_admission(*_args: object, **_kwargs: object) -> dict[str, object]:
        return failed_admission

    monkeypatch.setattr(
        "aeread_families.housing.backend_campaign.run_profile_admission",
        fake_admission,
    )
    result = asyncio.run(
        execute_campaign(
            contract_path=V11_CONTRACT_PATH,
            output_root=tmp_path,
            through="full_trajectory",
        )
    )

    blocked = result["full_trajectory"]
    assert blocked["status"] == "blocked_by_profile_admission"
    assert blocked["gate_id"] == "full_trajectory"
    assert blocked["provider_calls"] == 0
    assert (tmp_path / "full_trajectory" / "blocked.json").is_file()
    assert not (tmp_path / "live").exists()


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


def test_historical_v8_plan_refuses_live_execution_after_runtime_drift(
    tmp_path: Path,
) -> None:
    contract = load_contract(V8_CONTRACT_PATH)

    with pytest.raises(
        EvidenceIntegrityError,
        match="runtime differs from the frozen implementation pin",
    ):
        asyncio.run(
            run_live(contract, output_root=tmp_path, routes=route_table(contract))
        )


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


def test_published_v10_attempts_and_canonical_facts_are_digest_bound() -> None:
    repository_root = V10_CONTRACT_PATH.parents[1]
    root = repository_root / "evidence" / (
        "housing_model_sensitivity_openrouter_morph_v10"
    )
    qualification = json.loads(
        (root / "reports" / "qualification.json").read_bytes()
    )
    trajectories = json.loads(
        (root / "trajectories" / "attempted.json").read_bytes()
    )
    index = json.loads(
        (root / "tables" / "canonical_fact_index.json").read_bytes()
    )
    for value in (qualification, trajectories, index):
        core = {key: item for key, item in value.items() if key != "artifact_sha256"}
        assert value["artifact_sha256"] == hashlib.sha256(
            canonical_json_bytes(core)
        ).hexdigest()

    assert qualification["status"] == "completed_with_typed_missingness"
    assert qualification["schema_version"] == (
        "aeread.housing_backend_qualification/0.4"
    )
    assert qualification["acceptance"] == {
        "publishable_integration_evidence": True,
        "all_frozen_cells_attempted": True,
        "prerequisite_gates_passed": False,
        "typed_missingness_preserved": True,
        "paired_worlds_complete": False,
        "confirmatory_freeze_ready": False,
        "leaderboard_eligible": False,
        "protocol_conformant": False,
    }
    assert qualification["protocol_gate_assessment"] == {
        "required_before_variance_pilot": "full_trajectory",
        "full_trajectory_gate_passed": False,
        "protocol_conformant": False,
        "interpretation": (
            "No separate full-trajectory gate was recorded for the changed route "
            "before multi-world execution. Retain the run as operational evidence "
            "but do not promote it as a valid variance pilot."
        ),
    }
    variance = qualification["variance_pilot_analysis"]
    assert variance["status"] == "insufficient_paired_worlds"
    assert variance["paired_world_count"] == 0
    assert variance["incomplete_world_count"] == 4
    assert variance["recommended_confirmatory_worlds"] is None
    assert qualification["cost_note"].endswith(
        "combined provider-reported cost $0.15123042."
    )

    assert trajectories["planned_trajectories"] == 48
    assert trajectories["attempted_trajectories"] == 48
    assert trajectories["completed_trajectories"] == 31
    assert trajectories["operational_failures"] == 17
    completed = [
        row for row in trajectories["trajectories"] if row["status"] == "completed"
    ]
    failures = [
        row for row in trajectories["trajectories"] if row["status"] != "completed"
    ]
    assert len(completed) == 31
    assert len(failures) == 17
    assert all(
        row["route_verified"]
        and row["provider_cost_complete"]
        and row["replay_verified"]
        for row in completed
    )
    assert {
        condition: sum(row["failure_condition"] == condition for row in failures)
        for condition in {"rate_limit", "timeout", "transport"}
    } == {"rate_limit": 11, "timeout": 5, "transport": 1}
    assert all(row["score"] is None for row in failures)

    assert qualification["trajectory_export"]["artifact_sha256"] == trajectories[
        "artifact_sha256"
    ]
    assert qualification["fact_tables"]["artifact_sha256"] == index[
        "artifact_sha256"
    ]
    assert index["run_count"] == 12
    assert len(index["runs"]) == 12
    assert all(row["receipt_count"] == 4 for row in index["runs"])
    for run in index["runs"]:
        manifest_path = repository_root / run["fact_manifest_path"]
        manifest_bytes = manifest_path.read_bytes()
        assert hashlib.sha256(manifest_bytes).hexdigest() == run[
            "fact_manifest_file_sha256"
        ]
        manifest = json.loads(manifest_bytes)
        manifest_core = {
            key: item for key, item in manifest.items() if key != "manifest_sha256"
        }
        assert manifest["manifest_sha256"] == hashlib.sha256(
            canonical_json_bytes(manifest_core)
        ).hexdigest()
        assert manifest["manifest_sha256"] == run["fact_manifest_sha256"]
        for table in manifest["tables"].values():
            table_path = manifest_path.parent / table["path"]
            assert hashlib.sha256(table_path.read_bytes()).hexdigest() == table[
                "sha256"
            ]
            with table_path.open(newline="", encoding="utf-8") as handle:
                assert len(list(csv.DictReader(handle))) == table["row_count"]

    contrast = index["paired_world_contrasts"]
    contrast_path = repository_root / contrast["path"]
    assert hashlib.sha256(contrast_path.read_bytes()).hexdigest() == contrast[
        "sha256"
    ]
    with contrast_path.open(newline="", encoding="utf-8") as handle:
        contrast_rows = list(csv.DictReader(handle))
    assert len(contrast_rows) == 4
    assert all(row["complete_pair"] == "False" for row in contrast_rows)
    assert all(row["contrast"] == "" for row in contrast_rows)

    serialized = json.dumps(
        {"qualification": qualification, "trajectories": trajectories, "index": index}
    )
    assert "raw_response" not in serialized
    assert "output_text" not in serialized
    assert "/Users/" not in serialized


def test_published_v11_full_trajectory_block_is_digest_bound() -> None:
    repository_root = V11_CONTRACT_PATH.parents[1]
    root = repository_root / "evidence" / (
        "housing_model_sensitivity_openrouter_deepinfra_v11"
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

    gates = {row["gate_id"]: row for row in qualification["gate_status"]}
    assert qualification["status"] == "blocked_by_profile_admission"
    assert gates["design"]["planned_trajectories"] == 4
    assert gates["profile_admission"]["attempted_probe_count"] == 18
    assert gates["profile_admission"]["passed_probe_count"] == 15
    assert gates["profile_admission"]["operational_failures"] == 3
    assert gates["profile_admission"]["hidden_retry_count"] == 0
    assert gates["full_trajectory"] == {
        "gate_id": "full_trajectory",
        "status": "blocked_by_profile_admission",
        "artifact_sha256": (
            "296904f26ffca691bbd2f05bbfbce5d0bcd93de8ccfab09f0aae53e33d8268cf"
        ),
        "planned_trajectories": 4,
        "attempted_trajectories": 0,
        "completed_trajectories": 0,
        "not_started_trajectories": 4,
        "provider_calls": 0,
        "cost_usd": 0.0,
    }
    assert {
        (row["model_id"], row["probe_index"], row["failure_condition"])
        for row in qualification["failed_admission_probes"]
    } == {("glm_53_flash", 2, "rate_limit")}
    assert {
        row["action_schema"]
        for row in qualification["failed_admission_probes"]
    } == {
        "housing_contact_v1",
        "housing_commit_v1",
        "housing_respond_v1",
    }
    assert qualification["acceptance"]["publishable_gate_evidence"] is True
    assert qualification["acceptance"]["publishable_integration_evidence"] is False
    assert qualification["acceptance"]["leaderboard_eligible"] is False
    assert trajectories["source_gate"] == "full_trajectory_block"
    assert trajectories["planned_trajectories"] == 4
    assert trajectories["attempted_trajectories"] == 0
    assert trajectories["trajectories"] == []

    for table in manifest["artifacts"].values():
        table_path = repository_root / table["path"]
        assert hashlib.sha256(table_path.read_bytes()).hexdigest() == table["sha256"]
        with table_path.open(newline="", encoding="utf-8") as handle:
            assert len(list(csv.DictReader(handle))) == table["row_count"]
    serialized = json.dumps(
        {"qualification": qualification, "trajectories": trajectories}
    )
    assert "raw_response" not in serialized
    assert "output_text" not in serialized
    assert "/Users/" not in serialized
