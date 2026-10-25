"""Lossless, provider-free issue290 migration into the Refund 3.0.0 envelope.

The policy catalogue covers *all* source facts at a uniform cost, without a
relevance-price label. Cohort redesign/2 explicitly extends two Intake work
orders and one Customer history; original sources remain immutable fixtures.
Native source contracts remain in provenance; public V3 law replaces their
historical wording. Older intake contracts become
one-round collection_v6 contracts before the declared work-order extension. Older
customer provenance is retained in metadata, but is explicitly synthesized
into V621 authority/snapshot semantics, rather than pretending that V5's
per-fact revision ceilings mean a single global as_of timestamp.

``changed_paths`` uses dotted, zero-based list indices over facts, catalogue,
intake_contract, customer_contract, records, ledger and customer_lifecycle.
Identity, source aliases, reference results and provenance copies are excluded.
Clusters conservatively share a source scenario across generations and seeds;
wrapping or reseeding the same source does not create independent QC clusters.
No ledger here is an execution ticket: legacy observations must recompute
legacy.payment_ledger(source, confirmed_proposal['amount']) at execution time.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, fields, replace
from typing import Any, Mapping

from aeread.shared_runner.run.resolver import canonical_json_bytes

from . import v2_5_runner as legacy
from . import v2_5_seat_design_v3 as seat_v3
from . import v2_5_seat_extension_v4 as v4
from . import v2_5_seat_extension_v5 as v5
from . import v2_5_seat_extension_v6_2_1 as v621
from . import v2_5_seat_extension_v7_1 as v71
from . import v3_redesign as redesign
from . import v3_contracts as contracts
from .v2_5_branches import spec_for
from .v2_5_normative_cases import build_normative_panel
from .v2_5_payment_units_v51 import UNIT_CONTRACT
from .v2_5_policy import (
    UnifiedRefundCase, build_operational_extension_panel, build_unified_panel,
    render_policy_contract, resolve_policy, validate_case_domains,
    validate_resolution_invariants,
)
from .v2_5_policy_composition_cases import build_policy_composition_panel

VERSION = "3.0.0"
SeatCase = seat_v3.SeatCase
SEATS = ("intake", "customer", "policy", "payments")
ROLES = ("comparison", "diagnostic", "exposed_reserved")
PAIR_KINDS = ("contrast", "invariance")
POLICY_OUTCOME_FIELDS = ("eligibility", "remedy", "workflow", "amount", "refund_method",
                         "payment_mutation", "return_shipping_payer")


@dataclass(frozen=True, slots=True)
class Case:
    case_id: str
    pair_id: str
    seed: int
    seat: str
    cohort: str
    source: UnifiedRefundCase | SeatCase
    source_case_id: str
    source_sha256: str
    cluster_id: str
    role: str
    pair_kind: str
    catalogue: tuple[dict[str, Any], ...]
    intake_contract: dict[str, Any]
    customer_contract: dict[str, Any]
    records: tuple[dict[str, Any], ...]
    supporting_facts: dict[str, Any]
    ledger: dict[str, Any]
    changed_paths: tuple[str, ...]
    metadata: dict[str, Any]


def _json(value):
    """Detached JSON values; preserve bool/int/float distinctions in seals."""
    return json.loads(_bytes(value))


def _bytes(value):
    return canonical_json_bytes(value)


def _same(a, b):
    return _bytes(a) == _bytes(b)


def _sha(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def decode_source(raw):
    """Decode through the historical decoder, restoring SeatCase explicitly."""
    if not isinstance(raw, Mapping):
        raise ValueError("source must be an object")
    # Scheduler evidence contains mapping proxies and tuples. Detach it before
    # the historical decoder's deepcopy and restore ordinary JSON containers.
    raw = _json(raw)
    expected = {"interaction", "product_category"}
    if "seat_context" in raw:
        expected.add("seat_context")
    if set(raw) != expected or not isinstance(raw.get("interaction"), Mapping):
        raise ValueError("Unexpected source keys")
    if set(raw["interaction"]) != {f.name for f in fields(legacy.MarketplaceV24Case)}:
        raise ValueError("Unexpected source interaction keys")
    try:
        source = legacy._case({"case": copy.deepcopy(raw)})
        if type(source.interaction.world_seed) is not int:
            raise ValueError("Source world_seed must be an integer")
        source = replace(source, interaction=replace(
            source.interaction, changed_fact_ids=tuple(source.interaction.changed_fact_ids)))
        if "seat_context" in raw:
            if not isinstance(raw["seat_context"], Mapping):
                raise ValueError("seat_context must be an object")
            source = SeatCase(source.interaction, source.product_category, copy.deepcopy(raw["seat_context"]))
        validate_case_domains(source)
        validate_resolution_invariants(source, resolve_policy(source))
    except (TypeError, KeyError, AssertionError) as exc:
        raise ValueError("Invalid source") from exc
    if not _same(asdict(source), raw):
        raise ValueError("Source decoder changed serialized values")
    return source


def _diff(a, b, path=""):
    if _same(a, b):
        return ()
    if isinstance(a, dict) and isinstance(b, dict):
        result = []
        for key in sorted(set(a) | set(b)):
            child = f"{path}.{key}" if path else key
            result.extend((child,) if key not in a or key not in b else _diff(a[key], b[key], child))
        return tuple(result)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)) and len(a) == len(b):
        return tuple(p for i, (x, y) in enumerate(zip(a, b)) for p in _diff(x, y, f"{path}.{i}"))
    return (path,)


def _context(source):
    return getattr(source, "seat_context", {})


def _source_pair_changes(a, b):
    """Assert original interventions, without editing or regenerating sources."""
    x, y = _json(asdict(a)), _json(asdict(b))
    changed = {k for k in set(a.facts) | set(b.facts)
               if k not in a.facts or k not in b.facts or not _same(a.facts[k], b.facts[k])}
    if changed != set(a.interaction.changed_fact_ids) or changed != set(b.interaction.changed_fact_ids):
        raise ValueError("Source pair has undeclared fact changes")
    for raw in (x, y):
        raw["interaction"].pop("case_id")
        raw["interaction"].pop("variant")
    paths = _diff(x, y)
    allowed = {"interaction.facts." + k for k in changed}
    ca, cb = _context(a), _context(b)
    declared = ca.get("changed_public_fields", [])
    if not _same(declared, cb.get("changed_public_fields", [])):
        raise ValueError("Source public intervention declarations differ")
    for path in list(declared) + ([ca["intervention_path"]] if "intervention_path" in ca else []):
        path = re.sub(r"\[(\d+)\]", r".\1", path)
        allowed.add("seat_context." + path)
        if path.startswith("collection_v6."):
            allowed.add("seat_context." + path.replace("collection_v6.", "collection_v5.", 1))
    if "access_contract_v71" in ca:
        if not _same(ca["access_contract_v71"], v71.access_contract(a)) or not _same(cb.get("access_contract_v71"), v71.access_contract(b)):
            raise ValueError("Invalid V71 derived access rationale")
        allowed.add("seat_context.access_contract_v71")
    if any(not any(p == q or p.startswith(q + ".") for q in allowed) for p in paths):
        raise ValueError("Source pair changes beyond its declared intervention: " + repr(paths))
    return paths


def _intake(source, seat):
    ctx = _context(source)
    native = ctx.get("collection_v6", ctx.get("collection_v5"))
    if native is not None:
        return _json(native), "native_collection_v6" if "collection_v6" in ctx else "native_collection_v5"
    contract = seat_v3.collection_contract(SeatCase(source.interaction, source.product_category, ctx))
    opening = set(spec_for(source.interaction.scenario).intake_order[:2])
    rows = []
    for row in contract["fact_catalogue"]:
        active = row["material"]
        if seat != "intake":
            active = row["fact_id"] in opening
        elif contract["scoped"]:
            active = active and contract["work_order_scope"] in row["collection_scopes"]
        rows.append({"fact_id": row["fact_id"], "material": active,
                     "source": "work_order", "requires": [], "cost": 1,
                     "utility": max(1, 10 // (row["priority_group"] + 1))})
    cap = contract["max_batch_size"] if seat == "intake" else min(2, len(opening))
    return {"catalogue": rows, "authorized_sources": ["work_order"],
            "max_batch_size": cap, "max_rounds": 1, "total_budget": cap,
            "rule": v621.INTAKE_RULE}, "v3_scopes_priority_one_round" if seat == "intake" else "scripted_opening_one_round"


def _customer(source, twin):
    ctx = _context(source)
    if "customer_contract_v6" in ctx:
        contract, records = _json(ctx["customer_contract_v6"]), _json(ctx["private_records_v6"])
        mode = "native_customer_v6"
    else:
        pair = sorted((source, twin), key=lambda c: c.case_id)
        index = 0 if source.case_id == pair[0].case_id or _same(dict(source.facts), dict(twin.facts)) else 1
        contract = {"request_scope": "order_A", "as_of": 2,
                    "authorities": [{"document_id": "variant_A", "priority": 0 if index == 0 else 2},
                                    {"document_id": "variant_B", "priority": 1}],
                    "rule": v621.CUSTOMER_RULE}
        records = []
        for fact in sorted(source.facts):
            for doc, member in zip(("variant_A", "variant_B"), pair):
                records.append({"fact_id": fact, "document_id": doc, "scope": "order_A", "revision": 1,
                                "recorded_at": 1, "status": "live", "value": _json(member.facts[fact])})
                records.append({"fact_id": fact, "document_id": doc, "scope": "order_A", "revision": 99,
                                "recorded_at": 9, "status": "live", "value": "future"})
            records.append({"fact_id": fact, "document_id": "variant_A", "scope": "foreign", "revision": 100,
                            "recorded_at": 1, "status": "live", "value": "foreign"})
            records.append({"fact_id": fact, "document_id": "revoked", "scope": "order_A", "revision": 1,
                            "recorded_at": 1, "status": "revoked", "value": None})
        mode = "synthetic_shared_twins_authority_snapshot"
    records = tuple({**row, "record_id": f"record_{i:05d}"} for i, row in enumerate(records))
    obs = {"customer_contract_v6": contract, "private_fact_records": records,
           "requested_fact_ids": sorted(source.facts)}
    if not _same(v621.disclosure_reference(obs), dict(source.facts)):
        raise ValueError("Normalized customer disclosure differs from source facts")
    return contract, records, mode


def _normalized(source, twin, seat, generation):
    relevant = set(spec_for(source.interaction.scenario).fact_ids())
    catalogue = tuple({"fact_id": k, "cost": 1} for k in sorted(source.facts))
    if not set(source.facts) - relevant:
        raise ValueError("A policy decoy must be an actual source fact")
    intake, intake_mode = _intake(source, seat)
    customer, records, customer_mode = _customer(source, twin)
    supporting = {}
    cohort = f"{generation}.{seat}"
    if cohort in ("seat_v3.intake", "v71.intake", *contracts.INTAKE_EXTENSION_COHORTS):
        intake, supporting = redesign.intake(intake)
        customer, records = redesign.supporting_records(customer, records, supporting)
        intake_mode += "+work_order_publication_repair3" if cohort in contracts.INTAKE_EXTENSION_COHORTS else "+work_order_redesign2"
        catalogue += tuple({"fact_id": k, "cost": 1} for k in sorted(supporting))
    if cohort == "v71.customer":
        records = redesign.customer(source, twin, customer, records)
        customer_mode += "+history_redesign2"
    intake = contracts.normalize_intake(intake)
    customer = contracts.normalize_customer(customer)
    records = tuple({**r, "record_id": f"record_{i:05d}"} for i, r in enumerate(records))
    if not _same(v621.disclosure_reference({"customer_contract_v6": customer,
            "private_fact_records": records, "requested_fact_ids": sorted({**source.facts, **supporting})}),
            {**source.facts, **supporting}):
        raise ValueError("Redesign changed native disclosure values")
    ctx = _context(source)
    if "payment_ledger" in ctx:
        data = _json(ctx["payment_ledger"])
        ledger = {"kind": "v5" if "tenders" in data else "v4", "data": data}
    else:
        ledger = {"kind": "legacy", "data": _json(legacy.payment_ledger(source, resolve_policy(source).amount))}
    return catalogue, intake, customer, records, ledger, intake_mode, customer_mode, supporting


def _view(case):
    ledger = copy.deepcopy(case.ledger)
    for key in ("ledger_snapshot_id", "snapshot_id"):
        ledger["data"].pop(key, None)
    return {"facts": dict(case.source.facts), "supporting_facts": case.supporting_facts, "catalogue": case.catalogue,
            "intake_contract": case.intake_contract, "customer_contract": case.customer_contract,
            "records": case.records, "ledger": ledger,
            "customer_lifecycle": _context(case.source).get("proposal_binding_v7", {})}


def _native_behavior(source, seat, intake):
    """Comparison behavior without identities, provenance, or reference labels."""
    ctx = _context(source)
    resolution = resolve_policy(source)
    if seat == "intake":
        return v621.intake_plan_reference({"collection_v6": intake, "collection_round": 0,
            "remaining_collection_budget": intake["total_budget"], "disclosed_fact_ids": []})
    if seat == "customer":
        return {"facts": dict(source.facts), "binding": ctx.get("proposal_binding_v7", {})}
    if seat == "policy":
        # Basis/reason codes are contract labels, and evidence requirements
        # describe collection. Neither establishes a substantive policy contrast.
        return {field: getattr(resolution, field) for field in POLICY_OUTCOME_FIELDS}
    proposal = {**asdict(resolution), "proposal_id": "comparison"}
    if "payment_ledger" in ctx:
        reference = v5.payment_reference if "tenders" in ctx["payment_ledger"] else v4.payment_reference
        result = reference(proposal, ctx["payment_ledger"])
    else:
        result = {"payment_mutation": resolution.payment_mutation,
                  **_json(legacy.payment_ledger(source, resolution.amount))}
    for key in ("proposal_id", "ledger_snapshot_id", "idempotency_key"):
        result.pop(key, None)
    return result


def _no_op(source, seat):
    # This is a payments execution cap, not a cap on legitimate policy holds,
    # denials, intake requests or customer disclosures.
    if seat != "payments":
        return False
    resolution = resolve_policy(source)
    if "payment_ledger" not in _context(source):
        ledger = legacy.payment_ledger(source, resolution.amount)
        return (resolution.payment_mutation != "execute" or bool(ledger.get("already_applied"))
                or sum(row["amount"] for row in ledger["refund_allocations"]) <= 0)
    ctx = _context(source)
    ref = v5.payment_reference if "tenders" in ctx["payment_ledger"] else v4.payment_reference
    return ref({**asdict(resolution), "proposal_id": "comparison"}, ctx["payment_ledger"])["kind"] == "no_op"


def _migrate_pair(pair, generation, panel, seat, diagnostic=False):
    a, b = pair
    source_paths = _source_pair_changes(a, b)
    cases = []
    for source, twin in ((a, b), (b, a)):
        source = decode_source(_json(asdict(source)))
        twin = decode_source(_json(asdict(twin)))
        catalogue, intake, customer, records, ledger, imode, cmode, supporting = _normalized(source, twin, seat, generation)
        ctx = _context(source)
        reserved = bool(ctx.get("held_out"))
        cohort = f"{generation}.{panel}"
        pair_id = f"refund_v3.{generation}.{source.interaction.pair_id}.{source.interaction.world_seed}"
        cluster_id = f"refund_v3.source.{source.interaction.scenario}"
        metadata = {"generation": generation, "source_panel": panel,
                    "public_contract_revision": contracts.REVISION,
                    "twin_source": _json(asdict(twin)), "twin_sha256": _sha(asdict(twin)),
                    "source_changed_paths": list(source_paths), "intake_normalization": imode,
                    "customer_normalization": cmode, "blind": False, "exposed_reserved": reserved,
                    "reference_participation": list(SEATS), "comparison_seat": seat,
                    "pair_kind_basis": "substantive_policy_outcome" if seat == "policy" else "declared_seat_behavior",
                    "no_op": _no_op(source, seat), "diagnostic_origin": diagnostic,
                    "legacy_ledger_usage": "Recompute legacy.payment_ledger(source, confirmed_proposal.amount) after confirmation; data is migration metadata only."}
        if cohort in redesign.COHORTS:
            metadata["cohort_redesign"] = {"revision": redesign.REVISION,
                "source_preserved": True, "synthetic_workflow_facts": sorted(supporting),
                "policy_evidence": False, "developmentally_exposed": True}
        if cohort in contracts.INTAKE_EXTENSION_COHORTS:
            metadata["publication_intake_extension"] = {"revision": contracts.REVISION,
                "source_preserved": True, "all_native_cohort_roles": True,
                "synthetic_workflow_facts": sorted(supporting), "policy_evidence": False,
                "workflow_mechanics": redesign.REVISION, "developmentally_exposed": True}
        if cmode == "synthetic_shared_twins_authority_snapshot" and not _same(dict(source.facts), dict(twin.facts)):
            # Original hidden-fact labels remain in source, but migration adds
            # an explicit public authority intervention over a shared record
            # pool. That intervention is derived, not a hidden-only contrast.
            metadata["derived_customer_intervention"] = {
                "kind": "authority_priority_from_source_variant",
                "public_paths": ["customer_contract.authorities.0.priority"],
                "source_fact_ids": sorted(k for k in source.facts if not _same(source.facts[k], twin.facts[k])),
                "hidden_fact_only": False}
        metadata["source_aliases"] = []
        if generation == "seat_v3":
            prefix = f"seat_v3.{ctx['panel']}."
            if source.case_id.startswith(prefix):
                metadata["source_aliases"].append({"case_id": source.case_id[len(prefix):],
                    "kind": "legacy_selection_provenance", "separate_iid": False})
        if generation == "v5" and seat == "payments":
            metadata["payment_units_contract"] = _json(UNIT_CONTRACT)
        if ctx.get("customer_record_provenance") and "customer_contract_v6" not in ctx:
            if generation == "v5":
                rules, native_records = v5.provenance(source)
                metadata["native_customer_provenance"] = _json({"source_authorizations": rules, "records": native_records})
            elif generation == "v4":
                metadata["native_customer_provenance"] = _json({"records": v4.fact_records(source)})
        cases.append(Case(f"refund_v3.{generation}.{source.case_id}", pair_id, source.interaction.world_seed,
                          seat, cohort, source, source.case_id, _sha(asdict(source)), cluster_id,
                          "exposed_reserved" if reserved else "diagnostic" if diagnostic else "comparison",
                          "contrast", catalogue, intake, customer, records, supporting, ledger, (), metadata))
    behavior = [_native_behavior(c.source, seat, c.intake_contract) for c in cases]
    kind = "invariance" if _same(*behavior) else "contrast"
    # Native contracts that advertise a contrast must retain it after migration.
    effect = _context(a).get("pair_effect")
    if effect in ("observable_action_change", "disclosure_value_change", "confirmation_binding_change") and kind != "contrast":
        raise ValueError("Native behavior contrast was lost")
    changed = _diff(_view(cases[0]), _view(cases[1]))
    result = tuple(replace(c, pair_kind=kind, changed_paths=changed) for c in cases)
    if seat == "policy" and kind == "invariance":
        result = tuple(replace(c, role="diagnostic", metadata={**c.metadata,
                       "diagnostic_reason": "policy_outcome_invariance"})
                       if c.role == "comparison" else c for c in result)
    return result


def build_catalog(seed=401, include_reserved=True) -> tuple[Case, ...]:
    """Migrate each current source exactly once; reserved means exposed, not blind."""
    if type(seed) is not int or type(include_reserved) is not bool:
        raise ValueError("seed must be an integer and include_reserved a boolean")
    groups = [("unified", "policy", "policy", build_unified_panel(seed,
        include_policy_stress_extension=True, include_policy_frontier_extension=True,
        include_policy_frontier_hard_extension=True), False),
        ("normative", "policy", "policy", build_normative_panel(seed), True),
        ("compositions", "policy", "policy", build_policy_composition_panel(seed), False)]
    operational = build_operational_extension_panel(seed)
    for seat in ("intake", "payments"):
        groups.append(("operational", seat, seat, tuple(c for c in operational
                       if c.interaction.scenario.startswith(seat + "_")), False))
    for generation, module in (("seat_v3", seat_v3), ("v4", v4), ("v5", v5), ("v621", v621), ("v71", v71)):
        panels = module.build_panels(seed) if module is seat_v3 else module.build_panels(seed, include_holdout=include_reserved)
        for panel, sources in panels.items():
            groups.append((generation, panel, "policy" if panel == "common" else panel, sources, panel == "common"))
    result = []
    for generation, panel, seat, sources, diagnostic in groups:
        pairs = defaultdict(list)
        for source in sources:
            pairs[source.interaction.pair_id].append(source)
        for pair in pairs.values():
            if len(pair) != 2:
                raise ValueError("Every migrated source pair must have two members")
            result.extend(_migrate_pair(pair, generation, panel, seat, diagnostic))
    # Do not remove a difficult/negative world to manufacture a balanced cohort.
    cohorts = defaultdict(list)
    for c in result:
        if c.role == "comparison" and c.seat == "payments":
            cohorts[c.cohort].append(c)
    violating = {name for name, group in cohorts.items()
                 if sum(c.metadata["no_op"] for c in group) / len(group) > .25}
    if violating != set(contracts.PAYMENT_QUARANTINE_COHORTS):
        raise ValueError("Whole-cohort Payments admission drift; new design admission required")
    result = [replace(c, role="diagnostic", metadata={**c.metadata, "diagnostic_reason": "cohort_no_op_rate_exceeds_0.25"})
              if c.role == "comparison" and c.seat == "payments" and c.cohort in violating else c for c in result]
    if len({c.case_id for c in result}) != len(result):
        raise ValueError("Duplicate migration identities")
    return tuple(result)


def payload(case) -> dict[str, Any]:
    """Return a detached, closed, JSON-only payload."""
    return {"version": VERSION, "case": _json(asdict(case)),
            "rendered_policy_contract": render_policy_contract(case.source)}


def case_from_payload(raw) -> Case:
    """Validate local normalization and seals; never rebuild the source catalogue."""
    try:
        if not isinstance(raw, Mapping) or set(raw) != {"version", "case", "rendered_policy_contract"} or raw["version"] != VERSION:
            raise ValueError("Unexpected V3 payload keys/version")
        value = raw["case"]
        if not isinstance(value, Mapping) or set(value) != {f.name for f in fields(Case)}:
            raise ValueError("Unexpected V3 case keys")
        source = decode_source(value["source"])
        if value["source_sha256"] != _sha(asdict(source)) or value["source_case_id"] != source.case_id:
            raise ValueError("Source identity/hash mismatch")
        meta = value["metadata"]
        twin = decode_source(meta["twin_source"])
        if meta["twin_sha256"] != _sha(asdict(twin)) or source.case_id == twin.case_id:
            raise ValueError("Twin identity/hash mismatch")
        if source.interaction.pair_id != twin.interaction.pair_id or source.interaction.world_seed != twin.interaction.world_seed:
            raise ValueError("Twin does not belong to the source pair")
        if value["seat"] not in SEATS or value["role"] not in ROLES or value["pair_kind"] not in PAIR_KINDS:
            raise ValueError("Unknown seat/role/pair kind")
        # Re-normalizing a single stored pair is inexpensive and checks every
        # contract, record and migration metadata field without catalogue search.
        expected = _migrate_pair((source, twin), meta["generation"], meta["source_panel"],
                                 value["seat"], meta["diagnostic_origin"])[0]
        if (expected.role == "comparison" and expected.seat == "payments"
                and expected.cohort in contracts.PAYMENT_QUARANTINE_COHORTS):
            expected = replace(expected, role="diagnostic", metadata={**expected.metadata,
                               "diagnostic_reason": "cohort_no_op_rate_exceeds_0.25"})
        if not _same(value, asdict(expected)):
            raise ValueError("V3 normalized contracts/metadata mismatch")
        if raw["rendered_policy_contract"] != render_policy_contract(source):
            raise ValueError("Rendered policy contract mismatch")
        return expected
    except (KeyError, TypeError, AttributeError, AssertionError) as exc:
        raise ValueError("Invalid V3 case payload") from exc


def migration_inventory():
    """Explicit source coverage, alias provenance, and supersession boundaries."""
    cases = build_catalog()
    aliases = []
    for seat, builder in (("intake", seat_v3.build_intake_challenge_cases),
                          ("payments", seat_v3.build_payment_smoke_cases),
                          ("customer", seat_v3.build_customer_integrity_cases)):
        for original in builder(401):
            matches = [c for c in cases if c.metadata["generation"] == "seat_v3" and c.seat == seat
                       and c.source.interaction.scenario == original.interaction.scenario
                       and c.source.interaction.variant == original.interaction.variant]
            if len(matches) != 1:
                raise ValueError("Legacy selection must map to exactly one migrated case")
            aliases.append({"source": original.case_id, "source_sha256": _sha(asdict(original)),
                            "canonical": matches[0].case_id, "selection": builder.__name__, "separate_iid": False})
    return {"version": VERSION, "seed": 401, "total": len(cases),
            "public_contract_revision": contracts.REVISION,
            "publication_intake_extensions": list(contracts.INTAKE_EXTENSION_COHORTS),
            "counts": dict(sorted(Counter(c.metadata["generation"] for c in cases).items())),
            "roles": dict(sorted(Counter(c.role for c in cases).items())),
            "aliases": aliases + [
                {"source": "legacy initial common seat selections", "canonical": "unified.policy", "separate_iid": False},
                {"source": "v5.1 payment units", "canonical": "v5.payments", "separate_iid": False}],
            "superseded": {"v6": "v621", "v61": "v621", "v62": "v621", "v7": "v71"},
            "reserved": {"included": True, "blind": False, "role": "exposed_reserved"},
            "cohort_redesign": {"revision": redesign.REVISION, "cohorts": list(redesign.COHORTS),
                "extra_independent_clusters": 0, "failed_predecessor": "artifacts/refund_v3_development_qc2"},
            "customer_normalization": "Native source payloads preserved; v71 customer histories extended and order-neutralized under declared redesign/2. Other native v6 records retained; pre-v6 provenance retained and twin values synthesized under V621 authority/as_of semantics.",
            "ledger_usage": "Native v4/v5 ledgers preserved; legacy data is metadata, recomputed from the confirmed proposal amount by the engine."}
