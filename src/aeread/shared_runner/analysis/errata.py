"""Errata: later knowledge about already-published evidence.

Sealed receipts, self-hashed campaign modules, and append-only gate history
mean published evidence is never rewritten. That is the point, and it is also
why a defect discovered *after* publication -- a kernel bug that under-counted
cost, a route that turned out not to be what was pinned, a claim later
withdrawn -- needs somewhere to live that is not the bundle itself.

An erratum is a sealed, append-only record under ``evidence/errata/`` that
names the finding once and selects the affected evidence by identity:
campaign ids, ``run_plan_sha256`` values, receipt digests, implementation-pin
digests, or family ids. Every affected bundle then inherits it by selector
rather than by edit: the derived register under ``evidence/errata_register/``
lists which published bundles each erratum touches, ``ERRATA.md`` sidecars
next to those bundles surface it to a reader, and the research ledger carries
``errata_ids`` per attempt.

Errata are never edited or deleted. A wrong or outdated erratum is superseded
by a new one that names it.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import io
import json
import os
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..run.contract import read_sealed, sealed, sha256_bytes
from ..run.publication import atomic_publish
from ..run.resolver import canonical_json_bytes

ERRATUM_SCHEMA_VERSION = "aeread.erratum/0.1"
REGISTER_SCHEMA_VERSION = "aeread.errata_register/0.1"
DEFAULT_ERRATA_DIRECTORY = "errata"
DEFAULT_REGISTER_DIRECTORY = "errata_register"
SIDECAR_NAME = "ERRATA.md"

CATEGORIES = frozenset({"kernel", "family", "provider", "judgment"})
EFFECTS = frozenset(
    {
        "cost_lower_bound",
        "score_invalid",
        "route_unverified",
        "evidence_incomplete",
        "claim_withdrawn",
        "other",
    }
)
DISPOSITIONS = frozenset({"open", "fixed", "superseded"})
_ERRATA_ID = re.compile(r"^ERR-\d{4}-\d{2}-\d{2}-\d{3}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ErrataContractError(ValueError):
    """An erratum or register violates the errata contract."""


def _strings(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ErrataContractError(f"{label} must be a list of non-empty strings")
    return tuple(value)


def _digests(value: Any, label: str) -> tuple[str, ...]:
    items = _strings(value, label)
    bad = [item for item in items if not _SHA256.match(item)]
    if bad:
        raise ErrataContractError(f"{label} must contain sha256 hex digests")
    return items


@dataclass(frozen=True, slots=True)
class PinSelector:
    component_id: str
    sha256s: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Any) -> "PinSelector":
        if not isinstance(value, Mapping) or set(value) != {"component_id", "sha256s"}:
            raise ErrataContractError(
                "implementation_pins entries must have component_id and sha256s"
            )
        component_id = value["component_id"]
        if not isinstance(component_id, str) or not component_id:
            raise ErrataContractError("implementation_pins component_id must be non-empty")
        sha256s = _digests(value["sha256s"], "implementation_pins.sha256s")
        if not sha256s:
            raise ErrataContractError("implementation_pins.sha256s must not be empty")
        return cls(component_id=component_id, sha256s=sha256s)

    def to_dict(self) -> dict[str, Any]:
        return {"component_id": self.component_id, "sha256s": list(self.sha256s)}


@dataclass(frozen=True, slots=True)
class ErratumSelectors:
    campaign_ids: tuple[str, ...]
    run_plan_sha256s: tuple[str, ...]
    receipt_sha256s: tuple[str, ...]
    implementation_pins: tuple[PinSelector, ...]
    family_ids: tuple[str, ...]

    _FIELDS = (
        "campaign_ids",
        "run_plan_sha256s",
        "receipt_sha256s",
        "implementation_pins",
        "family_ids",
    )

    @classmethod
    def from_dict(cls, value: Any) -> "ErratumSelectors":
        if not isinstance(value, Mapping) or set(value) != set(cls._FIELDS):
            raise ErrataContractError(
                f"selectors must have exactly the fields {sorted(cls._FIELDS)}"
            )
        pins = value["implementation_pins"]
        if not isinstance(pins, (list, tuple)):
            raise ErrataContractError("selectors.implementation_pins must be a list")
        selectors = cls(
            campaign_ids=_strings(value["campaign_ids"], "selectors.campaign_ids"),
            run_plan_sha256s=_digests(
                value["run_plan_sha256s"], "selectors.run_plan_sha256s"
            ),
            receipt_sha256s=_digests(value["receipt_sha256s"], "selectors.receipt_sha256s"),
            implementation_pins=tuple(PinSelector.from_dict(item) for item in pins),
            family_ids=_strings(value["family_ids"], "selectors.family_ids"),
        )
        if selectors.is_empty():
            raise ErrataContractError("an erratum must declare at least one selector")
        return selectors

    def is_empty(self) -> bool:
        return not any(
            (
                self.campaign_ids,
                self.run_plan_sha256s,
                self.receipt_sha256s,
                self.implementation_pins,
                self.family_ids,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_ids": list(self.campaign_ids),
            "run_plan_sha256s": list(self.run_plan_sha256s),
            "receipt_sha256s": list(self.receipt_sha256s),
            "implementation_pins": [pin.to_dict() for pin in self.implementation_pins],
            "family_ids": list(self.family_ids),
        }


@dataclass(frozen=True, slots=True)
class Erratum:
    errata_id: str
    opened_at: str
    category: str
    effect: str
    title: str
    description: str
    selectors: ErratumSelectors
    fix_ref: str | None
    disposition: str
    superseded_by: str | None
    evidence_refs: tuple[str, ...]

    _FIELDS = (
        "errata_id",
        "opened_at",
        "category",
        "effect",
        "title",
        "description",
        "selectors",
        "fix_ref",
        "disposition",
        "superseded_by",
        "evidence_refs",
    )

    @classmethod
    def from_dict(cls, value: Any) -> "Erratum":
        if not isinstance(value, Mapping):
            raise ErrataContractError("erratum must be an object")
        payload = {
            key: item
            for key, item in value.items()
            if key not in {"schema_version", "artifact_sha256"}
        }
        if set(payload) != set(cls._FIELDS):
            raise ErrataContractError(
                f"erratum must have exactly the fields {sorted(cls._FIELDS)}"
            )
        errata_id = payload["errata_id"]
        if not isinstance(errata_id, str) or not _ERRATA_ID.match(errata_id):
            raise ErrataContractError("errata_id must look like ERR-YYYY-MM-DD-NNN")
        opened_at = payload["opened_at"]
        if not isinstance(opened_at, str) or not _DATE.match(opened_at):
            raise ErrataContractError("opened_at must be an ISO date (YYYY-MM-DD)")
        category = payload["category"]
        if category not in CATEGORIES:
            raise ErrataContractError(f"category must be one of {sorted(CATEGORIES)}")
        effect = payload["effect"]
        if effect not in EFFECTS:
            raise ErrataContractError(f"effect must be one of {sorted(EFFECTS)}")
        for name in ("title", "description"):
            if not isinstance(payload[name], str) or not payload[name].strip():
                raise ErrataContractError(f"{name} must be a non-empty string")
        disposition = payload["disposition"]
        if disposition not in DISPOSITIONS:
            raise ErrataContractError(
                f"disposition must be one of {sorted(DISPOSITIONS)}"
            )
        superseded_by = payload["superseded_by"]
        if disposition == "superseded":
            if not isinstance(superseded_by, str) or not _ERRATA_ID.match(superseded_by):
                raise ErrataContractError(
                    "a superseded erratum must name its successor in superseded_by"
                )
        elif superseded_by is not None:
            raise ErrataContractError("superseded_by is only valid when superseded")
        fix_ref = payload["fix_ref"]
        if fix_ref is not None and (not isinstance(fix_ref, str) or not fix_ref):
            raise ErrataContractError("fix_ref must be null or a non-empty string")
        return cls(
            errata_id=errata_id,
            opened_at=opened_at,
            category=category,
            effect=effect,
            title=payload["title"].strip(),
            description=payload["description"].strip(),
            selectors=ErratumSelectors.from_dict(payload["selectors"]),
            fix_ref=fix_ref,
            disposition=disposition,
            superseded_by=superseded_by,
            evidence_refs=_strings(payload["evidence_refs"], "evidence_refs"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "errata_id": self.errata_id,
            "opened_at": self.opened_at,
            "category": self.category,
            "effect": self.effect,
            "title": self.title,
            "description": self.description,
            "selectors": self.selectors.to_dict(),
            "fix_ref": self.fix_ref,
            "disposition": self.disposition,
            "superseded_by": self.superseded_by,
            "evidence_refs": list(self.evidence_refs),
        }

    def matches(
        self,
        *,
        campaign_id: str | None = None,
        run_plan_sha256: str | None = None,
        receipt_sha256: str | None = None,
        family_id: str | None = None,
        implementation_pins: Iterable[Any] | None = None,
    ) -> tuple[str, ...]:
        """Which selectors this subject hits, in a fixed order; empty means none."""

        hits: list[str] = []
        selectors = self.selectors
        if campaign_id is not None and campaign_id in selectors.campaign_ids:
            hits.append("campaign_id")
        if run_plan_sha256 is not None and run_plan_sha256 in selectors.run_plan_sha256s:
            hits.append("run_plan_sha256")
        if receipt_sha256 is not None and receipt_sha256 in selectors.receipt_sha256s:
            hits.append("receipt_sha256")
        if family_id is not None and family_id in selectors.family_ids:
            hits.append("family_id")
        if implementation_pins is not None and selectors.implementation_pins:
            wanted = {
                (pin.component_id, sha): True
                for pin in selectors.implementation_pins
                for sha in pin.sha256s
            }
            for candidate in implementation_pins:
                component = _pin_field(candidate, "component_id")
                digest = _pin_field(candidate, "sha256")
                if (component, digest) in wanted:
                    hits.append("implementation_pin")
                    break
        return tuple(hits)


def _pin_field(pin: Any, name: str) -> Any:
    if isinstance(pin, Mapping):
        return pin.get(name)
    return getattr(pin, name, None)


def errata_for(
    errata: Sequence[Erratum],
    *,
    campaign_id: str | None = None,
    run_plan_sha256: str | None = None,
    receipt_sha256: str | None = None,
    family_id: str | None = None,
    implementation_pins: Iterable[Any] | None = None,
    include_superseded: bool = False,
) -> tuple[str, ...]:
    """Sorted ids of the errata whose selectors hit the given subject."""

    pins = tuple(implementation_pins) if implementation_pins is not None else None
    ids = [
        erratum.errata_id
        for erratum in errata
        if (include_superseded or erratum.disposition != "superseded")
        and erratum.matches(
            campaign_id=campaign_id,
            run_plan_sha256=run_plan_sha256,
            receipt_sha256=receipt_sha256,
            family_id=family_id,
            implementation_pins=pins,
        )
    ]
    return tuple(sorted(ids))


# --- append-only storage ---


def erratum_payload(erratum: Erratum) -> dict[str, Any]:
    return sealed({"schema_version": ERRATUM_SCHEMA_VERSION, **erratum.to_dict()})


def write_erratum(root: Path | str, erratum: Erratum) -> Path:
    """Write one sealed erratum; identical bytes are a no-op, different bytes refuse."""

    path = Path(root) / f"{erratum.errata_id}.json"
    atomic_publish(path, canonical_json_bytes(erratum_payload(erratum)) + b"\n")
    return path


def load_errata(root: Path | str) -> tuple[Erratum, ...]:
    """Load every sealed erratum under ``root``; a missing root is simply empty."""

    directory = Path(root)
    if not directory.is_dir():
        return ()
    errata: list[Erratum] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.json")):
        payload = read_sealed(path)
        if payload.get("schema_version") != ERRATUM_SCHEMA_VERSION:
            raise ErrataContractError(f"{path.name}: unsupported erratum schema")
        erratum = Erratum.from_dict(payload)
        if path.stem != erratum.errata_id:
            raise ErrataContractError(
                f"{path.name}: file name must equal errata_id {erratum.errata_id!r}"
            )
        if erratum.errata_id in seen:
            raise ErrataContractError(f"duplicate errata_id {erratum.errata_id!r}")
        seen.add(erratum.errata_id)
        errata.append(erratum)
    return tuple(errata)


def plans_sealed_under(
    runs_root: Path | str, component_id: str, sha256s: Iterable[str]
) -> tuple[str, ...]:
    """Resolve a pin selector to ``run_plan_sha256`` values from local receipts.

    Published projections omit implementation pins, so a kernel-level finding
    is resolved once, against the local run directories, into plan digests
    that published evidence can be matched on.
    """

    wanted = set(sha256s)
    plans: set[str] = set()
    for receipt_path in Path(runs_root).rglob("evaluation_receipt.json"):
        try:
            receipt = json.loads(receipt_path.read_bytes())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(receipt, Mapping):
            continue
        pins = receipt.get("plan_implementation_pins")
        plan = receipt.get("run_plan_sha256")
        if not isinstance(pins, list) or not isinstance(plan, str):
            continue
        if any(
            isinstance(pin, Mapping)
            and pin.get("component_id") == component_id
            and pin.get("sha256") in wanted
            for pin in pins
        ):
            plans.add(plan)
    return tuple(sorted(plans))


# --- derived register over published evidence ---


@dataclass(frozen=True, slots=True)
class PublishedBundle:
    campaign_id: str
    path: str
    run_plan_sha256s: tuple[str, ...]
    receipt_sha256s: tuple[str, ...]


def scan_bundles(evidence_root: Path | str) -> tuple[PublishedBundle, ...]:
    """Every published bundle: a directory holding ``publication_manifest.json``."""

    root = Path(evidence_root)
    bundles: list[PublishedBundle] = []
    for manifest_path in sorted(root.glob("*/publication_manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_bytes())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, Mapping):
            continue
        campaign_id = manifest.get("campaign_id")
        if not isinstance(campaign_id, str) or not campaign_id:
            continue
        plans: set[str] = set()
        receipts: set[str] = set()
        plan_sha256 = manifest.get("plan_sha256")
        if isinstance(plan_sha256, str) and _SHA256.match(plan_sha256):
            plans.add(plan_sha256)
        projections = manifest_path.parent / "receipts" / "projections.jsonl"
        if projections.is_file():
            for line in projections.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, Mapping):
                    continue
                plan = row.get("run_plan_sha256")
                if isinstance(plan, str) and _SHA256.match(plan):
                    plans.add(plan)
                receipt = row.get("source_receipt_sha256")
                if isinstance(receipt, str) and _SHA256.match(receipt):
                    receipts.add(receipt)
        bundles.append(
            PublishedBundle(
                campaign_id=campaign_id,
                path=manifest_path.parent.name,
                run_plan_sha256s=tuple(sorted(plans)),
                receipt_sha256s=tuple(sorted(receipts)),
            )
        )
    return tuple(bundles)


@dataclass(frozen=True, slots=True)
class AffectedBundleRow:
    errata_id: str
    campaign_id: str
    bundle_path: str
    matched_by: str
    category: str
    effect: str
    disposition: str
    fix_ref: str
    superseded_by: str


def _bundle_hits(erratum: Erratum, bundle: PublishedBundle) -> tuple[str, ...]:
    hits: list[str] = []
    hits.extend(erratum.matches(campaign_id=bundle.campaign_id))
    if any(plan in erratum.selectors.run_plan_sha256s for plan in bundle.run_plan_sha256s):
        hits.append("run_plan_sha256")
    if any(
        receipt in erratum.selectors.receipt_sha256s for receipt in bundle.receipt_sha256s
    ):
        hits.append("receipt_sha256")
    return tuple(hits)


def affected_rows(
    bundles: Sequence[PublishedBundle], errata: Sequence[Erratum]
) -> tuple[AffectedBundleRow, ...]:
    rows: list[AffectedBundleRow] = []
    for erratum in sorted(errata, key=lambda item: item.errata_id):
        for bundle in bundles:
            hits = _bundle_hits(erratum, bundle)
            if not hits:
                continue
            rows.append(
                AffectedBundleRow(
                    errata_id=erratum.errata_id,
                    campaign_id=bundle.campaign_id,
                    bundle_path=bundle.path,
                    matched_by=",".join(hits),
                    category=erratum.category,
                    effect=erratum.effect,
                    disposition=erratum.disposition,
                    fix_ref=erratum.fix_ref or "",
                    superseded_by=erratum.superseded_by or "",
                )
            )
    rows.sort(key=lambda row: (row.errata_id, row.campaign_id, row.bundle_path))
    return tuple(rows)


def _csv_bytes(rows: Sequence[AffectedBundleRow]) -> bytes:
    fields = [field.name for field in dataclasses.fields(AffectedBundleRow)]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({name: getattr(row, name) for name in fields})
    return stream.getvalue().encode("utf-8")


def build_register(
    evidence_root: Path | str, errata: Sequence[Erratum]
) -> tuple[bytes, dict[str, Any]]:
    """Derive the affected-bundle table and its sealed summary; reproducible bytes."""

    bundles = scan_bundles(evidence_root)
    rows = affected_rows(bundles, errata)
    table = _csv_bytes(rows)
    affected = sorted({row.bundle_path for row in rows})
    summary = sealed(
        {
            "schema_version": REGISTER_SCHEMA_VERSION,
            "purpose": (
                "which published bundles each erratum touches; derived from "
                "published evidence and the errata records, never written by hand"
            ),
            "source_truth": [
                "evidence/errata",
                "publication_manifest.json",
                "receipts/projections.jsonl",
            ],
            "errata_count": len(errata),
            "open_errata_count": sum(1 for item in errata if item.disposition == "open"),
            "bundle_count": len(bundles),
            "affected_bundle_count": len(affected),
            "affected_bundles": affected,
            "by_errata": {
                item.errata_id: sorted(
                    {row.bundle_path for row in rows if row.errata_id == item.errata_id}
                )
                for item in sorted(errata, key=lambda item: item.errata_id)
            },
            "by_effect": dict(
                sorted(Counter(row.effect for row in rows).items())
            ),
            "by_disposition": dict(
                sorted(Counter(row.disposition for row in rows).items())
            ),
            "row_count": len(rows),
            "rows_sha256": sha256_bytes(table),
        }
    )
    return table, summary


def sidecar_markdown(campaign_id: str, rows: Sequence[AffectedBundleRow], errata_by_id: Mapping[str, Erratum]) -> str:
    lines = [
        f"# Errata for `{campaign_id}`",
        "",
        "Findings recorded after this bundle was published. The sealed bundle is",
        "unchanged; each row points at the erratum record under `evidence/errata/`.",
        "",
        "| erratum | effect | disposition | matched by | fix |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row.errata_id}` | `{row.effect}` | {row.disposition}"
            f"{' → ' + row.superseded_by if row.superseded_by else ''} | "
            f"{row.matched_by} | {row.fix_ref or '—'} |"
        )
    lines.append("")
    for row in rows:
        erratum = errata_by_id[row.errata_id]
        lines.extend(
            [
                f"## {row.errata_id} — {erratum.title}",
                "",
                erratum.description,
                "",
            ]
        )
        if erratum.evidence_refs:
            lines.append("References: " + ", ".join(erratum.evidence_refs))
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _write_derived(path: Path, payload: bytes) -> bool:
    """Replace a derived artifact only when its bytes change; returns whether it did."""

    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise ErrataContractError(f"derived artifact must be a regular file: {path}")
        if path.read_bytes() == payload:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return True


def publish_register(
    evidence_root: Path | str,
    *,
    errata_root: Path | str | None = None,
    register_root: Path | str | None = None,
    write_notes: bool = False,
) -> dict[str, Any]:
    """Regenerate the derived register (and optionally the bundle sidecars)."""

    evidence = Path(evidence_root)
    errata_dir = Path(errata_root) if errata_root is not None else evidence / DEFAULT_ERRATA_DIRECTORY
    register_dir = (
        Path(register_root) if register_root is not None else evidence / DEFAULT_REGISTER_DIRECTORY
    )
    errata = load_errata(errata_dir)
    table, summary = build_register(evidence, errata)
    _write_derived(register_dir / "tables" / "affected.csv", table)
    _write_derived(
        register_dir / "reports" / "summary.json", canonical_json_bytes(summary) + b"\n"
    )
    if write_notes:
        rows = affected_rows(scan_bundles(evidence), errata)
        errata_by_id = {item.errata_id: item for item in errata}
        by_bundle: dict[str, list[AffectedBundleRow]] = {}
        for row in rows:
            by_bundle.setdefault(row.bundle_path, []).append(row)
        for bundle_path, bundle_rows in by_bundle.items():
            campaign_id = bundle_rows[0].campaign_id
            _write_derived(
                evidence / bundle_path / SIDECAR_NAME,
                sidecar_markdown(campaign_id, bundle_rows, errata_by_id).encode("utf-8"),
            )
    return dict(summary)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aeread errata",
        description="Regenerate the errata register over published evidence.",
    )
    parser.add_argument("--evidence-root", default="evidence")
    parser.add_argument("--errata-root", default=None)
    parser.add_argument("--register-root", default=None)
    parser.add_argument(
        "--write-notes",
        action="store_true",
        help=f"write {SIDECAR_NAME} next to each affected bundle",
    )
    args = parser.parse_args(argv)
    summary = publish_register(
        args.evidence_root,
        errata_root=args.errata_root,
        register_root=args.register_root,
        write_notes=args.write_notes,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


__all__ = [
    "AffectedBundleRow",
    "CATEGORIES",
    "DISPOSITIONS",
    "EFFECTS",
    "ERRATUM_SCHEMA_VERSION",
    "Erratum",
    "ErratumSelectors",
    "ErrataContractError",
    "PinSelector",
    "PublishedBundle",
    "REGISTER_SCHEMA_VERSION",
    "affected_rows",
    "build_register",
    "errata_for",
    "erratum_payload",
    "load_errata",
    "main",
    "plans_sealed_under",
    "publish_register",
    "scan_bundles",
    "sidecar_markdown",
    "write_erratum",
]


if __name__ == "__main__":
    raise SystemExit(main())
