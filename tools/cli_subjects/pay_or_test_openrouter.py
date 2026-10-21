"""The pay-or-test pack played by three hosted flash models through OpenRouter.

Same twenty-four worlds and the same brief (prompt v2, ``finalquotes``) as the
Claude Code and Codex panels (``procurement_cli.py --pack pay_or_test_v1
--prompt finalquotes_v2``); only the subject and its transport differ. The
subjects are the three models of the Housing v14 confirmatory panel, on the
routes, reasoning settings and sampling controls that panel sealed, so the two
cases can be read side by side, with one exception:

    gemini38_flash       Gemini 3.8 Flash on Google AI Studio, reasoning minimal, temperature 0, top_p 1
    glm53_flash_morph    GLM 5.3 Flash on Morph fp8, reasoning low, temperature 0, top_p 1
    gpt6_luna            GPT-6 Luna on OpenAI, reasoning low, no temperature or top_p (the model takes neither)

The exception is GLM's route. Housing v14 sealed NextBit fp8, and that
endpoint left the OpenRouter catalog before this pack was played (P-O-05), so
GLM runs on the procurement family's earlier GLM route
(``model_campaign.GLM_MORPH_CANDIDATE``: same model revision and quantization,
Morph's prices) with Housing v14's reasoning and sampling settings. GLM's
plan says it breaks route parity with Housing v14.

Version 2 (identities ``..._gate_v2`` and ``..._v2``) replaces the family's
action schema by one the family parser agrees with (``action_output_schema``).
The first schema let a request's ``message`` be null, which the parser
rejects, and GPT-6 Luna's first action ended its v1 gate that way (P-D-23).
The v1 gate identities keep their cells; nothing is rerun under them.

and every control that can end a call, a cell or a run is the Housing v14
value and sealed into the plan: 4,096 output tokens a call, doubled on a
truncated answer up to 32,768; 300 s a call; eight attempts an action on
length, rate_limit, provider_5xx, empty_response, timeout and transport, with
exponential-jitter backoff from 2 s (doubling capped at 30 s, a provider's
Retry-After honoured up to 30 s); $0.30 a cell; three consecutive failed cells
stop the run; and a total ceiling a run never launches past.

Nothing is sent before two checks pass: the account holds at least
``CREDIT_FLOOR_USD`` of credit (``GET /api/v1/credits``), and the pinned
endpoint is in the OpenRouter catalog at or under the pinned price with every
parameter the strict client requires. A run root is created only after both,
so a route that is gone never consumes an identity.

This module is new and edits nothing that a sealed plan hashes. The plan
records this file's own digest, so a changed driver cannot resume a run root.

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/pay_or_test_openrouter.py \\
        --subject gemini38_flash --panel gate                       # plan only, no provider call
    ... --subject gemini38_flash --panel gate --probe --env-file <AERead>/.env   # one strict call
    ... --subject gemini38_flash --panel gate --execute --env-file <AERead>/.env
    ... --subject gemini38_flash --panel gate --verify               # offline replay of every receipt

Run roots default to ``runs/procurement_allocation/<campaign id less its family prefix>``
under this checkout, which ``pay_or_test_report.py runs/procurement_allocation`` reads.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import dataclasses
import hashlib
import json
import os
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.model_call.harness import MinimalChatHarness, default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import canonical_json_bytes, resolve_run_plan
from aeread.shared_runner.schemas import AgentProfile, RunSpec
from aeread.shared_runner.task.evaluation import audit_family_receipt
from aeread.shared_runner.task.execution import (
    OpenRouterChatClient,
    ProviderFailure,
    ProviderRequest,
    TokenPricing,
    execute_plan_cell,
)
from aeread_families.procurement_allocation import model_campaign as mc
from aeread_families.procurement_allocation import pay_or_test_case_matrix as pay_or_test
from aeread_families.procurement_allocation import pay_or_test_prompt
from aeread_families.procurement_allocation import runner
from aeread_families.procurement_grounding.bakeoff import BakeoffCandidate, preflight_candidate
from aeread_families.procurement_grounding.runner import OpenRouterRoute

REPOSITORY = Path(__file__).resolve().parents[2]
DRIVER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
RUNS_ROOT = REPOSITORY / "runs" / "procurement_allocation"
BASE_URL = "https://openrouter.ai/api/v1"
CREDITS_URL = f"{BASE_URL}/credits"
#: No paid call is made unless the account holds at least this much credit.
CREDIT_FLOOR_USD = 10.0

PACK = "pay_or_test_v1"
PROMPT_ARM = "finalquotes_v2"
PROMPT = {"prompt_id": pay_or_test_prompt.PROMPT_ID_V2, "text": pay_or_test_prompt.PAY_OR_TEST_PROMPT_V2,
          "treatment_id": pay_or_test_prompt.TREATMENT_ID_V2}
#: The gate plays the first ``test_cheapest`` world in the pack's own order (pack.json).
GATE_WORLD = "test_cheapest__tight__1"

VERSION = "v2"

#: The Housing v14 confirmatory route pins, copied value for value from
#: ``src/aeread_families/housing/price_campaign.py`` and ``housing/runner.py`` on
#: ``codex/housing-lemons-outside-demand``. The maximum price OpenRouter may route
#: to is the pinned list price, formatted as Housing formats it. GLM is the
#: exception: its Housing v14 route is gone (P-O-05), and it runs on the family's
#: earlier Morph route under its Housing v14 reasoning and sampling settings.
SUBJECTS: dict[str, dict[str, Any]] = {
    "gemini38_flash": {
        "route": OpenRouterRoute(
            profile_id="procurement_pay_or_test_gemini38_flash_v2",
            model="google/gemini-3.8-flash", revision="google/gemini-3.8-flash-20260902",
            route_provider="Google AI Studio", quantization="unknown",
            pricing=TokenPricing(0.75, 0.075, 3.75, "openrouter_google-ai-studio_2026-09-21_gemini-3.8-flash"),
            max_prompt_price_per_million="0.75", max_completion_price_per_million="3.75",
            reasoning_effort="minimal", temperature_supported=True,
        ),
        "temperature": 0.0, "top_p": 1.0,
        "housing_v14_identity": "housing_lemons_price_confirmatory_v14_gemini38_flash",
    },
    "glm53_flash_morph": {
        # model_campaign.GLM_MORPH_CANDIDATE's route as it stands (Morph, fp8, its prices), with this
        # driver's profile id and Housing v14's GLM reasoning effort (low, the same value it already holds).
        "route": dataclasses.replace(mc.GLM_MORPH_CANDIDATE.route, profile_id="procurement_pay_or_test_glm53_flash_morph_v2",
                                     reasoning_effort="low"),
        "temperature": 0.0, "top_p": 1.0,
        "housing_v14_identity": "housing_lemons_price_confirmatory_v14_glm53_flash_nextbit",
        "route_parity_with_housing_v14": False,
        # v1 named this subject by its Housing v14 route; the catalog check refused it before any run root existed.
        "v1_subject": "glm53_flash_nextbit",
        "housing_v14_route": {"provider": "NextBit", "quantization": "fp8",
                              "pricing_id": "openrouter_nextbit_2026-10-01_glm-5.3-flash-fp8",
                              "input_per_million_usd": 0.165, "cached_input_per_million_usd": 0.033,
                              "output_per_million_usd": 0.55},
        "route_note": "Housing v14's GLM route (NextBit fp8) left the OpenRouter catalog: the strict probe of "
                      "2026-10-13 answered 404, no allowed providers (P-O-05). This identity runs on the procurement "
                      "family's earlier GLM route, model_campaign.GLM_MORPH_CANDIDATE (Morph fp8), with Housing v14's "
                      "reasoning effort and sampling controls, and breaks route parity with Housing v14.",
    },
    "gpt6_luna": {
        "route": OpenRouterRoute(
            profile_id="procurement_pay_or_test_gpt6_luna_v2",
            model="openai/gpt-6-luna", revision="openai/gpt-6-luna-20260922",
            route_provider="OpenAI", quantization="unknown",
            pricing=TokenPricing(0.1, 0.01, 0.5, "openrouter_openai_2026-10-06_gpt-6-luna"),
            max_prompt_price_per_million="0.1", max_completion_price_per_million="0.5",
            reasoning_effort="low", temperature_supported=False,
        ),
        # The model takes no temperature or top_p. The profile's temperature is a
        # placeholder the request never sends (``sampling_controls``), as in Housing v14.
        "temperature": "unavailable", "top_p": None,
        "housing_v14_identity": "housing_lemons_price_confirmatory_v14_gpt6_luna",
    },
}

#: Housing v14's retry policy v2, every value as that panel sealed it.
RETRY_POLICY: dict[str, Any] = {
    "owner": "shared_runner",
    "max_action_attempts": 8,
    "retryable_conditions": ["length", "rate_limit", "provider_5xx", "empty_response", "timeout", "transport"],
    "length_retry_growth": {"factor": 2, "max_output_tokens_ceiling": 32768},
    "retry_backoff": {"policy": "exponential_jitter_v1", "retry_base_seconds": 2.0, "doubling_cap_seconds": 30.0,
                      "jitter": "0 to 1 s from the call id", "retry_after_max_seconds": 30.0},
    "session_mode": "restart",
    "sdk_retries": 0,
    "cost_boundary": "a retried timeout or transport failure may have been billed; the kernel cannot know, records "
                     "its cost as unknown, and a cell that had one reports a lower-bound cost",
}
CONTROLS: dict[str, Any] = {
    "max_logical_actions": pay_or_test.BUDGET_ACTIONS,
    "max_output_tokens": 4096,
    "timeout_seconds": 300.0,
    "max_cost_usd_per_trajectory": 0.30,
    "total_cost_ceiling_usd": {"gate": 0.30, "panel": 3.0},
    "max_consecutive_operational_failures": 3,
    "replicates": 1,
    "inference_seed": 87001,
    "max_parallel_cells": 3,
    "provider_stream": False,
}
HALT_RULE = ("a failed cell is typed missingness and is never rerun; the run stops launching cells after "
             "max_consecutive_operational_failures consecutive failed cells in execution order, or when the next wave "
             "could take the run past total_cost_ceiling_usd at max_cost_usd_per_trajectory a cell (a cell whose cost "
             "is unknown counts at that maximum)")


def campaign_id(subject: str, panel: str) -> str:
    stem = f"procurement_allocation_{PACK}_{PROMPT_ARM.split('_', 1)[0]}_openrouter_{subject}"
    return f"{stem}_gate_{VERSION}" if panel == "gate" else f"{stem}_{VERSION}"


ACTION_SCHEMA_ID = "procurement_pay_or_test_action_schema_v2"
#: What the family parser's ``_text`` accepts: a string holding a character that is not whitespace.
NON_EMPTY_TEXT: dict[str, Any] = {"type": "string", "pattern": "\\S"}
#: Replies the strict schema admits and the family parser still rejects. A strict provider schema is one flat
#: object (no branching on ``action`` at its root), so a field only some actions read cannot be required for
#: those actions alone. Each of these ends the episode as ``malformed_procurement_action`` and is scored as
#: walking away; ``tests/test_pay_or_test_openrouter.py`` pins that the list is complete.
SCHEMA_RESIDUAL = (
    "inquire with fields null",
    "inquire naming an inquiry field twice (uniqueItems is outside the strict subset)",
    "counter_offer with offer_id null or proposal null",
    "counter_offer whose proposal has every term null",
    "submit_award or check_award with award_lines null",
)


def action_output_schema(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The family's strict action object, tightened so that what it admits the family parser accepts.

    ``runner.procurement_action_output_schema`` makes every field required and
    nullable, because a strict schema cannot branch on the action. The parser
    keeps only the chosen action's own fields and then requires each one, so a
    null there passes the schema and fails the parser (P-D-23). This version
    closes every such gap one flat object can close:

    - ``supplier_id``, ``message`` and ``reason`` are a non-empty string on every
      action, the supplier one of this world's (the parser's ``unknown_supplier``
      check), listed in the order the buyer sees them. The parser reads each only
      on the actions that take it and drops it on the others.
    - ``fields`` is null or a non-empty list of this world's inquiry fields.
    - ``offer_id`` is null or a non-empty string; ``award_lines`` null or a
      non-empty list of lines, each a non-empty offer id and a quantity of at
      least one.
    - ``proposal`` is null or terms the parser accepts one by one: a price of at
      least zero, whole numbers of at least one, a freight payer of buyer or
      supplier.

    What one flat object cannot say is ``SCHEMA_RESIDUAL``.
    """
    schema = copy.deepcopy(runner.procurement_action_output_schema())
    properties = schema["properties"]
    suppliers = [str(s["supplier_id"]) for s in payload["suppliers"]]
    properties["supplier_id"] = {"type": "string", "enum": suppliers}
    properties["message"] = dict(NON_EMPTY_TEXT)
    properties["reason"] = dict(NON_EMPTY_TEXT)
    properties["fields"] = {"type": ["array", "null"], "minItems": 1,
                            "items": {"type": "string", "enum": list(payload["policy"]["inquiry_fields"])}}
    properties["offer_id"] = {"type": ["string", "null"], "pattern": NON_EMPTY_TEXT["pattern"]}
    terms = properties["proposal"]["properties"]
    terms["unit_price_usd"] = {"type": ["number", "null"], "minimum": 0}
    for name in ("moq", "payment_terms_days", "refund_window_days"):
        terms[name] = {"type": ["integer", "null"], "minimum": 1}
    terms["return_freight_payer"] = {"type": ["string", "null"], "enum": ["buyer", "supplier", None]}
    line = properties["award_lines"]["items"]
    line["properties"] = {"offer_id": dict(NON_EMPTY_TEXT), "quantity": {"type": "integer", "minimum": 1}}
    properties["award_lines"] = {"type": ["array", "null"], "minItems": 1, "items": line}
    if set(properties) != set(schema["required"]):
        raise AssertionError("every field of the strict object stays required")
    return schema


