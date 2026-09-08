"""Run the unique-array two-route integrated public campaign."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
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
from .public_integrated_campaign import _group_summary
from .public_integrated_v3_cases import (
    PACK_ID,
    load_public_integrated_v3_cases,
    public_integrated_v3_pack_sha256,
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


CONTRACT_SCHEMA_VERSION = (
    "aeread.datacenter_terms_public_integrated_v4_campaign/0.1"
)
CAMPAIGN_ID = "datacenter_development_terms_public_integrated_v4"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT_PATH = REPOSITORY_ROOT / "configs" / f"{CAMPAIGN_ID}.json"
DEFAULT_RUN_ROOT = REPOSITORY_ROOT / "runs" / CAMPAIGN_ID
PREDECESSOR_RUN_ROOT = (
    REPOSITORY_ROOT / "runs" / "datacenter_development_terms_public_integrated_v3"
)
MODEL_ORDER = ("mistral32_deepinfra", "qwen3_235b_google")


def _cases_by_slug() -> dict[str, Any]:
    return {
        case.case_id.rsplit(".", 1)[-1]: case
        for case in load_public_integrated_v3_cases()
    }


def _validate_predecessor(contract: Mapping[str, Any]) -> None:
    expected = {
        "campaign_id": "datacenter_development_terms_public_integrated_v3",
        "contract_sha256": (
            "1fb51779395c671b13efb1ac3bdf4ec56dedd8c35a079d93123ec5928b3fdeab"
        ),
        "design_sha256": (
            "1e7d879f2702556337a9e52329a133602af51bffb6747d23afde4477eaf30922"
        ),
        "live_summary_sha256": (
            "717851f610033a456f311e8eceedc669384f021900f29bd2ce5129c1c17407a3"
        ),
        "status": (
            "invalidated_for_strict_schema_comparison_schema_permitted_"
            "duplicate_evaluator_rejected"
        ),
        "comparison_scope": "audit_lineage_only_not_analysis_data",
    }
    if contract["predecessor"] != expected:
        raise ValueError("public integrated v4 predecessor lineage differs")
    for field, path in {
        "design_sha256": PREDECESSOR_RUN_ROOT / "design" / "summary.json",
        "live_summary_sha256": PREDECESSOR_RUN_ROOT / "live" / "summary.json",
    }.items():
        if path.exists() and _read_sealed(path)["artifact_sha256"] != expected[field]:
            raise ValueError(f"public integrated v4 predecessor {field} differs")


def _validate_snapshot(contract: Mapping[str, Any]) -> None:
    snapshot = contract["route_catalog_snapshot"]
    expected_sources = [
        "https://openrouter.ai/api/v1/models/"
        "mistralai/mistral-small-3.2-24b-instruct/endpoints",
        "https://openrouter.ai/api/v1/models/qwen/qwen3-235b-a22b-2507/endpoints",
    ]
    if (
        not isinstance(snapshot, Mapping)
        or set(snapshot)
        != {"verified_at", "sources", "selection_rule", "selected_endpoints"}
        or snapshot["verified_at"] != "2026-09-03T14:40:33Z"
        or snapshot["sources"] != expected_sources
        or snapshot["selection_rule"]
        != (
            "two_healthy_distinct_provider_routes_supporting_seed_response_"
            "format_structured_outputs_and_unique_items_with_price_caps_no_"
            "fallback"
        )
    ):
        raise ValueError("public integrated v4 route snapshot differs")
    endpoints = snapshot["selected_endpoints"]
    required = {"seed", "response_format", "structured_outputs"}
    if not isinstance(endpoints, Mapping) or set(endpoints) != set(MODEL_ORDER):
        raise ValueError("public integrated v4 selected endpoints differ")
    for model_id, endpoint in endpoints.items():
        model = contract["models"][model_id]
        if (
            endpoint.get("provider") != model["provider"]
            or endpoint.get("quantization") != model["quantization"]
            or endpoint.get("status") != 0
            or not required.issubset(set(endpoint.get("required_parameters", [])))
        ):
            raise ValueError(f"{model_id}: v4 selected endpoint differs")


def load_contract(path: Path | str = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    frozen = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "campaign_id": CAMPAIGN_ID,
        "family_id": "datacenter_development_terms_v1",
        "family_version": "1.0.0",
        "pack_id": PACK_ID,
        "claim_status": (
            "unique_array_three_project_two_route_model_comparison_"
            "exploratory"
        ),
    }
    if not isinstance(contract, dict) or any(
        contract.get(key) != value for key, value in frozen.items()
    ):
        raise ValueError("public integrated v4 campaign identity differs")
    if set(contract) != {
        *frozen,
        "pack_sha256",
        "predecessor",
        "route_catalog_snapshot",
        "cases",
        "inference_seeds",
        "models",
        "execution",
        "analysis",
    }:
        raise ValueError("public integrated v4 campaign fields differ")
    if contract["pack_sha256"] != public_integrated_v3_pack_sha256():
        raise ValueError("public integrated v4 pack digest differs")
    _validate_predecessor(contract)

    cases = _cases_by_slug()
    if len(cases) != 3 or set(contract["cases"]) != set(cases):
        raise ValueError("public integrated v4 case panel differs")
    for slug, case in cases.items():
        public = case.payload["public_case"]
        if contract["cases"][slug] != {
            "case_id": case.case_id,
            "expected_case_sha256": case.content_sha256,
            "source_cluster_id": public["independence_cluster_id"],
            "world_seed": case.world_seed,
        }:
            raise ValueError(f"{slug}: public integrated v4 case differs")
    if contract["inference_seeds"] != [321001, 321002, 321003]:
        raise ValueError("public integrated v4 inference seeds differ")

    common = {
        "access_class": "open_source",
        "license_id": "Apache-2.0",
        "reasoning_effort": None,
        "temperature_supported": True,
    }
    expected_models = {
        "mistral32_deepinfra": {
            "profile_id": "datacenter_terms_integrated_v4_mistral32_deepinfra",
            "requested_model": "mistralai/mistral-small-3.2-24b-instruct",
            "canonical_model": "mistralai/mistral-small-3.2-24b-instruct-2506",
            "provider": "DeepInfra",
            "quantization": "fp8",
            **common,
            "pricing": {
                "input_per_million": 0.075,
                "cached_input_per_million": 0.075,
                "output_per_million": 0.2,
                "pricing_id": (
                    "openrouter_2026-09-03_mistral32_deepinfra_terms_"
                    "integrated_v4"
                ),
            },
            "max_prompt_price_per_million": "0.075",
            "max_completion_price_per_million": "0.2",
        },
        "qwen3_235b_google": {
            "profile_id": "datacenter_terms_integrated_v4_qwen3_235b_google",
            "requested_model": "qwen/qwen3-235b-a22b-2507",
            "canonical_model": "qwen/qwen3-235b-a22b-07-25",
            "provider": "Google",
            "quantization": "unknown",
            **common,
            "pricing": {
                "input_per_million": 0.22,
                "cached_input_per_million": 0.22,
                "output_per_million": 0.88,
                "pricing_id": (
                    "openrouter_2026-09-03_qwen3_google_terms_integrated_v4"
                ),
            },
            "max_prompt_price_per_million": "0.22",
            "max_completion_price_per_million": "0.88",
        },
    }
    if contract["models"] != expected_models:
        raise ValueError("public integrated v4 model routes differ")
    _validate_snapshot(contract)

    if contract["execution"] != {
        "harness": "minimal_chat/1.0",
        "adapter": CLIENT_IMPLEMENTATION_ID,
        "schema_mode": "unique_array_items_v1",
        "unique_array_items": True,
        "max_output_tokens": 900,
        "timeout_seconds": 180.0,
        "max_cost_usd_per_cell": 0.02,
        "campaign_max_cost_usd": 0.36,
        "concurrency": 2,
        "max_concurrent_cells_per_route_provider": 1,
        "max_action_attempts": 1,
        "sdk_retries": 0,
        "response_cache": False,
        "provider_fallbacks": False,
    }:
        raise ValueError("public integrated v4 execution controls differ")
    if contract["analysis"] != {
        "case_count": 3,
        "independent_cluster_count": 3,
        "resampling_unit": "public_filing_project_cluster",
        "stability_replicate_unit": "inference_seed_within_project_route",
        "paired_by": ["case_slug", "inference_seed"],
        "primary_contrast": "qwen3_235b_google_minus_mistral32_deepinfra",
        "primary_endpoints": [
            "hard_gate_pass",
            "score",
            "forbidden_selection_count",
        ],
        "missingness": (
            "report_separately_and_require_both_routes_for_pair_no_selective_"
            "retry"
        ),
        "winner_claim_allowed": False,
        "inferential_model_ranking_allowed": False,
        "project_generalization_allowed": False,
        "population_causal_effect_allowed": False,
    }:
        raise ValueError("public integrated v4 analysis contract differs")
    return contract


def _cells(contract: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "cell_key": f"{slug}__{model_id}__seed_{seed}",
            "pair_key": f"{slug}__seed_{seed}",
            "case_slug": slug,
            "source_cluster_id": contract["cases"][slug]["source_cluster_id"],
            "world_seed": contract["cases"][slug]["world_seed"],
            "model_id": model_id,
            "inference_seed": seed,
        }
        for slug in sorted(contract["cases"])
        for seed in contract["inference_seeds"]
        for model_id in MODEL_ORDER
    )


def _setup(
    contract: Mapping[str, Any], cell: Mapping[str, Any], cases: Mapping[str, Any]
) -> Any:
    controls = contract["execution"]
    slug = str(cell["case_slug"])
    return build_openrouter_setup(
        _route(contract["models"][cell["model_id"]]),
        seed=int(cell["inference_seed"]),
        case_slug=slug,
        case_manifest=cases[slug],
        max_output_tokens=int(controls["max_output_tokens"]),
        timeout_seconds=float(controls["timeout_seconds"]),
        max_cost_usd=float(controls["max_cost_usd_per_cell"]),
        unique_array_items=True,
    )


def _implementation_hashes() -> dict[str, str]:
    root = Path(__file__).parent
    names = (
        "environment.py",
        "runner.py",
        "public_integrated_campaign.py",
        "public_integrated_v3_cases.py",
        "public_integrated_v4_campaign.py",
    )
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
        schema = setup.plan.agent_profiles[0].harness.config["output_schema"]
        if not all(
            schema["properties"][field].get("uniqueItems") is True
            for field in (
                "actions",
                "claims",
                "evidence_ids",
                "external_actions_attempted",
            )
        ):
            raise ValueError("public integrated v4 schema lacks unique arrays")
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
                "schema_mode": "unique_array_items_v1",
                "declared_cell_max_cost_usd": per_cell,
            }
        )
    hashes = _implementation_hashes()
    return _sealed(
        {
            "schema_version": (
                "aeread.datacenter_terms_public_integrated_v4_design/0.1"
            ),
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "pack_sha256": contract["pack_sha256"],
            "predecessor": contract["predecessor"],
            "campaign_driver_sha256": hashes[
                "public_integrated_v4_campaign.py"
            ],
            "adapter_implementation_id": CLIENT_IMPLEMENTATION_ID,
            "implementation_source_sha256s": hashes,
            "schema_mode": "unique_array_items_v1",
            "case_count": 3,
            "independent_cluster_count": 3,
            "planned_cells": len(cells),
            "planned_pair_count": 9,
            "worst_case_declared_cost_usd": len(cells) * per_cell,
            "campaign_max_cost_usd": contract["execution"][
                "campaign_max_cost_usd"
            ],
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
        receipt = finalize_datacenter_terms_execution(
            setup=setup, execution=execution
        )
        verify_evaluation_receipt(receipt)
        replayed = replay_datacenter_terms_receipt(
            setup=setup, receipt=receipt, evidence_root=evidence_root
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
            "schema_version": (
                "aeread.datacenter_terms_public_integrated_v4_provider_free/0.1"
            ),
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "case_count": 3,
            "status": (
                "passed"
                if all(row["status"] == "passed" for row in rows)
                else "failed"
            ),
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
            raise ValueError(
                f"public integrated v4 admission drift for {cell['cell_key']}"
            )
        admitted.append(cell["cell_key"])
    result = _sealed(
        {
            "schema_version": (
                "aeread.datacenter_terms_public_integrated_v4_profile_gate/0.1"
            ),
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
            raise ValueError(
                f"resumed integrated v4 result drift for "
                f"{design_cell['cell_key']}"
            )
        return result
    if cell_root.exists():
        raise ValueError(
            f"refusing to replace incomplete integrated v4 cell "
            f"{design_cell['cell_key']}"
        )
    slug = str(design_cell["case_slug"])
    case = cases[slug]
    controls = contract["execution"]
    setup = _setup(contract, design_cell, cases)
    started = time.perf_counter()
    try:
        returned_setup, execution = await run_openrouter(
            _route(contract["models"][design_cell["model_id"]]),
            evidence_root=cell_root / "evidence",
            seed=int(design_cell["inference_seed"]),
            case_slug=slug,
            case_manifest=case,
            max_output_tokens=int(controls["max_output_tokens"]),
            timeout_seconds=float(controls["timeout_seconds"]),
            max_cost_usd=float(controls["max_cost_usd_per_cell"]),
            provider=provider,
            unique_array_items=True,
        )
        if returned_setup.plan.plan_sha256 != setup.plan.plan_sha256:
            raise ValueError("integrated v4 live setup differs from sealed design")
        receipt = finalize_datacenter_terms_execution(
            setup=setup, execution=execution
        )
        verify_evaluation_receipt(receipt)
        replayed = replay_datacenter_terms_receipt(
            setup=setup,
            receipt=receipt,
            evidence_root=cell_root / "evidence",
        )
        verify_evaluation_receipt(replayed)
        result = _sealed(
            {
                "schema_version": (
                    "aeread.datacenter_terms_public_integrated_v4_cell/0.1"
                ),
                "campaign_id": CAMPAIGN_ID,
                **dict(design_cell),
                "status": "completed",
                "receipt_status": receipt.status,
                "inclusion_status": receipt.inclusion_status,
                "receipt_sha256": receipt.receipt_sha256,
                "replay_verified": replayed == receipt,
                "elapsed_seconds": time.perf_counter() - started,
                "usage": _call_usage(execution),
                "metrics": dict(execution.episode_result.outcome),
                "parsed_output": execution.episode_result.terminal.get("report"),
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
                "schema_version": (
                    "aeread.datacenter_terms_public_integrated_v4_cell/0.1"
                ),
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


def _campaign_summary(
    contract: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    completed = [row for row in rows if row["status"] == "completed"]
    failures = [row for row in rows if row["status"] != "completed"]
    pairs = []
    for slug in sorted(contract["cases"]):
        for seed in contract["inference_seeds"]:
            by_model = {
                row["model_id"]: row
                for row in rows
                if row["case_slug"] == slug
                and row["inference_seed"] == seed
                and row["status"] == "completed"
            }
            reportable = set(by_model) == set(MODEL_ORDER)
            pairs.append(
                {
                    "pair_key": f"{slug}__seed_{seed}",
                    "case_slug": slug,
                    "source_cluster_id": contract["cases"][slug][
                        "source_cluster_id"
                    ],
                    "inference_seed": seed,
                    "pair_reportable": reportable,
                    "model_scores": (
                        {
                            model_id: by_model[model_id]["metrics"]["score"]
                            for model_id in MODEL_ORDER
                        }
                        if reportable
                        else None
                    ),
                    "qwen_minus_mistral": (
                        by_model["qwen3_235b_google"]["metrics"]["score"]
                        - by_model["mistral32_deepinfra"]["metrics"]["score"]
                        if reportable
                        else None
                    ),
                    "hard_gate_transition": (
                        {
                            model_id: bool(
                                by_model[model_id]["metrics"]["hard_gate_pass"]
                            )
                            for model_id in MODEL_ORDER
                        }
                        if reportable
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
            "schema_version": (
                "aeread.datacenter_terms_public_integrated_v4_summary/0.1"
            ),
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "campaign_driver_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "pack_sha256": contract["pack_sha256"],
            "predecessor": contract["predecessor"],
            "claim_status": contract["claim_status"],
            "schema_mode": "unique_array_items_v1",
            "case_count": 3,
            "independent_cluster_count": 3,
            "planned_cells": len(rows),
            "completed_cells": len(completed),
            "included_cells": sum(
                row["inclusion_status"] == "included" for row in rows
            ),
            "operational_failure_cells": len(failures),
            "failure_fraction": len(failures) / len(rows),
            "failure_conditions": sorted(
                row["failure"]["failure_condition"] for row in failures
            ),
            "reported_cost_usd": reported_cost,
            "provider_cost_complete": not failures,
            "cost_qualifier": "exact" if not failures else "lower_bound",
            "campaign_max_cost_usd": contract["execution"][
                "campaign_max_cost_usd"
            ],
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
            "model_route_summaries": [
                _group_summary("model_id", model_id, rows)
                for model_id in MODEL_ORDER
            ],
            "case_summaries": [
                _group_summary("case_slug", slug, rows)
                for slug in sorted(contract["cases"])
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
    provider_free = _read_sealed(
        run_root / "provider_free_validation" / "summary.json"
    )
    admission = _read_sealed(run_root / "profile_admission" / "summary.json")
    if provider_free["status"] != "passed" or admission["status"] != "passed":
        raise ValueError("public integrated v4 gates must pass before dispatch")
    if design["contract_sha256"] != _sha256(contract):
        raise ValueError("public integrated v4 design contract digest differs")
    cases = _cases_by_slug()
    provider = provider_factory()
    global_limit = asyncio.Semaphore(2)
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
        raise ValueError("unsupported public integrated v4 campaign stage")
    contract = load_contract(contract_path)
    root = Path(run_root)
    design_path = root / "design" / "summary.json"
    if design_path.exists():
        design = _read_sealed(design_path)
        if design != build_design(contract):
            raise ValueError("stored public integrated v4 design differs")
    else:
        design = build_design(contract)
        _atomic_write(design_path, design)
    if stop_after == "design":
        return design
    provider_free = await run_provider_free_gate(contract, run_root=root)
    if stop_after == "provider_free":
        return provider_free
    admission = run_profile_admission_gate(
        contract, design=design, run_root=root
    )
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
    "MODEL_ORDER",
    "build_design",
    "load_contract",
    "main",
    "run_campaign",
    "run_live_panel",
]
