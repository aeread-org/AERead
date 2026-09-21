"""Gated Housing lemons refusal pilot.

One live tenant route on a frozen pack of gate-admitted lemons worlds, with the
three scripted tenant policies run through the same runner on the same pack as
controls. The campaign is descriptive and single-route: it measures the
tenants' net payoff against the scripted bracket per world and per declared
stratum, with world-clustered intervals, and may claim no winner and no ranking.

It follows the Housing population campaign's gate sequence and reuses its
gate-history, sealing and admission machinery. Two rules the family learned
elsewhere are built in rather than copied: the declared worst-case cost is
summed in integer cents (DC-T-05), and a run halts after a declared number of
consecutive operational failures, sealing the untouched cells as typed
missingness (DC-T-08).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import random
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread_families.housing import environment as hz
from aeread_families.housing import lemons

from aeread.shared_runner.quality import QCCoverage, QCEvidenceRef
from aeread.shared_runner.run.campaign import (
    CAMPAIGN_GATE_SEQUENCE,
    CampaignHistoryRecord,
    campaign_gate_artifact_type,
    campaign_promotion_decision,
)
from aeread.shared_runner.run.contract import (
    ContractError,
    load_contract as load_kernel_contract,
    read_sealed,
    require_claim_boundary,
    require_disjoint_seeds,
    require_positive_number,
    require_seed_panel,
    sealed,
    sha256_json,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import (
    OpenRouterChatClient,
    ProviderRequest,
    execute_plan_cell,
)
from aeread.shared_runner.task.receipts import verify_evaluation_receipt

from .population_campaign import (
    _assert_declared_profile_controls,
    _complete_admission_request,
    _failure_usage,
    _invalidate_history,
    _live_stage_root,
    _load_history,
    _record_gate,
    _role_metrics,
    _write_history,
    _write_json,
)
from .runner import (
    GEMINI_38_FLASH_MODEL,
    GOOGLE_AI_STUDIO_GEMINI_38_FLASH_ROUTE,
    GROK_47_MODEL,
    HOUSING_COMMIT_OUTPUT_SCHEMA,
    HOUSING_CONTACT_OUTPUT_SCHEMA,
    HOUSING_INSPECT_OUTPUT_SCHEMA,
    HOUSING_TENANT_LEMONS_PROMPT,
    XAI_GROK_47_ROUTE,
    HousingScriptedLandlordProvider,
    HousingScriptedTenantProvider,
    OpenRouterRoutePin,
    build_housing_smoke,
    finalize_housing_execution,
    finalize_housing_failure,
    replay_housing_receipt,
)


CONTRACT_SCHEMA_VERSION = "aeread.housing_lemons_campaign/0.1"
CAMPAIGN_ID = "housing_lemons_refusal_pilot_v1"
FAMILY_VERSION = "1.0.0"
STAGES = CAMPAIGN_GATE_SEQUENCE[:5]
LIVE_CONDITION_ID = "live_tenant"
STRATA = ("favourite_is_lemon", "favourite_is_sound")

# Sealed routes the driver knows. A contract names one; the driver refuses a
# route whose identity drifts from the pin the runner carries.
ROUTES: dict[str, tuple[str, OpenRouterRoutePin]] = {
    "google_gemini_38_flash": (GEMINI_38_FLASH_MODEL, GOOGLE_AI_STUDIO_GEMINI_38_FLASH_ROUTE),
    "xai_grok_47": (GROK_47_MODEL, XAI_GROK_47_ROUTE),
}

CONTRACT_FIELDS = (
    "schema_version",
    "campaign_id",
    "claim_status",
    "question",
    "primary_estimand",
    "secondary_estimands",
    "primary_contrast",
    "independent_cluster",
    "environment",
    "admission_rule",
    "controls",
    "route",
    "scripted_controls",
    "world_pack",
    "full_trajectory",
    "variance_pilot",
    "analysis",
    "missingness",
    "stopping_rule",
)
PROFILE_CONTROL_KEYS = (
    "harness",
    "tools",
    "memory",
    "reasoning_effort",
    "temperature",
    "top_p",
    "max_output_tokens",
    "timeout_seconds",
    "sdk_retries",
    "max_action_attempts",
    "retryable_conditions",
)
ADMISSION_SCHEMAS = ("housing_inspect_v1", "housing_contact_v1", "housing_commit_v1")
ADMISSION_PROBES = 3


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def _validate_environment(value: Mapping[str, Any]) -> None:
    environment = value["environment"]
    if environment != {
        "family": "housing_v1",
        "world_kind": "lemons",
        "tenants": 6,
        "listings": 4,
        "rounds": 4,
        "common_weight": 0.6,
        "lemon_share": 0.5,
        "lemon_loss": 1000.0,
        "inspection_cost": 25.0,
    }:
        raise ContractError("lemons pilot environment controls drifted")
    if value["admission_rule"] != lemons.DEFAULT_ADMISSION_RULE:
        raise ContractError("lemons pilot admission rule drifted from the family default")
    controls = value["scripted_controls"]
    if (
        not isinstance(controls, list)
        or len(controls) != len(lemons.TENANT_POLICY_IDS)
        or set(controls) != set(lemons.TENANT_POLICY_IDS)
    ):
        raise ContractError("the scripted control panel must be the family's three policies")
    if value["primary_estimand"] != "tenant_net_payoff":
        raise ContractError("the lemons pilot scores tenant_net_payoff")
    if value["independent_cluster"] != "world_seed":
        raise ContractError("the independent cluster is the world seed")


def _validate_controls(value: Mapping[str, Any]) -> None:
    controls = value["controls"]
    expected = {
        "harness": "minimal_chat/1.0",
        "tools": "disabled",
        "memory": "disabled",
        "reasoning_effort": "low",
        "temperature": 0.0,
        "top_p": 1.0,
        "max_output_tokens": 4096,
        "timeout_seconds": 120.0,
        "sdk_retries": 0,
        "max_action_attempts": 4,
        "retryable_conditions": ["length", "rate_limit", "provider_5xx", "empty_response"],
        "tenant_inference_seed_base": 87001,
        "landlord_policy": "housing_scripted_landlord_v1",
        "execution_order": "world_seed_ascending_then_replicate",
    }
    declared = {key: controls.get(key) for key in expected}
    if declared != expected:
        raise ContractError("lemons pilot execution controls drifted")
    extra = set(controls) - set(expected) - {
        "tenant_cost_ceiling_usd",
        "max_consecutive_operational_failures",
    }
    if extra:
        raise ContractError(f"unexpected execution controls: {sorted(extra)}")
    require_positive_number(
        controls.get("tenant_cost_ceiling_usd"), label="controls.tenant_cost_ceiling_usd"
    )
    limit = controls.get("max_consecutive_operational_failures")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ContractError(
            "controls.max_consecutive_operational_failures must be a positive integer"
        )


def _validate_route(value: Mapping[str, Any]) -> None:
    route = value["route"]
    if not isinstance(route, Mapping) or set(route) != {
        "route_id",
        "requested_model",
        "canonical_model",
        "provider",
        "quantization",
        "tenant_profile_id",
    }:
        raise ContractError("route fields are incomplete or unexpected")
    known = ROUTES.get(route["route_id"])
    if known is None:
        raise ContractError(f"unknown route: {route['route_id']!r}")
    requested, pin = known
    if (
        route["requested_model"] != requested
        or route["canonical_model"] != pin.canonical_model
        or route["provider"] != pin.provider
        or route["quantization"] != pin.quantization
    ):
        raise ContractError("route identity drifted from the sealed pin")
    if not isinstance(route["tenant_profile_id"], str) or not route["tenant_profile_id"]:
        raise ContractError("route.tenant_profile_id must be a non-empty string")


def _validate_panels(value: Mapping[str, Any]) -> None:
    pack = value["world_pack"]
    if pack.get("selection") != "first_admitted_seeds_from_stream_by_stratum":
        raise ContractError("world pack selection rule drifted")
    if list(pack.get("strata", ())) != list(STRATA):
        raise ContractError("world pack strata drifted")
    seed_start = pack.get("seed_start")
    if isinstance(seed_start, bool) or not isinstance(seed_start, int) or seed_start < 0:
        raise ContractError("world_pack.seed_start must be a non-negative integer")
    for field in ("full_trajectory_worlds", "worlds_per_stratum"):
        count = pack.get(field)
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ContractError(f"world_pack.{field} must be a positive integer")
    full = value["full_trajectory"]
    pilot = value["variance_pilot"]
    full_seeds = require_seed_panel(
        full.get("world_seeds"), minimum=pack["full_trajectory_worlds"], label="full_trajectory"
    )
    if len(full_seeds) != pack["full_trajectory_worlds"]:
        raise ContractError("full_trajectory world count drifted from the pack declaration")
    pilot_seeds = require_seed_panel(pilot.get("world_seeds"), minimum=2, label="variance_pilot")
    strata = pilot.get("strata")
    if not isinstance(strata, Mapping) or set(strata) != set(STRATA):
        raise ContractError("variance_pilot.strata must list every declared stratum")
    for stratum, seeds in strata.items():
        stratum_seeds = require_seed_panel(seeds, minimum=1, label=f"stratum {stratum}")
        if len(stratum_seeds) != pack["worlds_per_stratum"]:
            raise ContractError(f"stratum {stratum} does not hold worlds_per_stratum seeds")
    flattened = [seed for stratum in STRATA for seed in strata[stratum]]
    if sorted(flattened) != sorted(pilot_seeds):
        raise ContractError("variance_pilot strata do not partition its world seeds")
    require_disjoint_seeds(("full_trajectory", full_seeds), ("variance_pilot", pilot_seeds))
    for label, stage in (("full_trajectory", full), ("variance_pilot", pilot)):
        replicates = stage.get("replicates")
        if isinstance(replicates, bool) or not isinstance(replicates, int) or replicates < 1:
            raise ContractError(f"{label}.replicates must be a positive integer")
        require_positive_number(stage.get("cost_ceiling_usd"), label=f"{label}.cost_ceiling_usd")
    require_claim_boundary(
        pilot,
        keys=(
            "winner_claim_allowed",
            "inferential_model_ranking_allowed",
            "causal_condition_effect_allowed",
        ),
        label="variance_pilot",
    )


def _validate_analysis(value: Mapping[str, Any]) -> None:
    analysis = value["analysis"]
    draws = analysis.get("bootstrap_draws")
    seed = analysis.get("bootstrap_seed")
    for label, item in (("bootstrap_draws", draws), ("bootstrap_seed", seed)):
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise ContractError(f"analysis.{label} must be a positive integer")
    if analysis.get("resampling_unit") != "world_seed":
        raise ContractError("analysis.resampling_unit must be world_seed")
    if analysis.get("interval") != "percentile_95":
        raise ContractError("analysis.interval drifted")
    if analysis.get("predeclared_slices") != ["stratum"]:
        raise ContractError("analysis.predeclared_slices drifted")
    if analysis.get("endpoint_order") != list(ENDPOINT_ORDER):
        raise ContractError("analysis.endpoint_order drifted")
    if value["campaign_id"] != CAMPAIGN_ID:
        raise ContractError(f"this driver accepts only {CAMPAIGN_ID}")
    if value["claim_status"] != "development_qualification":
        raise ContractError("the lemons pilot is development qualification only")


ENDPOINT_ORDER = (
    "tenant_net_payoff",
    "within_case_score",
    "abstention_correctness_rate",
    "uninspected_lemon_signing_rate",
    "live_minus_reference_net_payoff",
)


def load_contract(path: str | Path) -> dict[str, Any]:
    return load_kernel_contract(
        path,
        schema_version=CONTRACT_SCHEMA_VERSION,
        required_keys=CONTRACT_FIELDS,
        validators=(_validate_environment, _validate_controls, _validate_route, _validate_panels, _validate_analysis),
    )


# ---------------------------------------------------------------------------
# World pack
# ---------------------------------------------------------------------------


def _make_world(environment: Mapping[str, Any], seed: int) -> lemons.LemonsWorld:
    return lemons.make_lemons_world(
        environment["tenants"],
        environment["listings"],
        seed,
        environment["common_weight"],
        lemon_share=environment["lemon_share"],
        lemon_loss=environment["lemon_loss"],
        inspection_cost=environment["inspection_cost"],
    )


def favourite_listing(world: lemons.LemonsWorld) -> int:
    """The listing most tenants rank first by value-if-sound gain; ties go to the
    lowest listing id, then to the lowest id among equally popular listings."""
    votes: dict[int, int] = {}
    for tenant in range(world.num_tenants):
        gains = [world.values_if_sound[tenant][l] - world.ask[l] for l in range(world.num_listings)]
        best = max(range(world.num_listings), key=lambda l: (gains[l], -l))
        votes[best] = votes.get(best, 0) + 1
    return max(votes, key=lambda l: (votes[l], -l))


def world_stratum(world: lemons.LemonsWorld) -> str:
    return STRATA[0] if world.quality[favourite_listing(world)] == lemons.LEMON else STRATA[1]


def world_sha256(world: lemons.LemonsWorld) -> str:
    return sha256_json(
        {
            "values": world.values,
            "values_if_sound": world.values_if_sound,
            "costs": world.costs,
            "ask": world.ask,
            "quality": list(world.quality),
        }
    )


def world_row(contract: Mapping[str, Any], seed: int) -> dict[str, Any]:
    environment = contract["environment"]
    world = _make_world(environment, seed)
    facts = lemons.lemons_world_facts(world, environment["rounds"])
    failures = lemons.admission_failures(facts, contract["admission_rule"])
    return {
        "world_seed": seed,
        "world_sha256": world_sha256(world),
        "stratum": world_stratum(world),
        "favourite_listing_id": favourite_listing(world),
        "admitted": not failures,
        "failed_requirements": failures,
        **{
            key: facts[key]
            for key in (
                "lemon_count",
                "oracle_total",
                "sign_anything_total",
                "pass_total",
                "inspect_then_sign_total",
                "sign_anything_normalized",
                "inspect_then_sign_normalized",
                "reference_minus_sign_anything_normalized",
                "sign_anything_lemon_signings",
                "inspect_then_sign_inspections",
                "inverted_ordering_holds",
            )
        },
    }


def select_world_pack(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Walk the declared seed stream: the first admitted world is the
    full-trajectory world, then each stratum fills to its declared size."""
    pack = contract["world_pack"]
    full: list[int] = []
    strata: dict[str, list[int]] = {stratum: [] for stratum in STRATA}
    scanned: list[dict[str, Any]] = []
    seed = pack["seed_start"]
    while len(full) < pack["full_trajectory_worlds"] or any(
        len(seeds) < pack["worlds_per_stratum"] for seeds in strata.values()
    ):
        row = world_row(contract, seed)
        scanned.append(row)
        if row["admitted"]:
            if len(full) < pack["full_trajectory_worlds"]:
                full.append(seed)
            elif len(strata[row["stratum"]]) < pack["worlds_per_stratum"]:
                strata[row["stratum"]].append(seed)
        seed += 1
        if seed - pack["seed_start"] > 10_000:
            raise ContractError("the seed stream did not fill the pack within 10000 seeds")
    return {
        "full_trajectory": full,
        "variance_pilot": sorted(seed for seeds in strata.values() for seed in seeds),
        "strata": strata,
        "scanned_seed_count": len(scanned),
        "excluded_seed_count": sum(1 for row in scanned if not row["admitted"]),
        "rows": scanned,
    }


