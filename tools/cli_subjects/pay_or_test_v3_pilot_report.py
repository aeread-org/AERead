"""Pay or test version 3 pilot: the declared read-out (``pay_or_test_v3_plan.md``, Section 5), in the declared order.

    PYTHONPATH=src python tools/cli_subjects/pay_or_test_v3_pilot_report.py RUN_ROOT [RUN_ROOT ...] > report.json

Every completed play is replayed through the version 3 environment from its public trace (the replies are a function
of the case, so the replay meets the same ones) and must reproduce the margin the run recorded; it is then priced
action by action with ``pay_or_test_v3_reference.score_actions``. Per subject and cell:

1. how often the first information request (quote, sample or lookup) goes to a newcomer, and how often the first action
   is a best first action (priced loss zero);
2. the share of the pay-the-premium-to-best gap the play closes, ``1 - loss / (best - pay)``, averaged over worlds
   (each world the mean of its plays), with a 95% bootstrap interval over worlds;
3. mean decision loss beside the one-step rule's and the pay-the-premium rule's exact expected losses;
4. lookups: plays with any, and plays that looked up two newcomers of one kind;
5. quote requests left unanswered, and how often a subject asked an unanswered newcomer again;
6. the sizing inputs: per-world SD of decision loss (mean of plays) and the within-world SD.
"""
from __future__ import annotations

import json
import random
import statistics
import sys
from pathlib import Path

from aeread_families.procurement_allocation import pay_or_test_v3_case_matrix as pack_module
from aeread_families.procurement_allocation import pay_or_test_v3_reference as reference
from aeread_families.procurement_allocation.pay_or_test_reference import final_margin

INFORMATION = reference.REQUESTS
BOOTSTRAP = 4000


def _actions(row: dict) -> list[dict]:
    keep = ("action", "supplier_id", "award_lines", "reason")
    return [{k: v for k, v in step.items() if k in keep} for step in row["action_trace"] if step["action"] != "unparseable"]


def _interval(values: list[float]) -> list[float] | None:
    if len(values) < 2:
        return None
    rng = random.Random(20261019)
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(BOOTSTRAP))
    return [round(means[int(0.025 * BOOTSTRAP)], 4), round(means[int(0.975 * BOOTSTRAP) - 1], 4)]


