"""One canonical register of every typed Housing failure across campaigns.

Failures were recorded faithfully but only ever inside the campaign that
produced them, so a pattern spanning campaigns -- one condition failing
repeatedly, one provider degrading over weeks, one defect reappearing under a
new identity -- was invisible without opening a dozen bundles by hand.

This register reads only published evidence, never the ignored local run
directories, so every row can be traced back to a committed artifact by
digest. It is derived rather than written: regenerating it must reproduce the
same bytes, or the register and the evidence have diverged.
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

REGISTER_SCHEMA_VERSION = "aeread.housing_failure_register/0.1"

REGISTER_FIELDS = (
    "campaign_id",
    "stage",
    "failure_condition",
    "failure_status_code",
    "failure_type",
    "subject",
    "opponent",
    "condition_id",
    "config_id",
    "world_seed",
    "replicate_index",
    "model_id",
    "action_schema",
    "probe_index",
    "visible_attempts",
    "elapsed_seconds",
    "cost_usd",
    "source_artifact",
    "source_artifact_sha256",
)


def _rows_from_trajectories(
    campaign_id: str, bundle: Path
) -> Iterator[dict[str, Any]]:
    for name in ("attempted.json", "selected.json"):
        path = bundle / "trajectories" / name
        if not path.exists():
            continue
        payload = json.loads(path.read_bytes())
        for row in payload.get("trajectories", []):
            if row.get("status") == "completed":
                continue
            yield {
                "campaign_id": campaign_id,
                "stage": "trajectory",
                "failure_condition": row.get("failure_condition"),
                "failure_status_code": row.get("failure_status_code"),
                "failure_type": row.get("failure_type"),
                "subject": row.get("subject"),
                "opponent": row.get("opponent"),
                "condition_id": row.get("condition_id"),
                "config_id": row.get("config_id"),
                "world_seed": row.get("world_seed"),
                "replicate_index": row.get("replicate_index"),
                "model_id": None,
                "action_schema": None,
                "probe_index": None,
                "visible_attempts": row.get("effective_retry_count"),
                "elapsed_seconds": row.get("elapsed_seconds"),
                "cost_usd": row.get("cost_usd"),
                "source_artifact": (
                    f"evidence/{bundle.name}/trajectories/{name}"
                ),
                "source_artifact_sha256": payload.get("artifact_sha256"),
            }


def _rows_from_admission(
    campaign_id: str, bundle: Path
) -> Iterator[dict[str, Any]]:
    path = bundle / "tables" / "profile_admission.csv"
    if not path.exists():
        return
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("status") == "passed":
                continue
            yield {
                "campaign_id": campaign_id,
                "stage": "profile_admission",
                "failure_condition": row.get("failure_condition") or None,
                "failure_status_code": row.get("failure_status_code") or None,
                "failure_type": None,
                "subject": None,
                "opponent": None,
                "condition_id": None,
                "config_id": None,
                "world_seed": None,
                "replicate_index": None,
                "model_id": row.get("model_id"),
                "action_schema": row.get("action_schema"),
                "probe_index": row.get("probe_index"),
                "visible_attempts": row.get("visible_attempt_count") or None,
                "elapsed_seconds": row.get("elapsed_seconds") or None,
                "cost_usd": row.get("cost_usd") or None,
                "source_artifact": (
                    f"evidence/{bundle.name}/tables/profile_admission.csv"
                ),
                "source_artifact_sha256": digest,
            }


def _sort_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        "" if row.get(field) is None else str(row.get(field))
        for field in (
            "campaign_id",
            "stage",
            "config_id",
            "condition_id",
            "world_seed",
            "replicate_index",
            "model_id",
            "action_schema",
            "probe_index",
        )
    )


def collect_failures(evidence_root: Path) -> list[dict[str, Any]]:
    """Every typed failure published by any Housing campaign bundle."""

    rows: list[dict[str, Any]] = []
    for bundle in sorted(evidence_root.iterdir()):
        if not bundle.is_dir() or not bundle.name.startswith("housing_"):
            continue
        campaign_id = bundle.name
        rows.extend(_rows_from_admission(campaign_id, bundle))
        rows.extend(_rows_from_trajectories(campaign_id, bundle))
    rows.sort(key=_sort_key)
    return rows


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer, fieldnames=list(REGISTER_FIELDS), lineterminator="\n"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {field: ("" if row.get(field) is None else row[field]) for field in REGISTER_FIELDS}
        )
    return buffer.getvalue().encode("utf-8")


def build_register(evidence_root: Path) -> tuple[bytes, dict[str, Any]]:
    rows = collect_failures(evidence_root)
    payload = _csv_bytes(rows)

    def tally(field: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in rows:
            key = str(row.get(field) or "unknown")
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    core = {
        "schema_version": REGISTER_SCHEMA_VERSION,
        "register_id": "housing_failure_register",
        "purpose": (
            "Every typed Housing failure in one place, derived only from "
            "published evidence so each row traces to a committed artifact."
        ),
        "failure_count": len(rows),
        "rows_sha256": hashlib.sha256(payload).hexdigest(),
        "by_campaign": tally("campaign_id"),
        "by_stage": tally("stage"),
        "by_failure_condition": tally("failure_condition"),
        "by_condition_id": tally("condition_id"),
        "source_bundles": sorted({row["campaign_id"] for row in rows}),
    }
    summary = dict(core)
    summary["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(core)
    ).hexdigest()
    return payload, summary


def publish(evidence_root: Path, register_root: Path) -> dict[str, Any]:
    payload, summary = build_register(evidence_root)
    (register_root / "tables").mkdir(parents=True, exist_ok=True)
    (register_root / "reports").mkdir(parents=True, exist_ok=True)
    (register_root / "tables" / "failures.csv").write_bytes(payload)
    (register_root / "reports" / "summary.json").write_bytes(
        canonical_json_bytes(summary)
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the canonical Housing failure register"
    )
    repo_root = Path(__file__).resolve().parents[3]
    parser.add_argument("--evidence-root", default=str(repo_root / "evidence"))
    parser.add_argument(
        "--register-root",
        default=str(repo_root / "evidence" / "housing_failure_register"),
    )
    args = parser.parse_args(argv)
    summary = publish(Path(args.evidence_root), Path(args.register_root))
    print(canonical_json_bytes(summary).decode("utf-8"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
