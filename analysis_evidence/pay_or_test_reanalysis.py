"""Versioned offline derivation of the paper's pay-or-test headline (P-T-17).

Build from retained logs with --cli-runs DIR --flash-runs DIR --write.
Check the published projection with --check; add both run directories to
re-audit the original receipts and re-extract every projected action.
Original plans, receipts, result rows and sealed events are never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
from typing import Any

from aeread.shared_runner.run.publication import (
    assert_public_payload, atomic_publish, bundle_artifact_digests, jsonl, seal_publication_manifest,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import audit_family_receipt
from aeread.shared_runner.task.receipts import read_evaluation_receipt
from . import model_campaign as mc
from . import pay_or_test_case_matrix as pack

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/cli_subjects"))
report = importlib.import_module("pay_or_test_report")
PUBLICATION_ID = "pay_or_test_v1_headline_reanalysis_20261016"
OUT = ROOT / "evidence/procurement_allocation" / PUBLICATION_ID
PANELS = {
    "sol61": ("cli", "codex_sol61", "pay_or_test_v1_finalquotes_codex_cli_sol61_v1"),
    "opus55": ("cli", "claude_opus55", "pay_or_test_v1_finalquotes_claude_code_opus55_v1"),
    "gemini38_flash": ("flash", "gemini38_flash", "pay_or_test_v1_finalquotes_openrouter_gemini38_flash_v2"),
    "gpt6_luna": ("flash", "gpt6_luna", "pay_or_test_v1_finalquotes_openrouter_gpt6_luna_v2"),
    "sol61_accounting": ("cli", "codex_sol61", "pay_or_test_v1_accounting_codex_cli_sol61_v1"),
    "opus55_accounting": ("cli", "claude_opus55", "pay_or_test_v1_accounting_claude_code_opus55_v1"),
}
ACTION_KEYS = ("action", "supplier_id", "offer_id", "proposal", "award_lines", "fields")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text())


def source_pins() -> dict[str, str]:
    # Pin the complete local Python implementation closure, including the
    # reference, environment, extraction code, report and replay machinery.
    paths = sorted(ROOT.joinpath("src").rglob("*.py"))
    paths += sorted(ROOT.joinpath("tools/cli_subjects").glob("*.py"))
    paths += [ROOT / "pyproject.toml"]
    paths += list(pack.case_paths()) + [pack.PACK_ROOT / "pack.json"]
    return {str(p.relative_to(ROOT)): digest(p) for p in paths}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def project_actions(events_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Extract ordered, parsed economic actions and their recorded validity.

    The caller first audits state and receipt replay. Free text is omitted;
    rejected actions retain their rejection, never repaired by text filling.
    """
    actions: dict[str, dict[str, Any]] = {}
    parsed: set[str] = set()
    finished: set[str] = set()
    outcomes = []
    for line in events_path.read_text().splitlines():
        event = json.loads(line)
        kind, action_id = event["event_type"], event["logical_action_id"]
        if kind not in {"logical_action_started", "action_parsed", "logical_action_succeeded",
                        "logical_action_failed", "family_outcome_recorded"}:
            continue
        payload = read(events_path.parent / event["payload_ref"])
        if kind == "logical_action_started":
            require(action_id not in actions, "duplicate logical action")
            require(payload["request"]["seat_id"] == "buyer", "unexpected acting seat")
            actions[action_id] = {"ordinal": len(actions) + 1}
        elif kind == "action_parsed":
            require(action_id in actions and action_id not in parsed, "unmatched or duplicate parse")
            result = payload["parse_result"]
            action = result["action"] if result["ok"] else {"action": "unparseable"}
            actions[action_id].update({key: action[key] for key in ACTION_KEYS if key in action})
            actions[action_id]["parse_ok"] = result["ok"]
            parsed.add(action_id)
        elif kind.startswith("logical_action_"):
            require(action_id in actions and action_id not in finished, "unmatched or duplicate action end")
            actions[action_id]["status"] = (
                "succeeded" if kind == "logical_action_succeeded" and payload.get("valid") is True
                else "agent_action_failure"
            )
            finished.add(action_id)
        else:
            outcomes.append(payload["outcome"])
    require(set(actions) == parsed == finished, "incomplete action records")
    require(len(outcomes) == 1, "expected exactly one sealed family outcome")
    outcome = outcomes[0]
    require(len(actions) == outcome["action_count"], "action count does not match sealed outcome")
    return list(actions.values()), outcome


