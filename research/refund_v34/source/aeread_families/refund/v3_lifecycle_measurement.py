"""Finalize-time lifecycle primary; native components remain separately visible."""
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
import hashlib

from aeread.shared_runner.measurement import (FamilyScoreSet, MetricValue, ScoreEnvelope,
    ValidityReport, ImplementationRef)
from . import v3_measurement as native
from . import v3_lifecycle as design


def family_manifest():
    def plain(value):
        from collections.abc import Mapping
        if is_dataclass(value): return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
        if isinstance(value, Mapping): return {k: plain(v) for k, v in value.items()}
        if isinstance(value, (tuple, list)): return [plain(v) for v in value]
        return value
    old = plain(native.family_manifest())
    old["family"].update(id=design.FAMILY, version=design.VERSION, plugin_id="aeread.refund_v31")
    old["environment"]["phase_specs"] += ["lifecycle_review", "lifecycle_disclosure"]
    old["measurement"].update(primary_estimand="refund_v31_complete_claim_compliance",
        leaves=[dict(leaf_id=design.PRIMARY, scope="finalize_time", seat_scope="subject_seat")],
        primary_leaf_id=design.PRIMARY, admission_leaf_ids=[design.PRIMARY])
    old["scoring"].update(scorer_id="refund_v31_measurement", oracle_id="refund_v31_environment")
    return native.FamilyManifest.from_dict(old)


def build_measurement_leaves(case):
    leaf = native.build_measurement_leaves(case.base)[0]
    implementation = ImplementationRef("refund_v31_measurement", design.VERSION, hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    reference = replace(leaf.verifier.reference, reference_id="refund_v31_reference", reference_version=design.VERSION,
        source_sha256=design.old.digest(design.payload(case)), implementation=ImplementationRef("refund_v31_environment", design.VERSION,
            hashlib.sha256(Path(design.__file__).read_bytes()).hexdigest()))
    return (replace(leaf, leaf_id=design.PRIMARY, leaf_version=design.VERSION, scorer=implementation,
                    estimand=replace(leaf.estimand, estimand_id="refund_v31_complete_claim_compliance", estimand_version=design.VERSION,
                        validity_domain=replace(leaf.estimand.validity_domain, domain_id="refund_v31_terminal",
                            domain_version=design.VERSION, schema_ref="refund_v31/terminal", predicate=implementation)),
                    verifier=replace(leaf.verifier, reference=reference)),)


def build_scorer(case):
    leaves = build_measurement_leaves(case)
    def score(scoring_input, *, evidence_refs=()):
        out = scoring_input.outcome
        reason = None
        for phase in scoring_input.phase_instances:
            for action in phase.actions:
                if not action.parse.ok: reason = "invalid_action_parse:" + action.parse.error_code
        if tuple(scoring_input.seat_context.subject_seats) != (case.seat,): reason = "unscored_crossseat_probe"
        value = out.get("seat_strict", {}).get(case.seat)
        if type(value) not in (int, float) or value not in (0, 1): reason = "invalid_primary_support"
        envelope = ScoreEnvelope(status="invalid_measurement" if reason else "ok", leaf=leaves[0],
            primary=None if reason else MetricValue(value, "pass", dict(native=out["native_seat_strict"],
                lifecycle=out["lifecycle_strict"], components=out["metrics"], coverage=out["coverage"],
                lifecycle_components=out["lifecycle_components"], role=case.seat, lifecycle_complete=out["lifecycle_complete"])),
            metrics={}, reference_values={"upper_bound": MetricValue(1, "pass")},
            validity=ValidityReport("invalid", (reason,)) if reason else ValidityReport("valid"),
            evidence_refs=evidence_refs or scoring_input.evidence_refs,
            utility_by_seat={} if reason else {case.seat: MetricValue(value, "pass")})
        return FamilyScoreSet(design.PRIMARY, (envelope,), (design.PRIMARY,))
    return score
