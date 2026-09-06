"""Frozen first-live campaign for the econevals external adapter (issue #90).

One unscored admission canary plus a six-case panel -- two cases from each
of the three tracks -- on the pinned OpenRouter GLM 5.3 Flash/Parasail
route, executed sequentially, aborting on the first operational failure.

What this campaign is for: the econevals family is the matrix's *pipeline
validator*, because its scorer is checked against an exact optimum that
upstream's own solvers compute (gurobipy for procurement, scipy for
pricing) rather than against a reimplementation of ours. A live panel here
exercises the same path procurement's oracle does -- model -> declared
tools -> sealed receipt -> offline replay -> measured headroom against a
known-correct optimum.

Every case is the pinned corpus case, unmodified: its payload, its
``pins.max_steps``, and its content digest are the ones the corpus
admission gate reproduces byte-for-byte from the ``(track, difficulty,
seed)`` triple.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.run.publication import (
    SANITIZATION_DECLARATION,
    assert_public_payload,
    atomic_publish,
    jsonl,
    receipt_projection,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import (
    finalize_family_execution,
    replay_family_receipt,
)
from aeread.shared_runner.task.execution import (
    OpenRouterChatClient,
    ProviderRequest,
    execute_plan_cell,
)
from aeread.shared_runner.analysis.research import deserialize_evaluation_receipt
from aeread.shared_runner.task.receipts import read_evaluation_receipt

from .cases import UPSTREAM_COMMIT, UPSTREAM_REPO
from .econevals_bridge import EconevalsBridge, discover_bridge_python
from .live import (
    MODEL,
    PRICING,
    PROMPT,
    PROVIDER,
    QUANTIZATION,
    REVISION,
    ROUTE_PROVIDER,
    build_live_setup,
    load_case,
    period_output_schema,
    route_metadata,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN_ID = "econevals_glm53_flash_parasail_first_light_v1"
CANARY_CASE_ID = "econevals.procurement.basic.0"
PANEL_CASE_IDS = (
    "econevals.procurement.basic.0",
    "econevals.procurement.basic.1",
    "econevals.scheduling.basic.0",
    "econevals.scheduling.basic.1",
    "econevals.pricing.basic.0",
    "econevals.pricing.basic.1",
)
PANEL_STRATA = (
    "procurement_exact_optimum_gurobi",
    "procurement_exact_optimum_gurobi",
    "scheduling_stable_matching",
    "scheduling_stable_matching",
    "pricing_monopoly_reference_scipy",
    "pricing_monopoly_reference_scipy",
)
SEED = 300
MAX_PARALLEL_CELLS = 1
MAX_CANARY_COST_USD = 0.01
MAX_CANARY_OUTPUT_TOKENS = 256
# A transient condition on an UNSCORED, zero-cost probe must not seal the
# attempt root: the probe produces no measurement, so re-probing changes
# nothing about what is measured. Every probe is still recorded write-once
# under its own ordinal, so the audit trail shows exactly how many were
# needed and why each failed. Non-transient rejections still stop the run.
# See docs/families/procurement-allocation/design_review.md, which recorded
# this defect after it sealed two attempt roots there.
CANARY_TRANSIENT_CONDITIONS = ("rate_limit", "provider_5xx", "timeout")
MAX_CANARY_PROBES = 6
CANARY_RETRY_BASE_SECONDS = 15.0
MAX_TRAJECTORY_COST_USD = 0.06
HARD_TOTAL_COST_CEILING_USD = 0.40


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _write_once_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"refusing to replace different artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def build_campaign_plan() -> dict[str, Any]:
    cases = [load_case(case_id) for case_id in PANEL_CASE_IDS]
    source_names = (
        "campaign.py",
        "cases.py",
        "econevals_bridge.py",
        "environment.py",
        "live.py",
        "measurement.py",
        "tools.py",
    )
    source_hashes = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in source_names
    }
    plan: dict[str, Any] = {
        "schema_version": "aeread.econevals_live_campaign/0.1",
        "campaign_id": CAMPAIGN_ID,
        "freeze_status": "first_light_frozen_before_live_execution",
        "upstream": {"repository": UPSTREAM_REPO, "commit": UPSTREAM_COMMIT},
        "route": {
            "provider": PROVIDER,
            "model": MODEL,
            "revision": REVISION,
            "route_provider": ROUTE_PROVIDER,
            "quantization": QUANTIZATION,
            "fallbacks": "disabled",
            "reasoning_effort": "low",
            "route_attestation": "openrouter_provider_order_pinned",
            "provider_cost_status": "response_reported",
            "provider_seed_status": "requested",
            "pricing_id": PRICING.pricing_id,
            "pricing_sha256": PRICING.content_sha256(),
        },
        "canary": {
            "case_id": CANARY_CASE_ID,
            "scored": False,
            "max_cost_usd": MAX_CANARY_COST_USD,
            "max_output_tokens": MAX_CANARY_OUTPUT_TOKENS,
            # Declared before execution so the re-probe budget is part of the
            # frozen contract, not an operator decision taken after a 429.
            "max_probes": MAX_CANARY_PROBES,
            "transient_conditions": list(CANARY_TRANSIENT_CONDITIONS),
            "retry_base_seconds": CANARY_RETRY_BASE_SECONDS,
            "probes_are_recorded_individually": True,
        },
        "panel": [
            {
                "case_id": case.case_id,
                "case_content_sha256": case.content_sha256,
                "track": case.payload["track"],
                "world_seed": case.payload["seed"],
                "max_steps": case.payload["pins"]["max_steps"],
                "stratum": stratum,
                "seed": SEED,
                "max_cost_usd": MAX_TRAJECTORY_COST_USD,
            }
            for case, stratum in zip(cases, PANEL_STRATA, strict=True)
        ],
        "execution": {
            "max_parallel_cells": MAX_PARALLEL_CELLS,
            "abort_on_operational_failure": True,
            "resume_only_failure_free_checkpoints": True,
            "publish_only": True,
            "scored_case_count": len(PANEL_CASE_IDS),
        },
        "budget": {
            "hard_total_cost_ceiling_usd": HARD_TOTAL_COST_CEILING_USD,
            "planned_maximum_usd": MAX_CANARY_COST_USD
            + len(PANEL_CASE_IDS) * MAX_TRAJECTORY_COST_USD,
            "canary_included": True,
        },
        "source_sha256": source_hashes,
    }
    plan["plan_sha256"] = _digest(plan)
    return plan


def _verify_plan(value: Mapping[str, Any]) -> None:
    recorded = value.get("plan_sha256")
    payload = {key: item for key, item in value.items() if key != "plan_sha256"}
    if recorded != _digest(payload):
        raise ValueError("campaign plan digest mismatch")
    expected = build_campaign_plan()
    if canonical_json_bytes(value) != canonical_json_bytes(expected):
        raise ValueError("campaign plan differs from the frozen implementation")


def _route_metadata() -> dict[str, str]:
    """One shared route seal for the canary and every panel cell."""
    return route_metadata()


async def _probe_canary(
    *, path: Path, plan_sha256: str, ordinal: int
) -> dict[str, Any]:
    if path.exists():
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("plan_sha256") != plan_sha256 or value.get(
            "record_sha256"
        ) != _digest({k: v for k, v in value.items() if k != "record_sha256"}):
            raise ValueError("canary checkpoint does not match the frozen plan")
        return value
    request = ProviderRequest(
        provider_call_id="econevals_first_light_canary",
        provider=PROVIDER,
        base_url="https://openrouter.ai/api/v1",
        model=MODEL,
        revision=REVISION,
        instructions=PROMPT,
        input_text=canonical_json_bytes(
            {
                "phase_id": "route_admission",
                "case_id": CANARY_CASE_ID,
                "instruction": (
                    "Return a single no-op call list for route admission: one "
                    "read_notes call and nothing else."
                ),
            }
        ).decode("utf-8"),
        temperature=0.0,
        top_p=None,
        max_output_tokens=MAX_CANARY_OUTPUT_TOKENS,
        reasoning_effort="low",
        reasoning_token_budget=None,
        timeout_seconds=180.0,
        request_sha256="",
        max_cost_usd=MAX_CANARY_COST_USD,
        output_schema=period_output_schema(),
        provider_metadata=_route_metadata(),
        seed=SEED,
    ).with_computed_hash()
    record: dict[str, Any] = {
        "schema_version": "aeread.provider_admission_canary/0.1",
        "campaign_id": CAMPAIGN_ID,
        "plan_sha256": plan_sha256,
        "case_id": CANARY_CASE_ID,
        "scored": False,
        "probe_ordinal": ordinal,
        "request_sha256": request.request_sha256,
        "model": MODEL,
        "revision": REVISION,
        "route_provider": ROUTE_PROVIDER,
        "attempted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    result = None
    try:
        result = await OpenRouterChatClient().complete(request)
        value = json.loads(result.output_text)
        calls = value.get("calls")
        if not isinstance(calls, list) or not calls:
            raise ValueError("canary did not return the required structured calls list")
        cost = float(result.cost_usd or 0.0)
        if cost > MAX_CANARY_COST_USD:
            raise ValueError("canary exceeded its cost ceiling")
        record.update(
            {
                "status": "admitted",
                "resolved_model": result.resolved_model,
                "finish_reason": result.finish_reason,
                "input_tokens": result.input_tokens,
                "cached_input_tokens": result.cached_input_tokens,
                "output_tokens": result.output_tokens,
                "cost_usd": cost,
            }
        )
    except Exception as error:
        cost = float(result.cost_usd or 0.0) if result is not None else 0.0
        record.update(
            {
                "status": "rejected",
                "failure_type": type(error).__name__,
                "failure_condition": getattr(error, "condition", "canary_rejected"),
                "cost_usd": cost,
            }
        )
    record["record_sha256"] = _digest(record)
    _write_once_json(path, record)
    return record


async def run_canary(*, run_root: Path, plan_sha256: str) -> dict[str, Any]:
    """Admit the route, re-probing only on typed transient conditions.

    Returns the admitted probe, or the last rejection when every allowed
    probe failed. Each probe is sealed write-once under its own ordinal.
    """
    directory = run_root / "checkpoints" / "canary_probes"
    record: dict[str, Any] = {}
    for ordinal in range(1, MAX_CANARY_PROBES + 1):
        record = await _probe_canary(
            path=directory / f"{ordinal:03d}.json",
            plan_sha256=plan_sha256,
            ordinal=ordinal,
        )
        if record.get("status") == "admitted":
            return record
        if record.get("failure_condition") not in CANARY_TRANSIENT_CONDITIONS:
            return record
        if ordinal < MAX_CANARY_PROBES:
            await asyncio.sleep(CANARY_RETRY_BASE_SECONDS * ordinal)
    return record


async def execute_campaign(*, run_root: Path) -> None:
    plan_path = run_root / "campaign_plan.json"
    plan = build_campaign_plan()
    _write_once_json(plan_path, plan)
    _verify_plan(json.loads(plan_path.read_text(encoding="utf-8")))
    bridge = EconevalsBridge(python_executable=discover_bridge_python())
    canary = await run_canary(run_root=run_root, plan_sha256=plan["plan_sha256"])
    if canary.get("status") != "admitted":
        raise RuntimeError("econevals canary was rejected; campaign stopped")
    total_cost = float(canary["cost_usd"])
    provider = OpenRouterChatClient()
    for ordinal, case_id in enumerate(PANEL_CASE_IDS):
        checkpoint_path = run_root / "checkpoints" / f"{ordinal:02d}_{case_id}.json"
        if checkpoint_path.exists():
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            recorded = checkpoint.get("record_sha256")
            payload = {k: v for k, v in checkpoint.items() if k != "record_sha256"}
            if (
                checkpoint.get("status") != "complete"
                or checkpoint.get("plan_sha256") != plan["plan_sha256"]
                or recorded != _digest(payload)
            ):
                raise RuntimeError("campaign cannot resume from a failed checkpoint")
            total_cost += float(checkpoint["cost_usd"])
            continue
        if total_cost + MAX_TRAJECTORY_COST_USD > HARD_TOTAL_COST_CEILING_USD:
            raise RuntimeError("insufficient campaign budget reserve for the next case")
        setup = build_live_setup(
            case_id=case_id,
            bridge=bridge,
            seed=SEED,
            max_trajectory_cost_usd=MAX_TRAJECTORY_COST_USD,
        )
        execution_root = run_root / "executions" / case_id
        try:
            execution = await execute_plan_cell(
                plan=setup.plan,
                cell_id=setup.plan.cells[0].cell_id,
                registry=setup.registry,
                evidence_root=execution_root,
                prompt_sources=setup.prompt_sources,
                providers={PROVIDER: provider},
                pricing=setup.pricing,
                harnesses=setup.harnesses,
                tool_runtime_factories=setup.tool_runtime_factories,
            )
            receipt = finalize_family_execution(setup=setup, execution=execution)
            if receipt.status != "ok" or receipt.inclusion_status != "included":
                raise RuntimeError(
                    "econevals case did not produce an included successful receipt"
                )
            replayed = replay_family_receipt(
                setup=setup,
                receipt=receipt,
                evidence_root=execution_root,
            )
            if replayed.receipt_sha256 != receipt.receipt_sha256:
                raise RuntimeError("receipt replay digest mismatch")
            cost = float(execution.total_cost_usd)
            total_cost += cost
            if total_cost > HARD_TOTAL_COST_CEILING_USD:
                raise RuntimeError("campaign exceeded its hard total cost ceiling")
            receipt_path = execution.evidence.root / "evaluation_receipt.json"
            checkpoint = {
                "schema_version": "aeread.econevals_checkpoint/0.1",
                "campaign_id": CAMPAIGN_ID,
                "plan_sha256": plan["plan_sha256"],
                "ordinal": ordinal,
                "case_id": case_id,
                "status": "complete",
                "run_plan_id": setup.plan.run_plan_id,
                "run_plan_sha256": setup.plan.plan_sha256,
                "receipt_path": str(receipt_path.relative_to(run_root)),
                "receipt_sha256": receipt.receipt_sha256,
                "receipt_replayed": True,
                "cost_usd": cost,
                "termination_reason": execution.episode_result.outcome[
                    "termination_reason"
                ],
                "period_count": execution.episode_result.outcome.get("period"),
            }
            checkpoint["record_sha256"] = _digest(checkpoint)
            _write_once_json(checkpoint_path, checkpoint)
        except Exception as error:
            failure = {
                "schema_version": "aeread.econevals_checkpoint/0.1",
                "campaign_id": CAMPAIGN_ID,
                "plan_sha256": plan["plan_sha256"],
                "ordinal": ordinal,
                "case_id": case_id,
                "status": "operational_failure",
                "failure_type": type(error).__name__,
                "failure_condition": getattr(error, "condition", "execution_failure"),
            }
            failure["record_sha256"] = _digest(failure)
            _write_once_json(checkpoint_path, failure)
            raise


def publish_campaign(*, run_root: Path, publication_root: Path) -> None:
    plan = json.loads((run_root / "campaign_plan.json").read_text(encoding="utf-8"))
    _verify_plan(plan)
    probes = sorted((run_root / "checkpoints" / "canary_probes").glob("*.json"))
    if not probes:
        raise RuntimeError("cannot publish a campaign with no recorded canary probe")
    records = [json.loads(path.read_text(encoding="utf-8")) for path in probes]
    canary = records[-1]
    canary_payload = {k: v for k, v in canary.items() if k != "record_sha256"}
    if (
        canary.get("status") != "admitted"
        or canary.get("plan_sha256") != plan["plan_sha256"]
        or canary.get("record_sha256") != _digest(canary_payload)
    ):
        raise RuntimeError("cannot publish a campaign with a rejected canary")
    receipt_rows: list[dict[str, Any]] = []
    trajectory_rows: list[dict[str, Any]] = []
    for ordinal, case_id in enumerate(PANEL_CASE_IDS):
        checkpoint = json.loads(
            (run_root / "checkpoints" / f"{ordinal:02d}_{case_id}.json").read_text(
                encoding="utf-8"
            )
        )
        payload = {k: v for k, v in checkpoint.items() if k != "record_sha256"}
        if (
            checkpoint.get("status") != "complete"
            or checkpoint.get("plan_sha256") != plan["plan_sha256"]
            or checkpoint.get("record_sha256") != _digest(payload)
        ):
            raise RuntimeError(f"cannot publish incomplete case {case_id}")
        serialized = read_evaluation_receipt(run_root / checkpoint["receipt_path"])
        receipt = deserialize_evaluation_receipt(serialized)
        receipt_rows.append(
            receipt_projection(serialized, campaign_cell_key=f"{ordinal:02d}:{case_id}")
        )
        # Both declared leaves are surfaced by the scorer; report each by id
        # rather than assuming a position.
        by_leaf = {score.leaf.leaf_id: score for score in receipt.scores}
        gate = next((s for lid, s in by_leaf.items() if lid.endswith("_gate_leaf")), None)
        objective = next(
            (s for lid, s in by_leaf.items() if lid.endswith("_objective_leaf")), None
        )
        trajectory_rows.append(
            {
                "case_id": case_id,
                "track": plan["panel"][ordinal]["track"],
                "stratum": PANEL_STRATA[ordinal],
                "termination_reason": checkpoint["termination_reason"],
                "period_count": checkpoint["period_count"],
                "gate_leaf_id": gate.leaf.leaf_id if gate else None,
                "gate_valid": gate.validity.valid if gate else None,
                "gate_value": (
                    gate.primary.value if gate is not None and gate.primary else None
                ),
                "objective_leaf_id": objective.leaf.leaf_id if objective else None,
                "objective_value": (
                    objective.primary.value
                    if objective is not None and objective.primary
                    else None
                ),
                "cost_usd": checkpoint["cost_usd"],
                "receipt_sha256": checkpoint["receipt_sha256"],
                "receipt_replayed": checkpoint["receipt_replayed"],
            }
        )
    total_cost = sum(float(record["cost_usd"]) for record in records) + sum(
        float(row["cost_usd"]) for row in trajectory_rows
    )
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "plan_sha256": plan["plan_sha256"],
        "canary_status": canary["status"],
        "canary_cost_usd": sum(float(record["cost_usd"]) for record in records),
        "canary_probe_count": len(records),
        "canary_probe_conditions": [
            record.get("failure_condition") for record in records[:-1]
        ],
        "planned_cases": len(PANEL_CASE_IDS),
        "completed_cases": len(trajectory_rows),
        "operational_failures": 0,
        "total_cost_usd": total_cost,
        "hard_total_cost_ceiling_usd": HARD_TOTAL_COST_CEILING_USD,
        "financial_ceiling_enforcement": "provider_response_reported_cost",
        "route": plan["route"],
        "upstream": plan["upstream"],
        "sanitization": dict(SANITIZATION_DECLARATION),
    }
    files: dict[str, bytes] = {
        "README.md": (
            "# econevals first live panel\n\n"
            "One unscored route canary plus a frozen six-case panel, two cases from "
            "each of the three econevals tracks, on the pinned OpenRouter GLM 5.3 "
            "Flash/Parasail route. Every case is the pinned corpus case, unmodified. "
            "All cases ran sequentially through the shared runner and replayed their "
            "receipts. Objective values are measured against upstream's own solver "
            "output (gurobipy for procurement, scipy for pricing), not a "
            "reimplementation.\n"
        ).encode("utf-8"),
        "reports/summary.json": canonical_json_bytes(summary) + b"\n",
        "trajectories/archive.jsonl": jsonl(trajectory_rows),
    }
    for row in receipt_rows:
        files[f"receipts/{row['case_id']}.json"] = canonical_json_bytes(row) + b"\n"
    artifact_rows = [
        {
            "path": path,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
        }
        for path, payload in sorted(files.items())
    ]
    manifest: dict[str, Any] = {
        "schema_version": "aeread.publication_manifest/0.1",
        "publication_id": CAMPAIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "plan_sha256": plan["plan_sha256"],
        "artifacts": artifact_rows,
        "sanitization": dict(SANITIZATION_DECLARATION),
    }
    manifest["publication_sha256"] = _digest(manifest)
    files["publication_manifest.json"] = canonical_json_bytes(manifest) + b"\n"
    for name, payload in files.items():
        assert_public_payload(name, payload)
        atomic_publish(publication_root / name, payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--publish-to", type=Path, default=None)
    args = parser.parse_args(argv)
    if not args.execute:
        plan = build_campaign_plan()
        print(json.dumps({"plan_sha256": plan["plan_sha256"], "campaign_id": CAMPAIGN_ID}))
        return 0
    if args.publish_to is not None:
        publish_campaign(run_root=args.run_root, publication_root=args.publish_to)
        return 0
    asyncio.run(execute_campaign(run_root=args.run_root))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