def extract(cli_runs: Path, flash_runs: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records = {r["case_id"]: r for r in mc._case_records(pack.case_paths())}
    rows, bindings = [], {}
    for panel, (kind, subject, folder) in PANELS.items():
        run = (cli_runs if kind == "cli" else flash_runs) / folder
        model_plan = read(run / "model_plan.json")
        require(len(model_plan["inference_seeds"]) == 1, "expected one inference replicate")
        inference_seed = model_plan["inference_seeds"][0]
        require(len(model_plan["cases"]) == len(records) == 24, "expected the complete 24-world panel")
        expected = {r["case_id"]: r["content_sha256"] for r in model_plan["cases"]}
        require(expected == {k: v["content_sha256"] for k, v in records.items()}, "panel case identity mismatch")
        saved = read(run / "summary.json")
        old_by_case = {r["case_id"]: r for r in saved["rows"]}
        analysis_order = {r["case_id"]: i for i, r in enumerate(saved["rows"])}
        require(len(old_by_case) == len(saved["rows"]) == 24 and set(old_by_case) == set(records),
                "missing or duplicate original result rows")
        receipts = list((run / "executions").rglob("evaluation_receipt.json"))
        require(len(receipts) == 24, "missing or extra attempt: refuse selection by outcome")
        seen = set()
        driver = importlib.import_module("procurement_cli" if kind == "cli" else "pay_or_test_openrouter")
        for path in sorted(receipts):
            receipt = read_evaluation_receipt(path)
            case_id = receipt["case_id"]
            require(case_id in records and case_id not in seen, "unexpected or duplicate case receipt")
            seen.add(case_id)
            record = records[case_id]
            setup = (driver.build_setup(subject, record["path"], model_plan["provider_runtime"],
                                        "accounting_v1" if panel.endswith("_accounting") else "finalquotes_v2")
                     if kind == "cli" else driver.build_setup(subject, record["path"]))
            audited = audit_family_receipt(setup=setup, receipt_path=path)
            require(audited["replay_level"] == "state_and_score", "no state-and-score replay")
            require(audited["status"] == "ok" and audited["inclusion_status"] == "included",
                    "unscorable receipt: retain exclusion, do not silently drop it")
            require(audited["case_sha256"] == record["content_sha256"], "case digest mismatch")
            actions, outcome = project_actions(path.parent / "events.jsonl")
            old = old_by_case[case_id]
            require(old["inference_seed"] == inference_seed, "inference-seed mismatch")
            require(old["receipt_sha256"] == audited["receipt_sha256"], "original result names another receipt")
            # A comparison with the old projection is diagnostic only. The new
            # headline's input above comes from the replay-verified event log.
            new_row = {"case_id": case_id, "action_trace": actions,
                       "termination_reason": outcome["termination_reason"]}
            payload = read(record["path"])["payload"]
            scored, margin = report.score_trace(payload, new_row)
            old_scored, old_margin = report.score_trace(payload, old)
            require(abs(margin - outcome["contribution_margin_usd"]) < 1e-6, "headline replay margin mismatch")
            require(abs(old_margin - margin) < 1e-6, "old result margin differs")
            require(scored["decision_loss_usd"] == old_scored["decision_loss_usd"], "headline differs from prior table")
            rows.append({
                "panel": panel, "campaign_id": model_plan["campaign_id"], "case_id": case_id,
                "analysis_order": analysis_order[case_id],
                "case_sha256": record["content_sha256"], "inference_seed": inference_seed,
                "receipt_sha256": audited["receipt_sha256"], "run_plan_sha256": audited["run_plan_sha256"],
                "cell_id": audited["cell_id"], "episode_attempt_id": audited["episode_attempt_id"],
                "event_root_sha256": audited["evidence"]["event_root_sha256"],
                "artifact_root_sha256": audited["evidence"]["artifact_root_sha256"],
                "replay_level": audited["replay_level"], "action_trace": actions,
                "termination_reason": outcome["termination_reason"],
                "contribution_margin_usd": outcome["contribution_margin_usd"],
                "original_decision_loss_usd": old_scored["decision_loss_usd"],
            })
        require(seen == set(records), "incomplete receipt coverage")
        bindings[panel] = {"campaign_id": model_plan["campaign_id"], "model_plan_file_sha256": digest(run / "model_plan.json"),
                           "original_summary_file_sha256": digest(run / "summary.json"),
                           "planned": 24, "verified": 24, "missing": 0}
        print(f"{panel}: 24/24 receipts replayed; sealed-action headline matches prior result", flush=True)
    return sorted(rows, key=lambda r: (r["panel"], r["case_id"])), bindings


def derive(rows: list[dict[str, Any]]) -> dict[str, Any]:
    manifest, payloads = report.load_pack()
    case_ids = {w["case_id"] for w in manifest["worlds"]}
    output = {}
    for panel in PANELS:
        selected = [r for r in rows if r["panel"] == panel]
        by_case = {r["case_id"]: r for r in selected}
        require(len(selected) == len(by_case) == 24 and set(by_case) == case_ids, "incomplete or duplicate projection")
        require({r["analysis_order"] for r in selected} == set(range(24)), "invalid bootstrap ordering")
        # The old report consumed summary-row order. Preserve that metadata
        # separately from JSONL order so its seeded Monte Carlo interval is exact.
        order = [r["case_id"] for r in sorted(selected, key=lambda r: r["analysis_order"])]
        losses, values = [], []
        for case_id in order:
            row = by_case[case_id]
            scored, margin = report.score_trace(payloads[case_id], row)
            require(abs(margin - row["contribution_margin_usd"]) < 1e-6, "projected margin changed")
            require(scored["decision_loss_usd"] == row["original_decision_loss_usd"], "projected headline changed")
            losses.append(scored["decision_loss_usd"])
            values.append(scored["best_policy_value_usd"])
        mean, lo, hi = report.interval(losses)
        output[panel] = {"worlds": 24, "decision_loss_usd": {"mean": round(mean, 1), "low": round(lo, 1), "high": round(hi, 1)},
                         "best_policy_share_percent": round(100 * (1 - sum(losses) / sum(values)), 1),
                         "per_world_decision_loss_usd": dict(zip(order, losses))}
    return {"analysis_id": PUBLICATION_ID, "status": "retrospective_derived_analysis", "panels": output,
            "receipt_replay_and_headline_derivation_are_separate": True,
            "run_to_run_variance": "unmeasured: one recorded trajectory per subject and world",
            "public_reproduction": "headline from projected actions; original receipt/state audit additionally requires retained run roots"}


def files(rows: list[dict[str, Any]], bindings: dict[str, Any]) -> dict[str, bytes]:
    result = derive(rows)
    return {
        "tables/actions.jsonl": jsonl(rows),
        "reports/headline.json": canonical_json_bytes(result) + b"\n",
        "source_pins.json": canonical_json_bytes(source_pins()) + b"\n",
        "source_bindings.json": canonical_json_bytes(bindings) + b"\n",
        "README.md": ("# Pay-or-test v1: verified headline reanalysis\n\n"
            "Retrospective derivation of paper Table 5.3 and the earlier-brief comparison in Appendix E.4 "
            "from all 144 original sealed executions (96 final-brief, 48 earlier-brief). "
            "Each receipt is audited through state and score replay before parsed buyer actions and their validity "
            "are extracted. The pinned reference prices those actions; all 144 losses equal the earlier report. "
            "No model is called and no original receipt is modified.\n\n"
            "`PYTHONPATH=src python -m aeread_families.procurement_allocation.pay_or_test_reanalysis --check` "
            "checks source pins and reconstructs the headline from the included projection. Add "
            "`--cli-runs DIR --flash-runs DIR` to audit original receipts and re-extract the projection. "
            "`DIR` is each group's parent run directory, not an individual run.\n\n"
            "Public data includes parsed economic fields, recorded action validity, case/receipt/evidence digests "
            "and outcomes needed by this analysis. It omits free-text messages, provider responses and complete "
            "receipts. Full provenance audit still needs the retained run roots. These scores were not leaves "
            "of the historical receipts, and this analysis does not make the campaigns preregistered or qualified.\n"
        ).encode(),
    }


def verify_manifest(output: Path) -> None:
    manifest = read(output / "publication_manifest.json")
    core = {k: v for k, v in manifest.items() if k not in {"manifest_sha256", "publication_sha256"}}
    require(hashlib.sha256(canonical_json_bytes(core)).hexdigest() == manifest["manifest_sha256"],
            "manifest digest mismatch")
    require(manifest["artifacts"] == bundle_artifact_digests(output), "bundle artifact digest mismatch")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli-runs", type=Path)
    parser.add_argument("--flash-runs", type=Path)
    parser.add_argument("--output", type=Path, default=OUT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    require(bool(args.cli_runs) == bool(args.flash_runs), "supply both run directories")
    require(not args.write or bool(args.cli_runs), "writing requires original evidence")
    if args.check:
        verify_manifest(args.output)
        require(read(args.output / "source_pins.json") == source_pins(), "analysis source pins changed")
    if args.cli_runs:
        rows, bindings = extract(args.cli_runs, args.flash_runs)
    else:
        rows = [json.loads(line) for line in (args.output / "tables/actions.jsonl").read_text().splitlines()]
        bindings = read(args.output / "source_bindings.json")
    generated = files(rows, bindings)
    for name, value in generated.items():
        assert_public_payload(name, value)
        if args.write:
            atomic_publish(args.output / name, value)
        else:
            require((args.output / name).read_bytes() == value, f"regeneration differs: {name}")
    if args.write and not (args.output / "publication_manifest.json").exists():
        seal_publication_manifest(args.output, publication_id=PUBLICATION_ID, campaign_id=None,
            privacy_boundary={"included": "numeric/categorical economic action projections, validity, outcomes and provenance digests",
                              "excluded": "free-text messages, complete receipts, provider responses and prompts"},
            source_bindings={"source_pins_sha256": digest(args.output / "source_pins.json"),
                             "inputs_sha256": digest(args.output / "source_bindings.json")})
    print(json.dumps({k: {a: b for a, b in v.items() if a != "per_world_decision_loss_usd"}
                      for k, v in derive(rows)["panels"].items()}, indent=2))
    print(f"all {len(rows)} headlines regenerate; source pins and public-text scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
