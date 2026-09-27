"""Bounded paired Housing price pilot; preflight is provider-free.

Live mode is explicit and writes one immutable result per planned cell. A failed
cell remains missing, and any operational failure stops this small pilot.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import OpenRouterChatClient, execute_plan_cell
from aeread.shared_runner.task.receipts import verify_evaluation_receipt

from . import lemons
from .population_campaign import _failure_usage
from .runner import (
    GEMINI_38_FLASH_MODEL,
    GOOGLE_AI_STUDIO_GEMINI_38_FLASH_ROUTE,
    HousingScriptedLandlordProvider,
    HousingScriptedTenantProvider,
    build_housing_smoke,
    finalize_housing_execution,
    finalize_housing_failure,
    replay_housing_receipt,
)
from .price_bargaining import LANDLORD_MODEL
from .price_bargaining import LANDLORD_MARGIN


DEFAULT_CONTRACT = Path(__file__).resolve().parents[3] / "configs/housing_lemons_price_pilot_v1.json"
EXPECTED_ID = "housing_lemons_price_pilot_v1_gemini38_flash"


def load_contract(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if set(value) != {
        "schema_version", "campaign_id", "claim_status", "route", "world_seeds",
        "arms", "replicates", "rounds", "tenant_cost_ceiling_usd_per_cell",
        "total_cost_ceiling_usd", "max_consecutive_operational_failures", "controls", "analysis",
    }:
        raise ValueError("price pilot contract fields drifted")
    if value["schema_version"] != "aeread.housing_price_pilot/1" or value["campaign_id"] != EXPECTED_ID:
        raise ValueError("price pilot identity drifted")
    if value["claim_status"] != "development_pilot" or value["route"] != {
        "route_id": "google_gemini_38_flash",
        "requested_model": GEMINI_38_FLASH_MODEL,
        "canonical_model": GOOGLE_AI_STUDIO_GEMINI_38_FLASH_ROUTE.canonical_model,
        "provider": GOOGLE_AI_STUDIO_GEMINI_38_FLASH_ROUTE.provider,
        "quantization": GOOGLE_AI_STUDIO_GEMINI_38_FLASH_ROUTE.quantization,
        "input_per_million_usd": GOOGLE_AI_STUDIO_GEMINI_38_FLASH_ROUTE.input_per_million,
        "cached_input_per_million_usd": GOOGLE_AI_STUDIO_GEMINI_38_FLASH_ROUTE.cached_input_per_million,
        "output_per_million_usd": GOOGLE_AI_STUDIO_GEMINI_38_FLASH_ROUTE.output_per_million,
    }:
        raise ValueError("price pilot claim or route drifted")
    if value["world_seeds"] != [100000, 100001, 100002, 100003]:
        raise ValueError("price pilot world panel drifted")
    if value["arms"] != ["true_cost", "pooled"] or value["replicates"] != 1 or value["rounds"] != 3:
        raise ValueError("price pilot arms, replicates or rounds drifted")
    if value["tenant_cost_ceiling_usd_per_cell"] != 0.3 or value["total_cost_ceiling_usd"] != 3.0:
        raise ValueError("price pilot cost cap drifted")
    if value["max_consecutive_operational_failures"] != 1:
        raise ValueError("price pilot halt rule drifted")
    if value["controls"] != {
        "harness": "minimal_chat/1.0", "tools": "disabled", "memory": "disabled",
        "reasoning_effort": "low", "temperature": 1.0, "top_p": 1.0,
        "max_output_tokens": 4096, "timeout_seconds": 120.0,
        "sdk_retries": 0, "max_action_attempts": 4,
        "retryable_conditions": ["length", "rate_limit", "provider_5xx", "empty_response"],
        "tenant_inference_seed_base": 87001,
        "landlord_model": LANDLORD_MODEL, "landlord_margin_usd": LANDLORD_MARGIN,
        "execution_order": "world_seed_ascending_then_arm_order",
    }:
        raise ValueError("price pilot execution controls drifted")
    if value["analysis"] != {
        "independent_unit": "world_seed",
        "price_endpoint": "signed_rent_minus_ask_conditional_on_signing",
        "selection_endpoint": "signed_listings_divided_by_eligible_listings_by_quality",
        "missingness": "report_separately",
        "model_ranking_allowed": False,
    }:
        raise ValueError("price pilot analysis contract drifted")
    return value


def build_setup(contract: Mapping[str, Any], arm: str, *, live: bool):
    if arm not in contract["arms"]:
        raise ValueError("undeclared price arm")
    tenant = (
        {"tenant_provider": "openrouter", "tenant_model": GEMINI_38_FLASH_MODEL,
         "tenant_revision": GOOGLE_AI_STUDIO_GEMINI_38_FLASH_ROUTE.canonical_model}
        if live else
        {"tenant_provider": "housing_scripted_tenant",
         "tenant_model": "housing_scripted_tenant_inspect_then_sign_v1", "tenant_revision": "1.0.0"}
    )
    return build_housing_smoke(
        **tenant,
        landlord_model=contract["controls"]["landlord_model"],
        world_kind="lemons",
        lemon_landlord=arm,
        world_seeds=tuple(contract["world_seeds"]),
        num_tenants=6,
        num_listings=4,
        rounds=contract["rounds"],
        common_weight=0.6,
        lemon_share=0.5,
        lemon_loss=1000.0,
        inspection_cost=25.0,
        replicates=contract["replicates"],
        reasoning_condition_id="housing_price_bargaining_v1",
        reasoning_effort=contract["controls"]["reasoning_effort"],
        inference_seed_base=contract["controls"]["tenant_inference_seed_base"],
        openrouter_route=GOOGLE_AI_STUDIO_GEMINI_38_FLASH_ROUTE,
        tenant_profile_id_override=f"housing_price_{'gemini38' if live else 'scripted'}_tenant_v1",
        tenant_max_cost_usd_override=contract["tenant_cost_ceiling_usd_per_cell"] if live else None,
        tenant_temperature=contract["controls"]["temperature"] if live else 0.0,
        tenant_top_p=contract["controls"]["top_p"],
        max_output_tokens_override=contract["controls"]["max_output_tokens"],
        timeout_seconds_override=contract["controls"]["timeout_seconds"],
        max_action_attempts_override=contract["controls"]["max_action_attempts"],
        retryable_conditions_override=contract["controls"]["retryable_conditions"],
    )


def price_rows(outcome: Mapping[str, Any], world_seed: int, arm: str) -> list[dict[str, Any]]:
    world = lemons.make_lemons_world(
        6, 4, world_seed, 0.6, lemon_share=0.5, lemon_loss=1000.0,
        inspection_cost=25.0, landlord_reservation=arm,
    )
    rents = {int(row["tenant_id"]): float(row["rent"]) for row in outcome["signed_rents"]}
    assigned = {int(listing_id): int(tenant_id) for tenant_id, listing_id in outcome["assignment_pairs"]}
    if list(outcome["quality"]) != ["lemon" if q == lemons.LEMON else "sound" for q in world.quality]:
        raise ValueError("receipt quality differs from the paired world")
    return [
        {
            "world_seed": world_seed, "arm": arm, "listing_id": listing_id,
            "quality": "lemon" if world.quality[listing_id] == lemons.LEMON else "sound",
            "ask": world.ask[listing_id],
            "signed_rent": rents[assigned[listing_id]] if listing_id in assigned else None,
        }
        for listing_id in range(world.num_listings)
    ]


def summarize(rows: list[Mapping[str, Any]], planned: int) -> dict[str, Any]:
    result: dict[str, Any] = {"planned_cells": planned, "completed_cells": sum(r["status"] == "completed" for r in rows),
                              "operational_failures": sum(r["status"] == "operational_failure" for r in rows),
                              "cost_usd": round(sum(float(r.get("cost_usd", 0)) for r in rows), 6)}
    result["price_by_arm_quality"] = {}
    for arm in ("true_cost", "pooled"):
        for quality in ("sound", "lemon"):
            eligible = [item for row in rows if row["status"] == "completed" and row["arm"] == arm
                        for item in row["price_rows"] if item["quality"] == quality]
            signed = [item for item in eligible if item["signed_rent"] is not None]
            discounts = [item["signed_rent"] - item["ask"] for item in signed]
            result["price_by_arm_quality"][f"{arm}:{quality}"] = {
                "eligible_listings_in_completed_cells": len(eligible),
                "signed": len(signed),
                "mean_signed_minus_ask": round(statistics.mean(discounts), 2) if discounts else None,
            }
    return result


async def run(contract: Mapping[str, Any], run_root: Path, *, live: bool) -> dict[str, Any]:
    run_root.mkdir(parents=True, exist_ok=True)
    identity_path = run_root / "contract_sha256.txt"
    digest = hashlib.sha256(canonical_json_bytes(contract)).hexdigest()
    if identity_path.exists() and identity_path.read_text().strip() != digest:
        raise ValueError("run root belongs to a different price contract")
    identity_path.write_text(digest + "\n")
    setups = {arm: build_setup(contract, arm, live=live) for arm in contract["arms"]}
    provider = OpenRouterChatClient() if live else HousingScriptedTenantProvider()
    results_root = run_root / ("live" if live else "preflight")
    results_root.mkdir(exist_ok=True)
    rows: list[dict[str, Any]] = []
    halted = False
    for seed in contract["world_seeds"]:
        for arm in contract["arms"]:
            setup = setups[arm]
            cell = next(item for item in setup.plan.cells if item.world_seed == seed)
            result_path = results_root / f"world_{seed}__{arm}.json"
            if result_path.exists():
                row = json.loads(result_path.read_text())
                if row["status"] != "completed":
                    halted = True
                rows.append(row)
                continue
            if halted:
                rows.append({"world_seed": seed, "arm": arm, "status": "not_attempted", "cost_usd": 0.0})
                continue
            spent = sum(float(row.get("cost_usd", 0.0)) for row in rows)
            if live and spent + contract["tenant_cost_ceiling_usd_per_cell"] > contract["total_cost_ceiling_usd"]:
                halted = True
                rows.append({"world_seed": seed, "arm": arm, "status": "not_attempted_budget", "cost_usd": 0.0})
                continue
            evidence_root = results_root / f"world_{seed}__{arm}_evidence"
            try:
                execution = await execute_plan_cell(
                    plan=setup.plan, cell_id=cell.cell_id, registry=setup.registry,
                    evidence_root=evidence_root, prompt_sources=setup.prompt_sources,
                    providers={"openrouter" if live else "housing_scripted_tenant": provider,
                               "housing_scripted_landlord": HousingScriptedLandlordProvider()},
                    pricing=setup.pricing, harnesses=setup.harnesses,
                )
                receipt = finalize_housing_execution(setup=setup, execution=execution)
                verify_evaluation_receipt(receipt)
                replayed = replay_housing_receipt(setup=setup, receipt=receipt, evidence_root=evidence_root)
                if canonical_json_bytes(replayed.scores) != canonical_json_bytes(receipt.scores):
                    raise ValueError("score replay mismatch")
                row = {"world_seed": seed, "arm": arm, "status": "completed",
                       "cost_usd": execution.total_cost_usd, "receipt_sha256": receipt.receipt_sha256,
                       "run_plan_id": setup.plan.run_plan_id, "cell_id": cell.cell_id,
                       "tenant_net_total": execution.episode_result.outcome["tenant_net_total"],
                       "price_rows": price_rows(execution.episode_result.outcome, seed, arm)}
            except Exception as error:
                failure_receipt = None
                try:
                    failure_receipt = finalize_housing_failure(
                        setup=setup, cell_id=cell.cell_id, evidence_root=evidence_root, error=error
                    )
                except Exception:
                    pass
                usage = _failure_usage(evidence_root=evidence_root, run_plan_id=setup.plan.run_plan_id, cell_id=cell.cell_id)
                row = {"world_seed": seed, "arm": arm, "status": "operational_failure",
                       "failure_condition": getattr(error, "condition", type(error).__name__),
                       "cost_usd": usage["cost_usd"],
                       "receipt_sha256": failure_receipt.receipt_sha256 if failure_receipt else None}
                halted = True
            if live and (not math.isfinite(float(row["cost_usd"])) or float(row["cost_usd"]) > contract["tenant_cost_ceiling_usd_per_cell"]):
                halted = True
            result_path.write_bytes(canonical_json_bytes(row) + b"\n")
            rows.append(row)
            print(json.dumps({k: row[k] for k in ("world_seed", "arm", "status", "cost_usd")}), flush=True)
    summary = summarize(rows, len(contract["world_seeds"]) * len(contract["arms"]))
    (results_root / "summary.json").write_bytes(canonical_json_bytes(summary) + b"\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--live", action="store_true", help="make paid OpenRouter tenant calls")
    args = parser.parse_args()
    contract = load_contract(args.contract)
    print(json.dumps(asyncio.run(run(contract, args.run_root, live=args.live)), sort_keys=True))


if __name__ == "__main__":
    main()
