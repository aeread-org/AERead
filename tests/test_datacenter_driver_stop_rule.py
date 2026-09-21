"""The world-panel driver halts on consecutive operational failures (DC-T-08).

With the network down overnight the driver walked 14 cells of a design, each
failing in 0 s as ``transport``, and reported 31% missingness as if it were
the model's. The limit lives in the contract (schema 0.3), the halt writes
every unreached cell as typed missingness that ``--retry-failed`` can set
aside and run, and the summary records the halt.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from aeread_families.datacenter_development.stack_runner import ProviderFailure
from aeread_families.datacenter_development.world_campaign import (
    CONTRACT_SCHEMA_VERSIONS,
    HALT_CONDITION,
    archive_failed_attempt,
    halt_record,
    load_contract,
    publish,
    run_campaign,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PILOT = REPOSITORY_ROOT / "configs" / "datacenter_development_v2_world_panel_v1.json"


def _contract(tmp_path: Path, **execution) -> Path:
    contract = json.loads(PILOT.read_text())
    contract["schema_version"] = CONTRACT_SCHEMA_VERSIONS[2]
    contract["campaign_id"] = "datacenter_development_v2_world_panel_stop_rule_test"
    contract["execution"]["provider_cooldown_seconds_after_cell"] = 0.0
    contract["execution"].update(execution)
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")
    return path


def test_the_limit_is_a_contract_field_of_schema_zero_three_only(tmp_path) -> None:
    assert load_contract(_contract(tmp_path, max_consecutive_operational_failures=3))["execution"]["max_consecutive_operational_failures"] == 3
    for bad in (0, -1, True, "3"):
        with pytest.raises(ValueError, match="positive integer"):
            load_contract(_contract(tmp_path, max_consecutive_operational_failures=bad))
    contract = json.loads(_contract(tmp_path).read_text())
    path = tmp_path / "missing.json"
    path.write_text(json.dumps(contract))
    with pytest.raises(ValueError, match="execution fields differ"):
        load_contract(path)  # 0.3 without the limit
    contract["schema_version"] = CONTRACT_SCHEMA_VERSIONS[1]
    contract["execution"]["max_consecutive_operational_failures"] = 3
    path.write_text(json.dumps(contract))
    with pytest.raises(ValueError, match="execution fields differ"):
        load_contract(path)  # 0.2 may not carry it


class _Outage:
    """A route whose every call dies in transport, as on 2026-09-21."""

    async def complete(self, request):
        raise ProviderFailure("transport", "simulated outage", retryable=True)


def test_a_run_halts_after_the_limit_and_writes_the_rest_as_typed_missingness(tmp_path) -> None:
    contract_path = _contract(tmp_path, max_consecutive_operational_failures=2)
    run_root = tmp_path / "run"
    summary = asyncio.run(
        run_campaign(contract_path=contract_path, run_root=run_root, stop_after="live", provider_factory=_Outage)
    )
    halt = halt_record(summary)
    assert halt == {
        "condition": HALT_CONDITION,
        "limit": 2,
        "after_cell": halt["after_cell"],
        "cells_not_attempted": 46,
    }
    rows = [json.loads((cell / "result.json").read_text()) for cell in sorted((run_root / "live").iterdir()) if cell.is_dir()]
    attempted = [row for row in rows if row["failure"]["failure_condition"] == "transport"]
    halted = [row for row in rows if row["failure"]["failure_condition"] == HALT_CONDITION]
    assert len(rows) == 48 and len(attempted) == 2 and len(halted) == 46
    assert all(row["receipt_sha256"] for row in attempted)
    assert all(row["receipt_sha256"] is None and row["receipt_status"] == "not_attempted" for row in halted)
    assert {row["failure"]["halted_after_cell"] for row in halted} == {halt["after_cell"]}
    assert halt["after_cell"] in {row["cell_key"] for row in attempted}
    assert summary["models"][0]["operational_failure_cells"] == 48 if "models" in summary else True

    # A halted run still publishes, as typed missingness with no receipt to bind.
    published = publish(run_root=run_root, publication_root=tmp_path / "evidence")
    cells = [json.loads(line) for line in (tmp_path / "evidence" / "tables" / "cells.jsonl").read_text().splitlines() if line.strip()]
    assert len(cells) == 48 and sum(c["failure"]["failure_condition"] == HALT_CONDITION for c in cells) == 46
    manifest = json.loads((tmp_path / "evidence" / "publication_manifest.json").read_text())
    assert len(manifest["source_receipt_sha256s"]) == 2

    # And --retry-failed sets a halted cell aside like any failed cell.
    cell_root = run_root / "live" / halted[0]["cell_key"]
    assert archive_failed_attempt(cell_root) == 1
    assert not (cell_root / "result.json").exists()


def test_contracts_without_the_limit_keep_running_to_the_end(tmp_path) -> None:
    """0.1 and 0.2 contracts have no stop rule, and their sealed runs must not
    acquire one retroactively: every cell is attempted, none is halted."""

    contract = json.loads(PILOT.read_text())
    contract["execution"]["provider_cooldown_seconds_after_cell"] = 0.0
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract))
    summary = asyncio.run(run_campaign(contract_path=path, run_root=tmp_path / "run", stop_after="live", provider_factory=_Outage))
    assert halt_record(summary) is None
    rows = [json.loads((cell / "result.json").read_text()) for cell in sorted((tmp_path / "run" / "live").iterdir()) if cell.is_dir()]
    assert len(rows) == 48 and all(row["failure"]["failure_condition"] == "transport" for row in rows)
