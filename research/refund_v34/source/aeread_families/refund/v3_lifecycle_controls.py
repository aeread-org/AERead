"""Executable observation-only controls; classifications fixed before screening.

The twelve previously missing challenges are retained by exact name. Historical
naive/random/collect_all functions are called unchanged, not redefined to lose.
Competent policies are reported separately even when they reach the reference.
"""
from . import v3_environment as old, v3_runner as runner

EXTRA = {
    "policy": ("always_deny", "always_defer", "branch_label_or_identifier_cue"),
    "intake": ("always_handoff", "greedy_immediate_utility", "price_only_selection"),
    "customer": ("always_confirm", "stale_proposal_confirmation", "record_id_or_position_cue"),
    "payments": ("always_execute", "bound_underpayment", "ignore_redelivery_or_proposal_revision"),
}
COMPETENT = ("independent_observation_policy",)


def arms(seat): return ("reference", "naive", "random", "collect_all", *EXTRA[seat], *COMPETENT)


def registry():
    from .v3_case_admission_review import registry as previous
    prior = previous()
    rows = list(prior["controls"])
    reasons = {
        "always_deny": "Fixed denial without evaluating evidence or precedence.",
        "always_defer": "Fixed manual review without deciding a determined obligation.",
        "branch_label_or_identifier_cue": "Chooses a refund-labelled branch without testing its predicate.",
        "always_handoff": "Never plans or collects evidence.",
        "greedy_immediate_utility": "Ignores value unlocked by future prerequisites.",
        "price_only_selection": "Chooses only by acquisition price and lexical tie-break, ignoring utility and dependencies.",
        "always_confirm": "Copies current terms without checking the customer's private consent.",
        "stale_proposal_confirmation": "Reuses archived consent for a revised proposal.",
        "record_id_or_position_cue": "Chooses smallest record identifier rather than source authority and snapshot.",
        "always_execute": "Executes without reconciliation or duplicate suppression.",
        "bound_underpayment": "Pays a feasible half-bound without satisfying the obligation.",
        "ignore_redelivery_or_proposal_revision": "Caches the first execution and reuses it after redelivery or authorization revision.",
    }
    for seat, names in EXTRA.items():
        for name in names:
            rows.append(dict(seat=seat, arm=name, classification="shortcut", reason=reasons[name],
                provenance=["artifacts/refund_v3_case_admission_review1/shortcut_registry.json",
                    "docs/families/refund/qc.md", "docs/families/refund/refund_v3_design.md"],
                implementation="v3_lifecycle_controls.action", coverage="executable_native_and_lifecycle"))
        rows.append(dict(seat=seat, arm=COMPETENT[0], classification="competent_simple_policy",
            reason="Evaluates the permitted branch/record/ledger semantics; Intake DP objective is independently enumerated.",
            provenance=["src/aeread_families/refund/v3_oracles.py"], implementation="v3_lifecycle.independent_action"))
    return dict(revision="refund_v31_controls/1", controls=rows, unexecuted_challenges=[],
        historical_scope="All controls in case-admission-review/1 plus its twelve named open challenges. Not a claim to enumerate every conceivable shortcut.",
        future_shortcut_rule="Preserve frozen worlds, report per-world ties and record an incident; never relabel a losing/tied arm after outcomes.")


def _fixed_policy(obs, defer=False):
    bases = obs["branch_specification"]["branches"]
    basis = bases[-1]["outcome"]["basis"]
    return dict(decision="submit_resolution", proposal_id=obs.get("assigned_proposal_id", "proposal_1"),
        eligibility="unresolved" if defer else "ineligible", remedy="none", workflow="manual_review" if defer else "no_mutation",
        amount=0.0, refund_method="none", payment_mutation="none", return_shipping_payer="none", policy_basis=basis, reason_code=basis)


def action(seat, obs, arm, memory):
    from .v3_lifecycle import reference, independent_action
    if arm == "reference": return reference(seat, obs)
    if arm in COMPETENT: return independent_action(seat, obs)
    if arm in ("naive", "random", "collect_all"):
        return runner.lower_action(seat, obs, arm)
    phase = obs["phase_id"]
    if seat == "policy":
        if arm in ("always_deny", "always_defer"): return _fixed_policy(obs, arm == "always_defer")
        return runner.lower_action(seat, obs, "naive")
    if seat == "intake":
        options = list(old.collection_batches(obs)) if obs["round"] < obs["collection_contract"]["max_rounds"] else []
        if arm == "always_handoff" or not options: return dict(decision="handoff")
        batch = (max(options, key=lambda r: (r[2], -r[1], r[0])) if arm == "greedy_immediate_utility"
                 else min(options, key=lambda r: (r[1], r[0])))[0]
        return dict(decision="request_facts", fact_ids=list(batch))
    if seat == "customer":
        if phase == "customer_disclosure" and arm == "record_id_or_position_cue":
            return dict(decision="disclose_facts", disclosures=[dict(fact_id=k, record_id=min(r["record_id"] for r in obs["private_records"] if r["fact_id"] == k)) for k in obs["requested_fact_ids"]])
        if phase == "customer_confirmation":
            proposal = obs["archived_proposals"][-1] if arm == "stale_proposal_confirmation" and obs["archived_proposals"] else obs["pending_proposal"]
            return dict(decision="confirm_resolution", proposal_id=proposal["proposal_id"], confirmed_terms={k: proposal[k] for k in old.TERMS})
        return reference(seat, obs)
    if arm == "ignore_redelivery_or_proposal_revision":
        if "payment" not in memory: memory["payment"] = reference(seat, obs)
        return old.plain(memory["payment"])
    p, ledger = obs["confirmed_proposal"], obs["payment_ledger"]
    result = dict(decision="no_mutation", proposal_id=p["proposal_id"], idempotency_key=ledger["idempotency_key"],
        ledger_snapshot_id=ledger.get("snapshot_id", ledger.get("ledger_snapshot_id")), amount=0.0, refund_method="none", refund_allocations=[])
    limit, caps = old.payment_safety_limits(obs)
    if arm == "always_execute":
        amount = max(1, round(p["amount"] * 100))
        destination = sorted(caps)[0] if caps else "card"
    elif limit:
        destination = sorted(caps)[0]; amount = max(1, min(limit // 2, caps[destination]))
    else: return result
    return dict(result, decision="execute_refund", amount=amount / 100, refund_method="original_payment",
                refund_allocations=[dict(instrument=destination, amount=amount / 100)])
