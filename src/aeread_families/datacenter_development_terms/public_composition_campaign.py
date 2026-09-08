"""Run matched integrated cases for a public clause-composition diagnostic."""

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
from .public_affirm_only_cases import (
    PACK_ID as AFFIRM_PACK_ID,
    load_public_affirm_only_cases,
    public_affirm_only_pack_sha256,
)
from .public_campaign import _group_summary
from .public_cases import (
    PACK_ID as BASE_PACK_ID,
    load_public_cases,
    public_pack_sha256,
)
from .public_mechanism_campaign import (
    _cases_by_slug as _mechanism_cases_by_slug,
    _setup as _mechanism_setup,
    load_contract as load_mechanism_contract,
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


CONTRACT_SCHEMA_VERSION = "aeread.datacenter_terms_public_composition_campaign/0.1"
CAMPAIGN_ID = "datacenter_development_terms_public_composition_v1"
CASE_SLUG = "linked-land-power-construction-underwriting"
CLUSTER_ID = "sec_core_denton_project_terms_2026"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT_PATH = REPOSITORY_ROOT / "configs" / f"{CAMPAIGN_ID}.json"
DEFAULT_RUN_ROOT = REPOSITORY_ROOT / "runs" / CAMPAIGN_ID
MECHANISM_PUBLICATION_ROOT = (
    REPOSITORY_ROOT / "evidence" / "datacenter_development_terms_public_mechanism_v1"
)
MODEL_ORDER = (
    "mistral32_deepinfra",
    "qwen3_235b_novita",
    "gptoss120b_coreweave",
)
CONDITION_ORDER = ("baseline", "affirm_only")
MECHANISM_ORDER = (
    "assignment_consent",
    "gmp_change_order",
    "land_power_cotermination",
)
COMPONENT_NAMES = (
    "state_accuracy",
    "amount_accuracy",
    "required_action_recall",
    "required_claim_recall",
    "evidence_coverage",
)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cases_by_condition() -> dict[str, Any]:
    baseline = load_public_cases(case_slugs=(CASE_SLUG,))[0]
    affirm = load_public_affirm_only_cases(case_slugs=(CASE_SLUG,))[0]
    return {"baseline": baseline, "affirm_only": affirm}


def _validate_mechanism_bridge(contract: Mapping[str, Any]) -> None:
    spec = contract["mechanism_bridge"]
    expected_fields = {
        "campaign_id",
        "contract_sha256",
        "design_sha256",
        "live_summary_sha256",
        "public_manifest_sha256",
        "trajectory_sha256",
        "mechanism_ids",
        "comparison_scope",
    }
    if set(spec) != expected_fields:
        raise ValueError("composition mechanism bridge fields differ")
    if spec["mechanism_ids"] != list(MECHANISM_ORDER):
        raise ValueError("composition mechanism set differs")
    if spec["comparison_scope"] != (
        "same_source_cluster_model_route_harness_budget_wording_condition_and_"
        "inference_seed_different_case_granularity_descriptive_only"
    ):
        raise ValueError("composition bridge comparison scope differs")
    mechanism_contract = load_mechanism_contract()
    manifest = _read_sealed(MECHANISM_PUBLICATION_ROOT / "publication_manifest.json")
    summary = _read_sealed(MECHANISM_PUBLICATION_ROOT / "reports" / "summary.json")
    trajectory_path = MECHANISM_PUBLICATION_ROOT / "trajectories" / "sanitized.jsonl"
    actual = {
        "campaign_id": manifest["campaign_id"],
        "contract_sha256": _sha256(mechanism_contract),
        "design_sha256": manifest["source_design_sha256"],
        "live_summary_sha256": manifest["source_summary_sha256"],
        "public_manifest_sha256": manifest["artifact_sha256"],
        "trajectory_sha256": _file_sha256(trajectory_path),
        "mechanism_ids": list(MECHANISM_ORDER),
        "comparison_scope": spec["comparison_scope"],
    }
    if spec != actual:
        raise ValueError("composition mechanism bridge artifacts differ")
    if (
        summary["source_summary_sha256"] != spec["live_summary_sha256"]
        or summary["source_design_sha256"] != spec["design_sha256"]
        or manifest["files"]["trajectories/sanitized.jsonl"]["sha256"]
        != spec["trajectory_sha256"]
    ):
        raise ValueError("composition mechanism publication linkage differs")


def load_contract(path: Path | str = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    frozen = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "campaign_id": CAMPAIGN_ID,
        "family_id": "datacenter_development_terms_v1",
        "family_version": "1.0.0",
        "claim_status": "matched_seed_single_source_cross_granularity_diagnostic",
    }
    if not isinstance(contract, dict) or any(
        contract.get(key) != value for key, value in frozen.items()
    ):
        raise ValueError("public composition campaign identity differs")
    if set(contract) != {
        *frozen,
        "route_catalog_snapshot",
        "integrated_cases",
        "mechanism_bridge",
        "inference_seeds",
        "models",
        "execution",
        "analysis",
    }:
        raise ValueError("public composition campaign fields differ")

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
        raise ValueError("public composition route snapshot differs")

    cases = _cases_by_condition()
    expected_packs = {
        "baseline": (BASE_PACK_ID, public_pack_sha256()),
        "affirm_only": (AFFIRM_PACK_ID, public_affirm_only_pack_sha256()),
    }
    if set(contract["integrated_cases"]) != set(CONDITION_ORDER):
        raise ValueError("public composition integrated conditions differ")
    for condition, case in cases.items():
        public = case.payload["public_case"]
        pack_id, pack_sha256 = expected_packs[condition]
        expected = {
            "pack_id": pack_id,
            "pack_sha256": pack_sha256,
            "case_id": case.case_id,
            "expected_case_sha256": case.content_sha256,
            "source_cluster_id": public["independence_cluster_id"],
            "world_seed": case.world_seed,
        }
        if contract["integrated_cases"][condition] != expected:
            raise ValueError(f"{condition}: public composition case differs")
    if contract["inference_seeds"] != [315001, 315002, 315003]:
        raise ValueError("public composition inference seeds differ")

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
            "datacenter_terms_composition_mistral32_deepinfra_v1",
            "openrouter_2026-09-03_mistral32_deepinfra_terms_composition_v1",
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
            "datacenter_terms_composition_qwen3_235b_novita_v1",
            "openrouter_2026-09-03_qwen3_novita_terms_composition_v1",
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
            "datacenter_terms_composition_gptoss120b_coreweave_v1",
            "openrouter_2026-09-03_gptoss120b_coreweave_terms_composition_v1",
            "0.03",
            "0.17",
        ),
    }
    if set(contract["models"]) != set(expected_routes):
        raise ValueError("public composition model panel differs")
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
            raise ValueError(f"{model_id}: public composition route differs")

    required_execution = {
        "harness": "minimal_chat/1.0",
        "adapter": CLIENT_IMPLEMENTATION_ID,
        "max_output_tokens": 900,
        "timeout_seconds": 180.0,
        "max_cost_usd_per_cell": 0.02,
        "campaign_max_cost_usd": 0.36,
        "concurrency": 3,
        "max_concurrent_cells_per_route_provider": 1,
        "max_action_attempts": 1,
        "sdk_retries": 0,
        "response_cache": False,
        "provider_fallbacks": False,
    }
    if contract["execution"] != required_execution:
        raise ValueError("public composition execution controls differ")
    required_analysis = {
        "integrated_case_count": 2,
        "mechanism_count": 3,
        "independent_cluster_count": 1,
        "resampling_unit": "single_public_filing_cluster",
        "integrated_wording_paired_by": ["model_id", "inference_seed"],
        "cross_granularity_blocked_by": [
            "wording_condition",
            "model_id",
            "inference_seed",
        ],
        "composition_gap_definition": (
            "integrated_hard_gate_failure_and_all_three_decomposed_mechanisms_pass"
        ),
        "score_difference_allowed": False,
        "missingness": (
            "report_separately_and_require_integrated_plus_all_three_mechanisms_"
            "no_selective_retry"
        ),
        "winner_claim_allowed": False,
        "inferential_model_ranking_allowed": False,
        "project_generalization_allowed": False,
        "population_causal_effect_allowed": False,
        "composition_causal_effect_allowed": False,
    }
    if contract["analysis"] != required_analysis:
        raise ValueError("public composition analysis contract differs")
    _validate_mechanism_bridge(contract)
    return contract


