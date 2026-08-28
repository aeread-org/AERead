"""Family-neutral paired batches with sealed receipts and conservative resume.

The spend limit is a recorded-cost stop, not a provider-side hard billing cap:
an in-flight episode can cross it. Unknown billing stops further execution.
An interrupted attempt without a verifiable receipt is never automatically rerun.
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import math
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Mapping

from .execution import EvidenceStore, OpenRouterChatClient, ProviderFailure, execute_plan_cell
from .family_evaluation import EvaluationSetup, audit_family_receipt, finalize_family_execution, finalize_family_failure
from .measurement import MeasurementLeafSpec
from .resolver import canonical_json_bytes, verify_run_plan
from .schemas import is_exportable_id


def atomic_write_json(destination: Path, value: Mapping[str, Any]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="wb", prefix=".batch-", dir=destination.parent, delete=False) as handle:
        handle.write(canonical_json_bytes(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = handle.name
    os.replace(temporary, destination)


def _seal(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = {key: item for key, item in value.items() if key != "result_sha256"}
    return {**payload, "result_sha256": hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}


@contextmanager
def _batch_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".batch.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("another process holds the batch lock") from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def paired_schedule(setups: Mapping[str, EvaluationSetup]) -> list[tuple[str, Any]]:
    if len(setups) != 2 or any(not is_exportable_id(name) for name in setups):
        raise ValueError("paired batches require two distinct exportable condition IDs")
    indexed = {}
    for condition, setup in setups.items():
        verify_run_plan(setup.plan)
        cells = {(cell.world_seed, cell.replicate_index): cell for cell in setup.plan.cells}
        if len(cells) != len(setup.plan.cells):
            raise ValueError("paired batch has duplicate world/replicate identities")
        indexed[condition] = cells
    conditions = sorted(setups)
    left, right = (indexed[c] for c in conditions)
    if set(left) != set(right):
        raise ValueError("paired conditions must contain exactly the same world/replicate panel")
    for identity in left:
        for field in ("case_sha256", "cluster_id", "pair_id", "paired_fields", "sampling_seed"):
            if getattr(left[identity], field) != getattr(right[identity], field):
                raise ValueError(f"paired cell {field} differs across conditions")
    # Alternate which condition goes first in successive pairs to reduce order drift.
    return [(condition, indexed[condition][identity])
            for index, identity in enumerate(sorted(left))
            for condition in (conditions if index % 2 == 0 else conditions[::-1])]


def event_execution_metrics(evidence: EvidenceStore, *, external_providers: set[str]) -> dict[str, Any]:
    calls, external_calls, unknown, thoughts, fixture_calls, cost = 0, 0, 0, 0, 0, 0.0
    external_ids, seeds, efforts, models = set(), set(), set(), set()
    requests, route_providers, route_failures = {}, set(), 0
    for event in evidence.read_events():
        payload = evidence.read_event_payload(event)
        if not isinstance(payload, Mapping):
            continue
        if event.event_type == "provider_call_started":
            request = payload.get("request", {})
            if request.get("provider") in external_providers:
                external_calls += 1
                external_ids.add(event.provider_call_id)
                requests[event.provider_call_id] = request
                seed, effort = request.get("seed"), request.get("reasoning_effort")
                if isinstance(seed, int) and not isinstance(seed, bool):
                    seeds.add(seed)
                if isinstance(effort, str):
                    efforts.add(effort)
        if event.event_type not in {"provider_call_succeeded", "provider_call_failed", "provider_call_outcome_unknown"}:
            continue
        calls += 1
        value = payload.get("cost_usd")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
            cost += value
        elif event.provider_call_id in external_ids or value == "unknown":
            unknown += 1
        result = payload.get("provider_result") or {}
        raw = result.get("raw_response") or {}
        if event.provider_call_id in external_ids:
            if result.get("resolved_model"):
                models.add(result["resolved_model"])
            fixture_calls += int(raw.get("fixture") is True)
            usage = raw.get("usageMetadata", {})
            value = usage.get("thoughtsTokenCount", raw.get("usage", {}).get("completion_tokens_details", {}).get("reasoning_tokens", 0))
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                thoughts += value
            request = requests[event.provider_call_id]
            if request.get("provider") == "openrouter" and result:
                metadata = request.get("provider_metadata") or {}
                try:
                    OpenRouterChatClient._verify_route(raw.get("openrouter_metadata"),
                        requested_model=request["model"], canonical_model=metadata["canonical_model"],
                        route_provider=metadata["route_provider"])
                    route_providers.add(metadata["route_provider"])
                except (ProviderFailure, KeyError, TypeError):
                    route_failures += 1
    return {
        "provider_call_count": calls, "external_provider_call_count": external_calls,
        "unknown_cost_provider_call_count": unknown, "reasoning_tokens": thoughts,
        "external_fixture_call_count": fixture_calls,
        "cost_usd": cost, "request_seeds": sorted(seeds), "reasoning_efforts": sorted(efforts),
        "resolved_models": sorted(models),
        "route_providers": sorted(route_providers), "route_verification_failures": route_failures,
    }


def _paths(root: Path, condition: str, setup: EvaluationSetup, cell: Any):
    evidence = root / condition / "evidence"
    return evidence, evidence / setup.plan.run_plan_id / cell.cell_id, root / condition / "results" / f"{cell.cell_id}.json"


def _receipt_row(root: Path, condition: str, setup: EvaluationSetup, cell: Any, receipt_path: Path) -> dict[str, Any]:
    receipt = audit_family_receipt(setup=setup, receipt_path=receipt_path)
    if receipt["cell_id"] != cell.cell_id:
        raise ValueError("batch result receipt points to another cell")
    evidence = EvidenceStore.audit_existing(receipt_path.parent)
    metrics = event_execution_metrics(evidence, external_providers={p.model.provider for p in setup.plan.agent_profiles if p.model.base_url is not None})
    evidence.close()
    included = receipt["inclusion_status"] == "included"
    scores = receipt["scores"]
    score = scores[0] if included else None
    ratio = score["metrics"].get("within_case_score") if score else None
    return _seal({
        "condition_id": condition, "world_seed": cell.world_seed, "replicate_index": cell.replicate_index,
        "cell_id": cell.cell_id, "run_plan_id": setup.plan.run_plan_id,
        "cluster_id": cell.cluster_id, "pair_id": cell.pair_id,
        "status": "completed" if included else "operational_failure",
        "receipt_inclusion_status": receipt["inclusion_status"], "receipt_status": receipt["status"],
        "receipt_path": str(receipt_path.relative_to(root)), "receipt_sha256": receipt["receipt_sha256"],
        "replay_level": receipt["replay_level"], "primary_value": score["primary"]["value"] if score else None,
        "within_case_score": ratio["value"] if ratio else None,
        "failure": receipt["failure"], **metrics,
    })


def _read_rows(setups: Mapping[str, EvaluationSetup], root: Path, *, recover: bool) -> list[dict[str, Any]]:
    rows = []
    schedule = paired_schedule(setups)
    expected_results = {str(_paths(root, condition, setups[condition], cell)[2]) for condition, cell in schedule}
    for path in root.glob("*/results/*.json"):
        if str(path) not in expected_results:
            raise ValueError("batch contains an unexpected result outside the sealed panel")
    for condition, cell in schedule:
        setup = setups[condition]
        _, attempt_root, result_path = _paths(root, condition, setup, cell)
        receipts = list(attempt_root.glob("*/evaluation_receipt.json"))
        attempts = [path for path in attempt_root.iterdir() if path.is_dir()] if attempt_root.exists() else []
        marker = result_path.with_suffix(".started")
        if len(receipts) > 1 or len(attempts) > 1:
            raise ValueError("batch cell has multiple attempts; manual recovery required")
        if not receipts:
            if result_path.exists() or attempts or marker.exists():
                raise ValueError("orphan/interrupted attempt has no verifiable receipt; refusing to rerun")
            continue
        row = _receipt_row(root, condition, setup, cell, receipts[0])
        if result_path.exists():
            saved = json.loads(result_path.read_bytes())
            if canonical_json_bytes(saved) != canonical_json_bytes(row):
                raise ValueError("batch result differs from replayed receipt or evidence")
        elif recover:
            atomic_write_json(result_path, row)
        else:
            raise ValueError("receipt has no result; resume the batch for no-call recovery")
        rows.append(row)
    return rows


def read_family_batch(*, setups: Mapping[str, EvaluationSetup], output_root: str | Path) -> list[dict[str, Any]]:
    """Read only: verify every returned row against sealed evidence and replay."""
    return _read_rows(setups, Path(output_root), recover=False)


async def run_family_batch(
    *, setups: Mapping[str, EvaluationSetup], output_root: str | Path,
    providers_by_condition: Mapping[str, Mapping[str, Any]],
    leaf_builder: Callable[[Mapping[str, Any]], MeasurementLeafSpec],
    spend_limit_usd: float, max_consecutive_failures: int = 3, max_new_cells: int | None = None,
    max_concurrency: int = 1, inflight_episode_reserve_usd: float = 0.0,
) -> dict[str, Any]:
    if isinstance(spend_limit_usd, bool) or not isinstance(spend_limit_usd, (int, float)) or not math.isfinite(spend_limit_usd) or spend_limit_usd <= 0:
        raise ValueError("spend_limit_usd must be finite and positive")
    if isinstance(max_consecutive_failures, bool) or not isinstance(max_consecutive_failures, int) or max_consecutive_failures < 1:
        raise ValueError("max_consecutive_failures must be a positive integer")
    if max_new_cells is not None and (isinstance(max_new_cells, bool) or not isinstance(max_new_cells, int) or max_new_cells < 0):
        raise ValueError("max_new_cells must be a nonnegative integer")
    if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int) or max_concurrency < 1:
        raise ValueError("max_concurrency must be a positive integer")
    if (isinstance(inflight_episode_reserve_usd, bool)
            or not isinstance(inflight_episode_reserve_usd, (int, float))
            or not math.isfinite(inflight_episode_reserve_usd)
            or inflight_episode_reserve_usd < 0
            or (max_concurrency > 1 and inflight_episode_reserve_usd == 0)):
        raise ValueError("parallel dispatch requires a finite positive episode reservation")
    schedule = paired_schedule(setups)
    if set(providers_by_condition) != set(setups):
        raise ValueError("providers must be supplied for both conditions")
    root = Path(output_root)
    source = Path(__file__).read_bytes() + Path(__file__).with_name("family_evaluation.py").read_bytes()
    manifest = _seal({
        "spec_version": "aeread.family_batch/1", "batch_source_sha256": hashlib.sha256(source).hexdigest(),
        "plans": {c: s.plan.plan_sha256 for c, s in setups.items()},
        "spend_limit_usd": float(spend_limit_usd), "max_consecutive_failures": max_consecutive_failures,
        "max_concurrency": max_concurrency,
        "inflight_episode_reserve_usd": inflight_episode_reserve_usd,
        "cost_policy": "recorded_cost_stop_after_episode;unknown_cost_stops;not_hard_billing_cap",
    })
    with _batch_lock(root):
        manifest_path = root / "batch_manifest.json"
        if manifest_path.exists():
            if canonical_json_bytes(json.loads(manifest_path.read_bytes())) != canonical_json_bytes(manifest):
                raise ValueError("batch manifest changed; use a new output directory")
        else:
            if any(root.glob("*/evidence")) or any(root.glob("*/results")):
                raise ValueError("existing attempts lack a sealed batch manifest")
            atomic_write_json(manifest_path, manifest)
        rows = _read_rows(setups, root, recover=True)
        by_cell = {(r["condition_id"], r["cell_id"]): r for r in rows}
        failures = {condition: 0 for condition in setups}
        known_cost = sum(r["cost_usd"] for r in rows)
        unknown_cost = sum(r["unknown_cost_provider_call_count"] for r in rows)
        new_cells, stop_reason = 0, "complete"
        reservation_exceeded = bool(inflight_episode_reserve_usd and any(
            row["cost_usd"] > inflight_episode_reserve_usd for row in rows))
        failure_circuit_open = False

        async def run_cell(condition, cell):
            setup = setups[condition]
            evidence_root, attempt_root, result_path = _paths(root, condition, setup, cell)
            atomic_write_json(result_path.with_suffix(".started"), {"cell_id": cell.cell_id, "run_plan_id": setup.plan.run_plan_id})
            try:
                execution = await execute_plan_cell(plan=setup.plan, cell_id=cell.cell_id, registry=setup.registry,
                    evidence_root=evidence_root, prompt_sources=setup.prompt_sources,
                    providers=providers_by_condition[condition], pricing=setup.pricing, episode_attempt_ordinal=0)
                finalize_family_execution(setup=setup, execution=execution)
            except Exception as error:
                finalize_family_failure(setup=setup, cell_id=cell.cell_id, evidence_root=evidence_root,
                                        error=error, leaf_builder=leaf_builder)
            receipts = list(attempt_root.glob("*/evaluation_receipt.json"))
            if len(receipts) != 1:
                raise ValueError("interrupted attempt has no unique receipt")
            row = _receipt_row(root, condition, setup, cell, receipts[0])
            atomic_write_json(result_path, row)
            return row

        cursor = 0
        while cursor < len(schedule):
            wave = []
            stop_reason = "complete"
            while cursor < len(schedule) and len(wave) < max_concurrency:
                condition, cell = schedule[cursor]
                existing = by_cell.get((condition, cell.cell_id))
                if existing:
                    failures[condition] = failures[condition] + 1 if existing["status"] != "completed" else 0
                    failure_circuit_open |= failures[condition] >= max_consecutive_failures
                    cursor += 1
                    continue
                if unknown_cost:
                    stop_reason = "unknown_billing"
                    break
                if reservation_exceeded:
                    stop_reason = "inflight_reservation_exceeded"
                    break
                if failure_circuit_open:
                    stop_reason = "failure_circuit"
                    break
                if known_cost >= spend_limit_usd:
                    stop_reason = "recorded_cost_limit"
                    break
                if max_new_cells is not None and new_cells + len(wave) >= max_new_cells:
                    stop_reason = "invocation_cell_limit"
                    break
                if inflight_episode_reserve_usd and (
                        known_cost + (len(wave) + 1) * inflight_episode_reserve_usd > spend_limit_usd):
                    stop_reason = "budget_reservation"
                    break
                wave.append((condition, cell))
                cursor += 1
            if not wave:
                break
            # Drain the bounded wave before another dispatch. Record failures in
            # declared schedule order, not whichever API response finishes first.
            outcomes = await asyncio.gather(*(run_cell(*item) for item in wave), return_exceptions=True)
            for row in outcomes:
                if isinstance(row, BaseException):
                    raise row
                rows.append(row)
                new_cells += 1
                known_cost += row["cost_usd"]
                unknown_cost += row["unknown_cost_provider_call_count"]
                condition = row["condition_id"]
                failures[condition] = failures[condition] + 1 if row["status"] != "completed" else 0
                failure_circuit_open |= failures[condition] >= max_consecutive_failures
                reservation_exceeded |= bool(inflight_episode_reserve_usd
                    and row["cost_usd"] > inflight_episode_reserve_usd)
            stop_reason = "complete"
        return {
            "planned_cell_count": len(schedule), "attempted_cell_count": len(rows),
            "included_count": sum(r["status"] == "completed" for r in rows),
            "excluded_count": sum(r["status"] != "completed" for r in rows),
            "known_cost_usd": known_cost, "unknown_cost_provider_call_count": unknown_cost,
            "stop_reason": stop_reason, "rows": rows,
        }
