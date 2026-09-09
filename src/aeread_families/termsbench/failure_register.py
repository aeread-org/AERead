"""Tier 1 failure register for the TERMS-Bench family.

Builds `evidence/termsbench_failure_register/` from sealed run evidence under
`runs/termsbench/<campaign>/attempt_*`: one row per rejected canary probe,
per cell that failed inside the kernel (a typed exclusion receipt), per
operational abort, per excluded receipt, and -- this family's own typed
model failure -- per completed episode the model ended with a malformed
move (`malformed_action_schema`, spec golden 4). Each row carries the
artifact it came from and that artifact's digest. Regenerated, never
hand-edited; the judgment half of the record lives in
`docs/operations/incident_log.md`.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterator, Mapping

from aeread.shared_runner.run.publication import assert_public_payload, atomic_publish
from aeread.shared_runner.run.resolver import canonical_json_bytes

REGISTER_ID = "termsbench_failure_register"
SCHEMA_VERSION = "aeread.failure_register/0.1"
PURPOSE = (
    "Every typed TERMS-Bench failure in one place, derived only from sealed run "
    "evidence so each row traces to an artifact by digest."
)
ROW_FIELDS = (
    "campaign_id",
    "attempt",
    "stage",
    "case_id",
    "regime",
    "failure_condition",
    "failure_class",
    "failure_type",
    "provider_call_failures",
    "retried_conditions",
    "attribution",
    "cost_usd",
    "source_artifact",
    "source_artifact_sha256",
)
_PROVIDER_CONDITIONS = frozenset(
    {"rate_limit", "provider_5xx", "provider_rejected", "timeout", "transport"}
)
_ENVIRONMENT_CONDITIONS = frozenset({"provider_contract", "harness_contract"})
_MODEL_CONDITIONS = frozenset(
    {"malformed_structured_output", "empty_response", "length", "malformed_action_schema"}
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _attribution(condition: str | None, failure_type: str | None) -> str:
    if condition in _PROVIDER_CONDITIONS:
        return "provider"
    if condition in _ENVIRONMENT_CONDITIONS:
        return "environment"
    if condition in _MODEL_CONDITIONS:
        return "model"
    if failure_type in {"SchedulerContractError", "RuntimeError"}:
        return "environment"
    return "unknown"


def _regime(case_id: str | None) -> str:
    parts = (case_id or "").split(".")
    return parts[2] if len(parts) >= 4 else ""


def _relative(path: Path, repository_root: Path) -> str:
    try:
        return str(path.relative_to(repository_root))
    except ValueError:
        return str(path)


def _sealed_conditions(execution_root: Path) -> tuple[str | None, dict[str, int]]:
    """The typed conditions a failed case really hit, from the sealed ledger.

    A checkpoint records `execution_failure` whenever the exception carries no
    `condition` -- true of every SchedulerContractError -- so the terminal
    condition and the retry histogram are recovered from the event ledger.
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
            if event.get("event_type") not in {"provider_call_failed", "action_attempt_failed"}:
                continue
            condition = None
            ref = event.get("payload_ref")
            digest = event.get("payload_sha256")
            artifact = None
            if isinstance(ref, str) and (root / ref).is_file():
                artifact = root / ref
            elif isinstance(digest, str) and len(digest) >= 4:
                candidate = root / "artifacts" / "sha256" / digest[:2] / digest
                artifact = candidate if candidate.is_file() else None
            if artifact is not None:
                try:
                    condition = json.loads(artifact.read_text(encoding="utf-8")).get(
                        "failure_condition"
                    )
                except (ValueError, OSError):
                    condition = None
            if not isinstance(condition, str):
                continue
            counts[condition] = counts.get(condition, 0) + 1
            terminal = condition
    return terminal, dict(sorted(counts.items()))


