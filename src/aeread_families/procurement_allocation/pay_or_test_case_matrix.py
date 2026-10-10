"""Pay or test: one supplier with a record, three cheaper ones without.

The decision. A buyer needs fifty kits by a deadline. One listing has a long
clean record and the highest price. Three are new, cheaper, and carry only what
the marketplace found when it tracked new sellers of their kind: how many
proved unreliable on delivery and how many failed inspection. A formal quote costs a little and
a day and shows whether a supplier delivers on time; a sample costs real money
and three days and shows its yield. Every award needs both. So the buyer can
pay the premium, or spend money and days finding out whether a cheaper
supplier is any good, and has to decide whom to test, in what order, and when
to stop and take what it has.

What is different from the inference packs.

- **The margin is thin.** Parts are about three quarters of revenue, so the
  premium is a large share of the profit and so is a sample fee.
- **Days bind, actions do not.** Ten actions cover every quote and sample in
  the world. The deadline does not: in a tight world one failed test still
  leaves time for the recorded supplier and a second does not.
- **Nothing is hidden behind a default.** The listing states its price, its
  lead time, its sample fee and days, and its record. What is not known is a
  supplier's type, and its odds are stated.
- **A sample settles yield.** No sampling noise is declared. With noise the
  environment's pre-award check reveals the true yield for one free action
  (incident row P-D-17), which would make a second batch pointless.

Worlds are admitted on their structure alone, never on how the suppliers
turned out: ``classify`` sees prices, fees, days and stated odds, and the types
are drawn afterwards from those odds with their own random stream. A screen
that looked at outcomes would select on luck (the Housing lemons pack did
exactly that, HL-D-03).

Six cells, four worlds each, named by the best plan and the clock.

- ``pay_money`` (tight clock): paying the premium is the best policy and every
  single test loses at least ``DECISIVE_USD`` against it, because the discounts
  are small, the odds poor or the samples dear.
- ``pay_time`` (no spare time): the same world with a few more days would say
  test, but a failed test leaves no time for the recorded supplier, so a test
  bets the whole order.
- ``test_cheapest`` and ``test_other``, each with a ``tight`` and a ``loose``
  clock: testing one newcomer first beats paying by at least that much, and
  the one to test is, or is not, the cheapest listing.

A tight clock fits one full test before the recorded supplier, a loose one two.
The cells are sampled evenly, which is not how the generator's draws fall:
``natural_mix`` in the manifest says how often each kind of world comes up.

No pinned module changes. The record, the cohort record, the sample fee and
the process costs are extra fields on the listing and the policy block, which
the environment hands to the buyer as they are.
"""

from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from .environment import ProcurementAllocationPlugin, solve_full_information_upper_bound
from .pay_or_test_reference import (
    GOOD, GOOD_ON_TIME, GOOD_YIELD, LATE, LATE_ON_TIME, POOR, POOR_YIELD, RULES, Reference,
    cheapest_newcomer, play, score_actions, test_once,
)

GENERATOR_ID = "procurement_allocation_pay_or_test_case_matrix_v1"
GENERATOR_VERSION = "1.0.0"
PACK_ID = "pay_or_test_v1"
PACK_SCHEMA = "aeread.procurement_pay_or_test_pack/0.1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = REPOSITORY_ROOT / "cases" / "procurement_allocation_v1" / PACK_ID

COMPONENT, VARIANT = "driver_board", "driver_board_rev_c"
CELLS: tuple[tuple[str, str], ...] = (
    ("pay_money", "tight"), ("pay_time", "none"),
    ("test_cheapest", "tight"), ("test_cheapest", "loose"),
    ("test_other", "tight"), ("test_other", "loose"),
)
#: Full newcomer tests that fit before the recorded supplier still delivers.
CLOCK_TESTS = {"none": 0, "tight": 1, "loose": 2}
WORLDS_PER_CELL = 4
NATURAL_MIX_SEEDS = 200
#: Disjoint from the inference packs (8810000 to 8830719). Each world takes the
#: first seed in its own block whose structure falls in its cell.
SEED_START = 8840000
SEEDS_PER_WORLD = 3000

