# Scripted seats: a seat that is not a model

**Status:** design, for review before implementation. Motivating family:
TERMS-Bench (#92), whose `counterpart` seat is resolved by the family's own
seeded stochastic kernel and is not a model. The live path today refuses this:
every seat in a resolved plan must map to an `AgentProfile` with a `ModelSpec`,
and a harness that answers without a model call is rejected by the kernel.

## What exists

- The family manifest already declares it: `roles[seat].scripted_policies`
  (schemas.py) -- TERMS-Bench declares `counterpart: {testable: false,
  scripted_policies: [termsbench_counterpart_kernel_v1]}`. Nothing in the
  kernel reads that field at run time.
- `RunSpec.seat_assignments` maps every case seat to a profile id; the
  resolver requires the two seat sets to be equal, and `PlanCell.profile_by_seat`
  is built from it. `_request_action` (scheduler.py) reads
  `cell.profile_by_seat[seat_id]` for every seat and hands a `DecisionRequest`
  to the single `response_source`, which is the executor.
- Replay (`_replay_family_trajectory`) re-executes phases and cross-checks
  every action against the sealed events (ruling R2).
- Ruling R12's `_check_seat_context_seat_set` compares `profile_by_seat`'s
  seat set against the receipt's `agent_profile_sha256_by_seat`.

## The capability

1. **Declaration.** `RunSpec.scripted_seats: Mapping[str, str]` (seat id ->
   policy id), optional, digest-neutral when empty (the same
   `_CANONICAL_OMIT_IF_DEFAULT` treatment `trajectory_outcome_paths` got).
   Seat sets: `case seats == seat_assignments ∪ scripted_seats`, disjoint.
2. **Validation (resolver).** A scripted seat's policy must be listed in the
   family's `roles[seat].scripted_policies`; the role must be `testable: false`;
   the seat may not appear in any block's `subject_seats`.
   It may be a block's `controlled_profiles` entry -- a fixed policy is the
   archetypal control; the resolver fixture's `controlled_fixed_counterpart`
   block names exactly such a seat. A scripted seat has no profile, no provider, no
   admission canary and no cost.
3. **Plan cell.** `PlanCell.scripted_seats` carries the mapping so the
   scheduler needs no back-reference to the run spec.
4. **Scheduler.** In `_request_action`, a seat in `cell.scripted_seats` does
   not build a `DecisionRequest`. It calls one new optional plugin hook,
   `plugin.scripted_response(policy_id, request, *, world_seed) -> Mapping` --
   the structured response the family's `parse_action` consumes, which is
   exactly what a harness-driven model seat hands the scheduler (the harness
   output's `action`, not the sealed canonical response). The kernel seals the
   mapping's canonical JSON as the attempt's `CanonicalResponse` with
   `finish_reason="scripted"` and no provider call ids, so parse, legality,
   the record and replay never distinguish the two kinds of seat -- and seals a `scripted_action` event carrying the
   policy id, the observation digest and the action -- never a
   `provider_call_*` event, so no receipt can read a scripted turn as
   model-produced. The `LogicalActionRecord` marks `source="scripted_policy"`.
   The hook is optional the way `close` and `inapplicable_leaf_ids` are; a
   plan naming a scripted seat for a plugin without the hook fails at
   resolution, not mid-episode.
5. **Determinism and replay.** The hook must be a pure function of its
   arguments and `cell.world_seed` (TERMS-Bench's kernel already is: it draws
   from the case's `world_seed`). Replay recomputes every scripted action and
   raises if it differs from the sealed one -- the R2 cross-check, applied to
   the seat that has no model to re-ask.
6. **Receipts.** `agent_profile_sha256_by_seat` keeps only model seats;
   `scripted_seats` is recorded on the receipt with its policy ids, so R12's
   seat-set check compares like with like. The scoring input's
   `SeatContext.profile_by_seat` likewise excludes scripted seats;
   `subject_seats` cannot name one (rule 2).
7. **Evidence.** The scripted-seat policy id and the family's implementation
   pin are enough to reproduce the turn; the receipt says so explicitly rather
   than leaving a seat with no provider record to be read as an omission.

## What this is not

- Not a harness that skips the model call: that path stays forbidden, because
  a *model* seat that returns without calling the model is a fabricated turn.
- Not a change to the phase graph, the replay goldens, or any case's
  `content_sha256`: TERMS-Bench's `counterpart_turn` stays a phase and a seat.
- Not pre-resolution: the counterpart keeps reacting to the agent's offers,
  which is the negotiation being measured.

## Review questions

- Is `RunSpec` the right home for `scripted_seats`, or the evaluation block?
  RunSpec, I think: it is a fact about how this run fills seats, not about
  what a block measures.
- Should a scripted seat's action be re-derived at *finalize* as well as
  replay? Replay covers it; finalize trusts the sealed store as it does for
  model seats.
