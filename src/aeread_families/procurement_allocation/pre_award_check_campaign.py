"""Frozen pre-award-check treatment: a verifier-visible dry run before any award.

Two prompt treatments (worksheet V1 and V2) transferred the payment-terms lever but
did not clear the preregistered rule; their residual losses were quantity errors
after a counter changed MOQ, four-supplier splits with one unsampled line, and
supplier selection under opaque labels. This campaign changes the decision interface
instead of the wording: the environment now exposes ``check_award``, a dry run of
``submit_award`` on the current formal offers and verified samples that returns the
exact violations, kits, and margin the award would produce, at the cost of one action
and nothing else. The prompt is the frozen worksheet V2 procedure plus one step that
requires a clean check before any award.

The paired control remains the sealed confirmatory V2 V4 arm. The control rows ran
on an environment without ``check_award``; because the control never emitted that
action, the difference is inert for those rows, but the treatment effect bundles the
new action with the instruction to use it. Adaptive development evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import OpenRouterChatClient
from aeread_families.procurement_grounding.bakeoff import preflight_candidate

from .confirmatory_campaign import (
    CAMPAIGN_ID as CONFIRMATORY_CAMPAIGN_ID,
    CONFIRMATORY_BATCH_SIZE,
    CONFIRMATORY_MAX_PARALLEL_CELLS,
    CONFIRMATORY_RETRY_CONDITIONS,
    FROZEN_V4_PROMPT_SHA256,
    INFERENCE_SEEDS,
    MAX_ACTION_ATTEMPTS,
    MAX_CANARY_COST_USD,
    MAX_TRAJECTORY_COST_USD,
    METRICS,
    PUBLISHABLE_ROW_FIELDS,
    RETRY_AFTER_MAX_SECONDS,
    RETRY_BACKOFF,
    _case_record,
    _failure_fields,
    _metric,
    _replace_json,
    _representative_request,
    _row_index,
    _sha256_file,
    _verified_summary,
    _write_once_json,
    _write_once_text,
)
from .confirmatory_case_matrix import CASE_SLUGS, LABELED_PATHS, OPAQUE_PATHS
from .model_campaign import planned_model_qualification, run_model_qualification
from .regret_decomposition import (
    REGRET_TERMS,
    case_path_for_id,
    decompose_feasible_award,
    oracle_evaluation,
    replay_action_trace,
    verified_bundle_report,
)
from .strategy_scaffold import (
    GLM_PARASAIL_CANDIDATE,
    PROMPT_ID as V4_PROMPT_ID,
    STRATEGY_PROMPT,
    TREATMENT_ID as V4_TREATMENT_ID,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN_ID = "procurement_allocation_glm53_flash_parasail_pre_award_check_v1"
V1_CAMPAIGN_ID = "procurement_allocation_glm53_flash_parasail_negotiation_worksheet_v2"
V1_EVIDENCE_MANIFEST_PATH = (
    REPOSITORY_ROOT / "evidence" / V1_CAMPAIGN_ID / "publication_manifest.json"
)
V1_EVIDENCE_MANIFEST_FILE_SHA256 = "c2cc3de852253775be2dbc6cf6a4619fc9100c93474217da944da91db24af639"
PROMPT_ID = "procurement_allocation_pre_award_check_v1"
TREATMENT_ID = "worksheet_v2_plus_verifier_visible_pre_award_check_v1"
PARENT_EVIDENCE_ROOT = (
    REPOSITORY_ROOT / "evidence" / CONFIRMATORY_CAMPAIGN_ID
)
PARENT_MANIFEST_PATH = PARENT_EVIDENCE_ROOT / "publication_manifest.json"
PARENT_MANIFEST_FILE_SHA256 = (
    "ec07cef61aa1a2f16b80e3fcddc0f63a20ea3a47c9fbd4fb83ccf625680a0146"
)
PARENT_CONTROL_REPORTS = {
    "labeled": {
        "path": PARENT_EVIDENCE_ROOT / "reports" / "labeled_treatment.json",
        "file_sha256": "6bc2789aa8ee44e4cb5534746ad9dfd11f51734805e6490f62a1ab9dc1299a49",
        "artifact_sha256": (
            "3067a5a528c8c5a3c7cb84d76a64605926a9c110c6985a0f196e6706460bf2c1"
        ),
        "campaign_id": f"{CONFIRMATORY_CAMPAIGN_ID}.labeled_treatment",
    },
    "opaque": {
        "path": PARENT_EVIDENCE_ROOT / "reports" / "opaque_treatment.json",
        "file_sha256": "03af779e19453c25ea5670eb1f5e56cbaa73ead5ad5b2004ed553f6fc8f4e38e",
        "artifact_sha256": (
            "4f40b4cc781e9464fd17e438fb18ee7d37e106f6487fede221e9bdab8bce4f9a"
        ),
        "campaign_id": f"{CONFIRMATORY_CAMPAIGN_ID}.opaque_treatment",
    },
}
DECOMPOSITION_MANIFEST_PATH = (
    REPOSITORY_ROOT
    / "evidence"
    / "procurement_allocation_glm_regret_decomposition_v1"
    / "publication_manifest.json"
)
BOOTSTRAP_SEED = 20260906
BOOTSTRAP_RESAMPLES = 50_000

WORKSHEET_BLOCK = """
Working-capital negotiation worksheet. Apply it every time a formal offer arrives
or a counter is answered, before any further counter or award. It replaces the
counter condition in procedure step 5.
A. Sample first. Request the exact-variant sample from a supplier as soon as its
   formal offer survives the hard checks in step 2. Never send a counter_offer to a
   supplier whose sample is not yet verified, and never include an award line for a
   supplier without a verified sample. An award that skips a sample is worth less
   than deferring.
