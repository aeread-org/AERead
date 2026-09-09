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

## Resolved (2026-09-08): the counterpart is a kernel scripted seat

The second option above was taken. The kernel now has a scripted-seat
capability (#150, `docs/kernel_scripted_seats_design.md`): a plan may
declare a seat as filled by a family policy rather than a profile
(`RunSpec.scripted_seats`), the kernel asks the plugin's
`scripted_response(policy_id, request, world_seed=...)` for that seat's
turn, seals it as a `scripted_action` (never as a provider call), and replay
recomputes it and holds it against the sealed response. A scripted seat may
be a block's control and never its subject.

What this family did with it:

- `environment.py` -- `TermsBenchPlugin.scripted_response` answers
  `termsbench_counterpart_kernel_v1` from the same pure function the legacy
  test harness used (`harness.resolve_counterpart_response`), so the
  scripted seat reproduces the legacy counterpart exactly
  (`tests/test_termsbench_scripted_seat.py`).
- `live.py` -- the live setup: the agent is the only profile, the
  counterpart is the scripted seat and the block's control. The harness
  makes one model call per agent turn and hands the JSON object to the
  family unchanged: a malformed move is a *measured* agreement violation
  here, and `protocol_compliance` is the admission leaf, so the harness
  does not judge it. Route, retry policy and the reasoning declaration are
  econevals' measured configuration on the same GLM 5.3 Flash/Parasail
  route.
- `campaign.py` -- the pilot: one unscored canary, then the 30-case corpus
  in the corpus manifest's order, serially, with the cost ceilings and the
  campaign SOP's wall-time gate frozen in the plan. The publisher reports
  per regime, because the leaves are regime-dependent, and adds the
  family's own corpus aggregate (`SE+`, `AGR+`, `CSE+`) over the Overlap
  half.

Every corpus case was run offline through the real kernel against the
scripted counterpart before the canary (`tests/test_termsbench_live_campaign.py`).
The first defect that surfaced is TB-D-01 in the incident log: a receipt
with a scripted seat could be sealed and replayed but not read back by the
research layer, fixed in #150 before any spend.

## Pilot v1 → v2 (2026-09-08)

`termsbench_glm53_flash_parasail_pilot_v1`, attempt_001: canary admitted;
cases 0–6 complete and replayed; case 7 (`nodeal.1010055`) aborted the
panel. GLM 5.3 Flash at temperature 0 wrote `{"decision": "offer", "price":
56.5993352745860345659335…` and repeated the digits of the price to the
4,000-token ceiling (`finish_reason: length`); the 1.0 harness typed that
as a non-retryable `malformed_structured_output` route fault, which the
kernel wraps as a contract error and the campaign as an operational abort
(TB-O-01, TB-D-02 in the incident log). Two things were wrong with that,
neither of them the model's answer:

- the family already defines a malformed move as a *measured* outcome
  (`malformed_action_schema`, spec golden 4), and the kernel's OpenRouter
  client deliberately keeps a completed non-JSON answer on the normal path
  for the family to classify -- the harness had pre-empted both;
- one cell's failure should never cost the other twenty-two cases.

v2 is the new campaign identity that carries the fixes, as a changed
frozen control requires: harness 1.1 hands a finished non-object answer to
the family as `{"raw_text": …}`, and a cell that fails inside the kernel is
sealed as a typed exclusion receipt (`finalize_family_failure`) while the
campaign continues. The v1 attempt root stays sealed as evidence. What the
two clients do with a truncated structured response differs (Arena types it
`length`, OpenRouter returns the text) and is filed as #152 rather than
changed under the scripted-seat PR.
