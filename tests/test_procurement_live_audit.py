"""Independent reporting arithmetic must use worlds, not episode pseudo-replication."""
import json
import hashlib
from decimal import Decimal

import pytest

from examples.verify_procurement_live import (
    audit_live_run, audit_prior_spend, audit_unknown_billing_recovery,
    recompute_panel,
)
from aeread.shared_runner.resolver import canonical_json_bytes


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


def test_prior_spend_preserves_every_admission_charge_and_checks_hashes(tmp_path):
    entries = []
    for index, cost in enumerate((.01, .02)):
        directory = tmp_path / str(index)
        directory.mkdir()
        raw = json.dumps({"total_known_cost_usd_including_admission": cost}).encode()
        (directory / "summary.json").write_bytes(raw)
        entries.append({"evidence_root": str(directory), "summary_path": "summary.json",
                        "summary_sha256": hashlib.sha256(raw).hexdigest(), "recorded_cost_usd": cost})
    authorization = {"prior_runs": entries, "prior_recorded_cost_usd": .03,
                     "remaining_run_limit_usd": 4.97, "approved_total_usd": 5}
    assert audit_prior_spend(authorization) == Decimal('.03')
    with pytest.raises(ValueError, match="authorization"):
        audit_prior_spend({**authorization, "remaining_run_limit_usd": 5})
    (tmp_path / "0/summary.json").write_text('{}')
    with pytest.raises(ValueError, match="hash"):
        audit_prior_spend(authorization)


def test_prior_spend_conservatively_reserves_lost_temporary_evidence():
    authorization = {
        "prior_runs": [],
        "lost_prior_runs": [{
            "evidence_status": "unrecoverable_after_temporary_storage_cleanup",
            "known_recorded_cost_usd": .333345078,
            "unknown_call_count": 2,
            "per_call_reserve_usd": .04,
            "reserved_cost_usd": .413345078,
        }],
        "prior_recorded_cost_usd": .413345078,
        "remaining_run_limit_usd": 4.586654922,
        "approved_total_usd": 5,
    }
    assert audit_prior_spend(authorization) == Decimal(".413345078")

    understated = {**authorization, "lost_prior_runs": [{
        **authorization["lost_prior_runs"][0], "reserved_cost_usd": .40,
    }]}
    with pytest.raises(ValueError, match="reserve"):
        audit_prior_spend(understated)

    unclassified = {**authorization, "lost_prior_runs": [{
        **authorization["lost_prior_runs"][0], "evidence_status": "missing",
    }]}
    with pytest.raises(ValueError, match="status"):
        audit_prior_spend(unclassified)


def _write_unknown_recovery_checkpoint(root, **changes):
    checkpoint = {
        "spec_version": "aeread.unknown_billing_recovery/1",
        "prefix_result_sha256s": ["included-hash", "unknown-hash"],
        "acknowledged_unknown_cost_provider_call_count": 1,
        "unknown_call_reserve_usd_each": .04,
        "reserved_unknown_cost_usd": .04,
        "request_cost_upper_bounds_usd": [.01],
        "account_usage_before_usd": 100.0,
        "account_usage_after_usd": 100.008,
        "account_known_cost_usd": .002,
        "account_unexplained_delta_usd": .006,
    }
    checkpoint.update(changes)
    checkpoint["result_sha256"] = hashlib.sha256(canonical_json_bytes(checkpoint)).hexdigest()
    (root / "recovery_checkpoint.json").write_bytes(canonical_json_bytes(checkpoint) + b"\n")


def test_live_audit_accepts_only_sealed_reserved_unknown_timeout_prefix(tmp_path):
    rows = [
        {"result_sha256": "included-hash", "status": "completed",
         "unknown_cost_provider_call_count": 0, "failure": None},
        {"result_sha256": "unknown-hash", "status": "operational_failure",
         "unknown_cost_provider_call_count": 1,
         "failure": {"condition": "timeout"}},
    ]
    _write_unknown_recovery_checkpoint(tmp_path)
    result = audit_unknown_billing_recovery(tmp_path, rows)
    assert result["acknowledged_unknown_cost_provider_call_count"] == 1
    assert result["reserved_unknown_cost_usd"] == Decimal(".04")
    assert result["acknowledged_result_sha256s"] == ["included-hash", "unknown-hash"]

    _write_unknown_recovery_checkpoint(tmp_path, reserved_unknown_cost_usd=.005)
    with pytest.raises(ValueError, match="reserve|bound"):
        audit_unknown_billing_recovery(tmp_path, rows)

    _write_unknown_recovery_checkpoint(tmp_path)
    with pytest.raises(ValueError, match="timeout|unknown"):
        audit_unknown_billing_recovery(tmp_path, [rows[0], {**rows[1], "status": "completed"}])


def test_live_audit_requires_cumulative_unknown_recovery_predecessor(tmp_path):
    predecessor, current = tmp_path / "predecessor", tmp_path / "current"
    predecessor.mkdir()
    current.mkdir()
    _write_unknown_recovery_checkpoint(
        predecessor,
        prefix_result_sha256s=["old-unknown"],
        acknowledged_unknown_cost_provider_call_count=1,
        reserved_unknown_cost_usd=.04,
        request_cost_upper_bounds_usd=[.01],
    )
    previous = json.loads((predecessor / "recovery_checkpoint.json").read_text())
    rows = [
        {"result_sha256": "old-unknown", "status": "operational_failure",
         "unknown_cost_provider_call_count": 1, "failure": {"condition": "timeout"}},
        {"result_sha256": "new-unknown", "status": "operational_failure",
         "unknown_cost_provider_call_count": 1, "failure": {"condition": "timeout"}},
    ]
    _write_unknown_recovery_checkpoint(
        current,
        prefix_result_sha256s=["old-unknown", "new-unknown"],
        acknowledged_unknown_cost_provider_call_count=2,
        reserved_unknown_cost_usd=.08,
        request_cost_upper_bounds_usd=[.01, .01],
        source_root=str(predecessor),
        predecessor_checkpoint_sha256=previous["result_sha256"],
    )
    result = audit_unknown_billing_recovery(current, rows)
    assert result["acknowledged_unknown_cost_provider_call_count"] == 2
    assert result["reserved_unknown_cost_usd"] == Decimal(".08")

    _write_unknown_recovery_checkpoint(
        current,
        prefix_result_sha256s=["old-unknown", "new-unknown"],
        acknowledged_unknown_cost_provider_call_count=2,
        unknown_call_reserve_usd_each=.02,
        reserved_unknown_cost_usd=.04,
        request_cost_upper_bounds_usd=[.01, .01],
        source_root=str(predecessor),
        predecessor_checkpoint_sha256=previous["result_sha256"],
    )
    with pytest.raises(ValueError, match="predecessor|cumulative|reserve"):
        audit_unknown_billing_recovery(current, rows)
