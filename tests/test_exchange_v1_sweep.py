"""Exchange V1 sweep harness (D7): grid execution, stable CSV, failure isolation.

Keyless: all cells run --mode offline (scripted policy). The invariant under
test is that harness failures NEVER produce economic numbers — a crashed cell
is a `harness_error` row with empty metric columns, and the other cells finish.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from aeread import exchange_v1_sweep as sweep  # noqa: E402


def _write_config(tmp_path: Path, name: str, **overrides) -> Path:
    payload = {
        "name": name,
        "description": "test fixture",
        "num_agents": 3,
        "num_resources": 3,
        "units_per_home_resource": 10,
        "seed": 3,
        "rounds": 2,
        "controllers": [1],
        "utility_mode": "linear",
        "protocol": {"name": "test_protocol"},
    }
    payload.update(overrides)
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(payload))
    return path


def _read_csv(sweep_dir: Path) -> list[dict[str, str]]:
    with (sweep_dir / "sweep_results.csv").open() as fh:
        return list(csv.DictReader(fh))


def test_offline_grid_produces_one_row_and_run_dir_per_cell(tmp_path):
    config_a = _write_config(tmp_path, "cfg_a")
    config_b = _write_config(tmp_path, "cfg_b", world_type="ring_cycle", cycle_length=3)
    sweep_dir = sweep.run_sweep(
        [config_a, config_b],
        models=["offline"],
        seeds=[1, 2],
        mode="offline",
        out_root=tmp_path / "sweep",
        quiet=True,
    )
    rows = _read_csv(sweep_dir)
    assert len(rows) == 4
    assert [r["status"] for r in rows] == ["ok"] * 4
    assert list(rows[0].keys()) == sweep.CSV_COLUMNS
    for row in rows:
        run_dir = Path(row["run_dir"])
        assert (run_dir / "trace.jsonl").is_file()
        assert (run_dir / "summary.json").is_file()
        assert row["llm_calls"] == "0"
    # ring-cycle k3 cells must show zero applied mechanisms; procedural > 0
    by_config = {(r["config"], r["seed"]): r for r in rows}
    assert int(by_config[("cfg_a", "1")]["applied_mechanisms"]) > 0
    assert int(by_config[("cfg_b", "1")]["applied_mechanisms"]) == 0

    meta = json.loads((sweep_dir / "sweep_meta.json").read_text())
    assert meta["cells"] == 4
    assert meta["status_counts"] == {"ok": 4}


def test_crashed_cell_isolates_as_harness_error(tmp_path):
    good = _write_config(tmp_path, "cfg_good")
    missing = tmp_path / "cfg_missing.json"  # never written -> RunnerError inside the cell
    sweep_dir = sweep.run_sweep(
        [good, missing],
        models=["offline"],
        seeds=[1],
        mode="offline",
        out_root=tmp_path / "sweep",
        quiet=True,
    )
    rows = {r["config"]: r for r in _read_csv(sweep_dir)}
    assert rows["cfg_good"]["status"] == "ok"
    bad = rows["cfg_missing"]
    assert bad["status"] == "harness_error"
    assert "RunnerError" in bad["error"]
    # a harness error must never carry economic numbers
    for column in ("welfare_ratio", "final_welfare", "applied_mechanisms"):
        assert bad[column] == ""


def test_cost_ceiling_skips_remaining_cells(tmp_path):
    config = _write_config(tmp_path, "cfg_ceiling")
    sweep_dir = sweep.run_sweep(
        [config],
        models=["offline"],
        seeds=[1, 2, 3],
        mode="offline",
        out_root=tmp_path / "sweep",
        cost_ceiling_usd=0.0,  # offline cost is $0, so the first cell trips it
        quiet=True,
    )
    rows = _read_csv(sweep_dir)
    assert [r["status"] for r in rows] == ["ok", "skipped", "skipped"]
    assert "cost ceiling" in rows[1]["error"]
    meta = json.loads((sweep_dir / "sweep_meta.json").read_text())
    assert meta["aborted_reason"]
    assert meta["status_counts"] == {"ok": 1, "skipped": 2}
