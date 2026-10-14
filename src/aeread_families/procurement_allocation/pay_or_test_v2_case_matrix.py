"""Pay or test, version 2: newcomers of one kind may share a source, so a test can inform another listing.

Version 1 (``pay_or_test_case_matrix``) failed Gates 1 and 3 on one rule: compare
each untested newcomer with paying, one test ahead, keeping the recorded
supplier reachable. It gave up six cents a world against the best informed
policy and solved 23 of 24 worlds (the family QC profile, section 8). Its
newcomers were independent, so a test was worth only what it showed about the
listing tested, and one test ahead was enough.

Here new listings of one seller kind share a source with a probability the
case states (``policy.newcomer_sourcing.same_source_probability``). Sharing one,
they are all of one type, drawn with their cohort's shares; otherwise each is
drawn on its own with those shares. Each listing's own odds are still exactly
its cohort record. What changes is that a cheap sample on a small-discount
newcomer can be worth taking for what it says about a large-discount newcomer
of the same kind whose own sample is dear, and no rule looking one test ahead
sees that: the sample's worth lies in the test it makes worth taking next.
Nothing else moves. The environment applies types exactly as in version 1; the
shared source is a property of how this generator draws them, and the brief
(``pay_or_test_v2_prompt``) states it. Sample fees and discounts are drawn on
their own over wide ranges, because in version 1's ranges a shared source alone
leaves the one-step rule within cents of the best policy (incident row P-D-24).

Admission (``admit``) reads only what a buyer can see and the exact expected
value of each policy under the stated law. A world is admitted only if

1. the one-step rule (``pay_or_test_v2_reference.one_step_value``, which
   updates its odds after every result) gives up at least ``MARGIN_USD`` against
   the best informed policy, and so does version 1's one-step comparison, which
   reads each listing's own odds and ignores the shared source;
2. every fixed rule (pay the premium, test the cheapest once, test the best
   odds once, work up the price list until one qualifies) and the kind-blind
   shortcut (sample the cheapest sample first, then look one test ahead;
   incident row P-D-25) give up at least ``MARGIN_USD`` as well;
3. the full-information value, the environment's bound averaged over every way
   the newcomers could turn out under the stated law, exceeds the best policy
   by at least ``INFORMATION_HEADROOM_USD``;
4. with the source never shared (``same_source_probability`` 0 on the same
   listings), the one-step rule is within ``ATTRIBUTION_USD`` of that world's
   best policy: the shortfall is the shared source's doing, not the clock's or
   the prices'.

The pack as a whole must also show a mean one-step loss of at least
``MEAN_MARGIN_USD``. Types are drawn after admission, on their own stream.

Cells are named by where the one-step rule's first request goes and by the
clock: ``myopic_pays`` (to the recorded supplier: it pays the premium while the
best policy tests a newcomer) and ``myopic_tests`` (to a newcomer: it tests one
directly where the best policy first takes a test for what it tells about
another), each on a ``tight`` clock (one full newcomer test fits before the
recorded supplier) and a ``loose`` one (two).
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from .environment import ProcurementAllocationPlugin, _validate_payload, solve_full_information_upper_bound
from .pay_or_test_case_matrix import COMPONENT, VARIANT, _supplier
from .pay_or_test_reference import GOOD, GOOD_ON_TIME, GOOD_YIELD, LATE, LATE_ON_TIME, POOR, POOR_YIELD
from .pay_or_test_v2_reference import (
    DIAGNOSTIC_RULES, FIXED_RULES, LOOKAHEAD_RULES, RULES, SHORTCUT_RULES, SOURCING_FIELD, Reference, play, score_actions,
)

GENERATOR_ID = "procurement_allocation_pay_or_test_case_matrix_v2"
GENERATOR_VERSION = "2.0.0"
PACK_ID = "pay_or_test_v2"
PACK_SCHEMA = "aeread.procurement_pay_or_test_pack/0.2"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = REPOSITORY_ROOT / "cases" / "procurement_allocation_v1" / PACK_ID

KINDS = ("myopic_pays", "myopic_tests")
CLOCKS = ("tight", "loose")
CELLS: tuple[tuple[str, str], ...] = tuple(itertools.product(KINDS, CLOCKS))
CLOCK_TESTS = {"tight": 1, "loose": 2}
WORLDS_PER_CELL = 6
#: Disjoint from version 1 (8 839 800 to 8 912 000) and the inference packs (8 810 000 to 8 830 719).
SEED_START = 8_950_000
SEEDS_PER_WORLD = 5_000

TARGET_KITS, MINIMUM_SERVICE_KITS = 50, 40
REVENUE_PER_KIT_USD, SHORTFALL_PENALTY_USD = 37.0, 12.0
#: Version 1's $2,500 could bind once a sample costs up to $240; the reference treats information cost as additive.
CASH_BUDGET_USD = 3000.0
NO_SUPPLY_VALUE_USD = -SHORTFALL_PENALTY_USD * TARGET_KITS
BUDGET_ACTIONS = 10
QUOTE_FEE_USD, QUOTE_DAYS = 2.0, 1
INQUIRY_FEE_USD, COUNTER_FEE_USD = 1.0, 1.0
ESTABLISHED_SAMPLE = (30.0, 2)
ESTABLISHED_LEAD_DAYS = 6
NEWCOMER_SAMPLE_DAYS = 3
NEWCOMER_COUNT = 3
INSPECTED_UNITS = 100
COHORT_TRACKED = 40
SELLER_KINDS = ("manufacturer", "trading company")
#: What the generator may draw. Discounts are off the recorded supplier's price; a newcomer's
#: discount and its sample fee are drawn on their own, so a cheap sample can sit on a small discount.
DISCOUNTS = (0.02, 0.04, 0.06, 0.08, 0.24, 0.28, 0.32, 0.36, 0.40)
SAMPLE_FEES_USD = (20.0, 25.0, 30.0, 40.0, 120.0, 160.0, 200.0, 240.0)
NEWCOMER_LEAD_DAYS = (5, 6, 7, 8)
COHORT_LATE = (2, 4, 6)
COHORT_FAILED = (18, 22, 26, 30)
SAME_SOURCE_PROBABILITIES = (0.8, 0.9, 0.95)

#: Admission margins (see the module docstring and ``admit``).
MARGIN_USD = 10.0
MEAN_MARGIN_USD = 15.0
INFORMATION_HEADROOM_USD = 10.0
ATTRIBUTION_USD = 5.0
#: Rules every admitted world must defeat by ``MARGIN_USD``.
ADMISSION_RULES = (*LOOKAHEAD_RULES, *FIXED_RULES, *SHORTCUT_RULES)


def world_specs() -> tuple[dict[str, Any], ...]:
    specs = []
    for cell_index, (kind, clock) in enumerate(CELLS):
        for k in range(WORLDS_PER_CELL):
            ordinal = cell_index * WORLDS_PER_CELL + k
            specs.append({"slug": f"{kind}__{clock}__{k + 1}", "kind": kind, "clock": clock,
                          "ordinal": ordinal + 1, "seed_block": SEED_START + ordinal * SEEDS_PER_WORLD})
    return tuple(specs)


def draw_structure(spec: Mapping[str, Any], seed: int) -> dict[str, Any]:
    """Everything a buyer can see, and nothing about how the newcomers turn out."""
    rng = random.Random(f"{GENERATOR_ID}:{seed}")
    codes = rng.sample(range(100, 1000), NEWCOMER_COUNT + 1)
    established_price = round(round(rng.uniform(24.0, 28.0) / 0.05) * 0.05, 2)
    orders = rng.randrange(48, 97)
    cohorts = {kind: {"late": rng.choice(COHORT_LATE), "failed": rng.choice(COHORT_FAILED)} for kind in SELLER_KINDS}
    newcomers = []
    for discount in rng.sample(DISCOUNTS, NEWCOMER_COUNT):
        kind = rng.choice(SELLER_KINDS)
        newcomers.append({
            "discount": discount, "price": round(established_price * (1.0 - discount), 2), "kind": kind,
            "sample_fee_usd": rng.choice(SAMPLE_FEES_USD), "lead_days": rng.choice(NEWCOMER_LEAD_DAYS),
            "late": cohorts[kind]["late"], "failed": cohorts[kind]["failed"],
        })
    one_test = QUOTE_DAYS + NEWCOMER_SAMPLE_DAYS
    fall_back = QUOTE_DAYS + ESTABLISHED_SAMPLE[1] + ESTABLISHED_LEAD_DAYS
    return {
        "codes": codes, "established_price": established_price, "established_orders": orders,
        "established_late": round(orders * (1.0 - GOOD_ON_TIME)),
        "established_kind": rng.choice(SELLER_KINDS),
        "newcomers": newcomers,
        "same_source_probability": rng.choice(SAME_SOURCE_PROBABILITIES),
        "deadline_days": CLOCK_TESTS[spec["clock"]] * one_test + fall_back + rng.randrange(2),
        "product_id": f"kit_{rng.randrange(1000, 10000)}",
        "listing_order": rng.sample(range(NEWCOMER_COUNT + 1), NEWCOMER_COUNT + 1),
    }


def groups_of(structure: Mapping[str, Any]) -> tuple[tuple[int, ...], ...]:
    """Newcomer positions (0-based, in ``structure['newcomers']`` order) that may share a source, by kind."""
    by_kind: dict[str, list[int]] = {}
    for i, newcomer in enumerate(structure["newcomers"]):
        by_kind.setdefault(newcomer["kind"], []).append(i)
    return tuple(tuple(members) for _, members in sorted(by_kind.items()))


def _draw_one(rng: random.Random, newcomer: Mapping[str, Any]) -> str:
    roll = rng.random() * COHORT_TRACKED
    return LATE if roll < newcomer["late"] else POOR if roll < newcomer["late"] + newcomer["failed"] else GOOD


def draw_types(structure: Mapping[str, Any], seed: int) -> tuple[str, ...]:
    """Each newcomer's type, under the stated law, on a stream of its own.

    For each seller kind: with the stated probability its newcomers share a
    source and take one type drawn with the cohort's shares; otherwise each
    takes its own draw with those shares.
    """
    rng = random.Random(f"{GENERATOR_ID}:{seed}:types")
    types: list[str | None] = [None] * len(structure["newcomers"])
    for members in groups_of(structure):
        shared = rng.random() < structure["same_source_probability"]
        if shared:
            kind_of = _draw_one(rng, structure["newcomers"][members[0]])
            for i in members:
                types[i] = kind_of
        else:
            for i in members:
                types[i] = _draw_one(rng, structure["newcomers"][i])
    return tuple(t for t in types if t is not None)


def build_case(spec: Mapping[str, Any], seed: int, structure: Mapping[str, Any], types: Sequence[str],
               *, seal: bool = True) -> dict[str, Any]:
    """The case for a structure and a draw of types. ``seal=False`` skips validation and the digest, for screening."""
    codes = structure["codes"]
    orders = structure["established_orders"]
    suppliers = [_supplier(
        f"l{codes[0]}", price=structure["established_price"], lead=ESTABLISHED_LEAD_DAYS, sample=ESTABLISHED_SAMPLE,
        kind=structure["established_kind"], on_time=GOOD_ON_TIME, yield_rate=GOOD_YIELD,
        record={"orders_reported": orders, "late_deliveries": structure["established_late"],
                "units_inspected": orders * 25, "defective_units": round(orders * 25 * (1.0 - GOOD_YIELD)),
                "largest_order_filled_units": 60},
        cohort=None,
    )]
    for code, newcomer, kind_of in zip(codes[1:], structure["newcomers"], types):
        suppliers.append(_supplier(
            f"l{code}", price=newcomer["price"], lead=newcomer["lead_days"],
            sample=(newcomer["sample_fee_usd"], NEWCOMER_SAMPLE_DAYS), kind=newcomer["kind"],
            on_time=LATE_ON_TIME if kind_of == LATE else GOOD_ON_TIME,
            yield_rate=POOR_YIELD if kind_of == POOR else GOOD_YIELD,
            record={"orders_reported": 0, "late_deliveries": None, "units_inspected": 0,
                    "defective_units": None, "largest_order_filled_units": None},
            cohort={"cohort": f"{newcomer['kind']}, new to this marketplace",
                    "sellers_tracked": COHORT_TRACKED, "unreliable_on_delivery": newcomer["late"],
                    "failed_inspection": newcomer["failed"]},
        ))
    suppliers = [suppliers[i] for i in structure["listing_order"]]
    case: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": f"procurement_allocation_v1.{PACK_ID}.{spec['slug']}",
        "family_id": "procurement_allocation_v1",
        "family_version": "1.0.0",
        "split": PACK_ID,
        "world_seed": seed,
        "seats": [{"id": "buyer", "role": "buyer"}],
        "episode": {"max_logical_actions": BUDGET_ACTIONS,
                    "termination": ["submitted", "deferred", "interaction_budget_exhausted", "invalid_action"]},
        "visibility_policy": "procurement_allocation_public_listings_private_supplier_terms_v1",
        "payload": {
            "objective": {
                "product_id": structure["product_id"],
                "target_kits": TARGET_KITS, "minimum_service_kits": MINIMUM_SERVICE_KITS,
                "revenue_per_completed_kit_usd": REVENUE_PER_KIT_USD,
                "shortfall_penalty_per_kit_usd": SHORTFALL_PENALTY_USD,
                "cash_budget_usd": CASH_BUDGET_USD,
                "deadline_days": structure["deadline_days"],
                "defect_detection_days": 10, "working_capital_horizon_days": 45,
                "annual_financing_rate": 0.12, "defer_value_usd": NO_SUPPLY_VALUE_USD,
                "bom": {COMPONENT: 1},
            },
            "interaction": {
                "max_actions": BUDGET_ACTIONS, "inquiry_days": 1, "quote_days": QUOTE_DAYS, "counter_days": 1,
                "inquiry_cost_usd": INQUIRY_FEE_USD, "quote_cost_usd": QUOTE_FEE_USD, "counter_cost_usd": COUNTER_FEE_USD,
            },
            "policy": {
                "required_variant_by_component": {COMPONENT: VARIANT},
                "inquiry_fields": ["exact_variant", "moq_capacity", "lead_time", "shipping", "quality",
                                   "sample_logistics", "return_refund_policy"],
                "award_requires": ["unexpired_formal_offer", "verified_sample", "exact_variant"],
                "process": {"quote_fee_usd": QUOTE_FEE_USD, "quote_days": QUOTE_DAYS,
                            "inquiry_fee_usd": INQUIRY_FEE_USD, "inquiry_days": 1,
                            "counter_fee_usd": COUNTER_FEE_USD, "counter_days": 1},
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
    ProcurementAllocationPlugin().validate_payload(manifest.payload)
    case["content_sha256"] = case_content_sha256(manifest)
    return case


def _blind(spec: Mapping[str, Any], seed: int, structure: Mapping[str, Any], rho: float | None = None) -> dict[str, Any]:
    """The payload with every newcomer good: what admission reads, since the reference never looks at types."""
    shown = structure if rho is None else {**structure, "same_source_probability": rho}
    return build_case(spec, seed, shown, tuple(GOOD for _ in structure["newcomers"]), seal=False)["payload"]


def expected_full_information_value(payload: Mapping[str, Any]) -> float:
    """The environment's full-information bound averaged over every type profile under the stated law."""
    ref = Reference(payload)
    total = 0.0
    for types, weight in ref.joint_prior():
        trial = json.loads(json.dumps(payload))
        by_index = {ref.ids[i]: t for i, t in zip(ref.newcomers, types)}
        for supplier in trial["suppliers"]:
            kind_of = by_index.get(supplier["supplier_id"])
            if kind_of is None:
                continue
            terms = supplier["private_terms"]
            terms["on_time_probability"] = LATE_ON_TIME if kind_of == LATE else GOOD_ON_TIME
            terms["quality"]["verified_yield_rate"] = POOR_YIELD if kind_of == POOR else GOOD_YIELD
            terms["quality"]["observed_defects"] = round(INSPECTED_UNITS * (1.0 - terms["quality"]["verified_yield_rate"]))
        total += weight * solve_full_information_upper_bound(_validate_payload(trial)).contribution_margin_usd
    return total


