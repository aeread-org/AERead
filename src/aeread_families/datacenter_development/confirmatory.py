"""Confirmatory freeze and analysis for the V2 world panel, reproducibly.

The first confirmatory, ``datacenter_development_v2_world_panel_confirmatory_v1``,
was frozen and analysed by session scripts that never reached the repository
(DC-T-07). This module is those scripts made into code: ``freeze_record``
builds the freeze from a contract and the design the driver resolves for it;
``analyze`` computes the predeclared endpoints from a sealed bundle's cell
table with the world-clustered bootstrap the freeze names; ``seal_analysis``
adds the result to the bundle's manifest.

On the v1 bundle ``analyze`` reproduces every sealed number. One split needs
the run root: v1 typed a walk that stated its reason as a parser rejection
(DC-D-08), and telling it from a non-JSON output required the raw model text,
which a sealed bundle does not carry. Given the run root the split is
reproduced exactly; without it the parser rejections stay one category. From
developer interface 3 a walk with a reason is a valid walk and the cell table
carries the distinction itself.
"""

from __future__ import annotations

import argparse
import collections
import datetime as _dt
import glob
import hashlib
import json
import random
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.publication import add_publication_artifact
from aeread.shared_runner.run.resolver import canonical_json_bytes

from .stack_worlds import load_pack_manifest
from .world_campaign import build_design, load_contract, pack_root_for, publication_root_for

FREEZE_SCHEMA = "aeread.datacenter_confirmatory_freeze/0.1"
ANALYSIS_SCHEMA = "aeread.datacenter_confirmatory_analysis/0.1"
PARSER_REJECTION = "malformed_datacenter_stack_action"

#: The predeclared text a freeze carries. Every field is a sentence someone
#: reads before the run; none is derived from the run.
DEFAULT_FREEZE_TEXT: dict[str, Any] = {
    "primary_endpoint": (
        "admission rate over worlds (a cell is admitted when the stack executes, every "
        "constraint check holds and financing funds), with a world-clustered bootstrap interval"
    ),
    "secondary_endpoint": (
        "mean developer_equity_npv delta from the scripted reference over admitted cells, "
        "world-clustered bootstrap"
    ),
    "predeclared_slices": ["stratum"],
    "seed_handling": (
        "the seeds of a world are averaged within the world before worlds are treated as independent"
    ),
    "stopping_rule": (
        "no early stop; the run ends when every planned cell holds a verified receipt or typed "
        "missingness, or the campaign ceiling is reached"
    ),
    "claims_allowed": {
        "winner": False,
        "inferential_model_ranking": False,
        "causal_condition_effect": False,
        "single_route_descriptive_with_cluster_intervals": True,
    },
    "execution_order": "world index then seed, one cell at a time, 10 s provider cooldown",
}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_record(
    contract_path: Path | str,
    design: Mapping[str, Any],
    *,
    prompt_id: str,
    prompt_text: str,
    holdout: str,
    sample_size_rationale: str,
    missingness_policy: str,
    output_schema_bounded: bool = True,
    text: Mapping[str, Any] | None = None,
    design_digest_note: str | None = None,
    frozen_at: str | None = None,
) -> dict[str, Any]:
    """The freeze record for ``contract_path`` given the design resolved for it.

    The binding pins are the run-plan digests, one per planned cell: they pin
    the case, the prompt, the schema and every implementation, and they do
    not depend on the interpreter. The design digest is recorded as well and,
    for schema-0.1 contracts, annotated with why it may differ (DC-T-05)."""

    contract_path = Path(contract_path)
    contract = load_contract(contract_path)
    fields = {**DEFAULT_FREEZE_TEXT, **(text or {})}
    record = {
        "schema_version": FREEZE_SCHEMA,
        "campaign_id": contract["campaign_id"],
        "frozen_at": frozen_at or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "contract_sha256": _sha256_file(contract_path),
        "pack_id": contract["pack_id"],
        "pack_sha256": contract["expected_pack_sha256"],
        "design_artifact_sha256": design["artifact_sha256"],
        "campaign_driver_sha256": design["campaign_driver_sha256"],
        "frozen_run_plan_sha256s": [cell["run_plan_sha256"] for cell in design["cells"]],
        "planned_cells": design["planned_cells"],
        "independent_cluster_count": design["independent_cluster_count"],
        "paired_seed_count": design["paired_seed_count"],
        "developer_prompt_id": prompt_id,
        "developer_prompt_sha256": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
        "output_schema_bounded": output_schema_bounded,
        "holdout": holdout,
        "sample_size_rationale": sample_size_rationale,
        "missingness_policy": missingness_policy,
        **fields,
    }
    if design_digest_note is not None:
        record["design_digest_note"] = design_digest_note
    if design["pack_sha256"] != record["pack_sha256"]:
        raise ValueError("design and contract disagree on the pack")
    return record


