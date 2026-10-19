"""Pay or test, version 3: worlds where looking ahead pays, under prices from the sourcing record.

Version 2 (``pay_or_test_v2_case_matrix``) is kept whole: newcomers of one seller kind share a source with a stated
probability, so a test can be worth taking for what it says about another listing. Version 3 changes what the
parameter specification (``docs/families/procurement-allocation/pay_or_test_v3_parameters.md``) and the v3 probe
found:

- **Prices from the record.** Each newcomer's price off the recorded supplier's is drawn from the 56
  recorded-against-unrecorded pairs of the maintainers' sourcing record (``RECORD_DISCOUNTS``), so a newcomer is
  dearer about half the time and up to two thirds cheaper otherwise. Prices are landed: shipping is folded in.
- **Unanswered quotes.** A newcomer answers a quote request with probability ``ANSWER_PROBABILITY`` (9 of 28
  suppliers quoted in the record); the recorded supplier always answers. Samples always arrive.
- **A source lookup.** ``look_up_source`` reads a listing's registered factory for ``LOOKUP_FEE_USD``. Two lookups
  in one kind settle whether it shares a source. Sharing is drawn from the stated probability, which now ranges down
  to 0.5, where knowing it is worth most.
- **No inquiry, no counter, no financing, no binding budget.** Each could only lose or never moved a choice.
- **A stake for the option-value worlds.** On v2's pilot the best policy beat paying the premium by only 2% to 15%
  where the one-step rule pays, so missing the probe cost little (v3 design note, probe). A ``myopic_pays`` world is
  now admitted only if the best policy beats paying the premium by at least ``STAKE_SHARE`` of what paying earns.

Admission (``admit``) reads only what a buyer can see and the exact expected value of each policy under the stated
law (``pay_or_test_v3_reference``). A world is admitted only if

1. some kind has two newcomers or more;
2. the one-step rule, every fixed rule and the kind-blind shortcut each give up at least ``MARGIN_USD`` against the
   best informed policy;
3. the one-step rule's first request goes where the cell says (``myopic_pays``: to the recorded supplier;
   ``myopic_tests``: to a newcomer);
4. in a ``myopic_pays`` world, the best policy beats paying the premium by ``STAKE_SHARE`` of its value;
5. with the source never shared, the one-step rule is within ``ATTRIBUTION_USD`` of that world's best policy;
6. the full-information value averaged over the stated law exceeds the best policy by ``INFORMATION_HEADROOM_USD``.

The pack must show a mean one-step loss of at least ``MEAN_MARGIN_USD``. Types, sharing, factories and replies are
drawn after admission on streams of their own.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from .environment import _validate_payload, solve_full_information_upper_bound
from .pay_or_test_case_matrix import COMPONENT, VARIANT, _supplier
from .pay_or_test_reference import GOOD, GOOD_ON_TIME, GOOD_YIELD, LATE, LATE_ON_TIME, POOR, POOR_YIELD
from .pay_or_test_v2_reference import SOURCING_FIELD
from .pay_or_test_v3_environment import FAMILY_ID, FAMILY_VERSION, PayOrTestV3Plugin, SOURCE_FIELD, version1_view
from .pay_or_test_v3_reference import (
    DIAGNOSTIC_RULES, FIXED_RULES, LOOKAHEAD_RULES, LOOKUP, REQUESTS, RULES, SHORTCUT_RULES, Reference, describe, play,
    score_actions,
)

GENERATOR_ID = "procurement_allocation_pay_or_test_case_matrix_v3"
GENERATOR_VERSION = "3.0.0"
PACK_SCHEMA = "aeread.procurement_pay_or_test_pack/0.3"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

KINDS = ("myopic_pays", "myopic_tests")
SEEDS_PER_WORLD = 4_000
PILOT_PACK_ID = "pay_or_test_v3_pilot"
#: Each split's seed range and size. v2 scanned 8 950 000 to 9 160 000; v3 starts above it.
SPLITS: dict[str, dict[str, int]] = {
    PILOT_PACK_ID: {"seed_start": 9_300_000, "worlds_per_cell": 6},
}

TARGET_KITS, MINIMUM_SERVICE_KITS = 50, 40
REVENUE_PER_KIT_USD, SHORTFALL_PENALTY_USD = 37.0, 12.0
NO_SUPPLY_VALUE_USD = -SHORTFALL_PENALTY_USD * TARGET_KITS
#: Never binds (a dearest newcomer at three times the recorded price, every test taken, is under it) and is not shown.
CASH_BUDGET_USD = 20_000.0
BUDGET_ACTIONS = 10
QUOTE_FEE_USD, QUOTE_DAYS = 2.0, 1
LOOKUP_FEE_USD, LOOKUP_DAYS = 1.0, 0
ESTABLISHED_SAMPLE = (30.0, 2)
ESTABLISHED_LEAD_DAYS = 6
NEWCOMER_SAMPLE_DAYS = 3
NEWCOMER_COUNT = 3
INSPECTED_UNITS = 100
COHORT_TRACKED = 40
SELLER_KINDS = ("manufacturer", "trading company")
#: 9 of the 28 suppliers contacted in the sourcing record quoted.
ANSWER_PROBABILITY = 1.0 / 3.0
#: Newcomer discount off the recorded seller over the 56 recorded-against-unrecorded pairs of the sourcing record
#: (cap 3; ``~/analysis/aeread-paper/procurement_calibration``, inputs hashed in INPUT_SHA256.txt). Negative: dearer.
RECORD_DISCOUNTS = (
    -1.894, -1.75, -1.375, -1.2294, -1.0543, -1.0492, -0.8333, -0.6389, -0.6, -0.5037, -0.5, -0.5, -0.4545, -0.3854,
    -0.3404, -0.3256, -0.2105, -0.2069, -0.2, -0.2, -0.1606, -0.16, -0.1, -0.0874, -0.0769, -0.0769, -0.0203, -0.0154,
    0.0, 0.0556, 0.0833, 0.0848, 0.1667, 0.1667, 0.1739, 0.1739, 0.2132, 0.3509, 0.4, 0.4271, 0.4474, 0.4545, 0.4803,
    0.5, 0.5, 0.5, 0.5, 0.5, 0.5134, 0.5134, 0.5134, 0.5556, 0.5962, 0.6, 0.6209, 0.6635,
)
SAMPLE_FEES_USD = (20.0, 25.0, 30.0, 40.0, 120.0, 160.0, 200.0, 240.0)
NEWCOMER_LEAD_DAYS = (5, 6, 7, 8)
COHORT_LATE = (2, 4, 6)
COHORT_FAILED = (18, 22, 26, 30)
SAME_SOURCE_PROBABILITIES = (0.5, 0.65, 0.8, 0.95)
#: Room for one newcomer test with its expected retries, or two, before the recorded supplier's fallback.
DEADLINES = tuple(range(14, 23))

MARGIN_USD = 10.0
MEAN_MARGIN_USD = 15.0
STAKE_SHARE = 0.10
INFORMATION_HEADROOM_USD = 10.0
ATTRIBUTION_USD = 5.0
ADMISSION_RULES = (*LOOKAHEAD_RULES, *FIXED_RULES, *SHORTCUT_RULES)


def pack_root(split: str = PILOT_PACK_ID) -> Path:
    if split not in SPLITS:
        raise KeyError(f"unknown split {split!r}")
    return REPOSITORY_ROOT / "cases" / "procurement_allocation_v1" / split


def world_specs(split: str = PILOT_PACK_ID) -> tuple[dict[str, Any], ...]:
    per_cell, start = SPLITS[split]["worlds_per_cell"], SPLITS[split]["seed_start"]
    specs = []
    for cell_index, kind in enumerate(KINDS):
        for k in range(per_cell):
            ordinal = cell_index * per_cell + k
            specs.append({"slug": f"{kind}__{k + 1}", "kind": kind, "pack_id": split, "ordinal": ordinal + 1,
                          "seed_block": start + ordinal * SEEDS_PER_WORLD})
    return tuple(specs)


def draw_structure(spec: Mapping[str, Any], seed: int) -> dict[str, Any]:
    """Everything a buyer can see, and nothing about how the newcomers turn out."""
    rng = random.Random(f"{GENERATOR_ID}:{seed}")
    codes = rng.sample(range(100, 1000), NEWCOMER_COUNT + 1)
    established_price = round(round(rng.uniform(24.0, 28.0) / 0.05) * 0.05, 2)
    orders = rng.randrange(48, 97)
    cohorts = {kind: {"late": rng.choice(COHORT_LATE), "failed": rng.choice(COHORT_FAILED)} for kind in SELLER_KINDS}
    newcomers = []
    for _ in range(NEWCOMER_COUNT):
        discount = rng.choice(RECORD_DISCOUNTS)
        kind = rng.choice(SELLER_KINDS)
        newcomers.append({
            "discount": discount, "price": round(established_price * (1.0 - discount), 2), "kind": kind,
            "sample_fee_usd": rng.choice(SAMPLE_FEES_USD), "lead_days": rng.choice(NEWCOMER_LEAD_DAYS),
            "late": cohorts[kind]["late"], "failed": cohorts[kind]["failed"],
        })
    return {
        "codes": codes, "established_price": established_price, "established_orders": orders,
        "established_late": round(orders * (1.0 - GOOD_ON_TIME)), "established_kind": rng.choice(SELLER_KINDS),
        "newcomers": newcomers, "same_source_probability": rng.choice(SAME_SOURCE_PROBABILITIES),
        "deadline_days": rng.choice(DEADLINES), "product_id": f"kit_{rng.randrange(1000, 10000)}",
        "listing_order": rng.sample(range(NEWCOMER_COUNT + 1), NEWCOMER_COUNT + 1),
        "reply_seed": rng.randrange(1, 2**31),
    }


def groups_of(structure: Mapping[str, Any]) -> tuple[tuple[int, ...], ...]:
    by_kind: dict[str, list[int]] = {}
    for i, newcomer in enumerate(structure["newcomers"]):
        by_kind.setdefault(newcomer["kind"], []).append(i)
    return tuple(tuple(members) for _, members in sorted(by_kind.items()))


def _draw_one(rng: random.Random, newcomer: Mapping[str, Any]) -> str:
    roll = rng.random() * COHORT_TRACKED
    return LATE if roll < newcomer["late"] else POOR if roll < newcomer["late"] + newcomer["failed"] else GOOD


def draw_types(structure: Mapping[str, Any], seed: int) -> dict[str, Any]:
    """Each newcomer's type and registered factory, and each kind's sharing, under the stated law, on their own stream."""
    rng = random.Random(f"{GENERATOR_ID}:{seed}:types")
    types: list[str] = [""] * len(structure["newcomers"])
    factories: list[str] = [""] * len(structure["newcomers"])
    shared_by_group = []
    labels = iter(rng.sample(range(1000, 10000), NEWCOMER_COUNT + 1))
    for members in groups_of(structure):
        shared = len(members) > 1 and rng.random() < structure["same_source_probability"]
        shared_by_group.append(shared)
        if shared:
            kind_of, factory = _draw_one(rng, structure["newcomers"][members[0]]), f"Factory F-{next(labels)}"
            for i in members:
                types[i], factories[i] = kind_of, factory
        else:
            for i in members:
                types[i], factories[i] = _draw_one(rng, structure["newcomers"][i]), f"Factory F-{next(labels)}"
    return {"types": tuple(types), "factories": tuple(factories), "shared_by_group": tuple(shared_by_group),
            "established_factory": f"Factory F-{next(labels)}"}


def _landed(supplier: dict[str, Any], factory: str) -> dict[str, Any]:
    """Version 1's supplier with shipping folded into the listed price and its registered factory named."""
    terms = supplier["private_terms"]
    terms["shipping_per_unit_usd"] = 0.0
    terms[SOURCE_FIELD] = factory
    return supplier


