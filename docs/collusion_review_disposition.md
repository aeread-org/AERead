# collusion adapter — review disposition

Reviews consulted: `docs/collusion_review_claude.md` (present).
`docs/collusion_review_codex.md` does not exist in this worktree — handled
gracefully, no codex findings to disposition.

Each finding below was independently re-verified against the code (not just
re-read from the review) before any fix was applied.

## CRITICAL 1 — `_extract_price_from_text` silently fabricates a wrong price
for scientific-notation numbers instead of failing the malformed gate

**Disposition: fixed.**

Verified directly: `_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")`
(`src/aeread_families/collusion/environment.py`, pre-fix) has no exponent
support, so `_extract_price_from_text("The best response price is
1.92e+00 dollars.")` returned `0.0` (not `1.92`) and
`_extract_price_from_text("price = 2.5e-3")` returned `-3.0` (not
`0.0025`) — reproduced both exactly as the review states, including the
`-3.0` case's legality-flipping potential (a negative price should be a
`price_out_of_bounds` violation, while the true `0.0025` would have been
legal).

Fix: `_NUMBER_RE` now includes an optional `(?:[eE][-+]?\d+)?` exponent
group, so a scientific-notation number is captured as one token instead of
being split into two independent decimal matches. Added a code comment at
`_NUMBER_RE`'s definition explaining why the exponent group is load-bearing.

Tests added (`tests/test_collusion_environment.py`):
`test_price_parsed_from_scientific_notation_prose_is_not_truncated` drives
the exact review repro string through the real `run_episode` scheduler path
and asserts the parsed price is `1.92`, not `0.0`.

## MAJOR 2 — `collusion_long_run_profit`'s comparator reference
(`baseline_profit_by_seat`) is unvalidated, and the spec cites a
`payload.opponent_policy_id` field that does not exist

**Disposition: fixed** (structural validation + spec/code alignment; the
deeper cross-cell/opponent *provenance* gap is a stated limit, not closed).

Verified: `grep -rn "opponent_policy_id" src/ tests/ docs/` showed the
field appears only in `docs/collusion_adapter_spec.md`'s prose and in
`measurement.py`'s own "documented deviation" docstring comment — no
`CaseManifest.payload` field of that name exists, and `_PAYLOAD_FIELDS`
(`environment.py`) never declares or validates one. Also verified
`score_long_run_profit` performed zero validation on the caller-supplied
`baseline_profit_by_seat` beyond `is None`: a missing seat key would raise
an uncaught `KeyError`, and a non-finite value (`NaN`/`inf`) would silently
propagate into the reported profit delta instead of a typed
`invalid_measurement` — a real gap, distinct class from the module's own
stated non-fabrication rule for every other leaf.

What was **not** fixed, and why: the review's specific failure scenario
(an eval harness accidentally handing the `alpha=1` cell's baseline to an
`alpha=10` agent trajectory) requires cross-cell/opponent *provenance*
tracking that no data in this leaf's signature carries — the baseline
arrives as bare floats with no case-identity token attached. Closing that
fully would require either adding a new `CaseManifest.payload` field (which
would re-digest the already-committed milestone-1 corpus's
`content_sha256` for no behavior change to the 6 committed pilot cells) or
threading a separate identity argument through a caller that does not exist
yet (no live-agent harness is wired to this leaf in this milestone). This
is an architectural decision belonging to whichever future milestone builds
that harness, not a silent guess to make here.

Fix: added `_malformed_baseline_reason` (`measurement.py`), structurally
validating `baseline_profit_by_seat` (exact `{"firm_a", "firm_b"}` keys,
finite numeric values); `score_long_run_profit` now reports
`invalid_measurement` with a typed reason
(`baseline_profit_not_a_mapping` / `baseline_profit_missing_or_unexpected_seat`
/ `baseline_profit_not_a_finite_number`) instead of crashing or silently
propagating a bad number. Updated both `measurement.py`'s docstring and
`docs/collusion_adapter_spec.md` §2 (leaf 4) and §6 (stated limits) to
remove the false `payload.opponent_policy_id` citation and state the
provenance-trust limit explicitly instead of only in a code comment.

