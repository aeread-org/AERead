"""Run and compare the procurement label/order-blinded paired campaign."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes

from .case_matrix import BLINDED_CASE_PATHS, REPOSITORY_ROOT
from .model_campaign import (
    CAMPAIGN_ID as BASELINE_CAMPAIGN_ID,
    derive_inference_seeds,
    planned_model_qualification,
    publish_model_qualification,
    run_model_qualification,
)


CAMPAIGN_ID = "procurement_allocation_glm_morph_blinded_invariance_v3"
PAIRED_INFERENCE_SEEDS = derive_inference_seeds(
    master_seed=20260902,
    count=3,
    campaign_id=BASELINE_CAMPAIGN_ID,
)
DEFAULT_BASELINE_RUN_ROOT = (
    REPOSITORY_ROOT
    / "runs"
    / "procurement_allocation"
    / BASELINE_CAMPAIGN_ID
    / "qualification_attempt_001"
)


def _verified_summary(run_root: Path) -> tuple[dict[str, Any], str]:
    path = run_root / "summary.json"
    raw_bytes = path.read_bytes()
    artifact = json.loads(raw_bytes)
    if not isinstance(artifact, dict):
        raise ValueError(f"qualification summary must be an object: {path}")
    recorded_sha = artifact.get("artifact_sha256")
    payload = {
        key: value for key, value in artifact.items() if key != "artifact_sha256"
    }
    expected_sha = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    if recorded_sha != expected_sha:
        raise ValueError(f"qualification artifact digest mismatch: {path}")
    plan = artifact.get("plan")
    if not isinstance(plan, Mapping):
        raise ValueError(f"qualification plan must be an object: {path}")
    recorded_plan_sha = plan.get("plan_sha256")
    plan_payload = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if (
        recorded_plan_sha
        != hashlib.sha256(canonical_json_bytes(plan_payload)).hexdigest()
    ):
        raise ValueError(f"qualification plan digest mismatch: {path}")
    return artifact, hashlib.sha256(raw_bytes).hexdigest()


def _pair_key(row: Mapping[str, Any]) -> tuple[str, int]:
    return str(row["case_id"]).rsplit(".", 1)[-1], int(row["inference_seed"])


def _indexed_rows(rows: Any, *, label: str) -> dict[tuple[str, int], Mapping[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError(f"{label} rows must be an array")
    indexed: dict[tuple[str, int], Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError(f"{label} row must be an object")
        key = _pair_key(row)
        if key in indexed:
            raise ValueError(f"duplicate {label} pair identity: {key}")
        indexed[key] = row
    return indexed


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def build_paired_comparison(
    *, baseline_run_root: Path, blinded_run_root: Path
) -> dict[str, Any]:
    """Compare paired rows after verifying both sealed qualification artifacts."""

    baseline, baseline_file_sha = _verified_summary(baseline_run_root)
    blinded, blinded_file_sha = _verified_summary(blinded_run_root)
    baseline_plan = baseline["plan"]
    blinded_plan = blinded["plan"]
    if baseline_plan.get("campaign_id") != BASELINE_CAMPAIGN_ID:
        raise ValueError("baseline campaign identity mismatch")
    if blinded_plan.get("campaign_id") != CAMPAIGN_ID:
        raise ValueError("blinded campaign identity mismatch")

    paired_route_fields = ("model", "revision", "provider", "quantization", "harness")
    route_match = all(
        baseline_plan.get(field) == blinded_plan.get(field)
        for field in paired_route_fields
    )
    seeds_match = (
        baseline_plan.get("inference_seeds")
        == blinded_plan.get("inference_seeds")
        == list(PAIRED_INFERENCE_SEEDS)
    )
    baseline_rows = _indexed_rows(baseline.get("rows"), label="baseline")
    blinded_rows = _indexed_rows(blinded.get("rows"), label="blinded")
    identities_match = set(baseline_rows) == set(blinded_rows)
    all_keys = sorted(set(baseline_rows) | set(blinded_rows))

    pairs: list[dict[str, Any]] = []
    transitions: Counter[str] = Counter()
    completed_margin_deltas: list[float] = []
    completed_regret_deltas: list[float] = []
    completed_kit_deltas: list[float] = []
    bounds_invariant = True
    per_case_rows: dict[str, list[dict[str, Any]]] = {}
    for slug, seed in all_keys:
        baseline_row = baseline_rows.get((slug, seed))
        blinded_row = blinded_rows.get((slug, seed))
        pair: dict[str, Any] = {
            "case_slug": slug,
            "inference_seed": seed,
            "baseline_status": (
                None if baseline_row is None else baseline_row.get("status")
            ),
            "blinded_status": (
                None if blinded_row is None else blinded_row.get("status")
            ),
        }
        if baseline_row is not None:
            pair["baseline_case_id"] = baseline_row.get("case_id")
        if blinded_row is not None:
            pair["blinded_case_id"] = blinded_row.get("case_id")
        if (
            baseline_row is not None
            and blinded_row is not None
            and baseline_row.get("status") == "completed"
            and blinded_row.get("status") == "completed"
        ):
            baseline_feasible = bool(baseline_row.get("feasible"))
            blinded_feasible = bool(blinded_row.get("feasible"))
            transition = (
                f"{'pass' if baseline_feasible else 'fail'}_"
                f"{'pass' if blinded_feasible else 'fail'}"
            )
            transitions[transition] += 1
            margin_delta = float(blinded_row["contribution_margin_usd"]) - float(
                baseline_row["contribution_margin_usd"]
            )
            regret_delta = float(blinded_row["regret_to_upper_bound_usd"]) - float(
                baseline_row["regret_to_upper_bound_usd"]
            )
            kit_delta = float(blinded_row["completed_kits"]) - float(
                baseline_row["completed_kits"]
            )
            bound_match = float(baseline_row["upper_bound_usd"]) == float(
                blinded_row["upper_bound_usd"]
            )
            bounds_invariant = bounds_invariant and bound_match
            completed_margin_deltas.append(margin_delta)
            completed_regret_deltas.append(regret_delta)
            completed_kit_deltas.append(kit_delta)
            pair.update(
                {
                    "feasibility_transition": transition,
                    "baseline_contribution_margin_usd": baseline_row[
                        "contribution_margin_usd"
                    ],
                    "blinded_contribution_margin_usd": blinded_row[
                        "contribution_margin_usd"
                    ],
                    "contribution_margin_delta_usd": margin_delta,
                    "regret_delta_usd": regret_delta,
                    "completed_kits_delta": kit_delta,
                    "upper_bound_invariant": bound_match,
                }
            )
        pairs.append(pair)
        per_case_rows.setdefault(slug, []).append(pair)

    per_case: dict[str, Any] = {}
    for slug, case_pairs in sorted(per_case_rows.items()):
        completed_pairs = [
            pair for pair in case_pairs if "contribution_margin_delta_usd" in pair
        ]
        per_case[slug] = {
            "pair_count": len(case_pairs),
            "completed_pair_count": len(completed_pairs),
            "feasibility_transition_counts": dict(
                sorted(
                    Counter(
                        str(pair["feasibility_transition"]) for pair in completed_pairs
                    ).items()
                )
            ),
            "mean_contribution_margin_delta_usd": _mean(
                [
                    float(pair["contribution_margin_delta_usd"])
                    for pair in completed_pairs
                ]
            ),
            "mean_regret_delta_usd": _mean(
                [float(pair["regret_delta_usd"]) for pair in completed_pairs]
            ),
            "mean_completed_kits_delta": _mean(
                [float(pair["completed_kits_delta"]) for pair in completed_pairs]
            ),
        }

    expected_pair_count = len(BLINDED_CASE_PATHS) * len(PAIRED_INFERENCE_SEEDS)
    baseline_ready = bool(
        baseline.get("summary", {}).get("readiness", {}).get("execution_qualified")
    )
    blinded_ready = bool(
        blinded.get("summary", {}).get("readiness", {}).get("execution_qualified")
    )
    completed_pair_count = len(completed_margin_deltas)
    comparison: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_blinded_invariance/0.1",
        "campaign_id": CAMPAIGN_ID,
        "paired_baseline_campaign_id": BASELINE_CAMPAIGN_ID,
        "intervention": {
            "changed": "visible supplier identifiers, neutral supplier names, and listing order",
            "held_fixed": (
                "objectives, policies, interaction budgets, substantive listing claims, "
                "private supplier terms, world seeds, model route, harness, and inference seeds"
            ),
        },
        "source": {
            "baseline_summary_file_sha256": baseline_file_sha,
            "baseline_artifact_sha256": baseline.get("artifact_sha256"),
            "baseline_plan_sha256": baseline_plan.get("plan_sha256"),
            "blinded_summary_file_sha256": blinded_file_sha,
            "blinded_artifact_sha256": blinded.get("artifact_sha256"),
            "blinded_plan_sha256": blinded_plan.get("plan_sha256"),
            "comparison_implementation_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
        },
        "integrity": {
            "route_and_harness_match": route_match,
            "paired_inference_seeds_match": seeds_match,
            "pair_identities_match": identities_match,
            "upper_bounds_invariant": bounds_invariant,
        },
        "summary": {
            "expected_pair_count": expected_pair_count,
            "pair_count": len(all_keys),
            "completed_pair_count": completed_pair_count,
            "feasibility_transition_counts": dict(sorted(transitions.items())),
            "baseline_feasible_count": baseline.get("summary", {}).get(
                "feasible_count"
            ),
            "blinded_feasible_count": blinded.get("summary", {}).get("feasible_count"),
            "mean_contribution_margin_delta_usd": _mean(completed_margin_deltas),
            "mean_regret_delta_usd": _mean(completed_regret_deltas),
            "mean_completed_kits_delta": _mean(completed_kit_deltas),
        },
        "per_case": per_case,
        "pairs": pairs,
        "readiness": {
            "baseline_execution_qualified": baseline_ready,
            "blinded_execution_qualified": blinded_ready,
            "paired_invariance_qualified": (
                baseline_ready
                and blinded_ready
                and identities_match
                and route_match
                and seeds_match
                and bounds_invariant
                and len(all_keys) == expected_pair_count
                and completed_pair_count == expected_pair_count
            ),
        },
        "claim_scope": (
            "paired label/order sensitivity diagnostic on six curated procurement "
            "worlds; not a population estimate or cross-model ranking"
        ),
    }
    comparison["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(comparison)
    ).hexdigest()
    return comparison


def _write_once_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"refusing to replace different comparison: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument(
        "--baseline-run-root", type=Path, default=DEFAULT_BASELINE_RUN_ROOT
    )
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument("--max-spend-usd", type=float, default=0.30)
    parser.add_argument("--max-parallel-cells", type=int, default=2)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--publish-only", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.execute and arguments.publish_only:
        parser.error("--execute and --publish-only are mutually exclusive")
    if arguments.publish_only and arguments.publication_root is None:
        parser.error("--publish-only requires --publication-root")
    if not arguments.execute and not arguments.publish_only:
        plan = planned_model_qualification(
            case_paths=BLINDED_CASE_PATHS,
            inference_seeds=PAIRED_INFERENCE_SEEDS,
            max_parallel_cells=arguments.max_parallel_cells,
            campaign_id=CAMPAIGN_ID,
        )
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    if arguments.execute:
        asyncio.run(
            run_model_qualification(
                run_root=arguments.run_root,
                case_paths=BLINDED_CASE_PATHS,
                inference_seeds=PAIRED_INFERENCE_SEEDS,
                max_spend_usd=arguments.max_spend_usd,
                max_parallel_cells=arguments.max_parallel_cells,
                resume=arguments.resume,
                campaign_id=CAMPAIGN_ID,
            )
        )
    comparison = build_paired_comparison(
        baseline_run_root=arguments.baseline_run_root,
        blinded_run_root=arguments.run_root,
    )
    _write_once_json(arguments.run_root / "paired_comparison.json", comparison)
    qualified = comparison["readiness"]["paired_invariance_qualified"]
    if arguments.publication_root is not None and qualified:
        publish_model_qualification(
            run_root=arguments.run_root,
            publication_root=arguments.publication_root,
            supplemental_reports={"reports/paired_invariance.json": comparison},
        )
    print(json.dumps(comparison["summary"], indent=2, sort_keys=True))
    return 0 if qualified else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BASELINE_CAMPAIGN_ID",
    "CAMPAIGN_ID",
    "DEFAULT_BASELINE_RUN_ROOT",
    "PAIRED_INFERENCE_SEEDS",
    "build_paired_comparison",
]
