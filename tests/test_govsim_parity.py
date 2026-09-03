"""Parity tests for the govsim adapter (docs/govsim_adapter_spec.md section 5's
"Parity (needs the bridge): tests/test_govsim_parity.py" -- the file that
file names but, before this pass, did not exist).

Closes triage Finding 5: ``tests/test_govsim_replay.py``'s replay tests
produce BOTH the "original" and the "replayed" episode through the SAME
``GovsimPlugin.step()`` translation (a kernel-level harvest-quantity
decision -> upstream's raw ``harvesting``/``chat``/``home`` action-kind
sequence). That proves deterministic self-consistency -- replaying the exact
same recorded decisions reproduces the exact same state -- never independent
agreement with a raw-upstream trajectory constructed a DIFFERENT way. A
``GovsimPlugin.step()`` translation bug (e.g. the wrong per-round action
order) would still make the live run and its replay agree byte-for-byte
with each other, because both use the identical (buggy) translation; the
required direct raw-upstream comparison would diverge, but nothing in the
existing replay suite could ever catch that.

Per spec section 5's four parity checks:

- **P1 (import determinism)** is already covered --
  ``tests/test_govsim_cases.py::test_importer_is_byte_identical_across_two_runs``
  and ``::test_committed_corpus_on_disk_matches_a_fresh_generation``.
- **P4 (gini parity)** is already covered --
  ``tests/test_govsim_measurement.py``'s
  ``test_vendored_gini_matches_upstreams_own_gini_through_the_bridge*``.
- **P2 (adapter/raw-upstream equivalence)** and **P3
  (regeneration/collapse cross-check)** below are new: neither existed
  anywhere before this pass.

Per-test skip, never module-level (mirrors
``tests/test_govsim_measurement.py``'s convention, deliberately NOT
``tests/test_govsim_replay.py``'s own module-level skip -- triage
Finding 7): every test here checks for the pinned upstream checkout/bridge
itself and skips individually if unavailable, so a regression in a
bridge-independent test elsewhere in a checkout without the upstream
checkout is never hidden by a blanket module-level skip.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from aeread.shared_runner.execution import EvidenceStore
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.resolver import PlanCell
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import run_episode
from aeread_families.govsim.environment import (
    DISCUSS_PHASE,
    HARVEST_PHASE,
    REFLECT_PHASE,
    GovsimPlugin,
    family_manifest,
    register_plugin,
)
from aeread_families.govsim.govsim_bridge import (
    GovsimBridge,
    GovsimBridgeUnavailableError,
    discover_bridge_python,
)
from aeread_families.govsim.harness import ScriptedGovsimHarness

CASES_DIR = Path("cases/govsim/v1")


def _find_upstream_root() -> Path | None:
    candidate = os.environ.get(
        "AEREAD_GOVSIM_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-govsim",
    )
    root = Path(candidate)
    marker = root / "simulation" / "scenarios" / "common" / "environment" / "concurrent_env.py"
    return root if marker.is_file() else None


UPSTREAM_ROOT = _find_upstream_root()

if UPSTREAM_ROOT is not None:
    try:
        BRIDGE_PYTHON = discover_bridge_python(upstream_root=UPSTREAM_ROOT)
    except GovsimBridgeUnavailableError as error:
        BRIDGE_PYTHON = None
        _BRIDGE_SKIP_REASON = str(error)
    else:
        _BRIDGE_SKIP_REASON = ""
else:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = "pinned upstream govsim checkout not found"


def _bridge() -> GovsimBridge:
    if UPSTREAM_ROOT is None or BRIDGE_PYTHON is None:
        pytest.skip(_BRIDGE_SKIP_REASON or "bridge python unavailable")
    return GovsimBridge(
        python_executable=BRIDGE_PYTHON, upstream_root=UPSTREAM_ROOT, timeout_seconds=120.0
    )


@pytest.fixture(scope="module")
def bridge() -> GovsimBridge:
    return _bridge()


def _case(case_id: str) -> CaseManifest:
    path = CASES_DIR / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    num_agents = int(case.payload["env_cfg"]["num_agents"])
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_govsim_parity_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_govsim_parity",
        suite_version="0.1.0",
        block_id="block_govsim_parity",
        sampling_plan_id="sampling_govsim_parity",
        analysis_plan_id="analysis_govsim_parity",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_govsim_parity_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(
            {f"persona_{i}": "scripted_persona" for i in range(num_agents)}
        ),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _resolved_plugin(bridge_instance: GovsimBridge) -> Any:
    plugin = GovsimPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge_instance)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    return registry.resolve_manifest(family_manifest())


@pytest.fixture(scope="module")
def live_sustainable(bridge: GovsimBridge, tmp_path_factory: pytest.TempPathFactory):
    """One full episode driven through the REAL kernel scheduler -- never
    ``GovsimPlugin.step()``/the bridge invoked directly by this test file's
    own P2/P3 checks below."""
    case = _case("govsim.fishing.sustainable.0")
    cell = _cell(case, suffix="sustainable")
    resolved_plugin = _resolved_plugin(bridge)
    tmp_path = tmp_path_factory.mktemp("govsim_parity_sustainable")
    evidence = EvidenceStore(
        tmp_path / "evidence",
        run_plan_id="runplan_govsim_parity_sustainable",
        cell_id=cell.cell_id,
        episode_id="episode_govsim_parity_sustainable",
        episode_attempt_id="attempt_1",
    )
    harness = ScriptedGovsimHarness(
        policy_assignment=case.payload["policy_assignment"], evidence=evidence
    )
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=harness)
    )
    evidence.seal()
    return case, result


# ---------------------------------------------------------------------------
# P2 -- adapter/raw-upstream equivalence (spec section 5).
# ---------------------------------------------------------------------------


def _independent_raw_action_sequence(
    result: Any, *, persona_ids: list[str]
) -> tuple[list[dict[str, Any]], list[int]]:
    """Reconstruct upstream's own raw ``harvesting``/``chat``/``home`` action
    sequence for one already-completed episode, reading ONLY the harvest
    quantity each seat actually chose (``result.phase_instances``) -- never
    by calling ``GovsimPlugin.step()`` (this is the "no kernel involved"
    half of P2: the per-round protocol below is transcribed independently
    from ``docs/govsim_adapter_spec.md`` section 3.1/``environment.py``'s
    own module docstring, not by importing that module's translation code).

    Also returns, per round, the action-count checkpoint immediately AFTER
    that round's ``discuss`` (chat) action and BEFORE its ``reflect``
    (home) actions -- the point at which ``resource_in_pool`` is
    post-harvest but PRE-regeneration, which P3 below needs.
    """
    raw_actions: list[dict[str, Any]] = []
    pre_regen_checkpoints: list[int] = []
    for instance in result.phase_instances:
        if instance.phase_id == HARVEST_PHASE:
            quantities = {
                action.seat_id: int(action.response["quantity"]) for action in instance.actions
            }
            for persona_id in persona_ids:
                raw_actions.append(
                    {"kind": "harvesting", "agent_id": persona_id, "quantity": quantities[persona_id]}
                )
            for persona_id in persona_ids:
                raw_actions.append({"kind": "harvesting", "agent_id": persona_id, "quantity": 0})
        elif instance.phase_id == DISCUSS_PHASE:
            raw_actions.append({"kind": "chat", "agent_id": persona_ids[0]})
            pre_regen_checkpoints.append(len(raw_actions))
        elif instance.phase_id == REFLECT_PHASE:
            for persona_id in persona_ids:
                raw_actions.append({"kind": "home", "agent_id": persona_id})
        else:
            raise AssertionError(f"unexpected phase_id {instance.phase_id!r}")
    return raw_actions, pre_regen_checkpoints


def test_p2_adapter_translation_matches_an_independently_constructed_raw_action_sequence(
    bridge: GovsimBridge, live_sustainable: Any
) -> None:
    """Drives the SAME scripted decisions two ways and asserts identical
    ``resource_in_pool``/``collected_resource``/termination trace EVERY
    ROUND, plus the terminal aggregates (spec section 5's P2 literal text:
    "Assert identical resource_in_pool, collected_resource, and
    termination trace every round"):

    (a) through the kernel's phase graph -- ``live_sustainable``, already
        driven via ``run_episode``/``GovsimPlugin.step()``'s own
        translation of a harvest-quantity decision into upstream's raw
        action sequence, whose own per-round record is
        ``result.terminal["round_trace"]``.
    (b) directly against raw upstream, with NO ``GovsimPlugin``, no
        scheduler, no kernel phase graph involved at all: the raw action
        sequence is reconstructed independently (see
        ``_independent_raw_action_sequence``) from only the harvest
        quantities each seat chose in (a), and submitted straight to
        ``GovsimBridge.run_actions`` -- the same bridge, but never through
        the adapter's own per-decision translation code -- at the END of
        every round (immediately after that round's ``reflect``/``home``
        actions, i.e. one round further than P3's own pre-regeneration
        checkpoint, so upstream has already applied regeneration and
        recomputed its own ``terminations`` for this round by the time (b)
        is queried).

    Before this test's per-round loop existed, this function (and P3
    below) checked only terminal aggregates -- a per-round translation bug
    that self-corrects by the end of the episode (spec section 5's own
    worry: "a transient per-round collection/trace mismatch that later
    converges to the same terminal aggregates") could pass both. The
    per-round loop below reads ``round_trace``'s ``resource_in_pool_after_
    regen``/``wanted_resource`` fields -- fields the terminal aggregate
    checks never touch (``environment.py``'s own ``terminal()`` reads
    ``resource_in_pool``/``collected_resource`` fresh off upstream's live
    projection at call time, independent of ``round_trace`` entirely) --
    so a bug confined to ``round_trace`` assembly is now caught here even
    though it would remain invisible to the terminal-only checks.
    """
    case, result = live_sustainable
    num_agents = int(case.payload["env_cfg"]["num_agents"])
    persona_ids = [f"persona_{i}" for i in range(num_agents)]

    raw_actions, pre_regen_checkpoints = _independent_raw_action_sequence(
        result, persona_ids=persona_ids
    )
    round_trace = result.terminal["round_trace"]
    assert len(pre_regen_checkpoints) == len(round_trace)

    cumulative_collected: dict[str, int] = {persona_id: 0 for persona_id in persona_ids}
    projection: dict[str, Any] | None = None
    post_round_checkpoint = 0
    for round_index, pre_regen_checkpoint in enumerate(pre_regen_checkpoints):
        entry = round_trace[round_index]
        for persona_id in persona_ids:
            cumulative_collected[persona_id] += int(
                entry["wanted_resource"].get(persona_id, 0)
            )
        # One round further than the pre-regen checkpoint (this round's
        # ``reflect``/``home`` actions, num_agents of them): the point at
        # which raw upstream has already regenerated the pool and
        # recomputed ``terminations`` for this round, matching exactly
        # what ``round_trace[round_index]`` records.
        post_round_checkpoint = pre_regen_checkpoint + num_agents
        projection = bridge.run_actions(
            scenario=case.payload["scenario"],
            env_cfg=case.payload["env_cfg"],
            seed=int(case.payload["world_seed"]),
            actions=raw_actions[:post_round_checkpoint],
        )

        assert projection["resource_in_pool"] == entry["resource_in_pool_after_regen"], (
            f"round {round_index}: raw-upstream resource_in_pool "
            f"{projection['resource_in_pool']!r} != adapter-recorded "
            f"resource_in_pool_after_regen {entry['resource_in_pool_after_regen']!r}"
        )
        assert dict(projection["collected_resource"]) == cumulative_collected, (
            f"round {round_index}: raw-upstream collected_resource "
            f"{dict(projection['collected_resource'])!r} != adapter-recorded "
            f"cumulative wanted_resource {cumulative_collected!r}"
        )
        raw_collapsed = bool(all(projection["terminations"].values()))
        assert raw_collapsed == entry["collapsed_or_horizon"], (
            f"round {round_index}: raw-upstream terminations "
            f"{projection['terminations']!r} (collapsed={raw_collapsed!r}) != "
            f"adapter-recorded collapsed_or_horizon {entry['collapsed_or_horizon']!r}"
        )

    # The final round's post-round checkpoint closes the entire recorded
    # action sequence (this fixture's episode ends via ``collapse_or_
    # horizon``, computed at the same last ``reflect``/``home`` action that
    # closes the loop above) -- so the terminal aggregates below reuse the
    # last iteration's already-fetched projection rather than submitting
    # the identical action sequence to the bridge a second time.
    assert post_round_checkpoint == len(raw_actions)
    assert projection is not None
    assert projection["resource_in_pool"] == result.terminal["resource_in_pool"]
    assert dict(projection["collected_resource"]) == dict(result.terminal["collected_resource"])
    assert projection["num_round"] == result.terminal["num_round"]


# ---------------------------------------------------------------------------
# P3 -- regeneration/collapse cross-check (spec section 5).
# ---------------------------------------------------------------------------


def test_p3_recorded_regeneration_and_collapse_match_the_documented_formula_independently(
    bridge: GovsimBridge, live_sustainable: Any
) -> None:
    """Independently recomputes, per round, ``min(initial_resource_in_pool,
    2 * pool_before_regen)`` and ``pool_after_regen < 5 or round >=
    max_num_rounds`` from a FRESH bridge query at the post-harvest/
    pre-regeneration checkpoint (never from ``environment.py``'s own
    ``round_trace``/collapse-flag computation), and diffs the result
    against what the adapter actually recorded for that round (spec
    section 5's P3: "never trust our arithmetic without this diff").

    Also cross-checks per-round ``collected_resource`` at that same
    checkpoint (upstream's own ``_assign_resource`` finalizes
    ``collected_resource`` the moment a round's harvest phase closes --
    before the ``chat``/``home`` actions this checkpoint sits after --
    so the fresh query already reflects it): independently reconstructed
    from the CUMULATIVE SUM of every prior round's ``wanted_resource``
    entry (upstream's own ``collected_resource[agent] += res`` and
    ``wanted_resource[agent] = res`` in the same call, so the two are
    mathematically identical by construction, never merely assumed to
    agree) and diffed against upstream's own recorded total -- this was
    the one quantity this test named in its own docstring but never
    actually asserted.
    """
    case, result = live_sustainable
    num_agents = int(case.payload["env_cfg"]["num_agents"])
    max_num_rounds = int(case.payload["env_cfg"]["max_num_rounds"])
    initial_resource_in_pool = int(case.payload["env_cfg"]["initial_resource_in_pool"])
    persona_ids = [f"persona_{i}" for i in range(num_agents)]

    raw_actions, pre_regen_checkpoints = _independent_raw_action_sequence(
        result, persona_ids=persona_ids
    )
    round_trace = result.terminal["round_trace"]
    assert len(pre_regen_checkpoints) == len(round_trace)

    cumulative_collected: dict[str, int] = {persona_id: 0 for persona_id in persona_ids}
    for round_index, checkpoint in enumerate(pre_regen_checkpoints):
        entry = round_trace[round_index]
        for persona_id in persona_ids:
            cumulative_collected[persona_id] += int(
                entry["wanted_resource"].get(persona_id, 0)
            )

        prefix = raw_actions[:checkpoint]
        projection = bridge.run_actions(
            scenario=case.payload["scenario"],
            env_cfg=case.payload["env_cfg"],
            seed=int(case.payload["world_seed"]),
            actions=prefix,
        )
        pool_before_regen = int(projection["resource_in_pool"])
        expected_pool_after_regen = min(initial_resource_in_pool, 2 * pool_before_regen)
        expected_collapsed_or_horizon = (
            expected_pool_after_regen < 5 or (round_index + 1) >= max_num_rounds
        )

        assert entry["resource_in_pool_after_regen"] == expected_pool_after_regen, (
            f"round {round_index}: adapter recorded "
            f"{entry['resource_in_pool_after_regen']!r}, independently recomputed "
            f"{expected_pool_after_regen!r} from pool_before_regen={pool_before_regen!r}"
        )
        assert entry["collapsed_or_horizon"] == expected_collapsed_or_horizon, (
            f"round {round_index}: adapter recorded "
            f"collapsed_or_horizon={entry['collapsed_or_horizon']!r}, independently "
            f"recomputed {expected_collapsed_or_horizon!r}"
        )
        assert dict(projection["collected_resource"]) == cumulative_collected, (
            f"round {round_index}: upstream's own recorded collected_resource "
            f"{dict(projection['collected_resource'])!r} != the cumulative sum of "
            f"every round's recorded wanted_resource {cumulative_collected!r}"
        )