def _rows(run_root: Path, repository_root: Path) -> Iterator[dict[str, Any]]:
    for attempt_root in sorted(run_root.glob("*/attempt_*")):
        attempt = f"{attempt_root.parent.name}/{attempt_root.name}"
        for path in sorted((attempt_root / "checkpoints" / "canary_probes").glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("status") == "admitted":
                continue
            condition = record.get("failure_condition")
            yield {
                "campaign_id": record.get("campaign_id", ""),
                "attempt": attempt,
                "stage": "canary_probe",
                "case_id": record.get("case_id", ""),
                "regime": _regime(record.get("case_id")),
                "failure_condition": condition or "",
                "failure_class": "",
                "failure_type": record.get("failure_type", ""),
                "provider_call_failures": 0,
                "retried_conditions": "",
                "attribution": _attribution(condition, record.get("failure_type")),
                "cost_usd": record.get("cost_usd", 0.0),
                "source_artifact": _relative(path, repository_root),
                "source_artifact_sha256": _digest(path),
            }
        for path in sorted((attempt_root / "checkpoints").glob("[0-9]*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            status = record.get("status")
            inclusion = record.get("inclusion_status")
            case_id = str(record.get("case_id", ""))
            execution_root = attempt_root / "executions" / case_id
            if status == "complete" and inclusion == "included":
                if not record.get("malformed_action_schema"):
                    continue
                # The model ended the episode with a move the family could not
                # parse: a measured critical violation, and a typed failure of
                # the model worth a row of its own.
                stage, condition, failure_class = "measurement", "malformed_action_schema", ""
                retried: dict[str, int] = {}
            elif status == "complete":
                stage, condition = "measurement", str(record.get("receipt_status") or "")
                failure_class, retried = "", {}
            elif status == "failed":
                # A typed exclusion receipt sealed by the campaign: the condition
                # is the receipt's, the histogram the ledger's.
                stage = "trajectory"
                terminal, retried = _sealed_conditions(execution_root)
                condition = str(record.get("failure_condition") or terminal or "")
                failure_class = str(record.get("failure_class") or "")
            else:
                stage = "trajectory"
                terminal, retried = _sealed_conditions(execution_root)
                condition = str(terminal or record.get("failure_condition") or "")
                failure_class = ""
            yield {
                "campaign_id": record.get("campaign_id", ""),
                "attempt": attempt,
                "stage": stage,
                "case_id": case_id,
                "regime": _regime(case_id),
                "failure_condition": condition,
                "failure_class": failure_class,
                "failure_type": record.get("failure_type", "") or "",
                "provider_call_failures": sum(retried.values()),
                "retried_conditions": ";".join(f"{k}={v}" for k, v in retried.items()),
                "attribution": (
                    "model" if stage == "measurement" else _attribution(condition, record.get("failure_type"))
                ),
                "cost_usd": record.get("cost_usd") or 0.0,
                "source_artifact": _relative(path, repository_root),
                "source_artifact_sha256": _digest(path),
            }


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
    handle = io.StringIO()
    writer = csv.DictWriter(handle, fieldnames=list(ROW_FIELDS), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row[field] for field in ROW_FIELDS})
    table = handle.getvalue().encode("utf-8")
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "register_id": REGISTER_ID,
        "purpose": PURPOSE,
        "failure_count": len(rows),
        "total_recorded_cost_usd": round(sum(float(row["cost_usd"] or 0) for row in rows), 6),
        "by_campaign": _counts(rows, "campaign_id"),
        "by_attempt": _counts(rows, "attempt"),
        "by_stage": _counts(rows, "stage"),
        "by_failure_condition": _counts(rows, "failure_condition"),
        "by_attribution": _counts(rows, "attribution"),
        "by_regime": _counts(rows, "regime"),
        "provider_call_failures_total": sum(int(row["provider_call_failures"] or 0) for row in rows),
        # Every checkpoint of this family records sealed spend for a failed
        # case (the campaign was written after E-J-03), so the total is the
        # recorded spend, not a floor.
        "cost_is_a_floor": False,
        "rows_sha256": hashlib.sha256(table).hexdigest(),
    }
    summary["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes({k: v for k, v in summary.items() if k != "artifact_sha256"})
    ).hexdigest()
    return table, summary


def publish(
    *,
    run_root: Path,
    publication_root: Path,
    repository_root: Path,
    regenerate: bool = False,
) -> dict[str, Any]:
    """Write the register bundle; `regenerate` replaces a stale bundle
    deliberately, because the register is a projection of sealed runs and
    must be rebuildable as they grow. The runs are never touched."""
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
    parser.add_argument("--run-root", type=Path, default=repository_root / "runs" / "termsbench")
    parser.add_argument(
        "--publication-root", type=Path, default=repository_root / "evidence" / REGISTER_ID
    )
    parser.add_argument("--regenerate", action="store_true", help="replace an existing bundle")
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