TARGET_KITS, MINIMUM_SERVICE_KITS = 50, 40
REVENUE_PER_KIT_USD, SHORTFALL_PENALTY_USD, CASH_BUDGET_USD = 37.0, 12.0, 2500.0
#: Supplying nothing is fifty kits short. Walking away, running out of actions and an award under the
#: minimum all end here, so a test that leaves no time for the recorded supplier bets this.
NO_SUPPLY_VALUE_USD = -SHORTFALL_PENALTY_USD * TARGET_KITS
CAPACITY, MOQ, ORDER_STEP = 60, 50, 5
SHIPPING_PER_UNIT_USD = 0.60
BUDGET_ACTIONS = 10
QUOTE_FEE_USD, QUOTE_DAYS = 2.0, 1
INQUIRY_FEE_USD, COUNTER_FEE_USD = 1.0, 1.0
ESTABLISHED_SAMPLE = (30.0, 2)  # fee, days
ESTABLISHED_LEAD_DAYS = 6
NEWCOMER_SAMPLE_DAYS = 3
NEWCOMER_COUNT = 3
INSPECTED_UNITS = 100
COHORT_TRACKED = 40
#: What the generator may draw. Discounts are off the recorded supplier's price.
DISCOUNTS = (0.03, 0.05, 0.07, 0.09, 0.12, 0.15, 0.18, 0.21)
SAMPLE_FEES_USD = (30.0, 40.0, 50.0, 60.0, 70.0, 80.0)
NEWCOMER_LEAD_DAYS = (6, 7, 8)
COHORT_LATE = (4, 8)
COHORT_FAILED = (8, 14, 20, 24)
SELLER_KINDS = ("manufacturer", "trading company")
#: A cell's best plan beats the alternatives it is defined against by at least this.
DECISIVE_USD = 8.0
#: In a pay world the best policy is paying, to within this.
CLOSE_USD = 1.0


def world_specs() -> tuple[dict[str, Any], ...]:
    specs = []
    for cell_index, (move, clock) in enumerate(CELLS):
        for k in range(WORLDS_PER_CELL):
            ordinal = cell_index * WORLDS_PER_CELL + k
            specs.append({"slug": f"{move}__{clock}__{k + 1}", "move": move, "clock": clock,
                          "ordinal": ordinal + 1, "seed_block": SEED_START + ordinal * SEEDS_PER_WORLD})
    return tuple(specs)


def _supplier(label: str, *, price: float, lead: int, sample: tuple[float, int], kind: str,
              on_time: float, yield_rate: float, record: Mapping[str, Any],
              cohort: Mapping[str, Any] | None) -> dict[str, Any]:
    listing: dict[str, Any] = {
        "supplier_name": f"Listing {label.upper()}",
        "seller_kind": kind,
        "displayed_unit_price_usd": price,
        "claimed_lead_time_days": lead,
        "claimed_variant": VARIANT.replace("_", " "),
        "sample_fee_usd": sample[0],
        "sample_days": sample[1],
        "marketplace_record": dict(record),
        "evidence_status": "marketplace_listing_unverified",
    }
    if cohort is not None:
        listing["cohort_record"] = dict(cohort)
    return {
        "supplier_id": f"{COMPONENT}_{label}",
        "component": COMPONENT,
        "listing": listing,
        "private_terms": {
            "variant_id": VARIANT,
            "base_unit_price_usd": price,
            "shipping_per_unit_usd": SHIPPING_PER_UNIT_USD,
            "duty_rate": 0.0,
            "capacity": CAPACITY, "moq": MOQ, "order_step": ORDER_STEP,
            "lead_time_days": lead,
            "on_time_probability": on_time,
            "payment_terms_days": 30,
            "offer_valid_days": 60,
            "return_policy": {
                "refund_window_days": 30, "claim_acceptance_probability": 0.9, "restocking_fee_rate": 0.0,
                "return_freight_payer": "supplier", "return_freight_per_unit_usd": 0.0, "refund_delay_days": 10,
            },
            "quality": {
                "sample_size": INSPECTED_UNITS,
                "observed_defects": round(INSPECTED_UNITS * (1.0 - yield_rate)),
                "verified_yield_rate": yield_rate,
                "sample_cost_usd": sample[0],
                "sample_lead_time_days": sample[1],
            },
            # Asked in conversation, every seller says what a good one would. Only a
            # formal quote and a sample are binding.
            "verbal_bias": {"verified_yield_rate": GOOD_YIELD, "on_time_probability": GOOD_ON_TIME},
            "negotiation": {
                "floor_unit_price_usd": price, "minimum_moq": MOQ, "maximum_payment_terms_days": 30,
                "maximum_refund_window_days": 30, "supplier_paid_return_freight_available": False,
            },
        },
    }


