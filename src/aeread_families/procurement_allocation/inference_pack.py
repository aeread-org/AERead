"""Inference worlds selected by rule from a seed domain no live cell has read.

`inference_v1` is eighteen authored worlds at fixed seeds, and every one of
them has been played by the pilots that produced the family's first subject
measurement (design review, defects 26 to 29). A confirmatory needs worlds no
live cell has read, so this module draws worlds from `inference_case_matrix`'s
declared ranges in a seed domain of their own and admits each by a screen,
recording every refusal with its verdict, the relationship-pack shape.

**What admits a world.** Six listing-only rules play it, one per direction of
each signal: verify the cheapest first and the dearest first, the fastest and
the slowest, the smallest minimum order and the largest. Each follows the
public-policy procedure (quote, sample, award once the qualified capacity
covers the target) and reads nothing but the listing. A world is admitted when

- the rules separate in expectation (`classify_world_by_policy_separation`
  over at least three sample-noise seeds), the rule the other screens lacked;
- the rule aligned with the world's declared signal solves the world (mean
  regret below `trajectory_analysis.SOLVED_REGRET_USD`); and
- in a yield or timing world, the rule committed to the opposite direction
  loses to it by at least `MINIMUM_RELATIVE_SPREAD` of the full-information
  bound. A capacity world is exempt: its poor suppliers supply one lot each,
  two of them cover the target, and reading the direction wrong costs actions
  rather than money. Capacity is the risk a formal offer states, the control
  that needs no inference, exactly as v1 reads it; and
- in a yield or timing world, the full-information optimum sources at least
  `ORACLE_GOOD_SHARE_FLOOR` of its expected good units from good suppliers,
  so the signal predicts the better decision and not merely quality. On v1 it
  does not always: `price_high_is_good__yield`'s optimum buys only the poor
  suppliers (P-D-13), so a buyer that ignored the signal there was right. A
  capacity world is exempt here too: a cheap small supplier is a legitimate
  buy, so the optimum may source from the "poor" side; the share is recorded.

Other rules may also solve a world by the luck of the decoy price order; that
is expected, every fixed rule wins some worlds. What a world must guarantee is
that reading its signal wins and reading it backwards costs. How much it costs
differs by risk and is recorded per world: a yield world punishes the wrong
direction with the whole bound, while a timing or capacity world can be
recovered by over-ordering from the suppliers the formal offer exposes, at a
price. `opposite_rule_solves` says which kind a world is.

So "a better decision exists, and it is the one the signal implies" is a
property each world is tested for, not a construction argument. A pack fills
every signal-by-risk cell to its declared count; a stratum reported from it
needs at least five worlds (strata audit, 2026-09).

The rules follow the public-policy procedure with one sanity rule added: a
top-up lot is ordered only when the kits it adds are worth more than it costs.
Without it a 20-unit minimum order made every rule buy a second 20-unit lot
to cover half an expected unit, and the cash budget, not the signal, decided
the world.

Nothing here changes a pinned source: `headroom_screen` and `policy_baselines`
are imported, never edited.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.task.scheduler import ActionEnvelope

from .duediligence_case_matrix import _build_case, economic_world_sha256
from .environment import ProcurementAllocationPlugin, solve_full_information_upper_bound
from .headroom_screen import (
    ADMIT,
    MINIMUM_RELATIVE_SPREAD,
    MINIMUM_SCREEN_SEEDS,
    classify_world_by_policy_separation,
)
from .inference_case_matrix import RISKS, SIGNALS, finish_case, sample_definition
from .policy_baselines import _evidenced_yield, _expected_capacity, _latest_offer, _valid_quantity
from .trajectory_analysis import SOLVED_REGRET_USD

PACK_GENERATOR_ID = "procurement_allocation_inference_pack_v1"
PACK_GENERATOR_VERSION = "1.0.0"
PACK_SCHEMA = "aeread.procurement_inference_pack/0.1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASES_ROOT = REPOSITORY_ROOT / "cases" / "procurement_allocation_v1"
SURFACES = ("labeled", "opaque")

#: Seed domains are disjoint from v1 (8810000 to 8810052) and from each other.
PACKS: dict[str, dict[str, Any]] = {
    "inference_holdout_v1": {"split": "holdout", "seed_start": 8820000, "per_cell": 2, "scan_limit": 720},
}

#: The six listing-only rules: which listing field they rank on, and whether
#: a larger value goes first.
RULES: dict[str, tuple[str, bool]] = {
    "cheapest_first": ("displayed_unit_price_usd", False),
    "dearest_first": ("displayed_unit_price_usd", True),
    "fastest_first": ("claimed_lead_time_days", False),
    "slowest_first": ("claimed_lead_time_days", True),
    "smallest_moq_first": ("claimed_moq", False),
    "largest_moq_first": ("claimed_moq", True),
}
ALIGNED_RULE: dict[str, str] = {
    "price_low_is_good": "cheapest_first",
    "price_high_is_good": "dearest_first",
    "lead_time_short_is_good": "fastest_first",
    "lead_time_long_is_good": "slowest_first",
    "moq_low_is_good": "smallest_moq_first",
    "moq_high_is_good": "largest_moq_first",
}
OPPOSITE_RULE: dict[str, str] = {
    "cheapest_first": "dearest_first",
    "dearest_first": "cheapest_first",
    "fastest_first": "slowest_first",
    "slowest_first": "fastest_first",
    "smallest_moq_first": "largest_moq_first",
    "largest_moq_first": "smallest_moq_first",
}
ALIGNED_RULE_FAILS = "reject: the aligned rule does not solve the world"
OPPOSITE_RULE_AS_GOOD = "reject: the opposite rule loses less than the margin"
ORACLE_BUYS_POOR = "reject: the full-information optimum sources mostly from poor suppliers"
ORACLE_GOOD_SHARE_FLOOR = 0.6
MARGIN_EXEMPT_RISKS = frozenset({"capacity"})

#: A supplier is good when none of the three risks touches it; the thresholds
#: sit between every good and poor level the ranges allow. Read from private
#: terms by the screen only; the buyer never sees them.
GOOD_YIELD_FLOOR, GOOD_ON_TIME_FLOOR, GOOD_CAPACITY_FLOOR = 0.9, 0.9, 20


def good_supplier_ids(payload: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(
        str(supplier["supplier_id"])
        for supplier in payload["suppliers"]
        if float(supplier["private_terms"]["quality"]["verified_yield_rate"]) >= GOOD_YIELD_FLOOR
        and float(supplier["private_terms"]["on_time_probability"]) >= GOOD_ON_TIME_FLOOR
        and int(supplier["private_terms"]["capacity"]) >= GOOD_CAPACITY_FLOOR
    )


def cells() -> tuple[tuple[str, str], ...]:
    """Every signal crossed with every binding risk, in v1's order."""
    return tuple((signal, risk) for signal in SIGNALS for risk in RISKS)


