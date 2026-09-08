"""Parameter-compatible route panel for data-center objective grounding.

V3 changes both the model/provider panel and the versioned OpenRouter adapter.
It neither retries nor replaces the excluded V1 and V2 campaign cells.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes

from .objective_campaign import (
    CONDITION,
    _atomic_write,
    _cells,
    _run_live_cell,
    _sealed,
    build_design as build_base_design,
    run_profile_admission_gate,
    run_provider_free_gate,
    summarize,
)
from .objective_openrouter import (
    CLIENT_IMPLEMENTATION_ID,
    ParameterCompatibleOpenRouterClient,
)


CONTRACT_SCHEMA_VERSION = "aeread.datacenter_objective_campaign_contract/0.3"
CAMPAIGN_ID = "datacenter_development_v2_objective_grounding_v3"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT_PATH = REPOSITORY_ROOT / "configs" / f"{CAMPAIGN_ID}.json"
DEFAULT_RUN_ROOT = REPOSITORY_ROOT / "runs" / CAMPAIGN_ID
EXPECTED_ROUTES = {
    "mistral32_deepinfra": {
        "requested_model": "mistralai/mistral-small-3.2-24b-instruct",
        "canonical_model": "mistralai/mistral-small-3.2-24b-instruct-2506",
        "provider": "DeepInfra",
    },
    "qwen3_235b_novita": {
        "requested_model": "qwen/qwen3-235b-a22b-2507",
        "canonical_model": "qwen/qwen3-235b-a22b-07-25",
        "provider": "Novita",
    },
}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def load_contract(path: Path | str = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    contract = _read_json(Path(path))
    if set(contract) != {
        "schema_version",
        "campaign_id",
        "family_id",
        "family_version",
        "case_id",
        "expected_case_sha256",
        "claim_status",
        "route_catalog_snapshot",
        "inference_seeds",
        "condition",
        "models",
        "execution",
        "analysis",
    }:
        raise ValueError("V3 objective campaign contract fields differ")
    frozen = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "campaign_id": CAMPAIGN_ID,
        "family_id": "datacenter_development_v1",
        "family_version": "2.1.0",
        "condition": CONDITION,
        "claim_status": "single_curated_project_objective_grounding_diagnostic_only",
    }
    if any(contract[key] != value for key, value in frozen.items()):
        raise ValueError("V3 objective campaign identity or claim boundary differs")

    snapshot = contract["route_catalog_snapshot"]
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "source",
        "verified_at",
        "selection_rule",
    }:
        raise ValueError("V3 route-catalog snapshot fields differ")
    if "openrouter.ai/api/v1/models" not in snapshot["source"]:
        raise ValueError("V3 routes must bind the official OpenRouter catalog")

    seeds = contract["inference_seeds"]
    if (
        not isinstance(seeds, list)
        or len(seeds) != 3
        or len(seeds) != len(set(seeds))
        or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seeds)
    ):
        raise ValueError("V3 objective campaign requires three unique non-negative seeds")

    models = contract["models"]
    if not isinstance(models, dict) or set(models) != set(EXPECTED_ROUTES):
        raise ValueError("V3 objective route panel differs")
    route_fields = {
        "profile_id",
        "requested_model",
        "canonical_model",
        "provider",
        "quantization",
        "access_class",
        "license_id",
        "reasoning_effort",
        "temperature_supported",
        "catalog_uptime_last_30m",
        "pricing",
        "max_prompt_price_per_million",
        "max_completion_price_per_million",
    }
    for model_id, expected_route in EXPECTED_ROUTES.items():
        model = models[model_id]
        if not isinstance(model, dict) or set(model) != route_fields:
            raise ValueError(f"{model_id}: V3 route fields differ")
        if any(model[key] != value for key, value in expected_route.items()):
            raise ValueError(f"{model_id}: named route differs")
        if (
            model["access_class"] != "open_source"
            or model["license_id"] != "Apache-2.0"
            or model["reasoning_effort"] is not None
        ):
            raise ValueError(f"{model_id}: V3 requires non-reasoning Apache-2.0 routes")
        uptime = model["catalog_uptime_last_30m"]
        if isinstance(uptime, bool) or not isinstance(uptime, (int, float)) or uptime < 99.7:
            raise ValueError(f"{model_id}: catalog uptime gate differs")
        pricing = model["pricing"]
        if not isinstance(pricing, dict) or set(pricing) != {
            "input_per_million",
            "cached_input_per_million",
            "output_per_million",
            "pricing_id",
        }:
            raise ValueError(f"{model_id}: V3 pricing fields differ")

    execution = contract["execution"]
    if not isinstance(execution, dict) or set(execution) != {
        "harness",
        "adapter",
        "max_output_tokens_per_action",
        "timeout_seconds_per_action",
        "max_cost_usd_per_live_profile",
        "campaign_max_cost_usd",
        "concurrency",
        "max_concurrent_cells_per_route_provider",
        "max_action_attempts",
        "sdk_retries",
        "response_cache",
        "provider_fallbacks",
    }:
        raise ValueError("V3 objective execution fields differ")
    frozen_controls = {
        "harness": "minimal_chat/1.0",
        "adapter": CLIENT_IMPLEMENTATION_ID,
        "max_concurrent_cells_per_route_provider": 1,
        "max_action_attempts": 1,
        "sdk_retries": 0,
        "response_cache": False,
        "provider_fallbacks": False,
    }
    if any(execution[key] != value for key, value in frozen_controls.items()):
        raise ValueError("V3 adapter, cache, retry, routing, or harness controls differ")
    for key in (
        "max_output_tokens_per_action",
        "timeout_seconds_per_action",
        "max_cost_usd_per_live_profile",
        "campaign_max_cost_usd",
        "concurrency",
    ):
        value = execution[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"execution.{key} must be positive")
    worst_case = len(seeds) * len(models) * float(
        execution["max_cost_usd_per_live_profile"]
    )
    if worst_case > float(execution["campaign_max_cost_usd"]):
        raise ValueError("V3 per-profile cost ceilings exceed the campaign cost ceiling")

    analysis = contract["analysis"]
    if analysis.get("independent_cluster_count") != 1:
        raise ValueError("V3 objective campaign must retain one project cluster")
    if analysis.get("missingness") != "report_separately":
        raise ValueError("V3 operational missingness must be reported separately")
    if analysis.get("primary_estimand") != "safe_developer_objective_attainment":
        raise ValueError("V3 primary estimand differs")
    for field in (
        "winner_claim_allowed",
        "inferential_model_ranking_allowed",
        "causal_condition_effect_allowed",
    ):
        if analysis.get(field) is not False:
            raise ValueError(f"analysis.{field} must be false")
    return contract


def build_design(contract: Mapping[str, Any]) -> dict[str, Any]:
    base = build_base_design(contract)
    core = {key: value for key, value in base.items() if key != "artifact_sha256"}
    source_root = Path(__file__).parent
    driver_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    adapter_hash = hashlib.sha256(
        (source_root / "objective_openrouter.py").read_bytes()
    ).hexdigest()
    dependencies = dict(core["implementation_source_sha256s"])
    dependencies[Path(__file__).name] = driver_hash
    dependencies["objective_openrouter.py"] = adapter_hash
    core["schema_version"] = "aeread.datacenter_objective_campaign_design/0.3"
    core["campaign_driver_sha256"] = driver_hash
    core["adapter_implementation_id"] = CLIENT_IMPLEMENTATION_ID
    core["adapter_implementation_sha256"] = adapter_hash
    core["implementation_source_sha256s"] = dependencies
    core["route_catalog_snapshot"] = contract["route_catalog_snapshot"]
    return _sealed(core)


async def run_campaign(
    *,
    contract_path: Path | str = DEFAULT_CONTRACT_PATH,
    run_root: Path | str = DEFAULT_RUN_ROOT,
    stop_after: str = "live",
    provider_factory: Callable[[], Any] = ParameterCompatibleOpenRouterClient,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    root = Path(run_root)
    design = build_design(contract)
    _atomic_write(root / "design.json", design)
    if stop_after == "design":
        return design

    provider_free = await run_provider_free_gate(contract, run_root=root)
    if provider_free["status"] != "passed":
        raise ValueError("provider-free V3 objective campaign gate failed")
    if stop_after == "provider_free":
        return provider_free

    profile_admission = run_profile_admission_gate(
        contract,
        design=design,
        run_root=root,
    )
    if profile_admission["status"] != "passed":
        raise ValueError("profile-admission V3 objective campaign gate failed")
    if stop_after == "profile_admission":
        return profile_admission

    concurrency = asyncio.Semaphore(int(contract["execution"]["concurrency"]))
    route_locks = {
        str(model["provider"]): asyncio.Semaphore(1)
        for model in contract["models"].values()
    }

    async def execute(cell: Mapping[str, Any]) -> dict[str, Any]:
        provider_name = str(contract["models"][cell["model_id"]]["provider"])
        async with concurrency, route_locks[provider_name]:
            return await _run_live_cell(
                contract,
                cell,
                run_root=root,
                provider=provider_factory(),
            )

    rows = await asyncio.gather(*(execute(cell) for cell in design["cells"]))
    summary = summarize(contract, design, rows)
    _atomic_write(root / "live" / "summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT_PATH)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument(
        "--stop-after",
        choices=("design", "provider_free", "profile_admission", "live"),
        default="live",
    )
    arguments = parser.parse_args(argv)
    result = asyncio.run(
        run_campaign(
            contract_path=arguments.contract,
            run_root=arguments.run_root,
            stop_after=arguments.stop_after,
        )
    )
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CAMPAIGN_ID",
    "DEFAULT_CONTRACT_PATH",
    "DEFAULT_RUN_ROOT",
    "build_design",
    "load_contract",
    "main",
    "run_campaign",
]
