"""Supplementary, observation-only QC oracles; never used by the runner.

Implementation independence, not independently authored policy: the policy
interpreter consumes the same published DSL and arithmetic conventions. Tests
also compare handwritten resolutions and hand goldens. No environment, scorer,
generator, historical resolver, or scripted profile is imported here.
"""
from itertools import combinations, groupby
import operator


def predicate(node, values):
    op = node["op"]
    if op == "always":
        return True, ()
    if op in ("all", "any", "not"):
        parts = [predicate(child, values) for child in node["children"]]
        if op == "not":
            truth, needed = parts[0]
            return (not truth if truth is not None else None), needed
        known = [truth for truth, _ in parts if truth is not None]
        if op == "all" and False in known:
            return False, ()
        if op == "any" and True in known:
            return True, ()
        missing = [ids for truth, ids in parts if truth is None]
        if missing:
            return None, (missing[0] if op == "any" else
                          tuple(dict.fromkeys(k for ids in missing for k in ids)))
        return op == "all", ()
    missing = tuple(k for k in node["fields"] if k not in values)
    if missing:
        return None, missing
    fields = node["fields"]
    left, right = values[fields[0]], values[fields[1]] if len(fields) == 2 else node["value"]
    if op in ("le", "gt"):
        left, right = float(left), float(right)
    comparisons = dict(eq=operator.eq, ne=operator.ne, le=operator.le,
                       gt=operator.gt, **{"in": lambda a, b: a in b})
    return comparisons[op](left, right), ()


def policy(spec, revealed, public):
    """Return (pending IDs, resolution-or-None), interpreting raw dictionaries."""
    if spec["design_version"] != "refund_v25_branch_contract/2":
        raise ValueError("Unsupported public DSL")
    for branch in spec["branches"]:
        truth, needed = predicate(branch["when"], {**revealed, **public})
        if truth is None:
            return needed, None
        if not truth:
            continue
        out = branch["outcome"]
        missing = tuple(k for k in out["amount_fields"] if k not in revealed)
        if missing:
            return missing, None
        price, tax = float(public["item_net_price"]), float(public["allocated_tax"])
        kind, amount = out["amount_kind"], 0.0
        if kind == "full":
            amount = round(price + tax, 2)
        elif kind == "residual":
            amount = round(max(0, round(price + tax, 2) -
                               round(int(revealed["settled_refund_cents"]) / 100, 2)), 2)
        elif kind in ("partial", "piecewise"):
            cap = price * float(revealed["category_cap_rate"])
            if kind == "piecewise":
                cap = round(cap, 2)
            amount = round(min(float(revealed[out["amount_fields"][0]]), cap) +
                           (float(revealed["allocated_component_tax"]) if kind == "piecewise" else 0), 2)
        elif kind != "zero":
            raise ValueError("Unsupported amount rule")
        flow = "no_mutation" if not amount and out["workflow"] == "execute_refund" else out["workflow"]
        return (), dict(eligibility=out["eligibility"], remedy=out["remedy"], workflow=flow,
                        amount=amount, refund_method="original_payment" if amount > 0 else "none",
                        payment_mutation="execute" if amount > 0 and flow == "execute_refund" else "none",
                        return_shipping_payer=out["payer"], policy_basis=out["basis"], reason_code=out["basis"])
    raise ValueError("No fallback branch")


def intake_objective(obs):
    """Breadth-first reachable-set enumeration, not recursive script/DP reuse.

    Equal selected sets have identical accumulated utility and cost. Track their
    earliest reachable round; later arrivals cannot improve that state's future.
    Prerequisites must exist at the START of a batch, not inside that batch.
    """
    c = obs["collection_contract"]
    rows = {r["fact_id"]: r for r in c["catalogue"]}
    initial = frozenset(obs["disclosed_fact_ids"])
    frontier, visited, best = {initial}, {initial}, (0, 0)
    for _ in range(max(0, c["max_rounds"] - obs["round"])):
        following = set()
        for known in frontier:
            spent = sum(rows[k]["cost"] for k in known - initial)
            ready = [k for k, r in rows.items() if k not in known
                     and r["source"] in c["authorized_sources"] and set(r["requires"]) <= known]
            for size in range(1, min(c["max_batch_size"], len(ready)) + 1):
                for batch in combinations(ready, size):
                    cost = spent + sum(rows[k]["cost"] for k in batch)
                    if cost > obs["remaining_budget"]:
                        continue
                    reached = known | frozenset(batch)
                    utility = sum(rows[k]["utility"] for k in reached - initial if rows[k]["material"])
                    if (utility, -cost) > (best[0], -best[1]):
                        best = utility, cost
                    if reached not in visited:
                        following.add(reached)
        visited.update(following)
        frontier = following
        if not frontier:
            break
    return best


