"""First-light GLM 5.2/Arena campaign for the STEER adapter."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.adapter_campaign import _digest, _write_once
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

from .live import CANARY_SPEC, MAX_OUTPUT_TOKENS, MODEL, PROVIDER, REVISION, ROUTE_PROVIDER, build_live_setup, load_case

CAMPAIGN_ID = "steer_glm5p2_arena_first_light_v6"
CASE_IDS = (
    "steer.transitivity.0_0",
    "steer.certainty_effect.0_0",
    "steer.pure_nash.0_0",
    "steer.backward_induction.50_0",
    "steer.plurality_voting.0_0",
    "steer.dsic_mechanism.0_0",
)
SEED = 300
MAX_CASE_COST_USD = 0.03
HARD_TOTAL_COST_USD = 0.20
SKIPPED_CASES = {
    "steer.certainty_effect.0_0": {
        "reason": "repeated_provider_length_without_visible_answer",
        "evidence": "evidence/steer_glm5p2_arena_first_light_v4/reports/summary.json",
    }
}


def _failure_condition(error: BaseException) -> str:
    """Recover the provider condition hidden by scheduler exception wrapping."""
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        condition = getattr(current, "condition", None)
        if isinstance(condition, str) and condition:
            return condition
        current = current.__cause__ or current.__context__
    return "execution_failure"


def campaign_plan() -> dict[str, Any]:
    cases = [load_case(case_id) for case_id in CASE_IDS]
    value: dict[str, Any] = {
        "schema_version": "aeread.adapter_live_campaign/0.1",
        "campaign_id": CAMPAIGN_ID,
        "family_id": "steer",
        "route": {
            "provider": PROVIDER,
            "model": MODEL,
            "revision": REVISION,
            "route_provider": ROUTE_PROVIDER,
            "canary_spec_sha256": CANARY_SPEC.spec_sha256,
            "substitution_for_issue_93": "glm-5.3-flash/Parasail unavailable to owner",
        },
        "panel": [
            {"case_id": case.case_id, "case_sha256": case.content_sha256, "seed": SEED}
            for case in cases
        ],
        "execution": {
            "sequential": True,
            "abort_on_operational_failure": False,
            "replay_every_receipt": True,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "reasoning_effort": "none",
            "predeclared_skips": SKIPPED_CASES,
        },
        "budget": {
            "max_case_cost_usd": MAX_CASE_COST_USD,
            "hard_total_cost_usd": HARD_TOTAL_COST_USD,
        },
    }
    value["plan_sha256"] = _digest(value)
    return value


async def execute(*, run_root: Path, data_root: Path) -> None:
    plan = campaign_plan()
    _write_once(run_root / "campaign_plan.json", plan)
    canary = json.loads((run_root / "checkpoints" / "canary.json").read_text())
    if (
        canary.get("status") != "admitted"
        or canary.get("family_id") != "steer"
        or canary.get("plan_sha256") != plan["plan_sha256"]
        or canary.get("spec_sha256") != CANARY_SPEC.spec_sha256
    ):
        raise RuntimeError("STEER canary was not admitted")
    total = float(canary.get("cost_usd", 0.0))
    provider = ArenaChatClient()
    for ordinal, case_id in enumerate(CASE_IDS):
        checkpoint_path = run_root / "checkpoints" / f"{ordinal:02d}_{case_id}.json"
        if checkpoint_path.exists():
            checkpoint = json.loads(checkpoint_path.read_text())
            total += float(checkpoint.get("cost_usd", 0.0))
            continue
        if case_id in SKIPPED_CASES:
            record = {
                "schema_version": "aeread.adapter_checkpoint/0.1",
                "campaign_id": CAMPAIGN_ID,
                "plan_sha256": plan["plan_sha256"],
                "ordinal": ordinal,
                "case_id": case_id,
                "status": "skipped_prior_operational_failure",
                **SKIPPED_CASES[case_id],
            }
            record["record_sha256"] = _digest(record)
            _write_once(checkpoint_path, record)
            continue
        if total + MAX_CASE_COST_USD > HARD_TOTAL_COST_USD:
            raise RuntimeError("insufficient reserve for next STEER case")
        setup = build_live_setup(
            case_id=case_id,
            data_root=data_root,
            seed=SEED,
            max_cost_usd=MAX_CASE_COST_USD,
        )
        execution_root = run_root / "executions" / case_id
        try:
            result = await execute_plan_cell(
                plan=setup.plan,
                cell_id=setup.plan.cells[0].cell_id,
                registry=setup.registry,
                evidence_root=execution_root,
                prompt_sources=setup.prompt_sources,
                providers={PROVIDER: provider},
                pricing=setup.pricing,
            )
            receipt = finalize_family_execution(setup=setup, execution=result)
            replayed = replay_family_receipt(
                setup=setup, receipt=receipt, evidence_root=execution_root
            )
            if replayed.receipt_sha256 != receipt.receipt_sha256:
                raise RuntimeError("STEER receipt replay digest mismatch")
            cost = float(result.total_cost_usd)
            total += cost
            if total > HARD_TOTAL_COST_USD:
                raise RuntimeError("STEER campaign exceeded total cost ceiling")
            record = {
                "schema_version": "aeread.adapter_checkpoint/0.1",
                "campaign_id": CAMPAIGN_ID,
                "plan_sha256": plan["plan_sha256"],
                "ordinal": ordinal,
                "case_id": case_id,
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
                "status": "operational_failure",
                "failure_type": type(error).__name__,
                "failure_condition": _failure_condition(error),
            }
            record["record_sha256"] = _digest(record)
            _write_once(checkpoint_path, record)
            continue
        record["record_sha256"] = _digest(record)
        _write_once(checkpoint_path, record)


def publish(*, run_root: Path, publication_root: Path) -> None:
    plan = json.loads((run_root / "campaign_plan.json").read_text())
    rows: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for ordinal, case_id in enumerate(CASE_IDS):
        checkpoint = json.loads(
            (run_root / "checkpoints" / f"{ordinal:02d}_{case_id}.json").read_text()
        )
        if checkpoint.get("status") == "complete":
            serialized = read_evaluation_receipt(run_root / checkpoint["receipt_path"])
            receipt = deserialize_evaluation_receipt(serialized)
            receipts.append(
                receipt_projection(serialized, campaign_cell_key=f"{ordinal:02d}:{case_id}")
            )
            primary = receipt.scores[0]
            rows.append(
                {
                    "case_id": case_id,
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
                    "status": checkpoint["status"],
                    "failure_type": checkpoint.get("failure_type"),
                    "failure_condition": checkpoint.get("failure_condition"),
                    "reason": checkpoint.get("reason"),
                    "evidence": checkpoint.get("evidence"),
                }
            )
    completed = [row for row in rows if "receipt_sha256" in row]
    skipped = [row for row in rows if row["status"] == "skipped_prior_operational_failure"]
    failed = [row for row in rows if row["status"] == "operational_failure"]
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "status": "complete" if len(completed) == len(rows) else "complete_with_exclusions",
        "plan_sha256": plan["plan_sha256"],
        "planned_cases": len(rows),
        "completed_cases": len(completed),
        "skipped_cases": len(skipped),
        "failed_cases": len(failed),
        "included_cases": sum(row.get("inclusion_status") == "included" for row in rows),
        "total_panel_cost_usd": sum(float(row.get("cost_usd", 0.0)) for row in rows),
        "route": plan["route"],
        "sanitization": dict(SANITIZATION_DECLARATION),
    }
    files: dict[str, bytes] = {
        "README.md": (
            b"# STEER GLM 5.2 Arena first-light panel v6\n\n"
            b"Six fixed panel positions; one pre-declared provider-length skip; "
            b"completed receipts replayed and sanitized.\n"
        ),
        "reports/summary.json": canonical_json_bytes(summary) + b"\n",
        "trajectories/archive.jsonl": jsonl(rows),
    }
    for row in receipts:
        files[f"receipts/{row['case_id']}.json"] = canonical_json_bytes(row) + b"\n"
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


def publish_failure(*, run_root: Path, publication_root: Path) -> None:
    """Publish typed partial evidence after the frozen campaign aborts."""
    plan = json.loads((run_root / "campaign_plan.json").read_text())
    canary = json.loads((run_root / "checkpoints" / "canary.json").read_text())
    rows: list[dict[str, Any]] = []
    receipt_rows: list[dict[str, Any]] = []
    failure: dict[str, Any] | None = None
    for ordinal, case_id in enumerate(CASE_IDS):
        path = run_root / "checkpoints" / f"{ordinal:02d}_{case_id}.json"
        if not path.exists():
            break
        checkpoint = json.loads(path.read_text())
        if checkpoint.get("status") == "complete":
            serialized = read_evaluation_receipt(run_root / checkpoint["receipt_path"])
            receipt = deserialize_evaluation_receipt(serialized)
            receipt_rows.append(
                receipt_projection(serialized, campaign_cell_key=f"{ordinal:02d}:{case_id}")
            )
            primary = receipt.scores[0]
            rows.append(
                {
                    "case_id": case_id,
                    "status": receipt.status,
                    "inclusion_status": receipt.inclusion_status,
                    "primary": primary.primary.value if primary.primary else None,
                    "cost_usd": checkpoint["cost_usd"],
                    "receipt_sha256": receipt.receipt_sha256,
                    "receipt_replayed": checkpoint["receipt_replayed"],
                }
            )
        else:
            failure = {
                "case_id": case_id,
                "status": checkpoint["status"],
                "failure_type": checkpoint.get("failure_type"),
                "failure_condition": checkpoint.get("failure_condition"),
            }
            rows.append(failure)
            break
    if failure is None:
        raise RuntimeError("no failed checkpoint exists")
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "status": "aborted_on_operational_failure",
        "plan_sha256": plan["plan_sha256"],
        "canary_status": canary["status"],
        "attempted_cases": len(rows),
        "completed_cases": len(receipt_rows),
        "planned_cases": len(CASE_IDS),
        "failure": failure,
        "route": plan["route"],
        "reported_cost_usd": float(canary.get("cost_usd", 0.0))
        + sum(float(row.get("cost_usd", 0.0)) for row in rows),
        "sanitization": dict(SANITIZATION_DECLARATION),
    }
    files: dict[str, bytes] = {
        "README.md": (
            b"# STEER GLM 5.2 Arena first-light attempt v6\n\n"
            b"The canary was admitted. The campaign aborted on the first operational "
            b"failure; unattempted cells were not run.\n"
        ),
        "reports/summary.json": canonical_json_bytes(summary) + b"\n",
        "trajectories/archive.jsonl": jsonl(rows),
    }
    for row in receipt_rows:
        files[f"receipts/{row['case_id']}.json"] = canonical_json_bytes(row) + b"\n"
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
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--publish-only", action="store_true")
    parser.add_argument("--publish-failure", action="store_true")
    args = parser.parse_args(argv)
    if args.execute:
        if args.data_root is None:
            parser.error("--execute requires --data-root")
        asyncio.run(execute(run_root=args.run_root, data_root=args.data_root))
    elif args.publish_only:
        if args.publication_root is None:
            parser.error("--publish-only requires --publication-root")
        publish(run_root=args.run_root, publication_root=args.publication_root)
    elif args.publish_failure:
        if args.publication_root is None:
            parser.error("--publish-failure requires --publication-root")
        publish_failure(run_root=args.run_root, publication_root=args.publication_root)
    else:
        print(json.dumps(campaign_plan(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
