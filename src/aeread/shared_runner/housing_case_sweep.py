"""Provider-free Housing V1 case-configuration qualification sweep."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.housing_v1 import environment as housing_environment

from . import housing_qc
from .housing_qc import audit_bid_world
from .quality import BenchmarkQCStatus, QCTrackStatus
from .resolver import canonical_json_bytes


CONTRACT_SCHEMA_VERSION = "aeread.housing_case_config_sweep/0.1"

_CONFIG_FIELDS = {
    "config_id",
    "difficulty_stratum",
    "tenants",
    "listings",
    "rounds",
    "common_weight",
}
_ROOT_FIELDS = {
    "schema_version",
    "sweep_id",
    "claim_status",
    "question",
    "independent_cluster",
    "generator",
    "development",
    "confirmatory_holdout",
    "policies",
    "selection_rule",
    "outputs",
}

WORLD_FACT_COLUMNS = (
    "sweep_id",
    "split",
    "config_id",
    "difficulty_stratum",
    "tenants",
    "listings",
    "rounds",
    "common_weight",
    "world_seed",
    "world_sha256",
    "case_config_sha256",
    "deterministic_regeneration",
    "finite_values",
    "valid_dimensions",
    "oracle_crosscheck_passed",
    "degenerate_upper_bound",
    "oracle_total",
    "brute_force_oracle_total",
    "no_op_total",
    "random_total",
    "naive_total",
    "adaptive_total",
    "oracle_informed_total",
    "no_op_normalized",
    "random_normalized",
    "naive_normalized",
    "adaptive_normalized",
    "oracle_minus_naive",
    "oracle_minus_naive_normalized",
    "adaptive_minus_naive",
    "adaptive_minus_naive_normalized",
    "naive_is_beatable",
    "adaptive_beats_naive",
    "positive_surplus_edges",
    "positive_surplus_density",
    "viable_favourite_count",
    "max_favourite_collision",
    "max_favourite_share",
    "market_tightness",
)

CONFIG_SUMMARY_COLUMNS = (
    "sweep_id",
    "config_id",
    "difficulty_stratum",
    "tenants",
    "listings",
    "rounds",
    "common_weight",
    "world_count",
    "admitted_world_count",
    "duplicate_world_count",
    "degenerate_world_count",
    "duplicate_rate",
    "degenerate_rate",
    "deterministic_regeneration_rate",
    "finite_values_rate",
    "valid_dimensions_rate",
    "oracle_crosscheck_rate",
    "oracle_active_ceiling_rate",
    "naive_beatable_rate",
    "adaptive_beats_naive_rate",
    "mean_oracle_total",
    "mean_random_normalized",
    "mean_naive_normalized",
    "median_naive_normalized",
    "p10_naive_normalized",
    "p90_naive_normalized",
    "mean_adaptive_normalized",
    "median_oracle_gap_normalized",
    "mean_adaptive_gain_normalized",
    "mean_positive_surplus_density",
    "mean_max_favourite_share",
    "admission_status",
    "failed_requirements",
    "selection_distance",
    "selected",
    "selection_rank_within_stratum",
)


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sealed(value: Mapping[str, Any]) -> dict[str, Any]:
    core = {key: item for key, item in value.items() if key != "artifact_sha256"}
    return {**core, "artifact_sha256": _sha256(core)}


def _source_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def implementation_pins() -> dict[str, dict[str, str]]:
    """Identify the executable source bytes that produced the sweep facts."""

    paths = {
        "housing_environment": Path(housing_environment.__file__).resolve(),
        "housing_qc": Path(housing_qc.__file__).resolve(),
        "housing_case_sweep": Path(__file__).resolve(),
    }
    return {
        component_id: {
            "module": {
                "housing_environment": "aeread.housing_v1.environment",
                "housing_qc": "aeread.shared_runner.housing_qc",
                "housing_case_sweep": "aeread.shared_runner.housing_case_sweep",
            }[component_id],
            "source_sha256": _source_sha256(path),
        }
        for component_id, path in paths.items()
    }


def _strict_positive_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{path} must be a positive integer")
    return value


def _validate_seed_list(value: Any, path: str) -> list[int]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{path} must be a non-empty list")
    if any(isinstance(seed, bool) or not isinstance(seed, int) for seed in value):
        raise ValueError(f"{path} must contain only integers")
    if len(set(value)) != len(value):
        raise ValueError(f"{path} contains duplicate seeds")
    return list(value)


def _validate_config(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _CONFIG_FIELDS:
        raise ValueError(f"{path} has incomplete or unexpected fields")
    for field in ("config_id", "difficulty_stratum"):
        if not isinstance(value[field], str) or not value[field]:
            raise ValueError(f"{path}.{field} must be a non-empty string")
    for field in ("tenants", "listings", "rounds"):
        _strict_positive_int(value[field], f"{path}.{field}")
    weight = value["common_weight"]
    if (
        isinstance(weight, bool)
        or not isinstance(weight, (int, float))
        or not math.isfinite(float(weight))
        or not 0.0 <= float(weight) <= 1.0
    ):
        raise ValueError(f"{path}.common_weight must be finite and within [0, 1]")
    return dict(value)


def _parameter_identity(config: Mapping[str, Any]) -> tuple[int, int, int, float]:
    return (
        config["tenants"],
        config["listings"],
        config["rounds"],
        float(config["common_weight"]),
    )


def load_contract(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_bytes())
    if not isinstance(value, dict) or set(value) != _ROOT_FIELDS:
        raise ValueError("case-sweep contract fields are incomplete or unexpected")
    if value["schema_version"] != CONTRACT_SCHEMA_VERSION:
        raise ValueError("unsupported Housing case-sweep contract schema")
    if value["sweep_id"] != "housing_case_config_sweep_v1":
        raise ValueError("this driver accepts only housing_case_config_sweep_v1")
    if value["claim_status"] != "development_case_qualification":
        raise ValueError("case sweep cannot carry a model-performance claim")
    if value["independent_cluster"] != "world_seed":
        raise ValueError("case sweep has an unexpected independent cluster")
    if value["generator"] != {
        "family": "housing_v1",
        "generator": "make_bid_world",
        "version": "1.0",
    }:
        raise ValueError("Housing generator identity drifted")

    development = value["development"]
    if not isinstance(development, dict) or set(development) != {
        "split",
        "world_seeds",
        "candidate_configs",
    }:
        raise ValueError("development sweep definition is invalid")
    if development["split"] != "development":
        raise ValueError("case sweep may execute only the development split")
    development_seeds = _validate_seed_list(
        development["world_seeds"], "development.world_seeds"
    )
    candidates = development["candidate_configs"]
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("development.candidate_configs must be non-empty")
    development_configs = [
        _validate_config(config, f"development.candidate_configs[{index}]")
        for index, config in enumerate(candidates)
    ]
    config_ids = [config["config_id"] for config in development_configs]
    if len(set(config_ids)) != len(config_ids):
        raise ValueError("development config IDs must be unique")
    if len({_parameter_identity(config) for config in development_configs}) != len(
        development_configs
    ):
        raise ValueError("development parameter combinations must be unique")
    stratum_counts: dict[str, int] = {}
    for config in development_configs:
        stratum_counts[config["difficulty_stratum"]] = (
            stratum_counts.get(config["difficulty_stratum"], 0) + 1
        )
    if stratum_counts != {"mild_1p2": 6, "moderate_1p5": 6, "severe_2p0": 6}:
        raise ValueError("development sweep must retain the frozen 3 by 3 by 2 grid")

    holdout = value["confirmatory_holdout"]
    if not isinstance(holdout, dict) or set(holdout) != {
        "status",
        "access_rule",
        "world_seeds",
        "parameter_combinations",
    }:
        raise ValueError("confirmatory holdout definition is invalid")
    if holdout["status"] != "sealed_not_executed":
        raise ValueError("confirmatory holdout must remain sealed and unexecuted")
    if holdout["access_rule"] != "new_campaign_id_after_confirmatory_freeze":
        raise ValueError("confirmatory holdout access rule drifted")
    holdout_seeds = _validate_seed_list(
        holdout["world_seeds"], "confirmatory_holdout.world_seeds"
    )
    holdout_values = holdout["parameter_combinations"]
    if not isinstance(holdout_values, list) or not holdout_values:
        raise ValueError("confirmatory holdout parameters must be non-empty")
    holdout_configs = [
        _validate_config(
            config, f"confirmatory_holdout.parameter_combinations[{index}]"
        )
        for index, config in enumerate(holdout_values)
    ]
    holdout_ids = [config["config_id"] for config in holdout_configs]
    if len(set(holdout_ids)) != len(holdout_ids):
        raise ValueError("confirmatory holdout config IDs must be unique")
    if len({_parameter_identity(config) for config in holdout_configs}) != len(
        holdout_configs
    ):
        raise ValueError("confirmatory holdout parameter combinations must be unique")
    if set(development_seeds) & set(holdout_seeds):
        raise ValueError("development and confirmatory seeds overlap")
    if {_parameter_identity(config) for config in development_configs} & {
        _parameter_identity(config) for config in holdout_configs
    }:
        raise ValueError("development and confirmatory parameter combinations overlap")

    if value["policies"] != [
        "no_op",
        "seeded_random",
        "naive",
        "adaptive",
        "oracle_informed",
    ]:
        raise ValueError("Housing provider-free policy panel drifted")
    selection = value["selection_rule"]
    expected_selection_fields = {
        "stratum_field",
        "selections_per_stratum",
        "eligibility",
        "target_naive_normalized_median",
        "target_oracle_gap_normalized_median",
        "distance",
        "tie_break",
    }
    if not isinstance(selection, dict) or set(selection) != expected_selection_fields:
        raise ValueError("selection rule is incomplete or unexpected")
    if selection["stratum_field"] != "difficulty_stratum":
        raise ValueError("selection stratum field drifted")
    _strict_positive_int(
        selection["selections_per_stratum"], "selection_rule.selections_per_stratum"
    )
    eligibility = selection["eligibility"]
    expected_eligibility = {
        "duplicate_rate_max",
        "degenerate_rate_max",
        "deterministic_regeneration_rate_min",
        "finite_values_rate_min",
        "valid_dimensions_rate_min",
        "oracle_crosscheck_rate_min",
        "oracle_active_ceiling_rate_min",
        "naive_beatable_rate_min",
        "median_naive_normalized_min",
        "median_naive_normalized_max",
        "median_oracle_gap_normalized_min",
    }
    if not isinstance(eligibility, dict) or set(eligibility) != expected_eligibility:
        raise ValueError("selection eligibility fields drifted")
    for field, threshold in eligibility.items():
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not math.isfinite(float(threshold))
            or not 0.0 <= float(threshold) <= 1.0
        ):
            raise ValueError(
                f"selection_rule.eligibility.{field} must be within [0, 1]"
            )
    if (
        eligibility["median_naive_normalized_min"]
        > eligibility["median_naive_normalized_max"]
    ):
        raise ValueError("naive normalized eligibility interval is inverted")
    for field in (
        "target_naive_normalized_median",
        "target_oracle_gap_normalized_median",
    ):
        target = selection[field]
        if (
            isinstance(target, bool)
            or not isinstance(target, (int, float))
            or not 0.0 <= float(target) <= 1.0
        ):
            raise ValueError(f"selection_rule.{field} must be within [0, 1]")
    if selection["distance"] != "unweighted_l1_to_targets":
        raise ValueError("selection distance rule drifted")
    if selection["tie_break"] != "config_id_ascending":
        raise ValueError("selection tie-break drifted")

    outputs = value["outputs"]
    if outputs != {
        "world_facts": "tables/housing_case_facts.csv",
        "config_summary": "tables/housing_config_summary.csv",
        "selected_configs": "reports/selected_development_configs.json",
        "fact_manifest": "tables/fact_manifest.json",
        "sweep_summary": "reports/sweep_summary.json",
    }:
        raise ValueError("case-sweep output contract drifted")
    return value


def _mean(values: Sequence[float]) -> float:
    return round(statistics.fmean(values), 12)


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("cannot calculate a percentile of an empty sequence")
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 12)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 12)
    weight = position - lower
    return round(ordered[lower] * (1.0 - weight) + ordered[upper] * weight, 12)


def _rate(rows: Sequence[Mapping[str, Any]], field: str) -> float:
    return round(sum(bool(row[field]) for row in rows) / len(rows), 12)


def _eligibility_failures(
    summary: Mapping[str, Any], rule: Mapping[str, Any]
) -> list[str]:
    failures: list[str] = []
    maximums = {
        "duplicate_rate": "duplicate_rate_max",
        "degenerate_rate": "degenerate_rate_max",
        "median_naive_normalized": "median_naive_normalized_max",
    }
    minimums = {
        "deterministic_regeneration_rate": "deterministic_regeneration_rate_min",
        "finite_values_rate": "finite_values_rate_min",
        "valid_dimensions_rate": "valid_dimensions_rate_min",
        "oracle_crosscheck_rate": "oracle_crosscheck_rate_min",
        "oracle_active_ceiling_rate": "oracle_active_ceiling_rate_min",
        "naive_beatable_rate": "naive_beatable_rate_min",
        "median_naive_normalized": "median_naive_normalized_min",
        "median_oracle_gap_normalized": "median_oracle_gap_normalized_min",
    }
    for field, threshold in maximums.items():
        if float(summary[field]) > float(rule[threshold]):
            failures.append(threshold)
    for field, threshold in minimums.items():
        if float(summary[field]) < float(rule[threshold]):
            failures.append(threshold)
    return failures


def summarize_config(
    *,
    sweep_id: str,
    config: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    selection_rule: Mapping[str, Any],
) -> dict[str, Any]:
    if not rows:
        raise ValueError(f"configuration {config['config_id']} has no world facts")
    digests = [str(row["world_sha256"]) for row in rows]
    duplicate_count = len(digests) - len(set(digests))
    admitted = [row for row in rows if not row["degenerate_upper_bound"]]
    if not admitted:
        raise ValueError(
            f"configuration {config['config_id']} has no nondegenerate worlds"
        )

    naive_scores = [float(row["naive_normalized"]) for row in admitted]
    random_scores = [float(row["random_normalized"]) for row in admitted]
    adaptive_scores = [float(row["adaptive_normalized"]) for row in admitted]
    oracle_gaps = [float(row["oracle_minus_naive_normalized"]) for row in admitted]
    adaptive_gains = [float(row["adaptive_minus_naive_normalized"]) for row in admitted]
    world_count = len(rows)
    summary: dict[str, Any] = {
        "sweep_id": sweep_id,
        **dict(config),
        "world_count": world_count,
        "admitted_world_count": len(admitted),
        "duplicate_world_count": duplicate_count,
        "degenerate_world_count": world_count - len(admitted),
        "duplicate_rate": round(duplicate_count / world_count, 12),
        "degenerate_rate": round((world_count - len(admitted)) / world_count, 12),
        "deterministic_regeneration_rate": _rate(rows, "deterministic_regeneration"),
        "finite_values_rate": _rate(rows, "finite_values"),
        "valid_dimensions_rate": _rate(rows, "valid_dimensions"),
        "oracle_crosscheck_rate": _rate(rows, "oracle_crosscheck_passed"),
        "oracle_active_ceiling_rate": round(
            sum(
                math.isclose(
                    float(row["oracle_informed_total"]),
                    float(row["oracle_total"]),
                    abs_tol=1e-9,
                )
                for row in rows
            )
            / world_count,
            12,
        ),
        "naive_beatable_rate": _rate(admitted, "naive_is_beatable"),
        "adaptive_beats_naive_rate": _rate(admitted, "adaptive_beats_naive"),
        "mean_oracle_total": _mean([float(row["oracle_total"]) for row in admitted]),
        "mean_random_normalized": _mean(random_scores),
        "mean_naive_normalized": _mean(naive_scores),
        "median_naive_normalized": round(statistics.median(naive_scores), 12),
        "p10_naive_normalized": _percentile(naive_scores, 0.10),
        "p90_naive_normalized": _percentile(naive_scores, 0.90),
        "mean_adaptive_normalized": _mean(adaptive_scores),
        "median_oracle_gap_normalized": round(statistics.median(oracle_gaps), 12),
        "mean_adaptive_gain_normalized": _mean(adaptive_gains),
        "mean_positive_surplus_density": _mean(
            [float(row["positive_surplus_density"]) for row in admitted]
        ),
        "mean_max_favourite_share": _mean(
            [float(row["max_favourite_share"]) for row in admitted]
        ),
    }
    failures = _eligibility_failures(summary, selection_rule["eligibility"])
    summary["admission_status"] = "passed" if not failures else "excluded"
    summary["failed_requirements"] = failures
    summary["selection_distance"] = round(
        abs(
            summary["median_naive_normalized"]
            - float(selection_rule["target_naive_normalized_median"])
        )
        + abs(
            summary["median_oracle_gap_normalized"]
            - float(selection_rule["target_oracle_gap_normalized_median"])
        ),
        12,
    )
    summary["selected"] = False
    summary["selection_rank_within_stratum"] = None
    return summary


def select_configs(
    summaries: Sequence[dict[str, Any]], selection_rule: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Apply the predeclared rule without consulting holdout or model outcomes."""

    by_stratum: dict[str, list[dict[str, Any]]] = {}
    for summary in summaries:
        by_stratum.setdefault(summary["difficulty_stratum"], []).append(summary)
    selected: list[dict[str, Any]] = []
    limit = int(selection_rule["selections_per_stratum"])
    for stratum in sorted(by_stratum):
        eligible = sorted(
            (
                summary
                for summary in by_stratum[stratum]
                if summary["admission_status"] == "passed"
            ),
            key=lambda summary: (
                summary["selection_distance"],
                summary["config_id"],
            ),
        )
        for rank, summary in enumerate(eligible, start=1):
            summary["selection_rank_within_stratum"] = rank
            if rank <= limit:
                summary["selected"] = True
                selected.append(summary)
    return selected


