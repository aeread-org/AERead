"""Provider-free scripted-harness coverage for alympics.wac (milestone 3).

Every upstream-gated test here runs the pinned, real ``waterAllocation``/
``Alympics`` checkout in-process (no bridge, no network, no LLM call --
``docs/alympics_adapter_spec.md`` section 1's "No bridge" decision), through
the *real* ``run_episode`` scheduler path -- never a hand-wired shortcut that
calls ``environment.py`` hooks directly. Mirrors
``tests/test_tau3_retail_environment.py``'s ``ScriptedTau3RetailHarness``
coverage, adapted to this family's simpler, tool-free boundary.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from aeread.shared_runner.execution import EvidenceSealedError, EvidenceSeal, EvidenceStore
from aeread.shared_runner.resolver import PlanCell
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import run_episode
from aeread_families.alympics_wac.cases import SEAT_ORDER
from aeread_families.alympics_wac.environment import AlympicsWacPlugin
from aeread_families.alympics_wac.harness import (
    POLICY_FUNCTIONS,
    ScriptedAlympicsWacHarness,
    aggressive_bid,
    baseline_policy_assignment,
    conservative_bid,
    myopic_need_bid,
    proportional_bid,
)


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_ALYMPICS_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-alympics",
    )
    root = Path(candidate)
    marker = root / "src" / "waterAllocation.py"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream Alympics checkout not found at {root}",
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()
CASES_DIR = Path("cases/alympics_wac/base")


def _case(name: str) -> CaseManifest:
    path = CASES_DIR / f"alympics.wac.{name}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_alympics_wac_harness_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_alympics_wac_harness",
        suite_version="0.1.0",
        block_id="block_alympics_wac_harness",
        sampling_plan_id="sampling_alympics_wac_harness",
        analysis_plan_id="analysis_alympics_wac_harness",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_alympics_wac_harness_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(
            {
                seat: f"scripted_{policy}"
                for seat, policy in case.payload["grid_cell"]["policy_assignment"].items()
            }
        ),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _evidence(tmp_path: Path, *, suffix: str) -> EvidenceStore:
    return EvidenceStore(
        tmp_path / f"evidence_{suffix}",
        run_plan_id=f"runplan_alympics_wac_harness_{suffix}",
        cell_id=f"cell_alympics_wac_harness_{suffix}",
        episode_id=f"episode_alympics_wac_harness_{suffix}",
        episode_attempt_id="attempt_1",
    )


# ---------------------------------------------------------------------------
# Pure: the four named policy functions (spec section 6).
# ---------------------------------------------------------------------------


def test_proportional_bid_is_3x_requirement_and_ignores_everything_else() -> None:
    assert proportional_bid({"requirement": 8, "no_drink": 9, "balance": 0}) == 24
    assert proportional_bid({"requirement": 12}) == 36


def test_conservative_bid_is_1x_requirement() -> None:
    assert conservative_bid({"requirement": 8}) == 8
    assert conservative_bid({"requirement": 12}) == 12


def test_aggressive_bid_is_5x_requirement() -> None:
    assert aggressive_bid({"requirement": 8}) == 40
    assert aggressive_bid({"requirement": 12}) == 60


def test_myopic_need_bid_scales_with_no_drink_only() -> None:
    assert myopic_need_bid({"requirement": 8, "no_drink": 1}) == 16
    assert myopic_need_bid({"requirement": 8, "no_drink": 4}) == 40
    # Requirement-only otherwise: same no_drink, different requirement.
    assert myopic_need_bid({"requirement": 11, "no_drink": 1}) == 22


def test_policy_functions_cover_exactly_the_declared_policy_ids() -> None:
    from aeread_families.alympics_wac.cases import POLICY_IDS

    assert set(POLICY_FUNCTIONS) == set(POLICY_IDS)


# ---------------------------------------------------------------------------
# Pure: baseline_policy_assignment.
# ---------------------------------------------------------------------------


def test_baseline_policy_assignment_swaps_only_the_focal_seat() -> None:
    assignment = {
        "alex": "aggressive",
        "bob": "conservative",
        "cindy": "proportional",
        "david": "myopic_need",
        "eric": "proportional",
    }
    baseline = baseline_policy_assignment(assignment, focal_seat="alex")
    assert baseline["alex"] == "proportional"
    for seat in ("bob", "cindy", "david", "eric"):
        assert baseline[seat] == assignment[seat]
    # Original is untouched.
    assert assignment["alex"] == "aggressive"


def test_baseline_policy_assignment_rejects_an_unknown_focal_seat() -> None:
    with pytest.raises(ValueError, match="focal_seat"):
        baseline_policy_assignment({"alex": "proportional"}, focal_seat="zeke")


def test_baseline_policy_assignment_rejects_an_unknown_baseline_policy_id() -> None:
    with pytest.raises(ValueError, match="baseline_policy_id"):
        baseline_policy_assignment(
            {"alex": "proportional"}, focal_seat="alex", baseline_policy_id="bogus"
        )


# ---------------------------------------------------------------------------
# Pure: ScriptedAlympicsWacHarness construction guards.
# ---------------------------------------------------------------------------


def test_harness_rejects_a_policy_assignment_missing_a_seat(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path, suffix="missing_seat")
    incomplete = {"alex": "proportional", "bob": "proportional"}
    with pytest.raises(ValueError, match="policy_assignment must cover exactly"):
        ScriptedAlympicsWacHarness(policy_assignment=incomplete, evidence=evidence)


def test_harness_rejects_an_undeclared_policy_id(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path, suffix="bad_policy")
    assignment = {seat: "proportional" for seat in SEAT_ORDER}
    assignment["alex"] = "omniscient"
    with pytest.raises(ValueError, match="undeclared policy id"):
        ScriptedAlympicsWacHarness(policy_assignment=assignment, evidence=evidence)


# ---------------------------------------------------------------------------
# End-to-end: at least 2 full episodes through the real run_episode path,
# each with its own sealed evidence generation.
# ---------------------------------------------------------------------------


def test_reference_baseline_runs_end_to_end_through_the_harness_with_sealed_evidence(
    tmp_path: Path,
) -> None:
    case = _case("reference_baseline")
    cell = _cell(case, suffix="reference_baseline")
    plugin = AlympicsWacPlugin(upstream_root=UPSTREAM_ROOT)
    evidence = _evidence(tmp_path, suffix="reference_baseline")
    policy_assignment = dict(case.payload["grid_cell"]["policy_assignment"])
    harness = ScriptedAlympicsWacHarness(policy_assignment=policy_assignment, evidence=evidence)

    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=harness)
    )

    assert result.terminal["reason"] == "rounds_exhausted"
    assert result.terminal["round_id"] == 20
    # Verified round-1 bid vector (spec section 4 golden 1).
    assert result.final_state["round_log"][0]["bids"] == {
        "alex": 24,
        "bob": 27,
        "cindy": 30,
        "david": 33,
        "eric": 36,
    }

    # Every request the scheduler made was answered exactly once, and every
    # answer was sealed as one durable evidence event -- the harness never
    # under- or over-records relative to what run_episode actually asked for.
    assert len(harness.requests) == result.logical_action_count
    seal = evidence.seal()
    assert isinstance(seal, EvidenceSeal)
    assert seal.event_count == len(harness.requests)
    evidence.verify_chain()
    assert evidence.verify_seal() == seal
    with pytest.raises(EvidenceSealedError):
        evidence.append_event("late", {})

    # Every sealed event actually records the policy this harness was
    # configured with for that seat.
    events = evidence.read_events()
    assert len(events) == seal.event_count
    for event in events:
        assert event.event_type == "alympics_wac_bid_served"
        payload = evidence.read_event_payload(event)
        assert payload["policy_id"] == policy_assignment[payload["seat_id"]]


def test_mixed_policies_a_runs_end_to_end_with_all_four_policies_and_sealed_evidence(
    tmp_path: Path,
) -> None:
    case = _case("mixed_policies_a")
    cell = _cell(case, suffix="mixed_policies_a")
    plugin = AlympicsWacPlugin(upstream_root=UPSTREAM_ROOT)
    evidence = _evidence(tmp_path, suffix="mixed_policies_a")
    policy_assignment = dict(case.payload["grid_cell"]["policy_assignment"])
    assert set(policy_assignment.values()) == set(POLICY_FUNCTIONS)  # all 4 policies exercised
    harness = ScriptedAlympicsWacHarness(policy_assignment=policy_assignment, evidence=evidence)

    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=harness)
    )

    # Verified concretely against this pinned case's own supply schedule:
    # alex ("aggressive") is the sole round-15 survivor, everyone else is
    # eliminated along the way (never a claim about optimal play -- P01's
    # audit verdict is baseline_only, spec section 6).
    assert result.terminal["reason"] == "rounds_exhausted"
    assert result.terminal["round_id"] == 15
    assert result.final_state["round_log"][0]["bids"] == {
        "alex": 40,
        "bob": 9,
        "cindy": 30,
        "david": 22,
        "eric": 36,
    }
    assert result.final_state["round_log"][0]["winners"] == ("alex",)
    assert result.final_state["round_log"][0]["bid_legal"] == {
        seat: True for seat in SEAT_ORDER
    }
    assert result.final_state["players"]["alex"]["alive"] is True
    assert set(result.final_state["eliminated_order"]) == {"bob", "cindy", "david", "eric"}

    assert len(harness.requests) == result.logical_action_count
    seal = evidence.seal()
    assert seal.event_count == len(harness.requests)
    evidence.verify_chain()


def test_two_full_episodes_produce_two_independent_evidence_seals(tmp_path: Path) -> None:
    """The explicit "at least 2 full episodes through the real path" check:
    two different cases, two different harness instances, two independent
    EvidenceStore generations -- neither leaks state into the other."""
    plugin = AlympicsWacPlugin(upstream_root=UPSTREAM_ROOT)

    reference_case = _case("reference_baseline")
    reference_cell = _cell(reference_case, suffix="two_episodes_reference")
    reference_evidence = _evidence(tmp_path, suffix="two_episodes_reference")
    reference_harness = ScriptedAlympicsWacHarness(
        policy_assignment=dict(reference_case.payload["grid_cell"]["policy_assignment"]),
        evidence=reference_evidence,
    )
    reference_result = asyncio.run(
        run_episode(
            cell=reference_cell,
            case=reference_case,
            plugin=plugin,
            response_source=reference_harness,
        )
    )

    mixed_case = _case("mixed_policies_a")
    mixed_cell = _cell(mixed_case, suffix="two_episodes_mixed")
    mixed_evidence = _evidence(tmp_path, suffix="two_episodes_mixed")
    mixed_harness = ScriptedAlympicsWacHarness(
        policy_assignment=dict(mixed_case.payload["grid_cell"]["policy_assignment"]),
        evidence=mixed_evidence,
    )
    mixed_result = asyncio.run(
        run_episode(cell=mixed_cell, case=mixed_case, plugin=plugin, response_source=mixed_harness)
    )

    assert reference_result.terminal["reason"] == "rounds_exhausted"
    assert mixed_result.terminal["reason"] == "rounds_exhausted"
    reference_seal = reference_evidence.seal()
    mixed_seal = mixed_evidence.seal()
    assert reference_seal.event_count == len(reference_harness.requests)
    assert mixed_seal.event_count == len(mixed_harness.requests)
    # Distinct episodes never share an evidence identity.
    assert reference_seal.episode_id != mixed_seal.episode_id
    assert reference_seal.event_root_sha256 != mixed_seal.event_root_sha256
