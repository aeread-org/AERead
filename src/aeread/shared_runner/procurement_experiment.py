"""Procurement panel rehearsal and gated Gemini/DeepSeek paired experiments.

Offline is the default and never masquerades as a live model result. Live modes
require two explicit thinking efforts and a total recorded-spend limit. Sample
execution additionally requires six fully replayed, out-of-panel admission cells.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .batch import _batch_lock, atomic_write_json, paired_schedule, read_family_batch, run_family_batch
from .execution import GeminiGenerateContentClient, OpenRouterChatClient, _paired_cell_request_seed
from .housing import OpenRouterRoutePin
from .paired_analysis import analyze_paired_results
from .procurement_measurement import procurement_measurement_leaf, procurement_score_support
from .procurement_rfq import ProcurementRFQPlugin, ProcurementScriptedBuyerProvider, ProcurementScriptedSupplierProvider, build_procurement_rfq_smoke
from .resolver import canonical_json_bytes


OFFLINE_MASTER_SEED = 20260827
DEEPSEEK_MODEL = "deepseek/deepseek-v4-flash-0731"
DEEPSEEK_ROUTE = OpenRouterRoutePin(
    provider="Parasail", quantization="fp8",
    canonical_model="deepseek/deepseek-v4-flash-20260731",
    input_per_million=.14, cached_input_per_million=.05, output_per_million=.28,
    pricing_id="openrouter_parasail_2026-08-28_deepseek-v4-flash-0731",
)
DEEPSEEK_BUYER_LIMITS = {
    "buyer_temperature": 1.0,
    "buyer_max_output_tokens": 32768,
    "buyer_timeout_seconds": 1800.0,
    "buyer_max_cost_usd": .04,
}
# Cover the post-call profile stop plus two full-context requests (including a
# length retry): .04 + 2 * (1048576*.14 + 65536*.28)/1e6 < .4 USD.
DEEPSEEK_EPISODE_RESERVE_USD = .4


def derive_procurement_world_seeds(*, master_seed: int, count: int, admission: bool = False) -> tuple[int, ...]:
    if isinstance(master_seed, bool) or not isinstance(master_seed, int) or master_seed < 0:
        raise ValueError("master_seed must be a nonnegative integer")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("world count must be a positive integer")
    namespace = "procurement_admission_v1" if admission else "procurement_panel_v1"
    seeds, counter = [], 0
    while len(seeds) < count:
        digest = hashlib.sha256(f"{namespace}:{master_seed}:{counter}".encode()).digest()
        candidate = int.from_bytes(digest[:4], "big") & 0x7FFF_FFFF
        counter += 1
        if candidate not in seeds:
            seeds.append(candidate)
    return tuple(seeds)


def analyze_procurement_panel(rows: Sequence[Mapping[str, Any]], *, setups: Mapping[str, Any],
                              bootstrap_draws: int = 10_000, bootstrap_seed: int = 20260827) -> dict[str, Any]:
    schedule = paired_schedule(setups)
    expected = {(condition, cell.world_seed, cell.replicate_index) for condition, cell in schedule}
    observed = {(row.get("condition_id"), row.get("world_seed"), row.get("replicate_index")) for row in rows}
    if len(observed) != len(rows) or not observed.issubset(expected):
        raise ValueError("result identity is duplicate or outside the declared panel")
    worlds = {cell.world_seed for _, cell in schedule}
    base = {"planned_world_count": len(worlds), "planned_cell_count": len(expected),
            "unattempted_count": len(expected - observed)}
    if expected != observed:
        return {**base, "status": "deferred_incomplete_panel", "analysis": None}
    # A single cluster is an instrumentation check, not an uncertainty estimate.
    complete_worlds = {world for world in worlds if all(
        row.get("status") == "completed" and row.get("within_case_score") is not None
        for row in rows if row["world_seed"] == world)}
    if len(complete_worlds) < 2:
        return {**base, "status": "deferred_fewer_than_two_complete_clusters", "analysis": None}
    setup = next(iter(setups.values()))
    plugin = ProcurementRFQPlugin()
    supports = {case.world_seed: procurement_score_support(plugin.validate_payload(case.payload)) for case in setup.plan.cases}
    conditions = list(setups)
    analysis = analyze_paired_results(rows, control_condition=conditions[0], treatment_condition=conditions[1],
        expected_replicates=setup.plan.sampling.replicates, bootstrap_draws=bootstrap_draws,
        bootstrap_seed=bootstrap_seed, score_support_by_world=supports)
    return {**base, "status": "complete", "analysis": analysis,
            "ninety_complete_world_planning_target_met": len(complete_worlds) >= 90,
            "estimand": "treatment_minus_control_mean_normalized_buyer_surplus"}


def validate_live_admission(rows: Sequence[Mapping[str, Any]], *, setups: Mapping[str, Any]) -> None:
    expected = {(condition, cell.world_seed, cell.replicate_index): cell for condition, cell in paired_schedule(setups)}
    if len(expected) != 6 or len(rows) != 6 or len({cell.world_seed for cell in expected.values()}) != 3:
        raise ValueError("live admission requires three worlds by two conditions by one repeat")
    seen = set()
    for row in rows:
        identity = (row.get("condition_id"), row.get("world_seed"), row.get("replicate_index"))
        if identity not in expected or identity in seen:
            raise ValueError("live admission identities do not match")
        seen.add(identity)
        setup, cell = setups[identity[0]], expected[identity]
        profile = next(p for p in setup.plan.agent_profiles if p.profile_id == cell.profile_by_seat["buyer_0"])
        if (profile.model.provider, profile.model.model) not in {
                ("google", "gemini-3.7-flash"), ("openrouter", DEEPSEEK_MODEL)}:
            raise ValueError("live admission requires a supported Gemini or DeepSeek profile")
        if profile.model.provider == "openrouter":
            if row.get("temperatures") != [profile.sampling.temperature]:
                raise ValueError("live admission failed: requested temperature did not verify")
            route = profile.harness.config["provider_metadata"]["route_provider"]
            if (row.get("route_providers") != [route] or row.get("route_verification_failures", 1) != 0):
                raise ValueError("live admission failed: actual OpenRouter route did not verify")
            if profile.reasoning.effort == "none" and row.get("reasoning_tokens", 0) != 0:
                raise ValueError("live admission failed: reasoning-off condition reported reasoning tokens")
        expected_seed = _paired_cell_request_seed(base_seed=profile.harness.config["request_seed_base"],
                                                world_seed=cell.world_seed, replicate_index=cell.replicate_index)
        if (row.get("status") != "completed" or row.get("receipt_inclusion_status") != "included"
                or row.get("replay_level") != "state_and_score"
                or row.get("external_provider_call_count", 0) < 4
                or row.get("external_fixture_call_count", 1) != 0
                or row.get("unknown_cost_provider_call_count", 1) != 0
                or row.get("request_seeds") != [expected_seed]
                or row.get("reasoning_efforts") != [profile.reasoning.effort]
                or row.get("resolved_models") != [profile.model.revision if profile.model.provider == "openrouter" else profile.model.model]):
            raise ValueError("live admission failed: incomplete, scripted, or mismatched provider evidence")


async def run_procurement_experiment(
    *, output_root: str | Path, mode: str = "offline", world_count: int = 100, replicates: int = 3,
    master_seed: int | None = None, inference_seed_base: int = 20260827,
    control_effort: str | None = None, treatment_effort: str | None = None,
    spend_limit_usd: float | None = None, bootstrap_draws: int = 10_000,
    provider: str = "gemini",
) -> dict[str, Any]:
    if mode not in {"offline", "admission", "sample"}:
        raise ValueError("mode must be offline, admission, or sample")
    live = mode != "offline"
    if provider not in {"gemini", "deepseek"}:
        raise ValueError("provider must be gemini or deepseek")
    if live:
        allowed_efforts = {"low", "medium", "high"} if provider == "gemini" else {"none", "low", "medium", "high"}
        if control_effort not in allowed_efforts or treatment_effort not in allowed_efforts or control_effort == treatment_effort:
            raise ValueError("live conditions require two explicit, distinct supported thinking efforts")
        if isinstance(spend_limit_usd, bool) or not isinstance(spend_limit_usd, (int, float)) or not math.isfinite(spend_limit_usd) or spend_limit_usd <= 0:
            raise ValueError("live runs require an explicit positive total spend budget")
        if master_seed is None or master_seed == OFFLINE_MASTER_SEED:
            raise ValueError("live runs require an explicit fresh master seed, not the inspected offline panel seed")
    if master_seed is None:
        master_seed = OFFLINE_MASTER_SEED
    panel = derive_procurement_world_seeds(master_seed=master_seed, count=world_count)
    admission = derive_procurement_world_seeds(master_seed=master_seed, count=3, admission=True)
    if set(panel) & set(admission):
        raise ValueError("admission and analysis panel seed sets overlap")
    conditions = ({f"reasoning_{control_effort}_v1": control_effort, f"reasoning_{treatment_effort}_v1": treatment_effort}
                  if live else {"scripted_control_v1": "none", "scripted_repeat_v1": "none"})
    if isinstance(bootstrap_draws, bool) or not isinstance(bootstrap_draws, int) or bootstrap_draws < 1:
        raise ValueError("bootstrap_draws must be a positive integer")

    def build(seeds, repeats):
        return {condition: build_procurement_rfq_smoke(
            buyer_provider=("google" if provider == "gemini" else "openrouter") if live else "procurement_scripted_buyer",
            buyer_model=("gemini-3.7-flash" if provider == "gemini" else DEEPSEEK_MODEL) if live else "procurement_scripted_buyer_v1",
            buyer_revision=("3.7-flash-08-2026" if provider == "gemini" else DEEPSEEK_ROUTE.canonical_model) if live else "1.0.0", world_seeds=seeds,
            replicates=repeats, reasoning_effort=effort, condition_id=condition,
            inference_seed_base=inference_seed_base, openrouter_route=DEEPSEEK_ROUTE,
            **(DEEPSEEK_BUYER_LIMITS if live and provider == "deepseek" else {}))
            for condition, effort in conditions.items()}

    root = Path(output_root)
    if live:
        inspected_seeds = set(derive_procurement_world_seeds(master_seed=OFFLINE_MASTER_SEED, count=100))
        offline_study_path = root / "offline_study.json"
        if offline_study_path.exists():
            inspected_seeds.update(json.loads(offline_study_path.read_bytes())["panel_seeds"])
        if (set(panel) | set(admission)) & inspected_seeds:
            raise ValueError("live seed panel overlaps inspected offline worlds; choose a fresh master seed")
    study = {
        "spec_version": "aeread.procurement_study/1",
        "provider": provider if live else "scripted",
        "openrouter_route": DEEPSEEK_ROUTE.provider_metadata() if live and provider == "deepseek" else None,
        "buyer_runtime_limits": DEEPSEEK_BUYER_LIMITS if live and provider == "deepseek" else None,
        "max_concurrency": 16 if live and provider == "deepseek" else 1,
        "inflight_episode_reserve_usd": DEEPSEEK_EPISODE_RESERVE_USD if live and provider == "deepseek" else 0.0,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes() + Path(__file__).with_name("paired_analysis.py").read_bytes()).hexdigest(),
        "evidence_kind": "native_live_provider" if live else "scripted_instrumentation_only",
        "panel_seeds": panel, "admission_seeds": admission, "replicates": replicates,
        "inference_seed_base": inference_seed_base, "ordered_conditions": list(conditions.items()),
        "bootstrap_draws": bootstrap_draws, "bootstrap_seed": 20260827,
        "primary_estimand": "treatment_minus_control_mean_normalized_buyer_surplus",
        "total_recorded_spend_limit_usd": spend_limit_usd if live else 0.0,
        "complete_world_planning_target": 90,
    }
    with _batch_lock(root):
        study_path = root / ("live_study.json" if live else "offline_study.json")
        if study_path.exists():
            if canonical_json_bytes(json.loads(study_path.read_bytes())) != canonical_json_bytes(study):
                raise ValueError("study manifest changed; use a new output directory")
        else:
            atomic_write_json(study_path, study)
    admission_cost = 0.0
    if mode == "sample":
        admission_setups = build(admission, 1)
        if not (root / "admission" / "batch_manifest.json").exists():
            raise ValueError("sample requires verified out-of-panel live admission first")
        admission_rows = read_family_batch(setups=admission_setups, output_root=root / "admission")
        validate_live_admission(admission_rows, setups=admission_setups)
        admission_cost = sum(row["cost_usd"] for row in admission_rows)
        if admission_cost >= spend_limit_usd:
            raise ValueError("admission already exhausted the total spend budget")
    setups = build(admission if mode == "admission" else panel, 1 if mode == "admission" else replicates)
    # No API client is even constructed until the sample admission gate is satisfied.
    live_provider = "google" if provider == "gemini" else "openrouter"
    live_client = GeminiGenerateContentClient if provider == "gemini" else OpenRouterChatClient
    clients = {condition: {
        live_provider if live else "procurement_scripted_buyer": live_client() if live else ProcurementScriptedBuyerProvider(),
        "procurement_scripted_supplier": ProcurementScriptedSupplierProvider(),
    } for condition in conditions}
    phase_root = root / mode
    batch = await run_family_batch(setups=setups, output_root=phase_root, providers_by_condition=clients,
        leaf_builder=procurement_measurement_leaf,
        spend_limit_usd=(spend_limit_usd - admission_cost) if live else 1.0,
        max_concurrency=study["max_concurrency"],
        inflight_episode_reserve_usd=study["inflight_episode_reserve_usd"])
    live_admission = False
    admission_error = None
    if mode == "admission":
        try:
            validate_live_admission(batch["rows"], setups=setups)
            live_admission = True
        except ValueError as error:
            admission_error = str(error)
    result = {"mode": mode, "provider": provider if live else "scripted", "live_admission": live_admission, "admission_error": admission_error,
        "scope": "synthetic electronics RFQ grammar with controlled suppliers; not real vendor procurement",
        "master_seed": master_seed, "inference_seed_base": inference_seed_base,
        "world_seeds": list(admission if mode == "admission" else panel), "conditions": conditions,
        "batch": batch, "total_known_cost_usd_including_admission": batch["known_cost_usd"] + admission_cost,
        "analysis": analyze_procurement_panel(batch["rows"], setups=setups, bootstrap_draws=bootstrap_draws),
        "evidence_kind": "native_live_provider" if live else "scripted_instrumentation_only"}
    atomic_write_json(phase_root / "summary.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("offline", "admission", "sample"), default="offline")
    parser.add_argument("--provider", choices=("gemini", "deepseek"), default="gemini")
    parser.add_argument("--world-count", type=int, default=100)
    parser.add_argument("--replicates", type=int, default=3)
    parser.add_argument("--master-seed", type=int, help="explicit fresh seed required for live modes; offline defaults to 20260827")
    parser.add_argument("--inference-seed-base", type=int, default=20260827)
    parser.add_argument("--control-effort", choices=("none", "low", "medium", "high"))
    parser.add_argument("--treatment-effort", choices=("none", "low", "medium", "high"))
    parser.add_argument("--spend-limit-usd", type=float)
    args = vars(parser.parse_args(argv))
    args["output_root"] = args.pop("output")
    result = asyncio.run(run_procurement_experiment(**args))
    compact = {**result, "batch": {key: value for key, value in result["batch"].items() if key != "rows"}}
    print(canonical_json_bytes(compact).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
