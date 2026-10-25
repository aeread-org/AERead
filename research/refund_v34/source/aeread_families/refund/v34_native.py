"""V3.4: versioned attribution repair; V3.3 sources/results stay immutable.

Same seat observations, actions and transition guards. Two typed component
attributions are repaired; one non-decisive intake pair becomes diagnostic.
No provider adapter, formal admission or publication approval is implied.
"""
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
import hashlib
import json

from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.task.scheduler import TransitionResult
from . import v33_native as prior

VERSION = "3.4.0"
REVISION = "refund_v34_attribution_and_pair_disposition/1"
FAMILY = "refund_v34_native"
PRIMARY = "refund_v34_native_seat_strict_leaf"
SEEDS, SEATS = prior.SEEDS, prior.SEATS
env, plain, digest, reference = prior.env, prior.plain, prior.digest, prior.reference
NONDECISIVE_SOURCE_PAIR = "seat_v5_intake_dependencies"


@dataclass(frozen=True)
class Case(prior.Case):
    @property
    def case_id(self): return "refund_v34." + self.base.case_id
    @property
    def pair_id(self): return "refund_v34." + self.base.pair_id


def parent(case):
    return prior.Case(case.origin, case.base, case.repair, case.consent, case.changed_paths)


@lru_cache(None)
def build_catalog(seed=SEEDS[0]):
    return tuple(Case(c.origin, c.base, c.repair, c.consent, c.changed_paths)
        for c in prior.build_catalog(seed))


@lru_cache(None)
def admission():
    records = {}
    old = prior.admission()
    for seed in SEEDS:
        for c in build_catalog(seed):
            row = plain(old[parent(c).case_id])
            # Match the source pair identity, never any model outcome. Apply
            # equally to every world seed, preserving pre-existing exclusions.
            if NONDECISIVE_SOURCE_PAIR in c.base.pair_id and row["role"] == "comparison":
                row.update(role="diagnostic", reason="shared_optimal_intake_plan")
            row.update(case_id=c.case_id, pair_id=c.pair_id,
                parent_case_id=parent(c).case_id, parent_pair_id=parent(c).pair_id,
                canonical_overlaps=tuple(row["canonical_overlaps"]))
            records[c.case_id] = MappingProxyType(row)
    return MappingProxyType(records)


def payload(case):
    return dict(version=VERSION, parent_payload=prior.payload(parent(case)),
        revision=REVISION, admission=plain(admission()[case.case_id]),
        publication_qc=False, external_approval=False)


def decode(raw):
    if raw.get("version") != VERSION:
        raise ValueError("Unexpected V3.4 version")
    original = prior.decode(raw["parent_payload"])
    case = next(c for c in build_catalog(original.seed) if c.base.case_id == original.base.case_id)
    if payload(case) != plain(raw):
        raise ValueError("V3.4 closed reconstruction mismatch")
    return case


def episode_contract(case, arm="reference"):
    old_cell, old_manifest = prior.episode_contract(parent(case), arm)
    raw = plain(old_manifest)
    raw.update(case_id=case.case_id, family_id=FAMILY, family_version=VERSION,
        visibility_policy="refund_v34_native_four_seat", payload=payload(case),
        provenance=dict(generator_id=FAMILY, generator_version=VERSION, review_status="generated"),
        content_sha256="0" * 64)
    raw["content_sha256"] = case_content_sha256(raw)
    manifest = CaseManifest.from_dict(raw)
    cell = replace(old_cell, case_id=case.case_id, case_sha256=manifest.content_sha256,
        family_id=FAMILY, family_version=VERSION, pair_id=case.pair_id,
        paired_fields={"pair_id": case.pair_id},
        cell_id="refund_v34_" + digest(dict(case=manifest.content_sha256, arm=arm, revision=REVISION))[:32])
    return cell, manifest


def binding_credit(action, observation):
    """ID binding only. Capacity, duplication and allocation are separate."""
    if not action:
        return None
    ledger, proposal = observation["payment_ledger"], observation["confirmed_proposal"]
    expected = dict(proposal_id=proposal["proposal_id"], idempotency_key=ledger["idempotency_key"],
        ledger_snapshot_id=ledger.get("snapshot_id", ledger.get("ledger_snapshot_id")))
    if any(v is None for v in expected.values()):
        return None
    return float(all(action.get(k) == v for k, v in expected.items()))


def initial_intake_observation(case):
    plugin = Plugin()
    phase = next(p for p in plugin.phases(case) if p.phase_id == "intake_request")
    # Canonical initial public state, never a missing-event/default-zero target.
    return plugin.observe(case, plugin.initial_state(case, None), "intake", phase)


