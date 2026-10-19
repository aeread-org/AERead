# Refund V1.3 worked trajectories

These development trajectories exercise the case contract in
`cases/refund_v1/dev/`. They are design fixtures, not model results. Each
action is typed; explanatory text is non-authoritative transcript evidence.

## Clean resolution

Case: `refund_v1.dev.clean.001`

```text
customer: I need help with a torn seam.
support: request_facts([condition, issue_type, return_received])
customer: disclose condition=damaged, issue_type=defective, return_received=true
support: propose(offer_id=o1, remedy_id=full_refund_cash)
customer: accept(offer_id=o1)
support: execute_refund(offer_id=o1)
```

Expected result: all information and transaction leaves pass; exactly one
authorized refund of `$60` reaches the original payment method.

## Valid push-back and counteroffer

Case: `refund_v1.dev.counter.001`

```text
customer: One earbud stopped working.
support: request_facts([condition, issue_type, return_received])
customer: disclose condition=opened_good, issue_type=defective, return_received=true
support: request_facts([liquid_damage])
customer: disclose liquid_damage=false
support: propose(offer_id=o1, remedy_id=partial_refund_cash)
customer: push_back(offer_id=o1, target=full_refund)
support: counter(offer_id=o2, remedy_id=full_refund_cash, supersedes_offer_id=o1)
customer: accept(offer_id=o2)
support: execute_refund(offer_id=o2)
```

Expected result: `o1` is rejected and superseded, `o2` is the only accepted
offer, and exactly one `$180` refund is executed. The counter remains within
the case's accepted remedy set.

## Detectable failure: premature and stale execution

Case: `refund_v1.dev.counter.001`

```text
customer: One earbud stopped working.
support: propose(offer_id=o1, remedy_id=full_refund_cash)
customer: push_back(offer_id=o1, target=full_refund)
support: counter(offer_id=o2, remedy_id=partial_refund_cash, supersedes_offer_id=o1)
customer: accept(offer_id=o2)
support: execute_refund(offer_id=o1)
```

Expected result: the trajectory fails `information_constraint` because the
proposal precedes the required disclosures, and fails
`temporal_transaction`/`state_invariant` because `o1` is stale and cannot be
executed after being superseded. The verifier must not silently reinterpret
`o1` as the accepted offer.
