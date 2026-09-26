"""The world-panel gap analysis: one part per cell, split to the steps behind it, against the scripted reference."""

from __future__ import annotations

import collections
import copy
import json

import pytest

from aeread.shared_runner.run.publication import assert_public_payload
from aeread_families.datacenter_development import world_campaign
from aeread_families.datacenter_development import world_panel_gap as gap

WORLD = gap.ROOT / "cases" / "datacenter_development_v1" / "worlds_v2_holdout" / "covenant_cliff_001.json"
COUNTERPART = {"land": "landowner", "power": "utility", "epc": "contractor", "service": "customer",
               "land_amendment": "landowner", "loan": "lender"}


def _payload() -> dict:
    return json.loads(WORLD.read_text())["payload"]


def _step(i, phase, seat, action, *, valid=True, code=None, instance=None, response=None):
    step = {"step_index": i, "phase_id": phase, "seat_id": seat, "action": action,
            "phase_instance_id": instance or f"pi_{i}",
            "outcome": {"valid": valid, "failure_code": code, "status": "succeeded" if valid else "agent_action_failure"}}
    if response is not None:
        step["attempts"] = [{"response": response}]
    return step


def _negotiate(terms_by_key: dict, *, decline_amendment: bool = False, stop_after: str | None = None) -> list[dict]:
    """A trajectory in which the developer offers each agreement once, the counterparty accepts, and it signs."""

    steps: list[dict] = []
    for key in gap.SEQUENCE:
        i = len(steps)
        if key == "land_amendment" and decline_amendment:
            steps.append(_step(i, f"{key}_developer_offer", "developer", {"decision": "decline", "message": "no amendment needed", "terms": None}))
            continue
        steps.append(_step(i, f"{key}_developer_offer", "developer", {"decision": "offer", "message": "offer", "terms": terms_by_key[key]}))
        steps.append(_step(i + 1, f"{key}_{COUNTERPART[key]}_response", COUNTERPART[key], {"decision": "accept", "offer_id": f"o{i}", "message": None, "terms": None}))
        steps.append(_step(i + 2, f"{key}_developer_commit", "developer", {"decision": "sign", "offer_id": f"o{i}"}))
        if key == stop_after:
            break
    return gap.with_rounds(steps)


def _row(payload: dict, **outcome) -> dict:
    base = {"project_completed": False, "termination_reason": "invalid_action", "temporal_violations": [],
            "binding_contract_integrity": False, "project_constraints_satisfied": False, "default_reasons": [],
            "developer_equity_npv_cents": payload["outside_option"]["developer_equity_npv_cents"]}
    base.update(outcome)
    return {"cell_key": "synthetic", "status": "completed", "inclusion_status": "included", "outcome": base,
            "scripted_baseline_developer_equity_npv_cents": payload["baseline"]["developer_equity_npv_cents"],
            "outside_option_developer_equity_npv_cents": payload["outside_option"]["developer_equity_npv_cents"],
            "scores": {"developer_equity_npv": {"value": float(base["developer_equity_npv_cents"])}}}


def _executed_row(payload: dict, steps: list[dict]) -> dict:
    stack = gap.simulate(payload, gap.model_terms(gap.signed(steps)))
    admitted = stack.negotiated_constraints_satisfied
    return _row(payload, project_completed=True, termination_reason="agreement_stack_executed", binding_contract_integrity=True,
                project_constraints_satisfied=admitted, default_reasons=list(stack.project.default_reasons),
                developer_equity_npv_cents=stack.developer_equity_npv_cents)


def _scripted(payload: dict) -> dict:
    return {key: copy.deepcopy(payload["scripted_developer"][f"{key}_terms"]) for key in gap.SEQUENCE}


def _only(result: dict, component: str) -> None:
    assert result["component"] == component and result["residual"] == 0 and result["contribution_residual"] == 0
    assert {k for k, v in result["parts"].items() if v} <= {component}
    assert sum(r["amount"] for r in result["contributions"]) == result["parts"][component] == result["gap"]


# -- synthetic inputs, one per part and class ------------------------------------------------------------------------


def test_rounds_count_the_first_phase_as_it_starts() -> None:
    steps = [_step(0, "land_developer_offer", "developer", {}, instance="a"), _step(1, "land_landowner_response", "landowner", {}, instance="b"),
             _step(2, "land_developer_offer", "developer", {}, instance="c"), _step(3, "power_developer_offer", "developer", {}, instance="d")]
    assert [s["round_index"] for s in gap.with_rounds(reversed(steps))] == [0, 0, 1, 1]


