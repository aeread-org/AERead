"""Landlord-seat accounting, derived only from published Housing evidence.

The primary Housing outcome is invariant to price: welfare sums value minus
cost over signed pairs, so every rent cancels and a landlord that gives a unit
away for nothing scores the same as one that charges the ask. The
confirmatory comparison could therefore find the two models indistinguishable
as tenants while one of them, in the landlord seat, signed 264 leases at rent
zero (incidents D-16, D-22). The fields that see this, ``signed_rents`` and
``ir_violation_count``, were published per trajectory and never aggregated.

This module aggregates them. Like the failure register it reads only
committed bundles, never the ignored local run roots, so every number traces
to a committed artifact by digest and regenerating it must reproduce the
committed bytes. It cannot say why a lease was signed at zero; that lives in
the local run root and the publication policy excludes it.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterator, Mapping

from aeread.shared_runner.run.resolver import canonical_json_bytes

ACCOUNTING_SCHEMA_VERSION = "aeread.housing_landlord_seat_accounting/0.1"

BY_SEAT_FIELDS = (
    "campaign_id",
    "landlord_model",
    "completed_cells",
    "signed_leases",
    "zero_rent_leases",
    "zero_rent_lease_share",
    "ir_violations",
    "cells_with_ir_violation",
    "cells_with_ir_violation_share",
    "mean_within_case_score",
    "source_artifact",
    "source_artifact_sha256",
)

BY_WORLD_FIELDS = (
    "campaign_id",
    "landlord_model",
    "world_seed",
    "completed_cells",
    "signed_leases",
    "zero_rent_leases",
    "ir_violations",
    "cells_with_ir_violation",
    "source_artifact",
    "source_artifact_sha256",
)


def _trajectory_bundles(evidence_root: Path) -> Iterator[tuple[str, Path, dict[str, Any]]]:
    for bundle in sorted(evidence_root.iterdir()):
        if not bundle.is_dir() or not bundle.name.startswith("housing_"):
            continue
        path = bundle / "trajectories" / "attempted.json"
        if not path.exists():
            continue
        yield bundle.name, path, json.loads(path.read_bytes())


def _zero_rent_count(row: Mapping[str, Any]) -> int:
    rents = row.get("signed_rents") or []
    return sum(1 for item in rents if float(item["rent"]) == 0.0)


def collect(evidence_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Per-seat and per-world accounting rows, plus bundles that lack the fields."""

    by_seat: list[dict[str, Any]] = []
    by_world: list[dict[str, Any]] = []
    without_fields: list[str] = []
    for campaign_id, path, payload in _trajectory_bundles(evidence_root):
        rows = [
            row
            for row in payload.get("trajectories", [])
            if row.get("status") == "completed"
        ]
        if not rows or any("signed_rents" not in row or "ir_violation_count" not in row for row in rows):
            without_fields.append(campaign_id)
            continue
        source = f"evidence/{campaign_id}/trajectories/attempted.json"
        digest = payload.get("artifact_sha256")
        seats: dict[str, dict[str, Any]] = {}
        worlds: dict[tuple[str, int], dict[str, Any]] = {}
        for row in rows:
            landlord = str(row["opponent"])
            seat = seats.setdefault(
                landlord,
                {
                    "completed_cells": 0,
                    "signed_leases": 0,
                    "zero_rent_leases": 0,
                    "ir_violations": 0,
                    "cells_with_ir_violation": 0,
                    "score_sum": 0.0,
                },
            )
            world = worlds.setdefault(
                (landlord, int(row["world_seed"])),
                {
                    "completed_cells": 0,
                    "signed_leases": 0,
                    "zero_rent_leases": 0,
                    "ir_violations": 0,
                    "cells_with_ir_violation": 0,
                },
            )
            leases = len(row.get("signed_rents") or [])
            zero = _zero_rent_count(row)
            violations = int(row.get("ir_violation_count") or 0)
            for bucket in (seat, world):
                bucket["completed_cells"] += 1
                bucket["signed_leases"] += leases
                bucket["zero_rent_leases"] += zero
                bucket["ir_violations"] += violations
                bucket["cells_with_ir_violation"] += 1 if violations > 0 else 0
            seat["score_sum"] += float(row["within_case_score"])
        for landlord, seat in sorted(seats.items()):
            by_seat.append(
                {
                    "campaign_id": campaign_id,
                    "landlord_model": landlord,
                    "completed_cells": seat["completed_cells"],
                    "signed_leases": seat["signed_leases"],
                    "zero_rent_leases": seat["zero_rent_leases"],
                    "zero_rent_lease_share": (
                        round(seat["zero_rent_leases"] / seat["signed_leases"], 6)
                        if seat["signed_leases"]
                        else 0.0
                    ),
                    "ir_violations": seat["ir_violations"],
                    "cells_with_ir_violation": seat["cells_with_ir_violation"],
                    "cells_with_ir_violation_share": round(
                        seat["cells_with_ir_violation"] / seat["completed_cells"], 6
                    ),
                    "mean_within_case_score": round(
                        seat["score_sum"] / seat["completed_cells"], 6
                    ),
                    "source_artifact": source,
                    "source_artifact_sha256": digest,
                }
            )
        for (landlord, world_seed), world in sorted(worlds.items()):
            by_world.append(
                {
                    "campaign_id": campaign_id,
                    "landlord_model": landlord,
                    "world_seed": world_seed,
                    **{k: world[k] for k in ("completed_cells", "signed_leases", "zero_rent_leases", "ir_violations", "cells_with_ir_violation")},
                    "source_artifact": source,
                    "source_artifact_sha256": digest,
                }
            )
    return by_seat, by_world, without_fields


