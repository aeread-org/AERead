"""Lower controls and the declared beatability rule for Refund V2.5 (QC Gate 3).

This is a new module on purpose. Every V2.5 module whose bytes a run plan
pins (``v2_5_runner``, ``v2_5_policy``, ``v2_5_measurement``,
``v2_5_branches``, ``v2_4_cases``, ``v2_4_reference``,
``v2_5_collection_budget``, ``v2_5_seat_cases``, ``v2_5_seat_design_v3``,
``v2_5_seat_extension_v4``, ``v2_5_seat_extension_v5``,
``v2_5_payment_units_v51``) is left byte-identical, so no reference plan
identity moves. ``v2_5_release`` is reused, not edited.

The rule below was declared and committed on 2026-10-13 before any control
was executed on any case. A changed threshold or clause is a new ``RULE_ID``;
the verdict under the old identity stays recorded.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

RULE_ID = "refund_v25_beatability/1"
CONTROLS_VERSION = "refund_v25_lower_controls/1"
SCREEN_SEED = 301
REFERENCE = "reference"
RANDOM_SEEDS = (0, 1, 2)

# Lower controls declared per active seat. The reference is the release's
# deterministic profile for that seat; every other seat stays the release's
# scripted counterpart, exactly as in a controlled comparison run.
CONTROLS: Mapping[str, tuple[str, ...]] = {
    "policy": ("refuse_empty", "noop_null_resolution", "naive_full_refund",
               *(f"random_legal_{seed}" for seed in RANDOM_SEEDS)),
    "customer": ("refuse_empty", "naive_overdisclose", "naive_first_record"),
    "intake": ("refuse_empty", "naive_first_sorted"),
    "payments": ("refuse_empty", "naive_no_mutation"),
}

CONTROL_DESCRIPTIONS: Mapping[str, str] = {
    "refuse_empty": "Returns an empty JSON object on every turn: no decision at all.",
    "noop_null_resolution": "Policy, first turn: submits the null resolution (unresolved, no remedy, no_mutation, amount 0, no payment, payer none, rule NO_DECISION) without collecting a fact.",
    "naive_full_refund": "Policy, first turn: submits a full refund (eligible, full_refund, execute_refund, item_net_price + allocated_tax, original_payment, execute, seller) citing the first public full-refund rule ID, without collecting a fact.",
    "random_legal": "Policy, seeded: requests a uniformly random nonempty subset (at most 3) of the facts the public branch specification lists as pending; once none are pending, submits a uniformly random canonical resolution (amount from {0, item_net_price, item_net_price + allocated_tax}, rule ID from the public catalogue, reason_code = policy_basis) that satisfies the environment's legality guard. Draws are keyed by seed and the canonical observation.",
    "naive_overdisclose": "Customer: the reference at claim and confirmation; at disclosure reveals every private fact it holds instead of the requested ones.",
    "naive_first_record": "Customer: the reference at claim and confirmation; at disclosure reveals exactly the requested IDs, each valued from the flat private_facts map or else the first listed record for that fact, ignoring document, revision and revocation.",
    "naive_first_sorted": "Intake: requests the first min(3, n) undisclosed available fact IDs in sorted order, ignoring the routing plan and collection contract.",
    "naive_no_mutation": "Payments: always no_mutation with amount 0, method none and no allocations, echoing proposal, idempotency and snapshot IDs; never reads the ledger amounts.",
}


@dataclass(frozen=True, slots=True)
class BeatabilityRule:
    """The reference must beat every lower control on every public cohort.

    For each screened seat and cohort, and for each declared control K:

    * B1: mean(reference end_to_end) - mean(K end_to_end) >= end_to_end_margin.
    * B2: mean(reference policy_semantic) - mean(K policy_semantic)
      >= policy_semantic_margin, for seats in ``policy_semantic_seats`` only.
      Other seats do not produce the policy resolution, so their
      policy_semantic is the scripted policy counterpart's.
    * B3: the share of cases where K's end_to_end reaches the reference's
      (K >= reference on that case) is at most ``max_reach_share``. With fewer
      than ten cases this allows no reached case at all.

    A cohort passes for a seat only if every clause holds for every control.
    A failing cohort is a finding about the cohort (a control without the
    judgment reaches the reference), never a reason to retune the rule.
    """

    rule_id: str
    end_to_end_margin: float
    policy_semantic_margin: float
    max_reach_share: float
    policy_semantic_seats: tuple[str, ...]


RULE = BeatabilityRule(
    rule_id=RULE_ID,
    end_to_end_margin=0.50,
    policy_semantic_margin=0.25,
    max_reach_share=0.10,
    policy_semantic_seats=("policy",),
)

_TOLERANCE = 1e-9


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return math.fsum(values) / len(values)


def evaluate_rule(rows: Iterable[Mapping[str, Any]], rule: BeatabilityRule = RULE) -> dict[str, Any]:
    """Apply ``rule`` to per-case rows with seat, cohort, control, case_id and leaves.

    Raises when a group has no reference, no control, a duplicated case or a
    control whose case set differs from the reference's: a screen that cannot
    be compared must not produce a verdict.
    """
    groups: dict[tuple[str, str], dict[str, dict[str, Mapping[str, Any]]]] = {}
    for row in rows:
        cases = groups.setdefault((row["seat"], row["cohort"]), {}).setdefault(row["control"], {})
        if row["case_id"] in cases:
            raise ValueError(f"duplicate case {row['case_id']} for {row['seat']}/{row['cohort']}/{row['control']}")
        cases[row["case_id"]] = row
    if not groups:
        raise ValueError("no rows to evaluate")
    verdicts = []
    for (seat, cohort), by_control in sorted(groups.items()):
        reference = by_control.get(REFERENCE)
        if not reference:
            raise ValueError(f"{seat}/{cohort}: no reference rows")
        controls = sorted(name for name in by_control if name != REFERENCE)
        if not controls:
            raise ValueError(f"{seat}/{cohort}: no control rows")
        case_ids = sorted(reference)
        n = len(case_ids)
        ref_e2e = _mean(reference[c]["end_to_end"] for c in case_ids)
        ref_sem = _mean(reference[c]["policy_semantic"] for c in case_ids)
        results = []
        for name in controls:
            rows_k = by_control[name]
            if set(rows_k) != set(case_ids):
                raise ValueError(f"{seat}/{cohort}/{name}: case set differs from the reference")
            e2e_gap = ref_e2e - _mean(rows_k[c]["end_to_end"] for c in case_ids)
            reached = sorted(c for c in case_ids if rows_k[c]["end_to_end"] >= reference[c]["end_to_end"])
            share = len(reached) / n
            clauses = {
                "B1_end_to_end_margin": {"value": round(e2e_gap, 6), "threshold": rule.end_to_end_margin,
                                         "holds": e2e_gap >= rule.end_to_end_margin - _TOLERANCE},
                "B3_reach_share": {"value": round(share, 6), "threshold": rule.max_reach_share,
                                   "holds": share <= rule.max_reach_share + _TOLERANCE, "reached_case_ids": reached},
            }
            if seat in rule.policy_semantic_seats:
                sem_gap = ref_sem - _mean(rows_k[c]["policy_semantic"] for c in case_ids)
                clauses["B2_policy_semantic_margin"] = {"value": round(sem_gap, 6), "threshold": rule.policy_semantic_margin,
                                                        "holds": sem_gap >= rule.policy_semantic_margin - _TOLERANCE}
            clauses = dict(sorted(clauses.items()))
            results.append({"control": name, "holds": all(c["holds"] for c in clauses.values()), "clauses": clauses})
        failing = [r["control"] for r in results if not r["holds"]]
        verdicts.append({"seat": seat, "cohort": cohort, "cases": n, "passes": not failing,
                         "failing_controls": failing, "controls": results})
    return {
        "rule": asdict(rule),
        "passes": all(v["passes"] for v in verdicts),
        "failing_cohorts": [{"seat": v["seat"], "cohort": v["cohort"], "failing_controls": v["failing_controls"]}
                            for v in verdicts if not v["passes"]],
        "verdicts": verdicts,
    }
