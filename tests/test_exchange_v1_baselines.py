"""Tests for the v1 frozen config set (D1) and the deterministic baselines CLI.

Cost note: the protocol-constrained oracle is cheap on limited-contact configs
(v1_main: 1 visible contact) but expensive on full-visibility ladder configs, so
every compute_baselines/freeze call here uses v1_main with rounds<=2. The
full-set D1 acceptance test avoids baseline computation entirely.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from aeread.exchange_v1 import economy as ex  # noqa: E402
from aeread.exchange_v1 import baselines as bl  # noqa: E402

CONFIG_DIR = ROOT / "configs" / "exchange_economy" / "releases" / "v1"
FROZEN_SET = sorted(p for p in CONFIG_DIR.glob("v1_*.json") if p.name != "v1_manifest.json")
V1_MAIN = CONFIG_DIR / "v1_main.json"


def test_frozen_set_is_v1_main_plus_six_ladder_configs():
    names = [p.name for p in FROZEN_SET]
    assert "v1_main.json" in names
    assert sum(1 for n in names if n.startswith("v1_ladder_l")) == 6
    assert len(names) == 7


def test_every_frozen_config_passes_d1_acceptance():
    for path in FROZEN_SET:
        violations = bl.d1_acceptance_violations(path)
        assert violations == [], f"{path.name}: {violations}"


def test_v1_main_uses_response_aware_finalization_and_partial_clearing():
    config = ex.load_experiment_config(V1_MAIN)
    assert config.protocol.atomic_commit is False
    assert config.protocol.partial_clearing is True


def test_compute_baselines_record_is_deterministic_and_well_formed():
    record = bl.compute_baselines(V1_MAIN, rounds=2, random_samples=1)

    assert record.config_name == "v1_main"
    assert record.no_op_gain == 0.0
    for value in (
        record.random_mean_gain,
        record.greedy_gain,
        record.stronger_heuristic_gain,
        record.information_constrained_gain,
        record.greedy_social_optimum_welfare_gain,
        record.social_optimum_welfare_gain,
    ):
        assert math.isfinite(value) and value >= 0.0
    assert record.sha256 == hashlib.sha256(V1_MAIN.read_bytes()).hexdigest()
    assert set(record.ordering) == {
        "random_lt_greedy",
        "greedy_lt_stronger_heuristic",
        "stronger_heuristic_lt_information_constrained",
    }

    again = bl.compute_baselines(V1_MAIN, rounds=2, random_samples=1)
    assert again == record


def test_freeze_then_check_round_trip(tmp_path):
    dest = tmp_path / V1_MAIN.name
    shutil.copy(V1_MAIN, dest)
    manifest_path = tmp_path / "v1_manifest.json"

    manifest, records = bl.freeze([dest], manifest_path, rounds=1, random_samples=1)
    assert len(records) == 1
    assert bl.check(manifest_path) == []

    # content drift is detected and names the config
    raw = json.loads(dest.read_text())
    raw["rounds"] = raw["rounds"] + 1
    dest.write_text(json.dumps(raw, indent=2) + "\n")
    failures = bl.check(manifest_path)
    assert any("content drift" in f and dest.name in f for f in failures)


def test_freeze_refuses_and_check_flags_missing_metadata_field(tmp_path):
    manifest_path = tmp_path / "v1_manifest.json"

    # freeze itself refuses a config failing D1 acceptance
    broken = tmp_path / "broken_v1_main.json"
    raw = json.loads(V1_MAIN.read_text())
    del raw["interpretation_if_failed"]
    broken.write_text(json.dumps(raw, indent=2) + "\n")
    with pytest.raises(ValueError, match="interpretation_if_failed"):
        bl.freeze([broken], manifest_path, rounds=1, random_samples=1)

    # and check() reports it if the drift happened after a valid freeze
    valid = tmp_path / V1_MAIN.name
    shutil.copy(V1_MAIN, valid)
    bl.freeze([valid], manifest_path, rounds=1, random_samples=1)
    raw_valid = json.loads(valid.read_text())
    del raw_valid["interpretation_if_failed"]
    valid.write_text(json.dumps(raw_valid, indent=2) + "\n")
    failures = bl.check(manifest_path)
    assert any("interpretation_if_failed" in f for f in failures)
    assert any("content drift" in f for f in failures)


def test_ordering_values_match_validity_result_on_v1_main():
    from aeread.exchange_v1 import validity as validity

    record = bl.compute_baselines(V1_MAIN, rounds=2, random_samples=1)
    config = ex.load_experiment_config(V1_MAIN)
    result = validity.evaluate_config_validity(config, rounds=2, random_samples=1)

    assert record.random_mean_gain == pytest.approx(result.random_mean_gain)
    assert record.greedy_gain == pytest.approx(result.greedy_gain)
    assert record.stronger_heuristic_gain == pytest.approx(result.stronger_heuristic_gain)
    assert record.information_constrained_gain == pytest.approx(result.information_constrained_gain)
    ineq = record.ordering["random_lt_greedy"]
    assert ineq.left_value == pytest.approx(result.random_mean_gain)
    assert ineq.right_value == pytest.approx(result.greedy_gain)


def test_ordering_cell_distinguishes_tie_from_inversion():
    from aeread.exchange_v1 import validity as validity

    def make_record(ordering):
        return bl.BaselineRecord(
            config_name="x", config_path="x.json", sha256="0" * 64, rounds=1, seed=0,
            no_op_gain=0.0, random_mean_gain=0.0, greedy_gain=0.0,
            stronger_heuristic_gain=0.0, information_constrained_gain=0.0,
            hidden_discovery_gain=0.0, greedy_applied_rounds=0,
            stronger_heuristic_applied_rounds=0, information_constrained_applied_rounds=0,
            greedy_social_optimum_welfare_gain=0.0, social_optimum_welfare_gain=0.0,
            ordering=ordering,
        )

    strict = validity.ValidityInequality("a", "b", 1.0, 2.0, passed=True)
    tie = validity.ValidityInequality("a", "b", 2.0, 2.0, passed=False)
    inverted = validity.ValidityInequality("a", "b", 3.0, 2.0, passed=False)

    assert bl._ordering_cell(make_record({"x": strict})) == "pass"
    assert bl._ordering_cell(make_record({"x": tie})) == "tie(x)"
    assert bl._ordering_cell(make_record({"x": inverted})) == "INVERTED(x)"
    assert bl._ordering_cell(make_record({"x": inverted, "y": tie})) == "INVERTED(x) tie(y)"


def test_records_from_manifest_round_trips_the_frozen_manifest():
    manifest_path = CONFIG_DIR / "v1_manifest.json"
    records = bl.records_from_manifest(manifest_path)
    assert len(records) == 7
    by_name = {r.config_name: r for r in records}
    assert "v1_main" in by_name
    for record in records:
        assert record.sha256 == bl.file_sha256(record.config_path)


def test_markdown_table_has_one_row_per_config():
    record = bl.compute_baselines(V1_MAIN, rounds=1, random_samples=1)
    other = dataclasses.replace(record, config_name="v1_other")
    md = bl.records_to_markdown([record, other])
    table_rows = [line for line in md.splitlines() if line.startswith("| v1_")]
    assert len(table_rows) == 2
