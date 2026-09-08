"""Run a GLM model-transfer probe on the integrated public terms case."""

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
from .public_campaign import _group_summary
from .public_candidate_screen_campaign import (
    DEFAULT_CONTRACT_PATH as BRIDGE_CONTRACT_PATH,
    _cases_by_condition as _bridge_cases_by_condition,
    _setup as _bridge_setup,
    load_contract as load_bridge_contract,
)
from .public_cases import PACK_ID, load_public_cases, public_pack_sha256
from .publication import _sha256_bytes
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
    "aeread.datacenter_terms_public_glm_transfer_contract/0.1"
)
CAMPAIGN_ID = "datacenter_development_terms_public_glm_transfer_v1"
MODEL_ID = "glm53_deepinfra"
CASE_SLUG = "linked-land-power-construction-underwriting"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT_PATH = REPOSITORY_ROOT / "configs" / f"{CAMPAIGN_ID}.json"
DEFAULT_RUN_ROOT = REPOSITORY_ROOT / "runs" / CAMPAIGN_ID
BRIDGE_PUBLICATION_ROOT = (
    REPOSITORY_ROOT
    / "evidence"
    / "datacenter_development_terms_public_candidate_screen_v1"
)
BRIDGE_MODELS = (
    "mistral32_deepinfra",
    "qwen3_235b_novita",
    "gptoss120b_coreweave",
)


def _case() -> Any:
    return load_public_cases(case_slugs=(CASE_SLUG,))[0]


def _bridge_artifacts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract = load_bridge_contract(BRIDGE_CONTRACT_PATH)
    manifest = _read_sealed(BRIDGE_PUBLICATION_ROOT / "publication_manifest.json")
    summary = _read_sealed(BRIDGE_PUBLICATION_ROOT / "reports" / "summary.json")
    return contract, manifest, summary


