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
import shutil
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
    temperatures = set()
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
                temperature = request.get("temperature")
                if isinstance(temperature, (int, float)) and not isinstance(temperature, bool) and math.isfinite(temperature):
                    temperatures.add(temperature)
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
        "temperatures": sorted(temperatures),
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
    root = Path(output_root)
    rows = _read_rows(setups, root, recover=False)
    _recovery_checkpoint(root, rows=rows)
    return rows


def _batch_source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()
        + Path(__file__).with_name("family_evaluation.py").read_bytes()).hexdigest()


def _read_sealed(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or value.get("result_sha256") != _seal(value)["result_sha256"]:
        raise ValueError(f"sealed checkpoint or manifest differs: {path.name}")
    return value


def _rate_limit_recovery_eligible(rows, manifest) -> None:
    if not rows or any(row["unknown_cost_provider_call_count"] for row in rows):
        raise ValueError("rate-limit recovery requires known billing for a completed prefix")
    failures, circuit = {}, False
    for row in rows:
        condition = row["condition_id"]
        if row["status"] != "completed":
            if (row.get("failure") or {}).get("condition") != "rate_limit":
                raise ValueError("only rate-limit failures may be acknowledged")
            failures[condition] = failures.get(condition, 0) + 1
            circuit |= failures[condition] >= manifest["max_consecutive_failures"]
        else:
            failures[condition] = 0
    if not circuit:
        raise ValueError("recovery requires an open failure circuit")
    cost = sum(row["cost_usd"] for row in rows)
    reserve = manifest["inflight_episode_reserve_usd"]
    if (cost >= manifest["spend_limit_usd"] or cost + reserve > manifest["spend_limit_usd"]
            or (reserve and any(row["cost_usd"] > reserve for row in rows))):
        raise ValueError("recovery cannot reset a spend or reservation budget")


def _unknown_billing_recovery_eligible(rows, manifest, checkpoint) -> None:
    unknown_count = sum(row["unknown_cost_provider_call_count"] for row in rows)
    if not rows or unknown_count < 1:
        raise ValueError("unknown-billing recovery requires an unknown provider outcome")
    if any(row["status"] != "completed" and (
            ((row.get("failure") or {}).get("condition") != "timeout"
             if row["unknown_cost_provider_call_count"]
             else (row.get("failure") or {}).get("condition") != "rate_limit"))
            for row in rows):
        raise ValueError(
            "only unknown-billing timeouts or known-billing rate-limit failures may be acknowledged")
    if checkpoint.get("acknowledged_unknown_cost_provider_call_count") != unknown_count:
        raise ValueError("unknown-billing recovery call count differs from its receipt prefix")
    each = checkpoint.get("unknown_call_reserve_usd_each")
    total = checkpoint.get("reserved_unknown_cost_usd")
    bounds = checkpoint.get("request_cost_upper_bounds_usd")
    numeric = lambda value: (isinstance(value, (int, float)) and not isinstance(value, bool)
                             and math.isfinite(value) and value >= 0)
    if (not numeric(each) or each <= 0 or not numeric(total)
            or not math.isclose(total, unknown_count * each, rel_tol=0, abs_tol=1e-12)
            or not isinstance(bounds, list) or len(bounds) != unknown_count
            or any(not numeric(bound) or bound > each for bound in bounds)):
        raise ValueError("unknown-billing recovery reserve does not cover every request bound")
    predecessor_sha = checkpoint.get("predecessor_checkpoint_sha256")
    parent_predecessor_sha = manifest.get("recovery_checkpoint_sha256")
    if predecessor_sha is None and parent_predecessor_sha is not None:
        raise ValueError("unknown-billing recovery cannot reset its predecessor checkpoint")
    if predecessor_sha is not None:
        if predecessor_sha != parent_predecessor_sha:
            raise ValueError("unknown-billing recovery predecessor differs from its parent manifest")
        predecessor = _read_sealed(Path(checkpoint["source_root"]) / "recovery_checkpoint.json")
        previous_count = predecessor.get("acknowledged_unknown_cost_provider_call_count")
        previous_hashes = predecessor.get("prefix_result_sha256s")
        previous_bounds = predecessor.get("request_cost_upper_bounds_usd")
        if (predecessor.get("spec_version") != "aeread.unknown_billing_recovery/1"
                or predecessor["result_sha256"] != predecessor_sha
                or not isinstance(previous_count, int) or previous_count >= unknown_count
                or checkpoint["prefix_result_sha256s"][:len(previous_hashes)] != previous_hashes
                or not math.isclose(predecessor["unknown_call_reserve_usd_each"], each,
                                    rel_tol=0, abs_tol=1e-12)
                or bounds[:previous_count] != previous_bounds
                or not math.isclose(predecessor["reserved_unknown_cost_usd"],
                                    previous_count * each, rel_tol=0, abs_tol=1e-12)):
            raise ValueError("unknown-billing recovery does not carry its cumulative predecessor")
    before = checkpoint.get("account_usage_before_usd")
    after = checkpoint.get("account_usage_after_usd")
    account_known = checkpoint.get("account_known_cost_usd")
    unexplained = checkpoint.get("account_unexplained_delta_usd")
    if (any(not numeric(value) for value in (before, after, account_known, unexplained))
            or not math.isclose(unexplained, after - before - account_known,
                                rel_tol=0, abs_tol=1e-12)
            or unexplained > total + 1e-12):
        raise ValueError("account usage delta is not reconciled by the unknown-call reserve")
    cost = sum(row["cost_usd"] for row in rows) + total
    reserve = manifest["inflight_episode_reserve_usd"]
    if (cost >= manifest["spend_limit_usd"] or cost + reserve > manifest["spend_limit_usd"]
            or (reserve and (total > unknown_count * reserve
                             or any(row["cost_usd"] > reserve for row in rows)))):
        raise ValueError("unknown-billing recovery cannot reset a spend or reservation budget")


def _recovery_checkpoint(root: Path, *, rows=None, for_execution=False):
    checkpoint_path = root / "recovery_checkpoint.json"
    if not checkpoint_path.exists():
        return None
    checkpoint = _read_sealed(checkpoint_path)
    parent = _read_sealed(root / "recovery_parent_manifest.json")
    current = _read_sealed(root / "batch_manifest.json")
    excluded = {"result_sha256", "batch_source_sha256", "recovery_checkpoint_sha256"}
    spec_version = checkpoint.get("spec_version")
    if (spec_version not in {"aeread.rate_limit_recovery/1", "aeread.unknown_billing_recovery/1"}
            or type(checkpoint.get("max_new_cells_per_invocation")) is not int
            or checkpoint["max_new_cells_per_invocation"] != 4
            or checkpoint.get("parent_manifest_sha256") != parent["result_sha256"]
            or current.get("recovery_checkpoint_sha256") != checkpoint["result_sha256"]
            or {k: v for k, v in parent.items() if k not in excluded}
            != {k: v for k, v in current.items() if k not in excluded}):
        raise ValueError("recovery checkpoint changed the frozen batch policy")
    hashes = checkpoint.get("prefix_result_sha256s")
    if not isinstance(hashes, list) or not hashes or any(not isinstance(value, str) for value in hashes):
        raise ValueError("recovery checkpoint requires a nonempty sealed result prefix")
    if for_execution and Path(checkpoint["output_root"]).resolve() != root.resolve():
        raise ValueError("recovery checkpoint belongs to another execution destination")
    if rows is not None:
        prefix = rows[:len(hashes)]
        if [row["result_sha256"] for row in prefix] != hashes:
            raise ValueError("recovery checkpoint prefix changed or lost a receipt")
        if spec_version == "aeread.rate_limit_recovery/1":
            _rate_limit_recovery_eligible(prefix, parent)
        else:
            _unknown_billing_recovery_eligible(prefix, parent, checkpoint)
    return checkpoint


def prepare_rate_limit_recovery(
    *, setups: Mapping[str, EvaluationSetup], source_root: str | Path,
    output_root: str | Path, expected_manifest_sha256: str, reason: str,
) -> dict[str, Any]:
    """Explicit one-time fork of a drained 429 stop; never rerun the acknowledged prefix.

    The original evidence and policy are retained, its only new file is a single-child
    pointer. The child preserves every receipt, charge and plan. Later failures still
    latch normally; neither unknown billing nor another recovery can be acknowledged.
    """
    if Path(output_root).is_symlink():
        raise FileExistsError(f"recovery destination is a symlink: {output_root}")
    source, target = Path(source_root).resolve(), Path(output_root).resolve()
    if source == target or source in target.parents:
        raise ValueError("recovery destination must be separate from its source")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("recovery requires an explicit operator reason")
    with _batch_lock(source):
        if (source / "recovery_checkpoint.json").exists():
            raise ValueError("a recovery cannot acknowledge another failure circuit")
        parent = _read_sealed(source / "batch_manifest.json")
        if parent["result_sha256"] != expected_manifest_sha256:
            raise ValueError("source manifest differs from the acknowledged checkpoint")
        if parent["plans"] != {condition: setup.plan.plan_sha256 for condition, setup in setups.items()}:
            raise ValueError("recovery plans differ from the frozen source plans")
        rows = _read_rows(setups, source, recover=False)
        schedule = paired_schedule(setups)
        if ([(r["condition_id"], r["cell_id"]) for r in rows]
                != [(condition, cell.cell_id) for condition, cell in schedule[:len(rows)]]
                or len(rows) == len(schedule)):
            raise ValueError("recovery requires a contiguous unfinished schedule prefix")
        _rate_limit_recovery_eligible(rows, parent)
        checkpoint = _seal({
            "spec_version": "aeread.rate_limit_recovery/1", "source_root": str(source),
            "output_root": str(target), "parent_manifest_sha256": parent["result_sha256"],
            "prefix_result_sha256s": [row["result_sha256"] for row in rows],
            "max_new_cells_per_invocation": 4,
            "operator_reason": reason.strip(),
        })
        pointer_path = source / "recovery_child.json"
        if pointer_path.exists():
            pointer = _read_sealed(pointer_path)
            if (pointer.get("output_root") != str(target)
                    or pointer.get("checkpoint_sha256") != checkpoint["result_sha256"]):
                raise ValueError("source already has another recovery child destination")
            if not target.exists() or _recovery_checkpoint(target) != checkpoint:
                raise ValueError("existing recovery child is incomplete; manual inspection required")
            return checkpoint
        if target.exists():
            raise FileExistsError(f"recovery destination already exists: {target}")
        # Claim one destination before copying. A failed copy is left for inspection,
        # never silently overwritten or turned into a second independently billed fork.
        atomic_write_json(pointer_path, _seal({"output_root": str(target),
            "checkpoint_sha256": checkpoint["result_sha256"]}))
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(".batch.lock", "recovery_child.json"))
        atomic_write_json(target / "recovery_parent_manifest.json", parent)
        atomic_write_json(target / "recovery_checkpoint.json", checkpoint)
        manifest = _seal({**parent, "batch_source_sha256": _batch_source_sha256(),
                          "recovery_checkpoint_sha256": checkpoint["result_sha256"]})
        atomic_write_json(target / "batch_manifest.json", manifest)
        copied = _read_rows(setups, target, recover=False)
        _recovery_checkpoint(target, rows=copied, for_execution=True)
        if copied != rows:
            raise ValueError("recovery copy changed a sealed result")
        return checkpoint


