"""Lower controls and the declared beatability rule for Refund V2.5 (QC Gate 3).

This is a new module on purpose. Every V2.5 module whose bytes a run plan
pins (``v2_5_runner``, ``v2_5_policy``, ``v2_5_measurement``,
``v2_5_branches``, ``v2_4_cases``, ``v2_4_reference``,
``v2_5_collection_budget``, ``v2_5_seat_cases``, ``v2_5_seat_design_v3``,
``v2_5_seat_extension_v4``, ``v2_5_seat_extension_v5``,
``v2_5_payment_units_v51``) is left byte-identical, so no reference plan
identity moves. ``v2_5_release`` is reused, not edited.

The rule below was declared and committed on 2026-10-13 before any control
was executed on any case. A changed threshold or clause is a new ``RULE_ID``;
the verdict under the old identity stays recorded.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import audit_family_receipt

from . import v2_5_release as release
from .v2_5_branches import BranchSpec, public_inputs

RULE_ID = "refund_v25_beatability/1"
CONTROLS_VERSION = "refund_v25_lower_controls/1"
SCREEN_SEED = 301
REFERENCE = "reference"
RANDOM_SEEDS = (0, 1, 2)

# Lower controls declared per active seat. The reference is the release's
# deterministic profile for that seat; every other seat stays the release's
# scripted counterpart, exactly as in a controlled comparison run.
CONTROLS: Mapping[str, tuple[str, ...]] = {
    "policy": ("refuse_empty", "noop_null_resolution", "naive_full_refund",
               *(f"random_legal_{seed}" for seed in RANDOM_SEEDS)),
    "customer": ("refuse_empty", "naive_overdisclose", "naive_first_record"),
    "intake": ("refuse_empty", "naive_first_sorted"),
    "payments": ("refuse_empty", "naive_no_mutation"),
}

CONTROL_DESCRIPTIONS: Mapping[str, str] = {
    "refuse_empty": "Returns an empty JSON object on every turn: no decision at all.",
    "noop_null_resolution": "Policy, first turn: submits the null resolution (unresolved, no remedy, no_mutation, amount 0, no payment, payer none, rule NO_DECISION) without collecting a fact.",
    "naive_full_refund": "Policy, first turn: submits a full refund (eligible, full_refund, execute_refund, item_net_price + allocated_tax, original_payment, execute, seller) citing the first public full-refund rule ID, without collecting a fact.",
    "random_legal": "Policy, seeded: requests a uniformly random nonempty subset (at most 3) of the facts the public branch specification lists as pending; once none are pending, submits a uniformly random canonical resolution (amount from {0, item_net_price, item_net_price + allocated_tax}, rule ID from the public catalogue, reason_code = policy_basis) that satisfies the environment's legality guard. Draws are keyed by seed and the canonical observation.",
    "naive_overdisclose": "Customer: the reference at claim and confirmation; at disclosure reveals every private fact it holds instead of the requested ones.",
    "naive_first_record": "Customer: the reference at claim and confirmation; at disclosure reveals exactly the requested IDs, each valued from the flat private_facts map or else the first listed record for that fact, ignoring document, revision and revocation.",
    "naive_first_sorted": "Intake: requests the first min(3, n) undisclosed available fact IDs in sorted order, ignoring the routing plan and collection contract.",
    "naive_no_mutation": "Payments: always no_mutation with amount 0, method none and no allocations, echoing proposal, idempotency and snapshot IDs; never reads the ledger amounts.",
}


@dataclass(frozen=True, slots=True)
class BeatabilityRule:
    """The reference must beat every lower control on every public cohort.

    For each screened seat and cohort, and for each declared control K:

    * B1: mean(reference end_to_end) - mean(K end_to_end) >= end_to_end_margin.
    * B2: mean(reference policy_semantic) - mean(K policy_semantic)
      >= policy_semantic_margin, for seats in ``policy_semantic_seats`` only.
      Other seats do not produce the policy resolution, so their
      policy_semantic is the scripted policy counterpart's.
    * B3: the share of cases where K's end_to_end reaches the reference's
      (K >= reference on that case) is at most ``max_reach_share``. With fewer
      than ten cases this allows no reached case at all.

    A cohort passes for a seat only if every clause holds for every control.
    A failing cohort is a finding about the cohort (a control without the
    judgment reaches the reference), never a reason to retune the rule.
    """

    rule_id: str
    end_to_end_margin: float
    policy_semantic_margin: float
    max_reach_share: float
    policy_semantic_seats: tuple[str, ...]


RULE = BeatabilityRule(
    rule_id=RULE_ID,
    end_to_end_margin=0.50,
    policy_semantic_margin=0.25,
    max_reach_share=0.10,
    policy_semantic_seats=("policy",),
)

_TOLERANCE = 1e-9


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return math.fsum(values) / len(values)


def evaluate_rule(rows: Iterable[Mapping[str, Any]], rule: BeatabilityRule = RULE) -> dict[str, Any]:
    """Apply ``rule`` to per-case rows with seat, cohort, control, case_id and leaves.

    Raises when a group has no reference, no control, a duplicated case or a
    control whose case set differs from the reference's: a screen that cannot
    be compared must not produce a verdict.
    """
    groups: dict[tuple[str, str], dict[str, dict[str, Mapping[str, Any]]]] = {}
    for row in rows:
        cases = groups.setdefault((row["seat"], row["cohort"]), {}).setdefault(row["control"], {})
        if row["case_id"] in cases:
            raise ValueError(f"duplicate case {row['case_id']} for {row['seat']}/{row['cohort']}/{row['control']}")
        cases[row["case_id"]] = row
    if not groups:
        raise ValueError("no rows to evaluate")
    verdicts = []
    for (seat, cohort), by_control in sorted(groups.items()):
        reference = by_control.get(REFERENCE)
        if not reference:
            raise ValueError(f"{seat}/{cohort}: no reference rows")
        controls = sorted(name for name in by_control if name != REFERENCE)
        if not controls:
            raise ValueError(f"{seat}/{cohort}: no control rows")
        case_ids = sorted(reference)
        n = len(case_ids)
        ref_e2e = _mean(reference[c]["end_to_end"] for c in case_ids)
        ref_sem = _mean(reference[c]["policy_semantic"] for c in case_ids)
        results = []
        for name in controls:
            rows_k = by_control[name]
            if set(rows_k) != set(case_ids):
                raise ValueError(f"{seat}/{cohort}/{name}: case set differs from the reference")
            e2e_gap = ref_e2e - _mean(rows_k[c]["end_to_end"] for c in case_ids)
            reached = sorted(c for c in case_ids if rows_k[c]["end_to_end"] >= reference[c]["end_to_end"])
            share = len(reached) / n
            clauses = {
                "B1_end_to_end_margin": {"value": round(e2e_gap, 6), "threshold": rule.end_to_end_margin,
                                         "holds": e2e_gap >= rule.end_to_end_margin - _TOLERANCE},
                "B3_reach_share": {"value": round(share, 6), "threshold": rule.max_reach_share,
                                   "holds": share <= rule.max_reach_share + _TOLERANCE, "reached_case_ids": reached},
            }
            if seat in rule.policy_semantic_seats:
                sem_gap = ref_sem - _mean(rows_k[c]["policy_semantic"] for c in case_ids)
                clauses["B2_policy_semantic_margin"] = {"value": round(sem_gap, 6), "threshold": rule.policy_semantic_margin,
                                                        "holds": sem_gap >= rule.policy_semantic_margin - _TOLERANCE}
            clauses = dict(sorted(clauses.items()))
            results.append({"control": name, "holds": all(c["holds"] for c in clauses.values()), "clauses": clauses})
        failing = [r["control"] for r in results if not r["holds"]]
        verdicts.append({"seat": seat, "cohort": cohort, "cases": n, "passes": not failing,
                         "failing_controls": failing, "controls": results})
    return {
        "rule": asdict(rule),
        "passes": all(v["passes"] for v in verdicts),
        "failing_cohorts": [{"seat": v["seat"], "cohort": v["cohort"], "failing_controls": v["failing_controls"]}
                            for v in verdicts if not v["passes"]],
        "verdicts": verdicts,
    }


# ---------------------------------------------------------------------------
# Control policies. Each reads only its seat's observation, as a model would.
# ---------------------------------------------------------------------------

_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
CONTROL_REVISION = f"{CONTROLS_VERSION}@{_SOURCE_SHA256[:16]}"
# Controls that claim to emit only actions the environment accepts.
LEGAL_ONLY = tuple(f"random_legal_{seed}" for seed in RANDOM_SEEDS)
# Not a lower control: delegates the active seat to the reference profile.
# Used only to show that a control matching the reference fails the rule.
COPY_REFERENCE = "copy_reference"
CANONICAL = {
    "eligibility": ("eligible", "ineligible", "unresolved"),
    "remedy": ("full_refund", "partial_refund", "none"),
    "workflow": ("execute_refund", "no_mutation", "request_evidence", "identity_review",
                 "seller_review", "payment_review", "return_and_inspect"),
    "refund_method": ("original_payment", "none"),
    "payment_mutation": ("execute", "none"),
    "return_shipping_payer": ("seller", "customer", "none"),
}
_DELEGATE = object()


def _public_contract(observation: Mapping[str, Any]) -> tuple[BranchSpec, dict, float, float]:
    contract = str(observation["policy_contract"])
    spec = re.search(r"^Public branch specification JSON: (.+)$", contract, re.MULTILINE)
    money = re.search(r"item_net_price = ([0-9]+(?:\.[0-9]+)?); allocated_tax = ([0-9]+(?:\.[0-9]+)?)", contract)
    if spec is None or money is None:
        raise ValueError("policy observation lacks the public branch specification or financial inputs")
    price, tax = float(money.group(1)), float(money.group(2))
    return BranchSpec.from_dict(json.loads(spec.group(1))), public_inputs(price, tax), price, tax


def _draw(key: bytes, label: str, n: int) -> int:
    """Uniform-enough index from SHA-256; independent of Python's RNG versions."""
    return int.from_bytes(hashlib.sha256(key + b"\x00" + label.encode()).digest()[:8], "big") % n


