"""Tests for the amazonbarg.bilateral offline replayer (replay.py, milestone 3).

All five QC Gate-2 goldens (docs/amazonbarg_adapter_spec.md section 4) are
each run once, live, through
``aeread_families.amazonbarg.harness.ScriptedAmazonbargHarness`` and the
real scheduler, recorded, JSON round-tripped, and replayed through a
SECOND, independent ``AmazonbargPlugin`` instance -- with zero further
model/network calls -- and asserted to reproduce state and score
byte-identically (spec section 3, milestone 3's own acceptance bar).
Originally only goldens 1 and 5 were replayed this way (the milestone's own
"at least 2 full episodes" acceptance bar); goldens 2, 3, and 4 were added
per docs/amazonbarg_review_claude.md finding W1, since golden 4 in
particular is the golden whose whole point is "no protected state changed
on invalid input" and had never been proven at the replay level before.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

import pytest

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.task.execution import CanonicalResponse, CellExecution, EvidenceStore
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
from aeread.shared_runner.task.evaluation import finalize_family_execution
from aeread.shared_runner.task.scheduler import EpisodeResult, run_episode
from aeread_families.amazonbarg import cases as amazonbarg_cases
from aeread_families.amazonbarg import environment as amazonbarg_environment
from aeread_families.amazonbarg import measurement as m
from aeread_families.amazonbarg.environment import (
    BUYER_PHASE,
    PLUGIN_ID,
    SCORER_ID,
    SELLER_PHASE,
    AmazonbargPlugin,
    family_manifest,
    register_plugin,
)
from aeread_families.amazonbarg.harness import ScriptedAmazonbargHarness
from aeread_families.amazonbarg.replay import (
    RecordedDecision,
    RecordedEpisode,
    RecordedResponseSource,
    ReplayError,
    assert_replay_matches,
    compare_episode_results,
    record_episode,
    record_episode_from_evidence,
    replay_and_verify,
    replay_episode,
    score_replayed_episode,
)


def _upstream_root() -> Path:
    """The pinned upstream checkout path -- may not exist on disk.

    Unlike this function's pre-fix form, this never skips at import time
    (codex-review finding 6): a missing checkout is caught per-test by
    ``conftest.py``'s ``pytest_collection_modifyitems`` hook instead, which
    skips only the tests that actually need it -- tests marked
    ``@pytest.mark.no_upstream_checkout_required`` (verified independently to
    touch no upstream bytes) still run and pass even when this path does not
    exist.
    """
    candidate = os.environ.get(
        "AEREAD_AMAZONBARG_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-amazonbarg",
    )
    return Path(candidate)


UPSTREAM_ROOT = _upstream_root()
CASES_DIR = Path("cases/amazonbarg/pilot")


def _case(codename: str) -> CaseManifest:
    case_id = amazonbarg_cases.case_id_for_codename(codename)
    path = CASES_DIR / f"{case_id}.json"
    if not path.is_file():
        pytest.skip(f"checked-in case file not found at {path}")
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_amazonbarg_replay_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_amazonbarg_replay",
        suite_version="0.1.0",
        block_id="block_amazonbarg_replay",
        sampling_plan_id="sampling_amazonbarg_replay",
        analysis_plan_id="analysis_amazonbarg_replay",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_amazonbarg_replay_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType({"buyer": "scripted_buyer", "seller": "scripted_seller"}),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _evidence(tmp_path: Path, *, suffix: str) -> EvidenceStore:
    return EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_amazonbarg_replay_{suffix}",
        cell_id=f"cell_amazonbarg_replay_{suffix}",
        episode_id=f"episode_amazonbarg_replay_{suffix}",
        episode_attempt_id="attempt_1",
    )


def _registry_plugin() -> tuple[PluginRegistry, AmazonbargPlugin, AmazonbargPlugin]:
    """A fresh plugin/registry pair, returning the resolved plugin plus the
    underlying real plugin object (for ``validate_payload``/``build_scorer``)."""
    plugin = AmazonbargPlugin(upstream_root=UPSTREAM_ROOT)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    return registry, registry.resolve_manifest(family_manifest()), plugin


GOLDEN_1_SCRIPT = [
    (BUYER_PHASE, "buyer", {"content": "Thought: t\nTalk: hi\nAction: [BUY] $120 (1x home-kitchen_2)"}),
    (SELLER_PHASE, "seller", {"content": "Thought: t\nTalk: ok\nAction: [SELL] $150 (1x home-kitchen_2)"}),
    (BUYER_PHASE, "buyer", {"content": "Thought: t\nTalk: deal?\nAction: [BUY] $135 (1x home-kitchen_2)"}),
    (SELLER_PHASE, "seller", {"content": "Thought: t\nTalk: yes\nAction: [DEAL] $135 (1x home-kitchen_2)"}),
]
GOLDEN_2_SCRIPT = [
    (BUYER_PHASE, "buyer", {"content": "Thought: t\nTalk: hi\nAction: [BUY] $61.5 (1x home-kitchen_3)"}),
    (SELLER_PHASE, "seller", {"content": "Thought: t\nTalk: ok\nAction: [DEAL] $61.5 (1x home-kitchen_3)"}),
]
GOLDEN_3_SCRIPT = [
    (BUYER_PHASE, "buyer", {"content": "Thought: t\nTalk: hi\nAction: [BUY] $400 (1x home-kitchen_5)"}),
    (SELLER_PHASE, "seller", {"content": "Thought: t\nTalk: ok\nAction: [SELL] $480 (1x home-kitchen_5)"}),
    (BUYER_PHASE, "buyer", {"content": "Thought: t\nTalk: deal?\nAction: [BUY] $480 (1x home-kitchen_5)"}),
    (SELLER_PHASE, "seller", {"content": "Thought: t\nTalk: yes\nAction: [DEAL] $480 (1x home-kitchen_5)"}),
]
# The malformed-action golden -- previously never replayed at all (see
# docs/amazonbarg_review_claude.md finding W1): a single decision, no
# seller-phase turn ever served, no phantom deal ever recorded.
GOLDEN_4_SCRIPT = [
    (BUYER_PHASE, "buyer", {"content": "Thought: t\nTalk: no action line here"}),
]
GOLDEN_5_SCRIPT = [
    (BUYER_PHASE, "buyer", {"content": "Thought: t\nTalk: hi\nAction: [BUY] $850 (1x toys-games_22)"}),
    (SELLER_PHASE, "seller", {"content": "Thought: t\nTalk: no\nAction: [REJECT]"}),
    (BUYER_PHASE, "buyer", {"content": "Thought: t\nTalk: bye\nAction: [QUIT]"}),
]

# kernel_scoring_contract_spec.md section 6 / ruling R7: a paired-history
# fixture for the same case (home-kitchen_2) as GOLDEN_1_SCRIPT, closing at
# the identical $135 deal through genuinely different intermediate offers
# (different opening bids and counter-offers, different "Talk:" text).
# Verified directly against the real bridge before being wired in here
# (never merely asserted): `outcome()` (termination_reason,
# terminating_actor, turns_completed, message_count) is byte-identical to
# GOLDEN_1_SCRIPT's, and `phase_instances` genuinely differ, and upstream's
# own delegated `D` (the realized deal price) is identical -- $135 in both
# -- which is exactly what the two forced-`terminal_state` bound leaves'
# `primary` reads (see measurement.py's `_score_bound`), so those two leaves
# stay invariant across the pair while the three genuinely
# `input_scope="trajectory"` leaves are free to (and, for
# `amazonbarg_deal_authenticity`/`amazonbarg_zopa_membership`, in this pair,
# do not need to) differ.
GOLDEN_1_PAIRED_HISTORY_SCRIPT = [
    (BUYER_PHASE, "buyer", {"content": "Thought: t2\nTalk: yo\nAction: [BUY] $100 (1x home-kitchen_2)"}),
    (SELLER_PHASE, "seller", {"content": "Thought: t2\nTalk: nope\nAction: [SELL] $160 (1x home-kitchen_2)"}),
    (BUYER_PHASE, "buyer", {"content": "Thought: t2\nTalk: final\nAction: [BUY] $135 (1x home-kitchen_2)"}),
    (SELLER_PHASE, "seller", {"content": "Thought: t2\nTalk: fine\nAction: [DEAL] $135 (1x home-kitchen_2)"}),
]


def _run_live(codename: str, script, tmp_path: Path, *, suffix: str):
    case = _case(codename)
    cell = _cell(case, suffix=suffix)
    _registry, resolved_plugin, plugin = _registry_plugin()
    evidence = _evidence(tmp_path, suffix=suffix)
    harness = ScriptedAmazonbargHarness(evidence=evidence, script=script)
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=harness)
    )
    assert harness.exhausted
    assert harness.sealed
    return case, cell, resolved_plugin, plugin, result


# ---------------------------------------------------------------------------
# Pure, structural: RecordedEpisode/RecordedResponseSource round-tripping.
# ---------------------------------------------------------------------------


@pytest.mark.no_upstream_checkout_required
def test_recorded_episode_round_trips_through_plain_json() -> None:
    decision = RecordedDecision(
        phase_id=BUYER_PHASE, seat_id="buyer", response={"content": "hello"}
    )
    episode = RecordedEpisode(case_id="amazonbarg.bilateral.home-kitchen_2", decisions=(decision,))

    text = episode.to_json()
    restored = RecordedEpisode.from_json(text)

    assert restored.case_id == episode.case_id
    assert len(restored.decisions) == 1
    assert restored.decisions[0].phase_id == BUYER_PHASE
    assert restored.decisions[0].seat_id == "buyer"
    assert restored.decisions[0].response == {"content": "hello"}


@pytest.mark.no_upstream_checkout_required
def test_recorded_response_source_enforces_ordering_and_reports_exhaustion() -> None:
    decisions = (
        RecordedDecision(phase_id=BUYER_PHASE, seat_id="buyer", response={"content": "hi"}),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = BUYER_PHASE
        seat_id = "buyer"

    response = asyncio.run(source(_Request()))
    assert response == {"content": "hi"}
    assert source.exhausted is True

    with pytest.raises(ReplayError, match="exhausted"):
        asyncio.run(source(_Request()))


@pytest.mark.no_upstream_checkout_required
def test_recorded_response_source_rejects_phase_seat_mismatch() -> None:
    decisions = (
        RecordedDecision(phase_id=SELLER_PHASE, seat_id="seller", response={"content": "ok"}),
    )
    source = RecordedResponseSource(decisions)

    class _Request:
        phase_id = BUYER_PHASE
        seat_id = "buyer"

    with pytest.raises(ReplayError, match="does not match"):
        asyncio.run(source(_Request()))


@pytest.mark.no_upstream_checkout_required
def test_compare_episode_results_reports_specific_mismatches_not_one_boolean() -> None:
    """A synthetic mismatch (mutated terminal, identical state hashes)."""

    class _FakeInstance:
        def __init__(self, phase_instance_id: str, post_state_sha256: str) -> None:
            self.phase_instance_id = phase_instance_id
            self.pre_state_sha256 = "a" * 64
            self.post_state_sha256 = post_state_sha256

    class _Fake:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    shared_instance = _FakeInstance("pi_1", "b" * 64)
    original = _Fake(
        phase_instances=(shared_instance,),
        terminal={"reason": "deal"},
        outcome={"termination_reason": "deal"},
        final_state={"turn_index": 2},
    )
    replayed = _Fake(
        phase_instances=(shared_instance,),
        terminal={"reason": "quit"},
        outcome={"termination_reason": "deal"},
        final_state={"turn_index": 2},
    )

    comparison = compare_episode_results(original, replayed)

    assert comparison.state_hashes_match is True
    assert comparison.terminal_matches is False
    assert comparison.outcome_matches is True
    assert comparison.final_state_matches is True
    assert comparison.matches is False
    with pytest.raises(ReplayError, match="terminal record differs"):
        assert_replay_matches(comparison)


def test_replay_case_mismatch_raises_a_typed_replay_error(tmp_path: Path) -> None:
    case, cell, resolved_plugin, _plugin, original = _run_live(
        "home-kitchen_2", GOLDEN_1_SCRIPT, tmp_path, suffix="mismatch"
    )
    recorded = record_episode(original)
    wrong_case = RecordedEpisode(
        case_id="amazonbarg.bilateral.home-kitchen_999", decisions=recorded.decisions
    )

    with pytest.raises(ReplayError, match="not"):
        asyncio.run(
            replay_episode(cell=cell, case=case, plugin=resolved_plugin, recorded=wrong_case)
        )


def test_record_episode_from_evidence_reads_the_sealed_disk_store_not_memory(
    tmp_path: Path,
) -> None:
    """Codex-review finding 3: replay's own production path must actually
    read the durable, hash-chained ``EvidenceStore`` -- not only the live
    process's own in-memory ``EpisodeResult``.

    ``docs/amazonbarg_adapter_spec.md:22`` claims ``replay.py`` "reproduces a
    sealed episode's state and score with zero further model/network
    calls" -- before this fix, nothing in ``replay.py`` ever imported,
    opened, or read an ``EvidenceStore`` at all, so that claim was not
    backed by any read of the durable evidence. This test reopens the
    evidence directory as a wholly independent, read-only store
    (``EvidenceStore.audit_existing``, never the harness's own live
    object) and drives the real replay from that read alone -- the
    production path itself, not the in-memory shortcut.
    """
    case, cell, resolved_plugin, _plugin, original = _run_live(
        "home-kitchen_2", GOLDEN_1_SCRIPT, tmp_path, suffix="from_evidence"
    )
    evidence_root = tmp_path / "evidence_from_evidence"

    audited = EvidenceStore.audit_existing(evidence_root)
    recorded = record_episode_from_evidence(audited, case_id=case.case_id)

    # Must agree exactly with the in-memory shortcut -- proving the two
    # really do reconstruct the same decision log, not merely asserting the
    # new path works in isolation.
    from_memory = record_episode(original)
    assert recorded.to_dict() == from_memory.to_dict()

    _replay_registry, resolved_replay_plugin, _replay_plugin = _registry_plugin()
    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=resolved_replay_plugin, recorded=recorded)
    )
    comparison = compare_episode_results(original, replayed)
    assert_replay_matches(comparison)  # never raises for a genuine disk-sourced replay


def test_record_episode_from_evidence_detects_tampering_on_disk(tmp_path: Path) -> None:
    """The concrete failure scenario finding 3 named: "corrupting or
    deleting the sealed EvidenceStore on disk after a test run would not
    affect any assertion." Tampering with one sealed artifact's bytes on
    disk must now be caught loudly, not silently accepted."""
    case, _cell, _resolved_plugin, _plugin, _original = _run_live(
        "home-kitchen_2", GOLDEN_1_SCRIPT, tmp_path, suffix="tamper_evidence"
    )
    evidence_root = tmp_path / "evidence_tamper_evidence"
    artifact_paths = sorted((evidence_root / "artifacts" / "sha256").glob("*/*"))
    assert artifact_paths, "expected at least one sealed decision artifact on disk"
    artifact_paths[0].write_bytes(artifact_paths[0].read_bytes() + b"\ntampered")

    # Caught the moment the tampered store is opened/audited at all (before
    # `record_episode_from_evidence` even gets a chance to read an event
    # payload) -- exactly the concrete failure this finding named as
    # currently undetectable.
    with pytest.raises(Exception):
        audited = EvidenceStore.audit_existing(evidence_root)
        record_episode_from_evidence(audited, case_id=case.case_id)


# ---------------------------------------------------------------------------
# Live, end-to-end: two full episodes, sealed, recorded, replayed by a
# SECOND, independent plugin instance, with zero further model calls.
# ---------------------------------------------------------------------------


def _replay_and_compare(codename: str, script, tmp_path: Path, *, suffix: str):
    case, cell, _resolved_plugin, plugin, original = _run_live(
        codename, script, tmp_path, suffix=f"{suffix}_live"
    )

    recorded = record_episode(original)
    # Force a genuine round trip through plain JSON text -- proves replay
    # never depends on reusing the original run's in-memory Python objects.
    recorded = RecordedEpisode.from_json(recorded.to_json())
    assert recorded.case_id == case.case_id

    # A second, independent AmazonbargPlugin -- not the one that produced
    # the original run -- drives the replay.
    _replay_registry, resolved_replay_plugin, replay_plugin = _registry_plugin()
    replayed: EpisodeResult = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=resolved_replay_plugin, recorded=recorded)
    )

    comparison = compare_episode_results(original, replayed)
    assert_replay_matches(comparison)  # never raises for a genuine replay
    return case, cell, plugin, replay_plugin, original, replayed, comparison


def test_golden_1_replay_reproduces_state_byte_identically(tmp_path: Path) -> None:
    case, _cell_, _plugin, _replay_plugin, original, replayed, comparison = _replay_and_compare(
        "home-kitchen_2", GOLDEN_1_SCRIPT, tmp_path, suffix="golden1"
    )

    assert comparison.matches is True
    # Strengthened guarantee vs. tau3_retail (see replay.py's module
    # docstring): AmazonbargPlugin.step() stamps no wall-clock timestamp
    # anywhere, so the RAW, byte-exact final state reproduces too, not
    # merely its content.
    assert comparison.final_state_matches is True
    assert comparison.original_final_state_sha256 == comparison.replayed_final_state_sha256
    assert canonical_json_bytes(replayed.final_state) == canonical_json_bytes(original.final_state)
    assert replayed.terminal["reason"] == "deal"


def test_golden_2_replay_reproduces_state_byte_identically(tmp_path: Path) -> None:
    case, _cell_, _plugin, _replay_plugin, original, replayed, comparison = _replay_and_compare(
        "home-kitchen_3", GOLDEN_2_SCRIPT, tmp_path, suffix="golden2"
    )

    assert comparison.matches is True
    assert comparison.final_state_matches is True
    assert canonical_json_bytes(replayed.final_state) == canonical_json_bytes(original.final_state)
    assert replayed.terminal["reason"] == "deal"


def test_golden_3_replay_reproduces_state_byte_identically(tmp_path: Path) -> None:
    case, _cell_, _plugin, _replay_plugin, original, replayed, comparison = _replay_and_compare(
        "home-kitchen_5", GOLDEN_3_SCRIPT, tmp_path, suffix="golden3"
    )

    assert comparison.matches is True
    assert comparison.final_state_matches is True
    assert canonical_json_bytes(replayed.final_state) == canonical_json_bytes(original.final_state)
    assert replayed.terminal["reason"] == "deal"


def test_golden_4_replay_reproduces_state_byte_identically(tmp_path: Path) -> None:
    """The malformed-action golden, now proven at the replay level too (see
    docs/amazonbarg_review_claude.md finding W1): a second, independent
    ``AmazonbargPlugin`` re-parses the same malformed reply, halts after the
    same single decision, and reproduces byte-identical state -- no
    seller-phase turn, no phantom deal, on either the original or the
    replayed run."""
    case, _cell_, _plugin, _replay_plugin, original, replayed, comparison = _replay_and_compare(
        "home-kitchen_4", GOLDEN_4_SCRIPT, tmp_path, suffix="golden4"
    )

    assert comparison.matches is True
    assert comparison.final_state_matches is True
    assert canonical_json_bytes(replayed.final_state) == canonical_json_bytes(original.final_state)
    assert replayed.terminal["reason"] == "action_error"
    assert replayed.terminal["terminating_actor"] == "buyer"
    assert replayed.terminal["turns_completed"] == 0
    assert len(replayed.final_state["history"]) == 1
    assert len(replayed.final_state["history"][0]) == 1


def test_golden_5_replay_reproduces_state_byte_identically(tmp_path: Path) -> None:
    case, _cell_, _plugin, _replay_plugin, original, replayed, comparison = _replay_and_compare(
        "toys-games_22", GOLDEN_5_SCRIPT, tmp_path, suffix="golden5"
    )

    assert comparison.matches is True
    assert comparison.final_state_matches is True
    assert canonical_json_bytes(replayed.final_state) == canonical_json_bytes(original.final_state)
    assert replayed.terminal["reason"] == "quit"


def test_golden_1_replay_recomputes_score_byte_identically_for_both_seats(
    tmp_path: Path,
) -> None:
    case, _cell_, plugin, replay_plugin, original, replayed, _comparison = _replay_and_compare(
        "home-kitchen_2", GOLDEN_1_SCRIPT, tmp_path, suffix="golden1_score"
    )
    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)
    replay_family_case = replay_plugin.validate_payload(case.payload)
    replay_scorer = replay_plugin.build_scorer(replay_family_case)

    original_metrics = m.compute_upstream_metrics(
        upstream_root=UPSTREAM_ROOT,
        family_case=family_case,
        history=json.loads(canonical_json_bytes(original.final_state["history"])),
    )
    assert original_metrics["D"] == pytest.approx(135.0)

    for tested_seat in ("buyer", "seller"):
        original_scores = scorer.score_all(
            metrics_output=original_metrics, tested_seat=tested_seat
        )
        replayed_scores = score_replayed_episode(
            upstream_root=UPSTREAM_ROOT,
            scorer=replay_scorer,
            replayed=replayed,
            tested_seat=tested_seat,
        )
        assert set(replayed_scores) == set(original_scores)
        for leaf_id, envelope in original_scores.items():
            assert replayed_scores[leaf_id] == envelope


def test_golden_4_replay_recomputes_an_invalid_measurement_score_identically(
    tmp_path: Path,
) -> None:
    """The malformed-action golden's score, recomputed from the *replayed*
    history -- never read back from a stored number -- reproduces the same
    ``invalid_measurement`` seal on every leaf gated by
    ``amazonbarg_deal_authenticity``'s own ``wrongAction=1`` verdict (see
    docs/amazonbarg_review_claude.md finding W1: this is the golden whose
    whole point is "no protected state changed on invalid input", now
    proven at the replay/score level too, not merely the plain
    ``run_episode`` level)."""
    case, _cell_, plugin, replay_plugin, original, replayed, _comparison = _replay_and_compare(
        "home-kitchen_4", GOLDEN_4_SCRIPT, tmp_path, suffix="golden4_score"
    )
    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)
    replay_family_case = replay_plugin.validate_payload(case.payload)
    replay_scorer = replay_plugin.build_scorer(replay_family_case)

    original_metrics = m.compute_upstream_metrics(
        upstream_root=UPSTREAM_ROOT,
        family_case=family_case,
        history=json.loads(canonical_json_bytes(original.final_state["history"])),
    )
    assert original_metrics["wrongAction"] == 1
    assert "D" not in original_metrics

    original_scores = scorer.score_all(metrics_output=original_metrics, tested_seat="buyer")
    replayed_scores = score_replayed_episode(
        upstream_root=UPSTREAM_ROOT, scorer=replay_scorer, replayed=replayed, tested_seat="buyer"
    )

    assert original_scores["amazonbarg_deal_authenticity_leaf"].primary.value == 0.0
    for leaf_id in ("amazonbarg_zopa_membership_leaf", "amazonbarg_deal_lower_bound_leaf", "amazonbarg_deal_upper_bound_leaf", "amazonbarg_bargained_ratio_leaf"):
        assert original_scores[leaf_id].status == "invalid_measurement"
    for leaf_id, envelope in original_scores.items():
        assert replayed_scores[leaf_id] == envelope


def test_golden_5_replay_recomputes_a_degenerate_score_identically(tmp_path: Path) -> None:
    case, _cell_, plugin, replay_plugin, original, replayed, _comparison = _replay_and_compare(
        "toys-games_22", GOLDEN_5_SCRIPT, tmp_path, suffix="golden5_score"
    )
    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)
    replay_family_case = replay_plugin.validate_payload(case.payload)
    replay_scorer = replay_plugin.build_scorer(replay_family_case)

    original_metrics = m.compute_upstream_metrics(
        upstream_root=UPSTREAM_ROOT,
        family_case=family_case,
        history=json.loads(canonical_json_bytes(original.final_state["history"])),
    )
    original_scores = scorer.score_all(metrics_output=original_metrics, tested_seat="buyer")
    replayed_scores = score_replayed_episode(
        upstream_root=UPSTREAM_ROOT, scorer=replay_scorer, replayed=replayed, tested_seat="buyer"
    )

    assert original_scores["amazonbarg_zopa_membership_leaf"].status == "invalid_measurement"
    for leaf_id, envelope in original_scores.items():
        assert replayed_scores[leaf_id] == envelope


def test_replay_and_verify_end_to_end_returns_a_matching_report(tmp_path: Path) -> None:
    case, cell, _resolved_plugin, plugin, original = _run_live(
        "home-kitchen_2", GOLDEN_1_SCRIPT, tmp_path, suffix="e2e_live"
    )
    recorded = record_episode(original)
    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)

    _replay_registry, resolved_replay_plugin, replay_plugin = _registry_plugin()

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            plugin=resolved_replay_plugin,
            upstream_root=UPSTREAM_ROOT,
            scorer=scorer,
            recorded=recorded,
            tested_seat="buyer",
            original=original,
        )
    )

    assert report.status == "match"
    assert report.final_state_sha256 == original.phase_instances[-1].post_state_sha256
    assert report.scores["amazonbarg_bargained_ratio_leaf"].primary.value == pytest.approx(
        0.49, abs=0.01
    )


def test_replay_and_verify_reports_not_comparable_rather_than_a_fabricated_match(
    tmp_path: Path,
) -> None:
    """Codex-review finding 4: a genuinely offline replay (no ``original``
    run in memory to compare against) must report a distinct, honest
    status -- never the same ``"match"`` string a byte-identical
    state-hash comparison reports. ``replay_and_verify``'s own docstring
    already promised this ("an explicit, typed 'not comparable' rather
    than a fabricated match"); ``ReplayReport.status`` previously
    contradicted it by falling through to ``"match"`` whenever
    ``comparison is None``."""
    case, cell, _resolved_plugin, plugin, original = _run_live(
        "home-kitchen_2", GOLDEN_1_SCRIPT, tmp_path, suffix="e2e_offline"
    )
    recorded = record_episode(original)
    family_case = plugin.validate_payload(case.payload)
    scorer = plugin.build_scorer(family_case)

    _replay_registry, resolved_replay_plugin, _replay_plugin = _registry_plugin()

    report = asyncio.run(
        replay_and_verify(
            cell=cell,
            case=case,
            plugin=resolved_replay_plugin,
            upstream_root=UPSTREAM_ROOT,
            scorer=scorer,
            recorded=recorded,
            tested_seat="buyer",
            original=None,
        )
    )

    assert report.comparison is None
    assert report.status == "not_comparable"
    assert report.status != "match"


# ---------------------------------------------------------------------------
# Honest, documented limitation (see replay.py module docstring): unlike
# tau3_retail's Tau3RetailPlugin.step() (which independently re-executes
# and cross-checks every tool call against a live bridge), amazonbarg has
# no tool calls to cross-check -- a tampered recorded response is simply
# re-parsed and produces a genuinely different trajectory, never a raised
# exception.
# ---------------------------------------------------------------------------


def test_replay_of_a_tampered_response_diverges_rather_than_raising(tmp_path: Path) -> None:
    case, cell, _resolved_plugin, _plugin, original = _run_live(
        "home-kitchen_2", GOLDEN_1_SCRIPT, tmp_path, suffix="tamper"
    )
    recorded = record_episode(original)

    # Change only the DEAL's price text, never its action type -- so the
    # replayed episode still terminates the same way ("deal", after the
    # same 4 decisions), and this test genuinely isolates "diverges" from
    # "raises" (a tampered action TYPE, e.g. DEAL -> REJECT, changes how
    # many decisions the phase graph asks for at all, which is a different,
    # already-covered failure mode -- RecordedResponseSource's own
    # exhaustion check, not a silent divergence).
    tampered_decisions = list(recorded.decisions)
    last = tampered_decisions[-1]
    assert "[DEAL] $135" in last.response["content"]
    tampered_decisions[-1] = RecordedDecision(
        phase_id=last.phase_id,
        seat_id=last.seat_id,
        response={
            "content": last.response["content"].replace(
                "[DEAL] $135 (1x home-kitchen_2)", "[DEAL] $140 (1x home-kitchen_2)"
            )
        },
    )
    tampered = RecordedEpisode(case_id=recorded.case_id, decisions=tuple(tampered_decisions))

    _replay_registry, resolved_replay_plugin, _replay_plugin = _registry_plugin()
    replayed = asyncio.run(
        replay_episode(cell=cell, case=case, plugin=resolved_replay_plugin, recorded=tampered)
    )

    comparison = compare_episode_results(original, replayed)
    assert comparison.matches is False
    assert comparison.final_state_matches is False
    assert replayed.terminal["reason"] == "deal"  # still a deal -- only its price diverged
    original_last_action = original.final_state["history"][-1][-1]["action"]
    replayed_last_action = replayed.final_state["history"][-1][-1]["action"]
    assert original_last_action != replayed_last_action


# ---------------------------------------------------------------------------
# Evidence-complete episode driving (kernel_scoring_contract_spec.md
# migration milestone 3): a response source that ALSO writes the full
# generic evidence trail ``task.evaluation.replay_family_scoring_input``
# needs to replay, plus a real, ``resolve_run_plan``-resolved ``RunPlan`` --
# both required to drive ``task.evaluation.finalize_family_execution`` for
# this family for the first time, and reused by
# ``tests/test_shared_runner_scoring_contract.py`` for its own paired-
# history fixtures. Mirrors govsim's identically-purposed
# ``EvidenceRecordingGovsimHarness``/``build_govsim_setup``
# (``tests/test_govsim_replay.py``, kernel_scoring_contract_spec.md's own
# reference migration) field-for-field -- both classes are entirely generic
# over ``task.scheduler``'s ``ResponseSource`` lifecycle hooks, so nothing
# here is amazonbarg-specific except the ``answer`` callable and the
# resolved ``RunPlan``'s own family/case/profile wiring below.
# ---------------------------------------------------------------------------


class EvidenceRecordingAmazonbargHarness:
    """A ``run_episode`` response source that writes the full generic
    replay-required evidence trail (``logical_action_started``,
    ``action_attempt_succeeded``, ``action_parsed``,
    ``action_legality_checked``, ``logical_action_succeeded``,
    ``phase_instance_started``, ``transition_applied``,
    ``phase_instance_succeeded``, ``episode_terminated``,
    ``family_outcome_recorded``) -- exactly the event vocabulary
    ``aeread.shared_runner.task.execution.MinimalChatExecutor``/
    ``AttemptExecutor`` write for every LLM-harness-backed family's own
    evidence, reproduced here without any of that class's provider/retry/
    cost machinery, since every amazonbarg decision is a plain scripted
    dict, never a provider completion.

    ``ScriptedAmazonbargHarness`` (this family's existing scripted response
    source, ``harness.py``) writes only its own convenience event
    (``amazonbarg_decision_served``) and has never produced evidence
    ``aeread.shared_runner.task.evaluation.replay_family_scoring_input`` can
    replay -- ``finalize_family_execution`` calls that replay internally, so
    this class is what makes driving THAT finalizer for this family
    possible at all. ``answer`` supplies the raw scripted decision for one
    request; this class owns only the evidence-recording seam around it,
    mirroring ``AttemptExecutor``'s own event shapes field-for-field.
    """

    def __init__(
        self, *, answer: Callable[[Any], Mapping[str, Any]], evidence: EvidenceStore
    ) -> None:
        self._answer = answer
        self._evidence = evidence

    async def __call__(self, request: Any) -> dict[str, Any]:
        response = dict(self._answer(request))
        self._evidence.append_event(
            "logical_action_started",
            {"request": request},
            phase_instance_id=request.phase_instance_id,
            logical_action_id=request.logical_action_id,
            visibility=f"seat:{request.seat_id}",
        )
        # A CanonicalResponse-shaped placeholder purely for replay provenance
        # (``LogicalActionRecord.response``): amazonbarg's own
        # ``parse_action`` never reads it (the scheduler hands it the raw
        # ``response`` dict returned above, unchanged -- see
        # ``ScriptedAmazonbargHarness``'s identical contract), and replay
        # itself reconstructs ``parse``/``legality`` directly from the
        # "action_parsed"/"action_legality_checked" events below, never
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


def amazonbarg_script_answer(
    script: list[tuple[str, str, Mapping[str, Any]]]
) -> Callable[[Any], Mapping[str, Any]]:
    """An ``answer`` callable for ``EvidenceRecordingAmazonbargHarness`` that
    serves a fixed ordered script exactly like ``ScriptedAmazonbargHarness``
    (``harness.py``) does, but without any evidence-writing of its own --
    this class writes the full generic vocabulary instead (above)."""
    iterator = iter(script)

    def answer(request: Any) -> Mapping[str, Any]:
        expected_phase, expected_seat, response = next(iterator)
        if request.phase_id != expected_phase or request.seat_id != expected_seat:
            raise RuntimeError(
                f"script expected phase={expected_phase!r} seat={expected_seat!r}, "
                f"got phase={request.phase_id!r} seat={request.seat_id!r}"
            )
        return response

    return answer


@dataclass(frozen=True, slots=True)
class AmazonbargSetup:
    """A resolved, provider-free ``RunPlan`` for one amazonbarg case.

    Like govsim's own ``GovsimSetup``, this family's real runtime never
    goes through ``execute_plan_cell``'s harness/provider stack at all --
    every seat is answered directly through ``run_episode``'s
    ``response_source`` (``ScriptedAmazonbargHarness``/
    ``EvidenceRecordingAmazonbargHarness`` above). The declared
    ``minimal_chat`` harness and fixture provider below exist purely to
    satisfy ``resolve_run_plan``'s structural pin/capability checks and are
    never actually invoked.
    """

    plan: RunPlan
    registry: PluginRegistry


_AMAZONBARG_FIXTURE_PROFILE_ID = "amazonbarg_unused_fixture_profile_v1"
_AMAZONBARG_FIXTURE_PROVIDER_ID = "amazonbarg_unused_fixture_provider"
_AMAZONBARG_FIXTURE_RUNTIME_ID = "aeread.shared_runner.task.execution"


def _pin(
    component_id: str, kind: str, source_path: Path, *, version: str = "0.1.0"
) -> ImplementationPin:
    return ImplementationPin.from_dict(
        {
            "component_id": component_id,
            "kind": kind,
            "version": version,
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        }
    )


def build_amazonbarg_setup(
    case: CaseManifest, *, suffix: str, subject_seats: Sequence[str] = ("buyer",)
) -> AmazonbargSetup:
    """Resolve a real, one-cell ``RunPlan`` for ``case`` (spec section 5.4).

    Both seats share one placeholder agent profile: this family's real
    runtime never invokes it (see ``AmazonbargSetup``'s own docstring), so
    the harness/provider it names exist only to satisfy
    ``resolve_run_plan``'s structural checks.

    ``subject_seats`` (ruling R12, kernel_scoring_contract_spec.md) becomes
    the resolved plan's one evaluation block's own ``subject_seats`` --
    defaulting to ``("buyer",)`` alone so a caller that does not pass it
    gets a genuine, single, resolvable tested seat (the shape
    ``amazonbarg_bargained_ratio`` needs to come back ``"ok"``); a caller
    exercising ruling R12 rule 2's ambiguous-seat path passes both seats
    explicitly.
    """
    family = family_manifest()
    seat_ids = ["buyer", "seller"]
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": f"amazonbarg_{suffix}_sample_v1",
            "estimand": "fixed_amazonbarg_case",
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
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": f"amazonbarg_{suffix}_block",
            "kind": "self_play",
            "subject_seats": list(subject_seats),
            "controlled_profiles": {},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": AnalysisPlan.SPEC_VERSION,
            "analysis_plan_id": f"amazonbarg_{suffix}_analysis_v1",
            "estimands": [m.BARGAINED_RATIO_ESTIMAND_ID],
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
            "spec_version": SuiteManifest.SPEC_VERSION,
            "suite_id": f"amazonbarg_{suffix}_suite_v1",
            "version": "1.0.0",
            "family_ids": [family.family.id],
            "case_ids": [case.case_id],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    profile = AgentProfile.from_dict(
        {
            "spec_version": AgentProfile.SPEC_VERSION,
            "profile_id": _AMAZONBARG_FIXTURE_PROFILE_ID,
            "model": {
                "provider": _AMAZONBARG_FIXTURE_PROVIDER_ID,
                "model": "amazonbarg_unused_fixture_model_v1",
                "revision": "1.0.0",
                "base_url": None,
            },
            "harness": {
                "id": "minimal_chat",
                "version": "1.0",
                "config": {},
            },
            "prompt": {
                "prompt_id": f"amazonbarg_{suffix}_prompt_v1",
                "sha256": hashlib.sha256(
                    b"amazonbarg scripted seat: no prompt is ever sent"
                ).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": _AMAZONBARG_FIXTURE_RUNTIME_ID,
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "amazonbarg_scripted_no_reasoning_v1",
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
    run_spec = RunSpec.from_dict(
        {
            "spec_version": RunSpec.SPEC_VERSION,
            "run_spec_id": f"amazonbarg_{suffix}_run_spec_v1",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id],
            "seat_assignments": {seat_id: profile.profile_id for seat_id in seat_ids},
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )

    registry = PluginRegistry()
    register_plugin(registry, upstream_root=UPSTREAM_ROOT)
    harness_registry = HarnessRegistry()
    for harness in default_harnesses().values():
        harness_registry.register(harness)

    environment_path = Path(amazonbarg_environment.__file__)
    execution_path = Path(execution_module.__file__)
    measurement_path = Path(m.__file__)
    upstream_shim_path = measurement_path.with_name("upstream_shim.py")
    # measurement.py declares each of its five leaves' validity-domain
    # predicate and scorer implementation under its own distinct component
    # id (see environment.py's family_manifest() docstring on
    # scoring.reference_provider_ids); every one of those seven must also
    # be pinned here, or EvaluationReceipt._validate_and_freeze_plan_pins
    # rejects the sealed receipt as missing implementations.
    pins = (
        _pin(PLUGIN_ID, "family_plugin", environment_path),
        _pin(SCORER_ID, "scorer", environment_path),
        _pin("minimal_chat", "harness", execution_path, version="1.0"),
        _pin(_AMAZONBARG_FIXTURE_RUNTIME_ID, "runtime", execution_path, version="0.1.0"),
        _pin("amazonbarg_upstream_metrics_bridge", "reference", upstream_shim_path),
        _pin("amazonbarg_base_domain_predicate", "reference", environment_path),
        _pin(m.DEAL_AUTHENTICITY_SCORER_ID, "reference", measurement_path),
        _pin(m.ZOPA_MEMBERSHIP_SCORER_ID, "reference", measurement_path),
        _pin(m.DEAL_LOWER_BOUND_SCORER_ID, "reference", measurement_path),
        _pin(m.DEAL_UPPER_BOUND_SCORER_ID, "reference", measurement_path),
        _pin(m.BARGAINED_RATIO_SCORER_ID, "reference", measurement_path),
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
            _AMAZONBARG_FIXTURE_PROVIDER_ID: ProviderCapabilities(
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
    return AmazonbargSetup(plan=plan, registry=registry)


def test_finalize_wires_amazonbarg_to_the_shared_family_finalizer(tmp_path: Path) -> None:
    """This family has never produced an ``EvaluationReceipt`` before this
    milestone.

    Every other already-migrated family has at least one test driving a
    real episode through ``task.evaluation.finalize_family_execution`` (see
    ``tests/test_govsim_replay.py``'s identically-purposed
    ``test_finalize_wires_govsim_to_the_shared_family_finalizer``);
    amazonbarg had none, because its existing scripted response source
    (``ScriptedAmazonbargHarness``) writes only its own convenience event
    and has never produced evidence ``finalize_family_execution``'s
    internal ``replay_family_scoring_input`` call can replay --
    ``EvidenceRecordingAmazonbargHarness`` (above) is what makes this
    reachable. Drives golden 1 (the same successful $135 Shark-vacuum deal
    every other amazonbarg test file already exercises) end to end through
    the real finalizer.

    The receipt carries every one of this family's five declared
    finalize-time leaves, with the four diagnostics all ``status="ok"`` --
    proving the wiring is genuinely complete, not merely reachable. Ruling
    R12 (kernel_scoring_contract_spec.md) makes which seat a ``RunPlan`` is
    testing reachable via ``FamilyScoringInput.seat_context.subject_seats``
    -- ``build_amazonbarg_setup``'s default ``subject_seats=("buyer",)``
    puts the tested profile in that one seat via the plan's evaluation
    block, so ``AmazonbargScorer.__call__`` resolves ``tested_seat="buyer"``
    and the declared primary and sole admission leaf now comes back
    ``status="ok"``/``inclusion_status="included"`` for the first time
    through this seam: this is the very gap
    docs/amazonbarg_adapter_status.md's "Leaf policy" section previously
    disclosed as "every receipt scored through this exact seam is
    non-admitted today", now resolved. See
    ``test_finalize_reports_ambiguous_subject_seat_honestly_and_does_not_raise``
    below for ruling R12 rule 2's ambiguous-seat path, still honestly
    ``invalid_measurement``/``"excluded"``.
    """
    case = _case("home-kitchen_2")
    setup = build_amazonbarg_setup(case, suffix="finalize_receipt")
    cell = setup.plan.cells[0]
    family = setup.plan.families[0]
    plugin = setup.registry.resolve_manifest(family)

    evidence = EvidenceStore(
        tmp_path / "evidence_finalize_receipt",
        run_plan_id=setup.plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_id=f"episode_{cell.cell_id}",
        episode_attempt_id="attempt_1",
    )
    harness = EvidenceRecordingAmazonbargHarness(
        answer=amazonbarg_script_answer(list(GOLDEN_1_SCRIPT)), evidence=evidence
    )
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=harness)
    )
    execution = CellExecution(
        run_plan_id=setup.plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_attempt_id="attempt_1",
        episode_result=result,
        evidence=evidence,
        action_executions=(),
        total_cost_usd=0.0,
    )

    receipt = finalize_family_execution(setup=setup, execution=execution)

    assert {score.leaf.leaf_id for score in receipt.scores} == {
        m.DEAL_AUTHENTICITY_LEAF_ID,
        m.ZOPA_MEMBERSHIP_LEAF_ID,
        m.DEAL_LOWER_BOUND_LEAF_ID,
        m.DEAL_UPPER_BOUND_LEAF_ID,
        m.BARGAINED_RATIO_LEAF_ID,
    }
    assert receipt.primary_leaf_id == m.BARGAINED_RATIO_LEAF_ID
    evidence_refs = {score.evidence_refs for score in receipt.scores}
    assert len(evidence_refs) == 1

    diagnostics = {
        score.leaf.leaf_id: score
        for score in receipt.scores
        if score.leaf.leaf_id != m.BARGAINED_RATIO_LEAF_ID
    }
    for leaf_id, score in diagnostics.items():
        assert score.status == "ok", f"{leaf_id} unexpectedly invalid: {score.validity.reasons}"

    primary = next(
        score for score in receipt.scores if score.leaf.leaf_id == m.BARGAINED_RATIO_LEAF_ID
    )
    assert primary.status == "ok"
    # Ruling R12 rule 2's singleton identity, tested directly (the kernel
    # enforces it too, at finalize, task/evaluation.py's
    # _enforce_subject_seat_primaries -- this assertion would have failed
    # loudly, not silently, had that enforcement not already run).
    assert primary.primary.value == primary.utility_by_seat["buyer"].value
    assert primary.primary.unit == primary.utility_by_seat["buyer"].unit
    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"


def test_finalize_reports_ambiguous_subject_seat_honestly_and_does_not_raise(
    tmp_path: Path,
) -> None:
    """Ruling R12 rule 2 (kernel_scoring_contract_spec.md): two subject
    seats is ambiguous for a leaf that declares no ``subject_reduction``
    (measurement.py's own module docstring: the ratio is one side's own,
    never blended) -- ``AmazonbargScorer.__call__`` reports this honestly
    as ``invalid_measurement``/``REASON_AMBIGUOUS_SUBJECT_SEAT``, and
    because that envelope's ``status`` is not ``"ok"``,
    ``task/evaluation.py``'s ``_enforce_subject_seat_primaries`` does not
    apply to it at all (it only raises for a status="ok" subject_seat leaf)
    -- ``finalize_family_execution`` itself must not raise here, which this
    test proves simply by not raising."""
    case = _case("home-kitchen_2")
    setup = build_amazonbarg_setup(
        case, suffix="finalize_ambiguous_seat", subject_seats=("buyer", "seller")
    )
    cell = setup.plan.cells[0]
    family = setup.plan.families[0]
    plugin = setup.registry.resolve_manifest(family)

    evidence = EvidenceStore(
        tmp_path / "evidence_finalize_ambiguous_seat",
        run_plan_id=setup.plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_id=f"episode_{cell.cell_id}",
        episode_attempt_id="attempt_1",
    )
    harness = EvidenceRecordingAmazonbargHarness(
        answer=amazonbarg_script_answer(list(GOLDEN_1_SCRIPT)), evidence=evidence
    )
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=harness)
    )
    execution = CellExecution(
        run_plan_id=setup.plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_attempt_id="attempt_1",
        episode_result=result,
        evidence=evidence,
        action_executions=(),
        total_cost_usd=0.0,
    )

    receipt = finalize_family_execution(setup=setup, execution=execution)

    diagnostics = {
        score.leaf.leaf_id: score
        for score in receipt.scores
        if score.leaf.leaf_id != m.BARGAINED_RATIO_LEAF_ID
    }
    for leaf_id, score in diagnostics.items():
        assert score.status == "ok", f"{leaf_id} unexpectedly invalid: {score.validity.reasons}"

    primary = next(
        score for score in receipt.scores if score.leaf.leaf_id == m.BARGAINED_RATIO_LEAF_ID
    )
    assert primary.status == "invalid_measurement"
    assert m.reasons_include(primary.validity, m.REASON_AMBIGUOUS_SUBJECT_SEAT)
    assert receipt.status == "invalid_measurement"
    assert receipt.inclusion_status == "excluded"
