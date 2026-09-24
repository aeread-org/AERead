"""Case cards for the repeated-sourcing packs, for the analysis team and the Examiner.

One card per world, generated from the pack manifest and the solver so no number
is typed by hand. The layout follows the split Terminal-Bench and APEX use: what
the buyer is asked and shown, what is hidden from it, a reference solution, and
atomic diagnostic checks, each with the condition that passes it and the one that
fails it, keyed to fields of the cell record. The mechanism behind each stratum
is prose, once per stratum, in `docs/families/procurement-allocation/case_cards.md`.

    python -m aeread_families.procurement_allocation.relationship_case_cards [--check]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from . import relationship
from .relationship_case_matrix import COMPETENT_BASELINE, PACK_POLICIES, pack_case_paths, pack_root

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CARDS_ROOT = REPOSITORY_ROOT / "docs" / "families" / "procurement-allocation" / "case_cards"
SCHEMA = "aeread.procurement_relationship_case_card/0.1"
PACKS = ("relationship_dev_v2", "relationship_holdout_v1")

#: Violation codes that mean the buyer did not execute the protocol, as opposed
#: to executing it and missing a service level.
EXECUTION_VIOLATIONS = (
    "sample_not_verified",
    "over_capacity",
    "malformed_procurement_action",
    "episode_ended_before_period",
)


def _checks(reference: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Atomic, trace-checkable criteria; each names what passes and what fails."""
    period_one = reference["per_period"][0]
    return [
        {
            "id": "D1_orders_in_time",
            "check": "places a period-1 order that can still arrive by the deadline",
            "passes_when": "period_results[0].decision == 'award' and no 'minimum_service_not_met' in period 1",
            "fails_when": "period 1 deferred, or ordered too late to meet minimum service",
            "reference": {
                "latest_order_day": reference["latest_period_one_order_day"],
                "deadline_days": reference["deadline_days"],
            },
        },
        {
            "id": "D2_reference_suppliers",
            "check": "buys from the suppliers the reference plan buys from, period by period",
            "passes_when": "set(awarded[].supplier_id) equals the reference set in every period",
            "fails_when": "any period's awarded set differs (the usual case: the cheaper-looking supplier today)",
            "reference": {"per_period": [row["suppliers"] for row in reference["per_period"]]},
        },
        {
            "id": "D3_negotiates",
            "check": "pays below a supplier's quoted price at least once",
            "passes_when": "some awarded unit_price_usd is below that supplier's quoted price",
            "fails_when": "every award is at the quoted price (counters == 0 is the common signature)",
            "reference": {
                "period_one_quote_vs_floor": {
                    row["supplier_id"]: {"quoted": row["base_quoted_unit_price_usd"], "floor": row["base_floor_unit_price_usd"]}
                    for row in period_one["lines"]
                }
            },
        },
        {
            "id": "D4_minimum_service",
            "check": "meets minimum service in every period",
            "passes_when": "no 'minimum_service_not_met' in any period",
            "fails_when": "any period misses minimum service",
            "reference": {"minimum_service_kits": [row["minimum_service_kits"] for row in reference["per_period"]]},
        },
        {
            "id": "D5_valid_execution",
            "check": "every action and award is valid and every period is played",
            "passes_when": "no violation among " + ", ".join(EXECUTION_VIOLATIONS),
            "fails_when": "any of them",
            "reference": None,
        },
        {
            "id": "D6_beats_competent_rule",
            "check": "earns more than the deadline-aware observation-only rule",
            "passes_when": "regret_to_upper_bound_usd < reference_ladder.deadline_aware",
            "fails_when": "regret at or above it",
            "reference": {"deadline_aware_regret_usd": reference["ladder"][COMPETENT_BASELINE]},
        },
    ]