def _resolution(**fields: Any) -> dict[str, Any]:
    return {"decision": "submit_resolution", "requested_fact_ids": [], "proposal_id": "proposal_1", **fields}


def _policy_action(control: str, observation: Mapping[str, Any]) -> dict[str, Any]:
    spec, public, price, tax = _public_contract(observation)
    bases = [branch.outcome.basis for branch in spec.branches]
    if control == "noop_null_resolution":
        return _resolution(eligibility="unresolved", remedy="none", workflow="no_mutation", amount=0.0,
                           refund_method="none", payment_mutation="none", return_shipping_payer="none",
                           policy_basis="NO_DECISION", reason_code="NO_DECISION")
    if control == "naive_full_refund":
        basis = next((b.outcome.basis for b in spec.branches if b.outcome.remedy == "full_refund"), bases[0])
        return _resolution(eligibility="eligible", remedy="full_refund", workflow="execute_refund",
                           amount=round(price + tax, 2), refund_method="original_payment", payment_mutation="execute",
                           return_shipping_payer="seller", policy_basis=basis, reason_code=basis)
    if control.startswith("random_legal_"):
        seed = int(control.rsplit("_", 1)[1])
        key = canonical_json_bytes({"controls_version": CONTROLS_VERSION, "seed": seed, "observation": observation})
        pending = list(spec.pending(dict(observation["revealed_facts"]), public))
        if pending:
            size = 1 + _draw(key, "batch_size", min(3, len(pending)))
            order = sorted(pending, key=lambda fact: hashlib.sha256(key + b"\x01" + fact.encode()).digest())
            return {"decision": "request_facts", "requested_fact_ids": sorted(order[:size])}
        fields = {name: values[_draw(key, name, len(values))] for name, values in CANONICAL.items()}
        positive = [amount for amount in (round(price, 2), round(price + tax, 2)) if amount > 0]
        if fields["payment_mutation"] == "execute" and positive:
            fields["workflow"] = "execute_refund"
            fields["amount"] = positive[_draw(key, "amount", len(positive))]
        else:
            fields["payment_mutation"] = "none"
            amounts = (0.0, round(price, 2), round(price + tax, 2))
            fields["amount"] = amounts[_draw(key, "amount", len(amounts))]
        basis = bases[_draw(key, "policy_basis", len(bases))]
        return _resolution(**fields, policy_basis=basis, reason_code=basis)
    raise ValueError(f"unknown policy control {control!r}")


