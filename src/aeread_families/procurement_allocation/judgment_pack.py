"""Supplier-judgment pack: the hidden-information case as environment worlds.

Each world is a repeated-sourcing case (four periods, one controller supplier
and two display suppliers) whose display suppliers carry a hidden kind drawn
from the declared market in :mod:`supplier_profiles`. What the buyer can learn
about a kind comes only through channels it pays for or earns:

- the listing's ``profile``, a marketplace record simulated from the kind;
- a sample (binomial, ``sample_size`` units, cumulative across draws);
- the history of each delivered lot (late, or on time with its defect count).

Everything else is closed: supplier ids are neutral codes; every supplier
claims the same yield and on-time figures, in the listing and when asked; a
formal offer states a common on-time commitment (``offer_on_time_probability``)
while scoring and delivery use the true one; ``check_award`` reports terms
only; and no award needs a sample (``policy.award_requires``). The declared
market reaches the buyer as ``policy.market_facts``.

The reference is the best policy on the buyer's information
(:func:`supplier_profiles.solve` with the environment's own per-period values
and ``lot_signal="delivery"``). The full-information bound is the repeated-
sourcing solver. Design and probe: ``docs/families/procurement-allocation/
hidden_information_case.md``.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import random
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from . import environment as env
from . import relationship
from . import supplier_profiles as sp

GENERATOR_ID = "procurement_allocation_judgment_pack_v1"
GENERATOR_VERSION = "1.0.0"
PACK_SCHEMA = "aeread.procurement_judgment_pack/0.1"
CASES_ROOT = Path(__file__).resolve().parents[3] / "cases" / "procurement_allocation_v1"

CONTROLLER = "esp32_s3_n8r8"
DISPLAY = "ssd1306_oled_096"
VARIANTS = {CONTROLLER: "esp32_s3_devkitc_1_n8r8", DISPLAY: "096in_128x64_four_pin_i2c_ssd1306"}
CLAIMED_VARIANTS = {CONTROLLER: "esp32 s3 devkitc 1 n8r8", DISPLAY: "096in 128x64 four pin i2c ssd1306"}

#: Economics shared by every world. A bad display lot (70% yield, 85% on time)
#: completes about 11 kits, so minimum service is set below it: buying from a
#: bad supplier is a costly award, never a rejection that would name the kind.
OBJECTIVE = {
    "target_kits": 20,
    "minimum_service_kits": 8,
    "revenue_per_completed_kit_usd": 10.0,
    "shortfall_penalty_per_kit_usd": 3.0,
    "cash_budget_usd": 150.0,
    "deadline_days": 14,
    "defect_detection_days": 10,
    "working_capital_horizon_days": 45,
    "annual_financing_rate": 0.12,
    "defer_value_usd": 0.0,
}
INTERACTION = {
    "max_actions": 10,
    "inquiry_days": 1,
    "quote_days": 1,
    "counter_days": 1,
    "inquiry_cost_usd": 0.05,
    "quote_cost_usd": 0.10,
    "counter_cost_usd": 0.15,
    "award_check": "terms_only",
}
PERIODS = 4
LOT_UNITS = 20
SAMPLE_UNITS = 10
SAMPLE_LEAD_DAYS = 2
LEAD_TIME_DAYS = 7
#: Every offer states this on-time commitment; the true figure stays private.
OFFER_ON_TIME = 0.95
#: What every supplier claims, in the listing and when asked.
CLAIMS = {"verified_yield_rate": 0.99, "on_time_probability": 0.97}

#: Cells as in the draft, with saving ranges re-set for the environment's
#: economics (a bad lot costs far more here: lost kits, the shortfall penalty).
CELLS: dict[str, dict[str, Any]] = {
    "switch_on_record": {"segment": "established", "band": (0.0, 0.03), "discount": (0.25, 0.34), "intended": "buy_C"},
    "test_thin_record": {"segment": "new", "band": (0.10, 0.5), "discount": (0.25, 0.34), "intended": "sample_C"},
    "not_worth_testing": {"segment": "new", "band": (0.10, 0.5), "discount": (0.04, 0.08), "intended": "buy_I"},
    "stars_mislead": {"segment": "new", "band": (0.6, 1.0), "discount": (0.25, 0.34), "intended": "buy_I", "outrates": True},
}
MIN_MARGIN_USD = 1.0
TWIN_BAND = (0.1, 0.9)

PACKS = {
    "judgment_dev_v1": {"split": "dev", "seed_start": 2450000, "per_cell": 2},
    "judgment_holdout_v1": {"split": "holdout", "seed_start": 2460000, "per_cell": 2},
}


def _code(rng: random.Random) -> str:
    return "".join(rng.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(4))


def _profile_listing(profile: sp.Profile) -> dict[str, Any]:
    """The record as a marketplace page shows it."""
    return {
        "years_on_platform": profile.years_on_platform,
        "orders": profile.orders,
        "rating": profile.rating,
        "reviews": profile.reviews,
        "star_counts": {f"{s}_star": n for s, n in zip(sp.STARS, profile.star_counts)},
        "protected_orders": profile.protected_orders,
        "on_time_protected_orders": profile.on_time_protected,
        "badges": [b for b, on in (("gold", profile.gold), ("verified", profile.verified)) if on],
        "typical_reply_hours": profile.response_hours,
    }


def _supplier(
    *, supplier_id: str, component: str, price: float, kind: str, profile: sp.Profile, sample_cost: float
) -> dict[str, Any]:
    t = sp.MARKET["type"][kind]
    return {
        "supplier_id": supplier_id,
        "component": component,
        "listing": {
            "supplier_name": "Supplier " + supplier_id.rsplit("_", 1)[-1].upper(),
            "displayed_unit_price_usd": price,
            "claimed_lead_time_days": LEAD_TIME_DAYS,
            "claimed_variant": CLAIMED_VARIANTS[component],
            "evidence_status": "marketplace_listing_unverified",
            "profile": _profile_listing(profile),
            # Sample terms are on the page, as a marketplace shows them, so the
            # buyer can weigh a test before paying for it.
            "sample_terms": {"units": SAMPLE_UNITS, "price_usd": sample_cost, "lead_time_days": SAMPLE_LEAD_DAYS},
        },
        "private_terms": {
            "variant_id": VARIANTS[component],
            "base_unit_price_usd": price,
            "shipping_per_unit_usd": 0.05,
            "duty_rate": 0.05,
            "capacity": LOT_UNITS,
            # A lot is always whole: splitting 10/10 would be a cheap test the
            # reference does not model, so a buyer could beat it.
            "moq": LOT_UNITS,
            "order_step": 10,
            "lead_time_days": LEAD_TIME_DAYS,
            "on_time_probability": t["on_time"],
            "offer_on_time_probability": OFFER_ON_TIME,
            "payment_terms_days": 30,
            "offer_valid_days": 30,
            "return_policy": {
                "refund_window_days": 30,
                "claim_acceptance_probability": 0.95,
                "restocking_fee_rate": 0.0,
                "return_freight_payer": "supplier",
                "return_freight_per_unit_usd": 0.0,
                "refund_delay_days": 5,
            },
            "quality": {
                "sample_size": SAMPLE_UNITS,
                "observed_defects": 0,
                "verified_yield_rate": round(1.0 - t["defect_rate"], 6),
                "sample_cost_usd": sample_cost,
                "sample_lead_time_days": SAMPLE_LEAD_DAYS,
            },
            # No room to negotiate: the case is about whom to trust, not price.
            "negotiation": {
                "floor_unit_price_usd": price,
                "minimum_moq": LOT_UNITS,
                "maximum_payment_terms_days": 30,
                "maximum_refund_window_days": 30,
                "supplier_paid_return_freight_available": True,
            },
            "verbal_bias": dict(CLAIMS),
        },
    }


def period_values(payload: Mapping[str, Any], roles: Mapping[str, str]) -> dict[tuple[str, str], float]:
    """The environment's own value of one period's award: the controller from
    its only supplier and the display lot from `role`, if that supplier is
    `kind`. Two quotes are charged; a sample is charged by the reference."""
    out: dict[tuple[str, str], float] = {}
    for role, supplier_id in roles.items():
        for kind in ("good", "bad"):
            case = copy.deepcopy(dict(payload))
            for s in case["suppliers"]:
                if s["supplier_id"] == supplier_id:
                    t = sp.MARKET["type"][kind]
                    s["private_terms"]["quality"]["verified_yield_rate"] = round(1.0 - t["defect_rate"], 6)
                    s["private_terms"]["on_time_probability"] = t["on_time"]
            view = relationship.period_case(case, 1)
            suppliers = {s["supplier_id"]: s for s in case["suppliers"]}
            controller = next(s for s in case["suppliers"] if s["component"] == CONTROLLER)
            offers = {}
            lines = []
            for s in (controller, suppliers[supplier_id]):
                offer = env._base_offer(s, version=1, issued_day=0)
                offers[offer["offer_id"]] = offer
                lines.append({"offer_id": offer["offer_id"], "quantity": LOT_UNITS})
            result = env.evaluate_award(
                view, award_lines=lines, offers=offers, quality_evidence={},
                elapsed_days=2 * INTERACTION["quote_days"],
                information_cost_usd=2 * INTERACTION["quote_cost_usd"],
            )
            if not result["feasible"]:
                raise ValueError(f"a {kind} lot from {role} is infeasible: {result['violations']}")
            out[(role, kind)] = float(result["contribution_margin_usd"])
    return out


def build_world(seed: int, cell: str, *, pack: str, split: str, max_draws: int = 4000) -> dict[str, Any] | None:
    """The first draw for `seed` whose challenger posterior falls in the cell's
    band and whose intended first move is best by MIN_MARGIN_USD."""
    spec = CELLS[cell]
    rng = random.Random(seed)
    for _ in range(max_draws):
        inc_kind = "bad" if rng.random() < sp.MARKET["prior_bad"]["established"] else "good"
        codes = {_code(rng) for _ in range(6)}
        codes = sorted(codes)[:3]
        ids = {"E": f"{CONTROLLER}_{codes[0]}", "I": f"{DISPLAY}_{codes[1]}", "C": f"{DISPLAY}_{codes[2]}"}
        inc = sp.draw_profile(rng, supplier_id=ids["I"], segment="established", kind=inc_kind)
        seg = spec["segment"]
        ch_kind = "bad" if rng.random() < sp.MARKET["prior_bad"][seg] else "good"
        ch = sp.draw_profile(rng, supplier_id=ids["C"], segment=seg, kind=ch_kind)
        bI, bC = sp.posterior_bad(inc), sp.posterior_bad(ch)
        lo, hi = spec["band"]
        if not (lo <= bC <= hi) or bI > 0.05:
            continue
        if spec.get("outrates") and not ((ch.rating or 0) > (inc.rating or 0)):
            continue
        esp = sp.draw_profile(rng, supplier_id=ids["E"], segment="established", kind="good")
        if sp.posterior_bad(esp) > 0.01:
            continue
        price = round(rng.uniform(1.30, 1.45), 4)
        c_price = round(price * (1 - rng.uniform(*spec["discount"])), 4)
        sample_cost = round(rng.uniform(8.3, 10.9), 2)
        suppliers = [
            _supplier(supplier_id=ids["E"], component=CONTROLLER, price=round(rng.uniform(2.9, 3.2), 4),
                      kind="good", profile=esp, sample_cost=round(rng.uniform(8.3, 10.9), 2)),
            _supplier(supplier_id=ids["I"], component=DISPLAY, price=price, kind=inc_kind, profile=inc, sample_cost=sample_cost),
            _supplier(supplier_id=ids["C"], component=DISPLAY, price=c_price, kind=ch_kind, profile=ch, sample_cost=sample_cost),
        ]
        order = [suppliers[0], *rng.sample(suppliers[1:], 2)]
        payload = {
            # Neutral: the product id is in the observation, so it must not name the cell.
            "objective": {"product_id": f"display_controller_{seed}", **OBJECTIVE,
                          "bom": {CONTROLLER: 1, DISPLAY: 1}},
            "interaction": {**INTERACTION, "periods": {"count": PERIODS, "delivery_seed": seed + 100000},
                            "sample_noise": {"model": "binomial", "seed": seed + 500000}},
            "policy": {
                "required_variant_by_component": dict(VARIANTS),
                "inquiry_fields": ["exact_variant", "moq_capacity", "lead_time", "shipping", "quality", "return_refund_policy"],
                "award_requires": ["unexpired_formal_offer", "exact_variant"],
                "market_facts": sp.market_facts_text(lot_signal="delivery"),
            },
            "suppliers": order,
        }
        env.ProcurementAllocationPlugin().validate_payload(payload)
        values = period_values(payload, {"I": ids["I"], "C": ids["C"]})
        econ = sp.Economics(
            periods=PERIODS, lot_units=LOT_UNITS, sample_units=SAMPLE_UNITS, sample_cost=sample_cost,
            incumbent_price=price, challenger_price=c_price,
            values=tuple((r, k, v) for (r, k), v in sorted(values.items())), lot_signal="delivery",
        )
        sol = sp.solve(econ, bI, bC)
        ranked = sorted(sol["first_action_values"].values(), reverse=True)
        if sol["first_action"] != spec["intended"] or ranked[0] - ranked[1] < MIN_MARGIN_USD:
            continue
        slug = f"{cell}_{seed}"
        raw = {
            "spec_version": "aeread.case/0.1",
            "case_id": f"procurement_allocation_v1.{pack}.{slug}",
            "family_id": "procurement_allocation_v1",
            "family_version": "1.0.0",
            "split": split,
            "world_seed": seed,
            "seats": [{"id": "buyer", "role": "buyer"}],
            "episode": {"max_logical_actions": PERIODS * INTERACTION["max_actions"],
                        "termination": ["submitted", "deferred", "interaction_budget_exhausted", "invalid_action"]},
            "visibility_policy": "procurement_allocation_public_listings_private_supplier_terms_v1",
            "payload": payload,
            "provenance": {"generator_id": GENERATOR_ID, "generator_version": GENERATOR_VERSION, "review_status": "generated"},
            "content_sha256": "0" * 64,
        }
        raw["content_sha256"] = case_content_sha256(CaseManifest.from_dict(raw))
        return {
            "raw": raw,
            "slug": slug,
            "cell": cell,
            "ids": ids,
            "hidden": {"I": inc_kind, "C": ch_kind},
            "posterior_bad": {"I": bI, "C": bC},
            "economics": asdict(econ),
            "reference": sol,
            "profiles": {"I": inc, "C": ch},
        }
    return None


def with_hidden_challenger(world: Mapping[str, Any], kind: str, *, pack: str) -> dict[str, Any]:
    """The twin: same record and listing, the challenger's hidden kind set."""
    raw = copy.deepcopy(world["raw"])
    t = sp.MARKET["type"][kind]
    for s in raw["payload"]["suppliers"]:
        if s["supplier_id"] == world["ids"]["C"]:
            s["private_terms"]["quality"]["verified_yield_rate"] = round(1.0 - t["defect_rate"], 6)
            s["private_terms"]["on_time_probability"] = t["on_time"]
    slug = world["slug"] + "_twin"
    raw["case_id"] = f"procurement_allocation_v1.{pack}.{slug}"
    raw["content_sha256"] = "0" * 64
    raw["content_sha256"] = case_content_sha256(CaseManifest.from_dict(raw))
    return {**world, "raw": raw, "slug": slug, "hidden": {**world["hidden"], "C": kind}, "twin_of": world["slug"]}


