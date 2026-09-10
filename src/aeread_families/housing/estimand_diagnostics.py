"""Does a published estimand respond to the seat the campaign compares?

The step that named Housing's root cause was a variance decomposition, and it
existed only as an ad-hoc script, which is the wrong resting state for the
evidence behind a claim. This module makes it reproducible: it reads committed
trajectory rows, attributes each metric's variance to the case, the opponent
and the subject, and regenerates byte for byte.

The reading is direct. A benchmark measures whichever factor carries its
metric's variance, regardless of which seat the design labels the subject. If
the subject's share is near zero, the campaign is measuring its worlds and its
counterparties, and no sample size or sealing discipline changes that, because
those protections assume the estimand responds to the comparison being made.

Two metrics are decomposed. ``within_case_score`` is welfare over the oracle
bound, published directly on every row. ``subject_surplus_share`` is the
tenants' realized surplus over the same bound, reconstructed from the row's
signed rents and the case's deterministic world, because rows sealed before
that field existed do not carry it. Reconstruction uses only the committed
sweep contract and the committed rows.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes

from . import environment as hz

DIAGNOSTICS_SCHEMA_VERSION = "aeread.housing_estimand_diagnostics/0.1"

#: A subject share is judged against chance, not against a fixed number.
#: Splitting a case's cells by a label captures variance even when the label
#: means nothing: for k groups and n cells the expected share is (k-1)/(n-1),
#: which is 0.143 for the two subjects and eight cells per case that Housing
#: runs. A raw share of 0.067 is therefore not merely small, it is half what a
#: coin flip would produce. This ratio replaces the arbitrary floor an earlier
#: version of this module used, which would have passed the very campaign the
#: module exists to catch.
MINIMUM_SIGNAL_TO_NULL_RATIO = 1.0


def _case_configs(sweep_path: Path) -> dict[str, dict[str, Any]]:
    """Every configuration the sweep defines, holdout and development alike.

    The holdout block lists ``parameter_combinations``; the development block
    lists ``candidate_configs``. Both are needed, because the campaigns worth
    decomposing include development lines as well as the confirmatory one.
    """

    sweep = json.loads(sweep_path.read_bytes())
    out: dict[str, dict[str, Any]] = {}
    for block, field in (
        ("confirmatory_holdout", "parameter_combinations"),
        ("development", "candidate_configs"),
    ):
        for config in sweep.get(block, {}).get(field, []) or []:
            out[str(config["config_id"])] = config
    return out


def enrich(
    rows: Sequence[Mapping[str, Any]], configs: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Attach the reconstructed surplus share to each completed row."""

    worlds: dict[tuple[int, str], Any] = {}
    enriched: list[dict[str, Any]] = []
    for row in rows:
        if row.get("status") != "completed":
            continue
        bound = row.get("oracle_upper_bound")
        config = configs.get(str(row.get("config_id")))
        if config is None or not isinstance(bound, (int, float)) or bound <= 0:
            continue
        key = (int(row["world_seed"]), str(row["config_id"]))
        if key not in worlds:
            worlds[key] = hz.make_bid_world(
                config["tenants"],
                config["listings"],
                seed=key[0],
                common_weight=config["common_weight"],
            )
        world = worlds[key]
        rents = {
            int(item["tenant_id"]): float(item["rent"])
            for item in row.get("signed_rents") or []
        }
        pairs = [tuple(pair) for pair in row.get("assignment_pairs") or []]
        surplus = sum(
            world.values[tenant][listing] - rents[tenant]
            for tenant, listing in pairs
            if tenant in rents
        )
        enriched.append(
            {
                "world_seed": key[0],
                "config_id": key[1],
                "subject": row["subject"],
                "opponent": row["opponent"],
                "within_case_score": float(row["within_case_score"]),
                "subject_surplus_share": surplus / float(bound),
            }
        )
    return enriched


def _share(
    rows: Sequence[Mapping[str, Any]], metric: str, key: Callable[[Mapping[str, Any]], Any]
) -> float:
    values = [row[metric] for row in rows]
    grand = statistics.fmean(values)
    total = sum((value - grand) ** 2 for value in values)
    if total <= 0:
        return 0.0
    groups: dict[Any, list[float]] = collections.defaultdict(list)
    for row in rows:
        groups[key(row)].append(row[metric])
    between = sum(
        len(group) * (statistics.fmean(group) - grand) ** 2 for group in groups.values()
    )
    return between / total


