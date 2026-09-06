from __future__ import annotations

import asyncio
import dataclasses

import pytest

from aeread.shared_runner import (
    FamilyScoreSet,
    MetricValue,
    ScoreEnvelope,
    ValidityReport,
    canonical_json_bytes,
    seal_evaluation_receipt,
    verify_evaluation_receipt,
)
from aeread.shared_runner.task.execution import execute_plan_cell
from aeread.shared_runner.task.evaluation import (
    _inapplicable_leaf_ids,
    _seat_context_for_cell,
    audit_family_receipt,
)
from aeread_families.housing.runner import (
    HousingScriptedLandlordProvider,
    HousingScriptedTenantProvider,
    build_housing_smoke,
    finalize_housing_execution,
    replay_housing_receipt,
)


def _install_multileaf_scorer(
    setup,
    *,
    diagnostic_valid: bool,
    diagnostic_is_admission: bool,
) -> None:
    plugin = setup.registry.resolve_manifest(setup.plan.families[0])
    original_builder = plugin.build_scorer

    def build_scorer(case):
        original_scorer = original_builder(case)

        def score(outcome, *, evidence_refs=()):
            primary = original_scorer(outcome, evidence_refs=evidence_refs)
            estimand = dataclasses.replace(
                primary.leaf.estimand,
                estimand_id="housing_secondary_welfare",
            )
            objective_scope = dataclasses.replace(
                primary.leaf.verifier.objective_scope,
                objective_id=estimand.estimand_id,
            )
            verifier = dataclasses.replace(
                primary.leaf.verifier,
                objective_scope=objective_scope,
            )
            diagnostic_leaf = dataclasses.replace(
                primary.leaf,
                leaf_id="housing_secondary_welfare_leaf",
                estimand=estimand,
                verifier=verifier,
            )
            if diagnostic_valid:
                diagnostic = dataclasses.replace(
                    primary,
                    leaf=diagnostic_leaf,
                    primary=MetricValue(
                        primary.primary.value,
                        primary.primary.unit,
                        {"test_fixture": True},
                    ),
                )
            else:
                diagnostic = ScoreEnvelope(
                    status="invalid_measurement",
                    leaf=diagnostic_leaf,
                    primary=None,
                    metrics={},
                    reference_values={},
                    validity=ValidityReport(
                        "invalid", ("secondary measurement unavailable",)
                    ),
                    evidence_refs=tuple(evidence_refs),
                )
            admission_leaf_ids = (primary.leaf.leaf_id,)
            if diagnostic_is_admission:
                admission_leaf_ids += (diagnostic_leaf.leaf_id,)
            return FamilyScoreSet(
                primary_leaf_id=primary.leaf.leaf_id,
                scores=(diagnostic, primary),
                admission_leaf_ids=admission_leaf_ids,
            )

        return score

    plugin.build_scorer = build_scorer


