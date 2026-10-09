"""The procurement inference panel played by a CLI subject (Claude Code, Codex).

Same eighteen worlds, same prompt and same reasoning condition as the four
development runs on the panel (``inference_v1_gemini`` and the others); only
the model block and its transport differ. One subprocess per action through
the kernel's ``ClaudeCodePrintClient`` or ``codex_exec_client.CodexExecClient``,
both without tools.

What a CLI cannot do is declared, not papered over: it takes no seed, no
temperature and no output cap, so the profile seals ``seed: null`` and
``sampling_controls: unavailable``, and a replicate is an ordinal. The result
rows keep the field name ``inference_seed`` for the ordinal so the family's
summary and publisher read them unchanged.

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/procurement_cli.py \
        --subject claude_fable51 --panel gate --run-root <runs/...> --execute
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.model_call.harness import MinimalChatHarness, default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import canonical_json_bytes, resolve_run_plan
from aeread.shared_runner.schemas import AgentProfile, RunSpec
from aeread.shared_runner.task.execution import ClaudeCodePrintClient, TokenPricing, execute_plan_cell
from aeread_families.procurement_allocation import model_campaign as mc
from aeread_families.procurement_allocation import runner
from aeread_families.procurement_allocation import inference_v2_case_matrix as inference_v2
from aeread_families.procurement_allocation import inference_v2_prompt
from aeread_families.procurement_allocation.strategy_scaffold import PROMPT_ID, STRATEGY_PROMPT, TREATMENT_ID

import codex_exec_client as codex

REPOSITORY = Path(__file__).resolve().parents[2]
CASE_ROOT = REPOSITORY / "cases/procurement_allocation_v1/inference_v1/labeled"
#: The world the gate plays: the first of the panel in file order.
GATE_WORLD = "lead_time_long_is_good__capacity"

#: A pack is a set of worlds; a prompt is what the buyer is told. The first runs
#: were ``inference_v1`` under ``scaffold_v3`` and their identities carry neither
#: name. Any other pairing names both, so a changed control is a new identity.
PACKS: dict[str, dict[str, Any]] = {
    "inference_v1": {"paths": lambda: sorted(CASE_ROOT.glob("*.json")), "gate_world": GATE_WORLD},
    # The gate plays a world whose cheapest unrecorded listing is a bad supplier.
    "inference_v2": {"paths": lambda: list(inference_v2.case_paths()), "gate_world": "moq_high_is_good__timing"},
}
PROMPTS: dict[str, dict[str, str]] = {
    "scaffold_v3": {"prompt_id": PROMPT_ID, "text": STRATEGY_PROMPT, "treatment_id": TREATMENT_ID},
    "neutral_v1": {"prompt_id": inference_v2_prompt.PROMPT_ID, "text": inference_v2_prompt.NEUTRAL_PROMPT,
                   "treatment_id": inference_v2_prompt.TREATMENT_ID},
}
DEFAULT_ARM = ("inference_v1", "scaffold_v3")

#: List prices, used as the sealed price of a call. Both CLIs here run on a
#: subscription login, so nothing is charged per call: Claude Code reports a
#: list-price cost itself, Codex reports none and the kernel prices its tokens.
SUBJECTS: dict[str, dict[str, Any]] = {
    "claude_fable51": {
        "provider": "claude_code", "model": "claude-fable-5-1",
        "profile_id": "procurement_claude_code_fable51_v1",
        "pricing": TokenPricing(10.0, 0.25, 50.0, "anthropic_list_2026-09-15_claude-fable-5-1"),
        # The Opus 5.5 gate cost $0.41 at list for nine actions; Fable's prices are 2.5 times Opus's,
        # so a panel of eighteen is about $18 at list. The first gate identity holds one refused
        # cell (CLI-O-01) and is never rerun, so the next gate is v2.
        "max_cost_usd_per_trajectory": 2.0, "total_cost_ceiling_usd": {"gate": 2.0, "panel": 25.0},
        "gate_version": 2,
    },
    # The same Claude Code route on the model the login could reach when Fable 5.1 could not
    # (CLI-O-01). First a one-world check that the route works; then, on the owner's word of
    # 2026-10-08, the panel. The gate cost $0.41 at list for nine actions, so eighteen worlds are
    # about $7.40 and the ceiling leaves room for a wave of three at the per-trajectory limit.
    "claude_opus55": {
        "provider": "claude_code", "model": "claude-opus-5-5",
        "profile_id": "procurement_claude_code_opus55_v1",
        "pricing": TokenPricing(4.0, 0.20, 20.0, "anthropic_list_2026-09-22_claude-opus-5-5"),
        "max_cost_usd_per_trajectory": 1.0, "total_cost_ceiling_usd": {"gate": 1.0, "panel": 12.0},
    },
    "codex_sol61": {
        "provider": codex.PROVIDER, "model": "gpt-6.1-sol",
        "profile_id": "procurement_codex_cli_sol61_v1",
        "pricing": TokenPricing(2.0, 0.10, 10.0, "openai_list_2026-10-04_gpt-6.1-sol"),
        "max_cost_usd_per_trajectory": 1.0, "total_cost_ceiling_usd": {"gate": 1.0, "panel": 8.0},
    },
}
CONTROLS = {
    "reasoning_effort": "low", "timeout_seconds": 300.0, "max_logical_actions": 10,
    "max_action_attempts": 1, "replicates": 1, "max_parallel_cells": 3,
    "max_consecutive_operational_failures": 3,
}


def campaign_id(subject: str, panel: str, pack: str = DEFAULT_ARM[0], prompt: str = DEFAULT_ARM[1]) -> str:
    who = f"{SUBJECTS[subject]['provider']}_{subject.split('_', 1)[1]}"
    if (pack, prompt) == DEFAULT_ARM:
        stem = f"procurement_allocation_inference_v1_{who}"
        return f"{stem}_gate_v{SUBJECTS[subject].get('gate_version', 1)}" if panel == "gate" else f"{stem}_v1"
    stem = f"procurement_allocation_{pack}_{prompt.split('_', 1)[0]}_{who}"
    return f"{stem}_gate_v1" if panel == "gate" else f"{stem}_v1"


def case_paths(panel: str, pack: str = DEFAULT_ARM[0]) -> list[Path]:
    paths = PACKS[pack]["paths"]()
    return [p for p in paths if p.stem == PACKS[pack]["gate_world"]] if panel == "gate" else paths


async def _claude_runner(arguments: tuple[str, ...], standard_input: bytes) -> tuple[int, bytes, bytes]:
    """The kernel's subprocess runner, with the CLI's own reason carried to where the adapter reads it.

    On a non-zero exit the adapter reports standard error, and Claude Code puts the reason in the
    JSON on standard output (RN-T-06). This copies it across so a refused cell says why.
    """
    returncode, stdout, stderr = await execution_module._run_subprocess(arguments, standard_input)
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
        return ClaudeCodePrintClient(
            executable=Path(shutil.which("claude")).resolve(), runtime_version=found.runtime_version,
            runtime_sha256=found.runtime_sha256, command_runner=_claude_runner,
        )
    return await codex.CodexExecClient.discover()


def build_setup(subject: str, case_path: Path, runtime: Mapping[str, str],
                prompt: str = DEFAULT_ARM[1]) -> runner.ProcurementAllocationSetup:
    """``runner.build_openrouter_setup`` with a CLI model block instead of an OpenRouter route."""
    spec = SUBJECTS[subject]
    told = PROMPTS[prompt]
    template = runner.build_offline_setup(case_path=case_path, prompt=told["text"], prompt_id=told["prompt_id"])
    harness = MinimalChatHarness()
    runtime_id = "aeread.shared_runner.task.execution"
    profile_id = f"{spec['profile_id']}_procurement_allocation"
    pricing: TokenPricing = spec["pricing"]
    profile = AgentProfile.from_dict(
        {
            "spec_version": AgentProfile.SPEC_VERSION,
            "profile_id": profile_id,
            "model": {"provider": spec["provider"], "model": spec["model"], "revision": spec["model"], "base_url": None},
            "harness": {
                "id": harness.id, "version": harness.version,
                "config": {
                    "pricing_id": pricing.pricing_id,
                    "pricing_sha256": pricing.content_sha256(),
                    "output_schema": runner.procurement_action_output_schema(),
                    "provider_runtime": dict(runtime),
                    "sampling_controls": {"temperature": "unavailable", "max_output_tokens": "provider_model_default"},
                },
            },
            "prompt": {"prompt_id": told["prompt_id"], "sha256": hashlib.sha256(told["text"].encode("utf-8")).hexdigest()},
            "runtime": {"kind": "python", "implementation": runtime_id, "version": "0.1.0"},
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": f"reasoning_{CONTROLS['reasoning_effort']}_v1", "effort": CONTROLS["reasoning_effort"],
                "token_budget": None, "rationale_visibility": "hidden",
            },
            "sampling": {"temperature": 0.0, "max_output_tokens": 32_000, "seed": None, "top_p": None},
            "budgets": {
                "max_logical_actions": CONTROLS["max_logical_actions"],
                "timeout_seconds": CONTROLS["timeout_seconds"],
                "max_cost_usd": spec["max_cost_usd_per_trajectory"],
            },
            "retry_policy": {"max_action_attempts": CONTROLS["max_action_attempts"], "retryable_conditions": [],
                             "session_mode": "restart", "sdk_retries": 0},
        }
    )
    run_spec = RunSpec.from_dict(
        {
            "spec_version": RunSpec.SPEC_VERSION,
            "run_spec_id": f"procurement_allocation_cli_{profile_id}",
            "suite_id": template.plan.suite.suite_id,
            "evaluation_block_ids": [block.block_id for block in template.plan.evaluation_blocks],
            "agent_profile_ids": [profile_id],
            "seat_assignments": {"buyer": profile_id},
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    harness_registry = HarnessRegistry()
    for item in default_harnesses().values():
        harness_registry.register(item)
    source = Path(execution_module.__file__)
    pins = [pin for pin in template.plan.implementation_pins if pin.kind not in {"harness", "runtime"}]
    pins += [runner._pin(harness.id, "harness", source, version=harness.version),
             runner._pin(runtime_id, "runtime", source, version="0.1.0")]
    plan = resolve_run_plan(
        families=template.plan.families, cases=template.plan.cases, suite=template.plan.suite,
        sampling=template.plan.sampling, evaluation_blocks=template.plan.evaluation_blocks,
        analysis=template.plan.analysis, agent_profiles=(profile,), run_spec=run_spec,
        registry=template.registry, implementation_pins=tuple(pins), harness_registry=harness_registry,
        provider_capabilities={
            spec["provider"]: ProviderCapabilities(
                native_tools=False, structured_output=True, seed=False, system_prompt=True,
                reasoning_budget=True, reasoning_token_report=spec["provider"] == codex.PROVIDER,
                max_context_tokens=None,
            )
        },
    )
    return runner.ProcurementAllocationSetup(
        plan=plan, registry=template.registry, prompt_sources=template.prompt_sources,
        pricing={spec["model"]: pricing}, case=template.case,
        harnesses={**default_harnesses(), f"{harness.id}/{harness.version}": harness},
    )


def model_plan(subject: str, panel: str, runtime: Mapping[str, str],
               pack: str = DEFAULT_ARM[0], prompt: str = DEFAULT_ARM[1]) -> dict[str, Any]:
    spec = SUBJECTS[subject]
    told = PROMPTS[prompt]
    cases = mc._case_records(case_paths(panel, pack))
    plan = {
        "schema_version": "aeread.procurement_allocation_cli_plan/0.1",
        "campaign_id": campaign_id(subject, panel, pack, prompt),
        "claim_status": "development_gate" if panel == "gate" else "development_pilot",
        "cases": [{"case_id": r["case_id"], "content_sha256": r["content_sha256"]} for r in cases],
        "independent_case_count": len(cases),
        "inference_seeds": list(range(CONTROLS["replicates"])),
        "inference_seed_meaning": "replicate ordinal; the CLI accepts no seed and the profile seals seed null",
        "planned_trajectory_count": len(cases) * CONTROLS["replicates"],
        "model": spec["model"], "revision": spec["model"], "provider": spec["provider"],
        "provider_runtime": dict(runtime),
        "billing": "subscription login; cost is the list price of the tokens, not a charge",
        "pricing_id": spec["pricing"].pricing_id,
        "prompt": {"prompt_id": told["prompt_id"], "sha256": hashlib.sha256(told["text"].encode("utf-8")).hexdigest(),
                   "treatment_id": told["treatment_id"]},
        "harness": "minimal_chat/1.0 (fixed transport; not an estimand)",
        "tools": "none: Claude Code with --tools \"\"; Codex with its acting features disabled, and a call that uses a tool is refused",
        "controls": {**CONTROLS, "temperature": "unavailable", "seed": "unavailable", "max_output_tokens": "provider default",
                     "max_cost_usd_per_trajectory": spec["max_cost_usd_per_trajectory"],
                     "total_cost_ceiling_usd": spec["total_cost_ceiling_usd"][panel],
                     "halt_rule": "a failed cell is typed missingness and is not rerun; the run stops launching cells after "
                                  "max_consecutive_operational_failures consecutive failed cells or when the next cell could exceed the total ceiling"},
        "retry_policy": "one sealed attempt per action; no retries",
        "response_cache": "disabled",
        "primary_outcomes": ["feasible", "feasible_award", "completed_kits", "contribution_margin_usd",
                             "regret_to_upper_bound_usd", "violations"],
        "claim_scope": "development probe of a CLI subject on declared cases; one replicate a world, no model ranking",
    }
    if (pack, prompt) != DEFAULT_ARM:
        # The first runs' plans carry neither key and stay as they were written.
        plan["pack"], plan["prompt_arm"] = pack, prompt
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return plan


async def run_cell(*, subject: str, run_root: Path, case_path: Path, replicate: int, client: Any,
                   runtime: Mapping[str, str], semaphore: asyncio.Semaphore,
                   prompt: str = DEFAULT_ARM[1]) -> dict[str, Any]:
    """``model_campaign._run_cell`` for a CLI provider; the row has the same fields."""
    setup = build_setup(subject, case_path, runtime, prompt)
    cell = setup.plan.cells[0]
    directory = mc._safe_case_directory(setup.case.case_id, setup.case.content_sha256)
    evidence_root = run_root / "executions" / directory / f"seed_{replicate}"
    started = time.perf_counter()
    failed = False
    try:
        async with semaphore:
            execution = await execute_plan_cell(
                plan=setup.plan, cell_id=cell.cell_id, registry=setup.registry, evidence_root=evidence_root,
                prompt_sources=setup.prompt_sources, providers={SUBJECTS[subject]["provider"]: client},
                pricing=setup.pricing, harnesses=setup.harnesses,
            )
        receipt = runner.finalize_procurement_allocation_execution(setup=setup, execution=execution)
        replayed = runner.replay_procurement_allocation_receipt(setup=setup, receipt=receipt, evidence_root=evidence_root)
        if canonical_json_bytes(replayed) != canonical_json_bytes(receipt):
            raise RuntimeError("replayed receipt differs from the live receipt")
        execution.evidence.audit_reconciliation()
        calls = [call for action in execution.action_executions for attempt in action.attempts
                 for call in attempt.provider_calls]
        retries = Counter(str(attempt.retry_reason) for action in execution.action_executions
                          for attempt in action.attempts if attempt.retry_reason is not None)
        outcome = json.loads(canonical_json_bytes(execution.episode_result.outcome))
        row: dict[str, Any] = {
            "case_id": setup.case.case_id, "case_content_sha256": setup.case.content_sha256,
            "inference_seed": replicate, "status": "completed",
            "decision": outcome["decision"], "termination_reason": outcome["termination_reason"],
            "feasible": bool(outcome["feasible"]), "feasible_award": bool(outcome.get("feasible_award", False)),
            "completed_kits": int(outcome["completed_kits"]),
            "contribution_margin_usd": float(outcome["contribution_margin_usd"]),
            "upper_bound_usd": float(outcome["upper_bound_usd"]),
            "regret_to_upper_bound_usd": float(outcome["regret_to_upper_bound_usd"]),
            "violations": list(outcome["violations"]),
            "elapsed_environment_days": int(outcome["elapsed_days"]),
            "action_count": len(execution.action_executions),
            "action_trace": mc._public_action_trace(execution),
            "elapsed_seconds": time.perf_counter() - started,
            "input_tokens": sum(call.input_tokens for call in calls),
            "cached_input_tokens": sum(call.cached_input_tokens for call in calls),
            "output_tokens": sum(call.output_tokens for call in calls),
            "cost_usd": execution.total_cost_usd,
            "cost_accounting": "list price of the tokens; subscription login, nothing charged per call",
            "resolved_models": sorted({call.resolved_model for call in calls if call.resolved_model is not None}),
            "receipt_sha256": receipt.receipt_sha256, "receipt_replayed": True, "replay_level": receipt.replay_level,
            "provider_call_count": len(calls), "runner_retry_count": sum(retries.values()),
            "retry_condition_counts": dict(sorted(retries.items())),
        }
    except Exception as error:  # noqa: BLE001 - a failed cell is a typed row, as in model_campaign
        failure_sha = None
        try:
            failure_sha = runner.finalize_procurement_allocation_failure(
                setup=setup, cell_id=cell.cell_id, evidence_root=evidence_root, error=error).receipt_sha256
        except Exception:  # noqa: BLE001
            pass
        row = {"case_id": setup.case.case_id, "case_content_sha256": setup.case.content_sha256,
               "inference_seed": replicate, "status": "operational_failure",
               "elapsed_seconds": time.perf_counter() - started, "failure_receipt_sha256": failure_sha,
               **mc._failure_summary(error)}
        failed = True
    if failed:
        row.update(mc._sealed_failure_telemetry(evidence_root))
    row["result_sha256"] = hashlib.sha256(canonical_json_bytes(dict(row))).hexdigest()
    mc._atomic_write_json(mc._result_path(run_root, case_id=setup.case.case_id,
                                          content_sha256=setup.case.content_sha256, seed=replicate), row)
    return row


async def run(subject: str, panel: str, run_root: Path, *, resume: bool,
              pack: str = DEFAULT_ARM[0], prompt: str = DEFAULT_ARM[1]) -> dict[str, Any]:
    mc._validate_operational_run_root(run_root)
    if pack == "inference_v2" and prompt != "neutral_v1":
        raise ValueError("inference_v2 is played under the neutral prompt; its facts are what the pack assumes")
    inner = await discover(subject)
    runtime = dict(inner.runtime_metadata)
    plan = model_plan(subject, panel, runtime, pack, prompt)
    run_root.mkdir(parents=True, exist_ok=True)
    plan_path = run_root / "model_plan.json"
    if plan_path.exists():
        if canonical_json_bytes(json.loads(plan_path.read_text())) != canonical_json_bytes(plan):
            raise ValueError("existing model plan does not match this invocation")
        if not resume:
            raise FileExistsError("run root exists; pass --resume to continue")
    else:
        mc._atomic_write_json(plan_path, plan)
    client = codex.LoggedClient(inner, run_root / "cli_calls.jsonl", subject=subject)
    records = mc._case_records(case_paths(panel, pack))
    rows: list[dict[str, Any]] = []
    todo: list[tuple[Path, int]] = []
    for record in records:
        for replicate in range(CONTROLS["replicates"]):
            path = mc._result_path(run_root, case_id=record["case_id"], content_sha256=record["content_sha256"], seed=replicate)
            if path.exists():
                rows.append(json.loads(path.read_text()))
            else:
                todo.append((record["path"], replicate))
    semaphore = asyncio.Semaphore(CONTROLS["max_parallel_cells"])
    ceiling = SUBJECTS[subject]["total_cost_ceiling_usd"][panel]
    per_cell = SUBJECTS[subject]["max_cost_usd_per_trajectory"]
    width = CONTROLS["max_parallel_cells"]
    halted = None
    # Cells go in waves the size of the parallelism, so the two stop rules are
    # checked between waves on rows that exist.
    for start in range(0, len(todo), width):
        spent = sum(float(row.get("cost_usd") or 0.0) for row in rows)
        if spent + per_cell * min(width, len(todo) - start) > ceiling:
            halted = f"total cost ceiling: spent {spent:.4f} of {ceiling}"
            break
        tail = [row.get("status") for row in rows][-CONTROLS["max_consecutive_operational_failures"]:]
        if len(tail) == CONTROLS["max_consecutive_operational_failures"] and all(s == "operational_failure" for s in tail):
            halted = "consecutive operational failures"
            break
        rows.extend(await asyncio.gather(*(
            run_cell(subject=subject, run_root=run_root, case_path=case_path, replicate=replicate,
                     client=client, runtime=runtime, semaphore=semaphore, prompt=prompt)
            for case_path, replicate in todo[start:start + width])))
    rows.sort(key=lambda row: (str(row["case_id"]), int(row["inference_seed"])))
    summary = mc.summarize_rows(rows, planned_trajectory_count=plan["planned_trajectory_count"],
                                independent_case_count=plan["independent_case_count"])
    artifact = {"schema_version": "aeread.procurement_allocation_cli_qualification/0.1", "plan": plan,
                "preflight": {"runtime": runtime}, "halted": halted, "summary": summary, "rows": rows}
    artifact["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(artifact)).hexdigest()
    mc._atomic_write_json(run_root / "summary.json", artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", choices=sorted(SUBJECTS), required=True)
    parser.add_argument("--panel", choices=("gate", "panel"), required=True)
    parser.add_argument("--pack", choices=sorted(PACKS), default=DEFAULT_ARM[0])
    parser.add_argument("--prompt", choices=sorted(PROMPTS), default=DEFAULT_ARM[1])
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    arguments = parser.parse_args()
    if not arguments.execute:
        runtime = dict(asyncio.run(discover(arguments.subject)).runtime_metadata)
        print(json.dumps(model_plan(arguments.subject, arguments.panel, runtime, arguments.pack, arguments.prompt),
                         indent=2, sort_keys=True))
        return 0
    artifact = asyncio.run(run(arguments.subject, arguments.panel, arguments.run_root, resume=arguments.resume,
                               pack=arguments.pack, prompt=arguments.prompt))
    rows = artifact["rows"]
    print(json.dumps({"campaign_id": artifact["plan"]["campaign_id"], "halted": artifact["halted"],
                      "rows": [{k: row.get(k) for k in ("case_id", "status", "decision", "regret_to_upper_bound_usd",
                                                        "action_count", "cost_usd", "elapsed_seconds", "failure_condition", "error_type")}
                               for row in rows]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
