from __future__ import annotations

import asyncio
import json
from pathlib import Path

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread_families.procurement_allocation.case_matrix import CASE_VARIANCE_PATHS
from aeread_families.procurement_allocation.confirmatory_case_matrix import (
    LABELED_PATHS as CONFIRMATORY_LABELED_PATHS,
)
from aeread_families.procurement_allocation.confirmatory_case_matrix import (
    OPAQUE_PATHS as CONFIRMATORY_OPAQUE_PATHS,
)
from aeread_families.procurement_allocation.environment import (
    ProcurementAllocationPlugin,
    solve_full_information_upper_bound,
)
from aeread_families.procurement_allocation.risk_gate_case_matrix import (
    CASE_SLUGS,
    LABELED_PATHS,
    OPAQUE_PATHS,
    STRATA_BY_SLUG,
    build_risk_gate_case_matrix,
    economic_world_sha256,
    write_risk_gate_case_matrix,
)
from aeread_families.procurement_allocation.runner import run_fixture_script


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_risk_gate_panel_is_new_paired_and_digest_stable() -> None:
    labeled = build_risk_gate_case_matrix(surface="labeled")
    opaque = build_risk_gate_case_matrix(surface="opaque")
    prior_paths = (
        *CASE_VARIANCE_PATHS,
        *CONFIRMATORY_LABELED_PATHS,
        *CONFIRMATORY_OPAQUE_PATHS,
    )
    prior_seeds = {_load(path)["world_seed"] for path in prior_paths}
    prior_digests = {_load(path)["content_sha256"] for path in prior_paths}

    assert len(labeled) == len(opaque) == len(CASE_SLUGS) == 6
    assert len({case["world_seed"] for case in labeled}) == 6
    assert {case["world_seed"] for case in labeled}.isdisjoint(prior_seeds)
    for left, right in zip(labeled, opaque, strict=True):
        assert left["split"] == "risk_gates_v1_labeled"
        assert right["split"] == "risk_gates_v1_opaque"
        assert left["content_sha256"] not in prior_digests
        assert right["content_sha256"] not in prior_digests
        assert left["content_sha256"] != right["content_sha256"]
        assert economic_world_sha256(left) == economic_world_sha256(right)
        assert [row["supplier_id"] for row in left["payload"]["suppliers"]] != [
            row["supplier_id"] for row in right["payload"]["suppliers"]
        ]
        for raw in (left, right):
            case = CaseManifest.from_dict(raw)
            assert case_content_sha256(case) == case.content_sha256
            ProcurementAllocationPlugin().validate_payload(case.payload)


def test_risk_gate_strata_expose_only_the_information_each_gate_needs() -> None:
    cases = build_risk_gate_case_matrix(surface="labeled")
    assert tuple(case["case_id"].rsplit(".", 1)[-1] for case in cases) == CASE_SLUGS
    assert set(STRATA_BY_SLUG.values()) == {"sample_timing", "landed_cash"}

    for slug, raw in zip(CASE_SLUGS, cases, strict=True):
        fields = raw["payload"]["policy"]["inquiry_fields"]
        if STRATA_BY_SLUG[slug] == "sample_timing":
            assert "sample_logistics" in fields
        else:
            assert "sample_logistics" not in fields


def test_risk_gate_oracles_are_positive_and_surface_invariant() -> None:
    labeled = build_risk_gate_case_matrix(surface="labeled")
    opaque = build_risk_gate_case_matrix(surface="opaque")
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
        assert left_bound.contribution_margin_usd > 0
        assert left_bound.actions_required <= 10


def test_landed_cash_worlds_make_low_sticker_allocation_exceed_budget() -> None:
    cases = build_risk_gate_case_matrix(surface="labeled")
    for slug, raw in zip(CASE_SLUGS, cases, strict=True):
        if STRATA_BY_SLUG[slug] != "landed_cash":
            continue
        payload = raw["payload"]
        low_sticker_total = 0.0
        for component, units_per_kit in payload["objective"]["bom"].items():
            supplier = next(
                row
                for row in payload["suppliers"]
                if row["component"] == component
                and "low_sticker" in row["supplier_id"]
            )
            terms = supplier["private_terms"]
            quantity = max(20 * units_per_kit, terms["moq"])
            while (quantity - terms["moq"]) % terms["order_step"]:
                quantity += 1
            low_sticker_total += quantity * (
                terms["base_unit_price_usd"]
                + terms["shipping_per_unit_usd"]
            ) * (1.0 + terms["duty_rate"])

        assert low_sticker_total > payload["objective"]["cash_budget_usd"]
        assert (
            solve_full_information_upper_bound(payload).cash_spend_usd
            <= payload["objective"]["cash_budget_usd"]
        )


