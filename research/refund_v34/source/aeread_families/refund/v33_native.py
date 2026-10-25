"""Native-seat repair, no appended common lifecycle and no manufactured margins.

All V3.2 source rows remain reconstructible. Publication selection is a new,
development-only whole-pair view, independent of model/control outcomes.
"""
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
import copy
import hashlib
import json

from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.task.scheduler import TransitionResult
from . import v32_holdout as origin
from . import v3_environment as env, v3_lifecycle as reference_impl
from . import v3_lifecycle_controls as controls

VERSION = "3.3.0"
REVISION = "refund_v33_native_discrimination/1"
FAMILY = "refund_v33_native"
PRIMARY = "refund_v33_native_seat_strict_leaf"
SEEDS = origin.SEEDS
SEATS = origin.native.SEATS
digest, plain = env.digest, env.plain


@dataclass(frozen=True)
class Case:
    origin: origin.Case
    base: origin.native.Case
    repair: str = "inherited"
    consent: object = None
    changed_paths: tuple = ()

    def __getattr__(self, name):
        return getattr(self.base, name)

    @property
    def case_id(self): return "refund_v33." + self.base.case_id
    @property
    def pair_id(self): return "refund_v33." + self.base.pair_id


def default_consent(base):
    return dict(maximum_amount=round(base.source.interaction.item_net_price + base.source.interaction.allocated_tax, 2),
        permitted_refund_methods=["original_payment", "none"],
        permitted_shipping_payers=["seller", "none"])


def reference(seat, obs):
    return reference_impl.reference(seat, obs)


def projection(case):
    """Conservative focal-input identity; omits unobserved other-seat payloads.

Includes future requestable evidence/transition dependencies, not just the first
observation. It does not equate differently worded laws by model outcomes.
"""
    b = case.base
    common = dict(seat=case.seat, public_claim=b.source.interaction.public_claim)
    binding = plain(getattr(b.source, "seat_context", {}).get("proposal_binding_v7", {}))
    if case.seat == "intake":
        return dict(**common, collection_contract=plain(b.intake_contract))
    if case.seat == "policy":
        return dict(**common, policy_contract=env.render_policy_contract(b.source),
            branch_specification=env.old.spec_for(b.source.interaction.scenario).to_dict(),
            financial_inputs=env.public_policy(b), catalogue=plain(b.catalogue),
            fact_types=env.fact_types(b), requestable_values={**b.source.facts, **b.supporting_facts},
            scripted_intake_contract=plain(b.intake_contract), proposal_binding=binding)
    proposal = {**asdict(env.resolve_policy(b.source)), "proposal_id": binding.get("current_id", "proposal_1")}
    proposal["reason_code"] = proposal["policy_basis"]
    if case.seat == "payments":
        return dict(seat=case.seat, observation=env.payment_observation(b, proposal))
    return dict(**common, records=plain(b.records), source_contract=plain(b.customer_contract),
        private_consent=plain(case.consent), pending_proposal=proposal, proposal_binding=binding,
        sequential_proposals=bool(getattr(b.source, "seat_context", {}).get("sequential_proposals")),
        request_catalogue=plain(b.catalogue), scripted_intake_contract=plain(b.intake_contract))


def view(case):
    return dict(native=origin.native._view(case.base),
        private_consent=plain(case.consent) if case.seat == "customer" else None)


def _positive_source(cases, seat):
    # A fixed law/branch template, not a losing model or a passing shortcut.
    return next(c for c in sorted(cases, key=lambda c: c.case_id)
        if c.seat == seat and c.base.source.interaction.scenario == "wrong_item_received"
        and env.resolve_policy(c.base.source).amount > 0)


