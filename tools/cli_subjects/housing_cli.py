"""The Housing price case (one deciding tenant, outside demand) played by a CLI subject.

The v14 confirmatory market, unchanged: the same worlds, both landlord arms,
three rounds, the sealed tenant prompt with the rules of the market in it, the
scripted landlord and the scripted outside demand. Only the deciding tenant's
model block and transport differ: one subprocess per action through the
kernel's ``ClaudeCodePrintClient`` or ``codex_exec_client.CodexExecClient``,
both without tools.

How the plan is built. ``runner.build_housing_smoke`` knows two kinds of tenant,
an OpenRouter route and the scripted policy, and editing it moves the run-plan
id of every sealed Housing identity (HL-T-04). So this builds the v14 plan for
a route pin that carries the CLI's list price, replaces the tenant profile's
model block and transport settings, and resolves the plan again from the same
families, cases, pins and run spec. Nothing in the hashed modules changes.

What a CLI cannot do is declared: no seed, no temperature, no output cap, so
the profile seals ``seed: null`` and ``sampling_controls: unavailable``.

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/housing_cli.py \
        --subject codex_sol61 --panel gate --run-root runs/<campaign> --execute
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import math
import shutil
import statistics
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.model_call.harness import MinimalChatHarness
from aeread.shared_runner.registry import HarnessRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import canonical_json_bytes, resolve_run_plan
from aeread.shared_runner.schemas import AgentProfile
from aeread.shared_runner.task import execution as kernel_execution
from aeread.shared_runner.task.execution import ClaudeCodePrintClient, execute_plan_cell
from aeread.shared_runner.task.receipts import verify_evaluation_receipt
from aeread_families.housing import price_campaign as pc
from aeread_families.housing import price_endpoint
from aeread_families.housing.population_campaign import _failure_usage
from aeread_families.housing.runner import (
    HousingScriptedLandlordProvider,
    OpenRouterRoutePin,
    finalize_housing_execution,
    finalize_housing_failure,
    replay_housing_receipt,
)

import codex_exec_client as codex

REPOSITORY = Path(__file__).resolve().parents[2]
V14_CONTRACT = REPOSITORY / "configs/housing_lemons_price_confirmatory_v14_gpt6_luna.json"


def _pin(provider: str, model: str, prices: tuple[float, float, float], pricing_id: str) -> OpenRouterRoutePin:
    """The CLI's list price in the shape the Housing runner seals a price in. It names no OpenRouter endpoint."""
    return OpenRouterRoutePin(provider=provider, quantization="not_applicable", canonical_model=model,
                              input_per_million=prices[0], cached_input_per_million=prices[1],
                              output_per_million=prices[2], pricing_id=pricing_id)


#: Both CLIs run on a subscription login: a cost is the list price of the tokens, not a charge.
SUBJECTS: dict[str, dict[str, Any]] = {
    "claude_fable51": {
        "provider": "claude_code", "model": "claude-fable-5-1",
        "pin": _pin("claude_code_cli", "claude-fable-5-1", (10.0, 0.25, 50.0), "anthropic_list_2026-09-15_claude-fable-5-1"),
        "cell_ceiling_usd": 4.0, "total_ceiling_usd": {"gate": 8.0, "panel": 60.0},
    },
    "claude_opus55": {
        "provider": "claude_code", "model": "claude-opus-5-5",
        "pin": _pin("claude_code_cli", "claude-opus-5-5", (4.0, 0.20, 20.0), "anthropic_list_2026-09-22_claude-opus-5-5"),
        "cell_ceiling_usd": 2.0, "total_ceiling_usd": {"gate": 4.0, "panel": 30.0},
    },
    "codex_sol61": {
        "provider": codex.PROVIDER, "model": "gpt-6.1-sol",
        "pin": _pin("codex_cli", "gpt-6.1-sol", (2.0, 0.10, 10.0), "openai_list_2026-10-04_gpt-6.1-sol"),
        "cell_ceiling_usd": 1.0, "total_ceiling_usd": {"gate": 2.0, "panel": 15.0},
    },
}
#: The first worlds of the v14 main pack, in seed order: declared here, not chosen from results.
PANELS = {"gate": pc.PACK["main"]["world_seeds"][:1], "panel": pc.PACK["main"]["world_seeds"][:20]}
MAX_PARALLEL_CELLS = 3
TRANSPORT_KEYS = ("provider_metadata", "request_seed_source", "request_seed_base", "retry_backoff",
                  "retry_base_seconds", "retry_after_max_seconds", "max_output_tokens_ceiling")


