"""Brief v3.1 for pay or test version 3 (``pay_or_test_v31_brief_plan.md``, Section 2; incident P-D-29).

Every rule the brief states is checked against the environment and the generator, as version 3's brief is in
``test_procurement_pay_or_test_v3.py``, and version 3's sealed brief is checked unchanged.
"""
from __future__ import annotations

import hashlib
import json
import re

import pytest

from aeread_families.procurement_allocation import environment as v1_environment
from aeread_families.procurement_allocation import pay_or_test_v3_case_matrix as pack_module
from aeread_families.procurement_allocation import pay_or_test_v3_environment as environment
from aeread_families.procurement_allocation.pay_or_test_v31_prompt import PAY_OR_TEST_V31_PROMPT
from aeread_families.procurement_allocation.pay_or_test_v3_prompt import PAY_OR_TEST_V3_PROMPT
from test_procurement_pay_or_test_v3 import _ids, _step, _world

FLAT = " ".join(PAY_OR_TEST_V31_PROMPT.split())
#: The brief every sealed v3 run recorded (``model_plan.json`` of the pilot, confirmatory and diagnostic runs).
SEALED_V3_BRIEF_SHA256 = "fffe37882a8dc3378bc77ecceb09f27a9d43b724fff10c1a43a91ee20fc63597"
PACKS = (pack_module.PILOT_PACK_ID, pack_module.CONFIRM_PACK_ID, pack_module.DIAGNOSTIC_PACK_ID)


def _observed(payload: dict) -> tuple[environment.PayOrTestV3Plugin, dict, dict, dict]:
    plugin = environment.PayOrTestV3Plugin()
    case = plugin.validate_payload(payload)
    state = plugin.initial_state(case, None)
    return plugin, case, state, plugin.observe(case, state, "buyer", None)


def test_the_sealed_v3_brief_is_unchanged() -> None:
    assert hashlib.sha256(PAY_OR_TEST_V3_PROMPT.encode("utf-8")).hexdigest() == SEALED_V3_BRIEF_SHA256


def test_v31_lists_the_environments_actions_and_no_other() -> None:
    listed = set(re.findall(r"^- ([a-z_]+): ", PAY_OR_TEST_V31_PROMPT.split("Allowed actions:")[1].split("\n\n")[0], re.M))
    assert listed == environment.ACTION_TYPES
    for gone in ("inquire", "counter_offer", "financing", "cash_budget", "verbal", "quality loss", "return recovery"):
        assert gone not in PAY_OR_TEST_V31_PROMPT


def test_every_field_v31_names_is_in_what_the_buyer_sees_or_in_a_formal_quote() -> None:
    _, payload = _world()
    _, case, _, observed = _observed(payload)
    for path in set(re.findall(r"\b((?:policy|objective)\.[a-z_]+(?:\.[a-z_]+)*)", PAY_OR_TEST_V31_PROMPT)):
        node = observed
        for part in path.split("."):
            assert part in node, path
            node = node[part]
    offer = v1_environment._base_offer(case["suppliers"][0], version=1, issued_day=0)
    for path in set(re.findall(r"\breturn_policy\.([a-z_]+)", PAY_OR_TEST_V31_PROMPT)):
        assert path in offer["return_policy"], path
    for field in ("moq", "capacity", "order_step"):
        assert field in offer


def test_v31_states_the_answering_and_sharing_rules_by_reported_orders_as_the_buyer_sees_them() -> None:
    assert "a listing with a marketplace_record" not in FLAT.lower()
    assert "A listing with reported orders always answers" in FLAT
    assert "a listing with reported orders is not part of any" in FLAT
    assert "A listing whose marketplace_record shows no orders is new and carries a cohort_record" in FLAT
    _, payload = _world()
    _, _, _, observed = _observed(payload)
    for item in observed["supplier_listings"]:
        listing = item["listing"]
        # Every listing carries a marketplace_record; the new ones show no orders and carry a cohort record.
        assert "marketplace_record" in listing
        assert (listing["marketplace_record"]["orders_reported"] == 0) == ("cohort_record" in listing)


def test_every_supplier_in_every_v3_pack_sells_50_to_60_units_in_steps_of_5_as_v31_states() -> None:
    assert "sells 50 to 60 units an order, in steps of 5" in FLAT
    terms = set()
    for pack in PACKS:
        for path in pack_module.case_paths(split=pack):
            for supplier in json.loads(path.read_text())["payload"]["suppliers"]:
                private = supplier["private_terms"]
                terms.add((private["moq"], private["capacity"], private["order_step"], private["negotiation"]["minimum_moq"]))
    assert terms == {(50, 60, 5, 50)}


def test_the_margin_and_refund_rule_v31_states_is_the_environments() -> None:
    _, payload = _world()
    _, case, _, _ = _observed(payload)
    recorded = next(s for s in case["suppliers"] if s["listing"]["marketplace_record"]["orders_reported"])
    offer = v1_environment._base_offer(recorded, version=1, issued_day=0)
    objective, returns = case["objective"], offer["return_policy"]
    assert returns["refund_window_days"] >= objective["defect_detection_days"]
    quantity, information = 55, 32.0
    result = v1_environment.evaluate_award(
        case, award_lines=[{"offer_id": offer["offer_id"], "quantity": quantity}], offers={offer["offer_id"]: offer},
        quality_evidence={recorded["supplier_id"]: {"evidence_status": "verified_sample", "variant_id": offer["variant_id"]}},
        elapsed_days=3, information_cost_usd=information)
    yield_rate = recorded["private_terms"]["quality"]["verified_yield_rate"]
    kits = min(objective["target_kits"], int(quantity * yield_rate * offer["on_time_probability"]))
    refund = (quantity * (1 - yield_rate) * returns["claim_acceptance_probability"] * offer["unit_price_usd"]
              * (1 - returns["restocking_fee_rate"]))
    stated = (kits * objective["revenue_per_completed_kit_usd"] - quantity * offer["unit_price_usd"] - information
              - (objective["target_kits"] - kits) * objective["shortfall_penalty_per_kit_usd"] + refund)
    assert result["feasible"] and result["completed_kits"] == kits
    assert result["contribution_margin_usd"] == pytest.approx(stated, abs=1e-6)


def test_a_message_changes_no_suppliers_price_or_terms() -> None:
    _, payload = _world()
    plugin, case, state, _ = _observed(payload)
    recorded, _ = _ids(case)
    plain = _step(plugin, case, state, {"action": "request_quote", "supplier_id": recorded, "message": "Quote please.",
                                        "award_lines": None, "reason": None})
    pressed = _step(plugin, case, state, {"action": "request_quote", "supplier_id": recorded,
                                          "message": "We need your lowest price for 60 units, net 90, or we walk.",
                                          "award_lines": None, "reason": None})
    assert plain["offers"] == pressed["offers"]
    assert {k: v for k, v in plain.items() if k != "conversation"} == {k: v for k, v in pressed.items() if k != "conversation"}
