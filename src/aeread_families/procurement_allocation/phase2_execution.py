"""Execute one reviewed Phase 2 campaign; no automatic resume or outcome retries."""

from __future__ import annotations
import argparse
import asyncio
import json
import tempfile
import time
from collections import Counter
from pathlib import Path
from aeread.shared_runner.quality import QCCoverage, QCEvidenceRef
from aeread.shared_runner.run.campaign import (
    CampaignGateRecord,
    append_campaign_gate,
    campaign_gate_artifact_type,
    campaign_history_record_from_dict,
    campaign_promotion_decision,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import (
    OpenRouterChatClient,
    execute_plan_cell,
    ProviderFailure,
)
from aeread.shared_runner.task.evaluation import (
    finalize_family_execution,
    finalize_family_failure,
    replay_family_receipt,
    audit_family_receipt,
)
from .model_campaign import (
    _write_once_json,
    _validate_operational_run_root,
    _public_action_trace,
    _sealed_failure_telemetry,
)
from .runner import SequenceResponseProvider
from .phase2_environment import Phase2Plugin, measurement_leaf, FAMILY_ID
from .phase2_admission import load_contribution, digest, source_pins, evidence_ref
from .phase2_runner import build_setup, PROMPTS
from .phase2_policies import behavior_diagnostics
from .phase2_worlds import (
    build_world,
    episode_case,
    CATEGORIES,
    PILOT_SEEDS,
    CONFIRMATORY_SEEDS,
)
from .phase2_campaign import (
    CAMPAIGN_ID,
    HARD_COST_CEILING_USD,
    BASELINE_SETTLED_USD,
    BASELINE_RESERVED_USD,
    execution_contract,
    pilot_gate,
    analyze,
)
from .phase2_budget import Phase2BudgetedProvider
from .strategy_scaffold import GLM_PARASAIL_CANDIDATE
from aeread_families.procurement_grounding.bakeoff import preflight_candidate


def seal(value):
    return {**value, "artifact_sha256": digest(value)}


def gate(root, name, artifact, passed):
    history = [
        campaign_history_record_from_dict(json.loads(p.read_text()))
        for p in sorted((root / "gates").glob("*.json"))
    ]
    decision = campaign_promotion_decision(
        CAMPAIGN_ID, name, history, evidence_root=root
    )
    if not decision.eligible:
        raise ValueError(f"{name} blocked: {decision.blockers}")
    status = "passed" if passed else "failed"
    path = f"gate_evidence/{name}.json"
    _write_once_json(root / path, artifact)
    ref = QCEvidenceRef.from_dict(
        evidence_ref(
            root,
            path,
            campaign_gate_artifact_type(name, status),
            name,
            ("declared_contract",),
        )
    )
    if not passed:
        from dataclasses import replace

        ref = replace(ref, coverage=(QCCoverage(name, ("declared_contract",), ()),))
    record = CampaignGateRecord(
        CAMPAIGN_ID,
        FAMILY_ID,
        "1.0.0",
        FAMILY_ID,
        name,
        decision.next_attempt_index,
        status,
        (ref,),
        () if passed else ("declared gate failed; inspect artifact",),
    )
    append_campaign_gate(history, record, evidence_root=root)
    _write_once_json(
        root / "gates" / f"{len(history):02d}_{name}.json",
        {"record_type": "gate", **json.loads(canonical_json_bytes(record))},
    )


async def canary(root, case, arm, provider, contribution, admission_root):
    setup = build_setup(
        episode_case(case, 54001),
        arm=arm,
        route=GLM_PARASAIL_CANDIDATE.route,
        seed=54001,
        contribution=contribution,
        evidence_root=admission_root,
    )
    fake = SequenceResponseProvider(
        [json.dumps({"action": "defer", "reason": "unscored request capture"})]
    )
    with tempfile.TemporaryDirectory(prefix="phase2-canary-") as temporary:
        await execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=temporary,
            prompt_sources=setup.prompt_sources,
            providers={"openrouter": fake},
            pricing=setup.pricing,
            harnesses=setup.harnesses,
        )
    request = fake.requests[0]
    result = {
        "status": "rejected",
        "arm": arm,
        "scored": False,
        "request_sha256": request.request_sha256,
    }
    try:
        for attempt in range(2):
            try:
                response = await provider.complete(request)
                break
            except ProviderFailure as error:
                if attempt or not error.retryable or error.status_code != 429:
                    raise
                await asyncio.sleep(error.retry_after_seconds)
        plugin = Phase2Plugin()
        payload = setup.case.payload
        phase = plugin.phases(payload)[0]
        state = plugin.initial_state(payload, None)
        parsed = plugin.parse_action(
            payload, state, "buyer", phase, response.output_text
        )
        valid = (
            parsed.ok
            and plugin.legal(payload, state, "buyer", phase, parsed.action).legal
        )
        result.update(
            status="admitted" if valid else "rejected",
            raw_output=response.output_text,
            resolved_model=response.resolved_model,
            cost_usd=response.cost_usd,
        )
    except Exception as error:
        result.update(failure_type=type(error).__name__, cost_usd=None)
    if result["status"] != "admitted":
        provider.stopped = True
    _write_once_json(root / "canaries" / f"{arm}.json", seal(result))
    return result


