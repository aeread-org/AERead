"""Versioned task rows for the public AERead rLLM integration fixture.

The checked-in manifest is the only source of default case membership. Its
``test`` registry split is an explicit alias of the public ``dev`` rows for
rLLM's current evaluation CLI; it is not a private benchmark test set.

Register all three rLLM-facing splits locally with::

    python -m aeread.integrations.rllm_dataset --register

Inspect the complete provider-free contract with::

    python -m aeread.integrations.rllm_dataset --preflight
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from aeread.integrations.failure_taxonomy import IntegrationConfigurationError


MANIFEST_FILENAME = "rllm_caseset_integration_v1.json"
MANIFEST_PATH = Path(__file__).with_name(MANIFEST_FILENAME)
MANIFEST_SCHEMA_VERSION = 1
REGISTERED_SPLITS = ("train", "dev", "test")
_HEX_DIGITS = frozenset("0123456789abcdef")
_PREFLIGHT_DEPENDENCIES = (
    "numpy",
    "openai",
    "pandas",
    "polars",
    "pyarrow",
    "rllm",
    "rllm_model_gateway",
    "scipy",
)


class CaseIntegrityError(IntegrationConfigurationError):
    """A packaged case resource is missing or differs from its manifest."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and set(value) <= _HEX_DIGITS
    )


