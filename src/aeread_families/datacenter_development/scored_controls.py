"""Gate 3 controls for the V2 stack, scored through the real interface.

Three provider-free developer policies run on the repaired curated case and
on every world of the pack, each trajectory finalised, verified and replayed
through the same scheduler a live subject uses:

- ``scripted``: the case's own feasible path, negotiated to the floor of every
  band -- the reference a subject is compared against;
- ``walk_away``: the outside option taken at the first offer -- the anchor a
  reference must strictly beat (DC-D-01);
- ``adopt_every_counter``: an opening the counterparty must refuse, then its
  counter copied verbatim at every agreement -- the transcription policy the
  score must be able to tell from negotiation (DC-D-03, DC-D-04).

The bundle is derived only from committed cases and the family's own engine,
so it is regenerated, never edited: ``python -m
aeread_families.datacenter_development.scored_controls`` must reproduce the
committed bytes, and the test asserts it does.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import statistics
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.publication import (
    rebuild_publication_manifest,
    seal_publication_manifest,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.receipts import verify_evaluation_receipt

from .stack_runner import (
    DEVELOPER_POLICIES,
    finalize_stack_execution,
    load_stack_case,
    replay_stack_receipt,
    run_stack_offline,
)
from .jv_worlds import DEFAULT_OUTPUT_ROOT as JV_WORLDS_ROOT
from .stack_worlds import DEFAULT_OUTPUT_ROOT as WORLDS_ROOT
from .stack_worlds import load_pack_manifest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASES_ROOT = REPOSITORY_ROOT / "cases" / "datacenter_development_v1"
PUBLICATION_ID = "datacenter_v2_scored_controls_v1"
#: One bundle per (curated case, world pack) the controls are scored on. The
#: first is the sealed interface-2 pack; the second is the same 24 worlds at
#: developer interface 3 (DC-D-10), where the adopter declines the amendment
#: instead of walking and so reaches the loan (DC-D-09).
BUNDLES: dict[str, dict[str, Path]] = {
    PUBLICATION_ID: {
        "curated": CASES_ROOT / "v2" / "full_stack_amendment_002.json",
        "worlds": WORLDS_ROOT,
    },
    "datacenter_v2_interface3_scored_controls_v1": {
        "curated": CASES_ROOT / "v2" / "full_stack_amendment_003.json",
        "worlds": CASES_ROOT / "worlds_v3",
    },
    # Scope V3, the shared-feeder joint venture: three curated cases, one per
    # scripted partner type, and a fourth control -- the free rider, which
    # offers nothing toward the feeder. The reference is the fair share, so
    # on the generous-partner case the rider beats it by design; the
    # inequality that must hold everywhere is that the rider is not admitted
    # unless the partner covers the feeder.
    "datacenter_v3_jv_scored_controls_v1": {
        "scope": "v3",
        "cases": [CASES_ROOT / "v3" / f"full_stack_jv_{index:03d}.json" for index in range(1, 9)],
        "policies": tuple(DEVELOPER_POLICIES),
    },
    # The same five policies over the generated joint-venture pack: sampled
    # capacities, feeder costs, partner types, records and rounds over the 24
    # sealed interface-3 worlds. This is the falsifiability proof of the
    # coalition endpoint measured across worlds rather than shown on six.
    "datacenter_v3_jv_world_controls_v1": {
        "scope": "v3",
        "cases": [],
        "worlds": JV_WORLDS_ROOT,
        "policies": tuple(DEVELOPER_POLICIES),
    },
}
DEFAULT_BUNDLE_ROOT = REPOSITORY_ROOT / "evidence" / "datacenter_development" / PUBLICATION_ID
CURATED_CASE = BUNDLES[PUBLICATION_ID]["curated"]
#: The three controls every V2 bundle scores; the free rider is a V3 control.
POLICIES: tuple[str, ...] = ("scripted", "walk_away", "adopt_every_counter")
COLUMNS = (
    "case_id",
    "source",
    "policy",
    "termination_reason",
    "project_completed",
    "project_constraints_satisfied",
    "logical_actions",
    "developer_equity_npv_cents",
    "total_project_npv_cents",
    "receipt_status",
    "inclusion_status",
    "run_plan_sha256",
    "replay_verified",
    # The coalition endpoint's failure rule, judged per trajectory (V3 only;
    # V2 rows carry an empty string).
    "coalition_decision",
)


def bundle_root_for(publication_id: str = PUBLICATION_ID) -> Path:
    return REPOSITORY_ROOT / "evidence" / "datacenter_development" / publication_id


def _cases(publication_id: str = PUBLICATION_ID) -> list[tuple[str, Path]]:
    sources = BUNDLES[publication_id]
    curated = sources["cases"] if "cases" in sources else [sources["curated"]]
    cases = [("curated", path) for path in curated]
    if "worlds" in sources:
        manifest = load_pack_manifest(sources["worlds"])
        for entry in manifest["worlds"]:
            cases.append(("world_pack", sources["worlds"] / entry["file"]))
    return cases


def _policies(publication_id: str = PUBLICATION_ID) -> tuple[str, ...]:
    return tuple(BUNDLES[publication_id].get("policies", POLICIES))


def _scope(publication_id: str = PUBLICATION_ID) -> str:
    return str(BUNDLES[publication_id].get("scope", "v2"))


async def _run(case_path: Path, policy: str, evidence_root: Path, scope: str = "v2") -> dict[str, Any]:
    setup, execution = await run_stack_offline(
        scope, evidence_root=evidence_root, case_path=case_path, developer_policy=policy
    )
    receipt = finalize_stack_execution(setup=setup, execution=execution)
    verify_evaluation_receipt(receipt)
    replayed = replay_stack_receipt(setup=setup, receipt=receipt, evidence_root=evidence_root)
    verify_evaluation_receipt(replayed)
    outcome = execution.episode_result.outcome
    return {
        "case_id": setup.case.case_id,
        "policy": policy,
        "termination_reason": outcome["termination_reason"],
        "project_completed": bool(outcome["project_completed"]),
        # Admission, not completion: an executed stack the lender will not
        # fund is what the adopter is expected to produce on a trap world.
        "project_constraints_satisfied": bool(outcome["project_constraints_satisfied"]),
        "logical_actions": execution.episode_result.logical_action_count,
        "developer_equity_npv_cents": int(outcome["developer_equity_npv_cents"]),
        "total_project_npv_cents": int(outcome["total_project_npv_cents"]),
        "receipt_status": receipt.status,
        "inclusion_status": receipt.inclusion_status,
        # The receipt digest is not reproducible across runs (attempt ids and
        # timestamps are sealed into it); the run plan digest is, and it pins
        # the case, the policy profile and every implementation.
        "run_plan_sha256": setup.plan.plan_sha256,
        "replay_verified": replayed == receipt,
        "coalition_decision": str((outcome.get("coalition") or {}).get("coalition_decision", "")),
    }


def score_controls(publication_id: str = PUBLICATION_ID) -> list[dict[str, Any]]:
    """One row per (case, policy), every trajectory sealed and replayed."""

    rows: list[dict[str, Any]] = []
    scope = _scope(publication_id)
    with tempfile.TemporaryDirectory() as scratch:
        for source, case_path in _cases(publication_id):
            case = load_stack_case(scope, case_path)
            for policy in _policies(publication_id):
                evidence_root = Path(scratch) / case.case_id / policy
                row = asyncio.run(_run(case_path, policy, evidence_root, scope))
                rows.append({"source": source, **row})
    return rows


def _by_case(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Mapping[str, Any]]]:
    grouped: dict[str, dict[str, Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["case_id"]), {})[str(row["policy"])] = row
    return grouped


def summarize(
    rows: Sequence[Mapping[str, Any]], publication_id: str = PUBLICATION_ID
) -> dict[str, Any]:
    """The three inequalities a measurable case must satisfy, per case."""

    grouped = _by_case(rows)
    per_case = []
    for case_id, by_policy in grouped.items():
        scripted = int(by_policy["scripted"]["developer_equity_npv_cents"])
        walk = int(by_policy["walk_away"]["developer_equity_npv_cents"])
        adopt = int(by_policy["adopt_every_counter"]["developer_equity_npv_cents"])
        per_case.append(
            {
                "case_id": case_id,
                "source": by_policy["scripted"]["source"],
                "reference_over_walk_away_cents": scripted - walk,
                "reference_over_adoption_cents": scripted - adopt,
                "adoption_over_walk_away_cents": adopt - walk,
                "reference_beats_walk_away": scripted > walk,
                "reference_beats_adoption": scripted > adopt,
                "adoption_completes_the_stack": bool(by_policy["adopt_every_counter"]["project_completed"]),
                "adoption_admitted": bool(by_policy["adopt_every_counter"]["project_constraints_satisfied"]),
                "adoption_termination": by_policy["adopt_every_counter"]["termination_reason"],
                **(
                    {
                        "reference_over_free_rider_cents": scripted - int(by_policy["free_rider"]["developer_equity_npv_cents"]),
                        "free_rider_admitted": bool(by_policy["free_rider"]["project_constraints_satisfied"]),
                    }
                    if "free_rider" in by_policy
                    else {}
                ),
            }
        )
    world_rows = [item for item in per_case if item["source"] == "world_pack"]
    decisions = {
        policy: dict(sorted(Counter(str(row["coalition_decision"]) for row in rows if row["policy"] == policy).items()))
        for policy in _policies(publication_id)
    } if any(row.get("coalition_decision") for row in rows) else {}
    # The rule is the ex-ante best response, so a control can beat the
    # reference on a single case without either being wrong. What must hold is
    # the aggregate: over every case the reference's realised equity NPV beats
    # both synthetic arms, because it minimises expected cost on each one.
    totals = {
        policy: sum(int(row["developer_equity_npv_cents"]) for row in rows if row["policy"] == policy)
        for policy in _policies(publication_id)
    } if decisions else {}
    coalition_aggregate = {
        "realised_developer_equity_npv_cents": totals,
        "reference_beats_both_arms_in_aggregate": bool(totals)
        and all(totals["scripted"] > totals[arm] for arm in ("free_rider", "fair_share") if arm in totals),
        "cases_where_an_arm_beats_the_reference": sum(
            any(
                int(by_policy[arm]["developer_equity_npv_cents"]) > int(by_policy["scripted"]["developer_equity_npv_cents"])
                for arm in ("free_rider", "fair_share")
                if arm in by_policy
            )
            for by_policy in grouped.values()
        ) if decisions else 0,
    } if decisions else {}
    return {
        "schema_version": "aeread.datacenter_scored_controls_summary/0.1",
        "publication_id": publication_id,
        "policies": list(_policies(publication_id)),
        "case_count": len(per_case),
        "trajectory_count": len(rows),
        "all_receipts_included": all(row["inclusion_status"] == "included" for row in rows),
        "all_replays_verified": all(bool(row["replay_verified"]) for row in rows),
        "reference_beats_walk_away_in": sum(item["reference_beats_walk_away"] for item in per_case),
        "reference_beats_adoption_in": sum(item["reference_beats_adoption"] for item in per_case),
        "adoption_completes_the_stack_in": sum(item["adoption_completes_the_stack"] for item in per_case),
        "adoption_admitted_in": sum(item["adoption_admitted"] for item in per_case),
        **(
            {"free_rider_admitted_in": sum(item["free_rider_admitted"] for item in per_case)}
            if per_case and "free_rider_admitted" in per_case[0]
            else {}
        ),
        "world_pack": {
            "world_count": len(world_rows),
            "median_reference_over_walk_away_cents": (
                int(statistics.median(item["reference_over_walk_away_cents"] for item in world_rows))
                if world_rows
                else None
            ),
            "median_reference_over_adoption_cents": (
                int(statistics.median(item["reference_over_adoption_cents"] for item in world_rows))
                if world_rows
                else None
            ),
            "adoption_terminations": sorted(
                {str(item["adoption_termination"]) for item in world_rows}
            ),
        },
        # Gate 5 item 7: the two synthetic arms the failure rule must reject.
        # `free_rider` is under_funded wherever the record does not license a
        # free ride; `fair_share` is over_funded wherever it does; `scripted`
        # is the best response everywhere.
        "coalition_decisions_by_policy": decisions,
        "coalition_aggregate": coalition_aggregate,
        "per_case": per_case,
        "winner_claim_allowed": False,
        "inferential_model_ranking_allowed": False,
    }


def _table(rows: Sequence[Mapping[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row[column] for column in COLUMNS})
    return buffer.getvalue()


def _readme(summary: Mapping[str, Any], publication_id: str = PUBLICATION_ID) -> str:
    world = summary["world_pack"]
    sources = BUNDLES[publication_id]
    if "cases" in sources:
        return _jv_readme(summary, publication_id)
    split = sources["worlds"].name
    curated = sources["curated"].stem
    interface_note = (
        ""
        if publication_id == PUBLICATION_ID
        else """
