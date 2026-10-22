"""Housing v15, addendum B: the price case's deciding tenant played by a CLI subject on v15's worlds.

Declared in ``docs/families/housing/price_v15_addendum_b_cli_plan.md``. v15's market, unchanged: its pack (260 main
worlds, 40 holdout), both landlord arms, notice v5, the scripted landlords and outside demand (0.5 a round on the main
pack, 0.3 on the holdout), and the seat-0 scorer through ``price_seat0.build_v15_setup``. Only the deciding tenant's
model block and transport differ: one subprocess per action through Claude Code (``ClaudeCodePrintClient``) or Codex
(``codex_exec_client.CodexExecClient``), with no tools, isolated as the Data-center v2 and Procurement v3
confirmatories were (``cli_isolation``).

How the plan is built (the earlier CLI probe's way, ``housing_cli.py`` on ``codex/cli-subjects-housing-probe``): the
identity is registered into ``price_campaign`` for this process, its v15 plan is built as the confirmatory's is, the
tenant profile's model block is replaced, and the plan is resolved again from the same families, cases, pins and run
spec. No hashed module is edited.

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/housing_v15_cli.py --subject codex_sol61 --kind admission
    ... --kind admission --execute        # probe, then one development world in both arms
    ... --kind main --execute             # after the plan's amendment sets the main ceiling
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import math
import shutil
import time
from pathlib import Path
from typing import Any, Mapping

import cli_isolation as iso
import codex_exec_client as codex
from aeread.shared_runner.registry import ProviderCapabilities
from aeread.shared_runner.run.resolver import canonical_json_bytes, resolve_run_plan
from aeread.shared_runner.schemas import AgentProfile
from aeread.shared_runner.task.execution import ClaudeCodePrintClient, execute_plan_cell
from aeread.shared_runner.task.receipts import verify_evaluation_receipt
from aeread_families.housing import price_campaign as pc
from aeread_families.housing import price_seat0
from aeread_families.housing import price_v15_identities as v15
from aeread_families.housing.population_campaign import _failure_usage
from aeread_families.housing.runner import (
    HousingScriptedLandlordProvider,
    OpenRouterRoutePin,
    finalize_housing_execution,
    finalize_housing_failure,
    replay_housing_receipt,
)

REPOSITORY = Path(__file__).resolve().parents[2]
RUNS = REPOSITORY / "runs" / "housing_v15"
PLAN = "docs/families/housing/price_v15_addendum_b_cli_plan.md"


def _pin(provider: str, model: str, prices: tuple[float, float, float], pricing_id: str) -> OpenRouterRoutePin:
    """The CLI's list price in the shape the Housing runner seals a price in. It names no OpenRouter endpoint."""
    return OpenRouterRoutePin(provider=provider, quantization="not_applicable", canonical_model=model,
                              input_per_million=prices[0], cached_input_per_million=prices[1],
                              output_per_million=prices[2], pricing_id=pricing_id)


#: Both CLIs run on a subscription login: a cost is the list price of the tokens, not a charge (plan Section 1).
SUBJECTS: dict[str, dict[str, Any]] = {
    "claude_opus55": {
        "provider": "claude_code", "model": "claude-opus-5-5",
        "pin": _pin("claude_code_cli", "claude-opus-5-5", (4.0, 0.20, 20.0), "anthropic_list_2026-09-22_claude-opus-5-5"),
        "cell_ceiling_usd": 2.0,
    },
    "codex_sol61": {
        "provider": codex.PROVIDER, "model": "gpt-6.1-sol",
        "pin": _pin("codex_cli", "gpt-6.1-sol", (2.0, 0.10, 10.0), "openai_list_2026-10-04_gpt-6.1-sol"),
        "cell_ceiling_usd": 1.0,
    },
}
#: Total ceilings, $ at list price (plan Section 3). A main identity's is set by the plan's amendment from its
#: admission (twice the measured cost a cell times 600, plus one cell's ceiling); until then it is None and refused.
CEILINGS: dict[str, float | None] = {
    "housing_lemons_price_v15_cli_admission_codex_sol61": 4.0,
    "housing_lemons_price_v15_cli_admission_claude_opus55": 4.0,
    # Amendment 1 (after admission, before the main runs): twice the measured list cost a cell times 600, plus one
    # cell's ceiling. Sol's admission cost $0.126802 for 2 cells, Opus's $0.240608.
    "housing_lemons_price_v15_cli_codex_sol61": 77.08,
    "housing_lemons_price_v15_cli_claude_opus55": 146.36,
}
MAX_PARALLEL_CELLS = 3
WALL_TIME_GATE_HOURS = 6.0
TRANSPORT_KEYS = ("provider_metadata", "request_seed_source", "request_seed_base", "retry_backoff",
                  "retry_base_seconds", "retry_after_max_seconds", "max_output_tokens_ceiling")


