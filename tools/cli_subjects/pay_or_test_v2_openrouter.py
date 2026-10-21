"""Pay or test version 2 played by hosted flash models through OpenRouter: the gate, the variance pilot and the confirmatory run.

The campaign is declared in
``docs/families/procurement-allocation/pay_or_test_v2_confirmatory_plan.md``.
This driver is written from ``pay_or_test_openrouter.py`` (the version 1
driver, whose bytes are in sealed plans and are not edited) and changes only
what that plan lists:

- the pack: ``pay_or_test_v2_pilot`` for the gate and the pilot, and the pack
  the confirmatory freeze names for the confirmatory run;
- the prompt: ``pay_or_test_v2_prompt.PAY_OR_TEST_V2_PROMPT``, id
  ``procurement_allocation_pay_or_test_shared_source_v1``;
- the panel names (``gate``, ``pilot``, ``confirmatory``), the identities and
  their profile ids;
- the request seeds: 87001 for the gate, 87001 and 87002 for the pilot and the
  confirmatory run, every world played once under each, seed by seed;
- the cost ceilings, one per panel and subject.

Every other control is the version 1 driver's, and most are imported from it
rather than copied, so they cannot drift: the route pins (each subject's route
with only its profile id changed), action schema v2 (``action_output_schema``,
which the family parser agrees with, P-D-23), the credit floor and the catalog
check before any run root exists, Housing v14's retry policy, $0.30 a cell, the
halt rule (three consecutive failed cells, and no wave launched past the
ceiling). The version 1 driver's digest is sealed beside this file's.

One addition: the model plan records the digests of both drivers, both
references and both prompt modules, so the module that prices every action into
decision loss is sealed with the run and ``verify`` refuses a run root once it
changes (P-T-17: the version 1 plans did not seal the module the headline
measure comes from). It is not a kernel implementation pin: the resolver admits
only pins a family verifier references, and the procurement verifiers are in
the family environment, which sealed plans hash (P-D-26). The pack is sealed by the digest
of its ``pack.json`` and of every case, not by the generator's bytes, so a
split added to the generator later does not move these identities.

The confirmatory panel runs only on a committed freeze,
``cases/procurement_allocation_v1/pay_or_test_v2_confirmatory_freeze.json``,
written by ``--write-freeze`` from the pilot report: it names this driver's
digest, every sealed source, the pack, the seeds, the subjects, the declared
contrasts and the sizing record. Without one the confirmatory panel refuses
before any check or call.

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/pay_or_test_v2_openrouter.py \\
        --subject gemini38_flash --panel gate                       # plan only, no provider call
    ... --subject gemini38_flash --panel gate --probe --env-file <AERead>/.env   # one strict call
    ... --subject gemini38_flash --panel pilot --execute --env-file <AERead>/.env
    ... --subject gemini38_flash --panel pilot --verify              # offline replay of every receipt

Run roots default to ``runs/procurement_allocation/<campaign id less its family prefix>``,
which ``pay_or_test_v2_report.py`` reads.
"""

from __future__ import annotations

import argparse
import asyncio
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
from aeread.shared_runner.task.evaluation import audit_family_receipt
from aeread.shared_runner.task.execution import (
    OpenRouterChatClient,
    ProviderFailure,
    ProviderRequest,
    execute_plan_cell,
)
from aeread_families.procurement_allocation import model_campaign as mc
from aeread_families.procurement_allocation import pay_or_test_v2_case_matrix as pack_v2
from aeread_families.procurement_allocation import pay_or_test_v2_prompt
from aeread_families.procurement_allocation import pay_or_test_v2_reference
from aeread_families.procurement_allocation import runner
from aeread_families.procurement_grounding.bakeoff import BakeoffCandidate, preflight_candidate
from aeread_families.procurement_grounding.runner import OpenRouterRoute

REPOSITORY = Path(__file__).resolve().parents[2]
DRIVER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
RUNS_ROOT = REPOSITORY / "runs" / "procurement_allocation"
BASE_URL = v1.BASE_URL
CREDIT_FLOOR_USD = v1.CREDIT_FLOOR_USD
FREEZE_PATH = REPOSITORY / "cases" / "procurement_allocation_v1" / "pay_or_test_v2_confirmatory_freeze.json"
FREEZE_SCHEMA = "aeread.procurement_pay_or_test_v2_confirmatory_freeze/0.1"

PROMPT = {"prompt_id": pay_or_test_v2_prompt.PROMPT_ID, "text": pay_or_test_v2_prompt.PAY_OR_TEST_V2_PROMPT,
          "treatment_id": pay_or_test_v2_prompt.TREATMENT_ID}
