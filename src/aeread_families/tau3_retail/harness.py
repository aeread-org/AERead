"""Provider-free scripted response source for tau3.retail integration tests."""
from __future__ import annotations

import copy
import json
from typing import Any, Mapping, Sequence

from aeread.shared_runner.model_call.harness import (
    AttemptContext,
    CanonicalMessage,
    ClaimedToolCall,
    FailureCondition,
    HarnessOutput,
)
from aeread.shared_runner.registry import HarnessRequirements
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import (
    EvidenceStore,
    ProviderFailure,
    ToolFailure,
)
from aeread.shared_runner.task.tools import ToolRuntime

from .environment import MAX_TOOL_ERRORS
from .tau2_bridge import Tau2Bridge
from .tools import RetailToolSession, build_tool_bindings


class ScriptedTau3RetailHarness:
    """Serve fixed user/assistant actions and record delegated tool evidence.

    ``script`` is an ordered sequence of ``(phase_id, response)`` pairs. For
    an assistant response, every tool call in every message is executed in
    list order through the kernel ``ToolRuntime``. The returned response adds
    the exact result and post-call upstream DB hash for ``step`` to replay and
    verify against its independent canonical state.
    """

    def __init__(
        self,
        *,
        bridge: Tau2Bridge,
        initial_db: Mapping[str, Any],
        evidence: EvidenceStore,
        script: Sequence[tuple[str, Mapping[str, Any]]],
    ) -> None:
        self.bridge = bridge
        self.evidence = evidence
        self.requests: list[Any] = []
        self._script = [(phase, copy.deepcopy(response)) for phase, response in script]
        self._cursor = 0
        self._session = RetailToolSession(copy.deepcopy(initial_db))
        self._runtime = ToolRuntime(
            evidence,
            build_tool_bindings(bridge, self._session),
        )

    async def __call__(self, request: Any) -> dict[str, Any]:
        self.requests.append(request)
        if self._cursor >= len(self._script):
            raise RuntimeError("script exhausted before episode termination")
        expected_phase, response = self._script[self._cursor]
        self._cursor += 1
        if request.phase_id != expected_phase:
            raise RuntimeError(
                f"script expected phase {expected_phase!r}, got {request.phase_id!r}"
            )
        if request.phase_id != "assistant_turn":
            return response

        messages = response.get("messages")
        if not isinstance(messages, list):
            return response
        executions: list[dict[str, Any]] = []
        executed_messages: list[dict[str, Any]] = []
        upstream_step_count = request.observation["upstream_step_count"]
        num_tool_errors = request.observation["num_tool_errors"]
        max_steps = request.observation["max_steps"]
        terminated_after_tools = False
        for message in messages:
            if not isinstance(message, Mapping):
                continue
            tool_calls = message.get("tool_calls")
            if not isinstance(tool_calls, list):
                executed_messages.append(message)
                upstream_step_count += 1
                break
            executed_messages.append(message)
            # Participant tool-call delivery. Upstream intentionally skips
            # termination checks while routing to ENV.
            upstream_step_count += 1
            for tool_call in tool_calls:
                result, record = await self._runtime.invoke(
                    action_attempt_id=request.logical_action_id,
                    tool_id=tool_call["name"],
                    arguments=tool_call["arguments"],
                )
                executions.append(
                    {
                        "tool_call_id": tool_call.get("id", ""),
                        "name": tool_call["name"],
                        "arguments": copy.deepcopy(tool_call["arguments"]),
                        "result": copy.deepcopy(result),
                        "post_db_hash": self.bridge.hash_db(self._session.get_db()),
                        "invocation_record_id": record.tool_invocation_id,
                    }
                )
                if result["error"]:
                    num_tool_errors += 1
            # One ENV hop covers the whole list of calls in this message.
            upstream_step_count += 1
            if upstream_step_count >= max_steps or num_tool_errors >= MAX_TOOL_ERRORS:
                terminated_after_tools = True
                break
        response["messages"] = executed_messages
        response["tool_executions"] = executions
        response["terminated_after_tools"] = terminated_after_tools
        return response

    @property
    def exhausted(self) -> bool:
        return self._cursor == len(self._script)


