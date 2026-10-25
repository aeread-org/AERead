"""Version-isolated runner adapter for V2.5 seat experiments.

This wrapper leaves the historical V2.5 runner and its pinned behavior alone.
It only converts a typed provider failure wrapped by the generic scheduler into
the shared runner's sealed operational-exclusion receipt path.
"""
from __future__ import annotations

import json
import argparse
import asyncio
import hashlib
import math
import time
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.layout import RunLayout
from aeread.shared_runner.task.evaluation import (
    audit_family_receipt,
    finalize_family_execution,
    finalize_family_failure,
    replay_family_receipt,
)
from aeread.shared_runner.task.execution import ProviderFailure, execute_plan_cell
from aeread.shared_runner.task.scheduler import SchedulerContractError
from aeread.shared_runner.run.resolver import ImplementationPin, canonical_json_bytes

from . import v2_5_runner as base
from . import v2_5_measurement as measurement
from . import v2_5_seat_cases as seat_cases
from .v2_5_policy import FAMILY_VERSION, UnifiedRefundCase
from .v2_5_policy_composition_cases import (
    build_policy_composition_panel,
    policy_composition_case_pin,
)


async def run_seat_panel(
    *,
    output: Path,
    cases: tuple[UnifiedRefundCase, ...],
    active_agents: tuple[str, ...],
    provider: str = "scripted",
    model: str = "refund-v25-scripted",
    revision: str = FAMILY_VERSION,
    repetitions: int = 1,
    env_file: Path | None = None,
    extra_implementation_pins: tuple[ImplementationPin, ...] = (),
    budget_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a supplied fixed panel with one controlled seat and sealed failures."""
    if provider == "arena":
        if budget_state is None:
            raise ValueError("Arena seat panels require an explicit campaign budget state")
        base._load_env_file(env_file)
    wrapper_pins = (
        base._pin("refund_v25_seat_cases", "reference", Path(seat_cases.__file__), "1"),
        base._pin("refund_v25_seat_experiment", "reference", Path(__file__), "2"),
    )
    setup = base.build_refund_v25_run(
        provider=provider,
        model=model,
        revision=revision,
        active_agents=active_agents,
        evaluation_kind="controlled",
        repetitions=repetitions,
        cases=cases,
        extra_implementation_pins=(*wrapper_pins, *extra_implementation_pins),
    )
    providers: dict[str, Any] = {"scripted": base.ScriptedV25Provider()}
    if provider == "arena":
        providers["arena"] = base.ArenaChatClient()

    receipts = []
    operational_failures = 0
    stop_reason = budget_state.get("stop_reason") if budget_state is not None else None
    for cell in setup.plan.cells:
        if stop_reason is not None:
            break
        if budget_state is not None:
            elapsed = time.monotonic() - budget_state["started_monotonic"]
            if elapsed >= budget_state["serial_time_limit_seconds"]:
                stop_reason = budget_state["stop_reason"] = "serial_time_limit_reached"
                break
            if budget_state["known_spend_usd"] >= budget_state["known_spend_stop_usd"]:
                stop_reason = budget_state["stop_reason"] = "known_spend_stop_reached"
                break
        try:
            execution = await execute_plan_cell(
                plan=setup.plan,
                cell_id=cell.cell_id,
                registry=setup.registry,
                evidence_root=output,
                prompt_sources=setup.prompt_sources,
                providers=providers,
                pricing=setup.pricing,
                episode_attempt_ordinal=0,
                harnesses=setup.harnesses,
            )
        except SchedulerContractError as scheduler_error:
            # Generic run_episode wraps callback exceptions. Unwrap only the
            # execution layer's typed ProviderFailure; scheduler/family bugs
            # remain visible as hard errors and are never mislabeled.
            failure = scheduler_error.__cause__
            if not isinstance(failure, ProviderFailure):
                raise
            receipt = finalize_family_failure(
                setup=setup,
                cell_id=cell.cell_id,
                evidence_root=output,
                error=failure,
                leaf_builder=lambda case: measurement.build_measurement_leaves(case)[0],
            )
            receipt_path = (
                RunLayout(output, setup.plan.run_plan_id).attempt_dir(
                    cell.cell_id, receipt.episode_attempt_id
                )
                / "evaluation_receipt.json"
            )
            audit_family_receipt(setup=setup, receipt_path=receipt_path)
            if budget_state is not None:
                budget_state["provider_calls"] += _count_started_model_calls(
                    receipt_path.parent / "events.jsonl", active_seat=active_agents[0]
                )
            operational_failures += 1
            if budget_state is not None and failure.condition in {"timeout", "transport"}:
                budget_state["billing_complete"] = False
                budget_state["unknown_charge_attempts"] += 1
                stop_reason = "provider_outcome_unknown"
            else:
                stop_reason = f"operational_exclusion:{failure.condition}"
        else:
            receipt = finalize_family_execution(setup=setup, execution=execution)
            replay_family_receipt(setup=setup, receipt=receipt, evidence_root=output)
            if budget_state is not None:
                cost, paid_calls, billing_error = _active_model_billing(
                    execution, model=model, active_seat=active_agents[0]
                )
                budget_state["provider_calls"] += paid_calls
                budget_state["known_spend_usd"] += cost
                if billing_error is not None:
                    budget_state["billing_complete"] = False
                    stop_reason = billing_error
                else:
                    if budget_state["known_spend_usd"] >= budget_state["known_spend_stop_usd"]:
                        stop_reason = "known_spend_stop_reached"
                if time.monotonic() - budget_state["started_monotonic"] >= budget_state["serial_time_limit_seconds"]:
                    stop_reason = "serial_time_limit_reached"
                if stop_reason is not None:
                    budget_state["stop_reason"] = stop_reason
        receipts.append(receipt)
        if stop_reason is not None:
            break

    if budget_state is not None and stop_reason is not None:
        budget_state["stop_reason"] = stop_reason

    return {
        "run_plan_id": setup.plan.run_plan_id,
        "active_agents": list(active_agents),
        "planned_cells": len(setup.plan.cells),
        "completed_cells": len(receipts),
        "operational_failures": operational_failures,
        "stop_reason": stop_reason,
        "known_spend_usd": budget_state["known_spend_usd"] if budget_state is not None else 0.0,
        "provider_calls": budget_state["provider_calls"] if budget_state is not None else 0,
        "billing_complete": budget_state["billing_complete"] if budget_state is not None else True,
        "receipts": [json.loads(canonical_json_bytes(receipt)) for receipt in receipts],
    }


def _panel_digest(cases: tuple[UnifiedRefundCase, ...]) -> str:
    rows = []
    for case in cases:
        rows.append({
            "case_id": case.case_id,
            "case": json.loads(canonical_json_bytes(case)),
            "contract": base.render_policy_contract(case),
        })
    return hashlib.sha256(canonical_json_bytes(rows)).hexdigest()


def _profile_digests(setup: Any) -> dict[str, str]:
    return {
        profile.profile_id: hashlib.sha256(canonical_json_bytes(profile)).hexdigest()
        for profile in setup.plan.agent_profiles
    }


def _campaign_cases(seat: str, seed: int) -> tuple[UnifiedRefundCase, ...]:
    builders = {
        "payments": seat_cases.build_payment_smoke_cases,
        "intake": seat_cases.build_intake_challenge_cases,
        "customer": seat_cases.build_customer_integrity_cases,
    }
    try:
        return builders[seat](seed)
    except KeyError as error:
        raise ValueError(f"unsupported smoke seat: {seat}") from error


def _validate_smoke_manifest(manifest: dict[str, Any]) -> dict[str, tuple[UnifiedRefundCase, ...]]:
    if manifest.get("schema_version") != "refund_v25_seat_smoke/2":
        raise ValueError("unsupported seat-smoke manifest schema")
    if manifest.get("status") != "authorized_for_single_seed_smoke" or manifest.get("paid_execution_authorized") is not True:
        raise ValueError("seat-smoke manifest lacks paid-execution authorization")
    if manifest.get("provider") != "arena" or manifest.get("model") != "gemini-2.5-flash-lite":
        raise ValueError("seat-smoke manifest model/provider differs from the frozen campaign")
    if manifest.get("active_seat_order") != ["payments", "intake", "customer"]:
        raise ValueError("seat-smoke stage order differs from the approved sequence")
    budget = manifest.get("budget_proposal", {})
    if (budget.get("known_spend_stop_usd") != 1.0
            or budget.get("unknown_charge_reserve_usd") != 1.0
            or budget.get("serial_time_limit_minutes") != 60.0):
        raise ValueError("seat-smoke budget differs from the user-approved limits")

    paths = {
        "refund_v25_seat_cases.py": Path(seat_cases.__file__),
        "refund_v25_seat_experiment.py": Path(__file__),
        "refund_v25_runner.py": Path(base.__file__),
        "refund_v25_policy.py": Path(base.__file__).with_name("v2_5_policy.py"),
        "refund_v25_measurement.py": Path(measurement.__file__),
        "shared_runner_execution.py": Path(base.execution_module.__file__),
    }
    for name, path in paths.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest.get("implementation_sha256", {}).get(name):
            raise ValueError(f"seat-smoke implementation pin mismatch: {name}")

    result: dict[str, tuple[UnifiedRefundCase, ...]] = {}
    for seat in manifest["active_seat_order"]:
        entry = manifest["panels"][seat]
        cases = _campaign_cases(seat, entry["world_seed"])
        if len(cases) != entry["case_count"] or _panel_digest(cases) != entry["case_panel_sha256"]:
            raise ValueError(f"{seat} case panel does not match the frozen manifest")
        setup = base.build_refund_v25_run(
            provider=manifest["provider"], model=manifest["model"],
            revision=manifest["revision"], active_agents=(seat,),
            evaluation_kind="controlled", repetitions=manifest["repetitions_per_case"],
            cases=cases,
        )
        profiles = _profile_digests(setup)
        if profiles.get(entry["active_profile_id"]) != entry["active_profile_sha256"]:
            raise ValueError(f"{seat} active profile does not match the frozen manifest")
        scripted = {
            role: profiles.get(next(
                profile_id for profile_id in profiles
                if profile_id.startswith(f"refund_v25_{role}_scripted_")
            ))
            for role in entry["scripted_profile_sha256_by_seat"]
        }
        if scripted != entry["scripted_profile_sha256_by_seat"]:
            raise ValueError(f"{seat} scripted profiles do not match the frozen manifest")
        result[seat] = cases
    if sum(len(cases) for cases in result.values()) != manifest.get("planned_episodes"):
        raise ValueError("seat-smoke planned episode count does not reconcile")
    return result


async def run_lite_smoke_campaign(
    *, manifest_path: Path, output: Path, env_file: Path
) -> dict[str, Any]:
    """Execute the approved sequential three-seat Lite smoke under one shared budget."""
    manifest = json.loads(manifest_path.read_bytes())
    panels = _validate_smoke_manifest(manifest)
    if output.exists():
        raise FileExistsError(f"refusing to reuse an existing smoke artifact root: {output}")
    output.mkdir(parents=True)
    (output / "execution_contract.json").write_bytes(canonical_json_bytes(manifest) + b"\n")
    started_at = time.time()
    started_monotonic = time.monotonic()
    (output / "started.json").write_bytes(canonical_json_bytes({
        "campaign_id": manifest["experiment_id"],
        "started_at_unix": started_at,
        "manifest_sha256": hashlib.sha256(canonical_json_bytes(manifest)).hexdigest(),
        "planned_episodes": manifest["planned_episodes"],
    }) + b"\n")
    budget = manifest["budget_proposal"]
    state: dict[str, Any] = {
        "known_spend_stop_usd": budget["known_spend_stop_usd"],
        "unknown_charge_reserve_usd": budget["unknown_charge_reserve_usd"],
        "serial_time_limit_seconds": budget["serial_time_limit_minutes"] * 60.0,
        "started_monotonic": started_monotonic,
        "known_spend_usd": 0.0,
        "provider_calls": 0,
        "unknown_charge_attempts": 0,
        "billing_complete": True,
        "stop_reason": None,
    }
    stages: list[dict[str, Any]] = []
    try:
        base._load_env_file(env_file)
        for seat in manifest["active_seat_order"]:
            if state["stop_reason"] is not None:
                break
            report = await run_seat_panel(
                output=output / seat,
                cases=panels[seat],
                active_agents=(seat,),
                provider=manifest["provider"],
                model=manifest["model"],
                revision=manifest["revision"],
                repetitions=manifest["repetitions_per_case"],
                env_file=env_file,
                budget_state=state,
            )
            compact = {key: report[key] for key in (
                "run_plan_id", "active_agents", "planned_cells", "completed_cells",
                "operational_failures", "stop_reason", "known_spend_usd",
                "provider_calls", "billing_complete",
            )}
            stages.append({"seat": seat, **compact})
            (output / f"{seat}_summary.json").write_bytes(canonical_json_bytes({
                **compact,
                "receipt_sha256_by_case": {
                    receipt["case_id"]: receipt["receipt_sha256"]
                    for receipt in report["receipts"]
                },
            }) + b"\n")
            if report["completed_cells"] != report["planned_cells"] or report["operational_failures"]:
                state["stop_reason"] = state["stop_reason"] or "stage_incomplete_or_operational_exclusion"
                break
        elapsed = time.monotonic() - started_monotonic
        complete = (
            len(stages) == 3
            and all(stage["completed_cells"] == stage["planned_cells"] for stage in stages)
            and all(stage["operational_failures"] == 0 for stage in stages)
            and state["billing_complete"]
        )
        summary = {
            "campaign_id": manifest["experiment_id"],
            "status": "complete" if complete else "stopped_incomplete",
            "analysis_status": "descriptive_seat_smoke_only",
            "planned_episodes": manifest["planned_episodes"],
            "completed_receipts": sum(stage["completed_cells"] for stage in stages),
            "stages": stages,
            "new_known_spend_usd": state["known_spend_usd"],
            "new_provider_calls": state["provider_calls"],
            "new_billing_complete": state["billing_complete"],
            "unknown_charge_attempts": state["unknown_charge_attempts"],
            "unknown_charge_reserve_usd": state["unknown_charge_reserve_usd"],
            "serial_elapsed_minutes": elapsed / 60.0,
            "stop_reason": state["stop_reason"],
            "historical_unresolved_payment_attempt": True,
        }
        (output / "summary.json").write_bytes(canonical_json_bytes(summary) + b"\n")
        return summary
    except Exception as error:
        failure = {
            "campaign_id": manifest["experiment_id"],
            "failure_type": type(error).__name__,
            "stop_reason": "runner_or_preflight_error",
            "known_spend_usd": state["known_spend_usd"],
            "billing_complete": state["billing_complete"],
            "stages": stages,
        }
        (output / "failure.json").write_bytes(canonical_json_bytes(failure) + b"\n")
        raise


def _active_model_billing(execution: Any, *, model: str, active_seat: str) -> tuple[float, int, str | None]:
    """Use only explicit provider-reported model cost; zero-price fallbacks are not billing evidence."""
    total = 0.0
    calls = 0
    for event in execution.evidence.read_events():
        if event.visibility != f"seat:{active_seat}":
            continue
        if event.event_type == "provider_call_outcome_unknown":
            return total, calls, "provider_outcome_unknown"
        if event.event_type != "provider_call_succeeded":
            continue
        payload = execution.evidence.read_event_payload(event)
        result = payload.get("provider_result") if isinstance(payload, dict) else None
        if not isinstance(result, dict) or result.get("requested_model") != model:
            continue
        calls += 1
        cost = result.get("cost_usd")
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
            return total, calls, "provider_usage_cost_missing"
        total += float(cost)
        if result.get("resolved_model") != model:
            return total, calls, "resolved_route_mismatch"
    return total, calls, None


def _count_started_model_calls(events_path: Path, *, active_seat: str) -> int:
    if not events_path.exists():
        return 0
    count = 0
    for line in events_path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if (event.get("event_type") == "provider_call_started"
                and event.get("visibility") == f"seat:{active_seat}"):
            count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="V2.5 controlled-seat conformance and smoke runner")
    parser.add_argument("--config", type=Path, help="frozen paid seat-smoke manifest")
    parser.add_argument("--active-agent", choices=base.ROLES, help="active seat for provider-free composition conformance")
    parser.add_argument("--world-seed", type=int, default=501)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path("env.local"))
    args = parser.parse_args(argv)
    if args.config is not None:
        summary = asyncio.run(run_lite_smoke_campaign(
            manifest_path=args.config, output=args.output, env_file=args.env_file
        ))
        print(json.dumps({key: summary[key] for key in (
            "campaign_id", "status", "completed_receipts", "new_provider_calls",
            "new_known_spend_usd", "new_billing_complete", "serial_elapsed_minutes", "stop_reason",
        )}, sort_keys=True))
        return 0 if summary["status"] == "complete" else 2
    if args.active_agent is None:
        parser.error("--active-agent is required for provider-free conformance")
    cases = build_policy_composition_panel(args.world_seed)
    report = asyncio.run(
        run_seat_panel(
            output=args.output,
            cases=cases,
            active_agents=(args.active_agent,),
            extra_implementation_pins=(policy_composition_case_pin(),),
        )
    )
    print(json.dumps({key: report[key] for key in (
        "active_agents", "planned_cells", "completed_cells", "operational_failures"
    )}))
    return 0


__all__ = ["main", "run_lite_smoke_campaign", "run_seat_panel"]


if __name__ == "__main__":
    raise SystemExit(main())