def load_contract(path: Path | str = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    frozen = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "campaign_id": CAMPAIGN_ID,
        "family_id": "datacenter_development_terms_v1",
        "family_version": "1.0.0",
        "claim_status": "single_source_model_transfer_diagnostic_exact_seed_bridge",
    }
    if not isinstance(contract, dict) or any(
        contract.get(key) != value for key, value in frozen.items()
    ):
        raise ValueError("public GLM transfer campaign identity differs")
    if set(contract) != {
        *frozen,
        "route_catalog_snapshot",
        "bridge",
        "case",
        "inference_seeds",
        "model",
        "execution",
        "analysis",
    }:
        raise ValueError("public GLM transfer campaign fields differ")

    snapshot = contract["route_catalog_snapshot"]
    if snapshot != {
        "verified_at": "2026-09-03T13:50:34Z",
        "source": (
            "https://openrouter.ai/api/v1/models/z-ai/glm-5.3-flash/endpoints"
        ),
        "selection_rule": (
            "lowest_priced_healthy_fp8_endpoint_supporting_seed_response_format_"
            "structured_outputs_and_reasoning_effort"
        ),
    }:
        raise ValueError("public GLM transfer route snapshot differs")

    case = _case()
    public = case.payload["public_case"]
    expected_case = {
        "pack_id": PACK_ID,
        "pack_sha256": public_pack_sha256(),
        "case_slug": CASE_SLUG,
        "case_id": case.case_id,
        "case_sha256": case.content_sha256,
        "source_cluster_id": public["independence_cluster_id"],
        "world_seed": case.world_seed,
    }
    if contract["case"] != expected_case:
        raise ValueError("public GLM transfer case differs")
    if contract["inference_seeds"] != [316001, 316002, 316003]:
        raise ValueError("public GLM transfer inference seeds differ")

    expected_model = {
        "model_id": MODEL_ID,
        "profile_id": "datacenter_terms_public_glm53_deepinfra_transfer_v1",
        "requested_model": "z-ai/glm-5.3-flash",
        "canonical_model": "z-ai/glm-5.3-flash-20260826",
        "provider": "DeepInfra",
        "quantization": "fp8",
        "access_class": "open_source",
        "license_id": "MIT",
        "reasoning_effort": "low",
        "temperature_supported": True,
        "pricing": {
            "input_per_million": 0.075,
            "cached_input_per_million": 0.015,
            "output_per_million": 0.25,
            "pricing_id": (
                "openrouter_2026-09-03_glm53_deepinfra_terms_public_transfer_v1"
            ),
        },
        "max_prompt_price_per_million": "0.075",
        "max_completion_price_per_million": "0.25",
    }
    if contract["model"] != expected_model:
        raise ValueError("public GLM transfer model route differs")

    required_execution = {
        "harness": "minimal_chat/1.0",
        "adapter": CLIENT_IMPLEMENTATION_ID,
        "max_output_tokens": 900,
        "timeout_seconds": 180.0,
        "max_cost_usd_per_cell": 0.02,
        "campaign_max_cost_usd": 0.06,
        "concurrency": 1,
        "max_concurrent_cells_per_route_provider": 1,
        "max_action_attempts": 1,
        "sdk_retries": 0,
        "response_cache": False,
        "provider_fallbacks": False,
    }
    if contract["execution"] != required_execution:
        raise ValueError("public GLM transfer execution controls differ")

    required_analysis = {
        "case_count": 1,
        "independent_cluster_count": 1,
        "resampling_unit": "single_public_filing_cluster",
        "paired_by_bridge": ["case_sha256", "inference_seed"],
        "primary_endpoint": "glm_hard_gate_pass_rate",
        "decision_rule": (
            "at_least_two_of_three_pass_qualifies_glm_for_five_cluster_"
            "replication_zero_of_three_is_broad_model_family_failure_"
            "operational_missingness_is_inconclusive"
        ),
        "missingness": "report_separately_no_selective_retry",
        "winner_claim_allowed": False,
        "inferential_model_ranking_allowed": False,
        "project_generalization_allowed": False,
        "population_causal_effect_allowed": False,
    }
    if contract["analysis"] != required_analysis:
        raise ValueError("public GLM transfer analysis contract differs")

    bridge_contract, bridge_manifest, bridge_summary = _bridge_artifacts()
    expected_bridge = {
        "campaign_id": bridge_contract["campaign_id"],
        "condition": "baseline",
        "contract_sha256": _sha256(bridge_contract),
        "design_sha256": bridge_summary["source_design_sha256"],
        "live_summary_sha256": bridge_summary["source_summary_sha256"],
        "public_manifest_sha256": bridge_manifest["artifact_sha256"],
        "comparison_scope": (
            "same_case_hash_prompt_schema_harness_budget_and_inference_seed_"
            "different_model_provider_route_descriptive_only"
        ),
    }
    if contract["bridge"] != expected_bridge:
        raise ValueError("public GLM transfer bridge artifacts differ")
    return contract


def _panel_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {**dict(contract), "models": {MODEL_ID: contract["model"]}}


def _cells(contract: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    case = contract["case"]
    return tuple(
        {
            "cell_key": f"{MODEL_ID}__seed_{seed}",
            "pair_key": f"baseline__seed_{seed}",
            "case_slug": CASE_SLUG,
            "wording_condition": "baseline",
            "source_cluster_id": case["source_cluster_id"],
            "world_seed": case["world_seed"],
            "model_id": MODEL_ID,
            "inference_seed": seed,
        }
        for seed in contract["inference_seeds"]
    )


def _setup(contract: Mapping[str, Any], cell: Mapping[str, Any]) -> Any:
    controls = contract["execution"]
    return build_openrouter_setup(
        _route(contract["model"]),
        seed=int(cell["inference_seed"]),
        case_slug=CASE_SLUG,
        case_manifest=_case(),
        max_output_tokens=int(controls["max_output_tokens"]),
        timeout_seconds=float(controls["timeout_seconds"]),
        max_cost_usd=float(controls["max_cost_usd_per_cell"]),
    )


def _implementation_hashes() -> dict[str, str]:
    root = Path(__file__).parent
    names = (
        "environment.py",
        "runner.py",
        "public_cases.py",
        "public_candidate_screen_campaign.py",
        "public_glm_transfer_campaign.py",
    )
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in names
    }