VERSION = "v1"
PANELS = ("gate", "pilot", "confirmatory")

#: The version 1 driver's subjects, the two the plan requires, with only the profile id changed.
SUBJECTS: dict[str, dict[str, Any]] = {
    name: {**v1.SUBJECTS[name],
           "route": dataclasses.replace(v1.SUBJECTS[name]["route"],
                                        profile_id=f"procurement_pay_or_test_v2_{name}_{VERSION}")}
    for name in ("gemini38_flash", "gpt6_luna")
}

#: Every control of the version 1 driver, but the seeds and the ceilings.
CONTROLS: dict[str, Any] = {
    **{k: v for k, v in v1.CONTROLS.items() if k not in ("inference_seed", "total_cost_ceiling_usd", "replicates")},
    "inference_seeds": {"gate": [87001], "pilot": [87001, 87002], "confirmatory": [87001, 87002]},
    #: Gemini 3.8 Flash cost $0.0073 a world under brief v2 on version 1, GPT-6 Luna $0.0012. A wave is launched
    #: only if the run's spend plus $0.30 for each of its cells stays under the ceiling, so each ceiling leaves
    #: room for three cells above about twice the plan's estimate.
    "total_cost_ceiling_usd": {
        "gate": {"gemini38_flash": 0.30, "gpt6_luna": 0.30},
        "pilot": {"gemini38_flash": 1.50, "gpt6_luna": 1.00},
        "confirmatory": {"gemini38_flash": 1.80, "gpt6_luna": 1.00},
    },
}
HALT_RULE = v1.HALT_RULE
RETRY_POLICY = v1.RETRY_POLICY
ACTION_SCHEMA_ID = v1.ACTION_SCHEMA_ID
SCHEMA_RESIDUAL = v1.SCHEMA_RESIDUAL
action_output_schema = v1.action_output_schema
load_api_key = v1.load_api_key
read_credit = v1.read_credit
check_credit = v1.check_credit
provider_metadata = v1.provider_metadata
parse_reply = v1.parse_reply
_payload = v1._payload
_schema_sha256 = v1._schema_sha256
_calls = v1._calls

_FAMILY = Path(pack_v2.__file__).parent
#: Modules whose bytes decide what a cell sends, how it is scored or what the pack holds. Their digests are sealed in
#: the model plan, so a changed module cannot resume a run root or pass ``verify``.
SOURCES = {
    "tools/cli_subjects/pay_or_test_v2_openrouter.py": Path(__file__),
    "tools/cli_subjects/pay_or_test_openrouter.py": Path(v1.__file__),
    "src/aeread_families/procurement_allocation/pay_or_test_v2_reference.py": Path(pay_or_test_v2_reference.__file__),
    "src/aeread_families/procurement_allocation/pay_or_test_reference.py": _FAMILY / "pay_or_test_reference.py",
    "src/aeread_families/procurement_allocation/pay_or_test_v2_prompt.py": Path(pay_or_test_v2_prompt.__file__),
    "src/aeread_families/procurement_allocation/pay_or_test_prompt.py": _FAMILY / "pay_or_test_prompt.py",
}
HEADLINE_REFERENCE = "src/aeread_families/procurement_allocation/pay_or_test_v2_reference.py"


def source_digests() -> dict[str, str]:
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in SOURCES.items()}


def campaign_id(subject: str, panel: str) -> str:
    if panel not in PANELS:
        raise ValueError(f"unknown panel {panel!r}")
    return f"procurement_allocation_pay_or_test_v2_shared_source_openrouter_{subject}_{panel}_{VERSION}"


def default_run_root(subject: str, panel: str) -> Path:
    return RUNS_ROOT / campaign_id(subject, panel).removeprefix("procurement_allocation_")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_freeze(path: Path | None = None) -> dict[str, Any]:
    """The committed confirmatory freeze, checked against this driver, its pack and its own digest."""
    path = path or FREEZE_PATH
    if not path.exists():
        raise FileNotFoundError(f"the confirmatory panel runs only on a committed freeze: {path} does not exist")
    freeze = json.loads(path.read_text(encoding="utf-8"))
    if freeze.get("schema_version") != FREEZE_SCHEMA:
        raise ValueError(f"not a confirmatory freeze: {freeze.get('schema_version')!r}")
    body = {k: v for k, v in freeze.items() if k != "freeze_sha256"}
    if hashlib.sha256(canonical_json_bytes(body)).hexdigest() != freeze.get("freeze_sha256"):
        raise ValueError("the freeze does not match its own digest")
    if freeze["sources"] != source_digests():
        raise ValueError("the driver or a module it seals changed after the freeze")
    if freeze["prompt"]["sha256"] != hashlib.sha256(PROMPT["text"].encode("utf-8")).hexdigest():
        raise ValueError("the prompt changed after the freeze")
    root = pack_v2.pack_root(freeze["pack"]["pack_id"])
    if _sha256_file(root / "pack.json") != freeze["pack"]["pack_json_sha256"]:
        raise ValueError("the frozen pack's pack.json changed")
    records = mc._case_records(pack_v2.case_paths(split=freeze["pack"]["pack_id"]))
    if [{"case_id": r["case_id"], "content_sha256": r["content_sha256"]} for r in records] != freeze["pack"]["cases"]:
        raise ValueError("the frozen pack's cases changed")
    if freeze["inference_seeds"] != CONTROLS["inference_seeds"]["confirmatory"]:
        raise ValueError("the frozen seeds are not this driver's")
    return freeze


