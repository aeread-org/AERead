"""The TERMS-Bench live pilot campaign (#92), everything short of a provider.

The plan is frozen and tamper-evident; the panel is the pinned corpus in the
corpus manifest's order; the canary re-probes only on typed transient
conditions; the wall-time gate is a frozen control that stops the campaign;
and the publisher projects a mixed panel from real sealed receipts.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import finalize_family_execution
from aeread.shared_runner.task.execution import ProviderFailure, execute_plan_cell
from aeread_families.termsbench import campaign as module
from aeread_families.termsbench.campaign import (
    CAMPAIGNS,
    DEFAULT_CAMPAIGN_ID,
    MAX_SERIAL_WALL_SECONDS,
    PANEL_CASE_IDS,
    _verify_plan,
    build_campaign_plan,
)

# The panel these tests exercise; the registry's other entries are covered by
# `test_every_registered_campaign_is_a_distinct_verifiable_identity`.
SPEC = CAMPAIGNS[DEFAULT_CAMPAIGN_ID]
CAMPAIGN_ID = SPEC.campaign_id
MAX_CANARY_COST_USD = SPEC.max_canary_cost_usd
MAX_TRAJECTORY_COST_USD = SPEC.max_trajectory_cost_usd
HARD_TOTAL_COST_CEILING_USD = SPEC.hard_total_cost_ceiling_usd
from aeread_families.termsbench.live import (
    CASES_DIR,
    MODEL,
    PROVIDER,
    ROUTE_PROVIDER,
    build_live_setup,
    load_case,
)
from tests.test_termsbench_live import OVERLAP_CASE_ID, _ScriptedRoute


def test_campaign_plan_freezes_route_panel_order_and_budget() -> None:
    plan = build_campaign_plan(SPEC)
    assert plan["campaign_id"] == CAMPAIGN_ID
    assert plan["route"]["provider"] == PROVIDER
    assert plan["route"]["model"] == MODEL
    assert plan["route"]["route_provider"] == ROUTE_PROVIDER
    assert plan["route"]["fallbacks"] == "disabled"
    # v3's condition: no reasoning block at all, which the 2026-09-10 probe
    # showed is the only way to obtain deliberation on this route -- a cap is
    # a suppression switch whatever its value, and an effort cannot be
    # declared beside one (#133).
    assert plan["route"]["reasoning_condition_id"] == "reasoning_unconstrained_v1"
    assert plan["route"]["reasoning_effort"] is None
    assert plan["route"]["reasoning_token_budget"] is None
    assert plan["route"]["reasoning_declared_block"] is False
    assert [row["case_id"] for row in plan["panel"]] == list(PANEL_CASE_IDS)
    assert len(plan["panel"]) == 30
    regimes = sorted(row["regime"] for row in plan["panel"])
    assert regimes == ["nodeal"] * 15 + ["overlap"] * 15
    assert sorted({row["difficulty_bin"] for row in plan["panel"]}) == [0, 1, 2, 3, 4]
    assert plan["seats"]["counterpart"].startswith("kernel_scripted_seat:")
    assert plan["execution"]["max_serial_wall_seconds"] == MAX_SERIAL_WALL_SECONDS
    assert plan["execution"]["cell_failure_policy"] == "seal_typed_exclusion_and_continue"
    assert plan["campaign_id"].endswith("_v3")
    planned = MAX_CANARY_COST_USD + len(PANEL_CASE_IDS) * MAX_TRAJECTORY_COST_USD
    assert plan["budget"]["planned_maximum_usd"] == pytest.approx(planned)
    assert planned <= HARD_TOTAL_COST_CEILING_USD
    # The publisher stays outside the execution freeze.
    assert "campaign.py" not in plan["execution_source_sha256"]
    assert "kernel.py" in plan["execution_source_sha256"]
    _verify_plan(plan)


def test_campaign_plan_digest_is_stable_and_tamper_evident() -> None:
    first = build_campaign_plan(SPEC)
    second = build_campaign_plan(SPEC)
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    tampered = dict(first)
    tampered["panel"] = list(reversed(first["panel"]))
    with pytest.raises(ValueError):
        _verify_plan(tampered)


def test_panel_cases_are_the_pinned_corpus_cases_unmodified() -> None:
    manifest = json.loads((CASES_DIR / "pilot_manifest.json").read_text(encoding="utf-8"))
    plan = build_campaign_plan(SPEC)
    assert plan["corpus"]["pilot_manifest_sha256"] == manifest["content_sha256"]
    for row in plan["panel"]:
        on_disk = json.loads((CASES_DIR / f"{row['case_id']}.json").read_text(encoding="utf-8"))
        assert row["case_content_sha256"] == on_disk["content_sha256"]
        assert load_case(row["case_id"]).content_sha256 == on_disk["content_sha256"]
        assert row["world_seed"] == on_disk["world_seed"]
        assert row["max_logical_actions"] == on_disk["episode"]["max_logical_actions"]


def test_plan_declares_the_canary_reprobe_budget() -> None:
    canary = build_campaign_plan(SPEC)["canary"]
    assert canary["scored"] is False
    assert canary["max_probes"] >= 2
    assert "rate_limit" in canary["transient_conditions"]
    assert canary["probes_are_recorded_individually"] is True


def test_canary_reprobes_a_transient_rejection_then_admits(tmp_path, monkeypatch) -> None:
    attempts: list[int] = []

    async def fake_probe(*, spec, path, plan_sha256, ordinal):
        attempts.append(ordinal)
        if ordinal < 3:
            return {"status": "rejected", "failure_condition": "rate_limit", "cost_usd": 0.0}
        return {"status": "admitted", "cost_usd": 0.0}

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(module, "_probe_canary", fake_probe)
    monkeypatch.setattr(module.asyncio, "sleep", no_sleep)
    record = asyncio.run(module.run_canary(spec=SPEC, run_root=tmp_path, plan_sha256="x"))
    assert record["status"] == "admitted"
    assert attempts == [1, 2, 3]


def test_canary_stops_immediately_on_a_non_transient_rejection(tmp_path, monkeypatch) -> None:
    attempts: list[int] = []

    async def fake_probe(*, spec, path, plan_sha256, ordinal):
        attempts.append(ordinal)
        return {"status": "rejected", "failure_condition": "provider_contract", "cost_usd": 0.0}

    monkeypatch.setattr(module, "_probe_canary", fake_probe)
    record = asyncio.run(module.run_canary(spec=SPEC, run_root=tmp_path, plan_sha256="x"))
    assert record["status"] == "rejected"
    assert attempts == [1]


def test_the_canary_request_is_shaped_like_an_agent_turn() -> None:
    message = module._canary_observation()
    assert message["phase_id"] == "agent_turn" and message["seat_id"] == "agent"
    observation = message["observation"]
    assert observation["round"] == 0 and observation["transcript"] == []
    assert set(observation) == {
        "role", "r_a", "price_bounds", "horizon", "round",
        "agent_offers", "counterpart_offers", "transcript",
    }


# --- a run root built from a real sealed receipt ----------------------------


def _sealed_receipt(tmp_path: Path, case_id: str = OVERLAP_CASE_ID) -> tuple[Path, str]:
    """Run one corpus case offline through the real kernel and return its
    sealed receipt and digest, so the publisher is exercised on genuine
    payloads, one per case."""
    setup = build_live_setup(case_id=case_id, seed=300, max_trajectory_cost_usd=0.05)
    payload = setup.case.payload
    r_a, r_b = float(payload["agent"]["r_a"]), float(payload["t_b"]["r_b"])
    route = _ScriptedRoute(
        [
            {"decision": "offer", "price": r_b + 0.5 * (r_a - r_b), "message": "opening"},
            {"decision": "accept", "message": "agreed"},
        ]
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path / "sealed" / case_id,
            prompt_sources=setup.prompt_sources,
            providers={PROVIDER: route},
            pricing=setup.pricing,
            harnesses=setup.harnesses,
            tool_runtime_factories=setup.tool_runtime_factories,
        )
    )
    receipt = finalize_family_execution(setup=setup, execution=execution)
    assert receipt.status == "ok", (case_id, receipt.status)
    return execution.evidence.root / "evaluation_receipt.json", receipt.receipt_sha256


def _admitted_probe(root: Path, plan: dict) -> None:
    probe = {
        "schema_version": module.CANARY_SCHEMA,
        "campaign_id": CAMPAIGN_ID,
        "plan_sha256": plan["plan_sha256"],
        "status": "admitted",
        "cost_usd": 0.00004,
        "probe_ordinal": 1,
    }
    probe["record_sha256"] = module._digest(probe)
    module._write_once_json(root / "checkpoints" / "canary_probes" / "001.json", probe)


def _complete_checkpoint(root: Path, plan: dict, *, ordinal: int, case_id: str,
                         receipt: tuple[Path, str], status: str, elapsed: float) -> None:
    source, receipt_sha256 = receipt
    destination = root / "receipts" / case_id / "evaluation_receipt.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    checkpoint = {
        "schema_version": module.CHECKPOINT_SCHEMA,
        "campaign_id": CAMPAIGN_ID,
        "plan_sha256": plan["plan_sha256"],
        "ordinal": ordinal,
        "case_id": case_id,
        "status": "complete",
        "run_plan_id": "runplan_test",
        "run_plan_sha256": "0" * 64,
        "receipt_path": str(destination.relative_to(root)),
        "receipt_sha256": receipt_sha256,
        "receipt_replayed": True,
        "receipt_status": status,
        "inclusion_status": "included" if status == "ok" else "excluded",
        "cost_usd": 0.01,
        "elapsed_seconds": elapsed,
        "termination_reason": "agent_accept",
        "final_price": 100.0,
        "rounds_used": 2,
        "malformed_action_schema": False,
    }
    checkpoint["record_sha256"] = module._digest(checkpoint)
    module._write_once_json(root / "checkpoints" / f"{ordinal:02d}_{case_id}.json", checkpoint)


def test_publish_projects_every_case_per_regime_and_names_the_publisher(tmp_path) -> None:
    root = tmp_path / "attempt"
    plan = build_campaign_plan(SPEC)
    module._write_once_json(root / "campaign_plan.json", plan)
    _admitted_probe(root, plan)
    statuses = ["ok"] * (len(PANEL_CASE_IDS) - 1) + ["invalid_measurement"]
    for ordinal, (case_id, status) in enumerate(zip(PANEL_CASE_IDS, statuses, strict=True)):
        _complete_checkpoint(root, plan, ordinal=ordinal, case_id=case_id,
                             receipt=_sealed_receipt(tmp_path, case_id), status=status,
                             elapsed=12.5)
    publication = tmp_path / "published"
    module.publish_campaign(run_root=root, publication_root=publication)
    summary = json.loads((publication / "reports" / "summary.json").read_text())
    assert summary["planned_cases"] == summary["completed_cases"] == len(PANEL_CASE_IDS)
    assert summary["included_cases"] == len(PANEL_CASE_IDS) - 1
    assert summary["excluded_cases"] == 1
    assert summary["by_regime"]["overlap"]["completed_cases"] == 15
    assert summary["by_regime"]["nodeal"]["completed_cases"] == 15
    # The family's own corpus aggregate over the Overlap half, from real leaves.
    aggregate = summary["overlap_corpus_aggregate"]
    assert set(aggregate) == {"SE_plus", "AGR_plus", "CSE_plus"}
    assert aggregate["AGR_plus"] == 1.0
    assert summary["total_elapsed_seconds"] == pytest.approx(12.5 * len(PANEL_CASE_IDS))
    manifest = json.loads((publication / "publication_manifest.json").read_text())
    assert len(manifest["publisher_implementation_sha256"]) == 64
    rows = [
        json.loads(line)
        for line in (publication / "trajectories" / "archive.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(rows) == len(PANEL_CASE_IDS)
    assert {row["inclusion_status"] for row in rows} == {"included", "excluded"}
    assert all(row["protocol_compliance_value"] is not None for row in rows)
    assert len(list((publication / "receipts").glob("*.json"))) == len(PANEL_CASE_IDS)


def test_the_wall_time_gate_stops_the_campaign_before_the_second_case(tmp_path) -> None:
    """The first completed case's serial wall time, projected over the panel,
    is a frozen control: a projection over the limit stops the campaign
    before another provider call is made."""
    root = tmp_path / "attempt"
    plan = build_campaign_plan(SPEC)
    module._write_once_json(root / "campaign_plan.json", plan)
    _admitted_probe(root, plan)
    too_slow = MAX_SERIAL_WALL_SECONDS / len(PANEL_CASE_IDS) + 1.0
    _complete_checkpoint(root, plan, ordinal=0, case_id=PANEL_CASE_IDS[0],
                         receipt=_sealed_receipt(tmp_path, PANEL_CASE_IDS[0]),
                         status="ok", elapsed=too_slow)
    with pytest.raises(RuntimeError, match="wall-time gate"):
        asyncio.run(module.execute_campaign(spec=SPEC, run_root=root))
    # Nothing was executed for the second case.
    assert not (root / "executions").exists()


def test_sealed_spend_counts_calls_a_failed_case_already_paid_for(tmp_path) -> None:
    root = tmp_path / "executions" / "case"
    shard = root / "run" / "artifacts" / "sha256" / "ab"
    shard.mkdir(parents=True)
    (shard / "one").write_text(json.dumps({"canonical_response": {"cost_usd": 0.25, "text": "x"}}))
    (shard / "two").write_text(json.dumps([{"nested": {"cost_usd": 0.5}}]))
    (shard / "three").write_text("not json at all")
    (shard / "four").write_text(json.dumps({"cost_usd": True}))
    assert module._sealed_spend(root) == pytest.approx(0.75)
    assert module._sealed_spend(tmp_path / "absent") == 0.0


def test_publish_refuses_a_receipt_that_names_another_case(tmp_path) -> None:
    root = tmp_path / "attempt"
    plan = build_campaign_plan(SPEC)
    module._write_once_json(root / "campaign_plan.json", plan)
    _admitted_probe(root, plan)
    wrong = _sealed_receipt(tmp_path, OVERLAP_CASE_ID)
    for ordinal, case_id in enumerate(PANEL_CASE_IDS):
        _complete_checkpoint(root, plan, ordinal=ordinal, case_id=case_id, receipt=wrong,
                             status="ok", elapsed=1.0)
    with pytest.raises(RuntimeError, match="names case"):
        module.publish_campaign(run_root=root, publication_root=tmp_path / "published")


def test_max_cases_pauses_after_complete_checkpoints_without_touching_the_route(tmp_path) -> None:
    """The operator's pause: with the first case already complete, a
    `max_cases=1` resume returns before the second case needs a provider."""
    root = tmp_path / "attempt"
    plan = build_campaign_plan(SPEC)
    module._write_once_json(root / "campaign_plan.json", plan)
    _admitted_probe(root, plan)
    _complete_checkpoint(root, plan, ordinal=0, case_id=PANEL_CASE_IDS[0],
                         receipt=_sealed_receipt(tmp_path, PANEL_CASE_IDS[0]),
                         status="ok", elapsed=1.0)
    asyncio.run(module.execute_campaign(spec=SPEC, run_root=root, max_cases=1))
    assert not (root / "executions").exists()
    assert sorted(p.name for p in (root / "checkpoints").glob("*.json")) == [
        f"00_{PANEL_CASE_IDS[0]}.json"
    ]
    with pytest.raises(ValueError):
        asyncio.run(module.execute_campaign(spec=SPEC, run_root=root, max_cases=0))


class _FailingThenScriptedRoute(_ScriptedRoute):
    """The first provider call fails closed with a non-retryable typed
    condition; every later call serves the scripted moves."""

    def __init__(self, moves):
        super().__init__(moves)
        self.failed_once = False

    async def complete(self, request):
        if not self.failed_once:
            self.failed_once = True
            raise ProviderFailure("provider_contract", "route said no", retryable=False)
        return await super().complete(request)


def _agreeing_moves(case_id: str) -> list[dict]:
    payload = load_case(case_id).payload
    r_a, r_b = float(payload["agent"]["r_a"]), float(payload["t_b"]["r_b"])
    return [
        {"decision": "offer", "price": r_b + 0.5 * (r_a - r_b), "message": "opening"},
        {"decision": "accept", "message": "agreed"},
    ]


def test_a_cell_that_fails_inside_the_kernel_is_sealed_and_the_campaign_continues(
    tmp_path, monkeypatch
) -> None:
    """v1 aborted the panel on one cell (TB-O-01). v2 seals the cell as a
    typed exclusion receipt and runs the next case."""
    root = tmp_path / "attempt"
    plan = build_campaign_plan(SPEC)

    async def admitted(*, spec, path, plan_sha256, ordinal):
        record = {"status": "admitted", "cost_usd": 0.0, "plan_sha256": plan_sha256,
                  "probe_ordinal": ordinal}
        record["record_sha256"] = module._digest(record)
        module._write_once_json(path, record)
        return record

    route = _FailingThenScriptedRoute(_agreeing_moves(PANEL_CASE_IDS[1]))
    monkeypatch.setattr(module, "_probe_canary", admitted)
    monkeypatch.setattr(module, "OpenRouterChatClient", lambda: route)
    asyncio.run(module.execute_campaign(spec=SPEC, run_root=root, max_cases=2))
    first = json.loads((root / "checkpoints" / f"00_{PANEL_CASE_IDS[0]}.json").read_text())
    second = json.loads((root / "checkpoints" / f"01_{PANEL_CASE_IDS[1]}.json").read_text())
    assert first["status"] == "failed"
    assert first["receipt_status"] == "invalid_measurement"
    assert first["inclusion_status"] == "excluded"
    assert first["failure_condition"] == "provider_contract"
    assert first["failure_class"] == "integration_or_configuration"
    assert (root / first["receipt_path"]).exists()
    assert second["status"] == "complete"
    # A resume never reruns the failed cell.
    asyncio.run(module.execute_campaign(spec=SPEC, run_root=root, max_cases=2))
    assert json.loads((root / "checkpoints" / f"00_{PANEL_CASE_IDS[0]}.json").read_text()) == first


def test_publish_carries_a_failed_cell_as_typed_missingness(tmp_path, monkeypatch) -> None:
    root = tmp_path / "attempt"
    plan = build_campaign_plan(SPEC)

    async def admitted(*, spec, path, plan_sha256, ordinal):
        record = {"status": "admitted", "cost_usd": 0.0, "plan_sha256": plan_sha256,
                  "probe_ordinal": ordinal}
        record["record_sha256"] = module._digest(record)
        module._write_once_json(path, record)
        return record

    route = _FailingThenScriptedRoute(_agreeing_moves(PANEL_CASE_IDS[1]))
    monkeypatch.setattr(module, "_probe_canary", admitted)
    monkeypatch.setattr(module, "OpenRouterChatClient", lambda: route)
    asyncio.run(module.execute_campaign(spec=SPEC, run_root=root, max_cases=2))
    for ordinal, case_id in list(enumerate(PANEL_CASE_IDS))[2:]:
        _complete_checkpoint(root, plan, ordinal=ordinal, case_id=case_id,
                             receipt=_sealed_receipt(tmp_path, case_id), status="ok", elapsed=1.0)
    publication = tmp_path / "published"
    module.publish_campaign(run_root=root, publication_root=publication)
    summary = json.loads((publication / "reports" / "summary.json").read_text())
    assert summary["completed_cases"] == len(PANEL_CASE_IDS)
    assert summary["failed_cases"] == 1
    assert summary["failure_conditions"] == {"provider_contract": 1}
    assert summary["excluded_cases"] == 1
    rows = [json.loads(l) for l in (publication / "trajectories" / "archive.jsonl").read_text().splitlines() if l.strip()]
    failed = [row for row in rows if row["cell_status"] == "failed"]
    assert len(failed) == 1 and failed[0]["case_id"] == PANEL_CASE_IDS[0]
    assert failed[0]["termination_reason"] is None and failed[0]["protocol_compliance_value"] is None


def test_every_registered_campaign_is_a_distinct_verifiable_identity() -> None:
    """Panels live side by side because each is a sealed identity a bundle
    refers back to. Every one must rebuild from its own record, and no two
    may share a plan digest -- a panel that silently reused another's
    identity would overwrite published evidence."""
    digests = {}
    for campaign_id, spec in CAMPAIGNS.items():
        plan = build_campaign_plan(spec)
        assert plan["campaign_id"] == campaign_id
        _verify_plan(plan)
        assert plan["budget"]["planned_maximum_usd"] <= plan["budget"]["hard_total_cost_ceiling_usd"]
        assert plan["route"]["revision"] == spec.route.revision
        digests[campaign_id] = plan["plan_sha256"]
    assert len(set(digests.values())) == len(CAMPAIGNS)


def test_the_two_paper_model_panels_differ_only_in_the_model() -> None:
    """They exist to be compared with each other and with the paper's own
    table, so every control except the model is held equal: same corpus,
    same reasoning condition, same completion budget, same schema dialect."""
    gpt = build_campaign_plan(CAMPAIGNS["termsbench_gpt4o_mini_pilot_v1"])
    glm = build_campaign_plan(CAMPAIGNS["termsbench_glm51_pilot_v1"])
    assert gpt["corpus"] == glm["corpus"]
    assert [row["case_id"] for row in gpt["panel"]] == [row["case_id"] for row in glm["panel"]]
    for key in ("reasoning_condition_id", "reasoning_effort", "reasoning_token_budget",
                "reasoning_declared_block"):
        assert gpt["route"][key] == glm["route"][key]
    assert gpt["canary"]["max_output_tokens"] == glm["canary"]["max_output_tokens"]
    assert gpt["route"]["revision"] != glm["route"]["revision"]
    # Both are agents the paper evaluated, at opposite ends of its table.
    assert "0.189" in gpt["purpose"] and "0.721" in glm["purpose"]
