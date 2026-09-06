Provenance: independent review of `zeyu/alympics-contract-migration` (diff-only, read-only against the branch tip).
Recorded verbatim below, followed by this branch's disposition of each finding after re-verifying it against the code.

--- BEGIN REVIEW ---
- **High — The migration invents `alex` as the evaluated subject.** `src/aeread_families/alympics_wac/measurement.py:108-121` explicitly admits that the case contains no focal seat, then chooses `SEAT_ORDER[0]`; `src/aeread_families/alympics_wac/measurement.py:1179-1190` consequently scores and constructs the baseline/reference for Alex on every call. Concrete failure: when Bob is the controlled/tested seat, the receipt's primary measurement is still Alex's terminal wealth. Bob's performance is measured only indirectly through its effect on Alex, so the primary no longer represents the evaluated subject. A migration cannot repair missing subject context by fabricating a fixed seat.

- **Medium — Score provenance is caller-controlled rather than copied from `FamilyScoringInput`.** `src/aeread_families/alympics_wac/measurement.py:1137-1139` accepts an independent `evidence_refs` argument defaulting to empty, and `src/aeread_families/alympics_wac/measurement.py:1191-1222` propagates that argument instead of `scoring_input.evidence_refs`. Calling `scorer(scoring_input)` where the input carries sealed references therefore emits four empty-reference leaves; passing unrelated references forges provenance. The receipt test would not detect the empty-reference mutation because `tests/test_alympics_wac_replay.py:1050-1051` checks only that all leaves agree, not that they equal the finalizer input's references.

- **High — Trusted-catalog closure can pass while AlyMpics' only protocol test skips.** `tests/test_shared_runner_scoring_contract.py:1710-1712` declares AlyMpics enrolled unconditionally, and `tests/test_shared_runner_scoring_contract.py:2053-2056` unions that declaration into closure without executing its fixture. The actual protocol test imports the replay module at `tests/test_shared_runner_scoring_contract.py:2145-2149`, whose module-level upstream check calls `pytest.skip(..., allow_module_level=True)` at `tests/test_alympics_wac_replay.py:74-85`. Concrete failure: on a normal checkout lacking the external AlyMpics tree, the shared closure test passes, the AlyMpics protocol test skips, and CI remains green without exercising its scorer, projection pair, leaf completeness, or finalizer path. An optional environment gate does not make default trusted enrollment behaviorally covered.

Review was diff-only and read-only; tests were not run.

FINDINGS: 3
--- END REVIEW ---

## Disposition (re-verified against code on this branch, tests run)

### Finding 1 (High — `alex` invented as evaluated subject): CONFIRMED, ESCALATED (owner decision)

Code evidence confirms the finding exactly as stated:

- `family_case` (the validated `payload`) never carries a `focal_seat` field. Confirmed
  by grepping `src/aeread_families/alympics_wac/cases.py` — no `focal_seat` key appears
  anywhere in the case/grid-cell schema.
