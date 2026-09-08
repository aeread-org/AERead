"""Runtime enforcement of a declared manifest leaf policy at finalize time.

kernel_contract_impl_review.md findings 5, 6, 12, and 13. These use Housing's
real, already-migrated plugin and scorer end to end -- the finalizer's
call site is exactly production's, only the *manifest* attached to a fresh
registry differs from the one the run-plan happens to carry, exercising
finding 6 directly: a manifest a run-plan carries with no leaf policy at all
must not shadow the trusted registration's declared policy.
"""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from typing import Any, Mapping

import pytest

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import LeafPolicyDeclaration
from aeread.shared_runner.task.evaluation import finalize_family_execution
from aeread.shared_runner.task.execution import TokenPricing, execute_plan_cell
from aeread_families.housing.runner import (
    HousingScriptedLandlordProvider,
    HousingScriptedTenantProvider,
    build_housing_smoke,
)


_HOUSING_LEAF_ID = "housing_social_welfare_leaf"


@dataclasses.dataclass(frozen=True, slots=True)
class _FinalizeOnlySetup:
    """A minimal ``EvaluationSetup`` for finalizing against an alternate registry."""

    plan: Any
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, TokenPricing]


def _with_leaf_policy(
    manifest,
    *,
    leaves: tuple[LeafPolicyDeclaration, ...],
    primary_leaf_id: str,
    admission_leaf_ids: tuple[str, ...],
):
    measurement = dataclasses.replace(
        manifest.measurement,
        leaves=leaves,
        primary_leaf_id=primary_leaf_id,
        admission_leaf_ids=admission_leaf_ids,
    )
    return dataclasses.replace(manifest, measurement=measurement)


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


def _registered_under_declared_policy(setup, plugin, manifest) -> _FinalizeOnlySetup:
    registry = PluginRegistry()
    registry.register_trusted(manifest, plugin)
    return _FinalizeOnlySetup(
        plan=setup.plan,
        registry=registry,
        prompt_sources=setup.prompt_sources,
        pricing=setup.pricing,
    )


def test_finalize_rejects_a_scorer_that_drops_a_declared_finalize_time_leaf(
    tmp_path,
) -> None:
    """Finding 5: the manifest is the source of truth once it declares a policy."""

    setup, execution = _run_housing_episode(tmp_path)
    base_manifest = setup.plan.families[0]
    plugin = setup.registry.resolve_manifest(base_manifest)

    # Housing's real scorer returns exactly one leaf. Declaring a second,
    # undeclared-by-the-scorer finalize_time leaf must be caught, not receipted.
    bad_manifest = _with_leaf_policy(
        base_manifest,
        leaves=(
            LeafPolicyDeclaration(_HOUSING_LEAF_ID, "finalize_time", None),
            LeafPolicyDeclaration("housing_never_produced_leaf", "finalize_time", None),
        ),
        primary_leaf_id=_HOUSING_LEAF_ID,
        admission_leaf_ids=(_HOUSING_LEAF_ID,),
    )
    finalize_setup = _registered_under_declared_policy(setup, plugin, bad_manifest)

    with pytest.raises(ValueError, match="declared finalize-time"):
        finalize_family_execution(setup=finalize_setup, execution=execution)


def test_finalize_carries_a_declared_deferred_leaf_onto_the_receipt(tmp_path) -> None:
    """Findings 6 and 12.

    The run-plan's own manifest copy declares no leaf policy at all (Housing
    is not yet migrated to declare one on its production manifest -- spec
    ruling R4). The registry's trusted registration declares one, including a
    deferred leaf, and the finalizer must use that registration, not the
    run-plan's copy: the receipt must carry the deferred leaf without the
    scorer ever needing to know about it.
    """

    setup, execution = _run_housing_episode(tmp_path)
    base_manifest = setup.plan.families[0]
    plugin = setup.registry.resolve_manifest(base_manifest)
    assert base_manifest.measurement.leaves == (), (
        "sanity: the run-plan's own manifest copy declares no leaf policy"
    )

    manifest = _with_leaf_policy(
        base_manifest,
        leaves=(
            LeafPolicyDeclaration(_HOUSING_LEAF_ID, "finalize_time", None),
            LeafPolicyDeclaration(
                "housing_deferred_diagnostic",
                "deferred",
                "external_rater_verdict",
            ),
        ),
        primary_leaf_id=_HOUSING_LEAF_ID,
        admission_leaf_ids=(_HOUSING_LEAF_ID,),
    )
    finalize_setup = _registered_under_declared_policy(setup, plugin, manifest)

    receipt = finalize_family_execution(setup=finalize_setup, execution=execution)

    assert receipt.status == "ok"
    assert receipt.primary_leaf_id == _HOUSING_LEAF_ID
    assert receipt.deferred_leaf_ids == ("housing_deferred_diagnostic",)


class _EvidenceRefTamperingPlugin:
    """Delegates every hook to a real plugin except a scorer that lies about
    provenance -- the scenario finding 13 is about."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def build_scorer(self, family_case: Mapping[str, Any]):
        real_scorer = self._inner.build_scorer(family_case)

        def tampering_scorer(scoring_input, *, evidence_refs=()):
            score = real_scorer(scoring_input, evidence_refs=evidence_refs)
            return dataclasses.replace(score, evidence_refs=())

        return tampering_scorer


def test_finalize_rejects_a_scorer_whose_evidence_refs_disagree_with_replay(
    tmp_path,
) -> None:
    """Finding 13: evidence_refs on a produced score must be
    scoring_input.evidence_refs verbatim, not merely by convention."""

    setup, execution = _run_housing_episode(tmp_path)
    base_manifest = setup.plan.families[0]
    real_plugin = setup.registry.resolve_manifest(base_manifest)

    registry = PluginRegistry()
    registry.register_trusted(base_manifest, _EvidenceRefTamperingPlugin(real_plugin))
    finalize_setup = _FinalizeOnlySetup(
        plan=setup.plan,
        registry=registry,
        prompt_sources=setup.prompt_sources,
        pricing=setup.pricing,
    )

    with pytest.raises(ValueError, match="evidence_refs"):
        finalize_family_execution(setup=finalize_setup, execution=execution)
