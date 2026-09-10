"""TERMS-Bench live pilot (#92): one unscored route canary, then the 30-case
pilot corpus, serially, on the pinned GLM 5.3 Flash/Parasail route.

What this campaign is for: the first live measurement of a model negotiating
against TERMS-Bench's specified counterpart. The counterpart is not a model:
it is the family's own seeded kernel, run as a kernel scripted seat
(`live.py`), so the agent seat is the only seat that reaches a provider.

Every case is the pinned pilot corpus case, unmodified: its payload, its
`world_seed`, its `episode.max_logical_actions` and its content digest are
the corpus's own, and the corpus manifest's digest is pinned in the plan.
The panel order is the corpus manifest's order.

Two things this campaign records that a reader will want and the receipts
alone do not give:

- The corpus is half Overlap and half No-deal, and the leaves are
  regime-dependent: an Overlap case is scored on surplus efficiency and
  feasible agreement, a No-deal case on no-deal agreement, and every case on
  protocol compliance, the admission leaf. The summary reports per regime,
  and the family's own corpus aggregate (`SE+`, `AGR+`, `CSE+`) over the
  Overlap half.
- The wall-time gate from the campaign SOP. The first completed case's
  serial wall time is projected over the panel and the campaign stops if
  the projection exceeds `MAX_SERIAL_WALL_SECONDS`, which is a frozen
  control here and not an operator's judgment.

A cell that fails inside the kernel -- an exhausted retry policy, a
contract error mid-episode -- is sealed as a typed exclusion receipt
(`finalize_family_failure`) and the campaign continues: a failed cell is
typed missingness and is never rerun. The campaign aborts only outside a
cell: a rejected canary, a plan that does not verify, a failure that left
no attempt root to seal. v1 aborted the whole panel on one cell (TB-O-01);
v2 is the new identity that carries this policy and the 1.1 harness. The
publisher is deliberately outside the execution freeze (`campaign.py` is
not in `execution_source_sha256`), because a publisher defect must be
fixable without invalidating a panel that already paid for its calls.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.analysis.research import deserialize_evaluation_receipt
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
    finalize_family_failure,
    replay_family_receipt,
)
from aeread.shared_runner.task.execution import (
    OpenRouterChatClient,
    ProviderRequest,
    execute_plan_cell,
)
from aeread.shared_runner.task.receipts import read_evaluation_receipt

from .cases import PAPER_ARXIV_ID, PAPER_TITLE, _pilot_content_sha256
from .live import (
    AGENT_PHASE,
    AGENT_SEAT,
    CASES_DIR,
    MAX_OUTPUT_TOKENS_UNCONSTRAINED,
    MODEL,
    PRICING,
    PROMPT,
    PROVIDER,
    QUANTIZATION,
    REASONING_UNCONSTRAINED_V1,
    REVISION,
    ROUTE_PROVIDER,
    agent_output_schema,
    build_live_setup,
    load_case,
    route_metadata,
)
from .measurement import (
    FEASIBLE_AGREEMENT_LEAF_ID,
    NO_DEAL_AGREEMENT_LEAF_ID,
    PROTOCOL_COMPLIANCE_LEAF_ID,
    SURPLUS_EFFICIENCY_LEAF_ID,
    aggregate_surplus_efficiency_corpus,
    build_protocol_compliance_leaf,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PILOT_MANIFEST_PATH = CASES_DIR / "pilot_manifest.json"

# v3 is v2's design with one control changed and therefore a new identity:
# the reasoning condition. v2 ran `reasoning_capped_1500_v1`, which the
# 2026-09-10 probe showed is a suppression switch (~13 reasoning tokens),
# so v2 measured a model that did not deliberate. v3 declares no reasoning
# block, which is the only way to obtain deliberation on this route, and
# gives the completion budget the headroom that rationale needs.
CAMPAIGN_ID = "termsbench_glm53_flash_parasail_pilot_v3"
REASONING = REASONING_UNCONSTRAINED_V1
MAX_OUTPUT_TOKENS = MAX_OUTPUT_TOKENS_UNCONSTRAINED
SEED = 300
MAX_PARALLEL_CELLS = 1

MAX_CANARY_COST_USD = 0.01
MAX_CANARY_OUTPUT_TOKENS = MAX_OUTPUT_TOKENS
CANARY_TRANSIENT_CONDITIONS = ("rate_limit", "provider_5xx", "timeout")
MAX_CANARY_PROBES = 6
CANARY_RETRY_BASE_SECONDS = 15.0

# An episode is at most `horizon` agent turns (10 in the pilot corpus), each
# one call with a growing transcript. Under v3's unconstrained reasoning the
# route spends its rationale inside the completion budget, so the worst case
# is ten turns at the 12,000-token ceiling: ~$0.06. The per-case cap is set
# above that and the hard ceiling covers the whole panel at the cap plus the
# canary, so a cap breach is a measured exclusion rather than the campaign's
# ceiling stopping the run.
MAX_TRAJECTORY_COST_USD = 0.10
HARD_TOTAL_COST_CEILING_USD = 3.50

# Campaign SOP wall-time gate: the first completed case's serial wall time,
# projected over the panel, must fit in this. Four hours.
MAX_SERIAL_WALL_SECONDS = 4 * 60 * 60

CHECKPOINT_SCHEMA = "aeread.termsbench_checkpoint/0.1"
CANARY_SCHEMA = "aeread.provider_admission_canary/0.1"
PLAN_SCHEMA = "aeread.termsbench_live_campaign/0.1"


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


def load_pilot_manifest() -> dict[str, Any]:
    """The pilot corpus manifest, digest-checked: the panel is its `cells`
    in its order, and a corpus that changed underneath the campaign is
    refused rather than silently re-sampled."""
    value = json.loads(PILOT_MANIFEST_PATH.read_text(encoding="utf-8"))
    if value.get("content_sha256") != _pilot_content_sha256(value):
        raise ValueError("pilot corpus manifest digest mismatch")
    ids = [cell["case_id"] for cell in value["cells"]]
    if ids != list(value["case_ids"]) or len(set(ids)) != len(ids):
        raise ValueError("pilot corpus manifest cells and case_ids disagree")
    return value


PILOT_MANIFEST = load_pilot_manifest()
PANEL_CASE_IDS: tuple[str, ...] = tuple(PILOT_MANIFEST["case_ids"])
PANEL_CELLS: tuple[Mapping[str, Any], ...] = tuple(PILOT_MANIFEST["cells"])
CANARY_CASE_ID = PANEL_CASE_IDS[0]


def build_campaign_plan() -> dict[str, Any]:
    cases = [load_case(case_id) for case_id in PANEL_CASE_IDS]
    source_names = (
        "cases.py",
        "environment.py",
        "harness.py",
        "kernel.py",
        "live.py",
        "measurement.py",
    )
    source_hashes = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in source_names
    }
    plan: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA,
        "campaign_id": CAMPAIGN_ID,
        "freeze_status": "pilot_frozen_before_live_execution",
        "paper": {"title": PAPER_TITLE, "arxiv_id": PAPER_ARXIV_ID},
        "corpus": {
            "pilot_id": PILOT_MANIFEST["pilot_id"],
            "pilot_manifest_sha256": PILOT_MANIFEST["content_sha256"],
            "case_count": len(PANEL_CASE_IDS),
        },
        "route": {
            "provider": PROVIDER,
            "model": MODEL,
            "revision": REVISION,
            "route_provider": ROUTE_PROVIDER,
            "quantization": QUANTIZATION,
            "fallbacks": "disabled",
            "reasoning_condition_id": REASONING["condition_id"],
            "reasoning_declared_block": REASONING["effort"] is not None
            or REASONING["token_budget"] is not None,
            "reasoning_effort": REASONING["effort"],
            "reasoning_token_budget": REASONING["token_budget"],
            "route_attestation": "openrouter_provider_order_pinned",
            "provider_cost_status": "response_reported",
            "provider_seed_status": "requested",
            "pricing_id": PRICING.pricing_id,
            "pricing_sha256": PRICING.content_sha256(),
        },
        "seats": {
            "agent": "model_under_test",
            "counterpart": "kernel_scripted_seat:termsbench_counterpart_kernel_v1",
        },
        "canary": {
            "case_id": CANARY_CASE_ID,
            "scored": False,
            "max_cost_usd": MAX_CANARY_COST_USD,
            "max_output_tokens": MAX_CANARY_OUTPUT_TOKENS,
            "max_probes": MAX_CANARY_PROBES,
            "transient_conditions": list(CANARY_TRANSIENT_CONDITIONS),
            "retry_base_seconds": CANARY_RETRY_BASE_SECONDS,
            "probes_are_recorded_individually": True,
        },
        "panel": [
            {
                "case_id": case.case_id,
                "case_content_sha256": case.content_sha256,
                "regime": cell["regime"],
                "family": cell["family"],
                "difficulty_bin": cell["difficulty_bin"],
                "chi": case.payload["chi"],
                "world_seed": case.world_seed,
                "horizon": case.payload["horizon"],
                "max_logical_actions": case.episode.max_logical_actions,
                "seed": SEED,
                "max_cost_usd": MAX_TRAJECTORY_COST_USD,
            }
            for case, cell in zip(cases, PANEL_CELLS, strict=True)
        ],
        "execution": {
            "max_parallel_cells": MAX_PARALLEL_CELLS,
            "cell_failure_policy": "seal_typed_exclusion_and_continue",
            "abort_on_operational_failure": True,
            "resume_only_failure_free_checkpoints": True,
            "publish_only": True,
            "scored_case_count": len(PANEL_CASE_IDS),
            "max_serial_wall_seconds": MAX_SERIAL_WALL_SECONDS,
            "wall_time_gate": "first_completed_case_projected_over_panel",
        },
        "budget": {
            "hard_total_cost_ceiling_usd": HARD_TOTAL_COST_CEILING_USD,
            "planned_maximum_usd": MAX_CANARY_COST_USD
            + len(PANEL_CASE_IDS) * MAX_TRAJECTORY_COST_USD,
            "canary_included": True,
        },
        "execution_source_sha256": source_hashes,
    }
    for row, cell in zip(plan["panel"], PANEL_CELLS, strict=True):
        if row["world_seed"] != cell["world_seed"]:
            raise ValueError(f"corpus manifest and case disagree on {row['case_id']}")
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


def _canary_observation() -> dict[str, Any]:
    """The agent's opening observation for the canary case, shaped exactly
    as `live.py`'s harness would send it. Unscored: admission only."""
    payload = load_case(CANARY_CASE_ID).payload
    return {
        "phase_id": AGENT_PHASE,
        "seat_id": AGENT_SEAT,
        "role": AGENT_SEAT,
        "observation_schema": "termsbench_agent_observation_v1",
        "action_schema": "termsbench_agent_action_v1",
        "observation": {
            "role": payload["agent"]["role"],
            "r_a": payload["agent"]["r_a"],
            "price_bounds": dict(payload["price_bounds"]),
            "horizon": payload["horizon"],
            "round": 0,
            "agent_offers": [],
            "counterpart_offers": [],
            "transcript": [],
        },
    }


