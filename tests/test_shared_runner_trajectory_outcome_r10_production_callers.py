"""Issue #122, requirement 5: trajectory_outcome_paths' declaration must be
read from the TRUSTED registered manifest by all three production callers
of replay_family_scoring_input, and a family that declares none must be
byte-identical, digest-for-digest, to the same family before this change.

Codex review R1 findings 1 and 3 (see docs/kernel_r9r10_review.md's issue
#122 section once Task 4 lands): finding 1 requires adversarial coverage at
all three production callers -- a TRUSTED declaration that is guaranteed to
fail R10 while the run-plan's own manifest copy declares none (must raise),
and the inverse (must pass) -- not only the "both declare the same
genuinely-conforming path" coverage below. Finding 3 requires a pinned,
pre-change golden oracle for digest neutrality, not a two-episode
comparison.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
from pathlib import Path
from typing import Any

import pytest

from aeread.shared_runner import canonical_json_bytes
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run import resolver as _resolver
from aeread.shared_runner.task.evaluation import (
    audit_family_receipt,
    finalize_family_execution,
    replay_family_receipt,
)
from aeread.shared_runner.task.execution import EvidenceStore, execute_plan_cell
from aeread_families.housing.runner import (
    HousingScriptedLandlordProvider,
    HousingScriptedTenantProvider,
    build_housing_smoke,
)


def _with_trajectory_outcome_paths(manifest, paths: tuple[str, ...]):
    measurement = dataclasses.replace(manifest.measurement, trajectory_outcome_paths=paths)
    return dataclasses.replace(manifest, measurement=measurement)


def _poisoned_plan_and_episode(tmp_path: Path, base_setup, *, failing_paths: tuple[str, ...]):
    """A second, independently-sealed RunPlan whose OWN family-manifest copy
    declares `failing_paths` -- needed for finding 1's inverse direction.

    The plan's own copy cannot be mutated in place: `plan_sha256` covers
    `families` (verified against `_plan_payload` in
    `src/aeread/shared_runner/run/resolver.py`), and `execution.run_plan_id`
    is bound to whichever plan sealed it, so a fresh episode must run
    against the re-sealed plan. `resolver._seal_plan` (private; the only
    change here is one family's `measurement`, which `resolve_run_plan`'s
    full suite/sampling/case cross-validation does not need to re-run) is
    the minimal way to get a digest-valid plan back. `PluginRegistry.
    resolve_registration` keys only on `(family_id, family_version,
    plugin_id)` (verified against `src/aeread/shared_runner/registry.py`),
    so passing the SAME, untouched `base_setup.registry` here keeps the
    TRUSTED registration declaring `()` throughout -- only the plan's own
    copy is poisoned."""
    base_manifest = base_setup.plan.families[0]
    poisoned_manifest = _with_trajectory_outcome_paths(base_manifest, failing_paths)
    poisoned_families = tuple(
        poisoned_manifest if family is base_manifest else family
        for family in base_setup.plan.families
    )
    poisoned_plan = _resolver._seal_plan(
        dataclasses.replace(base_setup.plan, families=poisoned_families)
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=poisoned_plan,
            cell_id=poisoned_plan.cells[0].cell_id,
            registry=base_setup.registry,
            evidence_root=tmp_path,
            prompt_sources=base_setup.prompt_sources,
            providers={
                "housing_scripted_tenant": HousingScriptedTenantProvider(),
                "housing_scripted_landlord": HousingScriptedLandlordProvider(),
            },
            pricing=base_setup.pricing,
            episode_attempt_ordinal=0,
        )
    )
    return poisoned_plan, execution


def _run_housing_episode(tmp_path: Path):
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
    return setup, execution


class _FinalizeOnlySetup:
    def __init__(self, plan, registry, prompt_sources, pricing):
        self.plan = plan
        self.registry = registry
        self.prompt_sources = prompt_sources
        self.pricing = pricing


def test_finalize_sources_trajectory_outcome_paths_from_the_trusted_registration(
    tmp_path,
) -> None:
    """A manifest declaring ("/signed_rents",), registered as the TRUSTED
    registration, must be consulted by finalize_family_execution even though
    the run-plan's own manifest copy (base_setup.plan.families[0]) carries
    none -- proving R10 is read from registration.manifest, not the plan's
    copy."""
    base_setup, execution = _run_housing_episode(tmp_path)
    base_manifest = base_setup.plan.families[0]
    real_plugin = base_setup.registry.resolve_manifest(base_manifest)

    declared_manifest = _with_trajectory_outcome_paths(base_manifest, ("/signed_rents",))
    registry = PluginRegistry()
    registry.register_trusted(declared_manifest, real_plugin)

    finalize_setup = _FinalizeOnlySetup(
        plan=base_setup.plan,  # the plan's OWN manifest copy still has no declaration
        registry=registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )

    receipt = finalize_family_execution(setup=finalize_setup, execution=execution)
    # Codex review R1 finding 2: EvaluationReceipt.status permits only "ok"
    # or "invalid_measurement" (receipts.py ~203-204); a conforming
    # finalize on a real, admitted Housing episode is "ok", matching the
    # production expectation at tests/test_shared_runner_housing.py ~354.
    # "admitted" is not a receipt status at all.
    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"
    assert receipt.replay_level == "state_and_score"


def test_finalize_rejects_a_failing_trusted_declaration_even_though_the_plan_copy_is_empty(
    tmp_path,
) -> None:
    """Codex review R1 finding 1, direction 1: the TRUSTED registration
    declares a path guaranteed to fail R10 ("/not_a_real_field" is absent
    from Housing's real outcome); the plan's own manifest copy
    (base_setup.plan) declares none. finalize_family_execution must still
    raise -- proving it is governed by the trusted registration, not a
    default that silently passes because the plan copy is empty."""
    base_setup, execution = _run_housing_episode(tmp_path)
    base_manifest = base_setup.plan.families[0]
    real_plugin = base_setup.registry.resolve_manifest(base_manifest)
    failing_manifest = _with_trajectory_outcome_paths(base_manifest, ("/not_a_real_field",))
    registry = PluginRegistry()
    registry.register_trusted(failing_manifest, real_plugin)
    finalize_setup = _FinalizeOnlySetup(
        plan=base_setup.plan,  # unchanged: plan's own copy still declares ()
        registry=registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    with pytest.raises(AssertionError, match="does not exist in the outcome"):
        finalize_family_execution(setup=finalize_setup, execution=execution)


def test_finalize_passes_when_the_plan_copy_declares_a_failing_path_but_the_trusted_registration_is_empty(
    tmp_path,
) -> None:
    """Codex review R1 finding 1, the inverse direction: the plan's OWN
    manifest copy declares a path guaranteed to fail R10; the TRUSTED
    registration declares none. finalize_family_execution must still pass
    -- proving it never reads trajectory_outcome_paths from
    setup.plan.families[...] at all."""
    base_setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    poisoned_plan, execution = _poisoned_plan_and_episode(
        tmp_path, base_setup, failing_paths=("/not_a_real_field",)
    )
    finalize_setup = _FinalizeOnlySetup(
        plan=poisoned_plan,
        registry=base_setup.registry,  # unchanged: trusted registration still declares ()
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    receipt = finalize_family_execution(setup=finalize_setup, execution=execution)
    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"
    assert receipt.replay_level == "state_and_score"


def test_replay_family_receipt_conforms_with_a_declared_trajectory_outcome_path(
    tmp_path,
) -> None:
    base_setup, execution = _run_housing_episode(tmp_path)
    base_manifest = base_setup.plan.families[0]
    real_plugin = base_setup.registry.resolve_manifest(base_manifest)
    declared_manifest = _with_trajectory_outcome_paths(base_manifest, ("/signed_rents",))
    registry = PluginRegistry()
    registry.register_trusted(declared_manifest, real_plugin)
    finalize_setup = _FinalizeOnlySetup(
        plan=base_setup.plan,
        registry=registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    receipt = finalize_family_execution(setup=finalize_setup, execution=execution)

    replayed = replay_family_receipt(
        setup=finalize_setup, receipt=receipt, evidence_root=tmp_path
    )
    assert canonical_json_bytes(replayed) == canonical_json_bytes(receipt)
    # Codex review R1 finding 2: a conforming replay must itself be a
    # conforming receipt -- "ok"/"included"/"state_and_score", never
    # "admitted" (not a valid status at all) or "invalid_measurement"
    # (replay_family_receipt skips nothing here; there IS a score to
    # replay, so "invalid_measurement" would not be conformance).
    assert replayed.status == "ok"
    assert replayed.inclusion_status == "included"
    assert replayed.replay_level == "state_and_score"


def test_replay_rejects_a_failing_trusted_declaration_even_though_the_plan_copy_is_empty(
    tmp_path,
) -> None:
    """Codex review R1 finding 1, direction 1, at replay_family_receipt: the
    receipt is sealed under a conforming (empty) trusted declaration, then
    replayed under a DIFFERENT registry whose trusted registration declares
    a path guaranteed to fail R10. The plan's own copy (unchanged throughout)
    still declares none. replay_family_receipt must raise."""
    base_setup, execution = _run_housing_episode(tmp_path)
    base_manifest = base_setup.plan.families[0]
    real_plugin = base_setup.registry.resolve_manifest(base_manifest)

    conforming_registry = PluginRegistry()
    conforming_registry.register_trusted(base_manifest, real_plugin)
    finalize_setup = _FinalizeOnlySetup(
        plan=base_setup.plan,
        registry=conforming_registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    receipt = finalize_family_execution(setup=finalize_setup, execution=execution)

    failing_manifest = _with_trajectory_outcome_paths(base_manifest, ("/not_a_real_field",))
    failing_registry = PluginRegistry()
    failing_registry.register_trusted(failing_manifest, real_plugin)
    replay_setup = _FinalizeOnlySetup(
        plan=base_setup.plan,  # unchanged: plan's own copy still declares ()
        registry=failing_registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    with pytest.raises(AssertionError, match="does not exist in the outcome"):
        replay_family_receipt(setup=replay_setup, receipt=receipt, evidence_root=tmp_path)


def test_replay_passes_when_the_plan_copy_declares_a_failing_path_but_the_trusted_registration_is_empty(
    tmp_path,
) -> None:
    """Codex review R1 finding 1, the inverse direction, at
    replay_family_receipt: the plan's OWN manifest copy (poisoned_plan)
    declares a path guaranteed to fail R10; the TRUSTED registration
    declares none throughout. replay_family_receipt must still pass."""
    base_setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    poisoned_plan, execution = _poisoned_plan_and_episode(
        tmp_path, base_setup, failing_paths=("/not_a_real_field",)
    )
    finalize_setup = _FinalizeOnlySetup(
        plan=poisoned_plan,
        registry=base_setup.registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    receipt = finalize_family_execution(setup=finalize_setup, execution=execution)
    replayed = replay_family_receipt(
        setup=finalize_setup, receipt=receipt, evidence_root=tmp_path
    )
    assert replayed.status == "ok"


def test_audit_family_receipt_conforms_with_a_declared_trajectory_outcome_path(
    tmp_path,
) -> None:
    base_setup, execution = _run_housing_episode(tmp_path)
    base_manifest = base_setup.plan.families[0]
    real_plugin = base_setup.registry.resolve_manifest(base_manifest)
    declared_manifest = _with_trajectory_outcome_paths(base_manifest, ("/signed_rents",))
    registry = PluginRegistry()
    registry.register_trusted(declared_manifest, real_plugin)
    finalize_setup = _FinalizeOnlySetup(
        plan=base_setup.plan,
        registry=registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    finalize_family_execution(setup=finalize_setup, execution=execution)
    receipt_path = execution.evidence.root / "evaluation_receipt.json"
    audited = audit_family_receipt(setup=finalize_setup, receipt_path=receipt_path)
    # Codex review R1 finding 2: same fix as the finalize/replay conforming
    # tests above -- "admitted" is not a receipt status, and
    # "invalid_measurement" would not be conformance (audit_family_receipt
    # skips score replay entirely when a receipt has no scores, per
    # evaluation.py's `if receipt.get("scores"):` guard -- accepting
    # "invalid_measurement" here would not prove the score-replay path, let
    # alone R10, ran at all).
    assert audited["status"] == "ok"
    assert audited["inclusion_status"] == "included"
    assert audited["replay_level"] == "state_and_score"


def test_audit_rejects_a_failing_trusted_declaration_even_though_the_plan_copy_is_empty(
    tmp_path,
) -> None:
    """Codex review R1 finding 1, direction 1, at audit_family_receipt: the
    durable receipt is sealed under a conforming (empty) trusted
    declaration, then audited under a DIFFERENT registry whose trusted
    registration declares a path guaranteed to fail R10. The plan's own
    copy (unchanged throughout) still declares none. audit_family_receipt
    must raise."""
    base_setup, execution = _run_housing_episode(tmp_path)
    base_manifest = base_setup.plan.families[0]
    real_plugin = base_setup.registry.resolve_manifest(base_manifest)

    conforming_registry = PluginRegistry()
    conforming_registry.register_trusted(base_manifest, real_plugin)
    finalize_setup = _FinalizeOnlySetup(
        plan=base_setup.plan,
        registry=conforming_registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    finalize_family_execution(setup=finalize_setup, execution=execution)
    receipt_path = execution.evidence.root / "evaluation_receipt.json"

    failing_manifest = _with_trajectory_outcome_paths(base_manifest, ("/not_a_real_field",))
    failing_registry = PluginRegistry()
    failing_registry.register_trusted(failing_manifest, real_plugin)
    audit_setup = _FinalizeOnlySetup(
        plan=base_setup.plan,  # unchanged: plan's own copy still declares ()
        registry=failing_registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    with pytest.raises(AssertionError, match="does not exist in the outcome"):
        audit_family_receipt(setup=audit_setup, receipt_path=receipt_path)


def test_audit_passes_when_the_plan_copy_declares_a_failing_path_but_the_trusted_registration_is_empty(
    tmp_path,
) -> None:
    """Codex review R1 finding 1, the inverse direction, at
    audit_family_receipt: the plan's OWN manifest copy (poisoned_plan)
    declares a path guaranteed to fail R10; the TRUSTED registration
    declares none throughout. audit_family_receipt must still pass."""
    base_setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    poisoned_plan, execution = _poisoned_plan_and_episode(
        tmp_path, base_setup, failing_paths=("/not_a_real_field",)
    )
    finalize_setup = _FinalizeOnlySetup(
        plan=poisoned_plan,
        registry=base_setup.registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    finalize_family_execution(setup=finalize_setup, execution=execution)
    receipt_path = execution.evidence.root / "evaluation_receipt.json"
    audited = audit_family_receipt(setup=finalize_setup, receipt_path=receipt_path)
    assert audited["status"] == "ok"


# Codex review R1 finding 3: a pinned, pre-change golden oracle, not a
# two-episode comparison. Re-derived on THIS branch's base
# (zeyu/issue-135-a1-replay-cell @ b1e3f566, the merge base pinned by the
# workflow that cut this worktree -- see this plan's own "Deviations" note in
# the implementation report), via this same file's `_run_housing_episode`
# fixture helper (Housing's scripted tenant/landlord providers, deterministic
# given a fixed `world_seed` -- verified empirically: two independent
# episodes produce byte-identical `episode_result.outcome` and
# `.phase_instances`).
#
# Two sources of incidental churn had to be neutralized to make this oracle
# reproducible, neither of which ruling R10 itself is responsible for:
#
# 1. `EvidenceStore.__init__`'s `clock` keyword defaults to `_utc_now`
#    (src/aeread/shared_runner/task/execution.py:229-237, used at its
#    `occurred_at` call sites), a real wall-clock read, and
#    `execute_plan_cell` never exposes a way to inject a fixed clock --
#    verified empirically: two independent episodes' sealed
#    `event_root_sha256` (and therefore `receipt_sha256` and the full
#    canonical receipt bytes) differ without freezing it.
#    `EvidenceStore.__init__.__kwdefaults__["clock"]` is the default's
#    storage location for this keyword-only parameter (confirmed
#    empirically: monkeypatching the module-level `_utc_now` name does NOT
#    affect it, because the default was already bound to the original
#    function object at class-definition time) -- monkeypatching that dict
#    entry for the duration of this test is what makes the oracle
#    reproducible against wall-clock drift.
# 2. Deviation from the plan, discovered empirically while deriving this
#    oracle (not anticipated by the plan's own fixture, which passes no
#    `implementation_digest_overrides`): Housing's `build_housing_smoke`
#    (src/aeread_families/housing/runner.py, around its `bridge_digest`
#    computation) hashes `Path(__file__).read_bytes() +
#    Path(evaluation_module.__file__).read_bytes()` -- i.e. Housing's own
#    runtime/reference implementation pins (`housing_feasible_zero_v1` and
#    the `aeread.shared_runner.housing` runtime pin) are, by design,
#    self-referential to `task/evaluation.py`'s OWN raw source bytes. Task
#    2's production change edits that exact file (adding
#    `_assert_trajectory_outcome_paths_are_consistent` and the new
#    `trajectory_outcome_paths` parameter) to satisfy issue #122's actual
#    goal, so those two pin digests change on every commit in this series
#    regardless of whether the new R10 check is itself behaviorally a
#    no-op. This was confirmed by a throwaway bisection across three
#    commits (the A1 base, the end of Task 1, and the end of Task 2; not
#    committed): the receipt is identical at the first two (Task 1 never
#    touches `evaluation.py`) and changes only at Task 2's commit, and the
#    per-field diff isolates the difference to exactly these two
#    implementation pins, nothing else. `build_housing_smoke` already
#    exposes `implementation_digest_overrides` for pinning exactly this
#    kind of incidental, code-identity-tracking digest; passing a fixed
#    `"bridge"` override below neutralizes it so this oracle isolates R10's
#    OWN no-op behavior from an unrelated, unavoidable side effect of
#    editing the file ruling R10 itself lives in.
#
# These two hashes were derived empirically, with both of the above
# neutralized, independently against the A1 base (b1e3f566), the end of
# Task 1 (9b4061a6, "test(scoring_contract): drop the duplicate json-pointer
# tokenizers"), and the end of Task 2 (ac8b8338, "fix(evaluation): enforce
# R10 trajectory-copy consistency at replay") -- identical at all three --
# and are NOT the plan's transcribed values, which were computed against a
# different, older commit, use no digest override, and do not reproduce on
# this branch.
_GOLDEN_RECEIPT_SHA256 = (
    "97f0e5fc6c0185db4443990b7946b7282605a923f9ec1ff3a1bc53855f7bf6e8"
)
_GOLDEN_CANONICAL_BYTES_SHA256 = (
    "15be699d1734def9895e3842c47b2e6d5bc490e50e1b3a248691896430d0b96f"
)

# See the module banner above: fixed only so Housing's own self-referential
# `task/evaluation.py`-bytes implementation pin (`bridge_digest`) does not
# churn this specific digest-neutrality oracle every time this issue's own
# production change edits that file. Every other test in this module uses
# the plain `_run_housing_episode` (no override) because none of them
# compares receipt bytes against a pinned constant.
_FIXED_BRIDGE_DIGEST_FOR_DIGEST_NEUTRALITY_ORACLE = "0" * 64


def _run_housing_episode_with_pinned_bridge_digest(tmp_path: Path):
    setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
        implementation_digest_overrides={
            "bridge": _FIXED_BRIDGE_DIGEST_FOR_DIGEST_NEUTRALITY_ORACLE
        },
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
    return setup, execution


def _freeze_evidence_store_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        EvidenceStore.__init__.__kwdefaults__,
        "clock",
        lambda: "2024-01-01T00:00:00.000000Z",
    )


def test_finalize_is_digest_neutral_with_no_declared_trajectory_outcome_paths(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`finalize_family_execution` on a family declaring
    `trajectory_outcome_paths == ()` must produce these EXACT, pre-change-
    pinned receipt bytes and this EXACT receipt_sha256 after this change --
    proving R10's replay-time check is a true no-op for the undeclared case,
    not merely "close"."""
    _freeze_evidence_store_clock(monkeypatch)
    setup, execution = _run_housing_episode_with_pinned_bridge_digest(tmp_path)
    finalize_setup = _FinalizeOnlySetup(
        plan=setup.plan,
        registry=setup.registry,
        prompt_sources=setup.prompt_sources,
        pricing=setup.pricing,
    )
    receipt = finalize_family_execution(setup=finalize_setup, execution=execution)
    assert receipt.receipt_sha256 == _GOLDEN_RECEIPT_SHA256
    assert (
        hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
        == _GOLDEN_CANONICAL_BYTES_SHA256
    )
