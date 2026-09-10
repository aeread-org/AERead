"""Tests for the econevals offline replayer (replay.py, milestone 3).

Follows the same ``_bridge()``/skip convention as
``tests/test_econevals_environment.py``: pure structural tests run
everywhere; tests that actually replay tool calls run for real when a
pinned upstream bridge interpreter is provisioned, and are skipped (never
faked) otherwise.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import pytest

from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import (
    ImplementationPin,
    PlanCell,
    RunPlan,
    case_content_sha256,
    canonical_json_bytes,
    resolve_run_plan,
)
from aeread.shared_runner.schemas import (
    AgentProfile,
    AnalysisPlan,
    CaseManifest,
    EvaluationBlock,
    RunSpec,
    SamplingPlan,
    SuiteManifest,
)
from aeread.shared_runner.task.evaluation import finalize_family_execution
import dataclasses

from aeread.shared_runner.measurement import MetricValue
from aeread.shared_runner.run.layout import RunLayout
from aeread.shared_runner.task.evaluation import replay_family_receipt
from aeread.shared_runner.task.receipts import seal_evaluation_receipt
from aeread.shared_runner.task.execution import CanonicalResponse, CellExecution, EvidenceStore
from aeread.shared_runner.task.scheduler import EpisodeResult, run_episode
from aeread_families.econevals.econevals_bridge import (
    EconevalsBridge,
    EconevalsBridgeUnavailableError,
    discover_bridge_python,
)
from aeread_families.econevals.environment import (
    SEAT_ID,
    EconevalsPlugin,
    family_manifest,
    register_plugin,
)
from aeread_families.econevals.harness import ScriptedEconevalsHarness
from aeread_families.econevals.measurement import declared_reference_implementations
from aeread_families.econevals.replay import (
    RecordedDecision,
    RecordedEpisode,
    RecordedResponseSource,
    ReplayError,
    assert_replay_matches,
    compare_episode_results,
    record_episode,
    replay_and_verify,
    replay_episode,
    score_replayed_episode,
)

CASES_DIR = Path("cases/econevals")

try:
    BRIDGE_PYTHON = discover_bridge_python()
except EconevalsBridgeUnavailableError as error:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = str(error)
else:
    _BRIDGE_SKIP_REASON = ""


def _bridge() -> EconevalsBridge:
    if BRIDGE_PYTHON is None:
        pytest.skip(_BRIDGE_SKIP_REASON or "bridge python unavailable")
    return EconevalsBridge(python_executable=BRIDGE_PYTHON)


def _shrunk_case(split: str, case_id: str, *, max_steps: int) -> CaseManifest:
    """See ``tests/test_econevals_environment.py``'s identical helper: a
    test-scoped copy of a real pilot case with a much smaller
    ``pins.max_steps``/``episode.max_logical_actions`` so a replay test can
    reach a genuine termination in a handful of periods."""
    path = CASES_DIR / split / f"{case_id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["payload"] = dict(raw["payload"])
    raw["payload"]["pins"] = dict(raw["payload"]["pins"])
    raw["payload"]["pins"]["max_steps"] = max_steps
    raw["episode"] = dict(raw["episode"])
    raw["episode"]["max_logical_actions"] = max_steps
    raw["content_sha256"] = case_content_sha256(raw)
    return CaseManifest.from_dict(raw)


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_econevals_replay_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_econevals_replay",
        suite_version="0.1.0",
        block_id="block_econevals_replay",
        sampling_plan_id="sampling_econevals_replay",
        analysis_plan_id="analysis_econevals_replay",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_econevals_replay_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType({SEAT_ID: "scripted_agent"}),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _pricing_script(product_ids: list[str], *, periods: int) -> list[list[dict]]:
    prices = {product_id: 1.0 for product_id in product_ids}
    return [
        [
            {"id": "1", "name": "get_product_ids", "arguments": {}},
            {"id": "2", "name": "set_prices", "arguments": {"prices_dict_str": prices}},
        ]
        for _ in range(periods)
    ]


def _run_live(bridge: EconevalsBridge, tmp_path: Path, *, suffix: str):
    case = _shrunk_case("pricing_basic", "econevals.pricing.basic.0", max_steps=3)
    cell = _cell(case, suffix=suffix)
    plugin = EconevalsPlugin(bridge=bridge)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())
    family_case = plugin.validate_payload(case.payload)
    product_ids = family_case["generated_instance"]["product_ids"]

    evidence = EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_econevals_replay_{suffix}",
        cell_id=cell.cell_id,
        episode_id=f"episode_econevals_replay_{suffix}",
        episode_attempt_id="attempt_1",
    )
    harness = ScriptedEconevalsHarness(
        plugin=resolved_plugin,
        family_case=family_case,
        evidence=evidence,
        script=_pricing_script(product_ids, periods=3),
    )
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=harness)
    )
    evidence.seal()
    return case, cell, resolved_plugin, family_case, result


# ---------------------------------------------------------------------------
# Pure, no bridge: RecordedDecision/RecordedEpisode structural round-tripping.
# ---------------------------------------------------------------------------


def test_recorded_episode_round_trips_through_plain_json() -> None:
    decision = RecordedDecision(
        phase_id="period",
        seat_id="agent",
        response={"tool_calls": [{"id": "1"}], "n": (1, 2)},
    )
    episode = RecordedEpisode(case_id="econevals.pricing.basic.0", decisions=(decision,))

    text = episode.to_json()
    restored = RecordedEpisode.from_json(text)

    assert restored.case_id == episode.case_id
    assert len(restored.decisions) == 1
    assert restored.decisions[0].phase_id == "period"
    assert restored.decisions[0].seat_id == "agent"
    # Tuple/list distinctions collapse to JSON arrays through the round trip.
    assert restored.decisions[0].response == {
        "tool_calls": [{"id": "1"}],
        "n": [1, 2],
    }


def test_recorded_response_source_enforces_ordering_and_reports_exhaustion() -> None:
    decisions = (
        RecordedDecision(phase_id="period", seat_id="agent", response={"tool_calls": []}),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "period"
        seat_id = "agent"

    response = asyncio.run(source(_Request()))
    assert response == {"tool_calls": []}
    assert source.exhausted is True

    with pytest.raises(ReplayError, match="exhausted"):
        asyncio.run(source(_Request()))


def test_recorded_response_source_rejects_phase_seat_mismatch() -> None:
    decisions = (
        RecordedDecision(phase_id="period", seat_id="agent", response={"tool_calls": []}),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = "period"
        seat_id = "someone_else"

    with pytest.raises(ReplayError, match="does not match"):
        asyncio.run(source(_Request()))


def test_compare_episode_results_reports_specific_mismatches_not_one_boolean() -> None:
    """A synthetic mismatch (mutated terminal) must be visible per-component."""

    class _Fake:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    original = _Fake(
        phase_instances=(),
        terminal={"reason": "max_periods"},
        outcome={"period_count": 3},
        final_state={"period": 3, "attempts": []},
    )
    replayed = _Fake(
        phase_instances=(),
        terminal={"reason": "error"},
        outcome={"period_count": 3},
        final_state={"period": 3, "attempts": []},
    )

    comparison = compare_episode_results(original, replayed)

    assert comparison.terminal_matches is False
    assert comparison.outcome_matches is True
    assert comparison.matches is False
    with pytest.raises(ReplayError, match="terminal record differs"):
        assert_replay_matches(comparison)


# ---------------------------------------------------------------------------
# Bridge-gated: genuine offline replay of a live, tool-executing episode.
# ---------------------------------------------------------------------------


def test_replay_from_a_json_round_tripped_record_reproduces_the_live_run_byte_identically(
    tmp_path: Path,
) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, family_case, original = _run_live(
        bridge, tmp_path, suffix="live"
    )

    recorded = record_episode(original)
    # Force a genuine round trip through plain JSON text -- proves replay
    # never depends on reusing the original run's in-memory Python objects.
    recorded = RecordedEpisode.from_json(recorded.to_json())
    assert recorded.case_id == case.case_id

    # A second, independent EconevalsBridge/plugin -- not the one that
    # produced the original run -- drives the replay, through the SAME
    # PlanCell (so phase_instance_id/episode_id agree; see replay.py's own
    # docstring on why this family's raw state is expected to byte-match,
    # unlike tau3.retail's timestamped messages).
    replay_bridge = EconevalsBridge(python_executable=BRIDGE_PYTHON)
    replay_plugin = EconevalsPlugin(bridge=replay_bridge)
    registry = PluginRegistry()
    register_plugin(registry, plugin=replay_plugin)
    resolved_replay_plugin = registry.resolve_manifest(family_manifest())

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=resolved_replay_plugin, recorded=recorded)
    )

    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is True
    assert comparison.state_hashes_match is True
    assert comparison.final_state_matches is True
    assert comparison.original_final_state_sha256 == comparison.replayed_final_state_sha256
    assert replayed.terminal["reason"] == "max_periods"

    # Genuinely byte-identical, not merely content-equivalent (see
    # replay.py's module docstring for why econevals's state affords this
    # where tau3.retail's cannot).
    assert canonical_json_bytes(replayed.final_state) == canonical_json_bytes(
        original.final_state
    )


def test_replayed_episode_recomputes_both_leaves_from_the_final_attempts_list(
    tmp_path: Path,
) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, family_case, original = _run_live(
        bridge, tmp_path, suffix="score"
    )
    recorded = record_episode(original)

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=resolved_plugin, recorded=recorded)
    )
    scorer = resolved_plugin.build_scorer(family_case)

    scores = score_replayed_episode(scorer=scorer, replayed=replayed)
    original_gate, original_objective = scorer.score_terminal_state(original.final_state)

    assert scores.gate == original_gate
    assert scores.objective == original_objective
    assert scores.gate.primary.value == 1.0
    assert scores.objective is not None
    assert scores.objective.leaf.estimand.units == "profit_usd"


def test_replay_and_verify_end_to_end_returns_a_matching_report(tmp_path: Path) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, family_case, original = _run_live(
        bridge, tmp_path, suffix="e2e"
    )
    recorded = record_episode(original)
    scorer = resolved_plugin.build_scorer(family_case)

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            plugin=resolved_plugin,
            scorer=scorer,
            recorded=recorded,
            original=original,
        )
    )

    assert report.status == "match"
    assert report.scores.gate.primary.value == 1.0
    assert report.final_state_sha256 == original.phase_instances[-1].post_state_sha256


def test_replay_raises_when_a_recorded_tool_result_is_tampered_with(tmp_path: Path) -> None:
    """The tool-level replay guarantee: step() itself catches this, and
    replay_episode must not swallow it."""
    bridge = _bridge()
    case, cell, resolved_plugin, family_case, original = _run_live(
        bridge, tmp_path, suffix="tamper"
    )
    recorded = record_episode(original)

    tampered_decisions = list(recorded.decisions)
    first = tampered_decisions[0]
    response = dict(first.response)
    executions = [dict(item) for item in response["tool_executions"]]
    executions[0] = dict(executions[0])
    executions[0]["result"] = dict(executions[0]["result"])
    executions[0]["result"]["content"] = {"product_ids": ["tampered"]}
    response["tool_executions"] = executions
    tampered_decisions[0] = RecordedDecision(
        phase_id=first.phase_id, seat_id=first.seat_id, response=response
    )
    tampered = RecordedEpisode(case_id=recorded.case_id, decisions=tuple(tampered_decisions))

    with pytest.raises(RuntimeError, match="tool replay result differs"):
        asyncio.run(
            replay_episode(cell=cell, case=case, plugin=resolved_plugin, recorded=tampered)
        )


def test_replay_requires_a_live_bridge_it_is_not_bridge_free(tmp_path: Path) -> None:
    """Pins down the corrected spec section 5 claim: "offline replay" means
    zero further MODEL calls, not zero bridge subprocess calls -- step()'s
    own tool-replay cross-check (exercised above by the tamper test) always
    re-derives every recorded tool result from a live bridge call, replay
    included, exactly like tau3_retail's replay re-executing tool calls
    through its own bridge. A plugin built with no bridge at all must fail
    loudly on replay, the same way a live run would -- never silently
    "succeed" by trusting the recorded evidence alone."""
    bridge = _bridge()
    case, cell, _resolved_plugin, family_case, original = _run_live(
        bridge, tmp_path, suffix="no_bridge"
    )
    recorded = record_episode(original)

    bridge_free_plugin = EconevalsPlugin(bridge=None)
    registry = PluginRegistry()
    register_plugin(registry, plugin=bridge_free_plugin)
    resolved_bridge_free_plugin = registry.resolve_manifest(family_manifest())

    with pytest.raises(RuntimeError, match="requires a provisioned EconevalsBridge"):
        asyncio.run(
            replay_episode(
                cell=cell, case=case, plugin=resolved_bridge_free_plugin, recorded=recorded
            )
        )


def test_replay_case_mismatch_raises_a_typed_replay_error(tmp_path: Path) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, family_case, original = _run_live(
        bridge, tmp_path, suffix="mismatch"
    )
    recorded = record_episode(original)
    wrong_case = RecordedEpisode(
        case_id="econevals.pricing.basic.999", decisions=recorded.decisions
    )

    with pytest.raises(ReplayError, match="not"):
        asyncio.run(
            replay_episode(cell=cell, case=case, plugin=resolved_plugin, recorded=wrong_case)
        )


# ---------------------------------------------------------------------------
# Finalize: the real production finalizer, end to end (issue #74/#141's
# econevals successor -- "enrollment plus a finalize test", ruling on #141).
# ``main``'s scorer (``EconevalsScorer.__call__``) is the contract this test
# drives; nothing here redeclares or redesigns it.
# ---------------------------------------------------------------------------


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def record_full_evidence_lifecycle(
    *,
    evidence: EvidenceStore,
    plugin: Any,
    family_case: Mapping[str, Any],
    result: EpisodeResult,
) -> None:
    """Seal one already-completed episode's full generic evidence lifecycle.

    ``ScriptedEconevalsHarness`` (harness.py) only ever appends the tool-
    level evidence ``task.tools.ToolRuntime`` writes for each period's
    read-only/submit calls -- it is a ``response_source``, and
    ``run_episode`` never hands a ``response_source`` the phase/parse/
    legality/transition/terminal/outcome facts it computes internally, so
    there was nothing for the harness to record them from *during* serving.
    Those facts already exist, completely and correctly, on the
    ``EpisodeResult`` the scheduler returns once the episode terminates;
    this function's only job is to translate that already-computed result
    into the same durable event types/payloads the shared kernel's own
    ``AttemptExecutor`` (``aeread.shared_runner.task.execution``) would have
    appended live, so ``task.evaluation.replay_family_state`` -- the same
    generic replay ``finalize_family_execution``/``replay_family_receipt``/
    ``audit_family_receipt`` all use -- can read this evidence back exactly
    like any other family's. It recomputes nothing: every payload below is
    either taken verbatim from ``result`` or is the record's own already-
    produced ``ParseResult``/``LegalityResult``/``TransitionResult``.

    Every already-enrolled bridge-gated family whose own scripted test
    harness does not drive a real ``ProviderClient`` through
    ``execute_plan_cell`` reimplements this exact generic translation for
    itself (``tests/test_agenticpay_bilateral_replay.py``'s
    ``EvidenceRecordingAgenticpayHarness``, ``tests/test_shared_runner_
    scoring_contract.py``'s negarena section's ``record_full_evidence_
    lifecycle``, ...); this is econevals's own copy, unchanged in shape.
    """
    phase_by_id = {phase.phase_id: phase for phase in plugin.phases(family_case)}
    for instance in result.phase_instances:
        evidence.append_event(
            "phase_instance_started",
            {
                "phase": phase_by_id[instance.phase_id],
                "eligible_actors": instance.eligible_actors,
                "pre_state_sha256": instance.pre_state_sha256,
            },
            phase_instance_id=instance.phase_instance_id,
        )
        for action in instance.actions:
            evidence.append_event(
                "logical_action_started",
                {"profile_id": action.request.profile_id, "request": action.request},
                phase_instance_id=instance.phase_instance_id,
                logical_action_id=action.logical_action_id,
                visibility=f"seat:{action.seat_id}",
            )
            canonical = CanonicalResponse(
                text=json.dumps(_plain(action.response), sort_keys=True),
                finish_reason="stop",
                empty=False,
                truncated=False,
                provider_call_ids=(),
                tool_invocation_ids=(),
                input_tokens=0,
                cached_input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
            )
            evidence.append_event(
                "action_attempt_succeeded",
                {"canonical_response": canonical},
                phase_instance_id=instance.phase_instance_id,
                logical_action_id=action.logical_action_id,
                visibility=f"seat:{action.seat_id}",
            )
            envelope = action.envelope
            evidence.append_event(
                "action_parsed",
                {"parse_result": envelope.parse},
                phase_instance_id=instance.phase_instance_id,
                logical_action_id=action.logical_action_id,
                visibility=f"seat:{action.seat_id}",
            )
            if envelope.legality is not None:
                evidence.append_event(
                    "action_legality_checked",
                    {"legality_result": envelope.legality},
                    phase_instance_id=instance.phase_instance_id,
                    logical_action_id=action.logical_action_id,
                )
            failure_code = None
            if not envelope.valid:
                failure_code = (
                    envelope.parse.error_code
                    if not envelope.parse.ok
                    else envelope.legality.reason
                )
            event_type = (
                "logical_action_succeeded"
                if envelope.valid
                else "logical_action_agent_action_failure"
            )
            evidence.append_event(
                event_type,
                {"valid": envelope.valid, "failure_code": failure_code},
                logical_action_id=action.logical_action_id,
            )
        for transition in instance.transitions:
            evidence.append_event(
                "transition_applied",
                {
                    "phase_id": instance.phase_id,
                    "transition": transition,
                    "post_state_sha256": instance.post_state_sha256,
                },
                phase_instance_id=instance.phase_instance_id,
            )
        evidence.append_event(
            "phase_instance_succeeded",
            {
                "phase_id": instance.phase_id,
                "post_state_sha256": instance.post_state_sha256,
                "logical_action_ids": tuple(
                    action.logical_action_id for action in instance.actions
                ),
            },
            phase_instance_id=instance.phase_instance_id,
        )
    evidence.append_event(
        "episode_terminated",
        {"terminal": result.terminal, "logical_action_count": result.logical_action_count},
    )
    evidence.append_event("family_outcome_recorded", {"outcome": result.outcome})


async def run_scripted_econevals_episode_with_full_evidence(
    *,
    cell: PlanCell,
    case: CaseManifest,
    plugin: Any,
    family_case: Mapping[str, Any],
    evidence: EvidenceStore,
    script: Sequence[Sequence[Mapping[str, Any]]],
) -> EpisodeResult:
    """Drive one ``ScriptedEconevalsHarness``-served episode through the real
    scheduler and seal the complete generic evidence lifecycle before
    returning -- the one entry point this module offers for reaching
    ``task.evaluation.finalize_family_execution``/the scoring-contract
    protocol test for this family (mirrors ``negarena.harness``'s
    identically-purposed ``run_scripted_negarena_episode``).
    """
    harness = ScriptedEconevalsHarness(
        plugin=plugin, family_case=family_case, evidence=evidence, script=script
    )
    result = await run_episode(cell=cell, case=case, plugin=plugin, response_source=harness)
    if not harness.exhausted:
        raise RuntimeError(
            "scripted econevals episode terminated before the script was exhausted"
        )
    record_full_evidence_lifecycle(
        evidence=evidence, plugin=plugin, family_case=family_case, result=result
    )
    return result


_ECONEVALS_FIXTURE_PROFILE_ID = "econevals_unused_fixture_profile_v1"
_ECONEVALS_FIXTURE_PROVIDER_ID = "econevals_unused_fixture_provider"
_ECONEVALS_FIXTURE_RUNTIME_ID = "aeread.shared_runner.task.execution"


def build_econevals_run_plan(
    *, plugin: EconevalsPlugin, case: CaseManifest
) -> tuple[RunPlan, PluginRegistry]:
    """One fully-resolved, sealed econevals ``RunPlan`` for a single pricing
    case.

    ``agent`` (``SEAT_ID``) is the only seat and the sole tested subject
    (``kind="self_play"``, mirroring ``procurement_allocation``'s/
    ``procurement_grounding``'s identical single-seat shape -- econevals has
    no second seat the way every already-enrolled BRIDGE-gated family
    (agenticpay.bilateral, negarena, ...) does). Nothing here ever calls a
    ``ProviderClient`` -- the episode is driven directly through
    ``run_episode`` + ``ScriptedEconevalsHarness``
    (``run_scripted_econevals_episode_with_full_evidence`` above) -- so the
    one agent profile only needs to be schema-valid and admitted, never
    actually invoked.
    """
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)

    profile = AgentProfile.from_dict(
        {
            "spec_version": "aeread.agent_profile/0.1",
            "profile_id": _ECONEVALS_FIXTURE_PROFILE_ID,
            "model": {
                "provider": _ECONEVALS_FIXTURE_PROVIDER_ID,
                "model": "econevals-unused-fixture-model-v1",
                "revision": "1.0.0",
                "base_url": None,
            },
            "harness": {"id": "minimal_chat", "version": "1.0", "config": {}},
            "prompt": {
                "prompt_id": "econevals_scripted_prompt_v1",
                "sha256": hashlib.sha256(
                    b"econevals scripted agent: no prompt is ever sent"
                ).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": _ECONEVALS_FIXTURE_RUNTIME_ID,
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "econevals_scripted_no_reasoning_v1",
                "effort": None,
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": 64,
                "seed": None,
                "top_p": None,
            },
            "budgets": {
                "max_logical_actions": case.episode.max_logical_actions,
                "timeout_seconds": 30.0,
                "max_cost_usd": 0.0,
            },
            "retry_policy": {
                "max_action_attempts": 1,
                "retryable_conditions": [],
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )

    sampling = SamplingPlan.from_dict(
        {
            "spec_version": "aeread.sampling/0.1",
            "sampling_plan_id": "econevals_kernel_finalizer_sample_v1",
            "estimand": "fixed_smoke_case",
            "target": case.case_id,
            "selection": "fixed_curated",
            "seeds": [case.world_seed],
            "replicates": 1,
            "cluster_level": "world_seed",
            "cluster_id_fields": ["generator_version", "world_seed"],
            "paired_fields": [],
            "replicate_level": "episode_attempt",
            "panel_mode": "fixed_panel",
        }
    )
    block = EvaluationBlock.from_dict(
        {
            "spec_version": "aeread.evaluation_block/0.1",
            "block_id": "econevals_kernel_finalizer_block",
            "kind": "self_play",
            "subject_seats": [SEAT_ID],
            "controlled_profiles": {},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    family = family_manifest()
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": "aeread.analysis/0.1",
            "analysis_plan_id": "econevals_kernel_finalizer_analysis_v1",
            "estimands": [family.measurement.primary_estimand],
            "group_by": ["family_id"],
            "missingness": "report_separately",
            "resampling_unit": "world_seed",
            "uncertainty": "none",
            "multiplicity": "none",
            "sensitivity": [],
            "cross_family_scalar": "disabled",
        }
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": "aeread.suite/0.1",
            "suite_id": "econevals_kernel_finalizer_suite_v1",
            "version": "1.0.0",
            "family_ids": [case.family_id],
            "case_ids": [case.case_id],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    run_spec = RunSpec.from_dict(
        {
            "spec_version": "aeread.run_spec/0.1",
            "run_spec_id": "econevals_kernel_finalizer_run_v1",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id],
            "seat_assignments": {SEAT_ID: profile.profile_id},
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )

    harness_registry = HarnessRegistry()
    for harness_impl in default_harnesses().values():
        harness_registry.register(harness_impl)

    environment_sha256 = hashlib.sha256(
        Path(__file__).resolve().parents[1].joinpath(
            "src", "aeread_families", "econevals", "environment.py"
        ).read_bytes()
    ).hexdigest()
    execution_sha256 = hashlib.sha256(
        Path(__file__).resolve().parents[1].joinpath(
            "src", "aeread", "shared_runner", "task", "execution.py"
        ).read_bytes()
    ).hexdigest()
    # Every implementation id the family's declared leaves (across all three
    # tracks) actually reference, read straight off ``measurement.py``'s own
    # ``declared_reference_implementations`` -- the SAME function
    # ``environment.py``'s manifest uses for ``reference_provider_ids`` --
    # so this can never drift from what the manifest declares. Required for
    # ``resolve_run_plan``'s own pin/declared-provider cross-check to pass
    # at all (family_manifest's own docstring: "the resolver requires
    # exactly the manifest's declared reference providers -- no more, no
    # fewer").
    reference_pins = tuple(
        ImplementationPin.from_dict(
            {
                "component_id": ref.implementation_id,
                "kind": "reference",
                "version": ref.version,
                "sha256": ref.content_sha256,
            }
        )
        for ref in declared_reference_implementations()
    )
    pins = (
        ImplementationPin.from_dict(
            {
                "component_id": family.family.plugin_id,
                "kind": "family_plugin",
                "version": "0.1.0",
                "sha256": environment_sha256,
            }
        ),
        ImplementationPin.from_dict(
            {
                "component_id": family.scoring.scorer_id,
                "kind": "scorer",
                "version": "0.1.0",
                "sha256": environment_sha256,
            }
        ),
        *reference_pins,
        ImplementationPin.from_dict(
            {
                "component_id": "minimal_chat",
                "kind": "harness",
                "version": "1.0",
                "sha256": execution_sha256,
            }
        ),
        ImplementationPin.from_dict(
            {
                "component_id": _ECONEVALS_FIXTURE_RUNTIME_ID,
                "kind": "runtime",
                "version": "0.1.0",
                "sha256": execution_sha256,
            }
        ),
    )

    plan = resolve_run_plan(
        families=(family,),
        cases=(case,),
        suite=suite,
        sampling=sampling,
        evaluation_blocks=(block,),
        analysis=analysis,
        agent_profiles=(profile,),
        run_spec=run_spec,
        registry=registry,
        implementation_pins=pins,
        harness_registry=harness_registry,
        provider_capabilities={
            _ECONEVALS_FIXTURE_PROVIDER_ID: ProviderCapabilities(
                native_tools=False,
                structured_output=False,
                seed=False,
                system_prompt=True,
                reasoning_budget=False,
                reasoning_token_report=False,
                max_context_tokens=None,
            )
        },
    )
    return plan, registry


@dataclass(frozen=True, slots=True)
class _EvaluationSetup:
    """Minimal ``EvaluationSetup`` (task/evaluation.py) implementation.

    ``prompt_sources``/``pricing`` are never read by
    ``finalize_family_execution`` itself (only by ``execute_plan_cell``'s
    provider-calling path, which this module deliberately bypasses -- the
    episode is driven directly through ``run_episode`` +
    ``ScriptedEconevalsHarness``), so both are left empty here. Mirrors
    ``tests/test_agenticpay_bilateral_replay.py``'s identically-purposed
    ``_EvaluationSetup``.
    """

    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, Any]


def _run_econevals_episode_through_finalizer(bridge: EconevalsBridge, tmp_path: Path):
    """Drive one shrunk (``max_steps=2``) pricing episode all the way to a
    sealed receipt through the real production finalizer.

    Returns ``(receipt, evidence, family_case, resolved_plugin, result,
    setup, evidence_root)`` -- the last two so a caller can replay the
    receipt against the same sealed evidence.
    """
    case = _shrunk_case("pricing_basic", "econevals.pricing.basic.0", max_steps=2)
    plugin = EconevalsPlugin(bridge=bridge)
    plan, registry = build_econevals_run_plan(plugin=plugin, case=case)
    cell = plan.cells[0]
    resolved_plugin = registry.resolve_manifest(family_manifest())
    family_case = resolved_plugin.validate_payload(case.payload)
    product_ids = family_case["generated_instance"]["product_ids"]

    # finalize_family_execution and a LATER replay_family_receipt must see the
    # same sealed evidence, and replay resolves it through RunLayout, so the
    # store is opened at the layout's own attempt directory rather than at a
    # path of this test's choosing.
    evidence_root = tmp_path / "evidence_finalize_receipt"
    attempt_dir = RunLayout(evidence_root, plan.run_plan_id).attempt_dir(
        cell.cell_id, "attempt_1"
    )
    evidence = EvidenceStore(
        attempt_dir,
        run_plan_id=plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_id=f"episode_{cell.cell_id}",
        episode_attempt_id="attempt_1",
    )
    result = asyncio.run(
        run_scripted_econevals_episode_with_full_evidence(
            cell=cell,
            case=case,
            plugin=resolved_plugin,
            family_case=family_case,
            evidence=evidence,
            script=_pricing_script(product_ids, periods=2),
        )
    )
    evidence.audit_reconciliation()

    execution = CellExecution(
        run_plan_id=plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_attempt_id="attempt_1",
        episode_result=result,
        evidence=evidence,
        action_executions=(),
        total_cost_usd=0.0,
    )
    setup = _EvaluationSetup(plan=plan, registry=registry, prompt_sources={}, pricing={})
    receipt = finalize_family_execution(setup=setup, execution=execution)
    return receipt, evidence, family_case, resolved_plugin, result, setup, evidence_root


def test_finalize_wires_econevals_to_the_shared_family_finalizer(tmp_path: Path) -> None:
    """econevals has never produced an ``EvaluationReceipt`` before this test
    (issue #141's minimal successor for #74/#108: "enrollment plus a
    finalize test", ``main``'s scorer as the contract -- #108's leaf-policy
    redesign is deliberately NOT adopted here). Drives one small, real,
    bridge-backed pricing episode end to end through the real finalizer and
    asserts a receipt comes back carrying both of this case's leaves (the
    gate passes on a legal, non-negative price, so the objective leaf is
    present too) and the primary the scorer actually declared -- not merely
    that a receipt came back.

    econevals's production manifest declares no finalize-time leaf policy
    yet (unlike the six already-migrated external families) -- a
    deliberately unperturbed fact this test does not change (see module
    docstring) -- so ``_enforce_declared_leaf_policy`` is unconstrained
    here; this test's own independent call to the SAME scorer on the SAME
    replayed final state is what pins the expected shape, rather than
    hardcoding a profit value this test would otherwise have to reverse-
    engineer from the bridge.
    """
    bridge = _bridge()
    receipt, evidence, family_case, resolved_plugin, result, _setup, _evidence_root = (
        _run_econevals_episode_through_finalizer(bridge, tmp_path)
    )

    scorer = resolved_plugin.build_scorer(family_case)
    expected_gate, expected_objective = scorer.score_terminal_state(result.final_state)
    assert expected_objective is not None  # price=1.0 is legal -> gate passes

    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"
    assert receipt.replay_level == "state_and_score"
    assert receipt.primary_leaf_id == expected_objective.leaf.leaf_id
    assert {score.leaf.leaf_id for score in receipt.scores} == {
        expected_gate.leaf.leaf_id,
        expected_objective.leaf.leaf_id,
    }
    assert receipt.inapplicable_leaf_ids == ()
    assert receipt.deferred_leaf_ids == ()

    gate_score = next(
        score for score in receipt.scores if score.leaf.leaf_id == expected_gate.leaf.leaf_id
    )
    assert gate_score.status == "ok"
    assert gate_score.primary is not None
    assert gate_score.primary.value == 1.0

    objective_score = next(
        score
        for score in receipt.scores
        if score.leaf.leaf_id == expected_objective.leaf.leaf_id
    )
    assert objective_score.status == "ok"
    assert objective_score.primary is not None
    assert objective_score.primary.value == pytest.approx(expected_objective.primary.value)
    assert objective_score.reference_values["v_star"].value == pytest.approx(
        expected_objective.reference_values["v_star"].value
    )

    evidence_refs = {score.evidence_refs for score in receipt.scores}
    assert len(evidence_refs) == 1

    # Evidence really was sealed with a durable receipt on disk.
    assert evidence.verify_seal() == receipt.evidence
    receipt_path = evidence.root / "evaluation_receipt.json"
    assert receipt_path.is_file()
    assert receipt_path.read_bytes() == canonical_json_bytes(receipt) + b"\n"


def test_econevals_receipt_replays_and_refuses_a_resealed_tamper(tmp_path: Path) -> None:
    """The finalize test above never called ``replay_family_receipt``, so this
    family had no replay coverage despite the pair being described as
    finalize-and-replay.

    Cross-model review of this branch raised that, and it was right. Replay is
    added here with the negative control that makes the call load-bearing,
    because ``replay_family_receipt`` returns the receipt it was handed:
    asserting on the returned object alone would be self-satisfying. Three
    checks stand in front of its comparison against the re-derived score set,
    established by probing rather than read off the source -- an altered
    receipt fails its own digest, a re-sealed one is refused against the bytes
    actually written to the attempt directory, and only a receipt that is both
    self-consistent and truly sealed reaches the comparison. This asserts the
    reachable one.
    """
    bridge = _bridge()
    receipt, _evidence, _family_case, _plugin, _result, setup, evidence_root = (
        _run_econevals_episode_through_finalizer(bridge, tmp_path)
    )

    # The untampered receipt replays from its own sealed evidence. Without this
    # the assertion below could pass because replay refuses everything.
    replayed = replay_family_receipt(
        setup=setup, receipt=receipt, evidence_root=evidence_root
    )
    assert replayed.receipt_sha256 == receipt.receipt_sha256

    # Re-seal a receipt that claims a different objective value, so it clears
    # the digest gate, and check the replay still refuses it.
    falsified = tuple(
        dataclasses.replace(
            score,
            primary=MetricValue(score.primary.value + 1.0, score.primary.unit),
        )
        if score.leaf.leaf_id == receipt.primary_leaf_id and score.primary is not None
        else score
        for score in receipt.scores
    )
    resealed = seal_evaluation_receipt(
        dataclasses.replace(receipt, scores=falsified, receipt_sha256=None)
    )
    assert resealed.receipt_sha256 != receipt.receipt_sha256

    with pytest.raises(ValueError, match="durable family receipt bytes"):
        replay_family_receipt(
            setup=setup, receipt=resealed, evidence_root=evidence_root
        )

