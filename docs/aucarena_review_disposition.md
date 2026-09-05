# aucarena adapter — review disposition

Reviews consulted: `docs/aucarena_review_claude.md` (present).
`docs/aucarena_review_codex.md` does not exist in this worktree — handled
gracefully, no codex findings to disposition.

Each finding below was independently re-verified against the code (not just
re-read from the review) before any fix was applied.

## WARNING 1 — `aucarena_hammer_rule`'s accept/reject partition read
`record.envelope.valid` instead of independently recomputing it

**Disposition: fixed.**

Verified: `score_hammer_rule` (`src/aeread_families/aucarena/measurement.py`,
pre-fix lines ~522-526) built `round_bids` by filtering
`phase_instance.actions` on `record.envelope.valid`, and `envelope.valid` is
computed by `environment.py`'s own `legal()`/`parse_action()` gate
(`scheduler.py:570`), not re-derived independently by this leaf. Confirmed
the module docstring's "independently reproduced ... never from
`environment.py`'s own live state" claim held for the hammer/tie-break
arithmetic but not for which bids were even considered.

Fix: added `_independently_accepted_bid` (`measurement.py`), which
recomputes acceptance from each action's own recorded `record.parse` plus a
fresh `vendored.bid_sanity_check` call against the action's frozen pre-round
observation — the same recompute `score_bid_legality` already performs,
reused here so `score_hammer_rule`'s independence claim no longer rests on
`environment.py`'s legality gate having already run correctly.
`score_hammer_rule` now builds `round_bids` from
`_independently_accepted_bid(record)` instead of `record.envelope.valid`,
and reads the bid price from `record.parse.action["bid_price"]` instead of
`record.envelope.action["bid_price"]`.

Test added:
`tests/test_aucarena_parity.py::test_hammer_rule_does_not_silently_trust_a_forged_envelope_valid_flag`
— forges an `envelope.valid=True` for golden 3's genuinely illegal bid (150,
below the item's starting bid) plus the round consequences a buggy
`step()` would have derived from trusting that forged flag, and confirms
`score_hammer_rule` still raises `AucArenaMeasurementError` on its own,
without relying on `aucarena_bid_legality` having caught the bug first.

## SUGGESTION 2 — `parse_action`'s `"-1" in response` substring check can
misparse a well-formed negative-looking bid text, inherited from upstream

**Disposition: fixed** (documentation only, no behavior change).

Verified: `environment.py:327-328` does perform a substring check
(`"-1" in response`), matching upstream's own `if '-1' in result:`
(`auctioneer_base.py:196`) verbatim — this is a faithful reproduction of an
upstream quirk, not a defect introduced by this adapter, and none of the
five goldens' scripted policies emit a response containing a literal `-1`
substring for a non-withdraw reason. The reviewer's own text already
characterizes this as correctly documented and not requiring a behavior
change (changing the substring semantics would break upstream parity, which
this adapter must preserve exactly).