def _payload(case_path: Path) -> dict[str, Any]:
    return json.loads(case_path.read_text(encoding="utf-8"))["payload"]


def _schema_sha256(case_path: Path) -> str:
    return hashlib.sha256(canonical_json_bytes(action_output_schema(_payload(case_path)))).hexdigest()


def default_run_root(subject: str, panel: str) -> Path:
    return RUNS_ROOT / campaign_id(subject, panel).removeprefix("procurement_allocation_")


def case_paths(panel: str) -> list[Path]:
    paths = list(pay_or_test.case_paths())
    return [p for p in paths if p.stem == GATE_WORLD] if panel == "gate" else paths


def provider_metadata(route: OpenRouterRoute) -> dict[str, str]:
    return {
        "route_provider": route.route_provider, "quantization": route.quantization, "canonical_model": route.revision,
        "max_prompt_price_per_million": route.max_prompt_price_per_million,
        "max_completion_price_per_million": route.max_completion_price_per_million,
    }


def _route_block(subject: str) -> dict[str, Any]:
    spec = SUBJECTS[subject]
    route: OpenRouterRoute = spec["route"]
    return {
        "requested_model": route.model, "canonical_model": route.revision, "provider": route.route_provider,
        "quantization": route.quantization, "pricing_id": route.pricing.pricing_id,
        "input_per_million_usd": route.pricing.input_per_million,
        "cached_input_per_million_usd": route.pricing.cached_input_per_million,
        "output_per_million_usd": route.pricing.output_per_million,
        "max_price_per_million": {"prompt": route.max_prompt_price_per_million,
                                  "completion": route.max_completion_price_per_million},
        "reasoning_effort": route.reasoning_effort, "temperature": spec["temperature"], "top_p": spec["top_p"],
    }


