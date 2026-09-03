# Procurement allocation v1

This family tests an interactive buyer that must acquire and negotiate supplier
information before allocating an electronics BOM. Marketplace listings and verbal
claims are provisional. Only environment-issued formal offers and verified sample
records are eligible for a final award.

The primary measurement is buyer contribution margin against a deterministic,
full-information upper bound. The objective accounts for completed on-time kits,
landed cost, verified yield, supplier return/refund recovery, working-capital cost,
information-acquisition cost, and shortfall penalties. Deferring remains an explicit
outside option.

The development case uses synthetic supplier identities and economics calibrated to
exercise the intended trade-offs. It does not represent live supplier commitments.

## Interaction contract

The buyer gets ten turns and can ask a supplier for verbal confirmation, request a
formal quote, counter a quote, request an exact-variant sample, submit an award, or
defer. Verbal replies remain `verbal_claim` records. Only environment-issued
`formal_offer` and `verified_sample` records can satisfy the award gate, so natural
conversation is useful for discovery without becoming transaction authority.

Supplier counters can change unit price, MOQ, payment terms, refund window, and the
return-freight payer within deterministic private limits. Quote, counter, inquiry,
and sample actions consume declared time and information cost.

## Verifier family

This is an `objective_reference` case. Its primary estimand is buyer contribution
margin in USD and its reference is a deterministic full-information upper bound. The
enumerator knows which terms to acquire but still charges every quote, sample, and
counter action required to reach an award. The reference therefore removes search
uncertainty without making qualification free.

The frozen grounding case remains a separate `claim_reference` evaluation, and the
refund/return cases remain the home of constraint and exact-state verification. The
three verifier families are reported separately rather than collapsed into one score.

## Runner

`aeread_families.procurement_allocation.runner` exposes offline scripted and
OpenRouter setup builders. Its module CLI accepts a JSON array containing one action
object per turn and writes normal AERead evidence plus a replayable evaluation
receipt:

```bash
python -m aeread_families.procurement_allocation \
  --script /path/to/actions.json \
  --run-root /tmp/procurement-allocation-run
```
