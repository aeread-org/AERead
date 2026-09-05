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
import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from aeread.shared_runner.task.execution import EvidenceStore
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import run_episode
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
