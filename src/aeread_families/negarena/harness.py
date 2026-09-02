"""Provider-free scripted response source for negarena integration tests
(spec section 5, "tau3's ScriptedTau3RetailHarness is the pattern").

Negarena's Mode B phase graph declares ``needs_tools: False``
(``environment.py``'s ``family_manifest``): every parse/legality/settlement
call already delegates to :class:`~aeread_families.negarena.negarena_bridge.NegarenaBridge`
from *inside* ``NegarenaPlugin``'s own hooks (``parse_action``, ``legal``,
``build_scorer`` -> ``measurement.score_seat_outcome``) -- never from a
harness-owned :class:`~aeread.shared_runner.tools.ToolRuntime`. So unlike
``ScriptedTau3RetailHarness`` (which drives ``ToolRuntime`` to *produce*
fresh tool evidence for every assistant turn), this harness executes no
tool at all; its only job is to serve one scripted raw response per
phase/seat, in the exact order the real scheduler (``run_episode``) asks
for one.

It still accepts an ``EvidenceStore`` and records one durable event per
served decision (spec section 3: "canonical events, visibility, evidence,
replay, and receipts ... unchanged from the portability contract" is
AERead-owned regardless of whether a family has tools) -- so a negarena
episode driven through the real scheduler produces genuinely sealed,
auditable evidence exactly like every other family, even though there is no
``ToolRuntime`` here to generate that evidence automatically.

Each recorded event is tagged with ``phase_instance_id`` only, deliberately
never with ``logical_action_id``/``action_attempt_id``/``provider_call_id``/
``tool_invocation_id``: those four identity fields drive
``EvidenceStore.audit_reconciliation``'s started/terminal pairing check
(``"logical_action_started"``/``"..._succeeded"`` etc.), a convention this
single, unpaired ``negarena_decision_served`` event type does not
participate in and must not be miscounted against.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from aeread.shared_runner.execution import EvidenceStore


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


class ScriptedNegarenaHarness:
    """Serve a fixed, ordered ``(phase_id, seat_id, response)`` script.

    Each entry is matched strictly, in order, against the scheduler's own
    ``DecisionRequest`` -- a phase/seat mismatch is a scripting bug in the
    caller (mirrors ``ScriptedTau3RetailHarness``'s identical phase-mismatch
    check), never a normal in-band condition.
    """

    def __init__(
        self,
        *,
        evidence: EvidenceStore,
        script: Sequence[tuple[str, str, Mapping[str, Any]]],
    ) -> None:
        self.evidence = evidence
        self.requests: list[Any] = []
        self._script = tuple(
            (phase_id, seat_id, _plain(response))
            for phase_id, seat_id, response in script
        )
        self._cursor = 0

    async def __call__(self, request: Any) -> dict[str, Any]:
        self.requests.append(request)
        if self._cursor >= len(self._script):
            raise RuntimeError("script exhausted before episode termination")
        expected_phase, expected_seat, response = self._script[self._cursor]
        self._cursor += 1
        if request.phase_id != expected_phase or request.seat_id != expected_seat:
            raise RuntimeError(
                "script expected "
                f"phase={expected_phase!r} seat={expected_seat!r}, got "
                f"phase={request.phase_id!r} seat={request.seat_id!r}"
            )
        served = copy.deepcopy(response)
        self.evidence.append_event(
            "negarena_decision_served",
            {
                "phase_id": request.phase_id,
                "seat_id": request.seat_id,
                "response": served,
            },
            phase_instance_id=request.phase_instance_id,
        )
        return served

    @property
    def exhausted(self) -> bool:
        return self._cursor == len(self._script)


__all__ = ["ScriptedNegarenaHarness"]
