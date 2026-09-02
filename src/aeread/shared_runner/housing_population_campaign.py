"""Gated Housing V1 model-population cross-play campaign.

The campaign compares two homogeneous tenant populations over a frozen
landlord panel.  Scripted anchors, cross-model play, and same-model self-play
are executed in one complete matrix but remain separate in analysis.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from scipy import stats

from aeread.housing_v1 import environment as hz

from .campaign import (
    CAMPAIGN_GATE_SEQUENCE,
    CampaignGateRecord,
    CampaignHistoryRecord,
    CampaignInvalidationRecord,
    append_campaign_gate,
    append_campaign_invalidation,
    campaign_active_gate_records,
    campaign_gate_artifact_type,
    campaign_history_record_from_dict,
    campaign_history_record_to_dict,
    campaign_promotion_decision,
)
from .execution import (
    EvidenceStore,
    OpenRouterChatClient,
    ProviderRequest,
    execute_plan_cell,
)
from .housing import (
    DEEPINFRA_GLM_53_FLASH_ROUTE,
    DEEPINFRA_HOUSING_ROUTE,
    GLM_53_FLASH_MODEL,
    GLM_53_FLASH_REVISION,
    HOUSING_COMMIT_OUTPUT_SCHEMA,
    HOUSING_CONTACT_OUTPUT_SCHEMA,
    HOUSING_LANDLORD_PROMPT,
    HOUSING_RESPOND_OUTPUT_SCHEMA,
    HOUSING_TENANT_PROMPT,
    HousingScriptedLandlordProvider,
    HousingScriptedTenantProvider,
    OpenRouterRoutePin,
    build_housing_smoke,
    finalize_housing_execution,
    finalize_housing_failure,
    replay_housing_receipt,
)
from .housing_qc import audit_bid_world
from .paired_analysis import analyze_paired_results
from .quality import QCCoverage, QCEvidenceRef
from .receipts import verify_evaluation_receipt
from .resolver import canonical_json_bytes


DEEPSEEK_MODEL = "deepseek/deepseek-v4-flash-0731"
DEEPSEEK_REVISION = "deepseek/deepseek-v4-flash-20260731"
CONTRACT_SCHEMA_VERSION = "aeread.housing_population_campaign/0.1"
FAMILY_VERSION = "1.0.0"
STAGES = CAMPAIGN_GATE_SEQUENCE[:5]


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sealed(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = {key: item for key, item in value.items() if key != "artifact_sha256"}
    return {**payload, "artifact_sha256": _sha256(payload)}


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    payload = canonical_json_bytes(value) + b"\n"
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _read_sealed(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, Mapping) or canonical_json_bytes(value) != canonical_json_bytes(
        _sealed(value)
    ):
        raise ValueError(f"artifact digest mismatch: {path}")
    return dict(value)


def load_contract(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_bytes())
    if not isinstance(value, dict):
        raise ValueError("campaign contract must be a JSON object")
    required = {
        "schema_version",
        "campaign_id",
        "claim_status",
        "question",
        "primary_estimand",
        "primary_contrast",
        "independent_cluster",
        "environment",
        "controls",
        "models",
        "opponent_panel",
        "conditions",
        "full_trajectory",
        "variance_pilot",
        "missingness",
        "stopping_rule",
    }
    if set(value) != required:
        raise ValueError("campaign contract fields are incomplete or unexpected")
    if value["schema_version"] != CONTRACT_SCHEMA_VERSION:
        raise ValueError("unsupported campaign contract schema")
    if value["campaign_id"] != "housing_population_crossplay_v0":
        raise ValueError("this driver accepts only housing_population_crossplay_v0")
    environment = value["environment"]
    if environment != {
        "family": "housing_v1",
        "tenants": 6,
        "listings": 4,
        "rounds": 4,
        "common_weight": 0.6,
    }:
        raise ValueError("Housing V0 environment controls drifted")
    models = value["models"]
    if set(models) != {"glm_53_flash", "deepseek_v4_flash"}:
        raise ValueError("the frozen subject panel requires exactly two models")
    expected_routes = {
        "glm_53_flash": (GLM_53_FLASH_MODEL, GLM_53_FLASH_REVISION),
        "deepseek_v4_flash": (DEEPSEEK_MODEL, DEEPSEEK_REVISION),
    }
    for model_id, (requested, canonical) in expected_routes.items():
        model = models[model_id]
        if (model.get("requested_model"), model.get("canonical_model")) != (
            requested,
            canonical,
        ):
            raise ValueError(f"model route drifted for {model_id}")
        if (model.get("provider"), model.get("quantization")) != (
            "DeepInfra",
            "fp8",
        ):
            raise ValueError(f"provider route drifted for {model_id}")
    conditions = value["conditions"]
    if not isinstance(conditions, list) or len(conditions) != 6:
        raise ValueError("the frozen cross-play matrix must contain six conditions")
    identities = {
        (item.get("subject"), item.get("opponent"), item.get("evaluation_kind"))
        for item in conditions
        if isinstance(item, Mapping)
    }
    expected_identities = {
        ("glm_53_flash", "scripted", "controlled"),
        ("glm_53_flash", "glm_53_flash", "self_play"),
        ("glm_53_flash", "deepseek_v4_flash", "cross_play"),
        ("deepseek_v4_flash", "scripted", "controlled"),
        ("deepseek_v4_flash", "glm_53_flash", "cross_play"),
        ("deepseek_v4_flash", "deepseek_v4_flash", "self_play"),
    }
    if identities != expected_identities:
        raise ValueError("the subject-by-opponent matrix is incomplete or mislabeled")
    condition_ids = [item.get("condition_id") for item in conditions]
    if any(not isinstance(item, str) or not item for item in condition_ids):
        raise ValueError("condition IDs must be non-empty strings")
    if len(set(condition_ids)) != len(condition_ids):
        raise ValueError("condition IDs must be unique")
    live_weights = value["opponent_panel"].get("live_weights")
    if live_weights != {"glm_53_flash": 0.5, "deepseek_v4_flash": 0.5}:
        raise ValueError("the live opponent weights drifted")
    full_seeds = value["full_trajectory"].get("world_seeds")
    pilot_seeds = value["variance_pilot"].get("world_seeds")
    for label, seeds, expected_count in (
        ("full_trajectory", full_seeds, 1),
        ("variance_pilot", pilot_seeds, 16),
    ):
        if (
            not isinstance(seeds, list)
            or len(seeds) != expected_count
            or any(isinstance(seed, bool) or not isinstance(seed, int) for seed in seeds)
            or len(set(seeds)) != len(seeds)
        ):
            raise ValueError(f"{label} world seeds are invalid")
    if set(full_seeds) & set(pilot_seeds):
        raise ValueError("full-trajectory and variance-pilot worlds must be disjoint")
    if value["variance_pilot"].get("winner_claim_allowed") is not False:
        raise ValueError("variance-pilot outcomes cannot support a winner claim")
    return value


def _route_for(model_id: str) -> OpenRouterRoutePin:
    if model_id == "glm_53_flash":
        return DEEPINFRA_GLM_53_FLASH_ROUTE
    if model_id == "deepseek_v4_flash":
        return DEEPINFRA_HOUSING_ROUTE
    raise ValueError(f"unknown model ID: {model_id}")


def _build_setup(
    contract: Mapping[str, Any],
    condition: Mapping[str, Any],
    *,
    world_seeds: Sequence[int],
    replicates: int,
) -> Any:
    models = contract["models"]
    controls = contract["controls"]
    environment = contract["environment"]
    subject_id = condition["subject"]
    opponent_id = condition["opponent"]
    subject = models[subject_id]
    model_opponent = opponent_id != "scripted"
    opponent = models[opponent_id] if model_opponent else None
    return build_housing_smoke(
        tenant_provider="openrouter",
        tenant_model=subject["requested_model"],
        tenant_revision=subject["canonical_model"],
        landlord_provider=("openrouter" if model_opponent else "housing_scripted_landlord"),
        landlord_model=(
            opponent["requested_model"]
            if opponent is not None
            else "housing_scripted_landlord_v1"
        ),
        landlord_revision=(
            opponent["canonical_model"] if opponent is not None else "1.0.0"
        ),
        world_seeds=tuple(world_seeds),
        replicates=replicates,
        reasoning_condition_id="population_crossplay_low_v0",
        reasoning_effort=controls["reasoning_effort"],
        inference_seed_base=controls["tenant_inference_seed_base"],
        num_tenants=environment["tenants"],
        num_listings=environment["listings"],
        rounds=environment["rounds"],
        openrouter_route=_route_for(subject_id),
        tenant_profile_id_override=subject["tenant_profile_id"],
        landlord_profile_id_override=(
            opponent["landlord_profile_id"] if opponent is not None else None
        ),
        landlord_inference_seed_base=(
            controls["landlord_inference_seed_base"] if model_opponent else None
        ),
        landlord_openrouter_route=(
            _route_for(opponent_id) if model_opponent else None
        ),
        evaluation_kind=condition["evaluation_kind"],
    )


def build_condition_setups(
    contract: Mapping[str, Any],
    *,
    world_seeds: Sequence[int],
    replicates: int,
) -> dict[str, Any]:
    return {
        condition["condition_id"]: _build_setup(
            contract,
            condition,
            world_seeds=world_seeds,
            replicates=replicates,
        )
        for condition in contract["conditions"]
    }


def audit_world_panel(contract: Mapping[str, Any]) -> dict[str, Any]:
    environment = contract["environment"]
    seeds = [
        *contract["full_trajectory"]["world_seeds"],
        *contract["variance_pilot"]["world_seeds"],
    ]
    rows: list[dict[str, Any]] = []
    digests: set[str] = set()
    for seed in seeds:
        facts = audit_bid_world(
            tenants=environment["tenants"],
            listings=environment["listings"],
            rounds=environment["rounds"],
            common_weight=environment["common_weight"],
            world_seed=seed,
        )
        if facts["world_sha256"] in digests:
            raise ValueError(f"duplicate world content for seed {seed}")
        digests.add(facts["world_sha256"])
        rows.append(
            {
                key: facts[key]
                for key in (
                    "world_seed",
                    "world_sha256",
                    "oracle_total",
                    "no_op_total",
                    "random_total",
                    "naive_total",
                    "adaptive_total",
                    "oracle_informed_total",
                    "oracle_minus_naive",
                    "adaptive_minus_naive",
                    "positive_surplus_edges",
                    "market_tightness",
                )
            }
        )
    zero_world = hz.BidWorld(
        listings=[
            hz.Listing(
                listing_id=0,
                rent_asked=1,
                beds=1,
                baths=1,
                minutes_to_campus=10,
                crime_index=1.0,
                minutes_to_groceries=5,
            )
        ],
        values=[[0.0]],
        costs=[1.0],
        ask=[1.0],
    )
    if hz.assignment_oracle(zero_world.surplus).total != 0.0:
        raise ValueError("zero-upper-bound quarantine golden failed")
    if not all(row["oracle_minus_naive"] > 0.0 for row in rows):
        raise ValueError("naive baseline leaves no beatable gap on part of the panel")
    return _sealed(
        {
            "schema_version": "aeread.housing_qc_report/0.1",
            "campaign_id": contract["campaign_id"],
            "status": "passed",
            "world_count": len(rows),
            "duplicate_world_count": 0,
            "nonfinite_world_count": 0,
            "zero_upper_bound_golden": "quarantined_without_normalized_score",
            "beatability_rule": "oracle_informed_total_exceeds_naive_total_on_every_admitted_world",
            "beatability_passed": True,
            "worlds": rows,
        }
    )


def _condition_by_id(contract: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {item["condition_id"]: item for item in contract["conditions"]}


def design_contract_artifact(contract: Mapping[str, Any]) -> dict[str, Any]:
    seeds = contract["full_trajectory"]["world_seeds"]
    setups = build_condition_setups(contract, world_seeds=seeds, replicates=1)
    conditions = _condition_by_id(contract)
    case_panels = {
        tuple(case.content_sha256 for case in setup.plan.cases)
        for setup in setups.values()
    }
    if len(case_panels) != 1:
        raise ValueError("condition plans do not resolve to the same case panel")
    plan_rows: list[dict[str, Any]] = []
    for condition_id, setup in setups.items():
        condition = conditions[condition_id]
        block = setup.plan.evaluation_blocks[0]
        if block.kind != condition["evaluation_kind"]:
            raise ValueError(f"evaluation kind drift for {condition_id}")
        expected_subject_seats = 10 if block.kind == "self_play" else 6
        if len(block.subject_seats) != expected_subject_seats:
            raise ValueError(f"subject-seat attribution drift for {condition_id}")
        if block.kind == "controlled" and len(block.controlled_profiles) != 4:
            raise ValueError(f"scripted control assignment drift for {condition_id}")
        if block.kind != "controlled" and block.controlled_profiles:
            raise ValueError(f"cross-play block has controlled profiles: {condition_id}")
        plan_rows.append(
            {
                "condition_id": condition_id,
                "run_plan_id": setup.plan.run_plan_id,
                "plan_sha256": setup.plan.plan_sha256,
                "evaluation_kind": block.kind,
                "case_sha256s": [case.content_sha256 for case in setup.plan.cases],
                "profile_sha256s": {
                    profile.profile_id: _sha256(profile)
                    for profile in setup.plan.agent_profiles
                },
            }
        )
    return _sealed(
        {
            "schema_version": "aeread.housing_campaign_design/0.1",
            "campaign_id": contract["campaign_id"],
            "contract_sha256": _sha256(contract),
            "status": "passed",
            "claim_status": contract["claim_status"],
            "primary_estimand": contract["primary_estimand"],
            "primary_contrast": contract["primary_contrast"],
            "independent_cluster": contract["independent_cluster"],
            "condition_count": len(plan_rows),
            "complete_matrix": True,
            "paired_worlds": True,
            "scripted_anchor_ranked": False,
            "self_play_in_live_opponent_average": False,
            "plans": plan_rows,
        }
    )


def _profile_request(
    *,
    model_id: str,
    role: str,
    action_schema: str,
    observation: Mapping[str, Any],
    probe_index: int,
) -> ProviderRequest:
    route = _route_for(model_id)
    model = GLM_53_FLASH_MODEL if model_id == "glm_53_flash" else DEEPSEEK_MODEL
    prompt = HOUSING_TENANT_PROMPT if role == "tenant" else HOUSING_LANDLORD_PROMPT
    output_schema = {
        "housing_contact_v1": HOUSING_CONTACT_OUTPUT_SCHEMA,
        "housing_commit_v1": HOUSING_COMMIT_OUTPUT_SCHEMA,
        "housing_respond_v1": HOUSING_RESPOND_OUTPUT_SCHEMA,
    }[action_schema]
    phase_id = {
        "housing_contact_v1": "contact",
        "housing_commit_v1": "commit",
        "housing_respond_v1": "respond",
    }[action_schema]
    seat_id = "tenant_0" if role == "tenant" else "landlord_0"
    input_text = canonical_json_bytes(
        {
            "phase_id": phase_id,
            "seat_id": seat_id,
            "role": role,
            "observation_schema": f"housing_{role}_{phase_id}_observation_v1",
            "action_schema": action_schema,
            "observation": observation,
        }
    ).decode("utf-8")
    return ProviderRequest(
        provider_call_id=f"admission_{model_id}_{role}_{phase_id}_{probe_index}",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        model=model,
        revision=route.canonical_model,
        instructions=prompt,
        input_text=input_text,
        temperature=0.0,
        top_p=1.0,
        max_output_tokens=4096,
        reasoning_effort="low",
        timeout_seconds=120.0,
        request_sha256="",
        max_cost_usd=0.01,
        output_schema=output_schema,
        provider_metadata=route.provider_metadata(),
        seed=103_001 + probe_index,
    ).with_computed_hash()


def _admission_observations(seed: int) -> dict[str, Mapping[str, Any]]:
    world = hz.make_bid_world(6, 4, seed, 0.6)
    market = hz.HousingMarket(world, rounds=4)
    contact = market.tenant_observation(0)
    contact_result = market.submit_offers({0: (0, world.ask[0])})
    respond = market.landlord_observation(0)
    response_result = market.submit_responses(
        hz.scripted_landlord_responses(market, contact_result.inbox)
    )
    commit = market.tenant_observation(0)
    if 0 not in response_result.holds:
        raise ValueError("admission fixture did not create the expected tenant hold")
    return {
        "housing_contact_v1": contact,
        "housing_respond_v1": respond,
        "housing_commit_v1": commit,
    }


def _validate_admission_action(
    action_schema: str,
    output_text: str,
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    value = json.loads(output_text)
    if not isinstance(value, dict):
        raise ValueError("admission output is not an object")
    if action_schema == "housing_contact_v1":
        if set(value) != {"decision", "listing_id", "rent"}:
            raise ValueError("contact action fields drifted")
        if value["decision"] == "pass":
            valid = value["listing_id"] is None and value["rent"] is None
        else:
            open_ids = {
                row["listing_id"]
                for row in observation["board"]
                if row["status"] == "OPEN"
            }
            valid = (
                value["decision"] == "offer"
                and value["listing_id"] in open_ids
                and isinstance(value["rent"], (int, float))
                and not isinstance(value["rent"], bool)
                and math.isfinite(float(value["rent"]))
                and float(value["rent"]) >= 0.0
            )
    elif action_schema == "housing_respond_v1":
        if set(value) != {"decision", "offer_id", "counter_rent"}:
            raise ValueError("respond action fields drifted")
        offer_ids = {offer.offer_id for offer in observation["inbox"]}
        if value["decision"] == "reject_all":
            valid = value["offer_id"] is None and value["counter_rent"] is None
        elif value["decision"] == "accept":
            valid = value["offer_id"] in offer_ids and value["counter_rent"] is None
        else:
            valid = (
                value["decision"] == "counter"
                and value["offer_id"] in offer_ids
                and isinstance(value["counter_rent"], (int, float))
                and not isinstance(value["counter_rent"], bool)
                and math.isfinite(float(value["counter_rent"]))
            )
    elif action_schema == "housing_commit_v1":
        if set(value) != {"decision", "hold_id"}:
            raise ValueError("commit action fields drifted")
        hold = observation["active_hold"]
        if value["decision"] == "pass":
            valid = value["hold_id"] is None
        else:
            valid = (
                value["decision"] in {"sign", "walk"}
                and hold is not None
                and value["hold_id"] == hold.hold_id
            )
    else:  # pragma: no cover - protected by the caller
        raise ValueError(f"unknown admission schema: {action_schema}")
    if not valid:
        raise ValueError(f"semantically invalid {action_schema} admission action")
    return value


async def run_profile_admission(contract: Mapping[str, Any]) -> dict[str, Any]:
    client = OpenRouterChatClient()
    results: list[dict[str, Any]] = []
    for model_id in contract["models"]:
        for probe_index in range(3):
            observations = _admission_observations(73001 + probe_index)
            for role, schemas in (
                ("tenant", ("housing_contact_v1", "housing_commit_v1")),
                ("landlord", ("housing_respond_v1",)),
            ):
                for action_schema in schemas:
                    request = _profile_request(
                        model_id=model_id,
                        role=role,
                        action_schema=action_schema,
                        observation=observations[action_schema],
                        probe_index=probe_index,
                    )
                    started = time.perf_counter()
                    result = await client.complete(request)
                    action = _validate_admission_action(
                        action_schema, result.output_text, observations[action_schema]
                    )
                    if result.cost_usd is None:
                        raise ValueError("admission call omitted provider billing")
                    results.append(
                        {
                            "model_id": model_id,
                            "role": role,
                            "action_schema": action_schema,
                            "probe_index": probe_index,
                            "status": "passed",
                            "request_sha256": request.request_sha256,
                            "response_id": result.response_id,
                            "resolved_model": result.resolved_model,
                            "action_sha256": _sha256(action),
                            "input_tokens": result.input_tokens,
                            "cached_input_tokens": result.cached_input_tokens,
                            "output_tokens": result.output_tokens,
                            "cost_usd": result.cost_usd,
                            "elapsed_seconds": time.perf_counter() - started,
                            "route_verified": True,
                            "sdk_retries": 0,
                        }
                    )
    expected = len(contract["models"]) * 9
    if len(results) != expected:
        raise ValueError("profile admission did not complete every declared probe")
    return _sealed(
        {
            "schema_version": "aeread.housing_profile_admission/0.1",
            "campaign_id": contract["campaign_id"],
            "status": "passed",
            "probe_count": len(results),
            "total_cost_usd": sum(row["cost_usd"] for row in results),
            "hidden_retry_count": 0,
            "results": results,
        }
    )


def _role_metrics(execution: Any, *, tenant_profile_id: str) -> dict[str, Any]:
    tenant_calls = []
    landlord_calls = []
    retries = 0
    for action in execution.action_executions:
        destination = tenant_calls if action.profile_id == tenant_profile_id else landlord_calls
        retries += max(0, len(action.attempts) - 1)
        for attempt in action.attempts:
            destination.extend(attempt.provider_calls)

    def summarize(calls: Sequence[Any]) -> dict[str, Any]:
        return {
            "provider_calls": len(calls),
            "input_tokens": sum(call.input_tokens for call in calls),
            "output_tokens": sum(call.output_tokens for call in calls),
            "cost_usd": sum(call.cost_usd for call in calls),
        }

    return {
        "tenant": summarize(tenant_calls),
        "landlord": summarize(landlord_calls),
        "effective_retry_count": retries,
    }


def _condition_summaries(
    rows: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]
) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for condition in contract["conditions"]:
        condition_id = condition["condition_id"]
        selected = [row for row in rows if row["condition_id"] == condition_id]
        completed = [row for row in selected if row["status"] == "completed"]
        summaries[condition_id] = {
            "subject": condition["subject"],
            "opponent": condition["opponent"],
            "evaluation_kind": condition["evaluation_kind"],
            "planned_trajectories": len(selected),
            "completed_trajectories": len(completed),
            "operational_failures": len(selected) - len(completed),
            "mean_within_case_score": (
                sum(float(row["within_case_score"]) for row in completed)
                / len(completed)
                if completed
                else None
            ),
            "total_cost_usd": sum(float(row.get("cost_usd", 0.0)) for row in selected),
        }
    return summaries


def _live_stage_root(output_root: Path, stage: str, attempt_index: int) -> Path:
    if attempt_index < 1:
        raise ValueError("attempt_index must be positive")
    return (
        output_root / stage
        if attempt_index == 1
        else output_root / stage / f"attempt_{attempt_index}"
    )


def _failure_usage(
    *, evidence_root: Path, run_plan_id: str, cell_id: str
) -> dict[str, int | float]:
    cell_root = evidence_root / run_plan_id / cell_id
    attempts = (
        sorted(path for path in cell_root.iterdir() if path.is_dir())
        if cell_root.is_dir()
        else []
    )
    if len(attempts) != 1:
        return {
            "provider_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
        }
    evidence = EvidenceStore.audit_existing(attempts[0])
    provider_calls = 0
    input_tokens = 0
    output_tokens = 0
    cost_usd = 0.0
    for event in evidence.read_events():
        if event.event_type != "provider_call_succeeded":
            continue
        payload = evidence.read_event_payload(event)
        result = payload.get("provider_result") if isinstance(payload, Mapping) else None
        if not isinstance(result, Mapping):
            continue
        provider_calls += 1
        input_tokens += int(result.get("input_tokens", 0))
        output_tokens += int(result.get("output_tokens", 0))
        cost = result.get("cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            cost_usd += float(cost)
    return {
        "provider_calls": provider_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
    }


def _live_opponent_rows(
    rows: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]
) -> list[dict[str, Any]]:
    weights = contract["opponent_panel"]["live_weights"]
    grouped: dict[tuple[str, int, int], dict[str, Mapping[str, Any]]] = defaultdict(dict)
    conditions = _condition_by_id(contract)
    for row in rows:
        condition = conditions[row["condition_id"]]
        opponent = condition["opponent"]
        if opponent == "scripted":
            continue
        grouped[
            (condition["subject"], row["world_seed"], row["replicate_index"])
        ][opponent] = row
    reduced: list[dict[str, Any]] = []
    for (subject, world_seed, replicate), opponent_rows in sorted(grouped.items()):
        if set(opponent_rows) != set(weights):
            reduced.append(
                {
                    "condition_id": subject,
                    "world_seed": world_seed,
                    "replicate_index": replicate,
                    "status": "operational_failure",
                }
            )
            continue
        if any(row["status"] != "completed" for row in opponent_rows.values()):
            reduced.append(
                {
                    "condition_id": subject,
                    "world_seed": world_seed,
                    "replicate_index": replicate,
                    "status": "operational_failure",
                }
            )
            continue
        reduced.append(
            {
                "condition_id": subject,
                "world_seed": world_seed,
                "replicate_index": replicate,
                "status": "completed",
                "within_case_score": sum(
                    weights[opponent] * float(row["within_case_score"])
                    for opponent, row in opponent_rows.items()
                ),
            }
        )
    return reduced


def _power_from_pilot(
    reduced_rows: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]
) -> dict[str, Any]:
    pilot = contract["variance_pilot"]
    by_world: dict[int, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in reduced_rows:
        if row["status"] == "completed":
            by_world[row["world_seed"]][row["condition_id"]].append(
                float(row["within_case_score"])
            )
    differences: list[float] = []
    for world_seed in sorted(by_world):
        values = by_world[world_seed]
        if set(values) != {"glm_53_flash", "deepseek_v4_flash"}:
            continue
        differences.append(
            sum(values["glm_53_flash"]) / len(values["glm_53_flash"])
            - sum(values["deepseek_v4_flash"]) / len(values["deepseek_v4_flash"])
        )
    if len(differences) < 2:
        raise ValueError("variance pilot has fewer than two complete world clusters")
    mean = sum(differences) / len(differences)
    variance = sum((value - mean) ** 2 for value in differences) / (
        len(differences) - 1
    )
    standard_deviation = math.sqrt(variance)
    z_alpha = stats.norm.ppf(1.0 - pilot["alpha"] / 2.0)
    z_power = stats.norm.ppf(pilot["power"])
    raw_required = math.ceil(
        ((z_alpha + z_power) * standard_deviation / pilot["minimum_meaningful_effect"])
        ** 2
    )
    minimum_applied = max(pilot["minimum_confirmatory_worlds"], raw_required)
    attrition_adjusted = math.ceil(
        minimum_applied / (1.0 - pilot["attrition_fraction"])
    )
    return {
        "complete_world_count": len(differences),
        "mean_exploratory_difference": mean,
        "paired_world_standard_deviation": standard_deviation,
        "raw_power_world_count": raw_required,
        "minimum_applied_world_count": minimum_applied,
        "attrition_adjusted_world_count": attrition_adjusted,
        "maximum_confirmatory_worlds": pilot["maximum_confirmatory_worlds"],
        "within_declared_maximum": (
            attrition_adjusted <= pilot["maximum_confirmatory_worlds"]
        ),
        "winner_claim_allowed": False,
    }


async def run_live_stage(
    contract: Mapping[str, Any],
    *,
    stage: str,
    output_root: Path,
    attempt_index: int = 1,
) -> dict[str, Any]:
    stage_contract = contract[stage]
    world_seeds = stage_contract["world_seeds"]
    replicates = stage_contract["replicates"]
    setups = build_condition_setups(
        contract, world_seeds=world_seeds, replicates=replicates
    )
    conditions = list(contract["conditions"])
    condition_lookup = _condition_by_id(contract)
    rows: list[dict[str, Any]] = []
    client = OpenRouterChatClient()
    stage_root = _live_stage_root(output_root, stage, attempt_index)
    for world_index, world_seed in enumerate(world_seeds):
        rotated = conditions[world_index % len(conditions) :] + conditions[: world_index % len(conditions)]
        for condition in rotated:
            condition_id = condition["condition_id"]
            setup = setups[condition_id]
            cells = sorted(
                (
                    cell
                    for cell in setup.plan.cells
                    if cell.world_seed == world_seed
                ),
                key=lambda cell: cell.replicate_index,
            )
            for cell in cells:
                result_path = (
                    stage_root
                    / condition_id
                    / "results"
                    / f"world_{world_seed}__rep_{cell.replicate_index}.json"
                )
                if result_path.exists():
                    rows.append(_read_sealed(result_path))
                    continue
                cost_so_far = sum(float(row.get("cost_usd", 0.0)) for row in rows)
                if cost_so_far >= stage_contract["cost_ceiling_usd"]:
                    raise RuntimeError(f"{stage} cost ceiling reached before matrix completion")
                evidence_root = stage_root / condition_id / "evidence"
                started = time.perf_counter()
                try:
                    providers: dict[str, Any] = {"openrouter": client}
                    if condition["opponent"] == "scripted":
                        providers["housing_scripted_landlord"] = (
                            HousingScriptedLandlordProvider()
                        )
                    execution = await execute_plan_cell(
                        plan=setup.plan,
                        cell_id=cell.cell_id,
                        registry=setup.registry,
                        evidence_root=evidence_root,
                        prompt_sources=setup.prompt_sources,
                        providers=providers,
                        pricing=setup.pricing,
                        harnesses=setup.harnesses,
                        episode_attempt_ordinal=attempt_index - 1,
                    )
                    receipt = finalize_housing_execution(setup=setup, execution=execution)
                    verify_evaluation_receipt(receipt)
                    replayed = replay_housing_receipt(
                        setup=setup,
                        receipt=receipt,
                        evidence_root=evidence_root,
                    )
                    replay_match = canonical_json_bytes(replayed.scores) == canonical_json_bytes(
                        receipt.scores
                    )
                    if not replay_match:
                        raise ValueError("offline replay score mismatch")
                    outcome = execution.episode_result.outcome
                    row = {
                        "condition_id": condition_id,
                        "subject": condition["subject"],
                        "opponent": condition["opponent"],
                        "evaluation_kind": condition["evaluation_kind"],
                        "world_seed": world_seed,
                        "replicate_index": cell.replicate_index,
                        "status": "completed",
                        "within_case_score": outcome["within_case_score"],
                        "social_welfare": outcome["social_welfare"],
                        "tenant_payoff": sum(outcome["tenant_payoffs"].values()),
                        "landlord_payoff": sum(outcome["landlord_payoffs"].values()),
                        "ir_violation_count": len(outcome["ir_violations"]),
                        "wasted_contacts": outcome["wasted_contacts"],
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
                            execution,
                            tenant_profile_id=contract["models"][condition["subject"]][
                                "tenant_profile_id"
                            ],
                        ),
                    }
                except Exception as error:
                    receipt_sha256 = None
                    try:
                        failure_receipt = finalize_housing_failure(
                            setup=setup,
                            cell_id=cell.cell_id,
                            evidence_root=evidence_root,
                            error=error,
                        )
                        receipt_sha256 = failure_receipt.receipt_sha256
                    except Exception:
                        pass
                    failure_usage = _failure_usage(
                        evidence_root=evidence_root,
                        run_plan_id=setup.plan.run_plan_id,
                        cell_id=cell.cell_id,
                    )
                    row = {
                        "condition_id": condition_id,
                        "subject": condition["subject"],
                        "opponent": condition["opponent"],
                        "evaluation_kind": condition["evaluation_kind"],
                        "world_seed": world_seed,
                        "replicate_index": cell.replicate_index,
                        "status": "operational_failure",
                        "failure_type": type(error).__name__,
                        "failure_condition": getattr(error, "condition", "execution_error"),
                        "failure_status_code": getattr(error, "status_code", None),
                        "receipt_sha256": receipt_sha256,
                        "cost_usd": failure_usage["cost_usd"],
                        "failure_usage": failure_usage,
                        "elapsed_seconds": time.perf_counter() - started,
                    }
                row = _sealed(row)
                _write_json(result_path, row)
                rows.append(row)
    expected = len(world_seeds) * replicates * len(conditions)
    completed = [row for row in rows if row["status"] == "completed"]
    total_cost = sum(float(row.get("cost_usd", 0.0)) for row in rows)
    reduced = _live_opponent_rows(rows, contract)
    paired_analysis = None
    paired_analysis_status = "deferred_no_complete_world_clusters"
    if reduced and any(row["status"] == "completed" for row in reduced):
        try:
            paired_analysis = analyze_paired_results(
                reduced,
                control_condition="deepseek_v4_flash",
                treatment_condition="glm_53_flash",
                expected_replicates=replicates,
                bootstrap_draws=10_000,
                bootstrap_seed=20260901,
            )
            paired_analysis_status = "complete"
        except ValueError as error:
            if "no complete world clusters" not in str(error):
                raise
    power = (
        _power_from_pilot(reduced, contract)
        if stage == "variance_pilot" and paired_analysis_status == "complete"
        else None
    )
    artifact = _sealed(
        {
            "schema_version": "aeread.housing_population_results/0.1",
            "campaign_id": contract["campaign_id"],
            "stage": stage,
            "attempt_index": attempt_index,
            "claim_status": (
                "integration_only"
                if stage == "full_trajectory"
                else "exploratory_variance_pilot"
            ),
            "winner_claim_allowed": False,
            "planned_trajectories": expected,
            "completed_trajectories": len(completed),
            "operational_failures": expected - len(completed),
            "complete_matrix": len(rows) == expected and len(completed) == expected,
            "total_cost_usd": total_cost,
            "cost_ceiling_usd": stage_contract["cost_ceiling_usd"],
            "condition_summaries": _condition_summaries(rows, contract),
            "live_opponent_paired_analysis_status": paired_analysis_status,
            "live_opponent_paired_analysis": paired_analysis,
            "confirmatory_power_design": power,
            "rows": rows,
        }
    )
    _write_json(stage_root / "summary.json", artifact)
    if len(rows) != expected or len(completed) != expected:
        raise RuntimeError(f"{stage} matrix is incomplete")
    if total_cost > stage_contract["cost_ceiling_usd"]:
        raise RuntimeError(f"{stage} exceeded its cost ceiling")
    if stage == "variance_pilot" and power is not None and not power["within_declared_maximum"]:
        raise RuntimeError("powered confirmatory size exceeds the declared maximum")
    return artifact


async def run_provider_free(
    contract: Mapping[str, Any], *, output_root: Path, attempt_index: int = 1
) -> dict[str, Any]:
    stage_root = _live_stage_root(
        output_root, "provider_free_validation", attempt_index
    )
    qc = audit_world_panel(contract)
    qc_path = stage_root / "housing_qc_report.json"
    _write_json(qc_path, qc)
    seed = contract["full_trajectory"]["world_seeds"][0]
    setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
        world_seeds=(seed,),
        replicates=1,
        inference_seed_base=87001,
        num_tenants=6,
        num_listings=4,
        rounds=4,
    )
    evidence_root = stage_root / "evidence"
    cell = setup.plan.cells[0]
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
    replayed = replay_housing_receipt(
        setup=setup, receipt=receipt, evidence_root=evidence_root
    )
    if canonical_json_bytes(replayed.scores) != canonical_json_bytes(receipt.scores):
        raise ValueError("provider-free offline replay mismatch")
    artifact = _sealed(
        {
            "schema_version": "aeread.housing_provider_free/0.2",
            "campaign_id": contract["campaign_id"],
            "status": "passed",
            "qc_report_sha256": qc["artifact_sha256"],
            "covered_world_ids": [
                f"world_{row['world_seed']}" for row in qc["worlds"]
            ],
            "run_plan_id": setup.plan.run_plan_id,
            "receipt_sha256": receipt.receipt_sha256,
            "replay_verified": True,
            "provider_cost_usd": execution.total_cost_usd,
        }
    )
    _write_json(stage_root / "summary.json", artifact)
    return artifact


def _load_history(path: Path) -> tuple[CampaignHistoryRecord, ...]:
    if not path.exists():
        return ()
    value = _read_sealed(path)
    if value.get("schema_version") != "aeread.campaign_gate_history/0.2":
        raise ValueError(
            "legacy campaign history lacks typed QC evidence bindings; "
            "start a new output directory or migrate it explicitly"
        )
    records = value.get("records")
    if not isinstance(records, list):
        raise ValueError("campaign gate history must contain a records array")
    return tuple(campaign_history_record_from_dict(row) for row in records)


def _write_history(path: Path, records: Sequence[CampaignHistoryRecord]) -> None:
    _write_json(
        path,
        _sealed(
            {
                "schema_version": "aeread.campaign_gate_history/0.2",
                "records": [
                    campaign_history_record_to_dict(record) for record in records
                ],
            }
        ),
    )


def _latest_status(
    records: Sequence[CampaignHistoryRecord],
    campaign_id: str,
    gate_id: str,
    *,
    evidence_root: Path,
) -> str | None:
    selected = {
        record.gate_id: record
        for record in campaign_active_gate_records(
            campaign_id, records, evidence_root=evidence_root
        )
    }
    return selected[gate_id].status if gate_id in selected else None


def _expected_gate_coverage(
    contract: Mapping[str, Any], gate_id: str
) -> tuple[str, ...]:
    if gate_id == "design_contract":
        return tuple(item["condition_id"] for item in contract["conditions"])
    if gate_id == "provider_free_validation":
        seeds = {
            *contract["full_trajectory"]["world_seeds"],
            *contract["variance_pilot"]["world_seeds"],
        }
        return (
            *(f"world_{seed}" for seed in sorted(seeds)),
            "provider_free_replay",
        )
    if gate_id == "profile_admission":
        return tuple(
            f"{model_id}.{role}.{schema_id}.probe_{probe_index}"
            for model_id in contract["models"]
            for probe_index in range(3)
            for role, schema_ids in (
                ("tenant", ("housing_contact_v1", "housing_commit_v1")),
                ("landlord", ("housing_respond_v1",)),
            )
            for schema_id in schema_ids
        )
    if gate_id in {"full_trajectory", "variance_pilot"}:
        stage = contract[gate_id]
        return tuple(
            f"{condition['condition_id']}.world_{world_seed}.rep_{replicate_index}"
            for condition in contract["conditions"]
            for world_seed in stage["world_seeds"]
            for replicate_index in range(stage["replicates"])
        )
    return (gate_id,)


def _observed_gate_coverage(
    artifact: Mapping[str, Any] | None, gate_id: str
) -> tuple[str, ...]:
    if artifact is None:
        return ()
    if gate_id == "design_contract":
        return tuple(row["condition_id"] for row in artifact.get("plans", ()))
    if gate_id == "provider_free_validation":
        observed = list(artifact.get("covered_world_ids", ()))
        if artifact.get("replay_verified") is True:
            observed.append("provider_free_replay")
        return tuple(observed)
    if gate_id == "profile_admission":
        return tuple(
            (
                f"{row['model_id']}.{row['role']}.{row['action_schema']}."
                f"probe_{row['probe_index']}"
            )
            for row in artifact.get("results", ())
            if row.get("status") == "passed"
        )
    if gate_id in {"full_trajectory", "variance_pilot"}:
        return tuple(
            (
                f"{row['condition_id']}.world_{row['world_seed']}."
                f"rep_{row['replicate_index']}"
            )
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


def _record_gate(
    *,
    records: Sequence[CampaignHistoryRecord],
    campaign_id: str,
    family_id: str,
    family_version: str,
    profile_id: str,
    gate_id: str,
    status: str,
    evidence_refs: Sequence[QCEvidenceRef],
    evidence_root: Path,
    failure_reasons: Sequence[str] = (),
) -> tuple[CampaignHistoryRecord, ...]:
    decision = campaign_promotion_decision(
        campaign_id, gate_id, records, evidence_root=evidence_root
    )
    if not decision.eligible:
        raise RuntimeError(f"campaign promotion blocked: {decision.blockers}")
    return append_campaign_gate(
        records,
        CampaignGateRecord(
            campaign_id=campaign_id,
            family_id=family_id,
            family_version=family_version,
            profile_id=profile_id,
            gate_id=gate_id,
            attempt_index=decision.next_attempt_index,
            status=status,
            evidence_refs=tuple(evidence_refs),
            failure_reasons=tuple(failure_reasons),
        ),
        evidence_root=evidence_root,
    )


def _invalidate_history(
    *,
    records: Sequence[CampaignHistoryRecord],
    contract: Mapping[str, Any],
    output_root: Path,
    from_gate_id: str,
    changed_controls: Sequence[str],
    reason: str,
) -> tuple[CampaignHistoryRecord, ...]:
    invalidation_index = (
        sum(isinstance(record, CampaignInvalidationRecord) for record in records) + 1
    )
    invalidation_id = f"invalidation_{invalidation_index}"
    path = output_root / "invalidations" / invalidation_id / "summary.json"
    artifact = _sealed(
        {
            "schema_version": "aeread.campaign_invalidation/0.1",
            "campaign_id": contract["campaign_id"],
            "invalidation_index": invalidation_index,
            "from_gate_id": from_gate_id,
            "changed_controls": list(changed_controls),
            "reason": reason,
        }
    )
    _write_json(path, artifact)
    evidence = QCEvidenceRef(
        artifact_type="campaign_invalidation",
        path=str(path.relative_to(output_root)),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        family_id=contract["environment"]["family"],
        family_version=FAMILY_VERSION,
        profile_id=contract["campaign_id"],
        coverage=(
            QCCoverage(
                coverage_id="invalidation",
                required_ids=(invalidation_id,),
                observed_ids=(invalidation_id,),
            ),
        ),
    )
    return append_campaign_invalidation(
        records,
        CampaignInvalidationRecord(
            campaign_id=contract["campaign_id"],
            family_id=contract["environment"]["family"],
            family_version=FAMILY_VERSION,
            profile_id=contract["campaign_id"],
            invalidation_index=invalidation_index,
            from_gate_id=from_gate_id,
            changed_controls=tuple(changed_controls),
            reason=reason,
            evidence_refs=(evidence,),
        ),
        evidence_root=output_root,
    )


async def execute_campaign(
    *,
    contract_path: Path,
    output_root: Path,
    through: str,
    invalidate_from: str | None = None,
    changed_controls: Sequence[str] = (),
    invalidation_reason: str | None = None,
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
        if not changed_controls:
            raise ValueError("changed_controls are required for invalidation")
        if invalidation_reason is None or not invalidation_reason.strip():
            raise ValueError("invalidation_reason is required for invalidation")
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
        raise ValueError(
            "invalidate_from is required when invalidation details are supplied"
        )
    target_index = STAGES.index(through)
    for gate_id in STAGES[: target_index + 1]:
        if _latest_status(
            records,
            contract["campaign_id"],
            gate_id,
            evidence_root=output_root,
        ) == "passed":
            summaries[gate_id] = {"status": "already_passed"}
            continue
        decision = campaign_promotion_decision(
            contract["campaign_id"],
            gate_id,
            records,
            evidence_root=output_root,
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
                artifact = await run_provider_free(
                    contract,
                    output_root=output_root,
                    attempt_index=attempt_index,
                )
                path = attempt_root / "summary.json"
            elif gate_id == "profile_admission":
                artifact = await run_profile_admission(contract)
                path = attempt_root / "summary.json"
                _write_json(path, artifact)
            elif gate_id in {"full_trajectory", "variance_pilot"}:
                artifact = await run_live_stage(
                    contract,
                    stage=gate_id,
                    output_root=output_root,
                    attempt_index=attempt_index,
                )
                path = attempt_root / "summary.json"
            else:  # pragma: no cover - STAGES protects this branch
                raise ValueError(f"unsupported stage: {gate_id}")
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
                        artifact_type=campaign_gate_artifact_type(
                            gate_id, "passed"
                        ),
                        path=path,
                        evidence_root=output_root,
                        artifact=artifact,
                    ),
                ),
            )
            _write_history(history_path, records)
            summaries[gate_id] = {
                "status": "passed",
                "artifact_sha256": artifact["artifact_sha256"],
            }
        except Exception as error:
            failure_path = attempt_root / "failure.json"
            failure = _sealed(
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
                        artifact_type=campaign_gate_artifact_type(
                            gate_id, "failed"
                        ),
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
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--through", choices=STAGES, default="full_trajectory")
    parser.add_argument("--invalidate-from", choices=STAGES)
    parser.add_argument("--changed-control", action="append", default=[])
    parser.add_argument("--invalidation-reason")
    args = parser.parse_args(argv)
    result = asyncio.run(
        execute_campaign(
            contract_path=args.contract,
            output_root=args.output,
            through=args.through,
            invalidate_from=args.invalidate_from,
            changed_controls=args.changed_control,
            invalidation_reason=args.invalidation_reason,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if any(
        value.get("status") == "failed"
        for value in result["gate_summaries"].values()
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "STAGES",
    "audit_world_panel",
    "build_condition_setups",
    "design_contract_artifact",
    "execute_campaign",
    "load_contract",
    "main",
    "run_live_stage",
    "run_profile_admission",
    "run_provider_free",
]
