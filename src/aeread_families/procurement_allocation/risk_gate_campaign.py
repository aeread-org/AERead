"""Held-out 2x2 prompt-factorial for procurement decision risk gates.

The fixed model and transport are not estimands.  The adaptive campaign tests
whether explicit sample-schedule and landed-cash checks improve decisions over
the frozen V4 procurement strategy on six new paired economic worlds.
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
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from aeread.shared_runner.model_call.harness import MinimalChatHarness
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import (
    OpenRouterChatClient,
    ProviderFailure,
    ProviderRequest,
    execute_plan_cell,
)
from aeread_families.procurement_grounding.bakeoff import preflight_candidate

from .confirmatory_campaign import INFERENCE_SEEDS as CONFIRMATORY_INFERENCE_SEEDS
from .model_campaign import (
    TRANSIENT_RETRY_CONDITIONS,
    derive_inference_seeds,
    planned_model_qualification,
    run_model_qualification,
)
from .risk_gate_case_matrix import (
    CASE_SLUGS,
    LABELED_PATHS,
    OPAQUE_PATHS,
    STRATA_BY_SLUG,
    economic_world_sha256,
)
from .runner import SequenceResponseProvider, build_openrouter_setup
from .strategy_scaffold import (
    GLM_PARASAIL_CANDIDATE,
    PARASAIL_INFERENCE_SEEDS,
    PROMPT_ID as V4_PROMPT_ID,
    STRATEGY_PROMPT,
    TREATMENT_ID as V4_TREATMENT_ID,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
V1_CAMPAIGN_ID = "procurement_allocation_glm53_flash_parasail_risk_gate_factorial_v1"
V2_CAMPAIGN_ID = "procurement_allocation_glm53_flash_parasail_risk_gate_factorial_v2"
CAMPAIGN_ID = "procurement_allocation_glm53_flash_parasail_risk_gate_factorial_v3"
PARENT_EVIDENCE_PATH = (
    REPOSITORY_ROOT
    / "evidence"
    / "procurement_allocation_glm53_flash_parasail_strategy_confirmatory_v2"
    / "publication_manifest.json"
)
PARENT_EVIDENCE_FILE_SHA256 = (
    "ec07cef61aa1a2f16b80e3fcddc0f63a20ea3a47c9fbd4fb83ccf625680a0146"
)
FROZEN_V4_PROMPT_SHA256 = (
    "9a9e69f8a513e40499f83fe3648a316c49461645033ef009f43a2be3c515a813"
)
MASTER_SEED = 20260903
INFERENCE_SEEDS = derive_inference_seeds(
    master_seed=MASTER_SEED,
    count=3,
    campaign_id=V1_CAMPAIGN_ID,
)
BOOTSTRAP_SEED = 20260903
BOOTSTRAP_RESAMPLES = 50_000
TRAJECTORIES_PER_ARM_PER_CHECKPOINT = 3
MAX_PARALLEL_CELLS = 1
MAX_ACTION_ATTEMPTS = 3
RETRY_CONDITIONS = (*TRANSIENT_RETRY_CONDITIONS, "empty_response")
RETRY_BACKOFF = "exponential_jitter_v1"
RETRY_BASE_SECONDS = 15.0
RETRY_AFTER_MAX_SECONDS = 60.0
INTER_CANARY_DELAY_SECONDS = 10.0
MAX_TRAJECTORY_COST_USD = 0.02
MAX_CANARY_COST_USD = 0.02
CONDITIONS = ("v4", "temporal", "cash", "joint")
SURFACES = ("labeled", "opaque")
METRICS = (
    "feasible",
    "completed_kits",
    "contribution_margin_usd",
    "regret_to_upper_bound_usd",
    "defer_rate",
)

TEMPORAL_GATE = """

Additional sample-schedule gate:
- Apply this gate only when `sample_logistics` is an allowed inquiry field. The
  listing and formal offer do not disclose sample turnaround. Before committing
  to samples, use `inquire` with field `sample_logistics` for every plausible
  candidate whose sample you may need; never infer speed from a supplier name or
  ID.
- Treat interactions and sample turnarounds as serial. From the current elapsed
  day, sum all remaining inquiry days, quote days, sample turnaround days, and
  any counter days, then add the slowest selected offer lead time. The resulting
  arrival day must not exceed the deadline.
- If the low-price candidates fail that critical-path check, qualify faster-sample
  candidates even when their unit prices are higher. Do not request a sample from
  a candidate that cannot fit the remaining schedule.

Return only the next JSON action, never this analysis.
"""

CASH_GATE = """

Additional landed-cash gate:
- After formal quotes arrive, compute each proposed line at its actual rounded
  quantity: quantity * (unit_price_usd + shipping_per_unit_usd) *
  (1 + duty_rate). Use the quantity required by BOM multiplicity, MOQ, order step,
  and capacity; displayed price is not this value.
- Sum every line plus already-incurred information cost and compare the total with
  cash_budget_usd before requesting samples or submitting an award. Reject a
  low-sticker offer when freight, duty, or MOQ makes the combined allocation exceed
  cash. Prefer a feasible landed-cash allocation over a cheaper-looking listing.

