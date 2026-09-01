"""Schema-driven adapters for open-source agent harnesses.

Frameworks such as LangChain own their provider serialization, so these
adapters run behind AERead's sealed model port.  They return the framework's
final structured action and preserve every captured OpenRouter response on the
enclosing provider result for reconciliation and cost accounting.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import math
import os
import time
from typing import Any, Mapping, Sequence, TypedDict

from .execution import (
    OpenRouterChatClient,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
)
from .harness import CanonicalMessage, FailureCondition, HarnessOutput
from .registry import HarnessRequirements
from .resolver import canonical_json_bytes


class FrameworkOneCallHarness:
    """AERead lifecycle adapter for a framework-owned provider invocation."""

    version = "1.0"
    requires: HarnessRequirements

    async def open_episode(self, episode: Any) -> None:
        return None

    async def close_episode(self, episode: Any) -> None:
        return None

    def classify_failure(self, exc: BaseException) -> FailureCondition:
        if isinstance(exc, ProviderFailure):
            return FailureCondition(exc.condition, retryable=exc.retryable)
        return FailureCondition("harness_error", retryable=False)

    def state_reader(self) -> Any:
        return None

    async def act(self, request: Any, ctx: Any) -> HarnessOutput:
        turn = await ctx.model.complete(
            messages=(
                CanonicalMessage(
                    role="user",
                    content=canonical_json_bytes(
                        {
                            "phase_id": request.phase_id,
                            "seat_id": request.seat_id,
                            "role": request.role,
                            "observation_schema": request.observation_schema,
                            "action_schema": request.action_schema,
                            "observation": request.observation,
                        }
                    ).decode("utf-8"),
                ),
            ),
            response_mode="text",
        )
        try:
            action = json.loads(turn.text or "")
        except json.JSONDecodeError as error:
            raise ProviderFailure(
                "provider_contract",
                f"{self.id} returned malformed final JSON",
                retryable=False,
            ) from error
        if not isinstance(action, Mapping):
            raise ProviderFailure(
                "provider_contract",
                f"{self.id} returned a non-object action",
                retryable=False,
            )
        return HarnessOutput(
            action=dict(action),
            claimed_tool_calls=(),
            rounds_used=1,
            notes={"framework": self.id},
        )


class LangChainProviderStrategyHarness(FrameworkOneCallHarness):
    id = "langchain_provider_strategy"
    requires = HarnessRequirements(
        provider=frozenset({"structured_output", "seed", "system_prompt"}),
        tools="none",
        memory=frozenset({"disabled"}),
        owns_retries=False,
        owns_tools=False,
        replayable=True,
        blocking=False,
        spawns_subagents=False,
    )


class LangGraphStructuredOutputHarness(FrameworkOneCallHarness):
    """One explicit LangGraph decision node with provider-native output."""

    id = "langgraph_structured_output"
    requires = HarnessRequirements(
        provider=frozenset({"structured_output", "seed", "system_prompt"}),
        tools="none",
        memory=frozenset({"disabled"}),
        owns_retries=False,
        owns_tools=False,
        replayable=True,
        blocking=False,
        spawns_subagents=False,
    )


def _route_body(request: ProviderRequest) -> dict[str, Any]:
    metadata = request.provider_metadata
    if not isinstance(metadata, Mapping):
        raise ProviderFailure(
            "provider_contract",
            "framework request lacks route metadata",
            retryable=False,
        )
    return {
        "reasoning": {"effort": request.reasoning_effort},
        "provider": {
            "only": [metadata["route_provider"]],
            "order": [metadata["route_provider"]],
            "allow_fallbacks": False,
            "require_parameters": True,
            "quantizations": [metadata["quantization"]],
            "max_price": {
                "prompt": metadata["max_prompt_price_per_million"],
                "completion": metadata["max_completion_price_per_million"],
            },
        },
    }


def _capture_http_client(captured: list[dict[str, Any]]) -> Any:
    openai_major = int(importlib.metadata.version("openai").split(".", 1)[0])
    if openai_major >= 3:
        import httpx2 as httpx
    else:
        import httpx

    def capture(response: Any) -> None:
        response.read()
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type:
            return
        try:
            value = response.json()
        except ValueError:
            return
        if isinstance(value, Mapping):
            captured.append(dict(value))

    return httpx.Client(event_hooks={"response": [capture]})


def _nonnegative_int(value: Any) -> int:
    return (
        int(value)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )


def _summed_usage(raw_responses: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    input_tokens = 0
    cached_tokens = 0
    output_tokens = 0
    reasoning_tokens = 0
    costs: list[float] = []
    for raw in raw_responses:
        usage = raw.get("usage")
        if not isinstance(usage, Mapping):
            continue
        input_tokens += _nonnegative_int(usage.get("prompt_tokens"))
        output_tokens += _nonnegative_int(usage.get("completion_tokens"))
        prompt_details = usage.get("prompt_tokens_details")
        completion_details = usage.get("completion_tokens_details")
        if isinstance(prompt_details, Mapping):
            cached_tokens += _nonnegative_int(prompt_details.get("cached_tokens"))
        if isinstance(completion_details, Mapping):
            reasoning_tokens += _nonnegative_int(
                completion_details.get("reasoning_tokens")
            )
        cost = usage.get("cost")
        if (
            isinstance(cost, (int, float))
            and not isinstance(cost, bool)
            and math.isfinite(cost)
        ):
            costs.append(float(cost))
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cost_usd": sum(costs) if len(costs) == len(raw_responses) else None,
        "provider_cost_complete": len(costs) == len(raw_responses),
    }


def _verify_framework_routes(
    request: ProviderRequest, raw_responses: Sequence[Mapping[str, Any]]
) -> str:
    metadata = request.provider_metadata
    if not isinstance(metadata, Mapping) or not raw_responses:
        raise ProviderFailure(
            "provider_contract",
            "framework adapter captured no verifiable provider response",
            retryable=False,
        )
    resolved: list[str] = []
    for raw in raw_responses:
        resolved.append(
            OpenRouterChatClient._verify_route(
                raw.get("openrouter_metadata"),
                requested_model=request.model,
                canonical_model=str(metadata["canonical_model"]),
                route_provider=str(metadata["route_provider"]),
            )
        )
    if len(set(resolved)) != 1:
        raise ProviderFailure(
            "provider_contract",
            f"framework calls resolved to multiple models: {sorted(set(resolved))}",
            retryable=False,
        )
    return resolved[0]


def _framework_result(
    *,
    request: ProviderRequest,
    framework: str,
    framework_version: str,
    action: Mapping[str, Any],
    raw_responses: Sequence[Mapping[str, Any]],
    elapsed_seconds: float,
    trace: Mapping[str, Any],
) -> ProviderResult:
    resolved_model = _verify_framework_routes(request, raw_responses)
    usage = _summed_usage(raw_responses)
    finish_reasons = [
        str(((raw.get("choices") or [{}])[0]).get("finish_reason") or "unknown")
        for raw in raw_responses
    ]
    response_ids = [str(raw.get("id") or "") for raw in raw_responses]
    response_id = (
        "framework_"
        + hashlib.sha256(canonical_json_bytes(response_ids)).hexdigest()[:20]
    )
    return ProviderResult(
        response_id=response_id,
        requested_model=request.model,
        resolved_model=resolved_model,
        output_text=canonical_json_bytes(dict(action)).decode("utf-8"),
        finish_reason="length" if "length" in finish_reasons else finish_reasons[-1],
        input_tokens=usage["input_tokens"],
        cached_input_tokens=usage["cached_input_tokens"],
        output_tokens=usage["output_tokens"],
        cost_usd=usage["cost_usd"],
        reasoning_tokens=usage["reasoning_tokens"],
        visible_output_tokens=max(
            0, usage["output_tokens"] - usage["reasoning_tokens"]
        ),
        raw_response={
            "framework": framework,
            "framework_version": framework_version,
            "framework_model_request_count": len(raw_responses),
            "elapsed_seconds": elapsed_seconds,
            "provider_cost_complete": usage["provider_cost_complete"],
            "provider_responses": list(raw_responses),
            "trace": dict(trace),
        },
    )


def _classify_framework_error(error: BaseException) -> ProviderFailure:
    status = getattr(error, "status_code", None)
    name = type(error).__name__
    if name in {"APITimeoutError", "TimeoutError"}:
        return ProviderFailure("timeout", str(error), retryable=True)
    if name == "RateLimitError" or status == 429:
        return ProviderFailure(
            "rate_limit", str(error), retryable=True, status_code=status
        )
    if name == "APIConnectionError":
        return ProviderFailure("transport", str(error), retryable=True)
    if isinstance(status, int) and status >= 500:
        return ProviderFailure(
            "provider_5xx", str(error), retryable=True, status_code=status
        )
    return ProviderFailure(
        "framework_error", f"{name}: {error}", retryable=False, status_code=status
    )


class LangChainProviderClient:
    async def complete(self, request: ProviderRequest) -> ProviderResult:
        try:
            return await asyncio.to_thread(self._complete_sync, request)
        except asyncio.CancelledError:
            raise
        except ProviderFailure:
            raise
        except Exception as error:
            raise _classify_framework_error(error) from error

    @staticmethod
    def _complete_sync(request: ProviderRequest) -> ProviderResult:
        from langchain.agents import create_agent
        from langchain.agents.structured_output import ProviderStrategy
        from langchain_core.messages import AIMessage
        from langchain_openai import ChatOpenAI

        if not isinstance(request.output_schema, Mapping):
            raise ProviderFailure(
                "provider_contract",
                "LangChain requires an output schema",
                retryable=False,
            )
        captured: list[dict[str, Any]] = []
        http_client = _capture_http_client(captured)
        started = time.perf_counter()
        try:
            extra_body = _route_body(request)
            # ChatOpenAI otherwise emits max_completion_tokens. The pinned
            # OpenRouter route declares max_tokens, so put the supported field
            # in the provider body and let OpenRouter reject any drift.
            extra_body["max_tokens"] = request.max_output_tokens
            model = ChatOpenAI(
                model=request.model,
                api_key=os.environ["OPENROUTER_API_KEY"],
                base_url=request.base_url,
                temperature=request.temperature,
                top_p=request.top_p,
                seed=request.seed,
                timeout=request.timeout_seconds,
                max_retries=0,
                default_headers={"X-OpenRouter-Metadata": "enabled"},
                extra_body=extra_body,
                http_client=http_client,
            )
            wire_schema = json.loads(canonical_json_bytes(request.output_schema))
            schema = {"title": "aeread_action", **wire_schema}
            agent = create_agent(
                model=model,
                tools=[],
                system_prompt=request.instructions,
                response_format=ProviderStrategy(schema),
            )
            state = agent.invoke(
                {"messages": [{"role": "user", "content": request.input_text}]},
                config={"recursion_limit": 6},
            )
            action = state.get("structured_response")
            if hasattr(action, "model_dump"):
                action = action.model_dump(mode="json")
            if not isinstance(action, Mapping):
                raise ProviderFailure(
                    "provider_contract",
                    "LangChain returned no structured action",
                    retryable=False,
                )
            messages = state.get("messages") or ()
            ai_messages = [item for item in messages if isinstance(item, AIMessage)]
            return _framework_result(
                request=request,
                framework="langchain_provider_strategy",
                framework_version=importlib.metadata.version("langchain"),
                action=action,
                raw_responses=captured,
                elapsed_seconds=time.perf_counter() - started,
                trace={"ai_message_count": len(ai_messages)},
            )
        finally:
            http_client.close()


class _LangGraphDecisionState(TypedDict, total=False):
    input_text: str
    action: Mapping[str, Any]


def _run_langgraph_structured_decision(
    structured_model: Any, request: ProviderRequest
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """Run one explicit graph node so graph orchestration is the treatment."""

    from langchain_core.messages import HumanMessage, SystemMessage
    from langgraph.graph import END, START, StateGraph

    calls = 0

    def decide(state: _LangGraphDecisionState) -> _LangGraphDecisionState:
        nonlocal calls
        calls += 1
        response = structured_model.invoke(
            [
                SystemMessage(content=request.instructions),
                HumanMessage(content=state["input_text"]),
            ]
        )
        parsed = response.get("parsed") if isinstance(response, Mapping) else response
        if hasattr(parsed, "model_dump"):
            parsed = parsed.model_dump(mode="json")
        if not isinstance(parsed, Mapping):
            raise ProviderFailure(
                "provider_contract",
                "LangGraph returned no structured action",
                retryable=False,
            )
        return {"action": dict(parsed)}

    builder = StateGraph(_LangGraphDecisionState)
    builder.add_node("decide", decide)
    builder.add_edge(START, "decide")
    builder.add_edge("decide", END)
    result = builder.compile().invoke(
        {"input_text": request.input_text}, config={"recursion_limit": 4}
    )
    action = result.get("action")
    if not isinstance(action, Mapping):
        raise ProviderFailure(
            "provider_contract",
            "LangGraph graph completed without an action",
            retryable=False,
        )
    return dict(action), {"graph_node_count": 1, "structured_model_calls": calls}


class LangGraphProviderClient:
    """Provider adapter for an explicit, single-node LangGraph harness."""

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        try:
            return await asyncio.to_thread(self._complete_sync, request)
        except asyncio.CancelledError:
            raise
        except ProviderFailure:
            raise
        except Exception as error:
            raise _classify_framework_error(error) from error

    @staticmethod
    def _complete_sync(request: ProviderRequest) -> ProviderResult:
        from langchain_openai import ChatOpenAI

        if not isinstance(request.output_schema, Mapping):
            raise ProviderFailure(
                "provider_contract",
                "LangGraph requires an output schema",
                retryable=False,
            )
        captured: list[dict[str, Any]] = []
        http_client = _capture_http_client(captured)
        started = time.perf_counter()
        try:
            extra_body = _route_body(request)
            extra_body["max_tokens"] = request.max_output_tokens
            model = ChatOpenAI(
                model=request.model,
                api_key=os.environ["OPENROUTER_API_KEY"],
                base_url=request.base_url,
                temperature=request.temperature,
                top_p=request.top_p,
                seed=request.seed,
                timeout=request.timeout_seconds,
                max_retries=0,
                default_headers={"X-OpenRouter-Metadata": "enabled"},
                extra_body=extra_body,
                http_client=http_client,
            )
            wire_schema = json.loads(canonical_json_bytes(request.output_schema))
            structured_model = model.with_structured_output(
                {"title": "aeread_action", **wire_schema},
                method="json_schema",
                strict=True,
                include_raw=True,
            )
            action, trace = _run_langgraph_structured_decision(
                structured_model, request
            )
            return _framework_result(
                request=request,
                framework="langgraph_structured_output",
                framework_version=importlib.metadata.version("langgraph"),
                action=action,
                raw_responses=captured,
                elapsed_seconds=time.perf_counter() - started,
                trace=trace,
            )
        finally:
            http_client.close()


__all__ = [
    "FrameworkOneCallHarness",
    "LangChainProviderClient",
    "LangChainProviderStrategyHarness",
    "LangGraphProviderClient",
    "LangGraphStructuredOutputHarness",
]
