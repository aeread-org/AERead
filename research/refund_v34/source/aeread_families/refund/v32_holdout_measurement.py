"""New release identities, unchanged full-claim measurement semantics."""
from dataclasses import replace
from pathlib import Path
import hashlib
from . import v3_lifecycle_measurement as parent
from . import v32_holdout as d


def family_manifest():
    raw=d.detach(parent.family_manifest())
    raw["family"].update(id=d.FAMILY,version=d.VERSION,plugin_id="aeread.refund_v32")
    raw["measurement"].update(primary_estimand="refund_v32_complete_claim_compliance",
        leaves=[dict(leaf_id=d.PRIMARY,scope="finalize_time",seat_scope="subject_seat")],
        primary_leaf_id=d.PRIMARY,admission_leaf_ids=[d.PRIMARY])
    raw["scoring"].update(scorer_id="refund_v32_measurement",oracle_id="refund_v32_environment")
    return parent.native.FamilyManifest.from_dict(raw)


def build_measurement_leaves(case):
    leaf=parent.build_measurement_leaves(d.parent.Case(case.base))[0]
    implementation=parent.ImplementationRef("refund_v32_measurement",d.VERSION,hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    reference=replace(leaf.verifier.reference,reference_id="refund_v32_reference",reference_version=d.VERSION,
        source_sha256=d.digest(d.payload(case)),implementation=parent.ImplementationRef("refund_v32_environment",d.VERSION,
        hashlib.sha256(Path(d.__file__).read_bytes()).hexdigest()))
    return (replace(leaf,leaf_id=d.PRIMARY,leaf_version=d.VERSION,scorer=implementation,
        estimand=replace(leaf.estimand,estimand_id="refund_v32_complete_claim_compliance",estimand_version=d.VERSION,
            validity_domain=replace(leaf.estimand.validity_domain,domain_id="refund_v32_terminal",domain_version=d.VERSION,
                schema_ref="refund_v32/terminal",predicate=implementation)),verifier=replace(leaf.verifier,reference=reference)),)


def build_scorer(case):
    old=parent.build_scorer(d.parent.Case(case.base))
    leaf=build_measurement_leaves(case)[0]
    def score(scoring_input,*,evidence_refs=()):
        result=old(scoring_input,evidence_refs=evidence_refs)
        scores=tuple(replace(s,leaf=leaf) for s in result.scores)
        return parent.FamilyScoreSet(d.PRIMARY,scores,(d.PRIMARY,))
    return score
