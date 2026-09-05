# alympics.wac adapter — review disposition

Two review reports were expected (`docs/alympics_review_codex.md`,
`docs/alympics_review_claude.md`); only the Claude report exists in this
checkout (`git status`/`find` show no `alympics_review_codex.md` on disk —
the other reviewer produced nothing to process). Every finding below is from
`docs/alympics_review_claude.md`, each independently re-verified against the
code before any fix, per this pass's own ground rules (reviews can contain
false positives; nothing here was fixed on the review's word alone).

CRITICAL: 0 · MAJOR: 2 · MINOR: 3 (all as reported by the reviewer).

## MAJOR

### M1 — Golden 3 (invalid/unauthorized bid) is never driven end-to-end through `run_episode`/the Mode C phase graph

**Verified:** confirmed independently. `tests/test_alympics_wac_environment.py`'s
`test_delegate_round_flags_an_over_balance_bid_as_illegal_but_still_settles`
and `test_legal_hook_never_rejects_an_over_balance_bid_action`, plus
`tests/test_alympics_wac_measurement.py`'s
`test_golden_3_over_balance_bid_becomes_invalid_measurement_never_a_legal_loss`,
all call `_delegate_round`/`legal()` directly or hand-construct the
`round_log` dict fed to the measurement scorers — none of them go through
`observe`/`parse_action`/`legal`/`step` via `run_episode` the way goldens 1,
2, and 5 do.

**Disposition: fixed.**
1. Added
   `test_over_balance_bid_is_flagged_illegal_through_a_real_run_episode_step`
   (`tests/test_alympics_wac_environment.py`) — drives a full
   `reference_baseline` episode through `run_episode` with alex always
   bidding `999_999` (unreachable by any balance alex could accrue this
   episode) and every other seat bidding `proportional`; asserts every round
   `step()` itself logs shows `bid_legal["alex"] is False`, alex never wins,
   every other still-alive seat's legality is untouched, and alex ends up
   genuinely eliminated (an ordinary loss trajectory, never a special
   "illegal-but-rewarded" outcome).
2. Added
   `test_golden_3_over_balance_bid_end_to_end_through_run_episode_becomes_invalid_measurement`
   (`tests/test_alympics_wac_measurement.py`) — same real `run_episode`
   trajectory, fed into `score_bid_legality`/`score_terminal_wealth`/
   `score_survival` as the *actual* recorded `round_log` (never a
   hand-constructed stand-in), asserting all three go `invalid_measurement`
   for alex while `bob`'s own leaf stays `ok`.

Both new tests pass; the pre-existing unit-level tests are left in place
(they still cover the isolated-helper claims, which remain true and useful).

### M2 — Golden 4 (malformed/operational failure) is structurally unreachable through any real production code path

**Verified:** confirmed independently by tracing `environment.py`'s
production call site. `step()` (`environment.py:600-608`) always calls
`_delegate_round(...)` without `force_malformed`, which defaults to `None`;
in that branch, `wa.llm.call` is always bound to a closure that returns
`json.dumps({p.name: p.bidding for p in survivors})` — valid, complete JSON
by construction, since every alive seat's bid is already known before
`step()` runs. The `KeyError`/`TypeError` catch inside `_delegate_round`
(lines 318-329) can therefore never actually fire from `step()`'s own call
site or any of the four named scripted policies; it is reachable only via
`_delegate_round`'s private, test-only `force_malformed` parameter. This
matches `cases.py`'s own existing inline comment on `TERMINATION_REASONS`
almost verbatim — the code was already honest about this internally, but
`docs/alympics_adapter_spec.md`'s golden-4 table row and its e2e test-plan
bullet did not carry the same disclosure, so a QC auditor reading only the
spec could reasonably believe golden 4 is a real, live-reachable scenario.

**Disposition: fixed (documentation), not a code defect.** This is an
intentional consequence of the adapter's own design (per-instance `LLM.call`
replacement that "never sniffs or reconstructs bids from prompt text" —
`environment.py`'s module docstring) — rearchitecting `step()` to route
through upstream's real freeform-text parser so this branch could fire for
real would reintroduce exactly the prompt-content-sniffing risk the design
deliberately avoids, and is out of scope for a fix pass. Instead:
1. `docs/alympics_adapter_spec.md` §4's golden-4 row now explicitly states
   the branch is reachable only via `_delegate_round`'s test-only
   `force_malformed` hook, never through `step()`'s real call site.