def summarise(world: Mapping[str, Any]) -> dict[str, Any]:
    """The pack row: everything a check or an analyst needs, nothing a buyer sees."""
    econ = sp.Economics(**{**world["economics"], "values": tuple(tuple(v) for v in world["economics"]["values"])})
    bI, bC = world["posterior_bad"]["I"], world["posterior_bad"]["C"]
    bound = relationship.solve_relationship_upper_bound(world["raw"]["payload"])
    rules = {}
    for rule in sp.RULES:
        policy = sp._rule(rule, world["profiles"])
        rules[rule] = round(world["reference"]["value"] - sp.evaluate(policy, econ, bI, bC), 4)
    row = {
        "slug": world["slug"],
        "cell": world["cell"],
        "case_id": world["raw"]["case_id"],
        "content_sha256": world["raw"]["content_sha256"],
        "world_seed": world["raw"]["world_seed"],
        "supplier_roles": {"controller": world["ids"]["E"], "incumbent": world["ids"]["I"], "challenger": world["ids"]["C"]},
        "hidden_kind": {"incumbent": world["hidden"]["I"], "challenger": world["hidden"]["C"]},
        "posterior_bad": {"incumbent": round(bI, 6), "challenger": round(bC, 6)},
        "period_values_usd": {f"{r}_{k}": round(v, 6) for r, k, v in econ.values},
        "sample_cost_usd": econ.sample_cost,
        "reference": {
            "first_action": world["reference"]["first_action"],
            "first_action_values_usd": {k: round(v, 6) for k, v in world["reference"]["first_action_values"].items()},
            "value_usd": round(world["reference"]["value"], 6),
            "realised_under_truth_usd": round(
                sp.evaluate(sp._optimal_policy(econ, sp.MARKET), econ, bI, bC,
                            {"I": world["hidden"]["I"], "C": world["hidden"]["C"]}), 6),
        },
        "oracle_usd": round(sp.oracle_value(econ, world["hidden"]), 6),
        "rule_ex_ante_regret_usd": rules,
    }
    # The environment's full-information bound. It equals periods x the better
    # supplier's period value when both are priced at their floor, which the
    # tests check; a difference would mean the two references read different worlds.
    row["relationship_bound_usd"] = round(float(bound.contribution_margin_usd), 6)
    if "twin_of" in world:
        row["twin_of"] = world["twin_of"]
    return row


