"""The seed-domain inference pack: unread, rule-selected, and still the v1 construct.

v1's eighteen worlds have fixed seeds and every one has been read by a pilot.
A confirmatory needs worlds no live cell has read, so `inference_pack` draws
them from declared ranges in a seed domain of their own and admits each by a
screen. These tests are what keep that true: the committed pack reproduces
from its seeds, its domain is disjoint from every other procurement world, each
world carries its signal and only its signal, and the refactor that made the
v1 generator shareable left v1's bytes alone.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread_families.procurement_allocation import inference_pack as pack_module
from aeread_families.procurement_allocation.duediligence_case_matrix import economic_world_sha256
from aeread_families.procurement_allocation.environment import ProcurementAllocationPlugin, stated_listing
from aeread_families.procurement_allocation.headroom_screen import ADMIT
from aeread_families.procurement_allocation.inference_case_matrix import (
    LABELED_ROOT,
    OPAQUE_ROOT,
    RISKS,
    SIGNALS,
    build_inference_case_matrix,
    sample_definition,
    world_specs,
)
from aeread_families.procurement_allocation.inference_pack import (
    ALIGNED_RULE,
    OPPOSITE_RULE,
    PACKS,
    RULES,
    SURFACES,
    build_world,
    choose_rule_action,
    direction,
    good_supplier_ids,
    pack_case_paths,
    read_manifest,
    screen_world,
)

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "cases" / "procurement_allocation_v1"
PACK = "inference_holdout_v1"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return read_manifest(PACK)


@pytest.fixture(scope="module")
def committed(manifest: dict) -> dict[str, dict[str, dict]]:
    """``{slug: {surface: case}}`` for every world the manifest lists."""
    return {
        row["slug"]: {
            surface: json.loads((CASES / PACK / surface / f"{row['slug']}.json").read_text(encoding="utf-8"))
            for surface in SURFACES
        }
        for row in manifest["worlds"]
    }


# --- v1 is untouched ---------------------------------------------------------


@pytest.mark.parametrize("surface, root", [("labeled", LABELED_ROOT), ("opaque", OPAQUE_ROOT)])
def test_v1_regenerates_byte_for_byte_from_the_shared_builder(surface: str, root: Path) -> None:
    """`finish_case` is shared with v1; its committed worlds must not move."""
    for case in build_inference_case_matrix(surface=surface):
        path = root / f"{case['case_id'].rsplit('.', 1)[-1]}.json"
        assert json.loads(path.read_text(encoding="utf-8")) == case, path.name


# --- the committed pack is what its manifest says ---------------------------


def test_manifest_is_complete_and_its_digest_is_its_own(manifest: dict) -> None:
    spec = PACKS[PACK]
    assert manifest["pack"] == PACK and manifest["split"] == spec["split"]
    assert manifest["per_cell"] == spec["per_cell"]
    assert manifest["complete"] is True
    assert manifest["admitted"] == len(manifest["worlds"]) == spec["per_cell"] * len(SIGNALS) * len(RISKS)
    recorded = manifest.pop("manifest_sha256")
    try:
        import hashlib

        recomputed = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    finally:
        manifest["manifest_sha256"] = recorded
    assert recomputed == recorded


def test_every_committed_world_validates_and_matches_the_manifest(manifest: dict, committed: dict) -> None:
    plugin = ProcurementAllocationPlugin()
    for row in manifest["worlds"]:
        for surface in SURFACES:
            case = committed[row["slug"]][surface]
            plugin.validate_payload(case["payload"])
            assert case["case_id"] == row["case_ids"][surface]
            assert case["world_seed"] == row["world_seed"]
            assert case_content_sha256(CaseManifest.from_dict(case)) == case["content_sha256"]
            assert case["content_sha256"] == row["content_sha256"][surface]
            assert case["provenance"]["review_status"] == "generated"
        labeled, opaque = committed[row["slug"]]["labeled"], committed[row["slug"]]["opaque"]
        assert economic_world_sha256(labeled) == economic_world_sha256(opaque) == row["economic_world_sha256"]
        assert pack_case_paths(PACK, surface="labeled")


def test_every_cell_is_filled_and_the_strata_are_balanced(manifest: dict) -> None:
    per_cell = manifest["per_cell"]
    cells = Counter((row["signal"], row["risk"]) for row in manifest["worlds"])
    assert cells == {(signal, risk): per_cell for signal in SIGNALS for risk in RISKS}
    assert manifest["strata"]["direction"] == {"low_is_good": 9 * per_cell, "high_is_good": 9 * per_cell}
    assert manifest["strata"]["risk"] == {risk: 6 * per_cell for risk in RISKS}
    assert manifest["strata"]["attribute"] == {"price": 6 * per_cell, "lead_time": 6 * per_cell, "moq": 6 * per_cell}


def test_the_seed_domain_is_disjoint_from_every_other_procurement_world(manifest: dict) -> None:
    start = manifest["seed_domain"]["start"]
    seeds = {row["world_seed"] for row in manifest["worlds"]}
    assert all(start <= seed < start + manifest["seed_domain"]["scan_limit"] for seed in seeds)
    assert seeds.isdisjoint({seed for _, seed, _, _ in world_specs()})
    others: set[int] = set()
    for path in CASES.rglob("*.json"):
        if PACK in path.parts or path.name == "pack.json":
            continue
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(case, dict) and isinstance(case.get("world_seed"), int):
            others.add(case["world_seed"])
    assert others, "no other procurement worlds found; the walk is wrong"
    assert seeds.isdisjoint(others)


def test_every_world_was_admitted_by_the_screen_and_says_why(manifest: dict) -> None:
    for row in manifest["worlds"]:
        assert row["aligned_rule"] == ALIGNED_RULE[row["signal"]]
        assert row["opposite_rule"] == OPPOSITE_RULE[row["aligned_rule"]]
        assert row["aligned_rule"] in row["solved_by"]
        assert set(row["rule_regret_usd"]) == set(RULES)
        assert row["opposite_margin_usd"] == pytest.approx(
            row["rule_regret_usd"][row["opposite_rule"]] - row["rule_regret_usd"][row["aligned_rule"]], abs=1e-5
        )
        if row["risk"] != "capacity":
            assert row["opposite_margin_usd"] >= 0.05 * row["upper_bound_usd"]
            assert row["oracle_good_share"] >= pack_module.ORACLE_GOOD_SHARE_FLOOR
    assert all(row["verdict"] != ADMIT for row in manifest["excluded"])


# --- each world carries its signal, and only its signal --------------------


def _private(case: dict) -> dict[str, dict]:
    return {s["supplier_id"]: s for s in case["payload"]["suppliers"]}


def test_the_signal_attribute_predicts_quality_in_every_world(committed: dict, manifest: dict) -> None:
    for row in manifest["worlds"]:
        case = committed[row["slug"]]["labeled"]
        good = good_supplier_ids(case["payload"])
        attribute = row["attribute"]
        for component in {s["component"] for s in case["payload"]["suppliers"]}:
            suppliers = [s for s in case["payload"]["suppliers"] if s["component"] == component]
            assert sum(1 for s in suppliers if s["supplier_id"] in good) == 2
            # What the buyer sees: the listing as the environment states it,
            # which is where a declared minimum-order claim appears.
            if attribute == "price":
                value = lambda s: float(stated_listing(s)["displayed_unit_price_usd"])  # noqa: E731
            elif attribute == "lead_time":
                value = lambda s: int(stated_listing(s)["claimed_lead_time_days"])  # noqa: E731
            else:
                value = lambda s: int(stated_listing(s)["claimed_moq"])  # noqa: E731
            good_values = sorted(value(s) for s in suppliers if s["supplier_id"] in good)
            poor_values = sorted(value(s) for s in suppliers if s["supplier_id"] not in good)
            if row["direction"] == "high_is_good":
                assert min(good_values) > max(poor_values), row["slug"]
            else:
                assert max(good_values) < min(poor_values), row["slug"]


def test_price_does_not_separate_good_from_poor_where_it_is_not_the_signal(committed: dict, manifest: dict) -> None:
    for row in manifest["worlds"]:
        if row["attribute"] == "price":
            continue
        case = committed[row["slug"]]["labeled"]
        good = good_supplier_ids(case["payload"])
        for component in {s["component"] for s in case["payload"]["suppliers"]}:
            suppliers = [s for s in case["payload"]["suppliers"] if s["component"] == component]
            good_prices = [float(s["listing"]["displayed_unit_price_usd"]) for s in suppliers if s["supplier_id"] in good]
            poor_prices = [float(s["listing"]["displayed_unit_price_usd"]) for s in suppliers if s["supplier_id"] not in good]
            assert min(good_prices) < max(poor_prices) and min(poor_prices) < max(good_prices), row["slug"]


def test_exactly_one_risk_binds_and_the_listing_states_the_minimum_order(committed: dict, manifest: dict) -> None:
    for row in manifest["worlds"]:
        case = committed[row["slug"]]["labeled"]
        terms = [s["private_terms"] for s in case["payload"]["suppliers"]]
        yields = {t["quality"]["verified_yield_rate"] for t in terms}
        on_times = {t["on_time_probability"] for t in terms}
        capacities = {t["capacity"] for t in terms}
        assert (len(yields) > 1, len(on_times) > 1, len(capacities) > 1) == (
            row["risk"] == "yield", row["risk"] == "timing", row["risk"] == "capacity"
        ), row["slug"]
        for supplier in case["payload"]["suppliers"]:
            stated = stated_listing(supplier)
            assert "claimed_moq" in stated
            assert supplier["private_terms"]["moq"] == min(stated["claimed_moq"], supplier["private_terms"]["capacity"])


def test_no_world_names_its_signal_or_risk_in_the_payload(committed: dict, manifest: dict) -> None:
    for row in manifest["worlds"]:
        for surface in SURFACES:
            body = json.dumps(committed[row["slug"]][surface]["payload"])
            for signal in SIGNALS:
                assert signal not in body
            assert row["slug"] not in body
            assert "binding_risk" not in body and "declared_signal" not in body
            assert "high_is_good" not in body and "low_is_good" not in body


def test_opaque_mirrors_hide_labels_and_reorder_listings(committed: dict, manifest: dict) -> None:
    for row in manifest["worlds"]:
        labeled = committed[row["slug"]]["labeled"]["payload"]["suppliers"]
        opaque = committed[row["slug"]]["opaque"]["payload"]["suppliers"]
        assert all(s["supplier_id"].startswith("supplier_") for s in opaque)
        assert [s["supplier_id"] for s in labeled] != [s["supplier_id"] for s in opaque]
        assert len(labeled) == len(opaque) == 8


# --- the generator and the screen -------------------------------------------


def test_two_committed_worlds_rebuild_from_their_seeds(manifest: dict, committed: dict) -> None:
    rows = [manifest["worlds"][0], manifest["worlds"][-1]]
    for row in rows:
        world = build_world(row["world_seed"], row["signal"], row["risk"], pack=PACK, split=manifest["split"])
        for surface in SURFACES:
            assert world["cases"][surface] == committed[row["slug"]][surface]
        screen = screen_world(world["cases"]["labeled"]["payload"], signal=row["signal"], risk=row["risk"])
        assert screen["verdict"] == ADMIT
        assert screen["rule_regret_usd"] == row["rule_regret_usd"]


def test_sampling_is_deterministic_and_seeds_differ_in_their_economics() -> None:
    first = sample_definition("price_low_is_good", "yield", 8820000)
    again = sample_definition("price_low_is_good", "yield", 8820000)
    other = sample_definition("price_low_is_good", "yield", 8820018)
    assert first == again
    assert first["levels"] != other["levels"] or first["objective"] != other["objective"]
    assert first["budget_actions"] == 9 and first["objective"]["target_kits"] == 19


def test_the_six_rules_rank_in_opposite_directions() -> None:
    observation = {
        "supplier_listings": [
            {"supplier_id": "a", "component": "c", "listing": {"displayed_unit_price_usd": 0.5, "claimed_lead_time_days": 7, "claimed_moq": 20}},
            {"supplier_id": "b", "component": "c", "listing": {"displayed_unit_price_usd": 0.9, "claimed_lead_time_days": 3, "claimed_moq": 10}},
        ]
    }
    ranked = {rule: [s["supplier_id"] for s in pack_module._ranked(observation, component="c", rule=rule)] for rule in RULES}
    assert ranked["cheapest_first"] == ["a", "b"] and ranked["dearest_first"] == ["b", "a"]
    assert ranked["fastest_first"] == ["b", "a"] and ranked["slowest_first"] == ["a", "b"]
    assert ranked["smallest_moq_first"] == ["b", "a"] and ranked["largest_moq_first"] == ["a", "b"]
    for signal in SIGNALS:
        assert direction(signal) in ("low_is_good", "high_is_good")
    with pytest.raises(ValueError):
        choose_rule_action({}, rule="no_such_rule")


@pytest.mark.skipif(not os.environ.get("AEREAD_SLOW_TESTS"), reason="rebuilds and screens the whole pack; set AEREAD_SLOW_TESTS=1")
def test_the_whole_pack_regenerates_to_its_committed_manifest(manifest: dict) -> None:
    built = pack_module.build_pack(PACK)["manifest"]
    assert built == manifest
