"""Every published Housing v14 and v15 plan rebuilds from current source on this kernel (HL-T-11, HL-D-11).

A v15 plan pins the kernel's runtime modules by digest, so a kernel commit that touches them moves every plan id and
the old lookup by ``run_plan_id`` finds nothing. ``aeread_families.housing.price_replay`` (v15 and addendum A) and
``tools/cli_subjects/housing_v15_cli_replay.py`` (addendum B) rebuild each plan and match it with the receipt's own pins
put back: kernel-owned digests may have moved, family digests may not. The receipts are in the run roots, not in the
bundles, so the pins each published plan was sealed under are committed in ``tools/housing/price_recorded_pins.json``,
which ``tools/housing/price_recorded_pins.py --check`` rebuilds from the run roots.

A v14 plan's ``housing_feasible_zero_v1`` pin hashes ``runner.py`` with the kernel's ``task/evaluation.py``; it is
checked by recomputing it from the current ``runner.py`` and that file at the v14 kernel (``git show 6aaf46bb:...``).
Without that commit (a shallow clone) the v14 rebuild skips with the reason ``price_replay.V14_AT_PUBLISHING_KERNEL``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import ImplementationPin, is_kernel_pin
from aeread_families.housing import price_replay

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "cli_subjects"))
import housing_v15_cli_replay as cli_replay  # noqa: E402

TABLE = json.loads((ROOT / "tools/housing/price_recorded_pins.json").read_text(encoding="utf-8"))["plans"]
EVIDENCE = ROOT / "evidence/housing"
V15 = {"housing_lemons_price_v15_confirmatory": price_replay, "housing_lemons_price_v15_glm_addendum": price_replay,
       "housing_lemons_price_v15_cli_addendum": cli_replay}


def _published(bundle: str, name: str = "receipts/projections.jsonl") -> dict[str, str | None]:
    rows = (json.loads(line) for line in (EVIDENCE / bundle / name).read_text(encoding="utf-8").splitlines())
    return {row["run_plan_id"]: row.get("run_plan_sha256") for row in rows if row.get("run_plan_id")}


def _receipt(plan_id: str) -> dict:
    entry = TABLE[plan_id]
    return {"run_plan_id": plan_id, "run_plan_sha256": entry["run_plan_sha256"],
            "plan_implementation_pins": entry["plan_implementation_pins"]}


def test_the_table_names_every_published_plan_and_its_digest() -> None:
    for bundle in V15:
        for plan_id, sha in _published(bundle).items():
            assert TABLE[plan_id]["bundle"] == bundle and TABLE[plan_id]["run_plan_sha256"] == sha
    for bundle in ("housing_lemons_price_confirmatory_v14", "housing_lemons_price_confirmatory_v14_gemini_fill"):
        assert set(_published(bundle, "tables/cells.jsonl")) <= set(TABLE)


@pytest.mark.parametrize("bundle", sorted(V15))
def test_every_published_v15_plan_rebuilds_with_its_recorded_pins(bundle: str) -> None:
    for plan_id in sorted(_published(bundle)):
        receipt = _receipt(plan_id)
        setup = V15[bundle].setup_for_receipt(receipt)
        assert price_replay.sealed_plan(setup.plan, receipt).run_plan_id == plan_id


def test_a_receipt_whose_family_pin_moved_is_refused() -> None:
    # Counterexample: the same receipt with one family pin's digest changed rebuilds nothing.
    plan_id = next(k for k, v in TABLE.items() if v["bundle"] == "housing_lemons_price_v15_confirmatory")
    receipt = _receipt(plan_id)
    pins = [dict(pin) for pin in receipt["plan_implementation_pins"]]
    family = next(pin for pin in pins if not is_kernel_pin(ImplementationPin.from_dict(pin)))
    family["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="with its recorded pins"):
        price_replay.setup_for_receipt({**receipt, "plan_implementation_pins": pins})


V14 = ("housing_lemons_price_confirmatory_v14", "housing_lemons_price_confirmatory_v14_gemini_fill")


def _v14_plans() -> list[str]:
    return sorted({p for bundle in V14 for p in _published(bundle, "tables/cells.jsonl")})


def test_every_published_v14_plan_rebuilds_with_its_bridge_recomputed() -> None:
    if price_replay.sealing_bridge_digest() is None:
        pytest.skip(price_replay.V14_AT_PUBLISHING_KERNEL)
    plans = _v14_plans()
    assert len(plans) == 8
    for plan_id in plans:
        receipt = _receipt(plan_id)
        setup = price_replay.setup_for_receipt(receipt)
        assert price_replay.sealed_plan(setup.plan, receipt).run_plan_id == plan_id


def test_a_v14_bridge_that_runner_py_no_longer_reproduces_is_refused(monkeypatch) -> None:
    # Counterexample: the digest the current runner.py and the v14 kernel file would give, had runner.py changed.
    monkeypatch.setattr(price_replay, "sealing_bridge_digest", lambda: "1" * 64)
    with pytest.raises(ValueError, match="with its recorded pins"):
        price_replay.setup_for_receipt(_receipt(_v14_plans()[0]))


def test_without_the_v14_kernel_in_history_a_v14_receipt_is_refused_with_the_reason(monkeypatch) -> None:
    # A shallow clone cannot check the bridge: the receipt is refused with the reason, never accepted.
    monkeypatch.setattr(price_replay, "sealing_bridge_digest", lambda: None)
    with pytest.raises(price_replay.SealingKernelUnavailable, match="publishing kernel 6aaf46bb"):
        price_replay.setup_for_receipt(_receipt(_v14_plans()[0]))