def _customer_values(observation: Mapping[str, Any], fact_ids: Iterable[str]) -> dict[str, Any]:
    flat = observation.get("private_facts")
    if isinstance(flat, Mapping):
        return {fact: flat[fact] for fact in fact_ids}
    first: dict[str, Any] = {}
    for record in observation["private_fact_records"]:
        first.setdefault(record["fact_id"], record["value"])
    return {fact: first[fact] for fact in fact_ids}


def _customer_action(control: str, payload: Mapping[str, Any]) -> Any:
    observation = payload["observation"]
    if observation["phase_id"] != "customer_disclosure":
        return _DELEGATE
    if control == "naive_overdisclose":
        flat = observation.get("private_facts")
        ids = sorted(flat) if isinstance(flat, Mapping) else sorted({r["fact_id"] for r in observation["private_fact_records"]})
    elif control == "naive_first_record":
        ids = list(observation["requested_fact_ids"])
    else:
        raise ValueError(f"unknown customer control {control!r}")
    return {"decision": "disclose_facts", "message": "Here are the facts.", "revealed_fact_ids": ids,
            "fact_values": _customer_values(observation, ids), "proposal_id": None}


def _intake_action(control: str, observation: Mapping[str, Any]) -> dict[str, Any]:
    if control != "naive_first_sorted":
        raise ValueError(f"unknown intake control {control!r}")
    open_ids = sorted(set(observation["available_fact_ids"]) - set(observation["disclosed_fact_ids"]))
    return {"decision": "request_facts", "requested_fact_ids": open_ids[:3]}