def _first(ref: Reference, action: tuple[Any, ...]) -> str:
    if action[0] in ("request_quote", "request_sample"):
        return f"{action[0]} {ref.ids[action[1]]}"
    if action[0] == "submit_award":
        return f"submit_award {ref.ids[action[1]]}"
    return "defer"


def kind_of_first(ref: Reference, action: tuple[Any, ...]) -> str | None:
    """``myopic_pays`` if the one-step rule's first request goes to the recorded supplier, ``myopic_tests`` if to a newcomer."""
    if action[0] not in ("request_quote", "request_sample"):
        return None
    return "myopic_pays" if action[1] in ref.established else "myopic_tests"


def classify(payload: Mapping[str, Any], *, full_information: bool = True) -> dict[str, Any]:
    """Exact values a world's admission is decided on. Reads nothing a buyer cannot see."""
    ref = Reference(payload)
    start = ref.start()
    best = ref.value(*start)
    values = {name: ref.rule_value(name, rule, *start) for name, rule in RULES.items()}
    status, left, day = start
    myopic = RULES["one_step_value"](ref, status, left, day)
    first = ref.best_action(*start)
    found = {
        "best_policy_value_usd": round(best, 2),
        "rule_value_usd": {name: round(v, 2) for name, v in values.items()},
        "rule_loss_usd": {name: round(best - v, 2) for name, v in values.items()},
        "best_first_action": _first(ref, first),
        "one_step_first_action": _first(ref, myopic),
        "kind": kind_of_first(ref, myopic),
        "same_source_groups": [[ref.ids[i] for i in members] for members in ref.groups],
    }
    if full_information:
        found["expected_full_information_value_usd"] = round(expected_full_information_value(payload), 2)
    return found


