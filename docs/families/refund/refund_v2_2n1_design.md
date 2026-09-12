# Refund V2.2 N:1 priority-queue benchmark

Refund V2.2 evaluates one policy service seat handling several customer refund
claims during a finite operating shift. It is a new family version and does
not alter the V2.1 1:N panel or its published results.

The benchmark models real support operations, not a competition for customers'
policy-authorized refunds. A valid contractual refund is not withheld because
the team has a busy shift or a limited discretionary fund. The policy agent's
job is to apply policy correctly, handle the highest-priority ready claims
first, and preserve a transparent, correctly ordered queue for work that does
not fit in the current shift.

## Episode contract

Each episode contains several customer claims and one policy seat. Customers
start with a public claim and retain their case facts privately. The policy
seat may request only declared fact identifiers, in batches of at most three.
A fact becomes visible only after the relevant customer responds. Payments is
scripted and remains the only role permitted to mutate the refund ledger.

After sufficient evidence is available, the policy seat records one
disposition for every claim:

- `approve`: a policy-eligible refund with its exact authorized amount and method;
- `deny`: a policy-ineligible request, with amount zero and method `none`;
- `queue`: a policy-eligible request that cannot be completed in this shift,
  with amount zero and method `none`, plus its preserved priority, queue reason,
  and follow-up deadline;
- `escalate`: a mandatory specialist, legal, safety, fraud, or SLA path, with
  no ordinary payment mutation until that path resolves.

An incomplete evidence record is neither denied nor silently queued: it stays
in an explicit `awaiting_customer_information` state, including the requested
facts and a follow-up deadline.

## Priority and ordering

Every claim has a public, auditable `priority_basis`; the numeric priority is
derived from the declared rule rather than inferred from a scenario label.

| Priority basis | Meaning | Weight |
| --- | --- | ---: |
| `standard` | Routine policy-complete claim | 1 |
| `elevated` | Material customer impact or approaching service deadline | 2 |
| `critical` | Mandatory/SLA-critical, safety, legal, fraud, or severe-impact case | 3 |

Priority determines work order, not entitlement. Among policy-eligible,
evidence-complete claims that are not mandatory escalations, the agent must
resolve claims in descending derived priority. Ties are broken by the sealed
arrival order, then by a stable claim identifier. A lower-priority claim may be
completed only after all higher-priority ready claims have either been resolved,
escalated, are awaiting customer information, or cannot be completed due to a
case-specific dependency recorded in the trajectory.

Mandatory escalations take precedence over this normal queue rule. The
benchmark must declare their trigger and deadline explicitly; they are not a
free-form model judgment.

## Capacity and funds

`shift_resolution_capacity` is the maximum number of policy-complete claims
that can be resolved and executed during the episode's operating shift. It
models finite review, approval, and payment-execution bandwidth. It does not
make a valid ordinary refund unaffordable. When capacity is exhausted, the
remaining eligible claims are queued in priority order with a clear reason and
follow-up deadline.

The benchmark has no shared budget for normal policy-authorized refunds. If
future cases include discretionary, ex-gratia goodwill, they must carry a
separate `goodwill_eligible` flag, maximum goodwill amount, and
`goodwill_fund_remaining`. That fund may constrain optional compensation only;
it must never affect the required remedy for an eligible refund.

## Deterministic reference policy

The V2.2 reference policy applies the following deterministic sequence:

1. Collect only the decision-critical facts required by each policy.
2. Classify each claim as eligible, ineligible, awaiting information, or
   mandatory escalation according to the sealed policy.
3. Handle mandatory escalations by their declared deadline.
4. Sort ready eligible claims by descending derived priority and sealed arrival
   order.
5. Approve and execute the exact policy remedy for the first
   `shift_resolution_capacity` claims in that order.
6. Queue all remaining ready eligible claims without changing their priority or
   eligibility determination.
7. Reconcile every executed payment exactly once against its approved claim.

This is a lexicographic service-order rule, not an optimization that can trade
one high-priority customer against several lower-priority customers.

## Measurements and admission

V2.2 reports the following non-compensatory measurements:

1. policy correctness: correct eligibility, denial, escalation, and remedy;
2. priority-order correctness: no unjustified inversion among ready claims;
3. SLA and escalation compliance: mandatory routes and deadlines are honored;
4. transaction correctness: only approved claims mutate, with exact terms and
   exactly-once execution;
5. queue integrity: eligible work outside shift capacity remains visible,
   ordered, and assigned a follow-up deadline;
6. disclosure and coordination: facts and handoffs have valid provenance;
7. operational diagnostics: resolved count, queue length, and time-to-resolution.

Policy correctness, priority order, SLA/escalation compliance, and transaction
correctness are admission leaves. Operational throughput cannot compensate for
a policy, priority, disclosure, or payment failure. Any aggregate utility is a
Refund-specific diagnostic only, not a cross-family scalar or model ranking.

## Current implementation status

The checked-in V2.2 prototype and its case catalog still implement the earlier
shared-budget constrained-allocation design. They are useful as a receipt and
interaction harness, but are not the authoritative V2.2 benchmark contract
after this redesign. Before a provider-backed V2.2 campaign, the implementation
must replace `refund_budget` and subset optimization with
`shift_resolution_capacity`, explicit queue states, arrival ordering,
deadlines, and the deterministic priority-queue reference described above.

No external V2.2 model result should be published until that migration and its
provider-free conformance tests are complete.
