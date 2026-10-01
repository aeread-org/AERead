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
    GLM_53_FLASH_MODEL,
    GLM_53_FLASH_REVISION,
    GOOGLE_AI_STUDIO_GEMINI_38_FLASH_ROUTE,
    PARASAIL_GLM_53_FLASH_ROUTE,
    HousingScriptedLandlordProvider,
    OpenRouterRoutePin,
    HousingScriptedTenantProvider,
    build_housing_smoke,
    finalize_housing_execution,
    finalize_housing_failure,
    replay_housing_receipt,
)
from .price_bargaining import LANDLORD_MODEL
from .price_endpoint import OUTCOME_FACTS
from .price_bargaining import LANDLORD_MARGIN


DEFAULT_CONTRACT = Path(__file__).resolve().parents[3] / "configs/housing_lemons_price_pilot_v1.json"
EXPECTED_ID = "housing_lemons_price_pilot_v1_gemini38_flash"

# Route pins for the v2 price identities. They live here and not in runner.py:
# a plan's implementation digests hash the bytes of runner.py, environment.py,
# lemons.py and price_bargaining.py, so editing any of them changes the run-plan
# id of every sealed Housing identity (HL-T-04). This module is not hashed.
#
# The OpenRouter catalog read on 2026-09-30 lists DeepInfra's GLM 5.3 Flash at
# fp4 and the route filter sends ``quantizations`` upstream, so the fp8 pin in
# runner.py can no longer find its endpoint. Prices are unchanged.
DEEPINFRA_GLM_53_FLASH_FP4_ROUTE = OpenRouterRoutePin(
    provider="DeepInfra",
    quantization="fp4",
    canonical_model=GLM_53_FLASH_REVISION,
    input_per_million=0.075,
    cached_input_per_million=0.015,
    output_per_million=0.25,
    pricing_id="openrouter_deepinfra_2026-09-30_glm-5.3-flash-fp4",
)
# GPT-5.6 Luna on OpenAI. The catalog lists three OpenAI tiers ($0.10/$0.60,
# $0.20/$1.20, $0.40/$2.40 per million); the pin names the standard tier, so the
# route price ceiling also admits the cheaper tier and a priced cost is an upper
# bound. The model accepts no temperature or top_p.
GPT_56_LUNA_MODEL = "openai/gpt-5.6-luna"
OPENAI_GPT_56_LUNA_ROUTE = OpenRouterRoutePin(
    provider="OpenAI",
    quantization="unknown",
    canonical_model="openai/gpt-5.6-luna-20260709",
    input_per_million=0.2,
    cached_input_per_million=0.02,
    output_per_million=1.2,
    pricing_id="openrouter_openai_2026-09-30_gpt-5.6-luna",
)

#: Sealed routes this driver knows. A contract names one; the driver refuses a
#: route whose identity drifts from the pin the runner carries.
ROUTES: dict[str, tuple[str, Any]] = {
    "google_gemini_38_flash": (GEMINI_38_FLASH_MODEL, GOOGLE_AI_STUDIO_GEMINI_38_FLASH_ROUTE),
    "deepinfra_glm_53_flash_fp4": (GLM_53_FLASH_MODEL, DEEPINFRA_GLM_53_FLASH_FP4_ROUTE),
    "openai_gpt_56_luna": (GPT_56_LUNA_MODEL, OPENAI_GPT_56_LUNA_ROUTE),
    "parasail_glm_53_flash": (GLM_53_FLASH_MODEL, PARASAIL_GLM_53_FLASH_ROUTE),
}

