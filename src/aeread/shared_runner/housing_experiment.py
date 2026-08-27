"""Paired, cluster-aware Housing reasoning-condition experiments."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import math
import os
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from aeread import housing_env as hz

from .execution import EvidenceStore, OpenRouterChatClient, execute_plan_cell
from .housing import (
    HousingScriptedLandlordProvider,
    HousingScriptedTenantProvider,
    HousingSmokeSetup,
    OpenRouterRoutePin,
    build_housing_smoke,
    finalize_housing_execution,
    finalize_housing_failure,
)
from .resolver import canonical_json_bytes
from .receipts import read_evaluation_receipt
from .paired_analysis import analyze_paired_results, analyze_paired_results_if_available


CONFIRMATORY_EXPERIMENT_ROUTE = OpenRouterRoutePin(
    provider="Parasail",
    quantization="fp8",
    canonical_model="deepseek/deepseek-v4-flash-20260731",
    input_per_million=0.14,
    cached_input_per_million=0.07,
    output_per_million=0.28,
    pricing_id="openrouter_parasail_2026-08-26_deepseek-v4-flash-0731",
)


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


def housing_within_case_score_support(
    *, world_seed: int, num_tenants: int = 6, num_listings: int = 4
) -> tuple[float, float]:
    """Return exact legal-outcome support for ``R / U`` on one Housing world.

    ``L = 0`` is a lower bound on the optimum, not on every realized outcome.
    A legal matching can therefore have negative welfare. The minimum is the
    negative of the max-weight matching on the negated surplus matrix, with
    unmatched seats retained as zero-weight options.
    """

    for name, value in (
        ("world_seed", world_seed),
        ("num_tenants", num_tenants),
        ("num_listings", num_listings),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    if num_tenants < 1 or num_listings < 1:
        raise ValueError("num_tenants and num_listings must be positive")
    world = hz.make_bid_world(num_tenants, num_listings, seed=world_seed)
    optimum = hz.assignment_oracle(world.surplus).total
    if optimum <= 0:
        raise ValueError("within-case score support requires a positive optimum")
    worst_magnitude = hz.assignment_oracle(
        [[-float(value) for value in row] for row in world.surplus]
    ).total
    return -float(worst_magnitude) / float(optimum), 1.0


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
    openrouter_route: OpenRouterRoutePin = CONFIRMATORY_EXPERIMENT_ROUTE,
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
        openrouter_route=openrouter_route,
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
        provider_result = (
            payload.get("provider_result") if isinstance(payload, Mapping) else None
        )
        raw = (
            provider_result.get("raw_response")
            if isinstance(provider_result, Mapping)
            else None
        )
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
    external_call_ids: set[str] = set()
    request_seeds: set[int] = set()
    reasoning_efforts: set[str] = set()
    route_providers: set[str] = set()
    resolved_models: set[str] = set()
    total_cost_usd = 0.0
    unknown_cost_provider_calls = 0
    for event in evidence.read_events():
        payload = _load_event_payload(evidence, event)
        if event.event_type == "logical_action_started" and event.logical_action_id:
            logical_action_ids.add(event.logical_action_id)
        if event.event_type == "provider_call_started":
            request = payload.get("request") if isinstance(payload, Mapping) else None
            if isinstance(request, Mapping) and request.get("provider") == "openrouter":
                external_provider_calls += 1
                if event.provider_call_id:
                    external_call_ids.add(event.provider_call_id)
                seed = request.get("seed")
                if isinstance(seed, int) and not isinstance(seed, bool):
                    request_seeds.add(seed)
                effort = request.get("reasoning_effort")
                if isinstance(effort, str) and effort:
                    reasoning_efforts.add(effort)
                metadata = request.get("provider_metadata")
                if isinstance(metadata, Mapping):
                    route = metadata.get("route_provider")
                    if isinstance(route, str) and route:
                        route_providers.add(route)
        if event.event_type in {
            "provider_call_succeeded",
            "provider_call_failed",
            "provider_call_outcome_unknown",
        }:
            provider_calls += 1
            cost = payload.get("cost_usd") if isinstance(payload, Mapping) else None
            if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                total_cost_usd += float(cost)
            elif cost == "unknown":
                unknown_cost_provider_calls += 1
            provider_result = (
                payload.get("provider_result") if isinstance(payload, Mapping) else None
            )
            if (
                event.provider_call_id in external_call_ids
                and isinstance(provider_result, Mapping)
            ):
                resolved_model = provider_result.get("resolved_model")
                if isinstance(resolved_model, str) and resolved_model:
                    resolved_models.add(resolved_model)
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
        "request_seeds": sorted(request_seeds),
        "reasoning_efforts": sorted(reasoning_efforts),
        "route_providers": sorted(route_providers),
        "resolved_models": sorted(resolved_models),
        "cost_usd": total_cost_usd,
        "unknown_cost_provider_call_count": unknown_cost_provider_calls,
    }


def _failure_evidence_fields(
    *, evidence_root: Path, run_plan_id: str, cell_id: str
) -> dict[str, Any]:
    cell_root = evidence_root / run_plan_id / cell_id
    if not cell_root.is_dir():
        return {
            "evidence_verified": False,
            "cost_usd": 0.0,
            "unknown_cost_provider_call_count": 0,
        }
    attempts = sorted(path for path in cell_root.iterdir() if path.is_dir())
    if len(attempts) != 1:
        return {
            "evidence_verified": False,
            "cost_usd": 0.0,
            "unknown_cost_provider_call_count": len(attempts),
        }
    try:
        evidence = EvidenceStore.audit_existing(attempts[0])
    except Exception:
        return {
            "evidence_dir": str(attempts[0].resolve()),
            "evidence_verified": False,
            "cost_usd": 0.0,
            "unknown_cost_provider_call_count": 1,
        }
    return {
        "evidence_dir": str(evidence.root.resolve()),
        **_event_execution_metrics(evidence),
    }


def _failure_receipt_fields(
    *,
    setup: HousingSmokeSetup,
    cell: Any,
    evidence_root: Path,
    error: BaseException,
) -> dict[str, Any]:
    try:
        receipt = finalize_housing_failure(
            setup=setup,
            cell_id=cell.cell_id,
            evidence_root=evidence_root,
            error=error,
        )
    except Exception as receipt_error:
        return {"receipt_failure_type": type(receipt_error).__name__}
    attempt_root = (
        evidence_root
        / setup.plan.run_plan_id
        / cell.cell_id
        / receipt.episode_attempt_id
    )
    return {
        "measurement_status": receipt.status,
        "receipt_sha256": receipt.receipt_sha256,
        "receipt_path": str((attempt_root / "evaluation_receipt.json").resolve()),
        "replay_level": receipt.replay_level,
    }


def _recover_orphan_attempts(
    *,
    setup: HousingSmokeSetup,
    condition_id: str,
    output_root: Path,
) -> int:
    """Seal interrupted evidence as missingness; never rerun an existing attempt."""

    condition_root = output_root / condition_id
    evidence_root = condition_root / "evidence"
    results_dir = condition_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    recovered = 0
    for cell in setup.plan.cells:
        result_path = results_dir / f"{cell.cell_id}.json"
        if result_path.exists():
            continue
        cell_root = evidence_root / setup.plan.run_plan_id / cell.cell_id
        attempts = (
            sorted(path for path in cell_root.iterdir() if path.is_dir())
            if cell_root.is_dir()
            else []
        )
        if not attempts:
            continue
        receipt_fields = _failure_receipt_fields(
            setup=setup,
            cell=cell,
            evidence_root=evidence_root,
            error=RuntimeError(
                "interrupted Housing attempt recovered without rerunning side effects"
            ),
        )
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
            "failure_type": "OrphanedAttemptRecovered",
            "interruption_recovered": True,
            "within_case_score": None,
            **_failure_evidence_fields(
                evidence_root=evidence_root,
                run_plan_id=setup.plan.run_plan_id,
                cell_id=cell.cell_id,
            ),
            **receipt_fields,
        }
        _atomic_write_json(result_path, _sealed_result(row))
        recovered += 1
    return recovered


def _result_from_execution(
    *,
    setup: HousingSmokeSetup,
    condition_id: str,
    cell: Any,
    execution: Any,
) -> dict[str, Any]:
    outcome = dict(execution.episode_result.outcome)
    receipt = finalize_housing_execution(setup=setup, execution=execution)
    evidence = EvidenceStore.audit_existing(execution.evidence.root)
    metrics = _event_execution_metrics(evidence)
    if not math.isclose(
        float(metrics["cost_usd"]),
        float(execution.total_cost_usd),
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        raise ValueError("execution cost does not reconcile to provider evidence")
    return {
        "condition_id": condition_id,
        "run_plan_id": setup.plan.run_plan_id,
        "cell_id": cell.cell_id,
        "case_id": cell.case_id,
        "cluster_id": cell.cluster_id,
        "pair_id": cell.pair_id,
        "world_seed": cell.world_seed,
        "replicate_index": cell.replicate_index,
        "status": (
            "completed" if receipt.inclusion_status == "included" else "invalid_measurement"
        ),
        "measurement_status": receipt.status,
        "receipt_sha256": receipt.receipt_sha256,
        "receipt_path": str(
            (execution.evidence.root / "evaluation_receipt.json").resolve()
        ),
        "replay_level": receipt.replay_level,
        "episode_attempt_id": execution.episode_attempt_id,
        "evidence_dir": str(evidence.root.resolve()),
        "within_case_score": outcome.get("within_case_score"),
        "social_welfare": outcome.get("social_welfare"),
        "feasible_floor": outcome.get("feasible_floor"),
        "baseline_total": outcome.get("baseline_total"),
        "oracle_total": outcome.get("oracle_total"),
        "tenant_payoffs": outcome.get("tenant_payoffs"),
        "landlord_payoffs": outcome.get("landlord_payoffs"),
        "ir_violations": outcome.get("ir_violations"),
        "wasted_contacts": outcome.get("wasted_contacts"),
        **metrics,
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
        if row.get("receipt_sha256") is not None:
            if verify_evidence and row.get("evidence_verified") is not True:
                raise ValueError(f"condition receipt lacks verified evidence: {path}")
            receipt_path_value = row.get("receipt_path")
            evidence_dir_value = row.get("evidence_dir")
            if not isinstance(receipt_path_value, str) or not isinstance(
                evidence_dir_value, str
            ):
                raise ValueError(f"condition receipt is missing: {path}")
            receipt_path = Path(receipt_path_value)
            if receipt_path.resolve() != (
                Path(evidence_dir_value).resolve() / "evaluation_receipt.json"
            ):
                raise ValueError(f"condition receipt path mismatch: {path}")
            try:
                receipt = read_evaluation_receipt(receipt_path)
            except Exception as error:
                raise ValueError(f"condition receipt verification failed: {path}") from error
            if (
                receipt.get("receipt_sha256") != row.get("receipt_sha256")
                or receipt.get("run_plan_id") != row.get("run_plan_id")
                or receipt.get("cell_id") != row.get("cell_id")
                or receipt.get("case_id") != row.get("case_id")
                or receipt.get("status") != row.get("measurement_status")
            ):
                raise ValueError(f"condition receipt identity mismatch: {path}")
            if verify_evidence:
                sealed = evidence.verify_seal()
                if canonical_json_bytes(receipt.get("evidence")) != canonical_json_bytes(
                    dataclasses.asdict(sealed)
                ):
                    raise ValueError(f"condition receipt evidence mismatch: {path}")
        rows.append(row)
    return rows


def validate_reasoning_admission(
    rows: Iterable[Mapping[str, Any]],
    *,
    expected_resolved_model: str,
    expected_route_provider: str,
    expected_paired_cell_count: int,
) -> dict[str, Any]:
    """Prove that the paired provider route applied both reasoning treatments."""

    if (
        isinstance(expected_paired_cell_count, bool)
        or not isinstance(expected_paired_cell_count, int)
        or expected_paired_cell_count < 1
    ):
        raise ValueError("expected_paired_cell_count must be a positive integer")

    conditions = ("reasoning_none_v1", "reasoning_low_v1")
    by_identity: dict[tuple[str, int, int], Mapping[str, Any]] = {}
    for row in rows:
        condition = row.get("condition_id")
        world_seed = row.get("world_seed")
        replicate_index = row.get("replicate_index")
        if condition not in conditions:
            raise ValueError(f"unexpected admission condition: {condition!r}")
        if row.get("status") != "completed" or row.get("evidence_verified") is not True:
            raise ValueError("admission requires completed, verified trajectories")
        if isinstance(world_seed, bool) or not isinstance(world_seed, int):
            raise ValueError("admission world_seed must be an integer")
        if isinstance(replicate_index, bool) or not isinstance(replicate_index, int):
            raise ValueError("admission replicate_index must be an integer")
        identity = (condition, world_seed, replicate_index)
        if identity in by_identity:
            raise ValueError(f"duplicate admission trajectory: {identity}")
        by_identity[identity] = row

    paired_identities = sorted(
        {
            (identity[1], identity[2])
            for identity in by_identity
            if all((condition, identity[1], identity[2]) in by_identity for condition in conditions)
        }
    )
    if len(by_identity) != 2 * len(paired_identities) or not paired_identities:
        raise ValueError("admission trajectories are not complete paired cells")
    if len(paired_identities) != expected_paired_cell_count:
        raise ValueError(
            f"expected {expected_paired_cell_count} paired admission cells, "
            f"received {len(paired_identities)}"
        )

    low_reasoning_tokens = 0
    for world_seed, replicate_index in paired_identities:
        control = by_identity[(conditions[0], world_seed, replicate_index)]
        treatment = by_identity[(conditions[1], world_seed, replicate_index)]
        for condition, row, expected_effort in (
            (conditions[0], control, "none"),
            (conditions[1], treatment, "low"),
        ):
            if row.get("reasoning_efforts") != [expected_effort]:
                raise ValueError(f"{condition} did not preserve its sealed effort")
            if row.get("route_providers") != [expected_route_provider]:
                raise ValueError(f"{condition} used an unexpected provider route")
            if row.get("resolved_models") != [expected_resolved_model]:
                raise ValueError(f"{condition} used an unexpected resolved model")
        if control.get("request_seeds") != treatment.get("request_seeds"):
            raise ValueError("paired admission cells did not use identical request seeds")
        if not control.get("request_seeds"):
            raise ValueError("paired admission cells omitted provider seeds")
        control_tokens = control.get("reasoning_tokens")
        if control_tokens != 0 or control.get("reasoning_text_present") is not False:
            raise ValueError("disabled arm emitted reasoning")
        treatment_tokens = treatment.get("reasoning_tokens")
        if not isinstance(treatment_tokens, int) or isinstance(treatment_tokens, bool):
            raise ValueError("low arm reasoning usage is invalid")
        if treatment_tokens <= 0 and treatment.get("reasoning_text_present") is not True:
            raise ValueError("low arm did not emit reasoning")
        low_reasoning_tokens += treatment_tokens
    return {
        "passed": True,
        "paired_cell_count": len(paired_identities),
        "control_reasoning_tokens": 0,
        "treatment_reasoning_tokens": low_reasoning_tokens,
        "resolved_model": expected_resolved_model,
        "route_provider": expected_route_provider,
        "seed_pairing": "identical_within_world_replicate",
    }


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
    _recover_orphan_attempts(
        setup=setup,
        condition_id=condition_id,
        output_root=output,
    )
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
                receipt_fields = _failure_receipt_fields(
                    setup=setup,
                    cell=cell,
                    evidence_root=evidence_root,
                    error=error,
                )
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
                    **receipt_fields,
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
    max_consecutive_failures: int = 3,
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
    if (
        isinstance(max_consecutive_failures, bool)
        or not isinstance(max_consecutive_failures, int)
        or max_consecutive_failures < 1
    ):
        raise ValueError("max_consecutive_failures must be a positive integer")
    conditions, identities = _validate_paired_setups(setups)
    output = Path(output_root)
    existing_by_condition: dict[str, dict[str, dict[str, Any]]] = {}
    all_existing_rows: list[dict[str, Any]] = []
    for condition in conditions:
        _recover_orphan_attempts(
            setup=setups[condition],
            condition_id=condition,
            output_root=output,
        )
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
    consecutive_failures_by_condition = {condition: 0 for condition in conditions}

    async def worker() -> None:
        nonlocal total_cost, executed_count, stop_reason
        while True:
            async with state_lock:
                if stop_reason == "operational_failure_limit_reached":
                    return
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
                receipt_fields = _failure_receipt_fields(
                    setup=setup,
                    cell=cell,
                    evidence_root=evidence_root,
                    error=error,
                )
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
                    **receipt_fields,
                }
            sealed = _sealed_result(row)
            _atomic_write_json(results_dir / f"{cell.cell_id}.json", sealed)
            async with state_lock:
                new_rows.append(sealed)
                executed_count += 1
                total_cost += float(sealed.get("cost_usd") or 0.0)
                if sealed.get("status") == "completed":
                    consecutive_failures_by_condition[condition] = 0
                else:
                    consecutive_failures_by_condition[condition] += 1
                    if (
                        consecutive_failures_by_condition[condition]
                        >= max_consecutive_failures
                    ):
                        stop_reason = "operational_failure_limit_reached"
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
        "consecutive_failure_count_by_condition": dict(
            consecutive_failures_by_condition
        ),
        "pending_count": queue.qsize(),
        "total_cost_usd": total_cost,
        "stop_reason": stop_reason,
    }


class _ScriptedExperimentTenantProvider:
    """Zero-cost structural preflight for plans sealed to the OpenRouter adapter."""

    def __init__(self) -> None:
        self._delegate = HousingScriptedTenantProvider()

    async def complete(self, request: Any) -> Any:
        translated = dataclasses.replace(request, provider="housing_scripted_tenant")
        return await self._delegate.complete(translated)


def _experiment_setups(
    *,
    world_seeds: Sequence[int],
    replicates: int,
    small_preflight: bool,
    openrouter_route: OpenRouterRoutePin,
) -> dict[str, HousingSmokeSetup]:
    common = {
        "world_seeds": tuple(world_seeds),
        "replicates": replicates,
        "tenant_model": "deepseek/deepseek-v4-flash-0731",
        "tenant_revision": "deepseek/deepseek-v4-flash-20260731",
        "num_tenants": 2 if small_preflight else 6,
        "num_listings": 1 if small_preflight else 4,
        "rounds": 1 if small_preflight else 4,
        "inference_seed_base": 87001,
        "openrouter_route": openrouter_route,
    }
    return {
        "reasoning_none_v1": build_housing_condition_setup(
            condition_id="reasoning_none_v1", reasoning_effort="none", **common
        ),
        "reasoning_low_v1": build_housing_condition_setup(
            condition_id="reasoning_low_v1", reasoning_effort="low", **common
        ),
    }


async def _run_experiment_phase(
    *,
    output_root: Path,
    world_seeds: Sequence[int],
    replicates: int,
    small_preflight: bool,
    tenant_provider: Any,
    concurrency: int,
    spend_limit_usd: float,
    progress_callback: Any | None,
    openrouter_route: OpenRouterRoutePin,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    setups = _experiment_setups(
        world_seeds=world_seeds,
        replicates=replicates,
        small_preflight=small_preflight,
        openrouter_route=openrouter_route,
    )
    batch = await run_paired_batch(
        setups=setups,
        output_root=output_root,
        providers={
            "openrouter": tenant_provider,
            "housing_scripted_landlord": HousingScriptedLandlordProvider(),
        },
        concurrency=concurrency,
        spend_limit_usd=spend_limit_usd,
        max_consecutive_failures=3,
        progress_callback=progress_callback,
    )
    rows: list[dict[str, Any]] = []
    for condition in ("reasoning_none_v1", "reasoning_low_v1"):
        rows.extend(
            read_condition_results(
                output_root,
                condition_id=condition,
                verify_evidence=True,
            )
        )
    return batch, rows


async def run_housing_reasoning_experiment(
    *,
    mode: str,
    output_root: str | Path,
    concurrency: int = 2,
    spend_limit_usd: float | None = None,
    tenant_provider: Any | None = None,
    progress_callback: Any | None = None,
    openrouter_route: OpenRouterRoutePin = CONFIRMATORY_EXPERIMENT_ROUTE,
) -> dict[str, Any]:
    """Run the locked dry, admission, or 100x2x3 Housing experiment workflow."""

    if mode not in {"dry-run", "admission", "full"}:
        raise ValueError("mode must be dry-run, admission, or full")
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    panel = derive_world_seeds(master_seed=20260826, count=100)
    admission_panel = derive_world_seeds(master_seed=20260827, count=3)
    if set(panel) & set(admission_panel):
        raise ValueError("admission and confirmatory world panels must be disjoint")
    if spend_limit_usd is None:
        spend_limit_usd = {"dry-run": 1.0, "admission": 0.10, "full": 6.0}[mode]
    if mode == "full" and spend_limit_usd <= 0.10:
        raise ValueError("full mode requires more than $0.10 for admission plus batch")

    provider = tenant_provider
    if provider is None:
        provider = (
            _ScriptedExperimentTenantProvider()
            if mode == "dry-run"
            else OpenRouterChatClient()
        )

    if mode == "dry-run":
        batch, rows = await _run_experiment_phase(
            output_root=output,
            world_seeds=panel[:2],
            replicates=1,
            small_preflight=True,
            tenant_provider=provider,
            concurrency=concurrency,
            spend_limit_usd=spend_limit_usd,
            progress_callback=progress_callback,
            openrouter_route=openrouter_route,
        )
        result: dict[str, Any] = {
            "mode": mode,
            "design": "2_world_structural_preflight",
            "batch": batch,
            "admission": None,
            "analysis": analyze_paired_results(
                rows,
                control_condition="reasoning_none_v1",
                treatment_condition="reasoning_low_v1",
                expected_replicates=1,
                bootstrap_draws=1000,
                bootstrap_seed=20260826,
            ),
            "total_cost_usd": batch["total_cost_usd"],
            "openrouter_route": dataclasses.asdict(openrouter_route),
        }
    elif mode == "admission":
        batch, rows = await _run_experiment_phase(
            output_root=output,
            world_seeds=admission_panel,
            replicates=1,
            small_preflight=False,
            tenant_provider=provider,
            concurrency=concurrency,
            spend_limit_usd=spend_limit_usd,
            progress_callback=progress_callback,
            openrouter_route=openrouter_route,
        )
        admission = validate_reasoning_admission(
            rows,
            expected_resolved_model=openrouter_route.canonical_model,
            expected_route_provider=openrouter_route.provider,
            expected_paired_cell_count=len(admission_panel),
        )
        result = {
            "mode": mode,
            "design": "3_out_of_panel_worlds_x_2_conditions_x_1_replicate_gate",
            "batch": batch,
            "admission": admission,
            "analysis": None,
            "total_cost_usd": batch["total_cost_usd"],
            "openrouter_route": dataclasses.asdict(openrouter_route),
        }
    else:
        admission_batch, admission_rows = await _run_experiment_phase(
            output_root=output / "admission",
            world_seeds=admission_panel,
            replicates=1,
            small_preflight=False,
            tenant_provider=provider,
            concurrency=concurrency,
            spend_limit_usd=min(0.10, spend_limit_usd),
            progress_callback=progress_callback,
            openrouter_route=openrouter_route,
        )
        admission = validate_reasoning_admission(
            admission_rows,
            expected_resolved_model=openrouter_route.canonical_model,
            expected_route_provider=openrouter_route.provider,
            expected_paired_cell_count=len(admission_panel),
        )
        remaining_budget = spend_limit_usd - admission_batch["total_cost_usd"]
        if remaining_budget <= 0:
            raise ValueError("admission exhausted the global experiment budget")
        batch, rows = await _run_experiment_phase(
            output_root=output / "full",
            world_seeds=panel,
            replicates=3,
            small_preflight=False,
            tenant_provider=provider,
            concurrency=concurrency,
            spend_limit_usd=remaining_budget,
            progress_callback=progress_callback,
            openrouter_route=openrouter_route,
        )
        analysis_result = analyze_paired_results_if_available(
            rows,
            control_condition="reasoning_none_v1",
            treatment_condition="reasoning_low_v1",
            expected_replicates=3,
            bootstrap_draws=10_000,
            bootstrap_seed=20260826,
            score_support_by_world={
                world_seed: housing_within_case_score_support(
                    world_seed=world_seed
                )
                for world_seed in panel
            },
        )
        result = {
            "mode": mode,
            "design": "100_worlds_x_2_conditions_x_3_nested_replicates",
            "admission_batch": admission_batch,
            "admission": admission,
            "batch": batch,
            "analysis_status": analysis_result["status"],
            "analysis": analysis_result["analysis"],
            "total_cost_usd": (
                admission_batch["total_cost_usd"] + batch["total_cost_usd"]
            ),
            "openrouter_route": dataclasses.asdict(openrouter_route),
        }
    _atomic_write_json(output / "experiment_summary.json", _sealed_result(result))
    return result


def _cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the locked paired Housing reasoning experiment"
    )
    parser.add_argument("--mode", choices=("dry-run", "admission", "full"), required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--spend-limit-usd", type=float)
    return parser


def main() -> None:
    arguments = _cli_parser().parse_args()

    def progress(value: Mapping[str, Any]) -> None:
        print(canonical_json_bytes({"progress": value}).decode("utf-8"), flush=True)

    result = asyncio.run(
        run_housing_reasoning_experiment(
            mode=arguments.mode,
            output_root=arguments.output_root,
            concurrency=arguments.concurrency,
            spend_limit_usd=arguments.spend_limit_usd,
            progress_callback=progress,
        )
    )
    print(canonical_json_bytes({"result": result}).decode("utf-8"), flush=True)


__all__ = [
    "analyze_paired_results",
    "analyze_paired_results_if_available",
    "CONFIRMATORY_EXPERIMENT_ROUTE",
    "build_housing_condition_setup",
    "derive_world_seeds",
    "housing_within_case_score_support",
    "paired_inference_seed",
    "read_condition_results",
    "run_condition_batch",
    "run_housing_reasoning_experiment",
    "run_paired_batch",
    "validate_reasoning_admission",
]


if __name__ == "__main__":
    main()
