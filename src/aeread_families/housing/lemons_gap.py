"""Why two lemons routes differ: an exact decomposition of the payoff gap, and a
typed count of the decisions behind it.

A derived analysis in the Tier 1 sense: it reads only the two published v2
bundles (``tables/cells.jsonl`` and ``trajectories/sanitized.jsonl``) and the
worlds regenerated from their published seeds, and regenerates byte-identical
output (``--check``).

**Decomposition.** Every cell's tenant net payoff is split exactly into five
parts, so the paired gap between the routes is their sum with nothing left over:

- ``informed_leases``: surplus of leases the tenant signed after inspecting,
  value minus rent;
- ``blind_good_bets``: expected surplus, at the tenant's own lemon probability,
  of uninspected leases whose expected value covered the rent;
- ``blind_bad_bets``: the same for uninspected leases whose expected value was
  below the rent (negative);
- ``lemon_draws``: true value minus expected value on every uninspected lease,
  the luck of which listings turned out to be lemons (HL-J-01);
- ``inspection_spend``: minus the inspection fee times the inspections bought.

**Decision classes** extend the Housing failure taxonomy
(``failure_taxonomy.py`` on the v13 line, schema
``aeread.housing_failure_taxonomy/0.1``) with the lemons group ``L``, judged at
what the tenant knew; ``A1`` keeps its meaning there. They are diagnostic: a
decision can fall in several classes, and their dollar amounts are expected
losses at the tenant's beliefs, not parts of the decomposition. When both
branches land, the classes belong in that module.

The report follows ``aeread.gap_decomposition/0.1``, the shape the Examiner
renders for any family: realized gap, additive components with world-bootstrap
intervals, decision classes with counts and amounts, and every instance with
the step that decided it.

    python -m aeread_families.housing.lemons_gap --write
    python -m aeread_families.housing.lemons_gap --check
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import lemons_comparison as comparison

OUT = comparison.EVIDENCE / "housing_lemons_refusal_v2_gap"
BOOTSTRAP_SEED = 20260926
BOOTSTRAP_DRAWS = 10000
SIDES = (("left", comparison.LEFT), ("right", comparison.RIGHT))

COMPONENTS: tuple[tuple[str, str, str, str], ...] = (
    ("informed_leases", "inspected, then signed", "decision",
     "Surplus of leases signed after inspecting the listing: value minus rent."),
    ("blind_good_bets", "signed blind, worth it in expectation", "decision",
     "Expected surplus at the tenant's own lemon probability of uninspected leases whose expected value covered the rent."),
    ("blind_bad_bets", "signed blind, not worth it in expectation", "decision",
     "Expected surplus (negative) of uninspected leases whose expected value was below the rent."),
    ("lemon_draws", "which blind leases turned out lemons (luck)", "luck",
     "True value minus expected value on every uninspected lease: the draw, not the decision."),
    ("inspection_spend", "inspection fees", "cost",
     "Minus the fee times the inspections bought."),
)

CLASSES: dict[str, dict[str, str]] = {
    "L1_blind_sign_below_expected_value": {
        "group": "L", "label": "signed an uninspected hold worth less than its rent in expectation",
        "amount": "rent minus expected value, at the tenant's lemon probability",
    },
    "L2_skipped_worthwhile_inspection": {
        "group": "L", "label": "signed blind after passing on that round's inspection, when inspecting the listing first was worth the fee",
        "amount": "p x (lemon loss - (value if sound - rent)) - fee: what inspecting first would have saved in expectation",
    },
    "L3_declined_hold_worth_more": {
        "group": "L", "label": "walked from or let expire a hold worth more than its rent in expectation",
        "amount": "expected value minus rent, forgone",
    },
    "L4_signed_above_ask": {
        "group": "L", "label": "signed at a rent above the posted ask",
        "amount": "rent minus ask",
    },
    "L5_good_blind_bet_turned_lemon": {
        "group": "L", "label": "a blind signing worth it in expectation that turned out a lemon (luck, not a failure)",
        "amount": "value lost to the draw: expected value minus true value",
    },
    "A1_tenant_signed_above_own_value": {
        "group": "A", "label": "a signed lease left the tenant below zero surplus (as in the Housing taxonomy)",
        "amount": "rent minus true value",
    },
}


def _grain(bundle: str) -> dict[str, dict[tuple[int, str], Any]]:
    """Per receipt, each seat's inspect action by round (rounds counted by inspect phases)."""
    rows = [json.loads(line) for line in (comparison.EVIDENCE / bundle / "trajectories" / "sanitized.jsonl").read_text().splitlines() if line.strip()]
    by_receipt: dict[str, list] = collections.defaultdict(list)
    for row in rows:
        by_receipt[row["source_receipt_sha256"]].append(row)
    out: dict[str, dict[tuple[int, str], Any]] = {}
    for receipt, steps in by_receipt.items():
        steps.sort(key=lambda r: r["step_index"])
        rounds, current, seen = {}, -1, set()
        for row in steps:
            if row["phase_id"] == "inspect" and row["phase_instance_id"] not in seen:
                current += 1
            seen.add(row["phase_instance_id"])
            if row["phase_id"] == "inspect":
                valid = (row.get("outcome") or {}).get("valid") is True
                rounds[(current, row["seat_id"])] = row["action"] if valid else None
        out[receipt] = rounds
    return out


