"""The TERMS-Bench Tier 1 register: derived only from sealed run evidence."""

from __future__ import annotations

import json
from pathlib import Path

from aeread_families.termsbench.failure_register import build, publish


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))


def _run_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs" / "termsbench"
    v1 = root / "pilot_v1" / "attempt_001"
    _write(v1 / "checkpoints" / "canary_probes" / "001.json",
           {"campaign_id": "v1", "status": "rejected", "failure_condition": "rate_limit",
            "failure_type": "ProviderFailure", "case_id": "termsbench.candid.overlap.1", "cost_usd": 0.0})
    _write(v1 / "checkpoints" / "canary_probes" / "002.json",
           {"campaign_id": "v1", "status": "admitted", "case_id": "termsbench.candid.overlap.1", "cost_usd": 0.0})
    _write(v1 / "checkpoints" / "00_termsbench.candid.overlap.1.json",
           {"campaign_id": "v1", "case_id": "termsbench.candid.overlap.1", "status": "complete",
            "inclusion_status": "included", "malformed_action_schema": False, "cost_usd": 0.01})
    # An operational abort whose checkpoint says only `execution_failure`; the
    # sealed ledger carries the typed condition.
    _write(v1 / "checkpoints" / "01_termsbench.candid.nodeal.2.json",
           {"campaign_id": "v1", "case_id": "termsbench.candid.nodeal.2", "status": "operational_failure",
            "failure_type": "SchedulerContractError", "failure_condition": "execution_failure", "cost_usd": 0.005})
    attempt = v1 / "executions" / "termsbench.candid.nodeal.2" / "run" / "attempt"
    _write(attempt / "artifacts" / "sha256" / "ab" / "abcd", {"failure_condition": "malformed_structured_output"})
    (attempt / "events.jsonl").write_text(
        json.dumps({"event_type": "provider_call_failed", "payload_ref": "artifacts/sha256/ab/abcd"}) + "\n"
    )
    v2 = root / "pilot_v2" / "attempt_001"
    _write(v2 / "checkpoints" / "canary_probes" / "001.json",
           {"campaign_id": "v2", "status": "admitted", "case_id": "termsbench.candid.overlap.1", "cost_usd": 0.0})
    # A measured malformed move: included, but a typed failure of the model.
    _write(v2 / "checkpoints" / "00_termsbench.candid.nodeal.2.json",
           {"campaign_id": "v2", "case_id": "termsbench.candid.nodeal.2", "status": "complete",
            "inclusion_status": "included", "malformed_action_schema": True, "cost_usd": 0.002})
    # A cell sealed as a typed exclusion by the campaign.
    _write(v2 / "checkpoints" / "01_termsbench.candid.overlap.3.json",
           {"campaign_id": "v2", "case_id": "termsbench.candid.overlap.3", "status": "failed",
            "failure_type": "SchedulerContractError", "failure_condition": "provider_contract",
            "failure_class": "integration_or_configuration", "inclusion_status": "excluded",
            "receipt_status": "invalid_measurement", "cost_usd": 0.001})
    return root


def test_the_register_types_every_failure_from_sealed_evidence(tmp_path: Path) -> None:
    root = _run_root(tmp_path)
    table, summary = build(run_root=root, repository_root=tmp_path)
    assert summary["failure_count"] == 4
    assert summary["by_stage"] == {"canary_probe": 1, "measurement": 1, "trajectory": 2}
    # The checkpoint's generic label never survives into the register.
    assert "execution_failure" not in summary["by_failure_condition"]
    assert summary["by_failure_condition"] == {
        "malformed_action_schema": 1,
        "malformed_structured_output": 1,
        "provider_contract": 1,
        "rate_limit": 1,
    }
    assert summary["by_attribution"] == {"environment": 1, "model": 2, "provider": 1}
    assert summary["by_regime"] == {"nodeal": 2, "overlap": 2}
    assert summary["cost_is_a_floor"] is False
    header, *rows = table.decode("utf-8").strip().splitlines()
    assert header.split(",")[0] == "campaign_id" and "source_artifact_sha256" in header
    for row in rows:
        assert len(row.rsplit(",", 1)[-1]) == 64
        assert row.rsplit(",", 2)[-2].startswith("runs/termsbench/")


def test_publish_is_regenerable_and_public(tmp_path: Path) -> None:
    root = _run_root(tmp_path)
    out = tmp_path / "evidence" / "termsbench_failure_register"
    first = publish(run_root=root, publication_root=out, repository_root=tmp_path)
    again = publish(run_root=root, publication_root=out, repository_root=tmp_path, regenerate=True)
    assert first["artifact_sha256"] == again["artifact_sha256"]
    assert (out / "tables" / "failures.csv").exists()
    assert json.loads((out / "reports" / "summary.json").read_text())["failure_count"] == 4
