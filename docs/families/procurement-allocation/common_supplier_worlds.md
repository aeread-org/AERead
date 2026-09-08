# Common supplier worlds

**Decision, 2026-09-08.** When two buyer conditions are compared, they face one
supplier population, and that is verified rather than assumed.

Comparing two buyers is only a comparison if they faced the same market. Nothing
previously checked that. Cases were authored per condition, so a comparison
could rest on populations that differed in a private term no reader would see,
and the resulting number would still be reported as one figure.

## What "the same suppliers" means

| Property | How it is held |
|---|---|
| Identical listings **and private terms** | every supplier field is byte-identical across conditions |
| Identical rules and starting conditions | capacity, quality, lead time, on-time probability, negotiation floors, payment terms, offer validity, return policy, the objective and the interaction budget are all inside the shared digest |
| Independent episodes | each replay builds its own plugin, validated case and initial state; verified by replaying alone, in order, and reversed |
| **Not** an identical transcript | suppliers answer what a buyer actually did, so conditions that act differently see different replies |

That last row is a requirement, not a caveat. A design that produced identical
transcripts would be holding the buyer's behaviour fixed, which is the thing
under measurement.

## How it is enforced

`common_supplier_world.supplier_population_sha256` digests the four payload
blocks a condition may not vary: `objective`, `interaction`, `policy` and
`suppliers`. Digesting the supplier list alone would pass a comparison whose
conditions had different deadlines, action budgets or required variants, which is
a different problem wearing the same suppliers.

`build_arm_cases` derives every condition's case from one source payload, so the
shared digest is a fact about construction rather than a hope about authoring
discipline. Conditions differ only in `case_id`, `split` and their own content
digest. `assert_shared_population` names the block that diverged instead of
reporting that two hashes differ, and `paired_world_report` publishes the digest
and the independence result together, so a comparison in evidence can be checked
to have used one population.

Twenty-six tests cover it, including one mutation of each named invariant in
turn, so the list above is enforced rather than merely written down. Three guards
are mutation-verified.

## The pilot, 2026-09-08

Two buyer conditions were run against three shared populations: the v4 control
procedure and the landed-cash gate, two seeds each, twelve rows, $0.0294.

| arm | rows | completed | receipts replayed | feasible awards | mean regret | cost |
|---|---:|---:|---:|---:|---:|---:|
| control_v4 | 6 | 6 | 6 | 2 | $93.24 | $0.0144 |
| gate_cash | 6 | 6 | 6 | 2 | $93.19 | $0.0150 |

What it establishes, which is all a pilot of this size can:

- **Both conditions run against an identical market.** Three distinct population
  digests, one per world, each shared by both arms.
- **Accounting holds.** All twelve rows completed, all twelve receipts replayed,
  all twelve carry a receipt digest. Zero operational failures, which is worth
  noting against this route's 17.6% historical call-failure rate, though twelve
  rows is far too few to claim the route improved.
- **Commitment rules fired.** Violations are typed and correct:
  `minimum_service_not_met` three times, and one
  `sample_not_verified` where a supplier was awarded without a verified sample.
  A run with no violations at all would have been the more suspicious result.
- **Privacy held.** No private-only field name appears in any buyer action
  trace: not the true yield, the price floor, the base price, the negotiation
  minimums, or the verbal bias.

**What it does not establish, explicitly.** Not an effect, not a ranking, not
realism. The two mean regrets differ by $0.05 and that number should not be
reported as anything: two seeds across three worlds, on a family where
within-world seed variance has measured zero (defect 18), gives an effective
sample size of three. The arms behaving alike here is consistent with the
conditions being equivalent and equally consistent with the panel being unable to
separate them, and this pilot cannot tell those apart. Doing so needs an admitted
panel under the continuous rule, which no procurement panel has yet passed.

## Deliberately not built: a supplier played by a model

A shared model supplier is a different design, not an increment of this one, and
it needs all of the following before it would mean anything:

- supplier decision turns, and private supplier information to decide from
- one reference profile held across buyer conditions
- authoritative facts and contract enforcement staying in deterministic code
- **an explicit supplier utility.** Without one, a supplier that accepts
  everything looks like successful negotiation, and the measurement inverts.
- buyer utility, supplier utility, agreement feasibility and joint welfare
  reported separately rather than collapsed into one number

Nothing in this module should be read as a step toward that. The deterministic
population is what a controlled buyer comparison needs, and it is what is here.

A related caution applies whenever a live model becomes part of the apparatus: a
route and configuration digest identify the setup that was *requested*. They do
not freeze a remotely hosted model's weights or serving behaviour, and inference
can vary even when weights do not. Such a thing is a version-pinned reference
profile, not a fixed opponent, unless the checkpoint and runtime are controlled
and verified.
