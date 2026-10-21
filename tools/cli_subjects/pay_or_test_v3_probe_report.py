"""The v3 probe's read-out (``pay_or_test_v3_design_note.md``, "Probe, 2026-10-19"), in the declared order.

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/pay_or_test_v3_probe_report.py \\
        runs/procurement_allocation/pay_or_test_v2_probe_cli_claude_opus55 runs/procurement_allocation/pay_or_test_v2_probe_cli_codex_sol61

Each play is priced action by action with ``pay_or_test_v2_report.score_trace`` (v2's reference) and checked against
the margin the run recorded. Per subject: on the 6 criterion worlds (``myopic_pays``: the best first move is a newcomer
quote worth only its option value), how often the first information request goes to a newcomer and how often the first
action is a best first move (its priced loss is zero); then decision loss per world beside the one-step rule's and the
pay-the-premium rule's exact expected losses from the pack; the 6 ``myopic_tests`` worlds as the contrast.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import pay_or_test_v2_report as rep

PACK = "pay_or_test_v2_pilot"
REQUESTS = ("request_quote", "request_sample")


def read(run_root: Path) -> dict:
    manifest, payloads = rep.load_pack(PACK)
    worlds = {w["case_id"]: w for w in manifest["worlds"]}
    artifact = json.loads((run_root / "summary.json").read_text())
    rows_by_kind: dict[str, list] = {"myopic_pays": [], "myopic_tests": []}
    failed = []
    for row in artifact["rows"]:
        w = worlds[row["case_id"]]
        if row.get("status") != "completed":
            failed.append(w["slug"])
            continue
        scored, margin = rep.score_trace(payloads[row["case_id"]], row)
        if abs(margin - float(row["contribution_margin_usd"])) > 1e-6:
            raise SystemExit(f"{w['slug']}: replay margin {margin} differs from the recorded {row['contribution_margin_usd']}")
        steps = scored["steps"]
        newcomers = {n["supplier_id"] for n in w["newcomers"]}
        first_request = next((s for s in steps if s["action"] in REQUESTS), None)
        rows_by_kind[w["kind"]].append({
            "slug": w["slug"], "trace": " ".join(rep._short(s) for s in steps),
            "first_action": steps[0]["action"] if steps else None,
            "first_is_best": bool(steps) and abs(float(steps[0]["loss_usd"])) < 1e-6,
            "first_request_to_newcomer": bool(first_request) and first_request["supplier_id"] in newcomers,
            "decision_loss_usd": scored["decision_loss_usd"],
            "one_step_loss_usd": w["rule_loss_usd"]["one_step_value"], "pay_premium_loss_usd": w["rule_loss_usd"]["pay_premium"],
        })
    out = {"campaign_id": artifact["plan"]["campaign_id"], "failed": failed, "by_kind": {}}
    for kind, rows in rows_by_kind.items():
        mean = lambda key: round(statistics.fmean(r[key] for r in rows), 2) if rows else None  # noqa: E731
        out["by_kind"][kind] = {
            "plays": len(rows), "first_request_to_newcomer": sum(r["first_request_to_newcomer"] for r in rows),
            "first_action_is_best": sum(r["first_is_best"] for r in rows),
            "mean_decision_loss_usd": mean("decision_loss_usd"), "mean_one_step_loss_usd": mean("one_step_loss_usd"),
            "mean_pay_premium_loss_usd": mean("pay_premium_loss_usd"), "rows": rows,
        }
    return out


if __name__ == "__main__":
    print(json.dumps([read(Path(p)) for p in sys.argv[1:]], indent=1))
