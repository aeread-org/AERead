"""Scripted seats (docs/kernel_scripted_seats_design.md, #92), slice 1.

A scripted seat is a seat the family resolves itself rather than a model.
These tests cover the declaration and resolution rules; the execution and
replay rules are in ``test_scripted_seats_execution.py``.
"""
from __future__ import annotations

import dataclasses
from types import MappingProxyType

import pytest

from aeread.shared_runner.run.resolver import PlanResolutionError, resolve_run_plan
from aeread.shared_runner.schemas import AuthoringValidationError, RunSpec
from tests.test_shared_runner_resolver import _inputs


def _scripted_inputs(**changes):
    """The resolver fixture with landlord_0 moved from a model-shaped profile
    to a real scripted seat -- the exact workaround the design retires."""
    inputs = _inputs()
    run = inputs["run_spec"]
    assignments = {seat: profile for seat, profile in run.seat_assignments.items() if seat != "landlord_0"}
    fields = {
        "seat_assignments": MappingProxyType(assignments),
        "scripted_seats": MappingProxyType({"landlord_0": "fixed_landlord_v1"}),
        **changes,
    }
    inputs["run_spec"] = dataclasses.replace(run, **fields)
    return inputs


def test_a_run_spec_without_scripted_seats_is_unchanged() -> None:
    """Digest neutrality at the source: the field defaults to empty and is
    omitted from canonical output, so every plan sealed before it existed
    hashes exactly as it did. (The pinned-digest suites prove the same thing
    on real plans; this pins the mechanism.)"""
    from aeread.shared_runner.run.resolver import canonical_json_bytes

    run = _inputs()["run_spec"]
    assert dict(run.scripted_seats) == {}
    assert b"scripted_seats" not in canonical_json_bytes(run)


def test_a_scripted_seat_resolves_without_a_profile() -> None:
    plan = resolve_run_plan(**_scripted_inputs())
    cell = plan.cells[0]
    assert dict(cell.scripted_seats) == {"landlord_0": "fixed_landlord_v1"}
    assert "landlord_0" not in cell.profile_by_seat
    assert set(cell.profile_by_seat) == {"tenant_0"}


def test_a_scripted_seat_must_use_a_policy_its_role_declares() -> None:
    inputs = _scripted_inputs(scripted_seats=MappingProxyType({"landlord_0": "not_declared_v9"}))
    with pytest.raises(PlanResolutionError, match="does not declare"):
        resolve_run_plan(**inputs)


def test_a_testable_role_cannot_be_scripted() -> None:
    """A scripted subject is a measurement of nothing."""
    inputs = _inputs()
    run = inputs["run_spec"]
    inputs["run_spec"] = dataclasses.replace(
        run,
        seat_assignments=MappingProxyType({"landlord_0": run.seat_assignments["landlord_0"]}),
        scripted_seats=MappingProxyType({"tenant_0": "anything"}),
    )
    with pytest.raises(PlanResolutionError):
        resolve_run_plan(**inputs)


def test_a_seat_cannot_be_both_scripted_and_assigned() -> None:
    run = _inputs()["run_spec"]
    with pytest.raises(AuthoringValidationError, match="never both"):
        dataclasses.replace(run, scripted_seats=MappingProxyType({"tenant_0": "x"}))


def test_a_scripted_seat_may_be_a_control_but_never_a_subject() -> None:
    """The fixture's block already names landlord_0 as a controlled profile,
    and a fixed policy is the archetypal control -- so that resolves. Naming
    the same seat as a subject does not."""
    plan = resolve_run_plan(**_scripted_inputs())
    (block,) = plan.evaluation_blocks
    assert "landlord_0" in block.controlled_profiles
    inputs = _scripted_inputs()
    (block,) = inputs["evaluation_blocks"]
    inputs["evaluation_blocks"] = (
        dataclasses.replace(block, subject_seats=tuple(block.subject_seats) + ("landlord_0",)),
    )
    with pytest.raises(PlanResolutionError, match="cannot be a subject"):
        resolve_run_plan(**inputs)