def draw_structure(spec: Mapping[str, Any], seed: int) -> dict[str, Any]:
    """Everything a buyer can see, and nothing about how the newcomers turn out."""
    rng = random.Random(seed)
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
    tests = CLOCK_TESTS[spec["clock"]]
    return {
        "codes": codes, "established_price": established_price, "established_orders": orders,
        "established_late": round(orders * (1.0 - GOOD_ON_TIME)),
        "established_kind": rng.choice(SELLER_KINDS),
        "newcomers": newcomers,
        # Room for that many full tests before the recorded supplier, and a spare day in half the worlds.
        # With no test fitting, the spare days (one to three) still let a newcomer be tested and awarded.
        "deadline_days": tests * one_test + fall_back + (rng.randrange(2) if tests else rng.randrange(1, 4)),
        "product_id": f"kit_{rng.randrange(1000, 10000)}",
        "listing_order": rng.sample(range(NEWCOMER_COUNT + 1), NEWCOMER_COUNT + 1),
    }


def draw_types(structure: Mapping[str, Any], seed: int) -> tuple[str, ...]:
    """Each newcomer's type, from the shares its listing states, on a stream of its own."""
    rng = random.Random(f"{seed}:types")
    types = []
    for newcomer in structure["newcomers"]:
        roll = rng.random() * COHORT_TRACKED
        types.append(LATE if roll < newcomer["late"] else POOR if roll < newcomer["late"] + newcomer["failed"] else GOOD)
    return tuple(types)


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
                "largest_order_filled_units": CAPACITY},
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
                # The interaction block is not shown to the buyer; what a request costs is.
                "process": {"quote_fee_usd": QUOTE_FEE_USD, "quote_days": QUOTE_DAYS,
                            "inquiry_fee_usd": INQUIRY_FEE_USD, "inquiry_days": 1,
                            "counter_fee_usd": COUNTER_FEE_USD, "counter_days": 1},
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


