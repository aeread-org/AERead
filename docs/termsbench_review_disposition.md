# termsbench adapter — review disposition

Fix pass against the second-reviewer read in `docs/termsbench_review_codex.md`
(missing — that reviewer did not produce a report; nothing to reconcile
against it) and `docs/termsbench_review_claude.md` (present, 4 findings: 2
MAJOR, 2 MINOR). Every finding below was independently re-verified against
the code before any fix was made. All 4 are about the termsbench adapter's
own code (`src/aeread_families/termsbench/`), not about the kernel/runner
(`src/aeread/shared_runner/`), so none required a
`ledger_entries/termsbench.md` entry — no ledger file was created.

## MAJOR

### 1. `termsbench_protocol_compliance`'s reference hash omits `agent.r_a`

**Disposition: fixed.**

Verified directly: `_case_constants_sha256` (`measurement.py`) hashed only
`price_bounds`, `agent["role"]`, and `horizon`, never `agent["r_a"]` — the
individual-rationality anchor `environment.py`'s `_step_agent` actually tests
Accept/Offer actions against. Two payloads sharing the hashed fields but
differing in `r_a` produced an identical `source_sha256`, confirmed by
direct computation before the fix.

Fix: `src/aeread_families/termsbench/measurement.py` — `_case_constants_sha256`
now includes `"agent_r_a": float(payload["agent"]["r_a"])` in the hashed
`rule_payload`.

