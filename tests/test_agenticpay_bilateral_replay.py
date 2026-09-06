"""Tests for the agenticpay.bilateral scripted harness and offline replayer
(harness.py/replay.py, spec section 5, Milestone 3).

Follows the same ``_bridge()``/skip convention as
``tests/test_agenticpay_bilateral_environment.py``: pure structural tests run
everywhere; tests that actually drive the real upstream bridge run for real when a
pinned upstream Python interpreter is provisioned, and are skipped (never faked)
otherwise.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import pytest

from aeread.shared_runner.task.execution import (
    CanonicalResponse,
    CellExecution,
    EvidenceStore,
)
from aeread.shared_runner.task.evaluation import finalize_family_execution
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import (
    ImplementationPin,
    PlanCell,
    RunPlan,
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
from aeread.shared_runner.task.scheduler import EpisodeResult, run_episode
from aeread_families.agenticpay_bilateral import measurement
from aeread_families.agenticpay_bilateral.agenticpay_bridge import (
    AgenticpayBridge,
    AgenticpayBridgeUnavailableError,
    discover_bridge_python,
)
from aeread_families.agenticpay_bilateral.environment import (
    BUYER_PHASE,
    SELLER_PHASE,
    AgenticpayBilateralPlugin,
    family_manifest,
    register_plugin,
)
from aeread_families.agenticpay_bilateral.harness import ScriptedAgenticpayBilateralHarness
from aeread_families.agenticpay_bilateral.measurement import build_scorer
from aeread_families.agenticpay_bilateral.replay import (
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


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_AGENTICPAY_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-agenticpay",
    )
    root = Path(candidate)
    marker = root / "agenticpay" / "envs" / "single_buyer_product_seller" / "Task1_basic_price_negotiation.py"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream AgenticPay checkout not found at {root}",
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()

try:
    BRIDGE_PYTHON = discover_bridge_python(upstream_root=UPSTREAM_ROOT)
except AgenticpayBridgeUnavailableError as error:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = str(error)
else:
    _BRIDGE_SKIP_REASON = ""


def _bridge() -> AgenticpayBridge:
    if BRIDGE_PYTHON is None:
        pytest.skip(_BRIDGE_SKIP_REASON or "upstream AgenticPay Python interpreter unavailable")
    return AgenticpayBridge(python_executable=BRIDGE_PYTHON, upstream_root=UPSTREAM_ROOT)


def _case(case_id: str) -> CaseManifest:
    split = case_id.split(".")[2]
    path = Path("cases/agenticpay_bilateral") / split / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_agenticpay_bilateral_replay_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_agenticpay_bilateral_replay",
        suite_version="0.1.0",
        block_id="block_agenticpay_bilateral_replay",
        sampling_plan_id="sampling_agenticpay_bilateral_replay",
        analysis_plan_id="analysis_agenticpay_bilateral_replay",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_agenticpay_bilateral_replay_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType({"buyer": "scripted_buyer", "seller": "scripted_seller"}),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _script(rounds: list[tuple[str, str]]) -> list[tuple[str, dict[str, str]]]:
    """Turn ``[(buyer_message, seller_message), ...]`` into a flat harness script."""
    flat: list[tuple[str, dict[str, str]]] = []
    for buyer_message, seller_message in rounds:
        flat.append((BUYER_PHASE, {"message": buyer_message}))
        flat.append((SELLER_PHASE, {"message": seller_message}))
    return flat


def _run_live(bridge: AgenticpayBridge, tmp_path: Path, *, case_id: str, suffix: str, rounds):
    """Drive one full episode through the real scheduler with sealed evidence.

    Mirrors ``tau3_retail.replay``'s own ``_run_live`` test helper: a real
    ``PluginRegistry``, a real ``run_episode`` call, and (the structural difference
    documented on ``harness.py``) a real ``EvidenceStore`` the harness itself seals one
    event into per served decision, since this family has no tool-call surface for a
    ``ToolRuntime`` to seal evidence through instead.
    """
    case = _case(case_id)
    cell = _cell(case, suffix=suffix)
    plugin = AgenticpayBilateralPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())

    evidence = EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_agenticpay_bilateral_replay_{suffix}",
        cell_id=cell.cell_id,
        episode_id=f"episode_agenticpay_bilateral_replay_{suffix}",
        episode_attempt_id="attempt_1",
    )
    harness = ScriptedAgenticpayBilateralHarness(evidence=evidence, script=_script(rounds))
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=harness)
    )
    return case, cell, resolved_plugin, result, evidence, harness


class EvidenceRecordingAgenticpayHarness:
    """A ``run_episode`` response source that writes the full generic
    replay-required evidence trail (``logical_action_started``,
    ``action_attempt_succeeded``, ``action_parsed``,
    ``action_legality_checked``, ``logical_action_succeeded``,
    ``phase_instance_started``, ``transition_applied``,
    ``phase_instance_succeeded``, ``episode_terminated``,
    ``family_outcome_recorded``) -- exactly the event vocabulary
    ``aeread.shared_runner.task.execution``'s ``AttemptExecutor`` writes for
    every LLM-harness-backed family's own evidence, reproduced here without
    any of that class's provider/retry/cost machinery, since every scripted
    agenticpay.bilateral decision is a plain ``{"message": str}`` dict,
    never a provider completion.

    ``ScriptedAgenticpayBilateralHarness`` (this family's existing scripted
    response source, above) writes only its own convenience event
    (``agenticpay_bilateral_decision_served``) and has never produced
    evidence ``aeread.shared_runner.task.evaluation.replay_family_scoring_input``
    can replay -- ``finalize_family_execution`` calls that replay internally,
    so this class is what makes driving THAT finalizer, and the scoring-
    contract protocol test's own paired fixtures, possible for this family at
    all (mirrors ``govsim``'s identically-purposed
    ``EvidenceRecordingGovsimHarness``). ``script`` is the same
    ``[(phase_id, response), ...]`` shape ``_script``/
    ``ScriptedAgenticpayBilateralHarness`` already use; this class owns only
    the evidence-recording seam around it, mirroring ``AttemptExecutor``'s
    own event shapes field-for-field.
    """

    def __init__(
        self,
        *,
        evidence: EvidenceStore,
        script: list[tuple[str, Mapping[str, Any]]],
    ) -> None:
        self._evidence = evidence
        self._script = list(script)
        self._cursor = 0

    async def __call__(self, request: Any) -> dict[str, Any]:
        if self._cursor >= len(self._script):
            raise RuntimeError("script exhausted before episode termination")
        expected_phase, response = self._script[self._cursor]
        self._cursor += 1
        if request.phase_id != expected_phase:
            raise RuntimeError(
                f"script expected phase {expected_phase!r}, got {request.phase_id!r}"
            )
        response = dict(response)
        self._evidence.append_event(
            "logical_action_started",
            {"request": request},
            phase_instance_id=request.phase_instance_id,
            logical_action_id=request.logical_action_id,
            visibility=f"seat:{request.seat_id}",
        )
        # A CanonicalResponse-shaped placeholder purely for replay provenance
        # (``LogicalActionRecord.response``): this family's own
        # ``parse_action`` never reads it (the scheduler hands it the raw
        # ``response`` dict returned below, unchanged -- see
        # ``ScriptedAgenticpayBilateralHarness``'s identical contract), and
        # replay itself reconstructs ``parse``/``legality`` directly from
        # the "action_parsed"/"action_legality_checked" events below, never
        # from this response.
        canonical = CanonicalResponse(
            text=json.dumps(response, sort_keys=True),
            finish_reason="stop",
            empty=False,
            truncated=False,
            provider_call_ids=(),
            tool_invocation_ids=(),
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            action=response,
        )
        self._evidence.append_event(
            "action_attempt_succeeded",
            {"canonical_response": canonical},
            phase_instance_id=request.phase_instance_id,
            logical_action_id=request.logical_action_id,
            visibility=f"seat:{request.seat_id}",
        )
        return response

    def finalize_action(self, record: Any) -> None:
        envelope = record.envelope
        failure_code = None
        if not envelope.valid:
            failure_code = (
                envelope.parse.error_code
                if not envelope.parse.ok
                else envelope.legality.reason
            )
        self._evidence.append_event(
            "action_parsed",
            {"parse_result": envelope.parse},
            phase_instance_id=record.request.phase_instance_id,
            logical_action_id=record.logical_action_id,
            visibility=f"seat:{record.seat_id}",
        )
        if envelope.legality is not None:
            self._evidence.append_event(
                "action_legality_checked",
                {"legality_result": envelope.legality},
                phase_instance_id=record.request.phase_instance_id,
                logical_action_id=record.logical_action_id,
            )
        event_type = (
            "logical_action_succeeded"
            if envelope.valid
            else "logical_action_agent_action_failure"
        )
        self._evidence.append_event(
            event_type,
            {"valid": envelope.valid, "failure_code": failure_code},
            logical_action_id=record.logical_action_id,
        )

    def fail_logical_action(self, logical_action_id: str, *, failure_code: str) -> None:
        self._evidence.append_event(
            "logical_action_failed",
            {"failure_condition": failure_code},
            logical_action_id=logical_action_id,
        )

    def phase_started(
        self,
        *,
        phase_instance_id: str,
        phase: Any,
        eligible_actors: tuple[str, ...],
        pre_state_sha256: str,
    ) -> None:
        self._evidence.append_event(
            "phase_instance_started",
            {
                "phase": phase,
                "eligible_actors": eligible_actors,
                "pre_state_sha256": pre_state_sha256,
            },
            phase_instance_id=phase_instance_id,
        )

    def transition_applied(
        self,
        *,
        phase_instance_id: str,
        phase: Any,
        transition: Any,
        post_state_sha256: str,
    ) -> None:
        self._evidence.append_event(
            "transition_applied",
            {
                "phase_id": phase.phase_id,
                "transition": transition,
                "post_state_sha256": post_state_sha256,
            },
            phase_instance_id=phase_instance_id,
        )

    def phase_completed(self, *, phase_instance: Any) -> None:
        self._evidence.append_event(
            "phase_instance_succeeded",
            {
                "phase_id": phase_instance.phase_id,
                "post_state_sha256": phase_instance.post_state_sha256,
                "logical_action_ids": tuple(
                    action.logical_action_id for action in phase_instance.actions
                ),
            },
            phase_instance_id=phase_instance.phase_instance_id,
        )

    def episode_completed(self, *, episode_result: EpisodeResult) -> None:
        self._evidence.append_event(
            "episode_terminated",
            {
                "terminal": episode_result.terminal,
                "logical_action_count": episode_result.logical_action_count,
            },
        )
        self._evidence.append_event(
            "family_outcome_recorded",
            {"outcome": episode_result.outcome},
        )


# ---------------------------------------------------------------------------
# Pure, no bridge: RecordedDecision/RecordedEpisode structural round-tripping.
# ---------------------------------------------------------------------------


def test_recorded_episode_round_trips_through_plain_json() -> None:
    decision = RecordedDecision(
        phase_id=BUYER_PHASE, seat_id="buyer", response={"message": "### BUYER_PRICE($90) ###"}
    )
    episode = RecordedEpisode(
        case_id="agenticpay.bilateral.basic.task1", case_sha256="a" * 64, decisions=(decision,)
    )

    text = episode.to_json()
    restored = RecordedEpisode.from_json(text)

    assert restored.case_id == episode.case_id
    assert restored.case_sha256 == episode.case_sha256
    assert len(restored.decisions) == 1
    assert restored.decisions[0].phase_id == BUYER_PHASE
    assert restored.decisions[0].seat_id == "buyer"
    assert restored.decisions[0].response == {"message": "### BUYER_PRICE($90) ###"}


def test_recorded_response_source_enforces_ordering_and_reports_exhaustion() -> None:
    decisions = (
        RecordedDecision(phase_id=BUYER_PHASE, seat_id="buyer", response={"message": "hi"}),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = BUYER_PHASE
        seat_id = "buyer"

    response = asyncio.run(source(_Request()))
    assert response == {"message": "hi"}
    assert source.exhausted is True

    with pytest.raises(ReplayError, match="exhausted"):
        asyncio.run(source(_Request()))


def test_recorded_response_source_rejects_phase_seat_mismatch() -> None:
    decisions = (
        RecordedDecision(phase_id=SELLER_PHASE, seat_id="seller", response={"message": "hi"}),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = BUYER_PHASE
        seat_id = "buyer"

    with pytest.raises(ReplayError, match="does not match"):
        asyncio.run(source(_Request()))


def test_compare_episode_results_reports_specific_mismatches_not_one_boolean() -> None:
    """A synthetic mismatch (mutated terminal) must be visible per-component."""

    class _Fake:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    original = _Fake(
        phase_instances=(),
        terminal={"reason": "agreed"},
        outcome={"agreed_price": 100.0},
        final_state={"termination": "agreed"},
    )
    replayed = _Fake(
        phase_instances=(),
        terminal={"reason": "timeout"},
        outcome={"agreed_price": 100.0},
        final_state={"termination": "agreed"},
    )

    comparison = compare_episode_results(original, replayed)

    assert comparison.terminal_matches is False
    assert comparison.outcome_matches is True
    assert comparison.matches is False
    with pytest.raises(ReplayError, match="terminal record differs"):
        assert_replay_matches(comparison)


# ---------------------------------------------------------------------------
# Bridge-gated: two full, independent, sealed-evidence episodes and their replay.
# ---------------------------------------------------------------------------

_BASIC_ROUNDS = [
    ("### BUYER_PRICE($90) ###", "### SELLER_PRICE($130) ###"),
    ("### BUYER_PRICE($100) ###", "### SELLER_PRICE($100) ###"),
]

_CONTRACT = (
    '<contract>{"price": 5.39, "continuous_terms": {"delivery_days": 1}, '
    '"discrete_terms": {"return_policy": "none", "packaging": "protective", '
    '"user_product_preference": "strong_match"}}</contract>'
)


def test_a_basic_negotiation_runs_end_to_end_with_sealed_evidence(tmp_path: Path) -> None:
    """Episode 1/2: a two-round price-only negotiation through the real scheduler."""
    bridge = _bridge()
    case, cell, plugin, result, evidence, harness = _run_live(
        bridge, tmp_path, case_id="agenticpay.bilateral.basic.task1", suffix="basic", rounds=_BASIC_ROUNDS
    )

    assert result.terminal["reason"] == "agreed"
    assert result.terminal["agreed_price"] == 100.0
    assert harness.exhausted is True

    evidence.seal()
    evidence.audit_reconciliation()
    events = evidence.read_events()
    served = [e for e in events if e.event_type == "agenticpay_bilateral_decision_served"]
    # One sealed decision per logical action: 2 rounds x (buyer + seller) = 4.
    assert len(served) == 4 == result.logical_action_count
    sealed_responses = [evidence.read_event_payload(e)["response"] for e in served]
    recorded = record_episode(result, case=case)
    assert recorded.case_sha256 == case.content_sha256
    assert [decision.response for decision in recorded.decisions] == sealed_responses


def test_a_contract_mode_negotiation_runs_end_to_end_with_sealed_evidence(tmp_path: Path) -> None:
    """Episode 2/2: a one-round contract-mode negotiation through the real scheduler."""
    bridge = _bridge()
    case, cell, plugin, result, evidence, harness = _run_live(
        bridge,
        tmp_path,
        case_id="agenticpay.bilateral.realistic.s01_beauty_product",
        suffix="contract",
        rounds=[(_CONTRACT, _CONTRACT)],
    )

    assert result.terminal["reason"] == "agreed"
    assert result.terminal["agreed_contract"] is not None
    assert harness.exhausted is True

    evidence.seal()
    evidence.audit_reconciliation()
    served = [
        e for e in evidence.read_events() if e.event_type == "agenticpay_bilateral_decision_served"
    ]
    assert len(served) == 2 == result.logical_action_count


def test_replay_from_a_json_round_tripped_record_reproduces_the_live_run_byte_identically(
    tmp_path: Path,
) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, original, evidence, _harness = _run_live(
        bridge, tmp_path, case_id="agenticpay.bilateral.basic.task1", suffix="live", rounds=_BASIC_ROUNDS
    )
    evidence.seal()

    recorded = record_episode(original, case=case)
    # Force a genuine round trip through plain JSON text -- proves replay never
    # depends on reusing the original run's in-memory Python objects.
    recorded = RecordedEpisode.from_json(recorded.to_json())
    assert recorded.case_id == case.case_id

    # A second, independent AgenticpayBridge/plugin -- not the one that produced the
    # original run -- drives the replay.
    replay_bridge = AgenticpayBridge(python_executable=BRIDGE_PYTHON, upstream_root=UPSTREAM_ROOT)
    replay_plugin = AgenticpayBilateralPlugin(upstream_root=UPSTREAM_ROOT, bridge=replay_bridge)
    registry = PluginRegistry()
    register_plugin(registry, plugin=replay_plugin)
    resolved_replay_plugin = registry.resolve_manifest(family_manifest())

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=resolved_replay_plugin, recorded=recorded)
    )

    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is True
    assert comparison.final_state_matches is True, (
        "this family's pinned upstream introduces no wall-clock/random nondeterminism "
        "(see replay.py's module docstring): replay must reproduce byte-identical "
        "final state, not merely content-equal state"
    )
    assert canonical_json_bytes(replayed.final_state) == canonical_json_bytes(
        original.final_state
    )
    assert replayed.terminal["reason"] == "agreed"
    assert replayed.terminal["agreed_price"] == original.terminal["agreed_price"]


def test_replayed_episode_recomputes_every_leaf_from_replayed_state(tmp_path: Path) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, original, evidence, _harness = _run_live(
        bridge, tmp_path, case_id="agenticpay.bilateral.basic.task1", suffix="score", rounds=_BASIC_ROUNDS
    )
    evidence.seal()
    recorded = record_episode(original, case=case)

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=resolved_plugin, recorded=recorded)
    )
    family_case = json.loads(canonical_json_bytes(case.payload))
    scorer = build_scorer(family_case)

    original_scores = score_replayed_episode(scorer=scorer, replayed=original)
    replayed_scores = score_replayed_episode(scorer=scorer, replayed=replayed)

    assert replayed_scores.deal_reached.primary.value == 1.0
    assert replayed_scores.buyer_surplus_share.primary.value == pytest.approx(
        original_scores.buyer_surplus_share.primary.value
    )
    assert replayed_scores.seller_surplus_share.primary.value == pytest.approx(
        original_scores.seller_surplus_share.primary.value
    )
    assert replayed_scores.contract_legality is None  # basic case: no contract leaf


def test_replayed_contract_mode_episode_recomputes_the_contract_legality_leaf(
    tmp_path: Path,
) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, original, evidence, _harness = _run_live(
        bridge,
        tmp_path,
        case_id="agenticpay.bilateral.realistic.s01_beauty_product",
        suffix="score_contract",
        rounds=[(_CONTRACT, _CONTRACT)],
    )
    evidence.seal()
    recorded = record_episode(original, case=case)

    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=resolved_plugin, recorded=recorded)
    )
    family_case = json.loads(canonical_json_bytes(case.payload))
    scorer = build_scorer(family_case)

    scores = score_replayed_episode(scorer=scorer, replayed=replayed)
    assert scores.contract_legality is not None
    assert scores.contract_legality.primary.value == 1.0


def test_replay_and_verify_end_to_end_returns_a_matching_report(tmp_path: Path) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, original, evidence, _harness = _run_live(
        bridge, tmp_path, case_id="agenticpay.bilateral.basic.task1", suffix="e2e", rounds=_BASIC_ROUNDS
    )
    evidence.seal()
    recorded = record_episode(original, case=case)
    family_case = json.loads(canonical_json_bytes(case.payload))
    scorer = build_scorer(family_case)

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
    assert report.scores.deal_reached.primary.value == 1.0
    assert report.comparison is not None and report.comparison.matches is True


def test_replay_case_mismatch_raises_a_typed_replay_error(tmp_path: Path) -> None:
    bridge = _bridge()
    case, cell, resolved_plugin, original, evidence, _harness = _run_live(
        bridge, tmp_path, case_id="agenticpay.bilateral.basic.task1", suffix="mismatch", rounds=_BASIC_ROUNDS
    )
    evidence.seal()
    recorded = record_episode(original, case=case)
    wrong_case_recorded = RecordedEpisode(
        case_id="agenticpay.bilateral.basic.task2",
        case_sha256=recorded.case_sha256,
        decisions=recorded.decisions,
    )

    with pytest.raises(ReplayError, match="recorded episode is for case"):
        asyncio.run(
            replay_episode(cell=cell, case=case, plugin=resolved_plugin, recorded=wrong_case_recorded)
        )


def test_replay_rejects_a_case_with_the_same_id_but_different_content(tmp_path: Path) -> None:
    """Second-review regression (Codex finding 3): a record must bind to the exact
    case content it was captured against, not just the ``case_id`` string. Before
    this fix, a record could be replayed against a freshly hashed ``CaseManifest``
    that shares the original's ``case_id`` but has tampered reservation prices (a
    different ``content_sha256``, paired with a matching new ``PlanCell``), and
    nothing rejected it -- the tampered case was silently replayed and scored as if
    it were the original.
    """
    bridge = _bridge()
    case, cell, resolved_plugin, original, evidence, _harness = _run_live(
        bridge, tmp_path, case_id="agenticpay.bilateral.basic.task1", suffix="tamper", rounds=_BASIC_ROUNDS
    )
    evidence.seal()
    recorded = record_episode(original, case=case)

    from aeread.shared_runner.run.resolver import case_content_sha256

    tampered_payload = json.loads(canonical_json_bytes(case.payload))
    tampered_payload["constructor_kwargs"]["buyer_max_price"] = 999.0
    draft = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": case.case_id,
        "family_id": case.family_id,
        "family_version": case.family_version,
        "split": case.split,
        "world_seed": case.world_seed,
        "seats": [{"id": seat.id, "role": seat.role} for seat in case.seats],
        "episode": {
            "max_logical_actions": case.episode.max_logical_actions,
            "termination": list(case.episode.termination),
        },
        "visibility_policy": case.visibility_policy,
        "payload": tampered_payload,
        "provenance": {
            "generator_id": case.provenance.generator_id,
            "generator_version": case.provenance.generator_version,
            "review_status": case.provenance.review_status,
        },
        "content_sha256": "0" * 64,
    }
    digest = case_content_sha256({**draft, "content_sha256": "0" * 64})
    tampered_case = CaseManifest.from_dict({**draft, "content_sha256": digest})
    assert tampered_case.content_sha256 != case.content_sha256
    tampered_cell = _cell(tampered_case, suffix="tamper_cell")

    with pytest.raises(ReplayError, match="content"):
        asyncio.run(
            replay_episode(
                cell=tampered_cell, case=tampered_case, plugin=resolved_plugin, recorded=recorded
            )
        )


def test_replay_without_an_original_run_still_replays_and_scores(tmp_path: Path) -> None:
    """A genuinely offline replay: no in-memory ``original`` to compare against."""
    bridge = _bridge()
    case, cell, resolved_plugin, original, evidence, _harness = _run_live(
        bridge, tmp_path, case_id="agenticpay.bilateral.basic.task1", suffix="offline", rounds=_BASIC_ROUNDS
    )
    evidence.seal()
    # Round-trip through JSON text -- the record now stands alone, exactly as it
    # would if read back from a durable file with no original run in memory.
    recorded = RecordedEpisode.from_json(record_episode(original, case=case).to_json())
    family_case = json.loads(canonical_json_bytes(case.payload))
    scorer = build_scorer(family_case)

    report = asyncio.run(
        replay_and_verify(
            cell=cell, case=case, plugin=resolved_plugin, scorer=scorer, recorded=recorded
        )
    )

    # Second-review regression (Codex finding 3): with no `original` to compare
    # against, `comparison` is `None` -- there was genuinely no comparison made, so
    # `status` must say so explicitly (`"not_comparable"`), never the same `"match"`
    # a real, checked byte-identical comparison reports.
    assert report.comparison is None
    assert report.status == "not_comparable"
    assert report.scores.deal_reached.primary.value == 1.0


# ---------------------------------------------------------------------------
# Bridge-gated: a real episode driven all the way to a sealed
# EvaluationReceipt through the shared kernel finalizer (kernel_scoring_
# contract_spec.md section 5, migration milestone 3 of 3). This family has
# never produced an EvaluationReceipt before this test: the pinned upstream
# checkout's own scripted response source
# (``ScriptedAgenticpayBilateralHarness``) writes only its own convenience
# event and never produces evidence
# ``task.evaluation.replay_family_scoring_input`` can replay --
# ``EvidenceRecordingAgenticpayHarness`` (above) is what makes this
# reachable. Mirrors ``tests/test_negarena_kernel_finalizer.py``'s
# identically-purposed ``_build_negarena_run_plan``/
# ``_run_negarena_episode_through_finalizer`` shape exactly.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _EvaluationSetup:
    """Minimal ``EvaluationSetup`` (task/evaluation.py) implementation.

    ``prompt_sources``/``pricing`` are never read by
    ``finalize_family_execution`` itself (only by ``execute_plan_cell``'s
    provider-calling path, which this module deliberately bypasses -- the
    episode is driven directly through ``run_episode`` +
    ``EvidenceRecordingAgenticpayHarness``), so both are left empty here.
    """

    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, Any]


_AGENTICPAY_FIXTURE_PROFILE_ID = "agenticpay_unused_fixture_profile_v1"
_AGENTICPAY_FIXTURE_PROVIDER_ID = "agenticpay_unused_fixture_provider"
_AGENTICPAY_FIXTURE_RUNTIME_ID = "aeread.shared_runner.task.execution"


def _build_agenticpay_run_plan(
    *, plugin: AgenticpayBilateralPlugin, case: CaseManifest, family_case: Mapping[str, Any]
) -> tuple[RunPlan, PluginRegistry]:
    """One fully-resolved, sealed agenticpay.bilateral ``RunPlan`` for a
    single contract-mode case.

    ``buyer`` is the tested subject seat (ruling R12); ``seller`` is a
    ``controlled`` (fixed) counterpart -- both share one placeholder agent
    profile, since nothing in this module ever calls a ``ProviderClient``
    (the episode is driven directly through ``run_episode`` +
    ``EvidenceRecordingAgenticpayHarness``), so the profile only needs to be
    schema-valid and admitted, never actually invoked.
    """
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)

    profile = AgentProfile.from_dict(
        {
            "spec_version": "aeread.agent_profile/0.1",
            "profile_id": _AGENTICPAY_FIXTURE_PROFILE_ID,
            "model": {
                "provider": _AGENTICPAY_FIXTURE_PROVIDER_ID,
                "model": "agenticpay-unused-fixture-model-v1",
                "revision": "1.0.0",
                "base_url": None,
            },
            "harness": {"id": "minimal_chat", "version": "1.0", "config": {}},
            "prompt": {
                "prompt_id": "agenticpay_scripted_prompt_v1",
                "sha256": hashlib.sha256(
                    b"agenticpay scripted seats: no prompt is ever sent"
                ).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": _AGENTICPAY_FIXTURE_RUNTIME_ID,
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "agenticpay_scripted_no_reasoning_v1",
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
            "sampling_plan_id": "agenticpay_kernel_finalizer_sample_v1",
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
            "block_id": "agenticpay_kernel_finalizer_block",
            "kind": "controlled",
            "subject_seats": ["buyer"],
            "controlled_profiles": {"seller": profile.profile_id},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    family = family_manifest()
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": "aeread.analysis/0.1",
            "analysis_plan_id": "agenticpay_kernel_finalizer_analysis_v1",
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
            "suite_id": "agenticpay_kernel_finalizer_suite_v1",
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
            "run_spec_id": "agenticpay_kernel_finalizer_run_v1",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id],
            "seat_assignments": {"buyer": profile.profile_id, "seller": profile.profile_id},
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )

    harness_registry = HarnessRegistry()
    for harness in default_harnesses().values():
        harness_registry.register(harness)

    environment_sha256 = hashlib.sha256(
        Path(__file__).parents[1].joinpath(
            "src", "aeread_families", "agenticpay_bilateral", "environment.py"
        ).read_bytes()
    ).hexdigest()
    execution_sha256 = hashlib.sha256(
        Path(__file__).parents[1].joinpath(
            "src", "aeread", "shared_runner", "task", "execution.py"
        ).read_bytes()
    ).hexdigest()
    # Every implementation id one of this case's three actual leaves
    # references (validity-domain predicate, reference implementation,
    # scorer), read straight off the leaves themselves so this can never
    # drift from ``family_manifest``'s own
    # ``_measurement_reference_provider_ids()``. Required for
    # ``EvaluationReceipt``'s own pin/implementation cross-check to pass at
    # all -- this case is contract-mode, so all three leaves (including
    # ``agenticpay_contract_legality``) exist and cover the full declared
    # ``reference_provider_ids`` set.
    deal_leaf = measurement.build_deal_reached_leaf(family_case)
    surplus_leaf = measurement.build_surplus_share_leaf(family_case)
    contract_leaf = measurement.build_contract_legality_leaf(family_case)
    assert contract_leaf is not None
    reference_refs = {
        deal_leaf.estimand.validity_domain.predicate,
        deal_leaf.verifier.reference.implementation,
        deal_leaf.scorer,
        surplus_leaf.estimand.validity_domain.predicate,
        surplus_leaf.verifier.reference.implementation,
        surplus_leaf.scorer,
        contract_leaf.estimand.validity_domain.predicate,
        contract_leaf.verifier.reference.implementation,
        contract_leaf.scorer,
    }
    reference_pins = tuple(
        ImplementationPin.from_dict(
            {
                "component_id": ref.implementation_id,
                "kind": "reference",
                "version": ref.version,
                "sha256": ref.content_sha256,
            }
        )
        for ref in reference_refs
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
                "component_id": _AGENTICPAY_FIXTURE_RUNTIME_ID,
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
            _AGENTICPAY_FIXTURE_PROVIDER_ID: ProviderCapabilities(
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


def _run_agenticpay_episode_through_finalizer(bridge: AgenticpayBridge, tmp_path: Path):
    """Drive one s01_beauty_product contract-mode episode all the way to a
    sealed receipt.

    Returns ``(receipt, evidence, family_case)``.
    """
    case = _case("agenticpay.bilateral.realistic.s01_beauty_product")
    plugin = AgenticpayBilateralPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    family_case = plugin.validate_payload(case.payload)

    plan, registry = _build_agenticpay_run_plan(plugin=plugin, case=case, family_case=family_case)
    cell = plan.cells[0]
    resolved_plugin = registry.resolve_manifest(family_manifest())

    evidence = EvidenceStore(
        tmp_path / "evidence_finalize_receipt",
        run_plan_id=plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_id=f"episode_{cell.cell_id}",
        episode_attempt_id="attempt_1",
    )
    harness = EvidenceRecordingAgenticpayHarness(
        evidence=evidence,
        script=_script(
            [
                ("Hi, let's talk terms.", "Sure, what did you have in mind?"),
                (_CONTRACT, _CONTRACT),
            ]
        ),
    )
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=harness)
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
    return receipt, evidence, family_case


def test_finalize_wires_agenticpay_to_the_shared_family_finalizer(tmp_path: Path) -> None:
    """This family has never produced an ``EvaluationReceipt`` before this
    test (spec section 5, migration milestone 3 of 3): drives one small,
    real, bridge-backed contract-mode episode end to end through the real
    finalizer and asserts a receipt comes back carrying EXACTLY this
    family's three declared finalize-time leaves and the declared primary --
    not merely that a receipt came back.
    """
    bridge = _bridge()
    receipt, evidence, _family_case = _run_agenticpay_episode_through_finalizer(bridge, tmp_path)

    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"
    assert receipt.replay_level == "state_and_score"
    assert receipt.primary_leaf_id == measurement.SURPLUS_SHARE_LEAF_ID
    assert {score.leaf.leaf_id for score in receipt.scores} == {
        measurement.DEAL_REACHED_LEAF_ID,
        measurement.SURPLUS_SHARE_LEAF_ID,
        measurement.CONTRACT_LEGALITY_LEAF_ID,
    }
    assert receipt.inapplicable_leaf_ids == ()
    assert receipt.deferred_leaf_ids == ()

    surplus = next(
        score for score in receipt.scores if score.leaf.leaf_id == measurement.SURPLUS_SHARE_LEAF_ID
    )
    assert surplus.status == "ok"
    assert surplus.primary is not None
    assert surplus.primary.value == pytest.approx(0.6 / 1.2)  # buyer's own share
    assert surplus.utility_by_seat["buyer"].value == surplus.primary.value

    deal = next(
        score for score in receipt.scores if score.leaf.leaf_id == measurement.DEAL_REACHED_LEAF_ID
    )
    assert deal.status == "ok"
    assert deal.primary.value == 1.0

    legality = next(
        score
        for score in receipt.scores
        if score.leaf.leaf_id == measurement.CONTRACT_LEGALITY_LEAF_ID
    )
    assert legality.status == "ok"
    assert legality.primary.value == 1.0

    evidence_refs = {score.evidence_refs for score in receipt.scores}
    assert len(evidence_refs) == 1

    # Evidence really was sealed with a durable receipt on disk.
    assert evidence.verify_seal() == receipt.evidence
    receipt_path = evidence.root / "evaluation_receipt.json"
    assert receipt_path.is_file()
    assert receipt_path.read_bytes() == canonical_json_bytes(receipt) + b"\n"
