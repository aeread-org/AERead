"""Read-only receipt audit and sanitized export of the approved Phase 2 recovery."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from aeread.shared_runner.quality import verify_qc_evidence_files
from aeread.shared_runner.run.campaign import (
    campaign_gate_artifact_type,
    campaign_history_record_from_dict,
)
from aeread.shared_runner.task.evaluation import audit_family_receipt
from aeread_families.procurement_allocation.model_campaign import (
    _validate_publication_root,
    _write_once_json,
    _write_once_text,
)
from aeread_families.procurement_allocation.phase2_admission import (
    digest,
    load_contribution,
    source_pins,
)
from aeread_families.procurement_allocation.phase2_campaign import (
    analyze,
    pilot_gate,
    prior_campaign_accounting,
)
from aeread_families.procurement_allocation.phase2_runner import build_setup
from aeread_families.procurement_allocation.strategy_scaffold import (
    GLM_PARASAIL_CANDIDATE,
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sealed(path, key="artifact_sha256"):
    value = json.loads(path.read_text())
    if value[key] != digest({k: v for k, v in value.items() if k != key}):
        raise ValueError(f"Digest mismatch: {path}")
    return value


def without_seal(value):
    return {k: v for k, v in value.items() if k != "artifact_sha256"}


PROVIDER_FAILURE_EVENTS = {"provider_call_failed", "provider_call_outcome_unknown"}


def public_failure_event(event, payload, *, phase, row_id):
    """Preserve typed unknown outcomes without exporting private error text."""
    if event["event_type"] not in PROVIDER_FAILURE_EVENTS | {
        "retry_backoff_started", "retry_backoff_completed"
    }:
        return None
    safe = {k: v for k, v in payload.items() if k in {
        "failure_condition", "retryable", "status_code", "delay_seconds",
        "attempt_ordinal", "provider_retry_after_seconds",
    }}
    return dict(phase=phase, row_id=row_id, event_type=event["event_type"],
                event_hash=event["event_hash"], **safe)


def public_provider_failures(bills):
    """Verify private error messages, exporting only explicit metadata and hashes."""
    result = []
    for bill in bills:
        details = bill.get("provider_failure")
        if details is None:
            continue
        if hashlib.sha256(details["message"].encode()).hexdigest() != details["message_sha256"]:
            raise ValueError("Private provider failure message digest mismatch")
        result.append({
            "request_sha256": bill["request_sha256"],
            "provider_call_id": bill["provider_call_id"],
            **{key: details[key] for key in (
                "exception_type", "message_sha256", "condition", "status_code", "retryable"
            )},
        })
    return result


def publish(root, target):
    _validate_publication_root(target)
    design = sealed(root / "execution_contract.json", "plan_sha256")
    if design["implementation_pins"] != source_pins():
        raise ValueError("Executed source pins changed")
    status = sealed(root / "execution_status.json")
    prior = prior_campaign_accounting()
    assert design["prior_phase2_campaigns"] == prior
    contribution = load_contribution(root / "admission")
    bills = [
        json.loads(p.read_text())
        for p in sorted((root / "billing").glob("call_*.json"))
    ]
    for p in sorted((root / "billing").glob("pending_*.json")):
        completion = p.with_name(p.name.replace("pending_", "call_"))
        if not completion.exists():
            raise ValueError(
                "Unsealed in-flight billing requires audit before publication"
            )
        assert (
            json.loads(p.read_text())["request_sha256"]
            == json.loads(completion.read_text())["request_sha256"]
        )
    known = sum(b["cost_usd"] for b in bills if b["status"] == "settled")
    reserved = sum(b["reserved_cost_usd"] for b in bills if b["status"] != "settled")
    assert math.isclose(status["known_settled_cost_usd"], known, abs_tol=1e-12)
    assert math.isclose(status["unresolved_reserved_cost_usd"], reserved, abs_tol=1e-12)
    assert math.isclose(status["prior_phase2_reserved_cost_usd"], prior["unresolved_reserved_cost_usd"], abs_tol=1e-12)
    assert math.isclose(status["combined_unresolved_reserved_cost_usd"], prior["unresolved_reserved_cost_usd"] + reserved, abs_tol=1e-12)
    assert math.isclose(
        status["accounted_cost_usd"],
        prior["accounted_cost_usd"] + known + reserved,
        abs_tol=1e-12,
    )
    assert status["accounted_cost_usd"] <= status["hard_ceiling_usd"]
    canaries = [sealed(p) for p in sorted((root / "canaries").glob("*.json"))]
    outputs, rows_by_phase, traces, raw_files = {}, {}, [], {}
    audited = 0
    audited_failures = 0
    failure_events = []
    for phase in ("pilot", "confirmatory"):
        report_path = root / phase / "report.json"
        if not report_path.exists():
            continue
        report = sealed(report_path)
        rows_by_phase[phase] = report["rows"]
        public_rows = []
        for row in report["rows"]:
            label = f"{row['world_id'].rsplit('.', 1)[-1]}_{row['environment_seed']}_{row['arm']}"
            source_path = root / phase / "rows" / f"{label}.json"
            assert row == sealed(source_path)
            raw_files[str(source_path.relative_to(root))] = sha(source_path)
            public = {
                k: v
                for k, v in row.items()
                if k
                not in {
                    "receipt_path",
                    "elapsed_seconds",
                    "artifact_sha256",
                    "failure_telemetry",
                }
            }
            public.update(
                case_id=row["world_id"],
                source_row_artifact_sha256=row["artifact_sha256"],
            )
            if row["status"] in {"completed", "operational_failure"}:
                case_path = root / "cases" / f"{label.rsplit('_', 1)[0]}.json"
                case = json.loads(case_path.read_text())
                setup = build_setup(
                    case,
                    arm=row["arm"],
                    seed=row["inference_seed"],
                    route=GLM_PARASAIL_CANDIDATE.route,
                    contribution=contribution,
                    evidence_root=root / "admission",
                )
                assert setup.plan.plan_sha256 == row["run_plan_sha256"]
                receipt_paths = list(
                    (root / phase / "executions" / label).rglob(
                        "evaluation_receipt.json"
                    )
                )
                assert len(receipt_paths) == 1
                receipt_path = receipt_paths[0]
                if row["status"] == "completed":
                    assert receipt_path == root / row["receipt_path"]
                receipt = audit_family_receipt(setup=setup, receipt_path=receipt_path)
                expected_receipt = row.get(
                    "receipt_sha256", row.get("failure_receipt_sha256")
                )
                assert receipt["receipt_sha256"] == expected_receipt
                if row["status"] == "completed":
                    public["result_sha256"] = receipt["receipt_sha256"]
                    audited += 1
                else:
                    assert receipt["scores"] == []
                    audited_failures += 1
                    public["failure_receipt_verified"] = True
                    public["runner_reported_cost_usd"] = row["failure_telemetry"][
                        "cost_usd"
                    ]
                events_path = receipt_path.parent / "events.jsonl"
                actions, requests, row_failures = [], set(), []
                for line in events_path.read_text().splitlines():
                    event = json.loads(line)
                    payload_path = events_path.parent / event["payload_ref"]
                    assert sha(payload_path) == event["payload_sha256"]
                    if event["event_type"] == "provider_call_started":
                        requests.add(
                            json.loads(payload_path.read_text())["request"][
                                "request_sha256"
                            ]
                        )
                    elif event["event_type"] == "provider_call_succeeded":
                        result = json.loads(payload_path.read_text())["provider_result"]
                        # Canonical buyer action only; never raw provider reasoning.
                        try:
                            actions.append(json.loads(result["output_text"]))
                        except json.JSONDecodeError:
                            actions.append(
                                {"unparsed_action_text": result["output_text"]}
                            )
                    else:
                        payload = json.loads(payload_path.read_text())
                        item = public_failure_event(
                            event, payload, phase=phase, row_id=label
                        )
                        if item is None:
                            continue
                        failure_events.append(item)
                        if event["event_type"] in PROVIDER_FAILURE_EVENTS:
                            row_failures.append(item)
                row_bills = [b for b in bills if b["request_sha256"] in requests]
                expected_calls = row.get(
                    "provider_call_count",
                    row.get("failure_telemetry", {}).get("provider_call_count"),
                )
                assert len(row_bills) == expected_calls
                assert math.isclose(
                    sum(b["cost_usd"] for b in row_bills if b["status"] == "settled"),
                    row["known_cost_usd"],
                    abs_tol=1e-12,
                )
                assert math.isclose(
                    sum(
                        b["reserved_cost_usd"]
                        for b in row_bills
                        if b["status"] != "settled"
                    ),
                    row["unresolved_reserved_cost_usd"],
                    abs_tol=1e-12,
                )
                if row["status"] == "operational_failure" and row_failures:
                    conditions = {e["failure_condition"] for e in row_failures}
                    codes = {e["status_code"] for e in row_failures}
                    if len(conditions) == 1:
                        public["failure_condition"] = conditions.pop()
                    if len(codes) == 1:
                        public["failure_status_code"] = codes.pop()
                    public["failure_attribution_source"] = (
                        "sealed provider failure/outcome-unknown events; original runtime exception type retained"
                    )
                traces.append(
                    dict(
                        phase=phase,
                        row_id=label,
                        canonical_actions=actions,
                        events_file_sha256=sha(events_path),
                        receipt_sha256=receipt["receipt_sha256"],
                    )
                )
            elif row["status"] != "not_attempted":
                raise ValueError("Unknown row status")
            public_rows.append(public)
        outputs[f"reports/{phase}.json"] = dict(
            campaign_id=design["campaign_id"], phase=phase, rows=public_rows
        )
    diagnostics = pilot_gate(rows_by_phase.get("pilot", []), design["world_ids"])
    if "pilot" in rows_by_phase:
        assert diagnostics == json.loads(
            (root / "gate_evidence/full_trajectory.json").read_text()
        )
    if "confirmatory" in rows_by_phase:
        frozen = sealed(root / "confirmatory_plan.json", "plan_sha256")
        assert frozen["execution_contract_sha256"] == design["plan_sha256"]
        assert frozen["pilot_report_sha256"] == digest(rows_by_phase["pilot"])
        comparison = analyze(rows_by_phase["confirmatory"], design["world_ids"])
        assert comparison == without_seal(sealed(root / "comparison.json"))
        outputs["tables/confirmatory_plan.json"] = frozen
        outputs["reports/comparison.json"] = comparison
    else:
        assert not (root / "confirmatory_plan.json").exists()
        comparison = None
    gates = []
    for path in sorted((root / "gates").glob("*.json")):
        record = campaign_history_record_from_dict(json.loads(path.read_text()))
        verify_qc_evidence_files(
            record.evidence_refs,
            root,
            expected_artifact_types=(
                campaign_gate_artifact_type(record.gate_id, record.status),
            ),
        )
        gates.append(dict(gate_id=record.gate_id, status=record.status))
    all_rows = [r for rows in rows_by_phase.values() for r in rows]
    row_known = sum(r.get("known_cost_usd", 0) for r in all_rows)
    canary_known = sum(c["cost_usd"] for c in canaries if c.get("cost_usd") is not None)
    assert math.isclose(known, row_known + canary_known, abs_tol=1e-12)
    summary = dict(
        campaign_id=design["campaign_id"],
        status=status["status"],
        gates=gates,
        phase_counts={
            phase: dict(
                planned=len(rows),
                completed=sum(r["status"] == "completed" for r in rows),
                operational_failures=sum(
                    r["status"] == "operational_failure" for r in rows
                ),
                not_attempted=sum(r["status"] == "not_attempted" for r in rows),
                replayed=sum(r.get("receipt_replayed") is True for r in rows),
                malformed_actions=sum(
                    r.get("failure_code") == "malformed_procurement_action"
                    for r in rows
                ),
                violation_rows=sum(bool(r.get("violations")) for r in rows),
                decisions_by_arm={
                    a: dict(
                        Counter(
                            r.get("decision", r["status"])
                            for r in rows
                            if r["arm"] == a
                        )
                    )
                    for a in ("control", "treatment")
                },
            )
            for phase, rows in rows_by_phase.items()
        },
        independently_audited_receipts=audited,
        independently_audited_score_free_failure_receipts=audited_failures,
        provider_request_count=len(bills),
        unscored_canary_count=len(canaries),
        recovery_settled_cost_usd=known,
        prior_phase2_settled_cost_usd=prior["settled_cost_usd"],
        prior_phase2_reserved_cost_usd=prior["unresolved_reserved_cost_usd"],
        combined_settled_cost_usd=prior["settled_cost_usd"] + known,
        unresolved_reserved_cost_usd=reserved,
        combined_unresolved_reserved_cost_usd=prior["unresolved_reserved_cost_usd"] + reserved,
        combined_accounted_cost_usd=status["accounted_cost_usd"],
        hard_combined_ceiling_usd=status["hard_ceiling_usd"],
        remaining_budget_usd=status["hard_ceiling_usd"] - status["accounted_cost_usd"],
        confirmatory_plan_sha256=outputs.get("tables/confirmatory_plan.json", {}).get(
            "plan_sha256"
        ),
        comparison=comparison,
        pilot_gate=diagnostics,
        confirmation_rows_executed=sum(r["status"] != "not_attempted" for r in rows_by_phase.get("confirmatory", [])),
        confirmation_rows_gated_off=(
            0 if "confirmatory" in rows_by_phase else design["confirmatory_rows"]
        ),
        provider_failure_evidence_limit="Provider exception messages retained privately and bound by digest; availability of an original raw response body depends on the adapter. Unknown charges remain reserved.",
        claim_scope="Fixed curated synthetic panel; all prior attempts excluded from effects but retained in costs. Trap certificates test public impossibility recognition, not hidden-market discovery.",
    )
    outputs["reports/execution_status.json"] = summary
    outputs["qc/canonical_actions.json"] = {"traces": traces}
    outputs["qc/provider_failure_events.json"] = {"events": failure_events}
    outputs["qc/provider_failure_digests.json"] = {"failures": public_provider_failures(bills)}
    diagnostic_path = root / "provider_diagnostic.json"
    if diagnostic_path.exists():
        diagnostic = json.loads(diagnostic_path.read_text())
        outputs["qc/provider_diagnostic.json"] = {
            key: diagnostic[key]
            for key in (
                "observed_at",
                "method",
                "endpoint",
                "http_status",
                "response_sha256",
                "model_inference_requests",
                "limitation",
            )
            if key in diagnostic
        }
        raw_files[str(diagnostic_path.relative_to(root))] = sha(diagnostic_path)
    outputs["qc/human_qc_approval.json"] = json.loads(
        (root / "admission/human_qc_approval.json").read_text()
    )
    outputs["tables/execution_contract.json"] = design
    for relative, value in outputs.items():
        _write_once_json(target / relative, value)
    _write_once_text(
        target / "README.md",
        f"""# Phase 2 provider recovery: verified live evidence

