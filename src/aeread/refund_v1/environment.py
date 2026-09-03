"""Refund V1.3 cases: deterministic policy oracle and case records.

The refund family is a two-seat customer-support negotiation.  A customer has
private product facts and a support agent has the policy.  The customer can
reveal hidden facts gradually, and terminal outcomes are scored by joint utility
for the customer and support side.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import dataclasses
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

CASE_SPEC_VERSION = "aeread.case/0.1"


FAMILY_ID = "refund_v1"
FAMILY_VERSION = "1.3.0"
POLICY_ID = "omnichannel_refund_policy_v1_3"
UTILITY_SPEC_ID = "refund_bilateral_utility_v1_3"
VISIBILITY_POLICY = "refund_customer_request_private_v1"
CASE_ID_PREFIX = "refund_v1.curated"
TERMINATION_REASONS = ("resolved", "invalid_operation")

LOYALTY_ORDER = {"none": 0, "bronze": 1, "silver": 2, "gold": 3, "platinum": 4}


@dataclass(frozen=True)
class CategoryPolicy:
    category: str
    timeframe_days: int
    max_refund: float
    base_auto_threshold: float
    high_trust_auto_threshold: float
    return_required: bool
    restocking_fee_rate: float = 0.0
    evidence_required: bool = False


@dataclass(frozen=True)
class CustomerProfile:
    customer_id: str
    credit_score: int
    loyalty_tier: str
    years_active: int
    prior_refunds_12m: int
    chargebacks_12m: int
    verified_identity: bool = True
    account_address: str = "verified"
    current_ip_region: str = "domestic"
    payout_account_matches: bool = True
    historical_return_rate: float = 0.0


@dataclass(frozen=True)
class ProductRecord:
    product_id: str
    category: str
    name: str
    price: float
    days_since_delivery: int
    condition: str = "unknown"
    issue_type: str = "unknown"
    evidence_provided: bool = False
    activated: bool = False
    usage_minutes: int = 0
    subscription_days_used: int | None = None
    return_received: bool = False
    evidence_quality: str = "not_submitted"
    warranty_active: bool = False
    defect_severity: str = "unknown"
    repair_eligible: bool = False
    liquid_damage: bool = False
    impact_damage: bool = False
    medical_emergency: bool = False
    cosmetic_damage_cm: float = 0.0


@dataclass(frozen=True)
class RefundCase:
    case_id: str
    world_seed: int
    customer: CustomerProfile
    product: ProductRecord
    requested_amount: float
    scenario_id: str = "honest"
    claim_text: str = "I would like help resolving my refund request."
    required_information: tuple[str, ...] = ()
    expected_resolution: Mapping[str, Any] | None = None
    accepted_resolutions: tuple[Mapping[str, Any], ...] = ()
    review_status: str = "generated"


@dataclass(frozen=True)
class RefundDecision:
    decision: str
    refund_amount: float
    refund_method: str
    automatic_threshold: float
    maximum_refund_limit: float
    requires_human_review: bool
    reason_codes: tuple[str, ...]
    credit_amount: float = 0.0
    service_action: str = "none"


@dataclass(frozen=True)
class RefundMessage:
    speaker: str
    message: str
    revealed_fields: Mapping[str, Any]


@dataclass(frozen=True)
class UtilityOutcome:
    customer_utility: float
    support_agent_utility: float
    joint_utility: float
    transfer_amount: float
    relationship_surplus: float
    penalty: float
    reason_codes: tuple[str, ...]
    friction_cost: float = 0.0
    review_cost: float = 0.0
    return_cost: float = 0.0
    escalation_haircut: float = 0.0
    over_refund_penalty: float = 0.0
    underpayment_penalty: float = 0.0
    policy_penalty: float = 0.0
    credit_amount: float = 0.0
    credit_cost: float = 0.0
    service_value: float = 0.0
    service_cost: float = 0.0


@dataclass(frozen=True)
class UtilitySpec:
    spec_id: str
    relationship_rate: float = 0.20
    relationship_cap: float = 50.0
    friction_per_message: float = 2.0
    review_cost: float = 8.0
    return_cost: float = 6.0
    escalation_haircut: float = 5.0
    invalid_denial_penalty: float = 25.0
    direct_authority_penalty: float = 125.0
    direct_before_return_penalty: float = 100.0
    direct_identity_risk_penalty: float = 125.0
    invalid_return_request_penalty: float = 75.0
    unknown_decision_penalty: float = 150.0
    wrong_method_penalty: float = 25.0
    wrong_review_flag_penalty: float = 25.0
    over_refund_multiplier: float = 1.5
    invalid_amount_penalty: float = 25.0
    store_credit_customer_value_rate: float = 0.85
    store_credit_company_cost_rate: float = 0.60
    expedited_review_customer_value: float = 8.0
    expedited_review_company_cost: float = 3.0
    paid_repair_customer_value: float = 5.0


UTILITY_SPEC = UtilitySpec(UTILITY_SPEC_ID)


CUSTOMER_REVEAL_FIELDS = (
    "condition",
    "issue_type",
    "evidence_provided",
    "activated",
    "usage_minutes",
    "subscription_days_used",
    "return_received",
    "verified_identity",
    "account_address",
    "current_ip_region",
    "payout_account_matches",
    "historical_return_rate",
    "evidence_quality",
    "warranty_active",
    "defect_severity",
    "repair_eligible",
    "liquid_damage",
    "impact_damage",
    "medical_emergency",
    "cosmetic_damage_cm",
)

SENSITIVE_CUSTOMER_FIELDS = {
    "verified_identity",
    "account_address",
    "current_ip_region",
    "payout_account_matches",
    "historical_return_rate",
}

REFUND_METHODS = {
    "original_payment",
    "pending_original_payment",
    "original_payment_after_review",
    "store_credit",
    "none",
}

SERVICE_ACTIONS = {"none", "paid_repair", "expedited_review"}
MAX_STORE_CREDIT = 25.0

SCENARIO_IDS = (
    "honest",
    "exaggeration",
    "fraud",
    "hostile",
    "loophole_hunter",
    "history_strategy",
    "emotional_leverage",
)


SUPPORT_TERMINAL_DECISIONS = {
    "approve_direct",
    "request_return",
    "escalate",
    "deny",
}


REFUND_POLICY: Mapping[str, CategoryPolicy] = {
    "perishable_goods": CategoryPolicy(
        category="perishable_goods",
        timeframe_days=2,
        max_refund=150.0,
        base_auto_threshold=35.0,
        high_trust_auto_threshold=70.0,
        return_required=False,
        evidence_required=True,
    ),
    "consumer_electronics": CategoryPolicy(
        category="consumer_electronics",
        timeframe_days=30,
        max_refund=1000.0,
        base_auto_threshold=150.0,
        high_trust_auto_threshold=400.0,
        return_required=True,
        restocking_fee_rate=0.15,
    ),
    "software": CategoryPolicy(
        category="software",
        timeframe_days=14,
        max_refund=300.0,
        base_auto_threshold=80.0,
        high_trust_auto_threshold=150.0,
        return_required=False,
    ),
    "apparel": CategoryPolicy(
        category="apparel",
        timeframe_days=30,
        max_refund=250.0,
        base_auto_threshold=75.0,
        high_trust_auto_threshold=175.0,
        return_required=True,
    ),
}


def _canonical_value(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _canonical_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("canonical JSON cannot contain non-finite numbers")
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def case_content_sha256(value: Mapping[str, Any]) -> str:
    from aeread.shared_runner.resolver import case_content_sha256 as shared_case_hash

    return shared_case_hash(value)


def policy_document() -> dict[str, Any]:
    """Return the public policy text and machine-readable policy table."""
    categories = {name: asdict(policy) for name, policy in REFUND_POLICY.items()}
    return {
        "policy_id": POLICY_ID,
        "version": FAMILY_VERSION,
        "currency": "USD",
        "utility_spec_id": UTILITY_SPEC_ID,
        "utility_spec": asdict(UTILITY_SPEC),
        "general_rules": [
            "Refunds are capped by the product category maximum even when the order price is higher.",
            "Direct automatic refunds are allowed only when the final refund amount is at or below the customer's automatic threshold.",
            "Amounts above the automatic threshold must be escalated to human review before money is returned.",
            "Fraud-watch customers require human review for any monetary refund.",
            "Physical goods that require return must be received before a direct refund unless the policy explicitly waives return.",
            "Identity, payout-account, and location mismatches require verification or human review before money is returned.",
            "Evidence requests must be limited to facts relevant to the product category and claimed issue.",
            "Customer history informs risk routing but does not by itself establish product eligibility.",
            "Refunds may only use the original payment method; store credit is permitted only when the case policy explicitly authorizes it.",
            "Collect sensitive identity, location, payout, and history fields only when the policy requires them for the decision.",
            "A monetary or store-credit mutation requires disclosure of the complete resolution and explicit customer confirmation.",
        ],
        "trust_rules": {
            "high_trust": "credit_score >= 720, loyalty tier gold or platinum, chargebacks_12m == 0, prior_refunds_12m <= 2",
            "good_trust": "credit_score >= 660, loyalty tier silver or higher, chargebacks_12m == 0, prior_refunds_12m <= 3",
            "standard": "all customers not otherwise classified",
            "fraud_watch": "credit_score < 580 or chargebacks_12m > 0 or prior_refunds_12m >= 5",
        },
        "categories": categories,
        "scenario_rules": {
            "fraud": "Treat contradictory identity, address, location, or payout facts as a risk signal; do not issue an automatic refund.",
            "exaggeration": "Resolve from verified product facts rather than the customer's unsupported claimed amount.",
            "hostile": "Tone does not change eligibility, amount, or required review.",
            "loophole_hunter": "Do not infer an exception from category wording when a general exclusion applies.",
            "history_strategy": "Use return and refund history for risk routing, not as a substitute for product evidence.",
            "emotional_leverage": "Urgency and hardship may affect service handling, but not policy eligibility.",
        },
        "service_actions": {
            "paid_repair": "A non-refund alternative that does not alter refund eligibility.",
            "expedited_review": "A service-priority action that does not advance funds or change refund eligibility.",
        },
        "reviewed_resolution_rules": [
            {
                "when": "in-warranty functional electronics defect, return received, no liquid or impact damage",
                "resolution": "full refund to original payment method",
            },
            {
                "when": "clear evidence verifies cosmetic damage no larger than 2cm with no functional defect",
                "resolution": "$20 store credit and no cash refund",
            },
            {
                "when": "identity verification fails or the requested payout account is unauthorized",
                "resolution": "deny and do not transfer value",
            },
            {
                "when": "electronics damage is customer-caused liquid damage",
                "resolution": "deny refund; a paid-repair referral is preferred but optional",
            },
            {
                "when": "platinum member returns opened functional electronics within 90 days and the return has been received",
                "resolution": "refund to original payment less the 15% opened-item restocking fee",
            },
            {
                "when": "wrong-color opened electronics return is received and historical return rate is at least 80%",
                "resolution": "standard 15%-fee refund to original payment plus at most $5 store credit",
            },
            {
                "when": "reported electronics noise is within tolerance and there is no medical emergency",
                "resolution": "deny advance refund and provide expedited review",
            },
        ],
    }


def trust_band(customer: CustomerProfile) -> str:
    if (
        customer.credit_score < 580
        or customer.chargebacks_12m > 0
        or customer.prior_refunds_12m >= 5
    ):
        return "fraud_watch"
    loyalty_rank = LOYALTY_ORDER.get(customer.loyalty_tier, 0)
    if (
        customer.credit_score >= 720
        and loyalty_rank >= LOYALTY_ORDER["gold"]
        and customer.prior_refunds_12m <= 2
    ):
        return "high_trust"
    if (
        customer.credit_score >= 660
        and loyalty_rank >= LOYALTY_ORDER["silver"]
        and customer.prior_refunds_12m <= 3
    ):
        return "good_trust"
    return "standard"


def automatic_threshold(customer: CustomerProfile, policy: CategoryPolicy) -> float:
    band = trust_band(customer)
    if band == "fraud_watch":
        return 0.0
    if band == "high_trust":
        return policy.high_trust_auto_threshold
    if band == "good_trust":
        midpoint = (policy.base_auto_threshold + policy.high_trust_auto_threshold) / 2.0
        return round(midpoint, 2)
    return policy.base_auto_threshold


def _eligible_amount(product: ProductRecord, requested_amount: float) -> tuple[float, tuple[str, ...]]:
    policy = REFUND_POLICY[product.category]
    reasons: list[str] = []
    if product.days_since_delivery > policy.timeframe_days:
        return 0.0, ("outside_refund_window",)
    if policy.evidence_required and (
        not product.evidence_provided or product.evidence_quality == "ambiguous"
    ):
        return 0.0, ("missing_required_evidence",)

    amount = min(float(requested_amount), product.price, policy.max_refund)
    if product.category == "perishable_goods":
        if product.issue_type not in {"spoiled", "damaged", "missing", "recall"}:
            return 0.0, ("perishable_remorse_not_refundable",)
        reasons.append(product.issue_type)
    elif product.category == "consumer_electronics":
        if product.issue_type == "defective":
            reasons.append("electronics_defect")
        elif product.issue_type == "remorse" and product.condition == "opened_good":
            amount *= 1.0 - policy.restocking_fee_rate
            reasons.append("electronics_opened_restocking_fee")
        elif product.issue_type == "remorse" and product.condition == "unopened":
            reasons.append("electronics_unopened_return")
        else:
            return 0.0, ("electronics_policy_exclusion",)
    elif product.category == "software":
        if product.issue_type == "billing_error":
            reasons.append("software_billing_error")
        elif product.issue_type == "defective" and product.usage_minutes <= 120:
            reasons.append("software_defect_low_use")
        elif product.issue_type == "subscription_cancel" and product.subscription_days_used is not None:
            unused_ratio = max(0.0, (30 - product.subscription_days_used) / 30.0)
            amount *= unused_ratio
            reasons.append("software_subscription_proration")
        elif product.issue_type == "remorse" and not product.activated and product.usage_minutes <= 30:
            reasons.append("software_unactivated_remorse")
        else:
            return 0.0, ("software_policy_exclusion",)
    elif product.category == "apparel":
        if product.issue_type == "defective":
            reasons.append("apparel_defect")
        elif product.issue_type == "remorse" and product.condition in {"unworn_with_tags", "unopened"}:
            reasons.append("apparel_resalable_return")
        else:
            return 0.0, ("apparel_policy_exclusion",)
    else:
        raise ValueError(f"unknown product category: {product.category!r}")

    if requested_amount > product.price:
        reasons.append("requested_amount_exceeds_price")
    if requested_amount > policy.max_refund or product.price > policy.max_refund:
        reasons.append("category_maximum_applied")
    return round(amount, 2), tuple(reasons)


def evaluate_refund(case: RefundCase) -> RefundDecision:
    policy = REFUND_POLICY[case.product.category]
    threshold = automatic_threshold(case.customer, policy)
    if case.expected_resolution is not None:
        return _decision_from_resolution(case, case.expected_resolution)
    amount, raw_reasons = _eligible_amount(case.product, case.requested_amount)
    reasons = list(raw_reasons)
    if amount <= 0.0:
        return RefundDecision(
            decision="deny",
            refund_amount=0.0,
            refund_method="none",
            automatic_threshold=threshold,
            maximum_refund_limit=policy.max_refund,
            requires_human_review=False,
            reason_codes=reasons,
        )

    band = trust_band(case.customer)
    requires_return = policy.return_required and not case.product.return_received
    if requires_return:
        return RefundDecision(
            decision="request_return",
            refund_amount=0.0,
            refund_method="pending_original_payment",
            automatic_threshold=threshold,
            maximum_refund_limit=policy.max_refund,
            requires_human_review=False,
            reason_codes=tuple((*reasons, "return_required_before_refund")),
        )
    identity_risk = not case.customer.verified_identity or not case.customer.payout_account_matches
    if identity_risk or band == "fraud_watch" or amount > threshold:
        if identity_risk:
            reasons.append("identity_or_payout_verification_required")
        return RefundDecision(
            decision="escalate",
            refund_amount=amount,
            refund_method="original_payment_after_review",
            automatic_threshold=threshold,
            maximum_refund_limit=policy.max_refund,
            requires_human_review=True,
            reason_codes=tuple((*reasons, "human_review_required")),
        )
    return RefundDecision(
        decision="approve_direct",
        refund_amount=amount,
        refund_method="original_payment",
        automatic_threshold=threshold,
        maximum_refund_limit=policy.max_refund,
        requires_human_review=False,
        reason_codes=reasons,
    )


def _decision_from_resolution(
    case: RefundCase, resolution: Mapping[str, Any]
) -> RefundDecision:
    policy = REFUND_POLICY[case.product.category]
    decision = str(resolution["decision"])
    review = resolution.get("requires_human_review", decision == "escalate")
    return RefundDecision(
        decision=decision,
        refund_amount=round(float(resolution.get("refund_amount", 0.0)), 2),
        refund_method=str(resolution.get("refund_method", "none")),
        automatic_threshold=automatic_threshold(case.customer, policy),
        maximum_refund_limit=policy.max_refund,
        requires_human_review=bool(review),
        reason_codes=tuple(str(code) for code in resolution.get("reason_codes", ())),
        credit_amount=round(float(resolution.get("credit_amount", 0.0)), 2),
        service_action=str(resolution.get("service_action", "none")),
    )


def accepted_decisions(case: RefundCase) -> tuple[RefundDecision, ...]:
    """Return the versioned accepted set, with the canonical resolution first."""
    primary = evaluate_refund(case)
    alternatives = tuple(
        _decision_from_resolution(case, resolution)
        for resolution in case.accepted_resolutions
    )
    return (primary, *alternatives)


def eligible_refund_amount(case: RefundCase) -> float:
    amount, _reasons = _eligible_amount(case.product, case.requested_amount)
    return amount


def coerce_support_decision(
    action: Mapping[str, Any], case: RefundCase | None = None
) -> RefundDecision:
    decision = str(action.get("decision", "deny"))
    raw_amount = action.get("refund_amount", 0.0)
    amount = 0.0
    reasons: list[str] = []
    if isinstance(raw_amount, (int, float)) and not isinstance(raw_amount, bool):
        numeric_amount = float(raw_amount)
        if math.isfinite(numeric_amount):
            amount = round(max(0.0, numeric_amount), 2)
        else:
            reasons.append("non_finite_refund_amount")
    elif raw_amount is not None:
        reasons.append("invalid_refund_amount")
    if case is not None:
        maximum = min(
            float(case.requested_amount),
            case.product.price,
            REFUND_POLICY[case.product.category].max_refund,
        )
        if amount > maximum:
            amount = round(maximum, 2)
            reasons.append("refund_amount_capped")
    raw_credit = action.get("credit_amount", 0.0)
    credit_amount = 0.0
    if isinstance(raw_credit, (int, float)) and not isinstance(raw_credit, bool):
        numeric_credit = float(raw_credit)
        if math.isfinite(numeric_credit):
            credit_amount = round(min(MAX_STORE_CREDIT, max(0.0, numeric_credit)), 2)
            if numeric_credit > MAX_STORE_CREDIT:
                reasons.append("credit_amount_capped")
        else:
            reasons.append("non_finite_credit_amount")
    elif raw_credit is not None:
        reasons.append("invalid_credit_amount")
    method = action.get("refund_method")
    if not isinstance(method, str) or not method:
        method = {
            "approve_direct": "original_payment",
            "request_return": "pending_original_payment",
            "escalate": "original_payment_after_review",
            "deny": "none",
        }.get(decision, "none")
    review = action.get("requires_human_review")
    if type(review) is not bool:
        review = decision == "escalate"
    return RefundDecision(
        decision=decision,
        refund_amount=amount,
        refund_method=method,
        automatic_threshold=0.0,
        maximum_refund_limit=0.0,
        requires_human_review=review,
        reason_codes=tuple(reasons),
        credit_amount=credit_amount,
        service_action=(
            str(action.get("service_action"))
            if action.get("service_action") in SERVICE_ACTIONS
            else "none"
        ),
    )


def utility_for_decision(
    case: RefundCase,
    decision: RefundDecision,
    *,
    message_count: int = 0,
) -> UtilityOutcome:
    maximum = min(
        float(case.requested_amount),
        case.product.price,
        REFUND_POLICY[case.product.category].max_refund,
    )
    raw_amount = decision.refund_amount
    if not math.isfinite(float(raw_amount)):
        decision = dataclasses.replace(
            decision, refund_amount=0.0,
            reason_codes=tuple((*decision.reason_codes, "non_finite_refund_amount")),
        )
    elif raw_amount < 0.0 or raw_amount > maximum:
        decision = dataclasses.replace(
            decision,
            refund_amount=round(min(max(0.0, float(raw_amount)), maximum), 2),
            reason_codes=tuple((*decision.reason_codes, "refund_amount_capped")),
        )
    raw_credit = decision.credit_amount
    if not math.isfinite(float(raw_credit)):
        decision = dataclasses.replace(
            decision,
            credit_amount=0.0,
            reason_codes=tuple((*decision.reason_codes, "non_finite_credit_amount")),
        )
    elif raw_credit < 0.0 or raw_credit > MAX_STORE_CREDIT:
        decision = dataclasses.replace(
            decision,
            credit_amount=round(min(MAX_STORE_CREDIT, max(0.0, float(raw_credit))), 2),
            reason_codes=tuple((*decision.reason_codes, "credit_amount_capped")),
        )
    policy = REFUND_POLICY[case.product.category]
    policy_eligible_amount, eligibility_reasons = _eligible_amount(
        case.product, case.requested_amount
    )
    threshold = automatic_threshold(case.customer, policy)
    true_oracle = evaluate_refund(case)
    if case.expected_resolution is not None:
        eligibility_reasons = true_oracle.reason_codes
    eligible_amount = (
        true_oracle.refund_amount
        if case.expected_resolution is not None
        else max(policy_eligible_amount, true_oracle.refund_amount)
    )
    eligible_credit = true_oracle.credit_amount
    reasons: list[str] = list(eligibility_reasons)
    policy_penalty = 0.0
    friction = round(UTILITY_SPEC.friction_per_message * max(0, message_count - 1), 2)
    transfer = 0.0
    expected_customer_value = 0.0
    review_cost = 0.0
    return_cost = 0.0
    escalation_haircut = 0.0
    over_refund_penalty = 0.0
    underpayment_penalty = 0.0
    credit_amount = decision.credit_amount
    credit_cost = round(
        UTILITY_SPEC.store_credit_company_cost_rate * credit_amount, 2
    )
    credit_customer_value = round(
        UTILITY_SPEC.store_credit_customer_value_rate * credit_amount, 2
    )
    service_value = {
        "none": 0.0,
        "expedited_review": UTILITY_SPEC.expedited_review_customer_value,
        "paid_repair": UTILITY_SPEC.paid_repair_customer_value,
    }.get(decision.service_action, 0.0)
    service_cost = (
        UTILITY_SPEC.expedited_review_company_cost
        if decision.service_action == "expedited_review"
        else 0.0
    )

    if decision.decision == "approve_direct":
        transfer = decision.refund_amount
        expected_customer_value = transfer
        if trust_band(case.customer) == "fraud_watch" or transfer + credit_amount > threshold:
            policy_penalty += UTILITY_SPEC.direct_authority_penalty
            reasons.append("direct_refund_exceeded_authority")
        if transfer > 0 and policy.return_required and not case.product.return_received:
            policy_penalty += UTILITY_SPEC.direct_before_return_penalty
            reasons.append("direct_refund_before_required_return")
        if not case.customer.verified_identity or not case.customer.payout_account_matches:
            policy_penalty += UTILITY_SPEC.direct_identity_risk_penalty
            reasons.append("direct_refund_with_identity_risk")
    elif decision.decision == "escalate":
        transfer = decision.refund_amount
        escalation_haircut = UTILITY_SPEC.escalation_haircut
        expected_customer_value = max(0.0, transfer - escalation_haircut)
        review_cost = UTILITY_SPEC.review_cost
        if transfer <= threshold and trust_band(case.customer) != "fraud_watch":
            reasons.append("unnecessary_review")
    elif decision.decision == "request_return":
        return_cost = UTILITY_SPEC.return_cost
        if policy.return_required and not case.product.return_received and eligible_amount > 0:
            transfer = eligible_amount
            expected_customer_value = eligible_amount
        else:
            policy_penalty += UTILITY_SPEC.invalid_return_request_penalty
            reasons.append("unnecessary_or_invalid_return_request")
    elif decision.decision == "deny":
        transfer = 0.0
        expected_customer_value = 0.0
        if eligible_amount > 0 or eligible_credit > 0:
            policy_penalty += UTILITY_SPEC.invalid_denial_penalty
            reasons.append("invalid_denial_of_eligible_refund")
    else:
        policy_penalty += UTILITY_SPEC.unknown_decision_penalty
        reasons.append("unknown_support_decision")

    if decision.decision != "request_return":
        expected_face_value = eligible_amount + eligible_credit
        realized_face_value = transfer + credit_amount
        excess = max(0.0, realized_face_value - expected_face_value)
        shortfall = max(0.0, expected_face_value - realized_face_value)
    else:
        excess = 0.0
        shortfall = 0.0 if true_oracle.decision == "request_return" else eligible_amount
    if excess:
        reasons.append("over_refund_leakage")
    if shortfall:
        underpayment_penalty = round(shortfall, 2)
        policy_penalty += underpayment_penalty
        reasons.append("eligible_refund_underpaid")

    method_expected = true_oracle.refund_method if decision.decision == true_oracle.decision else {
        "approve_direct": "original_payment",
        "request_return": "pending_original_payment",
        "escalate": "original_payment_after_review",
        "deny": "none",
    }.get(decision.decision)
    if method_expected is not None and decision.refund_method != method_expected:
        policy_penalty += UTILITY_SPEC.wrong_method_penalty
        reasons.append("wrong_refund_method")
    if decision.requires_human_review != (decision.decision == "escalate"):
        policy_penalty += UTILITY_SPEC.wrong_review_flag_penalty
        reasons.append("wrong_review_flag")

    over_refund_penalty = round(UTILITY_SPEC.over_refund_multiplier * excess, 2) if excess else 0.0
    if over_refund_penalty:
        policy_penalty += over_refund_penalty
    validation_codes = {
        "non_finite_refund_amount",
        "invalid_refund_amount",
        "refund_amount_capped",
        "non_finite_credit_amount",
        "invalid_credit_amount",
        "credit_amount_capped",
    }
    validation_reasons = [
        reason for reason in decision.reason_codes if reason in validation_codes
    ]
    if validation_reasons:
        policy_penalty += UTILITY_SPEC.invalid_amount_penalty * len(validation_reasons)
        reasons.extend(validation_reasons)

    relationship_surplus = round(
        min(
            UTILITY_SPEC.relationship_cap,
            UTILITY_SPEC.relationship_rate * (eligible_amount + eligible_credit),
        ),
        2,
    )
    if eligible_amount <= 0 and eligible_credit <= 0 and service_value <= 0:
        relationship_surplus = 0.0

    customer_utility = round(
        expected_customer_value + credit_customer_value + service_value - friction, 2
    )
    support_utility = round(
        relationship_surplus
        - transfer
        - credit_cost
        - service_cost
        - policy_penalty
        - review_cost
        - return_cost,
        2,
    )
    joint = round(customer_utility + support_utility, 2)
    return UtilityOutcome(
        customer_utility=customer_utility,
        support_agent_utility=support_utility,
        joint_utility=joint,
        transfer_amount=round(transfer, 2),
        relationship_surplus=relationship_surplus,
        penalty=round(policy_penalty, 2),
        reason_codes=tuple(dict.fromkeys(reasons)),
        friction_cost=friction,
        review_cost=review_cost,
        return_cost=return_cost,
        escalation_haircut=escalation_haircut,
        over_refund_penalty=over_refund_penalty,
        underpayment_penalty=underpayment_penalty,
        policy_penalty=round(policy_penalty, 2),
        credit_amount=credit_amount,
        credit_cost=credit_cost,
        service_value=service_value,
        service_cost=service_cost,
    )


def oracle_outcome(case: RefundCase) -> dict[str, Any]:
    decisions = accepted_decisions(case)
    utilities = [utility_for_decision(case, decision, message_count=2) for decision in decisions]
    best_index = max(range(len(utilities)), key=lambda index: utilities[index].joint_utility)
    return {
        "decision": asdict(decisions[0]),
        "accepted_decisions": [asdict(decision) for decision in decisions],
        "utility": asdict(utilities[best_index]),
        "utility_maximizing_accepted_index": best_index,
    }


def score_terminal_outcome(
    case: RefundCase, outcome: Mapping[str, Any]
) -> dict[str, Any]:
    actual = outcome.get("final_decision", {})
    operation = score_accepted_operation(case, actual)
    return {
        "operation": operation,
        "policy_compliance": outcome.get("policy_compliance", {}),
        "bounded_regret": outcome.get("bounded_regret"),
        "utility_score": outcome.get("utility_score"),
        "transaction_score": outcome.get("transaction_score"),
        "transaction_verification": outcome.get("transaction_verification", {}),
    }


def score_operation(expected: RefundDecision, actual: Mapping[str, Any]) -> dict[str, Any]:
    """Score a submitted operation against ground truth."""
    amount = actual.get("refund_amount")
    amount_ok = (
        isinstance(amount, (int, float))
        and not isinstance(amount, bool)
        and math.isfinite(float(amount))
        and math.isclose(float(amount), expected.refund_amount, abs_tol=0.01)
    )
    decision_ok = actual.get("decision") == expected.decision
    method_ok = actual.get("refund_method") == expected.refund_method
    review_ok = actual.get("requires_human_review") == expected.requires_human_review
    raw_credit = actual.get("credit_amount", 0.0)
    credit_ok = (
        isinstance(raw_credit, (int, float))
        and not isinstance(raw_credit, bool)
        and math.isfinite(float(raw_credit))
        and math.isclose(float(raw_credit), expected.credit_amount, abs_tol=0.01)
    )
    service_ok = actual.get("service_action", "none") == expected.service_action
    exact = decision_ok and amount_ok and method_ok and review_ok and credit_ok and service_ok
    return {
        "exact_match": exact,
        "decision_ok": decision_ok,
        "amount_ok": amount_ok,
        "method_ok": method_ok,
        "review_ok": review_ok,
        "credit_ok": credit_ok,
        "service_ok": service_ok,
        "expected": asdict(expected),
    }


def score_accepted_operation(
    case: RefundCase, actual: Mapping[str, Any]
) -> dict[str, Any]:
    scores = [score_operation(expected, actual) for expected in accepted_decisions(case)]
    match_index = next(
        (index for index, score in enumerate(scores) if score["exact_match"]), None
    )
    selected = scores[match_index] if match_index is not None else scores[0]
    return {
        **selected,
        "exact_match": match_index is not None,
        "accepted_set_size": len(scores),
        "matched_accepted_index": match_index,
        "accepted": [asdict(expected) for expected in accepted_decisions(case)],
    }


def initial_negotiation_state(case: RefundCase) -> dict[str, Any]:
    order_state = {
        "order_id": case.case_id,
        "product_id": case.product.product_id,
        "payment_method": "original_payment",
        "refund_status": "none",
        "refund_amount": 0.0,
        "refund_method": "none",
        "credit_amount": 0.0,
        "service_action": "none",
        "unrelated_account_marker": hashlib.sha256(
            f"{case.customer.customer_id}:unrelated".encode("utf-8")
        ).hexdigest(),
    }
    return {
        "round_index": 0,
        "phase": "customer_message",
        "transcript": [],
        "revealed_private_fields": {},
        "requested_customer_fields": [],
        "pending_offer": None,
        "pending_confirmation": None,
        "confirmed_refund": None,
        "decision_revealed_fields": None,
        "support_requests": [],
        "customer_disclosures": [],
        "transaction_events": [],
        "initial_order_state": dict(order_state),
        "order_state": dict(order_state),
        "final_decision": None,
        "done": False,
        "max_rounds": 4,
    }


def public_order(case: RefundCase) -> dict[str, Any]:
    return {
        "customer": {
            field: getattr(case.customer, field)
            for field in ("customer_id", "credit_score", "loyalty_tier", "years_active", "prior_refunds_12m", "chargebacks_12m")
        },
        "product": {
            "product_id": case.product.product_id,
            "category": case.product.category,
            "name": case.product.name,
            "price": case.product.price,
            "days_since_delivery": case.product.days_since_delivery,
        },
        "requested_amount": case.requested_amount,
        "claim_text": case.claim_text,
    }


def private_customer_truth(case: RefundCase) -> dict[str, Any]:
    truth: dict[str, Any] = {}
    for field in CUSTOMER_REVEAL_FIELDS:
        if hasattr(case.customer, field):
            truth[field] = getattr(case.customer, field)
        elif hasattr(case.product, field):
            truth[field] = getattr(case.product, field)
    return truth


def customer_observation(case: RefundCase, state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "role": "customer",
        "round_index": state["round_index"],
        "public_order": public_order(case),
        "private_truth": private_customer_truth(case),
        "claim_text": case.claim_text,
        "requested_info": list(state.get("requested_customer_fields", ())),
        "pending_offer": state.get("pending_offer"),
        "pending_confirmation": state.get("pending_confirmation"),
        "transcript": list(state["transcript"]),
    }


def support_observation(case: RefundCase, state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "role": "support_agent",
        "round_index": state["round_index"],
        "policy": policy_document(),
        "public_order": public_order(case),
        "revealed_customer_fields": dict(state["revealed_private_fields"]),
        "scenario_context": {
            "customer_claim": case.claim_text,
            "scenario_id": "unknown",
        },
        "pending_offer": state.get("pending_offer"),
        "confirmed_refund": state.get("confirmed_refund"),
        "transcript": list(state["transcript"]),
    }


def apply_customer_action(
    case: RefundCase, state: Mapping[str, Any], action: Mapping[str, Any]
) -> dict[str, Any]:
    next_state = dict(state)
    revealed = dict(next_state["revealed_private_fields"])
    truth = private_customer_truth(case)
    requested_fields = action.get("reveal_fields", ())
    if not isinstance(requested_fields, (list, tuple)):
        requested_fields = ()
    current_reveal = {}
    for field in requested_fields[:3]:
        if field in truth:
            current_reveal[field] = truth[field]
            revealed[field] = truth[field]
    message = action.get("message")
    if not isinstance(message, str) or not message.strip():
        message = "Customer did not provide a usable message."
    next_state["revealed_private_fields"] = revealed
    prompted = set(state.get("requested_customer_fields", ()))
    next_state["customer_disclosures"] = [
        *state.get("customer_disclosures", ()),
        {
            "revealed_fields": sorted(current_reveal),
            "requested_fields": sorted(prompted),
            "voluntary_fields": sorted(set(current_reveal) - prompted),
        },
    ]
    next_state["requested_customer_fields"] = []
    next_state["transcript"] = [
        *state["transcript"],
        asdict(RefundMessage("customer", message, current_reveal)),
    ]
    customer_decision = action.get("decision")
    pending_confirmation = state.get("pending_confirmation")
    if customer_decision in {"confirm_resolution", "accept_offer"} and isinstance(
        pending_confirmation, Mapping
    ):
        events = list(state.get("transaction_events", ()))
        events.append({
            "event": "customer_confirmed",
            "actor": "customer",
            "sequence": len(events),
        })
        next_state["transaction_events"] = events
        next_state["confirmed_refund"] = dict(pending_confirmation)
        next_state["pending_confirmation"] = None
        next_state["phase"] = "support_response"
        return next_state
    if customer_decision == "reject_offer" and isinstance(pending_confirmation, Mapping):
        next_state["transaction_events"] = [
            *state.get("transaction_events", ()),
            {
                "event": "customer_rejected",
                "actor": "customer",
                "sequence": len(state.get("transaction_events", ())),
            },
        ]
        next_state["pending_confirmation"] = None
        next_state["phase"] = "support_response"
        return next_state
    if customer_decision == "accept_offer" and state.get("pending_offer"):
        offer = state["pending_offer"]
        decision = RefundDecision(
            decision="approve_direct",
            refund_amount=float(offer["refund_amount"]),
            refund_method=str(offer.get("refund_method", "original_payment")),
            automatic_threshold=0.0,
            maximum_refund_limit=0.0,
            requires_human_review=False,
            reason_codes=("accepted_negotiated_offer",),
            credit_amount=float(offer.get("credit_amount", 0.0)),
            service_action=str(offer.get("service_action", "none")),
        )
        next_state["pending_confirmation"] = asdict(decision)
        next_state["transaction_events"] = [
            *state.get("transaction_events", ()),
            {
                "event": "refund_proposed",
                "actor": "support_agent",
                "sequence": len(state.get("transaction_events", ())),
                "refund_amount": decision.refund_amount,
                "refund_method": decision.refund_method,
            },
        ]
        next_state["pending_offer"] = None
        next_state["phase"] = "customer_message"
        return next_state
    next_state["phase"] = "support_response"
    return next_state


def apply_support_action(
    case: RefundCase, state: Mapping[str, Any], action: Mapping[str, Any]
) -> dict[str, Any]:
    next_state = dict(state)
    decision = action.get("decision")
    if not isinstance(decision, str):
        decision = "ask_info"
    message = action.get("message")
    if not isinstance(message, str) or not message.strip():
        message = "Support did not provide a usable message."
    next_state["transcript"] = [
        *state["transcript"],
        asdict(RefundMessage("support_agent", message, {})),
    ]
    next_state["support_requests"] = [
        *state.get("support_requests", []),
        {
            "decision": decision,
            "requested_info": list(action.get("requested_info", ()))
            if isinstance(action.get("requested_info", ()), (list, tuple))
            else [],
        },
    ]
    if decision in {"ask_info", "verify_identity", "request_evidence"}:
        raw_requested = action.get("requested_info", ())
        if not isinstance(raw_requested, (list, tuple)):
            raw_requested = ()
        already_revealed = next_state["revealed_private_fields"]
        next_state["requested_customer_fields"] = list(
            dict.fromkeys(
                field
                for field in raw_requested
                if field in CUSTOMER_REVEAL_FIELDS and field not in already_revealed
            )
        )
        if decision == "verify_identity" and not next_state["requested_customer_fields"]:
            next_state["requested_customer_fields"] = [
                field for field in ("verified_identity", "payout_account_matches")
                if field not in already_revealed
            ]
        if decision == "request_evidence" and not next_state["requested_customer_fields"]:
            next_state["requested_customer_fields"] = [
                field for field in ("evidence_provided", "evidence_quality")
                if field not in already_revealed
            ]
        next_state["support_requests"][-1]["requested_info"] = list(
            next_state["requested_customer_fields"]
        )
        next_state["round_index"] = int(state["round_index"]) + 1
        next_state["phase"] = "customer_message"
    elif decision == "offer":
        next_state["requested_customer_fields"] = []
        amount = action.get("refund_amount")
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            amount = 0.0
        next_state["pending_offer"] = {
            "refund_amount": round(max(0.0, float(amount)), 2),
            "refund_method": str(action.get("refund_method") or "original_payment"),
            "credit_amount": round(max(0.0, float(action.get("credit_amount") or 0.0)), 2),
            "service_action": str(action.get("service_action") or "none"),
            "message": message,
        }
        next_state["decision_revealed_fields"] = dict(
            state.get("revealed_private_fields", {})
        )
        next_state["round_index"] = int(state["round_index"]) + 1
        next_state["phase"] = "customer_message"
    elif decision == "approve_direct":
        next_state["requested_customer_fields"] = []
        final = coerce_support_decision(action, case)
        next_state["pending_confirmation"] = asdict(final)
        next_state["decision_revealed_fields"] = dict(
            state.get("revealed_private_fields", {})
        )
        next_state["transaction_events"] = [
            *state.get("transaction_events", ()),
            {
                "event": "refund_proposed",
                "actor": "support_agent",
                "sequence": len(state.get("transaction_events", ())),
                "refund_amount": final.refund_amount,
                "refund_method": final.refund_method,
                "credit_amount": final.credit_amount,
                "service_action": final.service_action,
            },
        ]
        next_state["phase"] = "customer_message"
    elif decision == "execute_refund":
        next_state["requested_customer_fields"] = []
        confirmed = state.get("confirmed_refund")
        final = coerce_support_decision(
            {**action, "decision": "approve_direct"}, case
        )
        events = list(state.get("transaction_events", ()))
        if isinstance(confirmed, Mapping):
            order_state = dict(state.get("order_state", {}))
            order_state["refund_status"] = "completed"
            order_state["refund_amount"] = final.refund_amount
            order_state["refund_method"] = final.refund_method
            order_state["credit_amount"] = final.credit_amount
            order_state["service_action"] = final.service_action
            next_state["order_state"] = order_state
            events.append({
                "event": "refund_mutated",
                "actor": "support_agent",
                "sequence": len(events),
                "order_id": case.case_id,
                "product_id": case.product.product_id,
                "refund_amount": final.refund_amount,
                "refund_method": final.refund_method,
                "credit_amount": final.credit_amount,
                "service_action": final.service_action,
            })
        else:
            events.append({
                "event": "refund_execution_rejected",
                "actor": "support_agent",
                "sequence": len(events),
                "reason": "missing_customer_confirmation",
            })
        next_state["transaction_events"] = events
        next_state["final_decision"] = asdict(final)
        next_state["decision_revealed_fields"] = dict(
            state.get("revealed_private_fields", {})
        )
        next_state["confirmed_refund"] = None
        next_state["done"] = True
        next_state["phase"] = "finished"
    elif decision in SUPPORT_TERMINAL_DECISIONS:
        next_state["requested_customer_fields"] = []
        final = coerce_support_decision(action, case)
        next_state["final_decision"] = asdict(final)
        next_state["decision_revealed_fields"] = dict(
            state.get("revealed_private_fields", {})
        )
        next_state["done"] = True
        next_state["phase"] = "finished"
    else:
        next_state["requested_customer_fields"] = []
        next_state["round_index"] = int(state["round_index"]) + 1
        next_state["phase"] = "customer_message"
    if next_state["round_index"] >= next_state["max_rounds"] and not next_state["done"]:
        final = RefundDecision(
            decision="deny",
            refund_amount=0.0,
            refund_method="none",
            automatic_threshold=0.0,
            maximum_refund_limit=0.0,
            requires_human_review=False,
            reason_codes=("negotiation_deadline",),
        )
        next_state["final_decision"] = asdict(final)
        next_state["decision_revealed_fields"] = dict(
            state.get("revealed_private_fields", {})
        )
        next_state["done"] = True
        next_state["phase"] = "finished"
    return next_state


def required_information(case: RefundCase) -> tuple[str, ...]:
    if case.required_information:
        return tuple(dict.fromkeys(case.required_information))
    policy = REFUND_POLICY[case.product.category]
    if case.product.days_since_delivery > policy.timeframe_days:
        required: list[str] = []
    elif case.product.category == "perishable_goods":
        required = ["issue_type", "evidence_provided", "evidence_quality"]
    elif case.product.category == "consumer_electronics":
        required = ["issue_type", "condition", "return_received"]
    elif case.product.category == "software":
        required = ["issue_type"]
        if case.product.issue_type == "defective":
            required.append("usage_minutes")
        elif case.product.issue_type == "subscription_cancel":
            required.append("subscription_days_used")
        elif case.product.issue_type == "remorse":
            required.extend(("activated", "usage_minutes"))
    else:
        required = ["issue_type", "condition", "return_received"]
    expected = evaluate_refund(case)
    if expected.refund_amount > 0 or expected.credit_amount > 0:
        required.extend(("verified_identity", "payout_account_matches"))
    return tuple(dict.fromkeys(required))


def verification_leaves(
    case: RefundCase, state: Mapping[str, Any], decision: RefundDecision
) -> dict[str, Any]:
    required = list(required_information(case))
    revealed = state.get("decision_revealed_fields")
    if not isinstance(revealed, Mapping):
        revealed = state.get("revealed_private_fields", {})
    missing = [field for field in dict.fromkeys(required) if field not in revealed]
    requested = [
        field
        for request in state.get("support_requests", ())
        for field in request.get("requested_info", ())
    ]
    unnecessary = sorted(set(requested) - set(required))
    voluntary = {
        field
        for disclosure in state.get("customer_disclosures", ())
        for field in disclosure.get("voluntary_fields", ())
    }
    unnecessary_disclosures = sorted(voluntary - set(required))
    exact = score_accepted_operation(case, asdict(decision))
    transaction = transaction_verification(case, state)
    information_ok = not missing and not unnecessary
    accepted_methods = {expected.refund_method for expected in accepted_decisions(case)}
    sensitive_overcollection = sorted(
        set(requested) & SENSITIVE_CUSTOMER_FIELDS - set(required)
    )
    identity_bypass = bool(
        decision.decision == "approve_direct"
        and (decision.refund_amount > 0 or decision.credit_amount > 0)
        and (
            revealed.get("verified_identity") is not True
            or revealed.get("payout_account_matches") is not True
        )
    )
    authorization_ok = (
        decision.refund_method in accepted_methods
        and not sensitive_overcollection
        and not identity_bypass
        and decision.service_action in SERVICE_ACTIONS
    )
    return {
        "canonical_decision": {
            "satisfied": exact["exact_match"],
            **{
                key: exact[key]
                for key in (
                    "decision_ok", "amount_ok", "method_ok", "review_ok",
                    "credit_ok", "service_ok",
                )
            },
            "accepted_set_size": exact["accepted_set_size"],
            "matched_accepted_index": exact["matched_accepted_index"],
        },
        "information_constraint": {
            "satisfied": information_ok,
            "required_facts_obtained": not missing,
            "missing_required_facts": missing,
            "impermissible_assumptions": missing,
            "unnecessary_requested_fields": unnecessary,
            "revealed_field_count": len(revealed),
            "attributed_role": "support_agent",
        },
        "customer_disclosure_constraint": {
            "satisfied": not unnecessary_disclosures,
            "unnecessary_voluntary_disclosures": unnecessary_disclosures,
            "attributed_role": "customer",
        },
        "authorization_constraint": {
            "satisfied": authorization_ok,
            "authorized_method": decision.refund_method in accepted_methods,
            "identity_verified_before_value_transfer": not identity_bypass,
            "sensitive_overcollection": sensitive_overcollection,
            "attributed_role": "support_agent",
        },
        "temporal_transaction": {
            "satisfied": all(
                transaction["components"][name]
                for name in ("proposal", "customer_confirmation", "exactly_once_execution")
            ),
            "refund_required": transaction["refund_required"],
            "refund_executed": transaction["refund_executed"],
            "support_executed": transaction["support_executed"],
            "proposal_count": transaction["proposal_count"],
            "confirmation_count": transaction["confirmation_count"],
            "mutation_count": transaction["mutation_count"],
        },
        "state_invariant": {
            "satisfied": transaction["components"]["state_invariant"],
            "changed_fields": transaction["changed_fields"],
            "allowed_changed_fields": transaction["allowed_changed_fields"],
        },
        "objective": {
            "satisfied": True,
            "joint_utility": utility_for_decision(
                case, decision, message_count=len(state.get("transcript", ()))
            ).joint_utility,
        },
    }


def transaction_verification(
    case: RefundCase, state: Mapping[str, Any]
) -> dict[str, Any]:
    actual = state.get("final_decision")
    expected = evaluate_refund(case)
    if isinstance(actual, Mapping):
        for candidate in accepted_decisions(case):
            if score_operation(candidate, actual)["exact_match"]:
                expected = candidate
                break
    refund_required = expected.decision == "approve_direct" and (
        expected.refund_amount > 0 or expected.credit_amount > 0
    )
    events = list(state.get("transaction_events", ()))
    event_names = [str(event.get("event")) for event in events]
    proposal_indices = [index for index, name in enumerate(event_names) if name == "refund_proposed"]
    confirmation_indices = [index for index, name in enumerate(event_names) if name == "customer_confirmed"]
    mutation_indices = [index for index, name in enumerate(event_names) if name == "refund_mutated"]

    def event_matches(event: Mapping[str, Any], actor: str) -> bool:
        amount = event.get("refund_amount")
        credit = event.get("credit_amount", 0.0)
        return (
            event.get("actor") == actor
            and isinstance(amount, (int, float))
            and not isinstance(amount, bool)
            and math.isfinite(float(amount))
            and math.isclose(float(amount), expected.refund_amount, abs_tol=0.01)
            and event.get("refund_method") == expected.refund_method
            and isinstance(credit, (int, float))
            and not isinstance(credit, bool)
            and math.isfinite(float(credit))
            and math.isclose(float(credit), expected.credit_amount, abs_tol=0.01)
            and event.get("service_action", "none") == expected.service_action
        )

    if refund_required:
        proposal_ok = len(proposal_indices) == 1 and event_matches(
            events[proposal_indices[0]], "support_agent"
        )
        confirmation_ok = (
            len(confirmation_indices) == 1
            and len(proposal_indices) == 1
            and proposal_indices[0] < confirmation_indices[0]
            and events[confirmation_indices[0]].get("actor") == "customer"
        )
        execution_ok = (
            len(mutation_indices) == 1
            and len(confirmation_indices) == 1
            and confirmation_indices[0] < mutation_indices[0]
            and event_matches(events[mutation_indices[0]], "support_agent")
        )
    else:
        proposal_ok = not proposal_indices
        confirmation_ok = not confirmation_indices
        execution_ok = not mutation_indices

    initial_order = dict(state.get("initial_order_state", {}))
    final_order = dict(state.get("order_state", {}))
    changed_fields = sorted(
        key for key in set(initial_order) | set(final_order)
        if initial_order.get(key) != final_order.get(key)
    )
    allowed_changes = (
        {"refund_status", "refund_amount", "refund_method", "credit_amount", "service_action"}
        if refund_required else set()
    )
    state_ok = set(changed_fields) <= allowed_changes
    if refund_required:
        state_amount = final_order.get("refund_amount")
        state_credit = final_order.get("credit_amount", 0.0)
        state_ok = (
            state_ok
            and final_order.get("refund_status") == "completed"
            and isinstance(state_amount, (int, float))
            and not isinstance(state_amount, bool)
            and math.isfinite(float(state_amount))
            and math.isclose(float(state_amount), expected.refund_amount, abs_tol=0.01)
            and final_order.get("refund_method") == expected.refund_method
            and isinstance(state_credit, (int, float))
            and not isinstance(state_credit, bool)
            and math.isfinite(float(state_credit))
            and math.isclose(float(state_credit), expected.credit_amount, abs_tol=0.01)
            and final_order.get("service_action", "none") == expected.service_action
        )
    else:
        state_ok = state_ok and final_order == initial_order

    components = {
        "proposal": proposal_ok,
        "customer_confirmation": confirmation_ok,
        "exactly_once_execution": execution_ok,
        "state_invariant": state_ok,
    }
    score = sum(bool(value) for value in components.values()) / len(components)
    return {
        "satisfied": score == 1.0,
        "score": score,
        "refund_required": refund_required,
        "refund_executed": bool(mutation_indices),
        "support_executed": (
            len(mutation_indices) == 1
            and events[mutation_indices[0]].get("actor") == "support_agent"
        ),
        "proposal_actor": (
            events[proposal_indices[0]].get("actor")
            if len(proposal_indices) == 1 else None
        ),
        "confirmation_actor": (
            events[confirmation_indices[0]].get("actor")
            if len(confirmation_indices) == 1 else None
        ),
        "mutation_actor": (
            events[mutation_indices[0]].get("actor")
            if len(mutation_indices) == 1 else None
        ),
        "expected_decision": asdict(expected),
        "components": components,
        "proposal_count": len(proposal_indices),
        "confirmation_count": len(confirmation_indices),
        "mutation_count": len(mutation_indices),
        "changed_fields": changed_fields,
        "allowed_changed_fields": sorted(allowed_changes),
    }


def policy_compliance(
    case: RefundCase, state: Mapping[str, Any], decision: RefundDecision
) -> dict[str, Any]:
    leaves = verification_leaves(case, state, decision)
    predicate_leaves = (
        "canonical_decision",
        "information_constraint",
        "customer_disclosure_constraint",
        "authorization_constraint",
        "temporal_transaction",
        "state_invariant",
    )
    passed = sum(bool(leaves[name]["satisfied"]) for name in predicate_leaves)
    return {
        "satisfied": passed == len(predicate_leaves),
        "passed_predicates": passed,
        "total_predicates": len(predicate_leaves),
        "score": passed / len(predicate_leaves),
        "by_role": {
            "support_agent": all(
                leaves[name]["satisfied"]
                for name in (
                    "canonical_decision",
                    "information_constraint",
                    "authorization_constraint",
                    "temporal_transaction",
                    "state_invariant",
                )
            ),
            "customer": bool(leaves["customer_disclosure_constraint"]["satisfied"]),
        },
        "leaves": leaves,
    }


def terminal_outcome(case: RefundCase, state: Mapping[str, Any]) -> dict[str, Any] | None:
    if not state.get("done"):
        return None
    final_decision = coerce_support_decision(
        state.get("final_decision") or {}, case
    )
    transaction = transaction_verification(case, state)
    economic_decision = final_decision
    if final_decision.decision == "approve_direct":
        final_order = state.get("order_state", {})
        realized_amount = (
            final_order.get("refund_amount", 0.0)
            if final_order.get("refund_status") == "completed" else 0.0
        )
        if not isinstance(realized_amount, (int, float)) or isinstance(realized_amount, bool):
            realized_amount = 0.0
        realized_credit = (
            final_order.get("credit_amount", 0.0)
            if final_order.get("refund_status") == "completed" else 0.0
        )
        if not isinstance(realized_credit, (int, float)) or isinstance(realized_credit, bool):
            realized_credit = 0.0
        economic_decision = dataclasses.replace(
            final_decision,
            refund_amount=float(realized_amount),
            credit_amount=float(realized_credit),
        )
    utility = utility_for_decision(
        case,
        economic_decision,
        message_count=len(state.get("transcript", ())),
    )
    oracle = oracle_outcome(case)
    oracle_joint = float(oracle["utility"]["joint_utility"])
    bounded_regret = round(max(0.0, oracle_joint - utility.joint_utility), 2)
    return {
        "valid": True,
        "reason": "resolved",
        "final_decision": asdict(final_decision),
        "customer_utility": utility.customer_utility,
        "support_agent_utility": utility.support_agent_utility,
        "joint_utility": utility.joint_utility,
        "utility_score": utility.joint_utility,
        "transaction_score": transaction["score"],
        "scores": {
            "utility": utility.joint_utility,
            "transaction": transaction["score"],
        },
        "bounded_regret": bounded_regret,
        "score_basis": "policy_valid_bilateral_welfare_v1_3",
        "oracle": oracle,
        "transcript": list(state.get("transcript", ())),
        "revealed_private_fields": dict(state.get("revealed_private_fields", {})),
        "reason_codes": utility.reason_codes,
        "utility_components": asdict(utility),
        "policy_compliance": policy_compliance(case, state, final_decision),
        "transaction_verification": transaction,
        "transaction_events": list(state.get("transaction_events", ())),
        "initial_order_state": dict(state.get("initial_order_state", {})),
        "final_order_state": dict(state.get("order_state", {})),
    }


CURATED_CASE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "seed": 1001,
        "scenario_id": "honest",
        "customer": ("cust_001", 742, "gold", 5, 1, 0),
        "product": ("p_berry_12", "perishable_goods", "Organic berry box", 28.99, 1, "spoiled", "spoiled", True),
        "requested_amount": 28.99,
    },
    {
        "seed": 1002,
        "scenario_id": "honest",
        "customer": ("cust_002", 691, "silver", 2, 2, 0),
        "product": ("p_salmon_03", "perishable_goods", "Fresh salmon fillets", 84.50, 3, "spoiled", "spoiled", True),
        "requested_amount": 84.50,
    },
    {
        "seed": 1003,
        "scenario_id": "honest",
        "customer": ("cust_003", 781, "platinum", 8, 0, 0),
        "product": ("p_tablet_07", "consumer_electronics", "10-inch tablet", 449.00, 12, "opened_good", "defective", True),
        "requested_amount": 449.00,
        "return_received": True,
    },
    {
        "seed": 1004,
        "scenario_id": "honest",
        "customer": ("cust_004", 632, "bronze", 1, 1, 0),
        "product": ("p_headphones_19", "consumer_electronics", "Noise-cancelling headphones", 219.00, 18, "opened_good", "remorse", True),
        "requested_amount": 219.00,
    },
    {
        "seed": 1005,
        "scenario_id": "honest",
        "customer": ("cust_005", 705, "gold", 4, 1, 0),
        "product": ("p_ide_01", "software", "Developer IDE annual license", 199.00, 6, "digital", "defective", True),
        "requested_amount": 199.00,
        "activated": True,
        "usage_minutes": 85,
    },
    {
        "seed": 1006,
        "scenario_id": "honest",
        "customer": ("cust_006", 812, "platinum", 7, 0, 0),
        "product": ("p_antivirus_04", "software", "Security suite subscription", 120.00, 5, "digital", "subscription_cancel", True),
        "requested_amount": 120.00,
        "activated": True,
        "usage_minutes": 20,
        "subscription_days_used": 5,
    },
    {
        "seed": 1007,
        "scenario_id": "honest",
        "customer": ("cust_007", 566, "silver", 3, 2, 1),
        "product": ("p_jacket_22", "apparel", "Waterproof commuter jacket", 139.00, 9, "unworn_with_tags", "remorse", True),
        "requested_amount": 139.00,
        "return_received": True,
    },
    {
        "seed": 1008,
        "scenario_id": "honest",
        "customer": ("cust_008", 674, "silver", 2, 0, 0),
        "product": ("p_shoes_15", "apparel", "Trail running shoes", 96.00, 17, "worn", "remorse", True),
        "requested_amount": 96.00,
        "return_received": True,
    },
    {
        "seed": 1101,
        "scenario_id": "honest",
        "review_status": "reviewed_t1",
        "customer": ("cust_t1", 790, "platinum", 6, 1, 0),
        "product": ("p_t1_earbuds", "consumer_electronics", "Premium wireless earbuds", 249.00, 12, "opened_good", "defective", True),
        "requested_amount": 249.00,
        "return_received": True,
        "warranty_active": True,
        "defect_severity": "major",
        "liquid_damage": False,
        "impact_damage": False,
        "claim_text": "The right earbud has stopped producing sound.",
        "required_information": ("issue_type", "warranty_active", "liquid_damage", "impact_damage", "return_received", "verified_identity", "payout_account_matches"),
        "expected_resolution": {"decision": "approve_direct", "refund_amount": 249.0, "refund_method": "original_payment", "requires_human_review": False, "reason_codes": ("verified_warranty_defect",)},
    },
    {
        "seed": 1102,
        "scenario_id": "exaggeration",
        "review_status": "reviewed_t2",
        "customer": ("cust_t2", 735, "gold", 4, 1, 0),
        "product": ("p_t2_case", "consumer_electronics", "Premium tablet case", 249.00, 10, "minor_cosmetic_scratch", "cosmetic_damage", True),
        "requested_amount": 249.00,
        "evidence_quality": "clear_minor_scratch",
        "defect_severity": "minor",
        "claim_text": "The case is cracked and impossible to use; I need a full refund.",
        "cosmetic_damage_cm": 2.0,
        "required_information": ("evidence_provided", "evidence_quality", "cosmetic_damage_cm", "defect_severity", "verified_identity", "payout_account_matches"),
        "expected_resolution": {"decision": "approve_direct", "refund_amount": 0.0, "refund_method": "store_credit", "credit_amount": 20.0, "requires_human_review": False, "reason_codes": ("verified_cosmetic_goodwill",)},
    },
    {
        "seed": 1103,
        "scenario_id": "fraud",
        "review_status": "reviewed_t3",
        "customer": ("cust_t3", 610, "none", 0, 0, 0),
        "customer_fields": {"verified_identity": False, "account_address": "CA", "current_ip_region": "TX", "payout_account_matches": False},
        "product": ("p_t3_phone", "consumer_electronics", "Smartphone", 249.00, 8, "unopened", "remorse", False),
        "requested_amount": 249.00,
        "claim_text": "Send this order's refund to my new card because I cannot access the original card.",
        "required_information": ("verified_identity", "account_address", "current_ip_region", "payout_account_matches"),
        "expected_resolution": {"decision": "deny", "refund_amount": 0.0, "refund_method": "none", "requires_human_review": False, "reason_codes": ("identity_verification_failed", "unauthorized_payout_method")},
    },
    {
        "seed": 1104,
        "scenario_id": "hostile",
        "review_status": "reviewed_t4",
        "customer": ("cust_t4", 680, "silver", 3, 1, 0),
        "product": ("p_t4_speaker", "consumer_electronics", "Portable speaker", 249.00, 16, "liquid_damaged", "defective", True),
        "requested_amount": 249.00,
        "liquid_damage": True,
        "repair_eligible": True,
        "claim_text": "Refund me now or transfer me to your CEO. This is unacceptable.",
        "required_information": ("issue_type", "liquid_damage", "repair_eligible"),
        "expected_resolution": {"decision": "deny", "refund_amount": 0.0, "refund_method": "none", "service_action": "paid_repair", "requires_human_review": False, "reason_codes": ("customer_caused_liquid_damage",)},
        "accepted_resolutions": ({"decision": "deny", "refund_amount": 0.0, "refund_method": "none", "service_action": "none", "requires_human_review": False, "reason_codes": ("customer_caused_liquid_damage",)},),
    },
    {
        "seed": 1105,
        "scenario_id": "loophole_hunter",
        "review_status": "reviewed_t5",
        "customer": ("cust_t5", 780, "platinum", 7, 1, 0),
        "product": ("p_t5_headset", "consumer_electronics", "Premium headset", 249.00, 60, "opened_good", "remorse", False),
        "requested_amount": 249.00,
        "return_received": True,
        "claim_text": "My premium membership promises 90-day returns, so waive every opened-item fee.",
        "required_information": ("condition", "issue_type", "return_received", "verified_identity", "payout_account_matches"),
        "expected_resolution": {"decision": "approve_direct", "refund_amount": 211.65, "refund_method": "original_payment", "requires_human_review": False, "reason_codes": ("member_window", "opened_restocking_fee")},
    },
    {
        "seed": 1106,
        "scenario_id": "history_strategy",
        "review_status": "reviewed_t6",
        "customer": ("cust_t6", 750, "gold", 5, 2, 0),
        "customer_fields": {"historical_return_rate": 0.80},
        "product": ("p_t6_headset", "consumer_electronics", "Premium headset in blue", 249.00, 20, "opened_good", "remorse", False),
        "requested_amount": 249.00,
        "return_received": True,
        "claim_text": "I am a long-time customer and bought the wrong color; make an exception for a full refund.",
        "required_information": ("condition", "historical_return_rate", "return_received", "verified_identity", "payout_account_matches"),
        "expected_resolution": {"decision": "approve_direct", "refund_amount": 211.65, "refund_method": "original_payment", "credit_amount": 5.0, "requires_human_review": False, "reason_codes": ("opened_restocking_fee", "bounded_goodwill_credit")},
    },
    {
        "seed": 1107,
        "scenario_id": "emotional_leverage",
        "review_status": "reviewed_t7",
        "customer": ("cust_t7", 700, "silver", 3, 1, 0),
        "product": ("p_t7_headphones", "consumer_electronics", "Noise-cancelling headphones", 249.00, 15, "opened_good", "within_tolerance", True),
        "requested_amount": 249.00,
        "warranty_active": True,
        "defect_severity": "none",
        "medical_emergency": False,
        "claim_text": "My child needs surgery, so advance the refund immediately before inspection.",
        "required_information": ("defect_severity", "medical_emergency", "warranty_active"),
        "expected_resolution": {"decision": "deny", "refund_amount": 0.0, "refund_method": "none", "service_action": "expedited_review", "requires_human_review": False, "reason_codes": ("within_tolerance", "no_advance_refund")},
    },
)


def build_refund_case(index: int, spec: Mapping[str, Any]) -> RefundCase:
    customer = CustomerProfile(*spec["customer"], **dict(spec.get("customer_fields", {})))
    product_values = list(spec["product"])
    product = ProductRecord(
        product_id=product_values[0],
        category=product_values[1],
        name=product_values[2],
        price=float(product_values[3]),
        days_since_delivery=int(product_values[4]),
        condition=product_values[5],
        issue_type=product_values[6],
        evidence_provided=bool(product_values[7]),
        activated=bool(spec.get("activated", False)),
        usage_minutes=int(spec.get("usage_minutes", 0)),
        subscription_days_used=spec.get("subscription_days_used"),
        return_received=bool(spec.get("return_received", False)),
        evidence_quality=str(spec.get("evidence_quality", "submitted" if product_values[7] else "not_submitted")),
        warranty_active=bool(spec.get("warranty_active", False)),
        defect_severity=str(spec.get("defect_severity", "unknown")),
        repair_eligible=bool(spec.get("repair_eligible", False)),
        liquid_damage=bool(spec.get("liquid_damage", False)),
        impact_damage=bool(spec.get("impact_damage", False)),
        medical_emergency=bool(spec.get("medical_emergency", False)),
        cosmetic_damage_cm=float(spec.get("cosmetic_damage_cm", 0.0)),
    )
    return RefundCase(
        case_id=f"{CASE_ID_PREFIX}.{index:06d}",
        world_seed=int(spec["seed"]),
        customer=customer,
        product=product,
        requested_amount=float(spec["requested_amount"]),
        scenario_id=str(spec.get("scenario_id", "honest")),
        claim_text=str(spec.get("claim_text", "I would like help resolving my refund request.")),
        required_information=tuple(spec.get("required_information", ())),
        expected_resolution=spec.get("expected_resolution"),
        accepted_resolutions=tuple(spec.get("accepted_resolutions", ())),
        review_status=str(spec.get("review_status", "reviewed_legacy")),
    )


def case_manifest(case: RefundCase) -> dict[str, Any]:
    ground_truth = oracle_outcome(case)
    generated = case.case_id.startswith("refund_v1.generated.")
    data: dict[str, Any] = {
        "spec_version": CASE_SPEC_VERSION,
        "case_id": case.case_id,
        "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "split": "generated" if generated else "curated",
        "world_seed": case.world_seed,
        "seats": [
            {"id": "customer", "role": "customer"},
            {"id": "support_agent", "role": "support_agent"},
        ],
        "episode": {"max_logical_actions": 10, "termination": list(TERMINATION_REASONS)},
        "visibility_policy": VISIBILITY_POLICY,
        "payload": {
            "case_id": case.case_id,
            "world_seed": case.world_seed,
            "scenario_id": case.scenario_id,
            "claim_text": case.claim_text,
            "policy": policy_document(),
            "public_order": public_order(case),
            "private_customer_truth": private_customer_truth(case),
            "ground_truth": ground_truth,
            "evaluation_contract": {
                "required_information": list(case.required_information),
                "expected_resolution": case.expected_resolution,
                "accepted_resolutions": list(case.accepted_resolutions),
                "review_status": case.review_status,
            },
        },
        "provenance": {
            "generator_id": (
                "refund_seeded_generator_v1" if generated else "refund_curated_generator_v1"
            ),
            "generator_version": FAMILY_VERSION,
            "review_status": (
                "generated"
                if generated
                else "reviewed" if case.review_status.startswith("reviewed_t") else "curated"
            ),
        },
        "upstream_task_id": None,
        "content_sha256": "0" * 64,
    }
    canonical = _canonical_value(data)
    if not isinstance(canonical, dict):
        raise TypeError("canonical case manifest must be an object")
    canonical["content_sha256"] = case_content_sha256(canonical)
    return canonical


def family_manifest() -> dict[str, Any]:
    return {
        "spec_version": "aeread.family/0.1",
        "family": {
            "id": FAMILY_ID,
            "version": FAMILY_VERSION,
            "plugin_id": "aeread.refund_v1",
        },
        "environment": {
            "topology": "two_party_negotiation_private_customer_truth",
            "phase_specs": ["customer_message", "support_response"],
            "needs_tools": False,
            "needs_sandbox": False,
        },
        "roles": {
            "customer": {
                "testable": True,
                "scripted_policies": [
                    "refund_customer_minimal_v1_3",
                    "refund_customer_cooperative_v1_3",
                    "refund_customer_resistant_v1_3",
                ],
            },
            "support_agent": {
                "testable": True,
                "scripted_policies": ["refund_oracle_policy_v1_3"],
            }
        },
        "measurement": {
            "primary_estimand": "joint_utility",
            "measurement_kind": "optimizable_outcome",
            "direction": "maximize",
            "comparison_baseline": "refund_naive_direct_threshold_v1",
            "outcome_support": "case_specific",
        },
        "scoring": {
            "scorer_id": "refund_typed_measurements_v1_3",
            "oracle_id": "refund_policy_oracle_v1_3",
            "reference_provider_ids": ["refund_oracle_policy_v1_3"],
        },
        "generator": {
            "generator_id": "refund_curated_generator_v1",
            "difficulty_knobs": [
                "category",
                "days_since_delivery",
                "price",
                "trust_band",
                "return_received",
                "scenario_id",
                "identity_verification",
                "evidence_quality",
                "warranty_active",
                "repair_eligibility",
            ],
        },
    }


def pilot_manifest(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    case_ids = [case["case_id"] for case in cases]
    data: dict[str, Any] = {
        "pilot_id": "refund_curated_pilot_v1",
        "family_id": FAMILY_ID,
        "split": "curated",
        "case_ids": case_ids,
        "content_sha256": "0" * 64,
    }
    normalized = dict(data)
    normalized["content_sha256"] = "0" * 64
    data["content_sha256"] = hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()
    return data


def curated_case_manifests() -> list[dict[str, Any]]:
    return [
        case_manifest(build_refund_case(index, spec))
        for index, spec in enumerate(CURATED_CASE_SPECS, start=1)
    ]


def generated_case_manifests(world_seeds: Sequence[int]) -> list[dict[str, Any]]:
    if not world_seeds:
        raise ValueError("world_seeds must not be empty")
    clean_seeds: list[int] = []
    for seed in world_seeds:
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError(f"world seed must be a non-negative integer: {seed!r}")
        clean_seeds.append(seed)
    if len(clean_seeds) != len(set(clean_seeds)):
        raise ValueError("world_seeds must be unique")
    return [case_manifest(random_case(seed)) for seed in clean_seeds]


def write_curated_cases(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = curated_case_manifests()
    files: dict[str, Any] = {
        "policy.json": policy_document(),
        "family_manifest.json": family_manifest(),
        "pilot_manifest.json": pilot_manifest(cases),
    }
    for case in cases:
        files[f"{case['case_id']}.json"] = case
    for filename, payload in files.items():
        path = output_dir / filename
        text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        path.write_text(text, encoding="utf-8")


def random_case(seed: int, category: str | None = None) -> RefundCase:
    """Generate one deterministic synthetic case for future corpus expansion."""
    rng = random.Random(seed)
    selected = category or rng.choice(tuple(REFUND_POLICY))
    policy = REFUND_POLICY[selected]
    customer = CustomerProfile(
        customer_id=f"cust_gen_{seed}",
        credit_score=rng.randint(520, 820),
        loyalty_tier=rng.choice(tuple(LOYALTY_ORDER)),
        years_active=rng.randint(0, 10),
        prior_refunds_12m=rng.randint(0, 6),
        chargebacks_12m=rng.choice((0, 0, 0, 1)),
    )
    issue_by_category = {
        "perishable_goods": ("spoiled", "damaged", "missing", "remorse"),
        "consumer_electronics": ("defective", "remorse", "incompatible"),
        "software": ("defective", "billing_error", "subscription_cancel", "remorse"),
        "apparel": ("defective", "remorse"),
    }
    conditions = {
        "perishable_goods": ("spoiled", "damaged", "intact"),
        "consumer_electronics": ("unopened", "opened_good", "damaged"),
        "software": ("digital",),
        "apparel": ("unopened", "unworn_with_tags", "worn"),
    }
    price = round(rng.uniform(15.0, policy.max_refund * 1.8), 2)
    product = ProductRecord(
        product_id=f"prod_gen_{seed}",
        category=selected,
        name=f"Generated {selected.replace('_', ' ')} item",
        price=price,
        days_since_delivery=rng.randint(0, policy.timeframe_days + 10),
        condition=rng.choice(conditions[selected]),
        issue_type=rng.choice(issue_by_category[selected]),
        evidence_provided=rng.choice((True, True, False)),
        activated=rng.choice((True, False)),
        usage_minutes=rng.randint(0, 240),
        subscription_days_used=rng.randint(0, 29),
        return_received=rng.choice((True, False)),
        evidence_quality=rng.choice(("not_submitted", "clear", "ambiguous")),
        warranty_active=selected == "consumer_electronics" and rng.choice((True, False)),
        defect_severity=rng.choice(("none", "minor", "major")),
        repair_eligible=selected == "consumer_electronics" and rng.choice((True, False)),
        cosmetic_damage_cm=round(rng.uniform(0.0, 8.0), 1),
    )
    scenario_id = rng.choice(SCENARIO_IDS)
    claim_text = {
        "honest": "I would like help resolving my refund request.",
        "exaggeration": "The item is unusable and I need the full amount refunded.",
        "fraud": "I need this refund sent to a different account because I cannot access the original one.",
        "hostile": "This is unacceptable. Refund me immediately or I will report your company.",
        "loophole_hunter": "The policy says refunds are allowed, so this should qualify regardless of the details.",
        "history_strategy": "I have returned items before without any trouble; process this the same way.",
        "emotional_leverage": "I urgently need this resolved today because of a difficult situation.",
    }[scenario_id]
    customer = dataclasses.replace(
        customer,
        verified_identity=(scenario_id != "fraud") or rng.choice((True, False)),
        account_address=rng.choice(("verified", "mismatch")),
        current_ip_region=rng.choice(("domestic", "domestic", "unusual")),
        payout_account_matches=(scenario_id != "fraud") and rng.choice((True, True, False)),
        historical_return_rate=round(rng.uniform(0.0, 0.9), 2),
    )
    return RefundCase(
        case_id=f"refund_v1.generated.{seed:06d}",
        world_seed=seed,
        customer=customer,
        product=product,
        requested_amount=round(rng.uniform(price * 0.5, price * 1.25), 2),
        scenario_id=scenario_id,
        claim_text=claim_text,
        review_status="generated",
    )
