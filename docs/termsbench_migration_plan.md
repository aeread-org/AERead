# termsbench migration plan (kernel_scoring_contract_spec.md)

Written fresh for this migration (the branch's first attempt at this plan,
tag `termsbench-attempt1`, proposed a different, now-rejected reconciliation
under "Open item for milestone 2" — its leaf table, reference-source
classification, and paired-history constructibility analysis below are
carried over from that document largely unchanged; its proposed primary
choice and single-manifest reconciliation are not). Contract:
`kernel_scoring_contract_spec.md` sections 3–6 plus rulings R7–R13.

## The decision

Ruling R13 rule 1 (`kernel_scoring_contract_spec.md`):

> A `case_conditional` leaf may not be `primary_leaf_id` and may not be in
> `admission_leaf_ids`: both must exist for every execution admitted under
> one static manifest. A family whose headline is genuinely
> regime-conditional either chooses an unconditional cross-regime primary or
> splits that regime into a distinct family version with its own static
> manifest.

TERMS-Bench's leaf set is regime-conditional by the paper's own design
(`docs/termsbench_adapter_spec.md` section 2's verifier table): `SE+`/`AGR+`
exist only for Overlap cases (`Delta_i>0`), `FAGR-` only for No-deal cases
(`Delta_i<0`), `CritViol%` for both. The owner decision is the second
branch of R13 rule 1: split into two family versions, `termsbench.overlap`
and `termsbench.nodeal`, each with its own static leaf set. The first
branch (an unconditional cross-regime primary) was rejected as an invented
estimand — see `docs/termsbench_adapter_status.md`'s "The owner decision"
section for the full reasoning and the two alternatives considered.

## Leaf tables per family version

`measurement.py::build_leaves` already declared these leaves conditionally
by case regime (`payload["regime"]`) before this migration; the split
changes nothing about which leaves exist or their arithmetic, only which
family identity/manifest declares which static subset.

### `termsbench.overlap`

| Leaf id | Estimand id | `input_scope` | Verifier family | Evaluation class | Scope | Primary | Admission |
|---|---|---|---|---|---|---|---|
| `termsbench_surplus_efficiency_leaf` | `termsbench_surplus_efficiency` | `terminal_state` | `comparative` (`head_to_head`) | `deterministic` | `finalize_time` | **yes** | **yes** |
| `termsbench_feasible_agreement_leaf` | `termsbench_feasible_agreement` | `terminal_state` | `comparative` (`head_to_head`) | `deterministic` | `finalize_time` | no | no |
| `termsbench_protocol_compliance_leaf` | `termsbench_protocol_compliance` | `terminal_state` | `rule_constraint` (`constraint_satisfaction`) | `deterministic` | `finalize_time` | no | no |

### `termsbench.nodeal`

| Leaf id | Estimand id | `input_scope` | Verifier family | Evaluation class | Scope | Primary | Admission |
|---|---|---|---|---|---|---|---|
| `termsbench_no_deal_agreement_leaf` | `termsbench_no_deal_agreement` | `terminal_state` | `comparative` (`head_to_head`) | `deterministic` | `finalize_time` | **yes** | **yes** |
| `termsbench_protocol_compliance_leaf` | `termsbench_protocol_compliance` | `terminal_state` | `rule_constraint` (`constraint_satisfaction`) | `deterministic` | `finalize_time` | no | no |

**`termsbench_protocol_compliance_leaf`'s `input_scope` is corrected from
`"trajectory"` (its pre-migration declaration) to `"terminal_state"` in both
tables above.** `score_protocol_compliance` reads only
`outcome["critical_violations"]`/`["secondary_violations"]`/
`["malformed_action_schema"]` — terminal aggregates `step()` already folds
every round, never `FamilyScoringInput.phase_instances` directly. This was a
pre-existing mislabelling this migration corrects (kernel_scoring_contract_spec.md
section 1's own rule: "Trajectory-scoped leaves read
`scoring_input.phase_instances`; terminal ones read `scoring_input.outcome`");
the arithmetic is unchanged. Consequently every leaf in both manifests is
`terminal_state` and neither family version has a trajectory-scoped leaf.

No leaf in either manifest is `case_conditional`: `TermsBenchPlugin.validate_payload`
rejects any case whose own `"regime"` does not match the plugin instance's
`regime`, so every case a given family version's `build_leaves` ever sees
already has that family version's own regime — the static leaf set in each
table above is what `build_leaves` returns for every admitted case,
unconditionally. Ruling R13's `inapplicable_leaf_ids` hook is not needed by
either family version and neither declares one.

## Reference-source classification (unchanged from the pre-split analysis)

| Leaf | What it needs to be `status="ok"` | Classification |
|---|---|---|
| `termsbench_surplus_efficiency_leaf` (SE+) | `outcome["final_price"]` (episode-dependent), `outcome["agent_role"]`/`outcome["r_a"]`/`outcome["delta"]` (case-derived, read off *this episode's* `outcome` dict) | **replayed-episode** — needs this episode's own outcome; no other episode's result, no judge verdict |
| `termsbench_feasible_agreement_leaf` (AGR+) | `outcome["final_price"]` (episode-dependent) | **replayed-episode** |
| `termsbench_no_deal_agreement_leaf` (FAGR-) | `outcome["final_price"]` (episode-dependent) | **replayed-episode** |
| `termsbench_protocol_compliance_leaf` (CritViol%) | `outcome["critical_violations"]`/`["secondary_violations"]`/`["malformed_action_schema"]` — flags accumulated across every round of *this* episode's trajectory, folded into terminal state by `step()` | **replayed-episode** |

Every leaf in both family versions is **replayed-episode**: none needs a
separate-run artifact (another episode's result, e.g. a baseline-policy run)
and none needs a judge/rater verdict. `ReferenceSpec.reference_kind=
"head_to_head"` on the comparative leaves could look like a separate-run
dependency, but it is not one: `_counterpart_reference_sha256()`'s own
docstring is explicit that it hashes `kernel.py`'s `FAMILY_PRESETS`/
`ECONOMIC_PRESETS` — code-pinned constants keyed only by `family`
(Candid/Taciturn/Expressive), "never a per-episode runtime draw." It is a
validity/version-pin check on the fixed counterpart mechanism, not a
pointer to another episode's result. Per replayed-episode and
closed-form-from-case both counting as `finalize_time`, **every leaf in
both family versions is `scope="finalize_time"`; none is `deferred`.**

This is why every receipt driven through the generic finalizer for either
family version is genuinely `status="ok"`/`inclusion_status="included"`
(`docs/termsbench_adapter_status.md`'s "Receipt" sections) — unlike
collusion/govsim, whose primary needs a comparison baseline no
single-episode `FamilyScoringInput` ever carries.

## Seat scope (ruling R12): not applicable, unchanged by the split

Each family version's `family_manifest()` `roles` declares exactly one
seat ever testable: `"agent": {"testable": True, ...}`,
`"counterpart": {"testable": False, ...}` (the counterpart seat is always
the scripted `termsbench_counterpart_kernel_v1`, never a subject). Every
leaf's value is already single-seat by construction.
`seat_scope="cell"` (the default) is correct for every leaf in both
manifests; none is `seat_scope="subject_seat"`.

## Paired-history constructibility

`TermsBenchPlugin.outcome()` returns `termination_reason, final_price,
rounds_used, critical_violations, secondary_violations,
malformed_action_schema, regime, family, agent_role, r_a, delta` — final
aggregates and case-derived scalars, never the per-round `message`/
`transcript` (that field lives only on `state`, never copied into
`outcome()`). No `trajectory_outcome_paths` declaration is needed or exists
on either manifest.

Since every leaf in both family versions is `terminal_state`, the paired
fixtures need only satisfy R7's contrapositive precondition (byte-identical
outcome, differing trajectory) — there is no trajectory-scoped leaf to
witness, so ruling R9(b)'s sensitivity witness is vacuous for both family
versions by construction, not a gap in coverage. The construction actually
used (`tests/test_shared_runner_scoring_contract.py`'s
`_termsbench_overlap_fixtures`/`_termsbench_nodeal_fixtures`) is simpler
than the one this document's predecessor sketched (which varied prices
across rounds while holding the final bound price fixed): two runs with the
IDENTICAL price/decision/counterpart-draws sequence, differing ONLY in the
agent's own scripted message text. `outcome()` never reads message or
transcript, so this guarantees byte-identical outcomes by construction
while the sealed `phase_instances` still genuinely differ (the agent's own
logical-action response differs). This works for both regimes identically.

## R11: no upstream code

Ruling R11 (`kernel_scoring_contract_spec.md`) applies to both family
versions (no upstream `termsbench` code exists — pinned source is the paper
only, `kernel.py`'s own module docstring states this).
`docs/termsbench_adapter_status.md` states R11's required wording verbatim:
*"No upstream implementation exists; conformance means agreement with
independently hand-derived paper-formula goldens, not parity with upstream
code."* The spec's own 5 QC Gate-2 goldens (section 4) are all
Overlap-regime; this migration adds two No-deal-regime goldens for eq. 60
(FAGR-) that were missing, so every formula either family version scores
now has a hand-derived golden with the arithmetic beside the expected value
in the test source (`docs/termsbench_adapter_status.md`'s "R11 goldens"
section).

## What the rejected attempt's `__call__` did

`termsbench-attempt1`'s `TermsBenchScorer.__call__` always declared all four
leaves in one manifest and returned `invalid_measurement("wrong_regime")`
for whichever of `SE+`/`AGR+`/`FAGR-` did not apply to a case's own regime.
It was never reachable by `finalize_family_execution` in production either
(the branch never wired a finalizer receipt test), so this was never
exercised against a real receipt before being reset out of this branch's
history. No `_wrong_regime_envelope` helper or comparable mechanism exists
in the design actually implemented: the rejection now happens once, in
`TermsBenchPlugin.validate_payload`, before any measurement code ever sees
a wrong-regime case — there is no "wrong_regime" status anywhere in this
migration's code.
