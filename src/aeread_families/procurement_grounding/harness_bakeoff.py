"""Paired harness probe on the frozen 231-project procurement case.

The model, endpoint, case, inference seeds, retry policy, and output budget are
held fixed.  Only the harness serialization/execution layer changes.  Because
the repository currently has one frozen procurement case, the resulting paired
differences are development evidence rather than population-level estimates.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from aeread.shared_runner.execution import OpenRouterChatClient, execute_plan_cell
from aeread.shared_runner.harness import MinimalChatHarness
from aeread.shared_runner.open_harnesses import (
    LangChainProviderClient,
    LangChainProviderStrategyHarness,
)
from aeread.shared_runner.resolver import canonical_json_bytes

from .bakeoff import OPEN_WEIGHT_CANDIDATES, preflight_candidate
from .runner import (
    build_openrouter_setup,
    finalize_procurement_execution,
    finalize_procurement_failure,
    replay_procurement_receipt,
)


GLM_CANDIDATE = next(
    candidate
    for candidate in OPEN_WEIGHT_CANDIDATES
    if candidate.candidate_id == "glm53_flash"
)
HARNESS_ARM_IDS = (
    "aeread_minimal_chat_v1",
    "langchain_provider_strategy_v1",
)


@dataclass(frozen=True, slots=True)
class HarnessArm:
    condition_id: str
    label: str
    harness: Any
    provider_factory: Callable[[], Any]


def harness_arms() -> tuple[HarnessArm, ...]:
    return (
        HarnessArm(
            condition_id="aeread_minimal_chat_v1",
            label="AERead Minimal Chat",
            harness=MinimalChatHarness(),
            provider_factory=OpenRouterChatClient,
        ),
        HarnessArm(
            condition_id="langchain_provider_strategy_v1",
            label="LangChain Provider Strategy",
            harness=LangChainProviderStrategyHarness(),
            provider_factory=LangChainProviderClient,
        ),
    )


def derive_inference_seeds(*, master_seed: int, count: int) -> tuple[int, ...]:
    if master_seed < 0 or count < 1:
        raise ValueError("master_seed must be non-negative and count positive")
    seeds: list[int] = []
    counter = 0
    while len(seeds) < count:
        payload = f"procurement_harness_v1:{master_seed}:{counter}".encode("utf-8")
        counter += 1
        candidate = (
            int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")
            & 0x7FFF_FFFF
        )
        if candidate not in seeds:
            seeds.append(candidate)
    return tuple(seeds)


def conservative_cost_ceiling(
    *,
    arm_count: int,
    seed_count: int,
    max_input_tokens: int = 8000,
    max_output_tokens: int = 2500,
) -> float:
    if arm_count < 1 or seed_count < 1:
        raise ValueError("arm_count and seed_count must be positive")
    return GLM_CANDIDATE.route.pricing.cost(
        input_tokens=max_input_tokens,
        cached_input_tokens=0,
        output_tokens=max_output_tokens,
    ) * arm_count * seed_count


def planned_probe(
    *,
    inference_seeds: Sequence[int],
    arm_ids: Sequence[str] | None = None,
    inter_call_delay_seconds: float = 0.0,
) -> dict[str, Any]:
    if inter_call_delay_seconds < 0:
        raise ValueError("inter_call_delay_seconds cannot be negative")
    selected = tuple(
        arm
        for arm in harness_arms()
        if arm_ids is None or arm.condition_id in set(arm_ids)
    )
    if not selected:
        raise ValueError("arm_ids selected no harness arms")
    return {
        "schema_version": "aeread.procurement_harness_probe_plan/0.1",
        "case_id": "procurement_grounding_v1.dev.231_projects",
        "model": GLM_CANDIDATE.route.model,
        "revision": GLM_CANDIDATE.route.revision,
        "provider": GLM_CANDIDATE.route.route_provider,
        "quantization": GLM_CANDIDATE.route.quantization,
        "inference_seeds": list(inference_seeds),
        "arms": [arm.condition_id for arm in selected],
        "retry_policy": "one attempt; SDK retries disabled",
        "response_cache": "disabled",
        "prompt_cache": "automatic provider behavior; observed and reported",
        "execution_order": "sequential with arm order rotated by seed",
        "inter_call_delay_seconds": inter_call_delay_seconds,
        "conservative_cost_ceiling_usd": conservative_cost_ceiling(
            arm_count=len(selected), seed_count=len(inference_seeds)
        ),
        "claim_scope": "single frozen case; exploratory harness comparison",
    }


def _plain(value: Any) -> Any:
    return json.loads(canonical_json_bytes(value))


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    payload = canonical_json_bytes(value) + b"\n"
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _framework_metrics(evidence: Any) -> dict[str, Any]:
    request_count = 0
    provider_cost_complete = True
    versions: set[str] = set()
    for event in evidence.read_events():
        if event.event_type != "provider_call_succeeded":
            continue
        payload = evidence.read_event_payload(event)
        result = (
            payload.get("provider_result") if isinstance(payload, Mapping) else None
        )
        raw = result.get("raw_response") if isinstance(result, Mapping) else None
        if not isinstance(raw, Mapping):
            provider_cost_complete = False
            continue
        if "framework" not in raw:
            request_count += 1
            usage = raw.get("usage")
            provider_cost_complete = provider_cost_complete and (
                isinstance(usage, Mapping)
                and isinstance(usage.get("cost"), (int, float))
            )
            continue
        count = raw.get("framework_model_request_count")
        request_count += count if isinstance(count, int) and count >= 0 else 0
        provider_cost_complete = (
            provider_cost_complete and raw.get("provider_cost_complete") is True
        )
        version = raw.get("framework_version")
        if isinstance(version, str):
            versions.add(version)
    return {
        "framework_model_request_count": request_count,
        "framework_versions": sorted(versions),
        "provider_cost_complete": provider_cost_complete,
    }


def _failure_summary(error: BaseException) -> dict[str, Any]:
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    condition = next(
        (
            value
            for item in chain
            if isinstance((value := getattr(item, "condition", None)), str)
        ),
        None,
    )
    status_code = next(
        (
            value
            for item in chain
            if isinstance((value := getattr(item, "status_code", None)), int)
        ),
        None,
    )
    messages = " ".join(str(item).lower() for item in chain)
    if condition is None and (
        status_code == 429 or "error code: 429" in messages or "rate-limit" in messages
    ):
        condition = "rate_limit"
    elif condition is None and status_code is not None and status_code >= 500:
        condition = "provider_5xx"
    return {
        "failure_type": type(error).__name__,
        "failure_condition": (
            condition if isinstance(condition, str) else "harness_probe_failure"
        ),
        "failure_status_code": status_code if isinstance(status_code, int) else None,
    }


def summarize_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for condition_id in HARNESS_ARM_IDS:
        arm_rows = [row for row in rows if row.get("condition_id") == condition_id]
        completed = [row for row in arm_rows if row.get("status") == "completed"]
        summaries[condition_id] = {
            "planned": len(arm_rows),
            "completed": len(completed),
            "reliability": len(completed) / len(arm_rows) if arm_rows else None,
            "mean_score": (
                statistics.fmean(float(row["score"]) for row in completed)
                if completed
                else None
            ),
            "median_elapsed_seconds": (
                statistics.median(float(row["elapsed_seconds"]) for row in completed)
                if completed
                else None
            ),
            "median_cost_usd": (
                statistics.median(float(row["cost_usd"]) for row in completed)
                if completed
                else None
            ),
            "median_input_tokens": (
                statistics.median(int(row["input_tokens"]) for row in completed)
                if completed
                else None
            ),
            "median_cached_input_tokens": (
                statistics.median(
                    int(row["cached_input_tokens"]) for row in completed
                )
                if completed
                else None
            ),
        }

    rows_by_pair = {
        (str(row.get("condition_id")), int(row["inference_seed"])): row
        for row in rows
        if row.get("status") == "completed"
    }
    paired_differences: list[dict[str, Any]] = []
    seeds = sorted({int(row["inference_seed"]) for row in rows})
    for seed in seeds:
        control = rows_by_pair.get(("aeread_minimal_chat_v1", seed))
        treatment = rows_by_pair.get(("langchain_provider_strategy_v1", seed))
        if control is None or treatment is None:
            continue
        paired_differences.append(
            {
                "inference_seed": seed,
                "score_difference_langchain_minus_aeread": (
                    float(treatment["score"]) - float(control["score"])
                ),
                "latency_difference_seconds_langchain_minus_aeread": (
                    float(treatment["elapsed_seconds"])
                    - float(control["elapsed_seconds"])
                ),
                "cost_difference_usd_langchain_minus_aeread": (
                    float(treatment["cost_usd"]) - float(control["cost_usd"])
                ),
            }
        )
    return {
        "conditions": summaries,
        "complete_pair_count": len(paired_differences),
        "paired_differences": paired_differences,
        "paired_score_difference_mean": (
            statistics.fmean(
                row["score_difference_langchain_minus_aeread"]
                for row in paired_differences
            )
            if paired_differences
            else None
        ),
        "inference": "descriptive only; inference seeds are not independent cases",
    }


async def run_probe(
    *,
    output_root: Path,
    inference_seeds: Sequence[int],
    arm_ids: Sequence[str] | None = None,
    max_spend_usd: float = 0.02,
    inter_call_delay_seconds: float = 0.0,
) -> dict[str, Any]:
    plan = planned_probe(
        inference_seeds=inference_seeds,
        arm_ids=arm_ids,
        inter_call_delay_seconds=inter_call_delay_seconds,
    )
    if plan["conservative_cost_ceiling_usd"] > max_spend_usd:
        raise ValueError(
            "conservative probe ceiling exceeds max_spend_usd: "
            f"{plan['conservative_cost_ceiling_usd']:.6f} > {max_spend_usd:.6f}"
        )
    preflight = preflight_candidate(GLM_CANDIDATE)
    selected = tuple(
        arm
        for arm in harness_arms()
        if arm_ids is None or arm.condition_id in set(arm_ids)
    )
    providers = {arm.condition_id: arm.provider_factory() for arm in selected}
    output_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    first_call = True
    for seed_index, inference_seed in enumerate(inference_seeds):
        rotated = selected[seed_index % len(selected) :] + selected[: seed_index % len(selected)]
        for arm in rotated:
            if not first_call and inter_call_delay_seconds:
                await asyncio.sleep(inter_call_delay_seconds)
            first_call = False
            setup = build_openrouter_setup(
                GLM_CANDIDATE.route,
                seed=inference_seed,
                max_output_tokens=2500,
                timeout_seconds=180.0,
                max_cost_usd=0.01,
                harness=arm.harness,
                harness_config={
                    "framework_package": (
                        None
                        if isinstance(arm.harness, MinimalChatHarness)
                        else "langchain"
                    ),
                    "framework_version": (
                        None
                        if isinstance(arm.harness, MinimalChatHarness)
                        else importlib.metadata.version("langchain")
                    ),
                    "framework_retries": 0,
                },
            )
            cell = setup.plan.cells[0]
            evidence_root = output_root / arm.condition_id / f"seed_{inference_seed}"
            started = time.perf_counter()
            try:
                execution = await execute_plan_cell(
                    plan=setup.plan,
                    cell_id=cell.cell_id,
                    registry=setup.registry,
                    evidence_root=evidence_root,
                    prompt_sources=setup.prompt_sources,
                    providers={"openrouter": providers[arm.condition_id]},
                    pricing=setup.pricing,
                    harnesses=setup.harnesses,
                )
                receipt = finalize_procurement_execution(
                    setup=setup, execution=execution
                )
                replay_procurement_receipt(
                    setup=setup,
                    receipt=receipt,
                    evidence_root=evidence_root,
                )
                calls = [
                    call
                    for action in execution.action_executions
                    for attempt in action.attempts
                    for call in attempt.provider_calls
                ]
                outcome = _plain(execution.episode_result.outcome)
                row = {
                    "condition_id": arm.condition_id,
                    "label": arm.label,
                    "inference_seed": inference_seed,
                    "status": "completed",
                    "valid": bool(outcome["valid"]),
                    "score": float(outcome["score"]),
                    "quality_band": outcome["quality_band"],
                    "elapsed_seconds": time.perf_counter() - started,
                    "input_tokens": sum(call.input_tokens for call in calls),
                    "cached_input_tokens": sum(
                        call.cached_input_tokens for call in calls
                    ),
                    "output_tokens": sum(call.output_tokens for call in calls),
                    "cost_usd": execution.total_cost_usd,
                    "resolved_models": sorted(
                        {
                            call.resolved_model
                            for call in calls
                            if call.resolved_model is not None
                        }
                    ),
                    "receipt_sha256": receipt.receipt_sha256,
                    "replay_level": receipt.replay_level,
                    **_framework_metrics(execution.evidence),
                }
            except Exception as error:
                failure_receipt_sha256 = None
                try:
                    failure_receipt = finalize_procurement_failure(
                        setup=setup,
                        cell_id=cell.cell_id,
                        evidence_root=evidence_root,
                        error=error,
                    )
                    failure_receipt_sha256 = failure_receipt.receipt_sha256
                except Exception:
                    pass
                row = {
                    "condition_id": arm.condition_id,
                    "label": arm.label,
                    "inference_seed": inference_seed,
                    "status": "operational_failure",
                    "elapsed_seconds": time.perf_counter() - started,
                    "failure_receipt_sha256": failure_receipt_sha256,
                    **_failure_summary(error),
                }
            row_payload = dict(row)
            row["result_sha256"] = hashlib.sha256(
                canonical_json_bytes(row_payload)
            ).hexdigest()
            rows.append(row)
            _atomic_write_json(
                output_root
                / arm.condition_id
                / "results"
                / f"seed_{inference_seed}.json",
                row,
            )

    artifact = {
        "schema_version": "aeread.procurement_harness_probe/0.1",
        "plan": plan,
        "preflight": preflight,
        "framework_versions": {
            "openai": importlib.metadata.version("openai"),
            "langchain": importlib.metadata.version("langchain"),
            "langchain-openai": importlib.metadata.version("langchain-openai"),
        },
        "measurement_boundary": {
            "case_and_oracle": "AERead authoritative",
            "framework_scope": "provider serialization and structured response",
            "receipt_replay": "required for every completed row",
        },
        "summary": summarize_rows(rows),
        "rows": rows,
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(artifact)
    ).hexdigest()
    _atomic_write_json(output_root / "summary.json", artifact)
    return artifact


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replicates", type=int, default=3)
    parser.add_argument("--master-seed", type=int, default=20260831)
    parser.add_argument("--max-spend-usd", type=float, default=0.02)
    parser.add_argument("--inter-call-delay-seconds", type=float, default=0.0)
    parser.add_argument("--execute", action="store_true")
    arguments = parser.parse_args(argv)
    seeds = derive_inference_seeds(
        master_seed=arguments.master_seed, count=arguments.replicates
    )
    if not arguments.execute:
        print(
            json.dumps(
                planned_probe(
                    inference_seeds=seeds,
                    inter_call_delay_seconds=arguments.inter_call_delay_seconds,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    artifact = asyncio.run(
        run_probe(
            output_root=arguments.output,
            inference_seeds=seeds,
            max_spend_usd=arguments.max_spend_usd,
            inter_call_delay_seconds=arguments.inter_call_delay_seconds,
        )
    )
    print(json.dumps(artifact["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "GLM_CANDIDATE",
    "HARNESS_ARM_IDS",
    "conservative_cost_ceiling",
    "derive_inference_seeds",
    "harness_arms",
    "planned_probe",
    "run_probe",
    "summarize_rows",
]
