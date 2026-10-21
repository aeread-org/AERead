"""V2.5 unified category-policy and interaction-policy catalog.

V2.4 measured interaction reasoning but deliberately omitted product categories.
V2.5 makes the category rule explicit and gives every policy agent a rendered,
case-local policy contract.  This module is also the admission gate: a case is
invalid if its category rule and its interaction overlay do not have exactly
one documented precedence path.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
from typing import Any, Mapping

from .v2_4_cases import MarketplaceV24Case, build_marketplace_v24_panel
from .v2_4_reference import V24Resolution, resolve_policy as resolve_interaction
from .v2_5_branches import DESIGN_VERSION, public_inputs, spec_for


FAMILY_VERSION = "2.5.0"
CATEGORIES = ("perishable_goods", "consumer_electronics", "software", "apparel")


@dataclass(frozen=True, slots=True)
class CategoryPolicy:
    category: str
    base_rule: str
    exclusions: str
    amount_rule: str


CATEGORY_POLICIES: Mapping[str, CategoryPolicy] = {
    "perishable_goods": CategoryPolicy(
        "perishable_goods",
        "Verified spoilage, damage, wrong-item, or seller-fault defect claims are eligible. A customer assertion alone is not verification.",
        "Buyer-remorse perishables are ineligible. A verified high-identity-risk item requires return_and_inspect before any refund.",
        "A full refund is item_net_price + allocated_tax. A permitted partial refund follows the interaction formula.",
    ),
    "consumer_electronics": CategoryPolicy(
        "consumer_electronics",
        "Verified manufacturing defects and verified wrong items are eligible. Verified post-return serial mismatch overrides a defect remedy and routes to identity_review.",
        "Customer-caused liquid damage is ineligible. A verified buyer-caused post-return deterioration routes to seller_review.",
        "A full refund is item_net_price + allocated_tax. Component refunds use the declared component formula.",
    ),
    "software": CategoryPolicy(
        "software",
        "Verified seller-fault delivery or entitlement failures are eligible; conflicting evidence routes to seller_review.",
        "A pending refund or chargeback never permits a second payment mutation and routes to payment_review.",
        "A full refund is item_net_price + allocated_tax. No payment is created while payment_review is pending.",
    ),
    "apparel": CategoryPolicy(
        "apparel",
        "Buyer-remorse returns are eligible only when the request is made on or before day 30. Verified wrong-item and seller-fault events are eligible.",
        "Final-sale excludes buyer-remorse returns, except a verified seller-fault event overrides that exclusion.",
        "A full refund is item_net_price + allocated_tax. Bundle/component refunds use the declared component formula.",
    ),
}

# The mapping is intentional: every interaction is exercised under a category
# whose base policy makes that interaction meaningful.  It is not a random
# product-label decoration.
SCENARIO_CATEGORY: Mapping[str, str] = {
    "wrong_item_received": "apparel",
    "missing_parts_partial_refund": "consumer_electronics",
    "late_defect_identity_conflict": "consumer_electronics",
    "seller_fault_unverified_evidence": "perishable_goods",
    "multiple_missing_components": "consumer_electronics",
    "discounted_bundle_component_value": "apparel",
    "returnless_refund_high_value_exception": "perishable_goods",
    "carrier_delay_request_date": "apparel",
    "refund_already_issued_chargeback_pending": "software",
    "condition_deterioration_after_return": "consumer_electronics",
    "category_exclusion_seller_fault_override": "apparel",
    "evidence_contradiction": "software",
    # V2.5-only operational extension.  These retain the same public-policy
    # contract but vary intake routing or payment-ledger state.
    "intake_identity_branch": "consumer_electronics",
    "intake_evidence_branch": "software",
    "payments_proportional_tender": "consumer_electronics",
    "payments_idempotency_retry": "software",
    "payments_residual_waterfall": "software",
    "payments_three_tender_rounding": "consumer_electronics",
    "payments_prior_refund_reconciliation": "software",
    "payments_rail_fallback": "software",
    # Policy stress extension: category base rules and interaction overlays
    # produce distinct, publicly derivable precedence paths.
    "policy_identity_override": "consumer_electronics",
    "policy_evidence_conflict": "software",
    "policy_seller_fault_override": "apparel",
    "policy_time_anchor": "apparel",
    "policy_perishable_verification": "perishable_goods",
    "policy_bundle_cap": "consumer_electronics",
    "policy_return_liability": "consumer_electronics",
    "policy_payment_hold_precedence": "software",
    "policy_identity_followup": "consumer_electronics",
    "policy_bundle_boundary": "consumer_electronics",
    "policy_payment_reconcile": "software",
    "policy_evidence_inconclusive": "software",
    "frontier_precedence_ladder": "consumer_electronics",
    "frontier_branch_reversal": "software",
    "frontier_evidence_provenance": "software",
    "frontier_override_window": "apparel",
    "frontier_piecewise_amount": "consumer_electronics",
    "frontier_liability_then_amount": "perishable_goods",
    "frontier_hard_authority_flip": "consumer_electronics",
    "frontier_hard_override_liability": "consumer_electronics",
    "frontier_hard_payment_identity": "consumer_electronics",
    "frontier_hard_evidence_reversal": "software",
    "frontier_hard_piecewise_tax": "consumer_electronics",
    "frontier_hard_window_override": "apparel",
    "frontier_hard_refund_reconciliation": "software",
    "frontier_hard_evidence_stop": "consumer_electronics",
}

# Earlier rows have higher priority.  The resolver's scenario rules are the
# executable expression of this table; the table is sent to the agent too.
PRECEDENCE = (
    "payment_state_safety",          # never duplicate a payment
    "identity_integrity",            # serial mismatch before refund
    "contradictory_or_missing_evidence",
    "category_hard_exclusion",
    "explicit_seller_fault_override",
    "category_eligibility_window",
    "remedy_and_amount_calculation",
    "canonical_execution_contract",
)

# These identifiers are public vocabulary, not labels supplied by the
# reference outcome.  A policy agent selects one after applying the catalogue.
RULE_IDS = {
    "identity_hold": "R_IDENTITY_HOLD",
    "identity_clear": "R_VERIFIED_DEFECT_REFUND",
    "evidence_conflict": "R_EVIDENCE_CONFLICT_REVIEW",
    "evidence_clear": "R_VERIFIED_SELLER_FAULT_REFUND",
    "seller_fault_override": "R_SELLER_FAULT_OVERRIDE",
    "final_sale": "R_FINAL_SALE_EXCLUSION",
    "time_window": "R_RETURN_WINDOW",
    "perishable_unverified": "R_PERISHABLE_VERIFICATION",
    "defect_unverified": "R_DEFECT_VERIFICATION",
    "bundle_cap": "R_COMPONENT_CAP",
    "return_liability": "R_POST_RETURN_LIABILITY",
    "payment_hold": "R_PAYMENT_HOLD",
}

_POLICY_STRESS = frozenset({
    "policy_identity_override", "policy_evidence_conflict",
    "policy_seller_fault_override", "policy_time_anchor",
    "policy_perishable_verification", "policy_bundle_cap",
    "policy_return_liability", "policy_payment_hold_precedence",
})


def _public_rule_id(label: str) -> str:
    """Canonical public identifier for both legacy and V2.5-only rules."""
    if label.startswith("R_"):
        return label
    return "R_" + "".join(char if char.isalnum() else "_" for char in label.upper()).strip("_")


@dataclass(frozen=True, slots=True)
class UnifiedRefundCase:
    interaction: MarketplaceV24Case
    product_category: str

    @property
    def case_id(self) -> str:
        return self.interaction.case_id.replace("refund_v2.4", "refund_v2.5")

    @property
    def facts(self) -> Mapping[str, object]:
        # Intake deliberately sees these IDs alongside the determinative IDs.
        # The values are private and none of the distractors is legal to
        # request.  This prevents the seat from treating the available-ID list
        # as a disguised copy of the policy oracle.
        return {**self.interaction.facts, **_INTAKE_DECOY_FACTS[self.interaction.scenario]}


# These fields are deliberately plausible customer/order metadata, but do not
# determine the V2.5 resolution.  They make fact selection a routing task.
_INTAKE_DECOY_FACTS: Mapping[str, Mapping[str, object]] = {
    scenario: {"customer_sentiment": "frustrated", "order_note": "standard order"}
    for scenario in SCENARIO_CATEGORY
} | {
    "late_defect_identity_conflict": {"carrier_handover_day": 3, "customer_sentiment": "frustrated"},
    "refund_already_issued_chargeback_pending": {"defect_evidence": "customer_assertion", "customer_sentiment": "frustrated"},
    "discounted_bundle_component_value": {"standalone_catalog_value": 180.0, "customer_sentiment": "frustrated"},
}


def intake_routing_plan(case: UnifiedRefundCase) -> Mapping[str, Any]:
    """Public, value-blind guidance for the intake seat.

    The plan gives a routing objective, never the determinative fact IDs.
    Correctness is evaluated against the hidden reference set in the
    transition guard.  This preserves intake's strict no-private-values view.
    """
    scenario = case.interaction.scenario
    if scenario in {"late_defect_identity_conflict", "returnless_refund_high_value_exception", "intake_identity_branch", "policy_identity_override", "policy_identity_followup", "frontier_precedence_ladder", "frontier_hard_payment_identity", "frontier_hard_evidence_stop"}:
        objective = "Prioritize identity/risk and verification facts before remedy or amount facts."
        route_kind = "identity"
    elif scenario in {"refund_already_issued_chargeback_pending", "policy_payment_hold_precedence", "policy_payment_reconcile", "frontier_branch_reversal"}:
        objective = "Prioritize existing payment-state facts; do not collect product-condition metadata first."
        route_kind = "payment_state"
    elif scenario in {"evidence_contradiction", "wrong_item_received", "seller_fault_unverified_evidence", "intake_evidence_branch", "policy_evidence_conflict", "policy_perishable_verification", "policy_return_liability", "policy_evidence_inconclusive", "frontier_evidence_provenance", "frontier_liability_then_amount", "frontier_hard_authority_flip", "frontier_hard_evidence_reversal"}:
        objective = "Prioritize evidence-source and verification facts before remedy or amount facts."
        route_kind = "evidence"
    elif scenario in {"carrier_delay_request_date", "category_exclusion_seller_fault_override", "policy_seller_fault_override", "policy_time_anchor", "frontier_override_window", "frontier_hard_override_liability", "frontier_hard_window_override"}:
        objective = "Prioritize the eligibility time-anchor or exclusion/override facts before amount facts."
        route_kind = "eligibility"
    else:
        objective = "Prioritize verification and remedy-classification facts before amount facts."
        route_kind = "verification"
    return {
        "interaction_id": scenario,
        "objective": objective,
        "route_kind": route_kind,
        "max_batch_size": 3,
        "request_only": "unrevealed facts material to eligibility, risk routing, evidence, remedy, or amount",
        "do_not_request": "customer sentiment, free-text order notes, or other convenience metadata",
    }


def payment_ledger(case: UnifiedRefundCase, amount: float) -> Mapping[str, Any]:
    """Case-local ledger state exposed only after proposal confirmation."""
    scenario = case.interaction.scenario
    if scenario == "payments_idempotency_retry" and case.interaction.facts["prior_execution_state"] == "applied":
        return {"ledger_snapshot_id": f"ledger-{case.case_id}", "state": "idempotency_key_already_applied", "refund_allocations": (), "already_applied": True}
    if amount <= 0:
        state = "chargeback_open" if scenario == "refund_already_issued_chargeback_pending" else "no_mutation_required"
        return {"ledger_snapshot_id": f"ledger-{case.case_id}", "state": state, "refund_allocations": ()}
    if scenario == "payments_proportional_tender":
        mix = str(case.interaction.facts["payment_ledger_mix"])
        card_share = 0.70 if mix == "card_70_credit_30" else 0.30
        card = round(amount * card_share, 2)
        return {
            "ledger_snapshot_id": f"ledger-{case.case_id}", "state": "captured_multi_tender_proportional",
            "allocation_rule": "proportional_original_tender",
            "original_tender_shares": (
                {"instrument": "card_4242", "share": card_share},
                {"instrument": "store_credit", "share": round(1 - card_share, 2)},
            ),
            "refund_allocations": (
                {"instrument": "card_4242", "amount": card},
                {"instrument": "store_credit", "amount": round(amount - card, 2)},
            ),
        }
    if scenario == "payments_residual_waterfall":
        profile = str(case.interaction.facts["payment_ledger_profile"])
        rows = (
            ({"instrument": "card_4242", "remaining_capacity": 19.37}, {"instrument": "wallet", "remaining_capacity": 23.68}, {"instrument": "store_credit", "remaining_capacity": amount})
            if profile == "card_then_wallet"
            else ({"instrument": "wallet", "remaining_capacity": 31.19}, {"instrument": "store_credit", "remaining_capacity": 17.86}, {"instrument": "card_4242", "remaining_capacity": amount})
        )
        remaining = amount; allocations = []
        for row in rows:
            allocated = min(remaining, float(row["remaining_capacity"]))
            allocations.append({"instrument": row["instrument"], "amount": round(allocated, 2)})
            remaining = round(remaining - allocated, 2)
        return {"ledger_snapshot_id": f"ledger-{case.case_id}", "state": "captured_with_prior_refunds", "allocation_rule": "waterfall_remaining_capacity", "tender_capacities": rows, "refund_allocations": tuple(allocations)}
    if scenario == "payments_three_tender_rounding":
        weights = (0.3333, 0.3333, 0.3334) if case.interaction.facts["payment_ledger_weights"] == "3333_3333_3334" else (0.4141, 0.2727, 0.3132)
        shares = tuple({"instrument": instrument, "share": share} for instrument, share in zip(("card_4242", "wallet", "store_credit"), weights, strict=True))
        first = round(amount * weights[0], 2); second = round(amount * weights[1], 2)
        return {"ledger_snapshot_id": f"ledger-{case.case_id}", "state": "captured_three_tender", "allocation_rule": "proportional_original_tender", "original_tender_shares": shares, "refund_allocations": ({"instrument": "card_4242", "amount": first}, {"instrument": "wallet", "amount": second}, {"instrument": "store_credit", "amount": round(amount - first - second, 2)})}
    if scenario == "payments_prior_refund_reconciliation":
        settled = round(int(case.interaction.facts["settled_refund_cents"]) / 100, 2)
        residual = round(max(0.0, amount - settled), 2)
        return {"ledger_snapshot_id": f"ledger-{case.case_id}", "state": "prior_refund_reconciliation", "allocation_rule": "residual_after_settled_refunds", "original_tender": "card_4242", "settled_refund_amount": settled, "requested_amount": amount, "executable_amount": residual, "refund_allocations": ({"instrument": "card_4242", "amount": residual},) if residual else ()}
    if scenario == "payments_rail_fallback":
        closed = case.interaction.facts["primary_rail_state"] == "closed"
        instrument = "store_credit" if closed else "card_4242"
        return {"ledger_snapshot_id": f"ledger-{case.case_id}", "state": "primary_rail_closed" if closed else "primary_rail_open", "allocation_rule": "original_rail_then_allowed_fallback", "original_rail": "card_4242", "allowed_fallback_rail": "store_credit", "refund_allocations": ({"instrument": instrument, "amount": amount},)}
    if scenario in {"discounted_bundle_component_value", "missing_parts_partial_refund", "multiple_missing_components"}:
        card = round(amount * 0.6, 2)
        return {
            "ledger_snapshot_id": f"ledger-{case.case_id}", "state": "captured_multi_tender",
            "refund_allocations": (
                {"instrument": "card_4242", "amount": card},
                {"instrument": "store_credit", "amount": round(amount - card, 2)},
            ),
        }
    return {
        "ledger_snapshot_id": f"ledger-{case.case_id}",
        "state": "captured",
        "refund_allocations": ({"instrument": "card_4242", "amount": round(amount, 2)},),
    }


def _extension_price(seed: int, pair_id: str, low: int, high: int) -> float:
    digest = hashlib.sha256(f"refund-v25-extension:{seed}:{pair_id}".encode()).digest()
    return round((low + int.from_bytes(digest[:8], "big") % (high - low + 1)) / 100, 2)


def build_operational_extension_panel(seed: int) -> tuple[UnifiedRefundCase, ...]:
    """Eight V2.5-only cells: four counterfactual pairs for intake/payments.

    The interaction panel remains untouched.  These cases are opt-in because
    they test operational decision quality rather than the historical V2.4
    policy estimand.
    """
    def make(scenario: str, variant: str, pair: str, changed: tuple[str, ...], claim: str, facts: Mapping[str, object], *, low: int = 6000, high: int = 42000) -> UnifiedRefundCase:
        price = _extension_price(seed, pair, low, high)
        interaction = MarketplaceV24Case(
            f"refund_v2.4.{scenario}.{variant}.{seed:06d}", seed, scenario, variant,
            pair, changed, claim, "V2.5 operational extension.", price,
            round(price * 0.0825, 2), dict(facts),
        )
        return UnifiedRefundCase(interaction, SCENARIO_CATEGORY[scenario])

    return (
        # Intake must open the identity branch, not request a price/note first.
        make("intake_identity_branch", "serial_mismatch", "v25_intake_identity", ("inspection_serial",), "The returned device is defective, but the warehouse raised an identity question.", {"defect_evidence": "verified", "inspection_stage": "post_return_warehouse", "order_serial": "D-100", "inspection_serial": "D-200", "component_catalog_value": 999.0, "customer_note": "please hurry"}, low=50000, high=150000),
        make("intake_identity_branch", "serial_match", "v25_intake_identity", ("inspection_serial",), "The returned device is defective, but the warehouse raised an identity question.", {"defect_evidence": "verified", "inspection_stage": "post_return_warehouse", "order_serial": "D-100", "inspection_serial": "D-100", "component_catalog_value": 999.0, "customer_note": "please hurry"}, low=50000, high=150000),
        # Intake must collect the conflicting sources before any amount detail.
        make("intake_evidence_branch", "conflicting_sources", "v25_intake_evidence", ("warehouse_inspection",), "The product photo and listing appear inconsistent.", {"customer_photo_status": "verified_mismatch", "warehouse_inspection": "verified_match", "listing_snapshot": "SKU-A", "catalog_price": 180.0, "delivery_comment": "left at door"}),
        make("intake_evidence_branch", "aligned_sources", "v25_intake_evidence", ("warehouse_inspection",), "The product photo and listing appear inconsistent.", {"customer_photo_status": "verified_mismatch", "warehouse_inspection": "verified_mismatch", "listing_snapshot": "SKU-A", "catalog_price": 180.0, "delivery_comment": "left at door"}),
        # Same policy resolution, but counterfactual original-tender mix means
        # payments must calculate different proportional allocations.
        make("payments_proportional_tender", "card_heavy", "v25_payment_tender", ("payment_ledger_mix",), "A verified accessory is missing from the device box.", {"evidence_status": "verified", "component_catalog_value": 9999.0, "category_cap_rate": 0.30, "payment_ledger_mix": "card_70_credit_30"}),
        make("payments_proportional_tender", "credit_heavy", "v25_payment_tender", ("payment_ledger_mix",), "A verified accessory is missing from the device box.", {"evidence_status": "verified", "component_catalog_value": 9999.0, "category_cap_rate": 0.30, "payment_ledger_mix": "card_30_credit_70"}),
        # The policy still approves a refund; a ledger replay makes execution a
        # safe idempotent no-op rather than a second mutation.
        make("payments_idempotency_retry", "not_previously_applied", "v25_payment_idempotency", ("prior_execution_state",), "The seller sent a verified defective software entitlement.", {"defect_evidence": "verified", "prior_execution_state": "absent"}),
        make("payments_idempotency_retry", "already_applied", "v25_payment_idempotency", ("prior_execution_state",), "The seller sent a verified defective software entitlement.", {"defect_evidence": "verified", "prior_execution_state": "applied"}),
        # A constrained waterfall forces payments to calculate the residual on
        # each tender rather than simply echo a preferred payment method.
        make("payments_residual_waterfall", "card_then_wallet", "v25_payment_waterfall", ("payment_ledger_profile",), "A verified defective software entitlement must be refunded.", {"defect_evidence": "verified", "payment_ledger_profile": "card_then_wallet"}, low=16000, high=24000),
        make("payments_residual_waterfall", "wallet_then_credit", "v25_payment_waterfall", ("payment_ledger_profile",), "A verified defective software entitlement must be refunded.", {"defect_evidence": "verified", "payment_ledger_profile": "wallet_then_credit"}, low=16000, high=24000),
        # Three-tender proportional allocation stresses cent rounding and final
        # residual assignment under two counterfactual original mixes.
        make("payments_three_tender_rounding", "uneven_weights", "v25_payment_rounding", ("payment_ledger_weights",), "A verified accessory is missing from the device box.", {"evidence_status": "verified", "component_catalog_value": 9999.0, "category_cap_rate": 0.30, "payment_ledger_weights": "3333_3333_3334"}),
        make("payments_three_tender_rounding", "skewed_weights", "v25_payment_rounding", ("payment_ledger_weights",), "A verified accessory is missing from the device box.", {"evidence_status": "verified", "component_catalog_value": 9999.0, "category_cap_rate": 0.30, "payment_ledger_weights": "4141_2727_3132"}),
        # A settled earlier refund reduces the executable residual while the
        # policy resolution remains the original approved obligation.
        make("payments_prior_refund_reconciliation", "no_prior_refund", "v25_payment_reconcile", ("settled_refund_cents",), "A verified defective software entitlement must be refunded.", {"defect_evidence": "verified", "settled_refund_cents": 0}, low=18000, high=26000),
        make("payments_prior_refund_reconciliation", "partial_prior_refund", "v25_payment_reconcile", ("settled_refund_cents",), "A verified defective software entitlement must be refunded.", {"defect_evidence": "verified", "settled_refund_cents": 2713}, low=18000, high=26000),
        # Original rail may be unavailable; payments may use only the explicit
        # fallback rail, and only when the original rail is closed.
        make("payments_rail_fallback", "primary_rail_open", "v25_payment_rail", ("primary_rail_state",), "A verified defective software entitlement must be refunded.", {"defect_evidence": "verified", "primary_rail_state": "open"}),
        make("payments_rail_fallback", "primary_rail_closed", "v25_payment_rail", ("primary_rail_state",), "A verified defective software entitlement must be refunded.", {"defect_evidence": "verified", "primary_rail_state": "closed"}),
    )


def build_policy_stress_panel(seed: int) -> tuple[UnifiedRefundCase, ...]:
    """Sixteen category × interaction cases for conditional policy reasoning."""
    def make(scenario: str, variant: str, pair: str, changed: tuple[str, ...], claim: str, facts: Mapping[str, object], *, low: int = 6000, high: int = 42000) -> UnifiedRefundCase:
        price = _extension_price(seed, pair, low, high)
        interaction = MarketplaceV24Case(
            f"refund_v2.4.{scenario}.{variant}.{seed:06d}", seed, scenario, variant,
            pair, changed, claim, "V2.5 policy stress extension.", price,
            round(price * 0.0825, 2), dict(facts),
        )
        return UnifiedRefundCase(interaction, SCENARIO_CATEGORY[scenario])
    return (
        make("policy_identity_override", "serial_mismatch", "v25_policy_identity", ("inspection_serial",), "The returned electronics item has a verified defect.", {"defect_evidence": "verified", "inspection_stage": "post_return_warehouse", "order_serial": "E-1", "inspection_serial": "E-2"}, low=50000, high=150000),
        make("policy_identity_override", "serial_match", "v25_policy_identity", ("inspection_serial",), "The returned electronics item has a verified defect.", {"defect_evidence": "verified", "inspection_stage": "post_return_warehouse", "order_serial": "E-1", "inspection_serial": "E-1"}, low=50000, high=150000),
        make("policy_evidence_conflict", "conflict", "v25_policy_evidence", ("warehouse_inspection",), "The delivered software entitlement does not match the listing.", {"customer_evidence": "verified_mismatch", "warehouse_inspection": "verified_match", "listing_snapshot": "ENT-A"}),
        make("policy_evidence_conflict", "aligned", "v25_policy_evidence", ("warehouse_inspection",), "The delivered software entitlement does not match the listing.", {"customer_evidence": "verified_mismatch", "warehouse_inspection": "verified_mismatch", "listing_snapshot": "ENT-A"}),
        make("policy_seller_fault_override", "ordinary_final_sale", "v25_policy_seller_override", ("seller_fault_event",), "I want to return this final-sale apparel item.", {"category_final_sale": True, "return_reason": "buyer_remorse", "seller_fault_event": "none"}),
        make("policy_seller_fault_override", "verified_wrong_item", "v25_policy_seller_override", ("seller_fault_event",), "I want to return this final-sale apparel item.", {"category_final_sale": True, "return_reason": "buyer_remorse", "seller_fault_event": "verified_wrong_item"}),
        make("policy_time_anchor", "day_29", "v25_policy_time", ("return_request_day",), "I initiated an apparel return while carrier handover was delayed.", {"return_request_day": 29, "carrier_handover_day": 35, "return_reason": "buyer_remorse"}),
        make("policy_time_anchor", "day_31", "v25_policy_time", ("return_request_day",), "I initiated an apparel return while carrier handover was delayed.", {"return_request_day": 31, "carrier_handover_day": 35, "return_reason": "buyer_remorse"}),
        make("policy_perishable_verification", "unverified", "v25_policy_perishable", ("spoilage_evidence",), "My perishable order arrived spoiled.", {"spoilage_evidence": "customer_assertion", "delivery_day": 1}),
        make("policy_perishable_verification", "verified", "v25_policy_perishable", ("spoilage_evidence",), "My perishable order arrived spoiled.", {"spoilage_evidence": "verified", "delivery_day": 1}),
        make("policy_bundle_cap", "below_cap", "v25_policy_bundle", ("paid_component_allocation",), "A component is missing from a discounted electronics bundle.", {"evidence_status": "verified", "paid_component_allocation": 7.13, "category_cap_rate": 0.30}),
        make("policy_bundle_cap", "above_cap", "v25_policy_bundle", ("paid_component_allocation",), "A component is missing from a discounted electronics bundle.", {"evidence_status": "verified", "paid_component_allocation": 9999.0, "category_cap_rate": 0.30}),
        make("policy_return_liability", "buyer_damage", "v25_policy_liability", ("inspection_cause",), "The returned electronics item was damaged after shipment back.", {"original_defect_evidence": "verified", "inspection_cause": "buyer_caused"}),
        make("policy_return_liability", "carrier_damage", "v25_policy_liability", ("inspection_cause",), "The returned electronics item was damaged after shipment back.", {"original_defect_evidence": "verified", "inspection_cause": "carrier_damage"}),
        make("policy_payment_hold_precedence", "chargeback_open", "v25_policy_payment_hold", ("chargeback_state",), "The software entitlement was defective and I filed a payment dispute.", {"defect_evidence": "verified", "chargeback_state": "pending"}),
        make("policy_payment_hold_precedence", "no_chargeback", "v25_policy_payment_hold", ("chargeback_state",), "The software entitlement was defective and I filed a payment dispute.", {"defect_evidence": "verified", "chargeback_state": "none"}),
        make("policy_identity_followup", "unverified_after_match", "v25_policy_identity_followup", ("defect_evidence",), "The returned electronics item has a reported defect and is undergoing inspection.", {"inspection_stage": "post_return_warehouse", "order_serial": "F-1", "inspection_serial": "F-1", "defect_evidence": "customer_assertion"}, low=50000, high=150000),
        make("policy_identity_followup", "verified_after_match", "v25_policy_identity_followup", ("defect_evidence",), "The returned electronics item has a reported defect and is undergoing inspection.", {"inspection_stage": "post_return_warehouse", "order_serial": "F-1", "inspection_serial": "F-1", "defect_evidence": "verified"}, low=50000, high=150000),
        make("policy_bundle_boundary", "just_below_cap", "v25_policy_bundle_boundary", ("paid_component_allocation",), "A verified component is missing from a discounted electronics bundle.", {"evidence_status": "verified", "paid_component_allocation": 95.92, "category_cap_rate": 0.30}, low=31977, high=31977),
        make("policy_bundle_boundary", "at_cap", "v25_policy_bundle_boundary", ("paid_component_allocation",), "A verified component is missing from a discounted electronics bundle.", {"evidence_status": "verified", "paid_component_allocation": 95.93, "category_cap_rate": 0.30}, low=31977, high=31977),
        make("policy_payment_reconcile", "prior_refund_issued", "v25_policy_reconcile_hold", ("prior_refund_state",), "The software entitlement is defective and its payment history requires review.", {"chargeback_state": "none", "prior_refund_state": "issued", "defect_evidence": "verified"}),
        make("policy_payment_reconcile", "no_prior_refund", "v25_policy_reconcile_hold", ("prior_refund_state",), "The software entitlement is defective and its payment history requires review.", {"chargeback_state": "none", "prior_refund_state": "none", "defect_evidence": "verified"}),
        make("policy_evidence_inconclusive", "inconclusive", "v25_policy_evidence_inconclusive", ("warehouse_inspection",), "The delivered software entitlement does not match the listing.", {"customer_evidence": "verified_mismatch", "warehouse_inspection": "inconclusive", "listing_snapshot": "ENT-A"}),
        make("policy_evidence_inconclusive", "verified", "v25_policy_evidence_inconclusive", ("warehouse_inspection",), "The delivered software entitlement does not match the listing.", {"customer_evidence": "verified_mismatch", "warehouse_inspection": "verified_mismatch", "listing_snapshot": "ENT-A"}),
    )


def build_policy_frontier_panel(seed: int) -> tuple[UnifiedRefundCase, ...]:
    """Twelve high-difficulty, branch-trace policy cases.

    This panel is opt-in and reported separately from the V2.5 stress panel.
    Every pair has the same public claim and changes exactly one private fact.
    """
    def make(scenario: str, variant: str, pair: str, changed: tuple[str, ...], claim: str, facts: Mapping[str, object], *, low: int = 6000, high: int = 42000) -> UnifiedRefundCase:
        price = _extension_price(seed, pair, low, high)
        interaction = MarketplaceV24Case(
            f"refund_v2.4.{scenario}.{variant}.{seed:06d}", seed, scenario, variant,
            pair, changed, claim, "V2.5 frontier policy challenge.", price,
            round(price * 0.0825, 2), dict(facts),
        )
        return UnifiedRefundCase(interaction, SCENARIO_CATEGORY[scenario])
    return (
        make("frontier_precedence_ladder", "serial_mismatch", "frontier_precedence", ("inspection_serial",), "The returned item has a verified defect and its payment and inspection records require review.", {"chargeback_state": "none", "inspection_stage": "post_return_warehouse", "order_serial": "L-1", "inspection_serial": "L-2", "defect_evidence": "verified"}, low=70000, high=120000),
        make("frontier_precedence_ladder", "serial_match", "frontier_precedence", ("inspection_serial",), "The returned item has a verified defect and its payment and inspection records require review.", {"chargeback_state": "none", "inspection_stage": "post_return_warehouse", "order_serial": "L-1", "inspection_serial": "L-1", "defect_evidence": "verified"}, low=70000, high=120000),
        make("frontier_branch_reversal", "prior_refund_issued", "frontier_reversal", ("prior_refund_state",), "The software entitlement is defective and its payment history requires review.", {"chargeback_state": "none", "prior_refund_state": "issued", "defect_evidence": "verified"}),
        make("frontier_branch_reversal", "no_prior_refund", "frontier_reversal", ("prior_refund_state",), "The software entitlement is defective and its payment history requires review.", {"chargeback_state": "none", "prior_refund_state": "none", "defect_evidence": "verified"}),
        make("frontier_evidence_provenance", "inconclusive", "frontier_provenance", ("warehouse_inspection",), "Evidence from the customer, warehouse, and listing must be reconciled.", {"customer_evidence": "verified_mismatch", "warehouse_inspection": "inconclusive", "listing_snapshot": "ENT-A"}),
        make("frontier_evidence_provenance", "corroborated", "frontier_provenance", ("warehouse_inspection",), "Evidence from the customer, warehouse, and listing must be reconciled.", {"customer_evidence": "verified_mismatch", "warehouse_inspection": "verified_mismatch", "listing_snapshot": "ENT-A"}),
        make("frontier_override_window", "ordinary_remorse", "frontier_override", ("seller_fault_event",), "A final-sale apparel return was requested after the ordinary return window.", {"category_final_sale": True, "return_request_day": 31, "return_reason": "buyer_remorse", "seller_fault_event": "none"}),
        make("frontier_override_window", "verified_seller_fault", "frontier_override", ("seller_fault_event",), "A final-sale apparel return was requested after the ordinary return window.", {"category_final_sale": True, "return_request_day": 31, "return_reason": "buyer_remorse", "seller_fault_event": "verified_wrong_item"}),
        make("frontier_piecewise_amount", "below_cap", "frontier_piecewise", ("paid_component_allocation",), "A verified component is missing from a discounted electronics bundle.", {"evidence_status": "verified", "paid_component_allocation": 95.92, "category_cap_rate": 0.30, "allocated_component_tax": 0.47}, low=31977, high=31977),
        make("frontier_piecewise_amount", "at_cap", "frontier_piecewise", ("paid_component_allocation",), "A verified component is missing from a discounted electronics bundle.", {"evidence_status": "verified", "paid_component_allocation": 95.93, "category_cap_rate": 0.30, "allocated_component_tax": 0.47}, low=31977, high=31977),
        make("frontier_liability_then_amount", "buyer_caused", "frontier_liability", ("inspection_cause",), "A verified defect was followed by damage during the return shipment.", {"original_defect_evidence": "verified", "inspection_cause": "buyer_caused"}),
        make("frontier_liability_then_amount", "carrier_damage", "frontier_liability", ("inspection_cause",), "A verified defect was followed by damage during the return shipment.", {"original_defect_evidence": "verified", "inspection_cause": "carrier_damage"}),
    )


def build_policy_frontier_hard_panel(seed: int) -> tuple[UnifiedRefundCase, ...]:
    def make(scenario: str, variant: str, pair: str, changed: tuple[str, ...], claim: str, facts: Mapping[str, object], *, low: int = 6000, high: int = 42000) -> UnifiedRefundCase:
        price = _extension_price(seed, pair, low, high)
        facts = dict(facts)
        # Reserved comparison seeds vary shared, substantive facts inside each
        # pair. Historical development seeds (1-3) remain unchanged.
        if seed >= 100:
            if scenario == "frontier_hard_authority_flip":
                facts.update(order_serial=f"E-{seed}", inspection_serial=f"E-{seed}")
            elif scenario == "frontier_hard_payment_identity":
                facts["order_serial"] = f"P-{seed}"
                facts["inspection_serial"] = f"P-{seed + (1 if variant == 'serial_mismatch' else 0)}"
            elif scenario == "frontier_hard_piecewise_tax":
                facts["allocated_component_tax"] = round(0.30 + (seed % 7) / 10, 2)
            elif scenario == "frontier_hard_window_override":
                facts["return_request_day"] = 31 + seed % 11
            elif scenario == "frontier_hard_refund_reconciliation" and variant == "positive_residual":
                facts["settled_refund_cents"] = 2000 + 37 * (seed % 20)
            elif scenario == "frontier_hard_evidence_stop":
                facts.update(order_serial=f"S-{seed}", inspection_serial=f"S-{seed}")
        interaction = MarketplaceV24Case(f"refund_v2.4.{scenario}.{variant}.{seed:06d}", seed, scenario, variant, pair, changed, claim, "V2.5 frontier-hard policy challenge.", price, round(price * 0.0825, 2), facts)
        return UnifiedRefundCase(interaction, SCENARIO_CATEGORY[scenario])
    return (
        make("frontier_hard_authority_flip", "authoritative_mismatch", "hard_authority", ("serial_registry",), "The returned electronics item has conflicting inspection records.", {"customer_evidence": "verified_mismatch", "warehouse_inspection": "verified_mismatch", "serial_registry": "mismatch", "inspection_serial": "E-1", "order_serial": "E-1"}, low=70000, high=120000),
        make("frontier_hard_authority_flip", "non_authoritative_mismatch", "hard_authority", ("serial_registry",), "The returned electronics item has conflicting inspection records.", {"customer_evidence": "verified_mismatch", "warehouse_inspection": "verified_mismatch", "serial_registry": "match", "inspection_serial": "E-1", "order_serial": "E-1"}, low=70000, high=120000),
        make("frontier_hard_override_liability", "buyer_caused", "hard_liability", ("inspection_cause",), "A final-sale device has a verified seller-fault event and was damaged after return.", {"category_final_sale": True, "seller_fault_event": "verified_wrong_item", "inspection_cause": "buyer_caused", "original_defect_evidence": "verified"}),
        make("frontier_hard_override_liability", "carrier_damage", "hard_liability", ("inspection_cause",), "A final-sale device has a verified seller-fault event and was damaged after return.", {"category_final_sale": True, "seller_fault_event": "verified_wrong_item", "inspection_cause": "carrier_damage", "original_defect_evidence": "verified"}),
        make("frontier_hard_payment_identity", "serial_mismatch", "hard_payment_identity", ("inspection_serial",), "A defective returned device has payment and identity records requiring review.", {"chargeback_state": "none", "inspection_stage": "post_return_warehouse", "order_serial": "P-1", "inspection_serial": "P-2", "defect_evidence": "verified"}, low=70000, high=120000),
        make("frontier_hard_payment_identity", "serial_match", "hard_payment_identity", ("inspection_serial",), "A defective returned device has payment and identity records requiring review.", {"chargeback_state": "none", "inspection_stage": "post_return_warehouse", "order_serial": "P-1", "inspection_serial": "P-1", "defect_evidence": "verified"}, low=70000, high=120000),
        make("frontier_hard_evidence_reversal", "stale_listing", "hard_evidence_reversal", ("listing_snapshot",), "Three evidence sources must be reconciled against the authoritative listing.", {"customer_evidence": "verified_mismatch", "warehouse_inspection": "verified_mismatch", "listing_snapshot": "ENT-OLD"}),
        make("frontier_hard_evidence_reversal", "current_listing", "hard_evidence_reversal", ("listing_snapshot",), "Three evidence sources must be reconciled against the authoritative listing.", {"customer_evidence": "verified_mismatch", "warehouse_inspection": "verified_mismatch", "listing_snapshot": "ENT-A"}),
        make("frontier_hard_piecewise_tax", "below_cap", "hard_piecewise_tax", ("paid_component_allocation",), "A verified bundle component is missing and its paid value is near the policy cap.", {"evidence_status": "verified", "paid_component_allocation": 95.92, "category_cap_rate": 0.30, "allocated_component_tax": 0.47}, low=31977, high=31977),
        make("frontier_hard_piecewise_tax", "at_cap", "hard_piecewise_tax", ("paid_component_allocation",), "A verified bundle component is missing and its paid value is near the policy cap.", {"evidence_status": "verified", "paid_component_allocation": 95.93, "category_cap_rate": 0.30, "allocated_component_tax": 0.47}, low=31977, high=31977),
        make("frontier_hard_window_override", "ordinary_late", "hard_window", ("seller_fault_event",), "A final-sale apparel return was requested after day 30.", {"category_final_sale": True, "return_request_day": 31, "return_reason": "buyer_remorse", "seller_fault_event": "none", "identity_risk": "low"}),
        make("frontier_hard_window_override", "fault_late", "hard_window", ("seller_fault_event",), "A final-sale apparel return was requested after day 30.", {"category_final_sale": True, "return_request_day": 31, "return_reason": "buyer_remorse", "seller_fault_event": "verified_wrong_item", "identity_risk": "low"}),
        make("frontier_hard_refund_reconciliation", "positive_residual", "hard_reconciliation", ("settled_refund_cents",), "A verified defect has a payment obligation that may already be partly settled.", {"defect_evidence": "verified", "settled_refund_cents": 2713}, low=18000, high=26000),
        make("frontier_hard_refund_reconciliation", "zero_residual", "hard_reconciliation", ("settled_refund_cents",), "A verified defect has a payment obligation that may already be partly settled.", {"defect_evidence": "verified", "settled_refund_cents": 999999}, low=18000, high=26000),
        make("frontier_hard_evidence_stop", "assertion", "hard_evidence_stop", ("defect_evidence",), "A returned device passed identity checks and its defect evidence is being assessed.", {"inspection_stage": "post_return_warehouse", "order_serial": "S-1", "inspection_serial": "S-1", "defect_evidence": "customer_assertion"}, low=70000, high=120000),
        make("frontier_hard_evidence_stop", "verified", "hard_evidence_stop", ("defect_evidence",), "A returned device passed identity checks and its defect evidence is being assessed.", {"inspection_stage": "post_return_warehouse", "order_serial": "S-1", "inspection_serial": "S-1", "defect_evidence": "verified"}, low=70000, high=120000),
    )


def build_unified_panel(seed: int, *, include_operational_extension: bool = False, include_policy_stress_extension: bool = False, include_policy_frontier_extension: bool = False, include_policy_frontier_hard_extension: bool = False) -> tuple[UnifiedRefundCase, ...]:
    core = tuple(UnifiedRefundCase(case, SCENARIO_CATEGORY[case.scenario]) for case in build_marketplace_v24_panel(seed))
    return core + (build_operational_extension_panel(seed) if include_operational_extension else ()) + (build_policy_stress_panel(seed) if include_policy_stress_extension else ()) + (build_policy_frontier_panel(seed) if include_policy_frontier_extension else ()) + (build_policy_frontier_hard_panel(seed) if include_policy_frontier_hard_extension else ())


def resolve_policy(case: UnifiedRefundCase) -> V24Resolution:
    """Return the one resolution admitted by the documented precedence table.

    Category membership is validated at admission time.  The interaction
    resolver is deliberately reused rather than duplicating its arithmetic;
    this eliminates two competing implementations of the same overlay.
    """
    if case.product_category != SCENARIO_CATEGORY[case.interaction.scenario]:
        raise ValueError(f"{case.interaction.scenario} is not admitted for {case.product_category}")
    f, scenario = case.interaction.facts, case.interaction.scenario
    full = round(case.interaction.item_net_price + case.interaction.allocated_tax, 2)
    def out(eligibility: str, remedy: str, workflow: str, amount: float, basis: str, required: tuple[str, ...], payer: str = "none") -> V24Resolution:
        amount = round(amount, 2)
        if workflow == "execute_refund" and amount == 0:
            workflow = "no_mutation"
        return V24Resolution(eligibility, remedy, workflow, amount, "original_payment" if amount > 0 else "none", "execute" if workflow == "execute_refund" and amount > 0 else "none", payer, _public_rule_id(basis), required)
    # New V2.5 semantics are authored here, without changing V2.4's baseline.
    if scenario == "wrong_item_received":
        required = ("sku_evidence_status", "ordered_sku", "received_sku")
        if f["sku_evidence_status"] != "verified":
            return out("unresolved", "none", "request_evidence", 0, "wrong_item_unverified", required)
        if f["ordered_sku"] == f["received_sku"]:
            return out("ineligible", "none", "no_mutation", 0, "wrong_item_match", required)
        return out("eligible", "full_refund", "execute_refund", full, "wrong_item_verified", required, "seller")
    if scenario == "condition_deterioration_after_return":
        required = ("inspection_cause", "original_defect_evidence")
        if f["inspection_cause"] == "buyer_caused":
            return out("unresolved", "none", "seller_review", 0, "buyer_deterioration", required)
        if f["original_defect_evidence"] != "verified":
            return out("unresolved", "none", "request_evidence", 0, "original_defect_unverified", required)
        return out("eligible", "full_refund", "execute_refund", full, "carrier_damage_preserves_remedy", required, "seller")
    if scenario == "evidence_contradiction":
        required = ("customer_evidence", "warehouse_inspection")
        if f["customer_evidence"] != "verified_mismatch" or f["warehouse_inspection"] != "verified_mismatch":
            return out("unresolved", "none", "seller_review", 0, "evidence_conflict", required)
        return out("eligible", "full_refund", "execute_refund", full, "aligned_verified_mismatch", required, "seller")
    if scenario == "policy_identity_override":
        required = ("inspection_stage", "order_serial", "inspection_serial", "defect_evidence")
        if f["inspection_stage"] == "post_return_warehouse" and f["order_serial"] != f["inspection_serial"]:
            return out("unresolved", "none", "identity_review", 0, RULE_IDS["identity_hold"], required)
        if f["defect_evidence"] != "verified":
            return out("unresolved", "none", "request_evidence", 0, RULE_IDS["defect_unverified"], required)
        return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["identity_clear"], required, "seller")
    if scenario == "policy_evidence_conflict":
        required = ("customer_evidence", "warehouse_inspection", "listing_snapshot")
        if f["customer_evidence"] != "verified_mismatch" or f["warehouse_inspection"] != "verified_mismatch":
            return out("unresolved", "none", "seller_review", 0, RULE_IDS["evidence_conflict"], required)
        return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["evidence_clear"], required, "seller")
    if scenario == "policy_seller_fault_override":
        required = ("category_final_sale", "return_reason", "seller_fault_event")
        if f["seller_fault_event"] == "verified_wrong_item":
            return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["seller_fault_override"], required, "seller")
        return out("ineligible", "none", "no_mutation", 0, RULE_IDS["final_sale"], required)
    if scenario == "policy_time_anchor":
        required = ("return_request_day", "return_reason")
        if int(f["return_request_day"]) <= 30:
            return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["time_window"], required, "customer")
        return out("ineligible", "none", "no_mutation", 0, RULE_IDS["time_window"], required)
    if scenario == "policy_perishable_verification":
        required = ("spoilage_evidence",)
        if f["spoilage_evidence"] == "verified":
            return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["evidence_clear"], required, "seller")
        return out("unresolved", "none", "request_evidence", 0, RULE_IDS["perishable_unverified"], required)
    if scenario == "policy_bundle_cap":
        required = ("evidence_status", "paid_component_allocation", "category_cap_rate")
        if f["evidence_status"] != "verified":
            return out("unresolved", "none", "request_evidence", 0, RULE_IDS["defect_unverified"], required)
        amount = min(float(f["paid_component_allocation"]), case.interaction.item_net_price * float(f["category_cap_rate"]))
        return out("eligible", "partial_refund", "execute_refund", amount, RULE_IDS["bundle_cap"], required, "seller")
    if scenario == "policy_return_liability":
        required = ("original_defect_evidence", "inspection_cause")
        if f["inspection_cause"] == "buyer_caused":
            return out("unresolved", "none", "seller_review", 0, RULE_IDS["return_liability"], required)
        if f["original_defect_evidence"] != "verified":
            return out("unresolved", "none", "request_evidence", 0, "original_defect_unverified", required)
        return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["return_liability"], required, "seller")
    if scenario == "policy_payment_hold_precedence":
        required = ("chargeback_state", "defect_evidence")
        if f["chargeback_state"] == "pending":
            return out("unresolved", "none", "payment_review", 0, RULE_IDS["payment_hold"], required)
        if f["defect_evidence"] != "verified":
            return out("unresolved", "none", "request_evidence", 0, RULE_IDS["defect_unverified"], required)
        return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["identity_clear"], required, "seller")
    if scenario == "policy_identity_followup":
        required = ("inspection_stage", "order_serial", "inspection_serial", "defect_evidence")
        if f["inspection_stage"] == "post_return_warehouse" and f["order_serial"] != f["inspection_serial"]:
            return out("unresolved", "none", "identity_review", 0, RULE_IDS["identity_hold"], required)
        if f["defect_evidence"] != "verified":
            return out("unresolved", "none", "request_evidence", 0, RULE_IDS["defect_unverified"], required)
        return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["identity_clear"], required, "seller")
    if scenario == "policy_bundle_boundary":
        required = ("evidence_status", "paid_component_allocation", "category_cap_rate")
        if f["evidence_status"] != "verified":
            return out("unresolved", "none", "request_evidence", 0, RULE_IDS["defect_unverified"], required)
        amount = min(float(f["paid_component_allocation"]), case.interaction.item_net_price * float(f["category_cap_rate"]))
        return out("eligible", "partial_refund", "execute_refund", amount, RULE_IDS["bundle_cap"], required, "seller")
    if scenario == "policy_payment_reconcile":
        required = ("chargeback_state", "prior_refund_state", "defect_evidence")
        if f["chargeback_state"] == "pending" or f["prior_refund_state"] in {"refund_pending", "issued"}:
            return out("unresolved", "none", "payment_review", 0, RULE_IDS["payment_hold"], required)
        if f["defect_evidence"] != "verified":
            return out("unresolved", "none", "request_evidence", 0, RULE_IDS["defect_unverified"], required)
        return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["identity_clear"], required, "seller")
    if scenario == "policy_evidence_inconclusive":
        required = ("customer_evidence", "warehouse_inspection", "listing_snapshot")
        if not (f["customer_evidence"] == "verified_mismatch" and f["warehouse_inspection"] == "verified_mismatch" and f["listing_snapshot"] == "ENT-A"):
            return out("unresolved", "none", "seller_review", 0, RULE_IDS["evidence_conflict"], required)
        return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["evidence_clear"], required, "seller")
    if scenario == "frontier_precedence_ladder":
        required = ("chargeback_state", "inspection_stage", "order_serial", "inspection_serial", "defect_evidence")
        if f["chargeback_state"] == "pending":
            return out("unresolved", "none", "payment_review", 0, RULE_IDS["payment_hold"], required)
        if f["inspection_stage"] == "post_return_warehouse" and f["order_serial"] != f["inspection_serial"]:
            return out("unresolved", "none", "identity_review", 0, RULE_IDS["identity_hold"], required)
        if f["defect_evidence"] != "verified":
            return out("unresolved", "none", "request_evidence", 0, RULE_IDS["defect_unverified"], required)
        return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["identity_clear"], required, "seller")
    if scenario == "frontier_branch_reversal":
        required = ("chargeback_state", "prior_refund_state", "defect_evidence")
        if f["chargeback_state"] == "pending" or f["prior_refund_state"] in {"refund_pending", "issued"}:
            return out("unresolved", "none", "payment_review", 0, RULE_IDS["payment_hold"], required)
        if f["defect_evidence"] != "verified":
            return out("unresolved", "none", "request_evidence", 0, RULE_IDS["defect_unverified"], required)
        return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["identity_clear"], required, "seller")
    if scenario == "frontier_evidence_provenance":
        required = ("customer_evidence", "warehouse_inspection", "listing_snapshot")
        if not (f["customer_evidence"] == "verified_mismatch" and f["warehouse_inspection"] == "verified_mismatch" and f["listing_snapshot"] == "ENT-A"):
            return out("unresolved", "none", "seller_review", 0, RULE_IDS["evidence_conflict"], required)
        return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["evidence_clear"], required, "seller")
    if scenario == "frontier_override_window":
        required = ("category_final_sale", "return_request_day", "return_reason", "seller_fault_event")
        if f["seller_fault_event"] == "verified_wrong_item":
            return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["seller_fault_override"], required, "seller")
        return out("ineligible", "none", "no_mutation", 0, RULE_IDS["final_sale"], required)
    if scenario == "frontier_piecewise_amount":
        required = ("evidence_status", "paid_component_allocation", "category_cap_rate", "allocated_component_tax")
        if f["evidence_status"] != "verified":
            return out("unresolved", "none", "request_evidence", 0, RULE_IDS["defect_unverified"], required)
        cap = round(case.interaction.item_net_price * float(f["category_cap_rate"]), 2)
        amount = round(min(float(f["paid_component_allocation"]), cap) + float(f["allocated_component_tax"]), 2)
        return out("eligible", "partial_refund", "execute_refund", amount, RULE_IDS["bundle_cap"], required, "seller")
    if scenario == "frontier_liability_then_amount":
        required = ("original_defect_evidence", "inspection_cause")
        if f["inspection_cause"] == "buyer_caused":
            return out("unresolved", "none", "seller_review", 0, RULE_IDS["return_liability"], required)
        if f["original_defect_evidence"] != "verified":
            return out("unresolved", "none", "request_evidence", 0, "original_defect_unverified", required)
        return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["return_liability"], required, "seller")
    if scenario == "frontier_hard_authority_flip":
        required = ("customer_evidence", "warehouse_inspection", "serial_registry", "inspection_serial", "order_serial")
        if f["serial_registry"] == "mismatch": return out("unresolved", "none", "identity_review", 0, RULE_IDS["identity_hold"], required)
        if f["customer_evidence"] != "verified_mismatch" or f["warehouse_inspection"] != "verified_mismatch" or f["inspection_serial"] != f["order_serial"]:
            return out("unresolved", "none", "seller_review", 0, RULE_IDS["evidence_conflict"], required)
        return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["identity_clear"], required, "seller")
    if scenario == "frontier_hard_override_liability":
        required = ("category_final_sale", "seller_fault_event", "inspection_cause", "original_defect_evidence")
        if f["inspection_cause"] == "buyer_caused": return out("unresolved", "none", "seller_review", 0, RULE_IDS["return_liability"], required)
        if f["seller_fault_event"] != "verified_wrong_item" or f["original_defect_evidence"] != "verified":
            return out("ineligible" if f["category_final_sale"] else "unresolved", "none", "no_mutation" if f["category_final_sale"] else "request_evidence", 0, RULE_IDS["final_sale"] if f["category_final_sale"] else RULE_IDS["defect_unverified"], required)
        return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["seller_fault_override"], required, "seller")
    if scenario == "frontier_hard_payment_identity":
        required = ("chargeback_state", "inspection_stage", "order_serial", "inspection_serial", "defect_evidence")
        if f["chargeback_state"] == "pending": return out("unresolved", "none", "payment_review", 0, RULE_IDS["payment_hold"], required)
        if f["inspection_stage"] == "post_return_warehouse" and f["order_serial"] != f["inspection_serial"]: return out("unresolved", "none", "identity_review", 0, RULE_IDS["identity_hold"], required)
        if f["defect_evidence"] != "verified": return out("unresolved", "none", "request_evidence", 0, RULE_IDS["defect_unverified"], required)
        return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["identity_clear"], required, "seller")
    if scenario == "frontier_hard_evidence_reversal":
        required = ("customer_evidence", "warehouse_inspection", "listing_snapshot")
        if f["listing_snapshot"] != "ENT-A" or f["customer_evidence"] != "verified_mismatch" or f["warehouse_inspection"] != "verified_mismatch": return out("unresolved", "none", "seller_review", 0, RULE_IDS["evidence_conflict"], required)
        return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["evidence_clear"], required, "seller")
    if scenario == "frontier_hard_piecewise_tax":
        required = ("evidence_status", "paid_component_allocation", "category_cap_rate", "allocated_component_tax")
        if f["evidence_status"] != "verified": return out("unresolved", "none", "request_evidence", 0, RULE_IDS["defect_unverified"], required)
        cap = round(case.interaction.item_net_price * float(f["category_cap_rate"]), 2)
        return out("eligible", "partial_refund", "execute_refund", round(min(float(f["paid_component_allocation"]), cap) + float(f["allocated_component_tax"]), 2), RULE_IDS["bundle_cap"], required, "seller")
    if scenario == "frontier_hard_window_override":
        required = ("category_final_sale", "return_request_day", "return_reason", "seller_fault_event")
        if f["seller_fault_event"] == "verified_wrong_item": return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["seller_fault_override"], required, "seller")
        if f["category_final_sale"] or (f["return_reason"] == "buyer_remorse" and int(f["return_request_day"]) > 30):
            return out("ineligible", "none", "no_mutation", 0, RULE_IDS["final_sale"], required)
        return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["time_window"], required, "customer")
    if scenario == "frontier_hard_refund_reconciliation":
        required = ("defect_evidence", "settled_refund_cents")
        if f["defect_evidence"] != "verified": return out("unresolved", "none", "request_evidence", 0, RULE_IDS["defect_unverified"], required)
        settled = round(int(f["settled_refund_cents"]) / 100, 2)
        residual = round(max(0.0, full - settled), 2)
        if residual == 0: return out("unresolved", "none", "payment_review", 0, RULE_IDS["payment_hold"], required)
        return out("eligible", "full_refund", "execute_refund", residual, RULE_IDS["identity_clear"], required, "seller")
    if scenario == "frontier_hard_evidence_stop":
        required = ("inspection_stage", "order_serial", "inspection_serial", "defect_evidence")
        if f["inspection_stage"] == "post_return_warehouse" and f["order_serial"] != f["inspection_serial"]: return out("unresolved", "none", "identity_review", 0, RULE_IDS["identity_hold"], required)
        if f["defect_evidence"] != "verified": return out("unresolved", "none", "request_evidence", 0, RULE_IDS["defect_unverified"], required)
        return out("eligible", "full_refund", "execute_refund", full, RULE_IDS["identity_clear"], required, "seller")
    if scenario == "intake_identity_branch":
        required = ("defect_evidence", "inspection_stage", "order_serial", "inspection_serial")
        if f["inspection_stage"] == "post_return_warehouse" and f["order_serial"] != f["inspection_serial"]:
            return out("unresolved", "none", "identity_review", 0, "extension_identity_review", required)
        if f["defect_evidence"] != "verified":
            return out("unresolved", "none", "request_evidence", 0, RULE_IDS["defect_unverified"], required)
        return out("eligible", "full_refund", "execute_refund", full, "extension_identity_clear", required, "seller")
    if scenario == "intake_evidence_branch":
        required = ("customer_photo_status", "warehouse_inspection", "listing_snapshot")
        if f["customer_photo_status"] != "verified_mismatch" or f["warehouse_inspection"] != "verified_mismatch":
            return out("unresolved", "none", "seller_review", 0, "extension_evidence_conflict", required)
        return out("eligible", "full_refund", "execute_refund", full, "extension_evidence_aligned", required, "seller")
    if scenario == "payments_proportional_tender":
        required = ("evidence_status", "component_catalog_value", "category_cap_rate")
        if f["evidence_status"] != "verified":
            return out("unresolved", "none", "request_evidence", 0, "extension_component_unverified", required)
        amount = min(float(f["component_catalog_value"]), case.interaction.item_net_price * float(f["category_cap_rate"]))
        return out("eligible", "partial_refund", "execute_refund", amount, "extension_proportional_tender", required)
    if scenario == "payments_idempotency_retry":
        required = ("defect_evidence",)
        return out("eligible", "full_refund", "execute_refund", full, "extension_verified_defect", required, "seller") if f["defect_evidence"] == "verified" else out("unresolved", "none", "request_evidence", 0, "extension_defect_unverified", required)
    if scenario in {"payments_residual_waterfall", "payments_prior_refund_reconciliation", "payments_rail_fallback"}:
        required = ("defect_evidence",)
        return out("eligible", "full_refund", "execute_refund", full, "extension_verified_defect", required, "seller") if f["defect_evidence"] == "verified" else out("unresolved", "none", "request_evidence", 0, "extension_defect_unverified", required)
    if scenario == "payments_three_tender_rounding":
        required = ("evidence_status", "component_catalog_value", "category_cap_rate")
        amount = min(float(f["component_catalog_value"]), case.interaction.item_net_price * float(f["category_cap_rate"]))
        return out("eligible", "partial_refund", "execute_refund", amount, "extension_three_tender_rounding", required) if f["evidence_status"] == "verified" else out("unresolved", "none", "request_evidence", 0, "extension_component_unverified", required)
    # The V2.4 resolver remains the interaction oracle.  V2.5 makes the
    # category path executable by rejecting an overlay outside its documented
    # category domain before the overlay can supply a resolution.
    resolution = resolve_interaction(case.interaction)
    return out(resolution.eligibility, resolution.remedy, resolution.workflow, resolution.amount,
               resolution.policy_basis, resolution.required_fact_ids, resolution.return_shipping_payer)


def _interaction_rule(case: UnifiedRefundCase) -> str:
    s = case.interaction.scenario
    if s == "policy_identity_override": return "Post-return serial mismatch takes precedence over a defect remedy; a matching serial permits the verified-defect rule."
    if s == "policy_evidence_conflict": return "Conflicting verified customer and warehouse evidence routes to seller_review; aligned verified mismatch permits refund."
    if s == "policy_seller_fault_override": return "Final-sale buyer remorse is excluded, except verified seller-fault/wrong-item evidence overrides the exclusion."
    if s == "policy_time_anchor": return "Buyer-remorse apparel is eligible only when return_request_day ≤ 30; carrier_handover_day is not the time anchor."
    if s == "policy_perishable_verification": return "A perishable customer assertion requires evidence review; verified spoilage permits full refund."
    if s == "policy_bundle_cap": return "Verified missing component refund = min(paid_component_allocation, item_net_price × category_cap_rate)."
    if s == "policy_return_liability": return "Buyer-caused post-return deterioration routes to seller_review; carrier damage preserves the verified-defect refund."
    if s == "policy_payment_hold_precedence": return "Pending chargeback has priority and routes to payment_review; otherwise verified defect permits refund."
    if s == "policy_identity_followup": return "Compare serials first; only a matching serial opens the defect-evidence branch. Unverified evidence routes to request_evidence; verified evidence permits refund."
    if s == "policy_bundle_boundary": return "Verified component refund = round(min(paid_component_allocation, item_net_price × category_cap_rate), 2). Multiply before applying the final two-decimal rounding."
    if s == "policy_payment_reconcile": return "Check chargeback first, then prior_refund_state. Pending chargeback, refund_pending or issued prior refund routes to payment_review; otherwise evaluate the verified defect."
    if s == "policy_evidence_inconclusive": return "Refund requires customer_evidence = verified_mismatch, warehouse_inspection = verified_mismatch, and listing_snapshot = ENT-A. Warehouse inconclusive evidence routes to seller_review."
    if s == "frontier_precedence_ladder": return "Check chargeback first, then post-return serial identity, then verified defect. Each higher-priority hold terminates the lower branch."
    if s == "frontier_branch_reversal": return "Check chargeback, then prior refund state, then defect evidence; payment safety routes to review before eligibility."
    if s == "frontier_evidence_provenance": return "Refund requires corroborated customer and warehouse mismatch against the listing; inconclusive warehouse evidence routes to seller_review."
    if s == "frontier_override_window": return "Final-sale buyer remorse after day 30 is excluded; verified seller fault overrides both exclusion and window."
    if s == "frontier_piecewise_amount": return "Amount = round(min(paid_component_allocation, round(item_net_price × category_cap_rate, 2)) + allocated_component_tax, 2)."
    if s == "frontier_liability_then_amount": return "Resolve post-return liability before calculating or executing any refund amount."
    if s == "frontier_hard_authority_flip": return "An authoritative serial-registry mismatch routes to identity_review. With a matching registry, require corroborated customer and warehouse evidence and matching order/inspection serials before refund."
    if s == "frontier_hard_override_liability": return "Buyer-caused deterioration routes to seller_review before a seller-fault refund; otherwise verified seller fault and defect evidence override final-sale exclusion."
    if s == "frontier_hard_payment_identity": return "Resolve pending chargeback, then post-return serial identity, then verified defect evidence, in that order."
    if s == "frontier_hard_evidence_reversal": return "Refund requires customer and warehouse verified mismatch and the authoritative ENT-A listing; otherwise route to seller_review."
    if s == "frontier_hard_piecewise_tax": return "Verified evidence is required; amount = round(min(paid_component_allocation, round(item_net_price × category_cap_rate, 2)) + allocated_component_tax, 2)."
    if s == "frontier_hard_window_override": return "Verified wrong-item seller fault overrides final-sale exclusion and the day-30 return window; otherwise apply those exclusions. identity_risk is not a policy fact for this interaction."
    if s == "frontier_hard_refund_reconciliation": return "Verified defect permits only a positive residual after settled refunds; a zero residual routes to payment_review without mutation."
    if s == "frontier_hard_evidence_stop": return "Post-return serial mismatch routes to identity_review. After identity clears, a customer assertion routes to request_evidence; verified defect receives a full refund."
    if s == "intake_identity_branch":
        return "Identity/inspection facts determine routing before remedy: post-return serial mismatch routes to identity_review; matched verified device receives full refund. Amount metadata and customer notes are irrelevant."
    if s == "intake_evidence_branch":
        return "Compare customer-photo status with warehouse inspection before remedy: a conflict routes to seller_review; aligned verified mismatch receives full refund. Catalog price and delivery comments are irrelevant."
    if s == "payments_proportional_tender":
        return "Verified component claim receives partial_refund = min(component_catalog_value, item_net_price × category_cap_rate). Payments returns to original tenders proportionally using its ledger ticket."
    if s == "payments_idempotency_retry":
        return "Verified defect receives full refund. Payments must use the execution ticket's idempotency state: an already-applied key is a no-op, never a second refund."
    if s == "payments_residual_waterfall":
        return "Verified defect receives full refund. Payments allocates the confirmed amount through visible tender remaining-capacity in stated waterfall order; no tender may exceed capacity."
    if s == "payments_three_tender_rounding":
        return "Verified component claim receives partial refund. Payments allocates it proportionally across three original tenders, rounds non-final tenders to cents, and assigns remaining cents to the final tender."
    if s == "payments_prior_refund_reconciliation":
        return "Verified defect receives full refund. Payments reconciles settled prior refunds and executes only the remaining amount; never refund the same obligation twice."
    if s == "payments_rail_fallback":
        return "Verified defect receives full refund. Payments uses the original rail when open; if and only if it is closed, it uses the named permitted fallback rail."
    if s in {"missing_parts_partial_refund", "multiple_missing_components"}:
        return "Formula: partial_refund = min(component_catalog_value_or_total, item_net_price × category_cap_rate). A verified core component overrides this formula: full_refund = item_net_price + allocated_tax."
    if s == "discounted_bundle_component_value":
        return "Formula: partial_refund = min(paid_component_allocation, item_net_price × category_cap_rate). Never use standalone_catalog_value."
    if s == "carrier_delay_request_date":
        return "Eligibility formula: return_request_day ≤ 30. carrier_handover_day and current day do not change this result."
    if s == "returnless_refund_high_value_exception":
        return "If verified defect AND item_net_price ≤ returnless_threshold AND identity_risk = low: execute full refund without return. Equality qualifies. If identity_risk = high: return_and_inspect, amount = 0, payment_mutation = none."
    if s == "refund_already_issued_chargeback_pending":
        return "If prior_refund_state is refund_pending or issued, OR chargeback_state is pending: eligibility = unresolved; workflow = payment_review; amount = 0; payment_mutation = none."
    if s == "late_defect_identity_conflict":
        return "A verified post-return serial mismatch has priority over the late-defect exception: identity_review, amount = 0. Otherwise a verified defect requested by day 90 receives full refund."
    if s == "category_exclusion_seller_fault_override":
        return "Final-sale buyer-remorse is ineligible. A verified wrong-item or seller-fault event overrides final-sale exclusion and receives full refund."
    if s == "evidence_contradiction":
        return "Refund requires BOTH customer_evidence and warehouse_inspection = verified_mismatch. Any other combination, including aligned verified_match or aligned unverified evidence, routes to seller_review, amount = 0, payment_mutation = none."
    if s == "condition_deterioration_after_return":
        return "Buyer-caused deterioration: seller_review, amount = 0. Carrier damage preserves full refund ONLY when original_defect_evidence = verified; otherwise request_evidence with amount=0."
    if s == "wrong_item_received":
        return "First verify sku_evidence_status. Unverified evidence requires request_evidence. If verified, compare ordered_sku and received_sku: equal IDs are ineligible/no_mutation (R_WRONG_ITEM_MATCH); different IDs receive full refund."
    return "Seller-fault remedies require verified evidence. Without it, request_evidence with amount = 0 and payment_mutation = none."


FACT_DOMAINS = {
    "customer_evidence": ("verified_mismatch", "verified_match", "unverified", "inconclusive", "customer_assertion"),
    "customer_photo_status": ("verified_mismatch", "verified_match", "unverified", "inconclusive", "customer_assertion"),
    "warehouse_inspection": ("verified_mismatch", "verified_match", "unverified", "inconclusive", "customer_assertion"),
    "original_defect_evidence": ("verified", "unverified", "inconclusive", "customer_assertion"),
    "inspection_cause": ("buyer_caused", "carrier_damage"),
    "sku_evidence_status": ("verified", "unverified", "inconclusive", "customer_assertion"),
    "prior_refund_state": ("none", "refund_pending", "issued"),
    "chargeback_state": ("none", "pending"),
}
NONNEGATIVE_FACTS = (
    "paid_component_allocation", "component_catalog_value", "noncore_catalog_total",
    "allocated_component_tax", "returnless_threshold", "settled_refund_cents",
)


def validate_case_domains(case: UnifiedRefundCase) -> None:
    """Public domains, including zero amounts; never hide positive premises."""
    for field, allowed in FACT_DOMAINS.items():
        if field in case.facts and case.facts[field] not in allowed:
            raise ValueError(f"{case.case_id}: invalid fact domain: {field}")
    values = {**case.facts, "item_net_price": case.interaction.item_net_price,
              "allocated_tax": case.interaction.allocated_tax}
    for field in (*NONNEGATIVE_FACTS, "item_net_price", "allocated_tax", "category_cap_rate"):
        if field not in values:
            continue
        value = values[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{case.case_id}: invalid numeric domain: {field}")
        if field == "category_cap_rate" and value > 1:
            raise ValueError(f"{case.case_id}: category_cap_rate must be in [0,1]")
        if field == "settled_refund_cents" and not isinstance(value, int):
            raise ValueError(f"{case.case_id}: settled_refund_cents must be integer cents")
    for field in ("ordered_sku", "received_sku"):
        if field in values and (not isinstance(values[field], str) or not values[field].strip()):
            raise ValueError(f"{case.case_id}: {field} must be a non-empty string")


def validate_resolution_invariants(case: UnifiedRefundCase, resolution: V24Resolution) -> None:
    """Independent safety premises, not comparisons with the branch compiler."""
    f, scenario = case.facts, case.interaction.scenario
    if resolution.amount == 0 and (resolution.payment_mutation != "none" or resolution.refund_method != "none" or resolution.workflow == "execute_refund"):
        raise ValueError(f"{case.case_id}: zero amount must be no-mutation")
    if resolution.amount > 0 and resolution.workflow == "execute_refund":
        if scenario == "wrong_item_received" and (f["sku_evidence_status"] != "verified" or f["ordered_sku"] == f["received_sku"]):
            raise ValueError(f"{case.case_id}: refund requires verified SKU mismatch")
        if scenario in {"evidence_contradiction", "policy_evidence_conflict", "intake_evidence_branch"}:
            left = "customer_photo_status" if scenario == "intake_evidence_branch" else "customer_evidence"
            if f[left] != "verified_mismatch" or f["warehouse_inspection"] != "verified_mismatch":
                raise ValueError(f"{case.case_id}: refund requires both verified mismatches")
        if scenario in {"condition_deterioration_after_return", "policy_return_liability", "frontier_liability_then_amount"} and f["original_defect_evidence"] != "verified":
            raise ValueError(f"{case.case_id}: original defect must be verified")
        if scenario in {"policy_payment_reconcile", "frontier_branch_reversal"} and (f["prior_refund_state"] in {"refund_pending", "issued"} or f["chargeback_state"] == "pending"):
            raise ValueError(f"{case.case_id}: existing payment state blocks mutation")


def render_policy_contract(case: UnifiedRefundCase) -> str:
    """Policy text exposed to the policy seat; it deliberately has no hidden rule."""
    category = CATEGORY_POLICIES[case.product_category]
    graph = policy_fact_dependency_graph(case)
    return "\n".join((
        "REFUND POLICY CONTRACT v2.5",
        f"Design revision: {DESIGN_VERSION} (new campaign only).",
        f"Product category: {category.category}.",
        f"Category base rule: {category.base_rule}",
        f"Category exclusions: {category.exclusions}",
        f"Category amount rule: {category.amount_rule}",
        "Amount formula: full_refund = item_net_price + allocated_tax; where an interaction supplies a partial-refund formula, that interaction formula controls.",
        f"Interaction ID: {case.interaction.scenario}.",
        f"Public financial inputs: item_net_price = {case.interaction.item_net_price:.2f}; allocated_tax = {case.interaction.allocated_tax:.2f}.",
        "Public fact domains: " + json.dumps({k: v for k, v in FACT_DOMAINS.items() if k in case.facts}, sort_keys=True) + "; SKU IDs are non-empty strings and may be equal. Financial inputs and amount facts are finite non-negative numbers (zero allowed); category_cap_rate is in [0,1]; settled_refund_cents is integer cents.",
        "Precedence (first applicable rule wins): the numbered case-local Rule catalogue below is authoritative; it specifies seller-fault overrides and terminal holds. Category text is general context, not an additional fact requirement or a conflicting priority order.",
        "Interaction rule for this case: " + _interaction_rule(case),
        "Rule catalogue: " + _rule_catalogue(case),
        "Fact dependency graph: " + graph + ".",
        "Public branch specification JSON: " + json.dumps(spec_for(case.interaction.scenario).to_dict(), sort_keys=True),
        "Zero-amount normalization (applies after every amount formula): if an execute_refund branch computes amount=0, retain its eligibility, remedy, payer and rule ID but output workflow=no_mutation, refund_method=none, payment_mutation=none. No zero-amount payment is executed.",
        "Canonical outputs: eligibility ∈ {eligible, ineligible, unresolved}; remedy ∈ {full_refund, partial_refund, none}; workflow ∈ {execute_refund, no_mutation, request_evidence, identity_review, seller_review, payment_review, return_and_inspect}; amount is non-negative; refund_method ∈ {original_payment, none}; payment_mutation ∈ {execute, none}; return_shipping_payer ∈ {seller, customer, none}. For any positive amount with workflow=execute_refund, refund_method must be original_payment and payment_mutation must be execute; zero-amount holds/reviews use none. The rule catalogue supplies the liability payer.",
        "policy_basis and reason_code must both be the selected Rule catalogue ID. A terminal precedence route may be submitted without collecting lower-priority facts. Evaluate known AND/OR operands first: a false conjunct or true disjunct can determine a branch. Only request facts still needed to determine the earliest applicable branch or its amount; the graph is NOT an all-fields checklist. An unresolved higher-priority branch cannot be skipped. Do not infer facts from the customer claim. request_evidence is a final workflow, not a substitute for requesting an undisclosed fact. Positive execute_refund uses original_payment/execute; zero holds/reviews use none/none. Amounts use Python-compatible binary float round(x,2), with intermediate rounding only where explicitly shown in the formula.",
    ))


def policy_fact_dependency_graph(case: UnifiedRefundCase) -> str:
    return spec_for(case.interaction.scenario).graph()


def _rule_catalogue(case: UnifiedRefundCase) -> str:
    return spec_for(case.interaction.scenario).catalogue()


def policy_requestable_fact_ids(case: UnifiedRefundCase, revealed: Mapping[str, object]) -> tuple[str, ...]:
    """Public branch obligations; never consult unrevealed case values."""
    return spec_for(case.interaction.scenario).pending(
        revealed, public_inputs(case.interaction.item_net_price, case.interaction.allocated_tax))


def policy_required_fact_ids(case: UnifiedRefundCase, revealed: Mapping[str, object]) -> tuple[str, ...]:
    return policy_requestable_fact_ids(case, revealed)


def validate_catalog(seed: int = 1, *, include_operational_extension: bool = False, include_policy_stress_extension: bool = False, include_policy_frontier_extension: bool = False, include_policy_frontier_hard_extension: bool = False) -> None:
    """Admission checks preventing internal policy conflicts before a run."""
    if len(PRECEDENCE) != len(set(PRECEDENCE)):
        raise ValueError("policy precedence contains duplicate ranks")
    cases = build_unified_panel(seed, include_operational_extension=include_operational_extension, include_policy_stress_extension=include_policy_stress_extension, include_policy_frontier_extension=include_policy_frontier_extension, include_policy_frontier_hard_extension=include_policy_frontier_hard_extension)
    if {case.product_category for case in cases} != set(CATEGORIES):
        raise ValueError("unified panel does not cover every category")
    for case in cases:
        if case.product_category not in CATEGORY_POLICIES:
            raise ValueError(f"unknown category: {case.product_category}")
        resolution = resolve_policy(case)
        if not resolution.required_fact_ids or not set(resolution.required_fact_ids) <= set(case.facts):
            raise ValueError(f"case lacks determinative facts: {case.case_id}")
        contract = render_policy_contract(case)
        if "Canonical outputs:" not in contract or "Precedence" not in contract or "Rule catalogue:" not in contract or "Fact dependency graph:" not in contract:
            raise ValueError(f"policy contract is incomplete: {case.case_id}")


__all__ = [
    "CATEGORY_POLICIES", "CATEGORIES", "FAMILY_VERSION", "PRECEDENCE", "SCENARIO_CATEGORY",
    "UnifiedRefundCase", "build_operational_extension_panel", "build_policy_stress_panel", "build_policy_frontier_panel", "build_policy_frontier_hard_panel", "build_unified_panel", "intake_routing_plan", "payment_ledger", "policy_fact_dependency_graph", "policy_requestable_fact_ids", "policy_required_fact_ids", "render_policy_contract", "resolve_policy", "validate_catalog",
]
