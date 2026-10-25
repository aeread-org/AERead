"""Versioned seat-specific case selections for the next V2.5 experiments."""
from __future__ import annotations

from dataclasses import replace

from .v2_4_cases import MarketplaceV24Case
from .v2_5_policy import (
    SCENARIO_CATEGORY,
    UnifiedRefundCase,
    _extension_price,
    build_unified_panel,
    build_policy_stress_panel,
    payment_ledger,
    resolve_policy,
)


PAYMENT_SCENARIOS = frozenset({
    "payments_proportional_tender",
    "payments_idempotency_retry",
    "payments_residual_waterfall",
    "payments_three_tender_rounding",
    "payments_prior_refund_reconciliation",
    "payments_rail_fallback",
})

INTAKE_CHALLENGE_SCENARIOS = (
    "policy_identity_override", "policy_evidence_conflict",
    "policy_seller_fault_override", "policy_time_anchor",
    "policy_perishable_verification", "policy_bundle_cap",
    "policy_return_liability", "policy_payment_hold_precedence",
)

CUSTOMER_CHALLENGE_SCENARIOS = (
    "policy_identity_override", "policy_evidence_conflict",
    "policy_seller_fault_override", "policy_time_anchor",
    "policy_identity_followup", "policy_bundle_boundary",
    "policy_payment_reconcile", "policy_evidence_inconclusive",
)


def _seat_challenge_cases(seed: int, seat: str, scenarios: tuple[str, ...]) -> tuple[UnifiedRefundCase, ...]:
    source = build_policy_stress_panel(seed)
    selected = [case for case in source if case.interaction.scenario in scenarios]
    if len(selected) != 2 * len(scenarios):
        raise ValueError(f"{seat} challenge panel is missing one or more complete counterfactual pairs")
    by_scenario: dict[str, list[UnifiedRefundCase]] = {scenario: [] for scenario in scenarios}
    for case in selected:
        by_scenario[case.interaction.scenario].append(case)
    output = []
    for scenario in scenarios:
        pair = by_scenario[scenario]
        if len(pair) != 2:
            raise ValueError(f"{seat} challenge pair {scenario} must contain exactly two variants")
        pair_id = f"v25_{seat}_challenge_{scenario.removeprefix('policy_')}"
        for case in pair:
            interaction = replace(
                case.interaction,
                case_id=f"refund_v2.4.{seat}_challenge.{scenario}.{case.interaction.variant}.{seed:06d}",
                pair_id=pair_id,
                policy_summary=f"V2.5 {seat} seat challenge: {scenario}.",
            )
            output.append(UnifiedRefundCase(interaction, case.product_category))
    result = tuple(output)
    if len({case.case_id for case in result}) != len(result):
        raise ValueError(f"{seat} challenge panel contains duplicate case IDs")
    return result


def build_intake_challenge_cases(seed: int = 301) -> tuple[UnifiedRefundCase, ...]:
    """Eight mechanism-distinct pairs for value-blind intake routing quality."""
    return _seat_challenge_cases(seed, "intake", INTAKE_CHALLENGE_SCENARIOS)


def build_customer_integrity_cases(seed: int = 401) -> tuple[UnifiedRefundCase, ...]:
    """Eight pairs with varied fact types and multi-turn customer opportunities."""
    return _seat_challenge_cases(seed, "customer", CUSTOMER_CHALLENGE_SCENARIOS)


def build_payment_residual_boundary_pair(seed: int) -> tuple[UnifiedRefundCase, ...]:
    """Hold the approved obligation fixed; change settled refund by one cent."""
    pair_id = "v25_payment_residual_boundary"
    price = _extension_price(seed, pair_id, 18000, 26000)
    tax = round(price * 0.0825, 2)
    obligation_cents = int(round(round(price + tax, 2) * 100))
    public_claim = "A verified defective software entitlement must be refunded."
    summary = "V2.5 payment residual boundary extension."
    cases = []
    for variant, settled_cents in (
        ("fully_settled", obligation_cents),
        ("one_cent_residual", obligation_cents - 1),
    ):
        interaction = MarketplaceV24Case(
            f"refund_v2.5.payments_prior_refund_reconciliation.{variant}.{seed:06d}",
            seed,
            "payments_prior_refund_reconciliation",
            variant,
            pair_id,
            ("settled_refund_cents",),
            public_claim,
            summary,
            price,
            tax,
            {"defect_evidence": "verified", "settled_refund_cents": settled_cents},
        )
        cases.append(UnifiedRefundCase(interaction, SCENARIO_CATEGORY[interaction.scenario]))

    # Admission proof: the policy proposal remains identical, while the
    # executable payment ticket changes from no residual to exactly one cent.
    left, right = cases
    assert resolve_policy(left) == resolve_policy(right)
    assert payment_ledger(left, resolve_policy(left).amount)["executable_amount"] == 0.0
    assert payment_ledger(right, resolve_policy(right).amount)["executable_amount"] == 0.01
    return tuple(cases)


def build_payment_smoke_cases(seed: int = 201) -> tuple[UnifiedRefundCase, ...]:
    """Six payment pairs, a one-cent boundary pair, and a hold pair (16 cases)."""
    panel = build_unified_panel(seed, include_operational_extension=True)
    payment_cases = [case for case in panel if case.interaction.scenario in PAYMENT_SCENARIOS]
    hold_cases = [
        case for case in panel
        if case.interaction.scenario == "refund_already_issued_chargeback_pending"
    ]
    boundary_cases = list(build_payment_residual_boundary_pair(seed))
    result = tuple(payment_cases + boundary_cases + hold_cases)
    if len(result) != 16:
        raise ValueError(f"expected 16 payment smoke cases, got {len(result)}")
    if len({case.case_id for case in result}) != len(result):
        raise ValueError("payment smoke panel contains duplicate case IDs")
    return result


__all__ = [
    "build_customer_integrity_cases", "build_intake_challenge_cases",
    "build_payment_residual_boundary_pair", "build_payment_smoke_cases",
]
