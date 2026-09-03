"""Gated reliability campaign for the data-center terms classifier.

The campaign is intentionally narrow: two exact OpenRouter routes receive the
same one synthetic project under five paired inference seeds. Repeated seeds
measure response and operational stability only; they are not independent
projects and cannot support a model-winner claim.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import statistics
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import OpenRouterChatClient, TokenPricing
from aeread.shared_runner.task.receipts import verify_evaluation_receipt

from .cases import load_cases
from .runner import (
    OpenRouterRoute,
    build_offline_setup,
    build_openrouter_setup,
    finalize_datacenter_terms_execution,
    finalize_datacenter_terms_failure,
    replay_datacenter_terms_receipt,
    run_fixture_response,
    run_openrouter,
)


CONTRACT_SCHEMA_VERSION = "aeread.datacenter_terms_reliability_contract/0.1"
CAMPAIGN_ID = "datacenter_development_terms_reliability_v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT_PATH = (
    REPOSITORY_ROOT / "configs" / "datacenter_development_terms_reliability_v1.json"
)
DEFAULT_RUN_ROOT = REPOSITORY_ROOT / "runs" / CAMPAIGN_ID


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sealed(value: Mapping[str, Any]) -> dict[str, Any]:
    core = {key: item for key, item in value.items() if key != "artifact_sha256"}
    return {**core, "artifact_sha256": _sha256(core)}


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
        "case_slug",
        "expected_case_sha256",
        "claim_status",
        "inference_seeds",
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
    if contract["family_id"] != "datacenter_development_terms_v1":
        raise ValueError("campaign family differs")
    if contract["claim_status"] != "single_synthetic_project_reliability_only":
        raise ValueError("campaign must retain its diagnostic claim boundary")
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
    for model_id, model in models.items():
        required = {
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
        if not isinstance(model, dict) or set(model) != required:
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
    if set(execution) != {
        "harness",
        "max_output_tokens",
        "timeout_seconds",
        "max_cost_usd_per_cell",
        "campaign_max_cost_usd",
        "concurrency",
        "max_action_attempts",
        "sdk_retries",
        "provider_fallbacks",
    }:
        raise ValueError("campaign execution fields differ")
    if execution != {
        **execution,
        "harness": "minimal_chat/1.0",
        "max_action_attempts": 1,
        "sdk_retries": 0,
        "provider_fallbacks": False,
    }:
        raise ValueError("campaign retry, fallback, or harness controls differ")
    for key in ("max_cost_usd_per_cell", "campaign_max_cost_usd"):
        value = execution.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"execution.{key} must be positive")
    if (
        isinstance(execution["concurrency"], bool)
        or not isinstance(execution["concurrency"], int)
        or execution["concurrency"] < 1
    ):
        raise ValueError("execution.concurrency must be a positive integer")
    planned_cells = len(seeds) * len(models)
    worst_case = planned_cells * float(execution["max_cost_usd_per_cell"])
    if worst_case > float(execution["campaign_max_cost_usd"]):
        raise ValueError("per-cell cost ceilings exceed the campaign cost ceiling")
    analysis = contract["analysis"]
    if analysis.get("independent_cluster_count") != 1:
        raise ValueError("campaign must retain one synthetic project cluster")
    if analysis.get("missingness") != "report_separately":
        raise ValueError("campaign must report operational missingness separately")
    if analysis.get("winner_claim_allowed") is not False:
        raise ValueError("campaign cannot allow a winner claim")
    if analysis.get("inferential_model_ranking_allowed") is not False:
        raise ValueError("campaign cannot allow inferential ranking")
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
            "cell_key": f"{model_id}__seed_{seed}",
            "model_id": model_id,
            "inference_seed": seed,
        }
        for seed in contract["inference_seeds"]
        for model_id in sorted(contract["models"])
    )


def build_design(contract: Mapping[str, Any]) -> dict[str, Any]:
    case = load_cases(case_slugs=(str(contract["case_slug"]),))[0]
    if case.content_sha256 != contract["expected_case_sha256"]:
        raise ValueError("case hash differs from the frozen campaign contract")
    execution = contract["execution"]
    cells: list[dict[str, Any]] = []
    for cell in _cells(contract):
        model = contract["models"][cell["model_id"]]
        setup = build_openrouter_setup(
            _route(model),
            seed=cell["inference_seed"],
            case_slug=str(contract["case_slug"]),
            max_output_tokens=int(execution["max_output_tokens"]),
            timeout_seconds=float(execution["timeout_seconds"]),
            max_cost_usd=float(execution["max_cost_usd_per_cell"]),
        )
        plan_cell = setup.plan.cells[0]
        cells.append(
            {
                **cell,
                "run_plan_id": setup.plan.run_plan_id,
                "run_plan_sha256": setup.plan.plan_sha256,
                "cell_id": plan_cell.cell_id,
                "case_id": plan_cell.case_id,
                "case_sha256": plan_cell.case_sha256,
                "profile_id": setup.plan.agent_profiles[0].profile_id,
            }
        )
    return _sealed(
        {
            "schema_version": "aeread.datacenter_terms_reliability_design/0.1",
            "campaign_id": contract["campaign_id"],
            "contract_sha256": _sha256(contract),
            "campaign_driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "case_id": case.case_id,
            "case_sha256": case.content_sha256,
            "independent_cluster_count": 1,
            "planned_cells": len(cells),
            "paired_seed_count": len(contract["inference_seeds"]),
            "worst_case_declared_cost_usd": (
                len(cells) * float(execution["max_cost_usd_per_cell"])
            ),
            "campaign_max_cost_usd": float(execution["campaign_max_cost_usd"]),
            "cells": cells,
        }
    )


async def run_provider_free_gate(
    contract: Mapping[str, Any],
    *,
    run_root: Path,
) -> dict[str, Any]:
    summary_path = run_root / "provider_free_validation" / "summary.json"
    if summary_path.exists():
        return _read_sealed(summary_path)
    case = load_cases(case_slugs=(str(contract["case_slug"]),))[0]
    gold = case.payload["oracle"]["gold"]
    response = {
        "case_id": case.case_id,
        "states": gold["states"],
        "amounts": gold["amounts"],
        "actions": gold["required_actions"],
        "claims": gold["required_claims"],
        "evidence_ids": gold["required_evidence_ids"],
        "external_actions_attempted": [],
    }
    evidence_root = run_root / "provider_free_validation" / "evidence"
    setup = build_offline_setup(case_slug=str(contract["case_slug"]))
    execution = await run_fixture_response(
        canonical_json_bytes(response).decode("utf-8"),
        evidence_root=evidence_root,
        case_slug=str(contract["case_slug"]),
    )
    receipt = finalize_datacenter_terms_execution(setup=setup, execution=execution)
    verify_evaluation_receipt(receipt)
    replayed = replay_datacenter_terms_receipt(
        setup=setup,
        receipt=receipt,
        evidence_root=evidence_root,
    )
    verify_evaluation_receipt(replayed)
    outcome = execution.episode_result.outcome
    summary = _sealed(
        {
            "schema_version": "aeread.datacenter_terms_provider_free_gate/0.1",
            "campaign_id": contract["campaign_id"],
            "contract_sha256": _sha256(contract),
            "status": "passed" if outcome["score"] == 1.0 else "failed",
            "case_sha256": case.content_sha256,
            "score": outcome["score"],
            "receipt_sha256": receipt.receipt_sha256,
            "replay_verified": True,
        }
    )
    _atomic_write(summary_path, summary)
    return summary


def run_profile_admission_gate(
    contract: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
    run_root: Path,
) -> dict[str, Any]:
    summary_path = run_root / "profile_admission" / "summary.json"
    if summary_path.exists():
        return _read_sealed(summary_path)
    design_by_key = {cell["cell_key"]: cell for cell in design["cells"]}
    admitted: list[str] = []
    for cell in _cells(contract):
        model = contract["models"][cell["model_id"]]
        execution = contract["execution"]
        setup = build_openrouter_setup(
            _route(model),
            seed=cell["inference_seed"],
            case_slug=str(contract["case_slug"]),
            max_output_tokens=int(execution["max_output_tokens"]),
            timeout_seconds=float(execution["timeout_seconds"]),
            max_cost_usd=float(execution["max_cost_usd_per_cell"]),
        )
        expected = design_by_key[cell["cell_key"]]
        if (
            setup.plan.plan_sha256 != expected["run_plan_sha256"]
            or setup.plan.cells[0].cell_id != expected["cell_id"]
            or not all(item.admitted for item in setup.plan.profile_admissions)
        ):
            raise ValueError(f"profile admission drift for {cell['cell_key']}")
        admitted.append(cell["cell_key"])
    summary = _sealed(
        {
            "schema_version": "aeread.datacenter_terms_profile_gate/0.1",
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
        raise ValueError(
            f"refusing to replace incomplete live cell {design_cell['cell_key']}"
        )
    model = contract["models"][design_cell["model_id"]]
    execution_controls = contract["execution"]
    route = _route(model)
    setup = build_openrouter_setup(
        route,
        seed=int(design_cell["inference_seed"]),
        case_slug=str(contract["case_slug"]),
        max_output_tokens=int(execution_controls["max_output_tokens"]),
        timeout_seconds=float(execution_controls["timeout_seconds"]),
        max_cost_usd=float(execution_controls["max_cost_usd_per_cell"]),
    )
    if (
        setup.plan.plan_sha256 != design_cell["run_plan_sha256"]
        or setup.plan.cells[0].cell_id != design_cell["cell_id"]
    ):
        raise ValueError(f"live plan drift for {design_cell['cell_key']}")
    started = time.perf_counter()
    try:
        _, execution = await run_openrouter(
            route,
            evidence_root=cell_root / "evidence",
            seed=int(design_cell["inference_seed"]),
            max_output_tokens=int(execution_controls["max_output_tokens"]),
            timeout_seconds=float(execution_controls["timeout_seconds"]),
            max_cost_usd=float(execution_controls["max_cost_usd_per_cell"]),
            provider=provider,
        )
        receipt = finalize_datacenter_terms_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_datacenter_terms_receipt(
            setup=setup,
            receipt=receipt,
            evidence_root=cell_root / "evidence",
        )
        verify_evaluation_receipt(replayed)
        outcome = dict(execution.episode_result.outcome)
        result = _sealed(
            {
                "schema_version": "aeread.datacenter_terms_live_cell/0.1",
                "campaign_id": contract["campaign_id"],
                **dict(design_cell),
                "status": "completed",
                "receipt_status": receipt.status,
                "inclusion_status": receipt.inclusion_status,
                "receipt_sha256": receipt.receipt_sha256,
                "replay_verified": True,
                "elapsed_seconds": time.perf_counter() - started,
                "usage": _call_usage(execution),
                "metrics": outcome,
                "parsed_output": (
                    execution.episode_result.terminal.get("report")
                    if isinstance(execution.episode_result.terminal, Mapping)
                    else None
                ),
                "failure": None,
            }
        )
    except Exception as error:
        receipt = finalize_datacenter_terms_failure(
            setup=setup,
            cell_id=setup.plan.cells[0].cell_id,
            evidence_root=cell_root / "evidence",
            error=error,
        )
        verify_evaluation_receipt(receipt)
        result = _sealed(
            {
                "schema_version": "aeread.datacenter_terms_live_cell/0.1",
                "campaign_id": contract["campaign_id"],
                **dict(design_cell),
                "status": "operational_failure",
                "receipt_status": receipt.status,
                "inclusion_status": receipt.inclusion_status,
                "receipt_sha256": receipt.receipt_sha256,
                "replay_verified": False,
                "elapsed_seconds": time.perf_counter() - started,
                "usage": None,
                "metrics": None,
                "parsed_output": None,
                "failure": {
                    "failure_class": receipt.failure.failure_class,
                    "failure_condition": receipt.failure.condition,
                    "error_type": type(error).__name__,
                },
            }
        )
    _atomic_write(result_path, result)
    return result


def _model_summary(
    model_id: str,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    selected = [row for row in rows if row["model_id"] == model_id]
    completed = [row for row in selected if row["status"] == "completed"]
    scores = [float(row["metrics"]["score"]) for row in completed]
    component_names = (
        "state_accuracy",
        "amount_accuracy",
        "required_action_recall",
        "required_claim_recall",
        "evidence_coverage",
    )
    return {
        "model_id": model_id,
        "planned_cells": len(selected),
        "completed_cells": len(completed),
        "operational_failure_cells": len(selected) - len(completed),
        "completion_rate": len(completed) / len(selected),
        "mean_score": statistics.fmean(scores) if scores else None,
        "min_score": min(scores) if scores else None,
        "max_score": max(scores) if scores else None,
        "score_std": statistics.pstdev(scores) if len(scores) > 1 else None,
        "hard_gate_pass_rate": (
            statistics.fmean(
                1.0 if row["metrics"]["hard_gate_pass"] else 0.0
                for row in completed
            )
            if completed
            else None
        ),
        "mean_components": {
            name: (
                statistics.fmean(float(row["metrics"][name]) for row in completed)
                if completed
                else None
            )
            for name in component_names
        },
        "reported_cost_usd": math.fsum(
            float(row["usage"]["reported_cost_usd"])
            for row in completed
            if row["usage"] is not None
        ),
    }


def _campaign_summary(
    contract: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    completed = [row for row in rows if row["status"] == "completed"]
    failures = [row for row in rows if row["status"] != "completed"]
    reported_cost = math.fsum(
        float(row["usage"]["reported_cost_usd"])
        for row in completed
        if row["usage"] is not None
    )
    paired: list[dict[str, Any]] = []
    for seed in contract["inference_seeds"]:
        by_model = {
            row["model_id"]: row
            for row in completed
            if row["inference_seed"] == seed
        }
        if set(by_model) == set(contract["models"]):
            paired.append(
                {
                    "inference_seed": seed,
                    "glm53_reka_score": by_model["glm53_reka"]["metrics"]["score"],
                    "mistral_small_score": by_model["mistral_small"]["metrics"]["score"],
                    "glm_minus_mistral": (
                        by_model["glm53_reka"]["metrics"]["score"]
                        - by_model["mistral_small"]["metrics"]["score"]
                    ),
                }
            )
    return _sealed(
        {
            "schema_version": "aeread.datacenter_terms_reliability_summary/0.1",
            "campaign_id": contract["campaign_id"],
            "contract_sha256": _sha256(contract),
            "campaign_driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "claim_status": contract["claim_status"],
            "independent_cluster_count": 1,
            "planned_cells": len(rows),
            "completed_cells": len(completed),
            "operational_failure_cells": len(failures),
            "failure_fraction": len(failures) / len(rows),
            "failure_conditions": sorted(
                row["failure"]["failure_condition"] for row in failures
            ),
            "reported_cost_usd": reported_cost,
            "provider_cost_complete": not failures,
            "cost_qualifier": "exact" if not failures else "lower_bound",
            "campaign_max_cost_usd": contract["execution"]["campaign_max_cost_usd"],
            "within_declared_campaign_cost_ceiling": (
                reported_cost <= contract["execution"]["campaign_max_cost_usd"]
            ),
            "all_completed_receipts_replayed": all(
                row["replay_verified"] for row in completed
            ),
            "winner_claim_allowed": False,
            "inferential_model_ranking_allowed": False,
            "model_summaries": [
                _model_summary(model_id, rows)
                for model_id in sorted(contract["models"])
            ],
            "paired_completed_seed_contrasts": paired,
        }
    )


async def run_live_panel(
    contract: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
    run_root: Path,
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
) -> dict[str, Any]:
    summary_path = run_root / "live" / "summary.json"
    if summary_path.exists():
        return _read_sealed(summary_path)
    provider_free = _read_sealed(run_root / "provider_free_validation" / "summary.json")
    admission = _read_sealed(run_root / "profile_admission" / "summary.json")
    if provider_free["status"] != "passed" or admission["status"] != "passed":
        raise ValueError("campaign gates must pass before live dispatch")
    if design["contract_sha256"] != _sha256(contract):
        raise ValueError("design contract digest differs before live dispatch")
    provider = provider_factory()
    semaphore = asyncio.Semaphore(int(contract["execution"]["concurrency"]))

    async def bounded(cell: Mapping[str, Any]) -> dict[str, Any]:
        async with semaphore:
            return await _run_live_cell(
                contract,
                cell,
                run_root=run_root,
                provider=provider,
            )

    rows = await asyncio.gather(*(bounded(cell) for cell in design["cells"]))
    summary = _campaign_summary(contract, rows)
    _atomic_write(summary_path, summary)
    return summary


async def run_campaign(
    *,
    contract_path: Path | str = DEFAULT_CONTRACT_PATH,
    run_root: Path | str = DEFAULT_RUN_ROOT,
    stop_after: str = "live",
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
) -> dict[str, Any]:
    if stop_after not in {"design", "provider_free", "profile_admission", "live"}:
        raise ValueError("unsupported campaign stage")
    contract = load_contract(contract_path)
    root = Path(run_root)
    design_path = root / "design" / "summary.json"
    if design_path.exists():
        design = _read_sealed(design_path)
        if design != build_design(contract):
            raise ValueError("stored campaign design differs from current resolution")
    else:
        design = build_design(contract)
        _atomic_write(design_path, design)
    if stop_after == "design":
        return design
    provider_free = await run_provider_free_gate(contract, run_root=root)
    if stop_after == "provider_free":
        return provider_free
    admission = run_profile_admission_gate(contract, design=design, run_root=root)
    if stop_after == "profile_admission":
        return admission
    return await run_live_panel(
        contract,
        design=design,
        run_root=root,
        provider_factory=provider_factory,
    )


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
    summary = asyncio.run(
        run_campaign(
            contract_path=arguments.contract,
            run_root=arguments.run_root,
            stop_after=arguments.stop_after,
        )
    )
    print(canonical_json_bytes(summary).decode("utf-8"))
    return 0


__all__ = [
    "CAMPAIGN_ID",
    "CONTRACT_SCHEMA_VERSION",
    "DEFAULT_CONTRACT_PATH",
    "DEFAULT_RUN_ROOT",
    "build_design",
    "load_contract",
    "main",
    "run_campaign",
    "run_live_panel",
    "run_profile_admission_gate",
    "run_provider_free_gate",
]


if __name__ == "__main__":
    raise SystemExit(main())
