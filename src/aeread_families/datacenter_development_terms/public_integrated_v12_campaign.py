"""Run the unit-explicit Qwen versus GPT-OSS data-center terms campaign."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.receipts import verify_evaluation_receipt
from aeread_families.datacenter_development.objective_openrouter import (
    INDICATOR_MAP_CLIENT_IMPLEMENTATION_ID,
    IndicatorMapOpenRouterClient,
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
from .public_integrated_expansion_v3_cases import (
    public_integrated_expansion_v3_pack_sha256,
)
from .public_integrated_expansion_v4_cases import (
    CURRENCY_BASE_UNIT_FIELDS,
    PACK_ID,
    load_public_integrated_expansion_v4_cases,
    public_integrated_expansion_v4_pack_sha256,
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
    "aeread.datacenter_terms_public_integrated_v12_campaign/0.1"
)
CAMPAIGN_ID = "datacenter_development_terms_public_integrated_v12"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT_PATH = REPOSITORY_ROOT / "configs" / f"{CAMPAIGN_ID}.json"
DEFAULT_RUN_ROOT = REPOSITORY_ROOT / "runs" / CAMPAIGN_ID
PREDECESSOR_RUN_ROOT = (
    REPOSITORY_ROOT / "runs" / "datacenter_development_terms_public_integrated_v11"
)
PREDECESSOR_PUBLICATION_ROOT = (
    REPOSITORY_ROOT / "evidence" / "datacenter_development_terms_public_integrated_v11"
)
GPTOSS_HISTORY_RUN_ROOT = (
    REPOSITORY_ROOT / "runs" / "datacenter_development_terms_public_gptoss_v1"
)
GPTOSS_HISTORY_PUBLICATION_ROOT = (
    REPOSITORY_ROOT / "evidence" / "datacenter_development_terms_public_gptoss_v1"
)
MODEL_ORDER = ("gptoss120b_coreweave", "qwen3_235b_google")


def _cases_by_slug() -> dict[str, Any]:
    return {
        case.case_id.rsplit(".", 1)[-1]: case
        for case in load_public_integrated_expansion_v4_cases()
    }


def _expected_corrections() -> tuple[dict[str, Any], dict[str, Any]]:
    answerability = {
        "base_pack_id": "datacenter_development_terms_public_integrated_expansion_v2",
        "base_pack_sha256": (
            "ffde8e79e9bb4a6baca981f0ae0d979507368469d976421a910dc4d35f980acb"
        ),
        "corrected_pack_id": "datacenter_development_terms_public_integrated_expansion_v3",
        "corrected_pack_sha256": public_integrated_expansion_v3_pack_sha256(),
        "case_slug": "tydal-open-book-epc-governance-and-risk",
        "evidence_id": "e05",
        "oracle_field": "amounts.invoice_payment_day",
        "visible_value_restored": 22.0,
        "full_panel_replacement": True,
    }
    numeric_units = {
        "base_pack_id": "datacenter_development_terms_public_integrated_expansion_v3",
        "base_pack_sha256": public_integrated_expansion_v3_pack_sha256(),
        "corrected_pack_id": PACK_ID,
        "corrected_pack_sha256": public_integrated_expansion_v4_pack_sha256(),
        "visible_rule": (
            "monetary_amounts_use_base_currency_units_other_amounts_use_key_named_units"
        ),
        "affected_v8_case_slug": (
            "lake-mariner-lease-commencement-prepaid-rent-and-land"
        ),
        "affected_v8_currency_fields": list(
            CURRENCY_BASE_UNIT_FIELDS[
                "lake-mariner-lease-commencement-prepaid-rent-and-land"
            ]
        ),
        "full_panel_replacement": True,
    }
    return answerability, numeric_units


def _validate_lineage(contract: Mapping[str, Any]) -> None:
    predecessor = {
        "campaign_id": "datacenter_development_terms_public_integrated_v11",
        "contract_sha256": (
            "a5232a77b91176b75ed7c9650dc047fbf007f79140a9ca848f1331cdae97e73d"
        ),
        "design_sha256": (
            "ce19f7ffc09dcdf09ee9520be36261aef16c03b4b55497b228db79c6b681c0e5"
        ),
        "live_summary_sha256": (
            "cbb728a9fc3cbd97908ee960ccf9f6bd02388436bb8a183efcccae4f21e00b41"
        ),
        "public_evidence_sha256": (
            "833d22bfb73fce63d533dcf2e4f1261f2e7289663ee5a1c0bd0260015d0961c7"
        ),
        "status": "unit_explicit_provider_order_diagnostic_five_of_six_complete",
        "comparison_scope": "audit_lineage_only_not_analysis_data",
    }
    if contract.get("predecessor") != predecessor:
        raise ValueError("public integrated v12 predecessor lineage differs")
    history = {
        "campaign_id": "datacenter_development_terms_public_gptoss_v1",
        "contract_sha256": (
            "ecba97f8281d7c0782dfcb36e3b4c143d3944fdb9c7dc0d4b9e7b55ac9f77e6f"
        ),
        "design_sha256": (
            "617dd2abd7d9b64c757d4221aef8b2d2447b2a314084349d8a344648fd23e6c1"
        ),
        "live_summary_sha256": (
            "08eafb806bf80cf0f1be0d91021e2a4ee598d482cf16d50cefb425a0576c36cc"
        ),
        "public_evidence_sha256": (
            "1f369655c625bc9a63ca13cdf16eff24fda15068fad5dcb7b5814fcd1645ba6c"
        ),
        "completed_cells": 15,
        "planned_cells": 15,
        "reported_cost_usd": 0.0018843759,
        "comparison_scope": "route_qualification_history_only_different_case_pack",
    }
    if contract.get("gptoss_route_history") != history:
        raise ValueError("public integrated v12 GPT-OSS history differs")
    local_checks = {
        predecessor["design_sha256"]: PREDECESSOR_RUN_ROOT / "design" / "summary.json",
        predecessor["live_summary_sha256"]: PREDECESSOR_RUN_ROOT / "live" / "summary.json",
        predecessor["public_evidence_sha256"]: (
            PREDECESSOR_PUBLICATION_ROOT / "publication_manifest.json"
        ),
        history["design_sha256"]: GPTOSS_HISTORY_RUN_ROOT / "design" / "summary.json",
        history["live_summary_sha256"]: GPTOSS_HISTORY_RUN_ROOT / "live" / "summary.json",
        history["public_evidence_sha256"]: (
            GPTOSS_HISTORY_PUBLICATION_ROOT / "publication_manifest.json"
        ),
    }
    for expected_hash, path in local_checks.items():
        if path.exists() and _read_sealed(path)["artifact_sha256"] != expected_hash:
            raise ValueError(f"public integrated v12 lineage differs: {path}")


def load_contract(path: Path | str = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("public integrated v12 contract must be an object")
    expected_scalars = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "campaign_id": CAMPAIGN_ID,
        "family_id": "datacenter_development_terms_v1",
        "family_version": "1.0.0",
        "pack_id": PACK_ID,
        "pack_sha256": public_integrated_expansion_v4_pack_sha256(),
        "claim_status": (
            "unit_explicit_qwen_gptoss_indicator_map_three_project_two_route_"
            "paired_exploratory"
        ),
    }
    for field, expected in expected_scalars.items():
        if value.get(field) != expected:
            raise ValueError(f"public integrated v12 {field} differs")
    if value.get("inference_seeds") != [422106]:
        raise ValueError("public integrated v12 seeds differ")
    _validate_lineage(value)
    answerability, numeric_units = _expected_corrections()
    if value.get("answerability_correction") != answerability:
        raise ValueError("public integrated v12 answerability correction differs")
    if value.get("numeric_unit_correction") != numeric_units:
        raise ValueError("public integrated v12 numeric unit correction differs")
    expected_snapshot = {
        "verified_at": "2026-09-03T20:56:41Z",
        "sources": [
            "https://openrouter.ai/api/v1/models/openai/gpt-oss-120b/endpoints",
            "https://openrouter.ai/api/v1/models/qwen/qwen3-235b-a22b-2507/endpoints",
        ],
        "selection_rule": (
            "pin_active_apache_2_routes_supporting_seed_response_format_"
            "structured_outputs_and_price_caps_with_no_fallback"
        ),
        "selected_endpoints": {
            "gptoss120b_coreweave": {
                "provider": "CoreWeave",
                "tag": "coreweave/fp4",
                "quantization": "fp4",
                "status": 0,
                "uptime_last_30m": 99.95548080728136,
                "required_parameters": [
                    "seed",
                    "response_format",
                    "structured_outputs",
                    "reasoning_effort",
                ],
            },
            "qwen3_235b_google": {
                "provider": "Google",
                "tag": "google-vertex/us-south1",
                "quantization": "unknown",
                "status": 0,
                "uptime_last_30m": 99.93574090733838,
                "required_parameters": [
                    "seed",
                    "response_format",
                    "structured_outputs",
                ],
            },
        },
    }
    if value.get("route_catalog_snapshot") != expected_snapshot:
        raise ValueError("public integrated v12 route snapshot differs")
    cases = _cases_by_slug()
    expected_cases = {
        slug: {
            "case_id": case.case_id,
            "expected_case_sha256": case.content_sha256,
            "source_cluster_id": case.payload["public_case"][
                "independence_cluster_id"
            ],
            "world_seed": case.world_seed,
        }
        for slug, case in cases.items()
    }
    if value.get("cases") != expected_cases:
        raise ValueError("public integrated v12 cases differ")
    common = {
        "access_class": "open_source",
        "license_id": "Apache-2.0",
        "temperature_supported": True,
    }
    expected_models = {
        "gptoss120b_coreweave": {
            "profile_id": "datacenter_terms_integrated_v12_gptoss120b_coreweave",
            "requested_model": "openai/gpt-oss-120b",
            "canonical_model": "openai/gpt-oss-120b",
            "provider": "CoreWeave",
            "quantization": "fp4",
            **common,
            "reasoning_effort": "low",
            "pricing": {
                "input_per_million": 0.03,
                "cached_input_per_million": 0.03,
                "output_per_million": 0.17,
                "pricing_id": (
                    "openrouter_2026-09-03_gptoss120b_coreweave_terms_"
                    "integrated_v12"
                ),
            },
            "max_prompt_price_per_million": "0.03",
            "max_completion_price_per_million": "0.17",
        },
        "qwen3_235b_google": {
            "profile_id": "datacenter_terms_integrated_v12_qwen3_235b_google",
            "requested_model": "qwen/qwen3-235b-a22b-2507",
            "canonical_model": "qwen/qwen3-235b-a22b-07-25",
            "provider": "Google",
            "quantization": "unknown",
            **common,
            "reasoning_effort": None,
            "pricing": {
                "input_per_million": 0.22,
                "cached_input_per_million": 0.22,
                "output_per_million": 0.88,
                "pricing_id": (
                    "openrouter_2026-09-03_qwen3_google_terms_integrated_v12"
                ),
            },
            "max_prompt_price_per_million": "0.22",
            "max_completion_price_per_million": "0.88",
        },
    }
    if value.get("models") != expected_models:
        raise ValueError("public integrated v12 models differ")
    expected_execution = {
        "harness": "minimal_chat/1.0",
        "adapter": INDICATOR_MAP_CLIENT_IMPLEMENTATION_ID,
        "schema_mode": "complete_indicator_maps_v1",
        "indicator_maps": True,
        "max_output_tokens": 1200,
        "timeout_seconds": 180.0,
        "max_cost_usd_per_cell": 0.025,
        "campaign_max_cost_usd": 0.15,
        "concurrency": 2,
        "max_concurrent_cells_per_route_provider": 1,
        "provider_schedule": "deterministic_route_queues_parallel_across_providers",
        "provider_cooldown_seconds_after_attempt": {
            "CoreWeave": 0.0,
            "Google": 0.0,
        },
        "provider_case_order": {
            provider: [
                "helios-phased-capacity-revenue-and-draws",
                "lake-mariner-lease-commencement-prepaid-rent-and-land",
                "tydal-open-book-epc-governance-and-risk",
            ]
            for provider in ("CoreWeave", "Google")
        },
        "max_action_attempts": 1,
        "sdk_retries": 0,
        "response_cache": False,
        "provider_fallbacks": False,
    }
    if value.get("execution") != expected_execution:
        raise ValueError("public integrated v12 execution controls differ")
    expected_analysis = {
        "case_count": 3,
        "independent_cluster_count": 3,
        "resampling_unit": "public_filing_project_cluster",
        "replicate_policy": (
            "one_fresh_predeclared_paired_seed_full_panel_unit_explicit_"
            "qwen_gptoss"
        ),
        "paired_by": ["case_slug", "inference_seed"],
        "primary_contrast": (
            "qwen3_235b_google_minus_gptoss120b_coreweave"
        ),
        "primary_endpoints": [
            "hard_gate_pass",
            "score",
            "forbidden_selection_count",
        ],
        "missingness": (
            "report_separately_and_require_both_routes_for_pair_no_selective_retry"
        ),
        "replacement_scope": "fresh_two_model_full_panel_not_bridge_or_retry",
        "winner_claim_allowed": False,
        "inferential_model_ranking_allowed": False,
        "project_generalization_allowed": False,
        "population_causal_effect_allowed": False,
    }
    if value.get("analysis") != expected_analysis:
        raise ValueError("public integrated v12 analysis contract differs")
    return value


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
        indicator_maps=True,
    )


def _implementation_hashes() -> dict[str, str]:
    root = Path(__file__).parent
    paths = {
        "environment.py": root / "environment.py",
        "runner.py": root / "runner.py",
        "objective_openrouter.py": (
            root.parent / "datacenter_development" / "objective_openrouter.py"
        ),
        "public_integrated_campaign.py": root / "public_integrated_campaign.py",
        "public_integrated_expansion_v4_cases.py": (
            root / "public_integrated_expansion_v4_cases.py"
        ),
        "public_integrated_v12_campaign.py": (
            root / "public_integrated_v12_campaign.py"
        ),
    }
    return {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in paths.items()
    }


def build_design(contract: Mapping[str, Any]) -> dict[str, Any]:
    cases = _cases_by_slug()
    per_cell = float(contract["execution"]["max_cost_usd_per_cell"])
    cells = []
    for cell in _cells(contract):
        setup = _setup(contract, cell, cases)
        plan_cell = setup.plan.cells[0]
        schema = setup.plan.agent_profiles[0].harness.config["output_schema"]
        for field in ("actions", "claims", "evidence_ids"):
            indicator = schema["properties"][field]
            if (
                indicator.get("type") != "object"
                or set(indicator.get("required", []))
                != set(indicator.get("properties", {}))
                or not all(
                    spec == {"type": "boolean"}
                    for spec in indicator.get("properties", {}).values()
                )
            ):
                raise ValueError("public integrated v12 indicator schema differs")
        if schema["properties"]["external_actions_attempted"]["properties"] != {
            "any": {"type": "boolean"}
        }:
            raise ValueError("public integrated v12 external indicator differs")
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
                "schema_mode": "complete_indicator_maps_v1",
                "declared_cell_max_cost_usd": per_cell,
            }
        )
    worst_case_cost = round(len(cells) * per_cell, 12)
    campaign_max = float(contract["execution"]["campaign_max_cost_usd"])
    if worst_case_cost > campaign_max:
        raise ValueError("public integrated v12 declared costs exceed campaign max")
    hashes = _implementation_hashes()
    return _sealed(
        {
            "schema_version": (
                "aeread.datacenter_terms_public_integrated_v12_design/0.1"
            ),
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "pack_sha256": contract["pack_sha256"],
            "predecessor": contract["predecessor"],
            "gptoss_route_history": contract["gptoss_route_history"],
            "answerability_correction": contract["answerability_correction"],
            "numeric_unit_correction": contract["numeric_unit_correction"],
            "campaign_driver_sha256": hashes[
                "public_integrated_v12_campaign.py"
            ],
            "adapter_implementation_id": INDICATOR_MAP_CLIENT_IMPLEMENTATION_ID,
            "implementation_source_sha256s": hashes,
            "schema_mode": "complete_indicator_maps_v1",
            "case_count": 3,
            "independent_cluster_count": 3,
            "planned_cells": len(cells),
            "planned_pair_count": 3,
            "worst_case_declared_cost_usd": worst_case_cost,
            "campaign_max_cost_usd": campaign_max,
            "provider_schedule": contract["execution"]["provider_schedule"],
            "provider_cooldown_seconds_after_attempt": contract["execution"][
                "provider_cooldown_seconds_after_attempt"
            ],
            "provider_case_order": contract["execution"]["provider_case_order"],
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
                "aeread.datacenter_terms_public_integrated_v12_provider_free/0.1"
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
            raise ValueError(f"public integrated v12 admission drift: {cell['cell_key']}")
        admitted.append(cell["cell_key"])
    result = _sealed(
        {
            "schema_version": (
                "aeread.datacenter_terms_public_integrated_v12_profile_gate/0.1"
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
            raise ValueError(f"resumed v12 result drift: {design_cell['cell_key']}")
        return result
    if cell_root.exists():
        raise ValueError(
            f"refusing to replace incomplete v12 cell {design_cell['cell_key']}"
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
            indicator_maps=True,
        )
        if returned_setup.plan.plan_sha256 != setup.plan.plan_sha256:
            raise ValueError("public integrated v12 live setup differs")
        receipt = finalize_datacenter_terms_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_datacenter_terms_receipt(
            setup=setup, receipt=receipt, evidence_root=cell_root / "evidence"
        )
        verify_evaluation_receipt(replayed)
        result = _sealed(
            {
                "schema_version": (
                    "aeread.datacenter_terms_public_integrated_v12_cell/0.1"
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
                    "aeread.datacenter_terms_public_integrated_v12_cell/0.1"
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
                    "qwen_minus_gptoss": (
                        by_model["qwen3_235b_google"]["metrics"]["score"]
                        - by_model["gptoss120b_coreweave"]["metrics"]["score"]
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
                "aeread.datacenter_terms_public_integrated_v12_summary/0.1"
            ),
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "campaign_driver_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "pack_sha256": contract["pack_sha256"],
            "predecessor": contract["predecessor"],
            "gptoss_route_history": contract["gptoss_route_history"],
            "answerability_correction": contract["answerability_correction"],
            "numeric_unit_correction": contract["numeric_unit_correction"],
            "claim_status": contract["claim_status"],
            "schema_mode": "complete_indicator_maps_v1",
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
            "provider_schedule": contract["execution"]["provider_schedule"],
            "provider_cooldown_seconds_after_attempt": contract["execution"][
                "provider_cooldown_seconds_after_attempt"
            ],
            "provider_case_order": contract["execution"]["provider_case_order"],
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


def _ordered_provider_cells(
    contract: Mapping[str, Any],
    cells: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[Mapping[str, Any], ...]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {
        model["provider"]: [] for model in contract["models"].values()
    }
    for cell in cells:
        provider_name = contract["models"][cell["model_id"]]["provider"]
        grouped[provider_name].append(cell)
    ordered = {}
    for provider_name, provider_cells in grouped.items():
        case_order = contract["execution"]["provider_case_order"][provider_name]
        rank = {slug: index for index, slug in enumerate(case_order)}
        if set(rank) != {cell["case_slug"] for cell in provider_cells}:
            raise ValueError("public integrated v12 provider case order differs")
        ordered[provider_name] = tuple(
            sorted(provider_cells, key=lambda cell: rank[cell["case_slug"]])
        )
    return ordered


async def _run_provider_queue(
    contract: Mapping[str, Any],
    cells: Sequence[Mapping[str, Any]],
    *,
    cases: Mapping[str, Any],
    run_root: Path,
    provider: Any,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    run_cell: Callable[..., Awaitable[dict[str, Any]]] = _run_live_cell,
) -> tuple[dict[str, Any], ...]:
    if not cells:
        return ()
    provider_names = {
        contract["models"][cell["model_id"]]["provider"] for cell in cells
    }
    if len(provider_names) != 1:
        raise ValueError("public integrated v12 queue mixes providers")
    provider_name = provider_names.pop()
    cooldown = float(
        contract["execution"]["provider_cooldown_seconds_after_attempt"][
            provider_name
        ]
    )
    rows = []
    for index, cell in enumerate(cells):
        rows.append(
            await run_cell(
                contract,
                cell,
                cases=cases,
                run_root=run_root,
                provider=provider,
            )
        )
        if cooldown > 0.0 and index + 1 < len(cells):
            await sleep(cooldown)
    return tuple(rows)


async def run_live_panel(
    contract: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
    run_root: Path,
    provider_factory: Callable[[], Any] = IndicatorMapOpenRouterClient,
) -> dict[str, Any]:
    path = run_root / "live" / "summary.json"
    if path.exists():
        return _read_sealed(path)
    provider_free = _read_sealed(
        run_root / "provider_free_validation" / "summary.json"
    )
    admission = _read_sealed(run_root / "profile_admission" / "summary.json")
    if provider_free["status"] != "passed" or admission["status"] != "passed":
        raise ValueError("public integrated v12 gates must pass before dispatch")
    if design["contract_sha256"] != _sha256(contract):
        raise ValueError("public integrated v12 design contract digest differs")
    cases = _cases_by_slug()
    provider = provider_factory()
    provider_cells = _ordered_provider_cells(contract, design["cells"])
    batches = await asyncio.gather(
        *(
            _run_provider_queue(
                contract,
                cells,
                cases=cases,
                run_root=run_root,
                provider=provider,
            )
            for cells in provider_cells.values()
        )
    )
    rows_by_key = {row["cell_key"]: row for batch in batches for row in batch}
    rows = tuple(rows_by_key[cell["cell_key"]] for cell in design["cells"])
    summary = _campaign_summary(contract, rows)
    _atomic_write(path, summary)
    return summary


async def run_campaign(
    *,
    contract_path: Path | str = DEFAULT_CONTRACT_PATH,
    run_root: Path | str = DEFAULT_RUN_ROOT,
    stop_after: str = "live",
    provider_factory: Callable[[], Any] = IndicatorMapOpenRouterClient,
) -> dict[str, Any]:
    if stop_after not in {"design", "provider_free", "profile_admission", "live"}:
        raise ValueError("unsupported public integrated v12 campaign stage")
    contract = load_contract(contract_path)
    root = Path(run_root)
    design_path = root / "design" / "summary.json"
    if design_path.exists():
        design = _read_sealed(design_path)
        if design != build_design(contract):
            raise ValueError("stored public integrated v12 design differs")
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
    "MODEL_ORDER",
    "build_design",
    "load_contract",
    "main",
    "run_campaign",
    "run_live_panel",
]