def _csv_bytes(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(fields), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({f: ("" if row.get(f) is None else row[f]) for f in fields})
    return buffer.getvalue().encode("utf-8")


def build(evidence_root: Path) -> tuple[bytes, bytes, dict[str, Any]]:
    by_seat, by_world, without_fields = collect(evidence_root)
    seat_bytes = _csv_bytes(by_seat, BY_SEAT_FIELDS)
    world_bytes = _csv_bytes(by_world, BY_WORLD_FIELDS)
    core = {
        "schema_version": ACCOUNTING_SCHEMA_VERSION,
        "analysis_id": "housing_landlord_seat_accounting",
        "purpose": (
            "Zero-rent leases and IR violations per landlord seat, aggregated "
            "from published per-trajectory rows the primary outcome cannot see "
            "because welfare cancels rent."
        ),
        "what_this_cannot_show": (
            "Why a lease was signed at zero rent. The originating actions and "
            "any reasoning live in the uncommitted local run root."
        ),
        "by_seat_sha256": hashlib.sha256(seat_bytes).hexdigest(),
        "by_world_sha256": hashlib.sha256(world_bytes).hexdigest(),
        "by_seat": [
            {
                k: row[k]
                for k in (
                    "campaign_id",
                    "landlord_model",
                    "completed_cells",
                    "signed_leases",
                    "zero_rent_leases",
                    "zero_rent_lease_share",
                    "ir_violations",
                    "cells_with_ir_violation",
                    "cells_with_ir_violation_share",
                    "mean_within_case_score",
                )
            }
            for row in by_seat
        ],
        "source_bundles": sorted({row["campaign_id"] for row in by_seat}),
        "bundles_without_accounting_fields": sorted(without_fields),
    }
    summary = dict(core)
    summary["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(core)).hexdigest()
    return seat_bytes, world_bytes, summary


def publish(evidence_root: Path, analysis_root: Path) -> dict[str, Any]:
    seat_bytes, world_bytes, summary = build(evidence_root)
    (analysis_root / "tables").mkdir(parents=True, exist_ok=True)
    (analysis_root / "reports").mkdir(parents=True, exist_ok=True)
    (analysis_root / "tables" / "by_seat.csv").write_bytes(seat_bytes)
    (analysis_root / "tables" / "by_world.csv").write_bytes(world_bytes)
    (analysis_root / "reports" / "summary.json").write_bytes(canonical_json_bytes(summary))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Housing landlord-seat accounting analysis")
    repo_root = Path(__file__).resolve().parents[3]
    parser.add_argument("--evidence-root", default=str(repo_root / "evidence"))
    parser.add_argument(
        "--analysis-root",
        default=str(repo_root / "evidence" / "housing" / "landlord_seat_accounting"),
    )
    args = parser.parse_args(argv)
    summary = publish(Path(args.evidence_root), Path(args.analysis_root))
    print(canonical_json_bytes(summary).decode("utf-8"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