def _caseset_hash(manifest: Mapping[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("caseset_sha256", None)
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _require_fields(
    value: Mapping[str, Any], fields: set[str], context: str
) -> None:
    missing = sorted(fields - set(value))
    if missing:
        raise IntegrationConfigurationError(
            f"{context} is missing required fields {missing}"
        )


def _validate_manifest(manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise IntegrationConfigurationError(
            "AERead rLLM case-set manifest must be a JSON object"
        )
    _require_fields(
        manifest,
        {
            "manifest_schema_version",
            "caseset_version",
            "protocol_version",
            "generator_version",
            "scorer_version",
            "semantic_role",
            "caseset_sha256",
            "prompt_spec",
            "panel_spec",
            "cases",
            "splits",
        },
        "AERead rLLM case-set manifest",
    )
    if manifest["manifest_schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise IntegrationConfigurationError(
            "unsupported AERead rLLM manifest schema version "
            f"{manifest['manifest_schema_version']!r}"
        )
    for name in (
        "caseset_version",
        "protocol_version",
        "generator_version",
        "scorer_version",
        "semantic_role",
    ):
        if not isinstance(manifest[name], str) or not manifest[name]:
            raise IntegrationConfigurationError(
                f"manifest field {name!r} must be a non-empty string"
            )

    expected_caseset_hash = manifest["caseset_sha256"]
    actual_caseset_hash = _caseset_hash(manifest)
    if not _valid_sha256(expected_caseset_hash):
        raise IntegrationConfigurationError(
            "manifest caseset_sha256 must be a lowercase SHA-256 digest"
        )
    if actual_caseset_hash != expected_caseset_hash:
        raise IntegrationConfigurationError(
            "AERead rLLM case-set manifest hash mismatch "
            f"(expected {expected_caseset_hash}, actual {actual_caseset_hash})"
        )

    for spec_name in ("prompt_spec", "panel_spec"):
        spec = manifest[spec_name]
        if not isinstance(spec, dict):
            raise IntegrationConfigurationError(
                f"manifest {spec_name} must be an object"
            )
        _require_fields(spec, {"source", "sha256"}, spec_name)
        if not _valid_sha256(spec["sha256"]):
            raise IntegrationConfigurationError(
                f"manifest {spec_name}.sha256 must be a lowercase SHA-256 digest"
            )

    cases = manifest["cases"]
    if not isinstance(cases, list) or not cases:
        raise IntegrationConfigurationError(
            "AERead rLLM case-set manifest must name at least one case"
        )
    case_ids: list[str] = []
    row_keys: list[str] = []
    resources: list[str] = []
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise IntegrationConfigurationError(
                f"manifest case {index} must be an object"
            )
        _require_fields(
            case,
            {"row_key", "case_id", "case_resource", "case_sha256"},
            f"manifest case {index}",
        )
        for name in ("row_key", "case_id", "case_resource"):
            if not isinstance(case[name], str) or not case[name]:
                raise IntegrationConfigurationError(
                    f"manifest case {index} field {name!r} must be non-empty"
                )
        _validated_resource_name(case["case_resource"])
        if not _valid_sha256(case["case_sha256"]):
            raise IntegrationConfigurationError(
                f"manifest case {case['case_id']!r} has an invalid SHA-256"
            )
        case_ids.append(case["case_id"])
        row_keys.append(case["row_key"])
        resources.append(case["case_resource"])
    for label, values in (
        ("case_id", case_ids),
        ("row_key", row_keys),
        ("case_resource", resources),
    ):
        if len(values) != len(set(values)):
            raise IntegrationConfigurationError(
                f"manifest {label} values must be unique"
            )

    splits = manifest["splits"]
    if not isinstance(splits, dict):
        raise IntegrationConfigurationError("manifest splits must be an object")
    if set(splits) != set(REGISTERED_SPLITS):
        raise IntegrationConfigurationError(
            "manifest splits must be exactly train, dev, and test"
        )
    for split_name, split_spec in splits.items():
        if not isinstance(split_spec, dict):
            raise IntegrationConfigurationError(
                f"manifest split {split_name!r} must be an object"
            )
        _require_fields(
            split_spec,
            {"semantic_role"},
            f"manifest split {split_name!r}",
        )
        if "alias_of" in split_spec:
            target = split_spec["alias_of"]
            if target == split_name or target not in splits:
                raise IntegrationConfigurationError(
                    f"manifest split {split_name!r} has invalid alias {target!r}"
                )
        else:
            seeds = split_spec.get("seeds")
            if (
                not isinstance(seeds, list)
                or not seeds
                or any(isinstance(seed, bool) or not isinstance(seed, int)
                       for seed in seeds)
                or len(seeds) != len(set(seeds))
            ):
                raise IntegrationConfigurationError(
                    f"manifest split {split_name!r} needs unique integer seeds"
                )
    return manifest


def load_manifest(path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate a case-set manifest shipped with AERead."""
    manifest_path = Path(path) if path is not None else MANIFEST_PATH
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise IntegrationConfigurationError(
            f"AERead rLLM case-set manifest is missing: {manifest_path}"
        ) from error
    except json.JSONDecodeError as error:
        raise IntegrationConfigurationError(
            f"AERead rLLM case-set manifest is invalid JSON: {error}"
        ) from error
    return _validate_manifest(manifest)


def _split_source(
    manifest: Mapping[str, Any], split: str
) -> tuple[str, Mapping[str, Any]]:
    splits = manifest["splits"]
    if split not in splits:
        raise ValueError(
            f"unknown split {split!r}; expected one of {REGISTERED_SPLITS}"
        )
    source = split
    seen: set[str] = set()
    while "alias_of" in splits[source]:
        if source in seen:
            raise IntegrationConfigurationError(
                f"manifest split aliases contain a cycle at {source!r}"
            )
        seen.add(source)
        source = splits[source]["alias_of"]
    return source, splits[source]


def build_rows(
    split: str = "train", *, manifest_path: str | Path | None = None
) -> list[dict[str, Any]]:
    """Build stable parameter rows for one manifest split.

    The ``test`` registry key returns the same rows as ``dev``. In particular,
    those rows retain ``split='dev'`` to identify their public-development
    semantics. Case resources remain package-relative until the flow builds an
    episode.
    """
    manifest = load_manifest(manifest_path)
    semantic_split, split_spec = _split_source(manifest, split)
    rows: list[dict[str, Any]] = []
    for case in manifest["cases"]:
        for seed in split_spec["seeds"]:
            row_id = (
                f"aeread:{manifest['caseset_version']}:"
                f"{case['row_key']}:s{seed}"
            )
            rows.append(
                {
                    "id": row_id,
                    "uid": row_id,
                    "case_id": case["case_id"],
                    "case_resource": case["case_resource"],
                    "case_sha256": case["case_sha256"],
                    "seed": int(seed),
                    "split": semantic_split,
                    "caseset_version": manifest["caseset_version"],
                    "caseset_sha256": manifest["caseset_sha256"],
                    "protocol_version": manifest["protocol_version"],
                    "prompt_spec": dict(manifest["prompt_spec"]),
                    "panel_spec": dict(manifest["panel_spec"]),
                    "scorer_version": manifest["scorer_version"],
                    "question": (
                        "AERead exchange-economy "
                        f"{case['row_key']}, seed {seed}"
                    ),
                }
            )
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise IntegrationConfigurationError(
            f"AERead rLLM split {split!r} contains duplicate row ids"
        )
    return rows


def build_splits(
    *, manifest_path: str | Path | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Build every rLLM-facing split and verify canonical ID uniqueness."""
    splits = {
        split: build_rows(split, manifest_path=manifest_path)
        for split in REGISTERED_SPLITS
    }
    canonical_ids = [
        row["id"] for split in ("train", "dev") for row in splits[split]
    ]
    if len(canonical_ids) != len(set(canonical_ids)):
        raise IntegrationConfigurationError(
            "AERead canonical train/dev row ids must be globally unique"
        )
    if splits["test"] != splits["dev"]:
        raise IntegrationConfigurationError(
            "AERead test split must remain an exact public-development alias"
        )
    return splits


def _validated_resource_name(case_resource: str) -> PurePosixPath:
    resource = PurePosixPath(case_resource)
    if (
        resource.is_absolute()
        or not resource.parts
        or any(part in {"", ".", ".."} for part in resource.parts)
    ):
        raise IntegrationConfigurationError(
            f"invalid package-relative case resource {case_resource!r}"
        )
    return resource


def _case_resource_roots() -> list[Path]:
    """Return installed-wheel then source-checkout config roots."""
    package_root = Path(__file__).resolve().parent.parent
    roots = [package_root / "configs", package_root.parents[1] / "configs"]
    return list(dict.fromkeys(roots))


def resolve_case_resource(
    row: Mapping[str, Any], *, resource_root: str | Path | None = None
) -> Path:
    """Resolve and SHA-256 verify one row's package-relative case resource."""
    case_resource = row.get("case_resource")
    expected_hash = row.get("case_sha256")
    if not isinstance(case_resource, str):
        raise CaseIntegrityError("AERead row is missing case_resource")
    if not _valid_sha256(expected_hash):
        raise CaseIntegrityError(
            f"AERead row for {case_resource!r} has an invalid case_sha256"
        )
    resource = _validated_resource_name(case_resource)
    roots = (
        [Path(resource_root)]
        if resource_root is not None
        else _case_resource_roots()
    )
    path = next((root.joinpath(*resource.parts) for root in roots
                 if root.joinpath(*resource.parts).is_file()), None)
    if path is None:
        searched = ", ".join(str(root) for root in roots)
        raise CaseIntegrityError(
            f"AERead case resource {case_resource!r} is missing under: {searched}",
            status="missing_case",
            details={"case_resource": case_resource},
        )
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise CaseIntegrityError(
            f"AERead case resource hash mismatch for {case_resource!r} "
            f"(expected {expected_hash}, actual {actual_hash})",
            status="invalid_configuration",
            details={
                "case_resource": case_resource,
                "expected_sha256": expected_hash,
                "actual_sha256": actual_hash,
            },
        )
    return path.resolve()


def register(
    name: str = "aeread",
    splits: Sequence[str] | str | None = None,
    *,
    manifest_path: str | Path | None = None,
) -> dict[str, int]:
    """Register manifest rows with rLLM under train, dev, and test by default."""
    from rllm.data import DatasetRegistry  # type: ignore[import-not-found]

    requested = REGISTERED_SPLITS if splits is None else splits
    if isinstance(requested, str):
        requested = (requested,)
    unknown = sorted(set(requested) - set(REGISTERED_SPLITS))
    if unknown:
        raise ValueError(f"unknown AERead rLLM splits: {unknown}")
    all_rows = build_splits(manifest_path=manifest_path)
    counts: dict[str, int] = {}
    for split in requested:
        rows = all_rows[split]
        DatasetRegistry.register_dataset(
            name,
            rows,
            split,
            source="aeread:integration-v1",
            description=(
                "AERead public integration fixture; test is a public-development "
                "alias, not a private benchmark split"
            ),
            category="economics",
        )
        counts[split] = len(rows)
    return counts


def _missing_dependencies() -> list[str]:
    missing: list[str] = []
    for name in _PREFLIGHT_DEPENDENCIES:
        try:
            available = importlib.util.find_spec(name) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            available = False
        if not available:
            missing.append(name)
    return missing


def preflight(*, manifest_path: str | Path | None = None) -> None:
    """Print the complete dataset contract without making a model call."""
    manifest = load_manifest(manifest_path)
    splits = build_splits(manifest_path=manifest_path)
    print("AERead rLLM dataset preflight")
    print(f"manifest_schema_version: {manifest['manifest_schema_version']}")
    print(f"caseset_version: {manifest['caseset_version']}")
    print(f"protocol_version: {manifest['protocol_version']}")
    print(f"generator_version: {manifest['generator_version']}")
    print(f"scorer_version: {manifest['scorer_version']}")
    print(f"semantic_role: {manifest['semantic_role']}")
    print(f"caseset_sha256: {manifest['caseset_sha256']}")
    print(f"prompt_spec_sha256: {manifest['prompt_spec']['sha256']}")
    print(f"panel_spec_sha256: {manifest['panel_spec']['sha256']}")
    missing = _missing_dependencies()
    print("missing_dependencies: " + (", ".join(missing) if missing else "none"))
    print("cases:")
    for case in manifest["cases"]:
        row = {
            "case_resource": case["case_resource"],
            "case_sha256": case["case_sha256"],
        }
        path = resolve_case_resource(row)
        print(
            f"  {case['case_id']}: resource={case['case_resource']} "
            f"sha256={case['case_sha256']} verified={path}"
        )
    print("splits:")
    for split in REGISTERED_SPLITS:
        alias = " (public-development alias of dev)" if split == "test" else ""
        print(f"  {split}: {len(splits[split])} rows{alias}")
        for row in splits[split]:
            print(f"    {row['id']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--preflight", action="store_true")
    actions.add_argument("--register", action="store_true")
    parser.add_argument("--name", default="aeread")
    parser.add_argument(
        "--split",
        action="append",
        choices=REGISTERED_SPLITS,
        dest="splits",
        help="register only this split; repeat to select more than one",
    )
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if args.register:
        counts = register(
            args.name, args.splits, manifest_path=args.manifest
        )
        print(f"registered dataset {args.name!r}")
        for split, count in counts.items():
            alias = " (public-development alias)" if split == "test" else ""
            print(f"  {split}: {count} rows{alias}")
        return
    preflight(manifest_path=args.manifest)


if __name__ == "__main__":
    main()
