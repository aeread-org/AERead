"""Pay or test version 3's declared worlds played by hosted flash models through OpenRouter.

Declared in ``docs/families/procurement-allocation/pay_or_test_v3_flash_plan.md``. Gemini 3.8 Flash and GPT-6 Luna play
the 20 worlds of the v3 confirmatory pack (``pay_or_test_v3_confirm``), twice each (request seeds 87001 and 87002), under
the v3 brief Sol and Opus played. Written from ``pay_or_test_v2_openrouter.py`` (unedited); what it changes:

- the plan: ``pay_or_test_v3_runner.build_offline_setup`` (the version 3 plugin), and a failed cell sealed under the
  version 3 leaf;
- the action schema (``action_output_schema``): version 3's actions, tightened as version 1's OpenRouter schema is, so
  that what it admits the parser accepts, but for ``SCHEMA_RESIDUAL``;
- the identities, the seeds and the ceilings.

Every other control is version 1's and imported from it: the route pins (each with only its profile id changed), the
credit floor and the catalog check before any run root exists, the retry policy, $0.30 a cell and the halt rule.

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/pay_or_test_v3_openrouter.py --subject gemini38_flash
    ... --subject gemini38_flash --probe --env-file <AERead>/.env      # one strict call
    ... --subject gemini38_flash --execute --env-file <AERead>/.env
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import dataclasses
import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping

import pay_or_test_openrouter as v1
from aeread.shared_runner.model_call.harness import MinimalChatHarness, default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import canonical_json_bytes, resolve_run_plan
from aeread.shared_runner.schemas import AgentProfile, RunSpec
from aeread.shared_runner.task.execution import OpenRouterChatClient, ProviderFailure, ProviderRequest, execute_plan_cell
from aeread_families.procurement_allocation import model_campaign as mc
from aeread_families.procurement_allocation import pay_or_test_v3_case_matrix as v3
from aeread_families.procurement_allocation import pay_or_test_v3_environment as environment
from aeread_families.procurement_allocation import pay_or_test_v3_prompt
from aeread_families.procurement_allocation import pay_or_test_v3_runner as v3_runner
from aeread_families.procurement_allocation import runner
from aeread_families.procurement_grounding.bakeoff import BakeoffCandidate, preflight_candidate

REPOSITORY = Path(__file__).resolve().parents[2]
RUNS_ROOT = REPOSITORY / "runs" / "procurement_allocation"
BASE_URL = v1.BASE_URL
CREDIT_FLOOR_USD = v1.CREDIT_FLOOR_USD
PACK = v3.CONFIRM_PACK_ID
PROMPT = {"prompt_id": pay_or_test_v3_prompt.PROMPT_ID, "text": pay_or_test_v3_prompt.PAY_OR_TEST_V3_PROMPT,
          "treatment_id": pay_or_test_v3_prompt.TREATMENT_ID}
SUBJECTS: dict[str, dict[str, Any]] = {
    name: {**v1.SUBJECTS[name], "route": dataclasses.replace(v1.SUBJECTS[name]["route"],
                                                             profile_id=f"procurement_pay_or_test_v3_{name}_v1")}
    for name in ("gemini38_flash", "gpt6_luna")
}
CONTROLS: dict[str, Any] = {
    **{k: v for k, v in v1.CONTROLS.items() if k not in ("inference_seed", "total_cost_ceiling_usd", "replicates")},
    "inference_seeds": [87001, 87002],
    #: On version 1 Gemini cost $0.0073 a world and Luna $0.0012; version 3 plays run longer. A wave is launched only
    #: if spend plus $0.30 for each of its cells stays under the ceiling.
    "total_cost_ceiling_usd": {"gemini38_flash": 2.00, "gpt6_luna": 1.50},
}
HALT_RULE = v1.HALT_RULE
RETRY_POLICY = v1.RETRY_POLICY
ACTION_SCHEMA_ID = "procurement_pay_or_test_v3_action_schema_v1"
#: What one flat strict object cannot say for version 3's actions.
SCHEMA_RESIDUAL = ("submit_award or check_award with award_lines null",)
NON_EMPTY_TEXT = v1.NON_EMPTY_TEXT
DRIVER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def action_output_schema(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Version 3's strict action object, tightened so that what it admits the version 3 parser accepts.

    ``supplier_id``, ``message`` and ``reason`` are a non-empty string on every action, the supplier one of this world's,
    in the order the buyer sees them; the parser reads each only on the actions that take it. ``award_lines`` is null or
    a non-empty list of lines with a non-empty offer id and a quantity of at least one.
    """
    schema = copy.deepcopy(environment.action_output_schema())
    properties = schema["properties"]
    properties["supplier_id"] = {"type": "string", "enum": [str(s["supplier_id"]) for s in payload["suppliers"]]}
    properties["message"] = dict(NON_EMPTY_TEXT)
    properties["reason"] = dict(NON_EMPTY_TEXT)
    line = {"type": "object", "properties": {"offer_id": dict(NON_EMPTY_TEXT), "quantity": {"type": "integer", "minimum": 1}},
            "required": ["offer_id", "quantity"], "additionalProperties": False}
    properties["award_lines"] = {"type": ["array", "null"], "minItems": 1, "items": line}
    if set(properties) != set(schema["required"]):
        raise AssertionError("every field of the strict object stays required")
    return schema