Return only the next JSON action, never this analysis.
"""

TEMPORAL_PROMPT = STRATEGY_PROMPT + TEMPORAL_GATE
CASH_PROMPT = STRATEGY_PROMPT + CASH_GATE
JOINT_PROMPT = STRATEGY_PROMPT + TEMPORAL_GATE + CASH_GATE
PROMPTS = {
    "v4": {
        "prompt": STRATEGY_PROMPT,
        "prompt_id": V4_PROMPT_ID,
        "treatment_id": V4_TREATMENT_ID,
    },
    "temporal": {
        "prompt": TEMPORAL_PROMPT,
        "prompt_id": "procurement_allocation_risk_gate_temporal_v1",
        "treatment_id": "sample_schedule_gate_v1",
    },
    "cash": {
        "prompt": CASH_PROMPT,
        "prompt_id": "procurement_allocation_risk_gate_cash_v1",
        "treatment_id": "landed_cash_gate_v1",
    },
    "joint": {
        "prompt": JOINT_PROMPT,
        "prompt_id": "procurement_allocation_risk_gate_joint_v1",
        "treatment_id": "sample_schedule_and_landed_cash_gates_v1",
    },
}
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
    specs: dict[str, dict[str, Any]] = {}
    for surface, paths in (("labeled", LABELED_PATHS), ("opaque", OPAQUE_PATHS)):
        for condition in CONDITIONS:
            specs[f"{surface}_{condition}"] = {
                "surface": surface,
                "condition": condition,
                "case_paths": paths,
                **PROMPTS[condition],
            }
    return specs


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_frozen_sources() -> None:
    if hashlib.sha256(STRATEGY_PROMPT.encode()).hexdigest() != FROZEN_V4_PROMPT_SHA256:
        raise ValueError("frozen V4 prompt changed; use a new campaign identity")
    if _sha256_file(PARENT_EVIDENCE_PATH) != PARENT_EVIDENCE_FILE_SHA256:
        raise ValueError("parent confirmatory evidence manifest changed")


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
    raw = json.loads(path.read_text(encoding="utf-8"))
    slug = str(raw["case_id"]).rsplit(".", 1)[-1]
    return {
        "slug": slug,
        "stratum": STRATA_BY_SLUG[slug],
        "case_id": raw["case_id"],
        "case_content_sha256": raw["content_sha256"],
        "world_seed": raw["world_seed"],
        "economic_world_sha256": economic_world_sha256(raw),
    }


def build_plan() -> dict[str, Any]:
    _assert_frozen_sources()
    if set(INFERENCE_SEEDS).intersection(
        (*PARASAIL_INFERENCE_SEEDS, *CONFIRMATORY_INFERENCE_SEEDS)
    ):
        raise ValueError("risk-gate inference seeds overlap a prior procurement campaign")
    specs = _arm_specs()
    arm_plans = {
        name: planned_model_qualification(
            case_paths=spec["case_paths"],
            inference_seeds=INFERENCE_SEEDS,
            max_parallel_cells=MAX_PARALLEL_CELLS,
            campaign_id=f"{CAMPAIGN_ID}.{name}",
            abort_on_operational_failure=True,
            candidate=GLM_PARASAIL_CANDIDATE,
            prompt=spec["prompt"],
            prompt_id=spec["prompt_id"],
            treatment_id=spec["treatment_id"],
            max_new_trajectories=TRAJECTORIES_PER_ARM_PER_CHECKPOINT,
            max_action_attempts=MAX_ACTION_ATTEMPTS,
            retryable_conditions=RETRY_CONDITIONS,
            retry_backoff=RETRY_BACKOFF,
            retry_base_seconds=RETRY_BASE_SECONDS,
            retry_after_max_seconds=RETRY_AFTER_MAX_SECONDS,
            max_cost_usd_per_trajectory=MAX_TRAJECTORY_COST_USD,
        )
        for name, spec in specs.items()
    }
    labeled = [_case_record(path) for path in LABELED_PATHS]
    opaque = [_case_record(path) for path in OPAQUE_PATHS]
    world_pairs: list[dict[str, Any]] = []
    for slug, left, right in zip(CASE_SLUGS, labeled, opaque, strict=True):
        if (
            left["slug"] != slug
            or right["slug"] != slug
            or left["world_seed"] != right["world_seed"]
            or left["economic_world_sha256"] != right["economic_world_sha256"]
        ):
            raise ValueError(f"surface economics differ for {slug}")
        world_pairs.append(
            {
                "slug": slug,
                "stratum": STRATA_BY_SLUG[slug],
                "world_seed": left["world_seed"],
                "economic_world_sha256": left["economic_world_sha256"],
                "labeled_case_id": left["case_id"],
                "labeled_case_content_sha256": left["case_content_sha256"],
                "opaque_case_id": right["case_id"],
                "opaque_case_content_sha256": right["case_content_sha256"],
            }
        )
    scored_hard_decimal = sum(
        (
            Decimal(int(arm["planned_trajectory_count"]))
            * Decimal(str(MAX_TRAJECTORY_COST_USD))
            for arm in arm_plans.values()
        ),
        start=Decimal("0"),
    )
    scored_conservative_decimal = sum(
        (
            Decimal(str(arm["conservative_cost_ceiling_usd"]))
            for arm in arm_plans.values()
        ),
        start=Decimal("0"),
    )
    canary_ceiling_decimal = Decimal(len(CONDITIONS)) * Decimal(
        str(MAX_CANARY_COST_USD)
    )
    scored_hard = float(scored_hard_decimal)
    scored_conservative = float(scored_conservative_decimal)
    plan: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_risk_gate_plan/0.1",
        "campaign_id": CAMPAIGN_ID,
        "freeze_status": "adaptive_mechanism_plan_frozen_before_live_execution",
        "lineage": {
            "supersedes_campaign_id": V2_CAMPAIGN_ID,
            "v1_disposition": (
                "sealed_ineligible_after_rate_limit_failure; later fresh attempts "
                "rejected by admission canaries"
            ),
            "v2_disposition": (
                "sealed_ineligible_after_provider-returned_malformed_structured_text "
                "was misclassified as provider_contract"
            ),
            "scientific_contract": "unchanged_from_v1_and_v2",
            "operational_changes_only": [
                "preserve nonempty provider-returned malformed structured text as a "
                "billable model response for family-level scoring",
                "make admission canaries transport-only so malformed model content "
                "cannot selectively gate scored execution",
            ],
            "parent_campaign_id": (
                "procurement_allocation_glm53_flash_parasail_strategy_confirmatory_v2"
            ),
            "parent_evidence_path": str(
                PARENT_EVIDENCE_PATH.relative_to(REPOSITORY_ROOT)
            ),
            "parent_evidence_file_sha256": PARENT_EVIDENCE_FILE_SHA256,
            "adaptation_basis": (
                "post-confirmation error audit identified sample critical-path and "
                "landed-cash arithmetic failures"
            ),
        },
        "candidate_id": GLM_PARASAIL_CANDIDATE.candidate_id,
        "model": GLM_PARASAIL_CANDIDATE.route.model,
        "revision": GLM_PARASAIL_CANDIDATE.route.revision,
        "provider": GLM_PARASAIL_CANDIDATE.route.route_provider,
        "quantization": GLM_PARASAIL_CANDIDATE.route.quantization,
        "prompt_factorial": {
            condition: {
                "prompt_id": PROMPTS[condition]["prompt_id"],
                "treatment_id": PROMPTS[condition]["treatment_id"],
                "sha256": hashlib.sha256(PROMPTS[condition]["prompt"].encode()).hexdigest(),
                "temporal_gate": condition in {"temporal", "joint"},
                "cash_gate": condition in {"cash", "joint"},
            }
            for condition in CONDITIONS
        },
        "world_pairs": world_pairs,
        "independent_world_count": len(world_pairs),
        "stratum_world_counts": dict(sorted(Counter(STRATA_BY_SLUG.values()).items())),
        "inference_seeds": list(INFERENCE_SEEDS),
        "arm_execution_order": list(specs),
        "checkpoint_schedule": (
            "one economic world per invocation: three seeds in every surface-condition arm"
        ),
        "inter_canary_delay_seconds": INTER_CANARY_DELAY_SECONDS,
        "arms": arm_plans,
        "planned_trajectory_count": sum(
            int(arm["planned_trajectory_count"]) for arm in arm_plans.values()
        ),
        "max_parallel_cells": MAX_PARALLEL_CELLS,
        "trajectories_per_arm_per_checkpoint": TRAJECTORIES_PER_ARM_PER_CHECKPOINT,
        "abort_on_operational_failure": True,
        "admission_canaries": list(CONDITIONS),
        "admission_canaries_scored": False,
        "conservative_scored_cost_ceiling_usd": scored_conservative,
        "conservative_total_cost_ceiling_usd": float(
            scored_conservative_decimal + canary_ceiling_decimal
        ),
        "hard_scored_cost_ceiling_usd": scored_hard,
        "hard_total_cost_ceiling_usd": float(
            scored_hard_decimal + canary_ceiling_decimal
        ),
        "analysis": {
            "status": "adaptive_exploratory_not_confirmatory",
            "independent_unit": "economic world",
            "seed_aggregation": "mean three inference seeds within world and surface",
            "surface_aggregation": "equal mean of labeled and opaque surfaces",
            "simple_contrasts": [
                "temporal_minus_v4",
                "cash_minus_v4",
                "joint_minus_v4",
            ],
            "factorial_contrasts": [
                "temporal_main_effect",
                "cash_main_effect",
                "temporal_by_cash_interaction",
            ],
            "uncertainty": (
                "deterministic percentile cluster bootstrap over worlds; exploratory"
            ),
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "progression_rule": {
                "joint_regret_delta_mean_overall_strictly_below_usd": 0.0,
                "joint_regret_delta_mean_each_stratum_at_most_usd": 0.0,
                "joint_feasibility_delta_mean_overall_and_each_stratum_at_least": 0.0,
                "joint_completed_kits_delta_mean_overall_and_each_stratum_at_least": 0.0,
                "joint_defer_rate_delta_mean_overall_and_each_stratum_at_most": 0.0,
            },
            "specialization_diagnostics_are_nonbinding": True,
            "no_early_efficacy_stopping": True,
        },
        "eligibility": (
            "all 144 rows completed and receipt-replayed with exact cost accounting; "
            "route, revision, prompts, cases, seeds, upper bounds, and digests match"
        ),
        "claim_scope": (
            "adaptive mechanism selection on six held-out curated synthetic worlds; "
            "not confirmation and not a population model ranking"
        ),
    }
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return plan


async def _representative_request(*, condition: str) -> ProviderRequest:
    prompt = PROMPTS[condition]
    setup = build_openrouter_setup(
        GLM_PARASAIL_CANDIDATE.route,
        case_path=LABELED_PATHS[0],
        seed=INFERENCE_SEEDS[0],
        max_output_tokens=1800,
        timeout_seconds=180.0,
        max_cost_usd=MAX_CANARY_COST_USD,
        harness=MinimalChatHarness(),
        prompt=prompt["prompt"],
        prompt_id=prompt["prompt_id"],
        max_action_attempts=MAX_ACTION_ATTEMPTS,
        retryable_conditions=RETRY_CONDITIONS,
        retry_backoff=RETRY_BACKOFF,
        retry_base_seconds=RETRY_BASE_SECONDS,
        retry_after_max_seconds=RETRY_AFTER_MAX_SECONDS,
    )
    provider = SequenceResponseProvider(
        (json.dumps({"action": "defer", "reason": "request-shape capture"}),)
    )
    with tempfile.TemporaryDirectory(prefix="aeread-procurement-risk-gate-canary-") as root:
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
    if condition not in CONDITIONS:
        raise ValueError(f"unknown canary condition: {condition}")
    prompt = PROMPTS[condition]
    request = await _representative_request(condition=condition)
    if path.exists():
        value = json.loads(path.read_text(encoding="utf-8"))
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
        "schema_version": "aeread.provider_admission_canary/0.4",
        "campaign_id": CAMPAIGN_ID,
        "condition": condition,
        "attempted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "request_sha256": request.request_sha256,
        "prompt_id": prompt["prompt_id"],
        "prompt_sha256": hashlib.sha256(prompt["prompt"].encode()).hexdigest(),
        "model": request.model,
        "revision": request.revision,
        "route_provider": request.provider_metadata["route_provider"],
        "max_output_tokens": request.max_output_tokens,
        "max_cost_usd": request.max_cost_usd,
        "scored": False,
    }
    provider = provider_factory()
    calls = input_tokens = cached_input_tokens = output_tokens = 0
    cost_usd = 0.0
    retry_counts: Counter[str] = Counter()
    cost_accounting = "exact"
    for ordinal in range(MAX_ACTION_ATTEMPTS):
        calls += 1
        try:
            result = await provider.complete(request)
            input_tokens += result.input_tokens
            cached_input_tokens += result.cached_input_tokens
            output_tokens += result.output_tokens
            cost_usd += result.cost_usd
            if not result.output_text.strip():
                raise ProviderFailure(
                    "empty_response",
                    "admission canary received an empty completion",
                    retryable=True,
                )
            try:
                action = json.loads(result.output_text)
            except json.JSONDecodeError:
                action = None
                output_contract_status = "malformed_json"
            else:
                output_contract_status = (
                    "valid_structured_action"
                    if isinstance(action, Mapping)
                    and isinstance(action.get("action"), str)
                    else "invalid_action_shape"
                )
            record.update(
                {
                    "status": "admitted",
                    "resolved_model": result.resolved_model,
                    "finish_reason": result.finish_reason,
                    "output_contract_status": output_contract_status,
                    "structured_action": (
                        action["action"]
                        if output_contract_status == "valid_structured_action"
                        else None
                    ),
                }
            )
            break
        except Exception as error:
            failure = _failure_fields(error)
            retryable = (
                failure["failure_condition"] in RETRY_CONDITIONS
                and ordinal + 1 < MAX_ACTION_ATTEMPTS
            )
            if retryable:
                retry_counts[failure["failure_condition"]] += 1
                await asyncio.sleep(
                    min(30.0, RETRY_BASE_SECONDS * (2**ordinal))
                )
                continue
            if failure["failure_condition"] not in {
                "rate_limit",
                "provider_5xx",
                "empty_response",
            }:
                cost_accounting = "unavailable"
            record.update({"status": "rejected", **failure})
            break
    record.update(
        {
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "cost_accounting": cost_accounting,
            "provider_call_count": calls,
            "runner_retry_count": sum(retry_counts.values()),
            "retry_condition_counts": dict(sorted(retry_counts.items())),
            "retry_base_seconds": RETRY_BASE_SECONDS,
        }
    )
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
        return float(row.get("feasible") is True)
    if metric == "defer_rate":
        return float(row.get("decision") == "defer")
    return float(row[metric])


def _bootstrap_interval(values: Sequence[float], *, label: str) -> list[float]:
    if not values:
        raise ValueError("bootstrap requires at least one world")
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


def _aggregate_world_map(
    values: Mapping[str, float], *, label: str
) -> dict[str, Any]:
    return _aggregate(
        [values[slug] for slug in CASE_SLUGS if slug in values],
        label=label,
    )


def build_risk_gate_comparison(*, run_root: Path) -> dict[str, Any]:
    expected_plan = build_plan()
    recorded_plan = json.loads((run_root / "campaign_plan.json").read_text())
    if canonical_json_bytes(recorded_plan) != canonical_json_bytes(expected_plan):
        raise ValueError("recorded campaign plan differs from frozen risk-gate plan")
    specs = _arm_specs()
    artifacts: dict[str, dict[str, Any]] = {}
    indexes: dict[str, dict[tuple[str, int], Mapping[str, Any]]] = {}
    source: dict[str, Any] = {}
    integrity: dict[str, bool] = {}
    expected_keys = {(slug, seed) for slug in CASE_SLUGS for seed in INFERENCE_SEEDS}
    route_fields = ("model", "revision", "provider", "quantization", "harness", "retry_policy")
    for name, spec in specs.items():
        artifact, file_sha = _verified_summary(
            run_root / "arms" / name,
            campaign_id=f"{CAMPAIGN_ID}.{name}",
        )
        artifacts[name] = artifact
        indexes[name] = _row_index(artifact["rows"])
        source[name] = {
            "summary_file_sha256": file_sha,
            "artifact_sha256": artifact["artifact_sha256"],
            "plan_sha256": artifact["plan"]["plan_sha256"],
        }
        integrity[f"{name}_model_plan_matches_frozen"] = (
            canonical_json_bytes(artifact["plan"])
            == canonical_json_bytes(expected_plan["arms"][name])
        )
        integrity[f"{name}_all_pairs_present"] = set(indexes[name]) == expected_keys
        integrity[f"{name}_execution_qualified"] = (
            artifact.get("summary", {}).get("readiness", {}).get("execution_qualified")
            is True
        )
        integrity[f"{name}_rows_completed_replayed_exact_cost"] = all(
            row.get("status") == "completed"
            and row.get("receipt_replayed") is True
            and row.get("cost_accounting") == "exact"
            and row.get("resolved_models") == [GLM_PARASAIL_CANDIDATE.route.revision]
            for row in artifact["rows"]
        )
        pair_by_slug = {pair["slug"]: pair for pair in expected_plan["world_pairs"]}
        integrity[f"{name}_cases_bound"] = all(
            row.get("case_content_sha256")
            == pair_by_slug[slug][f"{spec['surface']}_case_content_sha256"]
            for (slug, _), row in indexes[name].items()
        )
    first_plan = artifacts[next(iter(specs))]["plan"]
    integrity["route_harness_retry_match"] = all(
        artifact["plan"].get(field) == first_plan.get(field)
        for artifact in artifacts.values()
        for field in route_fields
    )
    integrity["seeds_match"] = all(
        artifact["plan"].get("inference_seeds") == list(INFERENCE_SEEDS)
        for artifact in artifacts.values()
    )

    upper_bounds_match = True
    for slug in CASE_SLUGS:
        for seed in INFERENCE_SEEDS:
            values = {
                float(indexes[name][(slug, seed)]["upper_bound_usd"])
                for name in specs
            }
            upper_bounds_match = upper_bounds_match and len(values) == 1
    integrity["all_arm_upper_bounds_match"] = upper_bounds_match
    integrity["economic_world_pairing_bound"] = len(
        {pair["economic_world_sha256"] for pair in expected_plan["world_pairs"]}
    ) == len(CASE_SLUGS)

    world_arm_means: dict[str, dict[str, dict[str, float]]] = {
        condition: {metric: {} for metric in METRICS} for condition in CONDITIONS
    }
    surface_arm_means: dict[str, dict[str, dict[str, dict[str, float]]]] = {
        surface: {
            condition: {metric: {} for metric in METRICS}
            for condition in CONDITIONS
        }
        for surface in SURFACES
    }
    for surface in SURFACES:
        for condition in CONDITIONS:
            index = indexes[f"{surface}_{condition}"]
            for metric in METRICS:
                for slug in CASE_SLUGS:
                    surface_arm_means[surface][condition][metric][slug] = (
                        statistics.fmean(
                            _metric(index[(slug, seed)], metric)
                            for seed in INFERENCE_SEEDS
                        )
                    )
    for condition in CONDITIONS:
        for metric in METRICS:
            for slug in CASE_SLUGS:
                world_arm_means[condition][metric][slug] = statistics.fmean(
                    surface_arm_means[surface][condition][metric][slug]
                    for surface in SURFACES
                )

    def contrast(
        *,
        name: str,
        formula: Callable[[Mapping[str, float]], float],
    ) -> dict[str, Any]:
        metric_maps: dict[str, dict[str, float]] = {}
        for metric in METRICS:
            metric_maps[metric] = {
                slug: formula(
                    {
                        condition: world_arm_means[condition][metric][slug]
                        for condition in CONDITIONS
                    }
                )
                for slug in CASE_SLUGS
            }
        return {
            "overall": {
                metric: _aggregate_world_map(values, label=f"{name}:overall:{metric}")
                for metric, values in metric_maps.items()
            },
            "by_stratum": {
                stratum: {
                    metric: _aggregate_world_map(
                        {
                            slug: value
                            for slug, value in values.items()
                            if STRATA_BY_SLUG[slug] == stratum
                        },
                        label=f"{name}:{stratum}:{metric}",
                    )
                    for metric, values in metric_maps.items()
                }
                for stratum in sorted(set(STRATA_BY_SLUG.values()))
            },
            "per_world": {
                slug: {metric: metric_maps[metric][slug] for metric in METRICS}
                for slug in CASE_SLUGS
            },
        }

    contrasts = {
        "temporal_minus_v4": contrast(
            name="temporal_minus_v4",
            formula=lambda arm: arm["temporal"] - arm["v4"],
        ),
        "cash_minus_v4": contrast(
            name="cash_minus_v4",
            formula=lambda arm: arm["cash"] - arm["v4"],
        ),
        "joint_minus_v4": contrast(
            name="joint_minus_v4",
            formula=lambda arm: arm["joint"] - arm["v4"],
        ),
        "temporal_main_effect": contrast(
            name="temporal_main_effect",
            formula=lambda arm: statistics.fmean(
                (arm["temporal"] - arm["v4"], arm["joint"] - arm["cash"])
            ),
        ),
        "cash_main_effect": contrast(
            name="cash_main_effect",
            formula=lambda arm: statistics.fmean(
                (arm["cash"] - arm["v4"], arm["joint"] - arm["temporal"])
            ),
        ),
        "temporal_by_cash_interaction": contrast(
            name="temporal_by_cash_interaction",
            formula=lambda arm: (
                arm["joint"] - arm["temporal"] - arm["cash"] + arm["v4"]
            ),
        ),
    }
    joint = contrasts["joint_minus_v4"]
    overall = joint["overall"]
    by_stratum = joint["by_stratum"]
    progression_checks = {
        "joint_regret_improves_overall": (
            overall["regret_to_upper_bound_usd"]["world_cluster_mean"] < 0.0
        ),
        "joint_regret_nonworse_each_stratum": all(
            values["regret_to_upper_bound_usd"]["world_cluster_mean"] <= 0.0
            for values in by_stratum.values()
        ),
        "joint_feasibility_nonworse_overall_and_each_stratum": (
            overall["feasible"]["world_cluster_mean"] >= 0.0
            and all(
                values["feasible"]["world_cluster_mean"] >= 0.0
                for values in by_stratum.values()
            )
        ),
        "joint_completed_kits_nonworse_overall_and_each_stratum": (
            overall["completed_kits"]["world_cluster_mean"] >= 0.0
            and all(
                values["completed_kits"]["world_cluster_mean"] >= 0.0
                for values in by_stratum.values()
            )
        ),
        "joint_defer_rate_nonworse_overall_and_each_stratum": (
            overall["defer_rate"]["world_cluster_mean"] <= 0.0
            and all(
                values["defer_rate"]["world_cluster_mean"] <= 0.0
                for values in by_stratum.values()
            )
        ),
    }
    eligible = all(integrity.values())
    progression = (
        "ineligible"
        if not eligible
        else "progress"
        if all(progression_checks.values())
        else "do_not_progress"
    )
    stratum_names = set(by_stratum)
    if {"sample_timing", "landed_cash"} <= stratum_names:
        specialization: dict[str, bool | None] = {
            "temporal_gate_more_helpful_on_sample_timing_regret": (
                contrasts["temporal_minus_v4"]["by_stratum"]["sample_timing"][
                    "regret_to_upper_bound_usd"
                ]["world_cluster_mean"]
                < contrasts["temporal_minus_v4"]["by_stratum"]["landed_cash"]
                ["regret_to_upper_bound_usd"]["world_cluster_mean"]
            ),
            "cash_gate_more_helpful_on_landed_cash_regret": (
                contrasts["cash_minus_v4"]["by_stratum"]["landed_cash"]
                ["regret_to_upper_bound_usd"]["world_cluster_mean"]
                < contrasts["cash_minus_v4"]["by_stratum"]["sample_timing"]
                ["regret_to_upper_bound_usd"]["world_cluster_mean"]
            ),
        }
    else:
        specialization = {
            "temporal_gate_more_helpful_on_sample_timing_regret": None,
            "cash_gate_more_helpful_on_landed_cash_regret": None,
        }
    comparison: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_risk_gate_comparison/0.1",
        "campaign_id": CAMPAIGN_ID,
        "integrity": integrity,
        "readiness": {"adaptive_evidence_qualified": eligible},
        "progression": {
            "status": progression,
            "checks": progression_checks,
            "rule_was_frozen_before_execution": True,
        },
        "effects": {
            "contrasts": contrasts,
            "specialization_diagnostics_nonbinding": specialization,
            "absolute_world_arm_means": world_arm_means,
        },
        "bootstrap": {
            "independent_unit": "economic world",
            "world_count": len(CASE_SLUGS),
            "worlds_per_stratum": dict(
                sorted(Counter(STRATA_BY_SLUG.values()).items())
            ),
            "seed": BOOTSTRAP_SEED,
            "resamples": BOOTSTRAP_RESAMPLES,
            "interpretation": "exploratory intervals; six worlds are not confirmatory",
        },
        "source": source,
        "interpretation": (
            "Eligibility depends only on integrity and completion. Progression is a "
            "separate adaptive decision and may fail without invalidating evidence."
        ),
    }
    comparison["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(comparison)
    ).hexdigest()
    return comparison


def _execution_status(
    run_root: Path, canaries: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    arms: dict[str, Any] = {}
    completed = failures = row_count = 0
    scored_cost = 0.0
    exact_cost = True
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
        artifact = json.loads(summary_path.read_text(encoding="utf-8"))
        summary = artifact["summary"]
        completed += int(summary["completed_trajectory_count"])
        failures += int(summary["operational_failure_count"])
        row_count += int(summary["row_count"])
        scored_cost += float(summary["total_cost_usd"])
        exact_cost = exact_cost and summary.get("cost_accounting") == "exact"
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
            "cost_accounting": summary.get("cost_accounting"),
        }
    planned = len(_arm_specs()) * len(CASE_SLUGS) * len(INFERENCE_SEEDS)
    canary_cost = sum(float(item.get("cost_usd", 0.0)) for item in canaries.values())
    canary_exact = all(item.get("cost_accounting") == "exact" for item in canaries.values())
    admitted = set(canaries) == set(CONDITIONS) and all(
        item.get("status") == "admitted" for item in canaries.values()
    )
    status: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_risk_gate_status/0.1",
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
            "cost_accounting": "exact" if exact_cost and canary_exact else "lower_bound",
            "execution_qualified": (
                admitted and completed == planned and failures == 0 and exact_cost
            ),
            "failure_free_checkpoint": (
                admitted and 0 < completed < planned and failures == 0
            ),
        },
    }
    status["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(status)).hexdigest()
    return status


async def run_risk_gate_campaign(
    *,
    run_root: Path,
    max_spend_usd: float = 2.96,
    resume: bool = False,
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
    preflight_fn: Callable[[Any], Mapping[str, Any]] = preflight_candidate,
) -> dict[str, Any]:
    resolved = run_root.resolve()
    if "runs" not in resolved.parts or {"evidence", "output", "outputs"}.intersection(
        resolved.parts
    ):
        raise ValueError("run_root must be under runs/ and outside publication paths")
    if run_root.exists() and not resume:
        raise FileExistsError("risk-gate output exists; pass --resume after a checkpoint")
    if resume and not run_root.exists():
        raise FileNotFoundError("cannot resume a risk-gate campaign that does not exist")
    plan = build_plan()
    if float(plan["hard_total_cost_ceiling_usd"]) > max_spend_usd:
        raise ValueError("risk-gate hard ceiling exceeds max_spend_usd")
    plan_path = run_root / "campaign_plan.json"
    if plan_path.exists():
        if canonical_json_bytes(json.loads(plan_path.read_text())) != canonical_json_bytes(plan):
            raise ValueError("existing risk-gate plan does not match this invocation")
    else:
        _write_once_json(plan_path, plan)
    for name in _arm_specs():
        path = run_root / "arms" / name / "summary.json"
        if path.exists() and json.loads(path.read_text())["summary"][
            "operational_failure_count"
        ]:
            raise ValueError("cannot resume an attempt containing an operational failure")

    canaries: dict[str, Mapping[str, Any]] = {}
    for index, condition in enumerate(CONDITIONS):
        if canaries and any(item.get("status") != "admitted" for item in canaries.values()):
            break
        canary_path = run_root / "canaries" / f"{condition}.json"
        was_new = not canary_path.exists()
        canaries[condition] = await run_admission_canary(
            path=canary_path,
            condition=condition,
            provider_factory=provider_factory,
        )
        if (
            was_new
            and canaries[condition].get("status") == "admitted"
            and index + 1 < len(CONDITIONS)
        ):
            await asyncio.sleep(INTER_CANARY_DELAY_SECONDS)
    if set(canaries) == set(CONDITIONS) and all(
        item.get("status") == "admitted" for item in canaries.values()
    ):
        preflight = dict(preflight_fn(GLM_PARASAIL_CANDIDATE))
        for name, spec in _arm_specs().items():
            arm_root = run_root / "arms" / name
            summary_path = arm_root / "summary.json"
            if summary_path.exists():
                prior = json.loads(summary_path.read_text())
                if prior["summary"]["readiness"]["execution_qualified"]:
                    continue
            artifact = await run_model_qualification(
                run_root=arm_root,
                case_paths=spec["case_paths"],
                inference_seeds=INFERENCE_SEEDS,
                max_spend_usd=max_spend_usd,
                max_parallel_cells=MAX_PARALLEL_CELLS,
                resume=arm_root.exists(),
                provider_factory=provider_factory,
                preflight_fn=lambda _candidate: preflight,
                campaign_id=f"{CAMPAIGN_ID}.{name}",
                abort_on_operational_failure=True,
                candidate=GLM_PARASAIL_CANDIDATE,
                prompt=spec["prompt"],
                prompt_id=spec["prompt_id"],
                treatment_id=spec["treatment_id"],
                max_new_trajectories=TRAJECTORIES_PER_ARM_PER_CHECKPOINT,
                max_action_attempts=MAX_ACTION_ATTEMPTS,
                retryable_conditions=RETRY_CONDITIONS,
                retry_backoff=RETRY_BACKOFF,
                retry_base_seconds=RETRY_BASE_SECONDS,
                retry_after_max_seconds=RETRY_AFTER_MAX_SECONDS,
                max_cost_usd_per_trajectory=MAX_TRAJECTORY_COST_USD,
            )
            if artifact["summary"]["operational_failure_count"]:
                break
    status = _execution_status(run_root, canaries)
    _replace_json(run_root / "campaign_status.json", status)
    if status["summary"]["execution_qualified"]:
        comparison = build_risk_gate_comparison(run_root=run_root)
        _write_once_json(run_root / "risk_gate_comparison.json", comparison)
        status = {**status, "comparison": comparison}
    return status


def _sanitized_arm(*, run_root: Path, name: str) -> dict[str, Any]:
    artifact, file_sha = _verified_summary(
        run_root / "arms" / name,
        campaign_id=f"{CAMPAIGN_ID}.{name}",
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
        "schema_version": "aeread.procurement_allocation_risk_gate_arm_review/0.1",
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
    value = json.loads(path.read_text(encoding="utf-8"))
    recorded = value.get("artifact_sha256")
    payload = {key: item for key, item in value.items() if key != "artifact_sha256"}
    prompt = PROMPTS[condition]
    if recorded != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
        raise ValueError("admission canary digest mismatch")
    if (
        value.get("campaign_id") != CAMPAIGN_ID
        or value.get("condition") != condition
        or value.get("status") != "admitted"
        or value.get("scored") is not False
        or value.get("prompt_id") != prompt["prompt_id"]
        or value.get("prompt_sha256")
        != hashlib.sha256(prompt["prompt"].encode()).hexdigest()
        or value.get("model") != GLM_PARASAIL_CANDIDATE.route.model
        or value.get("revision") != GLM_PARASAIL_CANDIDATE.route.revision
        or value.get("route_provider") != GLM_PARASAIL_CANDIDATE.route.route_provider
        or value.get("resolved_model") != GLM_PARASAIL_CANDIDATE.route.revision
        or value.get("cost_accounting") != "exact"
    ):
        raise ValueError("admission canary identity or admission state mismatch")
    return value


def publish_risk_gate_campaign(
    *, run_root: Path, publication_root: Path
) -> dict[str, Any]:
    if publication_root.resolve().parent.name != "evidence":
        raise ValueError("publication_root must be one direct evidence/ bundle")
    comparison = build_risk_gate_comparison(run_root=run_root)
    if not comparison["readiness"]["adaptive_evidence_qualified"]:
        raise ValueError("risk-gate evidence is not qualified")
    artifacts: dict[str, str] = {}
    for name in _arm_specs():
        review = _sanitized_arm(run_root=run_root, name=name)
        review["artifact_sha256"] = hashlib.sha256(
            canonical_json_bytes(review)
        ).hexdigest()
        relative = f"reports/{name}.json"
        path = publication_root / relative
        _write_once_json(path, review)
        artifacts[relative] = _sha256_file(path)
    comparison_path = publication_root / "reports" / "risk_gate_effects.json"
    _write_once_json(comparison_path, comparison)
    artifacts["reports/risk_gate_effects.json"] = _sha256_file(comparison_path)
    for condition in CONDITIONS:
        canary = _verified_canary(
            run_root / "canaries" / f"{condition}.json",
            condition=condition,
        )
        relative = f"reports/{condition}_admission_canary.json"
        path = publication_root / relative
        _write_once_json(path, canary)
        artifacts[relative] = _sha256_file(path)
    plan = json.loads((run_root / "campaign_plan.json").read_text(encoding="utf-8"))
    plan_path = publication_root / "tables" / "frozen_plan.json"
    _write_once_json(plan_path, plan)
    artifacts["tables/frozen_plan.json"] = _sha256_file(plan_path)
    manifest: dict[str, Any] = {
        "schema_version": "aeread.publication_manifest/0.1",
        "publication_id": CAMPAIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "evidence_status": "adaptive_exploratory",
        "progression_status": comparison["progression"]["status"],
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
    manifest["manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes(manifest)
    ).hexdigest()
    _write_once_json(publication_root / "publication_manifest.json", manifest)
    _write_once_text(
        publication_root / "README.md",
        f"# {CAMPAIGN_ID}\n\n"
        "Sanitized, digest-bound adaptive evidence for the held-out procurement "
        "risk-gate factorial. Raw provider state remains under ignored `runs/`.\n",
    )
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument("--max-spend-usd", type=float, default=2.96)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--publish-only", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.execute and arguments.publish_only:
        parser.error("--execute and --publish-only are mutually exclusive")
    if arguments.publish_only:
        if arguments.publication_root is None:
            parser.error("--publish-only requires --publication-root")
        manifest = publish_risk_gate_campaign(
            run_root=arguments.run_root,
            publication_root=arguments.publication_root,
        )
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    if not arguments.execute:
        print(json.dumps(build_plan(), indent=2, sort_keys=True))
        return 0
    status = asyncio.run(
        run_risk_gate_campaign(
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
    "CASH_PROMPT",
    "CONDITIONS",
    "INFERENCE_SEEDS",
    "JOINT_PROMPT",
    "MAX_TRAJECTORY_COST_USD",
    "PROMPTS",
    "TEMPORAL_PROMPT",
    "V1_CAMPAIGN_ID",
    "build_plan",
    "build_risk_gate_comparison",
    "publish_risk_gate_campaign",
    "run_admission_canary",
    "run_risk_gate_campaign",
]
