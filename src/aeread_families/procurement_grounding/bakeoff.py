"""Cost-capped OpenRouter bake-off for the frozen procurement-grounding case."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import statistics
import time
import urllib.parse
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from aeread.shared_runner.task.execution import (
    OpenRouterChatClient,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
    TokenPricing,
    execute_plan_cell,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes

from .runner import OpenRouterRoute, build_openrouter_setup


CATALOG_RETRIEVED_AT = "2026-08-31"
CATALOG_SOURCE = "https://openrouter.ai/api/v1/models"


@dataclass(frozen=True, slots=True)
class BakeoffCandidate:
    candidate_id: str
    route: OpenRouterRoute
    lane: str
    access_class: str
    license_id: str | None
    model_card_url: str | None
    timeout_seconds: float = 180.0


def _candidate(
    candidate_id: str,
    *,
    model: str,
    revision: str,
    route_provider: str,
    quantization: str,
    input_per_million: float,
    cached_input_per_million: float,
    output_per_million: float,
    max_prompt_price_per_million: float | None = None,
    max_completion_price_per_million: float | None = None,
    lane: str = "standard",
    access_class: str = "hosted_proprietary",
    license_id: str | None = None,
    model_card_url: str | None = None,
    reasoning_effort: str | None = "low",
    temperature_supported: bool = True,
    timeout_seconds: float = 180.0,
    catalog_retrieved_at: str = CATALOG_RETRIEVED_AT,
) -> BakeoffCandidate:
    pricing_id = (
        f"openrouter_{catalog_retrieved_at}_{candidate_id}_"
        f"{route_provider.lower().replace(' ', '_')}"
    )
    route = OpenRouterRoute(
        profile_id=f"procurement_{candidate_id}_v1",
        model=model,
        revision=revision,
        route_provider=route_provider,
        quantization=quantization,
        pricing=TokenPricing(
            input_per_million=input_per_million,
            cached_input_per_million=cached_input_per_million,
            output_per_million=output_per_million,
            pricing_id=pricing_id,
        ),
        max_prompt_price_per_million=str(
            max_prompt_price_per_million or input_per_million
        ),
        max_completion_price_per_million=str(
            max_completion_price_per_million or output_per_million
        ),
        reasoning_effort=reasoning_effort,
        temperature_supported=temperature_supported,
    )
    return BakeoffCandidate(
        candidate_id=candidate_id,
        route=route,
        lane=lane,
        access_class=access_class,
        license_id=license_id,
        model_card_url=model_card_url,
        timeout_seconds=timeout_seconds,
    )


DEFAULT_CANDIDATES = (
    _candidate(
        "gpt56_luna",
        model="openai/gpt-5.6-luna",
        revision="openai/gpt-5.6-luna-20260709",
        route_provider="OpenAI",
        quantization="unknown",
        input_per_million=0.20,
        cached_input_per_million=0.02,
        output_per_million=1.20,
        temperature_supported=False,
    ),
    _candidate(
        "gemini37_flash",
        model="google/gemini-3.7-flash",
        revision="google/gemini-3.7-flash-20260813",
        route_provider="Google AI Studio",
        quantization="unknown",
        input_per_million=0.75,
        cached_input_per_million=0.075,
        output_per_million=3.75,
    ),
    _candidate(
        "gpt54_mini",
        model="openai/gpt-5.4-mini",
        revision="openai/gpt-5.4-mini-20260317",
        route_provider="OpenAI",
        quantization="unknown",
        input_per_million=0.75,
        cached_input_per_million=0.075,
        output_per_million=4.50,
        temperature_supported=False,
    ),
    _candidate(
        "gemini37_flash_batch",
        model="google/gemini-3.7-flash:batch",
        revision="google/gemini-3.7-flash-20260813:batch",
        route_provider="Google",
        quantization="unknown",
        input_per_million=0.1875,
        cached_input_per_million=0.01875,
        output_per_million=0.9375,
        lane="batch_variant",
        temperature_supported=False,
        timeout_seconds=1800.0,
    ),
)


OPEN_WEIGHT_CANDIDATES = (
    _candidate(
        "glm53_flash",
        model="z-ai/glm-5.3-flash",
        revision="z-ai/glm-5.3-flash-20260826",
        route_provider="DeepInfra",
        quantization="fp8",
        input_per_million=0.075,
        cached_input_per_million=0.015,
        output_per_million=0.25,
        access_class="open_source",
        license_id="MIT",
        model_card_url="https://huggingface.co/zai-org/GLM-5.3-Flash",
    ),
    _candidate(
        "mistral_small4",
        model="mistralai/mistral-small-2603",
        revision="mistralai/mistral-small-2603",
        route_provider="Mistral",
        quantization="unknown",
        input_per_million=0.15,
        cached_input_per_million=0.015,
        output_per_million=0.60,
        access_class="open_source",
        license_id="Apache-2.0",
        model_card_url=(
            "https://huggingface.co/mistralai/Mistral-Small-4-119B-2603"
        ),
    ),
    _candidate(
        "qwen3_30b_a3b_instruct_2507_coreweave",
        model="qwen/qwen3-30b-a3b-instruct-2507",
        revision="qwen/qwen3-30b-a3b-instruct-2507",
        route_provider="CoreWeave",
        quantization="bf16",
        input_per_million=0.10,
        cached_input_per_million=0.10,
        output_per_million=0.30,
        access_class="open_source",
        license_id="Apache-2.0",
        model_card_url=(
            "https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507"
        ),
        reasoning_effort=None,
        catalog_retrieved_at="2026-09-03",
    ),
    _candidate(
        "qwen3_235b_a22b_instruct_2507_atlascloud",
        model="qwen/qwen3-235b-a22b-2507",
        revision="qwen/qwen3-235b-a22b-07-25",
        route_provider="AtlasCloud",
        quantization="fp8",
        input_per_million=0.20,
        cached_input_per_million=0.20,
        output_per_million=0.88,
        access_class="open_source",
        license_id="Apache-2.0",
        model_card_url=(
            "https://huggingface.co/Qwen/Qwen3-235B-A22B-Instruct-2507"
        ),
        reasoning_effort=None,
        catalog_retrieved_at="2026-09-03",
    ),
    _candidate(
        "qwen38_flash",
        model="qwen/qwen3.8-flash",
        revision="qwen/qwen3.8-flash-20260826",
        route_provider="Alibaba",
        quantization="unknown",
        input_per_million=0.15,
        cached_input_per_million=0.016,
        output_per_million=0.47,
        access_class="open_weight_custom_license",
        license_id="custom",
        model_card_url="https://huggingface.co/Qwen/Qwen3.8-Flash-Next",
        reasoning_effort=None,
    ),
    _candidate(
        "minimax_m3",
        model="minimax/minimax-m3",
        revision="minimax/minimax-m3-20260531",
        route_provider="CoreWeave",
        quantization="fp4",
        input_per_million=0.23,
        cached_input_per_million=0.05,
        output_per_million=0.96,
        access_class="open_weight_custom_license",
        license_id="custom",
        model_card_url="https://huggingface.co/MiniMaxAI/MiniMax-M3",
        reasoning_effort=None,
    ),
)

ALL_CANDIDATES = DEFAULT_CANDIDATES + OPEN_WEIGHT_CANDIDATES


def selected_candidates(
    candidate_ids: Iterable[str] | None = None,
    *,
    include_batch: bool = True,
    open_weight_only: bool = False,
) -> tuple[BakeoffCandidate, ...]:
    requested = set(candidate_ids or ())
    available = {candidate.candidate_id for candidate in ALL_CANDIDATES}
    unknown = sorted(requested - available)
    if unknown:
        raise ValueError(f"unknown candidate ids: {unknown}")
    pool = OPEN_WEIGHT_CANDIDATES if open_weight_only else (
        ALL_CANDIDATES if requested else DEFAULT_CANDIDATES
    )
    if open_weight_only:
        open_weight_ids = {
            candidate.candidate_id for candidate in OPEN_WEIGHT_CANDIDATES
        }
        non_open_weight = sorted(requested - open_weight_ids)
        if non_open_weight:
            raise ValueError(
                f"candidate ids are not open-weight: {non_open_weight}"
            )
    selected = tuple(
        candidate
        for candidate in pool
        if (not requested or candidate.candidate_id in requested)
        and (include_batch or candidate.lane == "standard")
    )
    if not selected:
        raise ValueError("the candidate selection is empty")
    return selected


def conservative_cost_ceiling(
    candidates: Iterable[BakeoffCandidate],
    *,
    replicates: int,
    warmups: int,
    max_input_tokens: int = 4000,
    max_output_tokens: int = 2500,
) -> float:
    return sum(
        candidate.route.pricing.cost(
            input_tokens=max_input_tokens,
            cached_input_tokens=0,
            output_tokens=max_output_tokens,
        )
        * (replicates + (warmups if candidate.lane == "standard" else 0))
        for candidate in candidates
    )


def _endpoint_url(model: str) -> str:
    encoded = urllib.parse.quote(model, safe="/:")
    return f"https://openrouter.ai/api/v1/models/{encoded}/endpoints"


def _load_endpoint_catalog(model: str) -> Mapping[str, Any]:
    request = urllib.request.Request(
        _endpoint_url(model), headers={"User-Agent": "AERead procurement bakeoff/1.0"}
    )
    with urllib.request.urlopen(request, timeout=30.0) as response:
        payload = json.load(response)
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise RuntimeError(f"OpenRouter returned no endpoint data for {model}")
    return data


def preflight_candidate(candidate: BakeoffCandidate) -> dict[str, Any]:
    data = _load_endpoint_catalog(candidate.route.model)
    endpoints = data.get("endpoints")
    if not isinstance(endpoints, list):
        raise RuntimeError(f"OpenRouter returned no endpoints for {candidate.route.model}")
    identity_matches = []
    for endpoint in endpoints:
        if not isinstance(endpoint, Mapping):
            continue
        name = str(endpoint.get("name") or "")
        endpoint_pricing = endpoint.get("pricing")
        if not isinstance(endpoint_pricing, Mapping):
            continue
        if (
            endpoint.get("provider_name") == candidate.route.route_provider
            and endpoint.get("quantization") == candidate.route.quantization
            and name.endswith(candidate.route.revision)
        ):
            identity_matches.append(endpoint)
    matches = [
        endpoint
        for endpoint in identity_matches
        if float(endpoint["pricing"]["prompt"]) * 1_000_000
        <= candidate.route.pricing.input_per_million + 1e-12
        and float(endpoint["pricing"]["completion"]) * 1_000_000
        <= candidate.route.pricing.output_per_million + 1e-12
    ]
    if identity_matches and not matches:
        raise RuntimeError(f"prices rose above the pin for {candidate.candidate_id}")
    if not matches:
        raise RuntimeError(
            f"found no endpoint within the route pin for {candidate.candidate_id}"
        )
    required_parameters = {"max_tokens", "response_format", "seed", "structured_outputs"}
    if candidate.route.reasoning_effort is not None:
        required_parameters.add("reasoning_effort")
    eligible = [
        endpoint
        for endpoint in matches
        if required_parameters.issubset(
            set(endpoint.get("supported_parameters") or ())
        )
    ]
    if not eligible:
        raise RuntimeError(
            f"all pinned endpoints lost required parameters for {candidate.candidate_id}"
        )
    prices = [
        (
            float(endpoint["pricing"]["prompt"]) * 1_000_000,
            float(endpoint["pricing"]["completion"]) * 1_000_000,
        )
        for endpoint in eligible
    ]
    return {
        "candidate_id": candidate.candidate_id,
        "model": candidate.route.model,
        "revision": candidate.route.revision,
        "route_provider": candidate.route.route_provider,
        "quantization": candidate.route.quantization,
        "eligible_endpoint_count": len(eligible),
        "prompt_per_million_range": [
            min(price[0] for price in prices),
            max(price[0] for price in prices),
        ],
        "completion_per_million_range": [
            min(price[1] for price in prices),
            max(price[1] for price in prices),
        ],
        "supported_parameters_verified": sorted(required_parameters),
        "source": _endpoint_url(candidate.route.model),
    }


def _openrouter_json_request(
    url: str, *, method: str, payload: Mapping[str, Any] | None = None
) -> Mapping[str, Any]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    body = canonical_json_bytes(payload) if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "AERead procurement bakeoff/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60.0) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenRouter batch HTTP {error.code}: {detail}") from error
    if not isinstance(result, Mapping):
        raise RuntimeError("OpenRouter batch response was not an object")
    return result


class OpenRouterBatchClient:
    """Collect independent AERead calls into one OpenRouter Batch API job."""

    TERMINAL_STATUSES = {"completed", "failed", "cancelled", "expired"}

    def __init__(self, *, expected_requests: int, poll_interval_seconds: float = 5.0):
        if expected_requests < 1:
            raise ValueError("expected_requests must be positive")
        self.expected_requests = expected_requests
        self.poll_interval_seconds = poll_interval_seconds
        self._lock = asyncio.Lock()
        self._pending: list[tuple[ProviderRequest, asyncio.Future[ProviderResult]]] = []
        self._submitted = False

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ProviderResult] = loop.create_future()
        async with self._lock:
            if self._submitted:
                raise ProviderFailure(
                    "provider_contract",
                    "OpenRouter batch client accepts exactly one grouped submission",
                    retryable=False,
                )
            self._pending.append((request, future))
            if len(self._pending) == self.expected_requests:
                self._submitted = True
                asyncio.create_task(self._submit(tuple(self._pending)))
        return await future

    @staticmethod
    def _wire_body(request: ProviderRequest) -> dict[str, Any]:
        if not isinstance(request.output_schema, Mapping):
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter batch requires a structured output schema",
                retryable=False,
            )
        provider_preferences, _canonical_model, _route_provider = (
            OpenRouterChatClient._route_preferences(request)
        )
        body: dict[str, Any] = {
            "model": request.model.removesuffix(":batch"),
            "messages": [
                {"role": "system", "content": request.instructions},
                {"role": "user", "content": request.input_text},
            ],
            "seed": request.seed,
            "max_tokens": request.max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "aeread_action",
                    "strict": True,
                    "schema": _plain(request.output_schema),
                },
            },
            "tools": [],
            "stream": False,
            "provider": provider_preferences,
        }
        if request.reasoning_effort is not None:
            body["reasoning"] = {"effort": request.reasoning_effort}
        if request.reasoning_token_budget is not None:
            body.setdefault("reasoning", {})["max_tokens"] = (
                request.reasoning_token_budget
            )
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.top_p is not None:
            body["top_p"] = request.top_p
        return body

    async def _submit(
        self,
        pending: tuple[tuple[ProviderRequest, asyncio.Future[ProviderResult]], ...],
    ) -> None:
        try:
            base_model = pending[0][0].model.removesuffix(":batch")
            if any(
                request.model.removesuffix(":batch") != base_model
                for request, _future in pending
            ):
                raise RuntimeError("one OpenRouter batch cannot mix models")
            indexed_pending = tuple(
                (request, future, f"{request.provider_call_id}-{index}")
                for index, (request, future) in enumerate(pending)
            )
            payload = {
                "endpoint": "/v1/chat/completions",
                "model": base_model,
                "requests": [
                    {
                        "custom_id": custom_id,
                        "body": self._wire_body(request),
                    }
                    for request, _future, custom_id in indexed_pending
                ],
            }
            created = await asyncio.to_thread(
                _openrouter_json_request,
                "https://openrouter.ai/api/beta/batches",
                method="POST",
                payload=payload,
            )
            batch_id = created.get("id")
            if not isinstance(batch_id, str) or not batch_id:
                raise RuntimeError(f"OpenRouter did not return a batch id: {created}")
            # Newly created batch ids are briefly eventually consistent at the
            # read endpoint; polling immediately can return a transient 404.
            await asyncio.sleep(self.poll_interval_seconds)
            while True:
                try:
                    batch = await asyncio.to_thread(
                        _openrouter_json_request,
                        f"https://openrouter.ai/api/beta/batches/{batch_id}",
                        method="GET",
                    )
                except RuntimeError as error:
                    if "batch HTTP 404" not in str(error):
                        raise
                    await asyncio.sleep(self.poll_interval_seconds)
                    continue
                status = batch.get("status")
                if status in self.TERMINAL_STATUSES:
                    break
                await asyncio.sleep(self.poll_interval_seconds)
            if status != "completed":
                raise RuntimeError(f"OpenRouter batch {batch_id} ended with {status}")
            raw_results = batch.get("results")
            if not isinstance(raw_results, list):
                raise RuntimeError("completed OpenRouter batch omitted inline results")
            by_id = {
                item.get("custom_id"): item
                for item in raw_results
                if isinstance(item, Mapping) and isinstance(item.get("custom_id"), str)
            }
            if set(by_id) != {
                custom_id for _request, _future, custom_id in indexed_pending
            }:
                raise RuntimeError("OpenRouter batch result ids do not match submitted ids")
            for request, future, custom_id in indexed_pending:
                try:
                    result = self._provider_result(
                        request, by_id[custom_id], batch_id=batch_id
                    )
                except Exception as error:
                    future.set_exception(error)
                else:
                    future.set_result(result)
        except Exception as error:
            for _request, future in pending:
                if not future.done():
                    future.set_exception(
                        ProviderFailure(
                            "provider_rejected",
                            str(error),
                            retryable=False,
                        )
                    )

    @staticmethod
    def _provider_result(
        request: ProviderRequest, item: Mapping[str, Any], *, batch_id: str
    ) -> ProviderResult:
        item_error = item.get("error")
        if item_error:
            raise ProviderFailure(
                "provider_rejected", str(item_error), retryable=False
            )
        response = item.get("response")
        if isinstance(response, Mapping):
            status_code = response.get("status_code")
            if isinstance(status_code, int) and status_code >= 400:
                raise ProviderFailure(
                    "provider_5xx" if status_code >= 500 else "provider_rejected",
                    str(response.get("body") or response),
                    retryable=status_code >= 500,
                    status_code=status_code,
                )
            raw_response = response.get("body")
        else:
            raw_response = item.get("body") or item.get("result")
        if not isinstance(raw_response, Mapping):
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter batch item omitted a response body",
                retryable=False,
            )
        raw_response = dict(raw_response)
        raw_response["openrouter_batch_id"] = batch_id
        _raw, choice, message = OpenRouterChatClient._parsed_choice(
            type(
                "BatchResponse",
                (),
                {"model_dump": lambda self, mode: raw_response},
            )()
        )
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str):
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter batch choice has no text content",
                retryable=False,
            )
        try:
            structured_output = json.loads(content)
        except json.JSONDecodeError as error:
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter batch structured output is not valid JSON",
                retryable=False,
            ) from error
        usage = raw_response.get("usage")
        if not isinstance(usage, Mapping):
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter batch response omitted token usage",
                retryable=False,
            )
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        input_details = usage.get("prompt_tokens_details")
        cached_input_tokens = (
            int(input_details.get("cached_tokens") or 0)
            if isinstance(input_details, Mapping)
            else 0
        )
        reported_cost = usage.get("cost")
        cost = (
            float(reported_cost)
            if isinstance(reported_cost, (int, float))
            and not isinstance(reported_cost, bool)
            and reported_cost >= 0
            else None
        )
        expected_provider = request.provider_metadata["route_provider"]
        actual_provider = raw_response.get("provider")
        if actual_provider is not None and actual_provider != expected_provider:
            raise ProviderFailure(
                "provider_contract",
                f"OpenRouter batch selected provider {actual_provider!r}, not {expected_provider!r}",
                retryable=False,
            )
        base_model = request.model.removesuffix(":batch")
        response_model = raw_response.get("model")
        if response_model not in {
            base_model,
            request.model,
            request.revision,
            request.revision.removesuffix(":batch"),
        }:
            raise ProviderFailure(
                "provider_contract",
                f"OpenRouter batch response model {response_model!r} was not requested",
                retryable=False,
            )
        return ProviderResult(
            response_id=str(raw_response.get("id") or ""),
            requested_model=request.model,
            resolved_model=request.revision,
            output_text=canonical_json_bytes(structured_output).decode("utf-8"),
            finish_reason=str(choice.get("finish_reason") or "unknown"),
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            raw_response=raw_response,
        )


def _plain(value: Any) -> Any:
    return json.loads(canonical_json_bytes(value))


async def _run_one(
    candidate: BakeoffCandidate,
    *,
    client: Any,
    evidence_root: Path,
    seed: int,
    warmup: bool,
    max_output_tokens: int,
    max_input_tokens: int,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    per_call_ceiling = candidate.route.pricing.cost(
        input_tokens=max_input_tokens,
        cached_input_tokens=0,
        output_tokens=max_output_tokens,
    )
    setup = build_openrouter_setup(
        candidate.route,
        seed=seed,
        max_output_tokens=max_output_tokens,
        timeout_seconds=candidate.timeout_seconds,
        max_cost_usd=max(per_call_ceiling * 1.05, 0.001),
    )
    started = time.perf_counter()
    try:
        async with semaphore:
            execution = await execute_plan_cell(
                plan=setup.plan,
                cell_id=setup.plan.cells[0].cell_id,
                registry=setup.registry,
                evidence_root=evidence_root,
                prompt_sources=setup.prompt_sources,
                providers={"openrouter": client},
                pricing=setup.pricing,
            )
        elapsed = time.perf_counter() - started
        provider_call = execution.action_executions[0].attempts[0].provider_calls[0]
        outcome = _plain(execution.episode_result.outcome)
        execution.evidence.audit_reconciliation()
        return {
            "candidate_id": candidate.candidate_id,
            "lane": candidate.lane,
            "seed": seed,
            "warmup": warmup,
            "status": "completed",
            "elapsed_seconds": elapsed,
            "valid": bool(outcome.get("valid")),
            "score": float(outcome.get("score", 0.0)),
            "quality_band": outcome.get("quality_band"),
            "breakdown": outcome.get("breakdown"),
            "mismatched_fields": outcome.get("mismatched_fields"),
            "input_tokens": provider_call.input_tokens,
            "cached_input_tokens": provider_call.cached_input_tokens,
            "output_tokens": provider_call.output_tokens,
            "cost_usd": execution.total_cost_usd,
            "cost_source": (
                "sealed_token_price_estimate"
                if candidate.lane == "batch_variant"
                else "openrouter_reported"
            ),
            "resolved_model": provider_call.resolved_model,
            "finish_reason": provider_call.finish_reason,
            "evidence_dir": str(execution.evidence.root),
        }
    except Exception as error:
        return {
            "candidate_id": candidate.candidate_id,
            "lane": candidate.lane,
            "seed": seed,
            "warmup": warmup,
            "status": "failed",
            "elapsed_seconds": time.perf_counter() - started,
            "error_type": type(error).__name__,
            "error": str(error),
            "cost_usd": 0.0,
        }


def _percentile_95(values: list[float]) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=20, method="inclusive")[18]


def summarize_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    measured = [row for row in rows if not row.get("warmup")]
    summaries: list[dict[str, Any]] = []
    for candidate in ALL_CANDIDATES:
        candidate_rows = [
            row for row in measured if row.get("candidate_id") == candidate.candidate_id
        ]
        if not candidate_rows:
            continue
        completed = [row for row in candidate_rows if row.get("status") == "completed"]
        elapsed = [float(row["elapsed_seconds"]) for row in completed]
        costs = [float(row["cost_usd"]) for row in completed]
        scores = [float(row["score"]) for row in completed]
        input_tokens = sum(int(row["input_tokens"]) for row in completed)
        cached_tokens = sum(int(row["cached_input_tokens"]) for row in completed)
        strong = [row for row in completed if float(row["score"]) >= 0.90]
        summary = {
            "candidate_id": candidate.candidate_id,
            "lane": candidate.lane,
            "requested_runs": len(candidate_rows),
            "completed_runs": len(completed),
            "failure_count": len(candidate_rows) - len(completed),
            "valid_rate": (
                sum(bool(row["valid"]) for row in completed) / len(completed)
                if completed
                else 0.0
            ),
            "mean_score": statistics.fmean(scores) if scores else 0.0,
            "minimum_score": min(scores) if scores else 0.0,
            "median_latency_seconds": statistics.median(elapsed) if elapsed else None,
            "p95_latency_seconds": _percentile_95(elapsed) if elapsed else None,
            "median_cost_usd": statistics.median(costs) if costs else None,
            "total_cost_usd": sum(costs),
            "cost_per_90_plus_run_usd": (
                sum(costs) / len(strong) if strong else None
            ),
            "provider_prompt_cache_rate": (
                cached_tokens / input_tokens if input_tokens else 0.0
            ),
        }
        summary["quality_qualified"] = (
            summary["failure_count"] == 0
            and summary["valid_rate"] == 1.0
            and summary["minimum_score"] >= 0.90
        )
        summaries.append(summary)

    qualified = [
        item
        for item in summaries
        if item["quality_qualified"]
        and item["median_cost_usd"] is not None
        and item["median_latency_seconds"] is not None
    ]
    recommendation = None
    if qualified:
        minimum_cost = min(float(item["median_cost_usd"]) for item in qualified)
        minimum_latency = min(
            float(item["median_latency_seconds"]) for item in qualified
        )
        for item in qualified:
            cost_ratio = float(item["median_cost_usd"]) / max(minimum_cost, 1e-12)
            latency_ratio = float(item["median_latency_seconds"]) / max(
                minimum_latency, 1e-12
            )
            item["balanced_index"] = math.sqrt(cost_ratio * latency_ratio)
        winner = min(qualified, key=lambda item: item["balanced_index"])
        recommendation = {
            "candidate_id": winner["candidate_id"],
            "rule": (
                "lowest geometric mean of median-cost and median-latency ratios "
                "among candidates with no failures, 100% valid outputs, and minimum score >= 0.90"
            ),
            "balanced_index": winner["balanced_index"],
        }
    return {"candidates": summaries, "recommendation": recommendation}


async def run_bakeoff(
    candidates: tuple[BakeoffCandidate, ...],
    *,
    output_dir: Path,
    replicates: int,
    warmups: int,
    concurrency: int,
    max_spend_usd: float,
    max_input_tokens: int = 4000,
    max_output_tokens: int = 2500,
) -> dict[str, Any]:
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise RuntimeError("OPENROUTER_API_KEY is required for --execute")
    if replicates < 1 or warmups < 1 or concurrency < 1:
        raise ValueError("replicates, warmups, and concurrency must all be positive")
    ceiling = conservative_cost_ceiling(
        candidates,
        replicates=replicates,
        warmups=warmups,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
    )
    if ceiling > max_spend_usd:
        raise ValueError(
            f"conservative ${ceiling:.6f} ceiling exceeds ${max_spend_usd:.6f} cap"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_root = output_dir / "evidence"
    preflight = await asyncio.gather(
        *(asyncio.to_thread(preflight_candidate, candidate) for candidate in candidates)
    )
    standard_candidates = tuple(
        candidate for candidate in candidates if candidate.lane == "standard"
    )
    batch_candidates = tuple(
        candidate for candidate in candidates if candidate.lane == "batch_variant"
    )
    client = OpenRouterChatClient() if standard_candidates else None
    semaphore = asyncio.Semaphore(concurrency)
    rows: list[dict[str, Any]] = []

    # Seed each model's provider-side prompt cache before any same-model fan-out.
    for warmup_index in range(warmups):
        warmup_rows = await asyncio.gather(
            *(
                _run_one(
                    candidate,
                    client=client,
                    evidence_root=evidence_root,
                    seed=70_000 + warmup_index,
                    warmup=True,
                    max_output_tokens=max_output_tokens,
                    max_input_tokens=max_input_tokens,
                    semaphore=semaphore,
                )
                for candidate in standard_candidates
            )
        )
        rows.extend(warmup_rows)

    measured_jobs = [
        (candidate, 71_000 + replicate_index)
        for candidate in standard_candidates
        for replicate_index in range(replicates)
    ]
    random.Random(20_260_831).shuffle(measured_jobs)
    rows.extend(
        await asyncio.gather(
            *(
                _run_one(
                    candidate,
                    client=client,
                    evidence_root=evidence_root,
                    seed=seed,
                    warmup=False,
                    max_output_tokens=max_output_tokens,
                    max_input_tokens=max_input_tokens,
                    semaphore=semaphore,
                )
                for candidate, seed in measured_jobs
            )
        )
    )
    for candidate in batch_candidates:
        batch_client = OpenRouterBatchClient(expected_requests=replicates)
        batch_semaphore = asyncio.Semaphore(replicates)
        rows.extend(
            await asyncio.gather(
                *(
                    _run_one(
                        candidate,
                        client=batch_client,
                        evidence_root=evidence_root,
                        seed=72_000 + replicate_index,
                        warmup=False,
                        max_output_tokens=max_output_tokens,
                        max_input_tokens=max_input_tokens,
                        semaphore=batch_semaphore,
                    )
                    for replicate_index in range(replicates)
                )
            )
        )
    actual_spend = sum(float(row.get("cost_usd", 0.0)) for row in rows)
    return {
        "spec_version": "aeread.procurement_openrouter_bakeoff/1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "case_id": "procurement_grounding_v1.dev.231_projects",
        "provider": "openrouter",
        "catalog_retrieved_at": CATALOG_RETRIEVED_AT,
        "catalog_source": CATALOG_SOURCE,
        "protocol": {
            "replicates": replicates,
            "warmups": warmups,
            "concurrency": concurrency,
            "response_cache": "disabled",
            "prompt_cache": "automatic_provider_cache_after_warmup",
            "batch_submission": (
                "one_grouped_async_job_per_batch_candidate; no cache warmup"
            ),
            "fallbacks": "disabled",
            "quality_threshold": 0.90,
            "conservative_cost_ceiling_usd": ceiling,
            "max_spend_usd": max_spend_usd,
        },
        "preflight": list(preflight),
        "rows": rows,
        "summary": summarize_rows(rows),
        "actual_spend_usd": actual_spend,
    }


def planned_matrix(
    candidates: tuple[BakeoffCandidate, ...],
    *,
    replicates: int,
    warmups: int,
    concurrency: int,
    max_input_tokens: int = 4000,
    max_output_tokens: int = 2500,
) -> dict[str, Any]:
    return {
        "provider": "openrouter",
        "case_id": "procurement_grounding_v1.dev.231_projects",
        "catalog_retrieved_at": CATALOG_RETRIEVED_AT,
        "catalog_source": CATALOG_SOURCE,
        "replicates": replicates,
        "warmups": warmups,
        "concurrency": concurrency,
        "response_cache": "disabled",
        "conservative_cost_ceiling_usd": conservative_cost_ceiling(
            candidates,
            replicates=replicates,
            warmups=warmups,
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
        ),
        "candidates": [
            {
                "candidate_id": candidate.candidate_id,
                "lane": candidate.lane,
                "access_class": candidate.access_class,
                "license_id": candidate.license_id,
                "model_card_url": candidate.model_card_url,
                "model": candidate.route.model,
                "revision": candidate.route.revision,
                "route_provider": candidate.route.route_provider,
                "quantization": candidate.route.quantization,
                "input_per_million": candidate.route.pricing.input_per_million,
                "cached_input_per_million": (
                    candidate.route.pricing.cached_input_per_million
                ),
                "output_per_million": candidate.route.pricing.output_per_million,
            }
            for candidate in candidates
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--run-root",
        "--output",
        dest="run_root",
        type=Path,
        default=Path("runs/procurement_grounding_openrouter_bakeoff"),
        help="ignored local run directory (legacy alias: --output)",
    )
    parser.add_argument("--replicates", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-spend-usd", type=float, default=0.15)
    parser.add_argument("--no-batch", action="store_true")
    parser.add_argument("--open-weight-only", action="store_true")
    parser.add_argument("--candidate", action="append", dest="candidates")
    arguments = parser.parse_args(argv)
    candidates = selected_candidates(
        arguments.candidates,
        include_batch=not arguments.no_batch,
        open_weight_only=arguments.open_weight_only,
    )
    if not arguments.execute:
        print(
            canonical_json_bytes(
                planned_matrix(
                    candidates,
                    replicates=arguments.replicates,
                    warmups=arguments.warmups,
                    concurrency=arguments.concurrency,
                )
            ).decode("utf-8")
        )
        return 0

    result = asyncio.run(
        run_bakeoff(
            candidates,
            output_dir=arguments.run_root,
            replicates=arguments.replicates,
            warmups=arguments.warmups,
            concurrency=arguments.concurrency,
            max_spend_usd=arguments.max_spend_usd,
        )
    )
    result_path = arguments.run_root / "results.json"
    result_path.write_bytes(canonical_json_bytes(result) + b"\n")
    print(
        canonical_json_bytes(
            {
                "results": str(result_path),
                "actual_spend_usd": result["actual_spend_usd"],
                "summary": result["summary"],
            }
        ).decode("utf-8")
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "BakeoffCandidate",
    "ALL_CANDIDATES",
    "DEFAULT_CANDIDATES",
    "OPEN_WEIGHT_CANDIDATES",
    "conservative_cost_ceiling",
    "planned_matrix",
    "preflight_candidate",
    "run_bakeoff",
    "selected_candidates",
    "summarize_rows",
]