def _assert_bridge_setup(
    contract: Mapping[str, Any], cell: Mapping[str, Any], setup: Any
) -> None:
    bridge_contract = load_bridge_contract(BRIDGE_CONTRACT_PATH)
    prior = _bridge_setup(
        bridge_contract,
        {
            **dict(cell),
            "wording_condition": "baseline",
            "model_id": "qwen3_235b_novita",
        },
        _bridge_cases_by_condition(),
    )
    current_profile = setup.plan.agent_profiles[0]
    prior_profile = prior.plan.agent_profiles[0]
    if (
        setup.case.case_id != prior.case.case_id
        or setup.case.content_sha256 != prior.case.content_sha256
        or current_profile.prompt != prior_profile.prompt
        or current_profile.harness.id != prior_profile.harness.id
        or current_profile.harness.version != prior_profile.harness.version
        or current_profile.harness.config["output_schema"]
        != prior_profile.harness.config["output_schema"]
        or current_profile.sampling.seed != prior_profile.sampling.seed
        or current_profile.sampling.max_output_tokens
        != prior_profile.sampling.max_output_tokens
        or current_profile.budgets.timeout_seconds
        != prior_profile.budgets.timeout_seconds
        or current_profile.budgets.max_cost_usd != prior_profile.budgets.max_cost_usd
        or current_profile.retry_policy != prior_profile.retry_policy
    ):
        raise ValueError("public GLM transfer setup is not bridge-compatible")


def build_design(contract: Mapping[str, Any]) -> dict[str, Any]:
    cells = []
    for cell in _cells(contract):
        setup = _setup(contract, cell)
        _assert_bridge_setup(contract, cell, setup)
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
            "schema_version": (
                "aeread.datacenter_terms_public_glm_transfer_design/0.1"
            ),
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "pack_sha256": public_pack_sha256(),
            "bridge": contract["bridge"],
            "campaign_driver_sha256": hashes["public_glm_transfer_campaign.py"],
            "adapter_implementation_id": CLIENT_IMPLEMENTATION_ID,
            "implementation_source_sha256s": hashes,
            "case_count": 1,
            "independent_cluster_count": 1,
            "planned_cells": len(cells),
            "worst_case_declared_cost_usd": len(cells) * 0.02,
            "campaign_max_cost_usd": 0.06,
            "cells": cells,
        }
    )


