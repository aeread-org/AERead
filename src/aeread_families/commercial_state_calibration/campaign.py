"""Gated open-weight campaign for commercial-state calibration.

The v1 campaign is deliberately exploratory.  Its nine cases come from one
sanitized source archive, so repeated inference seeds measure response
stability and paired within-panel differences, not population-level model
superiority.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import io
import json
import os
import statistics
import time
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from itertools import combinations
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.campaign import (
    CAMPAIGN_GATE_SEQUENCE,
    CampaignGateRecord,
    CampaignHistoryRecord,
    CampaignInvalidationRecord,
    append_campaign_gate,
    append_campaign_invalidation,
    campaign_active_gate_records,
    campaign_gate_artifact_type,
    campaign_history_record_from_dict,
    campaign_history_record_to_dict,
    campaign_promotion_decision,
)
from aeread.shared_runner.task.execution import (
    EvidenceStore,
    OpenRouterChatClient,
    TokenPricing,
    execute_plan_cell,
)
from aeread.shared_runner.run.layout import RunLayout
from aeread.shared_runner.task.evaluation import audit_family_receipt
from aeread.shared_runner.quality import QCCoverage, QCEvidenceRef
from aeread.shared_runner.task.receipts import verify_evaluation_receipt
from aeread.shared_runner.run.resolver import canonical_json_bytes

from .cases import load_authoring_records, load_cases
from .environment import FAMILY_ID, FAMILY_VERSION
from .runner import (
    OpenRouterRoute,
    build_offline_setup,
    build_openrouter_setup,
    finalize_commercial_state_execution,
    finalize_commercial_state_failure,
    run_fixture_response,
)


CONTRACT_SCHEMA_VERSION = "aeread.commercial_state_campaign/0.1"
CAMPAIGN_ID = "commercial_state_openweight_variance_v1"
V2_CAMPAIGN_ID = "commercial_state_openweight_variance_v2"
V3_CAMPAIGN_ID = "commercial_state_openweight_variance_v3"
V4_CAMPAIGN_ID = "commercial_state_openweight_variance_v4"
STAGES = CAMPAIGN_GATE_SEQUENCE[:5]
DEFAULT_CONTRACT_PATH = (
    Path(__file__).resolve().parents[3]
    / "configs"
    / "commercial_state_openweight_variance_v1.json"
)
V2_CONTRACT_PATH = (
    Path(__file__).resolve().parents[3]
    / "configs"
    / "commercial_state_openweight_variance_v2.json"
)
V3_CONTRACT_PATH = (
    Path(__file__).resolve().parents[3]
    / "configs"
    / "commercial_state_openweight_variance_v3.json"
)
V4_CONTRACT_PATH = (
    Path(__file__).resolve().parents[3]
    / "configs"
    / "commercial_state_openweight_variance_v4.json"
)

MODEL_ROUTE_PINS: Mapping[str, Mapping[str, Any]] = {
    "glm53_flash": {
        "requested_model": "z-ai/glm-5.3-flash",
        "canonical_model": "z-ai/glm-5.3-flash-20260826",
        "provider": "DeepInfra",
        "quantization": "fp8",
        "profile_id": "commercial_state_glm53_flash_v1",
        "access_class": "open_source",
        "license_id": "MIT",
        "pricing": {
            "input_per_million": 0.075,
            "cached_input_per_million": 0.015,
            "output_per_million": 0.25,
            "pricing_id": "openrouter_2026-08-31_glm53_flash_deepinfra",
        },
    },
    "mistral_small4": {
        "requested_model": "mistralai/mistral-small-2603",
        "canonical_model": "mistralai/mistral-small-2603",
        "provider": "Mistral",
        "quantization": "unknown",
        "profile_id": "commercial_state_mistral_small4_v1",
        "access_class": "open_source",
        "license_id": "Apache-2.0",
        "pricing": {
            "input_per_million": 0.15,
            "cached_input_per_million": 0.015,
            "output_per_million": 0.6,
            "pricing_id": "openrouter_2026-08-31_mistral_small4_mistral",
        },
    },
    "qwen38_flash": {
        "requested_model": "qwen/qwen3.8-flash",
        "canonical_model": "qwen/qwen3.8-flash-20260826",
        "provider": "Alibaba",
        "quantization": "unknown",
        "profile_id": "commercial_state_qwen38_flash_v1",
        "access_class": "open_weight_custom_license",
        "license_id": "custom",
        "pricing": {
            "input_per_million": 0.15,
            "cached_input_per_million": 0.016,
            "output_per_million": 0.47,
            "pricing_id": "openrouter_2026-08-31_qwen38_flash_alibaba",
        },
    },
    "minimax_m3": {
        "requested_model": "minimax/minimax-m3",
        "canonical_model": "minimax/minimax-m3-20260531",
        "provider": "CoreWeave",
        "quantization": "fp4",
        "profile_id": "commercial_state_minimax_m3_v1",
        "access_class": "open_weight_custom_license",
        "license_id": "custom",
        "pricing": {
            "input_per_million": 0.23,
            "cached_input_per_million": 0.05,
            "output_per_million": 0.96,
            "pricing_id": "openrouter_2026-08-31_minimax_m3_coreweave",
        },
    },
}

V2_MODEL_ROUTE_PINS: Mapping[str, Mapping[str, Any]] = {
    "glm53_flash": {
        "requested_model": "z-ai/glm-5.3-flash",
        "canonical_model": "z-ai/glm-5.3-flash-20260826",
        "provider": "Cloudflare",
        "quantization": "unknown",
        "profile_id": "commercial_state_glm53_flash_cloudflare_v2",
        "access_class": "open_source",
        "license_id": "MIT",
        "pricing": {
            "input_per_million": 0.15,
            "cached_input_per_million": 0.03,
            "output_per_million": 0.5,
            "pricing_id": "openrouter_2026-09-02_glm53_flash_cloudflare",
        },
    },
    "mistral_small4": {
        "requested_model": "mistralai/mistral-small-2603",
        "canonical_model": "mistralai/mistral-small-2603",
        "provider": "Mistral",
        "quantization": "unknown",
        "profile_id": "commercial_state_mistral_small4_v2",
        "access_class": "open_source",
        "license_id": "Apache-2.0",
        "pricing": {
            "input_per_million": 0.15,
            "cached_input_per_million": 0.015,
            "output_per_million": 0.6,
            "pricing_id": "openrouter_2026-09-02_mistral_small4_mistral",
        },
    },
    "qwen38_flash": {
        "requested_model": "qwen/qwen3.8-flash",
        "canonical_model": "qwen/qwen3.8-flash-20260826",
        "provider": "Alibaba",
        "quantization": "unknown",
        "profile_id": "commercial_state_qwen38_flash_v2",
        "access_class": "open_weight_custom_license",
        "license_id": "custom",
        "pricing": {
            "input_per_million": 0.15,
            "cached_input_per_million": 0.016,
            "output_per_million": 0.47,
            "pricing_id": "openrouter_2026-09-02_qwen38_flash_alibaba",
        },
    },
    "minimax_m3": {
        "requested_model": "minimax/minimax-m3",
        "canonical_model": "minimax/minimax-m3-20260531",
        "provider": "Parasail",
        "quantization": "fp8",
        "profile_id": "commercial_state_minimax_m3_parasail_v2",
        "access_class": "open_weight_custom_license",
        "license_id": "custom",
        "pricing": {
            "input_per_million": 0.3,
            "cached_input_per_million": 0.06,
            "output_per_million": 1.2,
            "pricing_id": "openrouter_2026-09-02_minimax_m3_parasail",
        },
    },
}

V3_MODEL_ROUTE_PINS: Mapping[str, Mapping[str, Any]] = {
    "glm53_flash": {
        "requested_model": "z-ai/glm-5.3-flash",
        "canonical_model": "z-ai/glm-5.3-flash-20260826",
        "provider": "Reka",
        "quantization": "fp8",
        "profile_id": "commercial_state_glm53_flash_reka_v3",
        "access_class": "open_source",
        "license_id": "MIT",
        "pricing": {
            "input_per_million": 0.15,
            "cached_input_per_million": 0.03,
            "output_per_million": 0.5,
            "pricing_id": "openrouter_2026-09-02_glm53_flash_reka",
        },
    },
    "mistral_small4": {
        "requested_model": "mistralai/mistral-small-2603",
        "canonical_model": "mistralai/mistral-small-2603",
        "provider": "Mistral",
        "quantization": "unknown",
        "profile_id": "commercial_state_mistral_small4_v3",
        "access_class": "open_source",
        "license_id": "Apache-2.0",
        "pricing": {
            "input_per_million": 0.15,
            "cached_input_per_million": 0.015,
            "output_per_million": 0.6,
            "pricing_id": "openrouter_2026-09-02_mistral_small4_mistral",
        },
    },
    "qwen38_flash": {
        "requested_model": "qwen/qwen3.8-flash",
        "canonical_model": "qwen/qwen3.8-flash-20260826",
        "provider": "Alibaba",
        "quantization": "unknown",
        "profile_id": "commercial_state_qwen38_flash_v3",
        "access_class": "open_weight_custom_license",
        "license_id": "custom",
        "pricing": {
            "input_per_million": 0.15,
            "cached_input_per_million": 0.016,
            "output_per_million": 0.47,
            "pricing_id": "openrouter_2026-09-02_qwen38_flash_alibaba",
        },
    },
    "minimax_m3": {
        "requested_model": "minimax/minimax-m3",
        "canonical_model": "minimax/minimax-m3-20260531",
        "provider": "Parasail",
        "quantization": "fp8",
        "profile_id": "commercial_state_minimax_m3_parasail_v3",
        "access_class": "open_weight_custom_license",
        "license_id": "custom",
        "pricing": {
            "input_per_million": 0.3,
            "cached_input_per_million": 0.06,
            "output_per_million": 1.2,
            "pricing_id": "openrouter_2026-09-02_minimax_m3_parasail",
        },
    },
}

V4_MODEL_ROUTE_PINS: Mapping[str, Mapping[str, Any]] = {
    "glm53_flash": {
        "requested_model": "z-ai/glm-5.3-flash",
        "canonical_model": "z-ai/glm-5.3-flash-20260826",
        "provider": "Reka",
        "quantization": "fp8",
        "profile_id": "commercial_state_glm53_flash_reka_v4",
        "access_class": "open_source",
        "license_id": "MIT",
        "pricing": {
            "input_per_million": 0.15,
            "cached_input_per_million": 0.03,
            "output_per_million": 0.5,
            "pricing_id": "openrouter_2026-09-02_glm53_flash_reka",
        },
    },
    "mistral_small4": {
        "requested_model": "mistralai/mistral-small-2603",
        "canonical_model": "mistralai/mistral-small-2603",
        "provider": "Mistral",
        "quantization": "unknown",
        "profile_id": "commercial_state_mistral_small4_v4",
        "access_class": "open_source",
        "license_id": "Apache-2.0",
        "pricing": {
            "input_per_million": 0.15,
            "cached_input_per_million": 0.015,
            "output_per_million": 0.6,
            "pricing_id": "openrouter_2026-09-02_mistral_small4_mistral",
        },
    },
    "qwen38_flash": {
        "requested_model": "qwen/qwen3.8-flash",
        "canonical_model": "qwen/qwen3.8-flash-20260826",
        "provider": "Alibaba",
        "quantization": "unknown",
        "profile_id": "commercial_state_qwen38_flash_v4",
        "access_class": "open_weight_custom_license",
        "license_id": "custom",
        "pricing": {
            "input_per_million": 0.15,
            "cached_input_per_million": 0.016,
            "output_per_million": 0.47,
            "pricing_id": "openrouter_2026-09-02_qwen38_flash_alibaba",
        },
    },
}

CAMPAIGN_MODEL_ROUTE_PINS: Mapping[
    str, Mapping[str, Mapping[str, Any]]
] = {
    CAMPAIGN_ID: MODEL_ROUTE_PINS,
    V2_CAMPAIGN_ID: V2_MODEL_ROUTE_PINS,
    V3_CAMPAIGN_ID: V3_MODEL_ROUTE_PINS,
    V4_CAMPAIGN_ID: V4_MODEL_ROUTE_PINS,
}

EXPECTED_CONTROLS: Mapping[str, Any] = {
    "harness": "minimal_chat/1.0",
    "tools": "disabled",
    "memory": "disabled",
    "reasoning_effort": None,
    "temperature": 0.0,
    "top_p": None,
    "max_output_tokens": 1200,
    "timeout_seconds": 180.0,
    "sdk_retries": 0,
    "max_action_attempts": 1,
    "retryable_conditions": [],
    "max_cost_usd_per_cell": 0.005,
    "parallelism": 4,
    "condition_order": "rotate_model_by_case_and_seed",
}

V3_EXPECTED_CONTROLS: Mapping[str, Any] = {
    **EXPECTED_CONTROLS,
    "max_output_tokens": 4096,
    "max_cost_usd_per_cell": 0.006,
}

V4_EXPECTED_CONTROLS: Mapping[str, Any] = {
    **EXPECTED_CONTROLS,
    "parallelism": 3,
}

CAMPAIGN_EXPECTED_CONTROLS: Mapping[str, Mapping[str, Any]] = {
    CAMPAIGN_ID: EXPECTED_CONTROLS,
    V2_CAMPAIGN_ID: EXPECTED_CONTROLS,
    V3_CAMPAIGN_ID: V3_EXPECTED_CONTROLS,
    V4_CAMPAIGN_ID: V4_EXPECTED_CONTROLS,
}


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sealed(value: Mapping[str, Any]) -> dict[str, Any]:
    core = {key: item for key, item in value.items() if key != "artifact_sha256"}
    return {**core, "artifact_sha256": _sha256(core)}


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_write(path, canonical_json_bytes(value) + b"\n")


def _publish_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_file() and path.read_bytes() == payload:
            return
        raise ValueError(f"refusing to overwrite a different campaign export: {path}")
    _atomic_write(path, payload)


def _read_sealed(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, Mapping) or canonical_json_bytes(value) != canonical_json_bytes(
        _sealed(value)
    ):
        raise ValueError(f"artifact digest mismatch: {path}")
    return dict(value)


def _campaign_implementation_sha256() -> str:
    return _file_sha256(Path(__file__))


def load_contract(path: str | Path = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    value = json.loads(Path(path).read_bytes())
    if not isinstance(value, dict):
        raise ValueError("campaign contract must be a JSON object")
    required = {
        "schema_version",
        "campaign_id",
        "claim_status",
        "question",
        "primary_estimand",
        "focal_factor",
        "independent_cluster",
        "case_panel",
        "controls",
        "models",
        "full_trajectory",
        "variance_pilot",
        "missingness",
        "stopping_rule",
    }
    if set(value) != required:
        raise ValueError("campaign contract fields are incomplete or unexpected")
    if value["schema_version"] != CONTRACT_SCHEMA_VERSION:
        raise ValueError("unsupported commercial-state campaign schema")
    campaign_id = value["campaign_id"]
    route_pins = CAMPAIGN_MODEL_ROUTE_PINS.get(campaign_id)
    if route_pins is None:
        supported = ", ".join(sorted(CAMPAIGN_MODEL_ROUTE_PINS))
        raise ValueError(f"unsupported campaign_id; expected one of: {supported}")
    expected_controls = CAMPAIGN_EXPECTED_CONTROLS[campaign_id]
    if value["claim_status"] != "exploratory_variance_pilot":
        raise ValueError("the one-cluster campaign must remain exploratory")
    if value["primary_estimand"] != "commercial_state_safe_accuracy":
        raise ValueError("primary estimand drifted")
    if value["focal_factor"] != "model_plus_provider_route":
        raise ValueError("focal factor must include provider-route differences")
    if value["independent_cluster"] != "source_archive":
        raise ValueError("independent cluster must remain source_archive")

    manifest, records, _ = load_authoring_records()
    case_slugs = [record["case_slug"] for record in records]
    case_panel = value["case_panel"]
    if case_panel != {
        "family": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "case_slugs": case_slugs,
        "independence_cluster_ids": ["commercial_archive_pilot_01"],
    }:
        raise ValueError("commercial-state case panel drifted")
    if manifest["inference_status"] != "diagnostic_only":
        raise ValueError("source pack must remain diagnostic-only")
    if value["controls"] != expected_controls:
        raise ValueError("commercial-state execution controls drifted")
    if set(value["models"]) != set(route_pins):
        raise ValueError("open-weight model panel drifted")
    for model_id, expected in route_pins.items():
        if value["models"].get(model_id) != expected:
            raise ValueError(f"model route or price pin drifted for {model_id}")
        if "deepseek" in json.dumps(value["models"][model_id]).lower():
            raise ValueError("DeepSeek is excluded from this campaign")

    full = value["full_trajectory"]
    pilot = value["variance_pilot"]
    stage_fields = {
        "case_slugs",
        "inference_seeds",
        "cost_ceiling_usd",
        "maximum_operational_failure_fraction",
        "winner_claim_allowed",
    }
    for name, stage in (("full_trajectory", full), ("variance_pilot", pilot)):
        if not isinstance(stage, dict) or set(stage) != stage_fields:
            raise ValueError(f"{name} contract fields drifted")
        seeds = stage["inference_seeds"]
        if (
            not isinstance(seeds, list)
            or not seeds
            or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seeds)
            or len(seeds) != len(set(seeds))
        ):
            raise ValueError(f"{name} inference seeds are invalid")
        slugs = stage["case_slugs"]
        if (
            not isinstance(slugs, list)
            or not slugs
            or len(slugs) != len(set(slugs))
            or not set(slugs).issubset(case_slugs)
        ):
            raise ValueError(f"{name} case panel is invalid")
        ceiling = stage["cost_ceiling_usd"]
        if isinstance(ceiling, bool) or not isinstance(ceiling, (int, float)) or ceiling <= 0:
            raise ValueError(f"{name} cost ceiling is invalid")
        missing = stage["maximum_operational_failure_fraction"]
        if isinstance(missing, bool) or not isinstance(missing, (int, float)) or not 0 <= missing <= 1:
            raise ValueError(f"{name} missingness ceiling is invalid")
        if stage["winner_claim_allowed"] is not False:
            raise ValueError(f"{name} cannot authorize a winner claim")
    if full["case_slugs"] != ["payment-release-reconcile"] or len(full["inference_seeds"]) != 1:
        raise ValueError("full-trajectory panel drifted")
    if pilot["case_slugs"] != case_slugs or len(pilot["inference_seeds"]) != 3:
        raise ValueError("variance-pilot panel drifted")
    if set(full["inference_seeds"]) & set(pilot["inference_seeds"]):
        raise ValueError("full-trajectory and variance-pilot seeds must be disjoint")
    return value


def _route_for(contract: Mapping[str, Any], model_id: str) -> OpenRouterRoute:
    model = contract["models"][model_id]
    pricing = model["pricing"]
    return OpenRouterRoute(
        profile_id=model["profile_id"],
        model=model["requested_model"],
        revision=model["canonical_model"],
        route_provider=model["provider"],
        quantization=model["quantization"],
        pricing=TokenPricing(
            input_per_million=float(pricing["input_per_million"]),
            cached_input_per_million=float(pricing["cached_input_per_million"]),
            output_per_million=float(pricing["output_per_million"]),
            pricing_id=pricing["pricing_id"],
        ),
        max_prompt_price_per_million=str(pricing["input_per_million"]),
        max_completion_price_per_million=str(pricing["output_per_million"]),
        reasoning_effort=contract["controls"]["reasoning_effort"],
        temperature_supported=True,
    )


def _build_setup(
    contract: Mapping[str, Any], model_id: str, case_slug: str, inference_seed: int
) -> Any:
    controls = contract["controls"]
    return build_openrouter_setup(
        _route_for(contract, model_id),
        seed=inference_seed,
        case_slug=case_slug,
        max_output_tokens=controls["max_output_tokens"],
        timeout_seconds=controls["timeout_seconds"],
        max_cost_usd=controls["max_cost_usd_per_cell"],
    )


def _cell_key(model_id: str, case_slug: str, inference_seed: int) -> str:
    return f"{model_id}__{case_slug}__seed_{inference_seed}"


def _stage_cells(
    contract: Mapping[str, Any], stage: str
) -> tuple[dict[str, Any], ...]:
    stage_contract = contract[stage]
    models = list(contract["models"])
    rows: list[dict[str, Any]] = []
    for seed_index, inference_seed in enumerate(stage_contract["inference_seeds"]):
        for case_index, case_slug in enumerate(stage_contract["case_slugs"]):
            offset = (seed_index + case_index) % len(models)
            rotated = models[offset:] + models[:offset]
            for model_id in rotated:
                rows.append(
                    {
                        "cell_key": _cell_key(model_id, case_slug, inference_seed),
                        "model_id": model_id,
                        "case_slug": case_slug,
                        "inference_seed": inference_seed,
                    }
                )
    return tuple(rows)


def _assert_setup_controls(
    setup: Any, contract: Mapping[str, Any], *, model_id: str, case_slug: str, inference_seed: int
) -> None:
    if len(setup.plan.cells) != 1 or len(setup.plan.agent_profiles) != 1:
        raise ValueError("each campaign plan must resolve to exactly one cell and profile")
    cell = setup.plan.cells[0]
    profile = setup.plan.agent_profiles[0]
    model = contract["models"][model_id]
    controls = contract["controls"]
    if cell.case_id != f"{FAMILY_ID}.pilot.{case_slug}":
        raise ValueError("campaign cell resolved the wrong case")
    if (
        profile.profile_id != model["profile_id"]
        or profile.model.model != model["requested_model"]
        or profile.model.revision != model["canonical_model"]
        or profile.harness.id != "minimal_chat"
        or profile.harness.version != "1.0"
        or profile.sampling.temperature != controls["temperature"]
        or profile.sampling.top_p != controls["top_p"]
        or profile.sampling.seed != inference_seed
        or profile.sampling.max_output_tokens != controls["max_output_tokens"]
        or profile.budgets.timeout_seconds != controls["timeout_seconds"]
        or profile.budgets.max_cost_usd != controls["max_cost_usd_per_cell"]
        or profile.retry_policy.max_action_attempts != controls["max_action_attempts"]
        or list(profile.retry_policy.retryable_conditions) != controls["retryable_conditions"]
        or profile.retry_policy.sdk_retries != controls["sdk_retries"]
        or profile.reasoning.effort != controls["reasoning_effort"]
        or profile.tools
        or profile.memory.mode != "disabled"
    ):
        raise ValueError(f"resolved profile controls drifted for {model_id}")


def design_contract_artifact(contract: Mapping[str, Any]) -> dict[str, Any]:
    cases = {case.case_id: case for case in load_cases()}
    stage_rows: dict[str, list[dict[str, Any]]] = {}
    pair_digests: dict[tuple[str, str, int], str] = {}
    for stage in ("full_trajectory", "variance_pilot"):
        resolved: list[dict[str, Any]] = []
        for cell_spec in _stage_cells(contract, stage):
            setup = _build_setup(contract, **{key: cell_spec[key] for key in ("model_id", "case_slug", "inference_seed")})
            _assert_setup_controls(setup, contract, **{key: cell_spec[key] for key in ("model_id", "case_slug", "inference_seed")})
            cell = setup.plan.cells[0]
            case = cases[cell.case_id]
            pair_key = (stage, cell_spec["case_slug"], cell_spec["inference_seed"])
            previous = pair_digests.setdefault(pair_key, case.content_sha256)
            if previous != case.content_sha256:
                raise ValueError("paired model conditions resolved different case bytes")
            resolved.append(
                {
                    **cell_spec,
                    "run_plan_id": setup.plan.run_plan_id,
                    "run_plan_sha256": setup.plan.plan_sha256,
                    "cell_id": cell.cell_id,
                    "case_id": cell.case_id,
                    "case_sha256": cell.case_sha256,
                    "cluster_id": case.payload["public_case"]["independence_cluster_id"],
                    "profile_sha256": _sha256(setup.plan.agent_profiles[0]),
                }
            )
        stage_rows[stage] = resolved
    return _sealed(
        {
            "schema_version": "aeread.commercial_state_campaign_design/0.1",
            "campaign_id": contract["campaign_id"],
            "contract_sha256": _sha256(contract),
            "campaign_implementation_sha256": _campaign_implementation_sha256(),
            "status": "passed",
            "claim_status": contract["claim_status"],
            "primary_estimand": contract["primary_estimand"],
            "focal_factor": contract["focal_factor"],
            "independent_cluster": contract["independent_cluster"],
            "independent_cluster_count": 1,
            "paired_by": ["case_slug", "inference_seed"],
            "inferential_model_ranking_allowed": False,
            "stage_plan_counts": {
                stage: len(rows) for stage, rows in stage_rows.items()
            },
            "plans": stage_rows,
        }
    )


def _strong_response(case: Any) -> dict[str, Any]:
    family_case = case.payload
    gold = family_case["oracle"]["gold"]
    return {
        "case_id": case.case_id,
        "states": _plain(gold["states"]),
        "amounts": _plain(gold["amounts"]),
        "actions": list(gold["required_actions"]),
        "claims": list(gold["required_claims"]),
        "evidence_ids": list(gold["required_evidence_ids"]),
        "external_actions_attempted": [],
    }


def _receipt_path(execution: Any) -> Path:
    return execution.evidence.root / "evaluation_receipt.json"


async def _run_offline_response(
    *, case_slug: str, response_text: str, evidence_root: Path
) -> dict[str, Any]:
    setup = build_offline_setup(case_slug=case_slug)
    execution = await run_fixture_response(
        response_text,
        evidence_root=evidence_root,
        case_slug=case_slug,
    )
    receipt = finalize_commercial_state_execution(setup=setup, execution=execution)
    verify_evaluation_receipt(receipt)
    path = _receipt_path(execution)
    audit_family_receipt(setup=setup, receipt_path=path)
    outcome = _plain(execution.episode_result.outcome)
    return {
        "case_slug": case_slug,
        "receipt_sha256": receipt.receipt_sha256,
        "receipt_path": str(path.relative_to(evidence_root)),
        "status": receipt.status,
        "inclusion_status": receipt.inclusion_status,
        "score": outcome.get("score"),
        "valid": outcome.get("valid"),
        "hard_gate_pass": outcome.get("hard_gate_pass"),
        "failure_code": outcome.get("failure_code"),
        "replay_verified": True,
        "provider_cost_usd": execution.total_cost_usd,
    }


async def run_provider_free(
    contract: Mapping[str, Any], *, output_root: Path, attempt_index: int = 1
) -> dict[str, Any]:
    stage_root = _live_stage_root(output_root, "provider_free_validation", attempt_index)
    rows: list[dict[str, Any]] = []
    for case in load_cases():
        case_slug = case.case_id.rsplit(".", 1)[-1]
        row = await _run_offline_response(
            case_slug=case_slug,
            response_text=canonical_json_bytes(_strong_response(case)).decode("utf-8"),
            evidence_root=stage_root / "evidence" / f"strong__{case_slug}",
        )
        if row["score"] != 1.0 or row["hard_gate_pass"] is not True:
            raise ValueError(f"strong provider-free response failed for {case_slug}")
        rows.append({"check_id": f"case.{case_slug}.strong", **row})

    fixtures = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "commercial_state_calibration"
    boundary_specs = (
        ("valid_but_poor", (fixtures / "valid_but_poor.json").read_text(encoding="utf-8")),
        ("hard_gate_failed", (fixtures / "hard_gate_failed.json").read_text(encoding="utf-8")),
        ("malformed", "not-json"),
    )
    for name, response_text in boundary_specs:
        row = await _run_offline_response(
            case_slug="payment-release-reconcile",
            response_text=response_text,
            evidence_root=stage_root / "evidence" / f"boundary__{name}",
        )
        if name == "valid_but_poor" and not (
            row["status"] == "ok" and row["score"] is not None and 0 < row["score"] < 1
        ):
            raise ValueError("valid-but-poor fixture lost its diagnostic score")
        if name == "hard_gate_failed" and not (
            row["status"] == "ok" and row["score"] == 0 and row["hard_gate_pass"] is False
        ):
            raise ValueError("hard-gate fixture no longer produces zero primary score")
        if name == "malformed" and not (
            row["status"] == "ok"
            and row["inclusion_status"] == "included"
            and row["valid"] is False
            and row["score"] == 0
            and row["failure_code"] == "malformed_json"
        ):
            raise ValueError("malformed fixture no longer produces a scored invalid action")
        rows.append({"check_id": f"boundary.{name}", **row})

    artifact = _sealed(
        {
            "schema_version": "aeread.commercial_state_provider_free/0.1",
            "campaign_id": contract["campaign_id"],
            "status": "passed",
            "case_count": len(load_cases()),
            "check_count": len(rows),
            "replay_verified": all(row["replay_verified"] for row in rows),
            "provider_cost_usd": sum(float(row["provider_cost_usd"]) for row in rows),
            "checks": rows,
        }
    )
    _write_json(stage_root / "summary.json", artifact)
    return artifact


def _endpoint_url(model: str) -> str:
    return "https://openrouter.ai/api/v1/models/" + urllib.parse.quote(
        model, safe="/:"
    ) + "/endpoints"


def _load_endpoint_catalog(model: str) -> Mapping[str, Any]:
    request = urllib.request.Request(
        _endpoint_url(model),
        headers={"User-Agent": "AERead commercial-state campaign/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30.0) as response:
        payload = json.load(response)
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise RuntimeError(f"OpenRouter returned no endpoint data for {model}")
    return data


def _admit_model_endpoint(
    contract: Mapping[str, Any], model_id: str, endpoint_loader: Callable[[str], Mapping[str, Any]]
) -> dict[str, Any]:
    model = contract["models"][model_id]
    data = endpoint_loader(model["requested_model"])
    endpoints = data.get("endpoints")
    if not isinstance(endpoints, list):
        raise RuntimeError(f"OpenRouter returned no endpoints for {model_id}")
    required_parameters = {"max_tokens", "response_format", "seed", "structured_outputs"}
    identity_matches: list[Mapping[str, Any]] = []
    eligible: list[Mapping[str, Any]] = []
    for endpoint in endpoints:
        if not isinstance(endpoint, Mapping) or not isinstance(endpoint.get("pricing"), Mapping):
            continue
        name = str(endpoint.get("name") or "")
        if (
            endpoint.get("provider_name") == model["provider"]
            and endpoint.get("quantization") == model["quantization"]
            and name.endswith(model["canonical_model"])
        ):
            identity_matches.append(endpoint)
            prompt_price = float(endpoint["pricing"]["prompt"]) * 1_000_000
            completion_price = float(endpoint["pricing"]["completion"]) * 1_000_000
            if (
                prompt_price <= float(model["pricing"]["input_per_million"]) + 1e-12
                and completion_price <= float(model["pricing"]["output_per_million"]) + 1e-12
                and required_parameters.issubset(set(endpoint.get("supported_parameters") or ()))
            ):
                eligible.append(endpoint)
    if identity_matches and not eligible:
        raise RuntimeError(f"route price or required parameters drifted for {model_id}")
    if not eligible:
        raise RuntimeError(f"no eligible pinned endpoint for {model_id}")
    setup = _build_setup(
        contract,
        model_id,
        contract["full_trajectory"]["case_slugs"][0],
        contract["full_trajectory"]["inference_seeds"][0],
    )
    _assert_setup_controls(
        setup,
        contract,
        model_id=model_id,
        case_slug=contract["full_trajectory"]["case_slugs"][0],
        inference_seed=contract["full_trajectory"]["inference_seeds"][0],
    )
    prices = [
        {
            "prompt_per_million": float(endpoint["pricing"]["prompt"]) * 1_000_000,
            "completion_per_million": float(endpoint["pricing"]["completion"]) * 1_000_000,
        }
        for endpoint in eligible
    ]
    return {
        "model_id": model_id,
        "profile_id": model["profile_id"],
        "status": "passed",
        "requested_model": model["requested_model"],
        "canonical_model": model["canonical_model"],
        "provider": model["provider"],
        "quantization": model["quantization"],
        "access_class": model["access_class"],
        "license_id": model["license_id"],
        "eligible_endpoint_count": len(eligible),
        "prompt_per_million_range": [
            min(row["prompt_per_million"] for row in prices),
            max(row["prompt_per_million"] for row in prices),
        ],
        "completion_per_million_range": [
            min(row["completion_per_million"] for row in prices),
            max(row["completion_per_million"] for row in prices),
        ],
        "supported_parameters_verified": sorted(required_parameters),
        "run_plan_id": setup.plan.run_plan_id,
        "run_plan_sha256": setup.plan.plan_sha256,
        "profile_sha256": _sha256(setup.plan.agent_profiles[0]),
        "source": _endpoint_url(model["requested_model"]),
    }


async def run_profile_admission(
    contract: Mapping[str, Any],
    *,
    endpoint_loader: Callable[[str], Mapping[str, Any]] = _load_endpoint_catalog,
) -> dict[str, Any]:
    model_ids = list(contract["models"])
    rows = await asyncio.gather(
        *(
            asyncio.to_thread(_admit_model_endpoint, contract, model_id, endpoint_loader)
            for model_id in model_ids
        )
    )
    artifact = _sealed(
        {
            "schema_version": "aeread.commercial_state_profile_admission/0.1",
            "campaign_id": contract["campaign_id"],
            "status": "passed",
            "admission_kind": "route_metadata_and_resolved_profile",
            "live_model_output_observed": False,
            "provider_cost_usd": 0.0,
            "hidden_retry_count": 0,
            "results": rows,
        }
    )
    return artifact


def _live_stage_root(output_root: Path, stage: str, attempt_index: int) -> Path:
    base = output_root / stage
    return base if attempt_index == 1 else base / f"attempt_{attempt_index}"


def _usage_from_receipt_path(receipt_path: Path) -> dict[str, Any]:
    evidence = EvidenceStore.audit_existing(receipt_path.parent)
    calls_started = 0
    calls_succeeded = 0
    input_tokens = 0
    cached_input_tokens = 0
    output_tokens = 0
    cost_usd = 0.0
    resolved_models: set[str] = set()
    selected_providers: set[str] = set()
    for event in evidence.read_events():
        if event.event_type == "provider_call_started":
            calls_started += 1
        if event.event_type != "provider_call_succeeded":
            continue
        calls_succeeded += 1
        payload = evidence.read_event_payload(event)
        if not isinstance(payload, Mapping):
            continue
        provider_result = payload.get("provider_result")
        if not isinstance(provider_result, Mapping):
            continue
        input_tokens += int(provider_result.get("input_tokens") or 0)
        cached_input_tokens += int(provider_result.get("cached_input_tokens") or 0)
        output_tokens += int(provider_result.get("output_tokens") or 0)
        cost_usd += float(provider_result.get("cost_usd") or 0.0)
        if provider_result.get("resolved_model"):
            resolved_models.add(str(provider_result["resolved_model"]))
        raw = provider_result.get("raw_response")
        if isinstance(raw, Mapping) and raw.get("provider"):
            selected_providers.add(str(raw["provider"]))
    evidence.close()
    return {
        "provider_calls_started": calls_started,
        "provider_calls_succeeded": calls_succeeded,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "resolved_models": sorted(resolved_models),
        "selected_providers": sorted(selected_providers),
    }


def _validate_resumed_row(
    row: Mapping[str, Any], cell_spec: Mapping[str, Any], setup: Any, output_root: Path
) -> None:
    expected = {key: cell_spec[key] for key in ("cell_key", "model_id", "case_slug", "inference_seed")}
    if any(row.get(key) != value for key, value in expected.items()):
        raise ValueError(f"resumed row identity drifted for {cell_spec['cell_key']}")
    receipt_value = row.get("receipt_path")
    if not isinstance(receipt_value, str) or not receipt_value:
        raise ValueError(f"resumed row lacks a receipt for {cell_spec['cell_key']}")
    receipt_path = (output_root / receipt_value).resolve(strict=True)
    receipt_path.relative_to(output_root.resolve(strict=True))
    audited = audit_family_receipt(setup=setup, receipt_path=receipt_path)
    if audited.get("receipt_sha256") != row.get("receipt_sha256"):
        raise ValueError(f"resumed receipt digest drifted for {cell_spec['cell_key']}")


async def _execute_live_cell(
    *,
    contract: Mapping[str, Any],
    stage_root: Path,
    output_root: Path,
    cell_spec: Mapping[str, Any],
    expected_plan: Mapping[str, Any],
    provider: Any,
    attempt_index: int,
) -> dict[str, Any]:
    result_path = stage_root / "cells" / cell_spec["cell_key"] / "result.json"
    setup = _build_setup(
        contract,
        cell_spec["model_id"],
        cell_spec["case_slug"],
        cell_spec["inference_seed"],
    )
    _assert_setup_controls(
        setup,
        contract,
        model_id=cell_spec["model_id"],
        case_slug=cell_spec["case_slug"],
        inference_seed=cell_spec["inference_seed"],
    )
    cell = setup.plan.cells[0]
    if (
        setup.plan.run_plan_id != expected_plan["run_plan_id"]
        or setup.plan.plan_sha256 != expected_plan["run_plan_sha256"]
        or cell.cell_id != expected_plan["cell_id"]
        or cell.case_sha256 != expected_plan["case_sha256"]
    ):
        raise ValueError(f"live plan drifted from design gate for {cell_spec['cell_key']}")
    if result_path.exists():
        row = _read_sealed(result_path)
        _validate_resumed_row(row, cell_spec, setup, output_root)
        return row

    evidence_root = result_path.parent / "evidence"
    started = time.perf_counter()
    try:
        execution = await execute_plan_cell(
            plan=setup.plan,
            cell_id=cell.cell_id,
            registry=setup.registry,
            evidence_root=evidence_root,
            prompt_sources=setup.prompt_sources,
            providers={"openrouter": provider},
            pricing=setup.pricing,
            harnesses=setup.harnesses,
            episode_attempt_ordinal=attempt_index - 1,
        )
        receipt = finalize_commercial_state_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        receipt_path = _receipt_path(execution)
        audit_family_receipt(setup=setup, receipt_path=receipt_path)
        usage = _usage_from_receipt_path(receipt_path)
        outcome = _plain(execution.episode_result.outcome)
        row = {
            **cell_spec,
            "run_plan_id": setup.plan.run_plan_id,
            "run_plan_sha256": setup.plan.plan_sha256,
            "cell_id": cell.cell_id,
            "case_id": cell.case_id,
            "case_sha256": cell.case_sha256,
            "status": (
                "completed" if receipt.inclusion_status == "included" else "measurement_invalid"
            ),
            "receipt_status": receipt.status,
            "inclusion_status": receipt.inclusion_status,
            "receipt_sha256": receipt.receipt_sha256,
            "receipt_path": str(receipt_path.relative_to(output_root)),
            "replay_verified": True,
            "route_verified": (
                usage["resolved_models"] == [contract["models"][cell_spec["model_id"]]["canonical_model"]]
                and usage["selected_providers"] == [contract["models"][cell_spec["model_id"]]["provider"]]
            ),
            "elapsed_seconds": time.perf_counter() - started,
            "usage": usage,
            "metrics": outcome,
        }
    except Exception as error:
        receipt = finalize_commercial_state_failure(
            setup=setup,
            cell_id=cell.cell_id,
            evidence_root=evidence_root,
            error=error,
        )
        verify_evaluation_receipt(receipt)
        receipt_path = (
            RunLayout(evidence_root, setup.plan.run_plan_id).resolve_attempt_dir(
                cell.cell_id, receipt.episode_attempt_id
            )
            / "evaluation_receipt.json"
        )
        audit_family_receipt(setup=setup, receipt_path=receipt_path)
        usage = _usage_from_receipt_path(receipt_path)
        receipt_failure = receipt.failure
        row = {
            **cell_spec,
            "run_plan_id": setup.plan.run_plan_id,
            "run_plan_sha256": setup.plan.plan_sha256,
            "cell_id": cell.cell_id,
            "case_id": cell.case_id,
            "case_sha256": cell.case_sha256,
            "status": "operational_failure",
            "receipt_status": receipt.status,
            "inclusion_status": receipt.inclusion_status,
            "receipt_sha256": receipt.receipt_sha256,
            "receipt_path": str(receipt_path.relative_to(output_root)),
            "replay_verified": True,
            "route_verified": False,
            "failure_type": type(error).__name__,
            "failure_class": (
                None if receipt_failure is None else receipt_failure.failure_class
            ),
            "failure_condition": (
                getattr(error, "condition", "execution_error")
                if receipt_failure is None
                else receipt_failure.condition
            ),
            "failure_status_code": getattr(error, "status_code", None),
            "failure_message": str(error),
            "elapsed_seconds": time.perf_counter() - started,
            "usage": usage,
            "metrics": None,
        }
    sealed = _sealed(row)
    _write_json(result_path, sealed)
    return sealed


def _mean(values: Sequence[float]) -> float | None:
    return None if not values else statistics.fmean(values)


def _model_summaries(
    contract: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    component_names = (
        "score",
        "state_accuracy",
        "amount_accuracy",
        "required_action_recall",
        "required_claim_recall",
        "evidence_coverage",
    )
    for model_id in contract["models"]:
        selected = [row for row in rows if row["model_id"] == model_id]
        completed = [row for row in selected if row["status"] == "completed"]
        metrics = [row["metrics"] for row in completed]
        by_case: dict[str, list[float]] = {}
        for row in completed:
            by_case.setdefault(row["case_slug"], []).append(float(row["metrics"]["score"]))
        case_seed_std = [
            statistics.pstdev(values) for values in by_case.values() if len(values) > 1
        ]
        summaries.append(
            {
                "model_id": model_id,
                "profile_id": contract["models"][model_id]["profile_id"],
                "planned_cells": len(selected),
                "completed_cells": len(completed),
                "measurement_invalid_cells": sum(row["status"] == "measurement_invalid" for row in selected),
                "operational_failure_cells": sum(row["status"] == "operational_failure" for row in selected),
                "component_means": {
                    name: _mean([float(metric[name]) for metric in metrics])
                    for name in component_names
                },
                "hard_gate_pass_rate": _mean(
                    [1.0 if metric["hard_gate_pass"] else 0.0 for metric in metrics]
                ),
                "valid_rate": _mean([1.0 if metric["valid"] else 0.0 for metric in metrics]),
                "quality_band_counts": dict(sorted(Counter(metric["quality_band"] for metric in metrics).items())),
                "mean_within_case_seed_std": _mean(case_seed_std),
                "exact_seed_stability_rate": _mean(
                    [1.0 if len(set(values)) == 1 else 0.0 for values in by_case.values() if len(values) > 1]
                ),
                "median_elapsed_seconds": (
                    None if not completed else statistics.median(float(row["elapsed_seconds"]) for row in completed)
                ),
                "input_tokens": sum(int(row["usage"]["input_tokens"]) for row in selected),
                "cached_input_tokens": sum(int(row["usage"]["cached_input_tokens"]) for row in selected),
                "output_tokens": sum(int(row["usage"]["output_tokens"]) for row in selected),
                "cost_usd": sum(float(row["usage"]["cost_usd"]) for row in selected),
            }
        )
    return summaries


def _pairwise_contrasts(
    contract: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    completed = {
        (row["model_id"], row["case_slug"], row["inference_seed"]): float(row["metrics"]["score"])
        for row in rows
        if row["status"] == "completed"
    }
    results: list[dict[str, Any]] = []
    for left, right in combinations(contract["models"], 2):
        pairs = [
            (completed[(left, case_slug, seed)], completed[(right, case_slug, seed)])
            for case_slug in contract["variance_pilot"]["case_slugs"]
            for seed in contract["variance_pilot"]["inference_seeds"]
            if (left, case_slug, seed) in completed and (right, case_slug, seed) in completed
        ]
        differences = [right_value - left_value for left_value, right_value in pairs]
        results.append(
            {
                "left_model_id": left,
                "right_model_id": right,
                "contrast": f"{right}_minus_{left}",
                "complete_pair_count": len(pairs),
                "planned_pair_count": len(contract["variance_pilot"]["case_slugs"])
                * len(contract["variance_pilot"]["inference_seeds"]),
                "mean_score_difference": _mean(differences),
                "right_better_count": sum(value > 0 for value in differences),
                "equal_count": sum(value == 0 for value in differences),
                "left_better_count": sum(value < 0 for value in differences),
                "independent_cluster_count": 1,
                "confidence_interval": None,
                "inference_status": "descriptive_only_single_source_archive",
            }
        )
    return results


def _csv_payload(fieldnames: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                field: (
                    json.dumps(_plain(row.get(field)), sort_keys=True, separators=(",", ":"))
                    if isinstance(row.get(field), (dict, list, tuple))
                    else row.get(field)
                )
                for field in fieldnames
            }
        )
    return stream.getvalue().encode("utf-8")


def _export_fact_tables(
    *,
    contract: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    stage_root: Path,
) -> dict[str, Any]:
    analysis_root = stage_root / "analysis"
    profile_rows: list[dict[str, Any]] = []
    feature_rows: list[dict[str, Any]] = []
    for result_row in rows:
        model_id = result_row["model_id"]
        model = contract["models"][model_id]
        setup = _build_setup(
            contract,
            model_id,
            result_row["case_slug"],
            result_row["inference_seed"],
        )
        profile = setup.plan.agent_profiles[0]
        profile_rows.append(
            {
                "campaign_id": contract["campaign_id"],
                "cell_key": result_row["cell_key"],
                "run_plan_id": setup.plan.run_plan_id,
                "run_plan_sha256": setup.plan.plan_sha256,
                "model_id": model_id,
                "profile_id": model["profile_id"],
                "profile_sha256": _sha256(profile),
                "case_slug": result_row["case_slug"],
                "inference_seed": result_row["inference_seed"],
                "provider": model["provider"],
                "requested_model": model["requested_model"],
                "canonical_model": model["canonical_model"],
                "quantization": model["quantization"],
                "access_class": model["access_class"],
                "license_id": model["license_id"],
                "harness": contract["controls"]["harness"],
                "reasoning_effort": contract["controls"]["reasoning_effort"],
                "temperature": contract["controls"]["temperature"],
                "max_output_tokens": contract["controls"]["max_output_tokens"],
                "timeout_seconds": contract["controls"]["timeout_seconds"],
                "sdk_retries": contract["controls"]["sdk_retries"],
                "pricing": model["pricing"],
                "source_kind": "sealed_run_plan",
                "source_sha256": setup.plan.plan_sha256,
            }
        )
        for feature_name, feature_value, evidence_class in (
            (
                "structured_output_observed",
                result_row["status"] == "completed",
                "live_observed",
            ),
            ("inference_seed", result_row["inference_seed"], "declared"),
            ("external_tools_enabled", False, "declared"),
            ("memory_enabled", False, "declared"),
            ("license_id", model["license_id"], "declared"),
        ):
            feature_rows.append(
                {
                    "campaign_id": contract["campaign_id"],
                    "cell_key": result_row["cell_key"],
                    "model_id": model_id,
                    "profile_id": model["profile_id"],
                    "feature_name": feature_name,
                    "feature_value": feature_value,
                    "evidence_class": evidence_class,
                    "source_kind": (
                        "evaluation_receipt"
                        if evidence_class == "live_observed"
                        else "sealed_run_plan"
                    ),
                    "source_sha256": (
                        result_row["receipt_sha256"]
                        if evidence_class == "live_observed"
                        else setup.plan.plan_sha256
                    ),
                    "reportable": True,
                }
            )

    result_rows: list[dict[str, Any]] = []
    metric_names = (
        "score",
        "component_mean",
        "state_accuracy",
        "amount_accuracy",
        "required_action_recall",
        "required_claim_recall",
        "evidence_coverage",
        "hard_gate_pass",
        "valid",
    )
    for row in rows:
        metrics = row.get("metrics")
        if not isinstance(metrics, Mapping):
            result_rows.append(
                {
                    "campaign_id": contract["campaign_id"],
                    "cell_key": row["cell_key"],
                    "model_id": row["model_id"],
                    "case_slug": row["case_slug"],
                    "inference_seed": row["inference_seed"],
                    "receipt_sha256": row["receipt_sha256"],
                    "inclusion_status": row["inclusion_status"],
                    "metric_role": "status",
                    "metric_name": row["status"],
                    "value": None,
                    "unit": None,
                    "reportable": False,
                }
            )
            continue
        for metric_name in metric_names:
            value = metrics[metric_name]
            if isinstance(value, bool):
                value = 1.0 if value else 0.0
            result_rows.append(
                {
                    "campaign_id": contract["campaign_id"],
                    "cell_key": row["cell_key"],
                    "model_id": row["model_id"],
                    "case_slug": row["case_slug"],
                    "inference_seed": row["inference_seed"],
                    "receipt_sha256": row["receipt_sha256"],
                    "inclusion_status": row["inclusion_status"],
                    "metric_role": "primary" if metric_name == "score" else "metric",
                    "metric_name": metric_name,
                    "value": value,
                    "unit": "indicator" if metric_name in {"hard_gate_pass", "valid"} else "ratio",
                    "reportable": row["status"] == "completed",
                }
            )

    tables = {
        "profiles": (
            [
                "campaign_id",
                "cell_key",
                "run_plan_id",
                "run_plan_sha256",
                "model_id",
                "profile_id",
                "profile_sha256",
                "case_slug",
                "inference_seed",
                "provider",
                "requested_model",
                "canonical_model",
                "quantization",
                "access_class",
                "license_id",
                "harness",
                "reasoning_effort",
                "temperature",
                "max_output_tokens",
                "timeout_seconds",
                "sdk_retries",
                "pricing",
                "source_kind",
                "source_sha256",
            ],
            profile_rows,
        ),
        "model_features": (
            [
                "campaign_id",
                "cell_key",
                "model_id",
                "profile_id",
                "feature_name",
                "feature_value",
                "evidence_class",
                "source_kind",
                "source_sha256",
                "reportable",
            ],
            feature_rows,
        ),
        "benchmark_results": (
            [
                "campaign_id",
                "cell_key",
                "model_id",
                "case_slug",
                "inference_seed",
                "receipt_sha256",
                "inclusion_status",
                "metric_role",
                "metric_name",
                "value",
                "unit",
                "reportable",
            ],
            result_rows,
        ),
    }
    manifest_tables: dict[str, Any] = {}
    for name, (fields, table_rows) in tables.items():
        payload = _csv_payload(fields, table_rows)
        filename = f"{name}.csv"
        _publish_bytes(analysis_root / filename, payload)
        manifest_tables[name] = {
            "path": filename,
            "row_count": len(table_rows),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    manifest = _sealed(
        {
            "schema_version": "aeread.commercial_state_fact_manifest/0.1",
            "campaign_id": contract["campaign_id"],
            "contract_sha256": _sha256(contract),
            "source_truth": ["RunPlan", "EvaluationReceipt"],
            "projection_semantics": "deterministic campaign projection; sealed receipts remain authoritative",
            "tables": manifest_tables,
        }
    )
    manifest_path = analysis_root / "fact_manifest.json"
    _publish_bytes(manifest_path, canonical_json_bytes(manifest) + b"\n")
    return {
        "path": str(manifest_path.relative_to(stage_root)),
        "sha256": _file_sha256(manifest_path),
        "artifact_sha256": manifest["artifact_sha256"],
        "tables": manifest_tables,
    }


async def run_live_stage(
    contract: Mapping[str, Any],
    *,
    stage: str,
    output_root: Path,
    attempt_index: int = 1,
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
) -> dict[str, Any]:
    if stage not in {"full_trajectory", "variance_pilot"}:
        raise ValueError("live stage must be full_trajectory or variance_pilot")
    stage_contract = contract[stage]
    stage_root = _live_stage_root(output_root, stage, attempt_index)
    cell_specs = list(_stage_cells(contract, stage))
    design = design_contract_artifact(contract)
    expected_plans = {
        row["cell_key"]: row for row in design["plans"][stage]
    }
    provider = provider_factory()
    rows: list[dict[str, Any]] = []
    parallelism = int(contract["controls"]["parallelism"])
    max_cell_cost = float(contract["controls"]["max_cost_usd_per_cell"])
    ceiling = float(stage_contract["cost_ceiling_usd"])
    for start in range(0, len(cell_specs), parallelism):
        batch = cell_specs[start : start + parallelism]
        spent = sum(float(row["usage"]["cost_usd"]) for row in rows)
        pending = sum(
            not (stage_root / "cells" / cell["cell_key"] / "result.json").exists()
            for cell in batch
        )
        if spent + pending * max_cell_cost > ceiling + 1e-12:
            raise RuntimeError(f"{stage} cost ceiling blocks the next atomic batch")
        batch_rows = await asyncio.gather(
            *(
                _execute_live_cell(
                    contract=contract,
                    stage_root=stage_root,
                    output_root=output_root,
                    cell_spec=cell,
                    expected_plan=expected_plans[cell["cell_key"]],
                    provider=provider,
                    attempt_index=attempt_index,
                )
                for cell in batch
            )
        )
        rows.extend(batch_rows)
        if sum(float(row["usage"]["cost_usd"]) for row in rows) > ceiling + 1e-12:
            raise RuntimeError(f"{stage} exceeded its cost ceiling")

    by_key = {row["cell_key"]: row for row in rows}
    if set(by_key) != {row["cell_key"] for row in cell_specs}:
        raise RuntimeError(f"{stage} did not record every planned cell")
    rows = [by_key[cell["cell_key"]] for cell in cell_specs]
    completed = [row for row in rows if row["status"] == "completed"]
    missing = [row for row in rows if row["status"] != "completed"]
    failure_fraction = len(missing) / len(rows)
    all_receipts_replayed = all(row["replay_verified"] for row in rows)
    all_completed_routes_verified = all(row["route_verified"] for row in completed)
    status = "passed"
    blockers: list[str] = []
    if not all_receipts_replayed:
        blockers.append("receipt_replay_failed")
    if not all_completed_routes_verified:
        blockers.append("route_verification_failed")
    if failure_fraction > float(stage_contract["maximum_operational_failure_fraction"]):
        blockers.append("operational_missingness_above_ceiling")
    if stage == "full_trajectory" and missing:
        blockers.append("full_trajectory_requires_every_condition_to_complete")
    if blockers:
        status = "failed"

    fact_manifest = _export_fact_tables(contract=contract, rows=rows, stage_root=stage_root)
    artifact = _sealed(
        {
            "schema_version": "aeread.commercial_state_campaign_results/0.1",
            "campaign_id": contract["campaign_id"],
            "stage": stage,
            "attempt_index": attempt_index,
            "status": status,
            "claim_status": "integration_only" if stage == "full_trajectory" else "exploratory_variance_pilot",
            "winner_claim_allowed": False,
            "independent_cluster_count": 1,
            "inferential_model_ranking_allowed": False,
            "planned_cells": len(rows),
            "completed_cells": len(completed),
            "measurement_invalid_cells": sum(row["status"] == "measurement_invalid" for row in rows),
            "operational_failure_cells": sum(row["status"] == "operational_failure" for row in rows),
            "failure_fraction": failure_fraction,
            "maximum_operational_failure_fraction": stage_contract["maximum_operational_failure_fraction"],
            "all_receipts_replayed": all_receipts_replayed,
            "all_completed_routes_verified": all_completed_routes_verified,
            "provider_calls_started": sum(int(row["usage"]["provider_calls_started"]) for row in rows),
            "provider_calls_succeeded": sum(int(row["usage"]["provider_calls_succeeded"]) for row in rows),
            "input_tokens": sum(int(row["usage"]["input_tokens"]) for row in rows),
            "cached_input_tokens": sum(int(row["usage"]["cached_input_tokens"]) for row in rows),
            "output_tokens": sum(int(row["usage"]["output_tokens"]) for row in rows),
            "total_cost_usd": sum(float(row["usage"]["cost_usd"]) for row in rows),
            "cost_ceiling_usd": ceiling,
            "model_summaries": _model_summaries(contract, rows),
            "pairwise_contrasts": _pairwise_contrasts(contract, rows) if stage == "variance_pilot" else [],
            "fact_manifest": fact_manifest,
            "blockers": blockers,
            "rows": rows,
        }
    )
    _write_json(stage_root / "summary.json", artifact)
    if status != "passed":
        raise RuntimeError(f"{stage} failed: {blockers}")
    return artifact


def _load_history(path: Path) -> tuple[CampaignHistoryRecord, ...]:
    if not path.exists():
        return ()
    value = _read_sealed(path)
    if value.get("schema_version") != "aeread.campaign_gate_history/0.2":
        raise ValueError("campaign history schema is unsupported")
    records = value.get("records")
    if not isinstance(records, list):
        raise ValueError("campaign gate history must contain records")
    return tuple(campaign_history_record_from_dict(row) for row in records)


def _write_history(path: Path, records: Sequence[CampaignHistoryRecord]) -> None:
    _write_json(
        path,
        _sealed(
            {
                "schema_version": "aeread.campaign_gate_history/0.2",
                "records": [campaign_history_record_to_dict(record) for record in records],
            }
        ),
    )


def _latest_status(
    records: Sequence[CampaignHistoryRecord], campaign_id: str, gate_id: str, output_root: Path
) -> str | None:
    active = {
        record.gate_id: record
        for record in campaign_active_gate_records(
            campaign_id, records, evidence_root=output_root
        )
    }
    return None if gate_id not in active else active[gate_id].status


def _expected_gate_coverage(contract: Mapping[str, Any], gate_id: str) -> tuple[str, ...]:
    if gate_id == "design_contract":
        return tuple(
            f"{stage}.{row['cell_key']}"
            for stage in ("full_trajectory", "variance_pilot")
            for row in _stage_cells(contract, stage)
        )
    if gate_id == "provider_free_validation":
        return tuple(
            [f"case.{slug}.strong" for slug in contract["case_panel"]["case_slugs"]]
            + ["boundary.valid_but_poor", "boundary.hard_gate_failed", "boundary.malformed"]
        )
    if gate_id == "profile_admission":
        return tuple(contract["models"])
    if gate_id in {"full_trajectory", "variance_pilot"}:
        return tuple(row["cell_key"] for row in _stage_cells(contract, gate_id))
    return (gate_id,)


def _observed_gate_coverage(artifact: Mapping[str, Any] | None, gate_id: str) -> tuple[str, ...]:
    if artifact is None:
        return ()
    if gate_id == "design_contract":
        plans = artifact.get("plans", {})
        return tuple(
            f"{stage}.{row['cell_key']}"
            for stage in ("full_trajectory", "variance_pilot")
            for row in plans.get(stage, ())
        )
    if gate_id == "provider_free_validation":
        return tuple(row["check_id"] for row in artifact.get("checks", ()))
    if gate_id == "profile_admission":
        return tuple(
            row["model_id"] for row in artifact.get("results", ()) if row.get("status") == "passed"
        )
    if gate_id in {"full_trajectory", "variance_pilot"}:
        return tuple(row["cell_key"] for row in artifact.get("rows", ()))
    return (gate_id,) if artifact.get("status") == "passed" else ()


def _gate_evidence(
    *,
    contract: Mapping[str, Any],
    gate_id: str,
    status: str,
    path: Path,
    output_root: Path,
    artifact: Mapping[str, Any] | None,
) -> QCEvidenceRef:
    return QCEvidenceRef(
        artifact_type=campaign_gate_artifact_type(gate_id, status),
        path=str(path.relative_to(output_root)),
        sha256=_file_sha256(path),
        family_id=FAMILY_ID,
        family_version=FAMILY_VERSION,
        profile_id=contract["campaign_id"],
        coverage=(
            QCCoverage(
                coverage_id=gate_id,
                required_ids=_expected_gate_coverage(contract, gate_id),
                observed_ids=_observed_gate_coverage(artifact, gate_id),
            ),
        ),
    )


def _record_gate(
    *,
    records: Sequence[CampaignHistoryRecord],
    contract: Mapping[str, Any],
    gate_id: str,
    status: str,
    evidence: QCEvidenceRef,
    output_root: Path,
    failure_reasons: Sequence[str] = (),
) -> tuple[CampaignHistoryRecord, ...]:
    decision = campaign_promotion_decision(
        contract["campaign_id"], gate_id, records, evidence_root=output_root
    )
    if not decision.eligible:
        raise RuntimeError(f"campaign promotion blocked: {decision.blockers}")
    return append_campaign_gate(
        records,
        CampaignGateRecord(
            campaign_id=contract["campaign_id"],
            family_id=FAMILY_ID,
            family_version=FAMILY_VERSION,
            profile_id=contract["campaign_id"],
            gate_id=gate_id,
            attempt_index=decision.next_attempt_index,
            status=status,
            evidence_refs=(evidence,),
            failure_reasons=tuple(failure_reasons),
        ),
        evidence_root=output_root,
    )


def _invalidate_history(
    *,
    records: Sequence[CampaignHistoryRecord],
    contract: Mapping[str, Any],
    output_root: Path,
    from_gate_id: str,
    changed_controls: Sequence[str],
    reason: str,
) -> tuple[CampaignHistoryRecord, ...]:
    index = sum(isinstance(record, CampaignInvalidationRecord) for record in records) + 1
    invalidation_id = f"invalidation_{index}"
    path = output_root / "invalidations" / invalidation_id / "summary.json"
    artifact = _sealed(
        {
            "schema_version": "aeread.campaign_invalidation/0.1",
            "campaign_id": contract["campaign_id"],
            "invalidation_index": index,
            "from_gate_id": from_gate_id,
            "changed_controls": list(changed_controls),
            "reason": reason,
        }
    )
    _write_json(path, artifact)
    evidence = QCEvidenceRef(
        artifact_type="campaign_invalidation",
        path=str(path.relative_to(output_root)),
        sha256=_file_sha256(path),
        family_id=FAMILY_ID,
        family_version=FAMILY_VERSION,
        profile_id=contract["campaign_id"],
        coverage=(
            QCCoverage(
                coverage_id="invalidation",
                required_ids=(invalidation_id,),
                observed_ids=(invalidation_id,),
            ),
        ),
    )
    return append_campaign_invalidation(
        records,
        CampaignInvalidationRecord(
            campaign_id=contract["campaign_id"],
            family_id=FAMILY_ID,
            family_version=FAMILY_VERSION,
            profile_id=contract["campaign_id"],
            invalidation_index=index,
            from_gate_id=from_gate_id,
            changed_controls=tuple(changed_controls),
            reason=reason,
            evidence_refs=(evidence,),
        ),
        evidence_root=output_root,
    )


def _verify_active_design_binding(
    records: Sequence[CampaignHistoryRecord], contract: Mapping[str, Any], output_root: Path
) -> None:
    active = campaign_active_gate_records(
        contract["campaign_id"], records, evidence_root=output_root
    )
    design = next(
        (record for record in active if record.gate_id == "design_contract" and record.status == "passed"),
        None,
    )
    if design is None:
        return
    artifact = _read_sealed(output_root / design.evidence_refs[0].path)
    if artifact.get("contract_sha256") != _sha256(contract):
        raise ValueError("campaign contract changed after design gate; use a new campaign identity")
    if artifact.get("campaign_implementation_sha256") != _campaign_implementation_sha256():
        raise ValueError("campaign implementation changed after design gate; invalidate from design_contract")
    current = design_contract_artifact(contract)
    if artifact.get("artifact_sha256") != current.get("artifact_sha256"):
        raise ValueError("resolved campaign plans changed after design gate; invalidate from design_contract")


async def execute_campaign(
    *,
    contract_path: Path = DEFAULT_CONTRACT_PATH,
    output_root: Path,
    through: str,
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
    endpoint_loader: Callable[[str], Mapping[str, Any]] = _load_endpoint_catalog,
    invalidate_from: str | None = None,
    changed_controls: Sequence[str] = (),
    invalidation_reason: str | None = None,
) -> dict[str, Any]:
    if through not in STAGES:
        raise ValueError(f"through must be one of {STAGES}")
    contract = load_contract(contract_path)
    output_root.mkdir(parents=True, exist_ok=True)
    history_path = output_root / "gate_history.json"
    records = _load_history(history_path)
    invalidation = None
    if invalidate_from is not None:
        if invalidate_from not in STAGES:
            raise ValueError(f"invalidate_from must be one of {STAGES}")
        if not changed_controls or invalidation_reason is None or not invalidation_reason.strip():
            raise ValueError("invalidation requires changed controls and a reason")
        records = _invalidate_history(
            records=records,
            contract=contract,
            output_root=output_root,
            from_gate_id=invalidate_from,
            changed_controls=changed_controls,
            reason=invalidation_reason,
        )
        _write_history(history_path, records)
        invalidation = {
            "from_gate_id": invalidate_from,
            "changed_controls": list(changed_controls),
            "reason": invalidation_reason,
        }
    elif changed_controls or invalidation_reason is not None:
        raise ValueError("invalidate_from is required with invalidation details")
    else:
        _verify_active_design_binding(records, contract, output_root)

    summaries: dict[str, Any] = {}
    target_index = STAGES.index(through)
    for gate_id in STAGES[: target_index + 1]:
        if _latest_status(records, contract["campaign_id"], gate_id, output_root) == "passed":
            summaries[gate_id] = {"status": "already_passed"}
            continue
        decision = campaign_promotion_decision(
            contract["campaign_id"], gate_id, records, evidence_root=output_root
        )
        attempt_index = decision.next_attempt_index
        stage_root = _live_stage_root(output_root, gate_id, attempt_index)
        artifact: Mapping[str, Any] | None = None
        try:
            if gate_id == "design_contract":
                artifact = design_contract_artifact(contract)
                path = stage_root / "summary.json"
                _write_json(path, artifact)
            elif gate_id == "provider_free_validation":
                artifact = await run_provider_free(
                    contract, output_root=output_root, attempt_index=attempt_index
                )
                path = stage_root / "summary.json"
            elif gate_id == "profile_admission":
                artifact = await run_profile_admission(
                    contract, endpoint_loader=endpoint_loader
                )
                path = stage_root / "summary.json"
                _write_json(path, artifact)
            else:
                artifact = await run_live_stage(
                    contract,
                    stage=gate_id,
                    output_root=output_root,
                    attempt_index=attempt_index,
                    provider_factory=provider_factory,
                )
                path = stage_root / "summary.json"
            records = _record_gate(
                records=records,
                contract=contract,
                gate_id=gate_id,
                status="passed",
                evidence=_gate_evidence(
                    contract=contract,
                    gate_id=gate_id,
                    status="passed",
                    path=path,
                    output_root=output_root,
                    artifact=artifact,
                ),
                output_root=output_root,
            )
            _write_history(history_path, records)
            summaries[gate_id] = {
                "status": "passed",
                "artifact_sha256": artifact["artifact_sha256"],
            }
        except Exception as error:
            failure_path = stage_root / "failure.json"
            failure = _sealed(
                {
                    "schema_version": "aeread.commercial_state_campaign_failure/0.1",
                    "campaign_id": contract["campaign_id"],
                    "gate_id": gate_id,
                    "attempt_index": attempt_index,
                    "status": "failed",
                    "failure_type": type(error).__name__,
                    "failure_condition": getattr(error, "condition", "stage_failure"),
                    "message": str(error),
                }
            )
            _write_json(failure_path, failure)
            records = _record_gate(
                records=records,
                contract=contract,
                gate_id=gate_id,
                status="failed",
                evidence=_gate_evidence(
                    contract=contract,
                    gate_id=gate_id,
                    status="failed",
                    path=failure_path,
                    output_root=output_root,
                    artifact=None,
                ),
                output_root=output_root,
                failure_reasons=(str(error) or type(error).__name__,),
            )
            _write_history(history_path, records)
            summaries[gate_id] = {
                "status": "failed",
                "failure_type": type(error).__name__,
                "message": str(error),
            }
            break
    return {
        "campaign_id": contract["campaign_id"],
        "through": through,
        "invalidation": invalidation,
        "gate_summaries": summaries,
        "gate_history": str(history_path),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT_PATH)
    parser.add_argument(
        "--run-root",
        "--output",
        dest="run_root",
        type=Path,
        required=True,
        help="ignored local campaign directory (legacy alias: --output)",
    )
    parser.add_argument("--through", choices=STAGES, default="full_trajectory")
    parser.add_argument("--invalidate-from", choices=STAGES)
    parser.add_argument("--changed-control", action="append", default=[])
    parser.add_argument("--invalidation-reason")
    arguments = parser.parse_args(argv)
    result = asyncio.run(
        execute_campaign(
            contract_path=arguments.contract,
            output_root=arguments.run_root,
            through=arguments.through,
            invalidate_from=arguments.invalidate_from,
            changed_controls=arguments.changed_control,
            invalidation_reason=arguments.invalidation_reason,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if any(
        row.get("status") == "failed" for row in result["gate_summaries"].values()
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CAMPAIGN_EXPECTED_CONTROLS",
    "CAMPAIGN_MODEL_ROUTE_PINS",
    "CAMPAIGN_ID",
    "CONTRACT_SCHEMA_VERSION",
    "DEFAULT_CONTRACT_PATH",
    "MODEL_ROUTE_PINS",
    "STAGES",
    "V2_CAMPAIGN_ID",
    "V2_CONTRACT_PATH",
    "V2_MODEL_ROUTE_PINS",
    "V3_CAMPAIGN_ID",
    "V3_CONTRACT_PATH",
    "V3_EXPECTED_CONTROLS",
    "V3_MODEL_ROUTE_PINS",
    "V4_CAMPAIGN_ID",
    "V4_CONTRACT_PATH",
    "V4_EXPECTED_CONTROLS",
    "V4_MODEL_ROUTE_PINS",
    "design_contract_artifact",
    "execute_campaign",
    "load_contract",
    "main",
    "run_live_stage",
    "run_profile_admission",
    "run_provider_free",
]