def _pack_seeds(contract: Mapping[str, Any]) -> list[int]:
    return [*contract["full_trajectory"]["world_seeds"], *contract["variance_pilot"]["world_seeds"]]


def _stratum_of(contract: Mapping[str, Any], seed: int) -> str:
    for stratum, seeds in contract["variance_pilot"]["strata"].items():
        if seed in seeds:
            return stratum
    return "full_trajectory"


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------


def _route_pin(contract: Mapping[str, Any]) -> tuple[str, OpenRouterRoutePin]:
    return ROUTES[contract["route"]["route_id"]]


def build_setup(
    contract: Mapping[str, Any],
    *,
    tenant: str,
    world_seeds: Sequence[int],
    replicates: int,
) -> Any:
    """``tenant`` is ``"live"`` or one of the scripted control policy ids."""
    environment = contract["environment"]
    controls = contract["controls"]
    common = dict(
        world_kind="lemons",
        lemon_share=environment["lemon_share"],
        lemon_loss=environment["lemon_loss"],
        inspection_cost=environment["inspection_cost"],
        num_tenants=environment["tenants"],
        num_listings=environment["listings"],
        rounds=environment["rounds"],
        common_weight=environment["common_weight"],
        world_seeds=tuple(world_seeds),
        replicates=replicates,
        inference_seed_base=controls["tenant_inference_seed_base"],
        landlord_model=controls["landlord_policy"],
    )
    if tenant == "live":
        requested, pin = _route_pin(contract)
        return build_housing_smoke(
            tenant_provider="openrouter",
            tenant_model=requested,
            tenant_revision=pin.canonical_model,
            openrouter_route=pin,
            tenant_profile_id_override=contract["route"]["tenant_profile_id"],
            reasoning_condition_id="lemons_pilot_low_v1",
            reasoning_effort=controls["reasoning_effort"],
            max_output_tokens_override=controls["max_output_tokens"],
            timeout_seconds_override=controls["timeout_seconds"],
            max_action_attempts_override=controls["max_action_attempts"],
            retryable_conditions_override=controls["retryable_conditions"],
            tenant_top_p=controls["top_p"],
            tenant_max_cost_usd_override=controls["tenant_cost_ceiling_usd"],
            **common,
        )
    if tenant not in lemons.TENANT_POLICIES:
        raise ValueError(f"unknown tenant: {tenant!r}")
    return build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model=f"housing_scripted_tenant_{tenant}_v1",
        tenant_revision="1.0.0",
        reasoning_condition_id="lemons_pilot_scripted_v1",
        **common,
    )