2. §5's e2e bullet now names goldens 1/2/3/5 as `run_episode`-driven and
   golden 4 as unit-level-only, with the reason.
3. §6's stated limits gained a new bullet stating this plainly, matching
   `cases.py`'s existing candor.

No test was added for M2 itself (the finding class is "the spec
overclaims," not "the code has a bug reachable by a scripted trajectory" —
the existing `test_delegate_round_missing_key_raises_keyerror_caught_as_malformed`/
`test_delegate_round_unparseable_raises_typeerror_caught_as_malformed`/
`test_step_records_malformed_action_termination_without_crashing` already
cover the reachable, hand-invoked half of this claim).

## MINOR

### N1 — `cases.py` embeds the shared, mutable `PERSONAS` dict by reference into every case payload

**Verified:** confirmed independently. `build_case`'s
`data["payload"]["personas"] = PERSONAS` aliased the same module-level dict
into all 7 generated case payloads.

**Disposition: fixed.** Changed to `copy.deepcopy(PERSONAS)`
(`src/aeread_families/alympics_wac/cases.py`). Added
`test_each_cases_personas_payload_is_an_independent_object_not_a_shared_alias`
(`tests/test_alympics_wac_cases.py`), which builds its own fresh cases
(never the shared module-scoped `built` fixture, to avoid polluting other
tests in the file with an in-place mutation), mutates one case's
`payload["personas"]["alex"]["requirement"]`, and asserts neither another
case's payload nor the module-level `PERSONAS` constant changed.
Mutation-verified: reverting the fix locally (`"personas": PERSONAS`)
reproduces the failure this test now catches, then restored via `cp` from a
`/tmp` backup (never `git checkout`, per this pass's own ground rules).

### N2 — No programmatic near-duplicate detection across the 7 grid cells

**Verified:** confirmed independently. `build_all_cases()` only rejected an
exact `case_id` collision; nothing checked whether two cells shared the same
`(supply_regime, rounds, seed, policy_assignment)` tuple under different
names.

**Disposition: fixed.** Added `_grid_cell_dedup_key()` and a check in
`build_all_cases()` that raises `GridValidationError` on a repeated
`(supply_regime, rounds, seed, policy_assignment)` tuple across cells;
`build_all_cases()` now takes an optional `grid` parameter (defaulting to
the real module `GRID`) so tests can exercise this against a synthetic grid
without touching production data. Added
`test_build_all_cases_rejects_near_duplicate_grid_cells` and
`test_build_all_cases_allows_disjoint_seed_cells_that_otherwise_match` (the
latter guards against a regression that would wrongly flag the real grid's
own `mixed_policies_a`/`_seed2` disjoint-seed pairing). Confirmed the real
7-cell `GRID` still builds cleanly under the new check.

### N3 — Spec §3's bid-legality-gate wording is looser than §2's and than the implementation

**Verified:** confirmed independently by reading `environment.py`'s
`_check_winner_wrapper` (`environment.py:280-296`): the gate runs *during*
the call to `run_single_round` (before the real, delegated `_check_winner`
executes), not as a separate check "before `run_single_round` is invoked"
as §3 literally said.

**Disposition: fixed.** Reworded §3's bullet in
`docs/alympics_adapter_spec.md` to match §2's more precise "checked before
delegating to `_check_winner`, during the same call to `run_single_round`."
No behavior changed; documentation-only.

## Summary

| Finding | Severity | Disposition |
|---|---|---|
| M1 | major | fixed |
| M2 | major | fixed (documentation; not a code defect) |
| N1 | minor | fixed |
| N2 | minor | fixed |
| N3 | minor | fixed |

## Codex-review findings

Second adversarial review pass (`docs/alympics_review_codex.md`), triaged
independently in `docs/alympics_codex_triage.md` (9 CONFIRMED, 0 REFUTED,
0 OUT_OF_SCOPE; each finding re-verified against the code, several against
the real pinned upstream checkout, before any fix). Every finding below is
family-local; none are routed to the shared-runner defect ledger.

### 1 — `observe()` balance was pre-salary; no prior-round public history

**Fixed.** `observe()` (`environment.py`) now returns the post-salary
balance for the current round (upstream's own `_get_salary()` runs before
`execute_bidding()` inside `run_single_round`, so a real upstream agent
already sees this round's salary credited) and a leak-free
`public_round_history` (`round_id`/`supply`/`winners` for every completed
round -- never another seat's balance/hp/no_drink; the existing leakage-
audit invariant is unchanged). Test:
`test_observe_shows_post_salary_balance_and_prior_round_public_winners_history`
(`tests/test_alympics_wac_environment.py`); the pre-existing
`test_observation_never_contains_another_seats_status_or_bid` was updated
to check the leaked/leak-free figure against the new post-salary
semantics (never weakened -- it now checks both the raw and post-salary
forms never leak).

### 2 — `baseline_policy_id` was accepted but never referenced; scorers trusted any baseline

**Fixed.** `baseline_policy_id` is now part of leaf 1/2's own reference
identity (`source_sha256` and `reference_id`, via `_opponent_panel_sha256`/
`_reference_id_for_baseline`), threaded through
`AlympicsWacScorer.leaves_for_focal_seat`, and enforced by
`score_terminal_wealth`/`score_survival`: baseline evidence declared under
a policy that does not match the leaf's own declared baseline is rejected
as `invalid_measurement` (`baseline_policy_id_mismatch`). Tests:
`test_declared_baseline_policy_id_is_part_of_the_leaf_1_2_reference_identity`,
`test_scorer_leaves_for_focal_seat_threads_the_declared_baseline_policy_id_through`,
`test_score_terminal_wealth_rejects_baseline_evidence_declared_under_a_mismatched_policy`,
`test_score_survival_rejects_baseline_evidence_declared_under_a_mismatched_policy`
(`tests/test_alympics_wac_measurement.py`).

### 3 — Missing `bid_legal` evidence silently passed as legal

**Fixed.** `_missing_legality_round`/`_bid_legality_invalid_reason`
(`measurement.py`) now distinguish "no legality evidence recorded for a
round the seat actually bid in" (`bid_legality_evidence_missing`) from
both "checked and legal" and "a round the seat never played" (still a
non-issue). `score_bid_legality`/`score_terminal_wealth`/`score_survival`
all reject the missing-evidence case as `invalid_measurement`. Tests:
`test_score_bid_legality_flags_a_round_with_no_legality_evidence_at_all`,
`test_score_terminal_wealth_and_survival_reject_missing_legality_evidence`,
`test_score_bid_legality_still_skips_rounds_the_seat_never_played`
(`tests/test_alympics_wac_measurement.py`).

### 4 — Dead players retain positive "terminal wealth" with no distinguishing flag

**Fixed.** `score_terminal_wealth` now reports `actual_alive_at_terminal`/
`baseline_alive_at_terminal` metrics, mirroring what `score_survival`
already carried -- a dead focal seat's frozen-at-death balance is never
silently unqualified. Status stays `"ok"` (no literal upstream
"reset-to-zero" rule to violate, per the triage's own caveat); the fix is
the missing distinguishing flag, not a redefinition of terminal wealth.
Tests: `test_score_terminal_wealth_flags_a_dead_focal_seats_frozen_balance_as_not_alive`
plus a strengthened `test_golden_1_successful_reports_positive_wealth_and_full_survival`
(`tests/test_alympics_wac_measurement.py`).

### 5 — Replaying with no original in memory reported a fabricated `"match"`

**Fixed.** `ReplayReport.status` (`replay.py`) now returns `"not_compared"`
when `comparison is None` (the module's own documented "no original run in
memory" offline-replay mode), never the same `"match"` string a genuine
byte-identical reproduction would produce. Test:
`test_replay_and_verify_with_no_original_in_memory_never_fabricates_a_match`
(`tests/test_alympics_wac_replay.py`), which drives the real
`replay_and_verify` function with `original` omitted.

### 6 — A preloaded generic `waterAllocation` module bypassed the pinned-checkout guarantee

**Fixed.** `_load_upstream` (`environment.py`) now verifies the resolved
module's own `__file__` actually lives under the pinned checkout's
`src/waterAllocation.py` before trusting it, closing the gap where a
`sys.modules["waterAllocation"]` entry populated by anything else in the
process (before this function's own first call) was returned unchecked.
Test: `test_load_upstream_rejects_a_waterallocation_module_already_bound_elsewhere`
(`tests/test_alympics_wac_environment.py`).

### 7 — Golden 1's "full survival" name was never actually asserted

**Fixed.** `test_golden_1_successful_reports_positive_wealth_and_full_survival`
(`tests/test_alympics_wac_measurement.py`) now asserts the real,
hand-verified elimination pattern (alex/bob/david eliminated round 4,
cindy round 6, only eric alive at round 20) instead of only checking
status fields that would pass regardless of whether any seat actually
survived. Assertions were added, never removed.

### 8 — Malformed-action coverage depends on a test-only hook

**No action.** Same fact as review-1's M2 (already disposed above as
"fixed (documentation), not a code defect"); the triage's own verdict
confirms this independently and explicitly states no further action item
beyond what M2 already closed.

### 9 — Missing upstream checkout silently skips this family's real coverage

**Fixed.** `conftest.py`'s existing `pytest_terminal_summary` hook
(previously tau2/tau3-only) is generalized to a table of per-family
upstream-required policies, with a new
`AEREAD_ALYMPICS_UPSTREAM_REQUIRED` entry: off by default, turns a
matching skip into a failed run when set, mirroring the project's own
established fix for the identical shape of problem. `.github/workflows/
ci.yml` is intentionally left unchanged (tau2/tau3's identical env var is
also not set there; wiring either into default CI would require
provisioning a third-party checkout over the network, which this pass's
own provider-free/no-network constraint rules out -- consistent with the
existing project convention rather than a new inconsistency). Tests:
`tests/test_alympics_wac_upstream_required_gate.py` (4 tests), calling the
real `conftest.pytest_terminal_summary` against hand-built
`terminalreporter`/`config` stand-ins.

## Codex-review summary

| Finding | Severity (reviewer) | Disposition |
|---|---|---|
| 1 | High | fixed |
| 2 | High | fixed |
| 3 | High | fixed |
| 4 | High | fixed |
| 5 | High | fixed |
| 6 | High | fixed |
| 7 | Medium | fixed |
| 8 | Medium | no action (same fact as M2, already closed) |
| 9 | Medium | fixed |

## Verification follow-up

An independent cross-model check (`docs/alympics_fix_verification.md`)
re-verified the five commits this file describes and confirmed findings
3, 4, 5, 6, and 8 (M1/N1/N2/N3 too) as genuinely fixed with teeth, but
flagged findings **1, 2, 7, and 9** above as only partially addressed
despite this file's own "fixed" dispositions. This section records what
was actually done about each, on this branch, after that check.

### 1 — still open sub-claim: no other seat's bid in `public_round_history`

The first fix pass closed the salary-credit and winners-history gaps but
left `public_round_history` narrower than upstream's own
`round_results_prompt` broadcast in one more respect: upstream's own
broadcast also makes every survivor's already-settled *bid* for a
completed round public (`bidding_details`), which this adapter's
`observe()` omitted entirely. Verified this is genuinely public, not a
leakage-audit violation: only rounds already appended to
`state["round_log"]` are ever included (never the current round's own,
not-yet-collected bids), so there is no not-yet-revealed information at
stake. **Completed the fix, not just narrowed the doc:** `observe()` now
includes each already-completed round's recorded bids alongside
`round_id`/`supply`/`winners`; still never another seat's balance/hp/
no_drink. Spec section 6's disclosure paragraph is updated to match.
Tests: the existing
`test_observe_shows_post_salary_balance_and_prior_round_public_winners_history`
was strengthened (never weakened) to require the `bids` key, plus a new,
dedicated
`test_public_round_history_includes_every_seats_own_bid_for_an_already_completed_round`
(`tests/test_alympics_wac_environment.py`). Both fail with the right
`KeyError`/`AssertionError` before the fix. Mutation-verified: reverted
just the `"bids": dict(entry["bids"])` line (via `/tmp` backup, never
`git checkout`), confirmed both tests die, restored.

### 2 — still open: no baseline provenance check, only a label check

The substantive finding. `score_terminal_wealth`/`score_survival`
(`measurement.py`) bind `baseline_policy_id` to the leaf's own reference
identity and reject a mismatched *label*, but never verified the
underlying `baseline_final_players`/`baseline_round_log` was actually
produced by running that policy -- an arbitrary `dummy_players` mapping
carrying the expected label scored `"ok"` unconditionally (exactly what
`test_score_terminal_wealth_rejects_baseline_evidence_declared_under_a_mismatched_policy`'s
own "matched" branch demonstrated, unintentionally, all along).

Decided verification *is* possible inside this family: every one of the
four named scripted policies (`harness.POLICY_FUNCTIONS`) is a pure,
deterministic function of only `(requirement, no_drink)`, and settlement
is upstream's own fully deterministic `_delegate_round`. Given the case's
frozen supply schedule/personas/starting state and one policy assignment,
there is exactly one possible baseline trajectory -- so it can be
recomputed from scratch and compared, never merely declared.

**Completed the fix**, but deliberately at only one of the two API
layers, mirroring an already-established asymmetry in this same module
(the bare `score_bid_legality`/`score_settlement_exactness` functions vs.
`AlympicsWacScorer`'s case-bound wrappers): `AlympicsWacScorer.
score_terminal_wealth`/`score_survival` -- the real, case-bound path every
production caller (`replay.score_replayed_episode`) actually uses -- now
call a new `_recompute_baseline_episode` (round-by-round, through the
identical `environment._delegate_round` every live run/replay makes) and
reject any supplied baseline that does not reconcile with it exactly, seat
by seat, via a new `_baseline_state_mismatch_reason` gate, added ahead of
the existing label check. The bare `measurement.score_terminal_wealth`/
`score_survival` module-level functions are unchanged and still only check
the label -- documented explicitly, in both the module docstring and
`docs/alympics_adapter_status.md`, as a narrower, case-free building block
this module's own unit tests rely on to isolate other gates (malformed
action, missing legality evidence, degenerate supply, dead-seat flag)
without needing case/upstream machinery; every pre-existing call site of
the bare functions was therefore left untouched.

Tests (`tests/test_alympics_wac_measurement.py`), both new:
`test_scorer_score_terminal_wealth_rejects_a_fabricated_baseline_with_the_correct_label`
and
`test_scorer_score_survival_rejects_a_fabricated_baseline_with_the_correct_label`.
Each drives the real `AlympicsWacScorer` (via `plugin.build_scorer`) with
a `dummy_players`-shaped fabricated baseline carrying the correct
`baseline_policy_id` label and asserts `status == "invalid_measurement"`
with reason `baseline_state_not_reproducible_from_declared_policy`, then
asserts a genuine baseline (a real second run under the declared policy)
still scores `"ok"`. Both fail with `TypeError` (missing
`upstream_module`) before the fix, then with `AssertionError: 'ok' ==
'invalid_measurement'` once `upstream_module` is threaded in but the
mismatch gate is absent. Mutation-verified: removed both
`_baseline_state_mismatch_reason` call blocks (via `/tmp` backup, never
`git checkout`), confirmed both new tests die with exactly that
`'ok' == 'invalid_measurement'` failure, restored.

### 7 — test name and spec still claimed universal survival

No further code behavior to fix -- the golden's own assertions were
already strengthened (by the first pass) to check the real elimination
pattern; only the test's *name* and the spec's *prose* still claimed
"full survival." **Narrowed the doc claim** rather than adding a new
guard (there is no behavior to gate): renamed
`test_golden_1_successful_reports_positive_wealth_and_full_survival` to
`test_golden_1_successful_reports_positive_wealth_and_the_actual_elimination_pattern`,
and corrected `docs/alympics_adapter_spec.md` section 4's golden-1 table
row to state the verified pattern (Alex/Bob/David eliminated round 4,
Cindy round 6, only Eric survives to round 20) instead of "full
survival." No test-first/mutation cycle applies here: nothing in
production code changed.

### 9 — default CI still cannot fail on a missing upstream checkout

Confirmed true, and deliberately left true: wiring
`AEREAD_ALYMPICS_UPSTREAM_REQUIRED` (or provisioning the pinned checkout)
into `.github/workflows/ci.yml` by default would require network access
to fetch a third-party repository, which this whole pass's own
provider-free/no-network constraint rules out -- and doing it for this
family alone, while tau2/tau3's identical gate stays opt-in, would be a
one-off inconsistency rather than a fix. This is a shared,
cross-family `conftest.py` convention, not a alympics-local defect, so
changing its default behavior was treated as out of scope for a
family-local fix pass. **Narrowed the doc claim:** added a "Known limits"
bullet to `docs/alympics_adapter_status.md` stating plainly that a green
default CI run certifies only that `test_alympics_wac_cases.py`'s
upstream-free tests ran, and that certifying the rest requires explicitly
setting `AEREAD_ALYMPICS_UPSTREAM_REQUIRED=1`. No code or test change; no
test-first/mutation cycle applies.

### Verification

`tests/test_alympics_wac_cases.py`, `tests/test_alympics_wac_environment.py`,
`tests/test_alympics_wac_harness.py`, `tests/test_alympics_wac_measurement.py`,
`tests/test_alympics_wac_parity.py`, `tests/test_alympics_wac_replay.py`,
`tests/test_alympics_wac_upstream_required_gate.py`, and
`tests/test_shared_runner_smoke.py` together: 122 passed, 0 failed
(30 + 25 + 13 + 26 + 2 + 12 + 4 + 10).
