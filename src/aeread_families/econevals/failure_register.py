"""Tier 1 failure register for the econevals family.

Builds `evidence/econevals_failure_register/` from sealed run evidence: one
row per failed canary probe and per failed case, each carrying the artifact
it came from and that artifact's digest, so every row can be traced back
without trusting this script. Regenerated, never hand-edited -- see
`docs/operations/incident_log.md` for the register standard.

The judgment half of the record (why a panel was badly designed, why a
claim was overstated) is deliberately not here: it cannot be derived from
evidence, and lives in the incident log instead.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterator, Mapping

from aeread.shared_runner.run.publication import assert_public_payload, atomic_publish
from aeread.shared_runner.run.resolver import canonical_json_bytes

REGISTER_ID = "econevals_failure_register"
SCHEMA_VERSION = "aeread.failure_register/0.1"
PURPOSE = (
    "Every typed econevals failure in one place, derived only from sealed run "
    "evidence so each row traces to a committed artifact."
)
ROW_FIELDS = (
    "campaign_id",
    "attempt",
    "stage",
    "case_id",
    "track",
    "failure_condition",
    "failure_type",
    "provider_call_failures",
    "retried_conditions",
    "attribution",
    "cost_usd",
    "source_artifact",
    "source_artifact_sha256",
)
# The standard's taxonomy: anything a model can trigger is the model's,
# never the provider's.
_PROVIDER_CONDITIONS = frozenset(
    {"rate_limit", "provider_5xx", "provider_rejected", "timeout", "transport"}
)
_ENVIRONMENT_CONDITIONS = frozenset({"provider_contract", "harness_contract"})


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _attribution(condition: str | None, failure_type: str | None) -> str:
    if condition in _PROVIDER_CONDITIONS:
        return "provider"
    if condition in _ENVIRONMENT_CONDITIONS:
        return "environment"
    if condition in {"malformed_structured_output", "empty_response"}:
        return "model"
    if failure_type in {"SchedulerContractError", "RuntimeError"}:
        return "environment"
    return "unknown"


def _track(case_id: str | None) -> str:
    return case_id.split(".")[1] if case_id and case_id.count(".") >= 2 else ""


def _rows(run_root: Path, repository_root: Path) -> Iterator[dict[str, Any]]:
    for attempt_root in sorted(run_root.glob("qualification_attempt_*")):
        attempt = attempt_root.name.rsplit("_", 1)[-1]
        probes = sorted(
            (attempt_root / "checkpoints" / "canary_probes").glob("*.json")
        )
        legacy = sorted((attempt_root / "checkpoints").glob("canary.json"))
        for path in probes + legacy:
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("status") == "admitted":
                continue
            condition = record.get("failure_condition")
            yield {
                "campaign_id": record.get("campaign_id", ""),
                "attempt": attempt,
                "stage": "canary_probe",
                "case_id": record.get("case_id", ""),
                "track": _track(record.get("case_id")),
                "failure_condition": condition or "",
                "failure_type": record.get("failure_type", ""),
                "provider_call_failures": 0,
                "retried_conditions": "",
                "attribution": _attribution(condition, record.get("failure_type")),
                "cost_usd": record.get("cost_usd", 0.0),
                "source_artifact": str(path.relative_to(repository_root)),
                "source_artifact_sha256": _digest(path),
            }
        for path in sorted((attempt_root / "checkpoints").glob("0*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            status = record.get("status")
            inclusion = record.get("inclusion_status")
            if status == "complete" and inclusion == "included":
                continue
            # An excluded receipt is a measurement outcome, not an
            # operational failure, and is recorded as such.
            stage = "trajectory" if status == "operational_failure" else "measurement"
            terminal, retried = (None, {})
            if stage == "trajectory":
                terminal, retried = _sealed_conditions(
                    attempt_root / "executions" / str(record.get("case_id", ""))
                )
            condition = (
                terminal
                or record.get("failure_condition")
                or (record.get("receipt_status") if stage == "measurement" else None)
            )
            yield {
                "campaign_id": record.get("campaign_id", ""),
                "attempt": attempt,
                "stage": stage,
                "case_id": record.get("case_id", ""),
                "track": _track(record.get("case_id")),
                "failure_condition": condition or "",
                "failure_type": record.get("failure_type", ""),
                "provider_call_failures": sum(retried.values()),
                "retried_conditions": ";".join(
                    f"{name}={count}" for name, count in retried.items()
                ),
                "attribution": (
                    "model"
                    if stage == "measurement"
                    else _attribution(condition, record.get("failure_type"))
                ),
                "cost_usd": record.get("cost_usd") or 0.0,
                "source_artifact": str(path.relative_to(repository_root)),
                "source_artifact_sha256": _digest(path),
            }


def _sealed_conditions(execution_root: Path) -> tuple[str | None, dict[str, int]]:
    """Recover the typed conditions a failed case really hit.

    A checkpoint records `execution_failure` whenever the exception carries no
    `condition` -- true of every SchedulerContractError -- which hides whether
    a case died on a 429, a 404 or a contract error. The sealed event ledger
    has the typed conditions, in order, so the terminal one and the full retry
    histogram are recovered from there rather than guessed from the message.
    """
    counts: dict[str, int] = {}
    terminal: str | None = None
    for events_path in sorted(execution_root.rglob("events.jsonl")):
        root = events_path.parent
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("event_type") not in {
                "provider_call_failed",
                "action_attempt_failed",
            }:
                continue
            digest = event.get("payload_sha256")
            condition = None
            if isinstance(digest, str) and len(digest) >= 4:
                artifact = root / "artifacts" / "sha256" / digest[:2] / digest
                if artifact.is_file():
                    try:
                        condition = json.loads(
                            artifact.read_text(encoding="utf-8")
                        ).get("failure_condition")
                    except (ValueError, OSError):
                        condition = None
            if not isinstance(condition, str):
                continue
            counts[condition] = counts.get(condition, 0) + 1
            terminal = condition
    return terminal, dict(sorted(counts.items()))



def _counts(rows: list[Mapping[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def build(*, run_root: Path, repository_root: Path) -> tuple[bytes, dict[str, Any]]:
    rows = sorted(
        _rows(run_root, repository_root),
        key=lambda row: (row["attempt"], row["stage"], row["case_id"]),
    )
    buffer = ["﻿"[:0] + ",".join(ROW_FIELDS)]
    import io

    handle = io.StringIO()
    writer = csv.DictWriter(handle, fieldnames=list(ROW_FIELDS), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row[field] for field in ROW_FIELDS})
    table = handle.getvalue().encode("utf-8")
    del buffer

    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "register_id": REGISTER_ID,
        "purpose": PURPOSE,
        "failure_count": len(rows),
        "total_recorded_cost_usd": round(
            sum(float(row["cost_usd"] or 0) for row in rows), 6
        ),
        "by_attempt": _counts(rows, "attempt"),
        "by_stage": _counts(rows, "stage"),
        "by_failure_condition": _counts(rows, "failure_condition"),
        "by_attribution": _counts(rows, "attribution"),
        "provider_call_failures_total": sum(
            int(row["provider_call_failures"] or 0) for row in rows
        ),
        "by_track": _counts(rows, "track"),
        # `cost_usd` is what each checkpoint recorded. Attempts sealed before
        # the E-J-03 fix recorded no cost for a failed case, so this total is
        # a floor, not the true spend; the corrected per-attempt figures are
        # in docs/families/econevals/incidents.md, recovered from the sealed
        # evidence rather than from these checkpoints.
        "cost_is_a_floor": True,
        "rows_sha256": hashlib.sha256(table).hexdigest(),
    }
    summary["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {key: value for key, value in summary.items() if key != "artifact_sha256"}
        )
    ).hexdigest()
    return table, summary


def publish(
    *,
    run_root: Path,
    publication_root: Path,
    repository_root: Path,
    regenerate: bool = False,
) -> dict[str, Any]:
    """Write the register bundle.

    Publication is write-once, which is right for evidence and wrong for a
    derived register: this bundle is a projection of sealed runs and must be
    rebuildable as those runs grow. `regenerate` therefore replaces the
    existing bundle deliberately, rather than the caller deleting files by
    hand. The sealed runs it reads are never touched either way.
    """
    table, summary = build(run_root=run_root, repository_root=repository_root)
    payloads = {
        "tables/failures.csv": table,
        "reports/summary.json": canonical_json_bytes(summary) + b"\n",
    }
    for name, payload in payloads.items():
        assert_public_payload(name, payload)
        target = publication_root / name
        if regenerate and target.exists() and target.read_bytes() != payload:
            target.unlink()
        atomic_publish(target, payload)
    return summary


def main(argv: list[str] | None = None) -> int:
    repository_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root",
        type=Path,
        default=repository_root
        / "runs"
        / "econevals"
        / "econevals_glm53_flash_parasail_first_light_v1",
    )
    parser.add_argument(
        "--publication-root",
        type=Path,
        default=repository_root / "evidence" / REGISTER_ID,
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="replace an existing bundle (the register is derived, not evidence)",
    )
    args = parser.parse_args(argv)
    summary = publish(
        run_root=args.run_root,
        publication_root=args.publication_root,
        repository_root=repository_root,
        regenerate=args.regenerate,
    )
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
