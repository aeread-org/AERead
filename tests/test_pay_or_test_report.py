"""The pay-or-test report on the rows that crashed it: a one-world gate, and an episode a rejected action ended.

Both rows are built here the way ``model_campaign._public_action_trace`` writes
them, so the tests need no run root. The rejected row is the GPT-6 Luna gate of
2026-10-13 (P-T-15): a first ``request_quote`` the family parser rejected for a
null ``message``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "tools" / "cli_subjects"))

import pay_or_test_report as report  # noqa: E402
from aeread_families.procurement_allocation import pay_or_test_reference as reference  # noqa: E402

GATE_WORLD = "test_cheapest__tight__1"


@pytest.fixture(scope="module")
def pack():
    manifest, payloads = report.load_pack()
    world = next(w for w in manifest["worlds"] if w["slug"] == GATE_WORLD)
    return manifest, payloads, world, payloads[world["case_id"]]


def _public(actions: list[dict], statuses: list[str]) -> list[dict]:
    """Wire actions as the public trace keeps them: no message, reason or inquiry fields."""
    return [{"ordinal": i, "status": status, "action": a["action"],
             **{k: a[k] for k in ("supplier_id", "offer_id", "proposal", "award_lines") if a.get(k) not in (None, [], {})}}
            for i, (a, status) in enumerate(zip(actions, statuses), start=1)]


def _row(world: dict, trace: list[dict], *, margin: float, termination: str, decision: str) -> dict:
    return {"case_id": world["case_id"], "status": "completed", "action_trace": trace, "termination_reason": termination,
            "decision": decision, "feasible_award": decision == "award", "contribution_margin_usd": margin,
            "regret_to_upper_bound_usd": 0.0, "cost_usd": 0.001, "elapsed_seconds": 1.0}


def _write_gate(runs: Path, subject: str, rows: list[dict]) -> Path:
    root = runs / f"pay_or_test_v1_finalquotes_{subject}_gate_v1"
    root.mkdir(parents=True)
    (root / "summary.json").write_text(json.dumps({"plan": {"campaign_id": subject, "model": subject}, "halted": None,
                                                   "rows": rows}), encoding="utf-8")
    return root


def _best_row(world: dict, payload: dict) -> dict:
    actions = reference.play(payload)
    ref = reference.Reference(payload)
    margin = reference.final_margin(ref, reference.run(payload, actions))
    return _row(world, _public(actions, ["succeeded"] * len(actions)), margin=margin, termination="submitted", decision="award")


def _rejected_first_quote(world: dict) -> dict:
    newcomer = world["cheapest_newcomer"]
    trace = [{"ordinal": 1, "status": "agent_action_failure", "action": "request_quote", "supplier_id": newcomer}]
    return _row(world, trace, margin=-600.0, termination="invalid_action", decision="failed")


def test_a_one_world_gate_with_no_pay_world_is_summarized(tmp_path: Path, pack) -> None:
    manifest, payloads, world, payload = pack
    _write_gate(tmp_path, "best", [_best_row(world, payload)])
    assert report.main([str(tmp_path), "--gate", "--json", str(tmp_path / "out.json")]) == 0
    out = json.loads((tmp_path / "out.json").read_text())["report"]
    summary = out["subjects"]["best_gate_v1"]
    assert summary["worlds"] == 1 and summary["decision_loss_usd"]["mean"] < report.SMALL_USD
    assert summary["pay_worlds"] == {"n": 0, "paid_without_testing": 0, "decision_loss_usd": None}
    assert summary["test_worlds"]["n"] == 1
    assert all(rule["pay_worlds"] is None and rule["test_worlds"] is not None for rule in out["rules_on_the_same_worlds"].values())


def test_a_rejected_first_action_is_priced_as_walking_away(pack) -> None:
    _, payloads, world, payload = pack
    row = _rejected_first_quote(world)
    scored, margin = report.score_trace(payload, row)
    ref = reference.Reference(payload)
    best = ref.value(*ref.start())
    assert margin == ref.defer_value == row["contribution_margin_usd"]
    assert scored["decision_loss_usd"] == pytest.approx(best - ref.defer_value, abs=1e-4)
    assert scored["loss_by_part_usd"]["walk_away"] == pytest.approx(best - ref.defer_value, abs=1e-4)
    assert sum(scored["loss_by_part_usd"].values()) == pytest.approx(scored["decision_loss_usd"], abs=1e-3)
    (step,) = scored["steps"]
    assert step["rejected"] is True and step["valid"] is False and step["action"] == "request_quote"
    # Re-played with its message filled in, the same quote would have succeeded: the crash this replaces.
    replayed = reference.score_actions(payload, row["action_trace"])
    assert replayed["outcome"] is None and replayed["steps"][0]["valid"] is True


def test_the_rejected_gate_runs_through_the_report(tmp_path: Path, pack) -> None:
    manifest, payloads, world, payload = pack
    root = _write_gate(tmp_path, "rejected", [_rejected_first_quote(world)])
    scored = report.score_run(root, manifest, payloads)
    (w,) = scored["worlds"]
    assert w["rejected_action"] == "request_quote" and w["newcomers_touched"] == 0 and w["requests"] == 0
    assert w["paid_without_testing"] is True and w["first_newcomer"] is None
    assert "[REJECTED]" in w["trace"]
    summary = report.summarize(scored)
    assert summary["rejected_actions"] == {"worlds": 1, "by_action": {"request_quote": 1}}
    assert summary["loss_by_part_usd"]["walk_away"] == summary["decision_loss_usd"]["mean"]


def test_a_rejection_after_executed_steps_keeps_their_cost_and_loss(pack) -> None:
    _, _, world, payload = pack
    newcomer = world["cheapest_newcomer"]
    executed = [{"action": "request_quote", "supplier_id": newcomer, "message": "quote"}]
    trace = _public(executed, ["succeeded"]) + [
        {"ordinal": 2, "status": "agent_action_failure", "action": "request_sample", "supplier_id": newcomer}]
    ref = reference.Reference(payload)
    state = reference.run(payload, executed)
    row = _row(world, trace, margin=ref.defer_value - state["information_cost_usd"], termination="invalid_action",
               decision="failed")
    scored, margin = report.score_trace(payload, row)
    assert margin == row["contribution_margin_usd"] < ref.defer_value
    prefix = reference.score_actions(payload, executed)
    status, left, day = ref.status_of(state), ref.max_actions - state["actions_used"], state["elapsed_days"]
    assert scored["steps"][:-1] == prefix["steps"] and scored["requests"] == 1
    assert scored["steps"][-1]["loss_usd"] == pytest.approx(ref.value(status, left, day) - ref.defer_value, abs=1e-4)
    assert scored["decision_loss_usd"] == pytest.approx(prefix["decision_loss_usd"] + scored["steps"][-1]["loss_usd"], abs=1e-3)


@pytest.mark.parametrize("termination", ["submitted", "invalid_action"])
def test_a_rejection_that_did_not_end_the_episode_is_refused(pack, termination: str) -> None:
    _, _, world, payload = pack
    newcomer = world["cheapest_newcomer"]
    trace = [{"ordinal": 1, "status": "agent_action_failure", "action": "request_quote", "supplier_id": newcomer},
             {"ordinal": 2, "status": "succeeded", "action": "request_quote", "supplier_id": newcomer}]
    if termination == "submitted":
        trace = trace[:1]
    with pytest.raises(RuntimeError, match="only a rejected last step"):
        report.score_trace(payload, _row(world, trace, margin=-600.0, termination=termination, decision="failed"))


def test_a_supplier_named_on_a_defer_is_not_a_supplier_touched(tmp_path: Path, pack) -> None:
    """The v2 schema has every action name a supplier; the parser drops it from a defer, and so does the report."""
    manifest, payloads, world, payload = pack
    newcomer = world["cheapest_newcomer"]
    trace = [{"ordinal": 1, "status": "succeeded", "action": "defer", "supplier_id": newcomer}]
    root = _write_gate(tmp_path, "named", [_row(world, trace, margin=-600.0, termination="deferred", decision="defer")])
    (w,) = report.score_run(root, manifest, payloads)["worlds"]
    assert w["newcomers_touched"] == 0 and w["first_newcomer"] is None and w["paid_without_testing"] is True
    assert report.as_parsed(trace[0]) == {"ordinal": 1, "status": "succeeded", "action": "defer"}