def build_case(spec: Mapping[str, Any], seed: int, structure: Mapping[str, Any], drawn: Mapping[str, Any],
               *, seal: bool = True) -> dict[str, Any]:
    """The case for a structure and a draw of types. ``seal=False`` skips validation and the digest, for screening."""
    codes = structure["codes"]
    orders = structure["established_orders"]
    suppliers = [_landed(_supplier(
        f"l{codes[0]}", price=structure["established_price"], lead=ESTABLISHED_LEAD_DAYS, sample=ESTABLISHED_SAMPLE,
        kind=structure["established_kind"], on_time=GOOD_ON_TIME, yield_rate=GOOD_YIELD,
        record={"orders_reported": orders, "late_deliveries": structure["established_late"],
                "units_inspected": orders * 25, "defective_units": round(orders * 25 * (1.0 - GOOD_YIELD)),
                "largest_order_filled_units": 60},
        cohort=None), drawn["established_factory"])]
    for code, newcomer, kind_of, factory in zip(codes[1:], structure["newcomers"], drawn["types"], drawn["factories"]):
        suppliers.append(_landed(_supplier(
            f"l{code}", price=newcomer["price"], lead=newcomer["lead_days"],
            sample=(newcomer["sample_fee_usd"], NEWCOMER_SAMPLE_DAYS), kind=newcomer["kind"],
            on_time=LATE_ON_TIME if kind_of == LATE else GOOD_ON_TIME,
            yield_rate=POOR_YIELD if kind_of == POOR else GOOD_YIELD,
            record={"orders_reported": 0, "late_deliveries": None, "units_inspected": 0,
                    "defective_units": None, "largest_order_filled_units": None},
            cohort={"cohort": f"{newcomer['kind']}, new to this marketplace", "sellers_tracked": COHORT_TRACKED,
                    "unreliable_on_delivery": newcomer["late"], "failed_inspection": newcomer["failed"]},
        ), factory))
    suppliers = [suppliers[i] for i in structure["listing_order"]]
    pack_id = spec.get("pack_id", PILOT_PACK_ID)
    case: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": f"{FAMILY_ID}.{pack_id}.{spec['slug']}",
        "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "split": pack_id,
        "world_seed": seed,
        "seats": [{"id": "buyer", "role": "buyer"}],
        "episode": {"max_logical_actions": BUDGET_ACTIONS,
                    "termination": ["submitted", "deferred", "interaction_budget_exhausted", "invalid_action"]},
        "visibility_policy": "procurement_allocation_public_listings_private_supplier_terms_v1",
        "payload": {
            "objective": {
                "product_id": structure["product_id"], "target_kits": TARGET_KITS,
                "minimum_service_kits": MINIMUM_SERVICE_KITS, "revenue_per_completed_kit_usd": REVENUE_PER_KIT_USD,
                "shortfall_penalty_per_kit_usd": SHORTFALL_PENALTY_USD, "cash_budget_usd": CASH_BUDGET_USD,
                "deadline_days": structure["deadline_days"], "defect_detection_days": 10,
                "working_capital_horizon_days": 45, "annual_financing_rate": 0.0,
                "defer_value_usd": NO_SUPPLY_VALUE_USD, "bom": {COMPONENT: 1},
            },
            "interaction": {
                "max_actions": BUDGET_ACTIONS, "quote_days": QUOTE_DAYS, "quote_cost_usd": QUOTE_FEE_USD,
                "source_lookup_days": LOOKUP_DAYS, "source_lookup_cost_usd": LOOKUP_FEE_USD,
                "reply_seed": structure["reply_seed"],
            },
            "policy": {
                "required_variant_by_component": {COMPONENT: VARIANT},
                "award_requires": ["unexpired_formal_offer", "verified_sample", "exact_variant"],
                "process": {"quote_fee_usd": QUOTE_FEE_USD, "quote_days": QUOTE_DAYS},
                "newcomer_quote_answer_probability": round(ANSWER_PROBABILITY, 6),
                SOURCING_FIELD: {"grouped_by": "seller_kind",
                                 "same_source_probability": structure["same_source_probability"]},
            },
            "suppliers": suppliers,
        },
        "provenance": {"generator_id": GENERATOR_ID, "generator_version": GENERATOR_VERSION, "review_status": "curated"},
        "content_sha256": "0" * 64,
    }
    if not seal:
        return case
    manifest = CaseManifest.from_dict(case)
    PayOrTestV3Plugin().validate_payload(manifest.payload)
    case["content_sha256"] = case_content_sha256(manifest)
    return case