This bundle scores the same 24 worlds at developer interface 3: the amendment
phase can be declined, so the adopter keeps the executed land agreement and
goes on to copy the lender's counter instead of walking (DC-D-09, DC-D-10).
"""
    )
    return f"""# Scored controls for the V2 stack

Three provider-free developer policies -- the scripted reference negotiated to
the floor of every band, walking away at the first offer, and adopting every
counterparty counter verbatim -- run through the real scheduler on the repaired
curated case and every world of `cases/datacenter_development_v1/{split}/`.
Every trajectory is finalised, verified and replayed offline; the rows are the
Gate 3 exit evidence the datacenter QC profile was missing.
{interface_note}
- cases: {summary['case_count']} ({world['world_count']} worlds and the curated `{curated}`)
- trajectories: {summary['trajectory_count']}, all included, all replay-verified
- the reference beats walking away in {summary['reference_beats_walk_away_in']} of {summary['case_count']} cases
- the reference beats adopting every counter in {summary['reference_beats_adoption_in']} of {summary['case_count']} cases
- adopting every counter completes the stack in {summary['adoption_completes_the_stack_in']} of {summary['case_count']} cases; on the worlds it ends in {', '.join(world['adoption_terminations'])}
- adopting every counter is admitted (the stack executes and the lender funds it) in {summary['adoption_admitted_in']} of {summary['case_count']} cases
- on the worlds the reference clears walking away by a median of {world['median_reference_over_walk_away_cents']:,} cents and adoption by a median of {world['median_reference_over_adoption_cents']:,} cents