def test_signing_the_reference_terms_is_admitted_at_zero_gap_with_a_row_per_agreement() -> None:
    payload = _payload()
    steps = _negotiate(_scripted(payload))
    row = _executed_row(payload, steps)
    assert world_campaign._admitted(row) and row["outcome"]["developer_equity_npv_cents"] == payload["baseline"]["developer_equity_npv_cents"]
    result = gap.analyse_cell(row, steps, payload)
    assert result["component"] == "admitted_terms" and result["gap"] == 0 and result["residual"] == 0
    assert [(r["agreement_key"], r["amount"], r["phase_id"]) for r in result["contributions"]] == [
        (key, 0, f"{key}_developer_commit") for key in gap.SEQUENCE]
    assert all("on the reference's terms" in r["note"] or "land amendment" in r["note"] for r in result["contributions"])
    assert result["instances"] == []


def test_a_dearer_epc_moves_only_the_epc_row() -> None:
    payload = _payload()
    terms = _scripted(payload)
    terms["epc"]["contract_price_cents"] += 100_000_000
    terms["epc"]["payment_schedule"][-1]["amount_cents"] += 100_000_000
    steps = _negotiate(terms)
    row = _executed_row(payload, steps)
    result = gap.analyse_cell(row, steps, payload)
    _only(result, "admitted_terms")
    moved = {r["agreement_key"]: r["amount"] for r in result["contributions"] if r["amount"]}
    assert list(moved) == ["epc"] and moved["epc"] < 0 and "contract price" in result["contributions"][2]["note"]
    assert [i["class"] for i in result["instances"]] == ["admitted_below_reference"]


def test_short_power_fails_admission_and_names_each_failing_check_at_its_agreement() -> None:
    payload = _payload()
    terms = _scripted(payload)
    terms["power"]["contracted_capacity_kw"] = 40_000
    steps = _negotiate(terms)
    row = _executed_row(payload, steps)
    assert not world_campaign._admitted(row)
    result = gap.analyse_cell(row, steps, payload)
    _only(result, "stack_failed_admission")
    assert result["gap"] == row["outside_option_developer_equity_npv_cents"] - row["scripted_baseline_developer_equity_npv_cents"]
    (only,) = result["contributions"]
    assert only["phase_id"] == "loan_developer_commit" and "power capacity covers the lease" in only["note"]
    where = {i["class"]: i["phase_id"] for i in result["instances"]}
    assert where["fails_power_capacity_covers_lease"] == "power_developer_commit"
    assert where["fails_site_control_holds_through_operations"] == "land_amendment_developer_commit"


def test_a_declined_amendment_is_its_own_row_and_class() -> None:
    payload = _payload()
    steps = _negotiate(_scripted(payload), decline_amendment=True)
    row = _executed_row(payload, steps)
    result = gap.analyse_cell(row, steps, payload)
    assert "declined_land_amendment" in {i["class"] for i in result["instances"]}
    amendment = [r for r in result["contributions"] if r["agreement_key"] == "land_amendment"]
    if result["component"] == "admitted_terms":
        assert amendment[0]["phase_id"] == "land_amendment_developer_offer" and amendment[0]["note"].startswith("declined")
    else:
        assert result["component"] == "stack_failed_admission"
    assert result["residual"] == 0 and result["contribution_residual"] == 0


def test_a_published_outcome_the_terms_do_not_reproduce_is_refused() -> None:
    payload = _payload()
    steps = _negotiate(_scripted(payload))
    row = _executed_row(payload, steps)
    row["outcome"]["developer_equity_npv_cents"] += 1
    with pytest.raises(ValueError):
        gap.analyse_cell(row, steps, payload)


def test_output_cut_off_at_the_token_cap_is_format() -> None:
    payload = _payload()
    steps = _negotiate(_scripted(payload), stop_after="service")
    steps.append(_step(len(steps), "loan_developer_offer", "developer", None, valid=False, code="malformed_json",
                       response={"truncated": True, "finish_reason": "length"}))
    steps = gap.with_rounds(steps)
    row = _row(payload, temporal_violations=["malformed_json"])
    result = gap.analyse_cell(row, steps, payload)
    _only(result, "ended_on_unparseable_action")
    assert result["contributions"][0]["step_index"] == steps[-1]["step_index"] and "token cap" in result["contributions"][0]["note"]
    assert [i["class"] for i in result["instances"]] == ["malformed_json"]