def _cells(setup: Any) -> list[Any]:
    return sorted(setup.plan.cells, key=lambda cell: (cell.world_seed, cell.replicate_index))


# ---------------------------------------------------------------------------
# Gate 1: design contract
# ---------------------------------------------------------------------------


def design_contract_artifact(contract: Mapping[str, Any]) -> dict[str, Any]:
    rows = [world_row(contract, seed) for seed in _pack_seeds(contract)]
    digests = [row["world_sha256"] for row in rows]
    if len(set(digests)) != len(digests):
        raise ValueError("duplicate world content in the pack")
    for row in rows:
        if not row["admitted"]:
            raise ValueError(
                f"world {row['world_seed']} fails admission: {row['failed_requirements']}"
            )
        declared = _stratum_of(contract, row["world_seed"])
        if declared != "full_trajectory" and declared != row["stratum"]:
            raise ValueError(f"world {row['world_seed']} is listed under the wrong stratum")
    selected = select_world_pack(contract)
    if (
        selected["full_trajectory"] != list(contract["full_trajectory"]["world_seeds"])
        or selected["strata"] != {
            stratum: list(seeds) for stratum, seeds in contract["variance_pilot"]["strata"].items()
        }
    ):
        raise ValueError("the declared pack is not what the declared selection rule yields")
    plans: list[dict[str, Any]] = []
    cell_count = 0
    for stage in ("full_trajectory", "variance_pilot"):
        block = contract[stage]
        setup = build_setup(
            contract, tenant="live", world_seeds=block["world_seeds"], replicates=block["replicates"]
        )
        _assert_declared_profile_controls(setup, contract["controls"])
        tenant_profile = next(
            profile for profile in setup.plan.agent_profiles if profile.model.provider == "openrouter"
        )
        if tenant_profile.budgets.max_cost_usd != contract["controls"]["tenant_cost_ceiling_usd"]:
            raise ValueError("the tenant cost ceiling did not reach the profile")
        cells = _cells(setup)
        cell_count += len(cells)
        plans.append(
            {
                "stage": stage,
                "run_plan_id": setup.plan.run_plan_id,
                "plan_sha256": setup.plan.plan_sha256,
                "cell_count": len(cells),
                "case_sha256s": [case.content_sha256 for case in setup.plan.cases],
                "tenant_profile_id": tenant_profile.profile_id,
                "tenant_profile_sha256": sha256_json(tenant_profile),
                "prompt_id": tenant_profile.prompt.prompt_id,
                "prompt_sha256": tenant_profile.prompt.sha256,
            }
        )
    ceiling_cents = round(contract["controls"]["tenant_cost_ceiling_usd"] * 100)
    stage_ceiling_cents = sum(
        round(contract[stage]["cost_ceiling_usd"] * 100)
        for stage in ("full_trajectory", "variance_pilot")
    )
    return sealed(
        {
            "schema_version": "aeread.housing_lemons_campaign_design/0.1",
            "campaign_id": contract["campaign_id"],
            "contract_sha256": sha256_json(contract),
            "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "lemons_sha256": hashlib.sha256(Path(lemons.__file__).read_bytes()).hexdigest(),
            "status": "passed",
            "claim_status": contract["claim_status"],
            "primary_estimand": contract["primary_estimand"],
            "primary_contrast": contract["primary_contrast"],
            "independent_cluster": contract["independent_cluster"],
            "route_id": contract["route"]["route_id"],
            "pack_selection": {
                "scanned_seed_count": selected["scanned_seed_count"],
                "excluded_seed_count": selected["excluded_seed_count"],
                "seed_start": contract["world_pack"]["seed_start"],
            },
            "world_count": len(rows),
            "planned_live_cells": cell_count,
            # The ceiling is per profile per cell and every tenant seat binds the
            # one live profile, so a cell can spend at most the ceiling once.
            "worst_case_declared_cost_usd": cell_count * ceiling_cents / 100,
            "worst_case_basis": "cells x per-profile ceiling, summed in integer cents",
            "stage_cost_ceilings_usd": stage_ceiling_cents / 100,
            "binding_limit": "the stage ceilings bind before the per-cell worst case",
            "worlds": rows,
            "plans": plans,
        }
    )