def _payments_action(control: str, observation: Mapping[str, Any]) -> dict[str, Any]:
    if control != "naive_no_mutation":
        raise ValueError(f"unknown payments control {control!r}")
    ticket = observation.get("execution_ticket")
    if isinstance(ticket, Mapping):
        ids = (ticket.get("proposal_id"), ticket.get("idempotency_key"), ticket.get("ledger_snapshot_id"))
    else:
        ledger = observation["payment_ledger"]
        ids = (observation["confirmed_proposal"]["proposal_id"], ledger["idempotency_key"], ledger["snapshot_id"])
    return {"decision": "no_mutation", "proposal_id": ids[0], "idempotency_key": ids[1], "ledger_snapshot_id": ids[2],
            "amount": 0.0, "refund_method": "none", "refund_allocations": []}


def control_model(control: str) -> str:
    return "refund-v25-control-" + control.replace("_", "-")


class ControlProvider:
    """Provider-free: the active seat plays ``control``; every other seat is the reference."""

    def __init__(self, *, seat: str, control: str, base: Any) -> None:
        if seat not in release.ROLES:
            raise ValueError(f"unknown seat {seat!r}")
        if control != COPY_REFERENCE and control not in CONTROLS[seat]:
            raise ValueError(f"{control!r} is not a declared {seat} control")
        self.seat, self.control, self.base, self.model = seat, control, base, control_model(control)

    async def complete(self, request: Any) -> Any:
        payload = json.loads(request.input_text)
        if payload["role"] != self.seat:
            return await self.base.complete(request)
        if request.model != self.model:
            raise release.core.legacy.ProviderFailure("provider_contract", "active seat is not the control profile", retryable=False)
        observation = payload["observation"]
        if self.control == "refuse_empty":
            action: Any = {}
        elif self.control == COPY_REFERENCE:
            action = _DELEGATE
        elif self.seat == "policy":
            action = _policy_action(self.control, observation)
        elif self.seat == "customer":
            action = _customer_action(self.control, payload)
        elif self.seat == "intake":
            action = _intake_action(self.control, observation)
        else:
            action = _payments_action(self.control, observation)
        text = (await self.base.complete(request)).output_text if action is _DELEGATE else json.dumps(action, sort_keys=True)
        return release.core.legacy.ProviderResult(
            f"refund_v25_control:{request.provider_call_id}", request.model, request.revision or request.model,
            text, "stop", 0, 0, 0, 0.0, {"control": self.control, "controls_version": CONTROLS_VERSION})


# ---------------------------------------------------------------------------
# Screen: play every control through the real environment and verifier.
# ---------------------------------------------------------------------------

