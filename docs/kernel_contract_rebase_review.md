# Kernel contract rebase review

**Provenance.** The section below, delimited by `BEGIN REVIEW` / `END
REVIEW`, is reproduced verbatim from an independent review spanning two
sibling worktrees that fork from the same `main` commit (`9724e39`): Part 1
examines the exception-chain rewrite in `tests/test_shared_runner_execution.py`
on branch `zeyu/fix-cancellation-context-assertions` at commit `6a6720f`;
Part 2 examines the kernel scoring-contract's post-rebase trusted-family and
manifest-validation state on branch `zeyu/kernel-contract` at commit
`118bc76`. It was supplied to this document's author for verification, not
authored by that author.

The **Dispositions** section following it was added by the engineer who
verified every claim, including its file/line citations, directly against
the code in the worktree each claim actually describes, and recorded the
outcome per claim. `FINDINGS: 0` is the review's own conclusion; the
dispositions confirm that conclusion rather than introduce a new finding.

--- BEGIN REVIEW ---
## Part 1 — STRENGTHENED-BUT-VALID

- No weakness found. The rewritten helper walks both `__context__` and `__cause__`, preserves exception identity, and prevents cycles (`tests/test_shared_runner_execution.py:679-713`). The outer assertions still require `asyncio.CancelledError`, while the chain assertions require the exact injected bookkeeping object (`tests/test_shared_runner_execution.py:724-744` and `:841-861`). Thus both cancellation and bookkeeping failure must remain observable; only the CPython-dependent one-hop topology was removed.
- Reverting the snapshot-handler guard would still fail the first test: the reader raises the recorded `RuntimeError` (`tests/test_shared_runner_execution.py:628-636`); production currently catches it and re-raises the original cancellation while handling it (`src/aeread/shared_runner/task/execution.py:2980-3009`). Without that re-raise, the `RuntimeError` escapes and violates `pytest.raises(asyncio.CancelledError)` at `tests/test_shared_runner_execution.py:728`.
- Reverting the event-write guard would still fail the second test: the injected append failure raises the recorded `RuntimeError` (`tests/test_shared_runner_execution.py:789-799`); production currently catches it and raises `cancelled_error` (`src/aeread/shared_runner/task/execution.py:3151-3187`). Without that guard, the bookkeeping error escapes and violates the outer cancellation assertion at `tests/test_shared_runner_execution.py:845`.

## Part 2 — OK

- No trusted family was dropped. All eleven post-rebase adapter families are present in `TRUSTED_BUILTIN_PLUGIN_KEYS` (`src/aeread/shared_runner/registry.py:64-78`) and appear with the same `(family_id, version)` identities in `_NOT_YET_MIGRATED_TRUSTED_KEYS` (`tests/test_shared_runner_scoring_contract.py:1054-1081`).
- The closed-world path consumes the real trusted catalog, projects each trusted triple to `(family_id, version)`, then computes `trusted - enrolled - exempt` and asserts that the result is empty (`tests/test_shared_runner_scoring_contract.py:1036-1039` and `:1085-1106`). The production-catalog call passes the locally enrolled fixtures and the explicit exemption set (`tests/test_shared_runner_scoring_contract.py:1164-1186`). Therefore omitting any of the eleven exemptions would leave that family in `unenrolled` and fail; the current exact entries remove them intentionally rather than silently excluding them from the trusted catalog.
- No relevant validation guard or schema field was dropped: `MeasurementDeclaration` retains `leaves`, `primary_leaf_id`, and `admission_leaf_ids` plus their cross-field validation (`src/aeread/shared_runner/schemas.py:396-462`); registry admission still requires a validated `MeasurementDeclaration` (`src/aeread/shared_runner/registry.py:281-296`) and stores the validated manifest on the registration (`src/aeread/shared_runner/registry.py:329-338`).

FINDINGS: 0
--- END REVIEW ---

## Dispositions

Legend: **VERIFIED** = the claim's prose and every file/line citation it
makes were checked directly against the code and matched exactly, including
the line boundaries cited. **CROSS-WORKTREE NOTE** = an observation added
during verification, not a finding, to prevent a future reader from
mis-locating the cited code.

### Part 1, bullet 1 — chain-walking helper and assertion shape

**VERIFIED** against `zeyu/fix-cancellation-context-assertions` at `6a6720f`.
`grep -n` confirms `_exception_chain` starts at line 679 and its body (the
two `if error.__context__ ...` / `if error.__cause__ ...` appends) ends at
line 713, matching the cited range exactly. `test_snapshot_failure_during_cancellation_preserves_the_cancellation`'s
`with pytest.raises(asyncio.CancelledError) as captured:` is at line 728
(cited), and its `chain = list(_exception_chain(captured.value))` /
`assert any(error is failures["bookkeeping"] for error in chain)` pair falls
inside the cited `724-744` span. `test_unknown_event_write_failure_preserves_the_cancellation`'s
matching `with pytest.raises(asyncio.CancelledError) as captured:` is at
line 845 (cited), with its chain assertion inside the cited `841-861` span.
The helper does walk both `__context__` and `__cause__`, is cycle-protected
via an `id()`-keyed `seen` set, and yields the root exception itself before
any ancestor — so exception identity (`is`, not equality) is preserved
end-to-end.

### Part 1, bullet 2 — snapshot-handler guard

