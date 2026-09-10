"""Provider-free proof that an estimand can see the seat it is meant to measure.

Gate 3 of the benchmark QC standard requires this before a campaign is frozen,
because twice a family has spent a full campaign on a metric structurally
incapable of responding to the agent under test. Housing's welfare sums value
minus rent plus rent minus cost, so every transfer cancels and the score moves
only through the assignment; the tenant seat's only lever is the price it
agrees to; and the 720-cell confirmatory comparison reported a precise null in
which the subject explained 0.000 of score variance (D-27).

Two known-ordered tenant policies make that visible without a provider. A
truthful bidder offers its full valuation, so it wins allocations as often as a
shrewd bidder and captures none of the surplus. Any metric that rates the two
alike is transfer-blind and must not be the sole primary. A metric that
separates them is measuring the distribution side.

The counterparty is swept as a controlled variable. A concessive landlord signs
below its own cost or counters at the rent floor at a declared rate, which is
the failure the confirmatory campaign observed 264 times. Sweeping it separates
two explanations that the live evidence confounds: an estimand that cannot see
the subject, and a counterparty whose own failures inject variance the paired
design cannot remove.

Everything here is deterministic given the panel and the declared seeds, so the
artifact regenerates byte for byte.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes

from . import environment as hz

CONTROL_SCHEMA_VERSION = "aeread.housing_sensitivity_control/0.1"

#: Policies whose ordering on the distribution side is known before the run.
#: ``truthful`` is the probe: it wins allocations like ``naive`` and captures
#: nothing, so welfare must rate them alike and surplus must not.
#: Sweeping a counterparty that violates its own participation constraint, a
#: real skill difference between two scripted tenant policies is detected at
#: 0.0%, 1.2% and 4.4% of cells carrying an opponent-seat violation, with the
#: contrast's spread rising from 0.019 to 0.139, and is no longer detected at
#: 10.7%, where the spread reaches 0.322. The confirmatory campaign observed
#: 4.7% under a DeepSeek landlord and 59.5% under a GLM landlord, and its
#: distribution-side contrast was decisive in the first case and absent in the
#: second. A campaign comparing on the distribution side should declare a
#: ceiling at or below this value. See `by_concession_rate` in the published
#: summary for the sweep this is read from.
RECOMMENDED_MAXIMUM_OPPONENT_IR_VIOLATION_FRACTION = 0.05

TENANT_POLICIES = ("random", "truthful", "naive", "adaptive", "oracle_informed")
LANDLORD_POLICIES = ("scripted", "concessive")


def _gain(world: hz.BidWorld, tenant: int, listing: int) -> float:
    return world.values[tenant][listing] - world.ask[listing]


def _tenant_offers(
    policy: str,
    market: hz.HousingMarket,
    state: dict[str, Any],
    rng: random.Random,
    oracle_listing: Mapping[int, int],
) -> dict[int, tuple[int, float]]:
    world = market.world
    offers: dict[int, tuple[int, float]] = {}
    bump = state.setdefault("bump", {})
    for tenant in market.unmatched_tenants():
        open_listings = market.open_listings()
        if policy == "oracle_informed":
            listing = oracle_listing.get(tenant)
            if listing is None or listing not in open_listings:
                continue
            candidates = [listing]
        else:
            candidates = [
                listing
                for listing in open_listings
                if _gain(world, tenant, listing) > 0
                and (policy != "adaptive" or listing not in market.rejected[tenant])
            ]
        if not candidates:
            continue
        if policy == "random":
            listing = rng.choice(candidates)
        else:
            listing = max(candidates, key=lambda x: _gain(world, tenant, x))
        if policy == "truthful":
            rent = world.values[tenant][listing]
        elif policy == "adaptive":
            rent = world.ask[listing] + bump.get(tenant, 0.0)
        else:
            rent = world.ask[listing] + 1.0
        if rent > world.values[tenant][listing]:
            continue
        if rent < market.minimum_rent:
            continue
        offers[tenant] = (listing, rent)
    return offers


def _landlord_responses(
    policy: str,
    market: hz.HousingMarket,
    inbox: Mapping[int, Sequence[Any]],
    rng: random.Random,
    concession_rate: float,
) -> dict[int, dict[int, tuple[str, float | None]]]:
    scripted = hz.scripted_landlord_responses(market, inbox)
    if policy == "scripted" or concession_rate <= 0.0:
        return scripted
    out: dict[int, dict[int, tuple[str, float | None]]] = {}
    for listing, offers in inbox.items():
        if not offers or rng.random() >= concession_rate:
            out[listing] = scripted[listing]
            continue
        # The observed failure: sign the best offer regardless of cost, or
        # concede the unit at the floor. Both are participation-constraint
        # violations by the landlord, not by the tenant under test.
        best = max(offers, key=lambda offer: offer.rent)
        per: dict[int, tuple[str, float | None]] = {}
        if rng.random() < 0.5:
            per[best.tenant_id] = ("accept", None)
        else:
            per[best.tenant_id] = ("counter", max(market.minimum_rent, 0.0))
        for offer in offers:
            per.setdefault(offer.tenant_id, ("reject", None))
        out[listing] = per
    return out


def play(
    world: hz.BidWorld,
    *,
    rounds: int,
    tenant_policy: str,
    landlord_policy: str = "scripted",
    concession_rate: float = 0.0,
    minimum_rent: float = 0.0,
    seed: int,
) -> dict[str, Any]:
    """One provider-free episode; returns both estimands and the seat-split IR."""

    rng = random.Random(seed)
    market = hz.HousingMarket(world, rounds=rounds, minimum_rent=minimum_rent)
    oracle = hz.assignment_oracle(world.surplus)
    oracle_listing = {tenant: listing for tenant, listing in oracle.pairs}
    state: dict[str, Any] = {}
    while not market.finished:
        offers = _tenant_offers(tenant_policy, market, state, rng, oracle_listing)
        contact = market.submit_offers(offers)
        response = market.submit_responses(
            _landlord_responses(
                landlord_policy, market, contact.inbox, rng, concession_rate
            )
        )
        commits: dict[int, tuple[str, str]] = {}
        for tenant, hold in response.holds.items():
            commits[tenant] = (
                ("sign", hold.hold_id)
                if hold.rent <= world.values[tenant][hold.listing_id]
                else ("walk", hold.hold_id)
            )
        for tenant in market.unmatched_tenants():
            if tenant not in response.holds:
                state.setdefault("bump", {})
                state["bump"][tenant] = state["bump"].get(tenant, 0.0) + 50.0
        market.submit_commits(commits)
    economics = market.economics()
    total = oracle.total
    tenant_surplus = sum(
        world.values[tenant][listing] - economics.signed_rents[tenant]
        for tenant, listing in economics.assignment.pairs
    )
    violations = [str(item) for item in economics.ir_violations]
    return {
        "welfare": economics.social_welfare / total if total > 0 else None,
        "tenant_surplus": tenant_surplus / total if total > 0 else None,
        "subject_seat_ir_violations": sum(1 for v in violations if v.startswith("tenant:")),
        "opponent_seat_ir_violations": sum(1 for v in violations if v.startswith("landlord:")),
        "leases": len(economics.assignment.pairs),
    }


def _interval(values: Sequence[float], alpha: float = 0.05) -> dict[str, Any]:
    count = len(values)
    if count < 2:
        return {"n": count, "mean": None, "lower": None, "upper": None, "excludes_zero": False}
    mean = statistics.fmean(values)
    deviation = statistics.stdev(values)
    error = deviation / math.sqrt(count)
    # Two-sided Student t at alpha, by bisection on the regularized incomplete
    # beta, so the module carries no numerical dependency.
    freedom = count - 1

    def cdf(t: float) -> float:
        x = freedom / (freedom + t * t)
        return 1.0 - 0.5 * _betainc(freedom / 2.0, 0.5, x) if t > 0 else 0.5 * _betainc(
            freedom / 2.0, 0.5, x
        )

    low, high = 0.0, 100.0
    for _ in range(200):
        mid = (low + high) / 2.0
        if cdf(mid) < 1.0 - alpha / 2.0:
            low = mid
        else:
            high = mid
    critical = (low + high) / 2.0
    lower, upper = mean - critical * error, mean + critical * error
    return {
        "n": count,
        "mean": round(mean, 9),
        "standard_deviation": round(deviation, 9),
        "lower": round(lower, 9),
        "upper": round(upper, 9),
        "excludes_zero": bool(lower > 0 or upper < 0),
    }


def _betainc(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1.0 - x) * b - lbeta) / a
    f, c, d = 1.0, 1.0, 0.0
    for i in range(0, 300):
        m = i // 2
        if i == 0:
            numerator = 1.0
        elif i % 2 == 0:
            numerator = (m * (b - m) * x) / ((a + 2.0 * m - 1.0) * (a + 2.0 * m))
        else:
            numerator = -((a + m) * (a + b + m) * x) / ((a + 2.0 * m) * (a + 2.0 * m + 1.0))
        d = 1.0 + numerator * d
        d = 1e-30 if abs(d) < 1e-30 else d
        d = 1.0 / d
        c = 1.0 + numerator / c
        c = 1e-30 if abs(c) < 1e-30 else c
        f *= c * d
        if abs(1.0 - c * d) < 1e-12:
            break
    result = front * (f - 1.0)
    return result if a + 1.0 > (a + b + 2.0) * x else 1.0 - _betainc(b, a, 1.0 - x)


def panel_cases(sweep_path: Path) -> list[dict[str, Any]]:
    """The sealed holdout panel: every world by every configuration."""

    sweep = json.loads(sweep_path.read_bytes())
    holdout = sweep["confirmatory_holdout"]
    excluded = {114691332}
    return [
        {**config, "world_seed": seed}
        for config in holdout["parameter_combinations"]
        for seed in holdout["world_seeds"]
        if seed not in excluded
    ]


def run(
    cases: Sequence[Mapping[str, Any]],
    *,
    concession_rates: Sequence[float] = (0.0, 0.1, 0.2, 0.4),
    minimum_rent: float = 0.0,
    replicates: int = 2,
    seed_base: int = 41001,
) -> dict[str, Any]:
    """Score every policy on every case, sweeping counterparty concession."""

    rows: list[dict[str, Any]] = []
    worlds: dict[tuple[int, str], hz.BidWorld] = {}
    for case in cases:
        key = (int(case["world_seed"]), str(case["config_id"]))
        if key not in worlds:
            worlds[key] = hz.make_bid_world(
                case["tenants"],
                case["listings"],
                seed=int(case["world_seed"]),
                common_weight=case["common_weight"],
            )
        world = worlds[key]
        if hz.assignment_oracle(world.surplus).total <= 0:
            continue
        for rate in concession_rates:
            landlord = "scripted" if rate == 0.0 else "concessive"
            for policy in TENANT_POLICIES:
                for replicate in range(replicates):
                    # A stable digest, not ``hash``: PYTHONHASHSEED is salted
                    # per process, so ``hash`` would break regeneration.
                    token = f"{key[0]}:{key[1]}:{policy}:{rate}:{replicate}"
                    seed = seed_base + int(
                        hashlib.sha256(token.encode("utf-8")).hexdigest()[:8], 16
                    ) % 100000
                    outcome = play(
                        world,
                        rounds=case["rounds"],
                        tenant_policy=policy,
                        landlord_policy=landlord,
                        concession_rate=rate,
                        minimum_rent=minimum_rent,
                        seed=seed,
                    )
                    rows.append(
                        {
                            "world_seed": key[0],
                            "config_id": key[1],
                            "tenant_policy": policy,
                            "landlord_policy": landlord,
                            "concession_rate": rate,
                            "replicate_index": replicate,
                            **outcome,
                        }
                    )
    return {"rows": rows, "case_count": len(worlds)}


def _paired(rows: Sequence[Mapping[str, Any]], metric: str, a: str, b: str) -> dict[str, Any]:
    """Paired world-level contrast between two policies, the frozen structure."""

    seeds = sorted({row["world_seed"] for row in rows})
    contrasts = []
    for seed in seeds:
        means = {}
        for policy in (a, b):
            values = [
                row[metric]
                for row in rows
                if row["world_seed"] == seed
                and row["tenant_policy"] == policy
                and row[metric] is not None
            ]
            if values:
                means[policy] = statistics.fmean(values)
        if len(means) == 2:
            contrasts.append(means[a] - means[b])
    return _interval(contrasts)


def analyse(result: Mapping[str, Any]) -> dict[str, Any]:
    rows = result["rows"]
    rates = sorted({row["concession_rate"] for row in rows})
    by_rate: dict[str, Any] = {}
    for rate in rates:
        selected = [row for row in rows if row["concession_rate"] == rate]
        means = {
            policy: {
                metric: round(
                    statistics.fmean(
                        [
                            row[metric]
                            for row in selected
                            if row["tenant_policy"] == policy and row[metric] is not None
                        ]
                    ),
                    6,
                )
                for metric in ("welfare", "tenant_surplus")
            }
            for policy in TENANT_POLICIES
        }
        by_rate[str(rate)] = {
            "policy_means": means,
            # The transfer-blindness probe: a truthful bidder wins allocations
            # like a shrewd one and captures nothing.
            "naive_minus_truthful": {
                metric: _paired(selected, metric, "naive", "truthful")
                for metric in ("welfare", "tenant_surplus")
            },
            # Two policies that differ in skill, not in transfer behaviour.
            "adaptive_minus_naive": {
                metric: _paired(selected, metric, "adaptive", "naive")
                for metric in ("welfare", "tenant_surplus")
            },
            "opponent_ir_violation_rate": round(
                statistics.fmean(
                    [1.0 if row["opponent_seat_ir_violations"] else 0.0 for row in selected]
                ),
                6,
            ),
        }
    core = {
        "schema_version": CONTROL_SCHEMA_VERSION,
        "control_id": "housing_estimand_sensitivity_control",
        "purpose": (
            "Provider-free evidence that an estimand responds to the seat under "
            "test, and that a counterparty violating its own participation "
            "constraint is what removes the response."
        ),
        "case_count": result["case_count"],
        "episode_count": len(rows),
        "tenant_policies": list(TENANT_POLICIES),
        "by_concession_rate": by_rate,
    }
    core["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(core)).hexdigest()
    return core


def publish(sweep_path: Path, control_root: Path, *, minimum_rent: float = 0.0) -> dict[str, Any]:
    summary = analyse(run(panel_cases(sweep_path), minimum_rent=minimum_rent))
    (control_root / "reports").mkdir(parents=True, exist_ok=True)
    (control_root / "reports" / "summary.json").write_bytes(canonical_json_bytes(summary))
    return summary


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sweep", default=str(repo_root / "configs" / "housing_case_config_sweep_v2.json")
    )
    parser.add_argument(
        "--control-root",
        default=str(repo_root / "evidence" / "housing" / "estimand_sensitivity_control"),
    )
    parser.add_argument("--minimum-rent", type=float, default=0.0)
    args = parser.parse_args(argv)
    summary = publish(
        Path(args.sweep), Path(args.control_root), minimum_rent=args.minimum_rent
    )
    print(canonical_json_bytes(summary).decode("utf-8"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
