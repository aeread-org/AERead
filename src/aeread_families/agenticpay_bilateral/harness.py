"""Provider-free scripted response source for agenticpay.bilateral integration tests.

Mirrors ``tau3_retail.harness.ScriptedTau3RetailHarness``'s constructor/``__call__``/
``exhausted`` shape as closely as this family's own real surface allows, with one
structural difference forced by ``docs/agenticpay_adapter_spec.md``'s own module layout,
not by any change of intent: this family declares no tool-call surface at all
(``tools.py``: "none -- no tool-call surface; both seats emit one action string per
turn"). Both seats' turns are plain negotiation-message strings, and it is
``environment.py``'s own ``step()`` -- not this harness -- that calls into the upstream
bridge (only the seller phase's ``step`` does so, once per completed round). So there is
nothing here for a ``ToolRuntime`` to execute or seal evidence for.

Instead, this harness seals every scripted decision it serves directly through
``EvidenceStore.append_event`` -- the same durable, hash-chained event-log primitive
``aeread.shared_runner.family_evaluation`` already uses for its own non-tool evidence
(``episode_terminated``/``family_outcome_recorded``/``score_recorded``). This gives each
served response an auditable, sealed record independent of the scheduler's own in-memory
``LogicalActionRecord`` -- exactly the property ``replay.py``'s ``record_episode``/
``RecordedResponseSource`` pair needs to exist for a later, genuinely offline replay, and
the property that makes "at least 2 full episodes ran through the real shared-runner path
with sealed evidence" a checkable claim rather than an assertion about in-memory state
alone.

``script`` is an ordered sequence of ``(phase_id, response)`` pairs: entry *i* answers the
*i*-th decision request the scheduler issues, alternating ``BUYER_PHASE``/``SELLER_PHASE``
per ``environment.py``'s own phase graph. Each ``response`` is exactly this family's own
action schema: ``{"message": <str>}``.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from aeread.shared_runner.execution import EvidenceStore


class ScriptedAgenticpayBilateralHarness:
    """Serve a fixed, ordered sequence of buyer/seller negotiation messages.

    Every served decision is sealed as one ``agenticpay_bilateral_decision_served``
    event on the supplied ``EvidenceStore`` before being returned to the scheduler,
    keyed by the phase instance and logical action the scheduler itself assigned it --
    so the sealed event log and the scheduler's own ``EpisodeResult.phase_instances``
    agree on ordering and identity by construction, not by convention alone.
    """

    def __init__(
        self,
        *,
        evidence: EvidenceStore,
        script: Sequence[tuple[str, Mapping[str, Any]]],
    ) -> None:
        self.evidence = evidence
        self.requests: list[Any] = []
        self._script = [(phase, copy.deepcopy(response)) for phase, response in script]
        self._cursor = 0

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
        sealed = copy.deepcopy(response)
        self.evidence.append_event(
            "agenticpay_bilateral_decision_served",
            {
                "phase_id": request.phase_id,
                "seat_id": request.seat_id,
                "response": sealed,
            },
            phase_instance_id=request.phase_instance_id,
            logical_action_id=request.logical_action_id,
        )
        return sealed

    @property
    def exhausted(self) -> bool:
        return self._cursor == len(self._script)


__all__ = ["ScriptedAgenticpayBilateralHarness"]