def admit(spec: Mapping[str, Any], seed: int, structure: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Whether a structure is admitted to its cell, and the exact values behind the verdict.

    Cheap checks first: the one-step rule's loss, then the other rules, then the
    attribution counterfactual, and the full-information average last.
    """
    payload = _blind(spec, seed, structure)
    ref = Reference(payload)
    start = ref.start()
    best = ref.value(*start)
    reasons: dict[str, Any] = {"best_policy_value_usd": round(best, 2)}
    if not any(len(members) > 1 for members in ref.groups):
        return False, {**reasons, "rejected": "no two newcomers share a kind"}
    one_step = best - ref.rule_value("one_step_value", RULES["one_step_value"], *start)
    if one_step < MARGIN_USD:
        return False, {**reasons, "rejected": "one_step_value within the margin", "loss": round(one_step, 2)}
    for name in ADMISSION_RULES:
        loss = best - ref.rule_value(name, RULES[name], *start)
        if loss < MARGIN_USD:
            return False, {**reasons, "rejected": f"{name} within the margin", "loss": round(loss, 2)}
    found = classify(payload, full_information=False)
    if found["kind"] != spec["kind"]:
        return False, {**reasons, "rejected": f"kind {found['kind']}"}
    independent = Reference(_blind(spec, seed, structure, rho=0.0))
    i_start = independent.start()
    i_loss = independent.value(*i_start) - independent.rule_value("one_step_value", RULES["one_step_value"], *i_start)
    if i_loss >= ATTRIBUTION_USD:
        return False, {**reasons, "rejected": "one_step_value falls short without a shared source", "loss": round(i_loss, 2)}
    full = expected_full_information_value(payload)
    if full - best < INFORMATION_HEADROOM_USD:
        return False, {**reasons, "rejected": "no information headroom", "headroom": round(full - best, 2)}
    found["expected_full_information_value_usd"] = round(full, 2)
    found["one_step_loss_without_shared_source_usd"] = round(i_loss, 2)
    return True, found


def build_world(spec: Mapping[str, Any], seed: int) -> dict[str, Any] | None:
    """The world for a cell at one seed, or ``None`` if its structure is not admitted there."""
    structure = draw_structure(spec, seed)
    admitted, found = admit(spec, seed, structure)
    if not admitted:
        return None
    types = draw_types(structure, seed)
    case = build_case(spec, seed, structure, types)
    return {"case": case, "types": types, "structure": structure, "classification": found}


def realized(payload: Mapping[str, Any]) -> dict[str, Any]:
    """What the best policy and each rule earn on the world as it turned out."""
    rows = {}
    for name, rule in [("best_policy", None), *RULES.items()]:
        scored = score_actions(payload, play(payload, rule))
        outcome = scored["outcome"]
        rows[name] = {"margin_usd": round(float(outcome["contribution_margin_usd"]), 2),
                      "decision_loss_usd": round(scored["decision_loss_usd"], 2),
                      "actions": len(scored["steps"]), "days": int(outcome["elapsed_days"])}
    return rows


def world_at(spec: Mapping[str, Any], seed: int, scanned: int) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """The case and the manifest entry for a cell at one seed, or ``None`` if the seed is not admitted there."""
    built = build_world(spec, seed)
    if built is None:
        return None
    case, found, structure = built["case"], built["classification"], built["structure"]
    newcomers = []
    for position, (code, n) in enumerate(zip(structure["codes"][1:], structure["newcomers"])):
        newcomers.append({"supplier_id": f"{COMPONENT}_l{code}", "price_usd": n["price"], "discount": n["discount"],
                          "kind": n["kind"], "sample_fee_usd": n["sample_fee_usd"], "lead_days": n["lead_days"],
                          "stated_good_share": round(1.0 - (n["late"] + n["failed"]) / COHORT_TRACKED, 4),
                          "stated_late_share": n["late"] / COHORT_TRACKED,
                          "stated_poor_share": n["failed"] / COHORT_TRACKED,
                          "type": built["types"][position]})
    entry = {
        "slug": spec["slug"], "kind": spec["kind"], "clock": spec["clock"],
        "world_seed": seed, "seeds_scanned": scanned,
        "case_id": case["case_id"], "content_sha256": case["content_sha256"],
        "deadline_days": structure["deadline_days"],
        "same_source_probability": structure["same_source_probability"],
        "established": {"supplier_id": f"{COMPONENT}_l{structure['codes'][0]}", "price_usd": structure["established_price"]},
        "newcomers": newcomers,
        **{k: found[k] for k in ("best_policy_value_usd", "rule_value_usd", "rule_loss_usd", "best_first_action",
                                 "one_step_first_action", "same_source_groups", "expected_full_information_value_usd",
                                 "one_step_loss_without_shared_source_usd")},
        "realized_upper_bound_usd": round(solve_full_information_upper_bound(case["payload"]).contribution_margin_usd, 2),
        "realized": realized(case["payload"]),
    }
    return case, entry


def scan(spec: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The first seed in a cell's block that admits a world, as its case and manifest entry."""
    for scanned, seed in enumerate(range(spec["seed_block"], spec["seed_block"] + SEEDS_PER_WORLD), start=1):
        found = world_at(spec, seed, scanned)
        if found is not None:
            return found
    raise RuntimeError(f"no seed in the block admits a world for {spec['slug']}")


def build_pack(entries: Sequence[tuple[dict[str, Any], dict[str, Any]]] | None = None) -> dict[str, Any]:
    """The pack: every cell's first admitted world, or ``entries`` already built in ``world_specs`` order."""
    built = list(entries) if entries is not None else [scan(spec) for spec in world_specs()]
    cases = [case for case, _ in built]
    worlds = [entry for _, entry in built]
    scanned_total = sum(w["seeds_scanned"] for w in worlds)
    names = list(RULES)
    mean_loss = {name: round(statistics.fmean(w["rule_loss_usd"][name] for w in worlds), 2) for name in names}
    if mean_loss["one_step_value"] < MEAN_MARGIN_USD:
        raise RuntimeError(f"mean one-step loss {mean_loss['one_step_value']} is under {MEAN_MARGIN_USD}")
    manifest = {
        "schema_version": PACK_SCHEMA, "pack_id": PACK_ID,
        "generator": {"id": GENERATOR_ID, "version": GENERATOR_VERSION},
        "controls": {
            "budget_actions": BUDGET_ACTIONS, "target_kits": TARGET_KITS, "minimum_service_kits": MINIMUM_SERVICE_KITS,
            "revenue_per_kit_usd": REVENUE_PER_KIT_USD, "shortfall_penalty_usd": SHORTFALL_PENALTY_USD,
            "no_supply_value_usd": NO_SUPPLY_VALUE_USD, "cash_budget_usd": CASH_BUDGET_USD,
            "quote_fee_usd": QUOTE_FEE_USD, "quote_days": QUOTE_DAYS, "newcomer_sample_days": NEWCOMER_SAMPLE_DAYS,
            "established_sample": list(ESTABLISHED_SAMPLE), "seed_start": SEED_START, "seeds_per_world": SEEDS_PER_WORLD,
            "worlds_per_cell": WORLDS_PER_CELL, "same_source_probabilities": list(SAME_SOURCE_PROBABILITIES),
            "good": {"on_time": GOOD_ON_TIME, "yield": GOOD_YIELD}, "late_on_time": LATE_ON_TIME, "poor_yield": POOR_YIELD,
        },
        "admission": {
            "margin_usd": MARGIN_USD, "mean_margin_usd": MEAN_MARGIN_USD,
            "information_headroom_usd": INFORMATION_HEADROOM_USD, "attribution_usd": ATTRIBUTION_USD,
            "rules_defeated_by_the_margin": list(ADMISSION_RULES),
            "reads": "the listings, the clock and the stated law; types are drawn afterwards on their own stream",
        },
        "rules": {"screened": list(ADMISSION_RULES), "diagnostic": list(DIAGNOSTIC_RULES)},
        "worlds": worlds,
        "world_count": len(worlds),
        "seeds_scanned": scanned_total,
        "seeds_scanned_by_cell": {f"{kind}__{clock}": sum(w["seeds_scanned"] for w in worlds
                                                          if (w["kind"], w["clock"]) == (kind, clock))
                                  for kind, clock in CELLS},
        "expected_loss_usd_by_rule": mean_loss,
    }
    return {"manifest": manifest, "cases": cases}


def write_pack(root: Path | None = None, pack: Mapping[str, Any] | None = None) -> tuple[Path, ...]:
    destination = root or PACK_ROOT
    destination.mkdir(parents=True, exist_ok=True)
    pack = pack or build_pack()
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


def case_paths(root: Path | None = None) -> tuple[Path, ...]:
    return tuple(sorted(p for p in (root or PACK_ROOT).glob("*.json") if p.name != "pack.json"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--root", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.write:
        for path in write_pack(arguments.root):
            print(path)
        return 0
    manifest = build_pack()["manifest"]
    print(json.dumps({"expected_loss_usd_by_rule": manifest["expected_loss_usd_by_rule"],
                      "seeds_scanned": manifest["seeds_scanned"],
                      "worlds": [{k: w[k] for k in ("slug", "world_seed", "seeds_scanned", "best_first_action",
                                                    "one_step_first_action")} for w in manifest["worlds"]]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ADMISSION_RULES", "ATTRIBUTION_USD", "CELLS", "CLOCK_TESTS", "GENERATOR_ID", "INFORMATION_HEADROOM_USD",
    "MARGIN_USD", "MEAN_MARGIN_USD", "PACK_ID", "PACK_ROOT", "admit", "build_case", "build_pack", "build_world",
    "case_paths", "classify", "draw_structure", "draw_types", "expected_full_information_value", "groups_of",
    "realized", "world_specs", "write_pack",
]