#: Every identity this driver runs. v1 is the sealed Gemini pilot as run. The two
#: v2 identities put the same four worlds and both landlord arms in front of a
#: second and third model, so the models see identical lemon draws. Luna accepts
#: no temperature or top_p, so its sampling controls are declared unavailable and
#: its replicates differ only through the request seed.
IDENTITIES: dict[str, dict[str, Any]] = {
    EXPECTED_ID: {
        "route_id": "google_gemini_38_flash", "profile": "housing_price_gemini38_tenant_v1",
        "reasoning_effort": "low", "temperature": 1.0, "top_p": 1.0, "total_cost_ceiling_usd": 3.0,
    },
    "housing_lemons_price_pilot_v2_glm53_flash_deepinfra": {
        "route_id": "deepinfra_glm_53_flash_fp4", "profile": "housing_price_glm53_deepinfra_tenant_v2",
        "reasoning_effort": "low", "temperature": 1.0, "top_p": 1.0, "total_cost_ceiling_usd": 0.5,
    },
    # The DeepInfra identity above ran once and failed (HL-O-08): its fp4 endpoint
    # returns the answer in ``reasoning`` with ``content`` null on most calls. This one
    # keeps the model and every control and moves to the route the lemons v2 GLM run
    # used, which returns content.
    "housing_lemons_price_pilot_v2_glm53_flash_parasail": {
        "route_id": "parasail_glm_53_flash", "profile": "housing_price_glm53_parasail_tenant_v2",
        "reasoning_effort": "low", "temperature": 1.0, "top_p": 1.0, "total_cost_ceiling_usd": 0.5,
    },
    # K=2 over the same four worlds (owner decision 2026-09-30): the K=1 runs left the
    # replicate noise unmeasured, and the realized arm contrast changed sign by model.
    "housing_lemons_price_pilot_v3_glm53_flash_parasail_k2": {
        "route_id": "parasail_glm_53_flash", "profile": "housing_price_glm53_parasail_tenant_v3",
        "reasoning_effort": "low", "temperature": 1.0, "top_p": 1.0, "total_cost_ceiling_usd": 0.5,
        "replicates": 2,
    },
    "housing_lemons_price_pilot_v3_gpt56_luna_k2": {
        "route_id": "openai_gpt_56_luna", "profile": "housing_price_gpt56_luna_tenant_v3",
        "reasoning_effort": "low", "temperature": "unavailable", "top_p": None,
        "total_cost_ceiling_usd": 1.0, "replicates": 2,
    },
    "housing_lemons_price_pilot_v2_gpt56_luna": {
        "route_id": "openai_gpt_56_luna", "profile": "housing_price_gpt56_luna_tenant_v2",
        "reasoning_effort": "low", "temperature": "unavailable", "top_p": None, "total_cost_ceiling_usd": 1.0,
    },
}


def _route_block(route_id: str) -> dict[str, Any]:
    model, pin = ROUTES[route_id]
    return {
        "route_id": route_id,
        "requested_model": model,
        "canonical_model": pin.canonical_model,
        "provider": pin.provider,
        "quantization": pin.quantization,
        "input_per_million_usd": pin.input_per_million,
        "cached_input_per_million_usd": pin.cached_input_per_million,
        "output_per_million_usd": pin.output_per_million,
    }


def identity(contract: Mapping[str, Any]) -> dict[str, Any]:
    spec = IDENTITIES.get(contract.get("campaign_id"))
    if spec is None:
        raise ValueError("price pilot identity drifted")
    return spec


