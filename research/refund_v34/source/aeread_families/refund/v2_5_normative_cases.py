"""Opt-in normative regression worlds, separate from the comparison library.

Five pairs per seed. They are diagnostic controls, not a newly balanced
model-comparison panel. No cases or outcomes are selected using model answers.
"""
from dataclasses import replace

from .v2_5_policy import build_unified_panel

OPTIONS = dict(include_operational_extension=True, include_policy_stress_extension=True,
               include_policy_frontier_extension=True, include_policy_frontier_hard_extension=True)


def build_normative_panel(seed):
    panel = build_unified_panel(seed, **OPTIONS)
    definitions = (
        ("policy_evidence_conflict", "aligned", "evidence_match", ("customer_evidence", "warehouse_inspection"),
         {"customer_evidence": "verified_match", "warehouse_inspection": "verified_match"},
         {"customer_evidence": "verified_mismatch", "warehouse_inspection": "verified_mismatch"}),
        ("policy_return_liability", "carrier_damage", "original_defect", ("original_defect_evidence",),
         {"original_defect_evidence": "customer_assertion"}, {"original_defect_evidence": "verified"}),
        ("wrong_item_received", "verified_mismatch", "sku_match", ("received_sku",),
         {"received_sku": "A"}, {"received_sku": "B"}),
        ("policy_payment_reconcile", "no_prior_refund", "refund_pending", ("prior_refund_state",),
         {"prior_refund_state": "refund_pending"}, {"prior_refund_state": "none"}),
        ("policy_bundle_cap", "below_cap", "zero_amount", ("paid_component_allocation",),
         {"paid_component_allocation": 0}, {"paid_component_allocation": 0.01}),
    )
    result = []
    for scenario, variant, label, changed, negative, positive in definitions:
        base = next(c for c in panel if c.interaction.scenario == scenario and c.interaction.variant == variant)
        for kind, patch in (("negative", negative), ("positive", positive)):
            interaction = replace(base.interaction,
                case_id=f"refund_v2.5.normative.{label}.{kind}.{seed:06d}",
                pair_id=f"normative_{label}", variant=kind, changed_fact_ids=changed,
                facts={**base.interaction.facts, **patch})
            result.append(replace(base, interaction=interaction))
    return tuple(result)
