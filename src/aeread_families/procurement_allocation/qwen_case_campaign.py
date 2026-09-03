"""Matched Qwen qualification on the six procurement-allocation worlds.

This campaign changes the model route while holding the cases, inference seeds,
prompt, harness, action budget, and objective verifier fixed relative to the
qualified GLM case-variance baseline.  It is an operationally gated panel, not a
population model ranking.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from aeread.shared_runner.model_call.harness import MinimalChatHarness
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import (
    OpenRouterChatClient,
    ProviderFailure,
    ProviderRequest,
    execute_plan_cell,
)
from aeread_families.procurement_grounding.bakeoff import (
    OPEN_WEIGHT_CANDIDATES,
    preflight_candidate,
)

from .case_matrix import CASE_VARIANCE_PATHS
from .model_campaign import (
    CAMPAIGN_ID as GLM_BASELINE_CAMPAIGN_ID,
    derive_inference_seeds,
    planned_model_qualification,
    run_model_qualification,
)
from .runner import PROMPT, SequenceResponseProvider, build_openrouter_setup


CAMPAIGN_ID = "procurement_allocation_qwen3_30b_coreweave_case_variance_v1"
QWEN_CANDIDATE = next(
    candidate
    for candidate in OPEN_WEIGHT_CANDIDATES
    if candidate.candidate_id == "qwen3_30b_a3b_instruct_2507_coreweave"
)
PAIRED_INFERENCE_SEEDS = derive_inference_seeds(
    master_seed=20260902,
    count=3,
    campaign_id=GLM_BASELINE_CAMPAIGN_ID,
)
MAX_PARALLEL_CELLS = 1
TRAJECTORIES_PER_CHECKPOINT = 6
MAX_ACTION_ATTEMPTS = 3
RETRY_CONDITIONS = ("rate_limit", "provider_5xx", "empty_response")
RETRY_BACKOFF = "exponential_jitter_v1"
RETRY_BASE_SECONDS = 15.0
RETRY_AFTER_MAX_SECONDS = 60.0
MAX_TRAJECTORY_COST_USD = 0.01
MAX_CANARY_COST_USD = 0.01
HARD_TOTAL_COST_CEILING_USD = 0.19


def _write_once_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"refusing to replace different artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _replace_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(canonical_json_bytes(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def build_plan() -> dict[str, Any]:
    scored = planned_model_qualification(
        case_paths=CASE_VARIANCE_PATHS,
        inference_seeds=PAIRED_INFERENCE_SEEDS,
        max_parallel_cells=MAX_PARALLEL_CELLS,
        campaign_id=CAMPAIGN_ID,
        abort_on_operational_failure=True,
        candidate=QWEN_CANDIDATE,
        prompt=PROMPT,
        prompt_id="procurement_allocation_prompt_v1",
        treatment_id="unscaffolded_control",
        max_new_trajectories=TRAJECTORIES_PER_CHECKPOINT,
        max_action_attempts=MAX_ACTION_ATTEMPTS,
        retryable_conditions=RETRY_CONDITIONS,
        retry_backoff=RETRY_BACKOFF,
        retry_base_seconds=RETRY_BASE_SECONDS,
        retry_after_max_seconds=RETRY_AFTER_MAX_SECONDS,
        max_cost_usd_per_trajectory=MAX_TRAJECTORY_COST_USD,
    )
    conservative_total = (
        Decimal(str(scored["conservative_cost_ceiling_usd"]))
        + Decimal(str(MAX_CANARY_COST_USD))
    ).quantize(Decimal("0.000000000001"))
    plan: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_candidate_campaign_plan/0.1",
        "campaign_id": CAMPAIGN_ID,
        "freeze_status": "frozen_before_live_execution",
        "candidate": {
            "candidate_id": QWEN_CANDIDATE.candidate_id,
            "model": QWEN_CANDIDATE.route.model,
            "revision": QWEN_CANDIDATE.route.revision,
            "provider": QWEN_CANDIDATE.route.route_provider,
            "quantization": QWEN_CANDIDATE.route.quantization,
            "access_class": QWEN_CANDIDATE.access_class,
            "license_id": QWEN_CANDIDATE.license_id,
            "model_card_url": QWEN_CANDIDATE.model_card_url,
        },
        "matched_baseline_campaign_id": GLM_BASELINE_CAMPAIGN_ID,
        "scored_plan": scored,
        "admission_canary": {
            "scored": False,
            "request_shape": "first declared case and inference seed",
            "max_cost_usd": MAX_CANARY_COST_USD,
            "output_validity_is_not_an_admission_gate": True,
        },
        "checkpoint_policy": (
            "six sequential trajectories per invocation; only a failure-free "
            "checkpoint may resume"
        ),
        "conservative_total_cost_ceiling_usd": float(conservative_total),
        "hard_total_cost_ceiling_usd": HARD_TOTAL_COST_CEILING_USD,
        "eligibility": (
            "all 18 rows completed and receipt-replayed with exact cost accounting; "
            "model route, cases, seeds, prompt, harness, and digests match"
        ),
        "claim_scope": (
            "matched model diagnostic on six curated procurement worlds; seeds are "
            "within-world replicates and this is not a population model ranking"
        ),
    }
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return plan


async def _representative_request() -> ProviderRequest:
    setup = build_openrouter_setup(
        QWEN_CANDIDATE.route,
        case_path=CASE_VARIANCE_PATHS[0],
        seed=PAIRED_INFERENCE_SEEDS[0],
        max_output_tokens=1800,
        timeout_seconds=180.0,
        max_cost_usd=MAX_CANARY_COST_USD,
        harness=MinimalChatHarness(),
        prompt=PROMPT,
        prompt_id="procurement_allocation_prompt_v1",
        max_action_attempts=MAX_ACTION_ATTEMPTS,
        retryable_conditions=RETRY_CONDITIONS,
        retry_backoff=RETRY_BACKOFF,
        retry_base_seconds=RETRY_BASE_SECONDS,
        retry_after_max_seconds=RETRY_AFTER_MAX_SECONDS,
    )
    provider = SequenceResponseProvider(
        (json.dumps({"action": "defer", "reason": "request-shape capture"}),)
    )
    with tempfile.TemporaryDirectory(prefix="aeread-procurement-qwen-canary-") as root:
        await execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=Path(root),
            prompt_sources=setup.prompt_sources,
            providers={"openrouter": provider},
            pricing=setup.pricing,
            harnesses=setup.harnesses,
        )
    if len(provider.requests) != 1:
        raise RuntimeError("canary request capture did not make exactly one call")
    return provider.requests[0]


def _failure_fields(error: BaseException) -> dict[str, Any]:
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    status_code = next(
        (
            value
            for item in chain
            if isinstance((value := getattr(item, "status_code", None)), int)
        ),
        None,
    )
    condition = next(
        (
            value
            for item in chain
            if isinstance((value := getattr(item, "condition", None)), str)
        ),
        None,
    )
    if condition is None and status_code == 429:
        condition = "rate_limit"
    return {
        "failure_type": type(error).__name__,
        "failure_condition": condition or "provider_failure",
        "failure_status_code": status_code,
    }


async def run_admission_canary(
    *,
    path: Path,
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
) -> dict[str, Any]:
    request = await _representative_request()
    if path.exists():
        value = json.loads(path.read_text(encoding="utf-8"))
        recorded = value.get("artifact_sha256")
        payload = {key: item for key, item in value.items() if key != "artifact_sha256"}
        if recorded != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
            raise ValueError("admission canary digest mismatch")
        if (
            value.get("campaign_id") != CAMPAIGN_ID
            or value.get("request_sha256") != request.request_sha256
        ):
            raise ValueError("admission canary identity mismatch")
        return value

    record: dict[str, Any] = {
        "schema_version": "aeread.provider_admission_canary/0.4",
        "campaign_id": CAMPAIGN_ID,
        "attempted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "request_sha256": request.request_sha256,
        "model": request.model,
        "revision": request.revision,
        "route_provider": request.provider_metadata["route_provider"],
        "max_output_tokens": request.max_output_tokens,
        "max_cost_usd": request.max_cost_usd,
        "scored": False,
    }
    provider = provider_factory()
    calls = input_tokens = cached_input_tokens = output_tokens = 0
    cost_usd = 0.0
    retry_counts: Counter[str] = Counter()
    cost_accounting = "exact"
    for ordinal in range(MAX_ACTION_ATTEMPTS):
        calls += 1
        try:
            result = await provider.complete(request)
            input_tokens += result.input_tokens
            cached_input_tokens += result.cached_input_tokens
            output_tokens += result.output_tokens
            cost_usd += result.cost_usd
            if not result.output_text.strip():
                raise ProviderFailure(
                    "empty_response",
                    "admission canary received an empty completion",
                    retryable=True,
                )
            try:
                action = json.loads(result.output_text)
            except json.JSONDecodeError:
                action = None
                output_contract_status = "malformed_json"
            else:
                output_contract_status = (
                    "valid_structured_action"
                    if isinstance(action, Mapping)
                    and isinstance(action.get("action"), str)
                    else "invalid_action_shape"
                )
            record.update(
                {
                    "status": "admitted",
                    "resolved_model": result.resolved_model,
                    "finish_reason": result.finish_reason,
                    "output_contract_status": output_contract_status,
                    "structured_action": (
                        action["action"]
                        if output_contract_status == "valid_structured_action"
                        else None
                    ),
                }
            )
            break
        except Exception as error:
            failure = _failure_fields(error)
            retryable = (
                failure["failure_condition"] in RETRY_CONDITIONS
                and ordinal + 1 < MAX_ACTION_ATTEMPTS
            )
            if retryable:
                retry_counts[failure["failure_condition"]] += 1
                await asyncio.sleep(min(30.0, RETRY_BASE_SECONDS * (2**ordinal)))
                continue
            if failure["failure_condition"] not in set(RETRY_CONDITIONS):
                cost_accounting = "unavailable"
            record.update({"status": "rejected", **failure})
            break
    record.update(
        {
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "cost_accounting": cost_accounting,
            "provider_call_count": calls,
            "runner_retry_count": sum(retry_counts.values()),
            "retry_condition_counts": dict(sorted(retry_counts.items())),
        }
    )
    record["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(record)).hexdigest()
    _write_once_json(path, record)
    return record


def _validate_run_root(run_root: Path) -> None:
    parts = run_root.resolve().parts
    if "runs" not in parts or {"evidence", "output", "outputs"}.intersection(parts):
        raise ValueError("run_root must be under runs/ and outside publication paths")


def _status(
    *, canary: Mapping[str, Any], artifact: Mapping[str, Any] | None
) -> dict[str, Any]:
    scored_summary = artifact.get("summary", {}) if artifact is not None else {}
    planned = len(CASE_VARIANCE_PATHS) * len(PAIRED_INFERENCE_SEEDS)
    completed = int(scored_summary.get("completed_trajectory_count", 0))
    failures = int(scored_summary.get("operational_failure_count", 0))
    scored_cost = float(scored_summary.get("total_cost_usd", 0.0))
    canary_cost = float(canary.get("cost_usd", 0.0))
    value: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_candidate_campaign_status/0.1",
        "campaign_id": CAMPAIGN_ID,
        "canary": dict(canary),
        "scored_summary": dict(scored_summary),
        "summary": {
            "planned_trajectory_count": planned,
            "completed_trajectory_count": completed,
            "operational_failure_count": failures,
            "unattempted_trajectory_count": max(planned - completed - failures, 0),
            "total_cost_including_canary_usd": scored_cost + canary_cost,
            "cost_accounting": (
                "exact"
                if canary.get("cost_accounting") == "exact"
                and scored_summary.get("cost_accounting", "exact") == "exact"
                else "lower_bound"
            ),
            "execution_qualified": (
                canary.get("status") == "admitted"
                and completed == planned
                and failures == 0
                and scored_summary.get("readiness", {}).get("execution_qualified") is True
            ),
            "failure_free_checkpoint": (
                canary.get("status") == "admitted"
                and 0 < completed < planned
                and failures == 0
            ),
        },
    }
    value["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    return value


async def run_campaign(
    *,
    run_root: Path,
    max_spend_usd: float = HARD_TOTAL_COST_CEILING_USD,
    resume: bool = False,
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
    preflight_fn: Callable[[Any], Mapping[str, Any]] = preflight_candidate,
) -> dict[str, Any]:
    _validate_run_root(run_root)
    if max_spend_usd < HARD_TOTAL_COST_CEILING_USD:
        raise ValueError("max_spend_usd is below the frozen hard total ceiling")
    if run_root.exists() and not resume:
        raise FileExistsError("campaign output exists; pass --resume after a checkpoint")
    if resume and not run_root.exists():
        raise FileNotFoundError("cannot resume a campaign that does not exist")
    plan = build_plan()
    plan_path = run_root / "campaign_plan.json"
    if plan_path.exists():
        if canonical_json_bytes(json.loads(plan_path.read_text())) != canonical_json_bytes(plan):
            raise ValueError("existing campaign plan does not match this invocation")
    else:
        _write_once_json(plan_path, plan)

    scored_root = run_root / "scored"
    existing_summary = scored_root / "summary.json"
    if existing_summary.exists():
        existing = json.loads(existing_summary.read_text(encoding="utf-8"))
        if existing.get("summary", {}).get("operational_failure_count"):
            raise ValueError("cannot resume an attempt containing an operational failure")

    canary = await run_admission_canary(
        path=run_root / "admission_canary.json",
        provider_factory=provider_factory,
    )
    artifact: Mapping[str, Any] | None = None
    if canary.get("status") == "admitted":
        artifact = await run_model_qualification(
            run_root=scored_root,
            case_paths=CASE_VARIANCE_PATHS,
            inference_seeds=PAIRED_INFERENCE_SEEDS,
            max_spend_usd=max_spend_usd - MAX_CANARY_COST_USD,
            max_parallel_cells=MAX_PARALLEL_CELLS,
            resume=scored_root.exists(),
            provider_factory=provider_factory,
            preflight_fn=preflight_fn,
            campaign_id=CAMPAIGN_ID,
            abort_on_operational_failure=True,
            candidate=QWEN_CANDIDATE,
            prompt=PROMPT,
            prompt_id="procurement_allocation_prompt_v1",
            treatment_id="unscaffolded_control",
            max_new_trajectories=TRAJECTORIES_PER_CHECKPOINT,
            max_action_attempts=MAX_ACTION_ATTEMPTS,
            retryable_conditions=RETRY_CONDITIONS,
            retry_backoff=RETRY_BACKOFF,
            retry_base_seconds=RETRY_BASE_SECONDS,
            retry_after_max_seconds=RETRY_AFTER_MAX_SECONDS,
            max_cost_usd_per_trajectory=MAX_TRAJECTORY_COST_USD,
        )
    status = _status(canary=canary, artifact=artifact)
    _replace_json(run_root / "campaign_status.json", status)
    return status


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument(
        "--max-spend-usd", type=float, default=HARD_TOTAL_COST_CEILING_USD
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    arguments = parser.parse_args(argv)
    if not arguments.execute:
        print(json.dumps(build_plan(), indent=2, sort_keys=True))
        return 0
    status = asyncio.run(
        run_campaign(
            run_root=arguments.run_root,
            max_spend_usd=arguments.max_spend_usd,
            resume=arguments.resume,
        )
    )
    print(json.dumps(status, indent=2, sort_keys=True))
    if status["summary"]["execution_qualified"]:
        return 0
    if status["summary"]["operational_failure_count"]:
        return 2
    if not status["summary"]["failure_free_checkpoint"]:
        return 3
    return 4


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CAMPAIGN_ID",
    "HARD_TOTAL_COST_CEILING_USD",
    "PAIRED_INFERENCE_SEEDS",
    "QWEN_CANDIDATE",
    "build_plan",
    "run_admission_canary",
    "run_campaign",
]