class Tau3RetailJsonHarness:
    id = "tau3_retail_json"
    version = "1.0"
    requires = HarnessRequirements(
        provider=frozenset({"structured_output"}),
        tools="declared",
        memory=frozenset({"disabled"}),
        owns_retries=False,
        owns_tools=False,
        replayable=True,
        blocking=False,
        spawns_subagents=False,
    )

    def __init__(self, *, bridge: Tau2Bridge, session: RetailToolSession) -> None:
        self.bridge = bridge
        self.session = session

    async def open_episode(self, episode: Any) -> None:
        return None

    async def close_episode(self, episode: Any) -> None:
        return None

    def classify_failure(self, exc: BaseException) -> FailureCondition:
        if isinstance(exc, (ProviderFailure, ToolFailure)):
            return FailureCondition(exc.condition, retryable=exc.retryable)
        return FailureCondition("harness_error", retryable=False)

    def state_reader(self) -> Any:
        return None

    @staticmethod
    def _request_message(request: Any) -> CanonicalMessage:
        observation = request.observation
        if request.phase_id == "assistant_turn" and isinstance(observation, Mapping):
            static_keys = (
                "policy",
                "policy_sha256",
                "tool_schema_sha256",
                "tools",
            )
            static_context = {
                key: observation[key] for key in static_keys if key in observation
            }
            turn_observation = {
                key: value for key, value in observation.items() if key not in static_context
            }
            turn_context = {
                "phase_id": request.phase_id,
                "seat_id": request.seat_id,
                "role": request.role,
                "observation_schema": request.observation_schema,
                "action_schema": request.action_schema,
                "observation": turn_observation,
            }
            content = (
                "STATIC_CONTEXT\n"
                + canonical_json_bytes(static_context).decode("utf-8")
                + "\nTURN_CONTEXT\n"
                + canonical_json_bytes(turn_context).decode("utf-8")
            )
        else:
            content = canonical_json_bytes(
                {
                    "phase_id": request.phase_id,
                    "seat_id": request.seat_id,
                    "role": request.role,
                    "observation_schema": request.observation_schema,
                    "action_schema": request.action_schema,
                    "observation": observation,
                }
            ).decode("utf-8")
        return CanonicalMessage(
            role="user",
            content=content,
        )

    @staticmethod
    def _decode(text: str) -> Mapping[str, Any]:
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            raise ProviderFailure(
                "malformed_structured_output",
                "tau3 retail response is not valid JSON",
                retryable=False,
            ) from error
        if not isinstance(value, Mapping):
            raise ProviderFailure(
                "malformed_structured_output",
                "tau3 retail response must be an object",
                retryable=False,
            )
        return value

    async def act(self, request: Any, ctx: AttemptContext) -> HarnessOutput:
        messages = (self._request_message(request),)
        if request.phase_id == "user_turn":
            turn = await ctx.model.complete(messages=messages, response_mode="json_dialect")
            value = self._decode(turn.text or "")
            if value.get("kind") != "reply" or not isinstance(value.get("text"), str):
                raise ProviderFailure(
                    "malformed_structured_output",
                    "tau3 retail user response must be a reply",
                    retryable=False,
                )
            return HarnessOutput(
                action={"content": value["text"]},
                claimed_tool_calls=(),
                rounds_used=1,
                notes={},
            )

        if request.phase_id != "assistant_turn":
            raise ProviderFailure(
                "harness_contract",
                f"unsupported tau3 retail phase {request.phase_id!r}",
                retryable=False,
            )
        if ctx.tools is None:
            raise ToolFailure(
                "tools_not_admitted",
                "tau3 retail assistant requires its declared tool runtime",
                retryable=False,
            )

        action_messages: list[dict[str, Any]] = []
        executions: list[dict[str, Any]] = []
        claimed: list[ClaimedToolCall] = []
        rounds_used = 0
        while rounds_used < ctx.budget.rounds_left:
            turn = await ctx.model.complete(
                messages=messages,
                response_mode="json_dialect",
            )
            rounds_used += 1
            value = self._decode(turn.text or "")
            if value.get("kind") == "reply":
                text = value.get("text")
                if not isinstance(text, str) or not text.strip():
                    raise ProviderFailure(
                        "malformed_structured_output",
                        "tau3 retail assistant reply must be non-empty",
                        retryable=False,
                    )
                action_messages.append(
                    {"role": "assistant", "content": text, "tool_calls": None}
                )
                return HarnessOutput(
                    action={
                        "messages": action_messages,
                        "tool_executions": executions,
                        "terminated_after_tools": False,
                    },
                    claimed_tool_calls=tuple(claimed),
                    rounds_used=rounds_used,
                    notes={},
                )
            calls = value.get("calls")
            if value.get("kind") != "tool_calls" or not isinstance(calls, list) or not calls:
                raise ProviderFailure(
                    "malformed_structured_output",
                    "tau3 retail assistant must return a reply or non-empty tool_calls",
                    retryable=False,
                )
            normalized_calls: list[dict[str, Any]] = []
            feedback: list[dict[str, Any]] = []
            for index, call in enumerate(calls):
                if not isinstance(call, Mapping):
                    raise ProviderFailure(
                        "malformed_structured_output",
                        "tau3 retail tool call must be an object",
                        retryable=False,
                    )
                call_id = call.get("id")
                name = call.get("name")
                arguments = call.get("arguments")
                if (
                    not isinstance(call_id, str)
                    or not call_id
                    or not isinstance(name, str)
                    or not name
                    or not isinstance(arguments, Mapping)
                ):
                    raise ProviderFailure(
                        "malformed_structured_output",
                        "tau3 retail tool call fields are invalid",
                        retryable=False,
                    )
                envelope = await ctx.tools.invoke(
                    tool_id=name,
                    arguments=arguments,
                    source_provider_call_id=turn.provider_call_id,
                    source_call_index=index,
                )
                plain_arguments = json.loads(canonical_json_bytes(arguments))
                plain_result = json.loads(canonical_json_bytes(envelope.result))
                normalized_calls.append(
                    {"id": call_id, "name": name, "arguments": plain_arguments}
                )
                executions.append(
                    {
                        "tool_call_id": call_id,
                        "name": name,
                        "arguments": plain_arguments,
                        "result": plain_result,
                        "post_db_hash": self.bridge.hash_db(self.session.get_db()),
                        "invocation_record_id": envelope.invocation_record.tool_invocation_id,
                    }
                )
                claimed.append(
                    ClaimedToolCall(
                        tool_id=name,
                        source_provider_call_id=turn.provider_call_id,
                        source_call_index=index,
                    )
                )
                feedback.append(
                    {"call_id": call_id, "name": name, "result": plain_result}
                )
            action_messages.append(
                {"role": "assistant", "content": None, "tool_calls": normalized_calls}
            )
            messages = messages + (
                CanonicalMessage(
                    role="user",
                    content=canonical_json_bytes({"tool_results": feedback}).decode("utf-8"),
                ),
            )
        raise ProviderFailure(
            "rounds_exhausted",
            f"tau3 retail assistant exceeded {ctx.budget.rounds_left} model rounds",
            retryable=False,
        )


__all__ = ["ScriptedTau3RetailHarness", "Tau3RetailJsonHarness"]