def write_freeze(contract_path: Path | str, **kwargs: Any) -> Path:
    """Resolve the design for the contract and write ``<contract>.freeze.json``."""

    contract_path = Path(contract_path)
    contract = load_contract(contract_path)
    design = build_design(contract, pack_root=pack_root_for(contract))
    record = freeze_record(contract_path, design, **kwargs)
    out = contract_path.with_suffix(".freeze.json")
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------


def _load_cells(bundle_root: Path) -> list[dict[str, Any]]:
    path = bundle_root / "tables" / "cells.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _walk_split(run_root: Path, cell_key: str) -> str:
    """v1's split of a parser rejection, from the raw model text under the run root."""

    cell = run_root / "live" / cell_key
    events = sorted(cell.glob("**/events.jsonl"))
    if not events:
        return "other_parser_rejection"
    rows = [json.loads(line) for line in events[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    calls = [row for row in rows if row.get("event_type") == "provider_call_succeeded"]
    if not calls:
        return "other_parser_rejection"
    blobs = glob.glob(str(cell / "**" / calls[-1]["payload_ref"]), recursive=True)
    if not blobs:
        return "other_parser_rejection"
    text = json.loads(Path(blobs[0]).read_text(encoding="utf-8"))["provider_result"]["output_text"]
    try:
        action = json.loads(text)
    except Exception:
        return "not_json"
    return "walk_with_reason" if action.get("decision") == "walk" and action.get("message") else "other_parser_rejection"


def classify(cell: Mapping[str, Any], *, run_root: Path | None = None) -> dict[str, Any]:
    """One row per cell: admitted, its reference delta when admitted, or why not."""

    if cell["status"] != "completed" or cell["inclusion_status"] != "included":
        return {"world": cell["case_id"], "stratum": cell["stratum"], "seed": cell["inference_seed"],
                "admitted": False, "delta": None, "exclusion": None, "missing": True}
    outcome = cell["outcome"]
    admitted = bool(outcome["project_completed"]) and bool(outcome["project_constraints_satisfied"]) and not outcome["temporal_violations"]
    kind = None
    if outcome["temporal_violations"]:
        kind = str(outcome["temporal_violations"][0])
        if kind == PARSER_REJECTION and run_root is not None:
            kind = _walk_split(run_root, str(cell["cell_key"]))
    elif outcome["project_completed"] and not admitted:
        kind = "completed_but_unfinanced"
    elif not outcome["project_completed"]:
        # A valid episode that ended without a stack: the walk or the
        # refusal that ended it, which under interface 3 may carry a reason.
        kind = str(outcome["termination_reason"])
    delta = (int(outcome["developer_equity_npv_cents"]) - int(cell["scripted_baseline_developer_equity_npv_cents"])) if admitted else None
    return {"world": cell["case_id"], "stratum": cell["stratum"], "seed": cell["inference_seed"],
            "admitted": admitted, "delta": delta, "exclusion": kind, "missing": False}


def _bootstrap(rng: random.Random, units: Sequence[str], stat, draws: int) -> tuple[float, float]:
    out = []
    for _ in range(draws):
        sample = [units[rng.randrange(len(units))] for _ in units]
        out.append(stat(sample))
    out.sort()
    return out[int(0.025 * draws)], out[int(0.975 * draws)]


def analyze(
    bundle_root: Path | str,
    contract: Mapping[str, Any],
    freeze: Mapping[str, Any],
    *,
    reading: str,
    run_root: Path | str | None = None,
    missingness_ceiling: float = 0.10,
) -> dict[str, Any]:
    """The predeclared endpoints, computed as the freeze says.

    Admission is averaged within each world across its seeds before worlds
    are resampled; the reference delta is averaged within admitted worlds
    the same way. One stream seeded by the contract serves both bootstraps
    in that order, admission then delta, which is how v1 was sealed; two
    analysts with the contract get the same intervals."""

    bundle_root = Path(bundle_root)
    draws = int(contract["analysis"]["bootstrap_draws"])
    seed = int(contract["analysis"]["bootstrap_seed"])
    rows = [classify(cell, run_root=Path(run_root) if run_root else None) for cell in _load_cells(bundle_root)]
    planned = len(rows)
    missing = [row for row in rows if row["missing"]]
    present = [row for row in rows if not row["missing"]]
    worlds = sorted({row["world"] for row in present})
    by_world = {world: [row for row in present if row["world"] == world] for world in worlds}
    rate = {world: sum(row["admitted"] for row in cells) / len(cells) for world, cells in by_world.items()}

    rng = random.Random(seed)
    point = statistics.mean(rate.values())
    low, high = _bootstrap(rng, worlds, lambda sample: statistics.mean(rate[w] for w in sample), draws)

    def world_delta(world: str) -> float | None:
        deltas = [row["delta"] for row in by_world[world] if row["admitted"]]
        return statistics.mean(deltas) if deltas else None

    deltas = {world: world_delta(world) for world in worlds}
    admitted_worlds = [world for world in worlds if deltas[world] is not None]
    if admitted_worlds:
        delta_point = statistics.mean(deltas[w] for w in admitted_worlds)
        delta_low, delta_high = _bootstrap(rng, admitted_worlds, lambda sample: statistics.mean(deltas[w] for w in sample), draws)
    else:
        delta_point, delta_low, delta_high = None, None, None

    exclusions = collections.Counter(row["exclusion"] for row in present if not row["admitted"])
    strata = sorted({row["stratum"] for row in rows})
    by_stratum = {
        stratum: {
            "admitted": sum(row["admitted"] for row in present if row["stratum"] == stratum),
            "cells": sum(1 for row in rows if row["stratum"] == stratum),
        }
        for stratum in strata
    }
    fraction = len(missing) / planned if planned else 0.0
    return {
        "schema_version": ANALYSIS_SCHEMA,
        "campaign_id": contract["campaign_id"],
        "freeze_contract_sha256": freeze["contract_sha256"],
        "predeclared": {
            "primary": freeze["primary_endpoint"],
            "secondary": freeze["secondary_endpoint"],
            "seed_handling": freeze["seed_handling"],
            "missingness_policy": freeze["missingness_policy"],
            "bootstrap": {"draws": draws, "seed": seed, "resampling_unit": "world"},
        },
        "cells": planned,
        "operational_failures": len(missing),
        "missingness_fraction": fraction,
        "eligible": fraction < missingness_ceiling,
        "primary_admission_rate": {
            "point": point,
            "ci95": [low, high],
            "worlds": len(worlds),
            "worlds_with_any_admission": sum(1 for w in worlds if rate[w] > 0),
            "worlds_admitted_on_every_seed": sum(1 for w in worlds if rate[w] == 1.0),
        },
        "secondary_reference_delta_cents": {
            "point": delta_point,
            "ci95": [delta_low, delta_high],
            "admitted_worlds": len(admitted_worlds),
            "admitted_cells": sum(row["admitted"] for row in present),
            "cells_above_reference": sum(1 for row in present if row["admitted"] and row["delta"] > 0),
        },
        "by_stratum": by_stratum,
        "exclusions": dict(exclusions),
        "reading": reading,
        "winner_claim_allowed": False,
        "inferential_model_ranking_allowed": False,
    }


def seal_analysis(bundle_root: Path | str, analysis: Mapping[str, Any]) -> dict[str, Any]:
    """Add ``reports/confirmatory_analysis.json`` to the bundle and re-seal its manifest."""

    payload = canonical_json_bytes(analysis) + b"\n"
    return add_publication_artifact(Path(bundle_root), "reports/confirmatory_analysis.json", payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, default=None, help="defaults to the contract's publication root")
    parser.add_argument("--run-root", type=Path, default=None, help="splits v1-style parser rejections from the raw text")
    parser.add_argument("--reading", required=True, help="the one-paragraph reading sealed with the numbers")
    parser.add_argument("--seal", action="store_true", help="add the analysis to the bundle manifest")
    arguments = parser.parse_args(argv)
    contract = load_contract(arguments.contract)
    freeze = json.loads(arguments.contract.with_suffix(".freeze.json").read_text(encoding="utf-8"))
    bundle = arguments.bundle or publication_root_for(contract)
    analysis = analyze(bundle, contract, freeze, reading=arguments.reading, run_root=arguments.run_root)
    if arguments.seal:
        manifest = seal_analysis(bundle, analysis)
        print(json.dumps({"sealed": True, "manifest_sha256": manifest["manifest_sha256"]}))
    print(json.dumps({k: analysis[k] for k in ("primary_admission_rate", "secondary_reference_delta_cents", "exclusions", "by_stratum")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ANALYSIS_SCHEMA",
    "DEFAULT_FREEZE_TEXT",
    "FREEZE_SCHEMA",
    "analyze",
    "classify",
    "freeze_record",
    "seal_analysis",
    "write_freeze",
]
