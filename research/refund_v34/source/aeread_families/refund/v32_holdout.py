"""Prospective matched-factual holdout; frozen V3.1 and old candidates unchanged.

This version changes the campaign identity and explicit native inputs. It
reuses the published lifecycle mechanics, not a development-labelled payload.
No unseen-mechanism, secret-test, or model-difficulty-equivalence claim is made.
"""
from collections import defaultdict
import copy
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from aeread.shared_runner.run.resolver import PlanCell, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from . import v3_lifecycle as parent, v3_cases as native, v3_lifecycle_controls as controls

VERSION = "3.2.0"
REVISION = "refund_v32_matched_factual_holdout/1"
FAMILY = "refund_v32_matched_holdout"
PRIMARY = "refund_v32_complete_claim_leaf"
SEEDS = (610001, 610003, 610007)
ANCHORS = (401,402,403)
EASY = {"policy":"policy_all_facts_predisclosed", "intake":"intake_one_round_unconstrained",
        "customer":"customer_single_authoritative_record", "payments":"payments_empty_ledger_single_open_tender"}


def detach(value): return parent.old.plain(value)
def digest(value): return parent.old.digest(value)


@dataclass(frozen=True)
class Case:
    base: native.Case
    anchor: native.Case
    ablation: str = "none"

    @property
    def case_id(self): return "refund_v32."+self.base.case_id+("."+self.ablation if self.ablation!="none" else "")
    @property
    def pair_id(self): return "refund_v32."+self.base.pair_id
    @property
    def seat(self): return self.base.seat
    @property
    def seed(self): return self.base.seed
    @property
    def cluster_id(self): return self.base.cluster_id


def atomic_nodes(node):
    if node.children:
        return tuple(n for child in node.children for n in atomic_nodes(child))
    return (node,)


def truths(source):
    spec=parent.old.old.spec_for(source.interaction.scenario)
    public=parent.old.public_policy(type("PublicCase",(),dict(source=source))())
    return tuple(node.evaluate(source.facts,public)[0] for branch in spec.branches for node in atomic_nodes(branch.when))


def vary_days(source, seed):
    # Constraint construction from the public predicates, not choosing a model
    # answer or dropping a failed screened world. Preserve every atomic truth.
    facts=copy.deepcopy(dict(source.interaction.facts)); target=truths(source)
    for key,value in sorted(facts.items()):
        if not key.endswith("_day") or type(value) is not int:
            continue
        for step in (1+seed%3,-1-seed%3):
            probe=replace(source,interaction=replace(source.interaction,facts={**facts,key:value+step}))
            if truths(probe)==target:
                facts[key]=value+step
                break
    return replace(source,interaction=replace(source.interaction,facts=facts))


def transform(base, anchor, seed):
    source=vary_days(base.source,seed) if base.seat=="policy" else base.source
    replacements={key:(base.source.facts[key],value) for key,value in source.facts.items()
                  if value!=base.source.facts[key]}
    # New canonical records preserve source truth even where historical
    # records encode both alternatives. No hidden reference is exposed.
    records=copy.deepcopy(list(base.records))
    a,b=2+seed%3,-10000-seed%997
    c=copy.deepcopy(base.customer_contract)
    c["as_of"]=a*c["as_of"]+b
    for row in c["authorities"]: row["priority"]=a*row["priority"]+b
    for row in records:
        row["recorded_at"]=a*row["recorded_at"]+b
        row["revision"]=a*row["revision"]+b
        if row["fact_id"] in replacements:
            old,new=replacements[row["fact_id"]]
            if row["value"]==old: row["value"]=new
    intake=copy.deepcopy(anchor.intake_contract)
    cost_scale,utility_scale=2+seed%5,3+seed%7
    intake["total_budget"]*=cost_scale
    for row in intake["catalogue"]:
        row["cost"]*=cost_scale; row["utility"]*=utility_scale
    ledger=copy.deepcopy(base.ledger)
    for row in ledger["data"].get("records",[]):
        row["revision"]=a*row["revision"]+b
    for row in ledger["data"].get("tenders",[]):
        row["priority"]=a*row["priority"]+b
    if "records" in ledger["data"]: ledger["data"]["records"].reverse()
    return replace(base,source=source,source_sha256=digest(asdict(source)),records=tuple(records),
        intake_contract=intake,customer_contract=c,ledger=ledger,
        metadata={**base.metadata,"v32_derivation":dict(revision=REVISION,anchor_case_id=anchor.case_id,
            exposure="author_visible_model_development_holdout",parent_role=anchor.role,
            native_clock_scale=a,native_clock_shift=b,cost_scale=cost_scale,utility_scale=utility_scale,
            changed_day_facts=sorted(replacements))})


