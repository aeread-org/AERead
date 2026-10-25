"""Developmental cohort redesign 2. No outcome-dependent authoring or controls.

Original source cases remain immutable. Added Intake facts are explicitly
synthetic workflow attestations, NOT additional refund eligibility evidence.
Customer histories preserve the native authority/snapshot intervention.
"""
from __future__ import annotations

import copy
import hashlib
import json

REVISION = "refund_v3_cohort_redesign/2"
COHORTS = ("seat_v3.intake", "v71.intake", "v71.customer")

# Competing retrieval paths: cheap index -> expensive reconciliation vs direct
# attestation, with a shared routing receipt. All can earn real planning utility;
# none is an unauthorized or unaffordable dummy option. These are synthetic
# work-order utility units, not money or expected refund benefit.
WORKFLOW = (
    ("routing_receipt", 1, 7, ()),
    ("archive_index", 1, 6, ()),
    ("archive_reconciliation", 2, 47, ("archive_index",)),
    ("direct_attestation", 2, 29, ()),
    ("dispatch_manifest", 1, 23, ("routing_receipt", "archive_index")),
)


def intake(contract):
    c = copy.deepcopy(contract)
    # The source graph, permissions, costs and priorities stay identifiable.
    # Scale native utility, not costs, to share a nontrivial objective with the
    # new verification paths. A pair changes only its original public axis.
    for row in c["catalogue"]:
        row["utility"] *= 5
    source = "workflow_service"
    c["authorized_sources"] = sorted(set(c["authorized_sources"]) | {source})
    c["catalogue"].extend({"fact_id": "workflow_" + name, "cost": cost,
        "utility": utility, "material": True, "source": source,
        "requires": ["workflow_" + k for k in parents]}
        for name, cost, utility, parents in WORKFLOW)
    c["total_budget"] += 3
    c["max_rounds"] += 2
    c["rule"] += (
        " V3 work-order extension: workflow_* are synthetic verification tasks, "
        "not refund-policy evidence. Their public utility competes with native "
        "fact collection under the SAME total budget, horizon and batch cap. "
        "Native utilities are scaled by five; workflow utilities are stated in "
        "the same abstract units. This V3 access clause supersedes the historical "
        "material-only sentence: every undisclosed, source-authorized, "
        "prerequisite-ready affordable task is legal, including material=false "
        "tasks, which earn zero utility."
    )
    supporting = {"workflow_" + name: "attested" for name, *_ in WORKFLOW}
    return c, supporting


def supporting_records(contract, records, facts):
    c, rows = copy.deepcopy(contract), copy.deepcopy(list(records))
    if facts:
        c["authorities"].append({"document_id": "workflow_service", "priority": 100})
        rows.extend({"fact_id": k, "document_id": "workflow_service",
            "scope": c["request_scope"], "revision": 1, "recorded_at": c["as_of"],
            "status": "live", "value": value} for k, value in sorted(facts.items()))
    return c, rows


def _old_value(value):
    # Type-preserving conflicts also exercise downstream non-oracle behavior.
    if type(value) is bool:
        return not value
    if type(value) in (float, int):
        return value + 1
    alternatives = {"verified": "unverified", "unverified": "verified",
        "match": "mismatch", "mismatch": "match", "complete": "incomplete",
        "incomplete": "complete", "pending": "none", "none": "pending"}
    if value in alternatives:
        return alternatives[value]
    if value and value[-1].isdigit():
        return value[:-1] + str((int(value[-1]) + 1) % 10)
    return "unknown" if value != "unknown" else "unverified"


def customer(source, twin, contract, records):
    """Add prehistory, revoked epochs and post-snapshot reissues per document.

    Histories are identical across twins, except original declared native
    interventions. A revoked prehistory cannot make a formerly absent document
    live. Future reissues use a cutoff beyond BOTH snapshots. Native rows remain
    present verbatim, but no row position or record ID encodes authority.
    """
    rows = copy.deepcopy(list(records))
    context = source.seat_context
    other = twin.seat_context
    native = context["private_records_v6"]
    other_native = other["private_records_v6"]
    cutoff = max(contract["as_of"], other["customer_contract_v6"]["as_of"])
    first_time = min(r["recorded_at"] for r in native + other_native) - 3
    groups = sorted({(r["fact_id"], r["document_id"], r["scope"]) for r in native + other_native})
    for fact, doc, scope in groups:
        pool = [r for r in native + other_native
                if (r["fact_id"], r["document_id"], r["scope"]) == (fact, doc, scope)]
        lo, hi = min(r["revision"] for r in pool), max(r["revision"] for r in pool)
        # Stable baseline, not the hidden outcome in this variant.
        live = [r for r in pool if r["value"] is not None] or [
            r for r in native + other_native if r["fact_id"] == fact and r["value"] is not None]
        value = sorted(live, key=lambda r: json.dumps(r, sort_keys=True))[0]["value"]
        base = {"fact_id": fact, "document_id": doc, "scope": scope}
        rows.extend([
            {**base, "revision": lo - 2, "recorded_at": first_time,
             "status": "live", "value": _old_value(value)},
            {**base, "revision": lo - 1, "recorded_at": first_time + 1,
             "status": "revoked", "value": None},
            {**base, "revision": hi + 1, "recorded_at": cutoff + 1,
             "status": "live", "value": _old_value(value)},
        ])
    def key(indexed):
        # Source row ordinal is stable across the declared native intervention;
        # hashing revision/time would create artificial array permutations.
        index, _ = indexed
        identity = [source.interaction.pair_id, source.interaction.world_seed, index]
        return hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    return [row for _, row in sorted(enumerate(rows), key=key)]
