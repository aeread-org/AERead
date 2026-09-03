"""Paired GLM prompt-scaffold campaign for procurement allocation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import itertools
import json
import os
import statistics
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from aeread.shared_runner.model_call.harness import MinimalChatHarness
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import (
    OpenRouterChatClient,
    ProviderRequest,
    execute_plan_cell,
)
from aeread_families.procurement_grounding.bakeoff import preflight_candidate

from .blinded_invariance import (
    CAMPAIGN_ID as OPAQUE_CONTROL_CAMPAIGN_ID,
    PAIRED_INFERENCE_SEEDS,
)
from .case_matrix import BLINDED_CASE_PATHS, CASE_VARIANCE_PATHS, REPOSITORY_ROOT
from .model_campaign import (
    CAMPAIGN_ID as LABELED_CONTROL_CAMPAIGN_ID,
    GLM_MORPH_CANDIDATE,
    conservative_cost_ceiling,
    planned_model_qualification,
    run_model_qualification,
)
from .runner import PROMPT as CONTROL_PROMPT
from .runner import SequenceResponseProvider, build_openrouter_setup


CAMPAIGN_ID = "procurement_allocation_glm_morph_strategy_scaffold_v1"
TREATMENT_ID = "public_evidence_decision_procedure_v1"
PROMPT_ID = "procurement_allocation_strategy_scaffold_v1"
STRATEGY_PROMPT = (
    CONTROL_PROMPT
    + """

Use this public-evidence decision procedure before choosing each action:
1. Ignore supplier IDs and names as quality signals. Rank only provisional listing
   price, claimed lead time, claimed variant, and the objective's requirements.
2. Preserve the ten-action budget. For each BOM component, qualify the smallest
   plausible supplier set: request a formal quote, then verify an exact-variant
   sample. Add another supplier only when verified capacity or service requires it.
3. Treat only current formal offers and verified samples as decision evidence.
   Check exact variant, MOQ/order step, capacity, landed cost, payment timing,
   deadline/on-time probability, yield, and return/refund terms.
4. Before an award, estimate component-complete kits from the weakest BOM component,
   confirm minimum service and cash budget, and prefer the feasible positive-margin
   allocation. Use quantities that satisfy each offer's MOQ, order step, and capacity.
5. Counter only when a current formal offer blocks an otherwise feasible allocation
   and enough actions remain. Defer only when no evidence-qualified, budget-feasible
   positive-utility award can be submitted.

