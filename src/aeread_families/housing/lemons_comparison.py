"""Paired comparison of two lemons v2 routes on one frozen pack.

A derived analysis in the Tier 1 sense: it reads only the two published
bundles' ``tables/cells.jsonl`` and regenerates byte-identical output
(``--check``). The two identities share the environment, the pack, the
scripted landlord (pooled, HL-D-01) and every control except the route, so a world's difference is a like-for-like contrast of the two models as
tenant populations (each cell is a market of one model's six tenants).

The world is the unit: each metric is averaged over a world's completed
replicates per route, differenced within the world, and summarised by a
world-clustered percentile bootstrap from one declared stream. Descriptive:
24 worlds cannot support a ranking and the bundles claim development
qualification only.

The GLM bundle is an incomplete pack published by the owner's decision
(HL-O-07): world 100021 has one GLM seed, so that world's GLM mean is one cell.

``expected_net_payoff`` takes the luck of the lemon draws out (HL-J-01). A
signing the tenant made without inspecting the listing is a bet at its own
lemon probability; the endpoint counts each such lease at the expected value
the environment recorded for it at that probability (``commit_decisions``)
instead of at the true value it turned out to have. True values come from the
world regenerated from its published seed under the contract's environment,
which reproduces every published payoff.

    python -m aeread_families.housing.lemons_comparison --write
    python -m aeread_families.housing.lemons_comparison --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence" / "housing"
LEFT = "housing_lemons_refusal_v2_gemini38_flash"
RIGHT = "housing_lemons_refusal_v2_glm53_flash"
OUT = EVIDENCE / "housing_lemons_refusal_v2_comparison"
BOOTSTRAP_SEED = 20260925
BOOTSTRAP_DRAWS = 10000
#: Endpoints in the order the bootstrap stream serves them. Live minus the
#: inspect-then-sign reference is left out: the reference is scripted and the
#: same in both bundles, so its difference is the net-payoff difference.
ENDPOINTS = (
    "tenant_net_payoff",
    "expected_net_payoff",
    "within_case_score",
    "abstention_correctness_rate",
    "uninspected_lemon_signing_rate",
    "inspection_count",
)


def _rows(bundle: str, table: str) -> list[dict[str, Any]]:
    path = EVIDENCE / bundle / "tables" / f"{table}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


#: Scripted totals recorded on every cell, reported per route as context.
BENCHMARKS = ("reference_total", "sign_anything_total", "oracle_total")


@lru_cache(maxsize=None)
def _world(seed: int):
    from aeread_families.housing import lemons_campaign

    environments = [lemons_campaign.load_contract(ROOT / "configs" / f"{bundle}.json")["environment"] for bundle in (LEFT, RIGHT)]
    if environments[0] != environments[1]:
        raise ValueError("the two identities declare different environments; their worlds are not the same")
    return lemons_campaign._make_world(environments[0], seed)


def true_value(seed: int, tenant: int, listing: int) -> float:
    """What the listing is truly worth to the tenant in the published world."""
    return float(_world(seed).values[tenant][listing])


def _expected_net_payoff(row: Mapping[str, Any]) -> float:
    blind = [d for d in row.get("commit_decisions") or [] if d["decision"] == "sign" and not d["informed"]]
    return float(row["tenant_net_payoff"]) + sum(
        float(d["expected_value"]) - true_value(int(row["world_seed"]), int(d["tenant_id"]), int(d["listing_id"])) for d in blind
    )


def _cell_value(row: Mapping[str, Any], endpoint: str) -> float | None:
    if endpoint == "expected_net_payoff":
        return _expected_net_payoff(row)
    if endpoint == "uninspected_lemon_signing_rate":
        return 1.0 if int(row["uninspected_lemon_signings"]) > 0 else 0.0
    value = row.get(endpoint)
    return None if value is None else float(value)


def world_means(bundle: str) -> dict[int, dict[str, Any]]:
    """Per world: the stratum, completed cells, and each endpoint's mean over replicates."""
    out: dict[int, dict[str, Any]] = {}
    for row in _rows(bundle, "cells"):
        if row.get("stage") != "variance_pilot" or row.get("status") != "completed":
            continue
        world = out.setdefault(int(row["world_seed"]), {"stratum": row["stratum"], "cells": 0, "values": {e: [] for e in ENDPOINTS + BENCHMARKS}})
        world.setdefault("payoffs", []).append(float(row["tenant_net_payoff"]))
        world["cells"] += 1
        for endpoint in ENDPOINTS + BENCHMARKS:
            value = _cell_value(row, endpoint)
            if value is not None:
                world["values"][endpoint].append(value)
    for world in out.values():
        world["means"] = {e: (sum(v) / len(v) if v else None) for e, v in world.pop("values").items()}
        payoffs = world.pop("payoffs")
        world["spread"] = [min(payoffs), max(payoffs)]
    return out