def _cells(bundle: str) -> list[dict[str, Any]]:
    return [row for row in comparison._rows(bundle, "cells")
            if row.get("stage") == "variance_pilot" and row.get("status") == "completed"]


def analyse_cell(row: Mapping[str, Any], inspections: Mapping[tuple[int, str], Any]) -> dict[str, Any]:
    world = comparison._world(int(row["world_seed"]))
    loss, fee = float(world.lemon_loss), float(world.inspection_cost)
    parts = {key: 0.0 for key, *_ in COMPONENTS}
    found: list[dict[str, Any]] = []
    for d in row.get("commit_decisions") or []:
        t, l = int(d["tenant_id"]), int(d["listing_id"])
        ev, rent = float(d["expected_value"]), float(d["rent"])
        true = float(world.values[t][l])
        sound = float(world.values_if_sound[t][l])
        p = 0.0 if d["informed"] else (sound - ev) / loss
        base = {"tenant_id": t, "listing_id": l, "round_index": int(d["round_index"]), "rent": rent,
                "expected_value": ev, "lemon_probability": round(p, 6), "quality": d["quality"], "decision": d["decision"]}
        if d["decision"] == "sign":
            if d["informed"]:
                parts["informed_leases"] += true - rent
            else:
                parts["blind_good_bets" if ev >= rent else "blind_bad_bets"] += ev - rent
                parts["lemon_draws"] += true - ev
                if ev < rent:
                    found.append({**base, "class": "L1_blind_sign_below_expected_value", "amount": rent - ev})
                gain = p * (loss - (sound - rent)) - fee
                spent = inspections.get((int(d["round_index"]), f"tenant_{t}"))
                inspected_that_round = isinstance(spent, dict) and spent.get("decision") == "inspect"
                if p > 0 and gain > 0 and not inspected_that_round:
                    found.append({**base, "class": "L2_skipped_worthwhile_inspection", "amount": gain})
                if ev >= rent and d["quality"] == "lemon":
                    found.append({**base, "class": "L5_good_blind_bet_turned_lemon", "amount": ev - true})
            if rent > float(world.ask[l]) + 1e-9:
                found.append({**base, "class": "L4_signed_above_ask", "amount": rent - float(world.ask[l])})
            if true < rent - 1e-9:
                found.append({**base, "class": "A1_tenant_signed_above_own_value", "amount": rent - true})
        elif ev > rent + 1e-9:
            found.append({**base, "class": "L3_declined_hold_worth_more", "amount": ev - rent})
    parts["inspection_spend"] = -fee * float(row["inspection_count"])
    residual = float(row["tenant_net_payoff"]) - sum(parts.values())
    return {"parts": parts, "residual": residual, "instances": found}