Action taken: added an inline comment at `environment.py`'s `"-1" in
response` branch spelling out the substring-vs-exact-match caveat
explicitly (previously only the module docstring's general "-1 sentinel"
description existed, without calling out the substring nuance), so a future
scripted-policy author is warned before writing a policy response that
contains a literal `-1` substring for a non-withdraw reason. No test added:
this is a comment-only change with no reachable behavior to regress, and no
existing golden exercises the edge case.

## SUGGESTION 3 — `docs/aucarena_adapter_spec.md`'s "Governing facts" say
`docs/benchmark_qc.md` does not exist in this repo

**Disposition: deferred-to-ledger** (already logged).

Verified: `docs/benchmark_qc.md` does not exist anywhere in this worktree
(`ls docs/benchmark_qc.md` fails), confirming the finding. This is a
repo-wide documentation gap in the shared QC-gate contract, not a defect in
the aucarena adapter's own code — the adapter's spec already states this
honestly rather than silently inventing a citation. A ledger entry for
exactly this gap already exists in `ledger_entries/aucarena.md` (first
entry, severity `medium`, "The aucarena workflow brief instructs
implementers to read `docs/benchmark_qc.md` ... No such file exists
anywhere in the repo"), logged during an earlier milestone. No duplicate
entry added; the existing entry was re-verified as still accurate and still
open.

## SUGGESTION 4 — Golden 4 never asserts `agent.profit` is untouched

**Disposition: fixed.**

Verified: `tests/test_aucarena_environment.py`'s
`test_golden_4_agents_gibberish_is_malformed_not_illegal` asserted
`agent.budget == 3200` and `winner == "field_high"` but not
`agent.profit == 0`, unlike golden 3's equivalent test. Logically redundant
(profit can only change via `win_bid`, unreachable given `winner ==
"field_high"` is independently asserted) but worth the one-line addition
for symmetry and to make the "zero mutation" claim equally explicit for
both invalid-action goldens, as the reviewer suggested.

Fix: added `assert result.outcome["seats"]["agent"]["profit"] == 0` to
`test_golden_4_agents_gibberish_is_malformed_not_illegal`.

## Summary

| # | Severity | Disposition |
|---|---|---|
| 1 | WARNING | fixed |
| 2 | SUGGESTION | fixed (doc-only) |
| 3 | SUGGESTION | deferred-to-ledger (pre-existing entry) |
| 4 | SUGGESTION | fixed |

Fixed: 3 (findings 1, 2, 4). Refuted: 0. Deferred: 1 (finding 3).

Re-ran after all fixes: family test files (`tests/test_aucarena_cases.py`,
`tests/test_aucarena_environment.py`, `tests/test_aucarena_measurement.py`,
`tests/test_aucarena_parity.py`, `tests/test_aucarena_replay.py`,
`tests/test_aucarena_vendored_upstream.py`) plus
`tests/test_shared_runner_smoke.py`, all green.

## Codex-review findings

Source: `docs/aucarena_codex_triage.md` (recovered second-reviewer transcript,
independently triaged into 8 counted findings plus one meta-observation,
Finding 0, about the transcript's own internal count mismatch — not an
adapter defect, not disposition below). All 8 counted findings were
classified **CONFIRMED** by the triage; none were REFUTED or OUT_OF_SCOPE.
Fixed in the triage's own listed order. Every fix below was verified with a
test that failed first, for the stated reason, against the pre-fix code
(confirmed by temporarily restoring the pre-fix file from a `git show
<prior-commit>:path` snapshot, re-running the new test alone, then restoring
the fix from a `/tmp` backup copy — never `git checkout` over uncommitted
work) before being confirmed green after the fix.

**Finding 1 — `AucArenaScorer` not callable.** *Fixed.* The kernel's real
calling convention (`finalize_family_execution`,
`aeread/shared_runner/family_evaluation.py`) calls whatever
`build_scorer(family_case)` returns as a function; `AucArenaScorer` was a
frozen dataclass with no `__call__`, so this crashed with `TypeError` the
moment aucarena ever ran through that path — no test in the family exercised
it, every test called a named method directly instead. Added
`AucArenaScorer.__call__` (adapts the bare terminal `outcome` mapping via a
small `_OutcomeOnlyResult` shim, since `aucarena_profit_vs_field` is the only
one of the four declared leaves that is terminal-state-scoped and
computable from `outcome` alone — the other three are trajectory-scoped and
this calling convention carries no trajectory data).
Test: `tests/test_aucarena_measurement.py::
test_scorer_is_callable_matching_the_kernels_real_calling_convention`.

**Finding 2 — malformed/illegal bids scored economically instead of
re-bid.** *Escalated, not auto-fixed.* Confirmed: upstream's own game
(`auction_workflow.py`) never lets a malformed or illegal response become a
final, scored action — it re-asks the bidder without a retry cap. This
adapter instead treats a malformed/illegal action as a final, zero-mutation
round outcome (`environment.py`'s own `# illegal or malformed: zero
mutation` comment), and `aucarena_profit_vs_field` reports a real, finite
economic score for that adapter-invented terminal state. Remediation
requires an actual product/architecture decision this pass did not have a
mandate to make unilaterally: (a) add a bounded retry loop to `step()`
matching upstream's shape but with a cap value nothing in the spec
specifies, which changes game semantics and would need re-authoring goldens
3/4's own "zero mutation" contract; or (b) have the measurement layer
declare the resulting terminal state's `aucarena_profit_vs_field` leaf
`invalid_measurement` instead of `ok` — but the only data that could drive
that determination (whether the tested seat ever produced a malformed/
illegal action) is trajectory data (`phase_instances`), which the leaf's own
Finding-1 fix established is *not* reachable from the kernel's real,
terminal-outcome-only calling convention without either a kernel signature
change or a new outcome/state schema field threaded through `environment.py`
(itself a further architecture decision with its own cascading impact on
`replay.py`'s state comparisons and every existing golden). Neither option
has a single spec-mandated answer. Not ledgered (not a kernel/shared_runner
defect — the gap is this family's own environment/measurement design).
Flagged in `docs/aucarena_adapter_status.md`'s "Known limits" section for a
human architecture call.

**Finding 3 — replay's `comparison.matches` accepts a validity-changing
tamper.** *Fixed.* Reproduced exactly as described: golden 5's single
recorded decision (`"-1"`, a legal withdraw) replayed as a malformed string
instead produces an identical downstream game state (no bid recorded either
way), so the existing `pre_state_sha256`/`post_state_sha256` per-phase
comparison agrees and the tamper passed `comparison.matches == True`. Added
`mismatched_action_classification_ids` to `StateComparison` /
`compare_episode_results` (`replay.py`), comparing each recorded action's
`(envelope.valid, parse.ok, legality.legal)` classification per phase
instance between the original and replayed run — data the state-hash
comparison never touched. `assert_replay_matches` now raises with a
specific reason for this class of mismatch.
Test: `tests/test_aucarena_replay.py::
test_tampering_a_legal_withdraw_into_a_malformed_response_is_caught_even_though_state_is_unchanged`.

**Finding 4 — per-call RNG reseeding can silently overturn an
already-resolved tie.** *Fixed* (already landed on this branch before this
pass, commit `619036f`, re-verified here, no further work needed).
`environment.py`'s `step()` now seeds one continuous `random.Random` per
round, threaded through every `vendored.record_bid` call, instead of
reseeding fresh per bidder call.
Test: `tests/test_aucarena_environment.py::
test_step_seeds_one_continuous_rng_per_round_not_per_bidder_call` (a
synthetic three-way tie; fails against the old per-call reseed, passes
against the fix).

**Finding 5 — the "mean-field" primary score is an invented, distortive
aggregation.** *Escalated, not auto-fixed.* Confirmed: `primary =
tested_profit - mean_field_profit`, an unweighted arithmetic mean over every
field seat, is not specified anywhere in `docs/aucarena_adapter_spec.md` or
`docs/verifier_taxonomy.md` — the taxonomy's `head_to_head` definition
permits a field-level comparison but does not mandate a mean, and an
always-withdraw field seat (profit `0`, present in this corpus by
construction) structurally dilutes a real, decisive loss against the field's
one competitive seat by roughly half (golden 1: `-1200` against
`field_high` alone vs. `-200` reported as `primary`). Every candidate fix
(minimum delta = "beat the whole field", drop a single `primary` entirely
and report only the per-opponent vector already in `metrics`, some other
weighting) is exactly as unspecified and invented as the mean it would
replace — none is spec-mandated, and picking one unilaterally would just
substitute a different invented number for the current one. Not ledgered
(not a kernel/shared_runner defect). Flagged in
`docs/aucarena_adapter_status.md`'s "Known limits" section for a human
decision on what `primary` should mean here, or whether it should exist at
all for a multi-seat field.

**Finding 6 — the estimand's own comparator identity is narrower than the
spec claims.** *Fixed*, partially, to the extent structurally reachable.
`_field_roster_sha256` hashed only the field roster; the spec (section 2)
also declares item order and `world_seed`/`case_id` pairing part of the
estimand identity. Extended the hash to also cover item order (reachable
from `family_case["items"]`). `case_id`/`world_seed` remain out of scope for
this leaf: `build_scorer` is called with only a bare `family_case` payload
— the kernel's own `plugin.build_scorer(family_case)` convention never
passes a `cell`, and both fields live on the outer `CaseManifest`/`PlanCell`,
not inside `payload` — so neither is reachable here without a kernel
signature change (not made; out of this pass's scope per the run
instruction). Narrowed `docs/aucarena_adapter_spec.md`'s own wording to
state this precisely instead of overclaiming full pairing coverage from
this one leaf.
Tests: `tests/test_aucarena_measurement.py::
test_profit_vs_field_reference_hash_distinguishes_item_order_not_only_the_field`
and `::test_build_scorer_reference_hash_reflects_the_real_cases_item_order`.

**Finding 7 — the "parity" tests are self-referential.** *Disclosed,
documentation only, not a code fix.* Confirmed and, as the triage itself
notes, already honestly disclosed in `tests/test_aucarena_parity.py`'s own
module docstring: both `environment.py`'s live decision and
`measurement.py`'s "independent" recompute call the identical vendored
functions, so this check cannot catch a bug transcribed into those vendored
functions themselves — only `tests/test_aucarena_vendored_upstream.py`'s
hand-derived numeric assertions defend against that, and the spec's own
"re-derive by hand" hardening step is explicitly non-gating and manual. No
code fix is possible that does not defeat its own purpose (any re-derivation
by someone who already has full view of the vendored code is not blind).
Made the residual gap explicit and prominent in
`docs/aucarena_adapter_status.md`'s "Known limits" section (previously only
visible inside one test module's own docstring).

**Finding 8 — module-wide silent skip hides 19 QC-Gate-1 tests.** *Fixed.*
Confirmed exactly as described: a missing pinned upstream checkout collapses
`tests/test_aucarena_cases.py`'s 19 tests into one `"1 skipped"` line via
`pytest.skip(..., allow_module_level=True)`, with
`docs/aucarena_adapter_status.md` previously (falsely) claiming "zero skips
anywhere in this family... there is no upstream bridge interpreter to be
missing." Generalized `conftest.py`'s existing `pytest_terminal_summary`
hook (already used for a missing tau2 bridge) into a small table of
required-skip-gates and added one row for this family:
`AEREAD_AUCARENA_QC_GATE_REQUIRED=1` now turns the skip into a failed run
with the reason and a provisioning hint, off by default so a local run is
unaffected. Corrected the status doc's false claim.
Tests: `tests/test_aucarena_qc_gate_visibility.py::
test_missing_upstream_checkout_skips_quietly_by_default` and `::
test_missing_upstream_checkout_fails_loudly_when_the_gate_is_required` — both
spawn `pytest` as a real subprocess against the real
`tests/test_aucarena_cases.py` file and the real `conftest.py` hook, not a
locally re-derived assumption about what either would do.

### Summary

| # | Finding | Disposition |
|---|---|---|
| 0 | transcript count mismatch (9 declared vs. 8 described) | not an adapter defect, not counted |
| 1 | `AucArenaScorer` not callable | fixed |
| 2 | malformed/illegal bids scored economically instead of re-bid | escalated (architecture decision) |
| 3 | replay accepts a validity-changing tamper | fixed |
| 4 | per-call RNG reseed can overturn a resolved tie | fixed (pre-existing, re-verified) |
| 5 | unspecified "mean-field" primary aggregation | escalated (architecture decision) |
| 6 | comparator identity narrower than spec claims | fixed (item order); case_id/world_seed structurally unreachable without a kernel change |
| 7 | self-referential parity tests | disclosed (documentation only) |
| 8 | module-wide silent skip | fixed |

Fixed: 4 (Findings 1, 3, 6, 8) plus 1 pre-existing (Finding 4, re-verified).
Documentation-only: 1 (Finding 7). Escalated, not auto-fixed: 2 (Findings 2,
5) — both require a product/architecture decision with more than one
defensible answer and no spec-mandated one; recorded in
`docs/aucarena_adapter_status.md`'s "Known limits" section rather than
guessed. Refuted: 0. Deferred-to-ledger: 0 (none of the 8 findings concern
`src/aeread/shared_runner/` kernel code).

Re-ran after all fixes: family test files (`tests/test_aucarena_cases.py`,
`tests/test_aucarena_environment.py`, `tests/test_aucarena_measurement.py`,
`tests/test_aucarena_parity.py`, `tests/test_aucarena_replay.py`,
`tests/test_aucarena_vendored_upstream.py`,
`tests/test_aucarena_qc_gate_visibility.py`) plus
`tests/test_shared_runner_smoke.py`: 118 passed, 0 failed. Full repo suite:
834 passed, 31 skipped, 1 xfailed, 0 failed (skip set unchanged by this
work).

## Verification follow-up (independent cross-model check)

Source: `docs/aucarena_fix_verification.md`, a read-only, independent re-check of the
"Codex-review findings" pass above. It found six items requiring further action: Findings 6
and 8 claimed fixed but incomplete; Findings 2, 5, and 7 explicitly unresolved (already
disclosed as such above, not claimed fixed); Finding 0 unchanged. Worked in that order. One
additional, already-decided item was folded in per standing instruction: `AucArenaScorer`'s
`__call__` (added for Finding 1) is a real instance of ledger entry **D-19**
(`runner_defect_ledger.md`) and is disclosed here rather than fixed, per that ledger entry's
own explicit warning against giving a multi-leaf scorer a `__call__` that silently picks one
leaf as primary.

**Finding 6 — comparator identity narrower than spec claims.** *Narrowed, not fixed further.*
Re-verified independently: `build_scorer(family_case)` is called, at every call site in this
family's own tests and by the kernel's own `plugin.build_scorer(family_case)` convention, with
only the case's `payload` (`AucArenaPlugin.validate_payload(case.payload)`) — a dict that has
no `case_id`/`world_seed` keys; those live one level up, on the outer `CaseManifest`. The
item-order half of the fix (commit `967c912`) is genuine and already independently tested
(`tests/test_aucarena_measurement.py::test_profit_vs_field_reference_hash_distinguishes_item_order_not_only_the_field`,
`::test_build_scorer_reference_hash_reflects_the_real_cases_item_order`); the `case_id`/
`world_seed` half the reviewer's transcript wanted is structurally unreachable from this leaf
without a kernel signature change, not an oversight this pass declined to fix. Added a
dedicated "Known limits" bullet to `docs/aucarena_adapter_status.md` stating this precisely
(previously only stated inside `measurement.py`'s own docstring and the spec, not in the one
doc a reviewer is told to read for claims). No test added: there is nothing reachable to pin
down that is not already pinned.

**Finding 8 — module-wide silent skip.** *Fixed further, with test.* Confirmed the gap
exactly as the independent check described: the opt-in `AEREAD_AUCARENA_QC_GATE_REQUIRED`
mechanism worked correctly when set, but nothing in this repo's own
`.github/workflows/ci.yml` sets it (nor the pre-existing tau2 equivalent), so an ordinary
default run — every contributor's and every CI job's actual invocation — stayed completely
silent about 19 skipped QC-Gate-1 tests, unchanged from the pre-Finding-8 behavior.
`conftest.py`'s `pytest_terminal_summary` now reports a matching gate skip unconditionally
(test count, reasons, and the enabling env var), for every row in `_REQUIRED_SKIP_GATES`
(tau2's included, not just aucarena's); only the exit status stays gated behind the env var, so
local runs are never surprised into failing.
Test: `tests/test_aucarena_qc_gate_visibility.py::
test_missing_upstream_checkout_prints_a_visible_note_even_when_the_gate_is_not_required` —
written first against the pre-fix hook and confirmed failing for the right reason (no note
printed at all when the gate is unset), then green after the fix.
Mutation result: restored the pre-fix early-`continue` guard (via a `/tmp` backup, never
`git checkout`), re-ran `tests/test_aucarena_qc_gate_visibility.py` — the new test failed with
exactly the expected `AssertionError` (missing note in stdout) while the two pre-existing tests
in that file still passed unchanged, confirming the new test is not vacuous. Reverted the
mutation and restored the fix immediately after.
Residual, explicitly not fixed: this repo's own CI still does not set the enabling env var, so
a default CI run today shows, but does not fail on, the note — enforcing it there would first
require provisioning the pinned upstream checkout in CI, a separate decision out of this pass's
scope (see `docs/aucarena_adapter_status.md`'s Evidence section).

**Finding 2 — malformed/illegal bids scored economically instead of re-bid.** *Narrowed,
already correctly disclosed above, not fixed.* Re-confirmed the escalation reasoning still
holds (no single spec-mandated answer between a bounded retry loop and an
`invalid_measurement` status). Strengthened traceability only: `docs/aucarena_adapter_status.md`
now names the exact tests that pin today's disclosed behavior —
`tests/test_aucarena_measurement.py::test_golden_3_earns_no_credit` and
`::test_golden_4_other_leaves_match_golden_3_outcome`, both of which assert `status == "ok"`
for a malformed/illegal round today — so a future silent change to this status breaks a named
test instead of slipping through unremarked. No new test added; these two already exist and
already bite.

**Finding 5 — unspecified mean-field primary.** *Narrowed, already correctly disclosed above,
not fixed.* Same reasoning as Finding 2: inventing a weighting would just substitute one
unspecified number for another. `tests/test_aucarena_measurement.py::
test_golden_1_profit_vs_field_is_finite_and_mixed_sign` already asserts
`score.primary.value == pytest.approx((300.0 - 1000.0) / 2.0)` — the exact unweighted-mean
formula — so this too already has a test that bites a silent change; named explicitly in
`docs/aucarena_adapter_status.md` now.

**Finding 7 — self-referential parity tests.** *Unchanged, already correctly disclosed above.*
Re-confirmed no code fix is possible that does not defeat the check's own purpose. No further
action; the existing disclosure in both `tests/test_aucarena_parity.py`'s module docstring and
`docs/aucarena_adapter_status.md`'s Known-limits section remains accurate.

**Finding 0 — transcript declares 9 findings but describes 8.** *Unchanged, confirmed as a
meta-observation, not an adapter defect.* Re-read the recovered transcript
(`docs/aucarena_review_codex.md`): "2 critical, 5 high, 2 medium" sums to 9, but the "Key
blockers include..." sentence lists exactly 8 items, matching Findings 1-8 above one-for-one in
order. The transcript is explicitly a recovery of a sandboxed run that could not write its own
report file; there is no way to reconstruct whatever a lost ninth item might have been from
what remains. Correctly excluded from the numbered findings above; this is an explicit
confirmation that the exclusion was re-checked, not a silent drop.

**D-19 — `AucArenaScorer.__call__` collapses four leaves to one.** *Disclosed, not fixed,
per standing instruction.* Confirmed `__call__` (commit `059f46a`) forwards only to
`score_profit_vs_field`, the sole leaf reachable from a bare terminal `outcome`, and has no way
to also surface `aucarena_budget_invariant`, `aucarena_bid_legality`, or
`aucarena_hammer_rule` when invoked through the kernel's real single-`ScoreEnvelope` calling
convention — exactly the risk `runner_defect_ledger.md` entry D-19's 2026-09-02 addendum warns
against ("do NOT paper over this per-adapter"). Not aucarena-specific: three other families
(`govsim`, `steer`, `negarena`) independently added the same shape of `__call__` while closing
their own reviews, and D-19 is already open, tracked, and awaiting a kernel-owner ruling on
whether `finalize_family_execution` should seal a leaf vector or a family-declared primary.
Added a "Known limits" bullet to `docs/aucarena_adapter_status.md` stating this plainly instead
of leaving `__call__`'s docstring (which frames the single-leaf forward as simply "the
additional surface the real kernel calling convention needs") as the only place a reader could
learn this. No code change: `__call__` is not touched, and no leaf-picking logic was added.

### Summary

| # | Finding | This-pass disposition |
|---|---|---|
| 0 | transcript count mismatch (9 declared vs. 8 described) | confirmed meta-observation, not counted (unchanged) |
| 2 | malformed/illegal bids scored economically instead of re-bid | narrowed (test cross-references added; escalation reasoning re-confirmed) |
| 5 | unspecified "mean-field" primary aggregation | narrowed (test cross-reference added; escalation reasoning re-confirmed) |
| 6 | comparator identity narrower than spec claims | narrowed (status doc now states the case_id/world_seed exclusion explicitly) |
| 7 | self-referential parity tests | unchanged (disclosure re-confirmed accurate) |
| 8 | module-wide silent skip | fixed further (always-visible note; test + mutation-verified) |
| D-19 | `AucArenaScorer.__call__` collapses four leaves to one | disclosed (status doc bullet added; ledger entry unchanged, per standing instruction) |

Fixed further, with a failing-first test and a confirmed-dying mutation: 1 (Finding 8).
Narrowed (documentation only, existing tests already bite where applicable): 4 (Findings 2, 5,
6, and D-19's disclosure). Unchanged, re-confirmed as already correctly handled: 2 (Findings 0,
7).

Re-ran after this pass: family test files (`tests/test_aucarena_cases.py`,
`tests/test_aucarena_environment.py`, `tests/test_aucarena_measurement.py`,
`tests/test_aucarena_parity.py`, `tests/test_aucarena_replay.py`,
`tests/test_aucarena_vendored_upstream.py`, `tests/test_aucarena_qc_gate_visibility.py`) plus
`tests/test_shared_runner_smoke.py`: 119 passed, 0 failed (one more than before — the new
Finding-8 test). Full repo suite: 835 passed, 31 skipped, 1 xfailed, 0 failed (skip set
unchanged by this work; exit code 0, confirming the Finding-8 fix never flips a default run
red).
