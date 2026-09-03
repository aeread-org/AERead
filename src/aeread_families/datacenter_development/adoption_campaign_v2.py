"""Starter-grounded V2 campaign for counteroffer-adoption depth."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.receipts import verify_evaluation_receipt

from .adoption_campaign import (
    _group_summary,
    _implementation_hashes as _v1_implementation_hashes,
)
from .adoption_environment import STAGE_SEQUENCES
from .adoption_runner_v2 import (
    build_adoption_setup_v2,
    finalize_adoption_execution_v2,
    finalize_adoption_failure_v2,
    load_adoption_case_v2,
    replay_adoption_receipt_v2,
    run_adoption_offline_v2,
    run_adoption_openrouter_v2,
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
    "aeread.datacenter_counteroffer_adoption_campaign_contract/0.2"
)
CAMPAIGN_ID = "datacenter_counteroffer_adoption_v2"
CONDITION = "starter_grounded_forced_first_written_counteroffer_exact_adoption"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT_PATH = REPOSITORY_ROOT / "configs" / f"{CAMPAIGN_ID}.json"
DEFAULT_RUN_ROOT = REPOSITORY_ROOT / "runs" / CAMPAIGN_ID
IMPLEMENTATION_SOURCES = (
    "adoption_environment_v2.py",
    "adoption_runner_v2.py",
    "adoption_campaign_v2.py",
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def load_contract(path: Path | str = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    contract = _read_json(Path(path))
    if set(contract) != {
        "schema_version", "campaign_id", "family_id", "family_version",
        "claim_status", "route_catalog_snapshot", "stages", "base_case",
        "inference_seeds", "condition", "models", "execution", "analysis",
    }:
        raise ValueError("V2 adoption contract fields differ")
    frozen = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "campaign_id": CAMPAIGN_ID,
        "family_id": "datacenter_counteroffer_adoption_v1",
        "family_version": "1.1.0",
        "condition": CONDITION,
        "claim_status": (
            "single_curated_project_starter_grounded_nested_depth_diagnostic_only"
        ),
    }
    if any(contract[key] != value for key, value in frozen.items()):
        raise ValueError("V2 adoption identity or claim boundary differs")
    if set(contract["stages"]) != set(STAGE_SEQUENCES):
        raise ValueError("V2 adoption stages differ")
    for stage_id, sequence in STAGE_SEQUENCES.items():
        stage = contract["stages"][stage_id]
        if set(stage) != {"case_id", "expected_case_sha256", "required_sequence"}:
            raise ValueError(f"{stage_id}: stage fields differ")
        if tuple(stage["required_sequence"]) != sequence:
            raise ValueError(f"{stage_id}: sequence differs")
    if set(contract["base_case"]) != {"case_id", "expected_case_sha256"}:
        raise ValueError("V2 base-case pin differs")
    seeds = contract["inference_seeds"]
    if (
        not isinstance(seeds, list) or len(seeds) != 3
        or len(seeds) != len(set(seeds))
        or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seeds)
    ):
        raise ValueError("V2 adoption requires three unique seeds")
    if set(contract["models"]) != {"mistral32_deepinfra", "qwen3_235b_novita"}:
        raise ValueError("V2 route panel differs")
    expected_routes = {
        "mistral32_deepinfra": (
            "mistralai/mistral-small-3.2-24b-instruct",
            "mistralai/mistral-small-3.2-24b-instruct-2506", "DeepInfra",
        ),
        "qwen3_235b_novita": (
            "qwen/qwen3-235b-a22b-2507",
            "qwen/qwen3-235b-a22b-07-25", "Novita",
        ),
    }
    for model_id, expected in expected_routes.items():
        model = contract["models"][model_id]
        if (model["requested_model"], model["canonical_model"], model["provider"]) != expected:
            raise ValueError(f"{model_id}: named route differs")
        if model["access_class"] != "open_source" or model["license_id"] != "Apache-2.0" or model["reasoning_effort"] is not None:
            raise ValueError(f"{model_id}: route policy differs")
    controls = contract["execution"]
    frozen_controls = {
        "harness": "minimal_chat/1.0",
        "adapter": CLIENT_IMPLEMENTATION_ID,
        "max_concurrent_cells_per_route_provider": 1,
        "max_action_attempts": 1,
        "sdk_retries": 0,
        "response_cache": False,
        "provider_fallbacks": False,
    }
    if any(controls.get(key) != value for key, value in frozen_controls.items()):
        raise ValueError("V2 adapter, retry, cache, route, or harness controls differ")
    worst = len(contract["stages"]) * len(seeds) * len(contract["models"]) * float(controls["max_cost_usd_per_live_profile"])
    if worst > float(controls["campaign_max_cost_usd"]):
        raise ValueError("V2 cell ceilings exceed campaign ceiling")
    analysis = contract["analysis"]
    if (
        analysis.get("independent_cluster_count") != 1
        or analysis.get("stage_variants_independent") is not False
        or analysis.get("nested_stage_order") != list(STAGE_SEQUENCES)
        or analysis.get("missingness") != "report_separately"
        or analysis.get("primary_estimand") != "counteroffer_adoption_rate"
    ):
        raise ValueError("V2 analysis contract differs")
    for field in ("winner_claim_allowed", "inferential_model_ranking_allowed", "causal_depth_effect_allowed"):
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
    return build_adoption_setup_v2(
        str(cell["stage_id"]),
        route=_route(contract["models"][cell["model_id"]]),
        seed=int(cell["inference_seed"]),
        max_output_tokens=int(controls["max_output_tokens_per_action"]),
        timeout_seconds=float(controls["timeout_seconds_per_action"]),
        max_cost_usd=float(controls["max_cost_usd_per_live_profile"]),
    )


def _implementation_hashes() -> dict[str, str]:
    hashes = _v1_implementation_hashes()
    root = Path(__file__).parent
    hashes.update({name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in IMPLEMENTATION_SOURCES})
    return hashes


def build_design(contract: Mapping[str, Any]) -> dict[str, Any]:
    base = load_stack_case("v2", OBJECTIVE_CASE_PATH)
    if base.case_id != contract["base_case"]["case_id"] or base.content_sha256 != contract["base_case"]["expected_case_sha256"]:
        raise ValueError("V2 base case differs from its pin")
    for stage_id, stage in contract["stages"].items():
        case = load_adoption_case_v2(stage_id)
        if case.case_id != stage["case_id"] or case.content_sha256 != stage["expected_case_sha256"]:
            raise ValueError(f"{stage_id}: V2 case differs from its pin")
    per_cell = float(contract["execution"]["max_cost_usd_per_live_profile"])
    cells = []
    for cell in _cells(contract):
        setup = _setup(contract, cell)
        plan_cell = setup.plan.cells[0]
        live_count = sum(profile.model.provider == "openrouter" for profile in setup.plan.agent_profiles)
        if live_count != 1 or setup.plan.evaluation_blocks[0].kind != "controlled":
            raise ValueError(f"V2 condition drift for {cell['cell_key']}")
        cells.append({**cell, "run_plan_id": setup.plan.run_plan_id, "run_plan_sha256": setup.plan.plan_sha256, "cell_id": plan_cell.cell_id, "case_id": plan_cell.case_id, "case_sha256": plan_cell.case_sha256, "evaluation_block_kind": "controlled", "live_profile_count": live_count, "declared_cell_max_cost_usd": per_cell})
    maximum = sum(cell["declared_cell_max_cost_usd"] for cell in cells)
    if maximum > float(contract["execution"]["campaign_max_cost_usd"]):
        raise ValueError("V2 resolved design exceeds campaign ceiling")
    hashes = _implementation_hashes()
    return _sealed({
        "schema_version": "aeread.datacenter_counteroffer_adoption_design/0.2",
        "campaign_id": CAMPAIGN_ID,
        "contract_sha256": _sha256(contract),
        "campaign_driver_sha256": hashes["adoption_campaign_v2.py"],
        "adapter_implementation_id": CLIENT_IMPLEMENTATION_ID,
        "implementation_source_sha256s": hashes,
        "base_case_id": base.case_id,
        "base_case_sha256": base.content_sha256,
        "independent_cluster_count": 1,
        "nested_stage_count": 3,
        "nested_stage_variants_independent": False,
        "planned_cells": len(cells),
        "paired_seed_count": len(contract["inference_seeds"]),
        "worst_case_declared_cost_usd": maximum,
        "campaign_max_cost_usd": contract["execution"]["campaign_max_cost_usd"],
        "predecessor_campaign_id": "datacenter_counteroffer_adoption_v1",
        "instrument_change": "public_valid_nonexact_starter_terms_and_schema_aligned_walk",
        "cells": cells,
    })


async def run_provider_free_gate(contract: Mapping[str, Any], *, run_root: Path) -> dict[str, Any]:
    path = run_root / "provider_free_validation" / "summary.json"
    if path.exists():
        return _read_sealed(path)
    rows = []
    for stage_id in contract["analysis"]["nested_stage_order"]:
        evidence = run_root / "provider_free_validation" / stage_id / "evidence"
        setup, execution = await run_adoption_offline_v2(stage_id, evidence_root=evidence)
        receipt = finalize_adoption_execution_v2(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_adoption_receipt_v2(setup=setup, receipt=receipt, evidence_root=evidence)
        verify_evaluation_receipt(replayed)
        score = next(item for item in receipt.scores if item.leaf.leaf_id == "counteroffer_adoption_rate")
        outcome = execution.episode_result.outcome
        passed = receipt.inclusion_status == "included" and score.primary.value == 1 and outcome["exact_package_integrity"] and replayed == receipt
        rows.append({"stage_id": stage_id, "status": "passed" if passed else "failed", "case_sha256": setup.case.content_sha256, "logical_action_count": execution.episode_result.logical_action_count, "primary_score": score.primary.value, "executed_agreement_count": outcome["executed_agreement_count"], "counteroffer_opportunity_count": outcome["counteroffer_opportunity_count"], "receipt_sha256": receipt.receipt_sha256, "replay_verified": replayed == receipt})
    result = _sealed({"schema_version": "aeread.datacenter_counteroffer_adoption_provider_free_gate/0.2", "campaign_id": CAMPAIGN_ID, "contract_sha256": _sha256(contract), "status": "passed" if all(row["status"] == "passed" for row in rows) else "failed", "stages": rows})
    _atomic_write(path, result)
    return result


def run_profile_admission_gate(contract: Mapping[str, Any], *, design: Mapping[str, Any], run_root: Path) -> dict[str, Any]:
    path = run_root / "profile_admission" / "summary.json"
    if path.exists():
        return _read_sealed(path)
    expected = {cell["cell_key"]: cell for cell in design["cells"]}
    admitted = []
    for cell in _cells(contract):
        setup = _setup(contract, cell)
        target = expected[cell["cell_key"]]
        if setup.plan.plan_sha256 != target["run_plan_sha256"] or setup.plan.cells[0].cell_id != target["cell_id"] or not all(item.admitted for item in setup.plan.profile_admissions):
            raise ValueError(f"V2 admission drift for {cell['cell_key']}")
        admitted.append(cell["cell_key"])
    result = _sealed({"schema_version": "aeread.datacenter_counteroffer_adoption_profile_gate/0.2", "campaign_id": CAMPAIGN_ID, "contract_sha256": _sha256(contract), "status": "passed", "admitted_cells": admitted})
    _atomic_write(path, result)
    return result


async def _run_live_cell(contract: Mapping[str, Any], cell: Mapping[str, Any], *, run_root: Path, provider: Any) -> dict[str, Any]:
    root = run_root / "live" / str(cell["cell_key"])
    path = root / "result.json"
    if path.exists():
        result = _read_sealed(path)
        if result["run_plan_sha256"] != cell["run_plan_sha256"]:
            raise ValueError(f"V2 resumed result drift for {cell['cell_key']}")
        return result
    if root.exists():
        raise ValueError(f"refusing to replace incomplete V2 cell {cell['cell_key']}")
    setup = _setup(contract, cell)
    controls = contract["execution"]
    started = time.perf_counter()
    try:
        _, execution = await run_adoption_openrouter_v2(str(cell["stage_id"]), _route(contract["models"][cell["model_id"]]), evidence_root=root / "evidence", seed=int(cell["inference_seed"]), max_output_tokens=int(controls["max_output_tokens_per_action"]), timeout_seconds=float(controls["timeout_seconds_per_action"]), max_cost_usd=float(controls["max_cost_usd_per_live_profile"]), provider=provider)
        receipt = finalize_adoption_execution_v2(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_adoption_receipt_v2(setup=setup, receipt=receipt, evidence_root=root / "evidence")
        verify_evaluation_receipt(replayed)
        result = _sealed({"schema_version": "aeread.datacenter_counteroffer_adoption_live_cell/0.2", "campaign_id": CAMPAIGN_ID, **dict(cell), "status": "completed", "receipt_status": receipt.status, "inclusion_status": receipt.inclusion_status, "receipt_sha256": receipt.receipt_sha256, "replay_verified": replayed == receipt, "elapsed_seconds": time.perf_counter() - started, "usage": _call_usage(execution), "outcome": _plain(execution.episode_result.outcome), "scores": _score_projection(receipt), "failure": None})
    except Exception as error:
        receipt = finalize_adoption_failure_v2(setup=setup, cell_id=setup.plan.cells[0].cell_id, evidence_root=root / "evidence", error=error)
        verify_evaluation_receipt(receipt)
        result = _sealed({"schema_version": "aeread.datacenter_counteroffer_adoption_live_cell/0.2", "campaign_id": CAMPAIGN_ID, **dict(cell), "status": "operational_failure", "receipt_status": receipt.status, "inclusion_status": receipt.inclusion_status, "receipt_sha256": receipt.receipt_sha256, "replay_verified": False, "elapsed_seconds": time.perf_counter() - started, "usage": None, "outcome": None, "scores": None, "failure": {"failure_class": receipt.failure.failure_class, "failure_condition": receipt.failure.condition, "error_type": type(error).__name__}})
    _atomic_write(path, result)
    return result


def summarize(contract: Mapping[str, Any], design: Mapping[str, Any], rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if row["status"] == "completed"]
    operational = [row for row in rows if row["status"] != "completed"]
    cost = sum(float(row["usage"]["reported_cost_usd"]) for row in completed if row["usage"] is not None)
    return _sealed({"schema_version": "aeread.datacenter_counteroffer_adoption_summary/0.2", "campaign_id": CAMPAIGN_ID, "contract_sha256": _sha256(contract), "design_sha256": design["artifact_sha256"], "campaign_driver_sha256": design["campaign_driver_sha256"], "implementation_source_sha256s": design["implementation_source_sha256s"], "claim_status": contract["claim_status"], "predecessor_campaign_id": design["predecessor_campaign_id"], "instrument_change": design["instrument_change"], "independent_cluster_count": 1, "nested_stage_variants_independent": False, "planned_cells": len(rows), "completed_cells": len(completed), "included_cells": sum(row["inclusion_status"] == "included" for row in completed), "operational_failure_cells": len(operational), "failure_fraction": len(operational) / len(rows), "failure_conditions": [row["failure"]["failure_condition"] for row in operational], "reported_cost_usd": cost, "provider_cost_complete": not operational, "cost_qualifier": "exact" if not operational else "lower_bound", "campaign_max_cost_usd": contract["execution"]["campaign_max_cost_usd"], "within_declared_campaign_cost_ceiling": cost <= float(contract["execution"]["campaign_max_cost_usd"]), "model_summaries": [_group_summary(key="model_id", value=model_id, rows=rows) for model_id in sorted(contract["models"])], "stage_summaries": [_group_summary(key="stage_id", value=stage_id, rows=rows) for stage_id in contract["analysis"]["nested_stage_order"]], "winner_claim_allowed": False, "inferential_model_ranking_allowed": False, "causal_depth_effect_allowed": False})


async def run_campaign(*, contract_path: Path | str = DEFAULT_CONTRACT_PATH, run_root: Path | str = DEFAULT_RUN_ROOT, stop_after: str = "live", provider_factory: Callable[[], Any] = ParameterCompatibleOpenRouterClient) -> dict[str, Any]:
    contract = load_contract(contract_path)
    root = Path(run_root)
    design = build_design(contract)
    _atomic_write(root / "design.json", design)
    if stop_after == "design": return design
    gate = await run_provider_free_gate(contract, run_root=root)
    if gate["status"] != "passed": raise ValueError("V2 provider-free gate failed")
    if stop_after == "provider_free": return gate
    admission = run_profile_admission_gate(contract, design=design, run_root=root)
    if admission["status"] != "passed": raise ValueError("V2 profile gate failed")
    if stop_after == "profile_admission": return admission
    concurrency = asyncio.Semaphore(int(contract["execution"]["concurrency"]))
    locks = {str(model["provider"]): asyncio.Semaphore(1) for model in contract["models"].values()}
    async def execute(cell):
        provider_name = str(contract["models"][cell["model_id"]]["provider"])
        async with concurrency, locks[provider_name]:
            return await _run_live_cell(contract, cell, run_root=root, provider=provider_factory())
    rows = await asyncio.gather(*(execute(cell) for cell in design["cells"]))
    summary = summarize(contract, design, list(rows))
    _atomic_write(root / "live" / "summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT_PATH)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--stop-after", choices=("design", "provider_free", "profile_admission", "live"), default="live")
    args = parser.parse_args(argv)
    print(canonical_json_bytes(asyncio.run(run_campaign(contract_path=args.contract, run_root=args.run_root, stop_after=args.stop_after))).decode("utf-8"))
    return 0


if __name__ == "__main__": raise SystemExit(main())


__all__ = ["CAMPAIGN_ID", "DEFAULT_CONTRACT_PATH", "DEFAULT_RUN_ROOT", "build_design", "load_contract", "run_campaign", "summarize"]
