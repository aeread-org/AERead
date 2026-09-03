"""Run and publish the frozen paired Qwen procurement holdout diagnostic.

This campaign compares the unscaffolded control prompt with the frozen
constraint-ledger V2 prompt on six new opaque worlds.  The worlds were selected
to probe residual split-capacity, order-step, minimum-service, and supplier-ID
grounding failures.  Selection is targeted, so the result is not a population
model ranking or a broad confirmatory mechanism estimate.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import OpenRouterChatClient
from aeread_families.procurement_grounding.bakeoff import preflight_candidate

from .confirmatory_case_matrix import economic_world_sha256
from .model_campaign import derive_inference_seeds
from .qwen_case_campaign import (
    CandidateCaseCampaignSpec,
    build_plan as build_candidate_plan,
    run_admission_canary as run_candidate_admission_canary,
    run_campaign as run_candidate_campaign,
)
from .qwen235b_constraint_v2_campaign import (
    PROMPT_ID as V2_PROMPT_ID,
    TREATMENT_ID as V2_TREATMENT_ID,
    V2_PROMPT,
)
from .qwen235b_google_case_campaign import QWEN235B_GOOGLE_CANDIDATE
from .qwen_holdout_case_matrix import (
    CASE_SLUGS,
    OPAQUE_PATHS,
    STRATA_BY_SLUG,
)
from .runner import PROMPT as CONTROL_PROMPT


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN_ID = "procurement_allocation_qwen3_235b_google_holdout_v1"
FROZEN_CONTROL_PROMPT_SHA256 = (
    "05dfee2fb708ac563e3503256ff43c1cb83b87d4bc28b238c05babcd512fb2df"
)
FROZEN_V2_PROMPT_SHA256 = (
    "09fee0d49d56fb1a1be678c930bca3b131a09bd1f120e7fe3828e8338af7ecad"
)
PARENT_EVIDENCE_PATH = (
    REPOSITORY_ROOT
    / "evidence"
    / "procurement_allocation_qwen3_235b_google_constraint_ledger_v2"
    / "publication_manifest.json"
)
PARENT_EVIDENCE_FILE_SHA256 = (
    "421fb120dedb8f35b0a2f0281cb9d2c1115fe831a7623fdc10521edd81d49b20"
)
MASTER_SEED = 20260903
INFERENCE_SEEDS = tuple(
    derive_inference_seeds(
        master_seed=MASTER_SEED,
        count=3,
        campaign_id=CAMPAIGN_ID,
    )
)
BOOTSTRAP_SEED = 20260903
BOOTSTRAP_RESAMPLES = 50_000
MAX_TRAJECTORY_COST_USD = 0.03
MAX_CANARY_COST_USD = 0.03
ARM_HARD_TOTAL_COST_CEILING_USD = 0.57
HARD_TOTAL_COST_CEILING_USD = 1.14
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


def _arm_specs() -> dict[str, CandidateCaseCampaignSpec]:
    shared = {
        "candidate": QWEN235B_GOOGLE_CANDIDATE,
        "max_trajectory_cost_usd": MAX_TRAJECTORY_COST_USD,
        "max_canary_cost_usd": MAX_CANARY_COST_USD,
        "hard_total_cost_ceiling_usd": ARM_HARD_TOTAL_COST_CEILING_USD,
        "case_paths": OPAQUE_PATHS,
        "inference_seeds": INFERENCE_SEEDS,
        "max_parallel_cells": 1,
        "trajectories_per_checkpoint": 6,
        "matched_baseline_campaign_id": None,
        "claim_scope": (
            "targeted held-out paired diagnostic on six new opaque procurement "
            "worlds; seeds are within-world replicates and this is not a population "
            "model ranking or broad confirmatory mechanism estimate"
        ),
    }
    return {
        "control": CandidateCaseCampaignSpec(
            campaign_id=f"{CAMPAIGN_ID}.control",
            lineage={
                "condition": "unscaffolded_control",
                "parent_evidence_path": str(
                    PARENT_EVIDENCE_PATH.relative_to(REPOSITORY_ROOT)
                ),
                "parent_evidence_file_sha256": PARENT_EVIDENCE_FILE_SHA256,
                "scientific_contract": (
                    "paired with treatment on identical opaque cases, inference "
                    "seeds, route, harness, action schema, retry policy, and verifier"
                ),
            },
            prompt=CONTROL_PROMPT,
            prompt_id="procurement_allocation_prompt_v1",
            treatment_id="unscaffolded_control",
            **shared,
        ),
        "treatment": CandidateCaseCampaignSpec(
            campaign_id=f"{CAMPAIGN_ID}.treatment",
            lineage={
                "condition": "frozen_constraint_ledger_v2",
                "parent_evidence_path": str(
                    PARENT_EVIDENCE_PATH.relative_to(REPOSITORY_ROOT)
                ),
                "parent_evidence_file_sha256": PARENT_EVIDENCE_FILE_SHA256,
                "scientific_contract": (
                    "paired with control on identical opaque cases, inference "
                    "seeds, route, harness, action schema, retry policy, and verifier"
                ),
            },
            prompt=V2_PROMPT,
            prompt_id=V2_PROMPT_ID,
            treatment_id=V2_TREATMENT_ID,
            **shared,
        ),
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_frozen_sources() -> None:
    if hashlib.sha256(CONTROL_PROMPT.encode()).hexdigest() != FROZEN_CONTROL_PROMPT_SHA256:
        raise ValueError("frozen control prompt changed; use a new campaign identity")
    if hashlib.sha256(V2_PROMPT.encode()).hexdigest() != FROZEN_V2_PROMPT_SHA256:
        raise ValueError("frozen V2 treatment prompt changed; use a new campaign identity")
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


def _case_record(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        "slug": path.stem,
        "case_id": raw["case_id"],
        "case_content_sha256": raw["content_sha256"],
        "world_seed": raw["world_seed"],
        "economic_world_sha256": economic_world_sha256(raw),
        "stratum": STRATA_BY_SLUG[path.stem],
    }


def build_plan() -> dict[str, Any]:
    _assert_frozen_sources()
    specs = _arm_specs()
    arms = {name: build_candidate_plan(spec=spec) for name, spec in specs.items()}
    worlds = [_case_record(path) for path in OPAQUE_PATHS]
    plan: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_qwen_holdout_plan/0.1",
        "campaign_id": CAMPAIGN_ID,
        "freeze_status": "targeted_holdout_frozen_before_live_execution",
        "selection_status": (
            "held out from execution but targeted from prior residual failure modes"
        ),
        "parent_adaptive_evidence": {
            "path": str(PARENT_EVIDENCE_PATH.relative_to(REPOSITORY_ROOT)),
            "file_sha256": PARENT_EVIDENCE_FILE_SHA256,
        },
        "candidate": {
            "candidate_id": QWEN235B_GOOGLE_CANDIDATE.candidate_id,
            "model": QWEN235B_GOOGLE_CANDIDATE.route.model,
            "revision": QWEN235B_GOOGLE_CANDIDATE.route.revision,
            "provider": QWEN235B_GOOGLE_CANDIDATE.route.route_provider,
            "quantization": QWEN235B_GOOGLE_CANDIDATE.route.quantization,
        },
        "prompts": {
            "control_prompt_id": "procurement_allocation_prompt_v1",
            "control_sha256": FROZEN_CONTROL_PROMPT_SHA256,
            "treatment_prompt_id": V2_PROMPT_ID,
            "treatment_id": V2_TREATMENT_ID,
            "treatment_sha256": FROZEN_V2_PROMPT_SHA256,
        },
        "worlds": worlds,
        "independent_world_count": len(worlds),
        "inference_seeds": list(INFERENCE_SEEDS),
        "replicates_per_world_arm": len(INFERENCE_SEEDS),
        "arm_execution_order": list(specs),
        "arms": arms,
        "planned_trajectory_count": sum(
            int(arm["scored_plan"]["planned_trajectory_count"])
            for arm in arms.values()
        ),
        "max_parallel_cells": 1,
        "max_new_trajectories_per_invocation": 6,
        "abort_on_operational_failure": True,
        "admission_canaries": ["control", "treatment"],
        "admission_canaries_scored": False,
        "conservative_total_cost_ceiling_usd": sum(
            float(arm["conservative_total_cost_ceiling_usd"])
            for arm in arms.values()
        ),
        "hard_total_cost_ceiling_usd": HARD_TOTAL_COST_CEILING_USD,
        "analysis": {
            "independent_unit": "economic world",
            "pairing": "prompt condition within opaque case and inference seed",
            "seed_aggregation": "mean three inference seeds within each world",
            "primary_estimand": (
                "V2-minus-control regret_to_upper_bound_usd across six worlds"
            ),
            "uncertainty": "deterministic percentile cluster bootstrap over worlds",
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "diagnostic_support_rule": {
                "regret_delta_bootstrap_upper_strictly_below_usd": 0.0,
                "feasibility_delta_bootstrap_lower_at_least": -0.05,
            },
            "secondary_outcomes": [
                "completed kits and contribution margin",
                "feasibility transitions and violation families",
                "split-capacity and minimum-service strata",
                "unknown opaque supplier-ID action attempts",
                "latency, token, retry, and cost diagnostics",
            ],
            "no_early_efficacy_stopping": True,
        },
        "eligibility": (
            "all 36 rows completed and receipt-replayed; route, revision, harness, "
            "retry policy, opaque cases, seeds, prompts, upper bounds, cost "
            "accounting, and digests match"
        ),
        "claim_scope": (
            "targeted held-out diagnostic of residual Qwen procurement capabilities "
            "on six curated synthetic opaque worlds; not a population model ranking "
            "or broad confirmatory mechanism estimate"
        ),
    }
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return plan


def _verified_json(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    value = json.loads(raw)
    recorded = value.get("artifact_sha256")
    payload = {key: item for key, item in value.items() if key != "artifact_sha256"}
    if recorded != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
        raise ValueError(f"artifact digest mismatch: {path}")
    return value, hashlib.sha256(raw).hexdigest()


def _verified_arm(
    run_root: Path,
    *,
    name: str,
    spec: CandidateCaseCampaignSpec,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    outer = json.loads((run_root / "arms" / name / "campaign_plan.json").read_text())
    expected_outer = build_candidate_plan(spec=spec)
    if canonical_json_bytes(outer) != canonical_json_bytes(expected_outer):
        raise ValueError(f"{name} outer plan differs from frozen plan")
    canary, _ = _verified_json(run_root / "arms" / name / "admission_canary.json")
    summary, summary_file_sha = _verified_json(
        run_root / "arms" / name / "scored" / "summary.json"
    )
    inner_plan = summary.get("plan")
    if not isinstance(inner_plan, Mapping):
        raise ValueError(f"{name} scored plan is missing")
    recorded_plan_sha = inner_plan.get("plan_sha256")
    plan_payload = {
        key: item for key, item in inner_plan.items() if key != "plan_sha256"
    }
    if recorded_plan_sha != hashlib.sha256(canonical_json_bytes(plan_payload)).hexdigest():
        raise ValueError(f"{name} scored plan digest mismatch")
    for row in summary.get("rows", []):
        recorded_row = row.get("result_sha256")
        row_payload = {key: item for key, item in row.items() if key != "result_sha256"}
        if recorded_row != hashlib.sha256(canonical_json_bytes(row_payload)).hexdigest():
            raise ValueError(f"{name} row digest mismatch")
    return outer, canary, summary, summary_file_sha


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
    return float(row.get("feasible") is True) if metric == "feasible" else float(row[metric])


def _bootstrap_interval(values: Sequence[float], *, label: str) -> list[float]:
    if len(values) != len(CASE_SLUGS):
        raise ValueError("bootstrap requires one value per holdout world")
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
        "world_cluster_bootstrap_95_interval": _bootstrap_interval(
            values, label=label
        ),
        "world_count": len(values),
    }


def _unknown_supplier_attempt_count(
    rows: Sequence[Mapping[str, Any]],
) -> int:
    supplier_targeting_actions = {
        "inquire",
        "request_quote",
        "request_sample",
        "counter_offer",
    }
    allowed = {
        path.stem: {
            supplier["supplier_id"]
            for supplier in json.loads(path.read_text(encoding="utf-8"))["payload"][
                "suppliers"
            ]
        }
        for path in OPAQUE_PATHS
    }
    count = 0
    for row in rows:
        slug = str(row["case_id"]).rsplit(".", 1)[-1]
        for action in row.get("action_trace", []):
            if action.get("action") not in supplier_targeting_actions:
                continue
            supplier_id = action.get("supplier_id")
            if isinstance(supplier_id, str) and supplier_id not in allowed[slug]:
                count += 1
    return count


def _violation_family_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        for violation in row.get("violations", []):
            value = str(violation)
            if value.endswith(".over_capacity"):
                counts["over_capacity"] += 1
            elif value == "minimum_service_not_met":
                counts["minimum_service_not_met"] += 1
            elif value == "malformed_procurement_action":
                counts["malformed_procurement_action"] += 1
            else:
                counts[value] += 1
    counts["unknown_supplier_action_attempt"] = _unknown_supplier_attempt_count(rows)
    return dict(sorted(counts.items()))


def _decision_diagnostics(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    supplier_components = {
        path.stem: {
            supplier["supplier_id"]: supplier["component"]
            for supplier in json.loads(path.read_text(encoding="utf-8"))["payload"][
                "suppliers"
            ]
        }
        for path in OPAQUE_PATHS
    }
    split_required_slugs = set(CASE_SLUGS) - {"minimum_service_budget"}
    split_attempts = 0
    split_required_submissions = 0
    for row in rows:
        slug = str(row["case_id"]).rsplit(".", 1)[-1]
        submitted = [
            action
            for action in row.get("action_trace", [])
            if action.get("action") == "submit_award"
        ]
        if submitted and slug in split_required_slugs:
            split_required_submissions += 1
        row_split = False
        for action in submitted:
            component_counts: Counter[str] = Counter()
            for line in action.get("award_lines", []):
                offer_id = str(line.get("offer_id", ""))
                for supplier_id, component in supplier_components[slug].items():
                    if offer_id.startswith(f"offer_{supplier_id}_v"):
                        component_counts[component] += 1
                        break
            row_split = row_split or any(count > 1 for count in component_counts.values())
        split_attempts += int(row_split)
    return {
        "award_decision_count": sum(row.get("decision") == "award" for row in rows),
        "feasible_award_count": sum(
            row.get("decision") == "award" and row.get("feasible") is True
            for row in rows
        ),
        "defer_decision_count": sum(row.get("decision") == "defer" for row in rows),
        "feasible_defer_count": sum(
            row.get("decision") == "defer" and row.get("feasible") is True
            for row in rows
        ),
        "failed_decision_count": sum(row.get("decision") == "failed" for row in rows),
        "split_required_submission_count": split_required_submissions,
        "split_award_attempt_count": split_attempts,
    }


def build_comparison(*, run_root: Path) -> dict[str, Any]:
    expected_plan = build_plan()
    recorded_plan = json.loads((run_root / "campaign_plan.json").read_text())
    if canonical_json_bytes(recorded_plan) != canonical_json_bytes(expected_plan):
        raise ValueError("recorded campaign plan differs from frozen holdout plan")
    specs = _arm_specs()
    artifacts: dict[str, dict[str, Any]] = {}
    sources: dict[str, Any] = {}
    indexes: dict[str, dict[tuple[str, int], Mapping[str, Any]]] = {}
    integrity: dict[str, bool] = {}
    expected_keys = {(slug, seed) for slug in CASE_SLUGS for seed in INFERENCE_SEEDS}
    expected_cases = {
        (record["slug"], record["case_content_sha256"])
        for record in expected_plan["worlds"]
    }
    for name, spec in specs.items():
        outer, canary, artifact, file_sha = _verified_arm(
            run_root, name=name, spec=spec
        )
        artifacts[name] = artifact
        index = _row_index(artifact["rows"])
        indexes[name] = index
        sources[name] = {
            "outer_plan_sha256": outer["plan_sha256"],
            "summary_file_sha256": file_sha,
            "summary_artifact_sha256": artifact["artifact_sha256"],
            "scored_plan_sha256": artifact["plan"]["plan_sha256"],
            "canary_artifact_sha256": canary["artifact_sha256"],
        }
        integrity[f"{name}_scored_plan_matches_frozen"] = (
            canonical_json_bytes(artifact["plan"])
            == canonical_json_bytes(expected_plan["arms"][name]["scored_plan"])
        )
        integrity[f"{name}_all_pairs_present"] = set(index) == expected_keys
        integrity[f"{name}_cases_bound"] = {
            (str(row["case_id"]).rsplit(".", 1)[-1], row["case_content_sha256"])
            for row in artifact["rows"]
        } == expected_cases
        integrity[f"{name}_execution_qualified"] = (
            artifact.get("summary", {}).get("readiness", {}).get(
                "execution_qualified"
            )
            is True
        )
        integrity[f"{name}_rows_completed_replayed_revision_pinned"] = all(
            row.get("status") == "completed"
            and row.get("receipt_replayed") is True
            and row.get("resolved_models")
            == [QWEN235B_GOOGLE_CANDIDATE.route.revision]
            for row in artifact["rows"]
        )
        integrity[f"{name}_cost_accounting_exact"] = (
            artifact.get("summary", {}).get("cost_accounting") == "exact"
            and canary.get("cost_accounting") == "exact"
        )
        integrity[f"{name}_canary_admitted_and_pinned"] = (
            canary.get("campaign_id") == spec.campaign_id
            and canary.get("status") == "admitted"
            and canary.get("scored") is False
            and canary.get("model") == spec.candidate.route.model
            and canary.get("revision") == spec.candidate.route.revision
            and canary.get("route_provider") == spec.candidate.route.route_provider
            and canary.get("resolved_model") == spec.candidate.route.revision
        )

    route_fields = ("model", "revision", "provider", "quantization", "harness", "retry_policy")
    integrity["route_harness_and_retry_policy_match"] = all(
        artifacts["control"]["plan"].get(field)
        == artifacts["treatment"]["plan"].get(field)
        for field in route_fields
    )
    integrity["inference_seeds_match"] = all(
        artifact["plan"].get("inference_seeds") == list(INFERENCE_SEEDS)
        for artifact in artifacts.values()
    )
    integrity["prompts_bound"] = (
        artifacts["control"]["plan"].get("prompt")
        == expected_plan["arms"]["control"]["scored_plan"]["prompt"]
        and artifacts["treatment"]["plan"].get("prompt")
        == expected_plan["arms"]["treatment"]["scored_plan"]["prompt"]
    )

    control = indexes["control"]
    treatment = indexes["treatment"]
    per_world: dict[str, dict[str, float]] = {}
    transitions: Counter[str] = Counter()
    upper_bounds_match = True
    case_content_match = True
    for slug in CASE_SLUGS:
        for seed in INFERENCE_SEEDS:
            left = control[(slug, seed)]
            right = treatment[(slug, seed)]
            case_content_match = case_content_match and (
                left["case_content_sha256"] == right["case_content_sha256"]
            )
            upper_bounds_match = upper_bounds_match and (
                float(left["upper_bound_usd"]) == float(right["upper_bound_usd"])
            )
            transitions[
                f"{'pass' if left['feasible'] else 'fail'}_to_"
                f"{'pass' if right['feasible'] else 'fail'}"
            ] += 1
        per_world[slug] = {
            metric: statistics.fmean(
                _metric(treatment[(slug, seed)], metric)
                - _metric(control[(slug, seed)], metric)
                for seed in INFERENCE_SEEDS
            )
            for metric in METRICS
        }
    integrity["paired_case_content_match"] = case_content_match
    integrity["paired_upper_bounds_match"] = upper_bounds_match
    integrity["six_unique_economic_worlds"] = len(
        {record["economic_world_sha256"] for record in expected_plan["worlds"]}
    ) == len(CASE_SLUGS)

    effects = {
        metric: _aggregate(
            [per_world[slug][metric] for slug in CASE_SLUGS],
            label=f"overall:{metric}",
        )
        for metric in METRICS
    }
    by_stratum = {
        stratum: {
            "world_count": len(slugs),
            "mean_v2_minus_control": {
                metric: statistics.fmean(per_world[slug][metric] for slug in slugs)
                for metric in METRICS
            },
        }
        for stratum in sorted(set(STRATA_BY_SLUG.values()))
        for slugs in [
            [slug for slug in CASE_SLUGS if STRATA_BY_SLUG[slug] == stratum]
        ]
    }
    eligible = all(integrity.values())
    regret_interval = effects["regret_to_upper_bound_usd"][
        "world_cluster_bootstrap_95_interval"
    ]
    feasibility_interval = effects["feasible"][
        "world_cluster_bootstrap_95_interval"
    ]
    support_checks = {
        "regret_upper_below_zero": regret_interval[1] < 0.0,
        "feasibility_lower_at_least_minus_0_05": feasibility_interval[0] >= -0.05,
    }
    status = (
        "ineligible"
        if not eligible
        else "residual_capability_gain_supported"
        if all(support_checks.values())
        else "residual_capability_gain_not_supported"
    )
    comparison: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_qwen_holdout_comparison/0.1",
        "campaign_id": CAMPAIGN_ID,
        "integrity": integrity,
        "readiness": {"holdout_diagnostic_qualified": eligible},
        "diagnostic": {
            "status": status,
            "checks": support_checks,
            "rule_was_frozen_before_execution": True,
            "eligibility_is_independent_of_effect_direction": True,
        },
        "effects_v2_minus_control": effects,
        "per_world_v2_minus_control": per_world,
        "by_stratum": by_stratum,
        "feasibility_transition_counts": dict(sorted(transitions.items())),
        "residual_failure_diagnostics": {
            name: {
                "decision_diagnostics": _decision_diagnostics(artifact["rows"]),
                "violation_families": _violation_family_counts(artifact["rows"]),
                "raw_violation_counts": artifact["summary"].get(
                    "violation_counts", {}
                ),
                "feasible_count": artifact["summary"].get("feasible_count"),
                "scored_cost_usd": artifact["summary"].get("total_cost_usd"),
                "median_elapsed_seconds": artifact["summary"].get(
                    "median_elapsed_seconds"
                ),
            }
            for name, artifact in artifacts.items()
        },
        "bootstrap": {
            "independent_unit": "economic world",
            "world_count": len(CASE_SLUGS),
            "seed": BOOTSTRAP_SEED,
            "resamples": BOOTSTRAP_RESAMPLES,
        },
        "source": sources,
        "interpretation": (
            "The panel was held out from model execution but targeted using prior "
            "residual failure modes. Publish qualified favorable and unfavorable "
            "results alike; do not generalize beyond these six synthetic worlds."
        ),
    }
    comparison["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(comparison)
    ).hexdigest()
    return comparison


def _execution_status(run_root: Path) -> dict[str, Any]:
    arms: dict[str, Any] = {}
    completed = failures = 0
    scored_cost = canary_cost = 0.0
    exact = True
    for name in _arm_specs():
        status_path = run_root / "arms" / name / "campaign_status.json"
        canary_path = run_root / "arms" / name / "admission_canary.json"
        canary = json.loads(canary_path.read_text()) if canary_path.exists() else None
        if canary is not None:
            canary_cost += float(canary.get("cost_usd", 0.0))
            exact = exact and canary.get("cost_accounting") == "exact"
        if not status_path.exists():
            arms[name] = {
                "status": "canary_only" if canary else "not_started",
                "planned_trajectory_count": len(CASE_SLUGS) * len(INFERENCE_SEEDS),
                "completed_trajectory_count": 0,
                "operational_failure_count": 0,
                "canary": canary,
            }
            continue
        arm_status, _ = _verified_json(status_path)
        summary = arm_status["summary"]
        completed += int(summary["completed_trajectory_count"])
        failures += int(summary["operational_failure_count"])
        arm_scored = arm_status.get("scored_summary", {})
        scored_cost += float(arm_scored.get("total_cost_usd", 0.0))
        exact = exact and summary.get("cost_accounting") == "exact"
        arms[name] = {
            "status": (
                "qualified"
                if summary["execution_qualified"]
                else "operational_failure"
                if summary["operational_failure_count"]
                else "checkpoint"
            ),
            **summary,
        }
    planned = 2 * len(CASE_SLUGS) * len(INFERENCE_SEEDS)
    both_canaries = all(
        (run_root / "arms" / name / "admission_canary.json").is_file()
        for name in _arm_specs()
    )
    status: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_qwen_holdout_status/0.1",
        "campaign_id": CAMPAIGN_ID,
        "arms": arms,
        "summary": {
            "planned_trajectory_count": planned,
            "completed_trajectory_count": completed,
            "operational_failure_count": failures,
            "unattempted_trajectory_count": max(planned - completed - failures, 0),
            "scored_cost_usd": scored_cost,
            "canary_cost_usd": canary_cost,
            "total_cost_including_canaries_usd": scored_cost + canary_cost,
            "cost_accounting": "exact" if exact else "lower_bound",
            "execution_qualified": completed == planned and failures == 0,
            "failure_free_checkpoint": (
                both_canaries and 0 < completed < planned and failures == 0
            ),
        },
    }
    status["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(status)).hexdigest()
    return status


async def run_campaign(
    *,
    run_root: Path,
    max_spend_usd: float = HARD_TOTAL_COST_CEILING_USD,
    resume: bool = False,
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
    preflight_fn: Callable[[Any], Mapping[str, Any]] = preflight_candidate,
) -> dict[str, Any]:
    resolved = run_root.resolve()
    if "runs" not in resolved.parts or {"evidence", "output", "outputs"}.intersection(
        resolved.parts
    ):
        raise ValueError("run_root must be under runs/ and outside publication paths")
    if max_spend_usd < HARD_TOTAL_COST_CEILING_USD:
        raise ValueError("max_spend_usd is below the frozen hard total ceiling")
    if run_root.exists() and not resume:
        raise FileExistsError("campaign output exists; pass --resume after a checkpoint")
    if resume and not run_root.exists():
        raise FileNotFoundError("cannot resume a campaign that does not exist")
    plan = build_plan()
    plan_path = run_root / "campaign_plan.json"
    if plan_path.exists():
        if canonical_json_bytes(json.loads(plan_path.read_text())) != canonical_json_bytes(
            plan
        ):
            raise ValueError("existing campaign plan does not match this invocation")
    else:
        _write_once_json(plan_path, plan)

    specs = _arm_specs()
    canaries: dict[str, Mapping[str, Any]] = {}
    for name, spec in specs.items():
        canaries[name] = await run_candidate_admission_canary(
            path=run_root / "arms" / name / "admission_canary.json",
            spec=spec,
            provider_factory=provider_factory,
        )
        if canaries[name].get("status") != "admitted":
            break

    if len(canaries) == len(specs) and all(
        canary.get("status") == "admitted" for canary in canaries.values()
    ):
        for name, spec in specs.items():
            arm_root = run_root / "arms" / name
            status_path = arm_root / "campaign_status.json"
            if status_path.exists():
                prior, _ = _verified_json(status_path)
                if prior["summary"]["operational_failure_count"]:
                    raise ValueError("cannot resume an arm containing an operational failure")
                if prior["summary"]["execution_qualified"]:
                    continue
            await run_candidate_campaign(
                run_root=arm_root,
                max_spend_usd=ARM_HARD_TOTAL_COST_CEILING_USD,
                resume=arm_root.exists(),
                spec=spec,
                provider_factory=provider_factory,
                preflight_fn=preflight_fn,
            )
            break

    status = _execution_status(run_root)
    _replace_json(run_root / "campaign_status.json", status)
    if status["summary"]["execution_qualified"]:
        comparison = build_comparison(run_root=run_root)
        _write_once_json(run_root / "holdout_comparison.json", comparison)
        status = {**status, "comparison": comparison}
    return status


def _sanitized_arm(*, run_root: Path, name: str) -> dict[str, Any]:
    spec = _arm_specs()[name]
    outer, _canary, artifact, file_sha = _verified_arm(
        run_root, name=name, spec=spec
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
        "schema_version": "aeread.procurement_allocation_qwen_holdout_arm_review/0.1",
        "campaign_id": spec.campaign_id,
        "arm": name,
        "source": {
            "raw_summary_path": (
                f"runs/procurement_allocation/{CAMPAIGN_ID}/{run_root.name}/"
                f"arms/{name}/scored/summary.json"
            ),
            "raw_summary_file_sha256": file_sha,
            "raw_artifact_sha256": artifact["artifact_sha256"],
            "outer_plan_sha256": outer["plan_sha256"],
            "scored_plan_sha256": artifact["plan"]["plan_sha256"],
        },
        "plan": artifact["plan"],
        "preflight": safe_preflight,
        "summary": artifact["summary"],
        "rows": [
            {key: row[key] for key in PUBLISHABLE_ROW_FIELDS if key in row}
            for row in artifact["rows"]
        ],
    }


def publish_campaign(*, run_root: Path, publication_root: Path) -> dict[str, Any]:
    if publication_root.resolve().parent.name != "evidence":
        raise ValueError("publication_root must be one direct evidence/ bundle")
    comparison = build_comparison(run_root=run_root)
    if not comparison["readiness"]["holdout_diagnostic_qualified"]:
        raise ValueError("holdout diagnostic is not integrity-qualified")
    artifacts: dict[str, str] = {}
    for name in _arm_specs():
        review = _sanitized_arm(run_root=run_root, name=name)
        review["artifact_sha256"] = hashlib.sha256(
            canonical_json_bytes(review)
        ).hexdigest()
        relative = f"reports/{name}_qualification.json"
        path = publication_root / relative
        _write_once_json(path, review)
        artifacts[relative] = _sha256_file(path)
        canary, _ = _verified_json(
            run_root / "arms" / name / "admission_canary.json"
        )
        canary_relative = f"reports/{name}_admission_canary.json"
        canary_path = publication_root / canary_relative
        _write_once_json(canary_path, canary)
        artifacts[canary_relative] = _sha256_file(canary_path)
    comparison_path = publication_root / "reports" / "holdout_effects.json"
    _write_once_json(comparison_path, comparison)
    artifacts["reports/holdout_effects.json"] = _sha256_file(comparison_path)
    plan = json.loads((run_root / "campaign_plan.json").read_text())
    plan_path = publication_root / "tables" / "frozen_plan.json"
    _write_once_json(plan_path, plan)
    artifacts["tables/frozen_plan.json"] = _sha256_file(plan_path)
    manifest: dict[str, Any] = {
        "schema_version": "aeread.publication_manifest/0.1",
        "publication_id": CAMPAIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "diagnostic_status": comparison["diagnostic"]["status"],
        "artifacts": artifacts,
        "source_bindings": {
            "campaign_plan_sha256": plan["plan_sha256"],
            "comparison_artifact_sha256": comparison["artifact_sha256"],
            "implementation_sha256": _sha256_file(Path(__file__)),
            "case_generator_sha256": _sha256_file(
                REPOSITORY_ROOT
                / "src"
                / "aeread_families"
                / "procurement_allocation"
                / "qwen_holdout_case_matrix.py"
            ),
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
        "Sanitized, digest-bound evidence for the targeted opaque Qwen procurement "
        "holdout. Raw provider state remains under ignored `runs/`.\n",
    )
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument(
        "--max-spend-usd", type=float, default=HARD_TOTAL_COST_CEILING_USD
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--publish-only", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.execute and arguments.publish_only:
        parser.error("--execute and --publish-only are mutually exclusive")
    if arguments.publish_only:
        if arguments.publication_root is None:
            parser.error("--publish-only requires --publication-root")
        value = publish_campaign(
            run_root=arguments.run_root,
            publication_root=arguments.publication_root,
        )
        print(json.dumps(value, indent=2, sort_keys=True))
        return 0
    if not arguments.execute:
        print(json.dumps(build_plan(), indent=2, sort_keys=True))
        return 0
    status = asyncio.run(
        run_campaign(
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
    "FROZEN_CONTROL_PROMPT_SHA256",
    "FROZEN_V2_PROMPT_SHA256",
    "HARD_TOTAL_COST_CEILING_USD",
    "INFERENCE_SEEDS",
    "build_comparison",
    "build_plan",
    "publish_campaign",
    "run_campaign",
]
