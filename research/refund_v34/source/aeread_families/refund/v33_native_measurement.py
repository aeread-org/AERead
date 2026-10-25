"""V3.3 typed native-only primary; original component validity stays explicit."""
from dataclasses import replace
from pathlib import Path
import hashlib
from . import v3_measurement as prior, v33_native as d


def ids():
    return {old: d.PRIMARY if name == "seat_strict" else f"refund_v33_native_{name}_leaf"
        for name, old in zip(prior.MEASUREMENTS, prior.LEAF_IDS)}


def family_manifest():
    raw = d.plain(prior.family_manifest())
    raw["family"].update(id=d.FAMILY, version=d.VERSION, plugin_id="aeread.refund_v33")
    raw["measurement"].update(primary_estimand="refund_v33_native_seat_strict",
        primary_leaf_id=d.PRIMARY, admission_leaf_ids=[d.PRIMARY])
    for leaf in raw["measurement"]["leaves"]: leaf["leaf_id"] = ids()[leaf["leaf_id"]]
    raw["scoring"].update(scorer_id="refund_v33_native_measurement", oracle_id="refund_v33_native_environment")
    return prior.FamilyManifest.from_dict(raw)


def build_measurement_leaves(case):
    scorer = prior.ImplementationRef("refund_v33_native_measurement", d.VERSION, hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    impl = prior.ImplementationRef("refund_v33_native_environment", d.VERSION, hashlib.sha256(Path(d.__file__).read_bytes()).hexdigest())
    leaves = []
    for old in prior.build_measurement_leaves(case.base):
        name = old.estimand.estimand_id.replace("refund_v3_", "refund_v33_native_", 1)
        reference = replace(old.verifier.reference, reference_id=old.verifier.reference.reference_id.replace("refund_v3", "refund_v33_native", 1),
            reference_version=d.VERSION, source_sha256=d.digest(d.payload(case)), implementation=impl)
        domain = replace(old.estimand.validity_domain, domain_id="refund_v33_native_terminal", domain_version=d.VERSION,
            schema_ref="refund_v33_native/terminal", predicate=scorer)
        leaves.append(replace(old, leaf_id=ids()[old.leaf_id], leaf_version=d.VERSION, scorer=scorer,
            estimand=replace(old.estimand, estimand_id=name, estimand_version=d.VERSION, validity_domain=domain),
            verifier=replace(old.verifier, reference=reference)))
    return tuple(leaves)


def build_scorer(case):
    score = prior.build_scorer(case)
    leaves = dict(zip(prior.LEAF_IDS, build_measurement_leaves(case)))
    def evaluate(scoring_input, *, evidence_refs=()):
        result = score(scoring_input, evidence_refs=evidence_refs)
        return prior.FamilyScoreSet(d.PRIMARY, tuple(replace(s, leaf=leaves[s.leaf.leaf_id]) for s in result.scores), (d.PRIMARY,))
    return evaluate
