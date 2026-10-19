# Refund: what a V2.6 needs for Gate 3 to pass

**Status:** a design note for the family owner (Yuchen), 2026-10-19, at the platform owner's request. Nothing here is
declared, built or run. It collects the open design rows against V2.5 and the change each one asks for; the owner
decides which to take into a new identity. V2.5 stays as published.

## Why Gate 3 fails today

The lower-control screen (`refund_v25_lower_controls/1`, rule `refund_v25_beatability/1` declared first, seed 301, all
11 public cohorts; `cases/refund_v25/qc/lower_controls.json`) found a naive control at or near the reference in three of
four seats, and one leaf that cannot fail:

| Seat or leaf | Row | What the naive control does | Result |
|---|---|---|---|
| policy | RV25-D-03 | `naive_full_refund` refunds in full on its first turn and collects nothing | passes strict end-to-end on 38 of 180 cases (5/24 `core`, 14/76 `policy`, 10/18 `v3_payments`) |
| policy, `evidence` leaf | RV25-D-04 | `random_legal` | 1.0 on all 204 placements: requests are legal only inside the pending set and submission only once it is empty, so every legal path scores 1.0 |
| customer | RV25-D-05 | `naive_first_record` copies the first record for each requested id | equals the reference on every case of 9 cohorts; the seat has one legal action |
| payments | RV25-D-06 | `naive_no_mutation` never reads the ledger | reaches the reference on 17% to 100% of cases, because many tickets are no-ops |
| payments, `payment` leaf | RF-D-05 | a proposal aliasing `payment_mutation: "refund"` | scores 1.0 while no money moves where the reference refunds $185.22: the leaf checks binding to the proposal |
| admission | RF-T-01 | none needed | the runner mints the human-QC approval from status stubs, so the requirement holds by construction |

## Changes, one per row

1. **Policy: score minimal pairs** (RV25-D-03). Generate each policy case with a twin that differs in one disclosed fact
   that flips the right resolution (full refund against partial, refund against hold). A case is passed only when both
   members are. On V2.5's cases the full-refund constant passes both members of 0 of the 38 pairs it can form, but that
   was found after the screen, so it is a hypothesis: declare the pair rule (a new rule id) before the screen reruns.
2. **Evidence: make collection a choice** (RV25-D-04). Let the policy seat request any document from the case's
   catalogue and submit at any time, each request at a stated cost; score `evidence` against the reference's minimal
   collection (what was needed and requested, what was requested and not needed). Then `random_legal` and "request
   everything" both lose.
3. **Customer: give the seat something private to decide, or stop scoring it** (RV25-D-05). Either a disclosure choice
   with a trade-off (a revoked or superseded record that must be reconciled, a cost to over-disclosing), or the seat
   becomes scripted and leaves the scored set; a seat with one legal action measures copying.
4. **Payments: balance the no-op share** (RV25-D-06). Cap no-mutation tickets at a declared share of each cohort (for
   example a quarter) and report the payments seat on mutation tickets first, so the constant cannot reach the reference.
5. **Payments: check that the right money moved** (RF-D-05). Keep today's leaf under an honest name (`payment_binding`)
   and add a leaf that compares the executed transactions with the reference resolution's amounts and targets.
6. **Admission: a reviewer-signed QC record** (RF-T-01). The runner refuses to mint an approval; a reviewer's record binds
   the contract digest, per `docs/operations/benchmark_qc.md`.

## Order

Declare the new beatability rule and the pair rule first; rebuild the generator with pairs, the catalogue, the no-op cap
and the money leaf; rerun the lower-control screen on fresh seeds; Gate 3 passes only if every seat's naive controls
fail the declared rule. Items 1, 2 and 5 change what is measured; 3 and 4 change who is measured; 6 is process. If only
part is taken, 1 and 5 matter most: they are the two places where a wrong answer scores as right today.
