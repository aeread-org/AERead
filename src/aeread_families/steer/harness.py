"""Provider-free scripted response source for steer integration tests.

Mode A (docs/steer_adapter_spec.md section 1): a single agent, one phase, one
logical action, no environment, no tools, no counterpart seat. Unlike
``aeread_families.tau3_retail.harness.ScriptedTau3RetailHarness`` -- which
drives a live ``ToolRuntime`` because tau3.retail's assistant turn issues
mutating tool calls -- this harness has no tool loop to drive at all: its
only job is to serve the one scripted answer this family's single phase ever
asks for, and to record that decision -- and, via :meth:`ScriptedSteerHarness
.record_score`, the score computed from it -- as durable, sealed evidence
events (``EvidenceSeal``, ``docs/shared_runner_portability_contract.md``
section 2), so a harness-driven run's seal is genuinely auditable as a
*scored* episode, not merely "some text was served" (docs/steer_codex_triage
.md finding 8), even though this family owns no tool evidence of its own.
"""
from __future__ import annotations

from typing import Any, Sequence

from aeread.shared_runner.execution import EvidenceStore, Event
from aeread.shared_runner.measurement import ScoreEnvelope


class ScriptedSteerHarness:
    """Serve a fixed ordered script of raw answer texts through the REAL
    kernel scheduler (``run_episode``), recording each served decision as a
    sealed evidence event.

    ``script`` is an ordered sequence of ``(phase_id, response_text)``
    pairs -- for this family's one-shot ``answer_question`` phase, exactly
    one entry: the raw text the scheduler hands to ``parse_action`` (a
    well-formed ``'{"option_id": <n>}'`` for a passing/failing golden, an
    out-of-range option_id for golden 3, or free-text prose for golden 4).
    Mirrors ``ScriptedTau3RetailHarness``'s ``requests``/``exhausted``
    bookkeeping contract exactly, so both families' harnesses are driven the
    same way by their respective test suites.
    """

    def __init__(
        self,
        *,
        evidence: EvidenceStore,
        script: Sequence[tuple[str, str]],
    ) -> None:
        self.evidence = evidence
        self.requests: list[Any] = []
        self._script = list(script)
        self._cursor = 0
        self.submission_events: list[Event] = []

    async def __call__(self, request: Any) -> str:
        self.requests.append(request)
        if self._cursor >= len(self._script):
            raise RuntimeError("script exhausted before episode termination")
        expected_phase, response_text = self._script[self._cursor]
        self._cursor += 1
        if request.phase_id != expected_phase:
            raise RuntimeError(
                f"script expected phase {expected_phase!r}, got {request.phase_id!r}"
            )
        observation = request.observation
        event = self.evidence.append_event(
            "steer_answer_submitted",
            {
                "element": observation.get("element"),
                "options_count": len(observation.get("options", ())),
                "response_text": response_text,
            },
            phase_instance_id=request.phase_instance_id,
            logical_action_id=request.logical_action_id,
        )
        self.submission_events.append(event)
        return response_text

    def record_score(self, score: ScoreEnvelope) -> Event:
        """Append a durable ``score_recorded`` event for the most recently
        submitted answer -- must be called after the episode has terminated
        and been scored, and before ``self.evidence.seal()``.

        Mirrors ``aeread.shared_runner.family_evaluation
        .finalize_family_execution``'s own ``score_recorded`` event shape
        exactly (``primary_leaf_id``/``outcome_event_id``/``score``), so a
        harness-driven run's sealed evidence certifies the same claim
        production finalization does: not just "this raw text was served,"
        but "this outcome was scored as X" (docs/steer_codex_triage.md
        finding 8). Without a prior call to this method, ``self.evidence
        .seal()`` seals only the raw submission -- never the score.
        """
        if not self.submission_events:
            raise RuntimeError("record_score called before any answer was submitted")
        outcome_event = self.submission_events[-1]
        return self.evidence.append_event(
            "score_recorded",
            {
                "primary_leaf_id": score.leaf.leaf_id,
                "outcome_event_id": outcome_event.event_id,
                "score": score,
            },
        )

    @property
    def exhausted(self) -> bool:
        return self._cursor == len(self._script)


__all__ = ["ScriptedSteerHarness"]