def test_sample_logistics_inquiry_is_verbal_and_creates_no_award_authority(
    tmp_path: Path,
) -> None:
    case_path = LABELED_PATHS[0]
    supplier_id = _load(case_path)["payload"]["suppliers"][0]["supplier_id"]
    script = [
        json.dumps(
            {
                "action": "inquire",
                "supplier_id": supplier_id,
                "fields": ["sample_logistics"],
                "message": "Confirm sample turnaround and sample cost.",
            },
            sort_keys=True,
        ),
        json.dumps({"action": "defer", "reason": "Information check complete."}),
    ]

    _, execution, provider = asyncio.run(
        run_fixture_script(
            script,
            evidence_root=tmp_path / "sample-logistics",
            case_path=case_path,
        )
    )
    state = execution.episode_result.final_state
    claim = state["claims"][supplier_id]["sample_logistics"]

    assert provider.exhausted
    assert claim["evidence_status"] == "verbal_claim"
    assert set(claim["value"]) == {"sample_lead_time_days", "sample_cost_usd"}
    assert not state["offers"]
    assert not state["quality_evidence"]


def test_sample_timing_worlds_have_observation_reachable_feasible_awards(
    tmp_path: Path,
) -> None:
    for case_path in LABELED_PATHS[:3]:
        raw = _load(case_path)
        payload = raw["payload"]
        actions = [
            {
                "action": "inquire",
                "supplier_id": supplier["supplier_id"],
                "fields": ["sample_logistics"],
                "message": "Confirm sample turnaround and sample cost.",
            }
            for supplier in payload["suppliers"]
        ]
        selected: list[tuple[dict, int]] = []
        for component, units_per_kit in payload["objective"]["bom"].items():
            supplier = min(
                (
                    row
                    for row in payload["suppliers"]
                    if row["component"] == component
                ),
                key=lambda row: row["private_terms"]["quality"][
                    "sample_lead_time_days"
                ],
            )
            terms = supplier["private_terms"]
            quantity = max(
                payload["objective"]["target_kits"] * units_per_kit,
                terms["moq"],
            )
            while (quantity - terms["moq"]) % terms["order_step"]:
                quantity += 1
            selected.append((supplier, quantity))
            actions.extend(
                [
                    {
                        "action": "request_quote",
                        "supplier_id": supplier["supplier_id"],
                        "message": "Issue the exact-variant formal offer.",
                    },
                    {
                        "action": "request_sample",
                        "supplier_id": supplier["supplier_id"],
                        "message": "Provide the exact-variant qualification sample.",
                    },
                ]
            )
        actions.append(
            {
                "action": "submit_award",
                "award_lines": [
                    {
                        "offer_id": f"offer_{supplier['supplier_id']}_v1",
                        "quantity": quantity,
                    }
                    for supplier, quantity in selected
                ],
            }
        )

        _, execution, provider = asyncio.run(
            run_fixture_script(
                [json.dumps(action, sort_keys=True) for action in actions],
                evidence_root=tmp_path / case_path.stem,
                case_path=case_path,
            )
        )
        outcome = execution.episode_result.outcome

        assert provider.exhausted
        assert len(actions) == 9
        assert outcome["feasible"] is True
        assert outcome["completed_kits"] == payload["objective"]["target_kits"]
        assert outcome["elapsed_days"] + max(
            supplier["private_terms"]["lead_time_days"]
            for supplier, _ in selected
        ) <= payload["objective"]["deadline_days"]


def test_tracked_risk_gate_cases_match_generator(tmp_path: Path) -> None:
    generated_labeled = write_risk_gate_case_matrix(
        surface="labeled", root=tmp_path / "labeled"
    )
    generated_opaque = write_risk_gate_case_matrix(
        surface="opaque", root=tmp_path / "opaque"
    )
    for generated, tracked in zip(generated_labeled, LABELED_PATHS, strict=True):
        assert generated.read_bytes() == tracked.read_bytes()
    for generated, tracked in zip(generated_opaque, OPAQUE_PATHS, strict=True):
        assert generated.read_bytes() == tracked.read_bytes()