# ---------------------------------------------------------------------------
# Gate 2: provider-free validation -- the scripted bracket on the pack
# ---------------------------------------------------------------------------


def _outcome_row(outcome: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tenant_net_payoff": outcome["tenant_net_total"],
        "within_case_score": outcome["within_case_score"],
        "social_welfare": outcome["social_welfare"],
        "abstention_correctness_rate": outcome["abstention_correctness_rate"],
        "abstention_decision_count": outcome["abstention_decision_count"],
        "uninspected_lemon_signings": outcome["uninspected_lemon_signings"],
        "lemon_signings": outcome["lemon_signings"],
        "inspection_count": outcome["inspection_count"],
        "ir_violation_count": len(outcome["ir_violations"]),
        "wasted_contacts": outcome["wasted_contacts"],
        "sign_anything_total": outcome["sign_anything_total"],
        "reference_total": outcome["reference_total"],
        "oracle_total": outcome["oracle_total"],
    }


async def _run_scripted_cell(setup: Any, cell: Any, *, evidence_root: Path) -> dict[str, Any]:
    execution = await execute_plan_cell(
        plan=setup.plan,
        cell_id=cell.cell_id,
        registry=setup.registry,
        evidence_root=evidence_root,
        prompt_sources=setup.prompt_sources,
        providers={
            "housing_scripted_tenant": HousingScriptedTenantProvider(),
            "housing_scripted_landlord": HousingScriptedLandlordProvider(),
        },
        pricing=setup.pricing,
        harnesses=setup.harnesses,
    )
    receipt = finalize_housing_execution(setup=setup, execution=execution)
    verify_evaluation_receipt(receipt)
    replayed = replay_housing_receipt(setup=setup, receipt=receipt, evidence_root=evidence_root)
    if canonical_json_bytes(replayed.scores) != canonical_json_bytes(receipt.scores):
        raise ValueError("provider-free offline replay mismatch")
    return {
        "receipt_sha256": receipt.receipt_sha256,
        "run_plan_id": setup.plan.run_plan_id,
        "cell_id": cell.cell_id,
        "replay_verified": True,
        **_outcome_row(execution.episode_result.outcome),
    }


async def run_provider_free(
    contract: Mapping[str, Any], *, output_root: Path, attempt_index: int = 1
) -> dict[str, Any]:
    stage_root = _live_stage_root(output_root, "provider_free_validation", attempt_index)
    seeds = _pack_seeds(contract)
    rows: list[dict[str, Any]] = []
    for policy in contract["scripted_controls"]:
        setup = build_setup(contract, tenant=policy, world_seeds=seeds, replicates=1)
        for cell in _cells(setup):
            result_path = stage_root / policy / "results" / f"world_{cell.world_seed}.json"
            if result_path.exists():
                rows.append(read_sealed(result_path))
                continue
            row = await _run_scripted_cell(
                setup, cell, evidence_root=stage_root / policy / "evidence"
            )
            expected = {
                "sign_anything": row["sign_anything_total"],
                "inspect_then_sign": row["reference_total"],
                "pass": 0.0,
            }[policy]
            if not math.isclose(row["tenant_net_payoff"], expected, abs_tol=1e-9):
                raise ValueError(
                    f"{policy} through the runner disagrees with the offline gate on "
                    f"world {cell.world_seed}"
                )
            row = sealed(
                {
                    "policy": policy,
                    "world_seed": cell.world_seed,
                    "stratum": _stratum_of(contract, cell.world_seed),
                    "status": "completed",
                    **row,
                }
            )
            _write_json(result_path, row)
            rows.append(row)
    expected_rows = len(seeds) * len(contract["scripted_controls"])
    if len(rows) != expected_rows:
        raise ValueError("provider-free validation did not cover the pack")
    artifact = sealed(
        {
            "schema_version": "aeread.housing_lemons_provider_free/0.1",
            "campaign_id": contract["campaign_id"],
            "status": "passed",
            "covered_world_ids": [f"world_{seed}" for seed in seeds],
            "policies": list(contract["scripted_controls"]),
            "replay_verified": True,
            "runner_matches_offline_gate": True,
            "provider_cost_usd": 0.0,
            "rows": rows,
        }
    )
    _write_json(stage_root / "summary.json", artifact)
    return artifact


# ---------------------------------------------------------------------------
# Gate 3: profile admission -- one live probe per action schema
# ---------------------------------------------------------------------------


def _admission_observations(
    environment: Mapping[str, Any], seed: int
) -> dict[str, Mapping[str, Any]]:
    world = _make_world(environment, seed)
    market = hz.HousingMarket(world, rounds=environment["rounds"])
    inspect = market.tenant_observation(0)
    market.submit_inspections({0: favourite_listing(world)})
    contact = market.tenant_observation(0)
    listing = favourite_listing(world)
    result = market.submit_offers({0: (listing, world.ask[listing])})
    market.submit_responses(hz.scripted_landlord_responses(market, result.inbox))
    commit = market.tenant_observation(0)
    if commit["active_hold"] is None:
        raise ValueError("admission fixture did not create the expected tenant hold")
    return {
        "housing_inspect_v1": inspect,
        "housing_contact_v1": contact,
        "housing_commit_v1": commit,
    }


def _hold_id(hold: Any) -> str | None:
    if hold is None:
        return None
    if isinstance(hold, Mapping):
        return hold.get("hold_id")
    return getattr(hold, "hold_id", None)