**VERIFIED** against the same commit. `_reader_failing_after_first_call`
(lines 628-636) raises and records the `RuntimeError` on its second call, as
cited. `src/aeread/shared_runner/task/execution.py:2980-3009` — byte-identical
in both the `zeyu/fix-cancellation-context-assertions` and
`zeyu/kernel-contract` worktrees, since neither branch touches
`ToolExecutor.invoke` — shows the `except BaseException as bookkeeping_error:`
block re-raising `original_error` after the nested `append_event` call,
letting Python's implicit chaining set `original_error.__context__ =
bookkeeping_error`. Removing that re-raise (mutation check performed by
copying the file to `/tmp`, deleting the final `raise original_error`, and
confirming `pytest tests/test_shared_runner_execution.py::test_snapshot_failure_in_failure_handler_preserves_the_original_tool_failure`
now fails with the bookkeeping `RuntimeError` escaping instead of the
expected `ToolFailure`, then restoring the file from the `/tmp` copy)
confirms the guard is load-bearing exactly as the review states.

### Part 1, bullet 3 — event-write guard

**VERIFIED** against the same commit. `_fail_append_for` (lines 789-799)
raises and records the `RuntimeError` on the targeted event type, as cited.
`src/aeread/shared_runner/task/execution.py:3151-3187` — also byte-identical
across both worktrees — shows the `except asyncio.CancelledError as
cancelled_error:` block's inner `except BaseException: raise
cancelled_error` after the failed `append_event` call. The same
mutation-check pattern (temporarily replacing `raise cancelled_error` with
a bare `raise` inside a `/tmp`-backed copy, confirming
`test_unknown_event_write_failure_preserves_the_cancellation` then raises
the bookkeeping `RuntimeError` instead of `asyncio.CancelledError`, then
restoring from the backup) confirms this guard is load-bearing exactly as
the review states.

### Part 1 — CROSS-WORKTREE NOTE

Part 1's `tests/test_shared_runner_execution.py` citations resolve
line-for-line only in the `zeyu/fix-cancellation-context-assertions`
worktree. `zeyu/kernel-contract`'s copy of that file does not yet contain
`_exception_chain`; its two cancellation tests still use the fixed-depth
`assert captured.value.__context__ is failures["bookkeeping"]` form the
sibling branch replaced. This is not a defect introduced by the
`zeyu/kernel-contract` rebase: both branches fork from the same `main`
commit (`9724e39`) as independent siblings, `zeyu/fix-cancellation-context-assertions`
has not merged to `main`, and nothing in the kernel-contract rebase touched
or was expected to touch this file. The project venv used for this repo's
own test runs is CPython 3.11.3, on which — per the sibling branch's own
direct interpreter testing (3.10.9 / 3.11.3 / 3.12.14) — the old fixed-depth
assertion already passes; the fragility the sibling branch fixed is 3.10-only
and does not manifest here. Recorded for traceability, not as a finding:
porting that fix into `zeyu/kernel-contract` is out of scope for this review
and was not requested.

### Part 2, bullet 1 — trusted-family parity

**VERIFIED** against `zeyu/kernel-contract` at `118bc76`. `sed -n
'64p;78p'` on `src/aeread/shared_runner/registry.py` shows line 64 opens
`TRUSTED_BUILTIN_PLUGIN_KEYS = frozenset(` and line 78 is the `termsbench`
entry, bracketing exactly the eleven adapter triples named in the review.
The same eleven `(family_id, version)` pairs appear in
`_NOT_YET_MIGRATED_TRUSTED_KEYS`, whose literal bounds (`sed -n
'1054p;1081p'` on `tests/test_shared_runner_scoring_contract.py`) match the
cited `1054-1081` range exactly. No family, and no `(family_id, version)`
pair, differs between the two sets.

### Part 2, bullet 2 — closed-world computation and production call

**VERIFIED.** `_trusted_family_versions` (opens line 1036, cited) projects
each trusted triple to `(family_id, version)`; `_assert_trusted_catalog_is_closed`
(opens line 1085, cited) computes `trusted - set(enrolled_family_versions) -
set(exempt_family_versions)` and asserts it is empty; both citations'
literal start/end lines (`1036/1039`, `1085/1106`) match exactly.
`test_every_registered_family_obeys_the_scoring_contract` (opens line 1164,
cited, closes at 1186) calls it with `enrolled_family_versions=set(fixtures)`
(the test's own local registry) and `exempt_family_versions=_NOT_YET_MIGRATED_TRUSTED_KEYS`.
Because the assertion is `trusted - enrolled - exempt == set()`, removing any
one of the eleven exemption entries would leave that family's key in
`unenrolled` and fail the test — confirmed by the set arithmetic, not merely
asserted.

### Part 2, bullet 3 — validation guards and schema fields intact

**VERIFIED.** `src/aeread/shared_runner/schemas.py:396-462` is
`MeasurementDeclaration`'s field block (`leaves`, `primary_leaf_id`,
`admission_leaf_ids`, cited at line 396) through the end of `__post_init__`'s
cross-field validation (`object.__setattr__(self, "admission_leaf_ids",
admission_leaf_ids)`, cited at line 462) — both line-exact. `src/aeread/shared_runner/registry.py:281-296`
is `_validate_plugin`'s `isinstance(manifest.measurement,
MeasurementDeclaration)` type guard (opens at the `@staticmethod` decorator
line 281, cited); `:329-338` is the `RegisteredPlugin(...)` construction
that stores `manifest=manifest` on the registration (cited), both
line-exact. No guard or field cited by the review has been removed,
weakened, or is missing from the range cited.

### Summary

0 findings confirmed as defects. 0 findings refuted as factually inaccurate.
1 cross-worktree scope note recorded (Part 1's citations describe the sibling
`zeyu/fix-cancellation-context-assertions` worktree, not `zeyu/kernel-contract`'s
current copy of the same file — expected, given the two branches are
independent siblings, and not something this review or its verification
asked to reconcile). No code change was made in either worktree as a result
of this review.
