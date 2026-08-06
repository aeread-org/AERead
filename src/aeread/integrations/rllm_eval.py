"""rLLM evaluator for AERead episodes (experimental).

Reward = per-episode AER (raw ``w_real / denominator``; negatives preserved).
An episode that carries no measurement (harness failure, degenerate
denominator) still returns 0.0, because rLLM's trainer needs a float, but it
is flagged: ``metadata["error"]`` is set, and the flow terminates such an
episode with rLLM's ERROR reason so the eval report counts it under Errors
instead of showing it as a model that scored zero. A genuine AER of 0.0 or
below is a measurement and stays a plain score.

Returned as a plain ``{"reward", "is_correct", "metadata"}`` dict, which
rLLM's evaluator dispatch accepts alongside ``EvalOutput``.
"""
from __future__ import annotations

from typing import Any


def aeread_evaluator(task: Any, episode: Any) -> dict[str, Any]:
    artifacts = getattr(episode, "artifacts", None) or {}
    aer = artifacts.get("aer")
    status = artifacts.get("status")
    error = artifacts.get("error")
    if error is None and (status != "ok" or aer is None):
        error = (f"aeread episode carries no AER (status={status!r}, "
                 f"denominator={artifacts.get('denominator')!r})")
    metadata: dict[str, Any] = {
        "status": status,
        "w_real": artifacts.get("w_real"),
        "denominator": artifacts.get("denominator"),
    }
    if error:
        metadata["error"] = error
    return {
        "reward": float(aer) if aer is not None else 0.0,
        "is_correct": bool(aer is not None and aer > 0.0),
        "metadata": metadata,
    }
