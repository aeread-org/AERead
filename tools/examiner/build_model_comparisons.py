"""Model comparisons for the examiner: every case that ran more than one model, as one table per case, by stratum.

    python3 build_model_comparisons.py <out dir> <AERead checkout>

Reads the checkout and the extra checkouts in roots.json, and the catalog the earlier steps wrote
(`<out>/data/catalog.json`) so only catalogued bundles are used. Writes `data/model_comparisons.json`.

A case becomes one comparison set: the models that played it, its independent unit (the world, or the
case when seeds only repeat one prompt), the strata the design fixes before any model acts (world type,
seat, reasoning effort, the model on the other side, market difficulty), and every measure the bundles
publish per cell, with the direction that counts as better. The page computes each stratum's paired
comparison from these cells, so any stratification and any pair of models can be chosen there.

Each adapter reads one published layout. A multi-model case no adapter can read is listed with the reason,
so the page states what is not compared rather than leaving it out silently.
"""

from __future__ import annotations

import base64
import csv
import gzip
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HIDDEN_FAMILIES = {"datacenter_development_terms", "commercial_state_calibration", "procurement_grounding"}

# canonical model key and label; the route or provider stays on the set as `routes`
MODELS = [
    (r"gemini.?3\.?8.?flash", "gemini-3.8-flash", "Gemini 3.8 Flash"),
    (r"gemini.?2\.?5.?flash.?lite", "gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite"),
    (r"glm.?5?\.?3", "glm-5.3-flash", "GLM 5.3 Flash"),
    (r"deepseek.?v4.?flash", "deepseek-v4-flash", "DeepSeek V4 Flash"),
    (r"gpt.?5\.?6.?luna", "gpt-5.6-luna", "GPT 5.6 Luna"),
    (r"grok.?4\.?3", "grok-4.3", "Grok 4.3"),
    (r"mistral.?(small.?)?3\.?2|mistral32", "mistral-small-3.2", "Mistral Small 3.2"),
    (r"mistral.?small.?4|mistral_small4|mistral-small-2603", "mistral-small-2603", "Mistral Small 4 (2603)"),
    (r"qwen3.?235b", "qwen3-235b-a22b", "Qwen3 235B A22B"),
    (r"qwen3.?30b", "qwen3-30b-a3b", "Qwen3 30B A3B"),
]


def model_of(route: str) -> tuple[str, str]:
    for pattern, key, label in MODELS:
        if re.search(pattern, route, re.I):
            return key, label
    return route, route