def customer_records(obs):
    """Group eligible snapshots, remove revoked latest revisions, rank sources."""
    c = obs["source_contract"]
    priorities = {a["document_id"]: a["priority"] for a in c["authorities"]}
    records = sorted((r for r in obs["private_records"] if r["scope"] == c["request_scope"]
                      and r["recorded_at"] <= c["as_of"] and r["document_id"] in priorities),
                     key=lambda r: (r["fact_id"], r["document_id"], -r["revision"]))
    available = {}
    for (fact, document), group in groupby(records, key=lambda r: (r["fact_id"], r["document_id"])):
        current = next(group)
        if current["status"] == "live":
            available.setdefault(fact, []).append((priorities[document], current["record_id"]))
    return {fact: sorted(available[fact])[0][1] for fact in obs["requested_fact_ids"]}


def payments(obs):
    """Reconcile visible raw ledgers and return a provider action, not a ticket."""
    p, ledger, kind = obs["confirmed_proposal"], obs["payment_ledger"], obs["ledger_kind"]
    amount, allocations = round(float(p["amount"]), 2), []
    blocked = obs["delivery_already_applied"] or ledger.get("already_applied", False) or p["payment_mutation"] != "execute"
    if kind in ("v4", "v5"):
        # Select global latest revision BEFORE scope; equivalent input row
        # permutations are allowed, but contradictory equal revisions are not.
        groups = groupby(sorted(ledger["records"], key=lambda r: (r["event_id"], -r["revision"])),
                         key=lambda r: r["event_id"])
        latest = [next(rows) for _, rows in groups]
        scope = ledger["scope"]
        relevant = [r for r in latest if all(r[k] == scope[k] for k in ("order_id", "line_item_id", "currency"))]
        blocked |= any(r["status"] in ("submitted", "unknown") or
                       (r["status"] == "settled" and r["idempotency_key"] == ledger["idempotency_key"]) for r in relevant)
        settled = [r for r in relevant if r["status"] == "settled"]
        if kind == "v4":
            residual = max(round(amount * 100) - sum(r["amount_cents"] for r in settled), 0)
            rail = ledger["original_rail"] if ledger["original_rail_open"] else ledger["fallback_rail"]
            allocations = [{"instrument": rail, "amount": residual / 100}] if residual else []
        else:
            used = {}
            for r in settled:
                for a in r["allocations_cents"]:
                    used[a["instrument"]] = used.get(a["instrument"], 0) + a["amount_cents"]
            residual = max(round(amount * 100) - sum(used.values()), 0)
            tenders = sorted(ledger["tenders"], key=lambda t: t["priority"])
            capacities = [max(t["capacity_cents"] - used.get(t["instrument"], 0), 0) for t in tenders]
            blocked |= sum(capacities) < residual
            left, destinations = residual, {}
            for t, capacity in zip(tenders, capacities):
                taken = min(left, capacity)
                left -= taken
                dest = t["instrument"] if t["open"] else t["fallback"]
                destinations[dest] = destinations.get(dest, 0) + taken
            allocations = [{"instrument": k, "amount": v / 100} for k, v in sorted(destinations.items()) if v]
        amount = residual / 100
    elif kind == "legacy":
        rule = ledger.get("allocation_rule")
        if rule == "waterfall_remaining_capacity":
            left = amount
            for t in ledger["tender_capacities"]:
                taken = round(min(left, float(t["remaining_capacity"])), 2)
                allocations.append(dict(instrument=t["instrument"], amount=taken))
                left = round(left - taken, 2)
        elif rule == "proportional_original_tender":
            shares, left = ledger["original_tender_shares"], amount
            for i, t in enumerate(shares):
                taken = left if i == len(shares) - 1 else round(amount * float(t["share"]), 2)
                allocations.append(dict(instrument=t["instrument"], amount=taken))
                left = round(left - taken, 2)
        elif rule == "residual_after_settled_refunds":
            amount = round(max(0, float(ledger["requested_amount"]) - float(ledger["settled_refund_amount"])), 2)
            allocations = [dict(instrument=ledger["original_tender"], amount=amount)] if amount else []
        elif rule == "original_rail_then_allowed_fallback":
            rail = ledger["allowed_fallback_rail"] if ledger["state"] == "primary_rail_closed" else ledger["original_rail"]
            allocations = [dict(instrument=rail, amount=amount)]
        elif rule is None:
            allocations = ledger["refund_allocations"]
        else:
            raise ValueError("Unsupported legacy allocation rule")
    else:
        raise ValueError("Unsupported ledger")
    if blocked or amount <= 0:
        amount, allocations = 0.0, []
    return dict(decision="execute_refund" if amount > 0 else "no_mutation",
                proposal_id=p["proposal_id"], idempotency_key=ledger["idempotency_key"],
                ledger_snapshot_id=ledger.get("snapshot_id", ledger.get("ledger_snapshot_id")),
                amount=amount, refund_method="original_payment" if amount > 0 else "none",
                refund_allocations=allocations)