def _payload(case_path: Path) -> dict[str, Any]:
    return json.loads(Path(case_path).read_text(encoding="utf-8"))["payload"]


def campaign_id(subject: str) -> str:
    return f"procurement_allocation_{PACK}_v3_openrouter_{subject}_v1"


def case_paths() -> list[Path]:
    return list(v3.case_paths(split=PACK))


def build_setup(subject: str, case_path: Path, seed: int) -> runner.ProcurementAllocationSetup:
    """``pay_or_test_v2_openrouter.build_setup`` on version 3's plan and schema, at request seed ``seed``."""
    spec = SUBJECTS[subject]
    route = spec["route"]
    template = v3_runner.build_offline_setup(case_path=case_path, prompt=PROMPT["text"], prompt_id=PROMPT["prompt_id"])
    harness = MinimalChatHarness()
    runtime_id = "aeread.shared_runner.task.execution"
    profile_id = f"{route.profile_id}_procurement_allocation"
    backoff = RETRY_POLICY["retry_backoff"]
    config: dict[str, Any] = {
        "pricing_id": route.pricing.pricing_id, "pricing_sha256": route.pricing.content_sha256(),
        "output_schema": action_output_schema(_payload(case_path)), "provider_metadata": v1.provider_metadata(route),
        "retry_backoff": backoff["policy"], "retry_base_seconds": backoff["retry_base_seconds"],
        "retry_after_max_seconds": backoff["retry_after_max_seconds"],
        "max_output_tokens_ceiling": RETRY_POLICY["length_retry_growth"]["max_output_tokens_ceiling"],
    }
    unavailable = spec["temperature"] == "unavailable"
    if unavailable:
        config["sampling_controls"] = {"temperature": "unavailable"}
    profile = AgentProfile.from_dict({
        "spec_version": AgentProfile.SPEC_VERSION, "profile_id": profile_id,
        "model": {"provider": "openrouter", "model": route.model, "revision": route.revision, "base_url": BASE_URL},
        "harness": {"id": harness.id, "version": harness.version, "config": config},
        "prompt": {"prompt_id": PROMPT["prompt_id"], "sha256": hashlib.sha256(PROMPT["text"].encode("utf-8")).hexdigest()},
        "runtime": {"kind": "python", "implementation": runtime_id, "version": "0.1.0"},
        "tools": [], "memory": {"mode": "disabled"},
        "reasoning": {"condition_id": f"reasoning_{route.reasoning_effort}_v1", "effort": route.reasoning_effort,
                      "token_budget": None, "rationale_visibility": "hidden"},
        "sampling": {"temperature": 0.0 if unavailable else spec["temperature"], "top_p": spec["top_p"],
                     "max_output_tokens": CONTROLS["max_output_tokens"], "seed": int(seed)},
        "budgets": {"max_logical_actions": CONTROLS["max_logical_actions"], "timeout_seconds": CONTROLS["timeout_seconds"],
                    "max_cost_usd": CONTROLS["max_cost_usd_per_trajectory"]},
        "retry_policy": {"max_action_attempts": RETRY_POLICY["max_action_attempts"],
                         "retryable_conditions": list(RETRY_POLICY["retryable_conditions"]),
                         "session_mode": RETRY_POLICY["session_mode"], "sdk_retries": RETRY_POLICY["sdk_retries"]},
    })
    run_spec = RunSpec.from_dict({
        "spec_version": RunSpec.SPEC_VERSION, "run_spec_id": f"procurement_pay_or_test_v3_openrouter_{profile_id}",
        "suite_id": template.plan.suite.suite_id,
        "evaluation_block_ids": [block.block_id for block in template.plan.evaluation_blocks],
        "agent_profile_ids": [profile_id], "seat_assignments": {"buyer": profile_id}, "execution_mode": "evaluate",
        "replicate_override": None, "budget_overrides": None,
    })
    harness_registry = HarnessRegistry()
    for item in default_harnesses().values():
        harness_registry.register(item)
    source = Path(v1.execution_module.__file__)
    pins = [pin for pin in template.plan.implementation_pins if pin.kind not in {"harness", "runtime"}]
    pins += [runner._pin(harness.id, "harness", source, version=harness.version),
             runner._pin(runtime_id, "runtime", source, version="0.1.0")]
    plan = resolve_run_plan(
        families=template.plan.families, cases=template.plan.cases, suite=template.plan.suite,
        sampling=template.plan.sampling, evaluation_blocks=template.plan.evaluation_blocks,
        analysis=template.plan.analysis, agent_profiles=(profile,), run_spec=run_spec, registry=template.registry,
        implementation_pins=tuple(pins), harness_registry=harness_registry,
        provider_capabilities={"openrouter": ProviderCapabilities(
            native_tools=False, structured_output=True, seed=True, system_prompt=True,
            reasoning_budget=route.reasoning_effort is not None, reasoning_token_report=True, max_context_tokens=None)},
    )
    return runner.ProcurementAllocationSetup(
        plan=plan, registry=template.registry, prompt_sources=template.prompt_sources,
        pricing={route.model: route.pricing}, case=template.case,
        harnesses={**default_harnesses(), f"{harness.id}/{harness.version}": harness},
    )


