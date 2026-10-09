"""Inference v2: whom to verify, read from a public record and carried to listings that have none.

What v1 measured (incident row P-D-15). The first inference panel put the signal
on one listing attribute and meant price to be a decoy elsewhere, but one fixed
decoy order left the cheapest listing good in every low-is-good world and bad in
every high-is-good one. It was played under a prompt that says to rank by landed
cost, and nothing on a listing said which way quality ran. So every subject
started at the cheapest listing and the panel's two halves were that starting
point being right or wrong, scored as all or nothing.

What changes here, and each change answers one part of that.

**There is something to read.** One of the two components has a public
marketplace record on every listing: orders reported and how many came late,
units inspected and how many were defective, the largest order filled in full.
The other component's listings are new and have none. The same kinds of seller
sell both, and the prompt says so. A buyer can see from the recorded component
which listing attribute separates reliable sellers from unreliable ones and in
which direction, and has to carry that to the component where it can see
nothing else.

**Only one attribute separates, and the others are crossed.** On each
component two suppliers are good and two are bad. The signal attribute splits
them; each of the other two attributes puts one good and one bad supplier at
each of its levels. Price is no longer a signal in disguise: in the twelve
worlds whose signal is lead time or minimum order, the cheapest unrecorded
listing is good in six and bad in six, and the dearest is the reverse.

**Verification is scarce, and the world says so.** Five actions: a quote and a
sample for one supplier of each component, and the award. The choice of whom
to verify is the decision, and a quote that prints a late or small supplier
(P-D-14) comes too late to search again.

**A wrong choice costs, it does not end the episode.** Minimum service is eight
kits of nineteen, so an award on a bad supplier keeps roughly a third of the
bound instead of none.

Nothing in the pinned modules changes: the record is an extra field on the
listing, which the environment passes to the buyer as it is.
"""

from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import ActionEnvelope

from .duediligence_case_matrix import _build_case, _supplier
from .environment import ProcurementAllocationPlugin, solve_full_information_upper_bound
from .inference_case_matrix import COMPONENTS, RISKS, SIGNALS
from .trajectory_analysis import SOLVED_REGRET_USD

GENERATOR_ID = "procurement_allocation_inference_case_matrix_v2"
GENERATOR_VERSION = "2.0.0"
PACK_ID = "inference_v2"
PACK_SCHEMA = "aeread.procurement_inference_v2_pack/0.1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = REPOSITORY_ROOT / "cases" / "procurement_allocation_v1" / PACK_ID

#: Disjoint from v1 (8810000 on) and the holdout draw (8820000 on). A cell takes
#: the first seed in its block whose world passes ``screen_world``.
SEED_START = 8830000
SEEDS_PER_CELL = 40

ATTRIBUTES: tuple[str, ...] = ("price", "lead_time", "moq")
#: The listing field that carries each attribute.
LISTING_FIELD = {"price": "displayed_unit_price_usd", "lead_time": "claimed_lead_time_days", "moq": "claimed_moq"}
BUDGET_ACTIONS = 5
TARGET_KITS = 19
MINIMUM_SERVICE_KITS = 8
SAMPLE_BATCH = 8
RECORD_ORDERS = 24
RECORD_UNITS = 160
GOOD_YIELD, GOOD_ON_TIME, GOOD_CAPACITY = 0.985, 0.99, 20
POOR_YIELD_RANGE, POOR_ON_TIME, POOR_CAPACITY = (0.50, 0.60), 0.55, 10
#: True lead days by level; the listing claims two days fewer.
LEAD_DAYS = ((5, 6), (8, 9))
MOQ_LEVELS = (10, 20)
#: A record counts a supplier as bad past these shares.
RECORD_LATE_SHARE, RECORD_DEFECT_SHARE = 0.2, 0.1


def attribute_of(signal: str) -> str:
    return next(name for name in ATTRIBUTES if signal.startswith(name))


def high_is_good(signal: str) -> bool:
    return signal.endswith(("high_is_good", "long_is_good"))


