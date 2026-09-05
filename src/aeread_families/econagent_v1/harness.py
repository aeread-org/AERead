"""Provider-free scripted response source for econagent_v1 integration tests.

Per ``docs/econagent_adapter_spec.md``'s milestone-1 correction 4, every
``agent_i`` seat's declared action this pass is a trivial acknowledgment
(``econagent_v1_month_ack_v1``) regardless of its own observation -- the real
``[labor, consumption]`` decision is computed once per month, for every agent
at once, inside the persistent bridge session ``environment.py``'s ``step()``
already drives. Unlike ``ScriptedTau3RetailHarness`` (which executes real
tool calls through a ``ToolRuntime`` and records delegated evidence for
``step()`` to cross-check), there is no tool/action content here to
interpret or delegate: this harness is the minimal provider-free
``ResponseSource`` the real scheduler (``run_episode``) needs to drive an
econagent_v1 episode end-to-end through the REAL shared-runner path -- every
request gets the exact same acknowledgment, in call order, with no model,
no tool, and no per-seat branching.
"""
from __future__ import annotations

from typing import Any

from .environment import AGENT_MONTH_PHASE

# The one action every seat ever submits this pass (spec milestone-1
# correction 4) -- a plain dict, never a frozen/shared mutable default, so
# each response handed back to the scheduler is independently detachable.
ACK_RESPONSE: dict[str, Any] = {"acknowledge": True}


class ScriptedEconAgentHarness:
    """Serve the fixed month acknowledgment for every agent seat, every month.

    Records every ``DecisionRequest`` it serves (``self.requests``, in call
    order) purely for test-side audit -- mirrors ``ScriptedTau3RetailHarness``'s
    ``self.requests`` bookkeeping, without any of its tool-execution
    machinery, which this family has no equivalent of this pass.
    """

    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def __call__(self, request: Any) -> dict[str, Any]:
        self.requests.append(request)
        if request.phase_id != AGENT_MONTH_PHASE:
            raise RuntimeError(
                f"ScriptedEconAgentHarness only serves phase {AGENT_MONTH_PHASE!r}, "
                f"got {request.phase_id!r}"
            )
        if not request.seat_id.startswith("agent_"):
            raise RuntimeError(
                f"ScriptedEconAgentHarness only serves agent seats, got {request.seat_id!r}"
            )
        return dict(ACK_RESPONSE)

    @property
    def call_count(self) -> int:
        return len(self.requests)


__all__ = ["ACK_RESPONSE", "ScriptedEconAgentHarness"]