def build_setup(subject: str, case_path: Path) -> runner.ProcurementAllocationSetup:
    """``runner.build_openrouter_setup`` with Housing v14's retry policy.

    That builder admits only rate_limit, provider_5xx and empty_response as
    retryable and fixes the output cap at the caller's value with no declared
    growth, so it cannot express v14's policy (timeout and transport retried,
    a truncated answer retried at double the cap). The profile is built the
    same way otherwise: same template, harness, runtime pins and capabilities.
    """
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
                         "max_output_tokens": CONTROLS["max_output_tokens"], "seed": CONTROLS["inference_seed"]},
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


def model_plan(subject: str, panel: str) -> dict[str, Any]:
    cases = mc._case_records(case_paths(panel))
    plan = {
        "schema_version": "aeread.procurement_allocation_openrouter_plan/0.1",
        "campaign_id": campaign_id(subject, panel),
        "claim_status": "development_gate" if panel == "gate" else "development_pilot",
        "pack": PACK, "prompt_arm": PROMPT_ARM,
        "cases": [{"case_id": r["case_id"], "content_sha256": r["content_sha256"]} for r in cases],
        "independent_case_count": len(cases),
        "inference_seeds": [CONTROLS["inference_seed"]],
        "inference_seed_meaning": "the OpenRouter request seed, the same declared value in every world; one play a world",
        "planned_trajectory_count": len(cases) * CONTROLS["replicates"],
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
        "controls": {**CONTROLS, "total_cost_ceiling_usd": CONTROLS["total_cost_ceiling_usd"][panel]},
        "retry_policy": RETRY_POLICY,
        "halt_rule": HALT_RULE,
        "response_cache": "disabled",
        "primary_outcomes": ["decision_loss_usd (pay_or_test_report)", *mc.DEFAULT_PRIMARY_OUTCOMES],
        "action_schema": {
            "schema_id": ACTION_SCHEMA_ID,
            "built_by": "action_output_schema in this driver, from runner.procurement_action_output_schema",
            "sha256_by_case": {r["case_id"]: _schema_sha256(r["path"]) for r in cases},
            "agrees_with": "ProcurementAllocationPlugin.parse_action: what the schema admits the parser accepts, "
                           "except the listed residual",
            "residual": list(SCHEMA_RESIDUAL),
            "residual_outcome": "the episode ends as malformed_procurement_action and is scored as walking away",
        },
        "comparability": _comparability(subject),
        "identity_history": {
            "supersedes": _v1_identity(subject, panel),
            "changed_from_v1": {
                "action_schema": "v1 sent runner.procurement_action_output_schema, which admits a null message the "
                                 "parser rejects (P-D-23); v2 sends action_output_schema",
                **({"route": SUBJECTS[subject]["route_note"]} if "route_note" in SUBJECTS[subject] else {}),
            },
            "v1_cells": "kept as they are; nothing is rerun under a v1 identity",
        },
        "claim_scope": "development probe of a hosted flash model on the pay-or-test pack; one play a world, "
                       "no model ranking from the gate",
        "driver": {"path": "tools/cli_subjects/pay_or_test_openrouter.py", "sha256": DRIVER_SHA256},
    }
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return plan


