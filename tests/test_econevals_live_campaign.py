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


def test_upstream_set_rendering_is_canonicalized() -> None:
    """Upstream renders a Python set into its message; order is not stable.

    Left raw, the kernel's tool-replay cross-check fails nondeterministically
    on scheduling cases -- the harness execution and the environment's
    independent re-derivation disagree on a string that means the same thing.
    """
    from aeread_families.econevals.econevals_bridge import (
        _canonicalize_set_rendering,
    )

    one = "Assignment doesn't include workers: {'W5', 'W9', 'W10', 'W2'}"
    two = "Assignment doesn't include workers: {'W2', 'W10', 'W9', 'W5'}"
    assert _canonicalize_set_rendering(one) == _canonicalize_set_rendering(two)
    assert "W10" in _canonicalize_set_rendering(one)
    # Anything that is not a set rendering passes through untouched.
    assert _canonicalize_set_rendering("plain reason") == "plain reason"
    assert _canonicalize_set_rendering(None) is None


def _fake_run_root(tmp_path, receipt_source, *, statuses) -> "Path":
    """A run root shaped exactly like a completed attempt.

    Reuses a real sealed receipt so the projection runs against a genuine
    payload rather than a hand-built stand-in.
    """
    import hashlib
    import shutil

    from aeread.shared_runner.run.resolver import canonical_json_bytes
    from aeread_families.econevals import campaign as module

    root = tmp_path / "attempt"
    (root / "checkpoints" / "canary_probes").mkdir(parents=True)
    plan = module.build_campaign_plan()
    module._write_once_json(root / "campaign_plan.json", plan)
    probe = {
        "schema_version": "aeread.provider_admission_canary/0.1",
        "campaign_id": module.CAMPAIGN_ID,
        "plan_sha256": plan["plan_sha256"],
        "status": "admitted",
        "cost_usd": 0.00004,
        "probe_ordinal": 1,
    }
    probe["record_sha256"] = module._digest(probe)
    module._write_once_json(root / "checkpoints" / "canary_probes" / "001.json", probe)

    for ordinal, (case_id, status) in enumerate(
        zip(module.PANEL_CASE_IDS, statuses, strict=True)
    ):
        destination = root / "receipts" / case_id / "evaluation_receipt.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(receipt_source, destination)
        checkpoint = {
            "schema_version": "aeread.econevals_checkpoint/0.1",
            "campaign_id": module.CAMPAIGN_ID,
            "plan_sha256": plan["plan_sha256"],
            "ordinal": ordinal,
            "case_id": case_id,
            "status": "complete",
            "run_plan_id": "runplan_test",
            "run_plan_sha256": "0" * 64,
            "receipt_path": str(destination.relative_to(root)),
            "receipt_sha256": "1" * 64,
            "receipt_replayed": True,
            "receipt_status": status,
            "inclusion_status": "included" if status == "ok" else "excluded",
            "cost_usd": 0.01,
            "termination_reason": "max_periods",
            "period_count": 100,
        }
        checkpoint["record_sha256"] = module._digest(checkpoint)
        module._write_once_json(
            root / "checkpoints" / f"{ordinal:02d}_{case_id}.json", checkpoint
        )
    return root


def _sealed_receipt() -> "Path | None":
    from pathlib import Path

    roots = sorted(
        Path("runs/econevals").rglob("evaluation_receipt.json")
    )
    return roots[0] if roots else None


def test_publish_projects_every_case_and_records_the_publisher(tmp_path) -> None:
    """Publishing must survive a mixed panel and name its own publisher.

    Attempt 011 executed a full panel and could not be published, because a
    publisher bug was unfixable once campaign.py was inside the execution
    freeze. This test exercises the projection itself so the next such bug is
    found before a panel pays for it.
    """
    import json

    from aeread_families.econevals import campaign as module

    receipt = _sealed_receipt()
    if receipt is None:
        pytest.skip("no sealed econevals receipt available to project")
    statuses = ["ok"] * (len(module.PANEL_CASE_IDS) - 1) + ["invalid_measurement"]
    root = _fake_run_root(tmp_path, receipt, statuses=statuses)
    publication = tmp_path / "published"
    module.publish_campaign(run_root=root, publication_root=publication)

    summary = json.loads((publication / "reports" / "summary.json").read_text())
    assert summary["planned_cases"] == len(module.PANEL_CASE_IDS)
    assert summary["completed_cases"] == len(module.PANEL_CASE_IDS)
    assert summary["included_cases"] == len(module.PANEL_CASE_IDS) - 1
    assert summary["excluded_cases"] == 1

    manifest = json.loads((publication / "publication_manifest.json").read_text())
    # The publisher is named next to what was executed, never inside the
    # execution freeze -- that is what makes a publisher fix possible.
    assert len(manifest["publisher_implementation_sha256"]) == 64
    assert "campaign.py" not in module.build_campaign_plan()["execution_source_sha256"]

    rows = [
        json.loads(line)
        for line in (publication / "trajectories" / "archive.jsonl")
        .read_text()
        .splitlines()
        if line.strip()
    ]
    assert len(rows) == len(module.PANEL_CASE_IDS)
    assert {row["inclusion_status"] for row in rows} == {"included", "excluded"}


def test_sealed_spend_counts_calls_a_failed_case_already_paid_for(tmp_path) -> None:
    """A case that dies partway has still paid for the periods it ran.

    Failure checkpoints carried no cost field, so 0.0635 USD of real spend
    across three attempts was invisible to the incident ledger -- a 44%
    understatement of what the failed attempts consumed.
    """
    import json

    from aeread_families.econevals.campaign import _sealed_spend

    root = tmp_path / "executions" / "case"
    shard = root / "run" / "artifacts" / "sha256" / "ab"
    shard.mkdir(parents=True)
    (shard / "one").write_text(
        json.dumps({"canonical_response": {"cost_usd": 0.25, "text": "x"}})
    )
    (shard / "two").write_text(json.dumps([{"nested": {"cost_usd": 0.5}}]))
    (shard / "three").write_text("not json at all")
    # A boolean must not be counted as a number.
    (shard / "four").write_text(json.dumps({"cost_usd": True}))
    assert _sealed_spend(root) == pytest.approx(0.75)
    assert _sealed_spend(tmp_path / "absent") == 0.0


def test_failure_register_types_conditions_from_the_sealed_ledger() -> None:
    """The register must not inherit the checkpoint's generic label.

    A checkpoint records `execution_failure` whenever the exception carries no
    condition -- true of every SchedulerContractError -- which would hide
    whether a case died on a 429, a 404 or a contract error. The typed
    conditions come from the sealed event ledger instead.
    """
    from pathlib import Path

    from aeread_families.econevals.failure_register import build

    run_root = Path("runs/econevals/econevals_glm53_flash_parasail_first_light_v1")
    if not run_root.exists():
        pytest.skip("no sealed econevals runs available")
    table, summary = build(run_root=run_root, repository_root=Path("."))
    assert summary["failure_count"] > 0
    assert summary["cost_is_a_floor"] is True
    # Generic labels must not survive into the register.
    assert "execution_failure" not in summary["by_failure_condition"]
    # Every row carries the artifact it came from, and that artifact's digest.
    header, *rows = table.decode("utf-8").strip().splitlines()
    assert "source_artifact_sha256" in header
    for row in rows:
        assert len(row.rsplit(",", 1)[-1]) == 64
