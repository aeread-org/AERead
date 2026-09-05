"""Frozen held-out confirmation of the verifier-visible pre-award check.

Twelve worlds generated after the pre-award-check prompt was frozen and after
the development result on the confirmatory v1 panel was read. Unlike the
development campaign, the control arm is re-run here on the same environment
that exposes ``check_award``, so the estimated effect is the prompt's use of the
action rather than the action's presence. Control is the frozen V4 strategy
scaffold; treatment is the frozen pre-award-check procedure.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
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

from .confirmatory_v2_case_matrix import (
    CASE_SLUGS,
    LABELED_PATHS,
    OPAQUE_PATHS,
    economic_world_sha256,
)
from .model_campaign import (
    TRANSIENT_RETRY_CONDITIONS,
    derive_inference_seeds,
    planned_model_qualification,
    run_model_qualification,
)
from .runner import PROMPT as CONTROL_PROMPT
from .runner import SequenceResponseProvider, build_openrouter_setup
from .pre_award_check_campaign import (
    FROZEN_WORKSHEET_PROMPT_SHA256 as FROZEN_TREATMENT_PROMPT_SHA256,
    PROMPT_ID as V4_PROMPT_ID,
    TREATMENT_ID as V4_TREATMENT_ID,
    WORKSHEET_PROMPT as STRATEGY_PROMPT,
)
from .strategy_scaffold import (
    GLM_PARASAIL_CANDIDATE,
    PROMPT_ID as SCAFFOLD_PROMPT_ID,
    STRATEGY_PROMPT as SCAFFOLD_PROMPT,
    TREATMENT_ID as SCAFFOLD_TREATMENT_ID,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
V1_CAMPAIGN_ID = (
    "procurement_allocation_glm53_flash_parasail_pre_award_check_v1"
)
CAMPAIGN_ID = "procurement_allocation_glm53_flash_parasail_pre_award_check_confirmatory_v3"
FROZEN_V4_PROMPT_SHA256 = FROZEN_TREATMENT_PROMPT_SHA256
FROZEN_SCAFFOLD_PROMPT_SHA256 = (
    "9a9e69f8a513e40499f83fe3648a316c49461645033ef009f43a2be3c515a813"
)
FROZEN_CONTROL_PROMPT_SHA256 = (
    "05dfee2fb708ac563e3503256ff43c1cb83b87d4bc28b238c05babcd512fb2df"
)
PARENT_EVIDENCE_PATH = (
    REPOSITORY_ROOT
    / "evidence"
    / "procurement_allocation_glm53_flash_parasail_pre_award_check_v1"
    / "publication_manifest.json"
)
PARENT_EVIDENCE_FILE_SHA256 = (
    "479fa73e746089475cca6760a0d88cb4cb5fc598c6aebba3cd1f776da202f858"
)
MASTER_SEED = 20260906
INFERENCE_SEEDS = tuple(
    derive_inference_seeds(
        master_seed=MASTER_SEED,
        count=3,
        campaign_id=V1_CAMPAIGN_ID,
    )
)
BOOTSTRAP_SEED = 20260906
BOOTSTRAP_RESAMPLES = 50_000
CONFIRMATORY_BATCH_SIZE = 12
CONFIRMATORY_MAX_PARALLEL_CELLS = 1
MAX_ACTION_ATTEMPTS = 4
RETRY_BASE_SECONDS = 15.0
CONFIRMATORY_RETRY_CONDITIONS = (*TRANSIENT_RETRY_CONDITIONS, "empty_response")
RETRY_BACKOFF = "exponential_jitter_v1"
RETRY_AFTER_MAX_SECONDS = 60.0
MAX_TRAJECTORY_COST_USD = 0.03
MAX_CANARY_COST_USD = 0.03
METRICS = (
    "feasible_award",
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
    "cost_accounting",
    "provider_call_count",
    "runner_retry_count",
    "retry_condition_counts",
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


def _arm_specs() -> dict[str, dict[str, Any]]:
    return {
        "labeled_control": {
            "surface": "labeled",
            "condition": "control",
            "case_paths": LABELED_PATHS,
            "prompt": SCAFFOLD_PROMPT,
            "prompt_id": SCAFFOLD_PROMPT_ID,
            "treatment_id": SCAFFOLD_TREATMENT_ID,
        },
        "opaque_control": {
            "surface": "opaque",
            "condition": "control",
            "case_paths": OPAQUE_PATHS,
            "prompt": SCAFFOLD_PROMPT,
            "prompt_id": SCAFFOLD_PROMPT_ID,
            "treatment_id": SCAFFOLD_TREATMENT_ID,
        },
        "labeled_treatment": {
            "surface": "labeled",
            "condition": "treatment",
            "case_paths": LABELED_PATHS,
            "prompt": STRATEGY_PROMPT,
            "prompt_id": V4_PROMPT_ID,
            "treatment_id": V4_TREATMENT_ID,
        },
        "opaque_treatment": {
            "surface": "opaque",
            "condition": "treatment",
            "case_paths": OPAQUE_PATHS,
            "prompt": STRATEGY_PROMPT,
            "prompt_id": V4_PROMPT_ID,
            "treatment_id": V4_TREATMENT_ID,
        },
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_frozen_sources() -> None:
    if hashlib.sha256(STRATEGY_PROMPT.encode()).hexdigest() != FROZEN_V4_PROMPT_SHA256:
        raise ValueError("frozen V4 treatment prompt changed; use a new campaign identity")
    if hashlib.sha256(SCAFFOLD_PROMPT.encode()).hexdigest() != FROZEN_SCAFFOLD_PROMPT_SHA256:
        raise ValueError("frozen control prompt changed; use a new campaign identity")
    if _sha256_file(PARENT_EVIDENCE_PATH) != PARENT_EVIDENCE_FILE_SHA256:
        raise ValueError("parent adaptive evidence manifest changed")


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


def _replace_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(canonical_json_bytes(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_once_text(path: Path, value: str) -> None:
    payload = value.encode()
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


def _case_record(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text())
    return {
        "case_id": raw["case_id"],
        "case_content_sha256": raw["content_sha256"],
        "world_seed": raw["world_seed"],
        "economic_world_sha256": economic_world_sha256(raw),
    }


def build_plan() -> dict[str, Any]:
    _assert_frozen_sources()
    specs = _arm_specs()
    arm_plans = {
        name: planned_model_qualification(
            case_paths=spec["case_paths"],
            inference_seeds=INFERENCE_SEEDS,
            max_parallel_cells=CONFIRMATORY_MAX_PARALLEL_CELLS,
            campaign_id=f"{CAMPAIGN_ID}.{name}",
            abort_on_operational_failure=True,
            candidate=GLM_PARASAIL_CANDIDATE,
            prompt=spec["prompt"],
            prompt_id=spec["prompt_id"],
            treatment_id=spec["treatment_id"],
            max_new_trajectories=CONFIRMATORY_BATCH_SIZE,
            max_action_attempts=MAX_ACTION_ATTEMPTS,
            retryable_conditions=CONFIRMATORY_RETRY_CONDITIONS,
            retry_backoff=RETRY_BACKOFF,
            retry_base_seconds=RETRY_BASE_SECONDS,
            retry_after_max_seconds=RETRY_AFTER_MAX_SECONDS,
        )
        for name, spec in specs.items()
    }
    labeled = [_case_record(path) for path in LABELED_PATHS]
    opaque = [_case_record(path) for path in OPAQUE_PATHS]
    world_pairs = []
    for slug, left, right in zip(CASE_SLUGS, labeled, opaque, strict=True):
        if (
            left["world_seed"] != right["world_seed"]
            or left["economic_world_sha256"] != right["economic_world_sha256"]
        ):
            raise ValueError(f"surface economics differ for {slug}")
        world_pairs.append(
            {
                "slug": slug,
                "world_seed": left["world_seed"],
                "economic_world_sha256": left["economic_world_sha256"],
                "labeled_case_id": left["case_id"],
                "labeled_case_content_sha256": left["case_content_sha256"],
                "opaque_case_id": right["case_id"],
                "opaque_case_content_sha256": right["case_content_sha256"],
            }
        )
    plan: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_pre_award_confirmatory_plan/0.1",
        "campaign_id": CAMPAIGN_ID,
        "freeze_status": "confirmatory_frozen_before_live_execution",
        "lineage": {
            "supersedes_campaign_id": V1_CAMPAIGN_ID,
            "v1_disposition": "sealed_ineligible_after_operational_failure",
            "scientific_contract": "unchanged_from_v1",
            "operational_changes_only": [
                "four action attempts with a 15s retry base after V1 was sealed "
                "twice by route rate limits before any panel row completed",
                "guard feasible_award rather than terminal feasibility, which "
                "counts an explicit defer as feasible",
                "retain billed usage for empty completions and failed trajectories",
                "retry empty_response within the existing three-attempt action bound",
            ],
        },
        "parent_adaptive_evidence": {
            "path": str(PARENT_EVIDENCE_PATH.relative_to(REPOSITORY_ROOT)),
            "file_sha256": PARENT_EVIDENCE_FILE_SHA256,
        },
        "candidate_id": GLM_PARASAIL_CANDIDATE.candidate_id,
        "model": GLM_PARASAIL_CANDIDATE.route.model,
        "revision": GLM_PARASAIL_CANDIDATE.route.revision,
        "provider": GLM_PARASAIL_CANDIDATE.route.route_provider,
        "quantization": GLM_PARASAIL_CANDIDATE.route.quantization,
        "prompts": {
            "control_prompt_id": SCAFFOLD_PROMPT_ID,
            "control_sha256": FROZEN_SCAFFOLD_PROMPT_SHA256,
            "treatment_prompt_id": V4_PROMPT_ID,
            "treatment_id": V4_TREATMENT_ID,
            "treatment_sha256": FROZEN_V4_PROMPT_SHA256,
        },
        "world_pairs": world_pairs,
        "independent_world_count": len(world_pairs),
        "inference_seeds": list(INFERENCE_SEEDS),
        "inference_seed_derivation_campaign_id": V1_CAMPAIGN_ID,
        "arm_execution_order": list(specs),
        "arms": arm_plans,
        "planned_trajectory_count": sum(
            int(arm["planned_trajectory_count"]) for arm in arm_plans.values()
        ),
        "max_parallel_cells": CONFIRMATORY_MAX_PARALLEL_CELLS,
        "batch_size": CONFIRMATORY_BATCH_SIZE,
        "abort_on_operational_failure": True,
        "admission_canaries": ["control", "treatment"],
        "admission_canaries_scored": False,
        "conservative_scored_cost_ceiling_usd": sum(
            float(arm["conservative_cost_ceiling_usd"])
            for arm in arm_plans.values()
        ),
        "conservative_total_cost_ceiling_usd": sum(
            float(arm["conservative_cost_ceiling_usd"])
            for arm in arm_plans.values()
        )
        + (2 * MAX_CANARY_COST_USD),
        "hard_scored_cost_ceiling_usd": sum(
            int(arm["planned_trajectory_count"]) * MAX_TRAJECTORY_COST_USD
            for arm in arm_plans.values()
        ),
        "hard_total_cost_ceiling_usd": sum(
            int(arm["planned_trajectory_count"]) * MAX_TRAJECTORY_COST_USD
            for arm in arm_plans.values()
        )
        + (2 * MAX_CANARY_COST_USD),
        "cost_accounting": {
            "successful_provider_calls": "exact, including empty completions",
            "failed_trajectories": "audited from the sealed event ledger",
            "unknown_provider_outcomes": "lower_bound, never coerced to zero",
        },
        "analysis": {
            "independent_unit": "economic world",
            "pairing": "condition within surface, then surfaces within world",
            "seed_aggregation": "mean three inference seeds within world and surface",
            "primary_estimand": (
                "treatment_minus_control regret_to_upper_bound_usd averaged equally "
                "over labeled and opaque surfaces within each world"
            ),
            "uncertainty": "deterministic percentile cluster bootstrap over worlds",
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "confirmation_rule": {
                "primary_regret_delta_bootstrap_upper_strictly_below_usd": 0.0,
                "overall_feasible_award_delta_bootstrap_lower_at_least": -0.05,
                "guarded_metric": "feasible_award, not terminal feasibility",
            },
            "secondary_outcomes": [
                "surface-specific feasibility, completed kits, margin, and regret",
                "presentation-surface difference in treatment effect",
                "violation, latency, token, retry, and cost diagnostics",
            ],
            "no_early_efficacy_stopping": True,
        },
        "eligibility": (
            "all 144 rows completed and receipt-replayed; route, revision, harness, "
            "retry policy, cases, seeds, prompts, upper bounds, and digests match"
        ),
        "claim_scope": (
            "held-out confirmation of the verifier-visible pre-award check against "
            "the frozen V4 scaffold on twelve curated synthetic procurement "
            "worlds, both arms on the same environment; not a population ranking"
        ),
    }
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return plan


async def _representative_request(*, prompt: str, prompt_id: str) -> ProviderRequest:
    setup = build_openrouter_setup(
        GLM_PARASAIL_CANDIDATE.route,
        case_path=LABELED_PATHS[0],
        seed=INFERENCE_SEEDS[0],
        max_output_tokens=1800,
        timeout_seconds=180.0,
        max_cost_usd=0.03,
        harness=MinimalChatHarness(),
        prompt=prompt,
        prompt_id=prompt_id,
        max_action_attempts=MAX_ACTION_ATTEMPTS,
        retryable_conditions=CONFIRMATORY_RETRY_CONDITIONS,
        retry_backoff=RETRY_BACKOFF,
        retry_base_seconds=RETRY_BASE_SECONDS,
        retry_after_max_seconds=RETRY_AFTER_MAX_SECONDS,
    )
    provider = SequenceResponseProvider(
        (json.dumps({"action": "defer", "reason": "request-shape capture"}),)
    )
    with tempfile.TemporaryDirectory(prefix="aeread-procurement-confirmatory-canary-") as root:
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
    *,
    path: Path,
    condition: str,
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
) -> dict[str, Any]:
    if condition not in {"control", "treatment"}:
        raise ValueError("canary condition must be control or treatment")
    prompt = SCAFFOLD_PROMPT if condition == "control" else STRATEGY_PROMPT
    prompt_id = SCAFFOLD_PROMPT_ID if condition == "control" else V4_PROMPT_ID
    request = await _representative_request(prompt=prompt, prompt_id=prompt_id)
    if path.exists():
        value = json.loads(path.read_text())
        recorded = value.get("artifact_sha256")
        payload = {key: item for key, item in value.items() if key != "artifact_sha256"}
        if recorded != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
            raise ValueError("admission canary digest mismatch")
        if (
            value.get("campaign_id") != CAMPAIGN_ID
            or value.get("condition") != condition
            or value.get("request_sha256") != request.request_sha256
        ):
            raise ValueError("admission canary identity mismatch")
        return value
    record: dict[str, Any] = {
        "schema_version": "aeread.provider_admission_canary/0.1",
        "campaign_id": CAMPAIGN_ID,
        "condition": condition,
        "attempted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "request_sha256": request.request_sha256,
        "prompt_id": prompt_id,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
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
        raise ValueError("qualification rows must be an array")
    for row in rows:
        recorded_row = row.get("result_sha256")
        row_payload = {key: item for key, item in row.items() if key != "result_sha256"}
        if recorded_row != hashlib.sha256(canonical_json_bytes(row_payload)).hexdigest():
            raise ValueError("qualification row digest mismatch")
    return value, hashlib.sha256(raw_bytes).hexdigest()


def _row_index(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, int], Mapping[str, Any]]:
    result: dict[tuple[str, int], Mapping[str, Any]] = {}
    for row in rows:
        key = (str(row["case_id"]).rsplit(".", 1)[-1], int(row["inference_seed"]))
        if key in result:
            raise ValueError(f"duplicate case/seed row: {key}")
        result[key] = row
    return result


def _metric(row: Mapping[str, Any], metric: str) -> float:
    return float(row.get("feasible") is True) if metric == "feasible" else float(row[metric])


def _bootstrap_interval(values: Sequence[float], *, label: str) -> list[float]:
    if len(values) != len(CASE_SLUGS):
        raise ValueError("bootstrap requires one value per confirmatory world")
    seed = int.from_bytes(
        hashlib.sha256(f"{BOOTSTRAP_SEED}:{label}".encode()).digest()[:8], "big"
    )
    rng = random.Random(seed)
    means = sorted(
        statistics.fmean(values[rng.randrange(len(values))] for _ in values)
        for _ in range(BOOTSTRAP_RESAMPLES)
    )
    return [
        means[int(0.025 * (len(means) - 1))],
        means[int(0.975 * (len(means) - 1))],
    ]


def _aggregate(values: Sequence[float], *, label: str) -> dict[str, Any]:
    return {
        "world_cluster_mean": statistics.fmean(values),
        "world_cluster_bootstrap_95_interval": _bootstrap_interval(values, label=label),
        "world_count": len(values),
    }


def build_confirmatory_comparison(*, run_root: Path) -> dict[str, Any]:
    expected_plan = build_plan()
    recorded_plan = json.loads((run_root / "campaign_plan.json").read_text())
    if canonical_json_bytes(recorded_plan) != canonical_json_bytes(expected_plan):
        raise ValueError("recorded campaign plan differs from frozen confirmatory plan")
    specs = _arm_specs()
    artifacts: dict[str, dict[str, Any]] = {}
    source: dict[str, Any] = {}
    integrity: dict[str, bool] = {}
    indexes: dict[str, dict[tuple[str, int], Mapping[str, Any]]] = {}
    route_fields = ("model", "revision", "provider", "quantization", "harness", "retry_policy")
    expected_keys = {(slug, seed) for slug in CASE_SLUGS for seed in INFERENCE_SEEDS}
    for name, spec in specs.items():
        artifact, file_sha = _verified_summary(
            run_root / "arms" / name, campaign_id=f"{CAMPAIGN_ID}.{name}"
        )
        artifacts[name] = artifact
        source[name] = {
            "summary_file_sha256": file_sha,
            "artifact_sha256": artifact["artifact_sha256"],
            "plan_sha256": artifact["plan"]["plan_sha256"],
        }
        index = _row_index(artifact["rows"])
        indexes[name] = index
        expected_prompt_sha = (
            FROZEN_SCAFFOLD_PROMPT_SHA256
            if spec["condition"] == "control"
            else FROZEN_V4_PROMPT_SHA256
        )
        integrity[f"{name}_model_plan_matches_frozen"] = (
            canonical_json_bytes(artifact["plan"])
            == canonical_json_bytes(expected_plan["arms"][name])
        )
        integrity[f"{name}_prompt_bound"] = artifact["plan"].get("prompt") == {
            "prompt_id": spec["prompt_id"],
            "sha256": expected_prompt_sha,
            "treatment_id": spec["treatment_id"],
        }
        expected_case_digests = {
            (slug, pair[f"{spec['surface']}_case_content_sha256"])
            for slug, pair in zip(CASE_SLUGS, expected_plan["world_pairs"], strict=True)
        }
        integrity[f"{name}_cases_bound"] = {
            (str(row["case_id"]).rsplit(".", 1)[-1], row["case_content_sha256"])
            for row in artifact["rows"]
        } == expected_case_digests
        integrity[f"{name}_all_pairs_present"] = set(index) == expected_keys
        integrity[f"{name}_execution_qualified"] = (
            artifact.get("summary", {}).get("readiness", {}).get("execution_qualified")
            is True
        )
        integrity[f"{name}_rows_completed_replayed_revision_pinned"] = all(
            row.get("status") == "completed"
            and row.get("receipt_replayed") is True
            and row.get("resolved_models") == [GLM_PARASAIL_CANDIDATE.route.revision]
            for row in artifact["rows"]
        )
    first_plan = artifacts["labeled_control"]["plan"]
    integrity["route_harness_and_retry_policy_match"] = all(
        artifact["plan"].get(field) == first_plan.get(field)
        for artifact in artifacts.values()
        for field in route_fields
    )
    integrity["seeds_match"] = all(
        artifact["plan"].get("inference_seeds") == list(INFERENCE_SEEDS)
        for artifact in artifacts.values()
    )

    surface_effects: dict[str, Any] = {}
    per_surface_world_delta: dict[str, dict[str, dict[str, float]]] = {}
    all_upper_bounds_match = True
    case_content_match = True
    for surface in ("labeled", "opaque"):
        control = indexes[f"{surface}_control"]
        treatment = indexes[f"{surface}_treatment"]
        metric_worlds: dict[str, dict[str, float]] = {metric: {} for metric in METRICS}
        transitions: Counter[str] = Counter()
        for slug in CASE_SLUGS:
            for seed in INFERENCE_SEEDS:
                left = control[(slug, seed)]
                right = treatment[(slug, seed)]
                case_content_match = case_content_match and (
                    left["case_content_sha256"] == right["case_content_sha256"]
                )
                all_upper_bounds_match = all_upper_bounds_match and (
                    float(left["upper_bound_usd"]) == float(right["upper_bound_usd"])
                )
                transitions[
                    f"{'pass' if left['feasible'] else 'fail'}_"
                    f"{'pass' if right['feasible'] else 'fail'}"
                ] += 1
            for metric in METRICS:
                metric_worlds[metric][slug] = statistics.fmean(
                    _metric(treatment[(slug, seed)], metric)
                    - _metric(control[(slug, seed)], metric)
                    for seed in INFERENCE_SEEDS
                )
        per_surface_world_delta[surface] = metric_worlds
        surface_effects[surface] = {
            "feasibility_transition_counts": dict(sorted(transitions.items())),
            "treatment_minus_control": {
                metric: _aggregate(
                    [metric_worlds[metric][slug] for slug in CASE_SLUGS],
                    label=f"{surface}:{metric}",
                )
                for metric in METRICS
            },
            "per_world_treatment_minus_control": {
                slug: {metric: metric_worlds[metric][slug] for metric in METRICS}
                for slug in CASE_SLUGS
            },
        }
    integrity["within_surface_case_content_match"] = case_content_match
    integrity["all_condition_upper_bounds_match"] = all_upper_bounds_match
    cross_surface_bounds = True
    for slug in CASE_SLUGS:
        for seed in INFERENCE_SEEDS:
            values = {
                float(indexes[name][(slug, seed)]["upper_bound_usd"])
                for name in specs
            }
            cross_surface_bounds = cross_surface_bounds and len(values) == 1
    integrity["cross_surface_upper_bounds_match"] = cross_surface_bounds
    integrity["economic_world_pairing_bound"] = len(
        {pair["economic_world_sha256"] for pair in recorded_plan["world_pairs"]}
    ) == len(CASE_SLUGS)

    overall_worlds = {
        metric: {
            slug: statistics.fmean(
                per_surface_world_delta[surface][metric][slug]
                for surface in ("labeled", "opaque")
            )
            for slug in CASE_SLUGS
        }
        for metric in METRICS
    }
    overall = {
        metric: _aggregate(
            [overall_worlds[metric][slug] for slug in CASE_SLUGS],
            label=f"overall:{metric}",
        )
        for metric in METRICS
    }
    surface_interaction = {
        metric: _aggregate(
            [
                per_surface_world_delta["opaque"][metric][slug]
                - per_surface_world_delta["labeled"][metric][slug]
                for slug in CASE_SLUGS
            ],
            label=f"surface_interaction:{metric}",
        )
        for metric in METRICS
    }
    eligible = all(integrity.values())
    primary_regret = overall["regret_to_upper_bound_usd"]
    # Guard feasible_award, not terminal feasibility: an explicit defer is
    # terminally feasible and earns nothing, so a treatment that defers more
    # could otherwise satisfy the guardrail while losing money.
    feasibility = overall["feasible_award"]
    confirmation_checks = {
        "primary_regret_upper_below_zero": (
            primary_regret["world_cluster_bootstrap_95_interval"][1] < 0.0
        ),
        "feasible_award_noninferiority_lower_at_least_minus_0_05": (
            feasibility["world_cluster_bootstrap_95_interval"][0] >= -0.05
        ),
    }
    confirmation_status = (
        "ineligible"
        if not eligible
        else "supported"
        if all(confirmation_checks.values())
        else "not_supported"
    )
    comparison: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_pre_award_confirmatory_comparison/0.1",
        "campaign_id": CAMPAIGN_ID,
        "integrity": integrity,
        "readiness": {"confirmatory_evidence_qualified": eligible},
        "confirmation": {
            "status": confirmation_status,
            "checks": confirmation_checks,
            "rule_was_frozen_before_execution": True,
        },
        "effects": {
            "overall_treatment_minus_control": overall,
            "by_surface": surface_effects,
            "opaque_minus_labeled_treatment_effect": surface_interaction,
            "per_world_overall_treatment_minus_control": {
                slug: {metric: overall_worlds[metric][slug] for metric in METRICS}
                for slug in CASE_SLUGS
            },
        },
        "bootstrap": {
            "independent_unit": "economic world",
            "world_count": len(CASE_SLUGS),
            "seed": BOOTSTRAP_SEED,
            "resamples": BOOTSTRAP_RESAMPLES,
        },
        "source": source,
        "interpretation": (
            "Support requires both the preregistered regret benefit and feasibility "
            "guardrail. Evidence eligibility never depends on favorable performance."
        ),
    }
    comparison["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(comparison)
    ).hexdigest()
    return comparison


def _execution_status(run_root: Path, canaries: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    arms: dict[str, Any] = {}
    completed = failures = row_count = 0
    scored_cost = 0.0
    for name in _arm_specs():
        summary_path = run_root / "arms" / name / "summary.json"
        if not summary_path.exists():
            arms[name] = {
                "status": "not_started",
                "planned_trajectory_count": len(CASE_SLUGS) * len(INFERENCE_SEEDS),
                "completed_trajectory_count": 0,
                "operational_failure_count": 0,
            }
            continue
        artifact = json.loads(summary_path.read_text())
        summary = artifact["summary"]
        completed += int(summary["completed_trajectory_count"])
        failures += int(summary["operational_failure_count"])
        row_count += int(summary["row_count"])
        scored_cost += float(summary["total_cost_usd"])
        arms[name] = {
            "status": (
                "qualified"
                if summary["readiness"]["execution_qualified"]
                else "operational_failure"
                if summary["operational_failure_count"]
                else "checkpoint"
            ),
            "artifact_sha256": artifact["artifact_sha256"],
            "planned_trajectory_count": summary["planned_trajectory_count"],
            "completed_trajectory_count": summary["completed_trajectory_count"],
            "operational_failure_count": summary["operational_failure_count"],
            "scored_cost_usd": summary["total_cost_usd"],
        }
    planned = len(_arm_specs()) * len(CASE_SLUGS) * len(INFERENCE_SEEDS)
    canary_cost = sum(float(item.get("cost_usd", 0.0)) for item in canaries.values())
    admitted = set(canaries) == {"control", "treatment"} and all(
        item.get("status") == "admitted" for item in canaries.values()
    )
    status: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_pre_award_confirmatory_status/0.1",
        "campaign_id": CAMPAIGN_ID,
        "canaries": dict(canaries),
        "arms": arms,
        "summary": {
            "planned_trajectory_count": planned,
            "row_count": row_count,
            "completed_trajectory_count": completed,
            "operational_failure_count": failures,
            "unattempted_trajectory_count": planned - row_count,
            "scored_cost_usd": scored_cost,
            "canary_cost_usd": canary_cost,
            "total_cost_including_canaries_usd": scored_cost + canary_cost,
            "execution_qualified": admitted and completed == planned and failures == 0,
            "failure_free_checkpoint": admitted and 0 < completed < planned and failures == 0,
        },
    }
    status["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(status)).hexdigest()
    return status


async def run_confirmatory_campaign(
    *,
    run_root: Path,
    max_spend_usd: float = 4.38,
    resume: bool = False,
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
    preflight_fn: Callable[[Any], Mapping[str, Any]] = preflight_candidate,
) -> dict[str, Any]:
    resolved = run_root.resolve()
    if "runs" not in resolved.parts or {"evidence", "output", "outputs"}.intersection(resolved.parts):
        raise ValueError("run_root must be under runs/ and outside publication paths")
    if run_root.exists() and not resume:
        raise FileExistsError("confirmatory output exists; pass --resume only after a failure-free checkpoint")
    if resume and not run_root.exists():
        raise FileNotFoundError("cannot resume a confirmatory campaign that does not exist")
    plan = build_plan()
    if float(plan["hard_total_cost_ceiling_usd"]) > max_spend_usd:
        raise ValueError("confirmatory hard ceiling exceeds max_spend_usd")
    plan_path = run_root / "campaign_plan.json"
    if plan_path.exists():
        if canonical_json_bytes(json.loads(plan_path.read_text())) != canonical_json_bytes(plan):
            raise ValueError("existing confirmatory plan does not match this invocation")
    else:
        _write_once_json(plan_path, plan)
    for name in _arm_specs():
        path = run_root / "arms" / name / "summary.json"
        if path.exists() and json.loads(path.read_text())["summary"]["operational_failure_count"]:
            raise ValueError("cannot resume an attempt containing an operational failure")
    canaries: dict[str, Mapping[str, Any]] = {}
    for condition in ("control", "treatment"):
        if canaries and any(item.get("status") != "admitted" for item in canaries.values()):
            break
        canaries[condition] = await run_admission_canary(
            path=run_root / "canaries" / f"{condition}.json",
            condition=condition,
            provider_factory=provider_factory,
        )
    if set(canaries) == {"control", "treatment"} and all(
        item.get("status") == "admitted" for item in canaries.values()
    ):
        preflight = dict(preflight_fn(GLM_PARASAIL_CANDIDATE))
        remaining_batch = CONFIRMATORY_BATCH_SIZE
        for name, spec in _arm_specs().items():
            arm_root = run_root / "arms" / name
            prior_count = 0
            summary_path = arm_root / "summary.json"
            if summary_path.exists():
                prior = json.loads(summary_path.read_text())
                prior_count = int(prior["summary"]["row_count"])
                if prior["summary"]["readiness"]["execution_qualified"]:
                    continue
            if remaining_batch < 1:
                break
            artifact = await run_model_qualification(
                run_root=arm_root,
                case_paths=spec["case_paths"],
                inference_seeds=INFERENCE_SEEDS,
                max_spend_usd=max_spend_usd,
                max_parallel_cells=CONFIRMATORY_MAX_PARALLEL_CELLS,
                resume=arm_root.exists(),
                provider_factory=provider_factory,
                preflight_fn=lambda _candidate: preflight,
                campaign_id=f"{CAMPAIGN_ID}.{name}",
                abort_on_operational_failure=True,
                candidate=GLM_PARASAIL_CANDIDATE,
                prompt=spec["prompt"],
                prompt_id=spec["prompt_id"],
                treatment_id=spec["treatment_id"],
                max_new_trajectories=remaining_batch,
                max_action_attempts=MAX_ACTION_ATTEMPTS,
                retryable_conditions=CONFIRMATORY_RETRY_CONDITIONS,
                retry_backoff=RETRY_BACKOFF,
                retry_base_seconds=RETRY_BASE_SECONDS,
                retry_after_max_seconds=RETRY_AFTER_MAX_SECONDS,
            )
            new_count = int(artifact["summary"]["row_count"]) - prior_count
            remaining_batch -= new_count
            if artifact["summary"]["operational_failure_count"]:
                break
    status = _execution_status(run_root, canaries)
    _replace_json(run_root / "campaign_status.json", status)
    if status["summary"]["execution_qualified"]:
        comparison = build_confirmatory_comparison(run_root=run_root)
        _write_once_json(run_root / "confirmatory_comparison.json", comparison)
        status = {**status, "comparison": comparison}
    return status


def _sanitized_arm(*, run_root: Path, name: str) -> dict[str, Any]:
    artifact, file_sha = _verified_summary(
        run_root / "arms" / name, campaign_id=f"{CAMPAIGN_ID}.{name}"
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
        "schema_version": "aeread.procurement_allocation_pre_award_confirmatory_arm_review/0.1",
        "campaign_id": f"{CAMPAIGN_ID}.{name}",
        "arm": name,
        "source": {
            "raw_summary_path": (
                f"runs/procurement_allocation/{CAMPAIGN_ID}/{run_root.name}/"
                f"arms/{name}/summary.json"
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


def _verified_canary(path: Path, *, condition: str) -> dict[str, Any]:
    value = json.loads(path.read_text())
    recorded = value.get("artifact_sha256")
    payload = {key: item for key, item in value.items() if key != "artifact_sha256"}
    expected_prompt_sha = (
        FROZEN_SCAFFOLD_PROMPT_SHA256
        if condition == "control"
        else FROZEN_V4_PROMPT_SHA256
    )
    expected_prompt_id = (
        SCAFFOLD_PROMPT_ID if condition == "control" else V4_PROMPT_ID
    )
    if recorded != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
        raise ValueError("admission canary digest mismatch")
    if (
        value.get("campaign_id") != CAMPAIGN_ID
        or value.get("condition") != condition
        or value.get("status") != "admitted"
        or value.get("scored") is not False
        or value.get("prompt_id") != expected_prompt_id
        or value.get("prompt_sha256") != expected_prompt_sha
        or value.get("model") != GLM_PARASAIL_CANDIDATE.route.model
        or value.get("revision") != GLM_PARASAIL_CANDIDATE.route.revision
        or value.get("route_provider") != GLM_PARASAIL_CANDIDATE.route.route_provider
        or value.get("resolved_model") != GLM_PARASAIL_CANDIDATE.route.revision
    ):
        raise ValueError("admission canary identity or admission state mismatch")
    return value


def publish_confirmatory_campaign(
    *, run_root: Path, publication_root: Path
) -> dict[str, Any]:
    if publication_root.resolve().parent.name != "evidence":
        raise ValueError("publication_root must be one direct evidence/ bundle")
    comparison = build_confirmatory_comparison(run_root=run_root)
    if not comparison["readiness"]["confirmatory_evidence_qualified"]:
        raise ValueError("confirmatory evidence is not qualified")
    artifacts: dict[str, str] = {}
    for name in _arm_specs():
        review = _sanitized_arm(run_root=run_root, name=name)
        review["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(review)).hexdigest()
        relative = f"reports/{name}.json"
        path = publication_root / relative
        _write_once_json(path, review)
        artifacts[relative] = _sha256_file(path)
    comparison_path = publication_root / "reports" / "confirmatory_effects.json"
    _write_once_json(comparison_path, comparison)
    artifacts["reports/confirmatory_effects.json"] = _sha256_file(comparison_path)
    for condition in ("control", "treatment"):
        source = run_root / "canaries" / f"{condition}.json"
        canary = _verified_canary(source, condition=condition)
        relative = f"reports/{condition}_admission_canary.json"
        path = publication_root / relative
        _write_once_json(path, canary)
        artifacts[relative] = _sha256_file(path)
    plan = json.loads((run_root / "campaign_plan.json").read_text())
    plan_path = publication_root / "tables" / "frozen_plan.json"
    _write_once_json(plan_path, plan)
    artifacts["tables/frozen_plan.json"] = _sha256_file(plan_path)
    manifest: dict[str, Any] = {
        "schema_version": "aeread.publication_manifest/0.1",
        "publication_id": CAMPAIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "confirmation_status": comparison["confirmation"]["status"],
        "artifacts": artifacts,
        "source_bindings": {
            "campaign_plan_sha256": plan["plan_sha256"],
            "comparison_artifact_sha256": comparison["artifact_sha256"],
            "implementation_sha256": _sha256_file(Path(__file__)),
            "parent_evidence_file_sha256": PARENT_EVIDENCE_FILE_SHA256,
        },
        "privacy_boundary": {
            "included": (
                "prompt hashes, public action traces, outcomes, typed failures, "
                "usage, cost, and receipt/result digests"
            ),
            "excluded": (
                "full prompts, observations, provider payloads, event logs, hidden "
                "supplier terms, and account metadata"
            ),
        },
    }
    manifest["manifest_sha256"] = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    _write_once_json(publication_root / "publication_manifest.json", manifest)
    _write_once_text(
        publication_root / "README.md",
        f"# {CAMPAIGN_ID}\n\n"
        "Sanitized, digest-bound evidence for the frozen procurement strategy "
        "confirmation. Raw provider state remains under ignored `runs/`.\n",
    )
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument("--max-spend-usd", type=float, default=4.38)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--publish-only", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.execute and arguments.publish_only:
        parser.error("--execute and --publish-only are mutually exclusive")
    if arguments.publish_only:
        if arguments.publication_root is None:
            parser.error("--publish-only requires --publication-root")
        manifest = publish_confirmatory_campaign(
            run_root=arguments.run_root,
            publication_root=arguments.publication_root,
        )
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    if not arguments.execute:
        print(
            json.dumps(
                build_plan(),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    status = asyncio.run(
        run_confirmatory_campaign(
            run_root=arguments.run_root,
            max_spend_usd=arguments.max_spend_usd,
            resume=arguments.resume,
        )
    )
    print(json.dumps(status, indent=2, sort_keys=True))
    if status["summary"]["execution_qualified"]:
        return 0
    if status["summary"]["operational_failure_count"]:
        return 2
    if not status["summary"]["failure_free_checkpoint"]:
        return 3
    return 4


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BOOTSTRAP_RESAMPLES",
    "CAMPAIGN_ID",
    "CONFIRMATORY_RETRY_CONDITIONS",
    "CONFIRMATORY_BATCH_SIZE",
    "CONFIRMATORY_MAX_PARALLEL_CELLS",
    "FROZEN_CONTROL_PROMPT_SHA256",
    "FROZEN_V4_PROMPT_SHA256",
    "INFERENCE_SEEDS",
    "V1_CAMPAIGN_ID",
    "build_confirmatory_comparison",
    "build_plan",
    "publish_confirmatory_campaign",
    "run_admission_canary",
    "run_confirmatory_campaign",
]
