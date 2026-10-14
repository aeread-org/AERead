"""Refund V2.5 lower controls and the declared beatability rule (QC Gate 3)."""
import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.refund import v2_5_controls as controls
from aeread_families.refund import v2_5_release as release

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "cases" / "refund_v25" / "qc" / "lower_controls.json"
PROFILE = ROOT / "docs" / "families" / "refund" / "qc.md"


def _rows(seat, cohort, control, values):
    return [{"seat": seat, "cohort": cohort, "control": control, "case_id": f"case_{i}",
             "end_to_end": e2e, "policy_semantic": sem} for i, (e2e, sem) in enumerate(values)]


def test_rule_is_the_declared_identity():
    rule = controls.RULE
    assert rule.rule_id == "refund_v25_beatability/1"
    assert (rule.end_to_end_margin, rule.policy_semantic_margin, rule.max_reach_share) == (0.50, 0.25, 0.10)
    assert rule.policy_semantic_seats == ("policy",)
    assert set(controls.CONTROLS) == {"customer", "intake", "policy", "payments"}


def test_rule_passes_a_floor_control_and_fails_each_clause_separately():
    reference = _rows("policy", "c", "reference", [(1.0, 1.0)] * 20)
    floor = _rows("policy", "c", "floor", [(0.0, 0.0)] * 20)
    assert controls.evaluate_rule(reference + floor)["passes"]
    # B3 alone: 3 of 20 reached (15% > 10%), e2e gap 0.85, semantic gap 0.85.
    reach = _rows("policy", "c", "reach", [(1.0, 1.0)] * 3 + [(0.0, 0.0)] * 17)
    verdict = controls.evaluate_rule(reference + reach)
    clauses = verdict["verdicts"][0]["controls"][0]["clauses"]
    assert not verdict["passes"]
    assert [k for k, v in clauses.items() if not v["holds"]] == ["B3_reach_share"]
    assert clauses["B3_reach_share"]["reached_case_ids"] == ["case_0", "case_1", "case_2"]
    # B2 alone: no case reached, but the semantic content is mostly right.
    semantic = _rows("policy", "c", "semantic", [(0.0, 0.9)] * 20)
    clauses = controls.evaluate_rule(reference + semantic)["verdicts"][0]["controls"][0]["clauses"]
    assert [k for k, v in clauses.items() if not v["holds"]] == ["B2_policy_semantic_margin"]
    # B1 fails with B3 whenever more than half the strict trajectories pass.
    half = _rows("policy", "c", "half", [(1.0, 0.0)] * 11 + [(0.0, 0.0)] * 9)
    clauses = controls.evaluate_rule(reference + half)["verdicts"][0]["controls"][0]["clauses"]
    assert {k for k, v in clauses.items() if not v["holds"]} == {"B1_end_to_end_margin", "B3_reach_share"}


def test_rule_margins_are_inclusive_at_the_declared_threshold():
    reference = _rows("policy", "c", "reference", [(1.0, 1.0)] * 20)
    edge = _rows("policy", "c", "edge", [(1.0, 1.0)] * 2 + [(0.5, 0.75)] * 18)
    # e2e gap = 1 - (2 + 9) / 20 = 0.45 < 0.5, so B1 fails; reach 2/20 = 0.10 holds.
    clauses = controls.evaluate_rule(reference + edge)["verdicts"][0]["controls"][0]["clauses"]
    assert not clauses["B1_end_to_end_margin"]["holds"]
    assert clauses["B3_reach_share"]["holds"]
    exact = _rows("policy", "c", "exact", [(0.5, 0.75)] * 20)
    clauses = controls.evaluate_rule(reference + exact)["verdicts"][0]["controls"][0]["clauses"]
    assert clauses["B1_end_to_end_margin"]["holds"] and clauses["B2_policy_semantic_margin"]["holds"]


def test_small_cohort_allows_no_reached_case():
    reference = _rows("payments", "tiny", "reference", [(1.0, 1.0)] * 4)
    one = _rows("payments", "tiny", "one", [(1.0, 1.0)] + [(0.0, 1.0)] * 3)
    verdict = controls.evaluate_rule(reference + one)
    assert not verdict["passes"]
    assert verdict["failing_cohorts"] == [{"seat": "payments", "cohort": "tiny", "failing_controls": ["one"]}]
    # policy_semantic is the scripted counterpart's outside the policy seat: not a clause.
    assert "B2_policy_semantic_margin" not in verdict["verdicts"][0]["controls"][0]["clauses"]


