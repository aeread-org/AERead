"""Audit and publish the stopped Phase 2 v1 pilot without provider calls.

Run from its frozen implementation revision. Only canonical buyer actions,
economic outcomes, aggregate billing and provenance digests leave raw storage.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from jsonschema import validate

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
    action_schema,
    digest,
    load_contribution,
    source_pins,
)
from aeread_families.procurement_allocation.phase2_campaign import pilot_gate
from aeread_families.procurement_allocation.phase2_environment import Phase2Plugin
from aeread_families.procurement_allocation.phase2_runner import build_setup
from aeread_families.procurement_allocation.strategy_scaffold import (
    GLM_PARASAIL_CANDIDATE,
)


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_sealed(path, key="artifact_sha256"):
    value = json.loads(path.read_text())
    assert value[key] == digest({k: v for k, v in value.items() if k != key}), path
    return value


def publish(root, target):
    _validate_publication_root(target)
    design = read_sealed(root / "execution_contract.json", "plan_sha256")
    assert design["implementation_pins"] == source_pins()
    status = read_sealed(root / "execution_status.json")
    assert status["status"] == "pilot_operational_gate_failed"
    assert not (root / "confirmatory_plan.json").exists()
    assert not (root / "confirmatory").exists()
    contribution = load_contribution(root / "admission")
    report = read_sealed(root / "pilot/report.json")
    assert len(report["rows"]) == 16
    public_rows, traces, failures, sources = [], [], [], {}
    for row in report["rows"]:
        label = f"{row['world_id'].rsplit('.', 1)[-1]}_{row['environment_seed']}_{row['arm']}"
        row_path = root / "pilot/rows" / f"{label}.json"
        assert row == read_sealed(row_path)
        sources[str(row_path.relative_to(root))] = file_digest(row_path)
        case = json.loads(
            (root / "cases" / f"{label.rsplit('_', 1)[0]}.json").read_text()
        )
        setup = build_setup(
            case,
            arm=row["arm"],
            seed=row["inference_seed"],
            route=GLM_PARASAIL_CANDIDATE.route,
            contribution=contribution,
            evidence_root=root / "admission",
        )
        receipt_path = root / row["receipt_path"]
        receipt = audit_family_receipt(setup=setup, receipt_path=receipt_path)
        assert receipt["receipt_sha256"] == row["receipt_sha256"]
        actions = []
        events = receipt_path.parent / "events.jsonl"
        last_action = None
        for line in events.read_text().splitlines():
            event = json.loads(line)
            payload_path = events.parent / event["payload_ref"]
            assert file_digest(payload_path) == event["payload_sha256"]
            if event["event_type"] == "provider_call_succeeded":
                payload = json.loads(payload_path.read_text())
                last_action = json.loads(payload["provider_result"]["output_text"])
                actions.append(last_action)
            elif event["event_type"] == "action_parsed":
                parsed = json.loads(payload_path.read_text())["parse_result"]
                if not parsed["ok"]:
                    validate(last_action, action_schema())
                    culprit = {
                        "request_quote": "message",
                        "request_sample": "message",
                        "counter_offer": "proposal",
                        "inquire": "fields",
                    }[last_action["action"]]
                    assert last_action[culprit] is None
                    plugin = Phase2Plugin()
                    state = plugin.initial_state(case["payload"], None)
                    phase = plugin.phases(case["payload"])[0]
                    assert not plugin.parse_action(
                        case["payload"], state, "buyer", phase, last_action
                    ).ok
                    failures.append(
                        dict(
                            row_id=label,
                            action_ordinal=len(actions),
                            action=last_action["action"],
                            null_required_field=culprit,
                            provider_schema_valid=True,
                            parser_error=parsed["error_code"],
                            source_event_hash=event["event_hash"],
                        )
                    )
        assert len(actions) == row["provider_call_count"]
        traces.append(
            dict(
                row_id=label,
                canonical_actions=actions,
                events_file_sha256=file_digest(events),
                receipt_sha256=row["receipt_sha256"],
            )
        )
        public_rows.append(
            {
                k: v
                for k, v in row.items()
                if k not in {"receipt_path", "elapsed_seconds", "artifact_sha256"}
            }
            | {
                "case_id": row["world_id"],
                "result_sha256": row["receipt_sha256"],
                "source_row_artifact_sha256": row["artifact_sha256"],
            }
        )
    gate = pilot_gate(report["rows"], design["world_ids"])
    assert gate == json.loads((root / "gate_evidence/full_trajectory.json").read_text())
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
    bills = [
        json.loads(p.read_text())
        for p in sorted((root / "billing").glob("call_*.json"))
    ]
    assert len(bills) == 27 and all(b["status"] == "settled" for b in bills)
    for p in sorted((root / "billing").glob("pending_*.json")):
        settled = json.loads(
            p.with_name(p.name.replace("pending_", "call_")).read_text()
        )
        assert settled["request_sha256"] == json.loads(p.read_text())["request_sha256"]
    canaries = [read_sealed(p) for p in sorted((root / "canaries").glob("*.json"))]
    assert len(canaries) == 2 and all(c["status"] == "admitted" for c in canaries)
    settled = sum(b["cost_usd"] for b in bills)
    assert abs(settled - status["known_settled_cost_usd"]) < 1e-12
    assert (
        abs(
            settled
            - sum(r["cost_usd"] for r in public_rows)
            - sum(c["cost_usd"] for c in canaries)
        )
        < 1e-12
    )
    assert status["unresolved_reserved_cost_usd"] == 0
    summary = dict(
        campaign_id=design["campaign_id"],
        status=status["status"],
        pilot_rows=16,
        replayed_receipts=16,
        invalid_action_rows=len(failures),
        failure_fields=dict(Counter(f["null_required_field"] for f in failures)),
        decisions_by_arm={
            a: dict(Counter(r["decision"] for r in public_rows if r["arm"] == a))
            for a in ("control", "treatment")
        },
        trap_deferrals=sum(
            r["decision"] == "defer"
            for r in public_rows
            if r["category"].startswith("trap_")
        ),
        trap_rows=4,
        profitable_nontrap_awards=sum(
            r["feasible_award"] and r["contribution_margin_usd"] > 0
            for r in public_rows
        ),
        provider_request_count=len(bills),
        pilot_provider_requests=sum(r["provider_call_count"] for r in public_rows),
        unscored_canary_requests=2,
        settled_cost_usd=settled,
        unresolved_reserved_cost_usd=0,
        hard_combined_ceiling_usd=0.45,
        remaining_budget_usd=0.45 - settled,
        confirmatory_rows_executed=0,
        confirmatory_rows_gated_off=48,
        confirmatory_plan_sha256=None,
        pilot_gate=gate,
        gates=gates,
        effect_claim="none; operational pilot failed before confirmatory freeze",
        limitation="Trap floors establish public impossibility; these deferrals do not demonstrate hidden-market discovery.",
    )
    outputs = {
        "reports/pilot.json": {
            "campaign_id": design["campaign_id"],
            "phase": "pilot",
            "rows": public_rows,
        },
        "reports/execution_status.json": summary,
        "qc/action_format_diagnosis.json": {
            "failures": failures,
            "canonical_action_traces": traces,
        },
        "qc/human_qc_approval.json": json.loads(
            (root / "admission/human_qc_approval.json").read_text()
        ),
    }
    for path, value in outputs.items():
        _write_once_json(target / path, value)
    _write_once_text(
        target / "README.md",
        """# Phase 2 v1: stopped operational pilot

