from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.procurement_allocation.case_matrix import CASE_VARIANCE_PATHS
from aeread_families.procurement_allocation.environment import (
    solve_full_information_upper_bound,
)
from aeread_families.procurement_allocation.regret_decomposition import (
    ANALYSIS_ID,
    BUNDLE_REPORTS,
    REGRET_TERMS,
    ReplayMismatchError,
    build_report,
    case_path_for_id,
    decompose_feasible_award,
    oracle_evaluation,
    publish_report,
    replay_action_trace,
    verified_bundle_report,
)
from aeread_families.procurement_allocation.runner import load_case


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def report() -> dict:
    return build_report(repository_root=REPOSITORY_ROOT)


def _family_case(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["payload"]


def _all_rows() -> list[tuple[str, dict]]:
    rows: list[tuple[str, dict]] = []
    for bundle in BUNDLE_REPORTS:
        report, _ = verified_bundle_report(REPOSITORY_ROOT / bundle.report_path)
        rows.extend((bundle.report_id, row) for row in report["rows"])
    return rows


def test_bundle_reports_exist_and_verify() -> None:
    assert len(BUNDLE_REPORTS) == 8
    total = 0
    for bundle in BUNDLE_REPORTS:
        report, file_sha = verified_bundle_report(REPOSITORY_ROOT / bundle.report_path)
        assert len(file_sha) == 64
        assert report["campaign_id"] == bundle.campaign_id
        total += len(report["rows"])
    assert total == 216


def test_tampered_bundle_report_is_rejected(tmp_path: Path) -> None:
    source = REPOSITORY_ROOT / BUNDLE_REPORTS[0].report_path
    value = json.loads(source.read_text(encoding="utf-8"))
    value["rows"][0]["contribution_margin_usd"] += 1.0
    target = tmp_path / "qualification.json"
    target.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        verified_bundle_report(target)


def test_case_path_resolves_every_published_case() -> None:
    for _, row in _all_rows():
        path = case_path_for_id(row["case_id"], repository_root=REPOSITORY_ROOT)
        case = load_case(path)
        assert case.case_id == row["case_id"]
        assert case.content_sha256 == row["case_content_sha256"]


def test_oracle_evaluation_matches_upper_bound() -> None:
    for path in CASE_VARIANCE_PATHS:
        family_case = _family_case(Path(path))
        upper = solve_full_information_upper_bound(family_case)
        oracle = oracle_evaluation(family_case)
        assert oracle["evaluation"]["feasible"] is True
        assert oracle["evaluation"]["contribution_margin_usd"] == pytest.approx(
            upper.contribution_margin_usd, abs=1e-6
        )
        assert oracle["information_cost_usd"] == pytest.approx(
            oracle["evaluation"]["information_cost_usd"]
        )


def test_replay_reproduces_every_published_row() -> None:
    for report_id, row in _all_rows():
        path = case_path_for_id(row["case_id"], repository_root=REPOSITORY_ROOT)
        replay = replay_action_trace(_family_case(path), row["action_trace"])
        outcome = replay["outcome"]
        assert outcome["feasible"] == row["feasible"], (report_id, row["case_id"])
        assert outcome["contribution_margin_usd"] == pytest.approx(
            row["contribution_margin_usd"], abs=1e-6
        )
        assert outcome["regret_to_upper_bound_usd"] == pytest.approx(
            row["regret_to_upper_bound_usd"], abs=1e-6
        )
        assert outcome["completed_kits"] == row["completed_kits"]
        assert outcome["termination_reason"] == row["termination_reason"]


def test_replay_rejects_trace_that_continues_after_termination() -> None:
    family_case = _family_case(Path(CASE_VARIANCE_PATHS[0]))
    trace = [
        {"ordinal": 1, "action": "defer", "status": "succeeded"},
        {"ordinal": 2, "action": "defer", "status": "succeeded"},
    ]
    with pytest.raises(ReplayMismatchError):
        replay_action_trace(family_case, trace)


def test_feasible_decomposition_sums_to_regret() -> None:
    decomposed = 0
    oracles: dict[str, dict] = {}
    for _, row in _all_rows():
        if not (row["feasible"] and row["decision"] == "award"):
            continue
        path = case_path_for_id(row["case_id"], repository_root=REPOSITORY_ROOT)
        family_case = _family_case(path)
        replay = replay_action_trace(family_case, row["action_trace"])
        if row["case_id"] not in oracles:
            oracles[row["case_id"]] = oracle_evaluation(family_case)
        terms = decompose_feasible_award(
            family_case, replay, oracle=oracles[row["case_id"]]
        )
        assert set(terms["terms"]) == set(REGRET_TERMS)
        total = sum(terms["terms"].values())
        assert total == pytest.approx(row["regret_to_upper_bound_usd"], abs=1e-6)
        assert terms["identity_residual_usd"] == pytest.approx(0.0, abs=1e-6)
        decomposed += 1
    assert decomposed > 60


def test_build_report_covers_every_row_and_binds_sources(report: dict) -> None:
    assert report["analysis_id"] == ANALYSIS_ID
    assert report["replay_integrity"]["rows_replayed"] == 216
    assert report["replay_integrity"]["mismatch_count"] == 0
    assert len(report["rows"]) == 216
    categories = {row["regret_category"] for row in report["rows"]}
    assert "feasible_award" in categories
    for bundle in BUNDLE_REPORTS:
        binding = report["sources"]["bundles"][bundle.report_id]
        assert len(binding["report_file_sha256"]) == 64
        assert len(binding["artifact_sha256"]) == 64
        summary = report["by_report"][bundle.report_id]
        assert summary["row_count"] == binding["row_count"]
        assert sum(summary["category_counts"].values()) == summary["row_count"]
    pooled = report["pooled_feasible_awards"]
    assert pooled["row_count"] > 60
    shares = pooled["term_share_of_regret"]
    assert sum(shares.values()) == pytest.approx(1.0, abs=1e-6)
    payload = {k: v for k, v in report.items() if k != "artifact_sha256"}
    assert report["artifact_sha256"] == hashlib.sha256(
        canonical_json_bytes(payload)
    ).hexdigest()


def test_publish_report_writes_manifest(tmp_path: Path, report: dict) -> None:
    root = tmp_path / "evidence" / ANALYSIS_ID
    manifest = publish_report(report, publication_root=root)
    written = json.loads(
        (root / "reports" / "regret_decomposition.json").read_text(encoding="utf-8")
    )
    assert written["artifact_sha256"] == report["artifact_sha256"]
    assert manifest["publication_id"] == ANALYSIS_ID
    assert manifest["artifacts"]["reports/regret_decomposition.json"] == hashlib.sha256(
        (root / "reports" / "regret_decomposition.json").read_bytes()
    ).hexdigest()
    with pytest.raises(FileExistsError):
        publish_report(report, publication_root=root)
    with pytest.raises(ValueError):
        publish_report(report, publication_root=tmp_path / "runs" / ANALYSIS_ID)


def test_replay_strips_null_counter_proposal_fields() -> None:
    family_case = _family_case(Path(CASE_VARIANCE_PATHS[0]))
    supplier = family_case["suppliers"][0]["supplier_id"]
    trace = [
        {"ordinal": 1, "action": "request_quote", "status": "succeeded", "supplier_id": supplier},
        {
            "ordinal": 2,
            "action": "counter_offer",
            "status": "succeeded",
            "supplier_id": supplier,
            "offer_id": f"offer_{supplier}_v1",
            "proposal": {
                "payment_terms_days": 45,
                "unit_price_usd": None,
                "moq": None,
                "refund_window_days": None,
                "return_freight_payer": None,
            },
        },
        {"ordinal": 3, "action": "defer", "status": "succeeded"},
    ]
    replay = replay_action_trace(family_case, trace)
    assert replay["terminal"]["reason"] == "deferred"
    assert replay["terminal"]["actions_used"] == 3

