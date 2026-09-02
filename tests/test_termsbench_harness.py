"""Scripted harness + end-to-end coverage for termsbench (milestone 3).

Drives at least 2 full episodes -- one Overlap-regime, one No-deal-regime --
against real, on-disk pilot case files (``cases/termsbench/pilot/``) through
the REAL shared-runner path: ``PluginRegistry.resolve_manifest`` ->
``run_episode`` -> ``TermsBenchPlugin``'s own ``step``/``terminal``/
``outcome`` hooks, never a hand-wired shortcut that calls plugin methods
directly (contrast ``test_termsbench_environment.py``'s two constraint-check
tests, which deliberately *do* call ``step`` directly to isolate one
transition -- those are unit tests, not this file's concern).

Each episode's ``ScriptedTermsBenchHarness`` is given a real ``EvidenceStore``
so every counterpart round's raw draws (and every agent turn's raw script
response) are sealed as durable, hash-chained evidence exactly as spec
section 5 requires ("every draw ``step()`` consumes must be sealed as
evidence per round"), then the store is sealed and independently
re-audited from disk (``EvidenceStore.audit_existing``) to prove the seal is
real, not merely called.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from aeread.shared_runner.execution import EvidenceSealedError, EvidenceStore
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.resolver import PlanCell
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import run_episode
from aeread_families.termsbench.environment import TermsBenchPlugin, register_plugin
from aeread_families.termsbench.harness import ScriptedTermsBenchHarness
from aeread_families.termsbench.measurement import build_scorer

PILOT_DIR = Path("cases/termsbench/pilot")


def _case(case_id: str) -> CaseManifest:
    path = PILOT_DIR / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_termsbench_harness_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_termsbench_harness",
        suite_version="0.1.0",
        block_id="block_termsbench_harness",
        sampling_plan_id="sampling_termsbench_harness",
        analysis_plan_id="analysis_termsbench_harness",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_termsbench_harness_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(
            {"agent": "scripted_agent", "counterpart": "termsbench_counterpart_kernel_v1"}
        ),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _evidence(tmp_path: Path, *, suffix: str, case: CaseManifest, cell: PlanCell) -> EvidenceStore:
    return EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_termsbench_harness_{suffix}",
        cell_id=cell.cell_id,
        episode_id=f"episode_termsbench_harness_{suffix}",
        episode_attempt_id="attempt_1",
    )


# ---------------------------------------------------------------------------
# Episode 1: real Overlap pilot case, agent_opens, 3 agent offers/accept +
# 2 counterpart rounds, ends agent_accept.
# ---------------------------------------------------------------------------

OVERLAP_CASE_ID = "termsbench.candid.overlap.1000001"
NODEAL_CASE_ID = "termsbench.candid.nodeal.1010011"


def _run_overlap_episode(tmp_path: Path, *, suffix: str = "overlap"):
    case = _case(OVERLAP_CASE_ID)
    assert case.payload["chi"] == "agent_opens"
    r_a = float(case.payload["agent"]["r_a"])
    r_b = float(case.payload["t_b"]["r_b"])
    cell = _cell(case, suffix=suffix)
    evidence = _evidence(tmp_path, suffix=suffix, case=case, cell=cell)

    script = [
        {"decision": "offer", "price": r_b + 0.1 * (r_a - r_b), "message": "opening"},
        {"decision": "offer", "price": r_b + 0.4 * (r_a - r_b), "message": "moving closer"},
        {"decision": "accept", "price": None, "message": "deal"},
    ]
    # Force rounds 1-2 away from an early accept/walk-away so the episode
    # actually exercises 2 distinct counterpart rounds (an opening anchor,
    # then a real counter-offer) before the agent's round-3 accept.
    draws = {
        1: {"u_accept": 0.9999999, "u_walkaway": 0.9999999, "opening_noise": 0.0, "sentiment_noise": 0.0},
        2: {"u_accept": 0.9999999, "u_walkaway": 0.9999999, "price_noise": 0.0, "sentiment_noise": 0.0},
    }
    harness = ScriptedTermsBenchHarness(
        world_seed=case.world_seed, script=script, counterpart_draws_by_round=draws, evidence=evidence
    )
    registry = PluginRegistry()
    plugin = register_plugin(registry)
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=harness)
    )
    return case, cell, plugin, harness, evidence, result


# ---------------------------------------------------------------------------
# Episode 2: real No-deal pilot case, agent_opens, repeated lowball offers ->
# counterpart walk-away at the round-5 hazard boundary (mirrors
# test_termsbench_environment.py's golden-4 termination case, on real data).
# ---------------------------------------------------------------------------


def _run_nodeal_episode(tmp_path: Path, *, suffix: str = "nodeal"):
    case = _case(NODEAL_CASE_ID)
    assert case.payload["chi"] == "agent_opens"
    r_a = float(case.payload["agent"]["r_a"])
    r_b = float(case.payload["t_b"]["r_b"])
    cell = _cell(case, suffix=suffix)
    evidence = _evidence(tmp_path, suffix=suffix, case=case, cell=cell)

    lowball = max(0.0, r_b - 90.0)
    assert lowball < r_a  # no agent-side IR violation on its own lowball offers
    script = [{"decision": "offer", "price": lowball, "message": "lowball"}] * 6
    draws = {round_k: {"u_accept": 0.999, "u_walkaway": 0.0} for round_k in range(1, 7)}
    harness = ScriptedTermsBenchHarness(
        world_seed=case.world_seed, script=script, counterpart_draws_by_round=draws, evidence=evidence
    )
    registry = PluginRegistry()
    plugin = register_plugin(registry)
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=harness)
    )
    return case, cell, plugin, harness, evidence, result


# ---------------------------------------------------------------------------
# Full episode + sealed evidence.
# ---------------------------------------------------------------------------


def test_overlap_episode_runs_end_to_end_through_the_real_scheduler(tmp_path: Path) -> None:
    case, _cell_, _plugin, harness, evidence, result = _run_overlap_episode(tmp_path)

    assert result.terminal["reason"] == "agent_accept"
    assert result.terminal["final_price"] is not None
    assert harness.exhausted is True

    # 5 logical actions: agent(offer), counterpart(offer), agent(offer),
    # counterpart(offer), agent(accept).
    assert result.logical_action_count == 5
    assert len(result.phase_instances) == 5

    plugin = TermsBenchPlugin()
    family_case = plugin.validate_payload(case.payload)
    scorer = build_scorer(family_case)
    se = scorer.score_surplus_efficiency(outcome=result.outcome)
    agr = scorer.score_feasible_agreement(outcome=result.outcome)
    cv = scorer.score_protocol_compliance(outcome=result.outcome)
    assert se.status == "ok" and se.primary.value > 0.0
    assert agr.status == "ok" and agr.primary.value == 1.0
    assert cv.status == "ok"

    evidence.seal()
    evidence.close()


def test_nodeal_episode_runs_end_to_end_through_the_real_scheduler(tmp_path: Path) -> None:
    case, _cell_, _plugin, harness, evidence, result = _run_nodeal_episode(tmp_path)

    assert result.terminal["reason"] == "counterpart_walk_away"
    assert result.terminal["final_price"] is None
    # The walk-away hazard fires at round 5 (k_walk = ceil(10/2)), so only 5
    # of the script's 6 scripted offers are ever consumed -- the 6th script
    # entry is deliberate headroom, not a bug.
    assert harness.exhausted is False

    plugin = TermsBenchPlugin()
    family_case = plugin.validate_payload(case.payload)
    scorer = build_scorer(family_case)
    fagr = scorer.score_no_deal_agreement(outcome=result.outcome)
    cv = scorer.score_protocol_compliance(outcome=result.outcome)
    assert fagr.status == "ok" and fagr.primary.value == 0.0  # no false agreement
    assert cv.status == "ok"

    evidence.seal()
    evidence.close()


def test_evidence_seals_one_event_per_logical_action_and_reopens_for_audit(
    tmp_path: Path,
) -> None:
    case, cell, _plugin, _harness, evidence, result = _run_overlap_episode(tmp_path, suffix="audit")
    seal = evidence.seal()
    assert seal.event_count == result.logical_action_count == 5
    evidence.close()

    # Genuinely reopen from disk -- not the same in-memory object -- and
    # verify the full hash chain plus the seal marker.
    reopened = EvidenceStore.audit_existing(tmp_path / "evidence_audit")
    reopened.verify_chain()
    reopened_seal = reopened.verify_seal()
    assert reopened_seal == seal

    events = reopened.read_events()
    assert [event.event_type for event in events] == [
        "termsbench_agent_response",
        "termsbench_counterpart_draws",
        "termsbench_agent_response",
        "termsbench_counterpart_draws",
        "termsbench_agent_response",
    ]
    # Every event is tagged to its own phase instance / logical action, and
    # the sealed counterpart payload carries exactly the draws step() used.
    phase_instance_ids = {instance.phase_instance_id for instance in result.phase_instances}
    for event in events:
        assert event.phase_instance_id in phase_instance_ids
        assert event.logical_action_id is not None

    counterpart_events = [e for e in events if e.event_type == "termsbench_counterpart_draws"]
    counterpart_actions = [
        action
        for instance in result.phase_instances
        for action in instance.actions
        if instance.phase_id == "counterpart_turn"
    ]
    assert len(counterpart_events) == len(counterpart_actions) == 2
    for event, action in zip(counterpart_events, counterpart_actions):
        payload = reopened.read_event_payload(event)
        assert payload["round"] == action.response["round"]
        assert payload["draws"] == dict(action.response["draws"])
        assert payload["resolved"] == action.response["resolved"]


def test_sealed_evidence_rejects_further_writes(tmp_path: Path) -> None:
    case, cell, _plugin, _harness, evidence, _result = _run_overlap_episode(tmp_path, suffix="sealwrite")
    evidence.seal()
    with pytest.raises(EvidenceSealedError):
        evidence.append_event("termsbench_agent_response", {"decision": "offer"})
    evidence.close()


def test_harness_without_an_evidence_store_still_runs(tmp_path: Path) -> None:
    """Backward compatibility: evidence is optional (default None) -- every
    existing provider-free unit test that never passes one keeps working."""
    case = _case(OVERLAP_CASE_ID)
    cell = _cell(case, suffix="noevidence")
    r_a = float(case.payload["agent"]["r_a"])
    r_b = float(case.payload["t_b"]["r_b"])
    harness = ScriptedTermsBenchHarness(
        world_seed=case.world_seed,
        script=[{"decision": "offer", "price": r_b + 0.1 * (r_a - r_b), "message": "x"}],
        counterpart_draws_by_round={1: {"u_accept": 0.0}},
    )
    registry = PluginRegistry()
    plugin = register_plugin(registry)
    result = asyncio.run(run_episode(cell=cell, case=case, plugin=plugin, response_source=harness))
    assert result.terminal["reason"] == "counterpart_accept"
    assert harness.evidence is None
