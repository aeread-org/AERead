"""Model-to-model Housing sensitivity integration campaign."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
import os
import statistics
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.task.execution import (
    EvidenceIntegrityError,
    EvidenceStore,
    OpenRouterChatClient,
    execute_plan_cell,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.receipts import verify_evaluation_receipt
from aeread.shared_runner.task.scheduler import SchedulerContractError

from .runner import (
    DEEPINFRA_GLM_53_FLASH_ROUTE,
    DEEPINFRA_HOUSING_ROUTE,
    GLM_53_FLASH_MODEL,
    GLM_53_FLASH_REVISION,
    HOUSING_COMMIT_OUTPUT_SCHEMA_V2,
    HOUSING_CONTACT_OUTPUT_SCHEMA_V2,
    HOUSING_RESPOND_OUTPUT_SCHEMA_V2,
    OpenRouterRoutePin,
    build_housing_smoke,
    finalize_housing_execution,
    finalize_housing_failure,
    replay_housing_receipt,
)
from .population_campaign import (
    DEEPSEEK_MODEL,
    DEEPSEEK_REVISION,
    _failure_usage,
    _role_metrics,
)
from .qc import audit_bid_world
from .provider_cooldown import CooldownProviderClient
from .provider_pacing import PacedProviderClient


CONTRACT_SCHEMA_VERSION = "aeread.housing_model_sensitivity/0.1"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ROOT_FIELDS = {
    "schema_version",
    "campaign_id",
    "claim_status",
    "question",
    "independent_cluster",
    "source_case_selection",
    "controls",
    "models",
    "conditions",
    "profile_admission_reference",
    "execution",
    "analysis",
    "missingness",
    "stopping_rule",
}
_HISTORICAL_IMPLEMENTATION_DIGESTS = {
    "housing_model_sensitivity_openrouter_alt_v8": {
        "housing": "4182057475816840253a8421fc461c09fa6bbb8ea0659e742f6d98ebc2a74a33",
        "bridge": "2cc022fc87fd49e5ed4d38391bd5af30de90be41eaced2086a81b75e51119cc5",
        "combined": "249101944729a189ff4b7c1e5205ee8964c2f86638e6dbd6331dcd07fcf61f6d",
        "execution": "d2c12667a55dddddaaf76ca39e396b998d4a57b08e0bd073a656372f6deb1dc5",
        "harness": "c7dd0cd5a2eb1f557df24a1f3e7bd731938b6938523799ee02a4273229c25590",
    },
    "housing_model_sensitivity_openrouter_deepinfra_v11": {
        "housing": "4182057475816840253a8421fc461c09fa6bbb8ea0659e742f6d98ebc2a74a33",
        "bridge": "5cc23b0340eb39a6d49d8885169c32b5a975b1c80ba858d932e32d179c6b1fae",
        "combined": "2a7c062960c060f78b85258f0b86768fd3133fb37def9ccd5e534e3a82ad08ab",
        "execution": "7b963ccc739e007504c4df5f6abce1748c295b20e2b6887599b88ee0108f7f7f",
        "harness": "063a26de9bd05b7ac0ac400a84e933beffec413ef4eb1ca50794f7e790fc4275",
    },
    "housing_model_sensitivity_openrouter_deepinfra_v12": {
        "housing": "4182057475816840253a8421fc461c09fa6bbb8ea0659e742f6d98ebc2a74a33",
        "bridge": "5cc23b0340eb39a6d49d8885169c32b5a975b1c80ba858d932e32d179c6b1fae",
        "combined": "2a7c062960c060f78b85258f0b86768fd3133fb37def9ccd5e534e3a82ad08ab",
        "execution": "7b963ccc739e007504c4df5f6abce1748c295b20e2b6887599b88ee0108f7f7f",
        "harness": "063a26de9bd05b7ac0ac400a84e933beffec413ef4eb1ca50794f7e790fc4275",
    },
}


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sealed(value: Mapping[str, Any]) -> dict[str, Any]:
    core = {key: item for key, item in value.items() if key != "artifact_sha256"}
    return {**core, "artifact_sha256": _sha256(core)}


def _read_sealed(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or canonical_json_bytes(
        value
    ) != canonical_json_bytes(_sealed(value)):
        raise ValueError(f"artifact digest mismatch: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    if path.exists():
        if path.is_file() and path.read_bytes() == payload:
            return
        raise ValueError(f"refusing to overwrite different campaign artifact: {path}")
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _source_path(relative: str) -> Path:
    path = (_REPO_ROOT / relative).resolve()
    try:
        path.relative_to(_REPO_ROOT)
    except ValueError as error:
        raise ValueError("source artifact path escapes the repository") from error
    return path


def _selected_case_artifact(contract: Mapping[str, Any]) -> dict[str, Any]:
    source = contract["source_case_selection"]
    selected_path = _source_path(source["path"])
    manifest_path = _source_path(source["fact_manifest_path"])
    if _file_sha256(selected_path) != source["file_sha256"]:
        raise ValueError("selected-case file digest drifted")
    if _file_sha256(manifest_path) != source["fact_manifest_file_sha256"]:
        raise ValueError("case-sweep fact manifest digest drifted")
    selected = _read_sealed(selected_path)
    if selected.get("artifact_sha256") != source["artifact_sha256"]:
        raise ValueError("selected-case artifact identity drifted")
    if selected.get("confirmatory_holdout_status") != "sealed_not_executed":
        raise ValueError("source case holdout is no longer sealed")
    if selected.get("selection_uses") != "development_provider_free_facts_only":
        raise ValueError("selected cases were not derived from provider-free facts")
    return selected


def _validate_models(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {
        "glm_53_flash",
        "deepseek_v4_flash",
    }:
        raise ValueError("model sensitivity requires exactly GLM and DeepSeek")
    expected = {
        "glm_53_flash": (GLM_53_FLASH_MODEL, GLM_53_FLASH_REVISION),
        "deepseek_v4_flash": (DEEPSEEK_MODEL, DEEPSEEK_REVISION),
    }
    for model_id, (requested, canonical) in expected.items():
        model = value[model_id]
        if set(model) != {
            "requested_model",
            "canonical_model",
            "provider",
            "quantization",
            "tenant_profile_id",
            "landlord_profile_id",
        }:
            raise ValueError(f"model fields drifted for {model_id}")
        if (model["requested_model"], model["canonical_model"]) != (
            requested,
            canonical,
        ):
            raise ValueError(f"model route drifted for {model_id}")
        if (model["provider"], model["quantization"]) != ("DeepInfra", "fp8"):
            raise ValueError(f"provider route drifted for {model_id}")


def load_contract(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_bytes())
    if not isinstance(value, dict) or set(value) != _ROOT_FIELDS:
        raise ValueError(
            "model-sensitivity contract fields are incomplete or unexpected"
        )
    if value["schema_version"] != CONTRACT_SCHEMA_VERSION:
        raise ValueError("unsupported Housing model-sensitivity contract schema")
    if value["campaign_id"] != "housing_model_sensitivity_v1":
        raise ValueError("this driver accepts only housing_model_sensitivity_v1")
    if value["claim_status"] != "development_integration_only":
        raise ValueError("single-world sensitivity cannot support a performance claim")
    if value["independent_cluster"] != "world_seed":
        raise ValueError("world_seed must remain the independent cluster")

    source = value["source_case_selection"]
    if not isinstance(source, dict) or set(source) != {
        "path",
        "artifact_sha256",
        "file_sha256",
        "fact_manifest_path",
        "fact_manifest_file_sha256",
    }:
        raise ValueError("source case selection is incomplete or unexpected")
    for field in source:
        item = source[field]
        if not isinstance(item, str) or not item:
            raise ValueError(f"source_case_selection.{field} must be non-empty")
    selected = _selected_case_artifact(value)
    configs = selected.get("selected_configs")
    if not isinstance(configs, list) or [
        config.get("config_id") for config in configs if isinstance(config, Mapping)
    ] != ["mild_cw085_r2", "moderate_cw085_r2", "severe_cw030_r2"]:
        raise ValueError("selected development case panel drifted")

    controls = value["controls"]
    if controls != {
        "harness": "minimal_chat/1.0",
        "tools": "disabled",
        "memory": "disabled",
        "reasoning_effort": "low",
        "temperature": 0.0,
        "top_p": 1.0,
        "max_output_tokens": 4096,
        "timeout_seconds": 120.0,
        "sdk_retries": 0,
        "max_action_attempts": 4,
        "tenant_max_logical_actions": 48,
        "landlord_max_logical_actions": 16,
        "retryable_conditions": ["length", "rate_limit", "provider_5xx"],
        "tenant_inference_seed_base": 87001,
        "landlord_inference_seed_base": 97001,
        "condition_order": "rotate_by_case_configuration",
    }:
        raise ValueError("fixed model-sensitivity controls drifted")
    _validate_models(value["models"])

    conditions = value["conditions"]
    if not isinstance(conditions, list) or len(conditions) != 4:
        raise ValueError("model-to-model matrix must contain four conditions")
    identities = {
        (
            condition.get("subject"),
            condition.get("opponent"),
            condition.get("evaluation_kind"),
        )
        for condition in conditions
        if isinstance(condition, Mapping)
    }
    if identities != {
        ("glm_53_flash", "glm_53_flash", "self_play"),
        ("glm_53_flash", "deepseek_v4_flash", "cross_play"),
        ("deepseek_v4_flash", "glm_53_flash", "cross_play"),
        ("deepseek_v4_flash", "deepseek_v4_flash", "self_play"),
    }:
        raise ValueError("model-to-model condition matrix drifted")
    condition_ids = [condition.get("condition_id") for condition in conditions]
    if any(not isinstance(item, str) or not item for item in condition_ids) or len(
        set(condition_ids)
    ) != len(condition_ids):
        raise ValueError("condition IDs must be unique non-empty strings")

    admission = value["profile_admission_reference"]
    if not isinstance(admission, dict) or set(admission) != {
        "campaign_id",
        "artifact_sha256",
        "hidden_retry_count",
        "profile_sha256s",
    }:
        raise ValueError("profile admission reference is invalid")
    if (
        admission["campaign_id"] != "housing_population_crossplay_v0"
        or admission["hidden_retry_count"] != 0
        or not isinstance(admission["artifact_sha256"], str)
        or len(admission["artifact_sha256"]) != 64
    ):
        raise ValueError("profile admission identity drifted")
    expected_profile_ids = {
        model[role]
        for model in value["models"].values()
        for role in ("tenant_profile_id", "landlord_profile_id")
    }
    if set(admission["profile_sha256s"]) != expected_profile_ids or any(
        not isinstance(digest, str) or len(digest) != 64
        for digest in admission["profile_sha256s"].values()
    ):
        raise ValueError("admitted profile identities are incomplete")

    execution = value["execution"]
    if not isinstance(execution, dict) or set(execution) != {
        "world_seeds",
        "replicates",
        "attempt_limit",
        "cost_ceiling_usd",
        "per_trajectory_cost_reserve_usd",
        "winner_claim_allowed",
        "completeness_policy",
    }:
        raise ValueError("execution contract is invalid")
    if execution != {
        "world_seeds": [1971418798],
        "replicates": 1,
        "attempt_limit": 1,
        "cost_ceiling_usd": 0.05,
        "per_trajectory_cost_reserve_usd": 0.02,
        "winner_claim_allowed": False,
        "completeness_policy": "retain_typed_missingness_without_selective_retry",
    }:
        raise ValueError("single-attempt execution controls drifted")
    if value["analysis"] != {
        "primary_view": "condition_by_case_configuration_within_case_score",
        "aggregation": "none_single_world_integration_slice",
        "uncertainty": "not_estimable_from_one_world_cluster",
        "ranking_allowed": False,
    }:
        raise ValueError("development-only analysis contract drifted")
    if value["missingness"] != "typed_operational_missingness_reported_separately":
        raise ValueError("missingness policy drifted")
    if value["stopping_rule"] != (
        "stop_before_next_trajectory_when_remaining_campaign_budget_is_below_the_"
        "declared_reserve; stop_immediately_on_route_drift_or_replay_failure"
    ):
        raise ValueError("campaign stopping rule drifted")
    return value


def selected_configs(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    selected = _selected_case_artifact(contract)
    configs = [
        {
            key: config[key]
            for key in (
                "config_id",
                "difficulty_stratum",
                "tenants",
                "listings",
                "rounds",
                "common_weight",
            )
        }
        for config in selected["selected_configs"]
    ]
    requested_ids = contract["execution"].get("config_ids")
    if requested_ids is None:
        return configs
    filtered = [config for config in configs if config["config_id"] in requested_ids]
    if {config["config_id"] for config in filtered} != set(requested_ids):
        raise ValueError("execution references an unselected case configuration")
    return filtered


def _route_for(
    model_id: str,
    routes: Mapping[str, OpenRouterRoutePin] | None = None,
) -> OpenRouterRoutePin:
    if routes is not None:
        try:
            return routes[model_id]
        except KeyError as error:
            raise ValueError(f"unknown model ID: {model_id}") from error
    if model_id == "glm_53_flash":
        return DEEPINFRA_GLM_53_FLASH_ROUTE
    if model_id == "deepseek_v4_flash":
        return DEEPINFRA_HOUSING_ROUTE
    raise ValueError(f"unknown model ID: {model_id}")


def build_setups(
    contract: Mapping[str, Any],
    *,
    routes: Mapping[str, OpenRouterRoutePin] | None = None,
) -> dict[tuple[str, str], Any]:
    setups: dict[tuple[str, str], Any] = {}
    controls = contract["controls"]
    historical_implementation_digests = _HISTORICAL_IMPLEMENTATION_DIGESTS.get(
        str(contract["campaign_id"])
    )
    use_action_schemas_v2 = (
        controls.get("action_schema_version") == "housing_actions/2.0"
    )
    tenant_harness_config = (
        {
            "output_schema_by_action_schema": {
                "housing_contact_v1": HOUSING_CONTACT_OUTPUT_SCHEMA_V2,
                "housing_commit_v1": HOUSING_COMMIT_OUTPUT_SCHEMA_V2,
            }
        }
        if use_action_schemas_v2
        else None
    )
    landlord_harness_config = (
        {
            "output_schema_by_action_schema": {
                "housing_respond_v1": HOUSING_RESPOND_OUTPUT_SCHEMA_V2,
            }
        }
        if use_action_schemas_v2
        else None
    )
    live_profile_controls = (
        {
            "max_output_tokens_override": controls["max_output_tokens"],
            "timeout_seconds_override": controls["timeout_seconds"],
            "max_action_attempts_override": controls["max_action_attempts"],
            "retryable_conditions_override": controls["retryable_conditions"],
        }
        if controls.get("wire_live_profile_controls") is True
        else {}
    )
    for config in selected_configs(contract):
        for condition in contract["conditions"]:
            subject = contract["models"][condition["subject"]]
            opponent = contract["models"][condition["opponent"]]
            setups[(config["config_id"], condition["condition_id"])] = (
                build_housing_smoke(
                    tenant_provider="openrouter",
                    tenant_model=subject["requested_model"],
                    tenant_revision=subject["canonical_model"],
                    landlord_provider="openrouter",
                    landlord_model=opponent["requested_model"],
                    landlord_revision=opponent["canonical_model"],
                    world_seeds=tuple(contract["execution"]["world_seeds"]),
                    replicates=contract["execution"]["replicates"],
                    reasoning_condition_id=controls.get(
                        "reasoning_condition_id", "population_crossplay_low_v0"
                    ),
                    reasoning_effort=controls["reasoning_effort"],
                    inference_seed_base=controls["tenant_inference_seed_base"],
                    landlord_inference_seed_base=controls[
                        "landlord_inference_seed_base"
                    ],
                    num_tenants=config["tenants"],
                    num_listings=config["listings"],
                    rounds=config["rounds"],
                    common_weight=config["common_weight"],
                    openrouter_route=_route_for(condition["subject"], routes),
                    landlord_openrouter_route=_route_for(condition["opponent"], routes),
                    tenant_profile_id_override=subject["tenant_profile_id"],
                    tenant_max_logical_actions_override=controls[
                        "tenant_max_logical_actions"
                    ],
                    landlord_profile_id_override=opponent["landlord_profile_id"],
                    landlord_max_logical_actions_override=controls[
                        "landlord_max_logical_actions"
                    ],
                    tenant_harness_config=tenant_harness_config,
                    landlord_harness_config=landlord_harness_config,
                    implementation_digest_overrides=(
                        historical_implementation_digests
                    ),
                    evaluation_kind=condition["evaluation_kind"],
                    **live_profile_controls,
                )
            )
    return setups


def design_artifact(
    contract: Mapping[str, Any],
    *,
    routes: Mapping[str, OpenRouterRoutePin] | None = None,
) -> dict[str, Any]:
    setups = build_setups(contract, routes=routes)
    admission = contract.get("profile_admission_reference") or contract.get(
        "profile_admission"
    )
    if not isinstance(admission, Mapping):
        raise ValueError("profile admission identities are missing")
    expected_profiles = admission["profile_sha256s"]
    plans: list[dict[str, Any]] = []
    multi_cell = (
        len(contract["execution"]["world_seeds"])
        * contract["execution"]["replicates"]
        > 1
    )
    for (config_id, condition_id), setup in sorted(setups.items()):
        config = next(
            item
            for item in selected_configs(contract)
            if item["config_id"] == config_id
        )
        profile_digests = {
            profile.profile_id: _sha256(profile)
            for profile in setup.plan.agent_profiles
        }
        if any(
            expected_profiles[profile_id] != digest
            for profile_id, digest in profile_digests.items()
        ):
            raise ValueError(f"profile identity drifted for {config_id}/{condition_id}")
        if any(
            (profile.harness.id, profile.harness.version) != ("minimal_chat", "1.0")
            for profile in setup.plan.agent_profiles
        ):
            raise ValueError("fixed harness drifted")
        cases_by_id = {case.case_id: case for case in setup.plan.cases}
        for cell in setup.plan.cells:
            case = cases_by_id[cell.case_id]
            expected_payload = {
                "world_kind": "bid",
                "world_seed": cell.world_seed,
                "num_tenants": config["tenants"],
                "num_listings": config["listings"],
                "rounds": config["rounds"],
                "common_weight": config["common_weight"],
            }
            if dict(case.payload) != expected_payload:
                raise ValueError(f"case payload drifted for {config_id}")
            plan_row = {
                "config_id": config_id,
                "condition_id": condition_id,
                "case_sha256": case.content_sha256,
                "run_plan_id": setup.plan.run_plan_id,
                "plan_sha256": setup.plan.plan_sha256,
                "profile_sha256s": profile_digests,
            }
            if multi_cell:
                plan_row.update(
                    {
                        "cell_id": cell.cell_id,
                        "world_seed": cell.world_seed,
                        "replicate_index": cell.replicate_index,
                    }
                )
            plans.append(plan_row)
    return _sealed(
        {
            "schema_version": "aeread.housing_model_sensitivity_design/0.1",
            "campaign_id": contract["campaign_id"],
            "status": "passed",
            "claim_status": contract["claim_status"],
            "contract_sha256": _sha256(contract),
            "source_case_selection_sha256": contract["source_case_selection"][
                "artifact_sha256"
            ],
            "configuration_count": len(selected_configs(contract)),
            "condition_count": len(contract["conditions"]),
            "planned_trajectories": len(plans),
            "paired_worlds": True,
            "fixed_harness": "minimal_chat/1.0",
            "complete_model_matrix": True,
            "ranking_allowed": False,
            "plans": plans,
        }
    )


def provider_free_artifact(contract: Mapping[str, Any]) -> dict[str, Any]:
    manifest_path = _source_path(
        contract["source_case_selection"]["fact_manifest_path"]
    )
    fact_manifest = json.loads(manifest_path.read_bytes())
    manifest_core = {
        key: value for key, value in fact_manifest.items() if key != "manifest_sha256"
    }
    if fact_manifest.get("manifest_sha256") != _sha256(manifest_core):
        raise ValueError("case-sweep fact manifest identity drifted")
    facts_path = _source_path(
        "evidence/housing_case_config_sweep_v1/tables/housing_case_facts.csv"
    )
    if fact_manifest.get("artifacts", {}).get("world_facts", {}).get(
        "sha256"
    ) != _file_sha256(facts_path):
        raise ValueError("case-sweep world facts digest drifted")
    with facts_path.open(newline="", encoding="utf-8") as handle:
        source_rows = list(csv.DictReader(handle))
    rows: list[dict[str, Any]] = []
    for config in selected_configs(contract):
        for world_seed in contract["execution"]["world_seeds"]:
            facts = audit_bid_world(
                tenants=config["tenants"],
                listings=config["listings"],
                rounds=config["rounds"],
                common_weight=config["common_weight"],
                world_seed=world_seed,
            )
            source = next(
                (
                    row
                    for row in source_rows
                    if row["config_id"] == config["config_id"]
                    and int(row["world_seed"]) == world_seed
                ),
                None,
            )
            if source is None or source["world_sha256"] != facts["world_sha256"]:
                raise ValueError(
                    f"source case facts drifted for {config['config_id']}"
                )
            rows.append(
                {
                    "config_id": config["config_id"],
                    "world_seed": world_seed,
                    "world_sha256": facts["world_sha256"],
                    "case_config_sha256": source["case_config_sha256"],
                    "oracle_total": facts["oracle_total"],
                    "naive_normalized": facts["naive_normalized"],
                    "oracle_gap_normalized": facts[
                        "oracle_minus_naive_normalized"
                    ],
                    "oracle_crosscheck_passed": facts[
                        "oracle_crosscheck_passed"
                    ],
                    "oracle_active_ceiling_passed": (
                        facts["oracle_total"] == facts["oracle_informed_total"]
                    ),
                }
            )
    return _sealed(
        {
            "schema_version": "aeread.housing_model_sensitivity_provider_free/0.1",
            "campaign_id": contract["campaign_id"],
            "status": "passed",
            "provider_calls": 0,
            "provider_cost_usd": 0.0,
            "confirmatory_holdout_status": "sealed_not_executed",
            "worlds": rows,
        }
    )


def _condition_by_id(contract: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        condition["condition_id"]: condition for condition in contract["conditions"]
    }


def _exception_attribute(error: BaseException, attribute: str) -> Any | None:
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        value = getattr(current, attribute, None)
        if value is not None:
            return value
        current = current.__cause__ or current.__context__
    return None


def _critical_failure(error: BaseException) -> bool:
    condition = _exception_attribute(error, "condition")
    if condition is not None:
        return condition == "provider_contract"
    if isinstance(error, (EvidenceIntegrityError, SchedulerContractError)):
        return True
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "offline replay",
            "selected provider",
            "canonical model",
            "fallback or repeated route",
            "route identity",
            "cost ceiling",
        )
    )


def _summary_views(
    rows: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    multi_cell = (
        len(contract["execution"]["world_seeds"])
        * contract["execution"]["replicates"]
        > 1
    )
    for config in selected_configs(contract):
        config_rows = [row for row in rows if row["config_id"] == config["config_id"]]
        view: dict[str, Any] = {
            "planned_trajectories": (
                len(contract["conditions"])
                * len(contract["execution"]["world_seeds"])
                * contract["execution"]["replicates"]
            ),
            "attempted_trajectories": len(config_rows),
            "completed_trajectories": sum(
                row["status"] == "completed" for row in config_rows
            ),
            "operational_failures": sum(
                row["status"] == "operational_failure" for row in config_rows
            ),
        }
        if multi_cell:
            view["conditions"] = {
                condition["condition_id"]: {
                    "planned_trajectories": (
                        len(contract["execution"]["world_seeds"])
                        * contract["execution"]["replicates"]
                    ),
                    "attempted_trajectories": len(condition_rows),
                    "completed_trajectories": sum(
                        row["status"] == "completed" for row in condition_rows
                    ),
                    "operational_failures": sum(
                        row["status"] == "operational_failure"
                        for row in condition_rows
                    ),
                    "worlds": [
                        {
                            "world_seed": row["world_seed"],
                            "replicate_index": row["replicate_index"],
                            "status": row["status"],
                            "within_case_score": row.get("within_case_score"),
                            "cost_usd": row.get("cost_usd", 0.0),
                            "failure_condition": row.get("failure_condition"),
                        }
                        for row in condition_rows
                    ],
                }
                for condition in contract["conditions"]
                for condition_rows in (
                    [
                        row
                        for row in config_rows
                        if row["condition_id"] == condition["condition_id"]
                    ],
                )
            }
        else:
            view["conditions"] = {
                row["condition_id"]: {
                    "status": row["status"],
                    "within_case_score": row.get("within_case_score"),
                    "cost_usd": row.get("cost_usd", 0.0),
                    "failure_condition": row.get("failure_condition"),
                }
                for row in config_rows
            }
        output[config["config_id"]] = view
    return output


def variance_pilot_analysis(
    rows: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]
) -> dict[str, Any]:
    """Estimate paired world-level variance without producing a ranking."""

    analysis = contract["analysis"]
    if analysis.get("aggregation") != (
        "equal_weight_configs_and_opponents_within_world"
    ):
        raise ValueError("contract does not declare the variance-pilot estimand")
    configs = selected_configs(contract)
    opponents = {condition["opponent"] for condition in contract["conditions"]}
    subjects = {condition["subject"] for condition in contract["conditions"]}
    if subjects != {"glm_53_flash", "deepseek_v4_flash"} or opponents != subjects:
        raise ValueError("variance-pilot model panel drifted")
    expected_per_subject = (
        len(configs) * len(opponents) * contract["execution"]["replicates"]
    )
    world_rows: list[dict[str, Any]] = []
    contrasts: list[float] = []
    for world_seed in contract["execution"]["world_seeds"]:
        subject_means: dict[str, float] = {}
        subject_counts: dict[str, int] = {}
        for subject in sorted(subjects):
            eligible = [
                row
                for row in rows
                if row["world_seed"] == world_seed
                and row["subject"] == subject
                and row["status"] == "completed"
            ]
            subject_counts[subject] = len(eligible)
            if len(eligible) == expected_per_subject:
                subject_means[subject] = statistics.fmean(
                    float(row["within_case_score"]) for row in eligible
                )
        complete_pair = len(subject_means) == 2
        contrast = (
            subject_means["glm_53_flash"]
            - subject_means["deepseek_v4_flash"]
            if complete_pair
            else None
        )
        if contrast is not None:
            contrasts.append(contrast)
        world_rows.append(
            {
                "world_seed": world_seed,
                "complete_pair": complete_pair,
                "completed_cells_by_subject": subject_counts,
                "subject_means": subject_means,
                "contrast": contrast,
            }
        )

    paired_world_count = len(contrasts)
    sample_variance = (
        statistics.variance(contrasts) if paired_world_count >= 2 else None
    )
    sample_standard_deviation = (
        math.sqrt(sample_variance) if sample_variance is not None else None
    )
    mean_contrast = statistics.fmean(contrasts) if contrasts else None
    raw_required_worlds: int | None = None
    attrition_adjusted_worlds: int | None = None
    recommended_worlds: int | None = None
    within_declared_maximum = False
    if sample_standard_deviation is not None:
        z_alpha = 1.959963984540054
        z_power = 0.8416212335729143
        raw_required_worlds = math.ceil(
            (
                (z_alpha + z_power)
                * sample_standard_deviation
                / analysis["minimum_meaningful_effect"]
            )
            ** 2
        )
        attrition_adjusted_worlds = math.ceil(
            raw_required_worlds / (1.0 - analysis["attrition_fraction"])
        )
        recommended_worlds = max(
            analysis["minimum_confirmatory_worlds"], attrition_adjusted_worlds
        )
        within_declared_maximum = (
            recommended_worlds <= analysis["maximum_confirmatory_worlds"]
        )
    return _sealed(
        {
            "schema_version": "aeread.housing_variance_pilot_analysis/0.1",
            "campaign_id": contract["campaign_id"],
            "status": (
                "estimable" if paired_world_count >= 2 else "insufficient_paired_worlds"
            ),
            "claim_status": contract["claim_status"],
            "ranking_allowed": False,
            "independent_cluster": "world_seed",
            "planned_world_count": len(contract["execution"]["world_seeds"]),
            "paired_world_count": paired_world_count,
            "incomplete_world_count": len(world_rows) - paired_world_count,
            "expected_cells_per_subject_per_world": expected_per_subject,
            "mean_paired_contrast": mean_contrast,
            "sample_variance": sample_variance,
            "sample_standard_deviation": sample_standard_deviation,
            "minimum_meaningful_effect": analysis["minimum_meaningful_effect"],
            "alpha": analysis["alpha"],
            "power": analysis["power"],
            "raw_required_worlds": raw_required_worlds,
            "attrition_adjusted_worlds": attrition_adjusted_worlds,
            "minimum_confirmatory_worlds": analysis[
                "minimum_confirmatory_worlds"
            ],
            "maximum_confirmatory_worlds": analysis[
                "maximum_confirmatory_worlds"
            ],
            "recommended_confirmatory_worlds": recommended_worlds,
            "within_declared_maximum": within_declared_maximum,
            "worlds": world_rows,
        }
    )


async def run_live(
    contract: Mapping[str, Any],
    *,
    output_root: Path,
    routes: Mapping[str, OpenRouterRoutePin] | None = None,
    stage_id: str = "live",
    provider_client: Any | None = None,
) -> dict[str, Any]:
    if stage_id not in {"live", "full_trajectory"}:
        raise ValueError("stage_id must be live or full_trajectory")
    live_root = output_root / stage_id
    summary_path = live_root / "summary.json"
    if summary_path.exists():
        return _read_sealed(summary_path)
    setups = build_setups(contract, routes=routes)
    current_execution_digest = hashlib.sha256(
        Path(execution_module.__file__).read_bytes()
    ).hexdigest()
    planned_execution_digests = {
        pin.sha256
        for setup in setups.values()
        for pin in setup.plan.implementation_pins
        if pin.component_id == "aeread.shared_runner.execution"
    }
    if planned_execution_digests != {current_execution_digest}:
        raise EvidenceIntegrityError(
            "live Housing execution runtime differs from the frozen implementation "
            "pin; create a new campaign identity"
        )
    client = provider_client or OpenRouterChatClient()
    conditions = list(contract["conditions"])
    execution_contract = contract["execution"]
    rows: list[dict[str, Any]] = []
    critical_stop = False
    stop_reason: str | None = None
    configs = selected_configs(contract)
    ordered_cells: list[tuple[Mapping[str, Any], Mapping[str, Any], Any, Any]] = []
    for world_index, world_seed in enumerate(execution_contract["world_seeds"]):
        for config_index, config in enumerate(configs):
            rotation_index = config_index
            if contract["controls"]["condition_order"] == (
                "rotate_by_world_and_case_configuration"
            ):
                rotation_index += world_index * len(configs)
            offset = rotation_index % len(conditions)
            rotated = conditions[offset:] + conditions[:offset]
            for condition in rotated:
                setup = setups[(config["config_id"], condition["condition_id"])]
                for replicate_index in range(execution_contract["replicates"]):
                    matches = [
                        cell
                        for cell in setup.plan.cells
                        if cell.world_seed == world_seed
                        and cell.replicate_index == replicate_index
                    ]
                    if len(matches) != 1:
                        raise ValueError("frozen execution cell did not resolve uniquely")
                    ordered_cells.append((config, condition, setup, matches[0]))

    for config, condition, setup, cell in ordered_cells:
        condition_id = condition["condition_id"]
        result_path = (
            live_root
            / config["config_id"]
            / condition_id
            / "results"
            / f"world_{cell.world_seed}__rep_{cell.replicate_index}.json"
        )
        if result_path.exists():
            rows.append(_read_sealed(result_path))
            continue
        cost_so_far = sum(float(row.get("cost_usd", 0.0)) for row in rows)
        if (
            cost_so_far + execution_contract["per_trajectory_cost_reserve_usd"]
            > execution_contract["cost_ceiling_usd"]
        ):
            critical_stop = True
            stop_reason = "campaign_cost_reserve_reached"
            break
        evidence_root = live_root / config["config_id"] / condition_id / "evidence"
        started = time.perf_counter()
        pacing_observation_index = (
            client.observation_count
            if isinstance(client, (PacedProviderClient, CooldownProviderClient))
            else None
        )
        critical_error = False
        try:
            execution = await execute_plan_cell(
                plan=setup.plan,
                cell_id=cell.cell_id,
                registry=setup.registry,
                evidence_root=evidence_root,
                prompt_sources=setup.prompt_sources,
                providers={"openrouter": client},
                pricing=setup.pricing,
                harnesses=setup.harnesses,
                episode_attempt_ordinal=0,
            )
            receipt = finalize_housing_execution(setup=setup, execution=execution)
            verify_evaluation_receipt(receipt)
            replayed = replay_housing_receipt(
                setup=setup,
                receipt=receipt,
                evidence_root=evidence_root,
            )
            if canonical_json_bytes(replayed.scores) != canonical_json_bytes(
                receipt.scores
            ):
                raise ValueError("offline replay score mismatch")
            outcome = execution.episode_result.outcome
            row = {
                "config_id": config["config_id"],
                "difficulty_stratum": config["difficulty_stratum"],
                "condition_id": condition_id,
                "subject": condition["subject"],
                "opponent": condition["opponent"],
                "evaluation_kind": condition["evaluation_kind"],
                "world_seed": cell.world_seed,
                "replicate_index": cell.replicate_index,
                "status": "completed",
                "within_case_score": outcome["within_case_score"],
                "social_welfare": outcome["social_welfare"],
                "tenant_payoff": sum(outcome["tenant_payoffs"].values()),
                "landlord_payoff": sum(outcome["landlord_payoffs"].values()),
                "ir_violation_count": len(outcome["ir_violations"]),
                "wasted_contacts": outcome["wasted_contacts"],
                "logical_action_count": execution.episode_result.logical_action_count,
                "cost_usd": execution.total_cost_usd,
                "elapsed_seconds": time.perf_counter() - started,
                "receipt_sha256": receipt.receipt_sha256,
                "run_plan_id": setup.plan.run_plan_id,
                "cell_id": cell.cell_id,
                "route_verified": True,
                "provider_cost_complete": True,
                "replay_verified": True,
                "role_metrics": _role_metrics(
                    execution,
                    tenant_profile_id=contract["models"][condition["subject"]][
                        "tenant_profile_id"
                    ],
                ),
            }
        except Exception as error:
            receipt_sha256 = None
            try:
                failure_receipt = finalize_housing_failure(
                    setup=setup,
                    cell_id=cell.cell_id,
                    evidence_root=evidence_root,
                    error=error,
                )
                receipt_sha256 = failure_receipt.receipt_sha256
            except Exception:
                pass
            usage = _failure_usage(
                evidence_root=evidence_root,
                run_plan_id=setup.plan.run_plan_id,
                cell_id=cell.cell_id,
            )
            row = {
                "config_id": config["config_id"],
                "difficulty_stratum": config["difficulty_stratum"],
                "condition_id": condition_id,
                "subject": condition["subject"],
                "opponent": condition["opponent"],
                "evaluation_kind": condition["evaluation_kind"],
                "world_seed": cell.world_seed,
                "replicate_index": cell.replicate_index,
                "status": "operational_failure",
                "failure_type": type(error).__name__,
                "failure_condition": (
                    _exception_attribute(error, "condition") or "execution_error"
                ),
                "failure_status_code": _exception_attribute(error, "status_code"),
                "receipt_sha256": receipt_sha256,
                "run_plan_id": setup.plan.run_plan_id,
                "cell_id": cell.cell_id,
                "cost_usd": usage["cost_usd"],
                "failure_usage": usage,
                "elapsed_seconds": time.perf_counter() - started,
            }
            critical_error = _critical_failure(error)
        if pacing_observation_index is not None:
            row["call_pacing"] = client.pacing_summary_since(
                pacing_observation_index
            )
        sealed_row = _sealed(row)
        _write_json(result_path, sealed_row)
        rows.append(sealed_row)
        if critical_error:
            critical_stop = True
            stop_reason = "critical_route_replay_or_cost_failure"
            break

    expected = (
        len(selected_configs(contract))
        * len(contract["conditions"])
        * len(execution_contract["world_seeds"])
        * execution_contract["replicates"]
    )
    completed = [row for row in rows if row["status"] == "completed"]
    failures = [row for row in rows if row["status"] == "operational_failure"]
    total_cost = sum(float(row.get("cost_usd", 0.0)) for row in rows)
    if total_cost > execution_contract["cost_ceiling_usd"] + 1e-12:
        raise RuntimeError("model-sensitivity run exceeded its hard cost ceiling")
    artifact_core: dict[str, Any] = {
        "schema_version": "aeread.housing_model_sensitivity_results/0.1",
        "campaign_id": contract["campaign_id"],
        "status": (
            "completed_with_full_matrix"
            if len(completed) == expected
            else (
                "completed_with_typed_missingness"
                if len(rows) == expected
                else "stopped_with_typed_missingness"
            )
        ),
        "claim_status": contract["claim_status"],
        "winner_claim_allowed": False,
        "ranking_allowed": False,
        "planned_trajectories": expected,
        "attempted_trajectories": len(rows),
        "completed_trajectories": len(completed),
        "operational_failures": len(failures),
        "not_started_trajectories": expected - len(rows),
        "complete_matrix": len(completed) == expected,
        "total_cost_usd": total_cost,
        "cost_ceiling_usd": execution_contract["cost_ceiling_usd"],
        "critical_stop": critical_stop,
        "stop_reason": stop_reason,
        "uncertainty": contract["analysis"]["uncertainty"],
        "configuration_views": _summary_views(rows, contract),
        "rows": rows,
    }
    if contract["analysis"].get("aggregation") == (
        "equal_weight_configs_and_opponents_within_world"
    ):
        artifact_core["variance_pilot_analysis"] = variance_pilot_analysis(
            rows, contract
        )
    if stage_id == "full_trajectory":
        artifact_core.update(
            {
                "gate_id": "full_trajectory",
                "promotion_eligible": len(completed) == expected,
                "promotion_requirement": (
                    "one completed trajectory per frozen subject-opponent condition"
                ),
            }
        )
    if "call_pacing" in contract["controls"]:
        artifact_core["call_pacing"] = {
            **contract["controls"]["call_pacing"],
            "observed": (
                client.pacing_summary_since(0)
                if isinstance(client, (PacedProviderClient, CooldownProviderClient))
                else None
            ),
        }
    artifact = _sealed(artifact_core)
    _write_json(summary_path, artifact)
    return artifact


async def execute_campaign(
    *, contract_path: str | Path, output_root: str | Path, through: str
) -> dict[str, Any]:
    if through not in {"design", "provider_free", "live"}:
        raise ValueError("through must be design, provider_free, or live")
    contract = load_contract(contract_path)
    root = Path(output_root)
    design = design_artifact(contract)
    _write_json(root / "design" / "summary.json", design)
    result: dict[str, Any] = {"design": design}
    if through in {"provider_free", "live"}:
        provider_free = provider_free_artifact(contract)
        _write_json(root / "provider_free" / "summary.json", provider_free)
        result["provider_free"] = provider_free
    if through == "live":
        if not os.getenv("OPENROUTER_API_KEY"):
            raise RuntimeError("OPENROUTER_API_KEY is required for the live stage")
        result["live"] = await run_live(contract, output_root=root)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the fixed-harness Housing model-sensitivity slice"
    )
    parser.add_argument(
        "--contract",
        default="configs/housing_model_sensitivity_v1.json",
    )
    parser.add_argument(
        "--run-root",
        "--output",
        dest="run_root",
        default="runs/housing_model_sensitivity_v1",
    )
    parser.add_argument(
        "--through",
        choices=("design", "provider_free", "live"),
        default="provider_free",
    )
    args = parser.parse_args(argv)
    result = asyncio.run(
        execute_campaign(
            contract_path=args.contract,
            output_root=args.run_root,
            through=args.through,
        )
    )
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
