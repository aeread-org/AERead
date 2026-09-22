#!/usr/bin/env python
"""Live passes over the six repeated-sourcing worlds on a frozen route.

Three steps, each its own invocation, so what was planned is on disk before
anything is spent and what was spent can be re-audited without a key:

    prepare  --run-root runs/<id> --campaign-id <id> --seeds 73201 73202 73203
    execute  --run-root runs/<id>      one episode per world x seed, sequential
    replay   --run-root runs/<id>      re-audit every receipt from disk, no provider

A seed binds two things: the inference seed sent to the route, and the
world's ``delivery_seed``, which is re-sealed into a per-seed episode case so
the delivery history the buyer sees from period two onward differs between
seeds while the economic world, its bound and its references do not. The
independent unit is still the world; the summary's interval resamples worlds
and carries every seed of a world together.

Every limit that can end a run is in the frozen plan: the per-trajectory cost
ceiling, the run ceiling, the attempt count, the timeout and the route pins. A
cell that fails is recorded as a typed failure and never rerun in place. The
run directory is gitignored; nothing here is evidence-lane, and the key is
read from ``OPENROUTER_API_KEY`` and never written.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import random
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from aeread.shared_runner.model_call.harness import MinimalChatHarness  # noqa: E402
from aeread.shared_runner.run.resolver import (  # noqa: E402
    canonical_json_bytes,
    case_content_sha256,
)
from aeread.shared_runner.schemas import CaseManifest  # noqa: E402
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

PROMPT_ID = "procurement_relationship_prompt_v1"
DEFAULT_SEEDS = (73101,)
BOOTSTRAP_SEED = 20260921
BOOTSTRAP_RESAMPLES = 10_000

#: Routes this tool may freeze. Prices are the ones the sealed campaigns
#: reviewed (Gemini on 2026-09-03 for the datacenter panels, GLM on
#: 2026-09-03 for the procurement scaffold campaigns); the price caps refuse a
#: repriced endpoint rather than pay it. Both are chat routes through the
#: kernel's OpenRouter client, so a paired contrast between them changes the
#: route and nothing else. Jev (`typesafe/jev-1.13`) is not listed: it is a
#: finite-choice decisions endpoint without seed, temperature or reasoning,
#: and putting it in this seat needs a menu adapter, which is a different
#: interface and therefore a different treatment.
ROUTES: dict[str, OpenRouterRoute] = {
    "gemini38_flash_aistudio": OpenRouterRoute(
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
    ),
    "glm53_flash_parasail": OpenRouterRoute(
        profile_id="procurement_relationship_glm53_flash_parasail_v1",
        model="z-ai/glm-5.3-flash",
        revision="z-ai/glm-5.3-flash-20260826",
        route_provider="Parasail",
        quantization="fp8",
        pricing=TokenPricing(
            input_per_million=0.15,
            cached_input_per_million=0.03,
            output_per_million=0.50,
            pricing_id="openrouter_2026-09-03_glm53_flash_parasail_procurement_relationship_v1",
        ),
        max_prompt_price_per_million="0.15",
        max_completion_price_per_million="0.50",
        reasoning_effort="low",
        temperature_supported=True,
    ),
}
DEFAULT_ROUTE = "gemini38_flash_aistudio"

CONTRACT = {
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
    "cluster_level": "economic_world",
    "bootstrap": {"seed": BOOTSTRAP_SEED, "resamples": BOOTSTRAP_RESAMPLES, "unit": "world"},
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


def _route_record(route: OpenRouterRoute) -> dict[str, Any]:
    return {
        "profile_id": route.profile_id,
        "model": route.model,
        "revision": route.revision,
        "route_provider": route.route_provider,
        "quantization": route.quantization,
        "pricing": {
            "input_per_million": route.pricing.input_per_million,
            "cached_input_per_million": route.pricing.cached_input_per_million,
            "output_per_million": route.pricing.output_per_million,
            "pricing_id": route.pricing.pricing_id,
        },
        "max_prompt_price_per_million": route.max_prompt_price_per_million,
        "max_completion_price_per_million": route.max_completion_price_per_million,
        "reasoning_effort": route.reasoning_effort,
        "temperature_supported": route.temperature_supported,
    }


def _route_from_record(record: Mapping[str, Any]) -> OpenRouterRoute:
    """The frozen plan's route, so execute and replay never read the code's table."""
    pricing = record["pricing"]
    return OpenRouterRoute(
        profile_id=str(record["profile_id"]),
        model=str(record["model"]),
        revision=str(record["revision"]),
        route_provider=str(record["route_provider"]),
        quantization=str(record["quantization"]),
        pricing=TokenPricing(
            input_per_million=float(pricing["input_per_million"]),
            cached_input_per_million=float(pricing["cached_input_per_million"]),
            output_per_million=float(pricing["output_per_million"]),
            pricing_id=str(pricing["pricing_id"]),
        ),
        max_prompt_price_per_million=str(record["max_prompt_price_per_million"]),
        max_completion_price_per_million=str(record["max_completion_price_per_million"]),
        reasoning_effort=record["reasoning_effort"],
        temperature_supported=bool(record["temperature_supported"]),
    )


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def episode_case(world: Mapping[str, Any], seed: int) -> dict[str, Any]:
    """The world re-sealed with this seed's delivery draws, its economics untouched."""
    if isinstance(seed, bool) or not isinstance(seed, int) or seed <= 0:
        raise ValueError("seed must be a positive integer")
    result = copy.deepcopy(dict(world))
    result["case_id"] = f"{world['case_id']}.delivery_{seed}"
    result["payload"]["interaction"]["periods"]["delivery_seed"] = seed
    result["content_sha256"] = "0" * 64
    result["content_sha256"] = case_content_sha256(CaseManifest.from_dict(result))
    return result


