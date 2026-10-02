"""Bounded paired Housing price pilot; preflight is provider-free.

Live mode is explicit and writes one immutable result per planned cell. A failed
cell remains missing, and any operational failure stops this small pilot.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import OpenRouterChatClient, ProviderFailure, execute_plan_cell
from aeread.shared_runner.task.receipts import verify_evaluation_receipt

from . import lemons, price_outside_demand
from .population_campaign import _failure_usage
from .runner import (
    GEMINI_38_FLASH_MODEL,
    GLM_53_FLASH_MODEL,
    GLM_53_FLASH_REVISION,
    GOOGLE_AI_STUDIO_GEMINI_38_FLASH_ROUTE,
    PARASAIL_GLM_53_FLASH_ROUTE,
    HousingScriptedLandlordProvider,
    OpenRouterRoutePin,
    SCRIPTED_TENANT_REVISION,
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

# Gemini 3.1 Flash Lite on Google, the rival seats of the v5 identities. The catalog
# lists Google's global route at $0.25/$1.50 per million and cheaper flex tiers, so the
# route price ceiling also admits those and a priced cost is an upper bound. Unlike
# Luna it accepts temperature, so rivals are pinned to 0.
GEMINI_31_FLASH_LITE_MODEL = "google/gemini-3.1-flash-lite"
GOOGLE_GEMINI_31_FLASH_LITE_ROUTE = OpenRouterRoutePin(
    provider="Google",
    quantization="unknown",
    canonical_model="google/gemini-3.1-flash-lite-20260507",
    input_per_million=0.25,
    cached_input_per_million=0.025,
    output_per_million=1.5,
    pricing_id="openrouter_google_2026-10-01_gemini-3.1-flash-lite",
)

# DeepSeek V4 Flash 0731 on DeepInfra, read from the catalog on 2026-10-01. The runner's
# own DeepInfra pin for this model carries the 2026-08-26 prices ($0.08 in); the endpoint
# is $0.06 now, and a pin is also the price a call is costed at, so this one is current.
DEEPSEEK_V4_FLASH_0731_MODEL = "deepseek/deepseek-v4-flash-0731"
DEEPINFRA_DEEPSEEK_V4_FLASH_0731_ROUTE = OpenRouterRoutePin(
    provider="DeepInfra",
    quantization="fp8",
    canonical_model="deepseek/deepseek-v4-flash-20260731",
    input_per_million=0.06,
    cached_input_per_million=0.015,
    output_per_million=0.18,
    pricing_id="openrouter_deepinfra_2026-10-01_deepseek-v4-flash-0731",
)

#: Sealed routes this driver knows. A contract names one; the driver refuses a
#: route whose identity drifts from the pin the runner carries.
ROUTES: dict[str, tuple[str, Any]] = {
    "google_gemini_38_flash": (GEMINI_38_FLASH_MODEL, GOOGLE_AI_STUDIO_GEMINI_38_FLASH_ROUTE),
    "deepinfra_glm_53_flash_fp4": (GLM_53_FLASH_MODEL, DEEPINFRA_GLM_53_FLASH_FP4_ROUTE),
    "openai_gpt_56_luna": (GPT_56_LUNA_MODEL, OPENAI_GPT_56_LUNA_ROUTE),
    "parasail_glm_53_flash": (GLM_53_FLASH_MODEL, PARASAIL_GLM_53_FLASH_ROUTE),
    "google_gemini_31_flash_lite": (GEMINI_31_FLASH_LITE_MODEL, GOOGLE_GEMINI_31_FLASH_LITE_ROUTE),
    "deepinfra_deepseek_v4_flash_0731": (DEEPSEEK_V4_FLASH_0731_MODEL, DEEPINFRA_DEEPSEEK_V4_FLASH_0731_ROUTE),
}

#: Seats the rival model plays in a focal-seat identity. Seat 0 is the focal model.
RIVAL_SEATS = (1, 2, 3, 4, 5)
#: Declared in the contract's rival block: a limit that can end a run is a control.
RIVAL_RATE_LIMIT_RETRIES = 5
RIVAL_BACKOFF_SECONDS = 3.0
FOCAL_SEAT = 0

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
    # 60 worlds at K=1 (owner decision 2026-10-01). Sized from the pooled K=3 variance
    # components of the two models on the four-world pilots: to detect a $150 arm contrast
    # at 80% power the panel needs ~57 worlds for GLM and ~81 for Luna's realized contrast
    # (~38 for Luna's reply-conditioned one). Seeds 100000-100059 rerun the original four.
    "housing_lemons_price_pilot_v4_glm53_flash_parasail_w60": {
        "route_id": "parasail_glm_53_flash", "profile": "housing_price_glm53_parasail_tenant_v4",
        "reasoning_effort": "low", "temperature": 1.0, "top_p": 1.0, "total_cost_ceiling_usd": 1.5,
        "world_seeds": list(range(100000, 100060)),
    },
    "housing_lemons_price_pilot_v4_gpt56_luna_w60": {
        "route_id": "openai_gpt_56_luna", "profile": "housing_price_gpt56_luna_tenant_v4",
        "reasoning_effort": "low", "temperature": "unavailable", "top_p": None,
        "total_cost_ceiling_usd": 3.0, "world_seeds": list(range(100000, 100060)),
    },
    # Focal-seat pilots (owner decision 2026-10-01): seat 0 is the model under test and
    # seats 1-5 are Gemini 3.1 Flash Lite at temperature 0, so the market the focal seat
    # meets is the same cheap, near-deterministic population in every world. The router
    # that splits the seats is a provider-level wrapper, not a runner profile (see
    # SeatRouterClient), so the plan still names one tenant profile.
    "housing_lemons_price_pilot_v5_glm53_flash_rivals_g31lite": {
        "route_id": "parasail_glm_53_flash", "profile": "housing_price_glm53_parasail_tenant_v5",
        "reasoning_effort": "low", "temperature": 1.0, "top_p": 1.0, "total_cost_ceiling_usd": 0.6,
        "world_seeds": list(range(100000, 100008)), "rival_route_id": "google_gemini_31_flash_lite",
    },
    # v5 above stopped at its second world: Google's shared pool answered 429 past the kernel's
    # four attempts (HL-O-11). v6 declares the router's backoff and runs the full panel; v5's
    # run root stays as the record and its failed cell is not rerun.
    "housing_lemons_price_pilot_v6_glm53_flash_rivals_g31lite_w60": {
        "route_id": "parasail_glm_53_flash", "profile": "housing_price_glm53_parasail_tenant_v6",
        "reasoning_effort": "low", "temperature": 1.0, "top_p": 1.0, "total_cost_ceiling_usd": 3.0,
        "world_seeds": list(range(100000, 100060)), "rival_route_id": "google_gemini_31_flash_lite",
    },
    # Scripted rivals (owner decision 2026-10-01): the primary focal-seat comparison. Seats 1-5
    # play a fixed rule, so the focal model meets the same market in every world and a gap
    # between focal models is not partly the rivals' quirk. Two rules bracket it: inspect_then_sign
    # (the careful reference) and sign_anything (the naive one).
    "housing_lemons_price_pilot_v7_glm53_flash_rivals_inspect_w60": {
        "route_id": "parasail_glm_53_flash", "profile": "housing_price_glm53_parasail_tenant_v7a",
        "reasoning_effort": "low", "temperature": 1.0, "top_p": 1.0, "total_cost_ceiling_usd": 1.0,
        "world_seeds": list(range(100000, 100060)),
        "rival_scripted_model": "housing_scripted_tenant_inspect_then_sign_v1",
    },
    "housing_lemons_price_pilot_v7_glm53_flash_rivals_signany_w60": {
        "route_id": "parasail_glm_53_flash", "profile": "housing_price_glm53_parasail_tenant_v7b",
        "reasoning_effort": "low", "temperature": 1.0, "top_p": 1.0, "total_cost_ceiling_usd": 1.0,
        "world_seeds": list(range(100000, 100060)),
        "rival_scripted_model": "housing_scripted_tenant_sign_anything_v1",
    },
    # Luna as the focal seat against the same three rival populations as GLM (v6 / v7). Luna
    # accepts no temperature, so its replicates differ only through the request seed.
    "housing_lemons_price_pilot_v6_gpt56_luna_rivals_g31lite_w60": {
        "route_id": "openai_gpt_56_luna", "profile": "housing_price_gpt56_luna_tenant_v6",
        "reasoning_effort": "low", "temperature": "unavailable", "top_p": None, "total_cost_ceiling_usd": 4.0,
        "world_seeds": list(range(100000, 100060)), "rival_route_id": "google_gemini_31_flash_lite",
    },
    "housing_lemons_price_pilot_v7_gpt56_luna_rivals_inspect_w60": {
        "route_id": "openai_gpt_56_luna", "profile": "housing_price_gpt56_luna_tenant_v7a",
        "reasoning_effort": "low", "temperature": "unavailable", "top_p": None, "total_cost_ceiling_usd": 2.0,
        "world_seeds": list(range(100000, 100060)),
        "rival_scripted_model": "housing_scripted_tenant_inspect_then_sign_v1",
    },
    "housing_lemons_price_pilot_v7_gpt56_luna_rivals_signany_w60": {
        "route_id": "openai_gpt_56_luna", "profile": "housing_price_gpt56_luna_tenant_v7b",
        "reasoning_effort": "low", "temperature": "unavailable", "top_p": None, "total_cost_ceiling_usd": 2.0,
        "world_seeds": list(range(100000, 100060)),
        "rival_scripted_model": "housing_scripted_tenant_sign_anything_v1",
    },
    # One deciding tenant, four landlords (owner decision 2026-10-01). The six-tenant panels
    # measured mostly who won a contested listing: with six copies the opening round differed
    # between the two arms in 48 of 57 worlds, and scripted rivals shut seat 0 out of sound
    # listings with a one-dollar overbid. Here seats 1-5 are outside demand (see
    # price_outside_demand): each open listing seat 0 did not bid on is taken at the end of a
    # round with probability 0.5, sound or lemon alike, on a schedule the world fixes. Same 60
    # worlds, so asks, lemons and seat 0's values are those of the v4-v7 panels.
    "housing_lemons_price_pilot_v8_glm53_flash_deepinfra_outside_w60": {
        "route_id": "deepinfra_glm_53_flash_fp4", "profile": "housing_price_glm53_deepinfra_tenant_v8",
        "reasoning_effort": "low", "temperature": 1.0, "top_p": 1.0, "total_cost_ceiling_usd": 1.0,
        "world_seeds": list(range(100000, 100060)), "outside_demand": True,
    },
    "housing_lemons_price_pilot_v8_deepseek_v4_flash_deepinfra_outside_w60": {
        "route_id": "deepinfra_deepseek_v4_flash_0731",
        "profile": "housing_price_deepseek_v4_flash_deepinfra_tenant_v8",
        "reasoning_effort": "low", "temperature": 1.0, "top_p": 1.0, "total_cost_ceiling_usd": 1.0,
        "world_seeds": list(range(100000, 100060)), "outside_demand": True,
    },
    # v8 above stopped at its first cell on both models (HL-O-15): DeepInfra's shared pool
    # answered 429 engine_overloaded past the kernel's four attempts (about 16 s of backoff),
    # and one DeepSeek call ran 116 s before the next hit the 120 s timeout. v9 keeps the
    # market, the notice, the routes and the sampling, and declares the two limits that ended
    # those cells: eight attempts (the kernel's exponential backoff then waits about two
    # minutes in total) and a 300 s call timeout. v8's run roots stay as the record.
    "housing_lemons_price_pilot_v9_glm53_flash_deepinfra_outside_w60": {
        "route_id": "deepinfra_glm_53_flash_fp4", "profile": "housing_price_glm53_deepinfra_tenant_v9",
        "reasoning_effort": "low", "temperature": 1.0, "top_p": 1.0, "total_cost_ceiling_usd": 1.0,
        "world_seeds": list(range(100000, 100060)), "outside_demand": True,
        "max_action_attempts": 8, "timeout_seconds": 300.0,
    },
    "housing_lemons_price_pilot_v9_deepseek_v4_flash_deepinfra_outside_w60": {
        "route_id": "deepinfra_deepseek_v4_flash_0731",
        "profile": "housing_price_deepseek_v4_flash_deepinfra_tenant_v9",
        "reasoning_effort": "low", "temperature": 1.0, "top_p": 1.0, "total_cost_ceiling_usd": 1.0,
        "world_seeds": list(range(100000, 100060)), "outside_demand": True,
        "max_action_attempts": 8, "timeout_seconds": 300.0,
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


def _rival_block(spec: Mapping[str, Any]) -> dict[str, Any]:
    """What the contract must declare about the rival seats of a focal-seat identity."""
    if spec.get("outside_demand"):
        return price_outside_demand.block()
    seats = {"seats": list(RIVAL_SEATS), "focal_seat": FOCAL_SEAT}
    if spec.get("rival_scripted_model"):
        return {"kind": "scripted_tenant", "model": spec["rival_scripted_model"],
                "revision": SCRIPTED_TENANT_REVISION, **seats}
    return {
        "route": _route_block(spec["rival_route_id"]), **seats,
        "temperature": 0.0, "top_p": 1.0, "reasoning_effort": "low",
        "rate_limit_retries": RIVAL_RATE_LIMIT_RETRIES, "backoff_seconds": RIVAL_BACKOFF_SECONDS,
    }


def has_rivals(spec: Mapping[str, Any]) -> bool:
    return bool(
        spec.get("rival_route_id") or spec.get("rival_scripted_model") or spec.get("outside_demand")
    )


def identity(contract: Mapping[str, Any]) -> dict[str, Any]:
    spec = IDENTITIES.get(contract.get("campaign_id"))
    if spec is None:
        raise ValueError("price pilot identity drifted")
    return spec


def load_contract(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    spec = identity(value)
    expected = {
        "schema_version", "campaign_id", "claim_status", "route", "world_seeds",
        "arms", "replicates", "rounds", "tenant_cost_ceiling_usd_per_cell",
        "total_cost_ceiling_usd", "max_consecutive_operational_failures", "controls", "analysis",
    }
    if has_rivals(spec):
        expected = expected | {"rivals"}
        if value.get("rivals") != _rival_block(spec):
            raise ValueError("price pilot rival seats drifted")
    if set(value) != expected:
        raise ValueError("price pilot contract fields drifted")
    if value["schema_version"] != "aeread.housing_price_pilot/1":
        raise ValueError("price pilot identity drifted")
    if value["claim_status"] != "development_pilot" or value["route"] != _route_block(spec["route_id"]):
        raise ValueError("price pilot claim or route drifted")
    if value["world_seeds"] != spec.get("world_seeds", [100000, 100001, 100002, 100003]):
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
        "max_output_tokens": 4096, "timeout_seconds": spec.get("timeout_seconds", 120.0),
        "sdk_retries": 0, "max_action_attempts": spec.get("max_action_attempts", 4),
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


class SeatRouterClient:
    """Sends the rival seats' calls to another player and the focal seat's to the plan's own.

    The plan names one tenant profile, so every request arrives addressed to the focal model.
    This wrapper reads the seat out of the request and, for a rival seat, rewrites the request
    (``rewrite``) and sends it to the rival client: another model on its own route, or the
    scripted tenant provider. The kernel then records the rival's own ``requested_model`` and
    ``resolved_model`` from the result, but the ``provider_call_started`` event keeps the request
    as the plan built it, so each call is also logged to ``seat_calls.jsonl`` under the run root
    with the player that actually answered. A plan-level seat profile would remove the
    discrepancy but edits runner.py, which moves the run-plan id of every sealed Housing
    identity (HL-T-04).
    """

    def __init__(self, focal: Any, rival: Any, *, rival_block: Mapping[str, Any], rewrite: Any, log_path: Path,
                 focal_rewrite: Any = None):
        self._focal, self._rival, self._log = focal, rival, log_path
        self._block, self._rewrite = rival_block, rewrite
        self._seats = set(rival_block["seats"])
        # Outside-demand identities tell the focal seat the departure rule here (see
        # price_outside_demand): the request the kernel logged does not carry the notice.
        self._focal_rewrite = focal_rewrite

    @staticmethod
    def seat_of(request: Any) -> int:
        body = json.loads(request.input_text)
        return int(body["observation"]["tenant_id"])

    async def complete(self, request: Any) -> Any:
        seat = self.seat_of(request)
        rival = seat in self._seats
        if rival:
            sent = self._rewrite(request)
        else:
            sent = self._focal_rewrite(request) if self._focal_rewrite is not None else request
        client = self._rival if rival else self._focal
        # Google's shared upstream pool answers 429 in bursts that outlast the kernel's four
        # immediate attempts (HL-O-11), and one failed cell halts the pilot. A rival call backs
        # off and retries here; the focal seat is never retried, so its failures stay typed.
        retries = int(self._block.get("rate_limit_retries", 0))
        for attempt in range(retries + 1):
            try:
                result = await client.complete(sent)
                break
            except ProviderFailure as failure:
                if not rival or failure.condition != "rate_limit" or attempt == retries:
                    raise
                await asyncio.sleep(float(self._block["backoff_seconds"]) * 2 ** attempt)
        with self._log.open("a") as handle:
            handle.write(json.dumps({
                "provider_call_id": request.provider_call_id, "seat": seat, "role": "rival" if rival else "focal",
                "requested_model": result.requested_model, "resolved_model": result.resolved_model,
                "temperature": sent.temperature, "cost_usd": result.cost_usd,
                **({"instructions_sha256": price_outside_demand.instructions_sha256(sent)}
                   if self._focal_rewrite is not None and not rival else {}),
            }, sort_keys=True) + "\n")
        return result


def llm_rival_rewrite(model: str, route: Any, block: Mapping[str, Any]) -> Any:
    def rewrite(request: Any) -> Any:
        meta = dict(request.provider_metadata or {})
        meta.update({
            "canonical_model": route.canonical_model, "route_provider": route.provider,
            "quantization": route.quantization,
            "max_prompt_price_per_million": str(route.input_per_million),
            "max_completion_price_per_million": str(route.output_per_million),
        })
        return dataclasses.replace(
            request, model=model, revision=route.canonical_model, provider_metadata=meta,
            temperature=block["temperature"], top_p=block["top_p"],
        )
    return rewrite


def scripted_rival_rewrite(block: Mapping[str, Any]) -> Any:
    def rewrite(request: Any) -> Any:
        return dataclasses.replace(
            request, provider="housing_scripted_tenant", model=block["model"], revision=block["revision"],
        )
    return rewrite


def make_seat_router(spec: Mapping[str, Any], contract: Mapping[str, Any], focal: Any, log_path: Path) -> SeatRouterClient:
    block = contract["rivals"]
    if block.get("kind") == "outside_demand":
        return SeatRouterClient(
            focal, price_outside_demand.OutsideDemandProvider(), rival_block=block,
            rewrite=price_outside_demand.rival_rewrite, log_path=log_path,
            focal_rewrite=price_outside_demand.focal_rewrite,
        )
    if block.get("kind") == "scripted_tenant":
        return SeatRouterClient(
            focal, HousingScriptedTenantProvider(), rival_block=block,
            rewrite=scripted_rival_rewrite(block), log_path=log_path,
        )
    model, route = ROUTES[spec["rival_route_id"]]
    return SeatRouterClient(
        focal, focal, rival_block=block, rewrite=llm_rival_rewrite(model, route, block), log_path=log_path,
    )


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
    contract: Mapping[str, Any], run_root: Path, *, live: bool, provider: Any = None,
    only_worlds: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """``provider`` replaces the paid client in live mode; a test passes a recording stub.

    ``only_worlds=(first, stop)`` restricts this process to the declared worlds whose seed is in
    ``[first, stop)``, so several workers can share one run root: a cell is a pure function of the
    contract, each worker writes only its own cells' result files, and any process skips a cell
    that already has one. Execution parallelism is not a control of the experiment, so it is not
    in the contract; a worker writes ``summary_<first>_<stop>.json`` and never ``summary.json``,
    which only a process that covered the whole panel writes.
    """
    run_root.mkdir(parents=True, exist_ok=True)
    identity_path = run_root / "contract_sha256.txt"
    digest = hashlib.sha256(canonical_json_bytes(contract)).hexdigest()
    if identity_path.exists() and identity_path.read_text().strip() != digest:
        raise ValueError("run root belongs to a different price contract")
    identity_path.write_text(digest + "\n")
    setups = {arm: build_setup(contract, arm, live=live) for arm in contract["arms"]}
    if provider is None:
        provider = OpenRouterChatClient() if live else HousingScriptedTenantProvider()
    spec = identity(contract)
    # Outside demand is part of the market, so the provider-free preflight plays it too.
    if has_rivals(spec) and (live or spec.get("outside_demand")):
        provider = make_seat_router(spec, contract, provider, run_root / "seat_calls.jsonl")
    results_root = run_root / ("live" if live else "preflight")
    results_root.mkdir(exist_ok=True)
    rows: list[dict[str, Any]] = []
    halted = False
    replicates = int(contract["replicates"])
    seeds = [
        seed for seed in contract["world_seeds"]
        if only_worlds is None or only_worlds[0] <= seed < only_worlds[1]
    ]
    for seed in seeds:
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
    summary = summarize(rows, len(seeds) * len(contract["arms"]) * replicates)
    name = "summary.json" if only_worlds is None else f"summary_{only_worlds[0]}_{only_worlds[1]}.json"
    (results_root / name).write_bytes(canonical_json_bytes(summary) + b"\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--live", action="store_true", help="make paid OpenRouter tenant calls")
    parser.add_argument("--only-worlds", metavar="FIRST:STOP", help="run only declared seeds in [FIRST, STOP)")
    args = parser.parse_args()
    contract = load_contract(args.contract)
    only = tuple(int(part) for part in args.only_worlds.split(":")) if args.only_worlds else None
    print(json.dumps(asyncio.run(run(contract, args.run_root, live=args.live, only_worlds=only)), sort_keys=True))


if __name__ == "__main__":
    main()