def assess(case, state):
    out = plain(env.assess(case, state))
    events, metrics, coverage = state["events"], out["metrics"], out["coverage"]
    intake = [e for e in events if e["seat"] == "intake"]
    if intake:
        target = env.intake_plan(initial_intake_observation(case))[:2]
        actual = (state["intake_utility"], state["intake_cost"])
        metrics["intake_planning"] = float(actual == target)
        coverage["intake_planning"] = 1.0
    payments = [e for e in events if e["phase"] == "payments_execute"]
    if payments:
        # Missing/unparsed binding is unknown, never an imputed failure/success.
        values = [e.get("binding") for e in payments]
        known = all(type(v) in (int, float) and v in (0, 1) for v in values)
        metrics["payment_binding"] = sum(values) / len(values) if known else None
        coverage["payment_binding"] = float(known)
    fields = dict(policy=("policy_semantic", "workflow", "contract", "evidence"),
        intake=("intake_planning",), customer=("customer_disclosure", "customer_confirmation"),
        payments=("payment_binding",))
    strict = {seat: float(all(coverage.get(k) == 1 and metrics[k] == 1 for k in names)
        and not any(not e["valid"] for e in events if e["seat"] == seat)) for seat, names in fields.items()}
    strict["payments"] *= float(out["payment_conditional_execution"] == 1)
    out["seat_strict"] = strict
    out["system_strict"] = float(all(any(e["seat"] == seat for e in events) for seat in SEATS)
        and all(strict.values()) and metrics["payment_execution"] == 1 and not state["failures"])
    taxonomy = set(out["taxonomy"])
    for name in ("intake_planning", "payment_binding"):
        taxonomy.discard(name + "_failure")
        if coverage.get(name) and metrics[name] != 1:
            taxonomy.add(name + "_failure")
    out["taxonomy"] = sorted(taxonomy)
    return out


class Plugin(prior.Plugin):
    def validate_payload(self, raw): return decode(raw)
    def generator(self): return build_catalog
    def build_scorer(self, case):
        from .v34_native_measurement import build_scorer
        return build_scorer(case)

    def step(self, case, state, phase, actions):
        result = super().step(case, state, phase, actions)
        if phase.phase_id != "payments_execute":
            return result
        envelope = next(iter(actions.values()))
        new = plain(result.state)
        action = plain(envelope.parse.action) if envelope.parse.ok else None
        obs = self.observe(case, state, "payments", phase)
        credit = binding_credit(action, obs)
        if credit is None:
            new["events"][-1].pop("binding", None)
        else:
            new["events"][-1]["binding"] = credit
        return TransitionResult(new, result.next_phase_id)

    def outcome(self, case, terminal): return assess(case, terminal)


def sources():
    return {**prior.sources(), **{name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ("v34_native.py", "v34_native_measurement.py")}}


async def execute(case, tape=None, certify=False, action_source=None):
    """Offline scheduler execution; no provider construction and no paid mode."""
    from aeread.shared_runner.task.scheduler import run_episode
    from aeread.shared_runner.task.evaluation import FamilyScoringInput, SeatContext
    from .v34_native_measurement import build_scorer
    cell, manifest = episode_contract(case)
    transcript, checks = [], []
    async def response(request):
        obs, seat = plain(request.observation), request.seat_id
        if tape is not None:
            row = tape[len(transcript)]
            if row["seat"] != seat or row["observation"] != obs:
                raise ValueError("V3.4 reanalysis observation drift")
            text = row["response"]
        else:
            action = action_source(seat, obs, transcript) if action_source else reference(seat, obs)
            if certify:
                independent = prior.reference_impl.independent
                if seat == "intake":
                    if independent.intake_objective(obs) != env.intake_plan(obs)[:2]:
                        raise ValueError("Independent intake objective mismatch")
                elif action != prior.reference_impl.independent_action(seat, obs):
                    raise ValueError("Independent reference mismatch")
                checks.append(dict(seat=seat, observation_sha256=digest(obs)))
            text = json.dumps(action, allow_nan=False)
        transcript.append(dict(seat=seat, observation=obs, response=text))
        return text
    result = await run_episode(cell=cell, case=manifest, plugin=Plugin(), response_source=response)
    if tape is not None and len(tape) != len(transcript):
        raise ValueError("Unused source tape")
    data = FamilyScoringInput(outcome=result.outcome, phase_instances=result.phase_instances,
        evidence_refs=(), seat_context=SeatContext((case.seat,), cell.profile_by_seat))
    scores = build_scorer(case)(data)
    return dict(case_id=case.case_id, parent_case_id=parent(case).case_id,
        strict=result.outcome["seat_strict"][case.seat], outcome=plain(result.outcome),
        state=plain(result.final_state), transcript=transcript, independent_checks=checks,
        scores=plain(scores), admission=plain(admission()[case.case_id]))