def model_plan(subject: str) -> dict[str, Any]:
    cases = mc._case_records(case_paths())
    seeds = list(CONTROLS["inference_seeds"])
    route = SUBJECTS[subject]["route"]
    plan = {
        "schema_version": "aeread.procurement_allocation_openrouter_plan/0.1",
        "campaign_id": campaign_id(subject), "claim_status": "declared_descriptive",
        "campaign_plan": "docs/families/procurement-allocation/pay_or_test_v3_flash_plan.md",
        "pack": PACK,
        "pack_json_sha256": hashlib.sha256((v3.pack_root(PACK) / "pack.json").read_bytes()).hexdigest(),
        "cases": [{"case_id": r["case_id"], "content_sha256": r["content_sha256"]} for r in cases],
        "independent_case_count": len(cases), "inference_seeds": seeds,
        "inference_seed_meaning": "the OpenRouter request seed; every world is played once under each seed, seed by seed",
        "planned_trajectory_count": len(cases) * len(seeds),
        "model": route.model, "revision": route.revision, "provider": "openrouter", "route": v1._route_block(subject)
        | {"profile_id": route.profile_id},
        "billing": "OpenRouter account; cost_usd is the charge OpenRouter reports for each call",
        "credit_floor_usd": CREDIT_FLOOR_USD,
        "prompt": {"prompt_id": PROMPT["prompt_id"], "sha256": hashlib.sha256(PROMPT["text"].encode("utf-8")).hexdigest(),
                   "treatment_id": PROMPT["treatment_id"]},
        "harness": "minimal_chat/1.0 (fixed transport; not an estimand)", "tools": "none", "memory": "disabled",
        "controls": {**{k: v for k, v in CONTROLS.items() if k not in ("inference_seeds", "total_cost_ceiling_usd")},
                     "total_cost_ceiling_usd": CONTROLS["total_cost_ceiling_usd"][subject]},
        "retry_policy": RETRY_POLICY, "halt_rule": HALT_RULE, "response_cache": "disabled",
        "action_schema": {"schema_id": ACTION_SCHEMA_ID, "residual": list(SCHEMA_RESIDUAL),
                          "residual_outcome": "the episode ends as malformed_procurement_action and is scored as walking away"},
        "headline_reference": {"module": "src/aeread_families/procurement_allocation/pay_or_test_v3_reference.py",
                               "sha256": hashlib.sha256((REPOSITORY / "src/aeread_families/procurement_allocation/"
                                                         "pay_or_test_v3_reference.py").read_bytes()).hexdigest()},
        "claim_scope": "declared descriptive run: the subject's per-world gap closed on the declared worlds, reported "
                       "beside Sol, Opus and the exact rules; no hypothesis is tested",
        "driver": {"path": "tools/cli_subjects/pay_or_test_v3_openrouter.py", "sha256": DRIVER_SHA256},
    }
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return plan


