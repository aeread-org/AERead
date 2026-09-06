"""Provider-free tests for the econevals first-live campaign (issue #90).

None of these tests makes a model call. They pin the frozen plan's shape,
the route it declares, and -- the point of this family -- that the scorer
surfaces BOTH declared measurement leaves through the kernel's
``FamilyScoreSet`` contract rather than collapsing to one (issue #74).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aeread.shared_runner.measurement import FamilyScoreSet
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.econevals.campaign import (
    CAMPAIGN_ID,
    HARD_TOTAL_COST_CEILING_USD,
    MAX_CANARY_COST_USD,
    MAX_TRAJECTORY_COST_USD,
    PANEL_CASE_IDS,
    PANEL_STRATA,
    _verify_plan,
    build_campaign_plan,
)
from aeread_families.econevals.live import (
    MODEL,
    PROVIDER,
    ROUTE_PROVIDER,
    build_live_setup,
    load_case,
)
from aeread_families.econevals.measurement import build_scorer

CASES_DIR = Path("cases/econevals")


def test_campaign_plan_freezes_route_panel_order_and_budget() -> None:
    plan = build_campaign_plan()
    assert plan["campaign_id"] == CAMPAIGN_ID
    # The matrix ruling pins these runs to GLM 5.3 Flash on Parasail with
    # fallbacks off -- NOT the Arena route accepted for the tau3 proof.
    assert plan["route"]["provider"] == PROVIDER
    assert plan["route"]["model"] == MODEL
    assert plan["route"]["route_provider"] == ROUTE_PROVIDER
    assert plan["route"]["fallbacks"] == "disabled"
    assert [row["case_id"] for row in plan["panel"]] == list(PANEL_CASE_IDS)
    assert [row["stratum"] for row in plan["panel"]] == list(PANEL_STRATA)
    # Two cases from each of the three tracks.
    tracks = sorted(row["track"] for row in plan["panel"])
    assert tracks == ["pricing", "pricing", "procurement", "procurement",
                      "scheduling", "scheduling"]
    planned = MAX_CANARY_COST_USD + len(PANEL_CASE_IDS) * MAX_TRAJECTORY_COST_USD
    assert plan["budget"]["planned_maximum_usd"] == pytest.approx(planned)
    assert planned <= HARD_TOTAL_COST_CEILING_USD
    _verify_plan(plan)


def test_campaign_plan_digest_is_stable_and_tamper_evident() -> None:
    first = build_campaign_plan()
    second = build_campaign_plan()
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    tampered = dict(first)
    tampered["panel"] = list(reversed(first["panel"]))
    with pytest.raises(ValueError):
        _verify_plan(tampered)


def test_panel_cases_are_the_pinned_corpus_cases_unmodified() -> None:
    """The pilot must not shrink max_steps or otherwise edit a corpus case."""
    for row in build_campaign_plan()["panel"]:
        case = load_case(row["case_id"])
        on_disk = json.loads(
            (CASES_DIR / f"{row['track']}_basic" / f"{row['case_id']}.json").read_text(
                encoding="utf-8"
            )
        )
        assert case.content_sha256 == on_disk["content_sha256"]
        assert row["case_content_sha256"] == on_disk["content_sha256"]
        assert row["max_steps"] == on_disk["payload"]["pins"]["max_steps"]


def _scoring_input(state: dict) -> SimpleNamespace:
    """Minimal stand-in for the kernel's FamilyScoringInput."""
    return SimpleNamespace(
        outcome={"termination_reason": "max_periods"},
        phase_instances=(
            SimpleNamespace(transitions=(SimpleNamespace(state=state),)),
        ),
        evidence_refs=(),
    )


def test_scorer_surfaces_both_leaves_when_the_gate_admits() -> None:
    """Issue #74: every declared leaf reaches the receipt, not just one."""
    case = load_case("econevals.procurement.basic.0")
    family_case = case.payload
    scorer = build_scorer(family_case)
    gold = family_case["gold_optimum"]
    # Attempts in state are the environment's OWN evaluated records, not raw
    # submissions. This one reproduces the optimum exactly, so the gate admits
    # it and the objective sits at full headroom.
    attempt = {
        "error": False,
        "is_feasible": True,
        "utility": gold["opt_utility"],
    }
    state = {"attempts": [attempt]}
    result = scorer(_scoring_input(state))
    assert isinstance(result, FamilyScoreSet)
    leaf_ids = {score.leaf.leaf_id for score in result.scores}
    assert leaf_ids == {
        scorer.gate_leaf.leaf_id,
        scorer.objective_leaf.leaf_id,
    }, leaf_ids
    assert result.primary_leaf_id == scorer.objective_leaf.leaf_id


def test_scorer_reports_the_gate_alone_when_no_attempt_was_recorded() -> None:
    """No attempts is an invalid measurement, and it excludes the receipt."""
    scorer = build_scorer(load_case("econevals.scheduling.basic.0").payload)
    result = scorer(_scoring_input({"attempts": []}))
    assert result.primary_leaf_id == scorer.gate_leaf.leaf_id
    assert [score.leaf.leaf_id for score in result.scores] == [
        scorer.gate_leaf.leaf_id
    ]
    assert result.scores[0].validity.status == "invalid"


def test_scorer_requires_a_replayed_terminal_state() -> None:
    scorer = build_scorer(load_case("econevals.pricing.basic.0").payload)
    empty = SimpleNamespace(outcome={}, phase_instances=(), evidence_refs=())
    with pytest.raises(ValueError, match="no replayed terminal state"):
        scorer(empty)


def test_plan_declares_the_canary_reprobe_budget() -> None:
    """A transient 429 on a zero-cost probe must not seal the attempt root."""
    canary = build_campaign_plan()["canary"]
    assert canary["scored"] is False
    assert canary["max_probes"] >= 2
    assert "rate_limit" in canary["transient_conditions"]
    assert canary["probes_are_recorded_individually"] is True


def test_canary_reprobes_a_transient_rejection_then_admits(tmp_path, monkeypatch) -> None:
    import asyncio

    from aeread_families.econevals import campaign as module

    attempts: list[int] = []

    async def fake_probe(*, path, plan_sha256, ordinal):
        attempts.append(ordinal)
        path.parent.mkdir(parents=True, exist_ok=True)
        if ordinal < 3:
            return {"status": "rejected", "failure_condition": "rate_limit",
                    "cost_usd": 0.0, "probe_ordinal": ordinal}
        return {"status": "admitted", "cost_usd": 0.0, "probe_ordinal": ordinal}

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(module, "_probe_canary", fake_probe)
    monkeypatch.setattr(module.asyncio, "sleep", no_sleep)
    record = asyncio.run(module.run_canary(run_root=tmp_path, plan_sha256="x"))
    assert record["status"] == "admitted"
    assert attempts == [1, 2, 3]


def test_canary_stops_immediately_on_a_non_transient_rejection(tmp_path, monkeypatch) -> None:
    import asyncio

    from aeread_families.econevals import campaign as module

    attempts: list[int] = []

    async def fake_probe(*, path, plan_sha256, ordinal):
        attempts.append(ordinal)
        return {"status": "rejected", "failure_condition": "provider_contract",
                "cost_usd": 0.0, "probe_ordinal": ordinal}

    monkeypatch.setattr(module, "_probe_canary", fake_probe)
    record = asyncio.run(module.run_canary(run_root=tmp_path, plan_sha256="x"))
    assert record["status"] == "rejected"
    assert attempts == [1]
