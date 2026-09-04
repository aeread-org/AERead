"""Frozen V2 data-center world panel: 24 worlds, paired live developers.

Every live cell puts one OpenRouter route in the developer seat against the
fixed scripted counterparties of one generated world. Worlds are the
independent clusters; every model sees every world and inference seed, and the
model execution order rotates by world index so no route always runs first.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import statistics
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import OpenRouterChatClient, TokenPricing
from aeread.shared_runner.task.receipts import verify_evaluation_receipt
from aeread_families.procurement_grounding.runner import OpenRouterRoute

from .stack_runner import (
    build_stack_openrouter_setup,
    finalize_stack_execution,
    finalize_stack_failure,
    replay_stack_receipt,
    run_stack_offline,
    run_stack_openrouter,
)
from .stack_worlds import DEFAULT_OUTPUT_ROOT as DEFAULT_PACK_ROOT
from .stack_worlds import PACK_ID, load_pack_manifest


CONTRACT_SCHEMA_VERSION = "aeread.datacenter_world_campaign_contract/0.1"
CAMPAIGN_ID = "datacenter_development_v2_world_panel_v1"
CONDITIONS = ("controlled_developer",)
LIVE_PROFILE_COUNT = 1
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT_PATH = REPOSITORY_ROOT / "configs" / f"{CAMPAIGN_ID}.json"
DEFAULT_RUN_ROOT = REPOSITORY_ROOT / "runs" / CAMPAIGN_ID
DEFAULT_PUBLICATION_ROOT = REPOSITORY_ROOT / "evidence" / CAMPAIGN_ID
PROHIBITED_PUBLIC_TEXT = (
    '"raw_response"',
    '"failure_message"',
    '"output_text"',
    '"user_id"',
    "authorization:",
    "api_key",
    "/users/",
)
OPTIONAL_ROUTE_FIELDS = {"max_cost_usd_per_live_profile"}
ROUTE_FIELDS = {
    "profile_id",
    "requested_model",
    "canonical_model",
    "provider",
    "quantization",
    "access_class",
    "license_id",
    "reasoning_effort",
    "temperature_supported",
    "pricing",
    "max_prompt_price_per_million",
    "max_completion_price_per_million",
}


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sealed(value: Mapping[str, Any]) -> dict[str, Any]:
    core = {key: item for key, item in value.items() if key != "artifact_sha256"}
    return {**core, "artifact_sha256": _sha256(core)}


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _read_sealed(path: Path) -> dict[str, Any]:
    value = _read_json(path)
    if value != _sealed(value):
        raise ValueError(f"artifact digest mismatch: {path}")
    return value


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


# --------------------------------------------------------------------------
# Contract
# --------------------------------------------------------------------------


def load_contract(path: Path | str = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    contract = _read_json(Path(path))
    expected_fields = {
        "schema_version",
        "campaign_id",
        "family_id",
        "scope_version",
        "pack_id",
        "expected_pack_sha256",
        "claim_status",
        "inference_seeds",
        "conditions",
        "models",
        "execution",
        "analysis",
    }
    if set(contract) != expected_fields:
        raise ValueError("campaign contract fields differ")
    if contract["schema_version"] != CONTRACT_SCHEMA_VERSION:
        raise ValueError("campaign contract schema version differs")
    if contract["campaign_id"] != CAMPAIGN_ID:
        raise ValueError("campaign ID differs")
    if contract["family_id"] != "datacenter_development_v1":
        raise ValueError("campaign family differs")
    if contract["scope_version"] != "v2":
        raise ValueError("campaign must use the V2 agreement stack")
    if contract["pack_id"] != PACK_ID:
        raise ValueError("campaign must run the generated V2 world pack")
    if tuple(contract["conditions"]) != CONDITIONS:
        raise ValueError("campaign conditions differ")

    seeds = contract["inference_seeds"]
    if (
        not isinstance(seeds, list)
        or len(seeds) < 1
        or len(seeds) != len(set(seeds))
        or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seeds)
    ):
        raise ValueError("campaign requires unique non-negative inference seeds")

    models = contract["models"]
    if not isinstance(models, dict) or len(models) < 2:
        raise ValueError("campaign requires at least two model routes to pair")
    for model_id, model in models.items():
        if not isinstance(model, dict) or set(model) - OPTIONAL_ROUTE_FIELDS != ROUTE_FIELDS:
            raise ValueError(f"{model_id}: model route fields differ")
        if model["access_class"] not in {"open_source", "proprietary"}:
            raise ValueError(f"{model_id}: access_class must be open_source or proprietary")
        cap = model.get("max_cost_usd_per_live_profile")
        if cap is not None and (isinstance(cap, bool) or not isinstance(cap, (int, float)) or cap <= 0):
            raise ValueError(f"{model_id}: max_cost_usd_per_live_profile must be positive")
        pricing = model["pricing"]
        if not isinstance(pricing, dict) or set(pricing) != {
            "input_per_million",
            "cached_input_per_million",
            "output_per_million",
            "pricing_id",
        }:
            raise ValueError(f"{model_id}: pricing fields differ")

    execution = contract["execution"]
    execution_fields = {
        "harness",
        "max_output_tokens_per_action",
        "timeout_seconds_per_action",
        "max_cost_usd_per_live_profile",
        "campaign_max_cost_usd",
        "concurrency",
        "max_concurrent_cells_per_route_provider",
        "provider_cooldown_seconds_after_cell",
        "max_action_attempts",
        "sdk_retries",
        "response_cache",
        "provider_fallbacks",
    }
    if set(execution) != execution_fields:
        raise ValueError("campaign execution fields differ")
    frozen_controls = {
        "harness": "minimal_chat/1.0",
        "max_concurrent_cells_per_route_provider": 1,
        "max_action_attempts": 1,
        "sdk_retries": 0,
        "response_cache": False,
        "provider_fallbacks": False,
    }
    if any(execution[key] != value for key, value in frozen_controls.items()):
        raise ValueError("campaign cache, retry, routing, or harness controls differ")
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
    cooldown = execution["provider_cooldown_seconds_after_cell"]
    if isinstance(cooldown, bool) or not isinstance(cooldown, (int, float)) or cooldown < 0:
        raise ValueError("execution.provider_cooldown_seconds_after_cell must be non-negative")

    analysis = contract["analysis"]
    if analysis.get("resampling_unit") != "world":
        raise ValueError("campaign must resample by world")
    if analysis.get("missingness") != "report_separately":
        raise ValueError("campaign must report operational missingness separately")
    if analysis.get("execution_order") != "rotate_model_order_by_world_index":
        raise ValueError("campaign must rotate model execution order by world")
    for field in (
        "winner_claim_allowed",
        "inferential_model_ranking_allowed",
        "causal_condition_effect_allowed",
    ):
        if analysis.get(field) is not False:
            raise ValueError(f"analysis.{field} must be false")
    return contract


def _profile_cap(contract: Mapping[str, Any], model_id: str) -> float:
    """Per-route live cost ceiling, falling back to the campaign default."""

    model = contract["models"][model_id]
    override = model.get("max_cost_usd_per_live_profile")
    if override is not None:
        return float(override)
    return float(contract["execution"]["max_cost_usd_per_live_profile"])


def _route(model: Mapping[str, Any]) -> OpenRouterRoute:
    pricing = model["pricing"]
    return OpenRouterRoute(
        profile_id=str(model["profile_id"]),
        model=str(model["requested_model"]),
        revision=str(model["canonical_model"]),
        route_provider=str(model["provider"]),
        quantization=str(model["quantization"]),
        pricing=TokenPricing(
            float(pricing["input_per_million"]),
            float(pricing["cached_input_per_million"]),
            float(pricing["output_per_million"]),
            str(pricing["pricing_id"]),
        ),
        max_prompt_price_per_million=str(model["max_prompt_price_per_million"]),
        max_completion_price_per_million=str(model["max_completion_price_per_million"]),
        reasoning_effort=model["reasoning_effort"],
        temperature_supported=bool(model["temperature_supported"]),
    )


def load_pack(contract: Mapping[str, Any], pack_root: Path | str = DEFAULT_PACK_ROOT) -> dict[str, Any]:
    manifest = load_pack_manifest(pack_root)
    if manifest["pack_id"] != contract["pack_id"]:
        raise ValueError("world pack ID differs from the frozen campaign contract")
    if manifest["artifact_sha256"] != contract["expected_pack_sha256"]:
        raise ValueError("world pack hash differs from the frozen campaign contract")
    if manifest["world_count"] != int(contract["analysis"]["independent_cluster_count"]):
        raise ValueError("world count differs from the declared cluster count")
    return manifest


def _world_slug(world: Mapping[str, Any]) -> str:
    return str(world["file"]).removesuffix(".json")


def _cells(contract: Mapping[str, Any], manifest: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Enumerate cells in execution order: rotate the model order per world."""

    model_ids = sorted(contract["models"])
    cells: list[dict[str, Any]] = []
    for world_index, world in enumerate(manifest["worlds"]):
        shift = world_index % len(model_ids)
        rotated = model_ids[shift:] + model_ids[:shift]
        for seed in contract["inference_seeds"]:
            for order_index, model_id in enumerate(rotated):
                cells.append(
                    {
                        "cell_key": f"{_world_slug(world)}__{model_id}__seed_{seed}",
                        "condition": CONDITIONS[0],
                        "world_index": world_index,
                        "case_id": world["case_id"],
                        "case_file": world["file"],
                        "case_sha256": world["content_sha256"],
                        "world_seed": world["world_seed"],
                        "stratum": world["stratum"],
                        "variant": world["variant"],
                        "model_id": model_id,
                        "execution_order_in_world": order_index,
                        "inference_seed": seed,
                        "scripted_baseline_developer_equity_npv_cents": world["mechanism"][
                            "feasible_path"
                        ]["developer_equity_npv_cents"],
                        "outside_option_developer_equity_npv_cents": world["mechanism"][
                            "walk_away"
                        ]["developer_equity_npv_cents"],
                    }
                )
    return tuple(cells)