def test_a_no_op_amendment_is_procedure() -> None:
    payload = _payload()
    terms = _scripted(payload)
    steps = _negotiate(terms, stop_after="service")
    steps.append(_step(len(steps), "land_amendment_developer_offer", "developer",
                       {"decision": "offer", "message": "Reaffirming executed land terms.", "terms": terms["land"]},
                       valid=False, code="amendment_changes_nothing"))
    steps = gap.with_rounds(steps)
    result = gap.analyse_cell(_row(payload, temporal_violations=["amendment_changes_nothing"]), steps, payload)
    _only(result, "ended_on_refused_action")
    assert [i["class"] for i in result["instances"]] == ["amendment_changes_nothing"] and "Reaffirming" in result["instances"][0]["note"]


def test_a_walk_and_a_round_out_are_decisions_located_at_the_developer() -> None:
    payload = _payload()
    steps = _negotiate(_scripted(payload), stop_after="service")
    steps.append(_step(len(steps), "land_amendment_developer_offer", "developer", {"decision": "decline", "message": None, "terms": None}))
    steps.append(_step(len(steps), "loan_developer_offer", "developer", {"decision": "walk", "message": "the written advance rate cannot fund it", "terms": None}))
    steps = gap.with_rounds(steps)
    walked = gap.analyse_cell(_row(payload, termination_reason="developer_walk"), steps, payload)
    _only(walked, "ended_by_walk_or_round_limit")
    assert {i["class"] for i in walked["instances"]} == {"walked_away", "declined_land_amendment"}

    rounds = _negotiate(_scripted(payload), stop_after="land")
    power = _scripted(payload)["power"]
    for r in range(3):
        i = len(rounds)
        rounds.append(_step(i, "power_developer_offer", "developer", {"decision": "offer", "message": "offer", "terms": power}))
        rounds.append(_step(i + 1, "power_utility_response", "utility", {"decision": "counter", "offer_id": f"o{i}", "message": "no", "terms": power}))
    rounds = gap.with_rounds(rounds)
    out = gap.analyse_cell(_row(payload, termination_reason="power_negotiation_rounds_exhausted"), rounds, payload)
    _only(out, "ended_by_walk_or_round_limit")
    assert out["contributions"][0]["step_index"] == rounds[-2]["step_index"] and out["contributions"][0]["seat_id"] == "developer"
    assert [i["class"] for i in out["instances"]] == ["negotiation_rounds_exhausted"]


# -- the published bundle --------------------------------------------------------------------------------------------


def _published(label: str) -> tuple[dict, list[dict]]:
    report = json.loads((gap.OUT / "reports" / f"gap_decomposition_{label}.json").read_text())
    table = [json.loads(line) for line in (gap.OUT / report["contributions"]["table"]).read_text().splitlines()]
    return report, table


@pytest.mark.parametrize("label,campaign", gap.REPORTS)
def test_published_parts_sum_to_the_published_endpoint_per_cell(label: str, campaign: str) -> None:
    report, _ = _published(label)
    lines = (gap.EVIDENCE / campaign / "tables" / "cells.jsonl").read_text().splitlines()
    rows = {r["receipt_sha256"]: r for r in (json.loads(line) for line in lines)}
    left = [c for c in report["cell_parts"] if c["side"] == "left"]
    right = [c for c in report["cell_parts"] if c["side"] == "right"]
    assert len(left) == len(rows) == 72 and len(right) == 24 == report["paired_worlds"]
    for cell in left:
        row = rows[cell["receipt_sha256"]]
        endpoint = world_campaign._economic_value(row) - row["scripted_baseline_developer_equity_npv_cents"]
        assert sum(cell["parts"].values()) == pytest.approx(endpoint / gap.MILLION, abs=1e-6)
    assert all(set(c["parts"].values()) == {0.0} for c in right)
    assert {c["receipt_sha256"] for c in right} == {r["case_sha256"] for r in rows.values()}
    summary = json.loads((gap.EVIDENCE / campaign / "reports" / "summary.json").read_text())
    assert report["realized"]["difference"] == pytest.approx(summary["leaderboard"][0]["mean_delta_from_baseline_cents"] / gap.MILLION, abs=1e-5)
    assert sum(c["difference"] for c in report["components"]) == pytest.approx(report["realized"]["difference"], abs=1e-5)
    assert report["accounting_check"]["max_abs_residual_per_cell"] == 0 == report["accounting_check"]["max_abs_contribution_residual"]