def direction(signal: str) -> str:
    return "high_is_good" if signal.endswith(("high_is_good", "long_is_good")) else "low_is_good"


def attribute(signal: str) -> str:
    return signal.rsplit("_", 3)[0]


# --- the six rules ------------------------------------------------------------


def _ranked(observation: Mapping[str, Any], *, component: str, rule: str) -> list[Mapping[str, Any]]:
    field, larger_first = RULES[rule]
    candidates = [s for s in observation["supplier_listings"] if s["component"] == component]

    def key(supplier: Mapping[str, Any]) -> tuple[float, str]:
        value = float(supplier["listing"].get(field, 0.0))
        return (-value if larger_first else value, str(supplier["supplier_id"]))

    return sorted(candidates, key=key)


def choose_rule_action(observation: Mapping[str, Any], *, rule: str) -> dict[str, Any]:
    """The public-policy procedure with the rule's ranking: quote, sample, award.

    A copy of ``policy_baselines.choose_public_policy_action``'s procedure with
    the ranking swapped and one sanity rule added (a lot must pay for itself),
    kept here so the pinned module's bytes do not move.
    """
    if rule not in RULES:
        raise ValueError(f"unknown rule {rule!r}; known: {sorted(RULES)}")
    objective = observation["objective"]
    required_variants = observation["policy"]["required_variant_by_component"]
    qualified: dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]] = {}
    for component, units_per_kit in objective["bom"].items():
        target_units = objective["target_kits"] * int(units_per_kit)
        expected_capacity = 0.0
        qualified[component] = []
        for supplier in _ranked(observation, component=component, rule=rule):
            supplier_id = str(supplier["supplier_id"])
            offer = _latest_offer(observation, supplier_id)
            actions_left = int(observation["actions_left"])
            if offer is None or int(offer["expires_day"]) < int(observation["elapsed_days"]):
                if actions_left <= 2:
                    return {"action": "defer", "reason": "insufficient actions to qualify another supplier"}
                return {
                    "action": "request_quote",
                    "supplier_id": supplier_id,
                    "message": "Issue a formal offer with complete commercial terms.",
                }
            if offer["variant_id"] != required_variants[component]:
                continue
            sample = observation["verified_samples"].get(supplier_id)
            if not isinstance(sample, Mapping) or sample.get("variant_id") != offer.get("variant_id"):
                if actions_left <= 1:
                    return {"action": "defer", "reason": "insufficient actions to verify a supplier sample"}
                return {
                    "action": "request_sample",
                    "supplier_id": supplier_id,
                    "message": "Provide an exact-variant qualification sample.",
                }
            qualified[component].append((offer, sample))
            expected_capacity += _expected_capacity(observation=observation, offer=offer, sample=sample)
            if expected_capacity + 1e-12 >= target_units:
                break

    expected_units: dict[str, float] = {}
    award_lines: list[dict[str, Any]] = []
    estimated_cash_spend = float(observation["information_cost_usd"])
    kit_value = float(objective["revenue_per_completed_kit_usd"]) + float(objective["shortfall_penalty_per_kit_usd"])
    for component, units_per_kit in objective["bom"].items():
        target_units = objective["target_kits"] * int(units_per_kit)
        accumulated = 0.0
        for offer, sample in qualified[component]:
            efficiency = (
                _evidenced_yield(sample) * float(offer["on_time_probability"])
                if observation["elapsed_days"] + int(offer["lead_time_days"]) <= objective["deadline_days"]
                else 0.0
            )
            if efficiency <= 0:
                continue
            remaining = target_units - accumulated
            if remaining <= 1e-9:
                break
            quantity = _valid_quantity(offer, remaining / efficiency)
            purchase = quantity * float(offer["unit_price_usd"])
            shipping = quantity * float(offer["shipping_per_unit_usd"])
            landed = purchase + shipping + (purchase + shipping) * float(offer["duty_rate"])
            # The sanity rule: a lot that adds less kit value than it costs is
            # not ordered. Without it a 20-unit minimum order buys a second
            # 20-unit lot to cover half an expected unit.
            if min(quantity * efficiency, remaining) / int(units_per_kit) * kit_value < landed:
                continue
            award_lines.append({"offer_id": str(offer["offer_id"]), "quantity": quantity})
            accumulated += quantity * efficiency
            estimated_cash_spend += landed
        expected_units[component] = accumulated

    completed_kits = min(
        int(expected_units[component] // int(units_per_kit) + 1e-12)
        for component, units_per_kit in objective["bom"].items()
    )
    if completed_kits < objective["minimum_service_kits"]:
        return {"action": "defer", "reason": "publicly qualified capacity cannot meet minimum service"}
    if estimated_cash_spend > float(objective["cash_budget_usd"]) + 1e-9:
        return {"action": "defer", "reason": "formal landed spend exceeds the cash budget"}
    return {"action": "submit_award", "award_lines": award_lines}


def replay_rule(payload: Mapping[str, Any], rule: str) -> dict[str, Any] | None:
    """Play one rule offline through the environment; ``None`` if no terminal."""
    plugin = ProcurementAllocationPlugin()
    family_case = plugin.validate_payload(payload)
    phase = plugin.phases(family_case)[0]
    state = plugin.initial_state(family_case, None)
    for _ in range(int(family_case["interaction"]["max_actions"])):
        if state["done"]:
            break
        observation = plugin.observe(family_case, state, "buyer", phase)
        action = choose_rule_action(observation, rule=rule)
        parsed = plugin.parse_action(family_case, state, "buyer", phase, action)
        if not parsed.ok:
            return None
        legality = plugin.legal(family_case, state, "buyer", phase, parsed.action)
        state = plugin.step(
            family_case,
            state,
            phase,
            {
                "buyer": ActionEnvelope(
                    seat_id="buyer",
                    valid=legality.legal,
                    action=parsed.action,
                    parse=parsed,
                    legality=legality,
                )
            },
        ).state
    terminal = plugin.terminal(family_case, state)
    if terminal is None:
        return None
    return plugin.outcome(family_case, terminal)


# --- the screen ---------------------------------------------------------------


def _good_unit_share(payload: Mapping[str, Any], plan: Sequence[Mapping[str, Any]], good: frozenset[str]) -> float:
    """Share of the optimum's expected good units that come from good suppliers."""
    terms = {str(s["supplier_id"]): s["private_terms"] for s in payload["suppliers"]}
    expected = {}
    for line in plan:
        supplier_id = str(line["supplier_id"])
        private = terms[supplier_id]
        units = int(line["quantity"]) * float(private["quality"]["verified_yield_rate"]) * float(private["on_time_probability"])
        expected[supplier_id] = expected.get(supplier_id, 0.0) + units
    total = sum(expected.values())
    if total <= 0:
        return 0.0
    return round(sum(units for supplier_id, units in expected.items() if supplier_id in good) / total, 6)


def screen_world(
    payload: Mapping[str, Any], *, signal: str, risk: str, seeds: int = MINIMUM_SCREEN_SEEDS
) -> dict[str, Any]:
    """Play the six rules at ``seeds`` sample-noise seeds and judge the world."""
    optimum = solve_full_information_upper_bound(payload)
    bound = float(optimum.contribution_margin_usd)
    good = good_supplier_ids(payload)
    oracle_awards = sorted({str(line["supplier_id"]) for line in optimum.award_plan})
    oracle_good_share = _good_unit_share(payload, optimum.award_plan, good)
    base_seed = int(payload["interaction"]["sample_noise"]["seed"])
    scores: dict[str, list[float]] = {rule: [] for rule in RULES}
    for offset in range(int(seeds)):
        variant = copy.deepcopy(dict(payload))
        variant["interaction"]["sample_noise"]["seed"] = base_seed + offset
        for rule in RULES:
            outcome = replay_rule(variant, rule)
            # A rule that reaches no terminal has forfeited the award; it
            # scores as a deferral at the full bound.
            scores[rule].append(
                float(outcome["regret_to_upper_bound_usd"]) if outcome is not None else bound
            )
    means = {rule: round(sum(values) / len(values), 6) for rule, values in scores.items()}
    aligned = ALIGNED_RULE[signal]
    opposite = OPPOSITE_RULE[aligned]
    verdict = classify_world_by_policy_separation(scores)
    margin = round(means[opposite] - means[aligned], 6)
    if verdict == ADMIT:
        if means[aligned] >= SOLVED_REGRET_USD:
            verdict = ALIGNED_RULE_FAILS
        elif risk not in MARGIN_EXEMPT_RISKS and margin < MINIMUM_RELATIVE_SPREAD * bound:
            verdict = OPPOSITE_RULE_AS_GOOD
        elif risk not in MARGIN_EXEMPT_RISKS and oracle_good_share < ORACLE_GOOD_SHARE_FLOOR:
            verdict = ORACLE_BUYS_POOR
    return {
        "verdict": verdict,
        "upper_bound_usd": round(bound, 6),
        "rule_regret_usd": means,
        "solved_by": sorted(rule for rule, mean in means.items() if mean < SOLVED_REGRET_USD),
        "aligned_rule": aligned,
        "opposite_rule": opposite,
        "opposite_margin_usd": margin,
        "opposite_rule_solves": bool(means[opposite] < SOLVED_REGRET_USD),
        "oracle_awards": oracle_awards,
        "oracle_good_share": oracle_good_share,
        "screen_seeds": int(seeds),
    }


# --- building a pack ----------------------------------------------------------


def build_world(seed: int, signal: str, risk: str, *, pack: str, split: str) -> dict[str, Any]:
    """Both surfaces of one drawn world. Raises ``ValueError`` when it has no beneficial award."""
    definition = sample_definition(signal, risk, seed)
    surfaces: dict[str, dict[str, Any]] = {}
    for surface in SURFACES:
        case = _build_case(copy.deepcopy(definition), surface=surface)
        surfaces[surface] = finish_case(
            case,
            case_id=f"procurement_allocation_v1.{pack}_{surface}.{definition['slug']}",
            split=f"{pack}_{surface}",
            sample_batch=int(definition["sample_batch"]),
            noise_seed=int(definition["noise_seed"]),
            generator=(PACK_GENERATOR_ID, PACK_GENERATOR_VERSION),
            review_status="generated",
        )
    return {"definition": definition, "cases": surfaces}


def build_pack(name: str, *, spec: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Walk the pack's seed stream and admit worlds by the screen.

    Seed ``s`` is offered to cell ``(s - seed_start) mod 18`` in v1's order;
    a draw the screen refuses is recorded with its verdict and the stream
    moves on. The walk stops when every cell holds ``per_cell`` admitted
    worlds or ``scan_limit`` seeds have been scanned, in which case the pack
    is short and its manifest says so.
    """
    spec = dict(spec or PACKS[name])
    seed_start = int(spec["seed_start"])
    per_cell = int(spec["per_cell"])
    scan_limit = int(spec["scan_limit"])
    split = str(spec["split"])
    grid = cells()
    admitted: dict[tuple[str, str], list[dict[str, Any]]] = {cell: [] for cell in grid}
    excluded: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    scanned = 0
    for offset in range(scan_limit):
        if all(len(rows) >= per_cell for rows in admitted.values()):
            break
        seed = seed_start + offset
        signal, risk = grid[offset % len(grid)]
        scanned += 1
        record = {"world_seed": seed, "signal": signal, "risk": risk}
        if len(admitted[(signal, risk)]) >= per_cell:
            excluded.append({**record, "verdict": "cell full"})
            continue
        try:
            world = build_world(seed, signal, risk, pack=name, split=split)
        except ValueError as error:
            excluded.append({**record, "verdict": f"invalid: {error}"[:200]})
            continue
        labeled = world["cases"]["labeled"]
        screen = screen_world(labeled["payload"], signal=signal, risk=risk)
        if screen["verdict"] != ADMIT:
            excluded.append({**record, "verdict": screen["verdict"], "rule_regret_usd": screen["rule_regret_usd"]})
            continue
        economic_ids = {surface: economic_world_sha256(case) for surface, case in world["cases"].items()}
        if len(set(economic_ids.values())) != 1:
            raise AssertionError(f"surfaces of seed {seed} are not one economic world")
        admitted[(signal, risk)].append(
            {
                "slug": world["definition"]["slug"],
                "signal": signal,
                "direction": direction(signal),
                "attribute": attribute(signal),
                "risk": risk,
                "world_seed": seed,
                "economic_world_sha256": economic_ids["labeled"],
                "case_ids": {surface: case["case_id"] for surface, case in world["cases"].items()},
                "content_sha256": {surface: case["content_sha256"] for surface, case in world["cases"].items()},
                "levels": world["definition"]["levels"],
                "budget_actions": world["definition"]["budget_actions"],
                "sample_batch": world["definition"]["sample_batch"],
                **{
                    key: screen[key]
                    for key in (
                        "upper_bound_usd",
                        "rule_regret_usd",
                        "solved_by",
                        "aligned_rule",
                        "opposite_rule",
                        "opposite_margin_usd",
                        "opposite_rule_solves",
                        "oracle_awards",
                        "oracle_good_share",
                        "screen_seeds",
                    )
                },
            }
        )
        cases.extend(world["cases"][surface] for surface in SURFACES)
    worlds = [row for cell in grid for row in admitted[cell]]
    manifest = {
        "schema_version": PACK_SCHEMA,
        "pack": name,
        "generator_id": PACK_GENERATOR_ID,
        "generator_version": PACK_GENERATOR_VERSION,
        "split": split,
        "seed_domain": {"start": seed_start, "scan_limit": scan_limit},
        "selection_rule": (
            "seed s is offered to cell (s - start) mod 18, signals crossed with risks in v1's order; "
            "its numbers are drawn from inference_case_matrix.RANGES by a generator seeded with s; "
            "the world is admitted when the six listing-only rules separate in expectation "
            f"(classify_world_by_policy_separation at {MINIMUM_RELATIVE_SPREAD} over "
            f"{MINIMUM_SCREEN_SEEDS} sample-noise seeds), the rule aligned with the declared signal "
            f"solves the world (mean regret below {SOLVED_REGRET_USD} USD), the rule committed to the "
            f"opposite direction loses to it by at least {MINIMUM_RELATIVE_SPREAD} of the bound "
            f"and the full-information optimum sources at least {ORACLE_GOOD_SHARE_FLOOR} of its "
            f"expected good units from good suppliers (capacity worlds exempt from both), and the cell "
            f"is not yet full at {per_cell}; every world declares binomial sample noise and states "
            "its minimum-order level in the listing"
        ),
        "rules": list(RULES),
        "per_cell": per_cell,
        "seeds_scanned": scanned,
        "admitted": len(worlds),
        "complete": all(len(rows) >= per_cell for rows in admitted.values()),
        "admission_rate": round(
            len(worlds) / max(1, len(worlds) + sum(1 for row in excluded if row["verdict"] != "cell full")), 4
        ),
        "strata": {
            "direction": {label: sum(1 for row in worlds if row["direction"] == label) for label in ("low_is_good", "high_is_good")},
            "attribute": {label: sum(1 for row in worlds if row["attribute"] == label) for label in ("price", "lead_time", "moq")},
            "risk": {label: sum(1 for row in worlds if row["risk"] == label) for label in RISKS},
        },
        "worlds": worlds,
        "excluded": excluded,
        "claim_scope": (
            "synthetic worlds selected by rule; the references are listing-only rules and the "
            "full-information bound, not a model; no live cell has read this pack"
        ),
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"manifest": manifest, "cases": cases}


def pack_root(name: str) -> Path:
    return CASES_ROOT / name


def read_manifest(name: str, *, root: Path | str | None = None) -> dict[str, Any]:
    base = Path(root) if root is not None else pack_root(name)
    return json.loads((base / "pack.json").read_text(encoding="utf-8"))


def pack_case_paths(name: str, *, surface: str, root: Path | str | None = None) -> tuple[Path, ...]:
    """The committed worlds of one surface, in manifest order, for a campaign's ``--case`` list."""
    if surface not in SURFACES:
        raise ValueError(f"surface must be one of {SURFACES}")
    base = Path(root) if root is not None else pack_root(name)
    return tuple(base / surface / f"{row['slug']}.json" for row in read_manifest(name, root=base)["worlds"])


def write_pack(name: str, *, root: Path | str | None = None, spec: Mapping[str, Any] | None = None) -> tuple[Path, ...]:
    built = build_pack(name, spec=spec)
    destination = Path(root) if root is not None else pack_root(name)
    written: list[Path] = []
    for case in built["cases"]:
        surface = case["split"].rsplit("_", 1)[-1]
        path = destination / surface / f"{case['case_id'].rsplit('.', 1)[-1]}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        _replace(path, json.dumps(case, indent=2, sort_keys=True) + "\n")
        written.append(path)
    manifest_path = destination / "pack.json"
    _replace(manifest_path, json.dumps(built["manifest"], indent=2, sort_keys=True) + "\n")
    written.append(manifest_path)
    return tuple(written)


def _replace(path: Path, body: str) -> None:
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    temporary.write_text(body, encoding="utf-8")
    os.replace(temporary, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", choices=sorted(PACKS))
    parser.add_argument("--write", action="store_true", help="write the worlds and pack.json")
    parser.add_argument("--root", type=Path, help="write somewhere other than cases/")
    parser.add_argument("--per-cell", type=int, help="override the pack's per-cell count (recorded in the manifest)")
    parser.add_argument("--seed-start", type=int, help="override the seed domain's start (recorded in the manifest)")
    parser.add_argument("--scan-limit", type=int)
    arguments = parser.parse_args(argv)
    spec = dict(PACKS[arguments.pack])
    for key in ("per_cell", "seed_start", "scan_limit"):
        value = getattr(arguments, key)
        if value is not None:
            spec[key] = int(value)
    if arguments.write:
        for path in write_pack(arguments.pack, root=arguments.root, spec=spec):
            print(path)
        return 0
    manifest = build_pack(arguments.pack, spec=spec)["manifest"]
    print(json.dumps({key: manifest[key] for key in ("pack", "seeds_scanned", "admitted", "complete", "admission_rate", "strata")}, indent=2))
    for row in manifest["worlds"]:
        print(row["slug"], row["aligned_rule"], json.dumps(row["rule_regret_usd"]))
    for row in manifest["excluded"]:
        print("excluded", row["world_seed"], row["signal"], row["risk"], row["verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ALIGNED_RULE",
    "OPPOSITE_RULE",
    "PACKS",
    "PACK_GENERATOR_ID",
    "PACK_SCHEMA",
    "RULES",
    "SURFACES",
    "build_pack",
    "build_world",
    "cells",
    "choose_rule_action",
    "good_supplier_ids",
    "pack_case_paths",
    "read_manifest",
    "replay_rule",
    "screen_world",
    "write_pack",
]
