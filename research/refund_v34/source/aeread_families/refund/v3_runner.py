"""Provider-free V3 development runner using the real shared-runner scheduler.

This is deliberately NOT a production registry admission, a paid adapter, or a
kernel-sealed evaluation receipt. Development transcript seals and deterministic
replay are supporting evidence until trusted CI and external QC admission run.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from aeread.shared_runner.run.resolver import PlanCell, canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import run_episode
from . import v3_cases as design
from . import v3_environment as env
from . import v3_qc as qc

VERSION = "3.0.0"
SEEDS = (401, 402, 403)
CONTROLS = ("naive", "random", "collect_all")
BEATABILITY_CONTROLS = ("naive", "random")


def implementation_sources():
    names = ("v3_cases.py", "v3_contracts.py", "v3_publication.py", "v3_redesign.py", "v3_environment.py", "v3_runner.py", "v3_qc.py", "v3_measurement.py",
        "v2_4_cases.py", "v2_4_reference.py", "v2_5_policy.py", "v2_5_runner.py", "v2_5_branches.py",
        "v2_5_seat_design_v3.py", "v2_5_seat_extension_v4.py", "v2_5_seat_extension_v5.py",
        "v2_5_seat_extension_v6_2_1.py", "v2_5_seat_extension_v7.py", "v2_5_seat_extension_v7_1.py",
        "v2_5_normative_cases.py", "v2_5_policy_composition_cases.py", "v2_5_payment_units_v51.py")
    facts = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in names}
    from aeread.shared_runner import measurement, schemas
    from aeread.shared_runner.run import resolver
    from aeread.shared_runner.task import scheduler, evaluation
    for module in (measurement, schemas, resolver, scheduler, evaluation):
        facts[module.__name__] = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    return facts


@lru_cache(None)
def implementation_digest():
    return env.digest(implementation_sources())


def episode_contract(case, active_seat, control="reference"):
    if active_seat not in env.ROLES:
        raise ValueError("Exactly one known active seat required")
    maximum = 4 * len(case.catalogue) + 4 * case.intake_contract["max_rounds"] + 16
    raw = {"spec_version": CaseManifest.SPEC_VERSION, "case_id": case.case_id,
        "family_id": "refund_v3", "family_version": VERSION, "split": "dev", "world_seed": case.seed,
        "seats": [{"id": s, "role": s} for s in env.ROLES],
        "episode": {"max_logical_actions": maximum, "termination": ["completed", "invalid_action"]},
        "visibility_policy": "refund_v3_four_seat", "payload": design.payload(case),
        "provenance": {"generator_id": "refund_v3_migration", "generator_version": VERSION,
                       "review_status": "generated"}, "content_sha256": "0" * 64}
    raw["content_sha256"] = case_content_sha256(raw)
    manifest = CaseManifest.from_dict(raw)
    identity = env.digest({"case": manifest.content_sha256, "active": active_seat, "control": control,
                           "implementation": implementation_digest()})
    cell = PlanCell("1", "refund_v3_" + identity[:32], case.case_id, manifest.content_sha256,
        "refund_v3", VERSION, "refund_v3_development", VERSION, "controlled_" + active_seat,
        "refund_v3_fixed", "refund_v3_development", case.seed, 0, 0, 0, 0,
        case.cluster_id, "mechanism", 2, case.pair_id, {"pair_id": case.pair_id}, "fixed_panel",
        {s: "active_" + control if s == active_seat else "scripted_reference" for s in env.ROLES},
        "controlled", maximum)
    return cell, manifest


def draw(obs, label, count):
    return int(env.digest({"observation": obs, "label": label})[:16], 16) % count


def lower_action(seat, obs, control):
    """Observation-only lower controls; none receives a case or outcome oracle."""
    phase = obs["phase_id"]
    if seat == "policy":
        if control in ("collect_all", "random"):
            available = [r["fact_id"] for r in obs["catalogue"]
                         if r["fact_id"] not in obs["attempted_fact_ids"] and r["cost"] <= obs["remaining_budget"]]
            if available and (control == "collect_all" or draw(obs, "collect", 3)):
                return {"decision": "request_facts", "fact_ids": [sorted(available)[draw(obs, control, len(available))]]}
            if control == "collect_all":
                return env.policy_action(obs)
        branches = obs["branch_specification"]["branches"]
        basis = next((b["outcome"]["basis"] for b in branches if b["outcome"]["remedy"] == "full_refund"), branches[0]["outcome"]["basis"])
        amount = round(obs["financial_inputs"]["item_net_price"] + obs["financial_inputs"]["allocated_tax"], 2)
        return {"decision": "submit_resolution", "proposal_id": "proposal_1", "eligibility": "eligible",
            "remedy": "full_refund", "workflow": "execute_refund", "amount": amount,
            "refund_method": "original_payment", "payment_mutation": "execute",
            "return_shipping_payer": "seller", "policy_basis": basis, "reason_code": basis}
    if seat == "intake":
        options = list(env.collection_batches(obs)) if obs["round"] < obs["collection_contract"]["max_rounds"] else []
        if not options:
            return {"decision": "handoff"}
        if control == "naive":
            batch = min(options, key=lambda x: x[0])[0]
        elif control == "collect_all":
            batch = max(options, key=lambda x: (len(x[0]), -x[1], x[0]))[0]
        else:
            batch = options[draw(obs, "intake", len(options))][0]
        return {"decision": "request_facts", "fact_ids": list(batch)}
    if seat == "customer":
        if phase != "customer_disclosure":
            return env.scripted_customer(obs)
        disclosures = []
        for fact in obs["requested_fact_ids"]:
            rows = [r for r in obs["private_records"] if r["fact_id"] == fact]
            row = rows[0] if control == "naive" else max(rows, key=lambda r: r["revision"]) if control == "collect_all" else rows[draw(obs, fact, len(rows))]
            disclosures.append({"fact_id": fact, "record_id": row["record_id"]})
        return {"decision": "disclose_facts", "disclosures": disclosures}
    ledger, proposal = obs["payment_ledger"], obs["confirmed_proposal"]
    action = {"decision": "no_mutation", "proposal_id": proposal["proposal_id"],
        "idempotency_key": ledger["idempotency_key"],
        "ledger_snapshot_id": ledger.get("snapshot_id", ledger.get("ledger_snapshot_id")),
        "amount": 0.0, "refund_method": "none", "refund_allocations": []}
    if control == "random":
        # A genuinely uninformed feasible control: no reference reducer or
        # optimal allocation, just a uniform public-capacity-bounded amount
        # on one randomly selected destination (including a no-op draw).
        limit, capacities = env.payment_safety_limits(obs)
        destinations = sorted(k for k, value in capacities.items() if value > 0)
        if limit and destinations:
            destination = destinations[draw(obs, "destination", len(destinations))]
            cents = draw(obs, "amount_cents", min(limit, capacities[destination]) + 1)
            if cents:
                action.update(decision="execute_refund", amount=cents / 100,
                    refund_method="original_payment",
                    refund_allocations=[{"instrument": destination, "amount": cents / 100}])
    return action


async def execute(case, seat, control="reference", tape=None, mutate=None):
    cell, manifest = episode_contract(case, seat, control)
    plugin = env.RefundV3Plugin()
    transcript = []
    async def source(request):
        observation = env.plain(request.observation)
        index = len(transcript)
        if tape is not None:
            if index >= len(tape) or observation != tape[index]["observation"] or request.seat_id != tape[index]["seat"]:
                raise ValueError("Offline replay observation/seat mismatch")
            response = tape[index]["response"]
        else:
            action = (env.scripted_action(request.seat_id, observation) if request.seat_id != seat or control == "reference"
                      else lower_action(seat, observation, control))
            if mutate:
                action = mutate(request, action)
            response = json.dumps(action, allow_nan=False)
        transcript.append({"seat": request.seat_id, "phase": request.phase_id,
                           "observation": observation, "response": response})
        return response
    result = await run_episode(cell=cell, case=manifest, plugin=plugin, response_source=source)
    if tape is not None and len(tape) != len(transcript):
        raise ValueError("Unconsumed replay actions")
    outcome = env.plain(result.outcome)
    parse_failures = [a.parse.error_code for p in result.phase_instances
                      for a in p.actions if not a.parse.ok]
    validity = not parse_failures
    return {"case_id": case.case_id, "pair_id": case.pair_id, "seed": case.seed,
            "seat": seat, "cohort": case.cohort, "control": control, "cluster_id": case.cluster_id,
            "source_case_id": case.source_case_id, "case_sha256": manifest.content_sha256,
            "implementation_sha256": implementation_digest(), "transcript": transcript,
            "state": env.plain(result.final_state), "outcome": outcome,
            "strict": outcome["seat_strict"][seat] if validity else None,
            "policy_semantic": outcome["metrics"]["policy_semantic"] if seat == "policy" and validity else None,
            "validity": validity, "invalidity_reasons": parse_failures,
            "paid_calls": 0, "development_evidence_only": True}


async def verify_replay(case, record):
    replay = await execute(case, record["seat"], record["control"], tape=record["transcript"])
    if replay != record:
        raise ValueError("Replay state, score, contract or source digest mismatch")
    return True


async def conformance(output, seeds=SEEDS, screen=False):
    output = Path(output)
    if output.exists():
        raise FileExistsError("Fresh output required; never overwrite or top up")
    output.mkdir(parents=True)
    started = time.monotonic()
    summaries, controls, manifests = [], [], []
    catalogs = {seed: design.build_catalog(seed) for seed in seeds}
    from .v3_publication import design_preflight
    preflight = design_preflight(catalogs)
    frozen_sources = implementation_sources()
    frozen_cases = [{"case_id": c.case_id, "seed": c.seed, "case_sha256": env.digest(design.payload(c)),
                     "role": c.role, "seat": c.seat, "cohort": c.cohort}
                    for catalog in catalogs.values() for c in catalog]
    # A frozen local declaration is written before any outcomes are inspected.
    contract = {"family": "refund_v3", "version": VERSION, "rule": qc.RULE_ID,
        "design_revision": design.contracts.REVISION,
        "cohort_redesign_revision": design.redesign.REVISION,
        "seeds": list(seeds), "controls": list(CONTROLS), "screen": screen,
        "beatability_controls": list(BEATABILITY_CONTROLS),
        "diagnostic_controls": {"collect_all": "evidence/efficiency shortcut test; uses the informed policy resolver after collection, so not a weak policy-semantic baseline"},
        "payment_random_control": "uniform feasible cents on one public capacity-bounded destination, including no-op; no reference reducer",
        "qualification_scope": "comparison only; diagnostic and exposed_reserved evaluated separately",
        "implementation_sha256": implementation_digest(), "paid_calls_authorized": False,
        "implementation_sources": frozen_sources, "cases": frozen_cases,
        "publication_selection": preflight["publication_selection"],
        "evidence_kind": "development_scheduler_transcript_not_kernel_receipt",
        "limits": {"logical_actions": "4N+4R+16 per episode", "provider_calls": 0,
                   "input_tokens": 0, "output_tokens": 0, "cost_usd": 0, "wall_seconds": 1800},
        "promotion": "blocked until model headroom, authenticated review, trusted CI and campaign gates pass"}
    (output / "execution_contract.json").write_bytes(canonical_json_bytes(contract) + b"\n")
    (output / "design_preflight.json").write_bytes(canonical_json_bytes(preflight) + b"\n")
    for seed in seeds:
        catalog = catalogs[seed]
        counts = Counter(c.seat for c in catalog)
        for case in catalog:
            if time.monotonic() - started > contract["limits"]["wall_seconds"]:
                raise TimeoutError("Development conformance wall-time ceiling reached")
            manifests.append({"case_id": case.case_id, "pair_id": case.pair_id, "seed": case.seed,
                "seat": case.seat, "cohort": case.cohort, "cluster_id": case.cluster_id,
                "source_sha256": case.source_sha256, "role": case.role})
            for seat in env.ROLES:
                record = await execute(case, seat)
                await verify_replay(case, record)
                if record["outcome"]["system_strict"] != 1:
                    raise AssertionError((case.case_id, seat, record["outcome"]))
                seal = env.digest(record)
                (output / (seal + ".json")).write_bytes(canonical_json_bytes(record) + b"\n")
                summaries.append({"case_id": case.case_id, "seat": seat, "seal": seal, "replayed": True})
            if screen:
                for control in ("reference", *CONTROLS):
                    record = await execute(case, case.seat, control)
                    await verify_replay(case, record)
                    seal = env.digest(record)
                    (output / (seal + ".json")).write_bytes(canonical_json_bytes(record) + b"\n")
                    controls.append({k: record[k] for k in ("case_id", "pair_id", "seed", "seat", "cohort", "control", "strict", "policy_semantic", "validity")})
        print(json.dumps({"seed": seed, "cases": len(catalog), "by_target_seat": dict(counts),
                          "completed_conformance": len(summaries), "paid_calls": 0}), flush=True)
    summary = {"version": VERSION, "seeds": list(seeds), "completed": len(summaries), "rows": summaries,
        "catalog": manifests, "paid_calls": 0, "provider_free_development": "passed",
        "trusted_conformance": "not_run", "normative_status": "partial"}
    if frozen_sources != implementation_sources():
        raise ValueError("Bound source changed during development conformance")
    if screen:
        (output / "lower_control_rows.json").write_bytes(canonical_json_bytes(controls) + b"\n")
        analysis = analyze_controls(controls, catalogs)
        (output / "lower_controls.json").write_bytes(canonical_json_bytes(analysis) + b"\n")
        summary["lower_control_rule_passed"] = analysis["passed"]
        publication_analysis = analyze_controls(controls, catalogs,
            preflight["publication_selection"]["eligible_case_ids"])
        (output / "publication_controls.json").write_bytes(canonical_json_bytes(publication_analysis) + b"\n")
        summary["publication_control_rule_passed"] = publication_analysis["passed"]
    payment_rows = [{"case_id": c.case_id, "cohort": c.cohort + "." + str(c.seed),
                     "initial_no_op": int(c.metadata["no_op"]), "redelivery": False}
                    for catalog in catalogs.values() for c in catalog if c.seat == "payments"]
    summary["payment_admission"] = qc.payment_admission(payment_rows)
    (output / "summary.json").write_bytes(canonical_json_bytes(summary) + b"\n")
    return summary


def analyze_controls(rows, catalogs, eligible_case_ids=None):
    """Preserve all sources; normalize template IDs, never count seeds as worlds."""
    def case_template(c):
        return c.case_id.removesuffix(f".{c.seed:06d}")
    def pair_template(c):
        return c.pair_id.removesuffix("." + str(c.seed))
    lookup = {c.case_id: c for catalog in catalogs.values() for c in catalog}
    eligible = set(eligible_case_ids) if eligible_case_ids is not None else None
    if eligible is not None and (not eligible or not eligible <= set(lookup)
            or any(lookup[k].role != "comparison" for k in eligible)):
        raise ValueError("Invalid publication comparison selection")
    def included(c, role):
        return c.role == role and (role != "comparison" or eligible is None or c.case_id in eligible)
    def evaluate(role):
        normalized = [{**r, "case_id": case_template(lookup[r["case_id"]]),
                       "pair_id": pair_template(lookup[r["case_id"]])} for r in rows
                      if r["control"] in ("reference", *BEATABILITY_CONTROLS)
                      and included(lookup[r["case_id"]], role)]
        first = [c for c in next(iter(catalogs.values())) if included(c, role)]
        pairs, invariance = {}, set()
        for c in first:
            pairs.setdefault((c.seat, c.cohort), {}).setdefault(pair_template(c), []).append(case_template(c))
            if c.pair_kind == "invariance":
                invariance.add((c.seat, c.cohort, pair_template(c)))
        if not pairs:
            return {"status": "not_applicable", "reason": "no cases in this role"}
        return qc.evaluate_beatability(normalized, pairs=pairs, seeds=tuple(catalogs),
            lower_controls=BEATABILITY_CONTROLS, invariance_pairs=invariance)
    result = evaluate("comparison")
    result["scope"] = "publication_comparison_deduplicated" if eligible is not None else "comparison"
    result["nonqualification_screens"] = {role: evaluate(role) for role in ("diagnostic", "exposed_reserved")}
    result["development_evidence_only"] = True
    result["model_headroom"] = "not_run"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", default=",".join(map(str, SEEDS)))
    parser.add_argument("--screen", action="store_true")
    options = parser.parse_args()
    existed_at_start = options.output.exists()
    try:
        asyncio.run(conformance(options.output, tuple(map(int, options.seeds.split(","))), options.screen))
    except (Exception, KeyboardInterrupt) as exc:
        if not existed_at_start and options.output.exists():
            (options.output / "failure.json").write_bytes(canonical_json_bytes({
                "status": "failed", "error_type": type(exc).__name__, "error": str(exc),
                "paid_calls": 0, "evidence_preserved": True}) + b"\n")
        raise


if __name__ == "__main__":
    main()