def _setup(contract: Mapping[str, Any], cell: Mapping[str, Any], pack_root: Path) -> Any:
    controls = contract["execution"]
    route = _route(contract["models"][cell["model_id"]])
    return build_stack_openrouter_setup(
        "v2",
        route,
        seed=int(cell["inference_seed"]),
        case_path=pack_root / str(cell["case_file"]),
        max_output_tokens=int(controls["max_output_tokens_per_action"]),
        timeout_seconds=float(controls["timeout_seconds_per_action"]),
        max_cost_usd=_profile_cap(contract, str(cell["model_id"])),
    )


def build_design(
    contract: Mapping[str, Any], *, pack_root: Path | str = DEFAULT_PACK_ROOT
) -> dict[str, Any]:
    root = Path(pack_root)
    manifest = load_pack(contract, root)
    cells: list[dict[str, Any]] = []
    for cell in _cells(contract, manifest):
        per_profile = _profile_cap(contract, str(cell["model_id"]))
        setup = _setup(contract, cell, root)
        plan_cell = setup.plan.cells[0]
        live_profiles = sum(
            profile.model.provider == "openrouter" for profile in setup.plan.agent_profiles
        )
        if live_profiles != LIVE_PROFILE_COUNT:
            raise ValueError(f"live profile count drift for {cell['cell_key']}")
        if plan_cell.case_id != cell["case_id"] or plan_cell.case_sha256 != cell["case_sha256"]:
            raise ValueError(f"case identity drift for {cell['cell_key']}")
        cells.append(
            {
                **cell,
                "run_plan_id": setup.plan.run_plan_id,
                "run_plan_sha256": setup.plan.plan_sha256,
                "cell_id": plan_cell.cell_id,
                "evaluation_block_kind": setup.plan.evaluation_blocks[0].kind,
                "live_profile_count": live_profiles,
                "declared_cell_max_cost_usd": live_profiles * per_profile,
            }
        )
    declared_maximum = sum(row["declared_cell_max_cost_usd"] for row in cells)
    campaign_maximum = float(contract["execution"]["campaign_max_cost_usd"])
    if declared_maximum > campaign_maximum:
        raise ValueError("resolved design exceeds the campaign cost ceiling")
    return _sealed(
        {
            "schema_version": "aeread.datacenter_world_campaign_design/0.1",
            "campaign_id": contract["campaign_id"],
            "contract_sha256": _sha256(contract),
            "campaign_driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "pack_id": manifest["pack_id"],
            "pack_sha256": manifest["artifact_sha256"],
            "generator_sha256": manifest["generator_sha256"],
            "independent_cluster_count": manifest["world_count"],
            "planned_cells": len(cells),
            "paired_seed_count": len(contract["inference_seeds"]),
            "model_ids": sorted(contract["models"]),
            "worst_case_declared_cost_usd": declared_maximum,
            "campaign_max_cost_usd": campaign_maximum,
            "cells": cells,
        }
    )


