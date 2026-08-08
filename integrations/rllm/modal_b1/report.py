"""Pure reporting for the B1 micro-GRPO smoke.

Deliberately free of ``modal``, network access, and provider credentials so
it runs inside the repository's default provider-free pytest suite.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from aeread.integrations.pooled_aer import aggregate_eval_signals

# Modal's published A10G rate, USD per second.
A10G_USD_PER_SECOND = 0.000306

# HANDOVER.md records roughly this much per episode on the OpenRouter path.
ESTIMATED_USD_PER_EPISODE = 0.007

_SIGNAL_FIELDS = (
    "episode_aer",
    "w_real",
    "denominator",
    "valid_measurement",
    "blank_completion_count",
)


def signal_rows_from_eval_output(task_id: str, output: Any) -> dict[str, Any]:
    """Flatten one ``EvalOutput`` into a pooled-AER-compatible row."""
    row: dict[str, Any] = {"task_id": task_id, "failure_class": None}
    tier: str | None = None
    for signal in getattr(output, "signals", []) or []:
        name = getattr(signal, "name", None)
        if name not in _SIGNAL_FIELDS:
            continue
        row[name] = getattr(signal, "value", None)
        metadata = getattr(signal, "metadata", None) or {}
        tier = tier or metadata.get("tier") or metadata.get("denominator_tier")

    output_metadata = getattr(output, "metadata", None) or {}
    tier = tier or output_metadata.get("tier") or output_metadata.get("denominator_tier")
    row["tier"] = tier
    row["valid_measurement"] = bool(row.get("valid_measurement"))
    row["blank_completion_count"] = float(row.get("blank_completion_count") or 0.0)
    return row


def variance_verdict(
    aers: Sequence[float], *, tol: float = 1e-9
) -> dict[str, Any]:
    """Decide whether a group of AERs can produce a non-zero GRPO advantage.

    An identical-valued group yields zero advantage for every member, so
    an optimizer step over it would be vacuously true rather than
    informative.
    """
    values = [float(a) for a in aers if a is not None]
    if len(values) < 2:
        return {
            "degenerate": True,
            "spread": 0.0,
            "n": len(values),
            "recommendation": "insufficient measurements to judge variance",
        }
    spread = max(values) - min(values)
    degenerate = spread <= tol
    return {
        "degenerate": degenerate,
        "spread": spread,
        "n": len(values),
        "min": min(values),
        "max": max(values),
        "recommendation": (
            "escalate to a larger policy before spending on optimizer steps"
            if degenerate
            else "proceed to stage 1"
        ),
    }


def gpu_cost_usd(seconds: float, rate_per_second: float) -> float:
    """Cost of measured GPU wall-clock at a published per-second rate."""
    return float(seconds) * float(rate_per_second)


def build_run_report(
    *,
    stage: str,
    rows: Sequence[Mapping[str, Any]],
    telemetry: Mapping[str, Any],
    gpu_seconds: float,
    openrouter_usd: float,
    live_calls: int,
    cached_calls: int,
    total_tokens: int,
    gpu_rate_per_second: float = A10G_USD_PER_SECOND,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the machine-readable run report."""
    aggregate = aggregate_eval_signals(rows)
    aers = [
        r["episode_aer"]
        for r in rows
        if r.get("valid_measurement") and r.get("episode_aer") is not None
    ]
    gpu_usd = gpu_cost_usd(gpu_seconds, gpu_rate_per_second)
    report: dict[str, Any] = {
        "stage": stage,
        "aggregate": aggregate,
        "variance": variance_verdict(aers),
        "telemetry": dict(telemetry),
        "cost": {
            "gpu_seconds": float(gpu_seconds),
            "gpu_usd": gpu_usd,
            "openrouter_usd": float(openrouter_usd),
            "total_usd": gpu_usd + float(openrouter_usd),
            "live_calls": int(live_calls),
            "cached_calls": int(cached_calls),
            "total_tokens": int(total_tokens),
        },
    }
    if extra:
        report.update(dict(extra))
    return report


def format_cost_line(report: Mapping[str, Any]) -> str:
    """Render the one-line cost summary the project requires after every run."""
    cost = report["cost"]
    calls = cost["live_calls"] + cost["cached_calls"]
    return (
        f"cost: ${cost['total_usd']:.2f} "
        f"({cost['gpu_usd']:.2f} GPU + {cost['openrouter_usd']:.2f} OpenRouter) "
        f"· {calls} calls ({cost['live_calls']} live / {cost['cached_calls']} cached) "
        f"· ~{cost['total_tokens']} tokens"
    )


def write_report(path: str, report: Mapping[str, Any]) -> None:
    """Persist the report as indented JSON."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