def _validate_admission_action(
    action_schema: str, output_text: str, observation: Mapping[str, Any]
) -> dict[str, Any]:
    value = json.loads(output_text)
    if not isinstance(value, dict):
        raise ValueError("admission output is not an object")
    open_ids = {row["listing_id"] for row in observation["board"] if row["status"] == "OPEN"}
    if action_schema == "housing_inspect_v1":
        if set(value) != {"decision", "listing_id"}:
            raise ValueError("inspect action fields drifted")
        inspected = {row["listing_id"] for row in observation["inspections"]}
        if value["decision"] == "pass":
            valid = value["listing_id"] is None
        else:
            valid = (
                value["decision"] == "inspect"
                and value["listing_id"] in open_ids
                and value["listing_id"] not in inspected
            )
    elif action_schema == "housing_contact_v1":
        if set(value) != {"decision", "listing_id", "rent"}:
            raise ValueError("contact action fields drifted")
        if value["decision"] == "pass":
            valid = value["listing_id"] is None and value["rent"] is None
        else:
            valid = (
                value["decision"] == "offer"
                and value["listing_id"] in open_ids
                and isinstance(value["rent"], (int, float))
                and not isinstance(value["rent"], bool)
                and math.isfinite(float(value["rent"]))
                and float(value["rent"]) >= 0.0
            )
    elif action_schema == "housing_commit_v1":
        if set(value) != {"decision", "hold_id"}:
            raise ValueError("commit action fields drifted")
        hold_id = _hold_id(observation["active_hold"])
        if value["decision"] == "pass":
            valid = value["hold_id"] is None
        else:
            valid = value["decision"] in {"sign", "walk"} and value["hold_id"] == hold_id
    else:  # pragma: no cover - protected by the caller
        raise ValueError(f"unknown admission schema: {action_schema}")
    if not valid:
        raise ValueError(f"semantically invalid {action_schema} admission action")
    return value


def _admission_request(
    contract: Mapping[str, Any],
    *,
    action_schema: str,
    observation: Mapping[str, Any],
    probe_index: int,
) -> ProviderRequest:
    controls = contract["controls"]
    requested, pin = _route_pin(contract)
    output_schema = {
        "housing_inspect_v1": HOUSING_INSPECT_OUTPUT_SCHEMA,
        "housing_contact_v1": HOUSING_CONTACT_OUTPUT_SCHEMA,
        "housing_commit_v1": HOUSING_COMMIT_OUTPUT_SCHEMA,
    }[action_schema]
    phase_id = action_schema.split("_")[1]
    input_text = canonical_json_bytes(
        {
            "phase_id": phase_id,
            "seat_id": "tenant_0",
            "role": "tenant",
            "observation_schema": f"housing_tenant_{phase_id}_observation_v1",
            "action_schema": action_schema,
            "observation": observation,
        }
    ).decode("utf-8")
    return ProviderRequest(
        provider_call_id=f"admission_{contract['route']['route_id']}_{phase_id}_{probe_index}",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        model=requested,
        revision=pin.canonical_model,
        instructions=HOUSING_TENANT_LEMONS_PROMPT,
        input_text=input_text,
        temperature=controls["temperature"],
        top_p=controls["top_p"],
        max_output_tokens=controls["max_output_tokens"],
        reasoning_effort=controls["reasoning_effort"],
        timeout_seconds=controls["timeout_seconds"],
        request_sha256="",
        max_cost_usd=controls["tenant_cost_ceiling_usd"],
        output_schema=output_schema,
        provider_metadata=pin.provider_metadata(),
        seed=103_001 + probe_index,
    ).with_computed_hash()


async def run_profile_admission(
    contract: Mapping[str, Any], *, client: Any | None = None
) -> dict[str, Any]:
    client = client or OpenRouterChatClient()
    setup = build_setup(
        contract,
        tenant="live",
        world_seeds=contract["full_trajectory"]["world_seeds"],
        replicates=1,
    )
    _assert_declared_profile_controls(setup, contract["controls"])
    tenant_profile = next(
        profile for profile in setup.plan.agent_profiles if profile.model.provider == "openrouter"
    )
    results: list[dict[str, Any]] = []
    for probe_index in range(ADMISSION_PROBES):
        observations = _admission_observations(contract["environment"], 73_001 + probe_index)
        for action_schema in ADMISSION_SCHEMAS:
            request = _admission_request(
                contract,
                action_schema=action_schema,
                observation=observations[action_schema],
                probe_index=probe_index,
            )
            started = time.perf_counter()
            result, attempts = await _complete_admission_request(
                client=client, request=request, controls=contract["controls"]
            )
            action = _validate_admission_action(
                action_schema, result.output_text, observations[action_schema]
            )
            results.append(
                {
                    "route_id": contract["route"]["route_id"],
                    "role": "tenant",
                    "profile_id": tenant_profile.profile_id,
                    "action_schema": action_schema,
                    "probe_index": probe_index,
                    "status": "passed",
                    "request_sha256": request.request_sha256,
                    "response_id": result.response_id,
                    "resolved_model": result.resolved_model,
                    "action_sha256": sha256_json(action),
                    "input_tokens": result.input_tokens,
                    "cached_input_tokens": result.cached_input_tokens,
                    "output_tokens": result.output_tokens,
                    "cost_usd": sum(row["cost_usd"] for row in attempts),
                    "elapsed_seconds": time.perf_counter() - started,
                    "route_verified": True,
                    "sdk_retries": 0,
                    "effective_retry_count": len(attempts) - 1,
                    "attempts": attempts,
                }
            )
    if len(results) != ADMISSION_PROBES * len(ADMISSION_SCHEMAS):
        raise ValueError("profile admission did not complete every declared probe")
    return sealed(
        {
            "schema_version": "aeread.housing_lemons_profile_admission/0.1",
            "campaign_id": contract["campaign_id"],
            "status": "passed",
            "probe_count": len(results),
            "profile_sha256s": {tenant_profile.profile_id: sha256_json(tenant_profile)},
            "total_cost_usd": sum(row["cost_usd"] for row in results),
            "hidden_retry_count": 0,
            "effective_retry_count": sum(row["effective_retry_count"] for row in results),
            "results": results,
        }
    )


# ---------------------------------------------------------------------------
# Gates 4 and 5: live stages
# ---------------------------------------------------------------------------


def _prior_completed_rows(output_root: Path, stage: str, attempt_index: int) -> dict[str, dict[str, Any]]:
    """Completed rows sealed by earlier attempts of the same stage, keyed by cell
    key, so a halted attempt's finished cells are not paid for twice. Failed
    cells are never reused: they re-execute as a further, separately rooted
    attempt and the failed attempt stays on record where it happened."""
    reusable: dict[str, dict[str, Any]] = {}
    for prior in range(1, attempt_index):
        results = _live_stage_root(output_root, stage, prior) / LIVE_CONDITION_ID / "results"
        if not results.is_dir():
            continue
        for path in sorted(results.glob("world_*__rep_*.json")):
            row = read_sealed(path)
            if row.get("status") == "completed":
                reusable[path.stem] = {**row, "reused_from_attempt": prior}
    return reusable


def _latest_stage_summary(output_root: Path, stage: str) -> dict[str, Any] | None:
    latest = None
    for attempt in range(1, 100):
        path = _live_stage_root(output_root, stage, attempt) / "summary.json"
        if path.exists():
            latest = read_sealed(path)
        elif attempt > 1:
            break
    return latest


