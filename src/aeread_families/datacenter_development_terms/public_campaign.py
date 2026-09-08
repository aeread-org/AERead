"""Run the public-primary-source data-center agreement variance panel."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import statistics
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.receipts import verify_evaluation_receipt
from aeread_families.datacenter_development.objective_openrouter import (
    CLIENT_IMPLEMENTATION_ID,
    ParameterCompatibleOpenRouterClient,
)

from .campaign import (
    _atomic_write,
    _call_usage,
    _read_sealed,
    _route,
    _sealed,
    _sha256,
)
from .public_cases import (
    PACK_ID,
    public_pack_sha256,
    load_public_cases,
)
from .runner import (
    build_offline_setup,
    build_openrouter_setup,
    finalize_datacenter_terms_execution,
    finalize_datacenter_terms_failure,
    replay_datacenter_terms_receipt,
    run_fixture_response,
    run_openrouter,
)


CONTRACT_SCHEMA_VERSION = "aeread.datacenter_terms_public_campaign_contract/0.1"
CAMPAIGN_ID = "datacenter_development_terms_public_v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT_PATH = REPOSITORY_ROOT / "configs" / f"{CAMPAIGN_ID}.json"
DEFAULT_RUN_ROOT = REPOSITORY_ROOT / "runs" / CAMPAIGN_ID
MODEL_ORDER = ("mistral32_deepinfra", "qwen3_235b_novita")


def load_contract(path: Path | str = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    expected_fields = {
        "schema_version",
        "campaign_id",
        "family_id",
        "family_version",
        "pack_id",
        "pack_sha256",
        "claim_status",
        "route_catalog_snapshot",
        "cases",
        "inference_seeds",
        "models",
        "execution",
        "analysis",
    }
    if not isinstance(contract, dict) or set(contract) != expected_fields:
        raise ValueError("public campaign contract fields differ")
    frozen = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "campaign_id": CAMPAIGN_ID,
        "family_id": "datacenter_development_terms_v1",
        "family_version": "1.0.0",
        "pack_id": PACK_ID,
        "claim_status": (
            "public_source_cross_project_variance_exploratory_five_filing_clusters"
        ),
    }
    if any(contract.get(key) != value for key, value in frozen.items()):
        raise ValueError("public campaign identity or claim boundary differs")
    if contract["pack_sha256"] != public_pack_sha256():
        raise ValueError("public pack digest differs")

    cases = {case.case_id.rsplit(".", 1)[-1]: case for case in load_public_cases()}
    if set(contract["cases"]) != set(cases) or len(cases) != 5:
        raise ValueError("public campaign case panel differs")
    for slug, case in cases.items():
        spec = contract["cases"][slug]
        if spec != {
            "case_id": case.case_id,
            "expected_case_sha256": case.content_sha256,
            "source_cluster_id": case.payload["public_case"]["independence_cluster_id"],
        }:
            raise ValueError(f"{slug}: public case contract differs")

    seeds = contract["inference_seeds"]
    if (
        not isinstance(seeds, list)
        or len(seeds) != 3
        or len(set(seeds)) != 3
        or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seeds)
    ):
        raise ValueError("public campaign requires three unique inference seeds")
    expected_routes = {
        "mistral32_deepinfra": (
            "mistralai/mistral-small-3.2-24b-instruct",
            "mistralai/mistral-small-3.2-24b-instruct-2506",
            "DeepInfra",
        ),
        "qwen3_235b_novita": (
            "qwen/qwen3-235b-a22b-2507",
            "qwen/qwen3-235b-a22b-07-25",
            "Novita",
        ),
    }
    if set(contract["models"]) != set(expected_routes):
        raise ValueError("public campaign model panel differs")
    for model_id, expected in expected_routes.items():
        model = contract["models"][model_id]
        if (
            (model["requested_model"], model["canonical_model"], model["provider"])
            != expected
            or model["access_class"] != "open_source"
            or model["license_id"] != "Apache-2.0"
            or model["reasoning_effort"] is not None
        ):
            raise ValueError(f"{model_id}: public route differs")
        pricing = model.get("pricing")
        if not isinstance(pricing, dict) or set(pricing) != {
            "input_per_million",
            "cached_input_per_million",
            "output_per_million",
            "pricing_id",
        }:
            raise ValueError(f"{model_id}: public pricing fields differ")

    controls = contract["execution"]
    required_controls = {
        "harness": "minimal_chat/1.0",
        "adapter": CLIENT_IMPLEMENTATION_ID,
        "max_concurrent_cells_per_route_provider": 1,
        "max_action_attempts": 1,
        "sdk_retries": 0,
        "response_cache": False,
        "provider_fallbacks": False,
    }
    if any(controls.get(key) != value for key, value in required_controls.items()):
        raise ValueError("public campaign execution controls differ")
    if controls.get("concurrency") != 2:
        raise ValueError("public campaign concurrency differs")
    planned = len(cases) * len(seeds) * len(expected_routes)
    worst = planned * float(controls["max_cost_usd_per_cell"])
    if worst > float(controls["campaign_max_cost_usd"]):
        raise ValueError("public campaign exceeds its declared cost ceiling")

    analysis = contract["analysis"]
    required_analysis = {
        "case_count": 5,
        "independent_cluster_count": 5,
        "resampling_unit": "public_filing_cluster",
        "paired_by": ["case_slug", "inference_seed"],
        "missingness": "report_separately_and_require_both_models_for_pair",
        "winner_claim_allowed": False,
        "inferential_model_ranking_allowed": False,
        "project_generalization_allowed": False,
        "population_causal_effect_allowed": False,
    }
    if any(analysis.get(key) != value for key, value in required_analysis.items()):
        raise ValueError("public campaign analysis contract differs")
    return contract


def _cases_by_slug() -> dict[str, Any]:
    return {
        case.case_id.rsplit(".", 1)[-1]: case
        for case in load_public_cases()
    }


def _cells(contract: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "cell_key": f"{case_slug}__{model_id}__seed_{seed}",
            "pair_key": f"{case_slug}__seed_{seed}",
            "case_slug": case_slug,
            "source_cluster_id": contract["cases"][case_slug]["source_cluster_id"],
            "model_id": model_id,
            "inference_seed": seed,
        }
        for case_slug in sorted(contract["cases"])
        for seed in contract["inference_seeds"]
        for model_id in MODEL_ORDER
    )


def _setup(
    contract: Mapping[str, Any],
    cell: Mapping[str, Any],
    cases: Mapping[str, Any],
):
    controls = contract["execution"]
    case = cases[str(cell["case_slug"])]
    return build_openrouter_setup(
        _route(contract["models"][cell["model_id"]]),
        seed=int(cell["inference_seed"]),
        case_slug=str(cell["case_slug"]),
        case_manifest=case,
        max_output_tokens=int(controls["max_output_tokens"]),
        timeout_seconds=float(controls["timeout_seconds"]),
        max_cost_usd=float(controls["max_cost_usd_per_cell"]),
    )


def _implementation_hashes() -> dict[str, str]:
    names = (
        "environment.py",
        "runner.py",
        "public_cases.py",
        "public_campaign.py",
    )
    root = Path(__file__).parent
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in names
    }


def build_design(contract: Mapping[str, Any]) -> dict[str, Any]:
    cases = _cases_by_slug()
    per_cell = float(contract["execution"]["max_cost_usd_per_cell"])
    cells = []
    for cell in _cells(contract):
        setup = _setup(contract, cell, cases)
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
                "evaluation_block_kind": setup.plan.evaluation_blocks[0].kind,
                "live_profile_count": 1,
                "declared_cell_max_cost_usd": per_cell,
            }
        )
    hashes = _implementation_hashes()
    return _sealed(
        {
            "schema_version": "aeread.datacenter_terms_public_design/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "pack_sha256": public_pack_sha256(),
            "campaign_driver_sha256": hashes["public_campaign.py"],
            "adapter_implementation_id": CLIENT_IMPLEMENTATION_ID,
            "implementation_source_sha256s": hashes,
            "case_count": len(cases),
            "independent_cluster_count": 5,
            "planned_cells": len(cells),
            "planned_pair_count": len(cases) * len(contract["inference_seeds"]),
            "worst_case_declared_cost_usd": len(cells) * per_cell,
            "campaign_max_cost_usd": contract["execution"]["campaign_max_cost_usd"],
            "cells": cells,
        }
    )


async def run_provider_free_gate(
    contract: Mapping[str, Any], *, run_root: Path
) -> dict[str, Any]:
    path = run_root / "provider_free_validation" / "summary.json"
    if path.exists():
        return _read_sealed(path)
    rows = []
    for slug, case in sorted(_cases_by_slug().items()):
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
        evidence_root = run_root / "provider_free_validation" / slug / "evidence"
        setup = build_offline_setup(case_slug=slug, case_manifest=case)
        execution = await run_fixture_response(
            canonical_json_bytes(response).decode("utf-8"),
            evidence_root=evidence_root,
            case_slug=slug,
            case_manifest=case,
        )
        receipt = finalize_datacenter_terms_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_datacenter_terms_receipt(
            setup=setup,
            receipt=receipt,
            evidence_root=evidence_root,
        )
        outcome = execution.episode_result.outcome
        passed = outcome["score"] == 1.0 and replayed == receipt
        rows.append(
            {
                "case_slug": slug,
                "case_sha256": case.content_sha256,
                "status": "passed" if passed else "failed",
                "score": outcome["score"],
                "receipt_sha256": receipt.receipt_sha256,
                "replay_verified": replayed == receipt,
            }
        )
    result = _sealed(
        {
            "schema_version": "aeread.datacenter_terms_public_provider_free_gate/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "status": "passed" if all(row["status"] == "passed" for row in rows) else "failed",
            "cases": rows,
        }
    )
    _atomic_write(path, result)
    return result


def run_profile_admission_gate(
    contract: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
    run_root: Path,
) -> dict[str, Any]:
    path = run_root / "profile_admission" / "summary.json"
    if path.exists():
        return _read_sealed(path)
    cases = _cases_by_slug()
    expected = {cell["cell_key"]: cell for cell in design["cells"]}
    admitted = []
    for cell in _cells(contract):
        setup = _setup(contract, cell, cases)
        target = expected[cell["cell_key"]]
        if (
            setup.plan.plan_sha256 != target["run_plan_sha256"]
            or setup.plan.cells[0].cell_id != target["cell_id"]
            or not all(item.admitted for item in setup.plan.profile_admissions)
        ):
            raise ValueError(f"profile admission drift for {cell['cell_key']}")
        admitted.append(cell["cell_key"])
    result = _sealed(
        {
            "schema_version": "aeread.datacenter_terms_public_profile_gate/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "status": "passed",
            "admitted_cells": admitted,
        }
    )
    _atomic_write(path, result)
    return result


async def _run_live_cell(
    contract: Mapping[str, Any],
    design_cell: Mapping[str, Any],
    *,
    cases: Mapping[str, Any],
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
    case = cases[str(design_cell["case_slug"])]
    route = _route(contract["models"][design_cell["model_id"]])
    controls = contract["execution"]
    setup = _setup(contract, design_cell, cases)
    started = time.perf_counter()
    try:
        returned_setup, execution = await run_openrouter(
            route,
            evidence_root=cell_root / "evidence",
            seed=int(design_cell["inference_seed"]),
            case_slug=str(design_cell["case_slug"]),
            case_manifest=case,
            max_output_tokens=int(controls["max_output_tokens"]),
            timeout_seconds=float(controls["timeout_seconds"]),
            max_cost_usd=float(controls["max_cost_usd_per_cell"]),
            provider=provider,
        )
        if returned_setup.plan.plan_sha256 != setup.plan.plan_sha256:
            raise ValueError("live setup differs from sealed design")
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
                "schema_version": "aeread.datacenter_terms_public_live_cell/0.1",
                "campaign_id": CAMPAIGN_ID,
                **dict(design_cell),
                "status": "completed",
                "receipt_status": receipt.status,
                "inclusion_status": receipt.inclusion_status,
                "receipt_sha256": receipt.receipt_sha256,
                "replay_verified": replayed == receipt,
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
                "schema_version": "aeread.datacenter_terms_public_live_cell/0.1",
                "campaign_id": CAMPAIGN_ID,
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


def _group_summary(
    field: str,
    value: str,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    selected = [row for row in rows if row[field] == value]
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
        field: value,
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
    contract: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    completed = [row for row in rows if row["status"] == "completed"]
    failures = [row for row in rows if row["status"] != "completed"]
    pairs = []
    for case_slug in sorted(contract["cases"]):
        for seed in contract["inference_seeds"]:
            selected = [
                row
                for row in rows
                if row["case_slug"] == case_slug and row["inference_seed"] == seed
            ]
            by_model = {
                row["model_id"]: row
                for row in selected
                if row["status"] == "completed"
            }
            usable = set(by_model) == set(MODEL_ORDER)
            pairs.append(
                {
                    "pair_key": f"{case_slug}__seed_{seed}",
                    "case_slug": case_slug,
                    "inference_seed": seed,
                    "pair_reportable": usable,
                    "model_scores": (
                        {
                            model_id: by_model[model_id]["metrics"]["score"]
                            for model_id in MODEL_ORDER
                        }
                        if usable
                        else None
                    ),
                    "qwen_minus_mistral": (
                        by_model["qwen3_235b_novita"]["metrics"]["score"]
                        - by_model["mistral32_deepinfra"]["metrics"]["score"]
                        if usable
                        else None
                    ),
                }
            )
    reported_cost = math.fsum(
        float(row["usage"]["reported_cost_usd"])
        for row in completed
        if row["usage"] is not None
    )
    return _sealed(
        {
            "schema_version": "aeread.datacenter_terms_public_summary/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "campaign_driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "claim_status": contract["claim_status"],
            "case_count": len(contract["cases"]),
            "independent_cluster_count": 5,
            "planned_cells": len(rows),
            "completed_cells": len(completed),
            "included_cells": sum(row["inclusion_status"] == "included" for row in rows),
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
            "project_generalization_allowed": False,
            "population_causal_effect_allowed": False,
            "model_summaries": [
                _group_summary("model_id", model_id, rows)
                for model_id in MODEL_ORDER
            ],
            "case_summaries": [
                _group_summary("case_slug", case_slug, rows)
                for case_slug in sorted(contract["cases"])
            ],
            "paired_case_seed_contrasts": pairs,
            "reportable_pair_count": sum(row["pair_reportable"] for row in pairs),
        }
    )


async def run_live_panel(
    contract: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
    run_root: Path,
    provider_factory: Callable[[], Any] = ParameterCompatibleOpenRouterClient,
) -> dict[str, Any]:
    path = run_root / "live" / "summary.json"
    if path.exists():
        return _read_sealed(path)
    provider_free = _read_sealed(run_root / "provider_free_validation" / "summary.json")
    admission = _read_sealed(run_root / "profile_admission" / "summary.json")
    if provider_free["status"] != "passed" or admission["status"] != "passed":
        raise ValueError("public campaign gates must pass before live dispatch")
    if design["contract_sha256"] != _sha256(contract):
        raise ValueError("public design contract digest differs")
    cases = _cases_by_slug()
    provider = provider_factory()
    global_limit = asyncio.Semaphore(int(contract["execution"]["concurrency"]))
    provider_limits = {
        model["provider"]: asyncio.Semaphore(1)
        for model in contract["models"].values()
    }

    async def bounded(cell: Mapping[str, Any]) -> dict[str, Any]:
        provider_name = contract["models"][cell["model_id"]]["provider"]
        async with global_limit, provider_limits[provider_name]:
            return await _run_live_cell(
                contract,
                cell,
                cases=cases,
                run_root=run_root,
                provider=provider,
            )

    rows = await asyncio.gather(*(bounded(cell) for cell in design["cells"]))
    summary = _campaign_summary(contract, rows)
    _atomic_write(path, summary)
    return summary


async def run_campaign(
    *,
    contract_path: Path | str = DEFAULT_CONTRACT_PATH,
    run_root: Path | str = DEFAULT_RUN_ROOT,
    stop_after: str = "live",
    provider_factory: Callable[[], Any] = ParameterCompatibleOpenRouterClient,
) -> dict[str, Any]:
    if stop_after not in {"design", "provider_free", "profile_admission", "live"}:
        raise ValueError("unsupported public campaign stage")
    contract = load_contract(contract_path)
    root = Path(run_root)
    design_path = root / "design" / "summary.json"
    if design_path.exists():
        design = _read_sealed(design_path)
        if design != build_design(contract):
            raise ValueError("stored public campaign design differs")
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
