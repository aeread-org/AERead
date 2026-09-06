"""Frozen first-live campaign for the govsim external adapter (issue #91).

One unscored admission canary plus a three-case panel -- one case per
scenario -- on the pinned OpenRouter GLM 5.3 Flash/Parasail route, executed
sequentially, aborting only on a broken pipeline.

**Why three cases and not nine.** The corpus has nine cases, but all nine
share `world_seed 0` and an identical `env_cfg`; they differ only in
`scenario` (fishing / pollution / sheep) and in `policy_assignment`. A live
run assigns every seat to the model, so `policy_assignment` has no effect
whatsoever -- the three cases within a scenario would be byte-identical
configurations. Running all nine would look like a nine-case panel and
deliver three, which is pseudo-replication: it would understate variance and
overstate coverage. The panel therefore takes one case per scenario and says
so, and widening the corpus with real world seeds is the follow-up.

**Comparative baselines.** govsim is `bound_status: baseline_only`, so three
of its five leaves are scored against `govsim_sustainable_v1`. The baselines
are produced here by running that scripted policy through the same
environment, provider-free, and frozen into the plan with the policy's own
source digest -- so a reader can see exactly what each comparative claim is
measured against, rather than trusting a number someone typed.

Every lesson from the econevals first light (#90) is applied rather than
rediscovered; see `docs/families/econevals/incidents.md` for the ledger of
what each one cost.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
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
    replay_family_receipt,
)
from aeread.shared_runner.task.execution import (
    OpenRouterChatClient,
    ProviderRequest,
    execute_plan_cell,
)
from aeread.shared_runner.task.receipts import read_evaluation_receipt

from .baseline import (
    baseline_digest,
    baselines_for_scoring,
    compute_baseline,
    compute_baseline_async,
    policy_source_sha256,
)
from .govsim_bridge import GovsimBridge
from .live import (
    MODEL,
    PRICING,
    PROMPT,
    PROVIDER,
    QUANTIZATION,
    REVISION,
    ROUTE_PROVIDER,
    build_live_setup,
    harvest_output_schema,
    load_case,
    route_metadata,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN_ID = "govsim_glm53_flash_parasail_first_light_v1"
CANARY_CASE_ID = "govsim.fishing.sustainable.0"
# One per scenario; see the module docstring on why not all nine.
PANEL_CASE_IDS = (
    "govsim.fishing.sustainable.0",
    "govsim.pollution.sustainable.0",
    "govsim.sheep.sustainable.0",
)
PANEL_STRATA = ("fishing", "pollution", "sheep")
SEED = 300
MAX_PARALLEL_CELLS = 1
MAX_CANARY_COST_USD = 0.01
MAX_CANARY_OUTPUT_TOKENS = 128
MAX_TRAJECTORY_COST_USD = 0.12
HARD_TOTAL_COST_CEILING_USD = 0.40
CANARY_TRANSIENT_CONDITIONS = ("rate_limit", "provider_5xx", "timeout")
MAX_CANARY_PROBES = 6
CANARY_RETRY_BASE_SECONDS = 15.0


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


def build_campaign_plan(*, baselines: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Freeze the plan. `baselines` is keyed by case id and produced by
    `baseline.compute_baseline`, never entered by hand."""
    cases = [load_case(case_id) for case_id in PANEL_CASE_IDS]
    # EXECUTION sources only: campaign.py carries the publisher as well as the
    # executor, and hashing it here would make a publisher bug unfixable for a
    # completed run (econevals E-D-02, which cost a full panel).
    source_names = (
        "baseline.py",
        "cases.py",
        "environment.py",
        "govsim_bridge.py",
        "live.py",
        "measurement.py",
        "policies.py",
    )
    source_hashes = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in source_names
    }
    plan: dict[str, Any] = {
        "schema_version": "aeread.govsim_live_campaign/0.1",
        "campaign_id": CAMPAIGN_ID,
        "freeze_status": "first_light_frozen_before_live_execution",
        "upstream": {
            "repository": cases[0].payload["upstream_repo"],
            "commit": cases[0].payload["upstream_commit"],
        },
        "route": {
            "provider": PROVIDER,
            "model": MODEL,
            "revision": REVISION,
            "route_provider": ROUTE_PROVIDER,
            "quantization": QUANTIZATION,
            "fallbacks": "disabled",
            "reasoning_effort": "low",
            "route_attestation": "openrouter_provider_order_pinned",
            "provider_cost_status": "response_reported",
            "provider_seed_status": "requested",
            "pricing_id": PRICING.pricing_id,
            "pricing_sha256": PRICING.content_sha256(),
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
                "scenario": case.payload["scenario"],
                "world_seed": case.world_seed,
                "num_agents": case.payload["env_cfg"]["num_agents"],
                "max_num_rounds": case.payload["env_cfg"]["max_num_rounds"],
                "stratum": stratum,
                "seed": SEED,
                "max_cost_usd": MAX_TRAJECTORY_COST_USD,
                "baseline": dict(baselines[case.case_id]),
            }
            for case, stratum in zip(cases, PANEL_STRATA, strict=True)
        ],
        "panel_design": {
            # Recorded so the panel is not mistaken for a nine-case one.
            "corpus_case_count": 9,
            "distinct_configurations": 3,
            "reason": (
                "all nine corpus cases share world_seed 0 and an identical "
                "env_cfg, and policy_assignment has no effect when every seat "
                "is the model, so the nine cases are three configurations "
                "repeated three times"
            ),
            "follow_up": "widen the corpus with real world seeds",
        },
        "baseline_policy": {
            "policy_id": "govsim_sustainable_v1",
            "policy_source_sha256": policy_source_sha256(),
            "provider_free": True,
        },
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
    baselines = {
        row["case_id"]: row["baseline"] for row in value.get("panel", [])
    }
    expected = build_campaign_plan(baselines=baselines)
    if canonical_json_bytes(value) != canonical_json_bytes(expected):
        raise ValueError("campaign plan differs from the frozen implementation")


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
        provider_call_id="govsim_first_light_canary",
        provider=PROVIDER,
        base_url="https://openrouter.ai/api/v1",
        model=MODEL,
        revision=REVISION,
        instructions=PROMPT,
        input_text=canonical_json_bytes(
            {
                "phase_id": "route_admission",
                "case_id": CANARY_CASE_ID,
                "instruction": "Return a harvest quantity of 0 for route admission.",
            }
        ).decode("utf-8"),
        temperature=0.0,
        top_p=None,
        max_output_tokens=MAX_CANARY_OUTPUT_TOKENS,
        reasoning_effort="low",
        reasoning_token_budget=None,
        timeout_seconds=180.0,
        request_sha256="",
        max_cost_usd=MAX_CANARY_COST_USD,
        output_schema=harvest_output_schema(),
        provider_metadata=route_metadata(),
        seed=SEED,
    ).with_computed_hash()
    record: dict[str, Any] = {
        "schema_version": "aeread.provider_admission_canary/0.1",
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
        if not isinstance(value.get("quantity"), int):
            raise ValueError("canary did not return the required integer quantity")
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


async def run_canary(*, run_root: Path, plan_sha256: str) -> dict[str, Any]:
    """Admit the route, re-probing only typed transient conditions.

    A transient 429 on an unscored, zero-cost probe must not seal the attempt
    root: the probe produces no measurement, so re-probing changes nothing
    about what is measured (econevals D-10, which sealed four roots).
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


def _sealed_spend(evidence_root: Path) -> float:
    """Provider spend already sealed under a run, receipted or not.

    A case that dies partway has paid for the calls it made; its failure
    checkpoint has no completed execution to read a cost from, so the spend is
    recovered from the evidence (econevals E-J-03, which understated a
    ledger by 44%).
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


def compute_panel_baselines(
    *, upstream_root: Path, bridge: GovsimBridge
) -> dict[str, dict[str, Any]]:
    """Synchronous form, for the plan-freeze CLI path."""
    return {
        case_id: compute_baseline(
            case=load_case(case_id), upstream_root=upstream_root, bridge=bridge
        )
        for case_id in PANEL_CASE_IDS
    }


async def compute_panel_baselines_async(
    *, upstream_root: Path, bridge: GovsimBridge
) -> dict[str, dict[str, Any]]:
    return {
        case_id: await compute_baseline_async(
            case=load_case(case_id), upstream_root=upstream_root, bridge=bridge
        )
        for case_id in PANEL_CASE_IDS
    }


async def execute_campaign(*, run_root: Path, upstream_root: Path) -> None:
    bridge = GovsimBridge.discover(upstream_root=upstream_root)
    baselines = await compute_panel_baselines_async(
        upstream_root=upstream_root, bridge=bridge
    )
    plan_path = run_root / "campaign_plan.json"
    plan = build_campaign_plan(baselines=baselines)
    _write_once_json(plan_path, plan)
    _verify_plan(json.loads(plan_path.read_text(encoding="utf-8")))
    canary = await run_canary(run_root=run_root, plan_sha256=plan["plan_sha256"])
    if canary.get("status") != "admitted":
        raise RuntimeError("govsim canary was rejected; campaign stopped")
    total_cost = float(canary["cost_usd"])
    provider = OpenRouterChatClient()
    for ordinal, case_id in enumerate(PANEL_CASE_IDS):
        checkpoint_path = run_root / "checkpoints" / f"{ordinal:02d}_{case_id}.json"
        if checkpoint_path.exists():
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            payload = {k: v for k, v in checkpoint.items() if k != "record_sha256"}
            if (
                checkpoint.get("status") != "complete"
                or checkpoint.get("plan_sha256") != plan["plan_sha256"]
                or checkpoint.get("record_sha256") != _digest(payload)
            ):
                raise RuntimeError("campaign cannot resume from a failed checkpoint")
            total_cost += float(checkpoint["cost_usd"])
            continue
        if total_cost + MAX_TRAJECTORY_COST_USD > HARD_TOTAL_COST_CEILING_USD:
            raise RuntimeError("insufficient campaign budget reserve for the next case")
        setup = build_live_setup(
            case_id=case_id,
            upstream_root=upstream_root,
            bridge=bridge,
            seed=SEED,
            baselines=baselines_for_scoring(baselines[case_id]),
            max_trajectory_cost_usd=MAX_TRAJECTORY_COST_USD,
        )
        execution_root = run_root / "executions" / case_id
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
            # An excluded receipt is a measurement outcome, not a broken
            # pipeline (econevals E-D-02's sibling finding).
            if receipt.status not in {"ok", "invalid_measurement"}:
                raise RuntimeError(
                    f"govsim case produced an unusable receipt: {receipt.status}"
                )
            replayed = replay_family_receipt(
                setup=setup, receipt=receipt, evidence_root=execution_root
            )
            if replayed.receipt_sha256 != receipt.receipt_sha256:
                raise RuntimeError("receipt replay digest mismatch")
            cost = float(execution.total_cost_usd)
            total_cost += cost
            if total_cost > HARD_TOTAL_COST_CEILING_USD:
                raise RuntimeError("campaign exceeded its hard total cost ceiling")
            receipt_path = execution.evidence.root / "evaluation_receipt.json"
            checkpoint = {
                "schema_version": "aeread.govsim_checkpoint/0.1",
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
                "baseline_sha256": baseline_digest(baselines[case_id]),
                "cost_usd": cost,
                "termination_reason": execution.episode_result.outcome[
                    "termination_reason"
                ],
                "num_round": execution.episode_result.outcome.get("num_round"),
            }
            checkpoint["record_sha256"] = _digest(checkpoint)
            _write_once_json(checkpoint_path, checkpoint)
        except Exception as error:
            failure = {
                "schema_version": "aeread.govsim_checkpoint/0.1",
                "campaign_id": CAMPAIGN_ID,
                "plan_sha256": plan["plan_sha256"],
                "ordinal": ordinal,
                "case_id": case_id,
                "status": "operational_failure",
                "failure_type": type(error).__name__,
                "failure_condition": getattr(error, "condition", "execution_failure"),
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
    if canary.get("status") != "admitted":
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
        by_leaf = {score.leaf.leaf_id: score for score in receipt.scores}
        trajectory_rows.append(
            {
                "case_id": case_id,
                "scenario": plan["panel"][ordinal]["scenario"],
                "stratum": PANEL_STRATA[ordinal],
                "termination_reason": checkpoint["termination_reason"],
                "num_round": checkpoint["num_round"],
                "receipt_status": checkpoint["receipt_status"],
                "inclusion_status": checkpoint["inclusion_status"],
                "baseline_sha256": checkpoint["baseline_sha256"],
                "leaves": {
                    leaf_id: (score.primary.value if score.primary else None)
                    for leaf_id, score in sorted(by_leaf.items())
                },
                "cost_usd": checkpoint["cost_usd"],
                "receipt_sha256": checkpoint["receipt_sha256"],
                "receipt_replayed": checkpoint["receipt_replayed"],
            }
        )
    total_cost = sum(float(record["cost_usd"]) for record in records) + sum(
        float(row["cost_usd"]) for row in trajectory_rows
    )
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "plan_sha256": plan["plan_sha256"],
        "canary_status": canary["status"],
        "canary_cost_usd": sum(float(record["cost_usd"]) for record in records),
        "canary_probe_count": len(records),
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
        "panel_design": plan["panel_design"],
        "baseline_policy": plan["baseline_policy"],
        "communication_note": (
            "this adapter's discuss and reflect actions carry no content, so "
            "the panel measures the common-pool dilemma with communication "
            "removed; the model chooses harvest quantities only"
        ),
        "sanitization": dict(SANITIZATION_DECLARATION),
    }
    files: dict[str, bytes] = {
        "README.md": (
            "# govsim first live panel\n\n"
            "One unscored route canary plus one case per scenario (fishing, "
            "pollution, sheep) on the pinned OpenRouter GLM 5.3 "
            "Flash/Parasail route.\n\n"
            "Two things a reader needs. The corpus's nine cases are three "
            "configurations repeated three times -- identical world seed and "
            "env_cfg, differing only in a policy assignment that has no "
            "effect when every seat is the model -- so the panel runs three. "
            "And this adapter's discuss and reflect actions carry no content, "
            "so what is measured is the common-pool dilemma with "
            "communication removed.\n\n"
            "Comparative leaves are scored against govsim_sustainable_v1, "
            "produced by running that scripted policy through this same "
            "environment provider-free; the policy digest and the three "
            "values are in the plan.\n"
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
        "campaign_id": CAMPAIGN_ID,
        "plan_sha256": plan["plan_sha256"],
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
    parser.add_argument("--upstream-root", type=Path, default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--publish-to", type=Path, default=None)
    args = parser.parse_args(argv)
    upstream_root = args.upstream_root or Path(
        os.environ.get("AEREAD_GOVSIM_UPSTREAM_ROOT", "")
    )
    if args.publish_to is not None:
        publish_campaign(run_root=args.run_root, publication_root=args.publish_to)
        return 0
    if not args.execute:
        bridge = GovsimBridge.discover(upstream_root=upstream_root)
        baselines = compute_panel_baselines(
            upstream_root=upstream_root, bridge=bridge
        )
        plan = build_campaign_plan(baselines=baselines)
        print(
            json.dumps(
                {"plan_sha256": plan["plan_sha256"], "campaign_id": CAMPAIGN_ID}
            )
        )
        return 0
    asyncio.run(
        execute_campaign(run_root=args.run_root, upstream_root=upstream_root)
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