async def run_row(
    root, phase, case, category, seed, arm, provider, contribution, admission_root
):
    setup = build_setup(
        episode_case(case, seed),
        arm=arm,
        route=GLM_PARASAIL_CANDIDATE.route,
        seed=seed,
        contribution=contribution,
        evidence_root=admission_root,
    )
    label = f"{case['case_id'].rsplit('.',1)[-1]}_{seed}_{arm}"
    path = root / phase / "rows" / f"{label}.json"
    evidence_root = root / phase / "executions" / label
    row = dict(
        world_id=case["case_id"],
        category=category,
        environment_seed=seed,
        inference_seed=seed,
        arm=arm,
        case_content_sha256=setup.case.content_sha256,
        run_plan_sha256=setup.plan.plan_sha256,
        status="not_attempted",
        receipt_replayed=False,
        cost_usd=None,
    )
    if provider.stopped:
        row["failure_condition"] = "campaign_dispatch_stopped"
    else:
        started = time.perf_counter()
        billing_start = len(provider.calls)
        try:
            execution = await execute_plan_cell(
                plan=setup.plan,
                cell_id=setup.plan.cells[0].cell_id,
                registry=setup.registry,
                evidence_root=evidence_root,
                prompt_sources=setup.prompt_sources,
                providers={"openrouter": provider},
                pricing=setup.pricing,
                harnesses=setup.harnesses,
            )
            receipt = finalize_family_execution(setup=setup, execution=execution)
            replay = replay_family_receipt(
                setup=setup, receipt=receipt, evidence_root=evidence_root
            )
            if canonical_json_bytes(receipt) != canonical_json_bytes(replay):
                raise ValueError("receipt replay mismatch")
            execution.evidence.audit_reconciliation()
            paths = list(evidence_root.rglob("evaluation_receipt.json"))
            if len(paths) != 1:
                raise ValueError("expected one sealed evaluation receipt")
            audit = audit_family_receipt(setup=setup, receipt_path=paths[0])
            if audit["receipt_sha256"] != receipt.receipt_sha256:
                raise ValueError("independent audit returned another receipt")
            outcome = json.loads(canonical_json_bytes(execution.episode_result.outcome))
            calls = [
                c
                for a in execution.action_executions
                for t in a.attempts
                for c in t.provider_calls
            ]
            retries = Counter(
                str(t.retry_reason)
                for a in execution.action_executions
                for t in a.attempts
                if t.retry_reason
            )
            trace = _public_action_trace(execution)
            actions = []
            for logical_action in execution.action_executions:
                response = next(
                    (
                        a.canonical_response
                        for a in reversed(logical_action.attempts)
                        if a.canonical_response is not None
                    ),
                    None,
                )
                if response is None:
                    break
                actions.append(
                    response.action if response.action is not None else response.text
                )
            diagnostics = behavior_diagnostics(setup.case.payload, actions)
            row.update(
                outcome,
                status="completed",
                receipt_replayed=True,
                receipt_sha256=receipt.receipt_sha256,
                receipt_path=str(paths[0].relative_to(root)),
                cost_usd=execution.total_cost_usd,
                cost_accounting="exact",
                provider_call_count=len(calls),
                runner_retry_count=sum(retries.values()),
                retry_conditions=dict(retries),
                input_tokens=sum(c.input_tokens for c in calls),
                output_tokens=sum(c.output_tokens for c in calls),
                elapsed_seconds=time.perf_counter() - started,
                action_trace=trace,
                behavior_diagnostics=diagnostics,
                quoted_suppliers=[
                    a["supplier_id"] for a in trace if a["action"] == "request_quote"
                ],
                sampled_suppliers=[
                    a["supplier_id"] for a in trace if a["action"] == "request_sample"
                ],
                award_supplier_count=sum(
                    len(a.get("award_lines", []))
                    for a in trace
                    if a["action"] == "submit_award"
                ),
            )
        except Exception as error:
            provider.stopped = True
            row.update(
                status="operational_failure",
                failure_type=type(error).__name__,
                elapsed_seconds=time.perf_counter() - started,
            )
            # Preserve typed failure and all attempts. Do not repeat an interrupted
            # action, and do not mark a failed receipt as a replayed observation.
            try:
                receipt = finalize_family_failure(
                    setup=setup,
                    cell_id=setup.plan.cells[0].cell_id,
                    evidence_root=evidence_root,
                    error=error,
                    leaf_builder=measurement_leaf,
                )
                row["failure_receipt_sha256"] = receipt.receipt_sha256
                row["failure_telemetry"] = _sealed_failure_telemetry(evidence_root)
            except Exception as sealing_error:
                row["failure_sealing_error"] = type(sealing_error).__name__
    if row["status"] != "not_attempted":
        bills = [json.loads(p.read_text()) for p in provider.calls[billing_start:]]
        known = sum(b["cost_usd"] for b in bills if b["status"] == "settled")
        reserved = sum(
            b["reserved_cost_usd"] for b in bills if b["status"] != "settled"
        )
        row.update(
            cost_usd=known if not reserved else None,
            known_cost_usd=known,
            unresolved_reserved_cost_usd=reserved,
            accounted_cost_usd=known + reserved,
            cost_accounting=(
                "exact" if not reserved else "known_plus_unresolved_reservations"
            ),
        )
    result = seal(row)
    _write_once_json(path, result)
    print(
        json.dumps(
            {
                k: row.get(k)
                for k in (
                    "world_id",
                    "arm",
                    "environment_seed",
                    "status",
                    "decision",
                    "regret_to_upper_bound_usd",
                    "cost_usd",
                )
            }
        ),
        flush=True,
    )
    return result


