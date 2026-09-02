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
`docs/benchmark_qc.md` corroboration, a `verifier_taxonomy.md` §11 drift
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