# --------------------------------------------------------------------------
# Gates
# --------------------------------------------------------------------------


async def run_provider_free_gate(
    contract: Mapping[str, Any], *, run_root: Path, pack_root: Path
) -> dict[str, Any]:
    """Execute and replay every world with scripted seats before any live call."""

    summary_path = run_root / "provider_free_validation" / "summary.json"
    if summary_path.exists():
        return _read_sealed(summary_path)
    manifest = load_pack(contract, pack_root)
    worlds: list[dict[str, Any]] = []
    for world in manifest["worlds"]:
        evidence_root = run_root / "provider_free_validation" / _world_slug(world)
        setup, execution = await run_stack_offline(
            "v2", evidence_root=evidence_root, case_path=pack_root / str(world["file"])
        )
        receipt = finalize_stack_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_stack_receipt(setup=setup, receipt=receipt, evidence_root=evidence_root)
        verify_evaluation_receipt(replayed)
        outcome = execution.episode_result.outcome
        expected_npv = world["mechanism"]["feasible_path"]["developer_equity_npv_cents"]
        passed = (
            receipt.inclusion_status == "included"
            and bool(outcome["project_completed"])
            and bool(outcome["binding_contract_integrity"])
            and bool(outcome["project_constraints_satisfied"])
            and not outcome["temporal_violations"]
            and int(outcome["developer_equity_npv_cents"]) == int(expected_npv)
            and replayed == receipt
        )
        worlds.append(
            {
                "case_id": world["case_id"],
                "stratum": world["stratum"],
                "case_sha256": setup.case.content_sha256,
                "logical_action_count": execution.episode_result.logical_action_count,
                "developer_equity_npv_cents": outcome["developer_equity_npv_cents"],
                "receipt_sha256": receipt.receipt_sha256,
                "replay_verified": replayed == receipt,
                "status": "passed" if passed else "failed",
            }
        )
    summary = _sealed(
        {
            "schema_version": "aeread.datacenter_world_provider_free_gate/0.1",
            "campaign_id": contract["campaign_id"],
            "contract_sha256": _sha256(contract),
            "pack_sha256": manifest["artifact_sha256"],
            "status": "passed" if all(row["status"] == "passed" for row in worlds) else "failed",
            "world_count": len(worlds),
            "strata_replayed": sorted({row["stratum"] for row in worlds}),
            "worlds": worlds,
        }
    )
    _atomic_write(summary_path, summary)
    return summary


def run_profile_admission_gate(
    contract: Mapping[str, Any], *, design: Mapping[str, Any], run_root: Path, pack_root: Path
) -> dict[str, Any]:
    summary_path = run_root / "profile_admission" / "summary.json"
    if summary_path.exists():
        return _read_sealed(summary_path)
    manifest = load_pack(contract, pack_root)
    design_by_key = {cell["cell_key"]: cell for cell in design["cells"]}
    admitted: list[str] = []
    for cell in _cells(contract, manifest):
        setup = _setup(contract, cell, pack_root)
        expected = design_by_key[str(cell["cell_key"])]
        if (
            setup.plan.plan_sha256 != expected["run_plan_sha256"]
            or setup.plan.cells[0].cell_id != expected["cell_id"]
            or not all(item.admitted for item in setup.plan.profile_admissions)
        ):
            raise ValueError(f"profile admission drift for {cell['cell_key']}")
        admitted.append(str(cell["cell_key"]))
    summary = _sealed(
        {
            "schema_version": "aeread.datacenter_world_profile_gate/0.1",
            "campaign_id": contract["campaign_id"],
            "contract_sha256": _sha256(contract),
            "status": "passed",
            "admitted_cells": admitted,
        }
    )
    _atomic_write(summary_path, summary)
    return summary


# --------------------------------------------------------------------------
# Live cells
# --------------------------------------------------------------------------