def route_preflight(subject: str) -> dict[str, Any]:
    return preflight_candidate(BakeoffCandidate(candidate_id=subject, route=SUBJECTS[subject]["route"], lane="standard",
                                                access_class="hosted", license_id=None, model_card_url=None))


def parse_reply(case_path: Path, text: str) -> dict[str, Any]:
    plugin = environment.PayOrTestV3Plugin()
    case = plugin.validate_payload(_payload(case_path))
    parsed = plugin.parse_action(case, plugin.initial_state(case, None), "buyer", None, text)
    return {"ok": parsed.ok, "error_code": None if parsed.ok else parsed.error_code}


async def probe(subject: str) -> dict[str, Any]:
    """One strict call on the sealed route with the first world's schema; no cell, nothing written."""
    spec, gate = SUBJECTS[subject], case_paths()[0]
    route, payload = spec["route"], _payload(case_paths()[0])
    request = ProviderRequest(
        provider_call_id=f"probe_{subject}_{DRIVER_SHA256[:8]}", provider="openrouter", base_url=BASE_URL,
        model=route.model, revision=route.revision,
        instructions=(f"Route check. Return the action defer with the reason 'probe', the message 'probe', the supplier_id "
                      f"{payload['suppliers'][0]['supplier_id']!r}, and award_lines null."),
        input_text=json.dumps({"observation": "route check"}),
        temperature=None if spec["temperature"] == "unavailable" else spec["temperature"], top_p=spec["top_p"],
        max_output_tokens=CONTROLS["max_output_tokens"], reasoning_effort=route.reasoning_effort,
        timeout_seconds=CONTROLS["timeout_seconds"], request_sha256="", max_cost_usd=0.01,
        output_schema=action_output_schema(payload), provider_metadata=v1.provider_metadata(route),
        seed=CONTROLS["inference_seeds"][0],
    ).with_computed_hash()
    started = time.perf_counter()
    try:
        result = await OpenRouterChatClient().complete(request)
    except ProviderFailure as failure:
        return {"subject": subject, "answered": False, "condition": failure.condition, "status_code": failure.status_code,
                "message": str(failure)[:400], "seconds": round(time.perf_counter() - started, 2)}
    return {"subject": subject, "answered": True, "finish_reason": result.finish_reason,
            "resolved_model": result.resolved_model, "family_parser": parse_reply(gate, result.output_text),
            "input_tokens": result.input_tokens, "output_tokens": result.output_tokens, "cost_usd": result.cost_usd,
            "seconds": round(time.perf_counter() - started, 2)}


