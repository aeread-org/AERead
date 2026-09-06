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
