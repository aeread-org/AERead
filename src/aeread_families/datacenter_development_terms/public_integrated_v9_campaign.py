"""Run the provider-paced indicator-map two-route public campaign."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
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
from .public_integrated_v4_campaign import _campaign_summary as _v4_summary
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
    "aeread.datacenter_terms_public_integrated_v9_campaign/0.1"
)
CAMPAIGN_ID = "datacenter_development_terms_public_integrated_v9"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT_PATH = REPOSITORY_ROOT / "configs" / f"{CAMPAIGN_ID}.json"
DEFAULT_RUN_ROOT = REPOSITORY_ROOT / "runs" / CAMPAIGN_ID
PREDECESSOR_RUN_ROOT = (
    REPOSITORY_ROOT / "runs" / "datacenter_development_terms_public_integrated_v8"
)
PREDECESSOR_PUBLICATION_ROOT = (
    REPOSITORY_ROOT / "evidence" / "datacenter_development_terms_public_integrated_v8"
)
ALTERNATE_QUALIFICATION_ROOT = (
    REPOSITORY_ROOT
    / "runs"
    / "datacenter_development_terms_public_integrated_v7_parasail_qualification"
)
MODEL_ORDER = ("mistral32_deepinfra", "qwen3_235b_google")


def _cases_by_slug() -> dict[str, Any]:
    return {
        case.case_id.rsplit(".", 1)[-1]: case
        for case in load_public_integrated_expansion_v4_cases()
    }


def _validate_predecessor(contract: Mapping[str, Any]) -> None:
    expected = {
        "campaign_id": "datacenter_development_terms_public_integrated_v8",
        "contract_sha256": (
            "3274f3a7990abdcd0f936eea2eb3707c14febf26f766d4bac3d21d3a002f9838"
        ),
        "design_sha256": (
            "c83258cf3a211f2d29298d18b2acf5b943879d5f284bbb99dbdfeef872954867"
        ),
        "live_summary_sha256": (
            "b84c1883591f878673569c5ebf33d75c86a5d9dbe11c5820992bc12667ce5a68"
        ),
        "public_evidence_sha256": (
            "a70af59b8ebd0862f7dca6d02eacfce9be06b8fc8d601a9f9b59d3b56b90cfa9"
        ),
        "status": (
            "provider_paced_six_of_six_complete_lake_currency_unit_ambiguity"
        ),
        "comparison_scope": "audit_lineage_only_not_analysis_data",
    }
    if contract["predecessor"] != expected:
        raise ValueError("public integrated v9 predecessor lineage differs")
    for field, path in {
        "design_sha256": PREDECESSOR_RUN_ROOT / "design" / "summary.json",
        "live_summary_sha256": PREDECESSOR_RUN_ROOT / "live" / "summary.json",
        "public_evidence_sha256": PREDECESSOR_PUBLICATION_ROOT
        / "publication_manifest.json",
    }.items():
        if path.exists() and _read_sealed(path)["artifact_sha256"] != expected[field]:
            raise ValueError(f"public integrated v9 predecessor {field} differs")


def _validate_qualification(contract: Mapping[str, Any]) -> None:
    expected = {
        "qualification_id": (
            "mistral32_deepinfra_indicator_map_polaris_seed_322000"
        ),
        "provider": "DeepInfra",
        "requested_model": "mistralai/mistral-small-3.2-24b-instruct",
        "canonical_model": "mistralai/mistral-small-3.2-24b-instruct-2506",
        "case_sha256": (
            "c95b2d3df234ee30d3df10be2033f4efab8069bd4e41019bfc377d74265fad99"
        ),
        "run_plan_sha256": (
            "8546e885b4a3d83074a53cfae29b32c2d0b127a624803ef24167cfc0b3fcd9b8"
        ),
        "receipt_sha256": (
            "982f7a4add0e995ae81d5ce7d3960f12e09380f104ba99e77a508b72165c4f88"
        ),
        "inference_seed": 322000,
        "status": "completed",
        "route_verified": True,
        "replay_verified": True,
        "reported_cost_usd": 0.000248094,
        "scope": "full_case_schema_route_compatibility_not_campaign_analysis",
    }
    if contract["indicator_schema_qualification"] != expected:
        raise ValueError("public integrated v9 qualification differs")


def _validate_answerability_correction(contract: Mapping[str, Any]) -> None:
    expected = {
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
    if contract.get("answerability_correction") != expected:
        raise ValueError("public integrated v9 answerability correction differs")


def _validate_numeric_unit_correction(contract: Mapping[str, Any]) -> None:
    expected = {
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
    if contract.get("numeric_unit_correction") != expected:
        raise ValueError("public integrated v9 numeric unit correction differs")


def _validate_alternate_qualification(contract: Mapping[str, Any]) -> None:
    expected = {
        "qualification_id": "mistral32_parasail_indicator_map_tydal_seed_422100",
        "provider": "Parasail",
        "requested_model": "mistralai/mistral-small-3.2-24b-instruct",
        "canonical_model": "mistralai/mistral-small-3.2-24b-instruct-2506",
        "case_sha256": (
            "4da4f11c913e01bf726b3309309ee1797222416d2e85c4fd504f1a35c07662be"
        ),
        "run_plan_sha256": (
            "10720cdef7b0e1621fcde168929420e06e847ae724f6bef738b092d2c1a16a02"
        ),
        "receipt_sha256": (
            "39a19368181a26dbe66c455448d79f105c2218d5e78ea8f605a0883af37991ca"
        ),
        "inference_seed": 422100,
        "status": "provider_rejected_pre_inference",
        "failure_class": "environment_failure",
        "failure_condition": "provider_rejected",
        "reported_cost_usd": 0.0,
        "decision": "exclude_parasail_from_campaign",
    }
    if contract.get("alternate_route_qualification") != expected:
        raise ValueError("public integrated v9 alternate qualification differs")
    receipts = tuple(ALTERNATE_QUALIFICATION_ROOT.rglob("evaluation_receipt.json"))
    if receipts:
        receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
        if (
            len(receipts) != 1
            or receipt.get("receipt_sha256") != expected["receipt_sha256"]
            or receipt.get("failure", {}).get("condition")
            != expected["failure_condition"]
        ):
            raise ValueError("public integrated v9 alternate receipt differs")


def load_contract(path: Path | str = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("public integrated v9 contract must be an object")
    if value.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        raise ValueError("public integrated v9 schema version differs")
    if value.get("campaign_id") != CAMPAIGN_ID:
        raise ValueError("public integrated v9 campaign id differs")
    if value.get("family_id") != "datacenter_development_terms_v1":
        raise ValueError("public integrated v9 family differs")
    if value.get("family_version") != "1.0.0":
        raise ValueError("public integrated v9 family version differs")
    if value.get("pack_id") != PACK_ID:
        raise ValueError("public integrated v9 pack id differs")
    if value.get("pack_sha256") != public_integrated_expansion_v4_pack_sha256():
        raise ValueError("public integrated v9 pack hash differs")
    if value.get("claim_status") != (
        "answerability_and_units_corrected_provider_paced_indicator_map_three_"
        "project_two_route_paired_diagnostic_exploratory"
    ):
        raise ValueError("public integrated v9 claim status differs")
    if value.get("inference_seeds") != [422103]:
        raise ValueError("public integrated v9 seeds differ")
    _validate_predecessor(value)
    _validate_qualification(value)
    _validate_answerability_correction(value)
    _validate_numeric_unit_correction(value)
    _validate_alternate_qualification(value)
    expected_snapshot = {
        "verified_at": "2026-09-03T20:00:55Z",
        "sources": [
            "https://openrouter.ai/api/v1/models/mistralai/mistral-small-3.2-24b-instruct/endpoints",
            "https://openrouter.ai/api/v1/models/qwen/qwen3-235b-a22b-2507/endpoints",
        ],
        "selection_rule": (
            "use_only_full_case_qualified_provider_routes_supporting_seed_"
            "response_format_structured_outputs_complete_boolean_objects_and_"
            "price_caps_no_fallback"
        ),
        "selected_endpoints": {
            "mistral32_deepinfra": {
                "provider": "DeepInfra",
                "tag": "deepinfra/fp8",
                "quantization": "fp8",
                "status": 0,
                "required_parameters": [
                    "seed",
                    "response_format",
                    "structured_outputs",
                ],
            },
            "qwen3_235b_google": {
                "provider": "Google",
                "tag": "google-vertex/us-south1",
                "quantization": "unknown",
                "status": 0,
                "required_parameters": [
                    "seed",
                    "response_format",
                    "structured_outputs",
                ],
            },
        },
    }
    if value.get("route_catalog_snapshot") != expected_snapshot:
        raise ValueError("public integrated v9 route snapshot differs")
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
        raise ValueError("public integrated v9 cases differ")
    common = {
        "access_class": "open_source",
        "license_id": "Apache-2.0",
        "reasoning_effort": None,
        "temperature_supported": True,
    }
    expected_models = {
        "mistral32_deepinfra": {
            "profile_id": "datacenter_terms_integrated_v9_mistral32_deepinfra",
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
                    "openrouter_2026-09-03_mistral32_deepinfra_terms_integrated_v9"
                ),
            },
            "max_prompt_price_per_million": "0.075",
            "max_completion_price_per_million": "0.2",
        },
        "qwen3_235b_google": {
            "profile_id": "datacenter_terms_integrated_v9_qwen3_235b_google",
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
                    "openrouter_2026-09-03_qwen3_google_terms_integrated_v9"
                ),
            },
            "max_prompt_price_per_million": "0.22",
            "max_completion_price_per_million": "0.88",
        },
    }
    if value.get("models") != expected_models:
        raise ValueError("public integrated v9 models differ")
    execution = value.get("execution", {})
    if execution != {
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
            "DeepInfra": 30.0,
            "Google": 0.0,
        },
        "max_action_attempts": 1,
        "sdk_retries": 0,
        "response_cache": False,
        "provider_fallbacks": False,
    }:
        raise ValueError("public integrated v9 execution controls differ")
    if value.get("analysis") != {
        "case_count": 3,
        "independent_cluster_count": 3,
        "resampling_unit": "public_filing_project_cluster",
        "replicate_policy": (
            "one_fresh_predeclared_paired_seed_full_panel_unit_correction_with_"
            "provider_pacing"
        ),
        "paired_by": ["case_slug", "inference_seed"],
        "primary_contrast": "qwen3_235b_google_minus_mistral32_deepinfra",
        "primary_endpoints": [
            "hard_gate_pass",
            "score",
            "forbidden_selection_count",
        ],
        "missingness": (
            "report_separately_and_require_both_routes_for_pair_no_selective_retry"
        ),
        "replacement_scope": (
            "fresh_full_panel_unit_contract_correction_not_selective_retry"
        ),
        "winner_claim_allowed": False,
        "inferential_model_ranking_allowed": False,
        "project_generalization_allowed": False,
        "population_causal_effect_allowed": False,
    }:
        raise ValueError("public integrated v9 analysis contract differs")
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
        "objective_openrouter.py": root.parent
        / "datacenter_development"
        / "objective_openrouter.py",
        "public_integrated_campaign.py": root / "public_integrated_campaign.py",
        "public_integrated_v4_campaign.py": root / "public_integrated_v4_campaign.py",
        "public_integrated_expansion_cases.py": root
        / "public_integrated_expansion_cases.py",
        "public_integrated_expansion_v2_cases.py": root
        / "public_integrated_expansion_v2_cases.py",
        "public_integrated_expansion_v3_cases.py": root
        / "public_integrated_expansion_v3_cases.py",
        "public_integrated_expansion_v4_cases.py": root
        / "public_integrated_expansion_v4_cases.py",
        "public_integrated_v9_campaign.py": root / "public_integrated_v9_campaign.py",
    }
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}


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
                raise ValueError("public integrated v9 indicator schema differs")
        if schema["properties"]["external_actions_attempted"]["properties"] != {
            "any": {"type": "boolean"}
        }:
            raise ValueError("public integrated v9 external indicator differs")
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
    worst_case_declared_cost = round(len(cells) * per_cell, 12)
    campaign_max_cost = float(contract["execution"]["campaign_max_cost_usd"])
    if worst_case_declared_cost > campaign_max_cost:
        raise ValueError(
            "public integrated v9 declared cell costs exceed campaign maximum"
        )
    hashes = _implementation_hashes()
    return _sealed(
        {
            "schema_version": "aeread.datacenter_terms_public_integrated_v9_design/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "pack_sha256": contract["pack_sha256"],
            "predecessor": contract["predecessor"],
            "answerability_correction": contract["answerability_correction"],
            "numeric_unit_correction": contract["numeric_unit_correction"],
            "indicator_schema_qualification": contract["indicator_schema_qualification"],
            "alternate_route_qualification": contract["alternate_route_qualification"],
            "campaign_driver_sha256": hashes["public_integrated_v9_campaign.py"],
            "adapter_implementation_id": INDICATOR_MAP_CLIENT_IMPLEMENTATION_ID,
            "implementation_source_sha256s": hashes,
            "schema_mode": "complete_indicator_maps_v1",
            "case_count": 3,
            "independent_cluster_count": 3,
            "planned_cells": len(cells),
            "planned_pair_count": 3,
            "worst_case_declared_cost_usd": worst_case_declared_cost,
            "campaign_max_cost_usd": campaign_max_cost,
            "provider_schedule": contract["execution"]["provider_schedule"],
            "provider_cooldown_seconds_after_attempt": contract["execution"][
                "provider_cooldown_seconds_after_attempt"
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
        receipt = finalize_datacenter_terms_execution(setup=setup, execution=execution)
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
            "schema_version": "aeread.datacenter_terms_public_integrated_v9_provider_free/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "case_count": 3,
            "status": "passed" if all(row["status"] == "passed" for row in rows) else "failed",
            "cases": rows,
        }
    )
    _atomic_write(path, result)
    return result


def run_profile_admission_gate(
    contract: Mapping[str, Any], *, design: Mapping[str, Any], run_root: Path
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
            raise ValueError(f"public integrated v9 admission drift: {cell['cell_key']}")
        admitted.append(cell["cell_key"])
    result = _sealed(
        {
            "schema_version": "aeread.datacenter_terms_public_integrated_v9_profile_gate/0.1",
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
            raise ValueError(f"resumed integrated v9 result drift: {design_cell['cell_key']}")
        return result
    if cell_root.exists():
        raise ValueError(f"refusing to replace incomplete integrated v9 cell {design_cell['cell_key']}")
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
            raise ValueError("integrated v9 live setup differs from sealed design")
        receipt = finalize_datacenter_terms_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_datacenter_terms_receipt(
            setup=setup, receipt=receipt, evidence_root=cell_root / "evidence"
        )
        verify_evaluation_receipt(replayed)
        result = _sealed(
            {
                "schema_version": "aeread.datacenter_terms_public_integrated_v9_cell/0.1",
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
                "schema_version": "aeread.datacenter_terms_public_integrated_v9_cell/0.1",
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
    base = _v4_summary(contract, rows)
    core = {key: value for key, value in base.items() if key != "artifact_sha256"}
    core.update(
        {
            "schema_version": "aeread.datacenter_terms_public_integrated_v9_summary/0.1",
            "campaign_id": CAMPAIGN_ID,
            "campaign_driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "schema_mode": "complete_indicator_maps_v1",
            "answerability_correction": contract["answerability_correction"],
            "numeric_unit_correction": contract["numeric_unit_correction"],
            "indicator_schema_qualification": contract["indicator_schema_qualification"],
            "alternate_route_qualification": contract["alternate_route_qualification"],
            "provider_schedule": contract["execution"]["provider_schedule"],
            "provider_cooldown_seconds_after_attempt": contract["execution"][
                "provider_cooldown_seconds_after_attempt"
            ],
        }
    )
    return _sealed(core)


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
        raise ValueError("public integrated v9 queue mixes providers")
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
    provider_free = _read_sealed(run_root / "provider_free_validation" / "summary.json")
    admission = _read_sealed(run_root / "profile_admission" / "summary.json")
    if provider_free["status"] != "passed" or admission["status"] != "passed":
        raise ValueError("public integrated v9 gates must pass before dispatch")
    if design["contract_sha256"] != _sha256(contract):
        raise ValueError("public integrated v9 design contract digest differs")
    cases = _cases_by_slug()
    provider = provider_factory()
    provider_cells = {
        model["provider"]: [] for model in contract["models"].values()
    }
    for cell in design["cells"]:
        provider_name = contract["models"][cell["model_id"]]["provider"]
        provider_cells[provider_name].append(cell)
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
        raise ValueError("unsupported public integrated v9 campaign stage")
    contract = load_contract(contract_path)
    root = Path(run_root)
    design_path = root / "design" / "summary.json"
    if design_path.exists():
        design = _read_sealed(design_path)
        if design != build_design(contract):
            raise ValueError("stored public integrated v9 design differs")
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