def _cells(contract: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "cell_key": f"integrated-{condition}__{model_id}__seed_{seed}",
            "wording_pair_key": f"integrated__{model_id}__seed_{seed}",
            "composition_key": f"{condition}__{model_id}__seed_{seed}",
            "case_slug": CASE_SLUG,
            "wording_condition": condition,
            "source_cluster_id": CLUSTER_ID,
            "world_seed": contract["integrated_cases"][condition]["world_seed"],
            "model_id": model_id,
            "inference_seed": seed,
        }
        for condition in CONDITION_ORDER
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
        case_slug=CASE_SLUG,
        case_manifest=cases[str(cell["wording_condition"])],
        max_output_tokens=int(controls["max_output_tokens"]),
        timeout_seconds=float(controls["timeout_seconds"]),
        max_cost_usd=float(controls["max_cost_usd_per_cell"]),
    )


def _mechanism_case_slug(condition: str) -> str:
    suffix = "m01" if condition == "baseline" else "m02"
    return f"assignment-consent-{suffix}"


def _assert_mechanism_compatible(
    contract: Mapping[str, Any],
    cell: Mapping[str, Any],
    setup: Any,
) -> None:
    mechanism_contract = load_mechanism_contract()
    mechanism_cell = {
        "case_slug": _mechanism_case_slug(str(cell["wording_condition"])),
        "model_id": cell["model_id"],
        "inference_seed": cell["inference_seed"],
    }
    prior = _mechanism_setup(
        mechanism_contract,
        mechanism_cell,
        _mechanism_cases_by_slug(),
    )
    current_profile = setup.plan.agent_profiles[0]
    prior_profile = prior.plan.agent_profiles[0]
    current_schema = current_profile.harness.config["output_schema"]
    prior_schema = prior_profile.harness.config["output_schema"]
    if (
        current_profile.model != prior_profile.model
        or current_profile.prompt != prior_profile.prompt
        or current_profile.harness.id != prior_profile.harness.id
        or current_profile.harness.version != prior_profile.harness.version
        or current_profile.harness.config["provider_metadata"]
        != prior_profile.harness.config["provider_metadata"]
        or current_schema["type"] != prior_schema["type"]
        or set(current_schema["properties"]) != set(prior_schema["properties"])
        or set(current_schema["required"]) != set(prior_schema["required"])
        or current_schema["additionalProperties"]
        != prior_schema["additionalProperties"]
        or current_profile.reasoning != prior_profile.reasoning
        or current_profile.sampling != prior_profile.sampling
        or current_profile.budgets != prior_profile.budgets
        or current_profile.retry_policy != prior_profile.retry_policy
    ):
        raise ValueError("public composition setup is not mechanism-compatible")


