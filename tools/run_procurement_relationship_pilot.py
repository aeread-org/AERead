#!/usr/bin/env python
"""One live pass over the six repeated-sourcing worlds on a frozen route.

Three steps, each its own invocation, so what was planned is on disk before
anything is spent and what was spent can be re-audited without a key:

    prepare  --run-root runs/<id>   freeze route, seed, ceilings, sources, cases
    execute  --run-root runs/<id>   one episode per world, sequential, receipts
    replay   --run-root runs/<id>   re-audit every receipt from disk, no provider

Every limit that can end a run is in the frozen plan: the per-trajectory cost
ceiling, the run ceiling, the attempt count, the timeout and the route pins. A
cell that fails is recorded as a typed failure and never rerun in place. The
run directory is gitignored; nothing here is evidence-lane, and the key is
read from ``OPENROUTER_API_KEY`` and never written.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from aeread.shared_runner.model_call.harness import MinimalChatHarness  # noqa: E402
from aeread.shared_runner.run.resolver import canonical_json_bytes  # noqa: E402
from aeread.shared_runner.task.evaluation import audit_family_receipt  # noqa: E402
from aeread.shared_runner.task.execution import (  # noqa: E402
    OpenRouterChatClient,
    TokenPricing,
    execute_plan_cell,
)
from aeread_families.procurement_allocation import (  # noqa: E402
    RELATIONSHIP_PROMPT,
    build_openrouter_setup,
    finalize_procurement_allocation_execution,
    finalize_procurement_allocation_failure,
    load_case,
    replay_procurement_allocation_receipt,
)
from aeread_families.procurement_allocation.relationship_case_matrix import (  # noqa: E402
    CASE_PATHS,
)
from aeread_families.procurement_grounding import OpenRouterRoute  # noqa: E402

CAMPAIGN_ID = "procurement_allocation_relationship_gemini38_flash_pilot_v1"
PROMPT_ID = "procurement_relationship_prompt_v1"

#: The datacenter campaigns' Gemini route, prices as reviewed there on
#: 2026-09-03; the price caps refuse a repriced endpoint rather than pay it.
ROUTE = OpenRouterRoute(
    profile_id="procurement_relationship_gemini38_flash_aistudio_v1",
    model="google/gemini-3.8-flash",
    revision="google/gemini-3.8-flash-20260902",
    route_provider="Google AI Studio",
    quantization="unknown",
    pricing=TokenPricing(
        input_per_million=0.75,
        cached_input_per_million=0.075,
        output_per_million=3.75,
        pricing_id="openrouter_2026-09-03_gemini38_flash_aistudio_procurement_relationship_v1",
    ),
    max_prompt_price_per_million="1.35",
    max_completion_price_per_million="6.75",
    reasoning_effort="low",
    temperature_supported=True,
)

CONTRACT = {
    "campaign_id": CAMPAIGN_ID,
    "inference_seed": 73101,
    "temperature": 0.0,
    "max_output_tokens": 1800,
    "timeout_seconds": 180.0,
    "max_cost_usd_per_trajectory": 0.60,
    "max_cost_usd_total": 4.00,
    "max_action_attempts": 1,
    "retryable_conditions": [],
    "concurrency": 1,
    "prompt_id": PROMPT_ID,
    "prompt_sha256": hashlib.sha256(RELATIONSHIP_PROMPT.encode("utf-8")).hexdigest(),
}

SOURCE_FILES = (
    "src/aeread_families/procurement_allocation/environment.py",
    "src/aeread_families/procurement_allocation/relationship.py",
    "src/aeread_families/procurement_allocation/relationship_case_matrix.py",
    "src/aeread_families/procurement_allocation/headroom_screen.py",
    "src/aeread_families/procurement_allocation/runner.py",
    "tools/run_procurement_relationship_pilot.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def source_hashes() -> dict[str, str]:
    return {name: _sha256(REPOSITORY_ROOT / name) for name in SOURCE_FILES}


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _route_record() -> dict[str, Any]:
    return {
        "profile_id": ROUTE.profile_id,
        "model": ROUTE.model,
        "revision": ROUTE.revision,
        "route_provider": ROUTE.route_provider,
        "quantization": ROUTE.quantization,
        "pricing": {
            "input_per_million": ROUTE.pricing.input_per_million,
            "cached_input_per_million": ROUTE.pricing.cached_input_per_million,
            "output_per_million": ROUTE.pricing.output_per_million,
            "pricing_id": ROUTE.pricing.pricing_id,
        },
        "max_prompt_price_per_million": ROUTE.max_prompt_price_per_million,
        "max_completion_price_per_million": ROUTE.max_completion_price_per_million,
        "reasoning_effort": ROUTE.reasoning_effort,
        "temperature_supported": ROUTE.temperature_supported,
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# prepare
# --------------------------------------------------------------------------


def prepare(run_root: Path) -> dict[str, Any]:
    plan_path = run_root / "plan.json"
    if plan_path.exists():
        raise SystemExit(f"{plan_path} exists; a frozen plan is never rewritten")
    cases = []
    for path in CASE_PATHS:
        case = load_case(path)
        cases.append(
            {
                "slug": path.stem,
                "case_id": case.case_id,
                "content_sha256": case.content_sha256,
                "path": str(path.relative_to(REPOSITORY_ROOT)),
                "max_logical_actions": case.episode.max_logical_actions,
            }
        )
    plan = {
        **CONTRACT,
        "route": _route_record(),
        "cases": cases,
        "sources": source_hashes(),
        "git_head": _git_head(),
        "prepared_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    plan["plan_sha256"] = _digest(plan)
    _write_json(plan_path, plan)
    return plan


def read_plan(run_root: Path) -> dict[str, Any]:
    plan = json.loads((run_root / "plan.json").read_text(encoding="utf-8"))
    declared = plan["plan_sha256"]
    if _digest({key: value for key, value in plan.items() if key != "plan_sha256"}) != declared:
        raise SystemExit("plan.json does not digest to its own plan_sha256")
    if plan["sources"] != source_hashes():
        drifted = sorted(
            name for name, digest in source_hashes().items() if plan["sources"].get(name) != digest
        )
        raise SystemExit(f"sources changed since the plan was frozen: {drifted}")
    for row in plan["cases"]:
        case = load_case(REPOSITORY_ROOT / row["path"])
        if case.content_sha256 != row["content_sha256"]:
            raise SystemExit(f"case {row['case_id']} changed since the plan was frozen")
    return plan


# --------------------------------------------------------------------------
# execute
# --------------------------------------------------------------------------


def _setup_for(plan: Mapping[str, Any], row: Mapping[str, Any]):
    return build_openrouter_setup(
        ROUTE,
        case_path=REPOSITORY_ROOT / row["path"],
        seed=int(plan["inference_seed"]),
        max_output_tokens=int(plan["max_output_tokens"]),
        timeout_seconds=float(plan["timeout_seconds"]),
        max_cost_usd=float(plan["max_cost_usd_per_trajectory"]),
        harness=MinimalChatHarness(),
        prompt=RELATIONSHIP_PROMPT,
        prompt_id=str(plan["prompt_id"]),
        max_action_attempts=int(plan["max_action_attempts"]),
        retryable_conditions=tuple(plan["retryable_conditions"]),
    )


def _cell_root(run_root: Path, row: Mapping[str, Any]) -> Path:
    return run_root / "cells" / row["slug"]


def _public_trace(execution: Any) -> list[dict[str, Any]]:
    """The buyer's actions as sent, read back from each attempt's canonical response."""
    trace: list[dict[str, Any]] = []
    for ordinal, logical_action in enumerate(execution.action_executions, start=1):
        response = next(
            (
                attempt.canonical_response
                for attempt in reversed(logical_action.attempts)
                if attempt.canonical_response is not None
            ),
            None,
        )
        payload: Mapping[str, Any] | None = None
        if response is not None and isinstance(response.action, Mapping):
            payload = response.action
        elif response is not None:
            try:
                candidate = json.loads(response.text)
                payload = candidate if isinstance(candidate, Mapping) else None
            except (TypeError, json.JSONDecodeError):
                payload = None
        row: dict[str, Any] = {
            "ordinal": ordinal,
            "status": logical_action.status,
            "failure_code": logical_action.failure_code,
            "action": payload.get("action") if payload is not None else "unparseable",
        }
        if payload is not None:
            for key in ("supplier_id", "offer_id", "proposal", "award_lines", "fields", "reason"):
                value = payload.get(key)
                if value not in (None, [], {}):
                    row[key] = value
        trace.append(row)
    return trace


def _live_client() -> tuple[OpenRouterChatClient, Any]:
    """The kernel's OpenRouter adapter over an SDK client this tool can close.

    The adapter builds its own SDK client when given none and never closes
    it; closed at interpreter exit instead, after the loop is gone, it printed
    a closed-event-loop traceback on the first run. Owning the SDK client
    here lets the cell close it while the loop is still open.
    """
    from openai import AsyncOpenAI

    sdk_client = AsyncOpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
        max_retries=0,
    )
    return OpenRouterChatClient(sdk_client=sdk_client), sdk_client


async def _run_one(plan: Mapping[str, Any], row: Mapping[str, Any], run_root: Path) -> dict[str, Any]:
    client, sdk_client = _live_client()
    try:
        return await _run_one_with(plan, row, run_root, client)
    finally:
        await sdk_client.close()


async def _run_one_with(
    plan: Mapping[str, Any], row: Mapping[str, Any], run_root: Path, client: OpenRouterChatClient
) -> dict[str, Any]:
    setup = _setup_for(plan, row)
    cell = setup.plan.cells[0]
    evidence_root = _cell_root(run_root, row) / "evidence"
    started = time.perf_counter()
    try:
        execution = await execute_plan_cell(
            plan=setup.plan,
            cell_id=cell.cell_id,
            registry=setup.registry,
            evidence_root=evidence_root,
            prompt_sources=setup.prompt_sources,
            providers={"openrouter": client},
            pricing=setup.pricing,
            harnesses=setup.harnesses,
        )
        receipt = finalize_procurement_allocation_execution(setup=setup, execution=execution)
        replayed = replay_procurement_allocation_receipt(
            setup=setup, receipt=receipt, evidence_root=evidence_root
        )
        if canonical_json_bytes(replayed) != canonical_json_bytes(receipt):
            raise RuntimeError("replayed receipt differs from the live receipt")
        execution.evidence.audit_reconciliation()
        calls = [
            call
            for action in execution.action_executions
            for attempt in action.attempts
            for call in attempt.provider_calls
        ]
        finish_reasons = Counter(str(call.finish_reason) for call in calls)
        outcome = json.loads(canonical_json_bytes(execution.episode_result.outcome))
        return {
            "slug": row["slug"],
            "case_id": row["case_id"],
            "case_content_sha256": row["content_sha256"],
            "status": "completed",
            "decision": outcome["decision"],
            "termination_reason": outcome["termination_reason"],
            "failure_code": outcome.get("failure_code"),
            "feasible": bool(outcome["feasible"]),
            "feasible_award": bool(outcome["feasible_award"]),
            "periods": outcome["periods"],
            "periods_awarded": outcome["periods_awarded"],
            "period_decisions": outcome["period_decisions"],
            "period_margins": outcome["period_margins"],
            "switches": outcome["switches"],
            "realized_on_time_rate": outcome["realized_on_time_rate"],
            "contribution_margin_usd": outcome["contribution_margin_usd"],
            "upper_bound_usd": outcome["upper_bound_usd"],
            "myopic_reference_usd": outcome["myopic_reference_usd"],
            "loyal_reference_usd": outcome["loyal_reference_usd"],
            "regret_to_upper_bound_usd": outcome["regret_to_upper_bound_usd"],
            "violations": outcome["violations"],
            "information_cost_usd": outcome["information_cost_usd"],
            "action_count": len(execution.action_executions),
            "provider_call_count": len(calls),
            "finish_reasons": dict(sorted(finish_reasons.items())),
            "input_tokens": sum(call.input_tokens for call in calls),
            "cached_input_tokens": sum(call.cached_input_tokens for call in calls),
            "output_tokens": sum(call.output_tokens for call in calls),
            "cost_usd": execution.total_cost_usd,
            "resolved_models": sorted(
                {call.resolved_model for call in calls if call.resolved_model is not None}
            ),
            "receipt_sha256": receipt.receipt_sha256,
            "receipt_status": receipt.status,
            "inclusion_status": receipt.inclusion_status,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "period_results": outcome["period_results"],
            "action_trace": _public_trace(execution),
        }
    except Exception as error:  # noqa: BLE001 - typed into the row, never rerun
        failure_sha256 = None
        try:
            failure = finalize_procurement_allocation_failure(
                setup=setup, cell_id=cell.cell_id, evidence_root=evidence_root, error=error
            )
            failure_sha256 = failure.receipt_sha256
        except Exception as inner:  # noqa: BLE001
            failure_sha256 = f"unrecorded: {type(inner).__name__}: {inner}"
        return {
            "slug": row["slug"],
            "case_id": row["case_id"],
            "case_content_sha256": row["content_sha256"],
            "status": "failed",
            "error_type": type(error).__name__,
            "error": str(error)[:2000],
            "failure_receipt_sha256": failure_sha256,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }


def execute(run_root: Path) -> dict[str, Any]:
    plan = read_plan(run_root)
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY is not set")
    results_path = run_root / "results.json"
    rows: list[dict[str, Any]] = []
    spent = 0.0
    for row in plan["cases"]:
        result_path = _cell_root(run_root, row) / "result.json"
        if result_path.exists():
            existing = json.loads(result_path.read_text(encoding="utf-8"))
            rows.append(existing)
            spent += float(existing.get("cost_usd", 0.0))
            continue  # never rerun a recorded cell, completed or failed
        if spent >= float(plan["max_cost_usd_total"]):
            rows.append(
                {
                    "slug": row["slug"],
                    "case_id": row["case_id"],
                    "status": "not_run",
                    "reason": f"run ceiling {plan['max_cost_usd_total']} reached at {spent:.4f}",
                }
            )
            continue
        result = asyncio.run(_run_one(plan, row, run_root))
        _write_json(result_path, result)
        rows.append(result)
        spent += float(result.get("cost_usd", 0.0))
        print(
            f"{row['slug']:26s} {result['status']:9s} "
            + (
                f"margin={result['contribution_margin_usd']:.2f} bound={result['upper_bound_usd']:.2f} "
                f"regret={result['regret_to_upper_bound_usd']:.2f} awarded={result['periods_awarded']}/{result['periods']} "
                f"switches={result['switches']} cost=${result['cost_usd']:.4f}"
                if result["status"] == "completed"
                else f"{result.get('error_type')}: {result.get('error', '')[:120]}"
            ),
            flush=True,
        )
    summary = summarize(plan, rows)
    _write_json(results_path, summary)
    return summary


def summarize(plan: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if row.get("status") == "completed"]
    return {
        "campaign_id": plan["campaign_id"],
        "plan_sha256": plan["plan_sha256"],
        "route": plan["route"],
        "cells": len(rows),
        "completed": len(completed),
        "failed": sum(1 for row in rows if row.get("status") == "failed"),
        "not_run": sum(1 for row in rows if row.get("status") == "not_run"),
        "cost_usd": round(sum(float(row.get("cost_usd", 0.0)) for row in rows), 8),
        "input_tokens": sum(int(row.get("input_tokens", 0)) for row in rows),
        "output_tokens": sum(int(row.get("output_tokens", 0)) for row in rows),
        "mean_regret_usd": (
            round(sum(float(row["regret_to_upper_bound_usd"]) for row in completed) / len(completed), 8)
            if completed
            else None
        ),
        "periods_awarded": sum(int(row.get("periods_awarded", 0)) for row in completed),
        "periods": sum(int(row.get("periods", 0)) for row in completed),
        "rows": [
            {
                key: row.get(key)
                for key in (
                    "slug",
                    "status",
                    "decision",
                    "termination_reason",
                    "feasible_award",
                    "periods_awarded",
                    "period_decisions",
                    "switches",
                    "realized_on_time_rate",
                    "contribution_margin_usd",
                    "upper_bound_usd",
                    "myopic_reference_usd",
                    "loyal_reference_usd",
                    "regret_to_upper_bound_usd",
                    "violations",
                    "action_count",
                    "cost_usd",
                    "receipt_sha256",
                    "error_type",
                    "error",
                )
                if key in row
            }
            for row in rows
        ],
    }


# --------------------------------------------------------------------------
# replay
# --------------------------------------------------------------------------


def replay(run_root: Path) -> dict[str, Any]:
    plan = read_plan(run_root)
    report: dict[str, Any] = {"campaign_id": plan["campaign_id"], "cells": {}}
    for row in plan["cases"]:
        result_path = _cell_root(run_root, row) / "result.json"
        receipt_path = _cell_root(run_root, row) / "evidence" / "evaluation_receipt.json"
        if not result_path.exists():
            report["cells"][row["slug"]] = "no result recorded"
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("status") != "completed":
            report["cells"][row["slug"]] = f"{result.get('status')}: not replayable"
            continue
        receipt_paths = sorted(_cell_root(run_root, row).glob("evidence/**/evaluation_receipt.json"))
        if not receipt_paths:
            report["cells"][row["slug"]] = "receipt missing"
            continue
        setup = _setup_for(plan, row)
        audit = audit_family_receipt(setup=setup, receipt_path=receipt_paths[0])
        recorded = json.loads(receipt_paths[0].read_text(encoding="utf-8"))
        matches = recorded.get("receipt_sha256") == result["receipt_sha256"]
        report["cells"][row["slug"]] = {
            "receipt_sha256_matches_result": matches,
            "audit": json.loads(canonical_json_bytes(audit)),
        }
        del receipt_path
    _write_json(run_root / "replay.json", report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("prepare", "execute", "replay"))
    parser.add_argument("--run-root", type=Path, required=True)
    arguments = parser.parse_args(argv)
    run_root = arguments.run_root.resolve()
    if arguments.step == "prepare":
        plan = prepare(run_root)
        print(json.dumps({k: plan[k] for k in ("campaign_id", "plan_sha256", "git_head")}, indent=2))
    elif arguments.step == "execute":
        summary = execute(run_root)
        print(json.dumps({k: summary[k] for k in ("completed", "failed", "not_run", "cost_usd", "mean_regret_usd")}, indent=2))
    else:
        report = replay(run_root)
        print(json.dumps({slug: (cell if isinstance(cell, str) else cell["receipt_sha256_matches_result"]) for slug, cell in report["cells"].items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