def _call_usage(execution: Any) -> dict[str, Any]:
    calls = [
        call
        for action in execution.action_executions
        for attempt in action.attempts
        for call in attempt.provider_calls
    ]
    return {
        "provider_calls_started": len(calls),
        "provider_calls_succeeded": sum(call.status == "succeeded" for call in calls),
        "input_tokens": sum(call.input_tokens for call in calls),
        "cached_input_tokens": sum(call.cached_input_tokens for call in calls),
        "output_tokens": sum(call.output_tokens for call in calls),
        "reported_cost_usd": sum(call.cost_usd for call in calls),
        "resolved_models": sorted(
            {call.resolved_model for call in calls if call.resolved_model is not None}
        ),
    }


def _verify_route(execution: Any, model: Mapping[str, Any]) -> dict[str, Any]:
    """Confirm every successful OpenRouter call landed on the pinned endpoint."""

    selected: list[tuple[str | None, str | None]] = []
    evidence = execution.evidence
    for event in evidence.read_events():
        if event.event_type != "provider_call_succeeded":
            continue
        payload = evidence.read_event_payload(event)
        result = payload.get("provider_result") if isinstance(payload, Mapping) else None
        if not isinstance(result, Mapping) or result.get("requested_model") != model["requested_model"]:
            continue
        raw = result.get("raw_response")
        metadata = raw.get("openrouter_metadata") if isinstance(raw, Mapping) else None
        endpoints = metadata.get("endpoints") if isinstance(metadata, Mapping) else None
        available = endpoints.get("available") if isinstance(endpoints, Mapping) else None
        chosen = (
            [item for item in available if item.get("selected") is True]
            if isinstance(available, list)
            else []
        )
        if len(chosen) != 1:
            raise ValueError("successful OpenRouter event lacks one selected endpoint")
        selected.append((chosen[0].get("provider"), chosen[0].get("model")))
    expected = (str(model["provider"]), str(model["canonical_model"]))
    return {
        "route_verified": bool(selected) and all(item == expected for item in selected),
        "verified_openrouter_call_count": len(selected),
    }


def _score_projection(receipt: Any) -> dict[str, Any]:
    return {
        item.leaf.leaf_id: {
            "value": item.primary.value if item.primary is not None else None,
            "unit": item.primary.unit if item.primary is not None else None,
            "status": item.status,
            "validity": item.validity.status,
        }
        for item in receipt.scores
    }


def _outcome_projection(outcome: Mapping[str, Any]) -> dict[str, Any]:
    decisions = [
        {
            "phase_id": item.get("phase_id"),
            "seat_id": item.get("seat_id"),
            "agreement_key": item.get("agreement_key"),
            "decision": item.get("decision"),
        }
        for item in outcome.get("public_history", [])
    ]
    return {
        "project_completed": bool(outcome["project_completed"]),
        "termination_reason": outcome["termination_reason"],
        "binding_contract_integrity": bool(outcome["binding_contract_integrity"]),
        "project_constraints_satisfied": bool(outcome["project_constraints_satisfied"]),
        "amendment_precedence_valid": bool(outcome["amendment_precedence_valid"]),
        "temporal_violations": list(outcome["temporal_violations"]),
        "developer_equity_npv_cents": int(outcome["developer_equity_npv_cents"]),
        "lender_npv_cents": int(outcome["lender_npv_cents"]),
        "customer_npv_cents": int(outcome["customer_npv_cents"]),
        "total_project_npv_cents": int(outcome["total_project_npv_cents"]),
        "default_reasons": (
            list(outcome["project_outcome"]["project"]["default_reasons"])
            if isinstance(outcome.get("project_outcome"), Mapping)
            else []
        ),
        "decisions": decisions,
        "counter_rounds": sum(item["decision"] == "counter" for item in decisions),
    }


async def _run_live_cell(
    contract: Mapping[str, Any],
    design_cell: Mapping[str, Any],
    *,
    run_root: Path,
    pack_root: Path,
    provider: Any,
) -> dict[str, Any]:
    cell_root = run_root / "live" / str(design_cell["cell_key"])
    result_path = cell_root / "result.json"
    if result_path.exists():
        result = _read_sealed(result_path)
        if result["run_plan_sha256"] != design_cell["run_plan_sha256"]:
            raise ValueError(f"resumed result drift for {design_cell['cell_key']}")
        return result
    if cell_root.exists():
        raise ValueError(f"refusing to replace incomplete live cell {design_cell['cell_key']}")

    setup = _setup(contract, design_cell, pack_root)
    if (
        setup.plan.plan_sha256 != design_cell["run_plan_sha256"]
        or setup.plan.cells[0].cell_id != design_cell["cell_id"]
    ):
        raise ValueError(f"live plan drift for {design_cell['cell_key']}")
    model = contract["models"][design_cell["model_id"]]
    route = _route(model)
    controls = contract["execution"]
    started = time.perf_counter()
    try:
        _, execution = await run_stack_openrouter(
            "v2",
            route,
            evidence_root=cell_root / "evidence",
            seed=int(design_cell["inference_seed"]),
            case_path=pack_root / str(design_cell["case_file"]),
            max_output_tokens=int(controls["max_output_tokens_per_action"]),
            timeout_seconds=float(controls["timeout_seconds_per_action"]),
            max_cost_usd=_profile_cap(contract, str(design_cell["model_id"])),
            provider=provider,
        )
        receipt = finalize_stack_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_stack_receipt(
            setup=setup, receipt=receipt, evidence_root=cell_root / "evidence"
        )
        verify_evaluation_receipt(replayed)
        result = _sealed(
            {
                "schema_version": "aeread.datacenter_world_live_cell/0.1",
                "campaign_id": contract["campaign_id"],
                **dict(design_cell),
                "status": "completed",
                "receipt_status": receipt.status,
                "inclusion_status": receipt.inclusion_status,
                "receipt_sha256": receipt.receipt_sha256,
                "replay_verified": replayed == receipt,
                "elapsed_seconds": time.perf_counter() - started,
                "usage": _call_usage(execution),
                **_verify_route(execution, model),
                "outcome": _outcome_projection(_plain(execution.episode_result.outcome)),
                "scores": _score_projection(receipt),
                "failure": None,
            }
        )
    except Exception as error:
        receipt = finalize_stack_failure(
            setup=setup,
            cell_id=setup.plan.cells[0].cell_id,
            evidence_root=cell_root / "evidence",
            error=error,
        )
        verify_evaluation_receipt(receipt)
        result = _sealed(
            {
                "schema_version": "aeread.datacenter_world_live_cell/0.1",
                "campaign_id": contract["campaign_id"],
                **dict(design_cell),
                "status": "operational_failure",
                "receipt_status": receipt.status,
                "inclusion_status": receipt.inclusion_status,
                "receipt_sha256": receipt.receipt_sha256,
                "replay_verified": False,
                "elapsed_seconds": time.perf_counter() - started,
                "usage": None,
                "route_verified": False,
                "verified_openrouter_call_count": 0,
                "outcome": None,
                "scores": None,
                "failure": {
                    "failure_class": receipt.failure.failure_class,
                    "failure_condition": receipt.failure.condition,
                    "error_type": type(error).__name__,
                },
            }
        )
    _atomic_write(result_path, result)
    return result