def campaign_id(subject: str, kind: str) -> str:
    return f"housing_lemons_price_v15_cli_{'admission_' if kind == 'admission' else ''}{subject}"


def register(subject: str, kind: str) -> str:
    """Make the identity known to ``price_campaign`` for this process; the module itself is not edited."""
    spec, name = SUBJECTS[subject], campaign_id(subject, kind)
    ceiling = CEILINGS[name]
    if ceiling is None:
        raise SystemExit(f"{name}: its total ceiling is set by the plan's amendment after admission; none is recorded")
    route_id = f"cli_{subject}"
    pc.ROUTES[route_id] = (spec["model"], spec["pin"])
    worlds = {"world_seeds": list(v15.DEVELOPMENT[:1]), "claim_status": "profile_admission",
              "analysis": v15.ADMISSION_ANALYSIS} if kind == "admission" else {
        "world_seeds": list(v15.MAIN), "holdout_world_seeds": list(v15.HOLDOUT),
        "claim_status": "confirmatory_addendum", "analysis": v15.ANALYSIS}
    pc.IDENTITIES[name] = {**v15.BASE, "route_id": route_id, "profile": f"housing_price_{subject}_tenant_cli_v15",
                           "reasoning_effort": "low", "temperature": "unavailable", "top_p": None,
                           "max_action_attempts": 1, "total_cost_ceiling_usd": ceiling, **worlds}
    return name


def build_contract(subject: str, kind: str, runtime: Mapping[str, str]) -> dict[str, Any]:
    """v15's contract for the identity, with what the CLI transport declares beside it."""
    spec, name = SUBJECTS[subject], register(subject, kind)
    contract = pc.v15_contract(name)
    contract["tenant_cost_ceiling_usd_per_cell"] = spec["cell_ceiling_usd"]
    contract["cli"] = {
        "plan": PLAN, "provider": spec["provider"], "model": spec["model"], "provider_runtime": dict(runtime),
        "transport": "one CLI subprocess per action; no OpenRouter",
        "billing": "subscription login; cost is the list price of the tokens, not a charge",
        "isolation": dict(iso.DECLARATION),
        "not_applied": {"seed": "unavailable; the profile seals seed null", "temperature": "unavailable",
                        "max_output_tokens": "the CLI's own default", "reasoning_tokens": "not reported"},
        "max_parallel_cells": MAX_PARALLEL_CELLS, "wall_time_gate_hours": WALL_TIME_GATE_HOURS,
        "halt_rule": "a failed cell is typed missingness and never rerun; no new cell starts after "
                     f"{contract['max_consecutive_operational_failures']} consecutive failed cells, after a cell over its "
                     "ceiling, or when the next cells could pass the total ceiling; an isolation violation refuses the run",
    }
    return contract


