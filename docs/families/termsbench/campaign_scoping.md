# TERMS-Bench live campaign (#92): what is done, and the blocker

## Done

- **Finalizer migrated (#75).** `TermsBenchScorer` had no `__call__` at all,
  so the kernel's finalizer could not score it and none of its four leaves
  could reach a receipt. It now implements
  `__call__(scoring_input) -> FamilyScoreSet`, scoring exactly the leaves a
  case declares -- they are regime-dependent, `(surplus_efficiency,
  feasible_agreement, protocol_compliance)` for Overlap and
  `(no_deal_agreement, protocol_compliance)` for No-deal -- so a case is
  never scored on a leaf it does not declare. `protocol_compliance` is the
  admission leaf, being the one leaf both regimes declare: a trajectory that
  broke the protocol is an invalid measurement, not a low score.
- **`scoring.reference_provider_ids` declared**, as the union across both
  regimes, built from the same `_implementation` helper the leaves use.
- **No upstream checkout is needed.** Unlike econevals and govsim, this
  family carries its own kernel and a 30-case pilot corpus; nothing has to
  be cloned or provisioned.

## The blocker: a seat that is not a model

TERMS-Bench has two seats. `agent` is the model under test. `counterpart` is
**not a model** -- it is resolved by this family's own stochastic kernel
(`kernel.resolve_counterpart_turn`, driven by the case's `world_seed`), which
is what makes the benchmark a negotiation against a specified opponent rather
than a self-play conversation.

`execute_plan_cell` has no way to express that. Every seat in a resolved plan
is routed through a profile to a harness to a model call, and there is no
scripted-seat parameter. The two obvious workarounds are both wrong:

- **A harness that returns the counterpart's action without a model call**
  is rejected by the kernel (`harness ... returned without a model call`),
  and rightly: that invariant is what stops a harness fabricating a
  trajectory no model took part in.
- **Giving `counterpart` a live profile** would have the model play both
  sides. That is a different experiment from TERMS-Bench, whose result is
  defined against the specified opponent.

## Three ways forward

| option | what it means | cost |
|---|---|---|
| **Fold the counterpart into the environment** | `counterpart_turn` stops being a seat; its resolution becomes part of `step()`, where the stochastic draw already belongs conceptually -- the counterpart is environment, not agent | a family redesign: the phase graph, the replay goldens and every case's `content_sha256` change |
| **Add a scripted-seat capability to the kernel** | `execute_plan_cell` accepts a per-seat response source for seats whose profile declares no model | a shared-kernel change benefiting any family with a specified opponent; needs its own evidence story, since a scripted seat's actions must still be replayable and clearly marked as not-model-produced |
| **Run the agent seat only, with the counterpart pre-resolved** | pre-compute the counterpart's turns per case from the seeded kernel and serve them as fixed observations | cheapest, but the counterpart stops reacting to the agent's offers, which destroys the negotiation |

The second is the one I would argue for: the counterpart being scripted is a
property many families share (govsim's scripted policies, procurement's
oracle), and the kernel currently forces every one of them into either a
model call or a bespoke driver outside `execute_plan_cell`. But it is a
shared-kernel capability with an evidence contract of its own, so it is a
ruling rather than an implementation detail.

Until then #92's live panel cannot be run without misrepresenting what
TERMS-Bench measures.
