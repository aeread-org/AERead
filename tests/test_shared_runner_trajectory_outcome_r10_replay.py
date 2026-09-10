"""Ruling R10 (kernel_scoring_contract_spec.md) enforced at replay time
itself, not only inside the scoring-contract protocol test (issue #122).

A deterministic outcome() that mis-copies its own trajectory state used to
verify against itself on every production replay path
(finalize_family_execution / replay_family_receipt / audit_family_receipt):
each compares a freshly replayed outcome only against bytes produced by that
SAME outcome() call, sealed earlier by that SAME call. A self-consistent
mis-copy agrees with itself at every boundary those paths already check.
This file proves _replay_family_trajectory now catches it directly.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.task.evaluation import (
    SeatContext,
    replay_family_scoring_input,
)
from aeread.shared_runner.task.execution import execute_plan_cell
from aeread_families.housing.runner import (
    HousingScriptedLandlordProvider,
    HousingScriptedTenantProvider,
    build_housing_smoke,
)


def _run_housing_episode(tmp_path: Path, *, registry: PluginRegistry | None = None):
    setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=registry or setup.registry,
            evidence_root=tmp_path,
            prompt_sources=setup.prompt_sources,
            providers={
                "housing_scripted_tenant": HousingScriptedTenantProvider(),
                "housing_scripted_landlord": HousingScriptedLandlordProvider(),
            },
            pricing=setup.pricing,
            episode_attempt_ordinal=0,
        )
    )
    cell = next(item for item in setup.plan.cells if item.cell_id == execution.cell_id)
    case = next(item for item in setup.plan.cases if item.case_id == cell.case_id)
    family = next(item for item in setup.plan.families if item.family.id == cell.family_id)
    plugin = (registry or setup.registry).resolve_manifest(family)
    family_case = plugin.validate_payload(case.payload)
    return setup, execution, plugin, family_case, cell


def test_r10_is_a_no_op_with_no_declared_paths(tmp_path) -> None:
    """Unchanged behavior: no declaration, no check, whatever Housing's real
    outcome/state happen to be."""
    _setup, execution, plugin, family_case, cell = _run_housing_episode(tmp_path)
    replay_family_scoring_input(
        plugin=plugin,
        family_case=family_case,
        evidence=execution.evidence,
        cell=cell,
        seat_context=SeatContext((), {}),
        trajectory_outcome_paths=(),
    )


def test_r10_accepts_a_genuine_matching_path(tmp_path) -> None:
    """/signed_rents is byte-identical between Housing's real outcome and
    its real final replayed state -- a true positive, no corruption needed."""
    _setup, execution, plugin, family_case, cell = _run_housing_episode(tmp_path)
    scoring_input = replay_family_scoring_input(
        plugin=plugin,
        family_case=family_case,
        evidence=execution.evidence,
        cell=cell,
        seat_context=SeatContext((), {}),
        trajectory_outcome_paths=("/signed_rents",),
    )
    assert scoring_input.outcome["signed_rents"]


def test_r10_rejects_a_declared_path_missing_from_the_outcome(tmp_path) -> None:
    """Housing's real outcome has no "/not_a_real_field" key at all."""
    _setup, execution, plugin, family_case, cell = _run_housing_episode(tmp_path)
    with pytest.raises(AssertionError, match="does not exist in the outcome"):
        replay_family_scoring_input(
            plugin=plugin,
            family_case=family_case,
            evidence=execution.evidence,
            cell=cell,
            seat_context=SeatContext((), {}),
            trajectory_outcome_paths=("/not_a_real_field",),
        )


def test_r10_rejects_a_declared_path_missing_from_the_final_state(tmp_path) -> None:
    """"/assignment_pairs" is a real, sequence-shaped outcome field, but
    Housing's own state snapshot never carries that key."""
    _setup, execution, plugin, family_case, cell = _run_housing_episode(tmp_path)
    with pytest.raises(AssertionError, match="does not exist in the final replayed state"):
        replay_family_scoring_input(
            plugin=plugin,
            family_case=family_case,
            evidence=execution.evidence,
            cell=cell,
            seat_context=SeatContext((), {}),
            trajectory_outcome_paths=("/assignment_pairs",),
        )


def test_r10_rejects_a_non_sequence_declared_path(tmp_path) -> None:
    """"/baseline_total" is a real outcome field, but it is a float, not a
    per-step record sequence."""
    _setup, execution, plugin, family_case, cell = _run_housing_episode(tmp_path)
    with pytest.raises(AssertionError, match="not a.*sequence"):
        replay_family_scoring_input(
            plugin=plugin,
            family_case=family_case,
            evidence=execution.evidence,
            cell=cell,
            seat_context=SeatContext((), {}),
            trajectory_outcome_paths=("/baseline_total",),
        )


