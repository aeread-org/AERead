"""Fixed-harness GLM qualification for procurement-allocation cases.

The harness is held constant as transport.  The reported construct is model
behavior in the procurement environment: evidence acquisition, supplier
selection, service feasibility, contribution margin, and regret.  Inference
seeds on one case are stochastic replicates, not independent procurement cases.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from aeread.shared_runner.task.execution import (
    OpenRouterChatClient,
    TokenPricing,
    execute_plan_cell,
)
from aeread.shared_runner.model_call.harness import MinimalChatHarness
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.procurement_grounding.bakeoff import (
    BakeoffCandidate,
    preflight_candidate,
)
from aeread_families.procurement_grounding.runner import OpenRouterRoute

from .case_matrix import CASE_VARIANCE_PATHS
from .runner import (
    PROMPT,
    build_openrouter_setup,
    finalize_procurement_allocation_execution,
    finalize_procurement_allocation_failure,
    load_case,
    replay_procurement_allocation_receipt,
)


CAMPAIGN_ID = "procurement_allocation_glm_morph_case_variance_v2"
PUBLICATION_ID = CAMPAIGN_ID


GLM_MORPH_CANDIDATE = BakeoffCandidate(
    candidate_id="glm53_flash_morph",
    route=OpenRouterRoute(
        profile_id="procurement_glm53_flash_morph_v1",
        model="z-ai/glm-5.3-flash",
        revision="z-ai/glm-5.3-flash-20260826",
        route_provider="Morph",
        quantization="fp8",
        pricing=TokenPricing(
            input_per_million=0.13,
            cached_input_per_million=0.02,
            output_per_million=0.45,
            pricing_id="openrouter_2026-09-02_glm53_flash_morph",
        ),
        max_prompt_price_per_million="0.13",
        max_completion_price_per_million="0.45",
        reasoning_effort="low",
    ),
    lane="standard",
    access_class="open_source",
    license_id="MIT",
    model_card_url="https://huggingface.co/zai-org/GLM-5.3-Flash",
)


def derive_inference_seeds(
    *, master_seed: int, count: int, campaign_id: str = CAMPAIGN_ID
) -> tuple[int, ...]:
    if master_seed < 0 or count < 1:
        raise ValueError("master_seed must be non-negative and count positive")
    seeds: list[int] = []
    counter = 0
    while len(seeds) < count:
        payload = f"{campaign_id}:{master_seed}:{counter}".encode()
        counter += 1
        candidate = (
            int.from_bytes(hashlib.sha256(payload).digest()[:4], "big") & 0x7FFF_FFFF
        )
        if candidate not in seeds:
            seeds.append(candidate)
    return tuple(seeds)


def conservative_cost_ceiling(
    *,
    case_count: int,
    seed_count: int,
    max_episode_input_tokens: int = 40_000,
    max_episode_output_tokens: int = 18_000,
    candidate: BakeoffCandidate = GLM_MORPH_CANDIDATE,
) -> float:
    if case_count < 1 or seed_count < 1:
        raise ValueError("case_count and seed_count must be positive")
    per_episode = candidate.route.pricing.cost(
        input_tokens=max_episode_input_tokens,
        cached_input_tokens=0,
        output_tokens=max_episode_output_tokens,
    )
    return per_episode * case_count * seed_count


def _case_records(case_paths: Sequence[Path | str]) -> tuple[dict[str, Any], ...]:
    if not case_paths:
        raise ValueError("case_paths cannot be empty")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for case_path in case_paths:
        path = Path(case_path).resolve()
        case = load_case(path)
        if case.case_id in seen:
            raise ValueError(f"duplicate case_id: {case.case_id}")
        seen.add(case.case_id)
        records.append(
            {
                "case_id": case.case_id,
                "content_sha256": case.content_sha256,
                "path": path,
            }
        )
    return tuple(records)


def planned_model_qualification(
    *,
    case_paths: Sequence[Path | str],
    inference_seeds: Sequence[int],
    max_parallel_cells: int = 2,
    campaign_id: str = CAMPAIGN_ID,
    abort_on_operational_failure: bool = False,
    candidate: BakeoffCandidate = GLM_MORPH_CANDIDATE,
    prompt: str = PROMPT,
    prompt_id: str = "procurement_allocation_prompt_v1",
    treatment_id: str = "unscaffolded_control",
) -> dict[str, Any]:
    if not inference_seeds:
        raise ValueError("inference_seeds cannot be empty")
    if len(set(inference_seeds)) != len(inference_seeds):
        raise ValueError("inference_seeds must be unique")
    if any(seed < 0 for seed in inference_seeds):
        raise ValueError("inference_seeds must be non-negative")
    if max_parallel_cells < 1:
        raise ValueError("max_parallel_cells must be positive")
    if not prompt.strip() or not prompt_id.strip() or not treatment_id.strip():
        raise ValueError("prompt, prompt_id, and treatment_id cannot be empty")
    cases = _case_records(case_paths)
    route = candidate.route
    plan = {
        "schema_version": "aeread.procurement_allocation_model_plan/0.3",
        "campaign_id": campaign_id,
        "cases": [
            {
                "case_id": record["case_id"],
                "content_sha256": record["content_sha256"],
            }
            for record in cases
        ],
        "independent_case_count": len(cases),
        "inference_seeds": list(inference_seeds),
        "planned_trajectory_count": len(cases) * len(inference_seeds),
        "model": route.model,
        "revision": route.revision,
        "provider": route.route_provider,
        "quantization": route.quantization,
        "pricing_id": route.pricing.pricing_id,
        "prompt": {
            "prompt_id": prompt_id,
            "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "treatment_id": treatment_id,
        },
        "harness": "minimal_chat/1.0 (fixed transport; not an estimand)",
        "max_parallel_cells": max_parallel_cells,
        "abort_on_operational_failure": abort_on_operational_failure,
        "retry_policy": "one sealed attempt per trajectory; SDK retries disabled",
        "resume_policy": "run only trajectories without a result row",
        "response_cache": "disabled",
        "prompt_cache": "automatic provider behavior; observed and reported",
        "max_actions_per_trajectory": 10,
        "max_output_tokens_per_action": 1800,
        "max_cost_usd_per_trajectory": 0.03,
        "conservative_cost_ceiling_usd": conservative_cost_ceiling(
            case_count=len(cases),
            seed_count=len(inference_seeds),
            candidate=candidate,
        ),
        "primary_outcomes": [
            "feasible",
            "completed_kits",
            "contribution_margin_usd",
            "regret_to_upper_bound_usd",
            "violations",
        ],
        "claim_scope": (
            "model qualification on declared cases; inference seeds within a case "
            "measure stochastic reliability and are not independent cases"
        ),
    }
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return plan


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    payload = canonical_json_bytes(value) + b"\n"
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _validate_operational_run_root(run_root: Path) -> None:
    """Keep live transcripts and receipts out of the tracked evidence tree."""

    parts = run_root.resolve().parts
    if "runs" not in parts or {"output", "outputs", "evidence"}.intersection(parts):
        raise ValueError(
            "--run-root must be under the ignored runs/ hierarchy and outside "
            "output/, outputs/, and evidence/"
        )


def _validate_publication_root(publication_root: Path) -> None:
    resolved = publication_root.resolve()
    parts = resolved.parts
    if resolved.parent.name != "evidence" or {
        "output",
        "outputs",
        "runs",
        "docs",
    }.intersection(parts):
        raise ValueError(
            "--publication-root must be one direct evidence/<publication_id> bundle"
        )


def _write_once_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"refusing to replace different evidence: {path}")
        return
    _atomic_write_json(path, value)


_PUBLISHABLE_ROW_FIELDS = (
    "case_id",
    "case_content_sha256",
    "inference_seed",
    "status",
    "decision",
    "termination_reason",
    "feasible",
    "completed_kits",
    "contribution_margin_usd",
    "upper_bound_usd",
    "regret_to_upper_bound_usd",
    "violations",
    "elapsed_environment_days",
    "action_count",
    "action_trace",
    "elapsed_seconds",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "cost_usd",
    "resolved_models",
    "receipt_sha256",
    "receipt_replayed",
    "replay_level",
    "result_sha256",
    "failure_type",
    "failure_condition",
    "failure_status_code",
    "failure_receipt_sha256",
)


def _repo_relative_run_label(run_root: Path) -> str:
    parts = run_root.resolve().parts
    runs_index = len(parts) - 1 - tuple(reversed(parts)).index("runs")
    return Path(*parts[runs_index:]).as_posix()


def _write_once_text(path: Path, value: str) -> None:
    payload = value.encode("utf-8")
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"refusing to replace different evidence: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def publish_model_qualification(
    *,
    run_root: Path,
    publication_root: Path,
    supplemental_reports: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Publish a sanitized, digest-bound projection of one completed raw run."""

    _validate_operational_run_root(run_root)
    _validate_publication_root(publication_root)
    raw_summary_path = run_root / "summary.json"
    raw_bytes = raw_summary_path.read_bytes()
    raw = json.loads(raw_bytes)
    if not isinstance(raw, dict):
        raise ValueError("raw qualification summary must be an object")

    recorded_artifact_sha = raw.get("artifact_sha256")
    raw_payload = {key: value for key, value in raw.items() if key != "artifact_sha256"}
    expected_artifact_sha = hashlib.sha256(
        canonical_json_bytes(raw_payload)
    ).hexdigest()
    if recorded_artifact_sha != expected_artifact_sha:
        raise ValueError("raw qualification artifact digest mismatch")

    rows = raw.get("rows")
    if not isinstance(rows, list):
        raise ValueError("raw qualification rows must be an array")
    publishable_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("raw qualification row must be an object")
        recorded_result_sha = row.get("result_sha256")
        result_payload = {
            key: value for key, value in row.items() if key != "result_sha256"
        }
        expected_result_sha = hashlib.sha256(
            canonical_json_bytes(result_payload)
        ).hexdigest()
        if recorded_result_sha != expected_result_sha:
            raise ValueError("raw qualification result digest mismatch")
        publishable_rows.append(
            {key: row[key] for key in _PUBLISHABLE_ROW_FIELDS if key in row}
        )

    preflight = raw.get("preflight")
    publishable_preflight = None
    if isinstance(preflight, Mapping):
        publishable_preflight = {
            key: preflight[key]
            for key in (
                "candidate_id",
                "model",
                "revision",
                "route_provider",
                "quantization",
                "eligible_endpoint_count",
                "prompt_per_million_range",
                "completion_per_million_range",
                "supported_parameters_verified",
                "source",
            )
            if key in preflight
        }

    plan = raw.get("plan")
    if not isinstance(plan, Mapping):
        raise ValueError("raw qualification plan must be an object")
    review: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_model_review/0.1",
        "campaign_id": plan.get("campaign_id"),
        "source": {
            "raw_summary_path": (f"{_repo_relative_run_label(run_root)}/summary.json"),
            "raw_summary_file_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "raw_artifact_sha256": recorded_artifact_sha,
            "plan_sha256": plan.get("plan_sha256"),
        },
        "publisher_implementation": {
            "module": "aeread_families.procurement_allocation.model_campaign",
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "privacy_boundary": {
            "included": (
                "case/model identities, parsed action trace, outcomes, typed failures, "
                "usage, cost, and receipt/result digests"
            ),
            "excluded": (
                "provider request/response payloads, full prompts, event logs, artifact "
                "stores, locks, and account metadata"
            ),
        },
        "plan": dict(plan),
        "preflight": publishable_preflight,
        "summary": raw.get("summary"),
        "rows": publishable_rows,
    }
    review["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(review)).hexdigest()
    review_path = publication_root / "reports" / "qualification.json"
    _write_once_json(review_path, review)

    review_file_sha = hashlib.sha256(review_path.read_bytes()).hexdigest()
    supplemental_artifacts: dict[str, dict[str, str]] = {}
    for relative_name, report in (supplemental_reports or {}).items():
        relative_path = Path(relative_name)
        if (
            relative_path.is_absolute()
            or len(relative_path.parts) != 2
            or relative_path.parts[0] != "reports"
            or relative_path.suffix != ".json"
            or ".." in relative_path.parts
        ):
            raise ValueError("supplemental report paths must be reports/<name>.json")
        report_path = publication_root / relative_path
        _write_once_json(report_path, report)
        supplemental_artifacts[relative_path.as_posix()] = {
            "path": relative_path.as_posix(),
            "sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        }
    fact_manifest: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_model_manifest/0.1",
        "campaign_id": plan.get("campaign_id"),
        "artifacts": {
            "qualification_summary": {
                "path": "reports/qualification.json",
                "sha256": review_file_sha,
            },
            **supplemental_artifacts,
        },
        "source_bindings": review["source"],
        "publisher_implementation": review["publisher_implementation"],
        "publication_scope": "sanitized PR-review evidence; not raw replay storage",
    }
    fact_manifest["manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes(fact_manifest)
    ).hexdigest()
    fact_path = publication_root / "tables" / "fact_manifest.json"
    _write_once_json(fact_path, fact_manifest)

    publication_manifest: dict[str, Any] = {
        "schema_version": "aeread.publication_manifest/0.1",
        "publication_id": publication_root.name,
        "campaign_id": plan.get("campaign_id"),
        "artifacts": {
            "reports/qualification.json": review_file_sha,
            **{
                name: binding["sha256"]
                for name, binding in supplemental_artifacts.items()
            },
            "tables/fact_manifest.json": hashlib.sha256(
                fact_path.read_bytes()
            ).hexdigest(),
        },
        "source_bindings": review["source"],
        "privacy_boundary": review["privacy_boundary"],
    }
    publication_manifest["manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes(publication_manifest)
    ).hexdigest()
    _write_once_json(
        publication_root / "publication_manifest.json", publication_manifest
    )
    _write_once_text(
        publication_root / "README.md",
        f"# {plan.get('campaign_id')}\n\n"
        "Sanitized, digest-bound review evidence for the declared procurement "
        "allocation panel. "
        "Raw prompts, provider payloads, "
        "event logs, and replay stores remain under the ignored `runs/` tree.\n",
    )
    return {
        "review": review,
        "fact_manifest": fact_manifest,
        "manifest": publication_manifest,
    }


def _failure_summary(error: BaseException) -> dict[str, Any]:
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    condition = next(
        (
            value
            for item in chain
            if isinstance((value := getattr(item, "condition", None)), str)
        ),
        None,
    )
    status_code = next(
        (
            value
            for item in chain
            if isinstance((value := getattr(item, "status_code", None)), int)
        ),
        None,
    )
    messages = " ".join(str(item).lower() for item in chain)
    if condition is None and (
        status_code == 429 or "error code: 429" in messages or "rate-limit" in messages
    ):
        condition = "rate_limit"
    elif condition is None and status_code is not None and status_code >= 500:
        condition = "provider_5xx"
    return {
        "failure_type": type(error).__name__,
        "failure_condition": condition or "model_qualification_failure",
        "failure_status_code": status_code,
    }


def _safe_case_directory(case_id: str, content_sha256: str) -> str:
    readable = "".join(
        character if character.isalnum() else "_" for character in case_id
    )
    return f"{readable}_{content_sha256[:12]}"


def _result_path(
    run_root: Path, *, case_id: str, content_sha256: str, seed: int
) -> Path:
    case_directory = _safe_case_directory(case_id, content_sha256)
    return run_root / "results" / case_directory / f"seed_{seed}.json"


def _read_result(
    path: Path,
    *,
    case_id: str,
    content_sha256: str,
    seed: int,
) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"result row is not an object: {path}")
    recorded_sha = value.get("result_sha256")
    payload = {key: item for key, item in value.items() if key != "result_sha256"}
    expected_sha = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    if recorded_sha != expected_sha:
        raise ValueError(f"result digest mismatch: {path}")
    identity = (
        value.get("case_id"),
        value.get("case_content_sha256"),
        value.get("inference_seed"),
    )
    if identity != (case_id, content_sha256, seed):
        raise ValueError(f"result identity mismatch: {path}")
    return value


