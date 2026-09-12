"""Refund V2.2 N:1 constrained-allocation environment.

V2.2 groups several customers into one shared support episode. Customer facts
remain private until requested, while one policy seat allocates a finite refund
budget across the resulting claims. Payments is the only mutating seat.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass, field
from typing import Any, Mapping


FAMILY_ID = "refund_v2"
FAMILY_VERSION = "2.2.0"
REVEALABLE_FIELDS = ("condition", "issue_type", "evidence_provided", "return_received")
PRIORITY_WEIGHTS = {"standard": 1, "elevated": 2, "critical": 3}


def derive_priority(priority_basis: str) -> int:
    """Map the declared public service basis to the allocation weight."""
    try:
        return PRIORITY_WEIGHTS[priority_basis]
    except KeyError as error:
        raise ValueError(f"unknown priority basis: {priority_basis!r}") from error


@dataclass(frozen=True, slots=True)
class RefundV22Case:
    case_id: str
    customer_id: str
    world_seed: int
    product_category: str
    price: float
    priority: int
    public_claim: str
    scenario: str
    policy_summary: str
    private_facts: Mapping[str, Any]
    authorized_refund_amount: float
    authorized_refund_method: str
    denial_reason: str | None
    required_facts: tuple[str, ...]
    priority_basis: str = "standard"

    @property
    def eligible(self) -> bool:
        return self.authorized_refund_amount > 0.0

    @property
    def content_sha256(self) -> str:
        payload = {
            "case_id": self.case_id,
            "customer_id": self.customer_id,
            "world_seed": self.world_seed,
            "product_category": self.product_category,
            "price": self.price,
            "priority": self.priority,
            "priority_basis": self.priority_basis,
            "public_claim": self.public_claim,
            "scenario": self.scenario,
            "policy_summary": self.policy_summary,
            "private_facts": dict(self.private_facts),
            "authorized_refund_amount": self.authorized_refund_amount,
            "authorized_refund_method": self.authorized_refund_method,
            "denial_reason": self.denial_reason,
            "required_facts": self.required_facts,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class RefundV22Batch:
    batch_id: str
    world_seed: int
    refund_budget: float
    review_capacity: int
    cases: tuple[RefundV22Case, ...]

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(json.dumps({
            "batch_id": self.batch_id,
            "world_seed": self.world_seed,
            "refund_budget": self.refund_budget,
            "review_capacity": self.review_capacity,
            "case_sha256s": [case.content_sha256 for case in self.cases],
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(slots=True)
class RefundV22State:
    phase: str = "customer_intake"
    revealed_facts: dict[str, dict[str, Any]] = field(default_factory=dict)
    decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    transactions: list[dict[str, Any]] = field(default_factory=list)
    transcript: list[dict[str, Any]] = field(default_factory=list)
    invalid_requests: list[str] = field(default_factory=list)
    budget_remaining: float = 120.0
    done: bool = False


@dataclass(frozen=True, slots=True)
class RefundV22Outcome:
    selected_case_ids: tuple[str, ...]
    policy_compliant: bool
    allocation_score: float
    transaction_score: float
    coordination_score: float
    system_utility: float
    verifier_reasons: tuple[str, ...]


def _case(
    world_seed: int,
    customer_number: int,
    *,
    scenario: str,
    priority: int,
    priority_basis: str | None = None,
    category: str,
    price: float,
    amount: float,
    claim: str,
    summary: str,
    facts: Mapping[str, Any],
    denial_reason: str | None = None,
) -> RefundV22Case:
    customer_id = f"customer_{customer_number}"
    basis = priority_basis or next(
        (name for name, weight in PRIORITY_WEIGHTS.items() if weight == priority),
        None,
    )
    if basis is None or derive_priority(basis) != priority:
        raise ValueError("priority must be derived from a declared priority_basis")
    return RefundV22Case(
        case_id=f"refund_v2.2n.{scenario}.{world_seed:06d}.{customer_number}",
        customer_id=customer_id,
        world_seed=world_seed,
        product_category=category,
        price=price,
        priority=priority,
        public_claim=claim,
        scenario=scenario,
        policy_summary=summary,
        private_facts=dict(facts),
        authorized_refund_amount=amount,
        authorized_refund_method="original_payment" if amount else "none",
        denial_reason=denial_reason,
        required_facts=REVEALABLE_FIELDS,
        priority_basis=basis,
    )


def build_n1_batch(world_seed: int) -> tuple[RefundV22Case, ...]:
    """Build three claims sharing one 120-unit refund budget.

    The two positive claims cost more than the shared budget, so allocation is
    nontrivial. The denial claim tests that a zero-cost denial does not consume
    budget or create a payment mutation.
    """
    return (
        _case(
            world_seed, 1, scenario="full_refund", priority=2,
            category="apparel", price=73.70, amount=73.70,
            claim="The item arrived defective and I would like a refund.",
            summary="Apparel defects are eligible for a full refund within 30 days when returned.",
            facts={"condition": "worn", "issue_type": "defective", "evidence_provided": True, "return_received": True},
        ),
        _case(
            world_seed, 2, scenario="partial_software", priority=3,
            category="software", price=120.00, amount=90.00,
            claim="The software service did not meet my needs and I want a partial refund.",
            summary="Lightly used software receives a 75 percent refund within 30 days.",
            facts={"condition": "intact", "issue_type": "service_quality", "evidence_provided": True, "return_received": True},
        ),
        _case(
            world_seed, 3, scenario="liquid_damage_denial", priority=1,
            category="consumer_electronics", price=420.00, amount=0.0,
            claim="The speaker stopped working and I want a refund.",
            summary="Consumer electronics are not refundable when liquid damage caused the failure.",
            facts={"condition": "liquid_damaged", "issue_type": "defective", "evidence_provided": True, "return_received": False},
            denial_reason="customer_caused_liquid_damage",
        ),
    )


def build_n1_panel(world_seed: int) -> RefundV22Batch:
    """Build one pinned but varied N:1 allocation world.

    The rotation changes the shared budget and priority ordering.  The policy
    reference therefore has to solve an allocation problem rather than learn a
    fixed customer position.  Cases retain their gradual-disclosure protocol.
    """
    budget, priorities = (
        (120.0, (2, 3, 1)),
        (100.0, (3, 2, 1)),
        (165.0, (2, 3, 1)),
        (200.0, (3, 2, 1)),
        (90.0, (1, 3, 2)),
        (145.0, (3, 1, 2)),
    )[world_seed % 6]
    cases = build_n1_batch(world_seed)
    varied_cases = tuple(
        RefundV22Case(
            **{field: (
                    priorities[index] if field == "priority" else
                    next(name for name, weight in PRIORITY_WEIGHTS.items() if weight == priorities[index])
                    if field == "priority_basis" else getattr(case, field)
                )
               for field in RefundV22Case.__dataclass_fields__}
        )
        for index, case in enumerate(cases)
    )
    return RefundV22Batch(
        batch_id=f"refund_v2.2n.batch.{world_seed:06d}",
        world_seed=world_seed,
        refund_budget=budget,
        review_capacity=2,
        cases=varied_cases,
    )


def _record(state: RefundV22State, speaker: str, customer_id: str | None, message: str, **extra: Any) -> None:
    state.transcript.append({"speaker": speaker, "customer_id": customer_id, "message": message, **extra})


def _disclose_case(case: RefundV22Case, state: RefundV22State) -> None:
    state.revealed_facts[case.customer_id] = {}
    _record(state, "customer", case.customer_id, case.public_claim, revealed_fields=[])
    first = list(case.required_facts[:3])
    second = list(case.required_facts[3:])
    for requested in (first, second):
        _record(state, "policy", case.customer_id, "Please provide the requested facts.", requested_fields=requested)
        revealed = {field: case.private_facts[field] for field in requested}
        state.revealed_facts[case.customer_id].update(revealed)
        _record(state, "customer", case.customer_id, "Here is the information you requested.", revealed_fields=requested)


def _optimal_selection(
    cases: tuple[RefundV22Case, ...], budget: float, review_capacity: int
) -> tuple[str, ...]:
    """Exhaustively maximize declared priority subject to budget and capacity.

    Ties prefer serving more customers, then the lower total transfer.  This
    makes the allocation reference explicit and stable across panel variants.
    """
    eligible = tuple(case for case in cases if case.eligible)
    candidates = []
    for count in range(min(review_capacity, len(eligible)) + 1):
        for selection in itertools.combinations(eligible, count):
            total = sum(case.authorized_refund_amount for case in selection)
            if total <= budget:
                candidates.append((selection, total))
    best, _ = max(
        candidates,
        key=lambda item: (
            sum(case.priority for case in item[0]),
            len(item[0]),
            -item[1],
            tuple(case.customer_id for case in item[0]),
        ),
    )
    return tuple(case.case_id for case in best)


def _cents(amount: float) -> int:
    """Compare currency exactly at the policy boundary, not as binary floats."""
    return round(float(amount) * 100)


def verify_n1_trajectory(
    batch: RefundV22Batch, state: RefundV22State
) -> RefundV22Outcome:
    """Verify a completed N:1 allocation independently of the policy actor.

    A served eligible claim must carry its exact authorized amount and method;
    every other claim must be a zero-value ``deny_or_defer``.  The allocation
    leaf is intentionally stricter than feasibility: it checks the declared
    priority/capacity optimum, so a feasible but suboptimal batch is visible as
    an allocation failure rather than silently counted as policy-compliant.
    """
    cases = batch.cases
    selected = tuple(
        case.case_id
        for case in cases
        if state.decisions.get(case.case_id, {}).get("decision") == "approve"
    )
    expected = _optimal_selection(cases, batch.refund_budget, batch.review_capacity)
    reasons: list[str] = []
    decision_valid = True
    for case in cases:
        decision = state.decisions.get(case.case_id)
        if not isinstance(decision, Mapping):
            decision_valid = False
            continue
        served = case.case_id in selected
        if served:
            decision_valid &= (
                case.eligible
                and _cents(float(decision.get("amount", 0.0))) == _cents(case.authorized_refund_amount)
                and decision.get("method") == case.authorized_refund_method
            )
        else:
            decision_valid &= (
                decision.get("decision") == "deny_or_defer"
                and _cents(float(decision.get("amount", 0.0))) == 0
                and decision.get("method") == "none"
            )
    if not decision_valid:
        reasons.append("per_claim_policy_terms_mismatch")

    allocation_score = 1.0 if selected == expected and decision_valid else 0.0
    if allocation_score == 0.0:
        reasons.append("allocation_policy_mismatch")
    expected_transactions = [
        {
            "customer_id": case.customer_id,
            "case_id": case.case_id,
            "amount": case.authorized_refund_amount,
            "method": case.authorized_refund_method,
        }
        for case in cases if case.case_id in selected
    ]
    spent = sum(_cents(item.get("amount", 0.0)) for item in state.transactions)
    transaction_score = 1.0 if (
        state.transactions == expected_transactions
        and spent <= _cents(batch.refund_budget)
        and _cents(state.budget_remaining) == _cents(batch.refund_budget) - spent
    ) else 0.0
    if transaction_score == 0.0:
        reasons.append("shared_budget_or_transaction_invariant")
    coordination_score = 1.0 if all(
        state.revealed_facts.get(case.customer_id) == dict(case.private_facts)
        for case in cases
    ) else 0.0
    if coordination_score == 0.0:
        reasons.append("incomplete_or_unproven_disclosure")
    policy_compliant = allocation_score == 1.0 and not state.invalid_requests
    if state.invalid_requests:
        reasons.append("invalid_fact_request")
    system_utility = sum(
        2.0 if case.case_id in selected else (-1.0 if case.eligible else 1.0)
        for case in cases
    )
    return RefundV22Outcome(
        selected, policy_compliant, allocation_score, transaction_score,
        coordination_score, system_utility, tuple(reasons),
    )


def run_scripted_n1(
    batch: RefundV22Batch | tuple[RefundV22Case, ...] | None = None,
) -> tuple[RefundV22State, RefundV22Outcome]:
    if batch is None:
        batch = build_n1_panel(1)
    if isinstance(batch, RefundV22Batch):
        cases = batch.cases
        budget = batch.refund_budget
        review_capacity = batch.review_capacity
    else:
        cases = batch
        budget = 120.0
        review_capacity = 2
    if len(cases) < 2:
        raise ValueError("N:1 requires at least two customer cases")
    state = RefundV22State(budget_remaining=budget)
    for case in cases:
        _disclose_case(case, state)
    selected = _optimal_selection(cases, state.budget_remaining, review_capacity)
    selected_set = set(selected)
    expected = {case.case_id: case.case_id in selected_set for case in cases}
    for case in cases:
        decision = "approve" if expected[case.case_id] else "deny_or_defer"
        state.decisions[case.case_id] = {"decision": decision, "amount": case.authorized_refund_amount if expected[case.case_id] else 0.0, "method": case.authorized_refund_method if expected[case.case_id] else "none"}
        _record(state, "policy", case.customer_id, decision, case_id=case.case_id)
        if expected[case.case_id]:
            _record(state, "customer", case.customer_id, "I confirm the proposed refund.", case_id=case.case_id)
            state.transactions.append({"customer_id": case.customer_id, "case_id": case.case_id, "amount": case.authorized_refund_amount, "method": case.authorized_refund_method})
            state.budget_remaining -= case.authorized_refund_amount
            _record(state, "payments", case.customer_id, "The confirmed refund was executed exactly once.", case_id=case.case_id)
        elif case.eligible:
            _record(state, "customer", case.customer_id, "The request was deferred because shared capacity was exhausted.", case_id=case.case_id)
        else:
            _record(state, "payments", case.customer_id, "No payment mutation is required for this denial.", case_id=case.case_id)
    state.phase = "finished"
    state.done = True
    # A tuple input is retained as a narrow backwards-compatible fixture API.
    verifier_batch = batch if isinstance(batch, RefundV22Batch) else RefundV22Batch(
        batch_id="refund_v2.2n.legacy_batch", world_seed=0, refund_budget=budget,
        review_capacity=review_capacity, cases=cases,
    )
    return state, verify_n1_trajectory(verifier_batch, state)


__all__ = [
    "FAMILY_ID",
    "FAMILY_VERSION",
    "RefundV22Case",
    "RefundV22Batch",
    "RefundV22Outcome",
    "RefundV22State",
    "build_n1_batch",
    "build_n1_panel",
    "derive_priority",
    "PRIORITY_WEIGHTS",
    "run_scripted_n1",
    "verify_n1_trajectory",
]