def _targeted(cases, seed):
    result = []
    for seat, repairs in (("customer", ("consent_amount_limit", "consent_shipping")),
                          ("intake", ("prerequisite_value", "source_authorization")),
                          ("payments", ("processor_correction", "uncertain_scope"))):
        parent = (_positive_source(cases, seat) if seat != "intake" else next(c for c in cases
            if c.seat == seat and c.base.source.interaction.scenario == "intake_identity_branch"))
        for repair in repairs:
            for variant in (0, 1):
                b = replace(parent.base, case_id=f"targeted.{seat}.{repair}.{variant}.{seed}",
                    pair_id=f"targeted.{seat}.{repair}.{seed}", role="comparison",
                    cohort="v33_" + repair, metadata={**parent.base.metadata, "v33_targeted": repair})
                consent = default_consent(b) if seat == "customer" else None
                if seat == "customer":
                    if repair == "consent_amount_limit" and variant:
                        consent["maximum_amount"] = round(consent["maximum_amount"] - .01, 2)
                    elif repair == "consent_shipping":
                        consent["permitted_shipping_payers"] = ["buyer", "none"] if variant else ["seller", "none"]
                elif seat == "intake":
                    c = copy.deepcopy(b.intake_contract)
                    c.update(catalogue=[
                        dict(fact_id="order_serial", source="work_order", requires=[], cost=1, utility=0, material=True),
                        dict(fact_id="inspection_serial", source="warehouse_audit" if repair == "source_authorization" else "work_order",
                             requires=["order_serial"], cost=2, utility=5 if repair == "prerequisite_value" and variant else 13, material=True),
                        dict(fact_id="defect_evidence", source="work_order", requires=[], cost=2, utility=7, material=True)],
                        total_budget=3, max_batch_size=1, max_rounds=2,
                        authorized_sources=["work_order", "warehouse_audit"] if repair == "source_authorization" and variant else ["work_order"])
                    b = replace(b, intake_contract=c)
                else:
                    total = round((b.source.interaction.item_net_price + b.source.interaction.allocated_tax) * 100)
                    scope = dict(order_id="native_order", line_item_id="native_line", currency="USD")
                    def row(rev, status, amount, key):
                        return dict(event_id="processor_event", revision=rev, status=status, amount_cents=amount,
                            idempotency_key=key, allocations_cents=[dict(instrument="card", amount_cents=amount)], **scope)
                    if repair == "processor_correction":
                        records = [row(1, "settled", total // 3, "previous_credit"),
                                   row(2, "settled" if variant else "reversed", total // 3, "previous_credit")]
                    else:
                        records = [row(1, "unknown", total, "native_credit")]
                        if variant: records[0]["order_id"] = "foreign_order"
                    ledger = dict(kind="v5", data=dict(scope=scope, snapshot_id="native_snapshot", idempotency_key="native_credit",
                        records=records, tenders=[dict(instrument="card", priority=0, capacity_cents=total // 2, open=True, fallback="bank"),
                            dict(instrument="wallet", priority=1, capacity_cents=total, open=True, fallback="bank")]))
                    b = replace(b, ledger=ledger)
                result.append(Case(parent, b, repair, consent))
    return result


@lru_cache(None)
def build_catalog(seed=SEEDS[0]):
    originals = origin.build_catalog(seed)
    cases = [Case(c, c.base, consent=default_consent(c.base) if c.seat == "customer" else None) for c in originals]
    cases.extend(_targeted(originals, seed))
    pairs = defaultdict(list)
    for i, c in enumerate(cases): pairs[c.pair_id].append(i)
    for indices in pairs.values():
        if len(indices) != 2: raise ValueError("V3.3 requires complete pairs")
        a, b = (cases[i] for i in indices)
        changes = tuple(origin.native._diff(view(a), view(b)))
        for i in indices: cases[i] = replace(cases[i], changed_paths=changes)
    return tuple(cases)


@lru_cache(None)
def admission():
    """Whole-pair selection, before any model/control results; global dedup."""
    groups = defaultdict(list)
    for seed in SEEDS:
        for c in build_catalog(seed): groups[c.pair_id].append(c)
    seen, records = {}, {}
    ordered = sorted(groups.values(), key=lambda xs: (xs[0].seed, xs[0].repair == "inherited", xs[0].pair_id))
    for members in ordered:
        a, b = sorted(members, key=lambda c: c.case_id)
        hashes = [digest(projection(c)) for c in (a, b)]
        collisions = sorted({seen[h] for h in hashes if h in seen})
        if any(c.base.role != "comparison" for c in members): reason = "protected_source_role"
        elif hashes[0] == hashes[1]: reason = "no_focal_input_contrast"
        elif collisions: reason = "whole_pair_input_overlap"
        else: reason = "comparison"
        for c, h in zip((a, b), hashes):
            records[c.case_id] = dict(case_id=c.case_id, pair_id=c.pair_id, seat=c.seat, seed=c.seed,
                source_role=c.base.role, role="comparison" if reason == "comparison" else "diagnostic",
                reason=reason, canonical_overlaps=collisions, focal_input_sha256=h, cluster_id=c.cluster_id)
        if reason == "comparison":
            for h in hashes: seen[h] = a.pair_id
    return MappingProxyType({key: MappingProxyType({**row, "canonical_overlaps": tuple(row["canonical_overlaps"])})
        for key, row in records.items()})


def payload(case):
    return dict(version=VERSION, base=plain(asdict(case.base)), origin_case_id=case.origin.case_id,
        repair=case.repair, private_consent=plain(case.consent), changed_paths=list(case.changed_paths),
        design_contract=dict(revision=REVISION, split="development_exposed", native_primary=True,
            common_lifecycle=False, source_role=case.base.role, admission=plain(admission()[case.case_id]),
            external_approval=False))


def decode(raw):
    if set(raw) != {"version", "base", "origin_case_id", "repair", "private_consent", "changed_paths", "design_contract"} or raw["version"] != VERSION:
        raise ValueError("Unexpected V3.3 payload")
    raw = plain(raw)
    candidates = [c for c in build_catalog(raw["base"]["seed"]) if c.base.case_id == raw["base"]["case_id"]]
    if len(candidates) != 1 or payload(candidates[0]) != raw: raise ValueError("V3.3 closed reconstruction failed")
    return candidates[0]


def episode_contract(case, arm="reference"):
    previous, old_manifest = origin.episode_contract(case.origin, arm)
    raw = plain(old_manifest)
    raw.update(case_id=case.case_id, family_id=FAMILY, family_version=VERSION, split="dev",
        visibility_policy="refund_v33_native_four_seat", payload=payload(case),
        provenance=dict(generator_id=FAMILY, generator_version=VERSION, review_status="generated"), content_sha256="0" * 64)
    raw["content_sha256"] = case_content_sha256(raw)
    manifest = CaseManifest.from_dict(raw)
    cell = replace(previous, case_id=case.case_id, case_sha256=manifest.content_sha256,
        family_id=FAMILY, family_version=VERSION, pair_id=case.pair_id, paired_fields={"pair_id": case.pair_id},
        cell_id="refund_v33_" + digest(dict(case=manifest.content_sha256, arm=arm, revision=REVISION))[:32])
    return cell, manifest


class Plugin(env.RefundV3Plugin):
    def validate_payload(self, raw): return decode(raw)
    def generator(self): return build_catalog
    def build_reference_providers(self, case): return ()
    def build_scorer(self, case):
        from .v33_native_measurement import build_scorer
        return build_scorer(case)

    def observe(self, case, state, seat, phase):
        obs = super().observe(case, state, seat, phase)
        if seat == "customer" and phase.phase_id == "customer_confirmation" and case.seat == "customer":
            obs.update(private_consent=plain(case.consent),
                confirmation_contract="Reject the CURRENT proposal if amount, refund method or shipping payer violates private consent; otherwise confirm its current ID and exact five terms. Archived consent does not authorize current terms.")
        return obs

    def parse_action(self, case, state, seat, phase, response):
        from aeread.shared_runner.task.execution import CanonicalResponse
        if isinstance(response, CanonicalResponse): response = response.text
        return super().parse_action(case, state, seat, phase, response)

    def step(self, case, state, phase, actions):
        result = super().step(case, state, phase, actions)
        if phase.phase_id == "customer_confirmation" and case.seat == "customer":
            new = plain(result.state)
            event = new["events"][-1]
            if event["valid"]:
                expected = reference("customer", self.observe(case, state, "customer", phase))
                event["quality"] = float(event["action"]["raw"] == expected)
            return TransitionResult(new, result.next_phase_id)
        return result


def sources():
    return {**origin.sources(), **{name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ("v33_native.py", "v33_native_measurement.py")}}


async def execute(case, arm="reference", tape=None, certify=False):
    from aeread.shared_runner.task.scheduler import run_episode
    cell, manifest = episode_contract(case, arm)
    transcript, checks, memory = [], [], {}
    async def response(request):
        obs, seat = plain(request.observation), request.seat_id
        if tape is not None:
            row = tape[len(transcript)]
            if row["seat"] != seat or row["observation"] != obs: raise ValueError("Native replay observation drift")
            text = row["response"]
        else:
            action = controls.action(seat, obs, arm, memory) if seat == case.seat else reference(seat, obs)
            if certify:
                if seat == "intake":
                    if reference_impl.independent.intake_objective(obs) != env.intake_plan(obs)[:2]: raise ValueError("Intake independent objective mismatch")
                elif action != reference_impl.independent_action(seat, obs): raise ValueError("Independent native reference mismatch")
                checks.append(dict(seat=seat, phase=request.phase_id, observation_sha256=digest(obs)))
            text = json.dumps(action, allow_nan=False)
        transcript.append(dict(seat=seat, observation=obs, phase=request.phase_id, response=text))
        return text
    result = await run_episode(cell=cell, case=manifest, plugin=Plugin(), response_source=response)
    if tape is not None and len(tape) != len(transcript): raise ValueError("Unused native replay tape")
    errors = [a.parse.error_code for p in result.phase_instances for a in p.actions if not a.parse.ok]
    out = plain(result.outcome)
    return dict(case_id=case.case_id, arm=arm, seat=case.seat, seed=case.seed,
        strict=None if errors else out["seat_strict"][case.seat], validity=not errors,
        outcome=out, state=plain(result.final_state), transcript=transcript, independent_checks=checks, parse_errors=errors)


async def verify_replay(case, record):
    replay = await execute(case, record["arm"], tape=record["transcript"])
    replay["independent_checks"] = record["independent_checks"]
    if replay != record: raise ValueError("Native exact replay mismatch")
