"""The evaluation setup a published pay-or-test version 3 receipt was sealed under, for ``aeread verify-replay``.

    PYTHONPATH=src:tools/cli_subjects aeread verify-replay evidence/procurement_allocation/<campaign_id> \\
        --run-root <run root> --setup pay_or_test_v3_replay:setup_for_receipt

A receipt names its case and its run-plan digest, not its campaign. The candidates are the campaigns published under
``evidence/procurement_allocation/*/reports/campaign.json`` (``pay_or_test_v3_publication``) on the receipt's pack.
Each candidate's setup is rebuilt from current source by the driver that made the run, for the receipt's case and, for
an OpenRouter run, each of its request seeds; the one whose plan, with the receipt's kernel-owned pins put back
(``plan_with_recorded_pins``: kernel bytes may have moved since sealing, family bytes may not), has the receipt's
digest is returned. When none matches, the error names the campaigns tried, and verify-replay reports the row as
``differs``.

The drivers live in ``tools/cli_subjects``, so that directory goes on ``PYTHONPATH`` with ``src``.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import ImplementationPin, PlanResolutionError, plan_with_recorded_pins
from aeread_families.procurement_allocation import pay_or_test_v3_case_matrix as pack_module

REPOSITORY = Path(__file__).resolve().parents[2]
EVIDENCE = REPOSITORY / "evidence" / "procurement_allocation"


@lru_cache(maxsize=None)
def campaigns() -> tuple[dict[str, Any], ...]:
    """Every published version 3 campaign record."""
    records = []
    for path in sorted(EVIDENCE.glob("*/reports/campaign.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("schema_version") == "aeread.procurement_pay_or_test_v3_campaign/0.1":
            records.append(record)
    return tuple(records)


def _case_path(case_id: str) -> Path:
    family, pack, slug = case_id.split(".")
    return pack_module.pack_root(pack) / f"{slug}.json"


def _setups(record: Mapping[str, Any], case_path: Path):
    """Each setup the campaign's driver could have sealed this case under (one an OpenRouter request seed)."""
    driver = record["driver_path"]
    if driver.endswith("pay_or_test_v3_cli.py"):
        import pay_or_test_v3_cli as cli
        yield cli.build_setup(record["subject"], case_path, record["provider_runtime"])
    elif driver.endswith(("pay_or_test_v3_openrouter.py", "pay_or_test_v3_control.py")):
        import pay_or_test_v3_control  # noqa: F401 - registers the control's candidates beside the flash subjects
        import pay_or_test_v3_openrouter as flash
        for seed in record["inference_seeds"]:
            yield flash.build_setup(record["subject"], case_path, int(seed))
    elif driver.endswith("pay_or_test_v3_baselines.py"):
        from aeread_families.procurement_allocation import pay_or_test_v3_baselines as baselines
        yield baselines.build_setup(case_path)
    else:
        raise ValueError(f"unknown driver {driver!r}")


def _recorded_pins(receipt: Mapping[str, Any]) -> tuple[ImplementationPin, ...]:
    """The pins the receipt was sealed under, as the kernel's audit reads them."""
    return tuple(ImplementationPin.from_dict(item) for item in receipt.get("plan_implementation_pins") or ())


def setup_for_receipt(receipt: Mapping[str, Any]):
    case_id, expected = receipt["case_id"], receipt["run_plan_sha256"]
    pack = case_id.split(".")[1]
    tried = []
    for record in campaigns():
        if record.get("pack") != pack:
            continue
        tried.append(record["campaign_id"])
        for setup in _setups(record, _case_path(case_id)):
            try:
                plan, _drift = plan_with_recorded_pins(setup.plan, _recorded_pins(receipt))
            except PlanResolutionError:
                continue
            if plan.plan_sha256 == expected:
                return setup
    raise ValueError(f"no published version 3 campaign rebuilds plan {expected[:16]} for {case_id}; tried {tried}")
