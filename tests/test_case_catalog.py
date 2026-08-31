"""Structural checks for the discoverable, versioned case catalog."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "cases"


def test_exchange_catalog_separates_scored_cases_from_diagnostics() -> None:
    official = CASES / "exchange_v1" / "v0"
    scored = sorted(official.glob("case0*.json"))
    diagnostics = sorted((official / "diagnostics").glob("*.json"))

    assert [path.name for path in scored] == [
        "case01_visible_bilateral_ir.json",
        "case02_multiparty_clearing.json",
        "case03_hidden_discovery.json",
        "case04_consent_under_hidden_info.json",
    ]
    assert len(diagnostics) == 2
    assert all("__panel_" in path.stem for path in diagnostics)


def test_exchange_legacy_path_resolves_to_the_canonical_catalog() -> None:
    canonical = CASES / "exchange_v1" / "v0"
    legacy = ROOT / "configs" / "exchange_economy" / "cases_v0"

    assert legacy.is_symlink()
    assert legacy.resolve() == canonical.resolve()


def test_specialized_exchange_cases_are_catalogued() -> None:
    specialized = CASES / "exchange_v1" / "specialized"
    assert sorted(path.name for path in specialized.glob("*.json")) == [
        "bundle_under_budget_trip3.json",
        "procurement_electronics_q3.json",
    ]


def test_tau3_base_split_has_all_cases_and_provenance() -> None:
    base = CASES / "tau3_retail" / "base"

    assert len(list(base.glob("tau3.retail.base.*.json"))) == 114
    assert (base / "pins.json").is_file()
    assert (base / "pilot_manifest.json").is_file()


def test_generated_housing_family_is_discoverable() -> None:
    assert (CASES / "housing_v1" / "README.md").is_file()