def campaign_id(subject: str, panel: str) -> str:
    spec = SUBJECTS[subject]
    stem = f"housing_lemons_price_cli_v1_{spec['provider']}_{subject.split('_', 1)[1]}_outside"
    return f"{stem}_gate" if panel == "gate" else f"{stem}_w{len(PANELS[panel])}"


def register(subject: str, panel: str) -> str:
    """Make the identity known to ``price_campaign`` for this process; the module itself is not edited."""
    spec, name = SUBJECTS[subject], campaign_id(subject, panel)
    route_id = f"cli_{subject}"
    pc.ROUTES[route_id] = (spec["model"], spec["pin"])
    pc.IDENTITIES[name] = {
        **pc._V14, "retry_policy_version": 1, "max_action_attempts": 1, "route_id": route_id,
        "profile": f"housing_price_{subject}_tenant_cli_v1", "reasoning_effort": "low",
        "temperature": "unavailable", "top_p": None, "world_seeds": list(PANELS[panel]),
        "total_cost_ceiling_usd": spec["total_ceiling_usd"][panel],
        "claim_status": "development_gate" if panel == "gate" else "development_pilot",
    }
    return name


def build_contract(subject: str, panel: str, runtime: Mapping[str, str]) -> dict[str, Any]:
    spec, name = SUBJECTS[subject], register(subject, panel)
    v14 = json.loads(V14_CONTRACT.read_text())
    return {
        "schema_version": "aeread.housing_price_cli_probe/1",
        "campaign_id": name,
        "claim_status": pc.IDENTITIES[name]["claim_status"],
        "route": {**pc._route_block(f"cli_{subject}"), "transport": "one CLI subprocess per action; no OpenRouter",
                  "billing": "subscription login; cost is the list price of the tokens, not a charge"},
        "provider_runtime": dict(runtime),
        "world_seeds": list(PANELS[panel]),
        "arms": v14["arms"], "replicates": 1, "rounds": v14["rounds"],
        "tenant_cost_ceiling_usd_per_cell": spec["cell_ceiling_usd"],
        "total_cost_ceiling_usd": spec["total_ceiling_usd"][panel],
        "max_consecutive_operational_failures": 3,
        "controls": {
            "harness": "minimal_chat/1.0",
            "tools": "none: Claude Code with --tools \"\"; Codex with its acting features disabled, and a call that uses a tool is refused",
            "memory": "disabled", "reasoning_effort": "low",
            "temperature": "unavailable", "top_p": None, "seed": "unavailable",
            "max_output_tokens": 32_000, "max_output_tokens_applied": "no: the CLI's own default",
            "timeout_seconds": 300.0, "sdk_retries": 0, "max_action_attempts": 1, "retryable_conditions": [],
            "halt_rule": "a failed cell is typed missingness and is not rerun; no new cell starts after "
                         "max_consecutive_operational_failures consecutive failed cells, after a cell over its ceiling, "
                         "or when the next cells could exceed the total ceiling",
            "max_parallel_cells": MAX_PARALLEL_CELLS,
            "tenant_inference_seed_base": v14["controls"]["tenant_inference_seed_base"],
            "tenant_inference_seed_applied": "no: kept so the plan has v14's structure; the profile seals seed null",
            "landlord_model": v14["controls"]["landlord_model"],
            "landlord_margin_usd": v14["controls"]["landlord_margin_usd"],
            "execution_order": v14["controls"]["execution_order"],
        },
        "rivals": v14["rivals"],
        "analysis": {
            "independent_unit": "world_seed",
            "primary_measure": v14["analysis"]["primary_measure"],
            "references": v14["analysis"]["references"],
            "compared_with": "the v14 confirmatory cells of the same worlds, paired by world; descriptive",
            "missingness": "report_separately", "model_ranking_allowed": False,
        },
    }