def build_setup(cohort: str, seat: str, seed: int = SCREEN_SEED, control: str | None = None):
    """The release's cohort builder; with ``control`` the active profile is that control.

    Without ``control`` this returns the release plan byte for byte, so the
    controls play exactly the panel the reference was qualified on.
    """
    if control is None:
        return release.build_setup(cohort, seat, seed)
    if cohort not in release.PANELS:
        raise ValueError(f"unknown cohort {cohort!r}")
    model, revision = control_model(control), CONTROL_REVISION
    if cohort in ("core", "policy"):
        options = dict(include_policy_stress_extension=True, include_policy_frontier_extension=True,
                       include_policy_frontier_hard_extension=True) if cohort == "policy" else {}
        return release.core.build_refund_v25_run(world_seeds=(seed,), active_agents=(seat,), model=model,
                                                 revision=revision, **options)
    version, name = cohort.split("_", 1)
    if version == "v3":
        return release.v3.build_run(cases=release.v3.build_panels(seed)[name], active_agents=(seat,),
                                    model=model, provider_revision=revision)
    if version == "v4":
        return release.v4.build_run(release.v4.build_panels(seed)[name], active_agents=(seat,),
                                    model=model, provider_revision=revision)
    name = "payments" if version == "v51" else name
    setup = release.v5.build_run(release.v5.build_panels(seed)[name], active_agents=(seat,),
                                 model=model, provider_revision=revision)
    return release.units.amend_setup(setup) if version == "v51" else setup


def _leaf_name(leaf_id: str) -> str:
    return leaf_id.removeprefix("refund_v25_").removesuffix("_leaf")


LEAVES = tuple(_leaf_name(leaf) for leaf in release.v3.measurement.LEAF_IDS)


async def run_group(output: Path, cohort: str, seat: str, control: str, seed: int = SCREEN_SEED) -> dict[str, Any]:
    """Execute, finalize, replay and audit one (cohort, seat, control); no paid provider exists here."""
    if output.exists():
        raise FileExistsError(f"use a fresh output directory: {output}")
    base = release.provider_for(cohort)
    if control == REFERENCE:
        setup, provider = build_setup(cohort, seat, seed), base
    else:
        setup = build_setup(cohort, seat, seed, control)
        provider = ControlProvider(seat=seat, control=control, base=base)
    if any(profile.model.provider != "scripted" for profile in setup.plan.agent_profiles):
        raise AssertionError("the screen is provider-free")
    output.mkdir(parents=True)
    cases = []
    for cell in setup.plan.cells:
        execution = await release.core.legacy.execute_plan_cell(
            plan=setup.plan, cell_id=cell.cell_id, registry=setup.registry, evidence_root=output,
            prompt_sources=setup.prompt_sources, providers={"scripted": provider}, pricing=setup.pricing,
            episode_attempt_ordinal=0, harnesses=setup.harnesses)
        receipt = release.core.legacy.finalize_family_execution(setup=setup, execution=execution)
        release.core.legacy.replay_family_receipt(setup=setup, receipt=receipt, evidence_root=output)
        receipt_path = (output / setup.plan.run_plan_id / "tasks" / cell.cell_id / "attempts"
                        / receipt.episode_attempt_id / "evaluation_receipt.json")
        audit_family_receipt(setup=setup, receipt_path=receipt_path)
        values = {_leaf_name(score.leaf.leaf_id): score.primary.value for score in receipt.scores}
        terminal = execution.episode_result.terminal or execution.episode_result.final_state
        active = [event for event in terminal["events"] if event.get("seat") == seat]
        invalid = [event.get("reason") for event in active if not event.get("valid")]
        moves = [{"phase": e.get("phase"), "valid": e.get("valid"), "action": e.get("action", e.get("action_candidate"))}
                 for e in active]
        cases.append({"case_id": cell.case_id, "leaves": [values[name] for name in LEAVES],
                      "active_invalid_reason": invalid[0] if invalid else None,
                      "active_moves_sha256": hashlib.sha256(canonical_json_bytes(moves)).hexdigest()})
    cases.sort(key=lambda row: row["case_id"])
    n = len(cases)
    reasons: dict[str, int] = {}
    for row in cases:
        if row["active_invalid_reason"] is not None:
            reasons[row["active_invalid_reason"]] = reasons.get(row["active_invalid_reason"], 0) + 1
    return {
        "seat": seat, "cohort": cohort, "control": control, "run_plan_id": setup.plan.run_plan_id, "cases": n,
        "case_ids": [row["case_id"] for row in cases],
        "leaves": {name: [row["leaves"][i] for row in cases] for i, name in enumerate(LEAVES)},
        "mean": {name: round(math.fsum(row["leaves"][i] for row in cases) / n, 6) for i, name in enumerate(LEAVES)},
        "active_invalid_cases": sum(reasons.values()),
        "active_invalid_by_reason": dict(sorted(reasons.items())),
        "distinct_active_move_sequences": len({row["active_moves_sha256"] for row in cases}),
    }