Execution status: `{status['status']}`. See [the reconciled result](reports/execution_status.json).
Independently audited receipts: {audited}. Recovery settled spend: ${known:.10f}.
Separately audited score-free failure receipts: {audited_failures}.
Combined Phase 2 settled spend, including all prior attempts:
${prior['settled_cost_usd'] + known:.10f}. Combined unresolved reservations:
${prior['unresolved_reserved_cost_usd'] + reserved:.10f}.
The combined ceiling remains $0.45. No original failed episode is pooled or replaced.

The confirmation comparison, when present, averages paired seeds within each
world and then weights the eight worlds equally. Its validity guard and support
decision are preserved; completed/replayed does not imply a feasible purchase.
Canonical buyer actions, economic outcomes, typed failures and hashes are public.
Full prompts, observations, provider reasoning, raw payloads and account metadata
remain in ignored local storage. No provider is created by the exporter.

Reproduce against the matching executed source with:
`PYTHONPATH=src python tools/publish_procurement_phase2_recovery.py --run-root {root} --publication-root {target}`.
The raw local run is required for independent receipt audits; the publication
contains the exact source, plan, receipt, event and billing digests.
""",
    )
    manifest = dict(
        schema_version="aeread.publication_manifest/0.1",
        publication_id=target.name,
        campaign_id=design["campaign_id"],
        artifacts={
            str(p.relative_to(target)): sha(p)
            for p in sorted(target.rglob("*"))
            if p.is_file() and p.name != "publication_manifest.json"
        },
        source_bindings=dict(
            execution_contract_sha256=design["plan_sha256"],
            implementation_pins=design["implementation_pins"],
            raw_row_file_sha256=raw_files,
            raw_billing_file_sha256={
                p.name: sha(p) for p in sorted((root / "billing").glob("*.json"))
            },
            exporter_sha256=sha(Path(__file__)),
        ),
        privacy_boundary=dict(
            included="canonical actions, outcomes, typed failures, costs and digests",
            excluded="prompts, observations, provider reasoning, raw payloads and account metadata",
        ),
    )
    _write_once_json(
        target / "publication_manifest.json",
        manifest | {"manifest_sha256": digest(manifest)},
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--publication-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(publish(args.run_root, args.publication_root), indent=2))
