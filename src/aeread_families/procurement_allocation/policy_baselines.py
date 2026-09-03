"""Deterministic public-observation baselines for procurement allocation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import itertools
import json
import math
import os
import re
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import (
    ProviderRequest,
    ProviderResult,
    execute_plan_cell,
)

from .blinded_invariance import CAMPAIGN_ID as BLINDED_CAMPAIGN_ID
from .case_matrix import BLINDED_CASE_PATHS, CASE_VARIANCE_PATHS, REPOSITORY_ROOT
from .model_campaign import CAMPAIGN_ID as LABELED_CAMPAIGN_ID
from .runner import (
    build_offline_setup,
    finalize_procurement_allocation_execution,
    finalize_procurement_allocation_failure,
    replay_procurement_allocation_receipt,
)


CAMPAIGN_ID = "procurement_allocation_public_policy_baselines_v1"
POLICY_IDS = (
    "defer",
    "displayed_price_greedy",
    "listing_claim_fit",
    "semantic_hint",
)
PANELS = {
    "labeled_original": CASE_VARIANCE_PATHS,
    "opaque_reordered": BLINDED_CASE_PATHS,
}
METRICS = (
    "feasible",
    "completed_kits",
    "contribution_margin_usd",
    "regret_to_upper_bound_usd",
)
DEFAULT_LABELED_RUN_ROOT = (
    REPOSITORY_ROOT
    / "runs"
    / "procurement_allocation"
    / LABELED_CAMPAIGN_ID
    / "qualification_attempt_001"
)
DEFAULT_BLINDED_RUN_ROOT = (
    REPOSITORY_ROOT
    / "runs"
    / "procurement_allocation"
    / BLINDED_CAMPAIGN_ID
    / "qualification_attempt_004"
)


def _write_once_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"refusing to replace different artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _tokens(value: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", value.lower()))


def _variant_overlap(required: str, claimed: str) -> float:
    required_tokens = _tokens(required)
    claimed_tokens = _tokens(claimed)
    union = required_tokens | claimed_tokens
    return len(required_tokens & claimed_tokens) / len(union) if union else 0.0


def _semantic_score(supplier: Mapping[str, Any]) -> int:
    listing = supplier["listing"]
    surface = f"{supplier['supplier_id']} {listing['supplier_name']}".lower()
    helpful = ("assured", "exact", "express", "reliable", "service", "net_terms")
    harmful = ("near_match", "prepay", "risky", "value")
    return sum(marker in surface for marker in helpful) - sum(
        marker in surface for marker in harmful
    )


def _ranked_suppliers(
    observation: Mapping[str, Any], *, component: str, policy_id: str
) -> list[Mapping[str, Any]]:
    required = observation["policy"]["required_variant_by_component"][component]
    candidates = [
        supplier
        for supplier in observation["supplier_listings"]
        if supplier["component"] == component
    ]

    def key(supplier: Mapping[str, Any]) -> tuple[Any, ...]:
        listing = supplier["listing"]
        price = float(listing["displayed_unit_price_usd"])
        lead = int(listing["claimed_lead_time_days"])
        overlap = _variant_overlap(required, str(listing["claimed_variant"]))
        supplier_id = str(supplier["supplier_id"])
        if policy_id == "displayed_price_greedy":
            return (price, lead, -overlap, supplier_id)
        if policy_id == "listing_claim_fit":
            return (-overlap, lead, price, supplier_id)
        if policy_id == "semantic_hint":
            return (-_semantic_score(supplier), -overlap, lead, price, supplier_id)
        raise ValueError(f"unsupported ranking policy: {policy_id}")

    return sorted(candidates, key=key)


def _latest_offer(
    observation: Mapping[str, Any], supplier_id: str
) -> Mapping[str, Any] | None:
    offers = [
        offer
        for offer in observation["formal_offers"].values()
        if offer["supplier_id"] == supplier_id
    ]
    return max(offers, key=lambda offer: int(offer["version"]), default=None)


def _expected_capacity(
    *,
    observation: Mapping[str, Any],
    offer: Mapping[str, Any],
    sample: Mapping[str, Any],
) -> float:
    on_time = (
        observation["elapsed_days"] + int(offer["lead_time_days"])
        <= observation["objective"]["deadline_days"]
    )
    if not on_time:
        return 0.0
    return (
        int(offer["capacity"])
        * float(sample["verified_yield_rate"])
        * float(offer["on_time_probability"])
    )


def _valid_quantity(offer: Mapping[str, Any], needed_raw_units: float) -> int:
    moq = int(offer["moq"])
    capacity = int(offer["capacity"])
    step = int(offer["order_step"])
    desired = max(moq, math.ceil(needed_raw_units - 1e-12))
    if desired >= capacity:
        return capacity
    steps = math.ceil((desired - moq) / step)
    quantity = moq + max(0, steps) * step
    return min(quantity, capacity)


def choose_public_policy_action(
    observation: Mapping[str, Any], *, policy_id: str
) -> dict[str, Any]:
    """Choose from the public observation without case or hidden-state access."""

    if policy_id == "defer":
        return {"action": "defer", "reason": "declared immediate-defer baseline"}
    if policy_id not in POLICY_IDS:
        raise ValueError(f"unknown policy_id: {policy_id}")

    objective = observation["objective"]
    required_variants = observation["policy"]["required_variant_by_component"]
    qualified: dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]] = {}
    for component, units_per_kit in objective["bom"].items():
        target_units = objective["target_kits"] * int(units_per_kit)
        expected_capacity = 0.0
        qualified[component] = []
        for supplier in _ranked_suppliers(
            observation, component=component, policy_id=policy_id
        ):
            supplier_id = str(supplier["supplier_id"])
            offer = _latest_offer(observation, supplier_id)
            actions_left = int(observation["actions_left"])
            if offer is None or int(offer["expires_day"]) < int(
                observation["elapsed_days"]
            ):
                if actions_left <= 2:
                    return {
                        "action": "defer",
                        "reason": "insufficient actions to qualify another supplier",
                    }
                return {
                    "action": "request_quote",
                    "supplier_id": supplier_id,
                    "message": "Issue a formal offer with complete commercial terms.",
                }
            if offer["variant_id"] != required_variants[component]:
                continue
            sample = observation["verified_samples"].get(supplier_id)
            if not isinstance(sample, Mapping) or sample.get("variant_id") != offer.get(
                "variant_id"
            ):
                if actions_left <= 1:
                    return {
                        "action": "defer",
                        "reason": "insufficient actions to verify a supplier sample",
                    }
                return {
                    "action": "request_sample",
                    "supplier_id": supplier_id,
                    "message": "Provide an exact-variant qualification sample.",
                }
            qualified[component].append((offer, sample))
            expected_capacity += _expected_capacity(
                observation=observation, offer=offer, sample=sample
            )
            if expected_capacity + 1e-12 >= target_units:
                break

    expected_units: dict[str, float] = {}
    award_lines: list[dict[str, Any]] = []
    estimated_cash_spend = float(observation["information_cost_usd"])
    for component, units_per_kit in objective["bom"].items():
        target_units = objective["target_kits"] * int(units_per_kit)
        accumulated = 0.0
        for offer, sample in qualified[component]:
            efficiency = (
                float(sample["verified_yield_rate"])
                * float(offer["on_time_probability"])
                if observation["elapsed_days"] + int(offer["lead_time_days"])
                <= objective["deadline_days"]
                else 0.0
            )
            if efficiency <= 0:
                continue
            quantity = _valid_quantity(offer, (target_units - accumulated) / efficiency)
            award_lines.append(
                {"offer_id": str(offer["offer_id"]), "quantity": quantity}
            )
            accumulated += quantity * efficiency
            purchase = quantity * float(offer["unit_price_usd"])
            shipping = quantity * float(offer["shipping_per_unit_usd"])
            estimated_cash_spend += (
                purchase + shipping + (purchase + shipping) * float(offer["duty_rate"])
            )
            if accumulated + 1e-12 >= target_units:
                break
        expected_units[component] = accumulated

    completed_kits = min(
        math.floor(expected_units[component] / int(units_per_kit) + 1e-12)
        for component, units_per_kit in objective["bom"].items()
    )
    if completed_kits < objective["minimum_service_kits"]:
        return {
            "action": "defer",
            "reason": "publicly qualified capacity cannot meet minimum service",
        }
    if estimated_cash_spend > float(objective["cash_budget_usd"]) + 1e-9:
        return {
            "action": "defer",
            "reason": "formal landed spend exceeds the cash budget",
        }
    return {"action": "submit_award", "award_lines": award_lines}


class PublicObservationPolicyProvider:
    """Provider-compatible deterministic policy restricted to request input bytes."""

    def __init__(self, policy_id: str) -> None:
        if policy_id not in POLICY_IDS:
            raise ValueError(f"unknown policy_id: {policy_id}")
        self.policy_id = policy_id
        self.request_sha256s: list[str] = []

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if "private_terms" in request.input_text:
            raise RuntimeError(
                "hidden supplier terms leaked into the public observation"
            )
        envelope = json.loads(request.input_text)
        observation = envelope.get("observation")
        if not isinstance(observation, Mapping):
            raise ValueError("policy request omitted the procurement observation")
        action = choose_public_policy_action(observation, policy_id=self.policy_id)
        output = canonical_json_bytes(action).decode("utf-8")
        self.request_sha256s.append(request.request_sha256)
        return ProviderResult(
            response_id=f"public_policy_{self.policy_id}_{len(self.request_sha256s)}",
            requested_model=request.model,
            resolved_model=f"deterministic/{self.policy_id}/1.0",
            output_text=output,
            finish_reason="stop",
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            raw_response={"deterministic_policy": self.policy_id},
        )


def _public_action_trace(execution: Any) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    for ordinal, logical_action in enumerate(execution.action_executions, start=1):
        response = next(
            (
                attempt.canonical_response
                for attempt in reversed(logical_action.attempts)
                if attempt.canonical_response is not None
            ),
            None,
        )
        payload: Mapping[str, Any] | None = None
        if response is not None and isinstance(response.action, Mapping):
            payload = response.action
        elif response is not None:
            try:
                candidate = json.loads(response.text)
                payload = candidate if isinstance(candidate, Mapping) else None
            except (TypeError, json.JSONDecodeError):
                payload = None
        row: dict[str, Any] = {
            "ordinal": ordinal,
            "status": logical_action.status,
            "action": (
                payload.get("action") if isinstance(payload, Mapping) else "unparseable"
            ),
        }
        if isinstance(payload, Mapping):
            for key in ("supplier_id", "offer_id", "award_lines"):
                if payload.get(key) not in (None, [], {}):
                    row[key] = payload[key]
        trace.append(row)
    return trace


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value)


async def _run_cell(
    *, run_root: Path, panel: str, policy_id: str, case_path: Path
) -> dict[str, Any]:
    setup = build_offline_setup(case_path=case_path)
    cell = setup.plan.cells[0]
    provider = PublicObservationPolicyProvider(policy_id)
    evidence_root = (
        run_root
        / "executions"
        / panel
        / policy_id
        / f"{_safe_name(setup.case.case_id)}_{setup.case.content_sha256[:12]}"
    )
    started = time.perf_counter()
    try:
        execution = await execute_plan_cell(
            plan=setup.plan,
            cell_id=cell.cell_id,
            registry=setup.registry,
            evidence_root=evidence_root,
            prompt_sources=setup.prompt_sources,
            providers={"fake": provider},
            pricing=setup.pricing,
            harnesses=setup.harnesses,
        )
        receipt = finalize_procurement_allocation_execution(
            setup=setup, execution=execution
        )
        replayed = replay_procurement_allocation_receipt(
            setup=setup, receipt=receipt, evidence_root=evidence_root
        )
        if canonical_json_bytes(replayed) != canonical_json_bytes(receipt):
            raise RuntimeError("replayed policy receipt differs from live receipt")
        execution.evidence.audit_reconciliation()
        outcome = json.loads(canonical_json_bytes(execution.episode_result.outcome))
        row: dict[str, Any] = {
            "panel": panel,
            "policy_id": policy_id,
            "case_id": setup.case.case_id,
            "case_slug": setup.case.case_id.rsplit(".", 1)[-1],
            "case_content_sha256": setup.case.content_sha256,
            "world_seed": setup.case.world_seed,
            "status": "completed",
            "decision": outcome["decision"],
            "termination_reason": outcome["termination_reason"],
            "feasible": bool(outcome["feasible"]),
            "completed_kits": int(outcome["completed_kits"]),
            "contribution_margin_usd": float(outcome["contribution_margin_usd"]),
            "upper_bound_usd": float(outcome["upper_bound_usd"]),
            "regret_to_upper_bound_usd": float(outcome["regret_to_upper_bound_usd"]),
            "violations": list(outcome["violations"]),
            "elapsed_environment_days": int(outcome["elapsed_days"]),
            "information_cost_usd": float(outcome["information_cost_usd"]),
            "action_count": len(execution.action_executions),
            "action_trace": _public_action_trace(execution),
            "elapsed_seconds": time.perf_counter() - started,
            "cost_usd": execution.total_cost_usd,
            "request_sha256s": list(provider.request_sha256s),
            "receipt_sha256": receipt.receipt_sha256,
            "receipt_replayed": True,
            "replay_level": receipt.replay_level,
        }
    except Exception as error:
        failure_receipt_sha256 = None
        try:
            failure = finalize_procurement_allocation_failure(
                setup=setup,
                cell_id=cell.cell_id,
                evidence_root=evidence_root,
                error=error,
            )
            failure_receipt_sha256 = failure.receipt_sha256
        except Exception:
            pass
        row = {
            "panel": panel,
            "policy_id": policy_id,
            "case_id": setup.case.case_id,
            "case_slug": setup.case.case_id.rsplit(".", 1)[-1],
            "case_content_sha256": setup.case.content_sha256,
            "world_seed": setup.case.world_seed,
            "status": "operational_failure",
            "failure_type": type(error).__name__,
            "failure_condition": "policy_execution_failure",
            "failure_receipt_sha256": failure_receipt_sha256,
            "elapsed_seconds": time.perf_counter() - started,
        }
    payload = dict(row)
    row["result_sha256"] = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return row


def build_plan() -> dict[str, Any]:
    cases = {
        panel: [
            {
                "case_id": build_offline_setup(case_path=path).case.case_id,
                "content_sha256": build_offline_setup(
                    case_path=path
                ).case.content_sha256,
            }
            for path in paths
        ]
        for panel, paths in PANELS.items()
    }
    plan: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_policy_plan/0.1",
        "campaign_id": CAMPAIGN_ID,
        "panels": cases,
        "policy_ids": list(POLICY_IDS),
        "planned_trajectory_count": sum(len(paths) for paths in PANELS.values())
        * len(POLICY_IDS),
        "independent_case_count": len(CASE_VARIANCE_PATHS),
        "provider": "deterministic public-observation policy",
        "harness": "minimal_chat/1.0 (fixed transport)",
        "cost_usd": 0.0,
        "hidden_state_access": False,
        "pairing": "case slug across labeled_original and opaque_reordered",
        "claim_scope": (
            "deterministic policy floors and surface-sensitivity controls on six "
            "curated procurement worlds; not a population estimate"
        ),
    }
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return plan


def summarize_policy_rows(
    *, plan: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    expected = int(plan["planned_trajectory_count"])
    completed = [row for row in rows if row.get("status") == "completed"]
    indexes = {
        (str(row["panel"]), str(row["policy_id"]), str(row["case_slug"])): row
        for row in completed
    }
    condition_summary: dict[str, Any] = {}
    for panel in PANELS:
        condition_summary[panel] = {}
        for policy_id in POLICY_IDS:
            selected = [
                row
                for row in completed
                if row["panel"] == panel and row["policy_id"] == policy_id
            ]
            condition_summary[panel][policy_id] = {
                "completed_count": len(selected),
                "feasible_count": sum(row["feasible"] is True for row in selected),
                "mean_completed_kits": (
                    statistics.fmean(float(row["completed_kits"]) for row in selected)
                    if selected
                    else None
                ),
                "mean_contribution_margin_usd": (
                    statistics.fmean(
                        float(row["contribution_margin_usd"]) for row in selected
                    )
                    if selected
                    else None
                ),
                "mean_regret_to_upper_bound_usd": (
                    statistics.fmean(
                        float(row["regret_to_upper_bound_usd"]) for row in selected
                    )
                    if selected
                    else None
                ),
                "mean_action_count": (
                    statistics.fmean(float(row["action_count"]) for row in selected)
                    if selected
                    else None
                ),
            }

    paired_invariance: dict[str, Any] = {}
    for policy_id in POLICY_IDS:
        pairs = []
        transitions: Counter[str] = Counter()
        for path in CASE_VARIANCE_PATHS:
            slug = path.stem
            labeled = indexes.get(("labeled_original", policy_id, slug))
            blinded = indexes.get(("opaque_reordered", policy_id, slug))
            if labeled is None or blinded is None:
                continue
            transition = (
                f"{'pass' if labeled['feasible'] else 'fail'}_"
                f"{'pass' if blinded['feasible'] else 'fail'}"
            )
            transitions[transition] += 1
            pairs.append(
                {
                    "case_slug": slug,
                    "feasibility_transition": transition,
                    "action_type_sequence_invariant": [
                        action["action"] for action in labeled["action_trace"]
                    ]
                    == [action["action"] for action in blinded["action_trace"]],
                    "outcome_invariant": all(
                        float(labeled[metric]) == float(blinded[metric])
                        for metric in METRICS
                    ),
                    "completed_kits_delta": float(blinded["completed_kits"])
                    - float(labeled["completed_kits"]),
                    "contribution_margin_delta_usd": float(
                        blinded["contribution_margin_usd"]
                    )
                    - float(labeled["contribution_margin_usd"]),
                    "regret_delta_usd": float(blinded["regret_to_upper_bound_usd"])
                    - float(labeled["regret_to_upper_bound_usd"]),
                    "upper_bound_invariant": float(blinded["upper_bound_usd"])
                    == float(labeled["upper_bound_usd"]),
                }
            )
        paired_invariance[policy_id] = {
            "pair_count": len(pairs),
            "feasibility_transition_counts": dict(sorted(transitions.items())),
            "mean_completed_kits_delta": (
                statistics.fmean(pair["completed_kits_delta"] for pair in pairs)
                if pairs
                else None
            ),
            "mean_contribution_margin_delta_usd": (
                statistics.fmean(
                    pair["contribution_margin_delta_usd"] for pair in pairs
                )
                if pairs
                else None
            ),
            "mean_regret_delta_usd": (
                statistics.fmean(pair["regret_delta_usd"] for pair in pairs)
                if pairs
                else None
            ),
            "all_upper_bounds_invariant": all(
                pair["upper_bound_invariant"] for pair in pairs
            ),
            "pairs": pairs,
        }

    integrity = {
        "all_rows_present": len(rows) == expected,
        "all_rows_completed": len(completed) == expected,
        "all_receipts_replayed": len(completed) == expected
        and all(row.get("receipt_replayed") is True for row in completed),
        "zero_provider_cost": sum(
            float(row.get("cost_usd") or 0.0) for row in completed
        )
        == 0.0,
        "all_policy_pairs_present": all(
            value["pair_count"] == len(CASE_VARIANCE_PATHS)
            for value in paired_invariance.values()
        ),
        "all_upper_bounds_invariant": all(
            value["all_upper_bounds_invariant"] for value in paired_invariance.values()
        ),
    }
    return {
        "planned_trajectory_count": expected,
        "completed_trajectory_count": len(completed),
        "operational_failure_count": len(rows) - len(completed),
        "condition_summary": condition_summary,
        "paired_invariance": paired_invariance,
        "integrity": integrity,
        "readiness": {"policy_baselines_qualified": all(integrity.values())},
    }


def _verified_qualification(
    root: Path, *, campaign_id: str
) -> tuple[dict[str, Any], str]:
    path = root / "summary.json"
    raw_bytes = path.read_bytes()
    value = json.loads(raw_bytes)
    if not isinstance(value, dict):
        raise ValueError(f"qualification summary must be an object: {path}")
    recorded_sha = value.get("artifact_sha256")
    payload = {key: item for key, item in value.items() if key != "artifact_sha256"}
    if recorded_sha != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
        raise ValueError(f"qualification artifact digest mismatch: {path}")
    if value.get("plan", {}).get("campaign_id") != campaign_id:
        raise ValueError(f"qualification campaign identity mismatch: {path}")
    rows = value.get("rows")
    if not isinstance(rows, list):
        raise ValueError("qualification rows must be an array")
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("qualification row must be an object")
        result_sha = row.get("result_sha256")
        result_payload = {
            key: item for key, item in row.items() if key != "result_sha256"
        }
        if (
            result_sha
            != hashlib.sha256(canonical_json_bytes(result_payload)).hexdigest()
        ):
            raise ValueError("qualification row digest mismatch")
    return value, hashlib.sha256(raw_bytes).hexdigest()


def _metric(row: Mapping[str, Any], metric: str) -> float:
    if metric == "feasible":
        return 1.0 if row.get("feasible") is True else 0.0
    return float(row[metric])


def _cluster_interval(values: Sequence[float]) -> list[float]:
    if len(values) != 6:
        raise ValueError("model context requires exactly six case clusters")
    means = sorted(
        statistics.fmean(values[index] for index in sample)
        for sample in itertools.product(range(6), repeat=6)
    )
    return [
        means[int(0.025 * (len(means) - 1))],
        means[int(0.975 * (len(means) - 1))],
    ]


def build_glm_policy_context(
    *,
    policy_artifact: Mapping[str, Any],
    labeled_run_root: Path,
    blinded_run_root: Path,
) -> dict[str, Any]:
    """Compare the primary deterministic floor with qualified GLM world means."""

    policy_sha = policy_artifact.get("artifact_sha256")
    policy_payload = {
        key: value for key, value in policy_artifact.items() if key != "artifact_sha256"
    }
    if policy_sha != hashlib.sha256(canonical_json_bytes(policy_payload)).hexdigest():
        raise ValueError("policy artifact digest mismatch")
    if (
        not policy_artifact.get("summary", {})
        .get("readiness", {})
        .get("policy_baselines_qualified")
    ):
        raise ValueError("policy baselines are not qualified")
    labeled, labeled_file_sha = _verified_qualification(
        labeled_run_root, campaign_id=LABELED_CAMPAIGN_ID
    )
    blinded, blinded_file_sha = _verified_qualification(
        blinded_run_root, campaign_id=BLINDED_CAMPAIGN_ID
    )

    policy_rows = {
        (str(row["panel"]), str(row["case_slug"])): row
        for row in policy_artifact["rows"]
        if row.get("policy_id") == "displayed_price_greedy"
        and row.get("status") == "completed"
    }
    conditions = {
        "labeled_original": labeled,
        "opaque_reordered": blinded,
    }
    comparisons: dict[str, Any] = {}
    integrity = {
        "policy_artifact_digest_verified": True,
        "model_artifact_and_row_digests_verified": True,
        "both_model_campaigns_execution_qualified": all(
            artifact.get("summary", {}).get("readiness", {}).get("execution_qualified")
            is True
            for artifact in conditions.values()
        ),
        "six_policy_rows_per_condition": all(
            sum(panel == condition for panel, _slug in policy_rows) == 6
            for condition in conditions
        ),
    }
    all_model_rows_complete = True
    all_upper_bounds_match = True
    all_three_seeds_present = True
    for condition, artifact in conditions.items():
        grouped: dict[str, list[Mapping[str, Any]]] = {}
        for row in artifact["rows"]:
            slug = str(row["case_id"]).rsplit(".", 1)[-1]
            grouped.setdefault(slug, []).append(row)
            all_model_rows_complete = all_model_rows_complete and (
                row.get("status") == "completed" and row.get("receipt_replayed") is True
            )
        per_case: dict[str, Any] = {}
        for path in CASE_VARIANCE_PATHS:
            slug = path.stem
            model_rows = grouped.get(slug, [])
            policy_row = policy_rows.get((condition, slug))
            if policy_row is None or len(model_rows) != 3:
                all_three_seeds_present = False
                continue
            upper_bounds = {
                float(policy_row["upper_bound_usd"]),
                *(float(row["upper_bound_usd"]) for row in model_rows),
            }
            all_upper_bounds_match = all_upper_bounds_match and len(upper_bounds) == 1
            per_case[slug] = {
                metric: {
                    "policy_value": _metric(policy_row, metric),
                    "glm_seed_mean": statistics.fmean(
                        _metric(row, metric) for row in model_rows
                    ),
                }
                for metric in METRICS
            }
            for values in per_case[slug].values():
                values["policy_minus_glm"] = (
                    values["policy_value"] - values["glm_seed_mean"]
                )
        aggregate: dict[str, Any] = {}
        for metric in METRICS:
            deltas = [
                per_case[slug][metric]["policy_minus_glm"] for slug in sorted(per_case)
            ]
            aggregate[metric] = {
                "case_cluster_mean_policy_minus_glm": (
                    statistics.fmean(deltas) if deltas else None
                ),
                "case_cluster_bootstrap_95_interval": (
                    _cluster_interval(deltas) if len(deltas) == 6 else None
                ),
            }
        comparisons[condition] = {
            "primary_policy_id": "displayed_price_greedy",
            "model_completed_trajectory_count": artifact["summary"].get(
                "completed_trajectory_count"
            ),
            "model_feasible_count": artifact["summary"].get("feasible_count"),
            "per_case": per_case,
            "aggregate": aggregate,
        }

    integrity["all_model_rows_completed_and_replayed"] = all_model_rows_complete
    integrity["three_model_seeds_per_case"] = all_three_seeds_present
    integrity["all_upper_bounds_match"] = all_upper_bounds_match
    context: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_policy_model_context/0.1",
        "campaign_id": CAMPAIGN_ID,
        "primary_policy_id": "displayed_price_greedy",
        "comparisons": comparisons,
        "integrity": integrity,
        "readiness": {"model_context_qualified": all(integrity.values())},
        "source": {
            "policy_artifact_sha256": policy_sha,
            "labeled_summary_file_sha256": labeled_file_sha,
            "labeled_artifact_sha256": labeled.get("artifact_sha256"),
            "labeled_plan_sha256": labeled.get("plan", {}).get("plan_sha256"),
            "blinded_summary_file_sha256": blinded_file_sha,
            "blinded_artifact_sha256": blinded.get("artifact_sha256"),
            "blinded_plan_sha256": blinded.get("plan", {}).get("plan_sha256"),
            "implementation_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
        },
        "claim_scope": (
            "paired deterministic-policy minus GLM comparison over six curated "
            "procurement worlds after averaging three inference seeds within each "
            "world; intervals describe this panel, not a population"
        ),
    }
    context["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(context)
    ).hexdigest()
    return context


async def run_policy_baselines(*, run_root: Path) -> dict[str, Any]:
    resolved = run_root.resolve()
    if "runs" not in resolved.parts or {"evidence", "output", "outputs"}.intersection(
        resolved.parts
    ):
        raise ValueError("run_root must be under runs/ and outside publication paths")
    if run_root.exists():
        raise FileExistsError("policy campaign output already exists")
    plan = build_plan()
    _write_once_json(run_root / "policy_plan.json", plan)
    rows = []
    for panel, paths in PANELS.items():
        for policy_id in POLICY_IDS:
            for path in paths:
                rows.append(
                    await _run_cell(
                        run_root=run_root,
                        panel=panel,
                        policy_id=policy_id,
                        case_path=path,
                    )
                )
    rows.sort(key=lambda row: (row["panel"], row["policy_id"], row["case_slug"]))
    artifact: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_policy_baselines/0.1",
        "plan": plan,
        "summary": summarize_policy_rows(plan=plan, rows=rows),
        "rows": rows,
        "measurement_boundary": {
            "policy_input": "provider request input_text public observation only",
            "hidden_supplier_terms": "not provided to policy",
            "environment_and_objective": "AERead authoritative",
            "receipt_replay": "required for every completed trajectory",
            "provider_cost": "zero; deterministic local policy",
        },
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(artifact)
    ).hexdigest()
    _write_once_json(run_root / "summary.json", artifact)
    return artifact


def publish_policy_baselines(
    *,
    run_root: Path,
    publication_root: Path,
    model_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if publication_root.resolve().parent.name != "evidence":
        raise ValueError("publication_root must be one direct evidence/ bundle")
    raw_bytes = (run_root / "summary.json").read_bytes()
    raw = json.loads(raw_bytes)
    recorded_sha = raw.get("artifact_sha256")
    payload = {key: value for key, value in raw.items() if key != "artifact_sha256"}
    if recorded_sha != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
        raise ValueError("policy summary digest mismatch")
    for row in raw.get("rows", []):
        result_sha = row.get("result_sha256")
        result_payload = {
            key: value for key, value in row.items() if key != "result_sha256"
        }
        if (
            result_sha
            != hashlib.sha256(canonical_json_bytes(result_payload)).hexdigest()
        ):
            raise ValueError("policy row digest mismatch")
    review: dict[str, Any] = {
        **raw,
        "source": {
            "raw_summary_path": (
                "runs/procurement_allocation/"
                f"{CAMPAIGN_ID}/{run_root.name}/summary.json"
            ),
            "raw_summary_file_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "raw_artifact_sha256": recorded_sha,
            "implementation_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
        },
        "privacy_boundary": {
            "included": "public policy actions, outcomes, and receipt/result digests",
            "excluded": "full prompts, observations, event logs, raw provider fixtures, and hidden supplier terms",
        },
    }
    review.pop("artifact_sha256", None)
    review["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(review)).hexdigest()
    report_path = publication_root / "reports" / "results.json"
    _write_once_json(report_path, review)
    report_sha = hashlib.sha256(report_path.read_bytes()).hexdigest()
    artifacts = {"reports/results.json": report_sha}
    if model_context is not None:
        context_path = publication_root / "reports" / "glm_context.json"
        _write_once_json(context_path, model_context)
        artifacts["reports/glm_context.json"] = hashlib.sha256(
            context_path.read_bytes()
        ).hexdigest()
    fact: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_policy_manifest/0.1",
        "campaign_id": CAMPAIGN_ID,
        "artifacts": {
            name: {"path": name, "sha256": sha256} for name, sha256 in artifacts.items()
        },
        "source_bindings": review["source"],
        "publication_scope": "sanitized deterministic policy evidence",
    }
    fact["manifest_sha256"] = hashlib.sha256(canonical_json_bytes(fact)).hexdigest()
    fact_path = publication_root / "tables" / "fact_manifest.json"
    _write_once_json(fact_path, fact)
    manifest: dict[str, Any] = {
        "schema_version": "aeread.publication_manifest/0.1",
        "publication_id": CAMPAIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "artifacts": {
            **artifacts,
            "tables/fact_manifest.json": hashlib.sha256(
                fact_path.read_bytes()
            ).hexdigest(),
        },
        "source_bindings": review["source"],
        "privacy_boundary": review["privacy_boundary"],
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes(manifest)
    ).hexdigest()
    _write_once_json(publication_root / "publication_manifest.json", manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument(
        "--glm-labeled-run-root", type=Path, default=DEFAULT_LABELED_RUN_ROOT
    )
    parser.add_argument(
        "--glm-blinded-run-root", type=Path, default=DEFAULT_BLINDED_RUN_ROOT
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--publish-only", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.publish_only:
        if arguments.execute:
            parser.error("--publish-only cannot be combined with --execute")
        if arguments.publication_root is None:
            parser.error("--publish-only requires --publication-root")
        artifact = json.loads((arguments.run_root / "summary.json").read_text())
        model_context = build_glm_policy_context(
            policy_artifact=artifact,
            labeled_run_root=arguments.glm_labeled_run_root,
            blinded_run_root=arguments.glm_blinded_run_root,
        )
        _write_once_json(arguments.run_root / "glm_context.json", model_context)
        manifest = publish_policy_baselines(
            run_root=arguments.run_root,
            publication_root=arguments.publication_root,
            model_context=model_context,
        )
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    if not arguments.execute:
        print(json.dumps(build_plan(), indent=2, sort_keys=True))
        return 0
    artifact = asyncio.run(run_policy_baselines(run_root=arguments.run_root))
    model_context = build_glm_policy_context(
        policy_artifact=artifact,
        labeled_run_root=arguments.glm_labeled_run_root,
        blinded_run_root=arguments.glm_blinded_run_root,
    )
    _write_once_json(arguments.run_root / "glm_context.json", model_context)
    if (
        arguments.publication_root is not None
        and artifact["summary"]["readiness"]["policy_baselines_qualified"]
        and model_context["readiness"]["model_context_qualified"]
    ):
        publish_policy_baselines(
            run_root=arguments.run_root,
            publication_root=arguments.publication_root,
            model_context=model_context,
        )
    print(json.dumps(artifact["summary"], indent=2, sort_keys=True))
    return 0 if artifact["summary"]["readiness"]["policy_baselines_qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CAMPAIGN_ID",
    "PANELS",
    "POLICY_IDS",
    "PublicObservationPolicyProvider",
    "build_glm_policy_context",
    "build_plan",
    "choose_public_policy_action",
    "publish_policy_baselines",
    "run_policy_baselines",
    "summarize_policy_rows",
]