def _boot(values: Sequence[float], rng: random.Random) -> list[float] | None:
    if len(values) < 2:
        return None
    means = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(BOOTSTRAP_DRAWS))
    return [means[int(0.025 * BOOTSTRAP_DRAWS)], means[min(BOOTSTRAP_DRAWS - 1, int(0.975 * BOOTSTRAP_DRAWS))]]


def _model(bundle: str) -> str:
    contract = json.loads((comparison.ROOT / "configs" / f"{bundle}.json").read_text())
    return contract["route"]["requested_model"]


def compare() -> dict[str, Any]:
    per_side: dict[str, dict[int, list[dict[str, Any]]]] = {}
    instances: list[dict[str, Any]] = []
    residuals: list[float] = []
    cells_count: dict[str, int] = {}
    for side, bundle in SIDES:
        grain = _grain(bundle)
        worlds: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
        cells = _cells(bundle)
        cells_count[side] = len(cells)
        for row in cells:
            result = analyse_cell(row, grain.get(row["receipt_sha256"], {}))
            residuals.append(result["residual"])
            worlds[int(row["world_seed"])].append({"parts": result["parts"], "classes": collections.Counter(i["class"] for i in result["instances"]),
                                                   "amounts": collections.Counter({k: sum(i["amount"] for i in result["instances"] if i["class"] == k) for k in CLASSES})})
            for item in result["instances"]:
                instances.append({"side": side, "campaign_id": bundle, "receipt_sha256": row["receipt_sha256"],
                                  "world_seed": int(row["world_seed"]), "replicate_index": int(row["replicate_index"]),
                                  "phase_id": "commit", "seat_id": f"tenant_{item['tenant_id']}", **item,
                                  "amount": round(item["amount"], 4)})
        per_side[side] = worlds
    paired = sorted(set(per_side["left"]) & set(per_side["right"]))

    def world_mean(side: str, world: int, pick) -> float:
        cells = per_side[side][world]
        return sum(pick(c) for c in cells) / len(cells)

    rng = random.Random(BOOTSTRAP_SEED)

    def block(pick) -> dict[str, Any]:
        left = [world_mean("left", w, pick) for w in paired]
        right = [world_mean("right", w, pick) for w in paired]
        diffs = [a - b for a, b in zip(left, right)]
        return {"left": sum(left) / len(left), "right": sum(right) / len(right),
                "difference": sum(diffs) / len(diffs), "difference_ci": _boot(diffs, rng)}

    realized = block(lambda c: sum(c["parts"].values()))
    components = [{"key": key, "label": label, "group": group, "description": description,
                   **block(lambda c, key=key: c["parts"][key])} for key, label, group, description in COMPONENTS]
    classes = []
    for key, meta in CLASSES.items():
        counts = {side: sum(c["classes"][key] for w in per_side[side] for c in per_side[side][w]) for side, _ in SIDES}
        amounts = block(lambda c, key=key: c["amounts"][key])
        classes.append({"key": key, "group": meta["group"], "label": meta["label"], "amount_basis": meta["amount"],
                        "left_count": counts["left"], "right_count": counts["right"],
                        "left_amount_per_market": amounts["left"], "right_amount_per_market": amounts["right"],
                        "amount_difference": amounts["difference"], "amount_difference_ci": amounts["difference_ci"]})
    sources = {bundle: hashlib.sha256((comparison.EVIDENCE / bundle / "publication_manifest.json").read_bytes()).hexdigest()
               for _, bundle in SIDES}
    return {
        "schema_version": "aeread.gap_decomposition/0.1",
        "taxonomy_schema": "aeread.housing_failure_taxonomy/0.1",
        "family": "housing", "world_kind": "lemons",
        "left": comparison.LEFT, "right": comparison.RIGHT,
        "left_model": _model(comparison.LEFT), "right_model": _model(comparison.RIGHT),
        "endpoint": "tenant_net_payoff", "unit": "utility points per market (cell)", "direction": "higher",
        "claim_status": "development_qualification", "winner_claim_allowed": False, "inferential_model_ranking_allowed": False,
        "paired_worlds": len(paired), "cells": cells_count,
        "bootstrap": {"seed": BOOTSTRAP_SEED, "draws": BOOTSTRAP_DRAWS, "interval": "percentile_95", "unit": "world_seed",
                      "stream": "one random.Random(seed): realized, then components in declared order, then class amounts in declared order"},
        "realized": realized,
        "components": components,
        "accounting_check": {"max_abs_residual_per_cell": max(abs(r) for r in residuals),
                             "statement": "each cell's components sum to its published tenant_net_payoff"},
        "classes": classes,
        "instances": sorted(instances, key=lambda i: (i["class"], i["side"], i["world_seed"], i["replicate_index"], i["round_index"], i["tenant_id"])),
        "source_manifest_sha256": sources,
    }