async def _probe_canary(*, path: Path, plan_sha256: str, ordinal: int) -> dict[str, Any]:
    if path.exists():
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("plan_sha256") != plan_sha256 or value.get("record_sha256") != _digest(
            {k: v for k, v in value.items() if k != "record_sha256"}
        ):
            raise ValueError("canary checkpoint does not match the frozen plan")
        return value
    request = ProviderRequest(
        provider_call_id="termsbench_pilot_canary",
        provider=PROVIDER,
        base_url="https://openrouter.ai/api/v1",
        model=MODEL,
        revision=REVISION,
        instructions=PROMPT,
        input_text=canonical_json_bytes(_canary_observation()).decode("utf-8"),
        temperature=0.0,
        top_p=None,
        max_output_tokens=MAX_CANARY_OUTPUT_TOKENS,
        reasoning_effort=REASONING["effort"],
        reasoning_token_budget=REASONING["token_budget"],
        timeout_seconds=180.0,
        request_sha256="",
        max_cost_usd=MAX_CANARY_COST_USD,
        output_schema=agent_output_schema(),
        provider_metadata=route_metadata(),
        seed=SEED,
    ).with_computed_hash()
    record: dict[str, Any] = {
        "schema_version": CANARY_SCHEMA,
        "campaign_id": CAMPAIGN_ID,
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
        if not isinstance(value, Mapping) or value.get("decision") not in (
            "offer",
            "accept",
            "reject",
        ):
            raise ValueError("canary did not return a negotiation move")
        cost = float(result.cost_usd or 0.0)
        if cost > MAX_CANARY_COST_USD:
            raise ValueError("canary exceeded its cost ceiling")
        record.update(
            {
                "status": "admitted",
                "resolved_model": result.resolved_model,
                "finish_reason": result.finish_reason,
                "decision": value["decision"],
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
    """Provider spend already sealed under a run, receipted or not: a case
    that dies partway has paid for the calls it made."""
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
    """Admit the route, re-probing only on typed transient conditions."""
    directory = run_root / "checkpoints" / "canary_probes"
    record: dict[str, Any] = {}
    for ordinal in range(1, MAX_CANARY_PROBES + 1):
        record = await _probe_canary(
            path=directory / f"{ordinal:03d}.json", plan_sha256=plan_sha256, ordinal=ordinal
        )
        if record.get("status") == "admitted":
            return record
        if record.get("failure_condition") not in CANARY_TRANSIENT_CONDITIONS:
            return record
        if ordinal < MAX_CANARY_PROBES:
            await asyncio.sleep(CANARY_RETRY_BASE_SECONDS * ordinal)
    return record


def _leaf_values(receipt: Any) -> dict[str, Any]:
    """The per-leaf primary values a reader wants next to the trajectory:
    absent leaves (the other regime's) are `None`, not zero."""
    by_leaf = {score.leaf.leaf_id: score for score in receipt.scores}
    out: dict[str, Any] = {}
    for key, leaf_id in (
        ("protocol_compliance", PROTOCOL_COMPLIANCE_LEAF_ID),
        ("surplus_efficiency", SURPLUS_EFFICIENCY_LEAF_ID),
        ("feasible_agreement", FEASIBLE_AGREEMENT_LEAF_ID),
        ("no_deal_agreement", NO_DEAL_AGREEMENT_LEAF_ID),
    ):
        score = by_leaf.get(leaf_id)
        out[f"{key}_status"] = score.status if score is not None else None
        out[f"{key}_validity"] = score.validity.status if score is not None else None
        out[f"{key}_value"] = (
            score.primary.value if score is not None and score.primary is not None else None
        )
    return out


async def execute_campaign(*, run_root: Path, max_cases: int | None = None) -> None:
    """Run the canary, then the panel in corpus order.

    `max_cases` is an operator's pause, not a frozen control: it stops after
    that many *complete* checkpoints exist so the operator can read the
    canary and the first case before the rest of the panel spends. The plan
    is unchanged by it and the run resumes from its checkpoints without it.
    """
    if max_cases is not None and max_cases < 1:
        raise ValueError("max_cases must be at least 1")
    plan_path = run_root / "campaign_plan.json"
    plan = build_campaign_plan()
    _write_once_json(plan_path, plan)
    _verify_plan(json.loads(plan_path.read_text(encoding="utf-8")))
    canary = await run_canary(run_root=run_root, plan_sha256=plan["plan_sha256"])
    if canary.get("status") != "admitted":
        raise RuntimeError("termsbench canary was rejected; campaign stopped")
    total_cost = float(canary["cost_usd"])
    # Constructed only once a case actually needs the route: a resume that
    # finds every checkpoint complete, or a gate that stops the campaign
    # first, never touches the provider.
    provider: OpenRouterChatClient | None = None
    first_elapsed: float | None = None
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
                checkpoint.get("status") not in {"complete", "failed"}
                or checkpoint.get("plan_sha256") != plan["plan_sha256"]
                or recorded != _digest(payload)
            ):
                raise RuntimeError("campaign cannot resume from an operational failure")
            total_cost += float(checkpoint["cost_usd"])
            if first_elapsed is None:
                first_elapsed = float(checkpoint["elapsed_seconds"])
            completed += 1
            continue
        if total_cost + MAX_TRAJECTORY_COST_USD > HARD_TOTAL_COST_CEILING_USD:
            raise RuntimeError("insufficient campaign budget reserve for the next case")
        if first_elapsed is not None and first_elapsed * len(PANEL_CASE_IDS) > MAX_SERIAL_WALL_SECONDS:
            raise RuntimeError(
                "wall-time gate: the first case's serial wall time projected over the "
                f"panel ({first_elapsed * len(PANEL_CASE_IDS):.0f}s) exceeds "
                f"{MAX_SERIAL_WALL_SECONDS}s"
            )
        setup = build_live_setup(
            case_id=case_id,
            seed=SEED,
            max_trajectory_cost_usd=MAX_TRAJECTORY_COST_USD,
            reasoning=REASONING,
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
        execution_root = run_root / "executions" / case_id
        if execution_root.exists():
            superseded = run_root / "executions" / (
                f"{case_id}.superseded_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            )
            execution_root.rename(superseded)
        if provider is None:
            provider = OpenRouterChatClient()
        started = time.monotonic()
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
            if receipt.status not in {"ok", "invalid_measurement"}:
                raise RuntimeError(f"termsbench case produced an unusable receipt: {receipt.status}")
            replayed = replay_family_receipt(
                setup=setup, receipt=receipt, evidence_root=execution_root
            )
            if replayed.receipt_sha256 != receipt.receipt_sha256:
                raise RuntimeError("receipt replay digest mismatch")
            cost = float(execution.total_cost_usd)
            total_cost += cost
            if total_cost > HARD_TOTAL_COST_CEILING_USD:
                raise RuntimeError("campaign exceeded its hard total cost ceiling")
            elapsed = time.monotonic() - started
            outcome = execution.episode_result.outcome
            receipt_path = execution.evidence.root / "evaluation_receipt.json"
            checkpoint = {
                "schema_version": CHECKPOINT_SCHEMA,
                "campaign_id": CAMPAIGN_ID,
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
                "elapsed_seconds": elapsed,
                "termination_reason": outcome["termination_reason"],
                "final_price": outcome["final_price"],
                "rounds_used": outcome["rounds_used"],
                "malformed_action_schema": outcome["malformed_action_schema"],
            }
            checkpoint["record_sha256"] = _digest(checkpoint)
            _write_once_json(checkpoint_path, checkpoint)
            completed += 1
            if first_elapsed is None:
                first_elapsed = elapsed
        except Exception as error:
            elapsed = time.monotonic() - started
            try:
                receipt = finalize_family_failure(
                    setup=setup,
                    cell_id=setup.plan.cells[0].cell_id,
                    evidence_root=execution_root,
                    error=error,
                    leaf_builder=build_protocol_compliance_leaf,
                )
            except Exception as sealing_error:
                # Nothing to seal: the failure is outside the cell.
                failure = {
                    "schema_version": CHECKPOINT_SCHEMA,
                    "campaign_id": CAMPAIGN_ID,
                    "plan_sha256": plan["plan_sha256"],
                    "ordinal": ordinal,
                    "case_id": case_id,
                    "status": "operational_failure",
                    "failure_type": type(error).__name__,
                    "failure_condition": getattr(error, "condition", "execution_failure"),
                    "sealing_failure_type": type(sealing_error).__name__,
                    "cost_usd": _sealed_spend(execution_root),
                    "elapsed_seconds": elapsed,
                }
                failure["record_sha256"] = _digest(failure)
                _write_once_json(checkpoint_path, failure)
                raise
            cost = _sealed_spend(execution_root)
            total_cost += cost
            receipt_path = next(execution_root.rglob("evaluation_receipt.json"))
            checkpoint = {
                "schema_version": CHECKPOINT_SCHEMA,
                "campaign_id": CAMPAIGN_ID,
                "plan_sha256": plan["plan_sha256"],
                "ordinal": ordinal,
                "case_id": case_id,
                "status": "failed",
                "run_plan_id": setup.plan.run_plan_id,
                "run_plan_sha256": setup.plan.plan_sha256,
                "receipt_path": str(receipt_path.relative_to(run_root)),
                "receipt_sha256": receipt.receipt_sha256,
                "receipt_replayed": False,
                "receipt_status": receipt.status,
                "inclusion_status": receipt.inclusion_status,
                "failure_type": type(error).__name__,
                "failure_class": receipt.failure.failure_class if receipt.failure else None,
                "failure_condition": receipt.failure.condition if receipt.failure else None,
                "cost_usd": cost,
                "elapsed_seconds": elapsed,
                "termination_reason": None,
                "final_price": None,
                "rounds_used": None,
                "malformed_action_schema": None,
            }
            checkpoint["record_sha256"] = _digest(checkpoint)
            _write_once_json(checkpoint_path, checkpoint)
            completed += 1
            if first_elapsed is None:
                first_elapsed = elapsed
            if total_cost > HARD_TOTAL_COST_CEILING_USD:
                raise RuntimeError("campaign exceeded its hard total cost ceiling")


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
    overlap_pairs: list[tuple[Any, Any]] = []
    for ordinal, case_id in enumerate(PANEL_CASE_IDS):
        checkpoint = json.loads(
            (run_root / "checkpoints" / f"{ordinal:02d}_{case_id}.json").read_text(
                encoding="utf-8"
            )
        )
        payload = {k: v for k, v in checkpoint.items() if k != "record_sha256"}
        if (
            checkpoint.get("status") not in {"complete", "failed"}
            or checkpoint.get("plan_sha256") != plan["plan_sha256"]
            or checkpoint.get("record_sha256") != _digest(payload)
        ):
            raise RuntimeError(f"cannot publish incomplete case {case_id}")
        serialized = read_evaluation_receipt(run_root / checkpoint["receipt_path"])
        receipt = deserialize_evaluation_receipt(serialized)
        if receipt.case_id != case_id or receipt.receipt_sha256 != checkpoint["receipt_sha256"]:
            raise RuntimeError(
                f"checkpoint {ordinal:02d} names case {case_id} but its receipt is "
                f"{receipt.case_id} ({receipt.receipt_sha256[:12]})"
            )
        receipt_rows.append(
            receipt_projection(serialized, campaign_cell_key=f"{ordinal:02d}:{case_id}")
        )
        panel_row = plan["panel"][ordinal]
        by_leaf = {score.leaf.leaf_id: score for score in receipt.scores}
        if panel_row["regime"] == "overlap" and {
            SURPLUS_EFFICIENCY_LEAF_ID,
            FEASIBLE_AGREEMENT_LEAF_ID,
        } <= set(by_leaf):
            overlap_pairs.append(
                (by_leaf[SURPLUS_EFFICIENCY_LEAF_ID], by_leaf[FEASIBLE_AGREEMENT_LEAF_ID])
            )
        trajectory_rows.append(
            {
                "case_id": case_id,
                "regime": panel_row["regime"],
                "family": panel_row["family"],
                "difficulty_bin": panel_row["difficulty_bin"],
                "chi": panel_row["chi"],
                "world_seed": panel_row["world_seed"],
                "termination_reason": checkpoint["termination_reason"],
                "final_price": checkpoint["final_price"],
                "rounds_used": checkpoint["rounds_used"],
                "malformed_action_schema": checkpoint["malformed_action_schema"],
                "receipt_status": checkpoint["receipt_status"],
                "inclusion_status": checkpoint["inclusion_status"],
                "cell_status": checkpoint["status"],
                "failure_class": checkpoint.get("failure_class"),
                "failure_condition": checkpoint.get("failure_condition"),
                **_leaf_values(receipt),
                "cost_usd": checkpoint["cost_usd"],
                "elapsed_seconds": checkpoint["elapsed_seconds"],
                "receipt_sha256": checkpoint["receipt_sha256"],
                "receipt_replayed": checkpoint["receipt_replayed"],
            }
        )
    total_cost = sum(float(record["cost_usd"]) for record in records) + sum(
        float(row["cost_usd"]) for row in trajectory_rows
    )

    def _regime(name: str) -> dict[str, Any]:
        rows = [row for row in trajectory_rows if row["regime"] == name]
        included = [row for row in rows if row["inclusion_status"] == "included"]
        return {
            "completed_cases": len(rows),
            "failed_cases": sum(1 for row in rows if row["cell_status"] == "failed"),
            "included_cases": len(included),
            "excluded_cases": len(rows) - len(included),
            # A failed cell has no termination: it is counted in
            # `failed_cases`, not as a reason.
            "termination_reasons": {
                reason: sum(1 for row in rows if row["termination_reason"] == reason)
                for reason in sorted({row["termination_reason"] for row in rows if row["termination_reason"]})
            },
        }

    try:
        overlap_aggregate: dict[str, Any] | None = aggregate_surplus_efficiency_corpus(
            overlap_pairs
        )
    except ValueError:
        overlap_aggregate = None
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "plan_sha256": plan["plan_sha256"],
        "canary_status": canary["status"],
        "canary_cost_usd": sum(float(record["cost_usd"]) for record in records),
        "canary_probe_count": len(records),
        "canary_probe_conditions": [record.get("failure_condition") for record in records[:-1]],
        "planned_cases": len(PANEL_CASE_IDS),
        "completed_cases": len(trajectory_rows),
        "included_cases": sum(1 for row in trajectory_rows if row["inclusion_status"] == "included"),
        "excluded_cases": sum(1 for row in trajectory_rows if row["inclusion_status"] != "included"),
        "failed_cases": sum(1 for row in trajectory_rows if row["cell_status"] == "failed"),
        "failure_conditions": {
            condition: sum(1 for row in trajectory_rows if row["failure_condition"] == condition)
            for condition in sorted({row["failure_condition"] for row in trajectory_rows if row["failure_condition"]})
        },
        "operational_failures": 0,
        "by_regime": {"overlap": _regime("overlap"), "nodeal": _regime("nodeal")},
        "overlap_corpus_aggregate": overlap_aggregate,
        "total_cost_usd": total_cost,
        "total_elapsed_seconds": sum(float(row["elapsed_seconds"]) for row in trajectory_rows),
        "hard_total_cost_ceiling_usd": HARD_TOTAL_COST_CEILING_USD,
        "financial_ceiling_enforcement": "provider_response_reported_cost",
        "route": plan["route"],
        "seats": plan["seats"],
        "corpus": plan["corpus"],
        "sanitization": dict(SANITIZATION_DECLARATION),
    }
    files: dict[str, bytes] = {
        "README.md": (
            "# TERMS-Bench first live pilot\n\n"
            "One unscored route canary plus the frozen 30-case pilot corpus, half "
            "Overlap and half No-deal, on the pinned OpenRouter GLM 5.3 Flash/Parasail "
            "route. The agent seat is the only model seat; the counterpart is the "
            "family's own seeded kernel, run as a kernel scripted seat and sealed as "
            "such in every receipt. Every case is the pinned corpus case, unmodified. "
            "All cases ran sequentially through the shared runner; completed cases "
            "replayed their receipts, which recompute the counterpart's every turn, and "
            "a cell that failed inside the kernel is a typed exclusion receipt, never "
            "rerun. Leaves are "
            "regime-dependent: see `reports/summary.json` `by_regime`, and the "
            "family's corpus aggregate over the Overlap half.\n"
        ).encode("utf-8"),
        "reports/summary.json": canonical_json_bytes(summary) + b"\n",
        "trajectories/archive.jsonl": jsonl(trajectory_rows),
    }
    for row in receipt_rows:
        files[f"receipts/{row['case_id']}.json"] = canonical_json_bytes(row) + b"\n"
    artifact_rows = [
        {"path": path, "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)}
        for path, payload in sorted(files.items())
    ]
    manifest: dict[str, Any] = {
        "schema_version": "aeread.publication_manifest/0.1",
        "publication_id": CAMPAIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "plan_sha256": plan["plan_sha256"],
        "publisher_implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
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
    if args.publish_to is not None:
        publish_campaign(run_root=args.run_root, publication_root=args.publish_to)
        return 0
    if not args.execute:
        plan = build_campaign_plan()
        print(json.dumps({"plan_sha256": plan["plan_sha256"], "campaign_id": CAMPAIGN_ID}))
        return 0
    asyncio.run(execute_campaign(run_root=args.run_root, max_cases=args.max_cases))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