B. For each current formal offer with a verified sample compute its working-capital
   cost: quantity x unit_price_usd x annual_financing_rate
   x max(0, working_capital_horizon_days - payment_terms_days) / 365,
   using the financing rate and horizon stated in the objective.
C. For that offer estimate the saving from improving one term at a time: longer
   payment_terms_days (recompute B), lower unit_price_usd, lower moq, longer
   refund_window_days, or supplier-paid return freight. Rank the terms by saving.
D. Reserve one action for submit_award. If the largest saving exceeds the counter
   cost and, after that reserve, at least one action remains, send one counter_offer
   on that offer that proposes only that single term and sets every other proposal
   field to null. For payment terms, first request working_capital_horizon_days; if
   rejected and the reserve still allows it, request two-thirds of that once, then
   stop countering that offer. Keep any unit_price_usd request within two percent of
   the quoted price. Do not counter a term that is already at the value you would
   request, and never repeat a rejected proposal.
E. Award only on each supplier's newest formal offer id. A superseded offer id is
   not an eligible award line.
F. Check before you award. A check_award action takes the exact award_lines you
   intend to submit and returns, without ending the episode, whether that award
   would be feasible, the violations it would raise, and the kits and margin it
   would produce. It costs one action and no money or time. Reserve two actions:
   one check_award and one submit_award. Never submit an award that has not passed
   a check with no violations; if the check reports violations, fix the lines
   (quantity, offer id, missing sample, service minimum, cash budget) and check
   again before submitting.