def _v1_identity(subject: str, panel: str) -> str:
    v1 = campaign_id(SUBJECTS[subject].get("v1_subject", subject), panel).removesuffix(f"_{VERSION}") + "_v1"
    if "v1_subject" in SUBJECTS[subject]:
        return f"{v1} (never created: the catalog check refused its route before a run root existed, P-O-05)"
    return v1


def _comparability(subject: str) -> dict[str, Any]:
    spec = SUBJECTS[subject]
    parity = spec.get("route_parity_with_housing_v14", True)
    same = ["model", "revision", "provider", "quantization", "pricing", "reasoning_effort",
            "temperature", "top_p", "max_output_tokens", "length_retry_growth", "timeout_seconds",
            "max_action_attempts", "retryable_conditions", "retry_backoff", "sdk_retries",
            "max_cost_usd_per_trajectory", "max_consecutive_operational_failures"]
    differs: dict[str, Any] = {
        "request_seed": "Housing derived one seed a cell from base 87001 (paired_cell_v1); here 87001 is sent in every world",
        "max_logical_actions": "the pack's own budget of ten actions",
        "total_cost_ceiling_usd": "this run's own",
        "action_schema": "this pack's own (procurement action schema, tightened to the family parser)",
    }
    if not parity:
        same = [item for item in same if item not in ("provider", "pricing")]
        differs["route"] = {"housing_v14": spec["housing_v14_route"], "here": _route_block(subject),
                            "why": spec["route_note"]}
    return {"housing_v14_identity": spec["housing_v14_identity"], "route_parity_with_housing_v14": parity,
            "same_as_housing_v14": same, "differs_from_housing_v14": differs}


