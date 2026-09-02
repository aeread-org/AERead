"""Provider-free scripted response source for amazonbarg.bilateral integration tests.

Mirrors ``tau3_retail``'s own ``ScriptedTau3RetailHarness`` (spec section 3,
milestone 3: "mirroring `tau3_retail`'s own `harness.py`/`parity.py`/
`replay.py` split"), with one structural simplification driven by a real
difference in the two benchmarks: amazonbarg has **no tool-calling surface
at all** (spec "Governing facts" -- every turn is one free-text reply parsed
by a fixed regex grammar, never a tool call), so there is no ``ToolRuntime``
to drive and no per-call tool evidence to record. What this harness still
owes the real shared-runner path is exactly what ``ScriptedTau3RetailHarness``
owes it:

1. serving a fixed, ordered script of buyer/seller replies strictly through
   the real ``DecisionRequest``/``ResponseSource`` contract -- i.e. driven by
   the genuine kernel scheduler (``run_episode``), never a hand-wired
   shortcut around it;
2. sealing a durable, hash-chained ``EvidenceStore`` -- one event per served
   decision -- so a later offline replay (``replay.py``) can be built and
   verified against a genuinely durable, auditable record rather than only
   an in-memory ``EpisodeResult``.

The seal itself is applied from the scheduler's own ``episode_completed``
lifecycle callback (``scheduler.py``'s ``_notify_lifecycle``, invoked
automatically by ``run_episode`` once its terminal loop produces a result --
see that module's own docstring on ``ResponseSource``'s optional lifecycle
hooks), so the seal genuinely covers every decision this harness served and
nothing served after it.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from aeread.shared_runner.execution import EvidenceStore

EVENT_TYPE_DECISION_SERVED = "amazonbarg_decision_served"


class ScriptedAmazonbargHarness:
    """Serve a fixed ordered script of buyer/seller replies, sealing evidence.

    ``script`` is an ordered sequence of ``(phase_id, seat_id, response)``
    triples. Both the phase and the seat are checked explicitly against the
    incoming ``DecisionRequest`` -- unlike ``tau3_retail`` (one seat,
    ``assistant``, ever produces a scripted action), amazonbarg alternates
    strictly between two testable seats (``buyer``, ``seller``), so a script
    entry that would serve the wrong seat's turn is exactly the bug this
    check exists to catch immediately, never silently.
    """

    def __init__(
        self,
        *,
        evidence: EvidenceStore,
        script: Sequence[tuple[str, str, Mapping[str, Any]]],
    ) -> None:
        self.evidence = evidence
        self.requests: list[Any] = []
        self._script = [
            (phase, seat, copy.deepcopy(response)) for phase, seat, response in script
        ]
        self._cursor = 0
        self._sealed = False

    async def __call__(self, request: Any) -> dict[str, Any]:
        self.requests.append(request)
        if self._cursor >= len(self._script):
            raise RuntimeError("script exhausted before episode termination")
        expected_phase, expected_seat, response = self._script[self._cursor]
        self._cursor += 1
        if request.phase_id != expected_phase or request.seat_id != expected_seat:
            raise RuntimeError(
                f"script expected phase={expected_phase!r} seat={expected_seat!r}, "
                f"got phase={request.phase_id!r} seat={request.seat_id!r}"
            )
        served = copy.deepcopy(response)
        self.evidence.append_event(
            EVENT_TYPE_DECISION_SERVED,
            {
                "phase_id": request.phase_id,
                "seat_id": request.seat_id,
                "logical_action_id": request.logical_action_id,
                "response": served,
            },
            phase_instance_id=request.phase_instance_id,
            logical_action_id=request.logical_action_id,
        )
        return served

    async def episode_completed(self, *, episode_result: Any) -> None:
        """``run_episode``'s own terminal lifecycle callback: seal evidence.

        Called automatically once, after ``run_episode``'s loop has produced
        a terminal ``EpisodeResult`` (see ``scheduler.py``'s own
        ``_notify_lifecycle`` calls) -- never invoked by test code directly,
        so the seal always covers exactly the decisions actually served.
        """
        del episode_result
        if not self._sealed:
            self.evidence.seal()
            self._sealed = True

    @property
    def exhausted(self) -> bool:
        return self._cursor == len(self._script)

    @property
    def sealed(self) -> bool:
        return self._sealed


__all__ = ["EVENT_TYPE_DECISION_SERVED", "ScriptedAmazonbargHarness"]
