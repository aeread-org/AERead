"""Frozen nested-depth campaign for written counteroffer adoption."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.receipts import verify_evaluation_receipt

from .adoption_environment import STAGE_SEQUENCES
from .adoption_runner import (
    build_adoption_setup,
    finalize_adoption_execution,
    finalize_adoption_failure,
    load_adoption_case,
    replay_adoption_receipt,
    run_adoption_offline,
    run_adoption_openrouter,
)
from .objective_campaign import (
    _atomic_write,
    _call_usage,
    _plain,
    _read_sealed,
    _route,
    _score_projection,
    _sealed,
    _sha256,
)
from .objective_openrouter import (
    CLIENT_IMPLEMENTATION_ID,
    ParameterCompatibleOpenRouterClient,
)
from .objective_runner import OBJECTIVE_CASE_PATH
from .stack_runner import load_stack_case


CONTRACT_SCHEMA_VERSION = (
    "aeread.datacenter_counteroffer_adoption_campaign_contract/0.1"
)
CAMPAIGN_ID = "datacenter_counteroffer_adoption_v1"
CONDITION = "forced_first_written_counteroffer_exact_adoption"
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
IMPLEMENTATION_SOURCES = (
    "contracts.py",
    "stack_environment.py",
    "stack_runner.py",
    "objective_environment.py",
    "objective_openrouter.py",
    "adoption_environment.py",
    "adoption_measurement.py",
    "adoption_runner.py",
    "adoption_campaign.py",
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def load_contract(path: Path | str = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    contract = _read_json(Path(path))
    expected_fields = {
        "schema_version",
        "campaign_id",
        "family_id",
        "family_version",
        "claim_status",
        "route_catalog_snapshot",
        "stages",
        "base_case",
        "inference_seeds",
        "condition",
        "models",
        "execution",
        "analysis",
    }
    if set(contract) != expected_fields:
        raise ValueError("adoption campaign contract fields differ")
    frozen = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "campaign_id": CAMPAIGN_ID,
        "family_id": CAMPAIGN_ID,
        "family_version": "1.0.0",
        "condition": CONDITION,
        "claim_status": "single_curated_project_nested_depth_diagnostic_only",
    }
    if any(contract[key] != value for key, value in frozen.items()):
        raise ValueError("adoption campaign identity or claim boundary differs")

    stages = contract["stages"]
    if not isinstance(stages, dict) or set(stages) != set(STAGE_SEQUENCES):
        raise ValueError("adoption stage panel differs")
    for stage_id, sequence in STAGE_SEQUENCES.items():
        stage = stages[stage_id]
        if not isinstance(stage, dict) or set(stage) != {
            "case_id",
            "expected_case_sha256",
            "required_sequence",
        }:
            raise ValueError(f"{stage_id}: stage fields differ")
        if tuple(stage["required_sequence"]) != sequence:
            raise ValueError(f"{stage_id}: nested sequence differs")

    base = contract["base_case"]
    if not isinstance(base, dict) or set(base) != {
        "case_id",
        "expected_case_sha256",
    }:
        raise ValueError("base-case pin fields differ")
    seeds = contract["inference_seeds"]
    if (
        not isinstance(seeds, list)
        or len(seeds) != 3
        or len(seeds) != len(set(seeds))
        or any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in seeds
        )
    ):
        raise ValueError("adoption campaign requires three unique inference seeds")

    snapshot = contract["route_catalog_snapshot"]
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "source",
        "verified_at",
        "selection_rule",
    }:
        raise ValueError("route-catalog snapshot fields differ")
    if "openrouter.ai/api/v1/models" not in snapshot["source"]:
        raise ValueError("route catalog must bind the official OpenRouter endpoint")

    models = contract["models"]
    if not isinstance(models, dict) or set(models) != set(EXPECTED_ROUTES):
        raise ValueError("adoption route panel differs")
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
    for model_id, expected in EXPECTED_ROUTES.items():
        model = models[model_id]
        if not isinstance(model, dict) or set(model) != route_fields:
            raise ValueError(f"{model_id}: route fields differ")
        if any(model[key] != value for key, value in expected.items()):
            raise ValueError(f"{model_id}: named route differs")
        if (
            model["access_class"] != "open_source"
            or model["license_id"] != "Apache-2.0"
            or model["reasoning_effort"] is not None
        ):
            raise ValueError(f"{model_id}: route policy differs")
        pricing = model["pricing"]
        if not isinstance(pricing, dict) or set(pricing) != {
            "input_per_million",
            "cached_input_per_million",
            "output_per_million",
            "pricing_id",
        }:
            raise ValueError(f"{model_id}: pricing fields differ")

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
        raise ValueError("adoption execution fields differ")
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
        raise ValueError("adapter, cache, retry, route, or harness controls differ")
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
    worst_case = len(stages) * len(seeds) * len(models) * float(
        execution["max_cost_usd_per_live_profile"]
    )
    if worst_case > float(execution["campaign_max_cost_usd"]):
        raise ValueError("cell cost ceilings exceed the campaign ceiling")

    analysis = contract["analysis"]
    if analysis.get("independent_cluster_count") != 1:
        raise ValueError("the ladder must retain one project cluster")
    if analysis.get("stage_variants_independent") is not False:
        raise ValueError("nested stage variants cannot be treated as independent")
    if analysis.get("nested_stage_order") != list(STAGE_SEQUENCES):
        raise ValueError("nested stage order differs")
    if analysis.get("missingness") != "report_separately":
        raise ValueError("operational missingness must remain separate")
    if analysis.get("primary_estimand") != "counteroffer_adoption_rate":
        raise ValueError("primary estimand differs")
    for field in (
        "winner_claim_allowed",
        "inferential_model_ranking_allowed",
        "causal_depth_effect_allowed",
    ):
        if analysis.get(field) is not False:
            raise ValueError(f"analysis.{field} must be false")
    return contract


def _cells(contract: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "cell_key": f"{stage_id}__{model_id}__seed_{seed}",
            "condition": contract["condition"],
            "stage_id": stage_id,
            "model_id": model_id,
            "inference_seed": seed,
        }
        for stage_id in contract["analysis"]["nested_stage_order"]
        for seed in contract["inference_seeds"]
        for model_id in sorted(contract["models"])
    )


def _setup(contract: Mapping[str, Any], cell: Mapping[str, Any]):
    controls = contract["execution"]
    return build_adoption_setup(
        str(cell["stage_id"]),
        route=_route(contract["models"][cell["model_id"]]),
        seed=int(cell["inference_seed"]),
        max_output_tokens=int(controls["max_output_tokens_per_action"]),
        timeout_seconds=float(controls["timeout_seconds_per_action"]),
        max_cost_usd=float(controls["max_cost_usd_per_live_profile"]),
    )


def _implementation_hashes() -> dict[str, str]:
    root = Path(__file__).parent
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in IMPLEMENTATION_SOURCES
    }


def build_design(contract: Mapping[str, Any]) -> dict[str, Any]:
    base = load_stack_case("v2", OBJECTIVE_CASE_PATH)
    if (
        base.case_id != contract["base_case"]["case_id"]
        or base.content_sha256 != contract["base_case"]["expected_case_sha256"]
    ):
        raise ValueError("base case differs from the contract pin")
    for stage_id, stage_contract in contract["stages"].items():
        case = load_adoption_case(stage_id)
        if (
            case.case_id != stage_contract["case_id"]
            or case.content_sha256 != stage_contract["expected_case_sha256"]
        ):
            raise ValueError(f"{stage_id}: case differs from its contract pin")

    per_profile = float(contract["execution"]["max_cost_usd_per_live_profile"])
    cells: list[dict[str, Any]] = []
    for cell in _cells(contract):
        setup = _setup(contract, cell)
        plan_cell = setup.plan.cells[0]
        live_profiles = sum(
            profile.model.provider == "openrouter"
            for profile in setup.plan.agent_profiles
        )
        if live_profiles != 1 or setup.plan.evaluation_blocks[0].kind != "controlled":
            raise ValueError(f"controlled condition drift for {cell['cell_key']}")
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
                "declared_cell_max_cost_usd": per_profile,
            }
        )
    maximum = sum(float(cell["declared_cell_max_cost_usd"]) for cell in cells)
    ceiling = float(contract["execution"]["campaign_max_cost_usd"])
    if maximum > ceiling:
        raise ValueError("resolved adoption design exceeds campaign ceiling")
    hashes = _implementation_hashes()
    return _sealed(
        {
            "schema_version": "aeread.datacenter_counteroffer_adoption_design/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "campaign_driver_sha256": hashes["adoption_campaign.py"],
            "adapter_implementation_id": CLIENT_IMPLEMENTATION_ID,
            "implementation_source_sha256s": hashes,
            "base_case_id": base.case_id,
            "base_case_sha256": base.content_sha256,
            "independent_cluster_count": 1,
            "nested_stage_count": len(contract["stages"]),
            "nested_stage_variants_independent": False,
            "planned_cells": len(cells),
            "paired_seed_count": len(contract["inference_seeds"]),
            "worst_case_declared_cost_usd": maximum,
            "campaign_max_cost_usd": ceiling,
            "cells": cells,
        }
    )


async def run_provider_free_gate(
    contract: Mapping[str, Any], *, run_root: Path
) -> dict[str, Any]:
    path = run_root / "provider_free_validation" / "summary.json"
    if path.exists():
        return _read_sealed(path)
    stages: list[dict[str, Any]] = []
    for stage_id in contract["analysis"]["nested_stage_order"]:
        evidence_root = run_root / "provider_free_validation" / stage_id / "evidence"
        setup, execution = await run_adoption_offline(
            stage_id, evidence_root=evidence_root
        )
        receipt = finalize_adoption_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_adoption_receipt(
            setup=setup, receipt=receipt, evidence_root=evidence_root
        )
        verify_evaluation_receipt(replayed)
        score = next(
            score
            for score in receipt.scores
            if score.leaf.leaf_id == "counteroffer_adoption_rate"
        )
        outcome = execution.episode_result.outcome
        passed = (
            receipt.inclusion_status == "included"
            and score.primary.value == 1.0
            and outcome["prefix_completed"]
            and outcome["exact_package_integrity"]
            and replayed == receipt
        )
        stages.append(
            {
                "stage_id": stage_id,
                "status": "passed" if passed else "failed",
                "case_sha256": setup.case.content_sha256,
                "logical_action_count": execution.episode_result.logical_action_count,
                "primary_score": score.primary.value,
                "executed_agreement_count": outcome["executed_agreement_count"],
                "counteroffer_opportunity_count": outcome[
                    "counteroffer_opportunity_count"
                ],
                "receipt_sha256": receipt.receipt_sha256,
                "replay_verified": replayed == receipt,
            }
        )
    summary = _sealed(
        {
            "schema_version": "aeread.datacenter_counteroffer_adoption_provider_free_gate/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "status": (
                "passed"
                if all(item["status"] == "passed" for item in stages)
                else "failed"
            ),
            "stages": stages,
        }
    )
    _atomic_write(path, summary)
    return summary


def run_profile_admission_gate(
    contract: Mapping[str, Any], *, design: Mapping[str, Any], run_root: Path
) -> dict[str, Any]:
    path = run_root / "profile_admission" / "summary.json"
    if path.exists():
        return _read_sealed(path)
    design_by_key = {cell["cell_key"]: cell for cell in design["cells"]}
    admitted: list[str] = []
    for cell in _cells(contract):
        setup = _setup(contract, cell)
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
            "schema_version": "aeread.datacenter_counteroffer_adoption_profile_gate/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "status": "passed",
            "admitted_cells": admitted,
        }
    )
    _atomic_write(path, summary)
    return summary


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
        raise ValueError(f"refusing to replace incomplete cell {design_cell['cell_key']}")

    setup = _setup(contract, design_cell)
    if (
        setup.plan.plan_sha256 != design_cell["run_plan_sha256"]
        or setup.plan.cells[0].cell_id != design_cell["cell_id"]
    ):
        raise ValueError(f"live plan drift for {design_cell['cell_key']}")
    controls = contract["execution"]
    model = contract["models"][design_cell["model_id"]]
    started = time.perf_counter()
    try:
        _, execution = await run_adoption_openrouter(
            str(design_cell["stage_id"]),
            _route(model),
            evidence_root=cell_root / "evidence",
            seed=int(design_cell["inference_seed"]),
            max_output_tokens=int(controls["max_output_tokens_per_action"]),
            timeout_seconds=float(controls["timeout_seconds_per_action"]),
            max_cost_usd=float(controls["max_cost_usd_per_live_profile"]),
            provider=provider,
        )
        receipt = finalize_adoption_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_adoption_receipt(
            setup=setup,
            receipt=receipt,
            evidence_root=cell_root / "evidence",
        )
        verify_evaluation_receipt(replayed)
        result = _sealed(
            {
                "schema_version": "aeread.datacenter_counteroffer_adoption_live_cell/0.1",
                "campaign_id": CAMPAIGN_ID,
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
        receipt = finalize_adoption_failure(
            setup=setup,
            cell_id=setup.plan.cells[0].cell_id,
            evidence_root=cell_root / "evidence",
            error=error,
        )
        verify_evaluation_receipt(receipt)
        result = _sealed(
            {
                "schema_version": "aeread.datacenter_counteroffer_adoption_live_cell/0.1",
                "campaign_id": CAMPAIGN_ID,
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
    *, key: str, value: str, rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    selected = [row for row in rows if row[key] == value]
    completed = [row for row in selected if row["status"] == "completed"]
    included = [row for row in completed if row["inclusion_status"] == "included"]

    def mean(leaf_id: str) -> float | None:
        values = [float(row["scores"][leaf_id]["value"]) for row in included]
        return statistics.fmean(values) if values else None

    return {
        key: value,
        "planned_cells": len(selected),
        "completed_cells": len(completed),
        "included_cells": len(included),
        "operational_failure_cells": len(selected) - len(completed),
        "completion_rate": len(completed) / len(selected),
        "mean_counteroffer_adoption_rate": mean("counteroffer_adoption_rate"),
        "mean_prefix_completion": mean("prefix_completion"),
        "mean_exact_package_integrity": mean("exact_package_integrity"),
        "mean_executed_agreement_count": mean("executed_agreement_count"),
        "mean_counteroffer_opportunity_count": mean(
            "counteroffer_opportunity_count"
        ),
        "mean_negotiation_temporal_compliance": mean(
            "negotiation_temporal_compliance"
        ),
        "mean_intentional_resolution": mean("intentional_resolution"),
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
            "schema_version": "aeread.datacenter_counteroffer_adoption_summary/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "design_sha256": design["artifact_sha256"],
            "campaign_driver_sha256": design["campaign_driver_sha256"],
            "implementation_source_sha256s": design[
                "implementation_source_sha256s"
            ],
            "claim_status": contract["claim_status"],
            "independent_cluster_count": 1,
            "nested_stage_variants_independent": False,
            "planned_cells": len(rows),
            "completed_cells": len(completed),
            "included_cells": sum(
                row["inclusion_status"] == "included" for row in completed
            ),
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
            "model_summaries": [
                _group_summary(key="model_id", value=model_id, rows=rows)
                for model_id in sorted(contract["models"])
            ],
            "stage_summaries": [
                _group_summary(key="stage_id", value=stage_id, rows=rows)
                for stage_id in contract["analysis"]["nested_stage_order"]
            ],
            "winner_claim_allowed": False,
            "inferential_model_ranking_allowed": False,
            "causal_depth_effect_allowed": False,
        }
    )


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
        raise ValueError("provider-free adoption campaign gate failed")
    if stop_after == "provider_free":
        return provider_free
    admission = run_profile_admission_gate(contract, design=design, run_root=root)
    if admission["status"] != "passed":
        raise ValueError("profile-admission adoption campaign gate failed")
    if stop_after == "profile_admission":
        return admission

    concurrency = asyncio.Semaphore(int(contract["execution"]["concurrency"]))
    provider_locks = {
        str(model["provider"]): asyncio.Semaphore(1)
        for model in contract["models"].values()
    }

    async def execute(cell: Mapping[str, Any]) -> dict[str, Any]:
        provider_name = str(contract["models"][cell["model_id"]]["provider"])
        async with concurrency, provider_locks[provider_name]:
            return await _run_live_cell(
                contract, cell, run_root=root, provider=provider_factory()
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
    args = parser.parse_args(argv)
    result = asyncio.run(
        run_campaign(
            contract_path=args.contract,
            run_root=args.run_root,
            stop_after=args.stop_after,
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
    "run_campaign",
    "run_profile_admission_gate",
    "run_provider_free_gate",
    "summarize",
]
