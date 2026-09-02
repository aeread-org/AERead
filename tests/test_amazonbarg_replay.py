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
import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from aeread.shared_runner.execution import EvidenceStore
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import EpisodeResult, run_episode
from aeread_families.amazonbarg import cases as amazonbarg_cases
from aeread_families.amazonbarg import measurement as m
from aeread_families.amazonbarg.environment import (
    BUYER_PHASE,
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
    candidate = os.environ.get(
        "AEREAD_AMAZONBARG_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-amazonbarg",
    )
    root = Path(candidate)
    marker = root / "data" / "AmazonHistoryPrice" / "home-kitchen.json"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream AmazonPriceHistory checkout not found at {root}",
            allow_module_level=True,
        )
    return root


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
