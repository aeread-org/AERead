"""Adaptive GLM transfer diagnostic on the frozen opaque Qwen holdout.

The campaign changes the checkpoint and pinned provider route while holding the
six cases, three inference seeds, V2 prompt, Minimal Chat harness, action schema,
retry policy, action budget, and objective verifier fixed.  Model selection was
made after observing the Qwen result, so this is a model-route transfer diagnostic
rather than a confirmatory model ranking.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import OpenRouterChatClient
from aeread_families.procurement_grounding.bakeoff import preflight_candidate

from .model_campaign import publish_model_qualification
from .qwen_case_campaign import (
    CandidateCaseCampaignSpec,
    build_plan as build_candidate_plan,
    run_admission_canary as run_candidate_admission_canary,
    run_campaign as run_candidate_campaign,
)
from .qwen235b_constraint_v2_campaign import (
    PROMPT_ID,
    TREATMENT_ID,
    V2_PROMPT,
)
from .qwen_holdout_campaign import INFERENCE_SEEDS
from .qwen_holdout_case_matrix import CASE_SLUGS, OPAQUE_PATHS, STRATA_BY_SLUG
from .strategy_scaffold import GLM_PARASAIL_CANDIDATE


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN_ID = "procurement_allocation_glm53_flash_parasail_qwen_holdout_transfer_v1"
QWEN_PARENT_CAMPAIGN_ID = "procurement_allocation_qwen3_235b_google_holdout_v1"
QWEN_PARENT_ARM_CAMPAIGN_ID = f"{QWEN_PARENT_CAMPAIGN_ID}.treatment"
PARENT_EVIDENCE_ROOT = REPOSITORY_ROOT / "evidence" / QWEN_PARENT_CAMPAIGN_ID
PARENT_EVIDENCE_PATH = PARENT_EVIDENCE_ROOT / "publication_manifest.json"
PARENT_EVIDENCE_FILE_SHA256 = (
    "ce7b7d34b2edf9febaa26db4b14c306630667fe0f2a8fe1ebf9eb7a904c44c7f"
)
PARENT_TREATMENT_PATH = PARENT_EVIDENCE_ROOT / "reports" / "treatment_qualification.json"
PARENT_TREATMENT_FILE_SHA256 = (
    "72b809e333eab2a7672f4639e1150d7d4047ae5cebe524f5a57964a51e1ed3b1"
)
PARENT_TREATMENT_PLAN_SHA256 = (
    "1d7fec0ff2b892dd1ff5760eddf13f2fb5a5d206295a563497cfcad030bc1cfd"
)
FROZEN_PROMPT_SHA256 = (
    "09fee0d49d56fb1a1be678c930bca3b131a09bd1f120e7fe3828e8338af7ecad"
)
MAX_TRAJECTORY_COST_USD = 0.03
MAX_CANARY_COST_USD = 0.03
HARD_TOTAL_COST_CEILING_USD = 0.57
BOOTSTRAP_SEED = 20260903
BOOTSTRAP_RESAMPLES = 50_000
METRICS = (
    "feasible_award",
    "feasible",
    "completed_kits",
    "contribution_margin_usd",
    "regret_to_upper_bound_usd",
)
SPLIT_REQUIRED_SLUGS = tuple(
    slug for slug in CASE_SLUGS if slug != "minimum_service_budget"
)
MIN_SPLIT_WORLDS_FOR_TRANSFER_SIGNAL = 2


SPEC = CandidateCaseCampaignSpec(
    campaign_id=CAMPAIGN_ID,
    candidate=GLM_PARASAIL_CANDIDATE,
    lineage={
        "selection_status": "adaptive_model_route_transfer_after_qwen_holdout",
        "selection_basis": (
            "Qwen V2 completed the targeted holdout with no feasible purchase "
            "award and no submitted multi-offer split; use a previously qualified "
            "open checkpoint/route to distinguish Qwen-specific behavior from a "
            "shared model-interface failure"
        ),
        "parent_evidence_path": str(PARENT_EVIDENCE_PATH.relative_to(REPOSITORY_ROOT)),
        "parent_evidence_file_sha256": PARENT_EVIDENCE_FILE_SHA256,
        "parent_treatment_path": str(
            PARENT_TREATMENT_PATH.relative_to(REPOSITORY_ROOT)
        ),
        "parent_treatment_file_sha256": PARENT_TREATMENT_FILE_SHA256,
        "parent_treatment_plan_sha256": PARENT_TREATMENT_PLAN_SHA256,
        "scientific_contract": (
            "cases, content digests, inference seeds, prompt, harness, action "
            "schema, action budget, retry policy, objective verifier, checkpointing, "
            "and per-trajectory cost cap match the Qwen V2 treatment; checkpoint, "
            "provider route, quantization declaration, and pricing identity change"
        ),
        "comparison_contract": {
            "independent_unit": "economic_world",
            "pairing": "exact_case_slug_and_inference_seed",
            "primary_outcome": "feasible_purchase_award",
            "uncertainty": "deterministic_percentile_cluster_bootstrap_over_six_worlds",
            "transfer_signal_rule": (
                "at least two split-required worlds contain a feasible GLM purchase "
                "award while the sealed Qwen parent contains none"
            ),
            "eligibility_independent_of_effect_direction": True,
        },
    },
    max_trajectory_cost_usd=MAX_TRAJECTORY_COST_USD,
    max_canary_cost_usd=MAX_CANARY_COST_USD,
    hard_total_cost_ceiling_usd=HARD_TOTAL_COST_CEILING_USD,
    claim_scope=(
        "adaptive model-route transfer diagnostic on six targeted opaque worlds; "
        "not a pure model causal effect, population ranking, or new confirmatory panel"
    ),
    prompt=V2_PROMPT,
    prompt_id=PROMPT_ID,
    treatment_id=TREATMENT_ID,
    case_paths=OPAQUE_PATHS,
    inference_seeds=INFERENCE_SEEDS,
    max_parallel_cells=1,
    trajectories_per_checkpoint=6,
    matched_baseline_campaign_id=QWEN_PARENT_ARM_CAMPAIGN_ID,
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_frozen_sources() -> None:
    if hashlib.sha256(V2_PROMPT.encode()).hexdigest() != FROZEN_PROMPT_SHA256:
        raise ValueError("frozen V2 prompt changed; use a new campaign identity")
    if _sha256_file(PARENT_EVIDENCE_PATH) != PARENT_EVIDENCE_FILE_SHA256:
        raise ValueError("parent Qwen publication manifest changed")
    if _sha256_file(PARENT_TREATMENT_PATH) != PARENT_TREATMENT_FILE_SHA256:
        raise ValueError("parent Qwen treatment artifact changed")
    manifest = json.loads(PARENT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    if (
        manifest.get("artifacts", {}).get("reports/treatment_qualification.json")
        != PARENT_TREATMENT_FILE_SHA256
    ):
        raise ValueError("parent manifest does not bind the Qwen treatment artifact")


def build_plan() -> dict[str, Any]:
    _assert_frozen_sources()
    return build_candidate_plan(spec=SPEC)


async def run_admission_canary(
    *,
    path: Path,
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
) -> dict[str, Any]:
    _assert_frozen_sources()
    return await run_candidate_admission_canary(
        path=path,
        spec=SPEC,
        provider_factory=provider_factory,
    )


async def run_campaign(
    *,
    run_root: Path,
    max_spend_usd: float = HARD_TOTAL_COST_CEILING_USD,
    resume: bool = False,
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
    preflight_fn: Callable[[Any], Mapping[str, Any]] = preflight_candidate,
) -> dict[str, Any]:
    _assert_frozen_sources()
    return await run_candidate_campaign(
        run_root=run_root,
        max_spend_usd=max_spend_usd,
        resume=resume,
        spec=SPEC,
        provider_factory=provider_factory,
        preflight_fn=preflight_fn,
    )


def _verified_artifact(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    value = json.loads(raw)
    recorded = value.get("artifact_sha256")
    payload = {key: item for key, item in value.items() if key != "artifact_sha256"}
    if recorded != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
        raise ValueError(f"artifact digest mismatch: {path}")
    return value, hashlib.sha256(raw).hexdigest()


def _verified_model_summary(path: Path, *, campaign_id: str) -> tuple[dict[str, Any], str]:
    value, file_sha = _verified_artifact(path)
    plan = value.get("plan")
    if not isinstance(plan, Mapping) or plan.get("campaign_id") != campaign_id:
        raise ValueError(f"model-plan campaign mismatch: {path}")
    recorded_plan_sha = plan.get("plan_sha256")
    plan_payload = {key: item for key, item in plan.items() if key != "plan_sha256"}
    if recorded_plan_sha != hashlib.sha256(canonical_json_bytes(plan_payload)).hexdigest():
        raise ValueError(f"model-plan digest mismatch: {path}")
    rows = value.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"model rows are missing: {path}")
    for row in rows:
        recorded_row = row.get("result_sha256")
        row_payload = {key: item for key, item in row.items() if key != "result_sha256"}
        if recorded_row != hashlib.sha256(canonical_json_bytes(row_payload)).hexdigest():
            raise ValueError(f"row digest mismatch: {path}")
    return value, file_sha


def _verified_parent() -> tuple[dict[str, Any], dict[str, Any], str]:
    _assert_frozen_sources()
    manifest = json.loads(PARENT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    recorded_manifest = manifest.get("manifest_sha256")
    manifest_payload = {
        key: item for key, item in manifest.items() if key != "manifest_sha256"
    }
    if recorded_manifest != hashlib.sha256(
        canonical_json_bytes(manifest_payload)
    ).hexdigest():
        raise ValueError("parent Qwen publication manifest digest mismatch")
    treatment, file_sha = _verified_artifact(PARENT_TREATMENT_PATH)
    if treatment.get("campaign_id") != QWEN_PARENT_ARM_CAMPAIGN_ID:
        raise ValueError("parent Qwen treatment campaign identity mismatch")
    plan = treatment.get("plan")
    if not isinstance(plan, Mapping) or plan.get("plan_sha256") != PARENT_TREATMENT_PLAN_SHA256:
        raise ValueError("parent Qwen treatment plan identity mismatch")
    return manifest, treatment, file_sha


def _verified_glm_run(run_root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    expected = build_plan()
    outer = json.loads((run_root / "campaign_plan.json").read_text(encoding="utf-8"))
    if canonical_json_bytes(outer) != canonical_json_bytes(expected):
        raise ValueError("recorded GLM campaign plan differs from frozen plan")
    canary, _ = _verified_artifact(run_root / "admission_canary.json")
    summary, file_sha = _verified_model_summary(
        run_root / "scored" / "summary.json", campaign_id=CAMPAIGN_ID
    )
    return outer, canary, summary, file_sha


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
    if metric == "feasible_award":
        return float(row.get("decision") == "award" and row.get("feasible") is True)
    if metric == "feasible":
        return float(row.get("feasible") is True)
    return float(row[metric])


def _bootstrap_interval(values: Sequence[float], *, label: str) -> list[float]:
    if len(values) != len(CASE_SLUGS):
        raise ValueError("bootstrap requires one value per economic world")
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


def _supplier_components() -> dict[str, dict[str, str]]:
    return {
        path.stem: {
            supplier["supplier_id"]: supplier["component"]
            for supplier in json.loads(path.read_text(encoding="utf-8"))["payload"][
                "suppliers"
            ]
        }
        for path in OPAQUE_PATHS
    }


def _decision_diagnostics(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    components = _supplier_components()
    split_attempts = 0
    split_required_submissions = 0
    for row in rows:
        slug = str(row["case_id"]).rsplit(".", 1)[-1]
        submitted = [
            action
            for action in row.get("action_trace", [])
            if action.get("action") == "submit_award"
        ]
        if submitted and slug in SPLIT_REQUIRED_SLUGS:
            split_required_submissions += 1
        row_split = False
        for action in submitted:
            counts: Counter[str] = Counter()
            for line in action.get("award_lines", []):
                offer_id = str(line.get("offer_id", ""))
                for supplier_id, component in components[slug].items():
                    if offer_id.startswith(f"offer_{supplier_id}_v"):
                        counts[component] += 1
                        break
            row_split = row_split or any(value > 1 for value in counts.values())
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


def _violation_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        for violation in row.get("violations", []):
            value = str(violation)
            if value.endswith(".over_capacity"):
                counts["over_capacity"] += 1
            elif value.endswith(".invalid_order_step"):
                counts["invalid_order_step"] += 1
            else:
                counts[value] += 1
    return dict(sorted(counts.items()))


def _split_world_successes(
    index: Mapping[tuple[str, int], Mapping[str, Any]],
) -> list[str]:
    return [
        slug
        for slug in SPLIT_REQUIRED_SLUGS
        if any(
            index[(slug, seed)].get("decision") == "award"
            and index[(slug, seed)].get("feasible") is True
            for seed in INFERENCE_SEEDS
        )
    ]


def build_comparison(*, run_root: Path) -> dict[str, Any]:
    parent_manifest, qwen, parent_file_sha = _verified_parent()
    outer, canary, glm, glm_file_sha = _verified_glm_run(run_root)
    qwen_index = _row_index(qwen["rows"])
    glm_index = _row_index(glm["rows"])
    expected_keys = {(slug, seed) for slug in CASE_SLUGS for seed in INFERENCE_SEEDS}
    expected_cases = {
        (
            json.loads(path.read_text(encoding="utf-8"))["case_id"],
            json.loads(path.read_text(encoding="utf-8"))["content_sha256"],
        )
        for path in OPAQUE_PATHS
    }
    qwen_plan = qwen["plan"]
    glm_plan = glm["plan"]
    invariant_plan_fields = (
        "cases",
        "inference_seeds",
        "prompt",
        "harness",
        "retry_policy",
        "max_actions_per_trajectory",
        "max_output_tokens_per_action",
        "max_parallel_cells",
        "max_new_trajectories_per_invocation",
        "max_cost_usd_per_trajectory",
        "abort_on_operational_failure",
        "resume_policy",
        "response_cache",
    )
    integrity = {
        "parent_manifest_file_bound": _sha256_file(PARENT_EVIDENCE_PATH)
        == PARENT_EVIDENCE_FILE_SHA256,
        "parent_treatment_file_bound": parent_file_sha
        == PARENT_TREATMENT_FILE_SHA256,
        "parent_treatment_plan_bound": qwen_plan.get("plan_sha256")
        == PARENT_TREATMENT_PLAN_SHA256,
        "glm_outer_plan_matches_frozen": canonical_json_bytes(outer)
        == canonical_json_bytes(build_plan()),
        "case_seed_pairs_match": set(qwen_index) == set(glm_index) == expected_keys,
        "case_content_digests_match": {
            (row["case_id"], row["case_content_sha256"])
            for row in qwen["rows"]
        }
        == {
            (row["case_id"], row["case_content_sha256"])
            for row in glm["rows"]
        }
        == expected_cases,
        "scientific_controls_match": all(
            qwen_plan.get(field) == glm_plan.get(field)
            for field in invariant_plan_fields
        ),
        "model_route_changed_as_declared": (
            qwen_plan.get("model") != glm_plan.get("model")
            and qwen_plan.get("provider") != glm_plan.get("provider")
            and glm_plan.get("model") == GLM_PARASAIL_CANDIDATE.route.model
            and glm_plan.get("revision") == GLM_PARASAIL_CANDIDATE.route.revision
            and glm_plan.get("provider")
            == GLM_PARASAIL_CANDIDATE.route.route_provider
        ),
        "qwen_execution_qualified": qwen.get("summary", {})
        .get("readiness", {})
        .get("execution_qualified")
        is True,
        "glm_execution_qualified": glm.get("summary", {})
        .get("readiness", {})
        .get("execution_qualified")
        is True,
        "all_rows_completed_and_replayed": all(
            row.get("status") == "completed" and row.get("receipt_replayed") is True
            for artifact in (qwen, glm)
            for row in artifact["rows"]
        ),
        "cost_accounting_exact": (
            qwen.get("summary", {}).get("cost_accounting") == "exact"
            and glm.get("summary", {}).get("cost_accounting") == "exact"
            and canary.get("cost_accounting") == "exact"
        ),
        "glm_canary_admitted_and_pinned": (
            canary.get("campaign_id") == CAMPAIGN_ID
            and canary.get("status") == "admitted"
            and canary.get("scored") is False
            and canary.get("model") == GLM_PARASAIL_CANDIDATE.route.model
            and canary.get("revision") == GLM_PARASAIL_CANDIDATE.route.revision
            and canary.get("route_provider")
            == GLM_PARASAIL_CANDIDATE.route.route_provider
            and canary.get("resolved_model") == GLM_PARASAIL_CANDIDATE.route.revision
        ),
        "upper_bounds_match": all(
            float(qwen_index[key]["upper_bound_usd"])
            == float(glm_index[key]["upper_bound_usd"])
            for key in expected_keys
        ),
    }
    per_world: dict[str, dict[str, float]] = {}
    transitions: Counter[str] = Counter()
    for slug in CASE_SLUGS:
        for seed in INFERENCE_SEEDS:
            left = qwen_index[(slug, seed)]
            right = glm_index[(slug, seed)]
            transitions[
                f"{'pass' if _metric(left, 'feasible_award') else 'fail'}_to_"
                f"{'pass' if _metric(right, 'feasible_award') else 'fail'}"
            ] += 1
        per_world[slug] = {
            metric: statistics.fmean(
                _metric(glm_index[(slug, seed)], metric)
                - _metric(qwen_index[(slug, seed)], metric)
                for seed in INFERENCE_SEEDS
            )
            for metric in METRICS
        }
    effects = {
        metric: _aggregate(
            [per_world[slug][metric] for slug in CASE_SLUGS],
            label=f"glm_minus_qwen:{metric}",
        )
        for metric in METRICS
    }
    qwen_split_worlds = _split_world_successes(qwen_index)
    glm_split_worlds = _split_world_successes(glm_index)
    eligible = all(integrity.values())
    transfer_checks = {
        "qwen_has_no_feasible_split_world": not qwen_split_worlds,
        "glm_has_at_least_two_feasible_split_worlds": len(glm_split_worlds)
        >= MIN_SPLIT_WORLDS_FOR_TRANSFER_SIGNAL,
    }
    status = (
        "ineligible"
        if not eligible
        else "model_route_transfer_signal_observed"
        if all(transfer_checks.values())
        else "model_route_transfer_signal_not_observed"
    )
    comparison: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_model_transfer/0.1",
        "campaign_id": CAMPAIGN_ID,
        "parent_campaign_id": QWEN_PARENT_CAMPAIGN_ID,
        "integrity": integrity,
        "readiness": {"model_transfer_diagnostic_qualified": eligible},
        "transfer_diagnostic": {
            "status": status,
            "checks": transfer_checks,
            "rule_was_frozen_before_execution": True,
            "eligibility_is_independent_of_effect_direction": True,
            "qwen_feasible_split_worlds": qwen_split_worlds,
            "glm_feasible_split_worlds": glm_split_worlds,
        },
        "effects_glm_minus_qwen": effects,
        "per_world_glm_minus_qwen": per_world,
        "by_stratum": {
            stratum: {
                "world_count": len(slugs),
                "mean_glm_minus_qwen": {
                    metric: statistics.fmean(per_world[slug][metric] for slug in slugs)
                    for metric in METRICS
                },
            }
            for stratum in sorted(set(STRATA_BY_SLUG.values()))
            for slugs in [
                [slug for slug in CASE_SLUGS if STRATA_BY_SLUG[slug] == stratum]
            ]
        },
        "feasible_award_transition_counts": dict(sorted(transitions.items())),
        "diagnostics": {
            "qwen": {
                "decision": _decision_diagnostics(qwen["rows"]),
                "violations": _violation_counts(qwen["rows"]),
                "summary": {
                    "scored_cost_usd": qwen["summary"].get("total_cost_usd"),
                    "median_elapsed_seconds": qwen["summary"].get(
                        "median_elapsed_seconds"
                    ),
                    "provider_call_count": qwen["summary"].get("provider_call_count"),
                },
            },
            "glm": {
                "decision": _decision_diagnostics(glm["rows"]),
                "violations": _violation_counts(glm["rows"]),
                "summary": {
                    "scored_cost_usd": glm["summary"].get("total_cost_usd"),
                    "canary_cost_usd": canary.get("cost_usd"),
                    "median_elapsed_seconds": glm["summary"].get(
                        "median_elapsed_seconds"
                    ),
                    "provider_call_count": glm["summary"].get("provider_call_count"),
                },
            },
        },
        "bootstrap": {
            "independent_unit": "economic_world",
            "world_count": len(CASE_SLUGS),
            "seed": BOOTSTRAP_SEED,
            "resamples": BOOTSTRAP_RESAMPLES,
        },
        "source": {
            "parent_publication_manifest_file_sha256": PARENT_EVIDENCE_FILE_SHA256,
            "parent_publication_manifest_sha256": parent_manifest["manifest_sha256"],
            "parent_treatment_file_sha256": parent_file_sha,
            "parent_treatment_artifact_sha256": qwen["artifact_sha256"],
            "glm_summary_file_sha256": glm_file_sha,
            "glm_summary_artifact_sha256": glm["artifact_sha256"],
            "glm_outer_plan_sha256": outer["plan_sha256"],
        },
        "interpretation": (
            "The model and provider route change together and were selected after "
            "observing Qwen. A qualified result distinguishes transfer behavior on "
            "these six worlds but is not a pure checkpoint causal effect or ranking."
        ),
    }
    comparison["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(comparison)
    ).hexdigest()
    return comparison


def publish_campaign(*, run_root: Path, publication_root: Path) -> dict[str, Any]:
    comparison = build_comparison(run_root=run_root)
    if not comparison["readiness"]["model_transfer_diagnostic_qualified"]:
        raise ValueError("model-transfer diagnostic is not integrity-qualified")
    plan = json.loads((run_root / "campaign_plan.json").read_text(encoding="utf-8"))
    canary, _ = _verified_artifact(run_root / "admission_canary.json")
    published = publish_model_qualification(
        run_root=run_root / "scored",
        publication_root=publication_root,
        supplemental_reports={
            "reports/admission_canary.json": canary,
            "reports/campaign_plan.json": plan,
            "reports/model_transfer_analysis.json": comparison,
        },
    )
    return published["manifest"]


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
    "HARD_TOTAL_COST_CEILING_USD",
    "SPEC",
    "build_comparison",
    "build_plan",
    "publish_campaign",
    "run_admission_canary",
    "run_campaign",
]
