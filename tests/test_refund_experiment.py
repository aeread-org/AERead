from __future__ import annotations

import json
import subprocess
import sys

from aeread.shared_runner.refund_experiment import analyze_paired_results


def _row(condition: str, world_seed: int, replicate: int, utility: float, *, status: str = "included"):
    return {"panel": "sample", "condition": condition, "world_seed": world_seed,
            "replicate": replicate, "status": status,
            "metrics": {"joint_utility": utility}}


def test_refund_analysis_aggregates_replicates_before_world_bootstrap() -> None:
    rows = []
    for world_seed in (11, 12, 13):
        for replicate in range(3):
            rows.append(_row("none", world_seed, replicate, -10.0))
            rows.append(_row("low", world_seed, replicate, 5.0))
    result = analyze_paired_results(
        rows, expected_replicates=3, bootstrap_draws=100, bootstrap_seed=7
    )
    assert result["complete_pair_world_count"] == 3
    assert result["condition_world_means"] == {"none": -10.0, "low": 5.0}
    assert result["mean_paired_difference_low_minus_none"] == 15.0
    assert result["cluster_bootstrap_95"] == [15.0, 15.0]
    assert result["resampling_unit"] == "world_seed"


def test_refund_analysis_reports_incomplete_world_without_imputing_zero() -> None:
    rows = [_row("none", 11, 0, -2.0), _row("low", 11, 0, 3.0),
            _row("none", 12, 0, -4.0), _row("low", 12, 0, 0.0, status="excluded")]
    result = analyze_paired_results(rows, expected_replicates=1, bootstrap_draws=50)
    assert result["complete_pair_world_count"] == 1
    assert result["incomplete_worlds"] == [12]
    assert result["mean_paired_difference_low_minus_none"] == 5.0
    assert result["missingness_bounds"] is None


def test_refund_experiment_cli_emits_housing_style_report_sections(tmp_path) -> None:
    output = tmp_path / "report"
    completed = subprocess.run(
        [sys.executable, "-m", "aeread.shared_runner.refund_experiment",
         "--provider", "fake", "--model", "refund-fixed-v1", "--revision", "1.0.0",
         "--world-seeds", "41001,41002", "--admission-world-seeds", "40999",
         "--replicates", "1", "--bootstrap-draws", "100", "--output", str(output)],
        check=True, capture_output=True, text=True,
    )
    cli = json.loads(completed.stdout)
    report = json.loads((output / "refund_experiment_summary.json").read_text())
    narrative = (output / "refund_experiment_report.md").read_text()
    assert cli["planned_cells"] == 4
    for key in ("design", "model_and_route", "run_plans", "receipt_coverage",
                "admission_results", "primary_analysis", "operational_results",
                "secondary_descriptive", "analysis_contract", "raw_evidence",
                "claim_boundaries", "artifact_sha256"):
        assert key in report
    assert report["primary_analysis"]["resampling_unit"] == "world_seed"
    assert report["receipt_coverage"]["evidence_verified"] == 6
    assert report["receipt_coverage"]["receipts_written"] == 6
    assert report["receipt_coverage"]["receipt_status"] == "complete"
    included = [row for row in report["rows"] if row["status"] == "included"]
    assert all(row["receipt_verified"] for row in included)
    assert all("bounded_regret" in row["metrics"] for row in included)
    assert all("utility_score" in row["metrics"] for row in included)
    assert all("transaction_score" in row["metrics"] for row in included)
    assert all(set(row["scores"]) == {"utility", "transaction"} for row in included)
    assert all("transaction_verification" in row for row in included)
    assert all("temporal_transaction" in row["verification_leaves"] for row in included)
    assert all("policy_penalty" in row["utility_components"] for row in included)
    assert "## Operational Results" in narrative
    assert "transaction score=" in narrative
    assert "## Claim Boundaries" in narrative