async def run_cell(*, subject: str, run_root: Path, case_path: Path, seed: int, semaphore: asyncio.Semaphore,
                   provider_factory: Callable[[], Any]) -> dict[str, Any]:
    """``pay_or_test_v2_openrouter.run_cell`` on version 3's plan; a failed cell is sealed under version 3's leaf."""
    setup = build_setup(subject, case_path, seed)
    cell = setup.plan.cells[0]
    evidence_root = run_root / "executions" / mc._safe_case_directory(setup.case.case_id, setup.case.content_sha256) / f"seed_{seed}"
    started = time.perf_counter()
    failed = False
    try:
        async with semaphore:
            execution = await execute_plan_cell(
                plan=setup.plan, cell_id=cell.cell_id, registry=setup.registry, evidence_root=evidence_root,
                prompt_sources=setup.prompt_sources, providers={"openrouter": provider_factory()},
                pricing=setup.pricing, harnesses=setup.harnesses)
        receipt = runner.finalize_procurement_allocation_execution(setup=setup, execution=execution)
        replayed = runner.replay_procurement_allocation_receipt(setup=setup, receipt=receipt, evidence_root=evidence_root)
        if canonical_json_bytes(replayed) != canonical_json_bytes(receipt):
            raise RuntimeError("replayed receipt differs from the live receipt")
        execution.evidence.audit_reconciliation()
        calls = v1._calls(execution)
        retries = Counter(str(a.retry_reason) for action in execution.action_executions for a in action.attempts
                          if a.retry_reason is not None)
        outcome = json.loads(canonical_json_bytes(execution.episode_result.outcome))
        row: dict[str, Any] = {
            "case_id": setup.case.case_id, "case_content_sha256": setup.case.content_sha256, "inference_seed": seed,
            "status": "completed", "decision": outcome["decision"], "termination_reason": outcome["termination_reason"],
            "feasible": bool(outcome["feasible"]), "feasible_award": bool(outcome.get("feasible_award", False)),
            "completed_kits": int(outcome["completed_kits"]),
            "contribution_margin_usd": float(outcome["contribution_margin_usd"]),
            "upper_bound_usd": float(outcome["upper_bound_usd"]),
            "regret_to_upper_bound_usd": float(outcome["regret_to_upper_bound_usd"]),
            "violations": list(outcome["violations"]), "elapsed_environment_days": int(outcome["elapsed_days"]),
            "action_count": len(execution.action_executions), "action_trace": mc._public_action_trace(execution),
            "elapsed_seconds": time.perf_counter() - started,
            "input_tokens": sum(c.input_tokens for c in calls), "cached_input_tokens": sum(c.cached_input_tokens for c in calls),
            "output_tokens": sum(c.output_tokens for c in calls), "cost_usd": execution.total_cost_usd,
            "cost_accounting": "lower_bound" if any(c.status == "outcome_unknown" for c in calls) else "exact",
            "resolved_models": sorted({c.resolved_model for c in calls if c.resolved_model is not None}),
            "receipt_sha256": receipt.receipt_sha256, "receipt_replayed": True, "replay_level": receipt.replay_level,
            "provider_call_count": len(calls), "runner_retry_count": sum(retries.values()),
            "retry_condition_counts": dict(sorted(retries.items())),
        }
    except Exception as error:  # noqa: BLE001 - a failed cell is a typed row
        failure_sha = None
        try:
            failure_sha = v3_runner.finalize_failure(setup=setup, cell_id=cell.cell_id, evidence_root=evidence_root,
                                                     error=error).receipt_sha256
        except Exception:  # noqa: BLE001
            pass
        row = {"case_id": setup.case.case_id, "case_content_sha256": setup.case.content_sha256, "inference_seed": seed,
               "status": "operational_failure", "elapsed_seconds": time.perf_counter() - started,
               "failure_receipt_sha256": failure_sha, "failure_message": str(error)[:2000], **mc._failure_summary(error)}
        failed = True
    if failed:
        row.update(mc._sealed_failure_telemetry(evidence_root))
    row["result_sha256"] = hashlib.sha256(canonical_json_bytes(dict(row))).hexdigest()
    mc._atomic_write_json(mc._result_path(run_root, case_id=setup.case.case_id, content_sha256=setup.case.content_sha256,
                                          seed=seed), row)
    return row


def _spent(row: Mapping[str, Any]) -> float:
    cost = row.get("cost_usd")
    return float(cost) if isinstance(cost, (int, float)) else float(CONTROLS["max_cost_usd_per_trajectory"])


