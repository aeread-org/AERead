"""Run the procurement supplier-identity by listing-order factorial campaign."""

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

from .blinded_invariance import (
    BASELINE_CAMPAIGN_ID,
    CAMPAIGN_ID as COMBINED_CAMPAIGN_ID,
    DEFAULT_BASELINE_RUN_ROOT,
    PAIRED_INFERENCE_SEEDS,
)
from .case_matrix import (
    LABELED_REORDERED_PATHS,
    OPAQUE_ORIGINAL_PATHS,
    REPOSITORY_ROOT,
)
from .model_campaign import (
    GLM_MORPH_CANDIDATE,
    planned_model_qualification,
    publish_model_qualification,
    run_model_qualification,
)
from .runner import SequenceResponseProvider, build_openrouter_setup


STUDY_ID = "procurement_allocation_glm_morph_surface_factorial_v4"
OPAQUE_ORIGINAL_CAMPAIGN_ID = "procurement_allocation_glm_morph_opaque_identity_v4"
LABELED_REORDERED_CAMPAIGN_ID = "procurement_allocation_glm_morph_reordered_listings_v4"
DEFAULT_COMBINED_RUN_ROOT = (
    REPOSITORY_ROOT
    / "runs"
    / "procurement_allocation"
    / COMBINED_CAMPAIGN_ID
    / "qualification_attempt_004"
)

CONDITIONS = {
    "labeled_original": {
        "campaign_id": BASELINE_CAMPAIGN_ID,
        "opaque_identity": False,
        "reordered": False,
    },
    "opaque_original": {
        "campaign_id": OPAQUE_ORIGINAL_CAMPAIGN_ID,
        "opaque_identity": True,
        "reordered": False,
    },
    "labeled_reordered": {
        "campaign_id": LABELED_REORDERED_CAMPAIGN_ID,
        "opaque_identity": False,
        "reordered": True,
    },
    "opaque_reordered": {
        "campaign_id": COMBINED_CAMPAIGN_ID,
        "opaque_identity": True,
        "reordered": True,
    },
}

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


