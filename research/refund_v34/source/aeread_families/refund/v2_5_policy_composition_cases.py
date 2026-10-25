"""New development-only compositions over already-admitted V2.5 mechanisms.

This extension adds interaction structure, not new refund entitlements.  It is
kept outside the frozen policy-comparison panels and is not a blind holdout.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from aeread.shared_runner.run.resolver import ImplementationPin

from .v2_5_policy import UnifiedRefundCase, build_policy_frontier_hard_panel


def build_policy_composition_panel(seed: int = 501) -> tuple[UnifiedRefundCase, ...]:
    """Four minimal pairs for competing holds and conditional branch order."""
    source = build_policy_frontier_hard_panel(seed)
    template_by_scenario = {}
    for case in source:
        template_by_scenario.setdefault(case.interaction.scenario, case)

    specs = (
        (
            "frontier_hard_payment_identity",
            "payment_vs_identity_hold",
            "A returned defective device has both an identity mismatch and payment-state records requiring review.",
            ("chargeback_state",),
            (
                ("identity_hold_only", {"chargeback_state": "none"}),
                ("payment_hold_precedence", {"chargeback_state": "pending"}),
            ),
            {
                "chargeback_state": "none",
                "inspection_stage": "post_return_warehouse",
                "order_serial": f"P-{seed}",
                "inspection_serial": f"P-{seed + 1}",
                "defect_evidence": "verified",
            },
        ),
        (
            "frontier_hard_payment_identity",
            "identity_short_circuit_before_defect",
            "A returned device has a warehouse identity check and only customer-asserted defect evidence.",
            ("inspection_serial",),
            (
                ("identity_mismatch", {"inspection_serial": f"S-{seed + 1}"}),
                ("identity_match", {"inspection_serial": f"S-{seed}"}),
            ),
            {
                "chargeback_state": "none",
                "inspection_stage": "post_return_warehouse",
                "order_serial": f"S-{seed}",
                "inspection_serial": f"S-{seed + 1}",
                "defect_evidence": "customer_assertion",
            },
        ),
        (
            "frontier_hard_override_liability",
            "seller_fault_after_return_damage_check",
            "A final-sale returned device has post-return carrier damage and a possible wrong-item shipment.",
            ("seller_fault_event",),
            (
                ("no_verified_seller_fault", {"seller_fault_event": "none"}),
                ("verified_wrong_item", {"seller_fault_event": "verified_wrong_item"}),
            ),
            {
                "category_final_sale": True,
                "seller_fault_event": "none",
                "inspection_cause": "carrier_damage",
                "original_defect_evidence": "verified",
            },
        ),
        (
            "frontier_hard_authority_flip",
            "corroboration_after_registry_match",
            "The serial registry clears an identity concern, but customer and warehouse evidence must corroborate the item mismatch.",
            ("customer_evidence",),
            (
                ("customer_assertion_only", {"customer_evidence": "customer_assertion"}),
                ("corroborated_customer_evidence", {"customer_evidence": "verified_mismatch"}),
            ),
            {
                "customer_evidence": "customer_assertion",
                "warehouse_inspection": "verified_mismatch",
                "serial_registry": "match",
                "inspection_serial": f"E-{seed}",
                "order_serial": f"E-{seed}",
            },
        ),
    )

    cases: list[UnifiedRefundCase] = []
    for scenario, mechanism, claim, changed, variants, base_facts in specs:
        template = template_by_scenario[scenario]
        # These pairs must change policy semantics, not only a ledger detail.
        pair_id = f"hard_v25_policy_composition_{mechanism}"
        for variant, overrides in variants:
            facts = {**base_facts, **overrides}
            interaction = replace(
                template.interaction,
                case_id=f"refund_v2.4.policy_composition.{mechanism}.{variant}.{seed:06d}",
                variant=variant,
                pair_id=pair_id,
                changed_fact_ids=changed,
                public_claim=claim,
                policy_summary=f"V2.5 development composition challenge: {mechanism}.",
                facts=facts,
            )
            cases.append(UnifiedRefundCase(interaction, template.product_category))
    result = tuple(cases)
    if len(result) != 8 or len({case.case_id for case in result}) != 8:
        raise ValueError("policy composition panel must contain eight unique variants")
    return result


def policy_composition_case_pin() -> ImplementationPin:
    path = Path(__file__)
    return ImplementationPin(
        "refund_v25_policy_composition_cases",
        "reference",
        "1",
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )


__all__ = ["build_policy_composition_panel", "policy_composition_case_pin"]
