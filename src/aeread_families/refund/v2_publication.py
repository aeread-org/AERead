"""Publish Refund V2.1 runs through the canonical AERead publication workflow."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from aeread.shared_runner.analysis.research import (
    deserialize_evaluation_receipt,
    main as export_tables_main,
)
from aeread.shared_runner.run.publication import (
    atomic_publish,
    assert_public_payload,
    jsonl,
    rebuild_publication_manifest,
    receipt_projection,
    seal_publication_manifest,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.run.publish_trajectories import publish_trajectory_grain


def _run_plan_path(run_root: Path) -> Path:
    candidates = sorted(run_root.glob("runplan_*/run_plan.json"))
    if len(candidates) != 1:
        raise ValueError(f"expected exactly one run_plan.json under {run_root}, found {len(candidates)}")
    return candidates[0]


def _attempt_dirs(run_plan_path: Path) -> list[Path]:
    root = run_plan_path.parent
    return sorted(
        path.parent
        for path in root.glob("tasks/*/attempts/*/evaluation_receipt.json")
        if (path.parent / "events.jsonl").is_file()
    )


def _copy_public_tables(*, analysis_root: Path, publication_root: Path) -> None:
    for name in (
        "runs.csv",
        "tasks.csv",
        "model_calls.csv",
        "profiles.csv",
        "model_features.csv",
        "benchmark_results.csv",
        "fact_manifest.json",
    ):
        payload = (analysis_root / "tables" / name).read_bytes()
        assert_public_payload(name, payload)
        atomic_publish(publication_root / "tables" / name, payload)


_METRICS = (
    ("refund_v21_policy_compliance", "policy_compliance"),
    ("refund_v21_transaction", "transaction_correctness"),
    ("refund_v21_coordination", "coordination"),
    ("refund_v21_system_utility", "system_utility"),
)


def _score_map(receipt: dict[str, Any]) -> dict[str, float | None]:
    values: dict[str, float | None] = {name: None for _, name in _METRICS}
    for score in receipt.get("scores", ()):
        estimand = score.get("leaf", {}).get("estimand", {}).get("estimand_id")
        for expected, name in _METRICS:
            if estimand == expected:
                value = score.get("primary", {}).get("value")
                values[name] = float(value) if isinstance(value, (int, float)) else None
    return values


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for _, name in _METRICS:
        values = [float(row[name]) for row in rows if row[name] is not None]
        item: dict[str, Any] = {"n": len(values), "mean": _mean(values)}
        if name != "system_utility":
            item["pass_rate"] = _mean(values)
        summary[name] = item
    return summary


def _result_rows(receipts: list[dict[str, Any]], cells: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for receipt in receipts:
        score_values = _score_map(receipt)
        cell = cells.get(receipt["cell_id"], {})
        case_id = str(receipt["case_id"])
        parts = case_id.split(".")
        scenario = parts[-2] if len(parts) >= 2 else case_id
        rows.append({
            "case_id": case_id,
            "cell_id": receipt["cell_id"],
            "world_seed": cell.get("world_seed"),
            "scenario": scenario,
            "status": receipt["status"],
            "inclusion_status": receipt["inclusion_status"],
            "receipt_sha256": receipt["receipt_sha256"],
            **score_values,
        })
    return sorted(rows, key=lambda row: (str(row["scenario"]), row["world_seed"] or -1, row["cell_id"]))


def _csv_payload(rows: list[dict[str, Any]]) -> bytes:
    fields = [
        "case_id", "cell_id", "world_seed", "scenario", "status", "inclusion_status",
        "receipt_sha256", "policy_compliance", "transaction_correctness",
        "coordination", "system_utility",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows({field: row.get(field) for field in fields} for row in rows)
    return output.getvalue().encode("utf-8")


def _publication_reports(
    *, run_plan: dict[str, Any], receipts: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> tuple[bytes, bytes, bytes]:
    planned = len(run_plan.get("cells", ()))
    included_rows = [row for row in rows if row["inclusion_status"] == "included"]
    completed_rows = [row for row in rows if row["status"] in {"ok", "completed"}]
    excluded_rows = [row for row in rows if row["inclusion_status"] != "included"]
    operational_failures = max(0, planned - len(rows)) + sum(
        1 for row in rows if row["status"] not in {"ok", "completed"}
    )
    scenarios: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in included_rows:
        scenarios[str(row["scenario"])].append(row)
    receipt_set_sha256 = hashlib.sha256(
        canonical_json_bytes(sorted(receipt["receipt_sha256"] for receipt in receipts))
    ).hexdigest()
    summary = {
        "schema_version": "aeread.refund_v21_public_summary/0.1",
        "campaign_id": "refund_v2",
        "run_plan_id": run_plan["run_plan_id"],
        "run_plan_sha256": run_plan["plan_sha256"],
        "planned_cells": planned,
        "completed_cells": len(completed_rows),
        "included_cells": len(included_rows),
        "excluded_cells": len(excluded_rows) + max(0, planned - len(rows)),
        "operational_failure_cells": operational_failures,
        "receipt_count": len(receipts),
        "receipt_set_sha256": receipt_set_sha256,
        "metrics": _metric_summary(included_rows),
        "per_scenario": {
            scenario: {"included_cells": len(items), "metrics": _metric_summary(items)}
            for scenario, items in sorted(scenarios.items())
        },
        "claim_boundary": {
            "scope": "fixed-panel Refund V2.1 measurements on the declared cases",
            "oracle_or_upper_bound_is_not_same_information": True,
            "population_generalization_allowed": False,
            "causal_or_winner_claim_allowed": False,
            "cross_family_comparable": False,
        },
        "sanitization": {
            "complete_receipts_included": False,
            "full_prompts_included": False,
            "raw_provider_responses_included": False,
            "model_reasoning_included": False,
        },
    }
    qualification = {
        "schema_version": "aeread.refund_v21_qualification/0.1",
        "campaign_id": "refund_v2",
        "run_plan_id": run_plan["run_plan_id"],
        "planned_cells": planned,
        "completed_cells": len(completed_rows),
        "included_cells": len(included_rows),
        "operational_failure_cells": operational_failures,
        "readiness": {
            "execution_qualified": operational_failures == 0 and bool(included_rows),
            "case_panel_present": bool(scenarios),
            "transaction_verifier_reported": True,
            "cross_family_comparison_qualified": False,
        },
        "primary_estimands": [name for _, name in _METRICS],
        "admission_estimands": ["policy_compliance", "transaction_correctness"],
        "interpretation": "descriptive fixed-panel reliability report; not a population-level model ranking",
    }
    readme = """# Refund V2.1 publication