def world_specs() -> tuple[dict[str, Any], ...]:
    """Six signals by three binding risks, with the two things a default could ride on balanced.

    ``cheapest_good``: whether the cheapest listing of the unrecorded component
    is a good supplier. Where price is the signal that follows from the
    direction. Elsewhere it is assigned: six worlds each way, three each way
    within each direction, within each of the two attributes, and two each way
    within each risk. Which component carries the record is balanced against
    attribute and risk, nine worlds each.
    """
    specs = []
    for signal_index, signal in enumerate(SIGNALS):
        for risk_index, risk in enumerate(RISKS):
            direction = 1 if high_is_good(signal) else 0
            attribute_index = ATTRIBUTES.index(attribute_of(signal))
            cheapest_good = (not direction) if attribute_index == 0 else bool((attribute_index + direction + risk_index) % 2)
            specs.append({
                "slug": f"{signal}__{risk}", "signal": signal, "risk": risk,
                "ordinal": signal_index * len(RISKS) + risk_index + 1,
                "cheapest_good": cheapest_good,
                "recorded_component": COMPONENTS[(direction + (risk_index == 2)) % 2],
                "seed_block": SEED_START + (signal_index * len(RISKS) + risk_index) * SEEDS_PER_CELL,
            })
    return tuple(specs)


def _binomial(rng: random.Random, n: int, p: float) -> int:
    return sum(rng.random() < p for _ in range(n))


def _component_suppliers(
    rng: random.Random, component: str, *, signal: str, risk: str, cheapest_good: bool,
    base_price: float, gap: float, poor_yields: Sequence[float], labels: Sequence[str],
) -> list[dict[str, Any]]:
    """Two good and two bad suppliers of one component, as ``_supplier`` builds them."""
    signal_attribute = attribute_of(signal)
    good_level = 1 if high_is_good(signal) else 0
    others = [name for name in ATTRIBUTES if name != signal_attribute]
    x, y = rng.randint(0, 1), rng.randint(0, 1)
    # good, good, bad, bad: the signal splits them; each other attribute has one
    # good and one bad at each level, and the two others are orthogonal.
    levels = [
        {signal_attribute: good_level, others[0]: x, others[1]: y},
        {signal_attribute: good_level, others[0]: 1 - x, others[1]: 1 - y},
        {signal_attribute: 1 - good_level, others[0]: x, others[1]: 1 - y},
        {signal_attribute: 1 - good_level, others[0]: 1 - x, others[1]: y},
    ]
    quality = [True, True, False, False]
    # Within a price level the two suppliers differ a little. Where price is not
    # the signal, a level holds one good and one bad supplier and the order
    # decides whether the cheapest (and, reversed, the dearest) is good.
    price_factor = [0.0] * 4
    lead_slot = [0] * 4
    for level in (0, 1):
        members = [i for i in range(4) if levels[i]["price"] == level]
        if signal_attribute == "price":
            rng.shuffle(members)
        else:
            # The cheaper of each pair is good exactly when the cheapest should be,
            # which makes the dearest listing the reverse of the cheapest.
            members.sort(key=lambda i: quality[i] != cheapest_good)
        for slot, i in enumerate(members):
            price_factor[i] = (1.0 if level == 0 else gap) * (1.0 + 0.035 * slot)
        members = [i for i in range(4) if levels[i]["lead_time"] == level]
        rng.shuffle(members)
        for slot, i in enumerate(members):
            lead_slot[i] = slot
    suppliers = []
    for i in range(4):
        good = quality[i]
        yield_rate, on_time, capacity = GOOD_YIELD, GOOD_ON_TIME, GOOD_CAPACITY
        if not good:
            if risk == "yield":
                yield_rate = poor_yields[i - 2]
            elif risk == "timing":
                on_time = POOR_ON_TIME
            else:
                capacity = POOR_CAPACITY
        moq_level = MOQ_LEVELS[levels[i]["moq"]]
        supplier = _supplier(
            component, labels[i],
            unit_price=round(base_price * price_factor[i], 4),
            capacity=capacity, moq=min(moq_level, capacity), order_step=10,
            lead_time=LEAD_DAYS[levels[i]["lead_time"]][lead_slot[i]],
            on_time=on_time, sample_cost=0.25, sample_days=2, yield_rate=yield_rate,
            # The listing states its minimum order; a small supplier's true one is its capacity.
            verbal_bias={"verified_yield_rate": 0.99, "moq": moq_level},
        )
        supplier["_good"] = good
        suppliers.append(supplier)
    return suppliers