@lru_cache(None)
def build_catalog(seed=SEEDS[0]):
    if type(seed) is not int or seed not in SEEDS: raise ValueError("Undeclared V3.2 seed")
    anchors=native.build_catalog(ANCHORS[SEEDS.index(seed)])
    sources=native.build_catalog(seed)
    if len(anchors)!=len(sources): raise ValueError("Source template inventory drift")
    cases=[]
    for base,anchor in zip(sources,anchors):
        if (base.seat,base.cohort,base.cluster_id,base.role,base.pair_kind)!=(anchor.seat,anchor.cohort,anchor.cluster_id,anchor.role,anchor.pair_kind):
            raise ValueError("Template/role/cluster drift; no outcome-selected repair")
        if base.seat!="policy":
            # Hold fixed the monetary obligation while varying the seat's
            # native chronology, release units or ledger corrections. A random
            # new price must not accidentally change a Payments safety branch.
            source=replace(anchor.source,interaction=replace(anchor.source.interaction,
                case_id=base.source.interaction.case_id,world_seed=seed))
            base=replace(anchor,case_id=base.case_id,pair_id=base.pair_id,seed=seed,source=source,
                source_case_id=source.case_id,source_sha256=digest(asdict(source)))
        cases.append(Case(transform(base,anchor,seed),anchor))
    pairs=defaultdict(list)
    for index,case in enumerate(cases): pairs[case.base.pair_id].append(index)
    for indices in pairs.values():
        if len(indices)!=2: raise ValueError("Incomplete prospective pair")
        x,y=(cases[i] for i in indices)
        changed=native._diff(native._view(x.base),native._view(y.base))
        for i in indices: cases[i]=replace(cases[i],base=replace(cases[i].base,changed_paths=changed))
    return tuple(cases)


def easy_case(case):
    """Executable, declared known-easy tasks; never admitted comparison rows."""
    base=case.base
    if case.seat=="intake":
        c=copy.deepcopy(base.intake_contract)
        for row in c["catalogue"]: row.update(requires=[],cost=1,utility=1,material=True)
        c.update(authorized_sources=sorted({r["source"] for r in c["catalogue"]}),
                 total_budget=len(c["catalogue"]),max_batch_size=len(c["catalogue"]),max_rounds=1)
        base=replace(base,intake_contract=c)
    elif case.seat=="customer":
        obs=dict(private_records=base.records,source_contract=base.customer_contract,
                 requested_fact_ids=sorted({r["fact_id"] for r in base.records}))
        selected=set(parent.independent.customer_records(obs).values())
        base=replace(base,records=tuple(r for r in base.records if r["record_id"] in selected))
    elif case.seat=="payments":
        base=replace(base,ledger=dict(kind="v5",data=dict(scope=dict(order_id="easy_order",line_item_id="easy_line",currency="USD"),
            records=[],snapshot_id="easy_snapshot",idempotency_key="easy_key",
            tenders=[dict(instrument="easy_card",open=True,fallback="easy_bank",priority=0,capacity_cents=1000000000)])))
    return replace(case,base=base,ablation=EASY[case.seat])


def contract(case):
    old=parent.contract(parent.Case(case.base))
    return dict(**{k:v for k,v in old.items() if k not in ("revision","split","blind")},
        revision=REVISION,split="heldout_from_model_development",blind=False,
        author_visible=True,model_results_used_in_authoring=False,external_review="pending",
        source_role=case.base.role,comparison_eligible=case.base.role=="comparison" and case.ablation=="none",
        anchor_case_id=case.anchor.case_id,anchor_cluster_id=case.anchor.cluster_id,
        scope="matched-template factual variation; not unseen laws or independent mechanisms",
        diagnostic_ablation=case.ablation)


def payload(case):
    return dict(version=VERSION,base=detach(asdict(case.base)),anchor_case_id=case.anchor.case_id,
                ablation=case.ablation,holdout_contract=contract(case))