# --------------------------------------------------------------------------
# Summary and leaderboard
# --------------------------------------------------------------------------


def _admitted(row: Mapping[str, Any]) -> bool:
    outcome = row.get("outcome")
    return (
        row["status"] == "completed"
        and row["inclusion_status"] == "included"
        and isinstance(outcome, Mapping)
        and bool(outcome["binding_contract_integrity"])
        and bool(outcome["project_constraints_satisfied"])
        and not outcome["temporal_violations"]
    )


NO_AGREEMENT_SUFFIXES = ("_negotiation_rounds_exhausted", "_walk", "_reject")


def _no_agreement(row: Mapping[str, Any]) -> bool:
    """A valid episode that ended without an executed stack (outside option)."""

    outcome = row.get("outcome")
    if (
        row["status"] != "completed"
        or row["inclusion_status"] != "included"
        or not isinstance(outcome, Mapping)
        or bool(outcome["project_completed"])
        or outcome["temporal_violations"]
    ):
        return False
    reason = str(outcome["termination_reason"])
    return any(reason.endswith(suffix) for suffix in NO_AGREEMENT_SUFFIXES)


def _walked_away(row: Mapping[str, Any]) -> bool:
    return _no_agreement(row)


def _economic_value(row: Mapping[str, Any]) -> float | None:
    """Developer NPV for admitted stacks and no-agreement outcomes; else None."""

    if _admitted(row) or _no_agreement(row):
        return float(row["outcome"]["developer_equity_npv_cents"])
    return None


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _model_summary(model_id: str, rows: Sequence[Mapping[str, Any]], planned: int) -> dict[str, Any]:
    selected = [row for row in rows if row["model_id"] == model_id]
    completed = [row for row in selected if row["status"] == "completed"]
    admitted = [row for row in selected if _admitted(row)]
    walked = [row for row in selected if _walked_away(row)]
    excluded = [
        row
        for row in completed
        if not _admitted(row) and not _walked_away(row)
    ]
    economic = [row for row in selected if _economic_value(row) is not None]
    complete_panel = len(completed) == planned
    route_verified = complete_panel and all(row["route_verified"] for row in completed)
    usage_rows = [row["usage"] for row in completed if row["usage"] is not None]
    by_stratum: dict[str, dict[str, Any]] = {}
    for stratum in sorted({str(row["stratum"]) for row in selected}):
        stratum_rows = [row for row in selected if row["stratum"] == stratum]
        by_stratum[stratum] = {
            "planned_cells": len(stratum_rows),
            "completed_cells": sum(row["status"] == "completed" for row in stratum_rows),
            "admitted_cells": sum(_admitted(row) for row in stratum_rows),
            "no_agreement_cells": sum(_no_agreement(row) for row in stratum_rows),
            "excluded_cells": sum(
                row["status"] == "completed" and not _admitted(row) and not _walked_away(row)
                for row in stratum_rows
            ),
            "mean_delta_from_baseline_cents": _mean(
                [
                    _economic_value(row) - float(row["scripted_baseline_developer_equity_npv_cents"])
                    for row in stratum_rows
                    if _economic_value(row) is not None
                ]
            ),
        }
    return {
        "model_id": model_id,
        "planned_cells": planned,
        "completed_cells": len(completed),
        "operational_failure_cells": len(selected) - len(completed),
        "admitted_cells": len(admitted),
        "no_agreement_cells": len(walked),
        "excluded_cells": len(excluded),
        "admission_rate": len(admitted) / planned,
        "no_agreement_rate": len(walked) / planned,
        "no_agreement_reasons": dict(
            sorted(Counter(str(row["outcome"]["termination_reason"]) for row in walked).items())
        ),
        "exclusion_rate": len(excluded) / planned,
        "mean_developer_equity_npv_cents": _mean([_economic_value(row) for row in economic]),
        "mean_delta_from_baseline_cents": _mean(
            [
                _economic_value(row) - float(row["scripted_baseline_developer_equity_npv_cents"])
                for row in economic
            ]
        ),
        "mean_admitted_developer_equity_npv_cents": _mean(
            [float(row["outcome"]["developer_equity_npv_cents"]) for row in admitted]
        ),
        "mean_total_project_npv_cents": _mean(
            [float(row["outcome"]["total_project_npv_cents"]) for row in admitted]
        ),
        "termination_counts": dict(
            sorted(
                Counter(str(row["outcome"]["termination_reason"]) for row in completed).items()
            )
        ),
        "exclusion_reasons": dict(
            sorted(
                Counter(
                    "invalid_action:" + ",".join(row["outcome"]["temporal_violations"])
                    if str(row["outcome"]["termination_reason"]) == "invalid_action"
                    else "temporal_violation"
                    if row["outcome"]["temporal_violations"]
                    else (
                        "constraint_failure:" + ",".join(row["outcome"]["default_reasons"] or ["unfinanced"])
                        if row["outcome"]["project_completed"]
                        else str(row["outcome"]["termination_reason"])
                    )
                    for row in excluded
                ).items()
            )
        ),
        "mean_elapsed_seconds": _mean([float(row["elapsed_seconds"]) for row in selected]),
        "total_provider_calls": sum(int(item["provider_calls_started"]) for item in usage_rows),
        "total_input_tokens": sum(int(item["input_tokens"]) for item in usage_rows),
        "total_output_tokens": sum(int(item["output_tokens"]) for item in usage_rows),
        "reported_cost_usd": sum(float(item["reported_cost_usd"]) for item in usage_rows),
        "complete_panel": complete_panel,
        "route_verified": route_verified,
        "provider_cost_complete": complete_panel,
        "rankable": complete_panel and route_verified,
        "by_stratum": by_stratum,
    }


