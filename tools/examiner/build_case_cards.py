"""Case cards for the examiner: the family's cards, and each check evaluated on every published cell.

    python3 build_case_cards.py <out dir> <AERead checkout> [receipt_index.json]

Reads `docs/families/*/case_cards/*.json` (generated world cards) and
`docs/families/*/case_cards.md` (stratum prose), and for every evidence bundle
whose `tables/cells.jsonl` rows name a carded world, evaluates the card's
diagnostic checks from `tables/cells.jsonl` and `tables/periods.jsonl`. Writes
`data/case_cards.json`. Families without cards are untouched.
"""

from __future__ import annotations

import base64
import gzip
import json
import re
import sys
from pathlib import Path

EXECUTION_VIOLATIONS = ("sample_not_verified", "over_capacity", "malformed_procurement_action", "episode_ended_before_period")


def sections(markdown: str) -> dict[str, dict[str, list[str]]]:
    """`## heading` sections as paragraphs and bullets, for the page's inline renderer."""
    out: dict[str, dict[str, list[str]]] = {}
    for block in re.split(r"^## ", markdown, flags=re.M)[1:]:
        heading, _, body = block.partition("\n")
        paragraphs, bullets, current = [], [], []
        for line in body.splitlines():
            if line.startswith("- "):
                bullets.append(line[2:].strip())
            elif line.startswith("  ") and bullets:
                bullets[-1] += " " + line.strip()
            elif line.startswith("|"):
                continue  # tables stay in the repository copy
            elif line.strip():
                current.append(line.strip())
            elif current:
                paragraphs.append(" ".join(current))
                current = []
        if current:
            paragraphs.append(" ".join(current))
        out[heading.strip()] = {"paragraphs": paragraphs, "bullets": bullets}
    return out


def negotiation_events(attempt_dir: Path) -> dict | None:
    """Counter-offers, the ones a supplier accepted, and whether an award used an accepted offer."""
    events = attempt_dir / "events.jsonl"
    if not events.exists():
        return None

    def payload(ref: str) -> dict:
        digest = ref.split(":")[-1].split("/")[-1]
        path = attempt_dir / "artifacts" / "sha256" / digest[:2] / digest
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    sent = accepted = used = 0
    accepted_offers: set[str] = set()
    pending = False
    for line in events.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event["event_type"] == "action_parsed":
            action = (payload(event["payload_ref"]).get("parse_result") or {}).get("action") or {}
            pending = action.get("action") == "counter_offer"
            sent += pending
            if action.get("action") == "submit_award":
                used += sum(1 for row in action.get("award_lines") or [] if row.get("offer_id") in accepted_offers)
        elif event["event_type"] == "transition_applied" and pending:
            consequences = (payload(event["payload_ref"]).get("transition") or {}).get("consequences") or {}
            if consequences.get("accepted") and consequences.get("offer_id"):
                accepted += 1
                accepted_offers.add(consequences["offer_id"])
            pending = False
    return {"sent": sent, "accepted": accepted, "award_lines_on_negotiated_offers": used}