def _expected_share_under_null(
    rows: Sequence[Mapping[str, Any]], key: Callable[[Mapping[str, Any]], Any]
) -> float:
    """Share a meaningless label would capture, weighted as the real one is.

    Within a case of ``n`` cells split into ``k`` groups, a label carrying no
    information still explains ``(k-1)/(n-1)`` of the within-case sum of
    squares in expectation. Cases contribute in proportion to their cell
    count, matching how the observed share pools them.
    """

    cases: dict[Any, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        cases[(row["world_seed"], row["config_id"])].append(row)
    weighted, total = 0.0, 0
    for group in cases.values():
        cells = len(group)
        groups = len({key(row) for row in group})
        if cells < 2 or groups < 2:
            continue
        weighted += cells * (groups - 1) / (cells - 1)
        total += cells
    return weighted / total if total else 0.0


def _within_case_share(
    rows: Sequence[Mapping[str, Any]], metric: str, key: Callable[[Mapping[str, Any]], Any]
) -> float:
    cases: dict[Any, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        cases[(row["world_seed"], row["config_id"])].append(row)
    residual = sum(
        (row[metric] - statistics.fmean([r[metric] for r in group])) ** 2
        for group in cases.values()
        for row in group
    )
    if residual <= 0:
        return 0.0
    between = 0.0
    for group in cases.values():
        centre = statistics.fmean([r[metric] for r in group])
        buckets: dict[Any, list[float]] = collections.defaultdict(list)
        for row in group:
            buckets[key(row)].append(row[metric])
        between += sum(
            len(bucket) * (statistics.fmean(bucket) - centre) ** 2
            for bucket in buckets.values()
        )
    return between / residual


def decompose(rows: Sequence[Mapping[str, Any]], metric: str) -> dict[str, Any]:
    """Attribute a metric's variance to the case, the opponent and the subject."""

    case = lambda row: (row["world_seed"], row["config_id"])  # noqa: E731
    subject_total = _share(rows, metric, lambda row: row["subject"])
    subject_within = _within_case_share(rows, metric, lambda row: row["subject"])
    null_share = _expected_share_under_null(rows, lambda row: row["subject"])
    return {
        "metric": metric,
        "cells": len(rows),
        "case_share_of_total": round(_share(rows, metric, case), 6),
        "opponent_share_of_total": round(
            _share(rows, metric, lambda row: row["opponent"]), 6
        ),
        "subject_share_of_total": round(subject_total, 6),
        "opponent_share_within_case": round(
            _within_case_share(rows, metric, lambda row: row["opponent"]), 6
        ),
        "subject_share_within_case": round(subject_within, 6),
        # The cleaner quantity: how many times more of the within-case
        # variation the counterparty carries than the seat under test.
        "opponent_to_subject_leverage": (
            round(
                _within_case_share(rows, metric, lambda row: row["opponent"])
                / subject_within,
                3,
            )
            if subject_within > 0
            else None
        ),
        "subject_share_under_null": round(null_share, 6),
        "subject_signal_to_null_ratio": (
            round(subject_within / null_share, 3) if null_share > 0 else None
        ),
        "subject_signal_above_chance": bool(
            null_share > 0
            and subject_within / null_share >= MINIMUM_SIGNAL_TO_NULL_RATIO
        ),
    }


def collect(evidence_root: Path, sweep_path: Path) -> dict[str, list[dict[str, Any]]]:
    configs = _case_configs(sweep_path)
    out: dict[str, list[dict[str, Any]]] = {}
    for bundle in sorted(evidence_root.iterdir()):
        path = bundle / "trajectories" / "attempted.json"
        if not bundle.is_dir() or not bundle.name.startswith("housing_") or not path.exists():
            continue
        payload = json.loads(path.read_bytes())
        rows = enrich(payload.get("trajectories", []), configs)
        # A decomposition needs both seats to vary, or the shares are undefined.
        if len(rows) >= 8 and len({row["subject"] for row in rows}) > 1:
            out[bundle.name] = rows
    return out


def build(evidence_root: Path, sweep_path: Path) -> dict[str, Any]:
    by_campaign = {}
    for campaign, rows in collect(evidence_root, sweep_path).items():
        by_campaign[campaign] = {
            metric: decompose(rows, metric)
            for metric in ("within_case_score", "subject_surplus_share")
        }
    core = {
        "schema_version": DIAGNOSTICS_SCHEMA_VERSION,
        "analysis_id": "housing_estimand_diagnostics",
        "purpose": (
            "Whether a published estimand responds to the seat the campaign "
            "compares, by attributing its variance to case, opponent and "
            "subject. A benchmark measures whichever factor carries the "
            "variance, whatever the design calls the subject."
        ),
        "minimum_signal_to_null_ratio": MINIMUM_SIGNAL_TO_NULL_RATIO,
        "how_to_read": (
            "subject_share_within_case is compared with subject_share_under_null, "
            "the share a meaningless label captures by chance in the same design. "
            "A ratio at or below 1 means the estimand carries no subject signal "
            "beyond a coin flip, and no sample size recovers a comparison."
        ),
        "by_campaign": by_campaign,
    }
    core["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(core)).hexdigest()
    return core


def publish(evidence_root: Path, sweep_path: Path, analysis_root: Path) -> dict[str, Any]:
    summary = build(evidence_root, sweep_path)
    (analysis_root / "reports").mkdir(parents=True, exist_ok=True)
    (analysis_root / "reports" / "summary.json").write_bytes(canonical_json_bytes(summary))
    return summary


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", default=str(repo_root / "evidence"))
    parser.add_argument(
        "--sweep", default=str(repo_root / "configs" / "housing_case_config_sweep_v2.json")
    )
    parser.add_argument(
        "--analysis-root",
        default=str(repo_root / "evidence" / "housing" / "estimand_diagnostics"),
    )
    args = parser.parse_args(argv)
    summary = publish(Path(args.evidence_root), Path(args.sweep), Path(args.analysis_root))
    print(canonical_json_bytes(summary).decode("utf-8"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