def build_world(spec: Mapping[str, Any], seed: int) -> dict[str, Any]:
    """One case for a cell at one seed. Raises if the environment rejects it."""
    rng = random.Random(seed)
    signal, risk = spec["signal"], spec["risk"]
    codes = rng.sample(range(100, 1000), 8)
    suppliers: list[dict[str, Any]] = []
    for index, component in enumerate(COMPONENTS):
        recorded = component == spec["recorded_component"]
        suppliers += _component_suppliers(
            rng, component, signal=signal, risk=risk,
            # Only the unrecorded component's cheapest listing is balanced by
            # design; the recorded one can be read off its record either way.
            cheapest_good=spec["cheapest_good"] if not recorded else bool(rng.randint(0, 1)),
            # Each component has its own price level, so no two listings of
            # different components share a price and look like one seller.
            base_price=round(rng.uniform(0.50, 0.70), 4), gap=round(rng.uniform(1.22, 1.30), 4),
            poor_yields=[round(rng.uniform(*POOR_YIELD_RANGE), 3) for _ in range(2)],
            labels=[f"l{code}" for code in codes[index * 4:index * 4 + 4]],
        )
    for supplier in suppliers:
        terms = supplier["private_terms"]
        if supplier["component"] == spec["recorded_component"]:
            record = {
                "orders_reported": RECORD_ORDERS,
                "late_deliveries": _binomial(rng, RECORD_ORDERS, 1.0 - terms["on_time_probability"]),
                "units_inspected": RECORD_UNITS,
                "defective_units": _binomial(rng, RECORD_UNITS, 1.0 - terms["quality"]["verified_yield_rate"]),
                "largest_order_filled_units": terms["capacity"],
            }
        else:
            record = {"orders_reported": 0, "late_deliveries": None, "units_inspected": 0,
                      "defective_units": None, "largest_order_filled_units": None}
        supplier["listing"]["marketplace_record"] = record
    good = sorted(s["supplier_id"] for s in suppliers if s.pop("_good"))
    rng.shuffle(suppliers)
    case = _build_case(
        {
            "slug": spec["slug"], "world_seed": seed,
            # A code, not the cell: the buyer reads the product id.
            "product_id": f"kit_{rng.randrange(1000, 10000)}",
            "bom": {component: 1 for component in COMPONENTS},
            "budget_actions": BUDGET_ACTIONS,
            "objective": {"revenue": 16.0, "penalty": 3.0, "budget": 60.0, "deadline": 24,
                          "minimum": MINIMUM_SERVICE_KITS},
            "interaction": {"inquiry": 0.05, "quote": 0.1, "counter": 0.15},
            "suppliers": suppliers,
        },
        surface="labeled",
    )
    case["case_id"] = f"procurement_allocation_v1.{PACK_ID}.{spec['slug']}"
    case["split"] = PACK_ID
    case["payload"]["objective"]["target_kits"] = TARGET_KITS
    for supplier in case["payload"]["suppliers"]:
        quality = supplier["private_terms"]["quality"]
        quality["sample_size"] = SAMPLE_BATCH
        quality["observed_defects"] = round(SAMPLE_BATCH * (1.0 - float(quality["verified_yield_rate"])))
    case["payload"]["interaction"]["sample_noise"] = {"model": "binomial", "seed": seed}
    case["provenance"] = {"generator_id": GENERATOR_ID, "generator_version": GENERATOR_VERSION,
                          "review_status": "curated"}
    case["content_sha256"] = "0" * 64
    manifest = CaseManifest.from_dict(case)
    ProcurementAllocationPlugin().validate_payload(manifest.payload)
    case["content_sha256"] = case_content_sha256(manifest)
    # Not part of the case: which suppliers the generator made good.
    return {"case": case, "good_supplier_ids": good}


# --- what a buyer can read, and the policies that read more or less of it ------