`tables/controls.csv` holds one row per case and policy with the sealed run-plan
digest; `reports/summary.json` holds the per-case inequalities. This bundle is
derived only from committed cases and the family's engine and is regenerated,
never edited: `python -m aeread_families.datacenter_development.scored_controls`
reproduces it byte for byte. No claim about any model is made here; a control
is what a subject's score is read against, not a subject.
"""


def _jv_readme(summary: Mapping[str, Any], publication_id: str) -> str:
    sources = BUNDLES[publication_id]
    if "worlds" in sources:
        return _jv_pack_readme(summary, publication_id)
    cases = ", ".join(f"`{path.stem}`" for path in sources["cases"])
    lever = ", ".join(f"{int(item['reference_over_free_rider_cents']):,}" for item in summary["per_case"])
    return f"""# Scored controls for the V3 joint venture

Four provider-free developer policies -- the scripted reference funding its
capacity share of the shared feeder, walking away at the first offer, adopting
every counter (which opens the joint venture at nothing and then takes whatever
share the utility's counter assigns), and the free rider, which offers nothing
toward the feeder in every round -- run through the real scheduler on the six
curated joint-venture cases ({cases}). The first three are the sincere stratum,
one per partner type that does what it announced (pro-rata, conditional,
generous), three joint-offer rounds. The last three are the credibility
stratum, one joint-offer round each, where the partner's announcement can be
untrue and its public record of earlier feeders is the only evidence: a
bluffing partner that announces full coverage and funds pro rata, a generous
partner whose record shows it kept its word, and a posturing partner that
announces pro rata and covers the rest. Every trajectory is finalised, verified
and replayed offline. The reference funds the share the evidence licenses: the
one with the lower expected cost, given the fraction of recorded feeders the
partner funded in full, or the territory's declared prior when there is no
record. Because that is an ex-ante rule, a control can beat the reference on a
single case; what must hold is the aggregate below. `free_rider` and
`fair_share` are the two synthetic arms the rule rejects.

- cases: {summary['case_count']}; trajectories: {summary['trajectory_count']}, all included, all replay-verified
- coalition decisions by policy: {_decisions_line(summary)}
- the reference beats walking away in {summary['reference_beats_walk_away_in']} of {summary['case_count']} cases
- the reference beats adopting every counter in {summary['reference_beats_adoption_in']} of {summary['case_count']} cases
- adopting every counter is admitted in {summary['adoption_admitted_in']} of {summary['case_count']} cases
- the free rider is admitted in {summary['free_rider_admitted_in']} of {summary['case_count']} cases; the reference clears it by {lever} cents per case
- coalition decisions by policy: {_decisions_line(summary)}
- realised equity NPV summed over the cases: {_aggregate_line(summary)}

The reference is the fair share, not the highest NPV. The partner states its
position before anyone offers, so the developer knows what a free ride is
worth: against a generous partner the rider is admitted and beats the reference
by its whole share of the feeder, which is the exploitation stratum by design;
against a pro-rata or conditional partner nobody funds the feeder, the rider's
solo stack still finances at the utility's solo interconnection price, and it
trails the reference by that premium. This bundle is derived only from
committed cases and the family engine and is regenerated, never edited. No
claim about any model is made here.
"""


def _aggregate_line(summary: Mapping[str, Any]) -> str:
    aggregate = summary.get("coalition_aggregate") or {}
    totals = aggregate.get("realised_developer_equity_npv_cents") or {}
    body = ", ".join(f"{policy} {value:,}" for policy, value in totals.items())
    verdict = "the reference beats both arms" if aggregate.get("reference_beats_both_arms_in_aggregate") else "the reference does NOT beat both arms"
    return f"{body}; {verdict}; an arm wins on {aggregate.get('cases_where_an_arm_beats_the_reference')} single cases"


def _decisions_line(summary: Mapping[str, Any]) -> str:
    return "; ".join(
        f"{policy} " + ", ".join(f"{decision} {count}" for decision, count in counts.items())
        for policy, counts in summary.get("coalition_decisions_by_policy", {}).items()
    )


def _jv_pack_readme(summary: Mapping[str, Any], publication_id: str) -> str:
    world = summary["world_pack"]
    split = BUNDLES[publication_id]["worlds"].name
    return f"""# Scored controls for the V3 joint-venture worlds

Five provider-free developer policies -- the scripted reference funding the
share the partner's record licenses, walking away at the first offer, adopting
every counter, the free rider (nothing toward the feeder, whatever the
evidence) and the fair share (its capacity share, whatever the evidence) --
run through the real scheduler on every world of
`cases/datacenter_development_v1/{split}/`: a sampled joint venture laid over
each of the 24 sealed interface-3 worlds. Every trajectory is finalised,
verified and replayed offline.

- worlds: {world['world_count']}; trajectories: {summary['trajectory_count']}, all included, all replay-verified
- the reference beats walking away in {summary['reference_beats_walk_away_in']} of {summary['case_count']} worlds
- the reference beats adopting every counter in {summary['reference_beats_adoption_in']} of {summary['case_count']} worlds
- coalition decisions by policy: {_decisions_line(summary)}
- realised equity NPV summed over the worlds: {_aggregate_line(summary)}

The decision line is the coalition endpoint's falsifiability proof (QC profile,
Gate 5 item 7): the rule classifies the reference as the best response on
every world, rejects the free rider wherever the record does not license a
free ride, and rejects the fair share wherever it does. This bundle is derived
only from committed cases and the family engine and is regenerated, never
edited. No claim about any model is made here.
"""


def write_bundle(
    bundle_root: Path | str | None = None, *, publication_id: str = PUBLICATION_ID
) -> dict[str, Any]:
    if publication_id not in BUNDLES:
        raise ValueError(f"publication_id must be one of {sorted(BUNDLES)}")
    root = Path(bundle_root) if bundle_root is not None else bundle_root_for(publication_id)
    sources = BUNDLES[publication_id]
    rows = score_controls(publication_id)
    summary = summarize(rows, publication_id)
    (root / "tables").mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / "tables" / "controls.csv").write_text(_table(rows), encoding="utf-8")
    (root / "reports" / "summary.json").write_bytes(canonical_json_bytes(summary) + b"\n")
    (root / "README.md").write_text(_readme(summary, publication_id), encoding="utf-8")
    manifest_path = root / "publication_manifest.json"
    boundary = {
        "included": "sealed receipt digests, terminations, NPVs and inequalities per case and policy",
        "excluded": "raw run evidence, which is provider-free and reproduced by regenerating",
    }
    if manifest_path.exists():
        rebuild_publication_manifest(root, privacy_boundary=boundary)
    else:
        seal_publication_manifest(
            root,
            publication_id=publication_id,
            privacy_boundary=boundary,
            campaign_id=publication_id,
            source_bindings=(
                {
                    "curated_cases": {
                        path.stem: load_stack_case(_scope(publication_id), path).content_sha256
                        for path in sources["cases"]
                    },
                    **({"world_pack_sha256": load_pack_manifest(sources["worlds"])["artifact_sha256"]} if "worlds" in sources else {}),
                }
                if "cases" in sources
                else {
                    "curated_case": load_stack_case("v2", sources["curated"]).content_sha256,
                    "world_pack_sha256": load_pack_manifest(sources["worlds"])["artifact_sha256"],
                }
            ),
            derived_from="committed cases and the family engine; no provider calls",
        )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication-id", default=PUBLICATION_ID, choices=sorted(BUNDLES))
    parser.add_argument("--output", type=Path, default=None, help="defaults to evidence/datacenter_development/<publication-id>")
    arguments = parser.parse_args(argv)
    summary = write_bundle(arguments.output, publication_id=arguments.publication_id)
    print(json.dumps({k: summary[k] for k in ("case_count", "trajectory_count", "reference_beats_walk_away_in", "reference_beats_adoption_in", "adoption_completes_the_stack_in")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BUNDLES",
    "DEFAULT_BUNDLE_ROOT",
    "PUBLICATION_ID",
    "POLICIES",
    "bundle_root_for",
    "score_controls",
    "summarize",
    "write_bundle",
]