def cli_setup(contract: Mapping[str, Any], arm: str, subject: str, runtime: Mapping[str, str]) -> Any:
    spec = SUBJECTS[subject]
    setup = pc.build_setup(contract, arm, live=True)
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
    registry = HarnessRegistry()
    registry.register(MinimalChatHarness())
    inert = dict(native_tools=False, structured_output=True, seed=False, system_prompt=True,
                 reasoning_token_report=False, max_context_tokens=None)
    resolved = resolve_run_plan(
        families=plan.families, cases=plan.cases, suite=plan.suite, sampling=plan.sampling,
        evaluation_blocks=plan.evaluation_blocks, analysis=plan.analysis, agent_profiles=tuple(profiles),
        run_spec=plan.run_spec, registry=setup.registry, implementation_pins=plan.implementation_pins,
        harness_registry=registry,
        provider_capabilities={
            spec["provider"]: ProviderCapabilities(**{**inert, "reasoning_token_report": spec["provider"] == codex.PROVIDER},
                                                   reasoning_budget=True),
            "housing_scripted_landlord": ProviderCapabilities(**inert, reasoning_budget=False),
        },
    )
    return dataclasses.replace(setup, plan=resolved)


async def _claude_runner(arguments: tuple[str, ...], standard_input: bytes) -> tuple[int, bytes, bytes]:
    """Carry Claude Code's stated reason for a non-zero exit to where the adapter reads it (RN-T-06)."""
    returncode, stdout, stderr = await kernel_execution._run_subprocess(arguments, standard_input)
    if returncode != 0 and not stderr.strip():
        try:
            payload = json.loads(stdout)
            reason = f"{payload.get('result')} (api_error_status {payload.get('api_error_status')})"
        except (ValueError, AttributeError):
            reason = stdout.decode("utf-8", errors="replace")[-400:]
        stderr = reason.encode("utf-8")
    return returncode, stdout, stderr


async def discover(subject: str) -> Any:
    if SUBJECTS[subject]["provider"] == "claude_code":
        found = await ClaudeCodePrintClient.discover()
        return ClaudeCodePrintClient(executable=Path(shutil.which("claude")).resolve(),
                                     runtime_version=found.runtime_version, runtime_sha256=found.runtime_sha256,
                                     command_runner=_claude_runner)
    return await codex.CodexExecClient.discover()


async def run_cell(*, contract: Mapping[str, Any], setup: Any, seed: int, arm: str, results_root: Path,
                   provider: Any, provider_name: str, semaphore: asyncio.Semaphore) -> dict[str, Any]:
    """One cell as ``price_campaign.run`` writes it, so ``price_endpoint`` reads the row unchanged."""
    cell = next(item for item in setup.plan.cells if item.world_seed == seed and item.replicate_index == 0)
    result_path = results_root / f"world_{seed}__{arm}.json"
    evidence_root = results_root / f"world_{seed}__{arm}_evidence"
    try:
        async with semaphore:
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
        row = {"world_seed": seed, "arm": arm, "replicate_index": 0, "status": "completed",
               "cost_usd": execution.total_cost_usd, "receipt_sha256": receipt.receipt_sha256,
               "run_plan_id": setup.plan.run_plan_id, "cell_id": cell.cell_id,
               "tenant_net_total": outcome["tenant_net_total"],
               "price_rows": pc.price_rows(outcome, seed, arm),
               "outcome_facts": {key: outcome[key] for key in price_endpoint.OUTCOME_FACTS}}
    except Exception as error:  # noqa: BLE001 - a failed cell is a typed row, as in price_campaign.run
        failure_receipt = None
        try:
            failure_receipt = finalize_housing_failure(setup=setup, cell_id=cell.cell_id, evidence_root=evidence_root, error=error)
        except Exception:  # noqa: BLE001
            pass
        usage = _failure_usage(evidence_root=evidence_root, run_plan_id=setup.plan.run_plan_id, cell_id=cell.cell_id)
        row = {"world_seed": seed, "arm": arm, "replicate_index": 0, "status": "operational_failure",
               "failure_condition": getattr(error, "condition", type(error).__name__),
               "failure_message": str(error)[:400], "cost_usd": usage["cost_usd"],
               "receipt_sha256": failure_receipt.receipt_sha256 if failure_receipt else None}
    result_path.write_bytes(canonical_json_bytes(row) + b"\n")
    print(json.dumps({k: row.get(k) for k in ("world_seed", "arm", "status", "cost_usd", "tenant_net_total", "failure_condition")}), flush=True)
    return row


