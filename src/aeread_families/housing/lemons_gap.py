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

**Against the reference.** The scripted ``inspect_then_sign`` reference ran on
the same worlds as a control in both bundles. It never signs without
inspecting, so its payoff is its inspected leases minus its fees, and each
route's parts can be set against it from the published control rows alone. Its
lease-level diagnostics come from replaying the deterministic policy on the
regenerated worlds, checked against every published control payoff.

The report follows ``aeread.gap_decomposition/0.1``, the shape the Examiner
renders for any family: realized gap, additive components with world-bootstrap
intervals, decision classes with counts and amounts, and every instance with
the step that decided it. ``tables/contributions.jsonl`` carries the parts down
to the step: one row per decision per part (a lease, a blind bet and its draw,
an inspection fee), each with its cell and step, and per cell the rows of a
part sum to that cell's part; ``cell_parts`` in the report lists every cell's
parts, so a part's gap can be followed to the worlds, cells and steps behind it.

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
    steps: list[dict[str, Any]] = []
    for d in row.get("commit_decisions") or []:
        t, l = int(d["tenant_id"]), int(d["listing_id"])
        ev, rent = float(d["expected_value"]), float(d["rent"])
        true = float(world.values[t][l])
        sound = float(world.values_if_sound[t][l])
        p = 0.0 if d["informed"] else (sound - ev) / loss
        base = {"tenant_id": t, "listing_id": l, "round_index": int(d["round_index"]), "rent": rent,
                "expected_value": ev, "lemon_probability": round(p, 6), "quality": d["quality"], "decision": d["decision"]}
        at = {"round_index": int(d["round_index"]), "phase_id": "commit", "seat_id": f"tenant_{t}", "tenant_id": t, "listing_id": l}
        if d["decision"] == "sign":
            if d["informed"]:
                parts["informed_leases"] += true - rent
                steps.append({**at, "component": "informed_leases", "amount": true - rent,
                              "note": f"signed listing {l} after inspecting it: worth {true:.0f} to the tenant, rent {rent:.0f}"})
            else:
                bet = "blind_good_bets" if ev >= rent else "blind_bad_bets"
                parts[bet] += ev - rent
                parts["lemon_draws"] += true - ev
                steps.append({**at, "component": bet, "amount": ev - rent,
                              "note": f"signed listing {l} without inspecting: expected value {ev:.0f} at lemon probability {p:.2f}, rent {rent:.0f}"})
                if true != ev:
                    steps.append({**at, "component": "lemon_draws", "amount": true - ev,
                                  "note": f"listing {l} turned out {d['quality']}: worth {true:.0f} against {ev:.0f} expected"})
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
    for (round_index, seat), action in sorted(inspections.items()):
        if isinstance(action, dict) and action.get("decision") == "inspect":
            listing = action.get("listing_id")
            steps.append({"round_index": int(round_index), "phase_id": "inspect", "seat_id": seat, "tenant_id": int(seat.split("_")[-1]),
                          "listing_id": listing, "component": "inspection_spend", "amount": -fee,
                          "note": f"inspected listing {listing}: fee {fee:.0f}"})
    residual = float(row["tenant_net_payoff"]) - sum(parts.values())
    return {"parts": parts, "residual": residual, "instances": found, "contributions": steps}


def _boot(values: Sequence[float], rng: random.Random) -> list[float] | None:
    if len(values) < 2:
        return None
    means = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(BOOTSTRAP_DRAWS))
    return [means[int(0.025 * BOOTSTRAP_DRAWS)], means[min(BOOTSTRAP_DRAWS - 1, int(0.975 * BOOTSTRAP_DRAWS))]]


REFERENCE = "inspect_then_sign"