def evaluate(card: dict, cell: dict, periods: list[dict], negotiation: dict | None = None) -> dict:
    reference = card["reference_solution"]["per_period"]
    checks = {check["id"]: check for check in card["diagnostic_checks"]}
    violations = cell.get("violations") or []
    by_period = {int(row["period"]): row for row in periods}
    result: dict[str, dict] = {}

    first = by_period.get(1)
    latest = checks["D1_orders_in_time"]["reference"]["latest_order_day"]
    if first is None:
        result["D1"] = {"verdict": "not evaluable", "why": "no period-1 row"}
    else:
        short = any("minimum_service_not_met" in v for v in first.get("violations") or [])
        ok = first["decision"] == "award" and not short
        result["D1"] = {
            "verdict": "pass" if ok else "fail",
            "why": f"period 1 {first['decision']} on day {first['elapsed_days']} (latest {latest})"
            + ("; minimum service missed" if short else ""),
        }

    mismatched = []
    for ref in reference:
        row = by_period.get(ref["period"])
        chosen = sorted(row.get("awarded_supplier_ids") or []) if row else []
        if chosen != ref["suppliers"]:
            mismatched.append(f"p{ref['period']}: {', '.join(s.split('_')[-1] for s in chosen) or 'none'}")
    result["D2"] = {
        "verdict": "pass" if not mismatched else "fail",
        "why": "same suppliers as the reference every period" if not mismatched else "differs in " + "; ".join(mismatched),
    }

    if negotiation is None:
        # The tables carry only the count; whether a counter was accepted and used lives in the sealed events.
        result["D3"] = {
            "verdict": "not evaluable" if cell.get("counters") else "fail",
            "why": f"counters sent {cell.get('counters', 0)}; no sealed event log on this machine"
            if cell.get("counters")
            else "no counter-offer sent",
        }
    else:
        result["D3"] = {
            "verdict": "pass" if negotiation["award_lines_on_negotiated_offers"] else "fail",
            "why": f"{negotiation['sent']} counter-offers, {negotiation['accepted']} accepted, "
            f"{negotiation['award_lines_on_negotiated_offers']} award lines on a negotiated offer",
        }

    # A period never played delivers nothing, so it misses minimum service too.
    short = [v for v in violations if "minimum_service_not_met" in v or "episode_ended_before_period" in v]
    result["D4"] = {"verdict": "fail" if short else "pass", "why": ", ".join(short) or "every period met minimum service"}
    bad = [v for v in violations if any(code in v for code in EXECUTION_VIOLATIONS)]
    result["D5"] = {"verdict": "fail" if bad else "pass", "why": ", ".join(bad) or "no invalid action or award"}

    competent = checks["D6_beats_competent_rule"]["reference"]["deadline_aware_regret_usd"]
    regret = float(cell["regret_to_upper_bound_usd"])
    result["D6"] = {
        "verdict": "pass" if regret < competent else "fail",
        "why": f"regret {regret:.1f} vs deadline_aware {competent:.1f}",
    }
    return {"world_case_id": card["case_id"], "regret": regret, "checks": result, "periods": [
        {"period": p, "suppliers": sorted(by_period[p].get("awarded_supplier_ids") or []),
         "prices": {a["supplier_id"]: a["unit_price_usd"] for a in by_period[p].get("awarded") or []},
         "decision": by_period[p]["decision"], "day": by_period[p].get("elapsed_days")}
        for p in sorted(by_period)
    ]}


def extra_checkouts() -> list[Path]:
    """The other checkouts this build reads: roots.json, which build_general_examiner.py rewrites from
    AEREAD_EXAMINER_EXTRA_CHECKOUTS on every catalog build, and roots.local.json, which nothing rewrites
    (checkouts that carry only derived analyses, such as gap bundles). Both are local and never published."""
    out: list[Path] = []
    for name in ("roots.json", "roots.local.json"):
        path = Path(__file__).with_name(name)
        if path.exists():
            out += [Path(p) for p in json.loads(path.read_text(encoding="utf-8")).values() if Path(p).is_dir() and Path(p) not in out]
    return out


def payoff_comparisons(checkouts: list[Path]) -> dict:
    """Paired payoff comparisons published as derived bundles (the Housing lemons v2 pair): per model and per
    world, the tenants' net payoff as realized and with each uninspected signing counted at its expected value.
    Keyed by the comparison bundle and by both compared runs, so each of their pages shows the chart."""
    out: dict = {}
    seen: set = set()
    for root in checkouts:
        for path in sorted(root.glob("evidence/**/reports/comparison.json")):
            report = json.loads(path.read_text(encoding="utf-8"))
            if not str(report.get("schema_version", "")).startswith("aeread.housing_lemons_comparison/"):
                continue
            bundle = path.parent.parent.name
            if bundle in seen:
                continue
            seen.add(bundle)

            def model(campaign_id: str) -> str:
                try:
                    return json.loads((root / "configs" / f"{campaign_id}.json").read_text(encoding="utf-8"))["route"]["requested_model"]
                except (OSError, KeyError, ValueError):
                    return campaign_id

            overall = report["slices"]["overall"]
            labels = {"tenant_net_payoff": "as realized", "expected_net_payoff": "blind signings at expected value (luck removed)"}
            metrics = [
                {"key": key, "label": labels[key],
                 "left": {"mean": overall[key]["left_mean"], "ci": overall[key].get("left_ci95")},
                 "right": {"mean": overall[key]["right_mean"], "ci": overall[key].get("right_ci95")},
                 "difference": overall[key]["difference"], "difference_ci": overall[key]["difference_ci95"],
                 "worlds_left_higher": overall[key]["worlds_left_higher"], "worlds_right_higher": overall[key]["worlds_right_higher"]}
                for key in labels if key in overall
            ]
            worlds = [
                {"world": w["world_seed"], "stratum": w["stratum"],
                 "left": w["tenant_net_payoff"]["left"], "right": w["tenant_net_payoff"]["right"],
                 "left_expected": (w.get("expected_net_payoff") or {}).get("left"),
                 "right_expected": (w.get("expected_net_payoff") or {}).get("right"),
                 "left_spread": (w.get("tenant_net_payoff_spread") or {}).get("left"),
                 "right_spread": (w.get("tenant_net_payoff_spread") or {}).get("right"),
                 "left_cells": w["cells"]["left"], "right_cells": w["cells"]["right"]}
                for w in report["worlds"]
            ]
            entry = {
                "kind": "paired", "source": "published", "endpoint": "tenant_net_payoff",
                "comparison_id": bundle, "left_id": report["left"], "right_id": report["right"],
                "left_model": model(report["left"]), "right_model": model(report["right"]),
                "paired_worlds": report["paired_worlds"], "incomplete_packs": report.get("incomplete_packs") or {},
                "metrics": metrics, "worlds": worlds,
                "benchmarks": {k: overall[k] for k in ("reference_total", "sign_anything_total", "oracle_total") if k in overall},
                "claim_scope": "descriptive, 24 worlds on one pack; each cell is a market of one model's six tenants; no ranking",
            }
            for key in (bundle, report["left"], report["right"]):
                out[key] = entry
    return out