class _CorruptedSignedRentsHousingPlugin:
    """Delegates every hook to a real HousingV1Plugin except outcome(),
    which deterministically drops the first signed_rents entry -- exactly
    the class of bug issue #122 describes: a deterministic outcome() that
    mis-copies trajectory state, which verifies against itself at every
    other replay boundary because both the live run and the replay call the
    SAME corrupted outcome() the same way."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def outcome(self, case, terminal):
        real = dict(self._inner.outcome(case, terminal))
        real["signed_rents"] = tuple(real["signed_rents"])[1:]
        return real


def test_r10_rejects_two_trajectory_copies_that_currently_pass_outside_protocol_fixtures(
    tmp_path,
) -> None:
    """The corrupted plugin is registered BEFORE the live episode runs, so
    its mis-copy is sealed as evidence once and replayed consistently --
    the existing outcome-vs-sealed-evidence cross-check in
    _replay_family_trajectory (line ~545) passes, because it only compares
    the corrupted outcome() against itself. Only the new R10 check, which
    compares the outcome's OWN copy against the final replayed state at
    the same pointer, can catch this."""
    base_setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    manifest = base_setup.plan.families[0]
    real_plugin = base_setup.registry.resolve_manifest(manifest)
    registry = PluginRegistry()
    registry.register_trusted(manifest, _CorruptedSignedRentsHousingPlugin(real_plugin))

    _setup, execution, plugin, family_case, cell = _run_housing_episode(
        tmp_path, registry=registry
    )

    with pytest.raises(AssertionError, match="does not match the same pointer read"):
        replay_family_scoring_input(
            plugin=plugin,
            family_case=family_case,
            evidence=execution.evidence,
            cell=cell,
            seat_context=SeatContext((), {}),
            trajectory_outcome_paths=("/signed_rents",),
        )


class _TerminalMutatesStateItWasHandedHousingPlugin:
    """Delegates every hook to a real HousingV1Plugin, except that terminal()
    -- which production code calls as ``plugin.terminal(family_case, state)``,
    handing it the SAME mutable ``state`` mapping the replay is still holding
    a reference to -- mutates that mapping in place to match a trimmed copy
    of signed_rents, immediately before returning the genuine, uncorrupted
    terminal result. outcome() separately drops the first signed_rents entry,
    exactly like ``_CorruptedSignedRentsHousingPlugin`` above. Every sealed
    boundary (transition, terminal, outcome) still agrees with itself, because
    each was sealed by this SAME pair of hooks. Only a check that reads the
    declared path from a snapshot of `state` taken BEFORE terminal() ran can
    tell the two trimmed copies apart from the genuine untrimmed trajectory."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def terminal(self, case, state):
        result = self._inner.terminal(case, state)
        if result is not None:
            state["signed_rents"] = list(result["signed_rents"])[1:]
        return result

    def outcome(self, case, terminal):
        real = dict(self._inner.outcome(case, terminal))
        real["signed_rents"] = tuple(real["signed_rents"])[1:]
        return real


class _OutcomeMutatesStateItWasHandedHousingPlugin:
    """Delegates every hook to a real HousingV1Plugin. terminal() is handed
    the final replayed ``state`` mapping directly and stashes that SAME
    object on ``self`` -- a plugin instance persists across every hook call
    in one replay, so nothing stops it reaching back into a mapping it saw
    earlier. outcome() then both drops the first signed_rents entry from the
    result it returns AND mutates that stashed ``state`` object in place to
    match, from inside the very call production code treats as read-only.
    As with the terminal-mutating variant above, every sealed boundary still
    agrees with itself; only a pre-terminal() snapshot of `state` defeats the
    corruption."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._last_state: Any = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def terminal(self, case, state):
        self._last_state = state
        return self._inner.terminal(case, state)

    def outcome(self, case, terminal):
        real = dict(self._inner.outcome(case, terminal))
        real["signed_rents"] = tuple(real["signed_rents"])[1:]
        if self._last_state is not None and "signed_rents" in self._last_state:
            self._last_state["signed_rents"] = list(real["signed_rents"])
        return real


@pytest.mark.parametrize(
    "corrupted_plugin_cls",
    [
        _TerminalMutatesStateItWasHandedHousingPlugin,
        _OutcomeMutatesStateItWasHandedHousingPlugin,
    ],
)
def test_r10_is_not_defeated_by_a_hook_mutating_the_state_it_was_handed(
    tmp_path, corrupted_plugin_cls
) -> None:
    """A plugin whose outcome() mis-copies its own trajectory must not be
    able to launder that mismatch by also editing the final replayed `state`
    object -- via terminal()'s direct parameter, or via a reference a hook
    stashed earlier -- to match. R10 must compare against the state the
    replay actually produced, frozen before either hook ran, not whatever
    `state` holds once both have had a chance to mutate it."""
    base_setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    manifest = base_setup.plan.families[0]
    real_plugin = base_setup.registry.resolve_manifest(manifest)
    registry = PluginRegistry()
    registry.register_trusted(manifest, corrupted_plugin_cls(real_plugin))

    _setup, execution, plugin, family_case, cell = _run_housing_episode(
        tmp_path, registry=registry
    )

    with pytest.raises(AssertionError, match="does not match the same pointer read"):
        replay_family_scoring_input(
            plugin=plugin,
            family_case=family_case,
            evidence=execution.evidence,
            cell=cell,
            seat_context=SeatContext((), {}),
            trajectory_outcome_paths=("/signed_rents",),
        )
