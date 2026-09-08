"""Run a GLM add-on linked to the grounded two-route data-center panel."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.receipts import verify_evaluation_receipt
from aeread_families.datacenter_development.objective_openrouter import (
    CLIENT_IMPLEMENTATION_ID,
    ParameterCompatibleOpenRouterClient,
)

from .campaign import _atomic_write, _call_usage, _read_sealed, _route, _sealed, _sha256
from .grounded_campaign import (
    DEFAULT_CONTRACT_PATH as BRIDGE_CONTRACT_PATH,
    DEFAULT_RUN_ROOT as BRIDGE_RUN_ROOT,
    _cases_by_slug,
    _group_summary,
    _setup,
    load_contract as load_bridge_contract,
)
from .grounded_cases import CLUSTER_ID, PACK_ID, grounded_pack_sha256
from .runner import (
    build_openrouter_setup,
    finalize_datacenter_terms_execution,
    finalize_datacenter_terms_failure,
    replay_datacenter_terms_receipt,
    run_openrouter,
)


CONTRACT_SCHEMA_VERSION = "aeread.datacenter_terms_grounded_glm_contract/0.1"
CAMPAIGN_ID = "datacenter_development_terms_grounded_glm_v1"
MODEL_ID = "glm53_reka"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT_PATH = REPOSITORY_ROOT / "configs" / f"{CAMPAIGN_ID}.json"
DEFAULT_RUN_ROOT = REPOSITORY_ROOT / "runs" / CAMPAIGN_ID


def _bridge_artifacts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract = load_bridge_contract(BRIDGE_CONTRACT_PATH)
    design = _read_sealed(BRIDGE_RUN_ROOT / "design" / "summary.json")
    summary = _read_sealed(BRIDGE_RUN_ROOT / "live" / "summary.json")
    return contract, design, summary


def load_contract(path: Path | str = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    frozen = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "campaign_id": CAMPAIGN_ID,
        "family_id": "datacenter_development_terms_v1",
        "family_version": "1.0.0",
        "pack_id": PACK_ID,
        "pack_sha256": grounded_pack_sha256(),
        "claim_status": (
            "source_grounded_glm_addon_diagnostic_one_conservative_archive_cluster"
        ),
    }
    if not isinstance(contract, dict) or any(
        contract.get(key) != value for key, value in frozen.items()
    ):
        raise ValueError("grounded GLM campaign identity differs")
    if set(contract) != {
        *frozen,
        "bridge",
        "case_slugs",
        "inference_seeds",
        "model",
        "execution",
        "analysis",
    }:
        raise ValueError("grounded GLM campaign fields differ")
    cases = _cases_by_slug()
    if contract["case_slugs"] != sorted(cases):
        raise ValueError("grounded GLM case panel differs")
    seeds = contract["inference_seeds"]
    if seeds != [313001, 313002, 313003]:
        raise ValueError("grounded GLM inference seeds differ")
    model = contract["model"]
    expected_route = (
        "z-ai/glm-5.3-flash",
        "z-ai/glm-5.3-flash-20260826",
        "Reka",
        "fp8",
        "open_source",
        "MIT",
        "low",
    )
    actual_route = (
        model.get("requested_model"),
        model.get("canonical_model"),
        model.get("provider"),
        model.get("quantization"),
        model.get("access_class"),
        model.get("license_id"),
        model.get("reasoning_effort"),
    )
    if model.get("model_id") != MODEL_ID or actual_route != expected_route:
        raise ValueError("grounded GLM route differs")
    controls = contract["execution"]
    required_controls = {
        "harness": "minimal_chat/1.0",
        "adapter": CLIENT_IMPLEMENTATION_ID,
        "concurrency": 1,
        "max_concurrent_cells_per_route_provider": 1,
        "max_action_attempts": 1,
        "sdk_retries": 0,
        "response_cache": False,
        "provider_fallbacks": False,
    }
    if any(controls.get(key) != value for key, value in required_controls.items()):
        raise ValueError("grounded GLM execution controls differ")
    if len(cases) * len(seeds) * float(controls["max_cost_usd_per_cell"]) > float(
        controls["campaign_max_cost_usd"]
    ):
        raise ValueError("grounded GLM campaign exceeds its cost ceiling")
    required_analysis = {
        "case_count": 4,
        "independent_cluster_count": 1,
        "resampling_unit": "conservative_source_archive_cluster",
        "paired_by_bridge": ["case_slug", "inference_seed"],
        "missingness": "report_separately_no_selective_retry",
        "winner_claim_allowed": False,
        "inferential_model_ranking_allowed": False,
        "project_generalization_allowed": False,
        "population_causal_effect_allowed": False,
    }
    if any(contract["analysis"].get(key) != value for key, value in required_analysis.items()):
        raise ValueError("grounded GLM analysis contract differs")

    bridge_contract, bridge_design, bridge_summary = _bridge_artifacts()
    bridge = contract["bridge"]
    if bridge != {
        "campaign_id": bridge_contract["campaign_id"],
        "contract_sha256": _sha256(bridge_contract),
        "design_sha256": bridge_design["artifact_sha256"],
        "live_summary_sha256": bridge_summary["artifact_sha256"],
        "comparison_scope": (
            "same_case_hash_prompt_schema_harness_and_inference_seed_descriptive_only"
        ),
    }:
        raise ValueError("grounded GLM bridge artifacts differ")
    if bridge_summary["completed_cells"] != 24:
        raise ValueError("grounded GLM bridge panel is incomplete")
    return contract


def _panel_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **dict(contract),
        "models": {MODEL_ID: contract["model"]},
    }


def _cells(contract: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "cell_key": f"{slug}__{MODEL_ID}__seed_{seed}",
            "pair_key": f"{slug}__seed_{seed}",
            "case_slug": slug,
            "source_cluster_id": CLUSTER_ID,
            "model_id": MODEL_ID,
            "inference_seed": seed,
        }
        for slug in contract["case_slugs"]
        for seed in contract["inference_seeds"]
    )


def _implementation_hashes() -> dict[str, str]:
    root = Path(__file__).parent
    names = (
        "environment.py",
        "runner.py",
        "grounded_cases.py",
        "grounded_campaign.py",
        "grounded_glm_campaign.py",
    )
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in names
    }


def _assert_bridge_setup(
    contract: Mapping[str, Any],
    cell: Mapping[str, Any],
    setup: Any,
) -> None:
    bridge_contract = load_bridge_contract(BRIDGE_CONTRACT_PATH)
    cases = _cases_by_slug()
    prior_cell = {
        **dict(cell),
        "model_id": "qwen3_235b_novita",
    }
    prior = _setup(bridge_contract, prior_cell, cases)
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
        raise ValueError("grounded GLM setup is not bridge-compatible")


def build_design(contract: Mapping[str, Any]) -> dict[str, Any]:
    cases = _cases_by_slug()
    panel_contract = _panel_contract(contract)
    per_cell = float(contract["execution"]["max_cost_usd_per_cell"])
    cells = []
    for cell in _cells(contract):
        setup = _setup(panel_contract, cell, cases)
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
                "live_profile_count": 1,
                "declared_cell_max_cost_usd": per_cell,
            }
        )
    hashes = _implementation_hashes()
    return _sealed(
        {
            "schema_version": "aeread.datacenter_terms_grounded_glm_design/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "pack_sha256": grounded_pack_sha256(),
            "bridge": contract["bridge"],
            "campaign_driver_sha256": hashes["grounded_glm_campaign.py"],
            "implementation_source_sha256s": hashes,
            "case_count": 4,
            "independent_cluster_count": 1,
            "planned_cells": len(cells),
            "worst_case_declared_cost_usd": len(cells) * per_cell,
            "campaign_max_cost_usd": contract["execution"]["campaign_max_cost_usd"],
            "cells": cells,
        }
    )


def run_inherited_provider_free_gate(
    contract: Mapping[str, Any], *, run_root: Path
) -> dict[str, Any]:
    path = run_root / "provider_free_validation" / "summary.json"
    if path.exists():
        return _read_sealed(path)
    source = _read_sealed(BRIDGE_RUN_ROOT / "provider_free_validation" / "summary.json")
    if source["status"] != "passed" or len(source["cases"]) != 4:
        raise ValueError("bridge provider-free gate is not reusable")
    result = _sealed(
        {
            "schema_version": "aeread.datacenter_terms_grounded_glm_provider_free_gate/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "status": "passed",
            "mode": "inherited_same_pack_environment_scorer_and_cases",
            "source_campaign_id": contract["bridge"]["campaign_id"],
            "source_gate_sha256": source["artifact_sha256"],
            "case_count": 4,
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
    panel_contract = _panel_contract(contract)
    expected = {cell["cell_key"]: cell for cell in design["cells"]}
    admitted = []
    for cell in _cells(contract):
        setup = _setup(panel_contract, cell, cases)
        target = expected[cell["cell_key"]]
        if (
            setup.plan.plan_sha256 != target["run_plan_sha256"]
            or setup.plan.cells[0].cell_id != target["cell_id"]
            or not all(item.admitted for item in setup.plan.profile_admissions)
        ):
            raise ValueError(f"GLM profile admission drift for {cell['cell_key']}")
        admitted.append(cell["cell_key"])
    result = _sealed(
        {
            "schema_version": "aeread.datacenter_terms_grounded_glm_profile_gate/0.1",
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
    cell_root = run_root / "live" / cell["cell_key"]
    path = cell_root / "result.json"
    if path.exists():
        return _read_sealed(path)
    if cell_root.exists():
        raise ValueError(f"refusing to replace incomplete GLM cell {cell['cell_key']}")
    cases = _cases_by_slug()
    case = cases[cell["case_slug"]]
    panel_contract = _panel_contract(contract)
    setup = _setup(panel_contract, cell, cases)
    route = _route(contract["model"])
    controls = contract["execution"]
    started = time.perf_counter()
    try:
        returned_setup, execution = await run_openrouter(
            route,
            evidence_root=cell_root / "evidence",
            seed=cell["inference_seed"],
            case_slug=cell["case_slug"],
            case_manifest=case,
            max_output_tokens=int(controls["max_output_tokens"]),
            timeout_seconds=float(controls["timeout_seconds"]),
            max_cost_usd=float(controls["max_cost_usd_per_cell"]),
            provider=provider,
        )
        if returned_setup.plan.plan_sha256 != setup.plan.plan_sha256:
            raise ValueError("GLM live setup differs from sealed design")
        receipt = finalize_datacenter_terms_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_datacenter_terms_receipt(
            setup=setup,
            receipt=receipt,
            evidence_root=cell_root / "evidence",
        )
        result = _sealed(
            {
                "schema_version": "aeread.datacenter_terms_grounded_glm_live_cell/0.1",
                "campaign_id": CAMPAIGN_ID,
                **dict(cell),
                "run_plan_id": setup.plan.run_plan_id,
                "run_plan_sha256": setup.plan.plan_sha256,
                "cell_id": setup.plan.cells[0].cell_id,
                "case_id": case.case_id,
                "case_sha256": case.content_sha256,
                "profile_id": setup.plan.agent_profiles[0].profile_id,
                "status": "completed",
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
        result = _sealed(
            {
                "schema_version": "aeread.datacenter_terms_grounded_glm_live_cell/0.1",
                "campaign_id": CAMPAIGN_ID,
                **dict(cell),
                "run_plan_id": setup.plan.run_plan_id,
                "run_plan_sha256": setup.plan.plan_sha256,
                "cell_id": setup.plan.cells[0].cell_id,
                "case_id": case.case_id,
                "case_sha256": case.content_sha256,
                "profile_id": setup.plan.agent_profiles[0].profile_id,
                "status": "operational_failure",
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


def _bridge_rows(
    rows: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    prior_results = {
        (row["case_slug"], row["inference_seed"], row["model_id"]): row
        for path in sorted((BRIDGE_RUN_ROOT / "live").glob("*/result.json"))
        for row in [_read_sealed(path)]
    }
    glm_results = {
        (row["case_slug"], row["inference_seed"]): row for row in rows
    }
    result = []
    for case_slug, seed in sorted(glm_results):
        glm = glm_results[(case_slug, seed)]
        models = {
            model_id: prior_results[(case_slug, seed, model_id)]
            for model_id in ("mistral32_deepinfra", "qwen3_235b_novita")
        }
        usable = glm["status"] == "completed" and all(
            row["status"] == "completed" for row in models.values()
        )
        result.append(
            {
                "pair_key": f"{case_slug}__seed_{seed}",
                "case_slug": case_slug,
                "inference_seed": seed,
                "bridge_reportable": usable,
                "scores": (
                    {
                        "mistral32_deepinfra": models["mistral32_deepinfra"]["metrics"]["score"],
                        "qwen3_235b_novita": models["qwen3_235b_novita"]["metrics"]["score"],
                        MODEL_ID: glm["metrics"]["score"],
                    }
                    if usable
                    else None
                ),
            }
        )
    return result


def _campaign_summary(
    contract: Mapping[str, Any], rows: list[Mapping[str, Any]]
) -> dict[str, Any]:
    completed = [row for row in rows if row["status"] == "completed"]
    failures = [row for row in rows if row["status"] != "completed"]
    bridge = _bridge_rows(rows)
    cost = math.fsum(
        float(row["usage"]["reported_cost_usd"])
        for row in completed
        if row["usage"] is not None
    )
    return _sealed(
        {
            "schema_version": "aeread.datacenter_terms_grounded_glm_summary/0.1",
            "campaign_id": CAMPAIGN_ID,
            "contract_sha256": _sha256(contract),
            "claim_status": contract["claim_status"],
            "bridge": contract["bridge"],
            "planned_cells": len(rows),
            "completed_cells": len(completed),
            "included_cells": sum(row["inclusion_status"] == "included" for row in rows),
            "operational_failure_cells": len(failures),
            "failure_conditions": sorted(
                row["failure"]["failure_condition"] for row in failures
            ),
            "reported_cost_usd": cost,
            "cost_qualifier": "exact" if not failures else "lower_bound",
            "campaign_max_cost_usd": contract["execution"]["campaign_max_cost_usd"],
            "within_declared_campaign_cost_ceiling": cost
            <= contract["execution"]["campaign_max_cost_usd"],
            "all_completed_receipts_replayed": all(
                row["replay_verified"] for row in completed
            ),
            "independent_cluster_count": 1,
            "model_summary": _group_summary("model_id", MODEL_ID, rows),
            "case_summaries": [
                _group_summary("case_slug", slug, rows)
                for slug in contract["case_slugs"]
            ],
            "bridge_rows": bridge,
            "bridge_reportable_count": sum(row["bridge_reportable"] for row in bridge),
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
        raise ValueError("grounded GLM gates must pass before live dispatch")
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
        raise ValueError("unsupported grounded GLM campaign stage")
    contract = load_contract(contract_path)
    root = Path(run_root)
    design_path = root / "design" / "summary.json"
    if design_path.exists():
        design = _read_sealed(design_path)
        if design != build_design(contract):
            raise ValueError("stored grounded GLM design differs")
    else:
        design = build_design(contract)
        _atomic_write(design_path, design)
    if stop_after == "design":
        return design
    provider_free = run_inherited_provider_free_gate(contract, run_root=root)
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
]