def _cluster_bootstrap(
    per_world_deltas: Sequence[float], *, draws: int, seed: int
) -> dict[str, Any]:
    if not per_world_deltas:
        return {"mean": None, "ci95": None, "worlds": 0}
    rng = random.Random(seed)
    count = len(per_world_deltas)
    means: list[float] = []
    for _ in range(draws):
        sample = [per_world_deltas[rng.randrange(count)] for _ in range(count)]
        means.append(statistics.fmean(sample))
    means.sort()
    lower = means[int(0.025 * (draws - 1))]
    upper = means[int(0.975 * (draws - 1))]
    return {"mean": statistics.fmean(per_world_deltas), "ci95": [lower, upper], "worlds": count}


def _paired_comparisons(
    contract: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """World-clustered paired differences for every ordered model pair."""

    draws = int(contract["analysis"]["bootstrap_draws"])
    seed = int(contract["analysis"]["bootstrap_seed"])
    model_ids = sorted(contract["models"])
    comparisons: list[dict[str, Any]] = []
    for index, treatment in enumerate(model_ids):
        for control in model_ids[index + 1 :]:
            admission_deltas: list[float] = []
            economic_deltas: list[float] = []
            for case_id in sorted({str(row["case_id"]) for row in rows}):
                world_rows = [row for row in rows if row["case_id"] == case_id]
                treat = [row for row in world_rows if row["model_id"] == treatment]
                ctrl = [row for row in world_rows if row["model_id"] == control]
                if not treat or not ctrl:
                    continue
                admission_deltas.append(
                    statistics.fmean(float(_admitted(row)) for row in treat)
                    - statistics.fmean(float(_admitted(row)) for row in ctrl)
                )
                treat_values = [_economic_value(row) for row in treat]
                ctrl_values = [_economic_value(row) for row in ctrl]
                if all(value is not None for value in treat_values + ctrl_values):
                    economic_deltas.append(
                        statistics.fmean(treat_values) - statistics.fmean(ctrl_values)
                    )
            comparisons.append(
                {
                    "treatment": treatment,
                    "control": control,
                    "admission_rate_difference": _cluster_bootstrap(
                        admission_deltas, draws=draws, seed=seed
                    ),
                    "developer_equity_npv_difference_cents": _cluster_bootstrap(
                        economic_deltas, draws=draws, seed=seed + 1
                    ),
                    "worlds_with_complete_economic_pairs": len(economic_deltas),
                }
            )
    return comparisons


def summarize(
    contract: Mapping[str, Any], design: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    completed = [row for row in rows if row["status"] == "completed"]
    operational = [row for row in rows if row["status"] != "completed"]
    reported_cost = sum(
        float(row["usage"]["reported_cost_usd"]) for row in completed if row["usage"] is not None
    )
    planned_per_model = design["independent_cluster_count"] * design["paired_seed_count"]
    model_summaries = [
        _model_summary(model_id, rows, planned_per_model) for model_id in sorted(contract["models"])
    ]
    rankable = [item for item in model_summaries if item["rankable"]]
    leaderboard = sorted(
        rankable,
        key=lambda item: (
            -(item["mean_developer_equity_npv_cents"] or float("-inf")),
            -item["admission_rate"],
            item["reported_cost_usd"],
        ),
    )
    return _sealed(
        {
            "schema_version": "aeread.datacenter_world_campaign_summary/0.1",
            "campaign_id": contract["campaign_id"],
            "contract_sha256": _sha256(contract),
            "design_sha256": design["artifact_sha256"],
            "campaign_driver_sha256": design["campaign_driver_sha256"],
            "pack_sha256": design["pack_sha256"],
            "claim_status": contract["claim_status"],
            "independent_cluster_count": design["independent_cluster_count"],
            "planned_cells": len(rows),
            "completed_cells": len(completed),
            "operational_failure_cells": len(operational),
            "failure_fraction": len(operational) / len(rows) if rows else None,
            "failure_conditions": dict(
                sorted(Counter(row["failure"]["failure_condition"] for row in operational).items())
            ),
            "reported_cost_usd": reported_cost,
            "provider_cost_complete": not operational,
            "cost_qualifier": "exact" if not operational else "lower_bound",
            "campaign_max_cost_usd": contract["execution"]["campaign_max_cost_usd"],
            "within_declared_campaign_cost_ceiling": reported_cost
            <= float(contract["execution"]["campaign_max_cost_usd"]),
            "ranking_basis": (
                "mean developer equity NPV over admitted stacks and declared walk-aways; "
                "no-agreement episodes (walk, reject, rounds exhausted) score the declared "
                "outside option; excluded cells (constraint, contract, temporal, or invalid-"
                "action failures) are admission failures reported separately, not low scores"
            ),
            "model_summaries": model_summaries,
            "leaderboard": [
                {
                    "rank": index + 1,
                    "model_id": item["model_id"],
                    "mean_developer_equity_npv_cents": item["mean_developer_equity_npv_cents"],
                    "mean_delta_from_baseline_cents": item["mean_delta_from_baseline_cents"],
                    "admission_rate": item["admission_rate"],
                    "no_agreement_rate": item["no_agreement_rate"],
                    "exclusion_rate": item["exclusion_rate"],
                    "mean_elapsed_seconds": item["mean_elapsed_seconds"],
                    "total_provider_calls": item["total_provider_calls"],
                    "total_input_tokens": item["total_input_tokens"],
                    "total_output_tokens": item["total_output_tokens"],
                    "reported_cost_usd": item["reported_cost_usd"],
                    "operational_failure_cells": item["operational_failure_cells"],
                }
                for index, item in enumerate(leaderboard)
            ],
            "unranked_model_ids": [
                item["model_id"] for item in model_summaries if not item["rankable"]
            ],
            "paired_comparisons": _paired_comparisons(contract, rows),
            "winner_claim_allowed": False,
            "inferential_model_ranking_allowed": False,
            "causal_condition_effect_allowed": False,
        }
    )


def _fmt_cents(value: float | None) -> str:
    return "n/a" if value is None else f"{value / 100:,.0f}"


def _fmt_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.0f}%"


def render_leaderboard(summary: Mapping[str, Any]) -> str:
    lines = [
        f"# {summary['campaign_id']}",
        "",
        f"Claim status: `{summary['claim_status']}`. Worlds (clusters): "
        f"{summary['independent_cluster_count']}. Cells: {summary['completed_cells']} of "
        f"{summary['planned_cells']} completed. Reported cost: "
        f"${summary['reported_cost_usd']:.4f} ({summary['cost_qualifier']}).",
        "",
        f"Ranking basis: {summary['ranking_basis']}.",
        "",
        "| Rank | Model | Mean dev NPV ($) | Delta vs scripted ($) | Admitted | No deal | Excluded | Failures | Calls | In tok | Out tok | Cost ($) | Mean s |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["leaderboard"]:
        lines.append(
            f"| {row['rank']} | {row['model_id']} | {_fmt_cents(row['mean_developer_equity_npv_cents'])} | "
            f"{_fmt_cents(row['mean_delta_from_baseline_cents'])} | {_fmt_rate(row['admission_rate'])} | "
            f"{_fmt_rate(row['no_agreement_rate'])} | {_fmt_rate(row['exclusion_rate'])} | "
            f"{row['operational_failure_cells']} | {row['total_provider_calls']} | "
            f"{row['total_input_tokens']} | {row['total_output_tokens']} | "
            f"{row['reported_cost_usd']:.4f} | {row['mean_elapsed_seconds']:.1f} |"
        )
    if summary["unranked_model_ids"]:
        lines += ["", "Unranked (incomplete panel or unverified route): " + ", ".join(summary["unranked_model_ids"])]
    lines += ["", "## Admission by stratum", ""]
    strata = sorted(
        {stratum for item in summary["model_summaries"] for stratum in item["by_stratum"]}
    )
    lines.append("| Model | " + " | ".join(strata) + " |")
    lines.append("|---|" + "---:|" * len(strata))
    for item in summary["model_summaries"]:
        cells = []
        for stratum in strata:
            block = item["by_stratum"].get(stratum)
            cells.append(
                "n/a" if block is None else f"{block['admitted_cells']}/{block['planned_cells']}"
            )
        lines.append(f"| {item['model_id']} | " + " | ".join(cells) + " |")
    lines += ["", "## Paired differences (world-clustered bootstrap, 95% interval)", ""]
    lines.append("| Treatment | Control | Admission rate diff | Dev NPV diff ($) | Worlds |")
    lines.append("|---|---|---:|---:|---:|")
    for item in summary["paired_comparisons"]:
        adm = item["admission_rate_difference"]
        eco = item["developer_equity_npv_difference_cents"]
        adm_text = (
            "n/a" if adm["mean"] is None else f"{adm['mean']:+.2f} [{adm['ci95'][0]:+.2f}, {adm['ci95'][1]:+.2f}]"
        )
        eco_text = (
            "n/a"
            if eco["mean"] is None
            else f"{eco['mean'] / 100:+,.0f} [{eco['ci95'][0] / 100:+,.0f}, {eco['ci95'][1] / 100:+,.0f}]"
        )
        lines.append(
            f"| {item['treatment']} | {item['control']} | {adm_text} | {eco_text} | "
            f"{item['worlds_with_complete_economic_pairs']} |"
        )
    lines += [
        "",
        "No winner claim, inferential model ranking, or causal condition effect is "
        "licensed by this artifact.",
        "",
    ]
    return "\n".join(lines)


def _assert_public(name: str, text: str) -> None:
    lowered = text.lower()
    for token in PROHIBITED_PUBLIC_TEXT:
        if token in lowered:
            raise ValueError(f"{name} contains prohibited public text: {token}")


def publish(
    *,
    run_root: Path | str = DEFAULT_RUN_ROOT,
    publication_root: Path | str = DEFAULT_PUBLICATION_ROOT,
) -> dict[str, Any]:
    """Copy sealed public artifacts and the rendered leaderboard into evidence/."""

    root = Path(run_root)
    target = Path(publication_root)
    design = _read_sealed(root / "design.json")
    summary = _read_sealed(root / "live" / "summary.json")
    provider_free = _read_sealed(root / "provider_free_validation" / "summary.json")
    rows = [
        _read_sealed(path) for path in sorted((root / "live").glob("*/result.json"))
    ]
    public_rows = [
        {
            key: value
            for key, value in row.items()
            if key not in {"case_file"}
        }
        for row in rows
    ]
    files = {
        "design.json": json.dumps(design, indent=2, sort_keys=True) + "\n",
        "provider_free_validation.json": json.dumps(provider_free, indent=2, sort_keys=True) + "\n",
        "summary.json": json.dumps(summary, indent=2, sort_keys=True) + "\n",
        "cells.jsonl": "".join(
            canonical_json_bytes(row).decode("utf-8") + "\n" for row in public_rows
        ),
        "leaderboard.md": render_leaderboard(summary),
    }
    target.mkdir(parents=True, exist_ok=True)
    manifest_files: dict[str, Any] = {}
    for name, text in files.items():
        _assert_public(name, text)
        payload = text.encode("utf-8")
        (target / name).write_bytes(payload)
        manifest_files[name] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    manifest = _sealed(
        {
            "schema_version": "aeread.datacenter_world_publication/0.1",
            "campaign_id": summary["campaign_id"],
            "summary_sha256": summary["artifact_sha256"],
            "design_sha256": design["artifact_sha256"],
            "source_receipt_sha256s": sorted(row["receipt_sha256"] for row in rows),
            "files": manifest_files,
        }
    )
    _atomic_write(target / "publication_manifest.json", manifest)
    return manifest


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


async def run_campaign(
    *,
    contract_path: Path | str = DEFAULT_CONTRACT_PATH,
    run_root: Path | str = DEFAULT_RUN_ROOT,
    pack_root: Path | str = DEFAULT_PACK_ROOT,
    stop_after: str = "live",
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
    cell_filter: Callable[[Mapping[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    root = Path(run_root)
    pack = Path(pack_root)
    design = build_design(contract, pack_root=pack)
    _atomic_write(root / "design.json", design)
    if stop_after == "design":
        return design

    provider_free = await run_provider_free_gate(contract, run_root=root, pack_root=pack)
    if provider_free["status"] != "passed":
        raise ValueError("provider-free campaign gate failed")
    if stop_after == "provider_free":
        return provider_free

    profile_admission = run_profile_admission_gate(
        contract, design=design, run_root=root, pack_root=pack
    )
    if profile_admission["status"] != "passed":
        raise ValueError("profile-admission campaign gate failed")
    if stop_after == "profile_admission":
        return profile_admission

    concurrency = asyncio.Semaphore(int(contract["execution"]["concurrency"]))
    route_locks = {
        str(model["provider"]): asyncio.Semaphore(1) for model in contract["models"].values()
    }

    cooldown = float(contract["execution"]["provider_cooldown_seconds_after_cell"])

    async def execute(cell: Mapping[str, Any]) -> dict[str, Any]:
        provider_name = str(contract["models"][cell["model_id"]]["provider"])
        async with concurrency, route_locks[provider_name]:
            result = await _run_live_cell(
                contract, cell, run_root=root, pack_root=pack, provider=provider_factory()
            )
            if cooldown > 0.0 and result["status"] != "resumed":
                # Hold the route lock so the provider sees a quiet gap between cells.
                await asyncio.sleep(cooldown)
            return result

    selected = [
        cell for cell in design["cells"] if cell_filter is None or cell_filter(cell)
    ]
    rows = await asyncio.gather(*(execute(cell) for cell in selected))
    if len(rows) != len(design["cells"]):
        return _sealed(
            {
                "schema_version": "aeread.datacenter_world_campaign_partial/0.1",
                "campaign_id": contract["campaign_id"],
                "status": "partial",
                "executed_cells": len(rows),
                "planned_cells": len(design["cells"]),
                "rows": [dict(row) for row in rows],
            }
        )
    summary = summarize(contract, design, rows)
    _atomic_write(root / "live" / "summary.json", summary)
    (root / "live" / "leaderboard.md").write_text(render_leaderboard(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT_PATH)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--pack-root", type=Path, default=DEFAULT_PACK_ROOT)
    parser.add_argument(
        "--stop-after",
        choices=("design", "provider_free", "profile_admission", "live"),
        default="live",
    )
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--publication-root", type=Path, default=DEFAULT_PUBLICATION_ROOT)
    arguments = parser.parse_args(argv)
    result = asyncio.run(
        run_campaign(
            contract_path=arguments.contract,
            run_root=arguments.run_root,
            pack_root=arguments.pack_root,
            stop_after=arguments.stop_after,
        )
    )
    if arguments.publish and arguments.stop_after == "live":
        result = publish(run_root=arguments.run_root, publication_root=arguments.publication_root)
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


__all__ = [
    "CAMPAIGN_ID",
    "DEFAULT_CONTRACT_PATH",
    "DEFAULT_RUN_ROOT",
    "build_design",
    "load_contract",
    "load_pack",
    "publish",
    "render_leaderboard",
    "run_campaign",
    "summarize",
]


if __name__ == "__main__":
    raise SystemExit(main())
