"""Run the paired public data-center clause-mechanism wording campaign."""

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

from .campaign import _atomic_write, _call_usage, _read_sealed, _route, _sealed, _sha256
from .public_campaign import _group_summary
from .public_mechanism_cases import (
    CLUSTER_ID,
    PACK_ID,
    load_public_mechanism_cases,
    mechanism_and_condition,
    public_mechanism_pack_sha256,
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


CONTRACT_SCHEMA_VERSION = "aeread.datacenter_terms_public_mechanism_campaign/0.1"
CAMPAIGN_ID = "datacenter_development_terms_public_mechanism_v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT_PATH = REPOSITORY_ROOT / "configs" / f"{CAMPAIGN_ID}.json"
DEFAULT_RUN_ROOT = REPOSITORY_ROOT / "runs" / CAMPAIGN_ID
MODEL_ORDER = (
    "mistral32_deepinfra",
    "qwen3_235b_novita",
    "gptoss120b_coreweave",
)
CONDITION_ORDER = ("baseline", "affirm_only")
COMPONENT_NAMES = (
    "state_accuracy",
    "amount_accuracy",
    "required_action_recall",
    "required_claim_recall",
    "evidence_coverage",
)


def load_contract(path: Path | str = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    frozen = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "campaign_id": CAMPAIGN_ID,
        "family_id": "datacenter_development_terms_v1",
        "family_version": "1.0.0",
        "pack_id": PACK_ID,
        "pack_sha256": public_mechanism_pack_sha256(),
        "claim_status": (
            "within_source_clause_decomposition_and_affirm_only_wording_diagnostic"
        ),
    }
    if not isinstance(contract, dict) or any(
        contract.get(key) != value for key, value in frozen.items()
    ):
        raise ValueError("public mechanism campaign identity differs")
    if set(contract) != {
        *frozen,
        "route_catalog_snapshot",
        "cases",
        "inference_seeds",
        "models",
        "execution",
        "analysis",
    }:
        raise ValueError("public mechanism campaign fields differ")

    snapshot = contract["route_catalog_snapshot"]
    expected_sources = [
        "https://openrouter.ai/api/v1/models/"
        "mistralai/mistral-small-3.2-24b-instruct/endpoints",
        "https://openrouter.ai/api/v1/models/qwen/qwen3-235b-a22b-2507/endpoints",
        "https://openrouter.ai/api/v1/models/openai/gpt-oss-120b/endpoints",
    ]
    if (
        not isinstance(snapshot, Mapping)
        or set(snapshot) != {"verified_at", "sources", "selection_rule"}
        or snapshot["sources"] != expected_sources
        or not str(snapshot["verified_at"]).endswith("Z")
    ):
        raise ValueError("public mechanism route snapshot differs")

    cases = _cases_by_slug()
    if set(contract["cases"]) != set(cases) or len(cases) != 6:
        raise ValueError("public mechanism case set differs")
    for slug, case in cases.items():
        mechanism, condition = mechanism_and_condition(slug)
        if contract["cases"][slug] != {
            "case_id": case.case_id,
            "expected_case_sha256": case.content_sha256,
            "mechanism_id": mechanism,
            "wording_condition": condition,
            "world_seed": case.world_seed,
        }:
            raise ValueError(f"{slug}: public mechanism case contract differs")
    if contract["inference_seeds"] != [315001, 315002, 315003]:
        raise ValueError("public mechanism inference seeds differ")

    expected_routes = {
        "mistral32_deepinfra": (
            "mistralai/mistral-small-3.2-24b-instruct",
            "mistralai/mistral-small-3.2-24b-instruct-2506",
            "DeepInfra",
            "fp8",
            None,
            0.075,
            0.075,
            0.2,
            "datacenter_terms_mechanism_mistral32_deepinfra_v1",
            "openrouter_2026-09-03_mistral32_deepinfra_terms_mechanism_v1",
            "0.075",
            "0.2",
        ),
        "qwen3_235b_novita": (
            "qwen/qwen3-235b-a22b-2507",
            "qwen/qwen3-235b-a22b-07-25",
            "Novita",
            "fp8",
            None,
            0.09,
            0.09,
            0.58,
            "datacenter_terms_mechanism_qwen3_235b_novita_v1",
            "openrouter_2026-09-03_qwen3_novita_terms_mechanism_v1",
            "0.09",
            "0.58",
        ),
        "gptoss120b_coreweave": (
            "openai/gpt-oss-120b",
            "openai/gpt-oss-120b",
            "CoreWeave",
            "fp4",
            "low",
            0.03,
            0.03,
            0.17,
            "datacenter_terms_mechanism_gptoss120b_coreweave_v1",
            "openrouter_2026-09-03_gptoss120b_coreweave_terms_mechanism_v1",
            "0.03",
            "0.17",
        ),
    }
    if set(contract["models"]) != set(expected_routes):
        raise ValueError("public mechanism model panel differs")
    for model_id, expected in expected_routes.items():
        model = contract["models"][model_id]
        pricing = model.get("pricing")
        actual = (
            model.get("requested_model"),
            model.get("canonical_model"),
            model.get("provider"),
            model.get("quantization"),
            model.get("reasoning_effort"),
            pricing.get("input_per_million") if isinstance(pricing, Mapping) else None,
            pricing.get("cached_input_per_million")
            if isinstance(pricing, Mapping)
            else None,
            pricing.get("output_per_million") if isinstance(pricing, Mapping) else None,
            model.get("profile_id"),
            pricing.get("pricing_id") if isinstance(pricing, Mapping) else None,
            model.get("max_prompt_price_per_million"),
            model.get("max_completion_price_per_million"),
        )
        if (
            actual != expected
            or model.get("access_class") != "open_source"
            or model.get("license_id") != "Apache-2.0"
            or model.get("temperature_supported") is not True
            or not isinstance(pricing, Mapping)
            or set(pricing)
            != {
                "input_per_million",
                "cached_input_per_million",
                "output_per_million",
                "pricing_id",
            }
        ):
            raise ValueError(f"{model_id}: public mechanism route differs")

    required_execution = {
        "harness": "minimal_chat/1.0",
        "adapter": CLIENT_IMPLEMENTATION_ID,
        "max_output_tokens": 900,
        "timeout_seconds": 180.0,
        "max_cost_usd_per_cell": 0.02,
        "campaign_max_cost_usd": 1.08,
        "concurrency": 3,
        "max_concurrent_cells_per_route_provider": 1,
        "max_action_attempts": 1,
        "sdk_retries": 0,
        "response_cache": False,
        "provider_fallbacks": False,
    }
    if contract["execution"] != required_execution:
        raise ValueError("public mechanism execution controls differ")
    planned = len(cases) * len(contract["inference_seeds"]) * len(MODEL_ORDER)
    if planned != 54 or planned * 0.02 > 1.08:
        raise ValueError("public mechanism campaign cost ceiling differs")

    required_analysis = {
        "case_count": 6,
        "mechanism_count": 3,
        "wording_condition_count": 2,
        "independent_cluster_count": 1,
        "resampling_unit": "single_public_filing_cluster",
        "paired_by": ["mechanism_id", "model_id", "inference_seed"],
        "contrast": "affirm_only_minus_baseline",
        "missingness": "report_separately_and_require_both_wording_conditions",
        "winner_claim_allowed": False,
        "inferential_model_ranking_allowed": False,
        "project_generalization_allowed": False,
        "population_causal_effect_allowed": False,
    }
    if contract["analysis"] != required_analysis:
        raise ValueError("public mechanism analysis contract differs")
    return contract


def _cases_by_slug() -> dict[str, Any]:
    return {
        case.case_id.rsplit(".", 1)[-1]: case
        for case in load_public_mechanism_cases()
    }


def _cells(contract: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "cell_key": f"{slug}__{model_id}__seed_{seed}",
            "pair_key": (
                f"{spec['mechanism_id']}__{model_id}__seed_{seed}"
            ),
            "case_slug": slug,
            "mechanism_id": spec["mechanism_id"],
            "wording_condition": spec["wording_condition"],
            "source_cluster_id": CLUSTER_ID,
            "world_seed": spec["world_seed"],
            "model_id": model_id,
            "inference_seed": seed,
        }
        for slug, spec in sorted(contract["cases"].items())
        for seed in contract["inference_seeds"]
        for model_id in MODEL_ORDER
    )


