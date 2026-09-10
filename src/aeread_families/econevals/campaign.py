"""Frozen first-live campaign for the econevals external adapter (issue #90).

One unscored admission canary plus a six-case panel -- two cases from each
of the three tracks -- on the pinned OpenRouter GLM 5.3 Flash/Parasail
route, executed sequentially, aborting on the first operational failure.

What this campaign is for: the econevals family is the matrix's *pipeline
validator*, because its scorer is checked against an exact optimum that
upstream's own solvers compute (gurobipy for procurement, scipy for
pricing) rather than against a reimplementation of ours. A live panel here
exercises the same path procurement's oracle does -- model -> declared
tools -> sealed receipt -> offline replay -> measured headroom against a
known-correct optimum.

Every case is the pinned corpus case, unmodified: its payload, its
``pins.max_steps``, and its content digest are the ones the corpus
admission gate reproduces byte-for-byte from the ``(track, difficulty,
seed)`` triple.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from aeread.shared_runner.run.publication import (
    SANITIZATION_DECLARATION,
    assert_public_payload,
    atomic_publish,
    jsonl,
    receipt_projection,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import (
    finalize_family_execution,
    replay_family_receipt,
)
from aeread.shared_runner.task.execution import (
    OpenRouterChatClient,
    ProviderRequest,
    execute_plan_cell,
)
from aeread.shared_runner.analysis.research import deserialize_evaluation_receipt
from aeread.shared_runner.task.receipts import read_evaluation_receipt

from .cases import UPSTREAM_COMMIT, UPSTREAM_REPO
from .econevals_bridge import EconevalsBridge, discover_bridge_python
from .live import (
    MODEL,
    PRICING,
    PROMPT,
    PROVIDER,
    QUANTIZATION,
    GLM53_FLASH_PARASAIL,
    GPT4O_20240806_OPENAI,
    MAX_OUTPUT_TOKENS_UNCONSTRAINED,
    REASONING_UNCONSTRAINED_V1,
    RouteSpec,
    REVISION,
    ROUTE_PROVIDER,
    build_live_setup,
    load_case,
    period_output_schema,
    route_metadata,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
# v1 asked the model to submit BLIND: one call per period, the whole burst
# executed afterwards, so nothing it looked up could inform what it
# submitted. That is not upstream's task -- upstream loops within the period
# and feeds each tool result back -- and it is why v1 scored gate = 0.0 on
# five of six cases. v2 runs the loop, which makes it a different experiment
# rather than a re-run, so it publishes alongside v1 instead of over it.
# v3, not a rerun of v2: the reasoning condition is a frozen control, and a
# changed frozen control takes a new campaign identity rather than a new
# attempt under the old one (CLAUDE.md, "Campaign discipline"). v2's three
# scored cases stand as v2's; they are not pooled with these.
# v10: the reasoning cap is declared again, because measuring it properly
# showed it works. See REASONING_DECLARATION for the numbers: 31 characters of
# reasoning median with the block, ~12,000 without, on the same case and route.
#
# v9: no reasoning control,
# a 4,000-token output ceiling (the cheapest of four values all of which fail
# at the same rate), $0.20 per trajectory and $1.30 total.
#
# The residual failure is a draw, not a fixed set of hard cases: the same case
# has passed and failed under identical wire configurations. So a panel attempt
# that ends in an operational failure is re-attempted whole, and the number of
# attempts is published with the result. That is a selection over attempts and
# it is disclosed; it is not a selection over cases, and no case is ever rerun
# on its own.
#
# v8: the output ceiling is raised to 24,000 and the cost ceilings with it.
# Sized from evidence -- every call that produced a usable action needed
# 4,521-7,070 output tokens, so 4,000 could not succeed on a long-reasoning
# call. The cost ceilings are raised in the same declaration rather than
# discovered mid-run: $0.60 per trajectory and $4.00 total. Both are declared
# before the run, and if the run exceeds them it stops, as before.
#
# v7: v6 ran at a 12,000 output budget and that made things worse -- reasoning
# expands to fill whatever it is given -- so the budget is back at 4,000. That
# is a changed frozen control, hence a new identity rather than another
# attempt under v6.
#
# The declaration is now final and deliberately minimal: no reasoning control
# (this route honours none), 4,000 output tokens, canary given the same
# headroom as the panel. Nothing here is tuned to a case. The residual failure
# mode -- an episode where the model emits no parseable action -- is a
# property of the route and is recorded as an operational failure when it
# happens, not designed around.
#
# v6: the reasoning controls were never the lever. This route honours neither
# `reasoning.effort` nor `reasoning.max_tokens`, and the budget that governs is
# `profile.sampling.max_output_tokens`, which the harness clamps every request
# to. Raised 4,000 -> 12,000; no reasoning control declared.
#
# v5: v4's plan restated the reasoning condition as a literal instead of
# deriving it, so the plan advertised effort "low" for a panel that ran with no
# effort and a 1,500-token cap, and the admission canary proved the route under
# "low" as well. The panel's six measurements were real, but a route admitted
# under one reasoning condition does not attest a panel run under another, and
# a bundle must not state a frozen control it did not use. v4 is retired
# unpublished; the condition is now derived from one declaration.
#
# v4: v3 declared effort and token_budget together, which OpenRouter rejects
# with a 400 (#133). v3 therefore produced no measurement at all -- one
# operational-failure checkpoint at $0.00, billed nothing -- and is retired
# rather than reused, so a campaign identity never names two declarations.
# v11 is v10's panel with one control changed and therefore a new identity:
# the reasoning condition. v10 declared `reasoning_capped_1500_v1`, measured
# on 2026-09-10 to suppress reasoning to ~13 tokens whatever its value, so it
# measured a GLM 5.3 Flash that did not deliberate -- which is not the agent
# the EconEvals paper's table describes.
#
# The unconstrained arm was tried here before and failed three times, at the
# 4,000-token completion ceiling; the rationale is emitted inside that
# budget, so the ceiling is what makes the retry a different experiment
# rather than a repeat. TERMS-Bench ran the same condition at 12,000 over 30
# cases with no truncation, which is the evidence for trying it here.
CAMPAIGN_ID = "econevals_glm53_flash_parasail_panel_v11"
REASONING_DECLARATION = REASONING_UNCONSTRAINED_V1
MAX_OUTPUT_TOKENS = MAX_OUTPUT_TOKENS_UNCONSTRAINED

# The panel that checks this adapter against the paper rather than using it.
# GPT-4o is the only one of the paper's three agents this route can serve,
# and the paper's Basic-tier scores for it are procurement 43.8, scheduling
# 37.4 and pricing 76.1 -- targets recorded here before the run.
#
# It declares no reasoning block, which for a model without reasoning
# controls is simply the ordinary request, and the strict schema dialect
# `gpt-4o` requires: OpenAI's structured outputs cannot express an open
# argument map, so the tool call carries `arguments_json` instead. Same
# action space, different wire form.
PAPER_MODEL_CAMPAIGN_ID = "econevals_gpt4o_20240806_panel_v1"
PAPER_MODEL_ROUTE = GPT4O_20240806_OPENAI
PAPER_MODEL_TARGETS = MappingProxyType(
    {"procurement": 43.8, "scheduling": 37.4, "pricing": 76.1}
)
CANARY_CASE_ID = "econevals.procurement.basic.0"
PANEL_CASE_IDS = (
    "econevals.procurement.basic.0",
    "econevals.procurement.basic.1",
    "econevals.scheduling.basic.0",
    "econevals.scheduling.basic.1",
    "econevals.pricing.basic.0",
    "econevals.pricing.basic.1",
)
PANEL_STRATA = (
    "procurement_exact_optimum_gurobi",
    "procurement_exact_optimum_gurobi",
    "scheduling_stable_matching",
    "scheduling_stable_matching",
    "pricing_monopoly_reference_scipy",
    "pricing_monopoly_reference_scipy",
)
SEED = 300
MAX_PARALLEL_CELLS = 1
MAX_CANARY_COST_USD = 0.01
# The canary must be able to answer under the same conditions as the panel.
# At 256 it could only answer while a reasoning control kept the model brief;
# once v6 stopped declaring one -- because this route honours none -- the
# canary reasoned past its own budget and returned unparseable output, and a
# route that works was rejected as if it did not. A canary tuned tighter than
# the run it admits tests the canary, not the route. Billing is per token
# emitted, so the wider ceiling costs nothing on a call that answers briefly.
MAX_CANARY_OUTPUT_TOKENS = 12000
# A transient condition on an UNSCORED, zero-cost probe must not seal the
# attempt root: the probe produces no measurement, so re-probing changes
# nothing about what is measured. Every probe is still recorded write-once
# under its own ordinal, so the audit trail shows exactly how many were
# needed and why each failed. Non-transient rejections still stop the run.
# See docs/families/procurement-allocation/design_review.md, which recorded
# this defect after it sealed two attempt roots there.
CANARY_TRANSIENT_CONDITIONS = ("rate_limit", "provider_5xx", "timeout")
MAX_CANARY_PROBES = 6
CANARY_RETRY_BASE_SECONDS = 15.0
# The in-period loop costs more than the blind single-burst shape: measured
# $0.0614 for 78 periods against v1's $0.0109 for 100. Not because the loop
# makes many more calls -- it averages 1.01 per period -- but because the
# provider bills growing input against a request that never changes (see
# issue #130; our own request is flat at ~1.1KB, verified with a stub over
# 100 periods). The ceiling is raised to fit the measurement rather than the
# estimate, and the panel ceiling with it.
# Deliberation is emitted inside the completion budget, so a 100-period case
# costs several times what v10's suppressed arm did. Both limits are raised
# to leave the cap above the worst case rather than have the ceiling stop
# the run.
MAX_TRAJECTORY_COST_USD = 0.80
HARD_TOTAL_COST_CEILING_USD = 5.00


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _write_once_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"refusing to replace different artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


ACTIVE_ROUTE: RouteSpec = GLM53_FLASH_PARASAIL
ACTIVE_CAMPAIGN_ID: str = CAMPAIGN_ID


def _use_paper_model() -> None:
    """Point this module at the paper-model panel.

    econevals keeps one identity per module rather than a registry, so the
    switch is explicit and total: campaign id, route, and the reasoning
    condition that goes with an ordinary non-reasoning request.
    """
    global ACTIVE_ROUTE, ACTIVE_CAMPAIGN_ID
    ACTIVE_ROUTE = PAPER_MODEL_ROUTE
    ACTIVE_CAMPAIGN_ID = PAPER_MODEL_CAMPAIGN_ID


def build_campaign_plan() -> dict[str, Any]:
    cases = [load_case(case_id) for case_id in PANEL_CASE_IDS]
    # EXECUTION sources only. campaign.py is deliberately absent: it carries
    # the publisher as well as the executor, so hashing it here would make a
    # publisher bug unfixable for a completed run -- publish with the bug, or
    # fix it and have the freeze reject the very run it governed. The
    # publisher's own digest is recorded in the publication manifest instead,
    # where it belongs: it describes how evidence was projected, not what was
    # executed.
    source_names = (
        "cases.py",
        "econevals_bridge.py",
        "environment.py",
        "live.py",
        "measurement.py",
        "tools.py",
    )
    source_hashes = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in source_names
    }
    plan: dict[str, Any] = {
        "schema_version": "aeread.econevals_live_campaign/0.1",
        "campaign_id": ACTIVE_CAMPAIGN_ID,
        "freeze_status": "first_light_frozen_before_live_execution",
        "upstream": {"repository": UPSTREAM_REPO, "commit": UPSTREAM_COMMIT},
        "route": {
            "provider": PROVIDER,
            "model": ACTIVE_ROUTE.model,
            "revision": ACTIVE_ROUTE.revision,
            "route_provider": ACTIVE_ROUTE.route_provider,
            "quantization": ACTIVE_ROUTE.quantization,
            "fallbacks": "disabled",
            # Derived, never restated. A literal here advertised
            # reasoning_effort "low" into published evidence for a panel that
            # ran with no effort and a 1,500-token cap.
            "reasoning_condition_id": REASONING_DECLARATION["condition_id"],
            "reasoning_effort": REASONING_DECLARATION["effort"],
            "reasoning_token_budget": REASONING_DECLARATION["token_budget"],
            "route_attestation": "openrouter_provider_order_pinned",
            "provider_cost_status": "response_reported",
            "provider_seed_status": "requested",
            "pricing_id": ACTIVE_ROUTE.pricing.pricing_id,
            "pricing_sha256": ACTIVE_ROUTE.pricing.content_sha256(),
        },
        "canary": {
            "case_id": CANARY_CASE_ID,
            "scored": False,
            "max_cost_usd": MAX_CANARY_COST_USD,
            "max_output_tokens": MAX_CANARY_OUTPUT_TOKENS,
            # Declared before execution so the re-probe budget is part of the
            # frozen contract, not an operator decision taken after a 429.
            "max_probes": MAX_CANARY_PROBES,
            "transient_conditions": list(CANARY_TRANSIENT_CONDITIONS),
            "retry_base_seconds": CANARY_RETRY_BASE_SECONDS,
            "probes_are_recorded_individually": True,
        },
        "panel": [
            {
                "case_id": case.case_id,
                "case_content_sha256": case.content_sha256,
                "track": case.payload["track"],
                "world_seed": case.payload["seed"],
                "max_steps": case.payload["pins"]["max_steps"],
                "stratum": stratum,
                "seed": SEED,
                "max_cost_usd": MAX_TRAJECTORY_COST_USD,
            }
            for case, stratum in zip(cases, PANEL_STRATA, strict=True)
        ],
        "execution": {
            "max_parallel_cells": MAX_PARALLEL_CELLS,
            "abort_on_operational_failure": True,
            "resume_only_failure_free_checkpoints": True,
            "publish_only": True,
            "scored_case_count": len(PANEL_CASE_IDS),
        },
        "budget": {
            "hard_total_cost_ceiling_usd": HARD_TOTAL_COST_CEILING_USD,
            "planned_maximum_usd": MAX_CANARY_COST_USD
            + len(PANEL_CASE_IDS) * MAX_TRAJECTORY_COST_USD,
            "canary_included": True,
        },
        "execution_source_sha256": source_hashes,
    }
    plan["plan_sha256"] = _digest(plan)
    return plan


def _verify_plan(value: Mapping[str, Any]) -> None:
    recorded = value.get("plan_sha256")
    payload = {key: item for key, item in value.items() if key != "plan_sha256"}
    if recorded != _digest(payload):
        raise ValueError("campaign plan digest mismatch")
    expected = build_campaign_plan()
    if canonical_json_bytes(value) != canonical_json_bytes(expected):
        raise ValueError("campaign plan differs from the frozen implementation")


def _route_metadata() -> dict[str, str]:
    """One shared route seal for the canary and every panel cell."""
    return route_metadata()


async def _probe_canary(
    *, path: Path, plan_sha256: str, ordinal: int
) -> dict[str, Any]:
    if path.exists():
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("plan_sha256") != plan_sha256 or value.get(
            "record_sha256"
        ) != _digest({k: v for k, v in value.items() if k != "record_sha256"}):
            raise ValueError("canary checkpoint does not match the frozen plan")
        return value
    request = ProviderRequest(
        provider_call_id="econevals_first_light_canary",
        provider=PROVIDER,
        base_url="https://openrouter.ai/api/v1",
        model=ACTIVE_ROUTE.model,
        revision=ACTIVE_ROUTE.revision,
        instructions=PROMPT,
        input_text=canonical_json_bytes(
            {
                "phase_id": "route_admission",
                "case_id": CANARY_CASE_ID,
                "instruction": (
                    "Return a single no-op call list for route admission: one "
                    "read_notes call and nothing else."
                ),
            }
        ).decode("utf-8"),
        temperature=0.0,
        top_p=None,
        max_output_tokens=MAX_CANARY_OUTPUT_TOKENS,
        # The canary must prove the route under the panel's own reasoning
        # condition. Admitting on "low" and then running the panel capped
        # means the admission attests a configuration that never executed.
        reasoning_effort=REASONING_DECLARATION["effort"],
        reasoning_token_budget=REASONING_DECLARATION["token_budget"],
        timeout_seconds=180.0,
        request_sha256="",
        max_cost_usd=MAX_CANARY_COST_USD,
        output_schema=period_output_schema(ACTIVE_ROUTE.output_schema_dialect),
        provider_metadata=route_metadata(ACTIVE_ROUTE),
        seed=SEED,
    ).with_computed_hash()
    record: dict[str, Any] = {
        "schema_version": "aeread.provider_admission_canary/0.1",
        "campaign_id": ACTIVE_CAMPAIGN_ID,
        "plan_sha256": plan_sha256,
        "case_id": CANARY_CASE_ID,
        "scored": False,
        "probe_ordinal": ordinal,
        "request_sha256": request.request_sha256,
        "model": MODEL,
        "revision": REVISION,
        "route_provider": ROUTE_PROVIDER,
        "attempted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    result = None
    try:
        result = await OpenRouterChatClient().complete(request)
        value = json.loads(result.output_text)
        calls = value.get("calls")
        if not isinstance(calls, list) or not calls:
            raise ValueError("canary did not return the required structured calls list")
        cost = float(result.cost_usd or 0.0)
        if cost > MAX_CANARY_COST_USD:
            raise ValueError("canary exceeded its cost ceiling")
        record.update(
            {
                "status": "admitted",
                "resolved_model": result.resolved_model,
                "finish_reason": result.finish_reason,
                "input_tokens": result.input_tokens,
                "cached_input_tokens": result.cached_input_tokens,
                "output_tokens": result.output_tokens,
                "cost_usd": cost,
            }
        )
    except Exception as error:
        cost = float(result.cost_usd or 0.0) if result is not None else 0.0
        record.update(
            {
                "status": "rejected",
                "failure_type": type(error).__name__,
                "failure_condition": getattr(error, "condition", "canary_rejected"),
                "cost_usd": cost,
            }
        )
    record["record_sha256"] = _digest(record)
    _write_once_json(path, record)
    return record


def _sealed_spend(evidence_root: Path) -> float:
    """Provider spend already sealed under a run, receipted or not.

    A case that dies partway has run real calls and paid for them, but its
    failure checkpoint has no completed execution to read a cost from. The
    spend is in the evidence tree regardless, so it is recovered from there:
    an unrecorded cost is still a cost, and a ledger that omits it
    understates what a failed attempt consumed.
    """
    total = 0.0

    def walk(value: Any) -> None:
        nonlocal total
        if isinstance(value, Mapping):
            cost = value.get("cost_usd")
            if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                total += float(cost)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for path in evidence_root.rglob("artifacts/sha256/*/*"):
        if not path.is_file():
            continue
        try:
            walk(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            continue
    return total


async def run_canary(*, run_root: Path, plan_sha256: str) -> dict[str, Any]:
    """Admit the route, re-probing only on typed transient conditions.

    Returns the admitted probe, or the last rejection when every allowed
    probe failed. Each probe is sealed write-once under its own ordinal.
    """
    directory = run_root / "checkpoints" / "canary_probes"
    record: dict[str, Any] = {}
    for ordinal in range(1, MAX_CANARY_PROBES + 1):
        record = await _probe_canary(
            path=directory / f"{ordinal:03d}.json",
            plan_sha256=plan_sha256,
            ordinal=ordinal,
        )
        if record.get("status") == "admitted":
            return record
        if record.get("failure_condition") not in CANARY_TRANSIENT_CONDITIONS:
            return record
        if ordinal < MAX_CANARY_PROBES:
            await asyncio.sleep(CANARY_RETRY_BASE_SECONDS * ordinal)
    return record


async def execute_campaign(*, run_root: Path, max_cases: int | None = None) -> None:
    """Run the canary, then the panel.

    `max_cases` is an operator's pause, not a frozen control: it stops after
    that many complete checkpoints so the first case can be read before the
    rest of the panel spends. It matters here because the unconstrained arm
    failed three times at the old ceiling, and a panel is not the place to
    discover that again. The plan is unchanged by it and the run resumes
    from its checkpoints without it.
    """
    if max_cases is not None and max_cases < 1:
        raise ValueError("max_cases must be at least 1")
    plan_path = run_root / "campaign_plan.json"
    plan = build_campaign_plan()
    _write_once_json(plan_path, plan)
    _verify_plan(json.loads(plan_path.read_text(encoding="utf-8")))
    bridge = EconevalsBridge(python_executable=discover_bridge_python())
    canary = await run_canary(run_root=run_root, plan_sha256=plan["plan_sha256"])
    if canary.get("status") != "admitted":
        raise RuntimeError("econevals canary was rejected; campaign stopped")
    total_cost = float(canary["cost_usd"])
    provider = OpenRouterChatClient()
    completed = 0
    for ordinal, case_id in enumerate(PANEL_CASE_IDS):
        if max_cases is not None and completed >= max_cases:
            return
        checkpoint_path = run_root / "checkpoints" / f"{ordinal:02d}_{case_id}.json"
        if checkpoint_path.exists():
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            recorded = checkpoint.get("record_sha256")
            payload = {k: v for k, v in checkpoint.items() if k != "record_sha256"}
            if (
                checkpoint.get("status") != "complete"
                or checkpoint.get("plan_sha256") != plan["plan_sha256"]
                or recorded != _digest(payload)
            ):
                raise RuntimeError("campaign cannot resume from a failed checkpoint")
            total_cost += float(checkpoint["cost_usd"])
            completed += 1
            continue
        if total_cost + MAX_TRAJECTORY_COST_USD > HARD_TOTAL_COST_CEILING_USD:
            raise RuntimeError("insufficient campaign budget reserve for the next case")
        setup = build_live_setup(
            case_id=case_id,
            bridge=bridge,
            seed=SEED,
            max_trajectory_cost_usd=MAX_TRAJECTORY_COST_USD,
            reasoning=REASONING_DECLARATION,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            route=ACTIVE_ROUTE,
        )
        execution_root = run_root / "executions" / case_id
        if execution_root.exists():
            # A case with no complete checkpoint but existing evidence died
            # mid-execution -- a killed process, an interrupted operator. Its
            # event log is partial, and the evidence store rightly refuses to
            # append to one. The partial log is still evidence of what was
            # attempted and what it cost, so it is moved aside rather than
            # deleted, and this case restarts on a clean root.
            superseded = run_root / "executions" / (
                f"{case_id}.superseded_"
                f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            )
            execution_root.rename(superseded)
        try:
            execution = await execute_plan_cell(
                plan=setup.plan,
                cell_id=setup.plan.cells[0].cell_id,
                registry=setup.registry,
                evidence_root=execution_root,
                prompt_sources=setup.prompt_sources,
                providers={PROVIDER: provider},
                pricing=setup.pricing,
                harnesses=setup.harnesses,
                tool_runtime_factories=setup.tool_runtime_factories,
            )
            receipt = finalize_family_execution(setup=setup, execution=execution)
            # An excluded receipt is a MEASUREMENT outcome, not an operational
            # failure: the pipeline ran, the episode sealed, and the verifier
            # judged the model's own submission invalid. Aborting the panel on
            # it would make the panel unable to report the very thing it
            # measures. Only a broken pipeline (a receipt that did not finalize
            # at all) stops the run; inclusion is recorded per case and the
            # publisher reports it.
            if receipt.status not in {"ok", "invalid_measurement"}:
                raise RuntimeError(
                    f"econevals case produced an unusable receipt: {receipt.status}"
                )
            replayed = replay_family_receipt(
                setup=setup,
                receipt=receipt,
                evidence_root=execution_root,
            )
            if replayed.receipt_sha256 != receipt.receipt_sha256:
                raise RuntimeError("receipt replay digest mismatch")
            cost = float(execution.total_cost_usd)
            total_cost += cost
            if total_cost > HARD_TOTAL_COST_CEILING_USD:
                raise RuntimeError("campaign exceeded its hard total cost ceiling")
            receipt_path = execution.evidence.root / "evaluation_receipt.json"
            checkpoint = {
                "schema_version": "aeread.econevals_checkpoint/0.1",
                "campaign_id": ACTIVE_CAMPAIGN_ID,
                "plan_sha256": plan["plan_sha256"],
                "ordinal": ordinal,
                "case_id": case_id,
                "status": "complete",
                "run_plan_id": setup.plan.run_plan_id,
                "run_plan_sha256": setup.plan.plan_sha256,
                "receipt_path": str(receipt_path.relative_to(run_root)),
                "receipt_sha256": receipt.receipt_sha256,
                "receipt_replayed": True,
                "receipt_status": receipt.status,
                "inclusion_status": receipt.inclusion_status,
                "cost_usd": cost,
                "termination_reason": execution.episode_result.outcome[
                    "termination_reason"
                ],
                "period_count": execution.episode_result.outcome.get("period_count"),
            }
            checkpoint["record_sha256"] = _digest(checkpoint)
            _write_once_json(checkpoint_path, checkpoint)
            completed += 1
        except Exception as error:
            failure = {
                "schema_version": "aeread.econevals_checkpoint/0.1",
                "campaign_id": ACTIVE_CAMPAIGN_ID,
                "plan_sha256": plan["plan_sha256"],
                "ordinal": ordinal,
                "case_id": case_id,
                "status": "operational_failure",
                "failure_type": type(error).__name__,
                "failure_condition": getattr(error, "condition", "execution_failure"),
                # What this case consumed before it died. Recovered from the
                # sealed evidence because there is no completed execution to
                # read it from; without it the incident ledger understates a
                # failed attempt's true cost.
                "cost_usd": _sealed_spend(execution_root),
            }
            failure["record_sha256"] = _digest(failure)
            _write_once_json(checkpoint_path, failure)
            raise


def publish_campaign(*, run_root: Path, publication_root: Path) -> None:
    plan = json.loads((run_root / "campaign_plan.json").read_text(encoding="utf-8"))
    _verify_plan(plan)
    probes = sorted((run_root / "checkpoints" / "canary_probes").glob("*.json"))
    if not probes:
        raise RuntimeError("cannot publish a campaign with no recorded canary probe")
    records = [json.loads(path.read_text(encoding="utf-8")) for path in probes]
    canary = records[-1]
    canary_payload = {k: v for k, v in canary.items() if k != "record_sha256"}
    if (
        canary.get("status") != "admitted"
        or canary.get("plan_sha256") != plan["plan_sha256"]
        or canary.get("record_sha256") != _digest(canary_payload)
    ):
        raise RuntimeError("cannot publish a campaign with a rejected canary")
    receipt_rows: list[dict[str, Any]] = []
    trajectory_rows: list[dict[str, Any]] = []
    for ordinal, case_id in enumerate(PANEL_CASE_IDS):
        checkpoint = json.loads(
            (run_root / "checkpoints" / f"{ordinal:02d}_{case_id}.json").read_text(
                encoding="utf-8"
            )
        )
        payload = {k: v for k, v in checkpoint.items() if k != "record_sha256"}
        if (
            checkpoint.get("status") != "complete"
            or checkpoint.get("plan_sha256") != plan["plan_sha256"]
            or checkpoint.get("record_sha256") != _digest(payload)
        ):
            raise RuntimeError(f"cannot publish incomplete case {case_id}")
        serialized = read_evaluation_receipt(run_root / checkpoint["receipt_path"])
        receipt = deserialize_evaluation_receipt(serialized)
        receipt_rows.append(
            receipt_projection(serialized, campaign_cell_key=f"{ordinal:02d}:{case_id}")
        )
        # Both declared leaves are surfaced by the scorer; report each by id
        # rather than assuming a position.
        by_leaf = {score.leaf.leaf_id: score for score in receipt.scores}
        gate = next((s for lid, s in by_leaf.items() if lid.endswith("_gate_leaf")), None)
        objective = next(
            (s for lid, s in by_leaf.items() if lid.endswith("_objective_leaf")), None
        )
        trajectory_rows.append(
            {
                "case_id": case_id,
                "track": plan["panel"][ordinal]["track"],
                "stratum": PANEL_STRATA[ordinal],
                "termination_reason": checkpoint["termination_reason"],
                "period_count": checkpoint["period_count"],
                "receipt_status": checkpoint["receipt_status"],
                "inclusion_status": checkpoint["inclusion_status"],
                "gate_leaf_id": gate.leaf.leaf_id if gate else None,
                "gate_validity": gate.validity.status if gate else None,
                "gate_value": (
                    gate.primary.value if gate is not None and gate.primary else None
                ),
                "objective_leaf_id": objective.leaf.leaf_id if objective else None,
                "objective_value": (
                    objective.primary.value
                    if objective is not None and objective.primary
                    else None
                ),
                "cost_usd": checkpoint["cost_usd"],
                "receipt_sha256": checkpoint["receipt_sha256"],
                "receipt_replayed": checkpoint["receipt_replayed"],
            }
        )
    total_cost = sum(float(record["cost_usd"]) for record in records) + sum(
        float(row["cost_usd"]) for row in trajectory_rows
    )
    summary = {
        "campaign_id": ACTIVE_CAMPAIGN_ID,
        "plan_sha256": plan["plan_sha256"],
        "canary_status": canary["status"],
        "canary_cost_usd": sum(float(record["cost_usd"]) for record in records),
        "canary_probe_count": len(records),
        "canary_probe_conditions": [
            record.get("failure_condition") for record in records[:-1]
        ],
        "planned_cases": len(PANEL_CASE_IDS),
        "completed_cases": len(trajectory_rows),
        "included_cases": sum(
            1 for row in trajectory_rows if row["inclusion_status"] == "included"
        ),
        "excluded_cases": sum(
            1 for row in trajectory_rows if row["inclusion_status"] != "included"
        ),
        "operational_failures": 0,
        "total_cost_usd": total_cost,
        "hard_total_cost_ceiling_usd": HARD_TOTAL_COST_CEILING_USD,
        "financial_ceiling_enforcement": "provider_response_reported_cost",
        "route": plan["route"],
        "upstream": plan["upstream"],
        "sanitization": dict(SANITIZATION_DECLARATION),
    }
    files: dict[str, bytes] = {
        "README.md": (
            "# econevals first live panel\n\n"
            "One unscored route canary plus a frozen six-case panel, two cases from "
            "each of the three econevals tracks, on the pinned OpenRouter GLM 5.3 "
            "Flash/Parasail route. Every case is the pinned corpus case, unmodified. "
            "All cases ran sequentially through the shared runner and replayed their "
            "receipts. Objective values are measured against upstream's own solver "
            "output (gurobipy for procurement, scipy for pricing), not a "
            "reimplementation.\n"
        ).encode("utf-8"),
        "reports/summary.json": canonical_json_bytes(summary) + b"\n",
        "trajectories/archive.jsonl": jsonl(trajectory_rows),
    }
    for row in receipt_rows:
        files[f"receipts/{row['case_id']}.json"] = canonical_json_bytes(row) + b"\n"
    artifact_rows = [
        {
            "path": path,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
        }
        for path, payload in sorted(files.items())
    ]
    manifest: dict[str, Any] = {
        "schema_version": "aeread.publication_manifest/0.1",
        "publication_id": CAMPAIGN_ID,
        "campaign_id": ACTIVE_CAMPAIGN_ID,
        "plan_sha256": plan["plan_sha256"],
        # How the evidence was projected, recorded next to what was executed
        # rather than inside the execution freeze.
        "publisher_implementation_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "artifacts": artifact_rows,
        "sanitization": dict(SANITIZATION_DECLARATION),
    }
    manifest["publication_sha256"] = _digest(manifest)
    files["publication_manifest.json"] = canonical_json_bytes(manifest) + b"\n"
    for name, payload in files.items():
        assert_public_payload(name, payload)
        atomic_publish(publication_root / name, payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--publish-to", type=Path, default=None)
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="stop once this many panel cases are complete (an operator's pause; resumable)",
    )
    args = parser.parse_args(argv)
    if getattr(args, 'paper_model', False):
        _use_paper_model()
    # Publish is checked BEFORE the plan-digest branch. It used to come after,
    # so `--publish-to` without `--execute` -- which is exactly how a
    # publish-only invocation is spelled -- printed a plan digest, published
    # nothing, and returned 0. A publisher that reports success without
    # publishing is worse than one that fails: the run driver treated exit 0
    # as "bundle written" and a completed 6/6 panel went unpublished with
    # nothing in the log to say so.
    if args.publish_to is not None:
        publish_campaign(run_root=args.run_root, publication_root=args.publish_to)
        return 0
    if not args.execute:
        plan = build_campaign_plan()
        print(json.dumps({"plan_sha256": plan["plan_sha256"], "campaign_id": ACTIVE_CAMPAIGN_ID}))
        return 0
        return 0
    asyncio.run(execute_campaign(run_root=args.run_root, max_cases=args.max_cases))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