_BLIND = {"types": None, "factories": None, "shared_by_group": None, "established_factory": "Factory F-0"}


def _blind(spec: Mapping[str, Any], seed: int, structure: Mapping[str, Any], rho: float | None = None) -> dict[str, Any]:
    """The payload with every newcomer good and its own factory: what admission reads, since the reference never looks."""
    shown = structure if rho is None else {**structure, "same_source_probability": rho}
    n = len(structure["newcomers"])
    drawn = {**_BLIND, "types": tuple(GOOD for _ in range(n)), "factories": tuple(f"Factory F-{i + 1}" for i in range(n))}
    return build_case(spec, seed, shown, drawn, seal=False)["payload"]


def expected_full_information_value(payload: Mapping[str, Any]) -> float:
    """The environment's full-information bound averaged over every type profile under the stated law."""
    ref = Reference(payload)
    view = version1_view(payload)
    total = 0.0
    for assignment, _, weight in ref.v3_profiles:
        trial = json.loads(json.dumps(view))
        by_id = {ref.ids[i]: t for i, t in assignment.items()}
        for supplier in trial["suppliers"]:
            kind_of = by_id.get(supplier["supplier_id"])
            if kind_of is None:
                continue
            terms = supplier["private_terms"]
            terms["on_time_probability"] = LATE_ON_TIME if kind_of == LATE else GOOD_ON_TIME
            terms["quality"]["verified_yield_rate"] = POOR_YIELD if kind_of == POOR else GOOD_YIELD
            terms["quality"]["observed_defects"] = round(INSPECTED_UNITS * (1.0 - terms["quality"]["verified_yield_rate"]))
        total += weight * solve_full_information_upper_bound(_validate_payload(trial)).contribution_margin_usd
    return total