async def _representative_request(*, case_path: Path, seed: int) -> ProviderRequest:
    setup = build_openrouter_setup(
        GLM_MORPH_CANDIDATE.route,
        case_path=case_path,
        seed=seed,
        max_output_tokens=1800,
        timeout_seconds=180.0,
        max_cost_usd=0.03,
        harness=MinimalChatHarness(),
    )
    provider = SequenceResponseProvider(
        (json.dumps({"action": "defer", "reason": "admission request capture"}),)
    )
    with tempfile.TemporaryDirectory(
        prefix="aeread-procurement-factorial-canary-"
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


def _verified_canary(
    path: Path, *, campaign_id: str, request_sha256: str
) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("admission canary must be an object")
    recorded_sha = value.get("artifact_sha256")
    payload = {key: item for key, item in value.items() if key != "artifact_sha256"}
    if recorded_sha != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
        raise ValueError("admission canary digest mismatch")
    if value.get("campaign_id") != campaign_id:
        raise ValueError("admission canary campaign identity mismatch")
    if value.get("request_sha256") != request_sha256:
        raise ValueError("admission canary request identity mismatch")
    return value


async def run_panel_canary(
    *,
    path: Path,
    campaign_id: str,
    case_path: Path,
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
) -> dict[str, Any]:
    request = await _representative_request(
        case_path=case_path, seed=PAIRED_INFERENCE_SEEDS[0]
    )
    if path.exists():
        return _verified_canary(
            path, campaign_id=campaign_id, request_sha256=request.request_sha256
        )
    record: dict[str, Any] = {
        "schema_version": "aeread.provider_admission_canary/0.1",
        "campaign_id": campaign_id,
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


def _verified_summary(path: Path) -> tuple[dict[str, Any], str]:
    raw_bytes = path.read_bytes()
    value = json.loads(raw_bytes)
    if not isinstance(value, dict):
        raise ValueError(f"qualification summary must be an object: {path}")
    recorded_sha = value.get("artifact_sha256")
    payload = {key: item for key, item in value.items() if key != "artifact_sha256"}
    if recorded_sha != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
        raise ValueError(f"qualification artifact digest mismatch: {path}")
    return value, hashlib.sha256(raw_bytes).hexdigest()


def _row_index(value: Mapping[str, Any]) -> dict[tuple[str, int], Mapping[str, Any]]:
    rows = value.get("rows")
    if not isinstance(rows, list):
        raise ValueError("qualification rows must be an array")
    indexed: dict[tuple[str, int], Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("qualification row must be an object")
        key = (str(row["case_id"]).rsplit(".", 1)[-1], int(row["inference_seed"]))
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
    """Exact percentile interval over ordered resamples of six case clusters."""

    count = len(case_effects)
    if count != 6:
        raise ValueError("factorial interval requires exactly six case clusters")
    means = sorted(
        _mean([case_effects[index] for index in sample])
        for sample in itertools.product(range(count), repeat=count)
    )
    low = means[int(0.025 * (len(means) - 1))]
    high = means[int(0.975 * (len(means) - 1))]
    return [low, high]


def build_factorial_comparison(
    *, condition_run_roots: Mapping[str, Path]
) -> dict[str, Any]:
    if set(condition_run_roots) != set(CONDITIONS):
        raise ValueError(
            "factorial comparison requires exactly four declared conditions"
        )
    artifacts: dict[str, dict[str, Any]] = {}
    indexes: dict[str, dict[tuple[str, int], Mapping[str, Any]]] = {}
    source: dict[str, Any] = {}
    for condition, specification in CONDITIONS.items():
        root = condition_run_roots[condition]
        artifact, file_sha = _verified_summary(root / "summary.json")
        if artifact.get("plan", {}).get("campaign_id") != specification["campaign_id"]:
            raise ValueError(f"{condition} campaign identity mismatch")
        artifacts[condition] = artifact
        indexes[condition] = _row_index(artifact)
        source[condition] = {
            "summary_file_sha256": file_sha,
            "artifact_sha256": artifact.get("artifact_sha256"),
            "plan_sha256": artifact.get("plan", {}).get("plan_sha256"),
        }

    baseline_keys = set(indexes["labeled_original"])
    identities_match = all(
        set(indexed) == baseline_keys for indexed in indexes.values()
    )
    expected_keys = {
        (path.stem, seed)
        for path in OPAQUE_ORIGINAL_PATHS
        for seed in PAIRED_INFERENCE_SEEDS
    }
    route_fields = ("model", "revision", "provider", "quantization", "harness")
    baseline_plan = artifacts["labeled_original"]["plan"]
    route_match = all(
        all(
            artifact["plan"].get(field) == baseline_plan.get(field)
            for field in route_fields
        )
        for artifact in artifacts.values()
    )
    seeds_match = all(
        artifact["plan"].get("inference_seeds") == list(PAIRED_INFERENCE_SEEDS)
        for artifact in artifacts.values()
    )
    execution_qualified = all(
        artifact.get("summary", {}).get("readiness", {}).get("execution_qualified")
        is True
        for artifact in artifacts.values()
    )
    completed_and_replayed = all(
        row.get("status") == "completed" and row.get("receipt_replayed") is True
        for indexed in indexes.values()
        for row in indexed.values()
    )
    upper_bounds_match = all(
        len({float(indexed[key]["upper_bound_usd"]) for indexed in indexes.values()})
        == 1
        for key in baseline_keys
    )

    contrasts = {
        "identity_at_original_order": ("opaque_original", "labeled_original"),
        "identity_at_reordered": ("opaque_reordered", "labeled_reordered"),
        "order_with_labels": ("labeled_reordered", "labeled_original"),
        "order_with_opaque_identity": ("opaque_reordered", "opaque_original"),
    }
    pairs: list[dict[str, Any]] = []
    per_case_pairs: dict[str, list[dict[str, Any]]] = {}
    for slug, seed in sorted(baseline_keys):
        condition_values = {
            condition: {
                metric: _metric(indexed[(slug, seed)], metric) for metric in METRICS
            }
            for condition, indexed in indexes.items()
        }
        effects = {
            contrast: {
                metric: condition_values[high][metric] - condition_values[low][metric]
                for metric in METRICS
            }
            for contrast, (high, low) in contrasts.items()
        }
        effects["identity_order_interaction"] = {
            metric: effects["identity_at_reordered"][metric]
            - effects["identity_at_original_order"][metric]
            for metric in METRICS
        }
        effects["identity_main_effect"] = {
            metric: (
                effects["identity_at_original_order"][metric]
                + effects["identity_at_reordered"][metric]
            )
            / 2.0
            for metric in METRICS
        }
        effects["order_main_effect"] = {
            metric: (
                effects["order_with_labels"][metric]
                + effects["order_with_opaque_identity"][metric]
            )
            / 2.0
            for metric in METRICS
        }
        pair = {
            "case_slug": slug,
            "inference_seed": seed,
            "conditions": condition_values,
            "effects": effects,
        }
        pairs.append(pair)
        per_case_pairs.setdefault(slug, []).append(pair)

    effect_names = tuple(contrasts) + (
        "identity_main_effect",
        "order_main_effect",
        "identity_order_interaction",
    )
    per_case: dict[str, Any] = {}
    for slug, case_pairs in sorted(per_case_pairs.items()):
        per_case[slug] = {
            "condition_feasible_counts": {
                condition: int(
                    sum(
                        pair["conditions"][condition]["feasible"] for pair in case_pairs
                    )
                )
                for condition in CONDITIONS
            },
            "mean_effects": {
                effect: {
                    metric: _mean(
                        [pair["effects"][effect][metric] for pair in case_pairs]
                    )
                    for metric in METRICS
                }
                for effect in effect_names
            },
        }

    aggregate_effects: dict[str, Any] = {}
    ordered_slugs = sorted(per_case)
    for effect in effect_names:
        aggregate_effects[effect] = {}
        for metric in METRICS:
            trajectory_values = [pair["effects"][effect][metric] for pair in pairs]
            case_values = [
                per_case[slug]["mean_effects"][effect][metric] for slug in ordered_slugs
            ]
            aggregate_effects[effect][metric] = {
                "trajectory_mean": _mean(trajectory_values),
                "case_cluster_mean": _mean(case_values),
                "case_cluster_bootstrap_95_interval": _cluster_interval(case_values),
            }

    condition_summary = {
        condition: {
            "feasible_count": int(
                sum(_metric(row, "feasible") for row in indexed.values())
            ),
            "mean_completed_kits": _mean(
                [_metric(row, "completed_kits") for row in indexed.values()]
            ),
            "mean_contribution_margin_usd": _mean(
                [_metric(row, "contribution_margin_usd") for row in indexed.values()]
            ),
            "mean_regret_to_upper_bound_usd": _mean(
                [_metric(row, "regret_to_upper_bound_usd") for row in indexed.values()]
            ),
            "total_cost_usd": artifacts[condition]["summary"].get("total_cost_usd"),
        }
        for condition, indexed in indexes.items()
    }
    transitions: dict[str, Any] = {}
    baseline = indexes["labeled_original"]
    for condition in CONDITIONS:
        if condition == "labeled_original":
            continue
        transitions[condition] = dict(
            sorted(
                Counter(
                    f"{'pass' if baseline[key].get('feasible') else 'fail'}_"
                    f"{'pass' if indexes[condition][key].get('feasible') else 'fail'}"
                    for key in baseline_keys
                ).items()
            )
        )

    source["comparison_implementation_sha256"] = hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest()
    integrity = {
        "pair_identities_match": identities_match and baseline_keys == expected_keys,
        "route_and_harness_match": route_match,
        "paired_inference_seeds_match": seeds_match,
        "all_conditions_execution_qualified": execution_qualified,
        "all_rows_completed_and_replayed": completed_and_replayed,
        "upper_bounds_match": upper_bounds_match,
    }
    comparison: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_surface_factorial/0.1",
        "study_id": STUDY_ID,
        "conditions": CONDITIONS,
        "independent_case_count": len(ordered_slugs),
        "replicates_per_case_condition": len(PAIRED_INFERENCE_SEEDS),
        "condition_summary": condition_summary,
        "transitions_vs_labeled_original": transitions,
        "aggregate_effects": aggregate_effects,
        "per_case": per_case,
        "pairs": pairs,
        "integrity": integrity,
        "readiness": {"factorial_qualified": all(integrity.values())},
        "source": source,
        "claim_scope": (
            "paired two-by-two supplier-identity and listing-order diagnostic on "
            "six curated procurement worlds; case-cluster intervals describe this "
            "panel and are not population-level confidence intervals"
        ),
    }
    comparison["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(comparison)
    ).hexdigest()
    return comparison


def _publish_factorial(
    *, comparison: Mapping[str, Any], publication_root: Path
) -> None:
    if publication_root.resolve().parent.name != "evidence":
        raise ValueError("factorial publication must be one direct evidence/ bundle")
    report_path = publication_root / "reports" / "factorial.json"
    _write_once_json(report_path, comparison)
    report_sha = hashlib.sha256(report_path.read_bytes()).hexdigest()
    fact: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_factorial_manifest/0.1",
        "study_id": STUDY_ID,
        "artifacts": {
            "factorial": {"path": "reports/factorial.json", "sha256": report_sha}
        },
        "source_bindings": comparison["source"],
        "publication_scope": "sanitized paired factorial evidence; not raw replay storage",
    }
    fact["manifest_sha256"] = hashlib.sha256(canonical_json_bytes(fact)).hexdigest()
    fact_path = publication_root / "tables" / "fact_manifest.json"
    _write_once_json(fact_path, fact)
    manifest: dict[str, Any] = {
        "schema_version": "aeread.publication_manifest/0.1",
        "publication_id": publication_root.name,
        "study_id": STUDY_ID,
        "artifacts": {
            "reports/factorial.json": report_sha,
            "tables/fact_manifest.json": hashlib.sha256(
                fact_path.read_bytes()
            ).hexdigest(),
        },
        "source_bindings": comparison["source"],
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes(manifest)
    ).hexdigest()
    _write_once_json(publication_root / "publication_manifest.json", manifest)


async def _run_panel(
    *,
    run_root: Path,
    campaign_id: str,
    case_paths: Sequence[Path],
    max_spend_usd: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    canary = await run_panel_canary(
        path=run_root / "admission_canary.json",
        campaign_id=campaign_id,
        case_path=case_paths[0],
    )
    if canary["status"] != "admitted":
        return canary, {}
    artifact = await run_model_qualification(
        run_root=run_root,
        case_paths=case_paths,
        inference_seeds=PAIRED_INFERENCE_SEEDS,
        max_spend_usd=max_spend_usd,
        max_parallel_cells=1,
        campaign_id=campaign_id,
        abort_on_operational_failure=True,
    )
    return canary, artifact


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opaque-run-root", type=Path, required=True)
    parser.add_argument("--reordered-run-root", type=Path, required=True)
    parser.add_argument(
        "--baseline-run-root", type=Path, default=DEFAULT_BASELINE_RUN_ROOT
    )
    parser.add_argument(
        "--combined-run-root", type=Path, default=DEFAULT_COMBINED_RUN_ROOT
    )
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument(
        "--max-spend-usd-per-panel",
        type=float,
        default=0.30,
        help="hard ceiling for each 18-trajectory scored panel; canary excluded",
    )
    parser.add_argument("--execute", action="store_true")
    arguments = parser.parse_args(argv)

    plans = {
        "opaque_original": planned_model_qualification(
            case_paths=OPAQUE_ORIGINAL_PATHS,
            inference_seeds=PAIRED_INFERENCE_SEEDS,
            max_parallel_cells=1,
            campaign_id=OPAQUE_ORIGINAL_CAMPAIGN_ID,
            abort_on_operational_failure=True,
        ),
        "labeled_reordered": planned_model_qualification(
            case_paths=LABELED_REORDERED_PATHS,
            inference_seeds=PAIRED_INFERENCE_SEEDS,
            max_parallel_cells=1,
            campaign_id=LABELED_REORDERED_CAMPAIGN_ID,
            abort_on_operational_failure=True,
        ),
    }
    if not arguments.execute:
        print(json.dumps(plans, indent=2, sort_keys=True))
        return 0

    opaque_canary, opaque_artifact = asyncio.run(
        _run_panel(
            run_root=arguments.opaque_run_root,
            campaign_id=OPAQUE_ORIGINAL_CAMPAIGN_ID,
            case_paths=OPAQUE_ORIGINAL_PATHS,
            max_spend_usd=arguments.max_spend_usd_per_panel,
        )
    )
    if opaque_canary["status"] != "admitted" or not opaque_artifact.get(
        "summary", {}
    ).get("readiness", {}).get("execution_qualified"):
        print(json.dumps({"opaque_original": opaque_canary}, indent=2, sort_keys=True))
        return 2
    reordered_canary, reordered_artifact = asyncio.run(
        _run_panel(
            run_root=arguments.reordered_run_root,
            campaign_id=LABELED_REORDERED_CAMPAIGN_ID,
            case_paths=LABELED_REORDERED_PATHS,
            max_spend_usd=arguments.max_spend_usd_per_panel,
        )
    )
    if reordered_canary["status"] != "admitted" or not reordered_artifact.get(
        "summary", {}
    ).get("readiness", {}).get("execution_qualified"):
        print(
            json.dumps(
                {"labeled_reordered": reordered_canary}, indent=2, sort_keys=True
            )
        )
        return 2

    roots = {
        "labeled_original": arguments.baseline_run_root,
        "opaque_original": arguments.opaque_run_root,
        "labeled_reordered": arguments.reordered_run_root,
        "opaque_reordered": arguments.combined_run_root,
    }
    comparison = build_factorial_comparison(condition_run_roots=roots)
    _write_once_json(
        arguments.opaque_run_root.parent / "factorial_comparison.json", comparison
    )
    if (
        arguments.publication_root is not None
        and comparison["readiness"]["factorial_qualified"]
    ):
        publish_model_qualification(
            run_root=arguments.opaque_run_root,
            publication_root=arguments.publication_root.parent
            / OPAQUE_ORIGINAL_CAMPAIGN_ID,
            supplemental_reports={
                "reports/admission_canary.json": opaque_canary,
            },
        )
        publish_model_qualification(
            run_root=arguments.reordered_run_root,
            publication_root=arguments.publication_root.parent
            / LABELED_REORDERED_CAMPAIGN_ID,
            supplemental_reports={
                "reports/admission_canary.json": reordered_canary,
            },
        )
        _publish_factorial(
            comparison=comparison, publication_root=arguments.publication_root
        )
    print(json.dumps(comparison["condition_summary"], indent=2, sort_keys=True))
    return 0 if comparison["readiness"]["factorial_qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CONDITIONS",
    "LABELED_REORDERED_CAMPAIGN_ID",
    "OPAQUE_ORIGINAL_CAMPAIGN_ID",
    "STUDY_ID",
    "build_factorial_comparison",
    "run_panel_canary",
]