def test_a_reference_failure_counts_as_reached():
    reference = _rows("policy", "c", "reference", [(0.0, 1.0)] + [(1.0, 1.0)] * 19)
    floor = _rows("policy", "c", "floor", [(0.0, 0.0)] * 20)
    clauses = controls.evaluate_rule(reference + floor)["verdicts"][0]["controls"][0]["clauses"]
    assert clauses["B3_reach_share"]["reached_case_ids"] == ["case_0"]


def test_mutation_a_control_that_copies_the_reference_fails_the_rule():
    reference = _rows("policy", "c", "reference", [(1.0, 1.0)] * 20)
    copy = [{**row, "control": "copy_reference"} for row in reference]
    verdict = controls.evaluate_rule(reference + copy)
    assert not verdict["passes"]
    assert all(not clause["holds"] for clause in verdict["verdicts"][0]["controls"][0]["clauses"].values())


@pytest.mark.parametrize("broken", ["no_reference", "no_control", "case_mismatch", "duplicate"])
def test_incomparable_screens_raise_instead_of_returning_a_verdict(broken):
    reference = _rows("policy", "c", "reference", [(1.0, 1.0)] * 3)
    floor = _rows("policy", "c", "floor", [(0.0, 0.0)] * 3)
    rows = {"no_reference": floor, "no_control": reference, "case_mismatch": reference + floor[:2],
            "duplicate": reference + floor + floor[:1]}[broken]
    with pytest.raises(ValueError):
        controls.evaluate_rule(rows)


# --- Controls played through the real environment and verifier ------------


@pytest.mark.parametrize("cohort", ["core", "v3_intake", "v4_payments", "v51_payments"])
def test_controls_play_exactly_the_release_panel_under_their_own_identity(cohort):
    reference = controls.build_setup(cohort, "policy")
    assert reference.plan.run_plan_id == release.build_setup(cohort, "policy", 301).plan.run_plan_id
    control = controls.build_setup(cohort, "policy", control="random_legal_0")
    assert [(c.case_id, c.content_sha256) for c in control.plan.cases] == \
        [(c.case_id, c.content_sha256) for c in reference.plan.cases]
    assert control.plan.run_plan_id != reference.plan.run_plan_id
    assert all(p.model.provider == "scripted" for p in control.plan.agent_profiles)
    active = [p for p in control.plan.agent_profiles if p.model.model == controls.control_model("random_legal_0")]
    assert len(active) == 1 and active[0].profile_id.startswith("refund_v25_policy_")
    assert active[0].model.revision == controls.CONTROL_REVISION


def test_undeclared_controls_are_refused():
    with pytest.raises(ValueError):
        controls.ControlProvider(seat="payments", control="naive_full_refund", base=None)


@pytest.fixture(scope="module")
def record():
    return json.loads(RECORD.read_bytes())


@pytest.fixture(scope="module")
def played(tmp_path_factory):
    root = tmp_path_factory.mktemp("refund_v25_controls")
    return {name: asyncio.run(controls.run_group(root / name, "core", "policy", name))
            for name in ("reference", "random_legal_0", "copy_reference")}


def _stored(record, seat, cohort, control):
    return next(g for g in record["groups"] if (g["seat"], g["cohort"], g["control"]) == (seat, cohort, control))


def test_random_control_is_deterministic_under_its_seed_and_changes_with_it(played, record):
    fresh = dict(played["random_legal_0"])
    assert fresh.pop("case_ids") == record["case_ids"]["core"]
    # The committed bytes came from a separate full-screen process.
    assert canonical_json_bytes(fresh) == canonical_json_bytes(_stored(record, "policy", "core", "random_legal_0"))
    seeds = [_stored(record, "policy", "core", f"random_legal_{seed}")["leaves"] for seed in controls.RANDOM_SEEDS]
    assert seeds[0] != seeds[1] != seeds[2]