async def run(subject: str, panel: str, run_root: Path, *, resume: bool) -> dict[str, Any]:
    if "runs" not in run_root.resolve().parts:
        raise ValueError("--run-root must be under the ignored runs/ hierarchy")
    spec = SUBJECTS[subject]
    inner = await discover(subject)
    runtime = dict(inner.runtime_metadata)
    contract = build_contract(subject, panel, runtime)
    run_root.mkdir(parents=True, exist_ok=True)
    contract_path = run_root / "contract.json"
    if contract_path.exists():
        if canonical_json_bytes(json.loads(contract_path.read_text())) != canonical_json_bytes(contract):
            raise ValueError("run root belongs to a different contract")
        if not resume:
            raise FileExistsError("run root exists; pass --resume to continue")
    else:
        contract_path.write_bytes(canonical_json_bytes(contract) + b"\n")
    setups = {arm: cli_setup(contract, arm, subject, runtime) for arm in contract["arms"]}
    focal = codex.LoggedClient(inner, run_root / "cli_calls.jsonl", subject=subject)
    provider = pc.make_seat_router(pc.identity(contract), contract, focal, run_root / "seat_calls.jsonl")
    results_root = run_root / "live"
    results_root.mkdir(exist_ok=True)
    rows: list[dict[str, Any]] = []
    todo: list[tuple[int, str]] = []
    for seed in contract["world_seeds"]:
        for arm in contract["arms"]:
            path = results_root / f"world_{seed}__{arm}.json"
            if path.exists():
                rows.append(json.loads(path.read_text()))
            else:
                todo.append((seed, arm))
    semaphore = asyncio.Semaphore(MAX_PARALLEL_CELLS)
    halted = None
    stop_after = contract["max_consecutive_operational_failures"]
    for start in range(0, len(todo), MAX_PARALLEL_CELLS):
        wave = todo[start:start + MAX_PARALLEL_CELLS]
        spent = sum(float(row.get("cost_usd") or 0.0) for row in rows)
        tail = [row["status"] for row in rows][-stop_after:]
        if spent + spec["cell_ceiling_usd"] * len(wave) > contract["total_cost_ceiling_usd"]:
            halted = f"total cost ceiling: spent {spent:.4f} of {contract['total_cost_ceiling_usd']}"
        elif len(tail) == stop_after and all(status == "operational_failure" for status in tail):
            halted = "consecutive operational failures"
        elif any(not math.isfinite(float(row["cost_usd"])) or float(row["cost_usd"]) > spec["cell_ceiling_usd"] for row in rows):
            halted = "a cell exceeded its cost ceiling"
        if halted:
            rows.extend({"world_seed": seed, "arm": arm, "replicate_index": 0, "status": "not_attempted", "cost_usd": 0.0}
                        for seed, arm in todo[start:])
            break
        rows.extend(await asyncio.gather(*(
            run_cell(contract=contract, setup=setups[arm], seed=seed, arm=arm, results_root=results_root,
                     provider=provider, provider_name=spec["provider"], semaphore=semaphore)
            for seed, arm in wave)))
    summary = {**pc.summarize(rows, len(contract["world_seeds"]) * len(contract["arms"])), "halted": halted,
               "campaign_id": contract["campaign_id"], "run_plan_ids": {arm: s.plan.run_plan_id for arm, s in setups.items()}}
    (results_root / "summary.json").write_bytes(canonical_json_bytes(summary) + b"\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", choices=sorted(SUBJECTS), required=True)
    parser.add_argument("--panel", choices=sorted(PANELS), required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    arguments = parser.parse_args()
    if not arguments.execute:
        runtime = dict(asyncio.run(discover(arguments.subject)).runtime_metadata)
        contract = build_contract(arguments.subject, arguments.panel, runtime)
        setups = {arm: cli_setup(contract, arm, arguments.subject, runtime) for arm in contract["arms"]}
        tenant = next(p for p in setups["pooled"].plan.agent_profiles if p.model.provider == SUBJECTS[arguments.subject]["provider"])
        print(json.dumps({"campaign_id": contract["campaign_id"], "worlds": len(contract["world_seeds"]),
                          "run_plan_ids": {arm: s.plan.run_plan_id for arm, s in setups.items()},
                          "tenant_profile": json.loads(canonical_json_bytes(tenant)) | {"harness": "(omitted)"}}, indent=1, sort_keys=True))
        return 0
    summary = asyncio.run(run(arguments.subject, arguments.panel, arguments.run_root, resume=arguments.resume))
    print(json.dumps({k: v for k, v in summary.items() if k != "cells"}, sort_keys=True)[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