# --------------------------------------------------------------------------
# prepare
# --------------------------------------------------------------------------


def prepare(
    run_root: Path, *, campaign_id: str, seeds: Sequence[int], route_id: str = DEFAULT_ROUTE
) -> dict[str, Any]:
    plan_path = run_root / "plan.json"
    if plan_path.exists():
        raise SystemExit(f"{plan_path} exists; a frozen plan is never rewritten")
    if not seeds or len(set(seeds)) != len(seeds):
        raise SystemExit("seeds must be non-empty and distinct")
    if route_id not in ROUTES:
        raise SystemExit(f"unknown route {route_id!r}; known: {sorted(ROUTES)}")
    worlds = []
    cells = []
    for path in CASE_PATHS:
        case = load_case(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        worlds.append(
            {
                "slug": path.stem,
                "case_id": case.case_id,
                "content_sha256": case.content_sha256,
                "path": str(path.relative_to(REPOSITORY_ROOT)),
                "max_logical_actions": case.episode.max_logical_actions,
            }
        )
        for seed in seeds:
            derived = episode_case(raw, seed)
            relative = Path("cases") / f"{path.stem}__seed_{seed}.json"
            _write_json(run_root / relative, derived)
            cells.append(
                {
                    "slug": path.stem,
                    "seed": int(seed),
                    "world_case_id": case.case_id,
                    "case_id": derived["case_id"],
                    "content_sha256": derived["content_sha256"],
                    "path": str(relative),
                }
            )
    plan = {
        **CONTRACT,
        "campaign_id": campaign_id,
        "seeds": [int(seed) for seed in seeds],
        "route_id": route_id,
        "route": _route_record(ROUTES[route_id]),
        "worlds": worlds,
        "cells": cells,
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
    current = source_hashes()
    drifted = sorted(name for name, digest in current.items() if plan["sources"].get(name) != digest)
    family_drift = [name for name in drifted if not name.startswith("tools/")]
    if family_drift:
        # The family sources decide what a cell measures; a changed one is a
        # new identity. The tool's own bytes are recorded but not enforced,
        # so a later fix to reporting does not lock earlier runs out of
        # replay (the DC-T-06 shape).
        raise SystemExit(f"family sources changed since the plan was frozen: {family_drift}")
    if drifted:
        print(f"note: tool bytes differ from the frozen plan ({drifted}); family sources unchanged", file=sys.stderr)
    for row in plan["worlds"]:
        case = load_case(REPOSITORY_ROOT / row["path"])
        if case.content_sha256 != row["content_sha256"]:
            raise SystemExit(f"world {row['case_id']} changed since the plan was frozen")
    for cell in plan["cells"]:
        case = load_case(run_root / cell["path"])
        if case.content_sha256 != cell["content_sha256"]:
            raise SystemExit(f"episode case {cell['case_id']} changed since the plan was frozen")
    return plan


# --------------------------------------------------------------------------
# execute
# --------------------------------------------------------------------------


def _setup_for(plan: Mapping[str, Any], cell: Mapping[str, Any], run_root: Path):
    return build_openrouter_setup(
        _route_from_record(plan["route"]),
        case_path=run_root / cell["path"],
        seed=int(cell["seed"]),
        max_output_tokens=int(plan["max_output_tokens"]),
        timeout_seconds=float(plan["timeout_seconds"]),
        max_cost_usd=float(plan["max_cost_usd_per_trajectory"]),
        harness=MinimalChatHarness(),
        prompt=RELATIONSHIP_PROMPT,
        prompt_id=str(plan["prompt_id"]),
        max_action_attempts=int(plan["max_action_attempts"]),
        retryable_conditions=tuple(plan["retryable_conditions"]),
    )


def _cell_root(run_root: Path, cell: Mapping[str, Any]) -> Path:
    return run_root / "cells" / cell["slug"] / f"seed_{cell['seed']}"


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


async def _run_one(plan: Mapping[str, Any], cell: Mapping[str, Any], run_root: Path) -> dict[str, Any]:
    client, sdk_client = _live_client()
    try:
        return await _run_one_with(plan, cell, run_root, client)
    finally:
        await sdk_client.close()


async def _run_one_with(
    plan: Mapping[str, Any], cell: Mapping[str, Any], run_root: Path, client: OpenRouterChatClient
) -> dict[str, Any]:
    setup = _setup_for(plan, cell, run_root)
    plan_cell = setup.plan.cells[0]
    evidence_root = _cell_root(run_root, cell) / "evidence"
    started = time.perf_counter()
    identity = {
        "slug": cell["slug"],
        "seed": int(cell["seed"]),
        "world_case_id": cell["world_case_id"],
        "case_id": cell["case_id"],
        "case_content_sha256": cell["content_sha256"],
    }
    try:
        execution = await execute_plan_cell(
            plan=setup.plan,
            cell_id=plan_cell.cell_id,
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
        trace = _public_trace(execution)
        actions = Counter(str(row["action"]) for row in trace)
        quoted = sorted(
            {
                supplier_id
                for period in outcome["period_results"]
                for supplier_id in period.get("quoted_supplier_ids", [])
            }
        )
        return {
            **identity,
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
            "advantage_over_myopic_usd": round(
                float(outcome["contribution_margin_usd"]) - float(outcome["myopic_reference_usd"]), 8
            ),
            "violations": outcome["violations"],
            "information_cost_usd": outcome["information_cost_usd"],
            "action_count": len(execution.action_executions),
            "action_counts": dict(sorted(actions.items())),
            "counters": int(actions.get("counter_offer", 0)),
            "inquiries": int(actions.get("inquire", 0)),
            "suppliers_quoted": quoted,
            "suppliers_quoted_count": len(quoted),
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
            "action_trace": trace,
        }
    except Exception as error:  # noqa: BLE001 - typed into the row, never rerun
        failure_sha256 = None
        try:
            failure = finalize_procurement_allocation_failure(
                setup=setup, cell_id=plan_cell.cell_id, evidence_root=evidence_root, error=error
            )
            failure_sha256 = failure.receipt_sha256
        except Exception as inner:  # noqa: BLE001
            failure_sha256 = f"unrecorded: {type(inner).__name__}: {inner}"
        return {
            **identity,
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
    rows: list[dict[str, Any]] = []
    spent = 0.0
    for cell in plan["cells"]:
        result_path = _cell_root(run_root, cell) / "result.json"
        if result_path.exists():
            existing = json.loads(result_path.read_text(encoding="utf-8"))
            rows.append(existing)
            spent += float(existing.get("cost_usd", 0.0))
            continue  # never rerun a recorded cell, completed or failed
        if spent >= float(plan["max_cost_usd_total"]):
            rows.append(
                {
                    "slug": cell["slug"],
                    "seed": int(cell["seed"]),
                    "case_id": cell["case_id"],
                    "status": "not_run",
                    "reason": f"run ceiling {plan['max_cost_usd_total']} reached at {spent:.4f}",
                }
            )
            continue
        result = asyncio.run(_run_one(plan, cell, run_root))
        _write_json(result_path, result)
        rows.append(result)
        spent += float(result.get("cost_usd", 0.0))
        label = f"{cell['slug']}/seed_{cell['seed']}"
        print(
            f"{label:38s} {result['status']:9s} "
            + (
                f"margin={result['contribution_margin_usd']:.2f} bound={result['upper_bound_usd']:.2f} "
                f"regret={result['regret_to_upper_bound_usd']:.2f} awarded={result['periods_awarded']}/{result['periods']} "
                f"counters={result['counters']} quoted={result['suppliers_quoted_count']} cost=${result['cost_usd']:.4f}"
                if result["status"] == "completed"
                else f"{result.get('error_type')}: {result.get('error', '')[:120]}"
            ),
            flush=True,
        )
    summary = summarize(plan, rows)
    _write_json(run_root / "results.json", summary)
    return summary


# --------------------------------------------------------------------------
# summary
# --------------------------------------------------------------------------


def _bootstrap_interval(cluster_means: Sequence[float]) -> list[float] | None:
    """Percentile interval of the mean over worlds, resampling whole worlds."""
    if len(cluster_means) < 2:
        return None
    generator = random.Random(BOOTSTRAP_SEED)
    count = len(cluster_means)
    draws = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        sample = [cluster_means[generator.randrange(count)] for _ in range(count)]
        draws.append(sum(sample) / count)
    draws.sort()
    lower = draws[int(0.025 * (BOOTSTRAP_RESAMPLES - 1))]
    upper = draws[int(0.975 * (BOOTSTRAP_RESAMPLES - 1))]
    return [round(lower, 8), round(upper, 8)]


def _world_summary(slug: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if row.get("status") == "completed"]
    regrets = [float(row["regret_to_upper_bound_usd"]) for row in completed]
    advantages = [float(row["advantage_over_myopic_usd"]) for row in completed]
    return {
        "slug": slug,
        "cells": len(rows),
        "completed": len(completed),
        "upper_bound_usd": completed[0]["upper_bound_usd"] if completed else None,
        "myopic_reference_usd": completed[0]["myopic_reference_usd"] if completed else None,
        "loyal_reference_usd": completed[0]["loyal_reference_usd"] if completed else None,
        "mean_regret_usd": round(statistics.mean(regrets), 8) if regrets else None,
        "regret_by_seed": {str(row["seed"]): float(row["regret_to_upper_bound_usd"]) for row in completed},
        "within_world_regret_variance": (
            round(statistics.variance(regrets), 8) if len(regrets) > 1 else 0.0
        ),
        "mean_advantage_over_myopic_usd": round(statistics.mean(advantages), 8) if advantages else None,
        "periods_awarded": sum(int(row["periods_awarded"]) for row in completed),
        "periods": sum(int(row["periods"]) for row in completed),
        "counters": sum(int(row["counters"]) for row in completed),
        "inquiries": sum(int(row["inquiries"]) for row in completed),
        "switches": sum(int(row["switches"]) for row in completed),
        "suppliers_quoted_by_seed": {
            str(row["seed"]): row["suppliers_quoted"] for row in completed
        },
        "distinct_routines": len(
            {
                json.dumps([r["action"] + ":" + str(r.get("supplier_id", "")) for r in row["action_trace"]])
                for row in completed
            }
        ),
        "cost_usd": round(sum(float(row.get("cost_usd", 0.0)) for row in rows), 8),
    }


def summarize(plan: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if row.get("status") == "completed"]
    by_world: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_world.setdefault(str(row["slug"]), []).append(row)
    worlds = [_world_summary(slug, cells) for slug, cells in by_world.items()]
    measured = [world for world in worlds if world["completed"] > 0]
    regret_means = [world["mean_regret_usd"] for world in measured]
    advantage_means = [world["mean_advantage_over_myopic_usd"] for world in measured]
    return {
        "campaign_id": plan["campaign_id"],
        "plan_sha256": plan["plan_sha256"],
        "route": plan["route"],
        "seeds": plan["seeds"],
        "cells": len(rows),
        "completed": len(completed),
        "failed": sum(1 for row in rows if row.get("status") == "failed"),
        "not_run": sum(1 for row in rows if row.get("status") == "not_run"),
        "cost_usd": round(sum(float(row.get("cost_usd", 0.0)) for row in rows), 8),
        "input_tokens": sum(int(row.get("input_tokens", 0)) for row in rows),
        "output_tokens": sum(int(row.get("output_tokens", 0)) for row in rows),
        "worlds_measured": len(measured),
        "cluster_level": plan["cluster_level"],
        "mean_regret_usd": round(statistics.mean(regret_means), 8) if regret_means else None,
        "mean_regret_usd_95_world_bootstrap": _bootstrap_interval(regret_means),
        "mean_advantage_over_myopic_usd": (
            round(statistics.mean(advantage_means), 8) if advantage_means else None
        ),
        "mean_advantage_over_myopic_usd_95_world_bootstrap": _bootstrap_interval(advantage_means),
        "periods_awarded": sum(int(row.get("periods_awarded", 0)) for row in completed),
        "periods": sum(int(row.get("periods", 0)) for row in completed),
        "counters": sum(int(row.get("counters", 0)) for row in completed),
        "inquiries": sum(int(row.get("inquiries", 0)) for row in completed),
        "switches": sum(int(row.get("switches", 0)) for row in completed),
        "claim_scope": (
            "one route, descriptive; the interval resamples worlds and says nothing "
            "about other routes, other worlds or the model in general"
        ),
        "worlds": worlds,
        "rows": [
            {
                key: row.get(key)
                for key in (
                    "slug",
                    "seed",
                    "status",
                    "decision",
                    "termination_reason",
                    "feasible_award",
                    "periods_awarded",
                    "period_decisions",
                    "switches",
                    "counters",
                    "inquiries",
                    "suppliers_quoted",
                    "realized_on_time_rate",
                    "contribution_margin_usd",
                    "upper_bound_usd",
                    "myopic_reference_usd",
                    "loyal_reference_usd",
                    "regret_to_upper_bound_usd",
                    "advantage_over_myopic_usd",
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
    for cell in plan["cells"]:
        label = f"{cell['slug']}/seed_{cell['seed']}"
        result_path = _cell_root(run_root, cell) / "result.json"
        if not result_path.exists():
            report["cells"][label] = "no result recorded"
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("status") != "completed":
            report["cells"][label] = f"{result.get('status')}: not replayable"
            continue
        receipt_paths = sorted(_cell_root(run_root, cell).glob("evidence/**/evaluation_receipt.json"))
        if not receipt_paths:
            report["cells"][label] = "receipt missing"
            continue
        setup = _setup_for(plan, cell, run_root)
        audit = audit_family_receipt(setup=setup, receipt_path=receipt_paths[0])
        recorded = json.loads(receipt_paths[0].read_text(encoding="utf-8"))
        report["cells"][label] = {
            "receipt_sha256_matches_result": recorded.get("receipt_sha256") == result["receipt_sha256"],
            "audit": json.loads(canonical_json_bytes(audit)),
        }
    _write_json(run_root / "replay.json", report)
    return report


# --------------------------------------------------------------------------
# compare: two runs on the same worlds and seeds, paired by world
# --------------------------------------------------------------------------


def compare(run_root: Path, against: Path) -> dict[str, Any]:
    """Paired contrast of this run against another on identical worlds and seeds.

    The difference is taken per world and seed, averaged within the world, and
    the interval resamples worlds. Nothing here ranks: two routes on six
    curated worlds give a paired descriptive contrast with an interval, which
    is the most the design allows.
    """
    left = json.loads((run_root / "results.json").read_text(encoding="utf-8"))
    right = json.loads((against / "results.json").read_text(encoding="utf-8"))
    if left["seeds"] != right["seeds"]:
        raise SystemExit("runs were made on different seeds; no pairing")
    left_rows = {(row["slug"], row["seed"]): row for row in left["rows"] if row.get("status") == "completed"}
    right_rows = {(row["slug"], row["seed"]): row for row in right["rows"] if row.get("status") == "completed"}
    keys = sorted(set(left_rows) & set(right_rows))
    if not keys:
        raise SystemExit("no completed cell is shared by both runs")
    for key in keys:
        if left_rows[key]["upper_bound_usd"] != right_rows[key]["upper_bound_usd"]:
            raise SystemExit(f"bound differs on {key}; the runs are not on the same world")
    per_world: dict[str, dict[str, list[float]]] = {}
    for slug, seed in keys:
        entry = per_world.setdefault(slug, {"regret": [], "margin": [], "counters": [], "quoted": []})
        entry["regret"].append(
            float(left_rows[(slug, seed)]["regret_to_upper_bound_usd"])
            - float(right_rows[(slug, seed)]["regret_to_upper_bound_usd"])
        )
        entry["margin"].append(
            float(left_rows[(slug, seed)]["contribution_margin_usd"])
            - float(right_rows[(slug, seed)]["contribution_margin_usd"])
        )
        entry["counters"].append(
            float(left_rows[(slug, seed)]["counters"]) - float(right_rows[(slug, seed)]["counters"])
        )
        entry["quoted"].append(
            float(len(left_rows[(slug, seed)]["suppliers_quoted"]))
            - float(len(right_rows[(slug, seed)]["suppliers_quoted"]))
        )
    worlds = {
        slug: {name: round(statistics.mean(values), 8) for name, values in entry.items()}
        for slug, entry in per_world.items()
    }
    regret_deltas = [worlds[slug]["regret"] for slug in sorted(worlds)]
    report = {
        "left_campaign_id": left["campaign_id"],
        "right_campaign_id": right["campaign_id"],
        "left_route": left["route"]["model"],
        "right_route": right["route"]["model"],
        "direction": "left minus right, per world and seed, averaged within world",
        "paired_cells": len(keys),
        "worlds": len(worlds),
        "mean_regret_delta_usd": round(statistics.mean(regret_deltas), 8),
        "mean_regret_delta_usd_95_world_bootstrap": _bootstrap_interval(regret_deltas),
        "worlds_left_lower_regret": sum(1 for value in regret_deltas if value < 0),
        "worlds_right_lower_regret": sum(1 for value in regret_deltas if value > 0),
        "per_world": worlds,
        "claim_scope": "paired descriptive contrast on curated worlds; no ranking",
    }
    _write_json(run_root / f"comparison_vs_{right['campaign_id']}.json", report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("prepare", "execute", "replay", "compare"))
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--campaign-id", default=None, help="prepare: the frozen campaign identity")
    parser.add_argument("--route", default=DEFAULT_ROUTE, choices=sorted(ROUTES), help="prepare: the route to freeze")
    parser.add_argument(
        "--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS), help="prepare: one cell per world per seed"
    )
    parser.add_argument("--against", type=Path, default=None, help="compare: the other run root")
    arguments = parser.parse_args(argv)
    run_root = arguments.run_root.resolve()
    if arguments.step == "prepare":
        if not arguments.campaign_id:
            raise SystemExit("prepare requires --campaign-id")
        plan = prepare(
            run_root, campaign_id=arguments.campaign_id, seeds=arguments.seeds, route_id=arguments.route
        )
        print(
            json.dumps(
                {k: plan[k] for k in ("campaign_id", "route_id", "plan_sha256", "git_head", "seeds")}
                | {"cells": len(plan["cells"])},
                indent=2,
            )
        )
    elif arguments.step == "compare":
        if arguments.against is None:
            raise SystemExit("compare requires --against")
        report = compare(run_root, arguments.against.resolve())
        print(json.dumps({k: v for k, v in report.items() if k != "per_world"}, indent=2))
        for slug, row in sorted(report["per_world"].items()):
            print(f"{slug:26s} regret delta {row['regret']:8.2f}  counters {row['counters']:+.2f}  quoted {row['quoted']:+.2f}")
    elif arguments.step == "execute":
        summary = execute(run_root)
        print(
            json.dumps(
                {
                    k: summary[k]
                    for k in (
                        "completed",
                        "failed",
                        "not_run",
                        "cost_usd",
                        "mean_regret_usd",
                        "mean_regret_usd_95_world_bootstrap",
                        "mean_advantage_over_myopic_usd",
                        "mean_advantage_over_myopic_usd_95_world_bootstrap",
                        "counters",
                        "inquiries",
                        "switches",
                    )
                },
                indent=2,
            )
        )
    else:
        report = replay(run_root)
        print(
            json.dumps(
                {
                    label: (cell if isinstance(cell, str) else cell["receipt_sha256_matches_result"])
                    for label, cell in report["cells"].items()
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