def _bootstrap(values: Sequence[float], rng: random.Random) -> list[float] | None:
    if len(values) < 2:
        return None
    means = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(BOOTSTRAP_DRAWS))
    return [means[int(0.025 * BOOTSTRAP_DRAWS)], means[min(BOOTSTRAP_DRAWS - 1, int(0.975 * BOOTSTRAP_DRAWS))]]


def compare() -> dict[str, Any]:
    left, right = world_means(LEFT), world_means(RIGHT)
    paired = sorted(set(left) & set(right))
    rng = random.Random(BOOTSTRAP_SEED)
    slices = {"overall": paired}
    for stratum in sorted({left[w]["stratum"] for w in paired}):
        slices[stratum] = [w for w in paired if left[w]["stratum"] == stratum]
    result: dict[str, Any] = {}
    for name, worlds in slices.items():
        block: dict[str, Any] = {"worlds": len(worlds)}
        for benchmark in BENCHMARKS:
            block[benchmark] = {side: sum(m[w]["means"][benchmark] for w in worlds) / len(worlds) if worlds else None
                                for side, m in (("left", left), ("right", right))}
        for endpoint in ENDPOINTS:
            rows = [(left[w]["means"][endpoint], right[w]["means"][endpoint]) for w in worlds]
            rows = [(a, b) for a, b in rows if a is not None and b is not None]
            diffs = [a - b for a, b in rows]
            block[endpoint] = {
                "left_mean": sum(a for a, _ in rows) / len(rows) if rows else None,
                "right_mean": sum(b for _, b in rows) / len(rows) if rows else None,
                "difference": sum(diffs) / len(diffs) if diffs else None,
                "difference_ci95": _bootstrap(diffs, rng),
                "left_ci95": _bootstrap([a for a, _ in rows], rng),
                "right_ci95": _bootstrap([b for _, b in rows], rng),
                "worlds_left_higher": sum(1 for d in diffs if d > 0),
                "worlds_right_higher": sum(1 for d in diffs if d < 0),
            }
        result[name] = block
    world_rows = [
        {
            "world_seed": w,
            "stratum": left[w]["stratum"],
            "cells": {"left": left[w]["cells"], "right": right[w]["cells"]},
            "tenant_net_payoff_spread": {"left": left[w]["spread"], "right": right[w]["spread"]},
            **{e: {"left": left[w]["means"][e], "right": right[w]["means"][e]} for e in ENDPOINTS + BENCHMARKS},
        }
        for w in paired
    ]
    sources, incomplete = {}, {}
    for bundle in (LEFT, RIGHT):
        manifest = EVIDENCE / bundle / "publication_manifest.json"
        sources[bundle] = hashlib.sha256(manifest.read_bytes()).hexdigest()
        missing = json.loads(manifest.read_bytes()).get("missing_pilot_cells")
        if missing:
            incomplete[bundle] = missing
    return {
        "schema_version": "aeread.housing_lemons_comparison/0.1",
        "left": LEFT,
        "right": RIGHT,
        "difference": "left minus right, within world, then averaged over worlds",
        "claim_status": "development_qualification",
        "winner_claim_allowed": False,
        "inferential_model_ranking_allowed": False,
        "unit": "world_seed; each world's endpoint is the mean over its completed variance-pilot replicates",
        "bootstrap": {"seed": BOOTSTRAP_SEED, "draws": BOOTSTRAP_DRAWS, "interval": "percentile_95",
                      "stream": "one random.Random(seed) serves every interval: overall first, then each stratum; per endpoint in declared order the difference, then left, then right"},
        "endpoints": list(ENDPOINTS),
        "paired_worlds": len(paired),
        "unpaired_worlds": {"left_only": sorted(set(left) - set(right)), "right_only": sorted(set(right) - set(left))},
        "source_manifest_sha256": sources,
        "incomplete_packs": incomplete,
        "slices": result,
        "worlds": world_rows,
    }


