"""One register for every failure this family has produced.

Failure evidence otherwise scatters across per-cell results, run summaries, ad
hoc correction files, archived aborted runs, and prose in the findings
document. That makes the one question worth asking later hard to answer: for a
given incident, whose fault was it?

The register answers that. Every incident carries an `attribution`:

- `model`        the agent emitted something the family refused
- `provider`     the route failed: rate limits, 5xx, empty or rejected responses
- `environment`  our own bug, which must be fixed rather than reported
- `budget`       a declared ceiling stopped the cell
- `negotiation`  a valid episode that ended without a deal, not a defect

Attribution is derived from the sealed receipt, never from the leaderboard, and
reclassifications are recorded next to the original condition rather than
overwriting it, so a mis-typed incident stays auditable.

The generated register is committed under `evidence/`. It is read back and
checked without touching `runs/`, which is gitignored, so the checks still pass
from a clean checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes

REGISTER_SCHEMA_VERSION = "aeread.datacenter_failure_register/0.1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUN_GLOB = "datacenter_development_v2_world_panel_v1*"
DEFAULT_REGISTER_PATH = (
    REPOSITORY_ROOT / "evidence" / "datacenter_failure_register.json"
)

# How a sealed failure condition is attributed. Anything a model can trigger is
# the model's, never the provider's.
ATTRIBUTION_BY_CONDITION = {
    "rate_limit": "provider",
    "provider_5xx": "provider",
    "provider_rejected": "provider",
    "provider_contract": "provider",
    "empty_response": "provider",
    "child_provider_outcome_unknown": "provider",
    "cost_budget_exceeded": "budget",
    "family_execution_failure": "environment",
}
# A sealed failure whose message matches one of these is really a model error,
# whatever condition the scheduler recorded. Kept as a reclassification so the
# original condition stays visible.
RECLASSIFY_BY_MESSAGE = (
    (
        "digits) for integer string conversion",
        "model",
        "oversized_integer_beyond_decode_limit",
        "The model emitted an integer past CPython's 4,300 digit decode limit. "
        "The refusal is raised inside the provider call, so the scheduler "
        "recorded provider missingness for what is a model error.",
    ),
)

# Defects in the family itself, each with the commit that fixed it and the test
# that keeps it fixed. These are curated: a defect is a judgement, not a row.
KNOWN_DEFECTS = (
    {
        "id": "degenerate-counter-adoption",
        "summary": (
            "The counterparty's opening counter was the developer-optimal "
            "answer, so copying it back matched or beat the scripted baseline "
            "in 20 of 24 worlds. The panel measured copying, not negotiating."
        ),
        "detected_by": "offline probe over the generated pack",
        "severity": "invalidates_measurement",
        "status": "fixed",
        "fix": "two-sided price bands with real width",
        "regression_test": (
            "tests/test_datacenter_worlds.py::"
            "test_adopting_every_counter_is_admissible_but_never_optimal"
        ),
    },
    {
        "id": "unbounded-self-written-damages",
        "summary": (
            "Liability terms were unconstrained, so a developer could award "
            "itself delay damages worth 38x the scripted baseline, accepted by "
            "every counterparty and passing every constraint."
        ),
        "detected_by": "offline probe over the generated pack",
        "severity": "invalidates_measurement",
        "status": "fixed",
        "fix": "two-sided liability bounds tied to the quoted level",
        "regression_test": (
            "tests/test_datacenter_worlds.py::"
            "test_no_within_policy_stack_earns_unbounded_self_written_damages"
        ),
    },
    {
        "id": "forced-amendment-no-decline",
        "summary": (
            "V2 forced a land amendment with no lawful way to decline, "
            "truncating 18 cells that had already negotiated four agreements."
        ),
        "detected_by": "live panel",
        "severity": "truncates_trajectories",
        "status": "fixed",
        "fix": "explicit decline action for optional agreements",
        "regression_test": (
            "tests/test_datacenter_worlds.py::"
            "test_optional_amendment_can_be_declined_without_ending_the_episode"
        ),
    },
    {
        "id": "undeclared-decline-transition",
        "summary": (
            "The decline jump skipped to a phase the amendment offer phase "
            "never declared as a successor, so the scheduler rejected it and "
            "the cell died as family_execution_failure. Introduced by the fix "
            "for forced-amendment-no-decline."
        ),
        "detected_by": "live panel",
        "severity": "kills_cells",
        "status": "fixed",
        "fix": "declare the skip as a successor for optional agreements",
        "regression_test": (
            "tests/test_datacenter_worlds.py::"
            "test_every_transition_lands_on_a_declared_next_phase"
        ),
    },
    {
        "id": "counter-terms-unrecorded",
        "summary": (
            "Counters recorded no structured terms, so a counter was "
            "unauditable and the verbal/written diagnostic always read zero "
            "adoptions even when the hidden term had demonstrably been taken."
        ),
        "detected_by": "reading sealed evidence after a panel",
        "severity": "silent_wrong_metric",
        "status": "fixed",
        "fix": "record counter terms; diagnostic falls back to the declared package",
        "regression_test": (
            "tests/test_datacenter_worlds.py::"
            "test_verbal_written_diagnostic_counts_adopted_undisclosed_terms"
        ),
    },
    {
        "id": "coverage-counted-the-balloon",
        "summary": (
            "Debt-service coverage included the bullet principal at maturity, "
            "so every realistic term loan breached its covenant in its final "
            "month by construction."
        ),
        "detected_by": "recalibration to market magnitudes",
        "severity": "invalidates_measurement",
        "status": "fixed",
        "fix": "coverage measured on scheduled service only",
        "regression_test": (
            "tests/test_datacenter_cashflow.py::"
            "test_a_bullet_repayment_at_maturity_is_not_a_coverage_breach"
        ),
    },
    {
        "id": "model-error-booked-as-provider",
        "summary": (
            "A model emitting a several-thousand-digit integer raised inside "
            "the provider call, before the family parser ran, so 14 cells were "
            "recorded as provider missingness for a model error."
        ),
        "detected_by": "live panel",
        "severity": "mis-attributes_failure",
        "status": "fixed",
        "fix": "lift the decode limit and reject implausible terms as malformed",
        "regression_test": (
            "tests/test_datacenter_qc.py::"
            "test_an_absurd_integer_is_a_model_error_not_an_infrastructure_failure"
        ),
    },
    {
        "id": "covenant-cliff-unbuildable-from-leverage",
        "summary": (
            "The plan specifies leverage as a covenant-cliff lever. At a "
            "realistic loan-to-cost cap the commitment binds before the "
            "advance rate does, so leverage changes coverage not at all and "
            "the stratum cannot be built from it."
        ),
        "detected_by": "recalibration to market magnitudes",
        "severity": "specification_not_realisable",
        "status": "worked_around",
        "fix": "stratum rebuilt on the tenant ramp, which does move coverage",
        "regression_test": (
            "tests/test_datacenter_worlds.py::"
            "test_every_world_has_feasible_trap_and_walk_away_paths"
        ),
    },
    {
        "id": "traps-unreachable-by-counter-adopters",
        "summary": (
            "In four of six strata the counterparty's counter package is the "
            "safe one, so an agent that adopts every counter walks past the "
            "trap without ever facing the decision the stratum exists to test. "
            "Only verbal/written baits with the counter. Against the one route "
            "that transacts, which adopts counters verbatim, five of six "
            "strata are inert: it was admitted in 17 of 24 worlds and failed "
            "every verbal/written world and almost nothing else."
        ),
        "detected_by": "offline probe plus the calibrated live panel",
        "severity": "strata_do_not_test_what_they_claim",
        "status": "open",
        "fix": None,
        "regression_test": None,
    },
    {
        "id": "planning-decoupled-from-negotiation",
        "summary": (
            "Price negotiation cannot break the structural plan: in 19 of 24 "
            "worlds both adopting every counter and negotiating every price to "
            "the floor are structurally valid. The counter package is "
            "internally consistent, so cross-agreement planning is solved for "
            "free and the sequence order is fixed rather than chosen. The "
            "family currently measures distributive pricing and schema "
            "compliance far more than it measures planning."
        ),
        "detected_by": "offline probe over the generated pack",
        "severity": "under-tests_declared_capability",
        "status": "open",
        "fix": None,
        "regression_test": None,
    },
    {
        "id": "suite-needs-gitignored-artifacts",
        "summary": (
            "Fifteen datacenter_development_terms tests read artifacts under "
            "the gitignored runs/ directory and fail anywhere those local runs "
            "are absent, contradicting the R3 exit gate's requirement that the "
            "suite be reproducible from a clean checkout."
        ),
        "detected_by": "running the suite in a fresh worktree",
        "severity": "blocks_clean_checkout",
        "status": "open",
        "fix": None,
        "regression_test": None,
    },
)


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sealed(value: Mapping[str, Any]) -> dict[str, Any]:
    core = {key: item for key, item in value.items() if key != "artifact_sha256"}
    return {**core, "artifact_sha256": _sha256(core)}


def _receipt_failure(cell_root: Path) -> dict[str, Any]:
    matches = sorted(cell_root.glob("evidence/**/evaluation_receipt.json"))
    if not matches:
        return {}
    receipt = json.loads(matches[0].read_text(encoding="utf-8"))
    return receipt.get("failure") or {}


def _reclassification(message: str) -> dict[str, Any] | None:
    lowered = message.lower()
    for needle, attribution, reason, explanation in RECLASSIFY_BY_MESSAGE:
        if needle.lower() in lowered:
            return {
                "corrected_attribution": attribution,
                "reason": reason,
                "explanation": explanation,
            }
    return None


def _incident(run_id: str, path: Path) -> dict[str, Any] | None:
    result = json.loads(path.read_text(encoding="utf-8"))
    common = {
        "run_id": run_id,
        "cell_key": result.get("cell_key"),
        "model_id": result.get("model_id"),
        "stratum": result.get("stratum"),
        "case_id": result.get("case_id"),
        "receipt_sha256": result.get("receipt_sha256"),
    }
    if result.get("status") != "completed":
        condition = str(result["failure"]["failure_condition"])
        message = str(_receipt_failure(path.parent).get("message") or "")
        incident = {
            **common,
            "class": "operational",
            "condition": condition,
            "attribution": ATTRIBUTION_BY_CONDITION.get(condition, "unclassified"),
        }
        correction = _reclassification(message)
        if correction is not None:
            incident["reclassified"] = correction
        return incident

    outcome = result.get("outcome") or {}
    if outcome.get("project_completed"):
        if outcome.get("project_constraints_satisfied"):
            return None
        return {
            **common,
            "class": "excluded",
            "condition": "signed_but_failed_constraints",
            "attribution": "model",
            "default_reasons": list(outcome.get("default_reasons") or []),
        }

    reason = str(outcome.get("termination_reason"))
    violations = list(outcome.get("temporal_violations") or [])
    if reason == "invalid_action":
        return {
            **common,
            "class": "excluded",
            "condition": "invalid_action:" + ",".join(violations or ["unknown"]),
            "attribution": "model",
        }
    return {
        **common,
        "class": "no_agreement",
        "condition": reason,
        "attribution": "negotiation",
    }


def build_register(
    *,
    runs_root: Path | str = REPOSITORY_ROOT / "runs",
    run_glob: str = DEFAULT_RUN_GLOB,
) -> dict[str, Any]:
    """Collect every incident across every run of this campaign."""

    root = Path(runs_root)
    incidents: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    for run_dir in sorted(root.glob(run_glob)):
        results = sorted(run_dir.glob("live/*/result.json"))
        if not results:
            continue
        found = [
            incident
            for incident in (_incident(run_dir.name, path) for path in results)
            if incident is not None
        ]
        incidents.extend(found)
        runs.append(
            {
                "run_id": run_dir.name,
                "cells": len(results),
                "incidents": len(found),
                "superseded": run_dir.name != DEFAULT_RUN_GLOB.rstrip("*"),
            }
        )
    incidents.sort(key=lambda item: (item["run_id"], str(item["cell_key"])))

    def _tally(field: str) -> dict[str, int]:
        return dict(sorted(Counter(item[field] for item in incidents).items()))

    effective = Counter(
        item.get("reclassified", {}).get("corrected_attribution", item["attribution"])
        for item in incidents
    )
    return _sealed(
        {
            "schema_version": REGISTER_SCHEMA_VERSION,
            "campaign_id": "datacenter_development_v2_world_panel_v1",
            "runs": runs,
            "total_cells": sum(run["cells"] for run in runs),
            "total_incidents": len(incidents),
            "by_class": _tally("class"),
            "by_attribution_as_recorded": _tally("attribution"),
            "by_attribution_corrected": dict(sorted(effective.items())),
            "reclassified_incidents": sum(
                1 for item in incidents if "reclassified" in item
            ),
            "unclassified_conditions": sorted(
                {
                    item["condition"]
                    for item in incidents
                    if item["attribution"] == "unclassified"
                }
            ),
            "defects": [dict(defect) for defect in KNOWN_DEFECTS],
            "open_defects": [
                defect["id"] for defect in KNOWN_DEFECTS if defect["status"] == "open"
            ],
            "incidents": incidents,
        }
    )


def check_register(register: Mapping[str, Any]) -> list[str]:
    """Internal consistency, checkable without the gitignored run artifacts."""

    problems: list[str] = []
    if register != _sealed(register):
        problems.append("artifact digest mismatch")
    if register.get("schema_version") != REGISTER_SCHEMA_VERSION:
        problems.append("schema version differs")

    incidents: Sequence[Mapping[str, Any]] = register.get("incidents", ())
    if len(incidents) != register.get("total_incidents"):
        problems.append("total_incidents disagrees with the incident list")
    if register.get("unclassified_conditions"):
        problems.append(
            "unclassified failure conditions: "
            + ", ".join(register["unclassified_conditions"])
        )

    recorded = Counter(item["attribution"] for item in incidents)
    if dict(sorted(recorded.items())) != register.get("by_attribution_as_recorded"):
        problems.append("attribution tally disagrees with the incident list")

    for defect in register.get("defects", ()):
        if defect["status"] in {"fixed", "worked_around"} and not defect.get(
            "regression_test"
        ):
            problems.append(f"{defect['id']}: closed without a regression test")
        if defect["status"] == "open" and defect.get("fix"):
            problems.append(f"{defect['id']}: open but carries a fix")
    return problems


def render_register(register: Mapping[str, Any]) -> str:
    lines = [
        "# Data-center family failure register",
        "",
        f"{register['total_incidents']} incidents across {register['total_cells']} "
        f"cells in {len(register['runs'])} runs of `{register['campaign_id']}`.",
        "",
        "Attribution answers the question worth asking later: whose fault was "
        "it? Anything a model can trigger is the model's, never the provider's.",
        "",
        "| Attribution | As recorded | After reclassification |",
        "|---|---:|---:|",
    ]
    recorded = register["by_attribution_as_recorded"]
    corrected = register["by_attribution_corrected"]
    for key in sorted(set(recorded) | set(corrected)):
        lines.append(f"| {key} | {recorded.get(key, 0)} | {corrected.get(key, 0)} |")
    lines += [
        "",
        f"{register['reclassified_incidents']} incidents were recorded under one "
        "attribution and belong to another. The original condition is kept "
        "beside the correction.",
        "",
        "## Runs",
        "",
        "| Run | Cells | Incidents | Superseded |",
        "|---|---:|---:|---|",
    ]
    for run in register["runs"]:
        lines.append(
            f"| `{run['run_id']}` | {run['cells']} | {run['incidents']} | "
            f"{'yes' if run['superseded'] else 'no'} |"
        )
    lines += ["", "## Defects", "", "| Defect | Severity | Status | Regression test |", "|---|---|---|---|"]
    for defect in register["defects"]:
        test = defect["regression_test"]
        short = test.split("::")[-1] if test else "none"
        lines.append(
            f"| {defect['id']} | {defect['severity']} | {defect['status']} | `{short}` |"
        )
    if register["open_defects"]:
        lines += ["", "Open: " + ", ".join(register["open_defects"]) + "."]
    lines.append("")
    return "\n".join(lines)


def write_register(
    *,
    runs_root: Path | str = REPOSITORY_ROOT / "runs",
    register_path: Path | str = DEFAULT_REGISTER_PATH,
) -> dict[str, Any]:
    register = build_register(runs_root=runs_root)
    problems = check_register(register)
    if problems:
        raise ValueError("register failed its own checks: " + "; ".join(problems))
    path = Path(register_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(register, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.with_suffix(".md").write_text(render_register(register), encoding="utf-8")
    return register


def load_register(register_path: Path | str = DEFAULT_REGISTER_PATH) -> dict[str, Any]:
    return json.loads(Path(register_path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=REPOSITORY_ROOT / "runs")
    parser.add_argument("--register", type=Path, default=DEFAULT_REGISTER_PATH)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.check:
        problems = check_register(load_register(arguments.register))
        print(canonical_json_bytes({"ok": not problems, "problems": problems}).decode("utf-8"))
        return 0 if not problems else 1
    register = write_register(
        runs_root=arguments.runs_root, register_path=arguments.register
    )
    print(
        canonical_json_bytes(
            {
                key: register[key]
                for key in (
                    "total_cells",
                    "total_incidents",
                    "by_class",
                    "by_attribution_corrected",
                    "reclassified_incidents",
                    "open_defects",
                )
            }
        ).decode("utf-8")
    )
    return 0


__all__ = [
    "DEFAULT_REGISTER_PATH",
    "KNOWN_DEFECTS",
    "build_register",
    "check_register",
    "load_register",
    "main",
    "render_register",
    "write_register",
]


if __name__ == "__main__":
    raise SystemExit(main())