async def run_live_stage(
    contract: Mapping[str, Any],
    *,
    stage: str,
    output_root: Path,
    attempt_index: int = 1,
    client: Any | None = None,
) -> dict[str, Any]:
    stage_contract = contract[stage]
    controls = contract["controls"]
    setup = build_setup(
        contract,
        tenant="live",
        world_seeds=stage_contract["world_seeds"],
        replicates=stage_contract["replicates"],
    )
    _assert_declared_profile_controls(setup, contract["controls"])
    client = client or OpenRouterChatClient()
    stage_root = _live_stage_root(output_root, stage, attempt_index)
    results_root = stage_root / LIVE_CONDITION_ID / "results"
    evidence_root = stage_root / LIVE_CONDITION_ID / "evidence"
    reusable = _prior_completed_rows(output_root, stage, attempt_index)
    cells = _cells(setup)
    rows: list[dict[str, Any]] = []
    consecutive_failures = 0
    halted_at: str | None = None
    for cell in cells:
        key = f"world_{cell.world_seed}__rep_{cell.replicate_index}"
        result_path = results_root / f"{key}.json"
        if result_path.exists():
            rows.append(read_sealed(result_path))
            continue
        if key in reusable:
            row = sealed({k: v for k, v in reusable[key].items() if k != "artifact_sha256"})
            _write_json(result_path, row)
            rows.append(row)
            continue
        if halted_at is not None:
            rows.append(
                sealed(
                    {
                        "condition_id": LIVE_CONDITION_ID,
                        "world_seed": cell.world_seed,
                        "replicate_index": cell.replicate_index,
                        "stratum": _stratum_of(contract, cell.world_seed),
                        "status": "not_attempted",
                        "failure_condition": "halted_after_consecutive_operational_failures",
                        "halted_at": halted_at,
                        "cost_usd": 0.0,
                    }
                )
            )
            continue
        cost_so_far = sum(float(row.get("cost_usd", 0.0)) for row in rows)
        if cost_so_far >= stage_contract["cost_ceiling_usd"]:
            raise RuntimeError(f"{stage} cost ceiling reached before the pack completed")
        started = time.perf_counter()
        try:
            execution = await execute_plan_cell(
                plan=setup.plan,
                cell_id=cell.cell_id,
                registry=setup.registry,
                evidence_root=evidence_root,
                prompt_sources=setup.prompt_sources,
                providers={
                    "openrouter": client,
                    "housing_scripted_landlord": HousingScriptedLandlordProvider(),
                },
                pricing=setup.pricing,
                harnesses=setup.harnesses,
                episode_attempt_ordinal=attempt_index - 1,
            )
            receipt = finalize_housing_execution(setup=setup, execution=execution)
            verify_evaluation_receipt(receipt)
            replayed = replay_housing_receipt(
                setup=setup, receipt=receipt, evidence_root=evidence_root
            )
            if canonical_json_bytes(replayed.scores) != canonical_json_bytes(receipt.scores):
                raise ValueError("offline replay score mismatch")
            row = {
                "condition_id": LIVE_CONDITION_ID,
                "world_seed": cell.world_seed,
                "replicate_index": cell.replicate_index,
                "stratum": _stratum_of(contract, cell.world_seed),
                "status": "completed",
                **_outcome_row(execution.episode_result.outcome),
                "commit_decisions": execution.episode_result.outcome["commit_decisions"],
                "logical_action_count": execution.episode_result.logical_action_count,
                "cost_usd": execution.total_cost_usd,
                "elapsed_seconds": time.perf_counter() - started,
                "receipt_sha256": receipt.receipt_sha256,
                "run_plan_id": setup.plan.run_plan_id,
                "cell_id": cell.cell_id,
                "route_verified": True,
                "provider_cost_complete": True,
                "replay_verified": True,
                "role_metrics": _role_metrics(
                    execution, tenant_profile_id=contract["route"]["tenant_profile_id"]
                ),
            }
            consecutive_failures = 0
        except Exception as error:
            receipt_sha256 = None
            try:
                failure_receipt = finalize_housing_failure(
                    setup=setup, cell_id=cell.cell_id, evidence_root=evidence_root, error=error
                )
                receipt_sha256 = failure_receipt.receipt_sha256
            except Exception:
                pass
            usage = _failure_usage(
                evidence_root=evidence_root, run_plan_id=setup.plan.run_plan_id, cell_id=cell.cell_id
            )
            row = {
                "condition_id": LIVE_CONDITION_ID,
                "world_seed": cell.world_seed,
                "replicate_index": cell.replicate_index,
                "stratum": _stratum_of(contract, cell.world_seed),
                "status": "operational_failure",
                "failure_type": type(error).__name__,
                "failure_condition": getattr(error, "condition", "execution_error"),
                "failure_status_code": getattr(error, "status_code", None),
                "receipt_sha256": receipt_sha256,
                "cost_usd": usage["cost_usd"],
                "failure_usage": usage,
                "elapsed_seconds": time.perf_counter() - started,
            }
            consecutive_failures += 1
            if consecutive_failures >= controls["max_consecutive_operational_failures"]:
                halted_at = key
        row = sealed(row)
        _write_json(result_path, row)
        rows.append(row)
    expected = len(cells)
    completed = [row for row in rows if row["status"] == "completed"]
    total_cost = sum(float(row.get("cost_usd", 0.0)) for row in rows)
    control_summary = _latest_stage_summary(output_root, "provider_free_validation")
    control_rows = control_summary["rows"] if control_summary else []
    analysis = analyze_pilot(rows, control_rows, contract) if stage == "variance_pilot" else None
    artifact = sealed(
        {
            "schema_version": "aeread.housing_lemons_pilot_results/0.1",
            "campaign_id": contract["campaign_id"],
            "stage": stage,
            "attempt_index": attempt_index,
            "route_id": contract["route"]["route_id"],
            "claim_status": (
                "integration_only" if stage == "full_trajectory" else "exploratory_variance_pilot"
            ),
            "winner_claim_allowed": False,
            "inferential_model_ranking_allowed": False,
            "planned_cells": expected,
            "completed_cells": len(completed),
            "operational_failures": sum(1 for row in rows if row["status"] == "operational_failure"),
            "not_attempted_cells": sum(1 for row in rows if row["status"] == "not_attempted"),
            "halted_at": halted_at,
            "complete_pack": len(completed) == expected,
            "total_cost_usd": total_cost,
            "cost_qualifier": "exact" if len(completed) == expected else "lower_bound",
            "cost_ceiling_usd": stage_contract["cost_ceiling_usd"],
            "analysis": analysis,
            "rows": rows,
        }
    )
    _write_json(stage_root / "summary.json", artifact)
    if halted_at is not None:
        raise RuntimeError(
            f"{stage} halted after {controls['max_consecutive_operational_failures']} "
            f"consecutive operational failures at {halted_at}"
        )
    if len(completed) != expected:
        raise RuntimeError(f"{stage} pack is incomplete")
    if total_cost > stage_contract["cost_ceiling_usd"]:
        raise RuntimeError(f"{stage} exceeded its cost ceiling")
    return artifact


