"""Public V3 law, not evaluator answers. Native fixtures remain in provenance.

This revision reopens qualification; it cannot inherit the redesign/2 verdict.
"""
from __future__ import annotations

import copy

REVISION = "refund_v3_publication_repair/4"
POLICY_MAX_BATCH_SIZE = 3
# Versioned whole-source admission decisions; recomputed on regeneration.
PAYMENT_QUARANTINE_COHORTS = ("seat_v3.payments", "v4.payments")
INTAKE_EXTENSION_COHORTS = ("v5.intake",)
CLAIM_RULE = "Return state_claim with message exactly equal to public_claim. This is a canonical claim acknowledgement, not a paraphrase or a new policy assertion."

INTAKE_RULE = (
    "V3 collection law: request a nonempty batch of distinct, undisclosed catalogue "
    "fact IDs, or handoff at any time. Every requested source must be authorized; "
    "ALL prerequisites must already be disclosed at round start (a same-batch "
    "prerequisite does not unlock a dependent). Sum of batch costs must fit the "
    "remaining TOTAL budget; obey max_batch_size and max_rounds. material=false "
    "requests are LEGAL and earn ZERO utility. Optimize the ENTIRE remaining "
    "multi-round plan: first maximize total material utility, then minimize total "
    "cost. All objective ties receive equal credit; output order is irrelevant. "
    "A legal early handoff or wasteful request can lose quality credit. Utilities "
    "are synthetic work-order units, NOT money or refund-policy evidence. "
    "No private fact value or policy outcome is implied by utility or material."
)

CUSTOMER_RULE = (
    "V3 disclosure law: choose owned matching record IDs only for explicitly "
    "requested fact IDs. Omissions and wrong owned matching records are legal "
    "but lose disclosure credit; selected values are never replaced by an oracle. "
    "For quality, first restrict to request_scope and recorded_at <= as_of. "
    "Within each (fact_id, document_id), use the highest numeric revision; if "
    "that record is revoked, that document supplies no value (do not revive an "
    "older live record). Among live documents listed in authorities, select the "
    "lowest numeric priority. Document/record IDs and array order confer no "
    "authority. Revisions and times are ordinal, possibly negative. Confirmation "
    "is a separate phase: confirm only the current proposal ID and its exact "
    "amount, workflow, refund_method, payment_mutation and return_shipping_payer. "
    "Rejecting the current unchanged proposal is legal but loses consent credit."
)


def normalize_intake(contract):
    result = copy.deepcopy(contract)
    # Replace conflicting historical text; do not append competing instructions.
    result["rule"] = INTAKE_RULE
    return result


def normalize_customer(contract):
    result = copy.deepcopy(contract)
    result["rule"] = CUSTOMER_RULE
    return result


def payment_contract(kind, ledger):
    """Complete public algorithm and units, without a computed allocation ticket."""
    from . import v2_5_seat_extension_v4 as v4
    from . import v2_5_seat_extension_v5 as v5

    if kind in ("v4", "v5"):
        contract = copy.deepcopy(v5.PAYMENT_CONTRACT if kind == "v5" else v4.CONTRACT)
        # V4's historical record/scope paragraphs are easily misread as filter
        # then reduce. State the actual order explicitly for both generations.
        contract["record_rule"] = (
            "Reduce ALL records by event_id to the highest numeric revision "
            "BEFORE filtering order_id, line_item_id and currency. Revisions "
            "per event are unique; record array order has no effect."
        )
        if kind == "v5":
            contract["execution_rule"] = contract["execution_rule"].replace(
                "Integer cents throughout.",
                "Use integer cents for internal reconciliation/allocation; divide "
                "by 100 for action amount and allocation.amount in major units.")
    else:
        rule = ledger.get("allocation_rule", "explicit_legacy_allocations")
        contract = {"allocation_rule": rule, "rules": {
            "waterfall_remaining_capacity": (
                "Use the positive confirmed amount. Traverse tender_capacities "
                "in ARRAY order, taking min(remaining amount, remaining_capacity) "
                "at each destination, rounding to two decimals at each step. "
                "Retain zero rows as supplied by this legacy convention."
            ),
            "proportional_original_tender": (
                "In original_tender_shares ARRAY order, allocate round(approved "
                "amount * share, 2) except at the last destination, which gets "
                "the remaining amount. Use Python nearest-even binary-float "
                "rounding, matching this declared legacy convention."
            ),
            "residual_after_settled_refunds": (
                "Residual = round(max(requested_amount - settled_refund_amount, "
                "0), 2); allocate it to original_tender."
            ),
            "original_rail_then_allowed_fallback": (
                "Allocate the positive confirmed amount to allowed_fallback_rail "
                "iff state is primary_rail_closed, otherwise original_rail."
            ),
            "explicit_legacy_allocations": (
                "Use the explicitly supplied refund_allocations on an execute "
                "instruction; these legacy instructions are diagnostic when "
                "they do not require meaningful allocation reasoning."
            ),
        }[rule]}
    contract.update(
        version=REVISION,
        units=("Action amount and refund_allocations.amount are currency MAJOR "
               "units with at most two decimals. Fields ending _cents are "
               "integer minor units. Convert approved amount using "
               "round(amount * 100); never output cents in a major-unit field."),
        binding_rule=("Copy confirmed_proposal.proposal_id, current ledger "
                      "idempotency_key and snapshot_id (or ledger_snapshot_id) "
                      "to the action. Do not recompute policy eligibility."),
        delivery_rule=("delivery_already_applied or ledger.already_applied, a "
                       "non-execute proposal, or zero obligation requires "
                       "no_mutation. Re-evaluate the current snapshot on every "
                       "delivery; positive execution is exactly once."),
        quality_vs_legality=("no_mutation with amount=0, refund_method=none and "
                             "refund_allocations=[] is legal, but loses quality "
                             "credit when an execute obligation exists. Safe "
                             "underpayment or nonpriority allocation can be "
                             "legal but fails exact execution quality."),
    )
    return contract