def _setup(
    contract: Mapping[str, Any],
    cell: Mapping[str, Any],
    cases: Mapping[str, Any],
) -> Any:
    controls = contract["execution"]
    return build_openrouter_setup(
        _route(contract["models"][cell["model_id"]]),
        seed=int(cell["inference_seed"]),
        case_slug=str(cell["case_slug"]),
        case_manifest=cases[str(cell["case_slug"])],
        max_output_tokens=int(controls["max_output_tokens"]),
        timeout_seconds=float(controls["timeout_seconds"]),
        max_cost_usd=float(controls["max_cost_usd_per_cell"]),
    )


def _implementation_hashes() -> dict[str, str]:
    root = Path(__file__).parent
    names = (
        "environment.py",
        "runner.py",
        "public_mechanism_cases.py",
        "public_mechanism_campaign.py",
    )
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in names
    }


def build_design(contract: Mapping[str, Any]) -> dict[str, Any]:
    cases = _cases_by_slug()
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
                "declared_cell_max_cost_usd": 0.02,
            }
        )
    hashes = _implementation_hashes()
    return _sealed(
        {
            "schema_version": "aeread.datacenter_terms_public_mechanism_design/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "pack_sha256": public_mechanism_pack_sha256(),
            "campaign_driver_sha256": hashes["public_mechanism_campaign.py"],
            "adapter_implementation_id": CLIENT_IMPLEMENTATION_ID,
            "implementation_source_sha256s": hashes,
            "case_count": 6,
            "mechanism_count": 3,
            "wording_condition_count": 2,
            "independent_cluster_count": 1,
            "planned_cells": len(cells),
            "planned_pair_count": 27,
            "worst_case_declared_cost_usd": len(cells) * 0.02,
            "campaign_max_cost_usd": 1.08,
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
    for slug, case in _cases_by_slug().items():
        setup = build_offline_setup(case_slug=slug, case_manifest=case)
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
            "schema_version": (
                "aeread.datacenter_terms_public_mechanism_provider_free_gate/0.1"
            ),
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
            raise ValueError(f"mechanism profile admission drift for {cell['cell_key']}")
        admitted.append(cell["cell_key"])
    result = _sealed(
        {
            "schema_version": (
                "aeread.datacenter_terms_public_mechanism_profile_gate/0.1"
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
    cell: Mapping[str, Any],
    *,
    cases: Mapping[str, Any],
    run_root: Path,
    provider: Any,
) -> dict[str, Any]:
    cell_root = run_root / "live" / str(cell["cell_key"])
    path = cell_root / "result.json"
    if path.exists():
        result = _read_sealed(path)
        if result["run_plan_sha256"] != cell["run_plan_sha256"]:
            raise ValueError(f"resumed mechanism result drift for {cell['cell_key']}")
        return result
    if cell_root.exists():
        raise ValueError(f"refusing to replace incomplete mechanism cell {cell['cell_key']}")
    case = cases[str(cell["case_slug"])]
    route = _route(contract["models"][cell["model_id"]])
    controls = contract["execution"]
    setup = _setup(contract, cell, cases)
    started = time.perf_counter()
    try:
        returned_setup, execution = await run_openrouter(
            route,
            evidence_root=cell_root / "evidence",
            seed=int(cell["inference_seed"]),
            case_slug=str(cell["case_slug"]),
            case_manifest=case,
            max_output_tokens=int(controls["max_output_tokens"]),
            timeout_seconds=float(controls["timeout_seconds"]),
            max_cost_usd=float(controls["max_cost_usd_per_cell"]),
            provider=provider,
        )
        if returned_setup.plan.plan_sha256 != setup.plan.plan_sha256:
            raise ValueError("mechanism live setup differs from sealed design")
        receipt = finalize_datacenter_terms_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_datacenter_terms_receipt(
            setup=setup,
            receipt=receipt,
            evidence_root=cell_root / "evidence",
        )
        result = _sealed(
            {
                "schema_version": "aeread.datacenter_terms_public_mechanism_cell/0.1",
                "campaign_id": CAMPAIGN_ID,
                **dict(cell),
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
                "schema_version": "aeread.datacenter_terms_public_mechanism_cell/0.1",
                "campaign_id": CAMPAIGN_ID,
                **dict(cell),
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
    _atomic_write(path, result)
    return result


def _condition_pairs(
    contract: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    indexed = {
        (
            row["mechanism_id"],
            row["model_id"],
            row["inference_seed"],
            row["wording_condition"],
        ): row
        for row in rows
    }
    pairs = []
    mechanisms = sorted({spec["mechanism_id"] for spec in contract["cases"].values()})
    for mechanism in mechanisms:
        for model_id in MODEL_ORDER:
            for seed in contract["inference_seeds"]:
                baseline = indexed[(mechanism, model_id, seed, "baseline")]
                affirm = indexed[(mechanism, model_id, seed, "affirm_only")]
                usable = baseline["status"] == affirm["status"] == "completed"
                if usable:
                    base_metrics = baseline["metrics"]
                    affirm_metrics = affirm["metrics"]
                    base_forbidden = len(base_metrics["forbidden_actions"]) + len(
                        base_metrics["forbidden_claims"]
                    )
                    affirm_forbidden = len(affirm_metrics["forbidden_actions"]) + len(
                        affirm_metrics["forbidden_claims"]
                    )
                pairs.append(
                    {
                        "pair_key": f"{mechanism}__{model_id}__seed_{seed}",
                        "mechanism_id": mechanism,
                        "model_id": model_id,
                        "inference_seed": seed,
                        "pair_reportable": usable,
                        "baseline_cell_key": baseline["cell_key"],
                        "affirm_only_cell_key": affirm["cell_key"],
                        "baseline_score": base_metrics["score"] if usable else None,
                        "affirm_only_score": affirm_metrics["score"] if usable else None,
                        "score_delta": (
                            affirm_metrics["score"] - base_metrics["score"]
                            if usable
                            else None
                        ),
                        "baseline_hard_gate_pass": (
                            base_metrics["hard_gate_pass"] if usable else None
                        ),
                        "affirm_only_hard_gate_pass": (
                            affirm_metrics["hard_gate_pass"] if usable else None
                        ),
                        "hard_gate_rescue": (
                            not base_metrics["hard_gate_pass"]
                            and affirm_metrics["hard_gate_pass"]
                            if usable
                            else None
                        ),
                        "hard_gate_regression": (
                            base_metrics["hard_gate_pass"]
                            and not affirm_metrics["hard_gate_pass"]
                            if usable
                            else None
                        ),
                        "baseline_forbidden_selection_count": (
                            base_forbidden if usable else None
                        ),
                        "affirm_only_forbidden_selection_count": (
                            affirm_forbidden if usable else None
                        ),
                        "forbidden_selection_delta": (
                            affirm_forbidden - base_forbidden if usable else None
                        ),
                        "component_deltas": (
                            {
                                name: affirm_metrics[name] - base_metrics[name]
                                for name in COMPONENT_NAMES
                            }
                            if usable
                            else None
                        ),
                    }
                )
    return pairs


def _contrast_summary(
    field: str,
    value: str,
    pairs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    selected = [pair for pair in pairs if pair[field] == value]
    reportable = [pair for pair in selected if pair["pair_reportable"]]
    return {
        field: value,
        "planned_pairs": len(selected),
        "reportable_pairs": len(reportable),
        "missing_pairs": len(selected) - len(reportable),
        "mean_score_delta": (
            statistics.fmean(float(pair["score_delta"]) for pair in reportable)
            if reportable
            else None
        ),
        "baseline_hard_gate_pass_rate": (
            statistics.fmean(
                1.0 if pair["baseline_hard_gate_pass"] else 0.0
                for pair in reportable
            )
            if reportable
            else None
        ),
        "affirm_only_hard_gate_pass_rate": (
            statistics.fmean(
                1.0 if pair["affirm_only_hard_gate_pass"] else 0.0
                for pair in reportable
            )
            if reportable
            else None
        ),
        "hard_gate_rescues": sum(pair["hard_gate_rescue"] is True for pair in reportable),
        "hard_gate_regressions": sum(
            pair["hard_gate_regression"] is True for pair in reportable
        ),
        "mean_forbidden_selection_delta": (
            statistics.fmean(
                float(pair["forbidden_selection_delta"]) for pair in reportable
            )
            if reportable
            else None
        ),
    }


def _campaign_summary(
    contract: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    completed = [row for row in rows if row["status"] == "completed"]
    failures = [row for row in rows if row["status"] != "completed"]
    pairs = _condition_pairs(contract, rows)
    cost = math.fsum(
        float(row["usage"]["reported_cost_usd"])
        for row in completed
        if row["usage"] is not None
    )
    return _sealed(
        {
            "schema_version": "aeread.datacenter_terms_public_mechanism_summary/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "campaign_driver_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "claim_status": contract["claim_status"],
            "case_count": 6,
            "mechanism_count": 3,
            "wording_condition_count": 2,
            "independent_cluster_count": 1,
            "planned_cells": len(rows),
            "completed_cells": len(completed),
            "included_cells": sum(row["inclusion_status"] == "included" for row in rows),
            "operational_failure_cells": len(failures),
            "failure_fraction": len(failures) / len(rows),
            "failure_conditions": sorted(
                row["failure"]["failure_condition"] for row in failures
            ),
            "reported_cost_usd": cost,
            "provider_cost_complete": not failures,
            "cost_qualifier": "exact" if not failures else "lower_bound",
            "campaign_max_cost_usd": contract["execution"]["campaign_max_cost_usd"],
            "within_declared_campaign_cost_ceiling": (
                cost <= contract["execution"]["campaign_max_cost_usd"]
            ),
            "all_completed_receipts_replayed": all(
                row["replay_verified"] for row in completed
            ),
            "model_summaries": [
                _group_summary("model_id", model_id, rows) for model_id in MODEL_ORDER
            ],
            "condition_summaries": [
                _group_summary("wording_condition", condition, rows)
                for condition in CONDITION_ORDER
            ],
            "mechanism_summaries": [
                _group_summary("mechanism_id", mechanism, rows)
                for mechanism in sorted(
                    {spec["mechanism_id"] for spec in contract["cases"].values()}
                )
            ],
            "paired_wording_contrasts": pairs,
            "reportable_pair_count": sum(pair["pair_reportable"] for pair in pairs),
            "model_contrast_summaries": [
                _contrast_summary("model_id", model_id, pairs)
                for model_id in MODEL_ORDER
            ],
            "mechanism_contrast_summaries": [
                _contrast_summary("mechanism_id", mechanism, pairs)
                for mechanism in sorted(
                    {spec["mechanism_id"] for spec in contract["cases"].values()}
                )
            ],
            "winner_claim_allowed": False,
            "inferential_model_ranking_allowed": False,
            "project_generalization_allowed": False,
            "population_causal_effect_allowed": False,
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
        raise ValueError("public mechanism gates must pass before live dispatch")
    if design["contract_sha256"] != _sha256(contract):
        raise ValueError("public mechanism design contract differs")
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
        raise ValueError("unsupported public mechanism campaign stage")
    contract = load_contract(contract_path)
    root = Path(run_root)
    design_path = root / "design" / "summary.json"
    if design_path.exists():
        design = _read_sealed(design_path)
        if design != build_design(contract):
            raise ValueError("stored public mechanism design differs")
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
    "CONDITION_ORDER",
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