Return only the next JSON action, never this analysis.
"""
)

PANELS = {
    "labeled_original": {
        "case_paths": CASE_VARIANCE_PATHS,
        "treatment_campaign_id": f"{CAMPAIGN_ID}.labeled_original",
        "control_campaign_id": LABELED_CONTROL_CAMPAIGN_ID,
    },
    "opaque_reordered": {
        "case_paths": BLINDED_CASE_PATHS,
        "treatment_campaign_id": f"{CAMPAIGN_ID}.opaque_reordered",
        "control_campaign_id": OPAQUE_CONTROL_CAMPAIGN_ID,
    },
}
DEFAULT_CONTROL_ROOTS = {
    "labeled_original": (
        REPOSITORY_ROOT
        / "runs"
        / "procurement_allocation"
        / LABELED_CONTROL_CAMPAIGN_ID
        / "qualification_attempt_001"
    ),
    "opaque_reordered": (
        REPOSITORY_ROOT
        / "runs"
        / "procurement_allocation"
        / OPAQUE_CONTROL_CAMPAIGN_ID
        / "qualification_attempt_004"
    ),
}
METRICS = (
    "feasible",
    "completed_kits",
    "contribution_margin_usd",
    "regret_to_upper_bound_usd",
)
PUBLISHABLE_ROW_FIELDS = (
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


def _write_once_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"refusing to replace different artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_once_text(path: Path, value: str) -> None:
    payload = value.encode("utf-8")
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"refusing to replace different artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def build_plan(*, max_parallel_cells: int = 1) -> dict[str, Any]:
    if max_parallel_cells < 1:
        raise ValueError("max_parallel_cells must be positive")
    panel_plans = {
        panel: planned_model_qualification(
            case_paths=spec["case_paths"],
            inference_seeds=PAIRED_INFERENCE_SEEDS,
            max_parallel_cells=max_parallel_cells,
            campaign_id=str(spec["treatment_campaign_id"]),
            abort_on_operational_failure=True,
            prompt=STRATEGY_PROMPT,
            prompt_id=PROMPT_ID,
            treatment_id=TREATMENT_ID,
        )
        for panel, spec in PANELS.items()
    }
    plan: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_strategy_plan/0.1",
        "campaign_id": CAMPAIGN_ID,
        "treatment_id": TREATMENT_ID,
        "prompt": {
            "prompt_id": PROMPT_ID,
            "sha256": hashlib.sha256(STRATEGY_PROMPT.encode()).hexdigest(),
            "control_prompt_sha256": hashlib.sha256(
                CONTROL_PROMPT.encode()
            ).hexdigest(),
        },
        "model": GLM_MORPH_CANDIDATE.route.model,
        "revision": GLM_MORPH_CANDIDATE.route.revision,
        "provider": GLM_MORPH_CANDIDATE.route.route_provider,
        "panels": panel_plans,
        "execution_order": list(PANELS),
        "planned_trajectory_count": sum(
            int(panel_plan["planned_trajectory_count"])
            for panel_plan in panel_plans.values()
        ),
        "independent_case_count": len(CASE_VARIANCE_PATHS),
        "inference_seeds": list(PAIRED_INFERENCE_SEEDS),
        "max_parallel_cells": max_parallel_cells,
        "abort_on_operational_failure": True,
        "admission_canary_scored": False,
        "conservative_scored_cost_ceiling_usd": sum(
            float(panel_plan["conservative_cost_ceiling_usd"])
            for panel_plan in panel_plans.values()
        ),
        "conservative_total_cost_ceiling_usd": sum(
            float(panel_plan["conservative_cost_ceiling_usd"])
            for panel_plan in panel_plans.values()
        )
        + 0.03,
        "analysis": {
            "primary_contrast": "strategy scaffold minus unscaffolded control",
            "surface_contrast": "opaque/reordered minus labeled/original",
            "interaction": "change in surface contrast under the scaffold",
            "resampling_unit": "procurement world after seed averaging",
            "uncertainty": "exact six-cluster percentile bootstrap",
        },
        "claim_scope": (
            "paired prompt-treatment pilot over six curated procurement worlds; "
            "not a population model ranking"
        ),
    }
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return plan


async def _representative_provider_request() -> ProviderRequest:
    setup = build_openrouter_setup(
        GLM_MORPH_CANDIDATE.route,
        case_path=CASE_VARIANCE_PATHS[0],
        seed=PAIRED_INFERENCE_SEEDS[0],
        max_output_tokens=1800,
        timeout_seconds=180.0,
        max_cost_usd=0.03,
        harness=MinimalChatHarness(),
        prompt=STRATEGY_PROMPT,
        prompt_id=PROMPT_ID,
    )
    provider = SequenceResponseProvider(
        (json.dumps({"action": "defer", "reason": "request-shape capture"}),)
    )
    with tempfile.TemporaryDirectory(
        prefix="aeread-procurement-scaffold-canary-"
    ) as root:
        await execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=Path(root),
            prompt_sources=setup.prompt_sources,
            providers={"openrouter": provider},
            pricing=setup.pricing,
            harnesses=setup.harnesses,
        )
    if len(provider.requests) != 1:
        raise RuntimeError("canary request capture did not make exactly one call")
    return provider.requests[0]


def _failure_fields(error: BaseException) -> dict[str, Any]:
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    status_code = next(
        (
            value
            for item in chain
            if isinstance((value := getattr(item, "status_code", None)), int)
        ),
        None,
    )
    condition = next(
        (
            value
            for item in chain
            if isinstance((value := getattr(item, "condition", None)), str)
        ),
        None,
    )
    if condition is None and status_code == 429:
        condition = "rate_limit"
    return {
        "failure_type": type(error).__name__,
        "failure_condition": condition or "provider_failure",
        "failure_status_code": status_code,
    }


async def run_admission_canary(
    *, path: Path, provider_factory: Callable[[], Any] = OpenRouterChatClient
) -> dict[str, Any]:
    request = await _representative_provider_request()
    if path.exists():
        value = json.loads(path.read_text())
        recorded = value.get("artifact_sha256")
        payload = {key: item for key, item in value.items() if key != "artifact_sha256"}
        if recorded != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
            raise ValueError("admission canary digest mismatch")
        if value.get("campaign_id") != CAMPAIGN_ID:
            raise ValueError("admission canary campaign identity mismatch")
        if value.get("request_sha256") != request.request_sha256:
            raise ValueError("admission canary request identity mismatch")
        return value
    record: dict[str, Any] = {
        "schema_version": "aeread.provider_admission_canary/0.1",
        "campaign_id": CAMPAIGN_ID,
        "attempted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "request_sha256": request.request_sha256,
        "prompt_id": PROMPT_ID,
        "prompt_sha256": hashlib.sha256(STRATEGY_PROMPT.encode()).hexdigest(),
        "model": request.model,
        "revision": request.revision,
        "route_provider": request.provider_metadata["route_provider"],
        "max_output_tokens": request.max_output_tokens,
        "max_cost_usd": request.max_cost_usd,
        "scored": False,
    }
    try:
        result = await provider_factory().complete(request)
        action = json.loads(result.output_text)
        if not isinstance(action, Mapping) or not isinstance(action.get("action"), str):
            raise ValueError("canary completion is not a structured action")
        record.update(
            {
                "status": "admitted",
                "resolved_model": result.resolved_model,
                "finish_reason": result.finish_reason,
                "input_tokens": result.input_tokens,
                "cached_input_tokens": result.cached_input_tokens,
                "output_tokens": result.output_tokens,
                "cost_usd": result.cost_usd,
                "structured_action": action["action"],
            }
        )
    except Exception as error:
        record.update({"status": "rejected", "cost_usd": 0.0, **_failure_fields(error)})
    record["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(record)).hexdigest()
    _write_once_json(path, record)
    return record


def _verified_summary(root: Path, *, campaign_id: str) -> tuple[dict[str, Any], str]:
    path = root / "summary.json"
    raw_bytes = path.read_bytes()
    value = json.loads(raw_bytes)
    if not isinstance(value, dict):
        raise ValueError(f"qualification summary must be an object: {path}")
    recorded = value.get("artifact_sha256")
    payload = {key: item for key, item in value.items() if key != "artifact_sha256"}
    if recorded != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
        raise ValueError(f"qualification artifact digest mismatch: {path}")
    plan = value.get("plan")
    if not isinstance(plan, Mapping) or plan.get("campaign_id") != campaign_id:
        raise ValueError(f"qualification campaign identity mismatch: {path}")
    plan_recorded = plan.get("plan_sha256")
    plan_payload = {key: item for key, item in plan.items() if key != "plan_sha256"}
    if plan_recorded != hashlib.sha256(canonical_json_bytes(plan_payload)).hexdigest():
        raise ValueError(f"qualification plan digest mismatch: {path}")
    rows = value.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"qualification rows must be an array: {path}")
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("qualification row must be an object")
        result_recorded = row.get("result_sha256")
        result_payload = {
            key: item for key, item in row.items() if key != "result_sha256"
        }
        if (
            result_recorded
            != hashlib.sha256(canonical_json_bytes(result_payload)).hexdigest()
        ):
            raise ValueError("qualification row digest mismatch")
    return value, hashlib.sha256(raw_bytes).hexdigest()


def _row_index(
    rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, int], Mapping[str, Any]]:
    result: dict[tuple[str, int], Mapping[str, Any]] = {}
    for row in rows:
        key = (str(row["case_id"]).rsplit(".", 1)[-1], int(row["inference_seed"]))
        if key in result:
            raise ValueError(f"duplicate case/seed row: {key}")
        result[key] = row
    return result


def _metric(row: Mapping[str, Any], metric: str) -> float:
    if metric == "feasible":
        return 1.0 if row.get("feasible") is True else 0.0
    return float(row[metric])


def _cluster_interval(values: Sequence[float]) -> list[float]:
    if len(values) != 6:
        raise ValueError("cluster interval requires exactly six procurement worlds")
    means = sorted(
        statistics.fmean(values[index] for index in sample)
        for sample in itertools.product(range(6), repeat=6)
    )
    return [
        means[int(0.025 * (len(means) - 1))],
        means[int(0.975 * (len(means) - 1))],
    ]


def _aggregate(values: Sequence[float]) -> dict[str, Any]:
    return {
        "case_cluster_mean": statistics.fmean(values) if values else None,
        "case_cluster_bootstrap_95_interval": (
            _cluster_interval(values) if len(values) == 6 else None
        ),
    }


def build_strategy_comparison(
    *,
    treatment_run_root: Path,
    control_roots: Mapping[str, Path] = DEFAULT_CONTROL_ROOTS,
) -> dict[str, Any]:
    prompt_sha = hashlib.sha256(STRATEGY_PROMPT.encode()).hexdigest()
    artifacts: dict[str, dict[str, Any]] = {}
    source: dict[str, Any] = {}
    integrity: dict[str, bool] = {}
    panel_results: dict[str, Any] = {}
    for panel, spec in PANELS.items():
        control, control_file_sha = _verified_summary(
            Path(control_roots[panel]), campaign_id=str(spec["control_campaign_id"])
        )
        treatment, treatment_file_sha = _verified_summary(
            treatment_run_root / panel,
            campaign_id=str(spec["treatment_campaign_id"]),
        )
        artifacts[panel] = {"control": control, "treatment": treatment}
        source[panel] = {
            "control_summary_file_sha256": control_file_sha,
            "control_artifact_sha256": control["artifact_sha256"],
            "control_plan_sha256": control["plan"]["plan_sha256"],
            "treatment_summary_file_sha256": treatment_file_sha,
            "treatment_artifact_sha256": treatment["artifact_sha256"],
            "treatment_plan_sha256": treatment["plan"]["plan_sha256"],
        }
        route_fields = ("model", "revision", "provider", "quantization", "harness")
        integrity[f"{panel}_route_and_harness_match"] = all(
            control["plan"].get(field) == treatment["plan"].get(field)
            for field in route_fields
        )
        integrity[f"{panel}_seeds_match"] = (
            control["plan"].get("inference_seeds")
            == treatment["plan"].get("inference_seeds")
            == list(PAIRED_INFERENCE_SEEDS)
        )
        integrity[f"{panel}_treatment_prompt_bound"] = treatment["plan"].get(
            "prompt"
        ) == {
            "prompt_id": PROMPT_ID,
            "sha256": prompt_sha,
            "treatment_id": TREATMENT_ID,
        }
        integrity[f"{panel}_both_execution_qualified"] = all(
            item.get("summary", {}).get("readiness", {}).get("execution_qualified")
            is True
            for item in (control, treatment)
        )
        control_rows = _row_index(control["rows"])
        treatment_rows = _row_index(treatment["rows"])
        integrity[f"{panel}_rows_completed_replayed_and_revision_pinned"] = all(
            row.get("status") == "completed"
            and row.get("receipt_replayed") is True
            and row.get("resolved_models") == [artifact["plan"]["revision"]]
            for artifact in (control, treatment)
            for row in artifact["rows"]
        )
        expected_keys = {
            (path.stem, seed)
            for path in CASE_VARIANCE_PATHS
            for seed in PAIRED_INFERENCE_SEEDS
        }
        integrity[f"{panel}_all_pairs_present"] = (
            set(control_rows) == set(treatment_rows) == expected_keys
        )
        upper_bounds_match = True
        case_content_digests_match = True
        transitions: Counter[str] = Counter()
        per_case: dict[str, Any] = {}
        for path in CASE_VARIANCE_PATHS:
            slug = path.stem
            case_control = [
                control_rows[(slug, seed)] for seed in PAIRED_INFERENCE_SEEDS
            ]
            case_treatment = [
                treatment_rows[(slug, seed)] for seed in PAIRED_INFERENCE_SEEDS
            ]
            for control_row, treatment_row in zip(
                case_control, case_treatment, strict=True
            ):
                upper_bounds_match = upper_bounds_match and float(
                    control_row["upper_bound_usd"]
                ) == float(treatment_row["upper_bound_usd"])
                case_content_digests_match = case_content_digests_match and (
                    control_row["case_content_sha256"]
                    == treatment_row["case_content_sha256"]
                )
                transitions[
                    f"{'pass' if control_row['feasible'] else 'fail'}_"
                    f"{'pass' if treatment_row['feasible'] else 'fail'}"
                ] += 1
            case_bounds = {
                float(row["upper_bound_usd"])
                for row in (*case_control, *case_treatment)
            }
            upper_bounds_match = upper_bounds_match and len(case_bounds) == 1
            per_case[slug] = {"upper_bound_usd": next(iter(case_bounds))}
            for metric in METRICS:
                control_mean = statistics.fmean(
                    _metric(row, metric) for row in case_control
                )
                treatment_mean = statistics.fmean(
                    _metric(row, metric) for row in case_treatment
                )
                per_case[slug][metric] = {
                    "control_seed_mean": control_mean,
                    "treatment_seed_mean": treatment_mean,
                    "treatment_minus_control": treatment_mean - control_mean,
                }
        integrity[f"{panel}_upper_bounds_match"] = upper_bounds_match
        integrity[f"{panel}_case_content_digests_match"] = case_content_digests_match
        panel_results[panel] = {
            "feasibility_transition_counts": dict(sorted(transitions.items())),
            "per_case": per_case,
            "aggregate_treatment_minus_control": {
                metric: _aggregate(
                    [
                        per_case[path.stem][metric]["treatment_minus_control"]
                        for path in CASE_VARIANCE_PATHS
                    ]
                )
                for metric in METRICS
            },
        }

    integrity["cross_surface_upper_bounds_match"] = all(
        panel_results["labeled_original"]["per_case"][path.stem]["upper_bound_usd"]
        == panel_results["opaque_reordered"]["per_case"][path.stem]["upper_bound_usd"]
        for path in CASE_VARIANCE_PATHS
    )

    surface_sensitivity: dict[str, Any] = {}
    for metric in METRICS:
        per_case = {}
        interactions = []
        for path in CASE_VARIANCE_PATHS:
            slug = path.stem
            labeled = panel_results["labeled_original"]["per_case"][slug][metric]
            opaque = panel_results["opaque_reordered"]["per_case"][slug][metric]
            control_surface = opaque["control_seed_mean"] - labeled["control_seed_mean"]
            treatment_surface = (
                opaque["treatment_seed_mean"] - labeled["treatment_seed_mean"]
            )
            interaction = (
                opaque["treatment_minus_control"] - labeled["treatment_minus_control"]
            )
            interactions.append(interaction)
            per_case[slug] = {
                "control_opaque_minus_labeled": control_surface,
                "treatment_opaque_minus_labeled": treatment_surface,
                "difference_in_differences": interaction,
                "absolute_surface_gap_reduction": abs(control_surface)
                - abs(treatment_surface),
            }
        control_gaps = [
            per_case[path.stem]["control_opaque_minus_labeled"]
            for path in CASE_VARIANCE_PATHS
        ]
        treatment_gaps = [
            per_case[path.stem]["treatment_opaque_minus_labeled"]
            for path in CASE_VARIANCE_PATHS
        ]
        gap_reductions = [
            per_case[path.stem]["absolute_surface_gap_reduction"]
            for path in CASE_VARIANCE_PATHS
        ]
        surface_sensitivity[metric] = {
            "control_surface_effect": _aggregate(control_gaps),
            "treatment_surface_effect": _aggregate(treatment_gaps),
            "difference_in_differences": _aggregate(interactions),
            "absolute_surface_gap_reduction": _aggregate(gap_reductions),
            "per_case": per_case,
        }

    comparison: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_strategy_comparison/0.1",
        "campaign_id": CAMPAIGN_ID,
        "treatment_id": TREATMENT_ID,
        "panels": panel_results,
        "surface_sensitivity": surface_sensitivity,
        "integrity": integrity,
        "readiness": {"strategy_comparison_qualified": all(integrity.values())},
        "source": source,
        "interpretation": (
            "Effects are paired within six curated worlds after averaging three "
            "model seeds. Positive absolute_surface_gap_reduction means the scaffold "
            "reduced surface sensitivity; it is not assumed in advance."
        ),
    }
    comparison["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(comparison)
    ).hexdigest()
    return comparison


def _execution_status(run_root: Path, canary: Mapping[str, Any]) -> dict[str, Any]:
    panels: dict[str, Any] = {}
    completed = failures = attempted = 0
    scored_cost = 0.0
    for panel in PANELS:
        path = run_root / panel / "summary.json"
        if not path.exists():
            panels[panel] = {"status": "not_started"}
            continue
        value = json.loads(path.read_text())
        summary = value["summary"]
        panels[panel] = {
            "status": (
                "qualified"
                if summary["readiness"]["execution_qualified"]
                else "incomplete"
            ),
            "completed_trajectory_count": summary["completed_trajectory_count"],
            "operational_failure_count": summary["operational_failure_count"],
            "unattempted_trajectory_count": summary["unattempted_trajectory_count"],
            "scored_cost_usd": summary["total_cost_usd"],
            "artifact_sha256": value["artifact_sha256"],
        }
        completed += int(summary["completed_trajectory_count"])
        failures += int(summary["operational_failure_count"])
        attempted += int(summary["row_count"])
        scored_cost += float(summary["total_cost_usd"])
    status: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_strategy_status/0.1",
        "campaign_id": CAMPAIGN_ID,
        "canary": {
            key: canary.get(key)
            for key in (
                "status",
                "cost_usd",
                "failure_type",
                "failure_condition",
                "failure_status_code",
                "artifact_sha256",
            )
            if key in canary
        },
        "panels": panels,
        "summary": {
            "planned_trajectory_count": 36,
            "attempted_trajectory_count": attempted,
            "completed_trajectory_count": completed,
            "operational_failure_count": failures,
            "unattempted_trajectory_count": 36 - attempted,
            "scored_cost_usd": scored_cost,
            "total_cost_including_canary_usd": scored_cost
            + float(canary.get("cost_usd", 0.0)),
            "execution_qualified": completed == 36 and failures == 0,
        },
    }
    status["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(status)).hexdigest()
    return status


async def run_strategy_campaign(
    *,
    run_root: Path,
    max_spend_usd: float = 0.60,
    max_parallel_cells: int = 1,
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
    preflight_fn: Callable[[Any], Mapping[str, Any]] = preflight_candidate,
) -> dict[str, Any]:
    resolved = run_root.resolve()
    if "runs" not in resolved.parts or {"evidence", "output", "outputs"}.intersection(
        resolved.parts
    ):
        raise ValueError("run_root must be under runs/ and outside publication paths")
    if run_root.exists():
        raise FileExistsError(
            "strategy campaign output already exists; use a fresh attempt"
        )
    plan = build_plan(max_parallel_cells=max_parallel_cells)
    if float(plan["conservative_total_cost_ceiling_usd"]) > max_spend_usd:
        raise ValueError("strategy campaign conservative ceiling exceeds max_spend_usd")
    _write_once_json(run_root / "campaign_plan.json", plan)
    canary = await run_admission_canary(
        path=run_root / "admission_canary.json", provider_factory=provider_factory
    )
    if canary["status"] == "admitted":
        preflight = dict(preflight_fn(GLM_MORPH_CANDIDATE))
        for panel, spec in PANELS.items():
            artifact = await run_model_qualification(
                run_root=run_root / panel,
                case_paths=spec["case_paths"],
                inference_seeds=PAIRED_INFERENCE_SEEDS,
                max_spend_usd=max_spend_usd,
                max_parallel_cells=max_parallel_cells,
                provider_factory=provider_factory,
                preflight_fn=lambda _candidate, value=preflight: value,
                campaign_id=str(spec["treatment_campaign_id"]),
                abort_on_operational_failure=True,
                prompt=STRATEGY_PROMPT,
                prompt_id=PROMPT_ID,
                treatment_id=TREATMENT_ID,
            )
            if not artifact["summary"]["readiness"]["execution_qualified"]:
                break
    status = _execution_status(run_root, canary)
    _write_once_json(run_root / "campaign_status.json", status)
    return status


def _sanitized_panel(
    *, run_root: Path, panel: str, expected_campaign_id: str
) -> dict[str, Any]:
    artifact, file_sha = _verified_summary(
        run_root / panel, campaign_id=expected_campaign_id
    )
    preflight = artifact.get("preflight")
    safe_preflight = None
    if isinstance(preflight, Mapping):
        safe_preflight = {
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
    return {
        "schema_version": "aeread.procurement_allocation_strategy_panel_review/0.1",
        "campaign_id": expected_campaign_id,
        "panel": panel,
        "source": {
            "raw_summary_path": (
                f"runs/procurement_allocation/{CAMPAIGN_ID}/{run_root.name}/"
                f"{panel}/summary.json"
            ),
            "raw_summary_file_sha256": file_sha,
            "raw_artifact_sha256": artifact["artifact_sha256"],
            "plan_sha256": artifact["plan"]["plan_sha256"],
        },
        "plan": artifact["plan"],
        "preflight": safe_preflight,
        "summary": artifact["summary"],
        "rows": [
            {key: row[key] for key in PUBLISHABLE_ROW_FIELDS if key in row}
            for row in artifact["rows"]
        ],
    }


def publish_strategy_campaign(
    *, run_root: Path, publication_root: Path, comparison: Mapping[str, Any]
) -> dict[str, Any]:
    if publication_root.resolve().parent.name != "evidence":
        raise ValueError("publication_root must be one direct evidence/ bundle")
    comparison_recorded = comparison.get("artifact_sha256")
    comparison_payload = {
        key: item for key, item in comparison.items() if key != "artifact_sha256"
    }
    if (
        comparison_recorded
        != hashlib.sha256(canonical_json_bytes(comparison_payload)).hexdigest()
    ):
        raise ValueError("strategy comparison digest mismatch")
    if not comparison.get("readiness", {}).get("strategy_comparison_qualified"):
        raise ValueError("strategy comparison is not qualified")
    plan_path = run_root / "campaign_plan.json"
    plan = json.loads(plan_path.read_text())
    recorded_plan_sha = plan.get("plan_sha256")
    plan_payload = {key: item for key, item in plan.items() if key != "plan_sha256"}
    if (
        recorded_plan_sha
        != hashlib.sha256(canonical_json_bytes(plan_payload)).hexdigest()
    ):
        raise ValueError("campaign plan digest mismatch")
    if plan.get("campaign_id") != CAMPAIGN_ID:
        raise ValueError("campaign plan identity mismatch")
    artifacts: dict[str, str] = {}
    for panel, spec in PANELS.items():
        review = _sanitized_panel(
            run_root=run_root,
            panel=panel,
            expected_campaign_id=str(spec["treatment_campaign_id"]),
        )
        review["artifact_sha256"] = hashlib.sha256(
            canonical_json_bytes(review)
        ).hexdigest()
        relative = f"reports/{panel}_qualification.json"
        path = publication_root / relative
        _write_once_json(path, review)
        artifacts[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    comparison_path = publication_root / "reports" / "strategy_effects.json"
    _write_once_json(comparison_path, comparison)
    artifacts["reports/strategy_effects.json"] = hashlib.sha256(
        comparison_path.read_bytes()
    ).hexdigest()
    canary = json.loads((run_root / "admission_canary.json").read_text())
    recorded_canary_sha = canary.get("artifact_sha256")
    canary_payload = {
        key: item for key, item in canary.items() if key != "artifact_sha256"
    }
    if (
        recorded_canary_sha
        != hashlib.sha256(canonical_json_bytes(canary_payload)).hexdigest()
    ):
        raise ValueError("admission canary digest mismatch")
    if (
        canary.get("campaign_id") != CAMPAIGN_ID
        or canary.get("status") != "admitted"
        or canary.get("scored") is not False
        or canary.get("prompt_id") != PROMPT_ID
        or canary.get("prompt_sha256")
        != hashlib.sha256(STRATEGY_PROMPT.encode()).hexdigest()
    ):
        raise ValueError("admission canary identity or scoring boundary mismatch")
    canary_path = publication_root / "reports" / "admission_canary.json"
    _write_once_json(canary_path, canary)
    artifacts["reports/admission_canary.json"] = hashlib.sha256(
        canary_path.read_bytes()
    ).hexdigest()
    source_bindings = {
        "campaign_plan_sha256": recorded_plan_sha,
        "comparison_artifact_sha256": comparison_recorded,
        "implementation_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
    }
    fact: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_strategy_manifest/0.1",
        "campaign_id": CAMPAIGN_ID,
        "artifacts": {
            name: {"path": name, "sha256": sha} for name, sha in artifacts.items()
        },
        "source_bindings": source_bindings,
        "publication_scope": "sanitized paired prompt-treatment evidence",
    }
    fact["manifest_sha256"] = hashlib.sha256(canonical_json_bytes(fact)).hexdigest()
    fact_path = publication_root / "tables" / "fact_manifest.json"
    _write_once_json(fact_path, fact)
    artifacts["tables/fact_manifest.json"] = hashlib.sha256(
        fact_path.read_bytes()
    ).hexdigest()
    manifest: dict[str, Any] = {
        "schema_version": "aeread.publication_manifest/0.1",
        "publication_id": CAMPAIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "artifacts": artifacts,
        "source_bindings": source_bindings,
        "privacy_boundary": {
            "included": "prompt hashes, public action traces, outcomes, typed failures, usage, cost, and receipt/result digests",
            "excluded": "full prompts, observations, provider payloads, event logs, hidden supplier terms, and account metadata",
        },
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes(manifest)
    ).hexdigest()
    _write_once_json(publication_root / "publication_manifest.json", manifest)
    _write_once_text(
        publication_root / "README.md",
        f"# {CAMPAIGN_ID}\n\n"
        "Sanitized, digest-bound evidence for the paired procurement strategy-scaffold "
        "campaign. Raw prompts, observations, provider payloads, event logs, and replay "
        "stores remain under the ignored `runs/` tree.\n",
    )
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument(
        "--labeled-control-root",
        type=Path,
        default=DEFAULT_CONTROL_ROOTS["labeled_original"],
    )
    parser.add_argument(
        "--opaque-control-root",
        type=Path,
        default=DEFAULT_CONTROL_ROOTS["opaque_reordered"],
    )
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument("--max-spend-usd", type=float, default=0.60)
    parser.add_argument("--max-parallel-cells", type=int, default=1)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--publish-only", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.execute and arguments.publish_only:
        parser.error("--execute and --publish-only are mutually exclusive")
    controls = {
        "labeled_original": arguments.labeled_control_root,
        "opaque_reordered": arguments.opaque_control_root,
    }
    if not arguments.execute and not arguments.publish_only:
        print(
            json.dumps(
                build_plan(max_parallel_cells=arguments.max_parallel_cells),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if arguments.execute:
        status = asyncio.run(
            run_strategy_campaign(
                run_root=arguments.run_root,
                max_spend_usd=arguments.max_spend_usd,
                max_parallel_cells=arguments.max_parallel_cells,
            )
        )
        if not status["summary"]["execution_qualified"]:
            print(json.dumps(status, indent=2, sort_keys=True))
            return 3 if status["canary"]["status"] == "rejected" else 2
    if arguments.publication_root is None:
        parser.error("a qualified execution requires --publication-root")
    comparison = build_strategy_comparison(
        treatment_run_root=arguments.run_root, control_roots=controls
    )
    _write_once_json(arguments.run_root / "strategy_comparison.json", comparison)
    manifest = publish_strategy_campaign(
        run_root=arguments.run_root,
        publication_root=arguments.publication_root,
        comparison=comparison,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CAMPAIGN_ID",
    "PANELS",
    "PROMPT_ID",
    "STRATEGY_PROMPT",
    "TREATMENT_ID",
    "build_plan",
    "build_strategy_comparison",
    "publish_strategy_campaign",
    "run_admission_canary",
    "run_strategy_campaign",
]