def cli_setup(contract: Mapping[str, Any], arm: str, subject: str, runtime: Mapping[str, str], *,
              holdout_rate: bool) -> Any:
    """``price_seat0.build_v15_setup``'s setup with the tenant profile's model block replaced, resolved again."""
    spec = SUBJECTS[subject]
    setup = price_seat0.build_v15_setup(contract, arm, live=True, holdout_rate=holdout_rate)
    plan = setup.plan
    profiles = []
    for profile in plan.agent_profiles:
        if profile.model.provider != "openrouter":
            profiles.append(profile)
            continue
        body = json.loads(canonical_json_bytes(profile))
        body["model"] = {"provider": spec["provider"], "model": spec["model"], "revision": spec["model"], "base_url": None}
        config = body["harness"]["config"]
        for key in TRANSPORT_KEYS:
            config.pop(key, None)
        config["provider_runtime"] = dict(runtime)
        config["sampling_controls"] = {"temperature": "unavailable", "max_output_tokens": "provider_model_default"}
        body["sampling"].update(seed=None, top_p=None, max_output_tokens=32_000)
        profiles.append(AgentProfile.from_dict(body))
    inert = dict(native_tools=False, structured_output=True, seed=False, system_prompt=True,
                 reasoning_token_report=False, max_context_tokens=None)
    resolved = resolve_run_plan(
        families=plan.families, cases=plan.cases, suite=plan.suite, sampling=plan.sampling,
        evaluation_blocks=plan.evaluation_blocks, analysis=plan.analysis, agent_profiles=tuple(profiles),
        run_spec=plan.run_spec, registry=setup.registry, implementation_pins=plan.implementation_pins,
        harness_registry=price_seat0._harness_registry(setup),
        provider_capabilities={
            spec["provider"]: ProviderCapabilities(**{**inert, "reasoning_token_report": spec["provider"] == codex.PROVIDER},
                                                   reasoning_budget=True),
            "housing_scripted_landlord": ProviderCapabilities(**inert, reasoning_budget=False),
        },
    )
    return dataclasses.replace(setup, plan=resolved)


async def _isolated_claude_runner(arguments: tuple[str, ...], standard_input: bytes) -> tuple[int, bytes, bytes]:
    """Claude Code in a fresh neutral directory, carrying its stated reason for a non-zero exit (RN-T-06)."""
    returncode, stdout, stderr = await iso.isolated_command_runner(arguments, standard_input)
    if returncode != 0 and not stderr.strip():
        try:
            payload = json.loads(stdout)
            stderr = f"{payload.get('result')} (api_error_status {payload.get('api_error_status')})".encode("utf-8")
        except (ValueError, AttributeError):
            stderr = stdout[-400:]
    return returncode, stdout, stderr


async def discover(subject: str) -> Any:
    if SUBJECTS[subject]["provider"] == "claude_code":
        found = await ClaudeCodePrintClient.discover()
        return ClaudeCodePrintClient(executable=Path(shutil.which("claude")).resolve(),
                                     runtime_version=found.runtime_version, runtime_sha256=found.runtime_sha256,
                                     command_runner=_isolated_claude_runner)
    iso.install_codex_isolation()
    return await codex.CodexExecClient.discover()


async def probe(subject: str, client: Any) -> dict[str, Any]:
    spec = SUBJECTS[subject]
    if spec["provider"] == "claude_code":
        found = await iso.probe_claude(client, client._executable, model=spec["model"], reasoning_effort="low",
                                       runner=_isolated_claude_runner)
    else:
        found = await iso.probe_codex(client, model=spec["model"], reasoning_effort="low")
    return {"probe": found, "violations": iso.isolation_violations(found), "declaration": dict(iso.DECLARATION)}