def prepare_unknown_billing_recovery(
    *, setups: Mapping[str, EvaluationSetup], source_root: str | Path,
    output_root: str | Path, expected_manifest_sha256: str, reason: str,
    account_usage_before_usd: float, account_usage_after_usd: float,
    account_known_cost_usd: float, unknown_call_reserve_usd_each: float,
    request_cost_upper_bounds_usd: list[float],
) -> dict[str, Any]:
    """Fork one drained unknown-billing stop with a full, sealed cost reserve.

    The source receipts remain immutable. The child acknowledges only the existing
    unknown outcomes, charges their full request-level reserve against the original
    spend limit, and never reruns their cells.
    """
    if Path(output_root).is_symlink():
        raise FileExistsError(f"recovery destination is a symlink: {output_root}")
    source, target = Path(source_root).resolve(), Path(output_root).resolve()
    if source == target or source in target.parents:
        raise ValueError("recovery destination must be separate from its source")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("recovery requires an explicit operator reason")
    with _batch_lock(source):
        predecessor = None
        if (source / "recovery_checkpoint.json").exists():
            predecessor = _read_sealed(source / "recovery_checkpoint.json")
            if predecessor.get("spec_version") != "aeread.unknown_billing_recovery/1":
                raise ValueError("only unknown-billing recovery may extend an unknown-billing checkpoint")
        parent = _read_sealed(source / "batch_manifest.json")
        if parent["result_sha256"] != expected_manifest_sha256:
            raise ValueError("source manifest differs from the acknowledged checkpoint")
        if parent["plans"] != {condition: setup.plan.plan_sha256 for condition, setup in setups.items()}:
            raise ValueError("recovery plans differ from the frozen source plans")
        rows = _read_rows(setups, source, recover=False)
        schedule = paired_schedule(setups)
        if ([(row["condition_id"], row["cell_id"]) for row in rows]
                != [(condition, cell.cell_id) for condition, cell in schedule[:len(rows)]]
                or len(rows) == len(schedule)):
            raise ValueError("recovery requires a contiguous unfinished schedule prefix")
        unknown_count = sum(row["unknown_cost_provider_call_count"] for row in rows)
        numeric = lambda value: (isinstance(value, (int, float)) and not isinstance(value, bool)
                                 and math.isfinite(value) and value >= 0)
        if any(not numeric(value) for value in (
                account_usage_before_usd, account_usage_after_usd,
                account_known_cost_usd, unknown_call_reserve_usd_each)):
            raise ValueError("recovery usage and reserve values must be finite and nonnegative")
        unexplained = account_usage_after_usd - account_usage_before_usd - account_known_cost_usd
        hashes = [row["result_sha256"] for row in rows]
        if predecessor:
            previous_count = predecessor["acknowledged_unknown_cost_provider_call_count"]
            previous_hashes = predecessor["prefix_result_sha256s"]
            previous_bounds = predecessor["request_cost_upper_bounds_usd"]
            if (unknown_count <= previous_count
                    or hashes[:len(previous_hashes)] != previous_hashes
                    or not math.isclose(unknown_call_reserve_usd_each,
                                        predecessor["unknown_call_reserve_usd_each"],
                                        rel_tol=0, abs_tol=1e-12)
                    or request_cost_upper_bounds_usd[:previous_count] != previous_bounds):
                raise ValueError("cumulative recovery cannot reset its predecessor reserve or prefix")
        checkpoint = _seal({
            "spec_version": "aeread.unknown_billing_recovery/1",
            "source_root": str(source), "output_root": str(target),
            "parent_manifest_sha256": parent["result_sha256"],
            "prefix_result_sha256s": hashes,
            "max_new_cells_per_invocation": 4,
            "acknowledged_unknown_cost_provider_call_count": unknown_count,
            "unknown_call_reserve_usd_each": unknown_call_reserve_usd_each,
            "reserved_unknown_cost_usd": unknown_count * unknown_call_reserve_usd_each,
            "request_cost_upper_bounds_usd": list(request_cost_upper_bounds_usd),
            "account_usage_before_usd": account_usage_before_usd,
            "account_usage_after_usd": account_usage_after_usd,
            "account_known_cost_usd": account_known_cost_usd,
            "account_unexplained_delta_usd": unexplained,
            "operator_reason": reason.strip(),
            **({"predecessor_checkpoint_sha256": predecessor["result_sha256"]}
               if predecessor else {}),
        })
        _unknown_billing_recovery_eligible(rows, parent, checkpoint)
        pointer_path = source / "recovery_child.json"
        if pointer_path.exists():
            pointer = _read_sealed(pointer_path)
            if (pointer.get("output_root") != str(target)
                    or pointer.get("checkpoint_sha256") != checkpoint["result_sha256"]):
                raise ValueError("source already has another recovery child destination")
            if not target.exists() or _recovery_checkpoint(target) != checkpoint:
                raise ValueError("existing recovery child is incomplete; manual inspection required")
            return checkpoint
        if target.exists():
            raise FileExistsError(f"recovery destination already exists: {target}")
        atomic_write_json(pointer_path, _seal({"output_root": str(target),
            "checkpoint_sha256": checkpoint["result_sha256"]}))
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(".batch.lock", "recovery_child.json"))
        atomic_write_json(target / "recovery_parent_manifest.json", parent)
        atomic_write_json(target / "recovery_checkpoint.json", checkpoint)
        manifest = _seal({**parent, "batch_source_sha256": _batch_source_sha256(),
                          "recovery_checkpoint_sha256": checkpoint["result_sha256"]})
        atomic_write_json(target / "batch_manifest.json", manifest)
        copied = _read_rows(setups, target, recover=False)
        _recovery_checkpoint(target, rows=copied, for_execution=True)
        if copied != rows:
            raise ValueError("recovery copy changed a sealed result")
        return checkpoint


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
    checkpoint = _recovery_checkpoint(root, for_execution=True)
    if checkpoint:
        if max_new_cells is None:
            max_new_cells = checkpoint["max_new_cells_per_invocation"]
        elif max_new_cells > checkpoint["max_new_cells_per_invocation"]:
            raise ValueError("recovery is limited to four new cells per invocation")
    manifest = _seal({
        "spec_version": "aeread.family_batch/1", "batch_source_sha256": _batch_source_sha256(),
        "plans": {c: s.plan.plan_sha256 for c, s in setups.items()},
        "spend_limit_usd": float(spend_limit_usd), "max_consecutive_failures": max_consecutive_failures,
        "max_concurrency": max_concurrency,
        "inflight_episode_reserve_usd": inflight_episode_reserve_usd,
        "cost_policy": "recorded_cost_stop_after_episode;unknown_cost_stops;not_hard_billing_cap",
        **({"recovery_checkpoint_sha256": checkpoint["result_sha256"]} if checkpoint else {}),
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
        _recovery_checkpoint(root, rows=rows, for_execution=True)
        acknowledged_prefix = len(checkpoint["prefix_result_sha256s"]) if checkpoint else 0
        acknowledged_unknown = (checkpoint.get("acknowledged_unknown_cost_provider_call_count", 0)
                                if checkpoint else 0)
        reserved_unknown_cost = checkpoint.get("reserved_unknown_cost_usd", 0.0) if checkpoint else 0.0
        by_cell = {(r["condition_id"], r["cell_id"]): r for r in rows}
        failures = {condition: 0 for condition in setups}
        known_cost = sum(r["cost_usd"] for r in rows)
        unknown_cost = sum(r["unknown_cost_provider_call_count"] for r in rows) - acknowledged_unknown
        if unknown_cost < 0:
            raise ValueError("recovery acknowledges more unknown calls than its receipt prefix")
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
                    if cursor >= acknowledged_prefix:
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
                if known_cost + reserved_unknown_cost >= spend_limit_usd:
                    stop_reason = "recorded_cost_limit"
                    break
                if max_new_cells is not None and new_cells + len(wave) >= max_new_cells:
                    stop_reason = "invocation_cell_limit"
                    break
                if inflight_episode_reserve_usd and (
                        known_cost + reserved_unknown_cost
                        + (len(wave) + 1) * inflight_episode_reserve_usd > spend_limit_usd):
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
            if checkpoint and any((row.get("failure") or {}).get("condition") == "rate_limit" for row in outcomes):
                stop_reason = ("unknown_billing" if unknown_cost else
                    "inflight_reservation_exceeded" if reservation_exceeded else
                    "failure_circuit" if failure_circuit_open else "rate_limit_pause")
                break
            stop_reason = "complete"
        return {
            "planned_cell_count": len(schedule), "attempted_cell_count": len(rows),
            "included_count": sum(r["status"] == "completed" for r in rows),
            "excluded_count": sum(r["status"] != "completed" for r in rows),
            "known_cost_usd": known_cost,
            "conservative_cost_usd": known_cost + reserved_unknown_cost,
            "unknown_cost_provider_call_count": unknown_cost,
            "acknowledged_unknown_cost_provider_call_count": acknowledged_unknown,
            "reserved_unknown_cost_usd": reserved_unknown_cost,
            "stop_reason": stop_reason, "rows": rows,
        }