def _readme(report: Mapping[str, Any]) -> str:
    o = report["slices"]["overall"]

    def line(endpoint: str, label: str, fmt: str = "{:.2f}") -> str:
        e = o[endpoint]
        ci = e["difference_ci95"]
        return (f"| {label} | {fmt.format(e['left_mean'])} | {fmt.format(e['right_mean'])} | "
                f"{fmt.format(e['difference'])} ({fmt.format(ci[0])} to {fmt.format(ci[1])}) | "
                f"{e['worlds_left_higher']} / {e['worlds_right_higher']} |")

    return "\n".join([
        f"# {OUT.name}",
        "",
        f"Paired comparison of `{LEFT}` (left) and `{RIGHT}` (right) on the same {report['paired_worlds']} "
        "lemons worlds, both with the pooled lemon landlord (HL-D-01) at temperature 1.0 (HL-D-02). "
        "Derived from the two published bundles by `python -m aeread_families.housing.lemons_comparison`; "
        "`--check` regenerates these bytes. Descriptive: no winner, no ranking.",
        "",
        *(
            f"`{bundle}` is an incomplete pack published by the owner's decision; missing as typed "
            f"missingness: {', '.join(f'`{cell}`' for cell in cells)}. That world's mean on that side "
            "uses the seeds it completed."
            for bundle, cells in report["incomplete_packs"].items()
        ),
        *([""] if report["incomplete_packs"] else []),
        "| endpoint | left | right | left minus right (95% world bootstrap) | worlds left higher / right higher |",
        "|---|---|---|---|---|",
        line("tenant_net_payoff", "tenant net payoff (market total)"),
        line("expected_net_payoff", "the same, blind signings at expected value (luck removed)"),
        line("within_case_score", "within-case score", "{:.3f}"),
        line("abstention_correctness_rate", "abstention correctness", "{:.3f}"),
        line("uninspected_lemon_signing_rate", "cells signing an uninspected lemon", "{:.3f}"),
        line("inspection_count", "inspections per cell", "{:.1f}"),
        "",
        "The second row takes the luck of the lemon draws out (HL-J-01): each lease a tenant signed without "
        "inspecting is counted at its expected value at that tenant's own lemon probability, as the environment "
        "recorded it, instead of the value it turned out to have. Most of the realized gap is those draws.",
        "",
        "Scripted benchmarks on the same worlds (left / right): "
        + "; ".join(f"{k.replace('_total', '').replace('_', ' ')} {o[k]['left']:.2f} / {o[k]['right']:.2f}" for k in BENCHMARKS)
        + ".",
        "",
        "Per-stratum slices and every world's means are in `reports/comparison.json`.",
        "",
    ])


def write() -> None:
    report = compare()
    (OUT / "reports").mkdir(parents=True, exist_ok=True)
    (OUT / "reports" / "comparison.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (OUT / "README.md").write_text(_readme(report))


def check() -> bool:
    report = compare()
    expected = json.dumps(report, indent=2, sort_keys=True) + "\n"
    ok = (OUT / "reports" / "comparison.json").read_text() == expected and (OUT / "README.md").read_text() == _readme(report)
    print("comparison regenerates to the committed bytes" if ok else "comparison differs from its generator")
    return ok


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        write()
        return 0
    if args.check:
        return 0 if check() else 1
    print(json.dumps(compare()["slices"]["overall"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