def test_random_control_emits_only_legal_actions(played):
    assert played["random_legal_0"]["active_invalid_cases"] == 0
    assert played["random_legal_0"]["mean"]["end_to_end"] < 1


def test_mutation_illegal_random_requests_are_detected(tmp_path, monkeypatch):
    original = controls._policy_action

    def tampered(control, observation):
        action = original(control, observation)
        if action["decision"] == "request_facts":
            action["requested_fact_ids"] = ["not_a_pending_fact"]
        return action

    monkeypatch.setattr(controls, "_policy_action", tampered)
    group = asyncio.run(controls.run_group(tmp_path / "tampered", "core", "policy", "random_legal_0"))
    assert group["active_invalid_cases"] > 0
    with pytest.raises(AssertionError, match="legal-only"):
        controls.record_from_groups([group])


def test_mutation_copying_the_reference_fails_the_rule_on_real_trajectories(played):
    reference, copy = played["reference"], played["copy_reference"]
    assert reference["leaves"] == copy["leaves"]
    verdict = controls.evaluate_rule(controls.rows_from_groups([reference, copy]))
    assert not verdict["passes"]
    clauses = verdict["verdicts"][0]["controls"][0]["clauses"]
    assert set(clauses) == {"B1_end_to_end_margin", "B2_policy_semantic_margin", "B3_reach_share"}
    assert not any(clause["holds"] for clause in clauses.values())


# --- The committed screen record -------------------------------------------

def test_record_is_bound_to_the_current_controls_and_complete(record):
    source = (ROOT / "src" / "aeread_families" / "refund" / "v2_5_controls.py").read_bytes()
    assert record["controls_source_sha256"] == hashlib.sha256(source).hexdigest()
    assert record["paid_calls"] == 0 and record["seed"] == controls.SCREEN_SEED
    expected = {(seat, cohort, control) for seat in release.ROLES for cohort in release.PANELS
                for control in (controls.REFERENCE, *controls.CONTROLS[seat])}
    assert {(g["seat"], g["cohort"], g["control"]) for g in record["groups"]} == expected
    for group in record["groups"]:
        n = len(record["case_ids"][group["cohort"]])
        assert group["cases"] == n and all(len(v) == n for v in group["leaves"].values())
        if group["control"] == controls.REFERENCE:
            assert all(v == 1.0 for v in group["mean"].values()) and group["active_invalid_cases"] == 0
        if group["control"] in controls.LEGAL_ONLY:
            assert group["active_invalid_cases"] == 0


def test_record_verdict_follows_from_its_rows_and_is_reported(record):
    rows = controls.rows_from_groups(record["groups"], record["case_ids"])
    recomputed = controls.evaluate_rule(rows)
    assert json.loads(canonical_json_bytes(recomputed)) == record["verdict"]
    text = PROFILE.read_text(encoding="utf-8")
    assert controls.RULE_ID in text
    # The profile's result table states every seat's verdict on every cohort.
    header = "| Cohort | n | Policy | Customer | Intake | Payments |"
    assert header in text
    table = {}
    for line in text.split(header, 1)[1].splitlines()[2:]:
        if not line.startswith("| `"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        table[cells[0].strip("`")] = dict(zip(("n", "policy", "customer", "intake", "payments"), cells[1:]))
    assert set(table) == set(release.PANELS)
    for verdict in record["verdict"]["verdicts"]:
        row = table[verdict["cohort"]]
        assert row["n"] == str(verdict["cases"])
        assert row[verdict["seat"]].startswith("pass" if verdict["passes"] else "fail"), (verdict["seat"], verdict["cohort"])


def test_record_regenerates_byte_for_byte_on_one_cohort(record, tmp_path):
    stored = {(g["seat"], g["control"]): g for g in record["groups"] if g["cohort"] == "v4_customer"}
    for seat in ("policy", "payments"):
        for control in (controls.REFERENCE, *controls.CONTROLS[seat]):
            group = asyncio.run(controls.run_group(tmp_path / seat / control, "v4_customer", seat, control))
            assert group.pop("case_ids") == record["case_ids"]["v4_customer"]
            assert canonical_json_bytes(group) == canonical_json_bytes(stored[(seat, control)])