Live model evidence: 16 pilot episodes, 16 independently re-audited receipts,
11 malformed-action failures, one profitable control award, four trap deferrals.
The operational gate failed. All 48 confirmatory episodes remain unexecuted;
there is no confirmatory plan digest and no treatment-effect claim.

Total settled API spend, including two unscored canaries: $0.0099593505 from
27 requests. No unresolved billing reservations or performance retries.

All 11 failed outputs satisfy the provider's nullable superset JSON schema
but omit an action-specific required value: message (9), proposal (1), fields (1).
The common prompt did not enumerate these requirements. This is an observed
interface failure; it does not identify economic reasoning quality.

The exact canonical actions are in qc/action_format_diagnosis.json. Provider
reasoning, prompts, observations, raw payloads and account metadata are excluded.
Receipt/event/file hashes bind this view to the ignored local raw records.

Reproduce the raw audit at source revision
1bae6714ff8b31fea8d28d5e9207e99c302cc4ff with tools/publish_procurement_phase2_pilot.py
from this publication commit. No provider is instantiated by the exporter.
The original offline admission bundle and stopped attempt remain immutable.
Any action-format repair uses a separate campaign identity and review.
""",
    )
    artifacts = {
        str(p.relative_to(target)): file_digest(p)
        for p in sorted(target.rglob("*"))
        if p.is_file() and p.name != "publication_manifest.json"
    }
    manifest = dict(
        schema_version="aeread.publication_manifest/0.1",
        publication_id=target.name,
        campaign_id=design["campaign_id"],
        artifacts=artifacts,
        source_bindings=dict(
            execution_contract_sha256=design["plan_sha256"],
            implementation_pins=design["implementation_pins"],
            raw_row_file_sha256=sources,
            raw_billing_file_sha256={
                p.name: file_digest(p)
                for p in sorted((root / "billing").glob("*.json"))
            },
            exporter_sha256=file_digest(Path(__file__)),
        ),
        privacy_boundary=dict(
            included="public canonical actions, outcomes, typed failures, aggregate billing and digests",
            excluded="prompts, observations, provider reasoning, raw provider payloads and account metadata",
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