def pack_of(panel: str) -> str:
    return load_freeze()["pack"]["pack_id"] if panel == "confirmatory" else pack_v2.PILOT_PACK_ID


def gate_world() -> str:
    """The gate plays the pilot pack's first world in its own order (pack.json)."""
    manifest = json.loads((pack_v2.pack_root(pack_v2.PILOT_PACK_ID) / "pack.json").read_text(encoding="utf-8"))
    return manifest["worlds"][0]["slug"]


def case_paths(panel: str) -> list[Path]:
    paths = list(pack_v2.case_paths(split=pack_of(panel)))
    return [p for p in paths if p.stem == gate_world()] if panel == "gate" else paths


def ceiling(subject: str, panel: str) -> float:
    return float(CONTROLS["total_cost_ceiling_usd"][panel][subject])


def build_setup(subject: str, case_path: Path, seed: int) -> runner.ProcurementAllocationSetup:
    """The version 1 driver's ``build_setup`` with this prompt and ``seed`` as the request seed."""
    spec = SUBJECTS[subject]
    route: OpenRouterRoute = spec["route"]
    template = runner.build_offline_setup(case_path=case_path, prompt=PROMPT["text"], prompt_id=PROMPT["prompt_id"])
    harness = MinimalChatHarness()
    runtime_id = "aeread.shared_runner.task.execution"
    profile_id = f"{route.profile_id}_procurement_allocation"
    backoff = RETRY_POLICY["retry_backoff"]
    config: dict[str, Any] = {
        "pricing_id": route.pricing.pricing_id,
        "pricing_sha256": route.pricing.content_sha256(),
        "output_schema": action_output_schema(_payload(case_path)),
        "provider_metadata": provider_metadata(route),
        "retry_backoff": backoff["policy"],
        "retry_base_seconds": backoff["retry_base_seconds"],
        "retry_after_max_seconds": backoff["retry_after_max_seconds"],
        "max_output_tokens_ceiling": RETRY_POLICY["length_retry_growth"]["max_output_tokens_ceiling"],
    }
    unavailable = spec["temperature"] == "unavailable"
    if unavailable:
        config["sampling_controls"] = {"temperature": "unavailable"}
    profile = AgentProfile.from_dict(
        {
            "spec_version": AgentProfile.SPEC_VERSION,
            "profile_id": profile_id,
            "model": {"provider": "openrouter", "model": route.model, "revision": route.revision, "base_url": BASE_URL},
            "harness": {"id": harness.id, "version": harness.version, "config": config},
            "prompt": {"prompt_id": PROMPT["prompt_id"],
                       "sha256": hashlib.sha256(PROMPT["text"].encode("utf-8")).hexdigest()},
            "runtime": {"kind": "python", "implementation": runtime_id, "version": "0.1.0"},
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {"condition_id": f"reasoning_{route.reasoning_effort}_v1", "effort": route.reasoning_effort,
                          "token_budget": None, "rationale_visibility": "hidden"},
            "sampling": {"temperature": 0.0 if unavailable else spec["temperature"], "top_p": spec["top_p"],
                         "max_output_tokens": CONTROLS["max_output_tokens"], "seed": int(seed)},
            "budgets": {"max_logical_actions": CONTROLS["max_logical_actions"],
                        "timeout_seconds": CONTROLS["timeout_seconds"],
                        "max_cost_usd": CONTROLS["max_cost_usd_per_trajectory"]},
            "retry_policy": {"max_action_attempts": RETRY_POLICY["max_action_attempts"],
                             "retryable_conditions": list(RETRY_POLICY["retryable_conditions"]),
                             "session_mode": RETRY_POLICY["session_mode"], "sdk_retries": RETRY_POLICY["sdk_retries"]},
        }
    )
    run_spec = RunSpec.from_dict(
        {
            "spec_version": RunSpec.SPEC_VERSION,
            "run_spec_id": f"procurement_allocation_openrouter_{profile_id}",
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
    source = Path(v1.execution_module.__file__)
    pins = [pin for pin in template.plan.implementation_pins if pin.kind not in {"harness", "runtime"}]
    pins += [runner._pin(harness.id, "harness", source, version=harness.version),
             runner._pin(runtime_id, "runtime", source, version="0.1.0")]
    plan = resolve_run_plan(
        families=template.plan.families, cases=template.plan.cases, suite=template.plan.suite,
        sampling=template.plan.sampling, evaluation_blocks=template.plan.evaluation_blocks,
        analysis=template.plan.analysis, agent_profiles=(profile,), run_spec=run_spec,
        registry=template.registry, implementation_pins=tuple(pins), harness_registry=harness_registry,
        provider_capabilities={
            "openrouter": ProviderCapabilities(
                native_tools=False, structured_output=True, seed=True, system_prompt=True,
                reasoning_budget=route.reasoning_effort is not None, reasoning_token_report=True,
                max_context_tokens=None,
            )
        },
    )
    return runner.ProcurementAllocationSetup(
        plan=plan, registry=template.registry, prompt_sources=template.prompt_sources,
        pricing={route.model: route.pricing}, case=template.case,
        harnesses={**default_harnesses(), f"{harness.id}/{harness.version}": harness},
    )


def _route_block(subject: str) -> dict[str, Any]:
    route: OpenRouterRoute = SUBJECTS[subject]["route"]
    return {**v1._route_block(subject), "profile_id": route.profile_id}


def model_plan(subject: str, panel: str) -> dict[str, Any]:
    cases = mc._case_records(case_paths(panel))
    seeds = list(CONTROLS["inference_seeds"][panel])
    pack_id = pack_of(panel)
    freeze = load_freeze() if panel == "confirmatory" else None
    plan = {
        "schema_version": "aeread.procurement_allocation_openrouter_plan/0.1",
        "campaign_id": campaign_id(subject, panel),
        "claim_status": {"gate": "development_gate", "pilot": "development_pilot",
                         "confirmatory": "confirmatory"}[panel],
        "campaign_plan": "docs/families/procurement-allocation/pay_or_test_v2_confirmatory_plan.md",
        "pack": pack_id,
        "pack_json_sha256": _sha256_file(pack_v2.pack_root(pack_id) / "pack.json"),
        "cases": [{"case_id": r["case_id"], "content_sha256": r["content_sha256"]} for r in cases],
        "independent_case_count": len(cases),
        "inference_seeds": seeds,
        "inference_seed_meaning": "the OpenRouter request seed; every world is played once under each seed, "
                                  "seed by seed in this order, so a halted run keeps whole passes",
        "planned_trajectory_count": len(cases) * len(seeds),
        "model": SUBJECTS[subject]["route"].model, "revision": SUBJECTS[subject]["route"].revision,
        "provider": "openrouter",
        "route": _route_block(subject),
        "routing": "only the pinned provider, no fallbacks, require_parameters, the pinned quantization, max price "
                   "at the pinned list price; a cheaper tier of the same provider is admitted, so a priced cost is "
                   "an upper bound and the charged cost is what OpenRouter reports",
        "billing": "OpenRouter account; cost_usd is the charge OpenRouter reports for each call",
        "credit_floor_usd": CREDIT_FLOOR_USD,
        "prompt": {"prompt_id": PROMPT["prompt_id"],
                   "sha256": hashlib.sha256(PROMPT["text"].encode("utf-8")).hexdigest(),
                   "treatment_id": PROMPT["treatment_id"]},
        "harness": "minimal_chat/1.0 (fixed transport; not an estimand)",
        "tools": "none",
        "memory": "disabled",
        "controls": {**{k: v for k, v in CONTROLS.items() if k not in ("inference_seeds", "total_cost_ceiling_usd")},
                     "total_cost_ceiling_usd": ceiling(subject, panel)},
        "retry_policy": RETRY_POLICY,
        "halt_rule": HALT_RULE,
        "response_cache": "disabled",
        "primary_outcomes": ["decision_loss_usd (pay_or_test_v2_report, priced by pay_or_test_v2_reference.score_actions)",
                             *mc.DEFAULT_PRIMARY_OUTCOMES],
        "action_schema": {
            "schema_id": ACTION_SCHEMA_ID,
            "built_by": "action_output_schema in pay_or_test_openrouter.py, from runner.procurement_action_output_schema",
            "sha256_by_case": {r["case_id"]: _schema_sha256(r["path"]) for r in cases},
            "agrees_with": "ProcurementAllocationPlugin.parse_action: what the schema admits the parser accepts, "
                           "except the listed residual",
            "residual": list(SCHEMA_RESIDUAL),
            "residual_outcome": "the episode ends as malformed_procurement_action and is scored as walking away",
        },
        "headline_reference": {"module": HEADLINE_REFERENCE, "sha256": source_digests()[HEADLINE_REFERENCE],
                               "sealed_by": "this plan's sources; not a kernel implementation pin, because the "
                                            "resolver admits only pins a family verifier references (P-D-26)"},
        "sources": source_digests(),
        "claim_scope": {"gate": "development gate: one world, one play, nothing scored as a result",
                        "pilot": "variance pilot of the confirmatory plan: development evidence, nothing in it is a result",
                        "confirmatory": "the confirmatory run of the declared plan; the contrasts are its freeze's"}[panel],
        "driver": {"path": "tools/cli_subjects/pay_or_test_v2_openrouter.py", "sha256": DRIVER_SHA256},
    }
    if freeze is not None:
        plan["freeze"] = {"path": str(FREEZE_PATH.relative_to(REPOSITORY)), "freeze_sha256": freeze["freeze_sha256"],
                          "sizing_record_sha256": freeze["sizing_record"]["artifact_sha256"]}
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return plan


#: What the plan declares before any play, copied into the freeze so the analysis cannot move after the run.
DECLARED = {
    "primary_measure": "decision loss per world in dollars (pay_or_test_v2_reference.score_actions), a world's value "
                       "the mean over its completed plays; a rejected or malformed action is priced as walking away",
    "contrasts": {
        "P1-gemini38_flash": "Gemini 3.8 Flash's loss less one_step_value's exact expected loss on the same world",
        "P1-gpt6_luna": "GPT-6 Luna's loss less one_step_value's exact expected loss on the same world",
        "P2": "Gemini 3.8 Flash's loss less GPT-6 Luna's, paired by world",
    },
    "test": "paired t on world values, two-sided, Holm across the three at a familywise 0.05; intervals at 95% and "
            "at each contrast's Holm level",
    "minimum_meaningful_effect_usd": 10.0,
    "exclusions": "a world is excluded only if its case fails validation or its digest differs from pack.json; a "
                  "failed cell is typed missingness and never rerun; a world enters a contrast only if both sides "
                  "have at least one completed play; a contrast that loses more than 5% of its worlds is reported "
                  "as not confirmatory, with the missing worlds named",
    "reported_not_tested": ["loss by part", "share of the best policy's value", "probe rate", "loss by cell and clock",
                            "the subject against pay_premium and two_step_value"],
}


def build_freeze(pack_id: str, sizing_record: Mapping[str, Any], *, pilot_report_sha256: str) -> dict[str, Any]:
    """The confirmatory freeze: everything the run may not change, with its own digest."""
    if sizing_record.get("artifact_sha256") is None:
        raise ValueError("the sizing record must be sealed")
    worlds = int(sizing_record["worlds"])
    records = mc._case_records(pack_v2.case_paths(split=pack_id))
    if worlds > 96:
        raise ValueError(f"the sizing needs {worlds} worlds; the plan allows no confirmatory run past 96")
    if len(records) < worlds:
        raise ValueError(f"pack {pack_id} has {len(records)} worlds; the sizing record needs {worlds}")
    plan_doc = REPOSITORY / "docs" / "families" / "procurement-allocation" / "pay_or_test_v2_confirmatory_plan.md"
    freeze: dict[str, Any] = {
        "schema_version": FREEZE_SCHEMA,
        "campaign_plan": {"path": str(plan_doc.relative_to(REPOSITORY)), "sha256": _sha256_file(plan_doc)},
        "pack": {"pack_id": pack_id, "pack_json_sha256": _sha256_file(pack_v2.pack_root(pack_id) / "pack.json"),
                 "cases": [{"case_id": r["case_id"], "content_sha256": r["content_sha256"]} for r in records]},
        "prompt": {"prompt_id": PROMPT["prompt_id"], "sha256": hashlib.sha256(PROMPT["text"].encode("utf-8")).hexdigest()},
        "sources": source_digests(),
        "driver_sha256": DRIVER_SHA256,
        "inference_seeds": list(CONTROLS["inference_seeds"]["confirmatory"]),
        "subjects": {s: {"campaign_id": campaign_id(s, "confirmatory"), "profile_id": SUBJECTS[s]["route"].profile_id,
                         "total_cost_ceiling_usd": ceiling(s, "confirmatory")} for s in SUBJECTS},
        "sizing_record": dict(sizing_record),
        "pilot_report_sha256": pilot_report_sha256,
        "declared": DECLARED,
    }
    freeze["freeze_sha256"] = hashlib.sha256(canonical_json_bytes(freeze)).hexdigest()
    return freeze


def write_freeze(pilot_report: Path, pack_id: str, path: Path | None = None) -> dict[str, Any]:
    """Write the freeze from the pilot report's sealed sizing record; refuse to overwrite one."""
    path = path or FREEZE_PATH
    if path.exists():
        raise FileExistsError(f"{path} exists; a freeze is never rewritten")
    data = pilot_report.read_bytes()
    record = json.loads(data)["variance"]["sizing"]["record"]
    freeze = build_freeze(pack_id, record, pilot_report_sha256=hashlib.sha256(data).hexdigest())
    mc._atomic_write_json(path, freeze)
    load_freeze(path)
    return freeze


def route_preflight(subject: str) -> dict[str, Any]:
    """The catalog check: the pinned endpoint exists, at or under the pin, with every strict parameter."""
    route: OpenRouterRoute = SUBJECTS[subject]["route"]
    return preflight_candidate(BakeoffCandidate(candidate_id=subject, route=route, lane="standard",
                                                access_class="hosted", license_id=None, model_card_url=None))


async def probe(subject: str, client: Any | None = None) -> dict[str, Any]:
    """One strict call on the sealed route with the gate world's action schema; no cell, nothing written."""
    spec = SUBJECTS[subject]
    route: OpenRouterRoute = spec["route"]
    gate = case_paths("gate")[0]
    payload = _payload(gate)
    first = payload["suppliers"][0]["supplier_id"]
    request = ProviderRequest(
        provider_call_id=f"probe_{subject}_{DRIVER_SHA256[:8]}", provider="openrouter", base_url=BASE_URL,
        model=route.model, revision=route.revision,
        instructions=(f"Route check. Return the action defer with the reason 'probe', the message 'probe', the "
                      f"supplier_id {first!r}, and every other field null."),
        input_text=json.dumps({"observation": "route check"}),
        temperature=None if spec["temperature"] == "unavailable" else spec["temperature"], top_p=spec["top_p"],
        max_output_tokens=CONTROLS["max_output_tokens"], reasoning_effort=route.reasoning_effort,
        timeout_seconds=CONTROLS["timeout_seconds"], request_sha256="", max_cost_usd=0.01,
        output_schema=action_output_schema(payload), provider_metadata=provider_metadata(route),
        seed=CONTROLS["inference_seeds"]["gate"][0],
    ).with_computed_hash()
    started = time.perf_counter()
    try:
        result = await (client or OpenRouterChatClient()).complete(request)
    except ProviderFailure as failure:
        return {"subject": subject, "answered": False, "condition": failure.condition,
                "status_code": failure.status_code, "message": str(failure),
                "seconds": round(time.perf_counter() - started, 2)}
    return {"subject": subject, "answered": True, "finish_reason": result.finish_reason,
            "resolved_model": result.resolved_model, "output_text": result.output_text,
            "family_parser": parse_reply(gate, result.output_text),
            "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
            "reasoning_tokens": result.reasoning_tokens, "cost_usd": result.cost_usd,
            "seconds": round(time.perf_counter() - started, 2)}


def _execution_root(run_root: Path, case_id: str, content_sha256: str, seed: int) -> Path:
    return run_root / "executions" / mc._safe_case_directory(case_id, content_sha256) / f"seed_{seed}"


async def run_cell(*, subject: str, run_root: Path, case_path: Path, seed: int, semaphore: asyncio.Semaphore,
                   provider_factory: Callable[[], Any]) -> dict[str, Any]:
    """The version 1 driver's ``run_cell`` at ``seed``; the row has the same fields."""
    setup = build_setup(subject, case_path, seed)
    cell = setup.plan.cells[0]
    evidence_root = _execution_root(run_root, setup.case.case_id, setup.case.content_sha256, seed)
    started = time.perf_counter()
    failed = False
    try:
        async with semaphore:
            execution = await execute_plan_cell(
                plan=setup.plan, cell_id=cell.cell_id, registry=setup.registry, evidence_root=evidence_root,
                prompt_sources=setup.prompt_sources, providers={"openrouter": provider_factory()},
                pricing=setup.pricing, harnesses=setup.harnesses,
            )
        receipt = runner.finalize_procurement_allocation_execution(setup=setup, execution=execution)
        replayed = runner.replay_procurement_allocation_receipt(setup=setup, receipt=receipt, evidence_root=evidence_root)
        if canonical_json_bytes(replayed) != canonical_json_bytes(receipt):
            raise RuntimeError("replayed receipt differs from the live receipt")
        execution.evidence.audit_reconciliation()
        calls = _calls(execution)
        retries = Counter(str(attempt.retry_reason) for action in execution.action_executions
                          for attempt in action.attempts if attempt.retry_reason is not None)
        outcome = json.loads(canonical_json_bytes(execution.episode_result.outcome))
        row: dict[str, Any] = {
            "case_id": setup.case.case_id, "case_content_sha256": setup.case.content_sha256,
            "inference_seed": seed, "status": "completed",
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
            "cost_accounting": ("lower_bound" if any(call.status == "outcome_unknown" for call in calls) else "exact"),
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
               "inference_seed": seed, "status": "operational_failure",
               "elapsed_seconds": time.perf_counter() - started, "failure_receipt_sha256": failure_sha,
               "failure_message": str(error)[:2000], **mc._failure_summary(error)}
        failed = True
    if failed:
        # Audited after the handler exits, so its traceback no longer holds the live store.
        row.update(mc._sealed_failure_telemetry(evidence_root))
    row["result_sha256"] = hashlib.sha256(canonical_json_bytes(dict(row))).hexdigest()
    mc._atomic_write_json(mc._result_path(run_root, case_id=setup.case.case_id,
                                          content_sha256=setup.case.content_sha256, seed=seed), row)
    return row


def _spent(row: Mapping[str, Any]) -> float:
    cost = row.get("cost_usd")
    return float(cost) if isinstance(cost, (int, float)) else float(CONTROLS["max_cost_usd_per_trajectory"])


async def run(subject: str, panel: str, run_root: Path, *, resume: bool,
              provider_factory: Callable[[], Any] = OpenRouterChatClient,
              credit_fn: Callable[[], Mapping[str, float]] = read_credit,
              preflight_fn: Callable[[str], Mapping[str, Any]] = route_preflight) -> dict[str, Any]:
    mc._validate_operational_run_root(run_root)
    plan = model_plan(subject, panel)
    plan_path = run_root / "model_plan.json"
    if plan_path.exists():
        if canonical_json_bytes(json.loads(plan_path.read_text())) != canonical_json_bytes(plan):
            raise ValueError("existing model plan does not match this invocation")
        if not resume:
            raise FileExistsError("run root exists; pass --resume to continue")
    # Both checks before the run root exists: a refused route or an empty account consumes no identity.
    credit = dict(credit_fn())
    check_credit(credit)
    route = dict(preflight_fn(subject))
    run_root.mkdir(parents=True, exist_ok=True)
    if not plan_path.exists():
        mc._atomic_write_json(plan_path, plan)
    rows: list[dict[str, Any]] = []
    todo: list[tuple[Path, int]] = []
    records = mc._case_records(case_paths(panel))
    # Seed by seed: every world's first play before any second play.
    for seed in plan["inference_seeds"]:
        for record in records:
            path = mc._result_path(run_root, case_id=record["case_id"], content_sha256=record["content_sha256"], seed=seed)
            if path.exists():
                rows.append(mc._read_result(path, case_id=record["case_id"], content_sha256=record["content_sha256"],
                                            seed=seed))
            else:
                todo.append((record["path"], seed))
    semaphore = asyncio.Semaphore(CONTROLS["max_parallel_cells"])
    limit = ceiling(subject, panel)
    per_cell = float(CONTROLS["max_cost_usd_per_trajectory"])
    width = CONTROLS["max_parallel_cells"]
    stop_after = CONTROLS["max_consecutive_operational_failures"]
    halted = None
    # Cells go in waves the size of the parallelism, so both stop rules are checked between waves on rows that exist.
    for start in range(0, len(todo), width):
        spent = sum(_spent(row) for row in rows)
        if spent + per_cell * min(width, len(todo) - start) > limit + 1e-9:
            halted = f"total cost ceiling: spent {spent:.4f} of {limit}"
            break
        tail = [row.get("status") for row in rows][-stop_after:]
        if len(tail) == stop_after and all(status == "operational_failure" for status in tail):
            halted = "consecutive operational failures"
            break
        rows.extend(await asyncio.gather(*(
            run_cell(subject=subject, run_root=run_root, case_path=case_path, seed=seed, semaphore=semaphore,
                     provider_factory=provider_factory)
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


def verify(subject: str, panel: str, run_root: Path) -> dict[str, Any]:
    """Offline replay of every completed row: its durable receipt re-driven through the environment and re-scored.

    No provider call. A row passes when the one receipt under its execution root is the one the row names and
    ``audit_family_receipt`` recomputes the same state and score from the sealed events.
    """
    plan = json.loads((run_root / "model_plan.json").read_text())
    if canonical_json_bytes(plan) != canonical_json_bytes(model_plan(subject, panel)):
        raise ValueError("run root was not written by this subject, panel and driver")
    artifact = json.loads((run_root / "summary.json").read_text())
    by_case = {record["case_id"]: record for record in mc._case_records(case_paths(panel))}
    checked = []
    for row in artifact["rows"]:
        seed = int(row["inference_seed"])
        if row["status"] != "completed":
            checked.append({"case_id": row["case_id"], "inference_seed": seed, "status": row["status"], "verified": None})
            continue
        record = by_case[row["case_id"]]
        root = _execution_root(run_root, record["case_id"], record["content_sha256"], seed)
        receipts = sorted(root.rglob("evaluation_receipt.json"))
        if len(receipts) != 1:
            raise ValueError(f"{row['case_id']} seed {seed}: expected one sealed receipt, found {len(receipts)}")
        audited = audit_family_receipt(setup=build_setup(subject, record["path"], seed), receipt_path=receipts[0])
        if audited["receipt_sha256"] != row["receipt_sha256"]:
            raise ValueError(f"{row['case_id']} seed {seed}: the sealed receipt is not the one the row names")
        checked.append({"case_id": row["case_id"], "inference_seed": seed, "status": row["status"], "verified": True,
                        "receipt_sha256": audited["receipt_sha256"], "replay_level": audited["replay_level"],
                        "scores": json.loads(canonical_json_bytes(audited["scores"]))})
    return {"campaign_id": plan["campaign_id"], "rows": checked,
            "verified": all(item["verified"] in (True, None) for item in checked)
            and any(item["verified"] for item in checked)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--subject", choices=sorted(SUBJECTS))
    parser.add_argument("--panel", choices=PANELS)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--env-file", type=Path, help="read OPENROUTER_API_KEY from this file (nothing else is read)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--probe", action="store_true", help="credit and catalog checks, then one strict call; no cell")
    mode.add_argument("--verify", action="store_true", help="offline replay of every completed receipt")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--write-freeze", type=Path, metavar="PILOT_REPORT_JSON",
                        help="write the confirmatory freeze from the pilot report (with --freeze-pack) and exit")
    parser.add_argument("--freeze-pack", default=pack_v2.PACK_ID)
    arguments = parser.parse_args()
    if arguments.write_freeze is not None:
        freeze = write_freeze(arguments.write_freeze, arguments.freeze_pack)
        print(json.dumps({"freeze": str(FREEZE_PATH), "freeze_sha256": freeze["freeze_sha256"],
                          "worlds": freeze["sizing_record"]["worlds"], "pack": freeze["pack"]["pack_id"]}, indent=1))
        return 0
    if arguments.subject is None or arguments.panel is None:
        parser.error("--subject and --panel are required")
    run_root = arguments.run_root or default_run_root(arguments.subject, arguments.panel)
    if arguments.verify:
        print(json.dumps(verify(arguments.subject, arguments.panel, run_root), indent=1))
        return 0
    if not (arguments.execute or arguments.probe):
        print(json.dumps({"run_root": str(run_root), "plan": model_plan(arguments.subject, arguments.panel)},
                         indent=2, sort_keys=True))
        return 0
    load_api_key(arguments.env_file)
    if arguments.probe:
        credit = read_credit()
        check_credit(credit)
        print(json.dumps({"credit_remaining_usd": credit["remaining_usd"],
                          "route": route_preflight(arguments.subject),
                          "probe": asyncio.run(probe(arguments.subject))}, indent=1))
        return 0
    artifact = asyncio.run(run(arguments.subject, arguments.panel, run_root, resume=arguments.resume))
    print(json.dumps({"campaign_id": artifact["plan"]["campaign_id"], "halted": artifact["halted"],
                      "credit_remaining_usd_at_start": artifact["preflight"]["credit_remaining_usd_at_start"],
                      "rows": [{k: row.get(k) for k in ("case_id", "inference_seed", "status", "decision",
                                                        "contribution_margin_usd", "action_count", "input_tokens",
                                                        "output_tokens", "cost_usd", "cost_accounting",
                                                        "elapsed_seconds", "failure_condition", "failure_message")}
                               for row in artifact["rows"]]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