def _public_action_trace(execution: Any) -> list[dict[str, Any]]:
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
            "action": payload.get("action") if payload is not None else "unparseable",
        }
        if payload is not None:
            for key in ("supplier_id", "offer_id", "proposal", "award_lines"):
                value = payload.get(key)
                if value not in (None, [], {}):
                    row[key] = value
        trace.append(row)
    return trace


def summarize_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    planned_trajectory_count: int,
    independent_case_count: int,
) -> dict[str, Any]:
    completed = [row for row in rows if row.get("status") == "completed"]
    feasible = [row for row in completed if row.get("feasible") is True]
    violation_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    supplier_contacts: Counter[str] = Counter()
    for row in completed:
        violation_counts.update(str(item) for item in row["violations"])
        for action in row["action_trace"]:
            action_counts[str(action["action"])] += 1
            supplier_id = action.get("supplier_id")
            if isinstance(supplier_id, str):
                supplier_contacts[supplier_id] += 1

    per_case: dict[str, Any] = {}
    for case_id in sorted({str(row["case_id"]) for row in rows}):
        case_rows = [row for row in rows if row["case_id"] == case_id]
        case_completed = [row for row in case_rows if row.get("status") == "completed"]
        case_feasible = [row for row in case_completed if row.get("feasible") is True]
        case_violations = Counter(
            str(violation)
            for row in case_completed
            for violation in row.get("violations", ())
        )
        case_terminations = Counter(
            str(row.get("termination_reason"))
            for row in case_completed
            if row.get("termination_reason") is not None
        )
        per_case[case_id] = {
            "planned": len(case_rows),
            "completed": len(case_completed),
            "operational_failures": len(case_rows) - len(case_completed),
            "feasible_count": len(case_feasible),
            "feasible_rate_among_completed": (
                len(case_feasible) / len(case_completed) if case_completed else None
            ),
            "mean_contribution_margin_usd": (
                statistics.fmean(
                    float(row["contribution_margin_usd"]) for row in case_completed
                )
                if case_completed
                else None
            ),
            "mean_completed_kits": (
                statistics.fmean(float(row["completed_kits"]) for row in case_completed)
                if case_completed
                else None
            ),
            "mean_regret_to_upper_bound_usd": (
                statistics.fmean(
                    float(row["regret_to_upper_bound_usd"]) for row in case_completed
                )
                if case_completed
                else None
            ),
            "termination_reason_counts": dict(sorted(case_terminations.items())),
            "violation_counts": dict(sorted(case_violations.items())),
        }

    all_rows_present = len(rows) == planned_trajectory_count
    all_completed = all_rows_present and len(completed) == planned_trajectory_count
    all_replayed = all_completed and all(
        row.get("receipt_replayed") is True for row in completed
    )
    execution_qualified = all_rows_present and all_completed and all_replayed
    return {
        "planned_trajectory_count": planned_trajectory_count,
        "row_count": len(rows),
        "unattempted_trajectory_count": max(planned_trajectory_count - len(rows), 0),
        "completed_trajectory_count": len(completed),
        "operational_failure_count": len(rows) - len(completed),
        "reliability": len(completed) / len(rows) if rows else None,
        "feasible_count": len(feasible),
        "feasible_rate_among_completed": (
            len(feasible) / len(completed) if completed else None
        ),
        "mean_completed_kits": (
            statistics.fmean(float(row["completed_kits"]) for row in completed)
            if completed
            else None
        ),
        "mean_contribution_margin_usd": (
            statistics.fmean(float(row["contribution_margin_usd"]) for row in completed)
            if completed
            else None
        ),
        "mean_regret_to_upper_bound_usd": (
            statistics.fmean(
                float(row["regret_to_upper_bound_usd"]) for row in completed
            )
            if completed
            else None
        ),
        "median_elapsed_seconds": (
            statistics.median(float(row["elapsed_seconds"]) for row in completed)
            if completed
            else None
        ),
        "total_cost_usd": sum(float(row.get("cost_usd", 0.0)) for row in completed),
        "cached_input_tokens": sum(
            int(row.get("cached_input_tokens", 0)) for row in completed
        ),
        "violation_counts": dict(sorted(violation_counts.items())),
        "action_type_counts": dict(sorted(action_counts.items())),
        "supplier_contact_counts": dict(sorted(supplier_contacts.items())),
        "per_case": per_case,
        "readiness": {
            "execution_qualified": execution_qualified,
            "case_variance_ready": execution_qualified and independent_case_count >= 6,
            "case_variance_minimum_independent_cases": 6,
        },
        "inference": (
            "bounded case-variance pilot on the declared curated panel; not a "
            "population-level model ranking"
            if independent_case_count >= 6
            else "model behavior is descriptive until independently sampled case "
            "count reaches the declared variance-pilot minimum"
        ),
    }