async def run_provider_free_gate(
    contract: Mapping[str, Any], *, run_root: Path
) -> dict[str, Any]:
    path = run_root / "provider_free_validation" / "summary.json"
    if path.exists():
        return _read_sealed(path)
    case = _case()
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
    evidence_root = run_root / "provider_free_validation" / "evidence"
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
    result = _sealed(
        {
            "schema_version": (
                "aeread.datacenter_terms_public_glm_transfer_provider_gate/0.1"
            ),
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "status": "passed" if passed else "failed",
            "mode": "reexecuted_same_case_environment_scorer_and_oracle",
            "case_sha256": case.content_sha256,
            "score": outcome["score"],
            "receipt_sha256": receipt.receipt_sha256,
            "replay_verified": replayed == receipt,
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
    expected = {cell["cell_key"]: cell for cell in design["cells"]}
    admitted = []
    for cell in _cells(contract):
        setup = _setup(contract, cell)
        target = expected[cell["cell_key"]]
        if (
            setup.plan.plan_sha256 != target["run_plan_sha256"]
            or setup.plan.cells[0].cell_id != target["cell_id"]
            or not all(item.admitted for item in setup.plan.profile_admissions)
        ):
            raise ValueError(f"public GLM admission drift for {cell['cell_key']}")
        admitted.append(cell["cell_key"])
    result = _sealed(
        {
            "schema_version": (
                "aeread.datacenter_terms_public_glm_transfer_profile_gate/0.1"
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
    run_root: Path,
    provider: Any,
) -> dict[str, Any]:
    cell_root = run_root / "live" / str(cell["cell_key"])
    path = cell_root / "result.json"
    if path.exists():
        result = _read_sealed(path)
        if result["run_plan_sha256"] != cell["run_plan_sha256"]:
            raise ValueError(f"resumed public GLM result drift for {cell['cell_key']}")
        return result
    if cell_root.exists():
        raise ValueError(f"refusing to replace incomplete GLM cell {cell['cell_key']}")
    route = _route(contract["model"])
    controls = contract["execution"]
    setup = _setup(contract, cell)
    started = time.perf_counter()
    try:
        returned_setup, execution = await run_openrouter(
            route,
            evidence_root=cell_root / "evidence",
            seed=int(cell["inference_seed"]),
            case_slug=CASE_SLUG,
            case_manifest=_case(),
            max_output_tokens=int(controls["max_output_tokens"]),
            timeout_seconds=float(controls["timeout_seconds"]),
            max_cost_usd=float(controls["max_cost_usd_per_cell"]),
            provider=provider,
        )
        if returned_setup.plan.plan_sha256 != setup.plan.plan_sha256:
            raise ValueError("public GLM live setup differs from sealed design")
        receipt = finalize_datacenter_terms_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_datacenter_terms_receipt(
            setup=setup,
            receipt=receipt,
            evidence_root=cell_root / "evidence",
        )
        result = _sealed(
            {
                "schema_version": (
                    "aeread.datacenter_terms_public_glm_transfer_cell/0.1"
                ),
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
                "schema_version": (
                    "aeread.datacenter_terms_public_glm_transfer_cell/0.1"
                ),
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


def _bridge_baselines() -> dict[tuple[str, int], dict[str, Any]]:
    manifest = _read_sealed(BRIDGE_PUBLICATION_ROOT / "publication_manifest.json")
    relative = "trajectories/sanitized.jsonl"
    path = BRIDGE_PUBLICATION_ROOT / relative
    payload = path.read_bytes()
    if _sha256_bytes(payload) != manifest["files"][relative]["sha256"]:
        raise ValueError("public GLM bridge trajectory digest differs")
    rows = [json.loads(line) for line in payload.splitlines()]
    selected = {
        (str(row["model_id"]), int(row["inference_seed"])): row
        for row in rows
        if row["wording_condition"] == "baseline"
        and row["case_slug"] == CASE_SLUG
        and row["model_id"] in BRIDGE_MODELS
    }
    expected = {
        (model_id, seed)
        for model_id in BRIDGE_MODELS
        for seed in (316001, 316002, 316003)
    }
    if set(selected) != expected:
        raise ValueError("public GLM bridge baseline cell set differs")
    return selected


def _bridge_rows(
    contract: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    prior = _bridge_baselines()
    current = {int(row["inference_seed"]): row for row in rows}
    result = []
    for seed in contract["inference_seeds"]:
        glm = current[seed]
        baselines = [prior[(model_id, seed)] for model_id in BRIDGE_MODELS]
        reportable = glm["status"] == "completed" and all(
            row["status"] == "completed" for row in baselines
        )
        scores = None
        hard_gates = None
        if reportable:
            scores = {
                **{
                    row["model_id"]: row["metrics"]["score"]
                    for row in baselines
                },
                MODEL_ID: glm["metrics"]["score"],
            }
            hard_gates = {
                **{
                    row["model_id"]: row["metrics"]["hard_gate_pass"]
                    for row in baselines
                },
                MODEL_ID: glm["metrics"]["hard_gate_pass"],
            }
        result.append(
            {
                "pair_key": f"baseline__seed_{seed}",
                "case_slug": CASE_SLUG,
                "source_cluster_id": contract["case"]["source_cluster_id"],
                "inference_seed": seed,
                "bridge_reportable": reportable,
                "scores": scores,
                "hard_gate_pass": hard_gates,
            }
        )
    return result


def _campaign_summary(
    contract: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    completed = [row for row in rows if row["status"] == "completed"]
    failures = [row for row in rows if row["status"] != "completed"]
    bridge = _bridge_rows(contract, rows)
    cost = math.fsum(
        float(row["usage"]["reported_cost_usd"])
        for row in completed
        if row["usage"] is not None
    )
    completed_gates = [bool(row["metrics"]["hard_gate_pass"]) for row in completed]
    pass_count = sum(completed_gates)
    decision = (
        "inconclusive_operational_missingness"
        if failures
        else (
            "qualifies_for_five_cluster_replication"
            if pass_count >= 2
            else (
                "broad_model_family_failure_on_integrated_case"
                if pass_count == 0
                else "mixed_does_not_qualify"
            )
        )
    )
    return _sealed(
        {
            "schema_version": (
                "aeread.datacenter_terms_public_glm_transfer_summary/0.1"
            ),
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "campaign_driver_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "claim_status": contract["claim_status"],
            "bridge": contract["bridge"],
            "case_count": 1,
            "independent_cluster_count": 1,
            "planned_cells": len(rows),
            "completed_cells": len(completed),
            "included_cells": sum(
                row["inclusion_status"] == "included" for row in rows
            ),
            "operational_failure_cells": len(failures),
            "failure_conditions": sorted(
                row["failure"]["failure_condition"] for row in failures
            ),
            "reported_cost_usd": cost,
            "provider_cost_complete": not failures,
            "cost_qualifier": "exact" if not failures else "lower_bound",
            "campaign_max_cost_usd": contract["execution"][
                "campaign_max_cost_usd"
            ],
            "within_declared_campaign_cost_ceiling": (
                cost <= contract["execution"]["campaign_max_cost_usd"]
            ),
            "all_completed_receipts_replayed": all(
                row["replay_verified"] for row in completed
            ),
            "model_summary": _group_summary("model_id", MODEL_ID, rows),
            "primary_endpoint": contract["analysis"]["primary_endpoint"],
            "decision_rule": contract["analysis"]["decision_rule"],
            "decision": decision,
            "bridge_rows": bridge,
            "bridge_reportable_count": sum(
                row["bridge_reportable"] for row in bridge
            ),
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
    provider_free = _read_sealed(
        run_root / "provider_free_validation" / "summary.json"
    )
    admission = _read_sealed(run_root / "profile_admission" / "summary.json")
    if provider_free["status"] != "passed" or admission["status"] != "passed":
        raise ValueError("public GLM gates must pass before live dispatch")
    if design["contract_sha256"] != _sha256(contract):
        raise ValueError("public GLM design contract differs")
    provider = provider_factory()
    rows = []
    for cell in design["cells"]:
        rows.append(
            await _run_live_cell(
                contract,
                cell,
                run_root=run_root,
                provider=provider,
            )
        )
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
        raise ValueError("unsupported public GLM campaign stage")
    contract = load_contract(contract_path)
    root = Path(run_root)
    design_path = root / "design" / "summary.json"
    if design_path.exists():
        design = _read_sealed(design_path)
        if design != build_design(contract):
            raise ValueError("stored public GLM design differs")
    else:
        design = build_design(contract)
        _atomic_write(design_path, design)
    if stop_after == "design":
        return design
    provider_free = await run_provider_free_gate(contract, run_root=root)
    if stop_after == "provider_free":
        return provider_free
    admission = run_profile_admission_gate(
        contract,
        design=design,
        run_root=root,
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
    "MODEL_ID",
    "build_design",
    "load_contract",
    "main",
    "run_campaign",
    "run_live_panel",
]