def load_contract(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if set(value) != {
        "schema_version", "campaign_id", "claim_status", "route", "world_seeds",
        "arms", "replicates", "rounds", "tenant_cost_ceiling_usd_per_cell",
        "total_cost_ceiling_usd", "max_consecutive_operational_failures", "controls", "analysis",
    }:
        raise ValueError("price pilot contract fields drifted")
    spec = identity(value)
    if value["schema_version"] != "aeread.housing_price_pilot/1":
        raise ValueError("price pilot identity drifted")
    if value["claim_status"] != "development_pilot" or value["route"] != _route_block(spec["route_id"]):
        raise ValueError("price pilot claim or route drifted")
    if value["world_seeds"] != [100000, 100001, 100002, 100003]:
        raise ValueError("price pilot world panel drifted")
    if (
        value["arms"] != ["true_cost", "pooled"]
        or value["replicates"] != spec.get("replicates", 1)
        or value["rounds"] != 3
    ):
        raise ValueError("price pilot arms, replicates or rounds drifted")
    if (
        value["tenant_cost_ceiling_usd_per_cell"] != 0.3
        or value["total_cost_ceiling_usd"] != spec["total_cost_ceiling_usd"]
    ):
        raise ValueError("price pilot cost cap drifted")
    if value["max_consecutive_operational_failures"] != 1:
        raise ValueError("price pilot halt rule drifted")
    if value["controls"] != {
        "harness": "minimal_chat/1.0", "tools": "disabled", "memory": "disabled",
        "reasoning_effort": spec["reasoning_effort"], "temperature": spec["temperature"],
        "top_p": spec["top_p"],
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
    spec = identity(contract)
    model, route = ROUTES[spec["route_id"]]
    controls = contract["controls"]
    unavailable = controls["temperature"] == "unavailable"
    tenant = (
        {"tenant_provider": "openrouter", "tenant_model": model,
         "tenant_revision": route.canonical_model}
        if live else
        {"tenant_provider": "housing_scripted_tenant",
         "tenant_model": "housing_scripted_tenant_inspect_then_sign_v1", "tenant_revision": "1.0.0"}
    )
    return build_housing_smoke(
        **tenant,
        landlord_model=controls["landlord_model"],
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
        reasoning_effort=controls["reasoning_effort"],
        inference_seed_base=controls["tenant_inference_seed_base"],
        openrouter_route=route,
        tenant_profile_id_override=spec["profile"] if live else "housing_price_scripted_tenant_v1",
        tenant_max_cost_usd_override=contract["tenant_cost_ceiling_usd_per_cell"] if live else None,
        # A model that accepts no temperature is declared so in its harness config;
        # the profile's own value is then a placeholder the request never sends.
        tenant_temperature=0.0 if (unavailable or not live) else controls["temperature"],
        tenant_harness_config=(
            {"sampling_controls": {"temperature": "unavailable"}} if unavailable and live else None
        ),
        tenant_top_p=controls["top_p"],
        max_output_tokens_override=controls["max_output_tokens"],
        timeout_seconds_override=controls["timeout_seconds"],
        max_action_attempts_override=controls["max_action_attempts"],
        retryable_conditions_override=controls["retryable_conditions"],
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


async def run(
    contract: Mapping[str, Any], run_root: Path, *, live: bool, provider: Any = None
) -> dict[str, Any]:
    """``provider`` replaces the paid client in live mode; a test passes a recording stub."""
    run_root.mkdir(parents=True, exist_ok=True)
    identity_path = run_root / "contract_sha256.txt"
    digest = hashlib.sha256(canonical_json_bytes(contract)).hexdigest()
    if identity_path.exists() and identity_path.read_text().strip() != digest:
        raise ValueError("run root belongs to a different price contract")
    identity_path.write_text(digest + "\n")
    setups = {arm: build_setup(contract, arm, live=live) for arm in contract["arms"]}
    if provider is None:
        provider = OpenRouterChatClient() if live else HousingScriptedTenantProvider()
    results_root = run_root / ("live" if live else "preflight")
    results_root.mkdir(exist_ok=True)
    rows: list[dict[str, Any]] = []
    halted = False
    replicates = int(contract["replicates"])
    for seed in contract["world_seeds"]:
        for arm in contract["arms"]:
            for replicate in range(replicates):
                setup = setups[arm]
                cell = next(
                    item for item in setup.plan.cells
                    if item.world_seed == seed and item.replicate_index == replicate
                )
                # One replicate keeps the original file names, so sealed v1 and v2 run roots read as before.
                tag = "" if replicates == 1 else f"__r{replicate}"
                result_path = results_root / f"world_{seed}__{arm}{tag}.json"
                if result_path.exists():
                    row = json.loads(result_path.read_text())
                    if row["status"] != "completed":
                        halted = True
                    rows.append(row)
                    continue
                if halted:
                    rows.append({"world_seed": seed, "arm": arm, "replicate_index": replicate, "status": "not_attempted", "cost_usd": 0.0})
                    continue
                spent = sum(float(row.get("cost_usd", 0.0)) for row in rows)
                if live and spent + contract["tenant_cost_ceiling_usd_per_cell"] > contract["total_cost_ceiling_usd"]:
                    halted = True
                    rows.append({"world_seed": seed, "arm": arm, "replicate_index": replicate, "status": "not_attempted_budget", "cost_usd": 0.0})
                    continue
                evidence_root = results_root / f"world_{seed}__{arm}{tag}_evidence"
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
                    row = {"world_seed": seed, "arm": arm, "replicate_index": replicate, "status": "completed",
                           "cost_usd": execution.total_cost_usd, "receipt_sha256": receipt.receipt_sha256,
                           "run_plan_id": setup.plan.run_plan_id, "cell_id": cell.cell_id,
                           "tenant_net_total": execution.episode_result.outcome["tenant_net_total"],
                           "price_rows": price_rows(execution.episode_result.outcome, seed, arm),
                           # What the ex-ante endpoint scores from (price_endpoint.py).
                           "outcome_facts": {
                               key: execution.episode_result.outcome[key] for key in OUTCOME_FACTS
                           }}
                except Exception as error:
                    failure_receipt = None
                    try:
                        failure_receipt = finalize_housing_failure(
                            setup=setup, cell_id=cell.cell_id, evidence_root=evidence_root, error=error
                        )
                    except Exception:
                        pass
                    usage = _failure_usage(evidence_root=evidence_root, run_plan_id=setup.plan.run_plan_id, cell_id=cell.cell_id)
                    row = {"world_seed": seed, "arm": arm, "replicate_index": replicate, "status": "operational_failure",
                           "failure_condition": getattr(error, "condition", type(error).__name__),
                           "cost_usd": usage["cost_usd"],
                           "receipt_sha256": failure_receipt.receipt_sha256 if failure_receipt else None}
                    halted = True
                if live and (not math.isfinite(float(row["cost_usd"])) or float(row["cost_usd"]) > contract["tenant_cost_ceiling_usd_per_cell"]):
                    halted = True
                result_path.write_bytes(canonical_json_bytes(row) + b"\n")
                rows.append(row)
                print(json.dumps({k: row[k] for k in ("world_seed", "arm", "status", "cost_usd")}), flush=True)
    summary = summarize(rows, len(contract["world_seeds"]) * len(contract["arms"]) * replicates)
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
