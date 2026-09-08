"""First-light GLM 5.2/Arena campaign for the AucArena adapter."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.adapter_campaign import (
    MODEL,
    PROVIDER,
    REVISION,
    ROUTE_PROVIDER,
    _digest,
    _write_once,
)
from aeread.shared_runner.analysis.research import deserialize_evaluation_receipt
from aeread.shared_runner.run.publication import (
    SANITIZATION_DECLARATION,
    assert_public_payload,
    atomic_publish,
    jsonl,
    receipt_projection,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import finalize_family_execution, replay_family_receipt
from aeread.shared_runner.task.execution import ArenaChatClient, execute_plan_cell
from aeread.shared_runner.task.receipts import read_evaluation_receipt

from .live import (
    MAX_OUTPUT_TOKENS,
    RULE_PROVIDER,
    RuleNoopClient,
    build_live_setup,
    load_case,
)

CAMPAIGN_ID = "aucarena_glm5p2_arena_first_light_v3"
CELLS = (
    ("aucarena.pilot.successful_01", 300),
    ("aucarena.pilot.valid_but_poor_01", 300),
    ("aucarena.pilot.invalid_unauthorized_01", 300),
    ("aucarena.pilot.malformed_operational_01", 300),
    ("aucarena.pilot.degenerate_reference_01", 300),
    ("aucarena.pilot.successful_01", 301),
)
MAX_CASE_COST_USD = 0.03
HARD_TOTAL_COST_USD = 0.20


def _failure_condition(error: BaseException) -> str:
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        condition = getattr(current, "condition", None)
        if isinstance(condition, str) and condition:
            return condition
        current = current.__cause__ or current.__context__
    return "execution_failure"


def _checkpoint_name(ordinal: int, case_id: str, seed: int) -> str:
    return f"{ordinal:02d}_{case_id}_s{seed}.json"


def campaign_plan() -> dict[str, Any]:
    panel = []
    for case_id, seed in CELLS:
        case = load_case(case_id)
        panel.append({"case_id": case_id, "case_sha256": case.content_sha256, "seed": seed})
    value: dict[str, Any] = {
        "schema_version": "aeread.adapter_live_campaign/0.1",
        "campaign_id": CAMPAIGN_ID,
        "family_id": "aucarena",
        "route": {
            "provider": PROVIDER,
            "model": MODEL,
            "revision": REVISION,
            "route_provider": ROUTE_PROVIDER,
            "substitution_for_issue_93": "glm-5.3-flash/Parasail unavailable to owner",
        },
        "panel": panel,
        "execution": {
            "sequential": True,
            "abort_on_operational_failure": False,
            "replay_every_receipt": True,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "reasoning_effort": "none",
            "sixth_cell": "prespecified replicate of successful_01",
        },
        "budget": {
            "max_case_cost_usd": MAX_CASE_COST_USD,
            "hard_total_cost_usd": HARD_TOTAL_COST_USD,
        },
    }
    value["plan_sha256"] = _digest(value)
    return value


async def execute(*, run_root: Path) -> None:
    plan = campaign_plan()
    _write_once(run_root / "campaign_plan.json", plan)
    canary = json.loads((run_root / "checkpoints" / "canary.json").read_text())
    if canary.get("status") != "admitted" or canary.get("family_id") != "aucarena":
        raise RuntimeError("AucArena canary was not admitted")
    total = float(canary.get("cost_usd", 0.0))
    provider = ArenaChatClient()
    for ordinal, (case_id, seed) in enumerate(CELLS):
        checkpoint_path = run_root / "checkpoints" / _checkpoint_name(ordinal, case_id, seed)
        if checkpoint_path.exists():
            total += float(json.loads(checkpoint_path.read_text()).get("cost_usd", 0.0))
            continue
        if total + MAX_CASE_COST_USD > HARD_TOTAL_COST_USD:
            raise RuntimeError("insufficient reserve for next AucArena case")
        setup = build_live_setup(
            case_id=case_id, sampling_seed=seed, max_cost_usd=MAX_CASE_COST_USD
        )
        execution_root = run_root / "executions" / f"{ordinal:02d}_{case_id}_s{seed}"
        try:
            result = await execute_plan_cell(
                plan=setup.plan,
                cell_id=setup.plan.cells[0].cell_id,
                registry=setup.registry,
                evidence_root=execution_root,
                prompt_sources=setup.prompt_sources,
                providers={PROVIDER: provider, RULE_PROVIDER: RuleNoopClient()},
                pricing=setup.pricing,
            )
            receipt = finalize_family_execution(setup=setup, execution=result)
            replayed = replay_family_receipt(
                setup=setup, receipt=receipt, evidence_root=execution_root
            )
            if replayed.receipt_sha256 != receipt.receipt_sha256:
                raise RuntimeError("AucArena receipt replay digest mismatch")
            cost = float(result.total_cost_usd)
            total += cost
            if total > HARD_TOTAL_COST_USD:
                raise RuntimeError("AucArena campaign exceeded total cost ceiling")
            record = {
                "schema_version": "aeread.adapter_checkpoint/0.1",
                "campaign_id": CAMPAIGN_ID,
                "plan_sha256": plan["plan_sha256"],
                "ordinal": ordinal,
                "case_id": case_id,
                "seed": seed,
                "status": "complete",
                "receipt_path": str(
                    (result.evidence.root / "evaluation_receipt.json").relative_to(run_root)
                ),
                "receipt_sha256": receipt.receipt_sha256,
                "receipt_replayed": True,
                "receipt_status": receipt.status,
                "inclusion_status": receipt.inclusion_status,
                "cost_usd": cost,
            }
        except Exception as error:
            record = {
                "schema_version": "aeread.adapter_checkpoint/0.1",
                "campaign_id": CAMPAIGN_ID,
                "plan_sha256": plan["plan_sha256"],
                "ordinal": ordinal,
                "case_id": case_id,
                "seed": seed,
                "status": "operational_failure",
                "failure_type": type(error).__name__,
                "failure_condition": _failure_condition(error),
            }
        record["record_sha256"] = _digest(record)
        _write_once(checkpoint_path, record)


def publish(*, run_root: Path, publication_root: Path) -> None:
    plan = json.loads((run_root / "campaign_plan.json").read_text())
    rows: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for ordinal, (case_id, seed) in enumerate(CELLS):
        checkpoint = json.loads(
            (run_root / "checkpoints" / _checkpoint_name(ordinal, case_id, seed)).read_text()
        )
        if checkpoint["status"] == "complete":
            serialized = read_evaluation_receipt(run_root / checkpoint["receipt_path"])
            receipt = deserialize_evaluation_receipt(serialized)
            cell_key = f"{ordinal:02d}:{case_id}:s{seed}"
            receipts.append(receipt_projection(serialized, campaign_cell_key=cell_key))
            primary = receipt.scores[0]
            rows.append(
                {
                    "case_id": case_id,
                    "seed": seed,
                    "status": receipt.status,
                    "inclusion_status": receipt.inclusion_status,
                    "primary": primary.primary.value if primary.primary else None,
                    "cost_usd": checkpoint["cost_usd"],
                    "receipt_sha256": receipt.receipt_sha256,
                    "receipt_replayed": checkpoint["receipt_replayed"],
                }
            )
        else:
            rows.append(
                {
                    "case_id": case_id,
                    "seed": seed,
                    "status": checkpoint["status"],
                    "failure_type": checkpoint.get("failure_type"),
                    "failure_condition": checkpoint.get("failure_condition"),
                }
            )
    completed = [row for row in rows if "receipt_sha256" in row]
    failed = [row for row in rows if row["status"] == "operational_failure"]
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "status": "complete" if len(completed) == len(rows) else "complete_with_exclusions",
        "plan_sha256": plan["plan_sha256"],
        "planned_cases": len(rows),
        "completed_cases": len(completed),
        "failed_cases": len(failed),
        "included_cases": sum(row.get("inclusion_status") == "included" for row in rows),
        "total_panel_cost_usd": sum(float(row.get("cost_usd", 0.0)) for row in rows),
        "route": plan["route"],
        "sanitization": dict(SANITIZATION_DECLARATION),
    }
    files: dict[str, bytes] = {
        "README.md": (
            b"# AucArena GLM 5.2 Arena first-light panel v3\n\n"
            b"Six sequential cells; completed receipts replayed and sanitized.\n"
        ),
        "reports/summary.json": canonical_json_bytes(summary) + b"\n",
        "trajectories/archive.jsonl": jsonl(rows),
    }
    for ordinal, row in enumerate(receipts):
        files[f"receipts/{ordinal:02d}_{row['case_id']}.json"] = (
            canonical_json_bytes(row) + b"\n"
        )
    artifacts = [
        {"path": name, "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)}
        for name, payload in sorted(files.items())
    ]
    manifest = {
        "schema_version": "aeread.publication_manifest/0.1",
        "publication_id": CAMPAIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "plan_sha256": plan["plan_sha256"],
        "artifacts": artifacts,
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
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--publish-only", action="store_true")
    args = parser.parse_args(argv)
    if args.execute:
        asyncio.run(execute(run_root=args.run_root))
    elif args.publish_only:
        if args.publication_root is None:
            parser.error("--publish-only requires --publication-root")
        publish(run_root=args.run_root, publication_root=args.publication_root)
    else:
        print(json.dumps(campaign_plan(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
