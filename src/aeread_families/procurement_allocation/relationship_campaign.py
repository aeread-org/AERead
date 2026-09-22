"""Live passes over the repeated-sourcing worlds, and their publication.

One campaign identity is one frozen plan: a route, a seed list, the worlds,
their per-seed episode cases, every ceiling that can end the run, and the
digests of the family sources that decide what a cell measures. ``prepare``
writes it before anything is spent; ``execute`` runs one cell per world and
seed, sequentially, records every cell as a verified receipt or a typed
failure, never reruns a recorded cell, and halts on consecutive operational
failures; ``replay`` re-audits every receipt from disk without a provider;
``compare`` pairs two runs on identical worlds and seeds; ``publish`` seals a
kernel-standard evidence bundle with the trajectory grain.

A seed binds the inference seed and the world's ``delivery_seed``, and, where
the world verifies noisily, its ``sample_noise`` seed, so it reaches the
evidence the buyer reads. Where a world verifies perfectly the seeds are
repeats on a deterministic route (P-D-01); the independent unit is the world
throughout and every interval resamples worlds.

The CLI is ``tools/run_procurement_relationship_pilot.py``; the tool imports
this module and adds nothing.
"""

from __future__ import annotations

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
from typing import Any, Callable, Mapping, Sequence

from aeread.shared_runner.model_call.harness import MinimalChatHarness
from aeread.shared_runner.run.publication import (
    assert_public_payload,
    atomic_publish,
    jsonl,
    receipt_projection,
    sanitized_trajectory_jsonl,
    sanitized_trajectory_rows,
    seal_publication_manifest,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.evaluation import audit_family_receipt
from aeread.shared_runner.task.execution import (
    EvidenceStore,
    OpenRouterChatClient,
    TokenPricing,
    execute_plan_cell,
)
from aeread_families.procurement_grounding import OpenRouterRoute

from .relationship_case_matrix import CASE_PATHS
from .runner import (
    RELATIONSHIP_PROMPT,
    build_openrouter_setup,
    finalize_procurement_allocation_execution,
    finalize_procurement_allocation_failure,
    load_case,
    replay_procurement_allocation_receipt,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_ROOT = REPOSITORY_ROOT / "evidence" / "procurement_allocation"
PROMPT_ID = "procurement_relationship_prompt_v1"
DEFAULT_SEEDS = (73101,)
BOOTSTRAP_SEED = 20260921
BOOTSTRAP_RESAMPLES = 10_000
PUBLICATION_SCHEMA = "aeread.procurement_relationship_pilot_publication/0.1"

#: Routes a plan may freeze. Prices are the ones the sealed campaigns
#: reviewed; the price caps refuse a repriced endpoint rather than pay it.
#: Both are chat routes through the kernel's OpenRouter client, so a paired
#: contrast between them changes the route and nothing else. Jev
#: (`typesafe/jev-1.13`) is not listed: it is a finite-choice decisions
#: endpoint without seed, temperature or reasoning, and putting it in this
#: seat needs a menu adapter, which is a different interface.
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

CONTRACT: dict[str, Any] = {
    "temperature": 0.0,
    "max_output_tokens": 1800,
    "timeout_seconds": 180.0,
    "max_cost_usd_per_trajectory": 0.60,
    "max_cost_usd_total": 4.00,
    # Retries cover only zero-cost provider conditions (a 429 or a 5xx that
    # billed nothing); a model's own malformed action is never retried.
    "max_action_attempts": 3,
    "retryable_conditions": ["rate_limit", "provider_5xx"],
    "retry_backoff": "exponential_jitter_v1",
    "retry_base_seconds": 5.0,
    "retry_after_max_seconds": 60.0,
    # After this many failed cells in a row the run halts, the untouched
    # cells are typed not_attempted and the process exits non-zero (P-T-07).
    "max_consecutive_operational_failures": 3,
    "concurrency": 1,
    "prompt_id": PROMPT_ID,
    "prompt_sha256": hashlib.sha256(RELATIONSHIP_PROMPT.encode("utf-8")).hexdigest(),
    "cluster_level": "economic_world",
    "bootstrap": {"seed": BOOTSTRAP_SEED, "resamples": BOOTSTRAP_RESAMPLES, "unit": "world"},
}

#: The family sources whose bytes decide what a cell measures. A plan pins
#: them and execute refuses to run under any others.
FAMILY_SOURCES = (
    "src/aeread_families/procurement_allocation/environment.py",
    "src/aeread_families/procurement_allocation/relationship.py",
    "src/aeread_families/procurement_allocation/relationship_case_matrix.py",
    "src/aeread_families/procurement_allocation/headroom_screen.py",
    "src/aeread_families/procurement_allocation/runner.py",
)
#: Recorded but not enforced, so a fix to reporting does not lock earlier
#: runs out of replay (the DC-T-06 shape).
TOOL_SOURCES = (
    "src/aeread_families/procurement_allocation/relationship_campaign.py",
    "tools/run_procurement_relationship_pilot.py",
)

#: Fields of a cell row that leave the run directory. ``error`` never does:
#: a provider's message can carry account identifiers.
PUBLISHABLE_ROW_FIELDS = (
    "slug",
    "seed",
    "world_case_id",
    "case_id",
    "case_content_sha256",
    "status",
    "reason",
    "decision",
    "termination_reason",
    "failure_code",
    "feasible",
    "feasible_award",
    "periods",
    "periods_awarded",
    "period_decisions",
    "period_margins",
    "switches",
    "realized_on_time_rate",
    "contribution_margin_usd",
    "upper_bound_usd",
    "myopic_reference_usd",
    "loyal_reference_usd",
    "shopping_reference_usd",
    "regret_to_upper_bound_usd",
    "advantage_over_myopic_usd",
    "violations",
    "information_cost_usd",
    "action_count",
    "action_counts",
    "counters",
    "inquiries",
    "suppliers_quoted",
    "suppliers_quoted_count",
    "provider_call_count",
    "finish_reasons",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "cost_usd",
    "resolved_models",
    "receipt_sha256",
    "receipt_status",
    "inclusion_status",
    "elapsed_seconds",
    "error_type",
    "failure_receipt_sha256",
)
#: Fields of a period record that leave the run directory: world data and
#: the buyer's own numbers, never text.
PUBLISHABLE_PERIOD_FIELDS = (
    "period",
    "decision",
    "feasible",
    "violations",
    "awarded",
    "awarded_supplier_ids",
    "quoted_supplier_ids",
    "delivery",
    "realized_completed_kits",
    "contribution_margin_usd",
    "raw_contribution_margin_usd",
    "completed_kits",
    "cash_spend_usd",
    "information_cost_usd",
    "expected_recovery_usd",
    "total_cost_usd",
    "elapsed_days",
    "actions_used",
    "termination_reason",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def source_hashes() -> dict[str, str]:
    return {
        name: _sha256(REPOSITORY_ROOT / name)
        for name in (*FAMILY_SOURCES, *TOOL_SOURCES)
        if (REPOSITORY_ROOT / name).exists()
    }


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


def route_record(route: OpenRouterRoute) -> dict[str, Any]:
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


def route_from_record(record: Mapping[str, Any]) -> OpenRouterRoute:
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


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def episode_case(world: Mapping[str, Any], seed: int) -> dict[str, Any]:
    """The world re-sealed with this seed's draws, its economics untouched."""
    if isinstance(seed, bool) or not isinstance(seed, int) or seed <= 0:
        raise ValueError("seed must be a positive integer")
    result = copy.deepcopy(dict(world))
    result["case_id"] = f"{world['case_id']}.delivery_{seed}"
    result["payload"]["interaction"]["periods"]["delivery_seed"] = seed
    noise = result["payload"]["interaction"].get("sample_noise")
    if noise is not None:
        # Where the world verifies noisily the seed also drives the sample
        # draws, so it reaches the evidence the buyer reads from period one.
        noise["seed"] = seed
    result["content_sha256"] = "0" * 64
    result["content_sha256"] = case_content_sha256(CaseManifest.from_dict(result))
    return result


# --------------------------------------------------------------------------
# prepare
# --------------------------------------------------------------------------


def prepare(
    run_root: Path,
    *,
    campaign_id: str,
    seeds: Sequence[int],
    route_id: str = DEFAULT_ROUTE,
    case_paths: Sequence[Path] = CASE_PATHS,
) -> dict[str, Any]:
    plan_path = run_root / "plan.json"
    if plan_path.exists():
        raise ValueError(f"{plan_path} exists; a frozen plan is never rewritten")
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("seeds must be non-empty and distinct")
    if route_id not in ROUTES:
        raise ValueError(f"unknown route {route_id!r}; known: {sorted(ROUTES)}")
    worlds = []
    cells = []
    for path in case_paths:
        case = load_case(path)
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        worlds.append(
            {
                "slug": Path(path).stem,
                "case_id": case.case_id,
                "content_sha256": case.content_sha256,
                "path": str(Path(path).resolve().relative_to(REPOSITORY_ROOT)),
                "max_logical_actions": case.episode.max_logical_actions,
            }
        )
        for seed in seeds:
            derived = episode_case(raw, seed)
            relative = Path("cases") / f"{Path(path).stem}__seed_{seed}.json"
            write_json(run_root / relative, derived)
            cells.append(
                {
                    "slug": Path(path).stem,
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
        "route": route_record(ROUTES[route_id]),
        "worlds": worlds,
        "cells": cells,
        "sources": source_hashes(),
        "git_head": _git_head(),
        "prepared_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    plan["plan_sha256"] = _digest(plan)
    write_json(plan_path, plan)
    return plan


def read_plan(run_root: Path, *, enforce_sources: bool = True) -> dict[str, Any]:
    plan = json.loads((run_root / "plan.json").read_text(encoding="utf-8"))
    declared = plan["plan_sha256"]
    if _digest({key: value for key, value in plan.items() if key != "plan_sha256"}) != declared:
        raise ValueError("plan.json does not digest to its own plan_sha256")
    if enforce_sources:
        current = source_hashes()
        drifted = sorted(
            name for name, digest in plan["sources"].items() if current.get(name) != digest
        )
        family_drift = [name for name in drifted if name in FAMILY_SOURCES]
        if family_drift:
            raise ValueError(f"family sources changed since the plan was frozen: {family_drift}")
        if drifted:
            print(
                f"note: tool bytes differ from the frozen plan ({drifted}); family sources unchanged",
                file=sys.stderr,
            )
    for row in plan["worlds"]:
        case = load_case(REPOSITORY_ROOT / row["path"])
        if case.content_sha256 != row["content_sha256"]:
            raise ValueError(f"world {row['case_id']} changed since the plan was frozen")
    for cell in plan["cells"]:
        case = load_case(run_root / cell["path"])
        if case.content_sha256 != cell["content_sha256"]:
            raise ValueError(f"episode case {cell['case_id']} changed since the plan was frozen")
    return plan


# --------------------------------------------------------------------------
# execute
# --------------------------------------------------------------------------


def setup_for(plan: Mapping[str, Any], cell: Mapping[str, Any], run_root: Path):
    return build_openrouter_setup(
        route_from_record(plan["route"]),
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
        retry_backoff=plan.get("retry_backoff"),
        retry_base_seconds=float(plan.get("retry_base_seconds", 2.0)),
        retry_after_max_seconds=float(plan.get("retry_after_max_seconds", 60.0)),
    )


def cell_root(run_root: Path, cell: Mapping[str, Any]) -> Path:
    return run_root / "cells" / cell["slug"] / f"seed_{cell['seed']}"


def live_client() -> tuple[OpenRouterChatClient, Any]:
    """The kernel's OpenRouter adapter over an SDK client the cell can close."""
    from openai import AsyncOpenAI

    sdk_client = AsyncOpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
        max_retries=0,
    )
    return OpenRouterChatClient(sdk_client=sdk_client), sdk_client


def public_trace(execution: Any) -> list[dict[str, Any]]:
    """The buyer's actions as sent, read back from each attempt's canonical response.

    Structured fields only: the action, the supplier and offer it names, a
    counter's numbers and an award's lines. A defer's reason and a message
    are model text and stay in the run directory.
    """
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
            for key in ("supplier_id", "offer_id", "proposal", "award_lines", "fields"):
                value = payload.get(key)
                if value not in (None, [], {}):
                    row[key] = value
        trace.append(row)
    return trace


async def run_cell(
    plan: Mapping[str, Any], cell: Mapping[str, Any], run_root: Path
) -> dict[str, Any]:
    client, sdk_client = live_client()
    try:
        return await run_cell_with(plan, cell, run_root, client)
    finally:
        await sdk_client.close()


async def run_cell_with(
    plan: Mapping[str, Any], cell: Mapping[str, Any], run_root: Path, client: Any
) -> dict[str, Any]:
    setup = setup_for(plan, cell, run_root)
    plan_cell = setup.plan.cells[0]
    evidence_root = cell_root(run_root, cell) / "evidence"
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
        trace = public_trace(execution)
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
            "shopping_reference_usd": outcome.get("shopping_reference_usd"),
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
            failure_sha256 = f"unrecorded: {type(inner).__name__}"
        return {
            **identity,
            "status": "failed",
            "error_type": type(error).__name__,
            "error": str(error)[:2000],
            "failure_receipt_sha256": failure_sha256,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }


def execute(
    run_root: Path,
    *,
    runner: Callable[[Mapping[str, Any], Mapping[str, Any], Path], dict[str, Any]] | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run every unrecorded cell in plan order; halt on the declared limits."""
    plan = read_plan(run_root)
    if runner is None:
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise ValueError("OPENROUTER_API_KEY is not set")
        runner = lambda plan_, cell_, root_: asyncio.run(run_cell(plan_, cell_, root_))  # noqa: E731
    rows: list[dict[str, Any]] = []
    spent = 0.0
    consecutive_failures = 0
    stop_after = int(plan.get("max_consecutive_operational_failures", 0)) or None
    halted: str | None = None
    for cell in plan["cells"]:
        result_path = cell_root(run_root, cell) / "result.json"
        if result_path.exists():
            existing = json.loads(result_path.read_text(encoding="utf-8"))
            rows.append(existing)
            spent += float(existing.get("cost_usd", 0.0))
            consecutive_failures = consecutive_failures + 1 if existing.get("status") == "failed" else 0
            continue  # never rerun a recorded cell, completed or failed
        if halted is None and spent >= float(plan["max_cost_usd_total"]):
            halted = f"run ceiling {plan['max_cost_usd_total']} reached at {spent:.4f}"
        if halted is None and stop_after is not None and consecutive_failures >= stop_after:
            halted = f"{consecutive_failures} consecutive operational failures (limit {stop_after})"
        if halted is not None:
            rows.append(
                {
                    "slug": cell["slug"],
                    "seed": int(cell["seed"]),
                    "case_id": cell["case_id"],
                    "status": "not_attempted",
                    "reason": halted,
                }
            )
            continue
        result = runner(plan, cell, run_root)
        write_json(result_path, result)
        rows.append(result)
        spent += float(result.get("cost_usd", 0.0))
        consecutive_failures = consecutive_failures + 1 if result.get("status") == "failed" else 0
        label = f"{cell['slug']}/seed_{cell['seed']}"
        log(
            f"{label:38s} {result['status']:9s} "
            + (
                f"margin={result['contribution_margin_usd']:.2f} bound={result['upper_bound_usd']:.2f} "
                f"regret={result['regret_to_upper_bound_usd']:.2f} awarded={result['periods_awarded']}/{result['periods']} "
                f"counters={result['counters']} quoted={result['suppliers_quoted_count']} cost=${result['cost_usd']:.4f}"
                if result["status"] == "completed"
                else f"{result.get('error_type')}: {result.get('error', '')[:120]}"
            )
        )
    summary = summarize(plan, rows)
    summary["halted"] = halted
    write_json(run_root / "results.json", summary)
    return summary


# --------------------------------------------------------------------------
# summary
# --------------------------------------------------------------------------


def bootstrap_interval(cluster_means: Sequence[float]) -> list[float] | None:
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
        "shopping_reference_usd": completed[0].get("shopping_reference_usd") if completed else None,
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
        "suppliers_quoted_by_seed": {str(row["seed"]): row["suppliers_quoted"] for row in completed},
        "distinct_routines": len(
            {
                json.dumps([r["action"] + ":" + str(r.get("supplier_id", "")) for r in row["action_trace"]])
                for row in completed
                if "action_trace" in row
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
        "not_attempted": sum(1 for row in rows if row.get("status") == "not_attempted"),
        "cost_usd": round(sum(float(row.get("cost_usd", 0.0)) for row in rows), 8),
        "input_tokens": sum(int(row.get("input_tokens", 0)) for row in rows),
        "output_tokens": sum(int(row.get("output_tokens", 0)) for row in rows),
        "worlds_measured": len(measured),
        "cluster_level": plan["cluster_level"],
        "mean_regret_usd": round(statistics.mean(regret_means), 8) if regret_means else None,
        "mean_regret_usd_95_world_bootstrap": bootstrap_interval(regret_means),
        "mean_advantage_over_myopic_usd": (
            round(statistics.mean(advantage_means), 8) if advantage_means else None
        ),
        "mean_advantage_over_myopic_usd_95_world_bootstrap": bootstrap_interval(advantage_means),
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
        "rows": [{key: row[key] for key in PUBLISHABLE_ROW_FIELDS if key in row} for row in rows],
    }


# --------------------------------------------------------------------------
# replay
# --------------------------------------------------------------------------


def receipt_paths(run_root: Path, cell: Mapping[str, Any]) -> list[Path]:
    return sorted(cell_root(run_root, cell).glob("evidence/**/evaluation_receipt.json"))


def replay(
    run_root: Path,
    *,
    setup_builder: Callable[[Mapping[str, Any], Mapping[str, Any], Path], Any] = setup_for,
) -> dict[str, Any]:
    plan = read_plan(run_root)
    report: dict[str, Any] = {"campaign_id": plan["campaign_id"], "cells": {}}
    for cell in plan["cells"]:
        label = f"{cell['slug']}/seed_{cell['seed']}"
        result_path = cell_root(run_root, cell) / "result.json"
        if not result_path.exists():
            report["cells"][label] = "no result recorded"
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("status") != "completed":
            report["cells"][label] = f"{result.get('status')}: not replayable"
            continue
        paths = receipt_paths(run_root, cell)
        if not paths:
            report["cells"][label] = "receipt missing"
            continue
        setup = setup_builder(plan, cell, run_root)
        audit = audit_family_receipt(setup=setup, receipt_path=paths[0])
        recorded = json.loads(paths[0].read_text(encoding="utf-8"))
        report["cells"][label] = {
            "receipt_sha256_matches_result": recorded.get("receipt_sha256") == result["receipt_sha256"],
            "audit": json.loads(canonical_json_bytes(audit)),
        }
    write_json(run_root / "replay.json", report)
    return report


# --------------------------------------------------------------------------
# compare
# --------------------------------------------------------------------------


def compare(run_root: Path, against: Path) -> dict[str, Any]:
    """Paired contrast of this run against another on identical worlds and seeds.

    The difference is taken per world and seed, averaged within the world,
    and the interval resamples worlds. Nothing here ranks.
    """
    left = json.loads((run_root / "results.json").read_text(encoding="utf-8"))
    right = json.loads((against / "results.json").read_text(encoding="utf-8"))
    if left["seeds"] != right["seeds"]:
        raise ValueError("runs were made on different seeds; no pairing")
    left_rows = {(row["slug"], row["seed"]): row for row in left["rows"] if row.get("status") == "completed"}
    right_rows = {(row["slug"], row["seed"]): row for row in right["rows"] if row.get("status") == "completed"}
    keys = sorted(set(left_rows) & set(right_rows))
    if not keys:
        raise ValueError("no completed cell is shared by both runs")
    for key in keys:
        if left_rows[key]["upper_bound_usd"] != right_rows[key]["upper_bound_usd"]:
            raise ValueError(f"bound differs on {key}; the runs are not on the same world")
    per_world: dict[str, dict[str, list[float]]] = {}
    for slug, seed in keys:
        entry = per_world.setdefault(slug, {"regret": [], "margin": [], "counters": [], "quoted": []})
        left_row, right_row = left_rows[(slug, seed)], right_rows[(slug, seed)]
        entry["regret"].append(
            float(left_row["regret_to_upper_bound_usd"]) - float(right_row["regret_to_upper_bound_usd"])
        )
        entry["margin"].append(
            float(left_row["contribution_margin_usd"]) - float(right_row["contribution_margin_usd"])
        )
        entry["counters"].append(float(left_row["counters"]) - float(right_row["counters"]))
        entry["quoted"].append(
            float(len(left_row["suppliers_quoted"])) - float(len(right_row["suppliers_quoted"]))
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
        "mean_regret_delta_usd_95_world_bootstrap": bootstrap_interval(regret_deltas),
        "worlds_left_lower_regret": sum(1 for value in regret_deltas if value < 0),
        "worlds_right_lower_regret": sum(1 for value in regret_deltas if value > 0),
        "per_world": worlds,
        "claim_scope": "paired descriptive contrast on curated worlds; no ranking",
    }
    write_json(run_root / f"comparison_vs_{right['campaign_id']}.json", report)
    return report


# --------------------------------------------------------------------------
# publish
# --------------------------------------------------------------------------


def _readme(plan: Mapping[str, Any], summary: Mapping[str, Any], comparisons: Sequence[Mapping[str, Any]]) -> str:
    route = plan["route"]
    interval = summary.get("mean_regret_usd_95_world_bootstrap") or [None, None]
    advantage = summary.get("mean_advantage_over_myopic_usd_95_world_bootstrap") or [None, None]
    lines = [
        f"# {plan['campaign_id']}",
        "",
        "Descriptive single-route run of the procurement repeated-sourcing worlds "
        "(`interaction.periods`, design §4): one live buyer route on the committed "
        "worlds, every seed re-sealed into the world's delivery draws, scored against "
        "the exact four-period bound with the myopic, loyal and shopping references "
        "beside it. Claim status: `development_qualification`. No winner and no model "
        "ranking may be read from this bundle.",
        "",
        f"- Route: `{route['model']}` (`{route['revision']}` via {route['route_provider']}), "
        f"reasoning effort {route['reasoning_effort']}, temperature {plan['temperature']}",
        f"- Seeds: {', '.join(str(seed) for seed in plan['seeds'])}; worlds: {len(plan['worlds'])}; "
        f"cells: {summary['cells']}, completed {summary['completed']}, failed {summary['failed']}, "
        f"not attempted {summary['not_attempted']}",
        f"- Cost: ${summary['cost_usd']:.4f} reported; {summary['input_tokens']} input and "
        f"{summary['output_tokens']} output tokens",
        f"- Mean regret to the bound over worlds: {summary['mean_regret_usd']} "
        f"(95% world-clustered bootstrap {interval[0]} to {interval[1]})",
        f"- Mean margin against the myopic reference: {summary['mean_advantage_over_myopic_usd']} "
        f"(95% {advantage[0]} to {advantage[1]})",
        f"- Periods awarded: {summary['periods_awarded']} of {summary['periods']}; counters "
        f"{summary['counters']}; inquiries {summary['inquiries']}; switches {summary['switches']}",
        "",
        "Seeds reach the buyer only through delivery history from period two on; "
        "where the route is deterministic the seeds of a world are repeats, and the "
        "independent unit is the world (incident P-D-01). The six worlds are curated "
        "and were tuned against the admission screen; this is a development panel.",
        "",
    ]
    for comparison in comparisons:
        delta = comparison.get("mean_regret_delta_usd_95_world_bootstrap") or [None, None]
        lines.append(
            f"- Paired against `{comparison['right_campaign_id']}` (`{comparison['right_route']}`): "
            f"regret delta {comparison['mean_regret_delta_usd']} (95% {delta[0]} to {delta[1]}), "
            f"{comparison['paired_cells']} paired cells; descriptive, no ranking."
        )
    if comparisons:
        lines.append("")
    lines += [
        "Files: `reports/plan.json` (the frozen plan and source pins), "
        "`reports/summary.json` (every cell row and the per-world summary), "
        "`tables/cells.jsonl` (one row per cell), `tables/periods.jsonl` (one row per "
        "cell and period), `receipts/receipts.jsonl` (the receipt projection of every "
        "sealed cell), `trajectories/sanitized.jsonl` (the kernel trajectory grain), "
        "and `reports/replay.json` (the re-audit from disk). Raw prompts, observations, "
        "provider text and failure messages stay in the ignored run root.",
        "",
    ]
    return "\n".join(lines)


def publish(
    run_root: Path,
    *,
    publication_root: Path | None = None,
    setup_builder: Callable[[Mapping[str, Any], Mapping[str, Any], Path], Any] = setup_for,
) -> dict[str, Any]:
    """Seal a completed run as a kernel-standard evidence bundle.

    Every completed cell is re-audited from its receipt before anything is
    written; a failed cell is published as its typed failure receipt when one
    was sealed. Bytes are written once and never overwritten.
    """
    plan = read_plan(run_root, enforce_sources=False)
    summary = json.loads((run_root / "results.json").read_text(encoding="utf-8"))
    if summary.get("campaign_id") != plan["campaign_id"]:
        raise ValueError("results.json belongs to a different campaign")
    bundle = publication_root or (EVIDENCE_ROOT / plan["campaign_id"])
    if (bundle / "publication_manifest.json").exists():
        raise ValueError(f"bundle already sealed: {bundle}")

    projections: list[dict[str, Any]] = []
    period_rows: list[dict[str, Any]] = []
    trajectory_rows: list[dict[str, Any]] = []
    receipt_digests: list[str] = []
    replay_report = replay(run_root, setup_builder=setup_builder)
    for cell in plan["cells"]:
        label = f"{cell['slug']}/seed_{cell['seed']}"
        result_path = cell_root(run_root, cell) / "result.json"
        if not result_path.exists():
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        paths = receipt_paths(run_root, cell)
        if result.get("status") == "completed":
            verdict = replay_report["cells"].get(label)
            if not isinstance(verdict, Mapping) or not verdict["receipt_sha256_matches_result"]:
                raise ValueError(f"{label} did not replay to its recorded receipt")
            receipt = json.loads(paths[0].read_text(encoding="utf-8"))
            projections.append(receipt_projection(receipt, campaign_cell_key=label))
            receipt_digests.append(receipt["receipt_sha256"])
            evidence = EvidenceStore.audit_existing(paths[0].parent)
            trajectory_rows.extend(sanitized_trajectory_rows(evidence, receipt))
            for period in result.get("period_results", []):
                period_rows.append(
                    {
                        "slug": cell["slug"],
                        "seed": int(cell["seed"]),
                        "case_id": cell["case_id"],
                        **{key: period[key] for key in PUBLISHABLE_PERIOD_FIELDS if key in period},
                    }
                )
        elif result.get("status") == "failed" and paths:
            receipt = json.loads(paths[0].read_text(encoding="utf-8"))
            if receipt.get("receipt_sha256") == result.get("failure_receipt_sha256"):
                projections.append(receipt_projection(receipt, campaign_cell_key=label))
                receipt_digests.append(receipt["receipt_sha256"])
    trajectory_rows.sort(key=lambda row: (row["source_receipt_sha256"], row["step_index"]))

    comparisons = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(run_root.glob("comparison_vs_*.json"))
    ]
    published_summary = {key: value for key, value in summary.items() if key != "rows"}
    published_summary["rows"] = [
        {key: row[key] for key in PUBLISHABLE_ROW_FIELDS if key in row} for row in summary["rows"]
    ]
    published_summary["schema_version"] = PUBLICATION_SCHEMA

    files: dict[str, bytes] = {
        "README.md": _readme(plan, published_summary, comparisons).encode("utf-8"),
        "reports/plan.json": canonical_json_bytes(plan) + b"\n",
        "reports/summary.json": canonical_json_bytes(published_summary) + b"\n",
        "reports/replay.json": canonical_json_bytes(replay_report) + b"\n",
        "tables/cells.jsonl": jsonl(published_summary["rows"]),
        "tables/periods.jsonl": jsonl(period_rows),
        "receipts/receipts.jsonl": jsonl(projections),
        "trajectories/sanitized.jsonl": sanitized_trajectory_jsonl(trajectory_rows),
    }
    for index, comparison in enumerate(comparisons):
        files[f"reports/comparison_vs_{comparison['right_campaign_id']}.json"] = (
            canonical_json_bytes(comparison) + b"\n"
        )
    for name, payload in files.items():
        assert_public_payload(name, payload)
        atomic_publish(bundle / name, payload)
    manifest = seal_publication_manifest(
        bundle,
        publication_id=plan["campaign_id"],
        campaign_id=plan["campaign_id"],
        privacy_boundary={
            "included": (
                "frozen plan and source pins, per-cell and per-period numbers, receipt "
                "projections, the kernel trajectory grain, the replay audit"
            ),
            "excluded": (
                "prompts, observations, model messages and reasons, provider payloads, "
                "failure messages, account metadata; all stay in the ignored run root"
            ),
        },
        source_bindings={
            "plan_sha256": plan["plan_sha256"],
            "results_file_sha256": _sha256(run_root / "results.json"),
            "implementation_pins": plan["sources"],
            "exporter_sha256": _sha256(Path(__file__)),
            "source_receipt_sha256s": sorted(receipt_digests),
        },
        claim_status="development_qualification",
        winner_claim_allowed=False,
        inferential_model_ranking_allowed=False,
        cluster_level=plan["cluster_level"],
    )
    return manifest


def verify_bundle(bundle: Path) -> dict[str, Any]:
    """Recompute every digest a sealed bundle declares; the evidence-lane check."""
    manifest = json.loads((bundle / "publication_manifest.json").read_text(encoding="utf-8"))
    body = {key: value for key, value in manifest.items() if key not in ("manifest_sha256", "publication_sha256")}
    problems: list[str] = []
    if hashlib.sha256(canonical_json_bytes(body)).hexdigest() != manifest.get("manifest_sha256"):
        problems.append("manifest_sha256 does not match the manifest body")
    for relative, digest in manifest["artifacts"].items():
        path = bundle / relative
        if not path.is_file():
            problems.append(f"missing artifact: {relative}")
        elif _sha256(path) != digest:
            problems.append(f"artifact digest differs: {relative}")
        else:
            try:
                assert_public_payload(relative, path.read_bytes())
            except ValueError as error:
                problems.append(str(error))
    receipts = [
        json.loads(line)
        for line in (bundle / "receipts" / "receipts.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    declared = set(manifest["source_bindings"]["source_receipt_sha256s"])
    projected = {row["source_receipt_sha256"] for row in receipts}
    if declared != projected:
        problems.append("receipt projections do not match the manifest's source receipts")
    return {"bundle": str(bundle), "artifacts": len(manifest["artifacts"]), "receipts": len(receipts), "problems": problems}


__all__ = [
    "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED",
    "CONTRACT",
    "DEFAULT_ROUTE",
    "DEFAULT_SEEDS",
    "EVIDENCE_ROOT",
    "FAMILY_SOURCES",
    "PUBLISHABLE_PERIOD_FIELDS",
    "PUBLISHABLE_ROW_FIELDS",
    "ROUTES",
    "bootstrap_interval",
    "cell_root",
    "compare",
    "episode_case",
    "execute",
    "prepare",
    "public_trace",
    "publish",
    "read_plan",
    "receipt_paths",
    "replay",
    "route_from_record",
    "route_record",
    "run_cell",
    "run_cell_with",
    "setup_for",
    "source_hashes",
    "summarize",
    "verify_bundle",
]
