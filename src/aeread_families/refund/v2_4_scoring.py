"""V2.4 attribution scorer: semantic policy is distinct from wire contract.

Only unambiguous aliases are normalized.  The raw spelling remains visible as
a protocol failure, so an operationally strict deployment can still report it
without calling it a policy-reasoning error.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .v2_4_cases import MarketplaceV24Case
from .v2_4_reference import V24Resolution, resolve_policy


_ALIASES = {
    "eligibility": {"not_eligible": "ineligible", "requires_clarification": "unresolved"},
    "remedy": {"refund": "full_refund", "deny_refund": "none", "issue_clarification": "none"},
    "workflow": {
        "refund": "execute_refund", "approve_refund": "execute_refund",
        "deny": "no_mutation", "deny_refund": "no_mutation",
        "clarify_issue": "request_issue_clarification",
    },
    "payment_mutation": {"refund": "execute", "no_refund": "none"},
    "return_shipping_payer": {"buyer": "customer", "not_applicable": "none"},
}


def _canonical(field: str, value: Any) -> tuple[Any, bool]:
    if value is None and field in {"remedy", "workflow", "payment_mutation", "return_shipping_payer"}:
        return "none", False
    aliases = _ALIASES.get(field, {})
    return aliases.get(value, value), value in aliases


@dataclass(frozen=True, slots=True)
class V24Attribution:
    policy_semantic_score: float
    workflow_score: float
    payment_score: float
    evidence_score: float
    contract_score: float
    operational_score: float
    taxonomy: tuple[str, ...]
    expected: Mapping[str, Any]
    normalized_proposal: Mapping[str, Any]


def score_proposal(
    case: MarketplaceV24Case,
    proposal: Mapping[str, Any] | None,
    *,
    revealed_fact_ids: Sequence[str] = (),
    transaction_count: int = 0,
    operational_failure: str | None = None,
) -> V24Attribution:
    """Score a model proposal without conflating policy and contract errors."""
    expected: V24Resolution = resolve_policy(case)
    exp = asdict(expected)
    tags: list[str] = []
    if operational_failure:
        return V24Attribution(0, 0, 0, 0, 0, 0, (f"operational_{operational_failure}",), exp, {})
    if proposal is None:
        return V24Attribution(0, 0, 0, 0, 0, 1, ("protocol_missing_resolution",), exp, {})

    normalized: dict[str, Any] = {}
    contract_errors = 0
    for field in ("eligibility", "remedy", "workflow", "payment_mutation", "return_shipping_payer"):
        value, alias = _canonical(field, proposal.get(field))
        normalized[field] = value
        if alias:
            tags.append(f"contract_noncanonical_{field}")
            contract_errors += 1
    normalized["amount"] = round(float(proposal.get("amount", 0.0)), 2)
    normalized["refund_method"] = "none" if proposal.get("refund_method") is None else proposal.get("refund_method")
    normalized["policy_basis"] = proposal.get("policy_basis")

    # Semantic policy dimensions only: no reason-code or enum-spelling test.
    policy_ok = True
    if normalized["eligibility"] != exp["eligibility"]:
        tags.append("policy_eligibility_boundary_error"); policy_ok = False
    if normalized["remedy"] != exp["remedy"]:
        tags.append("policy_remedy_selection_error"); policy_ok = False
    if normalized["amount"] != exp["amount"]:
        tags.append("policy_amount_calculation_error"); policy_ok = False
    if normalized["return_shipping_payer"] != exp["return_shipping_payer"]:
        tags.append("policy_liability_assignment_error"); policy_ok = False

    workflow_ok = normalized["workflow"] == exp["workflow"]
    if not workflow_ok: tags.append("workflow_routing_error")
    payment_ok = normalized["payment_mutation"] == exp["payment_mutation"] and normalized["refund_method"] == exp["refund_method"]
    if not payment_ok: tags.append("payment_mutation_error")
    expected_transactions = 1 if exp["payment_mutation"] == "execute" else 0
    if transaction_count != expected_transactions:
        tags.append("payment_execution_error")
        payment_ok = False

    sufficient = set(exp["required_fact_ids"]).issubset(revealed_fact_ids)
    if not sufficient:
        tags.append("evidence_insufficient_before_decision")
    raw_reason = proposal.get("reason_code", proposal.get("policy_basis"))
    if raw_reason is not None and raw_reason != exp["policy_basis"]:
        tags.append("contract_reason_code_noncanonical")
        contract_errors += 1
    contract_ok = contract_errors == 0
    return V24Attribution(float(policy_ok), float(workflow_ok), float(payment_ok), float(sufficient), float(contract_ok), 1.0, tuple(sorted(set(tags))), exp, normalized)


__all__ = ["V24Attribution", "score_proposal"]