@pytest.mark.parametrize(
    (
        "diagnostic_valid",
        "diagnostic_is_admission",
        "expected_status",
        "expected_inclusion",
    ),
    (
        (True, True, "ok", "included"),
        (False, False, "ok", "included"),
        (False, True, "invalid_measurement", "excluded"),
    ),
)
def test_family_finalizer_seals_and_replays_explicit_multileaf_admission(
    tmp_path,
    diagnostic_valid: bool,
    diagnostic_is_admission: bool,
    expected_status: str,
    expected_inclusion: str,
) -> None:
    setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    _install_multileaf_scorer(
        setup,
        diagnostic_valid=diagnostic_valid,
        diagnostic_is_admission=diagnostic_is_admission,
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
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

    receipt = finalize_housing_execution(setup=setup, execution=execution)

    verify_evaluation_receipt(receipt)
    assert receipt.status == expected_status
    assert receipt.inclusion_status == expected_inclusion
    assert len(receipt.scores) == 2
    assert receipt.scores[0].leaf.leaf_id == receipt.primary_leaf_id
    assert receipt.scores[1].status == (
        "ok" if diagnostic_valid else "invalid_measurement"
    )
    assert (receipt.failure is None) == (expected_status == "ok")

    score_event = next(
        event
        for event in execution.evidence.read_events()
        if event.event_type == "score_recorded"
    )
    score_payload = execution.evidence.read_event_payload(score_event)
    assert "scores" in score_payload
    assert "score" not in score_payload

    replayed = replay_housing_receipt(
        setup=setup,
        receipt=receipt,
        evidence_root=tmp_path,
    )
    assert canonical_json_bytes(replayed) == canonical_json_bytes(receipt)

    audited = audit_family_receipt(
        setup=setup,
        receipt_path=execution.evidence.root / "evaluation_receipt.json",
    )
    assert audited["receipt_sha256"] == receipt.receipt_sha256


def test_audit_and_replay_tolerate_kernel_pin_drift_but_not_family_drift(tmp_path) -> None:
    from aeread.shared_runner.run.resolver import plan_with_pins
    from aeread.shared_runner.task.evaluation import receipt_implementation_drift

    setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
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
    receipt = finalize_housing_execution(setup=setup, execution=execution)
    receipt_path = execution.evidence.root / "evaluation_receipt.json"

    def current(target, **changes):
        pins = tuple(
            dataclasses.replace(pin, **changes) if pin == target else pin
            for pin in setup.plan.implementation_pins
        )
        return dataclasses.replace(setup, plan=plan_with_pins(setup.plan, pins))

    harness = next(pin for pin in setup.plan.implementation_pins if pin.kind == "harness")
    kernel_moved = current(harness, sha256="a" * 64)
    assert kernel_moved.plan.run_plan_id != setup.plan.run_plan_id

    audited = audit_family_receipt(setup=kernel_moved, receipt_path=receipt_path)
    assert audited["receipt_sha256"] == receipt.receipt_sha256
    assert receipt_implementation_drift(kernel_moved.plan, audited) == (
        f"implementation_drift:{harness.component_id}",
    )
    assert receipt_implementation_drift(setup.plan, audited) == ()
    replayed = replay_housing_receipt(
        setup=kernel_moved, receipt=receipt, evidence_root=tmp_path
    )
    assert canonical_json_bytes(replayed) == canonical_json_bytes(receipt)

    scorer = next(pin for pin in setup.plan.implementation_pins if pin.kind == "scorer")
    family_moved = current(scorer, sha256="b" * 64)
    with pytest.raises(ValueError, match="plan_implementation_pins"):
        audit_family_receipt(setup=family_moved, receipt_path=receipt_path)
    with pytest.raises(ValueError, match="does not belong"):
        replay_housing_receipt(setup=family_moved, receipt=receipt, evidence_root=tmp_path)


def test_finalizer_threads_seat_context_from_the_plan_block_and_cell(tmp_path) -> None:
    """Ruling R12 rule 1: the scorer receives exactly the executed cell's
    seat context -- the plan's evaluation block's ``subject_seats`` (matched
    by ``cell.block_id``) and the cell's own ``profile_by_seat`` -- never
    anything the live episode produced.
    """
    setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    plugin = setup.registry.resolve_manifest(setup.plan.families[0])
    original_builder = plugin.build_scorer
    received: dict[str, object] = {}

    def build_scorer(case):
        original_scorer = original_builder(case)

        def score(scoring_input, *, evidence_refs=()):
            received["seat_context"] = scoring_input.seat_context
            return original_scorer(scoring_input, evidence_refs=evidence_refs)

        return score

    plugin.build_scorer = build_scorer

    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
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
    finalize_housing_execution(setup=setup, execution=execution)

    assert "seat_context" in received
    cell = setup.plan.cells[0]
    block = next(
        item for item in setup.plan.evaluation_blocks if item.block_id == cell.block_id
    )
    seat_context = received["seat_context"]
    assert seat_context.subject_seats == block.subject_seats
    assert dict(seat_context.profile_by_seat) == dict(cell.profile_by_seat)


def _reseal_with_tampered_agent_profile_seats(receipt, *, extra_seat: str):
    """A copy of ``receipt`` whose ``agent_profile_sha256_by_seat`` names one
    seat the plan's cell does not carry -- self-consistent (freshly resealed,
    so ``verify_evaluation_receipt`` does not itself object) but structurally
    wrong for ruling R12 rule 1's dedicated seat-set check to catch.
    """
    tampered = dataclasses.replace(
        receipt,
        receipt_sha256=None,
        agent_profile_sha256_by_seat={
            **receipt.agent_profile_sha256_by_seat,
            extra_seat: "0" * 64,
        },
    )
    return seal_evaluation_receipt(tampered)


def test_replay_rejects_a_receipt_whose_agent_profile_seats_disagree_with_the_plan(
    tmp_path,
) -> None:
    """Ruling R12 rule 1: replay rejects a seat context whose seat set
    disagrees with the receipt's recorded ``agent_profile_digests``.

    Reachability note: ``PlanCell.profile_by_seat`` is itself part of what
    makes ``RunPlan.plan_sha256``, so a receipt whose recorded seats
    genuinely differ from the CURRENT plan's cell almost always fails the
    earlier run_plan_id/plan_sha256 identity check first. This test reaches
    the seat-context check specifically by tampering the durable evidence
    directory's own receipt file directly (bypassing the write-once API,
    exactly as a corrupted evidence directory would) and passing the
    correspondingly tampered, freshly-resealed receipt object -- every other
    check upstream of the seat-context one is engineered to agree, so this
    check is the one that fires.
    """
    setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
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
    receipt = finalize_housing_execution(setup=setup, execution=execution)
    tampered = _reseal_with_tampered_agent_profile_seats(
        receipt, extra_seat="nonexistent_seat"
    )

    receipt_path = execution.evidence.root / "evaluation_receipt.json"
    receipt_path.write_bytes(canonical_json_bytes(tampered) + b"\n")

    with pytest.raises(ValueError, match="seat context does not match the receipt"):
        replay_housing_receipt(setup=setup, receipt=tampered, evidence_root=tmp_path)


def test_audit_rejects_a_receipt_whose_agent_profile_seats_disagree_with_the_plan(
    tmp_path,
) -> None:
    """Ruling R12 rule 1, the ``audit_family_receipt`` counterpart of the
    replay test above -- same tampering, same reachability note.
    """
    setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
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
    receipt = finalize_housing_execution(setup=setup, execution=execution)
    tampered = _reseal_with_tampered_agent_profile_seats(
        receipt, extra_seat="nonexistent_seat"
    )

    receipt_path = execution.evidence.root / "evaluation_receipt.json"
    receipt_path.write_bytes(canonical_json_bytes(tampered) + b"\n")

    with pytest.raises(ValueError, match="seat context does not match the receipt"):
        audit_family_receipt(setup=setup, receipt_path=receipt_path)


def test_seat_context_for_cell_rejects_a_subject_seat_with_no_assigned_profile() -> None:
    """Ruling R12 rule 1, review finding F1: a resolved plan can never
    legitimately reach this shape -- resolve_run_plan (run/resolver.py)
    already requires block.subject_seats to be a subset of the case's seat
    ids, which must exactly equal run_spec.seat_assignments' keys, which is
    exactly what becomes cell.profile_by_seat (see PlanCell drafting in
    resolve_run_plan). The resolver is therefore the first line of defense,
    and verify_run_plan's plan_sha256 recomputation blocks any attempt to
    reach a real finalizer entry point (finalize_family_execution,
    replay_family_receipt, audit_family_receipt) with a plan/cell pair that
    disagrees with it -- a directly hand-mutated cell (dataclasses.replace,
    below) is the only way to construct this shape at all, so this test
    drives _seat_context_for_cell directly rather than through the
    finalizer, exactly as a plan/cell pair this malformed can only arise
    from a bug elsewhere in the kernel, not from any authored plan.
    """
    setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    cell = setup.plan.cells[0]
    block = next(
        item for item in setup.plan.evaluation_blocks if item.block_id == cell.block_id
    )
    assert "tenant_0" in block.subject_seats

    mutated_cell = dataclasses.replace(
        cell,
        profile_by_seat={
            seat_id: profile_id
            for seat_id, profile_id in cell.profile_by_seat.items()
            if seat_id != "tenant_0"
        },
    )

    with pytest.raises(ValueError, match="tenant_0"):
        _seat_context_for_cell(setup.plan, mutated_cell)


def test_finalize_rejects_a_legacy_familys_hook_returning_an_undeclared_inapplicable_id(
    tmp_path,
) -> None:
    """R13 review finding 1 (blocker): ``_enforce_declared_leaf_policy``'s
    ``I`` subset-of-declared-``case_conditional`` check must run even for a
    family with no declared leaf policy at all -- Housing's production
    manifest is exactly such a family (see this module's own docstring
    note in test_shared_runner_scoring_contract.py: none of the five
    already-migrated families declare a leaf policy on their production
    manifest yet). A hook that returns a non-empty set here is already a
    violation and must be caught before the no-declared-policy early
    return, not silently passed through onto the receipt.
    """
    setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    assert setup.plan.families[0].measurement.leaves == ()
    plugin = setup.registry.resolve_manifest(setup.plan.families[0])
    plugin.inapplicable_leaf_ids = lambda family_case: frozenset({"typo_leaf"})

    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
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
    with pytest.raises(ValueError, match="not declared case_conditional"):
        finalize_housing_execution(setup=setup, execution=execution)


class _HookReturnsList:
    """R13 review finding 2: an adversarial plugin whose hook returns a
    ``list`` instead of a ``frozenset``/``set``."""

    def inapplicable_leaf_ids(self, family_case):
        del family_case
        return ["some_leaf"]


class _HookReturnsStr:
    """R13 review finding 2: ``frozenset("some_leaf")`` would silently
    become a set of individual characters -- the motivating adversary."""

    def inapplicable_leaf_ids(self, family_case):
        del family_case
        return "some_leaf"


class _HookReturnsSetWithANonStringMember:
    def inapplicable_leaf_ids(self, family_case):
        del family_case
        return {"some_leaf", 1}


def test_inapplicable_leaf_ids_rejects_a_hook_returning_a_list() -> None:
    with pytest.raises(TypeError, match="frozenset or set of str"):
        _inapplicable_leaf_ids(_HookReturnsList(), {})


def test_inapplicable_leaf_ids_rejects_a_hook_returning_a_str() -> None:
    with pytest.raises(TypeError, match="frozenset or set of str"):
        _inapplicable_leaf_ids(_HookReturnsStr(), {})


def test_inapplicable_leaf_ids_rejects_a_hook_returning_a_set_with_a_non_string_member() -> None:
    with pytest.raises(TypeError, match="member of type int"):
        _inapplicable_leaf_ids(_HookReturnsSetWithANonStringMember(), {})


def test_inapplicable_leaf_ids_accepts_a_plain_set_of_str() -> None:
    """R13 review finding 2 explicitly permits ``set``, not only
    ``frozenset`` -- the type hint says ``frozenset[str]``, but the
    validation is deliberately looser than the hint on this one point."""

    class _HookReturnsSet:
        def inapplicable_leaf_ids(self, family_case):
            del family_case
            return {"some_leaf"}

    assert _inapplicable_leaf_ids(_HookReturnsSet(), {}) == frozenset({"some_leaf"})