def rows_from_groups(groups: Iterable[Mapping[str, Any]], case_ids: Mapping[str, list[str]] | None = None) -> list[dict[str, Any]]:
    """Per-case rows for ``evaluate_rule``; a record stores case IDs once per cohort."""
    rows = []
    for group in groups:
        ids = group["case_ids"] if case_ids is None else case_ids[group["cohort"]]
        for i, case_id in enumerate(ids):
            rows.append({"seat": group["seat"], "cohort": group["cohort"], "control": group["control"],
                         "case_id": case_id, **{name: group["leaves"][name][i] for name in LEAVES}})
    return rows


def record_from_groups(groups: Iterable[Mapping[str, Any]], seed: int = SCREEN_SEED) -> dict[str, Any]:
    """The derived, byte-reproducible screen record (no paths, times or receipt digests)."""
    groups = list(groups)
    case_ids: dict[str, list[str]] = {}
    for group in groups:
        if case_ids.setdefault(group["cohort"], group["case_ids"]) != group["case_ids"]:
            raise ValueError(f"{group['cohort']}: groups disagree on the case set")
    for group in groups:
        if group["control"] in LEGAL_ONLY and group["active_invalid_cases"]:
            raise AssertionError(f"legal-only control made an illegal move: {group['seat']}/{group['cohort']}/{group['control']}")
    return {
        "artifact": "refund_v25_lower_control_screen", "family": release.core.legacy.FAMILY_ID,
        "family_version": release.core.legacy.FAMILY_VERSION, "release_id": release.RELEASE_ID,
        "controls_version": CONTROLS_VERSION, "controls_source_sha256": _SOURCE_SHA256, "seed": seed, "paid_calls": 0,
        "command": "python -m aeread_families.refund.v2_5_controls --output FRESH_PATH --record cases/refund_v25/qc/lower_controls.json",
        "control_descriptions": dict(CONTROL_DESCRIPTIONS), "legal_only_controls": list(LEGAL_ONLY),
        "leaves": list(LEAVES), "case_ids": dict(sorted(case_ids.items())),
        "groups": [{k: v for k, v in group.items() if k != "case_ids"} for group in groups],
        "verdict": evaluate_rule(rows_from_groups(groups), RULE),
    }


async def screen(output: Path, seats: Iterable[str] = release.ROLES, cohorts: Iterable[str] = release.PANELS,
                 seed: int = SCREEN_SEED) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("use a fresh output directory; no restart or top-up")
    groups = []
    for seat in seats:
        for cohort in cohorts:
            for control in (REFERENCE, *CONTROLS[seat]):
                group = await run_group(output / seat / cohort / control, cohort, seat, control, seed)
                groups.append(group)
                print(json.dumps({key: group[key] for key in ("seat", "cohort", "control", "cases", "active_invalid_cases")}
                                 | {"end_to_end": group["mean"]["end_to_end"], "policy_semantic": group["mean"]["policy_semantic"]}), flush=True)
    return record_from_groups(groups, seed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provider-free Refund V2.5 lower-control screen (QC Gate 3)")
    parser.add_argument("--output", type=Path, required=True, help="fresh run root for receipts")
    parser.add_argument("--seats", default=",".join(release.ROLES))
    parser.add_argument("--cohorts", default=",".join(release.PANELS))
    parser.add_argument("--record", type=Path, default=None, help="write the derived screen record here")
    args = parser.parse_args(argv)
    result = asyncio.run(screen(args.output, seats=tuple(args.seats.split(",")), cohorts=tuple(args.cohorts.split(","))))
    if args.record is not None:
        args.record.write_bytes(canonical_json_bytes(result) + b"\n")
    print(json.dumps({"passes": result["verdict"]["passes"], "failing_cohorts": result["verdict"]["failing_cohorts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
