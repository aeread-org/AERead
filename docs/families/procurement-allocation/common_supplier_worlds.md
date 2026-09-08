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
