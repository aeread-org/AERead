"""Frozen V2 data-center interaction campaign.

The campaign pairs a live-developer condition with homogeneous model-to-model
negotiation. All cells share one curated project, so results describe route and
interaction behavior on that project rather than population-level model rank.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
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
    build_stack_model_to_model_setup,
    build_stack_openrouter_setup,
    finalize_stack_execution,
    finalize_stack_failure,
    load_stack_case,
    replay_stack_receipt,
    run_stack_model_to_model,
    run_stack_offline,
    run_stack_openrouter,
)


CONTRACT_SCHEMA_VERSION = "aeread.datacenter_stack_campaign_contract/0.1"
CAMPAIGN_ID = "datacenter_development_v2_interaction_v1"
CONDITIONS = ("controlled_developer", "homogeneous_model_to_model")
LIVE_PROFILE_COUNT = {
    "controlled_developer": 1,
    "homogeneous_model_to_model": 6,
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT_PATH = REPOSITORY_ROOT / "configs" / f"{CAMPAIGN_ID}.json"
DEFAULT_RUN_ROOT = REPOSITORY_ROOT / "runs" / CAMPAIGN_ID


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
    payload = canonical_json_bytes(value) + b"\n"
    if path.exists():
        if path.is_file() and not path.is_symlink() and path.read_bytes() == payload:
            return
        raise ValueError(f"refusing to overwrite different campaign bytes: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise ValueError(f"campaign output parent must not be a symlink: {path.parent}")
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_contract(path: Path | str = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    contract = _read_json(Path(path))
    expected_fields = {
        "schema_version",
        "campaign_id",
        "family_id",
        "scope_version",
        "case_id",
        "expected_case_sha256",
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
    if contract["claim_status"] != "single_curated_project_interaction_diagnostic_only":
        raise ValueError("campaign must retain its diagnostic claim boundary")
    if tuple(contract["conditions"]) != CONDITIONS:
        raise ValueError("campaign interaction conditions differ")

    seeds = contract["inference_seeds"]
    if (
        not isinstance(seeds, list)
        or len(seeds) < 3
        or len(seeds) != len(set(seeds))
        or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seeds)
    ):
        raise ValueError("campaign requires at least three unique non-negative seeds")

    models = contract["models"]
    if not isinstance(models, dict) or set(models) != {"glm53_reka", "mistral_small"}:
        raise ValueError("campaign model panel differs")
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
        "pricing",
        "max_prompt_price_per_million",
        "max_completion_price_per_million",
    }
    for model_id, model in models.items():
        if not isinstance(model, dict) or set(model) != route_fields:
            raise ValueError(f"{model_id}: model route fields differ")
        if model["access_class"] != "open_source":
            raise ValueError(f"{model_id}: campaign is restricted to open-source models")
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
    worst_case = (
        len(seeds)
        * len(models)
        * sum(LIVE_PROFILE_COUNT.values())
        * float(execution["max_cost_usd_per_live_profile"])
    )
    if worst_case > float(execution["campaign_max_cost_usd"]):
        raise ValueError("per-profile cost ceilings exceed the campaign cost ceiling")

    analysis = contract["analysis"]
    if analysis.get("independent_cluster_count") != 1:
        raise ValueError("campaign must retain one curated project cluster")
    if analysis.get("missingness") != "report_separately":
        raise ValueError("campaign must report operational missingness separately")
    for field in (
        "winner_claim_allowed",
        "inferential_model_ranking_allowed",
        "causal_condition_effect_allowed",
    ):
        if analysis.get(field) is not False:
            raise ValueError(f"analysis.{field} must be false")
    return contract


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


def _cells(contract: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "cell_key": f"{condition}__{model_id}__seed_{seed}",
            "condition": condition,
            "model_id": model_id,
            "inference_seed": seed,
        }
        for seed in contract["inference_seeds"]
        for model_id in sorted(contract["models"])
        for condition in contract["conditions"]
    )


def _setup(contract: Mapping[str, Any], cell: Mapping[str, Any]) -> Any:
    controls = contract["execution"]
    route = _route(contract["models"][cell["model_id"]])
    kwargs = {
        "seed": int(cell["inference_seed"]),
        "max_output_tokens": int(controls["max_output_tokens_per_action"]),
        "timeout_seconds": float(controls["timeout_seconds_per_action"]),
        "max_cost_usd": float(controls["max_cost_usd_per_live_profile"]),
    }
    if cell["condition"] == "controlled_developer":
        return build_stack_openrouter_setup("v2", route, **kwargs)
    if cell["condition"] == "homogeneous_model_to_model":
        return build_stack_model_to_model_setup("v2", route, **kwargs)
    raise ValueError(f"unknown interaction condition: {cell['condition']}")


def build_design(contract: Mapping[str, Any]) -> dict[str, Any]:
    case = load_stack_case("v2")
    if case.case_id != contract["case_id"]:
        raise ValueError("case ID differs from the frozen campaign contract")
    if case.content_sha256 != contract["expected_case_sha256"]:
        raise ValueError("case hash differs from the frozen campaign contract")
    per_profile = float(contract["execution"]["max_cost_usd_per_live_profile"])
    cells: list[dict[str, Any]] = []
    for cell in _cells(contract):
        setup = _setup(contract, cell)
        plan_cell = setup.plan.cells[0]
        live_profiles = sum(
            profile.model.provider == "openrouter"
            for profile in setup.plan.agent_profiles
        )
        expected_live_profiles = LIVE_PROFILE_COUNT[str(cell["condition"])]
        if live_profiles != expected_live_profiles:
            raise ValueError(f"live profile count drift for {cell['cell_key']}")
        cells.append(
            {
                **cell,
                "run_plan_id": setup.plan.run_plan_id,
                "run_plan_sha256": setup.plan.plan_sha256,
                "cell_id": plan_cell.cell_id,
                "case_id": plan_cell.case_id,
                "case_sha256": plan_cell.case_sha256,
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
            "schema_version": "aeread.datacenter_stack_campaign_design/0.1",
            "campaign_id": contract["campaign_id"],
            "contract_sha256": _sha256(contract),
            "campaign_driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "case_id": case.case_id,
            "case_sha256": case.content_sha256,
            "independent_cluster_count": 1,
            "planned_cells": len(cells),
            "paired_seed_count": len(contract["inference_seeds"]),
            "worst_case_declared_cost_usd": declared_maximum,
            "campaign_max_cost_usd": campaign_maximum,
            "cells": cells,
        }
    )


async def run_provider_free_gate(
    contract: Mapping[str, Any], *, run_root: Path
) -> dict[str, Any]:
    summary_path = run_root / "provider_free_validation" / "summary.json"
    if summary_path.exists():
        return _read_sealed(summary_path)
    evidence_root = run_root / "provider_free_validation" / "evidence"
    setup, execution = await run_stack_offline("v2", evidence_root=evidence_root)
    receipt = finalize_stack_execution(setup=setup, execution=execution)
    verify_evaluation_receipt(receipt)
    replayed = replay_stack_receipt(
        setup=setup,
        receipt=receipt,
        evidence_root=evidence_root,
    )
    verify_evaluation_receipt(replayed)
    outcome = execution.episode_result.outcome
    passed = (
        receipt.inclusion_status == "included"
        and bool(outcome["project_completed"])
        and bool(outcome["binding_contract_integrity"])
        and bool(outcome["project_constraints_satisfied"])
        and not outcome["temporal_violations"]
    )
    summary = _sealed(
        {
            "schema_version": "aeread.datacenter_stack_provider_free_gate/0.1",
            "campaign_id": contract["campaign_id"],
            "contract_sha256": _sha256(contract),
            "status": "passed" if passed else "failed",
            "case_sha256": setup.case.content_sha256,
            "logical_action_count": execution.episode_result.logical_action_count,
            "receipt_sha256": receipt.receipt_sha256,
            "replay_verified": replayed == receipt,
        }
    )
    _atomic_write(summary_path, summary)
    return summary


def run_profile_admission_gate(
    contract: Mapping[str, Any], *, design: Mapping[str, Any], run_root: Path
) -> dict[str, Any]:
    summary_path = run_root / "profile_admission" / "summary.json"
    if summary_path.exists():
        return _read_sealed(summary_path)
    design_by_key = {cell["cell_key"]: cell for cell in design["cells"]}
    admitted: list[str] = []
    for cell in _cells(contract):
        setup = _setup(contract, cell)
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
            "schema_version": "aeread.datacenter_stack_profile_gate/0.1",
            "campaign_id": contract["campaign_id"],
            "contract_sha256": _sha256(contract),
            "status": "passed",
            "admitted_cells": admitted,
        }
    )
    _atomic_write(summary_path, summary)
    return summary


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


async def _run_live_cell(
    contract: Mapping[str, Any],
    design_cell: Mapping[str, Any],
    *,
    run_root: Path,
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

    setup = _setup(contract, design_cell)
    if (
        setup.plan.plan_sha256 != design_cell["run_plan_sha256"]
        or setup.plan.cells[0].cell_id != design_cell["cell_id"]
    ):
        raise ValueError(f"live plan drift for {design_cell['cell_key']}")
    model = contract["models"][design_cell["model_id"]]
    route = _route(model)
    controls = contract["execution"]
    run_kwargs = {
        "evidence_root": cell_root / "evidence",
        "seed": int(design_cell["inference_seed"]),
        "max_output_tokens": int(controls["max_output_tokens_per_action"]),
        "timeout_seconds": float(controls["timeout_seconds_per_action"]),
        "max_cost_usd": float(controls["max_cost_usd_per_live_profile"]),
        "provider": provider,
    }
    started = time.perf_counter()
    try:
        if design_cell["condition"] == "controlled_developer":
            _, execution = await run_stack_openrouter("v2", route, **run_kwargs)
        else:
            _, execution = await run_stack_model_to_model("v2", route, **run_kwargs)
        receipt = finalize_stack_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_stack_receipt(
            setup=setup,
            receipt=receipt,
            evidence_root=cell_root / "evidence",
        )
        verify_evaluation_receipt(replayed)
        result = _sealed(
            {
                "schema_version": "aeread.datacenter_stack_live_cell/0.1",
                "campaign_id": contract["campaign_id"],
                **dict(design_cell),
                "status": "completed",
                "receipt_status": receipt.status,
                "inclusion_status": receipt.inclusion_status,
                "receipt_sha256": receipt.receipt_sha256,
                "replay_verified": replayed == receipt,
                "elapsed_seconds": time.perf_counter() - started,
                "usage": _call_usage(execution),
                "outcome": _plain(execution.episode_result.outcome),
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
                "schema_version": "aeread.datacenter_stack_live_cell/0.1",
                "campaign_id": contract["campaign_id"],
                **dict(design_cell),
                "status": "operational_failure",
                "receipt_status": receipt.status,
                "inclusion_status": receipt.inclusion_status,
                "receipt_sha256": receipt.receipt_sha256,
                "replay_verified": False,
                "elapsed_seconds": time.perf_counter() - started,
                "usage": None,
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


def _group_summary(
    model_id: str, condition: str, rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    selected = [
        row
        for row in rows
        if row["model_id"] == model_id and row["condition"] == condition
    ]
    completed = [row for row in selected if row["status"] == "completed"]
    included = [row for row in completed if row["inclusion_status"] == "included"]
    developer_npvs = [
        float(row["outcome"]["developer_equity_npv_cents"])
        for row in included
    ]
    total_npvs = [
        float(row["outcome"]["total_project_npv_cents"])
        for row in included
    ]
    return {
        "model_id": model_id,
        "condition": condition,
        "planned_cells": len(selected),
        "completed_cells": len(completed),
        "included_cells": len(included),
        "operational_failure_cells": len(selected) - len(completed),
        "completion_rate": len(completed) / len(selected),
        "project_completion_rate": (
            sum(bool(row["outcome"]["project_completed"]) for row in included)
            / len(included)
            if included
            else None
        ),
        "mean_developer_equity_npv_cents": (
            statistics.fmean(developer_npvs) if developer_npvs else None
        ),
        "mean_total_project_npv_cents": (
            statistics.fmean(total_npvs) if total_npvs else None
        ),
        "termination_counts": dict(
            sorted(
                Counter(
                    str(row["outcome"]["termination_reason"])
                    for row in included
                ).items()
            )
        ),
        "reported_cost_usd": sum(
            float(row["usage"]["reported_cost_usd"])
            for row in completed
            if row["usage"] is not None
        ),
    }


def summarize(
    contract: Mapping[str, Any],
    design: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    completed = [row for row in rows if row["status"] == "completed"]
    operational = [row for row in rows if row["status"] != "completed"]
    reported_cost = sum(
        float(row["usage"]["reported_cost_usd"])
        for row in completed
        if row["usage"] is not None
    )
    return _sealed(
        {
            "schema_version": "aeread.datacenter_stack_campaign_summary/0.1",
            "campaign_id": contract["campaign_id"],
            "contract_sha256": _sha256(contract),
            "design_sha256": design["artifact_sha256"],
            "campaign_driver_sha256": design["campaign_driver_sha256"],
            "claim_status": contract["claim_status"],
            "independent_cluster_count": 1,
            "planned_cells": len(rows),
            "completed_cells": len(completed),
            "operational_failure_cells": len(operational),
            "failure_fraction": len(operational) / len(rows),
            "failure_conditions": [
                row["failure"]["failure_condition"] for row in operational
            ],
            "reported_cost_usd": reported_cost,
            "provider_cost_complete": not operational,
            "cost_qualifier": "exact" if not operational else "lower_bound",
            "campaign_max_cost_usd": contract["execution"]["campaign_max_cost_usd"],
            "within_declared_campaign_cost_ceiling": reported_cost
            <= float(contract["execution"]["campaign_max_cost_usd"]),
            "group_summaries": [
                _group_summary(model_id, condition, rows)
                for model_id in sorted(contract["models"])
                for condition in contract["conditions"]
            ],
            "winner_claim_allowed": False,
            "inferential_model_ranking_allowed": False,
            "causal_condition_effect_allowed": False,
        }
    )


async def run_campaign(
    *,
    contract_path: Path | str = DEFAULT_CONTRACT_PATH,
    run_root: Path | str = DEFAULT_RUN_ROOT,
    stop_after: str = "live",
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    root = Path(run_root)
    design = build_design(contract)
    _atomic_write(root / "design.json", design)
    if stop_after == "design":
        return design

    provider_free = await run_provider_free_gate(contract, run_root=root)
    if provider_free["status"] != "passed":
        raise ValueError("provider-free campaign gate failed")
    if stop_after == "provider_free":
        return provider_free

    profile_admission = run_profile_admission_gate(
        contract,
        design=design,
        run_root=root,
    )
    if profile_admission["status"] != "passed":
        raise ValueError("profile-admission campaign gate failed")
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
    "CONDITIONS",
    "DEFAULT_CONTRACT_PATH",
    "DEFAULT_RUN_ROOT",
    "build_design",
    "load_contract",
    "main",
    "run_campaign",
    "summarize",
]
