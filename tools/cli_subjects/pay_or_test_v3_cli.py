"""Pay or test version 3's pilot played by isolated CLI subjects (development, no claim).

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/pay_or_test_v3_cli.py \\
        --subject claude_opus55 --run-root runs/procurement_allocation/pay_or_test_v3_pilot_cli_opus55 --execute

Declared in ``docs/families/procurement-allocation/pay_or_test_v3_plan.md``. Like ``pay_or_test_v2_cli``, this changes
nothing in ``procurement_cli.py`` (whose bytes earlier plans seal): it adds the version 3 pilot pack and brief to that
driver's tables, sets two plays a world, and rebinds two of its names for this process only, because version 3 is a new
plugin: ``build_setup`` builds the kernel plan from ``pay_or_test_v3_runner`` with version 3's action schema, and a
failed cell is sealed under version 3's leaf. Both CLIs run through ``cli_isolation``; each CLI's context is probed
before any world and the run refuses on any violation.

The plan resolves only once the kernel trusts the version 3 plugin; until then every cell fails at setup, before any
call is made.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import types
from pathlib import Path

import cli_isolation as iso
import procurement_cli as base
from aeread.shared_runner.model_call.harness import MinimalChatHarness, default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import canonical_json_bytes, resolve_run_plan
from aeread.shared_runner.schemas import AgentProfile, RunSpec
import aeread.shared_runner.task.execution as execution_module
from aeread_families.procurement_allocation import pay_or_test_v3_case_matrix as v3
from aeread_families.procurement_allocation import pay_or_test_v3_prompt
from aeread_families.procurement_allocation import pay_or_test_v3_runner as v3_runner
from aeread_families.procurement_allocation import runner as v1_runner
from aeread_families.procurement_allocation.pay_or_test_v3_environment import action_output_schema

PACK, PROMPT = v3.PILOT_PACK_ID, "v3_brief_v1"
REPLICATES = 2
base.PACKS[PACK] = {
    "paths": lambda: list(v3.case_paths()),
    "gate_world": "myopic_pays__1",
    "prompts": (PROMPT,),
    "total_cost_ceiling_usd": {"claude_opus55": {"gate": 1.0, "panel": 15.0}, "codex_sol61": {"gate": 1.0, "panel": 10.0}},
}
base.PROMPTS[PROMPT] = {"prompt_id": pay_or_test_v3_prompt.PROMPT_ID, "text": pay_or_test_v3_prompt.PAY_OR_TEST_V3_PROMPT,
                        "treatment_id": pay_or_test_v3_prompt.TREATMENT_ID}
base.CONTROLS["replicates"] = REPLICATES


def build_setup(subject: str, case_path: Path, runtime, prompt: str = PROMPT) -> v1_runner.ProcurementAllocationSetup:
    """``procurement_cli.build_setup`` on version 3's plan and action schema."""
    spec = base.SUBJECTS[subject]
    told = base.PROMPTS[prompt]
    template = v3_runner.build_offline_setup(case_path=case_path, prompt=told["text"], prompt_id=told["prompt_id"])
    harness = MinimalChatHarness()
    runtime_id = "aeread.shared_runner.task.execution"
    profile_id = f"{spec['profile_id']}_procurement_pay_or_test_v3"
    pricing = spec["pricing"]
    controls = base.CONTROLS
    profile = AgentProfile.from_dict({
        "spec_version": AgentProfile.SPEC_VERSION, "profile_id": profile_id,
        "model": {"provider": spec["provider"], "model": spec["model"], "revision": spec["model"], "base_url": None},
        "harness": {"id": harness.id, "version": harness.version, "config": {
            "pricing_id": pricing.pricing_id, "pricing_sha256": pricing.content_sha256(),
            "output_schema": action_output_schema(), "provider_runtime": dict(runtime),
            "sampling_controls": {"temperature": "unavailable", "max_output_tokens": "provider_model_default"}}},
        "prompt": {"prompt_id": told["prompt_id"], "sha256": hashlib.sha256(told["text"].encode("utf-8")).hexdigest()},
        "runtime": {"kind": "python", "implementation": runtime_id, "version": "0.1.0"},
        "tools": [], "memory": {"mode": "disabled"},
        "reasoning": {"condition_id": f"reasoning_{controls['reasoning_effort']}_v1", "effort": controls["reasoning_effort"],
                      "token_budget": None, "rationale_visibility": "hidden"},
        "sampling": {"temperature": 0.0, "max_output_tokens": 32_000, "seed": None, "top_p": None},
        "budgets": {"max_logical_actions": controls["max_logical_actions"], "timeout_seconds": controls["timeout_seconds"],
                    "max_cost_usd": spec["max_cost_usd_per_trajectory"]},
        "retry_policy": {"max_action_attempts": controls["max_action_attempts"], "retryable_conditions": [],
                         "session_mode": "restart", "sdk_retries": 0},
    })
    run_spec = RunSpec.from_dict({
        "spec_version": RunSpec.SPEC_VERSION, "run_spec_id": f"procurement_pay_or_test_v3_cli_{profile_id}",
        "suite_id": template.plan.suite.suite_id,
        "evaluation_block_ids": [block.block_id for block in template.plan.evaluation_blocks],
        "agent_profile_ids": [profile_id], "seat_assignments": {"buyer": profile_id}, "execution_mode": "evaluate",
        "replicate_override": None, "budget_overrides": None,
    })
    harness_registry = HarnessRegistry()
    for item in default_harnesses().values():
        harness_registry.register(item)
    source = Path(execution_module.__file__)
    pins = [pin for pin in template.plan.implementation_pins if pin.kind not in {"harness", "runtime"}]
    pins += [v1_runner._pin(harness.id, "harness", source, version=harness.version),
             v1_runner._pin(runtime_id, "runtime", source, version="0.1.0")]
    plan = resolve_run_plan(
        families=template.plan.families, cases=template.plan.cases, suite=template.plan.suite,
        sampling=template.plan.sampling, evaluation_blocks=template.plan.evaluation_blocks,
        analysis=template.plan.analysis, agent_profiles=(profile,), run_spec=run_spec, registry=template.registry,
        implementation_pins=tuple(pins), harness_registry=harness_registry,
        provider_capabilities={spec["provider"]: ProviderCapabilities(
            native_tools=False, structured_output=True, seed=False, system_prompt=True, reasoning_budget=True,
            reasoning_token_report=spec["provider"] == base.codex.PROVIDER, max_context_tokens=None)},
    )
    return v1_runner.ProcurementAllocationSetup(
        plan=plan, registry=template.registry, prompt_sources=template.prompt_sources,
        pricing={spec["model"]: pricing}, case=template.case,
        harnesses={**default_harnesses(), f"{harness.id}/{harness.version}": harness},
    )