def world_card(pack: str, row: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    suppliers = {supplier["supplier_id"]: supplier for supplier in payload["suppliers"]}
    schedule = relationship.period_schedule(payload)
    objective = payload["objective"]
    bound = relationship.solve_relationship_upper_bound(payload)
    per_period = []
    for index, (plan, margin) in enumerate(zip(bound.period_plans, bound.period_margins)):
        lines = []
        for line in plan:
            terms = suppliers[line["supplier_id"]]["private_terms"]
            lines.append(
                {
                    "supplier_id": line["supplier_id"],
                    "quantity": line["quantity"],
                    "paid_unit_price_usd": round(float(line["unit_price_usd"]), 6),
                    # Before relationship effects: a loyalty discount or a
                    # retaliation markup moves the quote and the floor together.
                    "base_quoted_unit_price_usd": terms["base_unit_price_usd"],
                    "base_floor_unit_price_usd": terms["negotiation"]["floor_unit_price_usd"],
                }
            )
        per_period.append(
            {
                "period": index + 1,
                "suppliers": sorted(line["supplier_id"] for line in plan),
                "lines": lines,
                "margin_usd": round(float(margin), 4),
                "target_kits": schedule[index]["target_kits"],
                "minimum_service_kits": schedule[index]["minimum_service_kits"],
            }
        )
    first_leads = [suppliers[line["supplier_id"]]["private_terms"]["lead_time_days"] for line in bound.period_plans[0]]
    policies = row["public_policies"]
    ladder = {
        "optimum": 0.0,
        "myopic": round(row["upper_bound_usd"] - row["myopic_usd"], 4),
        "loyal": round(row["upper_bound_usd"] - row["loyal_usd"], 4),
        "shopping": round(row["upper_bound_usd"] - row["shopping_usd"], 4),
        **{name: round(policies[name]["regret_to_upper_bound_usd"], 4) for name in (*PACK_POLICIES, COMPETENT_BASELINE)},
    }
    reference = {
        "per_period": per_period,
        "latest_period_one_order_day": int(objective["deadline_days"]) - max(first_leads),
        "deadline_days": int(objective["deadline_days"]),
        "ladder": ladder,
    }
    interaction = payload["interaction"]
    return {
        "world": row["slug"],
        "case_id": row["case_id"],
        "content_sha256": row["content_sha256"],
        "pack": pack,
        "stratum": row["stratum"],
        "stratum_card": f"docs/families/procurement-allocation/case_cards.md#{row['stratum'].replace('_', '-')}",
        "task": {
            "periods": len(schedule),
            "actions_per_period": interaction["max_actions"],
            "days_per_action": {key: interaction[key] for key in ("inquiry_days", "quote_days", "counter_days")},
            "action_costs_usd": {key: interaction[key] for key in ("inquiry_cost_usd", "quote_cost_usd", "counter_cost_usd")},
            "deadline_days": objective["deadline_days"],
            "cash_budget_usd": objective["cash_budget_usd"],
            "revenue_per_kit_usd": objective["revenue_per_completed_kit_usd"],
            "shortfall_penalty_per_kit_usd": objective["shortfall_penalty_per_kit_usd"],
            "bill_of_materials": objective["bom"],
            "targets": [{"target_kits": s["target_kits"], "minimum_service_kits": s["minimum_service_kits"]} for s in schedule],
        },
        "buyer_sees": {
            supplier_id: {"component": supplier["component"], **supplier["listing"]}
            for supplier_id, supplier in sorted(suppliers.items())
        },
        "hidden_from_buyer": {
            supplier_id: {
                "base_quoted_unit_price_usd": terms["base_unit_price_usd"],
                "base_floor_unit_price_usd": terms["negotiation"]["floor_unit_price_usd"],
                "capacity": terms["capacity"],
                "moq": terms["moq"],
                "lead_time_days": terms["lead_time_days"],
                "on_time_probability": terms["on_time_probability"],
                "verified_yield_rate": terms["quality"]["verified_yield_rate"],
                "sample_cost_usd": terms["quality"]["sample_cost_usd"],
                "sample_lead_time_days": terms["quality"]["sample_lead_time_days"],
                "relationship": terms.get("relationship"),
            }
            for supplier_id, terms in sorted((sid, s["private_terms"]) for sid, s in suppliers.items())
        },
        "reference_solution": {
            "upper_bound_usd": round(float(bound.contribution_margin_usd), 4),
            "switches": bound.switches,
            "per_period": per_period,
        },
        "reference_ladder_regret_usd": ladder,
        "diagnostic_checks": _checks(reference),
    }


def build(pack: str) -> dict[str, Any]:
    manifest = json.loads((pack_root(pack) / "pack.json").read_text(encoding="utf-8"))
    cards = []
    for path, row in zip(pack_case_paths(pack), manifest["worlds"]):
        payload = json.loads(path.read_text(encoding="utf-8"))["payload"]
        cards.append(world_card(pack, row, payload))
    return {
        "schema": SCHEMA,
        "pack": pack,
        "pack_manifest_sha256": manifest["manifest_sha256"],
        "note": "generated by relationship_case_cards.py; do not edit by hand",
        "worlds": cards,
    }


def rendered(pack: str) -> str:
    return json.dumps(build(pack), indent=1, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 if a committed card file is stale")
    arguments = parser.parse_args(argv)
    stale = []
    for pack in PACKS:
        path = CARDS_ROOT / f"{pack}.json"
        text = rendered(pack)
        if arguments.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(str(path))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(path)
    if stale:
        print("stale:", *stale)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
