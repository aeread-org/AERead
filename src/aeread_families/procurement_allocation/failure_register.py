"""Tier 1 failure register: every typed failure, derived only from published evidence.

The [incident log](../../../docs/operations/incident_log.md) is the Tier 2
judgment record: design, operational, tooling, and judgment failures, written by
a person. This module is Tier 1, and it is mechanical. It reads only tracked
evidence bundles, extracts every row that did not complete and every rejected
admission canary, and emits a digest-bound register.

Being derived rather than authored is the point. A hand-written operational
audit can omit a failure by accident or by preference; a register regenerated
from the published bundles cannot, and any drift between the two is itself a
finding. The register is therefore regenerable and its digest is checkable, in
the same way the regret decomposition is.

What it deliberately does not contain: tooling and judgment failures, which
leave no trace in evidence and belong in the Tier 2 log.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes

from .model_campaign import _validate_publication_root

REGISTER_ID = "procurement_allocation_failure_register"
SCHEMA_VERSION = "aeread.procurement_allocation_failure_register/0.1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FAMILY_PREFIX = "procurement_allocation"

#: Row fields that describe a failure. Anything else stays in the source bundle.
_FAILURE_FIELDS = (
    "status",
    "failure_type",
    "failure_condition",
    "failure_status_code",
    "termination_reason",
    "runner_retry_count",
    "retry_condition_counts",
    "cost_usd",
)


def _bundles(evidence_root: Path) -> list[Path]:
    return sorted(
        path
        for path in evidence_root.iterdir()
        if path.is_dir() and path.name.startswith(FAMILY_PREFIX)
    )


def _reports(bundle: Path) -> list[Path]:
    return sorted((bundle / "reports").glob("*.json")) if (bundle / "reports").is_dir() else []


def build_register(*, repository_root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    """Scan every published procurement bundle for typed failures."""
    evidence_root = Path(repository_root) / "evidence"
    failures: list[dict[str, Any]] = []
    canaries: list[dict[str, Any]] = []
    sources: dict[str, Any] = {}
    scanned_rows = 0

    for bundle in _bundles(evidence_root):
        for report in _reports(bundle):
            raw = report.read_bytes()
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(value, Mapping):
                continue
            relative = str(report.relative_to(repository_root))
            sources[relative] = hashlib.sha256(raw).hexdigest()

            # A rejected admission canary is a failure that produced no row.
            if value.get("schema_version", "").startswith("aeread.provider_admission_canary"):
                if value.get("status") != "admitted":
                    canaries.append(
                        {
                            "source": relative,
                            "campaign_id": value.get("campaign_id"),
                            "condition": value.get("condition"),
                            "status": value.get("status"),
                            "failure_condition": value.get("failure_condition"),
                            "failure_type": value.get("failure_type"),
                            "failure_status_code": value.get("failure_status_code"),
                            "cost_usd": value.get("cost_usd", 0.0),
                        }
                    )
                continue

            rows = value.get("rows")
            if not isinstance(rows, list):
                continue
            for row in rows:
                # Only trajectory rows carry an execution `status`. Derived
                # reports such as the regret decomposition also publish a `rows`
                # key, and reading those as failures over-reports every analysed
                # row; requiring the discriminator keeps the register to rows
                # that actually executed.
                if not isinstance(row, Mapping) or "status" not in row:
                    continue
                scanned_rows += 1
                completed = row.get("status") == "completed"
                violations = list(row.get("violations") or [])
                # Two distinct kinds of failure share a register: a row that
                # never produced a measurement, and a row that measured a
                # rejected award. Keeping both makes "what went wrong" answerable
                # without deciding in advance which sense was meant.
                if completed and not violations:
                    continue
                entry = {
                    "source": relative,
                    "campaign_id": value.get("campaign_id"),
                    "case_id": row.get("case_id"),
                    "inference_seed": row.get("inference_seed"),
                    "kind": "operational" if not completed else "measured_violation",
                    "violations": violations,
                    "result_sha256": row.get("result_sha256"),
                }
                entry.update(
                    {field: row.get(field) for field in _FAILURE_FIELDS if field in row}
                )
                failures.append(entry)

    operational = [f for f in failures if f["kind"] == "operational"]
    measured = [f for f in failures if f["kind"] == "measured_violation"]
    register = {
        "schema_version": SCHEMA_VERSION,
        "register_id": REGISTER_ID,
        "derivation": (
            "mechanically derived from tracked evidence bundles under evidence/; "
            "contains no hand-entered failure. Tooling and judgment failures "
            "leave no trace in evidence and live in docs/operations/incident_log.md."
        ),
        "sources": dict(sorted(sources.items())),
        "summary": {
            "bundles_scanned": len({f["source"].split("/")[1] for f in failures})
            if failures
            else 0,
            "reports_scanned": len(sources),
            "rows_scanned": scanned_rows,
            "operational_failures": len(operational),
            "measured_violations": len(measured),
            "rejected_canaries": len(canaries),
            # A row can fail with no typed condition recorded; that is itself
            # worth counting, so it is kept under an explicit label rather than
            # dropped or left as a null key.
            "operational_failure_conditions": dict(
                sorted(
                    Counter(
                        str(f.get("failure_condition") or "untyped")
                        for f in operational
                    ).items()
                )
            ),
            "violation_kinds": dict(
                sorted(
                    Counter(
                        v.rsplit(".", 1)[-1] for f in measured for v in f["violations"]
                    ).items()
                )
            ),
            "operational_cost_usd": round(
                sum(float(f.get("cost_usd") or 0.0) for f in operational), 8
            ),
        },
        "rejected_canaries": canaries,
        "failures": failures,
    }
    register["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {k: v for k, v in register.items() if k != "artifact_sha256"}
        )
    ).hexdigest()
    return register


def publish_register(
    register: Mapping[str, Any], *, publication_root: Path
) -> dict[str, Any]:
    publication_root = Path(publication_root)
    _validate_publication_root(publication_root)
    reports = publication_root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(dict(register))
    (reports / "failure_register.json").write_bytes(payload)
    manifest = {
        "schema_version": "aeread.publication_manifest/0.1",
        "publication_id": REGISTER_ID,
        "campaign_id": REGISTER_ID,
        "artifacts": {
            "reports/failure_register.json": hashlib.sha256(payload).hexdigest()
        },
        "source_bindings": {
            "register_artifact_sha256": register["artifact_sha256"],
            "reports": register["sources"],
        },
        "privacy_boundary": {
            "included": "typed failure conditions, violations, and source digests",
            "excluded": "anything not already present in the tracked bundles",
        },
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {k: v for k, v in manifest.items() if k != "manifest_sha256"}
        )
    ).hexdigest()
    (publication_root / "publication_manifest.json").write_bytes(
        canonical_json_bytes(manifest)
    )
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument("--publish", action="store_true")
    arguments = parser.parse_args(argv)
    register = build_register(repository_root=arguments.repository_root)
    if arguments.publish:
        if arguments.publication_root is None:
            parser.error("--publish requires --publication-root")
        value: Mapping[str, Any] = publish_register(
            register, publication_root=arguments.publication_root
        )
    else:
        value = {k: v for k, v in register.items() if k not in {"failures", "sources"}}
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["REGISTER_ID", "build_register", "publish_register"]