def _listings(observation: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_component: dict[str, list[dict[str, Any]]] = {}
    for row in observation["supplier_listings"]:
        by_component.setdefault(row["component"], []).append(
            {"supplier_id": row["supplier_id"], **row["listing"]}
        )
    return by_component


def recorded_component(observation: Mapping[str, Any]) -> str:
    listings = _listings(observation)
    return next(c for c, rows in listings.items()
                if all(r["marketplace_record"]["orders_reported"] > 0 for r in rows))


def record_says_good(listing: Mapping[str, Any], *, largest: int) -> bool:
    record = listing["marketplace_record"]
    return (
        record["late_deliveries"] / record["orders_reported"] <= RECORD_LATE_SHARE
        and record["defective_units"] / record["units_inspected"] <= RECORD_DEFECT_SHARE
        and record["largest_order_filled_units"] >= largest
    )


def separating_attributes(rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, bool]]:
    """Every (attribute, high is good) that puts all record-good listings on one side of all record-bad ones."""
    largest = max(r["marketplace_record"]["largest_order_filled_units"] for r in rows)
    good = [r for r in rows if record_says_good(r, largest=largest)]
    bad = [r for r in rows if not record_says_good(r, largest=largest)]
    found = []
    for name in ATTRIBUTES:
        field = LISTING_FIELD[name]
        if good and bad and min(r[field] for r in good) > max(r[field] for r in bad):
            found.append((name, True))
        if good and bad and max(r[field] for r in good) < min(r[field] for r in bad):
            found.append((name, False))
    return found


RULES: dict[str, tuple[str, bool]] = {
    "cheapest_first": ("price", False), "dearest_first": ("price", True),
    "fastest_first": ("lead_time", False), "slowest_first": ("lead_time", True),
    "smallest_moq_first": ("moq", False), "largest_moq_first": ("moq", True),
}


def _by_rule(rows: Sequence[Mapping[str, Any]], rule: str) -> str:
    name, high = RULES[rule]
    field = LISTING_FIELD[name]
    # Ties (two listings state the same minimum order) go to the cheaper one.
    return min(rows, key=lambda r: ((-r[field] if high else r[field]), r["displayed_unit_price_usd"]))["supplier_id"]


def choose_targets(observation: Mapping[str, Any], *, mode: str, rule: str = "cheapest_first") -> dict[str, str]:
    """The supplier each policy verifies for each component.

    ``informed``: the recorded component by its record; the other by the
    attribute and direction that separate the recorded component's listings.
    ``records_then_rule``: the recorded component by its record; the other by a
    fixed listing rule. ``rule_only``: a fixed listing rule for both.
    """
    listings = _listings(observation)
    recorded = recorded_component(observation)
    other = next(c for c in listings if c != recorded)
    cheapest = lambda rows: min(rows, key=lambda r: r["displayed_unit_price_usd"])["supplier_id"]  # noqa: E731
    if mode == "rule_only":
        return {recorded: _by_rule(listings[recorded], rule), other: _by_rule(listings[other], rule)}
    largest = max(r["marketplace_record"]["largest_order_filled_units"] for r in listings[recorded])
    targets = {recorded: cheapest([r for r in listings[recorded] if record_says_good(r, largest=largest)])}
    if mode == "records_then_rule":
        targets[other] = _by_rule(listings[other], rule)
        return targets
    if mode != "informed":
        raise ValueError(f"unknown policy mode: {mode}")
    name, high = separating_attributes(listings[recorded])[0]
    field = LISTING_FIELD[name]
    ranked = sorted(listings[other], key=lambda r: r[field], reverse=high)
    targets[other] = cheapest(ranked[:2])
    return targets


def policy_action(observation: Mapping[str, Any], targets: Mapping[str, str]) -> dict[str, Any]:
    """Quote and sample each target in turn, then award what each offer can supply."""
    offers = {offer["supplier_id"]: offer for offer in observation["formal_offers"].values()}
    for supplier_id in targets.values():
        if supplier_id not in offers:
            return {"action": "request_quote", "supplier_id": supplier_id, "message": "Please issue a formal offer."}
        if supplier_id not in observation["verified_samples"]:
            return {"action": "request_sample", "supplier_id": supplier_id, "message": "Please send a sample batch."}
    return {
        "action": "submit_award",
        "award_lines": [
            {"offer_id": offers[supplier_id]["offer_id"], "quantity": min(int(offers[supplier_id]["capacity"]), 20)}
            for supplier_id in targets.values()
        ],
    }