"""
WORKSHEET_PROMPT = STRATEGY_PROMPT + WORKSHEET_BLOCK
FROZEN_WORKSHEET_PROMPT_SHA256 = (
    "600828117b31f363232085cfcf088bfa20ba0207adeed05e83255c55f5f7a871"
)


def _arm_specs() -> dict[str, dict[str, Any]]:
    return {
        "labeled_worksheet": {
            "surface": "labeled",
            "case_paths": LABELED_PATHS,
            "prompt": WORKSHEET_PROMPT,
            "prompt_id": PROMPT_ID,
            "treatment_id": TREATMENT_ID,
        },
        "opaque_worksheet": {
            "surface": "opaque",
            "case_paths": OPAQUE_PATHS,
            "prompt": WORKSHEET_PROMPT,
            "prompt_id": PROMPT_ID,
            "treatment_id": TREATMENT_ID,
        },
    }


def _assert_frozen_sources() -> None:
    if hashlib.sha256(WORKSHEET_PROMPT.encode()).hexdigest() != FROZEN_WORKSHEET_PROMPT_SHA256:
        raise ValueError("frozen worksheet prompt changed; use a new campaign identity")
    if hashlib.sha256(STRATEGY_PROMPT.encode()).hexdigest() != FROZEN_V4_PROMPT_SHA256:
        raise ValueError("frozen V4 base prompt changed; use a new campaign identity")
    if not WORKSHEET_PROMPT.startswith(STRATEGY_PROMPT):
        raise ValueError("worksheet prompt must extend the frozen V4 prompt verbatim")
    if _sha256_file(V1_EVIDENCE_MANIFEST_PATH) != V1_EVIDENCE_MANIFEST_FILE_SHA256:
        raise ValueError("V1 worksheet evidence manifest changed")
    if _sha256_file(PARENT_MANIFEST_PATH) != PARENT_MANIFEST_FILE_SHA256:
        raise ValueError("parent confirmatory evidence manifest changed")
    for surface, binding in PARENT_CONTROL_REPORTS.items():
        if _sha256_file(binding["path"]) != binding["file_sha256"]:
            raise ValueError(f"parent {surface} control report changed")


def _parent_control(surface: str) -> dict[str, Any]:
    binding = PARENT_CONTROL_REPORTS[surface]
    report, file_sha = verified_bundle_report(binding["path"])
    if file_sha != binding["file_sha256"]:
        raise ValueError(f"parent {surface} control file digest mismatch")
    if report.get("artifact_sha256") != binding["artifact_sha256"]:
        raise ValueError(f"parent {surface} control artifact digest mismatch")
    if report.get("campaign_id") != binding["campaign_id"]:
        raise ValueError(f"parent {surface} control campaign identity mismatch")
    return report


def build_plan() -> dict[str, Any]:
    _assert_frozen_sources()
    specs = _arm_specs()
    arm_plans = {
        name: planned_model_qualification(
            case_paths=spec["case_paths"],
            inference_seeds=INFERENCE_SEEDS,
            max_parallel_cells=CONFIRMATORY_MAX_PARALLEL_CELLS,
            campaign_id=f"{CAMPAIGN_ID}.{name}",
            abort_on_operational_failure=True,
            candidate=GLM_PARASAIL_CANDIDATE,
            prompt=spec["prompt"],
            prompt_id=spec["prompt_id"],
            treatment_id=spec["treatment_id"],
            max_new_trajectories=CONFIRMATORY_BATCH_SIZE,
            max_action_attempts=MAX_ACTION_ATTEMPTS,
            retryable_conditions=CONFIRMATORY_RETRY_CONDITIONS,
            retry_backoff=RETRY_BACKOFF,
            retry_after_max_seconds=RETRY_AFTER_MAX_SECONDS,
        )
        for name, spec in specs.items()
    }
    world_pairs = []
    for slug, left, right in zip(
        CASE_SLUGS,
        (_case_record(path) for path in LABELED_PATHS),
        (_case_record(path) for path in OPAQUE_PATHS),
        strict=True,
    ):
        if (
            left["world_seed"] != right["world_seed"]
            or left["economic_world_sha256"] != right["economic_world_sha256"]
        ):
            raise ValueError(f"surface economics differ for {slug}")
        world_pairs.append(
            {
                "slug": slug,
                "world_seed": left["world_seed"],
                "economic_world_sha256": left["economic_world_sha256"],
                "labeled_case_id": left["case_id"],
                "labeled_case_content_sha256": left["case_content_sha256"],
                "opaque_case_id": right["case_id"],
                "opaque_case_content_sha256": right["case_content_sha256"],
            }
        )
    planned = sum(int(arm["planned_trajectory_count"]) for arm in arm_plans.values())
    conservative = sum(float(arm["conservative_cost_ceiling_usd"]) for arm in arm_plans.values())
    plan: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_pre_award_check_plan/0.1",
        "campaign_id": CAMPAIGN_ID,
        "freeze_status": "adaptive_treatment_frozen_before_live_execution",
        "lineage": {
            "supersedes_campaign_id": V1_CAMPAIGN_ID,
            "v1_manifest_path": str(V1_EVIDENCE_MANIFEST_PATH.relative_to(REPOSITORY_ROOT)),
            "v1_manifest_file_sha256": V1_EVIDENCE_MANIFEST_FILE_SHA256,
            "change": "environment exposes check_award; prompt requires a clean check before any award",
        },
        "selection_basis": {
            "decomposition_publication_manifest": str(
                DECOMPOSITION_MANIFEST_PATH.relative_to(REPOSITORY_ROOT)
            ),
            "decomposition_manifest_file_sha256": _sha256_file(DECOMPOSITION_MANIFEST_PATH),
            "rationale": (
                "working-capital cost excess dominated feasible-award regret and traces "
                "to the payment-terms counter used by the oracle plan"
            ),
        },
        "parent_control": {
            "campaign_id": CONFIRMATORY_CAMPAIGN_ID,
            "manifest_path": str(PARENT_MANIFEST_PATH.relative_to(REPOSITORY_ROOT)),
            "manifest_file_sha256": PARENT_MANIFEST_FILE_SHA256,
            "arms": {
                surface: {
                    "report_path": str(binding["path"].relative_to(REPOSITORY_ROOT)),
                    "file_sha256": binding["file_sha256"],
                    "artifact_sha256": binding["artifact_sha256"],
                    "campaign_id": binding["campaign_id"],
                }
                for surface, binding in PARENT_CONTROL_REPORTS.items()
            },
            "control_prompt_id": V4_PROMPT_ID,
            "control_treatment_id": V4_TREATMENT_ID,
            "control_prompt_sha256": FROZEN_V4_PROMPT_SHA256,
        },
        "candidate_id": GLM_PARASAIL_CANDIDATE.candidate_id,
        "model": GLM_PARASAIL_CANDIDATE.route.model,
        "revision": GLM_PARASAIL_CANDIDATE.route.revision,
        "provider": GLM_PARASAIL_CANDIDATE.route.route_provider,
        "quantization": GLM_PARASAIL_CANDIDATE.route.quantization,
        "prompts": {
            "treatment_prompt_id": PROMPT_ID,
            "treatment_id": TREATMENT_ID,
            "treatment_sha256": FROZEN_WORKSHEET_PROMPT_SHA256,
            "base_prompt_sha256": FROZEN_V4_PROMPT_SHA256,
            "change": "append the sample-first worksheet plus a mandatory pre-award check step to the frozen V4 prompt",
        },
        "world_pairs": world_pairs,
        "independent_world_count": len(world_pairs),
        "inference_seeds": list(INFERENCE_SEEDS),
        "arm_execution_order": list(specs),
        "arms": arm_plans,
        "planned_trajectory_count": planned,
        "max_parallel_cells": CONFIRMATORY_MAX_PARALLEL_CELLS,
        "batch_size": CONFIRMATORY_BATCH_SIZE,
        "abort_on_operational_failure": True,
        "admission_canaries": ["treatment"],
        "admission_canaries_scored": False,
        "conservative_scored_cost_ceiling_usd": conservative,
        "conservative_total_cost_ceiling_usd": conservative + MAX_CANARY_COST_USD,
        "hard_scored_cost_ceiling_usd": planned * MAX_TRAJECTORY_COST_USD,
        "hard_total_cost_ceiling_usd": planned * MAX_TRAJECTORY_COST_USD + MAX_CANARY_COST_USD,
        "analysis": {
            "independent_unit": "economic world",
            "pairing": "worksheet row to sealed V4 row by case id and inference seed",
            "seed_aggregation": "mean three inference seeds within world and surface",
            "primary_estimand": (
                "worksheet_minus_v4 regret_to_upper_bound_usd averaged equally over "
                "labeled and opaque surfaces within each world"
            ),
            "uncertainty": "deterministic percentile cluster bootstrap over worlds",
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "support_rule": {
                "primary_regret_delta_bootstrap_upper_strictly_below_usd": 0.0,
                "overall_feasibility_delta_bootstrap_lower_at_least": -0.05,
            },
            "secondary_outcomes": [
                "working_capital_cost_excess term from the regret decomposition on "
                "feasible awards in each arm",
                "accepted counter count and feasible awards on counter-improved offers",
                "counter attempt count and single-field proposal share",
                "surface-specific feasibility, kits, margin, and regret",
            ],
            "no_early_efficacy_stopping": True,
        },
        "eligibility": (
            "all 72 worksheet rows completed and receipt-replayed; route, revision, "
            "harness, retry policy, cases, seeds, parent digests, and upper bounds match"
        ),
        "claim_scope": (
            "adaptive development treatment on twelve curated synthetic worlds selected "
            "after inspecting the regret decomposition; not a holdout confirmation and "
            "not a population model ranking"
        ),
    }
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return plan


async def run_admission_canary(
    *, path: Path, provider_factory: Callable[[], Any] = OpenRouterChatClient
) -> dict[str, Any]:
    request = await _representative_request(prompt=WORKSHEET_PROMPT, prompt_id=PROMPT_ID)
    if path.exists():
        value = json.loads(path.read_text())
        recorded = value.get("artifact_sha256")
        payload = {key: item for key, item in value.items() if key != "artifact_sha256"}
        if recorded != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
            raise ValueError("admission canary digest mismatch")
        if (
            value.get("campaign_id") != CAMPAIGN_ID
            or value.get("request_sha256") != request.request_sha256
        ):
            raise ValueError("admission canary identity mismatch")
        return value
    record: dict[str, Any] = {
        "schema_version": "aeread.provider_admission_canary/0.1",
        "campaign_id": CAMPAIGN_ID,
        "condition": "treatment",
        "attempted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "request_sha256": request.request_sha256,
        "prompt_id": PROMPT_ID,
        "prompt_sha256": hashlib.sha256(WORKSHEET_PROMPT.encode()).hexdigest(),
        "model": request.model,
        "revision": request.revision,
        "route_provider": request.provider_metadata["route_provider"],
        "max_output_tokens": request.max_output_tokens,
        "max_cost_usd": request.max_cost_usd,
        "scored": False,
    }
    try:
        result = await provider_factory().complete(request)
        action = json.loads(result.output_text)
        if not isinstance(action, Mapping) or not isinstance(action.get("action"), str):
            raise ValueError("canary completion is not a structured action")
        record.update(
            {
                "status": "admitted",
                "resolved_model": result.resolved_model,
                "finish_reason": result.finish_reason,
                "input_tokens": result.input_tokens,
                "cached_input_tokens": result.cached_input_tokens,
                "output_tokens": result.output_tokens,
                "cost_usd": result.cost_usd,
                "structured_action": action["action"],
            }
        )
    except Exception as error:
        record.update({"status": "rejected", "cost_usd": 0.0, **_failure_fields(error)})
    record["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(record)).hexdigest()
    _write_once_json(path, record)
    return record


def _bootstrap_interval(values: Sequence[float], *, label: str) -> list[float]:
    if len(values) != len(CASE_SLUGS):
        raise ValueError("bootstrap requires one value per confirmatory world")
    seed = int.from_bytes(
        hashlib.sha256(f"{BOOTSTRAP_SEED}:{label}".encode()).digest()[:8], "big"
    )
    rng = random.Random(seed)
    means = sorted(
        statistics.fmean(values[rng.randrange(len(values))] for _ in values)
        for _ in range(BOOTSTRAP_RESAMPLES)
    )
    return [means[int(0.025 * (len(means) - 1))], means[int(0.975 * (len(means) - 1))]]


def _aggregate(values: Sequence[float], *, label: str) -> dict[str, Any]:
    return {
        "world_cluster_mean": statistics.fmean(values),
        "world_cluster_bootstrap_95_interval": _bootstrap_interval(values, label=label),
        "world_count": len(values),
    }


def _negotiation_diagnostics(
    rows: Sequence[Mapping[str, Any]], *, repository_root: Path
) -> dict[str, Any]:
    """Replay rows to count counters, accepted counters, and decompose feasible regret."""
    counters = accepted = single_field = negotiated_feasible = 0
    check_count = rows_with_check = awards_after_clean_check = 0
    term_totals: dict[str, float] = {term: 0.0 for term in REGRET_TERMS}
    feasible = 0
    oracles: dict[str, dict[str, Any]] = {}
    for row in rows:
        trace = row["action_trace"]
        checks_in_row = [entry for entry in trace if entry.get("action") == "check_award"]
        check_count += len(checks_in_row)
        rows_with_check += bool(checks_in_row)
        attempts = [entry for entry in trace if entry.get("action") == "counter_offer"]
        counters += len(attempts)
        single_field += sum(
            1
            for entry in attempts
            if isinstance(entry.get("proposal"), Mapping)
            and len({k for k, v in entry["proposal"].items() if v is not None}) == 1
        )
        case_path = case_path_for_id(row["case_id"], repository_root=repository_root)
        family_case = json.loads(case_path.read_text(encoding="utf-8"))["payload"]
        replay = replay_action_trace(family_case, trace)
        outcome = replay["outcome"]
        if (
            outcome["feasible"] != row["feasible"]
            or abs(outcome["regret_to_upper_bound_usd"] - row["regret_to_upper_bound_usd"])
            > 1e-6
        ):
            raise ValueError(f"replay mismatch for {row['case_id']}/{row['inference_seed']}")
        terminal = replay["terminal"]
        accepted += sum(1 for offer in terminal["offers"].values() if offer["version"] > 1)
        if terminal["reason"] == "submitted" and any(
            check["feasible"] and check["award_lines"] == terminal["award_lines"]
            for check in replay["terminal"].get("award_checks", [])
        ):
            awards_after_clean_check += 1
        if row["feasible"] and row["decision"] == "award":
            feasible += 1
            if any(
                terminal["offers"][line["offer_id"]]["version"] > 1
                for line in terminal["award_lines"]
            ):
                negotiated_feasible += 1
            if row["case_id"] not in oracles:
                oracles[row["case_id"]] = oracle_evaluation(family_case)
            decomposed = decompose_feasible_award(
                family_case, replay, oracle=oracles[row["case_id"]]
            )
            for term in REGRET_TERMS:
                term_totals[term] += decomposed["terms"][term]
    return {
        "row_count": len(rows),
        "counter_attempt_count": counters,
        "single_field_counter_count": single_field,
        "accepted_counter_count": accepted,
        "feasible_award_count": feasible,
        "feasible_awards_on_negotiated_offer": negotiated_feasible,
        "check_award_count": check_count,
        "rows_with_check_award": rows_with_check,
        "awards_submitted_after_clean_matching_check": awards_after_clean_check,
        "feasible_term_total_usd": {k: round(v, 8) for k, v in term_totals.items()},
        "feasible_term_mean_usd": {
            k: (round(v / feasible, 8) if feasible else None) for k, v in term_totals.items()
        },
    }


def build_worksheet_comparison(
    *, run_root: Path, repository_root: Path = REPOSITORY_ROOT
) -> dict[str, Any]:
    expected_plan = build_plan()
    recorded_plan = json.loads((run_root / "campaign_plan.json").read_text())
    if canonical_json_bytes(recorded_plan) != canonical_json_bytes(expected_plan):
        raise ValueError("recorded campaign plan differs from frozen worksheet plan")
    specs = _arm_specs()
    integrity: dict[str, bool] = {}
    source: dict[str, Any] = {}
    treatment_index: dict[str, dict[tuple[str, int], Mapping[str, Any]]] = {}
    control_index: dict[str, dict[tuple[str, int], Mapping[str, Any]]] = {}
    treatment_rows: dict[str, list[Mapping[str, Any]]] = {}
    control_rows: dict[str, list[Mapping[str, Any]]] = {}
    expected_keys = {(slug, seed) for slug in CASE_SLUGS for seed in INFERENCE_SEEDS}
    for name, spec in specs.items():
        surface = spec["surface"]
        artifact, file_sha = _verified_summary(
            run_root / "arms" / name, campaign_id=f"{CAMPAIGN_ID}.{name}"
        )
        source[name] = {
            "summary_file_sha256": file_sha,
            "artifact_sha256": artifact["artifact_sha256"],
            "plan_sha256": artifact["plan"]["plan_sha256"],
        }
        treatment_index[surface] = _row_index(artifact["rows"])
        treatment_rows[surface] = list(artifact["rows"])
        integrity[f"{name}_model_plan_matches_frozen"] = (
            canonical_json_bytes(artifact["plan"])
            == canonical_json_bytes(expected_plan["arms"][name])
        )
        integrity[f"{name}_prompt_bound"] = artifact["plan"].get("prompt") == {
            "prompt_id": PROMPT_ID,
            "sha256": FROZEN_WORKSHEET_PROMPT_SHA256,
            "treatment_id": TREATMENT_ID,
        }
        integrity[f"{name}_all_pairs_present"] = set(treatment_index[surface]) == expected_keys
        integrity[f"{name}_execution_qualified"] = (
            artifact.get("summary", {}).get("readiness", {}).get("execution_qualified")
            is True
        )
        integrity[f"{name}_rows_completed_replayed_revision_pinned"] = all(
            row.get("status") == "completed"
            and row.get("receipt_replayed") is True
            and row.get("resolved_models") == [GLM_PARASAIL_CANDIDATE.route.revision]
            for row in artifact["rows"]
        )
        control = _parent_control(surface)
        control_index[surface] = _row_index(control["rows"])
        control_rows[surface] = list(control["rows"])
        source[f"{surface}_control"] = {
            "report_file_sha256": PARENT_CONTROL_REPORTS[surface]["file_sha256"],
            "artifact_sha256": control["artifact_sha256"],
        }
        integrity[f"{surface}_control_all_pairs_present"] = (
            set(control_index[surface]) == expected_keys
        )
        integrity[f"{surface}_control_route_matches"] = all(
            row.get("resolved_models") == [GLM_PARASAIL_CANDIDATE.route.revision]
            for row in control["rows"]
        )
        integrity[f"{surface}_control_prompt_is_frozen_v4"] = control["plan"].get(
            "prompt", {}
        ).get("sha256") == FROZEN_V4_PROMPT_SHA256
        integrity[f"{surface}_case_digests_match_control"] = all(
            treatment_index[surface][key]["case_content_sha256"]
            == control_index[surface][key]["case_content_sha256"]
            for key in expected_keys
        )
        integrity[f"{surface}_upper_bounds_match_control"] = all(
            float(treatment_index[surface][key]["upper_bound_usd"])
            == float(control_index[surface][key]["upper_bound_usd"])
            for key in expected_keys
        )
    integrity["seeds_match_parent"] = all(
        _parent_control(surface)["plan"].get("inference_seeds") == list(INFERENCE_SEEDS)
        for surface in ("labeled", "opaque")
    )

    surface_effects: dict[str, Any] = {}
    per_surface_world_delta: dict[str, dict[str, dict[str, float]]] = {}
    for surface in ("labeled", "opaque"):
        control = control_index[surface]
        treatment = treatment_index[surface]
        metric_worlds: dict[str, dict[str, float]] = {metric: {} for metric in METRICS}
        transitions: Counter[str] = Counter()
        for slug in CASE_SLUGS:
            for seed in INFERENCE_SEEDS:
                left = control[(slug, seed)]
                right = treatment[(slug, seed)]
                transitions[
                    f"{'pass' if left['feasible'] else 'fail'}_"
                    f"{'pass' if right['feasible'] else 'fail'}"
                ] += 1
            for metric in METRICS:
                metric_worlds[metric][slug] = statistics.fmean(
                    _metric(treatment[(slug, seed)], metric)
                    - _metric(control[(slug, seed)], metric)
                    for seed in INFERENCE_SEEDS
                )
        per_surface_world_delta[surface] = metric_worlds
        surface_effects[surface] = {
            "feasibility_transition_counts": dict(sorted(transitions.items())),
            "worksheet_minus_v4": {
                metric: _aggregate(
                    [metric_worlds[metric][slug] for slug in CASE_SLUGS],
                    label=f"{surface}:{metric}",
                )
                for metric in METRICS
            },
            "per_world_worksheet_minus_v4": {
                slug: {metric: metric_worlds[metric][slug] for metric in METRICS}
                for slug in CASE_SLUGS
            },
        }
    overall_worlds = {
        metric: {
            slug: statistics.fmean(
                per_surface_world_delta[surface][metric][slug]
                for surface in ("labeled", "opaque")
            )
            for slug in CASE_SLUGS
        }
        for metric in METRICS
    }
    overall = {
        metric: _aggregate(
            [overall_worlds[metric][slug] for slug in CASE_SLUGS],
            label=f"overall:{metric}",
        )
        for metric in METRICS
    }
    eligible = all(integrity.values())
    negotiation: dict[str, Any] = {}
    if eligible:
        for surface in ("labeled", "opaque"):
            negotiation[surface] = {
                "worksheet": _negotiation_diagnostics(
                    treatment_rows[surface], repository_root=repository_root
                ),
                "v4_control": _negotiation_diagnostics(
                    control_rows[surface], repository_root=repository_root
                ),
            }
    primary_regret = overall["regret_to_upper_bound_usd"]
    feasibility = overall["feasible"]
    checks = {
        "primary_regret_upper_below_zero": (
            primary_regret["world_cluster_bootstrap_95_interval"][1] < 0.0
        ),
        "feasibility_noninferiority_lower_at_least_minus_0_05": (
            feasibility["world_cluster_bootstrap_95_interval"][0] >= -0.05
        ),
    }
    status = (
        "ineligible" if not eligible else "supported" if all(checks.values()) else "not_supported"
    )
    comparison: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_pre_award_check_comparison/0.1",
        "campaign_id": CAMPAIGN_ID,
        "parent_campaign_id": CONFIRMATORY_CAMPAIGN_ID,
        "integrity": integrity,
        "readiness": {"worksheet_treatment_qualified": eligible},
        "support": {
            "status": status,
            "checks": checks,
            "rule_was_frozen_before_execution": True,
        },
        "effects": {
            "overall_worksheet_minus_v4": overall,
            "by_surface": surface_effects,
            "per_world_overall_worksheet_minus_v4": {
                slug: {metric: overall_worlds[metric][slug] for metric in METRICS}
                for slug in CASE_SLUGS
            },
        },
        "negotiation_diagnostics": negotiation,
        "bootstrap": {
            "independent_unit": "economic world",
            "world_count": len(CASE_SLUGS),
            "seed": BOOTSTRAP_SEED,
            "resamples": BOOTSTRAP_RESAMPLES,
        },
        "source": source,
        "interpretation": (
            "Adaptive treatment selected after the regret decomposition; the paired "
            "control is the sealed confirmatory V4 arm. Support requires the "
            "preregistered regret benefit and feasibility guardrail. Eligibility never "
            "depends on effect direction."
        ),
    }
    comparison["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(comparison)).hexdigest()
    return comparison


def _execution_status(run_root: Path, canary: Mapping[str, Any] | None) -> dict[str, Any]:
    arms: dict[str, Any] = {}
    completed = failures = row_count = 0
    scored_cost = 0.0
    for name in _arm_specs():
        summary_path = run_root / "arms" / name / "summary.json"
        if not summary_path.exists():
            arms[name] = {
                "status": "not_started",
                "planned_trajectory_count": len(CASE_SLUGS) * len(INFERENCE_SEEDS),
                "completed_trajectory_count": 0,
                "operational_failure_count": 0,
            }
            continue
        artifact = json.loads(summary_path.read_text())
        summary = artifact["summary"]
        completed += int(summary["completed_trajectory_count"])
        failures += int(summary["operational_failure_count"])
        row_count += int(summary["row_count"])
        scored_cost += float(summary["total_cost_usd"])
        arms[name] = {
            "status": (
                "qualified"
                if summary["readiness"]["execution_qualified"]
                else "operational_failure"
                if summary["operational_failure_count"]
                else "checkpoint"
            ),
            "artifact_sha256": artifact["artifact_sha256"],
            "planned_trajectory_count": summary["planned_trajectory_count"],
            "completed_trajectory_count": summary["completed_trajectory_count"],
            "operational_failure_count": summary["operational_failure_count"],
            "scored_cost_usd": summary["total_cost_usd"],
        }
    planned = len(_arm_specs()) * len(CASE_SLUGS) * len(INFERENCE_SEEDS)
    canary_cost = float(canary.get("cost_usd", 0.0)) if canary else 0.0
    admitted = bool(canary) and canary.get("status") == "admitted"
    status: dict[str, Any] = {
        "schema_version": "aeread.procurement_allocation_pre_award_check_status/0.1",
        "campaign_id": CAMPAIGN_ID,
        "canary": dict(canary) if canary else None,
        "arms": arms,
        "summary": {
            "planned_trajectory_count": planned,
            "row_count": row_count,
            "completed_trajectory_count": completed,
            "operational_failure_count": failures,
            "unattempted_trajectory_count": planned - row_count,
            "scored_cost_usd": scored_cost,
            "canary_cost_usd": canary_cost,
            "total_cost_including_canary_usd": scored_cost + canary_cost,
            "execution_qualified": admitted and completed == planned and failures == 0,
            "failure_free_checkpoint": admitted and 0 < completed < planned and failures == 0,
        },
    }
    status["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(status)).hexdigest()
    return status


async def run_worksheet_campaign(
    *,
    run_root: Path,
    max_spend_usd: float = 2.19,
    resume: bool = False,
    provider_factory: Callable[[], Any] = OpenRouterChatClient,
    preflight_fn: Callable[[Any], Mapping[str, Any]] = preflight_candidate,
) -> dict[str, Any]:
    resolved = run_root.resolve()
    if "runs" not in resolved.parts or {"evidence", "output", "outputs"}.intersection(
        resolved.parts
    ):
        raise ValueError("run_root must be under runs/ and outside publication paths")
    if run_root.exists() and not resume:
        raise FileExistsError("worksheet output exists; pass --resume only after a failure-free checkpoint")
    if resume and not run_root.exists():
        raise FileNotFoundError("cannot resume a worksheet campaign that does not exist")
    plan = build_plan()
    if float(plan["hard_total_cost_ceiling_usd"]) > max_spend_usd:
        raise ValueError("worksheet hard ceiling exceeds max_spend_usd")
    plan_path = run_root / "campaign_plan.json"
    if plan_path.exists():
        if canonical_json_bytes(json.loads(plan_path.read_text())) != canonical_json_bytes(plan):
            raise ValueError("existing worksheet plan does not match this invocation")
    else:
        _write_once_json(plan_path, plan)
    for name in _arm_specs():
        path = run_root / "arms" / name / "summary.json"
        if path.exists() and json.loads(path.read_text())["summary"]["operational_failure_count"]:
            raise ValueError("cannot resume an attempt containing an operational failure")
    canary = await run_admission_canary(
        path=run_root / "canaries" / "treatment.json", provider_factory=provider_factory
    )
    if canary.get("status") == "admitted":
        preflight = dict(preflight_fn(GLM_PARASAIL_CANDIDATE))
        remaining_batch = CONFIRMATORY_BATCH_SIZE
        for name, spec in _arm_specs().items():
            arm_root = run_root / "arms" / name
            prior_count = 0
            summary_path = arm_root / "summary.json"
            if summary_path.exists():
                prior = json.loads(summary_path.read_text())
                prior_count = int(prior["summary"]["row_count"])
                if prior["summary"]["readiness"]["execution_qualified"]:
                    continue
            if remaining_batch < 1:
                break
            artifact = await run_model_qualification(
                run_root=arm_root,
                case_paths=spec["case_paths"],
                inference_seeds=INFERENCE_SEEDS,
                max_spend_usd=max_spend_usd,
                max_parallel_cells=CONFIRMATORY_MAX_PARALLEL_CELLS,
                resume=arm_root.exists(),
                provider_factory=provider_factory,
                preflight_fn=lambda _candidate: preflight,
                campaign_id=f"{CAMPAIGN_ID}.{name}",
                abort_on_operational_failure=True,
                candidate=GLM_PARASAIL_CANDIDATE,
                prompt=spec["prompt"],
                prompt_id=spec["prompt_id"],
                treatment_id=spec["treatment_id"],
                max_new_trajectories=remaining_batch,
                max_action_attempts=MAX_ACTION_ATTEMPTS,
                retryable_conditions=CONFIRMATORY_RETRY_CONDITIONS,
                retry_backoff=RETRY_BACKOFF,
                retry_after_max_seconds=RETRY_AFTER_MAX_SECONDS,
            )
            new_count = int(artifact["summary"]["row_count"]) - prior_count
            remaining_batch -= new_count
            if artifact["summary"]["operational_failure_count"]:
                break
    status = _execution_status(run_root, canary)
    _replace_json(run_root / "campaign_status.json", status)
    if status["summary"]["execution_qualified"]:
        comparison = build_worksheet_comparison(run_root=run_root)
        _write_once_json(run_root / "worksheet_comparison.json", comparison)
        status = {**status, "comparison": comparison}
    return status


def _sanitized_arm(*, run_root: Path, name: str) -> dict[str, Any]:
    artifact, file_sha = _verified_summary(
        run_root / "arms" / name, campaign_id=f"{CAMPAIGN_ID}.{name}"
    )
    preflight = artifact.get("preflight")
    safe_preflight = None
    if isinstance(preflight, Mapping):
        safe_preflight = {
            key: preflight[key]
            for key in (
                "candidate_id",
                "model",
                "revision",
                "route_provider",
                "quantization",
                "eligible_endpoint_count",
                "prompt_per_million_range",
                "completion_per_million_range",
                "supported_parameters_verified",
                "source",
            )
            if key in preflight
        }
    return {
        "schema_version": "aeread.procurement_allocation_pre_award_check_arm_review/0.1",
        "campaign_id": f"{CAMPAIGN_ID}.{name}",
        "arm": name,
        "source": {
            "raw_summary_path": (
                f"runs/procurement_allocation/{CAMPAIGN_ID}/{run_root.name}/"
                f"arms/{name}/summary.json"
            ),
            "raw_summary_file_sha256": file_sha,
            "raw_artifact_sha256": artifact["artifact_sha256"],
            "plan_sha256": artifact["plan"]["plan_sha256"],
        },
        "plan": artifact["plan"],
        "preflight": safe_preflight,
        "summary": artifact["summary"],
        "rows": [
            {key: row[key] for key in PUBLISHABLE_ROW_FIELDS if key in row}
            for row in artifact["rows"]
        ],
    }


def _verified_canary(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    recorded = value.get("artifact_sha256")
    payload = {key: item for key, item in value.items() if key != "artifact_sha256"}
    if recorded != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
        raise ValueError("admission canary digest mismatch")
    if (
        value.get("campaign_id") != CAMPAIGN_ID
        or value.get("status") != "admitted"
        or value.get("scored") is not False
        or value.get("prompt_id") != PROMPT_ID
        or value.get("prompt_sha256") != FROZEN_WORKSHEET_PROMPT_SHA256
        or value.get("model") != GLM_PARASAIL_CANDIDATE.route.model
        or value.get("revision") != GLM_PARASAIL_CANDIDATE.route.revision
        or value.get("route_provider") != GLM_PARASAIL_CANDIDATE.route.route_provider
        or value.get("resolved_model") != GLM_PARASAIL_CANDIDATE.route.revision
    ):
        raise ValueError("admission canary identity or admission state mismatch")
    return value


def publish_worksheet_campaign(*, run_root: Path, publication_root: Path) -> dict[str, Any]:
    if publication_root.resolve().parent.name != "evidence":
        raise ValueError("publication_root must be one direct evidence/ bundle")
    comparison = build_worksheet_comparison(run_root=run_root)
    if not comparison["readiness"]["worksheet_treatment_qualified"]:
        raise ValueError("worksheet evidence is not qualified")
    artifacts: dict[str, str] = {}
    for name in _arm_specs():
        review = _sanitized_arm(run_root=run_root, name=name)
        review["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(review)).hexdigest()
        relative = f"reports/{name}.json"
        path = publication_root / relative
        _write_once_json(path, review)
        artifacts[relative] = _sha256_file(path)
    comparison_path = publication_root / "reports" / "worksheet_effects.json"
    _write_once_json(comparison_path, comparison)
    artifacts["reports/worksheet_effects.json"] = _sha256_file(comparison_path)
    canary = _verified_canary(run_root / "canaries" / "treatment.json")
    canary_path = publication_root / "reports" / "treatment_admission_canary.json"
    _write_once_json(canary_path, canary)
    artifacts["reports/treatment_admission_canary.json"] = _sha256_file(canary_path)
    plan = json.loads((run_root / "campaign_plan.json").read_text())
    plan_path = publication_root / "tables" / "frozen_plan.json"
    _write_once_json(plan_path, plan)
    artifacts["tables/frozen_plan.json"] = _sha256_file(plan_path)
    manifest: dict[str, Any] = {
        "schema_version": "aeread.publication_manifest/0.1",
        "publication_id": CAMPAIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "support_status": comparison["support"]["status"],
        "artifacts": artifacts,
        "source_bindings": {
            "campaign_plan_sha256": plan["plan_sha256"],
            "comparison_artifact_sha256": comparison["artifact_sha256"],
            "implementation_sha256": _sha256_file(Path(__file__)),
            "parent_manifest_file_sha256": PARENT_MANIFEST_FILE_SHA256,
            "parent_control_file_sha256": {
                surface: binding["file_sha256"]
                for surface, binding in PARENT_CONTROL_REPORTS.items()
            },
        },
        "privacy_boundary": {
            "included": (
                "prompt hashes, public action traces, outcomes, typed failures, usage, "
                "cost, negotiation diagnostics, and receipt/result digests"
            ),
            "excluded": (
                "full prompts, observations, provider payloads, event logs, hidden "
                "supplier terms, and account metadata"
            ),
        },
    }
    manifest["manifest_sha256"] = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    _write_once_json(publication_root / "publication_manifest.json", manifest)
    _write_once_text(
        publication_root / "README.md",
        f"# {CAMPAIGN_ID}\n\n"
        "Sanitized, digest-bound evidence for the frozen negotiation-worksheet "
        "treatment paired against the sealed confirmatory V4 arm. Raw provider state "
        "remains under ignored `runs/`.\n",
    )
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument("--max-spend-usd", type=float, default=2.19)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--publish-only", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.execute and arguments.publish_only:
        parser.error("--execute and --publish-only are mutually exclusive")
    if arguments.publish_only:
        if arguments.publication_root is None:
            parser.error("--publish-only requires --publication-root")
        manifest = publish_worksheet_campaign(
            run_root=arguments.run_root, publication_root=arguments.publication_root
        )
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    if not arguments.execute:
        print(json.dumps(build_plan(), indent=2, sort_keys=True))
        return 0
    status = asyncio.run(
        run_worksheet_campaign(
            run_root=arguments.run_root,
            max_spend_usd=arguments.max_spend_usd,
            resume=arguments.resume,
        )
    )
    print(json.dumps(status, indent=2, sort_keys=True))
    if status["summary"]["execution_qualified"]:
        return 0
    if status["summary"]["operational_failure_count"]:
        return 2
    if not status["summary"]["failure_free_checkpoint"]:
        return 3
    return 4


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CAMPAIGN_ID",
    "FROZEN_WORKSHEET_PROMPT_SHA256",
    "INFERENCE_SEEDS",
    "PROMPT_ID",
    "TREATMENT_ID",
    "WORKSHEET_PROMPT",
    "build_plan",
    "build_worksheet_comparison",
    "publish_worksheet_campaign",
    "run_admission_canary",
    "run_worksheet_campaign",
]