@pytest.mark.parametrize("label,campaign", gap.REPORTS)
def test_every_row_and_instance_lands_on_the_step_it_describes(label: str, campaign: str) -> None:
    report, table = _published(label)
    assert len(table) == report["contributions"]["rows"]
    steps = {}
    for line in (gap.EVIDENCE / campaign / "trajectories" / "sanitized.jsonl").read_text().splitlines():
        s = json.loads(line)
        steps.setdefault(s["source_receipt_sha256"], []).append(s)
    grain = {receipt: {s["step_index"]: s for s in gap.with_rounds(rows)} for receipt, rows in steps.items()}
    violation = {}
    for line in (gap.EVIDENCE / campaign / "tables" / "cells.jsonl").read_text().splitlines():
        cell = json.loads(line)
        violation[cell["receipt_sha256"]] = (cell["outcome"]["temporal_violations"] or [None])[0]
    sums: collections.Counter = collections.Counter()
    for r in table:
        s = grain[r["receipt_sha256"]][r["step_index"]]
        assert (s["phase_id"], s["seat_id"], s["round_index"]) == (r["phase_id"], r["seat_id"], r["round_index"])
        action, outcome = s["action"] or {}, s["outcome"]
        if r["component"] == "admitted_terms":
            assert s["phase_id"].startswith(r["agreement_key"] + "_developer_")
            assert action["decision"] == ("decline" if s["phase_id"].endswith("_offer") else "sign")
        elif r["component"] == "stack_failed_admission":
            assert s["phase_id"] == "loan_developer_commit" and action["decision"] == "sign"
        elif r["component"] in ("ended_on_unparseable_action", "ended_on_refused_action"):
            assert outcome["valid"] is False and outcome["failure_code"] == violation[r["receipt_sha256"]]
            assert (outcome["failure_code"] in gap.PARSE_FAILURES) == (r["component"] == "ended_on_unparseable_action")
            assert max(grain[r["receipt_sha256"]]) == r["step_index"]
        else:
            assert r["component"] == "ended_by_walk_or_round_limit" and s["seat_id"] == "developer"
            if action["decision"] == "offer":  # a round-out: the developer's last offer on that agreement
                later = [t for t in grain[r["receipt_sha256"]].values() if t["step_index"] > r["step_index"] and t["phase_id"] == s["phase_id"]]
                assert not later and s["phase_id"].endswith("_developer_offer")
            else:
                assert action["decision"] == "walk" and max(grain[r["receipt_sha256"]]) == r["step_index"]
        sums[(r["receipt_sha256"], r["component"])] += r["amount"]
    for cell in report["cell_parts"]:
        for key, value in cell["parts"].items():
            assert sums[(cell["receipt_sha256"], key)] == pytest.approx(value, abs=1e-6)
    for i in report["instances"]:
        s = grain[i["receipt_sha256"]][i["step_index"]]
        assert (s["phase_id"], s["seat_id"], s["round_index"]) == (i["phase_id"], i["seat_id"], i["round_index"])


def test_the_published_check_classes_match_the_campaign_labels() -> None:
    for label, campaign in gap.REPORTS:
        report, _ = _published(label)
        summary = json.loads((gap.EVIDENCE / campaign / "reports" / "summary.json").read_text())["model_summaries"][0]
        count = {c["key"]: c["left_count"] for c in report["classes"]}
        assert count["fails_financing_funded"] == summary["exclusion_reasons"].get("constraint_failure:funding_shortfall", 0)
        failed = next(c["cells"] for c in report["components"] if c["key"] == "stack_failed_admission")
        assert failed == sum(v for k, v in summary["exclusion_reasons"].items() if k.startswith("constraint_failure:"))
        assert report["stack_replay"]["reproduced"] == report["stack_replay"]["executed_stacks"]


def test_the_bundle_regenerates_and_carries_no_prohibited_text() -> None:
    assert gap.check()
    for path in [*sorted(gap.OUT.rglob("*")), gap.ROOT / "src" / "aeread_families" / "datacenter_development" / "world_panel_gap.py",
                 gap.ROOT / "tests" / "test_datacenter_world_panel_gap.py"]:
        if path.is_file():
            assert_public_payload(str(path.name), path.read_bytes())
