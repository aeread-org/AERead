"""Prospective native decision-structure screen, separate from quality scores.

Exact structural matching is deliberately narrower than latent model difficulty.
It can reject easy tasks even when all full-lifecycle shortcut scores are zero.
It is not an independent policy resolver and never enters agent observations.
"""
from collections import Counter, defaultdict
from functools import reduce
from math import gcd
from . import v32_holdout as d

REVISION="refund_v32_native_decision_structure/1"


def _normalize(values):
    unit=reduce(gcd,(abs(int(x)) for x in values),0) or 1
    return [x/unit for x in values]


def _rank(values):
    ordered=sorted(set(values))
    return [ordered.index(x) for x in values]


def fingerprint(case):
    b=case.base; seat=case.seat
    out=dict(seat=seat,category=b.source.product_category,cluster=b.cluster_id,role=b.role,pair_kind=b.pair_kind)
    if seat=="policy":
        spec=d.parent.old.old.spec_for(b.source.interaction.scenario)
        inputs=d.parent.old.public_policy(b)
        _,resolution=d.parent.independent.policy(spec.to_dict(),b.source.facts,inputs)
        out.update(branch_spec=spec.to_dict(),atomic_truths=list(d.truths(b.source)),
            fact_types=d.parent.old.fact_types(b),initially_disclosed_all=case.ablation==d.EASY["policy"],
            selected_regime={k:v for k,v in resolution.items() if k!="amount"},positive_amount=resolution["amount"]>0)
    elif seat=="intake":
        c=b.intake_contract; rows=sorted(c["catalogue"],key=lambda r:r["fact_id"])
        out.update(rows=[{k:r[k] for k in ("fact_id","source","requires","material")} for r in rows],
            costs_budget=_normalize([r["cost"] for r in rows]+[c["total_budget"]]),
            utilities=_normalize([r["utility"] for r in rows]),authorized=sorted(c["authorized_sources"]),
            rounds=c["max_rounds"],batch=c["max_batch_size"])
    elif seat=="customer":
        c=b.customer_contract
        priorities={r["document_id"]:r["priority"] for r in c["authorities"]}
        priority_rank=dict(zip(sorted(priorities),_rank([priorities[k] for k in sorted(priorities)])))
        groups=defaultdict(list)
        for r in b.records: groups[(r["fact_id"],r["document_id"],r["scope"])].append(r)
        histories=[]
        for key,rows in sorted(groups.items()):
            rows=sorted(rows,key=lambda r:(r["revision"],r["recorded_at"],r["record_id"]))
            # Classify values by equality, not raw strings or prices; this
            # preserves ambiguity/conflict information under factual variation.
            values=[d.digest(r["value"]) for r in rows]
            equalities=[[x==y for y in values] for x in values]
            histories.append(dict(key=list(key),revision_rank=_rank([r["revision"] for r in rows]),
                eligible=[r["recorded_at"]<=c["as_of"] for r in rows],
                status=[r["status"] for r in rows],value_equalities=equalities))
        out.update(scope=c["request_scope"],priority_rank=priority_rank,histories=histories,
            binding=bool(getattr(b.source,"seat_context",{}).get("proposal_binding_v7")))
    else:
        proposal=d.detach(d.parent.old.old.resolve_policy(b.source)); proposal["proposal_id"]="fingerprint"
        obs=d.parent.old.payment_observation(b,proposal)
        ledger=obs["payment_ledger"]
        rows=ledger.get("records",[])
        groups=defaultdict(list)
        for r in rows: groups[r["event_id"]].append(r)
        scope=ledger.get("scope",{})
        histories=[]
        for _,items in sorted(groups.items()):
            items=sorted(items,key=lambda r:r["revision"])
            histories.append(dict(revision_rank=_rank([r["revision"] for r in items]),
                status=[r["status"] for r in items],in_scope=[all(r[k]==scope[k] for k in scope) for r in items],
                same_key=[r["idempotency_key"]==ledger["idempotency_key"] for r in items],
                allocation_counts=[len(r.get("allocations_cents",[])) for r in items]))
        tenders=sorted(ledger.get("tenders",[]),key=lambda t:t["priority"])
        ref=d.parent.old.scripted_action("payments",obs)
        out.update(kind=b.ledger["kind"],histories=histories,
            tenders=[dict(open=t["open"],fallback=t.get("fallback"),instrument=t["instrument"]) for t in tenders],
            legacy_rule=ledger.get("allocation_rule"),legacy_state=ledger.get("state"),
            legacy_tenders=len(ledger.get("tender_capacities",ledger.get("original_tender_shares",[]))),
            execute=ref["decision"],positive=ref["amount"]>0,allocations=len(ref["refund_allocations"]))
    return out


def assess(case):
    # Matched anchor is fixed by template index and seed map, never by finding
    # an anchor with a similar score after seeing the candidate result.
    anchor=d.Case(case.anchor,case.anchor)
    expected,actual=fingerprint(anchor),fingerprint(case)
    paths=d.native._diff(expected,actual)
    return dict(case_id=case.case_id,seat=case.seat,anchor_case_id=case.anchor.case_id,
        passed=not paths,changed_dimensions=list(paths),expected_sha256=d.digest(expected),actual_sha256=d.digest(actual),
        tolerance=0,method=REVISION,ablation=case.ablation)