def decode(raw):
    if set(raw)!={"version","base","anchor_case_id","ablation","holdout_contract"} or raw["version"]!=VERSION:
        raise ValueError("Unexpected V3.2 payload")
    raw=detach(raw)
    seed=raw["base"]["seed"]
    candidates=[c for c in build_catalog(seed) if c.base.case_id==raw["base"]["case_id"]]
    if len(candidates)!=1: raise ValueError("Unknown V3.2 template")
    case=candidates[0]
    if raw["ablation"]!="none":
        if raw["ablation"]!=EASY[case.seat]: raise ValueError("Unknown diagnostic ablation")
        case=easy_case(case)
    if payload(case)!=raw: raise ValueError("V3.2 payload/contract drift")
    return case


def sources():
    return {**parent.sources(),**{name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ("v32_holdout.py","v32_holdout_measurement.py","v32_holdout_difficulty.py")}}


def episode_contract(case,control="reference"):
    raw=dict(spec_version=CaseManifest.SPEC_VERSION,case_id=case.case_id,family_id=FAMILY,family_version=VERSION,
        split="diagnostic" if case.ablation!="none" or case.base.role!="comparison" else "test",world_seed=case.seed,
        seats=[dict(id=s,role=s) for s in parent.old.ROLES],
        episode=dict(max_logical_actions=512,termination=["completed","invalid_action"]),
        visibility_policy="refund_v32_four_seat",payload=payload(case),
        provenance=dict(generator_id=FAMILY,generator_version=VERSION,review_status="generated"),content_sha256="0"*64)
    raw["content_sha256"]=case_content_sha256(raw); manifest=CaseManifest.from_dict(raw)
    prior=parent.episode_contract(parent.Case(case.base),control)[0]
    cell=replace(prior,case_id=case.case_id,case_sha256=manifest.content_sha256,family_id=FAMILY,family_version=VERSION,
        pair_id=case.pair_id,paired_fields={"pair_id":case.pair_id},cell_id="refund_v32_"+digest(dict(case=raw["content_sha256"],arm=control,sources=sources()))[:32])
    return cell,manifest


class Plugin(parent.Plugin):
    def validate_payload(self,raw): return decode(raw)
    def generator(self): return build_catalog
    def initial_state(self,case,run):
        state=super().initial_state(case,run)
        if case.ablation==EASY["policy"]:
            state["native"]["revealed"]=dict(case.base.source.facts)
        return state
    def build_scorer(self,case):
        from .v32_holdout_measurement import build_scorer
        return build_scorer(case)


async def execute(case,arm="reference",tape=None,certify=False):
    from aeread.shared_runner.task.scheduler import run_episode
    transcript,checks,memory=[],[],{}
    cell,manifest=episode_contract(case,arm)
    async def response(request):
        obs=detach(request.observation); seat=request.seat_id
        if tape is not None:
            row=tape[len(transcript)]
            if row["observation"]!=obs or row["seat"]!=seat: raise ValueError("V3.2 replay observation drift")
            text=row["response"]
        else:
            action=controls.action(seat,obs,arm,memory) if seat==case.seat else parent.reference(seat,obs)
            if certify:
                if seat=="intake":
                    if parent.independent.intake_objective(obs)!=parent.old.intake_plan(obs)[:2]: raise ValueError("Independent planning mismatch")
                elif action!=parent.independent_action(seat,obs): raise ValueError("Independent reference mismatch")
                checks.append(dict(seat=seat,phase=request.phase_id,observation_sha256=digest(obs)))
            text=json.dumps(action,allow_nan=False)
        transcript.append(dict(seat=seat,phase=request.phase_id,observation=obs,response=text))
        return text
    result=await run_episode(cell=cell,case=manifest,plugin=Plugin(),response_source=response)
    if tape is not None and len(tape)!=len(transcript): raise ValueError("Unused replay tape")
    errors=[a.parse.error_code for p in result.phase_instances for a in p.actions if not a.parse.ok]
    out=detach(result.outcome)
    return dict(case_id=case.case_id,arm=arm,seat=case.seat,seed=case.seed,case_sha256=manifest.content_sha256,
        transcript=transcript,state=detach(result.final_state),outcome=out,validity=not errors,
        strict=None if errors else out["seat_strict"][case.seat],parse_errors=errors,independent_checks=checks)


async def verify_replay(case,record):
    replay=await execute(case,record["arm"],tape=record["transcript"])
    replay["independent_checks"]=record["independent_checks"]
    if replay!=record: raise ValueError("V3.2 exact replay mismatch")
