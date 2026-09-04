"""Versioned OpenRouter adapter for non-reasoning structured-output routes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import (
    OpenRouterChatClient,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
)


CLIENT_IMPLEMENTATION_ID = "datacenter_objective_openrouter_parameter_compatible_v1"
INDICATOR_MAP_CLIENT_IMPLEMENTATION_ID = (
    "datacenter_objective_openrouter_indicator_map_v1"
)


class ParameterCompatibleOpenRouterClient(OpenRouterChatClient):
    """Omit the reasoning parameter when the profile declares no control.

    OpenRouter's `require_parameters` gate evaluates the transmitted request.
    An empty reasoning object is still a transmitted parameter and can remove
    otherwise compatible structured-output endpoints from the feasible route.
    """

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if request.provider != "openrouter":
            raise ProviderFailure(
                "provider_contract",
                f"OpenRouter adapter received provider {request.provider!r}",
                retryable=False,
            )
        requested_base_url = (request.base_url or "").rstrip("/")
        if requested_base_url != self._base_url:
            raise ProviderFailure(
                "provider_contract",
                f"request base URL {requested_base_url!r} does not match client base URL "
                f"{self._base_url!r}",
                retryable=False,
            )
        if request.messages is not None:
            raise ProviderFailure(
                "provider_contract",
                "parameter-compatible objective adapter supports structured output only",
                retryable=False,
            )
        if not isinstance(request.output_schema, Mapping):
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter adapter requires a structured output schema",
                retryable=False,
            )

        provider_preferences, canonical_model, route_provider = self._route_preferences(
            request
        )
        wire_output_schema = json.loads(canonical_json_bytes(request.output_schema))
        extra_body: dict[str, Any] = {"provider": provider_preferences}
        reasoning: dict[str, Any] = {}
        if request.reasoning_effort is not None:
            reasoning["effort"] = request.reasoning_effort
        if request.reasoning_token_budget is not None:
            reasoning["max_tokens"] = request.reasoning_token_budget
        if reasoning:
            extra_body["reasoning"] = reasoning
        kwargs: dict[str, Any] = {
            "model": request.model,
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
                    "schema": wire_output_schema,
                },
            },
            "tools": [],
            "stream": False,
            "extra_headers": {"X-OpenRouter-Metadata": "enabled"},
            "extra_body": extra_body,
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.top_p is not None:
            kwargs["top_p"] = request.top_p

        response = await self._create(**kwargs)
        raw_response, choice, message = self._parsed_choice(response)
        content = message.get("content") if isinstance(message, Mapping) else None
        input_tokens, cached_input_tokens, output_tokens, cost = self._usage(raw_response)
        selected_model = self._verify_route(
            raw_response.get("openrouter_metadata"),
            requested_model=request.model,
            canonical_model=canonical_model,
            route_provider=route_provider,
        )
        response_model = raw_response.get("model")
        if response_model not in {request.model, canonical_model}:
            raise ProviderFailure(
                "provider_contract",
                f"OpenRouter response model {response_model!r} was not requested",
                retryable=False,
            )
        if content is None or (isinstance(content, str) and not content.strip()):
            return ProviderResult(
                response_id=str(raw_response.get("id") or ""),
                requested_model=request.model,
                resolved_model=selected_model,
                output_text="",
                finish_reason=str(choice.get("finish_reason") or "unknown"),
                input_tokens=input_tokens,
                cached_input_tokens=cached_input_tokens,
                output_tokens=output_tokens,
                cost_usd=float(cost),
                raw_response=raw_response,
            )
        if not isinstance(content, str):
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter response choice has non-text content",
                retryable=False,
            )
        try:
            structured_output = json.loads(content)
        except json.JSONDecodeError as error:
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter structured output is not valid JSON",
                retryable=False,
            ) from error
        return ProviderResult(
            response_id=str(raw_response.get("id") or ""),
            requested_model=request.model,
            resolved_model=selected_model,
            output_text=canonical_json_bytes(structured_output).decode("utf-8"),
            finish_reason=str(choice.get("finish_reason") or "unknown"),
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            cost_usd=float(cost),
            raw_response=raw_response,
        )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def normalize_indicator_map_output(output_text: str) -> str:
    """Convert a full boolean classifier response to canonical label arrays."""

    value = json.loads(output_text, object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError("indicator-map response must be a JSON object")
    for field in ("actions", "claims", "evidence_ids"):
        indicators = value.get(field)
        if not isinstance(indicators, dict) or not all(
            isinstance(item, bool) for item in indicators.values()
        ):
            raise ValueError(f"indicator-map field {field} must contain booleans")
        value[field] = [key for key, selected in indicators.items() if selected]
    external = value.get("external_actions_attempted")
    if (
        not isinstance(external, dict)
        or set(external) != {"any"}
        or not isinstance(external["any"], bool)
    ):
        raise ValueError("external action indicator must contain one boolean")
    value["external_actions_attempted"] = (
        ["declared_external_action"] if external["any"] else []
    )
    return canonical_json_bytes(value).decode("utf-8")


class IndicatorMapOpenRouterClient(ParameterCompatibleOpenRouterClient):
    """Execute a typed indicator schema and expose canonical arrays to scoring."""

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        result = await super().complete(request)
        if not result.output_text.strip():
            return result
        try:
            normalized = normalize_indicator_map_output(result.output_text)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ProviderFailure(
                "provider_contract",
                "OpenRouter indicator-map response is invalid",
                retryable=False,
            ) from error
        return replace(result, output_text=normalized)


__all__ = [
    "CLIENT_IMPLEMENTATION_ID",
    "INDICATOR_MAP_CLIENT_IMPLEMENTATION_ID",
    "IndicatorMapOpenRouterClient",
    "ParameterCompatibleOpenRouterClient",
    "normalize_indicator_map_output",
]
