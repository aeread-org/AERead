# termsbench scoring-contract migration — independent review

Provenance: this document records an independent review of branch
`zeyu/termsbench-contract-migration` (commits `0f5b99a7..ce15ab1f`, the five
commits of the regime-split + scoring-contract migration), conveyed to this
document's author verbatim via the coordinating agent's own message during
this task — not a separately-authored review file quoted from disk, since no
such file existed for this family before this entry.

## Review

The review covered seven items, lettered (a)–(g). Five were reported clean
outright; two required a fix. The reviewer's own message, reproduced
verbatim for the two actionable items:

--- BEGIN REVIEW (as conveyed) ---
Independent review of your five commits: (b) manifests, (c)
arithmetic/goldens, (e) enrollment, (f) retirement, (g) test strength are
clean. Two items to fix, same rules (test-first, mutation-verify, never
weaken, one commit each, no AI mention in git metadata):

F1 (blocker) — src/aeread_families/termsbench/environment.py ~218-227:
`register_plugin(registry, regime=..., plugin=...)` builds the manifest
from `regime` but binds the supplied `plugin` unchanged, so
`register_plugin(registry, regime="overlap", plugin=TermsBenchPlugin(regime="nodeal"))`
binds the overlap manifest to a nodeal validator/scorer, and a nodeal
payload is then accepted and emits the nodeal leaf set under the overlap
registration. Fix: require `plugin.regime == regime` (raise a named error
naming both), or drop plugin injection if nothing needs it (say which and
why). Tests: mismatched injection rejected; and an explicit cross-regime
rejection regression test — the overlap family's validate_payload rejects
a nodeal case and vice versa, through the registered plugin (not a
hand-built one). Mutation: remove the guard → the injection test fails.
Commit: "fix(termsbench): a registered plugin's regime must match its
manifest".

F2 (should-fix) — tests/test_termsbench_replay.py ~597-652: the nodeal
receipt test covers only a walk-away episode (FAGR− = 0.0). Add a
finalizer-path test for a No-deal case where the scripted agents DO reach
an agreement (the wrong outcome for that regime): the receipt must be
status "ok" / inclusion "included" with FAGR− = 1.0 as a legitimate
numeric value — never invalid_measurement or excluded — and the
manifest's declared direction for termsbench.nodeal must make that the
worse outcome (confirm and cite the direction field). Mutation: make the
scorer return invalid for an agreement → the test fails. Commit:
"test(termsbench): a false agreement in a no-deal case is a legitimate
FAGR− of 1.0 through the finalizer".
--- END REVIEW (as conveyed) ---

The five clean items were reported by letter without further detail beyond
their one-line dispositions above; by elimination, F1 and F2 are items (a)
and (d) of the seven (the only two letters, of a–g, not named clean).

## Items and dispositions

- **(a) — identity/registration binding. Disposition: confirmed and fixed
  (F1, blocker).** `register_plugin`'s `plugin=` injection path bound a
  caller-supplied plugin to `family_manifest(regime)` without checking that
  the plugin's own `regime` matched — verified by writing a failing test
  first (`test_register_plugin_rejects_a_plugin_whose_regime_does_not_match`,
  confirmed `DID NOT RAISE ValueError` against the pre-fix code), then fixed
  in `register_plugin` (an `elif plugin.regime != regime: raise ValueError`
  naming both regimes). `plugin=` injection itself is kept, not dropped: it
  is a widely-used convention across every other migrated family's own
  `register_plugin` signature (govsim, collusion, tau3_retail,
  agenticpay.bilateral, and others all support it), so removing it here
  would make termsbench's interface inconsistent with the rest of the
  codebase for no benefit — the guard closes the actual gap without
  narrowing the interface. Mutation-verified (cp to `/tmp`, edit, run,
  restore — never `git checkout`): removing the `elif` guard reproduces
  `DID NOT RAISE ValueError` on the mismatched-injection test; restored and
  re-verified green. Commit `58e5c3d2`.

- **(b) — manifests. Disposition: clean, no action.** Reported clean by the
  reviewer; matches this branch's own leaf-policy tables
  (`docs/termsbench_migration_plan.md`).

- **(c) — arithmetic/goldens. Disposition: clean, no action.** Reported
  clean by the reviewer; matches this branch's own R11 goldens section
  (`docs/termsbench_adapter_status.md`).

- **(d) — receipt test coverage. Disposition: confirmed and fixed (F2,
  should-fix).** The existing No-deal finalizer receipt test
  (`test_finalize_wires_termsbench_nodeal_to_the_shared_family_finalizer`)
  exercised only the walk-away branch of eq. 60 (`FAGR− = 0.0`); a defect in
  the OTHER real branch (a bound price in a No-deal geometry — a false
  agreement, `FAGR− = 1.0`) would have left every existing termsbench test
  green. Added
  `test_finalize_wires_termsbench_nodeal_false_agreement_as_a_legitimate_fagr_minus_one`,
  which drives a real episode (the scripted agent accepts the counterpart's
  own kernel-computed opening offer, never a hand-picked price) through
  `finalize_family_execution` and asserts `status="ok"`,
  `inclusion_status="included"`,
  `termsbench_no_deal_agreement_leaf.primary.value == 1.0`. Confirmed and
  cited both `family_manifest("nodeal").measurement.direction` and the
  leaf's own `estimand.direction`, both `"minimize"` — so `FAGR− == 1.0` is
  the worse value here (the maximum of the leaf's 0/1 range), mirroring
  AGR+'s `"maximize"` for Overlap. Mutation-verified (cp to `/tmp`, edit,
  run, restore — never `git checkout`): forcing
  `score_no_deal_agreement` to report `invalid_measurement` whenever a
  price is bound makes the new test fail (a `MeasurementContractError`, an
  even stronger signal than a plain assertion failure); restored and
  re-verified green, including the unaffected walk-away companion test.
  Commit `0ce54be9`.

- **(e) — enrollment. Disposition: clean, no action.** Reported clean by
  the reviewer; matches this branch's own protocol-test enrollment
  (`tests/test_shared_runner_scoring_contract.py`'s
  `_termsbench_overlap_fixtures`/`_termsbench_nodeal_fixtures`).

- **(f) — retirement. Disposition: clean, no action.** Reported clean by
  the reviewer; matches this branch's own retirement of the single
  `termsbench` identity (`docs/termsbench_adapter_status.md`'s "The retired
  identity").

- **(g) — test strength. Disposition: clean overall, one gap closed under
  (d).** Reported clean by the reviewer at the level of the five commits
  reviewed; the one concrete gap found (the missing false-agreement
  finalizer-path coverage) is recorded under (d) above, not here, since the
  reviewer's own message filed it as a distinct, separately-commit-worthy
  finding (F2) rather than a blanket test-strength failure.