base.build_setup = build_setup
base.runner = types.SimpleNamespace(**{name: getattr(v1_runner, name) for name in dir(v1_runner) if not name.startswith("__")})
base.runner.finalize_procurement_allocation_failure = v3_runner.finalize_failure
_model_plan = base.model_plan


def model_plan(subject, panel, runtime, pack=PACK, prompt=PROMPT):
    """The base plan, with its scope stating two plays a world."""
    plan = dict(_model_plan(subject, panel, runtime, pack, prompt))
    plan.pop("plan_sha256")
    plan["claim_scope"] = ("development pilot of a CLI subject on declared cases; two plays a world, sizing a later "
                           "declared run, no model ranking")
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return plan


base.model_plan = model_plan


async def _isolated_claude_runner(arguments, standard_input):
    returncode, stdout, stderr = await iso.isolated_command_runner(arguments, standard_input)
    if returncode != 0 and not stderr.strip():
        try:
            payload = json.loads(stdout)
            stderr = f"{payload.get('result')} (api_error_status {payload.get('api_error_status')})".encode("utf-8")
        except (ValueError, AttributeError):
            stderr = stdout[-400:]
    return returncode, stdout, stderr


base._claude_runner = _isolated_claude_runner
iso.install_codex_isolation()


async def probe(subject: str) -> dict:
    client = await base.discover(subject)
    if base.SUBJECTS[subject]["provider"] == "claude_code":
        found = await iso.probe_claude(client, client._executable, model=base.SUBJECTS[subject]["model"],
                                       reasoning_effort=base.CONTROLS["reasoning_effort"], runner=_isolated_claude_runner)
    else:
        found = await iso.probe_codex(client, model=base.SUBJECTS[subject]["model"],
                                      reasoning_effort=base.CONTROLS["reasoning_effort"])
    return {"probe": found, "violations": iso.isolation_violations(found), "declaration": dict(iso.DECLARATION)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--subject", choices=("claude_opus55", "codex_sol61"), required=True)
    parser.add_argument("--panel", choices=("gate", "panel"), default="panel")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps(model_plan(args.subject, args.panel, {"runtime_version": "plan-only"}), indent=1, default=str)[:2000])
        return 0
    found = asyncio.run(probe(args.subject))
    args.run_root.mkdir(parents=True, exist_ok=True)
    (args.run_root / "isolation_probe.json").write_text(json.dumps(found, indent=1, default=str))
    if found["violations"]:
        print(f"isolation probe refuses the run: {found['violations']}", file=sys.stderr)
        return 2
    artifact = asyncio.run(base.run(args.subject, args.panel, args.run_root, resume=args.resume, pack=PACK, prompt=PROMPT))
    print(json.dumps({"halted": artifact["halted"], "summary": {k: artifact["summary"].get(k) for k in
                                                                ("completed_trajectories", "planned_trajectory_count")}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
