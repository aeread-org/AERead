"""A typed taxonomy of Housing failures, derived from published evidence.

The register counts operational failures, which are route and infrastructure
events. This counts the failures inside trajectories that *completed*, which
are the ones that say something about an agent. They are invisible to the
primary outcome, because welfare cancels every transfer and an agent can sign
away its entire surplus without moving the score (D-16, D-27).

Three groups, and they call for different responses:

- **A, participation-constraint violations.** An agent agreed to terms worse
  than not trading, which it could have checked against its own private
  information alone. Self-checkable, so a floor or a gate can close them.
- **B, allocative shortfalls.** The market cleared somewhere other than where
  the oracle would. Not individually attributable: it takes both seats and
  the search process to leave surplus on the table.
- **C, process signatures.** Patterns in how an episode was conducted, which
  are not errors in themselves but separate a market that worked from one that
  churned.

Counting requires the world, because a violation is defined against private
values and costs that no published row carries. Worlds are regenerated from
the committed sweep contract by the deterministic generator, so every count
here traces to committed artifacts and regenerates byte for byte.

An action-level layer exists and is not published. It classifies individual
decisions, for instance a landlord countering at zero rent or a tenant walking
from a profitable hold, and it needs the episode event logs, which live in the
ignored run root. See the failure taxonomy document for that layer, its counts
and the reason they are labelled unverifiable.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import itertools
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes

from . import environment as hz

TAXONOMY_SCHEMA_VERSION = "aeread.housing_failure_taxonomy/0.1"

CLASSES: dict[str, str] = {
    "A1_tenant_signed_above_own_value": (
        "A signed lease left the tenant with negative surplus. Checkable "
        "against the tenant's own private values with no other information."
    ),
    "A2_landlord_signed_at_zero_rent": (
        "A lease was signed at exactly zero rent, so the landlord received "
        "nothing and bore its whole cost."
    ),
    "A3_landlord_signed_below_cost": (
        "A lease was signed at a positive rent below the landlord's own "
        "private cost. Same class as A2, without the zero."
    ),
    "A4_pair_destroys_value": (
        "The matched pair's value is below the listing's cost, so the lease "
        "destroys surplus outright and both seats consented to it."
    ),
    "B1_oracle_listing_left_empty": (
        "A listing the oracle assignment leases was never leased, so the "
        "market failed to clear where clearing was profitable."
    ),
    "B2_leased_a_listing_the_oracle_leaves_empty": (
        "A listing the oracle leaves empty was leased, which is not an error "
        "on its own but occupies a tenant the oracle places elsewhere."
    ),
    "B3_right_listings_wrong_tenants": (
        "The set of leased listings could have been assigned to higher-value "
        "tenants. This is the sorting shortfall, and it is the largest "
        "component of the gap below the oracle."
    ),
    "C1_wasted_contacts_above_one_per_tenant": (
        "More offers were discarded than there are tenants, so the search "
        "churned rather than converged."
    ),
    "C2_no_lease_signed": "The episode ended with no lease at all.",
    "C3_landlord_rejected_more_than_accepted": (
        "The landlord seat refused more often than it agreed. Not an error, "
        "but it distinguishes a conservative counterparty from a permissive "
        "one, which matters because counterparty behaviour drives the "
        "variance the paired design cannot remove (D-27)."
    ),
    "C4_tenant_walked_more_than_signed": (
        "The tenant seat abandoned more holds than it signed."
    ),
}

#: Enumerating assignments of tenants to leased listings is factorial, so the
#: sorting class is skipped above this width rather than silently timing out.
MAXIMUM_SORTING_WIDTH = 7


def _configs(sweep_paths: Sequence[Path]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in sweep_paths:
        if not path.exists():
            continue
        sweep = json.loads(path.read_bytes())
        for block, field in (
            ("confirmatory_holdout", "parameter_combinations"),
            ("development", "candidate_configs"),
        ):
            for config in sweep.get(block, {}).get(field, []) or []:
                out.setdefault(str(config["config_id"]), config)
    return out


def classify(
    row: Mapping[str, Any], config: Mapping[str, Any], world: Any
) -> dict[str, int]:
    """Every class this completed trajectory exhibits, with its occurrences."""

    found: collections.Counter[str] = collections.Counter()
    rents = {
        int(item["tenant_id"]): float(item["rent"])
        for item in row.get("signed_rents") or []
    }
    pairs = [tuple(pair) for pair in row.get("assignment_pairs") or []]
    for tenant, listing in pairs:
        if tenant not in rents:
            continue
        if world.values[tenant][listing] - rents[tenant] < 0:
            found["A1_tenant_signed_above_own_value"] += 1
        if rents[tenant] == 0.0:
            found["A2_landlord_signed_at_zero_rent"] += 1
        elif rents[tenant] - world.costs[listing] < 0:
            found["A3_landlord_signed_below_cost"] += 1
        if world.values[tenant][listing] - world.costs[listing] < 0:
            found["A4_pair_destroys_value"] += 1

    oracle = hz.assignment_oracle(world.surplus)
    oracle_listings = {listing for _, listing in oracle.pairs}
    leased = {listing for _, listing in pairs}
    if oracle_listings - leased:
        found["B1_oracle_listing_left_empty"] += 1
    if leased - oracle_listings:
        found["B2_leased_a_listing_the_oracle_leaves_empty"] += 1
    if leased and len(leased) <= MAXIMUM_SORTING_WIDTH:
        ordered = sorted(leased)
        best = max(
            (
                sum(world.values[t][l] - world.costs[l] for t, l in zip(choice, ordered))
                for choice in itertools.permutations(
                    range(config["tenants"]), len(ordered)
                )
            ),
            default=0.0,
        )
        realized = sum(world.values[t][l] - world.costs[l] for t, l in pairs)
        if best - realized > 1e-9:
            found["B3_right_listings_wrong_tenants"] += 1

    if (row.get("wasted_contacts") or 0) > config["tenants"]:
        found["C1_wasted_contacts_above_one_per_tenant"] += 1
    if not pairs:
        found["C2_no_lease_signed"] += 1
    outcomes = row.get("action_outcomes") or {}
    if outcomes.get("reject_all", 0) > outcomes.get("accept", 0):
        found["C3_landlord_rejected_more_than_accepted"] += 1
    if outcomes.get("walk", 0) > outcomes.get("sign", 0):
        found["C4_tenant_walked_more_than_signed"] += 1
    return dict(found)


def collect(evidence_root: Path, sweep_paths: Sequence[Path]) -> dict[str, Any]:
    configs = _configs(sweep_paths)
    worlds: dict[tuple[int, str], Any] = {}
    occurrences: collections.Counter[str] = collections.Counter()
    cases: dict[str, set[tuple[Any, ...]]] = collections.defaultdict(set)
    by_seat: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    examined = skipped = 0
    campaigns: set[str] = set()

    for bundle in sorted(evidence_root.iterdir()):
        path = bundle / "trajectories" / "attempted.json"
        if not (bundle.is_dir() and bundle.name.startswith("housing_") and path.exists()):
            continue
        for row in json.loads(path.read_bytes()).get("trajectories", []):
            if row.get("status") != "completed":
                continue
            config = configs.get(str(row.get("config_id")))
            bound = row.get("oracle_upper_bound")
            if (
                config is None
                or not isinstance(bound, (int, float))
                or isinstance(bound, bool)
                or bound <= 0
            ):
                skipped += 1
                continue
            key = (int(row["world_seed"]), str(row["config_id"]))
            if key not in worlds:
                worlds[key] = hz.make_bid_world(
                    config["tenants"],
                    config["listings"],
                    seed=key[0],
                    common_weight=config["common_weight"],
                )
            examined += 1
            campaigns.add(bundle.name)
            identity = (bundle.name, key[0], key[1], str(row.get("condition_id")))
            for name, count in classify(row, config, worlds[key]).items():
                occurrences[name] += count
                cases[name].add(identity)
                # A-class violations attach to the seat that agreed to them;
                # the tenant is the subject and the landlord the opponent.
                if name == "A1_tenant_signed_above_own_value":
                    by_seat[name][str(row.get("subject"))] += count
                elif name in ("A2_landlord_signed_at_zero_rent", "A3_landlord_signed_below_cost"):
                    by_seat[name][str(row.get("opponent"))] += count
    return {
        "examined": examined,
        "skipped_not_reconstructible": skipped,
        "campaigns": sorted(campaigns),
        "occurrences": dict(occurrences),
        "distinct_cases": {name: len(values) for name, values in cases.items()},
        "by_seat_model": {
            name: dict(sorted(counter.items())) for name, counter in by_seat.items()
        },
    }


def build(evidence_root: Path, sweep_paths: Sequence[Path]) -> dict[str, Any]:
    collected = collect(evidence_root, sweep_paths)
    core = {
        "schema_version": TAXONOMY_SCHEMA_VERSION,
        "analysis_id": "housing_failure_taxonomy",
        "purpose": (
            "Failures inside trajectories that completed, which the primary "
            "outcome cannot see because welfare cancels every transfer. The "
            "operational register counts a different thing: route events."
        ),
        "scope": (
            "Outcome level only, from committed rows plus worlds regenerated "
            "by the deterministic generator. The action-level layer needs "
            "episode logs, which are not published."
        ),
        "classes": CLASSES,
        "completed_trajectories_examined": collected["examined"],
        "completed_trajectories_not_reconstructible": collected[
            "skipped_not_reconstructible"
        ],
        "source_campaigns": collected["campaigns"],
        "occurrences": dict(sorted(collected["occurrences"].items())),
        "distinct_cases": dict(sorted(collected["distinct_cases"].items())),
        "attributable_by_seat_model": dict(sorted(collected["by_seat_model"].items())),
    }
    core["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(core)).hexdigest()
    return core


def publish(
    evidence_root: Path, sweep_paths: Sequence[Path], analysis_root: Path
) -> dict[str, Any]:
    summary = build(evidence_root, sweep_paths)
    (analysis_root / "reports").mkdir(parents=True, exist_ok=True)
    (analysis_root / "reports" / "summary.json").write_bytes(
        canonical_json_bytes(summary)
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description="Build the Housing failure taxonomy")
    parser.add_argument("--evidence-root", default=str(repo_root / "evidence"))
    parser.add_argument(
        "--analysis-root",
        default=str(repo_root / "evidence" / "housing" / "failure_taxonomy"),
    )
    args = parser.parse_args(argv)
    sweeps = [
        repo_root / "configs" / "housing_case_config_sweep_v2.json",
        repo_root / "configs" / "housing_case_config_sweep_v1.json",
    ]
    summary = publish(Path(args.evidence_root), sweeps, Path(args.analysis_root))
    print(canonical_json_bytes(summary).decode("utf-8"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
