"""Provider-free scripted response source for tau3.retail integration tests."""
from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from aeread.shared_runner.task.execution import EvidenceStore
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


__all__ = ["ScriptedTau3RetailHarness"]
