"""Refund V2.4: twelve interaction-heavy synthetic marketplace scenarios.

V2.4 intentionally separates a policy outcome from the wire representation
used by an agent.  Cases are synthetic; they are not a retailer policy.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping


FAMILY_ID = "refund_v2"
FAMILY_VERSION = "2.4.0"
SCENARIOS = (
    "wrong_item_received", "missing_parts_partial_refund",
    "late_defect_identity_conflict", "seller_fault_unverified_evidence",
    "multiple_missing_components", "discounted_bundle_component_value",
    "returnless_refund_high_value_exception", "carrier_delay_request_date",
    "refund_already_issued_chargeback_pending", "condition_deterioration_after_return",
    "category_exclusion_seller_fault_override", "evidence_contradiction",
)


@dataclass(frozen=True, slots=True)
class MarketplaceV24Case:
    case_id: str
    world_seed: int
    scenario: str
    variant: str
    pair_id: str
    changed_fact_ids: tuple[str, ...]
    public_claim: str
    policy_summary: str
    item_net_price: float
    allocated_tax: float
    facts: Mapping[str, Any]

    @property
    def semantic_content_sha256(self) -> str:
        value = {
            "scenario": self.scenario, "variant": self.variant,
            "public_claim": self.public_claim, "policy_summary": self.policy_summary,
            "item_net_price": self.item_net_price, "allocated_tax": self.allocated_tax,
            "facts": dict(self.facts),
        }
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _money(seed: int, label: str, low: int = 6000, high: int = 42000) -> float:
    digest = hashlib.sha256(f"refund-v24:{seed}:{label}".encode()).digest()
    return round((low + int.from_bytes(digest[:8], "big") % (high - low + 1)) / 100, 2)


def _case(seed: int, scenario: str, variant: str, pair: str, changed: tuple[str, ...], claim: str, policy: str, facts: Mapping[str, Any], *, low: int = 6000, high: int = 42000) -> MarketplaceV24Case:
    price = _money(seed, f"{scenario}:{pair}", low, high)
    return MarketplaceV24Case(f"refund_v2.4.{scenario}.{variant}.{seed:06d}", seed, scenario, variant, pair, changed, claim, policy, price, round(price * 0.0825, 2), dict(facts))


def build_marketplace_v24_panel(seed: int) -> tuple[MarketplaceV24Case, ...]:
    """Return 24 cases: two counterfactual variants for each policy interaction."""
    return (
        # 1. Base wrong-item rule, now explicitly separates verified evidence from claim.
        _case(seed, "wrong_item_received", "verified_mismatch", "wrong_item_evidence", ("sku_evidence_status",), "I received a different item.", "Verified received-SKU mismatch is seller fault and refundable; an unverified claim goes to evidence review.", {"ordered_sku":"A", "received_sku":"B", "sku_evidence_status":"verified"}),
        _case(seed, "wrong_item_received", "unverified_mismatch", "wrong_item_evidence", ("sku_evidence_status",), "I received a different item.", "Verified received-SKU mismatch is seller fault and refundable; an unverified claim goes to evidence review.", {"ordered_sku":"A", "received_sku":"B", "sku_evidence_status":"unverified"}),
        # 2. Base partial-refund rule with a cap boundary.
        _case(seed, "missing_parts_partial_refund", "noncore_over_cap", "missing_cap", ("component_role",), "A listed accessory is missing.", "Verified missing non-core components receive the lesser of catalog value and 30% of item net price; a core component receives full refund.", {"component_role":"non_core", "component_catalog_value":9999.0, "category_cap_rate":0.30, "evidence_status":"verified"}),
        _case(seed, "missing_parts_partial_refund", "core_component", "missing_cap", ("component_role",), "A listed accessory is missing.", "Verified missing non-core components receive the lesser of catalog value and 30% of item net price; a core component receives full refund.", {"component_role":"core", "component_catalog_value":9999.0, "category_cap_rate":0.30, "evidence_status":"verified"}),
        # 3. Priority: identity review overrides a valid late-defect exception.
        _case(seed, "late_defect_identity_conflict", "identity_conflict", "identity_precedence", ("inspection_serial",), "The device failed after delivery; I returned it on day 45.", "A verified defect through day 90 is refundable, except a verified post-return serial mismatch routes to identity review before any refund.", {"return_request_day":45, "defect_evidence":"verified", "inspection_stage":"post_return_warehouse", "order_serial":"S1", "inspection_serial":"S2"}, low=50000, high=150000),
        _case(seed, "late_defect_identity_conflict", "serial_match", "identity_precedence", ("inspection_serial",), "The device failed after delivery; I returned it on day 45.", "A verified defect through day 90 is refundable, except a verified post-return serial mismatch routes to identity review before any refund.", {"return_request_day":45, "defect_evidence":"verified", "inspection_stage":"post_return_warehouse", "order_serial":"S1", "inspection_serial":"S1"}, low=50000, high=150000),
        # 4. A seller-fault assertion is not enough without the required evidence.
        _case(seed, "seller_fault_unverified_evidence", "claim_only", "seller_fault_evidence", ("defect_evidence",), "The seller sent a defective product.", "Seller-fault remedies require verified defect evidence; a customer assertion alone receives evidence review, not denial or refund.", {"defect_evidence":"customer_assertion", "return_request_day":10}),
        _case(seed, "seller_fault_unverified_evidence", "verified_defect", "seller_fault_evidence", ("defect_evidence",), "The seller sent a defective product.", "Seller-fault remedies require verified defect evidence; a customer assertion alone receives evidence review, not denial or refund.", {"defect_evidence":"verified", "return_request_day":10}),
        # 5. Remedy precedence: any verified core component dominates partial component compensation.
        _case(seed, "multiple_missing_components", "core_and_noncore", "component_precedence", ("core_component_missing",), "Several parts are absent from the box.", "Any verified missing core component yields full refund; otherwise verified non-core components receive their combined value capped at 30% of item price.", {"core_component_missing":True, "noncore_catalog_total":9999.0, "evidence_status":"verified", "category_cap_rate":0.30}),
        _case(seed, "multiple_missing_components", "only_noncore", "component_precedence", ("core_component_missing",), "Several parts are absent from the box.", "Any verified missing core component yields full refund; otherwise verified non-core components receive their combined value capped at 30% of item price.", {"core_component_missing":False, "noncore_catalog_total":9999.0, "evidence_status":"verified", "category_cap_rate":0.30}),
        # 6. Bundle allocation uses the paid allocation, not a standalone catalog list price.
        _case(seed, "discounted_bundle_component_value", "allocated_value_below_cap", "bundle_allocation", ("paid_component_allocation",), "One item from a discounted bundle is missing.", "For a discounted bundle, partial refund uses paid component allocation, not standalone catalog price, then applies the category cap.", {"standalone_catalog_value":180.0, "paid_component_allocation":5.0, "category_cap_rate":0.30, "evidence_status":"verified"}),
        _case(seed, "discounted_bundle_component_value", "allocated_value_above_cap", "bundle_allocation", ("paid_component_allocation",), "One item from a discounted bundle is missing.", "For a discounted bundle, partial refund uses paid component allocation, not standalone catalog price, then applies the category cap.", {"standalone_catalog_value":180.0, "paid_component_allocation":9999.0, "category_cap_rate":0.30, "evidence_status":"verified"}),
        # 7. Returnless threshold is overridden for high-risk identity items.
        _case(seed, "returnless_refund_high_value_exception", "low_value_low_risk", "returnless_risk", ("identity_risk",), "The item arrived damaged; returning it would cost more than it is worth.", "Verified seller-fault claims under $25 are returnless unless high identity risk requires a return and inspection.", {"defect_evidence":"verified", "identity_risk":"low", "returnless_threshold":25.0}, low=1000, high=2400),
        _case(seed, "returnless_refund_high_value_exception", "low_value_high_risk", "returnless_risk", ("identity_risk",), "The item arrived damaged; returning it would cost more than it is worth.", "Verified seller-fault claims under $25 are returnless unless high identity risk requires a return and inspection.", {"defect_evidence":"verified", "identity_risk":"high", "returnless_threshold":25.0}, low=1000, high=2400),
        # 8. The request date, not carrier handover, governs the window.
        _case(seed, "carrier_delay_request_date", "request_day_29", "time_anchor", ("return_request_day",), "The carrier pickup was delayed.", "Buyer-remorse eligibility uses return-request day, not carrier handover or current day; it is allowed through day 30.", {"return_request_day":29, "carrier_handover_day":35, "return_reason":"buyer_remorse"}),
        _case(seed, "carrier_delay_request_date", "request_day_31", "time_anchor", ("return_request_day",), "The carrier pickup was delayed.", "Buyer-remorse eligibility uses return-request day, not carrier handover or current day; it is allowed through day 30.", {"return_request_day":31, "carrier_handover_day":35, "return_reason":"buyer_remorse"}),
        # 9. Avoid a duplicate payment while a previous resolution is pending.
        _case(seed, "refund_already_issued_chargeback_pending", "refund_pending", "payment_state", ("prior_refund_state", "chargeback_state"), "I still do not see my refund.", "A pending or issued refund never receives a second payment mutation; a chargeback pending routes to payment review.", {"prior_refund_state":"refund_pending", "chargeback_state":"none"}),
        _case(seed, "refund_already_issued_chargeback_pending", "chargeback_pending", "payment_state", ("prior_refund_state", "chargeback_state"), "I still do not see my refund.", "A pending or issued refund never receives a second payment mutation; a chargeback pending routes to payment review.", {"prior_refund_state":"none", "chargeback_state":"pending"}),
        # 10. Responsibility after a return depends on inspection evidence, not the claim.
        _case(seed, "condition_deterioration_after_return", "buyer_caused_damage", "post_return_condition", ("inspection_cause",), "The returned item was damaged in transit.", "Verified buyer-caused deterioration after return routes to seller review; verified carrier damage preserves the original seller-fault refund.", {"inspection_cause":"buyer_caused", "original_defect_evidence":"verified"}),
        _case(seed, "condition_deterioration_after_return", "carrier_damage", "post_return_condition", ("inspection_cause",), "The returned item was damaged in transit.", "Verified buyer-caused deterioration after return routes to seller review; verified carrier damage preserves the original seller-fault refund.", {"inspection_cause":"carrier_damage", "original_defect_evidence":"verified"}),
        # 11. A category exclusion does not override a verified seller-fault wrong-item event.
        _case(seed, "category_exclusion_seller_fault_override", "ordinary_excluded_return", "category_override", ("seller_fault_event",), "I want to return this final-sale item.", "Final-sale categories do not accept buyer-remorse returns, but verified wrong-item or seller-fault defect claims override the exclusion.", {"category_final_sale":True, "return_reason":"buyer_remorse", "seller_fault_event":"none"}),
        _case(seed, "category_exclusion_seller_fault_override", "wrong_item_override", "category_override", ("seller_fault_event",), "I want to return this final-sale item.", "Final-sale categories do not accept buyer-remorse returns, but verified wrong-item or seller-fault defect claims override the exclusion.", {"category_final_sale":True, "return_reason":"buyer_remorse", "seller_fault_event":"verified_wrong_item"}),
        # 12. Contradictory evidence should route to review, not force a refund or denial.
        _case(seed, "evidence_contradiction", "conflicting_sources", "evidence_conflict", ("warehouse_inspection",), "The listing and product photos do not match.", "When customer evidence conflicts with warehouse inspection, route to seller review; aligned verified evidence supports the seller-fault remedy.", {"customer_evidence":"verified_mismatch", "warehouse_inspection":"verified_match", "seller_listing":"SKU-A"}),
        _case(seed, "evidence_contradiction", "aligned_sources", "evidence_conflict", ("warehouse_inspection",), "The listing and product photos do not match.", "When customer evidence conflicts with warehouse inspection, route to seller review; aligned verified evidence supports the seller-fault remedy.", {"customer_evidence":"verified_mismatch", "warehouse_inspection":"verified_mismatch", "seller_listing":"SKU-A"}),
    )


__all__ = ["FAMILY_ID", "FAMILY_VERSION", "MarketplaceV24Case", "SCENARIOS", "build_marketplace_v24_panel"]
