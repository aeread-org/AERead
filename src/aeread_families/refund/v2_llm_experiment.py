"""Run a Refund V2.1 1:N panel with independently selectable active seats.

The intake, customer, and policy seats can each be supplied by Arena. Any seat
not selected by ``--active-agents`` uses its deterministic counterpart, while
payments remains scripted and verifier-protected.
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
from aeread.shared_runner.run.publication import sanitized_trajectory_jsonl
from aeread.shared_runner.task.execution import ArenaChatClient, EvidenceStore, ProviderFailure, ProviderRequest

from .v2_environment import (
    AgentActivationConfig,
    build_1n_panel,
    run_1n_with_policy_turns,
    run_1n_with_role_actions,
    validate_active_agents,
)


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

INTAKE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["request_facts"]},
        "requested_fields": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["decision", "requested_fields"],
}

CUSTOMER_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["provide_info", "state_request"]},
        "reveal_fields": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["decision", "reveal_fields"],
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
    trajectories_dir = evidence_dir / "trajectories"
    trajectories_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    for ordinal, row in enumerate(rows, start=1):
        label = row.get("scenario", "positive" if row["positive"] else "denial")
        filename = f"{ordinal:03d}_seed_{row['world_seed']:06d}_{label}.json"
        payload = {
            "schema_version": "aeread.refund_v2.trajectory_evidence/1.0",
            "family_id": "refund_v2",
            "family_version": "2.1.0",
            "model": row.get("provider", {}).get("resolved_model"),
            "case_id": row["case_id"],
            "world_seed": row["world_seed"],
            "positive": row["positive"],
            "scenario": row.get("scenario"),
            "content_sha256": row["content_sha256"],
            "policy_turns": row.get("policy_turns", []),
            "transcript": row.get("transcript", []),
            "handoffs": row.get("handoffs", []),
            "proposals": row.get("proposals", []),
            "confirmations": row.get("confirmations", []),
            "transactions": row.get("transactions", []),
            "invalid_fact_requests": row.get("invalid_fact_requests", []),
            "outcome": row.get("outcome"),
            "failure": row.get("failure"),
            "provider": row.get("provider"),
            "active_agents": row.get("active_agents", []),
            "scripted_agents": row.get("scripted_agents", []),
        }
        data = canonical_json_bytes(payload) + b"\n"
        trajectory_dir = trajectories_dir / filename.removesuffix(".json")
        trajectory_dir.mkdir(parents=True, exist_ok=True)
        path = trajectory_dir / "trajectory.json"
        path.write_bytes(data)
        with EvidenceStore(
            trajectory_dir,
            run_plan_id="refund_v2_1n",
            cell_id=f"cell_{ordinal:04d}",
            episode_id=row["case_id"],
            episode_attempt_id=f"attempt_{ordinal:04d}",
        ) as store:
            store.append_event("trajectory_recorded", payload)
            store.seal()
        manifest.append({
            "case_id": row["case_id"],
            "world_seed": row["world_seed"],
            "positive": row["positive"],
            "relative_path": f"evidence/trajectories/{filename.removesuffix('.json')}/trajectory.json",
            "evidence_root": f"evidence/trajectories/{filename.removesuffix('.json')}",
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    (evidence_dir / "README.md").write_text(
        "# Refund V2 trajectory evidence\n\n"
        "Each trajectory directory contains a human-readable trajectory.json "
        "and a sealed EvidenceStore event chain with content-addressed artifacts. "
        "The manifest binds each trajectory to its case and content digest.\n",
        encoding="utf-8",
    )
    (output / "evidence_manifest.json").write_bytes(canonical_json_bytes({"trajectories": manifest}) + b"\n")
    _write_standard_publication(output, rows)


def _write_standard_publication(output: Path, rows: list[dict[str, Any]]) -> None:
    trajectory_rows: list[dict[str, Any]] = []
    receipt_rows: list[dict[str, Any]] = []
    for ordinal, row in enumerate(rows, start=1):
        case_id = row["case_id"]
        episode_attempt_id = f"attempt_{ordinal:04d}"
        resolved_model = row.get("provider", {}).get("resolved_model")
        run_plan_sha256 = hashlib.sha256(canonical_json_bytes({
            "family_id": "refund_v2",
            "family_version": "2.1.0",
            "topology": "1:N",
            "model": resolved_model,
            "active_agents": row.get("active_agents", []),
        })).hexdigest()
        receipt_basis = {
            "publication_ordinal": ordinal,
            "case_id": case_id,
            "content_sha256": row["content_sha256"],
            "provider": row.get("provider"),
            "active_agents": row.get("active_agents", []),
            "transcript": row.get("transcript", []),
            "outcome": row.get("outcome"),
            "status": row.get("status", "completed"),
        }
        receipt_sha256 = hashlib.sha256(canonical_json_bytes(receipt_basis)).hexdigest()
        transcript = row.get("transcript", [])
        provider_attempts = row.get("provider_attempts", [])
        attempts_by_role: dict[str, list[dict[str, Any]]] = {}
        for provider_attempt in provider_attempts:
            if isinstance(provider_attempt, dict):
                attempts_by_role.setdefault(provider_attempt.get("role", ""), []).append(provider_attempt)
        role_indices: dict[str, int] = {}
        episode_id = f"episode_{ordinal:04d}"
        for step_index, event in enumerate(transcript):
            speaker = event.get("speaker", "unknown") if isinstance(event, dict) else "unknown"
            action = dict(event) if isinstance(event, dict) else {"message": str(event)}
            role_index = role_indices.get(speaker, 0)
            role_indices[speaker] = role_index + 1
            provider_attempt = (
                attempts_by_role.get(speaker, [])[role_index]
                if role_index < len(attempts_by_role.get(speaker, []))
                else None
            )
            attempts = []
            if provider_attempt is not None:
                action_attempt_id = f"action_attempt_{ordinal:04d}_{step_index:04d}"
                attempts = [{
                    "action_attempt_id": action_attempt_id,
                    "failure_condition": None,
                    "max_output_tokens": provider_attempt["max_output_tokens"],
                    "ordinal": 0,
                    "provider_calls": [{
                        key: provider_attempt[key]
                        for key in (
                            "provider_call_id", "request_sha256", "requested_model",
                            "resolved_model", "response_id", "finish_reason",
                            "input_tokens", "cached_input_tokens", "output_tokens",
                            "reasoning_tokens", "visible_output_tokens", "cost_usd",
                        )
                    }],
                    "response": {
                        "cached_input_tokens": provider_attempt["cached_input_tokens"],
                        "cost_usd": provider_attempt["cost_usd"],
                        "empty": False,
                        "finish_reason": provider_attempt["finish_reason"],
                        "input_tokens": provider_attempt["input_tokens"],
                        "output_tokens": provider_attempt["output_tokens"],
                        "provider_call_ids": [provider_attempt["provider_call_id"]],
                        "tool_invocation_ids": [],
                        "truncated": provider_attempt["finish_reason"] == "length",
                    },
                    "retry_reason": None,
                    "session_mode": "restart",
                    "status": "succeeded",
                }]
            active_agents = row.get("active_agents", [])
            profile_id = (
                resolved_model
                if speaker in active_agents
                else "scripted"
            )
            trajectory_rows.append({
                "schema_version": "aeread.sanitized_trajectory_row/0.1",
                "source_receipt_sha256": receipt_sha256,
                "run_plan_id": "refund_v2_1n",
                "run_plan_sha256": run_plan_sha256,
                "cell_id": f"cell_{ordinal:04d}",
                "case_id": case_id,
                "episode_id": episode_id,
                "episode_attempt_id": episode_attempt_id,
                "step_index": step_index,
                "logical_action_id": f"logical_action_{ordinal:04d}_{step_index:04d}",
                "phase_id": "refund_v2_1n",
                "phase_instance_id": f"phase_{ordinal:04d}",
                "seat_id": speaker,
                "role": speaker,
                "profile_id": profile_id,
                "attempts": attempts,
                "parse": {"ok": True, "error_code": None},
                "action": action,
                "legality": {"legal": not bool(row.get("invalid_fact_requests")), "reason": None},
                "outcome": {
                    "status": "succeeded" if step_index == len(transcript) - 1 and row.get("status") == "completed" else "in_progress",
                    "valid": row.get("outcome", {}).get("policy_compliant") if step_index == len(transcript) - 1 else None,
                    "failure_code": row.get("failure") if step_index == len(transcript) - 1 else None,
                },
                "tools": [],
            })
        outcome = row.get("outcome") or {}
        receipt_rows.append({
            "source_receipt_sha256": receipt_sha256,
            "spec_version": "aeread.refund_v2.receipt/1.0",
            "status": "succeeded" if row.get("status") == "completed" else "failed",
            "inclusion_status": "included" if row.get("status") == "completed" else "excluded",
            "run_plan_id": "refund_v2_1n",
            "run_plan_sha256": run_plan_sha256,
            "cell_id": f"cell_{ordinal:04d}",
            "case_id": case_id,
            "case_sha256": row["content_sha256"],
            "episode_id": episode_id,
            "episode_attempt_id": episode_attempt_id,
            "cluster_id": str(row["world_seed"]),
            "cluster_level": "world_seed",
            "primary_leaf_id": "utility_score",
            "deferred_leaf_ids": [],
            "replay_level": "family_state_and_score",
            "evidence": {"trajectory_row_count": len(transcript)},
            "failure": {"condition": "provider_failure", "failure_class": "operational"} if row.get("failure") else None,
            "scores": {
                "utility_score": outcome.get("utility_score"),
                "transaction_score": outcome.get("transaction_score"),
                "coordination_score": outcome.get("coordination_score"),
                "policy_compliant": outcome.get("policy_compliant"),
            },
            "observability_limits": ["raw prompts and provider responses are excluded"],
            "campaign_cell_key": (
                f"{resolved_model or 'scripted'}__"
                f"{row.get('scenario', 'unknown')}__seed_{row['world_seed']}"
            ),
        })
    trajectories_dir = output / "trajectories"
    receipts_dir = output / "receipts"
    trajectories_dir.mkdir(parents=True, exist_ok=True)
    receipts_dir.mkdir(parents=True, exist_ok=True)
    (trajectories_dir / "sanitized.jsonl").write_bytes(sanitized_trajectory_jsonl(trajectory_rows))
    (receipts_dir / "projections.jsonl").write_bytes(
        b"".join(canonical_json_bytes(receipt) + b"\n" for receipt in receipt_rows)
    )


def _request(case: Any, revealed_facts: dict[str, Any], *, model: str, revision: str | None, reasoning_effort: str | None, max_output_tokens: int, timeout: float, seed: int, turn: int) -> ProviderRequest:
    public_case = {
        "case_id": case.case_id,
        "world_seed": case.world_seed,
        "product_category": case.product_category,
        "price": case.price,
        "days_since_delivery": case.days_since_delivery,
        "public_claim": case.public_claim,
        "scenario": case.scenario,
        "policy_summary": case.policy_summary,
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


def _seat_request(
    case: Any,
    role: str,
    payload: dict[str, Any],
    *,
    model: str,
    revision: str | None,
    reasoning_effort: str | None,
    max_output_tokens: int,
    timeout: float,
    seed: int,
    turn: int,
) -> ProviderRequest:
    if role == "intake":
        instructions = "You are the intake agent. Request at most three available fact IDs and return only JSON."
        schema = INTAKE_SCHEMA
    elif role == "customer":
        instructions = "You are the customer. Reveal only requested fact IDs from your private facts and return only JSON."
        schema = CUSTOMER_SCHEMA
    else:
        instructions = "You are the policy agent. Follow the disclosed policy and return only JSON."
        schema = OUTPUT_SCHEMA
    return ProviderRequest(
        provider_call_id=f"refund-v21-{role}-{case.case_id}-{turn}",
        provider="arena",
        base_url="https://api.preview.arena.ai/v1",
        model=model,
        revision=revision,
        instructions=instructions,
        input_text=canonical_json_bytes(payload).decode("utf-8"),
        temperature=None if model.startswith("gpt-5.6") else 0.0,
        top_p=None,
        max_output_tokens=max_output_tokens,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout,
        request_sha256="",
        output_schema=schema,
        seed=seed,
    ).with_computed_hash()


def _scripted_intake(case: Any) -> dict[str, Any]:
    return {"decision": "request_facts", "requested_fields": list(case.required_facts[:3])}


def _scripted_customer(requested_fields: list[str]) -> dict[str, Any]:
    return {"decision": "provide_info", "reveal_fields": list(requested_fields[:3])}


def _scripted_policy(case: Any, revealed_facts: dict[str, Any], turn: int) -> dict[str, Any]:
    missing = [field for field in case.required_facts if field not in revealed_facts]
    if missing:
        return {"decision": "request_facts", "requested_fields": missing[:3]}
    return {
        "decision": "approve_direct" if case.authorized_refund_amount else "deny",
        "amount": case.authorized_refund_amount,
        "method": case.authorized_refund_method,
        "reason": case.denial_reason,
        "proposal_id": f"proposal_{turn + 1}",
    }


def _provider_attempt_record(role: str, request: ProviderRequest, result: Any) -> dict[str, Any]:
    return {
        "role": role,
        "provider": request.provider,
        "provider_call_id": request.provider_call_id,
        "request_sha256": request.request_sha256,
        "requested_model": result.requested_model,
        "resolved_model": result.resolved_model,
        "response_id": result.response_id,
        "finish_reason": result.finish_reason,
        "input_tokens": result.input_tokens,
        "cached_input_tokens": result.cached_input_tokens,
        "output_tokens": result.output_tokens,
        "reasoning_tokens": result.reasoning_tokens,
        "visible_output_tokens": result.visible_output_tokens,
        "cost_usd": result.cost_usd or 0.0,
        "max_output_tokens": request.max_output_tokens,
    }


async def run(*, seeds: tuple[int, ...], output: Path, model: str, revision: str | None,
              reasoning_effort: str | None, max_output_tokens: int, timeout: float,
              env_file: Path | None, active_agents: tuple[str, ...] = ("policy",)) -> dict[str, Any]:
    active_agents = validate_active_agents(active_agents)
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

    async def run_one(seed: int, case: Any) -> dict[str, Any]:
        async with semaphore:
            row: dict[str, Any] = {
                "case_id": case.case_id,
                "world_seed": seed,
                "scenario": case.scenario,
                "positive": case.authorized_refund_amount > 0,
                "content_sha256": case.content_sha256,
                "active_agents": list(active_agents),
                "scripted_agents": [agent for agent in ("intake", "customer", "policy", "payments") if agent not in active_agents],
            }
            try:
                provider_results: list[Any] = []
                provider_attempts: list[dict[str, Any]] = []
                intake_payload = {
                    "case_id": case.case_id,
                    "public_claim": case.public_claim,
                    "product_category": case.product_category,
                    "price": case.price,
                    "days_since_delivery": case.days_since_delivery,
                    "available_fact_ids": list(case.required_facts),
                }
                if "intake" in active_agents:
                    request = _seat_request(
                        case, "intake", intake_payload, model=model, revision=revision,
                        reasoning_effort=reasoning_effort, max_output_tokens=max_output_tokens,
                        timeout=timeout, seed=seed, turn=0,
                    )
                    result = await client.complete(request)
                    provider_results.append(result)
                    provider_attempts.append(_provider_attempt_record("intake", request, result))
                    intake_action = json.loads(result.output_text)
                else:
                    intake_action = _scripted_intake(case)

                requested = intake_action.get("requested_fields", [])
                requested = requested if isinstance(requested, list) else []
                customer_payload = {
                    "case_id": case.case_id,
                    "requested_fields": requested[:3],
                    "private_facts": dict(case.private_facts),
                    "instruction": "Reveal only requested fields; never reveal any other field.",
                }
                if "customer" in active_agents:
                    request = _seat_request(
                        case, "customer", customer_payload, model=model, revision=revision,
                        reasoning_effort=reasoning_effort, max_output_tokens=max_output_tokens,
                        timeout=timeout, seed=seed, turn=0,
                    )
                    result = await client.complete(request)
                    provider_results.append(result)
                    provider_attempts.append(_provider_attempt_record("customer", request, result))
                    initial_customer_action = json.loads(result.output_text)
                else:
                    initial_customer_action = _scripted_customer(requested)

                revealed_facts: dict[str, Any] = {}
                initial_revealed = initial_customer_action.get("reveal_fields", [])
                if isinstance(initial_revealed, list):
                    for field in initial_revealed:
                        if field in requested[:3] and field in case.required_facts:
                            revealed_facts[field] = case.private_facts[field]
                turns: list[dict[str, Any]] = []
                customer_actions: list[dict[str, Any]] = []
                for turn in range(6):
                    policy_payload = {
                        "case_id": case.case_id,
                        "world_seed": case.world_seed,
                        "product_category": case.product_category,
                        "price": case.price,
                        "days_since_delivery": case.days_since_delivery,
                        "public_claim": case.public_claim,
                        "scenario": case.scenario,
                        "policy_summary": case.policy_summary,
                        "revealed_facts": revealed_facts,
                        "available_fact_ids": [field for field in case.required_facts if field not in revealed_facts],
                    }
                    if "policy" in active_agents:
                        request = _seat_request(
                            case, "policy", policy_payload, model=model, revision=revision,
                            reasoning_effort=reasoning_effort, max_output_tokens=max_output_tokens,
                            timeout=timeout, seed=seed, turn=turn,
                        )
                        result = await client.complete(request)
                        provider_results.append(result)
                        provider_attempts.append(_provider_attempt_record("policy", request, result))
                        action = json.loads(result.output_text)
                    else:
                        action = _scripted_policy(case, revealed_facts, turn)
                    turns.append(action)
                    if action.get("decision") != "request_facts":
                        break
                    requested = action.get("requested_fields", [])
                    requested = requested if isinstance(requested, list) else []
                    customer_payload = {
                        "case_id": case.case_id,
                        "requested_fields": requested[:3],
                        "private_facts": dict(case.private_facts),
                        "instruction": "Reveal only requested fields; never reveal any other field.",
                    }
                    if "customer" in active_agents:
                        request = _seat_request(
                            case, "customer", customer_payload, model=model, revision=revision,
                            reasoning_effort=reasoning_effort, max_output_tokens=max_output_tokens,
                            timeout=timeout, seed=seed, turn=turn + 1,
                        )
                        result = await client.complete(request)
                        provider_results.append(result)
                        provider_attempts.append(_provider_attempt_record("customer", request, result))
                        customer_action = json.loads(result.output_text)
                    else:
                        customer_action = _scripted_customer(requested)
                    customer_actions.append(customer_action)
                    revealed = customer_action.get("reveal_fields", [])
                    if isinstance(revealed, list):
                        for field in revealed:
                            if field in requested[:3] and field in case.required_facts and field not in revealed_facts:
                                revealed_facts[field] = case.private_facts[field]

                state, outcome = run_1n_with_role_actions(
                    case,
                    intake_action=intake_action,
                    initial_customer_action=initial_customer_action,
                    policy_turns=turns,
                    customer_actions=customer_actions,
                )
                result = provider_results[-1] if provider_results else None
                proposal = turns[-1] if turns and turns[-1].get("decision") in {"approve_direct", "deny"} else None
                row.update({
                    "status": "completed",
                    "proposal": proposal,
                    "policy_turns": turns,
                    "transcript": state.transcript,
                    "handoffs": state.handoffs,
                    "proposals": state.proposals,
                    "confirmations": state.confirmations,
                    "transactions": state.transactions,
                    "invalid_fact_requests": state.invalid_fact_requests,
                    "outcome": {
                        "decision": outcome.decision,
                        "utility_score": outcome.utility_score,
                        "transaction_score": outcome.transaction_score,
                        "coordination_score": outcome.coordination_score,
                        "policy_compliant": outcome.policy_compliant,
                        "verifier_reasons": list(outcome.verifier_reasons),
                    },
                    "provider": {
                        "response_id": result.response_id if result else None,
                        "resolved_model": result.resolved_model if result else None,
                        "finish_reason": result.finish_reason if result else None,
                        "input_tokens": sum(getattr(item, "input_tokens", 0) or 0 for item in provider_results),
                        "output_tokens": sum(getattr(item, "output_tokens", 0) or 0 for item in provider_results),
                        "reasoning_tokens": sum(getattr(item, "reasoning_tokens", 0) or 0 for item in provider_results),
                        "cost_usd": sum(getattr(item, "cost_usd", 0.0) or 0.0 for item in provider_results),
                    },
                    "provider_attempts": provider_attempts,
                })
            except (ProviderFailure, json.JSONDecodeError, TypeError, ValueError, KeyError, AttributeError, OverflowError) as error:
                row.update({"status": "failed", "failure": str(error)})
            return row

    rows = list(await asyncio.gather(*(run_one(seed, case) for seed in seeds for case in build_1n_panel(seed))))
    _write_trajectory_evidence(output, rows)
    for ordinal, row in enumerate(rows, start=1):
        label = row.get("scenario", "positive" if row["positive"] else "denial")
        row["evidence_path"] = f"evidence/trajectories/{ordinal:03d}_seed_{row['world_seed']:06d}_{label}/trajectory.json"
    completed = [row for row in rows if row["status"] == "completed"]
    report = {
        "family_id": "refund_v2",
        "family_version": "2.1.0",
        "topology": "1:N",
        "active_agents": list(active_agents),
        "scripted_agents": [agent for agent in ("intake", "customer", "policy", "payments") if agent not in active_agents],
        "model": model,
        "revision": revision,
        "reasoning_effort": reasoning_effort,
        "seeds": seeds,
        "scenarios": sorted({row["scenario"] for row in rows}),
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
    parser.add_argument("--active-agents", default="policy",
                        help="comma-separated active seats: intake,customer,policy")
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
        active_agents=validate_active_agents(tuple(item.strip() for item in args.active_agents.split(",") if item.strip())),
    ))
    print(json.dumps({key: report[key] for key in ("planned_cases", "completed_cases", "operational_failures", "means", "policy_compliance_rate")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