def build_sweep(
    contract: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    development = contract["development"]
    world_rows: list[dict[str, Any]] = []
    for config in development["candidate_configs"]:
        config_digests: set[str] = set()
        for world_seed in development["world_seeds"]:
            facts = audit_bid_world(
                tenants=config["tenants"],
                listings=config["listings"],
                rounds=config["rounds"],
                common_weight=config["common_weight"],
                world_seed=world_seed,
            )
            if facts["world_sha256"] in config_digests:
                raise ValueError(
                    "duplicate world content within candidate configuration: "
                    f"{config['config_id']} seed {world_seed}"
                )
            config_digests.add(facts["world_sha256"])
            world_rows.append(
                {
                    "sweep_id": contract["sweep_id"],
                    "split": "development",
                    **dict(config),
                    **facts,
                    "case_config_sha256": _sha256(
                        {
                            "world_sha256": facts["world_sha256"],
                            "rounds": config["rounds"],
                        }
                    ),
                }
            )

    summaries: list[dict[str, Any]] = []
    for config in development["candidate_configs"]:
        rows = [row for row in world_rows if row["config_id"] == config["config_id"]]
        summaries.append(
            summarize_config(
                sweep_id=contract["sweep_id"],
                config=config,
                rows=rows,
                selection_rule=contract["selection_rule"],
            )
        )
    selected = select_configs(summaries, contract["selection_rule"])
    selected_artifact = _sealed(
        {
            "schema_version": "aeread.housing_selected_development_configs/0.1",
            "sweep_id": contract["sweep_id"],
            "claim_status": contract["claim_status"],
            "contract_sha256": _sha256(contract),
            "selection_rule": contract["selection_rule"],
            "selection_uses": "development_provider_free_facts_only",
            "confirmatory_holdout_status": "sealed_not_executed",
            "selected_config_count": len(selected),
            "selected_configs": [
                {
                    key: summary[key]
                    for key in (
                        "config_id",
                        "difficulty_stratum",
                        "tenants",
                        "listings",
                        "rounds",
                        "common_weight",
                        "median_naive_normalized",
                        "median_oracle_gap_normalized",
                        "selection_distance",
                        "selection_rank_within_stratum",
                    )
                }
                for summary in selected
            ],
        }
    )
    return world_rows, summaries, selected_artifact


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def _csv_bytes(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream, fieldnames=columns, extrasaction="raise", lineterminator="\n"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({column: _csv_value(row[column]) for column in columns})
    return stream.getvalue().encode("utf-8")


def _publish(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"refusing to publish through symlink: {path}")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.is_file() and path.read_bytes() == payload:
            return path
        raise ValueError(f"refusing to overwrite different sweep artifact: {path}")
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write while publishing Housing sweep artifact")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path


def write_sweep(
    *, contract: Mapping[str, Any], output_dir: str | Path
) -> dict[str, Path]:
    destination = Path(output_dir)
    if destination.is_symlink():
        raise ValueError("Housing sweep output directory must not be a symlink")
    world_rows, summaries, selected = build_sweep(contract)
    outputs = contract["outputs"]
    world_payload = _csv_bytes(world_rows, WORLD_FACT_COLUMNS)
    summary_payload = _csv_bytes(summaries, CONFIG_SUMMARY_COLUMNS)
    selected_payload = canonical_json_bytes(selected) + b"\n"
    paths = {
        "world_facts": _publish(destination / outputs["world_facts"], world_payload),
        "config_summary": _publish(
            destination / outputs["config_summary"], summary_payload
        ),
        "selected_configs": _publish(
            destination / outputs["selected_configs"], selected_payload
        ),
    }
    manifest_core = {
        "schema_version": "aeread.housing_case_fact_manifest/0.1",
        "sweep_id": contract["sweep_id"],
        "contract_sha256": _sha256(contract),
        "source_truth": [
            "frozen_case_sweep_contract",
            "deterministic_housing_world_generator",
        ],
        "implementation_pins": implementation_pins(),
        "projection_semantics": (
            "reportable provider-free case and configuration facts; no model outcomes"
        ),
        "confirmatory_holdout_status": "sealed_not_executed",
        "artifacts": {
            "world_facts": {
                "path": outputs["world_facts"],
                "row_count": len(world_rows),
                "sha256": hashlib.sha256(world_payload).hexdigest(),
            },
            "config_summary": {
                "path": outputs["config_summary"],
                "row_count": len(summaries),
                "sha256": hashlib.sha256(summary_payload).hexdigest(),
            },
            "selected_configs": {
                "path": outputs["selected_configs"],
                "row_count": selected["selected_config_count"],
                "sha256": hashlib.sha256(selected_payload).hexdigest(),
            },
        },
    }
    manifest = {
        **manifest_core,
        "manifest_sha256": _sha256(manifest_core),
    }
    manifest_payload = canonical_json_bytes(manifest) + b"\n"
    paths["fact_manifest"] = _publish(
        destination / outputs["fact_manifest"], manifest_payload
    )
    sweep_summary = _sealed(
        {
            "schema_version": "aeread.housing_case_sweep_summary/0.2",
            "sweep_id": contract["sweep_id"],
            "status": "completed",
            "claim_status": contract["claim_status"],
            "qc_status": BenchmarkQCStatus(
                family_id="housing_v1",
                family_version="1.0.0",
                development=QCTrackStatus(
                    scope_id="development_case_qualification",
                    state="passed",
                    rationale=(
                        "The frozen provider-free development grid completed "
                        "and applied its declared selection rule."
                    ),
                ),
                normative=QCTrackStatus(
                    scope_id="normative_housing_profile",
                    state="partial",
                    rationale=(
                        "Confirmatory case admission, live-model sensitivity, "
                        "and the remaining normative QC bundle are incomplete."
                    ),
                ),
            ).to_dict(),
            "provider_calls": 0,
            "provider_cost_usd": 0.0,
            "development_config_count": len(summaries),
            "development_world_count": len(world_rows),
            "eligible_config_count": sum(
                summary["admission_status"] == "passed" for summary in summaries
            ),
            "selected_config_ids": [
                config["config_id"] for config in selected["selected_configs"]
            ],
            "confirmatory_holdout_status": "sealed_not_executed",
            "fact_manifest_sha256": hashlib.sha256(manifest_payload).hexdigest(),
        }
    )
    paths["sweep_summary"] = _publish(
        destination / outputs["sweep_summary"],
        canonical_json_bytes(sweep_summary) + b"\n",
    )
    return paths


def execute_sweep(
    *, contract_path: str | Path, output_dir: str | Path
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    paths = write_sweep(contract=contract, output_dir=output_dir)
    summary = json.loads(paths["sweep_summary"].read_bytes())
    return {**summary, "outputs": {key: str(path) for key, path in paths.items()}}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Qualify Housing case configurations without model calls"
    )
    parser.add_argument(
        "--contract",
        default="configs/housing_case_config_sweep_v1.json",
    )
    parser.add_argument(
        "--run-root",
        "--output",
        dest="run_root",
        default="runs/housing_case_config_sweep_v1",
    )
    args = parser.parse_args(argv)
    result = execute_sweep(contract_path=args.contract, output_dir=args.run_root)
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