async def run_cell(*, setup: Any, stream: str, prefix: str, seed: int, arm: str, results_root: Path, provider: Any,
                   provider_name: str, semaphore: asyncio.Semaphore) -> dict[str, Any]:
    """One cell as ``price_campaign.run`` writes a v15 cell, so ``price_v15_analysis.cells`` reads it unchanged."""
    cell = next(item for item in setup.plan.cells if item.world_seed == seed and item.replicate_index == 0)
    result_path = results_root / f"{prefix}world_{seed}__{arm}.json"
    evidence_root = results_root / f"{prefix}world_{seed}__{arm}_evidence"
    started = time.perf_counter()
    try:
        async with semaphore:
            started = time.perf_counter()
            execution = await execute_plan_cell(
                plan=setup.plan, cell_id=cell.cell_id, registry=setup.registry, evidence_root=evidence_root,
                prompt_sources=setup.prompt_sources,
                providers={provider_name: provider, "housing_scripted_landlord": HousingScriptedLandlordProvider()},
                pricing=setup.pricing, harnesses=setup.harnesses,
            )
        receipt = finalize_housing_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_housing_receipt(setup=setup, receipt=receipt, evidence_root=evidence_root)
        if canonical_json_bytes(replayed.scores) != canonical_json_bytes(receipt.scores):
            raise ValueError("score replay mismatch")
        outcome = execution.episode_result.outcome
        row = {"stream": stream, "world_seed": seed, "arm": arm, "replicate_index": 0, "status": "completed",
               "cost_usd": execution.total_cost_usd, "receipt_sha256": receipt.receipt_sha256,
               "run_plan_id": setup.plan.run_plan_id, "cell_id": cell.cell_id,
               "tenant_net_total": outcome["tenant_net_total"], "price_rows": pc.price_rows(outcome, seed, arm),
               "outcome_facts": {key: outcome[key] for key in pc.OUTCOME_FACTS},
               "elapsed_seconds": round(time.perf_counter() - started, 1)}
    except Exception as error:  # noqa: BLE001 - a failed cell is a typed row, as in price_campaign.run
        failure_receipt = None
        try:
            failure_receipt = finalize_housing_failure(setup=setup, cell_id=cell.cell_id, evidence_root=evidence_root,
                                                       error=error)
        except Exception:  # noqa: BLE001
            pass
        usage = _failure_usage(evidence_root=evidence_root, run_plan_id=setup.plan.run_plan_id, cell_id=cell.cell_id)
        row = {"stream": stream, "world_seed": seed, "arm": arm, "replicate_index": 0, "status": "operational_failure",
               "failure_condition": getattr(error, "condition", type(error).__name__),
               "failure_message": str(error)[:400], "cost_usd": usage["cost_usd"],
               "receipt_sha256": failure_receipt.receipt_sha256 if failure_receipt else None,
               "elapsed_seconds": round(time.perf_counter() - started, 1)}
    result_path.write_bytes(canonical_json_bytes(row) + b"\n")
    print(json.dumps({k: row.get(k) for k in ("stream", "world_seed", "arm", "status", "cost_usd", "elapsed_seconds",
                                              "failure_condition")}), flush=True)
    return row


