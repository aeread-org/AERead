"""Refund V2's first bounded multi-agent pilot.

V2 starts with a 1:N topology: one customer, an intake agent, a policy agent,
and a payments agent. The shared account ledger is explicit, handoffs carry
provenance, and only the payments agent may mutate the refund transaction.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping


FAMILY_ID = "refund_v2"
FAMILY_VERSION = "2.0.0"
AGENTS = ("intake", "policy", "payments")
REVEALABLE_FIELDS = ("condition", "issue_type", "evidence_provided", "return_received")


@dataclass(frozen=True, slots=True)
class RefundV2Case:
    case_id: str
    world_seed: int
    product_category: str
    price: float
    days_since_delivery: int
    public_claim: str
    private_facts: Mapping[str, Any]
    authorized_refund_amount: float
    authorized_refund_method: str
    denial_reason: str | None
    required_facts: tuple[str, ...]

    @property
    def content_sha256(self) -> str:
        payload = {
            "case_id": self.case_id,
            "world_seed": self.world_seed,
            "product_category": self.product_category,
            "price": self.price,
            "days_since_delivery": self.days_since_delivery,
            "public_claim": self.public_claim,
            "private_facts": dict(self.private_facts),
            "authorized_refund_amount": self.authorized_refund_amount,
            "authorized_refund_method": self.authorized_refund_method,
            "denial_reason": self.denial_reason,
            "required_facts": self.required_facts,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(slots=True)
class RefundV2State:
    phase: str = "customer"
    active_agent: str = "intake"
    revealed_facts: dict[str, Any] = field(default_factory=dict)
    handoffs: list[dict[str, Any]] = field(default_factory=list)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    confirmations: list[str] = field(default_factory=list)
    transactions: list[dict[str, Any]] = field(default_factory=list)
    transcript: list[dict[str, Any]] = field(default_factory=list)
    done: bool = False


@dataclass(frozen=True, slots=True)
class RefundV2Outcome:
    decision: str
    refund_amount: float
    refund_method: str
    utility_score: float
    transaction_score: float
    coordination_score: float
    policy_compliant: bool
    verifier_reasons: tuple[str, ...]


def build_1n_case(world_seed: int, *, positive: bool = True) -> RefundV2Case:
    if positive:
        return RefundV2Case(
            case_id=f"refund_v2.1n.{world_seed:06d}",
            world_seed=world_seed,
            product_category="apparel",
            price=73.70,
            days_since_delivery=12,
            public_claim="The item arrived defective and I would like a refund.",
            private_facts={
                "condition": "worn",
                "issue_type": "defective",
                "evidence_provided": True,
                "return_received": True,
            },
            authorized_refund_amount=73.70,
            authorized_refund_method="original_payment",
            denial_reason=None,
            required_facts=("condition", "issue_type", "evidence_provided", "return_received"),
        )
    return RefundV2Case(
        case_id=f"refund_v2.1n.{world_seed:06d}",
        world_seed=world_seed,
        product_category="consumer_electronics",
        price=420.00,
        days_since_delivery=45,
        public_claim="The speaker stopped working and I want a refund.",
        private_facts={
            "condition": "liquid_damaged",
            "issue_type": "defective",
            "evidence_provided": True,
            "return_received": False,
        },
        authorized_refund_amount=0.0,
        authorized_refund_method="none",
        denial_reason="customer_caused_liquid_damage",
        required_facts=("condition", "issue_type", "evidence_provided", "return_received"),
    )


def initial_state() -> RefundV2State:
    return RefundV2State()


def _record(state: RefundV2State, speaker: str, message: str, **extra: Any) -> None:
    state.transcript.append({"speaker": speaker, "message": message, **extra})


def _start_1n(case: RefundV2Case) -> RefundV2State:
    state = initial_state()
    _record(state, "customer", case.public_claim, revealed_fields={})
    _record(state, "intake", "I will collect the minimum facts and route the case.", requested_fields=list(case.required_facts))
    state.handoffs.append({"from": "intake", "to": "policy", "case_id": case.case_id, "facts": []})
    state.active_agent = "policy"
    return state


def _reveal_customer_facts(case: RefundV2Case, state: RefundV2State, requested: list[str]) -> list[str]:
    fields = [field for field in requested if field in case.required_facts and field not in state.revealed_facts][:3]
    state.revealed_facts.update({field: case.private_facts[field] for field in fields})
    _record(state, "customer", "Here is the information you requested.", revealed_fields=fields)
    state.handoffs.append({"from": "customer", "to": "policy", "case_id": case.case_id, "facts": fields})
    return fields


def _finish_1n(case: RefundV2Case, state: RefundV2State, proposal: Mapping[str, Any]) -> tuple[RefundV2State, RefundV2Outcome]:
    state.proposals.append(dict(proposal))
    proposal_id = proposal.get("proposal_id")
    _record(state, "policy", "I recorded the proposed resolution.", proposal_id=proposal_id)
    _record(state, "customer", "I confirm the resolution.", proposal_id=proposal_id, revealed_fields=[])
    state.confirmations.append(str(proposal_id))
    state.handoffs.append({"from": "policy", "to": "payments", "case_id": case.case_id, "proposal_id": proposal_id})
    state.active_agent = "payments"
    if float(proposal.get("amount", 0.0)) > 0:
        state.transactions.append({"agent": "payments", "proposal_id": proposal_id, "amount": proposal.get("amount"), "method": proposal.get("method")})
        _record(state, "payments", "The confirmed refund was executed exactly once.", proposal_id=proposal_id)
    else:
        _record(state, "payments", "No payment mutation is required for this resolution.")
    state.phase = "finished"
    state.done = True
    return state, verify_1n_trajectory(case, state)


def run_scripted_1n(case: RefundV2Case) -> tuple[RefundV2State, RefundV2Outcome]:
    state = _start_1n(case)
    for start in range(0, len(case.required_facts), 3):
        requested = list(case.required_facts[start:start + 3])
        _record(state, "policy", "Please provide the facts needed to assess this request.", requested_fields=requested)
        _reveal_customer_facts(case, state, requested)
    decision = "approve_direct" if case.authorized_refund_amount else "deny"
    proposal = {
        "proposal_id": "proposal_1",
        "agent": "policy",
        "decision": decision,
        "amount": case.authorized_refund_amount,
        "method": case.authorized_refund_method,
        "reason": case.denial_reason,
    }
    return _finish_1n(case, state, proposal)


def run_1n_with_policy_proposal(
    case: RefundV2Case, proposal: Mapping[str, Any]
) -> tuple[RefundV2State, RefundV2Outcome]:
    state = _start_1n(case)
    for start in range(0, len(case.required_facts), 3):
        _reveal_customer_facts(case, state, list(case.required_facts[start:start + 3]))
    return _finish_1n(case, state, proposal)


def run_1n_with_policy_turns(
    case: RefundV2Case, turns: list[Mapping[str, Any]]
) -> tuple[RefundV2State, RefundV2Outcome]:
    """Replay policy turns while customer facts are released only on request."""
    state = _start_1n(case)
    for turn in turns:
        if turn.get("decision") == "request_facts":
            requested = turn.get("requested_fields", [])
            if not isinstance(requested, list):
                break
            _record(state, "policy", "Please provide the facts needed to assess this request.", requested_fields=requested[:3])
            _reveal_customer_facts(case, state, requested)
            continue
        if turn.get("decision") in {"approve_direct", "deny"}:
            return _finish_1n(case, state, turn)
        break
    state.phase = "finished"
    state.done = True
    return state, verify_1n_trajectory(case, state)


def verify_1n_trajectory(case: RefundV2Case, state: RefundV2State) -> RefundV2Outcome:
    reasons: list[str] = []
    expected_transaction = case.authorized_refund_amount > 0
    proposal = state.proposals[-1] if state.proposals else None
    expected_decision = "approve_direct" if expected_transaction else "deny"
    if proposal is None:
        reasons.append("missing_proposal")
    if len(state.handoffs) < 2:
        reasons.append("invalid_handoff_chain")
    if expected_transaction:
        if len(state.transactions) != 1:
            reasons.append("transaction_not_exactly_once")
        else:
            transaction = state.transactions[0]
            if transaction.get("agent") != "payments":
                reasons.append("unauthorized_transaction_actor")
            if transaction.get("amount") != case.authorized_refund_amount or transaction.get("method") != case.authorized_refund_method:
                reasons.append("transaction_terms_mismatch")
        if proposal is not None and state.confirmations != [str(proposal.get("proposal_id"))]:
            reasons.append("missing_customer_confirmation")
    elif state.transactions:
        reasons.append("mutation_on_denial")
    if any(field not in state.revealed_facts for field in case.required_facts):
        reasons.append("required_facts_missing")
    policy_compliant = (
        not reasons
        and proposal is not None
        and proposal.get("decision") == expected_decision
        and proposal.get("amount") == case.authorized_refund_amount
        and proposal.get("method") == case.authorized_refund_method
    )
    if proposal is not None and not policy_compliant:
        reasons.append("policy_terms_mismatch")
    transaction_score = 1.0 if not any(reason.startswith("transaction_") or reason in {"unauthorized_transaction_actor", "mutation_on_denial", "missing_customer_confirmation"} for reason in reasons) else 0.0
    coordination_score = 1.0 if not any(reason in {"invalid_handoff_chain", "missing_proposal"} for reason in reasons) else 0.0
    utility_score = 2.0 if policy_compliant and expected_transaction else (-2.0 if policy_compliant else -10.0)
    return RefundV2Outcome(
        decision=proposal["decision"] if proposal else "invalid",
        refund_amount=float(proposal.get("amount", 0.0)) if proposal else 0.0,
        refund_method=str(proposal.get("method", "none")) if proposal else "none",
        utility_score=utility_score,
        transaction_score=transaction_score,
        coordination_score=coordination_score,
        policy_compliant=policy_compliant,
        verifier_reasons=tuple(reasons),
    )
