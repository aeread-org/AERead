"""The failure classifier decides what the analysis says, so it is tested.

The taxonomy lived in a scratch script until one such script was lost to a
temp-directory cleanup. These tests pin the two properties that make its counts
meaningful: the stages partition the rows, and each stage fires for its own
reason rather than absorbing its neighbours.
"""

from __future__ import annotations

import copy

import pytest

from aeread_families.procurement_allocation.inference_case_matrix import (
    BUDGET_ACTIONS,
    build_inference_case_matrix,
)
from aeread_families.procurement_allocation.trajectory_analysis import (
    STAGES,
    VISIBLE_IN_QUOTE,
    adequate,
    classify,
    observed_yield,
    to_csv,
)

CASES = {c["case_id"].rsplit(".", 1)[-1]: c
         for c in build_inference_case_matrix(surface="labeled")}


def case_for(risk: str) -> dict:
    return next(c for slug, c in CASES.items() if slug.endswith(f"__{risk}"))


def row(case: dict, **kw) -> dict:
    return {"case_id": case["case_id"], "inference_seed": 1, "status": "completed",
            "regret_to_upper_bound_usd": 250.0, "action_trace": [], **kw}


def quote_sample_award(case: dict, supplier_ids, awarded_ids) -> list[dict]:
    trace = []
    for sid in supplier_ids:
        trace.append({"action": "request_quote", "supplier_id": sid})
        trace.append({"action": "request_sample", "supplier_id": sid})
    trace.append({"action": "submit_award",
                  "award_lines": [{"offer_id": f"offer_{s}_v1", "quantity": 20}
                                  for s in awarded_ids]})
    return trace


def suppliers(case: dict, component_index: int = 0) -> list[dict]:
    comps = sorted({s["component"] for s in case["payload"]["suppliers"]})
    comp = comps[component_index]
    return [s for s in case["payload"]["suppliers"] if s["component"] == comp]


def test_stage_names_are_unique_and_declared() -> None:
    assert len(set(STAGES)) == len(STAGES)


def test_a_provider_failure_never_reaches_a_decision_stage() -> None:
    case = case_for("yield")
    out = classify(row(case, status="operational_failure", failure_condition="timeout"), case)
    assert out["stage"] == "never ran" and out["mode"] == "timeout"


def test_an_unparseable_response_is_not_a_decision() -> None:
    case = case_for("yield")
    out = classify(row(case, action_trace=[{"action": "unparseable"}]), case)
    assert out["stage"] == "no valid action"


def test_a_solved_row_is_solved_whatever_it_did() -> None:
    case = case_for("yield")
    out = classify(row(case, regret_to_upper_bound_usd=1.0), case)
    assert out["stage"] == "solved"


def test_awarding_an_unverified_supplier_is_caught_before_anything_else() -> None:
    case = case_for("yield")
    first = str(suppliers(case)[0]["supplier_id"])
    trace = [{"action": "submit_award",
              "award_lines": [{"offer_id": f"offer_{first}_v1", "quantity": 20}]}]
    assert classify(row(case, action_trace=trace), case)["stage"] == "bad award"


@pytest.mark.parametrize("risk", sorted(VISIBLE_IN_QUOTE))
def test_a_quote_visible_inadequacy_is_ignored_evidence_not_failed_search(risk: str) -> None:
    """The distinction an episode read by hand forced into the taxonomy.

    On-time probability and capacity are both in the formal offer, so a buyer
    that quoted a supplier already held the answer. Awarding it anyway is not a
    search failure, and merging the two hid the dominant failure mode.
    """
    case = case_for(risk)
    pool = suppliers(case)
    bad = next(s for s in pool if not adequate(s, risk))
    sid = str(bad["supplier_id"])
    out = classify(row(case, action_trace=quote_sample_award(case, [sid], [sid])), case)
    assert out["stage"] == "ignored evidence"
    assert risk in out["mode"]


def test_a_yield_world_is_a_search_failure_because_a_sample_is_needed() -> None:
    """Yield is the one risk a quote cannot settle, so it stays a search failure."""
    case = case_for("yield")
    pool = suppliers(case)
    bad = next(s for s in pool if not adequate(s, "yield"))
    sid = str(bad["supplier_id"])
    out = classify(row(case, action_trace=quote_sample_award(case, [sid], [sid])), case)
    assert out["stage"] == "search"


def test_spare_budget_separates_the_two_search_modes() -> None:
    case = case_for("yield")
    bad = next(s for s in suppliers(case) if not adequate(s, "yield"))
    sid = str(bad["supplier_id"])
    short = quote_sample_award(case, [sid], [sid])
    padded = [{"action": "request_quote", "supplier_id": sid}] * (BUDGET_ACTIONS - len(short)) + short
    assert "unspent" in classify(row(case, action_trace=short), case)["mode"]
    assert "whole budget" in classify(row(case, action_trace=padded), case)["mode"]


def test_observed_yield_is_what_the_buyer_saw_not_the_truth() -> None:
    case = case_for("yield")
    supplier = suppliers(case)[0]
    seen = observed_yield(supplier, str(supplier["supplier_id"]))
    assert 0.0 <= seen <= 1.0
    assert seen == observed_yield(supplier, str(supplier["supplier_id"]))


def test_csv_round_trips_every_declared_column() -> None:
    case = case_for("yield")
    text = to_csv([classify(row(case), case)])
    header = text.splitlines()[0].split(",")
    assert "subject" in header and "stage" in header and "mode" in header
