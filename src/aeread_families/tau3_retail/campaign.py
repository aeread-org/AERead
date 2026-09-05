"""Frozen first-live campaign for the tau3.retail external adapter."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.analysis.research import deserialize_evaluation_receipt
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
    ArenaChatClient,
    ProviderRequest,
    execute_plan_cell,
)
from aeread.shared_runner.task.receipts import read_evaluation_receipt

from .cases import UPSTREAM_COMMIT, UPSTREAM_REPO
from .live import (
    MODEL,
    PRICING,
    PROVIDER,
    QUANTIZATION,
    REVISION,
    ROUTE_PROVIDER,
    USER_PROMPT,
    build_live_setup,
    load_case,
    user_output_schema,
)
from .tau2_bridge import Tau2Bridge

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN_ID = "tau3_retail_glm5p2_arena_pipeline_proof_v5"
CANARY_CASE_ID = "tau3.retail.base.53"
PANEL_CASE_IDS = (
    "tau3.retail.base.14",
    "tau3.retail.base.10",
    "tau3.retail.base.5",
    "tau3.retail.base.16",
    "tau3.retail.base.30",
)
PANEL_STRATA = (
    "direct_return_state_transition",
    "payment_method_refusal_fallback",
    "confirmation_changed_mind_nonmutation",
    "compound_multi_order_state",
    "lookup_conditional_fallback",
)
SEED = 300
MAX_PARALLEL_CELLS = 1
MAX_CANARY_COST_USD = 0.025
MAX_CANARY_OUTPUT_TOKENS = 256
MAX_TRAJECTORY_COST_USD = 0.05
HARD_TOTAL_COST_CEILING_USD = 0.30


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
        "environment.py",
        "harness.py",
        "live.py",
        "measurement.py",
        "tau2_bridge.py",
        "tools.py",
    )
    source_hashes = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in source_names
    }
    plan: dict[str, Any] = {
        "schema_version": "aeread.tau3_retail_live_campaign/0.1",
        "campaign_id": CAMPAIGN_ID,
        "freeze_status": "pipeline_proof_frozen_before_live_execution",
        "upstream": {"repository": UPSTREAM_REPO, "commit": UPSTREAM_COMMIT},
        "route": {
            "provider": PROVIDER,
            "model": MODEL,
            "revision": REVISION,
            "route_provider": ROUTE_PROVIDER,
            "quantization": QUANTIZATION,
            "fallbacks": "not_reported",
            "reasoning_effort": "low",
            "route_attestation": "arena_catalog_model_id_only",
            "provider_cost_status": "response_reported",
            "provider_seed_status": "not_supported",
            "pricing_id": PRICING.pricing_id,
            "pricing_sha256": PRICING.content_sha256(),
        },
        "canary": {
            "case_id": CANARY_CASE_ID,
            "scored": False,
            "max_cost_usd": MAX_CANARY_COST_USD,
            "max_output_tokens": MAX_CANARY_OUTPUT_TOKENS,
        },
        "panel": [
            {
                "case_id": case.case_id,
                "case_content_sha256": case.content_sha256,
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
    return {
        "catalog_model_id": MODEL,
        "provider_cost_status": "response_reported",
    }


async def run_canary(*, path: Path, plan_sha256: str) -> dict[str, Any]:
    if path.exists():
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("plan_sha256") != plan_sha256 or value.get("record_sha256") != _digest(
            {key: item for key, item in value.items() if key != "record_sha256"}
        ):
            raise ValueError("canary checkpoint does not match the frozen plan")
        return value
    request = ProviderRequest(
        provider_call_id="tau3_retail_pipeline_canary",
        provider=PROVIDER,
        base_url="https://api.preview.arena.ai/v1",
        model=MODEL,
        revision=REVISION,
        instructions=USER_PROMPT,
        input_text=canonical_json_bytes(
            {
                "phase_id": "user_turn",
                "case_id": CANARY_CASE_ID,
                "instruction": "Return a short in-character greeting for route admission.",
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
        output_schema=user_output_schema(),
        provider_metadata=_route_metadata(),
        seed=SEED,
    ).with_computed_hash()
    record: dict[str, Any] = {
        "schema_version": "aeread.provider_admission_canary/0.1",
        "campaign_id": CAMPAIGN_ID,
        "plan_sha256": plan_sha256,
        "case_id": CANARY_CASE_ID,
        "scored": False,
        "request_sha256": request.request_sha256,
        "model": MODEL,
        "revision": REVISION,
        "route_provider": ROUTE_PROVIDER,
        "attempted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    result = None
    try:
        result = await ArenaChatClient().complete(request)
        value = json.loads(result.output_text)
        if value.get("kind") != "reply" or not isinstance(value.get("text"), str):
            raise ValueError("canary did not return the required structured reply")
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


async def execute_campaign(*, run_root: Path, upstream_root: Path) -> None:
    plan_path = run_root / "campaign_plan.json"
    plan = build_campaign_plan()
    _write_once_json(plan_path, plan)
    _verify_plan(json.loads(plan_path.read_text(encoding="utf-8")))
    bridge = Tau2Bridge.discover(upstream_root)
    canary = await run_canary(
        path=run_root / "checkpoints" / "canary.json",
        plan_sha256=plan["plan_sha256"],
    )
    if canary.get("status") != "admitted":
        raise RuntimeError("tau3 retail canary was rejected; campaign stopped")
    total_cost = float(canary["cost_usd"])
    provider = ArenaChatClient()
    for ordinal, case_id in enumerate(PANEL_CASE_IDS):
        checkpoint_path = run_root / "checkpoints" / f"{ordinal:02d}_{case_id}.json"
        if checkpoint_path.exists():
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            recorded = checkpoint.get("record_sha256")
            checkpoint_payload = {
                key: item for key, item in checkpoint.items() if key != "record_sha256"
            }
            if (
                checkpoint.get("status") != "complete"
                or checkpoint.get("plan_sha256") != plan["plan_sha256"]
                or recorded != _digest(checkpoint_payload)
            ):
                raise RuntimeError("campaign cannot resume from a failed checkpoint")
            total_cost += float(checkpoint["cost_usd"])
            continue
        if total_cost + MAX_TRAJECTORY_COST_USD > HARD_TOTAL_COST_CEILING_USD:
            raise RuntimeError("insufficient campaign budget reserve for the next case")
        setup = build_live_setup(
            case_id=case_id,
            upstream_root=upstream_root,
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
                    "tau3 retail case did not produce an included successful receipt"
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
                "schema_version": "aeread.tau3_retail_checkpoint/0.1",
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
                "upstream_step_count": execution.episode_result.outcome[
                    "upstream_step_count"
                ],
            }
            checkpoint["record_sha256"] = _digest(checkpoint)
            _write_once_json(checkpoint_path, checkpoint)
        except Exception as error:
            failure = {
                "schema_version": "aeread.tau3_retail_checkpoint/0.1",
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
    canary = json.loads(
        (run_root / "checkpoints" / "canary.json").read_text(encoding="utf-8")
    )
    recorded_canary_sha256 = canary.get("record_sha256")
    canary_payload = {
        key: item for key, item in canary.items() if key != "record_sha256"
    }
    if (
        canary.get("status") != "admitted"
        or canary.get("plan_sha256") != plan["plan_sha256"]
        or recorded_canary_sha256 != _digest(canary_payload)
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
        recorded = checkpoint.get("record_sha256")
        checkpoint_payload = {
            key: item for key, item in checkpoint.items() if key != "record_sha256"
        }
        if (
            checkpoint.get("status") != "complete"
            or checkpoint.get("plan_sha256") != plan["plan_sha256"]
            or recorded != _digest(checkpoint_payload)
        ):
            raise RuntimeError(f"cannot publish incomplete case {case_id}")
        serialized = read_evaluation_receipt(run_root / checkpoint["receipt_path"])
        receipt = deserialize_evaluation_receipt(serialized)
        safe = receipt_projection(serialized, campaign_cell_key=f"{ordinal:02d}:{case_id}")
        receipt_rows.append(safe)
        primary = receipt.scores[0]
        trajectory_rows.append(
            {
                "case_id": case_id,
                "stratum": PANEL_STRATA[ordinal],
                "termination_reason": checkpoint["termination_reason"],
                "db_state_score": primary.primary.value if primary.primary else None,
                "tool_error_count": primary.metrics["tool_error_count"].value,
                "redundant_tool_call_count": primary.metrics[
                    "redundant_tool_call_count"
                ].value,
                "upstream_step_count": checkpoint["upstream_step_count"],
                "cost_usd": checkpoint["cost_usd"],
                "receipt_sha256": checkpoint["receipt_sha256"],
                "receipt_replayed": checkpoint["receipt_replayed"],
            }
        )
    total_cost = float(canary["cost_usd"]) + sum(
        float(row["cost_usd"]) for row in trajectory_rows
    )
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "plan_sha256": plan["plan_sha256"],
        "canary_status": canary["status"],
        "canary_cost_usd": canary["cost_usd"],
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
            f"# tau3 retail pipeline proof\n\n"
            f"This bundle records one unscored route canary and a frozen five-case "
            f"panel spanning the five predeclared tau3 retail pilot strata. All cases "
            f"ran sequentially through the shared runner and replayed their receipts.\n"
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
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--upstream-root", type=Path)
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--publish-only", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.execute and arguments.publish_only:
        parser.error("--execute and --publish-only are mutually exclusive")
    plan = build_campaign_plan()
    _write_once_json(arguments.run_root / "campaign_plan.json", plan)
    if arguments.execute:
        if arguments.upstream_root is None:
            parser.error("--execute requires --upstream-root")
        asyncio.run(
            execute_campaign(
                run_root=arguments.run_root,
                upstream_root=arguments.upstream_root.resolve(),
            )
        )
    elif arguments.publish_only:
        if arguments.publication_root is None:
            parser.error("--publish-only requires --publication-root")
        publish_campaign(
            run_root=arguments.run_root,
            publication_root=arguments.publication_root,
        )
    else:
        print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
