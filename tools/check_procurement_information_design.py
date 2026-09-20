"""Provider-free finite-belief checks for procurement design decision points.

These are authoring fixtures, not registered worlds or model observations.
No sampled hidden state is passed to the reference policy. Values are incremental
from a stated decision point; full-episode accounting must also retain sunk costs.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
from functools import lru_cache
import hashlib
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/procurement_information_design_v1.json"


def number(value):
    return Fraction(str(value))


def validate(case):
    prior = tuple(map(number, case["prior"]))
    assert prior and all(p > 0 for p in prior) and sum(prior) == 1
    assert isinstance(case["research_actions_left"], int)
    assert case["research_actions_left"] >= 0
    actions = case["research_actions"]
    ids = [a["id"] for a in actions]
    assert len(set(ids)) == len(ids)
    choices = case["terminal_choices"]
    assert len({a["id"] for a in choices}) == len(choices)
    assert "defer" not in ids + [a["id"] for a in choices]
    assert not set(ids).intersection(a["id"] for a in choices)
    for a in actions:
        assert number(a["cost_usd"]) >= 0
        assert isinstance(a["days"], int) and a["days"] >= 0
        assert isinstance(a["max_uses"], int) and a["max_uses"] > 0
        assert a["outcomes"]
        likelihoods = [tuple(map(number, v)) for v in a["outcomes"].values()]
        assert all(len(v) == len(prior) for v in likelihoods)
        assert all(0 <= p <= 1 for v in likelihoods for p in v)
        assert all(sum(v[s] for v in likelihoods) == 1 for s in range(len(prior)))
    for choice in choices:
        assert len(choice["payoffs_usd"]) == len(prior)
        assert set(choice.get("requires", [])).issubset(ids)
    return prior


def action_values(case):
    """Exact Bellman values for legal actions under the public belief.

    A terminal action sees posterior-weighted payoffs, never the actual state.
    Research updates that posterior, consumes time and an action, and costs money
    on every outcome branch, including branches ending in defer.
    """
    prior = validate(case)
    actions = case["research_actions"]
    action_index = {a["id"]: i for i, a in enumerate(actions)}

    @lru_cache(None)
    def values(belief, uses, remaining, elapsed):
        result = {"defer": Fraction(0)}
        for choice in case["terminal_choices"]:
            if elapsed > choice.get("last_award_day", 10**6):
                continue
            if any(uses[action_index[r]] == 0 for r in choice.get("requires", [])):
                continue
            result[choice["id"]] = sum(
                p * number(v) for p, v in zip(belief, choice["payoffs_usd"])
            )
        if remaining:
            for i, a in enumerate(actions):
                if uses[i] >= a["max_uses"]:
                    continue
                future = -number(a["cost_usd"])
                for likelihood in a["outcomes"].values():
                    joint = tuple(p * number(l) for p, l in zip(belief, likelihood))
                    probability = sum(joint)
                    if not probability:
                        continue
                    posterior = tuple(p / probability for p in joint)
                    next_uses = tuple(n + (j == i) for j, n in enumerate(uses))
                    continuation = values(
                        posterior, next_uses, remaining - 1, elapsed + a["days"]
                    )
                    future += probability * max(dict(continuation).values())
                result[a["id"]] = future
        return tuple(sorted(result.items()))

    return dict(values(prior, (0,) * len(actions), case["research_actions_left"], 0))


def allocation_choices(market):
    """Enumerate quoted, sample-qualified integer orders at a decision point."""
    vendors = market["vendors"]
    grids = [[0] + list(range(v["moq"], v["capacity"] + 1, v["order_step"])) for v in vendors]
    choices = []
    for quantities in itertools.product(*grids):
        if not any(quantities):
            continue
        cost = sum(
            q * number(v["unit_price_usd"]) + (number(v["shipping_usd"]) if q else 0)
            for q, v in zip(quantities, vendors)
        )
        if cost > number(market["cash_budget_usd"]):
            continue
        inventory = {c: 0 for c in market["bom"]}
        for q, v in zip(quantities, vendors):
            inventory[v["component"]] += q
        kits = min(market["target_kits"], *(inventory[c] // n for c, n in market["bom"].items()))
        if kits < market["minimum_service_kits"]:
            continue
        value = kits * number(market["revenue_per_kit_usd"]) - cost
        lines = {v["id"]: q for v, q in zip(vendors, quantities) if q}
        choices.append(dict(
            id="award:" + ",".join(f"{s}={q}" for s, q in lines.items()),
            payoffs_usd=[str(value)], quantities=lines,
            cost_usd=str(cost), completed_kits=kits,
        ))
    return choices


def evaluate(cases):
    rows = []
    for case in cases:
        evaluated = dict(case)
        if "allocation_market" in case:
            evaluated["terminal_choices"] = allocation_choices(case["allocation_market"])
        qs = action_values(evaluated)
        best = max(qs.values())
        winners = sorted(a for a, q in qs.items() if q == best)
        assert winners == case["expected_best_actions"], (case["id"], winners)
        assert best == number(case["expected_incremental_value_usd"]), (case["id"], best)
        alternatives = [q for a, q in qs.items() if a not in winners]
        rows.append(dict(
            case_id=case["id"], mechanism=case["mechanism"], best_actions=winners,
            incremental_value_usd=float(best),
            advantage_over_next_action_usd=float(best - max(alternatives)),
            action_values_usd={a: float(q) for a, q in qs.items()},
            chosen_allocations=[a for a in evaluated["terminal_choices"] if a["id"] in winners],
        ))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    source = args.fixtures.read_bytes()
    fixtures = json.loads(source)
    rows = evaluate(fixtures["cases"])
    result = dict(
        status="offline_design_examples_verified", model_calls=0,
        fixture_sha256=hashlib.sha256(source).hexdigest(),
        scope="Twelve decision points; not twelve independent markets or a live campaign",
        rows=rows,
    )
    content = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content)
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
