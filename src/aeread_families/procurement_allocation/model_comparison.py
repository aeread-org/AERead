"""Run a paired Mistral Small 4 versus GLM procurement allocation comparison."""

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
from aeread_families.procurement_grounding.bakeoff import OPEN_WEIGHT_CANDIDATES

from .case_matrix import CASE_VARIANCE_PATHS, REPOSITORY_ROOT
from .model_campaign import (
    CAMPAIGN_ID as GLM_BASELINE_CAMPAIGN_ID,
    derive_inference_seeds,
    planned_model_qualification,
    publish_model_qualification,
    run_model_qualification,
)
from .runner import SequenceResponseProvider, build_openrouter_setup


CAMPAIGN_ID = "procurement_allocation_mistral_small4_case_variance_v1"
MISTRAL_SMALL4_CANDIDATE = next(
    candidate
    for candidate in OPEN_WEIGHT_CANDIDATES
    if candidate.candidate_id == "mistral_small4"
)
PAIRED_INFERENCE_SEEDS = derive_inference_seeds(
    master_seed=20260902,
    count=3,
    campaign_id=GLM_BASELINE_CAMPAIGN_ID,
)
DEFAULT_BASELINE_RUN_ROOT = (
    REPOSITORY_ROOT
    / "runs"
    / "procurement_allocation"
    / GLM_BASELINE_CAMPAIGN_ID
    / "qualification_attempt_001"
)
METRICS = (
    "feasible",
    "completed_kits",
    "contribution_margin_usd",
    "regret_to_upper_bound_usd",
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


async def _representative_request() -> ProviderRequest:
    setup = build_openrouter_setup(
        MISTRAL_SMALL4_CANDIDATE.route,
        case_path=CASE_VARIANCE_PATHS[0],
        seed=PAIRED_INFERENCE_SEEDS[0],
        max_output_tokens=1800,
        timeout_seconds=180.0,
        max_cost_usd=0.03,
        harness=MinimalChatHarness(),
    )
    provider = SequenceResponseProvider(
        (json.dumps({"action": "defer", "reason": "admission request capture"}),)
    )
    with tempfile.TemporaryDirectory(prefix="aeread-procurement-model-canary-") as root:
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
        raise RuntimeError("admission request capture did not produce exactly one call")
    return provider.requests[0]


def _failure_metadata(error: BaseException) -> dict[str, Any]:
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return {
        "failure_type": type(error).__name__,
        "failure_condition": next(
            (
                value
                for item in chain
                if isinstance((value := getattr(item, "condition", None)), str)
            ),
            "provider_failure",
        ),
        "failure_status_code": next(
            (
                value
                for item in chain
                if isinstance((value := getattr(item, "status_code", None)), int)
            ),
            None,
        ),
    }


def _verified_canary(path: Path, *, request_sha256: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("admission canary must be an object")
    recorded_sha = value.get("artifact_sha256")
    payload = {key: item for key, item in value.items() if key != "artifact_sha256"}
    if recorded_sha != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
        raise ValueError("admission canary digest mismatch")
    if value.get("campaign_id") != CAMPAIGN_ID:
        raise ValueError("admission canary campaign identity mismatch")
    if value.get("request_sha256") != request_sha256:
        raise ValueError("admission canary request identity mismatch")
    return value


async def run_admission_canary(
    *,
    path: Path,
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
) -> dict[str, Any]:
    request = await _representative_request()
    if path.exists():
        return _verified_canary(path, request_sha256=request.request_sha256)
    record: dict[str, Any] = {
        "schema_version": "aeread.provider_admission_canary/0.1",
        "campaign_id": CAMPAIGN_ID,
        "attempted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "request_sha256": request.request_sha256,
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
        record.update({"status": "rejected", "cost_usd": 0.0})
        record.update(_failure_metadata(error))
    record["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(record)).hexdigest()
    _write_once_json(path, record)
    return record


def _verified_summary(root: Path) -> tuple[dict[str, Any], str]:
    path = root / "summary.json"
    raw_bytes = path.read_bytes()
    value = json.loads(raw_bytes)
    if not isinstance(value, dict):
        raise ValueError(f"qualification summary must be an object: {path}")
    recorded_sha = value.get("artifact_sha256")
    payload = {key: item for key, item in value.items() if key != "artifact_sha256"}
    if recorded_sha != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
        raise ValueError(f"qualification artifact digest mismatch: {path}")
    return value, hashlib.sha256(raw_bytes).hexdigest()


def _runs_relative(path: Path) -> str:
    parts = path.resolve().parts
    if "runs" not in parts:
        raise ValueError("admission audit inputs must be under runs/")
    index = len(parts) - 1 - tuple(reversed(parts)).index("runs")
    return Path(*parts[index:]).as_posix()


def build_admission_audit(*, attempt_roots: Sequence[Path]) -> dict[str, Any]:
    """Verify and summarize repeated route failures without scoring them."""

    if len(attempt_roots) < 2:
        raise ValueError("admission audit requires at least two fresh attempts")
    attempts: list[dict[str, Any]] = []
    plan_shas: set[str] = set()
    conditions: Counter[str] = Counter()
    reported_cost_usd = 0.0
    for root in attempt_roots:
        summary, summary_file_sha = _verified_summary(root)
        plan = summary.get("plan", {})
        if plan.get("campaign_id") != CAMPAIGN_ID:
            raise ValueError("admission audit campaign identity mismatch")
        plan_shas.add(str(plan.get("plan_sha256")))
        canary_path = root / "admission_canary.json"
        canary = json.loads(canary_path.read_text(encoding="utf-8"))
        if not isinstance(canary, dict):
            raise ValueError("admission canary must be an object")
        canary_sha = canary.get("artifact_sha256")
        canary_payload = {
            key: value for key, value in canary.items() if key != "artifact_sha256"
        }
        if (
            canary_sha
            != hashlib.sha256(canonical_json_bytes(canary_payload)).hexdigest()
        ):
            raise ValueError("admission canary digest mismatch")
        if canary.get("campaign_id") != CAMPAIGN_ID:
            raise ValueError("admission canary campaign identity mismatch")
        rows = summary.get("rows")
        if not isinstance(rows, list):
            raise ValueError("qualification rows must be an array")
        failures = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("qualification row must be an object")
            recorded_sha = row.get("result_sha256")
            payload = {
                key: value for key, value in row.items() if key != "result_sha256"
            }
            if (
                recorded_sha
                != hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
            ):
                raise ValueError("qualification row digest mismatch")
            if row.get("status") == "operational_failure":
                condition = str(row.get("failure_condition"))
                conditions[condition] += 1
                failures.append(
                    {
                        key: row.get(key)
                        for key in (
                            "case_id",
                            "inference_seed",
                            "status",
                            "failure_type",
                            "failure_condition",
                            "failure_status_code",
                            "failure_receipt_sha256",
                            "result_sha256",
                        )
                    }
                )
        campaign_summary = summary.get("summary", {})
        reported_cost_usd += float(canary.get("cost_usd") or 0.0)
        reported_cost_usd += float(campaign_summary.get("total_cost_usd") or 0.0)
        attempts.append(
            {
                "attempt_id": root.name,
                "source": {
                    "summary_path": f"{_runs_relative(root)}/summary.json",
                    "summary_file_sha256": summary_file_sha,
                    "artifact_sha256": summary.get("artifact_sha256"),
                    "plan_sha256": plan.get("plan_sha256"),
                    "canary_file_sha256": hashlib.sha256(
                        canary_path.read_bytes()
                    ).hexdigest(),
                    "canary_artifact_sha256": canary_sha,
                },
                "canary": {
                    key: canary.get(key)
                    for key in (
                        "status",
                        "request_sha256",
                        "resolved_model",
                        "finish_reason",
                        "input_tokens",
                        "cached_input_tokens",
                        "output_tokens",
                        "cost_usd",
                        "structured_action",
                    )
                },
                "completed_trajectory_count": campaign_summary.get(
                    "completed_trajectory_count"
                ),
                "operational_failure_count": campaign_summary.get(
                    "operational_failure_count"
                ),
                "unattempted_trajectory_count": campaign_summary.get(
                    "unattempted_trajectory_count"
                ),
                "failures": failures,
            }
        )

    repeated_failure = (
        len(conditions) == 1
        and sum(conditions.values()) == len(attempts)
        and all(item["canary"]["status"] == "admitted" for item in attempts)
        and all(item["completed_trajectory_count"] == 0 for item in attempts)
        and all(item["operational_failure_count"] == 1 for item in attempts)
    )
    integrity = {
        "fresh_attempt_count_at_least_two": len(attempts) >= 2,
        "plan_identity_match": len(plan_shas) == 1,
        "all_artifact_digests_verified": True,
    }
    audit: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_admission_audit/0.1",
        "campaign_id": CAMPAIGN_ID,
        "attempts": attempts,
        "failure_condition_counts": dict(sorted(conditions.items())),
        "reported_cost_usd": reported_cost_usd,
        "integrity": integrity,
        "finding": {
            "repeated_post_canary_failure": repeated_failure,
            "route_eligible_for_scored_campaign": False,
            "model_comparison_allowed": False,
        },
        "interpretation": (
            "Two fresh attempts admitted the exact request canary and then failed "
            "their first scored trajectory with the same operational condition. "
            "No procurement model score or paired model ranking is reported."
        ),
        "next_gate": (
            "Use a new campaign identity only after the route demonstrates stable "
            "multi-turn structured responses; do not resume or selectively retry "
            "these failed attempts."
        ),
        "claim_scope": "provider-route admission and reliability only",
    }
    audit["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(audit)).hexdigest()
    return audit


def _row_index(value: Mapping[str, Any]) -> dict[tuple[str, int], Mapping[str, Any]]:
    rows = value.get("rows")
    if not isinstance(rows, list):
        raise ValueError("qualification rows must be an array")
    indexed: dict[tuple[str, int], Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("qualification row must be an object")
        key = (str(row["case_id"]), int(row["inference_seed"]))
        if key in indexed:
            raise ValueError(f"duplicate row identity: {key}")
        indexed[key] = row
    return indexed


def _metric(row: Mapping[str, Any], name: str) -> float:
    if name == "feasible":
        return 1.0 if row.get("feasible") is True else 0.0
    return float(row[name])


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values)


def _cluster_interval(case_effects: Sequence[float]) -> list[float]:
    count = len(case_effects)
    if count != 6:
        raise ValueError("paired model interval requires exactly six case clusters")
    means = sorted(
        _mean([case_effects[index] for index in sample])
        for sample in itertools.product(range(count), repeat=count)
    )
    return [
        means[int(0.025 * (len(means) - 1))],
        means[int(0.975 * (len(means) - 1))],
    ]


def build_paired_model_comparison(
    *, baseline_run_root: Path, mistral_run_root: Path
) -> dict[str, Any]:
    baseline, baseline_file_sha = _verified_summary(baseline_run_root)
    mistral, mistral_file_sha = _verified_summary(mistral_run_root)
    baseline_plan = baseline.get("plan", {})
    mistral_plan = mistral.get("plan", {})
    if baseline_plan.get("campaign_id") != GLM_BASELINE_CAMPAIGN_ID:
        raise ValueError("GLM baseline campaign identity mismatch")
    if mistral_plan.get("campaign_id") != CAMPAIGN_ID:
        raise ValueError("Mistral campaign identity mismatch")

    baseline_rows = _row_index(baseline)
    mistral_rows = _row_index(mistral)
    baseline_keys = set(baseline_rows)
    mistral_keys = set(mistral_rows)
    expected_keys = {
        (f"procurement_allocation_v1.dev.{path.stem}", seed)
        for path in CASE_VARIANCE_PATHS
        for seed in PAIRED_INFERENCE_SEEDS
    }
    identities_match = baseline_keys == mistral_keys == expected_keys
    all_keys = sorted(baseline_keys | mistral_keys)

    pairs: list[dict[str, Any]] = []
    per_case_pairs: dict[str, list[dict[str, Any]]] = {}
    completed_pair_count = 0
    bounds_match = True
    content_match = True
    transitions: Counter[str] = Counter()
    for case_id, seed in all_keys:
        baseline_row = baseline_rows.get((case_id, seed))
        mistral_row = mistral_rows.get((case_id, seed))
        pair: dict[str, Any] = {"case_id": case_id, "inference_seed": seed}
        if baseline_row is not None and mistral_row is not None:
            content_match = content_match and (
                baseline_row.get("case_content_sha256")
                == mistral_row.get("case_content_sha256")
            )
            completed = (
                baseline_row.get("status") == "completed"
                and mistral_row.get("status") == "completed"
                and baseline_row.get("receipt_replayed") is True
                and mistral_row.get("receipt_replayed") is True
            )
            if completed:
                completed_pair_count += 1
                bounds_match = bounds_match and (
                    float(baseline_row["upper_bound_usd"])
                    == float(mistral_row["upper_bound_usd"])
                )
                transition = (
                    f"{'pass' if baseline_row.get('feasible') else 'fail'}_"
                    f"{'pass' if mistral_row.get('feasible') else 'fail'}"
                )
                transitions[transition] += 1
                pair.update(
                    {
                        "feasibility_transition": transition,
                        "baseline": {
                            metric: _metric(baseline_row, metric) for metric in METRICS
                        },
                        "mistral": {
                            metric: _metric(mistral_row, metric) for metric in METRICS
                        },
                    }
                )
                pair["effects"] = {
                    metric: pair["mistral"][metric] - pair["baseline"][metric]
                    for metric in METRICS
                }
        pairs.append(pair)
        per_case_pairs.setdefault(case_id, []).append(pair)

    per_case: dict[str, Any] = {}
    for case_id, case_pairs in sorted(per_case_pairs.items()):
        completed = [pair for pair in case_pairs if "effects" in pair]
        per_case[case_id] = {
            "pair_count": len(case_pairs),
            "completed_pair_count": len(completed),
            "mean_effects": {
                metric: (
                    _mean([pair["effects"][metric] for pair in completed])
                    if completed
                    else None
                )
                for metric in METRICS
            },
        }

    completed_pairs = [pair for pair in pairs if "effects" in pair]
    aggregate_effects: dict[str, Any] = {}
    for metric in METRICS:
        case_values = [
            float(per_case[case_id]["mean_effects"][metric])
            for case_id in sorted(per_case)
            if per_case[case_id]["mean_effects"][metric] is not None
        ]
        aggregate_effects[metric] = {
            "trajectory_mean": (
                _mean([pair["effects"][metric] for pair in completed_pairs])
                if completed_pairs
                else None
            ),
            "case_cluster_mean": _mean(case_values) if case_values else None,
            "case_cluster_bootstrap_95_interval": (
                _cluster_interval(case_values) if len(case_values) == 6 else None
            ),
        }

    expected_count = len(expected_keys)
    integrity = {
        "case_and_seed_identities_match": identities_match,
        "case_content_digests_match": content_match,
        "paired_inference_seeds_match": (
            baseline_plan.get("inference_seeds")
            == mistral_plan.get("inference_seeds")
            == list(PAIRED_INFERENCE_SEEDS)
        ),
        "harness_match": baseline_plan.get("harness") == mistral_plan.get("harness"),
        "both_execution_qualified": (
            baseline.get("summary", {}).get("readiness", {}).get("execution_qualified")
            is True
            and mistral.get("summary", {})
            .get("readiness", {})
            .get("execution_qualified")
            is True
        ),
        "all_pairs_completed_and_replayed": completed_pair_count == expected_count,
        "upper_bounds_match": bounds_match,
    }
    comparison: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_model_comparison/0.1",
        "campaign_id": CAMPAIGN_ID,
        "baseline_campaign_id": GLM_BASELINE_CAMPAIGN_ID,
        "independent_case_count": len(CASE_VARIANCE_PATHS),
        "replicates_per_case_model": len(PAIRED_INFERENCE_SEEDS),
        "completed_pair_count": completed_pair_count,
        "feasibility_transition_counts": dict(sorted(transitions.items())),
        "aggregate_effects_mistral_minus_glm": aggregate_effects,
        "per_case": per_case,
        "pairs": pairs,
        "integrity": integrity,
        "readiness": {"paired_model_comparison_qualified": all(integrity.values())},
        "source": {
            "baseline_summary_file_sha256": baseline_file_sha,
            "baseline_artifact_sha256": baseline.get("artifact_sha256"),
            "baseline_plan_sha256": baseline_plan.get("plan_sha256"),
            "mistral_summary_file_sha256": mistral_file_sha,
            "mistral_artifact_sha256": mistral.get("artifact_sha256"),
            "mistral_plan_sha256": mistral_plan.get("plan_sha256"),
            "comparison_implementation_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
        },
        "claim_scope": (
            "paired GLM versus Mistral diagnostic on six curated procurement worlds; "
            "case-cluster intervals describe this panel and are not population-level "
            "confidence intervals or a general model ranking"
        ),
    }
    comparison["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(comparison)
    ).hexdigest()
    return comparison


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument(
        "--baseline-run-root", type=Path, default=DEFAULT_BASELINE_RUN_ROOT
    )
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument("--max-spend-usd", type=float, default=0.35)
    parser.add_argument("--audit-attempt-root", type=Path, action="append")
    parser.add_argument("--execute", action="store_true")
    arguments = parser.parse_args(argv)

    if arguments.audit_attempt_root:
        if arguments.execute:
            parser.error("--audit-attempt-root cannot be combined with --execute")
        audit = build_admission_audit(attempt_roots=arguments.audit_attempt_root)
        if arguments.publication_root is not None:
            publication_source = arguments.audit_attempt_root[-1]
            canary = json.loads(
                (publication_source / "admission_canary.json").read_text(
                    encoding="utf-8"
                )
            )
            publish_model_qualification(
                run_root=publication_source,
                publication_root=arguments.publication_root,
                supplemental_reports={
                    "reports/admission_canary.json": canary,
                    "reports/admission_audit.json": audit,
                },
            )
        print(json.dumps(audit, indent=2, sort_keys=True))
        return 0
    if arguments.run_root is None:
        parser.error("--run-root is required unless auditing attempts")

    plan = planned_model_qualification(
        case_paths=CASE_VARIANCE_PATHS,
        inference_seeds=PAIRED_INFERENCE_SEEDS,
        max_parallel_cells=1,
        campaign_id=CAMPAIGN_ID,
        abort_on_operational_failure=True,
        candidate=MISTRAL_SMALL4_CANDIDATE,
    )
    if not arguments.execute:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0

    canary = asyncio.run(
        run_admission_canary(path=arguments.run_root / "admission_canary.json")
    )
    if canary["status"] != "admitted":
        print(json.dumps(canary, indent=2, sort_keys=True))
        return 2
    artifact = asyncio.run(
        run_model_qualification(
            run_root=arguments.run_root,
            case_paths=CASE_VARIANCE_PATHS,
            inference_seeds=PAIRED_INFERENCE_SEEDS,
            max_spend_usd=arguments.max_spend_usd,
            max_parallel_cells=1,
            campaign_id=CAMPAIGN_ID,
            abort_on_operational_failure=True,
            candidate=MISTRAL_SMALL4_CANDIDATE,
        )
    )
    if not artifact.get("summary", {}).get("readiness", {}).get("execution_qualified"):
        print(json.dumps(artifact["summary"], indent=2, sort_keys=True))
        return 2

    comparison = build_paired_model_comparison(
        baseline_run_root=arguments.baseline_run_root,
        mistral_run_root=arguments.run_root,
    )
    _write_once_json(arguments.run_root / "paired_model_comparison.json", comparison)
    if (
        arguments.publication_root is not None
        and comparison["readiness"]["paired_model_comparison_qualified"]
    ):
        publish_model_qualification(
            run_root=arguments.run_root,
            publication_root=arguments.publication_root,
            supplemental_reports={
                "reports/admission_canary.json": canary,
                "reports/paired_model_comparison.json": comparison,
            },
        )
    print(
        json.dumps(
            {
                "mistral": artifact["summary"],
                "paired_effects": comparison["aggregate_effects_mistral_minus_glm"],
                "readiness": comparison["readiness"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if comparison["readiness"]["paired_model_comparison_qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CAMPAIGN_ID",
    "MISTRAL_SMALL4_CANDIDATE",
    "PAIRED_INFERENCE_SEEDS",
    "build_admission_audit",
    "build_paired_model_comparison",
    "run_admission_canary",
]