- `measurement.py:108-121`'s own comment states this directly: "this family's
  `family_case` does not yet carry a `focal_seat` field at all ... has to pick ONE
  deterministic seat, and this is that declared convention: the first seat in
  `SEAT_ORDER`." `FOCAL_SEAT = SEAT_ORDER[0]` resolves to `"alex"`
  (`cases.py`'s `SEAT_ORDER = ("alex", "bob", "cindy", "david", "eric")`).
- `measurement.py:1179` (`AlympicsWacScorer.__call__`) reads `focal_seat = FOCAL_SEAT`
  unconditionally, then lines 1184-1222 score and construct the baseline for that fixed
  seat on every call, regardless of which seat a plan actually placed the tested model
  in.

This also surfaces a genuine tension in the frozen spec itself, reported rather than
silently resolved per the task's own instruction: ruling R12 states "Families whose
case itself names the tested seat (aucarena's roster, **alympics' focal seat**) are
unaffected [by R12's SeatContext machinery]: their primary is cell-scoped and they
ignore seat context." That premise is false for this family as it exists in the
codebase today — `alympics_wac`'s case does *not* name a focal seat — and the family's
own status doc (`docs/alympics_adapter_status.md`, "The focal-seat convention (a stated
limit, not an invented one)") already says so explicitly: "On this branch, that premise
does not hold." The spec's factual claim about this family is incorrect; this migration
did not invent the discrepancy but did have to decide how to behave given it, and it
chose to state a fixed, documented convention (`alex`) rather than guess a different
one per call.

**Why this is not mine to fix.** Correcting this requires one of: (a) extending the
`family_case`/grid-cell schema to carry a `focal_seat` (or similar) field so each case
names its own tested seat, or (b) wiring ruling R12's `SeatContext`
(`subject_seats`/`profile_by_seat`) through to `FamilyScoringInput` and defining this
family's `seat_scope`/`subject_reduction` policy. Either path changes what seat's data
the primary estimand (`alympics_wac_terminal_wealth`) is computed over for any case
where the tested seat is not `alex` — i.e., it redefines the estimand's inputs, not
merely its plumbing. Per the task's own carve-out, a fix that changes an estimand
definition is an owner decision, not a migration-agent fix. Recorded here as confirmed
and escalated, with the two code citations above as evidence, for the owner to choose
between (a) and (b) (or to accept the current stated-limit as-is for this family
version).

**Post-R12 note (2026-09-06): RESOLVED.** The owner's ruling adopted option (b) above.
`zeyu/kernel-r12-seat-context` (PR #109) implements ruling R12's `SeatContext`
machinery, and this branch (rebased onto it) wires it through:
`AlympicsWacScorer.__call__` now resolves its focal seat per call from
`scoring_input.seat_context.subject_seats` (`measurement.py`'s `_resolve_focal_seat`)
instead of the fixed `FOCAL_SEAT = SEAT_ORDER[0]` constant this finding names, which is
deleted. `family_manifest()` declares leaves 1-3 `seat_scope="subject_seat"`
(no `subject_reduction`: this family's cluster mapping is one focal seat per trial,
never several subject seats scored together). This also resolves the "genuine tension
in the frozen spec" this finding separately reported: R12's stated premise that
"alympics' focal seat" is a case that names its own tested seat was, in fact, false for
this family (as this finding itself demonstrated) — the family now genuinely reads the
tested seat from `SeatContext`, which is what R12's premise implicitly assumed a family
in this position would already be doing. Leaf identity itself (each leaf's
`MeasurementLeafSpec`) does not depend on which seat is resolved as the subject
(`AlympicsWacScorer.leaves_for_focal_seat`'s own docstring), which the scoring-contract
protocol test's cross-fixture "leaf's declared identity must be stable" check verifies
directly once fixtures naming different focal seats are compared side by side. This
note records the resolution; the finding and disposition text above are left as
originally recorded, not rewritten.

**Superseded (2026-09-06): the "Leaf identity itself... does not depend on which seat
is resolved as the subject" sentence above.** A second, independent review pass found
that specific mechanism itself workaround-shaped — see "Second review pass:
reference-provenance finding" at the end of this document for the full finding and its
resolution. The sentence is left in place above, not deleted or edited, per this
document's own policy (stated in the line immediately above it) of recording history,
not rewriting it; readers should treat it as superseded by that section.

### Finding 2 (Medium — score provenance caller-controlled): REFUTED

The code citations are accurate (`__call__`'s signature at 1137-1139, the four
`score_*` calls threading the `evidence_refs` parameter at 1191-1222), and it is true
that calling `scorer(scoring_input)` without the `evidence_refs` keyword yields four
empty-reference leaves. But this is the contract's mandated shape, not a defect:
`kernel_scoring_contract_spec.md` section 2 fixes `FamilyScorer.__call__`'s signature as
`(self, scoring_input, *, evidence_refs: tuple[str, ...] = ())` for every family, and
section 5 states the migrating agent decides nothing about provenance — "`evidence_refs`
is always `scoring_input.evidence_refs` verbatim" is a **finalizer** obligation, verified
independently of any one family's internals. The reference migration (govsim,
`src/aeread_families/govsim/measurement.py`) has the byte-identical signature and the
byte-identical propagation-not-rederivation pattern; alympics did not deviate from the
approved reference shape here.

More importantly, the specific risk the finding raises — "passing unrelated references
forges provenance" and no test would catch a leaf silently disagreeing with
`scoring_input.evidence_refs` — is independently checked at the **kernel** layer, not
left to family-level convention. `src/aeread/shared_runner/task/evaluation.py`'s
`_check_evidence_refs_are_scoring_input_verbatim` (docstring: "kernel_contract_impl_review.md
finding 13 ... nothing stops a scorer from fabricating a different one on the envelopes
it returns; catch that here") is called from `finalize_family_execution` on every family,
and the shared protocol test (`tests/test_shared_runner_scoring_contract.py`,
`_assert_family_obeys_the_scoring_contract`) independently asserts
`score.evidence_refs == scoring_input.evidence_refs` for every leaf of every registered
family, including alympics via `test_alympics_wac_obeys_the_scoring_contract`.

**Mutation check performed** (file restored byte-for-byte afterward via `cp` from a
`/tmp` backup, confirmed with `git diff` showing no residual change): changed the
`terminal_wealth` call inside `__call__` from `evidence_refs=evidence_refs` to a fixed,
well-formed but unrelated `evidence_refs=("evt.forged-unrelated-ref",)`. Result:

- `tests/test_shared_runner_scoring_contract.py::test_alympics_wac_obeys_the_scoring_contract`
  — FAILED (`AssertionError` on the `evidence_refs == scoring_input.evidence_refs` check).
- `tests/test_alympics_wac_replay.py::test_finalize_wires_alympics_wac_to_the_shared_family_finalizer`
  — FAILED, and for a stronger reason than a test assertion: the **production**
  finalizer itself raised `ValueError: family scorer returned evidence_refs that
  disagree with scoring_input.evidence_refs for leaves: ('alympics_wac_terminal_wealth_leaf',)`
  from `task/evaluation.py:615`, before a receipt could ever be sealed.

So the exact failure mode described ("forges provenance", "would not be detected") is
caught twice over — once by the kernel's own runtime guard (which would abort
finalization outright, not merely fail a test) and once by the shared protocol test —
independently of the narrower family-specific replay assertion the finding cites. The
finding examined only `tests/test_alympics_wac_replay.py:1050-1051` and did not check
the kernel finalizer or the shared contract test, both of which already close this gap.
Refuted; no code or test change made for this finding.

### Finding 3 (High — trusted-catalog closure can pass while AlyMpics' protocol test skips): REFUTED

The code citations are accurate: `_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS` (line ~1710)
does declare `("alympics.wac", "0.1.0")` enrolled for closure purposes without running
its fixture, `_assert_trusted_catalog_is_closed`'s call (line ~2053-2056) does union it
in, and `test_alympics_wac_obeys_the_scoring_contract`'s deferred import of
`tests.test_alympics_wac_replay` does propagate that module's own
`pytest.skip(..., allow_module_level=True)` as a per-test skip when the pinned upstream
checkout is absent. Confirmed directly:

```
$ AEREAD_ALYMPICS_UPSTREAM_ROOT=/tmp/does-not-exist-alympics \
  pytest tests/test_shared_runner_scoring_contract.py -k "alympics or every_registered"
test_every_registered_family_obeys_the_scoring_contract PASSED
test_alympics_wac_obeys_the_scoring_contract SKIPPED
1 passed, 1 skipped ... ; exit code 0
```

This reproduces the finding's exact scenario. But this is the project's established,
deliberate, already-precedented mitigation shape for every upstream-bridge-gated family
(tau2, tau3, and the reference migration govsim itself), not a gap this migration
introduced or could have avoided by deviating from the reference shape — the
`test_shared_runner_scoring_contract.py` comments say so directly: alympics's own
protocol test "mirror[s] govsim's identical shape,
`tests/test_govsim_replay.py`/`test_govsim_obeys_the_scoring_contract`". The
finding's "an optional environment gate does not make default trusted enrollment
behaviorally covered" is answered by what that gate actually does on a certifying run,
verified directly:

```
$ AEREAD_ALYMPICS_UPSTREAM_ROOT=/tmp/does-not-exist-alympics \
  AEREAD_ALYMPICS_UPSTREAM_REQUIRED=1 \
  pytest tests/test_shared_runner_scoring_contract.py -k "alympics or every_registered"
test_every_registered_family_obeys_the_scoring_contract PASSED
test_alympics_wac_obeys_the_scoring_contract SKIPPED
=== upstream required: alympics.wac ===
1 Alympics (alympics.wac adapter) upstream-fidelity test(s) skipped while
$AEREAD_ALYMPICS_UPSTREAM_REQUIRED is set. ...
exit code 1
```

The gate is opt-in for local/no-bridge development runs by design (so a contributor
without the pinned upstream checkout is never blocked) and is exported for every
certifying/full-suite run, which is exactly the operating protocol this migration is
run under. This is the same pre-existing pattern already used for tau2/tau3
("predating this migration," per the test file's own docstring) generalized to a third
family, not a new or alympics-specific hole. Refuted; no code or test change made for
this finding.

## Summary

| Finding | Disposition |
|---|---|
| 1 — `alex` invented as evaluated subject | Confirmed, escalated (owner decision: extend case schema with a focal-seat field, or wire ruling R12's `SeatContext`; either redefines the primary estimand's inputs) |
| 2 — score provenance caller-controlled | Refuted (matches reference shape verbatim; independently guarded by the kernel finalizer's `_check_evidence_refs_are_scoring_input_verbatim` and by the shared protocol test's evidence-identity assertion; mutation check against the real code confirmed both catch it) |
| 3 — trusted-catalog closure vs. skipping protocol test | Refuted (deliberate, precedented mitigation shared with tau2/tau3/govsim; `AEREAD_ALYMPICS_UPSTREAM_REQUIRED=1` converts the described scenario into a hard failure, verified directly; this is the certifying-run protocol this migration operates under) |

Fixed: 0. Refuted: 2. Escalated: 1.

## Second review pass: reference-provenance finding (2026-09-06)

Provenance: a second, independent review pass over this branch after the Post-R12 note
above landed, distinct from the "--- BEGIN REVIEW ---"/"--- END REVIEW ---" verbatim
text at the top of this document (which remains a record of the FIRST review pass only,
unedited). This section is appended, not merged into the disposition/summary above, per
this document's own stated policy of recording findings, not rewriting them.

**Finding.** Ruling R12 introduced `seat_scope="subject_seat"` leaves without
reconciling them against a pre-existing kernel check (PR #103, `kernel_contract_gap_
review.md` finding 7): the scoring-contract protocol test's `_assert_family_obeys_the_
scoring_contract` compares the FULL `MeasurementLeafSpec` across every fixture for the
same `leaf_id`, which is correct for a leaf's invariant declaration but contradicts a
per-seat leaf whose reference legitimately depends on which seat is the subject. This
branch's own migration hit exactly that contradiction (the Post-R12 note above's now-
superseded claim) and worked around it by dropping `focal_seat` from `_opponent_panel_
sha256`'s hash payload (`measurement.py`) so leaves 1/2 (terminal_wealth, survival)
would hash identically no matter which seat later became the subject. That made two
MATERIALLY DIFFERENT baselines — the SAME case recomputed with a DIFFERENT seat's
policy replaced (`_recompute_baseline_episode`'s `policy_assignment[focal_seat] =
baseline_policy_id`) — collide on one `source_sha256`: false provenance, not a
cosmetic gap, and the workaround's own docstring said as much (it named satisfying the
protocol test as the reason for dropping `focal_seat`, not any property of the
underlying claim).

**Disposition — fixed, on both branches.**

1. `zeyu/kernel-r12-seat-context` (PR #109), commit `7542947c`
   ("fix(scoring-contract): a per-seat leaf may instantiate its reference identity per
   subject seat"): the kernel's stability check is reconciled with ruling R12. A
   `seat_scope="subject_seat"` leaf may now instantiate its `ReferenceSpec`'s own
   identity — `reference_id`/`source_sha256`, and ONLY those two fields — per subject
   seat; every other field (estimand, verifier, the rest of the reference, scorer ref)
   remains invariant across every fixture, exactly as before. Two fixtures sharing the
   SAME subject seat must still be byte-identical (closing the hole a scorer whose
   reference merely drifts from call to call would otherwise open). See
   `docs/kernel_r12_seat_context.md`'s "The stability check predates R12 and was never
   reconciled with it" section for the full rule, its four tests, and their mutation
   results.
2. `zeyu/alympics-contract-migration` (PR #110), rebased onto (1), commit `16104c20`
   ("fix(alympics): restore the focal seat to the reference provenance digest"): the
   workaround is reverted. `_opponent_panel_sha256`
   takes `focal_seat` again and includes it in its hash payload;
   `AlympicsWacScorer.leaves_for_focal_seat` again passes `panel_policy_ids(focal_seat)`
   (every OTHER seat's own policy) to `build_leaves`, not the case's full assignment;
   the now-dead `full_policy_assignment` helper is removed. Every other improvement from
   the R12 migration (the seat-context focal resolution, the typed invalid reasons,
   `utility_by_seat`, the different-focal-seat fixture in
   `tests/test_shared_runner_scoring_contract.py`) is unchanged.

**Tests** (`tests/test_alympics_wac_measurement.py`), three:

1. `test_leaves_for_focal_seat_reference_identity_depends_on_the_focal_seat` replaces
   the previous (now-incorrect) `test_leaves_for_focal_seat_identity_does_not_depend_
   on_which_seat_is_focal`: for one case (`mixed_policies_a`), leaves 1/2 built for two
   DIFFERENT focal seats differ in `source_sha256` and agree on every invariant field;
   leaves 3/4 stay byte-identical regardless of focal seat; the SAME focal seat called
   twice is byte-identical.
2. `test_focal_seat_is_part_of_the_leaf_1_2_reference_identity_even_for_an_identical_
   panel`: calls `build_terminal_wealth_leaf`/`build_survival_leaf` directly with the
   IDENTICAL `panel_policy_ids` for two DIFFERENT `focal_seat` values, isolating
   `_opponent_panel_sha256`'s own `focal_seat` parameter from `leaves_for_focal_seat`'s
   separate choice of panel (see test 3) — `panel_policy_ids(focal_seat)`'s own key set
   already differs by focal seat for any case with more than one seat, which would
   otherwise mask a regression in `_opponent_panel_sha256` itself.
3. `test_leaves_for_focal_seat_builds_leaf_1_2_identity_from_the_opponent_panel_not_the_
   full_assignment`: asserts `leaves_for_focal_seat`'s output EQUALS
   `build_terminal_wealth_leaf`/`build_survival_leaf` called directly with
   `panel_policy_ids(focal_seat)` — by equality, not a hash inequality across focal
   seats, since test 2's own fix would mask a regression in THIS half if checked by
   inequality alone.

`tests/test_shared_runner_scoring_contract.py::test_alympics_wac_obeys_the_scoring_
contract` — unchanged, still enrolling `different_focal_seat` (subject "bob") alongside
`left` (subject "alex") on the identical sealed evidence — continues to pass, now
because the kernel's corrected rule accepts the genuinely-differing reference identity,
not because of the reverted workaround.

**Item 3 (a related, narrower observation from the same review pass): the digest omits
`seat_order`/`personas`/`supply_schedule`/`grid_cell["rounds"]`.** Confirmed
PRE-EXISTING (present in the pre-workaround version of `_opponent_panel_sha256` at
`zeyu/kernel-r12-seat-context:src/aeread_families/alympics_wac/measurement.py`, which
predates this migration branch entirely) — not introduced or worsened by the workaround
or its reversion, so left as a stated limit rather than silently fixed. Recorded in
`docs/alympics_adapter_status.md`'s "Reference-provenance finding" section, with the
exact collision scenario and why `EvaluationReceipt.case_id`/`case_sha256` already
disambiguate it in practice.

**Mutation** (two independent mutations, each isolating one half of the fix, `/tmp`
copy of `measurement.py`, restored — never `git checkout` on the file holding
uncommitted work):

- Dropping `focal_seat` from `_opponent_panel_sha256`'s payload again (leaving
  `leaves_for_focal_seat` correct) makes test 2 fail on its `source_sha256 != `
  assertion, and correctly does NOT fail test 1 — confirming test 1 alone would have
  missed this specific regression, since `panel_policy_ids(focal_seat)`'s own key set
  already differs by focal seat independent of whether `_opponent_panel_sha256` also
  embeds it.
- Reverting `leaves_for_focal_seat` to pass the case's full policy assignment again
  (leaving `_opponent_panel_sha256` correct) makes test 3 fail on its equality
  assertion, and correctly does NOT fail tests 1/2 — confirming `_opponent_panel_
  sha256`'s own `focal_seat` parameter alone would have masked THIS regression from a
  hash-inequality check.

On the kernel side, see `docs/kernel_r12_seat_context.md`'s own mutation results for
the four tests covering the stability rule itself.