def build_pack(name: str) -> dict[str, Any]:
    spec = PACKS[name]
    worlds = []
    for ci, cell in enumerate(CELLS):
        found, seed = 0, spec["seed_start"] + 1000 * ci
        scanned = 0
        while found < spec["per_cell"]:
            scanned += 1
            if scanned > 200:
                raise ValueError(f"{cell}: no admissible world in 200 seeds")
            w = build_world(seed, cell, pack=name, split=spec["split"])
            seed += 1
            if w is None:
                continue
            found += 1
            worlds.append(w)
            if TWIN_BAND[0] < w["posterior_bad"]["C"] < TWIN_BAND[1]:
                flipped = "good" if w["hidden"]["C"] == "bad" else "bad"
                worlds.append(with_hidden_challenger(w, flipped, pack=name))
    rows = [summarise(w) for w in worlds]
    manifest = {
        "schema_version": PACK_SCHEMA,
        "pack": name,
        "generator_id": GENERATOR_ID,
        "generator_version": GENERATOR_VERSION,
        "split": spec["split"],
        "seed_start": spec["seed_start"],
        "per_cell": spec["per_cell"],
        "market": sp.MARKET,
        "market_facts": sp.market_facts_text(lot_signal="delivery"),
        "cells": CELLS,
        "min_margin_usd": MIN_MARGIN_USD,
        "twin_band": TWIN_BAND,
        "selection_rule": (
            "for each cell, seeds from seed_start + 1000*cell_index are tried in order; a seed's first draw "
            "whose challenger posterior falls in the cell's band, whose incumbent posterior is at most 0.05 and "
            "whose intended first move beats every other by min_margin_usd under the buyer-information "
            "reference is admitted; a twin with the other hidden challenger kind is added when the posterior "
            "is inside twin_band"
        ),
        "worlds": rows,
        "claim_scope": (
            "synthetic worlds selected by rule; the reference is the best policy on the buyer's information "
            "under the declared market, with one sample per supplier; not a statement about real suppliers"
        ),
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=list).encode("utf-8")
    ).hexdigest()
    return {"manifest": manifest, "cases": [w["raw"] for w in worlds]}


