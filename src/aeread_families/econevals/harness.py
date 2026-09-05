"""Provider-free scripted response source for econevals period-loop episodes.

Unlike tau3.retail's two-phase (``user_turn``/``assistant_turn``)
alternation, econevals has exactly one self-looping phase
(``environment.PERIOD_PHASE``): one ``DecisionRequest`` per period. This
harness serves a fixed, ordered script of per-period tool-call bursts --
never a live model call -- and executes every scripted call in list order
through the kernel ``ToolRuntime``, delegating each one to
``EconevalsPlugin.dispatch_read_only``/``dispatch_submit`` (spec section
3's own tool-body implementation, ``tools.build_tool_bindings``). ``step``
independently re-derives every result from its own FSM state and hard-fails
(``RuntimeError``) on any divergence (``environment.py``'s own tool-replay
cross-check) -- this harness never hand-types an expected result; every
recorded ``tool_executions`` entry here is the SAME dispatch call ``step``
itself will repeat, so the two can only ever agree by actually agreeing.

Mirrors ``tau3_retail.harness.ScriptedTau3RetailHarness``'s shape: an
internal cursor into ``script``, one ``ToolRuntime``-mediated execution
burst served per request, and a running mirror of in-episode state
(``tools.EconevalsToolSession``) that this harness itself advances between
periods (``session.advance_period``, spec section 3's ``advance_period``)
so the NEXT period's read-only responses (``get_attempt_number``,
``get_previous_*``) already reflect the previous period's submitted
attempt -- exactly as a live run would.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from aeread.shared_runner.task.execution import EvidenceStore
from aeread.shared_runner.task.tools import ToolRuntime

from .environment import PERIOD_PHASE, SEAT_ID, EconevalsPlugin
from .tools import EconevalsToolSession, build_tool_bindings


class ScriptedEconevalsHarness:
    """Serve a fixed per-period tool-call script and record sealed tool evidence.

    ``script`` is an ordered sequence of periods; each period is itself an
    ordered sequence of tool-call specs (``{"id", "name", "arguments"}``,
    ``"id"`` optional). The LAST call of every period must be the case's
    own track-declared submit tool, matching
    ``EconevalsPlugin.parse_action``'s own "submit tool must be the final
    call" rule -- this harness does not enforce that itself (``step``'s own
    replay/parse machinery already does, per request already produced by
    this harness), it only serves what the script says.
    """

    def __init__(
        self,
        *,
        plugin: EconevalsPlugin,
        family_case: Mapping[str, Any],
        evidence: EvidenceStore,
        script: Sequence[Sequence[Mapping[str, Any]]],
    ) -> None:
        self.plugin = plugin
        self.family_case = family_case
        self.evidence = evidence
        self.requests: list[Any] = []
        self._script = tuple(
            tuple(copy.deepcopy(dict(call)) for call in period) for period in script
        )
        self._cursor = 0
        self._session = EconevalsToolSession(plugin.initial_state(family_case, None))
        self._runtime = ToolRuntime(
            evidence, build_tool_bindings(plugin, family_case, self._session)
        )

    async def __call__(self, request: Any) -> dict[str, Any]:
        self.requests.append(request)
        if request.phase_id != PERIOD_PHASE or request.seat_id != SEAT_ID:
            raise RuntimeError(
                "ScriptedEconevalsHarness only serves the econevals period "
                f"phase/seat, got phase={request.phase_id!r} seat={request.seat_id!r}"
            )
        if self._cursor >= len(self._script):
            raise RuntimeError("script exhausted before episode termination")
        period_calls = self._script[self._cursor]
        self._cursor += 1

        tool_calls: list[dict[str, Any]] = []
        executions: list[dict[str, Any]] = []
        for index, call in enumerate(period_calls):
            call_id = call.get("id", str(index))
            name = call["name"]
            arguments = call["arguments"]
            tool_calls.append({"id": call_id, "name": name, "arguments": arguments})
            result, record = await self._runtime.invoke(
                action_attempt_id=request.logical_action_id,
                tool_id=name,
                arguments=arguments,
            )
            executions.append(
                {
                    "tool_call_id": call_id,
                    "name": name,
                    "arguments": copy.deepcopy(arguments),
                    "result": copy.deepcopy(result),
                    "invocation_record_id": record.tool_invocation_id,
                }
            )
        # One period's worth of tool calls is now sealed into evidence and
        # recorded in this response; mirror the SAME post-period advance
        # `step` itself applies, so the next period's read-only responses
        # already reflect this period's submitted attempt.
        self._session.advance_period(self.family_case)
        return {"tool_calls": tool_calls, "tool_executions": executions}

    @property
    def exhausted(self) -> bool:
        return self._cursor == len(self._script)


__all__ = ["ScriptedEconevalsHarness"]
