"""Paired Housing trajectories through popular open-source agent harnesses.

The Housing scheduler and receipts remain authoritative.  Framework adapters
run inside a provider client because LangChain and smolagents own their wire
serialization; each adapter returns the framework's final structured action
plus every captured OpenRouter response as evidence on the enclosing action.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .execution import (
    OpenRouterChatClient,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
    execute_plan_cell,
)
from .harness import MinimalChatHarness
from .housing import (
    HousingScriptedLandlordProvider,
    OpenRouterRoutePin,
    build_housing_smoke,
    finalize_housing_execution,
)
from .paired_analysis import analyze_paired_results_if_available
from .open_harnesses import (
    FrameworkOneCallHarness,
    LangChainProviderClient,
    LangChainProviderStrategyHarness,
    LangGraphProviderClient,
    LangGraphStructuredOutputHarness,
    _capture_http_client,
    _classify_framework_error,
    _framework_result,
    _nonnegative_int,
    _route_body,
    _summed_usage,
)
from .registry import HarnessRequirements
from .resolver import canonical_json_bytes


GLM_MODEL = "z-ai/glm-5.3-flash"
GLM_REVISION = "z-ai/glm-5.3-flash-20260826"
GLM_DEEPINFRA_ROUTE = OpenRouterRoutePin(
    provider="DeepInfra",
    quantization="fp8",
    canonical_model=GLM_REVISION,
    input_per_million=0.075,
    cached_input_per_million=0.075,
    output_per_million=0.25,
    pricing_id="openrouter_deepinfra_2026-08-31_glm-5.3-flash",
)
HARNESS_ARM_IDS = (
    "aeread_minimal_chat_v1",
    "langchain_provider_strategy_v1",
    "langgraph_structured_output_v1",
    "smolagents_tool_calling_agent_v1",
)
MODEL_LANDLORD_PROFILE_ID = "housing_glm_landlord_fixed_v1"


class HousingRoleRoutingProviderClient:
    """Keep the tenant harness treatment out of fixed model-landlord calls."""

    def __init__(self, *, tenant: Any, landlord: Any) -> None:
        self._tenant = tenant
        self._landlord = landlord

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        try:
            payload = json.loads(request.input_text)
        except json.JSONDecodeError as error:
            raise ProviderFailure(
                "provider_contract",
                "Housing role router requires the canonical decision request",
                retryable=False,
            ) from error
        role = payload.get("role") if isinstance(payload, Mapping) else None
        if role == "tenant":
            return await self._tenant.complete(request)
        if role == "landlord":
            return await self._landlord.complete(request)
        raise ProviderFailure(
            "provider_contract",
            f"Housing role router received unknown role {role!r}",
            retryable=False,
        )


class SmolagentsToolCallingHarness(FrameworkOneCallHarness):
    id = "smolagents_tool_calling_agent"
    requires = HarnessRequirements(
        provider=frozenset({"native_tools", "seed", "system_prompt"}),
        tools="none",
        memory=frozenset({"disabled"}),
        owns_retries=False,
        owns_tools=True,
        replayable=True,
        blocking=False,
        spawns_subagents=False,
    )


def _smol_final_answer_tool(output_schema: Mapping[str, Any]) -> Any:
    from smolagents import Tool

    properties = output_schema.get("properties")
    if not isinstance(properties, Mapping):
        raise ProviderFailure(
            "provider_contract", "smolagents schema has no properties", retryable=False
        )
    keys = set(properties)
    if keys == {"decision", "listing_id", "rent"}:

        class FinalAnswerTool(Tool):
            name = "final_answer"
            description = "Return the final Housing action. Call this exactly once."
            inputs = {
                "decision": {
                    "type": "string",
                    "enum": ["offer", "pass"],
                    "description": "Offer or pass.",
                },
                "listing_id": {
                    "type": ["integer", "null"],
                    "nullable": True,
                    "description": "Open listing id or null.",
                },
                "rent": {
                    "type": ["integer", "number", "null"],
                    "nullable": True,
                    "description": "Proposed rent or null.",
                },
            }
            output_type = "object"

            def forward(
                self, decision: str, listing_id: int | None, rent: float | None
            ) -> dict[str, Any]:
                return {"decision": decision, "listing_id": listing_id, "rent": rent}

        return FinalAnswerTool()
    if keys == {"decision", "hold_id"}:

        class FinalAnswerTool(Tool):
            name = "final_answer"
            description = "Return the final Housing action. Call this exactly once."
            inputs = {
                "decision": {
                    "type": "string",
                    "enum": ["sign", "walk", "pass"],
                    "description": "Sign, walk, or pass.",
                },
                "hold_id": {
                    "type": ["string", "null"],
                    "nullable": True,
                    "description": "Exact active hold id or null.",
                },
            }
            output_type = "object"

            def forward(self, decision: str, hold_id: str | None) -> dict[str, Any]:
                return {"decision": decision, "hold_id": hold_id}

        return FinalAnswerTool()
    raise ProviderFailure(
        "provider_contract",
        f"unsupported smolagents Housing action keys: {sorted(keys)}",
        retryable=False,
    )


class SmolagentsProviderClient:
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
        from smolagents import OpenAIModel, ToolCallingAgent
        from smolagents.monitoring import LogLevel

        if not isinstance(request.output_schema, Mapping):
            raise ProviderFailure(
                "provider_contract",
                "smolagents requires an output schema",
                retryable=False,
            )
        captured: list[dict[str, Any]] = []
        http_client = _capture_http_client(captured)
        started = time.perf_counter()
        try:
            model = OpenAIModel(
                model_id=request.model,
                api_base=request.base_url,
                api_key=os.environ["OPENROUTER_API_KEY"],
                client_kwargs={
                    "max_retries": 0,
                    "timeout": request.timeout_seconds,
                    "default_headers": {"X-OpenRouter-Metadata": "enabled"},
                    "http_client": http_client,
                },
                retry=False,
                temperature=request.temperature,
                top_p=request.top_p,
                seed=request.seed,
                max_tokens=request.max_output_tokens,
                extra_body=_route_body(request),
            )
            agent = ToolCallingAgent(
                tools=[_smol_final_answer_tool(request.output_schema)],
                model=model,
                instructions=request.instructions,
                max_steps=2,
                verbosity_level=LogLevel.ERROR,
            )
            action = agent.run(request.input_text, reset=True)
            if isinstance(action, str):
                try:
                    action = json.loads(action)
                except json.JSONDecodeError:
                    pass
            if not isinstance(action, Mapping):
                raise ProviderFailure(
                    "provider_contract",
                    "smolagents returned no structured action",
                    retryable=False,
                )
            monitor_counts = agent.monitor.get_total_token_counts()
            return _framework_result(
                request=request,
                framework="smolagents_tool_calling_agent",
                framework_version=importlib.metadata.version("smolagents"),
                action=action,
                raw_responses=captured,
                elapsed_seconds=time.perf_counter() - started,
                trace={
                    "monitor_input_tokens": monitor_counts.input_tokens,
                    "monitor_output_tokens": monitor_counts.output_tokens,
                    "step_count": len(agent.monitor.step_durations),
                },
            )
        finally:
            http_client.close()


@dataclass(frozen=True, slots=True)
class HarnessArm:
    condition_id: str
    harness: Any
    provider: Any


def harness_arms() -> tuple[HarnessArm, ...]:
    return (
        HarnessArm(
            "aeread_minimal_chat_v1",
            MinimalChatHarness(),
            OpenRouterChatClient(),
        ),
        HarnessArm(
            "langchain_provider_strategy_v1",
            LangChainProviderStrategyHarness(),
            LangChainProviderClient(),
        ),
        HarnessArm(
            "langgraph_structured_output_v1",
            LangGraphStructuredOutputHarness(),
            LangGraphProviderClient(),
        ),
        HarnessArm(
            "smolagents_tool_calling_agent_v1",
            SmolagentsToolCallingHarness(),
            SmolagentsProviderClient(),
        ),
    )


def derive_world_seeds(*, master_seed: int, count: int) -> tuple[int, ...]:
    if master_seed < 0 or count < 1:
        raise ValueError("master_seed must be non-negative and count positive")
    seeds: list[int] = []
    seen: set[int] = set()
    counter = 0
    while len(seeds) < count:
        payload = f"housing_panel_v1:{master_seed}:{counter}".encode("utf-8")
        counter += 1
        candidate = (
            int.from_bytes(hashlib.sha256(payload).digest()[:4], "big") & 0x7FFF_FFFF
        )
        if candidate not in seen:
            seen.add(candidate)
            seeds.append(candidate)
    return tuple(seeds)


def _public_failure_summary(error: BaseException) -> dict[str, Any]:
    """Keep failure evidence useful without publishing raw provider payloads."""

    message = str(error).lower()
    status_code = getattr(error, "status_code", None)
    condition = getattr(error, "condition", None)
    if status_code == 429 or "error code: 429" in message or "rate-limit" in message:
        condition = "provider_rate_limit"
        status_code = 429
    elif "no structured action" in message or "malformed final json" in message:
        condition = "provider_contract"
    elif not isinstance(condition, str) or not condition:
        condition = "execution_error"
    return {
        "failure_type": type(error).__name__,
        "failure_condition": condition,
        "failure_status_code": status_code if isinstance(status_code, int) else None,
    }


def _relative_evidence_root(*, evidence_root: Path, output_root: Path) -> str:
    try:
        return str(evidence_root.resolve().relative_to(output_root.resolve()))
    except ValueError as error:
        raise ValueError(
            "evidence root must be inside the bake-off output root"
        ) from error


def _condition_summary(
    rows: Sequence[Mapping[str, Any]], *, condition_id: str, planned: int
) -> dict[str, Any]:
    attempted = [row for row in rows if row.get("condition_id") == condition_id]
    completed = [row for row in attempted if row.get("status") == "completed"]
    failures = len(attempted) - len(completed)
    complete_panel = len(attempted) == planned and len(completed) == planned

    def complete_total(field: str) -> int | float | None:
        values = [
            row.get(field)
            for row in completed
            if isinstance(row.get(field), (int, float))
            and not isinstance(row.get(field), bool)
        ]
        if len(values) != len(completed):
            return None
        return sum(values)

    completed_count = len(completed)
    total_cost = complete_total("cost_usd")
    total_input = complete_total("input_tokens")
    total_output = complete_total("output_tokens")
    total_requests = complete_total("framework_model_request_count")
    total_retries = complete_total("effective_retry_count")
    total_subject_calls = complete_total("subject_provider_call_count")
    total_opponent_calls = complete_total("opponent_provider_call_count")
    total_subject_cost = complete_total("subject_cost_usd")
    total_opponent_cost = complete_total("opponent_cost_usd")
    route_verified = complete_panel and all(
        row.get("framework_route_verified") is True for row in completed
    )
    provider_cost_complete = complete_panel and all(
        row.get("framework_provider_cost_complete") is True for row in completed
    )
    return {
        "planned_worlds": planned,
        "attempted_worlds": len(attempted),
        "completed_worlds": completed_count,
        "operational_failures": failures,
        "mean_within_case_score": (
            sum(float(row["within_case_score"]) for row in completed) / completed_count
            if completed
            else None
        ),
        "mean_elapsed_seconds": (
            sum(float(row["elapsed_seconds"]) for row in attempted) / len(attempted)
            if attempted
            else None
        ),
        "total_input_tokens": int(total_input) if total_input is not None else None,
        "total_output_tokens": int(total_output) if total_output is not None else None,
        "total_cost_usd": float(total_cost) if total_cost is not None else None,
        "total_provider_model_requests": (
            int(total_requests) if total_requests is not None else None
        ),
        "effective_retry_count": (
            int(total_retries) if total_retries is not None else None
        ),
        "total_subject_provider_calls": (
            int(total_subject_calls) if total_subject_calls is not None else None
        ),
        "total_opponent_provider_calls": (
            int(total_opponent_calls) if total_opponent_calls is not None else None
        ),
        "total_subject_cost_usd": (
            float(total_subject_cost) if total_subject_cost is not None else None
        ),
        "total_opponent_cost_usd": (
            float(total_opponent_cost) if total_opponent_cost is not None else None
        ),
        "route_verified": route_verified,
        "provider_cost_complete": provider_cost_complete,
        "cost_qualifier": "exact" if provider_cost_complete else "unknown",
    }


def _sealed_row(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = {key: item for key, item in value.items() if key != "result_sha256"}
    return {
        **payload,
        "result_sha256": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    }


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    payload = canonical_json_bytes(value) + b"\n"
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _read_sealed_row(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, Mapping):
        raise ValueError(f"result is not an object: {path}")
    sealed = _sealed_row(value)
    if canonical_json_bytes(value) != canonical_json_bytes(sealed):
        raise ValueError(f"result digest mismatch: {path}")
    return sealed


def _event_framework_metrics(evidence: Any) -> dict[str, Any]:
    framework_calls = 0
    route_verified = True
    provider_cost_complete = True
    framework_versions: set[str] = set()
    for event in evidence.read_events():
        if event.event_type != "provider_call_succeeded":
            continue
        payload = evidence.read_event_payload(event)
        result = (
            payload.get("provider_result") if isinstance(payload, Mapping) else None
        )
        raw = result.get("raw_response") if isinstance(result, Mapping) else None
        if not isinstance(raw, Mapping) or raw.get("fixture") is True:
            continue
        if "framework" not in raw:
            framework_calls += 1
            usage = raw.get("usage")
            provider_cost_complete = provider_cost_complete and (
                isinstance(usage, Mapping)
                and isinstance(usage.get("cost"), (int, float))
            )
            continue
        framework_calls += _nonnegative_int(raw.get("framework_model_request_count"))
        provider_cost_complete = (
            provider_cost_complete and raw.get("provider_cost_complete") is True
        )
        version = raw.get("framework_version")
        if isinstance(version, str):
            framework_versions.add(version)
        responses = raw.get("provider_responses")
        if not isinstance(responses, list) or not responses:
            route_verified = False
            continue
        for response in responses:
            metadata = (
                response.get("openrouter_metadata")
                if isinstance(response, Mapping)
                else None
            )
            selected = (
                ((metadata or {}).get("endpoints") or {}).get("available")
                if isinstance(metadata, Mapping)
                else None
            )
            selected = [row for row in (selected or []) if row.get("selected")]
            route_verified = (
                route_verified
                and len(selected) == 1
                and selected[0].get("provider") == "DeepInfra"
            )
    return {
        "framework_model_request_count": framework_calls,
        "framework_versions": sorted(framework_versions),
        "framework_route_verified": route_verified,
        "framework_provider_cost_complete": provider_cost_complete,
    }


def _execution_role_metrics(
    execution: Any, *, landlord_profile_id: str
) -> dict[str, int | float]:
    subject_calls = []
    opponent_calls = []
    for action in execution.action_executions:
        destination = (
            opponent_calls
            if action.profile_id == landlord_profile_id
            else subject_calls
        )
        for attempt in action.attempts:
            destination.extend(attempt.provider_calls)

    def metrics(calls: Sequence[Any]) -> dict[str, int | float]:
        return {
            "provider_call_count": len(calls),
            "input_tokens": sum(call.input_tokens for call in calls),
            "output_tokens": sum(call.output_tokens for call in calls),
            "cost_usd": sum(call.cost_usd for call in calls),
        }

    subject = metrics(subject_calls)
    opponent = metrics(opponent_calls)
    return {
        **{f"subject_{key}": value for key, value in subject.items()},
        **{f"opponent_{key}": value for key, value in opponent.items()},
    }


def _framework_versions(arms: Sequence[HarnessArm]) -> dict[str, str]:
    packages = {"openai"}
    for arm in arms:
        if isinstance(arm.harness, LangChainProviderStrategyHarness):
            packages.update({"langchain", "langchain-openai"})
        elif isinstance(arm.harness, LangGraphStructuredOutputHarness):
            packages.update({"langchain-openai", "langgraph"})
        elif isinstance(arm.harness, SmolagentsToolCallingHarness):
            packages.add("smolagents")
    return {
        package: importlib.metadata.version(package) for package in sorted(packages)
    }


async def run_bakeoff(
    *,
    output_root: Path,
    world_seeds: Sequence[int],
    num_tenants: int = 6,
    num_listings: int = 4,
    rounds: int = 4,
    inference_seed_base: int = 87001,
    model_landlords: bool = False,
    landlord_inference_seed_base: int = 97001,
    arm_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    implementation_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    arms = tuple(
        arm
        for arm in harness_arms()
        if arm_ids is None or arm.condition_id in set(arm_ids)
    )
    if not arms:
        raise ValueError("arm_ids selected no harness arms")
    setups: dict[str, Any] = {}
    for arm in arms:
        external = not isinstance(arm.harness, MinimalChatHarness)
        setups[arm.condition_id] = build_housing_smoke(
            tenant_provider="openrouter",
            tenant_model=GLM_MODEL,
            tenant_revision=GLM_REVISION,
            world_seeds=tuple(world_seeds),
            replicates=1,
            reasoning_condition_id=arm.condition_id,
            reasoning_effort="low",
            inference_seed_base=inference_seed_base,
            num_tenants=num_tenants,
            num_listings=num_listings,
            rounds=rounds,
            openrouter_route=GLM_DEEPINFRA_ROUTE,
            tenant_harness=arm.harness,
            tenant_harness_config={
                "framework_package": (
                    None
                    if not external
                    else (
                        "langchain"
                        if isinstance(arm.harness, LangChainProviderStrategyHarness)
                        else (
                            "langgraph"
                            if isinstance(arm.harness, LangGraphStructuredOutputHarness)
                            else "smolagents"
                        )
                    )
                ),
                "framework_version": (
                    None
                    if not external
                    else importlib.metadata.version(
                        "langchain"
                        if isinstance(arm.harness, LangChainProviderStrategyHarness)
                        else (
                            "langgraph"
                            if isinstance(arm.harness, LangGraphStructuredOutputHarness)
                            else "smolagents"
                        )
                    )
                ),
                "framework_retries": 0,
            },
            tenant_profile_id_override=f"housing_glm_tenant_{arm.condition_id}",
            tenant_runtime=(
                "aeread.shared_runner.housing_harness_bakeoff"
                if external
                else "aeread.shared_runner.execution"
            ),
            tenant_implementation_sha256=(implementation_sha256 if external else None),
            landlord_provider=(
                "openrouter" if model_landlords else "housing_scripted_landlord"
            ),
            landlord_model=(
                GLM_MODEL if model_landlords else "housing_scripted_landlord_v1"
            ),
            landlord_revision=(
                GLM_REVISION if model_landlords else "1.0.0"
            ),
            landlord_profile_id_override=(
                MODEL_LANDLORD_PROFILE_ID if model_landlords else None
            ),
            landlord_inference_seed_base=(
                landlord_inference_seed_base if model_landlords else None
            ),
            landlord_openrouter_route=(
                GLM_DEEPINFRA_ROUTE if model_landlords else None
            ),
        )

    output_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    arm_by_condition = {arm.condition_id: arm for arm in arms}
    conditions = [arm.condition_id for arm in arms]
    for world_index, world_seed in enumerate(world_seeds):
        rotated = (
            conditions[world_index % len(conditions) :]
            + conditions[: world_index % len(conditions)]
        )
        for condition in rotated:
            setup = setups[condition]
            cell = next(
                item for item in setup.plan.cells if item.world_seed == world_seed
            )
            result_path = output_root / condition / "results" / f"{cell.cell_id}.json"
            if result_path.exists():
                rows.append(_read_sealed_row(result_path))
                continue
            started = time.perf_counter()
            try:
                tenant_provider = arm_by_condition[condition].provider
                providers = (
                    {
                        "openrouter": HousingRoleRoutingProviderClient(
                            tenant=tenant_provider,
                            landlord=OpenRouterChatClient(),
                        )
                    }
                    if model_landlords
                    else {
                        "openrouter": tenant_provider,
                        "housing_scripted_landlord": HousingScriptedLandlordProvider(),
                    }
                )
                execution = await execute_plan_cell(
                    plan=setup.plan,
                    cell_id=cell.cell_id,
                    registry=setup.registry,
                    evidence_root=output_root / condition / "evidence",
                    prompt_sources=setup.prompt_sources,
                    providers=providers,
                    pricing=setup.pricing,
                    harnesses=setup.harnesses,
                )
                receipt = finalize_housing_execution(setup=setup, execution=execution)
                outcome = execution.episode_result.outcome
                row = {
                    "condition_id": condition,
                    "world_seed": world_seed,
                    "replicate_index": cell.replicate_index,
                    "status": "completed",
                    "within_case_score": outcome["within_case_score"],
                    "social_welfare": outcome["social_welfare"],
                    "tenant_payoff": sum(outcome["tenant_payoffs"].values()),
                    "landlord_payoff": sum(outcome["landlord_payoffs"].values()),
                    "ir_violation_count": len(outcome["ir_violations"]),
                    "wasted_contacts": outcome["wasted_contacts"],
                    "logical_action_count": execution.episode_result.logical_action_count,
                    "elapsed_seconds": time.perf_counter() - started,
                    "input_tokens": sum(
                        call.input_tokens
                        for action in execution.action_executions
                        for attempt in action.attempts
                        for call in attempt.provider_calls
                    ),
                    "output_tokens": sum(
                        call.output_tokens
                        for action in execution.action_executions
                        for attempt in action.attempts
                        for call in attempt.provider_calls
                    ),
                    "cost_usd": execution.total_cost_usd,
                    "receipt_sha256": receipt.receipt_sha256,
                    "evidence_root": _relative_evidence_root(
                        evidence_root=execution.evidence.root,
                        output_root=output_root,
                    ),
                    **_execution_role_metrics(
                        execution,
                        landlord_profile_id=(
                            MODEL_LANDLORD_PROFILE_ID
                            if model_landlords
                            else "housing_scripted_landlord_v1"
                        ),
                    ),
                    **_event_framework_metrics(execution.evidence),
                }
            except Exception as error:
                row = {
                    "condition_id": condition,
                    "world_seed": world_seed,
                    "replicate_index": cell.replicate_index,
                    "status": "operational_failure",
                    "elapsed_seconds": time.perf_counter() - started,
                    **_public_failure_summary(error),
                }
            row = _sealed_row(row)
            _atomic_write_json(result_path, row)
            rows.append(row)

    summaries = {
        condition: _condition_summary(
            rows, condition_id=condition, planned=len(world_seeds)
        )
        for condition in conditions
    }
    paired_conditions = {
        "aeread_minimal_chat_v1",
        "langchain_provider_strategy_v1",
    }
    if paired_conditions.issubset(conditions):
        paired_state = analyze_paired_results_if_available(
            [row for row in rows if row["condition_id"] in paired_conditions],
            control_condition="aeread_minimal_chat_v1",
            treatment_condition="langchain_provider_strategy_v1",
            expected_replicates=1,
            bootstrap_draws=10_000,
            bootstrap_seed=20260831,
        )
    else:
        paired_state = {
            "status": "deferred_missing_paired_conditions",
            "analysis": None,
        }
    artifact = {
        "schema_version": "aeread.housing_harness_bakeoff/0.2",
        "scope": "full_housing_v1_trajectory",
        "model_route": {
            "requested_model": GLM_MODEL,
            "canonical_model": GLM_REVISION,
            "provider": GLM_DEEPINFRA_ROUTE.provider,
            "quantization": GLM_DEEPINFRA_ROUTE.quantization,
            "reasoning_effort": "low",
            "inference_seed_base": inference_seed_base,
            "temperature": 0.0,
            "top_p": 1.0,
        },
        "opponent": {
            "mode": "fixed_model" if model_landlords else "scripted",
            "profile_id": (
                MODEL_LANDLORD_PROFILE_ID
                if model_landlords
                else "housing_scripted_landlord_v1"
            ),
            "requested_model": GLM_MODEL if model_landlords else None,
            "canonical_model": GLM_REVISION if model_landlords else None,
            "provider": GLM_DEEPINFRA_ROUTE.provider if model_landlords else None,
            "quantization": (
                GLM_DEEPINFRA_ROUTE.quantization if model_landlords else None
            ),
            "harness": "minimal_chat/1.0" if model_landlords else "scripted",
            "reasoning_effort": "low" if model_landlords else None,
            "inference_seed_base": (
                landlord_inference_seed_base if model_landlords else None
            ),
        },
        "environment": {
            "family": "housing_v1",
            "world_seeds": list(world_seeds),
            "replicates": 1,
            "tenants": num_tenants,
            "listings": num_listings,
            "max_rounds": rounds,
            "controlled_landlords": True,
            "landlord_policy": "fixed_model" if model_landlords else "scripted",
        },
        "framework_versions": _framework_versions(arms),
        "measurement_boundary": {
            "housing_scheduler_and_scorer": "AERead authoritative",
            "external_framework_wire_execution": (
                "nested inside action-level provider adapter"
            ),
            "raw_provider_responses": (
                "sealed in local evidence; excluded from the public summary"
            ),
        },
        "condition_summaries": summaries,
        "paired_analysis_status": paired_state["status"],
        "paired_analysis": paired_state["analysis"],
        "paired_rows": rows,
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(artifact)
    ).hexdigest()
    _atomic_write_json(output_root / "summary.json", artifact)
    return artifact


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--world-count", type=int, default=3)
    parser.add_argument("--master-seed", type=int, default=20260831)
    parser.add_argument("--tenants", type=int, default=6)
    parser.add_argument("--listings", type=int, default=4)
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument(
        "--model-landlords",
        action="store_true",
        help="use a fixed minimal-chat GLM profile for every landlord seat",
    )
    parser.add_argument("--landlord-inference-seed-base", type=int, default=97001)
    parser.add_argument(
        "--arms",
        nargs="+",
        choices=HARNESS_ARM_IDS,
    )
    args = parser.parse_args(argv)
    artifact = asyncio.run(
        run_bakeoff(
            output_root=args.output,
            world_seeds=derive_world_seeds(
                master_seed=args.master_seed, count=args.world_count
            ),
            num_tenants=args.tenants,
            num_listings=args.listings,
            rounds=args.rounds,
            model_landlords=args.model_landlords,
            landlord_inference_seed_base=args.landlord_inference_seed_base,
            arm_ids=args.arms,
        )
    )
    print(json.dumps(artifact["condition_summaries"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "GLM_DEEPINFRA_ROUTE",
    "GLM_MODEL",
    "GLM_REVISION",
    "HousingRoleRoutingProviderClient",
    "MODEL_LANDLORD_PROFILE_ID",
    "LangChainProviderClient",
    "LangChainProviderStrategyHarness",
    "LangGraphProviderClient",
    "LangGraphStructuredOutputHarness",
    "SmolagentsProviderClient",
    "SmolagentsToolCallingHarness",
    "derive_world_seeds",
    "harness_arms",
    "run_bakeoff",
]