#: Contract keys that name the model or the identity rather than the experiment; two contracts equal
#: apart from these are twins, the same experiment run on different models.
_ROUTE_KEYS = {"route", "routes", "campaign_id", "question", "title", "description", "notes", "model", "models",
               "profiles", "pricing", "created", "created_date"}


def _experiment(value):
    if isinstance(value, dict):
        return {k: _experiment(v) for k, v in value.items()
                if k not in _ROUTE_KEYS and not k.endswith("_profile_id") and "route" not in k}
    if isinstance(value, list):
        return [_experiment(v) for v in value]
    return value


def _world_boot(values: dict, seed: int, draws: int = 10_000):
    import random as _random
    worlds = sorted(values)
    if len(worlds) < 2:
        return None
    rng = _random.Random(seed)
    means = sorted(sum(values[worlds[rng.randrange(len(worlds))]] for _ in worlds) / len(worlds) for _ in range(draws))
    return [means[int(0.025 * draws)], means[int(0.975 * draws) - 1]]


def gap_reports(roots: list[Path]) -> dict:
    """Why two paired runs differ, or why a run falls short of a reference, as published by derived bundles in the
    family-agnostic shape ``aeread.gap_decomposition``: realized gap, additive components, decision classes and their
    instances, and, when the bundle publishes a contributions table, every part down to the steps behind it.
    A bundle may hold several reports (``reports/gap_decomposition*.json``, e.g. one per model against an answer
    key). Each is keyed by the bundle (and its suffix); every run it covers lists it under ``refs``, except a
    reference that several reports share."""
    out: dict = {}
    for root in roots:
        for path in sorted(root.glob("evidence/**/reports/gap_decomposition*.json")):
            report = json.loads(path.read_text(encoding="utf-8"))
            if not str(report.get("schema_version", "")).startswith("aeread.gap_decomposition/"):
                continue
            bundle = path.parent.parent.name
            suffix = path.stem[len("gap_decomposition"):].lstrip("_")
            key = f"{bundle}/{suffix}" if suffix else bundle
            if key in out:
                continue
            entry = {**report, "gap_id": bundle, "gap_key": key}
            declared = (report.get("contributions") or {}).get("table") or "tables/contributions.jsonl"
            table = path.parent.parent / declared
            if report.get("cell_parts") and table.exists():
                # every part down to its steps, once: rows point at cell_parts by index
                cell = {(c["campaign_id"], c["receipt_sha256"]): i for i, c in enumerate(report["cell_parts"])}
                keys = [c["key"] for c in report["components"]]
                rows = [json.loads(line) for line in table.read_text(encoding="utf-8").splitlines() if line.strip()]
                entry["contribution_rows"] = {
                    "columns": ["cell", "component", "amount", "round", "phase", "seat", "note", "step", "listing"],
                    "rows": [[cell[(r["campaign_id"], r["receipt_sha256"])], keys.index(r["component"]), r["amount"], r.get("round_index"),
                              r["phase_id"], r["seat_id"], r.get("note", ""), r.get("step_index"), r.get("listing_id")] for r in rows]}
            if isinstance(report.get("cell_parts"), list):
                _compact_cells(entry)
            out[key] = entry
            sides = [report.get("left")] + ([] if report.get("reference_side") == "right" else [report.get("right")])
            for run in dict.fromkeys(s for s in sides if s):
                refs = out.setdefault(run, {"refs": []}).setdefault("refs", [])
                if key not in refs:
                    refs.append(key)
    return out


