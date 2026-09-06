# Kernel R9/R10 (scoring-contract) review — dispositions

**Provenance.** This document records an independent review of branch
`zeyu/kernel-r9r10` (5 commits over `origin/main`, ruling R9/R10 of
`kernel_scoring_contract_spec.md`, round 3), dated 2026-09-05. The review
examined the scoring-contract protocol test
(`tests/test_shared_runner_scoring_contract.py`) and the
`trajectory_outcome_paths` schema validator
(`src/aeread/shared_runner/schemas.py`) as they stood before this document's
fixes, and reported five findings. The **Dispositions** section below was
added by the engineer who verified each finding against the code and, where
confirmed, fixed it. Every disposition that claims a fix names the
commit, the test whose failure-before/pass-after was mutation-verified (the
fix was temporarily reverted or neutered via a `/tmp` backup-and-restore,
never `git checkout` on a file holding uncommitted work, the target test
confirmed to fail for the expected reason, then the fix was restored and the
suite confirmed green again), and states plainly where the review's claim
was accurate but not, on inspection, an actionable gap.

## Findings, as reviewed

1. **Blocker — the paired-history projection can be made vacuous.**
   `_assert_trajectory_outcome_paths_are_consistent` (protocol path around
   `tests/test_shared_runner_scoring_contract.py:1244` for `project_outcome`
   and the paired-history check body around lines 1484-1692) let a family
   declare a `trajectory_outcome_paths` entry covering an object subtree
   wider than the trajectory itself (e.g. `"/payload"` when `payload` holds
   both terminal fields and the embedded history). Projecting that path away
   from both fixtures produced `{}` on each side, so the paired-history
   equality check compared `{} == {}` and passed without ever comparing
   terminal state — the exact vacuous check ruling R7's contrapositive exists
   to prevent. A second, related gap: a declared path was never required to
   point at a per-step record sequence, so an object subtree could hide
   terminal facts behind the projection even when the projection was not
   fully empty.