async def run(subject: str, kind: str, run_root: Path, *, resume: bool) -> dict[str, Any]:
    if "runs" not in run_root.resolve().parts:
        raise ValueError("--run-root must be under the ignored runs/ hierarchy")
    spec = SUBJECTS[subject]
    inner = await discover(subject)
    runtime = dict(inner.runtime_metadata)
    contract = build_contract(subject, kind, runtime)
    run_root.mkdir(parents=True, exist_ok=True)
    contract_path = run_root / "contract.json"
    if contract_path.exists():
        if canonical_json_bytes(json.loads(contract_path.read_text())) != canonical_json_bytes(contract):
            raise ValueError("run root belongs to a different contract")
        if not resume:
            raise FileExistsError("run root exists; pass --resume to continue")
    found = await probe(subject, inner)
    (run_root / f"isolation_probe_{int(time.time())}.json").write_text(json.dumps(found, indent=1, default=str))
    if found["violations"]:
        raise SystemExit(f"isolation probe refuses the run: {found['violations']}")
    if not contract_path.exists():
        contract_path.write_bytes(canonical_json_bytes(contract) + b"\n")
    focal = codex.LoggedClient(inner, run_root / "cli_calls.jsonl", subject=subject)
    streams = [("main", contract["world_seeds"], False, "")]
    if "holdout" in contract:
        streams.append(("holdout", contract["holdout"]["world_seeds"], True, "holdout_"))
    spec_id = pc.identity(contract)
    work = []  # (stream, prefix, setup, provider, seed, arm), in v15's execution order
    run_plan_ids = {}
    for stream, seeds, holdout_rate, prefix in streams:
        setups = {arm: cli_setup(contract, arm, subject, runtime, holdout_rate=holdout_rate) for arm in contract["arms"]}
        run_plan_ids[stream] = {arm: s.plan.run_plan_id for arm, s in setups.items()}
        router = pc.make_seat_router(spec_id, contract, focal, run_root / f"{prefix}seat_calls.jsonl",
                                     holdout_rate=holdout_rate)
        for seed in seeds:
            for arm in contract["arms"]:
                work.append((stream, prefix, setups[arm], router, seed, arm))
    results_root = run_root / "live"
    results_root.mkdir(exist_ok=True)
    rows: list[dict[str, Any]] = []
    todo = []
    for item in work:
        stream, prefix, _setup, _router, seed, arm = item
        path = results_root / f"{prefix}world_{seed}__{arm}.json"
        if path.exists():
            rows.append(json.loads(path.read_text()))
        else:
            todo.append(item)
    semaphore = asyncio.Semaphore(MAX_PARALLEL_CELLS)
    halted = None
    stop_after = int(contract["max_consecutive_operational_failures"])
    ceiling, per_cell = float(contract["total_cost_ceiling_usd"]), float(spec["cell_ceiling_usd"])
    for start in range(0, len(todo), MAX_PARALLEL_CELLS):
        wave = todo[start:start + MAX_PARALLEL_CELLS]
        spent = sum(float(row.get("cost_usd") or 0.0) for row in rows)
        tail = [row["status"] for row in rows][-stop_after:]
        if spent + per_cell * len(wave) > ceiling:
            halted = f"total cost ceiling: spent {spent:.4f} of {ceiling}"
        elif len(tail) == stop_after and all(status == "operational_failure" for status in tail):
            halted = "consecutive operational failures"
        elif any(not math.isfinite(float(row["cost_usd"])) or float(row["cost_usd"]) > per_cell for row in rows):
            halted = "a cell exceeded its cost ceiling"
        if halted:
            rows.extend({"stream": stream, "world_seed": seed, "arm": arm, "replicate_index": 0,
                         "status": "not_attempted", "cost_usd": 0.0} for stream, _p, _s, _r, seed, arm in todo[start:])
            break
        rows.extend(await asyncio.gather(*(
            run_cell(setup=setup, stream=stream, prefix=prefix, seed=seed, arm=arm, results_root=results_root,
                     provider=router, provider_name=spec["provider"], semaphore=semaphore)
            for stream, prefix, setup, router, seed, arm in wave)))
    summary = {**pc.summarize(rows, len(work)), "halted": halted, "campaign_id": contract["campaign_id"],
               "run_plan_ids": run_plan_ids,
               "seconds_a_cell": {"median": sorted(r["elapsed_seconds"] for r in rows if "elapsed_seconds" in r)[
                   len([r for r in rows if "elapsed_seconds" in r]) // 2] if any("elapsed_seconds" in r for r in rows) else None}}
    (results_root / "summary.json").write_bytes(canonical_json_bytes(summary) + b"\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--subject", choices=sorted(SUBJECTS), required=True)
    parser.add_argument("--kind", choices=("admission", "main"), required=True)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    run_root = args.run_root or RUNS / campaign_id(args.subject, args.kind)
    if not args.execute:
        runtime = {"runtime_version": "plan-only"}
        contract = build_contract(args.subject, args.kind, runtime)
        streams = [("main", False)] + ([("holdout", True)] if "holdout" in contract else [])
        ids = {s: {arm: cli_setup(contract, arm, args.subject, runtime, holdout_rate=h).plan.run_plan_id
                   for arm in contract["arms"]} for s, h in streams}
        print(json.dumps({"campaign_id": contract["campaign_id"], "run_root": str(run_root),
                          "worlds": len(contract["world_seeds"]), "holdout": len(contract.get("holdout", {}).get("world_seeds", [])),
                          "ceiling": contract["total_cost_ceiling_usd"], "run_plan_ids": ids}, indent=1))
        return 0
    summary = asyncio.run(run(args.subject, args.kind, run_root, resume=args.resume))
    print(json.dumps({k: v for k, v in summary.items() if k != "price_by_arm_quality"}, sort_keys=True)[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