def kind_of_first(ref: Reference, action: tuple[Any, ...]) -> str | None:
    if action[0] not in REQUESTS:
        return None
    return "myopic_pays" if action[1] in ref.established else "myopic_tests"


def classify(payload: Mapping[str, Any], *, full_information: bool = True) -> dict[str, Any]:
    """Exact values a world's admission is decided on. Reads nothing a buyer cannot see."""
    ref = Reference(payload)
    start = ref.start()
    best = ref.value(*start)
    values = {name: ref.rule_value(name, rule, *start) for name, rule in RULES.items()}
    myopic = RULES["one_step_value"](ref, *start)
    first = ref.best_action(*start)
    pay = values["pay_premium"]
    found = {
        "best_policy_value_usd": round(best, 2),
        "rule_value_usd": {name: round(v, 2) for name, v in values.items()},
        "rule_loss_usd": {name: round(best - v, 2) for name, v in values.items()},
        "best_over_pay_share": round((best - pay) / abs(pay), 4),
        "best_first_action": describe(ref, first),
        "best_first_is_lookup": first[0] == LOOKUP,
        "best_first_to_newcomer": first[0] in REQUESTS and first[1] in ref.newcomers,
        "one_step_first_action": describe(ref, myopic),
        "kind": kind_of_first(ref, myopic),
        "same_source_groups": [[ref.ids[i] for i in members] for members in ref.groups],
    }
    if full_information:
        found["expected_full_information_value_usd"] = round(expected_full_information_value(payload), 2)
    return found


