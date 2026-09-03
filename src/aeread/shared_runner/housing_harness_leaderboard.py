"""Build ranked Housing harness leaderboards from sealed bake-off evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .resolver import canonical_json_bytes


DISPLAY_NAMES = {
    "aeread_minimal_chat_v1": "AERead Minimal Chat",
    "langchain_provider_strategy_v1": "LangChain Provider Strategy",
    "langgraph_structured_output_v1": "LangGraph Structured Output",
    "smolagents_tool_calling_agent_v1": "smolagents Tool-Calling Agent",
    "aeread_minimal_chat": "AERead Minimal Chat",
    "langchain_provider_strategy": "LangChain Provider Strategy",
    "langgraph_structured_output": "LangGraph Structured Output",
    "pydantic_ai_native_output": "PydanticAI Native Output",
    "smolagents_tool_calling_agent": "smolagents Tool-Calling Agent",
}

STATUS_LABELS = {
    "ranked": "Ranked",
    "ineligible_incomplete": "Ineligible: incomplete",
    "disqualified_operational_failure": "Disqualified: operational failure",
}


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _source_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_bakeoff_artifact(value: Mapping[str, Any]) -> None:
    claimed = value.get("artifact_sha256")
    payload = dict(value)
    payload.pop("artifact_sha256", None)
    actual = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    if claimed != actual:
        raise ValueError("bake-off artifact digest mismatch")


def _rank_full_trajectory_rows(
    bakeoff: Mapping[str, Any],
) -> list[dict[str, Any]]:
    environment = bakeoff.get("environment")
    summaries = bakeoff.get("condition_summaries")
    if not isinstance(environment, Mapping) or not isinstance(summaries, Mapping):
        raise ValueError("bake-off artifact lacks environment or condition summaries")
    world_seeds = environment.get("world_seeds")
    replicates = environment.get("replicates")
    if not isinstance(world_seeds, list) or not isinstance(replicates, int):
        raise ValueError("bake-off artifact lacks a valid planned panel")
    planned = len(world_seeds) * replicates
    if planned < 1:
        raise ValueError("bake-off planned trajectory count must be positive")

    rows: list[dict[str, Any]] = []
    for harness_id, raw in summaries.items():
        if not isinstance(raw, Mapping):
            raise ValueError(f"condition summary is not an object: {harness_id}")
        completed = raw.get("completed_worlds")
        score = raw.get("mean_within_case_score")
        total_cost = raw.get("total_cost_usd")
        total_input = raw.get("total_input_tokens")
        total_output = raw.get("total_output_tokens")
        total_requests = raw.get("total_provider_model_requests")
        elapsed = raw.get("mean_elapsed_seconds")
        failures = raw.get(
            "operational_failures",
            planned - completed if isinstance(completed, int) else None,
        )

        def optional_number(value: Any) -> bool:
            return value is None or _finite_number(value)

        def optional_integer(value: Any) -> bool:
            return value is None or (
                isinstance(value, int) and not isinstance(value, bool) and value >= 0
            )

        if (
            not isinstance(completed, int)
            or isinstance(completed, bool)
            or completed < 0
            or completed > planned
            or not isinstance(failures, int)
            or isinstance(failures, bool)
            or failures < 0
            or (completed == 0 and score is not None)
            or (completed > 0 and not _finite_number(score))
            or not optional_number(total_cost)
            or not optional_integer(total_input)
            or not optional_integer(total_output)
            or not optional_integer(total_requests)
            or not optional_number(elapsed)
        ):
            raise ValueError(f"condition summary has invalid metrics: {harness_id}")
        eligible = (
            completed == planned
            and raw.get("provider_cost_complete") is True
            and raw.get("route_verified") is True
            and _finite_number(total_cost)
        )
        denominator = completed if completed else None
        status = "ranked" if eligible else "ineligible_incomplete"
        if failures and completed == 0:
            status = "disqualified_operational_failure"

        def mean_from_total(total_value: Any) -> float | None:
            if not _finite_number(total_value) or denominator is None:
                return None
            return float(total_value) / denominator

        rows.append(
            {
                "rank": None,
                "scope": "full_trajectory",
                "harness_id": harness_id,
                "harness": DISPLAY_NAMES.get(harness_id, harness_id),
                "status": status,
                "completed": completed,
                "attempted": planned,
                "reliability": completed / planned,
                "mean_within_case_score": float(score) if score is not None else None,
                "mean_elapsed_seconds": float(elapsed) if elapsed is not None else None,
                "total_cost_usd": (
                    float(total_cost) if total_cost is not None else None
                ),
                "mean_cost_usd": raw.get("mean_cost_usd", mean_from_total(total_cost)),
                "mean_input_tokens": raw.get(
                    "mean_input_tokens", mean_from_total(total_input)
                ),
                "mean_output_tokens": raw.get(
                    "mean_output_tokens", mean_from_total(total_output)
                ),
                "mean_model_requests": raw.get(
                    "mean_model_requests", mean_from_total(total_requests)
                ),
                "effective_retry_count": raw.get("effective_retry_count"),
                "route_verified": raw.get("route_verified") is True,
                "provider_cost_complete": raw.get("provider_cost_complete") is True,
                "cost_qualifier": raw.get(
                    "cost_qualifier", "exact" if eligible else "unknown"
                ),
                "notes": str(raw.get("notes", "")),
            }
        )

    smol = bakeoff.get("smolagents_full_trajectory_gate")
    existing_harness_ids = {row["harness_id"] for row in rows}
    if (
        isinstance(smol, Mapping)
        and str(smol.get("condition_id")) not in existing_harness_ids
    ):
        rows.append(
            {
                "rank": None,
                "scope": "full_trajectory",
                "harness_id": str(smol.get("condition_id")),
                "harness": DISPLAY_NAMES.get(
                    str(smol.get("condition_id")), str(smol.get("condition_id"))
                ),
                "status": "disqualified_operational_failure",
                "completed": 0,
                "attempted": 1,
                "reliability": 0.0,
                "mean_within_case_score": None,
                "mean_elapsed_seconds": smol.get("elapsed_seconds"),
                "total_cost_usd": smol.get("known_prefix_cost_usd"),
                "mean_cost_usd": smol.get("known_prefix_cost_usd"),
                "mean_input_tokens": smol.get("known_prefix_input_tokens"),
                "mean_output_tokens": smol.get("known_prefix_output_tokens"),
                "mean_model_requests": smol.get("captured_internal_model_requests"),
                "effective_retry_count": None,
                "route_verified": True,
                "provider_cost_complete": False,
                "cost_qualifier": "lower_bound",
                "notes": (
                    "Failed after 21 successful tenant actions; the failing "
                    "action's billing was not captured."
                ),
            }
        )

    eligible_rows = [row for row in rows if row["status"] == "ranked"]
    eligible_rows.sort(
        key=lambda row: (
            -row["mean_within_case_score"],
            -row["reliability"],
            row["mean_cost_usd"],
            row["harness_id"],
        )
    )
    for rank, row in enumerate(eligible_rows, start=1):
        row["rank"] = rank
    rows.sort(
        key=lambda row: (
            row["rank"] is None,
            row["rank"] if row["rank"] is not None else math.inf,
            row["harness_id"],
        )
    )
    return rows


def _qualification_rows(admission: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if admission is None:
        return []
    aggregates = admission.get("aggregates")
    if not isinstance(aggregates, list):
        raise ValueError("admission artifact lacks aggregate rows")
    rows: list[dict[str, Any]] = []
    for raw in aggregates:
        if not isinstance(raw, Mapping):
            raise ValueError("admission aggregate row is not an object")
        completed, valid = raw.get("completed"), raw.get("valid")
        if (
            not isinstance(completed, int)
            or not isinstance(valid, int)
            or completed < 1
        ):
            raise ValueError("admission aggregate has invalid completion counts")
        rows.append(
            {
                "gate_rank": None,
                "scope": "single_action_gate",
                "harness_id": raw.get("harness"),
                "harness": DISPLAY_NAMES.get(
                    str(raw.get("harness")), str(raw.get("harness"))
                ),
                "status": (
                    "passed_single_action_gate"
                    if completed == valid
                    else "failed_single_action_gate"
                ),
                "completed": completed,
                "valid": valid,
                "validity_rate": valid / completed,
                "mean_elapsed_seconds": raw.get("mean_elapsed_seconds"),
                "mean_cost_usd": raw.get("mean_cost_usd"),
                "mean_input_tokens": raw.get("mean_input_tokens"),
                "mean_output_tokens": raw.get("mean_output_tokens"),
            }
        )
    rows.sort(
        key=lambda row: (
            -row["validity_rate"],
            row["mean_elapsed_seconds"],
            row["mean_cost_usd"],
            row["harness_id"],
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["gate_rank"] = rank
    return rows


def build_leaderboard(
    bakeoff: Mapping[str, Any], *, admission: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Build a transparent ranking without collapsing quality and operations."""

    _verify_bakeoff_artifact(bakeoff)
    full_rows = _rank_full_trajectory_rows(bakeoff)
    paired = bakeoff.get("paired_analysis")
    if not isinstance(paired, Mapping):
        raise ValueError(
            "bake-off artifact lacks a complete paired analysis; do not rank an "
            "incomplete panel"
        )
    leaderboard = {
        "schema_version": "aeread.housing_harness_leaderboard/0.1",
        "title": "Housing V1 Open Harness Leaderboard",
        "scope": bakeoff.get("scope"),
        "model_route": bakeoff.get("model_route"),
        "environment": bakeoff.get("environment"),
        "ranking_policy": {
            "eligibility": (
                "Complete the full paired panel with verified route and complete cost."
            ),
            "primary_metric": "mean_within_case_score_descending",
            "tie_breakers": ["reliability_descending", "mean_cost_usd_ascending"],
            "operational_failures": "visible_but_unranked",
            "single_action_gates": "separate_qualification_table",
            "composite_score": "disabled",
        },
        "full_trajectory_leaderboard": full_rows,
        "qualification_gate": _qualification_rows(admission),
        "statistical_context": {
            "paired_difference": paired.get("mean_paired_difference"),
            "cluster_bootstrap_95": paired.get("cluster_bootstrap_95"),
            "complete_pair_world_count": paired.get("complete_pair_world_count"),
            "interpretation": (
                "Exploratory only; the paired interval crosses zero, so rank 1 is "
                "the observed ordering, not a confirmed population winner."
            ),
        },
        "source_bakeoff_artifact_sha256": bakeoff.get("artifact_sha256"),
    }
    leaderboard["leaderboard_sha256"] = hashlib.sha256(
        canonical_json_bytes(leaderboard)
    ).hexdigest()
    return leaderboard