def _readme(report: Mapping[str, Any]) -> str:
    name = lambda m: str(m).split("/")[-1]
    left, right = name(report["left_model"]), name(report["right_model"])
    r = report["realized"]

    def row(label: str, b: Mapping[str, Any]) -> str:
        ci = b["difference_ci"]
        return f"| {label} | {b['left']:.1f} | {b['right']:.1f} | {b['difference']:.1f} ({ci[0]:.1f} to {ci[1]:.1f}) |"

    lines = [
        f"# {OUT.name}",
        "",
        f"Why `{report['left']}` ({left}) and `{report['right']}` ({right}) differ on the same {report['paired_worlds']} lemons worlds. "
        "Derived from the two published bundles and the worlds regenerated from their seeds by "
        "`python -m aeread_families.housing.lemons_gap`; `--check` regenerates these bytes. Descriptive: no winner, no ranking.",
        "",
        f"Tenant net payoff per market splits exactly into the parts below (largest per-cell residual "
        f"{report['accounting_check']['max_abs_residual_per_cell']:.2g}).",
        "",
        f"| part | {left} | {right} | {left} minus {right} (95% world bootstrap) |",
        "|---|---|---|---|",
        row("tenant net payoff (realized)", r),
        *(row(c["label"], c) for c in report["components"]),
        "",
        "Decision classes, judged at what the tenant knew (counts over all cells; amounts are expected dollars per market, "
        "diagnostic and overlapping, not parts of the sum):",
        "",
        f"| class | {left} count | {right} count | {left} per market | {right} per market |",
        "|---|---|---|---|---|",
        *(f"| `{c['key']}`: {c['label']} | {c['left_count']} | {c['right_count']} | {c['left_amount_per_market']:.1f} | {c['right_amount_per_market']:.1f} |"
          for c in report["classes"]),
        "",
        "Every instance, with the step that decided it, is in `reports/gap_decomposition.json`.",
        "",
    ]
    return "\n".join(lines)


def write() -> None:
    report = compare()
    (OUT / "reports").mkdir(parents=True, exist_ok=True)
    (OUT / "reports" / "gap_decomposition.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (OUT / "README.md").write_text(_readme(report))


def check() -> bool:
    report = compare()
    ok = ((OUT / "reports" / "gap_decomposition.json").read_text() == json.dumps(report, indent=2, sort_keys=True) + "\n"
          and (OUT / "README.md").read_text() == _readme(report))
    print("gap decomposition regenerates to the committed bytes" if ok else "gap decomposition differs from its generator")
    return ok


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        write()
        return 0
    if args.check:
        return 0 if check() else 1
    report = compare()
    print(json.dumps({k: report[k] for k in ("realized", "components", "accounting_check")}, indent=1))
    print(json.dumps([{k: c[k] for k in ("key", "left_count", "right_count", "left_amount_per_market", "right_amount_per_market")} for c in report["classes"]], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