Test: `tests/test_termsbench_measurement.py::test_protocol_compliance_reference_hash_changes_with_the_agent_ir_anchor`
builds leaf 4 for two payloads identical except `r_a` and asserts their
`verifier.reference.source_sha256` now differ (it failed before the fix,
matching the review's own before/after computation).

### 2. Golden 3 ("no protected state is touched") is never asserted

**Disposition: fixed.**

Verified directly: both golden-3 tests
(`tests/test_termsbench_measurement.py::test_golden3_invalid_unauthorized_accept_earns_no_credit_but_stays_valid`
and
`tests/test_termsbench_environment.py::test_golden3_accept_without_counterpart_offer_is_agreement_violation`)
only inspected `result.terminal`, never `result.final_state`, so the
"no protected state (price, DB) is touched" invariant both docstrings
restate was not locked in by either test. Confirmed the underlying behavior
was already correct (`_step_agent`'s invalid-action branch returns before
appending to `agent_offers`/`counterpart_offers`/`transcript`, and `round`
is never incremented on that path).

Fix: added assertions to both existing golden-3 tests —
`result.final_state["round"] == 1`,
`result.final_state["agent_offers"] == ()`,
`result.final_state["counterpart_offers"] == ()`,
`result.final_state["transcript"] == ()` — rather than writing new tests,
since the existing tests are the golden-3 regression tests the invariant
belongs in.

## MINOR

### 3. `select_pilot_cell_seed`'s docstring overstates what it returns

**Disposition: fixed.**

Verified directly: the implementation returns the seed at the first rank
(lowest `difficulty_score`) whose bin matches, not the numerically smallest
seed among every candidate landing in that bin. These coincide on the
committed 30-case pilot (per the review's own finding) but are not the same
guarantee.

Fix: reworded the docstring in `src/aeread_families/termsbench/cases.py` to
describe the actual first-rank-wins semantics.

Test:
`tests/test_termsbench_cases.py::test_select_pilot_cell_seed_picks_first_rank_not_smallest_seed_within_a_bin`
monkeypatches `_difficulty_score_only` so two candidates share a bin but the
lower-scored one is the larger seed, and asserts the function returns the
first-rank (lower-scored) seed, not the smallest seed in the bin — a
regression to the old (incorrect) "smallest seed in bin" reading would fail
this test.

### 4. `FamilyManifest.measurement.primary_estimand` names a leaf half the corpus never declares

**Disposition: fixed (documentation only).**

Verified directly: `resolver.py`'s `missing_estimands` check only requires
the suite's `AnalysisPlan` to know about the family's declared
`primary_estimand` id, never that every case emits it — confirmed by
reading `resolve_run_plan`'s check (`src/aeread/shared_runner/resolver.py`).
No functional defect; the review itself found no evidence this breaks
anything today, only that nothing in `FamilyManifest` documents the
Overlap/No-deal split.

Fix: added a comment above `primary_estimand` in
`family_manifest()` (`environment.py`) stating the split explicitly and
noting the resolver's actual (weaker) check, so a future suite-level
report keyed on this id is not silently surprised by an empty No-deal half.
No new test: the behavior this documents (No-deal cases never emit
`termsbench_surplus_efficiency`) is already regression-tested by the
pre-existing `test_nodeal_case_declares_no_deal_agreement_and_protocol_compliance_only`.

## Refuted

None — all 4 findings in `docs/termsbench_review_claude.md` were confirmed
by independent re-verification before fixing.

## Deferred to ledger

None — no finding was about `src/aeread/shared_runner/` (the kernel/runner)
rather than this adapter.

## Verification

`tests/test_termsbench_*.py` + `tests/test_shared_runner_smoke.py`: 92
passed, 0 failed. Full repo suite: 808 passed, 31 skipped, 1 xfailed (the
skips/xfail are `tau3_retail`'s bridge-gated fidelity tests and one
pre-existing xfail, unchanged from before this pass).

## Second-review findings

Fix pass against `docs/termsbench_codex_triage.md` (the transcribed triage of
`docs/termsbench_review_codex.md` — a second, cross-model adversarial review;
6 declared findings, 5 confirmed, 1 refuted, 0 kernel). Every CONFIRMED
finding below was independently re-verified against the code before any fix,
and fixed in severity order (High, Medium, Medium, Low, Low). REFUTED item 2
was left untouched, as instructed. There were 0 KERNEL items this pass, so
`runner_defect_ledger.md` was not touched.

### 1 (High). Terminal-round walk-away probability is discarded

**Disposition: fixed.**

Verified directly: `kernel.resolve_counterpart_turn` returned `"timeout"` for
`round_k >= horizon` immediately after the acceptance check, without ever
computing or sampling `omega_k` (the walk-away hazard, eq. 7). Concretely,
`round_k=10, horizon=10, delta_bar=-0.2, u_accept=0.5, u_walkaway=0.0` has a
strictly positive hazard that should resolve to Reject, but the old code
returned Timeout without reading `u_walkaway` at all.

Fix: `src/aeread_families/termsbench/kernel.py` — moved the `omega_k`
computation and `u_walkaway` check ahead of the `round_k >= horizon` guard,
so it always runs; Timeout is reached only once neither Accept nor
walk-away fires.

Tests: `tests/test_termsbench_counterpart.py::test_resolve_counterpart_turn_still_samples_walkaway_at_the_terminal_round`
(failed before the fix: asserted `"reject"`, got `"timeout"`) and its
companion `test_resolve_counterpart_turn_times_out_at_the_terminal_round_only_when_the_hazard_does_not_fire`,
which locks in that Timeout is still reached when the (now-sampled) hazard
does not fire.

### 3 (Medium). Uncompared offline replay is labelled `match`

**Disposition: fixed.**

Verified directly: `ReplayReport.status` returned `"match"` whenever
`comparison` was `None` (a genuinely offline replay, e.g.
`replay_and_verify` called with no `original`), contradicting the module's
own docstring describing `None` as "not comparable". Callers could report
equivalence that was never established.

Fix: `src/aeread_families/termsbench/replay.py` — `status` now returns
`"not_comparable"` when `comparison is None`, `"mismatch"` for a present,
failing comparison, and `"match"` only for a present, passing one.

Test: `tests/test_termsbench_replay.py::test_replay_and_verify_without_an_original_is_not_comparable_not_a_fabricated_match`
exercises `replay_and_verify` itself (the production entrypoint, not a
hand-built `ReplayReport`) with no `original`, asserting the report is
honestly `not_comparable` (failed before the fix: got `"match"`).

### 4 (Medium). Timeout reports one more round than was used

**Disposition: fixed.**

Verified directly: `_step_counterpart` advanced `state["round"]`
unconditionally before branching on the counterpart's resolved decision, so
every counterpart-side termination — Accept, Reject/walk-away, and Timeout
alike — reported `rounds_used` one higher than the round the terminating
decision actually happened in. The finding's own cited test only asserted
this for Timeout (`rounds_used == horizon + 1`), but the root cause is
general, not Timeout-specific.

Fix: `src/aeread_families/termsbench/environment.py` — the round cursor now
only advances on the `"offer"` branch (i.e. when the episode genuinely
continues into another round); `terminal()` reports `state["round"]`
unchanged for every terminating branch.

Tests: corrected the pre-existing
`tests/test_termsbench_environment.py::test_case5_round_limit_reached_without_agreement_is_timeout`
assertion from `horizon + 1` to `horizon` (failed against the old code
before the fix: `11 == 10`); added `rounds_used` assertions to
`test_case1_counterpart_accepts_the_agents_offer` (`== 1`, failed before the
fix: `2 == 1`) and `test_case4_counterpart_walk_away_terminates_with_disagreement`
(`== 5`, failed before the fix: `6 == 5`) — neither previously asserted
anything about round count, so both other affected termination reasons are
now covered too.

### 5 (Low). Difficulty-purity test checks spelling rather than dependency

**Disposition: fixed (test-only; `generate_payload` was already pure).**

Verified directly: `test_difficulty_score_is_a_pure_function_of_the_generator_draw`
greps `generate_payload`'s own source text for the substrings
`state`/`outcome`/`terminal` — it would miss impurity hidden behind an
innocuously-named helper (e.g. one consulting a stable post-episode
global/cached trajectory, the finding's own example), and would false-fail
on an unrelated local variable that happens to share one of those names.
The current implementation is genuinely pure; only the test's proof of that
was weak.

Fix: none to production code. Added a behavioral companion test,
`tests/test_termsbench_cases.py::test_difficulty_score_is_unaffected_by_an_actually_completed_production_episode`,
which drives a real `(state, outcome, terminal)` triple into existence
through the actual production scheduler (`run_episode` + `TermsBenchPlugin`
+ `ScriptedTermsBenchHarness`), then confirms regenerating the same
`(family, regime, world_seed)` payload afterwards is still byte-identical to
before that episode ran. Verified this test actually catches the finding's
concrete failure scenario by temporarily wiring a post-episode-global-backed
`difficulty_score` through `cases.py`/`environment.py`, confirming the new
test failed, then reverting (clean `git diff`, both files unchanged from
`HEAD`) — no production code was ultimately touched. The pre-existing
substring-based test is left untouched, per policy against weakening
existing tests.

### 6 (Low). Replay scoring test uses the same scorer as its golden

**Disposition: fixed (test-only; `measurement.py`'s scorers were already
correct).**

Verified directly: `test_replayed_episode_recomputes_every_leaf_the_same_way`
computes both `original_scores` and `replayed_scores` via the same
`score_replayed_episode`/`TermsBenchScorer` functions, then only compares
surplus efficiency and protocol compliance between those two results. A
regression that made `score_surplus_efficiency` always return `0`, or
`score_protocol_compliance` ignore violations entirely, would break both
sides identically and this test would stay green.

Fix: none to production code. Added two companion tests in
`tests/test_termsbench_replay.py`, each re-deriving its leaf's cited
equation directly from the case's own numbers (eq. 56) or the outcome's own
`critical_violations` dict (eq. 66) — never by calling the scorer a second
time — and checking both `original_scores` and `replayed_scores` against
that independent value:
`test_replayed_episode_surplus_efficiency_matches_an_independently_derived_value`
(a one-round immediate-accept scenario whose `final_price` is the agent's
own scripted offer, so `SE+` is hand-computable) and
`test_replayed_episode_protocol_compliance_matches_an_independently_derived_violation_flag`
(golden 3's unauthorized-Accept scenario, which — unlike every existing
replay fixture — carries a genuine critical violation, needed to
discriminate this leaf at all). Verified both catch their finding's exact
regression by temporarily wiring each into `measurement.py` and confirming
(a) the new tests fail and (b) the pre-existing comparison-only test stays
green under the same mutation, then reverting (clean `git diff`). The
pre-existing comparison-only test is left untouched.

### Deferred to ledger

None — 0 KERNEL items this pass (`COUNTS: confirmed=5 refuted=1 kernel=0` in
`docs/termsbench_codex_triage.md`); no finding was about
`src/aeread/shared_runner/`.

### Verification

`tests/test_termsbench_*.py` + `tests/test_shared_runner_smoke.py`: 98
passed, 0 failed. Full repo suite: 814 passed, 31 skipped, 1 xfailed (same
pre-existing skips/xfail as before this pass, plus the 6 new tests added
above).
