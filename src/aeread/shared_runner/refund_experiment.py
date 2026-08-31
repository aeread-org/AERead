"""Paired, cluster-aware Refund V1 reasoning-condition experiments."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from .execution import EvidenceStore, execute_plan_cell
from .refund import _provider_client, build_refund_run
from .resolver import canonical_json_bytes


CONTROL = "none"
TREATMENT = "low"
METRICS = ("joint_utility", "customer_utility", "support_agent_utility", "within_case_score")


_T_975 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}


def _t_critical_975(degrees_freedom: int) -> float:
    if degrees_freedom <= 30:
        return _T_975[degrees_freedom]
    return statistics.NormalDist().inv_cdf(0.975)


def _conditions(raw: str) -> tuple[str, ...]:
    values = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not values or set(values) - {CONTROL, TREATMENT} or len(set(values)) != len(values):
        raise ValueError("--conditions must be a unique comma-separated subset of none,low")
    return values


def _seeds(raw: str | None, *, option: str) -> tuple[int, ...]:
    if raw is None or not raw.strip():
        return ()
    values = tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    if len(set(values)) != len(values) or any(value < 0 for value in values):
        raise ValueError(f"{option} must contain unique non-negative integer seeds")
    return values


def _metric(outcome: Mapping[str, Any], name: str) -> float | None:
    value = outcome.get(name)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def analyze_paired_results(
    rows: Iterable[Mapping[str, Any]], *, expected_replicates: int,
    bootstrap_draws: int = 10_000, bootstrap_seed: int = 20260826,
) -> dict[str, Any]:
    """Aggregate replicates within world before paired world-cluster inference."""
    if expected_replicates < 1 or bootstrap_draws < 1:
        raise ValueError("replicate and bootstrap counts must be positive")
    materialized = [dict(row) for row in rows if row.get("panel") == "sample"]
    by_identity: dict[tuple[str, int, int], dict[str, Any]] = {}
    for row in materialized:
        identity = (str(row.get("condition")), int(row["world_seed"]), int(row["replicate"]))
        if identity in by_identity:
            raise ValueError(f"duplicate trajectory identity: {identity}")
        by_identity[identity] = row
    worlds = sorted({identity[1] for identity in by_identity})
    means: dict[str, list[float]] = {CONTROL: [], TREATMENT: []}
    differences: list[float] = []
    incomplete: list[int] = []
    for world_seed in worlds:
        world_means: dict[str, float] = {}
        for condition in (CONTROL, TREATMENT):
            values: list[float] = []
            for replicate in range(expected_replicates):
                row = by_identity.get((condition, world_seed, replicate))
                value = None if row is None or row.get("status") != "included" else row.get("metrics", {}).get("joint_utility")
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                    values.append(float(value))
            if len(values) == expected_replicates:
                world_means[condition] = float(np.mean(values))
        if set(world_means) != {CONTROL, TREATMENT}:
            incomplete.append(world_seed)
            continue
        for condition in (CONTROL, TREATMENT):
            means[condition].append(world_means[condition])
        differences.append(world_means[TREATMENT] - world_means[CONTROL])
    if not differences:
        return {"status": "deferred_no_complete_world_clusters", "complete_pair_world_count": 0,
                "incomplete_worlds": incomplete, "resampling_unit": "world_seed"}
    difference_array = np.asarray(differences)
    rng = np.random.default_rng(bootstrap_seed)
    draws = rng.choice(difference_array, size=(bootstrap_draws, len(difference_array)), replace=True).mean(axis=1)
    if len(differences) > 1:
        standard_error = difference_sd = float(np.std(difference_array, ddof=1))
        standard_error /= math.sqrt(len(differences))
        critical = _t_critical_975(len(differences) - 1)
        paired_t = [float(difference_array.mean() - critical * standard_error),
                    float(difference_array.mean() + critical * standard_error)]
    else:
        paired_t = [float(difference_array[0]), float(difference_array[0])]
        difference_sd = 0.0
    return {
        "status": "complete", "planned_world_count": len(worlds),
        "complete_pair_world_count": len(differences), "incomplete_world_count": len(incomplete),
        "incomplete_worlds": incomplete, "expected_replicates": expected_replicates,
        "condition_world_means": {condition: float(np.mean(values)) for condition, values in means.items()},
        "mean_paired_difference_low_minus_none": float(difference_array.mean()),
        "cluster_bootstrap_95": [float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))],
        "paired_t_95": paired_t, "paired_difference_sd": difference_sd,
        "standardized_paired_effect": (float(difference_array.mean() / difference_sd) if difference_sd else None),
        "missingness_bounds": None,
        "missingness_bounds_status": "unavailable_without_declared_joint_utility_support",
        "resampling_unit": "world_seed", "bootstrap_draws": bootstrap_draws,
        "bootstrap_seed": bootstrap_seed,
    }


def _event_metrics(evidence: EvidenceStore) -> dict[str, Any]:
    calls = external_calls = retries = reasoning_tokens = unknown_cost = 0
    cost = 0.0
    efforts: set[str] = set()
    models: set[str] = set()
    routes: set[str] = set()
    for event in evidence.read_events():
        payload = evidence.read_event_payload(event)
        if event.event_type == "provider_call_started" and isinstance(payload, Mapping):
            request = payload.get("request")
            if isinstance(request, Mapping):
                if request.get("provider") != "scripted":
                    external_calls += 1
                effort = request.get("reasoning_effort")
                if isinstance(effort, str):
                    efforts.add(effort)
                metadata = request.get("provider_metadata")
                if isinstance(metadata, Mapping) and isinstance(metadata.get("route_provider"), str):
                    routes.add(metadata["route_provider"])
        if event.event_type == "action_attempt_started" and isinstance(payload, Mapping) and payload.get("retry_reason") == "length":
            retries += 1
        if event.event_type in {"provider_call_succeeded", "provider_call_failed", "provider_call_outcome_unknown"}:
            calls += 1
            value = payload.get("cost_usd") if isinstance(payload, Mapping) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cost += float(value)
            elif value == "unknown":
                unknown_cost += 1
            result = payload.get("provider_result") if isinstance(payload, Mapping) else None
            if isinstance(result, Mapping):
                if isinstance(result.get("resolved_model"), str):
                    models.add(result["resolved_model"])
                raw = result.get("raw_response")
                usage = raw.get("usage") if isinstance(raw, Mapping) else None
                details = usage.get("completion_tokens_details") if isinstance(usage, Mapping) else None
                value = details.get("reasoning_tokens") if isinstance(details, Mapping) else None
                if isinstance(value, int) and not isinstance(value, bool):
                    reasoning_tokens += value
    events = evidence.read_events()
    return {"evidence_verified": True, "event_count": len(events),
            "events_sha256": hashlib.sha256(evidence.events_path.read_bytes()).hexdigest(),
            "final_event_hash": events[-1].event_hash if events else None,
            "provider_call_count": calls, "external_provider_call_count": external_calls,
            "length_retry_count": retries,
            "reasoning_tokens": reasoning_tokens, "requested_reasoning_efforts": sorted(efforts),
            "resolved_models": sorted(models), "route_providers": sorted(routes),
            "cost_usd": cost, "unknown_cost_provider_call_count": unknown_cost}


def _secondary(selected: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    decisions = Counter(row.get("final_decision") for row in selected)
    reasons = Counter(reason for row in selected for reason in row.get("reason_codes", ()))
    amount_errors = [float(row["refund_amount_error"]) for row in selected if isinstance(row.get("refund_amount_error"), (int, float))]
    return {"trajectory_count": len(selected), "decision_counts": dict(sorted(decisions.items())),
            "oracle_decision_exact_rate": (sum(bool(row.get("decision_exact")) for row in selected) / len(selected) if selected else None),
            "mean_absolute_refund_amount_error": (float(np.mean(amount_errors)) if amount_errors else None),
            "mean_logical_actions": (float(np.mean([row["logical_action_count"] for row in selected])) if selected else None),
            "mean_revealed_private_fields": (float(np.mean([row["revealed_private_field_count"] for row in selected])) if selected else None),
            "reason_code_counts": dict(sorted(reasons.items()))}


def _failure_condition(error: BaseException) -> str:
    message = str(error).lower()
    for condition, markers in (
        ("length", ("finish_reason='length'", "token ceiling", "max-output-tokens")),
        ("timeout", ("timeout", "timed out")),
        ("rate_limit", ("rate limit", "429")),
        ("provider_5xx", ("provider 5", "status 5")),
        ("empty_response", ("empty answer", "empty response")),
        ("cost_budget_exceeded", ("cost budget", "max_cost")),
    ):
        if any(marker in message for marker in markers):
            return condition
    return type(error).__name__


def _failed_evidence(cell_root: Path) -> dict[str, Any]:
    event_logs = sorted(cell_root.rglob("events.jsonl"))
    if len(event_logs) != 1:
        return {"evidence_verified": False}
    try:
        evidence = EvidenceStore.audit_existing(event_logs[0].parent)
        return {"evidence_dir": str(evidence.root.resolve()), **_event_metrics(evidence)}
    except Exception:
        return {"evidence_dir": str(event_logs[0].parent.resolve()), "evidence_verified": False}


async def _run_panel(*, args: argparse.Namespace, panel: str, seeds: Sequence[int],
                     replicates: int, conditions: Sequence[str], root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for condition in conditions:
        for seed in seeds:
            for replicate in range(replicates):
                cell_root = root / panel / f"condition_{condition}" / f"seed_{seed}" / f"replicate_{replicate}"
                try:
                    plan, registry, prompts, pricing = build_refund_run(
                        provider=args.provider, customer_model=args.model,
                        customer_revision=args.revision or args.model, support_model=args.model,
                        support_revision=args.revision or args.model, world_seeds=(seed,),
                        support_max_output_tokens=args.max_output_tokens,
                        support_reasoning_effort=condition)
                    execution = await execute_plan_cell(
                        plan=plan, cell_id=plan.cells[0].cell_id, registry=registry,
                        evidence_root=cell_root, prompt_sources=prompts,
                        providers={args.provider: _provider_client(args.provider),
                                   "scripted": _provider_client("scripted")},
                        pricing=pricing, episode_attempt_ordinal=replicate)
                    outcome = execution.episode_result.outcome
                    final = outcome.get("final_decision", {})
                    oracle = outcome.get("oracle", {}).get("decision", {})
                    evidence = EvidenceStore.audit_existing(execution.evidence.root)
                    rows.append({"status": "included", "panel": panel, "condition": condition,
                                 "world_seed": seed, "replicate": replicate,
                                 "case_id": execution.episode_result.case_id,
                                 "run_plan_id": plan.run_plan_id, "run_plan_sha256": plan.plan_sha256,
                                 "cell_id": execution.cell_id, "evidence_dir": str(evidence.root.resolve()),
                                 "logical_action_count": execution.episode_result.logical_action_count,
                                 "metrics": {name: _metric(outcome, name) for name in METRICS},
                                 "final_decision": final.get("decision"),
                                 "oracle_decision": oracle.get("decision"),
                                 "decision_exact": final.get("decision") == oracle.get("decision"),
                                 "refund_amount_error": abs(float(final.get("refund_amount", 0)) - float(oracle.get("refund_amount", 0))),
                                 "revealed_private_field_count": len(outcome.get("revealed_private_fields", {})),
                                 "reason_codes": list(outcome.get("reason_codes", ())), **_event_metrics(evidence)})
                except Exception as error:
                    rows.append({"status": "excluded", "panel": panel, "condition": condition,
                                 "world_seed": seed, "replicate": replicate,
                                 "error_type": type(error).__name__,
                                 "failure_condition": _failure_condition(error),
                                 "error": str(error), **_failed_evidence(cell_root)})
    return rows


def _operational(rows: Sequence[Mapping[str, Any]], conditions: Sequence[str], *, panel: str,
                 expected_replicates: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for condition in conditions:
        selected = [row for row in rows if row.get("panel") == panel and row.get("condition") == condition]
        included = [row for row in selected if row.get("status") == "included"]
        complete_worlds = Counter(int(row["world_seed"]) for row in included)
        result[condition] = {"planned": len(selected), "completed": len(included),
                             "failed": len(selected) - len(included),
                             "pass_all_replicates_worlds": sum(count == expected_replicates for count in complete_worlds.values()),
                             "provider_calls": sum(int(row.get("external_provider_call_count", 0)) for row in selected),
                             "reasoning_tokens": sum(int(row.get("reasoning_tokens", 0)) for row in selected),
                             "length_retry_cells": sum(int(row.get("length_retry_count", 0)) > 0 for row in selected),
                             "length_retry_count": sum(int(row.get("length_retry_count", 0)) for row in selected),
                             "known_recorded_cost_usd": sum(float(row.get("cost_usd", 0)) for row in selected),
                             "unknown_cost_provider_calls": sum(int(row.get("unknown_cost_provider_call_count", 0)) for row in selected)}
    failures = Counter(row.get("failure_condition", "unknown") for row in rows if row.get("panel") == panel and row.get("status") == "excluded")
    result["failure_taxonomy"] = dict(sorted(failures.items()))
    return result


def _render_markdown(report: Mapping[str, Any]) -> str:
    primary = report["primary_analysis"]
    lines = ["# Refund reasoning experiment", "", "## Design", "",
             f"- Planned sample cells: {report['design']['planned_sample_trajectories']}",
             f"- Included: {report['receipt_coverage']['sample_included']}; operational exclusions: {report['receipt_coverage']['sample_excluded']}",
             f"- World clusters: {report['design']['world_clusters']}; nested replicates: {report['design']['replicates_per_world_condition']}",
             f"- Treatment verification: {report['model_and_route']['reasoning_treatment_verification']}", "",
             "## Primary Analysis", ""]
    if primary.get("status") == "complete":
        lines += [f"- Complete paired worlds: {primary['complete_pair_world_count']}",
                  f"- Mean joint utility, none: {primary['condition_world_means'][CONTROL]:.6g}",
                  f"- Mean joint utility, low: {primary['condition_world_means'][TREATMENT]:.6g}",
                  f"- Paired difference, low minus none: {primary['mean_paired_difference_low_minus_none']:.6g}",
                  f"- Cluster-bootstrap 95% interval: {primary['cluster_bootstrap_95']}",
                  f"- Paired-t diagnostic 95% interval: {primary['paired_t_95']}",
                  f"- Missingness sensitivity: {primary['missingness_bounds_status']}"]
    else:
        lines.append(f"- Status: {primary['status']}")
    lines += ["", "## Operational Results", ""]
    for condition in report["design"]["conditions"]:
        item = report["operational_results"][condition]
        lines.append(f"- {condition}: {item['completed']}/{item['planned']} completed; {item['provider_calls']} calls; {item['reasoning_tokens']} reasoning tokens; ${item['known_recorded_cost_usd']:.6f} known cost")
    lines += [f"- Failure taxonomy: {report['operational_results']['failure_taxonomy']}", "",
              "## Secondary Diagnostics", ""]
    for condition, item in report["secondary_descriptive"].items():
        lines.append(f"- {condition}: decision exact rate={item['oracle_decision_exact_rate']!r}; mean refund error={item['mean_absolute_refund_amount_error']!r}; mean actions={item['mean_logical_actions']!r}")
    lines += ["", "## Evidence", "", f"- Evidence-audited successful cells: {report['receipt_coverage']['evidence_verified']}",
              f"- Durable evaluation receipts: {report['receipt_coverage']['receipt_status']}", "",
              "## Claim Boundaries", ""]
    lines.extend(f"- {boundary}" for boundary in report["claim_boundaries"])
    return "\n".join(lines) + "\n"


async def run_experiment(args: argparse.Namespace) -> dict[str, Any]:
    conditions = _conditions(args.conditions)
    sample_seeds = _seeds(args.world_seeds, option="--world-seeds")
    admission_seeds = _seeds(args.admission_world_seeds, option="--admission-world-seeds")
    if not sample_seeds or args.replicates < 1:
        raise ValueError("sample seeds and a positive replicate count are required")
    root = Path(args.output)
    admission = await _run_panel(args=args, panel="admission", seeds=admission_seeds,
                                 replicates=1, conditions=conditions, root=root) if admission_seeds else []
    sample = await _run_panel(args=args, panel="sample", seeds=sample_seeds,
                              replicates=args.replicates, conditions=conditions, root=root)
    rows = admission + sample
    included = [row for row in sample if row["status"] == "included"]
    primary = (analyze_paired_results(sample, expected_replicates=args.replicates,
                                      bootstrap_draws=args.bootstrap_draws,
                                      bootstrap_seed=args.bootstrap_seed)
               if set(conditions) == {CONTROL, TREATMENT} else {"status": "not_applicable_without_both_conditions"})
    provider_verification = "unverified_arena_adapter_does_not_transmit_reasoning_control" if args.provider == "arena" else "requested_condition_recorded_in_evidence_not_admission_verified"
    admission_included = [row for row in admission if row["status"] == "included"]
    evidence_paths = [Path(row["evidence_dir"]) for row in rows if row.get("evidence_verified")]
    evidence_files = [path for evidence_path in evidence_paths for path in evidence_path.rglob("*") if path.is_file()]
    report: dict[str, Any] = {
        "artifact_type": "refund_reasoning_experiment_summary", "artifact_version": "1.0.0",
        "claim_scope": f"{args.model} on the pinned Refund V1 generator with a scripted customer",
        "design": {"world_clusters": len(sample_seeds), "conditions": list(conditions),
                   "replicates_per_world_condition": args.replicates,
                   "planned_sample_trajectories": len(sample_seeds) * len(conditions) * args.replicates,
                   "admission_world_clusters": len(admission_seeds),
                   "admission_trajectories": len(admission), "resampling_unit": "world_seed",
                   "bootstrap_draws": args.bootstrap_draws, "bootstrap_seed": args.bootstrap_seed},
        "model_and_route": {"provider": args.provider, "model_listing": args.model,
                            "declared_revision": args.revision or args.model,
                            "max_output_tokens": args.max_output_tokens,
                            "resolved_models": sorted({model for row in included for model in row.get("resolved_models", [])}),
                            "route_providers": sorted({route for row in included for route in row.get("route_providers", [])}),
                            "fallback_status": "not_verifiable" if args.provider == "arena" else "see_route_evidence",
                            "reasoning_treatment_verification": provider_verification},
        "run_plans": [{"condition": condition, "run_plan_id": plan_id, "sha256": digest}
                      for condition, plan_id, digest in sorted({(row["condition"], row["run_plan_id"], row["run_plan_sha256"]) for row in included})],
        "receipt_coverage": {"sample_planned": len(sample), "sample_included": len(included),
                             "sample_excluded": len(sample) - len(included),
                             "admission_planned": len(admission),
                             "admission_included": sum(row["status"] == "included" for row in admission),
                             "evidence_verified": sum(row.get("evidence_verified") is True for row in rows),
                             "receipt_status": "not_yet_emitted_by_refund_adapter",
                             "verified_on_zero_call_resume": False},
        "admission_results": {
            "status": ("not_run" if not admission else
                       "passed_execution_only" if len(admission_included) == len(admission) else "failed"),
            "planned": len(admission), "included": len(admission_included),
            "control_reasoning_tokens": sum(int(row.get("reasoning_tokens", 0)) for row in admission_included if row["condition"] == CONTROL),
            "treatment_reasoning_tokens": sum(int(row.get("reasoning_tokens", 0)) for row in admission_included if row["condition"] == TREATMENT),
            "treatment_verification": provider_verification,
        },
        "primary_analysis": primary,
        "operational_results": _operational(rows, conditions, panel="sample", expected_replicates=args.replicates),
        "secondary_descriptive": {condition: _secondary([row for row in included if row["condition"] == condition]) for condition in conditions},
        "raw_evidence": {"workspace_path": str(root.resolve()),
                         "file_count_before_report_artifacts": len(evidence_files),
                         "size_bytes_before_report_artifacts": sum(path.stat().st_size for path in evidence_files),
                         "contains_prompts_and_responses": True},
        "analysis_contract": {
            "primary_estimand": "mean world-level joint utility difference, low minus none",
            "complete_pair_rule": "all nested replicates valid in both conditions",
            "operational_failure_rule": "exclude as missing measurement without replacement",
            "missingness_sensitivity": "not computed until Refund declares finite per-world joint-utility support",
        },
        "claim_boundaries": [
            "The estimand is conditional on the synthetic Refund generator, declared model and provider, and deterministic scripted customer.",
            "Arena none/low results are descriptive labels until the API adapter transmits and verifies provider reasoning controls.",
            "Nested replicates are not independent world clusters; uncertainty resamples world seeds.",
            "The full-information oracle is an upper bound and may not be attainable under gradual disclosure and interaction costs.",
            "Operational exclusions are missing measurements, never zero-utility outcomes, and are not silently replaced.",
            "Secondary policy, friction, and disclosure diagnostics are descriptive rather than additional confirmatory tests.",
        ], "rows": rows,
    }
    report["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(report)).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    (root / "refund_experiment_summary.json").write_bytes(canonical_json_bytes(report))
    (root / "refund_experiment_report.md").write_text(_render_markdown(report), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("fake", "gemini", "openai", "openrouter", "arena"), default="fake")
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision")
    parser.add_argument("--conditions", default="none,low")
    parser.add_argument("--world-seeds", required=True)
    parser.add_argument("--admission-world-seeds")
    parser.add_argument("--replicates", type=int, default=3)
    parser.add_argument("--bootstrap-draws", type=int, default=10_000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260826)
    parser.add_argument("--max-output-tokens", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parsed = parser.parse_args(argv)
    report = asyncio.run(run_experiment(parsed))
    print(json.dumps({"summary": str(parsed.output / "refund_experiment_summary.json"),
                      "planned_cells": report["receipt_coverage"]["sample_planned"],
                      "included_cells": report["receipt_coverage"]["sample_included"],
                      "excluded_cells": report["receipt_coverage"]["sample_excluded"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