This directory is the sanitized, digest-bound publication of a Refund V2.1
shared-runner campaign. It contains one family result row per sealed episode,
canonical shared-runner tables, receipt projections, and the canonical
per-action trajectory grain.

Policy compliance is the primary admission measurement and transaction
correctness is co-required. Coordination is reported as a secondary temporal
measurement, while system utility is reported last and is explicitly not
cross-family comparable. Only included, sealed episodes contribute to metric
means. Missing or operationally failed cells remain typed exclusions.

The publication supports descriptive fixed-panel claims only. It does not
support population generalization, causal effects, model-winner claims, or
comparisons with other benchmark families. Complete receipts, prompts, hidden
facts, provider responses, and reasoning remain outside this public bundle.
""".encode("utf-8")
    return canonical_json_bytes(summary) + b"\n", canonical_json_bytes(qualification) + b"\n", readme


def publish_refund_v21(
    *, run_root: Path, publication_root: Path, analysis_root: Path | None = None
) -> dict[str, Any]:
    """Project verified receipts, export tables, seal, and publish trajectories."""

    run_plan = _run_plan_path(run_root)
    analysis_root = analysis_root or run_plan.parent / "private_analysis"
    resolved_analysis = analysis_root.resolve()
    resolved_publication = publication_root.resolve()
    if (
        resolved_analysis == resolved_publication
        or resolved_analysis in resolved_publication.parents
        or resolved_publication in resolved_analysis.parents
    ):
        raise ValueError("analysis_root and publication_root must be separate directories")
    attempts = _attempt_dirs(run_plan)
    if not attempts:
        raise ValueError(f"no sealed Refund attempts found under {run_plan.parent}")
    run_plan_data = json.loads(run_plan.read_bytes())
    receipts = [json.loads((attempt / "evaluation_receipt.json").read_bytes()) for attempt in attempts]
    for receipt in receipts:
        deserialize_evaluation_receipt(receipt)
    projections = [
        receipt_projection(receipt, campaign_cell_key=f"refund_v21__{receipt['cell_id']}")
        for receipt in receipts
    ]
    projection_path = publication_root / "receipts" / "projections.jsonl"
    projection_payload = jsonl(projections)
    assert_public_payload("receipt projections", projection_payload)
    atomic_publish(projection_path, projection_payload)

    export_status = export_tables_main(
        [
            "--plan",
            str(run_plan),
            "--receipts",
            str(run_plan.parent),
            "--evidence-root",
            str(run_plan.parent),
            "--publication-root",
            str(analysis_root),
        ]
    )
    if export_status != 0:
        raise RuntimeError(f"aeread export-tables failed with status {export_status}")
    _copy_public_tables(analysis_root=analysis_root, publication_root=publication_root)
    cells = {str(cell["cell_id"]): cell for cell in run_plan_data.get("cells", ())}
    result_rows = _result_rows(receipts, cells)
    summary_payload, qualification_payload, readme_payload = _publication_reports(
        run_plan=run_plan_data, receipts=receipts, rows=result_rows
    )
    for name, payload in (
        ("README.md", readme_payload),
        ("reports/summary.json", summary_payload),
        ("reports/qualification.json", qualification_payload),
        ("tables/refund_results_by_scenario.csv", _csv_payload(result_rows)),
    ):
        assert_public_payload(name, payload)
        atomic_publish(publication_root / name, payload)
    if (publication_root / "publication_manifest.json").exists():
        manifest = rebuild_publication_manifest(publication_root)
    else:
        manifest = seal_publication_manifest(
            publication_root,
            publication_id=f"refund_v21_{run_plan.parent.name}",
            campaign_id="refund_v2",
            privacy_boundary={
                "included": "verified receipt projections, vetted canonical tables, and sanitized trajectories",
                "excluded": "raw provider responses, prompts, hidden facts, complete receipts, and reasoning",
            },
            source_bindings={
                "run_plan_id": run_plan_data["run_plan_id"],
                "run_plan_sha256": run_plan_data["plan_sha256"],
                "receipt_sha256s": [receipt["receipt_sha256"] for receipt in receipts],
            },
        )
    trajectory_rows, manifest = publish_trajectory_grain(publication_root, attempts)
    return {
        "run_plan": str(run_plan),
        "analysis_root": str(analysis_root),
        "publication_root": str(publication_root),
        "receipt_count": len(receipts),
        "trajectory_rows": trajectory_rows,
        "manifest_sha256": manifest["manifest_sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--publication-root", type=Path, required=True)
    parser.add_argument("--analysis-root", type=Path)
    args = parser.parse_args()
    print(json.dumps(publish_refund_v21(run_root=args.run_root, publication_root=args.publication_root, analysis_root=args.analysis_root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