Tests added (`tests/test_collusion_measurement.py`):
`test_score_long_run_profit_rejects_a_baseline_missing_a_seat`,
`test_score_long_run_profit_rejects_a_baseline_with_a_non_finite_value`,
`test_score_long_run_profit_rejects_a_non_mapping_baseline` — all reuse the
module-scoped `shared_nash_result` fixture rather than running a new
300-round episode each.

## MAJOR 3 — A legality violation on one seat is silently swallowed if the
other seat's response is malformed in the same round

**Disposition: fixed.**

Verified directly (matching the review's own repro): built a case where
`firm_a` submits a price 3x over ceiling (genuine `price_out_of_bounds`)
while `firm_b`'s response is unparseable text, both in the same round.
Pre-fix, `step()`'s `malformed = any(not actions[seat].parse.ok for seat in
_SEATS)` looked across *both* seats, so the round's termination reason
became `retry_exhausted` even though `firm_a` committed a real,
independently-checkable ceiling breach. `score_price_legality` then gates
on `termination_reason in OPERATIONAL_FAILURE_REASONS`, so the whole
episode reported `invalid_measurement` for every leaf — `firm_a`'s
violation was fully recorded in the raw `history[-1]["invalid_reasons"]`
dict but never surfaced through any `ScoreEnvelope`. Confirmed no existing
test exercised this combined-invalid case, matching the review's own
statement.

Fix: `step()` (`environment.py`) now computes
`legality_violation_seats` — seats whose action parsed successfully but
failed `legal()` — and only falls back to `retry_exhausted` when that list
is empty; a genuine, well-formed legality violation on either seat now
takes priority over a co-occurring parse failure on the other, since
`retry_exhausted` is meant for rounds where no legality data exists at all
to check (consistent with `score_price_legality`'s own docstring). Added a
code comment at the branch explaining the priority rule and citing the
review.

Tests added:
`tests/test_collusion_environment.py::test_combined_legality_violation_and_malformed_response_reports_legality_violation`
asserts `step()`'s own terminal reason and `invalid_reasons` dict for the
mixed round;
`tests/test_collusion_measurement.py::test_combined_legality_violation_and_malformed_response_still_surfaces_the_violation`
drives the same scenario through the real scorer and confirms
`collusion_price_legality` now reports `status="ok"`, `primary.value ==
0.0`, and the violation-round metadata, instead of `invalid_measurement`.

## MINOR 4 — Case-catalog READMEs are stale relative to the actual
milestone state

**Disposition: fixed** (documentation only, no behavior change).

Verified: `cases/README.md`'s table row said "environment pilot (cases +
environment only)... scorer lands in a later milestone", and
`cases/collusion/README.md` said "This milestone ships cases and the
environment plugin... only; the three declared measurement leaves are a
later milestone" — both contradicted `docs/collusion_adapter_status.md`
(same branch, 6 commits ahead of `origin/main` at review time), which
states milestones 1–3 are all complete (scorer, harness, replay, and all
five goldens already exist and pass).

Fix: updated both READMEs to state that milestones 1–3 have landed
(cases, environment plugin, four measurement leaves, scripted-policy
harness, offline replay), while preserving the "no live-agent run exists
yet" caveat from `docs/collusion_adapter_status.md`. No test added:
documentation-only change with no reachable behavior to regress.

## MINOR 5 — `docs/collusion_adapter_spec.md`/`docs/collusion_adapter_status.md`
cite `ledger_entries/collusion.md` as if it has checkable content, but it
does not exist anywhere in this repository's git history

**Disposition: refuted.**

Verified directly: `ledger_entries/collusion.md` **does exist** at
`/Users/sunzeyu/Documents/econ benchmark/ledger_entries/collusion.md` (a
workspace-level directory *sibling to*, not inside, the `AERead` git
repository — the same location this session's own task instructions
designate for defect entries, and the same location every other family's
ledger file lives: `ledger_entries/{agenticpay,alympics,amazonbarg,
aucarena,econagent,econevals,govsim,negarena,steer}.md` all sit alongside
it). It was already populated (three entries: the `D-10`
`docs/operations/benchmark_qc.md` corroboration, a `verifier_taxonomy.md` §11 drift
note, and an O(n²) scheduler-cost measurement) *before* the review was
written (file mtime 10:30 vs. the review's own 11:10 write time on the same
day), with real, checkable content matching exactly what the spec and
status doc cite.

The review's `git log --all --diff-filter=A --name-only | grep
ledger_entries` check is correct as far as it goes — this file is
deliberately **not** tracked inside the `AERead` git repository, by the
same cross-family convention every other adapter in this program already
follows — but the conclusion drawn from it ("a reviewer... has nothing to
check it against") does not hold once the workspace-level location (rather
than only the git tree) is checked. No fix applied; no ledger entry
duplicated, since the cited file and its content are exactly as the spec
claims.

## MINOR 6 — `ceiling_multiplier`'s cross-version determinism is asserted
more strongly than the stdlib actually guarantees

**Disposition: fixed** (documentation only, no behavior change).

Verified: `cases.py`'s docstring for `ceiling_multiplier` stated
`random.Random(seed).uniform(...)` is "a stable, documented part of the
stdlib" — CPython's Mersenne Twister has been practically stable for a
long time, but this is a convention, not a documented cross-version/
cross-implementation contract, exactly as the review states. Low practical
risk (self-defending: `test_committed_corpus_on_disk_matches_the_builder`
would catch a divergence immediately on a different interpreter).

Fix: reworded the docstring to state the weaker, accurate claim
("practically stable... not a documented cross-version/cross-
implementation contract") and to point at the self-defending test by name.
No test added: this is a comment-only change, and the existing corpus
regression test already covers the risk the review itself identifies as
low.

## Summary

| # | Severity | Disposition |
|---|---|---|
| 1 | CRITICAL | fixed |
| 2 | MAJOR | fixed (partial — provenance gap is a stated limit) |
| 3 | MAJOR | fixed |
| 4 | MINOR | fixed (doc-only) |
| 5 | MINOR | refuted |
| 6 | MINOR | fixed (doc-only) |

Fixed: 5 (findings 1, 2, 3, 4, 6). Refuted: 1 (finding 5). Deferred: 0.

Re-ran after all fixes: family test files (`tests/test_collusion_cases.py`,
`tests/test_collusion_environment.py`, `tests/test_collusion_measurement.py`,
`tests/test_collusion_harness.py`, `tests/test_collusion_replay.py`) plus
`tests/test_shared_runner_smoke.py` — 83 passed, 0 failed: 73 in the five
family files (67 pre-fix per the review's own count, plus 6 new regression
tests — 2 in `test_collusion_environment.py`, 4 in
`test_collusion_measurement.py`) and 10 in the smoke suite.

## Second-review findings (`docs/collusion_codex_triage.md`, codex second
reviewer, 6 findings: 4 CONFIRMED, 1 KERNEL, 1 REFUTED)

A second, independent adversarial pass over the same adapter, after the fixes
above had already landed. Each CONFIRMED finding below was re-verified directly
against the code (not taken from the triage's own prose) before any fix, and
each fix's regression test was first run against the pre-fix code and confirmed
to fail for the stated reason (a temporary `/tmp` backup + restore, never a git
checkout of the file under active edit).

### Finding 1 — Retry exhaustion occurs outside the family hook

**Disposition: deferred to the runner ledger (KERNEL).** `src/aeread/shared_runner/`
was not modified, per this fix pass's own scope rule. Re-verified: the scheduler's
`response_source(request)` call site (`scheduler.py:516`) invokes the response
source exactly once, with no retry loop anywhere in the decision-request path —
`collusion`'s own `environment.py:step()` already documents (in a code comment)
that it treats any parse failure as pre-exhausted, on the assumption that a
multi-attempt retry happens upstream, in a harness/response_source layer the
shared runner does not provide today. Recorded as
`runner_defect_ledger.md`'s **D-17** (MAJOR), "surfaced by: collusion".

### Finding 2 — Profit baseline uses the wrong opponent condition

**Disposition: fixed.** Re-verified: `tests/test_collusion_replay.py`'s
byte-identical-reproduction test (`shared_asymmetric_original`: firm_a plays
persistent monopoly-play, firm_b plays tit-for-tat) supplied
`baseline_profit_by_seat = dict(gold["pi_nash"])` — Nash-vs-Nash profit — even
though the live trajectory's opponent condition is not Nash for either seat.
Computed the economically correct baseline directly (re-running the real
scheduler/harness twice, once per seat, each time swapping only that seat's
policy to the named Nash-play baseline while keeping the *other* seat's real
policy function): `firm_a` playing Nash against firm_b's real tit-for-tat nets
16.24/round-mean vs. the wrong baseline's 93.69 (`pi_nash` at this cell's
`alpha=10`); `firm_b` playing Nash against firm_a's real persistent
monopoly-play nets 827.15 vs. the same wrong 93.69 — confirming the finding's
own failure scenario is real and large, not merely theoretical, for both seats.

Fix: added `_profit_report_window_mean` and the module-scoped fixture
`shared_asymmetric_same_opponent_baseline_profit` (`tests/test_collusion_replay.py`),
which computes the correct baseline through the real production path
(`run_episode` + `ScriptedCollusionHarness`, not an approximation); switched
the byte-identical-reproduction test to use it instead of `gold["pi_nash"]`,
with an inline pinning assertion that the two values differ materially (so a
future revert back to the wrong baseline fails loudly). `measurement.py`'s own
`score_long_run_profit` was intentionally left unchanged: it already
structurally validates the baseline's shape and (by design, per its own
docstring and the spec's stated limits) trusts the caller for provenance — no
data in this leaf's signature carries which opponent condition a caller
computed a baseline under, and inventing one is the same architectural
decision the first review round already declined to make unilaterally.

Tests added (`tests/test_collusion_replay.py`):
`test_same_opponent_condition_baseline_differs_from_nash_vs_nash_pi_nash_for_an_asymmetric_opponent`
(the standalone proof, run through the real harness);
`test_replay_and_verify_reproduces_state_and_score_byte_identically_with_zero_provider_calls`
(updated in place, with its own pinning assertion) — both fail against the
pre-fix baseline value.

### Finding 3 — Unverified offline replay reports `match`

**Disposition: fixed.** Re-verified: `ReplayReport.status` (`replay.py`)
returned `"mismatch"` only when a non-`None` `comparison` disagreed; with
`comparison is None` (a genuinely offline replay, no `original` in memory) it
always returned `"match"`, including for a tampered recording, exactly as the
finding's own cited test (`test_replay_without_an_original_reports_no_
comparison_but_still_scores`) demonstrated.

Fix: `record_episode` now seals the original run's own terminal outcome as
`RecordedEpisode.expected_final_outcome_sha256` at record time;
`replay_and_verify` always compares the freshly replayed outcome's digest
against that seal (a new `ReplayReport.digest_verified` field) regardless of
whether `comparison` is available, and `status` now reports `"mismatch"`
whenever `digest_verified` is `False` — so an offline replay of a tampered
recording is caught even with nothing live to compare against. The finding's
own instruction to exercise the production path, not a shortcut, is followed:
the regression test tampers a recording and drives it through the real
`replay_and_verify` entry point (not the raw `compare_episode_results` helper
the pre-existing tamper-detection test uses when `original` *is* available).

Test added (`tests/test_collusion_replay.py`):
`test_offline_replay_of_a_tampered_recording_with_no_original_in_memory_reports_mismatch_not_a_fabricated_match`
— fails pre-fix (`report.status == "match"` for a tampered recording), passes
post-fix. The pre-existing
`test_replay_without_an_original_reports_no_comparison_but_still_scores` needed
no assertion change (an untampered offline replay is still correctly `"match"`)
beyond adding `assert report.digest_verified is True`.

### Finding 4 — Replay identity is bound only to case ID

**Disposition: fixed.** Re-verified: `replay_episode` rejected a recording only
when `recorded.case_id != case.case_id`; a case whose `case_id` is unchanged
but whose economics content changed (a recomputed, still-valid manifest
digest) would pass this check and replay old decisions against the wrong
demand/cost parameters.

Fix: `RecordedEpisode` gained a `case_content_sha256` field, populated by
`record_episode` from `CaseManifest.content_sha256` (not just `case_id`);
`replay_episode` now rejects a mismatch on either field. `record_episode`'s
signature changed to `record_episode(result, *, case)` (was `record_episode(result)`)
to source this digest — every call site in `tests/test_collusion_replay.py`
updated accordingly.

Test added (`tests/test_collusion_replay.py`):
`test_replay_case_content_mismatch_raises_a_typed_replay_error_even_with_a_matching_case_id`
— a case_id-matching but stale `case_content_sha256` on the recording; fails
pre-fix (no such check existed), passes post-fix.

### Finding 5 — Distance leaves discard per-round gaps

**Disposition: fixed.** Re-verified: `_score_distance` (`measurement.py`)
computed only a seat-mean absolute gap, then averaged across seats into the
primary value; no per-round gap sequence was retained anywhere in the
envelope. Confirmed the finding's own concrete scenario: a trajectory
oscillating between `p_nash`/`p_monopoly` and a trajectory constant at their
midpoint produce byte-identical primary values under the pre-fix code, with
no way to tell them apart from the `ScoreEnvelope` alone.

Fix: `_score_distance` now attaches the raw, signed, per-round gap (price
minus target, keyed by round, for both seats) to `primary.metadata["per_round_gap"]`
— `MetricValue.metadata` is the schema's own sanctioned free-form field
(`Mapping[str, Any]`, already used elsewhere in this family for auxiliary
detail), so this required no change to `src/aeread/shared_runner/`. The
averaged primary computation itself is unchanged (spec doesn't ask for a
different aggregate, only for the raw detail alongside it).

Tests added (`tests/test_collusion_measurement.py`, plus a new `_short_case`
helper mirroring `test_collusion_replay.py`'s own convention for a cheap
real-scheduler episode):
`test_distance_leaf_retains_the_raw_signed_per_round_gap_not_just_the_averaged_primary`,
`test_distance_leaf_gap_metadata_distinguishes_oscillating_from_midpoint_trajectories_sharing_one_primary_value`
(the finding's own scenario, reproduced and asserted distinguishable) — both
fail pre-fix with `KeyError: 'per_round_gap'`.

### Finding 6 — Scientific notation parsing has been corrected

**Disposition: refuted, untouched.** Already fixed in the first review round
(this doc's own "CRITICAL 1", above) and independently re-verified again this
pass: `_NUMBER_RE` includes the optional exponent group, and
`test_price_parsed_from_scientific_notation_prose_is_not_truncated` still
covers it. No code or test change made for this finding.

### Summary

| # | Classification | Disposition |
|---|---|---|
| 1 | KERNEL | deferred — `runner_defect_ledger.md` D-17 |
| 2 | CONFIRMED | fixed |
| 3 | CONFIRMED | fixed |
| 4 | CONFIRMED | fixed |
| 5 | CONFIRMED | fixed |
| 6 | REFUTED | refuted (already fixed pre-existing) |

Re-ran after all second-review fixes: the same five family test files plus
`tests/test_shared_runner_smoke.py` — **88 passed, 0 failed** (83 pre-this-pass
plus 5 new regression tests: 2 in `test_collusion_measurement.py`, 3 in
`test_collusion_replay.py`).

## Verification follow-up (independent cross-model check,
`docs/collusion_fix_verification.md`)

A third, independent pass re-checked whether the two above CONFIRMED
findings this doc's second-review section labels "fixed" (Finding 2, Finding
4) were genuinely closed, rather than re-reading this doc's own prose. It
found both incomplete as of the commit it inspected (`7a4a5a7`) and flagged
one untracked file. This section corrects the record for both findings and
notes where the previous "fixed" label was accurate only in part.

### Finding 4 — now genuinely closed

The verifier's specific complaint: `case_content_sha256` binds a recording
to the case's *content*, but nothing bound it to *which run cell*
(`PlanCell.cell_id`) produced it — "no test exercises replay under a
different compatible cell." This was closed in commit `68bdc46` (landed
after the verifier's pass, recovered from a machine-sleep interruption and
independently re-verified this pass, not re-taken on faith): `RecordedEpisode`
gained a `cell_id` field, populated by `record_episode`'s now-required
`cell` keyword argument; `replay_episode` rejects a `cell_id` mismatch even
when both case checks pass.

Test added (`tests/test_collusion_replay.py`):
`test_replay_cell_identity_mismatch_raises_a_typed_replay_error_even_with_matching_case_content`
— records under one cell, replays under a second, `cell_id`-distinct
`PlanCell` for the same case, and asserts `ReplayError` naming the cell
mismatch.

**Mutation-verified this pass**: backed up `replay.py` to `/tmp`, deleted
just the `if recorded.cell_id != cell.cell_id: raise ReplayError(...)`
guard (leaving the field itself and both case-identity checks intact), and
re-ran the new test in isolation. It failed with `Failed: DID NOT RAISE
ReplayError` — the right reason, not a collateral error — confirming the
guard is load-bearing. Restored `replay.py` from the `/tmp` backup (never
`git checkout`), confirmed `git status`/`git diff` clean against the
committed state, and re-ran the full family suite green (below).
**Disposition: fixed**, superseding the second-review table's "fixed" label
above with an actual regression test for the specific gap the verifier
named.

### Finding 2 — narrowed, not fixed in production this pass

The verifier's specific complaint:
`test_same_opponent_condition_baseline_differs_from_nash_vs_nash_pi_nash_for_an_asymmetric_opponent`
"only proves the values differ; it would pass with production unchanged,"
and "the updated replay test guards its own fixture, not production
behavior." This is correct, and re-verified directly this pass:
`score_long_run_profit` (`measurement.py`) validates `baseline_profit_by_seat`'s
*shape* (exact seat keys, finite numbers) but has no way to validate its
*provenance* — nothing in this leaf's signature carries which opponent
condition, cell, or horizon a caller computed a baseline under, so a caller
that mistakenly passed `gold_reference["pi_nash"]` (Nash-vs-Nash) for an
asymmetric-opponent trajectory would still be accepted today and would
still silently publish a wrong delta.

This pass deliberately did **not** add production validation for this,
for the same reason the second-review section above already gives in its
own "Fix" paragraph: doing so requires either a new `CaseManifest.payload`
field naming the opponent condition (re-digesting the already-committed
milestone-1 corpus's `content_sha256` for the six pilot cells) or having
the scorer independently recompute the baseline from the recorded
trajectory instead of trusting the caller's number at all (a materially
different leaf-4 contract: no longer "caller-supplied", but "internally
derived"). Both are real architecture decisions already explicitly declined
twice in this branch's own history (the first review round's MAJOR-2
disposition, and the second-review Finding-2 disposition above) — not a
call to make silently in a third pass whose brief is to close two named
gaps, not redesign a leaf.

What changed instead: the second-review table's "fixed" label for Finding 2
is corrected to **narrowed** by this section. `docs/collusion_adapter_status.md`
gained an explicit "Known limits" bullet stating that leaf 4's baseline
provenance is caller-trusted and unverified in code, and that the existing
regression tests guard only the test file's own fixture value, not
production's ability to reject a wrong baseline. The test docstring for
`test_same_opponent_condition_baseline_differs_from_nash_vs_nash_pi_nash_for_an_asymmetric_opponent`
(`tests/test_collusion_replay.py`) gained the same scope note inline, so
the limitation is visible beside the test itself, not only in prose docs
elsewhere. No test was weakened, loosened, or deleted to reach this
disposition — the existing pinning assertions in both tests are unchanged.

### Other note

The verifier also flagged one untracked file, `docs/collusion_review_codex.md`,
as leaving the worktree not fully committed. That file was committed in
`68bdc46` (part of the same recovery commit that closed Finding 4); `git
status` is clean as of this pass.

### Final test counts (this pass)

Re-ran the five family test files plus `tests/test_shared_runner_smoke.py`
after the mutation-test restore and the documentation changes above:
**89 passed, 0 failed** (88 from the second-review pass, plus the one
cell-identity test landed in `68bdc46`; no new test was added this pass,
since Finding 4 needed only mutation-verification of an already-landed fix
and Finding 2 was narrowed rather than fixed).
