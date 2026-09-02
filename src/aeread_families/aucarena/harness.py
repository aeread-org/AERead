"""Provider-free scripted response source for ``aucarena`` integration tests
and scripted evaluation runs (``docs/aucarena_adapter_spec.md`` section 4/6).

Milestone 1 (``tests/test_aucarena_environment.py``) defined this class
in-test, deliberately, because every decision slot in this family is "one
seat's raw bid text" with no tool loop -- a five-line scripted policy
function was enough and no shipped module was needed yet (see that spec
section's own milestone-1 note). Milestone 3 promotes it here, unchanged in
behavior, for two reasons a test-local class cannot give:

1. It is now the one real, reusable ``ResponseSource`` any provider-free
   scripted evaluation run against this family drives through -- not a
   fixture private to one test module -- mirroring
   ``tau3_retail.harness.ScriptedTau3RetailHarness``.
2. It can optionally record every served decision into a real
   ``EvidenceStore`` (``evidence`` is ``None`` by default, so every existing
   milestone-1/2 call site -- which never passed one -- is unaffected). This
   is the sealed, tamper-evident, hash-chained log this family's own harness
   never had before: each request/response pair becomes one
   ``bid_decision_served`` event, keyed by the same ``phase_instance_id``/
   ``logical_action_id`` the kernel scheduler itself assigned. Unlike tau3
   (whose evidence covers delegated tool executions this family has none
   of), the thing worth sealing here is the raw decision itself -- the only
   externally-supplied input this family's environment ever consumes.
"""
from __future__ import annotations

from typing import Any, Callable

from aeread.shared_runner.execution import EvidenceStore
from aeread.shared_runner.scheduler import DecisionRequest

Policy = Callable[[str, Any], str]


class ScriptedAucArenaHarness:
    """Minimal provider-free ``ResponseSource``: one text policy per seat_id.

    A "rule" seat's raw response is accepted but never inspected by
    ``parse_action`` (its bid is computed internally from the vendored
    ``bid_rule``), so this harness always returns ``""`` for any seat the
    policy does not recognize -- the same contract upstream's own
    ``Bidder.bid()`` short-circuit has for ``model_name == "rule"``.
    """

    def __init__(self, policy: Policy, *, evidence: EvidenceStore | None = None) -> None:
        self._policy = policy
        self._evidence = evidence
        self.requests: list[DecisionRequest] = []

    async def __call__(self, request: DecisionRequest) -> str:
        self.requests.append(request)
        response = self._policy(request.seat_id, request.observation)
        if self._evidence is not None:
            self._evidence.append_event(
                "bid_decision_served",
                {
                    "phase_id": request.phase_id,
                    "seat_id": request.seat_id,
                    "response": response,
                },
                phase_instance_id=request.phase_instance_id,
                logical_action_id=request.logical_action_id,
                visibility=f"seat:{request.seat_id}",
            )
        return response


__all__ = ["Policy", "ScriptedAucArenaHarness"]
