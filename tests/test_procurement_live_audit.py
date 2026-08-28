"""Independent reporting arithmetic must use worlds, not episode pseudo-replication."""
import json

import pytest

from examples.verify_procurement_live import audit_live_run, recompute_panel


def panel_rows():
    scores = {11: {"off": [.1, .2, .3], "low": [.5, .6, .7]},
              12: {"off": [.9, .8, .7], "low": [.2, .1, 0.]}}
    return [{"world_seed": world, "condition_id": condition, "replicate_index": repeat,
             "status": "completed", "within_case_score": score}
            for world, conditions in scores.items() for condition, values in conditions.items()
            for repeat, score in enumerate(values)]


def test_independent_report_recomputes_world_means_and_cluster_interval():
    result = recompute_panel(panel_rows(), worlds=[11, 12], conditions=["off", "low"],
                             replicates=3, bootstrap_draws=10000, bootstrap_seed=20260827)
    assert result["complete_world_count"] == 2
    assert result["condition_means"] == pytest.approx({"off": .5, "low": .35})
    assert result["mean_paired_difference"] == pytest.approx(-.15)
    assert result["cluster_bootstrap_95"] == pytest.approx([-.7, .4])


def test_independent_report_preserves_missing_worlds_and_negative_legal_scores():
    rows = panel_rows()
    rows[0]["within_case_score"] = -.2
    rows[-1].update(status="operational_failure", within_case_score=None)
    result = recompute_panel(rows, worlds=[11, 12], conditions=["off", "low"],
        replicates=3, bootstrap_draws=100, bootstrap_seed=1,
        score_support_by_world={11: (-.3, 1), 12: (-.1, 1)})
    assert result["planned_world_count"] == 2 and result["complete_world_count"] == 1
    assert result["cluster_bootstrap_95"] is None
    assert result["missingness_difference_bounds"] == pytest.approx([(-.8+.2/3+.5)/2, (-.8+1.3/3+.5)/2])


def test_independent_report_rejects_duplicate_episode_identities():
    rows = panel_rows()
    with pytest.raises(ValueError, match="identity"):
        recompute_panel(rows + [rows[0]], worlds=[11, 12], conditions=["off", "low"],
                        replicates=3, bootstrap_draws=100, bootstrap_seed=1)


def test_live_audit_cannot_label_scripted_evidence_as_model_performance(tmp_path):
    (tmp_path / "live_study.json").write_text(json.dumps({"evidence_kind": "scripted_instrumentation_only"}))
    with pytest.raises(ValueError, match="native_live_provider"):
        audit_live_run(tmp_path)
