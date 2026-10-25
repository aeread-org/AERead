"""Independent V2.4 policy resolver.

This file intentionally contains policy logic rather than authored expected
answers so case admission can detect case/reference disagreement.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .v2_4_cases import MarketplaceV24Case


@dataclass(frozen=True, slots=True)
class V24Resolution:
    eligibility: str                 # eligible | ineligible | unresolved
    remedy: str                      # full_refund | partial_refund | none
    workflow: str                    # execute_refund | no_mutation | request_evidence | identity_review | seller_review | payment_review | return_and_inspect
    amount: float
    refund_method: str               # original_payment | none
    payment_mutation: str            # execute | none
    return_shipping_payer: str       # seller | customer | none
    policy_basis: str                # semantic policy bucket, not a wire code
    required_fact_ids: tuple[str, ...]


def _full(case: MarketplaceV24Case) -> float:
    return round(case.item_net_price + case.allocated_tax, 2)


def _out(eligibility: str, remedy: str, workflow: str, amount: float, basis: str, required: tuple[str, ...], payer: str = "none") -> V24Resolution:
    return V24Resolution(eligibility, remedy, workflow, round(amount, 2), "original_payment" if amount > 0 else "none", "execute" if workflow == "execute_refund" else "none", payer, basis, required)


def resolve_policy(case: MarketplaceV24Case) -> V24Resolution:
    f = case.facts
    s = case.scenario
    if s == "wrong_item_received":
        r = ("ordered_sku", "received_sku", "sku_evidence_status")
        return _out("unresolved", "none", "request_evidence", 0, "wrong_item_unverified", r) if f["sku_evidence_status"] != "verified" else _out("eligible", "full_refund", "execute_refund", _full(case), "wrong_item_verified", r, "seller")
    if s == "missing_parts_partial_refund":
        r = ("component_role", "component_catalog_value", "category_cap_rate", "evidence_status")
        if f["evidence_status"] != "verified": return _out("unresolved", "none", "request_evidence", 0, "component_unverified", r)
        if f["component_role"] == "core": return _out("eligible", "full_refund", "execute_refund", _full(case), "missing_core", r, "seller")
        return _out("eligible", "partial_refund", "execute_refund", min(float(f["component_catalog_value"]), case.item_net_price * float(f["category_cap_rate"])), "missing_noncore_cap", r)
    if s == "late_defect_identity_conflict":
        r = ("return_request_day", "defect_evidence", "inspection_stage", "order_serial", "inspection_serial")
        if f["inspection_stage"] == "post_return_warehouse" and f["order_serial"] != f["inspection_serial"]: return _out("unresolved", "none", "identity_review", 0, "identity_precedence", r)
        if f["defect_evidence"] == "verified" and int(f["return_request_day"]) <= 90: return _out("eligible", "full_refund", "execute_refund", _full(case), "defect_exception", r, "seller")
        return _out("unresolved", "none", "request_evidence", 0, "defect_not_verified", r)
    if s == "seller_fault_unverified_evidence":
        r = ("defect_evidence", "return_request_day")
        return _out("eligible", "full_refund", "execute_refund", _full(case), "seller_fault_verified", r, "seller") if f["defect_evidence"] == "verified" else _out("unresolved", "none", "request_evidence", 0, "seller_fault_unverified", r)
    if s == "multiple_missing_components":
        r = ("core_component_missing", "noncore_catalog_total", "evidence_status", "category_cap_rate")
        if f["evidence_status"] != "verified": return _out("unresolved", "none", "request_evidence", 0, "components_unverified", r)
        if f["core_component_missing"]: return _out("eligible", "full_refund", "execute_refund", _full(case), "core_precedence", r, "seller")
        return _out("eligible", "partial_refund", "execute_refund", min(float(f["noncore_catalog_total"]), case.item_net_price * float(f["category_cap_rate"])), "noncore_combined_cap", r)
    if s == "discounted_bundle_component_value":
        r = ("paid_component_allocation", "category_cap_rate", "evidence_status")
        if f["evidence_status"] != "verified": return _out("unresolved", "none", "request_evidence", 0, "bundle_unverified", r)
        return _out("eligible", "partial_refund", "execute_refund", min(float(f["paid_component_allocation"]), case.item_net_price * float(f["category_cap_rate"])), "bundle_paid_allocation", r)
    if s == "returnless_refund_high_value_exception":
        r = ("defect_evidence", "identity_risk", "returnless_threshold")
        if f["defect_evidence"] != "verified": return _out("unresolved", "none", "request_evidence", 0, "defect_unverified", r)
        if case.item_net_price <= float(f["returnless_threshold"]) and f["identity_risk"] == "low": return _out("eligible", "full_refund", "execute_refund", _full(case), "returnless_low_risk", r, "seller")
        return _out("unresolved", "none", "return_and_inspect", 0, "returnless_risk_exception", r, "seller")
    if s == "carrier_delay_request_date":
        r = ("return_request_day", "carrier_handover_day", "return_reason")
        if int(f["return_request_day"]) <= 30: return _out("eligible", "full_refund", "execute_refund", _full(case), "request_within_window", r, "customer")
        return _out("ineligible", "none", "no_mutation", 0, "request_outside_window", r)
    if s == "refund_already_issued_chargeback_pending":
        r = ("prior_refund_state", "chargeback_state")
        if f["chargeback_state"] == "pending": return _out("unresolved", "none", "payment_review", 0, "chargeback_pending", r)
        return _out("unresolved", "none", "payment_review", 0, "refund_already_pending", r)
    if s == "condition_deterioration_after_return":
        r = ("inspection_cause", "original_defect_evidence")
        if f["inspection_cause"] == "buyer_caused": return _out("unresolved", "none", "seller_review", 0, "buyer_deterioration", r)
        return _out("eligible", "full_refund", "execute_refund", _full(case), "carrier_damage_preserves_remedy", r, "seller")
    if s == "category_exclusion_seller_fault_override":
        r = ("category_final_sale", "return_reason", "seller_fault_event")
        if f["seller_fault_event"] != "none": return _out("eligible", "full_refund", "execute_refund", _full(case), "seller_fault_override", r, "seller")
        return _out("ineligible", "none", "no_mutation", 0, "final_sale_exclusion", r)
    if s == "evidence_contradiction":
        r = ("customer_evidence", "warehouse_inspection", "seller_listing")
        if f["customer_evidence"] != f["warehouse_inspection"]: return _out("unresolved", "none", "seller_review", 0, "evidence_conflict", r)
        return _out("eligible", "full_refund", "execute_refund", _full(case), "aligned_verified_mismatch", r, "seller")
    raise ValueError(f"unsupported V2.4 scenario: {s}")


def reference_dict(case: MarketplaceV24Case) -> Mapping[str, Any]:
    return asdict(resolve_policy(case))


__all__ = ["V24Resolution", "reference_dict", "resolve_policy"]