def _table_bytes(rows: Sequence[Mapping[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def _controls(bundle: str) -> dict[int, dict[str, Any]]:
    return {int(r["world_seed"]): r for r in comparison._rows(bundle, "scripted_controls")
            if r.get("policy") == REFERENCE and r.get("status") == "completed"}


def _lease_diagnostics(leases: Sequence[Sequence[tuple[float, float, bool]]]) -> dict[str, Any]:
    """Per market: leases signed after inspecting and blind, surplus per inspected lease, rent above the ask."""
    informed = [x for market in leases for x in market if x[2]]
    signed = [x for market in leases for x in market]
    n = len(leases)
    return {"markets": n,
            "informed_leases_per_market": round(len(informed) / n, 4) if n else None,
            "blind_leases_per_market": round((len(signed) - len(informed)) / n, 4) if n else None,
            "surplus_per_informed_lease": round(sum(x[0] for x in informed) / len(informed), 4) if informed else None,
            "rent_minus_ask_per_lease": round(sum(x[1] for x in signed) / len(signed), 4) if signed else None}


def _reference(paired: Sequence[int], world_mean, rng: random.Random) -> dict[str, Any]:
    from . import lemons, lemons_campaign

    controls = _controls(comparison.LEFT)
    if {w: controls[w]["tenant_net_payoff"] for w in controls} != {w: r["tenant_net_payoff"] for w, r in _controls(comparison.RIGHT).items()}:
        raise ValueError("the two bundles' reference controls differ; they were not run on the same worlds")
    ref: dict[int, dict[str, float]] = {}
    for world_seed in paired:
        row = controls[world_seed]
        if row["lemon_signings"] or row["uninspected_lemon_signings"]:
            raise ValueError("the reference signed a lemon or signed blind, so its payoff is not inspected leases minus fees")
        fee = float(comparison._world(world_seed).inspection_cost) * float(row["inspection_count"])
        ref[world_seed] = {"informed_leases": float(row["tenant_net_payoff"]) + fee, "blind_good_bets": 0.0, "blind_bad_bets": 0.0,
                           "lemon_draws": 0.0, "inspection_spend": -fee}
    vs = {}
    for side, _ in SIDES:
        def block(pick_model, pick_ref) -> dict[str, Any]:
            diffs = [world_mean(side, w, pick_model) - pick_ref(w) for w in paired]
            return {"model": sum(world_mean(side, w, pick_model) for w in paired) / len(paired),
                    "reference": sum(pick_ref(w) for w in paired) / len(paired),
                    "difference": sum(diffs) / len(diffs), "difference_ci": _boot(diffs, rng)}
        vs[side] = {"realized": block(lambda c: sum(c["parts"].values()), lambda w: sum(ref[w].values())),
                    "components": [{"key": key, "label": label, "group": group, "description": description,
                                    **block(lambda c, key=key: c["parts"][key], lambda w, key=key: ref[w][key])}
                                   for key, label, group, description in COMPONENTS]}
    environment = lemons_campaign.load_contract(comparison.ROOT / "configs" / f"{comparison.LEFT}.json")["environment"]
    replay, mismatches = [], 0
    for world_seed in paired:
        world = comparison._world(world_seed)
        market = lemons.run_lemons_policy(world, int(environment["rounds"]), REFERENCE)
        leases = [(float(world.values[t][l]) - float(market.signed_rent[t]), float(market.signed_rent[t]) - float(world.ask[l]), True)
                  for t, l in market.pairs]
        total = sum(x[0] for x in leases) - float(world.inspection_cost) * float(controls[world_seed]["inspection_count"])
        mismatches += abs(total - float(controls[world_seed]["tenant_net_payoff"])) > 1e-6
        replay.append(leases)
    diagnostics = {"reference": _lease_diagnostics(replay)}
    for side, bundle in SIDES:
        markets = []
        for row in _cells(bundle):
            if int(row["world_seed"]) not in paired:
                continue
            world = comparison._world(int(row["world_seed"]))
            markets.append([(float(world.values[d["tenant_id"]][d["listing_id"]]) - float(d["rent"]),
                             float(d["rent"]) - float(world.ask[d["listing_id"]]), bool(d["informed"]))
                            for d in row["commit_decisions"] if d["decision"] == "sign"])
        diagnostics[side] = _lease_diagnostics(markets)
    return {"key": REFERENCE, "label": "scripted inspect-then-sign reference",
            "description": ("A scripted policy on the same worlds: inspect the best uninspected open listing when the "
                            "inspection pays for itself in expectation, offer the ask plus one on the best listing it has "
                            "verified sound, sign only verified-sound holds. A yardstick, not an optimum: a route can beat "
                            "it on a part, as good blind bets do."),
            "source": "tables/scripted_controls.jsonl (both bundles, identical)",
            "replay_check": {"worlds": len(paired), "mismatches": mismatches,
                             "statement": "the replayed policy reproduces every published reference payoff"},
            "vs": vs, "lease_diagnostics": diagnostics,
            "reference_parts": [{"world_seed": w, "parts": ref[w]} for w in paired]}


def _model(bundle: str) -> str:
    contract = json.loads((comparison.ROOT / "configs" / f"{bundle}.json").read_text())
    return contract["route"]["requested_model"]


def compare() -> dict[str, Any]:
    return _analyse()[0]


def _analyse() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The report, and the contribution rows written beside it as ``tables/contributions.jsonl``."""
    per_side: dict[str, dict[int, list[dict[str, Any]]]] = {}
    instances: list[dict[str, Any]] = []
    residuals: list[float] = []
    cells_count: dict[str, int] = {}
    cell_parts: list[dict[str, Any]] = []
    contributions: list[dict[str, Any]] = []
    unexplained: list[float] = []
    for side, bundle in SIDES:
        grain = _grain(bundle)
        worlds: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
        cells = _cells(bundle)
        cells_count[side] = len(cells)
        for row in cells:
            result = analyse_cell(row, grain.get(row["receipt_sha256"], {}))
            residuals.append(result["residual"])
            cell = {"side": side, "campaign_id": bundle, "receipt_sha256": row["receipt_sha256"],
                    "world_seed": int(row["world_seed"]), "replicate_index": int(row["replicate_index"])}
            cell_parts.append({**cell, "stratum": row.get("stratum"), "parts": result["parts"]})
            sums: collections.Counter = collections.Counter()
            for item in result["contributions"]:
                sums[item["component"]] += item["amount"]
                contributions.append({**cell, **item, "amount": round(item["amount"], 6)})
            unexplained.extend(result["parts"][key] - sums[key] for key, *_ in COMPONENTS)
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
    baselines = [_reference(paired, world_mean, rng)]
    sources = {bundle: hashlib.sha256((comparison.EVIDENCE / bundle / "publication_manifest.json").read_bytes()).hexdigest()
               for _, bundle in SIDES}
    if max(abs(r) for r in unexplained) > 1e-6:
        raise ValueError("a cell's contribution rows do not add up to its components")
    phase_rank = {"inspect": 0, "commit": 1}
    table = sorted(contributions, key=lambda i: (i["side"], i["world_seed"], i["replicate_index"], i["round_index"],
                                                   phase_rank[i["phase_id"]], i["tenant_id"], i["component"]))
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
                      "stream": "one random.Random(seed): realized, then components in declared order, then class amounts in declared order, then each baseline's left and right contrasts (realized, then components)"},
        "realized": realized,
        "components": components,
        "accounting_check": {"max_abs_residual_per_cell": max(abs(r) for r in residuals),
                             "statement": "each cell's components sum to its published tenant_net_payoff",
                             "max_abs_contribution_residual": max(abs(r) for r in unexplained),
                             "contribution_statement": "per cell, the contribution rows of each component sum to that cell's component"},
        "cell_parts": sorted(cell_parts, key=lambda c: (c["side"], c["world_seed"], c["replicate_index"])),
        "contributions": {"table": "tables/contributions.jsonl", "rows": len(contributions),
                          "fields": ["side", "campaign_id", "receipt_sha256", "world_seed", "replicate_index", "round_index",
                                     "phase_id", "seat_id", "tenant_id", "listing_id", "component", "amount", "note"]},
        "classes": classes,
        "baselines": baselines,
        "instances": sorted(instances, key=lambda i: (i["class"], i["side"], i["world_seed"], i["replicate_index"], i["round_index"], i["tenant_id"])),
        "source_manifest_sha256": sources,
    }, table


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
        *_baseline_readme(report, left, right),
        "Every instance, with the step that decided it, is in `reports/gap_decomposition.json`. "
        f"`tables/contributions.jsonl` ({report['contributions']['rows']} rows) carries every part down to the decision and "
        "step that made it; per cell, a part's rows sum to that cell's part "
        f"(largest difference {report['accounting_check']['max_abs_contribution_residual']:.2g}).",
        "",
    ]
    return "\n".join(lines)


def _baseline_readme(report: Mapping[str, Any], left: str, right: str) -> list[str]:
    lines: list[str] = []
    for b in report.get("baselines") or []:
        f = lambda x: f"{x['difference']:.1f} ({x['difference_ci'][0]:.1f} to {x['difference_ci'][1]:.1f})"
        lines += [f"Against the {b['label']} (replay reproduces {b['replay_check']['worlds'] - b['replay_check']['mismatches']} of "
                  f"{b['replay_check']['worlds']} published payoffs), per market:", "",
                  f"| part | {left} minus reference | {right} minus reference |", "|---|---|---|",
                  f"| tenant net payoff (realized) | {f(b['vs']['left']['realized'])} | {f(b['vs']['right']['realized'])} |",
                  *(f"| {lc['label']} | {f(lc)} | {f(rc)} |" for lc, rc in zip(b["vs"]["left"]["components"], b["vs"]["right"]["components"])),
                  ""]
        d = b["lease_diagnostics"]
        lines += ["| leases, per market | " + " | ".join([left, right, "reference"]) + " |", "|---|---|---|---|",
                  *(f"| {label} | " + " | ".join("n/a" if d[k][key] is None else f"{d[k][key]:.2f}" for k in ("left", "right", "reference")) + " |"
                    for key, label in (("informed_leases_per_market", "signed after inspecting"), ("blind_leases_per_market", "signed blind"),
                                       ("surplus_per_informed_lease", "surplus per inspected lease"), ("rent_minus_ask_per_lease", "rent minus ask"))),
                  ""]
    return lines


def write() -> None:
    report, table = _analyse()
    (OUT / "reports").mkdir(parents=True, exist_ok=True)
    (OUT / "reports" / "gap_decomposition.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    (OUT / "tables" / "contributions.jsonl").write_text(_table_bytes(table))
    (OUT / "README.md").write_text(_readme(report))


def check() -> bool:
    report, rows = _analyse()
    table = OUT / "tables" / "contributions.jsonl"
    ok = ((OUT / "reports" / "gap_decomposition.json").read_text() == json.dumps(report, indent=2, sort_keys=True) + "\n"
          and table.exists() and table.read_text() == _table_bytes(rows)
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
