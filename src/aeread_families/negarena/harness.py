"""Provider-free scripted response source for negarena integration tests
(spec section 5, "tau3's ScriptedTau3RetailHarness is the pattern").

Negarena's Mode B phase graph declares ``needs_tools: False``
(``environment.py``'s ``family_manifest``): every parse/legality/settlement
call already delegates to :class:`~aeread_families.negarena.negarena_bridge.NegarenaBridge`
from *inside* ``NegarenaPlugin``'s own hooks (``parse_action``, ``legal``,
``build_scorer`` -> ``measurement.score_seat_outcome``) -- never from a
harness-owned :class:`~aeread.shared_runner.task.tools.ToolRuntime`. So unlike
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

from aeread.shared_runner.task.execution import EvidenceStore
from aeread.shared_runner.task.scheduler import EpisodeResult, run_episode


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


def record_full_evidence_lifecycle(
    *, evidence: EvidenceStore, plugin: Any, family_case: Mapping[str, Any], result: EpisodeResult
) -> None:
    """Seal one already-completed episode's full generic evidence lifecycle.

    ``ScriptedNegarenaHarness`` (this module) only ever appends its own
    ``negarena_decision_served`` event -- it is a ``response_source``, and
    ``run_episode`` never hands a ``response_source`` the phase/parse/
    legality/transition/terminal/outcome facts it computes internally, so
    there was nothing for the harness to record them from *during* serving
    (docs/negarena_codex_triage.md Finding 3). Those facts already exist,
    completely and correctly, on the ``EpisodeResult`` the scheduler returns
    once the episode finishes; this function's only job is to translate that
    already-computed result into the same durable event types/payloads the
    shared kernel's own ``MinimalChatExecutor`` (``aeread.shared_runner.execution``)
    would have appended live, so ``family_evaluation.replay_family_state`` --
    the same generic replay ``finalize_family_execution``/
    ``replay_family_receipt``/``audit_family_receipt`` all use -- can read
    this evidence back exactly like any other family's. It recomputes
    nothing: every payload below is either taken verbatim from ``result`` or
    is the record's own already-produced ``ParseResult``/``LegalityResult``/
    ``TransitionResult``.

    Call once, after ``run_episode`` returns a terminated ``EpisodeResult``,
    against the same ``EvidenceStore`` the harness used to serve decisions.
    """
    phase_by_id = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    for instance in result.phase_instances:
        evidence.append_event(
            "phase_instance_started",
            {
                "phase": phase_by_id[instance.phase_id],
                "eligible_actors": instance.eligible_actors,
                "pre_state_sha256": instance.pre_state_sha256,
            },
            phase_instance_id=instance.phase_instance_id,
        )
        for action in instance.actions:
            evidence.append_event(
                "logical_action_started",
                {"profile_id": action.request.profile_id, "request": action.request},
                phase_instance_id=instance.phase_instance_id,
                logical_action_id=action.logical_action_id,
                visibility=f"seat:{action.seat_id}",
            )
            envelope = action.envelope
            evidence.append_event(
                "action_parsed",
                {"parse_result": envelope.parse},
                phase_instance_id=instance.phase_instance_id,
                logical_action_id=action.logical_action_id,
                visibility=f"seat:{action.seat_id}",
            )
            if envelope.legality is not None:
                evidence.append_event(
                    "action_legality_checked",
                    {"legality_result": envelope.legality},
                    phase_instance_id=instance.phase_instance_id,
                    logical_action_id=action.logical_action_id,
                )
            failure_code = None
            if not envelope.valid:
                failure_code = (
                    envelope.parse.error_code
                    if not envelope.parse.ok
                    else envelope.legality.reason
                )
            event_type = (
                "logical_action_succeeded"
                if envelope.valid
                else "logical_action_agent_action_failure"
            )
            evidence.append_event(
                event_type,
                {"valid": envelope.valid, "failure_code": failure_code},
                logical_action_id=action.logical_action_id,
            )
        for transition in instance.transitions:
            evidence.append_event(
                "transition_applied",
                {
                    "phase_id": instance.phase_id,
                    "transition": transition,
                    "post_state_sha256": instance.post_state_sha256,
                },
                phase_instance_id=instance.phase_instance_id,
            )
    evidence.append_event(
        "episode_terminated",
        {"terminal": result.terminal, "logical_action_count": result.logical_action_count},
    )
    evidence.append_event("family_outcome_recorded", {"outcome": result.outcome})


async def run_scripted_negarena_episode(
    *,
    cell: Any,
    case: Any,
    plugin: Any,
    evidence: EvidenceStore,
    script: Sequence[tuple[str, str, Mapping[str, Any]]],
) -> EpisodeResult:
    """Drive one scripted episode through the real scheduler and seal the
    complete generic evidence lifecycle before returning.

    This is the one production entry point this adapter ships for driving a
    ``ScriptedNegarenaHarness``-served episode toward
    ``aeread.shared_runner.task.evaluation.finalize_family_execution``.
    Before this function existed, reaching that call site required a caller
    to remember two separate steps -- drive ``run_episode`` with a
    ``ScriptedNegarenaHarness``, *then* separately call
    ``record_full_evidence_lifecycle`` -- and nothing enforced the second
    step; the only place that ever actually made that call was a test
    module's own helper, not production code
    (docs/negarena_codex_triage.md Finding 3, closed for real in
    docs/negarena_fix_verification.md). Any caller that reaches a
    terminated episode through this function instead has the complete
    lifecycle sealed by construction, not by remembering a second call.
    """
    scripted = ScriptedNegarenaHarness(evidence=evidence, script=script)
    result = await run_episode(cell=cell, case=case, plugin=plugin, response_source=scripted)
    if not scripted.exhausted:
        raise RuntimeError(
            "scripted negarena episode terminated before the script was exhausted"
        )
    family_case = plugin.validate_payload(case.payload)
    record_full_evidence_lifecycle(
        evidence=evidence, plugin=plugin, family_case=family_case, result=result
    )
    return result


__all__ = [
    "ScriptedNegarenaHarness",
    "record_full_evidence_lifecycle",
    "run_scripted_negarena_episode",
]
