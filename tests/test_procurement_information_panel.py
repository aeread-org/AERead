from __future__ import annotations

import json
from pathlib import Path

import pytest

from aeread_families.procurement_allocation.environment import (
    ProcurementAllocationPlugin,
    UPPER_BOUND_ENUMERATION_LIMIT,
    solve_full_information_upper_bound,
)
from aeread_families.procurement_allocation.information_case_matrix import (
    CASE_SLUGS,
    build_confirmatory_case_matrix,
)
from aeread_families.procurement_allocation.runner import (
    procurement_action_output_schema,
)


def _case(slug: str, surface: str = "labeled") -> dict:
    for case in build_confirmatory_case_matrix(surface=surface):
        if case["case_id"].endswith("." + slug):
            return case["payload"]
    raise AssertionError(slug)


def test_information_panel_prices_information_to_bite() -> None:
    assert len(CASE_SLUGS) == 8
    for slug in CASE_SLUGS:
        payload = _case(slug)
        gross = (
            payload["objective"]["target_kits"]
            * payload["objective"]["revenue_per_completed_kit_usd"]
        )
        interaction = payload["interaction"]
        all_information = (
            interaction["inquiry_cost_usd"] * 3
            + interaction["quote_cost_usd"] * 4
            + interaction["counter_cost_usd"] * 2
            + sum(
                supplier["private_terms"]["quality"]["sample_cost_usd"]
                for supplier in payload["suppliers"]
            )
        )
        assert all_information / gross > 0.10, slug
        upper = solve_full_information_upper_bound(payload)
        assert upper.contribution_margin_usd > 0
        assert upper.actions_required <= interaction["max_actions"]


def test_a_verbal_claim_can_be_optimistic_while_the_award_uses_the_truth() -> None:
    payload = _case("optimistic_yield_claim")
    plugin = ProcurementAllocationPlugin()
    family_case = plugin.validate_payload(payload)
    phase = plugin.phases(family_case)[0]
    state = plugin.initial_state(family_case, run=None)
    liar = next(
        s for s in family_case["suppliers"] if "claims_high_yield" in s["supplier_id"]
    )

    action = {
        "action": "inquire",
        "supplier_id": liar["supplier_id"],
        "fields": ["quality"],
        "message": "What is your qualified yield?",
    }
    envelope = plugin.parse_action(family_case, state, "buyer", phase, action)
    assert envelope.ok
    from aeread.shared_runner.task.scheduler import ActionEnvelope, LegalityResult

    state = plugin.step(
        family_case,
        state,
        phase,
        {
            "buyer": ActionEnvelope(
                seat_id="buyer",
                valid=True,
                action=envelope.action,
                parse=envelope,
                legality=LegalityResult.legal_action(),
            )
        },
    ).state

    record = state["claims"][liar["supplier_id"]]["quality"]
    assert record["evidence_status"] == "verbal_claim"
    stated = record["value"]["claimed_yield_rate"]
    truth = liar["private_terms"]["quality"]["verified_yield_rate"]
    assert stated == pytest.approx(0.99)
    assert truth == pytest.approx(0.80)
    assert stated != truth, "the verbal claim must be able to overstate the truth"


def test_an_unbiased_supplier_still_states_the_truth() -> None:
    payload = _case("price_floor_headroom")
    for supplier in payload["suppliers"]:
        assert "verbal_bias" not in supplier["private_terms"]


def test_outcome_separates_a_feasible_award_from_a_feasible_defer() -> None:
    schema = procurement_action_output_schema()
    assert "check_award" in schema["properties"]["action"]["enum"]
    payload = _case("price_floor_headroom")
    plugin = ProcurementAllocationPlugin()
    family_case = plugin.validate_payload(payload)
    outcome = plugin.outcome(
        family_case,
        {
            "reason": "deferred",
            "failure_code": None,
            "actions_used": 1,
            "elapsed_days": 0,
            "information_cost_usd": 0.0,
            "offers": {},
            "quality_evidence": {},
            "award_lines": [],
            "award_checks": [],
            "defer_reason": "no qualified supplier",
        },
    )
    assert outcome["feasible"] is True
    assert outcome["feasible_award"] is False


def test_the_bound_refuses_an_intractable_world_instead_of_hanging() -> None:
    payload = json.loads(json.dumps(_case("price_floor_headroom")))
    for supplier in payload["suppliers"]:
        supplier["private_terms"]["moq"] = 2
        supplier["private_terms"]["order_step"] = 1
        supplier["private_terms"]["capacity"] = 400
    with pytest.raises(ValueError, match="enumeration exceeds"):
        solve_full_information_upper_bound(payload)
    assert UPPER_BOUND_ENUMERATION_LIMIT > 0


@pytest.mark.parametrize(
    "slug",
    [
        "optimistic_yield_claim",
        "optimistic_lead_time_claim",
        "optimistic_capacity_claim",
        "claim_versus_sample_tradeoff",
    ],
)
def test_trusting_an_optimistic_claim_loses_money(slug: str) -> None:
    """A buyer that believes the cheapest verbal claim must be punished.

    This is the property the v1 worlds could not have: there, a verbal claim was
    the truth, so trusting it was free. Here the stated terms pick a supplier
    whose true terms cannot satisfy the objective, and only a sample or a quote
    reveals that.
    """
    from aeread_families.procurement_allocation.environment import (
        _base_offer, _plain, _stated_terms, evaluate_award,
    )

    payload = _case(slug)
    upper = solve_full_information_upper_bound(payload)

    by_component: dict[str, list] = {}
    for supplier in payload["suppliers"]:
        by_component.setdefault(supplier["component"], []).append(supplier)
    believed = [
        min(group, key=lambda s: _stated_terms(s)["base_unit_price_usd"])
        for group in by_component.values()
    ]

    interaction = payload["interaction"]
    offers: dict = {}
    quality: dict = {}
    lines = []
    elapsed = 0
    information = 0.0
    for supplier in believed:
        offer = _base_offer(supplier, version=1, issued_day=0)
        offers[offer["offer_id"]] = offer
        record = _plain(supplier["private_terms"]["quality"])
        record.update(
            {
                "supplier_id": supplier["supplier_id"],
                "variant_id": supplier["private_terms"]["variant_id"],
                "evidence_status": "verified_sample",
            }
        )
        quality[supplier["supplier_id"]] = record
        elapsed += interaction["quote_days"] + record["sample_lead_time_days"]
        information += interaction["quote_cost_usd"] + record["sample_cost_usd"]
        lines.append({"offer_id": offer["offer_id"], "quantity": 20})

    naive = evaluate_award(
        payload,
        award_lines=lines,
        offers=offers,
        quality_evidence=quality,
        elapsed_days=elapsed,
        information_cost_usd=information,
    )
    assert naive["feasible"] is False, slug
    assert naive["contribution_margin_usd"] < upper.contribution_margin_usd



def test_information_campaign_runs_both_prompts_on_the_new_worlds() -> None:
    from aeread_families.procurement_allocation.information_campaign import (
        CAMPAIGN_ID, build_plan,
    )

    plan = build_plan()
    assert plan["campaign_id"] == CAMPAIGN_ID
    assert plan["independent_world_count"] == 8
    assert plan["planned_trajectory_count"] == 96
    assert plan["prompts"]["control_sha256"] != plan["prompts"]["treatment_sha256"]
    assert plan["analysis"]["diagnostic_rule"]["guarded_metric"].startswith(
        "feasible_award"
    )
    assert build_plan()["plan_sha256"] == plan["plan_sha256"]
