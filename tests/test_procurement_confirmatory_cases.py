from __future__ import annotations

import json
from pathlib import Path

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread_families.procurement_allocation.case_matrix import CASE_VARIANCE_PATHS
from aeread_families.procurement_allocation.confirmatory_case_matrix import (
    CASE_SLUGS,
    LABELED_PATHS,
    OPAQUE_PATHS,
    build_confirmatory_case_matrix,
    economic_world_sha256,
    write_confirmatory_case_matrix,
)
from aeread_families.procurement_allocation.environment import (
    ProcurementAllocationPlugin,
    solve_full_information_upper_bound,
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_confirmatory_panel_is_new_paired_and_digest_stable() -> None:
    labeled = build_confirmatory_case_matrix(surface="labeled")
    opaque = build_confirmatory_case_matrix(surface="opaque")
    assert len(labeled) == len(opaque) == len(CASE_SLUGS) == 12
    assert len({case["world_seed"] for case in labeled}) == 12
    assert {case["world_seed"] for case in labeled}.isdisjoint(
        {_load(path)["world_seed"] for path in CASE_VARIANCE_PATHS}
    )
    development_digests = {_load(path)["content_sha256"] for path in CASE_VARIANCE_PATHS}

    for labeled_case, opaque_case in zip(labeled, opaque, strict=True):
        assert labeled_case["split"] == "confirmatory_v1_labeled"
        assert opaque_case["split"] == "confirmatory_v1_opaque"
        assert labeled_case["content_sha256"] not in development_digests
        assert opaque_case["content_sha256"] not in development_digests
        assert labeled_case["content_sha256"] != opaque_case["content_sha256"]
        assert economic_world_sha256(labeled_case) == economic_world_sha256(opaque_case)
        for raw in (labeled_case, opaque_case):
            case = CaseManifest.from_dict(raw)
            assert case_content_sha256(case) == case.content_sha256
            ProcurementAllocationPlugin().validate_payload(case.payload)


def test_confirmatory_oracles_are_positive_paired_and_mechanism_diverse() -> None:
    labeled = build_confirmatory_case_matrix(surface="labeled")
    opaque = build_confirmatory_case_matrix(surface="opaque")
    bounds = []
    for left, right in zip(labeled, opaque, strict=True):
        left_bound = solve_full_information_upper_bound(left["payload"])
        right_bound = solve_full_information_upper_bound(right["payload"])
        assert (
            left_bound.contribution_margin_usd,
            left_bound.completed_kits,
            left_bound.cash_spend_usd,
            left_bound.actions_required,
            left_bound.elapsed_days,
        ) == (
            right_bound.contribution_margin_usd,
            right_bound.completed_kits,
            right_bound.cash_spend_usd,
            right_bound.actions_required,
            right_bound.elapsed_days,
        )
        assert left_bound.contribution_margin_usd > left["payload"]["objective"]["defer_value_usd"]
        assert left_bound.actions_required <= 10
        bounds.append(left_bound)

    by_slug = dict(zip(CASE_SLUGS, bounds, strict=True))
    assert any(item["mode"] == "negotiated" for item in by_slug["cash_budget_counter"].award_plan)
    assert any(item["mode"] == "negotiated" for item in by_slug["refund_counter"].award_plan)
    assert any(item["mode"] == "negotiated" for item in by_slug["payment_terms_counter"].award_plan)
    assert any(item["mode"] == "negotiated" for item in by_slug["negotiated_moq"].award_plan)
    split = by_slug["split_capacity_rounding"].award_plan
    assert len([item for item in split if item["component"] == "tactile_switch_6x6x5"]) == 2
    multi = {
        component: sum(
            item["quantity"]
            for item in by_slug["multi_unit_bom"].award_plan
            if item["component"] == component
        )
        for component in ("mosfet_low_side_3v3", "tactile_switch_6x6x5")
    }
    assert multi["mosfet_low_side_3v3"] >= 40
    assert multi["tactile_switch_6x6x5"] >= 60
    assert all("cheap_near_match" not in item["supplier_id"] for item in by_slug["exact_variant_decoys"].award_plan)


def test_confirmatory_observation_hides_private_terms() -> None:
    case = CaseManifest.from_dict(build_confirmatory_case_matrix(surface="labeled")[0])
    plugin = ProcurementAllocationPlugin()
    state = plugin.initial_state(case.payload, None)
    observation = plugin.observe(case.payload, state, "buyer", plugin.phases(case.payload)[0])
    serialized = json.dumps(observation, sort_keys=True)
    assert "private_terms" not in serialized
    assert "floor_unit_price_usd" not in serialized
    assert "verified_yield_rate" not in serialized


def test_tracked_confirmatory_cases_match_generator(tmp_path: Path) -> None:
    labeled_root = tmp_path / "labeled"
    opaque_root = tmp_path / "opaque"
    generated_labeled = write_confirmatory_case_matrix(surface="labeled", root=labeled_root)
    generated_opaque = write_confirmatory_case_matrix(surface="opaque", root=opaque_root)
    for generated, tracked in zip(generated_labeled, LABELED_PATHS, strict=True):
        assert generated.read_bytes() == tracked.read_bytes()
    for generated, tracked in zip(generated_opaque, OPAQUE_PATHS, strict=True):
        assert generated.read_bytes() == tracked.read_bytes()
