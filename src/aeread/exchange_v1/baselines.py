"""Deterministic baselines CLI + v1 config freeze (contract steps 1-2, no LLM).

Produces the baseline denominators (no-op / random / greedy / stronger-heuristic /
information-constrained oracle, plus social-optimum ceilings) for each frozen v1
config, and maintains the freeze manifest that pins the config set by content hash.
Runs entirely without an API key; every quantity is provider-free.

Usage:
    python -m aeread.exchange_v1.baselines --configs 'configs/exchange_economy/releases/v1/v1_*.json' \
        --output-json docs/exchange_economy/v1_baselines.json \
        --output-md docs/exchange_economy/v1_baselines.md
    python -m aeread.exchange_v1.baselines --freeze --configs 'configs/exchange_economy/releases/v1/v1_*.json'
    python -m aeread.exchange_v1.baselines --check
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:  # Supports installed and source-tree package imports.
    from aeread.exchange_v1 import economy as ex
    from aeread.exchange_v1 import validity as validity
except ModuleNotFoundError:  # pragma: no cover - exercised by module execution.
    from . import economy as ex
    from . import validity as validity


DEFAULT_MANIFEST_PATH = Path("configs/exchange_economy/releases/v1/v1_manifest.json")
D1_METADATA_FIELDS = ("description", "intended_capability", "interpretation_if_failed")


@dataclass(frozen=True)
class BaselineRecord:
    config_name: str
    config_path: str
    sha256: str
    rounds: int
    seed: int
    no_op_gain: float
    random_mean_gain: float
    greedy_gain: float
    stronger_heuristic_gain: float
    information_constrained_gain: float
    hidden_discovery_gain: float
    greedy_applied_rounds: int
    stronger_heuristic_applied_rounds: int
    information_constrained_applied_rounds: int
    greedy_social_optimum_welfare_gain: float
    social_optimum_welfare_gain: float
    ordering: dict[str, validity.ValidityInequality] = field(default_factory=dict)

    @property
    def ordering_passed(self) -> bool:
        return all(item.passed for item in self.ordering.values())


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compute_baselines(
    config_path: str | Path,
    *,
    rounds: Optional[int] = None,
    random_samples: int = 5,
    random_seed: int = 0,
) -> BaselineRecord:
    config_path = Path(config_path)
    config = ex.load_experiment_config(config_path)
    result = validity.evaluate_config_validity(
        config,
        rounds=rounds,
        random_samples=random_samples,
        random_seed=random_seed,
    )
    world = ex.make_world_from_config(config)
    initial_welfare = ex.total_welfare(world)
    greedy_ceiling = ex.total_welfare(world, ex.greedy_social_optimum(world)) - initial_welfare
    optimum_ceiling = ex.total_welfare(world, ex.social_optimum(world)) - initial_welfare
    return BaselineRecord(
        config_name=config.name,
        config_path=str(config_path),
        sha256=file_sha256(config_path),
        rounds=result.rounds,
        seed=config.seed,
        no_op_gain=result.no_op_gain,
        random_mean_gain=result.random_mean_gain,
        greedy_gain=result.greedy_gain,
        stronger_heuristic_gain=result.stronger_heuristic_gain,
        information_constrained_gain=result.information_constrained_gain,
        hidden_discovery_gain=result.hidden_discovery_gain,
        greedy_applied_rounds=result.greedy_applied_rounds,
        stronger_heuristic_applied_rounds=result.stronger_heuristic_applied_rounds,
        information_constrained_applied_rounds=result.information_constrained_applied_rounds,
        greedy_social_optimum_welfare_gain=greedy_ceiling,
        social_optimum_welfare_gain=optimum_ceiling,
        ordering=validity._treatment_environment_ordering(result),
    )


def d1_metadata_violations(config_path: str | Path) -> list[str]:
    """D1 acceptance: raw JSON must carry description/intended_capability/interpretation_if_failed."""
    raw = json.loads(Path(config_path).read_text())
    return [
        f"missing or empty required metadata field: {field_name}"
        for field_name in D1_METADATA_FIELDS
        if not str(raw.get(field_name, "")).strip()
    ]


def d1_acceptance_violations(config_path: str | Path) -> list[str]:
    """All D1 acceptance criteria for one config; empty list means accepted."""
    violations = d1_metadata_violations(config_path)
    try:
        config = ex.load_experiment_config(config_path)
    except Exception as exc:
        violations.append(f"load_experiment_config failed: {exc}")
        return violations
    if config.protocol.information_reveal_profile != "legacy":
        try:
            world = ex.make_world_from_config(config)
            audit = ex.validate_information_reveal_protocol(world, config.protocol)
            if not audit.ok:
                violations.append(audit.format())
        except Exception as exc:
            violations.append(f"information reveal validation errored: {exc}")
    return violations


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return ""


def freeze(
    config_paths: list[str | Path],
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    *,
    rounds: Optional[int] = None,
    random_samples: int = 5,
    random_seed: int = 0,
) -> tuple[dict[str, Any], list[BaselineRecord]]:
    """Pin the config set by content hash, recording baseline denominators alongside.

    Refuses to freeze a config that fails D1 acceptance -- a frozen set must be
    valid at freeze time, not just unchanged since. Returns (manifest, records)
    so callers can emit reports without recomputing the (expensive) baselines.
    """
    records = []
    entries = []
    for path in sorted(str(p) for p in config_paths):
        violations = d1_acceptance_violations(path)
        if violations:
            raise ValueError(f"{path} fails D1 acceptance, refusing to freeze:\n" + "\n".join(f"- {v}" for v in violations))
        record = compute_baselines(path, rounds=rounds, random_samples=random_samples, random_seed=random_seed)
        records.append(record)
        entry = asdict(record)
        entry["ordering_passed"] = record.ordering_passed
        entries.append(entry)
    manifest = {
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "random_samples": random_samples,
        "random_seed": random_seed,
        "configs": entries,
    }
    manifest_path = Path(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest, records


def check(manifest_path: str | Path = DEFAULT_MANIFEST_PATH) -> list[str]:
    """Verify the frozen set: hash drift + full D1 acceptance. Empty list = ok."""
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        return [f"manifest not found: {manifest_path}"]
    manifest = json.loads(manifest_path.read_text())
    failures: list[str] = []
    for entry in manifest.get("configs", []):
        path = entry["config_path"]
        if not Path(path).exists():
            failures.append(f"{path}: frozen config file is missing")
            continue
        actual = file_sha256(path)
        if actual != entry["sha256"]:
            failures.append(f"{path}: content drift (frozen {entry['sha256'][:12]}..., actual {actual[:12]}...)")
        for violation in d1_acceptance_violations(path):
            failures.append(f"{path}: {violation}")
    return failures


def records_from_manifest(manifest_path: str | Path = DEFAULT_MANIFEST_PATH) -> list[BaselineRecord]:
    """Rebuild BaselineRecords from a freeze manifest (no recomputation)."""
    manifest = json.loads(Path(manifest_path).read_text())
    records = []
    for entry in manifest.get("configs", []):
        ordering = {
            name: validity.ValidityInequality(**item)
            for name, item in entry.get("ordering", {}).items()
        }
        fields = {k: v for k, v in entry.items() if k in BaselineRecord.__dataclass_fields__}
        fields["ordering"] = ordering
        records.append(BaselineRecord(**fields))
    return records


def classify_ordering(record: BaselineRecord) -> tuple[list[str], list[str]]:
    """Split the record's failed ordering inequalities into (ties, inversions).

    Ties at a tier are expected structure on single-pressure configs (e.g. the
    greedy frontier IS the protocol frontier on a visible bilateral ladder rung);
    only an inversion (left > right) is a red flag for arena validity.
    """
    ties: list[str] = []
    inversions: list[str] = []
    for name, item in record.ordering.items():
        if item.passed:
            continue
        if abs(item.left_value - item.right_value) <= 1e-9:
            ties.append(name)
        else:
            inversions.append(name)
    return ties, inversions


def _ordering_cell(record: BaselineRecord) -> str:
    """Strict-pass / tie / inversion label for the report table."""
    if record.ordering_passed:
        return "pass"
    ties, inversions = classify_ordering(record)
    parts = []
    if inversions:
        parts.append("INVERTED(" + ",".join(inversions) + ")")
    if ties:
        parts.append("tie(" + ",".join(ties) + ")")
    return " ".join(parts)


def records_to_markdown(records: list[BaselineRecord]) -> str:
    lines = [
        "# V1 deterministic baseline denominators",
        "",
        "All quantities provider-free (no LLM calls). random/greedy/heuristic/info-oracle gains",
        "are summed per-round frontier surplus against the initial world (opportunities are NOT",
        "applied between rounds, so they are per-round denominators, not cumulative episode gains,",
        "and may exceed the ceilings). Ceilings are one-shot utilitarian optima over the endowment.",
        "Ordering: `pass` = random < greedy < heuristic < info-oracle strictly; `tie(...)` = adjacent",
        "tiers equal (expected on single-pressure rungs, e.g. greedy == protocol frontier when trade",
        "is bilateral-visible); `INVERTED(...)` = a lower tier strictly beats a higher one (red flag).",
        "",
        "| config | rounds | no-op | random | greedy | heuristic | info-oracle | hidden gap | greedy ceiling | optimum ceiling | ordering |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in records:
        ordering = _ordering_cell(r)
        lines.append(
            f"| {r.config_name} | {r.rounds} | {r.no_op_gain:.3f} | {r.random_mean_gain:.3f} "
            f"| {r.greedy_gain:.3f} | {r.stronger_heuristic_gain:.3f} | {r.information_constrained_gain:.3f} "
            f"| {r.hidden_discovery_gain:.3f} | {r.greedy_social_optimum_welfare_gain:.3f} "
            f"| {r.social_optimum_welfare_gain:.3f} | {ordering} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic v1 baselines + config freeze (no LLM)")
    parser.add_argument("--configs", default="configs/exchange_economy/releases/v1/v1_*.json",
                        help="glob of configs to score/freeze (default: the v1 frozen set)")
    parser.add_argument("--rounds", type=int, default=None, help="override rounds for scoring")
    parser.add_argument("--random-samples", type=int, default=5)
    parser.add_argument("--random-seed", type=int, default=0)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--freeze", action="store_true", help="write the freeze manifest")
    parser.add_argument("--check", action="store_true", help="verify the freeze manifest")
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--output-md", default=None)
    args = parser.parse_args()

    if args.check:
        failures = check(args.manifest)
        if failures:
            print(f"FREEZE CHECK FAILED ({len(failures)} problem(s)):")
            for item in failures:
                print(f"- {item}")
            return 1
        print(f"freeze check ok: {args.manifest}")
        return 0

    config_paths = sorted(glob.glob(args.configs))
    manifest_glob_excluded = [p for p in config_paths if not p.endswith("v1_manifest.json")]
    if not manifest_glob_excluded:
        print(f"no configs matched: {args.configs}")
        return 1

    if args.freeze:
        manifest, records = freeze(
            manifest_glob_excluded,
            args.manifest,
            rounds=args.rounds,
            random_samples=args.random_samples,
            random_seed=args.random_seed,
        )
        print(f"froze {len(manifest['configs'])} configs -> {args.manifest}")
    else:
        records = [
            compute_baselines(p, rounds=args.rounds, random_samples=args.random_samples, random_seed=args.random_seed)
            for p in manifest_glob_excluded
        ]
    markdown = records_to_markdown(records)
    print(markdown)
    if args.output_md:
        Path(args.output_md).write_text(markdown)
    if args.output_json:
        payload = []
        for record in records:
            entry = asdict(record)
            entry["ordering_passed"] = record.ordering_passed
            payload.append(entry)
        Path(args.output_json).write_text(json.dumps(payload, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
