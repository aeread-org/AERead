"""Paired, cluster-aware Housing reasoning-condition experiments."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

from .execution import EvidenceStore, execute_plan_cell
from .housing import HousingSmokeSetup, build_housing_smoke
from .resolver import canonical_json_bytes


def _derived_nonnegative_int(namespace: str, *values: int) -> int:
    payload = ":".join((namespace, *(str(value) for value in values))).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big") & 0x7FFF_FFFF


def derive_world_seeds(*, master_seed: int, count: int) -> tuple[int, ...]:
    """Derive a version-stable, outcome-blind panel of unique world seeds."""

    if isinstance(master_seed, bool) or not isinstance(master_seed, int) or master_seed < 0:
        raise ValueError("master_seed must be a non-negative integer")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("count must be a positive integer")
    seeds: list[int] = []
    seen: set[int] = set()
    counter = 0
    while len(seeds) < count:
        candidate = _derived_nonnegative_int("housing_panel_v1", master_seed, counter)
        counter += 1
        if candidate in seen:
            continue
        seen.add(candidate)
        seeds.append(candidate)
    return tuple(seeds)


def paired_inference_seed(
    *, base_seed: int, world_seed: int, replicate_index: int
) -> int:
    """Return the same provider seed for paired conditions of one world replicate."""

    for name, value in (
        ("base_seed", base_seed),
        ("world_seed", world_seed),
        ("replicate_index", replicate_index),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    return _derived_nonnegative_int(
        "housing_inference_seed_v1", base_seed, world_seed, replicate_index
    )


def build_housing_condition_setup(
    *,
    condition_id: str,
    reasoning_effort: str,
    world_seeds: Sequence[int],
    replicates: int,
    tenant_model: str,
    tenant_revision: str,
    num_tenants: int = 6,
    num_listings: int = 4,
    rounds: int = 4,
    inference_seed_base: int = 87001,
) -> HousingSmokeSetup:
    """Seal one arm of the paired Housing reasoning experiment."""

    expected_effort = {
        "reasoning_none_v1": "none",
        "reasoning_low_v1": "low",
    }
    if expected_effort.get(condition_id) != reasoning_effort:
        raise ValueError(
            "condition_id and reasoning_effort must be one of the locked "
            "none/low experiment arms"
        )
    return build_housing_smoke(
        tenant_provider="openrouter",
        tenant_model=tenant_model,
        tenant_revision=tenant_revision,
        world_seeds=tuple(world_seeds),
        replicates=replicates,
        reasoning_condition_id=condition_id,
        reasoning_effort=reasoning_effort,
        inference_seed_base=inference_seed_base,
        num_tenants=num_tenants,
        num_listings=num_listings,
        rounds=rounds,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sealed_result(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload.pop("result_sha256", None)
    return {
        **payload,
        "result_sha256": _sha256_bytes(canonical_json_bytes(payload)),
    }


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    payload = canonical_json_bytes(value)
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _verify_result_digest(row: Mapping[str, Any], *, path: Path) -> None:
    claimed = row.get("result_sha256")
    payload = dict(row)
    payload.pop("result_sha256", None)
    actual = _sha256_bytes(canonical_json_bytes(payload))
    if claimed != actual:
        raise ValueError(f"result digest mismatch: {path}")


def _evidence_fingerprint(evidence: EvidenceStore) -> tuple[str, str | None]:
    events = evidence.read_events()
    return (
        _sha256_bytes(evidence.events_path.read_bytes()),
        events[-1].event_hash if events else None,
    )


def _load_event_payload(evidence: EvidenceStore, event: Any) -> Any:
    payload = (evidence.root / event.payload_ref).read_bytes()
    return json.loads(payload)


def _reasoning_usage(evidence: EvidenceStore) -> tuple[int, bool]:
    reasoning_tokens = 0
    reasoning_text_present = False
    for event in evidence.read_events():
        if event.event_type not in {"provider_call_succeeded", "provider_call_failed"}:
            continue
        payload = _load_event_payload(evidence, event)
        raw = payload.get("provider_result", {}).get("raw_response")
        if not isinstance(raw, Mapping):
            continue
        usage = raw.get("usage")
        if isinstance(usage, Mapping):
            details = usage.get("completion_tokens_details")
            if isinstance(details, Mapping):
                value = details.get("reasoning_tokens", 0)
                if isinstance(value, int) and not isinstance(value, bool):
                    reasoning_tokens += max(0, value)
        choices = raw.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, Mapping):
                    continue
                message = choice.get("message")
                if not isinstance(message, Mapping):
                    continue
                for key in ("reasoning", "reasoning_content", "reasoning_details"):
                    value = message.get(key)
                    if value not in (None, "", [], {}):
                        reasoning_text_present = True
    return reasoning_tokens, reasoning_text_present


def _event_execution_metrics(evidence: EvidenceStore) -> dict[str, Any]:
    provider_calls = 0
    external_provider_calls = 0
    length_retries = 0
    logical_action_ids: set[str] = set()
    total_cost_usd = 0.0
    for event in evidence.read_events():
        payload = _load_event_payload(evidence, event)
        if event.event_type == "logical_action_started" and event.logical_action_id:
            logical_action_ids.add(event.logical_action_id)
        if event.event_type == "provider_call_started":
            request = payload.get("request") if isinstance(payload, Mapping) else None
            if isinstance(request, Mapping) and request.get("provider") == "openrouter":
                external_provider_calls += 1
        if event.event_type in {
            "provider_call_succeeded",
            "provider_call_failed",
            "provider_call_outcome_unknown",
        }:
            provider_calls += 1
            cost = payload.get("cost_usd") if isinstance(payload, Mapping) else None
            if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                total_cost_usd += float(cost)
        if event.event_type == "action_attempt_started":
            if isinstance(payload, Mapping) and payload.get("retry_reason") == "length":
                length_retries += 1
    reasoning_tokens, reasoning_text_present = _reasoning_usage(evidence)
    events_sha256, final_event_hash = _evidence_fingerprint(evidence)
    return {
        "evidence_verified": True,
        "events_sha256": events_sha256,
        "final_event_hash": final_event_hash,
        "logical_action_count": len(logical_action_ids),
        "provider_call_count": provider_calls,
        "external_provider_call_count": external_provider_calls,
        "length_retry_count": length_retries,
        "reasoning_tokens": reasoning_tokens,
        "reasoning_text_present": reasoning_text_present,
        "cost_usd": total_cost_usd,
    }


def _failure_evidence_fields(
    *, evidence_root: Path, run_plan_id: str, cell_id: str
) -> dict[str, Any]:
    cell_root = evidence_root / run_plan_id / cell_id
    if not cell_root.is_dir():
        return {"evidence_verified": False, "cost_usd": 0.0}
    attempts = sorted(path for path in cell_root.iterdir() if path.is_dir())
    if len(attempts) != 1:
        return {"evidence_verified": False, "cost_usd": 0.0}
    try:
        evidence = EvidenceStore.audit_existing(attempts[0])
    except Exception:
        return {
            "evidence_dir": str(attempts[0].resolve()),
            "evidence_verified": False,
            "cost_usd": 0.0,
        }
    return {
        "evidence_dir": str(evidence.root.resolve()),
        **_event_execution_metrics(evidence),
    }


def _execution_counts(execution: Any, setup: HousingSmokeSetup) -> dict[str, int]:
    provider_by_profile = {
        profile.profile_id: profile.model.provider
        for profile in setup.plan.agent_profiles
    }
    provider_calls = 0
    external_provider_calls = 0
    length_retries = 0
    for logical_action in execution.action_executions:
        for attempt in logical_action.attempts:
            provider_calls += len(attempt.provider_calls)
            if provider_by_profile.get(logical_action.profile_id) == "openrouter":
                external_provider_calls += len(attempt.provider_calls)
            if attempt.retry_reason == "length":
                length_retries += 1
    return {
        "provider_call_count": provider_calls,
        "external_provider_call_count": external_provider_calls,
        "length_retry_count": length_retries,
    }


def _result_from_execution(
    *,
    setup: HousingSmokeSetup,
    condition_id: str,
    cell: Any,
    execution: Any,
) -> dict[str, Any]:
    outcome = dict(execution.episode_result.outcome)
    evidence = EvidenceStore.audit_existing(execution.evidence.root)
    events_sha256, final_event_hash = _evidence_fingerprint(evidence)
    reasoning_tokens, reasoning_text_present = _reasoning_usage(evidence)
    return {
        "condition_id": condition_id,
        "run_plan_id": setup.plan.run_plan_id,
        "cell_id": cell.cell_id,
        "case_id": cell.case_id,
        "cluster_id": cell.cluster_id,
        "pair_id": cell.pair_id,
        "world_seed": cell.world_seed,
        "replicate_index": cell.replicate_index,
        "status": "completed",
        "episode_attempt_id": execution.episode_attempt_id,
        "evidence_dir": str(evidence.root.resolve()),
        "evidence_verified": True,
        "events_sha256": events_sha256,
        "final_event_hash": final_event_hash,
        "within_case_score": outcome.get("within_case_score"),
        "social_welfare": outcome.get("social_welfare"),
        "feasible_floor": outcome.get("feasible_floor"),
        "baseline_total": outcome.get("baseline_total"),
        "oracle_total": outcome.get("oracle_total"),
        "tenant_payoffs": outcome.get("tenant_payoffs"),
        "landlord_payoffs": outcome.get("landlord_payoffs"),
        "ir_violations": outcome.get("ir_violations"),
        "wasted_contacts": outcome.get("wasted_contacts"),
        "logical_action_count": execution.episode_result.logical_action_count,
        "cost_usd": execution.total_cost_usd,
        "reasoning_tokens": reasoning_tokens,
        "reasoning_text_present": reasoning_text_present,
        **_execution_counts(execution, setup),
    }


def read_condition_results(
    output_root: str | Path,
    *,
    condition_id: str,
    verify_evidence: bool = True,
) -> list[dict[str, Any]]:
    """Read sealed per-cell results, failing closed on tampering."""

    results_dir = Path(output_root) / condition_id / "results"
    if not results_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(results_dir.glob("*.json")):
        try:
            row = json.loads(path.read_bytes())
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid condition result: {path}") from error
        if not isinstance(row, dict):
            raise ValueError(f"condition result must be an object: {path}")
        _verify_result_digest(row, path=path)
        if row.get("condition_id") != condition_id:
            raise ValueError(f"condition result identity mismatch: {path}")
        if verify_evidence and row.get("evidence_verified") is True:
            evidence = EvidenceStore.audit_existing(row.get("evidence_dir", ""))
            events_sha256, final_event_hash = _evidence_fingerprint(evidence)
            if (
                events_sha256 != row.get("events_sha256")
                or final_event_hash != row.get("final_event_hash")
            ):
                raise ValueError(f"condition evidence fingerprint mismatch: {path}")
        rows.append(row)
    return rows


async def run_condition_batch(
    *,
    setup: HousingSmokeSetup,
    condition_id: str,
    output_root: str | Path,
    providers: Mapping[str, Any],
    concurrency: int,
    spend_limit_usd: float,
) -> dict[str, Any]:
    """Execute or resume one condition without replacing failed trajectories."""

    if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency < 1:
        raise ValueError("concurrency must be a positive integer")
    if (
        isinstance(spend_limit_usd, bool)
        or not isinstance(spend_limit_usd, (int, float))
        or not math.isfinite(float(spend_limit_usd))
        or spend_limit_usd <= 0
    ):
        raise ValueError("spend_limit_usd must be a positive finite number")
    profile_conditions = {
        profile.reasoning.condition_id
        for profile in setup.plan.agent_profiles
        if profile.model.provider == "openrouter"
    }
    if profile_conditions != {condition_id}:
        raise ValueError("condition_id does not match the sealed tenant profile")

    output = Path(output_root)
    condition_root = output / condition_id
    evidence_root = condition_root / "evidence"
    results_dir = condition_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    existing_rows = read_condition_results(
        output, condition_id=condition_id, verify_evidence=True
    )
    cell_by_id = {cell.cell_id: cell for cell in setup.plan.cells}
    existing_by_cell: dict[str, dict[str, Any]] = {}
    for row in existing_rows:
        cell_id = row.get("cell_id")
        if cell_id not in cell_by_id or row.get("run_plan_id") != setup.plan.run_plan_id:
            raise ValueError("existing result does not belong to the sealed RunPlan")
        if cell_id in existing_by_cell:
            raise ValueError(f"duplicate existing cell result: {cell_id}")
        existing_by_cell[cell_id] = row

    pending = [cell for cell in setup.plan.cells if cell.cell_id not in existing_by_cell]
    queue: asyncio.Queue[Any] = asyncio.Queue()
    for cell in pending:
        queue.put_nowait(cell)
    total_cost = sum(float(row.get("cost_usd") or 0.0) for row in existing_rows)
    executed_count = 0
    new_rows: list[dict[str, Any]] = []
    state_lock = asyncio.Lock()
    stop_reason: str | None = None

    async def worker() -> None:
        nonlocal total_cost, executed_count, stop_reason
        while True:
            async with state_lock:
                if total_cost >= spend_limit_usd:
                    stop_reason = "spend_limit_reached"
                    return
                try:
                    cell = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
            try:
                execution = await execute_plan_cell(
                    plan=setup.plan,
                    cell_id=cell.cell_id,
                    registry=setup.registry,
                    evidence_root=evidence_root,
                    prompt_sources=setup.prompt_sources,
                    providers=providers,
                    pricing=setup.pricing,
                    episode_attempt_ordinal=0,
                )
                row = _result_from_execution(
                    setup=setup,
                    condition_id=condition_id,
                    cell=cell,
                    execution=execution,
                )
            except Exception as error:
                row = {
                    "condition_id": condition_id,
                    "run_plan_id": setup.plan.run_plan_id,
                    "cell_id": cell.cell_id,
                    "case_id": cell.case_id,
                    "cluster_id": cell.cluster_id,
                    "pair_id": cell.pair_id,
                    "world_seed": cell.world_seed,
                    "replicate_index": cell.replicate_index,
                    "status": "operational_failure",
                    "failure_type": type(error).__name__,
                    "within_case_score": None,
                    **_failure_evidence_fields(
                        evidence_root=evidence_root,
                        run_plan_id=setup.plan.run_plan_id,
                        cell_id=cell.cell_id,
                    ),
                }
            sealed = _sealed_result(row)
            _atomic_write_json(results_dir / f"{cell.cell_id}.json", sealed)
            async with state_lock:
                new_rows.append(sealed)
                executed_count += 1
                total_cost += float(sealed.get("cost_usd") or 0.0)
            queue.task_done()

    await asyncio.gather(*(worker() for _ in range(concurrency)))
    all_rows = [*existing_rows, *new_rows]
    completed_count = sum(row.get("status") == "completed" for row in all_rows)
    failure_count = sum(row.get("status") != "completed" for row in all_rows)
    return {
        "condition_id": condition_id,
        "planned_count": len(setup.plan.cells),
        "executed_count": executed_count,
        "resumed_count": len(existing_rows),
        "completed_count": completed_count,
        "failure_count": failure_count,
        "pending_count": queue.qsize(),
        "total_cost_usd": total_cost,
        "stop_reason": stop_reason,
    }


def _validate_paired_setups(
    setups: Mapping[str, HousingSmokeSetup],
) -> tuple[tuple[str, str], list[tuple[int, int]]]:
    expected = ("reasoning_none_v1", "reasoning_low_v1")
    if set(setups) != set(expected):
        raise ValueError(f"paired setups must contain exactly {list(expected)}")
    cells_by_condition = {
        condition: {
            (cell.world_seed, cell.replicate_index): cell
            for cell in setups[condition].plan.cells
        }
        for condition in expected
    }
    identities = list(cells_by_condition[expected[0]])
    if set(identities) != set(cells_by_condition[expected[1]]):
        raise ValueError("paired conditions do not contain identical world replicates")
    for identity in identities:
        left = cells_by_condition[expected[0]][identity]
        right = cells_by_condition[expected[1]][identity]
        if left.cluster_id != right.cluster_id or left.pair_id != right.pair_id:
            raise ValueError(f"paired cell identity differs for {identity}")
    return expected, identities


async def run_paired_batch(
    *,
    setups: Mapping[str, HousingSmokeSetup],
    output_root: str | Path,
    providers: Mapping[str, Any],
    concurrency: int,
    spend_limit_usd: float,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """Run both reasoning arms under one interleaved queue and spend boundary."""

    if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency < 1:
        raise ValueError("concurrency must be a positive integer")
    if (
        isinstance(spend_limit_usd, bool)
        or not isinstance(spend_limit_usd, (int, float))
        or not math.isfinite(float(spend_limit_usd))
        or spend_limit_usd <= 0
    ):
        raise ValueError("spend_limit_usd must be a positive finite number")
    conditions, identities = _validate_paired_setups(setups)
    output = Path(output_root)
    existing_by_condition: dict[str, dict[str, dict[str, Any]]] = {}
    all_existing_rows: list[dict[str, Any]] = []
    for condition in conditions:
        rows = read_condition_results(
            output, condition_id=condition, verify_evidence=True
        )
        valid_cell_ids = {cell.cell_id for cell in setups[condition].plan.cells}
        by_cell: dict[str, dict[str, Any]] = {}
        for row in rows:
            cell_id = row.get("cell_id")
            if (
                cell_id not in valid_cell_ids
                or row.get("run_plan_id") != setups[condition].plan.run_plan_id
            ):
                raise ValueError("existing result does not belong to the sealed RunPlan")
            if cell_id in by_cell:
                raise ValueError(f"duplicate existing cell result: {cell_id}")
            by_cell[cell_id] = row
        existing_by_condition[condition] = by_cell
        all_existing_rows.extend(rows)

    cells_by_condition = {
        condition: {
            (cell.world_seed, cell.replicate_index): cell
            for cell in setups[condition].plan.cells
        }
        for condition in conditions
    }
    tasks: list[tuple[str, Any]] = []
    for world_seed, replicate_index in identities:
        order = list(conditions)
        if _derived_nonnegative_int(
            "housing_condition_order_v1", world_seed, replicate_index
        ) % 2:
            order.reverse()
        for condition in order:
            cell = cells_by_condition[condition][(world_seed, replicate_index)]
            if cell.cell_id not in existing_by_condition[condition]:
                tasks.append((condition, cell))

    queue: asyncio.Queue[Any] = asyncio.Queue()
    for task in tasks:
        queue.put_nowait(task)
    total_cost = sum(float(row.get("cost_usd") or 0.0) for row in all_existing_rows)
    executed_count = 0
    new_rows: list[dict[str, Any]] = []
    state_lock = asyncio.Lock()
    stop_reason: str | None = None

    async def worker() -> None:
        nonlocal total_cost, executed_count, stop_reason
        while True:
            async with state_lock:
                if total_cost >= spend_limit_usd:
                    stop_reason = "spend_limit_reached"
                    return
                try:
                    condition, cell = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
            setup = setups[condition]
            evidence_root = output / condition / "evidence"
            results_dir = output / condition / "results"
            results_dir.mkdir(parents=True, exist_ok=True)
            try:
                execution = await execute_plan_cell(
                    plan=setup.plan,
                    cell_id=cell.cell_id,
                    registry=setup.registry,
                    evidence_root=evidence_root,
                    prompt_sources=setup.prompt_sources,
                    providers=providers,
                    pricing=setup.pricing,
                    episode_attempt_ordinal=0,
                )
                row = _result_from_execution(
                    setup=setup,
                    condition_id=condition,
                    cell=cell,
                    execution=execution,
                )
            except Exception as error:
                row = {
                    "condition_id": condition,
                    "run_plan_id": setup.plan.run_plan_id,
                    "cell_id": cell.cell_id,
                    "case_id": cell.case_id,
                    "cluster_id": cell.cluster_id,
                    "pair_id": cell.pair_id,
                    "world_seed": cell.world_seed,
                    "replicate_index": cell.replicate_index,
                    "status": "operational_failure",
                    "failure_type": type(error).__name__,
                    "within_case_score": None,
                    **_failure_evidence_fields(
                        evidence_root=evidence_root,
                        run_plan_id=setup.plan.run_plan_id,
                        cell_id=cell.cell_id,
                    ),
                }
            sealed = _sealed_result(row)
            _atomic_write_json(results_dir / f"{cell.cell_id}.json", sealed)
            async with state_lock:
                new_rows.append(sealed)
                executed_count += 1
                total_cost += float(sealed.get("cost_usd") or 0.0)
                progress = {
                    "condition_id": condition,
                    "world_seed": cell.world_seed,
                    "replicate_index": cell.replicate_index,
                    "status": sealed.get("status"),
                    "executed_count": executed_count,
                    "total_cost_usd": total_cost,
                }
            if progress_callback is not None:
                callback_result = progress_callback(progress)
                if asyncio.iscoroutine(callback_result):
                    await callback_result
            queue.task_done()

    await asyncio.gather(*(worker() for _ in range(concurrency)))
    all_rows = [*all_existing_rows, *new_rows]
    completed_by_condition = {
        condition: sum(
            row.get("status") == "completed"
            for row in all_rows
            if row.get("condition_id") == condition
        )
        for condition in conditions
    }
    failure_by_condition = {
        condition: sum(
            row.get("status") != "completed"
            for row in all_rows
            if row.get("condition_id") == condition
        )
        for condition in conditions
    }
    return {
        "planned_count": sum(len(setup.plan.cells) for setup in setups.values()),
        "executed_count": executed_count,
        "resumed_count": len(all_existing_rows),
        "completed_count": sum(completed_by_condition.values()),
        "failure_count": sum(failure_by_condition.values()),
        "completed_count_by_condition": completed_by_condition,
        "failure_count_by_condition": failure_by_condition,
        "pending_count": queue.qsize(),
        "total_cost_usd": total_cost,
        "stop_reason": stop_reason,
    }


def _score_row(row: Mapping[str, Any]) -> float | None:
    if row.get("status") != "completed":
        return None
    score = row.get("within_case_score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    numeric = float(score)
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise ValueError("completed within_case_score must be finite and in [0, 1]")
    return numeric


def _percentile_interval(values: np.ndarray) -> list[float]:
    return [
        float(np.percentile(values, 2.5)),
        float(np.percentile(values, 97.5)),
    ]


def analyze_paired_results(
    rows: Iterable[Mapping[str, Any]],
    *,
    control_condition: str,
    treatment_condition: str,
    expected_replicates: int,
    bootstrap_draws: int = 10_000,
    bootstrap_seed: int = 20260826,
) -> dict[str, Any]:
    """Aggregate nested replicates and compare conditions at the world-cluster level."""

    if control_condition == treatment_condition:
        raise ValueError("control and treatment conditions must differ")
    if expected_replicates < 1:
        raise ValueError("expected_replicates must be positive")
    if bootstrap_draws < 1:
        raise ValueError("bootstrap_draws must be positive")
    materialized = [dict(row) for row in rows]
    allowed_conditions = {control_condition, treatment_condition}
    by_identity: dict[tuple[str, int, int], dict[str, Any]] = {}
    failures = {control_condition: 0, treatment_condition: 0}
    for row in materialized:
        condition = row.get("condition_id")
        world_seed = row.get("world_seed")
        replicate = row.get("replicate_index")
        if condition not in allowed_conditions:
            raise ValueError(f"unexpected condition_id: {condition!r}")
        if isinstance(world_seed, bool) or not isinstance(world_seed, int):
            raise ValueError("world_seed must be an integer")
        if isinstance(replicate, bool) or not isinstance(replicate, int):
            raise ValueError("replicate_index must be an integer")
        identity = (condition, world_seed, replicate)
        if identity in by_identity:
            raise ValueError(f"duplicate trajectory identity: {identity}")
        by_identity[identity] = row
        if _score_row(row) is None:
            failures[condition] += 1

    worlds = sorted({identity[1] for identity in by_identity})
    condition_world_means: dict[str, dict[int, float]] = {
        control_condition: {},
        treatment_condition: {},
    }
    incomplete_worlds: list[int] = []
    complete_differences: list[float] = []
    complete_control: list[float] = []
    complete_treatment: list[float] = []
    lower_differences: list[float] = []
    upper_differences: list[float] = []

    for world_seed in worlds:
        bounds: dict[str, tuple[float, float]] = {}
        complete = True
        for condition in (control_condition, treatment_condition):
            scores: list[float] = []
            replicates_seen: set[int] = set()
            for replicate in range(expected_replicates):
                row = by_identity.get((condition, world_seed, replicate))
                if row is None:
                    continue
                replicates_seen.add(replicate)
                score = _score_row(row)
                if score is not None:
                    scores.append(score)
            condition_complete = (
                replicates_seen == set(range(expected_replicates))
                and len(scores) == expected_replicates
            )
            if condition_complete:
                mean_score = float(np.mean(scores))
                condition_world_means[condition][world_seed] = mean_score
                bounds[condition] = (mean_score, mean_score)
            else:
                complete = False
                bounds[condition] = (0.0, 1.0)
        control_lower, control_upper = bounds[control_condition]
        treatment_lower, treatment_upper = bounds[treatment_condition]
        lower_differences.append(treatment_lower - control_upper)
        upper_differences.append(treatment_upper - control_lower)
        if complete:
            control_mean = condition_world_means[control_condition][world_seed]
            treatment_mean = condition_world_means[treatment_condition][world_seed]
            complete_control.append(control_mean)
            complete_treatment.append(treatment_mean)
            complete_differences.append(treatment_mean - control_mean)
        else:
            incomplete_worlds.append(world_seed)

    if not complete_differences:
        raise ValueError("paired analysis has no complete world clusters")
    difference_array = np.asarray(complete_differences, dtype=float)
    rng = np.random.default_rng(bootstrap_seed)
    draws = rng.choice(
        difference_array,
        size=(bootstrap_draws, len(difference_array)),
        replace=True,
    ).mean(axis=1)
    if len(difference_array) > 1:
        sem = float(stats.sem(difference_array))
        t_critical = float(stats.t.ppf(0.975, df=len(difference_array) - 1))
        paired_t_interval = [
            float(difference_array.mean() - t_critical * sem),
            float(difference_array.mean() + t_critical * sem),
        ]
    else:
        paired_t_interval = [float(difference_array[0]), float(difference_array[0])]

    return {
        "trajectory_count": len(materialized),
        "planned_world_count": len(worlds),
        "complete_pair_world_count": len(complete_differences),
        "incomplete_worlds": incomplete_worlds,
        "expected_replicates": expected_replicates,
        "condition_means": {
            control_condition: float(np.mean(complete_control)),
            treatment_condition: float(np.mean(complete_treatment)),
        },
        "mean_paired_difference": float(difference_array.mean()),
        "cluster_bootstrap_95": _percentile_interval(draws),
        "paired_t_95": paired_t_interval,
        "missingness_difference_bounds": [
            float(np.mean(lower_differences)),
            float(np.mean(upper_differences)),
        ],
        "operational_failure_count_by_condition": failures,
        "resampling_unit": "world_seed",
        "bootstrap_draws": bootstrap_draws,
        "bootstrap_seed": bootstrap_seed,
    }


__all__ = [
    "analyze_paired_results",
    "build_housing_condition_setup",
    "derive_world_seeds",
    "paired_inference_seed",
    "read_condition_results",
    "run_condition_batch",
    "run_paired_batch",
]
