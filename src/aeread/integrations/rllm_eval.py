"""rLLM evaluator for AERead episodes (experimental).

Returns rLLM's native ``EvalOutput`` with named ``Signal`` objects rather
than a plain dict. ``reward`` stays raw episode AER (``w_real /
denominator``, negatives preserved) for GRPO. ``is_correct`` stays the
Boolean ``aer > 0.0`` for rLLM's built-in ``Accuracy`` display, but that
display is a compatibility diagnostic -- ``positive_welfare_rate`` -- never
AERead's benchmark headline. AERead's official aggregate pools welfare
numerator and denominator within a denominator tier; see
``aeread.integrations.pooled_aer`` and
``integrations/rllm/READINESS_PROPOSAL.md`` (Workstream 5).
"""
from __future__ import annotations

from typing import Any

import rllm
from rllm.eval.types import EvalOutput, Signal

from aeread.integrations.failure_taxonomy import EpisodeMeasurement
from aeread.integrations.gateway_candidate import CandidateTraceMismatch


def _assistant_content(step: Any) -> str | None:
    for message in reversed(step.chat_completions or []):
        if message.get("role") == "assistant":
            return message.get("content")
    return None


def _validate_enriched_candidate_trace(episode: Any) -> None:
    """Fail closed if enriched trace identity, tokens, or text diverge."""
    artifacts = episode.artifacts or {}
    if artifacts.get("status") != "ok":
        return
    if "candidate_request_count" not in artifacts:
        return

    request_count = int(artifacts["candidate_request_count"])
    completed_turn_count = int(artifacts.get("completed_turn_count", -1))
    steps = [step for trajectory in episode.trajectories for step in trajectory.steps]
    if request_count != completed_turn_count or request_count != len(steps):
        raise CandidateTraceMismatch(
            "enriched candidate trace count mismatch "
            f"(requests={request_count}, completed_turns={completed_turn_count}, "
            f"steps={len(steps)})"
        )

    trace_ids: list[str] = []
    for step in steps:
        response = str(step.model_response or "")
        action = str(step.action or "")
        assistant = _assistant_content(step)
        if not response.strip() or response != action or assistant != response:
            raise CandidateTraceMismatch(
                "enriched candidate response does not match its recorded action"
            )
        trace_id = str(step.id or "")
        if not trace_id:
            raise CandidateTraceMismatch("enriched candidate step has no trace identity")
        trace_ids.append(trace_id)
        if not artifacts.get("is_validation") and not step.response_ids:
            raise CandidateTraceMismatch(
                f"candidate trace {trace_id} has no completion token IDs"
            )
    if len(trace_ids) != len(set(trace_ids)):
        raise CandidateTraceMismatch("candidate trace identities are not unique")


@rllm.evaluator
def aeread_evaluator(task: Any, episode: Any) -> EvalOutput:
    """Return raw episode AER for training and named signals for reporting.

    Raises a typed :class:`~aeread.integrations.failure_taxonomy.IntegrationError`
    (never returns a fabricated score) when ``episode.artifacts`` is not a
    complete, finite AERead measurement -- see
    :meth:`EpisodeMeasurement.from_result`. A trajectory only reaches this
    function's ``EvalOutput`` return if AERead actually measured it.
    """
    _validate_enriched_candidate_trace(episode)
    artifacts = getattr(episode, "artifacts", None) or {}
    measurement = EpisodeMeasurement.from_result(artifacts)

    denominator_tier = artifacts.get("denominator_tier")
    tier_metadata = {"tier": denominator_tier} if denominator_tier is not None else {}
    dataset = artifacts.get("dataset") or {}

    metadata: dict[str, Any] = {
        "status": "ok",
        "w_real": measurement.w_real,
        "denominator": measurement.denominator,
        "denominator_tier": denominator_tier,
        "dataset": dataset,
        "caseset_sha256": artifacts.get("caseset_sha256")
        or dataset.get("caseset_sha256"),
        "model": artifacts.get("model"),
        "candidate_sampling": artifacts.get("candidate_sampling"),
        "prompt_spec": artifacts.get("prompt_spec")
        or dataset.get("prompt_spec"),
        "panel_spec": artifacts.get("panel_spec")
        or dataset.get("panel_spec"),
        "scorer_version": artifacts.get("scorer_version")
        or dataset.get("scorer_version"),
        "scorer": artifacts.get("scorer"),
        "external_scoring": artifacts.get("external_scoring"),
        "rllm_revision": artifacts.get("rllm_revision"),
        "measurement_counters": artifacts.get("measurement_counters"),
        "flow_counters": artifacts.get("flow_counters"),
    }
    return EvalOutput(
        reward=float(measurement.aer),
        is_correct=bool(measurement.aer > 0.0),
        signals=[
            Signal("episode_aer", float(measurement.aer), dict(tier_metadata)),
            Signal("w_real", float(measurement.w_real), dict(tier_metadata)),
            Signal("denominator", float(measurement.denominator), dict(tier_metadata)),
            Signal("valid_measurement", 1.0),
            Signal(
                "blank_completion_count",
                float(artifacts.get("blank_completion_count", 0)),
            ),
        ],
        metadata=metadata,
    )


__all__ = ["aeread_evaluator"]
