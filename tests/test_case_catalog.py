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


def test_procurement_grounding_development_case_is_discoverable() -> None:
    family = CASES / "procurement_grounding_v1"

    assert (family / "README.md").is_file()
    assert sorted(path.name for path in (family / "dev").glob("*.json")) == [
        "procurement_grounding_231_projects.json"
    ]


def test_procurement_allocation_development_case_is_discoverable() -> None:
    family = CASES / "procurement_allocation_v1"

    assert (family / "README.md").is_file()
    assert sorted(path.name for path in (family / "dev").glob("*.json")) == [
        "deadline_cost.json",
        "moq_capacity_split.json",
        "quality_refund.json",
        "quality_speed_margin.json",
        "service_defer.json",
        "variant_substitution.json",
        "working_capital.json",
    ]
    assert sorted(path.name for path in (family / "blinded_v3").glob("*.json")) == [
        "deadline_cost.json",
        "moq_capacity_split.json",
        "quality_refund.json",
        "service_defer.json",
        "variant_substitution.json",
        "working_capital.json",
    ]


def test_datacenter_development_cases_are_discoverable() -> None:
    family = CASES / "datacenter_development_v1"

    assert (family / "README.md").is_file()
    assert (family / "dev" / "service_loan_bankability_001.json").is_file()
    assert (family / "v1" / "power_epc_bankability_001.json").is_file()
    assert (family / "v2" / "full_stack_amendment_001.json").is_file()
    assert (family / "v2" / "objective_bounded_001.json").is_file()


def test_datacenter_development_terms_pilot_is_discoverable() -> None:
    family = CASES / "datacenter_development_terms_v1"
    pilot = family / "pilot"

    assert (family / "README.md").is_file()
    assert (pilot / "manifest.json").is_file()
    assert (pilot / "cases.jsonl").is_file()
    assert (pilot / "source_catalog_private.json").is_file()
    assert (pilot / "project_manifest_private.json").is_file()


def test_datacenter_counteroffer_adoption_ladder_is_discoverable() -> None:
    family = CASES / "datacenter_counteroffer_adoption_v1"

    assert (family / "README.md").is_file()
    for split_name in ("v1", "v2", "v3"):
        assert sorted(
            path.name for path in (family / split_name).glob("*.json")
        ) == [
            "land_001.json",
            "land_power_001.json",
            "land_power_epc_001.json",
        ]


def test_datacenter_counteroffer_salience_pair_is_discoverable() -> None:
    family = CASES / "datacenter_counteroffer_salience_v1"

    assert (family / "README.md").is_file()
    assert sorted(path.name for path in (family / "v1").glob("*.json")) == [
        "explicit_delta_001.json",
        "full_package_001.json",
    ]


def test_datacenter_counteroffer_affordance_pair_is_discoverable() -> None:
    family = CASES / "datacenter_counteroffer_affordance_v1"

    assert (family / "README.md").is_file()
    assert sorted(path.name for path in (family / "v1").glob("*.json")) == [
        "accept_by_reference_001.json",
        "reemit_package_001.json",
    ]


def test_datacenter_counteroffer_action_schema_pair_is_discoverable() -> None:
    family = CASES / "datacenter_counteroffer_action_schema_v1"

    assert (family / "README.md").is_file()
    assert sorted(path.name for path in (family / "v1").glob("*.json")) == [
        "dedicated_accept_schema_001.json",
        "shared_offer_schema_001.json",
    ]


def test_commercial_state_calibration_pilot_is_discoverable() -> None:
    family = CASES / "commercial_state_calibration_v1"
    pilot = family / "pilot"

    assert (family / "README.md").is_file()
    assert (pilot / "manifest.json").is_file()
    assert (pilot / "cases.jsonl").is_file()
    assert (pilot / "source_catalog_private.json").is_file()