async def run_panel(root, phase, cases, seeds, provider, contribution, admission_root):
    rows = []
    for i, case in enumerate(cases):
        for seed in seeds:
            _write_once_json(
                root / "cases" / f"world_{i+1:02d}_{seed}.json",
                episode_case(case, seed),
            )
            arms = list(PROMPTS) if (i + seed) % 2 else list(reversed(PROMPTS))
            for arm in arms:
                rows.append(
                    await run_row(
                        root,
                        phase,
                        case,
                        CATEGORIES[i],
                        seed,
                        arm,
                        provider,
                        contribution,
                        admission_root,
                    )
                )
    _write_once_json(root / phase / "report.json", seal({"rows": rows}))
    return rows


async def run_campaign(
    root,
    admission_root,
    *,
    provider_factory=OpenRouterChatClient,
    preflight=preflight_candidate,
):
    root, admission_root = Path(root), Path(admission_root)
    _validate_operational_run_root(root)
    contribution = load_contribution(admission_root)
    screen = json.loads((admission_root / "offline_screen.json").read_text())
    cases = [build_world(i) for i in range(8)]
    design = execution_contract(cases, screen)
    if (root / "execution_contract.json").exists():
        raise RuntimeError("campaign already initialized; audit before any resume")
    _write_once_json(root / "execution_contract.json", design)
    gate(root, "design_contract", design, True)
    gate(
        root,
        "provider_free_validation",
        json.loads((admission_root / "provider_free_conformance.json").read_text()),
        True,
    )
    provider = Phase2BudgetedProvider(
        provider_factory(), root, baseline=BASELINE_SETTLED_USD + BASELINE_RESERVED_USD
    )

    def finish(status, **extra):
        bills = [json.loads(p.read_text()) for p in provider.calls if p.exists()]
        known = sum(b["cost_usd"] for b in bills if b["status"] == "settled")
        reserved = sum(
            b["reserved_cost_usd"] for b in bills if b["status"] != "settled"
        )
        value = seal(
            dict(
                status=status,
                known_settled_cost_usd=known,
                prior_phase2_settled_cost_usd=BASELINE_SETTLED_USD,
                prior_phase2_reserved_cost_usd=BASELINE_RESERVED_USD,
                combined_known_settled_cost_usd=BASELINE_SETTLED_USD + known,
                unresolved_reserved_cost_usd=reserved,
                combined_unresolved_reserved_cost_usd=BASELINE_RESERVED_USD + reserved,
                accounted_cost_usd=provider.spent,
                hard_ceiling_usd=HARD_COST_CEILING_USD,
                provider_request_count=len(provider.calls),
                **extra,
            )
        )
        _write_once_json(root / "execution_status.json", value)
        return value

    try:
        route = preflight(GLM_PARASAIL_CANDIDATE)
    except Exception as error:
        return finish(
            "route_metadata_preflight_failed", failure_type=type(error).__name__
        )
    canaries = []
    for arm in PROMPTS:
        if not provider.stopped:
            canaries.append(
                await canary(
                    root, cases[0], arm, provider, contribution, admission_root
                )
            )
    admitted = len(canaries) == 2 and all(c["status"] == "admitted" for c in canaries)
    gate(root, "profile_admission", dict(route=route, canaries=canaries), admitted)
    if not admitted:
        return finish("profile_admission_failed")
    before = provider.spent
    pilot = await run_panel(
        root, "pilot", cases, PILOT_SEEDS, provider, contribution, admission_root
    )
    diagnostics = pilot_gate(pilot, design["world_ids"])
    gate(root, "full_trajectory", diagnostics, diagnostics["operationally_complete"])
    if not diagnostics["operationally_complete"]:
        return finish("pilot_operational_gate_failed")
    gate(
        root,
        "variance_pilot",
        dict(
            diagnostics=diagnostics,
            variance_scope="offline reference noise and across-world pilot only; within-world model variance unidentified",
        ),
        diagnostics["passed"],
    )
    if not diagnostics["passed"]:
        return finish("pilot_behavior_gate_failed")
    projected = (provider.spent - before) * 3
    if provider.spent + projected > HARD_COST_CEILING_USD:
        return finish(
            "projected_budget_gate_failed", projected_confirmatory_cost_usd=projected
        )
    if design["implementation_pins"] != source_pins():
        raise ValueError("source changed after pilot; no confirmation dispatched")
    frozen = dict(
        campaign_id=CAMPAIGN_ID,
        execution_contract_sha256=design["plan_sha256"],
        pilot_report_sha256=digest(pilot),
        seeds=list(CONFIRMATORY_SEEDS),
        planned_rows=48,
        projected_cost_usd=projected,
        hard_total_cost_ceiling_usd=HARD_COST_CEILING_USD,
    )
    frozen = {**frozen, "plan_sha256": digest(frozen)}
    _write_once_json(root / "confirmatory_plan.json", frozen)
    gate(root, "confirmatory_freeze", frozen, True)
    rows = await run_panel(
        root,
        "confirmatory",
        cases,
        CONFIRMATORY_SEEDS,
        provider,
        contribution,
        admission_root,
    )
    comparison = analyze(rows, design["world_ids"])
    _write_once_json(root / "comparison.json", seal(comparison))
    gate(root, "confirmatory_execution", comparison, comparison["fully_replayed"])
    return finish(
        "completed" if comparison["fully_replayed"] else "confirmation_incomplete",
        comparison=comparison,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--admission-root", type=Path, required=True)
    args = parser.parse_args(argv)
    print(
        json.dumps(
            asyncio.run(run_campaign(args.run_root, args.admission_root)), indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
