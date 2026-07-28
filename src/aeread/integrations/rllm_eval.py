"""rLLM evaluator for AERead episodes (experimental).

Reward = per-episode AER (raw ``w_real / denominator``; negatives preserved,
harness errors and degenerate denominators score 0.0 with the reason kept in
metadata). Returned as a plain ``{"reward", "is_correct", "metadata"}`` dict,
which rLLM's evaluator dispatch accepts alongside ``EvalOutput``.
"""
from __future__ import annotations

from typing import Any


def aeread_evaluator(task: Any, episode: Any) -> dict[str, Any]:
    artifacts = getattr(episode, "artifacts", None) or {}
    aer = artifacts.get("aer")
    status = artifacts.get("status")
    reward = float(aer) if aer is not None else 0.0
    return {
        "reward": reward,
        "is_correct": bool(aer is not None and aer > 0.0),
        "metadata": {
            "status": status,
            "w_real": artifacts.get("w_real"),
            "denominator": artifacts.get("denominator"),
        },
    }