def write_pack(name: str, *, root: Path | str | None = None) -> tuple[Path, ...]:
    built = build_pack(name)
    destination = Path(root) if root is not None else CASES_ROOT / name
    destination.mkdir(parents=True, exist_ok=True)
    written = []
    for case in built["cases"]:
        path = destination / f"{case['case_id'].rsplit('.', 1)[-1]}.json"
        tmp = path.with_suffix(f".json.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        written.append(path)
    manifest_path = destination / "pack.json"
    tmp = manifest_path.with_suffix(f".json.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(built["manifest"], indent=2, default=list) + "\n", encoding="utf-8")
    os.replace(tmp, manifest_path)
    written.append(manifest_path)
    return tuple(written)


# ---------------------------------------------------------------------------
# Checks from the buyer's point of view
# ---------------------------------------------------------------------------

#: A decision counts as a mistake when it gives up more than this, in dollars of
#: expected value at the buyer's own beliefs. Below it the choice is a tie.
DECISION_TOLERANCE_USD = 1.0

CHECKS = {
    "J1": "First move: the move the buyer's own information favours (switch on a clean record, test a thin one, "
          "stay when testing does not pay, stay when the stars contradict the record)",
    "J2": "Uses its evidence: after a sample or a delivered lot, buys from the supplier that evidence favours",
    "J3": "Drops a supplier its evidence shows is bad: no award to a supplier believed more likely bad than good "
          "once a sample or lot has spoken",
    "J4": "Buys information only when it can pay: no sample whose expected value is below its cost",
    "J5": "Valid execution: every period awarded, no invalid action",
}


def decisions_from_state(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The buyer's display decisions in order, with what each one revealed.

    Read from the terminal state: samples from the conversation (a supplier's
    'Batch inspected' reply, in the period it happened), awards and deliveries
    from the period history. Nothing hidden is read.
    """
    out: list[dict[str, Any]] = []
    period = 1
    samples_by_period: dict[int, list[dict[str, Any]]] = {}
    for entry in state["conversation"]:
        content = str(entry.get("content", ""))
        if entry.get("role") == "system" and "begins; formal offers" in content:
            period += 1
        if entry.get("role") == "supplier" and content.startswith("Batch inspected:"):
            defects = int(content.split("Batch inspected: ", 1)[1].split(" defects", 1)[0])
            samples_by_period.setdefault(period, []).append({"supplier_id": entry["supplier_id"], "defects": defects})
    for row in state["history"]:
        p = int(row["period"])
        # grade() ignores samples of suppliers outside the display pair
        for s in samples_by_period.get(p, []):
            out.append({"period": p, "action": "sample", **s})
        awarded = [a for a in row["awarded"] if a["component"] == DISPLAY]
        delivery = next((d for d in row["delivery"] if d["component"] == DISPLAY), None)
        out.append({
            "period": p,
            "action": "award" if awarded else row["decision"],
            "supplier_id": awarded[0]["supplier_id"] if awarded else None,
            "on_time": delivery["on_time"] if delivery else None,
            "defects": delivery["defective_units"] if delivery else None,
        })
    return out


def grade(row: Mapping[str, Any], decisions: Sequence[Mapping[str, Any]], *, invalid_action: bool = False) -> dict[str, Any]:
    """Decision regret and J1-J5 for one episode of a pack world."""
    econ = sp.Economics(
        periods=PERIODS, lot_units=LOT_UNITS, sample_units=SAMPLE_UNITS, sample_cost=float(row["sample_cost_usd"]),
        values=tuple((k.split("_")[0], k.split("_")[1], float(v)) for k, v in sorted(row["period_values_usd"].items())),
        lot_signal="delivery",
    )
    role = {row["supplier_roles"]["incumbent"]: "I", row["supplier_roles"]["challenger"]: "C"}
    b = {"I": float(row["posterior_bad"]["incumbent"]), "C": float(row["posterior_bad"]["challenger"])}
    sampled: set[str] = set()
    t = sp.MARKET["type"]
    losses: list[dict[str, Any]] = []
    first: str | None = None
    fails = {k: [] for k in ("J2", "J3", "J4")}
    evidence_seen = False
    after_sample = False
    for d in decisions:
        left = econ.periods - int(d["period"]) + 1
        sub = sp.Economics(**{**asdict(econ), "periods": left})
        q = sp._state_values(sub, b["I"], b["C"], "I" in sampled, "C" in sampled, sp.MARKET, buy_only=after_sample)
        if d["action"] == "sample":
            r = role.get(d["supplier_id"])
            if r is None:
                continue
            chosen = f"sample_{r}"
            if r in sampled or chosen not in q:
                loss = econ.sample_cost  # a repeat sample is outside the reference: charged its cost
            else:
                loss = max(q.values()) - q[chosen]
            if loss > DECISION_TOLERANCE_USD:
                fails["J4"].append(d["period"])
            first = first or chosen
            losses.append({"period": d["period"], "decision": chosen, "loss_usd": round(loss, 4)})
            bd = sp._pmf(econ.sample_units, t["bad"]["defect_rate"])[d["defects"]]
            gd = sp._pmf(econ.sample_units, t["good"]["defect_rate"])[d["defects"]]
            b[r] = b[r] * bd / (b[r] * bd + (1 - b[r]) * gd) if (b[r] * bd + (1 - b[r]) * gd) > 0 else b[r]
            sampled.add(r)
            evidence_seen = True
            after_sample = True
            continue
        if d["action"] != "award" or d["supplier_id"] not in role:
            losses.append({"period": d["period"], "decision": d["action"], "loss_usd": None})
            after_sample = False
            continue
        r = role[d["supplier_id"]]
        chosen = f"buy_{r}"
        loss = max(q.values()) - q[chosen]
        first = first or chosen
        losses.append({"period": d["period"], "decision": chosen, "loss_usd": round(loss, 4)})
        if evidence_seen and loss > DECISION_TOLERANCE_USD:
            fails["J2"].append(d["period"])
        if evidence_seen and b[r] > 0.5:
            fails["J3"].append(d["period"])
        # what the lot showed
        if d["on_time"] is False:
            pb, pg = 1 - t["bad"]["on_time"], 1 - t["good"]["on_time"]
        elif d["defects"] is not None:
            pb = t["bad"]["on_time"] * sp._pmf(econ.lot_units, t["bad"]["defect_rate"])[d["defects"]]
            pg = t["good"]["on_time"] * sp._pmf(econ.lot_units, t["good"]["defect_rate"])[d["defects"]]
        else:
            pb = pg = 1.0
        b[r] = b[r] * pb / (b[r] * pb + (1 - b[r]) * pg) if (b[r] * pb + (1 - b[r]) * pg) > 0 else b[r]
        evidence_seen = True
        after_sample = False
    awarded_all = sum(1 for d in decisions if d["action"] == "award") == PERIODS
    checks = {
        "J1": first == row["reference"]["first_action"],
        "J2": not fails["J2"],
        "J3": not fails["J3"],
        "J4": not fails["J4"],
        "J5": awarded_all and not invalid_action,
    }
    counted = [x["loss_usd"] for x in losses if x["loss_usd"] is not None]
    return {
        "decision_regret_usd": round(sum(counted), 4) if awarded_all and not invalid_action else None,
        "first_move": first,
        "reference_first_move": row["reference"]["first_action"],
        "checks": checks,
        "failing_periods": {k: v for k, v in fails.items() if v},
        "decisions": losses,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("pack", choices=sorted(PACKS))
    parser.add_argument("--write", action="store_true", help="write the pack under cases/")
    parser.add_argument("--check", action="store_true", help="fail if the committed pack differs")
    args = parser.parse_args(argv)
    if args.check:
        built = build_pack(args.pack)
        committed = json.loads((CASES_ROOT / args.pack / "pack.json").read_text())
        if committed != json.loads(json.dumps(built["manifest"], default=list)):
            raise SystemExit(f"{args.pack} differs from its generator")
        print(f"{args.pack} regenerates to the committed manifest")
        return 0
    if args.write:
        for path in write_pack(args.pack):
            print(path)
        return 0
    for row in build_pack(args.pack)["manifest"]["worlds"]:
        print(row["slug"], row["hidden_kind"]["challenger"], round(row["posterior_bad"]["challenger"], 2),
              row["reference"]["first_action"], row["rule_ex_ante_regret_usd"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