def read(run_root: Path) -> dict:
    artifact = json.loads((run_root / "summary.json").read_text())
    split = artifact["plan"].get("pack", pack_module.PILOT_PACK_ID)
    manifest = json.loads((pack_module.pack_root(split) / "pack.json").read_text())
    worlds = {w["case_id"]: w for w in manifest["worlds"]}
    payloads = {json.loads(p.read_text())["case_id"]: json.loads(p.read_text())["payload"]
                for p in pack_module.case_paths(split=split)}
    plays, failed = [], []
    for row in artifact["rows"]:
        world = worlds[row["case_id"]]
        if row.get("status") != "completed":
            failed.append({"slug": world["slug"], "replicate": row.get("inference_seed")})
            continue
        payload = payloads[row["case_id"]]
        actions = _actions(row)
        ref = reference.Reference(payload)
        margin = final_margin(ref, reference.run(payload, actions))
        if abs(margin - float(row["contribution_margin_usd"])) > 1e-6:
            raise SystemExit(f"{world['slug']}: replay margin {margin} differs from the recorded {row['contribution_margin_usd']}")
        scored = reference.score_actions(payload, actions)
        steps = scored["steps"]
        newcomers = {n["supplier_id"] for n in world["newcomers"]}
        first_info = next((s for s in steps if s["action"] in INFORMATION), None)
        looked = [s["supplier_id"] for s in steps if s["action"] == reference.LOOKUP]
        kinds = {n["supplier_id"]: n["kind"] for n in world["newcomers"]}
        unanswered = [s for s in steps if s["action"] == "request_quote" and s.get("answered") is False]
        asked_again = sum(1 for k, s in enumerate(steps) if s in unanswered and any(
            t["action"] == "request_quote" and t["supplier_id"] == s["supplier_id"] for t in steps[k + 1:]))
        gap = world["best_policy_value_usd"] - world["rule_value_usd"]["pay_premium"]
        plays.append({
            # An odds twin carries no cell of its own; it is its confirmatory world's, whose slug it shares.
            "slug": world["slug"], "kind": world.get("kind", world["slug"].split("__")[0]), "replicate": row["inference_seed"],
            "trace": " ".join(f"{s['action'].replace('request_', '').replace('look_up_source', 'lookup')}:"
                              f"{(s['supplier_id'] or '').replace('driver_board_', '')}" for s in steps),
            "first_info_to_newcomer": bool(first_info) and first_info["supplier_id"] in newcomers,
            "first_is_best": bool(steps) and abs(float(steps[0]["loss_usd"])) < 1e-6,
            "decision_loss_usd": scored["decision_loss_usd"],
            "gap_closed": None if gap <= 1e-9 else 1.0 - scored["decision_loss_usd"] / gap,
            "lookups": len(looked),
            "settled_a_kind": any(sum(kinds.get(x) == kind for x in set(looked)) >= 2 for kind in set(kinds.values())),
            "unanswered_quotes": len(unanswered), "asked_again_after_no_reply": asked_again,
            "margin_usd": round(margin, 4),
        })
    out = {"campaign_id": artifact["plan"]["campaign_id"], "pack": split, "plays": len(plays), "failed": failed, "by_kind": {}}
    for kind in pack_module.KINDS:
        rows = [p for p in plays if p["kind"] == kind]
        by_world: dict[str, list[dict]] = {}
        for p in rows:
            by_world.setdefault(p["slug"], []).append(p)
        world_loss = [statistics.fmean(p["decision_loss_usd"] for p in ps) for ps in by_world.values()]
        world_gap = [statistics.fmean(p["gap_closed"] for p in ps) for ps in by_world.values()
                     if all(p["gap_closed"] is not None for p in ps)]
        within = [statistics.stdev(p["decision_loss_usd"] for p in ps) for ps in by_world.values() if len(ps) > 1]
        slugs = sorted(by_world)
        ref_rows = [w for w in manifest["worlds"] if w["slug"] in slugs]
        out["by_kind"][kind] = {
            "plays": len(rows), "worlds": len(by_world),
            "first_info_to_newcomer": sum(p["first_info_to_newcomer"] for p in rows),
            "first_is_best": sum(p["first_is_best"] for p in rows),
            "gap_closed_mean": round(statistics.fmean(world_gap), 4) if world_gap else None,
            "gap_closed_ci95": _interval(world_gap),
            "decision_loss_mean_usd": round(statistics.fmean(world_loss), 2) if world_loss else None,
            "one_step_loss_mean_usd": round(statistics.fmean(w["rule_loss_usd"]["one_step_value"] for w in ref_rows), 2) if ref_rows else None,
            "pay_premium_loss_mean_usd": round(statistics.fmean(w["rule_loss_usd"]["pay_premium"] for w in ref_rows), 2) if ref_rows else None,
            "plays_with_a_lookup": sum(p["lookups"] > 0 for p in rows),
            "plays_settling_a_kind": sum(p["settled_a_kind"] for p in rows),
            "unanswered_quotes": sum(p["unanswered_quotes"] for p in rows),
            "asked_again_after_no_reply": sum(p["asked_again_after_no_reply"] for p in rows),
            "sizing": {"world_sd_usd": round(statistics.stdev(world_loss), 2) if len(world_loss) > 1 else None,
                       "within_world_sd_usd": round(statistics.fmean(within), 2) if within else None},
        }
    out["plays_detail"] = plays
    return out


if __name__ == "__main__":
    print(json.dumps([read(Path(p)) for p in sys.argv[1:]], indent=1))