async def _run_cell(
    *,
    run_root: Path,
    case_path: Path,
    inference_seed: int,
    semaphore: asyncio.Semaphore,
    provider_factory: Callable[[], Any],
    candidate: BakeoffCandidate,
    prompt: str,
    prompt_id: str,
) -> dict[str, Any]:
    setup = build_openrouter_setup(
        candidate.route,
        case_path=case_path,
        seed=inference_seed,
        max_output_tokens=1800,
        timeout_seconds=180.0,
        max_cost_usd=0.03,
        harness=MinimalChatHarness(),
        prompt=prompt,
        prompt_id=prompt_id,
    )
    cell = setup.plan.cells[0]
    case_directory = _safe_case_directory(setup.case.case_id, setup.case.content_sha256)
    evidence_root = run_root / "executions" / case_directory / f"seed_{inference_seed}"
    started = time.perf_counter()
    try:
        async with semaphore:
            execution = await execute_plan_cell(
                plan=setup.plan,
                cell_id=cell.cell_id,
                registry=setup.registry,
                evidence_root=evidence_root,
                prompt_sources=setup.prompt_sources,
                providers={"openrouter": provider_factory()},
                pricing=setup.pricing,
                harnesses=setup.harnesses,
            )
        receipt = finalize_procurement_allocation_execution(
            setup=setup, execution=execution
        )
        replayed = replay_procurement_allocation_receipt(
            setup=setup,
            receipt=receipt,
            evidence_root=evidence_root,
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
        outcome = json.loads(canonical_json_bytes(execution.episode_result.outcome))
        row: dict[str, Any] = {
            "case_id": setup.case.case_id,
            "case_content_sha256": setup.case.content_sha256,
            "inference_seed": inference_seed,
            "status": "completed",
            "decision": outcome["decision"],
            "termination_reason": outcome["termination_reason"],
            "feasible": bool(outcome["feasible"]),
            "completed_kits": int(outcome["completed_kits"]),
            "contribution_margin_usd": float(outcome["contribution_margin_usd"]),
            "upper_bound_usd": float(outcome["upper_bound_usd"]),
            "regret_to_upper_bound_usd": float(outcome["regret_to_upper_bound_usd"]),
            "violations": list(outcome["violations"]),
            "elapsed_environment_days": int(outcome["elapsed_days"]),
            "action_count": len(execution.action_executions),
            "action_trace": _public_action_trace(execution),
            "elapsed_seconds": time.perf_counter() - started,
            "input_tokens": sum(call.input_tokens for call in calls),
            "cached_input_tokens": sum(call.cached_input_tokens for call in calls),
            "output_tokens": sum(call.output_tokens for call in calls),
            "cost_usd": execution.total_cost_usd,
            "resolved_models": sorted(
                {
                    call.resolved_model
                    for call in calls
                    if call.resolved_model is not None
                }
            ),
            "receipt_sha256": receipt.receipt_sha256,
            "receipt_replayed": True,
            "replay_level": receipt.replay_level,
        }
    except Exception as error:
        failure_receipt_sha256 = None
        try:
            failure_receipt = finalize_procurement_allocation_failure(
                setup=setup,
                cell_id=cell.cell_id,
                evidence_root=evidence_root,
                error=error,
            )
            failure_receipt_sha256 = failure_receipt.receipt_sha256
        except Exception:
            pass
        row = {
            "case_id": setup.case.case_id,
            "case_content_sha256": setup.case.content_sha256,
            "inference_seed": inference_seed,
            "status": "operational_failure",
            "elapsed_seconds": time.perf_counter() - started,
            "failure_receipt_sha256": failure_receipt_sha256,
            **_failure_summary(error),
        }
    payload = dict(row)
    row["result_sha256"] = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    _atomic_write_json(
        _result_path(
            run_root,
            case_id=setup.case.case_id,
            content_sha256=setup.case.content_sha256,
            seed=inference_seed,
        ),
        row,
    )
    return row


async def run_model_qualification(
    *,
    run_root: Path,
    case_paths: Sequence[Path | str],
    inference_seeds: Sequence[int],
    max_spend_usd: float = 0.30,
    max_parallel_cells: int = 2,
    resume: bool = False,
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
    preflight_fn: Callable[[BakeoffCandidate], Mapping[str, Any]] = preflight_candidate,
    campaign_id: str = CAMPAIGN_ID,
    abort_on_operational_failure: bool = False,
    candidate: BakeoffCandidate = GLM_MORPH_CANDIDATE,
    prompt: str = PROMPT,
    prompt_id: str = "procurement_allocation_prompt_v1",
    treatment_id: str = "unscaffolded_control",
) -> dict[str, Any]:
    cases = _case_records(case_paths)
    plan = planned_model_qualification(
        case_paths=case_paths,
        inference_seeds=inference_seeds,
        max_parallel_cells=max_parallel_cells,
        campaign_id=campaign_id,
        abort_on_operational_failure=abort_on_operational_failure,
        candidate=candidate,
        prompt=prompt,
        prompt_id=prompt_id,
        treatment_id=treatment_id,
    )
    if plan["conservative_cost_ceiling_usd"] > max_spend_usd:
        raise ValueError(
            "conservative qualification ceiling exceeds max_spend_usd: "
            f"{plan['conservative_cost_ceiling_usd']:.6f} > {max_spend_usd:.6f}"
        )
    _validate_operational_run_root(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    plan_path = run_root / "model_plan.json"
    if plan_path.exists():
        existing = json.loads(plan_path.read_text(encoding="utf-8"))
        if canonical_json_bytes(existing) != canonical_json_bytes(plan):
            raise ValueError("existing model plan does not match this invocation")
        if not resume:
            raise FileExistsError("model output exists; pass --resume to continue")
    else:
        _atomic_write_json(plan_path, plan)

    rows: list[dict[str, Any]] = []
    missing: list[tuple[Path, int]] = []
    for record in cases:
        for inference_seed in inference_seeds:
            result_path = _result_path(
                run_root,
                case_id=record["case_id"],
                content_sha256=record["content_sha256"],
                seed=inference_seed,
            )
            if result_path.exists():
                rows.append(
                    _read_result(
                        result_path,
                        case_id=record["case_id"],
                        content_sha256=record["content_sha256"],
                        seed=inference_seed,
                    )
                )
            else:
                missing.append((record["path"], inference_seed))

    prior_preflight = None
    summary_path = run_root / "summary.json"
    if resume and summary_path.exists():
        prior = json.loads(summary_path.read_text(encoding="utf-8"))
        if isinstance(prior, Mapping) and isinstance(prior.get("preflight"), Mapping):
            prior_preflight = dict(prior["preflight"])
    preflight = dict(preflight_fn(candidate)) if missing else prior_preflight
    semaphore = asyncio.Semaphore(max_parallel_cells)
    if missing:
        if abort_on_operational_failure and any(
            row.get("status") == "operational_failure" for row in rows
        ):
            raise ValueError(
                "cannot resume an aborted qualification after an operational "
                "failure; use a fresh attempt root"
            )
        if abort_on_operational_failure:
            for case_path, inference_seed in missing:
                row = await _run_cell(
                    run_root=run_root,
                    case_path=case_path,
                    inference_seed=inference_seed,
                    semaphore=semaphore,
                    provider_factory=provider_factory,
                    candidate=candidate,
                    prompt=prompt,
                    prompt_id=prompt_id,
                )
                rows.append(row)
                if row.get("status") == "operational_failure":
                    break
        else:
            rows.extend(
                await asyncio.gather(
                    *(
                        _run_cell(
                            run_root=run_root,
                            case_path=case_path,
                            inference_seed=inference_seed,
                            semaphore=semaphore,
                            provider_factory=provider_factory,
                            candidate=candidate,
                            prompt=prompt,
                            prompt_id=prompt_id,
                        )
                        for case_path, inference_seed in missing
                    )
                )
            )
    rows.sort(key=lambda row: (str(row["case_id"]), int(row["inference_seed"])))
    summary = summarize_rows(
        rows,
        planned_trajectory_count=plan["planned_trajectory_count"],
        independent_case_count=plan["independent_case_count"],
    )
    artifact = {
        "schema_version": "aeread.procurement_allocation_model_qualification/0.1",
        "plan": plan,
        "preflight": preflight,
        "runtime_versions": {"openai": importlib.metadata.version("openai")},
        "measurement_boundary": {
            "construct": "procurement decision quality under hidden supplier terms",
            "case_environment_and_objective": "AERead authoritative",
            "harness": "fixed transport; not compared",
            "provider_failures": "typed operational missingness",
            "receipt_replay": "required for every completed trajectory",
        },
        "summary": summary,
        "rows": rows,
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(artifact)
    ).hexdigest()
    _atomic_write_json(summary_path, artifact)
    return artifact


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", "--output", type=Path, required=True)
    parser.add_argument("--case", type=Path, action="append", dest="cases")
    parser.add_argument("--replicates", type=int, default=3)
    parser.add_argument("--master-seed", type=int, default=20260902)
    parser.add_argument("--max-spend-usd", type=float, default=0.30)
    parser.add_argument("--max-parallel-cells", type=int, default=2)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--publication-root", "--publish-evidence", type=Path)
    parser.add_argument("--publish-only", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.publish_only:
        if arguments.publication_root is None:
            parser.error("--publish-only requires --publication-root")
        published = publish_model_qualification(
            run_root=arguments.run_root,
            publication_root=arguments.publication_root,
        )
        print(json.dumps(published["manifest"], indent=2, sort_keys=True))
        return 0
    if arguments.publication_root is not None and not arguments.execute:
        parser.error("--publication-root requires --execute or --publish-only")
    case_paths = tuple(arguments.cases or CASE_VARIANCE_PATHS)
    seeds = derive_inference_seeds(
        master_seed=arguments.master_seed, count=arguments.replicates
    )
    if not arguments.execute:
        print(
            json.dumps(
                planned_model_qualification(
                    case_paths=case_paths,
                    inference_seeds=seeds,
                    max_parallel_cells=arguments.max_parallel_cells,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    artifact = asyncio.run(
        run_model_qualification(
            run_root=arguments.run_root,
            case_paths=case_paths,
            inference_seeds=seeds,
            max_spend_usd=arguments.max_spend_usd,
            max_parallel_cells=arguments.max_parallel_cells,
            resume=arguments.resume,
        )
    )
    if arguments.publication_root is not None:
        publish_model_qualification(
            run_root=arguments.run_root,
            publication_root=arguments.publication_root,
        )
    print(json.dumps(artifact["summary"], indent=2, sort_keys=True))
    return 0 if artifact["summary"]["readiness"]["execution_qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CAMPAIGN_ID",
    "GLM_MORPH_CANDIDATE",
    "PUBLICATION_ID",
    "conservative_cost_ceiling",
    "derive_inference_seeds",
    "planned_model_qualification",
    "publish_model_qualification",
    "run_model_qualification",
    "summarize_rows",
]