async def run(subject: str, run_root: Path, *, resume: bool) -> dict[str, Any]:
    """``pay_or_test_v2_openrouter.run``: credit floor and catalog check before the run root exists, waves, halt rule."""
    mc._validate_operational_run_root(run_root)
    plan = model_plan(subject)
    plan_path = run_root / "model_plan.json"
    if plan_path.exists():
        if canonical_json_bytes(json.loads(plan_path.read_text())) != canonical_json_bytes(plan):
            raise ValueError("existing model plan does not match this invocation")
        if not resume:
            raise FileExistsError("run root exists; pass --resume to continue")
    credit = dict(v1.read_credit())
    v1.check_credit(credit)
    route = dict(route_preflight(subject))
    run_root.mkdir(parents=True, exist_ok=True)
    if not plan_path.exists():
        mc._atomic_write_json(plan_path, plan)
    rows: list[dict[str, Any]] = []
    todo: list[tuple[Path, int]] = []
    records = mc._case_records(case_paths())
    for seed in plan["inference_seeds"]:
        for record in records:
            path = mc._result_path(run_root, case_id=record["case_id"], content_sha256=record["content_sha256"], seed=seed)
            if path.exists():
                rows.append(mc._read_result(path, case_id=record["case_id"], content_sha256=record["content_sha256"], seed=seed))
            else:
                todo.append((record["path"], seed))
    semaphore = asyncio.Semaphore(CONTROLS["max_parallel_cells"])
    limit = CONTROLS["total_cost_ceiling_usd"][subject]
    per_cell, width = float(CONTROLS["max_cost_usd_per_trajectory"]), CONTROLS["max_parallel_cells"]
    stop_after = CONTROLS["max_consecutive_operational_failures"]
    halted = None
    for start in range(0, len(todo), width):
        spent = sum(_spent(row) for row in rows)
        if spent + per_cell * min(width, len(todo) - start) > limit + 1e-9:
            halted = f"total cost ceiling: spent {spent:.4f} of {limit}"
            break
        tail = [row.get("status") for row in rows][-stop_after:]
        if len(tail) == stop_after and all(s == "operational_failure" for s in tail):
            halted = "consecutive operational failures"
            break
        rows.extend(await asyncio.gather(*(
            run_cell(subject=subject, run_root=run_root, case_path=case_path, seed=seed, semaphore=semaphore,
                     provider_factory=OpenRouterChatClient)
            for case_path, seed in todo[start:start + width])))
    rows.sort(key=lambda row: (int(row["inference_seed"]), str(row["case_id"])))
    summary = mc.summarize_rows(rows, planned_trajectory_count=plan["planned_trajectory_count"],
                                independent_case_count=plan["independent_case_count"])
    artifact = {"schema_version": "aeread.procurement_allocation_openrouter_qualification/0.1", "plan": plan,
                "preflight": {"credit_remaining_usd_at_start": credit["remaining_usd"], "route": route},
                "halted": halted, "summary": summary, "rows": rows}
    artifact["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(artifact)).hexdigest()
    mc._atomic_write_json(run_root / "summary.json", artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--subject", choices=sorted(SUBJECTS), required=True)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if not (args.probe or args.execute):
        plan = model_plan(args.subject)
        print(json.dumps({k: plan[k] for k in ("campaign_id", "planned_trajectory_count", "claim_status", "plan_sha256")}))
        return 0
    v1.load_api_key(args.env_file)
    if args.probe:
        print(json.dumps(asyncio.run(probe(args.subject)), indent=1))
        return 0
    run_root = args.run_root or RUNS_ROOT / campaign_id(args.subject).removeprefix("procurement_allocation_")
    artifact = asyncio.run(run(args.subject, run_root, resume=args.resume))
    print(json.dumps({"halted": artifact["halted"], "completed": sum(r["status"] == "completed" for r in artifact["rows"]),
                      "planned": artifact["plan"]["planned_trajectory_count"],
                      "cost_usd": round(sum(_spent(r) for r in artifact["rows"]), 4)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