def replay(payload: Mapping[str, Any], choose: Callable[[Mapping[str, Any]], Mapping[str, str]]) -> dict[str, Any] | None:
    """Play a policy through the environment; ``None`` if it never reaches a terminal state."""
    plugin = ProcurementAllocationPlugin()
    family_case = plugin.validate_payload(payload)
    phase = plugin.phases(family_case)[0]
    state = plugin.initial_state(family_case, None)
    targets: Mapping[str, str] | None = None
    for _ in range(int(family_case["interaction"]["max_actions"])):
        if state["done"]:
            break
        observation = plugin.observe(family_case, state, "buyer", phase)
        if targets is None:
            targets = choose(observation)
        parsed = plugin.parse_action(family_case, state, "buyer", phase, policy_action(observation, targets))
        if not parsed.ok:
            return None
        legality = plugin.legal(family_case, state, "buyer", phase, parsed.action)
        state = plugin.step(
            family_case, state, phase,
            {"buyer": ActionEnvelope(seat_id="buyer", valid=legality.legal, action=parsed.action,
                                     parse=parsed, legality=legality)},
        ).state
    terminal = plugin.terminal(family_case, state)
    if terminal is None:
        return None
    return {**plugin.outcome(family_case, terminal), "targets": dict(targets or {})}


def screen_world(built: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, Any]:
    """What the reference policies do on a world, and whether its structure is what the cell declares."""
    payload = built["case"]["payload"]
    good = set(built["good_supplier_ids"])
    plugin = ProcurementAllocationPlugin()
    family_case = plugin.validate_payload(payload)
    observation = plugin.observe(family_case, plugin.initial_state(family_case, None), "buyer", plugin.phases(family_case)[0])
    listings = _listings(observation)
    recorded = recorded_component(observation)
    other = next(c for c in listings if c != recorded)
    problems: list[str] = []
    if recorded != spec["recorded_component"]:
        problems.append("recorded component differs from the cell")
    expected = (attribute_of(spec["signal"]), high_is_good(spec["signal"]))
    if separating_attributes(listings[recorded]) != [expected]:
        problems.append(f"the record separates on {separating_attributes(listings[recorded])}, not only {expected}")
    largest = max(r["marketplace_record"]["largest_order_filled_units"] for r in listings[recorded])
    if {r["supplier_id"] for r in listings[recorded] if record_says_good(r, largest=largest)} != {
        s for s in good if s.startswith(recorded)
    }:
        problems.append("the record does not name the good suppliers")
    for component, rows in listings.items():
        for name in ATTRIBUTES:
            if name == expected[0]:
                continue
            field = LISTING_FIELD[name]
            cut = sorted(r[field] for r in rows)
            high = [r["supplier_id"] in good for r in rows if r[field] > cut[1]] if cut[1] < cut[2] else None
            if high is None or sorted(high) != [False, True]:
                problems.append(f"{name} is not crossed with quality on {component}")
    cheapest = min(listings[other], key=lambda r: r["displayed_unit_price_usd"])["supplier_id"] in good
    dearest = max(listings[other], key=lambda r: r["displayed_unit_price_usd"])["supplier_id"] in good
    if cheapest != spec["cheapest_good"]:
        problems.append("the cheapest unrecorded listing is not what the cell declares")
    if expected[0] != "price" and dearest == cheapest:
        problems.append("the dearest unrecorded listing is not the reverse of the cheapest")
    prices = [{r["displayed_unit_price_usd"] for r in rows} for rows in listings.values()]
    if prices[0] & prices[1]:
        problems.append("two listings of different components show the same price")
    upper = solve_full_information_upper_bound(family_case)
    plan = {str(line["supplier_id"]) for line in upper.award_plan}
    if not plan <= good:
        problems.append("the full-information optimum buys from a bad supplier")
    results: dict[str, Any] = {}
    informed = replay(payload, lambda o: choose_targets(o, mode="informed"))
    results["informed"] = None if informed is None else round(float(informed["regret_to_upper_bound_usd"]), 2)
    if informed is None or informed["regret_to_upper_bound_usd"] >= SOLVED_REGRET_USD:
        problems.append("the informed policy does not solve the world")
    elif not set(informed["targets"].values()) <= good:
        problems.append("the informed policy verified a bad supplier")
    for mode in ("records_then_rule", "rule_only"):
        for rule in RULES:
            outcome = replay(payload, lambda o, mode=mode, rule=rule: choose_targets(o, mode=mode, rule=rule))
            results[f"{mode}:{rule}"] = None if outcome is None else round(float(outcome["regret_to_upper_bound_usd"]), 2)
    return {
        "problems": problems, "regret_usd": results, "upper_bound_usd": round(upper.contribution_margin_usd, 2),
        "cheapest_unrecorded_is_good": cheapest, "dearest_unrecorded_is_good": dearest,
        "unrecorded_component": other,
    }