def _format_optional(value: Any, *, digits: int = 4) -> str:
    return "—" if not _finite_number(value) else f"{float(value):.{digits}f}"


def leaderboard_markdown(leaderboard: Mapping[str, Any]) -> str:
    rows = leaderboard["full_trajectory_leaderboard"]
    lines = [
        "# Housing V1 Open Harness Leaderboard",
        "",
        "Primary ranking: mean within-case Housing score. Reliability is an "
        "eligibility gate; cost breaks exact score/reliability ties.",
        "",
        "| Rank | Harness | Status | Full runs | Quality | Reliability | Time/run | Cost/run | Input/run | Model calls/run |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        rank = str(row["rank"]) if row["rank"] is not None else "—"
        cost = _format_optional(row["mean_cost_usd"], digits=6)
        if cost != "—":
            cost = "$" + cost
        if row.get("cost_qualifier") == "lower_bound" and cost != "—":
            cost = "≥" + cost
        input_tokens = _format_optional(row["mean_input_tokens"], digits=0)
        if row.get("cost_qualifier") == "lower_bound" and input_tokens != "—":
            input_tokens = "≥" + input_tokens
        model_requests = _format_optional(row["mean_model_requests"], digits=1)
        if row.get("cost_qualifier") == "lower_bound" and model_requests != "—":
            model_requests = "≥" + model_requests
        lines.append(
            "| "
            + " | ".join(
                (
                    rank,
                    row["harness"],
                    STATUS_LABELS.get(row["status"], row["status"]),
                    f"{row['completed']}/{row['attempted']}",
                    _format_optional(row["mean_within_case_score"]),
                    f"{row['reliability']:.0%}",
                    _format_optional(row["mean_elapsed_seconds"], digits=1) + "s",
                    cost,
                    input_tokens,
                    model_requests,
                )
            )
            + " |"
        )
    stats = leaderboard["statistical_context"]
    interval = stats["cluster_bootstrap_95"]
    lines.extend(
        [
            "",
            "Observed LangChain minus AERead score difference: "
            f"{stats['paired_difference']:+.4f}; paired bootstrap 95% interval "
            f"[{interval[0]:+.4f}, {interval[1]:+.4f}] across "
            f"{stats['complete_pair_world_count']} worlds.",
            "",
            "Unranked rows remain visible because operational failure is missingness, "
            "not a zero quality score. Values prefixed with ≥ are known lower bounds.",
            "Wall-clock time includes live provider variance and is not used for the "
            "primary rank.",
        ]
    )
    qualification = leaderboard.get("qualification_gate") or []
    if qualification:
        lines.extend(
            [
                "",
                "## Single-action qualification gate",
                "",
                "This table is not comparable to full Housing trajectories.",
                "",
                "| Gate order | Harness | Valid | Time/action | Cost/action | Input/action | Output/action |",
                "|---:|---|---:|---:|---:|---:|---:|",
            ]
        )
        for row in qualification:
            lines.append(
                "| "
                + " | ".join(
                    (
                        str(row["gate_rank"]),
                        row["harness"],
                        f"{row['valid']}/{row['completed']}",
                        _format_optional(row["mean_elapsed_seconds"], digits=3) + "s",
                        "$" + _format_optional(row["mean_cost_usd"], digits=7),
                        _format_optional(row["mean_input_tokens"], digits=0),
                        _format_optional(row["mean_output_tokens"], digits=1),
                    )
                )
                + " |"
            )
    return "\n".join(lines) + "\n"


def leaderboard_csv(leaderboard: Mapping[str, Any]) -> str:
    fields = (
        "rank",
        "scope",
        "harness_id",
        "harness",
        "status",
        "completed",
        "attempted",
        "reliability",
        "mean_within_case_score",
        "mean_elapsed_seconds",
        "mean_cost_usd",
        "cost_qualifier",
        "mean_input_tokens",
        "mean_output_tokens",
        "mean_model_requests",
        "notes",
    )
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=fields,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(leaderboard["full_trajectory_leaderboard"])
    return output.getvalue()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_leaderboard(
    *,
    bakeoff_path: Path,
    admission_path: Path | None,
    output_prefix: Path,
) -> tuple[Path, Path, Path]:
    bakeoff = json.loads(bakeoff_path.read_bytes())
    admission = (
        json.loads(admission_path.read_bytes()) if admission_path is not None else None
    )
    leaderboard = build_leaderboard(bakeoff, admission=admission)
    leaderboard["source_files"] = {
        "bakeoff": {
            "path": str(bakeoff_path),
            "sha256": _source_sha256(bakeoff_path),
        },
        "admission": (
            {
                "path": str(admission_path),
                "sha256": _source_sha256(admission_path),
            }
            if admission_path is not None
            else None
        ),
    }
    # Bind source-file identities into the final leaderboard digest.
    leaderboard.pop("leaderboard_sha256", None)
    leaderboard["leaderboard_sha256"] = hashlib.sha256(
        canonical_json_bytes(leaderboard)
    ).hexdigest()
    json_path = Path(str(output_prefix) + ".json")
    csv_path = Path(str(output_prefix) + ".csv")
    markdown_path = Path(str(output_prefix) + ".md")
    _atomic_write(json_path, canonical_json_bytes(leaderboard) + b"\n")
    _atomic_write(csv_path, leaderboard_csv(leaderboard).encode("utf-8"))
    _atomic_write(markdown_path, leaderboard_markdown(leaderboard).encode("utf-8"))
    return json_path, csv_path, markdown_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bakeoff", type=Path, required=True)
    parser.add_argument("--admission", type=Path)
    parser.add_argument(
        "--report-prefix",
        "--output-prefix",
        dest="report_prefix",
        type=Path,
        required=True,
    )
    arguments = parser.parse_args(argv)
    paths = write_leaderboard(
        bakeoff_path=arguments.bakeoff,
        admission_path=arguments.admission,
        output_prefix=arguments.report_prefix,
    )
    print("\n".join(str(path) for path in paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "build_leaderboard",
    "leaderboard_csv",
    "leaderboard_markdown",
    "write_leaderboard",
]
