"""Refund negotiation cases: deterministic policy oracle and case records.

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
FAMILY_VERSION = "1.0.0"
POLICY_ID = "omnichannel_refund_policy_v1"
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


@dataclass(frozen=True)
class ProductRecord:
    product_id: str
    category: str
    name: str
    price: float
    days_since_delivery: int
    condition: str
    issue_type: str
    evidence_provided: bool
    activated: bool = False
    usage_minutes: int = 0
    subscription_days_used: int | None = None
    return_received: bool = False


@dataclass(frozen=True)
class RefundCase:
    case_id: str
    world_seed: int
    customer: CustomerProfile
    product: ProductRecord
    requested_amount: float


@dataclass(frozen=True)
class RefundDecision:
    decision: str
    refund_amount: float
    refund_method: str
    automatic_threshold: float
    maximum_refund_limit: float
    requires_human_review: bool
    reason_codes: tuple[str, ...]


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


CUSTOMER_REVEAL_FIELDS = (
    "condition",
    "issue_type",
    "evidence_provided",
    "activated",
    "usage_minutes",
    "subscription_days_used",
    "return_received",
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
        "general_rules": [
            "Refunds are capped by the product category maximum even when the order price is higher.",
            "Direct automatic refunds are allowed only when the final refund amount is at or below the customer's automatic threshold.",
            "Amounts above the automatic threshold must be escalated to human review before money is returned.",
            "Fraud-watch customers require human review for any monetary refund.",
            "Physical goods that require return must be received before a direct refund unless the policy explicitly waives return.",
        ],
        "trust_rules": {
            "high_trust": "credit_score >= 720, loyalty tier gold or platinum, chargebacks_12m == 0, prior_refunds_12m <= 2",
            "good_trust": "credit_score >= 660, loyalty tier silver or higher, chargebacks_12m == 0, prior_refunds_12m <= 3",
            "standard": "all customers not otherwise classified",
            "fraud_watch": "credit_score < 580 or chargebacks_12m > 0 or prior_refunds_12m >= 5",
        },
        "categories": categories,
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
    if policy.evidence_required and not product.evidence_provided:
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
    amount, reasons = _eligible_amount(case.product, case.requested_amount)
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
    if band == "fraud_watch" or amount > threshold:
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


def eligible_refund_amount(case: RefundCase) -> float:
    amount, _reasons = _eligible_amount(case.product, case.requested_amount)
    return amount


def coerce_support_decision(action: Mapping[str, Any]) -> RefundDecision:
    decision = str(action.get("decision", "deny"))
    raw_amount = action.get("refund_amount", 0.0)
    amount = 0.0
    if isinstance(raw_amount, (int, float)) and not isinstance(raw_amount, bool):
        amount = round(max(0.0, float(raw_amount)), 2)
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
        reason_codes=(),
    )


def utility_for_decision(
    case: RefundCase,
    decision: RefundDecision,
    *,
    message_count: int = 0,
) -> UtilityOutcome:
    policy = REFUND_POLICY[case.product.category]
    eligible_amount, eligibility_reasons = _eligible_amount(
        case.product, case.requested_amount
    )
    threshold = automatic_threshold(case.customer, policy)
    true_oracle = evaluate_refund(case)
    reasons: list[str] = list(eligibility_reasons)
    penalty = 0.0
    friction = round(2.0 * max(0, message_count - 1), 2)
    transfer = 0.0
    expected_customer_value = 0.0
    review_cost = 0.0
    return_cost = 0.0

    if decision.decision == "approve_direct":
        transfer = decision.refund_amount
        expected_customer_value = transfer
        if trust_band(case.customer) == "fraud_watch" or transfer > threshold:
            penalty += 125.0
            reasons.append("direct_refund_exceeded_authority")
        if policy.return_required and not case.product.return_received:
            penalty += 100.0
            reasons.append("direct_refund_before_required_return")
    elif decision.decision == "escalate":
        transfer = decision.refund_amount
        expected_customer_value = max(0.0, transfer - 5.0)
        review_cost = 8.0
        if transfer <= threshold and trust_band(case.customer) != "fraud_watch":
            reasons.append("unnecessary_review")
    elif decision.decision == "request_return":
        return_cost = 6.0
        if policy.return_required and not case.product.return_received and eligible_amount > 0:
            transfer = eligible_amount
            expected_customer_value = max(0.0, eligible_amount - return_cost)
        else:
            penalty += 75.0
            reasons.append("unnecessary_or_invalid_return_request")
    elif decision.decision == "deny":
        transfer = 0.0
        expected_customer_value = 0.0
    else:
        penalty += 150.0
        reasons.append("unknown_support_decision")

    if decision.decision != "request_return":
        excess = max(0.0, transfer - eligible_amount)
        shortfall = max(0.0, eligible_amount - transfer)
    else:
        excess = 0.0
        shortfall = 0.0 if true_oracle.decision == "request_return" else eligible_amount
    if excess:
        penalty += round(1.5 * excess, 2)
        reasons.append("over_refund_leakage")
    if shortfall and decision.decision != "escalate":
        penalty += round(shortfall, 2)
        reasons.append("eligible_refund_underpaid")

    method_expected = {
        "approve_direct": "original_payment",
        "request_return": "pending_original_payment",
        "escalate": "original_payment_after_review",
        "deny": "none",
    }.get(decision.decision)
    if method_expected is not None and decision.refund_method != method_expected:
        penalty += 25.0
        reasons.append("wrong_refund_method")
    if decision.requires_human_review != (decision.decision == "escalate"):
        penalty += 25.0
        reasons.append("wrong_review_flag")

    relationship_surplus = round(min(50.0, 0.2 * eligible_amount), 2)
    if eligible_amount <= 0 or decision.decision == "deny":
        relationship_surplus = 0.0

    customer_utility = round(expected_customer_value - friction, 2)
    support_utility = round(
        relationship_surplus - transfer - penalty - review_cost - return_cost,
        2,
    )
    joint = round(customer_utility + support_utility, 2)
    return UtilityOutcome(
        customer_utility=customer_utility,
        support_agent_utility=support_utility,
        joint_utility=joint,
        transfer_amount=round(transfer, 2),
        relationship_surplus=relationship_surplus,
        penalty=round(penalty + review_cost + return_cost + friction, 2),
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def oracle_outcome(case: RefundCase) -> dict[str, Any]:
    decision = evaluate_refund(case)
    utility = utility_for_decision(case, decision, message_count=2)
    return {"decision": asdict(decision), "utility": asdict(utility)}


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
    exact = decision_ok and amount_ok and method_ok and review_ok
    return {
        "exact_match": exact,
        "decision_ok": decision_ok,
        "amount_ok": amount_ok,
        "method_ok": method_ok,
        "review_ok": review_ok,
        "expected": asdict(expected),
    }


def initial_negotiation_state(case: RefundCase) -> dict[str, Any]:
    return {
        "round_index": 0,
        "phase": "customer_message",
        "transcript": [],
        "revealed_private_fields": {},
        "requested_customer_fields": [],
        "pending_offer": None,
        "final_decision": None,
        "done": False,
        "max_rounds": 4,
    }


def public_order(case: RefundCase) -> dict[str, Any]:
    return {
        "customer": asdict(case.customer),
        "product": {
            "product_id": case.product.product_id,
            "category": case.product.category,
            "name": case.product.name,
            "price": case.product.price,
            "days_since_delivery": case.product.days_since_delivery,
        },
        "requested_amount": case.requested_amount,
    }


def private_customer_truth(case: RefundCase) -> dict[str, Any]:
    return {field: getattr(case.product, field) for field in CUSTOMER_REVEAL_FIELDS}


def customer_observation(case: RefundCase, state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "role": "customer",
        "round_index": state["round_index"],
        "public_order": public_order(case),
        "private_truth": private_customer_truth(case),
        "requested_info": list(state.get("requested_customer_fields", ())),
        "pending_offer": state.get("pending_offer"),
        "transcript": list(state["transcript"]),
    }


def support_observation(case: RefundCase, state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "role": "support_agent",
        "round_index": state["round_index"],
        "policy": policy_document(),
        "public_order": public_order(case),
        "revealed_customer_fields": dict(state["revealed_private_fields"]),
        "pending_offer": state.get("pending_offer"),
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
    for field in requested_fields:
        if field in truth:
            current_reveal[field] = truth[field]
            revealed[field] = truth[field]
    message = action.get("message")
    if not isinstance(message, str) or not message.strip():
        message = "Customer did not provide a usable message."
    next_state["revealed_private_fields"] = revealed
    next_state["requested_customer_fields"] = []
    next_state["transcript"] = [
        *state["transcript"],
        asdict(RefundMessage("customer", message, current_reveal)),
    ]
    if action.get("decision") == "accept_offer" and state.get("pending_offer"):
        offer = state["pending_offer"]
        decision = RefundDecision(
            decision="approve_direct",
            refund_amount=float(offer["refund_amount"]),
            refund_method="original_payment",
            automatic_threshold=0.0,
            maximum_refund_limit=0.0,
            requires_human_review=False,
            reason_codes=("accepted_negotiated_offer",),
        )
        next_state["final_decision"] = asdict(decision)
        next_state["done"] = True
        next_state["phase"] = "finished"
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
    if decision == "ask_info":
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
        next_state["round_index"] = int(state["round_index"]) + 1
        next_state["phase"] = "customer_message"
    elif decision == "offer":
        next_state["requested_customer_fields"] = []
        amount = action.get("refund_amount")
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            amount = 0.0
        next_state["pending_offer"] = {
            "refund_amount": round(max(0.0, float(amount)), 2),
            "message": message,
        }
        next_state["round_index"] = int(state["round_index"]) + 1
        next_state["phase"] = "customer_message"
    elif decision in SUPPORT_TERMINAL_DECISIONS:
        next_state["requested_customer_fields"] = []
        final = coerce_support_decision(action)
        next_state["final_decision"] = asdict(final)
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
        next_state["done"] = True
        next_state["phase"] = "finished"
    return next_state


def terminal_outcome(case: RefundCase, state: Mapping[str, Any]) -> dict[str, Any] | None:
    if not state.get("done"):
        return None
    final_decision = coerce_support_decision(state.get("final_decision") or {})
    utility = utility_for_decision(
        case,
        final_decision,
        message_count=len(state.get("transcript", ())),
    )
    oracle = oracle_outcome(case)
    oracle_joint = float(oracle["utility"]["joint_utility"])
    within_case_score = None
    if oracle_joint > 0:
        within_case_score = round(utility.joint_utility / oracle_joint, 6)
    return {
        "valid": True,
        "reason": "resolved",
        "final_decision": asdict(final_decision),
        "customer_utility": utility.customer_utility,
        "support_agent_utility": utility.support_agent_utility,
        "joint_utility": utility.joint_utility,
        "within_case_score": within_case_score,
        "oracle": oracle,
        "transcript": list(state.get("transcript", ())),
        "revealed_private_fields": dict(state.get("revealed_private_fields", {})),
        "reason_codes": utility.reason_codes,
    }


CURATED_CASE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "seed": 1001,
        "customer": ("cust_001", 742, "gold", 5, 1, 0),
        "product": ("p_berry_12", "perishable_goods", "Organic berry box", 28.99, 1, "spoiled", "spoiled", True),
        "requested_amount": 28.99,
    },
    {
        "seed": 1002,
        "customer": ("cust_002", 691, "silver", 2, 2, 0),
        "product": ("p_salmon_03", "perishable_goods", "Fresh salmon fillets", 84.50, 3, "spoiled", "spoiled", True),
        "requested_amount": 84.50,
    },
    {
        "seed": 1003,
        "customer": ("cust_003", 781, "platinum", 8, 0, 0),
        "product": ("p_tablet_07", "consumer_electronics", "10-inch tablet", 449.00, 12, "opened_good", "defective", True),
        "requested_amount": 449.00,
        "return_received": True,
    },
    {
        "seed": 1004,
        "customer": ("cust_004", 632, "bronze", 1, 1, 0),
        "product": ("p_headphones_19", "consumer_electronics", "Noise-cancelling headphones", 219.00, 18, "opened_good", "remorse", True),
        "requested_amount": 219.00,
    },
    {
        "seed": 1005,
        "customer": ("cust_005", 705, "gold", 4, 1, 0),
        "product": ("p_ide_01", "software", "Developer IDE annual license", 199.00, 6, "digital", "defective", True),
        "requested_amount": 199.00,
        "activated": True,
        "usage_minutes": 85,
    },
    {
        "seed": 1006,
        "customer": ("cust_006", 812, "platinum", 7, 0, 0),
        "product": ("p_antivirus_04", "software", "Security suite subscription", 120.00, 5, "digital", "subscription_cancel", True),
        "requested_amount": 120.00,
        "activated": True,
        "usage_minutes": 20,
        "subscription_days_used": 5,
    },
    {
        "seed": 1007,
        "customer": ("cust_007", 566, "silver", 3, 2, 1),
        "product": ("p_jacket_22", "apparel", "Waterproof commuter jacket", 139.00, 9, "unworn_with_tags", "remorse", True),
        "requested_amount": 139.00,
        "return_received": True,
    },
    {
        "seed": 1008,
        "customer": ("cust_008", 674, "silver", 2, 0, 0),
        "product": ("p_shoes_15", "apparel", "Trail running shoes", 96.00, 17, "worn", "remorse", True),
        "requested_amount": 96.00,
        "return_received": True,
    },
)


def build_refund_case(index: int, spec: Mapping[str, Any]) -> RefundCase:
    customer = CustomerProfile(*spec["customer"])
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
    )
    return RefundCase(
        case_id=f"{CASE_ID_PREFIX}.{index:06d}",
        world_seed=int(spec["seed"]),
        customer=customer,
        product=product,
        requested_amount=float(spec["requested_amount"]),
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
        "episode": {"max_logical_actions": 8, "termination": list(TERMINATION_REASONS)},
        "visibility_policy": VISIBILITY_POLICY,
        "payload": {
            "case_id": case.case_id,
            "world_seed": case.world_seed,
            "policy": policy_document(),
            "public_order": public_order(case),
            "private_customer_truth": private_customer_truth(case),
            "ground_truth": ground_truth,
        },
        "provenance": {
            "generator_id": (
                "refund_seeded_generator_v1" if generated else "refund_curated_generator_v1"
            ),
            "generator_version": FAMILY_VERSION,
            "review_status": "generated" if generated else "curated",
        },
        "upstream_task_id": None,
        "content_sha256": "0" * 64,
    }
    data["content_sha256"] = case_content_sha256(data)
    return data


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
                "testable": False,
                "scripted_policies": ["refund_customer_llm_profile_v1"],
            },
            "support_agent": {
                "testable": True,
                "scripted_policies": ["refund_oracle_policy_v1"],
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
            "scorer_id": "refund_operation_exact_match_v1",
            "oracle_id": "refund_policy_oracle_v1",
            "reference_provider_ids": ["refund_oracle_policy_v1"],
        },
        "generator": {
            "generator_id": "refund_curated_generator_v1",
            "difficulty_knobs": [
                "category",
                "days_since_delivery",
                "price",
                "trust_band",
                "return_received",
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
    )
    return RefundCase(
        case_id=f"refund_v1.generated.{seed:06d}",
        world_seed=seed,
        customer=customer,
        product=product,
        requested_amount=round(rng.uniform(price * 0.5, price * 1.25), 2),
    )