2. **Should-fix, partly refuted — R10's docstring/message overstate
   "canonical derivation from phase_instances."** The module banner comment
   (around `tests/test_shared_runner_scoring_contract.py:1215-1225`) and
   `_assert_trajectory_outcome_paths_are_consistent`'s docstring/assertion
   message (around line 1273) described the check as verifying the outcome's
   copy against a "canonical derivation... from `phase_instances`." What the
   check actually does — and all a family-agnostic kernel can do — is read
   the SAME JSON pointer from `_final_replayed_state` (the state
   `plugin.terminal()` was called on, the product of re-executing the
   sealed transitions through the family's own transition function) and
   require the sealed outcome copy to match it. It does not re-derive
   history from actions, so a family whose transition function itself
   mis-records history is out of scope, and a family whose outcome stores
   the trajectory under a different field name than its own state (e.g.
   outcome `"/public_history"` from state `"/history"`) could not declare
   that path — the pointer read into `final_state` raised a raw `KeyError`
   instead of a named, diagnosable failure.

3. **Blocker — the sensitivity witness accepted uncontrolled pairs.**
   `_assert_trajectory_leaves_are_witnessed` (around
   `tests/test_shared_runner_scoring_contract.py:1300`) scanned EVERY pair of
   supplied fixtures for a content difference on a `trajectory`-scoped leaf.
   A leaf that ignores `phase_instances` entirely but happens to read some
   outcome/case field that merely differs between two arbitrary fixtures
   still passed the witness — defeating its purpose (catching a family that
   relabels a terminal leaf as `trajectory`-scoped specifically to dodge R7's
   contrapositive, since `trajectory`-scoped leaves are never checked for
   invariance across the paired-history pair).

4. **Should-fix — accepted pointer syntax exceeded what projection
   supports.** `_JSON_POINTER_RE` (`src/aeread/shared_runner/schemas.py:28`)
   accepted any RFC 6901 pointer with at least one non-empty segment,
   including an array-index segment (e.g. `"/history/0"`), and
   `_json_pointer_get` (the protocol test's own read helper) follows list
   indices without complaint. But `_drop_json_pointer` (the projection
   helper the protocol path actually uses to build the paired-history
   comparison) raises `TypeError` the moment it is asked to navigate through
   a list. A manifest accepted as schema-valid at declaration time could
   therefore never complete the scoring-contract protocol — the failure
   would surface far from the mistake, as a crash inside the protocol test
   rather than a validation error at authoring time.

5. **Should-fix — the R9 end-to-end tests bypassed the registered-family
   protocol path.** The four synthetic-family tests exercising rulings
   R9/R10 end-to-end (`tests/test_shared_runner_scoring_contract.py:1790-2008`:
   `test_r9_projection_pairs_a_trajectory_embedding_outcome_when_the_path_is_declared`,
   `test_r9_projection_fails_to_pair_when_the_embedded_path_is_not_declared`,
   `test_sensitivity_witness_rejects_a_trajectory_leaf_that_ignores_the_trajectory`,
   `test_r10_rejects_a_corrupted_trajectory_outcome_copy_end_to_end`) built
   their own scoring inputs and called `project_outcome`/
   `_assert_trajectory_outcome_paths_are_consistent`/
   `_assert_trajectory_leaves_are_witnessed` directly, bypassing everything
   else `test_every_registered_family_obeys_the_scoring_contract`'s per-family
   body checks (leaf-set/primary/admission conformance, evidence provenance,
   leaf-identity stability across fixtures, the determinism pre-check). A
   regression in how the real protocol assembles and calls those helpers
   could go unnoticed by tests that never go through that assembly.

## Dispositions

Legend: **FIXED** = confirmed and closed with a code change and a
mutation-verified regression test. **PARTLY REFUTED** = the finding's
factual claim about the code (the wording) held up, but the underlying
mechanism it described was already correct; the fix is a documentation/
error-message correction, not a behavior change.

### Finding 1 — the paired-history projection can be made vacuous

**FIXED.** Two guards added:

- **Guard (a)**: `_assert_projection_is_not_vacuous` asserts each fixture's
  projected outcome is a non-empty mapping, called on both fixtures at the
  point in the protocol path where the paired-history projection is
  computed, before the equality comparison. Message names the declared
  `trajectory_outcome_paths` and states the paired-history check (ruling R7)
  would be vacuous.
- **Guard (b)**: inside `_assert_trajectory_outcome_paths_are_consistent`,
  each declared path's outcome value must be a `list`/`tuple` (a per-step
  record sequence), asserted immediately after the path is navigated and
  before the R10 equality check.

Commit: `51105424` — "test(scoring-contract): reject a trajectory projection
that erases terminal state".

Tests added: `test_projection_is_not_vacuous_rejects_a_projection_erased_to_an_empty_mapping`
(guard a, unit), `test_trajectory_outcome_path_consistency_rejects_a_mapping_shaped_path`
(guard b, unit), `test_r9_projection_erases_the_entire_outcome_when_the_declared_path_is_over_broad`
(end-to-end, mirrors `test_r9_projection_fails_to_pair_when_the_embedded_path_is_not_declared`
with a new synthetic `_OverBroadTrajectoryEmbeddingPlugin` that nests every
outcome field under one `"/payload"` key).

Mutation result: with guard (a)'s assertion body replaced by `pass`, both the
unit test and the end-to-end test failed with "DID NOT RAISE AssertionError".
With guard (b)'s assertion removed, `test_trajectory_outcome_path_consistency_rejects_a_mapping_shaped_path`
failed the same way. Both guards restored from the `/tmp` backup; full file
green again (25/25, then 29/29 after later findings added more tests).

**Accepted residual (second-pass review, findings R2(a)/R2(b)):** a second
review pass found the shape guards above satisfiable by an empty list, and
found that they are structural regardless -- they check byte-equality and
shape, not domain meaning, so a family that declares a field holding its
actual terminal result as a `trajectory_outcome_path` (a list-shaped one)
still passes every guard here. R2(a) (mechanical, closed) added a fourth
guard: a declared trajectory sequence must be non-empty whenever
`phase_instances` replayed at least one transition. R2(b) (documentation,
accepted as a permanent residual, not a code change) records plainly, in
`project_outcome`'s docstring and both projection guards' docstrings/comments,
that no structural guard can decide WHICH residual field is a genuine
terminal fact -- that declaration is reviewed by a human exactly like the
primary-leaf choice (spec section 5), and the family's own supplied fixtures
are the conformance evidence for it, not an adversarial boundary this kernel
enforces unattended. See "Second pass" below for the full disposition.

### Finding 2 — R10's docstring/message overstate "canonical derivation from phase_instances"

**PARTLY REFUTED, and fixed as a wording/error-handling correction.** The
review's claim about the CODE was accurate — the mechanism has always been a
direct re-read of the same pointer from `_final_replayed_state`, never a
derivation of history from actions — but this is not a behavioral gap in the
check itself, only in how it was described and in one unhandled edge case
(a mis-named field raising a raw `KeyError`). Fixed: reworded the module
banner comment and the function's docstring/assertion message to state
exactly what is compared and its two limits (a family's own transition
function mis-recording history is out of scope; a renamed trajectory field
cannot be declared); converted the `KeyError` from reading `final_state` into
a named `AssertionError` via `try`/`except ... raise ... from error`.

Commit: `4aa2e2c6` — "docs(scoring-contract): state precisely what ruling
R10 compares".

Test added: `test_r10_rejects_a_declared_path_the_final_state_does_not_have`
(outcome field `"/public_history"` not present in the final state, which
only carries `"/history"`).

Mutation result: with the `try`/`except` reverted to a bare
`derived_value = _json_pointer_get(final_state, pointer)`, the new test
failed with an uncaught `KeyError` instead of the expected `AssertionError`.
Restored from the `/tmp` backup; suite green again (29/29).

### Finding 3 — the sensitivity witness accepted uncontrolled pairs

**FIXED.** `_assert_trajectory_leaves_are_witnessed` now restricts witness
candidates to CONTROLLED pairs: pairs whose projected outcomes (per
`project_outcome` with the family's declared `trajectory_outcome_paths`) are
byte-identical under `canonical_json_bytes` AND whose `phase_instances`
differ — exactly R7's own paired-history precondition. On a controlled pair
nothing outside the trajectory differs, so any `_score_measurement_content`
difference (including a bare status/validity flip) is trajectory-caused;
the content comparison itself is unchanged. If zero controlled pairs exist
among the supplied fixtures, the assertion says so explicitly and names the
fixture count. The "missing witness" message now also reports how many
controlled pairs existed.

Commit: `42d9fd60` — "fix(scoring-contract): witness trajectory leaves on
controlled pairs only".

Tests updated: `test_sensitivity_witness_passes_when_a_trajectory_leaf_changes_on_some_pair`
and `test_sensitivity_witness_fails_when_a_trajectory_leaf_ignores_every_fixture`
now use controlled-pair fixtures (shared outcome, differing
`phase_instances`); the two end-to-end embedding tests that call this helper
now pass `trajectory_outcome_paths` so their pairs remain controlled. Tests
added: `test_sensitivity_witness_rejects_a_leaf_that_only_changes_on_an_uncontrolled_pair`
(a leaf constant on the one controlled pair but differing on an uncontrolled
one must still fail), `test_sensitivity_witness_counts_a_status_only_flip_on_a_controlled_pair`
(a bare status/validity flip on a controlled pair, with `primary` held
constant, still counts), `test_sensitivity_witness_requires_at_least_one_controlled_pair`
(no controlled pair among the supplied fixtures is rejected explicitly).

Mutation result: with the controlled-pair restriction replaced by "every
pair" (the pre-fix shape), exactly the two tests designed to distinguish
controlled from uncontrolled witnessing failed
(`test_sensitivity_witness_rejects_a_leaf_that_only_changes_on_an_uncontrolled_pair`,
`test_sensitivity_witness_requires_at_least_one_controlled_pair`); the other
five witness tests remained green, confirming the mutation was caught
precisely where intended. Restored from the `/tmp` backup; suite green again
(29/29).

### Finding 4 — accepted pointer syntax exceeded what projection supports

**FIXED.** `_json_pointer_tuple` (`src/aeread/shared_runner/schemas.py`,
shared by both `MeasurementDeclaration.from_dict` and `__post_init__`, so
both the authoring path and the `dataclasses.replace` bypass are covered by
one change) now rejects any segment that is all ASCII digits (RFC 6901
array-index form) and rejects one declared path being a strict prefix of
another declared path as redundant overlap. The comment above
`_JSON_POINTER_RE` states the restriction and its reason (the
scoring-contract protocol's projection helper can only navigate JSON
objects).

Commit: `8b7be0da` — "fix(schemas): restrict trajectory_outcome_paths to
object-field pointers".

Tests added: `test_measurement_declaration_rejects_an_array_index_trajectory_outcome_path`
and its `_from_dataclasses_replace` counterpart, `test_measurement_declaration_rejects_overlapping_trajectory_outcome_paths`
and its `_from_dataclasses_replace` counterpart, and
`test_measurement_declaration_accepts_a_nested_object_field_trajectory_outcome_path`
(mutation-style: a valid nested object-field path like `"/payload/history"`
must remain accepted — this guard restricts pointer shape, not nesting
depth).

Mutation result: with the new segment-shape and overlap checks removed from
`_json_pointer_tuple`, all four rejection tests failed with "DID NOT RAISE
AuthoringValidationError" while the acceptance test remained green. Restored
from the `/tmp` backup; suite green again (88/88 in
`test_shared_runner_schemas.py`).

### Finding 5 — the R9 end-to-end tests bypassed the registered-family protocol path

**FIXED**, in two commits as specified.

**Extraction** (no behavior change): the per-family body of
`test_every_registered_family_obeys_the_scoring_contract` was moved,
unchanged, into a module-level `_assert_family_obeys_the_scoring_contract(key,
registration, cases)` returning a `_FamilyContractResult` (the per-case
`(scoring_input, FamilyScoreSet)` pairs and the witness-pair mapping, so a
caller can make its own additional assertions on top of what the function
already checked). The registered-family test's loop now calls it unchanged.
Commit: `4e05bc3b` — "refactor(scoring-contract): extract the per-family
protocol check". Verified behavior-preserving: the full file's pass count was
29/29 both immediately before and immediately after this commit.

**Re-pointing** the four end-to-end tests: `_with_declared_leaf_policy` gained
an optional `trajectory_outcome_paths` parameter (default `()`, so the four
real-family fixture builders are unaffected); a new `_embedding_fixtures`
helper builds N labelled episodes for a given embedding plugin factory and
attaches a two-leaf policy plus the declared `trajectory_outcome_paths` onto
a copy of the REAL trusted `kernel_contract_reference_v1` manifest (the
identity `_TrajectoryEmbeddingPlugin` and its siblings are actually
registered under). All four tests now build a manifest/plugin/fixtures
triple, register it in a fresh `PluginRegistry`, and call
`_assert_family_obeys_the_scoring_contract` — the same path the registered-
family test uses — instead of calling the R9/R10 helpers directly. The
specific witness-pair and terminal-leaf-content assertions from the original
tests were kept, now read off `_FamilyContractResult`.

Commit: `df32a961` — "test(scoring-contract): drive the R9 end-to-end
fixtures through the protocol path".

Deviation note: `test_r10_rejects_a_corrupted_trajectory_outcome_copy_end_to_end`
originally hand-tampered an already-replayed `FamilyScoringInput` via
`dataclasses.replace`, which the protocol path (which replays scoring inputs
itself from case + sealed evidence) has no hook to accept. Routed through the
protocol path via a new synthetic `_TrajectoryCorruptingEmbeddingPlugin`
whose `outcome()` seals a genuinely reversed copy of the trajectory — a real
sealed-episode bug, caught by the real protocol path, rather than a
post-hoc-tampered value passed directly to the helper. This is arguably a
strictly more end-to-end test than the one it replaces, not a narrower one.

Mutation results:
- Disabling `_TrajectoryCorruptingEmbeddingPlugin`'s reversal (sealing the
  correct trajectory) made
  `test_r10_rejects_a_corrupted_trajectory_outcome_copy_end_to_end` fail —
  the protocol still raised `AssertionError`, but for an unrelated reason
  ("supplies fewer than two contract fixtures"), not a match on "does not
  match the same pointer read", confirming the test's specific match string
  is sensitive to the intended corruption and not to some other, incidental
  failure.
- Declaring `("/labels",)` instead of `()` in
  `test_r9_projection_fails_to_pair_when_the_embedded_path_is_not_declared`
  made the protocol pass with no raise at all, confirming that test is
  sensitive to the declaration being absent.
- Swapping `_TrajectoryIgnoringEmbeddingPlugin` for the correct
  `_TrajectoryEmbeddingPlugin` in
  `test_sensitivity_witness_rejects_a_trajectory_leaf_that_ignores_the_trajectory`
  made the protocol pass with no raise, confirming that test is sensitive to
  the leaf actually ignoring the trajectory.

All three mutations were restored from the `/tmp` backup; suite green again
(29/29 in `test_shared_runner_scoring_contract.py`; 117/117 combined with
`test_shared_runner_schemas.py`; 127/127 combined with
`test_shared_runner_smoke.py`).

## Final verification

```
../../.venv/bin/python -m pytest tests/test_shared_runner_schemas.py \
  tests/test_shared_runner_scoring_contract.py tests/test_shared_runner_smoke.py \
  -q -p no:cacheprovider
```

127 passed, 0 failed.

## Second pass

A second-pass review of the seven first-pass commits (`51105424` through
`2fa14a9f`) closed findings 2, 4, and 5's original gap, and raised three
residuals against the first pass's own fixes, dated 2026-09-05.

### R1 (finding 3, tighten) — a controlled pair did not require the same case

**FIXED.** `_assert_trajectory_leaves_are_witnessed`
(`tests/test_shared_runner_scoring_contract.py:1496`) required a
byte-identical projected outcome and differing `phase_instances` for a pair
to count as "controlled," but not the same `family_case`. Two fixtures from
DIFFERENT cases can share a byte-identical projection (same outcome shape,
no declared paths) while disagreeing on the case payload; a leaf that reads
only that payload -- never the trajectory -- would then be wrongly witnessed
by the case difference alone. Fixed: `produced_by_case` (built in
`_assert_family_obeys_the_scoring_contract`) now carries each fixture's
`family_case` alongside its scoring input and score set, and a controlled
pair additionally requires `canonical_json_bytes(left_case) ==
canonical_json_bytes(right_case)`. The "no controlled pair" message now says
"same case, byte-identical projected outcome, differing phase_instances".
The docstring's causality claim was reworded: on a controlled pair the only
remaining uncontrolled input is `evidence_refs`, which the contract
designates provenance-only (excluded from `_score_measurement_content`); a
scorer that turns sealed event ids into measurement content violates the
provenance rule on its own terms and is out of scope for this witness,
exactly as it is out of scope for R7's contrapositive -- stated as the
accepted residual.

Commit: `cf85c02f` — "fix(scoring-contract): a controlled witness pair must
share its case".

Test added: `test_sensitivity_witness_rejects_a_pair_whose_case_differs_even_with_matching_projection`
(`tests/test_shared_runner_scoring_contract.py:2668`) — two fixtures with
identical outcome/projection and differing `phase_instances` but different
cases; the pair must not count as controlled, and with no other pair
supplied the witness is rejected with "no controlled pair". The existing
positive test (`test_sensitivity_witness_passes_when_a_trajectory_leaf_changes_on_some_pair`)
was updated to share one case across all its fixtures and confirmed still
passing.

Mutation result: with the case-equality clause removed from the controlled-
pair condition, exactly the new test failed ("DID NOT RAISE AssertionError");
all seven other witness tests, including the positive controlled-pair test,
remained green. Restored from the `/tmp` backup; suite green again (30/30).

### R2 (finding 1, residual) — shape guards satisfiable by an empty list; guards are structural, not semantic

**R2(a) FIXED.** `_assert_trajectory_outcome_paths_are_consistent`
(`tests/test_shared_runner_scoring_contract.py:1412`) required a declared
path's outcome value to be A sequence (guard b, finding 1), but not a
NON-EMPTY one. Reaching that line already means
`_final_replayed_state(scoring_input.phase_instances)` found at least one
transition (it raises `ValueError` otherwise, before the per-path loop ever
starts) -- so an empty embedded trajectory at that point is never honest: the
family's own replay produced steps, but its sealed copy claims none. Added a
fourth guard, immediately after guard (b): the declared path's outcome value
must be non-empty. Test added:
`test_r10_rejects_an_empty_embedded_trajectory_beside_a_non_empty_replay`
(`tests/test_shared_runner_scoring_contract.py:2519`) — `phase_instances`
replays one transition, but the declared path's outcome copy is `[]`;
rejected with a message naming the inconsistency. Mutation result: with the
new assertion removed, the test failed ("DID NOT RAISE AssertionError");
restored from the `/tmp` backup, suite green again (31/31).

**R2(b) is an accepted, documented residual, not a code change.** All of the
projection/consistency guards (`project_outcome`, `_assert_projection_is_not_vacuous`,
guard (b), and R2(a)'s new non-empty check) are STRUCTURAL: they check shape
and byte-equality, never domain meaning. None of them can tell a genuine
per-step trajectory field apart from some OTHER list-shaped field the family
declared instead, and none of them can tell whether a family's declared
trajectory path happens to ALSO be where its real terminal result lives. A
family that declares its actual terminal-result field (list-shaped) as a
`trajectory_outcome_path` would have it projected away and pass every guard
here. This is now stated plainly in `project_outcome`'s docstring
(`tests/test_shared_runner_scoring_contract.py:1344`), in
`_assert_projection_is_not_vacuous`'s docstring (`:1369`), and in the guard
(b)/R2(a) comments inside `_assert_trajectory_outcome_paths_are_consistent`
(`:1412`): that declaration is reviewed by a human exactly like the
primary-leaf choice (spec section 5), and the family's own supplied fixtures
are the conformance evidence for it, not an adversarial boundary this kernel
enforces unattended. No further code change is planned against this residual.

Commit: `177c9b9d` — "fix(scoring-contract): an embedded trajectory may not
be empty beside a non-empty replay" (includes the R2(b) doc wording and the
Finding 1 update in this document).

### R3 (finding 5, residual) — the over-broad-projection end-to-end test still bypassed the protocol path

**FIXED.** `test_r9_projection_erases_the_entire_outcome_when_the_declared_path_is_over_broad`
(`tests/test_shared_runner_scoring_contract.py:2208`) called
`project_outcome`/`_assert_projection_is_not_vacuous` directly on a
hand-replayed scoring input, so it would have stayed green even if
`_assert_family_obeys_the_scoring_contract` stopped calling the
vacuous-projection guard entirely. Re-pointed through that helper: a new
synthetic single-leaf family (`_OverBroadTrajectoryEmbeddingPlugin`,
`:557`) whose outcome consists ENTIRELY of the per-step `labels` sequence
(a genuine, non-empty list, at the same state key `_ReferencePlugin.step`
already uses, so it also satisfies finding 1's guard (b), R2(a)'s non-empty
guard, and ruling R10's same-pointer consistency check) declares `"/labels"`
as its sole `trajectory_outcome_path`. Its one leaf is `trajectory`-scoped
and reads only `phase_instances`, so nothing upstream of the vacuous guard
has any other reason to reject it. The test builds a real two-fixture
episode pair, attaches the leaf policy and declaration to a copy of the
trusted `kernel_contract_reference_v1` manifest (`_with_declared_leaf_policy`),
registers it, and asserts `_assert_family_obeys_the_scoring_contract` raises
with the "vacuous" message.

Commit: `c1ecd6cb` — "test(scoring-contract): drive the over-broad
projection case through the protocol path".

Mutation result: with the two `_assert_projection_is_not_vacuous` calls
inside `_assert_family_obeys_the_scoring_contract` commented out (via a
`/tmp` copy), this test failed ("DID NOT RAISE AssertionError"); restored
from the backup, suite green again (31/31).

### Second-pass final verification

```
../../.venv/bin/python -m pytest tests/test_shared_runner_schemas.py \
  tests/test_shared_runner_scoring_contract.py tests/test_shared_runner_smoke.py \
  -q -p no:cacheprovider
```

129 passed, 0 failed.

## Third pass

A third-pass review of the second pass's three commits (`cf85c02f`,
`177c9b9d`, `c1ecd6cb`) closed R1 (same-case controlled pair) and R3
(protocol-path over-broad test), accepted the finding-1 semantic residual
(R2(b)) as documented, and raised two corrections against R2(a) and against
`c1ecd6cb`'s own replacement test, dated 2026-09-05.

### C1 — the empty-trajectory guard (R2(a)) asserted a false necessity and guarded nothing

**FIXED by deliberate removal.** The guard added in `177c9b9d` (second-pass
R2(a)), inside `_assert_trajectory_outcome_paths_are_consistent`
(`tests/test_shared_runner_scoring_contract.py:1426`), asserted that a
declared trajectory sequence must be non-empty whenever `phase_instances`
replayed at least one transition. Two problems: it asserted an assumption
the specification does not make -- that one replayed transition implies at
least one trajectory record -- and could misfire on a family whose
per-round history is appended only when a round completes, with a fixture
ending mid-round. More decisively, it guarded nothing: under ruling R10, an
empty declared trajectory must equal an empty list read from the final
replayed state (the very next assertion already enforces exactly that), and
projecting an empty list away leaves the whole outcome in the projection
unchanged -- the paired-history check becomes the whole-outcome check,
which is STRONGER, not weaker. An empty embedded trajectory is therefore
not a hole. Removed the assertion and its unit test,
`test_r10_rejects_an_empty_embedded_trajectory_beside_a_non_empty_replay`;
every other assertion from `177c9b9d` is unchanged, including the R2(b)
structural-guard-residual documentation (kept, and its one now-inaccurate
cross-reference to "the non-empty check just below" corrected). This is a
deliberate deletion of a guard added earlier in this same branch, not a
weakening of any pre-existing coverage: no assertion that predates this
branch is touched.

Commit: `10c2abab` — "fix(scoring-contract): drop the empty-trajectory
guard; an empty path strengthens the projection".

Test removed: `test_r10_rejects_an_empty_embedded_trajectory_beside_a_non_empty_replay`.

Verification: full suite green both immediately before and immediately
after this commit (`tests/test_shared_runner_scoring_contract.py`: 31 before
removing the test, 30 after -- one test fewer, zero failures either side).

### C2 — `c1ecd6cb`'s protocol-path test lost the guard's per-fixture independence coverage

**FIXED by restoring the coverage as a separate unit test.** The test
`c1ecd6cb` replaced originally called `_assert_projection_is_not_vacuous`
directly on BOTH the left and the right fixture's (real, replayed)
projection, independently asserting each one raised. Its
protocol-path replacement,
`test_r9_projection_erases_the_entire_outcome_when_the_declared_path_is_over_broad`
(`tests/test_shared_runner_scoring_contract.py:2214`), drives both fixtures
through `_assert_family_obeys_the_scoring_contract`, which calls the guard
on the left fixture first: that call raises and aborts the function before
the right fixture's guard call is ever reached, so the protocol-path test
alone no longer demonstrates the guard rejecting the right fixture's
projection. Added a new, separate direct unit test,
`test_projection_is_not_vacuous_rejects_each_fixtures_projection_independently`
(`:2270`), over the SAME real over-broad fixture pair, calling
`_assert_projection_is_not_vacuous` on the left and right projections as two
independent assertions (alongside, not instead of, the protocol-path test).

Commit: `128bae53` — "test(scoring-contract): cover the vacuous-projection
guard on each fixture independently".

Test added: `test_projection_is_not_vacuous_rejects_each_fixtures_projection_independently`.

Mutation results:
- With `_assert_projection_is_not_vacuous`'s own assertion body replaced by
  `pass`, all three tests that exercise it
  (`test_projection_is_not_vacuous_rejects_a_projection_erased_to_an_empty_mapping`,
  `test_r9_projection_erases_the_entire_outcome_when_the_declared_path_is_over_broad`,
  and the new `test_projection_is_not_vacuous_rejects_each_fixtures_projection_independently`)
  failed with "DID NOT RAISE AssertionError"; restored from the `/tmp`
  backup, suite green again.
- Separately, reproducing the exact regression C2 describes -- removing
  ONLY the right-fixture `_assert_projection_is_not_vacuous` call inside
  `_assert_family_obeys_the_scoring_contract`, leaving the left-fixture call
  intact -- confirmed the motivating claim: the protocol-path test still
  passed (the left call alone still raises "vacuous", which is all that
  test checks), while the new direct unit test is unaffected by this
  protocol-helper-internal change either way, since it calls the guard
  function directly rather than through the protocol path -- exactly the
  independence C2 asked to restore. Restored from the `/tmp` backup, suite
  green again (129/129 combined).

### Third-pass final verification

```
../../.venv/bin/python -m pytest tests/test_shared_runner_schemas.py \
  tests/test_shared_runner_scoring_contract.py tests/test_shared_runner_smoke.py \
  -q -p no:cacheprovider
```

129 passed, 0 failed.
