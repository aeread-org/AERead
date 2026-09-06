"""Provider-free scripted response source for govsim integration tests.

Mirrors ``tau3_retail``'s ``ScriptedTau3RetailHarness`` (spec section 5's
"scripted harness" mention): a ``response_source`` implementing the real
kernel-facing protocol required by
``aeread.shared_runner.task.scheduler.run_episode`` (``request.phase_id``/
``request.seat_id``/``request.observation`` in, a raw response dict out) --
the same code path a live model-backed run would use, never the ad hoc loop
``tests/test_govsim_measurement.py``'s ``_drive_episode`` used for milestones
1-2's goldens (that helper calls ``GovsimPlugin``'s hooks directly and never
exercises the scheduler's own budget checks, envelope construction, or state
hashing at all).

Unlike ``ScriptedTau3RetailHarness`` (which drives a ``ToolRuntime`` to
execute and record external tool calls mid-response), this family submits no
external tool calls whatsoever: every response is a plain, native
``{"quantity": int}`` (``harvest``) or ``{}`` (``discuss``/``reflect``)
action dict, computed directly from ``policies.py``'s pure scripted-policy
functions applied to the scheduler-frozen ``request.observation`` --
"native phase actions, no external tool loop, matching housing_v1" (spec
section 7's "Operational-failure handling" note). There is therefore no
``ToolRuntime``/``EvidenceStore`` dependency the way ``tau3_retail``'s
harness has one baked in; an ``EvidenceStore`` is instead accepted here as
an OPTIONAL parameter so a caller can still get a genuinely sealed evidence
chain for a scripted run (one event per completed logical action, via the
scheduler's own ``finalize_action`` lifecycle hook -- see
``aeread.shared_runner.task.scheduler._notify_action_result``), without forcing
every caller (e.g. a pure structural test) to provision one.
"""
from __future__ import annotations

from typing import Any, Mapping

from aeread.shared_runner.task.execution import EvidenceStore

from . import policies
from .environment import DISCUSS_PHASE, HARVEST_PHASE, REFLECT_PHASE


class ScriptedGovsimHarness:
    """Serve scripted-policy responses through the REAL scheduler path.

    ``policy_assignment`` is exactly the case payload's own
    ``policy_assignment`` (seat id -> scripted policy id, e.g.
    ``{"persona_0": "sustainable_v1", ...}``); every ``harvest``-phase
    request is answered by applying that seat's assigned
    ``policies.SCRIPTED_POLICIES`` function to the request's own observation
    -- never a fixed, finite list of pre-baked responses the way
    ``ScriptedTau3RetailHarness``'s ``script`` is, since a govsim episode's
    length (number of rounds) is not known ahead of time and a policy is a
    pure function of whatever observation the scheduler hands it.
    """

    def __init__(
        self,
        *,
        policy_assignment: Mapping[str, str],
        evidence: EvidenceStore | None = None,
    ) -> None:
        self._policy_assignment = dict(policy_assignment)
        self._evidence = evidence
        self.requests: list[Any] = []

    async def __call__(self, request: Any) -> dict[str, Any]:
        self.requests.append(request)
        if request.phase_id == HARVEST_PHASE:
            policy_id = self._policy_assignment[request.seat_id]
            policy = policies.SCRIPTED_POLICIES[policy_id]
            quantity = policy(request.observation)
            return {"quantity": int(quantity)}
        if request.phase_id == DISCUSS_PHASE:
            # A scripted utterance that states the policy the seat is
            # following, so a scripted baseline exercises the same
            # content-carrying action a live persona does.
            policy_id = self._policy_assignment.get(request.seat_id, "sustainable_v1")
            return {
                "message": (
                    f"I am following the {policy_id} policy and will take my "
                    "share accordingly."
                )
            }
        if request.phase_id == REFLECT_PHASE:
            return {"reflection": ""}
        raise RuntimeError(
            f"ScriptedGovsimHarness has no response for phase {request.phase_id!r}"
        )

    async def finalize_action(self, record: Any) -> None:
        """Append one sealed-evidence event per completed logical action.

        Only fires when an ``EvidenceStore`` was supplied -- optional,
        mirroring ``tau3_retail``'s convention of never requiring evidence
        plumbing from a caller that does not need it (e.g. a pure
        structural test). The recorded payload is exactly what this seat
        was asked and what it answered -- never a tool result (this family
        has none) -- so a sealed evidence generation for a govsim run is a
        genuine, independently verifiable per-decision ledger, not an
        artifact of a tool-call side channel that does not exist here.
        """
        if self._evidence is None:
            return
        self._evidence.append_event(
            "govsim_logical_action_completed",
            {
                "phase_id": record.request.phase_id,
                "seat_id": record.seat_id,
                "response": record.response,
                "valid": record.envelope.valid,
            },
            phase_instance_id=record.request.phase_instance_id,
            logical_action_id=record.logical_action_id,
        )


__all__ = ["ScriptedGovsimHarness"]