_CELL_FIELDS = ("side", "campaign_id", "receipt_sha256", "world_seed", "replicate_index", "unit")


def _compact_cells(entry: dict) -> None:
    """Cells as columns, and instances pointing at their cell, so a report ships each receipt once; the page
    expands both (``gapNorm``)."""
    cells = entry["cell_parts"]
    keys = [c["key"] for c in entry["components"]]
    campaigns = sorted({c["campaign_id"] for c in cells})
    index = {(c["campaign_id"], c["receipt_sha256"]): i for i, c in enumerate(cells)}
    entry["cell_parts"] = {"compact": 1, "campaigns": campaigns, "keys": keys,
                           "columns": ["side", "campaign", "receipt", "world_seed", "replicate_index", "unit", "stratum", "parts"],
                           "rows": [[c["side"], campaigns.index(c["campaign_id"]), c["receipt_sha256"], c.get("world_seed"),
                                     c.get("replicate_index"), c.get("unit"), c.get("stratum"), [c["parts"][k] for k in keys]] for c in cells]}
    if isinstance(entry.get("instances"), list):
        rows = []
        for inst in entry["instances"]:
            at = index.get((inst.get("campaign_id"), inst.get("receipt_sha256")))
            rows.append(inst if at is None else {**{k: v for k, v in inst.items() if k not in _CELL_FIELDS}, "cell": at})
        entry["instances"] = {"compact": 1, "rows": rows}