def pretty(value: str) -> str:
    """A stratum value as a label: ids read as words; a value that is already a label is kept."""
    value = str(value)
    return value if re.search(r"[A-Z]", value) else value.replace("_", " ").strip().capitalize()


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def num(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class Set:
    """One comparison set: cells as rows of unit, model, replicate, stratum values and measure values."""

    def __init__(self, sid: str, family: str, title: str, campaigns: list[str], unit: dict, dims: list[dict],
                 measures: list[dict], scope: str, what: str):
        self.sid, self.family, self.title, self.campaigns = sid, family, title, campaigns
        self.unit, self.dims, self.measures, self.scope, self.what = unit, dims, measures, scope, what
        self.rows: list[list] = []
        self.models: dict[str, str] = {}
        self.routes: dict[str, set] = defaultdict(set)
        self.missing: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.clusters: dict[str, str] = {}   # unit -> independent cluster, where they differ (a world and its twin)
        self.matched = True                  # replicate keys mean the same draw for every model

    def add(self, unit, route: str, rep, strata: dict, values: dict | None, reason: str | None = None):
        key, label = model_of(route)
        self.models[key] = label
        self.routes[key].add(route)
        if values is None:
            self.missing[key][str(reason or "not completed")] += 1
            return
        self.rows.append([str(unit), key, str(rep)] + [str(strata.get(d["key"], "")) for d in self.dims]
                         + [values.get(m["key"]) for m in self.measures])

    def out(self) -> dict | None:
        """The set as the page reads it, or None when fewer than two models completed a cell. A stratum with a
        single value is dropped (it splits nothing), and so is a measure no cell carries."""
        if len({r[1] for r in self.rows}) < 2:
            return None
        n = len(self.dims)
        dims, fixed = [], []
        for i, d in enumerate(self.dims):
            seen = {r[3 + i] for r in self.rows}
            if len(seen) < 2:
                # a stratum with one value splits nothing, but it still names what every cell shares
                v = next(iter(seen), "")
                if v:
                    fixed.append({"label": d["label"], "value": next((x["label"] for x in d.get("values", []) if x["v"] == v), pretty(v))})
                continue
            known = [v for v in d.get("values", []) if v["v"] in seen]
            extra = [{"v": v, "label": pretty(v)} for v in sorted(seen - {v["v"] for v in known})]
            dims.append((i, {**d, "values": known + extra}))
        measures = [(j, m) for j, m in enumerate(self.measures) if any(r[3 + n + j] is not None for r in self.rows)]
        return {
            "id": self.sid, "family": self.family, "title": self.title, "campaigns": self.campaigns,
            "what": self.what, "scope": self.scope, "unit": self.unit,
            "models": [{"key": k, "label": v, "routes": sorted(self.routes[k])} for k, v in sorted(self.models.items(), key=lambda kv: kv[1])],
            "dims": [d for _, d in dims], "measures": [m for _, m in measures],
            "cols": ["unit", "model", "rep"] + [d["key"] for _, d in dims] + [m["key"] for _, m in measures],
            "rows": [r[:3] + [r[3 + i] for i, _ in dims] + [r[3 + n + j] for j, _ in measures] for r in self.rows],
            "missing": {k: dict(v) for k, v in self.missing.items()},
            "clusters": self.clusters, "matched": self.matched, "fixed": fixed,
        }


def M(key, label, better, unit="", note="", primary=False, own_cells=False):
    """A measure. `own_cells`: compare each model's own cells rather than matched replicates, for a measure that
    conditions on an outcome the model controls (matching would drop the other model's cells on those draws)."""
    return {"key": key, "label": label, "better": better, "unit": unit, "note": note, "primary": primary, "own_cells": own_cells}


# ---------------------------------------------------------------------------------------------- adapters


def procurement_pairs(roots, catalog, strata_prose) -> list[Set]:
    """Repeated-sourcing pairs published as comparison_vs_*.json: each world is one generated or curated
    procurement world; its type (demand ramp, retaliation trap, ...) is fixed by the pack before the buyer acts."""
    out, seen = [], set()
    for root in roots:
        for path in sorted(root.glob("evidence/**/reports/comparison_vs_*.json")):
            report = json.loads(path.read_text(encoding="utf-8"))
            left_dir = path.parent.parent
            right_dir = left_dir.parent / str(report.get("right_campaign_id"))
            pair = tuple(sorted((left_dir.name, right_dir.name)))
            if pair in seen or not all(p in catalog for p in pair) or not (right_dir / "tables" / "cells.jsonl").exists():
                continue
            seen.add(pair)
            name = left_dir.name
            kind = ("pre-registered holdout" if "holdout" in name else "generated development worlds" if "dev2" in name
                    else "curated worlds")
            s = Set(f"procurement::{pair[0]}", "procurement_allocation", f"Repeated sourcing · {kind}", list(pair),
                    {"key": "world", "label": "world", "note": "one procurement world; its seeds repeat it"},
                    [{"key": "world_type", "label": "World type", "note": "fixed by the world pack before the buyer acts",
                      "values": []}],
                    [M("regret_to_upper_bound_usd", "Regret to the upper bound", "lower", "USD", primary=True),
                     M("breach", "Breach: any violation (missed service, invalid award)", "lower", "rate"),
                     M("regret_valid", "Regret, cells without a breach only", "lower", "USD",
                       "conditions on an outcome the buyer controls: compare with the breach rate beside it", own_cells=True),
                     M("advantage_over_myopic_usd", "Advantage over the myopic rule", "higher", "USD"),
                     M("contribution_margin_usd", "Contribution margin", "higher", "USD"),
                     M("feasible_award", "Feasible award", "higher", "rate"),
                     M("switches", "Supplier switches", None, "count"),
                     M("counters", "Counter-offers sent", None, "count"),
                     M("inquiries", "Inquiries", None, "count")],
                    report.get("claim_scope") or "paired descriptive contrast; no ranking",
                    "The buyer seat, played by each model on the same worlds and seeds.")
            for bundle_dir, route in ((left_dir, report.get("left_route")), (right_dir, report.get("right_route"))):
                for r in jsonl(bundle_dir / "tables" / "cells.jsonl"):
                    slug = r.get("slug") or r.get("case_id")
                    wtype = re.sub(r"_\d+$", "", str(slug))
                    ok = r.get("status") == "completed" and r.get("regret_to_upper_bound_usd") is not None
                    breach = 1.0 if r.get("violations") else 0.0
                    vals = None if not ok else {
                        "regret_to_upper_bound_usd": num(r["regret_to_upper_bound_usd"]), "breach": breach,
                        "regret_valid": num(r["regret_to_upper_bound_usd"]) if not breach else None,
                        "advantage_over_myopic_usd": num(r.get("advantage_over_myopic_usd")),
                        "contribution_margin_usd": num(r.get("contribution_margin_usd")),
                        "feasible_award": num(r.get("feasible_award")), "switches": num(r.get("switches")),
                        "counters": num(r.get("counters")), "inquiries": num(r.get("inquiries"))}
                    s.add(slug, route, r.get("seed"), {"world_type": wtype}, vals,
                          None if ok else (r.get("failure_code") or r.get("status") or "not completed"))
            wt = s.dims[0]
            for v in sorted({row[3] for row in s.rows}):
                prose = strata_prose.get(v.replace("_", "-")) or {}
                wt["values"].append({"v": v, "label": pretty(v), "note": " ".join((prose.get("paragraphs") or [])[:1])})
            out.append(s)
    return out


def procurement_published_pairs(roots, catalog) -> list[Set]:
    """Older procurement pairs published only as reports/paired_model_comparison.json (cell pairs inside)."""
    out = []
    for root in roots:
        for path in sorted(root.glob("evidence/**/reports/paired_model_comparison.json")):
            report = json.loads(path.read_text(encoding="utf-8"))
            left, right = report.get("baseline_campaign_id"), report.get("campaign_id")
            if left not in catalog or right not in catalog:
                continue
            sides = [k for k in report["pairs"][0] if isinstance(report["pairs"][0][k], dict) and not k.startswith("effects")]
            s = Set(f"procurement::{right}", "procurement_allocation", "Single-order allocation · six curated worlds",
                    [left, right], {"key": "world", "label": "world", "note": "one curated world; three seeds repeat it"},
                    [{"key": "world_type", "label": "World", "note": "one curated world each", "values": []}],
                    [M("regret_to_upper_bound_usd", "Regret to the upper bound", "lower", "USD", primary=True),
                     M("feasible", "Feasible award", "higher", "rate"),
                     M("contribution_margin_usd", "Contribution margin", "higher", "USD"),
                     M("completed_kits", "Completed kits", "higher", "count")],
                    report.get("claim_scope", ""), "The buyer seat, played by each model on the same worlds and seeds.")
            routes = {"glm": "glm-5.3-flash", "qwen": "qwen3-30b-a3b"}
            for p in report["pairs"]:
                case = p["case_id"].split(".")[-1]
                for side in sides:
                    s.add(case, routes.get(side, side), p.get("inference_seed"), {"world_type": case},
                          {k: num(v) for k, v in p[side].items()})
            out.append(s)
    return out


def lemons_pairs(roots, catalog) -> list[Set]:
    """Housing lemons: tenants are the model; landlords are scripted. The favourite listing being a lemon or
    sound is drawn by the world generator before any tenant acts."""
    out, seen = [], set()
    for root in roots:
        for path in sorted(root.glob("evidence/**/reports/comparison.json")):
            report = json.loads(path.read_text(encoding="utf-8"))
            if not str(report.get("schema_version", "")).startswith("aeread.housing_lemons_comparison/"):
                continue
            left, right = report["left"], report["right"]
            if (left, right) in seen or left not in catalog or right not in catalog:
                continue
            seen.add((left, right))
            s = Set(f"housing::{left}", "housing", "Lemons market · tenants", [left, right],
                    {"key": "world", "label": "world", "note": "one generated market; two seeds repeat it"},
                    [{"key": "favourite", "label": "Favourite listing", "note": "drawn by the world generator before any tenant acts",
                      "values": [{"v": "favourite_is_lemon", "label": "is a lemon", "note": "the listing most tenants rank first is a lemon"},
                                 {"v": "favourite_is_sound", "label": "is sound", "note": "the listing most tenants rank first is sound"}]}],
                    [M("tenant_net_payoff", "Tenants' net payoff per market, as realized", "higher", "USD", primary=True),
                     M("expected_net_payoff", "Tenants' net payoff, luck removed", "higher", "USD",
                       "each lease signed without inspecting counted at its expected value (HL-J-01); one value per world"),
                     M("within_case_score", "Within-case score (0 = pass, 1 = oracle)", "higher", "ratio"),
                     M("lemon_signings", "Lemons signed", "lower", "count"),
                     M("uninspected_lemon_signings", "Lemons signed without inspecting", "lower", "count"),
                     M("abstention_correctness_rate", "Correct abstentions", "higher", "rate"),
                     M("ir_violation_count", "Signings below the tenant's own value", "lower", "count"),
                     M("wasted_contacts", "Wasted contacts", "lower", "count"),
                     M("inspection_count", "Inspections", None, "count")],
                    "descriptive, one pack; each cell is a market of one model's six tenants; no ranking",
                    "Six tenant seats per market, all played by one model; landlords are scripted.")

            def route(cid):
                try:
                    return json.loads((root / "configs" / f"{cid}.json").read_text(encoding="utf-8"))["route"]["requested_model"]
                except (OSError, KeyError, ValueError):
                    return cid
            keys = ["tenant_net_payoff", "within_case_score", "lemon_signings", "uninspected_lemon_signings",
                    "abstention_correctness_rate", "ir_violation_count", "wasted_contacts", "inspection_count"]
            for cid in (left, right):
                cells = next(iter(root.glob(f"evidence/**/{cid}/tables/cells.jsonl")), None)
                if cells is None:
                    continue
                for r in jsonl(cells):
                    if r.get("stage") != "variance_pilot":
                        continue
                    ok = r.get("status") == "completed" and r.get("tenant_net_payoff") is not None
                    s.add(r["world_seed"], route(cid), r.get("replicate_index"), {"favourite": r.get("stratum")},
                          {k: num(r.get(k)) for k in keys} if ok else None, None if ok else (r.get("failure_type") or r.get("status")))
            for w in report["worlds"]:
                exp = w.get("expected_net_payoff") or {}
                for side, cid in (("left", left), ("right", right)):
                    if exp.get(side) is not None:
                        s.add(w["world_seed"], route(cid), "luck removed", {"favourite": w["stratum"]}, {"expected_net_payoff": exp[side]})
            out.append(s)
    return out


ARM_LABELS = {"one_price_low": "one price, low reasoning effort", "one_price_default": "one price, default reasoning",
              "two_prices_low": "two prices, low reasoning effort", "low_effort": "low reasoning effort",
              "default_reasoning": "default reasoning"}
SEAT_LABELS = {"client": "client (buys the build)", "integrator": "integrator (builds it)"}


def world_cluster(world: str) -> str:
    return re.sub(r"_twin$", "", str(world))


PLAYBOOK_LABELS = {"coordination": "coordination (client buys the hardware, integrator carries nothing)",
                   "managed": "managed (integrator procures and pays the fix)",
                   "turnkey": "turnkey (all in, damages, paid on delivery)"}


def risk_allocation_title(cid: str) -> str:
    version = cid.rsplit("_", 1)[-1]
    if "menu" in cid:
        return f"Risk allocation · client reads a posted playbook menu ({version})"
    if "contracts" in cid:
        return f"Risk allocation · client negotiates the full contract terms ({version})"
    return f"Risk allocation · one seat vs a scripted counterpart ({version})"


def risk_allocation(roots, catalog) -> list[Set]:
    """Datacenter risk allocation, one-sided: the model plays one seat against a scripted counterpart. Seat,
    reasoning arm and (in the menu and full-terms cases) the integrator's posted playbook are fixed by the design;
    a world and its twin form one cluster."""
    out = []
    for root in roots:
        for cells in sorted(root.glob("evidence/datacenter_development/*/tables/cells.jsonl")):
            cid = cells.parent.parent.name
            if cid not in catalog or "two_sided" in cid:
                continue
            rows = jsonl(cells)
            if not rows or not {"route_id", "arm", "decision_regret"} <= set(rows[0]):
                continue
            s = Set(f"datacenter::{cid}", "datacenter_development", risk_allocation_title(cid),
                    [cid], {"key": "world", "label": "world", "note": "a generated world; a twin world shares its cluster for the interval"},
                    [{"key": "seat", "label": "Seat", "note": "which side of the contract the model negotiates",
                      "values": [{"v": k, "label": v} for k, v in SEAT_LABELS.items()]},
                     {"key": "arm", "label": "Arm", "note": "prompt and reasoning setting, crossed with the other strata",
                      "values": [{"v": k, "label": v} for k, v in ARM_LABELS.items()]},
                     {"key": "playbook", "label": "Integrator's playbook", "note": "the offer the scripted integrator posts, set by its hidden costs before the client acts",
                      "values": [{"v": k, "label": v} for k, v in PLAYBOOK_LABELS.items()]},
                     {"key": "world_type", "label": "World type", "note": "the situation the generator builds", "values": [], "tally": False}],
                    [M("decision_regret", "Decision regret", "lower", "USD", "cost of the signed terms over the best the seat could have had", True),
                     M("first_move_regret", "Regret of the opening move", "lower", "USD"),
                     M("cost_over_best_attainable", "Realised cost over the best attainable", "lower", "USD"),
                     M("price_over_floor", "Price paid over the integrator's floor", "lower", "USD"),
                     M("signed_best_item", "Signed the item best for the client", "higher", "rate"),
                     M("signed_best_contract", "Signed the contract best for the client", "higher", "rate"),
                     M("allocation_gap", "Allocation gap", "lower", "USD", "value lost to the risk allocation alone"),
                     M("price_gap", "Price gap", "lower", "USD", "value lost to the price alone"),
                     M("switched_package", "Switched package after the opening", None, "rate"),
                     M("refused_rounds", "Rounds refused", None, "count"),
                     M("refused_counters", "Counters refused", None, "count")],
                    "development campaign; scripted counterpart; no ranking beyond these worlds",
                    "One seat played by the model, the other by a scripted counterpart; the same worlds for each model.")
            keys = [m["key"] for m in s.measures]
            for r in rows:
                if str(r["route_id"]).startswith("scripted"):
                    continue
                ok = r.get("valid") is True and r.get("decision_regret") is not None
                s.clusters[str(r["world"])] = world_cluster(r["world"])
                s.add(r["world"], r["route_id"], r.get("replicate_index", 0),
                      {"seat": r.get("seat", "client"), "arm": r["arm"], "playbook": r.get("playbook", ""), "world_type": r.get("world_cell")},
                      {k: num(r.get(k)) for k in keys} if ok else None,
                      None if ok else (r.get("invalid") or r.get("failure_cause") or r.get("receipt_status") or "invalid"))
            out.append(s)
    return out


def risk_allocation_two_sided(roots, catalog) -> list[Set]:
    """Two-sided risk allocation: both seats are models. Compared per seat, holding the other seat's model fixed."""
    out = []
    for root in roots:
        for cells in sorted(root.glob("evidence/datacenter_development/*two_sided*/tables/cells.jsonl")):
            cid = cells.parent.parent.name
            if cid not in catalog:
                continue
            rows = jsonl(cells)
            for seat, other in (("client", "integrator"), ("integrator", "client")):
                s = Set(f"datacenter::{cid}::{seat}", "datacenter_development", f"Risk allocation · two models negotiating · as {seat}",
                        [cid], {"key": "world", "label": "world", "note": "a generated world; a twin world shares its cluster for the interval"},
                        [{"key": "opponent", "label": f"{other.capitalize()} played by", "note": "the model on the other side, fixed per cell", "values": []},
                         {"key": "world_type", "label": "World type", "note": "the situation the generator builds", "values": [], "tally": False}],
                        [M(f"{seat}_surplus", f"{seat.capitalize()}'s surplus", "higher", "USD", primary=True),
                         M("joint_value_lost", "Joint value lost", "lower", "USD", "shared by both seats"),
                         M("efficient_contract_signed", "Efficient contract signed", "higher", "rate", "shared by both seats"),
                         M(f"{seat}_ir_violation", f"{seat.capitalize()} signed below its outside option", "lower", "rate"),
                         M(f"{seat}_share", f"{seat.capitalize()}'s share of the available surplus", "higher", "ratio")],
                        "development campaign; two models; no ranking beyond these worlds",
                        f"The {seat} seat, played by each model, against the same {other} model on the same worlds.")
                for r in rows:
                    me, them = r.get(f"{seat}_route"), r.get(f"{other}_route")
                    if not me or str(me).startswith("scripted") or str(them).startswith("scripted"):
                        continue
                    ok = r.get("valid") is True
                    vals = None
                    if ok:
                        vals = {f"{seat}_surplus": num(r.get(f"{seat}_surplus")), "joint_value_lost": num(r.get("joint_value_lost")),
                                "efficient_contract_signed": num(r.get("efficient_contract_signed")),
                                f"{seat}_ir_violation": num(r.get(f"{seat}_ir_violation"))}
                        share = num(r.get("client_share"))
                        vals[f"{seat}_share"] = share if seat == "client" or share is None else 1.0 - share
                    s.clusters[str(r["world"])] = world_cluster(r["world"])
                    s.add(r["world"], me, r.get("replicate_index", 0),
                          {"opponent": model_of(them)[1], "world_type": r.get("world_cell")}, vals,
                          None if ok else (r.get("invalid") or r.get("failure_cause") or "invalid"))
                out.append(s)
    return out


def refund(roots, catalog) -> list[Set]:
    """Refund V2.1: only the policy seat is a model. Each scenario is one fixed case; its twenty seeds repeat one
    prompt at temperature 0 (RF-D-01), so the scenario is the independent unit."""
    s = Set("refund::v2_1_controlled", "refund", "Refund V2.1 · policy seat", [],
            {"key": "scenario", "label": "scenario", "note": "one fixed case; its 20 seeds repeat one prompt at temperature 0 (RF-D-01)"},
            [{"key": "scenario_dim", "label": "Scenario", "note": "one case each", "values": []}],
            [M("policy_compliance", "Policy compliance", "higher", "rate", primary=True),
             M("transaction_correctness", "Transaction correctness", "higher", "rate"),
             M("coordination", "Coordination", "higher", "rate"),
             M("system_utility", "System utility", "higher", "points")],
            "descriptive fixed panel of six cases; no ranking",
            "The policy seat, played by each model; customer, intake and payments seats are scripted.")
    for root in roots:
        for table in sorted(root.glob("evidence/refund/*/tables/refund_results_by_scenario.csv")):
            cid = table.parent.parent.name
            if cid not in catalog or cid in s.campaigns:
                continue
            profiles = list(csv.DictReader((table.parent / "profiles.csv").open(encoding="utf-8")))
            policy = [p for p in profiles if "policy" in p["profile_id"] and "scripted" not in p["profile_id"]]
            if not policy:
                continue
            s.campaigns.append(cid)
            for r in csv.DictReader(table.open(encoding="utf-8")):
                ok = r["status"] == "ok" and r["inclusion_status"] == "included"
                s.add(r["scenario"], policy[0]["requested_model"], r["world_seed"], {"scenario_dim": r["scenario"]},
                      {k: num(r[k]) for k in ("policy_compliance", "transaction_correctness", "coordination", "system_utility")}
                      if ok else None, None if ok else r["status"])
    return [s]


def housing_runs(roots, catalog) -> list[Set]:
    """Housing markets where landlords and tenants are both models: compared per side, holding the other side's
    model fixed, within each market difficulty the contract declares."""
    out = []
    for root in roots:
        for by_run in sorted(root.glob("evidence/**/tables/by_run")):
            bundle = by_run.parent.parent
            cid = bundle.name
            if cid not in catalog:
                continue
            index = {}
            fact_index = bundle / "tables" / "canonical_fact_index.json"
            if fact_index.exists():
                runs = json.loads(fact_index.read_text(encoding="utf-8")).get("runs") or []
                index = {r["run_plan_id"]: r for r in runs if isinstance(r, dict)}
            difficulty = {}
            try:
                contract = json.loads((root / "configs" / f"{cid}.json").read_text(encoding="utf-8"))
                difficulty = {c["config_id"]: c.get("difficulty_stratum", c["config_id"]) for c in (contract.get("confirmatory_panel") or {}).get("configs") or []}
            except (OSError, ValueError, KeyError):
                pass
            cells = []
            for run_dir in sorted(by_run.iterdir()):
                results = run_dir / "benchmark_results.csv"
                if not results.exists():
                    continue
                side = {}
                for p in csv.DictReader((run_dir / "profiles.csv").open(encoding="utf-8")):
                    role = "landlord" if "landlord" in p["profile_id"] else "tenant" if "tenant" in p["profile_id"] else None
                    if role:
                        side[role] = p["requested_model"]
                config = (index.get(run_dir.name) or {}).get("config_id") or ""
                per = defaultdict(lambda: {"m": {}, "ok": True, "case": None})
                for r in csv.DictReader(results.open(encoding="utf-8")):
                    c = per[r["episode_attempt_id"]]
                    c["case"] = r["case_id"]
                    if r["inclusion_status"] != "included" or r["validity_status"] != "valid":
                        c["ok"] = False
                    v = num(r["value"])
                    if r["metric_role"] in ("metric", "primary") and r["metric_name"] in ("within_case_score", "social_welfare", "ir_violation_count", "wasted_contacts"):
                        c["m"][r["metric_name"]] = v
                    elif r["metric_role"] == "utility" and v is not None:
                        key = "landlord_utility" if r["seat_id"].startswith("landlord") else "tenant_utility"
                        c["m"][key] = c["m"].get(key, 0.0) + v
                for att, c in per.items():
                    cells.append((c["case"], att, side.get("landlord", "scripted"), side.get("tenant", "scripted"), config, c))
            for role, other in (("landlord", "tenant"), ("tenant", "landlord")):
                mine = {x[2] if role == "landlord" else x[3] for x in cells}
                if len({model_of(m)[0] for m in mine if m != "scripted"}) < 2:
                    continue
                s = Set(f"housing::{cid}::{role}", "housing", f"Housing market · models as {role}s ({cid.replace('housing_', '')})", [cid],
                        {"key": "world", "label": "world", "note": "one generated market; configurations and seeds vary within it"},
                        [{"key": "opponent", "label": f"{other.capitalize()}s played by", "note": "the model on the other side of the market", "values": []},
                         {"key": "difficulty", "label": "Market difficulty", "note": "the configuration the contract declares", "values": []}],
                        [M("within_case_score", "Within-case score (welfare between do-nothing 0 and the bound 1)", "higher", "ratio", primary=True),
                         M("social_welfare", "Social welfare", "higher", "points"),
                         M(f"{role}_utility", f"{role.capitalize()}s' total utility", "higher", "points", "the compared side's own payoff"),
                         M(f"{other}_utility", f"{other.capitalize()}s' total utility", None, "points", "the other side's payoff"),
                         M("ir_violation_count", "Deals below a party's own value", "lower", "count"),
                         M("wasted_contacts", "Wasted contacts", "lower", "count")],
                        "per-side comparison computed by the examiner; the family's own primary estimand averages seats and opponents",
                        f"All {role} seats played by one model, all {other} seats by one model; compared {role}-side, the {other} model held fixed.")
                s.matched = False
                for case, att, landlord, tenant, config, c in cells:
                    me, them = (landlord, tenant) if role == "landlord" else (tenant, landlord)
                    if me == "scripted":
                        continue
                    ok = c["ok"] and c["m"].get("within_case_score") is not None
                    s.add(case, me, att, {"opponent": model_of(them)[1] if them != "scripted" else "scripted",
                                          "difficulty": difficulty.get(config, config)}, c["m"] if ok else None,
                          None if ok else "excluded or invalid")
                out.append(s)
    return out


def shared_runner_long(roots, catalog) -> list[Set]:
    """Single-project datacenter diagnostics published in the shared runner's long table with a model column:
    one curated project, seeds repeat it, so there is one independent unit and no interval."""
    out = []
    skip = {"rate_limit", "provider_contract", "empty_response", "provider_rejected", "counteroffer_opportunity_count",
            "executed_agreement_count", "elapsed_seconds", "input_tokens", "cached_input_tokens", "output_tokens", "reported_cost_usd"}
    for root in roots:
        for table in sorted(root.glob("evidence/datacenter_development/*/tables/benchmark_results.csv")):
            cid = table.parent.parent.name
            if cid not in catalog:
                continue
            rows = list(csv.DictReader(table.open(encoding="utf-8")))
            if not rows or "model_id" not in rows[0]:
                continue
            dim = next((k for k in ("stage_id", "condition") if k in rows[0]), None)
            metric_key = "metric" if "metric" in rows[0] else "metric_name"
            metrics = sorted({r[metric_key] for r in rows if r.get("record_kind", "metric") != "status" and r[metric_key] not in skip})
            primary = next((m for m in ("counteroffer_adoption_rate", "safe_developer_objective_attainment", "developer_equity_npv", "score") if m in metrics), metrics[0] if metrics else None)
            if not primary:
                continue
            s = Set(f"datacenter::{cid}", "datacenter_development", f"Datacenter project · {cid.replace('datacenter_', '').replace('_', ' ')}", [cid],
                    {"key": "project", "label": "project", "note": "one curated project; its seeds repeat it, so no interval is possible"},
                    [{"key": "dim", "label": "Stage" if dim == "stage_id" else "Condition", "note": "set by the design before the model acts", "values": []}] if dim else [],
                    [M(m, pretty(m), None if m.endswith("_count") else "higher", "", primary=(m == primary)) for m in metrics],
                    "single curated project; diagnostic only", "The developer seat, played by each model on the same project.")
            requested = {}
            if (table.parent / "profiles.csv").exists():
                requested = {p["model_id"]: p["requested_model"] for p in csv.DictReader((table.parent / "profiles.csv").open(encoding="utf-8"))
                             if p.get("model_id") and p.get("requested_model")}
            per = defaultdict(dict)
            meta = {}
            for r in rows:
                key = r["cell_key"]
                meta[key] = (requested.get(r["model_id"], r["model_id"]), r.get(dim, "") if dim else "", r.get("inference_seed"), r["inclusion_status"])
                if r.get("record_kind", "metric") != "status" and r[metric_key] in metrics:
                    per[key][r[metric_key]] = num(r["value"])
            for key, (model, dv, seed, inc) in meta.items():
                ok = inc == "included" and per[key]
                s.add("project", model, seed, {"dim": dv}, per[key] if ok else None, None if ok else "excluded")
            out.append(s)
    return out


# ---------------------------------------------------------------------------------------------- main


def extra_checkouts() -> list[Path]:
    path = Path(__file__).with_name("roots.json")
    if not path.exists():
        return []
    return [Path(p) for p in json.loads(path.read_text(encoding="utf-8")).values() if Path(p).is_dir()]


def read_catalog(out: Path) -> dict:
    raw = json.loads((out / "data" / "catalog.json").read_text(encoding="utf-8"))
    if isinstance(raw, dict) and raw.get("encoding") == "gzip+base64":
        raw = json.loads(gzip.decompress(base64.b64decode(raw["payload"])))
    return raw


def strata_prose(checkout: Path) -> dict:
    sys.path.insert(0, str(Path(__file__).parent))
    from build_case_cards import sections  # noqa: E402
    prose = {}
    for path in sorted(checkout.glob("docs/families/*/case_cards.md")):
        prose.update(sections(path.read_text(encoding="utf-8")))
    return prose


def main(out: Path, checkout: Path) -> None:
    catalog = read_catalog(out)
    ids = {c["id"]: c for c in catalog["campaigns"] if c["family"] not in HIDDEN_FAMILIES}
    roots = [checkout, *[r for r in extra_checkouts() if r.resolve() != checkout.resolve()]]
    prose = strata_prose(checkout)
    for root in roots[1:]:
        prose.update({k: v for k, v in strata_prose(root).items() if k not in prose})
    built = []
    for adapter in (lambda: procurement_pairs(roots, ids, prose), lambda: procurement_published_pairs(roots, ids),
                    lambda: lemons_pairs(roots, ids), lambda: risk_allocation(roots, ids),
                    lambda: risk_allocation_two_sided(roots, ids), lambda: refund(roots, ids),
                    lambda: housing_runs(roots, ids), lambda: shared_runner_long(roots, ids)):
        for s in adapter():
            o = s.out()
            # the same bundle can sit in several checkouts; the first checkout read wins
            if o and o["id"] not in {b["id"] for b in built}:
                built.append(o)
    covered = {c for s in built for c in s["campaigns"]}
    # every catalogued campaign naming a model, grouped by stem, with the reason it is not compared
    uncovered = defaultdict(lambda: {"campaigns": [], "models": set()})
    for c in ids.values():
        # derived analyses (gap reports, comparison bundles) are not runs of a model
        if c["id"] in covered or re.search(r"_(gap|comparison)$", c["id"]):
            continue
        stem = re.sub(r"_(v\d+|\d{4}-\d{2}-\d{2})$", "", c.get("stem") or c["id"])
        names = set(c.get("models") or []) | {p for p in (c.get("grain") or {}).get("profile_ids", []) if "scripted" not in p}
        keys = {model_of(n)[1] for n in names if model_of(n)[0] != n}
        if not keys:
            continue
        u = uncovered[(c["family"], stem)]
        u["campaigns"].append(c["id"])
        u["models"] |= keys
    def has_cells(cid: str) -> bool:
        """A published per-cell table with at least one data row."""
        for root in roots:
            for bundle in root.glob(f"evidence/**/{cid}"):
                tables = [bundle / "tables" / t for t in ("cells.jsonl", "benchmark_results.csv", "refund_results_by_scenario.csv")]
                tables += list((bundle / "tables" / "by_run").glob("*/benchmark_results.csv"))
                if any(t.exists() and len(t.read_text(encoding="utf-8").strip().splitlines()) > 1 for t in tables):
                    return True
        return False

    stems = []
    for (family, stem), u in sorted(uncovered.items()):
        if len(u["models"]) < 2:
            reason = "one model only"
        elif not any(has_cells(c) for c in u["campaigns"]):
            reason = "no completed cells in a published per-cell table (qualification, admission or trajectory export only, or every cell failed)"
        else:
            reason = "each model ran under its own identity and no report pairs them on shared worlds"
        stems.append({"family": family, "stem": stem, "campaigns": sorted(u["campaigns"]), "models": sorted(u["models"]), "reason": reason})
    data = {
        "method": [
            "Each comparison pairs two models on the same independent units (worlds, or cases when seeds only repeat one prompt).",
            "Within a unit, the two models are compared on the cells both completed with the same seed or replicate (matched pairs), averaging first within each combination of the strata not selected so an unselected stratum counts equally rather than by cell count; where replicates cannot be matched across models (Housing runs), each model's mean over its completed cells is used.",
            "The estimate is the mean over paired units of the per-unit difference; the interval is a 95% percentile bootstrap that resamples independent clusters (a world with its twin; otherwise the unit), 2000 draws seeded by the stratum, shown only with at least 5 clusters.",
            "A unit missing either model in a stratum is dropped from that stratum; cells that did not complete are counted per model and reason.",
        ],
        "sets": built,
        "hidden_families": sorted(HIDDEN_FAMILIES),
        "not_compared": stems,
    }
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    envelope = {"encoding": "gzip+base64", "raw_bytes": len(raw), "payload": base64.b64encode(gzip.compress(raw, 9, mtime=0)).decode()}
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "data" / "model_comparisons.json").write_text(json.dumps(envelope, separators=(",", ":")), encoding="utf-8")
    print(f"model comparisons: {len(built)} sets, {sum(len(s['rows']) for s in built)} cells, {len(stems)} multi-model stems not compared")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