def load_api_key(env_file: Path | None) -> None:
    """Put OPENROUTER_API_KEY in the environment from ``env_file``; read nothing else and print nothing."""
    if os.environ.get("OPENROUTER_API_KEY") or env_file is None:
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.strip().partition("=")
        if separator and name.removeprefix("export ").strip() == "OPENROUTER_API_KEY":
            os.environ["OPENROUTER_API_KEY"] = value.strip().strip('"').strip("'")
            return
    raise RuntimeError(f"no OPENROUTER_API_KEY in {env_file}")


def read_credit() -> dict[str, float]:
    """Remaining account credit from ``GET /api/v1/credits``. The key goes in the header and nowhere else."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is required for the credit check")
    request = urllib.request.Request(CREDITS_URL, headers={"Authorization": f"Bearer {key}",
                                                           "User-Agent": "AERead pay-or-test/1.0"})
    with urllib.request.urlopen(request, timeout=30.0) as response:
        data = json.load(response)["data"]
    total, used = float(data["total_credits"]), float(data["total_usage"])
    return {"total_credits_usd": total, "total_usage_usd": used, "remaining_usd": round(total - used, 6)}


def check_credit(credit: Mapping[str, float]) -> None:
    if credit["remaining_usd"] < CREDIT_FLOOR_USD:
        raise RuntimeError(f"OpenRouter credit {credit['remaining_usd']:.2f} is under the {CREDIT_FLOOR_USD:.2f} floor; "
                           "no call was made")


def route_preflight(subject: str) -> dict[str, Any]:
    """The catalog check: the pinned endpoint exists, at or under the pin, with every strict parameter."""
    route: OpenRouterRoute = SUBJECTS[subject]["route"]
    return preflight_candidate(BakeoffCandidate(candidate_id=subject, route=route, lane="standard",
                                                access_class="hosted", license_id=None, model_card_url=None))


async def probe(subject: str, client: Any | None = None) -> dict[str, Any]:
    """One strict call on the sealed route: the gate world's action schema, the seed, require_parameters, the reasoning effort.

    Not a cell: no world is played, nothing scored, nothing written into a run root. The reply goes through the
    family parser, so a probe also shows whether the route's answer under this schema is one the parser accepts.
    """
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
        seed=CONTROLS["inference_seed"],
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


def parse_reply(case_path: Path, text: str) -> dict[str, Any]:
    """What the family parser makes of a reply in a world: ``{"ok": True}`` or the failure code it returns."""
    plugin = runner.ProcurementAllocationPlugin()
    family_case = plugin.validate_payload(_payload(case_path))
    phase = plugin.phases(family_case)[0]
    parsed = plugin.parse_action(family_case, plugin.initial_state(family_case, None), "buyer", phase, text)
    return {"ok": True} if parsed.ok else {"ok": False, "failure_code": parsed.error_code}


def _calls(execution: Any) -> list[Any]:
    return [call for action in execution.action_executions for attempt in action.attempts
            for call in attempt.provider_calls]


async def run_cell(*, subject: str, run_root: Path, case_path: Path, semaphore: asyncio.Semaphore,
                   provider_factory: Callable[[], Any]) -> dict[str, Any]:
    """``model_campaign._run_cell`` on this driver's setup; the row has the same fields."""
    seed = CONTROLS["inference_seed"]
    setup = build_setup(subject, case_path)
    cell = setup.plan.cells[0]
    directory = mc._safe_case_directory(setup.case.case_id, setup.case.content_sha256)
    evidence_root = run_root / "executions" / directory / f"seed_{seed}"
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
    seed = CONTROLS["inference_seed"]
    rows: list[dict[str, Any]] = []
    todo: list[Path] = []
    for record in mc._case_records(case_paths(panel)):
        path = mc._result_path(run_root, case_id=record["case_id"], content_sha256=record["content_sha256"], seed=seed)
        if path.exists():
            rows.append(mc._read_result(path, case_id=record["case_id"], content_sha256=record["content_sha256"], seed=seed))
        else:
            todo.append(record["path"])
    semaphore = asyncio.Semaphore(CONTROLS["max_parallel_cells"])
    ceiling = float(CONTROLS["total_cost_ceiling_usd"][panel])
    per_cell = float(CONTROLS["max_cost_usd_per_trajectory"])
    width = CONTROLS["max_parallel_cells"]
    stop_after = CONTROLS["max_consecutive_operational_failures"]
    halted = None
    # Cells go in waves the size of the parallelism, so both stop rules are checked between waves on rows that exist.
    for start in range(0, len(todo), width):
        spent = sum(_spent(row) for row in rows)
        if spent + per_cell * min(width, len(todo) - start) > ceiling + 1e-9:
            halted = f"total cost ceiling: spent {spent:.4f} of {ceiling}"
            break
        tail = [row.get("status") for row in rows][-stop_after:]
        if len(tail) == stop_after and all(status == "operational_failure" for status in tail):
            halted = "consecutive operational failures"
            break
        rows.extend(await asyncio.gather(*(
            run_cell(subject=subject, run_root=run_root, case_path=case_path, semaphore=semaphore,
                     provider_factory=provider_factory)
            for case_path in todo[start:start + width])))
    rows.sort(key=lambda row: (str(row["case_id"]), int(row["inference_seed"])))
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

    No provider call. A row passes when the receipt under its execution root is the one the row names and
    ``audit_family_receipt`` recomputes the same state and score from the sealed events.
    """
    plan = json.loads((run_root / "model_plan.json").read_text())
    if canonical_json_bytes(plan) != canonical_json_bytes(model_plan(subject, panel)):
        raise ValueError("run root was not written by this subject, panel and driver")
    artifact = json.loads((run_root / "summary.json").read_text())
    by_case = {record["case_id"]: record for record in mc._case_records(case_paths(panel))}
    checked = []
    for row in artifact["rows"]:
        if row["status"] != "completed":
            checked.append({"case_id": row["case_id"], "status": row["status"], "verified": None})
            continue
        record = by_case[row["case_id"]]
        root = run_root / "executions" / mc._safe_case_directory(record["case_id"], record["content_sha256"]) / f"seed_{row['inference_seed']}"
        receipts = sorted(root.rglob("evaluation_receipt.json"))
        if len(receipts) != 1:
            raise ValueError(f"{row['case_id']}: expected one sealed receipt, found {len(receipts)}")
        audited = audit_family_receipt(setup=build_setup(subject, record["path"]), receipt_path=receipts[0])
        if audited["receipt_sha256"] != row["receipt_sha256"]:
            raise ValueError(f"{row['case_id']}: the sealed receipt is not the one the row names")
        checked.append({"case_id": row["case_id"], "status": row["status"], "verified": True,
                        "receipt_sha256": audited["receipt_sha256"], "replay_level": audited["replay_level"],
                        "scores": json.loads(canonical_json_bytes(audited["scores"]))})
    return {"campaign_id": plan["campaign_id"], "rows": checked,
            "verified": all(item["verified"] in (True, None) for item in checked)
            and any(item["verified"] for item in checked)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--subject", choices=sorted(SUBJECTS), required=True)
    parser.add_argument("--panel", choices=("gate", "panel"), required=True)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--env-file", type=Path, help="read OPENROUTER_API_KEY from this file (nothing else is read)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--probe", action="store_true", help="credit and catalog checks, then one strict call; no cell")
    mode.add_argument("--verify", action="store_true", help="offline replay of every completed receipt")
    parser.add_argument("--resume", action="store_true")
    arguments = parser.parse_args()
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
                      "rows": [{k: row.get(k) for k in ("case_id", "status", "decision", "regret_to_upper_bound_usd",
                                                        "action_count", "input_tokens", "output_tokens", "cost_usd",
                                                        "cost_accounting", "elapsed_seconds", "failure_condition",
                                                        "failure_message")}
                               for row in artifact["rows"]]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