def admit(spec: Mapping[str, Any], seed: int, structure: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Whether a structure is admitted to its cell, and the exact values behind the verdict. Cheap checks first."""
    payload = _blind(spec, seed, structure)
    ref = Reference(payload)
    start = ref.start()
    best = ref.value(*start)
    reasons: dict[str, Any] = {"best_policy_value_usd": round(best, 2)}
    if not any(len(members) > 1 for members in ref.groups):
        return False, {**reasons, "rejected": "no two newcomers share a kind"}
    myopic = RULES["one_step_value"](ref, *start)
    if kind_of_first(ref, myopic) != spec["kind"]:
        return False, {**reasons, "rejected": f"kind {kind_of_first(ref, myopic)}"}
    for name in ADMISSION_RULES:
        loss = best - ref.rule_value(name, RULES[name], *start)
        if loss < MARGIN_USD:
            return False, {**reasons, "rejected": f"{name} within the margin", "loss": round(loss, 2)}
    pay = ref.rule_value("pay_premium", RULES["pay_premium"], *start)
    if spec["kind"] == "myopic_pays" and best - pay < STAKE_SHARE * abs(pay):
        return False, {**reasons, "rejected": "stake under the share", "share": round((best - pay) / abs(pay), 4)}
    independent = Reference(_blind(spec, seed, structure, rho=0.0))
    i_start = independent.start()
    i_loss = independent.value(*i_start) - independent.rule_value("one_step_value", RULES["one_step_value"], *i_start)
    if i_loss >= ATTRIBUTION_USD:
        return False, {**reasons, "rejected": "one_step_value falls short without a shared source", "loss": round(i_loss, 2)}
    full = expected_full_information_value(payload)
    if full - best < INFORMATION_HEADROOM_USD:
        return False, {**reasons, "rejected": "no information headroom", "headroom": round(full - best, 2)}
    found = classify(payload, full_information=False)
    found["expected_full_information_value_usd"] = round(full, 2)
    found["one_step_loss_without_shared_source_usd"] = round(i_loss, 2)
    return True, found


def build_world(spec: Mapping[str, Any], seed: int) -> dict[str, Any] | None:
    structure = draw_structure(spec, seed)
    admitted, found = admit(spec, seed, structure)
    if not admitted:
        return None
    drawn = draw_types(structure, seed)
    case = build_case(spec, seed, structure, drawn)
    return {"case": case, "drawn": drawn, "structure": structure, "classification": found}


def realized(payload: Mapping[str, Any]) -> dict[str, Any]:
    """What the best policy and each rule earn on the world as it turned out (its replies included)."""
    rows = {}
    for name, rule in [("best_policy", None), *RULES.items()]:
        scored = score_actions(payload, play(payload, rule))
        outcome = scored["outcome"]
        rows[name] = {"margin_usd": round(float(outcome["contribution_margin_usd"]), 2),
                      "decision_loss_usd": round(scored["decision_loss_usd"], 2),
                      "actions": len(scored["steps"]), "lookups": scored["lookups"], "days": int(outcome["elapsed_days"])}
    return rows


def world_at(spec: Mapping[str, Any], seed: int, scanned: int) -> tuple[dict[str, Any], dict[str, Any]] | None:
    built = build_world(spec, seed)
    if built is None:
        return None
    case, found, structure, drawn = built["case"], built["classification"], built["structure"], built["drawn"]
    newcomers = []
    for position, (code, n) in enumerate(zip(structure["codes"][1:], structure["newcomers"])):
        newcomers.append({"supplier_id": f"{COMPONENT}_l{code}", "price_usd": n["price"], "discount": n["discount"],
                          "kind": n["kind"], "sample_fee_usd": n["sample_fee_usd"], "lead_days": n["lead_days"],
                          "stated_good_share": round(1.0 - (n["late"] + n["failed"]) / COHORT_TRACKED, 4),
                          "stated_late_share": n["late"] / COHORT_TRACKED, "stated_poor_share": n["failed"] / COHORT_TRACKED,
                          "type": drawn["types"][position], "factory": drawn["factories"][position]})
    entry = {
        "slug": spec["slug"], "kind": spec["kind"], "world_seed": seed, "seeds_scanned": scanned,
        "case_id": case["case_id"], "content_sha256": case["content_sha256"],
        "deadline_days": structure["deadline_days"], "same_source_probability": structure["same_source_probability"],
        "shared_by_group": list(drawn["shared_by_group"]),
        "established": {"supplier_id": f"{COMPONENT}_l{structure['codes'][0]}", "price_usd": structure["established_price"]},
        "newcomers": newcomers,
        **{k: found[k] for k in ("best_policy_value_usd", "rule_value_usd", "rule_loss_usd", "best_over_pay_share",
                                 "best_first_action", "best_first_is_lookup", "best_first_to_newcomer",
                                 "one_step_first_action", "same_source_groups", "expected_full_information_value_usd",
                                 "one_step_loss_without_shared_source_usd")},
        "realized_upper_bound_usd": round(solve_full_information_upper_bound(
            PayOrTestV3Plugin().validate_payload(case["payload"])).contribution_margin_usd, 2),
        "realized": realized(case["payload"]),
    }
    return case, entry


def _admits(job: tuple[Mapping[str, Any], int]) -> bool:
    spec, seed = job
    return admit(spec, seed, draw_structure(spec, seed))[0]


def scan(spec: Mapping[str, Any], workers: int = 1) -> tuple[dict[str, Any], dict[str, Any]]:
    """The first seed in a cell's block that admits a world, as its case and manifest entry.

    With ``workers`` above one, seeds are screened in parallel in order, a chunk at a time, and the lowest admitted
    seed is taken: the same world a sequential scan finds.
    """
    seeds = range(spec["seed_block"], spec["seed_block"] + SEEDS_PER_WORLD)
    if workers <= 1:
        for scanned, seed in enumerate(seeds, start=1):
            found = world_at(spec, seed, scanned)
            if found is not None:
                return found
    else:
        from concurrent.futures import ProcessPoolExecutor

        chunk = workers * 8
        with ProcessPoolExecutor(workers) as pool:
            for offset in range(0, len(seeds), chunk):
                block = list(seeds[offset:offset + chunk])
                for k, ok in enumerate(pool.map(_admits, [(spec, seed) for seed in block])):
                    if ok:
                        found = world_at(spec, block[k], offset + k + 1)
                        if found is None:
                            raise RuntimeError(f"seed {block[k]} admitted in a worker but not on rebuild")
                        return found
    raise RuntimeError(f"no seed in the block admits a world for {spec['slug']}")


def build_pack(entries: Sequence[tuple[dict[str, Any], dict[str, Any]]] | None = None,
               split: str = PILOT_PACK_ID, workers: int = 1) -> dict[str, Any]:
    built = list(entries) if entries is not None else [scan(spec, workers) for spec in world_specs(split)]
    cases = [case for case, _ in built]
    worlds = [entry for _, entry in built]
    names = list(RULES)
    mean_loss = {name: round(statistics.fmean(w["rule_loss_usd"][name] for w in worlds), 2) for name in names}
    if mean_loss["one_step_value"] < MEAN_MARGIN_USD:
        raise RuntimeError(f"mean one-step loss {mean_loss['one_step_value']} is under {MEAN_MARGIN_USD}")
    manifest = {
        "schema_version": PACK_SCHEMA, "pack_id": split,
        "generator": {"id": GENERATOR_ID, "version": GENERATOR_VERSION},
        "family": {"id": FAMILY_ID, "version": FAMILY_VERSION},
        "controls": {
            "budget_actions": BUDGET_ACTIONS, "target_kits": TARGET_KITS, "minimum_service_kits": MINIMUM_SERVICE_KITS,
            "revenue_per_kit_usd": REVENUE_PER_KIT_USD, "shortfall_penalty_usd": SHORTFALL_PENALTY_USD,
            "no_supply_value_usd": NO_SUPPLY_VALUE_USD, "cash_budget_usd": CASH_BUDGET_USD,
            "quote_fee_usd": QUOTE_FEE_USD, "quote_days": QUOTE_DAYS, "lookup_fee_usd": LOOKUP_FEE_USD,
            "lookup_days": LOOKUP_DAYS, "newcomer_sample_days": NEWCOMER_SAMPLE_DAYS,
            "established_sample": list(ESTABLISHED_SAMPLE), "answer_probability": round(ANSWER_PROBABILITY, 6),
            "record_discounts": list(RECORD_DISCOUNTS), "sample_fees_usd": list(SAMPLE_FEES_USD),
            "same_source_probabilities": list(SAME_SOURCE_PROBABILITIES), "deadlines": list(DEADLINES),
            "seed_start": SPLITS[split]["seed_start"], "seeds_per_world": SEEDS_PER_WORLD,
            "worlds_per_cell": SPLITS[split]["worlds_per_cell"],
            "good": {"on_time": GOOD_ON_TIME, "yield": GOOD_YIELD}, "late_on_time": LATE_ON_TIME, "poor_yield": POOR_YIELD,
        },
        "admission": {
            "margin_usd": MARGIN_USD, "mean_margin_usd": MEAN_MARGIN_USD, "stake_share": STAKE_SHARE,
            "information_headroom_usd": INFORMATION_HEADROOM_USD, "attribution_usd": ATTRIBUTION_USD,
            "rules_defeated_by_the_margin": list(ADMISSION_RULES),
            "reads": "the listings, the clock and the stated law; types, sharing, factories and replies are drawn afterwards",
        },
        "rules": {"screened": list(ADMISSION_RULES), "diagnostic": list(DIAGNOSTIC_RULES)},
        "worlds": worlds, "world_count": len(worlds),
        "seeds_scanned": sum(w["seeds_scanned"] for w in worlds),
        "seeds_scanned_by_cell": {kind: sum(w["seeds_scanned"] for w in worlds if w["kind"] == kind) for kind in KINDS},
        "expected_loss_usd_by_rule": mean_loss,
    }
    return {"manifest": manifest, "cases": cases}


def write_pack(root: Path | None = None, pack: Mapping[str, Any] | None = None, split: str = PILOT_PACK_ID,
               workers: int = 1) -> tuple[Path, ...]:
    destination = root or pack_root(split)
    destination.mkdir(parents=True, exist_ok=True)
    pack = pack or build_pack(split=split, workers=workers)
    written = []
    for name, body in [(f"{case['case_id'].rsplit('.', 1)[-1]}.json", case) for case in pack["cases"]] + [
        ("pack.json", pack["manifest"])
    ]:
        path = destination / name
        temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        written.append(path)
    return tuple(written)


def case_paths(root: Path | None = None, split: str = PILOT_PACK_ID) -> tuple[Path, ...]:
    return tuple(sorted(p for p in (root or pack_root(split)).glob("*.json") if p.name != "pack.json"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--split", choices=sorted(SPLITS), default=PILOT_PACK_ID)
    parser.add_argument("--workers", type=int, default=1, help="screen seeds in parallel; the pack is the same")
    arguments = parser.parse_args(argv)
    if arguments.write:
        for path in write_pack(arguments.root, split=arguments.split, workers=arguments.workers):
            print(path)
        return 0
    manifest = build_pack(split=arguments.split, workers=arguments.workers)["manifest"]
    print(json.dumps({"expected_loss_usd_by_rule": manifest["expected_loss_usd_by_rule"],
                      "seeds_scanned": manifest["seeds_scanned"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ADMISSION_RULES", "ANSWER_PROBABILITY", "KINDS", "MARGIN_USD", "PILOT_PACK_ID", "RECORD_DISCOUNTS", "SPLITS",
    "STAKE_SHARE", "admit", "build_case", "build_pack", "build_world", "case_paths", "classify", "draw_structure",
    "draw_types", "expected_full_information_value", "groups_of", "pack_root", "realized", "world_specs", "write_pack",
]
