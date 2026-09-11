"""Run a Refund V2 1:N panel with an active Arena policy agent.

The intake, customer, and payments seats remain deterministic. Only the policy
seat is supplied by the model, so the report separates policy behavior from
transaction and coordination behavior.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import ArenaChatClient, ProviderFailure, ProviderRequest

from .v2_environment import build_1n_case, run_1n_with_policy_turns


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["request_facts", "approve_direct", "deny"]},
        "amount": {"type": "number"},
        "method": {"type": ["string", "null"]},
        "reason": {"type": ["string", "null"]},
        "proposal_id": {"type": "string"},
        "requested_fields": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["decision"],
    "additionalProperties": False,
}


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)


def _report_filename(model: str) -> str:
    label = re.sub(r"[^a-z0-9]+", "_", model.lower()).strip("_")
    return f"refund_v2_1n_{label}_summary.json"


def _write_trajectory_evidence(output: Path, rows: list[dict[str, Any]]) -> None:
    evidence_dir = output / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    for ordinal, row in enumerate(rows, start=1):
        label = "positive" if row["positive"] else "denial"
        filename = f"{ordinal:03d}_seed_{row['world_seed']:06d}_{label}.json"
        payload = {
            "schema_version": "aeread.refund_v2.trajectory_evidence/1.0",
            "family_id": "refund_v2",
            "family_version": "2.0.0",
            "model": row.get("provider", {}).get("resolved_model"),
            "case_id": row["case_id"],
            "world_seed": row["world_seed"],
            "positive": row["positive"],
            "content_sha256": row["content_sha256"],
            "policy_turns": row.get("policy_turns", []),
            "transcript": row.get("transcript", []),
            "outcome": row.get("outcome"),
            "provider": row.get("provider"),
        }
        data = canonical_json_bytes(payload) + b"\n"
        path = evidence_dir / filename
        path.write_bytes(data)
        manifest.append({
            "case_id": row["case_id"],
            "world_seed": row["world_seed"],
            "positive": row["positive"],
            "relative_path": f"evidence/{filename}",
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    (evidence_dir / "README.md").write_text(
        "# Refund V2 trajectory evidence\n\n"
        "Each JSON file contains one complete recorded policy trajectory, "
        "including policy turns, customer disclosures, transcript, provider "
        "metadata, and verifier outcomes. The manifest binds each file to its "
        "case and content digest.\n",
        encoding="utf-8",
    )
    (output / "evidence_manifest.json").write_bytes(canonical_json_bytes({"trajectories": manifest}) + b"\n")


def _request(case: Any, revealed_facts: dict[str, Any], *, model: str, revision: str | None, reasoning_effort: str | None, max_output_tokens: int, timeout: float, seed: int, turn: int) -> ProviderRequest:
    public_case = {
        "case_id": case.case_id,
        "world_seed": case.world_seed,
        "product_category": case.product_category,
        "price": case.price,
        "days_since_delivery": case.days_since_delivery,
        "public_claim": case.public_claim,
        "revealed_facts": revealed_facts,
        "available_fact_ids": [field for field in case.required_facts if field not in revealed_facts],
        "handoff": {"from": "intake" if turn == 0 else "customer", "to": "policy"},
    }
    instructions = (
        "You are the policy agent in a refund benchmark. Decide only from the "
        "public case and facts revealed by intake. Do not invent undisclosed facts. "
        "If a required fact is missing, return decision request_facts and request at "
        "no more than three available_fact_ids. Do not decide before the needed facts "
        "are disclosed. Approve exactly the authorized refund when the disclosed facts support it; "
        "otherwise deny. For approval use method original_payment; for denial use "
        "amount 0 and method none. Return only JSON matching the supplied schema."
    )
    return ProviderRequest(
        provider_call_id=f"refund-v2-policy-{case.world_seed}-{turn}",
        provider="arena",
        base_url="https://api.preview.arena.ai/v1",
        model=model,
        revision=revision,
        instructions=instructions,
        input_text=canonical_json_bytes(public_case).decode("utf-8"),
        temperature=None if model.startswith("gpt-5.6") else 0.0,
        top_p=None,
        max_output_tokens=max_output_tokens,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout,
        request_sha256="",
        output_schema=OUTPUT_SCHEMA,
        seed=seed,
    ).with_computed_hash()


async def run(*, seeds: tuple[int, ...], output: Path, model: str, revision: str | None, reasoning_effort: str | None, max_output_tokens: int, timeout: float, env_file: Path | None) -> dict[str, Any]:
    if env_file is not None:
        _load_env(env_file)
    try:
        from openai import AsyncOpenAI
    except ImportError as error:  # pragma: no cover - environment dependency
        raise RuntimeError("the openai package is required for the Arena experiment") from error
    api_key = os.environ.get("ARENA_API_KEY")
    if not api_key:
        raise RuntimeError("ARENA_API_KEY must be set, directly or through --env-file")
    client = ArenaChatClient(sdk_client=AsyncOpenAI(
        api_key=api_key,
        base_url="https://api.preview.arena.ai/v1",
        max_retries=0,
        timeout=timeout,
    ))
    semaphore = asyncio.Semaphore(4)

    async def run_one(seed: int, positive: bool) -> dict[str, Any]:
        async with semaphore:
            case = build_1n_case(seed, positive=positive)
            row: dict[str, Any] = {
                "case_id": case.case_id,
                "world_seed": seed,
                "positive": positive,
                "content_sha256": case.content_sha256,
            }
            try:
                revealed_facts: dict[str, Any] = {}
                turns: list[dict[str, Any]] = []
                provider_results = []
                for turn in range(4):
                    result = await client.complete(_request(
                        case,
                        revealed_facts,
                        model=model,
                        revision=revision,
                        reasoning_effort=reasoning_effort,
                        max_output_tokens=max_output_tokens,
                        timeout=timeout,
                        seed=seed,
                        turn=turn,
                    ))
                    provider_results.append(result)
                    action = json.loads(result.output_text)
                    turns.append(action)
                    if action.get("decision") != "request_facts":
                        break
                    requested = action.get("requested_fields", [])
                    if not isinstance(requested, list):
                        break
                    for field in requested[:3]:
                        if field in case.required_facts and field not in revealed_facts:
                            revealed_facts[field] = case.private_facts[field]
                state, outcome = run_1n_with_policy_turns(case, turns)
                result = provider_results[-1]
                proposal = turns[-1] if turns and turns[-1].get("decision") in {"approve_direct", "deny"} else None
                row.update({
                    "status": "completed",
                    "proposal": proposal,
                    "policy_turns": turns,
                    "transcript": state.transcript,
                    "outcome": {
                        "decision": outcome.decision,
                        "utility_score": outcome.utility_score,
                        "transaction_score": outcome.transaction_score,
                        "coordination_score": outcome.coordination_score,
                        "policy_compliant": outcome.policy_compliant,
                        "verifier_reasons": list(outcome.verifier_reasons),
                    },
                    "provider": {
                        "response_id": result.response_id,
                        "resolved_model": result.resolved_model,
                        "finish_reason": result.finish_reason,
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                        "reasoning_tokens": result.reasoning_tokens,
                        "cost_usd": result.cost_usd,
                    },
                })
            except (ProviderFailure, json.JSONDecodeError, TypeError, ValueError, KeyError, AttributeError, OverflowError) as error:
                row.update({"status": "failed", "failure": str(error)})
            return row

    rows = list(await asyncio.gather(*(run_one(seed, positive) for seed in seeds for positive in (True, False))))
    _write_trajectory_evidence(output, rows)
    for ordinal, row in enumerate(rows, start=1):
        label = "positive" if row["positive"] else "denial"
        row["evidence_path"] = f"evidence/{ordinal:03d}_seed_{row['world_seed']:06d}_{label}.json"
    completed = [row for row in rows if row["status"] == "completed"]
    report = {
        "family_id": "refund_v2",
        "family_version": "2.0.0",
        "topology": "1:N",
        "active_agent": "policy",
        "scripted_agents": ["intake", "customer", "payments"],
        "model": model,
        "revision": revision,
        "reasoning_effort": reasoning_effort,
        "seeds": seeds,
        "planned_cases": len(rows),
        "completed_cases": len(completed),
        "operational_failures": len(rows) - len(completed),
        "means": {
            metric: (sum(row["outcome"][metric] for row in completed) / len(completed) if completed else None)
            for metric in ("utility_score", "transaction_score", "coordination_score")
        },
        "policy_compliance_rate": (sum(row["outcome"]["policy_compliant"] for row in completed) / len(completed) if completed else None),
        "results": rows,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / _report_filename(model)).write_bytes(canonical_json_bytes(report) + b"\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world-seeds", default="1,2,3,4,5")
    parser.add_argument("--model", default="deepseek-v4-flash-0731")
    parser.add_argument("--revision", default=None)
    parser.add_argument("--reasoning-effort", default=None)
    parser.add_argument("--max-output-tokens", type=int, default=1024)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    seeds = tuple(int(item.strip()) for item in args.world_seeds.split(",") if item.strip())
    report = asyncio.run(run(
        seeds=seeds,
        output=args.output,
        model=args.model,
        revision=args.revision,
        reasoning_effort=args.reasoning_effort,
        max_output_tokens=args.max_output_tokens,
        timeout=args.timeout,
        env_file=args.env_file,
    ))
    print(json.dumps({key: report[key] for key in ("planned_cases", "completed_cases", "operational_failures", "means", "policy_compliance_rate")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