def _implementation_hashes() -> dict[str, str]:
    root = Path(__file__).parent
    names = (
        "environment.py",
        "runner.py",
        "public_cases.py",
        "public_affirm_only_cases.py",
        "public_composition_campaign.py",
    )
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names
    }


def build_design(contract: Mapping[str, Any]) -> dict[str, Any]:
    cases = _cases_by_condition()
    cells = []
    for cell in _cells(contract):
        setup = _setup(contract, cell, cases)
        _assert_mechanism_compatible(contract, cell, setup)
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
            "schema_version": "aeread.datacenter_terms_public_composition_design/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "integrated_pack_sha256s": {
                "baseline": public_pack_sha256(),
                "affirm_only": public_affirm_only_pack_sha256(),
            },
            "mechanism_bridge": contract["mechanism_bridge"],
            "campaign_driver_sha256": hashes["public_composition_campaign.py"],
            "adapter_implementation_id": CLIENT_IMPLEMENTATION_ID,
            "implementation_source_sha256s": hashes,
            "integrated_case_count": 2,
            "mechanism_count": 3,
            "independent_cluster_count": 1,
            "planned_cells": len(cells),
            "planned_wording_pair_count": 9,
            "planned_composition_bundle_count": 18,
            "worst_case_declared_cost_usd": len(cells) * 0.02,
            "campaign_max_cost_usd": 0.36,
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
    for condition, case in _cases_by_condition().items():
        setup = build_offline_setup(case_slug=CASE_SLUG, case_manifest=case)
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
        evidence_root = (
            run_root / "provider_free_validation" / condition / "evidence"
        )
        execution = await run_fixture_response(
            canonical_json_bytes(response).decode("utf-8"),
            evidence_root=evidence_root,
            case_slug=CASE_SLUG,
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
                "wording_condition": condition,
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
                "aeread.datacenter_terms_public_composition_provider_free_gate/0.1"
            ),
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "mode": "reexecuted_integrated_cases_environment_scorer_and_oracles",
            "case_count": len(rows),
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
    cases = _cases_by_condition()
    expected = {cell["cell_key"]: cell for cell in design["cells"]}
    admitted = []
    for cell in _cells(contract):
        setup = _setup(contract, cell, cases)
        _assert_mechanism_compatible(contract, cell, setup)
        target = expected[cell["cell_key"]]
        if (
            setup.plan.plan_sha256 != target["run_plan_sha256"]
            or setup.plan.cells[0].cell_id != target["cell_id"]
            or not all(item.admitted for item in setup.plan.profile_admissions)
        ):
            raise ValueError(f"composition profile admission drift for {cell['cell_key']}")
        admitted.append(cell["cell_key"])
    result = _sealed(
        {
            "schema_version": (
                "aeread.datacenter_terms_public_composition_profile_gate/0.1"
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
            raise ValueError(f"resumed composition result drift for {cell['cell_key']}")
        return result
    if cell_root.exists():
        raise ValueError(f"refusing to replace incomplete composition cell {cell['cell_key']}")
    case = cases[str(cell["wording_condition"])]
    route = _route(contract["models"][cell["model_id"]])
    controls = contract["execution"]
    setup = _setup(contract, cell, cases)
    started = time.perf_counter()
    try:
        returned_setup, execution = await run_openrouter(
            route,
            evidence_root=cell_root / "evidence",
            seed=int(cell["inference_seed"]),
            case_slug=CASE_SLUG,
            case_manifest=case,
            max_output_tokens=int(controls["max_output_tokens"]),
            timeout_seconds=float(controls["timeout_seconds"]),
            max_cost_usd=float(controls["max_cost_usd_per_cell"]),
            provider=provider,
        )
        if returned_setup.plan.plan_sha256 != setup.plan.plan_sha256:
            raise ValueError("composition live setup differs from sealed design")
        receipt = finalize_datacenter_terms_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_datacenter_terms_receipt(
            setup=setup,
            receipt=receipt,
            evidence_root=cell_root / "evidence",
        )
        result = _sealed(
            {
                "schema_version": "aeread.datacenter_terms_public_composition_cell/0.1",
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
                "schema_version": "aeread.datacenter_terms_public_composition_cell/0.1",
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


def _mechanism_rows(
    contract: Mapping[str, Any],
) -> dict[tuple[str, str, int], tuple[dict[str, Any], ...]]:
    path = MECHANISM_PUBLICATION_ROOT / "trajectories" / "sanitized.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line]
    if len(rows) != 54:
        raise ValueError("composition mechanism trajectory count differs")
    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (row["wording_condition"], row["model_id"], row["inference_seed"])
        if (
            row["campaign_id"] != contract["mechanism_bridge"]["campaign_id"]
            or row["mechanism_id"] not in MECHANISM_ORDER
            or row["wording_condition"] not in CONDITION_ORDER
            or row["model_id"] not in MODEL_ORDER
            or row["inference_seed"] not in contract["inference_seeds"]
            or row["source_cluster_id"] != CLUSTER_ID
        ):
            raise ValueError("composition mechanism trajectory identity differs")
        expected_route = {
            name: contract["models"][row["model_id"]][name]
            for name in (
                "requested_model",
                "canonical_model",
                "provider",
                "quantization",
            )
        }
        if row["expected_route"] != expected_route:
            raise ValueError("composition mechanism route differs")
        grouped.setdefault(key, []).append(row)
    expected_keys = {
        (condition, model_id, seed)
        for condition in CONDITION_ORDER
        for model_id in MODEL_ORDER
        for seed in contract["inference_seeds"]
    }
    if set(grouped) != expected_keys:
        raise ValueError("composition mechanism bundle set differs")
    result = {}
    for key, bundle in grouped.items():
        ordered = tuple(sorted(bundle, key=lambda row: row["mechanism_id"]))
        if [row["mechanism_id"] for row in ordered] != list(MECHANISM_ORDER):
            raise ValueError("composition mechanism bundle members differ")
        result[key] = ordered
    return result


def _wording_pairs(
    contract: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    indexed = {
        (row["wording_condition"], row["model_id"], row["inference_seed"]): row
        for row in rows
    }
    pairs = []
    for model_id in MODEL_ORDER:
        for seed in contract["inference_seeds"]:
            baseline = indexed[("baseline", model_id, seed)]
            affirm = indexed[("affirm_only", model_id, seed)]
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
                    "pair_key": f"integrated__{model_id}__seed_{seed}",
                    "model_id": model_id,
                    "inference_seed": seed,
                    "pair_reportable": usable,
                    "baseline_status": baseline["status"],
                    "affirm_only_status": affirm["status"],
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


def _composition_bundles(
    contract: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    integrated = {
        (row["wording_condition"], row["model_id"], row["inference_seed"]): row
        for row in rows
    }
    mechanisms = _mechanism_rows(contract)
    if set(integrated) != set(mechanisms):
        raise ValueError("composition integrated and mechanism blocks differ")
    result = []
    for key in sorted(integrated):
        condition, model_id, seed = key
        whole = integrated[key]
        parts = mechanisms[key]
        usable = whole["status"] == "completed" and all(
            part["status"] == "completed" for part in parts
        )
        if usable:
            integrated_metrics = whole["metrics"]
            all_mechanisms_pass = all(
                part["metrics"]["hard_gate_pass"] for part in parts
            )
            failed_mechanisms = [
                part["mechanism_id"]
                for part in parts
                if not part["metrics"]["hard_gate_pass"]
            ]
            integrated_forbidden = len(integrated_metrics["forbidden_actions"]) + len(
                integrated_metrics["forbidden_claims"]
            )
            decomposed_forbidden = sum(
                len(part["metrics"]["forbidden_actions"])
                + len(part["metrics"]["forbidden_claims"])
                for part in parts
            )
        result.append(
            {
                "composition_key": f"{condition}__{model_id}__seed_{seed}",
                "wording_condition": condition,
                "model_id": model_id,
                "inference_seed": seed,
                "bundle_reportable": usable,
                "integrated_status": whole["status"],
                "mechanism_statuses": {
                    part["mechanism_id"]: part["status"] for part in parts
                },
                "integrated_hard_gate_pass": (
                    integrated_metrics["hard_gate_pass"] if usable else None
                ),
                "all_mechanisms_hard_gate_pass": (
                    all_mechanisms_pass if usable else None
                ),
                "failed_mechanism_ids": failed_mechanisms if usable else None,
                "composition_gap": (
                    not integrated_metrics["hard_gate_pass"]
                    and all_mechanisms_pass
                    if usable
                    else None
                ),
                "component_only_gap": (
                    integrated_metrics["hard_gate_pass"]
                    and not all_mechanisms_pass
                    if usable
                    else None
                ),
                "integrated_forbidden_selection_count": (
                    integrated_forbidden if usable else None
                ),
                "decomposed_forbidden_selection_count": (
                    decomposed_forbidden if usable else None
                ),
                "score_difference_reported": False,
            }
        )
    return result


def _composition_summary(
    field: str,
    value: str,
    bundles: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    selected = [bundle for bundle in bundles if bundle[field] == value]
    reportable = [bundle for bundle in selected if bundle["bundle_reportable"]]
    return {
        field: value,
        "planned_bundles": len(selected),
        "reportable_bundles": len(reportable),
        "missing_bundles": len(selected) - len(reportable),
        "integrated_hard_gate_pass_rate": (
            statistics.fmean(
                1.0 if bundle["integrated_hard_gate_pass"] else 0.0
                for bundle in reportable
            )
            if reportable
            else None
        ),
        "all_mechanisms_hard_gate_pass_rate": (
            statistics.fmean(
                1.0 if bundle["all_mechanisms_hard_gate_pass"] else 0.0
                for bundle in reportable
            )
            if reportable
            else None
        ),
        "composition_gaps": sum(
            bundle["composition_gap"] is True for bundle in reportable
        ),
        "component_only_gaps": sum(
            bundle["component_only_gap"] is True for bundle in reportable
        ),
    }


def _campaign_summary(
    contract: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    completed = [row for row in rows if row["status"] == "completed"]
    failures = [row for row in rows if row["status"] != "completed"]
    wording_pairs = _wording_pairs(contract, rows)
    bundles = _composition_bundles(contract, rows)
    cost = math.fsum(
        float(row["usage"]["reported_cost_usd"])
        for row in completed
        if row["usage"] is not None
    )
    return _sealed(
        {
            "schema_version": "aeread.datacenter_terms_public_composition_summary/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "campaign_driver_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "claim_status": contract["claim_status"],
            "mechanism_bridge": contract["mechanism_bridge"],
            "integrated_case_count": 2,
            "mechanism_count": 3,
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
            "integrated_wording_contrasts": wording_pairs,
            "planned_wording_pair_count": len(wording_pairs),
            "reportable_wording_pair_count": sum(
                pair["pair_reportable"] for pair in wording_pairs
            ),
            "composition_bundles": bundles,
            "planned_composition_bundle_count": len(bundles),
            "reportable_composition_bundle_count": sum(
                bundle["bundle_reportable"] for bundle in bundles
            ),
            "composition_gap_count": sum(
                bundle["composition_gap"] is True for bundle in bundles
            ),
            "component_only_gap_count": sum(
                bundle["component_only_gap"] is True for bundle in bundles
            ),
            "condition_composition_summaries": [
                _composition_summary("wording_condition", condition, bundles)
                for condition in CONDITION_ORDER
            ],
            "model_composition_summaries": [
                _composition_summary("model_id", model_id, bundles)
                for model_id in MODEL_ORDER
            ],
            "score_difference_reported_across_granularity": False,
            "winner_claim_allowed": False,
            "inferential_model_ranking_allowed": False,
            "project_generalization_allowed": False,
            "population_causal_effect_allowed": False,
            "composition_causal_effect_allowed": False,
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
        raise ValueError("public composition gates must pass before live dispatch")
    if design["contract_sha256"] != _sha256(contract):
        raise ValueError("public composition design contract differs")
    cases = _cases_by_condition()
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
        raise ValueError("unsupported public composition campaign stage")
    contract = load_contract(contract_path)
    root = Path(run_root)
    design_path = root / "design" / "summary.json"
    if design_path.exists():
        design = _read_sealed(design_path)
        if design != build_design(contract):
            raise ValueError("stored public composition design differs")
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
