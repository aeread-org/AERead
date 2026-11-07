"""The paired lemons comparison: world as the unit, pairing, and byte replay."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aeread_families.housing import lemons_comparison as comparison


def _cell(world: int, replicate: int, payoff: float, *, stratum: str = "favourite_is_lemon",
          stage: str = "variance_pilot", status: str = "completed", lemons: int = 0) -> dict:
    return {
        "world_seed": world, "replicate_index": replicate, "stratum": stratum, "stage": stage, "status": status,
        "tenant_net_payoff": payoff, "within_case_score": payoff / 1000, "abstention_correctness_rate": 1.0,
        "uninspected_lemon_signings": lemons, "inspection_count": 4,
        "reference_total": 100.0, "sign_anything_total": -50.0, "oracle_total": 900.0,
    }


def _bundle(root: Path, name: str, rows: list[dict]) -> None:
    tables = root / name / "tables"
    tables.mkdir(parents=True)
    (tables / "cells.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    (root / name / "publication_manifest.json").write_text(json.dumps({"campaign_id": name}))


@pytest.fixture
def evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(comparison, "EVIDENCE", tmp_path)
    monkeypatch.setattr(comparison, "OUT", tmp_path / "comparison")
    _bundle(tmp_path, comparison.LEFT, [
        _cell(1, 0, 300.0), _cell(1, 1, 100.0),
        _cell(2, 0, 50.0, stratum="favourite_is_sound", lemons=1), _cell(2, 1, 0.0, stratum="favourite_is_sound"),
        _cell(3, 0, 999.0),  # unpaired: the right bundle lost world 3
        _cell(1, 0, -500.0, stage="full_trajectory"),  # a gate cell is not pilot data
    ])
    _bundle(tmp_path, comparison.RIGHT, [
        _cell(1, 0, 100.0), _cell(1, 1, 100.0),
        _cell(2, 0, 25.0, stratum="favourite_is_sound"), _cell(2, 1, 0.0, stratum="favourite_is_sound"),
        _cell(3, 0, 0.0, status="operational_failure"),  # typed missingness, not a zero
    ])
    return tmp_path


def test_world_is_the_unit_and_only_completed_pilot_cells_count(evidence: Path) -> None:
    report = comparison.compare()
    overall = report["slices"]["overall"]["tenant_net_payoff"]
    assert report["paired_worlds"] == 2
    assert report["unpaired_worlds"] == {"left_only": [3], "right_only": []}
    # world 1: 200 vs 100; world 2: 25 vs 12.5 -> mean difference (100 + 12.5) / 2
    assert overall["left_mean"] == pytest.approx(112.5)
    assert overall["right_mean"] == pytest.approx(56.25)
    assert overall["difference"] == pytest.approx(56.25)
    assert (overall["worlds_left_higher"], overall["worlds_right_higher"]) == (2, 0)
    lemon = report["slices"]["overall"]["uninspected_lemon_signing_rate"]
    assert lemon["left_mean"] == pytest.approx(0.25) and lemon["right_mean"] == 0.0


def test_strata_partition_the_paired_worlds(evidence: Path) -> None:
    slices = comparison.compare()["slices"]
    assert slices["favourite_is_lemon"]["worlds"] + slices["favourite_is_sound"]["worlds"] == slices["overall"]["worlds"]
    assert slices["favourite_is_lemon"]["tenant_net_payoff"]["difference_ci95"] is None  # one world: no interval


def test_written_output_replays_and_detects_drift(evidence: Path) -> None:
    comparison.write()
    assert comparison.check()
    readme = evidence / "comparison" / "README.md"
    readme.write_text(readme.read_text() + "edited\n")
    assert not comparison.check()


def test_blind_signings_count_at_expected_value(evidence: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # tenant 0 signed listing 1 without inspecting it: expected 900 at its lemon probability, truly worth 400
    # (a lemon); tenant 1 signed listing 2 after inspecting: counted as realized.
    monkeypatch.setattr(comparison, "true_value", lambda seed, tenant, listing: 400.0 if listing == 1 else 1500.0)
    row = {"tenant_net_payoff": 100.0, "world_seed": 7, "commit_decisions": [
        {"decision": "sign", "informed": False, "expected_value": 900.0, "tenant_id": 0, "listing_id": 1},
        {"decision": "sign", "informed": True, "expected_value": 1500.0, "tenant_id": 1, "listing_id": 2},
        {"decision": "walk", "informed": False, "expected_value": 50.0, "tenant_id": 2, "listing_id": 3},
    ]}
    assert comparison._cell_value(row, "expected_net_payoff") == pytest.approx(100.0 + (900.0 - 400.0))
    assert comparison._cell_value({**row, "commit_decisions": []}, "expected_net_payoff") == 100.0


def test_every_interval_has_both_sides(evidence: Path) -> None:
    block = comparison.compare()["slices"]["overall"]["tenant_net_payoff"]
    assert block["left_ci95"] and block["right_ci95"] and block["difference_ci95"]
