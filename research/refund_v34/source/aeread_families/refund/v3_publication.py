"""Structural publication preflight, deliberately NOT normative admission.

Exposure is irrevocable here. Development data cannot be relabeled a blind
holdout, and a structural audit cannot substitute for model or external evidence.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from . import v3_cases as cases, v3_contracts as law


def world_signature(c):
    """Whole task modulo opaque ledger-snapshot renaming, including lifecycle.

    _view removes snapshot identifiers, NOT snapshot content or delivery state.
    Equality is a declared task equivalence, not byte equality of raw transcripts.
    """
    ctx = getattr(c.source, "seat_context", {})
    return cases._sha({"seat": c.seat, "world": cases._view(c),
        "category": c.source.product_category,
        "claim": c.source.interaction.public_claim,
        "financial_inputs": {"item_net_price": c.source.interaction.item_net_price,
                             "allocated_tax": c.source.interaction.allocated_tax},
        "branch_specification": cases.spec_for(c.source.interaction.scenario).to_dict(),
        "policy": cases.render_policy_contract(c.source),
        "overlapping_disclosure": bool(ctx.get("overlapping_disclosure")),
        "sequential_proposals": bool(ctx.get("sequential_proposals"))})


def publication_selection(catalogs):
    """Reject task aliases prospectively, without inspecting any control outcome.

    Lexicographic (cohort, pair-template) order chooses a representative. An
    overlapping pair template is excluded at ALL planned seeds if either twin
    duplicates a retained task at ANY same seed. Never keep only a favorable
    twin. Native roles remain migration/coverage roles, not publication admission.
    """
    templates = defaultdict(lambda: defaultdict(list))
    for seed, panel in catalogs.items():
        for c in panel:
            if c.role == "comparison":
                template = c.pair_id.removesuffix("." + str(c.seed))
                templates[(c.cohort, template)][seed].append(c)
    retained, aliases, seen = [], [], {}
    for key, seeds in sorted(templates.items()):
        if set(seeds) != set(catalogs) or any(len(pair) != 2 for pair in seeds.values()):
            raise ValueError("Publication requires a complete paired seed matrix")
        conflicts = []
        for seed, pair in seeds.items():
            for c in pair:
                signature = world_signature(c)
                if (seed, signature) in seen:
                    canonical = seen[seed, signature]
                    if canonical.cluster_id != c.cluster_id:
                        raise ValueError("Exact duplicate assigned to independent clusters")
                    conflicts.append({"case_id": c.case_id, "canonical_case_id": canonical.case_id})
        if conflicts:
            aliases.append({"cohort": key[0], "pair_template": key[1],
                "reason": "exact_task_overlap_with_retained_pair_template",
                "excluded_case_ids": sorted(c.case_id for pair in seeds.values() for c in pair),
                "overlap_witnesses": sorted(conflicts, key=lambda row: row["case_id"])})
        else:
            for seed, pair in seeds.items():
                for c in pair:
                    signature = world_signature(c)
                    if (seed, signature) in seen:
                        raise ValueError("Comparison twins are exact task duplicates")
                    seen[seed, signature] = c
                    retained.append(c)
    return {"rule": "refund_v3_normalized_task_pair_dedup/1",
        "canonical_order": "lexicographic cohort then source pair-template; no scores consulted",
        "equivalence": "identical normalized world/financial inputs/branches/lifecycle, modulo bijective opaque ledger-snapshot renaming; redelivery identity distinctions preserved",
        "eligible_case_ids": sorted(c.case_id for c in retained),
        "eligible_variants_by_seed": {str(seed): sum(c.seed == seed for c in retained) for seed in catalogs},
        "eligible_independent_clusters": len({c.cluster_id for c in retained}),
        "structural_alias_pairs": aliases,
        "source_roles_unchanged": True, "model_headroom": "not_run", "admission": "blocked"}


def design_preflight(catalogs):
    if not catalogs or any(not panel for panel in catalogs.values()):
        raise ValueError("Explicit nonempty seed panels required")
    signatures, pairs, identifiers = defaultdict(list), defaultdict(list), set()
    roles, seats, clusters, excluded = Counter(), Counter(), set(), []
    for seed, panel in catalogs.items():
        for c in panel:
            if c.seed != seed or c.case_id in identifiers:
                raise ValueError("Duplicate identity or wrong seed")
            identifiers.add(c.case_id)
            # Reconstruct single stored pairs, not a fresh panel; validates
            # roles, source pins, contracts and declared minimal interventions.
            cases.case_from_payload(cases.payload(c))
            if c.metadata["public_contract_revision"] != law.REVISION:
                raise ValueError("Wrong public contract revision")
            if c.metadata["blind"] is not False:
                raise ValueError("Exposed development cannot be blind holdout")
            if c.intake_contract["rule"] != law.INTAKE_RULE or c.customer_contract["rule"] != law.CUSTOMER_RULE:
                raise ValueError("Public contract mismatch")
            if {r["cost"] for r in c.catalogue} != {1}:
                raise ValueError("Policy retrieval price may not encode relevance")
            roles[c.role] += 1
            seats[c.seat] += 1
            clusters.add(c.cluster_id)
            pairs[c.pair_id].append(c)
            signature = world_signature(c)
            signatures[signature].append(c)
            if c.role != "comparison":
                excluded.append({"case_id": c.case_id, "role": c.role,
                    "reason": "developmentally_exposed_reserved" if c.role == "exposed_reserved"
                    else c.metadata.get("diagnostic_reason", "diagnostic_source_panel")})
    for group in pairs.values():
        if len(group) != 2 or group[0].role != group[1].role:
            raise ValueError("Incomplete pair or split pair role")
        if group[0].changed_paths != cases._diff(cases._view(group[0]), cases._view(group[1])):
            raise ValueError("Counterfactual changes disagree")
    # Pair completeness alone cannot detect deleting a whole source pair or
    # selectively changing admission roles. Regenerate the declared full panel
    # before computing ANY sampling selection or qualification denominator.
    for seed, panel in catalogs.items():
        canonical = cases.build_catalog(seed)
        expected = {c.case_id: cases.payload(c) for c in canonical}
        observed = {c.case_id: cases.payload(c) for c in panel}
        if observed != expected:
            raise ValueError("Frozen full-panel membership or whole-cohort admission mismatch")
    duplicates = []
    for signature, group in signatures.items():
        if len(group) < 2:
            continue
        if len({c.cluster_id for c in group}) != 1:
            raise ValueError("Exact duplicate assigned to independent clusters")
        duplicates.append({"content_sha256": signature, "cluster_id": group[0].cluster_id,
                           "case_ids": sorted(c.case_id for c in group)})
    return {"artifact_type": "refund_v3_development_design_preflight",
        "design_revision": law.REVISION, "structural_checks": "passed",
        "cases": len(identifiers), "pairs": len(pairs), "independent_source_clusters": len(clusters),
        "seeds": list(catalogs), "roles": dict(sorted(roles.items())),
        "target_seats": dict(sorted(seats.items())), "within_cluster_duplicates": duplicates,
        "qualification_exclusions": excluded, "blind_holdout_cases": 0,
        "publication_selection": publication_selection(catalogs),
        "scope": "scripted-background, single-active-seat; no live-counterpart or cross-seat model-ranking claim",
        "publication_ready": False, "normative_status": "partial",
        "required_external_or_empirical_evidence": ["actual_scored_model_headroom_and_dispersion",
            "fresh_exposure_audited_holdout", "complete_independent_oracle_and_mutation_coverage",
            "trusted_CI_and_six_resource_ceiling_admission", "authenticated_external_review",
            "powered_prespecified_confirmatory_campaign"],
        "paid_calls_authorized": False}