# ---------------------------------------------------------------------------
# Analysis: descriptive, world-clustered, one shared stream
# ---------------------------------------------------------------------------


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _bootstrap_mean(
    values_by_world: Mapping[int, float], *, draws: int, stream: random.Random
) -> dict[str, Any]:
    worlds = sorted(values_by_world)
    point = _mean([values_by_world[world] for world in worlds])
    if point is None or len(worlds) < 2:
        return {"point": point, "ci95": None, "worlds": len(worlds)}
    means: list[float] = []
    for _ in range(draws):
        sample = [values_by_world[stream.choice(worlds)] for _ in worlds]
        means.append(sum(sample) / len(sample))
    means.sort()
    return {
        "point": point,
        "ci95": [means[int(0.025 * draws)], means[min(draws - 1, int(0.975 * draws))]],
        "worlds": len(worlds),
    }


def _per_world(rows: Sequence[Mapping[str, Any]], field: str) -> dict[int, float]:
    grouped: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        value = row.get(field)
        if row.get("status") == "completed" and isinstance(value, (int, float)) and not isinstance(value, bool):
            grouped[int(row["world_seed"])].append(float(value))
    return {world: sum(values) / len(values) for world, values in grouped.items()}


def analyze_pilot(
    live_rows: Sequence[Mapping[str, Any]],
    control_rows: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Descriptive endpoints with world-clustered percentile intervals. One stream
    seeded by the contract serves every interval in the declared order, overall
    first and then each stratum, so two analysts with the contract get the same
    numbers."""
    analysis = contract["analysis"]
    draws = analysis["bootstrap_draws"]
    stream = random.Random(analysis["bootstrap_seed"])
    reference = {
        int(row["world_seed"]): float(row["tenant_net_payoff"])
        for row in control_rows
        if row.get("policy") == "inspect_then_sign" and row.get("status") == "completed"
    }
    sign_anything = {
        int(row["world_seed"]): float(row["tenant_net_payoff"])
        for row in control_rows
        if row.get("policy") == "sign_anything" and row.get("status") == "completed"
    }
    completed = [row for row in live_rows if row.get("status") == "completed"]

    def endpoints(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        rows = [dict(row) for row in rows]
        for row in rows:
            row["uninspected_lemon_signing"] = 1.0 if row.get("uninspected_lemon_signings", 0) else 0.0
            if row["world_seed"] in reference:
                row["live_minus_reference_net_payoff"] = (
                    float(row["tenant_net_payoff"]) - reference[row["world_seed"]]
                )
        fields = {
            "tenant_net_payoff": "tenant_net_payoff",
            "within_case_score": "within_case_score",
            "abstention_correctness_rate": "abstention_correctness_rate",
            "uninspected_lemon_signing_rate": "uninspected_lemon_signing",
            "live_minus_reference_net_payoff": "live_minus_reference_net_payoff",
        }
        out: dict[str, Any] = {}
        for endpoint in ENDPOINT_ORDER:
            out[endpoint] = _bootstrap_mean(_per_world(rows, fields[endpoint]), draws=draws, stream=stream)
        worlds = {int(row["world_seed"]) for row in rows}
        out["cells"] = len(rows)
        out["worlds"] = len(worlds)
        out["cells_above_reference"] = sum(
            1 for row in rows if row["world_seed"] in reference and float(row["tenant_net_payoff"]) > reference[row["world_seed"]]
        )
        out["cells_below_sign_anything"] = sum(
            1 for row in rows if row["world_seed"] in sign_anything and float(row["tenant_net_payoff"]) < sign_anything[row["world_seed"]]
        )
        out["cells_with_uninspected_lemon_signing"] = sum(
            1 for row in rows if row.get("uninspected_lemon_signings", 0)
        )
        return out

    overall = endpoints(completed)
    by_stratum = {
        stratum: endpoints([row for row in completed if row.get("stratum") == stratum])
        for stratum in STRATA
    }
    planned = len(live_rows)
    return {
        "schema_version": "aeread.housing_lemons_pilot_analysis/0.1",
        "campaign_id": contract["campaign_id"],
        "predeclared": {
            "primary": contract["primary_estimand"],
            "contrast": contract["primary_contrast"],
            "bootstrap": {
                "draws": draws,
                "seed": analysis["bootstrap_seed"],
                "resampling_unit": analysis["resampling_unit"],
                "procedure": analysis["bootstrap_procedure"],
            },
            "endpoint_order": list(ENDPOINT_ORDER),
        },
        "planned_cells": planned,
        "completed_cells": len(completed),
        "missingness_fraction": (planned - len(completed)) / planned if planned else None,
        "reference_worlds": len(reference),
        "overall": overall,
        "by_stratum": by_stratum,
        "winner_claim_allowed": False,
        "inferential_model_ranking_allowed": False,
    }


# ---------------------------------------------------------------------------
# Gate history
# ---------------------------------------------------------------------------


def _expected_gate_coverage(contract: Mapping[str, Any], gate_id: str) -> tuple[str, ...]:
    if gate_id == "design_contract":
        return tuple(f"world_{seed}" for seed in _pack_seeds(contract))
    if gate_id == "provider_free_validation":
        return (
            *(
                f"{policy}.world_{seed}"
                for policy in contract["scripted_controls"]
                for seed in _pack_seeds(contract)
            ),
            "provider_free_replay",
        )
    if gate_id == "profile_admission":
        return tuple(
            f"{contract['route']['route_id']}.tenant.{schema}.probe_{index}"
            for index in range(ADMISSION_PROBES)
            for schema in ADMISSION_SCHEMAS
        )
    if gate_id in {"full_trajectory", "variance_pilot"}:
        stage = contract[gate_id]
        return tuple(
            f"{LIVE_CONDITION_ID}.world_{seed}.rep_{replicate}"
            for seed in stage["world_seeds"]
            for replicate in range(stage["replicates"])
        )
    return (gate_id,)


def _observed_gate_coverage(artifact: Mapping[str, Any] | None, gate_id: str) -> tuple[str, ...]:
    if artifact is None:
        return ()
    if gate_id == "design_contract":
        return tuple(f"world_{row['world_seed']}" for row in artifact.get("worlds", ()) if row.get("admitted"))
    if gate_id == "provider_free_validation":
        observed = [f"{row['policy']}.world_{row['world_seed']}" for row in artifact.get("rows", ())]
        if artifact.get("replay_verified") is True:
            observed.append("provider_free_replay")
        return tuple(observed)
    if gate_id == "profile_admission":
        return tuple(
            f"{row['route_id']}.{row['role']}.{row['action_schema']}.probe_{row['probe_index']}"
            for row in artifact.get("results", ())
            if row.get("status") == "passed"
        )
    if gate_id in {"full_trajectory", "variance_pilot"}:
        return tuple(
            f"{row['condition_id']}.world_{row['world_seed']}.rep_{row['replicate_index']}"
            for row in artifact.get("rows", ())
            if row.get("status") == "completed"
        )
    return (gate_id,) if artifact.get("status") == "passed" else ()


def _gate_evidence(
    *,
    contract: Mapping[str, Any],
    gate_id: str,
    artifact_type: str,
    path: Path,
    evidence_root: Path,
    artifact: Mapping[str, Any] | None,
) -> QCEvidenceRef:
    return QCEvidenceRef(
        artifact_type=artifact_type,
        path=str(path.relative_to(evidence_root)),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        family_id=contract["environment"]["family"],
        family_version=FAMILY_VERSION,
        profile_id=contract["campaign_id"],
        coverage=(
            QCCoverage(
                coverage_id=gate_id,
                required_ids=_expected_gate_coverage(contract, gate_id),
                observed_ids=_observed_gate_coverage(artifact, gate_id),
            ),
        ),
    )


def _latest_status(
    records: Sequence[CampaignHistoryRecord], campaign_id: str, gate_id: str, *, evidence_root: Path
) -> str | None:
    from .population_campaign import _latest_status as latest

    return latest(records, campaign_id, gate_id, evidence_root=evidence_root)


async def execute_campaign(
    *,
    contract_path: Path,
    output_root: Path,
    through: str,
    invalidate_from: str | None = None,
    changed_controls: Sequence[str] = (),
    invalidation_reason: str | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    if through not in STAGES:
        raise ValueError(f"through must be one of {STAGES}")
    contract = load_contract(contract_path)
    output_root.mkdir(parents=True, exist_ok=True)
    history_path = output_root / "gate_history.json"
    records = _load_history(history_path)
    summaries: dict[str, Any] = {}
    invalidation_summary: dict[str, Any] | None = None
    if invalidate_from is not None:
        if invalidate_from not in STAGES:
            raise ValueError(f"invalidate_from must be one of {STAGES}")
        if not changed_controls or not (invalidation_reason or "").strip():
            raise ValueError("changed_controls and invalidation_reason are required")
        records = _invalidate_history(
            records=records,
            contract=contract,
            output_root=output_root,
            from_gate_id=invalidate_from,
            changed_controls=changed_controls,
            reason=invalidation_reason,
        )
        _write_history(history_path, records)
        invalidation_summary = {
            "from_gate_id": invalidate_from,
            "changed_controls": list(changed_controls),
            "reason": invalidation_reason,
        }
    elif changed_controls or invalidation_reason is not None:
        raise ValueError("invalidate_from is required when invalidation details are supplied")
    for gate_id in STAGES[: STAGES.index(through) + 1]:
        if _latest_status(records, contract["campaign_id"], gate_id, evidence_root=output_root) == "passed":
            summaries[gate_id] = {"status": "already_passed"}
            continue
        decision = campaign_promotion_decision(
            contract["campaign_id"], gate_id, records, evidence_root=output_root
        )
        attempt_index = decision.next_attempt_index
        attempt_root = _live_stage_root(output_root, gate_id, attempt_index)
        artifact: Mapping[str, Any] | None = None
        try:
            if gate_id == "design_contract":
                artifact = design_contract_artifact(contract)
                path = attempt_root / "summary.json"
                _write_json(path, artifact)
            elif gate_id == "provider_free_validation":
                artifact = await run_provider_free(contract, output_root=output_root, attempt_index=attempt_index)
                path = attempt_root / "summary.json"
            elif gate_id == "profile_admission":
                artifact = await run_profile_admission(contract, client=client)
                path = attempt_root / "summary.json"
                _write_json(path, artifact)
            else:
                artifact = await run_live_stage(
                    contract, stage=gate_id, output_root=output_root, attempt_index=attempt_index, client=client
                )
                path = attempt_root / "summary.json"
            records = _record_gate(
                records=records,
                campaign_id=contract["campaign_id"],
                family_id=contract["environment"]["family"],
                family_version=FAMILY_VERSION,
                profile_id=contract["campaign_id"],
                gate_id=gate_id,
                status="passed",
                evidence_root=output_root,
                evidence_refs=(
                    _gate_evidence(
                        contract=contract,
                        gate_id=gate_id,
                        artifact_type=campaign_gate_artifact_type(gate_id, "passed"),
                        path=path,
                        evidence_root=output_root,
                        artifact=artifact,
                    ),
                ),
            )
            _write_history(history_path, records)
            summaries[gate_id] = {"status": "passed", "artifact_sha256": artifact["artifact_sha256"]}
        except Exception as error:
            failure_path = attempt_root / "failure.json"
            failure = sealed(
                {
                    "campaign_id": contract["campaign_id"],
                    "gate_id": gate_id,
                    "status": "failed",
                    "failure_type": type(error).__name__,
                    "failure_condition": getattr(error, "condition", "stage_failure"),
                    "message": str(error),
                }
            )
            _write_json(failure_path, failure)
            records = _record_gate(
                records=records,
                campaign_id=contract["campaign_id"],
                family_id=contract["environment"]["family"],
                family_version=FAMILY_VERSION,
                profile_id=contract["campaign_id"],
                gate_id=gate_id,
                status="failed",
                evidence_root=output_root,
                evidence_refs=(
                    _gate_evidence(
                        contract=contract,
                        gate_id=gate_id,
                        artifact_type=campaign_gate_artifact_type(gate_id, "failed"),
                        path=failure_path,
                        evidence_root=output_root,
                        artifact=artifact,
                    ),
                ),
                failure_reasons=(str(error) or type(error).__name__,),
            )
            _write_history(history_path, records)
            summaries[gate_id] = {
                "status": "failed",
                "failure_type": type(error).__name__,
                "message": str(error),
            }
            break
    return {
        "campaign_id": contract["campaign_id"],
        "through": through,
        "invalidation": invalidation_summary,
        "gate_summaries": summaries,
        "gate_history": str(history_path),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=Path("configs") / f"{CAMPAIGN_ID}.json")
    parser.add_argument("--run-root", dest="run_root", type=Path, required=True)
    parser.add_argument("--through", choices=STAGES, default="design_contract")
    parser.add_argument("--invalidate-from", choices=STAGES, default=None)
    parser.add_argument("--changed-control", action="append", default=[])
    parser.add_argument("--invalidation-reason", default=None)
    parser.add_argument("--select-pack", action="store_true", help="print the pack the selection rule yields and exit")
    arguments = parser.parse_args(argv)
    if arguments.select_pack:
        contract = load_contract(arguments.contract)
        selected = select_world_pack(contract)
        print(json.dumps({key: value for key, value in selected.items() if key != "rows"}, indent=2, sort_keys=True))
        return 0
    summary = asyncio.run(
        execute_campaign(
            contract_path=arguments.contract,
            output_root=arguments.run_root,
            through=arguments.through,
            invalidate_from=arguments.invalidate_from,
            changed_controls=tuple(arguments.changed_control),
            invalidation_reason=arguments.invalidation_reason,
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if all(item.get("status") in {"passed", "already_passed"} for item in summary["gate_summaries"].values()) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