def twin_comparisons(roots: list[Path], already: set) -> dict:
    """A comparison for every published pair of identities whose contracts are equal except for the model,
    when no published comparison covers them: the declared primary estimand, averaged per world over completed
    cells, paired by world, with world-bootstrap intervals. Computed by the examiner, and labelled so."""
    import itertools
    bundles: dict = {}
    for root in roots:
        for cfg in sorted(root.glob("configs/*.json")):
            cid = cfg.stem
            found = [p.parent for p in root.glob(f"evidence/**/{cid}/tables/cells.jsonl")]
            if not found or cid in bundles:
                continue
            try:
                contract = json.loads(cfg.read_text(encoding="utf-8"))
                design = json.loads((found[0].parent / "reports" / "design.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            estimand = design.get("primary_estimand")
            model = ((contract.get("route") or {}).get("requested_model")) or ((contract.get("route") or {}).get("route_id"))
            if estimand and model:
                bundles[cid] = {"key": json.dumps(_experiment(contract), sort_keys=True), "dir": found[0].parent,
                                "estimand": estimand, "model": model}
    groups: dict = {}
    for cid, b in bundles.items():
        groups.setdefault((b["key"], b["estimand"]), []).append(cid)
    out: dict = {}
    for (_, estimand), ids in groups.items():
        for left, right in itertools.combinations(sorted(ids), 2):
            if left in already or right in already or bundles[left]["model"] == bundles[right]["model"]:
                continue
            per = {}
            for cid in (left, right):
                rows = [json.loads(l) for l in (bundles[cid]["dir"] / "tables" / "cells.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
                if any(r.get("stage") == "variance_pilot" for r in rows):
                    rows = [r for r in rows if r.get("stage") == "variance_pilot"]
                worlds: dict = {}
                for r in rows:
                    world = r.get("world_seed", r.get("slug", r.get("case_id")))
                    if r.get("status") == "completed" and isinstance(r.get(estimand), (int, float)) and world is not None:
                        worlds.setdefault(world, []).append(float(r[estimand]))
                per[cid] = worlds
            paired = sorted(set(per[left]) & set(per[right]), key=str)
            if len(paired) < 2:
                continue
            mean = lambda xs: sum(xs) / len(xs)
            lm = {w: mean(per[left][w]) for w in paired}
            rm = {w: mean(per[right][w]) for w in paired}
            diff = {w: lm[w] - rm[w] for w in paired}
            entry = {
                "kind": "paired", "source": "examiner", "comparison_id": None, "left_id": left, "right_id": right,
                "left_model": bundles[left]["model"], "right_model": bundles[right]["model"],
                "paired_worlds": len(paired), "incomplete_packs": {},
                "metrics": [{
                    "key": estimand, "label": "as realized",
                    "left": {"mean": mean(list(lm.values())), "ci": _world_boot(lm, 20260925)},
                    "right": {"mean": mean(list(rm.values())), "ci": _world_boot(rm, 20260926)},
                    "difference": mean(list(diff.values())), "difference_ci": _world_boot(diff, 20260927),
                    "worlds_left_higher": sum(1 for v in diff.values() if v > 0),
                    "worlds_right_higher": sum(1 for v in diff.values() if v < 0),
                }],
                "worlds": [{"world": w, "stratum": "", "left": lm[w], "right": rm[w],
                            "left_spread": [min(per[left][w]), max(per[left][w])],
                            "right_spread": [min(per[right][w]), max(per[right][w])],
                            "left_cells": len(per[left][w]), "right_cells": len(per[right][w])} for w in paired],
                "benchmarks": {},
                "claim_scope": (f"computed by the examiner from the two bundles' cells tables on their declared primary "
                                f"estimand ({estimand}); descriptive; neither bundle publishes this comparison"),
                "endpoint": estimand,
            }
            out[left] = out[right] = entry
    return out


def main(out: Path, checkout: Path, receipt_index: Path | None = None) -> None:
    index = json.loads(receipt_index.read_text(encoding="utf-8")) if receipt_index and receipt_index.exists() else {}
    cards: dict[str, dict] = {}
    prompts: dict[str, dict] = {}
    for path in sorted(checkout.glob("docs/families/*/case_cards/*.json")):
        pack = json.loads(path.read_text(encoding="utf-8"))
        if pack.get("prompt"):
            prompts[pack["pack"]] = pack["prompt"]
        for card in pack["worlds"]:
            cards[card["case_id"]] = card
    prose: dict[str, dict] = {}
    for path in sorted(checkout.glob("docs/families/*/case_cards.md")):
        prose.update(sections(path.read_text(encoding="utf-8")))
    evaluations: dict[str, dict] = {}
    bundles = 0
    for cells_path in sorted(checkout.glob("evidence/**/tables/cells.jsonl")):
        rows = [json.loads(line) for line in cells_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not any(row.get("world_case_id") in cards for row in rows):
            continue
        bundles += 1
        periods_path = cells_path.with_name("periods.jsonl")
        periods: dict[str, list[dict]] = {}
        if periods_path.exists():
            for line in periods_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    periods.setdefault(row["case_id"], []).append(row)
        for row in rows:
            card = cards.get(row.get("world_case_id"))
            if card is None or row.get("status") != "completed" or not row.get("receipt_sha256"):
                continue
            dirs = index.get(row["receipt_sha256"]) or []
            negotiation = negotiation_events(Path(dirs[0])) if dirs else None
            evaluations[row["receipt_sha256"]] = evaluate(card, row, periods.get(row["case_id"], []), negotiation)
            evaluations[row["receipt_sha256"]]["seed"] = row.get("seed")
    # Pre-registered confirmatory reports, keyed by the bundle (campaign) directory name.
    confirmatory = {
        path.parent.parent.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(checkout.glob("evidence/**/reports/confirmatory_vs_*.json"))
    }
    # Model comparisons: every bundle that publishes a paired comparison report against another bundle.
    comparisons = {}
    def cells_of(bundle_dir: Path) -> list[dict]:
        path = bundle_dir / "tables" / "cells.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for path in sorted(checkout.glob("evidence/**/reports/comparison_vs_*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        left_dir = path.parent.parent
        right_dir = left_dir.parent / str(report.get("right_campaign_id"))
        left, right = cells_of(left_dir), cells_of(right_dir)
        if not left or not right:
            continue
        def per_world(rows):
            out: dict[str, dict] = {}
            for row in rows:
                if row.get("status") != "completed" or row.get("regret_to_upper_bound_usd") is None:
                    continue
                w = out.setdefault(row["slug"], {"regrets": [], "breaches": 0, "flags": []})
                w["flags"].append(1.0 if row.get("violations") else 0.0)
                w["regrets"].append(float(row["regret_to_upper_bound_usd"]))
                w["breaches"] += bool(row.get("violations"))
            return out
        lw, rw = per_world(left), per_world(right)
        worlds = []
        for slug in sorted(set(lw) & set(rw)):
            worlds.append({
                "world": slug,
                "left_regret": sum(lw[slug]["regrets"]) / len(lw[slug]["regrets"]),
                "right_regret": sum(rw[slug]["regrets"]) / len(rw[slug]["regrets"]),
                "left_breach_rate": lw[slug]["breaches"] / len(lw[slug]["regrets"]),
                "right_breach_rate": rw[slug]["breaches"] / len(rw[slug]["regrets"]),
                "left_cells": len(lw[slug]["regrets"]), "right_cells": len(rw[slug]["regrets"]),
                # seed spread within the world (min-max), not an interval: a world has only 3-5 seeds
                "left_spread": [min(lw[slug]["regrets"]), max(lw[slug]["regrets"])],
                "right_spread": [min(rw[slug]["regrets"]), max(rw[slug]["regrets"])],
            })
        import random as _random
        def world_boot(per_world_values: dict, resamples: int = 10_000, seed: int = 20260924):
            """Mean of per-world means, with a 95% world-clustered bootstrap interval (the world is the unit)."""
            worlds = sorted(k for k, v in per_world_values.items() if v)
            if not worlds:
                return None, [None, None]
            means = {k: sum(v) / len(v) for k, v in per_world_values.items() if v}
            rng = _random.Random(seed)
            draws = sorted(sum(means[worlds[rng.randrange(len(worlds))]] for _ in worlds) / len(worlds) for _ in range(resamples))
            return sum(means.values()) / len(means), [draws[int(0.025 * resamples)], draws[int(0.975 * resamples) - 1]]
        def overall(side):
            pw = lw if side == "left" else rw
            rows = [r for r in (left if side == "left" else right) if r.get("status") == "completed" and r.get("regret_to_upper_bound_usd") is not None]
            regret, regret_ci = world_boot({k: v["regrets"] for k, v in pw.items()})
            breach, breach_ci = world_boot({k: v["flags"] for k, v in pw.items()})
            return {"cells": len(rows), "worlds": len(pw), "mean_regret": regret, "mean_regret_ci": regret_ci,
                    "breach_rate": breach, "breach_rate_ci": breach_ci}
        comparisons[left_dir.name] = {
            "left_id": left_dir.name, "right_id": right_dir.name,
            "left_model": report.get("left_route"), "right_model": report.get("right_route"),
            "left": overall("left"), "right": overall("right"),
            "paired_cells": report.get("paired_cells"),
            "delta_mean": report.get("mean_regret_delta_usd"), "delta_interval": report.get("mean_regret_delta_usd_95_world_bootstrap"),
            "claim_scope": report.get("claim_scope"), "worlds": worlds,
        }
    roots = [checkout, *extra_checkouts()]
    comparisons.update(payoff_comparisons(roots))
    comparisons.update(twin_comparisons(roots, set(comparisons)))
    gaps = gap_reports(roots)
    data = {
        "comparisons": comparisons,
        "gaps": gaps,
        "cards": cards,
        "strata": {key: value for key, value in prose.items() if "-" in key and key.replace("-", "_") in {c["stratum"] for c in cards.values()}},
        "common": {key: value for key, value in prose.items() if key in ("How to read a cell", "Common to every world", "Known limits")},
        "evaluations": evaluations,
        "prompts": prompts,
        "confirmatory": confirmatory,
    }
    (out / "data").mkdir(parents=True, exist_ok=True)
    # the same gzip+base64 envelope as the other data files (getJSON inflates it); mtime 0 keeps the bytes reproducible
    raw = json.dumps(data, sort_keys=True).encode("utf-8")
    envelope = {"encoding": "gzip+base64", "raw_bytes": len(raw), "payload": base64.b64encode(gzip.compress(raw, 9, mtime=0)).decode()}
    (out / "data" / "case_cards.json").write_text(json.dumps(envelope, separators=(",", ":")), encoding="utf-8")
    print(f"case cards: {len(cards)} worlds, {len(data['strata'])} strata, {len(evaluations)} cells evaluated in {bundles} bundles")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]) if len(sys.argv) > 3 else None)