def classify(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Which cell a world's structure falls in. Reads nothing a buyer cannot."""
    ref = Reference(payload)
    start = ref.start()
    best = ref.value(*start)
    pay = ref.rule_value("pay_premium", RULES["pay_premium"], *start)
    once = {i: ref.rule_value(f"test_once:{i}", test_once(lambda _r, i=i: i), *start) for i in ref.newcomers}
    cheapest = cheapest_newcomer(ref)
    target = max(once, key=lambda i: (once[i], -i))
    others = [value for i, value in once.items() if i != target]
    move = None
    if pay >= max(once.values()) + DECISIVE_USD and best - pay <= CLOSE_USD:
        move = "pay"
    elif once[target] >= pay + DECISIVE_USD and once[target] >= max(others) + DECISIVE_USD:
        move = "test_cheapest" if target == cheapest else "test_other"
    first = ref.best_action(*start)
    return {
        "move": move,
        "best_policy_value_usd": round(best, 2),
        "pay_value_usd": round(pay, 2),
        "test_once_value_usd": {ref.ids[i]: round(value, 2) for i, value in once.items()},
        "best_single_test": ref.ids[target],
        "cheapest_newcomer": ref.ids[cheapest],
        "best_first_action": f"{first[0]} {ref.ids[first[1]]}" if first[0] != "defer" else "defer",
        "rule_value_usd": {name: round(ref.rule_value(name, rule, *start), 2) for name, rule in RULES.items()},
    }


def cell_of(spec: Mapping[str, Any], seed: int, structure: Mapping[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """The cell a structure falls in under its clock, and the reference values behind that."""
    # Classified with every newcomer good, so the answer cannot depend on the draw that follows.
    blind = build_case(spec, seed, structure, tuple(GOOD for _ in structure["newcomers"]), seal=False)
    found = classify(blind["payload"])
    move = found["move"]
    if move == "pay":
        # Why paying is right: the tests lose money even with time for one, or there is no time.
        one_test = QUOTE_DAYS + NEWCOMER_SAMPLE_DAYS
        roomy = {**structure, "deadline_days": structure["deadline_days"] + one_test}
        with_time = classify(build_case(spec, seed, roomy, tuple(GOOD for _ in structure["newcomers"]), seal=False)["payload"])["move"]
        if spec["clock"] == "none":
            move = "pay_time" if with_time in ("test_cheapest", "test_other") else None
        else:
            move = "pay_money"
    elif spec["clock"] == "none" and move is not None:
        move = "test_without_fallback"  # a test that bets the order and still wins: counted, not a cell
    return move, found


def build_world(spec: Mapping[str, Any], seed: int) -> dict[str, Any] | None:
    """The world for a cell at one seed, or ``None`` if its structure falls elsewhere."""
    structure = draw_structure(spec, seed)
    move, structure_class = cell_of(spec, seed, structure)
    if move != spec["move"]:
        return None
    types = draw_types(structure, seed)
    case = build_case(spec, seed, structure, types)
    return {"case": case, "types": types, "structure": structure, "classification": structure_class}


def realized(payload: Mapping[str, Any]) -> dict[str, Any]:
    """What the best policy and each rule earn on the world as it turned out."""
    rows = {}
    for name, rule in [("best_policy", None), *RULES.items()]:
        scored = score_actions(payload, play(payload, rule))
        outcome = scored["outcome"]
        rows[name] = {"margin_usd": round(float(outcome["contribution_margin_usd"]), 2),
                      "regret_to_upper_bound_usd": round(float(outcome["regret_to_upper_bound_usd"]), 2),
                      "decision_loss_usd": round(scored["decision_loss_usd"], 2),
                      "actions": len(scored["steps"]), "days": int(outcome["elapsed_days"])}
    return rows


def natural_mix() -> dict[str, dict[str, int]]:
    """How the generator's draws fall before any cell is asked for, by clock."""
    mix: dict[str, dict[str, int]] = {}
    for clock in CLOCK_TESTS:
        spec = {"slug": f"mix__{clock}", "move": None, "clock": clock}
        counts: dict[str, int] = {}
        for seed in range(SEED_START - NATURAL_MIX_SEEDS, SEED_START):
            move, _ = cell_of(spec, seed, draw_structure(spec, seed))
            counts[move or "undecided"] = counts.get(move or "undecided", 0) + 1
        mix[clock] = dict(sorted(counts.items()))
    return mix


def build_pack() -> dict[str, Any]:
    worlds, cases = [], []
    for spec in world_specs():
        admitted = None
        for scanned, seed in enumerate(range(spec["seed_block"], spec["seed_block"] + SEEDS_PER_WORLD), start=1):
            built = build_world(spec, seed)
            if built is not None:
                admitted = (seed, scanned, built)
                break
        if admitted is None:
            raise RuntimeError(f"no seed in the block admits a world for {spec['slug']}")
        seed, scanned, built = admitted
        case, classification = built["case"], built["classification"]
        by_code = {f"{COMPONENT}_l{code}": i for i, code in enumerate(built["structure"]["codes"])}
        newcomers = []
        for sid, i in sorted(by_code.items(), key=lambda kv: kv[1]):
            if i == 0:
                continue
            n = built["structure"]["newcomers"][i - 1]
            newcomers.append({"supplier_id": sid, "price_usd": n["price"], "discount": n["discount"], "kind": n["kind"],
                              "sample_fee_usd": n["sample_fee_usd"], "lead_days": n["lead_days"],
                              "stated_good_share": round(1.0 - (n["late"] + n["failed"]) / COHORT_TRACKED, 4),
                              "stated_late_share": n["late"] / COHORT_TRACKED,
                              "stated_poor_share": n["failed"] / COHORT_TRACKED,
                              "type": built["types"][i - 1]})
        cases.append(case)
        worlds.append({
            "slug": spec["slug"], "move": spec["move"], "clock": spec["clock"],
            "world_seed": seed, "seeds_scanned": scanned,
            "case_id": case["case_id"], "content_sha256": case["content_sha256"],
            "deadline_days": built["structure"]["deadline_days"],
            "established": {"supplier_id": f"{COMPONENT}_l{built['structure']['codes'][0]}",
                            "price_usd": built["structure"]["established_price"]},
            "newcomers": newcomers,
            **{k: classification[k] for k in ("best_policy_value_usd", "pay_value_usd", "test_once_value_usd",
                                              "best_single_test", "cheapest_newcomer", "best_first_action", "rule_value_usd")},
            "upper_bound_usd": round(solve_full_information_upper_bound(case["payload"]).contribution_margin_usd, 2),
            "realized": realized(case["payload"]),
        })
    names = list(RULES)
    manifest = {
        "schema_version": PACK_SCHEMA, "pack_id": PACK_ID,
        "generator": {"id": GENERATOR_ID, "version": GENERATOR_VERSION},
        "controls": {
            "budget_actions": BUDGET_ACTIONS, "target_kits": TARGET_KITS, "minimum_service_kits": MINIMUM_SERVICE_KITS,
            "revenue_per_kit_usd": REVENUE_PER_KIT_USD, "shortfall_penalty_usd": SHORTFALL_PENALTY_USD,
            "no_supply_value_usd": NO_SUPPLY_VALUE_USD,
            "quote_fee_usd": QUOTE_FEE_USD, "quote_days": QUOTE_DAYS, "newcomer_sample_days": NEWCOMER_SAMPLE_DAYS,
            "established_sample": list(ESTABLISHED_SAMPLE), "decisive_usd": DECISIVE_USD, "close_usd": CLOSE_USD,
            "seed_start": SEED_START, "seeds_per_world": SEEDS_PER_WORLD, "worlds_per_cell": WORLDS_PER_CELL,
            "good": {"on_time": GOOD_ON_TIME, "yield": GOOD_YIELD}, "late_on_time": LATE_ON_TIME, "poor_yield": POOR_YIELD,
        },
        "worlds": worlds,
        "world_count": len(worlds),
        "natural_mix": {"seeds_per_clock": NATURAL_MIX_SEEDS, "by_clock": natural_mix()},
        "expected_loss_usd_by_rule": {
            name: round(sum(w["best_policy_value_usd"] - w["rule_value_usd"][name] for w in worlds) / len(worlds), 2)
            for name in names
        },
    }
    return {"manifest": manifest, "cases": cases}


def write_pack(root: Path | None = None) -> tuple[Path, ...]:
    destination = root or PACK_ROOT
    destination.mkdir(parents=True, exist_ok=True)
    pack = build_pack()
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
                      "worlds": [{k: w[k] for k in ("slug", "world_seed", "seeds_scanned", "best_first_action")}
                                 for w in manifest["worlds"]]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BUDGET_ACTIONS", "CELLS", "CLOCK_TESTS", "GENERATOR_ID", "PACK_ID", "PACK_ROOT", "build_case", "build_pack",
    "build_world", "case_paths", "cell_of", "classify", "draw_structure", "draw_types", "natural_mix", "realized",
    "world_specs", "write_pack",
]
