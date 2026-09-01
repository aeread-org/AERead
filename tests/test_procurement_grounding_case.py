from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

import aeread.shared_runner.execution as execution_module
from aeread.shared_runner.resolver import canonical_json_bytes, case_content_sha256
from aeread_families.procurement_grounding import (
    ProcurementGroundingPlugin,
    build_offline_setup,
    load_case,
    run_fixture_response,
)
import aeread_families.procurement_grounding.environment as environment_module


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "procurement_grounding"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _plain(value):
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def test_case_hash_and_frozen_workbook_provenance_validate() -> None:
    case = load_case()

    assert case.case_id == "procurement_grounding_v1.dev.231_projects"
    assert case.content_sha256 == case_content_sha256(case)
    assert case.payload["snapshot"]["workbook_sha256"] == (
        "1488985150e3afc9c5dc8bf4753200fd60dc504ce0f8468aa99e3d325a284504"
    )
    assert case.payload["snapshot"]["workbook_bytes"] == 139785


def test_agent_observation_excludes_evaluator_oracle() -> None:
    case = load_case()
    plugin = ProcurementGroundingPlugin()
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, run=None)
    phase = plugin.phases(family_case)[0]

    observation = plugin.observe(family_case, state, "analyst", phase)
    serialized = canonical_json_bytes(observation)

    assert set(observation) == {"snapshot", "evidence"}
    assert b'"oracle"' not in serialized
    assert b'"mismatched_fields"' not in serialized
    assert b'"quality_band"' not in serialized
    vocabulary = observation["evidence"]["report_vocabulary"]
    oracle = case.payload["oracle"]
    assert vocabulary["scope_id"] == oracle["scope"]
    assert vocabulary["shortlist_structure_id"] == oracle["shortlist_structure"]
    assert vocabulary["next_step_ids"] == list(oracle["next_steps"])


def test_strong_fixture_runs_end_to_end_and_scores_100(tmp_path) -> None:
    execution = asyncio.run(
        run_fixture_response(_fixture("strong.json"), evidence_root=tmp_path / "strong")
    )
    outcome = _plain(execution.episode_result.outcome)

    assert outcome == {
        "valid": True,
        "quality_band": "strong",
        "total_points": 100,
        "max_points": 100,
        "score": 1.0,
        "breakdown": {
            "source_counts": 26,
            "priority_families": 24,
            "supplier_distribution": 10,
            "evidence_interpretations": 15,
            "procurement_controls": 15,
            "decision_and_next_steps": 10,
        },
        "mismatched_fields": [],
        "failure_code": None,
    }
    assert execution.total_cost_usd == pytest.approx(0.0)
    execution.evidence.audit_reconciliation()
    assert execution.action_executions[0].status == "succeeded"


def test_structurally_valid_but_poor_fixture_stays_valid_and_scores_low(tmp_path) -> None:
    execution = asyncio.run(
        run_fixture_response(
            _fixture("valid_but_poor.json"), evidence_root=tmp_path / "poor"
        )
    )
    outcome = _plain(execution.episode_result.outcome)

    assert outcome["valid"] is True
    assert outcome["quality_band"] == "valid_but_poor"
    assert 0 < outcome["total_points"] < 60
    assert outcome["failure_code"] is None
    execution.evidence.audit_reconciliation()


def test_premature_bulk_order_claim_is_an_invalid_action_with_zero_credit(tmp_path) -> None:
    execution = asyncio.run(
        run_fixture_response(
            _fixture("invalid_bulk_ready.json"), evidence_root=tmp_path / "invalid"
        )
    )
    outcome = _plain(execution.episode_result.outcome)

    assert outcome["valid"] is False
    assert outcome["quality_band"] == "invalid"
    assert outcome["score"] == 0.0
    assert outcome["failure_code"] == "premature_bulk_order_readiness"
    assert execution.action_executions[0].status == "agent_action_failure"
    execution.evidence.audit_reconciliation()


def test_malformed_response_is_recorded_as_invalid_not_as_poor_quality(tmp_path) -> None:
    execution = asyncio.run(
        run_fixture_response("not json", evidence_root=tmp_path / "malformed")
    )
    outcome = _plain(execution.episode_result.outcome)

    assert outcome["valid"] is False
    assert outcome["score"] == 0.0
    assert outcome["failure_code"] == "malformed_json"


def test_same_response_reproduces_the_same_outcome_and_episode_state(tmp_path) -> None:
    first = asyncio.run(
        run_fixture_response(_fixture("strong.json"), evidence_root=tmp_path / "first")
    )
    second = asyncio.run(
        run_fixture_response(_fixture("strong.json"), evidence_root=tmp_path / "second")
    )

    assert first.episode_result.episode_id == second.episode_result.episode_id
    assert first.episode_result.final_state == second.episode_result.final_state
    assert first.episode_result.outcome == second.episode_result.outcome


def test_run_plan_pins_actual_family_and_runtime_sources() -> None:
    setup = build_offline_setup()
    pins = {pin.component_id: pin.sha256 for pin in setup.plan.implementation_pins}
    family_sha = hashlib.sha256(Path(environment_module.__file__).read_bytes()).hexdigest()
    execution_sha = hashlib.sha256(Path(execution_module.__file__).read_bytes()).hexdigest()

    assert pins["procurement_grounding_environment"] == family_sha
    assert pins["procurement_grounding_scorer_v1"] == family_sha
    assert pins["minimal_chat"] == execution_sha
    assert pins["aeread.shared_runner.execution"] == execution_sha


def test_fixture_files_are_valid_json_objects() -> None:
    for name in ("strong.json", "valid_but_poor.json", "invalid_bulk_ready.json"):
        value = json.loads(_fixture(name))
        assert isinstance(value, dict)