def build_pack() -> dict[str, Any]:
    """The eighteen worlds and what the reference policies earn on them."""
    worlds, cases = [], []
    for spec in world_specs():
        admitted = None
        scanned = 0
        for seed in range(spec["seed_block"], spec["seed_block"] + SEEDS_PER_CELL):
            scanned += 1
            try:
                built = build_world(spec, seed)
            except (ValueError, AssertionError):
                continue
            screened = screen_world(built, spec)
            if not screened["problems"]:
                admitted = (seed, built, screened)
                break
        if admitted is None:
            raise RuntimeError(f"no seed in the block admits a world for {spec['slug']}")
        seed, built, screened = admitted
        cases.append(built["case"])
        worlds.append({
            "slug": spec["slug"], "signal": spec["signal"], "risk": spec["risk"],
            "world_seed": seed, "seeds_scanned": scanned,
            "case_id": built["case"]["case_id"], "content_sha256": built["case"]["content_sha256"],
            "recorded_component": spec["recorded_component"],
            "unrecorded_component": screened["unrecorded_component"],
            "cheapest_unrecorded_is_good": screened["cheapest_unrecorded_is_good"],
            "dearest_unrecorded_is_good": screened["dearest_unrecorded_is_good"],
            "good_supplier_ids": built["good_supplier_ids"],
            "upper_bound_usd": screened["upper_bound_usd"],
            "reference_regret_usd": screened["regret_usd"],
        })
    policies = sorted(worlds[0]["reference_regret_usd"])
    solved = {
        policy: sum(w["reference_regret_usd"][policy] is not None
                    and w["reference_regret_usd"][policy] < SOLVED_REGRET_USD for w in worlds)
        for policy in policies
    }
    manifest = {
        "schema_version": PACK_SCHEMA, "pack_id": PACK_ID,
        "generator": {"id": GENERATOR_ID, "version": GENERATOR_VERSION},
        "controls": {
            "budget_actions": BUDGET_ACTIONS, "target_kits": TARGET_KITS,
            "minimum_service_kits": MINIMUM_SERVICE_KITS, "sample_batch": SAMPLE_BATCH,
            "record_orders": RECORD_ORDERS, "record_units": RECORD_UNITS,
            "seed_start": SEED_START, "seeds_per_cell": SEEDS_PER_CELL,
            "solved_regret_usd": SOLVED_REGRET_USD,
        },
        "worlds": worlds,
        "reference_worlds_solved": solved,
        "world_count": len(worlds),
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
    print(json.dumps({"reference_worlds_solved": manifest["reference_worlds_solved"],
                      "worlds": [{k: w[k] for k in ("slug", "world_seed", "seeds_scanned", "cheapest_unrecorded_is_good")}
                                 for w in manifest["worlds"]]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ATTRIBUTES", "BUDGET_ACTIONS", "GENERATOR_ID", "PACK_ID", "RULES",
    "attribute_of", "build_pack", "build_world", "case_paths", "choose_targets", "high_is_good",
    "policy_action", "recorded_component", "replay", "screen_world", "separating_attributes",
    "world_specs", "write_pack",
]
